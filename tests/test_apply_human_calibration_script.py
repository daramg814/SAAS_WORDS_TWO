import sys
from pathlib import Path

from saas_words_two import db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import apply_human_calibration as script


def test_group_market_observations_by_problem_ignores_title_query_and_missing_problem_id():
    observations = [
        {"query_type": "MARKET_QUERY", "problem_id": "P-0001"},
        {"query_type": "TITLE_QUERY", "problem_id": "P-0001"},
        {"query_type": "MARKET_QUERY", "problem_id": None},
        {"query_type": "MARKET_QUERY", "problem_id": "P-0002"},
    ]
    grouped = script.group_market_observations_by_problem(observations)
    assert set(grouped.keys()) == {"P-0001", "P-0002"}
    assert len(grouped["P-0001"]) == 1


def test_compute_adjustment_no_observations_returns_base_score_unchanged():
    result = script.compute_adjustment([], base_score=80.0)
    assert result["adjusted_supply_scarcity_score"] == 80.0
    assert result["status"] == "NO_DATA"


def test_compute_adjustment_blends_toward_human_observation():
    # 5 observations, all VERY_LOW result count -> high human scarcity score
    observations = [{"user_result_count": 10, "top_results_relevant": 5} for _ in range(5)]
    result = script.compute_adjustment(observations, base_score=20.0)
    assert result["adjusted_supply_scarcity_score"] > 20.0  # pulled toward higher human scarcity
    assert result["status"] == "PROVISIONAL"
    assert 0 < result["human_weight"] <= 0.25


def test_compute_adjustment_status_is_research_required_when_ai_prediction_way_off(tmp_path):
    """4.11 RESEARCH_REQUIRED: predicted VERY_LOW but actual VERY_HIGH is a
    >=2-band surprise (google_calibration.classify_market_query_error), which
    overrides PROVISIONAL/CALIBRATED regardless of sample count."""
    observations = [
        {"user_result_count": 200_000, "top_results_relevant": 5, "predicted_result_band_at_time": "VERY_LOW"}
    ]
    result = script.compute_adjustment(observations, base_score=80.0)
    assert result["status"] == "RESEARCH_REQUIRED"


def test_compute_adjustment_status_ignores_observations_without_a_recorded_prediction():
    observations = [{"user_result_count": 200_000, "top_results_relevant": 5}]  # no predicted_result_band_at_time
    result = script.compute_adjustment(observations, base_score=80.0)
    assert result["status"] == "PROVISIONAL"


def test_apply_calibration_updates_opportunities_with_matching_observations(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute(
        "INSERT INTO problems (problem_id, status) VALUES ('P-0001', 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
        "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, updated_at) "
        "VALUES ('P-0001', 80, 1.0, 85, 'S', 90, 'A', 'GENERATE_TITLES', '[]', '[]', 't0')"
    )
    conn.commit()

    observations = [
        {"query_type": "MARKET_QUERY", "problem_id": "P-0001", "user_result_count": 50, "top_results_relevant": 1}
    ]
    updated = script.apply_calibration(conn, observations)
    assert updated == 1

    row = conn.execute("SELECT * FROM opportunities WHERE problem_id = 'P-0001'").fetchone()
    assert row["human_observation_count"] == 1
    assert row["human_adjusted_supply_scarcity_score"] is not None
    assert row["human_calibration_status"] == "PROVISIONAL"
    conn.close()


def test_apply_calibration_leaves_unobserved_opportunities_as_no_data(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("INSERT INTO problems (problem_id, status) VALUES ('P-0002', 'DEMAND_PASSED')")
    conn.execute(
        "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
        "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, updated_at) "
        "VALUES ('P-0002', 80, 1.0, 85, 'S', 90, 'A', 'GENERATE_TITLES', '[]', '[]', 't0')"
    )
    conn.commit()
    script.apply_calibration(conn, [])
    row = conn.execute("SELECT * FROM opportunities WHERE problem_id = 'P-0002'").fetchone()
    assert row["human_observation_count"] == 0
    assert row["human_adjusted_supply_scarcity_score"] is None
    assert row["human_calibration_status"] == "NO_DATA"
    conn.close()
