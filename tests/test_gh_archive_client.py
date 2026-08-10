import gzip
import json

import requests

from saas_words_two import gh_archive_client


class FakeResponse:
    def __init__(self, content: bytes, status_ok: bool = True):
        self.content = content
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError("bad status")


class FakeSession:
    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url, timeout):
        self.calls.append(url)
        assert url.startswith(gh_archive_client.BASE_URL + "/")
        hour = url[len(gh_archive_client.BASE_URL) + 1 : -len(".json.gz")]
        entry = self.routes[hour]
        if isinstance(entry, list):
            entry = entry.pop(0)
        if isinstance(entry, Exception):
            raise entry
        return entry


def no_sleep(_seconds):
    return None


def gzip_events(events: list[dict]) -> bytes:
    body = "\n".join(json.dumps(event) for event in events).encode("utf-8")
    return gzip.compress(body)


ISSUE_OPENED = {
    "id": "1",
    "type": "IssuesEvent",
    "actor": {"login": "alice"},
    "created_at": "2026-08-10T07:07:52Z",
    "payload": {
        "action": "opened",
        "issue": {
            "id": 5000000001,
            "title": "Is there a tool for X",
            "body": "We still use spreadsheets for this, takes hours.",
            "html_url": "https://github.com/alice/repo/issues/1",
        },
    },
}

ISSUE_COMMENT = {
    "id": "2",
    "type": "IssueCommentEvent",
    "actor": {"login": "bob"},
    "created_at": "2026-08-10T07:08:00Z",
    "payload": {
        "action": "created",
        "issue": {"id": 5000000001},
        "comment": {
            "id": 5000000002,
            "body": "manual process, built this internally as a workaround",
            "html_url": "https://github.com/alice/repo/issues/1#issuecomment-2",
        },
    },
}

BOT_ISSUE_COMMENT = {
    "id": "3",
    "type": "IssueCommentEvent",
    "actor": {"login": "dependabot[bot]"},
    "created_at": "2026-08-10T07:09:00Z",
    "payload": {
        "action": "created",
        "issue": {"id": 5000000001},
        "comment": {"id": 5000000003, "body": "bumps version", "html_url": "https://x/y"},
    },
}

PUSH_EVENT = {"id": "4", "type": "PushEvent", "actor": {"login": "carol"}, "payload": {}}


def test_hour_key_and_next_hour_key_roll_over_day_and_month():
    assert gh_archive_client.hour_key(gh_archive_client.hour_key_to_datetime("2026-08-10-23")) == "2026-08-10-23"
    assert gh_archive_client.next_hour_key("2026-08-10-23") == "2026-08-11-0"
    assert gh_archive_client.next_hour_key("2026-08-31-23") == "2026-09-01-0"


def test_normalize_event_maps_issue_opened_to_story():
    normalized = gh_archive_client.normalize_event(ISSUE_OPENED)
    assert normalized["id"] == 5000000001
    assert normalized["type"] == "story"
    assert normalized["by"] == "alice"
    assert normalized["title"] == "Is there a tool for X"
    assert normalized["parent"] is None
    assert normalized["time"] is not None


def test_normalize_event_maps_issue_comment_to_comment_with_parent():
    normalized = gh_archive_client.normalize_event(ISSUE_COMMENT)
    assert normalized["id"] == 5000000002
    assert normalized["type"] == "comment"
    assert normalized["parent"] == 5000000001
    assert normalized["by"] == "bob"


def test_normalize_event_excludes_bot_actors():
    assert gh_archive_client.normalize_event(BOT_ISSUE_COMMENT) is None


def test_normalize_event_excludes_unrelated_event_types():
    assert gh_archive_client.normalize_event(PUSH_EVENT) is None


def test_iter_hour_events_decompresses_and_parses_ndjson():
    compressed = gzip_events([ISSUE_OPENED, ISSUE_COMMENT])
    events = list(gh_archive_client.iter_hour_events(compressed))
    assert len(events) == 2
    assert events[0]["type"] == "IssuesEvent"


def test_iter_hour_events_skips_malformed_lines():
    body = gzip.compress(b'{"ok": true}\nnot json\n')
    events = list(gh_archive_client.iter_hour_events(body))
    assert events == [{"ok": True}]


def test_access_test_pass_reports_counts():
    compressed = gzip_events([ISSUE_OPENED, ISSUE_COMMENT, BOT_ISSUE_COMMENT, PUSH_EVENT])
    session = FakeSession({"2026-08-10-7": FakeResponse(compressed)})
    result = gh_archive_client.access_test(session, hour="2026-08-10-7", sleep_fn=no_sleep)
    assert result.ok
    assert result.data["hour"] == "2026-08-10-7"
    assert result.data["total_events"] == 4
    assert result.data["normalizable_events"] == 2


def test_access_test_fails_on_http_error():
    session = FakeSession({"2026-08-10-7": FakeResponse(b"", status_ok=False)})
    result = gh_archive_client.access_test(session, hour="2026-08-10-7", sleep_fn=no_sleep)
    assert not result.ok


def test_access_test_fails_on_empty_hour():
    compressed = gzip.compress(b"")
    session = FakeSession({"2026-08-10-7": FakeResponse(compressed)})
    result = gh_archive_client.access_test(session, hour="2026-08-10-7", sleep_fn=no_sleep)
    assert not result.ok
    assert "zero events" in result.error


def test_fetch_hour_retries_then_succeeds():
    compressed = gzip_events([ISSUE_OPENED])
    session = FakeSession({"2026-08-10-7": [requests.ConnectionError("boom"), FakeResponse(compressed)]})
    result = gh_archive_client.fetch_hour(session, "2026-08-10-7", retry_attempts=3, timeout=30.0, sleep_fn=no_sleep)
    assert result.ok
    assert result.attempts == 2
