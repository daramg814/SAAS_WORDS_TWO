import json
import shutil
from pathlib import Path

import pytest

from saas_words_two import db, judgment, pipeline, run_state

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_options(tmp_path, mode="qa", target_count=20, **overrides):
    return pipeline.RunOptions(mode=mode, target_count=target_count, project_root=tmp_path, **overrides)


def with_real_scripts(tmp_path):
    """Stage handlers shell out to scripts/*.py under project_root; copy the
    real scripts directory in for tests that exercise those code paths."""
    shutil.copytree(REPO_ROOT / "scripts", tmp_path / "scripts")
    return tmp_path


def with_qa_history_snapshot(tmp_path, state):
    """_history_path_for(qa) reads state.context["qa_history_snapshot_path"],
    which _stage_load_state sets; seed it directly for tests that start past
    that stage."""
    snapshot_path = tmp_path / "output" / "_pipeline" / "qa" / state.run_id / "qa_history_snapshot.txt"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text("", encoding="utf-8")
    state.context["qa_history_snapshot_path"] = str(snapshot_path)


# ---------------------------------------------------------------------------
# _load_or_create_state
# ---------------------------------------------------------------------------


def test_load_or_create_state_creates_new_run(tmp_path):
    options = make_options(tmp_path)
    state = pipeline._load_or_create_state(options)
    assert state.mode == "qa"
    assert state.target_title_count == 20
    assert state.stage == pipeline.STAGES[0]
    assert state.run_id.startswith("QA-")
    assert "generated_filename" in state.context


def test_load_or_create_state_rejects_duplicate_run_id(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    run_state.save(tmp_path, state)
    with pytest.raises(ValueError):
        pipeline._load_or_create_state(options)


def test_load_or_create_state_resume_requires_existing_run(tmp_path):
    options = make_options(tmp_path, resume=True)
    with pytest.raises(ValueError):
        pipeline._load_or_create_state(options)


def test_load_or_create_state_resume_loads_latest(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    state.stage = "score_demand"
    run_state.save(tmp_path, state)

    resumed = pipeline._load_or_create_state(make_options(tmp_path, resume=True))
    assert resumed.run_id == state.run_id
    assert resumed.stage == "score_demand"


def test_load_or_create_state_resume_rejects_mode_mismatch(tmp_path):
    options = make_options(tmp_path, mode="qa", target_count=20, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    run_state.save(tmp_path, state)

    with pytest.raises(ValueError):
        pipeline._load_or_create_state(
            make_options(tmp_path, mode="production", target_count=500, resume=True, run_id=state.run_id)
        )


# ---------------------------------------------------------------------------
# _stage_load_state (QA history snapshot)
# ---------------------------------------------------------------------------


def test_stage_load_state_snapshots_history_for_qa(tmp_path):
    history_path = tmp_path / "output" / "deliverables" / "history" / "words.txt"
    history_path.parent.mkdir(parents=True)
    history_path.write_text("Vendor Guard\nPermit Flow\n", encoding="utf-8")

    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    pipeline._stage_load_state(conn, tmp_path, options, state)
    conn.close()

    snapshot_path = tmp_path / "output" / "_pipeline" / "qa" / state.run_id / "qa_history_snapshot.txt"
    assert snapshot_path.exists()
    assert "Vendor Guard" in snapshot_path.read_text(encoding="utf-8")
    assert state.context["qa_history_snapshot_path"] == str(snapshot_path)


def test_stage_load_state_snapshots_empty_history_as_truly_empty(tmp_path):
    """Regression: an empty output/deliverables/history/words.txt must snapshot to a
    0-byte file, not "\n" - otherwise _read_lines() reads the snapshot back
    as [''] (one blank line) instead of [] (no lines), a mismatch with the
    real file the snapshot is supposed to mirror."""
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    pipeline._stage_load_state(conn, tmp_path, options, state)
    conn.close()

    snapshot_path = tmp_path / "output" / "_pipeline" / "qa" / state.run_id / "qa_history_snapshot.txt"
    assert snapshot_path.read_bytes() == b""
    assert pipeline._read_lines(snapshot_path) == []


def test_stage_load_state_noop_for_production(tmp_path):
    options = make_options(tmp_path, mode="production", target_count=500, run_id="RUN-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    pipeline._stage_load_state(conn, tmp_path, options, state)
    conn.close()
    assert "qa_history_snapshot_path" not in state.context


# ---------------------------------------------------------------------------
# extract_and_cluster_problems judgment round trip
# ---------------------------------------------------------------------------


def seed_candidates_for_clustering(conn):
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, fetched_at) VALUES (1, 'story', 'alice', 100, 't0')"
    )
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, fetched_at) VALUES (2, 'comment', 'bob', 101, 't0')"
    )
    conn.execute(
        "INSERT INTO candidate_sentences (item_id, sentence, matched_patterns, created_at) VALUES "
        "(1, 'We still use spreadsheets to track vendor insurance', 'still use spreadsheets', 't0')"
    )
    conn.execute(
        "INSERT INTO candidate_sentences (item_id, sentence, matched_patterns, created_at) VALUES "
        "(2, 'I still use a spreadsheet to track vendor insurance', 'still use spreadsheets', 't0')"
    )
    conn.commit()


def test_brief_context_empty_when_file_missing(tmp_path):
    assert pipeline._brief_context(tmp_path) == ""


def test_brief_context_empty_when_file_blank(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "brief.md").write_text("   \n\n", encoding="utf-8")
    assert pipeline._brief_context(tmp_path) == ""


