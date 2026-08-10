from saas_words_two import collection, db, hn_client


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


def build_routes():
    return {
        "newstories.json": [1, 10],
        "askstories.json": [1],
        "showstories.json": [10],
        "item/1.json": {"id": 1, "type": "story", "title": "Ask HN: tool for X", "kids": [2, 3]},
        "item/2.json": {"id": 2, "type": "comment", "text": "still use spreadsheets", "parent": 1},
        "item/3.json": {"id": 3, "type": "comment", "text": "manual process takes hours", "parent": 1},
        "item/10.json": {"id": 10, "type": "story", "title": "Show HN: my tool", "kids": []},
    }


SOURCES_CONFIG = {
    "sources": {
        "hacker_news": {"enabled": True, "required": True, "incremental_cursor": "data/cache/hacker_news_last_id.txt"},
        "stack_exchange_dump": {"enabled": False, "required": False},
    }
}
HN_SETTINGS = {"stories_per_list": 500, "comments_per_story": 20, "max_items_per_run": 800}


def test_run_access_test_pass_writes_report(tmp_path):
    session = FakeSession(
        {"maxitem.json": 100, "item/100.json": {"id": 100, "type": "story"}, "search": {"hits": []}}
    )
    report = collection.run_access_test(tmp_path, SOURCES_CONFIG, session, generated_at="2026-08-10T19:00:00+09:00")
    assert report.results["hacker_news"]["status"] == "PASS"
    assert report.results["stack_exchange_dump"]["status"] == "DISABLED"
    report_path = tmp_path / "output" / "logs" / "access_test_report.md"
    assert report_path.exists()
    assert "hacker_news" in report_path.read_text(encoding="utf-8")


def test_run_access_test_fail_when_maxitem_not_int(tmp_path):
    session = FakeSession({"maxitem.json": "oops"})
    report = collection.run_access_test(tmp_path, SOURCES_CONFIG, session, generated_at="t0")
    assert report.results["hacker_news"]["status"] == "FAIL"


def test_incremental_collection_first_run_inserts_stories_and_comments(tmp_path):
    conn = db.connect(tmp_path)
    summary = collection.run_incremental_collection(
        tmp_path, conn, SOURCES_CONFIG, HN_SETTINGS, FakeSession(build_routes()), fetched_at="2026-08-10T19:00:00+09:00"
    )
    assert summary.fetched_stories == 2
    assert summary.fetched_comments == 2
    assert summary.cursor_before == 0
    assert summary.cursor_after == 10
    rows = conn.execute("SELECT id FROM hn_items ORDER BY id").fetchall()
    assert [row[0] for row in rows] == [1, 2, 3, 10]
    cursor_file = tmp_path / "data" / "cache" / "hacker_news_last_id.txt"
    assert cursor_file.read_text(encoding="utf-8").strip() == "10"
    conn.close()


def test_incremental_collection_second_run_dedupes_and_skips_network(tmp_path):
    conn = db.connect(tmp_path)
    collection.run_incremental_collection(
        tmp_path, conn, SOURCES_CONFIG, HN_SETTINGS, FakeSession(build_routes()), fetched_at="t0"
    )
    second_session = FakeSession(build_routes())
    summary2 = collection.run_incremental_collection(
        tmp_path, conn, SOURCES_CONFIG, HN_SETTINGS, second_session, fetched_at="t1"
    )
    assert summary2.fetched_stories == 0
    assert summary2.fetched_comments == 0
    assert summary2.skipped_existing == 2
    # only the three story-list endpoints should be hit; no item fetches on a fully-deduped run
    assert all("item/" not in call for call in second_session.calls)
    conn.close()


def test_incremental_collection_respects_max_items_budget(tmp_path):
    conn = db.connect(tmp_path)
    limited_settings = {**HN_SETTINGS, "max_items_per_run": 1}
    summary = collection.run_incremental_collection(
        tmp_path, conn, SOURCES_CONFIG, limited_settings, FakeSession(build_routes()), fetched_at="t0"
    )
    assert summary.fetched_stories + summary.fetched_comments == 1
    conn.close()


def test_keyword_search_collection_inserts_story_and_comment_hits(tmp_path):
    conn = db.connect(tmp_path)
    routes = {
        "search": {
            "hits": [
                {
                    "objectID": "1",
                    "_tags": ["story"],
                    "author": "a",
                    "created_at_i": 10,
                    "title": "Ask HN: manual process pain",
                },
                {
                    "objectID": "2",
                    "_tags": ["comment"],
                    "author": "b",
                    "created_at_i": 11,
                    "comment_text": "still use spreadsheets here",
                    "parent_id": 1,
                },
            ]
        }
    }
    session = FakeSession(routes)
    summary = collection.run_keyword_search_collection(
        conn,
        ["manual process"],
        session,
        hits_per_pattern=40,
        budget=100,
        created_after_epoch=0,
        fetched_at="2026-08-10T20:00:00+09:00",
    )
    assert summary.fetched_stories == 1
    assert summary.fetched_comments == 1
    rows = conn.execute("SELECT id FROM hn_items ORDER BY id").fetchall()
    assert [row[0] for row in rows] == [1, 2]
    conn.close()


def test_keyword_search_collection_dedupes_across_patterns_and_existing_rows(tmp_path):
    conn = db.connect(tmp_path)
    hit = {"objectID": "1", "_tags": ["story"], "author": "a", "created_at_i": 10, "title": "x"}
    routes = {"search": {"hits": [hit]}}
    session = FakeSession(routes)
    summary = collection.run_keyword_search_collection(
        conn, ["manual process", "takes hours"], session,
        hits_per_pattern=10, budget=100, created_after_epoch=0, fetched_at="t0",
    )
    assert summary.fetched_stories == 1
    assert summary.skipped_existing == 1
    conn.close()


def test_keyword_search_collection_respects_budget(tmp_path):
    conn = db.connect(tmp_path)
    routes = {
        "search": {
            "hits": [
                {"objectID": "1", "_tags": ["story"], "author": "a", "created_at_i": 10, "title": "x"},
                {"objectID": "2", "_tags": ["story"], "author": "b", "created_at_i": 11, "title": "y"},
            ]
        }
    }
    summary = collection.run_keyword_search_collection(
        conn, ["manual process"], FakeSession(routes),
        hits_per_pattern=10, budget=1, created_after_epoch=0, fetched_at="t0",
    )
    assert summary.fetched_stories == 1
    conn.close()


def test_no_duplicate_ids_after_collection(tmp_path):
    conn = db.connect(tmp_path)
    collection.run_incremental_collection(
        tmp_path, conn, SOURCES_CONFIG, HN_SETTINGS, FakeSession(build_routes()), fetched_at="t0"
    )
    rows = conn.execute("SELECT id, COUNT(*) c FROM hn_items GROUP BY id HAVING c > 1").fetchall()
    assert rows == []
    conn.close()
