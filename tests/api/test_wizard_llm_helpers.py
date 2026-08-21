# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les helpers de connexion LLM dans wizard.py.

Couvre:
- _test_claude_connection() - test connexion Claude
- _test_ollama_connection() - test connexion Ollama
"""

import pytest
from unittest.mock import patch, MagicMock
from flask import Flask

from app.api.wizard import (
    wizard_bp,
    _test_claude_connection,
    _test_ollama_connection,
)


@pytest.fixture
def app():
    """Cree une application Flask de test."""
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
    """Create an admin JWT for protected wizard endpoints."""
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


class TestTestClaudeConnection:
    """Tests pour _test_claude_connection()."""

    def test_successful_connection(self):
        """Retourne succes si connexion reussie."""
        with patch("app.adapters.llm.claude_adapter.ClaudeAdapter") as mock_claude:
            mock_instance = MagicMock()
            mock_instance.complete.return_value = "Connection successful"
            mock_claude.return_value = mock_instance

            result = _test_claude_connection(
                api_key="sk-test-key",
                model="claude-3-sonnet-20240229",
            )

            assert result["success"] is True
            assert result["provider"] == "claude"
            assert result["model"] == "claude-3-sonnet-20240229"
            assert "response_time_ms" in result

    def test_invalid_api_key(self):
        """Retourne erreur si cle API invalide."""
        with patch("app.adapters.llm.claude_adapter.ClaudeAdapter") as mock_claude:
            mock_claude.side_effect = ValueError("Invalid API key")

            result = _test_claude_connection(
                api_key="invalid-key",
                model="claude-3-sonnet-20240229",
            )

            assert result["success"] is False
            assert "Invalid API key" in result["error"]

    def test_authentication_error(self):
        """Retourne message d'erreur pour erreur d'authentification."""
        with patch("app.adapters.llm.claude_adapter.ClaudeAdapter") as mock_claude:
            mock_instance = MagicMock()
            mock_instance.complete.side_effect = Exception("API key authentication failed")
            mock_claude.return_value = mock_instance

            result = _test_claude_connection(
                api_key="bad-key",
                model="claude-3-sonnet-20240229",
            )

            assert result["success"] is False
            assert "invalide" in result["error"].lower() or "api key" in result["error"].lower()

    def test_rate_limit_error(self):
        """Retourne message d'erreur pour limite de requetes."""
        with patch("app.adapters.llm.claude_adapter.ClaudeAdapter") as mock_claude:
            mock_instance = MagicMock()
            mock_instance.complete.side_effect = Exception("Rate limit exceeded")
            mock_claude.return_value = mock_instance

            result = _test_claude_connection(
                api_key="sk-test-key",
                model="claude-3-sonnet-20240229",
            )

            assert result["success"] is False
            assert "limite" in result["error"].lower() or "rate limit" in result["error"].lower()

    def test_generic_exception(self):
        """Gere les exceptions generiques."""
        with patch("app.adapters.llm.claude_adapter.ClaudeAdapter") as mock_claude:
            mock_instance = MagicMock()
            mock_instance.complete.side_effect = Exception("Unknown error")
            mock_claude.return_value = mock_instance

            result = _test_claude_connection(
                api_key="sk-test-key",
                model="claude-3-sonnet-20240229",
            )

            assert result["success"] is False
            assert "error" in result