def test_brief_context_includes_file_content(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "brief.md").write_text("제외 시장: 성인 콘텐츠", encoding="utf-8")
    context = pipeline._brief_context(tmp_path)
    assert "제외 시장: 성인 콘텐츠" in context
    assert "brief.md" in context


def test_stage_extract_and_cluster_problems_includes_brief_in_instructions(tmp_path):
    with_real_scripts(tmp_path)
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "brief.md").write_text("제외 시장: 도박", encoding="utf-8")
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_candidates_for_clustering(conn)

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        pipeline._stage_extract_and_cluster_problems(conn, tmp_path, options, state)
    conn.close()

    request_doc = json.loads(excinfo.value.request_path.read_text(encoding="utf-8"))
    assert "제외 시장: 도박" in request_doc["instructions"]


def test_stage_extract_and_cluster_problems_writes_request_when_no_response(tmp_path):
    with_real_scripts(tmp_path)
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_candidates_for_clustering(conn)

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        pipeline._stage_extract_and_cluster_problems(conn, tmp_path, options, state)
    conn.close()

    assert excinfo.value.stage == "extract_and_cluster_problems"
    assert excinfo.value.request_path.exists()
    assert state.awaiting_judgment == "extract_and_cluster_problems"


def test_stage_extract_and_cluster_problems_consumes_response(tmp_path):
    with_real_scripts(tmp_path)
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_candidates_for_clustering(conn)

    with pytest.raises(judgment.JudgmentRequired):
        pipeline._stage_extract_and_cluster_problems(conn, tmp_path, options, state)

    run_dir = pipeline._run_dir(tmp_path, state)
    request = json.loads(judgment.request_path(run_dir, "extract_and_cluster_problems").read_text(encoding="utf-8"))
    cluster_id = request["items"][0]["cluster_id"]
    member_ids = [m["candidate_id"] for m in request["items"][0]["members"]]

    judgment.write_response(
        run_dir,
        "extract_and_cluster_problems",
        [
            {
                "cluster_id": cluster_id,
                "problems": [
                    {
                        "target_user": "small firms",
                        "task": "track vendor insurance",
                        "workaround": "spreadsheets",
                        "pain": "manual tracking",
                        "impact": "missed renewals",
                        "desired_outcome": "automatic reminders",
                        "frequency": "weekly",
                        "risk_severity": "moderate",
                        "purchase_intent": "strong",
                        "has_manual_or_complaint_evidence": True,
                        "member_candidate_ids": member_ids,
                    }
                ],
            }
        ],
        judged_at="2026-08-10T20:00:00+09:00",
    )

    pipeline._stage_extract_and_cluster_problems(conn, tmp_path, options, state)

    problems = conn.execute("SELECT * FROM problems").fetchall()
    assert len(problems) == 1
    assert problems[0]["target_user"] == "small firms"
    evidence = conn.execute("SELECT * FROM problem_evidence WHERE problem_id = ?", (problems[0]["problem_id"],)).fetchall()
    assert len(evidence) == len(member_ids)
    conn.close()


# ---------------------------------------------------------------------------
# collect_and_verify_supply judgment round trip
# ---------------------------------------------------------------------------


def seed_demand_passed_problem_with_candidate(conn):
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, status) VALUES "
        "('P-0001', 'small firms', 'track renewals', 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, dedupe_key, source) VALUES "
        "('S-0001', 'P-0001', 'VendorGuard', 'vendorguard', 'hn_show')"
    )
    conn.commit()


def seed_demand_passed_problem_with_two_candidates(conn):
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, status) VALUES "
        "('P-0001', 'small firms', 'track renewals', 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, domain, dedupe_key, source) VALUES "
        "('S-0001', 'P-0001', 'VendorGuard', 'vendorguard.com', 'vendorguardcom', 'hn_show')"
    )
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, domain, dedupe_key, source) VALUES "
        "('S-0002', 'P-0001', 'VendorGuard EU', 'vendorguard.eu', 'vendorguardeu', 'hn_mention')"
    )
    conn.commit()


def test_stage_collect_and_verify_supply_includes_merge_candidates_item_when_two_or_more(tmp_path, monkeypatch):
    # Candidates are seeded directly below; skip the real collect_supply_
    # candidates.py subprocess (it would hit the live HN Algolia API) since
    # this test only cares about the merge_candidates item this stage builds
    # from what's already in the DB.
    monkeypatch.setattr(pipeline, "_run_or_raise", lambda *a, **k: None)
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_demand_passed_problem_with_two_candidates(conn)

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        pipeline._stage_collect_and_verify_supply(conn, tmp_path, options, state)
    conn.close()

    request_doc = json.loads(excinfo.value.request_path.read_text(encoding="utf-8"))
    merge_items = [item for item in request_doc["items"] if item["kind"] == "merge_candidates"]
    assert len(merge_items) == 1
    assert merge_items[0]["problem_id"] == "P-0001"
    assert {c["product_id"] for c in merge_items[0]["candidates"]} == {"S-0001", "S-0002"}


def test_stage_collect_and_verify_supply_no_merge_candidates_item_with_single_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_run_or_raise", lambda *a, **k: None)
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_demand_passed_problem_with_candidate(conn)

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        pipeline._stage_collect_and_verify_supply(conn, tmp_path, options, state)
    conn.close()

    request_doc = json.loads(excinfo.value.request_path.read_text(encoding="utf-8"))
    assert not [item for item in request_doc["items"] if item["kind"] == "merge_candidates"]


