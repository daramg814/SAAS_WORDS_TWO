
from __future__ import annotations

import argparse
from pathlib import Path

from .judgment import JudgmentRequired
from .pipeline import ImplementationPendingError, RecoveryRequired, RetryRequired, RunOptions, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SAAS_WORDS_TWO pipeline")
    parser.add_argument("--mode", choices=("production", "qa"), required=True)
    parser.add_argument("--target-count", type=int, required=True)
    parser.add_argument(
        "--resume", action="store_true", help="continue the latest (or --run-id) run for this mode"
    )
    parser.add_argument("--run-id", default=None, help="explicit run id to start or resume")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = RunOptions(
        mode=args.mode,
        target_count=args.target_count,
        project_root=Path.cwd(),
        resume=args.resume,
        run_id=args.run_id,
    )
    try:
        return run_pipeline(options)
    except JudgmentRequired as exc:
        print(f"AWAITING_JUDGMENT: {exc}")
        return 3
    except RetryRequired as exc:
        print(f"{exc.status}: {exc}")
        return 4
    except RecoveryRequired as exc:
        print(f"RECOVERY_REQUIRED: {exc}")
        return 5
    except (ValueError, ImplementationPendingError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 2
