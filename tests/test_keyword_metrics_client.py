from pathlib import Path

import pytest
import requests

from saas_words_two.keyword_metrics_client import (
    ApiRuntimeConfig,
    GoogleAdsCredentials,
    KeywordMetricsBudgetExceeded,
    KeywordMetricsClient,
    KeywordMetricsCredentialsError,
    credentials_from_env,
    load_env_file,
)


class FakeResponse:
    def __init__(self, json_data, status_code=200, headers=None):
        self._json_data = json_data
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._json_data


class FakeSession:
    def __init__(self, token_responses=None, generate_responses=None):
        self.calls: list[tuple[str, dict]] = []
        self._token_responses = token_responses if token_responses is not None else [FakeResponse({"access_token": "tok1", "expires_in": 3600})]
        self._generate_responses = generate_responses or []

    def post(self, url, *, json, headers, timeout):
        self.calls.append((url, json))
        if "oauth2.googleapis.com" in url:
            entry = self._token_responses.pop(0) if isinstance(self._token_responses, list) else self._token_responses
        else:
            entry = self._generate_responses.pop(0)
        if isinstance(entry, Exception):
            raise entry
        return entry


CREDS = GoogleAdsCredentials(
    developer_token="dev-token",
    customer_id="1234567890",
    client_id="client-id",
    client_secret="client-secret",
    refresh_token="refresh-token",
)
CONFIG = ApiRuntimeConfig(batch_size=20, free_tier_budget=1000, min_request_interval_ms=0)


def no_sleep(_seconds):
    return None


def make_client(session, *, config=CONFIG, sleep_recorder=None, progress_fn=None):
    sleep_fn = sleep_recorder.append if sleep_recorder is not None else no_sleep
    return KeywordMetricsClient(
        CREDS, config, session=session, sleep_fn=sleep_fn, clock_fn=lambda: 0.0,
        progress_fn=progress_fn or (lambda done, total: None),
    )


# ---------------------------------------------------------------------------
# env file / credentials
# ---------------------------------------------------------------------------


def test_load_env_file_parses_key_value_pairs(tmp_path):
    path = tmp_path / ".env.local"
    path.write_text("# comment\nGOOGLE_ADS_DEVELOPER_TOKEN=abc\n\nGOOGLE_ADS_CUSTOMER_ID=123-456\n", encoding="utf-8")
    env = load_env_file(path)
    assert env == {"GOOGLE_ADS_DEVELOPER_TOKEN": "abc", "GOOGLE_ADS_CUSTOMER_ID": "123-456"}


def test_load_env_file_strips_trailing_inline_comments(tmp_path):
    # Real-world regression: Word_check's .env.local has lines like
    # "GOOGLE_ADS_CUSTOMER_ID=123  # test account (name)" - a naive parser
    # keeps the comment in the value and the API call 404s.
    path = tmp_path / ".env.local"
    path.write_text(
        "GOOGLE_ADS_CUSTOMER_ID=1756305286  # Test client account under test manager\n"
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID=4783111482\t# Test manager account\n",
        encoding="utf-8",
    )
    env = load_env_file(path)
    assert env["GOOGLE_ADS_CUSTOMER_ID"] == "1756305286"
    assert env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"] == "4783111482"


def test_load_env_file_missing_file_raises(tmp_path):
    with pytest.raises(KeywordMetricsCredentialsError):
        load_env_file(tmp_path / "nope.env")


def test_credentials_from_env_missing_required_key_raises():
    with pytest.raises(KeywordMetricsCredentialsError, match="GOOGLE_ADS_REFRESH_TOKEN"):
        credentials_from_env(
            {
                "GOOGLE_ADS_DEVELOPER_TOKEN": "d",
                "GOOGLE_ADS_CUSTOMER_ID": "1",
                "GOOGLE_ADS_CLIENT_ID": "c",
                "GOOGLE_ADS_CLIENT_SECRET": "s",
            }
        )


def test_credentials_from_env_strips_hyphens_from_ids():
    creds = credentials_from_env(
        {
            "GOOGLE_ADS_DEVELOPER_TOKEN": "d",
            "GOOGLE_ADS_CUSTOMER_ID": "123-456-7890",
            "GOOGLE_ADS_CLIENT_ID": "c",
            "GOOGLE_ADS_CLIENT_SECRET": "s",
            "GOOGLE_ADS_REFRESH_TOKEN": "r",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "999-888-7777",
        }
    )
    assert creds.customer_id == "1234567890"
    assert creds.login_customer_id == "9998887777"


# ---------------------------------------------------------------------------
# fetch_metrics
# ---------------------------------------------------------------------------


