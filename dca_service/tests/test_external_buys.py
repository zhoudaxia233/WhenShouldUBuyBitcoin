"""
External buys: BTC bought on other exchanges (Kraken Pro, Bitvavo) and entered by hand.

They are read-only history: never ordered, never synced, never counted against the
DCA budget, but included in holdings, cost basis and the stats.
"""
import csv
import io
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from dca_service.models import DCATransaction, ExternalTrade, GlobalSettings, VenueBalance
from dca_service.services import fx_rates, market_history
from dca_service.services.fx_rates import FxRate, FxUnavailable
from dca_service.services.market_history import MarketDay


KRAKEN_BUY = {
    "venue": "Kraken Pro",
    "timestamp": "2025-11-12T13:32:00Z",
    "quote_currency": "EUR",
    "quote_amount": 500.0,
    "btc_amount": 0.005618,
    "fee_amount": 1.30,
    "fee_currency": "EUR",
    "venue_trade_id": "TXQ4ZB-7KD2M-ERN5PA",
    "adjust_balance": True,
}


@pytest.fixture(autouse=True)
def fixed_market_data(monkeypatch):
    calls = []

    def fake_rate(day: date) -> FxRate:
        calls.append(day)
        return FxRate(rate=1.1612, date="2025-11-12")

    monkeypatch.setattr(fx_rates, "eur_usd_rate", fake_rate)
    monkeypatch.setattr(
        market_history,
        "market_day",
        lambda day: MarketDay(close_price=103200.0, ahr999=0.82),
    )
    monkeypatch.setattr(
        "whenshouldubuybitcoin.data_fetcher.get_realtime_btc_price",
        lambda: (datetime.now(timezone.utc), 110000.0),
    )
    return calls


def _add(client: TestClient, **overrides):
    return client.post("/api/external-buys", json={**KRAKEN_BUY, **overrides})


def _binance_buy(session: Session, usd: float, btc: float, **kwargs):
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=usd,
        btc_amount=btc,
        price=usd / btc,
        ahr999=0.9,
        source=kwargs.pop("source", "DCA"),
        timestamp=kwargs.pop("timestamp", datetime(2026, 9, 1, tzinfo=timezone.utc)),
        **kwargs,
    )
    session.add(tx)
    session.commit()
    return tx


# --- recording a buy -------------------------------------------------------

def test_eur_buy_is_stored_with_trade_day_rate_and_ahr999(client, session, fixed_market_data):
    response = _add(client)

    assert response.status_code == 201
    body = response.json()
    assert body["venue"] == "Kraken Pro"
    assert body["usd_amount"] == pytest.approx(580.60)
    assert body["fee_usd"] == pytest.approx(1.30 * 1.1612)
    assert body["fx_rate_usd"] == 1.1612
    assert body["fx_date"] == "2025-11-12"
    assert fixed_market_data == [date(2025, 11, 12)]

    stored = session.exec(select(ExternalTrade)).one()
    assert stored.ahr999 == 0.82
    assert stored.quote_amount == 500.0


def test_usd_buy_needs_no_exchange_rate(client, fixed_market_data):
    body = _add(client, quote_currency="USDC", quote_amount=600.0, fee_currency="USDC").json()

    assert body["usd_amount"] == 600.0
    assert body["fx_rate_usd"] == 1.0
    assert body["fx_date"] is None
    assert fixed_market_data == []


def test_buy_adds_btc_to_venue_balance_when_asked(client, session):
    _add(client)
    _add(client, venue_trade_id="SECOND", btc_amount=0.001, adjust_balance=False)

    balance = session.get(VenueBalance, "Kraken Pro")
    assert balance.btc == pytest.approx(0.005618)


def test_same_trade_reference_is_rejected(client):
    assert _add(client).status_code == 201

    response = _add(client)

    assert response.status_code == 409
    assert "already" in response.json()["detail"]


def test_same_time_and_amount_without_reference_is_rejected(client):
    assert _add(client, venue_trade_id=None).status_code == 201

    response = _add(client, venue_trade_id="  ")

    assert response.status_code == 409


@pytest.mark.parametrize(
    "overrides",
    [
        {"venue": "Binance"},
        {"venue": "  "},
        {"quote_amount": 0},
        {"btc_amount": -1},
        {"quote_currency": "GBP"},
        {"fee_currency": "BNB"},
        {"fee_amount": -0.5},
    ],
)
def test_invalid_buys_are_rejected(client, overrides):
    response = _add(client, **overrides)

    assert response.status_code == 422