class TestTestOllamaConnection:
    """Tests pour _test_ollama_connection()."""

    def test_successful_connection(self):
        """Retourne succes si connexion reussie."""
        with patch("app.adapters.llm.ollama_adapter.OllamaAdapter") as mock_ollama:
            mock_instance = MagicMock()
            mock_instance.is_available.return_value = True
            mock_instance.list_models.return_value = ["llama2", "mistral"]
            mock_instance.complete.return_value = "OK"
            mock_ollama.return_value = mock_instance

            result = _test_ollama_connection(
                base_url="http://localhost:11434",
                model="llama2",
            )

            assert result["success"] is True
            assert result["provider"] == "ollama"
            assert result["model"] == "llama2"
            assert "response_time_ms" in result

    def test_server_not_available(self):
        """Retourne erreur si serveur Ollama non disponible."""
        with patch("app.adapters.llm.ollama_adapter.OllamaAdapter") as mock_ollama:
            mock_instance = MagicMock()
            mock_instance.is_available.return_value = False
            mock_ollama.return_value = mock_instance

            result = _test_ollama_connection(
                base_url="http://localhost:11434",
                model="llama2",
            )

            assert result["success"] is False
            assert "connect" in result["error"].lower()

    def test_model_not_found(self):
        """Retourne erreur si modele non trouve."""
        with patch("app.adapters.llm.ollama_adapter.OllamaAdapter") as mock_ollama:
            mock_instance = MagicMock()
            mock_instance.is_available.return_value = True
            mock_instance.list_models.return_value = ["llama2", "mistral"]
            mock_ollama.return_value = mock_instance

            result = _test_ollama_connection(
                base_url="http://localhost:11434",
                model="nonexistent-model",
            )

            assert result["success"] is False
            assert "non trouv" in result["error"].lower() or "not found" in result["error"].lower()
            # Should suggest available models
            assert "llama2" in result["error"] or "available" in result["error"].lower()

    def test_connection_error_exception(self):
        """Gere LLMConnectionError."""
        with patch("app.adapters.llm.ollama_adapter.OllamaAdapter") as mock_ollama:
            from app.domain.exceptions import LLMConnectionError
            mock_ollama.side_effect = LLMConnectionError("Connection refused")

            result = _test_ollama_connection(
                base_url="http://localhost:11434",
                model="llama2",
            )

            assert result["success"] is False
            assert "connect" in result["error"].lower()

    def test_model_not_found_exception(self):
        """Gere LLMModelNotFoundError."""
        with patch("app.adapters.llm.ollama_adapter.OllamaAdapter") as mock_ollama:
            from app.domain.exceptions import LLMModelNotFoundError
            mock_instance = MagicMock()
            mock_instance.is_available.return_value = True
            mock_instance.list_models.return_value = ["llama2"]
            mock_instance.complete.side_effect = LLMModelNotFoundError(
                provider="ollama", model="llama2", message="Model not found"
            )
            mock_ollama.return_value = mock_instance

            result = _test_ollama_connection(
                base_url="http://localhost:11434",
                model="llama2",
            )

            assert result["success"] is False
            assert "non trouv" in result["error"].lower() or "not found" in result["error"].lower()

    def test_generic_exception(self):
        """Gere les exceptions generiques."""
        with patch("app.adapters.llm.ollama_adapter.OllamaAdapter") as mock_ollama:
            mock_instance = MagicMock()
            mock_instance.is_available.return_value = True
            mock_instance.list_models.return_value = ["llama2"]
            mock_instance.complete.side_effect = Exception("Unknown error")
            mock_ollama.return_value = mock_instance

            result = _test_ollama_connection(
                base_url="http://localhost:11434",
                model="llama2",
            )

            assert result["success"] is False
            assert "Unknown error" in result["error"]


class TestTestLlmEndpoint:
    """Tests pour POST /api/wizard/test-llm."""

    def test_invalid_provider(self, client):
        """Retourne 400 si provider invalide."""
        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "invalid",
                "model": "gpt-4",
            },
        )

        assert response.status_code == 400
        assert "provider" in response.json["error"]

    def test_missing_model(self, client):
        """Retourne 400 si model manquant."""
        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "claude",
                "api_key": "sk-test",
            },
        )

        assert response.status_code == 400
        assert "model" in response.json["error"]

    def test_claude_missing_api_key(self, client):
        """Retourne 400 si api_key manquant pour Claude."""
        response = client.post(
            "/api/wizard/test-llm",
            json={
                "provider": "claude",
                "model": "claude-3-sonnet-20240229",
            },
        )

        assert response.status_code == 400
        assert "api_key" in response.json["error"]

    def test_claude_success(self, client):
        """Retourne succes pour Claude."""
        with patch("app.api.wizard._test_claude_connection") as mock_test:
            mock_test.return_value = {
                "success": True,
                "provider": "claude",
                "model": "claude-3-sonnet-20240229",
                "response_time_ms": 150,
            }

            response = client.post(
                "/api/wizard/test-llm",
                json={
                    "provider": "claude",
                    "model": "claude-3-sonnet-20240229",
                    "api_key": "sk-test-key",
                },
            )

            assert response.status_code == 200
            assert response.json["success"] is True
            assert response.json["provider"] == "claude"

    def test_ollama_success(self, client):
        """Retourne succes pour Ollama."""
        with patch("app.api.wizard._test_ollama_connection") as mock_test:
            mock_test.return_value = {
                "success": True,
                "provider": "ollama",
                "model": "llama2",
                "response_time_ms": 200,
            }

            response = client.post(
                "/api/wizard/test-llm",
                json={
                    "provider": "ollama",
                    "model": "llama2",
                    "ollama_url": "http://localhost:11434",
                },
            )

            assert response.status_code == 200
            assert response.json["success"] is True
            assert response.json["provider"] == "ollama"

    def test_ollama_default_url(self, client):
        """Utilise l'URL par defaut pour Ollama."""
        with patch("app.api.wizard._test_ollama_connection") as mock_test:
            mock_test.return_value = {
                "success": True,
                "provider": "ollama",
                "model": "llama2",
                "response_time_ms": 200,
            }

            client.post(
                "/api/wizard/test-llm",
                json={
                    "provider": "ollama",
                    "model": "llama2",
                },
            )

            mock_test.assert_called_once_with(
                "http://localhost:11434",
                "llama2",
            )
