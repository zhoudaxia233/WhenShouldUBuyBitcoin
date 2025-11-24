"""
Tests for email notification service

Tests the mailer service including:
- EMAIL_ENABLED flag behavior
- SMTP connection and sending
- Error handling and graceful degradation
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import smtplib

from dca_service.services.mailer import send_email


class TestMailerDisabled:
    """Tests when EMAIL_ENABLED=False"""
    
    @patch('dca_service.services.mailer.settings')
    @patch('dca_service.services.mailer.smtplib.SMTP')
    def test_email_disabled_no_smtp_connection(self, mock_smtp, mock_settings):
        """When EMAIL_ENABLED=False, no SMTP connection should be attempted"""
        mock_settings.EMAIL_ENABLED = False
        
        send_email("Test Subject", "Test Body")
        
        # SMTP should never be instantiated
        mock_smtp.assert_not_called()
    
    @patch('dca_service.services.mailer.settings')
    def test_email_disabled_returns_immediately(self, mock_settings):
        """When EMAIL_ENABLED=False, function should return immediately"""
        mock_settings.EMAIL_ENABLED = False
        
        # Should not raise any exceptions
        result = send_email("Test", "Test")
        
        # Function returns None
        assert result is None


class TestMailerMissingConfig:
    """Tests when email is enabled but configuration is incomplete"""
    
    @patch('dca_service.services.mailer.settings')
    @ patch('dca_service.services.mailer.smtplib.SMTP')
    def test_missing_smtp_host(self, mock_smtp, mock_settings):
        """Missing SMTP host should prevent email sending"""
        mock_settings.EMAIL_ENABLED = True
        mock_settings.EMAIL_SMTP_HOST = ""  # Missing
        mock_settings.EMAIL_SMTP_USER = "user"
        mock_settings.EMAIL_SMTP_PASSWORD = "pass"
        mock_settings.EMAIL_FROM = "from@example.com"
        mock_settings.EMAIL_TO = "to@example.com"
        
        send_email("Test", "Test")
        
        # Should not attempt SMTP connection
        mock_smtp.assert_not_called()
    
    @patch('dca_service.services.mailer.settings')
    @patch('dca_service.services.mailer.smtplib.SMTP')
    def test_missing_email_addresses(self, mock_smtp, mock_settings):
        """Missing FROM or TO email should prevent sending"""
        mock_settings.EMAIL_ENABLED = True
        mock_settings.EMAIL_SMTP_HOST = "smtp.example.com"
        mock_settings.EMAIL_SMTP_USER = "user"
        mock_settings.EMAIL_SMTP_PASSWORD = "pass"
        mock_settings.EMAIL_FROM = ""  # Missing
        mock_settings.EMAIL_TO = ""  # Missing
        
        send_email("Test", "Test")
        
        mock_smtp.assert_not_called()


class TestMailerSuccess:
    """Tests successful email sending"""
    
    @patch('dca_service.services.mailer.settings')
    @patch('dca_service.services.mailer.smtplib.SMTP')
    def test_successful_email_send(self, mock_smtp, mock_settings):
        """Test successful email sending with proper SMTP flow"""
        # Configure settings
        mock_settings.EMAIL_ENABLED = True
        mock_settings.EMAIL_SMTP_HOST = "smtp.gmail.com"
        mock_settings.EMAIL_SMTP_PORT = 587
        mock_settings.EMAIL_SMTP_USER = "test@example.com"
        mock_settings.EMAIL_SMTP_PASSWORD = "testpass"
        mock_settings.EMAIL_FROM = "from@example.com"
        mock_settings.EMAIL_TO = "to@example.com"
        
        # Mock SMTP server
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        # Send email
        send_email("Test Subject", "Test Body")
        
        # Verify SMTP connection
        mock_smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=10)
        
        # Verify TLS and authentication
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("test@example.com", "testpass")
        
        # Verify message was sent
        mock_server.send_message.assert_called_once()
        sent_msg = mock_server.send_message.call_args[0][0]
        assert sent_msg['Subject'] == "Test Subject"
        assert sent_msg['From'] == "from@example.com"
        assert sent_msg['To'] == "to@example.com"
        assert "Test Body" in sent_msg.get_content()


class TestMailerErrorHandling:
    """Tests error handling and graceful degradation"""
    
    @patch('dca_service.services.mailer.settings')
    @patch('dca_service.services.mailer.smtplib.SMTP')
    def test_smtp_authentication_error(self, mock_smtp, mock_settings):
        """SMTP authentication errors should be caught and logged"""
        mock_settings.EMAIL_ENABLED = True
        mock_settings.EMAIL_SMTP_HOST = "smtp.gmail.com"
        mock_settings.EMAIL_SMTP_PORT = 587
        mock_settings.EMAIL_SMTP_USER = "test@example.com"
        mock_settings.EMAIL_SMTP_PASSWORD = "wrongpass"
        mock_settings.EMAIL_FROM = "from@example.com"
        mock_settings.EMAIL_TO = "to@example.com"
        
        # Mock authentication failure
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        # Should not raise exception
        send_email("Test", "Test")
        
        # Verify login was attempted
        mock_server.login.assert_called_once()
    
    @patch('dca_service.services.mailer.settings')
    @patch('dca_service.services.mailer.smtplib.SMTP')
    def test_smtp_connection_error(self, mock_smtp, mock_settings):
        """SMTP connection errors should be caught"""
        mock_settings.EMAIL_ENABLED = True
        mock_settings.EMAIL_SMTP_HOST = "invalid.smtp.com"
        mock_settings.EMAIL_SMTP_PORT = 587
        mock_settings.EMAIL_SMTP_USER = "test@example.com"
        mock_settings.EMAIL_SMTP_PASSWORD = "pass"
        mock_settings.EMAIL_FROM = "from@example.com"
        mock_settings.EMAIL_TO = "to@example.com"
        
        # Mock connection failure
        mock_smtp.side_effect = smtplib.SMTPConnectError(421, b"Service not available")
        
        # Should not raise exception
        send_email("Test", "Test")
    
    @patch('dca_service.services.mailer.settings')
    @patch('dca_service.services.mailer.smtplib.SMTP')
    def test_unexpected_error(self, mock_smtp, mock_settings):
        """Unexpected errors should be caught and logged"""
        mock_settings.EMAIL_ENABLED = True
        mock_settings.EMAIL_SMTP_HOST = "smtp.gmail.com"
        mock_settings.EMAIL_SMTP_PORT = 587
        mock_settings.EMAIL_SMTP_USER = "test@example.com"
        mock_settings.EMAIL_SMTP_PASSWORD = "pass"
        mock_settings.EMAIL_FROM = "from@example.com"
        mock_settings.EMAIL_TO = "to@example.com"
        
        # Mock unexpected error
        mock_smtp.side_effect = Exception("Unexpected error")
        
        # Should not raise exception
        send_email("Test", "Test")
