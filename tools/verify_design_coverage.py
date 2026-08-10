
from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/design/source/claude_code_saas_high_demand_low_supply_two_word_design_v2.4.md"
COVERAGE = ROOT / "docs/design/DESIGN_COVERAGE.csv"
HASH_FILE = ROOT / "docs/design/source/SOURCE_SHA256.txt"


def main() -> int:
    headings = [line.rstrip() for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.startswith("#")]
    with COVERAGE.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    mapped = {row["source_heading"] for row in rows if row["status"] == "COVERED"}
    missing = [h for h in headings if h not in mapped]
    extra = sorted(mapped - set(headings))

    expected_hash = None
    for line in HASH_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("design_sha256="):
            expected_hash = line.split("=", 1)[1].strip()
    actual_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()

    target_missing = []
    for row in rows:
        for target in [x.strip() for x in row["target_document"].split("+")]:
            if target == "CLAUDE.md":
                target_path = ROOT / target
            else:
                target_path = ROOT / target
            if not target_path.exists():
                target_missing.append(str(target_path.relative_to(ROOT)))

    if missing or extra or target_missing or expected_hash != actual_hash:
        print("DESIGN COVERAGE: FAIL")
        if missing:
            print("Missing headings:")
            print("\n".join(missing))
        if extra:
            print("Extra mappings:")
            print("\n".join(extra))
        if target_missing:
            print("Missing target files:")
            print("\n".join(sorted(set(target_missing))))
        if expected_hash != actual_hash:
            print("Source checksum mismatch")
        return 1
    print(f"DESIGN COVERAGE: PASS ({len(headings)} headings, 0 missing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
