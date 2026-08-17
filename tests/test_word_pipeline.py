import csv
import json
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
    competition_index exactly 0) so existing round-loop tests keep their
    pre-GKP-001 "judgment approval == final approval" semantics. Tests of the
    gate itself override records_by_title or raise_error."""

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


def make_options(tmp_path, mode="qa", target_count=5, **overrides):
    return word_pipeline.RunOptions(mode=mode, target_count=target_count, project_root=tmp_path, **overrides)


def with_qa_history_snapshot(tmp_path, state, existing_lines=()):
    snapshot_path = tmp_path / "output" / "_pipeline" / "qa" / state.run_id / "qa_history_snapshot.txt"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(existing_lines) + "\n" if existing_lines else ""
    snapshot_path.write_text(content, encoding="utf-8")
    state.context["qa_history_snapshot_path"] = str(snapshot_path)


def approve_all_response(run_dir, run_id, round_no):
    request = json.loads(
        (run_dir / "judgment" / f"review_titles_round{round_no}_request.json").read_text(encoding="utf-8")
    )
    decisions = [{"title": item["title"], "approve": True} for item in request["items"]]
    judgment.write_response(run_dir, "review_titles", decisions, round_no=round_no, judged_at="t1")


def reject_all_response(run_dir, run_id, round_no):
    request = json.loads(
        (run_dir / "judgment" / f"review_titles_round{round_no}_request.json").read_text(encoding="utf-8")
    )
    decisions = [{"title": item["title"], "approve": False, "reason": "too abstract"} for item in request["items"]]
    judgment.write_response(run_dir, "review_titles", decisions, round_no=round_no, judged_at="t1")


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------


def test_stage_load_state_snapshots_history_for_qa(tmp_path):
    history_path = tmp_path / "output" / "deliverables" / "history" / "words.txt"
    history_path.parent.mkdir(parents=True)
    history_path.write_text("Vendor Guard\n", encoding="utf-8")

    options = make_options(tmp_path, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)

    snapshot_path = tmp_path / "output" / "_pipeline" / "qa" / state.run_id / "qa_history_snapshot.txt"
    assert snapshot_path.exists()
    assert "Vendor Guard" in snapshot_path.read_text(encoding="utf-8")


def test_stage_load_state_noop_for_production(tmp_path):
    options = make_options(tmp_path, mode="production", target_count=500, run_id="RUN-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    assert "qa_history_snapshot_path" not in state.context


def test_round_size_override_controls_round1_candidate_count(tmp_path):
    # default first_round_size(100) = max(round(100*1.6), 100+20) = 160 - the
    # override must replace that, not add to it (GKP-001 low pass-rate fix).
    options = make_options(tmp_path, target_count=100, run_id="QA-20260817-200000-KST", round_size=500)
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)

    request = json.loads((run_dir / "judgment" / "review_titles_round1_request.json").read_text(encoding="utf-8"))
    assert len(request["items"]) == 500


def test_round_size_override_also_controls_round2_candidate_count(tmp_path):
    # GKP-001: the old behavior only overrode round 1 - round 2+ fell back to
    # next_round_size(shortfall), a tiny batch that's statistically ~0% likely
    # to pass anything once the downstream gate's pass rate is ~1%. A real run
    # hit exactly this: a 27-candidate round 2 (shortfall*2) yielded 0 passes.
    # round_size must apply uniformly to every round, not just the first.
    options = make_options(tmp_path, target_count=100, run_id="QA-20260817-200000-KST", round_size=500)
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    reject_all_response(run_dir, state.run_id, 1)  # 0 approved -> forces round 2

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)

    request = json.loads((run_dir / "judgment" / "review_titles_round2_request.json").read_text(encoding="utf-8"))
    assert len(request["items"]) == 500  # not next_round_size(100) == 200


# ---------------------------------------------------------------------------
# generate_and_review_titles
# ---------------------------------------------------------------------------


def test_generate_and_review_titles_completes_in_one_round_when_all_approved(tmp_path):
    options = make_options(tmp_path, target_count=5, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_all_response(run_dir, state.run_id, 1)

    word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert len(state.context["approved"]) >= 5


def test_generate_and_review_titles_second_round_after_rejections(tmp_path):
    options = make_options(tmp_path, target_count=5, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    reject_all_response(run_dir, state.run_id, 1)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    assert state.context["title_round"] == 2
    approve_all_response(run_dir, state.run_id, 2)

    word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert len(state.context["approved"]) >= 5


def test_generate_and_review_titles_zero_progress_is_capability_stagnation(tmp_path):
    options = make_options(tmp_path, target_count=5, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    for round_no in range(1, word_pipeline.word_generation.MAX_ROUNDS + 1):
        with pytest.raises(judgment.JudgmentRequired):
            word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
        run_state.save(tmp_path, state)
        reject_all_response(run_dir, state.run_id, round_no)

    with pytest.raises(word_pipeline.RetryRequired) as excinfo:
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert state.status == "CAPABILITY_STAGNATION"
    assert excinfo.value.status == "CAPABILITY_STAGNATION"
    intermediate = tmp_path / "output" / "_pipeline" / "intermediate" / f"{state.run_id}_shortfall_titles.txt"
    assert intermediate.exists()


def approve_one_response(run_dir, run_id, round_no):
    request = json.loads(
        (run_dir / "judgment" / f"review_titles_round{round_no}_request.json").read_text(encoding="utf-8")
    )
    decisions = [
        {"title": item["title"], "approve": i == 0}
        for i, item in enumerate(request["items"])
    ]
    judgment.write_response(run_dir, "review_titles", decisions, round_no=round_no, judged_at="t1")


def test_generate_and_review_titles_partial_progress_stays_retrying(tmp_path):
    options = make_options(tmp_path, target_count=10, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    # round 1: approve exactly one candidate - real progress, but nowhere near target
    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_one_response(run_dir, state.run_id, 1)

    for round_no in range(2, word_pipeline.word_generation.MAX_ROUNDS + 1):
        with pytest.raises(judgment.JudgmentRequired):
            word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
        run_state.save(tmp_path, state)
        reject_all_response(run_dir, state.run_id, round_no)

    with pytest.raises(word_pipeline.RetryRequired) as excinfo:
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert state.status == "RETRYING"
    assert excinfo.value.status == "RETRYING"
    assert len(state.context["approved"]) == 1


# ---------------------------------------------------------------------------
# Keyword Planner filter gate (GKP-001) - applied inside the round loop, on
# top of AI judgment approval.
# ---------------------------------------------------------------------------


def test_keyword_metrics_gate_rejects_null_competition_index_regardless_of_searches(tmp_path, monkeypatch):
    # NULL competition_index means "no data" (dead word), never "zero
    # competition" - must reject even with a huge avg_monthly_searches.
    stub = StubKeywordMetricsClient(
        default_factory=lambda word: KeywordMetricRecord(
            word=word, avg_monthly_searches=999999, competition=None, competition_index=None, api_status="failed"
        )
    )
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    options = make_options(tmp_path, target_count=5, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    for round_no in range(1, word_pipeline.word_generation.MAX_ROUNDS + 1):
        with pytest.raises(judgment.JudgmentRequired):
            word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
        run_state.save(tmp_path, state)
        approve_all_response(run_dir, state.run_id, round_no)

    with pytest.raises(word_pipeline.RetryRequired) as excinfo:
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert state.status == "CAPABILITY_STAGNATION"
    assert excinfo.value.status == "CAPABILITY_STAGNATION"
    assert state.context["approved"] == []


def test_keyword_metrics_gate_rejects_below_search_volume_threshold(tmp_path, monkeypatch):
    stub = StubKeywordMetricsClient(
        default_factory=lambda word: KeywordMetricRecord(
            word=word, avg_monthly_searches=10, competition="LOW", competition_index=0, api_status="success"
        )
    )
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    options = make_options(tmp_path, target_count=5, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_all_response(run_dir, state.run_id, 1)

    for round_no in range(2, word_pipeline.word_generation.MAX_ROUNDS + 1):
        with pytest.raises(judgment.JudgmentRequired):
            word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
        run_state.save(tmp_path, state)
        approve_all_response(run_dir, state.run_id, round_no)

    with pytest.raises(word_pipeline.RetryRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert state.context["approved"] == []


def test_keyword_metrics_gate_passes_when_both_conditions_met(tmp_path, monkeypatch):
    stub = StubKeywordMetricsClient(
        default_factory=lambda word: KeywordMetricRecord(
            word=word, avg_monthly_searches=1000, competition="LOW", competition_index=0, api_status="success"
        )
    )
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    options = make_options(tmp_path, target_count=5, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_all_response(run_dir, state.run_id, 1)

    word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert len(state.context["approved"]) >= 5


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

    options = make_options(tmp_path, target_count=5, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_all_response(run_dir, state.run_id, 1)

    try:
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    except (judgment.JudgmentRequired, word_pipeline.RetryRequired):
        pass

    evidence_path = tmp_path / "output" / "_pipeline" / "intermediate" / f"{state.run_id}_keyword_metrics_evidence.jsonl"
    assert evidence_path.exists()
    entries = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    assert entries
    assert any(e["passed"] for e in entries)
    assert any(not e["passed"] for e in entries)
    for entry in entries:
        assert {"title", "avg_monthly_searches", "competition_index", "api_status", "passed", "checked_at"} <= entry.keys()


def test_keyword_metrics_budget_exceeded_raises_retry_required(tmp_path, monkeypatch):
    stub = StubKeywordMetricsClient(raise_error=word_pipeline.KeywordMetricsBudgetExceeded("out of budget"))
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    options = make_options(tmp_path, target_count=5, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    run_dir = word_pipeline._run_dir(tmp_path, state)

    with pytest.raises(judgment.JudgmentRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    run_state.save(tmp_path, state)
    approve_all_response(run_dir, state.run_id, 1)

    with pytest.raises(word_pipeline.RetryRequired):
        word_pipeline._stage_generate_and_review_titles(tmp_path, options, state)
    assert state.status == "CAPABILITY_STAGNATION"


# ---------------------------------------------------------------------------
# Cumulative keyword-metrics cache (GKP-001, 2026-08-17 user request):
# raw pass/fail data persisted across runs, and reused instead of re-querying.
# ---------------------------------------------------------------------------


def write_cache_row(tmp_path, *, title, avg, competition_index, api_status, gate_passed, checked_at="t0"):
    cache_path = word_pipeline._metrics_cache_path(tmp_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "title": title,
        "avg_monthly_searches": "" if avg is None else avg,
        "competition_index": "" if competition_index is None else competition_index,
        "api_status": api_status,
        "gate_passed": str(gate_passed),
        "checked_at": checked_at,
    }
    is_new_file = not cache_path.exists()
    with cache_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=word_pipeline._CACHE_COLUMNS)
        if is_new_file:
            writer.writeheader()
        writer.writerow(row)


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


def test_append_metrics_cache_rows_merges_without_duplicating(tmp_path):
    word_pipeline._append_metrics_cache_rows(
        tmp_path, [{"title": "Ledger Pilot", "avg_monthly_searches": 2000, "competition_index": 0, "api_status": "success", "gate_passed": "True", "checked_at": "t0"}]
    )
    word_pipeline._append_metrics_cache_rows(
        tmp_path, [{"title": "Claim Sentry", "avg_monthly_searches": 10, "competition_index": 50, "api_status": "success", "gate_passed": "False", "checked_at": "t1"}]
    )
    full = word_pipeline._load_metrics_cache(tmp_path)
    assert len(full) == 2  # not 1, not duplicated - both survive across separate append calls


def test_excluded_normalized_includes_cached_gate_failures_but_not_passes(tmp_path):
    write_cache_row(tmp_path, title="Curriculum Terminal", avg=5000, competition_index=30, api_status="success", gate_passed=False)
    write_cache_row(tmp_path, title="Ledger Pilot", avg=2000, competition_index=0, api_status="success", gate_passed=True)
    (tmp_path / "input").mkdir(parents=True, exist_ok=True)
    (tmp_path / "input" / "blocklist.txt").write_text("", encoding="utf-8")

    options = make_options(tmp_path, target_count=5, run_id="QA-20260817-210000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    excluded = word_pipeline._excluded_normalized(tmp_path, state)

    assert "curriculum terminal" in excluded  # known failure - never regenerate
    assert "ledger pilot" not in excluded  # known pass - still an eligible candidate


def test_apply_keyword_metrics_filter_reuses_cache_and_skips_api_for_cached_titles(tmp_path, monkeypatch):
    write_cache_row(tmp_path, title="Ledger Pilot", avg=2000, competition_index=0, api_status="success", gate_passed=True)
    stub = StubKeywordMetricsClient()
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    state = word_pipeline._load_or_create_state(make_options(tmp_path, target_count=5, run_id="QA-20260817-210000-KST"))
    candidates = [
        {"title": "Ledger Pilot", "industry": "finance"},  # cached - must NOT hit the API
        {"title": "Claim Sentry", "industry": "insurance"},  # new - must hit the API
    ]
    passed = word_pipeline._apply_keyword_metrics_filter(tmp_path, state, candidates)

    assert stub.fetched == ["Claim Sentry"]  # cached title never sent to fetch_metrics
    assert {c["title"] for c in passed} == {"Ledger Pilot", "Claim Sentry"}  # cached pass + fresh default-pass


def test_apply_keyword_metrics_filter_evidence_marks_source_cache_vs_api(tmp_path, monkeypatch):
    write_cache_row(tmp_path, title="Ledger Pilot", avg=2000, competition_index=0, api_status="success", gate_passed=True)
    stub = StubKeywordMetricsClient()
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: stub)

    state = word_pipeline._load_or_create_state(make_options(tmp_path, target_count=5, run_id="QA-20260817-210000-KST"))
    candidates = [{"title": "Ledger Pilot", "industry": "finance"}, {"title": "Claim Sentry", "industry": "insurance"}]
    word_pipeline._apply_keyword_metrics_filter(tmp_path, state, candidates)

    evidence_path = tmp_path / "output" / "_pipeline" / "intermediate" / f"{state.run_id}_keyword_metrics_evidence.jsonl"
    entries = {json.loads(line)["title"]: json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()}
    assert entries["Ledger Pilot"]["source"] == "cache"
    assert entries["Claim Sentry"]["source"] == "api"


# ---------------------------------------------------------------------------
# validate_outputs
# ---------------------------------------------------------------------------


def test_stage_validate_outputs_selects_exact_target_count(tmp_path):
    # target_count=10 (QA's real enforced floor) so the 30%-per-industry cap
    # (floor(10*0.3)=3) doesn't zero out a small handful of one-per-industry items
    options = make_options(tmp_path, target_count=10, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    state.context["approved"] = [
        {"title": t, "industry": industry}
        for t, industry in [
            ("Vendor Guard", "finance"), ("Claim Tracker", "insurance"), ("Freight Flow", "logistics"),
            ("Lease Hub", "real_estate"), ("Policy Pilot", "insurance"), ("Onboarding Desk", "hr_payroll"),
            ("Permit Radar", "construction"), ("Inventory Relay", "retail_ecommerce"),
            ("Reservation Vault", "hospitality"), ("Enrollment Compass", "education"),
        ]
    ]
    word_pipeline._stage_validate_outputs(tmp_path, options, state)
    assert len(state.context["final_titles"]) == 10


def test_stage_validate_outputs_enforces_industry_cap(tmp_path):
    """design 9.1's 30%-per-opportunity cap applies to industries now - 5
    titles all from the same industry can't fill a 5-target run alone."""
    options = make_options(tmp_path, target_count=5, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    state.context["approved"] = [
        {"title": f"Ledger Word{i}", "industry": "finance"} for i in range(5)
    ]
    # not real title-format words but the cap check runs before format
    # validation in this test's assembled dict list; use valid two-word titles
    state.context["approved"] = [
        {"title": t, "industry": "finance"}
        for t in ["Ledger Guard", "Ledger Tracker", "Ledger Sync", "Ledger Flow", "Ledger Hub"]
    ]
    with pytest.raises(word_pipeline.RetryRequired):
        word_pipeline._stage_validate_outputs(tmp_path, options, state)
    assert state.status == "RETRYING"


def test_stage_validate_outputs_rejects_history_duplicate(tmp_path):
    # target_count=10 with a 10th, different-industry duplicate slot removed
    # would still hit the cap trivially, so instead this seeds exactly the
    # cap's worth of distinct industries and makes ONE a history duplicate -
    # validate_title_set must still catch it even though the cap step passes.
    options = make_options(tmp_path, target_count=10, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state, existing_lines=["Vendor Guard"])
    state.context["approved"] = [
        {"title": t, "industry": industry}
        for t, industry in [
            ("Vendor Guard", "finance"), ("Claim Tracker", "insurance"), ("Freight Flow", "logistics"),
            ("Lease Hub", "real_estate"), ("Policy Pilot", "insurance"), ("Onboarding Desk", "hr_payroll"),
            ("Permit Radar", "construction"), ("Inventory Relay", "retail_ecommerce"),
            ("Reservation Vault", "hospitality"), ("Enrollment Compass", "education"),
        ]
    ]
    with pytest.raises(RuntimeError, match="duplicate_history"):
        word_pipeline._stage_validate_outputs(tmp_path, options, state)
    assert state.status == "FAILED"


# ---------------------------------------------------------------------------
# publish_mode_outputs
# ---------------------------------------------------------------------------


def test_stage_publish_mode_outputs_qa_writes_only_under_qa_dir(tmp_path):
    options = make_options(tmp_path, target_count=2, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    state.context["final_titles"] = ["Vendor Guard", "Claim Tracker"]

    word_pipeline._stage_publish_mode_outputs(tmp_path, options, state)

    qa_output = tmp_path / "output" / "_pipeline" / "qa" / state.run_id / "generated" / "saas_words_qa.txt"
    assert qa_output.read_text(encoding="utf-8") == "Vendor Guard\nClaim Tracker\n"
    assert not (tmp_path / "output" / "deliverables" / "history" / "words.txt").exists()
    assert not (tmp_path / "output" / "deliverables" / "generated").exists()


def test_stage_publish_mode_outputs_production_appends_history_atomically(tmp_path):
    options = make_options(tmp_path, mode="production", target_count=2, run_id="RUN-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    state.context["final_titles"] = ["Vendor Guard", "Claim Tracker"]

    word_pipeline._stage_publish_mode_outputs(tmp_path, options, state)

    final_path = tmp_path / "output" / "deliverables" / "generated" / state.context["generated_filename"]
    assert final_path.read_text(encoding="utf-8") == "Vendor Guard\nClaim Tracker\n"
    history = (tmp_path / "output" / "deliverables" / "history" / "words.txt").read_text(encoding="utf-8")
    assert history == "Vendor Guard\nClaim Tracker\n"


def test_stage_update_memory_and_git_checkpoint_writes_handoff_and_checkpoints(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        word_pipeline, "_run_or_raise", lambda project_root, script_name, *extra: calls.append(script_name)
    )
    options = make_options(tmp_path, target_count=2, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    state.context["final_titles"] = ["Vendor Guard", "Claim Tracker"]

    word_pipeline._stage_update_memory_and_git_checkpoint(tmp_path, options, state)

    assert "git_checkpoint.py" in calls
    handoff = (tmp_path / "memory" / "HANDOFF.md").read_text(encoding="utf-8")
    assert "DONE" in handoff


def test_stage_publish_mode_outputs_production_is_idempotent_on_resume(tmp_path):
    options = make_options(tmp_path, mode="production", target_count=2, run_id="RUN-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    state.context["final_titles"] = ["Vendor Guard", "Claim Tracker"]

    word_pipeline._stage_publish_mode_outputs(tmp_path, options, state)
    word_pipeline._stage_publish_mode_outputs(tmp_path, options, state)  # simulated resume

    history = (tmp_path / "output" / "deliverables" / "history" / "words.txt").read_text(encoding="utf-8")
    assert history == "Vendor Guard\nClaim Tracker\n"  # not doubled
