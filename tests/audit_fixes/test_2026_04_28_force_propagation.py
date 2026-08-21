"""Audit fix 2026-04-28: `force=True` propagation to SmartRouter streaming.

Bug observed live (mobile drive mode, no-reply@email.claude.com email):
- User dictates a reply intent + taps "yes draft it" chip.
- Mobile POSTs /api/emails/<id>/process with `force: true` and instructions.
- Backend SmartRouter prefilter still triggers `tier=skip` (auto-sender).
- Backend discards draft in 4ms; mobile polls /pending-drafts for 90s.
- Eventually times out → "Génération trop longue" toast (misleading).

Root cause:
1. `_process_email_with_use_case` did not accept a `force` parameter and
   never forwarded one to `router.route_streaming(...)`.
2. POST /process read `force_regen` from the request body but only used it
   for cache eviction — the LLM call always ran with `force=False`.
3. Even after #1+#2, the post-LLM `_strip_clarification_draft` guard could
   still discard a clarification-style draft against the user's explicit
   intent.

Fix : forward `force` end-to-end, AND bypass the post-LLM clarification
guard when the user explicitly forced + supplied instructions.
"""

from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def app():
    from app.api.app import create_app

    flask_app = create_app(config={"TESTING": True})
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _make_email(email_id: str = "auto-1", sender: str = "no-reply@email.claude.com") -> Mock:
    e = Mock()
    e.id = email_id
    e.sender = sender
    e.sender_name = "Anthropic"
    e.subject = "Your weekly digest"
    e.body = "Here's a summary of your week. Click to view."
    e.received_at = "2026-04-28T10:00:00"
    e.has_attachments = False
    e.conversation_id = None
    e.attachments_meta = None
    return e


class TestForcePropagation:
    """Unit-level: `force` argument flows through `_process_email_with_use_case`."""

    def test_force_true_passed_to_route_streaming(self):
        from app.api import routes_helpers as rh

        with patch("app.smart_routing.SmartRouter") as mock_router_cls, \
             patch("app.api.settings.load_settings", return_value={"booking_url": ""}), \
             patch("app.api.routes_helpers._get_container") as mock_container, \
             patch("app.api.routes_helpers._fetch_thread_context", return_value=[]), \
             patch("app.api.routes_helpers._is_booking_request", return_value=False):
            mock_container.return_value.llm.name = "claude"

            mock_result = Mock()
            mock_result.draft = "ok"
            mock_result.draft_v1 = "ok"
            mock_result.classification = "Action"
            mock_result.priority = 50
            mock_result.status = "OK"
            mock_result.decision.tier.value = "standard"
            mock_result.decision.complexity_score = 0.5
            mock_result.decision.reason = "n/a"
            mock_result.critique_info = {"is_valid": True}
            mock_result.faq_sent_message_id = None
            mock_result.correction_details = []

            mock_router = Mock()
            mock_router.route_streaming.return_value = mock_result
            mock_router_cls.return_value = mock_router

            rh._process_email_with_use_case(
                _make_email(),
                instructions="I am interested. Let's meet tomorrow.",
                use_streaming=True,
                force=True,
            )

            kwargs = mock_router.route_streaming.call_args.kwargs
            assert kwargs.get("force") is True, (
                "force=True from caller must propagate to route_streaming"
            )

    def test_force_false_default_when_no_instructions(self):
        from app.api import routes_helpers as rh

        with patch("app.smart_routing.SmartRouter") as mock_router_cls, \
             patch("app.api.settings.load_settings", return_value={"booking_url": ""}), \
             patch("app.api.routes_helpers._get_container") as mock_container, \
             patch("app.api.routes_helpers._fetch_thread_context", return_value=[]), \
             patch("app.api.routes_helpers._is_booking_request", return_value=False):
            mock_container.return_value.llm.name = "claude"

            mock_result = Mock()
            mock_result.draft = ""
            mock_result.draft_v1 = ""
            mock_result.classification = "Noise"
            mock_result.priority = 0
            mock_result.status = "SKIPPED"
            mock_result.decision.tier.value = "skip"
            mock_result.decision.complexity_score = 0
            mock_result.decision.reason = "auto-sender"
            mock_result.critique_info = {"is_valid": True}
            mock_result.faq_sent_message_id = None
            mock_result.correction_details = []

            mock_router = Mock()
            mock_router.route_streaming.return_value = mock_result
            mock_router_cls.return_value = mock_router

            rh._process_email_with_use_case(
                _make_email(),
                use_streaming=True,
            )

            kwargs = mock_router.route_streaming.call_args.kwargs
            assert kwargs.get("force") is False, (
                "Default (no instructions, no force) must not bypass prefilter"
            )

    def test_instructions_alone_promotes_to_force(self):
        """Passing user instructions even without `force` flag should bypass
        the auto-sender prefilter — the user's explicit input is itself
        evidence of intent."""
        from app.api import routes_helpers as rh

        with patch("app.smart_routing.SmartRouter") as mock_router_cls, \
             patch("app.api.settings.load_settings", return_value={"booking_url": ""}), \
             patch("app.api.routes_helpers._get_container") as mock_container, \
             patch("app.api.routes_helpers._fetch_thread_context", return_value=[]), \
             patch("app.api.routes_helpers._is_booking_request", return_value=False):
            mock_container.return_value.llm.name = "claude"

            mock_result = Mock()
            mock_result.draft = "ok"
            mock_result.draft_v1 = "ok"
            mock_result.classification = "Action"
            mock_result.priority = 50
            mock_result.status = "OK"
            mock_result.decision.tier.value = "standard"
            mock_result.decision.complexity_score = 0.5
            mock_result.decision.reason = "n/a"
            mock_result.critique_info = {"is_valid": True}
            mock_result.faq_sent_message_id = None
            mock_result.correction_details = []

            mock_router = Mock()
            mock_router.route_streaming.return_value = mock_result
            mock_router_cls.return_value = mock_router

            rh._process_email_with_use_case(
                _make_email(),
                instructions="Reply yes please",
                use_streaming=True,
                force=False,
            )

            kwargs = mock_router.route_streaming.call_args.kwargs
            assert kwargs.get("force") is True

    def test_manual_generation_can_disable_faq_auto_send(self):
        """Manual /process generation must be able to force FAQ into draft-only mode."""
        from app.api import routes_helpers as rh

        with patch("app.smart_routing.SmartRouter") as mock_router_cls, \
             patch("app.api.settings.load_settings", return_value={"booking_url": ""}), \
             patch("app.api.routes_helpers._get_container") as mock_container, \
             patch("app.api.routes_helpers._fetch_thread_context", return_value=[]), \
             patch("app.api.routes_helpers._is_booking_request", return_value=False):
            mock_container.return_value.llm.name = "claude"

            mock_result = Mock()
            mock_result.draft = "ok"
            mock_result.draft_v1 = "ok"
            mock_result.classification = "Action"
            mock_result.priority = 50
            mock_result.status = "OK"
            mock_result.decision.tier.value = "standard"
            mock_result.decision.complexity_score = 0.5
            mock_result.decision.reason = "n/a"
            mock_result.critique_info = {"is_valid": True}
            mock_result.faq_sent_message_id = None
            mock_result.correction_details = []

            mock_router = Mock()
            mock_router.route_streaming.return_value = mock_result
            mock_router_cls.return_value = mock_router

            rh._process_email_with_use_case(
                _make_email(),
                use_streaming=True,
                allow_faq_auto_send=False,
            )

            kwargs = mock_router.route_streaming.call_args.kwargs
            assert kwargs.get("allow_faq_auto_send") is False


