# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for wizard env-config API endpoint."""

import pytest
from unittest.mock import patch, MagicMock
import tempfile
import os
from pathlib import Path

from flask import Flask
from app.api.wizard import wizard_bp


@pytest.fixture
def app():
    """Create test Flask app."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(wizard_bp, url_prefix="/api/wizard")
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def temp_env_file():
    """Create a temporary .env file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        yield f
    os.unlink(f.name)


@pytest.fixture(autouse=True)
def _empty_db_accounts():
    """Default the env-config DB lookup to "no active account"."""
    session_cm = MagicMock()
    session_cm.__enter__ = MagicMock(return_value=MagicMock())
    session_cm.__exit__ = MagicMock(return_value=False)
    repo = MagicMock()
    repo.get_active_accounts.return_value = []
    repo.get_active_accounts_for_user.return_value = []
    with patch("app.db.database.get_db_session", return_value=session_cm), \
         patch("app.db.repositories.account_repository.AccountRepository", return_value=repo):
        yield


class TestGetEnvConfigEndpoint:
    """Tests for GET /api/wizard/env-config."""

    def test_returns_no_env_when_file_missing(self, client):
        """Test returns has_env=False when no .env file exists."""
        # Create a mock that properly simulates non-existent files
        mock_env = MagicMock()
        mock_env.exists.return_value = False

        mock_config_env = MagicMock()
        mock_config_env.exists.return_value = False

        mock_config_dir = MagicMock()
        mock_config_dir.__truediv__ = MagicMock(return_value=mock_config_env)

        mock_root = MagicMock()

        def truediv_side_effect(name):
            if name == ".env":
                return mock_env
            if name == "config":
                return mock_config_dir
            return MagicMock()

        mock_root.__truediv__ = MagicMock(side_effect=truediv_side_effect)

        with patch("app.config.PROJECT_ROOT", mock_root):
            response = client.get("/api/wizard/env-config")

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is False
            assert data["has_env"] is False

    def test_detects_gmail_provider(self, client, temp_env_file):
        """Test detects Gmail OAuth configuration."""
        temp_env_file.write("""
EMAIL_PROVIDER_TYPE=GMAIL
GOOGLE_CLIENT_ID=test-client-id
GOOGLE_CLIENT_SECRET=test-secret
GOOGLE_REFRESH_TOKEN=test-token
""")
        temp_env_file.close()

        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "GMAIL",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "GOOGLE_CLIENT_SECRET": "test-secret",
                "GOOGLE_REFRESH_TOKEN": "test-token",
            }
            response = client.get("/api/wizard/env-config")

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["email_provider_type"] == "GMAIL"
            assert data["email"]["provider"] == "gmail"
            assert data["email"]["configured"] is True

    def test_detects_gmail_incomplete(self, client):
        """Test detects incomplete Gmail config."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "GMAIL",
                "GOOGLE_CLIENT_ID": "test-id",
                # Missing client_secret and refresh_token
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert data["email"]["configured"] is False
            assert data["email"]["has_client_id"] is True
            assert data["email"]["has_client_secret"] is False

    def test_detects_outlook_provider(self, client):
        """Test detects Outlook OAuth configuration."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "OUTLOOK",
                "AZURE_TENANT_ID": "tenant-123",
                "AZURE_CLIENT_ID": "client-123",
                "AZURE_CLIENT_SECRET": "secret-123",
                "OUTLOOK_USER_ID": "user@example.com",
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert data["email_provider_type"] == "OUTLOOK"
            assert data["email"]["provider"] == "outlook"
            assert data["email"]["configured"] is True
            assert data["email"]["user_id"] == "user@example.com"

    def test_detects_outlook_incomplete(self, client):
        """Test detects incomplete Outlook config."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "OUTLOOK",
                "AZURE_TENANT_ID": "tenant-123",
                # Missing client_id and client_secret
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert data["email"]["configured"] is False
            assert data["email"]["has_tenant_id"] is True

    def test_detects_imap_smtp_provider(self, client):
        """Test detects IMAP/SMTP configuration."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "IMAP",
                "IMAP_HOST": "imap.example.com",
                "IMAP_PORT": "993",
                "IMAP_USER": "user@example.com",
                "IMAP_PASSWORD": "secret",
                "IMAP_USE_SSL": "true",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "587",
                "SMTP_USER": "user@example.com",
                "SMTP_PASSWORD": "secret",
                "SMTP_USE_TLS": "true",
                "SMTP_USE_SSL": "false",
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert data["email"]["provider"] == "imap_smtp"
            assert data["email"]["configured"] is True
            assert data["email"]["imap_host"] == "imap.example.com"
            assert data["email"]["smtp_host"] == "smtp.example.com"
            assert data["email"]["imap_use_ssl"] is True
            assert data["email"]["smtp_use_tls"] is True

    def test_detects_imap_smtp_incomplete(self, client):
        """Test detects incomplete IMAP/SMTP config."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "",
                "IMAP_HOST": "imap.example.com",
                # Missing SMTP_HOST
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert data["email"]["configured"] is False

    def test_detects_llm_config(self, client):
        """Test detects LLM configuration."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "",
                "LLM_PROVIDER": "claude",
                "LLM_MODEL": "claude-3-sonnet",
                "ANTHROPIC_API_KEY": "sk-ant-test",
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert "llm" in data
            assert data["llm"]["provider"] == "claude"
            assert data["llm"]["model"] == "claude-3-sonnet"
            assert data["llm"]["has_api_key"] is True

    def test_detects_ollama_config(self, client):
        """Test detects Ollama LLM configuration."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "",
                "LLM_PROVIDER": "ollama",
                "LLM_MODEL": "llama2",
                "OLLAMA_BASE_URL": "http://localhost:11434",
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert data["llm"]["provider"] == "ollama"
            assert data["llm"]["ollama_url"] == "http://localhost:11434"

    def test_handles_empty_env_file(self, client):
        """Test handles empty .env file."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {}

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert data["success"] is True
            assert data["email"]["provider"] == "imap_smtp"
            assert data["email"]["configured"] is False

    def test_handles_read_error(self, client):
        """Test handles file read errors gracefully."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.side_effect = Exception("Permission denied")

            response = client.get("/api/wizard/env-config")

            assert response.status_code == 500
            data = response.get_json()
            assert data["success"] is False
            assert data["has_env"] is True
            assert "error" in data

    def test_checks_config_directory_fallback(self, client):
        """Test checks config/ directory as fallback."""
        mock_root_path = MagicMock()

        # First check (PROJECT_ROOT / ".env") returns False
        first_env = MagicMock()
        first_env.exists.return_value = False

        # Second check (PROJECT_ROOT / "config" / ".env") returns False
        config_dir = MagicMock()
        second_env = MagicMock()
        second_env.exists.return_value = False
        config_dir.__truediv__ = MagicMock(return_value=second_env)

        def truediv_side_effect(path):
            if path == ".env":
                return first_env
            elif path == "config":
                return config_dir
            return MagicMock()

        mock_root_path.__truediv__ = MagicMock(side_effect=truediv_side_effect)

        with patch("app.config.PROJECT_ROOT", mock_root_path):
            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert data["success"] is False
            assert data["has_env"] is False


class TestEnvParserHelperInEnvConfig:
    """Tests for helper functions used by env-config endpoint."""

    def test_parse_boolean_true_values(self, client):
        """Test parses various true values."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "",
                "IMAP_HOST": "imap.example.com",
                "SMTP_HOST": "smtp.example.com",
                "IMAP_USE_SSL": "TRUE",
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert data["email"]["imap_use_ssl"] is True

    def test_parse_int_safe_with_default(self, client):
        """Test parses integer with default fallback."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "",
                "IMAP_HOST": "imap.example.com",
                "IMAP_PORT": "invalid",
                "SMTP_HOST": "smtp.example.com",
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            # Should use default port when parse fails
            assert data["email"]["imap_port"] == 993


class TestEnvConfigUserScoping:
    """Verify the JWT-scoped DB-account lookup."""

    @staticmethod
    def _patch_db(repo_instance):
        session_cm = MagicMock()
        session_cm.__enter__ = MagicMock(return_value=MagicMock())
        session_cm.__exit__ = MagicMock(return_value=False)
        return [
            patch("app.db.database.get_db_session", return_value=session_cm),
            patch(
                "app.db.repositories.account_repository.AccountRepository",
                return_value=repo_instance,
            ),
        ]

    def test_jwt_user_uses_per_user_lookup(self, app):
        from flask import g
        from app.api.wizard import get_env_config

        fake_account = MagicMock()
        fake_account.provider = "gmail"

        repo_instance = MagicMock()
        repo_instance.get_active_accounts_for_user.return_value = [fake_account]
        repo_instance.get_active_accounts.return_value = []

        patches = self._patch_db(repo_instance)
        for p in patches:
            p.start()
        try:
            with app.test_request_context("/api/wizard/env-config"):
                g.auth_user = {"id": 42, "email": "user@example.com"}
                response = get_env_config()
        finally:
            for p in patches:
                p.stop()

        assert response.status_code == 200
        data = response.get_json()
        assert data["email"]["configured"] is True
        assert data["email"]["provider"] == "gmail"
        repo_instance.get_active_accounts_for_user.assert_called_once_with(42)
        repo_instance.get_active_accounts.assert_not_called()

    def test_no_jwt_falls_back_to_global_lookup(self, client):
        fake_account = MagicMock()
        fake_account.provider = "outlook"

        repo_instance = MagicMock()
        repo_instance.get_active_accounts.return_value = [fake_account]

        patches = self._patch_db(repo_instance)
        for p in patches:
            p.start()
        try:
            response = client.get("/api/wizard/env-config")
        finally:
            for p in patches:
                p.stop()

        assert response.status_code == 200
        data = response.get_json()
        assert data["email"]["configured"] is True
        assert data["email"]["provider"] == "outlook"
        repo_instance.get_active_accounts.assert_called_once_with()
        repo_instance.get_active_accounts_for_user.assert_not_called()

    def test_jwt_user_with_no_account_falls_through_to_env(self, app):
        from flask import g
        from app.api.wizard import get_env_config

        repo_instance = MagicMock()
        repo_instance.get_active_accounts_for_user.return_value = []

        patches = self._patch_db(repo_instance)
        for p in patches:
            p.start()
        try:
            with patch("app.api.wizard._parse_env_file") as mock_parse, \
                 patch.object(Path, 'exists', return_value=True):
                mock_parse.return_value = {
                    "EMAIL_PROVIDER_TYPE": "GMAIL",
                    "GOOGLE_CLIENT_ID": "id",
                    "GOOGLE_CLIENT_SECRET": "secret",
                    "GOOGLE_REFRESH_TOKEN": "refresh",
                }
                with app.test_request_context("/api/wizard/env-config"):
                    g.auth_user = {"id": 99, "email": "fresh@example.com"}
                    response = get_env_config()
        finally:
            for p in patches:
                p.stop()

        data = response.get_json()
        assert data["success"] is True
        assert data["email"]["provider"] == "gmail"
        assert data["email"]["configured"] is True


class TestEnvConfigWithCompleteConfig:
    """Tests for env-config with complete configurations."""

    def test_full_imap_smtp_with_llm(self, client):
        """Test complete IMAP/SMTP + LLM configuration."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "",
                "IMAP_HOST": "imap.example.com",
                "IMAP_PORT": "993",
                "IMAP_USER": "user@example.com",
                "IMAP_PASSWORD": "password",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "587",
                "SMTP_USER": "user@example.com",
                "SMTP_PASSWORD": "password",
                "LLM_PROVIDER": "claude",
                "LLM_MODEL": "claude-3-opus",
                "ANTHROPIC_API_KEY": "sk-ant-xxx",
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert data["success"] is True
            assert data["email"]["configured"] is True
            assert data["llm"]["provider"] == "claude"

    def test_no_llm_config(self, client):
        """Test returns no llm when not configured."""
        with patch("app.api.wizard._parse_env_file") as mock_parse, \
             patch.object(Path, 'exists', return_value=True):
            mock_parse.return_value = {
                "EMAIL_PROVIDER_TYPE": "",
                "IMAP_HOST": "imap.example.com",
                "SMTP_HOST": "smtp.example.com",
            }

            response = client.get("/api/wizard/env-config")

            data = response.get_json()
            assert "llm" not in data or data.get("llm") == {}
