"""
Tests for email settings API

Tests saving and retrieving email configuration with encryption.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from sqlmodel import Session, create_engine, SQLModel, select
from sqlmodel.pool import StaticPool

from dca_service.main import app
from dca_service.database import get_session
from dca_service.models import EmailSettings


class TestEmailSettingsAPI:
    """Tests for email settings API endpoints"""
    
    def test_save_email_settings_new(self, session, client):
        """Test saving new email settings"""
        payload = {
            "is_enabled": True,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "test@gmail.com",
            "smtp_password": "test_password",
            "email_to": "recipient@example.com"
        }
        
        response = client.post("/api/email/settings", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Verify stored in database
        settings = session.exec(select(EmailSettings)).first()
        assert settings is not None
        assert settings.is_enabled is True
        assert settings.smtp_host == "smtp.gmail.com"
        assert settings.smtp_port == 587
        assert settings.smtp_user == "test@gmail.com"
        # email_from should equal smtp_user
        assert settings.email_from == "test@gmail.com"
        assert settings.email_to == "recipient@example.com"
        # Password should be encrypted
        assert settings.smtp_password_encrypted != "test_password"
    
    def test_save_email_settings_update(self, session, client):
        """Test updating existing email settings"""
        # Create initial settings
        from dca_service.services.security import encrypt_text
        
        initial = EmailSettings(
            is_enabled=False,
            smtp_host="smtp.old.com",
            smtp_port=465,
            smtp_user="old@example.com",
            smtp_password_encrypted=encrypt_text("old_password"),
            email_from="old@example.com",  # Keep for backwards compatibility
            email_to="old_recipient@example.com"
        )
        session.add(initial)
        session.commit()
        
        # Update with new settings
        payload = {
            "is_enabled": True,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "new@gmail.com",
            "smtp_password": "new_password",
            "email_to": "new_recipient@example.com"
        }
        
        response = client.post("/api/email/settings", json=payload)
        
        assert response.status_code == 200
        
        # Verify updated (should only be one record)
        settings_list = session.exec(select(EmailSettings)).all()
        assert len(settings_list) == 1
        
        settings = settings_list[0]
        assert settings.is_enabled is True
        assert settings.smtp_host == "smtp.gmail.com"
        assert settings.smtp_user == "new@gmail.com"
        assert settings.email_from == "new@gmail.com"  # Should match smtp_user
    
    def test_save_email_settings_update_without_password(self, session, client):
        """Test updating settings without changing password"""
        from dca_service.services.security import encrypt_text, decrypt_text
        
        original_password = "original_password"
        initial = EmailSettings(
            is_enabled=False,
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@gmail.com",
            smtp_password_encrypted=encrypt_text(original_password),
            email_from="test@gmail.com",
            email_to="old@example.com"
        )
        session.add(initial)
        session.commit()
        
        # Update WITHOUT password (just toggle enabled)
        payload = {
            "is_enabled": True,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "test@gmail.com",
            "email_to": "new@example.com"
        }
        
        response = client.post("/api/email/settings", json=payload)
        
        assert response.status_code == 200
        
        # Verify password was NOT changed
        settings = session.exec(select(EmailSettings)).first()
        assert settings.is_enabled is True
        assert settings.email_to == "new@example.com"
        # Password should still be the original
        decrypted = decrypt_text(settings.smtp_password_encrypted)
        assert decrypted == original_password
    
    def test_save_email_settings_new_without_password_fails(self, session, client):
        """Test that new config requires password"""
        payload = {
            "is_enabled": True,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "test@gmail.com",
            "email_to": "recipient@example.com"
            # No password
        }
        
        response = client.post("/api/email/settings", json=payload)
        
        assert response.status_code == 400
        assert "Password is required" in response.json()["detail"]
    
    def test_get_email_settings_status_not_configured(self, session, client):
        """Test status endpoint when no settings exist"""
        response = client.get("/api/email/settings/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["has_settings"] is False
        assert data["is_enabled"] is False
    
    def test_get_email_settings_status_configured(self, session, client):
        """Test status endpoint with configured settings"""
        from dca_service.services.security import encrypt_text
        
        settings = EmailSettings(
            is_enabled=True,
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@gmail.com",
            smtp_password_encrypted=encrypt_text("password"),
            email_from="test@gmail.com",
            email_to="recipient@example.com"
        )
        session.add(settings)
        session.commit()
        
        response = client.get("/api/email/settings/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["has_settings"] is True
        assert data["is_enabled"] is True
        assert data["smtp_host"] == "smtp.gmail.com"
        assert data["smtp_port"] == 587
        # Email should be masked
        assert "****" in data["smtp_user_masked"]
        assert "@gmail.com" in data["smtp_user_masked"]
        # Password should NOT be in response
        assert "password" not in str(data)
    
    def test_encryption_decryption_roundtrip(self, session, client):
        """Test that password encryption/decryption works correctly"""
        from dca_service.services.security import encrypt_text, decrypt_text
        
        original_password = "my_secret_password_123"
        
        # Save settings
        payload = {
            "is_enabled": True,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "test@gmail.com",
            "smtp_password": original_password,
            "email_to": "recipient@example.com"
        }
        
        response = client.post("/api/email/settings", json=payload)
        assert response.status_code == 200
        
        # Retrieve from database and decrypt
        settings = session.exec(select(EmailSettings)).first()
        decrypted = decrypt_text(settings.smtp_password_encrypted)
        
        assert decrypted == original_password

    def test_toggle_email_settings(self, session, client):
        """Test toggling email enabled status"""
        # Setup initial settings
        from dca_service.services.security import encrypt_text
        settings = EmailSettings(
            is_enabled=False,
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@gmail.com",
            smtp_password_encrypted=encrypt_text("password"),
            email_from="test@gmail.com",
            email_to="recipient@example.com"
        )
        session.add(settings)
        session.commit()
        
        # Enable
        response = client.post("/api/email/settings/toggle", json={"is_enabled": True})
        assert response.status_code == 200
        assert response.json()["success"] is True
        
        updated = session.exec(select(EmailSettings)).first()
        assert updated.is_enabled is True
        
        # Disable
        response = client.post("/api/email/settings/toggle", json={"is_enabled": False})
        assert response.status_code == 200
        
        updated = session.exec(select(EmailSettings)).first()
        assert updated.is_enabled is False

    def test_toggle_email_settings_not_found(self, session, client):
        """Test toggling when no settings exist"""
        response = client.post("/api/email/settings/toggle", json={"is_enabled": True})
        
        assert response.status_code == 404
        assert "not configured" in response.json()["detail"]
