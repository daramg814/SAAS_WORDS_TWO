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
