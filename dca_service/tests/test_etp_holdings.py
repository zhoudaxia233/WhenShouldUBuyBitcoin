"""
Bitcoin ETP holdings (IB1T): the owner enters the shares, the average price per
share and the yearly fee. The app works out the bitcoin behind the shares and
counts it with the other holdings. There is no trade date, so it stays out of
the buy history.
"""
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from sqlmodel import select

from dca_service.models import EtpHolding, GlobalSettings
from dca_service.services import etp_holdings, fx_rates, market_history
from dca_service.services.fx_rates import FxRate, FxUnavailable

TODAY = date(2026, 11, 10)
IB1T_INPUT = {"shares": 500.123456, "avg_price_eur": 7.1234, "fee_percent": 0.15}
# The iShares fact sheet gives 0.000099758 BTC per share on 6 Nov 2026, four days
# before TODAY; each day takes that day's share of the yearly fee off it.
BTC_PER_SHARE = 0.000099758 * (1 - 0.0015 / 365) ** 4
BTC = 500.123456 * BTC_PER_SHARE
COST_USD = 500.123456 * 7.1234 * 1.16


@pytest.fixture(autouse=True)
def fixed_day_and_rates(monkeypatch):
    calls = []

    def fake_rate(day: date) -> FxRate:
        calls.append(day)
        return FxRate(rate=1.16, date="2026-11-10")

    monkeypatch.setattr(fx_rates, "eur_usd_rate", fake_rate)
    monkeypatch.setattr(market_history, "close_range", lambda since: (74000.0, 126000.0))
    monkeypatch.setattr(
        "whenshouldubuybitcoin.data_fetcher.get_realtime_btc_price",
        lambda: (datetime.now(timezone.utc), 74000.0),
    )
    with freeze_time("2026-11-10 12:00:00", tz_offset=0):
        yield calls


def _save(client, **overrides):
    return client.put("/api/etp-holdings/IB1T", json={**IB1T_INPUT, **overrides})


# --- bitcoin per share -----------------------------------------------------

def test_btc_per_share_starts_at_the_ishares_figure_and_shrinks_by_the_fee():
    ib1t = etp_holdings.PRODUCTS["IB1T"]

    assert etp_holdings.btc_per_share(ib1t, 0.15, date(2026, 11, 6)) == 0.000099758
    assert etp_holdings.btc_per_share(ib1t, 0.15, TODAY) == pytest.approx(BTC_PER_SHARE, rel=1e-12)
    assert etp_holdings.btc_per_share(ib1t, 0.25, date(2027, 11, 6)) == pytest.approx(
        0.000099758 * (1 - 0.0025 / 365) ** 365, rel=1e-12
    )
    assert etp_holdings.btc_per_share(ib1t, 0, TODAY) == 0.000099758
    # Never more than the published figure, even for a day before it.
    assert etp_holdings.btc_per_share(ib1t, 0.15, date(2026, 1, 1)) == 0.000099758


# --- saving the holding ----------------------------------------------------

def test_saving_works_out_the_bitcoin_and_fixes_the_exchange_rate(client, session, fixed_day_and_rates):
    response = _save(client)

    assert response.status_code == 200
    body = response.json()
    assert body["product"] == "IB1T"
    assert body["shares"] == 500.123456
    assert body["avg_price_eur"] == 7.1234
    assert body["fee_percent"] == 0.15
    assert body["btc_per_share"] == pytest.approx(BTC_PER_SHARE, rel=1e-12)
    assert body["btc"] == pytest.approx(BTC, rel=1e-12)
    assert body["cost_eur"] == pytest.approx(500.123456 * 7.1234)
    assert body["cost_usd"] == pytest.approx(COST_USD)
    assert body["fx_rate_usd"] == 1.16
    assert body["fx_date"] == "2026-11-10"
    assert fixed_day_and_rates == [TODAY]

    stored = session.exec(select(EtpHolding)).one()
    assert stored.shares == 500.123456
    assert stored.fee_percent == 0.15


def test_saving_again_replaces_the_holding(client, session):
    _save(client)

    body = _save(client, shares=510.5, avg_price_eur=7.2).json()

    assert body["shares"] == 510.5
    assert body["cost_eur"] == pytest.approx(510.5 * 7.2)
    assert len(session.exec(select(EtpHolding)).all()) == 1


def test_a_new_fee_alone_keeps_the_cost_basis(client, monkeypatch, fixed_day_and_rates):
    _save(client)
    monkeypatch.setattr(fx_rates, "eur_usd_rate", lambda day: FxRate(rate=1.20, date="2027-01-04"))

    # When the fee waiver ends only the fee changes: no money moved, so the
    # cost in USD stays at the rate of the last save.
    fee_only = _save(client, fee_percent=0.25).json()
    assert fee_only["fx_rate_usd"] == 1.16
    assert fee_only["cost_usd"] == pytest.approx(COST_USD)

    # New shares bought: the cost is valued at today's rate.
    more_shares = _save(client, shares=520.0).json()
    assert more_shares["fx_rate_usd"] == 1.20
    assert more_shares["fx_date"] == "2027-01-04"


