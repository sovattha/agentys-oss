# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix Cluster A (2026-05-10) — send / draft / compose contracts.

Source: tasks/audit-reports/2026-05-10_2219/

Three silent / leaky failures on the critical user flows:

  * B-01 — POST /api/emails/<id>/draft returns 201 with success=false when
    the underlying provider.create_draft returns None. The frontend trusts
    2xx and shows a confirmation toast for a draft that does not exist.
    Fix: when draft_id is None AND no send happened, return 502.

  * U-01 — POST /api/emails/send-new
        (a) does NOT validate the single-token `to` against the RFC-5322
            regex (only multi-recipient CC/BCC lists are filtered). A
            payload like {"to":"not-an-email"} reaches Gmail and the
            provider raises HttpError; the route then echoes provider
            ._last_error which contains the raw `<HttpError 400 …>` repr
            including the full Google endpoint URL — leaks API surface and
            renders an unreadable toast.
        Fix: validate `to` against _email_re BEFORE provider call; sanitize
            _last_error to strip raw `<HttpError …>` repr (replace with a
            friendly message + keep the underlying reason if extractable).

  * B-07 — POST /api/emails/compose with compose_id starts
    `_compose_stream_bg` in a background thread even when
    `_resolve_account_id_for_user()` raises (account_id=None). All WS
    emits then route to no room → every chunk is silently dropped and
    the spinner spins forever. The emit_draft_error fallback is itself
    wrapped in `except Exception: pass`.
    Fix: if account resolution fails, return 503 BEFORE starting the
    thread; replace the bare `except: pass` with a logged error.

