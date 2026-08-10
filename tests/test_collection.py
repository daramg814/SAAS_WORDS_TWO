import gzip
import json
from datetime import datetime, timedelta, timezone

import requests

from saas_words_two import collection, db, gh_archive_client, hn_client


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


def test_check_disk_usage_reports_free_space_and_db_size(tmp_path):
    usage = collection.check_disk_usage(tmp_path)
    assert usage["free_bytes"] > 0
    assert usage["total_bytes"] >= usage["free_bytes"]
    assert usage["local_db_bytes"] == 0  # no data/local.db in a fresh tmp_path
    assert usage["ok"] is True


def test_check_disk_usage_sums_cache_dir_and_reports_db_size(tmp_path):
    cache_dir = tmp_path / "data" / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "hacker_news_last_id.txt").write_text("123", encoding="utf-8")
    db_dir = tmp_path / "data"
    (db_dir / "local.db").write_bytes(b"x" * 50)
    usage = collection.check_disk_usage(tmp_path)
    assert usage["cache_bytes"] == 3
    assert usage["local_db_bytes"] == 50


def test_run_access_test_pass_writes_report(tmp_path):
    session = FakeSession(
        {"maxitem.json": 100, "item/100.json": {"id": 100, "type": "story"}, "search": {"hits": []}}
    )
    report = collection.run_access_test(tmp_path, SOURCES_CONFIG, session, generated_at="2026-08-10T19:00:00+09:00")
    assert report.results["hacker_news"]["status"] == "PASS"
    assert report.results["stack_exchange_dump"]["status"] == "DISABLED"
    assert report.disk_usage["ok"] is True
    report_path = tmp_path / "output" / "logs" / "access_test_report.md"
    assert report_path.exists()
    assert "hacker_news" in report_path.read_text(encoding="utf-8")
    assert "disk_usage" in report_path.read_text(encoding="utf-8")


class CombinedFakeSession:
    """Dispatches to the HN or gh_archive fake by URL prefix, mirroring how a
    single real requests.Session serves run_access_test's calls to both
    hn_client.access_test and gh_archive_client.access_test."""

    def __init__(self, hn_session: FakeSession, gh_events_by_hour: dict):
        self.hn_session = hn_session
        self.gh_session = FakeGhSession(gh_events_by_hour)

    def get(self, url, timeout):
        if url.startswith(gh_archive_client.BASE_URL + "/"):
            return self.gh_session.get(url, timeout)
        return self.hn_session.get(url, timeout)


def test_run_access_test_exercises_gh_archive_and_reports_pass(tmp_path):
    sources_config = {**SOURCES_CONFIG, "sources": {**SOURCES_CONFIG["sources"], **GH_SOURCES_CONFIG["sources"]}}
    hn_session = FakeSession(
        {"maxitem.json": 100, "item/100.json": {"id": 100, "type": "story"}, "search": {"hits": []}}
    )
    session = CombinedFakeSession(hn_session, {"2026-08-10-7": [_issue_event(1, 9001)]})
    report = collection.run_access_test(
        tmp_path, sources_config, session, generated_at="t0", gh_archive_hour="2026-08-10-7"
    )
    assert report.results["gh_archive"]["status"] == "PASS"


def test_run_access_test_reports_gh_archive_fail_while_hacker_news_still_passes(tmp_path):
    """Regression: DEMAND-001's A안 adds gh_archive as a second, non-required
    source. Rule 4 (CLAUDE.md) requires that a failing optional source is
    marked DISABLED/FAIL and the pipeline continues on the sources that do
    pass - it must not fail the whole access test."""
    sources_config = {**SOURCES_CONFIG, "sources": {**SOURCES_CONFIG["sources"], **GH_SOURCES_CONFIG["sources"]}}
    hn_session = FakeSession(
        {"maxitem.json": 100, "item/100.json": {"id": 100, "type": "story"}, "search": {"hits": []}}
    )
    session = CombinedFakeSession(hn_session, {})  # no gh_archive fixture registered -> ConnectionError -> FAIL
    report = collection.run_access_test(
        tmp_path, sources_config, session, generated_at="t0", gh_archive_hour="2026-08-10-7"
    )
    assert report.results["hacker_news"]["status"] == "PASS"
    assert report.results["gh_archive"]["status"] == "FAIL"


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


