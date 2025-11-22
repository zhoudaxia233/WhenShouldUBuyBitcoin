from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager

from dca_service.config import settings
from dca_service.database import create_db_and_tables
from dca_service.api import routes, strategy_api, dca_api, binance_api, cold_wallet_api
from dca_service.scheduler import scheduler
from sqlmodel import Session, select
from dca_service.models import DCAStrategy
from dca_service.database import engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    scheduler.start()
    yield
    scheduler.stop()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Setup templates
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Include API routers
app.include_router(routes.router, prefix=settings.API_V1_STR)
app.include_router(strategy_api.router, prefix=settings.API_V1_STR)
app.include_router(dca_api.router, prefix=settings.API_V1_STR)
app.include_router(binance_api.router, prefix=settings.API_V1_STR)
app.include_router(cold_wallet_api.router, prefix=settings.API_V1_STR)

async def run_dca_cycle():
    """
    Placeholder for the main DCA execution logic.
    """
    with Session(engine) as session:
        strategy = session.exec(select(DCAStrategy)).first()
        if not strategy or not strategy.is_active:
            print("DCA cycle skipped: Strategy inactive or not found")
            return
        
        print("DCA cycle executed (placeholder)")

@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "project_name": settings.PROJECT_NAME})

@app.get("/strategy")
def read_strategy_page(request: Request):
    return templates.TemplateResponse("strategy.html", {"request": request, "project_name": settings.PROJECT_NAME})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dca_service.main:app", host="0.0.0.0", port=8000, reload=True)
