from saas_words_two import opportunity_scoring as ops


def test_priority_score_matches_worked_example_a():
    # demand 80, supply-scarcity 60, no scarcity bonus
    assert round(ops.priority_score(80, 60, effective_supply_value=6), 1) == 67.0


def test_priority_score_matches_worked_example_b():
    # demand 52, supply-scarcity 90, effective_supply 1.5 -> +10 bonus
    score = ops.priority_score(52, 90, effective_supply_value=1.5)
    assert round(score, 1) == 86.7


def test_priority_score_capped_at_100():
    assert ops.priority_score(100, 100, effective_supply_value=1) == 100.0


def test_priority_score_bonus_tiers():
    base = 50.0
    assert ops.priority_score(base, base, effective_supply_value=2) - ops.priority_score(
        base, base, effective_supply_value=2.1
    ) == 5.0
    assert ops.priority_score(base, base, effective_supply_value=5) - ops.priority_score(
        base, base, effective_supply_value=5.1
    ) == 5.0


def test_confidence_a_requires_all_three_conditions():
    assert (
        ops.confidence(3, 25, supply_fully_verified=True, supply_partially_verified=False) == "A"
    )
    assert (
        ops.confidence(2, 25, supply_fully_verified=True, supply_partially_verified=False) == "B"
    )
    assert (
        ops.confidence(3, 10, supply_fully_verified=True, supply_partially_verified=False) == "B"
    )


def test_confidence_b_requires_source_and_user_minimums():
    assert ops.confidence(2, 5, supply_fully_verified=False, supply_partially_verified=True) == "B"
    assert ops.confidence(1, 5, supply_fully_verified=False, supply_partially_verified=True) == "C"
    assert ops.confidence(2, 4, supply_fully_verified=False, supply_partially_verified=True) == "C"


def _eligible_input(**overrides):
    base = {
        "demand_score": 80,
        "independent_users": 10,
        "has_recent_evidence": True,
        "is_repeated_task": True,
        "has_loss_time_or_risk_evidence": True,
        "has_clear_saas_feature": True,
        "supply_scarcity_score": 85,
        "priority_score_value": 80.0,
        "scarcity_grade": "S",
        "confidence_level": "A",
        "has_manual_or_complaint_evidence": True,
        "purchase_intent_or_loss": True,
    }
    base.update(overrides)
    return ops.OpportunityEligibilityInput(**base)


def test_hard_exclusion_overrides_everything_even_with_zero_supply():
    eligible = _eligible_input(independent_users=3)
    reasons = ops.hard_exclusion_reasons(eligible)
    assert "independent_users_below_5" in reasons
    assert ops.provisional_decision(eligible) == "REJECT"
    assert not ops.meets_generate_titles_conditions(eligible)


def test_generate_titles_when_all_conditions_met():
    eligible = _eligible_input()
    assert ops.meets_generate_titles_conditions(eligible)
    assert ops.provisional_decision(eligible) == "GENERATE_TITLES"


def test_reject_when_grade_c():
    eligible = _eligible_input(scarcity_grade="C")
    assert not ops.meets_generate_titles_conditions(eligible)


def test_reject_when_confidence_c():
    eligible = _eligible_input(confidence_level="C")
    assert not ops.meets_generate_titles_conditions(eligible)


def test_moderate_demand_extreme_scarcity_still_clears_generate_titles_gate():
    # Demand 52 clears the >=45 floor, so the mechanical gate is GENERATE_TITLES;
    # only the opportunity-reviewer (not code) may relabel this SCARCITY_PRIORITY.
    moderate = _eligible_input(demand_score=52, supply_scarcity_score=90, scarcity_grade="S")
    assert ops.meets_generate_titles_conditions(moderate)
    assert ops.provisional_decision(moderate) == "GENERATE_TITLES"


def test_scarcity_priority_is_never_assigned_by_code():
    for demand_score in (45, 50, 60, 64, 80):
        eligible = _eligible_input(demand_score=demand_score)
        assert ops.provisional_decision(eligible) != "SCARCITY_PRIORITY"


def test_high_demand_high_supply_is_rejected_by_scarcity_score_gate():
    # plenty of demand but supply isn't scarce (below 65) -> no titles, no priority bump
    input_ = _eligible_input(supply_scarcity_score=40, scarcity_grade="C")
    assert ops.provisional_decision(input_) == "RESEARCH_MORE"


def test_sort_opportunities_orders_by_grade_then_scarcity_then_supply_then_priority():
    opportunities = [
        {"problem_id": "P1", "scarcity_grade": "A", "supply_scarcity_score": 70, "effective_supply": 3, "priority_score": 75, "confidence": "A", "demand_score": 60},
        {"problem_id": "P2", "scarcity_grade": "S", "supply_scarcity_score": 80, "effective_supply": 1, "priority_score": 90, "confidence": "A", "demand_score": 50},
        {"problem_id": "P3", "scarcity_grade": "S", "supply_scarcity_score": 85, "effective_supply": 2, "priority_score": 88, "confidence": "B", "demand_score": 55},
    ]
    ordered = ops.sort_opportunities(opportunities)
    assert [o["problem_id"] for o in ordered] == ["P3", "P2", "P1"]


def test_worked_example_from_design_doc_problem_b_outranks_problem_a():
    # Problem A: demand 80, supply-scarcity 60 -> priority 67, grade lower since scarcity score < 65 threshold band assumptions
    # Problem B: demand 52, supply-scarcity 90, effective_supply 1.5 -> priority 86.7, grade S
    problem_a = {
        "problem_id": "A", "scarcity_grade": "B", "supply_scarcity_score": 60,
        "effective_supply": 6, "priority_score": 67.0, "confidence": "B", "demand_score": 80,
    }
    problem_b = {
        "problem_id": "B", "scarcity_grade": "S", "supply_scarcity_score": 90,
        "effective_supply": 1.5, "priority_score": 86.7, "confidence": "A", "demand_score": 52,
    }
    ordered = ops.sort_opportunities([problem_a, problem_b])
    assert [o["problem_id"] for o in ordered] == ["B", "A"]
