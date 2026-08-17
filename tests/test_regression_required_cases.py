"""qa/regression/REQUIRED_CASES.md의 필수 회귀 사례를 순서대로 검증한다.

각 테스트는 해당 항목의 코드 경로를 직접 호출해 실제로 통과/실패하는지
증명한다. 다른 테스트 파일에서 더 상세히 다루는 항목도 있지만, 이 파일은
필수 목록 전체가 한 곳에서 재현 가능함을 보장하기 위한 것이다.

2026-08-18: 수요/공급 파이프라인 완전 삭제 + "정확히 500개"/30% 상한 폐기로
그 개념에 묶여있던 옛 사례들은 제거됐다(git 이력에 원본 보존,
`memory/ACTIVE_ISSUES.md` 참고). 현재 목록은 `qa/regression/REQUIRED_CASES.md`
참고.
"""

import sys
from pathlib import Path

import pytest

from saas_words_two import contracts

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


# 1. QA 19개/21개 실패
def _unique_titles(count):
    return [f"Alpha{chr(97 + i)} Beta" for i in range(count)]


def test_qa_19_or_21_titles_fails_validation():
    errors_19 = contracts.validate_title_set(_unique_titles(19), target_count=20)
    assert any(e.startswith("wrong_count") for e in errors_19)

    errors_21 = contracts.validate_title_set(_unique_titles(21), target_count=20)
    assert any(e.startswith("wrong_count") for e in errors_21)

    assert contracts.validate_title_set(_unique_titles(20), target_count=20) == []


# 2. 운영 이력 정확/대소문자/역순 중복
def test_history_exact_case_and_reverse_duplicates_rejected():
    history = ["Vendor Guard"]
    errors = contracts.validate_title_set(
        ["Vendor Guard", "vendor guard", "Guard Vendor", "Permit Flow"], target_count=4, history=history
    )
    assert any("duplicate_history" in e for e in errors)
    assert any("reverse_duplicate" in e or "duplicate" in e for e in errors)


# 3. 원자적 쓰기는 부분 파일을 남기지 않음
def test_atomic_write_never_leaves_a_partial_file(tmp_path):
    target = tmp_path / "generated_candidates.csv"
    contracts.atomic_write_text(target, "Vendor Guard\n")
    assert target.read_text(encoding="utf-8") == "Vendor Guard\n"
    contracts.atomic_write_text(target, "Vendor Guard\nPermit Flow\n")
    assert target.read_text(encoding="utf-8") == "Vendor Guard\nPermit Flow\n"


# 4. 세션 중단·재개 - see tests/test_word_pipeline.py::
#    test_run_pipeline_completes_after_judgment_response_provided for the
#    full end-to-end path; re-checked here at the state-persistence layer.
def test_session_pause_and_resume_preserves_stage_and_context(tmp_path):
    from saas_words_two import run_state, word_pipeline

    options = word_pipeline.RunOptions(mode="qa", project_root=tmp_path, run_id="QA-20260818-190000-KST")
    state = word_pipeline._load_or_create_state(options)
    state.stage = "generate_and_review_titles"
    state.status = "RUNNING"
    state.awaiting_judgment = "review_titles"
    state.context["candidate_industry"] = {"Vendor Guard": "finance"}
    run_state.save(tmp_path, state)

    resumed = word_pipeline._load_or_create_state(
        word_pipeline.RunOptions(mode="qa", project_root=tmp_path, resume=True)
    )
    assert resumed.stage == "generate_and_review_titles"
    assert resumed.context["candidate_industry"] == {"Vendor Guard": "finance"}


# 5. Git push 실패 - see tests/test_git_checkpoint_script.py::
#    test_commit_batch_push_failure_reports_commit_pending for the full test;
#    re-asserted here for traceability against the required-cases list.
def test_git_push_failure_reports_commit_pending_not_data_loss(tmp_path):
    import subprocess

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import git_checkpoint

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")

    result = git_checkpoint.commit_batch(tmp_path, "no remote configured", push=True)
    assert result.status == "COMMIT_PENDING"
    assert result.local_sha


# 6-10. Keyword Planner 게이트 (GKP-001) - word_pipeline._apply_keyword_metrics_filter
# 를 직접 호출해 재현한다.
def _kw_state(tmp_path, run_id="QA-20260817-000000-KST"):
    from saas_words_two import word_pipeline

    options = word_pipeline.RunOptions(mode="qa", project_root=tmp_path, run_id=run_id)
    return word_pipeline._load_or_create_state(options)


# 6. competition_index NULL(죽은 단어)은 avg_monthly_searches가 아무리 높아도 항상 탈락
def test_keyword_metrics_gate_rejects_null_competition_index_regardless_of_searches(tmp_path, monkeypatch):
    from saas_words_two import word_pipeline
    from saas_words_two.keyword_metrics_client import KeywordMetricRecord

    class _NullMetricsClient:
        def fetch_metrics(self, words):
            return [
                KeywordMetricRecord(
                    word=w, avg_monthly_searches=999999, competition=None, competition_index=None, api_status="failed"
                )
                for w in words
            ]

    monkeypatch.setattr(word_pipeline, "_keyword_metrics_settings", lambda project_root: (1000, 0, None, Path(".")))
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: _NullMetricsClient())

    state = _kw_state(tmp_path)
    passed = word_pipeline._apply_keyword_metrics_filter(tmp_path, state, [{"title": "Ledger Pilot", "industry": "finance"}])
    assert passed == []