def test_fetch_metrics_success_normalizes_response():
    session = FakeSession(
        generate_responses=[
            FakeResponse(
                {
                    "results": [
                        {
                            "text": "Ledger Pilot",
                            "keywordIdeaMetrics": {
                                "avgMonthlySearches": 1500,
                                "competition": "LOW",
                                "competitionIndex": 0,
                            },
                        }
                    ]
                }
            )
        ]
    )
    client = make_client(session)
    records = client.fetch_metrics(["Ledger Pilot"])
    assert len(records) == 1
    record = records[0]
    assert record.word == "Ledger Pilot"
    assert record.avg_monthly_searches == 1500
    assert record.competition_index == 0
    assert record.api_status == "success"


def test_fetch_metrics_coerces_string_encoded_int64_avg_searches():
    # Real-world regression: Google Ads API serializes int64 proto fields
    # (avgMonthlySearches) as JSON strings, not numbers. A raw pass-through
    # crashes downstream '>=' threshold comparisons.
    session = FakeSession(
        generate_responses=[
            FakeResponse(
                {
                    "results": [
                        {
                            "text": "Ledger Pilot",
                            "keywordIdeaMetrics": {"avgMonthlySearches": "1500", "competitionIndex": 0},
                        }
                    ]
                }
            )
        ]
    )
    client = make_client(session)
    record = client.fetch_metrics(["Ledger Pilot"])[0]
    assert record.avg_monthly_searches == 1500
    assert isinstance(record.avg_monthly_searches, float)
    assert record.competition_index == 0


def test_fetch_metrics_no_data_for_word_is_null_not_zero():
    # generateKeywordIdeas omits keywordIdeaMetrics entirely for statistically
    # insignificant terms - portable-build-spec.md §8.1. Must stay None, never 0.
    session = FakeSession(generate_responses=[FakeResponse({"results": []})])
    client = make_client(session)
    records = client.fetch_metrics(["Zonko Flarp"])
    assert records[0].avg_monthly_searches is None
    assert records[0].competition_index is None
    assert records[0].api_status == "failed"


def test_fetch_metrics_splits_batches_at_hard_limit_20():
    words = [f"Word{i} Pilot" for i in range(25)]
    session = FakeSession(generate_responses=[FakeResponse({"results": []}), FakeResponse({"results": []})])
    client = make_client(session)
    records = client.fetch_metrics(words)
    assert len(records) == 25
    generate_calls = [c for c in session.calls if "generateKeywordIdeas" in c[0]]
    assert len(generate_calls) == 2
    assert len(generate_calls[0][1]["keywordSeed"]["keywords"]) == 20
    assert len(generate_calls[1][1]["keywordSeed"]["keywords"]) == 5


def test_fetch_metrics_reports_progress_after_every_batch():
    # 2026-08-17 (GKP-001): a 9,645-word round gave zero visibility for 12+
    # minutes because fetch_metrics returned nothing until fully done.
    # progress_fn must fire once per completed batch with (done_so_far, total).
    words = [f"Word{i} Pilot" for i in range(25)]
    session = FakeSession(generate_responses=[FakeResponse({"results": []}), FakeResponse({"results": []})])
    calls = []
    client = make_client(session, progress_fn=lambda done, total: calls.append((done, total)))
    client.fetch_metrics(words)
    assert calls == [(20, 25), (25, 25)]


def test_default_progress_fn_prints_a_flushed_line(capsys):
    session = FakeSession(generate_responses=[FakeResponse({"results": []})])
    client = KeywordMetricsClient(CREDS, CONFIG, session=session, sleep_fn=no_sleep, clock_fn=lambda: 0.0)
    client.fetch_metrics(["Ledger Pilot"])
    out = capsys.readouterr().out
    assert "1/1" in out


def test_fetch_metrics_retries_connection_error_then_succeeds():
    # 2026-08-17 (GKP-001): real run hit RemoteDisconnected ~49% through a
    # 9,645-word round - requests.ConnectionError (no HTTP response at all,
    # so 401/429 handling never runs) must retry, not crash the whole round.
    session = FakeSession(
        generate_responses=[
            requests.exceptions.ConnectionError("Connection aborted."),
            FakeResponse(
                {"results": [{"text": "Ledger Pilot", "keywordIdeaMetrics": {"avgMonthlySearches": 500, "competitionIndex": 0}}]}
            ),
        ]
    )
    client = make_client(session)
    records = client.fetch_metrics(["Ledger Pilot"])
    assert records[0].avg_monthly_searches == 500
    assert records[0].api_status == "success"
    generate_calls = [c for c in session.calls if "generateKeywordIdeas" in c[0]]
    assert len(generate_calls) == 2  # first attempt failed, second succeeded


def test_fetch_metrics_connection_error_exhausts_retries_returns_failed_not_raises():
    session = FakeSession(
        generate_responses=[requests.exceptions.ConnectionError("boom")] * 3
    )
    client = make_client(session, config=ApiRuntimeConfig(batch_size=20, free_tier_budget=1000, min_request_interval_ms=0))
    records = client.fetch_metrics(["Ledger Pilot"])  # must not raise
    assert records[0].api_status == "failed"
    assert records[0].avg_monthly_searches is None
    assert records[0].competition_index is None
    assert client.request_count == 1  # one _fetch_batch call, despite 3 internal attempts


