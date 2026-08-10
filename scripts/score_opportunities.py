"""공급 희소성 등급과 희소성 우선 점수를 계산해 opportunities 테이블에 반영한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from saas_words_two import db, google_calibration, ids, opportunity_scoring, supply


def load_observations(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    return [
        json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def load_supply_verification(conn, problem_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT sv.* FROM supply_verification sv "
        "JOIN supply_candidates sc ON sc.product_id = sv.product_id "
        "WHERE sc.problem_id = ?",
        (problem_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def build_opportunity_row(conn, problem_row, demand_row, market_observations_by_problem: dict) -> dict:
    problem_id = problem_row["problem_id"]
    verifications = load_supply_verification(conn, problem_id)
    verified_products = [
        {"active": bool(v["active"]), "supply_type": v["supply_type"]} for v in verifications
    ]
    effective_supply_value = supply.effective_supply(verified_products)
    direct_competitor_count = sum(
        1 for v in verifications if v["active"] and v["supply_type"] == "direct"
    )

    scarcity_input = supply.SupplyScarcityInput(
        effective_supply_value=effective_supply_value,
        supply_gap_user_specific=bool(problem_row["supply_gap_user_specific"]),
        supply_gap_no_strong_incumbent=bool(problem_row["supply_gap_no_strong_incumbent"]),
        supply_gap_no_recent_entrants=bool(problem_row["supply_gap_no_recent_entrants"]),
        supply_gap_unresolved_complaints=bool(problem_row["supply_gap_unresolved_complaints"]),
    )
    scarcity_result = supply.score_supply_scarcity(scarcity_input)

    # design 4.7: human Google observations blend into the supply scarcity
    # score before it drives grade/priority/eligibility - applied inline here
    # (not only via the standalone apply_human_calibration.py script) so a
    # freshly recomputed score is never left uncalibrated until that script
    # happens to run again. supply_scarcity_score itself stays the raw,
    # unadjusted value for transparency; the adjusted value is what actually
    # governs downstream decisions when observations exist.
    adjustment = google_calibration.compute_supply_adjustment(
        market_observations_by_problem.get(problem_id, []), scarcity_result.total
    )
    operative_scarcity_score = adjustment["adjusted_supply_scarcity_score"]

    grade = supply.scarcity_grade(effective_supply_value, direct_competitor_count, operative_scarcity_score)

    priority = opportunity_scoring.priority_score(
        demand_row["total"], operative_scarcity_score, effective_supply_value
    )

    evidence_rows = conn.execute(
        "SELECT evidence_id, item_id FROM problem_evidence WHERE problem_id = ?", (problem_id,)
    ).fetchall()
    source_count = len({row["item_id"] for row in evidence_rows})
    confidence_level = opportunity_scoring.confidence(
        source_count,
        demand_row["independent_users"],
        supply_fully_verified=any(v["active"] and v["supply_type"] == "direct" for v in verifications),
        supply_partially_verified=any(v["active"] for v in verifications),
    )

    eligibility = opportunity_scoring.OpportunityEligibilityInput(
        demand_score=demand_row["total"],
        independent_users=demand_row["independent_users"],
        has_recent_evidence=True,  # already required to reach DEMAND_PASSED
        is_repeated_task=problem_row["frequency"] != "unknown",
        has_loss_time_or_risk_evidence=demand_row["risk_score"] > 0,
        has_clear_saas_feature=bool(problem_row["task"]),
        supply_scarcity_score=operative_scarcity_score,
        priority_score_value=priority,
        scarcity_grade=grade,
        confidence_level=confidence_level,
        has_manual_or_complaint_evidence=bool(problem_row["has_manual_or_complaint_evidence"]),
        purchase_intent_or_loss=(
            problem_row["purchase_intent"] != "none" or problem_row["risk_severity"] != "none"
        ),
    )
    decision = opportunity_scoring.provisional_decision(eligibility)

    return {
        "problem_id": problem_id,
        "demand_score": demand_row["total"],
        "effective_supply": effective_supply_value,
        "supply_scarcity_score": scarcity_result.total,
        "scarcity_grade": grade,
        "priority_score": priority,
        "confidence": confidence_level,
        "decision": decision,
        "evidence_ids": [row["evidence_id"] for row in evidence_rows],
        "product_ids": [v["product_id"] for v in verifications if v["active"]],
        "human_observation_count": adjustment["observation_count"],
        "human_adjusted_supply_scarcity_score": (
            adjustment["adjusted_supply_scarcity_score"] if adjustment["observation_count"] else None
        ),
        "human_calibration_status": adjustment["status"],
        "direct_competitor_count": direct_competitor_count,
    }


def persist_opportunity(conn, row: dict, updated_at: str) -> None:
    conn.execute(
        "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
        "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, "
        "human_observation_count, human_adjusted_supply_scarcity_score, human_calibration_status, "
        "direct_competitor_count, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(problem_id) DO UPDATE SET "
        "demand_score=excluded.demand_score, effective_supply=excluded.effective_supply, "
        "supply_scarcity_score=excluded.supply_scarcity_score, scarcity_grade=excluded.scarcity_grade, "
        "priority_score=excluded.priority_score, confidence=excluded.confidence, decision=excluded.decision, "
        "evidence_ids=excluded.evidence_ids, product_ids=excluded.product_ids, "
        "human_observation_count=excluded.human_observation_count, "
        "human_adjusted_supply_scarcity_score=excluded.human_adjusted_supply_scarcity_score, "
        "human_calibration_status=excluded.human_calibration_status, "
        "direct_competitor_count=excluded.direct_competitor_count, updated_at=excluded.updated_at",
        (
            row["problem_id"],
            row["demand_score"],
            row["effective_supply"],
            row["supply_scarcity_score"],
            row["scarcity_grade"],
            row["priority_score"],
            row["confidence"],
            row["decision"],
            json.dumps(row["evidence_ids"]),
            json.dumps(row["product_ids"]),
            row["human_observation_count"],
            row["human_adjusted_supply_scarcity_score"],
            row["human_calibration_status"],
            row["direct_competitor_count"],
            updated_at,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--observations-ledger",
        type=Path,
        default=None,
        help="defaults to memory/human_feedback/google_supply_observations.jsonl",
    )
    args = parser.parse_args(argv)

    project_root = args.project_root
    ledger_path = (
        args.observations_ledger or project_root / "memory" / "human_feedback" / "google_supply_observations.jsonl"
    )
    market_observations_by_problem = google_calibration.group_market_observations_by_problem(
        load_observations(ledger_path)
    )

    conn = db.connect(project_root)
    try:
        problems = conn.execute("SELECT * FROM problems WHERE status = 'DEMAND_PASSED'").fetchall()
        updated_at = ids.now_kst().isoformat()
        rows = []
        for problem_row in problems:
            demand_row = conn.execute(
                "SELECT * FROM demand_scores WHERE problem_id = ?", (problem_row["problem_id"],)
            ).fetchone()
            if demand_row is None:
                continue
            opportunity_row = build_opportunity_row(conn, problem_row, demand_row, market_observations_by_problem)
            persist_opportunity(conn, opportunity_row, updated_at)
            rows.append(opportunity_row)
        conn.commit()
    finally:
        conn.close()

    decisions: dict[str, int] = {}
    for row in rows:
        decisions[row["decision"]] = decisions.get(row["decision"], 0) + 1
    summary = " ".join(f"{key}={value}" for key, value in decisions.items())
    print(f"OPPORTUNITY SCORING: problems={len(rows)} {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
