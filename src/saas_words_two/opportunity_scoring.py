from __future__ import annotations

from dataclasses import dataclass

DEMAND_WEIGHT = 0.35
SUPPLY_SCARCITY_WEIGHT = 0.65
DEMAND_SCORE_MIN = 45
SUPPLY_SCARCITY_SCORE_MIN = 65
PRIORITY_SCORE_MIN = 65
ALLOWED_SCARCITY_GRADES = ("S", "A", "B")
ALLOWED_CONFIDENCE = ("A", "B")

GRADE_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3}
CONFIDENCE_ORDER = {"A": 0, "B": 1, "C": 2}


def priority_score(demand_score: int, supply_scarcity_score: int, effective_supply_value: float) -> float:
    base = demand_score * DEMAND_WEIGHT + supply_scarcity_score * SUPPLY_SCARCITY_WEIGHT
    if effective_supply_value <= 2:
        bonus = 10
    elif effective_supply_value <= 5:
        bonus = 5
    else:
        bonus = 0
    return min(100.0, base + bonus)


def confidence(
    source_count: int,
    independent_users: int,
    *,
    supply_fully_verified: bool,
    supply_partially_verified: bool,
) -> str:
    if source_count >= 3 and independent_users >= 25 and supply_fully_verified:
        return "A"
    if source_count >= 2 and independent_users >= 5 and (supply_partially_verified or supply_fully_verified):
        return "B"
    return "C"


@dataclass(frozen=True)
class OpportunityEligibilityInput:
    demand_score: int
    independent_users: int
    has_recent_evidence: bool
    is_repeated_task: bool
    has_loss_time_or_risk_evidence: bool
    has_clear_saas_feature: bool
    supply_scarcity_score: int
    priority_score_value: float
    scarcity_grade: str
    confidence_level: str
    has_manual_or_complaint_evidence: bool
    purchase_intent_or_loss: bool


def hard_exclusion_reasons(eligibility: OpportunityEligibilityInput) -> tuple[str, ...]:
    """These exclude a problem even if supply is zero (charter 1.3/1.6): the
    market itself may not exist, so absence of competition proves nothing."""
    reasons = []
    if eligibility.independent_users < 5:
        reasons.append("independent_users_below_5")
    if not eligibility.has_recent_evidence:
        reasons.append("no_recent_24_month_evidence")
    if not eligibility.is_repeated_task:
        reasons.append("not_repeated_task")
    if not eligibility.has_loss_time_or_risk_evidence:
        reasons.append("no_loss_time_or_risk_evidence")
    if not eligibility.has_clear_saas_feature:
        reasons.append("no_clear_saas_feature")
    return tuple(reasons)


def meets_generate_titles_conditions(eligibility: OpportunityEligibilityInput) -> bool:
    if hard_exclusion_reasons(eligibility):
        return False
    return (
        eligibility.demand_score >= DEMAND_SCORE_MIN
        and eligibility.supply_scarcity_score >= SUPPLY_SCARCITY_SCORE_MIN
        and eligibility.priority_score_value >= PRIORITY_SCORE_MIN
        and eligibility.scarcity_grade in ALLOWED_SCARCITY_GRADES
        and eligibility.confidence_level in ALLOWED_CONFIDENCE
        and eligibility.has_manual_or_complaint_evidence
        and eligibility.purchase_intent_or_loss
    )


def provisional_decision(eligibility: OpportunityEligibilityInput) -> str:
    """Code-only provisional call, used as the default for problems the
    opportunity-reviewer does not individually re-examine (8.5 has it review
    only the top-scoring subset). The reviewer's GENERATE_TITLES / RESEARCH_MORE
    / REJECT / SCARCITY_PRIORITY decision has no dedicated script per
    docs/architecture/06-agents-and-role-separation.md - SCARCITY_PRIORITY in
    particular requires judging whether the supply search was thorough enough
    and whether the loss evidence is genuinely repeated, not a numeric gate -
    so this function never assigns it; only the reviewer does, by overriding
    this value for the opportunities it actually looks at."""
    if hard_exclusion_reasons(eligibility):
        return "REJECT"
    if meets_generate_titles_conditions(eligibility):
        return "GENERATE_TITLES"
    return "RESEARCH_MORE"


def sort_key(opportunity: dict) -> tuple:
    return (
        GRADE_ORDER.get(opportunity["scarcity_grade"], 99),
        -opportunity["supply_scarcity_score"],
        opportunity["effective_supply"],
        -opportunity["priority_score"],
        CONFIDENCE_ORDER.get(opportunity["confidence"], 99),
        -opportunity["demand_score"],
    )


def sort_opportunities(opportunities: list[dict]) -> list[dict]:
    return sorted(opportunities, key=sort_key)
