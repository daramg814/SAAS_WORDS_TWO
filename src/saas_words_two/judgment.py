from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import atomic_write_text


class JudgmentRequired(Exception):
    """Raised when a pipeline stage needs semantic judgment from the running
    Claude Code session (or a subagent it calls) before it can continue.

    This is a controlled pause, not a failure: the caller writes a response
    file per the request's schema and re-runs with --resume to continue.
    """

    def __init__(self, stage: str, request_path: Path, round_no: int = 1):
        self.stage = stage
        self.request_path = request_path
        self.round_no = round_no
        super().__init__(
            f"AWAITING_JUDGMENT stage={stage} round={round_no} request={request_path} "
            "- write the judgment response and re-run with --resume"
        )


def _judgment_dir(run_directory: Path) -> Path:
    return run_directory / "judgment"


def request_path(run_directory: Path, stage: str, round_no: int = 1) -> Path:
    return _judgment_dir(run_directory) / f"{stage}_round{round_no}_request.json"


def response_path(run_directory: Path, stage: str, round_no: int = 1) -> Path:
    return _judgment_dir(run_directory) / f"{stage}_round{round_no}_response.json"


def _canonical_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def write_request(
    run_directory: Path,
    stage: str,
    run_id: str,
    instructions: str,
    items: list[dict],
    *,
    round_no: int = 1,
    generated_at: str,
) -> Path:
    payload = {"stage": stage, "run_id": run_id, "round": round_no, "items": items}
    request_hash = _canonical_hash(payload)
    document = {
        **payload,
        "instructions": instructions,
        "generated_at": generated_at,
        "request_hash": request_hash,
    }
    path = request_path(run_directory, stage, round_no)
    atomic_write_text(path, json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def has_response(run_directory: Path, stage: str, round_no: int = 1) -> bool:
    return response_path(run_directory, stage, round_no).exists()


def read_response(run_directory: Path, stage: str, round_no: int = 1) -> dict:
    req_path = request_path(run_directory, stage, round_no)
    res_path = response_path(run_directory, stage, round_no)
    if not req_path.exists():
        raise FileNotFoundError(f"no judgment request at {req_path}")
    if not res_path.exists():
        raise FileNotFoundError(f"no judgment response at {res_path}")
    request_doc = json.loads(req_path.read_text(encoding="utf-8"))
    response_doc = json.loads(res_path.read_text(encoding="utf-8"))
    if response_doc.get("request_hash") != request_doc.get("request_hash"):
        raise ValueError(
            f"judgment response request_hash mismatch for stage={stage} round={round_no}: "
            "the request changed since this response was written"
        )
    if "decisions" not in response_doc:
        raise ValueError(f"judgment response missing 'decisions' for stage={stage} round={round_no}")
    return response_doc


def write_response(
    run_directory: Path,
    stage: str,
    decisions: list[dict],
    *,
    round_no: int = 1,
    judged_at: str,
    judged_by: str = "main-orchestrator",
) -> Path:
    req_path = request_path(run_directory, stage, round_no)
    if not req_path.exists():
        raise FileNotFoundError(f"no judgment request at {req_path}")
    request_doc = json.loads(req_path.read_text(encoding="utf-8"))
    document = {
        "stage": stage,
        "run_id": request_doc["run_id"],
        "round": round_no,
        "request_hash": request_doc["request_hash"],
        "judged_at": judged_at,
        "judged_by": judged_by,
        "decisions": decisions,
    }
    path = response_path(run_directory, stage, round_no)
    atomic_write_text(path, json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path
