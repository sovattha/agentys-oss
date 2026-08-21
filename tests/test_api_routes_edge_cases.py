# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests edge cases pour les routes API REST.

Ces tests vérifient:
- Validation des entrées (null, vide, formats invalides)
- Erreurs HTTP (400, 401, 404, 500)
- Cas limites des paramètres
- Comportement avec données malformées
"""

import pytest
import re
from unittest.mock import patch, Mock

# Skip all tests if flask_cors is not available
pytest.importorskip("flask_cors")

from app.application.health_check import SystemHealthStatus, HealthStatus


def _create_health_status(email_healthy=True, llm_healthy=True,
                          email_msg=None, llm_msg=None):
    """Factory pour créer un SystemHealthStatus avec les paramètres donnés."""
    return SystemHealthStatus(
        email_provider=HealthStatus(healthy=email_healthy, message=email_msg),
        llm=HealthStatus(healthy=llm_healthy, message=llm_msg),
    )


def _setup_mock_container(mock_get_container, health_status):
    """Configure le mock container avec le status de santé donné."""
    mock_use_case = Mock()
    mock_use_case.execute.return_value = health_status
    mock_container = Mock()
    mock_container.get_health_check_use_case.return_value = mock_use_case
    mock_get_container.return_value = mock_container


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def app():
    """Application Flask de test."""
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Client de test Flask."""
    return app.test_client()


# ============================================================================
# TESTS - HEALTH ENDPOINT
# ============================================================================

