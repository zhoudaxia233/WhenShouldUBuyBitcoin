"""
External buys: BTC bought on other exchanges and entered by hand (read-only history).

This module owns everything about them: validation, the trade-day exchange rate,
the venue balance they optionally add to, and the read-only view that lets the
stats treat them like Binance buys. They live in their own table so the Binance
re-sync and the DCA budget never see them.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, col, select

from dca_service.models import DCATransaction, ExternalTrade, VenueBalance
from dca_service.services import fx_rates, market_history

QUOTE_CURRENCIES = ("EUR", "USD", "USDC")
FEE_CURRENCIES = ("EUR", "USD", "USDC", "BTC")
PRICE_WARNING_THRESHOLD = 0.05  # Flag prices more than 5% away from that day's close


class ExternalBuyInput(BaseModel):
    venue: str = Field(max_length=40)
    timestamp: datetime
    quote_currency: str
    quote_amount: float = Field(gt=0)
    btc_amount: float = Field(gt=0)
    fee_amount: float = Field(default=0.0, ge=0)
    fee_currency: str = "EUR"
    venue_trade_id: Optional[str] = Field(default=None, max_length=100)
    adjust_balance: bool = True

    @field_validator("venue")
    @classmethod
    def _venue(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter the exchange name")
        if value.lower() == "binance":
            raise ValueError("Binance buys are synced automatically; add only other exchanges here")
        return value

    @field_validator("quote_currency")
    @classmethod
    def _quote_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in QUOTE_CURRENCIES:
            raise ValueError(f"Currency must be one of {', '.join(QUOTE_CURRENCIES)}")
        return value

    @field_validator("fee_currency")
    @classmethod
    def _fee_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in FEE_CURRENCIES:
            raise ValueError(f"Fee currency must be one of {', '.join(FEE_CURRENCIES)}")
        return value

    @field_validator("venue_trade_id")
    @classmethod
    def _trade_id(cls, value: Optional[str]) -> Optional[str]:
        value = (value or "").strip()
        return value or None

    @field_validator("timestamp")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class ExternalBuyError(Exception):
    status_code = 400


class DuplicateBuy(ExternalBuyError):
    status_code = 409


class BuyNotFound(ExternalBuyError):
    status_code = 404


class RateUnavailable(ExternalBuyError):
    status_code = 503


@dataclass(frozen=True)
class Conversion:
    fx_rate_usd: float
    fx_date: Optional[str]
    usd_amount: float
    fee_usd: float
    price_quote: float
    price_usd: float


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def _convert(data: ExternalBuyInput) -> Conversion:
    if data.quote_currency == "EUR" or data.fee_currency == "EUR":
        try:
            rate = fx_rates.eur_usd_rate(data.timestamp.date())
        except fx_rates.FxUnavailable as e:
            raise RateUnavailable(
                "The EUR/USD exchange rate for that day is not available right now. Try again in a few minutes."
            ) from e
        eur_usd, eur_date = rate.rate, rate.date
    else:
        eur_usd, eur_date = None, None

    if data.quote_currency == "EUR":
        fx_rate_usd, fx_date = eur_usd, eur_date
    else:
        fx_rate_usd, fx_date = 1.0, None

    usd_amount = data.quote_amount * fx_rate_usd
    price_quote = data.quote_amount / data.btc_amount
    price_usd = usd_amount / data.btc_amount
    if data.fee_currency == "BTC":
        fee_usd = data.fee_amount * price_usd
    elif data.fee_currency == "EUR":
        fee_usd = data.fee_amount * eur_usd
    else:
        fee_usd = data.fee_amount
    return Conversion(fx_rate_usd, fx_date, usd_amount, fee_usd, price_quote, price_usd)


def preview(data: ExternalBuyInput) -> dict:
    """What a buy would be recorded as, plus a sanity check against that day's price."""
    conversion = _convert(data)
    day = market_history.market_day(data.timestamp.date())
    close = day.close_price if day else None
    deviation = (conversion.price_usd - close) / close if close else None
    return {
        **conversion.__dict__,
        "ahr999": day.ahr999 if day else None,
        "day_close_usd": close,
        "price_deviation": deviation,
        "price_warning": deviation is not None and abs(deviation) > PRICE_WARNING_THRESHOLD,
    }


def _check_duplicate(session: Session, data: ExternalBuyInput, exclude_id: Optional[int] = None) -> None:
    query = select(ExternalTrade).where(ExternalTrade.venue == data.venue)
    if exclude_id is not None:
        query = query.where(ExternalTrade.id != exclude_id)
    for trade in session.exec(query).all():
        if data.venue_trade_id and trade.venue_trade_id == data.venue_trade_id:
            raise DuplicateBuy(f"A {data.venue} buy with reference {data.venue_trade_id} is already recorded.")
        if (
            _utc(trade.timestamp) == data.timestamp
            and trade.quote_currency == data.quote_currency
            and abs(trade.quote_amount - data.quote_amount) < 1e-9
        ):
            raise DuplicateBuy(f"A {data.venue} buy with the same time and amount is already recorded.")


def _adjust_venue_balance(session: Session, venue: str, delta_btc: float) -> None:
    balance = session.get(VenueBalance, venue) or VenueBalance(venue=venue, btc=0.0)
    balance.btc = max(balance.btc + delta_btc, 0.0)
    balance.updated_at = datetime.now(timezone.utc)
    session.add(balance)


