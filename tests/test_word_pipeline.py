import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from saas_words_two import judgment, run_state, word_pipeline
from saas_words_two.keyword_metrics_client import (
    KeywordMetricRecord,
    KeywordMetricsBudgetExceeded,
    KeywordMetricsCredentialsError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class StubKeywordMetricsClient:
    """By default every word passes the gate (avg_monthly_searches huge,
    competition_index exactly 0). Tests of the gate itself override
    records_by_title/default_factory/raise_error."""

    def __init__(self, records_by_title=None, raise_error=None, default_factory=None):
        self.records_by_title = records_by_title or {}
        self.raise_error = raise_error
        self.default_factory = default_factory or (
            lambda word: KeywordMetricRecord(
                word=word, avg_monthly_searches=999999, competition="LOW", competition_index=0, api_status="success"
            )
        )
        self.fetched: list[str] = []

    def fetch_metrics(self, words):
        if self.raise_error is not None:
            raise self.raise_error
        self.fetched.extend(words)
        return [self.records_by_title.get(word, self.default_factory(word)) for word in words]


@pytest.fixture(autouse=True)
def default_keyword_metrics_stub(monkeypatch):
    monkeypatch.setattr(word_pipeline, "_keyword_metrics_settings", lambda project_root: (1000, 0, None, Path(".")))
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: StubKeywordMetricsClient())


def make_options(tmp_path, mode="qa", round_size=5, **overrides):
    return word_pipeline.RunOptions(mode=mode, project_root=tmp_path, round_size=round_size, **overrides)


def approve_all_response(run_dir, round_no=1):
    request = json.loads(
        (run_dir / "judgment" / f"review_titles_round{round_no}_request.json").read_text(encoding="utf-8")
    )
    decisions = [{"title": item["title"], "approve": True} for item in request["items"]]
    judgment.write_response(run_dir, "review_titles", decisions, round_no=round_no, judged_at="t1")


def reject_all_response(run_dir, round_no=1):
    request = json.loads(
        (run_dir / "judgment" / f"review_titles_round{round_no}_request.json").read_text(encoding="utf-8")
    )
    decisions = [{"title": item["title"], "approve": False, "reason": "too abstract"} for item in request["items"]]
    judgment.write_response(run_dir, "review_titles", decisions, round_no=round_no, judged_at="t1")


def approve_one_response(run_dir, round_no=1):
    request = json.loads(
        (run_dir / "judgment" / f"review_titles_round{round_no}_request.json").read_text(encoding="utf-8")
    )
    decisions = [{"title": item["title"], "approve": i == 0} for i, item in enumerate(request["items"])]
    judgment.write_response(run_dir, "review_titles", decisions, round_no=round_no, judged_at="t1")


def empty_expand_word_bank_response(run_dir, round_no=1):
    judgment.write_response(run_dir, "expand_word_bank", [], round_no=round_no, judged_at="t1")


# ---------------------------------------------------------------------------
# RunOptions
# ---------------------------------------------------------------------------


def test_run_options_rejects_bad_mode(tmp_path):
    with pytest.raises(ValueError):
        word_pipeline.RunOptions(mode="bogus", project_root=tmp_path).validate()


def test_run_options_rejects_non_positive_round_size(tmp_path):
    with pytest.raises(ValueError):
        word_pipeline.RunOptions(mode="qa", project_root=tmp_path, round_size=0).validate()


def test_run_options_accepts_no_round_size(tmp_path):
    word_pipeline.RunOptions(mode="production", project_root=tmp_path).validate()


# ---------------------------------------------------------------------------
# load_state - backlog sweep (2026-08-18: AI-approved-but-KP-unresolved
# candidates from the ledger must be picked up automatically, not lost)
# ---------------------------------------------------------------------------


def test_stage_load_state_sweeps_ai_approved_kp_unresolved_into_backlog(tmp_path):
    word_pipeline._append_generated_ledger_rows(
        tmp_path,
        [
            {"title": "Vendor Guard", "industry": "finance", "ai_approved": "True", "ai_reason": "", "judged_at": "t0"},
            {"title": "Claim Tracker", "industry": "insurance", "ai_approved": "False", "ai_reason": "too abstract", "judged_at": "t0"},
        ],
    )
    state = word_pipeline._load_or_create_state(make_options(tmp_path, run_id="QA-20260818-000000-KST"))
    word_pipeline._stage_load_state(tmp_path, None, state)

    assert state.context["backlog"] == [{"title": "Vendor Guard", "industry": "finance"}]


