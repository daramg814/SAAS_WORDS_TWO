"""수요를 통과한 문제만 대상으로 Show HN 제품·댓글 언급 공급 후보를 수집한다."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import requests

from saas_words_two import config, db, hn_client, ids, supply

_DOMAIN_RE = re.compile(r"https?://(?:www\.)?([^/]+)")


def extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    match = _DOMAIN_RE.match(url)
    return match.group(1) if match else None


def build_query(problem_row) -> str:
    parts = [problem_row["task"], problem_row["target_user"]]
    return " ".join(part for part in parts if part).strip()


def collect_for_problem(conn, problem_row, session, *, hits_per_problem: int) -> int:
    query = build_query(problem_row)
    if not query:
        return 0

    inserted = 0
    for tags, source in (("show_hn", "hn_show"), ("(story,comment)", "hn_mention")):
        result = hn_client.search_items(session, query, tags=tags, hits_per_page=hits_per_problem)
        if not result.ok or not isinstance(result.data, dict):
            continue
        for hit in result.data.get("hits", []):
            title = hit.get("title") or hit.get("comment_text") or ""
            if not title:
                continue
            name = supply.normalize_product_name(title)
            if not name:
                continue
            domain = extract_domain(hit.get("url"))
            key = supply.dedupe_key(name, domain)
            existing = conn.execute(
                "SELECT 1 FROM supply_candidates WHERE problem_id = ? AND dedupe_key = ?",
                (problem_row["problem_id"], key),
            ).fetchone()
            if existing:
                continue
            product_id = ids.next_product_id(conn)
            conn.execute(
                "INSERT INTO supply_candidates "
                "(product_id, problem_id, name, domain, dedupe_key, source, evidence_url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (product_id, problem_row["problem_id"], name, domain, key, source, hit.get("url")),
            )
            inserted += 1
    return inserted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    project_root = args.project_root
    project_config = config.load_project_config(project_root)
    hits_per_problem = project_config["collection"]["hacker_news"].get("supply_hits_per_problem", 20)

    conn = db.connect(project_root)
    try:
        problems = conn.execute("SELECT * FROM problems WHERE status = 'DEMAND_PASSED'").fetchall()
        session = requests.Session()
        total_inserted = 0
        for problem_row in problems:
            total_inserted += collect_for_problem(
                conn, problem_row, session, hits_per_problem=hits_per_problem
            )
        conn.commit()
    finally:
        conn.close()

    print(f"SUPPLY CANDIDATES: problems={len(problems)} candidates_inserted={total_inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
