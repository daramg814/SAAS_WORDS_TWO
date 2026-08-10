"""문제별 사람 관측치로 공급 부족 점수를 제한적으로 보정한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from saas_words_two import db, google_calibration


def load_observations(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    return [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def group_market_observations_by_problem(observations: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for observation in observations:
        if observation.get("query_type") != "MARKET_QUERY" or not observation.get("problem_id"):
            continue
        grouped.setdefault(observation["problem_id"], []).append(observation)
    return grouped


def compute_adjustment(observations_for_problem: list[dict], base_score: float) -> dict:
    count = len(observations_for_problem)
    if count == 0:
        return {
            "observation_count": 0,
            "human_weight": 0.0,
            "adjusted_supply_scarcity_score": base_score,
            "status": "NO_DATA",
        }

    count_only = all(o.get("top_results_relevant") is None for o in observations_for_problem)
    weight = google_calibration.human_weight(count, count_only=count_only)
    bands = [google_calibration.result_band(o["user_result_count"]) for o in observations_for_problem]
    human_scarcity = sum(google_calibration.human_google_scarcity_score(band) for band in bands) / len(bands)
    adjusted = google_calibration.adjusted_supply_scarcity(base_score, human_scarcity, weight)

    return {
        "observation_count": count,
        "human_weight": weight,
        "adjusted_supply_scarcity_score": adjusted,
        "status": google_calibration.calibration_status(count),
    }


def apply_calibration(conn, observations: list[dict]) -> int:
    grouped = group_market_observations_by_problem(observations)
    updated = 0
    for row in conn.execute("SELECT problem_id, supply_scarcity_score FROM opportunities").fetchall():
        problem_observations = grouped.get(row["problem_id"], [])
        adjustment = compute_adjustment(problem_observations, float(row["supply_scarcity_score"]))
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
    args = parser.parse_args(argv)

    project_root = args.project_root
    observations = load_observations(
        project_root / "memory" / "human_feedback" / "google_supply_observations.jsonl"
    )
    conn = db.connect(project_root)
    try:
        updated = apply_calibration(conn, observations)
    finally:
        conn.close()

    print(f"HUMAN CALIBRATION APPLIED: opportunities_updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
