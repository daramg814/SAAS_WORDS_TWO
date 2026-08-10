import json
import sys
from pathlib import Path

from saas_words_two import db, ids

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_human_google_checks as script

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = REPO_ROOT / "qa" / "samples" / "human_google_checks_valid.csv"


def test_sample_fixture_row_is_valid():
    rows = script.read_csv_rows(SAMPLE_CSV)
    assert len(rows) == 1
    assert script.google_calibration.validate_import_row(rows[0]).valid


def test_import_observations_appends_and_freezes_predictions(tmp_path):
    conn = db.connect(tmp_path)
    now = ids.now_kst()
    ledger_path = tmp_path / "ledger.jsonl"
    summary = script.import_observations(
        SAMPLE_CSV,
        tmp_path / "missing_queue.csv",
        ledger_path,
        import_run_id="RUN-TEST",
        id_conn=conn,
        now=now,
    )
    assert summary["imported"] == 1
    assert summary["invalid"] == 0
    assert summary["duplicate_rejected"] == 0

    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["validation_id"] == "GVQ-20260804-0001"
    assert record["predicted_scarcity_score_at_time"] == 91.0
    assert record["import_run_id"] == "RUN-TEST"
    conn.close()


def test_import_observations_rejects_exact_duplicate_on_rerun(tmp_path):
    conn = db.connect(tmp_path)
    now = ids.now_kst()
    ledger_path = tmp_path / "ledger.jsonl"
    script.import_observations(
        SAMPLE_CSV, tmp_path / "missing_queue.csv", ledger_path, import_run_id="RUN-1", id_conn=conn, now=now
    )
    summary2 = script.import_observations(
        SAMPLE_CSV, tmp_path / "missing_queue.csv", ledger_path, import_run_id="RUN-2", id_conn=conn, now=now
    )
    assert summary2["imported"] == 0
    assert summary2["duplicate_rejected"] == 1
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    conn.close()


def test_import_observations_treats_different_checked_at_as_new(tmp_path):
    conn = db.connect(tmp_path)
    now = ids.now_kst()
    ledger_path = tmp_path / "ledger.jsonl"
    input_path = tmp_path / "human_google_checks.csv"
    input_path.write_text(SAMPLE_CSV.read_text(encoding="utf-8"), encoding="utf-8")
    script.import_observations(
        input_path, tmp_path / "missing_queue.csv", ledger_path, import_run_id="RUN-1", id_conn=conn, now=now
    )

    rows = script.read_csv_rows(SAMPLE_CSV)
    rows[0]["user_checked_at"] = "2026-08-05T09:00:00+09:00"
    import csv

    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    summary2 = script.import_observations(
        input_path, tmp_path / "missing_queue.csv", ledger_path, import_run_id="RUN-2", id_conn=conn, now=now
    )
    assert summary2["imported"] == 1
    assert summary2["duplicate_rejected"] == 0
    conn.close()


def test_import_observations_skips_invalid_rows(tmp_path):
    """4.11: a row with both required fields filled but malformed (here, a
    non-integer count) is INVALID, distinct from PARTIALLY_FILLED below."""
    conn = db.connect(tmp_path)
    now = ids.now_kst()
    input_path = tmp_path / "human_google_checks.csv"
    input_path.write_text(
        "validation_id,user_result_count,user_checked_at\nGVQ-1,not-a-number,2026-08-04T20:15:00+09:00\n",
        encoding="utf-8",
    )
    summary = script.import_observations(
        input_path,
        tmp_path / "missing_queue.csv",
        tmp_path / "ledger.jsonl",
        import_run_id="RUN-1",
        id_conn=conn,
        now=now,
    )
    assert summary["invalid"] == 1
    assert summary["imported"] == 0
    conn.close()


def test_import_observations_counts_partially_filled_rows_separately(tmp_path):
    """4.11 PARTIALLY_FILLED: the user filled in one of the two required
    fields but not the other - not the same as a format error (INVALID) or
    an untouched row (QUEUED)."""
    conn = db.connect(tmp_path)
    now = ids.now_kst()
    input_path = tmp_path / "human_google_checks.csv"
    input_path.write_text(
        "validation_id,user_result_count,user_checked_at\nGVQ-1,,2026-08-04T20:15:00+09:00\n",
        encoding="utf-8",
    )
    summary = script.import_observations(
        input_path,
        tmp_path / "missing_queue.csv",
        tmp_path / "ledger.jsonl",
        import_run_id="RUN-1",
        id_conn=conn,
        now=now,
    )
    assert summary["partially_filled"] == 1
    assert summary["invalid"] == 0
    assert summary["imported"] == 0
    conn.close()


def test_import_observations_counts_untouched_rows_as_queued(tmp_path):
    """4.11 QUEUED: a row still waiting on the user (neither field filled)
    is not an error at all - it just keeps waiting."""
    conn = db.connect(tmp_path)
    now = ids.now_kst()
    input_path = tmp_path / "human_google_checks.csv"
    input_path.write_text(
        "validation_id,user_result_count,user_checked_at\nGVQ-1,,\n",
        encoding="utf-8",
    )
    summary = script.import_observations(
        input_path,
        tmp_path / "missing_queue.csv",
        tmp_path / "ledger.jsonl",
        import_run_id="RUN-1",
        id_conn=conn,
        now=now,
    )
    assert summary["queued"] == 1
    assert summary["invalid"] == 0
    assert summary["partially_filled"] == 0
    conn.close()


def test_main_writes_report(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "output" / "review").mkdir(parents=True)
    (tmp_path / "memory" / "human_feedback").mkdir(parents=True)
    (tmp_path / "input" / "human_google_checks.csv").write_text(
        SAMPLE_CSV.read_text(encoding="utf-8"), encoding="utf-8"
    )
    exit_code = script.main(["--project-root", str(tmp_path)])
    assert exit_code == 0
    report_path = tmp_path / "output" / "review" / "google_feedback_import_report.md"
    assert report_path.exists()
    assert "imported: 1" in report_path.read_text(encoding="utf-8")
