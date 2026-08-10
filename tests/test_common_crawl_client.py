import gzip

import pytest
import requests

from saas_words_two import common_crawl_client as ccc


def no_sleep(_seconds):
    return None


class FakeJsonResponse:
    def __init__(self, json_data, status_ok: bool = True):
        self._json_data = json_data
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError("bad status")

    def json(self):
        return self._json_data


class FakeTextResponse:
    def __init__(self, text: str, status_ok: bool = True):
        self.text = text
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError("bad status")


class FakeBinaryResponse:
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

    def get(self, url, timeout, headers=None):
        self.calls.append(url)
        for prefix, entry in self.routes.items():
            if url.startswith(prefix):
                if isinstance(entry, list):
                    entry = entry.pop(0)
                if isinstance(entry, Exception):
                    raise entry
                return entry
        raise AssertionError(f"unrecognized url: {url}")


SAMPLE_CAPTURE = {
    "status": "200",
    "mime": "text/html",
    "offset": "100",
    "length": "50",
    "filename": "crawl-data/CC-MAIN-2026-30/segments/x/warc/sample.warc.gz",
}


def _build_warc_record(html: str) -> bytes:
    raw = (
        b"WARC/1.0\r\n"
        b"WARC-Type: response\r\n"
        b"\r\n"
        b"HTTP/1.1 200 OK\r\n"
        b"content-type: text/html\r\n"
        b"\r\n" + html.encode("utf-8")
    )
    return gzip.compress(raw)


def test_fetch_latest_index_returns_first_id():
    session = FakeSession(
        {ccc.CDX_BASE: FakeJsonResponse([{"id": "CC-MAIN-2026-30"}, {"id": "CC-MAIN-2026-25"}])}
    )
    result = ccc.fetch_latest_index(session, sleep_fn=no_sleep)
    assert result.ok
    assert result.data == "CC-MAIN-2026-30"


def test_fetch_latest_index_fails_on_empty_list():
    session = FakeSession({ccc.CDX_BASE: FakeJsonResponse([])})
    result = ccc.fetch_latest_index(session, sleep_fn=no_sleep)
    assert not result.ok


def test_lookup_captures_filters_to_200_html_only():
    ndjson = (
        '{"status": "200", "mime": "text/html", "offset": "1", "length": "2", "filename": "a"}\n'
        '{"status": "301", "mime": "text/html", "offset": "3", "length": "4", "filename": "b"}\n'
        '{"status": "200", "mime": "application/pdf", "offset": "5", "length": "6", "filename": "c"}\n'
    )
    session = FakeSession({ccc.CDX_BASE: FakeTextResponse(ndjson)})
    result = ccc.lookup_captures(session, "example.com", "CC-MAIN-2026-30", sleep_fn=no_sleep)
    assert result.ok
    assert len(result.data) == 1
    assert result.data[0]["filename"] == "a"


def test_extract_html_body_parses_warc_record():
    warc_bytes = _build_warc_record("<html><body>manual process takes hours</body></html>")
    html = ccc.extract_html_body(warc_bytes)
    assert html is not None
    assert "manual process takes hours" in html


def test_extract_html_body_returns_none_on_bad_gzip():
    assert ccc.extract_html_body(b"not gzip data") is None


def test_fetch_capture_excerpt_strips_html_and_truncates():
    warc_bytes = _build_warc_record("<p>" + "x" * 5000 + "</p>")
    session = FakeSession({ccc.DATA_BASE: FakeBinaryResponse(warc_bytes)})
    result = ccc.fetch_capture_excerpt(session, SAMPLE_CAPTURE, sleep_fn=no_sleep)
    assert result.ok
    assert len(result.data) == ccc.EXCERPT_MAX_CHARS
    assert "Range: bytes=100-149" not in session.calls[0]  # header, not in URL
    assert session.calls[0].startswith(ccc.DATA_BASE)


def test_fetch_domain_excerpt_fails_gracefully_when_no_captures():
    session = FakeSession({ccc.CDX_BASE: FakeTextResponse("")})
    result = ccc.fetch_domain_excerpt(session, "nosuchdomain.example", "CC-MAIN-2026-30", sleep_fn=no_sleep)
    assert not result.ok
    assert "no captures" in result.error


def test_access_test_pass():
    warc_bytes = _build_warc_record("<html>pricing signup demo</html>")
    ndjson = '{"status": "200", "mime": "text/html", "offset": "1", "length": "2", "filename": "a"}\n'
    session = FakeSession(
        {
            ccc.CDX_BASE: [FakeJsonResponse([{"id": "CC-MAIN-2026-30"}]), FakeTextResponse(ndjson)],
            ccc.DATA_BASE: FakeBinaryResponse(warc_bytes),
        }
    )
    result = ccc.access_test(session, sleep_fn=no_sleep)
    assert result.ok
    assert result.data["index_id"] == "CC-MAIN-2026-30"


def test_access_test_fails_when_index_lookup_fails():
    session = FakeSession({ccc.CDX_BASE: FakeJsonResponse({}, status_ok=False)})
    result = ccc.access_test(session, sleep_fn=no_sleep)
    assert not result.ok
