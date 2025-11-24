from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager

from dca_service.config import settings
from dca_service.database import create_db_and_tables
from dca_service.api import routes, strategy_api, dca_api, binance_api, cold_wallet_api, email_settings_api
from dca_service.scheduler import scheduler
from sqlmodel import Session, select
from dca_service.models import DCAStrategy
from dca_service.database import engine

from dca_service.core.logging import logger
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

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = (time.time() - start_time) * 1000
    # Filter out health checks or noise if needed, but for now log all
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration:.2f} ms)")
    return response

# Setup templates
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Include API routers
app.include_router(routes.router, prefix=settings.API_V1_STR)
app.include_router(strategy_api.router, prefix=settings.API_V1_STR)
app.include_router(dca_api.router, prefix=settings.API_V1_STR)
app.include_router(binance_api.router, prefix=settings.API_V1_STR)
app.include_router(cold_wallet_api.router, prefix=settings.API_V1_STR)
app.include_router(email_settings_api.router, prefix=settings.API_V1_STR)

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
def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "project_name": settings.PROJECT_NAME})

@app.get("/strategy")
def read_strategy_page(request: Request):
    return templates.TemplateResponse("strategy.html", {"request": request, "project_name": settings.PROJECT_NAME})

@app.get("/settings/binance")
def read_binance_settings_page(request: Request):
    return templates.TemplateResponse("binance_settings.html", {"request": request, "project_name": settings.PROJECT_NAME})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dca_service.main:app", host="0.0.0.0", port=8000, reload=True)
