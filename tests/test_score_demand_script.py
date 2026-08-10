import sys
import time
from pathlib import Path

from saas_words_two import db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import score_demand


def seed_passing_problem(conn, now_epoch: int):
    authors = ["alice", "bob", "carl", "dave", "eve"]
    for index, author in enumerate(authors, start=1):
        conn.execute(
            "INSERT INTO hn_items (id, type, by, time, parent, fetched_at) VALUES (?, ?, ?, ?, ?, 't0')",
            (index, "story" if index == 1 else "comment", author, now_epoch - index * 20 * 24 * 3600, None if index == 1 else 1),
        )
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, frequency, risk_severity, "
        "purchase_intent, has_manual_or_complaint_evidence, status) VALUES "
        "('P-0001', 'small firms', 'track renewals', 'weekly', 'moderate', 'strong', 1, 'CLUSTERED')"
    )
    for index in range(1, 6):
        conn.execute(
            "INSERT INTO problem_evidence (evidence_id, problem_id, item_id, author, excerpt) "
            "VALUES (?, 'P-0001', ?, ?, 'y')",
            (f"E-{index:04d}", index, authors[index - 1]),
        )
    conn.commit()


def test_main_scores_and_marks_problem_passed(tmp_path):
    conn = db.connect(tmp_path)
    seed_passing_problem(conn, int(time.time()))
    conn.close()

    exit_code = score_demand.main(["--project-root", str(tmp_path)])
    assert exit_code == 0

    conn = db.connect(tmp_path)
    problem = conn.execute("SELECT status FROM problems WHERE problem_id = 'P-0001'").fetchone()
    assert problem["status"] == "DEMAND_PASSED"
    score_row = conn.execute("SELECT * FROM demand_scores WHERE problem_id = 'P-0001'").fetchone()
    assert score_row["passed"] == 1
    assert score_row["independent_users"] == 5
    conn.close()


def test_main_is_idempotent_on_rerun(tmp_path):
    conn = db.connect(tmp_path)
    seed_passing_problem(conn, int(time.time()))
    conn.close()

    score_demand.main(["--project-root", str(tmp_path)])
    score_demand.main(["--project-root", str(tmp_path)])

    conn = db.connect(tmp_path)
    rows = conn.execute("SELECT COUNT(*) c FROM demand_scores").fetchone()
    assert rows["c"] == 1
    conn.close()
