import pytest
import requests

from saas_words_two import npm_client


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
        for path, entry in self._responses.items():
            if url.startswith(f"{npm_client.BASE_URL}/{path}"):
                if isinstance(entry, list):
                    entry = entry.pop(0)
                if isinstance(entry, Exception):
                    raise entry
                return entry
        raise AssertionError(f"unrecognized url: {url}")


def no_sleep(_seconds):
    return None


SAMPLE_HIT = {
    "package": {
        "name": "vendor-guard",
        "description": "track vendor insurance",
        "links": {"npm": "https://www.npmjs.com/package/vendor-guard", "homepage": "https://vendorguard.dev"},
    }
}


def test_search_packages_builds_query_and_parses_response():
    session = FakeSession({"-/v1/search": FakeResponse({"objects": [SAMPLE_HIT], "total": 1})})
    result = npm_client.search_packages(session, "vendor insurance", size=5, sleep_fn=no_sleep)
    assert result.ok
    assert result.data["total"] == 1
    assert "text=vendor" in session.calls[0]
    assert "size=5" in session.calls[0]


def test_search_packages_retries_then_succeeds():
    session = FakeSession(
        {"-/v1/search": [requests.ConnectionError("boom"), FakeResponse({"objects": [], "total": 0})]}
    )
    result = npm_client.search_packages(session, "x", sleep_fn=no_sleep)
    assert result.ok
    assert result.attempts == 2


def test_normalize_hit_maps_fields():
    normalized = npm_client.normalize_hit(SAMPLE_HIT)
    assert normalized["name"] == "vendor-guard"
    assert normalized["url"] == "https://www.npmjs.com/package/vendor-guard"
    assert normalized["homepage"] == "https://vendorguard.dev"


def test_normalize_hit_returns_none_without_name():
    assert npm_client.normalize_hit({"package": {}}) is None


def test_normalize_hit_falls_back_to_generated_url_when_no_npm_link():
    hit = {"package": {"name": "some-pkg", "links": {}}}
    normalized = npm_client.normalize_hit(hit)
    assert normalized["url"] == "https://www.npmjs.com/package/some-pkg"


def test_access_test_pass():
    session = FakeSession({"-/v1/search": FakeResponse({"objects": [SAMPLE_HIT], "total": 42})})
    result = npm_client.access_test(session, sleep_fn=no_sleep)
    assert result.ok
    assert result.data["total"] == 42
    assert result.data["sample_name"] == "vendor-guard"


def test_access_test_fails_when_objects_missing():
    session = FakeSession({"-/v1/search": FakeResponse({"total": 0})})
    result = npm_client.access_test(session, sleep_fn=no_sleep)
    assert not result.ok


def test_access_test_fails_when_zero_results():
    session = FakeSession({"-/v1/search": FakeResponse({"objects": [], "total": 0})})
    result = npm_client.access_test(session, sleep_fn=no_sleep)
    assert not result.ok


def test_access_test_fails_on_http_error():
    session = FakeSession({"-/v1/search": FakeResponse({}, status_ok=False)})
    result = npm_client.access_test(session, sleep_fn=no_sleep)
    assert not result.ok