def test_stage_collect_and_verify_supply_includes_common_crawl_excerpt_in_product_item(tmp_path, monkeypatch):
    """design 3.2: Common Crawl only enriches an already-collected candidate;
    the excerpt (collect_supply_candidates.py's enrich_with_common_crawl)
    must actually reach the product judgment item as extra evidence."""
    monkeypatch.setattr(pipeline, "_run_or_raise", lambda *a, **k: None)
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_demand_passed_problem_with_candidate(conn)
    conn.execute(
        "UPDATE supply_candidates SET common_crawl_excerpt = ? WHERE product_id = 'S-0001'",
        ("pricing signup demo page text",),
    )
    conn.commit()

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        pipeline._stage_collect_and_verify_supply(conn, tmp_path, options, state)
    conn.close()

    request_doc = json.loads(excinfo.value.request_path.read_text(encoding="utf-8"))
    product_items = [item for item in request_doc["items"] if item["kind"] == "product"]
    assert product_items[0]["common_crawl_excerpt"] == "pricing signup demo page text"
    assert "common_crawl_excerpt" in request_doc["instructions"]


def test_stage_collect_and_verify_supply_applies_merge_group_decision(tmp_path):
    """design 7.2: two candidates the reviewer judges to be the same
    underlying product (here: a rebrand/regional-site pair) merge into one -
    the duplicate is excluded from downstream competitor counting, not
    deleted (its evidence stays attached, just no longer counted separately)."""
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_demand_passed_problem_with_two_candidates(conn)
    run_dir = pipeline._run_dir(tmp_path, state)

    signals = {
        "official_name": True, "target_user": True, "core_feature": True, "signup_or_demo": False,
        "pricing": False, "recent_activity": False, "product_docs": False, "customer_references": False,
    }
    judgment.write_request(run_dir, "collect_and_verify_supply", state.run_id, "test", [], generated_at="t0")
    judgment.write_response(
        run_dir,
        "collect_and_verify_supply",
        [
            {"kind": "merge_group", "problem_id": "P-0001", "canonical_product_id": "S-0001",
             "duplicate_product_ids": ["S-0002"]},
            {"kind": "product", "product_id": "S-0001", "signals": signals, "supply_type": "direct"},
            {"kind": "product", "product_id": "S-0002", "signals": signals, "supply_type": "direct"},
            {"kind": "problem_gap", "problem_id": "P-0001", "supply_gap_user_specific": True,
             "supply_gap_no_strong_incumbent": True, "supply_gap_no_recent_entrants": False,
             "supply_gap_unresolved_complaints": True},
        ],
        judged_at="t1",
    )

    pipeline._stage_collect_and_verify_supply(conn, tmp_path, options, state)

    duplicate = conn.execute("SELECT merged_into_product_id FROM supply_candidates WHERE product_id = 'S-0002'").fetchone()
    assert duplicate["merged_into_product_id"] == "S-0001"
    canonical = conn.execute("SELECT merged_into_product_id FROM supply_candidates WHERE product_id = 'S-0001'").fetchone()
    assert canonical["merged_into_product_id"] is None

    # both still get verified (harmless - the merge only affects downstream counting)
    assert conn.execute("SELECT COUNT(*) c FROM supply_verification").fetchone()["c"] == 2

    import sys
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import score_opportunities

    verifications = score_opportunities.load_supply_verification(conn, "P-0001")
    assert [v["product_id"] for v in verifications] == ["S-0001"]  # S-0002 excluded, merged away
    conn.close()


def test_stage_collect_and_verify_supply_skips_when_no_demand_passed_problems(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    pipeline._stage_collect_and_verify_supply(conn, tmp_path, options, state)  # should not raise
    conn.close()


def test_stage_collect_and_verify_supply_consumes_response(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_demand_passed_problem_with_candidate(conn)
    run_dir = pipeline._run_dir(tmp_path, state)

    signals = {
        "official_name": True, "target_user": True, "core_feature": True, "signup_or_demo": False,
        "pricing": False, "recent_activity": False, "product_docs": False, "customer_references": False,
    }
    judgment.write_request(
        run_dir, "collect_and_verify_supply", state.run_id, "test", [], generated_at="t0"
    )
    judgment.write_response(
        run_dir,
        "collect_and_verify_supply",
        [
            {"kind": "product", "product_id": "S-0001", "signals": signals, "supply_type": "direct"},
            {
                "kind": "problem_gap",
                "problem_id": "P-0001",
                "supply_gap_user_specific": True,
                "supply_gap_no_strong_incumbent": True,
                "supply_gap_no_recent_entrants": False,
                "supply_gap_unresolved_complaints": True,
            },
        ],
        judged_at="t1",
    )

    pipeline._stage_collect_and_verify_supply(conn, tmp_path, options, state)

    verification = conn.execute("SELECT * FROM supply_verification WHERE product_id = 'S-0001'").fetchone()
    assert verification["signal_count"] == 3
    assert verification["active"] == 1
    assert verification["weight"] == 1.0

    problem = conn.execute("SELECT * FROM problems WHERE problem_id = 'P-0001'").fetchone()
    assert problem["supply_gap_user_specific"] == 1
    assert problem["supply_gap_no_recent_entrants"] == 0
    conn.close()


# ---------------------------------------------------------------------------
# review_opportunities judgment round trip
# ---------------------------------------------------------------------------


def seed_opportunity(conn, problem_id="P-0001", decision="RESEARCH_MORE"):
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, status) VALUES (?, 'small firms', 'track renewals', 'DEMAND_PASSED')",
        (problem_id,),
    )
    conn.execute(
        "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
        "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, updated_at) "
        "VALUES (?, 80, 1.0, 85, 'S', 90, 'A', ?, '[]', '[]', 't0')",
        (problem_id, decision),
    )
    conn.commit()


