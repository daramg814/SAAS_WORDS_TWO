from saas_words_two import db, text_filter


def test_matched_patterns_case_insensitive():
    assert "manual process" in text_filter.matched_patterns("This is a Manual Process for us.")
    assert text_filter.matched_patterns("everything is fine") == []


def test_split_sentences_strips_html_and_code_blocks():
    raw = "<p>We still use spreadsheets.</p><pre><code>def f(): pass</code></pre><p>It takes hours.</p>"
    sentences = text_filter.split_sentences(raw)
    assert "We still use spreadsheets." in sentences
    assert "It takes hours." in sentences
    assert not any("def f" in s for s in sentences)


def test_split_sentences_unescapes_html_entities():
    sentences = text_filter.split_sentences("Cost &gt; benefit and it&#x27;s too expensive.")
    assert any("too expensive" in s for s in sentences)
    assert not any("&gt;" in s or "&#x27;" in s for s in sentences)


def test_quote_lines_excluded():
    candidates = text_filter.extract_candidate_sentences(1, "> still use spreadsheets for this")
    assert candidates == []


def test_promo_sentences_excluded():
    candidates = text_filter.extract_candidate_sentences(
        1, "Check out our new product, it fixes the manual process issue!"
    )
    assert candidates == []


def test_url_only_sentences_excluded():
    candidates = text_filter.extract_candidate_sentences(1, "https://example.com/manual-process-tool")
    assert candidates == []


def test_extract_candidate_sentences_keeps_genuine_pain_points():
    text = (
        "Is there a tool for tracking vendor insurance? We still use spreadsheets and it takes hours "
        "every month. Nothing works well for our team size."
    )
    candidates = text_filter.extract_candidate_sentences(42, text)
    assert len(candidates) >= 3
    assert all(c.item_id == 42 for c in candidates)
    assert any("is there a tool" in c.matched_patterns for c in candidates)


def test_dedupe_candidates_removes_case_and_whitespace_variants():
    candidates = [
        text_filter.CandidateSentence(1, "We still use spreadsheets.", ("still use spreadsheets",)),
        text_filter.CandidateSentence(2, "we   still use spreadsheets.", ("still use spreadsheets",)),
        text_filter.CandidateSentence(3, "Totally different manual process.", ("manual process",)),
    ]
    deduped = text_filter.dedupe_candidates(candidates)
    assert len(deduped) == 2


def test_run_filter_pass_persists_to_candidate_sentences_table(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, title, text, fetched_at) VALUES "
        "(1, 'story', 'alice', 100, 'Ask HN: is there a tool for X', NULL, 't0')"
    )
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, title, text, fetched_at) VALUES "
        "(2, 'comment', 'bob', 101, NULL, 'We still use spreadsheets and it takes hours.', 't0')"
    )
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, title, text, deleted, fetched_at) VALUES "
        "(3, 'comment', 'carl', 102, NULL, 'is there a tool for X', 1, 't0')"
    )
    conn.commit()

    summary = text_filter.run_filter_pass(conn, created_at="2026-08-10T20:00:00+09:00")
    assert summary.source_items == 2  # deleted item excluded by the WHERE clause
    assert summary.candidates_after_dedupe >= 2

    rows = conn.execute("SELECT item_id, sentence, matched_patterns FROM candidate_sentences").fetchall()
    assert len(rows) == summary.candidates_after_dedupe
    item_ids = {row["item_id"] for row in rows}
    assert 3 not in item_ids
    conn.close()


def test_run_filter_pass_is_idempotent_replacing_prior_results(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, title, text, fetched_at) VALUES "
        "(1, 'story', 'alice', 100, 'is there a tool for X', NULL, 't0')"
    )
    conn.commit()
    text_filter.run_filter_pass(conn, created_at="t0")
    summary2 = text_filter.run_filter_pass(conn, created_at="t1")
    rows = conn.execute("SELECT COUNT(*) c FROM candidate_sentences").fetchone()
    assert rows["c"] == summary2.candidates_after_dedupe
    conn.close()


# ---------------------------------------------------------------------------
# is_generic_courtesy_sentence ("B안" companion filter - see the module
# comment above GENERIC_COURTESY_TOKENS in text_filter.py for why this
# exists alongside the clustering-algorithm change)
# ---------------------------------------------------------------------------


def test_is_generic_courtesy_sentence_true_for_short_boilerplate():
    assert text_filter.is_generic_courtesy_sentence("I'd love to hear your feedback and feature requests!")
    assert text_filter.is_generic_courtesy_sentence("Feedback and feature requests are welcome.")
    assert text_filter.is_generic_courtesy_sentence("Any feature requests?")
    assert text_filter.is_generic_courtesy_sentence("Open to feedback and feature requests from anyone.")


def test_is_generic_courtesy_sentence_false_for_specific_content():
    assert not text_filter.is_generic_courtesy_sentence(
        "We still use spreadsheets to track vendor insurance renewal deadlines."
    )
    assert not text_filter.is_generic_courtesy_sentence(
        "Is there a tool for backing up my Android phone ROM before flashing Cyanogenmod?"
    )


def test_is_generic_courtesy_sentence_false_when_too_long_even_if_generic_words_present():
    # a long sentence padded with generic words but with real specific
    # content should not be caught by the length-gated filter
    sentence = (
        "We would love your feedback and feature requests on our new vendor insurance "
        "renewal tracking dashboard that we built after months of manual spreadsheet work"
    )
    assert not text_filter.is_generic_courtesy_sentence(sentence)


def test_is_generic_courtesy_sentence_false_for_empty_content():
    assert not text_filter.is_generic_courtesy_sentence("")
    assert not text_filter.is_generic_courtesy_sentence("a an the is")


def test_extract_candidate_sentences_excludes_generic_courtesy_text():
    candidates = text_filter.extract_candidate_sentences(
        1, "I'd love to hear your feedback and feature requests! Also, we still use spreadsheets for tracking."
    )
    sentences = [c.sentence for c in candidates]
    assert not any("feedback" in s.lower() for s in sentences)
    assert any("spreadsheets" in s.lower() for s in sentences)
