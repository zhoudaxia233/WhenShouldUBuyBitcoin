"""
Bitcoin ETP holdings API: IB1T shares entered by hand (no orders, no sync).
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from dca_service.auth.dependencies import get_current_user
from dca_service.database import get_session
from dca_service.models import User
from dca_service.services import etp_holdings
from dca_service.services.etp_holdings import EtpHoldingError, EtpHoldingInput

router = APIRouter(prefix="/etp-holdings", tags=["etp-holdings"])


def _raise(error: EtpHoldingError):
    raise HTTPException(status_code=error.status_code, detail=str(error))


@router.post("/{product}/preview")
def preview_etp_holding(
    product: str,
    data: EtpHoldingInput,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        return etp_holdings.preview(session, product, data)
    except EtpHoldingError as e:
        _raise(e)


@router.get("/{product}")
def read_etp_holding(
    product: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        return etp_holdings.describe(etp_holdings.get(session, product))
    except EtpHoldingError as e:
        _raise(e)


@router.put("/{product}")
def save_etp_holding(
    product: str,
    data: EtpHoldingInput,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        return etp_holdings.describe(etp_holdings.save(session, product, data))
    except EtpHoldingError as e:
        _raise(e)


@router.delete("/{product}", status_code=204)
def delete_etp_holding(
    product: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        etp_holdings.delete(session, product)
    except EtpHoldingError as e:
        _raise(e)
    return Response(status_code=204)