def test_fetch_metrics_retries_5xx_server_error_then_succeeds():
    # 2026-08-17 (GKP-001): real run hit "503 Service Unavailable" at 91%
    # through a 9,645-word round - response.raise_for_status() turned this
    # straight into an uncaught HTTPError with no retry. A 5xx is Google's
    # server being transiently unavailable, not a bad request - must retry.
    session = FakeSession(
        generate_responses=[
            FakeResponse({}, status_code=503),
            FakeResponse(
                {"results": [{"text": "Ledger Pilot", "keywordIdeaMetrics": {"avgMonthlySearches": 500, "competitionIndex": 0}}]}
            ),
        ]
    )
    client = make_client(session)
    records = client.fetch_metrics(["Ledger Pilot"])
    assert records[0].avg_monthly_searches == 500
    assert records[0].api_status == "success"
    generate_calls = [c for c in session.calls if "generateKeywordIdeas" in c[0]]
    assert len(generate_calls) == 2


def test_fetch_metrics_5xx_exhausts_retries_returns_failed_not_raises():
    session = FakeSession(generate_responses=[FakeResponse({}, status_code=503)] * 3)
    client = make_client(session)
    records = client.fetch_metrics(["Ledger Pilot"])  # must not raise
    assert records[0].api_status == "failed"
    assert client.request_count == 1


def test_fetch_metrics_calls_on_batch_fn_after_every_batch():
    # 2026-08-17 (GKP-001): incremental persistence hook - the caller uses
    # this to save results to disk per-batch so a crash mid-run doesn't lose
    # everything already fetched.
    words = [f"Word{i} Pilot" for i in range(25)]
    session = FakeSession(generate_responses=[FakeResponse({"results": []}), FakeResponse({"results": []})])
    batches = []
    client = KeywordMetricsClient(
        CREDS, CONFIG, session=session, sleep_fn=no_sleep, clock_fn=lambda: 0.0,
        on_batch_fn=lambda records: batches.append(len(records)),
    )
    client.fetch_metrics(words)
    assert batches == [20, 5]


def test_fetch_metrics_4xx_client_error_raises_immediately_not_retried():
    # A 4xx (e.g. bad request) is permanent - retrying wastes budget and time.
    session = FakeSession(generate_responses=[FakeResponse({}, status_code=400)])
    client = make_client(session)
    with pytest.raises(requests.exceptions.HTTPError):
        client.fetch_metrics(["Ledger Pilot"])
    generate_calls = [c for c in session.calls if "generateKeywordIdeas" in c[0]]
    assert len(generate_calls) == 1  # no retry attempts


def test_fetch_metrics_401_refreshes_token_and_retries_once():
    session = FakeSession(
        token_responses=[
            FakeResponse({"access_token": "tok1", "expires_in": 3600}),
            FakeResponse({"access_token": "tok2", "expires_in": 3600}),
        ],
        generate_responses=[
            FakeResponse({}, status_code=401),
            FakeResponse({"results": []}),
        ],
    )
    client = make_client(session)
    records = client.fetch_metrics(["Ledger Pilot"])
    assert records[0].api_status == "failed"
    generate_calls = [c for c in session.calls if "generateKeywordIdeas" in c[0]]
    assert len(generate_calls) == 2


def test_fetch_metrics_429_waits_retry_after_and_retries_once():
    waits = []
    session = FakeSession(
        generate_responses=[
            FakeResponse({}, status_code=429, headers={"retry-after": "7"}),
            FakeResponse({"results": []}),
        ]
    )
    client = make_client(session, sleep_recorder=waits)
    client.fetch_metrics(["Ledger Pilot"])
    assert 7.0 in waits


def test_fetch_metrics_budget_exceeded_raises_without_calling_api():
    session = FakeSession(generate_responses=[])
    client = make_client(session, config=ApiRuntimeConfig(batch_size=20, free_tier_budget=0, min_request_interval_ms=0))
    with pytest.raises(KeywordMetricsBudgetExceeded):
        client.fetch_metrics(["Ledger Pilot"])
    assert session.calls == []


def test_fetch_metrics_budget_exceeded_partway_through_batches():
    words = [f"Word{i} Pilot" for i in range(21)]  # 2 batches (20 + 1)
    session = FakeSession(generate_responses=[FakeResponse({"results": []})])
    client = make_client(session, config=ApiRuntimeConfig(batch_size=20, free_tier_budget=1, min_request_interval_ms=0))
    with pytest.raises(KeywordMetricsBudgetExceeded):
        client.fetch_metrics(words)
    assert client.request_count == 1
