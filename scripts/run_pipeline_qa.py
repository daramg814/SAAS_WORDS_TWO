
from __future__ import annotations

import argparse
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="qa", choices=("qa",))
    p.add_argument("--round-size", type=int, default=None)
    args = p.parse_args(argv)
    cmd = [sys.executable, "run.py", "--mode", "qa"]
    if args.round_size is not None:
        cmd += ["--round-size", str(args.round_size)]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
