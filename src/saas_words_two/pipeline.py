from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import db, google_calibration, ids, judgment, opportunity_scoring, run_state, title_generation
from .contracts import (
    atomic_write_text,
    normalize_title,
    reverse_normalized_title,
    validate_title,
    validate_title_set,
)
from .judgment import JudgmentRequired


class ImplementationPendingError(RuntimeError):
    pass


class RetryRequired(RuntimeError):
    """A controlled stop that is not a judgment pause: e.g. max title-
    generation rounds exhausted with a real shortfall, or an opportunity pool
    too small to proceed. Run state is left RETRYING (not FAILED, not DONE);
    final outputs are not published. See docs/pipeline/10-title-generation.md
    9.3: "부족 원인이 기회 부족이면 수요·공급 조사 단계로 복귀한다."

    status defaults to RETRYING but can be CAPABILITY_STAGNATION (design 11's
    state list) when the shortfall reflects zero progress at all - not "try
    a bit more", but "this run's current data/approach cannot produce
    anything and needs a structural change" (e.g. DEMAND-001: no amount of
    re-running the same pipeline against the same source helped; only
    changing the data source or clustering approach did). Neither status
    changes retry mechanics - both are raised as this same exception type -
    only what gets persisted and reported to distinguish the two cases for
    HANDOFF/ACTIVE_ISSUES purposes.
    """

    def __init__(self, reason: str, *, status: str = "RETRYING"):
        self.reason = reason
        self.status = status
        super().__init__(f"{status}: {reason}")


