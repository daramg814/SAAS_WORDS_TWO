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


def test_foreign_keys_enforced(tmp_path):
    conn = db.connect(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO problem_evidence (evidence_id, problem_id, item_id, author, excerpt) "
            "VALUES ('E-0001', 'P-9999', 1, 'x', 'y')"
        )
        conn.commit()
    conn.close()
