"""
External buys API: record BTC bought on other exchanges by hand (no orders, no sync).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session

from dca_service.auth.dependencies import get_current_user
from dca_service.database import get_session
from dca_service.models import ExternalTrade, User
from dca_service.services import external_buys
from dca_service.services.external_buys import ExternalBuyError, ExternalBuyInput

router = APIRouter(prefix="/external-buys", tags=["external-buys"])


def _read(trade: ExternalTrade) -> dict:
    return {
        "id": trade.id,
        "venue": trade.venue,
        "venue_trade_id": trade.venue_trade_id,
        "timestamp": external_buys._utc(trade.timestamp).isoformat(),
        "quote_currency": trade.quote_currency,
        "quote_amount": trade.quote_amount,
        "btc_amount": trade.btc_amount,
        "fee_amount": trade.fee_amount,
        "fee_currency": trade.fee_currency,
        "fee_usd": trade.fee_usd,
        "fx_rate_usd": trade.fx_rate_usd,
        "fx_date": trade.fx_date,
        "usd_amount": trade.quote_amount * trade.fx_rate_usd,
        "ahr999": trade.ahr999,
    }


def _raise(error: ExternalBuyError):
    raise HTTPException(status_code=error.status_code, detail=str(error))


@router.post("/preview")
def preview_external_buy(
    data: ExternalBuyInput,
    current_user: User = Depends(get_current_user),
):
    try:
        return external_buys.preview(data)
    except ExternalBuyError as e:
        _raise(e)


@router.post("", status_code=201)
def create_external_buy(
    data: ExternalBuyInput,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        return _read(external_buys.create(session, data))
    except ExternalBuyError as e:
        _raise(e)


@router.get("/{trade_id}")
def read_external_buy(
    trade_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    trade = session.get(ExternalTrade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="This buy no longer exists.")
    return _read(trade)


@router.put("/{trade_id}")
def update_external_buy(
    trade_id: int,
    data: ExternalBuyInput,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        return _read(external_buys.update(session, trade_id, data))
    except ExternalBuyError as e:
        _raise(e)


@router.delete("/{trade_id}", status_code=204)
def delete_external_buy(
    trade_id: int,
    adjust_balance: bool = Query(default=True),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        external_buys.delete(session, trade_id, adjust_balance)
    except ExternalBuyError as e:
        _raise(e)
    return Response(status_code=204)
