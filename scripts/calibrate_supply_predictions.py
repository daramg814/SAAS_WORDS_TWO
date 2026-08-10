"""사람 관측과 AI 예측을 비교해 오차 유형을 판정하고 누적 지표를 갱신한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from saas_words_two import db, google_calibration, supply
from saas_words_two.contracts import atomic_write_text


def load_observations(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    return [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def classify_observation(observation: dict) -> str:
    actual_band = google_calibration.result_band(observation["user_result_count"])
    predicted_band = observation.get("predicted_result_band_at_time") or actual_band
    if observation.get("query_type") == "TITLE_QUERY":
        return google_calibration.classify_title_query_error(
            predicted_band,
            actual_band,
            brand_conflict_flagged=google_calibration.title_brand_conflict_flagged(observation.get("user_notes")),
        )
    return google_calibration.classify_market_query_error(
        predicted_band, actual_band, top_results_relevant=observation.get("top_results_relevant")
    )


def _rate(errors: list[str], label: str) -> float | None:
    return round(errors.count(label) / len(errors), 4) if errors else None


def per_industry_counts(observations: list[dict], conn) -> dict[str, int]:
    """4.9 '산업별 검증 수'. No dedicated industry taxonomy exists anywhere in
    the schema (design only ever refers to industry in prose) - problems.
    target_user is the closest existing judgment-derived categorical label,
    so it is used as the industry bucket here rather than inventing a new
    code-only classifier (industry classification is semantic judgment, not
    code's job per docs/architecture/06)."""
    problem_ids = {o["problem_id"] for o in observations if o.get("problem_id")}
    if not problem_ids:
        return {}
    placeholders = ",".join("?" for _ in problem_ids)
    target_user_by_id = {
        row["problem_id"]: row["target_user"]
        for row in conn.execute(
            f"SELECT problem_id, target_user FROM problems WHERE problem_id IN ({placeholders})",
            list(problem_ids),
        ).fetchall()
    }
    counts: dict[str, int] = {}
    for observation in observations:
        industry = target_user_by_id.get(observation.get("problem_id"))
        if industry:
            counts[industry] = counts.get(industry, 0) + 1
    return counts


def noise_rate_by_query(market_observations: list[dict], market_errors: list[str]) -> dict[str, dict]:
    """4.9 '검색식별 노이즈율' - broken down per google_query, not just one
    aggregate rate."""
    by_query: dict[str, list[str]] = {}
    for observation, error in zip(market_observations, market_errors):
        query = observation.get("google_query") or "(unknown)"
        by_query.setdefault(query, []).append(error)
    return {
        query: {"count": len(errors), "noise_rate": _rate(errors, "QUERY_NOISE_HIGH")}
        for query, errors in by_query.items()
    }


def queries_eligible_for_noise_rule_promotion(noise_by_query: dict[str, dict]) -> list[str]:
    """Operationalizes minimum_repetitions_for_rule_promotion for the
    '검색 노이즈가 낮은/높은 검색식' candidate-rule category (4.9): flags query
    strings seen often enough with a majority-noise outcome for a
    human/session to consider promoting into google_query_playbook.md. Does
    not promote anything automatically - counting repetitions is code's job,
    judging whether it's really the same reusable rule is not."""
    return sorted(
        query
        for query, stats in noise_by_query.items()
        if stats["count"] >= google_calibration.MINIMUM_REPETITIONS_FOR_RULE_PROMOTION
        and stats["noise_rate"] is not None
        and stats["noise_rate"] >= 0.5
    )


def supply_grade_change_count(conn) -> int:
    """4.9 '사람 검증 전후 공급 등급 변경 수'. opportunities.scarcity_grade is
    always computed from the calibrated score once observations exist
    (score_opportunities.py); recomputing the grade the raw, uncalibrated
    score would have produced and comparing tells us how often calibration
    actually flipped the grade, not just nudged the score."""
    count = 0
    rows = conn.execute(
        "SELECT effective_supply, direct_competitor_count, supply_scarcity_score, scarcity_grade "
        "FROM opportunities WHERE human_calibration_status NOT IN ('NO_DATA')"
    ).fetchall()
    for row in rows:
        raw_grade = supply.scarcity_grade(
            row["effective_supply"], row["direct_competitor_count"], row["supply_scarcity_score"]
        )
        if raw_grade != row["scarcity_grade"]:
            count += 1
    return count


def titles_rejected_by_human_validation_count(conn) -> int:
    """4.9 '사람 검증으로 탈락한 제목 수' - titles pipeline.py's
    _stage_validate_outputs excludes for an explicit TITLE_BRAND_CONFLICT
    (design 4.8), counted cumulatively across all runs."""
    return conn.execute(
        "SELECT COUNT(*) c FROM titles WHERE google_title_collision_class = 'BRAND_CONFLICT'"
    ).fetchone()["c"]


def build_metrics(observations: list[dict], conn) -> dict:
    market = [o for o in observations if o.get("query_type") == "MARKET_QUERY"]
    title = [o for o in observations if o.get("query_type") == "TITLE_QUERY"]
    market_errors = [classify_observation(o) for o in market]
    title_errors = [classify_observation(o) for o in title]
    noise_by_query = noise_rate_by_query(market, market_errors)

    return {
        "total_observations": len(observations),
        "market_query_observations": len(market),
        "title_query_observations": len(title),
        "observations_by_industry": per_industry_counts(observations, conn),
        "supply_underestimated_rate": _rate(market_errors, "SUPPLY_UNDERESTIMATED"),
        "supply_overestimated_rate": _rate(market_errors, "SUPPLY_OVERESTIMATED"),
        "title_collision_underestimated_rate": _rate(title_errors, "TITLE_COLLISION_UNDERESTIMATED"),
        "query_noise_rate": _rate(market_errors, "QUERY_NOISE_HIGH"),
        "query_noise_rate_by_query": noise_by_query,
        "queries_eligible_for_noise_rule_promotion": queries_eligible_for_noise_rule_promotion(noise_by_query),
        "supply_grade_changes_from_calibration": supply_grade_change_count(conn),
        "titles_rejected_by_human_validation": titles_rejected_by_human_validation_count(conn),
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

    conn = db.connect(project_root)
    try:
        metrics = build_metrics(observations, conn)
    finally:
        conn.close()

    atomic_write_text(metrics_path, json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    print(
        f"CALIBRATION METRICS: total={metrics['total_observations']} "
        f"market={metrics['market_query_observations']} title={metrics['title_query_observations']} "
        f"status={metrics['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
