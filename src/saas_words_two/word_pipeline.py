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
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config, ids, judgment, run_state, word_bank, word_generation, word_performance
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
    # 스냅샷 생성은 호출자에게 위임(finally 블록에서 처리) - 예외 안전성 확보
    return passed


# ---------------------------------------------------------------------------
# 자가확장 단어뱅크 (2026-08-18, 사용자 지시): 조합공간이 완전히 소진되면(단어
# 자체가 없어진 게 아니라 손으로 고른 목록이 작았을 뿐 - 사용자 지적), 실행을
# CAPABILITY_STAGNATION으로 정직하게 끝내는 대신 현재 세션이 그 자리에서 직접
# 새 도메인어/기능어를 제안하는 별도 판정 라운드(`expand_word_bank`)를 한 번
# 연다. 제안은 word_bank.py 원본을 고치지 않고 `config/word_bank_expansions.csv`
# (누적, git 추적)에만 append되고, `_merged_word_bank`가 매 실행마다 원본과
# 병합해 후보 생성에 넘긴다 - word_bank.py 자체의 큐레이션 이력은 그대로 보존.
# ---------------------------------------------------------------------------

_EXPANSION_COLUMNS = ("type", "word", "industry", "added_at", "added_by_run_id")


def _word_bank_expansions_path(project_root: Path) -> Path:
    return project_root / "config" / "word_bank_expansions.csv"


def _load_dynamic_word_bank(project_root: Path) -> tuple[dict[str, list[str]], list[str]]:
    path = _word_bank_expansions_path(project_root)
    domain_words: dict[str, list[str]] = {}
    function_words: list[str] = []
    if not path.exists():
        return domain_words, function_words
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["type"] == "domain":
                domain_words.setdefault(row["industry"], []).append(row["word"])
            elif row["type"] == "function":
                function_words.append(row["word"])
    return domain_words, function_words


def _merged_word_bank(project_root: Path) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    """`word_bank.py`(정적 원본) + `config/word_bank_expansions.csv`(세션이
    누적 제안한 것) 병합, 중복 제거. 반환 형태는 `word_bank.DOMAIN_WORDS`/
    `FUNCTION_WORDS`와 동일해서 `word_generation.generate_combinations`에
    그대로 넘길 수 있다.

    2026-08-18 학습 루프: `config/retired_function_words.csv`(실측으로 통과
    0건이 확정된 기능어, word_performance 참고)에 오른 기능어는 병합 풀에서
    제외한다 - 이미 시도된 조합은 ledger가 재생성을 막지만, 이 필터가 없으면
    앞으로 추가될 새 도메인어가 죽은 기능어와 계속 짝지어져 API 예산을
    낭비한다(실측: 전체 조회의 32%가 통과 0건 기능어에 소모됨)."""
    dyn_domain, dyn_function = _load_dynamic_word_bank(project_root)
    merged_domain: dict[str, list[str]] = {
        industry: list(words) for industry, words in word_bank.DOMAIN_WORDS.items()
    }
    for industry, words in dyn_domain.items():
        existing = merged_domain.setdefault(industry, [])
        for w in words:
            if w not in existing:
                existing.append(w)
    merged_function = list(word_bank.FUNCTION_WORDS)
    for w in dyn_function:
        if w not in merged_function:
            merged_function.append(w)
    retired = word_performance.load_retired_function_words(project_root)
    if retired:
        merged_function = [w for w in merged_function if w not in retired]
    return {industry: tuple(words) for industry, words in merged_domain.items()}, tuple(merged_function)


def _append_word_bank_expansion_rows(project_root: Path, new_rows: list[dict]) -> None:
    if not new_rows:
        return
    path = _word_bank_expansions_path(project_root)
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def _key(row: dict) -> tuple[str, str, str]:
        return (row["type"], row["word"].strip().lower(), row.get("industry", "").strip().lower())

    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                key = _key(row)
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
    for row in new_rows:
        key = _key(row)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_EXPANSION_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(path, buffer.getvalue())


