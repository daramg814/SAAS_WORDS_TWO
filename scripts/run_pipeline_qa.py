
from __future__ import annotations

import argparse
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="qa", choices=("qa",))
    p.add_argument("--target-count", type=int, default=20)
    args = p.parse_args(argv)
    return subprocess.call([sys.executable, "run.py", "--mode", "qa", "--target-count", str(args.target_count)])


if __name__ == "__main__":
    raise SystemExit(main())
