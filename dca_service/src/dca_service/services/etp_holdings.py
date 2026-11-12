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
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
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
    # The issuer's fees, prefilled in the form and used until the owner saves their own
    default_fee_percent: float = 0.0
    default_fee_changes: Tuple[Tuple[date, float], ...] = field(default=())


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
        # TER on the same fact sheet: 0.15% a year while part of it is waived,
        # up to and including 31 Dec 2026; 0.25% from 1 Jan 2027.
        default_fee_percent=0.15,
        default_fee_changes=((date(2027, 1, 1), 0.25),),
    ),
}

MAX_FEE_CHANGES = 10


def _fee_ok(value: float) -> bool:
    return math.isfinite(value) and 0 <= value <= MAX_FEE_PERCENT


class FeeChange(BaseModel):
    """From this day on, the yearly fee is fee_percent."""
    date: date
    fee_percent: float

    @field_validator("fee_percent")
    @classmethod
    def _fee(cls, value: float) -> float:
        if not _fee_ok(value):
            raise ValueError("Enter each yearly fee in percent, for example 0.25")
        return value


class EtpHoldingInput(BaseModel):
    shares: float
    avg_price_eur: float
    fee_percent: float  # The fee until the first change
    # None: the issuer's schedule (default_fee_changes); [] for one fee throughout
    fee_changes: Optional[List[FeeChange]] = None

    @field_validator("fee_changes")
    @classmethod
    def _changes(cls, value: Optional[List[FeeChange]]) -> Optional[List[FeeChange]]:
        if value is None:
            return None
        if len(value) > MAX_FEE_CHANGES:
            raise ValueError(f"Enter at most {MAX_FEE_CHANGES} fee changes")
        if len({c.date for c in value}) != len(value):
            raise ValueError("Each fee change needs its own day")
        return sorted(value, key=lambda c: c.date)

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
        if not _fee_ok(value):
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


Changes = List[dict]  # [{"date": date, "fee_percent": float}], oldest first


def fee_on(fee_percent: float, changes: Changes, day: date) -> float:
    """The yearly fee in force on a day: the last change on or before it, else the first fee."""
    for change in reversed(changes):
        if change["date"] <= day:
            return change["fee_percent"]
    return fee_percent


def btc_per_share(etp: EtpProduct, fee_percent: float, day: date, changes: Changes = ()) -> float:
    """
    The published figure, less each day's share of the yearly fee in force
    that day, from the day after the figure up to `day`.
    """
    start = etp.btc_per_share_date
    value = etp.btc_per_share
    if day <= start:
        return value
    changes = list(changes)
    # Each run of days (begin, end] has one fee: a change dated d takes over
    # from day d itself, so the run before it ends the day before.
    cuts = sorted({c["date"] - timedelta(days=1) for c in changes if start < c["date"] - timedelta(days=1) < day})
    bounds = [start, *cuts, day]
    for begin, end in zip(bounds, bounds[1:]):
        fee = fee_on(fee_percent, changes, begin + timedelta(days=1))
        value *= (1 - fee / 100 / 365) ** (end - begin).days
    return value


def _changes_of(holding_changes: Optional[str], etp: EtpProduct) -> Changes:
    """The saved schedule; the issuer's when nothing was saved."""
    if holding_changes is None:
        return [{"date": d, "fee_percent": f} for d, f in etp.default_fee_changes]
    return [
        {"date": date.fromisoformat(c["date"]), "fee_percent": float(c["fee_percent"])}
        for c in json.loads(holding_changes)
    ]


def _changes_json(changes: Optional[List["FeeChange"]]) -> Optional[str]:
    if changes is None:
        return None
    return json.dumps([{"date": c.date.isoformat(), "fee_percent": c.fee_percent} for c in changes])


@dataclass(frozen=True)
class Position:
    etp: EtpProduct
    shares: float
    avg_price_eur: float
    fee_percent: float
    fx_rate_usd: float
    fx_date: Optional[str]
    btc_per_share: float
    fee_changes: Changes = field(default_factory=list)
    fee_percent_today: float = 0.0

    @property
    def btc(self) -> float:
        return self.shares * self.btc_per_share

    @property
    def cost_eur(self) -> float:
        return self.shares * self.avg_price_eur

    @property
    def cost_usd(self) -> float:
        return self.cost_eur * self.fx_rate_usd


def _make(etp: EtpProduct, shares: float, avg_price_eur: float, fee_percent: float, changes: Changes,
          fx_rate_usd: float, fx_date: Optional[str], day: date) -> Position:
    return Position(
        etp=etp,
        shares=shares,
        avg_price_eur=avg_price_eur,
        fee_percent=fee_percent,
        fx_rate_usd=fx_rate_usd,
        fx_date=fx_date,
        btc_per_share=btc_per_share(etp, fee_percent, day, changes),
        fee_changes=changes,
        fee_percent_today=fee_on(fee_percent, changes, day),
    )


def _position(holding: EtpHolding, day: date) -> Position:
    etp = PRODUCTS[holding.product]
    return _make(etp, holding.shares, holding.avg_price_eur, holding.fee_percent,
                 _changes_of(holding.fee_changes, etp), holding.fx_rate_usd, holding.fx_date, day)


def defaults(key: str) -> dict:
    """The issuer's fees, to start the form from."""
    etp = product(key)
    return {
        "fee_percent": etp.default_fee_percent,
        "fee_changes": [{"date": d.isoformat(), "fee_percent": f} for d, f in etp.default_fee_changes],
    }


def describe(position: Position) -> dict:
    etp = position.etp
    return {
        "product": etp.key,
        "name": etp.name,
        "isin": etp.isin,
        "shares": position.shares,
        "avg_price_eur": position.avg_price_eur,
        "fee_percent": position.fee_percent,
        "fee_changes": [{"date": c["date"].isoformat(), "fee_percent": c["fee_percent"]} for c in position.fee_changes],
        "fee_percent_today": position.fee_percent_today,
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
        "fee_btc_per_year": position.btc * position.fee_percent_today / 100,
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
    changes = _changes_of(_changes_json(data.fee_changes), etp)
    position = _make(etp, data.shares, data.avg_price_eur, data.fee_percent, changes, fx_rate_usd, fx_date, day)
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
    holding.fee_changes = _changes_json(data.fee_changes)
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
