from saas_words_two import supply


def test_normalize_product_name_strips_show_hn_prefix_and_pitch():
    assert supply.normalize_product_name("Show HN: VendorGuard – track vendor insurance") == "VendorGuard"
    assert supply.normalize_product_name("Show HN: PermitFlow - permit tracking") == "PermitFlow"
    assert supply.normalize_product_name("Just a plain title") == "Just a plain title"


def test_dedupe_key_prefers_domain_over_name():
    assert supply.dedupe_key("VendorGuard", "vendorguard.com") == "vendorguardcom"
    assert supply.dedupe_key("VendorGuard", None) == "vendorguard"
    assert supply.dedupe_key("Vendor Guard!", "www.VendorGuard.com") == supply.dedupe_key(
        "vendorguard", "vendorguard.com"
    )


def test_deduplicate_candidates_groups_by_dedupe_key():
    candidates = [
        supply.SupplyCandidate("VendorGuard", "vendorguard.com", "hn_show", 1),
        supply.SupplyCandidate("Vendor Guard", "vendorguard.com", "hn_mention", 2),
        supply.SupplyCandidate("PermitFlow", "permitflow.io", "hn_show", 3),
    ]
    deduped = supply.deduplicate_candidates(candidates)
    assert len(deduped) == 2
    vendor_guard = next(d for d in deduped if d.domain == "vendorguard.com")
    assert len(vendor_guard.sources) == 2


def test_active_signal_count_and_is_active_supply():
    signals = {"official_name": True, "target_user": True, "core_feature": False, "pricing": True}
    assert supply.active_signal_count(signals) == 3
    assert supply.is_active_supply(signals)
    assert not supply.is_active_supply({"official_name": True, "target_user": False})


def test_effective_supply_only_counts_active_products():
    products = [
        {"active": True, "supply_type": "direct"},
        {"active": True, "supply_type": "partial"},
        {"active": False, "supply_type": "direct"},
        {"active": True, "supply_type": "generic"},
    ]
    assert supply.effective_supply(products) == 1.0 + 0.4 + 0.1


def test_effective_supply_score_tiers():
    assert supply.effective_supply_score(0) == 40
    assert supply.effective_supply_score(2) == 40
    assert supply.effective_supply_score(3) == 30
    assert supply.effective_supply_score(5) == 30
    assert supply.effective_supply_score(7) == 15
    assert supply.effective_supply_score(11) == 0


def test_score_supply_scarcity_passes_when_gates_met():
    result = supply.score_supply_scarcity(
        supply.SupplyScarcityInput(
            effective_supply_value=1.5,
            supply_gap_user_specific=True,
            supply_gap_no_strong_incumbent=True,
            supply_gap_no_recent_entrants=True,
            supply_gap_unresolved_complaints=True,
        )
    )
    assert result.total == 40 + 20 + 15 + 10 + 15
    assert result.passed


def test_score_supply_scarcity_fails_without_no_strong_incumbent():
    result = supply.score_supply_scarcity(
        supply.SupplyScarcityInput(
            effective_supply_value=1.0,
            supply_gap_user_specific=True,
            supply_gap_no_strong_incumbent=False,
            supply_gap_no_recent_entrants=True,
            supply_gap_unresolved_complaints=True,
        )
    )
    assert not result.passed


def test_score_supply_scarcity_fails_below_threshold_even_with_gates():
    result = supply.score_supply_scarcity(
        supply.SupplyScarcityInput(
            effective_supply_value=8,
            supply_gap_user_specific=True,
            supply_gap_no_strong_incumbent=True,
            supply_gap_no_recent_entrants=False,
            supply_gap_unresolved_complaints=False,
        )
    )
    assert result.total < supply.SUPPLY_SCARCITY_SCORE_MIN
    assert not result.passed


def test_scarcity_grade_s_a_b_c():
    assert supply.scarcity_grade(1.0, 1, 85) == "S"
    assert supply.scarcity_grade(4.0, 5, 75) == "A"
    assert supply.scarcity_grade(8.0, 5, 68) == "B"
    assert supply.scarcity_grade(12.0, 5, 90) == "C"
    assert supply.scarcity_grade(1.0, 5, 90) == "A"  # too many direct competitors for S