def _consume_word_bank_expansion(
    response: dict, run_id: str, when: str, *, retired: frozenset[str] | set[str] = frozenset()
) -> list[dict]:
    """판정 응답의 decisions(각 {type, word, industry?})를 검증해 유효한
    것만 반환한다 - 단일 Title Case 영단어, type은 domain/function, domain이면
    industry 필수. 형식이 안 맞는 제안은 조용히 버린다(예산 낭비 방지 목적의
    관대한 검증 - 나머지 review_titles 판정이 최종 필터 역할을 한다).

    2026-08-18 학습 루프: 은퇴 목록(`retired`)에 있는 기능어를 다시 제안하면
    버린다 - 실측 통과 0건이 확정된 단어의 재유입 방지."""
    rows = []
    for decision in response.get("decisions", []):
        word = str(decision.get("word", "")).strip()
        word_type = decision.get("type")
        industry = str(decision.get("industry", "")).strip()
        if word_type not in ("domain", "function"):
            continue
        if not word.isalpha() or word != word.capitalize():
            continue
        if word_type == "function" and word in retired:
            continue
        if word_type == "domain" and not industry:
            continue
        rows.append(
            {
                "type": word_type,
                "word": word,
                "industry": industry if word_type == "domain" else "",
                "added_at": when,
                "added_by_run_id": run_id,
            }
        )
    return rows


_EXPAND_WORD_BANK_INSTRUCTIONS = (
    "[누적 노하우 - 반드시 먼저 읽을 것] 입력에 포함된 accumulated_learnings는 "
    "과거 라운드들의 시행착오를 현재 세션(들)이 memory/WORD_GENERATION_LEARNINGS.md에 "
    "직접 기록해 쌓아온 핵심 원칙이다. 각 원칙에는 candidate 또는 validated 표시가 "
    "있다 - validated 원칙은 반드시 지켜라. candidate 원칙(관측 1건뿐이거나 여러 "
    "변수가 동시에 바뀐 라운드로만 뒷받침됨)은 참고하되 맹신하지 말고, 가능하면 "
    "이번 제안이 그 원칙 하나만(다른 변수는 그대로 두고) 독립적으로 테스트하는 "
    "기회가 되도록 설계해서 교란을 풀어라. 이 라운드의 제안은 validated 원칙과 "
    "모순되지 않아야 한다 - 특히 과거에 실패로 확인된 패턴(예: 특정 업종 전문용어, "
    "특정 발명 단어 유형)을 반복하지 마라. 이번 라운드 결과가 나온 뒤(같은 실행 "
    "종료 시점) 현재 세션은 이번에 제안한 단어들과 그 결과(통과율 변화, 새로 은퇴된 "
    "단어 유무)를 memory/WORD_GENERATION_LEARNINGS.md의 라운드별 로그에 append하고, "
    "일반화 가능한 교훈이면 '핵심 원칙' 절도 갱신해야 한다(승격 조건을 충족했으면 "
    "candidate를 validated로 승격) - 이 기록이 다음 expand_word_bank 라운드에 다시 "
    "자동으로 주입된다. "
    "현재 단어뱅크(word_bank.py + 이미 제안된 확장분) 조합공간이 완전히 소진됐다 - "
    "영어 단어 자체가 부족한 게 아니라 손으로 고른 목록이 작아서다. 새 도메인어(업무 "
    "대상·문서·프로세스를 연상시키는 명사, 특정 업계 최소 20개 이상)와 새 기능어(업계에 "
    "무관하게 '이 도구가 무엇을 하는지' 연상시키는 동작·역할 명사, 최소 10개 이상)를 "
    "제안하라. 완전히 새로운 업계를 제안해도 좋다. Terminal/Ring처럼 특정 업계에서만 "
    "말이 되는 단어는 기능어로 제안하지 말 것(과거 실측으로 문제였음). "
    "[학습 루프 - 반드시 준수] 입력에 포함된 function_word_performance(누적 Keyword "
    "Planner 실측)를 먼저 읽어라: 새 기능어는 top_function_words의 패턴(Portal/Map/Hub처럼 "
    "사람들이 실제로 검색하는 구체적 장소·사물 명사)을 닮게 제안하고, "
    "retired_function_words(각 300회 이상 시도에 통과 0건으로 확정된 죽은 단어)와 그 "
    "패턴(Suite/Sync/Dashboard류 SaaS 전문용어풍 합성어)은 절대 제안하지 마라. "
    "[동의어 다양성 - 반드시 준수] 이번에 제안하는 기능어 목록 안에서 서로 뜻이 겹치는 "
    "동의어를 피하라(2026-08-19 실측 문제: Yard/Bay/Post/Outpost/Plaza/Harbor/Tower/"
    "Shelf/Locker/Booth/Kiosk를 한 번에 제안했더니 전부 '보관 장소'라는 같은 뜻이라 "
    "도메인어와 조합할 때마다 사실상 같은 문구가 11번 반복돼 AI 승인률이 21%로 급락함). "
    "제안하는 기능어들은 서로 다른 기능(추적/일정관리/문서보관/소통/분석 등)을 각각 "
    "대표해야 한다 - 한 기능당 비슷한 단어를 여러 개 넣지 말 것. "
    "[범용 결합력 - 반드시 준수, 동의어 다양성과는 별개 조건] 동의어가 아니어도 특정 "
    "의미 카테고리의 도메인어와만 자연스러운 기능어는 피하라(2026-08-19 실측: Inbox/"
    "Passport/Lobby/Bin/Line/Window/Ticker/Roll 10개를 서로 겹치지 않게 제안했지만 "
    "그 서브셋만의 승인률이 2.7%(112/4152)에 그침 - Inbox는 메시지·요청성 도메인어와만, "
    "Passport는 신원·자격증성 도메인어와만 자연스러워 나머지 도메인어 대다수와는 "
    "어색했음). Portal/Map/Hub/Tracker/Point/Station/Center/Register/Panel/Counter가 "
    "성공한 이유는 단어가 독특해서가 아니라 도메인어의 의미 카테고리에 관계없이 거의 "
    "모든 명사 뒤에 자연스럽게 붙는 범용 메타포이기 때문이다 - 새 기능어도 이 성질(특정 "
    "업계·특정 의미군에 국한되지 않고 폭넓게 결합됨)을 우선 고려해 제안하라. "
    "기존 word_bank.py와 이미 제안된 확장분(입력으로 함께 제공됨)과 겹치지 않게. 각 항목을 "
    '{"type": "domain"|"function", "word": "Title Case 단일 영단어", "industry": '
    '"domain일 때만 필수, function이면 생략"} 형태로 응답하라.'
)