def test_stage_review_opportunities_includes_brief_in_instructions(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "brief.md").write_text("제외 시장: 도박", encoding="utf-8")
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_opportunity(conn)

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        pipeline._stage_review_opportunities(conn, tmp_path, options, state)
    conn.close()

    request_doc = json.loads(excinfo.value.request_path.read_text(encoding="utf-8"))
    assert "제외 시장: 도박" in request_doc["instructions"]


def test_stage_review_opportunities_writes_request(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_opportunity(conn)

    with pytest.raises(judgment.JudgmentRequired):
        pipeline._stage_review_opportunities(conn, tmp_path, options, state)
    conn.close()


def test_stage_review_opportunities_consumes_response(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_opportunity(conn)
    run_dir = pipeline._run_dir(tmp_path, state)

    judgment.write_request(run_dir, "review_opportunities", state.run_id, "test", [], generated_at="t0")
    judgment.write_response(
        run_dir, "review_opportunities",
        [{"problem_id": "P-0001", "decision": "GENERATE_TITLES", "rationale": "clear gap"}],
        judged_at="t1",
    )

    pipeline._stage_review_opportunities(conn, tmp_path, options, state)
    row = conn.execute("SELECT decision FROM opportunities WHERE problem_id = 'P-0001'").fetchone()
    assert row["decision"] == "GENERATE_TITLES"
    conn.close()


def test_stage_review_opportunities_forces_c_grade_generate_titles_to_research_more(tmp_path):
    """Regression: design 8.5 says grade C never generates titles - this must
    be enforced in code, not left to the judgment response alone."""
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, status) VALUES "
        "('P-0001', 'small firms', 'track renewals', 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
        "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, updated_at) "
        "VALUES ('P-0001', 80, 12.0, 40, 'C', 50, 'C', 'RESEARCH_MORE', '[]', '[]', 't0')"
    )
    conn.commit()
    run_dir = pipeline._run_dir(tmp_path, state)

    judgment.write_request(run_dir, "review_opportunities", state.run_id, "test", [], generated_at="t0")
    judgment.write_response(
        run_dir, "review_opportunities",
        [{"problem_id": "P-0001", "decision": "GENERATE_TITLES", "rationale": "looks great"}],
        judged_at="t1",
    )

    pipeline._stage_review_opportunities(conn, tmp_path, options, state)
    row = conn.execute("SELECT decision FROM opportunities WHERE problem_id = 'P-0001'").fetchone()
    assert row["decision"] == "RESEARCH_MORE"
    conn.close()


def test_stage_review_opportunities_forces_c_grade_scarcity_priority_to_research_more(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, status) VALUES "
        "('P-0001', 'small firms', 'track renewals', 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
        "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, updated_at) "
        "VALUES ('P-0001', 40, 12.0, 40, 'C', 50, 'C', 'RESEARCH_MORE', '[]', '[]', 't0')"
    )
    conn.commit()
    run_dir = pipeline._run_dir(tmp_path, state)

    judgment.write_request(run_dir, "review_opportunities", state.run_id, "test", [], generated_at="t0")
    judgment.write_response(
        run_dir, "review_opportunities",
        [{"problem_id": "P-0001", "decision": "SCARCITY_PRIORITY", "rationale": "severe loss despite low demand"}],
        judged_at="t1",
    )

    pipeline._stage_review_opportunities(conn, tmp_path, options, state)
    row = conn.execute("SELECT decision FROM opportunities WHERE problem_id = 'P-0001'").fetchone()
    assert row["decision"] == "RESEARCH_MORE"
    conn.close()


def test_eligible_opportunities_excludes_c_grade_even_if_decision_is_generate_titles(tmp_path):
    """Defense-in-depth: even if a C-grade row somehow has decision=GENERATE_TITLES
    (e.g. a future bug upstream, or direct DB manipulation), the title-generation
    gate itself must still exclude it."""
    conn = db.connect(tmp_path)
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, status) VALUES "
        "('P-0001', 'small firms', 'track renewals', 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
        "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, updated_at) "
        "VALUES ('P-0001', 80, 12.0, 40, 'C', 90, 'A', 'GENERATE_TITLES', '[]', '[]', 't0')"
    )
    conn.commit()
    assert pipeline._eligible_opportunities(conn) == []
    conn.close()


