from saas_words_two import source_reliability


def test_side_reliability_is_no_data_below_minimum_samples():
    result = source_reliability.compute_demand_reliability(
        [("gh_archive", "P-0001", True), ("gh_archive", "P-0002", False)]
    )
    assert result["gh_archive"].status == source_reliability.NO_DATA
    assert result["gh_archive"].score is None
    assert result["gh_archive"].total == 2
    assert result["gh_archive"].positive == 1


def test_demand_reliability_calibrates_once_minimum_samples_reached():
    rows = [("hacker_news", f"P-{i:04d}", i < 3) for i in range(5)]
    result = source_reliability.compute_demand_reliability(rows)
    rel = result["hacker_news"]
    assert rel.status == source_reliability.CALIBRATED
    assert rel.total == 5
    assert rel.positive == 3
    assert rel.score == 3 / 5


def test_demand_reliability_dedupes_multiple_evidence_rows_for_same_problem():
    # two evidence rows from the same source for the same problem must count
    # as one (problem, source) pair, not inflate the denominator
    rows = [
        ("hacker_news", "P-0001", True),
        ("hacker_news", "P-0001", True),
        ("hacker_news", "P-0002", False),
        ("hacker_news", "P-0003", False),
        ("hacker_news", "P-0004", False),
        ("hacker_news", "P-0005", False),
    ]
    result = source_reliability.compute_demand_reliability(rows)
    assert result["hacker_news"].total == 5
    assert result["hacker_news"].positive == 1


def test_demand_reliability_treats_unscored_problem_as_not_passed():
    rows = [("npm_registry", f"P-{i:04d}", False) for i in range(5)]
    result = source_reliability.compute_demand_reliability(rows)
    assert result["npm_registry"].positive == 0
    assert result["npm_registry"].score == 0.0


def test_demand_reliability_separates_sources_independently():
    rows = [("hacker_news", "P-0001", True)] + [("gh_archive", f"P-{i:04d}", False) for i in range(5)]
    result = source_reliability.compute_demand_reliability(rows)
    assert result["hacker_news"].status == source_reliability.NO_DATA
    assert result["gh_archive"].status == source_reliability.CALIBRATED
    assert result["gh_archive"].score == 0.0


def test_supply_reliability_is_no_data_below_minimum_samples():
    result = source_reliability.compute_supply_reliability([("common_crawl", True), ("common_crawl", False)])
    assert result["common_crawl"].status == source_reliability.NO_DATA


def test_supply_reliability_calibrates_once_minimum_samples_reached():
    rows = [("stack_exchange_dump", True)] * 3 + [("stack_exchange_dump", False)] * 2
    result = source_reliability.compute_supply_reliability(rows)
    rel = result["stack_exchange_dump"]
    assert rel.status == source_reliability.CALIBRATED
    assert rel.total == 5
    assert rel.positive == 3
    assert rel.score == 3 / 5


def test_reliability_functions_return_empty_dict_for_no_rows():
    assert source_reliability.compute_demand_reliability([]) == {}
    assert source_reliability.compute_supply_reliability([]) == {}
