"""design roadmap 3차 개선 "데이터원별 신뢰도 보정".

각 데이터원(hacker_news/gh_archive/stack_exchange_dump/npm_registry/
common_crawl/official_feeds)이 기여한 증거가 실제로 통과 판정까지 이어졌는지를
파이프라인 자체의 누적 결과(problem_evidence + demand_scores,
supply_candidates + supply_verification)만으로 집계하는 순수 함수 모음이다.

CLAUDE.md 12항(기존 점수 기준을 임의로 변경하지 않는다)에 따라 이 계산은
demand_scoring.py/opportunity_scoring.py의 점수 공식 입력을 바꾸지 않는다 —
그 결과는 collect_and_verify_supply/review_opportunities 판정 단계에 참고
정보로만 전달되고, 최종 수용/거부는 여전히 그 단계의 AI 판정이 결정한다.

표본이 MINIMUM_SAMPLES_FOR_CALIBRATION 미만인 소스는 NO_DATA로 유지한다 —
google_calibration.py의 human_calibration_status와 동일한, "표본 부족은
판정 근거로 쓰지 않는다"는 패턴을 그대로 따른다.
"""

from __future__ import annotations

from dataclasses import dataclass

MINIMUM_SAMPLES_FOR_CALIBRATION = 5

NO_DATA = "NO_DATA"
CALIBRATED = "CALIBRATED"


@dataclass(frozen=True)
class SideReliability:
    total: int
    positive: int
    score: float | None
    status: str


def _side_reliability(total: int, positive: int) -> SideReliability:
    if total < MINIMUM_SAMPLES_FOR_CALIBRATION:
        return SideReliability(total=total, positive=positive, score=None, status=NO_DATA)
    return SideReliability(total=total, positive=positive, score=positive / total, status=CALIBRATED)


def compute_demand_reliability(rows: list[tuple[str, str, bool]]) -> dict[str, SideReliability]:
    """rows: (source, problem_id, passed) — one row per distinct (source,
    problem) pair that source contributed at least one evidence item to.
    passed reflects that problem's demand_scores.passed (False if the
    problem has not been scored yet, or scored and failed the gate)."""
    problems_by_source: dict[str, set[str]] = {}
    passed_by_source: dict[str, set[str]] = {}
    for source, problem_id, passed in rows:
        problems_by_source.setdefault(source, set()).add(problem_id)
        if passed:
            passed_by_source.setdefault(source, set()).add(problem_id)
    return {
        source: _side_reliability(len(problem_ids), len(passed_by_source.get(source, set())))
        for source, problem_ids in problems_by_source.items()
    }


def compute_supply_reliability(rows: list[tuple[str, bool]]) -> dict[str, SideReliability]:
    """rows: (source, active) — one row per supply_candidates row that has
    already been through the collect_and_verify_supply judgment (i.e. has a
    matching supply_verification row); unverified candidates are excluded
    so an unreviewed backlog doesn't dilute a source's rate."""
    total_by_source: dict[str, int] = {}
    active_by_source: dict[str, int] = {}
    for source, active in rows:
        total_by_source[source] = total_by_source.get(source, 0) + 1
        if active:
            active_by_source[source] = active_by_source.get(source, 0) + 1
    return {
        source: _side_reliability(total, active_by_source.get(source, 0))
        for source, total in total_by_source.items()
    }