def test_stage_review_opportunities_skips_when_no_opportunities(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    pipeline._stage_review_opportunities(conn, tmp_path, options, state)  # should not raise
    conn.close()


# ---------------------------------------------------------------------------
# 데이터원별 신뢰도 보정 (source_reliability.py) 판정 컨텍스트 연동
# ---------------------------------------------------------------------------


def test_stage_collect_and_verify_supply_includes_source_reliability_in_product_item(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_run_or_raise", lambda *a, **k: None)
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_demand_passed_problem_with_candidate(conn)
    conn.execute(
        "INSERT INTO source_reliability (source, demand_problem_total, demand_problem_passed, "
        "demand_reliability_score, demand_reliability_status, supply_candidate_total, "
        "supply_candidate_active, supply_reliability_score, supply_reliability_status, updated_at) "
        "VALUES ('hn_show', 5, 1, 0.2, 'CALIBRATED', 5, 4, 0.8, 'CALIBRATED', 't0')"
    )
    conn.commit()

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        pipeline._stage_collect_and_verify_supply(conn, tmp_path, options, state)
    conn.close()

    request_doc = json.loads(excinfo.value.request_path.read_text(encoding="utf-8"))
    product_items = [item for item in request_doc["items"] if item["kind"] == "product"]
    assert product_items[0]["source_reliability"]["supply_reliability_score"] == 0.8
    assert "source_reliability" in request_doc["instructions"]


def test_stage_collect_and_verify_supply_source_reliability_none_when_unknown_source(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_run_or_raise", lambda *a, **k: None)
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_demand_passed_problem_with_candidate(conn)

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        pipeline._stage_collect_and_verify_supply(conn, tmp_path, options, state)
    conn.close()

    request_doc = json.loads(excinfo.value.request_path.read_text(encoding="utf-8"))
    product_items = [item for item in request_doc["items"] if item["kind"] == "product"]
    assert product_items[0]["source_reliability"] is None


def test_stage_review_opportunities_includes_evidence_source_reliability(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_opportunity(conn)
    conn.execute("INSERT INTO hn_items (id, type, by, time, fetched_at, source) VALUES (1, 'story', 'alice', 100, 't0', 'gh_archive')")
    conn.execute(
        "INSERT INTO problem_evidence (evidence_id, problem_id, item_id, author, excerpt) "
        "VALUES ('E-0001', 'P-0001', 1, 'alice', 'x')"
    )
    conn.execute(
        "UPDATE opportunities SET evidence_ids = '[\"E-0001\"]' WHERE problem_id = 'P-0001'"
    )
    conn.execute(
        "INSERT INTO source_reliability (source, demand_problem_total, demand_problem_passed, "
        "demand_reliability_score, demand_reliability_status, supply_candidate_total, "
        "supply_candidate_active, supply_reliability_score, supply_reliability_status, updated_at) "
        "VALUES ('gh_archive', 10, 0, 0.0, 'CALIBRATED', 0, 0, NULL, 'NO_DATA', 't0')"
    )
    conn.commit()

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        pipeline._stage_review_opportunities(conn, tmp_path, options, state)
    conn.close()

    request_doc = json.loads(excinfo.value.request_path.read_text(encoding="utf-8"))
    item = request_doc["items"][0]
    assert item["evidence_source_reliability"]["gh_archive"]["demand_reliability_score"] == 0.0
    assert "evidence_source_reliability" in request_doc["instructions"]


def test_stage_review_opportunities_evidence_source_reliability_empty_when_no_evidence(tmp_path):
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_opportunity(conn)  # evidence_ids defaults to '[]'

    with pytest.raises(judgment.JudgmentRequired) as excinfo:
        pipeline._stage_review_opportunities(conn, tmp_path, options, state)
    conn.close()

    request_doc = json.loads(excinfo.value.request_path.read_text(encoding="utf-8"))
    assert request_doc["items"][0]["evidence_source_reliability"] == {}


def test_stage_update_memory_and_git_checkpoint_runs_source_reliability_calibration(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline, "_run_or_raise", lambda project_root, script_name, *extra: calls.append(script_name)
    )
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)

    pipeline._stage_update_memory_and_git_checkpoint(conn, tmp_path, options, state)
    conn.close()

    assert calls[0] == "calibrate_source_reliability.py"
    assert "git_checkpoint.py" in calls


# ---------------------------------------------------------------------------
# generate_and_review_titles round loop
# ---------------------------------------------------------------------------


def seed_eligible_opportunities(conn, count, target_users=None):
    for i in range(count):
        problem_id = f"P-{i:04d}"
        conn.execute(
            "INSERT INTO problems (problem_id, target_user, task, pain, desired_outcome, status) VALUES "
            "(?, 'firms', 'track thing', 'pain', 'result', 'DEMAND_PASSED')",
            (problem_id,),
        )
        conn.execute(
            "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
            "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, updated_at) "
            "VALUES (?, 80, 1.0, 85, 'S', ?, 'A', 'GENERATE_TITLES', '[]', '[]', 't0')",
            (problem_id, 90 - i),
        )
    conn.commit()


WORD_PAIRS = [
    "Vendor Guard", "Permit Flow", "Claim Tracker", "Audit Radar", "Roster Sync",
    "Signal Watch", "Bridge Route", "Anchor Point", "Beacon Path", "Cipher Lock",
]


def make_word_pair_titles(problem_id, slot_count, round_no):
    idx = int(problem_id.split("-")[1])
    return [WORD_PAIRS[(idx + n) % len(WORD_PAIRS)] for n in range(slot_count)]


def respond_to_generation(run_dir, run_id, round_no, titles_per_problem):
    request = judgment.request_path(run_dir, "generate_titles", round_no)
    request_doc = json.loads(request.read_text(encoding="utf-8"))
    decisions = []
    for item in request_doc["items"]:
        titles = titles_per_problem(item["problem_id"], item["slot_count"], round_no)
        decisions.append({"problem_id": item["problem_id"], "titles": titles})
    judgment.write_response(run_dir, "generate_titles", decisions, round_no=round_no, judged_at="t")


def respond_to_review(run_dir, run_id, round_no, approve_all=True):
    request = judgment.request_path(run_dir, "review_titles", round_no)
    request_doc = json.loads(request.read_text(encoding="utf-8"))
    decisions = [{"title": item["title"], "approve": approve_all, "reason": ""} for item in request_doc["items"]]
    judgment.write_response(run_dir, "review_titles", decisions, round_no=round_no, judged_at="t")


def test_generate_and_review_titles_completes_in_one_round_when_enough_approved(tmp_path):
    options = make_options(tmp_path, target_count=5, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    conn = db.connect(tmp_path)
    seed_eligible_opportunities(conn, 5)
    run_dir = pipeline._run_dir(tmp_path, state)

    # round 1: generate
    with pytest.raises(judgment.JudgmentRequired):
        pipeline._stage_generate_and_review_titles(conn, tmp_path, options, state)
    run_state.save(tmp_path, state)
    respond_to_generation(run_dir, state.run_id, 1, make_word_pair_titles)

    # round 1: review (consumes generation, then pauses for review)
    with pytest.raises(judgment.JudgmentRequired):
        pipeline._stage_generate_and_review_titles(conn, tmp_path, options, state)
    run_state.save(tmp_path, state)
    respond_to_review(run_dir, state.run_id, 1, approve_all=True)

    # consumes review; enough approved -> returns normally
    pipeline._stage_generate_and_review_titles(conn, tmp_path, options, state)

    approved = conn.execute(
        "SELECT COUNT(*) c FROM titles WHERE run_id = ? AND status = 'approved'", (state.run_id,)
    ).fetchone()["c"]
    assert approved >= 5
    conn.close()


def test_generate_and_review_titles_no_eligible_opportunities_is_capability_stagnation(tmp_path):
    """design 11: zero opportunities to generate from at all - across zero
    approved titles - is CAPABILITY_STAGNATION, not plain RETRYING (this
    run's current data/approach cannot produce anything, not just "not
    enough yet"). Still raised as RetryRequired (same retry mechanics)."""
    options = make_options(tmp_path, target_count=20, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    with pytest.raises(pipeline.RetryRequired) as excinfo:
        pipeline._stage_generate_and_review_titles(conn, tmp_path, options, state)
    assert state.status == "CAPABILITY_STAGNATION"
    assert excinfo.value.status == "CAPABILITY_STAGNATION"
    # design 2.3/9.3: a shortfall must persist whatever partial result exists
    # to output/_pipeline/intermediate/, never silently only in the DB.
    intermediate = tmp_path / "output" / "_pipeline" / "intermediate" / f"{state.run_id}_shortfall_titles.txt"
    assert intermediate.exists()
    conn.close()


def test_generate_and_review_titles_exhausts_max_rounds_with_zero_progress_is_capability_stagnation(tmp_path):
    """design 11: exhausting every round while landing zero titles the whole
    time is CAPABILITY_STAGNATION, not RETRYING - the opportunity pool
    produced nothing no matter how many rounds it got."""
    options = make_options(tmp_path, target_count=20, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    conn = db.connect(tmp_path)
    seed_eligible_opportunities(conn, 5)
    run_dir = pipeline._run_dir(tmp_path, state)

    def make_no_titles(problem_id, slot_count, round_no):
        return []  # judgment refuses to produce anything -> guaranteed shortfall

    # Empty generations leave nothing pending review, so the state machine
    # skips straight to the next round's generation request within a single
    # call - it only ever pauses on "generate_titles", never "review_titles".
    retried = False
    for _ in range(pipeline.title_generation.MAX_ROUNDS + 2):  # safety bound
        try:
            pipeline._stage_generate_and_review_titles(conn, tmp_path, options, state)
        except judgment.JudgmentRequired:
            run_state.save(tmp_path, state)
            current_round = state.context["title_round"]
            respond_to_generation(run_dir, state.run_id, current_round, make_no_titles)
            continue
        except pipeline.RetryRequired:
            retried = True
            break

    assert retried, "expected RetryRequired after exhausting max rounds"
    assert state.status == "CAPABILITY_STAGNATION"


def test_generate_and_review_titles_exhausts_max_rounds_with_partial_progress_stays_retrying(tmp_path):
    """Contrast case: SOME titles were approved before rounds ran out - the
    pool clearly can produce something, just not enough yet, so this stays
    ordinary RETRYING rather than escalating to CAPABILITY_STAGNATION."""
    options = make_options(tmp_path, target_count=20, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    conn = db.connect(tmp_path)
    seed_eligible_opportunities(conn, 5)
    run_dir = pipeline._run_dir(tmp_path, state)

    first_round = True

    def make_a_few_then_nothing(problem_id, slot_count, round_no):
        nonlocal first_round
        if first_round:
            first_round = False
            return make_word_pair_titles(problem_id, slot_count, round_no)
        return []

    retried = False
    for _ in range(pipeline.title_generation.MAX_ROUNDS + 2):
        try:
            pipeline._stage_generate_and_review_titles(conn, tmp_path, options, state)
        except judgment.JudgmentRequired:
            run_state.save(tmp_path, state)
            current_round = state.context["title_round"]
            if state.context["title_phase"] == "review":
                respond_to_review(run_dir, state.run_id, current_round, approve_all=True)
            else:
                respond_to_generation(run_dir, state.run_id, current_round, make_a_few_then_nothing)
            continue
        except pipeline.RetryRequired:
            retried = True
            break

    assert retried, "expected RetryRequired after exhausting max rounds"
    assert state.status == "RETRYING"
    intermediate = tmp_path / "output" / "_pipeline" / "intermediate" / f"{state.run_id}_shortfall_titles.txt"
    assert intermediate.exists()
    conn.close()


# ---------------------------------------------------------------------------
# validate_outputs / publish_mode_outputs
# ---------------------------------------------------------------------------

_ADJECTIVES = [
    "Vendor", "Permit", "Claim", "Audit", "Roster", "Signal", "Bridge", "Anchor", "Beacon", "Cipher",
    "Delta", "Falcon", "Grove", "Harbor", "Ivory", "Jasper", "Kelvin", "Lumen", "Mosaic", "Nectar",
    "Onyx", "Pixel", "Quartz", "Raven", "Solace",
]
_NOUNS = [
    "Guard", "Flow", "Tracker", "Radar", "Sync", "Watch", "Route", "Point", "Path", "Lock",
    "Portal", "Ledger", "Circuit", "Vault", "Grid", "Relay", "Cache", "Frame", "Panel", "Nexus",
]


def unique_titles(count: int) -> list[str]:
    titles = []
    for adjective in _ADJECTIVES:
        for noun in _NOUNS:
            title = f"{adjective} {noun}"
            titles.append(title)
            if len(titles) >= count:
                return titles
    raise ValueError("word bank too small for requested count")


def seed_approved_titles(conn, run_id, count, opportunity_count=8):
    from saas_words_two.contracts import normalize_title as _norm

    titles = unique_titles(count)
    opportunity_count = min(opportunity_count, count)
    for i in range(opportunity_count):
        problem_id = f"P-{i:04d}"
        conn.execute("INSERT INTO problems (problem_id, status) VALUES (?, 'DEMAND_PASSED')", (problem_id,))
        conn.execute(
            "INSERT INTO opportunities (problem_id, demand_score, effective_supply, supply_scarcity_score, "
            "scarcity_grade, priority_score, confidence, decision, evidence_ids, product_ids, updated_at) "
            "VALUES (?, 80, 1.0, 85, 'S', ?, 'A', 'GENERATE_TITLES', '[]', '[]', 't0')",
            (problem_id, 100 - i),
        )
    for i, title in enumerate(titles):
        problem_id = f"P-{i % opportunity_count:04d}"
        conn.execute(
            "INSERT INTO titles (title, normalized, problem_id, run_id, status, created_at) "
            "VALUES (?, ?, ?, ?, 'approved', ?)",
            (title, _norm(title), problem_id, run_id, "2026-08-10T20:00:00+09:00"),
        )
    conn.commit()
    return titles


def test_stage_validate_outputs_excludes_brand_conflict_title_and_persists_calibration(tmp_path):
    """design 4.8: an explicit user-flagged brand conflict must be excluded
    from final selection outright, and the calibration fields must be
    persisted on the titles rows for every approved title, not just the
    excluded one."""
    options = make_options(tmp_path, target_count=20, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    conn = db.connect(tmp_path)
    titles = seed_approved_titles(conn, state.run_id, 21)  # one extra so excluding 1 still hits 20

    ledger_path = tmp_path / "memory" / "human_feedback" / "google_supply_observations.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    conflicted_title = titles[0]  # "Vendor Guard" - problem P-0000, highest priority (100)
    observation = {
        "query_type": "TITLE_QUERY",
        "title": conflicted_title,
        "user_result_count": 5,
        "top_results_relevant": None,
        "user_notes": "TITLE_BRAND_CONFLICT: same name as an existing SaaS product",
    }
    ledger_path.write_text(json.dumps(observation) + "\n", encoding="utf-8")

    pipeline._stage_validate_outputs(conn, tmp_path, options, state)

    selected_titles = {
        row["title"]
        for row in conn.execute(
            "SELECT title FROM titles WHERE run_id = ? AND status = 'selected'", (state.run_id,)
        ).fetchall()
    }
    assert len(selected_titles) == 20
    assert conflicted_title not in selected_titles

    conflicted_row = conn.execute(
        "SELECT * FROM titles WHERE run_id = ? AND title = ?", (state.run_id, conflicted_title)
    ).fetchone()
    assert conflicted_row["google_title_collision_class"] == "BRAND_CONFLICT"
    assert conflicted_row["human_title_validation_count"] == 1
    assert conflicted_row["status"] == "approved"  # excluded from selection, not force-rejected

    other_row = conn.execute(
        "SELECT * FROM titles WHERE run_id = ? AND title = ?", (state.run_id, titles[1])
    ).fetchone()
    assert other_row["human_title_validation_count"] == 0
    assert other_row["google_title_collision_class"] is None
    conn.close()


def test_stage_validate_outputs_selects_exact_target_and_marks_selected(tmp_path):
    options = make_options(tmp_path, target_count=20, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    conn = db.connect(tmp_path)
    seed_approved_titles(conn, state.run_id, 25)  # more than target, forces trimming

    pipeline._stage_validate_outputs(conn, tmp_path, options, state)

    selected = conn.execute(
        "SELECT COUNT(*) c FROM titles WHERE run_id = ? AND status = 'selected'", (state.run_id,)
    ).fetchone()["c"]
    assert selected == 20
    assert len(state.context["final_titles"]) == 20
    conn.close()


def test_stage_validate_outputs_retries_when_cap_prevents_reaching_target(tmp_path):
    options = make_options(tmp_path, target_count=20, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    conn = db.connect(tmp_path)
    # only 2 opportunities -> cap = floor(20*0.3) = 6 each -> max 12 achievable, short of 20
    seed_approved_titles(conn, state.run_id, 15, opportunity_count=2)

    with pytest.raises(pipeline.RetryRequired):
        pipeline._stage_validate_outputs(conn, tmp_path, options, state)
    assert state.status == "RETRYING"
    intermediate = tmp_path / "output" / "_pipeline" / "intermediate" / f"{state.run_id}_shortfall_titles.txt"
    assert intermediate.exists()
    # 12 titles survive the 30%-per-opportunity cap (2 opportunities x 6 each), short of 20
    saved = [line for line in intermediate.read_text(encoding="utf-8").splitlines() if line]
    assert len(saved) == 12
    conn.close()


def test_stage_publish_mode_outputs_qa_does_not_touch_shared_history(tmp_path):
    history_path = tmp_path / "output" / "deliverables" / "history" / "words.txt"
    history_path.parent.mkdir(parents=True)
    history_path.write_text("Existing One\n", encoding="utf-8")

    options = make_options(tmp_path, target_count=20, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    with_qa_history_snapshot(tmp_path, state)
    conn = db.connect(tmp_path)
    seed_approved_titles(conn, state.run_id, 20)
    pipeline._stage_validate_outputs(conn, tmp_path, options, state)

    checksum_before = history_path.read_bytes()
    pipeline._stage_publish_mode_outputs(conn, tmp_path, options, state)
    checksum_after = history_path.read_bytes()

    assert checksum_before == checksum_after
    qa_final = tmp_path / "output" / "_pipeline" / "qa" / state.run_id / "generated" / "saas_words_qa.txt"
    assert qa_final.exists()
    assert len(qa_final.read_text(encoding="utf-8").splitlines()) == 20
    assert not (tmp_path / "output" / "deliverables" / "generated").exists()
    conn.close()


def test_stage_publish_mode_outputs_production_updates_history_atomically(tmp_path):
    options = make_options(tmp_path, mode="production", target_count=20, run_id="RUN-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_approved_titles(conn, state.run_id, 20)
    pipeline._stage_validate_outputs(conn, tmp_path, options, state)

    pipeline._stage_publish_mode_outputs(conn, tmp_path, options, state)

    final_path = tmp_path / "output" / "deliverables" / "generated" / state.context["generated_filename"]
    assert final_path.exists()
    assert len(final_path.read_text(encoding="utf-8").splitlines()) == 20

    history_path = tmp_path / "output" / "deliverables" / "history" / "words.txt"
    assert len(history_path.read_text(encoding="utf-8").splitlines()) == 20

    assert (tmp_path / "output" / "_pipeline" / "final" / "opportunities.jsonl").exists()
    conn.close()


def test_stage_publish_mode_outputs_history_mismatch_raises_recovery_required(tmp_path, monkeypatch):
    """design 11 RECOVERY_REQUIRED: if the on-disk history file's new tail
    doesn't match what this run was supposed to append (simulated here via a
    monkeypatched write that "corrupts" the result), the stage must halt
    rather than silently treating the run as complete or blindly retrying."""
    options = make_options(tmp_path, mode="production", target_count=20, run_id="RUN-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_approved_titles(conn, state.run_id, 20)
    pipeline._stage_validate_outputs(conn, tmp_path, options, state)

    real_atomic_write_text = pipeline.atomic_write_text
    history_path = tmp_path / "output" / "deliverables" / "history" / "words.txt"

    def corrupting_write(path, content):
        if path == history_path:
            real_atomic_write_text(path, "Unexpected Content\n")
            return
        real_atomic_write_text(path, content)

    monkeypatch.setattr(pipeline, "atomic_write_text", corrupting_write)

    with pytest.raises(pipeline.RecoveryRequired):
        pipeline._stage_publish_mode_outputs(conn, tmp_path, options, state)
    assert state.status == "RECOVERY_REQUIRED"
    conn.close()


def test_stage_publish_mode_outputs_production_appends_to_existing_history(tmp_path):
    history_path = tmp_path / "output" / "deliverables" / "history" / "words.txt"
    history_path.parent.mkdir(parents=True)
    history_path.write_text("Old Title\n", encoding="utf-8")

    options = make_options(tmp_path, mode="production", target_count=20, run_id="RUN-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_approved_titles(conn, state.run_id, 20)
    pipeline._stage_validate_outputs(conn, tmp_path, options, state)
    pipeline._stage_publish_mode_outputs(conn, tmp_path, options, state)

    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Old Title"
    assert len(lines) == 21
    conn.close()


def test_stage_publish_mode_outputs_resume_does_not_double_append_history(tmp_path):
    """Regression: if publish succeeds once, then this stage is re-entered
    (crash + --resume, or an operator re-running it), the same titles must
    not be appended to words.txt a second time."""
    options = make_options(tmp_path, mode="production", target_count=20, run_id="RUN-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_approved_titles(conn, state.run_id, 20)
    pipeline._stage_validate_outputs(conn, tmp_path, options, state)

    pipeline._stage_publish_mode_outputs(conn, tmp_path, options, state)
    history_path = tmp_path / "output" / "deliverables" / "history" / "words.txt"
    first_pass_lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(first_pass_lines) == 20

    # simulate a resume re-entering the same stage with the same final_titles
    pipeline._stage_publish_mode_outputs(conn, tmp_path, options, state)
    second_pass_lines = history_path.read_text(encoding="utf-8").splitlines()

    assert second_pass_lines == first_pass_lines
    assert len(set(second_pass_lines)) == len(second_pass_lines)  # no duplicates
    conn.close()
