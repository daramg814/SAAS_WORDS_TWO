from saas_words_two.clustering import Candidate, cluster_candidates, combined_similarity, tokenize


def test_tokenize_drops_stopwords_and_short_tokens():
    tokens = tokenize("We still use spreadsheets to track vendor insurance")
    assert "spreadsheets" in tokens
    assert "vendor" in tokens
    assert "insurance" in tokens
    assert "we" not in tokens
    assert "to" not in tokens


def test_combined_similarity_high_for_near_duplicate_sentences():
    a = "We still use spreadsheets to track vendor insurance expiration"
    b = "I still use a spreadsheet to track vendor insurance expiry"
    assert combined_similarity(a, a) == 1.0
    assert combined_similarity(a, b) > 0.4


def test_combined_similarity_low_for_unrelated_sentences():
    a = "We still use spreadsheets to track vendor insurance"
    b = "This new JavaScript framework has a confusing build system"
    assert combined_similarity(a, b) < 0.3


def test_cluster_candidates_groups_near_duplicates_together():
    candidates = [
        Candidate(1, 101, "We still use spreadsheets to track vendor insurance", author="alice"),
        Candidate(2, 102, "I still use a spreadsheet to track vendor insurance", author="bob"),
        Candidate(3, 103, "Our team uses spreadsheets for vendor insurance tracking", author="carl"),
        Candidate(4, 104, "This build tool is way too complicated for beginners", author="dave"),
    ]
    clusters = cluster_candidates(candidates)
    # the two near-identical vendor-insurance sentences should land in one cluster;
    # the more loosely related third one and the unrelated fourth stay separate
    sizes = sorted(len(c.members) for c in clusters)
    assert sizes == [1, 1, 2]


def test_cluster_candidates_does_not_merge_on_shared_trigger_phrase_alone():
    # both contain "how do you manage" but are otherwise unrelated topics
    candidates = [
        Candidate(1, 101, "How do you manage your prompts in ChatGPT?", author="alice"),
        Candidate(2, 102, "How do you manage your morning catch-up routine?", author="bob"),
    ]
    clusters = cluster_candidates(candidates)
    assert len(clusters) == 2


def test_strip_trigger_phrases_removes_matched_pattern():
    from saas_words_two.clustering import strip_trigger_phrases

    residual = strip_trigger_phrases("We still use spreadsheets for tracking vendor insurance")
    assert "still use spreadsheets" not in residual.lower()
    assert "vendor insurance" in residual


def test_cluster_independent_user_count_dedupes_by_author():
    candidates = [
        Candidate(1, 101, "We still use spreadsheets to track vendor insurance", author="alice"),
        Candidate(2, 102, "We still use spreadsheets to track vendor insurance", author="alice"),
        Candidate(3, 103, "We still use spreadsheets to track vendor insurance", author="bob"),
    ]
    clusters = cluster_candidates(candidates)
    assert len(clusters) == 1
    assert clusters[0].independent_user_count == 2


def test_cluster_independent_user_count_falls_back_to_candidate_count_when_author_missing():
    candidates = [
        Candidate(1, 101, "We still use spreadsheets to track vendor insurance", author=None),
        Candidate(2, 102, "We still use spreadsheets to track vendor insurance", author=None),
    ]
    clusters = cluster_candidates(candidates)
    assert clusters[0].independent_user_count == 2


def test_singleton_cluster_is_confident_not_ambiguous():
    candidates = [Candidate(1, 101, "A completely unique sentence about llamas", author="alice")]
    clusters = cluster_candidates(candidates)
    assert len(clusters) == 1
    assert clusters[0].confident
    assert not clusters[0].ambiguous


def test_cluster_candidates_is_order_independent_for_grouping_outcome():
    a = Candidate(1, 101, "We still use spreadsheets to track vendor insurance", author="alice")
    b = Candidate(2, 102, "I still use a spreadsheet to track vendor insurance", author="bob")
    c = Candidate(3, 103, "This build tool is way too complicated", author="carl")
    forward = cluster_candidates([a, b, c])
    backward = cluster_candidates([c, b, a])
    assert sorted(len(cl.members) for cl in forward) == sorted(len(cl.members) for cl in backward)