# ---------------------------------------------------------------------------
# gh_archive collection
# ---------------------------------------------------------------------------

GH_SOURCES_CONFIG = {
    "sources": {
        "gh_archive": {
            "enabled": True,
            "required": False,
            "recent_days_min": 30,
            "recent_days_max": 90,
            "incremental_cursor": "data/cache/gh_archive_last_hour.txt",
        }
    }
}
GH_SETTINGS = {"max_hours_per_run": 10}


def _issue_event(event_id: int, issue_id: int) -> dict:
    return {
        "id": str(event_id),
        "type": "IssuesEvent",
        "actor": {"login": f"user{event_id}"},
        "created_at": "2026-08-10T00:00:00Z",
        "payload": {
            "action": "opened",
            "issue": {"id": issue_id, "title": "t", "body": "manual process pain", "html_url": "https://x/issues/1"},
        },
    }


class FakeGhResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


class FakeGhSession:
    def __init__(self, events_by_hour: dict):
        self.events_by_hour = events_by_hour
        self.calls: list[str] = []

    def get(self, url, timeout):
        self.calls.append(url)
        assert url.startswith(gh_archive_client.BASE_URL + "/")
        hour = url[len(gh_archive_client.BASE_URL) + 1 : -len(".json.gz")]
        if hour not in self.events_by_hour:
            raise requests.ConnectionError(f"no fixture registered for hour {hour}")
        events = self.events_by_hour[hour]
        body = "\n".join(json.dumps(event) for event in events).encode("utf-8")
        return FakeGhResponse(gzip.compress(body))


def _preset_gh_cursor(tmp_path, value: str) -> None:
    cursor_file = tmp_path / "data" / "cache" / "gh_archive_last_hour.txt"
    cursor_file.parent.mkdir(parents=True, exist_ok=True)
    cursor_file.write_text(f"{value}\n", encoding="utf-8")


def test_run_gh_archive_collection_inserts_with_source_and_advances_cursor(tmp_path):
    conn = db.connect(tmp_path)
    _preset_gh_cursor(tmp_path, "2026-08-10-7")
    events_by_hour = {"2026-08-10-7": [_issue_event(1, 9001)], "2026-08-10-8": [_issue_event(2, 9002)]}
    session = FakeGhSession(events_by_hour)
    now = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)  # ceiling = now - 2h = ...-8
    summary = collection.run_gh_archive_collection(
        tmp_path, conn, GH_SOURCES_CONFIG, GH_SETTINGS, session, now=now, fetched_at="t0"
    )
    assert summary.fetched_stories == 2
    assert summary.hours_processed[-2:] == ["2026-08-10-7", "2026-08-10-8"]
    rows = conn.execute("SELECT id, source FROM hn_items WHERE source = 'gh_archive' ORDER BY id").fetchall()
    assert [(row["id"], row["source"]) for row in rows] == [(9001, "gh_archive"), (9002, "gh_archive")]
    cursor_file = tmp_path / "data" / "cache" / "gh_archive_last_hour.txt"
    assert cursor_file.read_text(encoding="utf-8").strip() == "2026-08-10-9"
    conn.close()