def test_unavailable_exchange_rate_gives_a_plain_message(client, monkeypatch):
    def broken(day):
        raise FxUnavailable("ECB down: ConnectError https://api.frankfurter.dev")

    monkeypatch.setattr(fx_rates, "eur_usd_rate", broken)

    response = _add(client)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "exchange rate" in detail
    assert "frankfurter" not in detail
    assert "ConnectError" not in detail


def test_preview_checks_price_against_that_day(client):
    ok = client.post("/api/external-buys/preview", json=KRAKEN_BUY).json()
    assert ok["price_quote"] == pytest.approx(500.0 / 0.005618)
    assert ok["price_usd"] == pytest.approx(580.60 / 0.005618)
    assert ok["day_close_usd"] == 103200.0
    assert ok["ahr999"] == 0.82
    assert ok["price_warning"] is False

    typo = client.post(
        "/api/external-buys/preview", json={**KRAKEN_BUY, "btc_amount": 0.0005618}
    ).json()
    assert typo["price_warning"] is True


# --- editing and deleting --------------------------------------------------

def test_edit_applies_btc_difference_to_balance(client, session):
    trade_id = _add(client).json()["id"]

    response = client.put(
        f"/api/external-buys/{trade_id}", json={**KRAKEN_BUY, "btc_amount": 0.006}
    )

    assert response.status_code == 200
    assert response.json()["btc_amount"] == 0.006
    assert session.get(VenueBalance, "Kraken Pro").btc == pytest.approx(0.006)


def test_delete_can_leave_balance_untouched(client, session):
    trade_id = _add(client).json()["id"]

    response = client.delete(f"/api/external-buys/{trade_id}?adjust_balance=false")

    assert response.status_code == 204
    assert session.exec(select(ExternalTrade)).all() == []
    assert session.get(VenueBalance, "Kraken Pro").btc == pytest.approx(0.005618)


def test_delete_subtracts_from_balance_but_not_below_zero(client, session):
    trade_id = _add(client).json()["id"]
    client.put("/api/wallet/venue-balances/Kraken Pro", json={"btc": 0.001})

    client.delete(f"/api/external-buys/{trade_id}")

    assert session.get(VenueBalance, "Kraken Pro").btc == 0.0


# --- isolation from Binance and DCA ---------------------------------------

def test_binance_resync_keeps_external_buys(client, session):
    _add(client)

    with patch(
        "dca_service.services.sync_service.TradeSyncService.sync_trades",
        new=AsyncMock(return_value=0),
    ):
        response = client.post("/api/transactions/clear-simulated")

    assert response.status_code == 200
    assert len(session.exec(select(ExternalTrade)).all()) == 1


def test_external_buys_do_not_use_dca_budget(client, session):
    # The DCA engine sums dca_transactions for the monthly budget; external buys
    # must never land there.
    _add(client, timestamp=datetime.now(timezone.utc).isoformat())

    assert session.exec(select(DCATransaction)).all() == []


# --- where they show up ----------------------------------------------------

def test_transaction_list_mixes_external_buys_by_time(client, session):
    _binance_buy(session, 250.0, 0.0025)
    _add(client)

    rows = client.get("/api/transactions").json()

    assert [r["source"] for r in rows] == ["DCA", "EXTERNAL"]
    external = rows[1]
    assert external["venue"] == "Kraken Pro"
    assert external["external_id"] is not None
    assert external["fiat_amount"] == pytest.approx(580.60)
    assert external["quote_currency"] == "EUR"
    assert external["quote_amount"] == 500.0
    assert external["fx_rate_usd"] == 1.1612
    assert external["fee_usd"] == pytest.approx(1.30 * 1.1612)
    assert external["ahr999"] == 0.82
    assert rows[0]["venue"] == "Binance"


def test_pnl_includes_external_buys(client, session):
    _binance_buy(session, 1000.0, 0.02)
    _add(client)

    data = client.get("/api/stats/pnl").json()

    assert data["invested"][-1] == pytest.approx(1580.60)
    assert data["btc_balance"][-1] == pytest.approx(0.025618)
    assert data["dates"][0].startswith("2025-11-12")


def test_fees_include_external_buys(client, session):
    _binance_buy(session, 1000.0, 0.02, fee_amount=1.0, fee_asset="USDC")
    _add(client)

    data = client.get("/api/stats/fees").json()

    assert data["total_fees_usd"] == pytest.approx(1.0 + 1.30 * 1.1612)
    assert data["transaction_count"] == 2
    assert data["external_count"] == 1


