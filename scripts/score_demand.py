"""독립 사용자·기간·빈도·손실·수작업·구매 의도·출처 수를 점수화한다."""

from __future__ import annotations

import argparse
from pathlib import Path

from saas_words_two import db, demand_scoring, ids


def load_evidence(conn, problem_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT hi.id AS id, hi.type AS type, hi.parent AS parent, hi.time AS time, hi.by AS author "
        "FROM problem_evidence pe JOIN hn_items hi ON hi.id = pe.item_id "
        "WHERE pe.problem_id = ?",
        (problem_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def build_input(problem_row, evidence: list[dict], *, now_epoch: int) -> demand_scoring.DemandScoreInput:
    timestamps = [row["time"] for row in evidence]
    independent_users = len({row["author"] for row in evidence if row["author"]}) or len(evidence)
    return demand_scoring.DemandScoreInput(
        independent_users=independent_users,
        distinct_periods=demand_scoring.distinct_period_count(timestamps),
        frequency=problem_row["frequency"],
        risk_severity=problem_row["risk_severity"],
        has_manual_or_complaint_evidence=bool(problem_row["has_manual_or_complaint_evidence"]),
        purchase_intent=problem_row["purchase_intent"],
        distinct_threads=len(demand_scoring.distinct_thread_ids(evidence)),
        has_recent_evidence=demand_scoring.has_recent_evidence(timestamps, now_epoch=now_epoch),
    )


def persist_result(conn, problem_id: str, demand_input, result: demand_scoring.DemandScoreResult) -> None:
    conn.execute(
        "INSERT INTO demand_scores (problem_id, independent_users_score, persistence_score, "
        "frequency_score, risk_score, manual_evidence_score, purchase_intent_score, "
        "source_diversity_score, total, independent_users, passed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(problem_id) DO UPDATE SET "
        "independent_users_score=excluded.independent_users_score, "
        "persistence_score=excluded.persistence_score, "
        "frequency_score=excluded.frequency_score, "
        "risk_score=excluded.risk_score, "
        "manual_evidence_score=excluded.manual_evidence_score, "
        "purchase_intent_score=excluded.purchase_intent_score, "
        "source_diversity_score=excluded.source_diversity_score, "
        "total=excluded.total, independent_users=excluded.independent_users, "
        "passed=excluded.passed",
        (
            problem_id,
            result.independent_users_score,
            result.persistence_score,
            result.frequency_score,
            result.risk_score,
            result.manual_evidence_score,
            result.purchase_intent_score,
            result.source_diversity_score,
            result.total,
            demand_input.independent_users,
            int(result.passed),
        ),
    )
    status = "DEMAND_PASSED" if result.passed else "DEMAND_REJECTED"
    conn.execute("UPDATE problems SET status = ? WHERE problem_id = ?", (status, problem_id))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    project_root = args.project_root
    conn = db.connect(project_root)
    try:
        problems = conn.execute("SELECT * FROM problems").fetchall()
        now_epoch = int(ids.now_kst().timestamp())
        passed_count = 0
        for problem_row in problems:
            evidence = load_evidence(conn, problem_row["problem_id"])
            demand_input = build_input(problem_row, evidence, now_epoch=now_epoch)
            result = demand_scoring.score_demand(demand_input)
            persist_result(conn, problem_row["problem_id"], demand_input, result)
            if result.passed:
                passed_count += 1
        conn.commit()
    finally:
        conn.close()

    print(f"DEMAND SCORING: problems={len(problems)} passed={passed_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
