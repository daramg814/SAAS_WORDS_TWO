from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import atomic_write_text

VALID_STATUSES = {
    "RUNNING",
    "RETRYING",
    "CAPABILITY_STAGNATION",
    "COMMIT_PENDING",
    "RECOVERY_REQUIRED",
    "PAUSED",
    "FAILED",
    "DONE",
}


@dataclass
class RunState:
    run_id: str
    mode: str
    target_title_count: int
    status: str
    stage: str
    created_at: str
    updated_at: str
    awaiting_judgment: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {self.status}")
        payload = {
            "run_id": self.run_id,
            "mode": self.mode,
            "target_title_count": self.target_title_count,
            "status": self.status,
            "stage": self.stage,
            "awaiting_judgment": self.awaiting_judgment,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "context": self.context,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> RunState:
        data = json.loads(text)
        return cls(
            run_id=data["run_id"],
            mode=data["mode"],
            target_title_count=data["target_title_count"],
            status=data["status"],
            stage=data["stage"],
            awaiting_judgment=data.get("awaiting_judgment"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            context=data.get("context", {}),
        )


def run_dir(project_root: Path, run_id: str) -> Path:
    return project_root / "output" / "runs" / run_id


def state_path(project_root: Path, run_id: str) -> Path:
    return run_dir(project_root, run_id) / "run_state.json"


def load(project_root: Path, run_id: str) -> RunState:
    return RunState.from_json(state_path(project_root, run_id).read_text(encoding="utf-8"))


def save(project_root: Path, state: RunState) -> None:
    atomic_write_text(state_path(project_root, state.run_id), state.to_json())


def exists(project_root: Path, run_id: str) -> bool:
    return state_path(project_root, run_id).exists()


def latest_run_id(project_root: Path, mode: str) -> str | None:
    runs_root = project_root / "output" / "runs"
    if not runs_root.exists():
        return None
    prefix = "QA-" if mode == "qa" else "RUN-"
    candidates = sorted(
        (p.name for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(prefix)),
    )
    return candidates[-1] if candidates else None