Run: pytest tests/audit_fixes/test_cluster_a_send_draft_contracts.py -v
"""

from __future__ import annotations

import inspect
import re
from unittest.mock import MagicMock, patch

import pytest


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #




def _auth_headers(email: str = "test@agentys.app", sub: str = "12345") -> dict:
    """Mint a JWT Bearer header.

    /api/refine-text and /api/emails/compose are @require_auth gated
    (audit-2026-05-11). Tests hitting these endpoints must include a token.
    """
    import time as _time
    import jwt as _pyjwt
    from app.api.auth import JWT_ALGORITHM, JWT_SECRET
    token = _pyjwt.encode(
        {
            "sub": sub,
            "email": email,
            "iat": int(_time.time()),
            "exp": int(_time.time()) + 3600,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def app():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# --------------------------------------------------------------------------- #
# B-01 — create_draft_from_content must surface provider failure as 5xx
# --------------------------------------------------------------------------- #


class TestB01DraftCreationFailureSurfacing:
    """When provider.create_draft returns None, the endpoint must NOT claim 201 success."""

    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_returns_502_when_provider_returns_none(
        self,
        mock_get_provider,
        mock_get_email,
        mock_sig,
        mock_r1,
        mock_r2,
        client,
    ):
        mock_email = MagicMock()
        mock_email.id = "test-email-id"
        mock_email.sender = "sender@test.com"
        mock_get_email.return_value = mock_email

        # Provider create_draft fails silently (returns None, no exception).
        mock_provider = MagicMock()
        mock_provider.create_draft.return_value = None
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider

        resp = client.post(
            "/api/emails/test-email-id/draft",
            json={"subject": "Re: hello", "body": "body content"},
        )
        data = resp.get_json() or {}

        # Before fix: 201 with success=false. After fix: 5xx with explicit error.
        assert resp.status_code >= 500, (
            f"Expected 5xx when draft creation fails silently, got {resp.status_code} "
            f"with body {data}"
        )
        assert data.get("success") is not True
        assert "error" in data

    @patch("app.api.routes_emails._resolve_account_id_cached", return_value=1)
    @patch("app.api.routes_helpers._resolve_account_id_cached", return_value=1)
    @patch("app.utils.signature.append_signature", side_effect=lambda body, **kw: body)
    @patch("app.api.routes_emails._get_email_by_id")
    @patch("app.api.routes_emails._get_authenticated_provider")
    def test_success_path_still_returns_201(
        self,
        mock_get_provider,
        mock_get_email,
        mock_sig,
        mock_r1,
        mock_r2,
        client,
    ):
        """Regression guard: the fix must not break the happy path."""
        mock_email = MagicMock()
        mock_email.id = "ok-email"
        mock_email.sender = "ok@test.com"
        mock_get_email.return_value = mock_email

        mock_provider = MagicMock()
        mock_provider.create_draft.return_value = "fresh-draft-id"
        mock_provider.PROVIDER_NAME = "gmail"
        mock_get_provider.return_value = mock_provider

        resp = client.post(
            "/api/emails/ok-email/draft",
            json={"subject": "Re: ok", "body": "body"},
        )
        data = resp.get_json() or {}
        assert resp.status_code == 201
        assert data.get("success") is True
        assert data.get("draft_id") == "fresh-draft-id"


# --------------------------------------------------------------------------- #
# U-01 — send-new must validate `to` and sanitize provider error repr
# --------------------------------------------------------------------------- #


class TestU01SendNewRecipientValidation:
    """A single-token bad `to` (no comma) must be rejected with 400 before provider."""

    def test_rejects_single_token_bad_recipient_with_400(self, client):
        # No provider mocked — the route must reject BEFORE
        # _get_authenticated_provider is called.
        resp = client.post(
            "/api/emails/send-new",
            json={"to": "not-an-email", "subject": "audit", "body": "hi"},
        )
        data = resp.get_json() or {}
        assert resp.status_code == 400, (
            f"Expected 400 on malformed single-token `to`, got {resp.status_code} "
            f"with body {data}"
        )
        # Friendly user-facing error.
        assert "error" in data
        err = (data.get("error") or "").lower()
        assert "email" in err or "recipient" in err or "invalid" in err

    def test_rejects_single_token_bad_recipient_with_whitespace(self, client):
        resp = client.post(
            "/api/emails/send-new",
            json={"to": "   not-an-email   ", "subject": "audit", "body": "hi"},
        )
        assert resp.status_code == 400

    def test_accepts_valid_single_recipient(self, client):
        """Regression guard: a legit single recipient must still pass validation
        (the call may fail downstream for other reasons; we only assert the
        validation gate doesn't 400 the request)."""
        with patch(
            "app.api.routes_emails._get_authenticated_provider"
        ) as mock_prov:
            mock_provider = MagicMock()
            mock_provider.send_new_directly.return_value = "msg-id"
            mock_prov.return_value = mock_provider
            resp = client.post(
                "/api/emails/send-new",
                json={
                    "to": "alice@example.com",
                    "subject": "ok",
                    "body": "hello",
                },
            )
            # Either 200 (full happy path mocked) or any non-validation status.
            assert resp.status_code != 400, (
                "Valid single recipient must not trigger validation 400. "
                f"Got {resp.status_code} body={resp.get_json()}"
            )

    def test_accepts_valid_multi_recipient(self, client):
        with patch(
            "app.api.routes_emails._get_authenticated_provider"
        ) as mock_prov:
            mock_provider = MagicMock()
            mock_provider.send_new_directly.return_value = "msg-id"
            mock_prov.return_value = mock_provider
            resp = client.post(
                "/api/emails/send-new",
                json={
                    "to": "alice@example.com, bob@example.com",
                    "subject": "ok",
                    "body": "hello",
                },
            )
            assert resp.status_code != 400, (
                f"Valid multi recipient must not 400. Got {resp.status_code} "
                f"body={resp.get_json()}"
            )

    def test_accepts_recipient_arrays_from_clients(self, client):
        with (
            patch("app.api.routes_emails._rate_limited", return_value=(True, 0)),
            patch("app.api.routes_emails._get_authenticated_provider") as mock_prov,
        ):
            mock_provider = MagicMock()
            mock_provider.send_new_directly.return_value = "msg-id"
            mock_prov.return_value = mock_provider
            resp = client.post(
                "/api/emails/send-new",
                json={
                    "to": ["alice@example.com", " bob@example.com "],
                    "cc": ["copy@example.com"],
                    "bcc": [],
                    "subject": "ok",
                    "body": "hello",
                },
            )

        assert resp.status_code == 200, resp.get_json()
        kwargs = mock_provider.send_new_directly.call_args.kwargs
        assert kwargs["to"] == ["alice@example.com", "bob@example.com"]
        assert kwargs["cc"] == ["copy@example.com"]
        assert kwargs["bcc"] is None

    def test_rejects_multi_recipient_when_one_is_bad(self, client):
        """Even if validation already covered multi via _validate_email_list,
        lock the contract: any invalid token in `to` → 400."""
        resp = client.post(
            "/api/emails/send-new",
            json={
                "to": "alice@example.com, broken",
                "subject": "audit",
                "body": "hi",
            },
        )
        assert resp.status_code == 400


class TestU01SendNewProviderErrorSanitization:
    """When provider._last_error contains the raw Python repr of HttpError,
    the route MUST NOT leak it verbatim to the client.

    The audit captured:
        {"error":"<HttpError 400 when requesting https://gmail.googleapis.com/…>"}
    This leaks the API endpoint URL and the SDK version string. After the
    fix, the response must:
      * not contain the literal `<HttpError`
      * not contain `gmail.googleapis.com` (the leaked endpoint)
      * still surface a useful reason if extractable (e.g. "Invalid To header")
    """

    def test_strips_httperror_repr_from_response(self, client):
        fake_provider = MagicMock()
        fake_provider.send_new_directly.return_value = None
        fake_provider._last_error = (
            "<HttpError 400 when requesting "
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send?alt=json "
            'returned "Invalid To header". '
            "Details: \"[{'message': 'Invalid To header', 'domain': 'global', "
            "'reason': 'invalidArgument'}]\">"
        )

        with patch(
            "app.api.routes_emails._get_authenticated_provider",
            return_value=fake_provider,
        ):
            resp = client.post(
                "/api/emails/send-new",
                json={
                    "to": "ok-format@example.com",
                    "subject": "audit",
                    "body": "hi",
                },
            )
        data = resp.get_json() or {}
        err = data.get("error", "")
        assert "<HttpError" not in err, (
            f"Raw HttpError repr leaked to client: {err!r}"
        )
        assert "gmail.googleapis.com" not in err, (
            f"Google API endpoint leaked to client: {err!r}"
        )
        # The useful reason should still be communicated.
        assert err, "Sanitized error must not be empty"


# --------------------------------------------------------------------------- #
# B-07 — compose streaming must refuse when account resolution fails
# --------------------------------------------------------------------------- #


class TestB07ComposeStreamAccountResolutionFailure:
    """If _resolve_account_id_for_user() raises (transient DB error), the
    route must NOT spawn a streaming thread with account_id=None — all WS
    emits would be silently dropped. Return 503 immediately so the UI can
    surface a real error instead of an infinite spinner."""

    def test_returns_503_when_account_resolution_raises(self, client):
        with patch(
            "app.api.routes_helpers._resolve_account_id_for_user",
            side_effect=RuntimeError("simulated DB transient failure"),
        ), patch(
            "app.api.routes_misc._get_current_account_for_user",
            return_value=MagicMock(name="acct", email="me@test.com"),
        ), patch(
            "threading.Thread"
        ) as mock_thread:
            resp = client.post(
                "/api/emails/compose",
                json={
                    "to": "alice@example.com",
                    "subject": "audit",
                    "instructions": "say hi",
                    "compose_id": "audit-stream-1",
                },
                headers=_auth_headers(),
            )
            # Must NOT spawn the bg thread when account is unresolvable.
            assert not mock_thread.called, (
                "Background streaming thread must NOT be started when "
                "account_id resolution fails — chunks would be silently dropped."
            )

        # Must surface a 5xx so the frontend can stop spinning.
        assert resp.status_code >= 500, (
            f"Expected 5xx when account resolution fails, got {resp.status_code} "
            f"body={resp.get_json()}"
        )

    def test_streaming_compose_returns_202_fast_even_when_style_profile_load_stalls(self, client):
        """Audit 2026-05-19: regression for the 30s `withTimeout` toast.

        Pre-fix the route ran `get_writing_style_profile()` (disk I/O) +
        prompt assembly synchronously on the Flask worker BEFORE returning
        202. A slow disk read could push the HTTP response past the
        frontend's 30s `withTimeout` wrapper. Post-fix the streaming
        branch returns 202 in <1s regardless — the disk I/O runs inside
        the BG thread via `_compose_stream_setup_and_bg`.
        """
        import time as _time

        def _slow_profile(*args, **kwargs):
            _time.sleep(5)  # simulate a stalled disk read
            return None

        # `get_writing_style_profile` lives on the container singleton.
        # Patch via the container reference rather than the bound method.
        from app.infrastructure.container import get_container
        container = get_container()
        with patch.object(
            container, "get_writing_style_profile", side_effect=_slow_profile
        ), patch(
            "app.api.routes_helpers._resolve_account_id_for_user", return_value=1,
        ), patch(
            "app.api.routes_misc._get_current_account_for_user",
            return_value=MagicMock(name="acct", email="me@test.com"),
        ), patch(
            "threading.Thread"  # don't actually run the BG work in the test
        ):
            t0 = _time.monotonic()
            resp = client.post(
                "/api/emails/compose",
                json={
                    "to": "alice@example.com",
                    "subject": "perf",
                    "instructions": "say hi",
                    "compose_id": "audit-perf-1",
                },
                headers=_auth_headers(),
            )
            elapsed = _time.monotonic() - t0

        assert resp.status_code == 202, (
            f"Streaming compose should return 202, got {resp.status_code} "
            f"body={resp.get_json()}"
        )
        assert elapsed < 1.0, (
            f"Streaming compose returned 202 in {elapsed:.2f}s — disk I/O "
            f"is still running on the request thread. The 5s sleep on "
            f"`get_writing_style_profile` should be off the request path."
        )

    def test_compose_stream_bg_does_not_swallow_emit_error_silently(self):
        """Source-level lock: `_compose_stream_bg` must not contain the
        anti-pattern `except Exception: pass` around emit_draft_error.

        Rationale: if the WebSocket emit itself fails, swallowing the
        exception silently makes the bug invisible. We at least want a
        logger.error so ops can detect WS infra problems."""
        from app.api import routes_misc

        src = inspect.getsource(routes_misc._compose_stream_bg)

        # The literal `except Exception:\n        pass` (no logging) must be gone.
        offending = re.search(
            r"except\s+Exception\s*:\s*\n\s*pass\b",
            src,
        )
        assert offending is None, (
            "`except Exception: pass` still present in _compose_stream_bg — "
            "emit_draft_error failures will be silently swallowed."
        )
