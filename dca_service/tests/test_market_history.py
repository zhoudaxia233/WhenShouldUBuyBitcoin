from datetime import date

from dca_service.services import market_history


def test_market_day_reads_close_and_ahr999(tmp_path, monkeypatch):
    csv_path = tmp_path / "btc_metrics.csv"
    csv_path.write_text(
        "date,close_price,ahr999\n"
        "2025-11-12,103200.5,0.82\n"
        "2025-11-13,101000,\n"
    )
    monkeypatch.setattr(market_history, "resolve_metrics_csv_path", lambda: csv_path)

    assert market_history.market_day(date(2025, 11, 12)) == market_history.MarketDay(103200.5, 0.82)
    assert market_history.market_day(date(2025, 11, 13)).ahr999 is None
    assert market_history.market_day(date(2025, 11, 14)) is None


def test_missing_csv_means_no_market_data(tmp_path, monkeypatch):
    monkeypatch.setattr(market_history, "resolve_metrics_csv_path", lambda: tmp_path / "missing.csv")

    assert market_history.market_day(date(2025, 11, 12)) is None
