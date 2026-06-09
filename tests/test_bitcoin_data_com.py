"""Tests for the bitcoin-data.com (BGeometrics) provider."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from whenshouldubuybitcoin.providers import bitcoin_data_com as bdc

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "bitcoin_data_com"


@pytest.mark.parametrize("metric_key", list(bdc.ONCHAIN_ENDPOINTS))
def test_parse_series_real_fixture(metric_key):
    rows = json.loads((FIXTURE_DIR / f"{metric_key}.json").read_text())
    parsed = bdc.parse_series(rows)
    assert len(parsed) > 1000, f"{metric_key}: expected ~4y of rows"
    day, value = parsed[-1]
    assert len(day) == 10 and day[4] == "-" and day[7] == "-"
    assert isinstance(value, float)
    # ascending dates
    assert [d for d, _ in parsed] == sorted(d for d, _ in parsed)


def test_parse_series_skips_bad_rows():
    rows = [
        {"d": "2025-01-01", "unixTs": "1735689600", "mvrv": "1.5"},
        {"d": "2025-01-02", "unixTs": "1735776000", "mvrv": None},
        {"unixTs": "1735862400", "mvrv": "2.0"},
        "garbage",
        {"d": "2025-01-04", "unixTs": "1735948800", "mvrv": "not-a-number"},
    ]
    assert bdc.parse_series(rows) == [("2025-01-01", 1.5)]


def test_parse_series_handles_empty():
    assert bdc.parse_series([]) == []
    assert bdc.parse_series(None) == []


def test_fetch_series_retries_then_fails(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(bdc.requests, "get", fake_get)
    monkeypatch.setattr(bdc.time, "sleep", lambda s: None)
    assert bdc.fetch_series("mvrv", max_retries=2) is None
    assert len(calls) == 2


def test_fetch_series_sends_token_and_startday(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(url=url, params=params, headers=headers)
        resp = MagicMock()
        resp.json.return_value = []
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(bdc.requests, "get", fake_get)
    monkeypatch.setenv("BGEOMETRICS_TOKEN", "abc123")
    assert bdc.fetch_series("mvrv", startday="2026-06-01") == []
    assert captured["url"].endswith("/v1/mvrv")
    assert captured["params"] == {"startday": "2026-06-01"}
    assert captured["headers"] == {"Authorization": "Bearer abc123"}


def test_fetch_series_no_token_no_header(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["headers"] = headers
        resp = MagicMock()
        resp.json.return_value = []
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(bdc.requests, "get", fake_get)
    monkeypatch.delenv("BGEOMETRICS_TOKEN", raising=False)
    bdc.fetch_series("mvrv")
    assert captured["headers"] == {}


def test_fetch_all_spaces_requests_and_skips_failures(monkeypatch):
    sleeps = []
    monkeypatch.setattr(bdc.time, "sleep", lambda s: sleeps.append(s))

    def fake_fetch(metric_key, startday=None):
        if metric_key == "mvrv":
            return None  # simulated failure -> omitted from result
        return [("2026-06-08", 1.0)]

    monkeypatch.setattr(bdc, "fetch_series", fake_fetch)
    out = bdc.fetch_all_onchain_series(startday="2026-06-01")
    assert set(out) == set(bdc.ONCHAIN_ENDPOINTS) - {"mvrv"}
    # one spacing sleep between each consecutive pair of calls
    assert sleeps == [bdc.REQUEST_SPACING_SECONDS] * (len(bdc.ONCHAIN_ENDPOINTS) - 1)
