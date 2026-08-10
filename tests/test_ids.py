from datetime import datetime
from zoneinfo import ZoneInfo

from saas_words_two import db, ids


def test_format_run_id_production_vs_qa():
    when = datetime(2026, 8, 10, 19, 30, 5, tzinfo=ZoneInfo("Asia/Seoul"))
    assert ids.format_run_id("production", when) == "RUN-20260810-193005-KST"
    assert ids.format_run_id("qa", when) == "QA-20260810-193005-KST"


def test_format_generated_filename():
    when = datetime(2026, 8, 10, 19, 30, 5, tzinfo=ZoneInfo("Asia/Seoul"))
    assert ids.format_generated_filename(when) == "saas_words_20260810_193005_KST.txt"


def test_sequential_ids_increment_and_are_zero_padded(tmp_path):
    conn = db.connect(tmp_path)
    assert ids.next_problem_id(conn) == "P-0001"
    assert ids.next_problem_id(conn) == "P-0002"
    assert ids.next_evidence_id(conn) == "E-0001"
    assert ids.next_product_id(conn) == "S-0001"
    conn.close()


def test_daily_ids_reset_per_day(tmp_path):
    conn = db.connect(tmp_path)
    day1 = datetime(2026, 8, 4, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    day2 = datetime(2026, 8, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert ids.next_validation_id(conn, day1) == "GVQ-20260804-0001"
    assert ids.next_validation_id(conn, day1) == "GVQ-20260804-0002"
    assert ids.next_validation_id(conn, day2) == "GVQ-20260805-0001"
    assert ids.next_observation_id(conn, day1) == "HGO-20260804-0001"
    conn.close()


def test_now_kst_is_seoul_timezone():
    now = ids.now_kst()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 9 * 3600
