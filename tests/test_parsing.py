from saas_words_two import parsing


def test_validate_rows_clean_data_passes():
    rows = [
        {"id": 1, "type": "story", "by": "alice", "time": 100, "deleted": 0, "dead": 0},
        {"id": 2, "type": "comment", "by": "bob", "time": 101, "parent": 1, "deleted": 0, "dead": 0},
    ]
    report = parsing.validate_rows(rows)
    assert report.ok
    assert report.total_items == 2
    assert report.counts_by_type == {"story": 1, "comment": 1}


def test_validate_rows_detects_duplicate_ids():
    rows = [
        {"id": 1, "type": "story", "by": "alice", "time": 100},
        {"id": 1, "type": "story", "by": "alice", "time": 100},
    ]
    report = parsing.validate_rows(rows)
    assert not report.ok
    assert report.duplicate_ids == [1]


def test_validate_rows_detects_missing_required_field():
    rows = [{"id": 1, "type": "story", "by": None, "time": 100}]
    report = parsing.validate_rows(rows)
    assert not report.ok
    assert "missing required field 'by'" in report.schema_violations[0]


def test_validate_rows_skips_dead_or_deleted_items():
    rows = [{"id": 1, "type": "story", "by": None, "time": None, "dead": 1}]
    report = parsing.validate_rows(rows)
    assert report.ok


def test_checksum_is_order_independent_and_deterministic():
    assert parsing.checksum_ids([3, 1, 2]) == parsing.checksum_ids([1, 2, 3])
    assert parsing.checksum_ids([1, 2, 3]) != parsing.checksum_ids([1, 2, 4])


def test_report_to_markdown_reflects_pass_and_fail():
    ok_report = parsing.validate_rows([{"id": 1, "type": "story", "by": "a", "time": 1}])
    assert "Result: PASS" in parsing.report_to_markdown(ok_report, "t0")

    bad_report = parsing.validate_rows([{"id": 1, "type": "story", "by": None, "time": None}])
    markdown = parsing.report_to_markdown(bad_report, "t0")
    assert "Result: FAIL" in markdown
    assert "Schema violations" in markdown
