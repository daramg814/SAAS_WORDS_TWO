import pytest

from saas_words_two import judgment


def test_write_request_then_missing_response_raises(tmp_path):
    judgment.write_request(
        tmp_path,
        "extract_and_cluster_problems",
        "RUN-20260810-190000-KST",
        "extract problem structure",
        [{"evidence_id": "E-0001", "sentence": "is there a tool for X"}],
        generated_at="2026-08-10T19:00:00+09:00",
    )
    assert not judgment.has_response(tmp_path, "extract_and_cluster_problems")
    with pytest.raises(FileNotFoundError):
        judgment.read_response(tmp_path, "extract_and_cluster_problems")


def test_full_round_trip(tmp_path):
    judgment.write_request(
        tmp_path,
        "score_demand",
        "RUN-20260810-190000-KST",
        "judge purchase intent",
        [{"problem_id": "P-0001"}],
        generated_at="2026-08-10T19:00:00+09:00",
    )
    judgment.write_response(
        tmp_path,
        "score_demand",
        [{"problem_id": "P-0001", "purchase_intent": True, "economic_loss": False}],
        judged_at="2026-08-10T19:05:00+09:00",
    )
    response = judgment.read_response(tmp_path, "score_demand")
    assert response["decisions"] == [
        {"problem_id": "P-0001", "purchase_intent": True, "economic_loss": False}
    ]


def test_response_rejected_if_request_changes_after_response_written(tmp_path):
    judgment.write_request(
        tmp_path,
        "score_demand",
        "RUN-1",
        "judge",
        [{"problem_id": "P-0001"}],
        generated_at="t0",
    )
    judgment.write_response(
        tmp_path, "score_demand", [{"problem_id": "P-0001", "purchase_intent": True}], judged_at="t1"
    )
    # Request regenerated with different content (e.g. new evidence appeared) invalidates the old response.
    judgment.write_request(
        tmp_path,
        "score_demand",
        "RUN-1",
        "judge",
        [{"problem_id": "P-0001"}, {"problem_id": "P-0002"}],
        generated_at="t2",
    )
    with pytest.raises(ValueError):
        judgment.read_response(tmp_path, "score_demand")


def test_write_response_without_request_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        judgment.write_response(tmp_path, "score_demand", [], judged_at="t0")


def test_response_missing_decisions_key_raises(tmp_path):
    judgment.write_request(tmp_path, "score_demand", "RUN-1", "judge", [], generated_at="t0")
    resp_path = judgment.response_path(tmp_path, "score_demand")
    resp_path.parent.mkdir(parents=True, exist_ok=True)
    req = judgment.request_path(tmp_path, "score_demand")
    import json

    request_hash = json.loads(req.read_text(encoding="utf-8"))["request_hash"]
    resp_path.write_text(
        json.dumps({"stage": "score_demand", "run_id": "RUN-1", "round": 1, "request_hash": request_hash}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        judgment.read_response(tmp_path, "score_demand")


def test_judgment_required_exception_message(tmp_path):
    path = judgment.request_path(tmp_path, "score_demand")
    exc = judgment.JudgmentRequired("score_demand", path)
    assert "AWAITING_JUDGMENT" in str(exc)
    assert "score_demand" in str(exc)
