import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import git_checkpoint as script


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)


def test_find_sensitive_files_flags_known_patterns():
    flagged = script.find_sensitive_files([".env", "src/app.py", "secrets/api.token", "cookies.cookie"])
    assert ".env" in flagged
    assert "src/app.py" not in flagged
    assert "secrets/api.token" in flagged


def test_commit_batch_creates_local_commit(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    result = script.commit_batch(tmp_path, "test commit")
    assert result.status == "COMMITTED_LOCAL"
    assert result.local_sha
    assert not result.pushed


def test_commit_batch_nothing_to_commit_when_clean(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    script.commit_batch(tmp_path, "first commit")
    result = script.commit_batch(tmp_path, "second commit")
    assert result.status == "NOTHING_TO_COMMIT"


def test_commit_batch_blocks_sensitive_files(tmp_path):
    init_repo(tmp_path)
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    result = script.commit_batch(tmp_path, "should be blocked")
    assert result.status == "SENSITIVE_FILES_BLOCKED"
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert "A  .env" not in status.stdout  # unstaged after reset


def test_commit_batch_does_not_push_by_default(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    result = script.commit_batch(tmp_path, "no push")
    assert result.status == "COMMITTED_LOCAL"
    assert result.remote_sha is None


def test_commit_batch_push_failure_reports_commit_pending(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    # no remote configured -> push must fail
    result = script.commit_batch(tmp_path, "attempt push", push=True)
    assert result.status == "COMMIT_PENDING"
    assert result.local_sha  # commit itself still succeeded


def test_persist_checkpoint_writes_json(tmp_path):
    (tmp_path / "memory").mkdir()
    result = script.CheckpointResult(status="COMMITTED_LOCAL", local_sha="abc123", remote_sha=None, pushed=False)
    script.persist_checkpoint(tmp_path, result, "2026-08-10T20:00:00+09:00")
    data = json.loads((tmp_path / "memory" / "GIT_CHECKPOINT.json").read_text(encoding="utf-8"))
    assert data["status"] == "COMMITTED_LOCAL"
    assert data["local_sha"] == "abc123"


def test_main_end_to_end_local_commit(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    exit_code = script.main(["--project-root", str(tmp_path), "--message", "batch commit"])
    assert exit_code == 0
    data = json.loads((tmp_path / "memory" / "GIT_CHECKPOINT.json").read_text(encoding="utf-8"))
    assert data["status"] == "COMMITTED_LOCAL"
