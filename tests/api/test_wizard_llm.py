# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour l'endpoint de test de connexion LLM.

POST /api/wizard/test-llm
- Valide la connexion Claude ou Ollama
- Retourne un status détaillé avec temps de réponse
"""

import pytest
from unittest.mock import patch, MagicMock
from flask import Flask

from app.api.wizard import wizard_bp


@pytest.fixture
def app():
    """Crée une application Flask de test."""
    from app.api import admin as _admin_module
    _original_admins = _admin_module.ADMIN_EMAILS.copy()
    _admin_module.ADMIN_EMAILS.add("admin@test.com")
    try:
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(wizard_bp, url_prefix="/api/wizard")
        yield app
    finally:
        _admin_module.ADMIN_EMAILS.clear()
        _admin_module.ADMIN_EMAILS.update(_original_admins)


@pytest.fixture
def client(app):
    """Client de test Flask."""
    raw_client = app.test_client()
    original_open = raw_client.open

    def open_with_admin(*args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Authorization", _admin_auth_headers()["Authorization"])
        kwargs["headers"] = headers
        return original_open(*args, **kwargs)

    raw_client.open = open_with_admin
    return raw_client


def _admin_auth_headers() -> dict:
    """Crée un JWT admin pour les endpoints wizard protégés."""
    import time
    import jwt as _pyjwt
    from app.api.auth import JWT_SECRET, JWT_ALGORITHM

    token = _pyjwt.encode(
        {
            "sub": "99999",
            "email": "admin@test.com",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


class TestLLMEndpoint:
    """Tests pour POST /api/wizard/test-llm."""

    def test_missing_json_body(self, client):
        """Retourne 400 si pas de body JSON."""
        response = client.post("/api/wizard/test-llm")
        assert response.status_code in (400, 415)

    def test_missing_provider(self, client):
        """Retourne 400 si provider manquant."""
        response = client.post(
            "/api/wizard/test-llm",
            json={"model": "claude-sonnet-4-20250514"},
        )
        assert response.status_code == 400
        assert "provider" in response.json.get("error", "")

    def test_invalid_provider(self, client):
        """Retourne 400 si provider invalide."""
        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "openai",
                "model": "gpt-4",
            },
        )
        assert response.status_code == 400
        assert "provider" in response.json.get("error", "")

    def test_missing_model(self, client):
        """Retourne 400 si model manquant."""
        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "claude",
                "api_key": "sk-ant-test",
            },
        )
        assert response.status_code == 400
        assert "model" in response.json.get("error", "")

    def test_claude_missing_api_key(self, client):
        """Retourne 400 si api_key manquante pour Claude."""
        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "claude",
                "model": "claude-sonnet-4-20250514",
            },
        )
        assert response.status_code == 400
        assert "api_key" in response.json.get("error", "")

    @patch("app.adapters.llm.claude_adapter.ClaudeAdapter")
    def test_claude_success(self, mock_adapter_class, client):
        """Retourne success pour Claude avec API key valide."""
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = MagicMock(content="Connection successful")
        mock_adapter_class.return_value = mock_adapter

        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "claude",
                "api_key": "sk-ant-api03-test-key",
                "model": "claude-sonnet-4-20250514",
            },
        )

        assert response.status_code == 200
        data = response.json
        assert data["success"] is True
        assert data["provider"] == "claude"
        assert data["model"] == "claude-sonnet-4-20250514"
        assert "response_time_ms" in data

    @patch("app.adapters.llm.claude_adapter.ClaudeAdapter")
    def test_claude_invalid_api_key(self, mock_adapter_class, client):
        """Retourne erreur pour Claude avec API key invalide."""
        mock_adapter_class.side_effect = ValueError("ANTHROPIC_API_KEY invalide")

        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "claude",
                "api_key": "invalid-key",
                "model": "claude-sonnet-4-20250514",
            },
        )

        assert response.status_code == 200
        data = response.json
        assert data["success"] is False
        assert "error" in data

    @patch("app.adapters.llm.ollama_adapter.OllamaAdapter")
    def test_ollama_success(self, mock_adapter_class, client):
        """Retourne success pour Ollama accessible."""
        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = True
        mock_adapter.list_models.return_value = ["llama3.2", "mistral"]
        mock_adapter.complete.return_value = MagicMock(content="OK")
        mock_adapter_class.return_value = mock_adapter

        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "ollama",
                "ollama_url": "http://localhost:11434",
                "model": "llama3.2",
            },
        )

        assert response.status_code == 200
        data = response.json
        assert data["success"] is True
        assert data["provider"] == "ollama"
        assert data["model"] == "llama3.2"

    @patch("app.adapters.llm.ollama_adapter.OllamaAdapter")
    def test_ollama_not_available(self, mock_adapter_class, client):
        """Retourne erreur si Ollama non accessible."""
        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = False
        mock_adapter_class.return_value = mock_adapter

        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "ollama",
                "ollama_url": "http://localhost:11434",
                "model": "llama3.2",
            },
        )

        assert response.status_code == 200
        data = response.json
        assert data["success"] is False
        assert "Unable to connect" in data.get("error", "")

    @patch("app.adapters.llm.ollama_adapter.OllamaAdapter")
    def test_ollama_model_not_found(self, mock_adapter_class, client):
        """Retourne erreur si modèle Ollama non trouvé."""
        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = True
        mock_adapter.list_models.return_value = ["mistral", "phi3"]
        mock_adapter_class.return_value = mock_adapter

        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "ollama",
                "ollama_url": "http://localhost:11434",
                "model": "llama3.2",
            },
        )

        assert response.status_code == 200
        data = response.json
        assert data["success"] is False
        assert "not found" in data.get("error", "")

    def test_ollama_default_url(self, client):
        """Utilise l'URL par défaut si non spécifiée."""
        with patch("app.adapters.llm.ollama_adapter.OllamaAdapter") as mock_adapter_class:
            mock_adapter = MagicMock()
            mock_adapter.is_available.return_value = False
            mock_adapter_class.return_value = mock_adapter

            client.post(
                "/api/wizard/test-llm",
                json={
                    "provider": "ollama",
                    "model": "llama3.2",
                },
            )

            mock_adapter_class.assert_called_with(
                model="llama3.2",
                base_url="http://localhost:11434",
            )
