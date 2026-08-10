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