def _word_generation_learnings_path(project_root: Path) -> Path:
    return project_root / "memory" / "WORD_GENERATION_LEARNINGS.md"


def _load_word_generation_learnings_principles(project_root: Path) -> str:
    """`memory/WORD_GENERATION_LEARNINGS.md`의 "## 핵심 원칙" 섹션만 추출해 반환한다.

    2026-08-19 사용자 지시: 세션이 매번 이 문서를 "읽으려는 의지"에 기대지 않고,
    `expand_word_bank` 판정 요청을 만드는 이 코드가 매번 강제로 끼워 넣는다 -
    `function_word_performance`와 동일한 패턴(구조적 전달, 세션의 선택 사항이 아님).
    전체 문서(라운드별 로그 포함)를 매번 넣으면 로그가 쌓일수록 요청이 무한정
    커지므로, "지금 유효한 원칙" 요약만 담는 이 섹션만 추출한다. 파일이 없거나
    섹션이 없으면(아직 아무것도 기록되지 않았으면) 빈 문자열."""
    path = _word_generation_learnings_path(project_root)
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    # 줄 시작(^)에 오는 실제 헤딩만 매칭 - 본문 설명 중 백틱 안에 같은 문자열이
    # 그대로 등장해도(예: "`## 핵심 원칙` 섹션은...") 오매칭되지 않도록 함
    # (2026-08-19 실측으로 발견된 버그: 단순 문자열 탐색은 첫 등장 위치인 설명
    # 문단을 헤딩으로 착각했다).
    match = re.search(r"^## 핵심 원칙\s*\n", text, flags=re.MULTILINE)
    if match is None:
        return ""
    start = match.end()
    next_match = re.search(r"^## ", text[start:], flags=re.MULTILINE)
    section = text[start : start + next_match.start()] if next_match else text[start:]
    return section.strip()


