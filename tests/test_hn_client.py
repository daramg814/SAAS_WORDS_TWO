import pytest
import requests

from saas_words_two import hn_client


class FakeResponse:
    def __init__(self, json_data, status_ok=True):
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
        path = url.split("/v0/", 1)[1]
        entry = self._responses[path]
        if isinstance(entry, list):
            entry = entry.pop(0)
        if isinstance(entry, Exception):
            raise entry
        return entry


def no_sleep(_seconds):
    return None


def test_get_json_success():
    session = FakeSession({"maxitem.json": FakeResponse(42)})
    result = hn_client._get_json(session, "maxitem.json", retry_attempts=3, sleep_fn=no_sleep)
    assert result.ok
    assert result.data == 42
    assert result.attempts == 1


def test_get_json_retries_then_succeeds():
    session = FakeSession(
        {"maxitem.json": [requests.ConnectionError("boom"), FakeResponse(42)]}
    )
    result = hn_client._get_json(session, "maxitem.json", retry_attempts=3, sleep_fn=no_sleep)
    assert result.ok
    assert result.data == 42
    assert result.attempts == 2


def test_get_json_fails_after_all_retries():
    session = FakeSession(
        {
            "maxitem.json": [
                requests.ConnectionError("boom1"),
                requests.ConnectionError("boom2"),
                requests.ConnectionError("boom3"),
            ]
        }
    )
    result = hn_client._get_json(session, "maxitem.json", retry_attempts=3, sleep_fn=no_sleep)
    assert not result.ok
    assert result.attempts == 3
    assert "boom3" in result.error


def test_access_test_pass():
    session = FakeSession(
        {
            "maxitem.json": FakeResponse(100),
            "item/100.json": FakeResponse({"id": 100, "type": "story", "title": "hi"}),
        }
    )
    result = hn_client.access_test(session, sleep_fn=no_sleep)
    assert result.ok
    assert result.data["max_item"] == 100
    assert result.data["sample_item"]["id"] == 100


def test_access_test_fails_when_maxitem_not_int():
    session = FakeSession({"maxitem.json": FakeResponse("not-a-number")})
    result = hn_client.access_test(session, sleep_fn=no_sleep)
    assert not result.ok


def test_access_test_fails_when_sample_item_is_null():
    session = FakeSession({"maxitem.json": FakeResponse(100), "item/100.json": FakeResponse(None)})
    result = hn_client.access_test(session, sleep_fn=no_sleep)
    assert not result.ok


def test_fetch_story_list_rejects_unknown_list():
    session = FakeSession({})
    with pytest.raises(ValueError):
        hn_client.fetch_story_list(session, "bogusstories")


def test_normalize_item_maps_fields_and_coerces_booleans():
    raw = {
        "id": 5,
        "type": "comment",
        "by": "alice",
        "time": 123,
        "text": "manual process takes hours",
        "parent": 4,
        "dead": True,
        "deleted": False,
    }
    normalized = hn_client.normalize_item(raw)
    assert normalized["id"] == 5
    assert normalized["by"] == "alice"
    assert normalized["dead"] == 1
    assert normalized["deleted"] == 0
    assert normalized["title"] is None