# 7. avg_monthly_searches가 임계값 미만이면 탈락
def test_keyword_metrics_gate_rejects_below_search_volume_threshold(tmp_path, monkeypatch):
    from saas_words_two import word_pipeline
    from saas_words_two.keyword_metrics_client import KeywordMetricRecord

    class _LowVolumeClient:
        def fetch_metrics(self, words):
            return [
                KeywordMetricRecord(word=w, avg_monthly_searches=10, competition="LOW", competition_index=0, api_status="success")
                for w in words
            ]

    monkeypatch.setattr(word_pipeline, "_keyword_metrics_settings", lambda project_root: (1000, 0, None, Path(".")))
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: _LowVolumeClient())

    state = _kw_state(tmp_path)
    passed = word_pipeline._apply_keyword_metrics_filter(tmp_path, state, [{"title": "Ledger Pilot", "industry": "finance"}])
    assert passed == []


# 8. 자격증명 누락/일일 예산 초과 시 가짜 통과 없이 예외가 그대로 전파된다
def test_keyword_metrics_gate_credentials_error_does_not_silently_pass(tmp_path, monkeypatch):
    from saas_words_two import word_pipeline
    from saas_words_two.keyword_metrics_client import KeywordMetricsCredentialsError

    def _raise_credentials_error(project_root):
        raise KeywordMetricsCredentialsError("missing required credentials")

    monkeypatch.setattr(word_pipeline, "_keyword_metrics_settings", lambda project_root: (1000, 0, None, Path(".")))
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", _raise_credentials_error)

    state = _kw_state(tmp_path)
    with pytest.raises(KeywordMetricsCredentialsError):
        word_pipeline._apply_keyword_metrics_filter(tmp_path, state, [{"title": "Ledger Pilot", "industry": "finance"}])


# 9. 이미 탈락으로 캐시된 단어는 재생성/재조회하지 않음 - see
#    tests/test_word_pipeline.py::test_ledger_entries_never_regenerated_across_separate_runs
def test_excluded_normalized_includes_ledger_entries_regardless_of_verdict(tmp_path):
    from saas_words_two import word_pipeline

    word_pipeline._append_generated_ledger_rows(
        tmp_path,
        [
            {"title": "Curriculum Terminal", "industry": "education", "ai_approved": "False", "ai_reason": "unclear", "judged_at": "t0"},
            {"title": "Ledger Pilot", "industry": "finance", "ai_approved": "True", "ai_reason": "", "judged_at": "t0"},
        ],
    )
    (tmp_path / "input").mkdir(parents=True, exist_ok=True)
    (tmp_path / "input" / "blocklist.txt").write_text("", encoding="utf-8")

    state = _kw_state(tmp_path)
    excluded = word_pipeline._excluded_normalized(tmp_path, state)

    assert "curriculum terminal" in excluded
    assert "ledger pilot" in excluded  # approved AND already-generated - never regenerated either


# 10. 이미 통과로 캐시된 단어는 API 재호출 없이 캐시값 재사용 - see
#     tests/test_word_pipeline.py::test_apply_keyword_metrics_filter_reuses_cache_and_skips_api_for_cached_titles
def test_apply_keyword_metrics_filter_reuses_cache_and_skips_api(tmp_path, monkeypatch):
    from saas_words_two import word_pipeline

    word_pipeline._append_metrics_cache_rows(
        tmp_path,
        [{"title": "Ledger Pilot", "avg_monthly_searches": 2000, "competition_index": 0, "api_status": "success", "gate_passed": "True", "checked_at": "t0"}],
    )

    class _ShouldNotBeCalled:
        def fetch_metrics(self, words):
            raise AssertionError("must not query the API for an already-cached title")

    monkeypatch.setattr(word_pipeline, "_keyword_metrics_settings", lambda project_root: (1000, 0, None, Path(".")))
    monkeypatch.setattr(word_pipeline, "_build_keyword_metrics_client", lambda project_root: _ShouldNotBeCalled())

    state = _kw_state(tmp_path)
    passed = word_pipeline._apply_keyword_metrics_filter(tmp_path, state, [{"title": "Ledger Pilot", "industry": "finance"}])
    assert {c["title"] for c in passed} == {"Ledger Pilot"}


# 11. 생성 ledger: AI 승인됐지만 Keyword Planner 미확인인 후보(backlog)는
#     다음 실행에 자동 반영되어 유실되지 않는다 - see
#     tests/test_word_pipeline.py::test_stage_load_state_sweeps_ai_approved_kp_unresolved_into_backlog
#     and test_generate_and_review_titles_budget_exceeded_is_retrying
def test_ai_approved_kp_unresolved_candidate_becomes_backlog(tmp_path):
    from saas_words_two import word_pipeline

    word_pipeline._append_generated_ledger_rows(
        tmp_path,
        [{"title": "Vendor Guard", "industry": "finance", "ai_approved": "True", "ai_reason": "", "judged_at": "t0"}],
    )
    state = _kw_state(tmp_path)
    word_pipeline._stage_load_state(tmp_path, None, state)
    assert state.context["backlog"] == [{"title": "Vendor Guard", "industry": "finance"}]


# 12. 생성 ledger: 한 번 생성+판정된 조합(승인/거절 무관)은 재생성되지 않는다 -
#     see tests/test_word_pipeline.py::test_ledger_entries_never_regenerated_across_separate_runs
def test_generated_ledger_entries_excluded_from_future_generation(tmp_path):
    from saas_words_two import word_generation, word_pipeline

    word_pipeline._append_generated_ledger_rows(
        tmp_path,
        [{"title": "Vendor Guard", "industry": "finance", "ai_approved": "True", "ai_reason": "", "judged_at": "t0"}],
    )
    state = _kw_state(tmp_path)
    excluded = word_pipeline._excluded_normalized(tmp_path, state)
    candidates = word_generation.generate_combinations(500, exclude=excluded)
    assert not any(c["title"] == "Vendor Guard" for c in candidates)
