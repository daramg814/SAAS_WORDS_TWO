import sys
from pathlib import Path

from saas_words_two import db, ids

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_google_validation_queue as script


def test_predicted_band_from_scarcity_score_extremes():
    assert script.predicted_band_from_scarcity_score(95) == "VERY_LOW"
    assert script.predicted_band_from_scarcity_score(5) == "VERY_HIGH"


def test_market_query_priority_reasons_flags_s_grade_low_confidence():
    opportunity = {
        "problem_id": "P-0001",
        "scarcity_grade": "S",
        "confidence": "B",
        "supply_scarcity_score": 85,
    }
    reasons = script.market_query_priority_reasons(opportunity, previously_observed_problem_ids=set())
    assert any("신뢰도" in r for r in reasons)
    assert any("사람 검증" in r for r in reasons)


def test_market_query_priority_reasons_empty_for_well_covered_high_confidence():
    opportunity = {
        "problem_id": "P-0001",
        "scarcity_grade": "B",
        "confidence": "A",
        "supply_scarcity_score": 50,  # not within +-5 of the 65/70/80 boundary set
    }
    reasons = script.market_query_priority_reasons(
        opportunity, previously_observed_problem_ids={"P-0001"}
    )
    assert reasons == []


def _seed_opportunity(conn, problem_id="P-0001", grade="S", confidence="B"):
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, status) VALUES (?, 'small firms', 'track renewals', 'DEMAND_PASSED')",
        (problem_id,),
    )
    conn.execute(
        "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
        "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, updated_at) "
        "VALUES (?, 80, 1.0, 85, ?, 90, ?, 'GENERATE_TITLES', '[]', '[]', 't0')",
        (problem_id, grade, confidence),
    )
    conn.commit()


def test_build_rows_produces_market_query_row_for_flagged_opportunity(tmp_path):
    conn = db.connect(tmp_path)
    _seed_opportunity(conn)
    rows = script.build_rows(conn, now=ids.now_kst())
    conn.commit()
    market_rows = [r for r in rows if r["query_type"] == "MARKET_QUERY"]
    assert len(market_rows) == 1
    assert market_rows[0]["problem_id"] == "P-0001"
    assert market_rows[0]["validation_id"].startswith("GVQ-")
    conn.close()


def test_write_queue_csv_round_trips(tmp_path):
    conn = db.connect(tmp_path)
    _seed_opportunity(conn)
    rows = script.build_rows(conn, now=ids.now_kst())
    conn.commit()
    conn.close()

    csv_path = tmp_path / "queue.csv"
    script.write_queue_csv(csv_path, rows)
    import csv as csv_module

    with csv_path.open(encoding="utf-8", newline="") as handle:
        read_rows = list(csv_module.DictReader(handle))
    assert len(read_rows) == len(rows)
    assert list(read_rows[0].keys()) == list(script.CSV_FIELDS)


def test_main_writes_queue_file(tmp_path):
    conn = db.connect(tmp_path)
    _seed_opportunity(conn)
    conn.close()

    exit_code = script.main(["--project-root", str(tmp_path)])
    assert exit_code == 0
    queue_path = tmp_path / "output" / "deliverables" / "review" / "google_validation_queue.csv"
    assert queue_path.exists()
