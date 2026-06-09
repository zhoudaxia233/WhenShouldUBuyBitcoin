# On-Chain Bottom Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five on-chain signals scored 0-20 each (holder cost basis, MVRV deviation, supply in loss, 30d realized-cap flow, Fear & Greed) summing to a 0-100 composite with zone classification, a backtest (trigger segments + accuracy matrix), a prerendered `docs/charts/bottom_signals.html` dashboard, an `index.html` summary card, and a daily-report section — fed by free APIs within strict rate budgets.

**Architecture:** A new provider (`bitcoin_data_com.py`) fetches seven series from the free bitcoin-data.com API (10 req/h, 15/day, last-4-years window; supply-loss/profit arrive as absolute BTC and are combined into an exact in-loss percentage); `onchain_data.py` accumulates them plus alternative.me Fear & Greed history into `docs/data/onchain_metrics.csv` with a freshness guard; `bottom_signals.py` holds pure scoring/backtest functions; `bottom_signals_page.py` renders a self-contained Jinja2 page plus `bottom_signals_info.json`; `main.py` wires it into the daily pipeline. Spec: `docs/superpowers/specs/2026-06-09-onchain-bottom-signals-design.md`.

**Tech Stack:** Python (pandas, numpy, requests, jinja2 — all existing deps), plotly.js via CDN on the new page only, pytest, vanilla JS in `docs/index.html`.

**Conventions:** TDD per AGENTS.md. Run tests with `poetry run pytest tests/<file> -v`. All file writes to `docs/` are atomic (temp file + replace). Print-style logging with `✓` / `⚠` / `✗` prefixes matches existing modules.

**Rate-budget warning:** bitcoin-data.com free tier = 10 requests/hour, 15/day per IP. Task 1 spends 6, the first real pipeline run after Task 9 spends 0 (freshness guard) — do not re-run the capture script casually. If any call returns HTTP 429, stop and resume the task after an hour.

---

### Task 0: Branch

- [ ] **Step 0.1:** Create the feature branch:

```bash
git checkout -b feat/onchain-bottom-signals
```

---

### Task 1: Capture real API fixtures

The exact JSON field names of bitcoin-data.com responses are undocumented; we pin them with recorded fixtures, which also double as the seed for the initial CSV backfill (Task 9), so capture the **full free window** (no `startday`).

**Files:**
- Create: `scripts/capture_bitcoin_data_fixtures.py`
- Create (generated): `tests/fixtures/bitcoin_data_com/*.json` (6 files)
- Create (generated): `tests/fixtures/alternative_me_history.json`

- [ ] **Step 1.1: Write the capture script**

```python
#!/usr/bin/env python3
"""One-shot capture of real API responses as committed test fixtures.

bitcoin-data.com free tier allows 15 requests/day; this script uses up to 6
(one per endpoint) and is resumable: endpoints whose fixture file already
exists are skipped, so a rate-limited run can be finished the next day.
"""
import json
import time
from pathlib import Path

import requests

BASE_URL = "https://api.bitcoin-data.com"
ENDPOINTS = {
    "lth_realized_price": "/v1/lth-realized-price",
    "realized_price": "/v1/realized-price",
    "sth_realized_price": "/v1/sth-realized-price",
    "mvrv": "/v1/mvrv",
    "supply_loss_btc": "/v1/supply-loss",
    "supply_profit_btc": "/v1/supply-profit",
    "realized_cap_change_30d_usd": "/v1/realized-cap-change-30d",
}
FIXTURE_DIR = Path("tests/fixtures/bitcoin_data_com")


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    first = True
    for key, path in ENDPOINTS.items():
        out = FIXTURE_DIR / f"{key}.json"
        if out.exists():
            print(f"skip {key} (fixture exists)")
            continue
        if not first:
            time.sleep(7)
        first = False
        r = requests.get(f"{BASE_URL}{path}", timeout=60)
        r.raise_for_status()
        rows = r.json()
        out.write_text(json.dumps(rows, indent=1))
        if rows:
            print(
                f"✓ {key}: {len(rows)} rows, fields={sorted(rows[0])}, "
                f"first={rows[0]}, last={rows[-1]}"
            )
        else:
            print(f"⚠ {key}: EMPTY response — investigate before proceeding")

    fng_out = Path("tests/fixtures/alternative_me_history.json")
    if not fng_out.exists():
        r = requests.get("https://api.alternative.me/fng/?limit=10", timeout=30)
        r.raise_for_status()
        fng_out.write_text(json.dumps(r.json(), indent=1))
        print(f"✓ fear&greed fixture: {fng_out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 1.2: Run it**

Run: `poetry run python scripts/capture_bitcoin_data_fixtures.py`
Expected: six `✓` lines each reporting ~1400+ rows (4-year window) with their field names, plus the F&G fixture. **Record the printed field names and the first/last dates** — Task 2's parser is generic, but verify each row has a date field (`d`/`theDay`/`day`) plus one numeric metric field. If a response is empty or truncated (row count far below ~1400, e.g. a pagination cap), check whether `?size=5000` as a query param returns the full window before burning more requests, and note what worked in the commit message.

- [ ] **Step 1.3: Sanity-check values against the reference site**

Inspect the last rows: `sth_realized_price` ≈ $74-75k, `realized_price` ≈ $53-54k, `lth_realized_price` ≈ $48-49k, `mvrv` ≈ 1.1-1.2 (these matched a third-party dashboard on 2026-06-08). Note whether `supply_loss_pct` arrives as a fraction (≈0.2) or percent (≈20), and whether `realized_cap_change_30d_usd` is in USD (≈ -2e10) or billions (≈ -20) — Task 4's normalizers depend on knowing both representations exist.

- [ ] **Step 1.4: Commit**

```bash
git add scripts/capture_bitcoin_data_fixtures.py tests/fixtures/
git commit -m "chore: capture bitcoin-data.com + alternative.me API fixtures"
```

---

### Task 2: bitcoin-data.com provider

**Files:**
- Create: `src/whenshouldubuybitcoin/providers/bitcoin_data_com.py`
- Test: `tests/test_bitcoin_data_com.py`

- [ ] **Step 2.1: Write the failing tests**

```python
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
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_bitcoin_data_com.py -v`
Expected: FAIL with `ModuleNotFoundError: ... bitcoin_data_com`

- [ ] **Step 2.3: Implement the provider**

```python
"""
Provider for free Bitcoin on-chain metrics from bitcoin-data.com (BGeometrics).

Free tier (no token): 10 requests/hour, 15 requests/day, history limited to
the most recent ~4 years. An optional BGEOMETRICS_TOKEN env var is sent as a
Bearer token for paid tiers. Responses are JSON arrays of per-day objects
like {"d": "2024-01-01", "unixTs": "...", "<metricField>": "1.23"} where the
metric field name varies per endpoint.
"""

import os
import time
from typing import Optional

import requests

BASE_URL = "https://api.bitcoin-data.com"

# Free tier allows 10 requests/hour; spacing keeps a 6-call run under it.
REQUEST_SPACING_SECONDS = 7.0

# CSV column name -> API endpoint path.
ONCHAIN_ENDPOINTS = {
    "lth_realized_price": "/v1/lth-realized-price",
    "realized_price": "/v1/realized-price",
    "sth_realized_price": "/v1/sth-realized-price",
    "mvrv": "/v1/mvrv",
    "supply_loss_btc": "/v1/supply-loss",
    "supply_profit_btc": "/v1/supply-profit",
    "realized_cap_change_30d_usd": "/v1/realized-cap-change-30d",
}

# Non-value fields seen in API rows; the remaining parseable field is the metric.
_META_FIELDS = {"d", "theDay", "day", "unixTs", "unixTimestamp"}


