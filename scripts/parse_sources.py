"""수집된 원문의 스키마·중복 ID·체크섬을 검증하고 DB 적재를 확정한다."""

from __future__ import annotations

import argparse
from pathlib import Path

from saas_words_two import db, ids, parsing
from saas_words_two.contracts import atomic_write_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    project_root = args.project_root
    conn = db.connect(project_root)
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM hn_items").fetchall()]
    finally:
        conn.close()

    report = parsing.validate_rows(rows)
    generated_at = ids.now_kst().isoformat()
    atomic_write_text(
        project_root / "output" / "logs" / "parse_report.md",
        parsing.report_to_markdown(report, generated_at),
    )

    print(
        f"PARSE VALIDATION: {'PASS' if report.ok else 'FAIL'} "
        f"total={report.total_items} checksum={report.checksum}"
    )
    if not report.ok:
        for violation in report.schema_violations[:20]:
            print(f"  VIOLATION: {violation}")
        for duplicate_id in report.duplicate_ids[:20]:
            print(f"  DUPLICATE: {duplicate_id}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
