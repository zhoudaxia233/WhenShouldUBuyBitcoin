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
