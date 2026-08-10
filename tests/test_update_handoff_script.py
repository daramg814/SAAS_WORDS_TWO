import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_handoff as script


def test_render_handoff_includes_required_fields():
    content = script.render_handoff(
        status="PAUSED",
        current_stage="score_demand",
        last_verified="demand scoring batch tests pass",
        next_action="collect_supply_candidates",
    )
    assert "상태: `PAUSED`" in content
    assert "현재 단계: score_demand" in content
    assert "다음 원자 작업: collect_supply_candidates" in content
    assert "주의:" not in content


def test_render_handoff_includes_optional_caution_and_prohibited():
    content = script.render_handoff(
        status="RUNNING",
        current_stage="x",
        last_verified="y",
        next_action="z",
        caution="주의 문구",
        prohibited="금지 문구",
    )
    assert "주의: 주의 문구" in content
    assert "금지: 금지 문구" in content


def test_update_handoff_writes_file(tmp_path):
    path = script.update_handoff(
        tmp_path,
        status="PAUSED",
        current_stage="x",
        last_verified="y",
        next_action="z",
    )
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("# HANDOFF")


def test_main_writes_handoff(tmp_path):
    exit_code = script.main(
        [
            "--project-root",
            str(tmp_path),
            "--status",
            "PAUSED",
            "--current-stage",
            "x",
            "--last-verified",
            "y",
            "--next-action",
            "z",
        ]
    )
    assert exit_code == 0
    assert (tmp_path / "memory" / "HANDOFF.md").exists()
