
from __future__ import annotations

import argparse
from pathlib import Path

from saas_words_two.contracts import atomic_write_text, validate_title_set


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("candidate_file", type=Path)
    p.add_argument("final_file", type=Path)
    p.add_argument("--target-count", type=int, required=True)
    p.add_argument("--mode", choices=("production", "qa"), required=True)
    p.add_argument("--history", type=Path, default=Path("output/deliverables/history/words.txt"))
    p.add_argument("--blocklist", type=Path, default=Path("input/blocklist.txt"))
    args = p.parse_args(argv)

    titles = lines(args.candidate_file)
    history = lines(args.history)
    errors = validate_title_set(titles, target_count=args.target_count, history=history, blocklist=lines(args.blocklist))
    if errors:
        for e in errors:
            print(e)
        return 1

    content = "\n".join(titles) + "\n"
    atomic_write_text(args.final_file, content)
    if args.mode == "production":
        atomic_write_text(args.history, "\n".join(history + titles) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
