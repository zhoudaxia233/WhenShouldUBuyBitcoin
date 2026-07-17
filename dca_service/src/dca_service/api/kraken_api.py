from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from dca_service.auth.dependencies import get_current_user
from dca_service.database import get_session
from dca_service.models import KrakenCredentials, User
from dca_service.services.exchange_config import get_exchange_symbol
from dca_service.services.kraken_client import KrakenClient
from dca_service.services.security import decrypt_text, encrypt_text


router = APIRouter(prefix="/kraken", tags=["kraken"])


class CredentialsSchema(BaseModel):
    api_key: str
    api_secret: str
    credential_type: str = "READ_ONLY"


class CredentialsStatus(BaseModel):
    has_credentials: bool
    masked_api_key: Optional[str] = None
    last_updated: Optional[datetime] = None


class ConnectionTestResult(BaseModel):
    success: bool
    error_message: Optional[str] = None


class TradingStatus(BaseModel):
    has_credentials: bool
    has_trading_permission: bool
    can_enable_live: bool
    error_message: Optional[str] = None


@router.post("/credentials")
def save_credentials(
    creds: CredentialsSchema,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not creds.api_key or not creds.api_secret:
        raise HTTPException(status_code=400, detail="API Key and Secret are required")

    try:
        key_enc = encrypt_text(creds.api_key)
        secret_enc = encrypt_text(creds.api_secret)
    except ValueError as e:
        raise HTTPException(status_code=500, detail="Unable to secure Kraken credentials") from e

    existing = session.exec(
        select(KrakenCredentials).where(KrakenCredentials.credential_type == creds.credential_type)
    ).first()
    if existing:
        existing.api_key_encrypted = key_enc
        existing.api_secret_encrypted = secret_enc
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
    else:
        session.add(
            KrakenCredentials(
                credential_type=creds.credential_type,
                api_key_encrypted=key_enc,
                api_secret_encrypted=secret_enc,
            )
        )
    session.commit()
    return {"success": True, "message": f"Kraken {creds.credential_type} credentials saved."}


@router.get("/credentials/status", response_model=CredentialsStatus)
def get_credentials_status(
    credential_type: str = "READ_ONLY",
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    creds = session.exec(
        select(KrakenCredentials).where(KrakenCredentials.credential_type == credential_type)
    ).first()
    if not creds:
        return CredentialsStatus(has_credentials=False)
    try:
        plain_key = decrypt_text(creds.api_key_encrypted)
        masked = f"{plain_key[:4]}****{plain_key[-4:]}" if len(plain_key) > 8 else "****"
    except Exception:
        masked = "ERROR"
    return CredentialsStatus(
        has_credentials=True,
        masked_api_key=masked,
        last_updated=creds.updated_at,
    )


@router.post("/test-connection", response_model=ConnectionTestResult)
async def test_connection(
    credential_type: str = "READ_ONLY",
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    creds = session.exec(
        select(KrakenCredentials).where(KrakenCredentials.credential_type == credential_type)
    ).first()
    if not creds:
        return ConnectionTestResult(success=False, error_message="No credentials found")
    client = None
    try:
        client = KrakenClient(
            decrypt_text(creds.api_key_encrypted),
            decrypt_text(creds.api_secret_encrypted),
        )
        await client.test_connection()
        return ConnectionTestResult(success=True)
    except Exception:
        return ConnectionTestResult(success=False, error_message="Kraken connection test failed")
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass


@router.get("/trading-status", response_model=TradingStatus)
async def get_trading_status(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    creds = session.exec(
        select(KrakenCredentials).where(KrakenCredentials.credential_type == "TRADING")
    ).first()
    if not creds:
        return TradingStatus(
            has_credentials=False,
            has_trading_permission=False,
            can_enable_live=False,
            error_message="No Kraken trading credentials configured",
        )
    client = None
    try:
        client = KrakenClient(
            decrypt_text(creds.api_key_encrypted),
            decrypt_text(creds.api_secret_encrypted),
        )
        await client.test_connection()
        await client.test_trading_permission(get_exchange_symbol("KRAKEN"))
        return TradingStatus(
            has_credentials=True,
            has_trading_permission=True,
            can_enable_live=True,
        )
    except Exception:
        return TradingStatus(
            has_credentials=True,
            has_trading_permission=False,
            can_enable_live=False,
            error_message="Kraken trading connection failed",
        )
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass
