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


def _complete_frame(day: str) -> pd.DataFrame:
    return _frame(
        {
            "date": [day],
            "lth_realized_price": [48_000.0],
            "realized_price": [52_000.0],
            "sth_realized_price": [65_000.0],
            "mvrv": [1.2],
            "supply_loss_pct": [35.0],
            "realized_cap_change_30d_usd": [-1.5e9],
            "fear_greed": [20.0],
        }
    )


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
    assert od.is_fresh(_complete_frame("2026-06-09"), today)
    assert od.is_fresh(_complete_frame("2026-06-08"), today)
    assert not od.is_fresh(_complete_frame("2026-06-07"), today)
    assert not od.is_fresh(_frame({"date": ["2026-06-09"], "fear_greed": [10]}), today)
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
    fresh = _complete_frame(date.today().isoformat())
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

    def fake_fetch_all(plan=None, **kwargs):
        captured["plan"] = dict(plan)
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
    # overlap: each series restarts 7 days before its own last cached date;
    # series with no cached values are fetched in full
    assert captured["plan"]["mvrv"] == "2025-12-25"
    assert captured["plan"]["supply_loss_btc"] is None
    assert out["date"].tolist() == ["2026-01-01", "2026-06-09"]
    # derived: 9.0 / (9.0 + 11.0) = 45%
    assert out.loc[1, "supply_loss_pct"] == pytest.approx(45.0)
    assert out.loc[1, "fear_greed"] == 10
    # persisted
    assert (tmp_path / od.ONCHAIN_CSV).exists()


def test_update_returns_cache_when_all_fetches_fail(monkeypatch):
    stale = _frame({"date": ["2026-01-01"], "mvrv": [1.0]})
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: stale)
    monkeypatch.setattr(od, "fetch_all_onchain_series", lambda **kwargs: {})
    monkeypatch.setattr(od, "fetch_fear_and_greed_history", lambda: None)
    assert od.update_onchain_metrics() is stale


def test_update_returns_cache_when_onchain_fetch_fails_but_fng_succeeds(monkeypatch):
    stale = _complete_frame("2026-01-01")
    saved = []
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: stale)
    monkeypatch.setattr(od, "fetch_all_onchain_series", lambda **kwargs: {})
    monkeypatch.setattr(
        od,
        "fetch_fear_and_greed_history",
        lambda: [{"date": date.today().isoformat(), "value": 10}],
    )
    monkeypatch.setattr(od, "save_onchain_metrics", lambda df: saved.append(df))

    assert od.update_onchain_metrics() is stale
    assert saved == []


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


def test_load_dedupes_duplicate_dates(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "get_data_dir", lambda: tmp_path)
    csv = tmp_path / od.ONCHAIN_CSV
    csv.write_text(
        "date,mvrv\n2026-06-08,1.0\n2026-06-08,2.0\n2026-06-09,3.0\n"
    )
    loaded = od.load_onchain_metrics()
    assert loaded["date"].tolist() == ["2026-06-08", "2026-06-09"]
    assert loaded["mvrv"].tolist() == [2.0, 3.0]


def test_update_returns_merged_even_when_save_fails(monkeypatch):
    stale = _frame({"date": ["2026-01-01"], "mvrv": [1.0]})
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: stale)
    monkeypatch.setattr(
        od, "fetch_all_onchain_series",
        lambda **kwargs: {"mvrv": [("2026-06-09", 1.3)]},
    )
    monkeypatch.setattr(od, "fetch_fear_and_greed_history", lambda: None)
    monkeypatch.setattr(od, "save_onchain_metrics", lambda df: False)
    out = od.update_onchain_metrics()
    assert out["date"].tolist() == ["2026-01-01", "2026-06-09"]


def test_save_dedupes_duplicate_dates(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "get_data_dir", lambda: tmp_path)
    df = _frame(
        {"date": ["2026-06-08", "2026-06-08", "2026-06-09"], "mvrv": [1.0, 2.0, 3.0]}
    )
    assert od.save_onchain_metrics(df)
    text = (tmp_path / od.ONCHAIN_CSV).read_text()
    assert text.count("2026-06-08") == 1  # the duplicate date is collapsed on save
    loaded = od.load_onchain_metrics()
    assert loaded["date"].tolist() == ["2026-06-08", "2026-06-09"]
    assert loaded.loc[0, "mvrv"] == 2.0  # last write wins


def test_update_raises_in_strict_mode_when_fetch_fails(monkeypatch):
    stale = _frame({"date": ["2026-01-01"], "mvrv": [1.0]})
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: stale)
    monkeypatch.setattr(od, "fetch_all_onchain_series", lambda **kwargs: {})
    monkeypatch.setattr(od, "fetch_fear_and_greed_history", lambda: None)
    with pytest.raises(RuntimeError):
        od.update_onchain_metrics(strict=True)
    # non-strict still degrades gracefully to the cache
    assert od.update_onchain_metrics() is stale


def test_update_strict_no_raise_when_cache_is_fresh(monkeypatch):
    fresh = _complete_frame(date.today().isoformat())
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: fresh)

    def explode(*a, **k):
        raise AssertionError("network must not be touched when fresh")

    monkeypatch.setattr(od, "fetch_all_onchain_series", explode)
    monkeypatch.setattr(od, "fetch_fear_and_greed_history", explode)
    # fresh cache short-circuits before any fetch, so strict mode does not raise
    assert od.update_onchain_metrics(strict=True) is fresh


