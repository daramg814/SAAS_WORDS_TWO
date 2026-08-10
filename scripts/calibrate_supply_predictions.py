"""사람 관측과 AI 예측을 비교해 오차 유형을 판정하고 누적 지표를 갱신한다."""

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


def _brand_conflict_flagged(observation: dict) -> bool:
    notes = (observation.get("user_notes") or "").lower()
    return any(marker in notes for marker in ("brand", "conflict", "동일 제품", "동일 브랜드"))


def classify_observation(observation: dict) -> str:
    actual_band = google_calibration.result_band(observation["user_result_count"])
    predicted_band = observation.get("predicted_result_band_at_time") or actual_band
    if observation.get("query_type") == "TITLE_QUERY":
        return google_calibration.classify_title_query_error(
            predicted_band, actual_band, brand_conflict_flagged=_brand_conflict_flagged(observation)
        )
    return google_calibration.classify_market_query_error(
        predicted_band, actual_band, top_results_relevant=observation.get("top_results_relevant")
    )


def _rate(errors: list[str], label: str) -> float | None:
    return round(errors.count(label) / len(errors), 4) if errors else None


def build_metrics(observations: list[dict]) -> dict:
    market = [o for o in observations if o.get("query_type") == "MARKET_QUERY"]
    title = [o for o in observations if o.get("query_type") == "TITLE_QUERY"]
    market_errors = [classify_observation(o) for o in market]
    title_errors = [classify_observation(o) for o in title]

    return {
        "total_observations": len(observations),
        "market_query_observations": len(market),
        "title_query_observations": len(title),
        "supply_underestimated_rate": _rate(market_errors, "SUPPLY_UNDERESTIMATED"),
        "supply_overestimated_rate": _rate(market_errors, "SUPPLY_OVERESTIMATED"),
        "title_collision_underestimated_rate": _rate(title_errors, "TITLE_COLLISION_UNDERESTIMATED"),
        "query_noise_rate": _rate(market_errors, "QUERY_NOISE_HIGH"),
        "status": google_calibration.calibration_status(len(market)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--ledger", type=Path, default=None, help="defaults to memory/human_feedback/google_supply_observations.jsonl"
    )
    parser.add_argument(
        "--metrics", type=Path, default=None, help="defaults to memory/human_feedback/google_calibration_metrics.json"
    )
    args = parser.parse_args(argv)

    project_root = args.project_root
    ledger_path = args.ledger or project_root / "memory" / "human_feedback" / "google_supply_observations.jsonl"
    metrics_path = args.metrics or project_root / "memory" / "human_feedback" / "google_calibration_metrics.json"
    observations = load_observations(ledger_path)
    metrics = build_metrics(observations)

    atomic_write_text(metrics_path, json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    print(
        f"CALIBRATION METRICS: total={metrics['total_observations']} "
        f"market={metrics['market_query_observations']} title={metrics['title_query_observations']} "
        f"status={metrics['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
