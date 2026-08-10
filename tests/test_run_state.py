import pytest

from saas_words_two import run_state


def make_state(run_id="RUN-20260810-190000-KST", status="RUNNING", stage="load_state"):
    return run_state.RunState(
        run_id=run_id,
        mode="production",
        target_title_count=500,
        status=status,
        stage=stage,
        created_at="2026-08-10T19:00:00+09:00",
        updated_at="2026-08-10T19:00:00+09:00",
    )


def test_save_and_load_round_trip(tmp_path):
    state = make_state()
    run_state.save(tmp_path, state)
    loaded = run_state.load(tmp_path, state.run_id)
    assert loaded == state


def test_invalid_status_rejected(tmp_path):
    state = make_state(status="NOT_A_STATUS")
    with pytest.raises(ValueError):
        run_state.save(tmp_path, state)


def test_exists_false_until_saved(tmp_path):
    assert not run_state.exists(tmp_path, "RUN-20260810-190000-KST")
    run_state.save(tmp_path, make_state())
    assert run_state.exists(tmp_path, "RUN-20260810-190000-KST")


def test_latest_run_id_picks_lexicographically_last_matching_prefix(tmp_path):
    run_state.save(tmp_path, make_state(run_id="RUN-20260810-190000-KST"))
    run_state.save(tmp_path, make_state(run_id="RUN-20260811-090000-KST"))
    run_state.save(tmp_path, make_state(run_id="QA-20260811-100000-KST"))
    assert run_state.latest_run_id(tmp_path, "production") == "RUN-20260811-090000-KST"
    assert run_state.latest_run_id(tmp_path, "qa") == "QA-20260811-100000-KST"


def test_latest_run_id_none_when_missing(tmp_path):
    assert run_state.latest_run_id(tmp_path, "production") is None


def test_awaiting_judgment_and_context_round_trip(tmp_path):
    state = make_state()
    state.awaiting_judgment = "extract_and_cluster_problems"
    state.context = {"round": 2, "approved_titles": 17}
    run_state.save(tmp_path, state)
    loaded = run_state.load(tmp_path, state.run_id)
    assert loaded.awaiting_judgment == "extract_and_cluster_problems"
    assert loaded.context == {"round": 2, "approved_titles": 17}
