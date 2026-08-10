from __future__ import annotations

import math
from dataclasses import dataclass

BAND_ORDER = ["VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"]
_BAND_THRESHOLDS = (
    (100_000, "VERY_HIGH"),
    (10_000, "HIGH"),
    (1_000, "MEDIUM"),
    (100, "LOW"),
    (0, "VERY_LOW"),
)
# Provisional heuristic (docs/policies/05-human-google-calibration.md 4.5 gives
# only the band table, not a scarcity mapping): more visible existing supply
# implies less scarcity. Candidate, not validated - see PROJECT_PLAYBOOK.md.
BAND_TO_SCARCITY_SCORE = {"VERY_LOW": 95.0, "LOW": 75.0, "MEDIUM": 50.0, "HIGH": 25.0, "VERY_HIGH": 5.0}

MAX_HUMAN_WEIGHT = 0.25
MAX_COUNT_ONLY_WEIGHT = 0.125
OBSERVATIONS_FOR_FULL_WEIGHT = 20

MARKET_QUEUE_SIZE = 20
TITLE_QUEUE_SIZE = 30


def google_footprint(user_result_count: int) -> float:
    return math.log10(user_result_count + 1)


def result_band(user_result_count: int) -> str:
    for threshold, band in _BAND_THRESHOLDS:
        if user_result_count >= threshold:
            return band
    return "VERY_LOW"


def band_distance(predicted_band: str, actual_band: str) -> int:
    return BAND_ORDER.index(actual_band) - BAND_ORDER.index(predicted_band)


def classify_market_query_error(
    predicted_band: str,
    actual_band: str,
    *,
    top_results_relevant: int | None,
) -> str:
    distance = band_distance(predicted_band, actual_band)
    if distance >= 2:
        return "SUPPLY_UNDERESTIMATED"
    if distance <= -2:
        return "SUPPLY_OVERESTIMATED"
    if top_results_relevant is not None:
        if actual_band in ("HIGH", "VERY_HIGH") and top_results_relevant <= 1:
            return "QUERY_NOISE_HIGH"
        if actual_band in ("VERY_LOW", "LOW") and top_results_relevant >= 3:
            return "NICHE_COMPETITION_DENSE"
    return "CALIBRATED"


def classify_title_query_error(
    predicted_band: str,
    actual_band: str,
    *,
    brand_conflict_flagged: bool,
) -> str:
    if brand_conflict_flagged:
        return "TITLE_BRAND_CONFLICT"
    distance = band_distance(predicted_band, actual_band)
    if distance >= 2:
        return "TITLE_COLLISION_UNDERESTIMATED"
    if distance <= -2:
        return "TITLE_COLLISION_OVERESTIMATED"
    if actual_band in ("HIGH", "VERY_HIGH"):
        return "TITLE_GENERIC_PHRASE"
    return "TITLE_CLEAR"


def human_google_scarcity_score(actual_band: str) -> float:
    return BAND_TO_SCARCITY_SCORE.get(actual_band, 50.0)


def human_weight(valid_market_observations: int, *, count_only: bool) -> float:
    weight = min(MAX_HUMAN_WEIGHT, valid_market_observations / OBSERVATIONS_FOR_FULL_WEIGHT * MAX_HUMAN_WEIGHT)
    if count_only:
        weight = min(weight, MAX_COUNT_ONLY_WEIGHT)
    return weight


def adjusted_supply_scarcity(base_score: float, human_scarcity_score: float, weight: float) -> float:
    return base_score * (1 - weight) + human_scarcity_score * weight


def calibration_status(valid_market_observations: int) -> str:
    return "CALIBRATED" if valid_market_observations >= OBSERVATIONS_FOR_FULL_WEIGHT else "PROVISIONAL"


