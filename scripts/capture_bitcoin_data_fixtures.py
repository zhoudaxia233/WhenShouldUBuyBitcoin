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
    "supply_loss_pct": "/v1/supply-loss",
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
