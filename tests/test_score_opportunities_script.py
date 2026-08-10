import sys
from pathlib import Path

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
