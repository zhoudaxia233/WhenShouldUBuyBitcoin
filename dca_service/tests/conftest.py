import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from dca_service.main import app
from dca_service.database import get_session

@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", 
        connect_args={"check_same_thread": False}, 
        poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_send_email():
    """
    Global mock to prevent any real emails from being sent during tests.
    This fixture is automatically used for all tests.
    """
    from unittest.mock import patch
    with patch("dca_service.services.mailer.send_email") as mock:
        yield mock
