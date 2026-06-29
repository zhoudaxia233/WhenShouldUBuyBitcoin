from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from dca_service.auth.dependencies import get_current_user
from dca_service.config import settings
from dca_service.database import get_session
from dca_service.models import DCAStrategy, GlobalSettings, User
from dca_service.services.exchange_config import (
    get_active_exchange,
    get_credentials,
    get_exchange_symbol,
    set_active_exchange,
)
from dca_service.services.security import decrypt_text


router = APIRouter(prefix="/exchange", tags=["exchange"])


class ActiveExchangeUpdate(BaseModel):
    active_exchange: str


@router.get("/active")
def read_active_exchange(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return {"active_exchange": get_active_exchange(session)}


@router.post("/active")
def update_active_exchange(
    payload: ActiveExchangeUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        active_exchange = set_active_exchange(session, payload.active_exchange)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported exchange") from exc
    return {"success": True, "active_exchange": active_exchange}


@router.get("/holdings")
async def get_active_exchange_holdings(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    active_exchange = get_active_exchange(session)
    quote_asset = "USD" if active_exchange == "KRAKEN" else settings.DCA_QUOTE_ASSET
    strategy = session.exec(select(DCAStrategy)).first()
    target_btc = strategy.target_btc_amount if strategy else 1.0
    creds = get_credentials(session, active_exchange, "READ_ONLY")
    if not creds:
        return {
            "connected": False,
            "reason": "no_credentials",
            "exchange": active_exchange,
            "quote_asset": quote_asset,
            "target_btc_amount": target_btc,
        }

    try:
        api_key = decrypt_text(creds.api_key_encrypted)
        api_secret = decrypt_text(creds.api_secret_encrypted)
    except Exception:
        return {
            "connected": False,
            "reason": "auth_error",
            "exchange": active_exchange,
            "quote_asset": quote_asset,
            "target_btc_amount": target_btc,
        }

    client = None
    try:
        if active_exchange == "KRAKEN":
            from dca_service.services.kraken_client import KrakenClient

            client = KrakenClient(api_key, api_secret)
        else:
            from dca_service.services.binance_client import BinanceClient

            client = BinanceClient(api_key, api_secret)
        balances = await client.get_spot_balances(["BTC", quote_asset])
        btc_bal = balances.get("BTC", 0.0)
        quote_bal = balances.get(quote_asset, 0.0)
        settings_record = session.get(GlobalSettings, 1)
        cold_wallet_btc = settings_record.cold_wallet_balance if settings_record else 0.0
        total_btc = btc_bal + cold_wallet_btc
        return {
            "connected": True,
            "exchange": active_exchange,
            "exchange_symbol": get_exchange_symbol(active_exchange),
            "btc_balance": total_btc,
            "quote_balance": quote_bal,
            "quote_asset": quote_asset,
            "target_btc_amount": target_btc,
            "progress_ratio": min(total_btc / target_btc, 1.0) if target_btc > 0 else 0.0,
            "binance_btc_balance": btc_bal if active_exchange == "BINANCE" else None,
            "exchange_btc_balance": btc_bal,
            "cold_wallet_btc_balance": cold_wallet_btc,
        }
    except Exception:
        return {
            "connected": False,
            "reason": "api_error",
            "exchange": active_exchange,
            "quote_asset": quote_asset,
            "target_btc_amount": target_btc,
        }
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass
