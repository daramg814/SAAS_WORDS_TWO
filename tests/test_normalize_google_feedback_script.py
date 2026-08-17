import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import normalize_google_feedback as script


def test_normalize_observation_computes_footprint_and_band():
    observation = {
        "observation_id": "HGO-1",
        "validation_id": "GVQ-1",
        "query_type": "MARKET_QUERY",
        "user_result_count": 18400,
    }
    normalized = script.normalize_observation(observation)
    assert normalized["result_band"] == "HIGH"
    assert normalized["google_footprint"] > 4.0


def test_main_writes_normalized_json(tmp_path):
    ledger_dir = tmp_path / "memory" / "human_feedback"
    ledger_dir.mkdir(parents=True)
    record = {
        "observation_id": "HGO-1",
        "validation_id": "GVQ-1",
        "query_type": "MARKET_QUERY",
        "user_result_count": 500,
    }
    (ledger_dir / "google_supply_observations.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )

    exit_code = script.main(["--project-root", str(tmp_path)])
    assert exit_code == 0
    output_path = tmp_path / "output" / "_pipeline" / "logs" / "google_normalized_observations.json"
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["result_band"] == "LOW"


def test_main_handles_missing_ledger(tmp_path):
    exit_code = script.main(["--project-root", str(tmp_path)])
    assert exit_code == 0
