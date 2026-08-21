# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour l'import de fichier .env existant.

POST /api/wizard/import-env
- Parse un fichier .env et extrait la configuration
- Retourne les valeurs detectees pour pre-remplir le wizard
"""

import pytest
import tempfile
import os
from flask import Flask

from app.api.wizard import wizard_bp


@pytest.fixture(autouse=True)
def _bypass_path_safety(monkeypatch):
    """F-03 (audit issue #209): bypass `_is_safe_path` so the existing
    tempfile-based tests (which use absolute paths under TMP) still
    pass through the new path-safety gate."""
    monkeypatch.setattr("app.api.wizard._is_safe_path", lambda p: True)


@pytest.fixture
def app():
    """Cree une application Flask de test.

    F-03 (audit issue #209, 2026-04-29) + F-04 (regression audit,
    2026-04-29): /import-env now under @require_admin. The fixture
    mutates `app.api.admin.ADMIN_EMAILS` and now restores the original
    on teardown (was leaking `admin@test.com` into later tests).
    """
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


def _admin_auth_headers() -> dict:
    """Mint admin JWT for tests hitting @require_admin endpoints."""
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


@pytest.fixture
def client(app):
    """Client de test Flask with admin JWT auto-injected."""
    raw_client = app.test_client()
    _original_open = raw_client.open

    def _open_with_admin(*args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Authorization", _admin_auth_headers()["Authorization"])
        kwargs["headers"] = headers
        return _original_open(*args, **kwargs)

    raw_client.open = _open_with_admin
    return raw_client


@pytest.fixture
def sample_env_file():
    """Cree un fichier .env temporaire pour les tests."""
    content = """# Configuration Agentys
EMAIL_PROVIDER_TYPE=IMAP_SMTP

# IMAP
IMAP_HOST=imap.example.com
IMAP_PORT=993
IMAP_USER=user@example.com
IMAP_PASSWORD=secret123
IMAP_USE_SSL=true

# SMTP
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user@example.com
SMTP_PASSWORD=secret123
SMTP_USE_TLS=true

# LLM
LLM_PROVIDER=claude
LLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-test123

# Daemon
DAEMON_POLL_INTERVAL=60
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write(content)
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def gmail_env_file():
    """Cree un fichier .env avec config Gmail OAuth."""
    content = """EMAIL_PROVIDER_TYPE=GMAIL
GOOGLE_CLIENT_ID=client-id-123
GOOGLE_CLIENT_SECRET=client-secret-456
GOOGLE_REFRESH_TOKEN=refresh-token-789
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write(content)
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def outlook_env_file():
    """Cree un fichier .env avec config Outlook OAuth."""
    content = """EMAIL_PROVIDER_TYPE=OUTLOOK
AZURE_TENANT_ID=tenant-123
AZURE_CLIENT_ID=client-456
AZURE_CLIENT_SECRET=secret-789
OUTLOOK_USER_ID=user@outlook.com
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-prod-key
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write(content)
        f.flush()
        yield f.name
    os.unlink(f.name)


class TestImportEnvEndpoint:
    """Tests pour POST /api/wizard/import-env."""

    def test_missing_json_body(self, client):
        """Retourne 400 si pas de body JSON."""
        response = client.post("/api/wizard/import-env")
        assert response.status_code in (400, 415)

    def test_missing_file_path(self, client):
        """Retourne 400 si file_path manquant."""
        response = client.post(
            "/api/wizard/import-env",
            json={"other_field": "value"},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "file_path" in data["error"].lower()

    def test_file_not_found(self, client):
        """Retourne 404 si fichier n'existe pas."""
        response = client.post(
            "/api/wizard/import-env",
            json={"file_path": "/nonexistent/path/.env"},
        )
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_import_imap_smtp_config(self, client, sample_env_file):
        """Parse correctement une config IMAP/SMTP."""
        response = client.post(
            "/api/wizard/import-env",
            json={"file_path": sample_env_file},
        )
        assert response.status_code == 200
        data = response.get_json()

        assert data["success"] is True
        assert data["provider_type"] == "IMAP_SMTP"

        # IMAP config
        assert data["imap"]["host"] == "imap.example.com"
        assert data["imap"]["port"] == 993
        assert data["imap"]["username"] == "user@example.com"
        assert data["imap"]["use_ssl"] is True
        # Password should be masked
        assert data["imap"]["has_password"] is True
        assert "password" not in data["imap"]

        # SMTP config
        assert data["smtp"]["host"] == "smtp.example.com"
        assert data["smtp"]["port"] == 587
        assert data["smtp"]["username"] == "user@example.com"
        assert data["smtp"]["use_tls"] is True
        assert data["smtp"]["has_password"] is True

        # LLM config
        assert data["llm"]["provider"] == "claude"
        assert data["llm"]["model"] == "claude-sonnet-4-20250514"
        assert data["llm"]["has_api_key"] is True

        # Daemon config
        assert data["daemon"]["poll_interval"] == 60

    def test_import_gmail_config(self, client, gmail_env_file):
        """Parse correctement une config Gmail OAuth."""
        response = client.post(
            "/api/wizard/import-env",
            json={"file_path": gmail_env_file},
        )
        assert response.status_code == 200
        data = response.get_json()

        assert data["success"] is True
        assert data["provider_type"] == "GMAIL"
        assert data["gmail"]["has_client_id"] is True
        assert data["gmail"]["has_client_secret"] is True
        assert data["gmail"]["has_refresh_token"] is True

        # LLM Ollama
        assert data["llm"]["provider"] == "ollama"
        assert data["llm"]["ollama_url"] == "http://localhost:11434"

    def test_import_outlook_config(self, client, outlook_env_file):
        """Parse correctement une config Outlook OAuth."""
        response = client.post(
            "/api/wizard/import-env",
            json={"file_path": outlook_env_file},
        )
        assert response.status_code == 200
        data = response.get_json()

        assert data["success"] is True
        assert data["provider_type"] == "OUTLOOK"
        assert data["outlook"]["has_tenant_id"] is True
        assert data["outlook"]["has_client_id"] is True
        assert data["outlook"]["has_client_secret"] is True
        assert data["outlook"]["user_id"] == "user@outlook.com"

    def test_returns_detected_variables_count(self, client, sample_env_file):
        """Retourne le nombre de variables detectees."""
        response = client.post(
            "/api/wizard/import-env",
            json={"file_path": sample_env_file},
        )
        data = response.get_json()

        assert "variables_count" in data
        assert data["variables_count"] > 0

    def test_handles_empty_file(self, client):
        """Gere correctement un fichier .env vide."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("")
            f.flush()
            env_path = f.name

        try:
            response = client.post(
                "/api/wizard/import-env",
                json={"file_path": env_path},
            )
            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["variables_count"] == 0
        finally:
            os.unlink(env_path)

    def test_handles_comments_only(self, client):
        """Ignore les lignes de commentaires."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("# This is a comment\n")
            f.write("# Another comment\n")
            f.write("\n")
            f.flush()
            env_path = f.name

        try:
            response = client.post(
                "/api/wizard/import-env",
                json={"file_path": env_path},
            )
            data = response.get_json()
            assert data["success"] is True
            assert data["variables_count"] == 0
        finally:
            os.unlink(env_path)

    def test_handles_malformed_lines(self, client):
        """Ignore les lignes malformees sans planter."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("VALID_KEY=valid_value\n")
            f.write("malformed line without equals\n")
            f.write("ANOTHER_KEY=another_value\n")
            f.flush()
            env_path = f.name

        try:
            response = client.post(
                "/api/wizard/import-env",
                json={"file_path": env_path},
            )
            data = response.get_json()
            assert data["success"] is True
            assert data["variables_count"] == 2
        finally:
            os.unlink(env_path)


class TestEnvParserHelpers:
    """Tests pour les fonctions helper de parsing .env."""

    def test_parse_boolean_values(self, client):
        """Parse correctement les valeurs booleennes."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("EMAIL_PROVIDER_TYPE=IMAP_SMTP\n")
            f.write("IMAP_HOST=imap.test.com\n")
            f.write("IMAP_USER=test@test.com\n")
            f.write("SMTP_HOST=smtp.test.com\n")
            f.write("SMTP_USER=test@test.com\n")
            f.write("IMAP_USE_SSL=true\n")
            f.write("SMTP_USE_TLS=True\n")
            f.write("SMTP_USE_SSL=false\n")
            f.flush()
            env_path = f.name

        try:
            response = client.post(
                "/api/wizard/import-env",
                json={"file_path": env_path},
            )
            data = response.get_json()
            assert data["imap"]["use_ssl"] is True
            assert data["smtp"]["use_tls"] is True
            assert data["smtp"]["use_ssl"] is False
        finally:
            os.unlink(env_path)

    def test_parse_integer_values(self, client):
        """Parse correctement les valeurs entieres."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("EMAIL_PROVIDER_TYPE=IMAP_SMTP\n")
            f.write("IMAP_HOST=imap.test.com\n")
            f.write("IMAP_USER=test@test.com\n")
            f.write("SMTP_HOST=smtp.test.com\n")
            f.write("SMTP_USER=test@test.com\n")
            f.write("IMAP_PORT=993\n")
            f.write("SMTP_PORT=465\n")
            f.write("DAEMON_POLL_INTERVAL=120\n")
            f.flush()
            env_path = f.name

        try:
            response = client.post(
                "/api/wizard/import-env",
                json={"file_path": env_path},
            )
            data = response.get_json()
            assert data["imap"]["port"] == 993
            assert data["smtp"]["port"] == 465
            assert data["daemon"]["poll_interval"] == 120
        finally:
            os.unlink(env_path)

    def test_strips_quotes_from_values(self, client):
        """Supprime les guillemets autour des valeurs."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write('EMAIL_PROVIDER_TYPE="IMAP_SMTP"\n')
            f.write("IMAP_HOST='imap.quoted.com'\n")
            f.write('IMAP_USER="user@quoted.com"\n')
            f.write("SMTP_HOST=smtp.quoted.com\n")
            f.write("SMTP_USER=user@quoted.com\n")
            f.flush()
            env_path = f.name

        try:
            response = client.post(
                "/api/wizard/import-env",
                json={"file_path": env_path},
            )
            data = response.get_json()
            assert data["provider_type"] == "IMAP_SMTP"
            assert data["imap"]["host"] == "imap.quoted.com"
            assert data["imap"]["username"] == "user@quoted.com"
        finally:
            os.unlink(env_path)
