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


# ---------------------------------------------------------------------------
# 4.8 title-conflict calibration
# ---------------------------------------------------------------------------


def test_title_brand_conflict_flagged_detects_marker_case_insensitively():
    assert gc.title_brand_conflict_flagged("looks like a title_brand_conflict with Notion")
    assert gc.title_brand_conflict_flagged("TITLE_BRAND_CONFLICT")
    assert not gc.title_brand_conflict_flagged("looks fine")
    assert not gc.title_brand_conflict_flagged(None)


def test_classify_title_collision_brand_conflict_wins_over_everything():
    assert gc.classify_title_collision(0, None, "TITLE_BRAND_CONFLICT: same as existing app") == "BRAND_CONFLICT"


def test_classify_title_collision_relevant_top_results_is_collision():
    assert gc.classify_title_collision(500, 3, None) == "COLLISION"


def test_classify_title_collision_low_count_no_relevant_hits_is_novel():
    assert gc.classify_title_collision(5, 0, None) == "NOVEL"
    assert gc.classify_title_collision(5, None, None) == "NOVEL"


def test_classify_title_collision_high_count_no_relevant_hits_is_generic():
    assert gc.classify_title_collision(50_000, 0, None) == "GENERIC"
    assert gc.classify_title_collision(50_000, None, None) == "GENERIC"


def test_group_title_observations_by_title_ignores_market_query_and_missing_title():
    observations = [
        {"query_type": "TITLE_QUERY", "title": "Vendor Guard", "user_result_count": 1},
        {"query_type": "MARKET_QUERY", "title": "Vendor Guard", "user_result_count": 1},
        {"query_type": "TITLE_QUERY", "title": "", "user_result_count": 1},
        {"query_type": "TITLE_QUERY", "title": "Vendor Guard", "user_result_count": 2},
    ]
    grouped = gc.group_title_observations_by_title(observations)
    assert list(grouped.keys()) == ["Vendor Guard"]
    assert len(grouped["Vendor Guard"]) == 2


def test_compute_title_calibration_no_observations_is_neutral_zero():
    result = gc.compute_title_calibration([])
    assert result == {
        "validation_count": 0,
        "google_title_footprint": None,
        "google_title_collision_class": None,
        "title_collision_adjustment": 0.0,
    }


def test_compute_title_calibration_uses_most_recent_observation():
    observations = [
        {"user_result_count": 500, "top_results_relevant": 3, "user_notes": None},  # older: COLLISION
        {"user_result_count": 2, "top_results_relevant": 0, "user_notes": None},  # latest: NOVEL
    ]
    result = gc.compute_title_calibration(observations)
    assert result["validation_count"] == 2
    assert result["google_title_collision_class"] == "NOVEL"
    assert result["title_collision_adjustment"] == gc.TITLE_COLLISION_ADJUSTMENTS["NOVEL"]
    assert result["google_title_footprint"] == round(gc.google_footprint(2), 4)


def test_compute_title_calibration_brand_conflict_gets_large_negative_adjustment():
    result = gc.compute_title_calibration(
        [{"user_result_count": 10, "top_results_relevant": None, "user_notes": "TITLE_BRAND_CONFLICT"}]
    )
    assert result["google_title_collision_class"] == "BRAND_CONFLICT"
    assert result["title_collision_adjustment"] < -50


# ---------------------------------------------------------------------------
# 4.11 processing states
# ---------------------------------------------------------------------------


def test_market_query_needs_research_true_on_large_band_gap():
    observations = [
        {"user_result_count": 200_000, "top_results_relevant": 5, "predicted_result_band_at_time": "VERY_LOW"}
    ]
    assert gc.market_query_needs_research(observations)


def test_market_query_needs_research_false_when_prediction_close():
    observations = [
        {"user_result_count": 50, "top_results_relevant": None, "predicted_result_band_at_time": "LOW"}
    ]
    assert not gc.market_query_needs_research(observations)


def test_market_query_needs_research_false_without_recorded_prediction():
    assert not gc.market_query_needs_research([{"user_result_count": 200_000, "top_results_relevant": 5}])


def test_classify_import_row_status_queued_when_untouched():
    assert gc.classify_import_row_status({"validation_id": "GVQ-1", "user_result_count": "", "user_checked_at": ""}) == "QUEUED"


def test_classify_import_row_status_partially_filled_when_one_side_missing():
    row = {"validation_id": "GVQ-1", "user_result_count": "", "user_checked_at": "2026-08-04T20:15:00+09:00"}
    assert gc.classify_import_row_status(row) == "PARTIALLY_FILLED"


def test_classify_import_row_status_invalid_when_malformed():
    row = {"validation_id": "GVQ-1", "user_result_count": "not-a-number", "user_checked_at": "2026-08-04T20:15:00+09:00"}
    assert gc.classify_import_row_status(row) == "INVALID"


def test_classify_import_row_status_invalid_when_no_validation_id():
    row = {"validation_id": "", "user_result_count": "100", "user_checked_at": "2026-08-04T20:15:00+09:00"}
    assert gc.classify_import_row_status(row) == "INVALID"


def test_classify_import_row_status_ready_when_fully_filled_and_well_formed():
    row = {"validation_id": "GVQ-1", "user_result_count": "100", "user_checked_at": "2026-08-04T20:15:00+09:00"}
    assert gc.classify_import_row_status(row) == "READY"
