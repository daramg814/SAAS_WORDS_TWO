from __future__ import annotations

import time
from dataclasses import dataclass

DEMAND_SCORE_MIN = 45
INDEPENDENT_USERS_MIN = 5

FREQUENCY_POINTS = {
    "daily": 10,
    "weekly": 8,
    "monthly": 5,
    "occasional": 2,
    "unknown": 0,
}
RISK_SEVERITY_POINTS = {"severe": 15, "moderate": 8, "none": 0}
PURCHASE_INTENT_POINTS = {"strong": 15, "weak": 8, "none": 0}


def independent_users_score(independent_users: int) -> int:
    if independent_users >= 25:
        return 25
    if independent_users >= 10:
        return 20
    if independent_users >= 5:
        return 15
    if independent_users >= 1:
        return 5
    return 0


def persistence_score(distinct_periods: int) -> int:
    if distinct_periods >= 3:
        return 15
    if distinct_periods == 2:
        return 8
    return 0


def frequency_score(frequency: str) -> int:
    return FREQUENCY_POINTS.get(frequency, 0)


def risk_score(risk_severity: str) -> int:
    return RISK_SEVERITY_POINTS.get(risk_severity, 0)


def manual_evidence_score(has_manual_or_complaint_evidence: bool) -> int:
    return 10 if has_manual_or_complaint_evidence else 0


def purchase_intent_score(purchase_intent: str) -> int:
    return PURCHASE_INTENT_POINTS.get(purchase_intent, 0)


def source_diversity_score(distinct_threads: int) -> int:
    if distinct_threads >= 3:
        return 10
    if distinct_threads == 2:
        return 6
    if distinct_threads == 1:
        return 2
    return 0


def distinct_thread_ids(evidence: list[dict]) -> set[int]:
    """Approximate independent-source counting: a comment's thread is its
    immediate parent id; a story is its own id. Comments are fetched only a
    couple of levels deep (see collection.py), so this is a reasonable proxy
    for "distinct discussion" without walking the full parent chain."""
    threads: set[int] = set()
    for row in evidence:
        if row.get("type") == "comment" and row.get("parent"):
            threads.add(row["parent"])
        else:
            threads.add(row["id"])
    return threads


def distinct_period_count(timestamps: list[int | None], *, tz_offset_seconds: int = 9 * 3600) -> int:
    periods = set()
    for timestamp in timestamps:
        if timestamp is None:
            continue
        shifted = time.gmtime(timestamp + tz_offset_seconds)
        periods.add((shifted.tm_year, shifted.tm_mon))
    return len(periods)


def has_recent_evidence(timestamps: list[int | None], *, now_epoch: int, months: int = 24) -> bool:
    cutoff = now_epoch - months * 30 * 24 * 3600
    return any(timestamp is not None and timestamp >= cutoff for timestamp in timestamps)


@dataclass(frozen=True)
class DemandScoreInput:
    independent_users: int
    distinct_periods: int
    frequency: str
    risk_severity: str
    has_manual_or_complaint_evidence: bool
    purchase_intent: str
    distinct_threads: int
    has_recent_evidence: bool


@dataclass(frozen=True)
class DemandScoreResult:
    independent_users_score: int
    persistence_score: int
    frequency_score: int
    risk_score: int
    manual_evidence_score: int
    purchase_intent_score: int
    source_diversity_score: int
    total: int
    passed: bool
    fail_reasons: tuple[str, ...]


def score_demand(demand_input: DemandScoreInput) -> DemandScoreResult:
    scores = {
        "independent_users_score": independent_users_score(demand_input.independent_users),
        "persistence_score": persistence_score(demand_input.distinct_periods),
        "frequency_score": frequency_score(demand_input.frequency),
        "risk_score": risk_score(demand_input.risk_severity),
        "manual_evidence_score": manual_evidence_score(demand_input.has_manual_or_complaint_evidence),
        "purchase_intent_score": purchase_intent_score(demand_input.purchase_intent),
        "source_diversity_score": source_diversity_score(demand_input.distinct_threads),
    }
    total = sum(scores.values())

    fail_reasons: list[str] = []
    if total < DEMAND_SCORE_MIN:
        fail_reasons.append(f"total_below_minimum:{total}<{DEMAND_SCORE_MIN}")
    if demand_input.independent_users < INDEPENDENT_USERS_MIN:
        fail_reasons.append(f"independent_users_below_minimum:{demand_input.independent_users}<5")
    if not demand_input.has_recent_evidence:
        fail_reasons.append("no_recent_24_month_evidence")
    if not demand_input.has_manual_or_complaint_evidence:
        fail_reasons.append("no_manual_or_complaint_evidence")
    if demand_input.purchase_intent == "none" and demand_input.risk_severity == "none":
        fail_reasons.append("no_purchase_intent_or_economic_loss")

    return DemandScoreResult(
        **scores,
        total=total,
        passed=not fail_reasons,
        fail_reasons=tuple(fail_reasons),
    )
