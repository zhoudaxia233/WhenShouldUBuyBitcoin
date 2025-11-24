"""
Tests for email test endpoint

Tests the /api/email/test endpoint for SMTP configuration verification.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from dca_service.main import app

class TestEmailTestEndpoint:
    """Tests for POST /api/email/test"""
    
    @patch('dca_service.services.mailer._get_email_config')
    @patch('dca_service.services.mailer.send_email')
    def test_email_disabled(self, mock_send_email, mock_get_config, client):
        """When email is disabled (config returns None), endpoint should return error"""
        # Mock config to return None (disabled/not configured)
        mock_get_config.return_value = None
        
        response = client.post("/api/email/test")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not configured" in data["error"].lower()
        
        # send_email should not be called
        mock_send_email.assert_not_called()
    
    @patch('dca_service.services.mailer._get_email_config')
    @patch('dca_service.services.mailer.send_email')
    def test_email_enabled_success(self, mock_send_email, mock_get_config, client):
        """When email is enabled and sending succeeds, return success"""
        # Mock valid config
        mock_get_config.return_value = {
            "enabled": True,
            "smtp_host": "smtp.test.com",
            "smtp_port": 587,
            "smtp_user": "user",
            "email_from": "from@test.com",
            "email_to": "to@test.com",
            "source": "test"
        }
        
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
        assert "test message" in call_args[1].lower()  # Body mentions test
    
    @patch('dca_service.services.mailer._get_email_config')
    @patch('dca_service.services.mailer.send_email')
    def test_email_send_exception(self, mock_send_email, mock_get_config, client):
        """When send_email raises exception, endpoint should catch it"""
        # Mock valid config
        mock_get_config.return_value = {
            "enabled": True,
            "smtp_host": "smtp.test.com",
            "smtp_port": 587,
            "smtp_user": "user",
            "email_from": "from@test.com",
            "email_to": "to@test.com",
            "source": "test"
        }
        
        # Mock exception during send
        mock_send_email.side_effect = Exception("SMTP connection failed")
        
        response = client.post("/api/email/test")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data
        assert "SMTP connection failed" in data["error"]
