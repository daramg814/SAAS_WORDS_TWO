"""데이터원 접근성 검사 결과에 따라 증분 수집한다."""

from __future__ import annotations

import argparse
from pathlib import Path

import requests

from saas_words_two import collection, config, db, ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    project_root = args.project_root
    sources_config = config.load_sources_config(project_root)
    project_config = config.load_project_config(project_root)
    now = ids.now_kst()

    session = requests.Session()
    access_report = collection.run_access_test(
        project_root, sources_config, session, generated_at=now.isoformat()
    )
    if access_report.results.get("hacker_news", {}).get("status") != "PASS":
        print("SOURCE ACCESS: FAIL - hacker_news is required and did not pass")
        for name, info in access_report.results.items():
            print(f"  {name}: {info['status']} ({info['detail']})")
        return 2

    conn = db.connect(project_root)
    try:
        hn_settings = project_config["collection"]["hacker_news"]
        summary = collection.run_incremental_collection(
            project_root, conn, sources_config, hn_settings, session, fetched_at=now.isoformat()
        )
    finally:
        conn.close()

    print(
        f"COLLECTED stories={summary.fetched_stories} comments={summary.fetched_comments} "
        f"skipped_existing={summary.skipped_existing} "
        f"cursor={summary.cursor_before}->{summary.cursor_after}"
    )
    for error in summary.errors:
        print(f"  WARN: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