class RecoveryRequired(RuntimeError):
    """design 11's RECOVERY_REQUIRED: an atomic operation's own postcondition
    check failed after the write (e.g. output/history/words.txt's on-disk
    tail doesn't match what was just atomically written). Retrying
    automatically is not safe here - continuing could double-append or
    otherwise compound the corruption - so this is a distinct exception from
    RetryRequired/JudgmentRequired that halts the run for manual inspection."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"RECOVERY_REQUIRED: {reason}")


@dataclass(frozen=True)
class RunOptions:
    mode: str
    target_count: int
    project_root: Path
    resume: bool = False
    run_id: str | None = None
    # 2026-08-17 (GKP-001): overrides EVERY round's candidate count (not just
    # round 1) to a fixed size, replacing both title_generation.first_round_size
    # and next_round_size(shortfall). Exists because the Keyword Planner gate's
    # real-world pass rate (~1%) makes the normal shortfall*2 top-up strategy
    # useless once close to target - a real run's round 2 requested only 27
    # candidates for a 14-item shortfall and got exactly 0 passes (expected:
    # at ~1%, a 27-item batch has ~78% odds of zero). User's directive: "use
    # 10,000 extraction as the standard unit," not "chase an exact target
    # count via small top-up rounds."
    round_size: int | None = None

    def validate(self) -> None:
        if self.mode not in {"production", "qa"}:
            raise ValueError("mode must be production or qa")
        if self.mode == "production" and self.target_count != 500:
            raise ValueError("production target_count must be exactly 500")
        if self.mode == "qa" and self.target_count < 10:
            raise ValueError("qa target_count must be at least 10")
        if self.round_size is not None and self.round_size < self.target_count:
            raise ValueError("round_size, if given, must be at least target_count")


STAGES = (
    "load_state",
    "source_access_test",
    "collect_sources",
    "filter_pain_sentences",
    "extract_and_cluster_problems",
    "score_demand",
    "collect_and_verify_supply",
    "score_opportunities",
    "review_opportunities",
    "generate_and_review_titles",
    "validate_outputs",
    "publish_mode_outputs",
    "build_google_validation_queue",
    "import_and_apply_human_feedback",
    "update_memory_and_git_checkpoint",
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _run_script(project_root: Path, script_name: str, *extra_args: str) -> subprocess.CompletedProcess:
    script_path = project_root / "scripts" / script_name
    return subprocess.run(
        [sys.executable, str(script_path), "--project-root", str(project_root), *extra_args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_or_raise(project_root: Path, script_name: str, *extra_args: str) -> subprocess.CompletedProcess:
    result = _run_script(project_root, script_name, *extra_args)
    if result.returncode != 0:
        raise RuntimeError(
            f"{script_name} exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def _run_dir(project_root: Path, state: run_state.RunState) -> Path:
    return run_state.run_dir(project_root, state.run_id)


def _history_path_for(project_root: Path, state: run_state.RunState) -> Path:
    if state.mode == "qa":
        return Path(state.context["qa_history_snapshot_path"])
    return project_root / "output" / "history" / "words.txt"


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _brief_context(project_root: Path) -> str:
    """Design 2.1: /input/brief.md is an optional file for target/excluded
    market, language, and similar scope settings ("입력이 없으면 광범위한
    B2B·B2C SaaS 문제를 대상으로 한다" - its absence just means no
    restriction, which is also a valid, common state). Prepended to judgment
    instructions wherever market/user scope actually matters, so an edited
    brief.md is honored instead of being silently ignored."""
    path = project_root / "input" / "brief.md"
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return ""
    return f"실행 브리프(범위 설정, /input/brief.md):\n{content}\n\n"


def _write_shortfall_intermediate(project_root: Path, state: run_state.RunState, titles: list[str]) -> Path:
    """Design 2.3/9.3: a run that ends short of its target count must save
    what it has to /output/intermediate/, never to the published outputs.
    Called at every RetryRequired shortfall point so the partial result
    survives the run (recoverable for inspection or a future --resume-style
    continuation) instead of being visible only inside data/local.db."""
    path = project_root / "output" / "intermediate" / f"{state.run_id}_shortfall_titles.txt"
    atomic_write_text(path, "\n".join(titles) + "\n" if titles else "")
    return path


def _pause_for_judgment(
    project_root: Path, state: run_state.RunState, stage_name: str, request_path: Path
) -> None:
    state.status = "RUNNING"
    state.awaiting_judgment = stage_name
    state.updated_at = ids.now_kst().isoformat()
    run_state.save(project_root, state)
    raise JudgmentRequired(stage_name, request_path)


# ---------------------------------------------------------------------------
# Stage: load_state
# ---------------------------------------------------------------------------


def _stage_load_state(conn, project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    if state.mode == "qa" and "qa_history_snapshot_path" not in state.context:
        history_path = project_root / "output" / "history" / "words.txt"
        snapshot_path = project_root / "output" / "qa" / state.run_id / "qa_history_snapshot.txt"
        lines = _read_lines(history_path)
        # An empty operational history must snapshot to a truly empty file -
        # "\n".join([]) + "\n" would instead write a single "\n", which
        # _read_lines()/splitlines() reads back as [''] (one blank line) not
        # [] (no lines), a mismatch with the real file it is meant to mirror.
        atomic_write_text(snapshot_path, "\n".join(lines) + "\n" if lines else "")
        state.context["qa_history_snapshot_path"] = str(snapshot_path)


# ---------------------------------------------------------------------------
# Stage: source_access_test / collect_sources
# collect_sources.py already performs the access test *and* incremental
# collection as one atomic operation (see docs/policies/04-data-source-policy.md
# 3.3); parse_sources.py's validation pass runs under the "collect_sources"
# stage name since the design's 15-stage list has no separate slot for it.
# ---------------------------------------------------------------------------


def _stage_source_access_test(conn, project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    _run_or_raise(project_root, "collect_sources.py")


def _stage_collect_sources(conn, project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    _run_or_raise(project_root, "parse_sources.py")


def _stage_filter_pain_sentences(conn, project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    _run_or_raise(project_root, "filter_pain_sentences.py")


# ---------------------------------------------------------------------------
# Stage: extract_and_cluster_problems (judgment checkpoint 1+2 combined:
# problem-structure extraction, ambiguous-cluster resolution, and the
# loss/purchase-intent judgment that docs/pipeline/07 6.3 folds into the same
# "문제 구조 추출" LLM step - gathering these in one request instead of two
# round-trips is a deliberate token-saving consolidation)
# ---------------------------------------------------------------------------


def _stage_extract_and_cluster_problems(
    conn, project_root: Path, options: RunOptions, state: run_state.RunState
) -> None:
    run_dir = _run_dir(project_root, state)
    stage_name = "extract_and_cluster_problems"

    if judgment.has_response(run_dir, stage_name):
        response = judgment.read_response(run_dir, stage_name)
        _consume_cluster_judgment(conn, response)
        return

    _run_or_raise(project_root, "cluster_problems.py")
    clusters_path = project_root / "output" / "intermediate" / "problem_clusters.json"
    clusters = json.loads(clusters_path.read_text(encoding="utf-8"))["clusters"]
    if not clusters:
        return

    items = [
        {
            "cluster_id": cluster["cluster_id"],
            "ambiguous": cluster["ambiguous"],
            "independent_user_count": cluster["independent_user_count"],
            "members": cluster["members"],
        }
        for cluster in clusters
    ]
    instructions = (
        _brief_context(project_root)
        + "각 군집이 실제 SaaS로 해결 가능한 반복 업무 문제인지 판단하라. ambiguous=true인 "
        "군집은 구성원이 정말 같은 문제인지 먼저 확인하고, 아니라면 problems를 여러 개로 "
        "나누거나 관련 없는 구성원은 제외하라. 채택하는 각 problem마다 target_user, task, "
        "workaround, pain, impact, desired_outcome, "
        "frequency(daily/weekly/monthly/occasional/unknown), "
        "risk_severity(none/moderate/severe), purchase_intent(none/weak/strong), "
        "has_manual_or_complaint_evidence(bool), member_candidate_ids(정수 배열)를 채워라. "
        "SaaS로 해결하기 어렵거나 일회성 개인 문제면 problems를 빈 배열로 두어라. "
        "브리프에 제외 시장/대상이 명시되어 있으면 해당 문제는 problems를 빈 배열로 두어라."
    )
    request_path = judgment.write_request(
        run_dir, stage_name, state.run_id, instructions, items, generated_at=ids.now_kst().isoformat()
    )
    _pause_for_judgment(project_root, state, stage_name, request_path)


def _consume_cluster_judgment(conn, response: dict) -> None:
    now = ids.now_kst().isoformat()
    for decision in response["decisions"]:
        for problem_spec in decision.get("problems", []):
            problem_id = ids.next_problem_id(conn)
            conn.execute(
                "INSERT INTO problems (problem_id, target_user, task, workaround, pain, impact, "
                "desired_outcome, frequency, risk_severity, purchase_intent, "
                "has_manual_or_complaint_evidence, status, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLUSTERED', ?, ?)",
                (
                    problem_id,
                    problem_spec.get("target_user"),
                    problem_spec.get("task"),
                    problem_spec.get("workaround"),
                    problem_spec.get("pain"),
                    problem_spec.get("impact"),
                    problem_spec.get("desired_outcome"),
                    problem_spec.get("frequency", "unknown"),
                    problem_spec.get("risk_severity", "none"),
                    problem_spec.get("purchase_intent", "none"),
                    int(bool(problem_spec.get("has_manual_or_complaint_evidence"))),
                    now,
                    now,
                ),
            )
            for candidate_id in problem_spec.get("member_candidate_ids", []):
                row = conn.execute(
                    "SELECT cs.item_id AS item_id, hi.by AS author, cs.sentence AS sentence "
                    "FROM candidate_sentences cs JOIN hn_items hi ON hi.id = cs.item_id WHERE cs.id = ?",
                    (candidate_id,),
                ).fetchone()
                if row is None:
                    continue
                evidence_id = ids.next_evidence_id(conn)
                conn.execute(
                    "INSERT INTO problem_evidence (evidence_id, problem_id, item_id, author, excerpt) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (evidence_id, problem_id, row["item_id"], row["author"], row["sentence"]),
                )
    conn.commit()


def _stage_score_demand(conn, project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    _run_or_raise(project_root, "score_demand.py")


# ---------------------------------------------------------------------------
# Stage: collect_and_verify_supply (judgment checkpoint 3: active-signal /
# supply-type classification per candidate, plus the four problem-level
# supply-gap booleans that feed the scarcity score)
# ---------------------------------------------------------------------------


def _stage_collect_and_verify_supply(
    conn, project_root: Path, options: RunOptions, state: run_state.RunState
) -> None:
    run_dir = _run_dir(project_root, state)
    stage_name = "collect_and_verify_supply"

    demand_passed = conn.execute(
        "SELECT COUNT(*) c FROM problems WHERE status = 'DEMAND_PASSED'"
    ).fetchone()["c"]
    if demand_passed == 0:
        return

    if judgment.has_response(run_dir, stage_name):
        response = judgment.read_response(run_dir, stage_name)
        _consume_supply_judgment(conn, response)
        return

    _run_or_raise(project_root, "collect_supply_candidates.py")

    candidate_rows = conn.execute(
        "SELECT sc.product_id, sc.problem_id, sc.name, sc.domain, sc.source, sc.evidence_url, "
        "sc.common_crawl_excerpt "
        "FROM supply_candidates sc "
        "WHERE sc.product_id NOT IN (SELECT product_id FROM supply_verification) "
        "AND sc.merged_into_product_id IS NULL"
    ).fetchall()
    problem_rows = conn.execute(
        "SELECT problem_id, task, target_user FROM problems WHERE status = 'DEMAND_PASSED'"
    ).fetchall()

    # design 7.2: candidates for the same problem may be the same underlying
    # product under a different domain/name (rebrand, country site, free/paid
    # tier, reseller, multi-domain company) - reviewed here as its own item
    # kind so the merge decision happens before/alongside signal judgment,
    # not as a separate unreviewed pipeline stage (the supply-analysis
    # skill's step 1 previously had no actual judgment checkpoint backing it).
    merge_review_items = [
        {
            "kind": "merge_candidates",
            "problem_id": problem_id,
            "candidates": [
                {"product_id": row["product_id"], "name": row["name"], "domain": row["domain"]}
                for row in rows
            ],
        }
        for problem_id, rows in _group_candidates_by_problem(candidate_rows).items()
        if len(rows) >= 2
    ]

    reliability_by_source = _load_source_reliability(conn)
    items = [
        {"kind": "product", **dict(row), "source_reliability": reliability_by_source.get(row["source"])}
        for row in candidate_rows
    ]
    items += [{"kind": "problem_gap", **dict(row)} for row in problem_rows]
    items += merge_review_items
    if not items:
        return

    instructions = (
        "kind=product 항목마다 8개 활성 신호(official_name, target_user, core_feature, "
        "signup_or_demo, pricing, recent_activity, product_docs, customer_references) 중 "
        "HN 게시글/댓글 텍스트와 common_crawl_excerpt(있는 경우 — 해당 도메인의 실제 "
        "웹페이지 발췌, 기능·가격·활성 상태 확인용 보강 증거)로 확인 가능한 것을 "
        "signals 객체(불리언)로 판정하고, supply_type을 direct/partial/generic/"
        "noncompeting 중 하나로 분류하라. "
        "source_reliability는 이 후보가 나온 데이터원이 지금까지 이 파이프라인에서 "
        "실제로 활성 공급으로 확인된 비율이다(status가 NO_DATA면 표본이 아직 부족하다는 "
        "뜻이고, 그 자체로 signals나 supply_type 판정을 대신하지 않는다 — 신호가 "
        "약할 때 추가로 의심할지 참고하는 보조 정보일 뿐이다). "
        "kind=problem_gap 항목마다 supply_gap_user_specific(특정 사용자 전용 제품 부족), "
        "supply_gap_no_strong_incumbent(강력한 기존 제품 부재), "
        "supply_gap_no_recent_entrants(최근 24개월 신규 공급 부족), "
        "supply_gap_unresolved_complaints(기존 제품의 반복 미해결 불만)를 판정하라. "
        "kind=merge_candidates 항목은 같은 문제에 딸린 후보 제품들이다 - 같은 회사의 "
        "여러 도메인, 리브랜딩 전후, 국가별 사이트, 무료·유료 버전, 파트너 재판매처럼 "
        "실제로는 동일 제품이면 kind=merge_group 결정을 추가해 canonical_product_id "
        "(대표로 남길 product_id)와 duplicate_product_ids(나머지, 대표에 합쳐질 "
        "product_id 배열)를 채워라. 병합할 대상이 없으면 해당 problem_id에 대한 "
        "merge_group 결정을 생략하라."
    )
    request_path = judgment.write_request(
        run_dir, stage_name, state.run_id, instructions, items, generated_at=ids.now_kst().isoformat()
    )
    _pause_for_judgment(project_root, state, stage_name, request_path)


def _load_source_reliability(conn) -> dict[str, dict]:
    """design roadmap 3차 개선 "데이터원별 신뢰도 보정" (source_reliability.py):
    read the most recently persisted per-source reliability snapshot
    (calibrate_source_reliability.py) for use as informative judgment
    context. Empty until that script has run at least once (e.g. a brand
    new local.db) - callers must treat a missing source as simply unknown,
    not as a signal of anything."""
    rows = conn.execute("SELECT * FROM source_reliability").fetchall()
    return {row["source"]: dict(row) for row in rows}


def _evidence_sources_for_ids(conn, evidence_ids: list[str]) -> list[str]:
    if not evidence_ids:
        return []
    placeholders = ",".join("?" for _ in evidence_ids)
    rows = conn.execute(
        f"SELECT DISTINCT hi.source AS source FROM problem_evidence pe "
        f"JOIN hn_items hi ON hi.id = pe.item_id WHERE pe.evidence_id IN ({placeholders})",
        evidence_ids,
    ).fetchall()
    return sorted(row["source"] for row in rows)


def _group_candidates_by_problem(candidate_rows) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for row in candidate_rows:
        grouped.setdefault(row["problem_id"], []).append(row)
    return grouped


def _consume_supply_judgment(conn, response: dict) -> None:
    from . import supply

    # Applied before the product/problem_gap decisions in the same response
    # so that a duplicate's merged_into_product_id is already set by the time
    # anything downstream looks at it - order within response["decisions"]
    # is not guaranteed to put merge_group entries first.
    for decision in response["decisions"]:
        if decision.get("kind") != "merge_group":
            continue
        canonical_id = decision["canonical_product_id"]
        for duplicate_id in decision.get("duplicate_product_ids", []):
            if duplicate_id == canonical_id:
                continue
            conn.execute(
                "UPDATE supply_candidates SET merged_into_product_id = ? WHERE product_id = ?",
                (canonical_id, duplicate_id),
            )

    for decision in response["decisions"]:
        kind = decision.get("kind")
        if kind == "product":
            signals = decision["signals"]
            signal_count = supply.active_signal_count(signals)
            active = supply.is_active_supply(signals)
            supply_type = decision["supply_type"]
            weight = supply.SUPPLY_TYPE_WEIGHTS.get(supply_type, 0.0) if active else 0.0
            conn.execute(
                "INSERT INTO supply_verification (product_id, signals, signal_count, active, supply_type, weight) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(product_id) DO UPDATE SET signals=excluded.signals, "
                "signal_count=excluded.signal_count, active=excluded.active, "
                "supply_type=excluded.supply_type, weight=excluded.weight",
                (
                    decision["product_id"],
                    json.dumps(signals, sort_keys=True),
                    signal_count,
                    int(active),
                    supply_type,
                    weight,
                ),
            )
        elif kind == "problem_gap":
            conn.execute(
                "UPDATE problems SET supply_gap_user_specific = ?, supply_gap_no_strong_incumbent = ?, "
                "supply_gap_no_recent_entrants = ?, supply_gap_unresolved_complaints = ? WHERE problem_id = ?",
                (
                    int(bool(decision.get("supply_gap_user_specific"))),
                    int(bool(decision.get("supply_gap_no_strong_incumbent"))),
                    int(bool(decision.get("supply_gap_no_recent_entrants"))),
                    int(bool(decision.get("supply_gap_unresolved_complaints"))),
                    decision["problem_id"],
                ),
            )
    conn.commit()


def _stage_score_opportunities(conn, project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    _run_or_raise(project_root, "score_opportunities.py")


# ---------------------------------------------------------------------------
# Stage: review_opportunities (judgment checkpoint 4: opportunity-reviewer's
# GENERATE_TITLES / RESEARCH_MORE / REJECT / SCARCITY_PRIORITY call - this has
# no dedicated script per docs/architecture/06, only the top-scoring subset is
# reviewed; everything else keeps score_opportunities.py's provisional_decision)
# ---------------------------------------------------------------------------

_MAX_OPPORTUNITIES_REVIEWED = 20


def _stage_review_opportunities(
    conn, project_root: Path, options: RunOptions, state: run_state.RunState
) -> None:
    run_dir = _run_dir(project_root, state)
    stage_name = "review_opportunities"

    if judgment.has_response(run_dir, stage_name):
        response = judgment.read_response(run_dir, stage_name)
        grades = {
            row["problem_id"]: row["scarcity_grade"]
            for row in conn.execute("SELECT problem_id, scarcity_grade FROM opportunities").fetchall()
        }
        for decision in response["decisions"]:
            final_decision = decision["decision"]
            # Design 8.5: "C 등급은 제목을 생성하지 않고 추가 조사 대상으로 저장한다" - a
            # hard rule, not left to reviewer judgment. Enforce it in code regardless of
            # what the judgment response says, rather than trusting the instruction alone.
            if grades.get(decision["problem_id"]) == "C" and final_decision in (
                "GENERATE_TITLES",
                "SCARCITY_PRIORITY",
            ):
                final_decision = "RESEARCH_MORE"
            conn.execute(
                "UPDATE opportunities SET decision = ? WHERE problem_id = ?",
                (final_decision, decision["problem_id"]),
            )
        conn.commit()
        return

    opportunities = [dict(row) for row in conn.execute("SELECT * FROM opportunities").fetchall()]
    if not opportunities:
        return

    ranked = opportunity_scoring.sort_opportunities(opportunities)
    top = [o for o in ranked if o["decision"] in ("GENERATE_TITLES", "RESEARCH_MORE")][
        :_MAX_OPPORTUNITIES_REVIEWED
    ]
    if not top:
        return

    problems_by_id = {row["problem_id"]: dict(row) for row in conn.execute("SELECT * FROM problems").fetchall()}
    reliability_by_source = _load_source_reliability(conn)
    items = []
    for opp in top:
        evidence_sources = _evidence_sources_for_ids(conn, json.loads(opp["evidence_ids"]))
        items.append(
            {
                "problem_id": opp["problem_id"],
                "target_user": problems_by_id.get(opp["problem_id"], {}).get("target_user"),
                "task": problems_by_id.get(opp["problem_id"], {}).get("task"),
                "pain": problems_by_id.get(opp["problem_id"], {}).get("pain"),
                "demand_score": opp["demand_score"],
                "supply_scarcity_score": opp["supply_scarcity_score"],
                "scarcity_grade": opp["scarcity_grade"],
                "priority_score": opp["priority_score"],
                "confidence": opp["confidence"],
                "provisional_decision": opp["decision"],
                "evidence_source_reliability": {
                    source: reliability_by_source.get(source) for source in evidence_sources
                },
            }
        )
    instructions = (
        _brief_context(project_root)
        + "각 기회를 독립 검토해 GENERATE_TITLES, RESEARCH_MORE, REJECT, SCARCITY_PRIORITY 중 "
        "하나로 최종 판정하라. 공급 조사가 충분치 않으면 RESEARCH_MORE, 실제 수요가 없거나 "
        "강력한 경쟁 제품이 다수면 REJECT, 수요는 낮지만 공급이 극도로 부족하고 반복 손실이 "
        "확인되면 SCARCITY_PRIORITY를 사용하라. provisional_decision은 참고용 코드 판정이다. "
        "scarcity_grade가 C인 항목은 GENERATE_TITLES나 SCARCITY_PRIORITY로 판정하지 마라 "
        "(C 등급은 제목 생성 대상이 아니다 — RESEARCH_MORE 또는 REJECT만 가능). "
        "브리프에 제외 시장으로 명시된 대상이면 REJECT하라. "
        "evidence_source_reliability는 이 기회의 근거가 나온 데이터원별로 지금까지 "
        "이 파이프라인에서 실제로 수요 관문을 통과한 비율이다(NO_DATA는 표본 부족, "
        "숫자 자체를 판정 기준으로 강제하지 않는다 — 근거 신뢰도를 가늠하는 참고 정보다)."
    )
    request_path = judgment.write_request(
        run_dir, stage_name, state.run_id, instructions, items, generated_at=ids.now_kst().isoformat()
    )
    _pause_for_judgment(project_root, state, stage_name, request_path)


# ---------------------------------------------------------------------------
# Stage: generate_and_review_titles (judgment checkpoints 5+6: title
# generation, then semantic-duplicate/clarity review; iterates rounds per
# docs/pipeline/10-title-generation.md 9.1/9.3 via a small generate/review
# phase state machine stored in state.context)
# ---------------------------------------------------------------------------


def _eligible_opportunities(conn) -> list[dict]:
    # scarcity_grade != 'C' is defense-in-depth: _stage_review_opportunities already
    # forces a C-grade decision away from GENERATE_TITLES/SCARCITY_PRIORITY, but this
    # query is the actual title-generation gate, so it must not rely solely on that
    # upstream guard staying correct (design 8.5's "C 등급은 제목을 생성하지 않는다").
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE decision IN ('GENERATE_TITLES', 'SCARCITY_PRIORITY') "
        "AND scarcity_grade != 'C'"
    ).fetchall()
    return [dict(row) for row in rows]


def _approved_titles(conn, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT title, problem_id FROM titles WHERE run_id = ? AND status = 'approved'", (run_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def _write_generation_request(
    conn, run_dir: Path, state: run_state.RunState, round_no: int, target_count: int, approved_count: int
) -> Path | None:
    eligible = _eligible_opportunities(conn)
    if not eligible:
        return None

    shortfall = target_count - approved_count
    candidate_count = (
        title_generation.first_round_size(target_count)
        if round_no == 1
        else title_generation.next_round_size(shortfall)
    )
    allocation = title_generation.allocate_title_slots(
        [{"problem_id": o["problem_id"], "priority_score": o["priority_score"]} for o in eligible],
        candidate_count,
    )
    problems_by_id = {row["problem_id"]: dict(row) for row in conn.execute("SELECT * FROM problems").fetchall()}
    items = []
    for opp in eligible:
        slots = allocation.get(opp["problem_id"], 0)
        if slots <= 0:
            continue
        problem = problems_by_id.get(opp["problem_id"], {})
        items.append(
            {
                "problem_id": opp["problem_id"],
                "target_user": problem.get("target_user"),
                "task": problem.get("task"),
                "pain": problem.get("pain"),
                "desired_outcome": problem.get("desired_outcome"),
                "slot_count": slots,
            }
        )
    if not items:
        return None

    instructions = (
        "각 기회에 대해 slot_count만큼 영어 2단어 Title Case 제목 후보를 생성하라. "
        "정확히 두 단어, 영문 알파벳만, 단어 사이 공백 하나, 하이픈/숫자/기호 금지. "
        "대상+기능, 업무+도구, 문제+해결, 결과+기능, 위험+방지, 정보+관리 조합을 사용하고 "
        "지나치게 추상적이거나 유명 서비스와 동일한 이름은 피하라."
    )
    return judgment.write_request(
        run_dir, "generate_titles", state.run_id, instructions, items,
        round_no=round_no, generated_at=ids.now_kst().isoformat(),
    )


def _consume_title_generation(conn, project_root: Path, state: run_state.RunState, response: dict) -> None:
    history_norm = {normalize_title(line) for line in _read_lines(_history_path_for(project_root, state)) if line.strip()}
    blocklist_norm = {
        normalize_title(line) for line in _read_lines(project_root / "input" / "blocklist.txt") if line.strip()
    }
    existing_norms = set(history_norm)
    for row in conn.execute(
        "SELECT normalized FROM titles WHERE run_id = ? AND status IN ('approved', 'pending_review')",
        (state.run_id,),
    ).fetchall():
        existing_norms.add(row["normalized"])

    now = ids.now_kst().isoformat()
    for decision in response["decisions"]:
        problem_id = decision["problem_id"]
        for raw_title in decision.get("titles", []):
            title = raw_title.strip()
            if not validate_title(title).valid:
                continue
            norm = normalize_title(title)
            rev = reverse_normalized_title(title)
            if norm in existing_norms or norm in blocklist_norm or rev in existing_norms:
                continue
            existing_norms.add(norm)
            conn.execute(
                "INSERT OR IGNORE INTO titles (title, normalized, problem_id, run_id, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending_review', ?)",
                (title, norm, problem_id, state.run_id, now),
            )
    conn.commit()


def _write_review_request(conn, run_dir: Path, state: run_state.RunState, round_no: int) -> Path | None:
    pending = conn.execute(
        "SELECT title, problem_id FROM titles WHERE run_id = ? AND status = 'pending_review'", (state.run_id,)
    ).fetchall()
    if not pending:
        return None
    items = [{"title": row["title"], "problem_id": row["problem_id"]} for row in pending]
    instructions = (
        "각 제목의 의미 중복과 명확성을 검토하라. 다른 후보와 의미가 겹치거나, 어떤 SaaS인지 "
        "추측할 수 없을 만큼 추상적이거나, 유명 서비스와 명백히 동일하면 approve=false로 "
        "판정하고 reason을 남겨라. 그렇지 않으면 approve=true."
    )
    return judgment.write_request(
        run_dir, "review_titles", state.run_id, instructions, items,
        round_no=round_no, generated_at=ids.now_kst().isoformat(),
    )


def _consume_title_review(conn, response: dict, run_id: str) -> None:
    for decision in response["decisions"]:
        status = "approved" if decision.get("approve") else "rejected"
        conn.execute(
            "UPDATE titles SET status = ?, reason = ? WHERE run_id = ? AND title = ? AND status = 'pending_review'",
            (status, decision.get("reason"), run_id, decision["title"]),
        )
    conn.commit()


def _stage_generate_and_review_titles(
    conn, project_root: Path, options: RunOptions, state: run_state.RunState
) -> None:
    run_dir = _run_dir(project_root, state)
    target_count = options.target_count

    round_no = state.context.get("title_round", 1)
    phase = state.context.get("title_phase", "generate")

    while True:
        approved = _approved_titles(conn, state.run_id)
        if len(approved) >= target_count:
            return

        if round_no > title_generation.MAX_ROUNDS:
            # Zero progress across every round is a stronger signal than "ran
            # out of rounds while still gaining ground" - it means this run's
            # current opportunity pool cannot produce anything at all, not
            # just not enough (design 11's CAPABILITY_STAGNATION vs RETRYING).
            status = "CAPABILITY_STAGNATION" if not approved else "RETRYING"
            state.status = status
            state.context["title_round"] = round_no
            run_state.save(project_root, state)
            _write_shortfall_intermediate(project_root, state, [item["title"] for item in approved])
            raise RetryRequired(
                f"reached max rounds ({title_generation.MAX_ROUNDS}) with only "
                f"{len(approved)}/{target_count} approved titles",
                status=status,
            )

        if phase == "generate":
            if judgment.has_response(run_dir, "generate_titles", round_no):
                response = judgment.read_response(run_dir, "generate_titles", round_no)
                _consume_title_generation(conn, project_root, state, response)
                phase = "review"
                state.context["title_phase"] = phase
                continue

            request_path = _write_generation_request(conn, run_dir, state, round_no, target_count, len(approved))
            if request_path is None:
                # No eligible opportunities/slots at all in a round where
                # nothing has been approved yet means the upstream demand/
                # supply pipeline produced nothing usable for this run - not
                # a "try once more" situation (design 11 CAPABILITY_STAGNATION).
                # If earlier rounds DID land some titles, this is ordinary
                # exhaustion of the pool and stays RETRYING.
                status = "CAPABILITY_STAGNATION" if not approved else "RETRYING"
                state.status = status
                run_state.save(project_root, state)
                _write_shortfall_intermediate(project_root, state, [item["title"] for item in approved])
                raise RetryRequired(
                    "no eligible opportunities or slots available for title generation", status=status
                )
            state.context["title_round"] = round_no
            state.context["title_phase"] = phase
            _pause_for_judgment(project_root, state, "generate_titles", request_path)

        else:  # phase == "review"
            if judgment.has_response(run_dir, "review_titles", round_no):
                response = judgment.read_response(run_dir, "review_titles", round_no)
                _consume_title_review(conn, response, state.run_id)
                round_no += 1
                phase = "generate"
                state.context["title_round"] = round_no
                state.context["title_phase"] = phase
                continue

            request_path = _write_review_request(conn, run_dir, state, round_no)
            if request_path is None:
                round_no += 1
                phase = "generate"
                state.context["title_round"] = round_no
                state.context["title_phase"] = phase
                continue
            state.context["title_round"] = round_no
            state.context["title_phase"] = phase
            _pause_for_judgment(project_root, state, "review_titles", request_path)


# ---------------------------------------------------------------------------
# Stage: validate_outputs
# ---------------------------------------------------------------------------


def _load_title_observations(project_root: Path) -> dict[str, list[dict]]:
    ledger_path = project_root / "memory" / "human_feedback" / "google_supply_observations.jsonl"
    if not ledger_path.exists():
        return {}
    observations = [
        json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return google_calibration.group_title_observations_by_title(observations)


def _apply_title_calibration(
    conn, project_root: Path, run_id: str, approved_rows: list
) -> dict[str, dict]:
    """design 4.8: TITLE_QUERY human observations calibrate title quality
    separately from the opportunity's (MARKET_QUERY-driven) priority_score.
    Computed and persisted for every approved title on every validate_outputs
    pass, same rationale as the inline supply calibration in
    score_opportunities.py (never stale, not dependent on a separate script
    happening to run first)."""
    observations_by_title = _load_title_observations(project_root)
    calibration_by_title: dict[str, dict] = {}
    for row in approved_rows:
        title = row["title"]
        calibration = google_calibration.compute_title_calibration(observations_by_title.get(title, []))
        calibration_by_title[title] = calibration
        conn.execute(
            "UPDATE titles SET google_title_footprint = ?, google_title_collision_class = ?, "
            "human_title_validation_count = ?, title_collision_adjustment = ? "
            "WHERE run_id = ? AND title = ?",
            (
                calibration["google_title_footprint"],
                calibration["google_title_collision_class"],
                calibration["validation_count"],
                calibration["title_collision_adjustment"],
                run_id,
                title,
            ),
        )
    conn.commit()
    return calibration_by_title


def _stage_validate_outputs(conn, project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    approved = conn.execute(
        "SELECT title, problem_id FROM titles WHERE run_id = ? AND status = 'approved'", (state.run_id,)
    ).fetchall()
    opportunities_by_id = {
        row["problem_id"]: dict(row) for row in conn.execute("SELECT * FROM opportunities").fetchall()
    }
    calibration_by_title = _apply_title_calibration(conn, project_root, state.run_id, approved)
    scored = [
        {
            "title": row["title"],
            "problem_id": row["problem_id"],
            "priority_score": opportunities_by_id.get(row["problem_id"], {}).get("priority_score", 0.0),
            "title_collision_adjustment": calibration_by_title[row["title"]]["title_collision_adjustment"],
        }
        for row in approved
        # design 4.8: an explicit user-flagged brand conflict is excluded
        # outright, not merely down-ranked - the same treatment as any other
        # hard validation failure (contracts.validate_title_set already
        # excludes exact/case/reversed history duplicates the same way).
        if calibration_by_title[row["title"]]["google_title_collision_class"] != "BRAND_CONFLICT"
    ]
    selected = title_generation.select_final_titles(scored, options.target_count)
    if len(selected) != options.target_count:
        state.status = "RETRYING"
        run_state.save(project_root, state)
        _write_shortfall_intermediate(project_root, state, [item["title"] for item in selected])
        raise RetryRequired(
            f"only {len(selected)}/{options.target_count} titles survive final selection "
            "under the 30%-per-opportunity cap"
        )

    selected_titles = [item["title"] for item in selected]
    placeholders = ",".join("?" for _ in selected_titles)
    conn.execute(
        f"UPDATE titles SET status = 'selected' WHERE run_id = ? AND title IN ({placeholders})",
        (state.run_id, *selected_titles),
    )
    conn.commit()

    history = _read_lines(_history_path_for(project_root, state))
    blocklist = _read_lines(project_root / "input" / "blocklist.txt")
    errors = validate_title_set(
        selected_titles, target_count=options.target_count, history=history, blocklist=blocklist
    )
    if errors:
        state.status = "FAILED"
        run_state.save(project_root, state)
        raise RuntimeError("final title set failed validate_title_set: " + "; ".join(errors))

    counts_by_problem: dict[str, int] = {}
    for item in selected:
        counts_by_problem[item["problem_id"]] = counts_by_problem.get(item["problem_id"], 0) + 1
    distribution_violations = title_generation.check_distribution(counts_by_problem, options.target_count)
    if distribution_violations:
        state.status = "FAILED"
        run_state.save(project_root, state)
        raise RuntimeError("distribution check failed: " + "; ".join(distribution_violations))

    state.context["final_titles"] = selected_titles


# ---------------------------------------------------------------------------
# Stage: publish_mode_outputs
# ---------------------------------------------------------------------------


def _write_opportunities_jsonl(conn, path: Path, final_titles: list[str]) -> None:
    if not final_titles:
        atomic_write_text(path, "")
        return
    placeholders = ",".join("?" for _ in final_titles)
    problem_ids = sorted(
        {
            row["problem_id"]
            for row in conn.execute(
                f"SELECT DISTINCT problem_id FROM titles WHERE title IN ({placeholders})", final_titles
            ).fetchall()
        }
    )
    lines = []
    for problem_id in problem_ids:
        opp = conn.execute("SELECT * FROM opportunities WHERE problem_id = ?", (problem_id,)).fetchone()
        problem = conn.execute("SELECT * FROM problems WHERE problem_id = ?", (problem_id,)).fetchone()
        if opp is None or problem is None:
            continue
        record = {
            "problem_id": problem_id,
            "target_user": problem["target_user"],
            "task": problem["task"],
            "workaround": problem["workaround"],
            "pain": problem["pain"],
            "demand_score": opp["demand_score"],
            "supply_scarcity_score": opp["supply_scarcity_score"],
            "opportunity_score": opp["priority_score"],
            "confidence": opp["confidence"],
            "decision": opp["decision"],
            "evidence_ids": json.loads(opp["evidence_ids"]),
            "product_ids": json.loads(opp["product_ids"]),
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def _stage_publish_mode_outputs(
    conn, project_root: Path, options: RunOptions, state: run_state.RunState
) -> None:
    final_titles = state.context.get("final_titles")
    if final_titles is None:
        rows = conn.execute(
            "SELECT title FROM titles WHERE run_id = ? AND status = 'selected'", (state.run_id,)
        ).fetchall()
        final_titles = [row["title"] for row in rows]

    content = "\n".join(final_titles) + "\n"

    if state.mode == "production":
        final_path = project_root / "output" / "generated" / state.context["generated_filename"]
        atomic_write_text(final_path, content)

        history_path = project_root / "output" / "history" / "words.txt"
        history = _read_lines(history_path)
        # Idempotency guard: if this stage previously wrote final_path but then
        # failed/crashed before (or during) the history append, a resume would
        # re-enter this function from the top. Without this check it would
        # append the same titles to words.txt a second time, corrupting the
        # operational history with real duplicates.
        history_norm = {normalize_title(t) for t in history}
        already_appended = bool(final_titles) and all(
            normalize_title(t) in history_norm for t in final_titles
        )
        if not already_appended:
            atomic_write_text(history_path, "\n".join(history + final_titles) + "\n")
            # design 2.3: "현재 실행 결과와 정확히 일치하는 증가분 검증" - verify the
            # write actually took effect as intended before treating this run
            # as complete. A mismatch here means atomic_write_text's own
            # postcondition failed (e.g. a concurrent writer, a filesystem
            # anomaly) - retrying automatically is not safe (could double-
            # append), so this halts for manual inspection (design 11
            # RECOVERY_REQUIRED) rather than raising a generic error.
            history_after = _read_lines(history_path)
            if history_after[len(history):] != final_titles:
                state.status = "RECOVERY_REQUIRED"
                run_state.save(project_root, state)
                raise RecoveryRequired(
                    f"output/history/words.txt increment did not match this run's final_titles "
                    f"after atomic write (expected {len(final_titles)} new lines, "
                    f"found {len(history_after) - len(history)})"
                )

        _write_opportunities_jsonl(conn, project_root / "output" / "final" / "opportunities.jsonl", final_titles)
    else:
        qa_dir = project_root / "output" / "qa" / state.run_id
        atomic_write_text(qa_dir / "generated" / "saas_words_qa.txt", content)
        _write_opportunities_jsonl(conn, qa_dir / "opportunities.jsonl", final_titles)
        report = (
            "# QA Report\n\n"
            f"- run_id: {state.run_id}\n"
            f"- target_title_count: {state.target_title_count}\n"
            f"- approved_titles: {len(final_titles)}\n"
            f"- status: {state.status}\n"
        )
        atomic_write_text(qa_dir / "qa_report.md", report)


# ---------------------------------------------------------------------------
# Stage: build_google_validation_queue / import_and_apply_human_feedback
# QA writes to its own run directory rather than the shared output/review and
# memory/human_feedback locations, per output isolation rules; it still
# exercises every step (QA acceptance 15.2 items 15-19) using the bundled
# qa/samples fixture for the human-input CSV.
# ---------------------------------------------------------------------------


def _stage_build_google_validation_queue(
    conn, project_root: Path, options: RunOptions, state: run_state.RunState
) -> None:
    if state.mode == "qa":
        output_path = project_root / "output" / "qa" / state.run_id / "google_validation_queue.csv"
        _run_or_raise(project_root, "build_google_validation_queue.py", "--output", str(output_path))
    else:
        _run_or_raise(project_root, "build_google_validation_queue.py")


def _stage_import_and_apply_human_feedback(
    conn, project_root: Path, options: RunOptions, state: run_state.RunState
) -> None:
    if state.mode == "qa":
        qa_dir = project_root / "output" / "qa" / state.run_id
        input_path = project_root / "qa" / "samples" / "human_google_checks_valid.csv"
        queue_path = qa_dir / "google_validation_queue.csv"
        ledger_path = qa_dir / "google_supply_observations.jsonl"
        report_path = qa_dir / "google_feedback_import_report.md"
        normalized_path = qa_dir / "google_normalized_observations.json"
        metrics_path = qa_dir / "google_calibration_metrics.json"
    else:
        input_path = project_root / "input" / "human_google_checks.csv"
        queue_path = project_root / "output" / "review" / "google_validation_queue.csv"
        ledger_path = project_root / "memory" / "human_feedback" / "google_supply_observations.jsonl"
        report_path = project_root / "output" / "review" / "google_feedback_import_report.md"
        normalized_path = project_root / "output" / "logs" / "google_normalized_observations.json"
        metrics_path = project_root / "memory" / "human_feedback" / "google_calibration_metrics.json"

    _run_or_raise(
        project_root,
        "import_human_google_checks.py",
        "--run-id", state.run_id,
        "--input", str(input_path),
        "--queue", str(queue_path),
        "--ledger", str(ledger_path),
        "--report", str(report_path),
    )
    _run_or_raise(
        project_root, "normalize_google_feedback.py", "--ledger", str(ledger_path), "--output", str(normalized_path)
    )
    _run_or_raise(
        project_root, "calibrate_supply_predictions.py", "--ledger", str(ledger_path), "--metrics", str(metrics_path)
    )
    _run_or_raise(project_root, "apply_human_calibration.py", "--ledger", str(ledger_path))


def _stage_update_memory_and_git_checkpoint(
    conn, project_root: Path, options: RunOptions, state: run_state.RunState
) -> None:
    # design roadmap 3차 개선 "데이터원별 신뢰도 보정": recompute the
    # per-source reliability snapshot from this run's accumulated DB state so
    # the next run's collect_and_verify_supply/review_opportunities judgment
    # items carry an up-to-date reference (see source_reliability.py).
    _run_or_raise(project_root, "calibrate_source_reliability.py")

    selected_count = conn.execute(
        "SELECT COUNT(*) c FROM titles WHERE run_id = ? AND status = 'selected'", (state.run_id,)
    ).fetchone()["c"]
    done = selected_count == options.target_count
    atomic_write_text(
        project_root / "memory" / "HANDOFF.md",
        "# HANDOFF\n\n"
        f"- 상태: `{'DONE' if done else state.status}`\n"
        f"- 현재 단계: update_memory_and_git_checkpoint\n"
        f"- 마지막 검증: run {state.run_id} produced {selected_count}/{options.target_count} titles\n"
        f"- 다음 원자 작업: "
        f"{'다음 실행 대기' if done else '추가 수집·군집화 반복 후 재개'}\n",
    )
    _run_or_raise(project_root, "git_checkpoint.py", "--message", f"chore: pipeline checkpoint for {state.run_id}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_STAGE_HANDLERS = {
    "load_state": _stage_load_state,
    "source_access_test": _stage_source_access_test,
    "collect_sources": _stage_collect_sources,
    "filter_pain_sentences": _stage_filter_pain_sentences,
    "extract_and_cluster_problems": _stage_extract_and_cluster_problems,
    "score_demand": _stage_score_demand,
    "collect_and_verify_supply": _stage_collect_and_verify_supply,
    "score_opportunities": _stage_score_opportunities,
    "review_opportunities": _stage_review_opportunities,
    "generate_and_review_titles": _stage_generate_and_review_titles,
    "validate_outputs": _stage_validate_outputs,
    "publish_mode_outputs": _stage_publish_mode_outputs,
    "build_google_validation_queue": _stage_build_google_validation_queue,
    "import_and_apply_human_feedback": _stage_import_and_apply_human_feedback,
    "update_memory_and_git_checkpoint": _stage_update_memory_and_git_checkpoint,
}


def _load_or_create_state(options: RunOptions) -> run_state.RunState:
    project_root = options.project_root
    now = ids.now_kst()

    if options.resume:
        run_id = options.run_id or run_state.latest_run_id(project_root, options.mode)
        if run_id is None:
            raise ValueError(f"--resume given but no existing {options.mode} run was found")
        state = run_state.load(project_root, run_id)
        if state.mode != options.mode or state.target_title_count != options.target_count:
            raise ValueError(
                f"run {run_id} was started as mode={state.mode} target={state.target_title_count}; "
                f"--mode {options.mode} --target-count {options.target_count} does not match"
            )
        return state

    run_id = options.run_id or ids.format_run_id(options.mode, now)
    if run_state.exists(project_root, run_id):
        raise ValueError(f"run {run_id} already exists; pass --resume to continue it")
    return run_state.RunState(
        run_id=run_id,
        mode=options.mode,
        target_title_count=options.target_count,
        status="RUNNING",
        stage=STAGES[0],
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        context={"generated_filename": ids.format_generated_filename(now)},
    )


def run_pipeline(options: RunOptions) -> int:
    options.validate()
    project_root = options.project_root
    state = _load_or_create_state(options)
    run_state.save(project_root, state)

    conn = db.connect(project_root)
    try:
        stage_index = STAGES.index(state.stage)
        for stage in STAGES[stage_index:]:
            state.stage = stage
            state.awaiting_judgment = None
            handler = _STAGE_HANDLERS.get(stage)
            if handler is None:
                raise ImplementationPendingError(f"no handler registered for stage: {stage}")
            try:
                handler(conn, project_root, options, state)
            except (JudgmentRequired, RetryRequired, RecoveryRequired):
                raise
            except Exception as exc:
                state.status = "FAILED"
                state.updated_at = ids.now_kst().isoformat()
                run_state.save(project_root, state)
                raise RuntimeError(f"stage '{stage}' failed: {exc}") from exc
            state.status = "RUNNING"
            state.updated_at = ids.now_kst().isoformat()
            run_state.save(project_root, state)
        state.status = "DONE"
        state.updated_at = ids.now_kst().isoformat()
        run_state.save(project_root, state)
    finally:
        conn.close()
    return 0
