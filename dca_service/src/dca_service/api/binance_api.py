from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from dca_service.database import get_session
from dca_service.models import BinanceCredentials, DCAStrategy
from dca_service.services.security import encrypt_text, decrypt_text
from dca_service.services.binance_client import BinanceClient
from dca_service.config import settings

router = APIRouter(prefix="/binance", tags=["binance"])

class CredentialsSchema(BaseModel):
    api_key: str
    api_secret: str

class CredentialsStatus(BaseModel):
    has_credentials: bool
    masked_api_key: Optional[str] = None
    last_updated: Optional[datetime] = None

class ConnectionTestResult(BaseModel):
    success: bool
    error_message: Optional[str] = None

class HoldingsSummary(BaseModel):
    connected: bool
    reason: Optional[str] = None
    btc_balance: Optional[float] = None
    quote_balance: Optional[float] = None
    quote_asset: str
    target_btc_amount: Optional[float] = None
    progress_ratio: Optional[float] = None
    # Breakdown
    binance_btc_balance: Optional[float] = None
    cold_wallet_btc_balance: Optional[float] = None

@router.post("/credentials")
def save_credentials(creds: CredentialsSchema, session: Session = Depends(get_session)):
    if not creds.api_key or not creds.api_secret:
        raise HTTPException(status_code=400, detail="API Key and Secret are required")
    
    try:
        # Encrypt
        key_enc = encrypt_text(creds.api_key)
        secret_enc = encrypt_text(creds.api_secret)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Check if exists
    existing = session.exec(select(BinanceCredentials)).first()
    if existing:
        existing.api_key_encrypted = key_enc
        existing.api_secret_encrypted = secret_enc
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
    else:
        new_creds = BinanceCredentials(
            api_key_encrypted=key_enc,
            api_secret_encrypted=secret_enc
        )
        session.add(new_creds)
    
    session.commit()
    return {"success": True, "message": "Credentials saved."}

@router.get("/credentials/status", response_model=CredentialsStatus)
def get_credentials_status(session: Session = Depends(get_session)):
    creds = session.exec(select(BinanceCredentials)).first()
    if not creds:
        return CredentialsStatus(has_credentials=False)
    
    try:
        # Decrypt to mask
        plain_key = decrypt_text(creds.api_key_encrypted)
        masked = f"{plain_key[:4]}****{plain_key[-4:]}" if len(plain_key) > 8 else "****"
        return CredentialsStatus(
            has_credentials=True,
            masked_api_key=masked,
            last_updated=creds.updated_at
        )
    except Exception:
        return CredentialsStatus(has_credentials=True, masked_api_key="ERROR", last_updated=creds.updated_at)

@router.post("/test-connection", response_model=ConnectionTestResult)
async def test_connection(session: Session = Depends(get_session)):
    creds = session.exec(select(BinanceCredentials)).first()
    if not creds:
        return ConnectionTestResult(success=False, error_message="No credentials found")
    
    try:
        api_key = decrypt_text(creds.api_key_encrypted)
        api_secret = decrypt_text(creds.api_secret_encrypted)
    except Exception as e:
        return ConnectionTestResult(success=False, error_message=f"Decryption failed: {str(e)}")
    
    client = BinanceClient(api_key, api_secret)
    try:
        await client.test_connection()
        return ConnectionTestResult(success=True)
    except Exception as e:
        return ConnectionTestResult(success=False, error_message=str(e))
    finally:
        await client.close()

@router.get("/holdings", response_model=HoldingsSummary)
async def get_holdings(session: Session = Depends(get_session)):
    quote_asset = settings.DCA_QUOTE_ASSET
    
    # Get strategy for target
    strategy = session.exec(select(DCAStrategy)).first()
    target_btc = strategy.target_btc_amount if strategy else 1.0 # Default to 1.0 if no strategy
    
    creds = session.exec(select(BinanceCredentials)).first()
    if not creds:
        return HoldingsSummary(
            connected=False, 
            reason="no_credentials", 
            quote_asset=quote_asset,
            target_btc_amount=target_btc
        )
    
    try:
        api_key = decrypt_text(creds.api_key_encrypted)
        api_secret = decrypt_text(creds.api_secret_encrypted)
    except Exception as e:
        return HoldingsSummary(
            connected=False, 
            reason="auth_error", 
            quote_asset=quote_asset,
            target_btc_amount=target_btc
        )
        
    client = BinanceClient(api_key, api_secret)
    try:
        balances = await client.get_spot_balances(["BTC", quote_asset])
        
        btc_bal = balances.get("BTC", 0.0)
        quote_bal = balances.get(quote_asset, 0.0)
        
        # Add manual holdings (Cold Wallet)
        from dca_service.models import ColdWalletEntry
        manual_txs = session.exec(select(ColdWalletEntry)).all()
        manual_btc = sum(tx.btc_amount for tx in manual_txs)
        
        total_btc = btc_bal + manual_btc
        
        progress = min(total_btc / target_btc, 1.0) if target_btc > 0 else 0.0
        
        return HoldingsSummary(
            connected=True,
            btc_balance=total_btc, # Return total (Binance + Manual)
            quote_balance=quote_bal,
            quote_asset=quote_asset,
            target_btc_amount=target_btc,
            progress_ratio=progress,
            binance_btc_balance=btc_bal,
            cold_wallet_btc_balance=manual_btc
        )
    except Exception as e:
        return HoldingsSummary(
            connected=False, 
            reason=f"api_error: {str(e)}", 
            quote_asset=quote_asset,
            target_btc_amount=target_btc
        )
    finally:
        await client.close()
