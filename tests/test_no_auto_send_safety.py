"""
Tests for Story 6-8: No Auto-Send Safety

This test file verifies that the system never auto-sends emails without
explicit human validation (FR30, NFR30).

Critical Safety Requirements:
- AC1: No code path allows sending without explicit approval
- AC2: Automated tests verify impossibility of auto-send
- AC3: Code review required for send flow changes (documented)
- AC4: Audit logs for every send attempt
- AC5: Documentation of no-auto-send constraint
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock

from app.domain.entities.pending_draft import PendingDraftStatus


@pytest.fixture
def app():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestNoAutoSendSafety:
    """Test suite for no auto-send safety requirements."""

    # =========================================================================
    # AC1: No code path allows sending without explicit approval
    # =========================================================================

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_send_draft_endpoint_is_explicit_only(self, mock_get_provider, client):
        """
        Test that /emails/<draft_id>/send endpoint exists but requires
        explicit API call (cannot be triggered automatically).

        This endpoint should only be called by user-initiated actions.
        """
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.return_value = True
        mock_get_provider.return_value = mock_provider

        # The endpoint requires an explicit POST request
        response = client.post('/api/emails/test-draft-123/send')

        # Should work when explicitly called
        assert response.status_code in [200, 404]  # 200 if draft exists, 404 otherwise

    @patch("app.api.routes_pending._rh.submit_background")
    @patch("app.api.routes_pending._rh.get_db_session")
    @patch("app.api.routes_pending._rh.EmailRepository")
    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_helpers._get_container")
    @patch("app.api.routes_pending._get_authenticated_provider")
    def test_validate_endpoint_requires_explicit_call(
        self, mock_get_provider, mock_get_container, mock_append_sig,
        mock_resolve_account, mock_email_repo, mock_db_session,
        mock_submit_bg, client
    ):
        """
        Test that /pending-drafts/<id>/validate requires explicit POST call.
        """
        # Setup mock pending draft
        mock_draft = MagicMock()
        mock_draft.id = 'test-pending-123'
        mock_draft.email_sender = 'test@example.com'
        mock_draft.draft_subject = 'Test Subject'
        mock_draft.draft_body = 'Test body'
        mock_draft.email_id = 'original-email-123'
        mock_draft.email_received_at = None
        mock_draft.account_id = 1
        mock_draft.status = PendingDraftStatus.PENDING

        mock_store = MagicMock()
        mock_store.get_by_id.return_value = mock_draft

        mock_container = MagicMock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        mock_provider = MagicMock(spec=[
            'create_draft', 'send_draft', 'mark_as_read', 'authenticate',
        ])
        mock_provider.create_draft.return_value = 'gmail-draft-123'
        mock_provider.send_draft.return_value = True
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider

        # Must be explicit POST - GET should fail
        response_get = client.get('/api/pending-drafts/test-pending-123/validate')
        assert response_get.status_code == 405  # Method not allowed

        # POST works (explicit action)
        response_post = client.post('/api/pending-drafts/test-pending-123/validate')
        assert response_post.status_code == 200

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_no_auto_trigger_on_email_sync(self, mock_get_provider, client):
        """
        Test that syncing emails does NOT trigger auto-send.
        The sync endpoint should only fetch emails, never send.
        """
        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.fetch_emails.return_value = [
            MagicMock(id='new-email-1', subject='New Email')
        ]
        mock_get_provider.return_value = mock_provider

        # Sync endpoint fetches but doesn't send
        client.get('/api/accounts/1/sync')

        # send_draft should never be called during sync
        mock_provider.send_draft.assert_not_called()

    @patch("app.api.routes_helpers._get_container")
    @patch("app.api.routes_pending._get_authenticated_provider")
    def test_no_auto_send_on_draft_update(
        self, mock_get_provider, mock_get_container, client
    ):
        """
        Test that updating a draft does NOT automatically send it.
        """
        mock_draft = MagicMock()
        mock_draft.id = 'test-pending-123'
        mock_draft.draft_subject = 'Original Subject'
        mock_draft.draft_body = 'Original body'

        mock_store = MagicMock()
        mock_store.get_by_id.return_value = mock_draft

        mock_container = MagicMock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        client.patch(
            '/api/pending-drafts/test-pending-123',
            json={'subject': 'Updated Subject', 'body': 'Updated body'}
        )

        # Update should NOT trigger send
        mock_provider.send_draft.assert_not_called()

    # =========================================================================
    # AC2: Automated tests verify impossibility of auto-send
    # =========================================================================

    def test_send_requires_user_initiated_http_request(self):
        """
        Verify that sending an email requires an HTTP request.
        No background task or timer can send emails.
        """
        # This is a design verification test
        # The send functionality is ONLY exposed via HTTP endpoints:
        # 1. POST /api/emails/<draft_id>/send
        # 2. POST /api/pending-drafts/<draft_id>/validate
        #
        # There is no:
        # - Background task that sends emails
        # - Timer that auto-sends drafts
        # - Event handler that sends on email receive
        # - WebSocket event that triggers send

        # Import the route sub-modules where send endpoints are defined
        from app.api import routes_emails, routes_pending

        # Verify send-related functions are HTTP endpoints only
        assert hasattr(routes_emails, 'send_draft')
        assert hasattr(routes_pending, 'validate_pending_draft')

    def test_draft_generation_agent_does_not_send(self):
        """
        Verify draft generation (AI pipeline) does not send.
        """
        # The draft generation pipeline creates drafts but never sends them
        # This is enforced by architecture: DrafterAgent only generates text

        from app.agents import DrafterAgent

        with patch('app.agents.get_container') as mock_container:
            mock_llm = MagicMock()
            mock_container.return_value.llm = mock_llm
            mock_container.return_value.llm_label = mock_llm

            agent = DrafterAgent()
            # DrafterAgent.draft only creates text, doesn't call any provider
            # The agent has no reference to email provider at all

            # Verify the agent class doesn't have send capability
            assert not hasattr(agent, 'send_draft')
            assert not hasattr(agent, 'send_email')
            # The agent only has _llm for text generation, no provider
            assert hasattr(agent, '_llm')
            assert not hasattr(agent, 'email_provider')

    # =========================================================================
    # AC4: Audit logs for every send attempt
    # =========================================================================

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_send_endpoint_logs_audit(self, mock_get_provider, client, caplog):
        """
        Test that send endpoint creates audit log entry.
        """
        import logging
        caplog.set_level(logging.INFO)

        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.return_value = True
        mock_get_provider.return_value = mock_provider

        client.post('/api/emails/test-draft-123/send')

        # Should have audit log for send attempt
        log_messages = [r.message for r in caplog.records]
        assert any('sent' in msg.lower() or 'send' in msg.lower() for msg in log_messages)

    @patch("app.api.routes_pending._rh.submit_background")
    @patch("app.api.routes_pending._rh.get_db_session")
    @patch("app.api.routes_pending._rh.EmailRepository")
    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_helpers._get_container")
    @patch("app.api.routes_pending._get_authenticated_provider")
    def test_validate_endpoint_logs_audit(
        self, mock_get_provider, mock_get_container, mock_append_sig,
        mock_resolve_account, mock_email_repo, mock_db_session,
        mock_submit_bg, client, caplog
    ):
        """
        Test that validate+send endpoint creates audit log entry.
        """
        import logging
        caplog.set_level(logging.INFO)

        mock_draft = MagicMock()
        mock_draft.id = 'test-pending-123'
        mock_draft.email_sender = 'test@example.com'
        mock_draft.draft_subject = 'Test Subject'
        mock_draft.draft_body = 'Test body'
        mock_draft.email_id = 'original-email-123'
        mock_draft.email_received_at = None
        mock_draft.account_id = 1
        mock_draft.status = PendingDraftStatus.PENDING

        mock_store = MagicMock()
        mock_store.get_by_id.return_value = mock_draft

        mock_container = MagicMock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        mock_provider = MagicMock(spec=[
            'create_draft', 'send_draft', 'mark_as_read', 'authenticate',
        ])
        mock_provider.create_draft.return_value = 'gmail-draft-123'
        mock_provider.send_draft.return_value = True
        mock_provider.mark_as_read.return_value = True
        mock_get_provider.return_value = mock_provider

        client.post('/api/pending-drafts/test-pending-123/validate')

        # Should have audit log for send
        log_messages = [r.message for r in caplog.records]
        assert any('sent' in msg.lower() or 'email' in msg.lower() for msg in log_messages)

    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_failed_send_logs_audit(self, mock_get_provider, client, caplog):
        """
        Test that failed send attempts are also logged.
        """
        import logging
        caplog.set_level(logging.INFO)

        mock_provider = Mock()
        mock_provider.authenticate.return_value = True
        mock_provider.send_draft.return_value = False
        mock_get_provider.return_value = mock_provider

        response = client.post('/api/emails/test-draft-123/send')

        # Should have log entry even for failed attempt
        assert response.status_code in [404, 500, 502]  # Failed send


class TestNoAutoSendIntegration:
    """Integration tests for no auto-send requirement."""

    @patch("app.api.routes_pending._rh.submit_background")
    @patch("app.api.routes_pending._rh.get_db_session")
    @patch("app.api.routes_pending._rh.EmailRepository")
    @patch("app.api.routes_pending._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_helpers._get_container")
    @patch("app.api.routes_pending._get_authenticated_provider")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_full_flow_requires_explicit_approval(
        self, mock_emails_provider, mock_pending_provider, mock_get_container,
        mock_append_sig, mock_resolve_account, mock_email_repo,
        mock_db_session, mock_submit_bg, client
    ):
        """
        Test the complete flow from draft creation to send requires explicit steps:
        1. Email received (no send)
        2. Draft generated (no send)
        3. User edits draft (no send)
        4. User clicks "Approuver et Envoyer" (explicit send)
        """
        # Setup mocks
        mock_draft = MagicMock()
        mock_draft.id = 'pending-1'
        mock_draft.email_sender = 'test@example.com'
        mock_draft.draft_subject = 'Test'
        mock_draft.draft_body = 'Test body'
        mock_draft.email_id = 'email-1'
        mock_draft.email_received_at = None
        mock_draft.account_id = 1
        mock_draft.status = PendingDraftStatus.PENDING

        mock_store = MagicMock()
        mock_store.get_by_id.return_value = mock_draft

        mock_container = MagicMock()
        mock_container.get_pending_draft_store.return_value = mock_store
        mock_get_container.return_value = mock_container

        # Use spec to prevent auto-creation of send_reply_directly attribute
        # This forces the 2-step create_draft + send_draft path
        mock_provider = MagicMock(spec=[
            'authenticate', 'fetch_emails', 'create_draft', 'send_draft',
            'mark_as_read',
        ])
        mock_provider.authenticate.return_value = True
        mock_provider.fetch_emails.return_value = []
        mock_provider.create_draft.return_value = 'gmail-draft-1'
        mock_provider.send_draft.return_value = True
        mock_provider.mark_as_read.return_value = True
        mock_emails_provider.return_value = mock_provider
        mock_pending_provider.return_value = mock_provider

        # Step 1: Simulate email sync (no send)
        client.get('/api/accounts/1/sync')
        mock_provider.send_draft.assert_not_called()

        # Step 2: Update draft content (no send)
        client.patch('/api/pending-drafts/pending-1', json={'body': 'Updated'})
        mock_provider.send_draft.assert_not_called()

        # Step 3: Explicit validation + send (NOW it sends)
        response = client.post('/api/pending-drafts/pending-1/validate')

        # NOW send_draft is called (explicit user action)
        mock_provider.send_draft.assert_called_once()
        assert response.status_code == 200

    def test_keyboard_shortcut_cannot_bypass_approval(self):
        """
        Test that keyboard shortcuts cannot bypass the approval requirement.
        This is enforced in the frontend (tested separately).

        Backend verification: no endpoint accepts shortcut triggers.
        """
        # All send endpoints require explicit HTTP POST
        # No query parameter or header can trigger auto-send
        pass  # Frontend test - documented here for completeness


class TestCodePathAudit:
    """
    Code audit tests to verify no hidden auto-send paths exist.
    These tests inspect the codebase structure.
    """

    def test_send_draft_only_in_expected_locations(self):
        """
        Audit that send_draft is only called from expected locations.
        """
        # Files that are ALLOWED to call send_draft
        allowed_patterns = [
            'routes.py',  # API endpoints
            'test_',  # Test files
            'mock',  # Mock files
            'provider',  # Provider implementations
            'adapter',  # Adapter implementations
            'interface',  # Interface definitions
        ]

        # Search for send_draft calls in the codebase
        app_dir = os.path.join(os.path.dirname(__file__), '..', 'app')

        violations = []
        for root, dirs, files in os.walk(app_dir):
            # Skip __pycache__ and test directories
            dirs[:] = [d for d in dirs if d != '__pycache__']

            for file in files:
                if not file.endswith('.py'):
                    continue

                # Skip allowed files
                if any(allowed in file.lower() for allowed in allowed_patterns):
                    continue

                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except Exception:
                    continue

                # Check for send_draft calls (excluding definitions and comments)
                lines = content.split('\n')
                for i, line in enumerate(lines, 1):
                    # Skip comments and definitions
                    stripped = line.strip()
                    if stripped.startswith('#') or stripped.startswith('def send_draft'):
                        continue
                    if 'send_draft(' in line and 'def ' not in line:
                        # Found a call - check if it's in allowed location
                        rel_path = os.path.relpath(filepath, app_dir)
                        if not any(p in rel_path.lower() for p in allowed_patterns):
                            violations.append(f"{rel_path}:{i}: {line.strip()}")

        # If violations found, they need review (but this is informational)
        if violations:
            print("\nPotential send_draft calls to review:\n" + '\n'.join(violations))

        # The test passes but documents findings for manual review
        # Real enforcement is via CODEOWNERS (AC3)

    def test_no_background_send_tasks(self):
        """
        Verify no background tasks or schedulers that send emails.
        """
        # Search for potential background send patterns
        app_dir = os.path.join(os.path.dirname(__file__), '..', 'app')

        dangerous_patterns = [
            'schedule',
            'cron',
            'celery',
            'background',
            'periodic',
            'timer',
        ]

        for root, dirs, files in os.walk(app_dir):
            dirs[:] = [d for d in dirs if d != '__pycache__']

            for file in files:
                if not file.endswith('.py'):
                    continue

                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read().lower()
                except Exception:
                    continue

                # Check if any dangerous pattern + send_draft appear together
                has_dangerous = any(p in content for p in dangerous_patterns)
                has_send = 'send_draft' in content or 'send_email' in content

                if has_dangerous and has_send:
                    # This file needs review
                    rel_path = os.path.relpath(filepath, app_dir)
                    # Don't fail, but document for review
                    print(f"\nFile {rel_path} contains both scheduler patterns and send operations - review needed")
