"""
Summary API Settings API
Handles saving/retrieving LLM summary API configuration with encryption.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
import httpx
from pydantic import BaseModel
from sqlmodel import Session, select

from dca_service.auth.dependencies import get_current_user
from dca_service.database import get_session
from dca_service.models import SummaryApiSettings, User
from dca_service.services.security import decrypt_text, encrypt_text

router = APIRouter()


class SummaryApiSettingsRequest(BaseModel):
    is_enabled: bool
    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: Optional[str] = None


class SummaryApiTestRequest(BaseModel):
    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: Optional[str] = None


@router.post("/summary-api/settings")
def save_summary_api_settings(
    settings: SummaryApiSettingsRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Save summary API settings with encrypted API key."""
    existing = session.exec(select(SummaryApiSettings)).first()

    if not existing and not settings.api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is required for new summary API configuration",
        )

    encrypted_key = encrypt_text(settings.api_key) if settings.api_key else None

    if existing:
        existing.is_enabled = settings.is_enabled
        existing.provider = settings.provider
        existing.base_url = settings.base_url
        existing.model = settings.model
        if encrypted_key:
            existing.api_key_encrypted = encrypted_key
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
    else:
        session.add(
            SummaryApiSettings(
                is_enabled=settings.is_enabled,
                provider=settings.provider,
                base_url=settings.base_url,
                model=settings.model,
                api_key_encrypted=encrypted_key,
            )
        )

    session.commit()
    return {"success": True, "message": "Summary API settings saved successfully"}


@router.post("/summary-api/settings/test")
def test_summary_api_settings(
    payload: SummaryApiTestRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Test summary API connectivity without persisting new values.
    Uses API key from payload if provided; otherwise falls back to stored key.
    """
    existing = session.exec(select(SummaryApiSettings)).first()

    api_key = payload.api_key
    if not api_key and existing:
        try:
            api_key = decrypt_text(existing.api_key_encrypted)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Stored API key decryption failed: {exc}") from exc

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is required for connectivity test (or save settings first).",
        )

    base_url = (payload.base_url or (existing.base_url if existing else "")).strip() or "https://api.openai.com/v1"
    model = (payload.model or (existing.model if existing else "")).strip() or "gpt-4o-mini"
    provider = (payload.provider or (existing.provider if existing else "")).strip() or "openai"

    if provider.lower() != "openai":
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    models_url = base_url.rstrip("/") + "/models"
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(
                models_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )

        if resp.status_code in (401, 403):
            raise HTTPException(status_code=400, detail="Authentication failed: invalid API key or insufficient permission.")
        if resp.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Provider error: HTTP {resp.status_code}")

        body = resp.json()
        model_available = False
        if isinstance(body, dict) and isinstance(body.get("data"), list):
            model_available = any((item or {}).get("id") == model for item in body["data"] if isinstance(item, dict))

        return {
            "success": True,
            "reachable": True,
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "model_available": model_available,
            "message": "Connectivity test succeeded",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Connectivity test failed: {exc}") from exc


@router.get("/summary-api/settings/status")
def get_summary_api_settings_status(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get summary API settings status without exposing full key."""
    settings = session.exec(select(SummaryApiSettings)).first()

    if not settings:
        return {"has_settings": False, "is_enabled": False}

    def mask_key(raw_key: str) -> str:
        if len(raw_key) < 8:
            return "****"
        return f"{raw_key[:4]}****{raw_key[-4:]}"

    try:
        decrypted = decrypt_text(settings.api_key_encrypted)
        masked = mask_key(decrypted)
    except Exception:
        masked = "****"

    return {
        "has_settings": True,
        "is_enabled": settings.is_enabled,
        "provider": settings.provider,
        "base_url": settings.base_url,
        "model": settings.model,
        "api_key_masked": masked,
        "updated_at": settings.updated_at.isoformat(),
    }
