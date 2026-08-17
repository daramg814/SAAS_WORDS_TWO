"""단어뱅크 기반 제목 생성 파이프라인 (2026-08-11 프로젝트 정의 전환, CLAUDE.md §1).

`pipeline.py`(수요/공급/기회 기반)는 보류 상태로 그대로 보존하고, 이 모듈이
`run.py`의 현재 진입점이 실제로 실행하는 경로다. RunOptions와 판정 예외
클래스는 `pipeline.py`에서 그대로 재사용한다(순수 값 객체/예외 타입이라
수요/공급에 종속되지 않음). `contracts.py`/`run_state.py`/`judgment.py`도
DB에 의존하지 않는 순수 파일 기반 모듈이라 그대로 재사용한다 - 이 모듈은
DB(`data/local.db`)를 전혀 쓰지 않는다(단어뱅크 조합은 결정론적 생성이라
문제/증거/기회 같은 관계형 스키마가 필요 없음).
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from pathlib import Path

from . import config, ids, judgment, run_state, title_generation, word_generation
from .contracts import (
    atomic_write_text,
    normalize_title,
    validate_title_set,
)
from .judgment import JudgmentRequired
from .keyword_metrics_client import (
    ApiRuntimeConfig,
    KeywordMetricsBudgetExceeded,
    KeywordMetricsClient,
    KeywordMetricsCredentialsError,
    credentials_from_env,
    load_env_file,
)
from .pipeline import ImplementationPendingError, RecoveryRequired, RetryRequired, RunOptions

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
    "validate_outputs",
    "publish_mode_outputs",
    "update_memory_and_git_checkpoint",
)


# ---------------------------------------------------------------------------
# Shared helpers (duplicated in miniature from pipeline.py rather than
# importing its private _-prefixed names across modules - each is a handful
# of lines with no demand/supply coupling)
# ---------------------------------------------------------------------------


def _run_dir(project_root: Path, state: run_state.RunState) -> Path:
    return run_state.run_dir(project_root, state.run_id)


def _history_path_for(project_root: Path, state: run_state.RunState) -> Path:
    if state.mode == "qa":
        return Path(state.context["qa_history_snapshot_path"])
    return project_root / "output" / "deliverables" / "history" / "words.txt"


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _write_shortfall_intermediate(project_root: Path, state: run_state.RunState, titles: list[str]) -> Path:
    path = project_root / "output" / "_pipeline" / "intermediate" / f"{state.run_id}_shortfall_titles.txt"
    atomic_write_text(path, "\n".join(titles) + "\n" if titles else "")
    return path


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
# Stage: load_state
# ---------------------------------------------------------------------------


def _stage_load_state(project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    if state.mode == "qa" and "qa_history_snapshot_path" not in state.context:
        history_path = project_root / "output" / "deliverables" / "history" / "words.txt"
        snapshot_path = project_root / "output" / "_pipeline" / "qa" / state.run_id / "qa_history_snapshot.txt"
        lines = _read_lines(history_path)
        atomic_write_text(snapshot_path, "\n".join(lines) + "\n" if lines else "")
        state.context["qa_history_snapshot_path"] = str(snapshot_path)


# ---------------------------------------------------------------------------
# Stage: generate_and_review_titles (judgment checkpoint: code generates
# word-bank combinations, the current session reviews clarity/semantic-
# duplication/well-known-trademark conflict - design 9.2's hard-reject list
# minus anything opportunity-specific)
# ---------------------------------------------------------------------------


def _excluded_normalized(project_root: Path, state: run_state.RunState) -> set[str]:
    history = _read_lines(_history_path_for(project_root, state))
    blocklist = _read_lines(project_root / "input" / "blocklist.txt")
    excluded = {normalize_title(t) for t in history if t.strip()}
    excluded |= {normalize_title(t) for t in blocklist if t.strip()}
    excluded |= set(state.context.get("excluded_normalized", []))
    # 2026-08-17 (GKP-001, user request): a combination already known to fail
    # the keyword-metrics gate (see _load_metrics_cache below) is excluded
    # from candidate generation itself - regenerating/re-judging/re-querying
    # a combo whose avg_monthly_searches/competition_index are already on
    # record as not meeting the bar wastes AI-judgment cycles and API budget
    # for an outcome we already know. Passing combos are deliberately NOT
    # excluded here - they remain eligible candidates until actually used.
    cache = _load_metrics_cache(project_root)
    excluded |= {norm for norm, row in cache.items() if row["gate_passed"] != "True"}
    return excluded


# ---------------------------------------------------------------------------
# Keyword Planner filter gate (2026-08-17, CLAUDE.md §4, memory/ACTIVE_ISSUES.md
# GKP-001) - applied to AI-judgment-approved candidates each round, before they
# count toward target_count. Pure numeric comparison, so this stays code-only
# per CLAUDE.md §2 role separation (no session judgment needed).
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
# Persistent, cumulative (cross-run) raw-data table (2026-08-17, user
# request): every word ever checked against the Keyword Planner API, pass or
# fail, survives here - not just in a single run's evidence log. Written
# incrementally per API batch (KeywordMetricsClient.on_batch_fn), not once at
# the end, so a mid-run crash never loses results already fetched (real
# incidents: GKP-001 runs died at 49% and 91% through a 9,645-word round with
# nothing persisted). _CACHE_COLUMNS order is the on-disk CSV column order -
# do not reorder without a migration, per CLAUDE.md 12 (don't silently change
# output contracts).
# ---------------------------------------------------------------------------

_CACHE_COLUMNS = ("title", "avg_monthly_searches", "competition_index", "api_status", "gate_passed", "checked_at")


def _metrics_cache_path(project_root: Path) -> Path:
    return project_root / "output" / "deliverables" / "history" / "keyword_metrics_cache.csv"


def _metrics_passed_path(project_root: Path) -> Path:
    return project_root / "output" / "deliverables" / "history" / "keyword_metrics_passed.csv"


def _load_metrics_cache(project_root: Path) -> dict[str, dict]:
    """Returns {normalized_title: row} for every word ever recorded, keyed so
    a later re-check of the same combo (if it ever happens) overwrites the
    earlier row rather than duplicating it."""
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
    """Merges new_rows into the cumulative cache (by normalized title) and
    atomically rewrites both the full table and the pass-only subset table
    (user request: passed combos collected separately for easy reuse)."""
    if not new_rows:
        return
    cache = _load_metrics_cache(project_root)
    for row in new_rows:
        cache[normalize_title(row["title"])] = row
    ordered = sorted(cache.values(), key=lambda r: r["title"])

    full_buffer = io.StringIO()
    writer = csv.DictWriter(full_buffer, fieldnames=_CACHE_COLUMNS)
    writer.writeheader()
    writer.writerows(ordered)
    atomic_write_text(_metrics_cache_path(project_root), full_buffer.getvalue())

    passed_buffer = io.StringIO()
    passed_writer = csv.DictWriter(passed_buffer, fieldnames=_CACHE_COLUMNS)
    passed_writer.writeheader()
    passed_writer.writerows([r for r in ordered if r["gate_passed"] == "True"])
    atomic_write_text(_metrics_passed_path(project_root), passed_buffer.getvalue())


def _final_words_dir(project_root: Path) -> Path:
    return project_root / "output" / "deliverables" / "final_words"


def _history_snapshots_dir(project_root: Path) -> Path:
    return project_root / "output" / "deliverables" / "history" / "snapshots"


def _export_final_words_and_history_snapshots(project_root: Path, when) -> None:
    """2026-08-17 user request, two parts:

    1. A plain word list (title only, one per line, no CSV columns) the user
       can take away as-is - exported from the cumulative pass-only table.
    2. Dated snapshots of the live history tables (words.txt,
       keyword_metrics_cache.csv, keyword_metrics_passed.csv) so point-in-time
       state is preserved even though those live files keep a fixed path
       (word_pipeline/run_state code depends on that path staying stable -
       CLAUDE.md 12 - so the live files themselves are never renamed).

    Called once per round that does keyword-metrics work (not once per API
    batch) - a 10,000-word round batches in chunks of 20, and snapshotting on
    every chunk would create hundreds of near-duplicate multi-MB files."""
    stamp = when.strftime("%Y%m%d_%H%M%S") + "_KST"

    passed_path = _metrics_passed_path(project_root)
    if passed_path.exists():
        with passed_path.open("r", encoding="utf-8", newline="") as f:
            titles = [row["title"] for row in csv.DictReader(f)]
        atomic_write_text(
            _final_words_dir(project_root) / f"passed_words_{stamp}.txt",
            "\n".join(titles) + "\n" if titles else "",
        )

    snapshot_sources = (
        (project_root / "output" / "deliverables" / "history" / "words.txt", "words", "txt"),
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
    """Keeps only candidates whose avg_monthly_searches >= threshold AND whose
    competition_index is exactly the configured value (default 0). A missing
    (NULL) competition_index means Keyword Planner has no data for that
    combination - "dead word" - and never passes, regardless of
    avg_monthly_searches. Every checked candidate (pass or fail) is logged to
    the run's keyword_metrics_evidence.jsonl for traceability (CLAUDE.md §3.1)
    and to the cumulative output/deliverables/history/keyword_metrics_cache.csv table.

    Candidates already present in the cache (previously checked, in this run
    or any earlier one) reuse that recorded result instead of re-querying the
    API - 2026-08-17 user request: never pay for the same lookup twice. Only
    genuinely new titles are sent to the API.
    """
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


def _stage_generate_and_review_titles(project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    run_dir = _run_dir(project_root, state)
    stage_name = "review_titles"
    target_count = options.target_count

    while True:
        approved = state.context.get("approved", [])
        if len(approved) >= target_count:
            return

        round_no = state.context.get("title_round", 1)
        if round_no > word_generation.MAX_ROUNDS:
            status = "CAPABILITY_STAGNATION" if not approved else "RETRYING"
            state.status = status
            run_state.save(project_root, state)
            _write_shortfall_intermediate(project_root, state, [item["title"] for item in approved])
            raise RetryRequired(
                f"reached max rounds ({word_generation.MAX_ROUNDS}) with only "
                f"{len(approved)}/{target_count} approved titles",
                status=status,
            )

        if judgment.has_response(run_dir, stage_name, round_no):
            response = judgment.read_response(run_dir, stage_name, round_no)
            newly_judged = _consume_review(state, response)
            try:
                newly_approved = _apply_keyword_metrics_filter(project_root, state, newly_judged)
            except (KeywordMetricsCredentialsError, KeywordMetricsBudgetExceeded) as exc:
                approved_so_far = state.context.get("approved", [])
                status = "CAPABILITY_STAGNATION" if not approved_so_far else "RETRYING"
                state.status = status
                run_state.save(project_root, state)
                _write_shortfall_intermediate(project_root, state, [item["title"] for item in approved_so_far])
                raise RetryRequired(f"keyword metrics filter unavailable: {exc}", status=status)
            approved = state.context.setdefault("approved", [])
            approved.extend(newly_approved)
            state.context["approved"] = approved
            state.context["title_round"] = round_no + 1
            run_state.save(project_root, state)
            continue

        shortfall = target_count - len(approved)
        if options.round_size:
            candidate_count = options.round_size
        elif round_no == 1:
            candidate_count = title_generation.first_round_size(target_count)
        else:
            candidate_count = title_generation.next_round_size(shortfall)
        excluded = _excluded_normalized(project_root, state)
        candidates = word_generation.generate_combinations(candidate_count, exclude=excluded)
        if not candidates:
            status = "CAPABILITY_STAGNATION" if not approved else "RETRYING"
            state.status = status
            run_state.save(project_root, state)
            _write_shortfall_intermediate(project_root, state, [item["title"] for item in approved])
            raise RetryRequired("word bank exhausted - no new combinations available", status=status)

        candidate_industry = state.context.setdefault("candidate_industry", {})
        for item in candidates:
            candidate_industry[item["title"]] = item["industry"]
        state.context["candidate_industry"] = candidate_industry
        state.context["excluded_normalized"] = sorted(excluded | {normalize_title(c["title"]) for c in candidates})

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
        state.context["title_round"] = round_no
        _pause_for_judgment(project_root, state, stage_name, request_path)


def _consume_review(state: run_state.RunState, response: dict) -> list[dict]:
    """Returns this round's AI-judgment-approved candidates. Callers must still
    run them through `_apply_keyword_metrics_filter` before counting them
    toward `state.context["approved"]` / target_count (CLAUDE.md §4 신규 게이트)."""
    candidate_industry = state.context.get("candidate_industry", {})
    newly_judged = []
    for decision in response["decisions"]:
        title = decision["title"]
        if decision.get("approve"):
            newly_judged.append({"title": title, "industry": candidate_industry.get(title, "")})
    return newly_judged


# ---------------------------------------------------------------------------
# Stage: validate_outputs
# ---------------------------------------------------------------------------


def _stage_validate_outputs(project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    approved = state.context.get("approved", [])
    scored = [
        {"title": item["title"], "problem_id": item["industry"], "priority_score": 0.0}
        for item in approved
    ]
    selected = title_generation.select_final_titles(scored, options.target_count)
    if len(selected) != options.target_count:
        state.status = "RETRYING"
        run_state.save(project_root, state)
        _write_shortfall_intermediate(project_root, state, [item["title"] for item in selected])
        raise RetryRequired(
            f"only {len(selected)}/{options.target_count} titles survive final selection "
            "under the 30%-per-industry cap"
        )

    selected_titles = [item["title"] for item in selected]
    history = _read_lines(_history_path_for(project_root, state))
    blocklist = _read_lines(project_root / "input" / "blocklist.txt")
    errors = validate_title_set(selected_titles, target_count=options.target_count, history=history, blocklist=blocklist)
    if errors:
        state.status = "FAILED"
        run_state.save(project_root, state)
        raise RuntimeError("final title set failed validate_title_set: " + "; ".join(errors))

    counts_by_industry: dict[str, int] = {}
    for item in selected:
        counts_by_industry[item["problem_id"]] = counts_by_industry.get(item["problem_id"], 0) + 1
    violations = title_generation.check_distribution(counts_by_industry, options.target_count)
    if violations:
        state.status = "FAILED"
        run_state.save(project_root, state)
        raise RuntimeError("distribution check failed: " + "; ".join(violations))

    state.context["final_titles"] = selected_titles


# ---------------------------------------------------------------------------
# Stage: publish_mode_outputs
# ---------------------------------------------------------------------------


def _stage_publish_mode_outputs(project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    final_titles = state.context["final_titles"]
    content = "\n".join(final_titles) + "\n"

    if state.mode == "production":
        final_path = project_root / "output" / "deliverables" / "generated" / state.context["generated_filename"]
        atomic_write_text(final_path, content)

        history_path = project_root / "output" / "deliverables" / "history" / "words.txt"
        history = _read_lines(history_path)
        history_norm = {normalize_title(t) for t in history}
        already_appended = bool(final_titles) and all(normalize_title(t) in history_norm for t in final_titles)
        if not already_appended:
            atomic_write_text(history_path, "\n".join(history + final_titles) + "\n")
            history_after = _read_lines(history_path)
            if history_after[len(history):] != final_titles:
                state.status = "RECOVERY_REQUIRED"
                run_state.save(project_root, state)
                raise RecoveryRequired(
                    f"output/deliverables/history/words.txt increment did not match this run's final_titles "
                    f"after atomic write (expected {len(final_titles)} new lines, "
                    f"found {len(history_after) - len(history)})"
                )
    else:
        qa_dir = project_root / "output" / "_pipeline" / "qa" / state.run_id
        atomic_write_text(qa_dir / "generated" / "saas_words_qa.txt", content)
        report = (
            "# QA Report\n\n"
            f"- run_id: {state.run_id}\n"
            f"- target_title_count: {state.target_title_count}\n"
            f"- approved_titles: {len(final_titles)}\n"
            f"- status: {state.status}\n"
        )
        atomic_write_text(qa_dir / "qa_report.md", report)


# ---------------------------------------------------------------------------
# Stage: update_memory_and_git_checkpoint
# ---------------------------------------------------------------------------


def _stage_update_memory_and_git_checkpoint(project_root: Path, options: RunOptions, state: run_state.RunState) -> None:
    final_titles = state.context.get("final_titles", [])
    done = len(final_titles) == options.target_count
    atomic_write_text(
        project_root / "memory" / "HANDOFF.md",
        "# HANDOFF\n\n"
        f"- 상태: `{'DONE' if done else state.status}`\n"
        f"- 현재 단계: update_memory_and_git_checkpoint (word_pipeline)\n"
        f"- 마지막 검증: run {state.run_id} produced {len(final_titles)}/{options.target_count} titles\n"
        f"- 다음 원자 작업: {'다음 실행 대기' if done else '추가 라운드 생성 후 재개'}\n",
    )
    _run_or_raise(project_root, "git_checkpoint.py", "--message", f"chore: word pipeline checkpoint for {state.run_id}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_STAGE_HANDLERS = {
    "load_state": _stage_load_state,
    "generate_and_review_titles": _stage_generate_and_review_titles,
    "validate_outputs": _stage_validate_outputs,
    "publish_mode_outputs": _stage_publish_mode_outputs,
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
