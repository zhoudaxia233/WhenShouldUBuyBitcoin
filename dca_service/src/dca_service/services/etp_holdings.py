"""
Bitcoin ETP holdings: shares of a physically backed bitcoin ETP (IB1T) held with
a broker, entered by hand as shares, average price per share and yearly fee.

Each share stands for a fixed amount of bitcoin, the issuer's "cryptoasset
entitlement". Every day that day's share of the yearly fee (TER) is taken off
it, so the bitcoin is worked out from the issuer's latest published figure and
the fee the owner enters. A holding has no trade date: it counts in holdings and
the cost basis, but stays out of the buy history and the DCA budget.
"""
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, field_validator
from sqlmodel import Session, col, select

from dca_service.models import EtpHolding
from dca_service.services import fx_rates, market_history

MAX_FEE_PERCENT = 5.0
PRICE_RANGE_TOLERANCE = 0.10  # Flag a cost per BTC this far outside BTC's range since launch


@dataclass(frozen=True)
class EtpProduct:
    key: str
    name: str
    isin: str
    btc_per_share: float  # Published entitlement on btc_per_share_date
    btc_per_share_date: date
    launch_date: date


PRODUCTS: Dict[str, EtpProduct] = {
    "IB1T": EtpProduct(
        key="IB1T",
        name="iShares Bitcoin ETP",
        isin="XS2940466316",
        # "Daily Cryptoasset Entitlement per Security" on the iShares fact sheet
        # for Germany, data as at 6 Nov 2026. It was 0.0001 on the series issue
        # date, 24 Mar 2025 (Final Terms). Change the figure and date together.
        btc_per_share=0.000099758,
        btc_per_share_date=date(2026, 11, 6),
        launch_date=date(2025, 3, 24),
    ),
}


class EtpHoldingInput(BaseModel):
    shares: float
    avg_price_eur: float
    fee_percent: float

    @field_validator("shares")
    @classmethod
    def _shares(cls, value: float) -> float:
        if not (math.isfinite(value) and value > 0):
            raise ValueError("Enter how many shares you hold")
        return value

    @field_validator("avg_price_eur")
    @classmethod
    def _price(cls, value: float) -> float:
        if not (math.isfinite(value) and value > 0):
            raise ValueError("Enter the average price per share")
        return value

    @field_validator("fee_percent")
    @classmethod
    def _fee(cls, value: float) -> float:
        if not (math.isfinite(value) and 0 <= value <= MAX_FEE_PERCENT):
            raise ValueError("Enter the yearly fee in percent, for example 0.25")
        return value


class EtpHoldingError(Exception):
    status_code = 400


class UnknownProduct(EtpHoldingError):
    status_code = 404


class HoldingNotFound(EtpHoldingError):
    status_code = 404


class RateUnavailable(EtpHoldingError):
    status_code = 503


def product(key: str) -> EtpProduct:
    try:
        return PRODUCTS[key]
    except KeyError:
        raise UnknownProduct("Only IB1T can be added here.") from None


def today() -> date:
    return datetime.now(timezone.utc).date()


def btc_per_share(etp: EtpProduct, fee_percent: float, day: date) -> float:
    """The published figure, less each day's share of the yearly fee since then."""
    days = max((day - etp.btc_per_share_date).days, 0)
    return etp.btc_per_share * (1 - fee_percent / 100 / 365) ** days


@dataclass(frozen=True)
class Position:
    etp: EtpProduct
    shares: float
    avg_price_eur: float
    fee_percent: float
    fx_rate_usd: float
    fx_date: Optional[str]
    btc_per_share: float

    @property
    def btc(self) -> float:
        return self.shares * self.btc_per_share

    @property
    def cost_eur(self) -> float:
        return self.shares * self.avg_price_eur

    @property
    def cost_usd(self) -> float:
        return self.cost_eur * self.fx_rate_usd


def _position(holding: EtpHolding, day: date) -> Position:
    etp = PRODUCTS[holding.product]
    return Position(
        etp=etp,
        shares=holding.shares,
        avg_price_eur=holding.avg_price_eur,
        fee_percent=holding.fee_percent,
        fx_rate_usd=holding.fx_rate_usd,
        fx_date=holding.fx_date,
        btc_per_share=btc_per_share(etp, holding.fee_percent, day),
    )