def test_run_gh_archive_collection_resumes_from_persisted_cursor(tmp_path):
    conn = db.connect(tmp_path)
    _preset_gh_cursor(tmp_path, "2026-08-10-7")
    events_by_hour = {"2026-08-10-7": [_issue_event(1, 9001)], "2026-08-10-8": [_issue_event(2, 9002)]}
    now = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
    collection.run_gh_archive_collection(
        tmp_path, conn, GH_SOURCES_CONFIG, GH_SETTINGS, FakeGhSession(events_by_hour), now=now, fetched_at="t0"
    )
    second_session = FakeGhSession(events_by_hour)
    second_now = datetime(2026, 8, 10, 11, 0, tzinfo=timezone.utc)  # ceiling now = ...-9
    events_by_hour["2026-08-10-9"] = [_issue_event(3, 9003)]
    summary2 = collection.run_gh_archive_collection(
        tmp_path, conn, GH_SOURCES_CONFIG, GH_SETTINGS, second_session, now=second_now, fetched_at="t1"
    )
    assert summary2.hours_processed == ["2026-08-10-9"]
    assert second_session.calls == [f"{gh_archive_client.BASE_URL}/2026-08-10-9.json.gz"]
    conn.close()


def test_run_gh_archive_collection_respects_max_hours_budget(tmp_path):
    conn = db.connect(tmp_path)
    _preset_gh_cursor(tmp_path, "2026-08-10-7")
    events_by_hour = {f"2026-08-10-{h}": [_issue_event(h, 9000 + h)] for h in range(7, 12)}
    now = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)  # ceiling ...-13, five hours available
    summary = collection.run_gh_archive_collection(
        tmp_path, conn, GH_SOURCES_CONFIG, {"max_hours_per_run": 2}, FakeGhSession(events_by_hour), now=now, fetched_at="t0"
    )
    assert len(summary.hours_processed) == 2
    conn.close()


def test_run_gh_archive_collection_crosses_single_to_double_digit_hour_boundary(tmp_path):
    """Regression test: hour keys have no leading zero, so lexicographic
    string comparison of e.g. '2026-08-10-9' vs '2026-08-10-10' is wrong
    (treats hour 9 as *after* hour 10). This asserts the loop correctly
    continues past the single-digit/double-digit boundary."""
    conn = db.connect(tmp_path)
    events_by_hour = {
        "2026-08-10-9": [_issue_event(9, 9009)],
        "2026-08-10-10": [_issue_event(10, 9010)],
        "2026-08-10-11": [_issue_event(11, 9011)],
    }
    now = datetime(2026, 8, 10, 13, 30, tzinfo=timezone.utc)  # ceiling = ...-11
    cursor_file = tmp_path / "data" / "cache" / "gh_archive_last_hour.txt"
    cursor_file.parent.mkdir(parents=True, exist_ok=True)
    cursor_file.write_text("2026-08-10-9\n", encoding="utf-8")
    summary = collection.run_gh_archive_collection(
        tmp_path, conn, GH_SOURCES_CONFIG, GH_SETTINGS, FakeGhSession(events_by_hour), now=now, fetched_at="t0"
    )
    assert summary.hours_processed == ["2026-08-10-9", "2026-08-10-10", "2026-08-10-11"]
    conn.close()


def test_run_gh_archive_collection_converts_kst_now_to_utc_before_selecting_hours(tmp_path):
    conn = db.connect(tmp_path)
    # 2026-08-10 02:00 KST (UTC+9) is 2026-08-09 17:00 UTC; ceiling = 17:00 - 2h = ...-15
    kst = timezone(timedelta(hours=9))
    now_kst = datetime(2026, 8, 10, 2, 0, tzinfo=kst)
    events_by_hour = {"2026-08-09-15": [_issue_event(15, 9015)]}
    cursor_file = tmp_path / "data" / "cache" / "gh_archive_last_hour.txt"
    cursor_file.parent.mkdir(parents=True, exist_ok=True)
    cursor_file.write_text("2026-08-09-15\n", encoding="utf-8")
    summary = collection.run_gh_archive_collection(
        tmp_path, conn, GH_SOURCES_CONFIG, GH_SETTINGS, FakeGhSession(events_by_hour), now=now_kst, fetched_at="t0"
    )
    assert summary.hours_processed == ["2026-08-09-15"]
    conn.close()