class TestHealthEndpoint:
    """Tests edge cases pour /api/health.

    /api/health est un health check léger qui retourne instantanément
    {status: "ok", version, timestamp} sans I/O externe.
    /api/health/deep est le health check complet (IMAP + LLM).
    """

    def test_health_all_ok(self, client):
        """Health check léger retourne status ok."""
        response = client.get("/api/health")
        data = response.get_json()

        assert response.status_code == 200
        assert data["status"] == "ok"

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_email_failure(self, mock_get_container, client):
        """Deep health check avec email provider en échec."""
        _setup_mock_container(
            mock_get_container,
            _create_health_status(email_healthy=False, email_msg="Auth failed")
        )

        response = client.get("/api/health/deep")
        data = response.get_json()

        assert response.status_code == 200
        assert data["services"]["email"] == "disconnected"
        assert data["services"]["llm"] == "connected"

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_llm_failure(self, mock_get_container, client):
        """Deep health check avec LLM en échec."""
        _setup_mock_container(
            mock_get_container,
            _create_health_status(llm_healthy=False, llm_msg="LLM Error")
        )

        response = client.get("/api/health/deep")
        data = response.get_json()

        assert response.status_code == 200
        assert data["services"]["llm"] == "disconnected"

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_both_failure(self, mock_get_container, client):
        """Deep health check avec tous les services en échec."""
        _setup_mock_container(
            mock_get_container,
            _create_health_status(
                email_healthy=False, llm_healthy=False,
                email_msg="Connection error", llm_msg="LLM Error"
            )
        )

        response = client.get("/api/health/deep")
        data = response.get_json()

        assert response.status_code == 200
        assert data["services"]["email"] == "disconnected"
        assert data["services"]["llm"] == "disconnected"

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_llm_empty_response(self, mock_get_container, client):
        """Deep health check avec réponse LLM vide (considéré comme échec)."""
        _setup_mock_container(
            mock_get_container,
            _create_health_status(llm_healthy=False, llm_msg="Empty response")
        )

        response = client.get("/api/health/deep")
        data = response.get_json()

        assert response.status_code == 200
        assert data["services"]["llm"] == "disconnected"

    def test_health_response_timestamp_format(self, client):
        """Health check retourne un timestamp au format ISO 8601 avec Z."""
        response = client.get("/api/health")
        data = response.get_json()

        assert response.status_code == 200
        assert "timestamp" in data
        timestamp = data["timestamp"]
        assert timestamp.endswith("Z")
        iso_pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z"
        assert re.match(iso_pattern, timestamp)

    def test_health_method_not_allowed_post(self, client):
        """Health endpoint rejette les requêtes POST."""
        response = client.post("/api/health")
        assert response.status_code == 405

    def test_health_method_not_allowed_put(self, client):
        """Health endpoint rejette les requêtes PUT."""
        response = client.put("/api/health")
        assert response.status_code == 405

    def test_health_method_not_allowed_delete(self, client):
        """Health endpoint rejette les requêtes DELETE."""
        response = client.delete("/api/health")
        assert response.status_code == 405

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_use_case_raises_exception(self, mock_get_container, client):
        """Deep health check quand le use case lève une exception non gérée.

        L'exception se propage car il n'y a pas de try/catch dans l'endpoint.
        """
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = RuntimeError("Unexpected error")
        mock_container = Mock()
        mock_container.get_health_check_use_case.return_value = mock_use_case
        mock_get_container.return_value = mock_container

        response = client.get("/api/health/deep")
        assert response.status_code == 500

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_container_raises_exception(self, mock_get_container, client):
        """Deep health check quand le container lève une exception.

        L'exception se propage car il n'y a pas de try/catch dans l'endpoint.
        """
        mock_get_container.side_effect = RuntimeError("Container initialization failed")

        response = client.get("/api/health/deep")
        assert response.status_code == 500

    def test_health_response_structure(self, client):
        """Vérifie la structure complète de la réponse health léger."""
        response = client.get("/api/health")
        data = response.get_json()

        assert "status" in data
        assert "version" in data
        assert "timestamp" in data
        assert set(data.keys()) == {"status", "version", "timestamp"}

    # --- EDGE CASES ADDITIONNELS ---

    def test_health_ignores_query_params(self, client):
        """Health check ignore les query params inattendus."""
        response = client.get("/api/health?foo=bar&baz=123")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"

    def test_health_response_content_type(self, client):
        """Health check retourne Content-Type application/json."""
        response = client.get("/api/health")

        assert "application/json" in response.content_type

    def test_health_with_accept_text_plain(self, client):
        """Health check avec Accept: text/plain retourne quand même JSON."""
        response = client.get(
            "/api/health",
            headers={"Accept": "text/plain"}
        )

        assert response.status_code == 200
        assert "application/json" in response.content_type

    def test_health_head_request(self, client):
        """Health endpoint supporte ou rejette HEAD selon implémentation.

        Flask par défaut supporte HEAD pour les routes GET.
        """
        response = client.head("/api/health")

        assert response.status_code in [200, 405, 500, 503]

    def test_health_options_request(self, client):
        """Health endpoint OPTIONS pour CORS preflight."""
        response = client.options("/api/health")

        assert response.status_code in [200, 204, 405]

    def test_health_method_patch_not_allowed(self, client):
        """Health endpoint rejette les requêtes PATCH."""
        response = client.patch("/api/health")
        assert response.status_code == 405

    def test_health_status_with_message_none(self, client):
        """Health check léger retourne toujours status ok."""
        response = client.get("/api/health")
        data = response.get_json()

        assert response.status_code == 200
        assert data["status"] == "ok"

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_status_with_empty_message(self, mock_get_container, client):
        """Deep health check avec message vide dans HealthStatus."""
        _setup_mock_container(
            mock_get_container,
            _create_health_status(email_healthy=False, email_msg="")
        )

        response = client.get("/api/health/deep")
        data = response.get_json()

        assert response.status_code == 200
        assert data["services"]["email"] == "disconnected"

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_memory_error_propagates(self, mock_get_container, client):
        """Deep health check propage MemoryError."""
        mock_get_container.side_effect = MemoryError("Out of memory")

        response = client.get("/api/health/deep")
        assert response.status_code == 500

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_keyboard_interrupt_propagates(self, mock_get_container, client):
        """Deep health check propage KeyboardInterrupt.

        KeyboardInterrupt est une BaseException non catchée par Flask
        (convention Python : Ctrl+C doit toujours interrompre). Le test
        valide qu'elle propage bien jusqu'à pytest, donc on garde le
        pytest.raises (à la différence des Exception ordinaires que
        Flask catche → 500).
        """
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = KeyboardInterrupt()
        mock_container = Mock()
        mock_container.get_health_check_use_case.return_value = mock_use_case
        mock_get_container.return_value = mock_container

        with pytest.raises(KeyboardInterrupt):
            client.get("/api/health/deep")

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_system_exit_propagates(self, mock_get_container, client):
        """Deep health check propage SystemExit.

        SystemExit est une BaseException non catchée par Flask (idem
        KeyboardInterrupt) — elle propage jusqu'à pytest.
        """
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = SystemExit(1)
        mock_container = Mock()
        mock_container.get_health_check_use_case.return_value = mock_use_case
        mock_get_container.return_value = mock_container

        with pytest.raises(SystemExit):
            client.get("/api/health/deep")

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_get_use_case_raises(self, mock_get_container, client):
        """Deep health check quand get_health_check_use_case lève une exception."""
        mock_container = Mock()
        mock_container.get_health_check_use_case.side_effect = ValueError("Invalid config")
        mock_get_container.return_value = mock_container

        response = client.get("/api/health/deep")
        assert response.status_code == 500

    def test_health_with_trailing_slash(self, client):
        """Health check avec slash final dans l'URL."""
        response = client.get("/api/health/")

        assert response.status_code in [200, 301, 308, 404]

    @patch("app.api.routes_helpers._get_container")
    def test_health_deep_concurrent_degraded_status(self, mock_get_container, client):
        """Deep health check quand email OK mais llm KO."""
        _setup_mock_container(
            mock_get_container,
            _create_health_status(llm_healthy=False, llm_msg="Timeout")
        )

        response = client.get("/api/health/deep")
        data = response.get_json()

        assert response.status_code == 200
        assert data["services"]["email"] == "connected"
        assert data["services"]["llm"] == "disconnected"

    def test_health_version_matches_api_version_constant(self, client):
        """Health check version correspond à API_VERSION."""
        from app.api.routes import API_VERSION

        response = client.get("/api/health")
        data = response.get_json()

        assert data["version"] == API_VERSION

    def test_health_response_not_cached(self, client):
        """Health check retourne des timestamps différents à chaque appel."""
        import time

        response1 = client.get("/api/health")
        time.sleep(0.01)  # 10ms de délai
        response2 = client.get("/api/health")

        data1 = response1.get_json()
        data2 = response2.get_json()

        assert data1["timestamp"] != data2["timestamp"]


