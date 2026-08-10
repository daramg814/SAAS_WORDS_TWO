from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

import requests

BASE_URL = "https://hacker-news.firebaseio.com/v0"
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
) -> FetchResult:
    last_error = None
    for attempt in range(1, retry_attempts + 1):
        try:
            response = session.get(f"{BASE_URL}/{path}", timeout=timeout)
            response.raise_for_status()
            return FetchResult(ok=True, data=response.json(), attempts=attempt)
        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)
            if attempt < retry_attempts:
                sleep_fn(2 ** (attempt - 1))
    return FetchResult(ok=False, data=None, attempts=retry_attempts, error=last_error)


def access_test(session: SupportsGet, *, retry_attempts: int = 3, sleep_fn=time.sleep) -> FetchResult:
    """Minimal accessibility sample per source-access skill: fetch maxitem, then one real item."""
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
    return FetchResult(
        ok=True, data={"max_item": max_item.data, "sample_item": sample.data}, attempts=sample.attempts
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
