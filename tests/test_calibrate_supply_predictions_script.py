import json
import sys
from pathlib import Path

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
    metrics = script.build_metrics(observations)
    assert metrics["total_observations"] == 2
    assert metrics["market_query_observations"] == 2
    assert metrics["supply_underestimated_rate"] == 0.5
    assert metrics["status"] == "PROVISIONAL"


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
