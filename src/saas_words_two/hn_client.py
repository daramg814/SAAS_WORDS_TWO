from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import requests

BASE_URL = "https://hacker-news.firebaseio.com/v0"
SEARCH_BASE_URL = "https://hn.algolia.com/api/v1"
STORY_LISTS = ("newstories", "askstories", "showstories")


class SupportsGet(Protocol):
    def get(self, url: str, timeout: float) -> Any: ...


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    data: Any
    attempts: int
    error: str | None = None


def _get_json(
    session: SupportsGet,
    path: str,
    *,
    retry_attempts: int,
    timeout: float = 10.0,
    sleep_fn=time.sleep,
    base_url: str = BASE_URL,
) -> FetchResult:
    last_error = None
    for attempt in range(1, retry_attempts + 1):
        try:
            response = session.get(f"{base_url}/{path}", timeout=timeout)
            response.raise_for_status()
            return FetchResult(ok=True, data=response.json(), attempts=attempt)
        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)
            if attempt < retry_attempts:
                sleep_fn(2 ** (attempt - 1))
    return FetchResult(ok=False, data=None, attempts=retry_attempts, error=last_error)


def access_test(session: SupportsGet, *, retry_attempts: int = 3, sleep_fn=time.sleep) -> FetchResult:
    """Minimal accessibility sample per source-access skill: fetch maxitem, one real item,
    and one search hit, since collection depends on both the Firebase item API and the
    Algolia-backed search API."""
    max_item = _get_json(session, "maxitem.json", retry_attempts=retry_attempts, sleep_fn=sleep_fn)
    if not max_item.ok or not isinstance(max_item.data, int):
        return FetchResult(
            ok=False, data=None, attempts=max_item.attempts, error=max_item.error or "maxitem not an int"
        )
    sample = _get_json(
        session, f"item/{max_item.data}.json", retry_attempts=retry_attempts, sleep_fn=sleep_fn
    )
    if not sample.ok or not isinstance(sample.data, dict):
        return FetchResult(
            ok=False, data=None, attempts=sample.attempts, error=sample.error or "sample item not an object"
        )
    search_sample = search_items(session, "the", hits_per_page=1, retry_attempts=retry_attempts, sleep_fn=sleep_fn)
    if not search_sample.ok or not isinstance(search_sample.data, dict) or "hits" not in search_sample.data:
        return FetchResult(
            ok=False,
            data=None,
            attempts=search_sample.attempts,
            error=search_sample.error or "search response missing 'hits'",
        )
    return FetchResult(
        ok=True,
        data={"max_item": max_item.data, "sample_item": sample.data, "search_hits": len(search_sample.data["hits"])},
        attempts=sample.attempts,
    )


def fetch_story_list(
    session: SupportsGet, list_name: str, *, retry_attempts: int = 3, sleep_fn=time.sleep
) -> FetchResult:
    if list_name not in STORY_LISTS:
        raise ValueError(f"unknown story list: {list_name}")
    return _get_json(session, f"{list_name}.json", retry_attempts=retry_attempts, sleep_fn=sleep_fn)


def fetch_item(
    session: SupportsGet, item_id: int, *, retry_attempts: int = 3, sleep_fn=time.sleep
) -> FetchResult:
    return _get_json(session, f"item/{item_id}.json", retry_attempts=retry_attempts, sleep_fn=sleep_fn)


def search_items(
    session: SupportsGet,
    query: str,
    *,
    tags: str = "(story,comment)",
    hits_per_page: int = 50,
    page: int = 0,
    created_after_epoch: int | None = None,
    retry_attempts: int = 3,
    sleep_fn=time.sleep,
) -> FetchResult:
    """Full-text search across all of HN history via the official Algolia-backed
    search API (hn.algolia.com), the same public, key-free, login-free endpoint
    linked from HN's own search page. Complements the sequential/list-based
    Firebase collection, which only reaches recently active items and cannot
    practically satisfy the 24-month evidence window on its own.

    NOTE: tags must use OR-group syntax "(story,comment)" — a bare
    "story,comment" is interpreted as AND and always returns zero hits.
    """
    params = {"query": query, "tags": tags, "hitsPerPage": hits_per_page, "page": page}
    if created_after_epoch is not None:
        params["numericFilters"] = f"created_at_i>{created_after_epoch}"
    path = f"search?{urlencode(params)}"
    return _get_json(
        session, path, retry_attempts=retry_attempts, sleep_fn=sleep_fn, base_url=SEARCH_BASE_URL
    )


def normalize_algolia_hit(hit: dict) -> dict:
    tags = hit.get("_tags") or []
    if "comment" in tags:
        item_type = "comment"
    elif "job" in tags:
        item_type = "job"
    elif "poll" in tags:
        item_type = "poll"
    else:
        item_type = "story"
    return {
        "id": int(hit["objectID"]),
        "type": item_type,
        "by": hit.get("author"),
        "time": hit.get("created_at_i"),
        "text": hit.get("comment_text") or hit.get("story_text"),
        "title": hit.get("title"),
        "url": hit.get("url"),
        "parent": hit.get("parent_id") if item_type == "comment" else None,
        "score": hit.get("points"),
        "descendants": hit.get("num_comments"),
        "dead": 0,
        "deleted": 0,
    }


def normalize_item(raw: dict) -> dict:
    return {
        "id": raw["id"],
        "type": raw.get("type"),
        "by": raw.get("by"),
        "time": raw.get("time"),
        "text": raw.get("text"),
        "title": raw.get("title"),
        "url": raw.get("url"),
        "parent": raw.get("parent"),
        "score": raw.get("score"),
        "descendants": raw.get("descendants"),
        "dead": 1 if raw.get("dead") else 0,
        "deleted": 1 if raw.get("deleted") else 0,
    }