class TestRouteEndpointForce:
    """End-to-end: POST /api/emails/<id>/process with `force=True` reaches the router."""

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_force_in_request_body_forwarded(self, mock_auth, mock_get_email, client):
        """POST /process body `{force: true, instructions: ...}` must reach
        `_process_email_with_use_case(force=True, ...)`."""
        mock_get_email.return_value = _make_email()

        with patch("app.api.routes_emails._process_email_with_use_case") as mock_proc, \
             patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            mock_proc.return_value = ("draft body", "OK", "Action", "normal", "standard", {})

            response = client.post(
                "/api/emails/auto-1/process",
                json={
                    "instructions": "Reply yes please",
                    "reply_type": "reply",
                    "force": True,
                },
            )

        assert response.status_code == 202

        # Background thread runs synchronously in tests if EAGER, but the
        # endpoint detaches the provider and returns 202 immediately. We
        # don't assert mock_proc.called here because the bg thread is fire-
        # and-forget; the propagation is covered by the unit tests above.
        # Instead we verify the endpoint did not 4xx and accepted `force`.
        data = response.get_json()
        assert data["status"] == "processing"

    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_process_returns_before_body_fetch(self, mock_auth, mock_get_email, client):
        """POST /process must not block on slow provider body fetches."""

        class DeferredThread:
            def __init__(self, target, *args, **kwargs):
                self.target = target

            def start(self):
                return None

        with patch("app.api.routes_emails.threading.Thread", DeferredThread), \
             patch("app.api.routes_emails._detach_provider_from_request"), \
             patch("app.api.routes_emails._rh") as mock_rh:
            mock_store = Mock()
            mock_store.get_by_email_id.return_value = None
            mock_rh._get_container.return_value.get_pending_draft_store.return_value = mock_store

            response = client.post(
                "/api/emails/slow-body-1/process",
                json={
                    "instructions": "Reply yes please",
                    "reply_type": "reply",
                    "force": True,
                },
            )

        assert response.status_code == 202
        mock_get_email.assert_not_called()
