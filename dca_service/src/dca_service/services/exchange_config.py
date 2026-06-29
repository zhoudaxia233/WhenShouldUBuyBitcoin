from sqlmodel import Session, select

from dca_service.config import settings
from dca_service.models import BinanceCredentials, GlobalSettings, KrakenCredentials


SUPPORTED_EXCHANGES = {"BINANCE", "KRAKEN"}


def normalize_exchange(exchange: str | None) -> str:
    normalized = (exchange or "BINANCE").strip().upper()
    if normalized not in SUPPORTED_EXCHANGES:
        raise ValueError("Unsupported exchange")
    return normalized


def get_global_settings(session: Session) -> GlobalSettings:
    global_settings = session.get(GlobalSettings, 1)
    if global_settings:
        return global_settings
    global_settings = GlobalSettings(id=1, cold_wallet_balance=0.0, active_exchange="BINANCE")
    session.add(global_settings)
    session.commit()
    session.refresh(global_settings)
    return global_settings


def get_active_exchange(session: Session) -> str:
    global_settings = get_global_settings(session)
    try:
        return normalize_exchange(global_settings.active_exchange)
    except ValueError:
        return "BINANCE"


def set_active_exchange(session: Session, exchange: str) -> str:
    active_exchange = normalize_exchange(exchange)
    global_settings = get_global_settings(session)
    global_settings.active_exchange = active_exchange
    session.add(global_settings)
    session.commit()
    return active_exchange


def get_exchange_symbol(exchange: str, quote_asset: str | None = None) -> str:
    active_exchange = normalize_exchange(exchange)
    quote = (quote_asset or settings.DCA_QUOTE_ASSET or "USDC").strip().upper()
    if active_exchange == "KRAKEN":
        return "XBTUSD"
    return f"BTC{quote}"


def get_credentials(session: Session, exchange: str, credential_type: str):
    active_exchange = normalize_exchange(exchange)
    model = KrakenCredentials if active_exchange == "KRAKEN" else BinanceCredentials
    return session.exec(
        select(model).where(model.credential_type == credential_type)
    ).first()
