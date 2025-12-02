from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager

from dca_service.config import settings
from dca_service.database import create_db_and_tables
from dca_service.api import routes, strategy_api, dca_api, binance_api, email_settings_api, wallet_api, stats_api, auth_api
from starlette.middleware.sessions import SessionMiddleware
from dca_service.scheduler import scheduler
from sqlmodel import Session, select
from dca_service.models import DCAStrategy
from dca_service.database import engine
from dca_service.models import User
from dca_service.auth.dependencies import get_current_user

from dca_service.core.logging import logger
from fastapi.responses import RedirectResponse
import time

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    logger.info("Starting DCA Scheduler...")
    scheduler.start()
    logger.info("DCA Scheduler startup complete")
    yield
    logger.info("Stopping DCA Scheduler...")
    scheduler.stop()
    logger.info("DCA Scheduler shutdown complete")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Exception handler for 401 Unauthorized - redirect to login
@app.exception_handler(401)
async def unauthorized_exception_handler(request: Request, exc: HTTPException):
    """Redirect to login page when user is not authenticated"""
    return RedirectResponse(url="/api/auth/login", status_code=303)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = (time.time() - start_time) * 1000
    # Filter out health checks or noise if needed, but for now log all
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration:.2f} ms)")
    return response

# Add session middleware for authentication
# CRITICAL: SESSION_SECRET must be set in environment variables
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET,
    session_cookie=settings.SESSION_COOKIE_NAME,
    max_age=settings.SESSION_MAX_AGE,
    same_site=settings.SESSION_COOKIE_SAMESITE,
    https_only=settings.SESSION_COOKIE_HTTPS_ONLY,
)

# Setup templates
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Mount docs folder for analysis charts and data
# This serves the btc_metrics.csv analysis HTML files
DOCS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "docs"
if DOCS_DIR.exists():
    app.mount("/analysis", StaticFiles(directory=str(DOCS_DIR), html=True), name="analysis")

# Include API routers
app.include_router(routes.router, prefix=settings.API_V1_STR)
app.include_router(strategy_api.router, prefix=settings.API_V1_STR)
app.include_router(dca_api.router, prefix=settings.API_V1_STR)
app.include_router(binance_api.router, prefix=settings.API_V1_STR)
app.include_router(wallet_api.router, prefix=settings.API_V1_STR)
app.include_router(email_settings_api.router, prefix=settings.API_V1_STR)
app.include_router(stats_api.router, prefix=settings.API_V1_STR)
app.include_router(auth_api.router, prefix=settings.API_V1_STR)

# SSE endpoint for real-time updates
from dca_service.sse import sse_manager

@app.get("/api/events")
async def events(request: Request):
    """Server-Sent Events endpoint for real-time updates"""
    return await sse_manager.connect(request)

async def run_dca_cycle():
    """
    Placeholder for the main DCA execution logic.
    """
    with Session(engine) as session:
        strategy = session.exec(select(DCAStrategy)).first()
        if not strategy or not strategy.is_active:
            logger.info("DCA cycle skipped: Strategy inactive or not found")
            return
        
        logger.info("DCA cycle executed (placeholder)")

@app.get("/")
def read_root(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="index.html", context={"user": user, "project_name": settings.PROJECT_NAME})

@app.get("/strategy")
def read_strategy_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="strategy.html", context={"user": user, "project_name": settings.PROJECT_NAME})

@app.get("/settings/binance")
def read_binance_settings_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="binance_settings.html", context={"user": user, "project_name": settings.PROJECT_NAME})

@app.get("/stats")
def read_stats_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="stats.html", context={"user": user, "project_name": settings.PROJECT_NAME})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dca_service.main:app", host="0.0.0.0", port=8000, reload=True)
