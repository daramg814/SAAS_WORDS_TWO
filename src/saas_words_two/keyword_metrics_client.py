"""Google Ads API (Keyword Planner) client — 2026-08-17 통합, CLAUDE.md §2.3/§4,
memory/ACTIVE_ISSUES.md GKP-001 참고.

Word_check(`C:\\Share\\Claude_project\\Word_check\\src\\ads-api\\local-client.ts`,
`docs/portable-build-spec.md` §8)의 REST 호출 로직을 그대로 Python으로 이식했다 -
같은 공식 엔드포인트, 같은 OAuth 흐름, 같은 배치/재시도/예산 규칙을 재사용해
두 프로젝트가 서로 다른 결과를 내지 않게 한다. 스크래핑·CAPTCHA 우회·브라우저
자동화가 아니라 공식 Google Ads REST API만 쓴다(CLAUDE.md §2.3 개정 근거).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
BASE_URL = "https://googleads.googleapis.com/v23"
# generateKeywordIdeas 하드 제한(실측 확인, portable-build-spec.md §8.2): 20 초과 시
# 응답 누락/실패.
MAX_BATCH_SIZE = 20


class KeywordMetricsBudgetExceeded(Exception):
    """하루 API 호출 예산(config.free_tier_budget)을 넘어서는 조회 요청."""


class KeywordMetricsCredentialsError(Exception):
    """자격증명 파일이 없거나 필수 키가 빠짐 - 가짜로 통과시키지 않고 명시적으로 실패."""


@dataclass(frozen=True)
class GoogleAdsCredentials:
    developer_token: str
    customer_id: str
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str | None = None


@dataclass(frozen=True)
class ApiRuntimeConfig:
    batch_size: int = 20
    free_tier_budget: int = 1000
    min_request_interval_ms: int = 500
    geo_target_constants: str = ""
    language: str = "languageConstants/1000"
    keyword_plan_network: str = "GOOGLE_SEARCH"


@dataclass(frozen=True)
class KeywordMetricRecord:
    word: str
    avg_monthly_searches: float | None
    competition: str | None
    competition_index: float | None
    api_status: str  # "success" | "failed"


REQUIRED_ENV_KEYS = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CUSTOMER_ID",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
)


def load_env_file(path: Path) -> dict[str, str]:
    """Minimal `.env` parser (KEY=VALUE per line, `#` full-line or trailing
    inline comments, blank lines skipped). Word_check's `.env.local` (reused
    here, see GKP-001) has real trailing-comment lines like
    `GOOGLE_ADS_CUSTOMER_ID=123  # test account (name)` - a naive parser that
    keeps the comment corrupts the customer id and 404s against the API, so
    inline comments must be stripped the same way `dotenv` does. No
    python-dotenv dependency needed for this much (CLAUDE.md §8 - stdlib
    covers it)."""
    if not path.exists():
        raise KeywordMetricsCredentialsError(f"credentials file not found: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        value = rest.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            for marker in (" #", "\t#"):
                comment_start = value.find(marker)
                if comment_start != -1:
                    value = value[:comment_start].rstrip()
                    break
        values[key.strip()] = value
    return values


def credentials_from_env(env: dict[str, str]) -> GoogleAdsCredentials:
    missing = [key for key in REQUIRED_ENV_KEYS if not env.get(key)]
    if missing:
        raise KeywordMetricsCredentialsError(f"missing required credentials: {', '.join(missing)}")
    return GoogleAdsCredentials(
        developer_token=env["GOOGLE_ADS_DEVELOPER_TOKEN"],
        customer_id=env["GOOGLE_ADS_CUSTOMER_ID"].replace("-", ""),
        client_id=env["GOOGLE_ADS_CLIENT_ID"],
        client_secret=env["GOOGLE_ADS_CLIENT_SECRET"],
        refresh_token=env["GOOGLE_ADS_REFRESH_TOKEN"],
        login_customer_id=(env.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "").replace("-", "") or None,
    )


class SupportsRequests(Protocol):
    def post(self, url: str, *, json: Any, headers: dict, timeout: float) -> Any: ...


def _retry_after_seconds(response: Any, default: float = 4.0) -> float:
    header = getattr(response, "headers", {}).get("retry-after") if hasattr(response, "headers") else None
    if header is None:
        return default
    try:
        return float(header)
    except ValueError:
        return default


class KeywordMetricsClient:
    """Word_check `LocalAdsClient`와 동일한 규칙(§8): OAuth refresh-token 인증,
    배치당 최대 20개, 401은 토큰 재발급 후 1회 재시도, 429는 retry-after만큼
    대기 후 1회 재시도, 일일 예산 초과 시 명시적으로 실패(가짜 성공 없음)."""

    def __init__(
        self,
        credentials: GoogleAdsCredentials,
        config: ApiRuntimeConfig,
        *,
        session: SupportsRequests | None = None,
        sleep_fn=time.sleep,
        clock_fn=time.monotonic,
    ) -> None:
        self._creds = credentials
        self._config = config
        self._session = session or requests
        self._sleep_fn = sleep_fn
        self._clock_fn = clock_fn
        self._access_token: str | None = None
        self._token_expiry: float = 0.0
        self._request_count = 0
        self._last_request_time: float | None = None
        self._batch_size = min(config.batch_size, MAX_BATCH_SIZE)

    def _authenticate(self) -> str:
        if self._access_token and self._clock_fn() < self._token_expiry:
            return self._access_token
        response = self._session.post(
            TOKEN_URL,
            json={
                "refresh_token": self._creds.refresh_token,
                "client_id": self._creds.client_id,
                "client_secret": self._creds.client_secret,
                "grant_type": "refresh_token",
            },
            headers={},
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
        self._access_token = data["access_token"]
        self._token_expiry = self._clock_fn() + max(data.get("expires_in", 3600) - 60, 0)
        return self._access_token

    def _headers(self, token: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "developer-token": self._creds.developer_token,
        }
        if self._creds.login_customer_id:
            headers["login-customer-id"] = self._creds.login_customer_id
        return headers

    def _wait_for_rate_limit(self) -> None:
        if self._last_request_time is None:
            self._last_request_time = self._clock_fn()
            return
        elapsed_ms = (self._clock_fn() - self._last_request_time) * 1000
        min_interval = self._config.min_request_interval_ms
        if elapsed_ms < min_interval:
            self._sleep_fn((min_interval - elapsed_ms) / 1000)
        self._last_request_time = self._clock_fn()

    def _post_generate_keyword_ideas(self, words: list[str], token: str) -> Any:
        url = f"{BASE_URL}/customers/{self._creds.customer_id}:generateKeywordIdeas"
        body = {
            "keywordSeed": {"keywords": words},
            "keywordPlanNetwork": self._config.keyword_plan_network,
            "geoTargetConstants": [self._config.geo_target_constants] if self._config.geo_target_constants else [],
            "language": self._config.language,
            "includeAdultKeywords": False,
        }
        return self._session.post(url, json=body, headers=self._headers(token), timeout=30.0)

    def _fetch_batch(self, words: list[str]) -> list[KeywordMetricRecord]:
        remaining = self._config.free_tier_budget - self._request_count
        if remaining <= 0:
            raise KeywordMetricsBudgetExceeded(
                f"free_tier_budget exhausted ({self._request_count}/{self._config.free_tier_budget} calls used)"
            )

        self._wait_for_rate_limit()
        token = self._authenticate()
        response = self._post_generate_keyword_ideas(words, token)

        if response.status_code == 401:
            self._access_token = None
            self._token_expiry = 0.0
            token = self._authenticate()
            response = self._post_generate_keyword_ideas(words, token)

        if response.status_code == 429:
            self._sleep_fn(_retry_after_seconds(response))
            response = self._post_generate_keyword_ideas(words, token)

        self._request_count += 1
        response.raise_for_status()
        return _normalize_response(words, response.json())

    def fetch_metrics(self, words: list[str]) -> list[KeywordMetricRecord]:
        records: list[KeywordMetricRecord] = []
        for start in range(0, len(words), self._batch_size):
            chunk = words[start : start + self._batch_size]
            records.extend(self._fetch_batch(chunk))
        return records

    @property
    def request_count(self) -> int:
        return self._request_count


def _coerce_number(value: Any) -> float | None:
    """Google Ads API serializes proto int64 fields (avgMonthlySearches) as
    JSON strings, not numbers - the standard proto3 JSON mapping for int64,
    done to avoid precision loss in JS number types. competitionIndex is
    int32 and normally arrives as a number, but is coerced too for safety.
    Without this, comparing avg_monthly_searches >= threshold crashes with
    "'>=' not supported between instances of 'str' and 'int'" (found via a
    real API call, not a hypothetical)."""
    if value is None:
        return None
    if isinstance(value, str):
        return float(value)
    return float(value)


def _normalize_response(words: list[str], payload: dict) -> list[KeywordMetricRecord]:
    results = payload.get("results") if isinstance(payload, dict) else None
    metrics_by_text: dict[str, dict] = {}
    for item in results or []:
        metrics = item.get("keywordIdeaMetrics")
        if not metrics:
            continue
        text = item.get("text") or metrics.get("text") or ""
        metrics_by_text[text] = metrics

    records: list[KeywordMetricRecord] = []
    for word in words:
        metrics = metrics_by_text.get(word) or metrics_by_text.get(word.lower())
        avg = _coerce_number(metrics.get("avgMonthlySearches")) if metrics else None
        records.append(
            KeywordMetricRecord(
                word=word,
                avg_monthly_searches=avg,
                competition=(metrics.get("competition") if metrics else None),
                competition_index=(_coerce_number(metrics.get("competitionIndex")) if metrics else None),
                api_status="success" if avg is not None else "failed",
            )
        )
    return records
