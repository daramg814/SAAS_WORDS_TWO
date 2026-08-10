import pytest
import requests

from saas_words_two import app_store_client as asc


class FakeResponse:
    def __init__(self, json_data, status_ok: bool = True):
        self._json_data = json_data
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError("bad status")

    def json(self):
        return self._json_data


class FakeSession:
    def __init__(self, responses: dict):
        self._responses = responses
        self.calls: list[str] = []

    def get(self, url, timeout):
        self.calls.append(url)
        for prefix, entry in self._responses.items():
            if url.startswith(prefix):
                if isinstance(entry, list):
                    entry = entry.pop(0)
                if isinstance(entry, Exception):
                    raise entry
                return entry
        raise AssertionError(f"unrecognized url: {url}")


def no_sleep(_seconds):
    return None


SAMPLE_APP_HIT = {"trackId": 1104772757, "trackName": "HoneyBook - Small Business CRM", "genres": ["Business"]}

SAMPLE_REVIEW_ENTRY = {
    "author": {"name": {"label": "Anna moser photo"}},
    "updated": {"label": "2026-06-11T09:46:26-07:00"},
    "im:rating": {"label": "5"},
    "id": {"label": "14170584668"},
    "title": {"label": "Love this platform"},
    "content": {"label": "This had made my life so much easier running my business."},
}

FEED_METADATA_ENTRY = {
    "author": {"name": {"label": "HoneyBook - Small Business CRM"}},
    "id": {"label": "1104772757"},
    "title": {"label": "HoneyBook - Small Business CRM"},
}


def test_search_apps_builds_query_and_parses_response():
    session = FakeSession({asc.SEARCH_URL: FakeResponse({"results": [SAMPLE_APP_HIT], "resultCount": 1})})
    result = asc.search_apps(session, "invoicing small business", limit=5, sleep_fn=no_sleep)
    assert result.ok
    assert result.data["resultCount"] == 1
    assert "term=invoicing" in session.calls[0]
    assert "limit=5" in session.calls[0]


def test_search_apps_retries_then_succeeds():
    session = FakeSession(
        {asc.SEARCH_URL: [requests.ConnectionError("boom"), FakeResponse({"results": [], "resultCount": 0})]}
    )
    result = asc.search_apps(session, "x", sleep_fn=no_sleep)
    assert result.ok
    assert result.attempts == 2


def test_normalize_app_hit_maps_fields():
    normalized = asc.normalize_app_hit(SAMPLE_APP_HIT)
    assert normalized["app_id"] == 1104772757
    assert normalized["name"] == "HoneyBook - Small Business CRM"
    assert normalized["genres"] == ["Business"]


def test_normalize_app_hit_returns_none_without_track_id_or_name():
    assert asc.normalize_app_hit({"trackName": "x"}) is None
    assert asc.normalize_app_hit({"trackId": 1}) is None


def test_make_item_id_prefixes_and_pads():
    assert asc.make_item_id(14170584668) == 7014170584668
    assert asc.make_item_id(1) == 7000000000001


def test_normalize_review_maps_fields():
    normalized = asc.normalize_review(1104772757, SAMPLE_REVIEW_ENTRY)
    assert normalized["id"] == asc.make_item_id(14170584668)
    assert normalized["by"] == "Anna moser photo"
    assert normalized["title"] == "Love this platform"
    assert "easier running my business" in normalized["text"]
    assert normalized["type"] == "story"
    assert normalized["deleted"] == 0
    assert normalized["time"] is not None


def test_normalize_review_returns_none_for_feed_metadata_entry():
    assert asc.normalize_review(1104772757, FEED_METADATA_ENTRY) is None


def test_normalize_review_returns_none_without_author():
    entry = dict(SAMPLE_REVIEW_ENTRY)
    entry["author"] = {"name": {}}
    assert asc.normalize_review(1104772757, entry) is None


def test_fetch_reviews_builds_url_with_app_id():
    session = FakeSession({"https://itunes.apple.com/us/rss/customerreviews/id=1104772757": FakeResponse({"feed": {"entry": []}})})
    result = asc.fetch_reviews(session, 1104772757, sleep_fn=no_sleep)
    assert result.ok
    assert "id=1104772757" in session.calls[0]


def test_access_test_pass():
    session = FakeSession(
        {
            asc.SEARCH_URL: FakeResponse({"results": [SAMPLE_APP_HIT], "resultCount": 1}),
            "https://itunes.apple.com/us/rss/customerreviews/id=1104772757": FakeResponse(
                {"feed": {"entry": [SAMPLE_REVIEW_ENTRY, FEED_METADATA_ENTRY]}}
            ),
        }
    )
    result = asc.access_test(session, sleep_fn=no_sleep)
    assert result.ok
    assert result.data["app_id"] == 1104772757
    assert result.data["review_count"] == 1


def test_access_test_fails_when_search_returns_no_results():
    session = FakeSession({asc.SEARCH_URL: FakeResponse({"results": [], "resultCount": 0})})
    result = asc.access_test(session, sleep_fn=no_sleep)
    assert not result.ok


def test_access_test_fails_when_no_normalizable_reviews():
    session = FakeSession(
        {
            asc.SEARCH_URL: FakeResponse({"results": [SAMPLE_APP_HIT], "resultCount": 1}),
            "https://itunes.apple.com/us/rss/customerreviews/id=1104772757": FakeResponse(
                {"feed": {"entry": [FEED_METADATA_ENTRY]}}
            ),
        }
    )
    result = asc.access_test(session, sleep_fn=no_sleep)
    assert not result.ok


def test_access_test_fails_on_http_error():
    session = FakeSession({asc.SEARCH_URL: FakeResponse({}, status_ok=False)})
    result = asc.access_test(session, sleep_fn=no_sleep)
    assert not result.ok
