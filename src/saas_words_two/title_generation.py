from __future__ import annotations

import math

MIN_OPPORTUNITIES = 5
MAX_SHARE_PER_OPPORTUNITY = 0.30
MAX_ROUNDS = 5
FIRST_ROUND_MULTIPLIER = 1.6
FIRST_ROUND_MIN_EXTRA = 20
NEXT_ROUND_SHORTFALL_MULTIPLIER = 2


def first_round_size(
    target_count: int, *, multiplier: float = FIRST_ROUND_MULTIPLIER, min_extra: int = FIRST_ROUND_MIN_EXTRA
) -> int:
    return max(round(target_count * multiplier), target_count + min_extra)


def next_round_size(shortfall: int, *, multiplier: int = NEXT_ROUND_SHORTFALL_MULTIPLIER) -> int:
    return max(shortfall, 0) * multiplier


def max_titles_per_opportunity(target_count: int, *, max_share: float = MAX_SHARE_PER_OPPORTUNITY) -> int:
    return math.floor(target_count * max_share)


def check_distribution(
    counts_by_problem: dict[str, int],
    target_count: int,
    *,
    min_opportunities: int = MIN_OPPORTUNITIES,
) -> tuple[str, ...]:
    violations: list[str] = []
    used_opportunities = {problem_id for problem_id, count in counts_by_problem.items() if count > 0}
    if len(used_opportunities) < min_opportunities:
        violations.append(f"fewer_than_{min_opportunities}_opportunities:{len(used_opportunities)}")
    cap = max_titles_per_opportunity(target_count)
    for problem_id, count in counts_by_problem.items():
        if count > cap:
            violations.append(f"opportunity_over_30pct:{problem_id}:{count}>{cap}")
    return tuple(violations)


def allocate_title_slots(opportunities: list[dict], target_count: int) -> dict[str, int]:
    """Proportional (largest-remainder method) allocation of target_count slots
    across opportunities weighted by priority_score, capped at 30% per
    opportunity per docs/pipeline/10-title-generation.md 9.1. Returns fewer than
    target_count total slots if the opportunity pool is too small/too capped to
    reach it - callers should treat that as "need more opportunities", not a bug.
    """
    if not opportunities or target_count <= 0:
        return {}

    problem_ids = [opportunity["problem_id"] for opportunity in opportunities]
    weights = {opportunity["problem_id"]: max(opportunity["priority_score"], 0.0) for opportunity in opportunities}
    total_weight = sum(weights.values())
    if total_weight <= 0:
        weights = dict.fromkeys(problem_ids, 1.0)
        total_weight = float(len(problem_ids))

    cap = max_titles_per_opportunity(target_count)
    raw_shares = {pid: target_count * weights[pid] / total_weight for pid in problem_ids}
    allocation = {pid: min(int(raw_shares[pid]), cap) for pid in problem_ids}
    assigned = sum(allocation.values())

    remainder_order = sorted(problem_ids, key=lambda pid: raw_shares[pid] - int(raw_shares[pid]), reverse=True)
    cursor = 0
    max_attempts = len(remainder_order) * 10 if remainder_order else 0
    attempts = 0
    while assigned < target_count and attempts < max_attempts:
        pid = remainder_order[cursor % len(remainder_order)]
        if allocation[pid] < cap:
            allocation[pid] += 1
            assigned += 1
        cursor += 1
        attempts += 1
        if all(allocation[p] >= cap for p in problem_ids):
            break

    return allocation
