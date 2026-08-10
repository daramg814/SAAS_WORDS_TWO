"""후보 문제 문장을 코드 기반 패턴으로 선별한다."""

from __future__ import annotations

import argparse
from pathlib import Path

from saas_words_two import db, ids, text_filter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    project_root = args.project_root
    conn = db.connect(project_root)
    try:
        summary = text_filter.run_filter_pass(conn, created_at=ids.now_kst().isoformat())
    finally:
        conn.close()

    print(
        f"CANDIDATE SENTENCES: source_items={summary.source_items} "
        f"before_dedupe={summary.candidates_before_dedupe} "
        f"after_dedupe={summary.candidates_after_dedupe} "
        f"reduction_from_source_units={summary.reduction_from_source_units_pct:.1f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
