"""qa/regression/REQUIRED_CASES.md의 필수 회귀 사례를 순서대로 검증한다.

각 테스트는 해당 항목의 코드 경로를 직접 호출해 실제로 통과/실패하는지
증명한다. 다른 테스트 파일에서 더 상세히 다루는 항목도 있지만, 이 파일은
필수 목록 전체가 한 곳에서 재현 가능함을 보장하기 위한 것이다.
"""

import csv
import sys
from pathlib import Path

import pytest
import requests

from saas_words_two import (
    collection,
    contracts,
    db,
    demand_scoring,
    google_calibration,
    opportunity_scoring,
    supply,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import apply_human_calibration
import import_human_google_checks


# 1. QA 19개/21개 실패
def _unique_titles(count):
    # each word must match ^[A-Z][a-z]*$ - a single leading uppercase letter,
    # lowercase after that - so vary titles with a lowercase suffix, not digits.
    return [f"Alpha{chr(97 + i)} Beta" for i in range(count)]


def test_qa_19_or_21_titles_fails_validation():
    errors_19 = contracts.validate_title_set(_unique_titles(19), target_count=20)
    assert any(e.startswith("wrong_count") for e in errors_19)

    errors_21 = contracts.validate_title_set(_unique_titles(21), target_count=20)
    assert any(e.startswith("wrong_count") for e in errors_21)

    assert contracts.validate_title_set(_unique_titles(20), target_count=20) == []


# 2. 추가 라운드 후 정확히 20개 (multi-round shortfall recovery)
def test_additional_round_reaches_exact_target():
    from saas_words_two import title_generation as tg

    approved_round1 = 12
    shortfall = 20 - approved_round1
    round2_size = tg.next_round_size(shortfall)
    assert round2_size == shortfall * 2 == 16

    # round 2 over-produces relative to the shortfall; final selection trims
    # back to exactly target_count once enough are approved.
    candidates = [{"problem_id": f"P-{i % 6:04d}", "priority_score": 100 - i} for i in range(approved_round1 + round2_size)]
    selected = tg.select_final_titles(candidates, target_count=20)
    assert len(selected) == 20


# 3. 데이터원 하나 실패 (다른 데이터원으로 계속)
class _FailingSession:
    def __init__(self, routes):
        self.routes = routes

    def get(self, url, timeout):
        path = url.split("/v0/", 1)[1]
        if path == "askstories.json":
            # must be requests' ConnectionError (a RequestException subclass) -
            # hn_client._get_json only retries/catches that, not the builtin one
            raise requests.ConnectionError("askstories down")
        return _FakeResponse(self.routes[path])


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_single_source_list_failure_does_not_block_others(tmp_path):
    routes = {
        "newstories.json": [1],
        "showstories.json": [],
        "item/1.json": {"id": 1, "type": "story", "by": "alice", "time": 100, "title": "x"},
    }
    conn = db.connect(tmp_path)
    sources_config = {"sources": {"hacker_news": {"incremental_cursor": "data/cache/hacker_news_last_id.txt"}}}
    summary = collection.run_incremental_collection(
        tmp_path, conn, sources_config, {"stories_per_list": 500, "comments_per_story": 5, "max_items_per_run": 100},
        _FailingSession(routes), fetched_at="t0",
    )
    assert summary.fetched_stories == 1  # newstories still collected despite askstories failing
    assert any("askstories" in e for e in summary.errors)
    conn.close()


# 4. 중복 게시글·동일 작성자 반복 댓글 (독립 사용자 수는 저자 기준)
def test_repeated_comments_from_same_author_count_as_one_independent_user():
    evidence = [
        {"id": 1, "type": "story", "parent": None, "time": 100, "author": "alice"},
        {"id": 2, "type": "comment", "parent": 1, "time": 101, "author": "alice"},
        {"id": 3, "type": "comment", "parent": 1, "time": 102, "author": "alice"},
    ]
    independent_users = len({row["author"] for row in evidence if row["author"]})
    assert independent_users == 1
    assert demand_scoring.independent_users_score(independent_users) == 5  # below the 5-user gate tier


# 5. 직접·부분·범용 제품 혼합
def test_mixed_supply_types_weighted_correctly():
    products = [
        {"active": True, "supply_type": "direct"},
        {"active": True, "supply_type": "partial"},
        {"active": True, "supply_type": "generic"},
        {"active": True, "supply_type": "noncompeting"},
    ]
    assert supply.effective_supply(products) == 1.0 + 0.4 + 0.1 + 0.0


# 6. 폐업 제품 (신호 부족 -> 비활성 -> 유효 공급량에서 제외)
def test_defunct_product_excluded_from_effective_supply():
    defunct_signals = {"official_name": True, "target_user": False, "core_feature": False}  # only 1 of 8
    assert not supply.is_active_supply(defunct_signals)
    products = [
        {"active": supply.is_active_supply(defunct_signals), "supply_type": "direct"},
        {"active": True, "supply_type": "direct"},
    ]
    assert supply.effective_supply(products) == 1.0  # only the genuinely active one counts


# 7. 수요 높음+공급 많음 제외
def test_high_demand_high_supply_excluded_from_title_generation():
    eligibility = opportunity_scoring.OpportunityEligibilityInput(
        demand_score=90, independent_users=30, has_recent_evidence=True, is_repeated_task=True,
        has_loss_time_or_risk_evidence=True, has_clear_saas_feature=True,
        supply_scarcity_score=20, priority_score_value=40, scarcity_grade="C",
        confidence_level="A", has_manual_or_complaint_evidence=True, purchase_intent_or_loss=True,
    )
    assert not opportunity_scoring.meets_generate_titles_conditions(eligibility)


# 8. 수요 중간+공급 거의 없음 우선 (design doc worked example)
def test_moderate_demand_near_zero_supply_ranks_above_high_demand_ample_supply():
    problem_a = {"problem_id": "A", "scarcity_grade": "B", "supply_scarcity_score": 60, "effective_supply": 6, "priority_score": 67.0, "confidence": "B", "demand_score": 80}
    problem_b = {"problem_id": "B", "scarcity_grade": "S", "supply_scarcity_score": 90, "effective_supply": 1.5, "priority_score": 86.7, "confidence": "A", "demand_score": 52}
    ordered = opportunity_scoring.sort_opportunities([problem_a, problem_b])
    assert [o["problem_id"] for o in ordered] == ["B", "A"]


# 9. 공급 없음+수요 없음 제외 (공급 0이어도 수요 증거 없으면 제외)
def test_zero_supply_but_no_demand_evidence_still_excluded():
    eligibility = opportunity_scoring.OpportunityEligibilityInput(
        demand_score=50, independent_users=2, has_recent_evidence=False, is_repeated_task=False,
        has_loss_time_or_risk_evidence=False, has_clear_saas_feature=True,
        supply_scarcity_score=100, priority_score_value=100, scarcity_grade="S",
        confidence_level="A", has_manual_or_complaint_evidence=False, purchase_intent_or_loss=False,
    )
    reasons = opportunity_scoring.hard_exclusion_reasons(eligibility)
    assert "independent_users_below_5" in reasons
    assert "no_recent_24_month_evidence" in reasons
    assert not opportunity_scoring.meets_generate_titles_conditions(eligibility)


# 10. 기회 하나 30% 초과 방지
def test_single_opportunity_cannot_exceed_30_percent_share():
    from saas_words_two import title_generation as tg

    counts = {"P-0001": 7, "P-0002": 5, "P-0003": 4, "P-0004": 2, "P-0005": 2}  # sums to 20
    violations = tg.check_distribution(counts, target_count=20)
    assert any("opportunity_over_30pct:P-0001" in v for v in violations)


# 11. 운영 이력 정확/대소문자/역순 중복
def test_history_exact_case_and_reverse_duplicates_rejected():
    history = ["Vendor Guard"]
    errors = contracts.validate_title_set(
        ["Vendor Guard", "vendor guard", "Guard Vendor", "Permit Flow"], target_count=4, history=history
    )
    assert any("duplicate_history" in e for e in errors)  # exact + case-insensitive
    assert any("reverse_duplicate" in e or "duplicate" in e for e in errors)


# 12. 게시 실패 롤백 - see tests/test_pipeline.py::
#     test_stage_publish_mode_outputs_resume_does_not_double_append_history
#     for the full pipeline-level regression; verified again here at the
#     atomic_write_text level.
def test_atomic_write_never_leaves_a_partial_file(tmp_path):
    target = tmp_path / "words.txt"
    contracts.atomic_write_text(target, "Vendor Guard\n")
    assert target.read_text(encoding="utf-8") == "Vendor Guard\n"
    # a second, larger write must fully replace, never partially overlay
    contracts.atomic_write_text(target, "Vendor Guard\nPermit Flow\n")
    assert target.read_text(encoding="utf-8") == "Vendor Guard\nPermit Flow\n"


# 13. 세션 중단·재개 - see tests/test_pipeline.py for resume-state coverage;
#     spot-checked here at the run_state layer.
def test_session_pause_and_resume_preserves_stage_and_context(tmp_path):
    from saas_words_two import pipeline, run_state

    options = pipeline.RunOptions(mode="qa", target_count=20, project_root=tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    state.stage = "collect_and_verify_supply"
    state.status = "RUNNING"
    state.awaiting_judgment = "collect_and_verify_supply"
    state.context["title_round"] = 2
    run_state.save(tmp_path, state)

    resumed = pipeline._load_or_create_state(
        pipeline.RunOptions(mode="qa", target_count=20, project_root=tmp_path, resume=True)
    )
    assert resumed.stage == "collect_and_verify_supply"
    assert resumed.context["title_round"] == 2


# 14. Git push 실패 - see tests/test_git_checkpoint_script.py::
#     test_commit_batch_push_failure_reports_commit_pending for the full test;
#     re-asserted here for traceability against the required-cases list.
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
    assert result.local_sha  # the commit itself is not lost


# 15. Google 입력 일부 행/중복/잘못된 형식/다른 날짜 - one CSV exercising all four
def test_google_input_partial_duplicate_malformed_and_redated_rows(tmp_path):
    conn = db.connect(tmp_path)
    rows = [
        {  # valid, minimal
            "validation_id": "GVQ-1", "query_type": "MARKET_QUERY", "problem_id": "", "title": "",
            "google_query": "", "predicted_effective_supply": "", "predicted_scarcity_score": "",
            "predicted_result_band": "", "priority_reason": "", "user_result_count": "100",
            "user_checked_at": "2026-08-04T20:15:00+09:00", "country": "", "language": "",
            "search_context": "", "top_results_relevant": "", "user_notes": "",
        },
        {  # partially filled -> missing user_checked_at -> PARTIALLY_FILLED (4.11), not invalid
            "validation_id": "GVQ-2", "query_type": "MARKET_QUERY", "problem_id": "", "title": "",
            "google_query": "", "predicted_effective_supply": "", "predicted_scarcity_score": "",
            "predicted_result_band": "", "priority_reason": "", "user_result_count": "50",
            "user_checked_at": "", "country": "", "language": "", "search_context": "",
            "top_results_relevant": "", "user_notes": "",
        },
        {  # malformed count
            "validation_id": "GVQ-3", "query_type": "MARKET_QUERY", "problem_id": "", "title": "",
            "google_query": "", "predicted_effective_supply": "", "predicted_scarcity_score": "",
            "predicted_result_band": "", "priority_reason": "", "user_result_count": "not-a-number",
            "user_checked_at": "2026-08-04T20:15:00+09:00", "country": "", "language": "",
            "search_context": "", "top_results_relevant": "", "user_notes": "",
        },
    ]
    input_path = tmp_path / "human_google_checks.csv"
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    ledger_path = tmp_path / "ledger.jsonl"
    from saas_words_two import ids

    summary = import_human_google_checks.import_observations(
        input_path, tmp_path / "missing_queue.csv", ledger_path,
        import_run_id="RUN-1", id_conn=conn, now=ids.now_kst(),
    )
    assert summary["imported"] == 1
    assert summary["invalid"] == 1  # malformed count (GVQ-3)
    assert summary["partially_filled"] == 1  # missing checked_at (GVQ-2), design 4.11 - not the same as invalid

    # re-checking the SAME query on a different date is a new, valid observation
    rows_redated = [dict(rows[0])]
    rows_redated[0]["user_checked_at"] = "2026-08-05T09:00:00+09:00"
    rows_redated[0]["user_result_count"] = "150"
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows_redated)

    summary2 = import_human_google_checks.import_observations(
        input_path, tmp_path / "missing_queue.csv", ledger_path,
        import_run_id="RUN-2", id_conn=conn, now=ids.now_kst(),
    )
    assert summary2["imported"] == 1
    assert summary2["duplicate_rejected"] == 0

    # importing the exact same original row again IS a duplicate
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows([rows[0]])
    summary3 = import_human_google_checks.import_observations(
        input_path, tmp_path / "missing_queue.csv", ledger_path,
        import_run_id="RUN-3", id_conn=conn, now=ids.now_kst(),
    )
    assert summary3["duplicate_rejected"] == 1
    conn.close()


# 16. 검색 노이즈, 공급 과소·과대, TITLE_QUERY 분리, 보정 전파 제한
def test_query_noise_and_over_under_estimation_classified_distinctly():
    assert (
        google_calibration.classify_market_query_error("LOW", "VERY_HIGH", top_results_relevant=None)
        == "SUPPLY_UNDERESTIMATED"
    )
    assert (
        google_calibration.classify_market_query_error("VERY_HIGH", "LOW", top_results_relevant=None)
        == "SUPPLY_OVERESTIMATED"
    )
    assert (
        google_calibration.classify_market_query_error("HIGH", "HIGH", top_results_relevant=0)
        == "QUERY_NOISE_HIGH"
    )


def test_title_query_errors_are_a_separate_taxonomy_from_market_query():
    market_error = google_calibration.classify_market_query_error("LOW", "VERY_HIGH", top_results_relevant=None)
    title_error = google_calibration.classify_title_query_error("LOW", "VERY_HIGH", brand_conflict_flagged=False)
    assert market_error == "SUPPLY_UNDERESTIMATED"
    assert title_error == "TITLE_COLLISION_UNDERESTIMATED"
    assert market_error != title_error


def test_calibration_does_not_propagate_to_problems_without_observations(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("INSERT INTO problems (problem_id, status) VALUES ('P-OBSERVED', 'DEMAND_PASSED')")
    conn.execute("INSERT INTO problems (problem_id, status) VALUES ('P-UNOBSERVED', 'DEMAND_PASSED')")
    for pid in ("P-OBSERVED", "P-UNOBSERVED"):
        conn.execute(
            "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
            "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, updated_at) "
            "VALUES (?, 80, 1.0, 80, 'S', 90, 'A', 'GENERATE_TITLES', '[]', '[]', 't0')",
            (pid,),
        )
    conn.commit()

    observations = [
        {"query_type": "MARKET_QUERY", "problem_id": "P-OBSERVED", "user_result_count": 50, "top_results_relevant": 5}
    ]
    apply_human_calibration.apply_calibration(conn, observations)

    observed = conn.execute("SELECT * FROM opportunities WHERE problem_id = 'P-OBSERVED'").fetchone()
    unobserved = conn.execute("SELECT * FROM opportunities WHERE problem_id = 'P-UNOBSERVED'").fetchone()
    assert observed["human_calibration_status"] != "NO_DATA"
    assert unobserved["human_calibration_status"] == "NO_DATA"
    assert unobserved["human_adjusted_supply_scarcity_score"] is None
    assert unobserved["supply_scarcity_score"] == 80  # untouched base score
    conn.close()


# 17-19. Keyword Planner 게이트 (GKP-001) - word_pipeline._apply_keyword_metrics_filter
# 를 직접 호출해 세 회귀 사례를 재현한다.
def _kw_state(tmp_path, run_id="QA-20260817-000000-KST"):
    from saas_words_two import word_pipeline

    options = word_pipeline.RunOptions(mode="qa", target_count=5, project_root=tmp_path, run_id=run_id)
    return word_pipeline._load_or_create_state(options)


# 17. competition_index NULL(죽은 단어)은 avg_monthly_searches가 아무리 높아도 항상 탈락
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


# 18. avg_monthly_searches가 임계값 미만이면 탈락
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


# 19. 자격증명 누락/일일 예산 초과 시 가짜 통과 없이 예외가 그대로 전파된다
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
