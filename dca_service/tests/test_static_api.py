"""
Tests for manual static file generation API endpoint
"""
import pytest
from unittest.mock import patch, MagicMock

from dca_service.models import User


class TestStaticGenerationAPI:
    """Tests for static file generation API endpoint"""
    
    @patch("dca_service.services.static_generator.trigger_static_generation")
    @patch("dca_service.auth.dependencies.get_current_user")
    def test_regenerate_endpoint_success(self, mock_auth, mock_trigger, client):
        """Test successful static file regeneration via API"""
        # Mock authentication
        mock_auth.return_value = User(email="test@example.com", password_hash="test")
        
        # Mock the background process
        mock_process = MagicMock()
        mock_process.pid = 54321
        mock_trigger.return_value = mock_process
        
        # Call the endpoint
        response = client.post("/api/static/regenerate")
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "background" in data["message"].lower() or data["background"] is True
        assert data["pid"] == 54321
        
        # Verify service was called
        mock_trigger.assert_called_once_with(background=True)
    
    @patch("dca_service.services.static_generator.trigger_static_generation")
    @patch("dca_service.auth.dependencies.get_current_user")
    def test_regenerate_endpoint_file_not_found(self, mock_auth, mock_trigger, client):
        """Test error handling when main.py is not found"""
        # Mock authentication
        mock_auth.return_value = User(email="test@example.com", password_hash="test")
        
        # Mock file not found error
        mock_trigger.side_effect = FileNotFoundError("main.py not found")
        
        # Call the endpoint
        response = client.post("/api/static/regenerate")
        
        # Verify error response
        assert response.status_code == 200  # Returns 200 with error in JSON
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["error"].lower()
    
    @patch("dca_service.services.static_generator.trigger_static_generation")
    @patch("dca_service.auth.dependencies.get_current_user")
    def test_regenerate_endpoint_generic_error(self, mock_auth, mock_trigger, client):
        """Test error handling for generic exceptions"""
        # Mock authentication
        mock_auth.return_value = User(email="test@example.com", password_hash="test")
        
        # Mock generic error
        mock_trigger.side_effect = Exception("Subprocess failed")
        
        # Call the endpoint
        response = client.post("/api/static/regenerate")
        
        # Verify error response
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data

