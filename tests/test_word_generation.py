from saas_words_two import word_generation
from saas_words_two.contracts import normalize_title, validate_title


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
