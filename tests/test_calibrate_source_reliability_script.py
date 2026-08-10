import sys
from pathlib import Path

from saas_words_two import db, source_reliability

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import calibrate_source_reliability


def seed_demand_evidence(conn, *, source: str, problem_count: int, passed_count: int):
    for i in range(problem_count):
        problem_id = f"P-{source}-{i:04d}"
        conn.execute(
            "INSERT INTO problems (problem_id, status) VALUES (?, 'DEMAND_PASSED')", (problem_id,)
        )
        item_id = abs(hash((source, problem_id))) % 1_000_000_000 + 1
        conn.execute(
            "INSERT INTO hn_items (id, type, by, time, fetched_at, source) VALUES (?, 'story', 'alice', 100, 't0', ?)",
            (item_id, source),
        )
        conn.execute(
            "INSERT INTO problem_evidence (evidence_id, problem_id, item_id, author, excerpt) "
            "VALUES (?, ?, ?, 'alice', 'x')",
            (f"E-{source}-{i:04d}", problem_id, item_id),
        )
        if i < passed_count:
            conn.execute(
                "INSERT INTO demand_scores (problem_id, independent_users_score, persistence_score, "
                "frequency_score, risk_score, manual_evidence_score, purchase_intent_score, "
                "source_diversity_score, total, independent_users, passed) VALUES "
                "(?, 15, 15, 8, 8, 10, 15, 10, 81, 7, 1)",
                (problem_id,),
            )
    conn.commit()


def seed_supply_candidates(conn, *, source: str, total: int, active_count: int):
    for i in range(total):
        product_id = f"S-{source}-{i:04d}"
        conn.execute(
            "INSERT INTO problems (problem_id, status) VALUES (?, 'DEMAND_PASSED') "
            "ON CONFLICT(problem_id) DO NOTHING",
            (f"P-supply-{source}",),
        )
        conn.execute(
            "INSERT INTO supply_candidates (product_id, problem_id, name, dedupe_key, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (product_id, f"P-supply-{source}", product_id, product_id.lower(), source),
        )
        conn.execute(
            "INSERT INTO supply_verification (product_id, signals, signal_count, active, supply_type, weight) "
            "VALUES (?, '{}', 1, ?, 'direct', 1.0)",
            (product_id, int(i < active_count)),
        )
    conn.commit()


def test_load_demand_rows_dedupes_per_problem(tmp_path):
    conn = db.connect(tmp_path)
    seed_demand_evidence(conn, source="gh_archive", problem_count=5, passed_count=2)
    rows = calibrate_source_reliability.load_demand_rows(conn)
    conn.close()
    assert len(rows) == 5
    assert sum(1 for _, _, passed in rows if passed) == 2


def test_load_supply_rows_only_includes_verified_candidates(tmp_path):
    conn = db.connect(tmp_path)
    seed_supply_candidates(conn, source="npm_registry", total=5, active_count=3)
    conn.execute(
        "INSERT INTO problems (problem_id, status) VALUES ('P-unverified', 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, dedupe_key, source) "
        "VALUES ('S-unverified', 'P-unverified', 'x', 'x', 'npm_registry')"
    )
    conn.commit()
    rows = calibrate_source_reliability.load_supply_rows(conn)
    conn.close()
    assert len(rows) == 5  # the unverified one is excluded
    assert sum(1 for _, active in rows if active) == 3


def test_main_persists_calibrated_and_no_data_sources(tmp_path):
    conn = db.connect(tmp_path)
    seed_demand_evidence(conn, source="hacker_news", problem_count=5, passed_count=1)
    seed_demand_evidence(conn, source="rss_atom_feed", problem_count=2, passed_count=0)
    seed_supply_candidates(conn, source="hacker_news", total=5, active_count=4)
    conn.close()

    exit_code = calibrate_source_reliability.main(["--project-root", str(tmp_path)])
    assert exit_code == 0

    conn = db.connect(tmp_path)
    hn = dict(conn.execute("SELECT * FROM source_reliability WHERE source = 'hacker_news'").fetchone())
    rss = dict(conn.execute("SELECT * FROM source_reliability WHERE source = 'rss_atom_feed'").fetchone())
    conn.close()

    assert hn["demand_reliability_status"] == source_reliability.CALIBRATED
    assert hn["demand_problem_total"] == 5
    assert hn["demand_problem_passed"] == 1
    assert hn["supply_reliability_status"] == source_reliability.CALIBRATED
    assert hn["supply_candidate_active"] == 4

    assert rss["demand_reliability_status"] == source_reliability.NO_DATA
    assert rss["demand_reliability_score"] is None
    assert rss["supply_candidate_total"] == 0


def test_main_is_idempotent_and_upserts_on_rerun(tmp_path):
    conn = db.connect(tmp_path)
    seed_demand_evidence(conn, source="hacker_news", problem_count=5, passed_count=1)
    conn.close()

    calibrate_source_reliability.main(["--project-root", str(tmp_path)])

    conn = db.connect(tmp_path)
    seed_demand_evidence(conn, source="hacker_news", problem_count=0, passed_count=0)
    # add one more passed problem for the same source, then recalibrate
    conn.execute(
        "INSERT INTO problems (problem_id, status) VALUES ('P-hacker_news-0005', 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, fetched_at, source) VALUES (999, 'story', 'bob', 1, 't0', 'hacker_news')"
    )
    conn.execute(
        "INSERT INTO problem_evidence (evidence_id, problem_id, item_id, author, excerpt) "
        "VALUES ('E-hacker_news-0005', 'P-hacker_news-0005', 999, 'bob', 'x')"
    )
    conn.execute(
        "INSERT INTO demand_scores (problem_id, independent_users_score, persistence_score, "
        "frequency_score, risk_score, manual_evidence_score, purchase_intent_score, "
        "source_diversity_score, total, independent_users, passed) VALUES "
        "('P-hacker_news-0005', 15, 15, 8, 8, 10, 15, 10, 81, 7, 1)"
    )
    conn.commit()
    conn.close()

    calibrate_source_reliability.main(["--project-root", str(tmp_path)])

    conn = db.connect(tmp_path)
    rows = conn.execute("SELECT * FROM source_reliability WHERE source = 'hacker_news'").fetchall()
    hn = dict(rows[0])
    conn.close()

    assert len(rows) == 1  # upsert, not a duplicate row
    assert hn["demand_problem_total"] == 6
    assert hn["demand_problem_passed"] == 2
