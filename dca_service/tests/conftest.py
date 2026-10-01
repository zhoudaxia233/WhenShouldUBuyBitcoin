import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from dca_service.main import app
from dca_service.database import get_session
from dca_service.models import User, GlobalSettings
from dca_service.auth.dependencies import get_current_user

@pytest.fixture(autouse=True)
def block_real_static_generation(monkeypatch):
    """Never launch the real main.py from tests.

    Successful DCA transactions trigger static generation, which would otherwise
    start a real background main.py that fetches live data and rewrites tracked
    files. Tests that need Popen patch it themselves, which overrides this guard.
    """
    import dca_service.services.static_generator as static_generator

    monkeypatch.setattr(static_generator, "_background_process", None)
    monkeypatch.setattr(static_generator, "_background_started_at", None)

    real_popen = subprocess.Popen

    def guarded_popen(args, *popen_args, **popen_kwargs):
        if "main.py" in str(args):
            raise RuntimeError("Tests must not launch the real main.py")
        return real_popen(args, *popen_args, **popen_kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded_popen)


# Rounded from real history; keeps AHR999 = 1.0 in the 25-50% (p50) band.
TEST_AHR999_PERCENTILES = {
    "p10": 0.48,
    "p25": 0.66,
    "p50": 1.1,
    "p75": 1.7,
    "p90": 3.5,
}


@pytest.fixture(autouse=True)
def fixed_ahr999_percentiles(monkeypatch):
    """Keep DCA engine decisions independent of generated docs/data files.

    Without this, band thresholds come from docs/data/btc_metrics.csv when it
    exists and from hardcoded fallbacks when it does not, so results differ
    between a dev machine and a clean CI checkout. Tests that need other
    thresholds patch the function themselves, which overrides this fixture.
    """
    monkeypatch.setattr(
        "dca_service.services.dca_engine.calculate_ahr999_percentile_thresholds",
        lambda: dict(TEST_AHR999_PERCENTILES),
    )


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", 
        connect_args={"check_same_thread": False}, 
        poolclass=StaticPool
    )
    # Create all tables from SQLModel metadata
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        # Initialize GlobalSettings singleton (required by some services)
        global_settings = GlobalSettings(id=1, cold_wallet_balance=0.0)
        session.add(global_settings)
        
        # Create a test user for authentication bypass
        # Use a proper bcrypt hash for "testpassword123" so auth tests can verify it
        from dca_service.auth.password import hash_password
        test_user = User(
            id=1,
            email="test@example.com",
            password_hash=hash_password("testpassword123"),
            is_active=True,
            is_admin=True
        )
        session.add(test_user)
        session.commit()
        session.refresh(test_user)
        
        yield session

@pytest.fixture(name="test_user")
def test_user_fixture(session: Session):
    """Provide access to the test user created in session fixture."""
    from sqlmodel import select
    user = session.exec(select(User).where(User.id == 1)).first()
    return user

@pytest.fixture(name="client")
def client_fixture(session: Session, test_user: User):
    def get_session_override():
        return session
    
    def get_current_user_override():
        """Override authentication to return test user for all requests."""
        return test_user

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_current_user] = get_current_user_override
    
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
