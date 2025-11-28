from fastapi import APIRouter
import requests
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
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        
        return {
            "status_code": response.status_code,
            "url": url,
            "headers_sent": headers,
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
