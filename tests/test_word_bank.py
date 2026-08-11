from saas_words_two import word_bank


def test_covers_at_least_25_industries():
    assert len(word_bank.DOMAIN_WORDS) >= 25


def test_no_duplicate_words_within_an_industry():
    for industry, words in word_bank.DOMAIN_WORDS.items():
        assert len(words) == len(set(words)), f"duplicate word in {industry}"


def test_function_words_has_no_duplicates():
    assert len(word_bank.FUNCTION_WORDS) == len(set(word_bank.FUNCTION_WORDS))


def test_all_words_are_single_title_case_alpha_tokens():
    for words in word_bank.DOMAIN_WORDS.values():
        for word in words:
            assert word.isalpha(), word
            assert word == word.capitalize(), word
    for word in word_bank.FUNCTION_WORDS:
        assert word.isalpha(), word
        assert word == word.capitalize(), word


def test_all_industries_returns_every_key():
    assert set(word_bank.all_industries()) == set(word_bank.DOMAIN_WORDS.keys())


def test_all_domain_words_pairs_industry_with_each_word():
    pairs = word_bank.all_domain_words()
    assert len(pairs) == sum(len(words) for words in word_bank.DOMAIN_WORDS.values())
    assert ("healthcare", "Patient") in pairs
