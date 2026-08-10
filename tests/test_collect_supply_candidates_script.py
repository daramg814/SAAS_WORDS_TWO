import sys
from pathlib import Path

from saas_words_two import db, hn_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_supply_candidates


class FakeResponse:
    def __init__(self, json_data):
        self._json_data = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_data


class FakeSession:
    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url, timeout):
        self.calls.append(url)
        for base in (hn_client.BASE_URL, hn_client.SEARCH_BASE_URL):
            if url.startswith(base + "/"):
                path = url[len(base) + 1 :]
                break
        else:
            raise AssertionError(f"unrecognized base url: {url}")
        if path.startswith("search?") and path not in self.routes:
            path = "search"
        return FakeResponse(self.routes[path])


def seed_problem(conn):
    conn.execute(
        "INSERT INTO problems (problem_id, target_user, task, status) VALUES "
        "('P-0001', 'small construction firms', 'track contractor insurance', 'DEMAND_PASSED')"
    )
    conn.commit()


def test_extract_domain():
    assert collect_supply_candidates.extract_domain("https://www.vendorguard.com/pricing") == "vendorguard.com"
    assert collect_supply_candidates.extract_domain(None) is None


def test_collect_for_problem_inserts_deduped_candidates(tmp_path):
    conn = db.connect(tmp_path)
    seed_problem(conn)
    problem_row = conn.execute("SELECT * FROM problems WHERE problem_id = 'P-0001'").fetchone()

    routes = {
        "search": {
            "hits": [
                {"objectID": "1", "title": "Show HN: VendorGuard – insurance tracking", "url": "https://vendorguard.com"},
                {"objectID": "2", "title": "Show HN: VendorGuard – insurance tracking", "url": "https://vendorguard.com"},
            ]
        }
    }
    inserted = collect_supply_candidates.collect_for_problem(
        conn, problem_row, FakeSession(routes), hits_per_problem=10
    )
    conn.commit()
    assert inserted == 1  # second hit is an exact dedupe_key repeat within this pass
    rows = conn.execute("SELECT * FROM supply_candidates WHERE problem_id = 'P-0001'").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "VendorGuard"
    conn.close()


