"""Tests for summary API settings endpoints."""

from unittest.mock import Mock, patch

from sqlmodel import select

from dca_service.models import SummaryApiSettings


class TestSummaryApiSettingsAPI:
    def test_save_new_settings(self, session, client):
        payload = {
            "is_enabled": True,
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "sk-test-1234567890",
        }

        response = client.post("/api/summary-api/settings", json=payload)
        assert response.status_code == 200
        assert response.json()["success"] is True

        settings = session.exec(select(SummaryApiSettings)).first()
        assert settings is not None
        assert settings.is_enabled is True
        assert settings.provider == "openai"
        assert settings.model == "gpt-4o-mini"
        assert settings.api_key_encrypted != payload["api_key"]

    def test_save_new_without_key_fails(self, session, client):
        payload = {
            "is_enabled": True,
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        }

        response = client.post("/api/summary-api/settings", json=payload)
        assert response.status_code == 400
        assert "API key is required" in response.json()["detail"]

    def test_update_without_key_keeps_existing_encrypted_key(self, session, client):
        create_resp = client.post(
            "/api/summary-api/settings",
            json={
                "is_enabled": True,
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "api_key": "sk-original-1111",
            },
        )
        assert create_resp.status_code == 200

        existing = session.exec(select(SummaryApiSettings)).first()
        original_cipher = existing.api_key_encrypted

        update_resp = client.post(
            "/api/summary-api/settings",
            json={
                "is_enabled": False,
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4.1-mini",
            },
        )
        assert update_resp.status_code == 200

        updated = session.exec(select(SummaryApiSettings)).first()
        assert updated.is_enabled is False
        assert updated.model == "gpt-4.1-mini"
        assert updated.api_key_encrypted == original_cipher

    def test_status_endpoint_masks_key(self, session, client):
        client.post(
            "/api/summary-api/settings",
            json={
                "is_enabled": True,
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
            },
        )

        response = client.get("/api/summary-api/settings/status")
        assert response.status_code == 200
        data = response.json()
        assert data["has_settings"] is True
        assert data["is_enabled"] is True
        assert data["provider"] == "openai"
        assert "****" in data["api_key_masked"]
        assert "abcdefghijklmnopqrstuvwxyz" not in str(data)

    def test_status_endpoint_empty(self, session, client):
        response = client.get("/api/summary-api/settings/status")
        assert response.status_code == 200
        data = response.json()
        assert data["has_settings"] is False
        assert data["is_enabled"] is False

    @patch("dca_service.api.summary_api_settings_api.httpx.Client")
    def test_connectivity_test_success_with_inline_key(self, mock_client_cls, session, client):
        mock_client = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4.1-mini"}]
        }
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        response = client.post(
            "/api/summary-api/settings/test",
            json={
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "api_key": "sk-test-inline-1234",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["reachable"] is True
        assert data["model_available"] is True

    @patch("dca_service.api.summary_api_settings_api.httpx.Client")
    def test_connectivity_test_auth_failure(self, mock_client_cls, session, client):
        mock_client = Mock()
        mock_response = Mock()
        mock_response.status_code = 401
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        response = client.post(
            "/api/summary-api/settings/test",
            json={
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "api_key": "sk-invalid",
            },
        )
        assert response.status_code == 400
        assert "Authentication failed" in response.json()["detail"]
