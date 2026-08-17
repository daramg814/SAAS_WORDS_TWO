from datetime import datetime
from zoneinfo import ZoneInfo

from saas_words_two import ids


def test_format_run_id_production_vs_qa():
    when = datetime(2026, 8, 10, 19, 30, 5, tzinfo=ZoneInfo("Asia/Seoul"))
    assert ids.format_run_id("production", when) == "RUN-20260810-193005-KST"
    assert ids.format_run_id("qa", when) == "QA-20260810-193005-KST"


def test_now_kst_is_seoul_timezone():
    now = ids.now_kst()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 9 * 3600
