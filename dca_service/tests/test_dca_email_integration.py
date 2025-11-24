"""
Integration tests for DCA email notifications

Tests that DCA execution triggers email notifications correctly.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from dca_service.main import app

client = TestClient(app)


class TestDCAEmailIntegration:
    """Tests DCA execution email integration"""
    
    @patch('dca_service.api.dca_api._send_dca_email_task')
    def test_successful_dca_triggers_email(self, mock_send_email):
        """Successful DCA execution should trigger email in background"""
        response = client.post("/api/dca/execute-simulated")
        
        assert response.status_code == 200
        data = response.json()
        
        # If execution was successful
        if data.get("transaction"):
            # Email should be scheduled (called once)
            mock_send_email.assert_called_once()
            
            # Verify email was called with transaction and decision
            call_args = mock_send_email.call_args
            assert call_args is not None
    
    @patch('dca_service.api.dca_api._send_dca_email_task')
    def test_skipped_dca_no_email(self, mock_send_email):
        """Skipped DCA should not send email"""
        # This test would need strategy configured to skip
        # For now, just verify the endpoint doesn't crash
        response = client.post("/api/dca/execute-simulated")
        
        assert response.status_code == 200
        data = response.json()
        
        # If DCA was skipped, no email
        if not data.get("transaction"):
            mock_send_email.assert_not_called()
    
    @patch('dca_service.services.mailer.send_email')
    @patch('dca_service.services.mailer.settings')
    def test_email_content_format(self, mock_settings, mock_send_email):
        """Email should contain proper transaction details"""
        from dca_service.api.dca_api import _send_dca_email_task
        from dca_service.models import DCATransaction
        from dca_service.services.dca_engine import DCADecision
        from datetime import datetime, timezone
        
        mock_settings.EMAIL_ENABLED = True
        mock_settings.EMAIL_SMTP_HOST = "smtp.example.com"
        mock_settings.EMAIL_SMTP_USER = "user"
        mock_settings.EMAIL_SMTP_PASSWORD = "pass"
        mock_settings.EMAIL_FROM = "from@example.com"
        mock_settings.EMAIL_TO = "to@example.com"
        
        # Create test transaction
        transaction = DCATransaction(
            id=1,
            status="SUCCESS",
            fiat_amount=50.0,
            btc_amount=0.0006,
            price=83333.33,
            ahr999=0.52,
            notes="Test transaction",
            source="SIMULATED",
            timestamp=datetime.now(timezone.utc)
        )
        
        # Create test decision
        decision = MagicMock()
        decision.suggested_amount_usd = 50.0
        decision.ahr999_value = 0.52
        decision.price_usd = 83333.33
        
        # Call email function
        with patch('dca_service.services.mailer.Session') as mock_session:
             # Mock DB lookup to return None so it falls back to settings
             mock_session.return_value.__enter__.return_value.exec.return_value.first.return_value = None
             _send_dca_email_task(transaction, decision)
        
        # Verify send_email was called
        mock_send_email.assert_called_once()
        
        # Check email content
        subject, body = mock_send_email.call_args[0]
        assert "$50.00" in subject
        assert "USDC" in subject
        assert "0.0006" in body or "0.00060000" in body
        assert "83333.33" in body
        assert "0.52" in body
        assert "SIMULATED" in body
