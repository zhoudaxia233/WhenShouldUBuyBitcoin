from fastapi import APIRouter, Depends

from dca_service.auth.dependencies import get_current_admin_user
from dca_service.models import User
from dca_service.services.distribution_scraper import (
    fetch_distribution_with_status,
    get_distribution_diagnostics,
)


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/data-sources/bitinfocharts")
def get_bitinfocharts_diagnostics(
    current_user: User = Depends(get_current_admin_user),
):
    return {
        "name": "BitInfoCharts Bitcoin wealth distribution",
        "diagnostics": get_distribution_diagnostics(),
    }


@router.post("/data-sources/bitinfocharts/refresh")
def refresh_bitinfocharts_distribution(
    current_user: User = Depends(get_current_admin_user),
):
    try:
        snapshot = fetch_distribution_with_status(
            use_cache=False,
            allow_static_fallback=False,
            allow_stale_cache=False,
        )
        data = snapshot.get("data") or []
        return {
            "success": True,
            "message": "BitInfoCharts live refresh completed.",
            "tier_count": len(data),
            "data_status": snapshot.get("data_status", "live"),
            "diagnostics": get_distribution_diagnostics(),
        }
    except ValueError:
        return {
            "success": False,
            "message": "BitInfoCharts live refresh failed. See diagnostics.",
            "tier_count": 0,
            "data_status": "unavailable",
            "diagnostics": get_distribution_diagnostics(),
        }
