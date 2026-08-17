from saas_words_two import word_generation
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


def test_generate_combinations_respects_reverse_of_exclude_set():
    first = word_generation.generate_combinations(1)
    title = first[0]["title"]
    reversed_title = " ".join(reversed(title.split()))
    exclude = {normalize_title(title)}
    second = word_generation.generate_combinations(2000, exclude=exclude)
    second_normalized = {normalize_title(c["title"]) for c in second}
    assert normalize_title(reversed_title) not in second_normalized