def test_update_strict_raises_when_partial_fetch_still_stale(monkeypatch, tmp_path):
    # fetch "succeeds" but only returns an OLD row -> merged is still not fresh.
    # This is the partial-degradation path that a naive "did we fetch anything?"
    # guard would miss; strict mode must still refuse.
    monkeypatch.setattr(od, "get_data_dir", lambda: tmp_path)
    stale = _frame({"date": ["2026-01-01"], "mvrv": [1.0]})
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: stale)
    monkeypatch.setattr(
        od, "fetch_all_onchain_series", lambda **kwargs: {"mvrv": [("2025-01-02", 2.0)]}
    )
    monkeypatch.setattr(od, "fetch_fear_and_greed_history", lambda: None)
    with pytest.raises(RuntimeError):
        od.update_onchain_metrics(strict=True)
    # non-strict still degrades gracefully (returns the merged stale frame)
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: stale)
    out = od.update_onchain_metrics()
    assert out is not None and not out.empty


def test_update_strict_succeeds_when_fetch_brings_fresh_data(monkeypatch, tmp_path):
    # strict + a successful fetch that brings a complete current row -> no raise.
    monkeypatch.setattr(od, "get_data_dir", lambda: tmp_path)
    stale = _frame({"date": ["2026-01-01"], "mvrv": [1.0]})
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: stale)
    today = date.today().isoformat()
    monkeypatch.setattr(
        od,
        "fetch_all_onchain_series",
        lambda **kwargs: {
            "lth_realized_price": [(today, 48_000.0)],
            "realized_price": [(today, 52_000.0)],
            "sth_realized_price": [(today, 65_000.0)],
            "mvrv": [(today, 1.2)],
            "supply_loss_btc": [(today, 9.0e6)],
            "supply_profit_btc": [(today, 11.0e6)],
            "realized_cap_change_30d_usd": [(today, -1.5e9)],
        },
    )
    monkeypatch.setattr(
        od, "fetch_fear_and_greed_history", lambda: [{"date": today, "value": 20}]
    )
    out = od.update_onchain_metrics(strict=True)  # must NOT raise
    assert out["date"].tolist()[-1] == today


def test_update_with_garbage_dates_falls_back_to_full_fetch(monkeypatch):
    bad = _frame({"date": ["not-a-date"], "mvrv": [1.0]})
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: bad)
    captured = {}

    def fake_fetch_all(plan=None, **kwargs):
        captured["plan"] = dict(plan)
        return {"mvrv": [("2026-06-09", 1.3)]}

    monkeypatch.setattr(od, "fetch_all_onchain_series", fake_fetch_all)
    monkeypatch.setattr(od, "fetch_fear_and_greed_history", lambda: None)
    monkeypatch.setattr(od, "save_onchain_metrics", lambda df: True)
    od.update_onchain_metrics()
    assert captured["plan"]["mvrv"] is None


def _history(last_by_column: dict, start: str = "2026-06-20", end: str = "2026-10-01") -> pd.DataFrame:
    """Daily rows; each column is filled up to its own last date."""
    days = pd.date_range(start, end, freq="D").strftime("%Y-%m-%d")
    rows = {"date": list(days)}
    for col in od.REQUIRED_SIGNAL_COLUMNS:
        last = last_by_column.get(col, end)
        rows[col] = [1.0 if d <= last else None for d in days]
    return _frame(rows)


def test_plan_fetches_only_stale_metrics_oldest_first():
    existing = _history(
        {
            "supply_loss_pct": "2026-07-02",
            "realized_cap_change_30d_usd": "2026-07-02",
            "mvrv": "2026-09-24",
        }
    )
    plan = od.plan_onchain_fetches(existing, today=date(2026, 10, 2))
    assert plan == [
        ("supply_loss_btc", "2026-06-25"),
        ("supply_profit_btc", "2026-06-25"),
        ("realized_cap_change_30d_usd", "2026-06-25"),
        ("mvrv", "2026-09-17"),
    ]


def test_plan_fetches_everything_without_cache():
    plan = od.plan_onchain_fetches(None, today=date(2026, 10, 2))
    assert plan == [(key, None) for key in od.ONCHAIN_ENDPOINTS]


def test_plan_is_empty_when_every_metric_is_fresh():
    existing = _history({}, end="2026-10-01")
    assert od.plan_onchain_fetches(existing, today=date(2026, 10, 2)) == []


def test_update_fetches_the_stale_plan(monkeypatch):
    stale = _history({"supply_loss_pct": "2026-07-02"})
    monkeypatch.setattr(od, "load_onchain_metrics", lambda: stale)
    monkeypatch.setattr(od, "save_onchain_metrics", lambda df: True)
    monkeypatch.setattr(od, "fetch_fear_and_greed_history", lambda: [])
    seen = {}

    def fake_fetch_all(plan=None, **kwargs):
        seen["plan"] = plan
        return {}

    monkeypatch.setattr(od, "fetch_all_onchain_series", fake_fetch_all)
    od.update_onchain_metrics()
    assert [metric for metric, _ in seen["plan"]] == ["supply_loss_btc", "supply_profit_btc"]
