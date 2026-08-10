from __future__ import annotations

import gzip
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import requests

from .text_filter import strip_html

# Official, key-free Common Crawl CDX index + WARC data endpoints. CLAUDE.md
# rule 4 / design 3.2: used only to enrich a domain the pipeline already has
# as a supply candidate (기능·가격·활성 상태 보강) - never to broadly search
# Common Crawl for new candidates (design 7.1: "Common Crawl 전체에서 제품을
# 막연히 검색하지 않는다").
CDX_BASE = "https://index.commoncrawl.org"
DATA_BASE = "https://data.commoncrawl.org"
EXCERPT_MAX_CHARS = 3000


class SupportsGet(Protocol):
    def get(self, url: str, timeout: float, headers: dict | None = None) -> Any: ...


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    data: Any
    attempts: int
    error: str | None = None


def _get(
    session: SupportsGet, url: str, *, retry_attempts: int, timeout: float, headers: dict | None, sleep_fn
) -> FetchResult:
    last_error = None
    for attempt in range(1, retry_attempts + 1):
        try:
            response = session.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            return FetchResult(ok=True, data=response, attempts=attempt)
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < retry_attempts:
                sleep_fn(2 ** (attempt - 1))
    return FetchResult(ok=False, data=None, attempts=retry_attempts, error=last_error)


def fetch_latest_index(session: SupportsGet, *, retry_attempts: int = 3, sleep_fn=time.sleep) -> FetchResult:
    """collinfo.json lists every crawl, newest first - this is how a session
    picks up new crawls automatically instead of hardcoding a CC-MAIN id
    that goes stale."""
    result = _get(
        session, f"{CDX_BASE}/collinfo.json", retry_attempts=retry_attempts, timeout=15.0, headers=None, sleep_fn=sleep_fn
    )
    if not result.ok:
        return result
    try:
        indexes = result.data.json()
    except ValueError as exc:
        return FetchResult(ok=False, data=None, attempts=result.attempts, error=f"invalid JSON: {exc}")
    if not indexes:
        return FetchResult(ok=False, data=None, attempts=result.attempts, error="collinfo.json returned zero indexes")
    return FetchResult(ok=True, data=indexes[0]["id"], attempts=result.attempts)


def lookup_captures(
    session: SupportsGet, domain: str, index_id: str, *, limit: int = 5, retry_attempts: int = 3, sleep_fn=time.sleep
) -> FetchResult:
    params = {"url": domain, "output": "json", "limit": limit}
    result = _get(
        session,
        f"{CDX_BASE}/{index_id}-index?{urlencode(params)}",
        retry_attempts=retry_attempts,
        timeout=15.0,
        headers=None,
        sleep_fn=sleep_fn,
    )
    if not result.ok:
        return result
    captures = []
    for line in result.data.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            import json

            record = json.loads(line)
        except ValueError:
            continue
        if record.get("status") == "200" and "html" in (record.get("mime") or ""):
            captures.append(record)
    return FetchResult(ok=True, data=captures, attempts=result.attempts)


def extract_html_body(warc_gz_bytes: bytes) -> str | None:
    """A CDX capture's WARC record is: WARC header block, blank line, HTTP
    response header block, blank line, then the page body - splitting on the
    double-CRLF twice is enough without a full WARC-spec parser."""
    try:
        raw = gzip.decompress(warc_gz_bytes)
    except OSError:
        return None
    parts = raw.split(b"\r\n\r\n", 2)
    if len(parts) < 3:
        return None
    body = parts[2]
    return body.decode("utf-8", errors="replace")


def fetch_capture_excerpt(
    session: SupportsGet, capture: dict, *, retry_attempts: int = 3, sleep_fn=time.sleep
) -> FetchResult:
    offset = int(capture["offset"])
    length = int(capture["length"])
    url = f"{DATA_BASE}/{capture['filename']}"
    headers = {"Range": f"bytes={offset}-{offset + length - 1}"}
    result = _get(session, url, retry_attempts=retry_attempts, timeout=30.0, headers=headers, sleep_fn=sleep_fn)
    if not result.ok:
        return result
    html = extract_html_body(result.data.content)
    if html is None:
        return FetchResult(ok=False, data=None, attempts=result.attempts, error="could not extract HTML body from WARC record")
    excerpt = strip_html(html).strip()[:EXCERPT_MAX_CHARS]
    return FetchResult(ok=True, data=excerpt, attempts=result.attempts)


def fetch_domain_excerpt(
    session: SupportsGet, domain: str, index_id: str, *, retry_attempts: int = 3, sleep_fn=time.sleep
) -> FetchResult:
    """The full enrichment flow for one candidate domain: latest capture ->
    range-fetch -> HTML-to-text excerpt. Returns ok=False (not an error worth
    surfacing loudly) if the domain simply has no Common Crawl capture -
    that's an expected, common outcome, not a failure of the source itself."""
    captures = lookup_captures(session, domain, index_id, limit=1, retry_attempts=retry_attempts, sleep_fn=sleep_fn)
    if not captures.ok:
        return captures
    if not captures.data:
        return FetchResult(ok=False, data=None, attempts=captures.attempts, error="no captures found for domain")
    return fetch_capture_excerpt(session, captures.data[0], retry_attempts=retry_attempts, sleep_fn=sleep_fn)


def access_test(
    session: SupportsGet, *, sample_domain: str = "stripe.com", retry_attempts: int = 3, sleep_fn=time.sleep
) -> FetchResult:
    """source-access skill sample: index discovery -> CDX lookup -> WARC
    range fetch -> HTML extraction, against one well-known, reliably-crawled
    domain."""
    index_result = fetch_latest_index(session, retry_attempts=retry_attempts, sleep_fn=sleep_fn)
    if not index_result.ok:
        return index_result

    excerpt_result = fetch_domain_excerpt(
        session, sample_domain, index_result.data, retry_attempts=retry_attempts, sleep_fn=sleep_fn
    )
    if not excerpt_result.ok:
        return excerpt_result

    return FetchResult(
        ok=True,
        data={"index_id": index_result.data, "domain": sample_domain, "excerpt_chars": len(excerpt_result.data)},
        attempts=excerpt_result.attempts,
    )
