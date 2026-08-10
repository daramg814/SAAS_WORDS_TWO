from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlencode

import requests

# DEMAND-001 follow-up (2026-08-11): a "fundamentally different kind of data
# source" per the design roadmap's option (c) - not another developer/
# software-community text corpus (HN/GH Archive/Stack Exchange all share the
# same boilerplate-heavy failure mode, see ACTIVE_ISSUES.md DEMAND-001).
# Apple's App Store customer-review RSS and the iTunes Search API are both
# official, public, key-free (no login/OAuth/API key, unlike Reddit's 2026
# lockdown or the CFPB/FTC/Product Hunt APIs also probed for this - all three
# require credentials this session cannot self-provision). Real end users,
# each a distinct reviewer, describe concrete complaints about an existing
# app in their own words - genuinely different content shape from GitHub
# issues or Ask-HN templates.
SEARCH_URL = "https://itunes.apple.com/search"
REVIEWS_URL_TEMPLATE = "https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortby=mostrecent/json"


class SupportsGet(Protocol):
    def get(self, url: str, timeout: float) -> Any: ...


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    data: Any
    attempts: int
    error: str | None = None


def _get_json(
    session: SupportsGet, url: str, *, retry_attempts: int, timeout: float = 10.0, sleep_fn=time.sleep
) -> FetchResult:
    last_error = None
    for attempt in range(1, retry_attempts + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return FetchResult(ok=True, data=response.json(), attempts=attempt)
        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)
            if attempt < retry_attempts:
                sleep_fn(2 ** (attempt - 1))
    return FetchResult(ok=False, data=None, attempts=retry_attempts, error=last_error)


def search_apps(
    session: SupportsGet, term: str, *, country: str = "us", limit: int = 20,
    retry_attempts: int = 3, sleep_fn=time.sleep,
) -> FetchResult:
    params = {"term": term, "country": country, "entity": "software", "limit": limit}
    return _get_json(session, f"{SEARCH_URL}?{urlencode(params)}", retry_attempts=retry_attempts, sleep_fn=sleep_fn)


def normalize_app_hit(hit: dict) -> dict | None:
    track_id = hit.get("trackId")
    name = hit.get("trackName")
    if track_id is None or not name:
        return None
    return {"app_id": int(track_id), "name": name, "genres": hit.get("genres") or []}


def fetch_reviews(
    session: SupportsGet, app_id: int, *, country: str = "us",
    retry_attempts: int = 3, sleep_fn=time.sleep,
) -> FetchResult:
    url = REVIEWS_URL_TEMPLATE.format(country=country, app_id=app_id)
    return _get_json(session, url, retry_attempts=retry_attempts, sleep_fn=sleep_fn)


def make_item_id(review_id: int) -> int:
    """"7" + 12-digit zero-padded review id - disambiguates from HN (still
    tens of millions as of 2026), GH Archive (billions), and Stack Exchange
    (explicit "9"+sitecode+postid) id ranges. Real observed review ids are
    8-11 digits; 12-digit padding leaves headroom."""
    return int(f"7{review_id:012d}")


def _parse_updated(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except ValueError:
        return None


def normalize_review(app_id: int, entry: dict) -> dict | None:
    """One <entry> from the customer-reviews RSS-as-JSON feed. Entries
    without a rating/content are feed metadata, not real reviews (Apple's
    feed does not consistently separate these with a distinct shape, so
    presence of the review-only fields is the actual signal)."""
    if "im:rating" not in entry or "content" not in entry:
        return None
    review_id = entry.get("id", {}).get("label")
    if not review_id or not str(review_id).isdigit():
        return None
    author = entry.get("author", {}).get("name", {}).get("label")
    if not author:
        return None
    content = entry.get("content", {}).get("label")
    title = entry.get("title", {}).get("label")
    return {
        "id": make_item_id(int(review_id)),
        "type": "story",
        "by": author,
        "time": _parse_updated(entry.get("updated", {}).get("label")),
        "text": content,
        "title": title,
        "url": f"https://itunes.apple.com/us/review?id={app_id}",
        "parent": None,
        "score": None,
        "descendants": None,
        "dead": 0,
        "deleted": 0,
    }


def access_test(session: SupportsGet, *, retry_attempts: int = 3, sleep_fn=time.sleep) -> FetchResult:
    """source-access skill sample: search for one real SaaS-category app,
    then fetch and normalize its review feed."""
    search_result = search_apps(session, "small business invoicing", limit=1, retry_attempts=retry_attempts, sleep_fn=sleep_fn)
    if not search_result.ok:
        return search_result
    results = search_result.data.get("results") if isinstance(search_result.data, dict) else None
    if not results:
        return FetchResult(ok=False, data=None, attempts=search_result.attempts, error="search returned no results")
    app = normalize_app_hit(results[0])
    if app is None:
        return FetchResult(ok=False, data=None, attempts=search_result.attempts, error="first hit missing trackId/trackName")

    reviews_result = fetch_reviews(session, app["app_id"], retry_attempts=retry_attempts, sleep_fn=sleep_fn)
    if not reviews_result.ok:
        return reviews_result
    entries = reviews_result.data.get("feed", {}).get("entry", []) if isinstance(reviews_result.data, dict) else []
    normalized = [r for r in (normalize_review(app["app_id"], e) for e in entries) if r is not None]
    if not normalized:
        return FetchResult(ok=False, data=None, attempts=reviews_result.attempts, error="no normalizable reviews in feed")
    return FetchResult(
        ok=True,
        data={"app_id": app["app_id"], "app_name": app["name"], "review_count": len(normalized)},
        attempts=reviews_result.attempts,
    )