def _auth_headers() -> dict:
    token = os.environ.get("BGEOMETRICS_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def parse_series(rows) -> list[tuple[str, float]]:
    """Parse a bitcoin-data.com JSON array into [(YYYY-MM-DD, value), ...].

    Rows with a missing date or no numeric metric field are skipped. Output
    is sorted by date ascending.
    """
    out: list[tuple[str, float]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        day = row.get("d") or row.get("theDay") or row.get("day")
        if not day:
            continue
        value = None
        for key, raw in row.items():
            if key in _META_FIELDS:
                continue
            try:
                value = float(raw)
                break
            except (TypeError, ValueError):
                continue
        if value is not None:
            out.append((str(day)[:10], value))
    out.sort(key=lambda pair: pair[0])
    return out


def fetch_series(
    metric_key: str,
    startday: Optional[str] = None,
    max_retries: int = 3,
) -> Optional[list[tuple[str, float]]]:
    """Fetch one metric series; returns None when all retries fail."""
    url = f"{BASE_URL}{ONCHAIN_ENDPOINTS[metric_key]}"
    params = {"startday": startday} if startday else {}

    for attempt in range(max_retries):
        try:
            response = requests.get(
                url, params=params, headers=_auth_headers(), timeout=30
            )
            response.raise_for_status()
            return parse_series(response.json())
        except Exception as e:
            wait = 10 * (2**attempt)
            if attempt < max_retries - 1:
                print(
                    f"⚠ bitcoin-data.com {metric_key} attempt "
                    f"{attempt + 1}/{max_retries} failed: {e}. Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                print(
                    f"✗ bitcoin-data.com {metric_key} failed after "
                    f"{max_retries} attempts: {e}"
                )
    return None


def fetch_all_onchain_series(
    startday: Optional[str] = None,
) -> dict[str, list[tuple[str, float]]]:
    """Fetch every on-chain series sequentially with free-tier spacing.

    Returns only the series that succeeded (possibly none); callers degrade
    gracefully on partial data.
    """
    results: dict[str, list[tuple[str, float]]] = {}
    for i, metric_key in enumerate(ONCHAIN_ENDPOINTS):
        if i:
            time.sleep(REQUEST_SPACING_SECONDS)
        series = fetch_series(metric_key, startday=startday)
        if series is not None:
            results[metric_key] = series
            print(f"✓ bitcoin-data.com {metric_key}: {len(series)} rows")
    return results
```

If Step 1.2 revealed a date field name other than `d`/`theDay`/`day`, add it to `_META_FIELDS` handling (date lookup chain) now.

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_bitcoin_data_com.py -v`
Expected: all PASS

- [ ] **Step 2.5: Commit**

```bash
git add src/whenshouldubuybitcoin/providers/bitcoin_data_com.py tests/test_bitcoin_data_com.py
git commit -m "feat: add bitcoin-data.com on-chain metrics provider"
```

---

### Task 3: Fear & Greed history fetch

**Files:**
- Modify: `src/whenshouldubuybitcoin/providers/alternative_me.py` (append function)
- Test: `tests/test_alternative_me.py` (create)

- [ ] **Step 3.1: Write the failing tests**

```python
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
```

Note: the fixture's `timestamp` values may be unix-seconds strings (`"1717891200"`) or `YYYY-MM-DD` strings depending on capture; the implementation below handles both.

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_alternative_me.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'fetch_fear_and_greed_history'`

- [ ] **Step 3.3: Append the implementation to `alternative_me.py`**

```python
def fetch_fear_and_greed_history() -> Optional[list]:
    """
    Fetch the full daily Fear & Greed history (index inception: 2018-02-01).

    Returns:
        List of {"date": "YYYY-MM-DD", "value": int} sorted by date ascending,
        or None if fetching fails or yields no rows.
    """
    url = "https://api.alternative.me/fng/?limit=0"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        rows = []
        for item in data.get("data", []):
            try:
                ts = str(item["timestamp"])
                if "-" in ts:
                    day = ts[:10]
                else:
                    day = datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
                rows.append({"date": day, "value": int(item["value"])})
            except (KeyError, TypeError, ValueError):
                continue

        rows.sort(key=lambda r: r["date"])
        return rows or None

    except Exception as e:
        print(f"⚠ Warning: Failed to fetch Fear & Greed history: {e}")

    return None
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_alternative_me.py -v`
Expected: all PASS

- [ ] **Step 3.5: Commit**

```bash
git add src/whenshouldubuybitcoin/providers/alternative_me.py tests/test_alternative_me.py
git commit -m "feat: add Fear & Greed full-history fetch"
```

---

### Task 4: On-chain dataset orchestration (`onchain_data.py`)

**Files:**
- Create: `src/whenshouldubuybitcoin/onchain_data.py`
- Test: `tests/test_onchain_data.py`

- [ ] **Step 4.1: Write the failing tests**

```python
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
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_onchain_data.py -v`
Expected: FAIL with `ModuleNotFoundError: ... onchain_data`

- [ ] **Step 4.3: Implement `onchain_data.py`**

```python
"""
Orchestration for the on-chain bottom-signal dataset.

Fetches free on-chain series (bitcoin-data.com) plus Fear & Greed history
(alternative.me), accumulates them in docs/data/onchain_metrics.csv (history
never shrinks even though the free API only serves the last ~4 years), and
guards the free-tier request budget with a freshness check.
"""

import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from .persistence import get_data_dir
from .providers.alternative_me import fetch_fear_and_greed_history
from .providers.bitcoin_data_com import fetch_all_onchain_series

ONCHAIN_CSV = "onchain_metrics.csv"

ONCHAIN_COLUMNS = [
    "date",
    "lth_realized_price",
    "realized_price",
    "sth_realized_price",
    "mvrv",
    "supply_loss_pct",
    "realized_cap_change_30d_usd",
    "fear_greed",
]

# Refetch this many days before the last cached date to absorb upstream revisions.
REFETCH_OVERLAP_DAYS = 7


def _normalize_realized_cap_change(series: pd.Series) -> pd.Series:
    """Store the 30d realized-cap change in USD whether the API sends USD or billions."""
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().empty:
        return s
    return s * 1e9 if s.abs().max() < 1e6 else s


def load_onchain_metrics() -> Optional[pd.DataFrame]:
    """Load the accumulated dataset; None when absent or unreadable."""
    filepath = get_data_dir() / ONCHAIN_CSV
    if not filepath.exists():
        print(f"No existing on-chain data file at {filepath}")
        return None
    try:
        df = pd.read_csv(filepath)
        if "date" not in df.columns or df.empty:
            return None
        df["date"] = df["date"].astype(str).str[:10]
        for col in ONCHAIN_COLUMNS:
            if col == "date":
                continue
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
        df = df[ONCHAIN_COLUMNS].sort_values("date").reset_index(drop=True)
        print(f"✓ Loaded {len(df)} on-chain rows from {filepath}")
        return df
    except Exception as e:
        print(f"✗ Error loading {filepath}: {e}")
        return None


def save_onchain_metrics(df: pd.DataFrame) -> bool:
    """Atomically persist the dataset sorted by date."""
    filepath = get_data_dir() / ONCHAIN_CSV
    try:
        out = df[ONCHAIN_COLUMNS].sort_values("date").reset_index(drop=True)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=filepath.parent,
                prefix=f".{filepath.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                out.to_csv(tmp, index=False)
                tmp_path = Path(tmp.name)
            tmp_path.replace(filepath)
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        print(f"✓ Saved {len(out)} on-chain rows to {filepath}")
        return True
    except Exception as e:
        print(f"✗ Error saving {filepath}: {e}")
        return False


def merge_onchain(
    existing: Optional[pd.DataFrame], new: pd.DataFrame
) -> pd.DataFrame:
    """Outer-merge on date; new values win where present, history is never dropped."""
    new = new[ONCHAIN_COLUMNS].sort_values("date")
    if existing is None or existing.empty:
        return new.reset_index(drop=True)
    merged = (
        new.set_index("date")
        .combine_first(existing[ONCHAIN_COLUMNS].set_index("date"))
        .reset_index()
    )
    return merged[ONCHAIN_COLUMNS].sort_values("date").reset_index(drop=True)


def is_fresh(df: Optional[pd.DataFrame], today: Optional[date] = None) -> bool:
    """True when the newest cached row is from today or yesterday (UTC daily lag)."""
    if df is None or df.empty:
        return False
    today = today or date.today()
    try:
        last = date.fromisoformat(str(df["date"].max())[:10])
    except ValueError:
        return False
    return last >= today - timedelta(days=1)


def _series_dict_to_frame(series_by_metric: dict, fng_rows) -> pd.DataFrame:
    """Pivot fetched series into one wide normalized frame keyed by date."""
    frames = []
    for metric, series in (series_by_metric or {}).items():
        if not series:
            continue
        frame = pd.DataFrame(series, columns=["date", metric]).set_index("date")
        frames.append(frame[~frame.index.duplicated(keep="last")])
    if fng_rows:
        fng = pd.DataFrame(fng_rows).rename(columns={"value": "fear_greed"})
        fng = fng.set_index("date")
        frames.append(fng[~fng.index.duplicated(keep="last")])
    if not frames:
        return pd.DataFrame(columns=ONCHAIN_COLUMNS)

    wide = pd.concat(frames, axis=1, join="outer").reset_index()
    wide = wide.rename(columns={"index": "date"})
    for col in ("supply_loss_btc", "supply_profit_btc", *ONCHAIN_COLUMNS):
        if col not in wide.columns:
            wide[col] = pd.NA

    # The API reports absolute BTC in loss/profit; their sum is the provider's
    # circulating-supply universe, so the ratio is an exact in-loss share.
    loss = pd.to_numeric(wide["supply_loss_btc"], errors="coerce")
    profit = pd.to_numeric(wide["supply_profit_btc"], errors="coerce")
    total = loss + profit
    wide["supply_loss_pct"] = (100.0 * loss / total).where(total > 0)

    wide["realized_cap_change_30d_usd"] = _normalize_realized_cap_change(
        wide["realized_cap_change_30d_usd"]
    )
    return wide[ONCHAIN_COLUMNS]


def update_onchain_metrics(force: bool = False) -> Optional[pd.DataFrame]:
    """Load, freshen (within free-tier limits), persist, and return the dataset.

    Network is skipped entirely when the cache already holds today's or
    yesterday's row, so repeated local runs cannot burn the request budget.
    """
    existing = load_onchain_metrics()
    if not force and is_fresh(existing):
        print("✓ On-chain metrics are fresh; skipping API calls (free-tier budget guard)")
        return existing

    startday = None
    if existing is not None and not existing.empty:
        last = date.fromisoformat(str(existing["date"].max())[:10])
        startday = (last - timedelta(days=REFETCH_OVERLAP_DAYS)).isoformat()

    series_by_metric = fetch_all_onchain_series(startday=startday)
    fng_rows = fetch_fear_and_greed_history()
    new = _series_dict_to_frame(series_by_metric, fng_rows)

    if new.empty:
        print("⚠ No new on-chain data fetched; using cached dataset")
        return existing

    merged = merge_onchain(existing, new)
    save_onchain_metrics(merged)
    return merged
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_onchain_data.py -v`
Expected: all PASS. (Captured reality from Task 1: `/v1/supply-loss` and `/v1/supply-profit` return absolute BTC — `supplyLossBtc` ≈ 9.94M, `supplyProfitBtc` ≈ 10.10M on 2026-06-08, summing to the ~20.04M circulating supply — and `realizedCapChange30d` is plain USD.)

- [ ] **Step 4.5: Commit**

```bash
git add src/whenshouldubuybitcoin/onchain_data.py tests/test_onchain_data.py
git commit -m "feat: add on-chain dataset orchestration with freshness guard"
```

---

### Task 5: Scoring (`bottom_signals.py`, part 1)

**Files:**
- Create: `src/whenshouldubuybitcoin/bottom_signals.py`
- Test: `tests/test_bottom_signals.py`

- [ ] **Step 5.1: Write the failing tests**

```python
"""Tests for on-chain bottom-signal scoring and backtest."""
import numpy as np
import pandas as pd
import pytest

from whenshouldubuybitcoin import bottom_signals as bs


# ---------- S1: holder cost ----------

def test_s1_anchor_points():
    lth, avg, sth = 48_000.0, 53_000.0, 74_000.0
    assert bs.score_s1_holder_cost(sth, lth, avg, sth) == pytest.approx(5.0)
    assert bs.score_s1_holder_cost(avg, lth, avg, sth) == pytest.approx(10.0)
    assert bs.score_s1_holder_cost(lth, lth, avg, sth) == pytest.approx(15.0)
    assert bs.score_s1_holder_cost(0.8 * lth, lth, avg, sth) == pytest.approx(20.0)
    assert bs.score_s1_holder_cost(1.2 * sth, lth, avg, sth) == pytest.approx(0.0)


def test_s1_clamps_outside_anchors():
    lth, avg, sth = 48_000.0, 53_000.0, 74_000.0
    assert bs.score_s1_holder_cost(200_000.0, lth, avg, sth) == pytest.approx(0.0)
    assert bs.score_s1_holder_cost(10_000.0, lth, avg, sth) == pytest.approx(20.0)


def test_s1_monotonic_decreasing_in_price():
    lth, avg, sth = 48_000.0, 53_000.0, 74_000.0
    prices = np.linspace(30_000, 100_000, 50)
    scores = [bs.score_s1_holder_cost(p, lth, avg, sth) for p in prices]
    assert all(a >= b for a, b in zip(scores, scores[1:]))


def test_s1_crossed_lines_do_not_crash():
    # mid-bear regime: STH cost can fall below the average cost line
    score = bs.score_s1_holder_cost(50_000.0, 48_000.0, 60_000.0, 55_000.0)
    assert 0.0 <= score <= 20.0


def test_s1_missing_inputs():
    assert bs.score_s1_holder_cost(None, 1.0, 2.0, 3.0) is None
    assert bs.score_s1_holder_cost(50_000.0, float("nan"), 2.0, 3.0) is None
    assert bs.score_s1_holder_cost(50_000.0, -1.0, 2.0, 3.0) is None


# ---------- sigma helpers / S2 / S3 ----------

def _bimodal_series() -> pd.Series:
    # 100 ones and 100 threes: mean 2.0, population std 1.0
    return pd.Series([1.0] * 100 + [3.0] * 100)


def test_full_sample_deviation():
    d = bs.full_sample_deviation(_bimodal_series())
    assert d.iloc[0] == pytest.approx(-1.0)
    assert d.iloc[-1] == pytest.approx(1.0)


def test_full_sample_deviation_needs_min_observations():
    short = pd.Series([1.0] * 50 + [3.0] * 50)  # 100 < MIN_OBSERVATIONS
    assert bs.full_sample_deviation(short).isna().all()


def test_s2_scores():
    s = bs.score_s2_mvrv(_bimodal_series())
    # d=-1: between -1.5 (20) and 0 (8) -> 8 + (1/1.5)*12 = 16
    assert s.iloc[0] == pytest.approx(16.0)
    # d=+1: between 0 (8) and +2 (0) -> 8 - (1/2)*8 = 4
    assert s.iloc[-1] == pytest.approx(4.0)


def test_s3_scores():
    s = bs.score_s3_supply_loss(_bimodal_series())
    # d=-1 -> 0
    assert s.iloc[0] == pytest.approx(0.0)
    # d=+1: between +0.5 (10) and +2 (20) -> 10 + (0.5/1.5)*10
    assert s.iloc[-1] == pytest.approx(10.0 + 10.0 / 3.0)


# ---------- S4 ----------

def test_s4_percentile_scores():
    s = bs.score_s4_capital_flow(pd.Series(np.arange(1.0, 201.0)))
    assert s.iloc[0] == pytest.approx(19.9)  # deepest outflow -> highest score
    assert s.iloc[-1] == pytest.approx(0.0)  # biggest inflow -> 0


def test_s4_needs_min_observations():
    assert bs.score_s4_capital_flow(pd.Series(np.arange(50.0))).isna().all()


# ---------- S5 ----------

def test_s5_anchor_points():
    assert bs.score_s5_fear_greed(10) == pytest.approx(20.0)
    assert bs.score_s5_fear_greed(0) == pytest.approx(20.0)
    assert bs.score_s5_fear_greed(75) == pytest.approx(0.0)
    assert bs.score_s5_fear_greed(100) == pytest.approx(0.0)
    assert bs.score_s5_fear_greed(42.5) == pytest.approx(10.0)
    assert bs.score_s5_fear_greed(None) is None


# ---------- composite ----------

def _scores_frame(n: int = 200) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    onchain = pd.DataFrame(
        {
            "date": dates,
            "lth_realized_price": 48_000.0,
            "realized_price": 53_000.0,
            "sth_realized_price": 74_000.0,
            "mvrv": [1.0] * (n // 2) + [3.0] * (n - n // 2),
            "supply_loss_pct": [10.0] * (n // 2) + [30.0] * (n - n // 2),
            "realized_cap_change_30d_usd": np.linspace(-4e10, 4e10, n),
            "fear_greed": 10.0,
        }
    )
    prices = pd.DataFrame({"date": dates, "close_price": 60_000.0})
    return bs.compute_bottom_signal_scores(onchain, prices)


def test_compute_scores_has_all_columns_and_composite():
    df = _scores_frame()
    for col in ["s1", "s2", "s3", "s4", "s5", "composite", "zone", "zone_color",
                "s2_dev", "s3_dev", "s4_pctile"]:
        assert col in df.columns
    last = df.iloc[-1]
    expected = last["s1"] + last["s2"] + last["s3"] + last["s4"] + last["s5"]
    assert last["composite"] == pytest.approx(expected)
    assert last["zone"] in {z[2] for z in bs.ZONES}
    assert last["zone_color"] in {z[3] for z in bs.ZONES}


def test_compute_scores_composite_null_when_any_signal_missing():
    dates = pd.date_range("2024-01-01", periods=200).strftime("%Y-%m-%d")
    onchain = pd.DataFrame(
        {
            "date": dates,
            "lth_realized_price": 48_000.0,
            "realized_price": 53_000.0,
            "sth_realized_price": 74_000.0,
            "mvrv": pd.NA,  # S2 unavailable
            "supply_loss_pct": 20.0,
            "realized_cap_change_30d_usd": -1e10,
            "fear_greed": 10.0,
        }
    )
    prices = pd.DataFrame({"date": dates, "close_price": 60_000.0})
    df = bs.compute_bottom_signal_scores(onchain, prices)
    assert df["composite"].isna().all()


def test_zone_for():
    assert bs.zone_for(0)[0] == "Watch"
    assert bs.zone_for(59.9)[0] == "Watch"
    assert bs.zone_for(60)[0] == "Mildly Undervalued"
    assert bs.zone_for(70)[0] == "Undervalued"
    assert bs.zone_for(80)[0] == "Extremely Undervalued"
    assert bs.zone_for(100)[0] == "Extremely Undervalued"
    assert bs.zone_for(100.01)[0] == "Extremely Undervalued"
    assert bs.zone_for(None) is None


def test_compute_scores_accepts_datetime_dates():
    n = 200
    dates = pd.date_range("2024-01-01", periods=n)  # datetime64, not str
    onchain = pd.DataFrame(
        {
            "date": dates,
            "lth_realized_price": 48_000.0,
            "realized_price": 53_000.0,
            "sth_realized_price": 74_000.0,
            "mvrv": 1.5,
            "supply_loss_pct": 20.0,
            "realized_cap_change_30d_usd": -1e10,
            "fear_greed": 10.0,
        }
    )
    prices = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "close_price": 60_000.0})
    df = bs.compute_bottom_signal_scores(onchain, prices)
    assert len(df) == n
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_bottom_signals.py -v`
Expected: FAIL with `ModuleNotFoundError: ... bottom_signals`

- [ ] **Step 5.3: Implement scoring**

```python
"""
On-chain bottom-signal scoring and backtest.

Five signals scored 0-20 each sum to a 0-100 composite:
  S1 price vs holder cost-basis lines, S2 MVRV sigma deviation,
  S3 supply-in-loss sigma deviation, S4 30d realized-cap flow percentile,
  S5 Fear & Greed.
Sigma/percentile statistics are computed once over the full available sample
(not expanding windows); the dashboard page states the look-ahead caveat.
"""

import math
from typing import Optional

import numpy as np
import pandas as pd

MIN_OBSERVATIONS = 180

# (lower bound inclusive, upper bound exclusive, label, color)
ZONES = [
    (0.0, 60.0, "Watch", "#6e6e73"),
    (60.0, 70.0, "Mildly Undervalued", "#10b981"),
    (70.0, 80.0, "Undervalued", "#f59e0b"),
    (80.0, math.inf, "Extremely Undervalued", "#ef4444"),
]

ZONE_ADVICE = {
    "Watch": "Not cheap yet — keep watching.",
    "Mildly Undervalued": "Getting interesting — consider scaling in slowly.",
    "Undervalued": "Undervalued — historically a productive DCA zone.",
    "Extremely Undervalued": "Extremely undervalued — historically rare readings.",
}

# (date, daily-close price) of cycle bottoms inside the free-tier data window.
CYCLE_BOTTOMS = [
    ("2022-11-21", 15797.53),
    ("2024-09-06", 53914.82),
]

# A trigger segment "hits" when its minimum price is within this multiple
# of its assigned cycle bottom.
BOTTOM_HIT_MULTIPLE = 1.3

THRESHOLDS = (60, 70, 80)
DURATIONS = (1, 3, 7)
# CYCLE_BOTTOMS / BOTTOM_HIT_MULTIPLE / THRESHOLDS / DURATIONS are consumed by the backtest functions (added in a subsequent commit).

# Sigma-deviation anchor curves: (sigma anchors, score anchors).
S2_SIGMA_ANCHORS = ([-1.5, 0.0, 2.0], [20.0, 8.0, 0.0])
S3_SIGMA_ANCHORS = ([-1.0, 0.0, 0.5, 2.0], [0.0, 6.0, 10.0, 20.0])


def zone_for(composite) -> Optional[tuple[str, str]]:
    """Return (label, color) for a composite score, or None for missing input."""
    if composite is None or pd.isna(composite):
        return None
    for low, high, label, color in ZONES:
        if low <= composite < high:
            return label, color
    return None


def _interp(x: float, xs, ys) -> float:
    """Piecewise-linear interpolation clamped to the anchor range."""
    return float(np.interp(x, xs, ys))


def score_s1_holder_cost(price, lth, avg, sth) -> Optional[float]:
    """Price vs holder cost-basis lines, interpolated in log space.

    Anchors: >= 1.2*STH -> 0; STH -> 5; AVG -> 10; LTH -> 15; <= 0.8*LTH -> 20.
    """
    vals = [price, lth, avg, sth]
    if any(v is None or pd.isna(v) or v <= 0 for v in vals):
        return None
    raw = np.log([0.8 * lth, lth, avg, sth, 1.2 * sth])
    cum = np.maximum.accumulate(raw)
    # Nudge only positions that were flattened (ties after cummax), preserving
    # exact boundary anchors where no crossing occurred.
    nudge = np.where(cum == raw, 0.0, np.arange(5) * 1e-9)
    log_xs = cum + nudge
    ys = [20.0, 15.0, 10.0, 5.0, 0.0]
    return _interp(np.log(price), log_xs, ys)


def full_sample_deviation(series: pd.Series) -> pd.Series:
    """Deviation from the full-sample mean in population-std units.

    All-NaN result when the sample is shorter than MIN_OBSERVATIONS or flat.
    """
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if len(valid) < MIN_OBSERVATIONS or valid.std(ddof=0) == 0:
        return pd.Series(np.nan, index=s.index)
    return (s - valid.mean()) / valid.std(ddof=0)


def _sigma_to_score(dev: pd.Series, anchors_sigma, anchors_score) -> pd.Series:
    return dev.apply(
        lambda v: np.nan if pd.isna(v) else _interp(v, anchors_sigma, anchors_score)
    )


def score_s2_mvrv(series: pd.Series) -> pd.Series:
    """MVRV deviation: +2 sigma -> 0, 0 -> 8, -1.5 sigma -> 20."""
    return _sigma_to_score(full_sample_deviation(series), *S2_SIGMA_ANCHORS)


def score_s3_supply_loss(series: pd.Series) -> pd.Series:
    """Supply-in-loss deviation: -1 sigma -> 0, 0 -> 6, +0.5 -> 10, +2 -> 20."""
    return _sigma_to_score(full_sample_deviation(series), *S3_SIGMA_ANCHORS)


def score_s4_capital_flow(series: pd.Series) -> pd.Series:
    """20 x (1 - full-sample percentile rank) of the 30d realized-cap change."""
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() < MIN_OBSERVATIONS:
        return pd.Series(np.nan, index=s.index)
    return 20.0 * (1.0 - s.rank(pct=True))


def score_s5_fear_greed(value) -> Optional[float]:
    """Fear & Greed: <= 10 -> 20; >= 75 -> 0; linear between."""
    if value is None or pd.isna(value):
        return None
    return _interp(float(value), [10.0, 75.0], [20.0, 0.0])


def compute_bottom_signal_scores(
    onchain_df: pd.DataFrame, price_df: pd.DataFrame
) -> pd.DataFrame:
    """Join on-chain data with daily closes and score S1-S5 plus the composite.

    price_df needs `date` and `close_price`. Returns one row per on-chain date
    that has a close price, sorted ascending, with raw inputs, s1..s5, the
    diagnostic columns (s2_dev, s3_dev, s4_pctile), composite, zone, zone_color.
    """
    prices = price_df[["date", "close_price"]].copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.strftime("%Y-%m-%d")
    onchain = onchain_df.copy()
    onchain["date"] = pd.to_datetime(onchain["date"]).dt.strftime("%Y-%m-%d")
    df = (
        onchain.merge(prices, on="date", how="inner")
        .sort_values("date")
        .reset_index(drop=True)
    )

    df["s1"] = [
        score_s1_holder_cost(p, lth, avg, sth)
        for p, lth, avg, sth in zip(
            df["close_price"],
            df["lth_realized_price"],
            df["realized_price"],
            df["sth_realized_price"],
        )
    ]
    df["s2_dev"] = full_sample_deviation(df["mvrv"])
    df["s2"] = _sigma_to_score(df["s2_dev"], *S2_SIGMA_ANCHORS)
    df["s3_dev"] = full_sample_deviation(df["supply_loss_pct"])
    df["s3"] = _sigma_to_score(df["s3_dev"], *S3_SIGMA_ANCHORS)
    s4_raw = pd.to_numeric(df["realized_cap_change_30d_usd"], errors="coerce")
    df["s4_pctile"] = (
        s4_raw.rank(pct=True)
        if s4_raw.notna().sum() >= MIN_OBSERVATIONS
        else pd.Series(np.nan, index=df.index)
    )
    df["s4"] = 20.0 * (1.0 - df["s4_pctile"])
    df["s5"] = [score_s5_fear_greed(v) for v in df["fear_greed"]]

    score_cols = ["s1", "s2", "s3", "s4", "s5"]
    for col in score_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["composite"] = df[score_cols].sum(axis=1, min_count=len(score_cols))

    zones = df["composite"].map(zone_for)
    df["zone"] = zones.map(lambda z: z[0] if z else None)
    df["zone_color"] = zones.map(lambda z: z[1] if z else None)
    return df
```

Note `sum(axis=1, min_count=5)` yields NaN whenever any signal is missing — that is the composite null guard.

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_bottom_signals.py -v`
Expected: all PASS

- [ ] **Step 5.5: Commit**

```bash
git add src/whenshouldubuybitcoin/bottom_signals.py tests/test_bottom_signals.py
git commit -m "feat: add S1-S5 bottom-signal scoring with composite"
```

---

### Task 6: Backtest (`bottom_signals.py`, part 2)

**Files:**
- Modify: `src/whenshouldubuybitcoin/bottom_signals.py` (append functions)
- Modify: `tests/test_bottom_signals.py` (append tests)

- [ ] **Step 6.1: Append the failing tests**

```python
# ---------- backtest ----------

def _backtest_frame() -> pd.DataFrame:
    # 30 days around the 2022-11-21 cycle bottom; composite crosses 60 twice
    dates = pd.date_range("2022-11-10", periods=30).strftime("%Y-%m-%d")
    composite = [50.0] * 5 + [65.0] * 4 + [55.0] * 6 + [82.0] * 1 + [50.0] * 14
    prices = np.linspace(17_000, 16_000, 30)
    return pd.DataFrame({"date": dates, "close_price": prices, "composite": composite})


def test_extract_trigger_segments_duration_filter():
    df = _backtest_frame()
    segs_1d = bs.extract_trigger_segments(df, 60, 1)
    assert len(segs_1d) == 2
    segs_3d = bs.extract_trigger_segments(df, 60, 3)
    assert len(segs_3d) == 1
    seg = segs_3d[0]
    assert seg["startDate"] == "2022-11-15"
    assert seg["endDate"] == "2022-11-18"
    assert seg["days"] == 4
    assert seg["minPrice"] <= seg["maxPrice"]
    assert seg["after90"]["min"] == pytest.approx(16_000.0)
    assert seg["after180"]["min"] == pytest.approx(16_000.0)


def test_extract_trigger_segments_handles_trailing_run():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5).strftime("%Y-%m-%d"),
            "close_price": [1.0, 2.0, 3.0, 4.0, 5.0],
            "composite": [10.0, 10.0, 90.0, 90.0, 90.0],
        }
    )
    segs = bs.extract_trigger_segments(df, 80, 3)
    assert len(segs) == 1
    assert segs[0]["endDate"] == "2024-01-05"
    assert segs[0]["after90"] is None  # no data beyond the segment end


def test_extract_trigger_segments_null_composite_never_qualifies():
    df = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "close_price": [1.0, 2.0],
            "composite": [np.nan, 95.0],
        }
    )
    segs = bs.extract_trigger_segments(df, 60, 1)
    assert len(segs) == 1 and segs[0]["days"] == 1


def test_assign_cycle_bottom_picks_nearest():
    seg = {"startDate": "2022-12-01", "endDate": "2022-12-10"}
    date, price = bs.assign_cycle_bottom(seg)
    assert date == "2022-11-21"
    seg2 = {"startDate": "2024-08-01", "endDate": "2024-08-10"}
    assert bs.assign_cycle_bottom(seg2)[0] == "2024-09-06"


def test_build_backtest_structure_and_accuracy():
    df = _backtest_frame()
    out = bs.build_backtest(df)
    assert set(out) == {"trig", "matrix"}
    assert set(out["trig"]) == {"60", "70", "80"}
    assert set(out["trig"]["60"]) == {"1", "3", "7"}
    cell = out["matrix"]["60"]["1"]
    # both segments bottom near $16-17k vs bottom 15797.53 * 1.3 = 20536 -> hits
    assert cell["segments"] == 2
    assert cell["hits"] == 2
    assert cell["accuracy"] == 100
    assert out["matrix"]["80"]["7"]["segments"] == 0
    assert out["matrix"]["80"]["7"]["accuracy"] is None
```

- [ ] **Step 6.2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_bottom_signals.py -v -k "trigger or cycle_bottom or backtest"`
Expected: FAIL with `AttributeError: ... extract_trigger_segments`

- [ ] **Step 6.3: Append the implementation to `bottom_signals.py`**

```python
def extract_trigger_segments(
    scores_df: pd.DataFrame, threshold: float, min_duration: int
) -> list[dict]:
    """Consecutive-row runs with composite >= threshold, kept when long enough.

    scores_df must be date-sorted with columns date, close_price, composite.
    Null composites never qualify. Forward 90/180-day windows are relative to
    the segment end date; None when no data exists beyond the segment.
    """
    df = scores_df.reset_index(drop=True)
    composite = pd.to_numeric(df["composite"], errors="coerce")
    qualifying = composite.ge(threshold).fillna(False)
    dates = pd.to_datetime(df["date"])

    segments: list[dict] = []
    start = None
    for i in range(len(df) + 1):
        active = i < len(df) and bool(qualifying.iloc[i])
        if active and start is None:
            start = i
        elif not active and start is not None:
            end = i - 1
            if end - start + 1 >= min_duration:
                seg = df.iloc[start : end + 1]
                end_date = dates.iloc[end]
                seg_dict = {
                    "startDate": str(df["date"].iloc[start]),
                    "endDate": str(df["date"].iloc[end]),
                    "days": int(end - start + 1),
                    "priceStart": float(seg["close_price"].iloc[0]),
                    "priceEnd": float(seg["close_price"].iloc[-1]),
                    "minPrice": float(seg["close_price"].min()),
                    "maxPrice": float(seg["close_price"].max()),
                    "avgPrice": float(seg["close_price"].mean()),
                }
                for horizon in (90, 180):
                    mask = (dates > end_date) & (
                        dates <= end_date + pd.Timedelta(days=horizon)
                    )
                    window = df.loc[mask, "close_price"]
                    seg_dict[f"after{horizon}"] = (
                        {"min": float(window.min()), "max": float(window.max())}
                        if not window.empty
                        else None
                    )
                segments.append(seg_dict)
            start = None
    return segments


def assign_cycle_bottom(segment: dict, bottoms=None) -> tuple[str, float]:
    """Nearest cycle bottom (by days) to the segment midpoint."""
    bottoms = bottoms or CYCLE_BOTTOMS
    start = pd.Timestamp(segment["startDate"])
    end = pd.Timestamp(segment["endDate"])
    mid = start + (end - start) / 2
    return min(bottoms, key=lambda b: abs((pd.Timestamp(b[0]) - mid).days))


def build_backtest(scores_df: pd.DataFrame) -> dict:
    """Precompute trigger segments and the accuracy matrix for all combos.

    Returns {"trig": {th: {dur: [segments]}}, "matrix": {th: {dur: cell}}}
    with string keys ready for JSON embedding; cell accuracy is a rounded
    percent or None when no segments exist.
    """
    trig: dict = {}
    matrix: dict = {}
    for th in THRESHOLDS:
        trig[str(th)] = {}
        matrix[str(th)] = {}
        for dur in DURATIONS:
            segments = extract_trigger_segments(scores_df, th, dur)
            hits = sum(
                1
                for seg in segments
                if seg["minPrice"]
                <= assign_cycle_bottom(seg)[1] * BOTTOM_HIT_MULTIPLE
            )
            trig[str(th)][str(dur)] = segments
            matrix[str(th)][str(dur)] = {
                "segments": len(segments),
                "hits": hits,
                "accuracy": round(100.0 * hits / len(segments)) if segments else None,
            }
    return {"trig": trig, "matrix": matrix}
```

- [ ] **Step 6.4: Run the full test file**

Run: `poetry run pytest tests/test_bottom_signals.py -v`
Expected: all PASS

- [ ] **Step 6.5: Commit**

```bash
git add src/whenshouldubuybitcoin/bottom_signals.py tests/test_bottom_signals.py
git commit -m "feat: add trigger-segment backtest and accuracy matrix"
```

---

### Task 7: Page helpers (`bottom_signals_page.py`, part 1)

**Files:**
- Create: `src/whenshouldubuybitcoin/bottom_signals_page.py`
- Test: `tests/test_bottom_signals_page.py`

- [ ] **Step 7.1: Write the failing tests**

```python
"""Tests for the prerendered bottom-signals dashboard page."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from whenshouldubuybitcoin import bottom_signals as bs
from whenshouldubuybitcoin import bottom_signals_page as page


def test_status_for_score_bands():
    assert page._status_for_score(None) == ("No data", "#71717a")
    assert page._status_for_score(17.0)[0] == "Bottom zone"
    assert page._status_for_score(12.0)[0] == "Leaning cheap"
    assert page._status_for_score(7.0)[0] == "Neutral"
    assert page._status_for_score(2.0)[0] == "Rich side"


def test_marker_pct():
    assert page.marker_pct(20.0) == pytest.approx(0.0)
    assert page.marker_pct(0.0) == pytest.approx(100.0)
    assert page.marker_pct(10.0) == pytest.approx(50.0)
    assert page.marker_pct(None) == pytest.approx(50.0)
    assert page.marker_pct(25.0) == pytest.approx(0.0)  # clamped


def test_gauge_svg_contains_needle_and_score():
    svg = page.gauge_svg(55.0, "Watch", "#6e6e73")
    assert svg.startswith("<svg")
    assert ">55<" in svg
    assert svg.count("<path") == 4  # one arc per zone band
    assert "<line" in svg and "<circle" in svg


def test_sparkline_points_shape():
    pts = page.sparkline_points([1.0, 2.0, 3.0, 2.0])
    pairs = [p.split(",") for p in pts.split()]
    assert len(pairs) == 4
    xs = [float(x) for x, _ in pairs]
    assert xs[0] == 0.0 and xs[-1] == pytest.approx(150.0)
    ys = [float(y) for _, y in pairs]
    assert min(ys) >= 0.0 and max(ys) <= 36.0


def test_sparkline_points_handles_flat_and_missing():
    assert page.sparkline_points([]) == ""
    assert page.sparkline_points([5.0]) == ""
    flat = page.sparkline_points([2.0, 2.0, 2.0])
    assert flat  # flat series still renders (mid-height line)
    gappy = page.sparkline_points([1.0, None, 3.0])
    assert len(gappy.split()) == 2
```

- [ ] **Step 7.2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_bottom_signals_page.py -v`
Expected: FAIL with `ModuleNotFoundError: ... bottom_signals_page`

- [ ] **Step 7.3: Implement the helpers**

```python
"""
Prerendered on-chain bottom-signals dashboard (Jinja2).

All values, the gauge SVG, sparklines, and backtest JSON are computed here
and embedded into a self-contained static page; the only client-side JS is
the threshold/duration toggle for the main chart.
"""

import json
import math
import tempfile
from pathlib import Path
from typing import Optional

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from .bottom_signals import ZONE_ADVICE, zone_for

TEMPLATE_DIR = Path(__file__).parent / "templates"
PLOTLY_CDN = "https://cdn.plot.ly/plotly-3.2.0.min.js"

OUTPUT_HTML = Path("docs/charts/bottom_signals.html")
OUTPUT_INFO = Path("docs/charts/bottom_signals_info.json")


def _status_for_score(score) -> tuple[str, str]:
    """Uniform per-signal status label/color from the 0-20 score."""
    if score is None or pd.isna(score):
        return "No data", "#71717a"
    if score >= 15:
        return "Bottom zone", "#3b82f6"
    if score >= 10:
        return "Leaning cheap", "#10b981"
    if score >= 5:
        return "Neutral", "#d97706"
    return "Rich side", "#6e6e73"


def marker_pct(score) -> float:
    """Marker position on the 4-band score bar; left edge = bottom (score 20)."""
    if score is None or pd.isna(score):
        return 50.0
    return max(0.0, min(100.0, 100.0 - 5.0 * float(score)))


def _polar(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return cx + r * math.cos(a), cy - r * math.sin(a)


def _arc_path(cx, cy, r, start_deg, end_deg) -> str:
    x1, y1 = _polar(cx, cy, r, start_deg)
    x2, y2 = _polar(cx, cy, r, end_deg)
    large = 1 if (start_deg - end_deg) > 180 else 0
    return f"M {x1:.2f} {y1:.2f} A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f}"


def gauge_svg(score: float, zone_label: str, zone_color: str) -> str:
    """Semi-circular 0-100 gauge; 0 at the left (180 deg), 100 at the right."""
    cx, cy, r = 170.0, 165.0, 118.0

    def angle(v: float) -> float:
        return 180.0 - 1.8 * v

    zone_bands = [
        (0, 60, "#d2d2d7"),
        (60, 70, "#10b981"),
        (70, 80, "#f59e0b"),
        (80, 100, "#ef4444"),
    ]
    arcs = "".join(
        f'<path d="{_arc_path(cx, cy, r, angle(lo), angle(hi))}" fill="none" '
        f'stroke="{color}" stroke-width="28"/>'
        for lo, hi, color in zone_bands
    )
    ticks = "".join(
        f'<text x="{x:.1f}" y="{y:.1f}" fill="#86868b" font-size="10" '
        f'text-anchor="middle" dominant-baseline="middle">{v}</text>'
        for v in (0, 60, 70, 80, 100)
        for x, y in [_polar(cx, cy, r + 24, angle(v))]
    )
    clamped = max(0.0, min(100.0, float(score)))
    nx, ny = _polar(cx, cy, r - 40, angle(clamped))
    needle = (
        f'<line x1="{cx}" y1="{cy}" x2="{nx:.2f}" y2="{ny:.2f}" '
        f'stroke="{zone_color}" stroke-width="3" stroke-linecap="round"/>'
        f'<circle cx="{cx}" cy="{cy}" r="6" fill="{zone_color}"/>'
    )
    label = (
        f'<text x="{cx}" y="127" fill="{zone_color}" font-size="46" '
        f'font-weight="700" text-anchor="middle">{score:.0f}</text>'
        f'<text x="{cx}" y="151" fill="#86868b" font-size="13" '
        f'text-anchor="middle">/ 100</text>'
    )
    return (
        '<svg viewBox="-10 0 360 200" width="100%" '
        'style="max-width:380px;display:block;">'
        + arcs + ticks + needle + label + "</svg>"
    )


def sparkline_points(values, width: float = 150.0, height: float = 36.0) -> str:
    """SVG polyline points for a score sparkline; skips missing values."""
    clean = [None if (v is None or pd.isna(v)) else float(v) for v in (values or [])]
    present = [v for v in clean if v is not None]
    if len(present) < 2:
        return ""
    vmin, vmax = min(present), max(present)
    span = (vmax - vmin) or 1.0
    n = len(clean)
    pts = []
    for i, v in enumerate(clean):
        if v is None:
            continue
        x = width * i / (n - 1)
        y = 2.0 + (height - 4.0) * (1.0 - (v - vmin) / span)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_bottom_signals_page.py -v`
Expected: all PASS

- [ ] **Step 7.5: Commit**

```bash
git add src/whenshouldubuybitcoin/bottom_signals_page.py tests/test_bottom_signals_page.py
git commit -m "feat: add gauge/sparkline/scale helpers for bottom-signals page"
```

---

### Task 8: Template + page generation (`bottom_signals_page.py`, part 2)

**Files:**
- Create: `src/whenshouldubuybitcoin/templates/bottom_signals.html.j2`
- Modify: `src/whenshouldubuybitcoin/bottom_signals_page.py` (append)
- Modify: `tests/test_bottom_signals_page.py` (append)

- [ ] **Step 8.1: Append the failing tests**

```python
def _synthetic_inputs():
    n = 400
    dates = pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    onchain = pd.DataFrame(
        {
            "date": dates,
            "lth_realized_price": np.linspace(40_000, 49_000, n),
            "realized_price": np.linspace(45_000, 54_000, n),
            "sth_realized_price": np.linspace(60_000, 75_000, n),
            "mvrv": np.concatenate([np.full(n // 2, 1.0), np.full(n - n // 2, 2.4)]),
            "supply_loss_pct": np.linspace(5.0, 25.0, n),
            "realized_cap_change_30d_usd": np.linspace(-3e10, 3e10, n),
            "fear_greed": np.linspace(80.0, 10.0, n),
        }
    )
    price_df = pd.DataFrame(
        {"date": dates, "close_price": np.linspace(70_000, 63_000, n)}
    )
    scores_df = bs.compute_bottom_signal_scores(onchain, price_df)
    backtest = bs.build_backtest(scores_df)
    return scores_df, price_df, backtest


def test_generate_page_writes_html_and_info(tmp_path):
    scores_df, price_df, backtest = _synthetic_inputs()
    html_path = tmp_path / "bottom_signals.html"
    info_path = tmp_path / "bottom_signals_info.json"
    snapshot = page.generate_bottom_signals_page(
        scores_df, price_df, backtest, output_path=html_path, info_path=info_path
    )

    html = html_path.read_text()
    assert "On-Chain Bottom Signals" in html
    assert "const TRIG =" in html
    assert "const cycleBots =" in html
    assert page.PLOTLY_CDN in html
    for title in ("S1", "S2", "S3", "S4", "S5", "MA 120", "accuracy matrix"):
        assert title in html, f"missing {title}"
    assert "bitcoin-data.com" in html and "alternative.me" in html

    info = json.loads(info_path.read_text())
    assert info["composite"] == pytest.approx(snapshot["composite"])
    assert len(info["signals"]) == 5
    assert info["zone"] in {z[2] for z in bs.ZONES}
    assert snapshot["date"] == scores_df["date"].iloc[-1]


def test_generate_page_snapshot_values_are_finite(tmp_path):
    scores_df, price_df, backtest = _synthetic_inputs()
    snapshot = page.generate_bottom_signals_page(
        scores_df,
        price_df,
        backtest,
        output_path=tmp_path / "p.html",
        info_path=tmp_path / "i.json",
    )
    assert 0 <= snapshot["composite"] <= 100
    assert snapshot["price"] > 0
    assert snapshot["ath"] >= snapshot["price"]
    assert snapshot["ma200"] > 0
    for sig in snapshot["signals"]:
        assert 0 <= sig["score"] <= 20
```

- [ ] **Step 8.2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_bottom_signals_page.py -v -k generate`
Expected: FAIL with `AttributeError: ... generate_bottom_signals_page`

- [ ] **Step 8.3: Create the Jinja2 template**

Create `src/whenshouldubuybitcoin/templates/bottom_signals.html.j2` exactly as follows (light theme matching `docs/index.html`):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>On-Chain Bottom Signals · When Should You Buy Bitcoin</title>
<script src="{{ plotly_cdn }}"></script>
<style>
  :root {
    --bg:#f5f5f7; --card:#ffffff; --card2:#f0f0f2; --border:#e3e3e8;
    --text:#1d1d1f; --muted:#86868b; --green:#10b981; --gold:#f59e0b;
    --red:#ef4444; --blue:#3b82f6;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); padding:24px;
         font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',Roboto,sans-serif;
         line-height:1.5; }
  .wrap { max-width:1280px; margin:0 auto; }
  .pagetitle { font-size:13px; color:var(--muted); margin-bottom:16px; }
  .pagetitle b { color:var(--text); font-size:15px; }
  .pagetitle a { color:#0066cc; text-decoration:none; }
  .pagetitle a:hover { text-decoration:underline; }

  .hero { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:24px; }
  .hero-price, .hero-gauge { background:var(--card); border:1px solid var(--border);
    border-radius:16px; padding:24px; box-shadow:0 2px 8px rgba(0,0,0,0.04); }
  .hero-price { display:flex; flex-direction:column; justify-content:center; }
  .hero-price .label { font-size:13px; color:var(--muted); margin-bottom:6px; }
  .hero-price .big { font-size:46px; font-weight:800; line-height:1.05; letter-spacing:-0.02em; }
  .hero-price .chg { font-size:19px; margin-top:6px; }
  .hero-price .meta { margin-top:16px; font-size:13px; color:var(--muted); }
  .hero-price .meta b { color:var(--text); }
  .pos { color:var(--green); } .neg { color:var(--red); }
  .hero-gauge { display:flex; flex-direction:column; align-items:center; }
  .hero-gauge .glabel { font-size:13px; color:var(--muted); align-self:flex-start; }
  .gauge-zone { margin-top:6px; padding:6px 18px; border-radius:999px; font-size:15px; font-weight:600; }
  .gauge-advice { margin-top:8px; font-size:14px; font-weight:600; }

  .section-title { font-size:14px; font-weight:600; margin:8px 0 14px; }
  .grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:28px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px;
          padding:16px; box-shadow:0 2px 8px rgba(0,0,0,0.04); }
  .card-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
  .card-title { font-size:14px; font-weight:600; }
  .card-status { font-size:12px; font-weight:600; }
  .card-sub { font-size:11px; color:var(--muted); margin:-4px 0 10px; }
  .card-score { font-size:32px; font-weight:700; line-height:1; }
  .card-score-max { font-size:15px; color:var(--muted); font-weight:400; }
  .card-bar { height:5px; background:var(--card2); border-radius:99px; margin:10px 0; overflow:hidden; }
  .card-bar-fill { height:100%; border-radius:99px; }
  .card-now { font-size:13px; color:var(--muted); margin-bottom:4px; }
  .card-now b { font-size:19px; color:var(--text); font-weight:700; }
  .scale { margin:8px 0 6px; }
  .scale-bar { position:relative; display:flex; height:8px; border-radius:4px; overflow:hidden; }
  .scale-bar > div:not(.scale-marker) { height:100%; }
  .scale-marker { position:absolute; top:-3px; width:3px; height:14px; background:var(--text);
                  border-radius:2px; transform:translateX(-50%); box-shadow:0 0 4px rgba(0,0,0,0.5); }
  .scale-labels { display:flex; justify-content:space-between; font-size:10px; color:var(--muted); margin-top:4px; }
  .s1-lines { display:flex; flex-direction:column; gap:7px; margin:4px 0 8px; }
  .s1-line { display:grid; grid-template-columns:1fr auto auto; align-items:center; gap:10px; font-size:13px; }
  .s1-line .s1-name { color:var(--muted); }
  .s1-line b { color:var(--text); }
  .s1-line span:last-child { font-size:11px; color:var(--muted); }
  .card-dist { font-size:12px; color:var(--muted); margin-top:4px; font-style:italic; }
  .card-spark { margin-top:10px; opacity:0.9; }
  .ma-rows { display:flex; flex-direction:column; gap:8px; margin-top:4px; }
  .ma-row { display:flex; justify-content:space-between; align-items:center; font-size:14px; }
  .ma-row span:first-child { color:var(--muted); }

  .chart-box { background:var(--card); border:1px solid var(--border); border-radius:12px;
               padding:16px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,0.04); }
  .chart-box h3 { font-size:14px; margin-bottom:4px; }
  .chart-box .sub { font-size:12px; color:var(--muted); margin-bottom:10px; }
  .toggles { display:flex; gap:20px; flex-wrap:wrap; align-items:center; margin-bottom:12px; }
  .toggle-group { display:flex; align-items:center; gap:6px; }
  .toggle-group .lbl { font-size:12px; color:var(--muted); margin-right:2px; }
  .tbtn { padding:5px 12px; background:var(--card2); color:var(--muted); border:1px solid var(--border);
          border-radius:6px; cursor:pointer; font-size:12px; }
  .tbtn.active { background:var(--green); color:#fff; border-color:var(--green); }
  .caption { font-size:12px; color:var(--muted); margin-top:8px; }

  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { padding:8px 12px; text-align:left; border-bottom:1px solid var(--border); }
  th { background:var(--card2); color:var(--muted); font-size:11px; text-transform:uppercase;
       letter-spacing:.04em; font-weight:500; }
  td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .table-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; }

  .sys-note { margin-top:18px; padding:16px 18px; background:var(--card); border:1px solid var(--border);
              border-radius:10px; font-size:13px; line-height:1.85; color:var(--muted); }
  .sys-note h4 { margin:0 0 8px; font-size:14px; color:var(--text); }
  .sys-note p { margin:6px 0; }
  .sys-note b { color:var(--text); }
  .disclaimer { margin-top:32px; padding-top:18px; border-top:1px solid var(--border);
                text-align:center; color:var(--muted); font-size:12px; line-height:1.9; }
  .disclaimer a { color:#0066cc; text-decoration:none; }

  @media(max-width:900px){ .hero{grid-template-columns:1fr;} .grid{grid-template-columns:repeat(2,1fr);} }
  @media(max-width:600px){
    body{ padding:14px; }
    .hero{ gap:14px; margin-bottom:18px; }
    .hero-price .big{ font-size:38px; }
    .grid{ grid-template-columns:1fr; gap:12px; }
    #mainChart{ height:340px !important; }
    .table-scroll table{ min-width:600px; }
  }
</style>
</head>
<body>
<div class="wrap">

  <div class="pagetitle">
    <a href="../index.html">← Back to dashboard</a> &nbsp;·&nbsp;
    <b>⛓️ On-Chain Bottom Signals</b> &nbsp;·&nbsp; data through {{ data_date }}
  </div>

  <div class="hero">
    <div class="hero-price">
      <div class="label">BTC price (USD, daily close)</div>
      <div class="big">${{ "{:,.0f}".format(price) }}</div>
      <div class="chg {{ 'neg' if chg24h_pct < 0 else 'pos' }}">{{ "%+.2f"|format(chg24h_pct) }}% <span style="color:var(--muted);font-size:13px;">24h</span></div>
      <div class="meta">From ATH ${{ "{:,.0f}".format(ath) }}: <b class="{{ 'neg' if from_ath_pct < 0 else 'pos' }}">{{ "%+.1f"|format(from_ath_pct) }}%</b></div>
    </div>
    <div class="hero-gauge">
      <div class="glabel">Composite score</div>
      {{ gauge|safe }}
      <div class="gauge-zone" style="background:{{ zone_color }}22;color:{{ zone_color }};">{{ zone }}</div>
      <div class="gauge-advice" style="color:{{ zone_color }};">{{ advice }}</div>
    </div>
  </div>

  <div class="section-title">5 signals + moving-average reference</div>
  <div class="grid">
    {% for card in cards %}
    <div class="card" style="border-color:{{ card.color }}55;">
      <div class="card-head">
        <span class="card-title">{{ card.title }}</span>
        <span class="card-status" style="color:{{ card.color }};">● {{ card.status }}</span>
      </div>
      <div class="card-sub">{{ card.subtitle }}</div>
      <div class="card-score" style="color:{{ card.color }};">{{ card.score_text }}<span class="card-score-max">/20</span></div>
      <div class="card-bar"><div class="card-bar-fill" style="width:{{ card.bar_pct }}%;background:{{ card.color }};"></div></div>
      <div class="card-now">{{ card.now_html|safe }}</div>
      <div class="scale">
        <div class="scale-bar">
          <div style="width:25%;background:var(--blue);"></div><div style="width:25%;background:var(--green);"></div><div style="width:25%;background:var(--gold);"></div><div style="width:25%;background:var(--red);"></div>
          <div class="scale-marker" style="left:{{ card.marker_pct }}%;"></div>
        </div>
        <div class="scale-labels"><span>← bottom</span><span>top →</span></div>
      </div>
      {% if card.extra_html %}{{ card.extra_html|safe }}{% endif %}
      {% if card.spark %}
      <div class="card-spark"><svg width="150" height="36"><polyline points="{{ card.spark }}" fill="none" stroke="{{ card.color }}" stroke-width="1.5" stroke-linejoin="round"/></svg></div>
      {% endif %}
    </div>
    {% endfor %}

    <div class="card">
      <div class="card-head">
        <span class="card-title">MA · Long-term averages</span>
        <span class="card-status" style="color:var(--muted);">reference only</span>
      </div>
      <div class="card-sub">Not part of the composite score</div>
      <div class="ma-rows">
        <div class="ma-row"><span>MA 120</span><b>${{ "{:,.0f}".format(ma120) }}</b><span class="{{ 'neg' if ma120_dist_pct < 0 else 'pos' }}">{{ "%+.1f"|format(ma120_dist_pct) }}%</span></div>
        <div class="ma-row"><span>MA 200</span><b>${{ "{:,.0f}".format(ma200) }}</b><span class="{{ 'neg' if ma200_dist_pct < 0 else 'pos' }}">{{ "%+.1f"|format(ma200_dist_pct) }}%</span></div>
      </div>
      <div class="card-dist">{{ ma_comment }}</div>
    </div>
  </div>

  <div class="chart-box">
    <h3>📈 Where history triggered: price + composite score + trigger zones</h3>
    <div class="sub">Green shading = historical trigger segments for the selected combo · red dotted lines = cycle bottoms · right axis = composite score</div>
    <div class="toggles">
      <div class="toggle-group"><span class="lbl">Threshold</span>
        <button class="tbtn th-btn active" data-th="60">≥60</button>
        <button class="tbtn th-btn" data-th="70">≥70</button>
        <button class="tbtn th-btn" data-th="80">≥80</button>
      </div>
      <div class="toggle-group"><span class="lbl">Duration</span>
        <button class="tbtn dur-btn active" data-dur="1">same day</button>
        <button class="tbtn dur-btn" data-dur="3">3 days straight</button>
        <button class="tbtn dur-btn" data-dur="7">7 days straight</button>
      </div>
    </div>
    <div id="mainChart" style="width:100%;height:480px;"></div>
    <div class="caption" id="caption"></div>
  </div>

  <div class="chart-box">
    <h3>💰 What prices history bought at: trigger segment detail</h3>
    <div class="sub">Linked to the threshold × duration toggles above · shows each segment's buy range and whether price went lower afterwards</div>
    <div class="table-scroll">
      <table>
        <thead><tr><th>Start</th><th>End</th><th class="num">Days</th><th class="num">Start price</th><th class="num">Segment low</th><th class="num">Low within 90d after</th><th class="num">Low within 180d after</th></tr></thead>
        <tbody id="segTableBody"></tbody>
      </table>
    </div>
  </div>

  <div class="chart-box">
    <h3>🎯 How accurate was it: accuracy matrix</h3>
    <div class="sub">Cell = number of historical trigger segments · share whose segment low landed within 30% above the nearest cycle bottom</div>
    <div class="table-scroll">
      <table>
        <thead><tr><th>Threshold</th><th class="num">same day</th><th class="num">3 days straight</th><th class="num">7 days straight</th></tr></thead>
        <tbody>
          {% for th in thresholds %}
          <tr>
            <td>≥{{ th }}</td>
            {% for dur in durations %}
            {% set cell = matrix[th|string][dur|string] %}
            <td class="num">{% if cell.segments %}{{ cell.segments }} seg · {{ cell.accuracy }}%{% else %}—{% endif %}</td>
            {% endfor %}
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    <div class="sys-note">
      <h4>About this system</h4>
      <p>Five on-chain/sentiment signals are each scored 0-20 and summed into a 0-100 composite:
      <b>S1</b> price vs long-term-holder / average / short-term-holder cost basis,
      <b>S2</b> MVRV deviation from its historical mean (in sigma),
      <b>S3</b> share of circulating supply in unrealized loss (sigma deviation),
      <b>S4</b> 30-day realized-cap net change (historical percentile),
      <b>S5</b> the Fear &amp; Greed Index. Zones: &lt;60 Watch, 60-70 Mildly Undervalued, 70-80 Undervalued, ≥80 Extremely Undervalued.</p>
      <p><b>Honest caveats:</b> on-chain history comes from a free API limited to the most recent ~4 years, so the backtest covers the {{ cycle_bottoms_label }} bottoms only — far fewer cycles than ideal. Sigma/percentile statistics use the <b>full sample</b> (the same statistics score early and recent dates), which introduces look-ahead bias into the shaded backtest. S3 uses supply-weighted loss share rather than the value-weighted "relative unrealized loss" used by some paid dashboards. None of this is investment advice.</p>
      <p>Data sources: <a href="https://bitcoin-data.com" style="color:#0066cc;">bitcoin-data.com (BGeometrics)</a> on-chain series · <a href="https://alternative.me/crypto/fear-and-greed-index/" style="color:#0066cc;">alternative.me</a> Fear &amp; Greed. </p>
    </div>
  </div>

  <div class="disclaimer">
    ⚠️ Personal research, not investment advice. DYOR.<br>
    Part of <a href="../index.html">When Should You Buy Bitcoin</a>.
  </div>
</div>

<script>
const dates = {{ dates_json|safe }};
const prices = {{ prices_json|safe }};
const totals = {{ totals_json|safe }};
const cycleBots = {{ cycle_bots_json|safe }};
const TRIG = {{ trig_json|safe }};
const SHADE = {"60":"rgba(16,185,129,0.10)","70":"rgba(16,185,129,0.16)","80":"rgba(16,185,129,0.24)"};
let curTh = "60", curDur = "1";
const fmtUSD = v => '$' + Math.round(v).toLocaleString('en-US');

Plotly.newPlot('mainChart', [
  {x: dates, y: prices, name: 'BTC price', type: 'scatter', mode: 'lines',
   line: {color: '#1d1d1f', width: 1.4}},
  {x: dates, y: totals, name: 'Composite score', type: 'scatter', mode: 'lines',
   line: {color: '#f59e0b', width: 1.2}, yaxis: 'y2'},
], {
  margin: {l: 56, r: 48, t: 10, b: 36},
  paper_bgcolor: '#ffffff', plot_bgcolor: '#ffffff',
  font: {color: '#1d1d1f', size: 12},
  xaxis: {gridcolor: '#eeeeef'},
  yaxis: {title: 'Price (log)', type: 'log', gridcolor: '#eeeeef'},
  yaxis2: {title: 'Score', overlaying: 'y', side: 'right', range: [0, 100], showgrid: false},
  legend: {orientation: 'h', y: 1.08},
}, {responsive: true, displayModeBar: false});

function refresh() {
  const segs = (TRIG[curTh] && TRIG[curTh][curDur]) || [];
  const shapes = segs.map(s => ({
    type: 'rect', xref: 'x', yref: 'paper', x0: s.startDate, x1: s.endDate, y0: 0, y1: 1,
    fillcolor: SHADE[curTh], line: {width: 0}, layer: 'below',
  })).concat(cycleBots.map(b => ({
    type: 'line', xref: 'x', yref: 'paper', x0: b.date, x1: b.date, y0: 0, y1: 1,
    line: {color: 'rgba(239,68,68,0.5)', width: 1, dash: 'dot'}, layer: 'below',
  })));
  Plotly.relayout('mainChart', {shapes});
  const durLabel = curDur === '1' ? 'same-day trigger' : curDur + ' consecutive days';
  document.getElementById('caption').textContent =
    'Current: score ≥' + curTh + ' / ' + durLabel + ' · ' + segs.length + ' historical segment(s)';
  const tbody = document.getElementById('segTableBody');
  if (!segs.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:16px;">(no trigger segments for this combo)</td></tr>';
  } else {
    tbody.innerHTML = segs.map(s => '<tr>' +
      '<td>' + s.startDate + '</td><td>' + s.endDate + '</td>' +
      '<td class="num">' + s.days + '</td>' +
      '<td class="num">' + fmtUSD(s.priceStart) + '</td>' +
      '<td class="num">' + fmtUSD(s.minPrice) + '</td>' +
      '<td class="num">' + (s.after90 ? fmtUSD(s.after90.min) : '—') + '</td>' +
      '<td class="num">' + (s.after180 ? fmtUSD(s.after180.min) : '—') + '</td>' +
    '</tr>').join('');
  }
}
document.querySelectorAll('.th-btn').forEach(b => b.addEventListener('click', () => {
  curTh = b.dataset.th;
  document.querySelectorAll('.th-btn').forEach(x => x.classList.toggle('active', x === b));
  refresh();
}));
document.querySelectorAll('.dur-btn').forEach(b => b.addEventListener('click', () => {
  curDur = b.dataset.dur;
  document.querySelectorAll('.dur-btn').forEach(x => x.classList.toggle('active', x === b));
  refresh();
}));
refresh();
</script>
</body>
</html>
```

- [ ] **Step 8.4: Append the page generation code to `bottom_signals_page.py`**

Add these imports at the top of the file: `from .bottom_signals import CYCLE_BOTTOMS, DURATIONS, THRESHOLDS` (merge with the existing import from `.bottom_signals`), and `from .persistence import _atomic_write_text`.

```python
SIGNAL_DEFS = [
    ("s1", "S1 · Holder Cost Basis", "Price vs the three holder cost-basis lines"),
    ("s2", "S2 · MVRV Deviation", "Market value vs aggregate on-chain cost basis"),
    ("s3", "S3 · Supply in Loss", "Share of supply underwater (more = closer to a bottom)"),
    ("s4", "S4 · Capital Net Change", "30-day realized-cap inflow / outflow"),
    ("s5", "S5 · Fear & Greed", "How cold is market sentiment"),
]

SIGNAL_SHORT_LABELS = {
    "s1": "Holder cost",
    "s2": "MVRV",
    "s3": "Supply in loss",
    "s4": "Capital flow",
    "s5": "Fear & Greed",
}


def _fmt_usd_compact(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    sign = "-" if value < 0 else "+"
    v = abs(float(value))
    if v >= 1e12:
        return f"{sign}${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"{sign}${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.0f}M"
    return f"{sign}${v:,.0f}"


def _fng_classification(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    v = float(value)
    if v <= 25:
        return "Extreme Fear"
    if v <= 45:
        return "Fear"
    if v < 55:
        return "Neutral"
    if v < 75:
        return "Greed"
    return "Extreme Greed"


def _rel_line(price: float, line) -> str:
    if line is None or pd.isna(line) or line <= 0:
        return "N/A"
    pct = (price / float(line) - 1.0) * 100.0
    side = "above" if pct >= 0 else "below"
    return f"price {abs(pct):.1f}% {side}"


def _build_cards(latest: pd.Series, scores_df: pd.DataFrame) -> list[dict]:
    cards = []
    spark_window = scores_df.tail(90)
    for key, title, subtitle in SIGNAL_DEFS:
        score = latest.get(key)
        status, color = _status_for_score(score)
        score_missing = score is None or pd.isna(score)
        price = float(latest["close_price"])

        if key == "s1":
            now_html = f"Current BTC <b>${price:,.0f}</b>"
            extra = '<div class="s1-lines">'
            for line_key, dot, name in [
                ("sth_realized_price", "var(--red)", "Short-term holder cost"),
                ("realized_price", "var(--gold)", "Average holder cost"),
                ("lth_realized_price", "var(--blue)", "Long-term holder cost"),
            ]:
                line_val = latest.get(line_key)
                shown = (
                    f"${float(line_val):,.0f}"
                    if line_val is not None and not pd.isna(line_val)
                    else "N/A"
                )
                extra += (
                    f'<div class="s1-line"><span class="s1-name">'
                    f'<span style="color:{dot};">●</span> {name}</span>'
                    f"<b>{shown}</b><span>{_rel_line(price, line_val)}</span></div>"
                )
            extra += "</div>"
            extra += (
                '<div class="card-dist">Below average cost = most holders underwater · '
                "below long-term cost = deep-value zone</div>"
            )
        elif key == "s2":
            mvrv = latest.get("mvrv")
            dev = latest.get("s2_dev")
            mvrv_txt = f"{float(mvrv):.2f}" if mvrv is not None and not pd.isna(mvrv) else "N/A"
            dev_txt = (
                f"{float(dev):+.2f}σ vs full-sample mean"
                if dev is not None and not pd.isna(dev)
                else "insufficient history"
            )
            now_html = f"Current MVRV <b>{mvrv_txt}</b> · {dev_txt}"
            extra = '<div class="card-dist">Further left = closer to historical bottoms</div>'
        elif key == "s3":
            loss = latest.get("supply_loss_pct")
            dev = latest.get("s3_dev")
            loss_txt = f"{float(loss):.1f}%" if loss is not None and not pd.isna(loss) else "N/A"
            dev_txt = (
                f"{float(dev):+.2f}σ" if dev is not None and not pd.isna(dev) else "n/a"
            )
            now_html = f"Supply in loss <b>{loss_txt}</b> · {dev_txt}"
            extra = (
                '<div class="card-dist">Bull tops ≈ 0-2% · bear bottoms reach 50%+ '
                "(supply-weighted)</div>"
            )
        elif key == "s4":
            flow = latest.get("realized_cap_change_30d_usd")
            pctile = latest.get("s4_pctile")
            pct_txt = (
                f"{float(pctile) * 100.0:.0f}th percentile"
                if pctile is not None and not pd.isna(pctile)
                else "insufficient history"
            )
            now_html = f"30d realized-cap change <b>{_fmt_usd_compact(flow)}</b> · {pct_txt}"
            extra = (
                '<div class="card-dist">Deep outflows historically cluster near '
                "capitulation lows</div>"
            )
        else:  # s5
            fng = latest.get("fear_greed")
            fng_txt = f"{float(fng):.0f}" if fng is not None and not pd.isna(fng) else "N/A"
            now_html = f"Fear &amp; Greed <b>{fng_txt}</b> · {_fng_classification(fng)}"
            extra = '<div class="card-dist">0 = extreme fear (bottoms) · 100 = extreme greed (tops)</div>'

        cards.append(
            {
                "title": title,
                "subtitle": subtitle,
                "status": status,
                "color": color,
                "score_text": "–" if score_missing else f"{float(score):.1f}",
                "bar_pct": 0.0 if score_missing else round(5.0 * float(score), 1),
                "marker_pct": round(marker_pct(score), 1),
                "now_html": now_html,
                "extra_html": extra,
                "spark": sparkline_points(spark_window[key].tolist()),
            }
        )
    return cards


def generate_bottom_signals_page(
    scores_df: pd.DataFrame,
    price_df: pd.DataFrame,
    backtest: dict,
    output_path: Path = OUTPUT_HTML,
    info_path: Path = OUTPUT_INFO,
) -> dict:
    """Render the dashboard page and info JSON; return the snapshot dict.

    scores_df comes from compute_bottom_signal_scores (date-sorted), price_df
    is the full btc_metrics frame (for ATH / MA context beyond the on-chain
    window), backtest comes from build_backtest.
    """
    scored = scores_df[scores_df["composite"].notna()]
    if scored.empty:
        raise ValueError("no rows with a composite score; cannot render page")
    latest = scored.iloc[-1]

    closes = pd.to_numeric(price_df["close_price"], errors="coerce").dropna()
    price = float(latest["close_price"])
    chg24h = (
        (closes.iloc[-1] / closes.iloc[-2] - 1.0) * 100.0 if len(closes) >= 2 else 0.0
    )
    ath = float(closes.max())
    ma120 = float(closes.rolling(120).mean().iloc[-1]) if len(closes) >= 120 else price
    ma200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else price

    composite = float(latest["composite"])
    zone_label, zone_color = zone_for(composite)
    advice = ZONE_ADVICE[zone_label]

    if price < ma120 and price < ma200:
        ma_comment = "Price below both averages (weak trend)"
    elif price > ma120 and price > ma200:
        ma_comment = "Price above both averages (strong trend)"
    else:
        ma_comment = "Price between the two averages (transition)"

    context = {
        "plotly_cdn": PLOTLY_CDN,
        "data_date": str(latest["date"]),
        "price": price,
        "chg24h_pct": chg24h,
        "ath": ath,
        "from_ath_pct": (price / ath - 1.0) * 100.0,
        "gauge": gauge_svg(composite, zone_label, zone_color),
        "zone": zone_label,
        "zone_color": zone_color,
        "advice": advice,
        "cards": _build_cards(latest, scores_df),
        "ma120": ma120,
        "ma200": ma200,
        "ma120_dist_pct": (price / ma120 - 1.0) * 100.0,
        "ma200_dist_pct": (price / ma200 - 1.0) * 100.0,
        "ma_comment": ma_comment,
        "thresholds": list(THRESHOLDS),
        "durations": list(DURATIONS),
        "matrix": backtest["matrix"],
        "cycle_bottoms_label": " and ".join(b[0][:7] for b in CYCLE_BOTTOMS),
        "dates_json": json.dumps(scores_df["date"].tolist()),
        "prices_json": json.dumps(
            [round(float(v), 2) for v in scores_df["close_price"]]
        ),
        "totals_json": json.dumps(
            [
                None if pd.isna(v) else round(float(v), 2)
                for v in scores_df["composite"]
            ]
        ),
        "cycle_bots_json": json.dumps(
            [{"date": d, "price": p} for d, p in CYCLE_BOTTOMS]
        ),
        "trig_json": json.dumps(backtest["trig"]),
    }

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    html = env.get_template("bottom_signals.html.j2").render(**context)
    _atomic_write_text(Path(output_path), html)
    print(f"✓ Bottom signals page written to {output_path}")

    snapshot = {
        "date": str(latest["date"]),
        "price": price,
        "chg24h_pct": chg24h,
        "ath": ath,
        "from_ath_pct": (price / ath - 1.0) * 100.0,
        "composite": composite,
        "zone": zone_label,
        "zone_color": zone_color,
        "advice": advice,
        "signals": [
            {
                "key": key,
                "label": SIGNAL_SHORT_LABELS[key],
                "score": round(float(latest[key]), 1),
                "status": _status_for_score(latest[key])[0],
            }
            for key, _, _ in SIGNAL_DEFS
        ],
        "mvrv": None if pd.isna(latest.get("mvrv")) else float(latest["mvrv"]),
        "supply_loss_pct": None
        if pd.isna(latest.get("supply_loss_pct"))
        else float(latest["supply_loss_pct"]),
        "realized_cap_change_30d_usd": None
        if pd.isna(latest.get("realized_cap_change_30d_usd"))
        else float(latest["realized_cap_change_30d_usd"]),
        "fear_greed": None
        if pd.isna(latest.get("fear_greed"))
        else float(latest["fear_greed"]),
        "lth_realized_price": None
        if pd.isna(latest.get("lth_realized_price"))
        else float(latest["lth_realized_price"]),
        "realized_price": None
        if pd.isna(latest.get("realized_price"))
        else float(latest["realized_price"]),
        "sth_realized_price": None
        if pd.isna(latest.get("sth_realized_price"))
        else float(latest["sth_realized_price"]),
        "ma120": ma120,
        "ma200": ma200,
    }
    _atomic_write_text(Path(info_path), json.dumps(snapshot, indent=2))
    print(f"✓ Bottom signals info written to {info_path}")
    return snapshot
```

- [ ] **Step 8.5: Run the full test file**

Run: `poetry run pytest tests/test_bottom_signals_page.py -v`
Expected: all PASS (`"MA 120"` matches the MA card row label, `"accuracy matrix"` matches the matrix heading).

- [ ] **Step 8.6: Commit**

```bash
git add src/whenshouldubuybitcoin/templates/bottom_signals.html.j2 src/whenshouldubuybitcoin/bottom_signals_page.py tests/test_bottom_signals_page.py
git commit -m "feat: render prerendered bottom-signals dashboard page + info JSON"
```

---

### Task 9: Seed the initial dataset from fixtures

**Files:**
- Create: `scripts/seed_onchain_from_fixtures.py`
- Create (generated): `docs/data/onchain_metrics.csv`

- [ ] **Step 9.1: Write the seed script**

```python
#!/usr/bin/env python3
"""Build the initial docs/data/onchain_metrics.csv from committed fixtures.

Spends zero bitcoin-data.com requests: the Task-1 fixtures already contain the
full free-tier window. Fear & Greed history is fetched live (alternative.me is
not meaningfully rate-limited). Run once; afterwards the daily pipeline keeps
the CSV current incrementally.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from whenshouldubuybitcoin.onchain_data import (
    _series_dict_to_frame,
    load_onchain_metrics,
    merge_onchain,
    save_onchain_metrics,
)
from whenshouldubuybitcoin.providers.alternative_me import (
    fetch_fear_and_greed_history,
)
from whenshouldubuybitcoin.providers.bitcoin_data_com import (
    ONCHAIN_ENDPOINTS,
    parse_series,
)

FIXTURE_DIR = Path("tests/fixtures/bitcoin_data_com")


def main() -> None:
    series_by_metric = {}
    for key in ONCHAIN_ENDPOINTS:
        path = FIXTURE_DIR / f"{key}.json"
        rows = json.loads(path.read_text())
        series_by_metric[key] = parse_series(rows)
        print(f"✓ {key}: {len(series_by_metric[key])} rows from fixture")

    fng = fetch_fear_and_greed_history()
    print(f"✓ fear_greed: {len(fng) if fng else 0} rows from alternative.me")

    new = _series_dict_to_frame(series_by_metric, fng)
    merged = merge_onchain(load_onchain_metrics(), new)
    save_onchain_metrics(merged)
    print(
        f"Seeded {len(merged)} rows: {merged['date'].min()} .. {merged['date'].max()}"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 9.2: Run it**

Run: `poetry run python scripts/seed_onchain_from_fixtures.py`
Expected: `docs/data/onchain_metrics.csv` created; on-chain columns covering ~4 years (≈2022-06 onward), `fear_greed` covering 2018-02 onward. Spot-check the last row's values against Step 1.3.

- [ ] **Step 9.3: Commit**

```bash
git add scripts/seed_onchain_from_fixtures.py docs/data/onchain_metrics.csv
git commit -m "feat: seed on-chain metrics dataset from captured fixtures"
```

---

### Task 10: Pipeline wiring (`main.py`)

**Files:**
- Modify: `main.py` (imports ~line 46, `component_status` ~line 137, new step after the macro-charts block ~line 419, daily-report call ~line 586)

- [ ] **Step 10.1: Add imports** (after the existing provider imports, around `main.py:46`)

```python
from whenshouldubuybitcoin.onchain_data import update_onchain_metrics
from whenshouldubuybitcoin.bottom_signals import (
    compute_bottom_signal_scores,
    build_backtest,
)
from whenshouldubuybitcoin.bottom_signals_page import generate_bottom_signals_page
```

- [ ] **Step 10.2: Register the component** — in the `component_status` dict (`main.py:137-143`), add:

```python
            "bottom_signals": False,
```

- [ ] **Step 10.3: Add the generation step** — immediately after the macro-charts `except` block (after `main.py:419`, before `# --- Step 6: Futures Data Analysis ---`):

```python
        # Generate on-chain bottom signals dashboard
        print("\n" + "=" * 80)
        print("GENERATING ON-CHAIN BOTTOM SIGNALS")
        print("=" * 80)
        bottom_signals_snapshot = None
        try:
            onchain_df = update_onchain_metrics()
            if onchain_df is None or onchain_df.empty:
                raise RuntimeError("no on-chain data available (fetch failed and no cache)")
            scores_df = compute_bottom_signal_scores(onchain_df, df)
            backtest = build_backtest(scores_df)
            bottom_signals_snapshot = generate_bottom_signals_page(scores_df, df, backtest)
            print(
                f"✓ Bottom signals: composite {bottom_signals_snapshot['composite']:.0f} "
                f"({bottom_signals_snapshot['zone']})"
            )
            component_status["bottom_signals"] = True
        except Exception as e:
            print(f"⚠ Warning: Failed to generate on-chain bottom signals: {e}")
            print("  Continuing without bottom signals page.")
            if strict_update:
                raise
```

- [ ] **Step 10.4: Pass the snapshot to the daily report** — in the `generate_daily_report(...)` call (`main.py:586-593`), add the keyword argument:

```python
                bottom_signals_snapshot=bottom_signals_snapshot,
```

(`daily_report.py` gains this parameter in Task 11; do Task 11's Step 11.3 before running the pipeline.)

- [ ] **Step 10.5:** Proceed to Task 11 before the end-to-end run (the daily-report signature must exist first).

---

### Task 11: Daily report section

**Files:**
- Modify: `src/whenshouldubuybitcoin/daily_report.py` (`build_report_payload` ~line 157, `generate_daily_report` ~line 1025, `_deterministic_en_summary` ~line 410, `_deterministic_zh_summary` ~line 576)
- Modify: `tests/test_daily_report.py` (append)

- [ ] **Step 11.1: Append the failing tests**

Match the existing test style in `tests/test_daily_report.py` (it builds frames and calls `build_report_payload`); append:

```python
def _bottom_signals_snapshot():
    return {
        "date": "2026-06-08",
        "composite": 55.0,
        "zone": "Watch",
        "advice": "Not cheap yet — keep watching.",
        "signals": [
            {"key": "s1", "label": "Holder cost", "score": 4.2, "status": "Rich side"},
            {"key": "s2", "label": "MVRV", "score": 14.2, "status": "Leaning cheap"},
            {"key": "s3", "label": "Supply in loss", "score": 7.1, "status": "Neutral"},
            {"key": "s4", "label": "Capital flow", "score": 10.0, "status": "Leaning cheap"},
            {"key": "s5", "label": "Fear & Greed", "score": 20.0, "status": "Bottom zone"},
        ],
        "mvrv": 1.18,
        "supply_loss_pct": 20.6,
        "realized_cap_change_30d_usd": -2.09e10,
        "fear_greed": 10.0,
    }


def _minimal_btc_df():
    # build_report_payload only needs a date-sorted metrics frame; mirror the
    # frame-construction style already used at the top of this test file if
    # one exists, otherwise this minimal frame suffices for the MA section.
    n = 250
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-10-01", periods=n),
            "close_price": np.linspace(60_000.0, 63_000.0, n),
            "volume": np.full(n, 1.0e9),
        }
    )


def test_report_includes_bottom_signals_section():
    payload = build_report_payload(
        _minimal_btc_df(), bottom_signals_snapshot=_bottom_signals_snapshot()
    )
    sections = {s["chart"]: s for s in payload["sections"]}
    assert "On-Chain Bottom Signals" in sections
    metrics = sections["On-Chain Bottom Signals"]["metrics"]
    assert metrics["composite_score"] == 55.0
    assert metrics["zone"] == "Watch"
    assert metrics["s5"] == 20.0


def test_bottom_signals_deterministic_summaries():
    from whenshouldubuybitcoin.daily_report import (
        _deterministic_en_summary,
        _deterministic_zh_summary,
    )

    snapshot = _bottom_signals_snapshot()
    section = {
        "chart": "On-Chain Bottom Signals",
        "metrics": {
            "composite_score": snapshot["composite"],
            "zone": snapshot["zone"],
            "s1": 4.2, "s2": 14.2, "s3": 7.1, "s4": 10.0, "s5": 20.0,
            "mvrv": 1.18,
            "supply_loss_pct": 20.6,
        },
    }
    en = _deterministic_en_summary(section)
    assert "55" in en and "Watch" in en
    zh = _deterministic_zh_summary(section)
    assert "55" in zh and "观望" in zh
```

Ensure the test file imports `numpy as np`, `pandas as pd`, and `build_report_payload` (add them if its existing imports differ).

- [ ] **Step 11.2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_daily_report.py -v -k bottom_signals`
Expected: FAIL (`unexpected keyword argument 'bottom_signals_snapshot'`)

- [ ] **Step 11.3: Implement**

(a) Add the parameter to `build_report_payload` (~line 157) and `generate_daily_report` (~line 1025), mirroring `free_signal_snapshot`:

```python
    bottom_signals_snapshot: dict[str, Any] | None = None,
```

and in `generate_daily_report`, forward it to `build_report_payload(...)`:

```python
        bottom_signals_snapshot=bottom_signals_snapshot,
```

(b) In `build_report_payload`, after the Futures OI section block (search for `"chart": "Futures OI & Price"` and place this after that block's end, before the payload is assembled):

```python
    if bottom_signals_snapshot:
        metrics: dict[str, Any] = {
            "composite_score": _safe_float(bottom_signals_snapshot.get("composite")),
            "zone": bottom_signals_snapshot.get("zone"),
            "advice": bottom_signals_snapshot.get("advice"),
            "mvrv": _safe_float(bottom_signals_snapshot.get("mvrv")),
            "supply_loss_pct": _safe_float(bottom_signals_snapshot.get("supply_loss_pct")),
            "realized_cap_change_30d_usd": _safe_float(
                bottom_signals_snapshot.get("realized_cap_change_30d_usd")
            ),
            "fear_greed": _safe_float(bottom_signals_snapshot.get("fear_greed")),
        }
        for sig in bottom_signals_snapshot.get("signals", []):
            key = sig.get("key")
            if key:
                metrics[key] = _safe_float(sig.get("score"))
        sections.append({"chart": "On-Chain Bottom Signals", "metrics": metrics})
```

(Adapt the list variable name to whatever `build_report_payload` actually appends sections to — read the surrounding code first; if sections are accumulated as `sections.append(...)` this drops in directly.)

(c) In `_deterministic_en_summary`, before the final fallback `return`:

```python
    if chart == "On-Chain Bottom Signals":
        comp = _safe_float(m.get("composite_score"))
        if comp is None:
            return "On-chain bottom-signal data is unavailable in the current daily snapshot."
        zone = str(m.get("zone") or "Watch")

        def _s(key: str) -> str:
            v = _safe_float(m.get(key))
            return f"{v:.0f}" if v is not None else "N/A"

        mvrv = _safe_float(m.get("mvrv"))
        loss = _safe_float(m.get("supply_loss_pct"))
        tail = ""
        if mvrv is not None and loss is not None:
            tail = (
                f" MVRV is {mvrv:.2f} and about {loss:.1f}% of circulating supply"
                " sits in unrealized loss."
            )
        return (
            f"The on-chain bottom composite scores {comp:.0f}/100, in the {zone} zone."
            f" Per-signal scores out of 20: holder cost {_s('s1')}, MVRV {_s('s2')},"
            f" supply-in-loss {_s('s3')}, capital flow {_s('s4')}, fear&greed {_s('s5')}."
            + tail
        )
```

(d) In `_deterministic_zh_summary`, before its final fallback `return`:

```python
    if chart == "On-Chain Bottom Signals":
        comp = _safe_float(m.get("composite_score"))
        if comp is None:
            return "今日链上底部信号数据不可用。"
        zone_map = {
            "Watch": "观望区",
            "Mildly Undervalued": "偏低估区",
            "Undervalued": "低估区",
            "Extremely Undervalued": "极度低估区",
        }
        zone = zone_map.get(str(m.get("zone")), "观望区")

        def _s(key: str) -> str:
            v = _safe_float(m.get(key))
            return f"{v:.0f}" if v is not None else "暂缺"

        mvrv = _safe_float(m.get("mvrv"))
        loss = _safe_float(m.get("supply_loss_pct"))
        tail = ""
        if mvrv is not None and loss is not None:
            tail = f"当前 MVRV {mvrv:.2f}，约 {loss:.1f}% 的流通供应处于浮亏。"
        return (
            f"链上底部综合评分 {comp:.0f}/100，处于{zone}。"
            f"五项信号得分（每项满分 20）：持有者成本 {_s('s1')}、MVRV {_s('s2')}、"
            f"亏损供应 {_s('s3')}、资金流向 {_s('s4')}、恐慌贪婪 {_s('s5')}。"
            + tail
        )
```

- [ ] **Step 11.4: Run the tests**

Run: `poetry run pytest tests/test_daily_report.py -v`
Expected: all PASS (new and pre-existing)

- [ ] **Step 11.5: Run the full pipeline end-to-end**

Run: `poetry run python main.py`
Expected:
- "GENERATING ON-CHAIN BOTTOM SIGNALS" prints "✓ On-chain metrics are fresh; skipping API calls" (Task 9 seeded today's window — zero requests spent) or fetches at most 6 calls;
- `✓ Bottom signals: composite NN (Zone)` — **acceptance check:** composite ≈ 45-65 with S5 = 20, S2 ≈ 12-16, S1 ≤ 6 (same ordering as a third-party dashboard showed on 2026-06-08: S1 4.2, S2 14.2, S3 7.1, S4 10, S5 20, total 55);
- `docs/charts/bottom_signals.html` and `docs/charts/bottom_signals_info.json` exist;
- `daily_report.json` contains an "On-Chain Bottom Signals" section;
- component status shows `✓ bottom_signals`.

If composite lands far outside 45-65, debug the scoring inputs (units! check `supply_loss_pct` and `realized_cap_change_30d_usd` normalization against Step 1.3 notes) before proceeding.

- [ ] **Step 11.6: Commit**

```bash
git add main.py src/whenshouldubuybitcoin/daily_report.py tests/test_daily_report.py docs/data/ docs/charts/bottom_signals.html docs/charts/bottom_signals_info.json
git commit -m "feat: wire bottom signals into pipeline and daily report"
```

---

### Task 12: index.html summary card

**Files:**
- Modify: `docs/index.html` — CSS (insert before `.daily-report-card {`, ~line 138), HTML (insert after the daily-report-card's closing `</div>`, immediately before `<div class="chart-container">` ~line 1547), JS (insert next to `function updateOIQuadrantLegend()` ~line 3042 and its call ~line 3122)

- [ ] **Step 12.1: Add the CSS** (immediately before the `.daily-report-card {` rule):

```css
        .bottom-signals-card { display:flex; align-items:center; gap:16px; background:white; border-radius:18px; padding:18px 24px; margin-bottom:20px; box-shadow:0 2px 8px rgba(0,0,0,0.06); text-decoration:none; color:#1d1d1f; transition:box-shadow .2s; }
        .bottom-signals-card:hover { box-shadow:0 4px 16px rgba(0,0,0,0.10); }
        .bsc-main { flex:1; min-width:0; }
        .bsc-title { font-weight:600; font-size:1.05em; }
        .bsc-meta { color:#86868b; font-size:0.85em; margin-top:2px; }
        .bsc-score-wrap { display:flex; align-items:baseline; gap:6px; white-space:nowrap; }
        .bsc-score { font-size:1.9em; font-weight:700; }
        .bsc-score-max { color:#86868b; font-size:0.9em; }
        .bsc-zone { font-size:0.8em; font-weight:600; padding:4px 10px; border-radius:999px; background:rgba(0,0,0,0.05); }
        .bsc-arrow { color:#86868b; font-size:1.4em; }
        @media (max-width:600px){ .bottom-signals-card{ padding:14px 16px; gap:10px; flex-wrap:wrap; } .bsc-score{ font-size:1.5em; } }
```

- [ ] **Step 12.2: Add the card HTML** (between the daily-report-card's closing `</div>` and `<div class="chart-container">`):

```html
            <a id="bottomSignalsCard" class="bottom-signals-card" href="charts/bottom_signals.html" style="display:none;">
                <div class="bsc-main">
                    <div class="bsc-title">⛓️ On-Chain Bottom Signals</div>
                    <div class="bsc-meta" id="bscMeta">—</div>
                </div>
                <div class="bsc-score-wrap">
                    <span class="bsc-score" id="bscScore">–</span>
                    <span class="bsc-score-max">/100</span>
                    <span class="bsc-zone" id="bscZone">–</span>
                </div>
                <div class="bsc-arrow">›</div>
            </a>
```

- [ ] **Step 12.3: Add the JS** (immediately before `function updateOIQuadrantLegend() {`):

```javascript
        // Populate the On-Chain Bottom Signals summary card from the generated info JSON
        function updateBottomSignalsCard() {
            fetch('charts/bottom_signals_info.json')
                .then(r => r.ok ? r.json() : null)
                .then(data => {
                    if (!data || typeof data.composite !== 'number') return;
                    const card = document.getElementById('bottomSignalsCard');
                    if (!card) return;
                    const scoreEl = document.getElementById('bscScore');
                    scoreEl.textContent = Math.round(data.composite);
                    scoreEl.style.color = data.zone_color || '#1d1d1f';
                    const zoneEl = document.getElementById('bscZone');
                    zoneEl.textContent = data.zone || '';
                    zoneEl.style.color = data.zone_color || '#1d1d1f';
                    const parts = (data.signals || []).map(
                        s => s.key.toUpperCase() + ' ' + Math.round(s.score)
                    );
                    document.getElementById('bscMeta').textContent =
                        (data.date ? 'Data ' + data.date + ' · ' : '') + parts.join(' · ');
                    card.style.display = 'flex';
                })
                .catch(() => {});
        }

```

And next to the `updateOIQuadrantLegend();` call (~line 3122), add:

```javascript
        updateBottomSignalsCard();
```

- [ ] **Step 12.4: Browser verification (AGENTS.md requirement — desktop + mobile)**

Serve the site and verify in a real browser (use the webapp-testing skill / Playwright):

```bash
cd docs && python3 -m http.server 8765
```

Desktop (1280px) and mobile (390px) checks, with screenshots:
1. `http://localhost:8765/index.html` — summary card visible under Daily Summary with score, zone chip, five `S1..S5` mini-scores; clicking navigates to the dashboard.
2. `http://localhost:8765/charts/bottom_signals.html` — gauge renders with needle and zone chip; 6 cards (5 signals + MA) with score bars, scale markers, sparklines; main Plotly chart renders with green shading + red dotted cycle-bottom lines; threshold/duration toggles update shading, caption, and the segment table; accuracy matrix populated; no JS console errors; mobile layout single-column without horizontal overflow (tables scroll inside `.table-scroll`).

- [ ] **Step 12.5: Commit**

```bash
git add docs/index.html
git commit -m "feat: add on-chain bottom signals summary card to dashboard"
```

---

### Task 13: Final verification

- [ ] **Step 13.1: Full test suites**

Run: `poetry run pytest tests/ -v` — Expected: all PASS, no regressions.
Run: `npm test` — Expected: existing JS tests still PASS (nothing in `backtest.js` was touched).

- [ ] **Step 13.2: Re-run the pipeline once more**

Run: `poetry run python main.py`
Expected: freshness guard skips API calls; all component statuses `✓`; regenerated artifacts are stable (no churn beyond timestamps).

- [ ] **Step 13.3: Acceptance summary against the reference site**

Record in the final commit/PR description: today's composite, per-signal scores, and zone, side-by-side with a third-party dashboard's same-day values (expected: same zone and same per-signal ordering; exact numbers differ by design for S3/S4 — substituted metric and percentile scoring).

- [ ] **Step 13.4: Pre-merge housekeeping per AGENTS.md**

The wealth-distribution refresh runs inside `main.py` (Step 7) — confirm its `✓` in the Step 13.2 output. Then use the superpowers:finishing-a-development-branch skill (merge/PR decision belongs to the user).
```