def describe(position: Position) -> dict:
    etp = position.etp
    return {
        "product": etp.key,
        "name": etp.name,
        "isin": etp.isin,
        "shares": position.shares,
        "avg_price_eur": position.avg_price_eur,
        "fee_percent": position.fee_percent,
        "btc_per_share": position.btc_per_share,
        "published_btc_per_share": etp.btc_per_share,
        "published_date": etp.btc_per_share_date.isoformat(),
        "btc": position.btc,
        "cost_eur": position.cost_eur,
        "cost_usd": position.cost_usd,
        "fx_rate_usd": position.fx_rate_usd,
        "fx_date": position.fx_date,
        "cost_per_btc_eur": position.avg_price_eur / position.btc_per_share,
        "cost_per_btc_usd": position.avg_price_eur * position.fx_rate_usd / position.btc_per_share,
        "fee_btc_per_year": position.btc * position.fee_percent / 100,
    }


def _rate(session: Session, etp: EtpProduct, data: EtpHoldingInput, day: date) -> Tuple[float, Optional[str]]:
    """
    The EUR/USD rate for the cost basis: kept from the last save when the shares
    and price are unchanged (a new fee alone moves no money), else the ECB rate of today.
    """
    stored = session.get(EtpHolding, etp.key)
    if stored and stored.shares == data.shares and stored.avg_price_eur == data.avg_price_eur:
        return stored.fx_rate_usd, stored.fx_date
    try:
        rate = fx_rates.eur_usd_rate(day)
    except fx_rates.FxUnavailable as e:
        raise RateUnavailable(
            "The EUR/USD exchange rate is not available right now. Try again in a few minutes."
        ) from e
    return rate.rate, rate.date


def preview(session: Session, key: str, data: EtpHoldingInput) -> dict:
    """What the holding would be saved as, plus a check of the price against BTC since launch."""
    etp = product(key)
    day = today()
    fx_rate_usd, fx_date = _rate(session, etp, data, day)
    position = Position(
        etp, data.shares, data.avg_price_eur, data.fee_percent, fx_rate_usd, fx_date,
        btc_per_share(etp, data.fee_percent, day),
    )
    result = describe(position)
    price_range = market_history.close_range(etp.launch_date)
    low, high = price_range if price_range else (None, None)
    cost_per_btc = result["cost_per_btc_usd"]
    result.update(
        price_low_usd=low,
        price_high_usd=high,
        price_warning=price_range is not None and not (
            low * (1 - PRICE_RANGE_TOLERANCE) <= cost_per_btc <= high * (1 + PRICE_RANGE_TOLERANCE)
        ),
    )
    return result


def save(session: Session, key: str, data: EtpHoldingInput) -> Position:
    etp = product(key)
    day = today()
    fx_rate_usd, fx_date = _rate(session, etp, data, day)
    holding = session.get(EtpHolding, etp.key) or EtpHolding(
        product=etp.key, shares=data.shares, avg_price_eur=data.avg_price_eur, fee_percent=data.fee_percent
    )
    holding.shares = data.shares
    holding.avg_price_eur = data.avg_price_eur
    holding.fee_percent = data.fee_percent
    holding.fx_rate_usd = fx_rate_usd
    holding.fx_date = fx_date
    holding.updated_at = datetime.now(timezone.utc)
    session.add(holding)
    session.commit()
    session.refresh(holding)
    return _position(holding, day)


def get(session: Session, key: str) -> Position:
    etp = product(key)
    holding = session.get(EtpHolding, etp.key)
    if not holding:
        raise HoldingNotFound(f"No {etp.key} holding is saved.")
    return _position(holding, today())


def delete(session: Session, key: str) -> None:
    etp = product(key)
    holding = session.get(EtpHolding, etp.key)
    if not holding:
        raise HoldingNotFound(f"No {etp.key} holding is saved.")
    session.delete(holding)
    session.commit()


def positions(session: Session) -> List[Position]:
    day = today()
    holdings = session.exec(select(EtpHolding).order_by(col(EtpHolding.product))).all()
    return [_position(h, day) for h in holdings if h.product in PRODUCTS]


def total_btc(session: Session) -> float:
    return sum(p.btc for p in positions(session))
