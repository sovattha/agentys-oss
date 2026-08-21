"""Tests unitaires pour l'endpoint POST /api/emails/<draft_id>/send."""

from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def app():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestSendDraftEndpoint:

    @patch("app.multi_accounts.get_current_account", return_value=None)
    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_send_draft_success(self, mock_get_provider, mock_acct, client):
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/draft-abc123/send")
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["draft_id"] == "draft-abc123"
        assert data["message"] == "Email sent successfully"
        mock_provider.send_draft.assert_called_once_with("draft-abc123")

    @patch("app.multi_accounts.get_current_account", return_value=None)
    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_send_draft_auth_failure(self, mock_get_provider, mock_acct, client):
        mock_provider = Mock()
        mock_provider.authenticate.return_value = False
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/draft-abc123/send")
        data = response.get_json()

        assert response.status_code == 503
        assert "error" in data

    @patch("app.multi_accounts.get_current_account", return_value=None)
    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_send_draft_not_found(self, mock_get_provider, mock_acct, client):
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.return_value = False
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/nonexistent-draft/send")
        data = response.get_json()

        assert response.status_code in (404, 502)
        assert "error" in data

    def test_send_draft_invalid_id_format(self, client):
        response = client.post("/api/emails/invalid%20id%20with%20spaces/send")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Invalid draft ID format" in data["error"]

    def test_send_draft_empty_id(self, client):
        response = client.post("/api/emails//send")

        assert response.status_code in (404, 405)

    @patch("app.multi_accounts.get_current_account", return_value=None)
    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_send_draft_internal_error(self, mock_get_provider, mock_acct, client):
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.side_effect = Exception("Unexpected error")
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/draft-abc123/send")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data
        assert "internal error" in data["error"].lower()

    @patch("app.multi_accounts.get_current_account", return_value=None)
    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_send_draft_id_with_special_allowed_chars(self, mock_get_provider, mock_acct, client):
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/draft_123-abc.test@user+tag/send")
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["draft_id"] == "draft_123-abc.test@user+tag"

    def test_send_draft_id_too_long(self, client):
        long_id = "a" * 300
        response = client.post(f"/api/emails/{long_id}/send")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "Invalid draft ID format" in data["error"]


