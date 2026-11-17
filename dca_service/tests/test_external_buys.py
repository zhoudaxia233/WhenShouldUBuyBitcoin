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


@pytest.mark.parametrize(
    "deviation, warned",
    [(0.053, False), (-0.08, False), (0.12, True), (-0.12, True)],
)
def test_preview_warns_only_beyond_ten_percent(client, deviation, warned):
    # A buy at the day's high or low, plus the exchange's spread, is often 5% off the close.
    btc_amount = 580.60 / (103200.0 * (1 + deviation))

    body = client.post(
        "/api/external-buys/preview", json={**KRAKEN_BUY, "btc_amount": btc_amount}
    ).json()

    assert body["price_deviation"] == pytest.approx(deviation)
    assert body["price_warning"] is warned


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
    assert external["venue_trade_id"] == "TXQ4ZB-7KD2M-ERN5PA"
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
    assert [(b["venue"], b["btc"]) for b in data["venue_balances"]] == [("Kraken Pro", pytest.approx(0.005618))]
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


# --- moving bitcoin from an exchange to cold storage -----------------------
#
# The owner buys on an exchange and later withdraws to a hardware wallet. One
# call moves the BTC: the exchange balance and cold storage change together, so
# it is never counted twice or not at all, and the buy history stays as it was.

def _move(client: TestClient, venue: str = "Kraken Pro", **body):
    return client.post(f"/api/wallet/venue-balances/{venue}/move-to-cold", json=body)


def _cold(session: Session, balance: float, source=None, keys: bool = False):
    from dca_service.services.security import encrypt_text

    settings = session.get(GlobalSettings, 1)
    settings.cold_wallet_balance = balance
    settings.cold_wallet_source = source
    settings.cold_wallet_keys_encrypted = encrypt_text('["zpub-test"]') if keys else None
    session.add(settings)
    session.commit()


def _detail(response) -> str:
    detail = response.json()["detail"]
    return detail if isinstance(detail, str) else " ".join(d["msg"] for d in detail)


def test_move_everything_to_cold_storage_typed_by_hand(client, session):
    _add(client)  # Kraken Pro holds 0.005618
    _cold(session, 0.1, source="manual")

    response = _move(client, left_btc=0, arrived_btc=0.0056)

    assert response.status_code == 200
    session.expire_all()
    assert session.get(VenueBalance, "Kraken Pro").btc == 0
    settings = session.get(GlobalSettings, 1)
    assert settings.cold_wallet_balance == pytest.approx(0.1056)
    assert settings.cold_wallet_source == "manual"
    data = response.json()
    assert data["cold_wallet_balance"] == pytest.approx(0.1056)
    # Only the withdrawal fee left the total.
    assert data["total_btc"] == pytest.approx(0.1056)


def test_partial_move_leaves_the_rest_on_the_exchange(client, session):
    _add(client)
    _cold(session, 0.1, source=None)  # saved before the source was recorded, no key

    response = _move(client, left_btc=0.002, arrived_btc=0.0036)

    assert response.status_code == 200
    data = response.json()
    assert data["venue_balances"][0]["btc"] == pytest.approx(0.002)
    assert data["cold_wallet_balance"] == pytest.approx(0.1036)
    assert data["cold_wallet_source"] == "manual"
    assert data["total_btc"] == pytest.approx(0.1056)


def test_move_leaves_the_buy_history_untouched(client, session):
    _add(client)
    before = client.get("/api/transactions").json()
    pnl_before = client.get("/api/stats/pnl").json()

    assert _move(client, left_btc=0, arrived_btc=0.0056).status_code == 200

    trades = session.exec(select(ExternalTrade)).all()
    assert len(trades) == 1
    assert trades[0].btc_amount == pytest.approx(0.005618)
    assert client.get("/api/transactions").json() == before
    data = client.get("/api/wallet/summary").json()
    assert data["external_buy_count"] == 1
    assert data["avg_buy_price"] == pytest.approx(580.60 / 0.005618)
    assert client.get("/api/stats/pnl").json() == pnl_before


def test_key_tracked_cold_storage_changes_only_the_exchange(client, session):
    _add(client)
    _cold(session, 0.1, source="public_key", keys=True)

    response = _move(client, left_btc=0, arrived_btc=None)

    assert response.status_code == 200
    session.expire_all()
    assert session.get(VenueBalance, "Kraken Pro").btc == 0
    settings = session.get(GlobalSettings, 1)
    # The browser reads the key again right after; nothing is added by hand.
    assert settings.cold_wallet_balance == pytest.approx(0.1)
    assert settings.cold_wallet_source == "public_key"


def test_key_with_unknown_source_counts_as_tracked(client, session):
    _add(client)
    _cold(session, 0.1, source=None, keys=True)

    assert _move(client, left_btc=0, arrived_btc=None).status_code == 200
    assert _move(client, venue="Kraken Pro", left_btc=0, arrived_btc=0.001).status_code == 422


