"""Tests for the alternative.me Fear & Greed provider."""
import json
from pathlib import Path
from unittest.mock import MagicMock

from whenshouldubuybitcoin.providers import alternative_me as am

FIXTURE = Path(__file__).parent / "fixtures" / "alternative_me_history.json"


def test_history_parses_fixture(monkeypatch):
    payload = json.loads(FIXTURE.read_text())

    def fake_get(url, timeout=None):
        assert "limit=0" in url
        resp = MagicMock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(am.requests, "get", fake_get)
    rows = am.fetch_fear_and_greed_history()
    assert rows and len(rows) == len(payload["data"])
    assert all(set(r) == {"date", "value"} for r in rows)
    assert all(isinstance(r["value"], int) for r in rows)
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates)
    assert all(len(d) == 10 and d[4] == "-" for d in dates)


def test_history_returns_none_on_error(monkeypatch):
    def fake_get(url, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(am.requests, "get", fake_get)
    assert am.fetch_fear_and_greed_history() is None
