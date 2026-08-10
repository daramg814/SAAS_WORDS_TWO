import math

from saas_words_two import google_calibration as gc


def test_google_footprint_log10():
    assert gc.google_footprint(0) == 0.0
    assert math.isclose(gc.google_footprint(99), math.log10(100))


def test_result_band_matches_table_boundaries():
    assert gc.result_band(0) == "VERY_LOW"
    assert gc.result_band(99) == "VERY_LOW"
    assert gc.result_band(100) == "LOW"
    assert gc.result_band(999) == "LOW"
    assert gc.result_band(1000) == "MEDIUM"
    assert gc.result_band(9999) == "MEDIUM"
    assert gc.result_band(10000) == "HIGH"
    assert gc.result_band(99999) == "HIGH"
    assert gc.result_band(100000) == "VERY_HIGH"
    assert gc.result_band(18400) == "HIGH"  # matches the sample fixture row


def test_band_distance_signed():
    assert gc.band_distance("LOW", "VERY_HIGH") == 3
    assert gc.band_distance("VERY_HIGH", "LOW") == -3
    assert gc.band_distance("MEDIUM", "MEDIUM") == 0


def test_classify_market_query_error_underestimated_and_overestimated():
    assert gc.classify_market_query_error("LOW", "VERY_HIGH", top_results_relevant=None) == "SUPPLY_UNDERESTIMATED"
    assert gc.classify_market_query_error("VERY_HIGH", "LOW", top_results_relevant=None) == "SUPPLY_OVERESTIMATED"


def test_classify_market_query_error_noise_and_niche():
    assert (
        gc.classify_market_query_error("HIGH", "HIGH", top_results_relevant=0) == "QUERY_NOISE_HIGH"
    )
    assert (
        gc.classify_market_query_error("LOW", "LOW", top_results_relevant=5) == "NICHE_COMPETITION_DENSE"
    )


def test_classify_market_query_error_calibrated_when_close_and_no_signal():
    assert gc.classify_market_query_error("MEDIUM", "MEDIUM", top_results_relevant=None) == "CALIBRATED"
    assert gc.classify_market_query_error("MEDIUM", "HIGH", top_results_relevant=None) == "CALIBRATED"


def test_classify_title_query_error_brand_conflict_takes_priority():
    result = gc.classify_title_query_error("LOW", "VERY_HIGH", brand_conflict_flagged=True)
    assert result == "TITLE_BRAND_CONFLICT"


def test_classify_title_query_error_collision_under_and_over():
    assert (
        gc.classify_title_query_error("LOW", "VERY_HIGH", brand_conflict_flagged=False)
        == "TITLE_COLLISION_UNDERESTIMATED"
    )
    assert (
        gc.classify_title_query_error("VERY_HIGH", "LOW", brand_conflict_flagged=False)
        == "TITLE_COLLISION_OVERESTIMATED"
    )


def test_classify_title_query_error_generic_vs_clear():
    assert gc.classify_title_query_error("HIGH", "HIGH", brand_conflict_flagged=False) == "TITLE_GENERIC_PHRASE"
    assert gc.classify_title_query_error("LOW", "LOW", brand_conflict_flagged=False) == "TITLE_CLEAR"


def test_human_weight_scales_with_observation_count_and_caps_at_25_percent():
    assert gc.human_weight(1, count_only=False) == 0.25 / 20
    assert gc.human_weight(5, count_only=False) == 0.0625
    assert gc.human_weight(20, count_only=False) == 0.25
    assert gc.human_weight(100, count_only=False) == 0.25


def test_human_weight_count_only_capped_at_half():
    assert gc.human_weight(20, count_only=True) == 0.125
    assert gc.human_weight(5, count_only=True) == 0.0625


def test_adjusted_supply_scarcity_blends_by_weight():
    assert gc.adjusted_supply_scarcity(80, 20, 0.0) == 80
    assert gc.adjusted_supply_scarcity(80, 20, 1.0) == 20
    assert gc.adjusted_supply_scarcity(80, 20, 0.25) == 80 * 0.75 + 20 * 0.25


def test_calibration_status_provisional_below_full_weight_threshold():
    assert gc.calibration_status(1) == "PROVISIONAL"
    assert gc.calibration_status(19) == "PROVISIONAL"
    assert gc.calibration_status(20) == "CALIBRATED"


def test_validate_import_row_requires_minimum_fields():
    result = gc.validate_import_row({"validation_id": "GVQ-1", "user_result_count": "", "user_checked_at": "t"})
    assert not result.valid
    assert any("user_result_count" in e for e in result.errors)


def test_validate_import_row_rejects_non_integer_count():
    result = gc.validate_import_row(
        {"validation_id": "GVQ-1", "user_result_count": "abc", "user_checked_at": "2026-08-04T20:15:00+09:00"}
    )
    assert not result.valid


def test_validate_import_row_rejects_non_iso_date():
    result = gc.validate_import_row(
        {"validation_id": "GVQ-1", "user_result_count": "100", "user_checked_at": "2026-08-04"}
    )
    assert not result.valid


def test_validate_import_row_accepts_minimal_valid_row():
    result = gc.validate_import_row(
        {"validation_id": "GVQ-1", "user_result_count": "100", "user_checked_at": "2026-08-04T20:15:00+09:00"}
    )
    assert result.valid


def test_is_duplicate_observation_requires_exact_triple_match():
    existing = [{"validation_id": "GVQ-1", "user_result_count": 100, "user_checked_at": "t0"}]
    assert gc.is_duplicate_observation(
        {"validation_id": "GVQ-1", "user_result_count": "100", "user_checked_at": "t0"}, existing
    )
    assert not gc.is_duplicate_observation(
        {"validation_id": "GVQ-1", "user_result_count": "100", "user_checked_at": "t1"}, existing
    )


def test_is_duplicate_observation_same_query_different_date_is_not_duplicate():
    existing = [{"validation_id": "GVQ-1", "user_result_count": 100, "user_checked_at": "2026-08-01T00:00:00+09:00"}]
    assert not gc.is_duplicate_observation(
        {"validation_id": "GVQ-1", "user_result_count": "150", "user_checked_at": "2026-08-05T00:00:00+09:00"},
        existing,
    )
