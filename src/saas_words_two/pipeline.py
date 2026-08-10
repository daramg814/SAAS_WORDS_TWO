
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ImplementationPendingError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunOptions:
    mode: str
    target_count: int
    project_root: Path

    def validate(self) -> None:
        if self.mode not in {"production", "qa"}:
            raise ValueError("mode must be production or qa")
        if self.mode == "production" and self.target_count != 500:
            raise ValueError("production target_count must be exactly 500")
        if self.mode == "qa" and self.target_count < 10:
            raise ValueError("qa target_count must be at least 10")


STAGES = (
    "load_state",
    "source_access_test",
    "collect_sources",
    "filter_pain_sentences",
    "extract_and_cluster_problems",
    "score_demand",
    "collect_and_verify_supply",
    "score_opportunities",
    "review_opportunities",
    "generate_and_review_titles",
    "validate_outputs",
    "publish_mode_outputs",
    "build_google_validation_queue",
    "import_and_apply_human_feedback",
    "update_memory_and_git_checkpoint",
)


def run_pipeline(options: RunOptions) -> int:
    options.validate()
    raise ImplementationPendingError(
        "Pipeline implementation is intentionally pending. Start with HN access testing and "
        "incremental collection per docs/implementation/14-implementation-roadmap.md."
    )
