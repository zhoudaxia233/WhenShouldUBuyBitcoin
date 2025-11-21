from sqlmodel import SQLModel, create_engine, Session
from .config import settings

# check_same_thread=False is needed for SQLite with FastAPI
engine = create_engine(
    settings.DATABASE_URL, 
    connect_args={"check_same_thread": False}
)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
