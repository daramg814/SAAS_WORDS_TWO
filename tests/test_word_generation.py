from saas_words_two import word_bank, word_generation
from saas_words_two.contracts import normalize_title, reverse_normalized_title, validate_title


def test_generate_combinations_returns_requested_count():
    combos = word_generation.generate_combinations(20)
    assert len(combos) == 20


def test_generate_combinations_all_valid_titles():
    combos = word_generation.generate_combinations(50)
    for c in combos:
        result = validate_title(c["title"])
        assert result.valid, (c["title"], result.errors)


def test_generate_combinations_no_duplicates_within_batch():
    combos = word_generation.generate_combinations(200)
    normalized = [normalize_title(c["title"]) for c in combos]
    assert len(normalized) == len(set(normalized))


def test_generate_combinations_respects_exclude_set():
    first = word_generation.generate_combinations(20)
    exclude = {normalize_title(c["title"]) for c in first}
    second = word_generation.generate_combinations(20, exclude=exclude)
    second_normalized = {normalize_title(c["title"]) for c in second}
    assert not (exclude & second_normalized)


def test_generate_combinations_spreads_across_multiple_industries():
    combos = word_generation.generate_combinations(30)
    industries = {c["industry"] for c in combos}
    assert len(industries) >= 10


def test_generate_combinations_zero_or_negative_returns_empty():
    assert word_generation.generate_combinations(0) == []
    assert word_generation.generate_combinations(-5) == []


def test_generate_combinations_each_item_has_title_and_industry_keys():
    combos = word_generation.generate_combinations(5)
    for c in combos:
        assert set(c.keys()) == {"title", "industry"}


def test_generate_combinations_no_reverse_duplicates_at_large_batch_size():
    # GKP-001 (2026-08-17): a handful of words (Grid/Meter/Ledger/Terminal/
    # Route) are cross-listed as both a domain word (one industry) and a
    # function word, so "A B" and "B A" can both be generated. At small batch
    # sizes this rarely coincided; a 10,000-candidate round hit it 6 times.
    combos = word_generation.generate_combinations(5000)
    normalized = {normalize_title(c["title"]) for c in combos}
    for norm in normalized:
        rev = reverse_normalized_title(norm)
        assert rev == norm or rev not in normalized, f"reverse duplicate: {norm!r} vs {rev!r}"


def test_generate_combinations_can_reach_every_pair_regardless_of_word_bank_size(monkeypatch):
    # 2026-08-17 (GKP-001): with the real 42-industry/74-function-word bank,
    # gcd(504 mod 74, 74) == 2, so the old single-counter scheme could only
    # ever reach half the domain-word/function-word pairs (14,903 of
    # 37,296) no matter how many attempts it made. This monkeypatches in an
    # even more adversarial size (12 domain words mod 6 function words == 0,
    # so the old scheme would pair every domain word with the exact same
    # function word every time - 12/72 reachable) and asserts the fix
    # reaches the full product space.
    monkeypatch.setattr(
        word_bank,
        "DOMAIN_WORDS",
        {
            "a": ("A1", "A2", "A3", "A4"),
            "b": ("B1", "B2", "B3", "B4"),
            "c": ("C1", "C2", "C3", "C4"),
        },
    )
    monkeypatch.setattr(word_bank, "FUNCTION_WORDS", ("F1", "F2", "F3", "F4", "F5", "F6"))

    combos = word_generation.generate_combinations(1000, exclude=set())

    expected = {
        f"{domain} {func}"
        for words in word_bank.DOMAIN_WORDS.values()
        for domain in words
        for func in word_bank.FUNCTION_WORDS
    }
    assert {c["title"] for c in combos} == expected
    assert len(combos) == 12 * 6


def test_generate_combinations_accepts_domain_words_and_function_words_override():
    # 2026-08-18 (self-expanding word bank): passing explicit pools bypasses
    # word_bank.DOMAIN_WORDS/FUNCTION_WORDS entirely, so a merged
    # static+dynamic pool (word_pipeline._merged_word_bank) can be used
    # without touching module-level state.
    combos = word_generation.generate_combinations(
        100,
        domain_words={"custom_industry": ("Widget", "Gadget")},
        function_words=("Hub", "Desk"),
    )
    assert len(combos) == 4
    assert {c["title"] for c in combos} == {"Widget Hub", "Widget Desk", "Gadget Hub", "Gadget Desk"}
    assert {c["industry"] for c in combos} == {"custom_industry"}


def test_generate_combinations_respects_reverse_of_exclude_set():
    first = word_generation.generate_combinations(1)
    title = first[0]["title"]
    reversed_title = " ".join(reversed(title.split()))
    exclude = {normalize_title(title)}
    second = word_generation.generate_combinations(2000, exclude=exclude)
    second_normalized = {normalize_title(c["title"]) for c in second}
    assert normalize_title(reversed_title) not in second_normalized
