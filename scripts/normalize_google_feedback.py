"""사람 Google 관측치의 footprint와 결과 구간을 정규화한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from saas_words_two import google_calibration
from saas_words_two.contracts import atomic_write_text


def load_observations(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    return [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def normalize_observation(observation: dict) -> dict:
    return {
        "observation_id": observation["observation_id"],
        "validation_id": observation["validation_id"],
        "query_type": observation.get("query_type"),
        "google_footprint": round(google_calibration.google_footprint(observation["user_result_count"]), 4),
        "result_band": google_calibration.result_band(observation["user_result_count"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    project_root = args.project_root
    observations = load_observations(
        project_root / "memory" / "human_feedback" / "google_supply_observations.jsonl"
    )
    normalized = [normalize_observation(observation) for observation in observations]

    atomic_write_text(
        project_root / "output" / "logs" / "google_normalized_observations.json",
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
    )
    print(f"NORMALIZED OBSERVATIONS: {len(normalized)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
