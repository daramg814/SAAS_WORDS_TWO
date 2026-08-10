
from __future__ import annotations

import argparse
from pathlib import Path

from saas_words_two.contracts import validate_title_set


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("title_file", type=Path)
    p.add_argument("--target-count", type=int, required=True)
    p.add_argument("--history", type=Path, default=Path("output/history/words.txt"))
    p.add_argument("--blocklist", type=Path, default=Path("input/blocklist.txt"))
    args = p.parse_args(argv)

    errors = validate_title_set(
        read_lines(args.title_file),
        target_count=args.target_count,
        history=read_lines(args.history),
        blocklist=read_lines(args.blocklist),
    )
    if errors:
        print("OUTPUT VALIDATION: FAIL")
        for error in errors:
            print(error)
        return 1
    print("OUTPUT VALIDATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
