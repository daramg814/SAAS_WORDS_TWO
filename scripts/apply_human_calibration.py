"""문제별 사람 관측치로 공급 부족 점수를 제한적으로 보정한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from saas_words_two import db, google_calibration

# Backward-compatible aliases: the real logic now lives in google_calibration
# (shared with score_opportunities.py, which applies the same adjustment
# inline on every scoring pass rather than only when this script is run).
group_market_observations_by_problem = google_calibration.group_market_observations_by_problem
compute_adjustment = google_calibration.compute_supply_adjustment


def load_observations(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    return [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def apply_calibration(conn, observations: list[dict]) -> int:
    grouped = google_calibration.group_market_observations_by_problem(observations)
    updated = 0
    for row in conn.execute("SELECT problem_id, supply_scarcity_score FROM opportunities").fetchall():
        problem_observations = grouped.get(row["problem_id"], [])
        adjustment = google_calibration.compute_supply_adjustment(
            problem_observations, float(row["supply_scarcity_score"])
        )
        conn.execute(
            "UPDATE opportunities SET human_observation_count = ?, "
            "human_adjusted_supply_scarcity_score = ?, human_calibration_status = ? "
            "WHERE problem_id = ?",
            (
                adjustment["observation_count"],
                adjustment["adjusted_supply_scarcity_score"] if adjustment["observation_count"] else None,
                adjustment["status"],
                row["problem_id"],
            ),
        )
        if adjustment["observation_count"]:
            updated += 1
    conn.commit()
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--ledger", type=Path, default=None, help="defaults to memory/human_feedback/google_supply_observations.jsonl"
    )
    args = parser.parse_args(argv)

    project_root = args.project_root
    ledger_path = args.ledger or project_root / "memory" / "human_feedback" / "google_supply_observations.jsonl"
    observations = load_observations(ledger_path)
    conn = db.connect(project_root)
    try:
        updated = apply_calibration(conn, observations)
    finally:
        conn.close()

    print(f"HUMAN CALIBRATION APPLIED: opportunities_updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
