from fastapi import APIRouter
import cloudscraper
import logging

router = APIRouter(prefix="/debug", tags=["debug"])
logger = logging.getLogger(__name__)

@router.get("/scraper")
def debug_scraper():
    """
    Debug endpoint to test connectivity to BitInfoCharts.
    Returns the raw response status, headers, and content preview.
    """
    url = "https://bitinfocharts.com/top-100-richest-bitcoin-addresses.html"
    
    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, timeout=15)
        
        return {
            "status_code": response.status_code,
            "url": url,
            "headers_sent": dict(response.request.headers),
            "headers_received": dict(response.headers),
            "content_length": len(response.text),
            "content_preview": response.text[:1000],  # First 1000 chars
            "is_ok": response.ok
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "type": type(e).__name__
        }
