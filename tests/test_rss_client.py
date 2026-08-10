import requests

from saas_words_two import rss_client

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Example Blog</title>
  <item>
    <title>Is there a tool for X</title>
    <link>https://example.com/posts/1</link>
    <dc:creator>Alice</dc:creator>
    <pubDate>Thu, 06 Aug 2026 19:49:34 +0000</pubDate>
    <guid isPermaLink="false">https://example.com/?p=1</guid>
    <description><![CDATA[<p>manual process takes hours</p>]]></description>
  </item>
  <item>
    <title>Second post</title>
    <link>https://example.com/posts/2</link>
    <guid>https://example.com/?p=2</guid>
    <description>no creator on this one</description>
  </item>
</channel>
</rss>
"""

ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom Feed</title>
  <entry>
    <title>Still use spreadsheets</title>
    <link rel="alternate" href="https://example.com/entries/1"/>
    <id>urn:uuid:entry-1</id>
    <updated>2026-08-06T19:49:34Z</updated>
    <summary>we still use spreadsheets for this</summary>
  </entry>
</feed>
"""


def no_sleep(_seconds):
    return None


class FakeResponse:
    def __init__(self, text: str, status_ok: bool = True):
        self.text = text
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
        if url not in self.routes:
            raise AssertionError(f"unrecognized url: {url}")
        entry = self.routes[url]
        if isinstance(entry, Exception):
            raise entry
        return entry


def test_parse_feed_rss_extracts_items():
    entries = rss_client.parse_feed("https://example.com/feed", RSS_XML)
    assert len(entries) == 2
    first = entries[0]
    assert first["type"] == "story"
    assert first["title"] == "Is there a tool for X"
    assert first["by"] == "Alice"
    assert first["url"] == "https://example.com/posts/1"
    assert "manual process takes hours" in first["text"]
    assert first["time"] is not None
    assert entries[1]["by"] is None  # no dc:creator on the second item


def test_parse_feed_atom_extracts_entries():
    entries = rss_client.parse_feed("https://example.com/atom", ATOM_XML)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["title"] == "Still use spreadsheets"
    assert entry["url"] == "https://example.com/entries/1"
    assert "still use spreadsheets" in entry["text"]
    assert entry["time"] is not None


def test_parse_feed_rejects_malformed_xml():
    import xml.etree.ElementTree as ET
    import pytest

    with pytest.raises(ET.ParseError):
        rss_client.parse_feed("https://example.com/feed", "<rss><channel><item>")


def test_make_item_id_is_deterministic_and_namespaced():
    id1 = rss_client.make_item_id("https://example.com/feed", "guid-1")
    id2 = rss_client.make_item_id("https://example.com/feed", "guid-1")
    id3 = rss_client.make_item_id("https://example.com/feed", "guid-2")
    assert id1 == id2
    assert id1 != id3
    assert str(id1).startswith("8")
    assert len(str(id1)) == 12


def test_make_item_id_differs_by_feed_url_for_same_guid():
    """Same guid string reused across two different feeds must not collide."""
    id_a = rss_client.make_item_id("https://a.example.com/feed", "same-guid")
    id_b = rss_client.make_item_id("https://b.example.com/feed", "same-guid")
    assert id_a != id_b


def test_fetch_feed_success():
    session = FakeSession({"https://example.com/feed": FakeResponse(RSS_XML)})
    result = rss_client.fetch_feed(session, "https://example.com/feed", sleep_fn=no_sleep)
    assert result.ok
    assert len(result.data) == 2


class RetryingFakeSession(FakeSession):
    def get(self, url, timeout):
        self.calls.append(url)
        entry = self.routes[url]
        if isinstance(entry, list):
            entry = entry.pop(0)
        if isinstance(entry, Exception):
            raise entry
        return entry


def test_fetch_feed_retries_then_succeeds():
    session = RetryingFakeSession(
        {"https://example.com/feed": [requests.ConnectionError("boom"), FakeResponse(RSS_XML)]}
    )
    result = rss_client.fetch_feed(session, "https://example.com/feed", sleep_fn=no_sleep)
    assert result.ok
    assert result.attempts == 2


def test_fetch_feed_fails_on_bad_xml():
    session = FakeSession({"https://example.com/feed": FakeResponse("not xml at all <<<")})
    result = rss_client.fetch_feed(session, "https://example.com/feed", sleep_fn=no_sleep)
    assert not result.ok
    assert "XML parse error" in result.error


def test_access_test_pass_with_one_configured_feed():
    session = FakeSession({"https://example.com/feed": FakeResponse(RSS_XML)})
    result = rss_client.access_test(session, feed_urls=["https://example.com/feed"], sleep_fn=no_sleep)
    assert result.ok
    assert result.data["total_entries"] == 2


def test_access_test_fails_with_no_feed_urls():
    result = rss_client.access_test(FakeSession({}), feed_urls=[], sleep_fn=no_sleep)
    assert not result.ok
    assert "no feed_urls" in result.error


def test_access_test_fails_when_all_feeds_fail():
    session = FakeSession({"https://example.com/feed": FakeResponse("", status_ok=False)})
    result = rss_client.access_test(session, feed_urls=["https://example.com/feed"], sleep_fn=no_sleep)
    assert not result.ok


def test_access_test_passes_if_at_least_one_of_several_feeds_works():
    session = FakeSession(
        {
            "https://good.example.com/feed": FakeResponse(RSS_XML),
            "https://bad.example.com/feed": FakeResponse("", status_ok=False),
        }
    )
    result = rss_client.access_test(
        session, feed_urls=["https://good.example.com/feed", "https://bad.example.com/feed"], sleep_fn=no_sleep
    )
    assert result.ok
    assert result.data["total_entries"] == 2
