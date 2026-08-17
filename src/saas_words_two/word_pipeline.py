"""단어뱅크 기반 제목 생성 파이프라인 (2026-08-18 두 번째 프로젝트 정의 전환).

`run.py`의 유일한 진입점. "정확히 500개 선정·발행" 계약과 업계 30% 분산 상한은
폐기됐다 - 산출물은 목표 개수 없이 계속 누적되는 4개 문서(원시 생성 전체 /
Keyword Planner OK+NG 전체 / OK만 정리된 표 / OK 단어 리스트) 모델이다. 실행
모델도 "한 번의 CLI 실행 = 한 라운드"로 단순화됐다(더 이상 MAX_ROUNDS/
shortfall*2 재생성 루프가 없다). 수요/공급(demand/supply) 파이프라인은 이
전환으로 완전히 삭제됐으므로, `RunOptions`/판정 예외 클래스는 더 이상 다른
모듈과 공유하지 않고 이 파일이 직접 소유한다.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config, ids, judgment, run_state, word_generation
from .contracts import atomic_write_text, normalize_title
from .judgment import JudgmentRequired
from .keyword_metrics_client import (
    ApiRuntimeConfig,
    KeywordMetricsBudgetExceeded,
    KeywordMetricsClient,
    KeywordMetricsCredentialsError,
    credentials_from_env,
    load_env_file,
)

__all__ = [
    "ImplementationPendingError",
    "JudgmentRequired",
    "RecoveryRequired",
    "RetryRequired",
    "RunOptions",
    "run_pipeline",
]

STAGES = (
    "load_state",
    "generate_and_review_titles",
    "update_memory_and_git_checkpoint",
)

# 모드별 round-size 기본값(명시적으로 --round-size를 안 주면 이 값 사용).
# QA=소규모 스모크 테스트, production=실제 대량 배치 - 두 모드의 유일한 차이.
DEFAULT_ROUND_SIZE = {"qa": 50, "production": 10000}


# ---------------------------------------------------------------------------
# 판정 예외 클래스 (2026-08-18 이전엔 pipeline.py에서 재사용했으나, 그 모듈이
# 수요/공급 삭제로 없어져서 이 파일이 직접 소유한다)
# ---------------------------------------------------------------------------


class ImplementationPendingError(RuntimeError):
    pass


class RetryRequired(RuntimeError):
    """판정 대기가 아닌, 제어된 중단. 예: 이번 라운드에 신규 후보가 전혀 없거나
    Keyword Planner API 예산이 소진된 경우. 최종 산출물은 갱신되지 않는다.

    status는 기본 RETRYING이지만 CAPABILITY_STAGNATION(단어뱅크 조합공간이
    진짜로 소진되어 이 실행/설정으로는 더 진행 불가)일 수도 있다 - 둘 다 이
    예외 타입으로 발생하며, HANDOFF/ACTIVE_ISSUES 기록 목적으로만 구분된다.
    """

    def __init__(self, reason: str, *, status: str = "RETRYING"):
        self.reason = reason
        self.status = status
        super().__init__(f"{status}: {reason}")


class RecoveryRequired(RuntimeError):
    """원자적 쓰기 자체의 사후 검증이 실패한 경우(예: 캐시 파일의 병합 결과가
    방금 쓴 내용과 다름) - 자동 재시도가 안전하지 않아 수동 점검을 위해 멈춘다."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"RECOVERY_REQUIRED: {reason}")


@dataclass(frozen=True)
class RunOptions:
    mode: str
    project_root: Path
    resume: bool = False
    run_id: str | None = None
    round_size: int | None = None

    def validate(self) -> None:
        if self.mode not in {"production", "qa"}:
            raise ValueError("mode must be production or qa")
        if self.round_size is not None and self.round_size <= 0:
            raise ValueError("round_size, if given, must be positive")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _run_dir(project_root: Path, state: run_state.RunState) -> Path:
    return run_state.run_dir(project_root, state.run_id)


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _pause_for_judgment(project_root: Path, state: run_state.RunState, stage_name: str, request_path: Path) -> None:
    state.status = "RUNNING"
    state.awaiting_judgment = stage_name
    state.updated_at = ids.now_kst().isoformat()
    run_state.save(project_root, state)
    raise JudgmentRequired(stage_name, request_path)


