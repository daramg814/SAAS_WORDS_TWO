import json
import sys
from pathlib import Path

import pytest

from saas_words_two import db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import score_opportunities


def seed_full_opportunity(conn):
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, frequency, risk_severity, "
        "purchase_intent, has_manual_or_complaint_evidence, supply_gap_user_specific, "
        "supply_gap_no_strong_incumbent, supply_gap_no_recent_entrants, "
        "supply_gap_unresolved_complaints, status) VALUES "
        "('P-0001', 'small firms', 'track renewals', 'weekly', 'moderate', 'strong', 1, "
        "1, 1, 1, 1, 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO demand_scores (problem_id, independent_users_score, persistence_score, "
        "frequency_score, risk_score, manual_evidence_score, purchase_intent_score, "
        "source_diversity_score, total, independent_users, passed) VALUES "
        "('P-0001', 15, 15, 8, 8, 10, 15, 10, 81, 7, 1)"
    )
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, fetched_at) VALUES (1, 'story', 'alice', 100, 't0')"
    )
    conn.execute(
        "INSERT INTO problem_evidence (evidence_id, problem_id, item_id, author, excerpt) "
        "VALUES ('E-0001', 'P-0001', 1, 'alice', 'x')"
    )
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, dedupe_key, source) "
        "VALUES ('S-0001', 'P-0001', 'VendorGuard', 'vendorguard', 'hn_show')"
    )
    conn.execute(
        "INSERT INTO supply_verification (product_id, signals, signal_count, active, supply_type, weight) "
        "VALUES ('S-0001', '{}', 1, 0, 'direct', 0.0)"
    )
    conn.commit()


def test_main_computes_and_persists_opportunity(tmp_path):
    conn = db.connect(tmp_path)
    seed_full_opportunity(conn)
    conn.close()

    exit_code = score_opportunities.main(["--project-root", str(tmp_path)])
    assert exit_code == 0

    conn = db.connect(tmp_path)
    row = conn.execute("SELECT * FROM opportunities WHERE problem_id = 'P-0001'").fetchone()
    assert row is not None
    assert row["scarcity_grade"] in ("S", "A", "B", "C")
    assert row["decision"] in ("GENERATE_TITLES", "RESEARCH_MORE", "REJECT")
    conn.close()


def test_main_is_idempotent(tmp_path):
    conn = db.connect(tmp_path)
    seed_full_opportunity(conn)
    conn.close()
    score_opportunities.main(["--project-root", str(tmp_path)])
    score_opportunities.main(["--project-root", str(tmp_path)])
    conn = db.connect(tmp_path)
    rows = conn.execute("SELECT COUNT(*) c FROM opportunities").fetchone()
    assert rows["c"] == 1
    conn.close()


def seed_borderline_opportunity(conn, problem_id="P-0003"):
    """Raw supply_scarcity_score = 60 (effective_supply_score(3)=30 +
    no_strong_incumbent=15 + unresolved_complaints=15), effective_supply=3 ->
    grade C (60 < B's 65 threshold) without calibration."""
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, frequency, risk_severity, "
        "purchase_intent, has_manual_or_complaint_evidence, supply_gap_user_specific, "
        "supply_gap_no_strong_incumbent, supply_gap_no_recent_entrants, "
        "supply_gap_unresolved_complaints, status) VALUES "
        f"('{problem_id}', 'small firms', 'track renewals', 'weekly', 'moderate', 'strong', 1, "
        "0, 1, 0, 1, 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO demand_scores (problem_id, independent_users_score, persistence_score, "
        "frequency_score, risk_score, manual_evidence_score, purchase_intent_score, "
        "source_diversity_score, total, independent_users, passed) VALUES "
        f"('{problem_id}', 15, 15, 8, 8, 10, 15, 10, 81, 7, 1)"
    )
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, fetched_at) VALUES (1, 'story', 'alice', 100, 't0')"
    )
    conn.execute(
        "INSERT INTO problem_evidence (evidence_id, problem_id, item_id, author, excerpt) "
        f"VALUES ('E-0001', '{problem_id}', 1, 'alice', 'x')"
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO supply_candidates (product_id, problem_id, name, dedupe_key, source) "
            f"VALUES ('S-000{i}', '{problem_id}', 'Vendor{i}', 'vendor{i}', 'hn_show')"
        )
        conn.execute(
            "INSERT INTO supply_verification (product_id, signals, signal_count, active, supply_type, weight) "
            f"VALUES ('S-000{i}', '{{}}', 3, 1, 'direct', 1.0)"
        )
    conn.commit()


def test_main_applies_human_calibration_and_changes_grade(tmp_path):
    conn = db.connect(tmp_path)
    seed_borderline_opportunity(conn)
    conn.close()

    exit_code = score_opportunities.main(["--project-root", str(tmp_path)])
    assert exit_code == 0
    conn = db.connect(tmp_path)
    row = conn.execute("SELECT * FROM opportunities WHERE problem_id = 'P-0003'").fetchone()
    assert row["supply_scarcity_score"] == 60
    assert row["scarcity_grade"] == "C"
    assert row["human_calibration_status"] == "NO_DATA"
    assert row["human_adjusted_supply_scarcity_score"] is None
    conn.close()

    ledger_path = tmp_path / "memory" / "human_feedback" / "google_supply_observations.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    observations = [
        {
            "problem_id": "P-0003",
            "query_type": "MARKET_QUERY",
            "user_result_count": 0,
            "top_results_relevant": 0,
        }
        for _ in range(20)
    ]
    ledger_path.write_text("\n".join(json.dumps(o) for o in observations) + "\n", encoding="utf-8")

    exit_code = score_opportunities.main(["--project-root", str(tmp_path)])
    assert exit_code == 0
    conn = db.connect(tmp_path)
    row = conn.execute("SELECT * FROM opportunities WHERE problem_id = 'P-0003'").fetchone()
    # raw score stays 60 (base signals unchanged); adjusted = 60*0.75 + 95*0.25 = 68.75 -> grade B
    assert row["supply_scarcity_score"] == 60
    assert row["human_observation_count"] == 20
    assert row["human_calibration_status"] == "CALIBRATED"
    assert row["human_adjusted_supply_scarcity_score"] == pytest.approx(68.75)
    assert row["scarcity_grade"] == "B"
    conn.close()


def test_main_skips_problems_without_demand_scores(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("INSERT INTO problems (problem_id, status) VALUES ('P-0002', 'DEMAND_PASSED')")
    conn.commit()
    conn.close()
    exit_code = score_opportunities.main(["--project-root", str(tmp_path)])
    assert exit_code == 0
    conn = db.connect(tmp_path)
    rows = conn.execute("SELECT COUNT(*) c FROM opportunities").fetchone()
    assert rows["c"] == 0
    conn.close()
