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
    snapshot_path = tmp_path / "output" / "qa" / state.run_id / "qa_history_snapshot.txt"
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
    history_path = tmp_path / "output" / "history" / "words.txt"
    history_path.parent.mkdir(parents=True)
    history_path.write_text("Vendor Guard\nPermit Flow\n", encoding="utf-8")

    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    pipeline._stage_load_state(conn, tmp_path, options, state)
    conn.close()

    snapshot_path = tmp_path / "output" / "qa" / state.run_id / "qa_history_snapshot.txt"
    assert snapshot_path.exists()
    assert "Vendor Guard" in snapshot_path.read_text(encoding="utf-8")
    assert state.context["qa_history_snapshot_path"] == str(snapshot_path)


def test_stage_load_state_snapshots_empty_history_as_truly_empty(tmp_path):
    """Regression: an empty output/history/words.txt must snapshot to a
    0-byte file, not "\n" - otherwise _read_lines() reads the snapshot back
    as [''] (one blank line) instead of [] (no lines), a mismatch with the
    real file the snapshot is supposed to mirror."""
    options = make_options(tmp_path, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    pipeline._stage_load_state(conn, tmp_path, options, state)
    conn.close()

    snapshot_path = tmp_path / "output" / "qa" / state.run_id / "qa_history_snapshot.txt"
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


def test_generate_and_review_titles_raises_retry_when_no_eligible_opportunities(tmp_path):
    options = make_options(tmp_path, target_count=20, run_id="QA-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    with pytest.raises(pipeline.RetryRequired):
        pipeline._stage_generate_and_review_titles(conn, tmp_path, options, state)
    assert state.status == "RETRYING"
    # design 2.3/9.3: a shortfall must persist whatever partial result exists
    # to output/intermediate/, never silently only in the DB.
    intermediate = tmp_path / "output" / "intermediate" / f"{state.run_id}_shortfall_titles.txt"
    assert intermediate.exists()
    conn.close()


def test_generate_and_review_titles_exhausts_max_rounds_and_retries(tmp_path):
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
    assert state.status == "RETRYING"
    intermediate = tmp_path / "output" / "intermediate" / f"{state.run_id}_shortfall_titles.txt"
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
    intermediate = tmp_path / "output" / "intermediate" / f"{state.run_id}_shortfall_titles.txt"
    assert intermediate.exists()
    # 12 titles survive the 30%-per-opportunity cap (2 opportunities x 6 each), short of 20
    saved = [line for line in intermediate.read_text(encoding="utf-8").splitlines() if line]
    assert len(saved) == 12
    conn.close()


def test_stage_publish_mode_outputs_qa_does_not_touch_shared_history(tmp_path):
    history_path = tmp_path / "output" / "history" / "words.txt"
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
    qa_final = tmp_path / "output" / "qa" / state.run_id / "generated" / "saas_words_qa.txt"
    assert qa_final.exists()
    assert len(qa_final.read_text(encoding="utf-8").splitlines()) == 20
    assert not (tmp_path / "output" / "generated").exists()
    conn.close()


def test_stage_publish_mode_outputs_production_updates_history_atomically(tmp_path):
    options = make_options(tmp_path, mode="production", target_count=20, run_id="RUN-20260810-190000-KST")
    state = pipeline._load_or_create_state(options)
    conn = db.connect(tmp_path)
    seed_approved_titles(conn, state.run_id, 20)
    pipeline._stage_validate_outputs(conn, tmp_path, options, state)

    pipeline._stage_publish_mode_outputs(conn, tmp_path, options, state)

    final_path = tmp_path / "output" / "generated" / state.context["generated_filename"]
    assert final_path.exists()
    assert len(final_path.read_text(encoding="utf-8").splitlines()) == 20

    history_path = tmp_path / "output" / "history" / "words.txt"
    assert len(history_path.read_text(encoding="utf-8").splitlines()) == 20

    assert (tmp_path / "output" / "final" / "opportunities.jsonl").exists()
    conn.close()


def test_stage_publish_mode_outputs_production_appends_to_existing_history(tmp_path):
    history_path = tmp_path / "output" / "history" / "words.txt"
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
    history_path = tmp_path / "output" / "history" / "words.txt"
    first_pass_lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(first_pass_lines) == 20

    # simulate a resume re-entering the same stage with the same final_titles
    pipeline._stage_publish_mode_outputs(conn, tmp_path, options, state)
    second_pass_lines = history_path.read_text(encoding="utf-8").splitlines()

    assert second_pass_lines == first_pass_lines
    assert len(set(second_pass_lines)) == len(second_pass_lines)  # no duplicates
    conn.close()
