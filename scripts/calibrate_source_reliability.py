"""데이터원별 신뢰도 보정: problem_evidence/demand_scores와
supply_candidates/supply_verification의 누적 결과만으로 각 데이터원의
신뢰도를 집계해 source_reliability 테이블에 원자적으로 갱신한다.

design roadmap 3차 개선 "데이터원별 신뢰도 보정". 사람 관측 없이 파이프라인
자체 데이터로만 계산하는 순수 집계이며, 자세한 설계 근거는
src/saas_words_two/source_reliability.py의 모듈 docstring을 따른다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from saas_words_two import db, ids, source_reliability


def load_demand_rows(conn) -> list[tuple[str, str, bool]]:
    rows = conn.execute(
        "SELECT DISTINCT hi.source AS source, pe.problem_id AS problem_id, "
        "COALESCE(ds.passed, 0) AS passed "
        "FROM problem_evidence pe "
        "JOIN hn_items hi ON hi.id = pe.item_id "
        "LEFT JOIN demand_scores ds ON ds.problem_id = pe.problem_id"
    ).fetchall()
    return [(row["source"], row["problem_id"], bool(row["passed"])) for row in rows]


def load_supply_rows(conn) -> list[tuple[str, bool]]:
    rows = conn.execute(
        "SELECT sc.source AS source, sv.active AS active "
        "FROM supply_candidates sc "
        "JOIN supply_verification sv ON sv.product_id = sc.product_id"
    ).fetchall()
    return [(row["source"], bool(row["active"])) for row in rows]


def persist(
    conn,
    demand: dict[str, source_reliability.SideReliability],
    supply: dict[str, source_reliability.SideReliability],
    *,
    updated_at: str,
) -> list[dict]:
    rows = []
    for source in sorted(set(demand) | set(supply)):
        d = demand.get(source)
        s = supply.get(source)
        row = {
            "source": source,
            "demand_problem_total": d.total if d else 0,
            "demand_problem_passed": d.positive if d else 0,
            "demand_reliability_score": d.score if d else None,
            "demand_reliability_status": d.status if d else source_reliability.NO_DATA,
            "supply_candidate_total": s.total if s else 0,
            "supply_candidate_active": s.positive if s else 0,
            "supply_reliability_score": s.score if s else None,
            "supply_reliability_status": s.status if s else source_reliability.NO_DATA,
            "updated_at": updated_at,
        }
        rows.append(row)
        conn.execute(
            "INSERT INTO source_reliability (source, demand_problem_total, demand_problem_passed, "
            "demand_reliability_score, demand_reliability_status, supply_candidate_total, "
            "supply_candidate_active, supply_reliability_score, supply_reliability_status, updated_at) "
            "VALUES (:source, :demand_problem_total, :demand_problem_passed, :demand_reliability_score, "
            ":demand_reliability_status, :supply_candidate_total, :supply_candidate_active, "
            ":supply_reliability_score, :supply_reliability_status, :updated_at) "
            "ON CONFLICT(source) DO UPDATE SET "
            "demand_problem_total=excluded.demand_problem_total, "
            "demand_problem_passed=excluded.demand_problem_passed, "
            "demand_reliability_score=excluded.demand_reliability_score, "
            "demand_reliability_status=excluded.demand_reliability_status, "
            "supply_candidate_total=excluded.supply_candidate_total, "
            "supply_candidate_active=excluded.supply_candidate_active, "
            "supply_reliability_score=excluded.supply_reliability_score, "
            "supply_reliability_status=excluded.supply_reliability_status, "
            "updated_at=excluded.updated_at",
            row,
        )
    conn.commit()
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    conn = db.connect(args.project_root)
    try:
        demand = source_reliability.compute_demand_reliability(load_demand_rows(conn))
        supply = source_reliability.compute_supply_reliability(load_supply_rows(conn))
        rows = persist(conn, demand, supply, updated_at=ids.now_kst().isoformat())
    finally:
        conn.close()

    calibrated = sum(
        1
        for row in rows
        if row["demand_reliability_status"] == source_reliability.CALIBRATED
        or row["supply_reliability_status"] == source_reliability.CALIBRATED
    )
    print(f"SOURCE_RELIABILITY: sources={len(rows)} calibrated={calibrated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
