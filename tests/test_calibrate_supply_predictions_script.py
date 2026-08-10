import json
import sys
from pathlib import Path

from saas_words_two import db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import calibrate_supply_predictions as script


def test_classify_observation_market_query_underestimated():
    observation = {
        "query_type": "MARKET_QUERY",
        "predicted_result_band_at_time": "LOW",
        "user_result_count": 500_000,
        "top_results_relevant": None,
    }
    assert script.classify_observation(observation) == "SUPPLY_UNDERESTIMATED"


def test_classify_observation_title_query_brand_conflict_from_notes():
    observation = {
        "query_type": "TITLE_QUERY",
        "predicted_result_band_at_time": "LOW",
        "user_result_count": 50,
        "user_notes": "found an exact brand conflict on page 1",
    }
    assert script.classify_observation(observation) == "TITLE_BRAND_CONFLICT"


def test_build_metrics_computes_rates_and_status(tmp_path):
    observations = [
        {
            "query_type": "MARKET_QUERY",
            "predicted_result_band_at_time": "LOW",
            "user_result_count": 500_000,
            "top_results_relevant": None,
        },
        {
            "query_type": "MARKET_QUERY",
            "predicted_result_band_at_time": "MEDIUM",
            "user_result_count": 500,
            "top_results_relevant": None,
        },
    ]
    conn = db.connect(tmp_path)
    metrics = script.build_metrics(observations, conn)
    conn.close()
    assert metrics["total_observations"] == 2
    assert metrics["market_query_observations"] == 2
    assert metrics["supply_underestimated_rate"] == 0.5
    assert metrics["status"] == "PROVISIONAL"
    assert metrics["observations_by_industry"] == {}
    assert metrics["supply_grade_changes_from_calibration"] == 0
    assert metrics["titles_rejected_by_human_validation"] == 0


def test_main_writes_metrics_file(tmp_path):
    ledger_dir = tmp_path / "memory" / "human_feedback"
    ledger_dir.mkdir(parents=True)
    record = {
        "query_type": "MARKET_QUERY",
        "predicted_result_band_at_time": "MEDIUM",
        "user_result_count": 500,
        "top_results_relevant": None,
    }
    (ledger_dir / "google_supply_observations.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")

    exit_code = script.main(["--project-root", str(tmp_path)])
    assert exit_code == 0
    metrics = json.loads((ledger_dir / "google_calibration_metrics.json").read_text(encoding="utf-8"))
    assert metrics["total_observations"] == 1


def test_per_industry_counts_groups_by_target_user(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("INSERT INTO problems (problem_id, target_user, status) VALUES ('P-0001', 'bookkeepers', 'DEMAND_PASSED')")
    conn.execute("INSERT INTO problems (problem_id, target_user, status) VALUES ('P-0002', 'contractors', 'DEMAND_PASSED')")
    conn.commit()
    observations = [
        {"query_type": "MARKET_QUERY", "problem_id": "P-0001"},
        {"query_type": "MARKET_QUERY", "problem_id": "P-0001"},
        {"query_type": "MARKET_QUERY", "problem_id": "P-0002"},
    ]
    counts = script.per_industry_counts(observations, conn)
    conn.close()
    assert counts == {"bookkeepers": 2, "contractors": 1}


def test_noise_rate_by_query_breaks_down_per_query():
    # QUERY_NOISE_HIGH needs a close prediction (|distance|<2) but a
    # HIGH/VERY_HIGH actual band with few relevant top results.
    market = [
        {"google_query": "vendor tracker", "predicted_result_band_at_time": "HIGH", "user_result_count": 500_000, "top_results_relevant": 0},
        {"google_query": "vendor tracker", "predicted_result_band_at_time": "HIGH", "user_result_count": 500_000, "top_results_relevant": 0},
        {"google_query": "permit flow", "predicted_result_band_at_time": "MEDIUM", "user_result_count": 500, "top_results_relevant": None},
    ]
    errors = [script.classify_observation(o) for o in market]
    result = script.noise_rate_by_query(market, errors)
    assert result["vendor tracker"]["count"] == 2
    assert result["vendor tracker"]["noise_rate"] == 1.0
    assert result["permit flow"]["noise_rate"] == 0.0


def test_queries_eligible_for_noise_rule_promotion_requires_min_repetitions_and_majority_noise():
    noise_by_query = {
        "too-few": {"count": 4, "noise_rate": 1.0},  # below MINIMUM_REPETITIONS_FOR_RULE_PROMOTION (5)
        "enough-but-clean": {"count": 5, "noise_rate": 0.2},
        "enough-and-noisy": {"count": 5, "noise_rate": 0.8},
    }
    assert script.queries_eligible_for_noise_rule_promotion(noise_by_query) == ["enough-and-noisy"]


def test_supply_grade_change_count_counts_flipped_grades(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute(
        "INSERT INTO problems (problem_id, status) VALUES ('P-0001', 'DEMAND_PASSED')"
    )
    # raw score 60 with effective_supply=3 -> grade C; stored (calibrated) grade B -> counts as changed
    conn.execute(
        "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
        "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, "
        "direct_competitor_count, human_calibration_status, updated_at) VALUES "
        "('P-0001', 80, 3.0, 60, 'B', 70, 'B', 'RESEARCH_MORE', '[]', '[]', 0, 'CALIBRATED', 't0')"
    )
    conn.execute(
        "INSERT INTO problems (problem_id, status) VALUES ('P-0002', 'DEMAND_PASSED')"
    )
    # unaffected: NO_DATA calibration status excluded regardless of grade
    conn.execute(
        "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
        "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, "
        "direct_competitor_count, human_calibration_status, updated_at) VALUES "
        "('P-0002', 80, 3.0, 60, 'C', 70, 'B', 'RESEARCH_MORE', '[]', '[]', 0, 'NO_DATA', 't0')"
    )
    conn.commit()
    assert script.supply_grade_change_count(conn) == 1
    conn.close()


def test_titles_rejected_by_human_validation_count(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("INSERT INTO problems (problem_id, status) VALUES ('P-0001', 'DEMAND_PASSED')")
    conn.execute(
        "INSERT INTO titles (title, normalized, problem_id, run_id, status, created_at, "
        "google_title_collision_class) VALUES "
        "('Vendor Guard', 'vendorguard', 'P-0001', 'RUN-1', 'approved', 't0', 'BRAND_CONFLICT')"
    )
    conn.execute(
        "INSERT INTO titles (title, normalized, problem_id, run_id, status, created_at, "
        "google_title_collision_class) VALUES "
        "('Permit Flow', 'permitflow', 'P-0001', 'RUN-1', 'selected', 't0', 'NOVEL')"
    )
    conn.commit()
    assert script.titles_rejected_by_human_validation_count(conn) == 1
    conn.close()