class TestSendDraftEdgeCases:
    """Edge cases et tests de sécurité pour l'endpoint send_draft."""

    def test_send_draft_method_not_allowed_get(self, client):
        """GET au lieu de POST doit retourner 405."""
        response = client.get("/api/emails/draft-abc123/send")

        assert response.status_code == 405

    def test_send_draft_method_not_allowed_put(self, client):
        """PUT au lieu de POST doit retourner 405."""
        response = client.put("/api/emails/draft-abc123/send")

        assert response.status_code == 405

    def test_send_draft_method_not_allowed_delete(self, client):
        """DELETE au lieu de POST doit retourner 405."""
        response = client.delete("/api/emails/draft-abc123/send")

        assert response.status_code == 405

    def test_send_draft_path_traversal_attempt(self, client):
        """Tentative de path traversal - Flask route vers 404 (URL invalide)."""
        # Note: Flask/Werkzeug intercepte les / encodés et ne trouve pas de route
        response = client.post("/api/emails/..%2F..%2Fetc%2Fpasswd/send")

        # Flask retourne 404 car l'URL avec slashes ne matche pas la route
        assert response.status_code == 404

    def test_send_draft_xss_attempt_script_tag(self, client):
        """Tentative XSS avec balise script - Flask route vers 404."""
        # Note: Flask ne route pas les URLs avec < > non encodés
        response = client.post("/api/emails/<script>alert(1)</script>/send")

        assert response.status_code == 404

    def test_send_draft_xss_attempt_encoded(self, client):
        """Tentative XSS encodée - Flask route vers 404."""
        # Note: Flask décode les < > et ne trouve pas de route
        response = client.post("/api/emails/%3Cscript%3Ealert%281%29%3C%2Fscript%3E/send")

        assert response.status_code == 404

    def test_send_draft_sql_injection_attempt(self, client):
        """Tentative SQL injection doit être rejetée."""
        response = client.post("/api/emails/1'; DROP TABLE emails;--/send")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_send_draft_null_byte_injection(self, client):
        """Tentative null byte injection doit être rejetée."""
        response = client.post("/api/emails/draft%00malicious/send")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_send_draft_unicode_id_rejected(self, client):
        """Unicode non-ASCII dans l'ID doit être rejeté."""
        response = client.post("/api/emails/draft-日本語/send")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_send_draft_emoji_id_rejected(self, client):
        """Emoji dans l'ID doit être rejeté."""
        response = client.post("/api/emails/draft-📧/send")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_send_draft_newline_injection(self, client):
        """Newline dans l'ID doit être rejeté (log injection)."""
        response = client.post("/api/emails/draft%0Amalicious/send")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_send_draft_carriage_return_injection(self, client):
        """Carriage return dans l'ID doit être rejeté."""
        response = client.post("/api/emails/draft%0Dmalicious/send")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    @patch("app.multi_accounts.get_current_account", return_value=None)
    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_send_draft_auth_exception(self, mock_get_provider, mock_acct, client):
        """Exception lors de authenticate() doit retourner 500."""
        mock_provider = Mock()
        mock_provider.authenticate.side_effect = Exception("Network error")
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/draft-abc123/send")
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data

    @patch("app.multi_accounts.get_current_account", return_value=None)
    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_send_draft_idempotence_double_send(self, mock_get_provider, mock_acct, client):
        """Double envoi du même draft - premier réussit, second échoue."""
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.side_effect = [True, False]
        mock_get_provider.return_value = mock_provider

        # Premier envoi réussit
        response1 = client.post("/api/emails/draft-abc123/send")
        assert response1.status_code == 200

        # Second envoi échoue (draft déjà envoyé/supprimé)
        response2 = client.post("/api/emails/draft-abc123/send")
        assert response2.status_code in (404, 502)

    def test_send_draft_id_boundary_255_chars(self, client):
        """ID de 255 caractères (limite -1) doit être accepté par validation."""
        valid_id = "a" * 255
        # Note: Ce test vérifie juste la validation format, pas l'envoi réel
        response = client.post(f"/api/emails/{valid_id}/send")
        # Sans mock, on aura une erreur d'auth, mais pas 400
        assert response.status_code != 400

    def test_send_draft_id_boundary_256_chars(self, client):
        """ID de 256 caractères (limite exacte) doit être accepté."""
        valid_id = "a" * 256
        response = client.post(f"/api/emails/{valid_id}/send")
        # Sans mock, on aura une erreur d'auth, mais pas 400
        assert response.status_code != 400

    def test_send_draft_id_boundary_257_chars(self, client):
        """ID de 257 caractères (limite +1) doit être rejeté."""
        invalid_id = "a" * 257
        response = client.post(f"/api/emails/{invalid_id}/send")
        data = response.get_json()

        assert response.status_code == 400
        assert "Invalid draft ID format" in data["error"]

    @patch("app.multi_accounts.get_current_account", return_value=None)
    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_send_draft_provider_returns_none(self, mock_get_provider, mock_acct, client):
        """Provider retournant None (au lieu de bool) doit être géré."""
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.return_value = None  # Falsy value
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/draft-abc123/send")

        # None est falsy, donc traité comme échec
        assert response.status_code in (404, 502)

    def test_send_draft_only_dots(self, client):
        """ID composé uniquement de points doit être accepté (pattern valide)."""
        response = client.post("/api/emails/.../send")
        # Valide selon le pattern, mais échouera à l'auth
        assert response.status_code != 400

    def test_send_draft_only_dashes(self, client):
        """ID composé uniquement de tirets doit être accepté."""
        response = client.post("/api/emails/---/send")
        assert response.status_code != 400

    def test_send_draft_single_char_id(self, client):
        """ID d'un seul caractère doit être accepté."""
        response = client.post("/api/emails/a/send")
        assert response.status_code != 400

    @patch("app.multi_accounts.get_current_account", return_value=None)
    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_send_draft_response_content_type(self, mock_get_provider, mock_acct, client):
        """Vérifier que la réponse est bien en JSON."""
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/draft-abc123/send")

        assert response.content_type == "application/json"

    @patch("app.multi_accounts.get_current_account", return_value=None)
    @patch("app.api.routes_emails.LegacyModuleLoader.email_provider")
    def test_send_draft_preserves_id_case(self, mock_get_provider, mock_acct, client):
        """Vérifier que la casse de l'ID est préservée."""
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.return_value = True
        mock_get_provider.return_value = mock_provider

        response = client.post("/api/emails/DraftABC123XYZ/send")
        data = response.get_json()

        assert data["draft_id"] == "DraftABC123XYZ"
        mock_provider.send_draft.assert_called_once_with("DraftABC123XYZ")
