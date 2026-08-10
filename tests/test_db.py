import sqlite3

import pytest

from saas_words_two import db


def test_connect_creates_db_file_and_schema(tmp_path):
    conn = db.connect(tmp_path)
    assert (tmp_path / "data" / "local.db").exists()
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "id_counters",
        "hn_items",
        "candidate_sentences",
        "problems",
        "problem_evidence",
        "demand_scores",
        "supply_candidates",
        "supply_verification",
        "opportunities",
        "titles",
    }
    assert expected.issubset(tables)
    conn.close()


def test_connect_is_idempotent(tmp_path):
    conn1 = db.connect(tmp_path)
    conn1.execute(
        "INSERT INTO hn_items (id, type, fetched_at) VALUES (1, 'story', '2026-08-10T00:00:00+09:00')"
    )
    conn1.commit()
    conn1.close()

    conn2 = db.connect(tmp_path)
    row = conn2.execute("SELECT id FROM hn_items WHERE id = 1").fetchone()
    assert row is not None
    conn2.close()


def test_connect_backfills_columns_added_after_a_table_already_existed(tmp_path):
    db_path = tmp_path / "data" / "local.db"
    db_path.parent.mkdir(parents=True)
    legacy_conn = sqlite3.connect(db_path)
    # Simulate a local.db built before a column migration existed.
    legacy_conn.execute(
        "CREATE TABLE opportunities (problem_id TEXT PRIMARY KEY, demand_score INTEGER NOT NULL, "
        "effective_supply REAL NOT NULL, supply_scarcity_score INTEGER NOT NULL, scarcity_grade TEXT NOT NULL, "
        "priority_score REAL NOT NULL, confidence TEXT NOT NULL, decision TEXT NOT NULL, "
        "evidence_ids TEXT NOT NULL, product_ids TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    legacy_conn.commit()
    legacy_conn.close()

    conn = db.connect(tmp_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(opportunities)").fetchall()}
    assert "human_observation_count" in columns
    assert "human_adjusted_supply_scarcity_score" in columns
    assert "human_calibration_status" in columns
    conn.close()


def test_connect_migration_is_idempotent_on_rerun(tmp_path):
    db.connect(tmp_path).close()
    conn = db.connect(tmp_path)  # should not raise "duplicate column" on second connect
    columns = {row[1] for row in conn.execute("PRAGMA table_info(opportunities)").fetchall()}
    assert "human_observation_count" in columns
    conn.close()


def test_foreign_keys_enforced(tmp_path):
    conn = db.connect(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO problem_evidence (evidence_id, problem_id, item_id, author, excerpt) "
            "VALUES ('E-0001', 'P-9999', 1, 'x', 'y')"
        )
        conn.commit()
    conn.close()
