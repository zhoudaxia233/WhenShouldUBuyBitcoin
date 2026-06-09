"""Tests for on-chain dataset persistence, merging, and the freshness guard."""
from datetime import date

import pandas as pd
import pytest

from whenshouldubuybitcoin import onchain_data as od


def _frame(rows: dict) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in od.ONCHAIN_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[od.ONCHAIN_COLUMNS]


def test_merge_new_wins_and_history_kept():
    existing = _frame({"date": ["2026-06-01", "2026-06-02"], "mvrv": [1.0, 1.1]})
    new = _frame({"date": ["2026-06-02", "2026-06-03"], "mvrv": [1.5, 1.6]})
    merged = od.merge_onchain(existing, new)
    assert merged["date"].tolist() == ["2026-06-01", "2026-06-02", "2026-06-03"]
    assert merged["mvrv"].tolist() == [1.0, 1.5, 1.6]


def test_merge_preserves_columns_new_lacks():
    existing = _frame({"date": ["2026-06-01"], "mvrv": [1.0], "fear_greed": [12.0]})
    new = _frame({"date": ["2026-06-01"], "mvrv": [1.2]})
    merged = od.merge_onchain(existing, new)
    assert merged.loc[0, "mvrv"] == 1.2
    assert merged.loc[0, "fear_greed"] == 12.0  # NA in new must not erase history


def test_merge_without_existing():
    new = _frame({"date": ["2026-06-03", "2026-06-01"], "mvrv": [1.6, 1.4]})
    merged = od.merge_onchain(None, new)
    assert merged["date"].tolist() == ["2026-06-01", "2026-06-03"]


def test_is_fresh():
    today = date(2026, 6, 9)
    assert od.is_fresh(_frame({"date": ["2026-06-09"], "mvrv": [1]}), today)
    assert od.is_fresh(_frame({"date": ["2026-06-08"], "mvrv": [1]}), today)
    assert not od.is_fresh(_frame({"date": ["2026-06-07"], "mvrv": [1]}), today)
    assert not od.is_fresh(None, today)
    assert not od.is_fresh(_frame({"date": [], "mvrv": []}), today)


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "get_data_dir", lambda: tmp_path)
    df = _frame({"date": ["2026-06-08", "2026-06-09"], "mvrv": [1.1, 1.2]})
    assert od.save_onchain_metrics(df)
    loaded = od.load_onchain_metrics()
    assert loaded is not None
    assert loaded["date"].tolist() == ["2026-06-08", "2026-06-09"]
    assert loaded["mvrv"].tolist() == [1.1, 1.2]
    assert list(loaded.columns) == od.ONCHAIN_COLUMNS


def test_update_skips_network_when_fresh(monkeypatch):
    fresh = _frame({"date": [date.today().isoformat()], "mvrv": [1.0]})
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: fresh)

    def explode(*a, **k):
        raise AssertionError("network must not be touched when fresh")

    monkeypatch.setattr(od, "fetch_all_onchain_series", explode)
    monkeypatch.setattr(od, "fetch_fear_and_greed_history", explode)
    out = od.update_onchain_metrics()
    assert out is fresh


def test_update_fetches_merges_saves(monkeypatch, tmp_path):
    monkeypatch.setattr(od, "get_data_dir", lambda: tmp_path)
    stale = _frame({"date": ["2026-01-01"], "mvrv": [1.0]})
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: stale)
    captured = {}

    def fake_fetch_all(startday=None):
        captured["startday"] = startday
        return {
            "mvrv": [("2026-06-09", 1.3)],
            "supply_loss_btc": [("2026-06-09", 9.0e6)],
            "supply_profit_btc": [("2026-06-09", 11.0e6)],
        }

    monkeypatch.setattr(od, "fetch_all_onchain_series", fake_fetch_all)
    monkeypatch.setattr(
        od, "fetch_fear_and_greed_history",
        lambda: [{"date": "2026-06-09", "value": 10}],
    )
    out = od.update_onchain_metrics()
    # overlap: startday = last cached date minus 7 days
    assert captured["startday"] == "2025-12-25"
    assert out["date"].tolist() == ["2026-01-01", "2026-06-09"]
    # derived: 9.0 / (9.0 + 11.0) = 45%
    assert out.loc[1, "supply_loss_pct"] == pytest.approx(45.0)
    assert out.loc[1, "fear_greed"] == 10
    # persisted
    assert (tmp_path / od.ONCHAIN_CSV).exists()


def test_update_returns_cache_when_all_fetches_fail(monkeypatch):
    stale = _frame({"date": ["2026-01-01"], "mvrv": [1.0]})
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: stale)
    monkeypatch.setattr(od, "fetch_all_onchain_series", lambda startday=None: {})
    monkeypatch.setattr(od, "fetch_fear_and_greed_history", lambda: None)
    assert od.update_onchain_metrics() is stale


def test_series_frame_derives_supply_loss_pct():
    series = {
        "supply_loss_btc": [("2026-06-08", 9_937_373.9)],
        "supply_profit_btc": [("2026-06-08", 10_100_084.58)],
    }
    frame = od._series_dict_to_frame(series, None)
    assert frame.loc[0, "supply_loss_pct"] == pytest.approx(49.594, abs=0.01)


def test_series_frame_supply_loss_pct_nan_when_profit_missing():
    frame = od._series_dict_to_frame(
        {"supply_loss_btc": [("2026-06-08", 9.9e6)]}, None
    )
    assert pd.isna(frame.loc[0, "supply_loss_pct"])


def test_normalize_realized_cap_change_billions_vs_usd():
    billions = pd.Series([-20.9, 30.0])
    usd = pd.Series([-2.09e10, 3.0e10])
    assert od._normalize_realized_cap_change(billions).tolist() == [-2.09e10, 3.0e10]
    assert od._normalize_realized_cap_change(usd).tolist() == [-2.09e10, 3.0e10]
