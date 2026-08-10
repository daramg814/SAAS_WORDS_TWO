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


def _selection_sort_key(item: dict) -> tuple:
    # priority_score (market/opportunity score, design 8.1) ranks first;
    # title_collision_adjustment (design 4.8's separate title-quality score)
    # only breaks ties within that - CLAUDE.md rule 8 requires MARKET_QUERY
    # and TITLE_QUERY calibration to feed different scores, never blended
    # into one number. Missing the key (most callers/tests) defaults to 0.0,
    # i.e. no effect on ordering.
    return (item["priority_score"], item.get("title_collision_adjustment", 0.0))


def select_final_titles(approved: list[dict], target_count: int) -> list[dict]:
    """Pick up to target_count from an approved pool, ranked by opportunity
    priority_score (ties broken by title_collision_adjustment, design 4.8),
    capped at 30% per opportunity (docs/pipeline/10-title-generation.md 9.4).
    Clarity/diversity/distance/pronounceability were already judged when each
    title was approved, so priority ordering plus the cap is what's left for
    code to enforce.

    Deliberately never exceeds the cap to force target_count: if the capped
    pool can't fill target_count, this returns fewer, same as
    allocate_title_slots - the caller's signal to generate more candidates
    from underrepresented opportunities rather than overconcentrate.
    Expects each item to have "problem_id" and "priority_score" keys.
    """
    if len(approved) <= target_count:
        cap = max_titles_per_opportunity(target_count)
        per_opportunity_count: dict[str, int] = {}
        within_cap = []
        for item in sorted(approved, key=_selection_sort_key, reverse=True):
            pid = item["problem_id"]
            if per_opportunity_count.get(pid, 0) >= cap:
                continue
            within_cap.append(item)
            per_opportunity_count[pid] = per_opportunity_count.get(pid, 0) + 1
        return within_cap

    cap = max_titles_per_opportunity(target_count)
    ordered = sorted(approved, key=_selection_sort_key, reverse=True)

    selected: list[dict] = []
    per_opportunity_count = {}
    for item in ordered:
        if len(selected) >= target_count:
            break
        pid = item["problem_id"]
        if per_opportunity_count.get(pid, 0) >= cap:
            continue
        selected.append(item)
        per_opportunity_count[pid] = per_opportunity_count.get(pid, 0) + 1

    return selected