def test_stage_load_state_excludes_kp_resolved_from_backlog(tmp_path):
    word_pipeline._append_generated_ledger_rows(
        tmp_path,
        [{"title": "Vendor Guard", "industry": "finance", "ai_approved": "True", "ai_reason": "", "judged_at": "t0"}],
    )
    word_pipeline._append_metrics_cache_rows(
        tmp_path,
        [{"title": "Vendor Guard", "avg_monthly_searches": 2000, "competition_index": 0, "api_status": "success", "gate_passed": "True", "checked_at": "t0"}],
    )
    state = word_pipeline._load_or_create_state(make_options(tmp_path, run_id="QA-20260818-000000-KST"))
    word_pipeline._stage_load_state(tmp_path, None, state)

    assert state.context["backlog"] == []


# ---------------------------------------------------------------------------
# generate_and_review_titles - single-round model (2026-08-18)
# ---------------------------------------------------------------------------


def test_generate_and_review_titles_no_candidates_no_backlog_is_capability_stagnation(tmp_path, monkeypatch):
    monkeypatch.setattr(word_pipeline.word_generation, "generate_combinations", lambda *a, **k: [])
    options = make_options(tmp_path, run_id="QA-20260818-000000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    # empty candidates first trigger one self-expansion judgment round (2026-08-18)
    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    empty_expand_word_bank_response(run_dir)

    with pytest.raises(word_pipeline.RetryRequired) as excinfo:
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert excinfo.value.status == "CAPABILITY_STAGNATION"
    assert state.status == "CAPABILITY_STAGNATION"


def test_generate_and_review_titles_no_candidates_but_backlog_skips_judgment(tmp_path, monkeypatch):
    monkeypatch.setattr(word_pipeline.word_generation, "generate_combinations", lambda *a, **k: [])
    word_pipeline._append_generated_ledger_rows(
        tmp_path,
        [{"title": "Vendor Guard", "industry": "finance", "ai_approved": "True", "ai_reason": "", "judged_at": "t0"}],
    )
    options = make_options(tmp_path, run_id="QA-20260818-000000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    # empty candidates first trigger one self-expansion judgment round (2026-08-18)
    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    empty_expand_word_bank_response(run_dir)

    word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)  # no further JudgmentRequired
    assert state.status == "DONE"
    assert [c["title"] for c in state.context["approved"]] == ["Vendor Guard"]
    assert state.context["round_stats"]["backlog_carried"] == 1
    assert state.context["round_stats"]["generated"] == 0


# ---------------------------------------------------------------------------
# 자가확장 단어뱅크 (2026-08-18)
# ---------------------------------------------------------------------------


def test_merged_word_bank_combines_static_and_dynamic_pools(tmp_path, monkeypatch):
    monkeypatch.setattr(word_pipeline.word_bank, "DOMAIN_WORDS", {"finance": ("Ledger",)})
    monkeypatch.setattr(word_pipeline.word_bank, "FUNCTION_WORDS", ("Guard",))
    word_pipeline._append_word_bank_expansion_rows(
        tmp_path,
        [
            {"type": "domain", "word": "Invoice", "industry": "finance", "added_at": "t0", "added_by_run_id": "r0"},
            {"type": "domain", "word": "Claim", "industry": "insurance", "added_at": "t0", "added_by_run_id": "r0"},
            {"type": "function", "word": "Tracker", "industry": "", "added_at": "t0", "added_by_run_id": "r0"},
        ],
    )
    domain_words, function_words = word_pipeline._merged_word_bank(tmp_path)
    assert domain_words["finance"] == ("Ledger", "Invoice")
    assert domain_words["insurance"] == ("Claim",)
    assert function_words == ("Guard", "Tracker")


def test_append_word_bank_expansion_rows_dedupes_exact_and_across_calls(tmp_path):
    row = {"type": "function", "word": "Tracker", "industry": "", "added_at": "t0", "added_by_run_id": "r0"}
    word_pipeline._append_word_bank_expansion_rows(tmp_path, [row, dict(row)])
    word_pipeline._append_word_bank_expansion_rows(tmp_path, [dict(row, added_by_run_id="r1")])
    with word_pipeline._word_bank_expansions_path(tmp_path).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["added_by_run_id"] == "r0"  # first-seen wins, not overwritten


def test_consume_word_bank_expansion_drops_invalid_and_keeps_valid():
    response = {
        "decisions": [
            {"type": "domain", "word": "Invoice", "industry": "finance"},
            {"type": "function", "word": "Tracker"},
            {"type": "domain", "word": "no industry given"},  # missing industry -> dropped
            {"type": "function", "word": "not a word!"},  # not a single alpha token -> dropped
            {"type": "bogus", "word": "Whatever"},  # invalid type -> dropped
        ]
    }
    rows = word_pipeline._consume_word_bank_expansion(response, "RUN-1", "t0")
    assert [r["word"] for r in rows] == ["Invoice", "Tracker"]
    assert rows[0]["industry"] == "finance"
    assert rows[1]["industry"] == ""


def test_generate_and_review_titles_self_expands_when_static_bank_exhausted(tmp_path, monkeypatch):
    monkeypatch.setattr(word_pipeline.word_bank, "DOMAIN_WORDS", {"finance": ("Ledger",)})
    monkeypatch.setattr(word_pipeline.word_bank, "FUNCTION_WORDS", ("Guard",))
    # pre-seed the ledger so the tiny static bank's one combo is already spent
    word_pipeline._append_generated_ledger_rows(
        tmp_path,
        [{"title": "Ledger Guard", "industry": "finance", "ai_approved": "True", "ai_reason": "", "judged_at": "t0"}],
    )
    options = make_options(tmp_path, run_id="QA-20260818-000002-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert excinfo.value.stage == "expand_word_bank"
    run_state.save(tmp_path, state)

    judgment.write_response(
        run_dir,
        "expand_word_bank",
        [
            {"type": "domain", "word": "Invoice", "industry": "finance"},
            {"type": "function", "word": "Tracker"},
        ],
        round_no=1,
        judged_at="t1",
    )

    with pytest.raises(judgment.JudgmentRequired) as excinfo2:
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert excinfo2.value.stage == "review_titles"
    run_state.save(tmp_path, state)

    request = json.loads((run_dir / "judgment" / "review_titles_round1_request.json").read_text(encoding="utf-8"))
    generated_titles = {item["title"] for item in request["items"]}
    assert "Ledger Guard" not in generated_titles  # already-ledgered combo not regenerated
    assert generated_titles  # the newly proposed words produced fresh combos

    approve_all_response(run_dir)
    word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert state.status == "DONE"

    domain_words, function_words = word_pipeline._merged_word_bank(tmp_path)
    assert "Invoice" in domain_words["finance"]
    assert "Tracker" in function_words


def test_generate_and_review_titles_pauses_for_judgment_then_completes_on_approve(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260818-000000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_all_response(run_dir)

    word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert state.status == "DONE"
    assert len(state.context["approved"]) == 5

    ledger = word_pipeline._load_generated_ledger(tmp_path)
    assert len(ledger) == 5
    assert all(row["ai_approved"] == "True" for row in ledger.values())


def test_generate_and_review_titles_rejected_candidates_recorded_but_not_regenerated(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260818-000000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    request = json.loads((run_dir / "judgment" / "review_titles_round1_request.json").read_text(encoding="utf-8"))
    rejected_titles = {item["title"] for item in request["items"]}
    run_state.save(tmp_path, state)
    reject_all_response(run_dir)

    word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert state.context["approved"] == []

    ledger = word_pipeline._load_generated_ledger(tmp_path)
    assert set(ledger.keys()) == {word_pipeline.normalize_title(t) for t in rejected_titles}
    assert all(row["ai_approved"] == "False" for row in ledger.values())

    excluded = word_pipeline._excluded_normalized(tmp_path, state)
    assert {word_pipeline.normalize_title(t) for t in rejected_titles} <= excluded


def test_ledger_entries_never_regenerated_across_separate_runs(tmp_path):
    options1 = make_options(tmp_path, run_id="QA-20260818-000000-KST")
    state1 = word_pipeline._load_or_create_state(options1)
    word_pipeline._stage_load_state(tmp_path, options1, state1)
    run_dir1 = word_pipeline._run_dir(tmp_path, state1)
    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options1, state1)
    run_state.save(tmp_path, state1)
    approve_all_response(run_dir1)
    word_pipeline._stage_generate_and_review_titles(tmp_path, options1, state1)
    first_run_titles = {word_pipeline.normalize_title(c["title"]) for c in state1.context["approved"]}

    options2 = make_options(tmp_path, run_id="QA-20260818-000100-KST", round_size=200)
    state2 = word_pipeline._load_or_create_state(options2)
    word_pipeline._stage_load_state(tmp_path, options2, state2)
    run_dir2 = word_pipeline._run_dir(tmp_path, state2)
    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options2, state2)
    request2 = json.loads((run_dir2 / "judgment" / "review_titles_round1_request.json").read_text(encoding="utf-8"))
    second_run_titles = {word_pipeline.normalize_title(item["title"]) for item in request2["items"]}

    assert first_run_titles.isdisjoint(second_run_titles)


def test_generate_and_review_titles_budget_exceeded_is_retrying(tmp_path, monkeypatch):
    stub = StubKeywordMetricsClient(raise_error=KeywordMetricsBudgetExceeded("out of budget"))
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    options = make_options(tmp_path, run_id="QA-20260818-000000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_all_response(run_dir)

    with pytest.raises(word_pipeline.RetryRequired) as excinfo:
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert excinfo.value.status == "RETRYING"
    assert state.status == "RETRYING"
    # the approvals are already durably recorded in the ledger even though KP
    # never resolved them - the NEXT run's load_state backlog sweep will pick
    # them up automatically (see test_stage_load_state_sweeps_...).
    ledger = word_pipeline._load_generated_ledger(tmp_path)
    assert len(ledger) == 5
    assert all(row["ai_approved"] == "True" for row in ledger.values())


# ---------------------------------------------------------------------------
# Keyword Planner filter gate (unchanged logic, GKP-001)
# ---------------------------------------------------------------------------


def test_keyword_metrics_gate_rejects_null_competition_index_regardless_of_searches(tmp_path, monkeypatch):
    stub = StubKeywordMetricsClient(
        default_factory=lambda word: KeywordMetricRecord(
            word=word, avg_monthly_searches=999999, competition=None, competition_index=None, api_status="failed"
        )
    )
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    options = make_options(tmp_path, run_id="QA-20260818-000000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_all_response(run_dir)

    word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert state.context["approved"] == []


def test_keyword_metrics_gate_passes_when_both_conditions_met(tmp_path, monkeypatch):
    stub = StubKeywordMetricsClient(
        default_factory=lambda word: KeywordMetricRecord(
            word=word, avg_monthly_searches=1000, competition="LOW", competition_index=0, api_status="success"
        )
    )
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    options = make_options(tmp_path, run_id="QA-20260818-000000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_all_response(run_dir)

    word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert len(state.context["approved"]) == 5


def test_keyword_metrics_gate_writes_evidence_for_pass_and_fail(tmp_path, monkeypatch):
    def alternate_pass_fail(word):
        passes = hash(word) % 2 == 0
        return KeywordMetricRecord(
            word=word,
            avg_monthly_searches=5000 if passes else 5,
            competition="LOW" if passes else "HIGH",
            competition_index=0 if passes else 50,
            api_status="success",
        )

    stub = StubKeywordMetricsClient(default_factory=alternate_pass_fail)
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    options = make_options(tmp_path, round_size=10, run_id="QA-20260818-000000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_all_response(run_dir)

    word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)

    evidence_path = tmp_path / "output" / "_pipeline" / "intermediate" / f"{state.run_id}_keyword_metrics_evidence.jsonl"
    assert evidence_path.exists()
    entries = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    assert entries
    assert any(e["passed"] for e in entries)
    assert any(not e["passed"] for e in entries)
    for entry in entries:
        assert {"title", "avg_monthly_searches", "competition_index", "api_status", "passed", "checked_at"} <= entry.keys()


# ---------------------------------------------------------------------------
# Cumulative keyword-metrics cache (문서②③, unchanged from pre-2026-08-18)
# ---------------------------------------------------------------------------


def write_cache_row(tmp_path, *, title, avg, competition_index, api_status, gate_passed, checked_at="t0"):
    row = {
        "title": title,
        "avg_monthly_searches": "" if avg is None else avg,
        "competition_index": "" if competition_index is None else competition_index,
        "api_status": api_status,
        "gate_passed": str(gate_passed),
        "checked_at": checked_at,
    }
    word_pipeline._append_metrics_cache_rows(tmp_path, [row])


def test_record_to_cache_row_serializes_none_as_empty_string():
    from saas_words_two.keyword_metrics_client import KeywordMetricRecord

    record = KeywordMetricRecord(word="Ledger Pilot", avg_monthly_searches=None, competition=None, competition_index=None, api_status="failed")
    row = word_pipeline._record_to_cache_row("Ledger Pilot", record, gate_passed=False, checked_at="t0")
    assert row == {
        "title": "Ledger Pilot", "avg_monthly_searches": "", "competition_index": "",
        "api_status": "failed", "gate_passed": "False", "checked_at": "t0",
    }


def test_append_metrics_cache_rows_writes_full_table_and_pass_only_subset(tmp_path):
    rows = [
        {"title": "Ledger Pilot", "avg_monthly_searches": 2000, "competition_index": 0, "api_status": "success", "gate_passed": "True", "checked_at": "t0"},
        {"title": "Claim Sentry", "avg_monthly_searches": 10, "competition_index": 50, "api_status": "success", "gate_passed": "False", "checked_at": "t0"},
    ]
    word_pipeline._append_metrics_cache_rows(tmp_path, rows)

    full = word_pipeline._load_metrics_cache(tmp_path)
    assert set(full.keys()) == {"ledger pilot", "claim sentry"}

    passed_path = word_pipeline._metrics_passed_path(tmp_path)
    passed_content = passed_path.read_text(encoding="utf-8")
    assert "Ledger Pilot" in passed_content
    assert "Claim Sentry" not in passed_content


def test_append_metrics_cache_rows_writes_lf_only_no_crlf(tmp_path):
    # regression: csv.DictWriter defaults to \r\n, which survives into the
    # buffer untouched by atomic_write_text's newline="\n" (it only affects
    # how \n in the string is translated on write, not \r already present) -
    # must pass lineterminator="\n" explicitly to csv.DictWriter itself.
    word_pipeline._append_metrics_cache_rows(
        tmp_path, [{"title": "Ledger Pilot", "avg_monthly_searches": 2000, "competition_index": 0, "api_status": "success", "gate_passed": "True", "checked_at": "t0"}]
    )
    cache_bytes = word_pipeline._metrics_cache_path(tmp_path).read_bytes()
    passed_bytes = word_pipeline._metrics_passed_path(tmp_path).read_bytes()
    assert b"\r\n" not in cache_bytes
    assert b"\r\n" not in passed_bytes


def test_append_generated_ledger_rows_writes_lf_only_no_crlf(tmp_path):
    word_pipeline._append_generated_ledger_rows(
        tmp_path, [{"title": "Vendor Guard", "industry": "finance", "ai_approved": "True", "ai_reason": "", "judged_at": "t0"}]
    )
    ledger_bytes = word_pipeline._generated_ledger_path(tmp_path).read_bytes()
    assert b"\r\n" not in ledger_bytes


def test_append_metrics_cache_rows_merges_without_duplicating(tmp_path):
    word_pipeline._append_metrics_cache_rows(
        tmp_path, [{"title": "Ledger Pilot", "avg_monthly_searches": 2000, "competition_index": 0, "api_status": "success", "gate_passed": "True", "checked_at": "t0"}]
    )
    word_pipeline._append_metrics_cache_rows(
        tmp_path, [{"title": "Claim Sentry", "avg_monthly_searches": 10, "competition_index": 50, "api_status": "success", "gate_passed": "False", "checked_at": "t1"}]
    )
    full = word_pipeline._load_metrics_cache(tmp_path)
    assert len(full) == 2


def test_apply_keyword_metrics_filter_reuses_cache_and_skips_api_for_cached_titles(tmp_path, monkeypatch):
    write_cache_row(tmp_path, title="Ledger Pilot", avg=2000, competition_index=0, api_status="success", gate_passed=True)
    stub = StubKeywordMetricsClient()
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    state = word_pipeline._load_or_create_state(make_options(tmp_path, run_id="QA-20260818-000000-KST"))
    candidates = [
        {"title": "Ledger Pilot", "industry": "finance"},
        {"title": "Claim Sentry", "industry": "insurance"},
    ]
    passed = word_pipeline._apply_keyword_metrics_filter(tmp_path, state, candidates)

    assert stub.fetched == ["Claim Sentry"]
    assert {c["title"] for c in passed} == {"Ledger Pilot", "Claim Sentry"}


# ---------------------------------------------------------------------------
# 문서① 원시 생성 ledger
# ---------------------------------------------------------------------------


def test_append_generated_ledger_rows_merges_without_duplicating(tmp_path):
    word_pipeline._append_generated_ledger_rows(
        tmp_path, [{"title": "Vendor Guard", "industry": "finance", "ai_approved": "True", "ai_reason": "", "judged_at": "t0"}]
    )
    word_pipeline._append_generated_ledger_rows(
        tmp_path, [{"title": "Claim Tracker", "industry": "insurance", "ai_approved": "False", "ai_reason": "abstract", "judged_at": "t1"}]
    )
    ledger = word_pipeline._load_generated_ledger(tmp_path)
    assert len(ledger) == 2


def test_export_generated_ledger_snapshot_writes_dated_copy(tmp_path):
    word_pipeline._append_generated_ledger_rows(
        tmp_path, [{"title": "Vendor Guard", "industry": "finance", "ai_approved": "True", "ai_reason": "", "judged_at": "t0"}]
    )
    when = datetime(2026, 8, 18, 10, 0, 0)
    word_pipeline._export_generated_ledger_snapshot(tmp_path, when)

    snap = word_pipeline._history_snapshots_dir(tmp_path) / "generated_candidates_20260818_100000_KST.csv"
    assert snap.exists()
    assert "Vendor Guard" in snap.read_text(encoding="utf-8")


def test_export_generated_ledger_snapshot_noop_when_ledger_missing(tmp_path):
    when = datetime(2026, 8, 18, 10, 0, 0)
    word_pipeline._export_generated_ledger_snapshot(tmp_path, when)
    assert not word_pipeline._history_snapshots_dir(tmp_path).exists()


# ---------------------------------------------------------------------------
# 문서④ OK 단어 리스트 - 마스터(passed_words_latest.txt) + 날짜시간 스냅샷.
# words.txt는 더 이상 스냅샷 소스가 아니다(2026-08-18).
# ---------------------------------------------------------------------------

FIXED_WHEN = datetime(2026, 8, 18, 21, 30, 0)


def test_export_final_words_writes_dated_snapshot_and_latest_master(tmp_path):
    write_cache_row(tmp_path, title="Ledger Pilot", avg=2000, competition_index=0, api_status="success", gate_passed=True)
    write_cache_row(tmp_path, title="Claim Sentry", avg=3000, competition_index=0, api_status="success", gate_passed=True)

    word_pipeline._export_final_words_and_history_snapshots(tmp_path, FIXED_WHEN)

    dated = word_pipeline._final_words_dir(tmp_path) / "passed_words_20260818_213000_KST.txt"
    latest = word_pipeline._final_words_dir(tmp_path) / "passed_words_latest.txt"
    assert dated.read_text(encoding="utf-8") == "Claim Sentry\nLedger Pilot\n"
    assert latest.read_text(encoding="utf-8") == "Claim Sentry\nLedger Pilot\n"


def test_export_final_words_latest_master_overwritten_each_call(tmp_path):
    write_cache_row(tmp_path, title="Ledger Pilot", avg=2000, competition_index=0, api_status="success", gate_passed=True)
    word_pipeline._export_final_words_and_history_snapshots(tmp_path, FIXED_WHEN)
    write_cache_row(tmp_path, title="Claim Sentry", avg=3000, competition_index=0, api_status="success", gate_passed=True)
    word_pipeline._export_final_words_and_history_snapshots(tmp_path, datetime(2026, 8, 18, 21, 31, 0))

    latest = word_pipeline._final_words_dir(tmp_path) / "passed_words_latest.txt"
    assert latest.read_text(encoding="utf-8") == "Claim Sentry\nLedger Pilot\n"  # both, not just the second


def test_export_final_words_skipped_when_no_passed_cache_yet(tmp_path):
    word_pipeline._export_final_words_and_history_snapshots(tmp_path, FIXED_WHEN)
    assert not word_pipeline._final_words_dir(tmp_path).exists()


def test_export_history_snapshots_copies_live_cache_files_with_timestamped_names(tmp_path):
    write_cache_row(tmp_path, title="Ledger Pilot", avg=2000, competition_index=0, api_status="success", gate_passed=True)

    word_pipeline._export_final_words_and_history_snapshots(tmp_path, FIXED_WHEN)

    snap_dir = word_pipeline._history_snapshots_dir(tmp_path)
    assert (snap_dir / "keyword_metrics_cache_20260818_213000_KST.csv").exists()
    assert (snap_dir / "keyword_metrics_passed_20260818_213000_KST.csv").exists()
    assert not (snap_dir / "words_20260818_213000_KST.txt").exists()  # words.txt no longer exists at all


def test_apply_keyword_metrics_filter_uses_cache_and_api(tmp_path, monkeypatch):
    # 스냅샷 생성은 호출자의 책임(finally 블록) - 함수는 캐시와 evidence만 담당
    write_cache_row(tmp_path, title="Ledger Pilot", avg=2000, competition_index=0, api_status="success", gate_passed=True)
    stub = StubKeywordMetricsClient()
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)
    state = word_pipeline._load_or_create_state(make_options(tmp_path, run_id="QA-20260818-000000-KST"))

    # 캐시에 있는 것과 없는 것 함께 테스트
    passed = word_pipeline._apply_keyword_metrics_filter(tmp_path, state, [
        {"title": "Ledger Pilot", "industry": "finance"},  # 캐시 hit
        {"title": "Claim Sentry", "industry": "insurance"}  # API 호출
    ])

    # 둘 다 통과 기준 만족
    assert len(passed) == 2
    titles = {p["title"] for p in passed}
    assert titles == {"Ledger Pilot", "Claim Sentry"}


# ---------------------------------------------------------------------------
# update_memory_and_git_checkpoint
# ---------------------------------------------------------------------------


def test_stage_update_memory_and_git_checkpoint_writes_handoff_and_checkpoints(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        word_pipeline, "_run_or_raise", lambda project_root, script_name, *extra: calls.append(script_name)
    )
    options = make_options(tmp_path, run_id="QA-20260818-000000-KST")
    state = word_pipeline._load_or_create_state(options)
    state.context["approved"] = [{"title": "Vendor Guard", "industry": "finance"}]
    state.context["round_stats"] = {"generated": 5, "ai_approved": 1, "backlog_carried": 0, "kp_passed": 1}

    word_pipeline._stage_update_memory_and_git_checkpoint(tmp_path, options, state)

    assert "git_checkpoint.py" in calls
    handoff = (tmp_path / "memory" / "HANDOFF.md").read_text(encoding="utf-8")
    assert "DONE" in handoff
    assert "1개" in handoff  # kp_passed count appears somewhere in the summary


# ---------------------------------------------------------------------------
# End-to-end: run_pipeline via the 3-stage orchestration
# ---------------------------------------------------------------------------


def test_run_pipeline_completes_after_judgment_response_provided(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        word_pipeline, "_run_or_raise", lambda project_root, script_name, *extra: calls.append(script_name)
    )
    options = make_options(tmp_path, run_id="QA-20260818-000000-KST")

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        word_pipeline.run_pipeline(options)
    run_dir = excinfo.value.request_path.parent.parent
    approve_all_response(run_dir)

    result = word_pipeline.run_pipeline(word_pipeline.RunOptions(mode="qa", project_root=tmp_path, round_size=5, resume=True, run_id=options.run_id))
    assert result == 0
    final_state = run_state.load(tmp_path, options.run_id)
    assert final_state.status == "DONE"
