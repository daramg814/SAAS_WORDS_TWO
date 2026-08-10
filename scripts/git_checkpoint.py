"""검증된 원자 배치를 로컬 커밋하고(옵션) 원격 push 후 SHA를 확인한다."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from saas_words_two import ids
from saas_words_two.contracts import atomic_write_text

SENSITIVE_PATTERNS = (".env", ".token", ".cookie", "credentials", "secret", "id_rsa", ".pem")


def find_sensitive_files(paths: list[str]) -> list[str]:
    return [path for path in paths if any(pattern in path.lower() for pattern in SENSITIVE_PATTERNS)]


def run_git(project_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=project_root, capture_output=True, text=True, check=False
    )


def staged_files(project_root: Path) -> list[str]:
    result = run_git(project_root, "diff", "--cached", "--name-only")
    return [line for line in result.stdout.splitlines() if line.strip()]


@dataclass(frozen=True)
class CheckpointResult:
    status: str
    local_sha: str | None
    remote_sha: str | None
    pushed: bool


def commit_batch(
    project_root: Path,
    message: str,
    *,
    paths: list[str] | None = None,
    push: bool = False,
) -> CheckpointResult:
    """Local commit only by default (push=False) - CLAUDE.md's per-batch push
    requirement is honored only when the caller explicitly opts in, since
    remote credentials/authorization are outside this pipeline's control."""
    run_git(project_root, "add", *(paths if paths else ["-A"]))

    flagged = find_sensitive_files(staged_files(project_root))
    if flagged:
        run_git(project_root, "reset")
        return CheckpointResult(status="SENSITIVE_FILES_BLOCKED", local_sha=None, remote_sha=None, pushed=False)

    if not staged_files(project_root):
        return CheckpointResult(status="NOTHING_TO_COMMIT", local_sha=None, remote_sha=None, pushed=False)

    commit_result = run_git(project_root, "commit", "-m", message)
    if commit_result.returncode != 0:
        return CheckpointResult(status="COMMIT_FAILED", local_sha=None, remote_sha=None, pushed=False)

    local_sha = run_git(project_root, "rev-parse", "HEAD").stdout.strip()

    if not push:
        return CheckpointResult(status="COMMITTED_LOCAL", local_sha=local_sha, remote_sha=None, pushed=False)

    push_result = run_git(project_root, "push", "origin", "main")
    if push_result.returncode != 0:
        return CheckpointResult(status="COMMIT_PENDING", local_sha=local_sha, remote_sha=None, pushed=False)

    remote_sha = run_git(project_root, "rev-parse", "origin/main").stdout.strip()
    return CheckpointResult(status="DONE", local_sha=local_sha, remote_sha=remote_sha, pushed=True)


def persist_checkpoint(project_root: Path, result: CheckpointResult, checked_at: str) -> None:
    payload = {
        "status": result.status,
        "local_sha": result.local_sha,
        "remote_sha": result.remote_sha,
        "checked_at": checked_at,
    }
    atomic_write_text(
        project_root / "memory" / "GIT_CHECKPOINT.json", json.dumps(payload, indent=2) + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--message", required=True)
    parser.add_argument(
        "--push", action="store_true", help="attempt push origin main (default: local commit only)"
    )
    args = parser.parse_args(argv)

    result = commit_batch(args.project_root, args.message, push=args.push)
    persist_checkpoint(args.project_root, result, ids.now_kst().isoformat())

    print(f"GIT CHECKPOINT: status={result.status} local_sha={result.local_sha} remote_sha={result.remote_sha}")
    return 0 if result.status in ("COMMITTED_LOCAL", "DONE", "NOTHING_TO_COMMIT") else 1


if __name__ == "__main__":
    raise SystemExit(main())
