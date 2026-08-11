import json
from pathlib import Path

import pytest

from saas_words_two import judgment, run_state, word_pipeline

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_options(tmp_path, mode="qa", target_count=5, **overrides):
    return word_pipeline.RunOptions(mode=mode, target_count=target_count, project_root=tmp_path, **overrides)


def with_qa_history_snapshot(tmp_path, state, existing_lines=()):
    snapshot_path = tmp_path / "output" / "qa" / state.run_id / "qa_history_snapshot.txt"
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
    history_path = tmp_path / "output" / "history" / "words.txt"
    history_path.parent.mkdir(parents=True)
    history_path.write_text("Vendor Guard\n", encoding="utf-8")

    options = make_options(tmp_path, run_id="QA-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)

    snapshot_path = tmp_path / "output" / "qa" / state.run_id / "qa_history_snapshot.txt"
    assert snapshot_path.exists()
    assert "Vendor Guard" in snapshot_path.read_text(encoding="utf-8")


def test_stage_load_state_noop_for_production(tmp_path):
    options = make_options(tmp_path, mode="production", target_count=500, run_id="RUN-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    word_pipeline._stage_load_state(tmp_path, options, state)
    assert "qa_history_snapshot_path" not in state.context


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
    intermediate = tmp_path / "output" / "intermediate" / f"{state.run_id}_shortfall_titles.txt"
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

    qa_output = tmp_path / "output" / "qa" / state.run_id / "generated" / "saas_words_qa.txt"
    assert qa_output.read_text(encoding="utf-8") == "Vendor Guard\nClaim Tracker\n"
    assert not (tmp_path / "output" / "history" / "words.txt").exists()
    assert not (tmp_path / "output" / "generated").exists()


def test_stage_publish_mode_outputs_production_appends_history_atomically(tmp_path):
    options = make_options(tmp_path, mode="production", target_count=2, run_id="RUN-20260811-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    state.context["final_titles"] = ["Vendor Guard", "Claim Tracker"]

    word_pipeline._stage_publish_mode_outputs(tmp_path, options, state)

    final_path = tmp_path / "output" / "generated" / state.context["generated_filename"]
    assert final_path.read_text(encoding="utf-8") == "Vendor Guard\nClaim Tracker\n"
    history = (tmp_path / "output" / "history" / "words.txt").read_text(encoding="utf-8")
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

    history = (tmp_path / "output" / "history" / "words.txt").read_text(encoding="utf-8")
    assert history == "Vendor Guard\nClaim Tracker\n"  # not doubled
