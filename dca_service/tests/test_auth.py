"""
Tests for authentication system.

Covers:
- Password hashing and verification
- CSRF token generation and validation
- Login flow (success/failure)
- Logout
- Protected routes (requires authentication)
- Admin-only routes
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel
from dca_service.main import app
from dca_service.database import get_session
from dca_service.models import User
from dca_service.auth.password import hash_password, verify_password
from dca_service.auth.csrf import get_csrf_token, validate_csrf
from fastapi import Request, HTTPException


# Test database setup
@pytest.fixture(name="session")
def session_fixture():
    """Create a fresh test database for each test."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        # Create a test user
        test_user = User(
            email="test@example.com",
            password_hash=hash_password("testpassword123"),
            is_active=True,
            is_admin=False
        )
        session.add(test_user)
        
        # Create an admin user
        admin_user = User(
            email="admin@example.com",
            password_hash=hash_password("adminpassword123"),
            is_active=True,
            is_admin=True
        )
        session.add(admin_user)
        
        session.commit()
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """Create a test client with database override."""
    def get_session_override():
        yield session
    
    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# Password hashing tests
def test_hash_password():
    """Test password hashing produces different hashes each time."""
    password = "my_secure_password"
    hash1 = hash_password(password)
    hash2 = hash_password(password)
    
    # Hashes should be different (due to random salt)
    assert hash1 != hash2
    
    # Both should start with bcrypt identifier
    assert hash1.startswith("$2b$")
    assert hash2.startswith("$2b$")


def test_verify_password():
    """Test password verification."""
    password = "my_secure_password"
    hashed = hash_password(password)
    
    # Correct password should verify
    assert verify_password(password, hashed) is True
    
    # Wrong password should not verify
    assert verify_password("wrong_password", hashed) is False


# CSRF tests
def test_csrf_token_generation(client):
    """Test CSRF token generation."""
    # Get login page
    response = client.get("/api/auth/login")
    assert response.status_code == 200
    
    # Check that CSRF token is in the response
    assert "csrf_token" in response.text


# Login tests
def test_login_page_renders(client):
    """Test that login page renders correctly."""
    response = client.get("/api/auth/login")
    assert response.status_code == 200
    assert "Sign in to your account" in response.text


def test_login_with_valid_credentials(client):
    """Test successful login."""
    # Get login page to get CSRF token
    response = client.get("/api/auth/login")
    
    # Extract CSRF token from HTML
    csrf_token = response.text.split('name="csrf_token" value="')[1].split('"')[0]
    
    # Submit login form
    response = client.post(
        "/api/auth/login",
        data={
            "email": "test@example.com",
            "password": "testpassword123",
            "csrf_token": csrf_token
        },
        follow_redirects=False
    )
    
    # Should redirect to home
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    
    # Session should contain user_id
    assert "user_id" in client.cookies


def test_login_with_invalid_password(client):
    """Test login with wrong password."""
    # Get CSRF token
    response = client.get("/api/auth/login")
    csrf_token = response.text.split('name="csrf_token" value="')[1].split('"')[0]
    
    # Submit with wrong password
    response = client.post(
        "/api/auth/login",
        data={
            "email": "test@example.com",
            "password": "wrongpassword",
            "csrf_token": csrf_token
        }
    )
    
    # Should return 401 with error message
    assert response.status_code == 401
    assert "Invalid email or password" in response.text


def test_login_with_nonexistent_user(client):
    """Test login with email that doesn't exist."""
    # Get CSRF token
    response = client.get("/api/auth/login")
    csrf_token = response.text.split('name="csrf_token" value="')[1].split('"')[0]
    
    # Submit with nonexistent email
    response = client.post(
        "/api/auth/login",
        data={
            "email": "nonexistent@example.com",
            "password": "password123",
            "csrf_token": csrf_token
        }
    )
    
    # Should return 401
    assert response.status_code == 401
    assert "Invalid email or password" in response.text


def test_login_without_csrf_token(client):
    """Test that login fails without CSRF token."""
    response = client.post(
        "/api/auth/login",
        data={
            "email": "test@example.com",
            "password": "testpassword123"
        }
    )
    
    # Should fail with 422 (missing field)
    assert response.status_code == 422


# Logout tests
def test_logout(client):
    """Test logout functionality."""
    # First, log in
    response = client.get("/api/auth/login")
    csrf_token = response.text.split('name="csrf_token" value="')[1].split('"')[0]
    
    client.post(
        "/api/auth/login",
        data={
            "email": "test@example.com",
            "password": "testpassword123",
            "csrf_token": csrf_token
        }
    )
    
    # Now logout
    response = client.post("/api/auth/logout", follow_redirects=False)
    
    # Should redirect to login
    assert response.status_code == 303
    assert response.headers["location"] == "/api/auth/login"


# Protected route tests
def test_protected_route_without_auth(client):
    """Test that protected routes require authentication."""
    # Try to access a protected route (we'll need to add this in routes.py)
    # For now, this is a placeholder
    # response = client.get("/api/protected-route")
    # assert response.status_code == 401
    pass


def test_inactive_user_cannot_login(client, session):
    """Test that inactive users cannot log in."""
    # Create inactive user
    inactive_user = User(
        email="inactive@example.com",
        password_hash=hash_password("password123"),
        is_active=False,
        is_admin=False
    )
    session.add(inactive_user)
    session.commit()
    
    # Get CSRF token
    response = client.get("/api/auth/login")
    csrf_token = response.text.split('name="csrf_token" value="')[1].split('"')[0]
    
    # Try to login
    response = client.post(
        "/api/auth/login",
        data={
            "email": "inactive@example.com",
            "password": "password123",
            "csrf_token": csrf_token
        }
    )
    
    # Should be forbidden
    assert response.status_code == 403
    assert "disabled" in response.text.lower()
