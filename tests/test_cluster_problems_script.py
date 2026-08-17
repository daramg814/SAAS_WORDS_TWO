import json
import sys
from pathlib import Path

from saas_words_two import db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cluster_problems


def seed_db(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, fetched_at) VALUES (1, 'story', 'alice', 100, 't0')"
    )
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, fetched_at) VALUES (2, 'comment', 'bob', 101, 't0')"
    )
    conn.execute(
        "INSERT INTO candidate_sentences (item_id, sentence, matched_patterns, created_at) VALUES "
        "(1, 'We still use spreadsheets to track vendor insurance', 'still use spreadsheets', 't0')"
    )
    conn.execute(
        "INSERT INTO candidate_sentences (item_id, sentence, matched_patterns, created_at) VALUES "
        "(2, 'I still use a spreadsheet to track vendor insurance', 'still use spreadsheets', 't0')"
    )
    conn.commit()
    return conn


def test_load_candidates_joins_author_from_hn_items(tmp_path):
    conn = seed_db(tmp_path)
    candidates = cluster_problems.load_candidates(conn)
    assert len(candidates) == 2
    assert {c.author for c in candidates} == {"alice", "bob"}
    conn.close()


def test_main_writes_intermediate_json(tmp_path):
    conn = seed_db(tmp_path)
    conn.close()
    output_path = tmp_path / "output" / "_pipeline" / "intermediate" / "problem_clusters.json"
    exit_code = cluster_problems.main(["--project-root", str(tmp_path), "--output", str(output_path)])
    assert exit_code == 0
    assert output_path.exists()
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(data["clusters"]) == 1
    assert data["clusters"][0]["independent_user_count"] == 2