def test_collect_for_problem_skips_problems_without_task_or_user(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("INSERT INTO problems (problem_id, status) VALUES ('P-0002', 'DEMAND_PASSED')")
    conn.commit()
    problem_row = conn.execute("SELECT * FROM problems WHERE problem_id = 'P-0002'").fetchone()
    inserted = collect_supply_candidates.collect_for_problem(
        conn, problem_row, FakeSession({}), hits_per_problem=10
    )
    assert inserted == 0
    conn.close()


def test_extract_github_repo_parses_owner_and_repo():
    assert collect_supply_candidates.extract_github_repo(
        "https://github.com/acme/insurance-tracker/issues/42"
    ) == ("acme", "insurance-tracker")
    assert collect_supply_candidates.extract_github_repo(None) is None
    assert collect_supply_candidates.extract_github_repo("https://example.com/not-github") is None


def _seed_gh_archive_item(conn, item_id, *, title=None, text=None, url):
    conn.execute(
        "INSERT INTO hn_items (id, type, by, time, title, text, url, fetched_at, source) "
        "VALUES (?, 'story', 'alice', 100, ?, ?, ?, 't0', 'gh_archive')",
        (item_id, title, text, url),
    )


def test_collect_gh_archive_mentions_inserts_repo_matching_query_terms(tmp_path):
    conn = db.connect(tmp_path)
    seed_problem(conn)
    problem_row = conn.execute("SELECT * FROM problems WHERE problem_id = 'P-0001'").fetchone()

    _seed_gh_archive_item(
        conn, 5000000001,
        title="contractor insurance tracker",
        text="tracks expirations",
        url="https://github.com/acme/insurance-tracker/issues/1",
    )
    _seed_gh_archive_item(
        conn, 5000000002,
        title="unrelated repo",
        text="nothing to do with the query",
        url="https://github.com/other/unrelated/issues/2",
    )
    conn.commit()

    inserted = collect_supply_candidates.collect_gh_archive_mentions_for_problem(
        conn, problem_row, hits_per_problem=10
    )
    conn.commit()
    assert inserted == 1
    rows = conn.execute(
        "SELECT * FROM supply_candidates WHERE problem_id = 'P-0001' AND source = 'gh_archive_mention'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "insurance-tracker"
    assert rows[0]["domain"] == "github.com/acme/insurance-tracker"
    conn.close()


def test_collect_gh_archive_mentions_dedupes_same_repo_across_multiple_matching_items(tmp_path):
    conn = db.connect(tmp_path)
    seed_problem(conn)
    problem_row = conn.execute("SELECT * FROM problems WHERE problem_id = 'P-0001'").fetchone()

    _seed_gh_archive_item(
        conn, 5000000001, title="contractor insurance tool", text=None,
        url="https://github.com/acme/insurance-tracker/issues/1",
    )
    _seed_gh_archive_item(
        conn, 5000000002, title=None, text="another comment about contractor insurance",
        url="https://github.com/acme/insurance-tracker/issues/1#issuecomment-1",
    )
    conn.commit()

    inserted = collect_supply_candidates.collect_gh_archive_mentions_for_problem(
        conn, problem_row, hits_per_problem=10
    )
    assert inserted == 1  # same repo (owner/repo) - counts as one supply candidate
    conn.close()


def test_collect_gh_archive_mentions_skips_problems_without_task_or_user(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("INSERT INTO problems (problem_id, status) VALUES ('P-0002', 'DEMAND_PASSED')")
    conn.commit()
    problem_row = conn.execute("SELECT * FROM problems WHERE problem_id = 'P-0002'").fetchone()
    inserted = collect_supply_candidates.collect_gh_archive_mentions_for_problem(
        conn, problem_row, hits_per_problem=10
    )
    assert inserted == 0
    conn.close()


class FakeNpmResponse:
    def __init__(self, json_data):
        self._json_data = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_data


class FakeNpmSession:
    def __init__(self, objects):
        self.objects = objects
        self.calls: list[str] = []

    def get(self, url, timeout):
        self.calls.append(url)
        return FakeNpmResponse({"objects": self.objects, "total": len(self.objects)})


def test_collect_npm_mentions_inserts_normalized_packages(tmp_path):
    conn = db.connect(tmp_path)
    seed_problem(conn)
    problem_row = conn.execute("SELECT * FROM problems WHERE problem_id = 'P-0001'").fetchone()

    session = FakeNpmSession(
        [{"package": {"name": "vendor-guard", "links": {"npm": "https://www.npmjs.com/package/vendor-guard"}}}]
    )
    inserted = collect_supply_candidates.collect_npm_mentions_for_problem(
        conn, problem_row, session, hits_per_problem=10
    )
    conn.commit()
    assert inserted == 1
    rows = conn.execute(
        "SELECT * FROM supply_candidates WHERE problem_id = 'P-0001' AND source = 'npm_registry'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "vendor-guard"
    conn.close()


def test_collect_npm_mentions_skips_problems_without_task_or_user(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("INSERT INTO problems (problem_id, status) VALUES ('P-0002', 'DEMAND_PASSED')")
    conn.commit()
    problem_row = conn.execute("SELECT * FROM problems WHERE problem_id = 'P-0002'").fetchone()
    inserted = collect_supply_candidates.collect_npm_mentions_for_problem(
        conn, problem_row, FakeNpmSession([]), hits_per_problem=10
    )
    assert inserted == 0
    conn.close()


def test_collect_npm_mentions_deduped_against_existing_candidate(tmp_path):
    conn = db.connect(tmp_path)
    seed_problem(conn)
    problem_row = conn.execute("SELECT * FROM problems WHERE problem_id = 'P-0001'").fetchone()
    hit = {"package": {"name": "vendor-guard", "links": {"npm": "https://www.npmjs.com/package/vendor-guard"}}}

    session = FakeNpmSession([hit, hit])  # same package returned twice in one search
    inserted = collect_supply_candidates.collect_npm_mentions_for_problem(
        conn, problem_row, session, hits_per_problem=10
    )
    assert inserted == 1
    conn.close()


import gzip


class FakeCcJsonResponse:
    def __init__(self, json_data):
        self._json_data = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_data


class FakeCcTextResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeCcBinaryResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


def _build_cc_warc_record(html: str) -> bytes:
    raw = (
        b"WARC/1.0\r\n\r\n"
        b"HTTP/1.1 200 OK\r\n\r\n" + html.encode("utf-8")
    )
    return gzip.compress(raw)


class FakeCcSession:
    """Routes by URL prefix: common_crawl_client.CDX_BASE for index/CDX
    lookups, common_crawl_client.DATA_BASE for the WARC range fetch."""

    def __init__(self, *, index_id="CC-MAIN-2026-30", ndjson="", warc_bytes=b""):
        self.index_id = index_id
        self.ndjson = ndjson
        self.warc_bytes = warc_bytes
        self.calls: list[str] = []

    def get(self, url, timeout, headers=None):
        self.calls.append(url)
        from saas_words_two import common_crawl_client as ccc

        if url.startswith(ccc.CDX_BASE + "/collinfo.json"):
            return FakeCcJsonResponse([{"id": self.index_id}])
        if url.startswith(ccc.CDX_BASE):
            return FakeCcTextResponse(self.ndjson)
        if url.startswith(ccc.DATA_BASE):
            return FakeCcBinaryResponse(self.warc_bytes)
        raise AssertionError(f"unrecognized url: {url}")


def test_enrich_with_common_crawl_stores_excerpt_for_candidate_with_capture(tmp_path):
    conn = db.connect(tmp_path)
    seed_problem(conn)
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, domain, dedupe_key, source) "
        "VALUES ('S-0001', 'P-0001', 'VendorGuard', 'vendorguard.com', 'vendorguardcom', 'hn_show')"
    )
    conn.commit()

    ndjson = '{"status": "200", "mime": "text/html", "offset": "0", "length": "10", "filename": "a"}\n'
    session = FakeCcSession(ndjson=ndjson, warc_bytes=_build_cc_warc_record("<p>pricing signup demo</p>"))
    enriched = collect_supply_candidates.enrich_with_common_crawl(conn, session)
    conn.commit()
    assert enriched == 1
    row = conn.execute("SELECT common_crawl_excerpt FROM supply_candidates WHERE product_id = 'S-0001'").fetchone()
    assert "pricing signup demo" in row["common_crawl_excerpt"]
    conn.close()


def test_enrich_with_common_crawl_records_empty_string_when_no_capture_found(tmp_path):
    conn = db.connect(tmp_path)
    seed_problem(conn)
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, domain, dedupe_key, source) "
        "VALUES ('S-0001', 'P-0001', 'VendorGuard', 'vendorguard.com', 'vendorguardcom', 'hn_show')"
    )
    conn.commit()

    session = FakeCcSession(ndjson="")  # no captures
    enriched = collect_supply_candidates.enrich_with_common_crawl(conn, session)
    conn.commit()
    assert enriched == 0
    row = conn.execute("SELECT common_crawl_excerpt FROM supply_candidates WHERE product_id = 'S-0001'").fetchone()
    assert row["common_crawl_excerpt"] == ""  # attempted, not NULL - won't be retried
    conn.close()


def test_enrich_with_common_crawl_skips_candidates_without_domain(tmp_path):
    conn = db.connect(tmp_path)
    seed_problem(conn)
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, domain, dedupe_key, source) "
        "VALUES ('S-0001', 'P-0001', 'VendorGuard', NULL, 'vendorguard', 'hn_mention')"
    )
    conn.commit()

    session = FakeCcSession()
    enriched = collect_supply_candidates.enrich_with_common_crawl(conn, session)
    assert enriched == 0
    # only the shared index lookup happens (collinfo.json); no per-candidate
    # CDX lookup, since the one candidate has no domain to look up
    assert len(session.calls) == 1
    conn.close()


def test_enrich_with_common_crawl_skips_already_enriched_candidates(tmp_path):
    conn = db.connect(tmp_path)
    seed_problem(conn)
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, domain, dedupe_key, source, "
        "common_crawl_excerpt) VALUES "
        "('S-0001', 'P-0001', 'VendorGuard', 'vendorguard.com', 'vendorguardcom', 'hn_show', 'already done')"
    )
    conn.commit()

    session = FakeCcSession()
    enriched = collect_supply_candidates.enrich_with_common_crawl(conn, session)
    assert enriched == 0
    conn.close()
