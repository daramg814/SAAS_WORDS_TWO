from saas_words_two import title_generation as tg


def test_first_round_size_uses_multiplier_when_larger():
    # target 500: 500*1.6=800 vs 500+20=520 -> 800 wins
    assert tg.first_round_size(500) == 800


def test_first_round_size_uses_min_extra_when_multiplier_smaller():
    # target 20: 20*1.6=32 vs 20+20=40 -> 40 wins
    assert tg.first_round_size(20) == 40


def test_next_round_size_is_double_the_shortfall():
    assert tg.next_round_size(160) == 320
    assert tg.next_round_size(0) == 0


def test_max_titles_per_opportunity_floors_to_30_percent():
    assert tg.max_titles_per_opportunity(500) == 150
    assert tg.max_titles_per_opportunity(20) == 6


def test_check_distribution_flags_too_few_opportunities():
    counts = {"P-0001": 10, "P-0002": 10}
    violations = tg.check_distribution(counts, target_count=20)
    assert any("fewer_than_5_opportunities" in v for v in violations)


def test_check_distribution_flags_opportunity_over_cap():
    counts = {f"P-{i:04d}": 4 for i in range(5)}
    counts["P-0000"] = 10  # cap for target=20 is 6
    violations = tg.check_distribution(counts, target_count=20)
    assert any("opportunity_over_30pct:P-0000" in v for v in violations)


def test_check_distribution_passes_when_balanced_across_five_plus():
    counts = {f"P-{i:04d}": 4 for i in range(5)}
    violations = tg.check_distribution(counts, target_count=20)
    assert violations == ()


def test_allocate_title_slots_sums_to_target_when_pool_is_large_enough():
    opportunities = [{"problem_id": f"P-{i:04d}", "priority_score": 100 - i} for i in range(8)]
    allocation = tg.allocate_title_slots(opportunities, target_count=20)
    assert sum(allocation.values()) == 20


def test_allocate_title_slots_respects_cap_per_opportunity():
    opportunities = [{"problem_id": "P-0001", "priority_score": 100}, {"problem_id": "P-0002", "priority_score": 1}]
    allocation = tg.allocate_title_slots(opportunities, target_count=20)
    cap = tg.max_titles_per_opportunity(20)
    assert all(count <= cap for count in allocation.values())


def test_allocate_title_slots_gives_more_to_higher_priority():
    opportunities = [
        {"problem_id": "P-high", "priority_score": 90},
        {"problem_id": "P-mid", "priority_score": 50},
        {"problem_id": "P-low", "priority_score": 10},
        {"problem_id": "P-low2", "priority_score": 10},
        {"problem_id": "P-low3", "priority_score": 10},
    ]
    allocation = tg.allocate_title_slots(opportunities, target_count=20)
    assert allocation["P-high"] >= allocation["P-mid"] >= allocation["P-low"]


def test_allocate_title_slots_falls_short_when_pool_too_small_and_capped():
    # only 2 opportunities, cap=6 each for target=20 -> max 12 total, cannot reach 20
    opportunities = [{"problem_id": "P-0001", "priority_score": 50}, {"problem_id": "P-0002", "priority_score": 50}]
    allocation = tg.allocate_title_slots(opportunities, target_count=20)
    assert sum(allocation.values()) <= 12


def test_allocate_title_slots_empty_when_no_opportunities():
    assert tg.allocate_title_slots([], target_count=20) == {}
