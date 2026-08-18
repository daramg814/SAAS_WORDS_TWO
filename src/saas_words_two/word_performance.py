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