def group_market_observations_by_problem(observations: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for observation in observations:
        if observation.get("query_type") != "MARKET_QUERY" or not observation.get("problem_id"):
            continue
        grouped.setdefault(observation["problem_id"], []).append(observation)
    return grouped


# 4.8: qualitative title-conflict rules, grounded directly in the existing
# TITLE_QUERY observation fields - distinct from classify_title_query_error()
# above, which grades AI *prediction accuracy* (4.6), not the title's actual
# collision risk (4.8). Exact numeric values are this implementation's choice
# (the design gives only "novelty bonus" / "neutral" / "strong penalty or
# elimination" / "immediate re-review", not numbers); BRAND_CONFLICT is large
# enough to always lose a tie-break, effectively excluding it in practice.
TITLE_COLLISION_ADJUSTMENTS = {
    "BRAND_CONFLICT": -100.0,
    "COLLISION": -10.0,
    "GENERIC": 0.0,
    "NOVEL": 1.0,
}


def title_brand_conflict_flagged(user_notes: str | None) -> bool:
    """4.8: '사용자가 메모로 직접 충돌을 표시하면 TITLE_BRAND_CONFLICT로 즉시 재검토' -
    the documented convention is the literal marker string in user_notes."""
    return bool(user_notes) and "TITLE_BRAND_CONFLICT" in user_notes.upper()


def classify_title_collision(
    user_result_count: int, top_results_relevant: int | None, user_notes: str | None
) -> str:
    if title_brand_conflict_flagged(user_notes):
        return "BRAND_CONFLICT"
    if top_results_relevant is not None and top_results_relevant >= 1:
        return "COLLISION"
    if result_band(user_result_count) in ("VERY_LOW", "LOW"):
        return "NOVEL"
    return "GENERIC"


def group_title_observations_by_title(observations: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for observation in observations:
        if observation.get("query_type") != "TITLE_QUERY" or not observation.get("title"):
            continue
        grouped.setdefault(observation["title"], []).append(observation)
    return grouped


def compute_title_calibration(observations_for_title: list[dict]) -> dict:
    """Ledger order is append-order (chronological); the most recent check
    is taken as the title's current status."""
    count = len(observations_for_title)
    if count == 0:
        return {
            "validation_count": 0,
            "google_title_footprint": None,
            "google_title_collision_class": None,
            "title_collision_adjustment": 0.0,
        }
    latest = observations_for_title[-1]
    collision_class = classify_title_collision(
        latest["user_result_count"], latest.get("top_results_relevant"), latest.get("user_notes")
    )
    return {
        "validation_count": count,
        "google_title_footprint": round(google_footprint(latest["user_result_count"]), 4),
        "google_title_collision_class": collision_class,
        "title_collision_adjustment": TITLE_COLLISION_ADJUSTMENTS[collision_class],
    }


def market_query_needs_research(observations_for_problem: list[dict]) -> bool:
    """4.11 RESEARCH_REQUIRED: 'AI 예측과 사람 관측 차이가 커서 공급 재조사 필요'.
    True if any observation's actual result band is >=2 steps away from what
    was predicted at queue-build time (classify_market_query_error's
    SUPPLY_UNDERESTIMATED/SUPPLY_OVERESTIMATED) - a large enough surprise to
    warrant re-investigating supply regardless of how many samples exist."""
    for observation in observations_for_problem:
        predicted_band = observation.get("predicted_result_band_at_time")
        if not predicted_band:
            continue
        actual_band = result_band(observation["user_result_count"])
        error = classify_market_query_error(
            predicted_band, actual_band, top_results_relevant=observation.get("top_results_relevant")
        )
        if error in ("SUPPLY_UNDERESTIMATED", "SUPPLY_OVERESTIMATED"):
            return True
    return False


def compute_supply_adjustment(observations_for_problem: list[dict], base_score: float) -> dict:
    """4.7: adjusted_supply_scarcity = base x (1-w) + human_google_scarcity x w.
    Shared by apply_human_calibration.py (recalibrates existing opportunities
    on demand) and score_opportunities.py (applies it inline on every score,
    so a freshly recomputed supply_scarcity_score is never left uncalibrated
    until the next standalone apply_human_calibration.py run)."""
    count = len(observations_for_problem)
    if count == 0:
        return {
            "observation_count": 0,
            "human_weight": 0.0,
            "adjusted_supply_scarcity_score": base_score,
            "status": "NO_DATA",
        }

    count_only = all(o.get("top_results_relevant") is None for o in observations_for_problem)
    weight = human_weight(count, count_only=count_only)
    bands = [result_band(o["user_result_count"]) for o in observations_for_problem]
    human_scarcity = sum(human_google_scarcity_score(band) for band in bands) / len(bands)
    adjusted = adjusted_supply_scarcity(base_score, human_scarcity, weight)
    status = (
        "RESEARCH_REQUIRED"
        if market_query_needs_research(observations_for_problem)
        else calibration_status(count)
    )

    return {
        "observation_count": count,
        "human_weight": weight,
        "adjusted_supply_scarcity_score": adjusted,
        "status": status,
    }


REQUIRED_IMPORT_FIELDS = ("validation_id", "user_result_count", "user_checked_at")


@dataclass(frozen=True)
class RowValidation:
    valid: bool
    errors: tuple[str, ...]


def validate_import_row(row: dict) -> RowValidation:
    errors: list[str] = []
    for field_name in REQUIRED_IMPORT_FIELDS:
        if not (row.get(field_name) or "").strip():
            errors.append(f"missing_required_field:{field_name}")
    if errors:
        return RowValidation(False, tuple(errors))

    raw_count = row["user_result_count"].strip()
    if not raw_count.isdigit():
        errors.append("user_result_count_not_a_nonnegative_integer")
    raw_checked_at = row["user_checked_at"].strip()
    if "T" not in raw_checked_at:
        errors.append("user_checked_at_not_iso8601")
    return RowValidation(not errors, tuple(errors))


def classify_import_row_status(row: dict) -> str:
    """4.11's per-row import lifecycle, checked before validate_import_row's
    field-format validation: a completely untouched queue row (QUEUED - the
    user hasn't filled anything in) is distinct from one the user started but
    didn't finish (PARTIALLY_FILLED), which is distinct again from one that's
    fully filled but malformed (INVALID, decided by validate_import_row)."""
    result_count = (row.get("user_result_count") or "").strip()
    checked_at = (row.get("user_checked_at") or "").strip()
    if not (row.get("validation_id") or "").strip():
        return "INVALID"
    if not result_count and not checked_at:
        return "QUEUED"
    if not result_count or not checked_at:
        return "PARTIALLY_FILLED"
    return "INVALID" if not validate_import_row(row).valid else "READY"


def is_duplicate_observation(
    row: dict, existing_observations: list[dict]
) -> bool:
    """Reject only a fully identical validation_id + result_count + checked_at
    triple (policy 4.4); re-checking the same query on a different date is a
    new, valid observation."""
    for existing in existing_observations:
        if (
            existing.get("validation_id") == row.get("validation_id")
            and str(existing.get("user_result_count")) == str(row.get("user_result_count"))
            and existing.get("user_checked_at") == row.get("user_checked_at")
        ):
            return True
    return False