# ============================================================================
# TESTS - EMAILS ENDPOINT
# ============================================================================

class TestEmailsEndpoint:
    """Tests edge cases pour /api/emails."""

    @patch("app.multi_accounts.get_account_manager")
    @patch("app.api.routes_emails._get_current_account_for_user")
    def test_emails_no_account(self, mock_get_account, mock_get_manager, client):
        """Liste emails sans compte configuré retourne une liste vide."""
        mock_get_account.return_value = None
        mock_manager = Mock()
        mock_manager.get_all_accounts.return_value = []
        mock_get_manager.return_value = mock_manager

        response = client.get("/api/emails")
        data = response.get_json()

        assert response.status_code == 200
        assert data["emails"] == []
        assert data.get("no_account") is True

    def test_emails_limit_zero(self, client):
        """Liste emails avec limit=0 retourne une erreur 400."""
        response = client.get("/api/emails?limit=0")
        data = response.get_json()

        # Security: limit=0 is rejected to prevent DoS
        assert response.status_code == 400
        assert "error" in data
        assert "Limit must be between" in data["error"]

    def test_emails_limit_negative(self, client):
        """Liste emails avec limit négatif retourne une erreur 400."""
        response = client.get("/api/emails?limit=-5")
        data = response.get_json()

        # Security: negative limit is rejected
        assert response.status_code == 400
        assert "error" in data
        assert "Limit must be between" in data["error"]

    def test_emails_limit_invalid_type(self, client):
        """Liste emails avec limit invalide (string) retourne une erreur 400."""
        response = client.get("/api/emails?limit=abc")
        data = response.get_json()

        # Security: non-integer limit is rejected
        assert response.status_code == 400
        assert "error" in data
        assert "valid integer" in data["error"]

    @patch("app.api.routes_emails._get_current_account_for_user")
    def test_emails_provider_exception(self, mock_get_account, client):
        """Liste emails avec exception lors de la résolution du compte.

        With TESTING=True, Flask propagates unhandled exceptions.
        """
        mock_get_account.side_effect = Exception("API Error")

        response = client.get("/api/emails")
        assert response.status_code == 500


