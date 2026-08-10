
from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import ImplementationPendingError, RunOptions, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SAAS_WORDS_TWO pipeline")
    parser.add_argument("--mode", choices=("production", "qa"), required=True)
    parser.add_argument("--target-count", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = RunOptions(mode=args.mode, target_count=args.target_count, project_root=Path.cwd())
    try:
        return run_pipeline(options)
    except (ValueError, ImplementationPendingError) as exc:
        print(f"ERROR: {exc}")
        return 2
