from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import requests

# design 3.2: "공식 RSS·Atom | 특정 산업의 공개 문제·공지 | 고정 피드 URL과 증분
# 수집 PASS" - a curated, fixed list of feed URLs (config/sources.yaml's
# official_feeds.feed_urls), not a discovery/crawl mechanism. Both RSS 2.0
# and Atom are plain XML, so - unlike Stack Exchange's 7z - the stdlib's
# xml.etree.ElementTree is enough; no new dependency needed.


class SupportsGet(Protocol):
    def get(self, url: str, timeout: float) -> Any: ...


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    data: Any
    attempts: int
    error: str | None = None


def _fetch_text(
    session: SupportsGet, url: str, *, retry_attempts: int, timeout: float, sleep_fn
) -> FetchResult:
    last_error = None
    for attempt in range(1, retry_attempts + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return FetchResult(ok=True, data=response.text, attempts=attempt)
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < retry_attempts:
                sleep_fn(2 ** (attempt - 1))
    return FetchResult(ok=False, data=None, attempts=retry_attempts, error=last_error)


def _local(tag: str) -> str:
    """Strips a namespace ("{http://...}tag" -> "tag") so RSS 2.0 (no
    namespace) and Atom (always namespaced) can be walked with the same
    lookups."""
    return tag.rsplit("}", 1)[-1]


def _find_child_text(elem: ET.Element, *names: str) -> str | None:
    for child in elem:
        if _local(child.tag) in names:
            return (child.text or "").strip() or None
    return None


def _parse_date(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).astimezone(timezone.utc).timestamp())
    except (ValueError, TypeError):
        pass
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())
    except ValueError:
        return None


def make_item_id(feed_url: str, guid: str) -> int:
    """RSS guid/Atom id are arbitrary strings (often URLs), not integers -
    hashed into a 12-digit id prefixed with 8 (Stack Exchange uses the same
    12-digit shape prefixed with 9; GH Archive/HN ids don't reach 12 digits
    yet) to keep this source's id namespace disjoint from the others.
    Collision probability at any realistic feed-entry volume is negligible
    (birthday bound on an 11-digit space), and a rare collision would just
    silently skip one duplicate-looking insert, not corrupt data."""
    digest_int = int(hashlib.sha256(f"{feed_url}|{guid}".encode()).hexdigest(), 16)
    suffix = digest_int % 10**11
    return int(f"8{suffix:011d}")


def _parse_rss_item(feed_url: str, item: ET.Element) -> dict | None:
    guid = _find_child_text(item, "guid") or _find_child_text(item, "link")
    if not guid:
        return None
    return {
        "id": make_item_id(feed_url, guid),
        "type": "story",
        "by": _find_child_text(item, "creator"),
        "time": _parse_date(_find_child_text(item, "pubDate")),
        "text": _find_child_text(item, "description", "encoded"),
        "title": _find_child_text(item, "title"),
        "url": _find_child_text(item, "link"),
        "parent": None,
        "score": None,
        "descendants": None,
        "dead": 0,
        "deleted": 0,
    }


def _atom_link(entry: ET.Element) -> str | None:
    for child in entry:
        if _local(child.tag) == "link":
            href = child.get("href")
            if href and child.get("rel", "alternate") == "alternate":
                return href
    for child in entry:
        if _local(child.tag) == "link" and child.get("href"):
            return child.get("href")
    return None


def _parse_atom_entry(feed_url: str, entry: ET.Element) -> dict | None:
    guid = _find_child_text(entry, "id") or _atom_link(entry)
    if not guid:
        return None
    return {
        "id": make_item_id(feed_url, guid),
        "type": "story",
        "by": None,
        "time": _parse_date(_find_child_text(entry, "updated", "published")),
        "text": _find_child_text(entry, "summary", "content"),
        "title": _find_child_text(entry, "title"),
        "url": _atom_link(entry),
        "parent": None,
        "score": None,
        "descendants": None,
        "dead": 0,
        "deleted": 0,
    }


def parse_feed(feed_url: str, xml_text: str) -> list[dict]:
    """Parses either RSS 2.0 (<rss><channel><item>...) or Atom
    (<feed><entry>...) from the same entry point - dispatched by root tag."""
    root = ET.fromstring(xml_text)
    root_tag = _local(root.tag)
    entries: list[dict] = []
    if root_tag == "rss":
        for item in root.iter():
            if _local(item.tag) == "item":
                normalized = _parse_rss_item(feed_url, item)
                if normalized is not None:
                    entries.append(normalized)
    elif root_tag == "feed":
        for entry in root:
            if _local(entry.tag) == "entry":
                normalized = _parse_atom_entry(feed_url, entry)
                if normalized is not None:
                    entries.append(normalized)
    return entries


def fetch_feed(
    session: SupportsGet, feed_url: str, *, retry_attempts: int = 3, timeout: float = 15.0, sleep_fn=time.sleep
) -> FetchResult:
    fetched = _fetch_text(session, feed_url, retry_attempts=retry_attempts, timeout=timeout, sleep_fn=sleep_fn)
    if not fetched.ok:
        return fetched
    try:
        entries = parse_feed(feed_url, fetched.data)
    except ET.ParseError as exc:
        return FetchResult(ok=False, data=None, attempts=fetched.attempts, error=f"XML parse error: {exc}")
    return FetchResult(ok=True, data=entries, attempts=fetched.attempts)


def access_test(
    session: SupportsGet, *, feed_urls: list[str], retry_attempts: int = 3, sleep_fn=time.sleep
) -> FetchResult:
    """source-access skill sample: fetch and parse every configured feed URL;
    PASS requires at least one feed to be reachable and parse to at least one
    entry (a feed with genuinely zero posts is implausible for any real
    config, so zero entries across every feed indicates a parsing problem,
    not an empty-but-valid feed)."""
    if not feed_urls:
        return FetchResult(ok=False, data=None, attempts=0, error="no feed_urls configured")

    per_feed: dict[str, dict] = {}
    total_entries = 0
    for feed_url in feed_urls:
        result = fetch_feed(session, feed_url, retry_attempts=retry_attempts, sleep_fn=sleep_fn)
        if result.ok:
            per_feed[feed_url] = {"ok": True, "entries": len(result.data)}
            total_entries += len(result.data)
        else:
            per_feed[feed_url] = {"ok": False, "error": result.error}

    if total_entries == 0:
        return FetchResult(ok=False, data=per_feed, attempts=retry_attempts, error="zero entries parsed across all configured feeds")
    return FetchResult(ok=True, data={"feeds": per_feed, "total_entries": total_entries}, attempts=retry_attempts)