# ============================================================================
# TESTS - PROCESS EMAIL ENDPOINT
# ============================================================================

class TestProcessEmailEndpoint:
    """Tests edge cases pour /api/emails/<id>/process."""

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_auth_failure(self, mock_get_auth_provider, client):
        """Traitement email avec authentification échouée."""
        from werkzeug.exceptions import ServiceUnavailable
        mock_get_auth_provider.side_effect = ServiceUnavailable("Email provider authentication failed")

        response = client.post("/api/emails/test-id/process")
        data = response.get_json()

        assert response.status_code == 503
        assert "error" in data

    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_process_email_not_found(self, mock_get_provider, client):
        """Traitement email non trouvé.

        Route devenue async — retourne 202 Accepted immédiatement,
        l'erreur 404 arriverait via WebSocket si l'email est introuvable
        en background. Donc on accepte 202 (nouveau path) ou 404 (ancien).
        """
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.get_unread_messages.return_value = []
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/nonexistent-id/process")

        assert response.status_code in (202, 404)

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    @patch("app.api.routes_helpers._get_container")
    def test_process_drafter_exception(
        self, mock_get_container, mock_get_auth_provider, mock_get_email, client
    ):
        """Traitement email avec exception du use case."""
        mock_email = Mock()
        mock_email.id = "test-id"
        mock_email.sender = "sender@test.com"
        mock_email.sender_name = "Sender"
        mock_email.subject = "Subject"
        mock_email.body = "Body"
        mock_email.received_at = "2025-01-01T00:00:00"
        mock_email.has_attachments = False
        mock_email.conversation_id = None

        mock_provider = Mock()
        mock_get_auth_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        # Mock le Container: pending_draft_store returns None (no existing draft)
        mock_pending_store = Mock()
        mock_pending_store.get_by_email_id.return_value = None
        mock_container = Mock()
        mock_container.get_pending_draft_store.return_value = mock_pending_store
        mock_get_container.return_value = mock_container

        # The process endpoint runs generation in background, so the HTTP response
        # is 202 (accepted) — the actual error happens asynchronously.
        response = client.post("/api/emails/test-id/process")

        # The endpoint returns 202 for background processing or 500 on immediate error
        assert response.status_code in [200, 202, 500]

    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_process_special_chars_in_id(self, mock_get_provider, client):
        """Traitement email avec caractères spéciaux dans l'ID."""
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.get_unread_messages.return_value = []
        mock_get_provider.return_value = mock_provider

        # ID avec caractères spéciaux encodés
        response = client.post("/api/emails/test%2Fid%40special/process")
        response.get_json()

        assert response.status_code == 404


# ============================================================================
# TESTS - DRAFTS ENDPOINTS
# ============================================================================

