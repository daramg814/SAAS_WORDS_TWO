from __future__ import annotations

import gzip
import io
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import requests

BASE_URL = "https://data.gharchive.org"

# GH Archive hourly dumps carry every public GitHub event (PushEvent alone is
# ~97% of a typical hour). Only these two carry first-person problem/feature
# text (see docs/policies/04-data-source-policy.md, GH Archive row: "기능
# 요청·수작업·내부 스크립트 문제"). PullRequestEvent bodies are code-change
# descriptions, not problem statements, and GH Archive's use for supply-side
# tool discovery (design doc 7.1) is out of scope for this batch.
ISSUES_EVENT = "IssuesEvent"
ISSUE_COMMENT_EVENT = "IssueCommentEvent"


class SupportsGet(Protocol):
    def get(self, url: str, timeout: float) -> Any: ...


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    data: Any
    attempts: int
    error: str | None = None


def hour_key(dt: datetime) -> str:
    """GH Archive's hourly file naming: https://data.gharchive.org/YYYY-MM-DD-H.json.gz
    (H has no leading zero)."""
    return f"{dt.strftime('%Y-%m-%d')}-{dt.hour}"


def hour_key_to_datetime(hour: str) -> datetime:
    date_part, hour_part = hour.rsplit("-", 1)
    return datetime.strptime(date_part, "%Y-%m-%d").replace(hour=int(hour_part), tzinfo=timezone.utc)


def next_hour_key(hour: str) -> str:
    return hour_key(hour_key_to_datetime(hour) + timedelta(hours=1))


def fetch_hour(
    session: SupportsGet, hour: str, *, retry_attempts: int, timeout: float, sleep_fn
) -> FetchResult:
    url = f"{BASE_URL}/{hour}.json.gz"
    last_error = None
    for attempt in range(1, retry_attempts + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return FetchResult(ok=True, data=response.content, attempts=attempt)
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < retry_attempts:
                sleep_fn(2 ** (attempt - 1))
    return FetchResult(ok=False, data=None, attempts=retry_attempts, error=last_error)


def iter_hour_events(compressed: bytes):
    """Decompress and parse one hour's newline-delimited JSON events in memory.
    A single hour is ~20MB compressed / ~100MB decompressed but only ~0.1% of
    events are text-bearing issue/comment events - nothing from this stream is
    ever written to disk; only normalize_event()'s small output is persisted,
    into the same hn_items table HN collection already uses."""
    raw = gzip.decompress(compressed)
    for line in io.BytesIO(raw):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def is_bot_actor(actor: dict | None) -> bool:
    login = (actor or {}).get("login") or ""
    return login.endswith("[bot]")


def _parse_created_at(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        )
    except ValueError:
        return None


def normalize_event(event: dict) -> dict | None:
    """Map a GH Archive event onto the same shape hn_client.normalize_item()
    produces (id/type/by/time/text/title/url/parent/...), so it can be inserted
    into hn_items unchanged and flow through the existing filter/cluster/score
    pipeline. Only IssuesEvent(action=opened) and IssueCommentEvent(action=
    created) normalize; everything else (including bot-authored events, which
    are not independent human demand signals) returns None."""
    event_type = event.get("type")
    payload = event.get("payload") or {}
    actor = event.get("actor") or {}
    if is_bot_actor(actor):
        return None

    if event_type == ISSUES_EVENT and payload.get("action") == "opened":
        issue = payload.get("issue") or {}
        return {
            "id": issue.get("id"),
            "type": "story",
            "by": actor.get("login"),
            "time": _parse_created_at(event.get("created_at")),
            "text": issue.get("body"),
            "title": issue.get("title"),
            "url": issue.get("html_url"),
            "parent": None,
            "score": None,
            "descendants": None,
            "dead": 0,
            "deleted": 0,
        }
    if event_type == ISSUE_COMMENT_EVENT and payload.get("action") == "created":
        comment = payload.get("comment") or {}
        issue = payload.get("issue") or {}
        return {
            "id": comment.get("id"),
            "type": "comment",
            "by": actor.get("login"),
            "time": _parse_created_at(event.get("created_at")),
            "text": comment.get("body"),
            "title": None,
            "url": comment.get("html_url"),
            "parent": issue.get("id"),
            "score": None,
            "descendants": None,
            "dead": 0,
            "deleted": 0,
        }
    return None


def access_test(
    session: SupportsGet,
    *,
    hour: str | None = None,
    retry_attempts: int = 3,
    timeout: float = 30.0,
    sleep_fn=time.sleep,
) -> FetchResult:
    """Minimal accessibility sample per source-access skill: download one
    hourly .json.gz, gunzip it in memory, parse it as newline-delimited JSON,
    and confirm normalize_event() runs cleanly over it. Defaults to 6 hours
    before now, since GH Archive publishes each hour's file with some delay."""
    target_hour = hour or hour_key(datetime.now(timezone.utc) - timedelta(hours=6))
    fetched = fetch_hour(session, target_hour, retry_attempts=retry_attempts, timeout=timeout, sleep_fn=sleep_fn)
    if not fetched.ok:
        return fetched

    try:
        events = list(iter_hour_events(fetched.data))
    except OSError as exc:
        return FetchResult(ok=False, data=None, attempts=fetched.attempts, error=f"gunzip failed: {exc}")

    if not events:
        return FetchResult(ok=False, data=None, attempts=fetched.attempts, error="hour file parsed to zero events")

    normalizable = [item for item in (normalize_event(event) for event in events) if item is not None]
    return FetchResult(
        ok=True,
        data={
            "hour": target_hour,
            "compressed_bytes": len(fetched.data),
            "total_events": len(events),
            "normalizable_events": len(normalizable),
        },
        attempts=fetched.attempts,
    )
