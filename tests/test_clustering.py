import pytest

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


# ---------------------------------------------------------------------------
# TF-IDF weighted cosine similarity ("B안")
# ---------------------------------------------------------------------------

from saas_words_two.clustering import (
    compute_idf,
    cosine_similarity,
    cluster_candidates_tfidf,
    tfidf_vector,
)


def test_compute_idf_gives_lower_weight_to_more_common_terms():
    token_sets = [
        {"common", "rare_a"},
        {"common", "rare_b"},
        {"common", "rare_c"},
        {"common", "rare_d"},
    ]
    idf = compute_idf(token_sets)
    assert idf["common"] < idf["rare_a"]


def test_compute_idf_term_in_every_document_still_gets_positive_weight():
    token_sets = [{"always"}, {"always"}, {"always"}]
    idf = compute_idf(token_sets)
    assert idf["always"] > 0.0


def test_tfidf_vector_scales_by_term_frequency():
    idf = {"x": 2.0}
    vector = tfidf_vector(["x", "x", "x"], idf)
    assert vector["x"] == 6.0


def test_tfidf_vector_omits_unknown_terms():
    vector = tfidf_vector(["unknown"], idf={})
    assert vector == {}


def test_cosine_similarity_identical_vectors_is_one():
    vector = {"a": 1.0, "b": 2.0}
    assert cosine_similarity(vector, vector) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity({"a": 1.0}, {"b": 1.0}) == 0.0


def test_cosine_similarity_empty_vector_is_zero():
    assert cosine_similarity({}, {"a": 1.0}) == 0.0


def test_cluster_candidates_tfidf_separates_frequent_boilerplate_from_rare_shared_topic():
    """The empirical DEMAND-001 failure mode: a phrase common across many
    unrelated authors (here, README-style "feedback/feature requests
    welcome" boilerplate) must not out-cluster a phrase shared by only a
    few authors about one genuine, specific problem (here, vendor insurance
    renewal tracking) - TF-IDF should suppress the frequent terms' weight
    enough that the boilerplate senders don't out-score the specific ones
    for each other."""
    boilerplate_authors = [f"b{i}" for i in range(1, 13)]
    boilerplate_sentences = [
        "Feedback and feature requests are always welcome here",
        "Feature requests and feedback welcome, thanks for trying it",
        "Any feedback or feature requests appreciated, open an issue",
        "Would love feedback, feature requests, or contributions",
        "Feel free to leave feedback or feature requests anytime",
        "Feedback, feature requests, bug reports - all welcome",
        "Feature requests welcome, feedback welcome, everything welcome",
        "Open to feedback and feature requests from anyone",
        "Feature requests and general feedback are both welcome",
        "Welcome any feedback, welcome any feature requests too",
        "Send feedback or feature requests whenever you like",
        "Feedback appreciated, feature requests especially welcome",
    ]
    real_topic_authors = ["v1", "v2", "v3", "v4", "v5"]
    real_topic_sentences = [
        "We still use a spreadsheet to track vendor insurance renewal deadlines",
        "I still use a spreadsheet to track vendor insurance renewal deadlines",
        "Our team still uses a spreadsheet to track vendor insurance renewal deadlines",
        "We still track vendor insurance renewal deadlines in a spreadsheet",
        "I still use spreadsheets to track vendor insurance renewal deadlines",
    ]

    candidates = [
        Candidate(i, 1000 + i, sentence, author=author)
        for i, (sentence, author) in enumerate(zip(boilerplate_sentences, boilerplate_authors), start=1)
    ]
    offset = len(candidates)
    candidates += [
        Candidate(offset + i, 2000 + i, sentence, author=author)
        for i, (sentence, author) in enumerate(zip(real_topic_sentences, real_topic_authors), start=1)
    ]

    clusters = cluster_candidates_tfidf(candidates)
    real_topic_ids = {2001, 2002, 2003, 2004, 2005}

    # the real-topic cluster forms with all 5 independent authors together
    real_cluster = next(c for c in clusters if {m.item_id for m in c.members} & real_topic_ids)
    assert real_topic_ids.issubset({m.item_id for m in real_cluster.members})
    assert real_cluster.independent_user_count == 5

    # no cluster reaches 5+ independent users on boilerplate alone
    boilerplate_item_ids = {1000 + i for i in range(1, 13)}
    for cluster in clusters:
        member_ids = {m.item_id for m in cluster.members}
        if member_ids & boilerplate_item_ids and not (member_ids & real_topic_ids):
            assert cluster.independent_user_count < 5
