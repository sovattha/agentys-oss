"""Tests for POST /api/emails/{id}/draft endpoint."""

from unittest.mock import Mock, patch

import pytest


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



class TestCreateDraftEndpoint:
    """Tests for POST /api/emails/{id}/draft endpoint."""

    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_success(self, mock_get_provider, mock_get_email,
                                   mock_sig, mock_resolve1, mock_resolve2, client):
        """Create draft returns 201 with draft_id."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"

        mock_provider = Mock()
        mock_provider.create_draft.return_value = "new-draft-id"
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-id/draft",
            json={
                "subject": "Re: Test Subject",
                "body": "This is the draft body",
            },
        )
        data = response.get_json()

        assert response.status_code == 201
        assert data["success"] is True
        assert data["draft_id"] == "new-draft-id"
        assert data["email_id"] == "test-email-id"

    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=5)
    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=5)
    @patch("app.api.routes_emails._resolve_account_id_for_provider", return_value=4)
    @patch(
        "app.utils.signature.append_signature",
        side_effect=lambda body, **kw: f"{body} [sig:{kw.get('account_id')}]",
    )
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_uses_provider_account_for_signature(
        self, mock_get_provider, mock_get_email, mock_sig,
        mock_resolve_provider, mock_resolve_helper, mock_resolve_route, client,
    ):
        """Signature must follow the provider selected for this request, not a later account switch."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"

        mock_provider = Mock(spec=["create_draft", "authenticate", "mark_as_read"])
        mock_provider.create_draft.return_value = "new-draft-id"
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-id/draft",
            json={
                "subject": "Re: Test Subject",
                "body": "This is the draft body",
            },
        )

        assert response.status_code == 201
        mock_resolve_provider.assert_called_once_with(mock_provider)
        assert mock_sig.call_count == 2
        assert all(call.kwargs["account_id"] == 4 for call in mock_sig.call_args_list)
        assert mock_provider.create_draft.call_args.kwargs["body"].endswith("[sig:4]")

    @patch("app.api.routes_emails._resolve_account_id_for_provider", return_value=4)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_string_false_does_not_send(
        self, mock_get_provider, mock_get_email, mock_sig,
        mock_resolve_provider, client,
    ):
        """Only JSON boolean true may trigger send; string 'false' is a draft."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"

        mock_provider = Mock()
        mock_provider.PROVIDER_NAME = "gmail"
        mock_provider.create_draft.return_value = "new-draft-id"
        mock_provider.send_reply_directly.return_value = True
        mock_provider.send_draft.return_value = True
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-id/draft",
            json={
                "subject": "Re: Test Subject",
                "body": "This is the draft body",
                "send": "false",
            },
        )
        data = response.get_json()

        assert response.status_code == 201
        assert data["sent"] is False
        mock_provider.create_draft.assert_called_once()
        mock_provider.send_reply_directly.assert_not_called()
        mock_provider.send_draft.assert_not_called()

    @patch("app.api.routes_emails._find_recent_sent_reply", return_value="existing-sent-id")
    @patch("app.api.routes_emails._resolve_account_id_for_provider", return_value=4)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_send_retry_does_not_duplicate_recent_sent_reply(
        self,
        mock_get_provider,
        mock_get_email,
        mock_sig,
        mock_resolve_provider,
        mock_find_recent_sent_reply,
        client,
    ):
        """A retry after a browser timeout must not send the same reply twice."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"

        mock_provider = Mock()
        mock_provider.PROVIDER_NAME = "gmail"
        mock_provider.send_reply_directly.return_value = "new-sent-id"
        mock_provider.create_draft.return_value = "new-draft-id"
        mock_provider.send_draft.return_value = True
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-id/draft",
            json={
                "subject": "Re: Test Subject",
                "body": "This is the draft body",
                "send": True,
            },
        )
        data = response.get_json()

        assert response.status_code == 200
        assert data["success"] is True
        assert data["duplicate"] is True
        assert data["sent"] == "existing-sent-id"
        mock_find_recent_sent_reply.assert_called_once()
        mock_provider.send_reply_directly.assert_not_called()
        mock_provider.create_draft.assert_not_called()
        mock_provider.send_draft.assert_not_called()

    def test_create_draft_no_json_body(self, client):
        """Create draft without JSON body returns 400."""
        response = client.post("/api/emails/test-id/draft")
        assert response.status_code in (400, 415)

    def test_create_draft_empty_json(self, client):
        """Create draft with empty JSON returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_create_draft_missing_subject(self, client):
        """Create draft without subject returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"body": "Draft body"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "subject" in data["error"].lower()

    def test_create_draft_missing_body(self, client):
        """Create draft without body returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": "Re: Test"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "body" in data["error"].lower()

    def test_create_draft_empty_subject(self, client):
        """Create draft with empty subject returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": "", "body": "Draft body"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "subject" in data["error"].lower()

    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_empty_body_allowed(self, mock_get_provider, mock_get_email,
                                              mock_sig, mock_resolve1, mock_resolve2, client):
        """Create draft with empty body is allowed."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"

        mock_provider = Mock()
        mock_provider.create_draft.return_value = "draft-123"
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-id/draft",
            json={"subject": "Re: Test", "body": ""},
        )

        assert response.status_code == 201

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_auth_failure(self, mock_get_provider, client):
        """Create draft with authentication failure returns 401."""
        from werkzeug.exceptions import Unauthorized
        mock_get_provider.side_effect = Unauthorized("Authentication failed")

        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": "Re: Test", "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 401
        assert "error" in data

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_email_not_found(self, mock_get_provider, mock_get_email, client):
        """Create draft with non-existent email returns 404."""
        from werkzeug.exceptions import NotFound
        mock_get_provider.return_value = Mock()
        mock_get_email.side_effect = NotFound("Email not found")

        response = client.post(
            "/api/emails/nonexistent-id/draft",
            json={"subject": "Re: Test", "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 404
        assert "error" in data

    def test_create_draft_invalid_email_id_format(self, client):
        """Create draft with invalid email_id format returns 400."""
        response = client.post(
            "/api/emails/invalid--id!!/draft",
            json={"subject": "Re: Test", "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "email_id" in data["error"].lower()

    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_provider_error(self, mock_get_provider, mock_get_email,
                                          mock_sig, mock_resolve1, mock_resolve2, client):
        """Create draft with provider error returns 500."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"

        mock_provider = Mock()
        mock_provider.create_draft.side_effect = Exception("Provider error")
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-id/draft",
            json={"subject": "Re: Test", "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 500
        assert "error" in data


class TestCreateDraftEdgeCases:
    """Edge case tests for POST /api/emails/{id}/draft endpoint."""

    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_unicode_content(self, mock_get_provider, mock_get_email,
                                           mock_sig, mock_resolve1, mock_resolve2, client):
        """Create draft with unicode content works correctly."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"

        mock_provider = Mock()
        mock_provider.create_draft.return_value = "draft-123"
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-id/draft",
            json={
                "subject": "Re: 日本語のメール 🎉",
                "body": "Contenu français avec accents: é, è, à, ù",
            },
        )

        assert response.status_code == 201

    def test_create_draft_email_id_too_long(self, client):
        """Create draft with email_id too long returns 400."""
        long_id = "a" * 1001

        response = client.post(
            f"/api/emails/{long_id}/draft",
            json={"subject": "Re: Test", "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_create_draft_whitespace_only_subject(self, client):
        """Create draft with whitespace-only subject returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": "   ", "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "subject" in data["error"].lower()

    def test_create_draft_subject_as_number(self, client):
        """Create draft with subject as number returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": 12345, "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "subject" in data["error"].lower()

    def test_create_draft_body_as_number(self, client):
        """Create draft with body as number returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": "Re: Test", "body": 12345},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "body" in data["error"].lower()

    def test_create_draft_subject_as_array(self, client):
        """Create draft with subject as array returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": ["Re:", "Test"], "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_create_draft_body_as_object(self, client):
        """Create draft with body as object returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": "Re: Test", "body": {"content": "Body"}},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_create_draft_wrong_content_type(self, client):
        """Create draft with wrong Content-Type returns error."""
        response = client.post(
            "/api/emails/test-id/draft",
            data='{"subject": "Re: Test", "body": "Body"}',
            content_type="text/plain",
        )

        assert response.status_code in (400, 415)

    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_ignores_extra_fields(self, mock_get_provider, mock_get_email,
                                                mock_sig, mock_resolve1, mock_resolve2, client):
        """Create draft ignores extra fields in request."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"

        mock_provider = Mock()
        mock_provider.create_draft.return_value = "draft-123"
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-id/draft",
            json={
                "subject": "Re: Test",
                "body": "Body",
                "extra_field": "should be ignored",
                "another": 123,
            },
        )

        assert response.status_code == 201

    def test_create_draft_null_subject(self, client):
        """Create draft with null subject returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": None, "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_create_draft_null_body(self, client):
        """Create draft with null body returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": "Re: Test", "body": None},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_create_draft_invalid_json(self, client):
        """Create draft with invalid JSON returns error."""
        response = client.post(
            "/api/emails/test-id/draft",
            data="not valid json{",
            content_type="application/json",
        )

        assert response.status_code in (400, 415)

    def test_create_draft_subject_exceeds_max_length(self, client):
        """Create draft with subject exceeding max length returns 400."""
        long_subject = "X" * 1000

        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": long_subject, "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "subject" in data["error"].lower()
        assert "998" in data["error"]

    def test_create_draft_body_exceeds_max_length(self, client):
        """Create draft with body exceeding max length returns 400."""
        long_body = "X" * 1_000_001

        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": "Re: Test", "body": long_body},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "body" in data["error"].lower()
        assert "1000000" in data["error"]

    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_returns_502_when_draft_id_none(
        self, mock_get_provider, mock_get_email,
        mock_sig, mock_resolve1, mock_resolve2, client
    ):
        """Audit Cluster A (2026-05-10) B-01: when provider.create_draft returns
        None, the endpoint must respond 502 — NOT 201 with success=false. The
        frontend trusts 2xx and used to show a confirmation toast for a draft
        that did not exist."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"

        mock_provider = Mock()
        mock_provider.create_draft.return_value = None
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-id/draft",
            json={"subject": "Re: Test", "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 502
        assert data.get("success") is not True
        assert "error" in data

    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_create_draft_returns_502_when_draft_id_empty_string(
        self, mock_get_provider, mock_get_email,
        mock_sig, mock_resolve1, mock_resolve2, client
    ):
        """Audit Cluster A (2026-05-10) B-01: empty-string draft_id is treated
        as a silent failure, same as None — must return 502."""
        mock_email = Mock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"

        mock_provider = Mock()
        mock_provider.create_draft.return_value = ""
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider
        mock_get_email.return_value = mock_email

        response = client.post(
            "/api/emails/test-email-id/draft",
            json={"subject": "Re: Test", "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 502
        assert data.get("success") is not True
        assert "error" in data

    def test_create_draft_boolean_subject(self, client):
        """Create draft with boolean subject returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": True, "body": "Body"},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data

    def test_create_draft_boolean_body(self, client):
        """Create draft with boolean body returns 400."""
        response = client.post(
            "/api/emails/test-id/draft",
            json={"subject": "Re: Test", "body": False},
        )
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
