from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager

from dca_service.config import settings
from dca_service.database import create_db_and_tables
from dca_service.api import routes

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Setup templates
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Include API router
app.include_router(routes.router, prefix=settings.API_V1_STR)

@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "project_name": settings.PROJECT_NAME})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dca_service.main:app", host="0.0.0.0", port=8000, reload=True)
