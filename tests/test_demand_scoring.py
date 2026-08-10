from saas_words_two import demand_scoring as ds


def test_independent_users_score_tiers():
    assert ds.independent_users_score(0) == 0
    assert ds.independent_users_score(3) == 5
    assert ds.independent_users_score(5) == 15
    assert ds.independent_users_score(10) == 20
    assert ds.independent_users_score(25) == 25
    assert ds.independent_users_score(100) == 25


def test_persistence_score_tiers():
    assert ds.persistence_score(1) == 0
    assert ds.persistence_score(2) == 8
    assert ds.persistence_score(3) == 15
    assert ds.persistence_score(9) == 15


def test_frequency_score_known_and_unknown_labels():
    assert ds.frequency_score("daily") == 10
    assert ds.frequency_score("monthly") == 5
    assert ds.frequency_score("nonsense") == 0


def test_distinct_thread_ids_uses_parent_for_comments_and_self_for_stories():
    evidence = [
        {"id": 1, "type": "story", "parent": None},
        {"id": 2, "type": "comment", "parent": 1},
        {"id": 3, "type": "comment", "parent": 1},
        {"id": 4, "type": "comment", "parent": 99},
    ]
    threads = ds.distinct_thread_ids(evidence)
    assert threads == {1, 99}


def test_distinct_period_count_groups_by_month():
    # 2024-01-15 and 2024-01-20 same month; 2024-03-01 different month
    timestamps = [1705276800, 1705708800, 1709251200]
    assert ds.distinct_period_count(timestamps) == 2


def test_has_recent_evidence_true_within_window_false_outside():
    now = 1_800_000_000
    recent = now - 30 * 24 * 3600
    old = now - 800 * 24 * 3600
    assert ds.has_recent_evidence([old, recent], now_epoch=now, months=24)
    assert not ds.has_recent_evidence([old], now_epoch=now, months=24)


def _passing_input(**overrides):
    base = {
        "independent_users": 7,
        "distinct_periods": 3,
        "frequency": "weekly",
        "risk_severity": "moderate",
        "has_manual_or_complaint_evidence": True,
        "purchase_intent": "strong",
        "distinct_threads": 3,
        "has_recent_evidence": True,
    }
    base.update(overrides)
    return ds.DemandScoreInput(**base)


def test_score_demand_passes_when_all_gates_met():
    result = ds.score_demand(_passing_input())
    assert result.passed
    assert result.fail_reasons == ()
    assert result.total == (15 + 15 + 8 + 8 + 10 + 15 + 10)


def test_score_demand_fails_on_independent_users_below_minimum():
    result = ds.score_demand(_passing_input(independent_users=3))
    assert not result.passed
    assert any("independent_users_below_minimum" in r for r in result.fail_reasons)


def test_score_demand_fails_without_recent_evidence():
    result = ds.score_demand(_passing_input(has_recent_evidence=False))
    assert not result.passed
    assert "no_recent_24_month_evidence" in result.fail_reasons


def test_score_demand_fails_without_manual_or_complaint_evidence():
    result = ds.score_demand(_passing_input(has_manual_or_complaint_evidence=False))
    assert not result.passed
    assert "no_manual_or_complaint_evidence" in result.fail_reasons


def test_score_demand_fails_without_purchase_intent_or_loss():
    result = ds.score_demand(_passing_input(purchase_intent="none", risk_severity="none"))
    assert not result.passed
    assert "no_purchase_intent_or_economic_loss" in result.fail_reasons


def test_score_demand_passes_with_loss_but_no_purchase_intent():
    result = ds.score_demand(_passing_input(purchase_intent="none", risk_severity="severe"))
    assert result.passed


def test_score_demand_fails_below_total_minimum_even_if_gates_pass():
    # meets every boolean gate but every graded score is at its lowest non-zero tier
    result = ds.score_demand(
        _passing_input(
            independent_users=5,
            distinct_periods=1,
            frequency="unknown",
            risk_severity="none",
            purchase_intent="none",
            distinct_threads=1,
        )
    )
    assert not result.passed
