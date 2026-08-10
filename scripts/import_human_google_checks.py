"""사용자 Google 검증 CSV를 검증·중복 제거하여 append-only 원장에 반영한다."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from saas_words_two import db, google_calibration, ids
from saas_words_two.contracts import atomic_write_text


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_queue_index(queue_path: Path) -> dict[str, dict]:
    return {row["validation_id"]: row for row in read_csv_rows(queue_path) if row.get("validation_id")}


def load_existing_observations(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    observations = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            observations.append(json.loads(line))
    return observations


def build_observation(
    row: dict, queue_row: dict | None, *, observation_id: str, import_run_id: str
) -> dict:
    def pick(field_name: str, default=None):
        value = row.get(field_name)
        if value not in (None, ""):
            return value
        if queue_row:
            return queue_row.get(field_name, default)
        return default

    return {
        "observation_id": observation_id,
        "validation_id": row["validation_id"],
        "query_type": pick("query_type"),
        "problem_id": pick("problem_id"),
        "title": pick("title"),
        "google_query": pick("google_query"),
        "user_result_count": int(row["user_result_count"]),
        "user_checked_at": row["user_checked_at"],
        "country": pick("country", "KR"),
        "language": pick("language", "ko"),
        "search_context": row.get("search_context") or "normal",
        "top_results_relevant": int(row["top_results_relevant"]) if row.get("top_results_relevant") else None,
        "predicted_effective_supply_at_time": _float_or_none(pick("predicted_effective_supply")),
        "predicted_scarcity_score_at_time": _float_or_none(pick("predicted_scarcity_score")),
        "predicted_result_band_at_time": pick("predicted_result_band"),
        "source": "human_manual_google",
        "import_run_id": import_run_id,
        "user_notes": row.get("user_notes") or None,
    }


def _float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def import_observations(
    input_path: Path,
    queue_path: Path,
    ledger_path: Path,
    *,
    import_run_id: str,
    id_conn,
    now,
) -> dict:
    rows = read_csv_rows(input_path)
    queue_index = load_queue_index(queue_path)
    existing = load_existing_observations(ledger_path)

    imported: list[dict] = []
    duplicate_rejected = 0
    invalid = 0

    for row in rows:
        validation = google_calibration.validate_import_row(row)
        if not validation.valid:
            invalid += 1
            continue
        if google_calibration.is_duplicate_observation(row, existing) or google_calibration.is_duplicate_observation(
            row, imported
        ):
            duplicate_rejected += 1
            continue
        observation_id = ids.next_observation_id(id_conn, now)
        observation = build_observation(
            row, queue_index.get(row["validation_id"]), observation_id=observation_id, import_run_id=import_run_id
        )
        imported.append(observation)

    if imported:
        lines = [json.dumps(observation, ensure_ascii=False, sort_keys=True) for observation in imported]
        existing_text = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""
        if existing_text and not existing_text.endswith("\n"):
            existing_text += "\n"
        atomic_write_text(ledger_path, existing_text + "\n".join(lines) + "\n")

    return {
        "total_rows": len(rows),
        "imported": len(imported),
        "duplicate_rejected": duplicate_rejected,
        "invalid": invalid,
        "imported_records": imported,
    }


def report_to_markdown(summary: dict, generated_at: str) -> str:
    return (
        "# Google Feedback Import Report\n\n"
        f"Generated: {generated_at}\n\n"
        f"- total rows read: {summary['total_rows']}\n"
        f"- imported: {summary['imported']}\n"
        f"- duplicate rejected: {summary['duplicate_rejected']}\n"
        f"- invalid: {summary['invalid']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--input", type=Path, default=None, help="defaults to input/human_google_checks.csv")
    parser.add_argument(
        "--queue", type=Path, default=None, help="defaults to output/review/google_validation_queue.csv"
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="defaults to memory/human_feedback/google_supply_observations.jsonl",
    )
    parser.add_argument(
        "--report", type=Path, default=None, help="defaults to output/review/google_feedback_import_report.md"
    )
    args = parser.parse_args(argv)

    project_root = args.project_root
    now = ids.now_kst()
    run_id = args.run_id or ids.format_run_id("production", now)
    input_path = args.input or project_root / "input" / "human_google_checks.csv"
    queue_path = args.queue or project_root / "output" / "review" / "google_validation_queue.csv"
    ledger_path = args.ledger or project_root / "memory" / "human_feedback" / "google_supply_observations.jsonl"
    report_path = args.report or project_root / "output" / "review" / "google_feedback_import_report.md"

    conn = db.connect(project_root)
    try:
        summary = import_observations(
            input_path,
            queue_path,
            ledger_path,
            import_run_id=run_id,
            id_conn=conn,
            now=now,
        )
    finally:
        conn.close()

    atomic_write_text(report_path, report_to_markdown(summary, now.isoformat()))
    print(
        f"GOOGLE FEEDBACK IMPORT: total={summary['total_rows']} imported={summary['imported']} "
        f"duplicate_rejected={summary['duplicate_rejected']} invalid={summary['invalid']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
