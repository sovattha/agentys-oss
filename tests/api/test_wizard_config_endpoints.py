# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for wizard config API endpoints."""

import pytest
from unittest.mock import patch

from flask import Flask
from app.api.wizard import wizard_bp
from app.domain.entities import (
    WizardConfig,
    BusinessSector,
    CompanySize,
    ConfigPack,
    KnowledgeBaseConfig,
)


@pytest.fixture(autouse=True)
def _bypass_path_safety(monkeypatch):
    """Bypass `_is_safe_path` and the production gate for all wizard tests.

    F-03 (audit issue #209, 2026-04-29): wizard import/export/import-env
    now require `_is_safe_path()` AND loopback-or-non-prod. The existing
    tests use synthetic paths like `/path/to/kb.md` that don't resolve
    under ~/ or the project root. Patching the helpers preserves the
    test's original intent (exercising the use-case wiring) while the
    new auth + path checks are validated by dedicated tests added in
    `tests/api/test_wizard_path_safety.py`.
    """
    monkeypatch.setattr("app.api.wizard._is_safe_path", lambda p: True)


@pytest.fixture
def app():
    """Create test Flask app.

    F-03/F-05 (audit issue #209, 2026-04-29) + F-04 (regression audit,
    2026-04-29): wizard config save/delete + import/export/import_env
    are now under @require_admin. The fixture mutates the module-global
    `ADMIN_EMAILS` set, so it MUST restore the original on teardown
    (was previously fire-and-forget, leaking `admin@test.com` into
    every later test in the same pytest session — flaked admin-gate
    assertions in unrelated tests).
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


@pytest.fixture
def client(app):
    """Create test client with admin JWT auto-injected.

    F-03/F-05 (audit issue #209, 2026-04-29): wraps the Flask test client
    so every request carries the admin Authorization header. Lets the
    existing tests hit @require_admin-gated endpoints without rewriting
    every call site.
    """
    raw_client = app.test_client()
    _original_open = raw_client.open

    def _open_with_admin(*args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Authorization", _admin_auth_headers()["Authorization"])
        kwargs["headers"] = headers
        return _original_open(*args, **kwargs)

    raw_client.open = _open_with_admin
    return raw_client


def _admin_auth_headers() -> dict:
    """Mint a JWT for admin@test.com — used by tests hitting endpoints
    now under @require_admin (F-02/F-03/F-04/F-05 audit issue #209).
    """
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
def mock_wizard_config():
    """Create a mock WizardConfig."""
    config = WizardConfig(
        config_id="test-config-123",
        company_name="Test Company",
        sector=BusinessSector.TECH,
        size=CompanySize.SMB,
        primary_language="fr",
        supported_languages=["fr", "en"],
        pack=ConfigPack.STARTUP,
    )
    config.knowledge_base = KnowledgeBaseConfig(
        company_name="Test Company",
        company_description="A test company",
        products_services="Test products",
        tone_guidelines="Professional",
        forbidden_topics=["politics"],
        custom_signatures={"default": "Best regards"},
        faq_entries={"q1": "a1"},
    )
    return config


# =============================================================================
# GET /config Tests
# =============================================================================


class TestGetConfigEndpoint:
    """Tests for GET /api/wizard/config."""

    def test_returns_null_when_no_config(self, client):
        """Test returns exists=False when no config exists."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.load.return_value = None

            response = client.get("/api/wizard/config")

            assert response.status_code == 200
            data = response.get_json()
            assert data["exists"] is False
            assert data["config"] is None

    def test_returns_config_when_exists(self, client, mock_wizard_config):
        """Test returns config when it exists."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.load.return_value = mock_wizard_config

            response = client.get("/api/wizard/config")

            assert response.status_code == 200
            data = response.get_json()
            assert data["exists"] is True
            assert data["config"] is not None
            assert data["config"]["company_name"] == "Test Company"

    def test_includes_active_agents(self, client, mock_wizard_config):
        """Test response includes active agents list."""
        mock_wizard_config.activate_agent("drafter", priority=80)
        mock_wizard_config.activate_agent("critic", priority=60)

        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.load.return_value = mock_wizard_config

            response = client.get("/api/wizard/config")

            data = response.get_json()
            assert "active_agents" in data
            agent_ids = [a["agent_id"] for a in data["active_agents"]]
            assert "drafter" in agent_ids
            assert "critic" in agent_ids


# =============================================================================
# POST /config Tests
# =============================================================================


class TestSaveConfigEndpoint:
    """Tests for POST /api/wizard/config."""

    def test_requires_json_body(self, client):
        """Test returns 415 or 400 when no JSON body provided."""
        response = client.post("/api/wizard/config")

        # Flask returns 415 for missing Content-Type, 400 for missing JSON body
        assert response.status_code in (400, 415)

    def test_requires_company_name(self, client):
        """Test returns 400 when company_name missing."""
        response = client.post(
            "/api/wizard/config",
            json={"sector": "technology"},
        )

        assert response.status_code == 400
        assert "company_name is required" in response.get_json()["error"]

    def test_creates_config_with_minimal_data(self, client):
        """Test creates config with just company_name."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.load.return_value = None

            response = client.post(
                "/api/wizard/config",
                json={"company_name": "New Company"},
            )

            assert response.status_code == 201
            data = response.get_json()
            assert data["success"] is True
            assert data["config"]["company_name"] == "New Company"

    def test_creates_config_with_all_options(self, client):
        """Test creates config with all options."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.load.return_value = None

            response = client.post(
                "/api/wizard/config",
                json={
                    "company_name": "Full Company",
                    "sector": "tech",  # Use valid enum value
                    "size": "enterprise",
                    "primary_language": "en",
                    "supported_languages": ["en", "fr", "de"],
                    "pack": "enterprise",
                    "agents": [
                        {"agent_id": "drafter", "enabled": True, "priority": 90},
                        {"agent_id": "critic", "enabled": True, "priority": 70},
                    ],
                    "knowledge_base": {
                        "company_description": "A full company",
                        "products_services": "Products",
                        "tone_guidelines": "Formal",
                    },
                },
            )

            assert response.status_code == 201
            data = response.get_json()
            assert data["success"] is True
            assert data["config"]["primary_language"] == "en"

    def test_handles_value_error(self, client):
        """Test handles ValueError from invalid enum value."""
        response = client.post(
            "/api/wizard/config",
            json={
                "company_name": "Test",
                "sector": "invalid_sector",
            },
        )

        assert response.status_code == 400

    def test_handles_internal_error(self, client):
        """Test handles internal errors gracefully."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store, \
             patch("app.api.wizard.SaveWizardConfigUseCase") as mock_save:
            mock_store.return_value.load.return_value = None
            mock_save.return_value.execute.side_effect = Exception("DB error")

            response = client.post(
                "/api/wizard/config",
                json={"company_name": "Test"},
            )

            assert response.status_code == 500
            assert "internal error" in response.get_json()["error"]

    def test_applies_agents_with_disabled(self, client):
        """Test applies agent configuration including disabled agents."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.load.return_value = None

            response = client.post(
                "/api/wizard/config",
                json={
                    "company_name": "Test",
                    "agents": [
                        {"agent_id": "drafter", "enabled": True},
                        {"agent_id": "optional_agent", "enabled": False},
                    ],
                },
            )

            assert response.status_code == 201


# =============================================================================
# DELETE /config Tests
# =============================================================================


class TestDeleteConfigEndpoint:
    """Tests for DELETE /api/wizard/config."""

    def test_deletes_existing_config(self, client):
        """Test deletes config when exists."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.delete.return_value = True

            response = client.delete("/api/wizard/config")

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert "deleted" in data["message"].lower()

    def test_handles_no_config(self, client):
        """Test handles case when no config exists -- endpoint always returns success True."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.delete.return_value = False

            response = client.delete("/api/wizard/config")

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True


# =============================================================================
# GET /packs Tests
# =============================================================================


class TestListPacksEndpoint:
    """Tests for GET /api/wizard/packs."""

    def test_returns_all_packs(self, client):
        """Test returns all available packs."""
        with patch("app.api.wizard.get_available_packs") as mock_packs:
            mock_packs.return_value = [
                {"id": "startup", "name": "Startup"},
                {"id": "enterprise", "name": "Enterprise"},
            ]

            response = client.get("/api/wizard/packs")

            assert response.status_code == 200
            data = response.get_json()
            assert data["count"] == 2
            assert len(data["packs"]) == 2


class TestGetPackEndpoint:
    """Tests for GET /api/wizard/packs/<pack_id>."""

    def test_returns_pack_details(self, client):
        """Test returns pack details with agents."""
        with patch("app.api.wizard.get_available_agents") as mock_agents:
            mock_agents.return_value = [
                {"id": "drafter", "name": "Drafter", "category": "core"},
                {"id": "critic", "name": "Critic", "category": "core"},
            ]

            response = client.get("/api/wizard/packs/startup")

            assert response.status_code == 200
            data = response.get_json()
            assert data["id"] == "startup"
            assert "agents" in data

    def test_returns_404_for_invalid_pack(self, client):
        """Test returns 404 for non-existent pack."""
        response = client.get("/api/wizard/packs/invalid_pack")

        assert response.status_code == 404
        assert "not found" in response.get_json()["error"].lower()


# =============================================================================
# GET /agents Tests
# =============================================================================


class TestListAgentsEndpoint:
    """Tests for GET /api/wizard/agents."""

    def test_returns_all_agents(self, client):
        """Test returns all agents with status."""
        with patch("app.api.wizard.get_available_agents") as mock_agents, \
             patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_agents.return_value = [
                {"id": "drafter", "name": "Drafter", "category": "core"},
                {"id": "critic", "name": "Critic", "category": "core"},
                {"id": "support", "name": "Support", "category": "support"},
            ]
            mock_store.return_value.load.return_value = None

            response = client.get("/api/wizard/agents")

            assert response.status_code == 200
            data = response.get_json()
            assert data["count"] == 3
            assert "by_category" in data

    def test_filters_by_category(self, client):
        """Test filters agents by category."""
        with patch("app.api.wizard.get_available_agents") as mock_agents, \
             patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_agents.return_value = [
                {"id": "drafter", "name": "Drafter", "category": "core"},
                {"id": "critic", "name": "Critic", "category": "core"},
                {"id": "support", "name": "Support", "category": "support"},
            ]
            mock_store.return_value.load.return_value = None

            response = client.get("/api/wizard/agents?category=core")

            data = response.get_json()
            assert data["count"] == 2
            assert all(a["category"] == "core" for a in data["agents"])

    def test_includes_activation_status(self, client, mock_wizard_config):
        """Test includes activation status from config."""
        mock_wizard_config.activate_agent("drafter", priority=80)

        with patch("app.api.wizard.get_available_agents") as mock_agents, \
             patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_agents.return_value = [
                {"id": "drafter", "name": "Drafter", "category": "core"},
                {"id": "critic", "name": "Critic", "category": "core"},
            ]
            mock_store.return_value.load.return_value = mock_wizard_config

            response = client.get("/api/wizard/agents")

            data = response.get_json()
            drafter = next(a for a in data["agents"] if a["id"] == "drafter")
            assert drafter["enabled"] is True


# =============================================================================
# PATCH /agents/<agent_id> Tests
# =============================================================================


class TestToggleAgentEndpoint:
    """Tests for PATCH /api/wizard/agents/<agent_id>."""

    def test_requires_json_body(self, client):
        """Test returns 415 or 400 when no JSON body."""
        response = client.patch("/api/wizard/agents/drafter")

        # Flask returns 415 for missing Content-Type
        assert response.status_code in (400, 415)

    def test_requires_enabled_field(self, client):
        """Test returns 400 when enabled missing."""
        response = client.patch(
            "/api/wizard/agents/drafter",
            json={"priority": 80},
        )

        assert response.status_code == 400
        assert "enabled is required" in response.get_json()["error"]

    def test_validates_priority_range(self, client):
        """Test validates priority is 0-100."""
        response = client.patch(
            "/api/wizard/agents/drafter",
            json={"enabled": True, "priority": 150},
        )

        assert response.status_code == 400
        assert "priority must be between" in response.get_json()["error"]

    def test_returns_404_for_unknown_agent(self, client):
        """Test returns 404 for non-existent agent."""
        with patch("app.api.wizard.get_available_agents") as mock_agents:
            mock_agents.return_value = [
                {"id": "drafter", "name": "Drafter", "category": "core"},
            ]

            response = client.patch(
                "/api/wizard/agents/unknown_agent",
                json={"enabled": True},
            )

            assert response.status_code == 404

    def test_prevents_disabling_core_agents(self, client):
        """Test prevents disabling core agents."""
        with patch("app.api.wizard.get_available_agents") as mock_agents:
            mock_agents.return_value = [
                {"id": "drafter", "name": "Drafter", "category": "core"},
            ]

            response = client.patch(
                "/api/wizard/agents/drafter",
                json={"enabled": False},
            )

            assert response.status_code == 400
            assert "core agents" in response.get_json()["error"].lower()

    def test_enables_agent(self, client, mock_wizard_config):
        """Test enables an agent."""
        with patch("app.api.wizard.get_available_agents") as mock_agents, \
             patch("app.api.wizard.get_wizard_config_store"), \
             patch("app.api.wizard.ToggleAgentUseCase") as mock_use_case:
            mock_agents.return_value = [
                {"id": "support", "name": "Support", "category": "support"},
            ]
            mock_wizard_config.activate_agent("support", priority=70)
            mock_use_case.return_value.execute.return_value = mock_wizard_config

            response = client.patch(
                "/api/wizard/agents/support",
                json={"enabled": True, "priority": 70},
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["agent_id"] == "support"
            assert data["enabled"] is True

    def test_returns_404_when_no_config(self, client):
        """Test returns 404 when no config exists."""
        with patch("app.api.wizard.get_available_agents") as mock_agents, \
             patch("app.api.wizard.get_wizard_config_store"), \
             patch("app.api.wizard.ToggleAgentUseCase") as mock_use_case:
            mock_agents.return_value = [
                {"id": "support", "name": "Support", "category": "support"},
            ]
            mock_use_case.return_value.execute.return_value = None

            response = client.patch(
                "/api/wizard/agents/support",
                json={"enabled": True},
            )

            assert response.status_code == 404


# =============================================================================
# GET /knowledge-base Tests
# =============================================================================


class TestGetKnowledgeBaseEndpoint:
    """Tests for GET /api/wizard/knowledge-base."""

    def test_returns_404_when_no_config(self, client):
        """Test returns 404 when no config exists."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.load.return_value = None

            response = client.get("/api/wizard/knowledge-base")

            assert response.status_code == 404

    def test_returns_knowledge_base(self, client, mock_wizard_config):
        """Test returns knowledge base from config."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.load.return_value = mock_wizard_config

            response = client.get("/api/wizard/knowledge-base")

            assert response.status_code == 200
            data = response.get_json()
            assert data["company_name"] == "Test Company"
            assert data["company_description"] == "A test company"
            assert data["forbidden_topics"] == ["politics"]


# =============================================================================
# PATCH /knowledge-base Tests
# =============================================================================


class TestUpdateKnowledgeBaseEndpoint:
    """Tests for PATCH /api/wizard/knowledge-base."""

    def test_requires_json_body(self, client):
        """Test returns 415 or 400 when no JSON body."""
        response = client.patch("/api/wizard/knowledge-base")

        # Flask returns 415 for missing Content-Type
        assert response.status_code in (400, 415)

    def test_returns_404_when_no_config(self, client):
        """Test returns 404 when no config exists."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store:
            mock_store.return_value.load.return_value = None

            response = client.patch(
                "/api/wizard/knowledge-base",
                json={"company_description": "Updated"},
            )

            assert response.status_code == 404

    def test_updates_single_field(self, client, mock_wizard_config):
        """Test updates a single field."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store, \
             patch("app.api.wizard.SaveWizardConfigUseCase"):
            mock_store.return_value.load.return_value = mock_wizard_config

            response = client.patch(
                "/api/wizard/knowledge-base",
                json={"company_description": "Updated description"},
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True

    def test_updates_multiple_fields(self, client, mock_wizard_config):
        """Test updates multiple fields."""
        with patch("app.api.wizard.get_wizard_config_store") as mock_store, \
             patch("app.api.wizard.SaveWizardConfigUseCase"):
            mock_store.return_value.load.return_value = mock_wizard_config

            response = client.patch(
                "/api/wizard/knowledge-base",
                json={
                    "company_name": "New Name",
                    "products_services": "New products",
                    "tone_guidelines": "Casual",
                    "forbidden_topics": ["sensitive"],
                    "custom_signatures": {"new": "sig"},
                    "faq_entries": {"new_q": "new_a"},
                },
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True


# =============================================================================
# POST /import Tests
# =============================================================================


class TestImportKnowledgeBaseEndpoint:
    """Tests for POST /api/wizard/import."""

    def test_requires_json_body(self, client):
        """Test returns 415 or 400 when no JSON body."""
        response = client.post("/api/wizard/import")

        # Flask returns 415 for missing Content-Type
        assert response.status_code in (400, 415)

    def test_requires_file_path(self, client):
        """Test returns 400 when file_path missing."""
        response = client.post(
            "/api/wizard/import",
            json={"merge": True},
        )

        assert response.status_code == 400
        assert "file_path is required" in response.get_json()["error"]

    def test_imports_successfully(self, client, mock_wizard_config):
        """Test imports knowledge base successfully."""
        with patch("app.api.wizard.get_wizard_config_store"), \
             patch("app.api.wizard.ImportKnowledgeBaseUseCase") as mock_use_case:
            mock_use_case.return_value.execute.return_value = mock_wizard_config

            response = client.post(
                "/api/wizard/import",
                json={"file_path": "/path/to/kb.md"},
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True

    def test_returns_404_when_no_config(self, client):
        """Test returns 404 when no config exists."""
        with patch("app.api.wizard.get_wizard_config_store"), \
             patch("app.api.wizard.ImportKnowledgeBaseUseCase") as mock_use_case:
            mock_use_case.return_value.execute.return_value = None

            response = client.post(
                "/api/wizard/import",
                json={"file_path": "/path/to/kb.md"},
            )

            assert response.status_code == 404

    def test_returns_404_for_missing_file(self, client):
        """Test returns 404 when file not found."""
        with patch("app.api.wizard.get_wizard_config_store"), \
             patch("app.api.wizard.ImportKnowledgeBaseUseCase") as mock_use_case:
            mock_use_case.return_value.execute.side_effect = FileNotFoundError()

            response = client.post(
                "/api/wizard/import",
                json={"file_path": "/nonexistent.md"},
            )

            assert response.status_code == 404

    def test_handles_internal_error(self, client):
        """Test handles internal errors gracefully."""
        with patch("app.api.wizard.get_wizard_config_store"), \
             patch("app.api.wizard.ImportKnowledgeBaseUseCase") as mock_use_case:
            mock_use_case.return_value.execute.side_effect = Exception("DB error")

            response = client.post(
                "/api/wizard/import",
                json={"file_path": "/path/to/kb.md"},
            )

            assert response.status_code == 500

    def test_supports_merge_option(self, client, mock_wizard_config):
        """Test supports merge option."""
        with patch("app.api.wizard.get_wizard_config_store"), \
             patch("app.api.wizard.ImportKnowledgeBaseUseCase") as mock_use_case:
            mock_use_case.return_value.execute.return_value = mock_wizard_config

            response = client.post(
                "/api/wizard/import",
                json={"file_path": "/path/to/kb.md", "merge": True},
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["merged"] is True


# =============================================================================
# POST /export Tests
# =============================================================================


class TestExportConfigEndpoint:
    """Tests for POST /api/wizard/export."""

    def test_requires_json_body(self, client):
        """Test returns 415 or 400 when no JSON body."""
        response = client.post("/api/wizard/export")

        # Flask returns 415 for missing Content-Type
        assert response.status_code in (400, 415)

    def test_requires_file_path(self, client):
        """Test returns 400 when file_path missing."""
        response = client.post(
            "/api/wizard/export",
            json={"some_other_field": "value"},  # Empty dict triggers JSON body required
        )

        assert response.status_code == 400
        assert "file_path is required" in response.get_json()["error"]

    def test_exports_successfully(self, client):
        """Test exports config successfully."""
        with patch("app.api.wizard.get_wizard_config_store"), \
             patch("app.api.wizard.ExportConfigUseCase") as mock_use_case:
            mock_use_case.return_value.execute.return_value = None

            response = client.post(
                "/api/wizard/export",
                json={"file_path": "/path/to/export.json"},
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["file_path"] == "/path/to/export.json"

    def test_handles_value_error(self, client):
        """Test handles ValueError."""
        with patch("app.api.wizard.get_wizard_config_store"), \
             patch("app.api.wizard.ExportConfigUseCase") as mock_use_case:
            mock_use_case.return_value.execute.side_effect = ValueError("No config")

            response = client.post(
                "/api/wizard/export",
                json={"file_path": "/path/to/export.json"},
            )

            assert response.status_code == 400

    def test_handles_internal_error(self, client):
        """Test handles internal errors."""
        with patch("app.api.wizard.get_wizard_config_store"), \
             patch("app.api.wizard.ExportConfigUseCase") as mock_use_case:
            mock_use_case.return_value.execute.side_effect = Exception("IO error")

            response = client.post(
                "/api/wizard/export",
                json={"file_path": "/path/to/export.json"},
            )

            assert response.status_code == 500