def test_holding_can_be_read_back_and_deleted(client):
    assert client.get("/api/etp-holdings/IB1T").status_code == 404
    _save(client)

    assert client.get("/api/etp-holdings/IB1T").json()["shares"] == 500.123456
    assert client.delete("/api/etp-holdings/IB1T").status_code == 204
    assert client.get("/api/etp-holdings/IB1T").status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"shares": 0},
        {"shares": -1},
        {"avg_price_eur": 0},
        {"fee_percent": -0.1},
        {"fee_percent": 6},
    ],
)
def test_invalid_holdings_are_rejected(client, overrides):
    assert _save(client, **overrides).status_code == 422


def test_only_known_products_can_be_saved(client):
    assert client.put("/api/etp-holdings/IBIT", json=IB1T_INPUT).status_code == 404


def test_unavailable_exchange_rate_gives_a_plain_message(client, monkeypatch):
    def broken(day):
        raise FxUnavailable("ECB down: ConnectError https://api.frankfurter.dev")

    monkeypatch.setattr(fx_rates, "eur_usd_rate", broken)

    response = _save(client)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "exchange rate" in detail
    assert "frankfurter" not in detail
    assert "ConnectError" not in detail


def test_preview_checks_the_price_against_bitcoin_since_launch(client, session):
    ok = client.post("/api/etp-holdings/IB1T/preview", json=IB1T_INPUT).json()

    assert ok["btc"] == pytest.approx(BTC, rel=1e-12)
    assert ok["cost_per_btc_eur"] == pytest.approx(7.1234 / BTC_PER_SHARE)
    assert ok["cost_per_btc_usd"] == pytest.approx(7.1234 * 1.16 / BTC_PER_SHARE)
    assert ok["fee_btc_per_year"] == pytest.approx(BTC * 0.0015)
    assert ok["price_low_usd"] == 74000.0
    assert ok["price_high_usd"] == 126000.0
    assert ok["price_warning"] is False

    # A price per share typed ten times too high
    typo = client.post(
        "/api/etp-holdings/IB1T/preview", json={**IB1T_INPUT, "avg_price_eur": 71.234}
    ).json()
    assert typo["price_warning"] is True
    assert session.exec(select(EtpHolding)).all() == []


def test_preview_without_price_history_gives_no_warning(client, monkeypatch):
    monkeypatch.setattr(market_history, "close_range", lambda since: None)

    body = client.post("/api/etp-holdings/IB1T/preview", json=IB1T_INPUT).json()

    assert body["price_low_usd"] is None
    assert body["price_warning"] is False


# --- where it shows up ----------------------------------------------------

def test_wallet_counts_the_holding_and_lists_it_apart(client, session):
    settings = session.get(GlobalSettings, 1)
    settings.cold_wallet_balance = 0.1
    session.add(settings)
    session.commit()
    _save(client)

    data = client.get("/api/wallet/summary").json()

    assert data["total_btc"] == pytest.approx(0.1 + BTC)
    # Listed apart, so a program reading the summary can leave it out where
    # the shares are already counted (for example with the broker's account).
    assert data["etp_holdings"] == [
        {
            "product": "IB1T",
            "name": "iShares Bitcoin ETP",
            "isin": "XS2940466316",
            "shares": 500.123456,
            "btc": pytest.approx(BTC),
        }
    ]
    # No Binance connection and no other buys: the cost basis is the holding alone.
    assert data["avg_buy_price"] == pytest.approx(COST_USD / BTC)


def test_cost_basis_blends_binance_and_the_holding(client, session):
    from dca_service.api import wallet_api

    _save(client)
    client_mock = AsyncMock()
    client_mock.get_spot_balances.return_value = {"BTC": 0.04}
    client_mock.get_current_price.return_value = 74000.0
    client_mock.calculate_buy_cost_basis.return_value = {
        "avg_price": 50000.0,
        "total_btc": 0.04,
        "total_cost": 2000.0,
    }
    with patch.object(wallet_api, "_get_binance_client", return_value=client_mock):
        data = client.get("/api/wallet/summary").json()

    assert data["total_btc"] == pytest.approx(0.04 + BTC)
    assert data["avg_buy_price"] == pytest.approx((2000.0 + COST_USD) / (0.04 + BTC))


def test_the_holding_shrinks_with_the_fee_over_time(client):
    _save(client)

    with freeze_time("2027-11-10 12:00:00", tz_offset=0):
        data = client.get("/api/wallet/summary").json()

    # 369 days after the iShares figure of 6 Nov 2026
    assert data["total_btc"] == pytest.approx(500.123456 * 0.000099758 * (1 - 0.0015 / 365) ** 369)


def test_dca_email_total_includes_the_holding(client, session):
    from dca_service.services.mailer import _get_total_btc_balance

    _save(client)

    assert _get_total_btc_balance(session) == pytest.approx(BTC)


def test_binance_holdings_total_includes_the_holding(client, session):
    from dca_service.models import BinanceCredentials
    from dca_service.services.security import encrypt_text

    session.add(BinanceCredentials(
        credential_type="READ_ONLY",
        api_key_encrypted=encrypt_text("k"),
        api_secret_encrypted=encrypt_text("s"),
    ))
    session.commit()
    _save(client)

    with patch(
        "dca_service.api.binance_api.BinanceClient.get_spot_balances",
        new=AsyncMock(return_value={"BTC": 0.01, "USDC": 50.0}),
    ):
        data = client.get("/api/binance/holdings").json()

    assert data["btc_balance"] == pytest.approx(0.01 + BTC)
    assert data["binance_btc_balance"] == 0.01


def test_holding_stays_out_of_the_buy_history(client):
    _save(client)

    assert client.get("/api/transactions").json() == []