def _apply(trade: ExternalTrade, data: ExternalBuyInput) -> None:
    conversion = _convert(data)
    day = market_history.market_day(data.timestamp.date())
    trade.venue = data.venue
    trade.venue_trade_id = data.venue_trade_id
    trade.timestamp = data.timestamp
    trade.quote_currency = data.quote_currency
    trade.quote_amount = data.quote_amount
    trade.btc_amount = data.btc_amount
    trade.fee_amount = data.fee_amount
    trade.fee_currency = data.fee_currency
    trade.fx_rate_usd = conversion.fx_rate_usd
    trade.fx_date = conversion.fx_date
    trade.fee_usd = conversion.fee_usd
    trade.ahr999 = day.ahr999 if day else None
    trade.updated_at = datetime.now(timezone.utc)


def create(session: Session, data: ExternalBuyInput) -> ExternalTrade:
    _check_duplicate(session, data)
    trade = ExternalTrade(
        venue=data.venue, timestamp=data.timestamp, quote_currency=data.quote_currency,
        quote_amount=data.quote_amount, btc_amount=data.btc_amount,
    )
    _apply(trade, data)
    session.add(trade)
    if data.adjust_balance:
        _adjust_venue_balance(session, data.venue, data.btc_amount)
    session.commit()
    session.refresh(trade)
    return trade


def update(session: Session, trade_id: int, data: ExternalBuyInput) -> ExternalTrade:
    trade = session.get(ExternalTrade, trade_id)
    if not trade:
        raise BuyNotFound("This buy no longer exists.")
    _check_duplicate(session, data, exclude_id=trade_id)
    old_venue, old_btc = trade.venue, trade.btc_amount
    _apply(trade, data)
    session.add(trade)
    if data.adjust_balance:
        _adjust_venue_balance(session, old_venue, -old_btc)
        _adjust_venue_balance(session, data.venue, data.btc_amount)
    session.commit()
    session.refresh(trade)
    return trade


def delete(session: Session, trade_id: int, adjust_balance: bool) -> None:
    trade = session.get(ExternalTrade, trade_id)
    if not trade:
        raise BuyNotFound("This buy no longer exists.")
    if adjust_balance:
        _adjust_venue_balance(session, trade.venue, -trade.btc_amount)
    session.delete(trade)
    session.commit()


def all_trades(session: Session) -> List[ExternalTrade]:
    return list(session.exec(select(ExternalTrade).order_by(col(ExternalTrade.timestamp))).all())


def venue_balances(session: Session) -> List[VenueBalance]:
    return list(session.exec(select(VenueBalance).order_by(col(VenueBalance.venue))).all())


def set_venue_balance(session: Session, venue: str, btc: float) -> VenueBalance:
    balance = session.get(VenueBalance, venue) or VenueBalance(venue=venue)
    balance.btc = btc
    balance.updated_at = datetime.now(timezone.utc)
    session.add(balance)
    session.commit()
    session.refresh(balance)
    return balance


# --- read-only view for the stats -------------------------------------------

@dataclass(frozen=True)
class LedgerBuy:
    """
    An external buy shaped like a DCATransaction (amounts in USD), so the stats
    code can read both kinds of buy the same way. Never persisted.

    `id` is negative (minus the external_trades id) so it can't collide with a
    dca_transactions id when the stats group fills by id.
    """
    id: int
    timestamp: datetime
    status: str
    fiat_amount: float
    btc_amount: float
    price: float
    fee_amount: float
    fee_asset: str
    ahr999: Optional[float]
    notes: Optional[str]
    source: str
    is_manual: bool
    venue: str
    quote_currency: str
    quote_amount: float
    fx_rate_usd: float
    fx_date: Optional[str]
    executed_amount_usd: Optional[float] = None
    executed_amount_btc: Optional[float] = None
    avg_execution_price_usd: Optional[float] = None
    binance_order_id: Optional[int] = None
    binance_trade_id: Optional[int] = None


def as_ledger_buy(trade: ExternalTrade) -> LedgerBuy:
    usd_amount = trade.quote_amount * trade.fx_rate_usd
    return LedgerBuy(
        id=-int(trade.id),
        timestamp=_utc(trade.timestamp),
        status="SUCCESS",
        fiat_amount=usd_amount,
        btc_amount=trade.btc_amount,
        price=usd_amount / trade.btc_amount,
        fee_amount=trade.fee_usd,
        fee_asset="USD",
        ahr999=trade.ahr999,
        notes=None,
        source="MANUAL",
        is_manual=True,
        venue=trade.venue,
        quote_currency=trade.quote_currency,
        quote_amount=trade.quote_amount,
        fx_rate_usd=trade.fx_rate_usd,
        fx_date=trade.fx_date,
    )


def successful_buys(session: Session) -> list:
    """Successful Binance/DCA rows and external buys together, oldest first."""
    rows = list(
        session.exec(
            select(DCATransaction)
            .where(DCATransaction.status == "SUCCESS")
            .order_by(DCATransaction.timestamp)
        ).all()
    )
    rows.extend(as_ledger_buy(t) for t in all_trades(session))
    rows.sort(key=lambda tx: _utc(tx.timestamp))
    return rows