def test_key_tracked_cold_storage_refuses_an_amount_typed_by_hand(client, session):
    _add(client)
    _cold(session, 0.1, source="public_key", keys=True)

    response = _move(client, left_btc=0, arrived_btc=0.0056)

    assert response.status_code == 422
    assert "public key" in _detail(response)
    session.expire_all()
    assert session.get(VenueBalance, "Kraken Pro").btc == pytest.approx(0.005618)
    assert session.get(GlobalSettings, 1).cold_wallet_balance == pytest.approx(0.1)


@pytest.mark.parametrize(
    "source, keys",
    [("manual", False), (None, False), ("manual", True), ("public_key", False)],
)
def test_cold_storage_without_a_key_sync_needs_the_arrived_amount(client, session, source, keys):
    # A key saved but a balance typed after it (paused), or a synced balance
    # whose key was removed: nothing will read the wallet, so the amount is needed.
    _add(client)
    _cold(session, 0.1, source=source, keys=keys)

    response = _move(client, left_btc=0, arrived_btc=None)

    assert response.status_code == 422
    assert "Enter what arrived" in _detail(response)
    session.expire_all()
    assert session.get(VenueBalance, "Kraken Pro").btc == pytest.approx(0.005618)


@pytest.mark.parametrize(
    "body, message",
    [
        ({"left_btc": 0.005618, "arrived_btc": 0.001}, "less than"),
        ({"left_btc": 0.01, "arrived_btc": 0.001}, "less than"),
        ({"left_btc": -0.001, "arrived_btc": 0.001}, ""),
        ({"left_btc": 0, "arrived_btc": 0}, "more than 0"),
        ({"left_btc": 0, "arrived_btc": -0.001}, "more than 0"),
        ({"left_btc": 0.002, "arrived_btc": 0.004}, "more than left"),
    ],
)
def test_invalid_moves_are_refused_with_a_plain_message(client, session, body, message):
    _add(client)
    _cold(session, 0.1, source="manual")

    response = _move(client, **body)

    assert response.status_code == 422
    assert message in _detail(response)
    assert "Traceback" not in response.text
    session.expire_all()
    assert session.get(VenueBalance, "Kraken Pro").btc == pytest.approx(0.005618)
    assert session.get(GlobalSettings, 1).cold_wallet_balance == pytest.approx(0.1)


def test_arrived_may_equal_what_left_the_exchange(client, session):
    # Some exchanges take the fee from the balance instead of the withdrawal.
    _add(client)
    _cold(session, 0, source="manual")

    response = _move(client, left_btc=0.000618, arrived_btc=0.005)

    assert response.status_code == 200
    assert response.json()["cold_wallet_balance"] == pytest.approx(0.005)


@pytest.mark.parametrize("venue", ["Bitvavo", "Binance"])
def test_move_needs_bitcoin_on_that_exchange(client, session, venue):
    _add(client)
    _cold(session, 0.1, source="manual")

    response = _move(client, venue=venue, left_btc=0, arrived_btc=0.001)

    assert response.status_code == 422
    assert session.get(GlobalSettings, 1).cold_wallet_balance == pytest.approx(0.1)


def test_move_requires_login(session):
    from dca_service.main import app
    from dca_service.database import get_session

    app.dependency_overrides[get_session] = lambda: session
    try:
        response = TestClient(app).post(
            "/api/wallet/venue-balances/Kraken Pro/move-to-cold",
            json={"left_btc": 0, "arrived_btc": 0.001},
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code in (303, 401)


# --- an emptied exchange stays listed -------------------------------------

def test_emptied_exchange_with_buys_stays_listed_with_the_time(client, session):
    _add(client)
    _cold(session, 0.1, source="manual")
    _move(client, left_btc=0, arrived_btc=0.0056)
    client.put("/api/wallet/venue-balances/Bitvavo", json={"btc": 0})  # no buys there

    data = client.get("/api/wallet/summary").json()

    assert [b["venue"] for b in data["venue_balances"]] == ["Kraken Pro"]
    row = data["venue_balances"][0]
    assert row["btc"] == 0
    assert datetime.fromisoformat(row["updated_at"]).tzinfo is not None
    assert data["total_btc"] == pytest.approx(0.1056)


def test_exchange_with_bitcoin_but_no_buys_is_listed(client, session):
    client.put("/api/wallet/venue-balances/Bitvavo", json={"btc": 0.01})

    data = client.get("/api/wallet/summary").json()

    assert [(b["venue"], b["btc"]) for b in data["venue_balances"]] == [("Bitvavo", 0.01)]
    assert data["total_btc"] == pytest.approx(0.01)


def test_totals_elsewhere_ignore_emptied_exchanges(client, session):
    from dca_service.services.mailer import _get_total_btc_balance

    _add(client)
    _cold(session, 0.1, source="manual")
    _move(client, left_btc=0, arrived_btc=0.0056)

    assert _get_total_btc_balance(session) == pytest.approx(0.1056)
