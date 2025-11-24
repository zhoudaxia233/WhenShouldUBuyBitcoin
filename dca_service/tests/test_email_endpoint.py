"""
Tests for email test endpoint

Tests the /api/email/test endpoint for SMTP configuration verification.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from dca_service.main import app

client = TestClient(app)


class TestEmailTestEndpoint:
    """Tests for POST /api/email/test"""
    
    @patch('dca_service.services.mailer.send_email')
    @patch('dca_service.config.settings')
    def test_email_disabled(self, mock_settings, mock_send_email):
        """When email is disabled, endpoint should return error"""
        mock_settings.EMAIL_ENABLED = False
        
        response = client.post("/api/email/test")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "disabled" in data["error"].lower()
        
        # send_email should not be called
        mock_send_email.assert_not_called()
    
    @patch('dca_service.services.mailer.send_email')
    @patch('dca_service.config.settings')
    def test_email_enabled_success(self, mock_settings, mock_send_email):
        """When email is enabled and sending succeeds, return success"""
        mock_settings.EMAIL_ENABLED = True
        mock_settings.EMAIL_SMTP_HOST = "smtp.gmail.com"
        mock_settings.EMAIL_SMTP_PORT = 587
        mock_settings.EMAIL_FROM = "from@example.com"
        mock_settings.EMAIL_TO = "to@example.com"
        
        # Mock successful send
        mock_send_email.return_value = None
        
        response = client.post("/api/email/test")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Verify send_email was called with test message
        mock_send_email.assert_called_once()
        call_args = mock_send_email.call_args[0]
        assert "Test" in call_args[0]  # Subject contains "Test"
        assert "test email" in call_args[1].lower()  # Body mentions test
    
    @patch('dca_service.services.mailer.send_email')
    @patch('dca_service.config.settings')
    def test_email_send_exception(self, mock_settings, mock_send_email):
        """When send_email raises exception, endpoint should catch it"""
        mock_settings.EMAIL_ENABLED = True
        mock_settings.EMAIL_SMTP_HOST = "smtp.gmail.com"
        mock_settings.EMAIL_SMTP_PORT = 587
        mock_settings.EMAIL_FROM = "from@example.com"
        mock_settings.EMAIL_TO = "to@example.com"
        
        # Mock exception during send
        mock_send_email.side_effect = Exception("SMTP connection failed")
        
        response = client.post("/api/email/test")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data
        assert "SMTP connection failed" in data["error"]
