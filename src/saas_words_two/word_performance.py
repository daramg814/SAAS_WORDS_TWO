"""단어 성과 분석·학습 루프 (2026-08-18, 사용자 지시).

10,000개 라운드에서 Keyword Planner 통과가 12개(0.12%)에 그친 것을 계기로,
누적 캐시(문서②)의 실측 통과/탈락 데이터를 매 라운드 분석해 다음 생성에
반영하는 구조를 도입했다. 실측 분석(2026-08-18, 30,263건 기준) 요지:

- 기능어가 승부를 결정한다: Portal 5.85%/Map 5.68% vs. Suite/Sync/Dashboard/
  Toolkit/Workbench 등 28개 기능어는 각 300회+ 시도에 통과 0건.
- 그 28개 죽은 기능어에 전체 API 조회의 32%(9,797회)가 낭비됐다.
- 패턴: 사람들이 실제로 검색하는 구체적 명사(portal, map, hub)는 통과하고,
  SaaS 업계 전문용어풍 합성어(suite, sync, dashboard)는 전멸한다.

이 모듈이 제공하는 세 가지:
1. 통계 계산(순수 함수) - 기능어/도메인어별 통과율.
2. 은퇴 목록(`config/retired_function_words.csv`) - 충분히 시도됐는데 통과
   0건인 기능어를 조합 생성에서 제외(`word_pipeline._merged_word_bank`가
   로드). 은퇴된 단어는 더 시도되지 않으므로 통계가 동결되어 되살아날 수
   없다 - 의도된 단방향 설계(수동으로 CSV에서 지우면 복귀 가능).
3. 성과 리포트(`output/_pipeline/analysis/word_performance_latest.md`) -
   매 라운드 종료 시 자동 갱신되고, `expand_word_bank` 판정 요청에 요약이
   직접 포함되어 새 단어 제안이 실측 승자 패턴을 따르도록 강제한다.

Keyword Planner 게이트 자체(임계값·비교 로직)는 이 학습 루프의 대상이
아니다 - 게이트는 시장 신호이며 약화하면 가짜 데이터만 늘어난다(설계 문서
`docs/design/15-continuous-word-quality-improvement.md` 참고).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .contracts import atomic_write_text

# 은퇴 기준: 이만큼 시도했는데 통과 0건이면 "죽은 기능어"로 판정.
# 실측 근거: 2026-08-18 분석에서 300회+ 시도 기능어의 통과율 분포는
# 0.00%(28개)와 1%+(승자군)로 양분됐고 그 사이가 비어 있었다 - 300회 시도에
# 0건이면 통과율 1%였을 때 관측될 확률이 (0.99)^300 ≈ 4.9%로 충분히 낮다.
RETIREMENT_MIN_ATTEMPTS = 300

RETIRED_COLUMNS = ("word", "passed", "attempts", "retired_at")

# 리포트/판정 요약에서 "충분히 표본이 쌓인" 기능어만 순위에 올리는 기준.
MIN_ATTEMPTS_FOR_RANKING = 100


def metrics_cache_path(project_root: Path) -> Path:
    return project_root / "output" / "deliverables" / "history" / "keyword_metrics_cache.csv"


def report_path(project_root: Path) -> Path:
    return project_root / "output" / "_pipeline" / "analysis" / "word_performance_latest.md"


def retired_function_words_path(project_root: Path) -> Path:
    return project_root / "config" / "retired_function_words.csv"


def load_cache_rows(project_root: Path) -> list[dict]:
    path = metrics_cache_path(project_root)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _split_two_word_title(title: str) -> tuple[str, str] | None:
    parts = title.split()
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def function_word_stats(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """기능어(제목의 두 번째 단어) -> (통과 수, 시도 수)."""
    stats: dict[str, list[int]] = {}
    for row in rows:
        split = _split_two_word_title(row.get("title", ""))
        if split is None:
            continue
        _, fn = split
        entry = stats.setdefault(fn, [0, 0])
        entry[1] += 1
        if row.get("gate_passed") == "True":
            entry[0] += 1
    return {word: (p, t) for word, (p, t) in stats.items()}


def domain_word_stats(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """도메인어(제목의 첫 번째 단어) -> (통과 수, 시도 수)."""
    stats: dict[str, list[int]] = {}
    for row in rows:
        split = _split_two_word_title(row.get("title", ""))
        if split is None:
            continue
        dom, _ = split
        entry = stats.setdefault(dom, [0, 0])
        entry[1] += 1
        if row.get("gate_passed") == "True":
            entry[0] += 1
    return {word: (p, t) for word, (p, t) in stats.items()}


def retirement_candidates(
    stats: dict[str, tuple[int, int]], *, min_attempts: int = RETIREMENT_MIN_ATTEMPTS
) -> list[tuple[str, int, int]]:
    """통과 0건이면서 시도 수가 기준 이상인 기능어. (word, passed, attempts)."""
    return sorted(
        (word, p, t) for word, (p, t) in stats.items() if p == 0 and t >= min_attempts
    )


def load_retired_function_words(project_root: Path) -> set[str]:
    path = retired_function_words_path(project_root)
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8", newline="") as f:
        return {row["word"] for row in csv.DictReader(f) if row.get("word")}


def merge_retired_function_words(
    project_root: Path, candidates: list[tuple[str, int, int]], when: str
) -> int:
    """은퇴 후보를 `config/retired_function_words.csv`에 병합(기존 행 유지,
    중복 제외). 새로 추가된 개수를 반환한다."""
    path = retired_function_words_path(project_root)
    rows: list[dict] = []
    seen: set[str] = set()
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                word = row.get("word", "")
                if word and word.lower() not in seen:
                    seen.add(word.lower())
                    rows.append(row)
    added = 0
    for word, passed, attempts in candidates:
        if word.lower() in seen:
            continue
        seen.add(word.lower())
        rows.append({"word": word, "passed": str(passed), "attempts": str(attempts), "retired_at": when})
        added += 1
    if added == 0 and not rows:
        return 0

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=RETIRED_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(path, buffer.getvalue())
    return added


def _ranked(stats: dict[str, tuple[int, int]], *, min_attempts: int) -> list[tuple[str, int, int, float]]:
    rows = [
        (word, p, t, (100.0 * p / t) if t else 0.0)
        for word, (p, t) in stats.items()
        if t >= min_attempts
    ]
    return sorted(rows, key=lambda x: (-x[3], -x[1], x[0]))


def performance_summary_for_expansion(project_root: Path, *, top_n: int = 10) -> dict:
    """`expand_word_bank` 판정 요청에 직접 포함되는 실측 성과 요약. 새 단어
    제안이 파일을 따로 찾아 읽지 않아도 승자/사망 패턴을 알 수 있게 한다."""
    rows = load_cache_rows(project_root)
    fn_stats = function_word_stats(rows)
    retired = sorted(load_retired_function_words(project_root))
    top = _ranked(fn_stats, min_attempts=MIN_ATTEMPTS_FOR_RANKING)[:top_n]
    return {
        "function_word_performance_note": (
            "누적 Keyword Planner 실측 통과율. 새 기능어는 아래 top_function_words의 "
            "패턴(사람들이 실제 검색하는 구체적 장소/사물 명사)을 닮게 제안하고, "
            "retired_function_words의 패턴(SaaS 전문용어풍 합성어)은 제안 금지."
        ),
        "top_function_words": [
            {"word": w, "passed": p, "attempts": t, "pass_rate_pct": round(r, 2)}
            for w, p, t, r in top
        ],
        "retired_function_words": retired,
    }


def render_report(
    fn_stats: dict[str, tuple[int, int]],
    dom_stats: dict[str, tuple[int, int]],
    retired: set[str],
    when: str,
) -> str:
    total_pass = sum(p for p, _ in fn_stats.values())
    total = sum(t for _, t in fn_stats.values())
    overall = (100.0 * total_pass / total) if total else 0.0

    lines = [
        "# 단어 성과 리포트 (자동 생성)",
        "",
        f"- 생성 시각: {when}",
        f"- 누적 통과율: {total_pass}/{total} = {overall:.2f}%",
        f"- 은퇴 기능어: {len(retired)}개 (`config/retired_function_words.csv`)",
        "",
        f"## 기능어 통과율 상위 (시도 {MIN_ATTEMPTS_FOR_RANKING}회 이상)",
        "",
        "| 기능어 | 통과 | 시도 | 통과율 |",
        "|---|---|---|---|",
    ]
    for word, p, t, r in _ranked(fn_stats, min_attempts=MIN_ATTEMPTS_FOR_RANKING)[:20]:
        lines.append(f"| {word} | {p} | {t} | {r:.2f}% |")

    zero = retirement_candidates(fn_stats)
    lines += [
        "",
        f"## 은퇴 대상(통과 0 / 시도 {RETIREMENT_MIN_ATTEMPTS}회 이상)",
        "",
        ", ".join(w for w, _, _ in zero) if zero else "(없음)",
        "",
        "## 도메인어 통과율 상위 (시도 30회 이상)",
        "",
        "| 도메인어 | 통과 | 시도 | 통과율 |",
        "|---|---|---|---|",
    ]
    for word, p, t, r in _ranked(dom_stats, min_attempts=30)[:20]:
        lines.append(f"| {word} | {p} | {t} | {r:.2f}% |")
    lines += [
        "",
        "> 해석 가이드: 새 기능어를 제안할 때는 상위 표의 패턴(실제 검색되는 구체적",
        "> 명사)을 닮게, 은퇴 목록의 패턴(전문용어풍 합성어)은 피한다. Keyword",
        "> Planner 게이트 임계값 자체는 조정 대상이 아니다.",
        "",
    ]
    return "\n".join(lines)


def write_report(project_root: Path, when) -> Path | None:
    """누적 캐시가 있으면 성과 리포트를 갱신하고 경로를 반환. 없으면 no-op."""
    rows = load_cache_rows(project_root)
    if not rows:
        return None
    fn_stats = function_word_stats(rows)
    dom_stats = domain_word_stats(rows)
    retired = load_retired_function_words(project_root)
    path = report_path(project_root)
    atomic_write_text(path, render_report(fn_stats, dom_stats, retired, when.isoformat()))
    return path


# ---------------------------------------------------------------------------
# 라운드별 정체 점검 (2026-08-19, 사용자 지시): "라운드가 끝날 때마다 단어
# 생성 능력이 정말 향상됐는지, 정체되고 있는 건 아닌지" 자동으로 더블체크하는
# 루틴. 위의 기능어/도메인어 통계는 "누적 스냅샷"이라 라운드를 거듭해도 추세를
# 알 수 없다 - 이 절이 라운드마다 한 줄씩 쌓는 이력(`round_history.csv`)과
# 그 이력을 최근/이전 구간으로 나눠 비교하는 정체 감지를 더한다.
# ---------------------------------------------------------------------------

ROUND_HISTORY_COLUMNS = (
    "run_id",
    "mode",
    "completed_at",
    "generated",
    "ai_approved",
    "backlog_carried",
    "kp_passed",
    "round_pass_rate_pct",
)

# 정체/개선/저하를 가르는 상대 변화 임계값(%). 라운드 단위 통과율은 표본이
# 작을수록 흔들리므로(2026-08-18 실측: 0.68% -> 0.82%는 22/2691 표본), ±10%
# 미만의 변화는 "정체"로 본다 - 노이즈를 개선/저하로 오판하지 않기 위함.
STAGNATION_DECLINE_THRESHOLD_PCT = 10.0

# 정체 판단에 묶는 한 구간(최근/이전)의 최소 누적 생성 수. 이보다 작은
# 표본으로 비교하면 우연에 의한 오판정이 잦다 - 500개면 통과 1건 차이가
# 미치는 영향이 0.2%p 이내로 줄어든다.
STAGNATION_MIN_GENERATED_PER_WINDOW = 500


def round_history_path(project_root: Path) -> Path:
    return project_root / "output" / "_pipeline" / "analysis" / "round_history.csv"


def load_round_history(project_root: Path) -> list[dict]:
    path = round_history_path(project_root)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def append_round_history(project_root: Path, run_id: str, mode: str, when: str, round_stats: dict) -> dict:
    """라운드 완료 시 정확히 한 번 호출된다(`_stage_update_memory_and_git_checkpoint`).
    같은 run_id가 이미 기록돼 있으면 재기록하지 않고 기존 행을 반환한다 -
    이미 DONE인 run을 실수로 다시 --resume해도 이력이 중복되지 않는다."""
    rows = load_round_history(project_root)
    existing = next((r for r in rows if r["run_id"] == run_id), None)
    if existing is not None:
        return existing

    generated = int(round_stats.get("generated", 0) or 0)
    kp_passed = int(round_stats.get("kp_passed", 0) or 0)
    row = {
        "run_id": run_id,
        "mode": mode,
        "completed_at": when,
        "generated": str(generated),
        "ai_approved": str(int(round_stats.get("ai_approved", 0) or 0)),
        "backlog_carried": str(int(round_stats.get("backlog_carried", 0) or 0)),
        "kp_passed": str(kp_passed),
        "round_pass_rate_pct": f"{100.0 * kp_passed / generated:.4f}" if generated else "",
    }
    rows.append(row)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=ROUND_HISTORY_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(round_history_path(project_root), buffer.getvalue())
    return row


def _stagnation_windows(rows: list[dict], min_generated: int) -> list[dict]:
    """가장 최근 라운드부터 거꾸로, generated>0인 라운드만 누적해 min_generated
    이상 채워질 때마다 하나의 구간으로 묶는다(최대 2개: 최근/이전).
    backlog만 처리한 라운드(generated=0)는 신규 생성 능력에 대한 신호가 없으므로
    구간 계산에서 제외한다(이력에는 그대로 남아 감사 추적용으로 보존됨)."""
    usable = [r for r in reversed(rows) if int(r["generated"] or 0) > 0]
    windows: list[dict] = []
    i = 0
    while i < len(usable) and len(windows) < 2:
        gen_sum = passed_sum = rounds = 0
        while i < len(usable) and gen_sum < min_generated:
            gen_sum += int(usable[i]["generated"])
            passed_sum += int(usable[i]["kp_passed"])
            rounds += 1
            i += 1
        windows.append({"generated": gen_sum, "kp_passed": passed_sum, "rounds": rounds})
    return windows


def detect_stagnation(
    rows: list[dict],
    *,
    min_generated: int = STAGNATION_MIN_GENERATED_PER_WINDOW,
    decline_threshold_pct: float = STAGNATION_DECLINE_THRESHOLD_PCT,
) -> dict:
    """최근 구간과 그 직전 구간의 통과율을 비교해 improving/stagnant/declining을
    판정한다. 두 구간을 채울 이력이 아직 없으면 insufficient_data."""
    windows = _stagnation_windows(rows, min_generated)
    if len(windows) < 2 or windows[1]["generated"] < min_generated:
        return {
            "status": "insufficient_data",
            "min_generated": min_generated,
        }

    recent, prior = windows[0], windows[1]
    recent_rate = 100.0 * recent["kp_passed"] / recent["generated"]
    prior_rate = 100.0 * prior["kp_passed"] / prior["generated"]

    if prior_rate == 0.0 and recent_rate == 0.0:
        status = "stagnant"
        delta_relative = 0.0
    elif prior_rate == 0.0:
        status = "improving"
        delta_relative = float("inf")
    else:
        delta_relative = 100.0 * (recent_rate - prior_rate) / prior_rate
        if delta_relative <= -decline_threshold_pct:
            status = "declining"
        elif delta_relative >= decline_threshold_pct:
            status = "improving"
        else:
            status = "stagnant"

    return {
        "status": status,
        "recent_generated": recent["generated"],
        "recent_kp_passed": recent["kp_passed"],
        "recent_pass_rate_pct": round(recent_rate, 3),
        "recent_rounds": recent["rounds"],
        "prior_generated": prior["generated"],
        "prior_kp_passed": prior["kp_passed"],
        "prior_pass_rate_pct": round(prior_rate, 3),
        "prior_rounds": prior["rounds"],
        "delta_relative_pct": delta_relative,
    }


def format_stagnation_message(result: dict) -> str:
    """`detect_stagnation`의 결과를 콘솔·HANDOFF에 바로 쓸 수 있는 한 줄로."""
    if result["status"] == "insufficient_data":
        return (
            f"[학습 정체 점검] 데이터 부족 - 최근/이전 구간 각각 생성 "
            f"{result['min_generated']}개 이상 쌓여야 판단 가능"
        )
    label = {"improving": "향상 중", "stagnant": "정체", "declining": "저하"}[result["status"]]
    delta = result["delta_relative_pct"]
    delta_str = "+∞%" if delta == float("inf") else f"{delta:+.1f}%"
    return (
        f"[학습 정체 점검] {label}: 최근 {result['recent_rounds']}라운드"
        f"(생성 {result['recent_generated']}개) 통과율 {result['recent_pass_rate_pct']:.2f}% "
        f"vs 이전 {result['prior_rounds']}라운드(생성 {result['prior_generated']}개) "
        f"{result['prior_pass_rate_pct']:.2f}% (상대변화 {delta_str}, "
        f"임계값 ±{STAGNATION_DECLINE_THRESHOLD_PCT:.0f}%)"
    )