def test_wallet_counts_venue_balances_and_blends_cost_basis(client, session):
    settings = session.get(GlobalSettings, 1)
    settings.cold_wallet_balance = 0.1
    session.add(settings)
    session.commit()
    _add(client)

    data = client.get("/api/wallet/summary").json()

    assert data["total_btc"] == pytest.approx(0.105618)
    assert data["venue_balances"] == [{"venue": "Kraken Pro", "btc": pytest.approx(0.005618)}]
    # No Binance connection, so the blended cost basis is the external buy alone.
    assert data["avg_buy_price"] == pytest.approx(580.60 / 0.005618)
    assert data["external_buy_count"] == 1


def test_blended_cost_basis_weights_binance_and_external_buys(client, session):
    from dca_service.api import wallet_api

    _add(client)
    client_mock = AsyncMock()
    client_mock.get_spot_balances.return_value = {"BTC": 0.04}
    client_mock.get_current_price.return_value = 110000.0
    client_mock.calculate_buy_cost_basis.return_value = {
        "avg_price": 50000.0,
        "total_btc": 0.04,
        "total_cost": 2000.0,
    }
    with patch.object(wallet_api, "_get_binance_client", return_value=client_mock):
        data = client.get("/api/wallet/summary").json()

    assert data["hot_wallet_avg_price"] == 50000.0
    assert data["avg_buy_price"] == pytest.approx((2000.0 + 580.60) / (0.04 + 0.005618))


def test_venue_balance_can_be_set_by_hand(client, session):
    response = client.put("/api/wallet/venue-balances/Bitvavo", json={"btc": 0.01})

    assert response.status_code == 200
    assert session.get(VenueBalance, "Bitvavo").btc == 0.01
    assert client.put("/api/wallet/venue-balances/Bitvavo", json={"btc": -1}).status_code == 422


def test_purchase_csv_names_the_venue_and_original_currency(client, session):
    _binance_buy(session, 250.0, 0.0025)
    _add(client)

    response = client.get("/api/stats/trading-style.csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))

    kraken = rows[0]
    assert kraken["venue"] == "Kraken Pro"
    assert kraken["purchase_type"] == "ACTIVE_BUY"
    assert kraken["quote_currency"] == "EUR"
    assert float(kraken["quote_amount"]) == 500.0
    assert float(kraken["fx_rate_usd"]) == 1.1612
    assert kraken["fx_date"] == "2025-11-12"
    assert rows[1]["venue"] == "Binance"
    assert rows[1]["fx_rate_usd"] == ""


def test_trading_style_counts_external_buy_as_manual(client, session):
    _binance_buy(session, 250.0, 0.0025)
    _add(client)

    from dca_service.api.stats_api import _build_buy_behavior_snapshot

    buys, meta, _, _ = _build_buy_behavior_snapshot(session)

    assert meta["event_count"] == 2
    assert meta["events"][0]["source_types"] == ["MANUAL"]


def test_dca_email_total_includes_venue_balances(client, session):
    from dca_service.services.mailer import _get_total_btc_balance

    client.put("/api/wallet/venue-balances/Kraken Pro", json={"btc": 0.005})

    assert _get_total_btc_balance(session) == pytest.approx(0.005)


def test_binance_holdings_total_includes_venue_balances(client, session):
    from dca_service.models import BinanceCredentials
    from dca_service.services.security import encrypt_text

    session.add(BinanceCredentials(
        credential_type="READ_ONLY",
        api_key_encrypted=encrypt_text("k"),
        api_secret_encrypted=encrypt_text("s"),
    ))
    session.commit()
    client.put("/api/wallet/venue-balances/Kraken Pro", json={"btc": 0.005})

    with patch(
        "dca_service.api.binance_api.BinanceClient.get_spot_balances",
        new=AsyncMock(return_value={"BTC": 0.01, "USDC": 50.0}),
    ):
        data = client.get("/api/binance/holdings").json()

    assert data["btc_balance"] == pytest.approx(0.015)
    assert data["binance_btc_balance"] == 0.01


def test_cost_basis_is_left_blank_when_binance_fails(client, session):
    from dca_service.api import wallet_api

    _add(client)
    client_mock = AsyncMock()
    client_mock.get_spot_balances.side_effect = RuntimeError("timeout")
    with patch.object(wallet_api, "_get_binance_client", return_value=client_mock):
        data = client.get("/api/wallet/summary").json()

    # Blending only the external buy would show a misleading cost basis.
    assert data["avg_buy_price"] == 0.0
    assert data["total_btc"] == pytest.approx(0.005618)
