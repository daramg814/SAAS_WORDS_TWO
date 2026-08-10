from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import requests

# Official, key-free, login-free npm registry search API (the same endpoint
# npmjs.com's own search box uses) - design 3.2's "개발자 도구·오픈소스 대체재
# 공급 보조" source.
BASE_URL = "https://registry.npmjs.org"


class SupportsGet(Protocol):
    def get(self, url: str, timeout: float) -> Any: ...


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    data: Any
    attempts: int
    error: str | None = None


def _get_json(
    session: SupportsGet, path: str, *, retry_attempts: int, timeout: float = 10.0, sleep_fn=time.sleep
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


def search_packages(
    session: SupportsGet, query: str, *, size: int = 20, retry_attempts: int = 3, sleep_fn=time.sleep
) -> FetchResult:
    params = {"text": query, "size": size}
    return _get_json(session, f"-/v1/search?{urlencode(params)}", retry_attempts=retry_attempts, sleep_fn=sleep_fn)


def normalize_hit(hit: dict) -> dict | None:
    package = hit.get("package") or {}
    name = package.get("name")
    if not name:
        return None
    links = package.get("links") or {}
    return {
        "name": name,
        "description": package.get("description"),
        "url": links.get("npm") or f"https://www.npmjs.com/package/{name}",
        "homepage": links.get("homepage"),
        "repository": links.get("repository"),
    }


def access_test(session: SupportsGet, *, retry_attempts: int = 3, sleep_fn=time.sleep) -> FetchResult:
    """source-access skill sample: one real search, confirm the response has
    the expected objects/package/links shape."""
    result = search_packages(session, "cli tool", size=1, retry_attempts=retry_attempts, sleep_fn=sleep_fn)
    if not result.ok:
        return result
    if not isinstance(result.data, dict) or "objects" not in result.data:
        return FetchResult(ok=False, data=None, attempts=result.attempts, error="response missing 'objects'")
    objects = result.data["objects"]
    if not objects:
        return FetchResult(ok=False, data=None, attempts=result.attempts, error="search returned zero objects")
    normalized = normalize_hit(objects[0])
    if normalized is None:
        return FetchResult(ok=False, data=None, attempts=result.attempts, error="first hit missing package.name")
    return FetchResult(ok=True, data={"total": result.data.get("total"), "sample_name": normalized["name"]}, attempts=result.attempts)
