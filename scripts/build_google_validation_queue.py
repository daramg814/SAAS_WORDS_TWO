"""사람이 확인하면 학습 가치가 높은 검색어를 우선순위에 따라 추천 목록으로 만든다."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from saas_words_two import db, google_calibration, ids

CSV_FIELDS = (
    "validation_id",
    "query_type",
    "problem_id",
    "title",
    "google_query",
    "predicted_effective_supply",
    "predicted_scarcity_score",
    "predicted_result_band",
    "priority_reason",
    "user_result_count",
    "user_checked_at",
    "country",
    "language",
    "search_context",
    "top_results_relevant",
    "user_notes",
)

BOUNDARY_VALUES = (65, 70, 80)


def predicted_band_from_scarcity_score(scarcity_score: float) -> str:
    """Inverse of google_calibration.BAND_TO_SCARCITY_SCORE: a high scarcity
    score means we predict little visible online supply (a low Google
    footprint), and vice versa."""
    nearest_band = min(
        google_calibration.BAND_TO_SCARCITY_SCORE,
        key=lambda band: abs(google_calibration.BAND_TO_SCARCITY_SCORE[band] - scarcity_score),
    )
    return nearest_band


def market_query_priority_reasons(opportunity: dict, previously_observed_problem_ids: set[str]) -> list[str]:
    reasons = []
    if opportunity["scarcity_grade"] == "S" and opportunity["confidence"] != "A":
        reasons.append("S등급이지만 AI 신뢰도가 낮음")
    if opportunity["problem_id"] not in previously_observed_problem_ids:
        reasons.append("사람 검증 데이터가 없는 산업")
    for boundary in BOUNDARY_VALUES:
        if abs(opportunity["supply_scarcity_score"] - boundary) <= 5:
            reasons.append(f"공급 부족 점수가 경계값({boundary}) 근처")
            break
    return reasons


def select_market_query_candidates(
    opportunities: list[dict], previously_observed_problem_ids: set[str], *, limit: int
) -> list[dict]:
    scored = []
    for opportunity in opportunities:
        reasons = market_query_priority_reasons(opportunity, previously_observed_problem_ids)
        if reasons:
            scored.append((len(reasons), opportunity, reasons))
    scored.sort(key=lambda item: (-item[0], item[1]["problem_id"]))
    return [{"opportunity": opp, "reasons": reasons} for _, opp, reasons in scored[:limit]]


def select_title_query_candidates(titles: list[dict], *, limit: int) -> list[dict]:
    return [{"title": title, "reasons": ["최종 후보 제목의 충돌 위험 확인"]} for title in titles[:limit]]


def build_rows(
    conn,
    *,
    now,
    market_limit: int = google_calibration.MARKET_QUEUE_SIZE,
    title_limit: int = google_calibration.TITLE_QUEUE_SIZE,
) -> list[dict]:
    opportunities = [dict(row) for row in conn.execute("SELECT * FROM opportunities").fetchall()]
    problems_by_id = {row["problem_id"]: dict(row) for row in conn.execute("SELECT * FROM problems").fetchall()}
    previously_observed = {
        row["problem_id"]
        for row in conn.execute(
            "SELECT DISTINCT problem_id FROM opportunities WHERE human_observation_count > 0"
        ).fetchall()
    }
    titles = [dict(row) for row in conn.execute("SELECT * FROM titles WHERE status = 'approved'").fetchall()]

    rows = []
    for candidate in select_market_query_candidates(opportunities, previously_observed, limit=market_limit):
        opportunity = candidate["opportunity"]
        problem = problems_by_id.get(opportunity["problem_id"], {})
        validation_id = ids.next_validation_id(conn, now)
        query_text = " ".join(part for part in (problem.get("task"), problem.get("target_user")) if part)
        rows.append(
            {
                "validation_id": validation_id,
                "query_type": "MARKET_QUERY",
                "problem_id": opportunity["problem_id"],
                "title": "",
                "google_query": query_text,
                "predicted_effective_supply": opportunity["effective_supply"],
                "predicted_scarcity_score": opportunity["supply_scarcity_score"],
                "predicted_result_band": predicted_band_from_scarcity_score(opportunity["supply_scarcity_score"]),
                "priority_reason": "; ".join(candidate["reasons"]),
                "user_result_count": "",
                "user_checked_at": "",
                "country": "KR",
                "language": "en",
                "search_context": "",
                "top_results_relevant": "",
                "user_notes": "",
            }
        )

    for candidate in select_title_query_candidates(titles, limit=title_limit):
        title_row = candidate["title"]
        validation_id = ids.next_validation_id(conn, now)
        rows.append(
            {
                "validation_id": validation_id,
                "query_type": "TITLE_QUERY",
                "problem_id": title_row.get("problem_id", ""),
                "title": title_row.get("title", ""),
                "google_query": f'"{title_row.get("title", "")}"',
                "predicted_effective_supply": "",
                "predicted_scarcity_score": "",
                "predicted_result_band": "LOW",
                "priority_reason": "; ".join(candidate["reasons"]),
                "user_result_count": "",
                "user_checked_at": "",
                "country": "KR",
                "language": "en",
                "search_context": "",
                "top_results_relevant": "",
                "user_notes": "",
            }
        )
    return rows


def write_queue_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path, default=None, help="defaults to output/deliverables/review/google_validation_queue.csv"
    )
    args = parser.parse_args(argv)

    project_root = args.project_root
    output_path = args.output or project_root / "output" / "deliverables" / "review" / "google_validation_queue.csv"
    now = ids.now_kst()
    conn = db.connect(project_root)
    try:
        rows = build_rows(conn, now=now)
        conn.commit()
    finally:
        conn.close()

    write_queue_csv(output_path, rows)
    market_count = sum(1 for row in rows if row["query_type"] == "MARKET_QUERY")
    title_count = sum(1 for row in rows if row["query_type"] == "TITLE_QUERY")
    print(f"GOOGLE VALIDATION QUEUE: market={market_count} title={title_count} total={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
