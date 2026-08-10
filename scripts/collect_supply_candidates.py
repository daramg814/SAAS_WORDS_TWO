"""수요를 통과한 문제만 대상으로 Show HN·GH Archive·npm 제품 언급 공급 후보를 수집한다."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import requests

from saas_words_two import common_crawl_client, config, db, hn_client, ids, npm_client, supply

_DOMAIN_RE = re.compile(r"https?://(?:www\.)?([^/]+)")
_GITHUB_REPO_RE = re.compile(r"github\.com/([^/]+)/([^/]+)")
_QUERY_TERM_RE = re.compile(r"[a-zA-Z]+")


def extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    match = _DOMAIN_RE.match(url)
    return match.group(1) if match else None


def extract_github_repo(url: str | None) -> tuple[str, str] | None:
    """Parses (owner, repo) out of a GH Archive issue/comment html_url, used
    as the product identity for design 7.1's "GH Archive·GitHub에서 확인된
    제품·오픈소스 도구" supply tier."""
    if not url:
        return None
    match = _GITHUB_REPO_RE.search(url)
    return (match.group(1), match.group(2)) if match else None


def build_query(problem_row) -> str:
    parts = [problem_row["task"], problem_row["target_user"]]
    return " ".join(part for part in parts if part).strip()


def _insert_candidate_if_new(conn, problem_id: str, name: str, domain: str | None, source: str, evidence_url) -> bool:
    key = supply.dedupe_key(name, domain)
    existing = conn.execute(
        "SELECT 1 FROM supply_candidates WHERE problem_id = ? AND dedupe_key = ?", (problem_id, key)
    ).fetchone()
    if existing:
        return False
    product_id = ids.next_product_id(conn)
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, domain, dedupe_key, source, evidence_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (product_id, problem_id, name, domain, key, source, evidence_url),
    )
    return True


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
            if _insert_candidate_if_new(
                conn, problem_row["problem_id"], name, extract_domain(hit.get("url")), source, hit.get("url")
            ):
                inserted += 1
    return inserted


def collect_gh_archive_mentions_for_problem(conn, problem_row, *, hits_per_problem: int) -> int:
    """design 7.1 supply-collection tier 3: 'GH Archive·GitHub에서 확인된
    제품·오픈소스 도구'. GH Archive issue/comment text is already collected
    locally as part of demand-side collection (source='gh_archive' in
    hn_items) - reusing it here needs no new network call, unlike the HN
    Algolia search above. A repo mentioned in an issue/comment whose text
    matches the problem's query terms is treated as a supply candidate, with
    the GitHub repo itself (owner/repo, parsed from the item's html_url) as
    the product identity."""
    query = build_query(problem_row)
    terms = [term for term in _QUERY_TERM_RE.findall(query) if len(term) > 2]
    if not terms:
        return 0

    like_clause = " OR ".join(["title LIKE ? OR text LIKE ?"] * len(terms))
    params: list[str] = []
    for term in terms:
        pattern = f"%{term}%"
        params.extend([pattern, pattern])
    rows = conn.execute(
        f"SELECT DISTINCT url FROM hn_items WHERE source = 'gh_archive' AND url IS NOT NULL AND ({like_clause}) "
        "LIMIT ?",
        (*params, hits_per_problem),
    ).fetchall()

    inserted = 0
    for row in rows:
        repo = extract_github_repo(row["url"])
        if repo is None:
            continue
        owner, repo_name = repo
        domain = f"github.com/{owner}/{repo_name}"
        if _insert_candidate_if_new(
            conn, problem_row["problem_id"], repo_name, domain, "gh_archive_mention", row["url"]
        ):
            inserted += 1
    return inserted


def collect_npm_mentions_for_problem(conn, problem_row, session, *, hits_per_problem: int) -> int:
    """design 3.2/7.1: npm Registry supports "개발자 도구·오픈소스 대체재 공급 보조".
    Searches the same query built for HN/GH Archive against npm's package
    search - like those, this casts a wide net at collection time and leaves
    relevance judgment (is this actually a competing product, or an
    unrelated dependency?) to the existing active-signal verification
    step, rather than trying to code-classify "is this a developer problem"
    up front."""
    query = build_query(problem_row)
    if not query:
        return 0

    result = npm_client.search_packages(session, query, size=hits_per_problem)
    if not result.ok or not isinstance(result.data, dict):
        return 0

    inserted = 0
    for hit in result.data.get("objects", []):
        normalized = npm_client.normalize_hit(hit)
        if normalized is None:
            continue
        domain = extract_domain(normalized["url"]) or f"npmjs.com/package/{normalized['name']}"
        if _insert_candidate_if_new(
            conn, problem_row["problem_id"], normalized["name"], domain, "npm_registry", normalized["url"]
        ):
            inserted += 1
    return inserted


def enrich_with_common_crawl(conn, session) -> int:
    """design 3.2/CLAUDE.md rule 4: Common Crawl only enriches domains this
    pipeline has *already* collected as supply candidates - never a broad
    product search. One index lookup is shared across all candidates in this
    run; each candidate with a domain and no excerpt yet gets a best-effort
    fetch. A missing capture or fetch failure is expected/common (not every
    domain is in Common Crawl) and is recorded as "" (attempted, nothing
    found) so it is not retried every run - only NULL means "not yet tried"."""
    index_result = common_crawl_client.fetch_latest_index(session)
    if not index_result.ok:
        return 0
    index_id = index_result.data

    rows = conn.execute(
        "SELECT product_id, domain FROM supply_candidates "
        "WHERE domain IS NOT NULL AND common_crawl_excerpt IS NULL AND merged_into_product_id IS NULL"
    ).fetchall()

    enriched = 0
    for row in rows:
        result = common_crawl_client.fetch_domain_excerpt(session, row["domain"], index_id)
        excerpt = result.data if result.ok else ""
        conn.execute(
            "UPDATE supply_candidates SET common_crawl_excerpt = ? WHERE product_id = ?",
            (excerpt, row["product_id"]),
        )
        if excerpt:
            enriched += 1
    return enriched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    project_root = args.project_root
    project_config = config.load_project_config(project_root)
    sources_config = config.load_sources_config(project_root)
    hits_per_problem = project_config["collection"]["hacker_news"].get("supply_hits_per_problem", 20)
    npm_enabled = sources_config["sources"].get("npm_registry", {}).get("enabled", False)
    common_crawl_enabled = sources_config["sources"].get("common_crawl", {}).get("enabled", False)

    conn = db.connect(project_root)
    try:
        problems = conn.execute("SELECT * FROM problems WHERE status = 'DEMAND_PASSED'").fetchall()
        session = requests.Session()
        total_inserted = 0
        for problem_row in problems:
            total_inserted += collect_for_problem(
                conn, problem_row, session, hits_per_problem=hits_per_problem
            )
            total_inserted += collect_gh_archive_mentions_for_problem(
                conn, problem_row, hits_per_problem=hits_per_problem
            )
            if npm_enabled:
                total_inserted += collect_npm_mentions_for_problem(
                    conn, problem_row, session, hits_per_problem=hits_per_problem
                )
        conn.commit()

        enriched = 0
        if common_crawl_enabled:
            enriched = enrich_with_common_crawl(conn, session)
            conn.commit()
    finally:
        conn.close()

    print(
        f"SUPPLY CANDIDATES: problems={len(problems)} candidates_inserted={total_inserted} "
        f"common_crawl_enriched={enriched}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