def _write_expand_word_bank_request(project_root: Path, run_dir: Path, state: run_state.RunState) -> Path:
    existing_domain, existing_function = _merged_word_bank(project_root)
    items = [
        {"industry": industry, "existing_domain_words": list(words)}
        for industry, words in existing_domain.items()
    ] + [
        {"existing_function_words": list(existing_function)},
        {"function_word_performance": word_performance.performance_summary_for_expansion(project_root)},
        {"accumulated_learnings": _load_word_generation_learnings_principles(project_root)},
    ]
    return judgment.write_request(
        run_dir,
        "expand_word_bank",
        state.run_id,
        _EXPAND_WORD_BANK_INSTRUCTIONS,
        items,
        round_no=1,
        generated_at=ids.now_kst().isoformat(),
    )


# ---------------------------------------------------------------------------
# Stage: generate_and_review_titles - "한 번의 CLI 실행 = 한 라운드"(2026-08-18
# 전환). backlog(load_state에서 적재) + 이번에 새로 생성/판정한 승인분을 합쳐
# Keyword Planner 게이트에 태우고 끝난다. 더 이상 target_count를 추격하는
# 다중 라운드 루프가 없다 - 더 하고 싶으면 다시 실행(새 run 또는 --resume).
# 조합공간이 소진되면 즉시 포기하지 않고, 자가확장(위 섹션) 판정을 한 번 거친
# 뒤에도 여전히 신규 후보가 없을 때만 진짜 CAPABILITY_STAGNATION으로 처리한다.
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
        finally:
            # 판정/API 조회 후 모든 스냅샷 생성 - 명시적 호출로 누락 방지
            _export_final_words_and_history_snapshots(project_root, ids.now_kst())
            # 학습 루프: 매 라운드 성과 리포트 자동 갱신(캐시 없으면 no-op)
            word_performance.write_report(project_root, ids.now_kst())
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
    domain_words, function_words = _merged_word_bank(project_root)
    candidates = word_generation.generate_combinations(
        round_size, exclude=excluded, domain_words=domain_words, function_words=function_words
    )

    if not candidates:
        expand_stage = "expand_word_bank"
        if judgment.has_response(run_dir, expand_stage, round_no):
            expand_response = judgment.read_response(run_dir, expand_stage, round_no)
            new_rows = _consume_word_bank_expansion(
                expand_response,
                state.run_id,
                ids.now_kst().isoformat(),
                retired=word_performance.load_retired_function_words(project_root),
            )
            _append_word_bank_expansion_rows(project_root, new_rows)
            domain_words, function_words = _merged_word_bank(project_root)
            candidates = word_generation.generate_combinations(
                round_size, exclude=excluded, domain_words=domain_words, function_words=function_words
            )
        elif not state.context.get("word_bank_expansion_attempted"):
            state.context["word_bank_expansion_attempted"] = True
            expand_request_path = _write_expand_word_bank_request(project_root, run_dir, state)
            _pause_for_judgment(project_root, state, expand_stage, expand_request_path)

    if not candidates:
        if not backlog:
            state.status = "CAPABILITY_STAGNATION"
            run_state.save(project_root, state)
            raise RetryRequired(
                "word bank exhausted even after a self-expansion attempt - "
                "no new combinations and no pending backlog",
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

    # 학습 정체 점검(2026-08-19, 사용자 지시): 이 스테이지가 라운드 완료를
    # 확정하는 유일한 지점이므로 여기서 정확히 한 번 이력에 기록한다.
    word_performance.append_round_history(
        project_root, state.run_id, state.mode, ids.now_kst().isoformat(), stats
    )
    stagnation = word_performance.detect_stagnation(word_performance.load_round_history(project_root))
    stagnation_line = word_performance.format_stagnation_message(stagnation)
    print(stagnation_line)

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
        f"- {stagnation_line}\n"
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