def _run_or_raise(project_root: Path, script_name: str, *extra_args: str) -> subprocess.CompletedProcess:
    script_path = project_root / "scripts" / script_name
    result = subprocess.run(
        [sys.executable, str(script_path), "--project-root", str(project_root), *extra_args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{script_name} exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result


# ---------------------------------------------------------------------------
# 문서 ① 원시 생성 전체 ledger (2026-08-18 신규): 생성+판정된 모든 후보를
# verdict(승인/거절)와 무관하게 기록한다. 이게 있어야 (a) 같은 조합이 다시
# 생성/판정되는 낭비를 막고, (b) AI 승인은 됐지만 아직 Keyword Planner로 확인
# 안 된 후보("backlog")가 다음 실행에서 유실되지 않고 자동으로 이어진다.
# keyword_metrics_cache.csv와 동일한 "정규화 키로 병합 후 전체 재기록" 패턴.
# ---------------------------------------------------------------------------

_LEDGER_COLUMNS = ("title", "industry", "ai_approved", "ai_reason", "judged_at")


def _generated_ledger_path(project_root: Path) -> Path:
    return project_root / "output" / "deliverables" / "history" / "generated_candidates.csv"


def _load_generated_ledger(project_root: Path) -> dict[str, dict]:
    path = _generated_ledger_path(project_root)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as f:
        return {normalize_title(row["title"]): row for row in csv.DictReader(f)}


def _append_generated_ledger_rows(project_root: Path, new_rows: list[dict]) -> None:
    if not new_rows:
        return
    ledger = _load_generated_ledger(project_root)
    for row in new_rows:
        ledger[normalize_title(row["title"])] = row
    ordered = sorted(ledger.values(), key=lambda r: r["title"])

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_LEDGER_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(ordered)
    atomic_write_text(_generated_ledger_path(project_root), buffer.getvalue())


def _export_generated_ledger_snapshot(project_root: Path, when) -> None:
    src_path = _generated_ledger_path(project_root)
    if not src_path.exists():
        return
    stamp = when.strftime("%Y%m%d_%H%M%S") + "_KST"
    atomic_write_text(
        _history_snapshots_dir(project_root) / f"generated_candidates_{stamp}.csv",
        src_path.read_text(encoding="utf-8"),
    )


def _excluded_normalized(project_root: Path, state: run_state.RunState) -> set[str]:
    blocklist = _read_lines(project_root / "input" / "blocklist.txt")
    excluded = {normalize_title(t) for t in blocklist if t.strip()}
    # 한 번 생성+판정된 조합은 승인/거절과 무관하게 다시 생성하지 않는다 -
    # 승인분 중 아직 Keyword Planner 미확인인 것은 backlog로 별도 처리된다
    # (_stage_load_state 참고), 재생성 대상에서는 제외되지만 유실되지 않는다.
    excluded |= set(_load_generated_ledger(project_root).keys())
    return excluded


# ---------------------------------------------------------------------------
# Stage: load_state - backlog 스윕(AI 승인은 됐지만 Keyword Planner 미확인인
# 후보를 다음 게이트 실행에 먼저 태운다)
# ---------------------------------------------------------------------------


def _stage_load_state(project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    ledger = _load_generated_ledger(project_root)
    cache = _load_metrics_cache(project_root)
    backlog = [
        {"title": row["title"], "industry": row["industry"]}
        for norm, row in ledger.items()
        if row["ai_approved"] == "True" and norm not in cache
    ]
    state.context["backlog"] = backlog


# ---------------------------------------------------------------------------
# Keyword Planner filter gate (변경 없음 - CLAUDE.md §4, memory/ACTIVE_ISSUES.md
# GKP-001) - 순수 수치 비교라 코드 전담, 판정은 이 함수 호출 전에 이미 끝나 있다.
# ---------------------------------------------------------------------------


def _keyword_metrics_settings(project_root: Path) -> tuple[float, float, ApiRuntimeConfig, Path]:
    cfg = config.load_keyword_metrics_config(project_root)
    api_cfg = cfg.get("api", {})
    runtime = ApiRuntimeConfig(
        batch_size=api_cfg.get("batch_size", 20),
        free_tier_budget=api_cfg.get("free_tier_budget", 1000),
        min_request_interval_ms=api_cfg.get("min_request_interval_ms", 500),
        geo_target_constants=api_cfg.get("geo_target_constants", ""),
        language=api_cfg.get("language", "languageConstants/1000"),
        keyword_plan_network=api_cfg.get("keyword_plan_network", "GOOGLE_SEARCH"),
    )
    credentials_path = Path(api_cfg.get("credentials_env_path", ".env.local"))
    if not credentials_path.is_absolute():
        credentials_path = project_root / credentials_path
    return cfg["avg_monthly_searches_min"], cfg["competition_index_exact"], runtime, credentials_path


# ---------------------------------------------------------------------------
# 문서 ②③ Keyword Planner 조회 결과(전체/OK만) - 기존 로직 그대로 유지.
# ---------------------------------------------------------------------------

_CACHE_COLUMNS = ("title", "avg_monthly_searches", "competition_index", "api_status", "gate_passed", "checked_at")


def _metrics_cache_path(project_root: Path) -> Path:
    return project_root / "output" / "deliverables" / "history" / "keyword_metrics_cache.csv"


def _metrics_passed_path(project_root: Path) -> Path:
    return project_root / "output" / "deliverables" / "history" / "keyword_metrics_passed.csv"


def _load_metrics_cache(project_root: Path) -> dict[str, dict]:
    path = _metrics_cache_path(project_root)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as f:
        return {normalize_title(row["title"]): row for row in csv.DictReader(f)}


def _record_to_cache_row(title: str, record, gate_passed: bool, checked_at: str) -> dict:
    return {
        "title": title,
        "avg_monthly_searches": "" if record.avg_monthly_searches is None else record.avg_monthly_searches,
        "competition_index": "" if record.competition_index is None else record.competition_index,
        "api_status": record.api_status,
        "gate_passed": str(gate_passed),
        "checked_at": checked_at,
    }


def _append_metrics_cache_rows(project_root: Path, new_rows: list[dict]) -> None:
    if not new_rows:
        return
    cache = _load_metrics_cache(project_root)
    for row in new_rows:
        cache[normalize_title(row["title"])] = row
    ordered = sorted(cache.values(), key=lambda r: r["title"])

    full_buffer = io.StringIO()
    writer = csv.DictWriter(full_buffer, fieldnames=_CACHE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(ordered)
    atomic_write_text(_metrics_cache_path(project_root), full_buffer.getvalue())

    passed_buffer = io.StringIO()
    passed_writer = csv.DictWriter(passed_buffer, fieldnames=_CACHE_COLUMNS, lineterminator="\n")
    passed_writer.writeheader()
    passed_writer.writerows([r for r in ordered if r["gate_passed"] == "True"])
    atomic_write_text(_metrics_passed_path(project_root), passed_buffer.getvalue())


def _final_words_dir(project_root: Path) -> Path:
    return project_root / "output" / "deliverables" / "final_words"


def _history_snapshots_dir(project_root: Path) -> Path:
    return project_root / "output" / "deliverables" / "history" / "snapshots"


def _export_final_words_and_history_snapshots(project_root: Path, when) -> None:
    """문서 ④(OK 단어 리스트)의 마스터(`passed_words_latest.txt`, 항상 최신
    전체 누적)와 날짜시간 스냅샷을 쓰고, 문서 ②③의 날짜시간 스냅샷도 함께
    쓴다. `words.txt`는 더 이상 존재하지 않으므로 스냅샷 소스에서 제외됐다
    (2026-08-18 전환). 라운드당 1회 호출(_apply_keyword_metrics_filter 종료 시)."""
    stamp = when.strftime("%Y%m%d_%H%M%S") + "_KST"

    passed_path = _metrics_passed_path(project_root)
    if passed_path.exists():
        with passed_path.open("r", encoding="utf-8", newline="") as f:
            titles = [row["title"] for row in csv.DictReader(f)]
        content = "\n".join(titles) + "\n" if titles else ""
        atomic_write_text(_final_words_dir(project_root) / f"passed_words_{stamp}.txt", content)
        atomic_write_text(_final_words_dir(project_root) / "passed_words_latest.txt", content)

    snapshot_sources = (
        (_metrics_cache_path(project_root), "keyword_metrics_cache", "csv"),
        (_metrics_passed_path(project_root), "keyword_metrics_passed", "csv"),
    )
    for src_path, prefix, ext in snapshot_sources:
        if not src_path.exists():
            continue
        atomic_write_text(
            _history_snapshots_dir(project_root) / f"{prefix}_{stamp}.{ext}",
            src_path.read_text(encoding="utf-8"),
        )


def _build_keyword_metrics_client(project_root: Path) -> KeywordMetricsClient:
    searches_min, competition_exact, runtime, credentials_path = _keyword_metrics_settings(project_root)
    env = load_env_file(credentials_path)
    creds = credentials_from_env(env)

    def _persist_batch(records: list) -> None:
        checked_at = ids.now_kst().isoformat()
        rows = []
        for record in records:
            gate_passed = (
                record.avg_monthly_searches is not None
                and record.competition_index is not None
                and record.avg_monthly_searches >= searches_min
                and record.competition_index == competition_exact
            )
            rows.append(_record_to_cache_row(record.word, record, gate_passed, checked_at))
        _append_metrics_cache_rows(project_root, rows)

    return KeywordMetricsClient(creds, runtime, on_batch_fn=_persist_batch)


def _write_metrics_evidence(project_root: Path, state: run_state.RunState, evidence: list[dict]) -> None:
    path = project_root / "output" / "_pipeline" / "intermediate" / f"{state.run_id}_keyword_metrics_evidence.jsonl"
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = existing + [json.dumps(entry, ensure_ascii=False, sort_keys=True) for entry in evidence]
    atomic_write_text(path, "\n".join(lines) + "\n" if lines else "")


def _apply_keyword_metrics_filter(
    project_root: Path, state: run_state.RunState, candidates: list[dict]
) -> list[dict]:
    """avg_monthly_searches>=임계값 AND competition_index==임계값(기본 0)인
    후보만 통과시킨다. NULL competition_index는 항상 탈락(메트릭 자체가 없는
    "죽은 단어"). pass/fail 전부 run별 evidence(jsonl)와 누적 캐시(문서②③)에
    기록된다. 캐시에 이미 있는 후보는 API 재조회 없이 재사용."""
    if not candidates:
        return []

    searches_min, competition_exact, _, _ = _keyword_metrics_settings(project_root)
    cache = _load_metrics_cache(project_root)

    cached_hits: dict[str, dict] = {}
    uncached_titles: list[str] = []
    for candidate in candidates:
        row = cache.get(normalize_title(candidate["title"]))
        if row is not None:
            cached_hits[candidate["title"]] = row
        else:
            uncached_titles.append(candidate["title"])

    fresh_records_by_title = {}
    if uncached_titles:
        client = _build_keyword_metrics_client(project_root)
        fresh_records_by_title = {record.word: record for record in client.fetch_metrics(uncached_titles)}
        # already persisted incrementally per-batch via on_batch_fn above

    checked_at = ids.now_kst().isoformat()
    passed: list[dict] = []
    evidence: list[dict] = []
    for candidate in candidates:
        title = candidate["title"]
        if title in cached_hits:
            row = cached_hits[title]
            avg = None if row["avg_monthly_searches"] == "" else float(row["avg_monthly_searches"])
            competition_index = None if row["competition_index"] == "" else float(row["competition_index"])
            api_status = row["api_status"]
            gate_passed = row["gate_passed"] == "True"
            source = "cache"
        else:
            record = fresh_records_by_title.get(title)
            avg = record.avg_monthly_searches if record else None
            competition_index = record.competition_index if record else None
            api_status = record.api_status if record else "failed"
            gate_passed = (
                avg is not None
                and competition_index is not None
                and avg >= searches_min
                and competition_index == competition_exact
            )
            source = "api"
        evidence.append(
            {
                "title": title,
                "avg_monthly_searches": avg,
                "competition_index": competition_index,
                "api_status": api_status,
                "passed": gate_passed,
                "source": source,
                "checked_at": checked_at,
            }
        )
        if gate_passed:
            passed.append(candidate)

    _write_metrics_evidence(project_root, state, evidence)
    _export_final_words_and_history_snapshots(project_root, ids.now_kst())
    return passed


# ---------------------------------------------------------------------------
# Stage: generate_and_review_titles - "한 번의 CLI 실행 = 한 라운드"(2026-08-18
# 전환). backlog(load_state에서 적재) + 이번에 새로 생성/판정한 승인분을 합쳐
# Keyword Planner 게이트에 태우고 끝난다. 더 이상 target_count를 추격하는
# 다중 라운드 루프가 없다 - 더 하고 싶으면 다시 실행(새 run 또는 --resume).
# ---------------------------------------------------------------------------


def _stage_generate_and_review_titles(project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    run_dir = _run_dir(project_root, state)
    stage_name = "review_titles"
    round_no = 1
    backlog = state.context.get("backlog", [])

    if judgment.has_response(run_dir, stage_name, round_no):
        response = judgment.read_response(run_dir, stage_name, round_no)
        candidate_industry = state.context.get("candidate_industry", {})
        judged_at = ids.now_kst().isoformat()
        ledger_rows = []
        fresh_approved = []
        for decision in response["decisions"]:
            title = decision["title"]
            approve = bool(decision.get("approve"))
            ledger_rows.append(
                {
                    "title": title,
                    "industry": candidate_industry.get(title, ""),
                    "ai_approved": str(approve),
                    "ai_reason": "" if approve else decision.get("reason", ""),
                    "judged_at": judged_at,
                }
            )
            if approve:
                fresh_approved.append({"title": title, "industry": candidate_industry.get(title, "")})
        _append_generated_ledger_rows(project_root, ledger_rows)
        _export_generated_ledger_snapshot(project_root, ids.now_kst())

        combined = backlog + fresh_approved
        try:
            approved = _apply_keyword_metrics_filter(project_root, state, combined)
        except (KeywordMetricsCredentialsError, KeywordMetricsBudgetExceeded) as exc:
            state.status = "RETRYING"
            run_state.save(project_root, state)
            raise RetryRequired(f"keyword metrics filter unavailable: {exc}", status="RETRYING")
        state.context["approved"] = approved
        state.context["round_stats"] = {
            "generated": len(ledger_rows),
            "ai_approved": len(fresh_approved),
            "backlog_carried": len(backlog),
            "kp_passed": len(approved),
        }
        state.status = "DONE"
        run_state.save(project_root, state)
        return

    excluded = _excluded_normalized(project_root, state)
    round_size = options.round_size or DEFAULT_ROUND_SIZE[options.mode]
    candidates = word_generation.generate_combinations(round_size, exclude=excluded)

    if not candidates:
        if not backlog:
            state.status = "CAPABILITY_STAGNATION"
            run_state.save(project_root, state)
            raise RetryRequired(
                "word bank exhausted - no new combinations and no pending backlog",
                status="CAPABILITY_STAGNATION",
            )
        try:
            approved = _apply_keyword_metrics_filter(project_root, state, backlog)
        except (KeywordMetricsCredentialsError, KeywordMetricsBudgetExceeded) as exc:
            state.status = "RETRYING"
            run_state.save(project_root, state)
            raise RetryRequired(f"keyword metrics filter unavailable: {exc}", status="RETRYING")
        state.context["approved"] = approved
        state.context["round_stats"] = {
            "generated": 0,
            "ai_approved": 0,
            "backlog_carried": len(backlog),
            "kp_passed": len(approved),
        }
        state.status = "DONE"
        run_state.save(project_root, state)
        return

    candidate_industry = state.context.setdefault("candidate_industry", {})
    for item in candidates:
        candidate_industry[item["title"]] = item["industry"]
    state.context["candidate_industry"] = candidate_industry

    instructions = (
        "각 제목의 의미 중복과 명확성을 검토하라. 다른 후보와 의미가 겹치거나, "
        "어떤 SaaS인지 추측할 수 없을 만큼 추상적이거나, 유명 서비스·브랜드와 "
        "명백히 동일/유사하면 approve=false로 판정하고 reason을 남겨라. "
        "그렇지 않으면 approve=true. industry 필드는 참고용 맥락이다."
    )
    items = [{"title": c["title"], "industry": c["industry"]} for c in candidates]
    request_path = judgment.write_request(
        run_dir, stage_name, state.run_id, instructions, items,
        round_no=round_no, generated_at=ids.now_kst().isoformat(),
    )
    _pause_for_judgment(project_root, state, stage_name, request_path)


# ---------------------------------------------------------------------------
# Stage: update_memory_and_git_checkpoint
# ---------------------------------------------------------------------------


def _stage_update_memory_and_git_checkpoint(project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    # 이 스테이지에 도달했다는 것 자체가 generate_and_review_titles가 예외
    # 없이 끝났다는 뜻이다(RetryRequired/CAPABILITY_STAGNATION은 그 안에서
    # 즉시 예외로 전파되어 여기까지 오지 않는다) - 그래서 state.status를
    # 다시 읽지 않고(run_pipeline의 스테이지 루프가 각 스테이지 성공 후
    # "RUNNING"으로 되돌려놓으므로 신뢰할 수 없다) 항상 DONE으로 기록한다.
    stats = state.context.get("round_stats", {})
    approved = state.context.get("approved", [])
    atomic_write_text(
        project_root / "memory" / "HANDOFF.md",
        "# HANDOFF\n\n"
        f"- 상태: `DONE`\n"
        f"- 현재 단계: update_memory_and_git_checkpoint (word_pipeline)\n"
        f"- 마지막 실행: run {state.run_id} (mode={state.mode})\n"
        f"- 이번 라운드: 신규생성 {stats.get('generated', 0)}개, "
        f"AI승인 {stats.get('ai_approved', 0)}개, "
        f"backlog반영 {stats.get('backlog_carried', 0)}개, "
        f"Keyword Planner통과 {stats.get('kp_passed', len(approved))}개\n"
        f"- 다음 원자 작업: 필요하면 다시 실행(같은 run_id --resume 또는 새 run)\n",
    )
    _run_or_raise(project_root, "git_checkpoint.py", "--message", f"chore: word pipeline checkpoint for {state.run_id}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_STAGE_HANDLERS = {
    "load_state": _stage_load_state,
    "generate_and_review_titles": _stage_generate_and_review_titles,
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
        if state.mode != options.mode:
            raise ValueError(f"run {run_id} was started as mode={state.mode}; --mode {options.mode} does not match")
        return state

    run_id = options.run_id or ids.format_run_id(options.mode, now)
    if run_state.exists(project_root, run_id):
        raise ValueError(f"run {run_id} already exists; pass --resume to continue it")
    return run_state.RunState(
        run_id=run_id,
        mode=options.mode,
        status="RUNNING",
        stage=STAGES[0],
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        context={},
    )


def run_pipeline(options: RunOptions) -> int:
    options.validate()
    project_root = options.project_root
    state = _load_or_create_state(options)
    run_state.save(project_root, state)

    stage_index = STAGES.index(state.stage)
    for stage in STAGES[stage_index:]:
        state.stage = stage
        state.awaiting_judgment = None
        handler = _STAGE_HANDLERS.get(stage)
        if handler is None:
            raise ImplementationPendingError(f"no handler registered for stage: {stage}")
        try:
            handler(project_root, options, state)
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
    return 0