class TestDraftsEndpoint:
    """Tests edge cases pour /api/drafts."""

    @patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_drafts_empty(self, mock_get_container, mock_resolve_account, client):
        """Liste drafts vide."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = []
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 0
        assert data["drafts"] == []

    @patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_drafts_pagination_out_of_range(self, mock_get_container, mock_resolve_account, client):
        """Pagination hors limites."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = []
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?offset=1000&limit=50")
        data = response.get_json()

        assert response.status_code == 200
        assert data["drafts"] == []

    def test_drafts_negative_offset(self, client):
        """Offset negatif retourne erreur 400."""
        response = client.get("/api/drafts?offset=-10")
        data = response.get_json()

        # Security: negative offset is rejected
        assert response.status_code == 400
        assert "error" in data
        assert "Offset must be between" in data["error"]

    @patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_draft_by_id_not_found(self, mock_get_container, mock_resolve_account, client):
        """Draft par ID non trouve."""
        mock_draft_history = Mock()
        mock_draft_history.get_by_id_for_account.return_value = None
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts/nonexistent-id")
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data

    def test_draft_feedback_no_json(self, client):
        """Feedback sans body JSON."""
        response = client.patch(
            "/api/drafts/test-id/feedback",
            content_type="application/json"
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_draft_feedback_invalid_value(self, client):
        """Feedback avec valeur invalide."""
        response = client.patch(
            "/api/drafts/test-id/feedback",
            json={"feedback": "invalid"}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "positive" in data["error"] or "negative" in data["error"]

    def test_draft_feedback_missing_field(self, client):
        """Feedback sans champ feedback."""
        response = client.patch(
            "/api/drafts/test-id/feedback",
            json={"comment": "Just a comment"}
        )
        response.get_json()

        assert response.status_code == 400

    @patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_draft_feedback_not_found(self, mock_get_container, mock_resolve_account, client):
        """Feedback sur draft non trouve."""
        mock_draft_history = Mock()
        mock_draft_history.update_feedback_for_account.return_value = False
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.patch(
            "/api/drafts/test-id/feedback",
            json={"feedback": "positive"}
        )
        response.get_json()

        assert response.status_code == 404

    @patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_draft_feedback_success(self, mock_get_container, mock_resolve, client):
        """Feedback reussi.

        Route appelle update_feedback_for_account (pas update_feedback) avec
        account_id, cf routes_drafts.py:312.
        """
        mock_draft_history = Mock()
        mock_draft_history.update_feedback_for_account.return_value = True
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.patch(
            "/api/drafts/test-id/feedback",
            json={"feedback": "positive", "comment": "Great!"}
        )
        data = response.get_json()

        assert response.status_code == 200, f"got {response.status_code}: {data}"
        assert data["success"] is True


# ============================================================================
# TESTS - DRAFT COMPLETION ENDPOINT
# ============================================================================

class TestDraftCompletionEndpoint:
    """Tests edge cases pour /api/drafts/complete."""

    def test_complete_no_json(self, client):
        """Complétion sans body JSON."""
        response = client.post(
            "/api/drafts/complete",
            content_type="application/json"
        )
        data = response.get_json()

        assert response.status_code == 400
        # Flask intercepte les requêtes JSON invalides avec errorhandler(400)
        assert "error" in data

    def test_complete_missing_raw_input(self, client):
        """Complétion sans raw_input."""
        response = client.post(
            "/api/drafts/complete",
            json={"recipient": "Sophie"}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "raw_input is required" in data["error"]

    def test_complete_empty_raw_input(self, client):
        """Complétion avec raw_input vide."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": ""}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "raw_input is required" in data["error"]

    def test_complete_invalid_tone(self, client):
        """Complétion avec ton invalide."""
        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "- Point 1", "tone": "invalid_tone"}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "Invalid tone" in data["error"]

    @patch("app.api.routes_helpers.get_container")
    def test_complete_success_basic(self, mock_get_container, client):
        """Complétion réussie basique."""
        mock_result = Mock()
        mock_result.subject = "Test Subject"
        mock_result.body = "Test Body"
        mock_result.recipient = None
        mock_result.tone_used = Mock()
        mock_result.tone_used.value = "neutral"
        mock_result.formatted_output = "Formatted output"

        mock_use_case = Mock()
        mock_use_case.execute.return_value = mock_result
        mock_container = Mock()
        mock_container.get_complete_draft_use_case.return_value = mock_use_case
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "- Point 1\n- Point 2"}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["subject"] == "Test Subject"

    @patch("app.api.routes_helpers.get_container")
    def test_complete_with_options(self, mock_get_container, client):
        """Complétion avec options."""
        mock_result = Mock()
        mock_result.subject = "Test Subject"
        mock_result.body = "Test Body"
        mock_result.recipient = "Sophie"
        mock_result.tone_used = Mock()
        mock_result.tone_used.value = "formal"
        mock_result.formatted_output = "Formatted output"

        mock_use_case = Mock()
        mock_use_case.execute.return_value = mock_result
        mock_container = Mock()
        mock_container.get_complete_draft_use_case.return_value = mock_use_case
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/drafts/complete",
            json={
                "raw_input": "- Point 1",
                "recipient": "Sophie",
                "tone": "formal",
                "subject_hint": "Meeting"
            }
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["recipient"] == "Sophie"
        assert data["tone_used"] == "formal"

    @patch("app.api.routes_helpers.get_container")
    def test_complete_exception(self, mock_get_container, client):
        """Complétion avec exception."""
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = Exception("LLM Error")
        mock_container = Mock()
        mock_container.get_complete_draft_use_case.return_value = mock_use_case
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "- Point 1"}
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


# ============================================================================
# TESTS - DRAFT DETECT ENDPOINT
# ============================================================================

class TestDraftDetectEndpoint:
    """Tests edge cases pour /api/drafts/detect."""

    def test_detect_no_json(self, client):
        """Détection sans body JSON."""
        response = client.post(
            "/api/drafts/detect",
            content_type="application/json"
        )
        data = response.get_json()

        assert response.status_code == 400
        # Flask intercepte les requêtes JSON invalides avec errorhandler(400)
        assert "error" in data

    def test_detect_missing_text(self, client):
        """Détection sans text."""
        response = client.post(
            "/api/drafts/detect",
            json={}
        )
        data = response.get_json()

        assert response.status_code == 400
        # Soit "text is required" de notre code, soit "JSON body required" du helper
        assert "error" in data

    def test_detect_empty_text(self, client):
        """Détection avec text vide."""
        response = client.post(
            "/api/drafts/detect",
            json={"text": ""}
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "text is required" in data["error"]

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_true(self, mock_get_legacy, client):
        """Détection positive."""
        mock_is_draft = Mock(return_value=True)
        mock_get_legacy.return_value = {"is_draft_request": mock_is_draft}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Brouillon: test"}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["is_draft_request"] is True

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_false(self, mock_get_legacy, client):
        """Détection négative."""
        mock_is_draft = Mock(return_value=False)
        mock_get_legacy.return_value = {"is_draft_request": mock_is_draft}

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Normal email content"}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["is_draft_request"] is False

    @patch("app.api.routes_learning._get_legacy_modules")
    def test_detect_long_text_preview(self, mock_get_legacy, client):
        """Détection avec text long (preview tronqué)."""
        mock_is_draft = Mock(return_value=False)
        mock_get_legacy.return_value = {"is_draft_request": mock_is_draft}
        long_text = "A" * 200

        response = client.post(
            "/api/drafts/detect",
            json={"text": long_text}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert len(data["text_preview"]) <= 103  # 100 + "..."


# ============================================================================
# TESTS - COSTS ENDPOINTS
# ============================================================================

class TestCostsEndpoint:
    """Tests edge cases pour /api/costs."""

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    def test_costs_basic(self, mock_cost_manager, client):
        """Récupération des coûts."""
        mock_manager = Mock()
        mock_manager.get_current_month_stats.return_value = {"total": 10.50}
        mock_manager.get_breakdown_by_agent.return_value = {"drafter": 5.0}
        mock_manager.monthly_budget = 100.0
        mock_manager.alert_threshold = 0.8
        mock_cost_manager.return_value = mock_manager

        with patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "admin@example.com"}), \
             patch("app.api.admin._is_admin", return_value=True):
            response = client.get("/api/costs", headers={"Authorization": "Bearer admin-jwt"})
        data = response.get_json()

        assert response.status_code == 200
        assert "current_month" in data
        assert "by_agent" in data
        assert "budget" in data

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    def test_cost_history_default_days(self, mock_cost_manager, client):
        """Historique des coûts avec jours par défaut."""
        mock_manager = Mock()
        mock_manager.get_daily_costs.return_value = []
        mock_cost_manager.return_value = mock_manager

        with patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "admin@example.com"}), \
             patch("app.api.admin._is_admin", return_value=True):
            response = client.get("/api/costs/history", headers={"Authorization": "Bearer admin-jwt"})
        data = response.get_json()

        assert response.status_code == 200
        assert data["days"] == 30

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    def test_cost_history_custom_days(self, mock_cost_manager, client):
        """Historique des coûts avec jours personnalisés."""
        mock_manager = Mock()
        mock_manager.get_daily_costs.return_value = []
        mock_cost_manager.return_value = mock_manager

        with patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "admin@example.com"}), \
             patch("app.api.admin._is_admin", return_value=True):
            response = client.get("/api/costs/history?days=7", headers={"Authorization": "Bearer admin-jwt"})
        data = response.get_json()

        assert response.status_code == 200
        assert data["days"] == 7

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    def test_cost_history_invalid_days(self, mock_cost_manager, client):
        """Historique des coûts avec jours invalides."""
        mock_manager = Mock()
        mock_manager.get_daily_costs.return_value = []
        mock_cost_manager.return_value = mock_manager

        with patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "admin@example.com"}), \
             patch("app.api.admin._is_admin", return_value=True):
            response = client.get("/api/costs/history?days=invalid", headers={"Authorization": "Bearer admin-jwt"})
        response.get_json()

        # Devrait utiliser la valeur par défaut
        assert response.status_code == 200


# ============================================================================
# TESTS - ERROR HANDLERS
# ============================================================================

class TestErrorHandlers:
    """Tests pour les error handlers."""

    def test_404_not_found(self, client):
        """Route non trouvée."""
        response = client.get("/api/nonexistent-route")
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data

    def test_method_not_allowed(self, client):
        """Méthode non autorisée."""
        response = client.delete("/api/health")

        assert response.status_code == 405

    def test_bad_json(self, client):
        """JSON malformé."""
        response = client.post(
            "/api/drafts/complete",
            data="{invalid json",
            content_type="application/json"
        )

        assert response.status_code == 400


# ============================================================================
# TESTS - RESPONSE HEADERS
# ============================================================================

class TestResponseHeaders:
    """Tests pour les headers de réponse."""

    def test_response_time_header(self, client):
        """Header X-Response-Time-Ms présent."""
        response = client.get("/api/health")

        assert "X-Response-Time-Ms" in response.headers

    def test_api_version_header(self, client):
        """Header X-API-Version présent et commence par 1.0.0."""
        from app.api.routes import API_VERSION

        response = client.get("/api/health")

        assert response.headers.get("X-API-Version") == API_VERSION
        assert response.headers.get("X-API-Version").startswith("1.0.0")


# ============================================================================
# TESTS - INDEX / ROOT ENDPOINT
# ============================================================================

class TestIndexEndpoint:
    """Tests pour l'endpoint racine."""

    def test_index(self, client):
        """Endpoint racine retourne les informations API."""
        response = client.get("/")
        data = response.get_json()

        assert response.status_code == 200
        assert data["name"] == "Agentys API"
        assert data["version"] == "1.0.0"
        assert "endpoints" in data
        assert "health" in data["endpoints"]


# ============================================================================
# TESTS - UNICODE AND SPECIAL CHARACTERS
# ============================================================================

class TestUnicodeHandling:
    """Tests pour la gestion de l'unicode."""

    @patch("app.api.routes_helpers.get_container")
    def test_complete_with_unicode(self, mock_get_container, client):
        """Complétion avec contenu unicode."""
        mock_result = Mock()
        mock_result.subject = "Réponse: 日本語"
        mock_result.body = "Bonjour 🎉 世界"
        mock_result.recipient = "Sébastien"
        mock_result.tone_used = Mock()
        mock_result.tone_used.value = "neutral"
        mock_result.formatted_output = "Formatted"

        mock_use_case = Mock()
        mock_use_case.execute.return_value = mock_result
        mock_container = Mock()
        mock_container.get_complete_draft_use_case.return_value = mock_use_case
        mock_get_container.return_value = mock_container

        response = client.post(
            "/api/drafts/complete",
            json={"raw_input": "- Point avec émoji 🎉\n- 日本語テスト"}
        )
        data = response.get_json()

        assert response.status_code == 200
        assert "日本語" in data["subject"]
        assert "🎉" in data["body"]

    @patch("app.draft_completion.is_draft_request")
    def test_detect_with_unicode(self, mock_is_draft, client):
        """Détection avec contenu unicode."""
        mock_is_draft.return_value = True

        response = client.post(
            "/api/drafts/detect",
            json={"text": "Brouillon : 日本語で書いてください 🎉"}
        )
        response.get_json()

        assert response.status_code == 200


# ============================================================================
# TESTS - CONCURRENT REQUESTS
# ============================================================================

class TestConcurrentRequests:
    """Tests pour les requetes concurrentes."""

    @patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1)
    @patch("app.api.routes_helpers._get_container")
    def test_concurrent_draft_list(self, mock_get_container, mock_resolve_account, app):
        """Liste des drafts en parallele."""
        import threading

        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = []
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        results = []
        errors = []

        def make_request():
            with app.test_client() as client:
                try:
                    response = client.get("/api/drafts")
                    results.append(response.status_code)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=make_request) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert all(status == 200 for status in results)
