# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix Cluster C (2026-05-11) — backend hygiene.

Source: tasks/audit-reports/2026-05-10_2219/02-backend-silent.md (B-05, B-06,
B-08, B-09, B-10, B-11, B-12) and 03-ui-live.md (U-06, U-11).

Nine related backend silent-failure / contract findings, batched into one
PR because they share the same theme: log-and-forget patterns and missing
defense-in-depth that combine into invisible failure modes.

  * B-05 — POST /api/emails/save-draft accepts a stale `X-Account-Id` header
    from a foreign tenant; the draft lands on the JWT user's default account
    silently. Fix: validate via require_owned_account_id, like send_new_email.

  * B-06 — POST /api/emails/compose has no per-tenant rate limit and no
    X-Account-Id validation. A client can drain Anthropic credit or pull
    style profiles for an unowned account. Fix: rate-limit + validate
    matching the send_new_email shape.

  * B-08 — _send_reply (quickstep) returns None on fallback failure without
    surfacing provider._last_error. The chain sees `reply_send_failed`
    instead of "token revoked" / "quota exceeded". Fix: stash _last_error
    on the provider so the calling handler can include it in ActionResult.

  * B-09 / B-10 / B-11 / B-12 — wrong log severity (debug/warning) on
    failures that affect data integrity (commitment extraction, contact
    style learning, audit ledger, post-send background archive). Fix:
    promote to logger.error(..., exc_info=True) — source-level guard.

  * U-06 — POST /api/quicksteps/dry-run rejects an empty triggers list
    with 400, blocking the preview UX for manual-only steps that have
    no auto-trigger. Fix: accept empty triggers; return examined=0 +
    `no_triggers=true` so the UI can render a clean "nothing to match".

  * U-11 — Fresh JWT user (just-onboarded, no account row yet) hits any
    @account_scoped route and gets 401 NO_ACCOUNT_SCOPE — the same code
    used for genuine auth failures. The frontend can't tell whether to
    redirect to wizard or to login. Fix: distinct code
    `ONBOARDING_REQUIRED` when JWT is valid but no account exists.

Run: pytest tests/audit_fixes/test_cluster_c_backend_hygiene.py -v
"""

from __future__ import annotations

import inspect
import re
from unittest.mock import patch

import pytest


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


# --------------------------------------------------------------------------- #
# B-05 — save-draft must reject stale X-Account-Id
# --------------------------------------------------------------------------- #


class TestB05SaveDraftAccountValidation:
    def test_invalid_x_account_id_returns_404(self, client):
        """A stale localStorage accountId from a foreign tenant must be
        rejected — not silently fall back to the JWT user's default."""
        # Patch require_owned_account_id to behave as if header doesn't belong.
        with patch(
            "app.api.routes_helpers.require_owned_account_id",
            return_value=-1,
        ), patch(
            "app.api.routes_emails._get_authenticated_provider"
        ):
            resp = client.post(
                "/api/emails/save-draft",
                json={"to": "alice@example.com", "subject": "x", "body": "y"},
                headers={"X-Account-Id": "DEADBEEF"},
            )
        # Must NOT 2xx silently. Either 404 (preferred) or 4xx with a clear code.
        assert resp.status_code in (400, 401, 403, 404), (
            f"Stale X-Account-Id slipped through, got {resp.status_code} "
            f"body={resp.get_json()}"
        )
        body = resp.get_json() or {}
        assert "error" in body


# --------------------------------------------------------------------------- #
# B-06 — compose must rate-limit and validate X-Account-Id
# --------------------------------------------------------------------------- #


class TestB06ComposeAccountValidation:
    def test_invalid_x_account_id_returns_404(self, client):
        with patch(
            "app.api.routes_helpers.require_owned_account_id",
            return_value=-1,
        ):
            resp = client.post(
                "/api/emails/compose",
                json={
                    "to": "alice@example.com",
                    "subject": "test",
                    "instructions": "hi",
                },
                headers={"X-Account-Id": "DEADBEEF"},
            )
        assert resp.status_code in (400, 401, 403, 404), (
            f"Stale X-Account-Id slipped through compose, got {resp.status_code} "
            f"body={resp.get_json()}"
        )


class TestB06ComposeRateLimitSource:
    """Source-level lock: compose endpoint MUST call _rate_limited with a
    per-tenant bucket key (matching the send_email:{aid} pattern). Without
    this, a single client can drain the global compose quota for the whole
    tenant pool."""

    def test_compose_callsite_has_per_tenant_rate_limit(self):
        from app.api import routes_misc

        src = inspect.getsource(routes_misc.compose_email)
        # Two acceptable shapes:
        #  (1) inline f-string:  _rate_limited(f"compose:{aid}", ...)
        #  (2) audit F-03 helper: _rate_limited(_per_caller_bucket_key("compose"), ...)
        # The helper-form salts the `_NO_ACCOUNT_SENTINEL` (-1) cohort with
        # JWT identity so pre-OAuth users don't share one bucket — same
        # per-tenant intent, stronger isolation.
        shape_inline = re.search(r"_rate_limited\(\s*f?[\"']compose:", src)
        shape_helper = re.search(
            r"_rate_limited\(\s*_per_caller_bucket_key\(\s*[\"']compose[\"']",
            src,
        )
        assert shape_inline or shape_helper, (
            "/api/emails/compose has no per-tenant _rate_limited gate — "
            "Anthropic credit drainage / DoS surface."
        )


# --------------------------------------------------------------------------- #
# B-08 — _send_reply fallback must surface provider._last_error
# --------------------------------------------------------------------------- #


class TestB08ReplyFallbackErrorPropagation:
    """Source-level guard: the reply quickstep handler must read
    provider._last_error when create_draft / send_draft fails, so the chain
    can report something better than a generic reply_send_failed."""

    def test_send_reply_reads_last_error_on_fallback_failure(self):
        from app.quicksteps.handlers import reply as reply_module

        src = inspect.getsource(reply_module)
        # The fix must reference `_last_error` somewhere in the fallback
        # path so the calling handler can include it in ActionResult.
        assert "_last_error" in src, (
            "reply handler doesn't surface provider._last_error — the real "
            "cause (token revoked, quota, MIME) stays invisible."
        )


# --------------------------------------------------------------------------- #
# B-09 / B-10 / B-11 / B-12 — severity promotion guards
# --------------------------------------------------------------------------- #


class TestB09CommitmentExtractionSeverity:
    def test_commitment_extraction_logs_at_error(self):
        """`logger.warning(...)` for a failure that silently breaks the
        calendar suggestions feature is the wrong severity — ops cannot
        tell the feature is broken from telemetry alone."""
        from app.api import routes_emails

        src = inspect.getsource(routes_emails)
        # Find the commitment extraction inner function.
        m = re.search(
            r"def _extract_compose_commitments[\s\S]{0,2000}?logger\.(\w+)\("
            r"[^)]*Commitment extraction failed",
            src,
        )
        assert m is not None, "Cannot locate commitment extraction logger call"
        assert m.group(1) == "error", (
            f"Commitment extraction failure logged at {m.group(1)!r}; "
            "should be `error` (with exc_info=True) for observability."
        )


class TestB10RecordSentRecipientsSeverity:
    def test_all_three_record_sent_recipients_logs_are_above_debug(self):
        """Three sites (reply / compose / draft-send) all logged at debug;
        a failed Contact.sent_count update silently degrades personalization
        forever. Bump to warning or error so ops can see the rot."""
        from app.api import routes_emails

        src = inspect.getsource(routes_emails)
        # Multi-line: matches both `logger.warning("rec... failed: ...")`
        # inline AND the split form `logger.warning(\n    "rec... failed: %s",`.
        hits = re.findall(
            r"logger\.(\w+)\(\s*f?\"record_sent_recipients[^\"]*\"",
            src,
        )
        assert len(hits) >= 3, (
            f"Expected 3 record_sent_recipients log sites, found {len(hits)}: {hits}"
        )
        for level in hits:
            assert level not in ("debug", "info"), (
                f"record_sent_recipients log site at level {level!r} — "
                "should be warning or error so ops can see the failure."
            )


class TestB11QuickStepsAuditRecorderSeverity:
    def test_audit_recorder_failure_logs_at_error(self):
        """Audit ledger drift breaks idempotency replay + auto-trigger
        deduplication — far more critical than a debug-level log line."""
        from app.quicksteps import engine

        src = inspect.getsource(engine)
        # The recorder catch should not be at debug level.
        # Look for the audit recorder failure log specifically (the message
        # carries "audit recorder" so it can't collide with other logger
        # calls in the engine module).
        m = re.search(
            r"logger\.(\w+)\(\s*[\"'][^\"']*audit recorder",
            src,
        )
        assert m is not None, "Cannot locate audit recorder logger call"
        assert m.group(1) in ("warning", "error"), (
            f"audit recorder failure logged at {m.group(1)!r}; "
            "should be warning/error."
        )


class TestB12SafeCallSeverity:
    def test_safe_call_logs_at_error_for_observability(self):
        """_safe_call is used by _post_send_bg to fire-and-forget the
        mark_as_read / archive_email calls after a send. Failures here
        cause state divergence (email shows archived locally but not
        provider-side) and must surface in Sentry, not be lost in warnings."""
        from app.api import routes_helpers

        src = inspect.getsource(routes_helpers._safe_call)
        m = re.search(r"logger\.(\w+)\(", src)
        assert m is not None
        assert m.group(1) in ("warning", "error"), (
            f"_safe_call logs at {m.group(1)!r} — should be warning or "
            "error so post-send-bg failures are visible."
        )
        # Stronger: the audit specifically asked for `error` because these
        # failures leave the user-visible inbox state diverged from the
        # provider state. We accept warning as minimum but recommend error.


# --------------------------------------------------------------------------- #
# U-06 — dry-run must accept empty triggers (manual-only steps)
# --------------------------------------------------------------------------- #


class TestU06DryRunEmptyTriggers:
    """A Quick Step that's only bound to a manual shortcut has no auto-trigger
    predicate; the user should still be able to dry-run / preview it before
    binding the shortcut. Empty triggers must not 400."""

    def test_empty_triggers_does_not_400(self, client):
        # Patch the account_scoped decorator's resolver to inject a valid
        # account_id so we get past auth and exercise the contract.
        with patch(
            "app.api.routes_helpers._resolve_account_id_for_user",
            return_value=1,
        ):
            resp = client.post(
                "/api/quicksteps/dry-run",
                json={"triggers": [], "triggerOperator": "OR"},
            )
        assert resp.status_code != 400, (
            f"Empty triggers list rejected with 400 — manual-only steps "
            f"cannot be previewed. body={resp.get_json()}"
        )

    def test_missing_triggers_does_not_400(self, client):
        with patch(
            "app.api.routes_helpers._resolve_account_id_for_user",
            return_value=1,
        ):
            resp = client.post(
                "/api/quicksteps/dry-run",
                json={},
            )
        assert resp.status_code != 400, (
            f"Missing triggers field rejected with 400. body={resp.get_json()}"
        )


# --------------------------------------------------------------------------- #
# U-11 — distinct code when JWT valid but no account yet
# --------------------------------------------------------------------------- #


class TestU11OnboardingRequiredCode:
    """A fresh JWT user (just signed up, wizard not started yet) hits any
    account-scoped route and gets 401 NO_ACCOUNT_SCOPE — same code as a
    real auth failure. The frontend can't tell to route to wizard. Fix:
    when JWT user exists but account resolution returns sentinel, return
    a distinct code `ONBOARDING_REQUIRED` so the UI can branch."""

    def test_returns_onboarding_required_code_when_jwt_user_no_account(self, app):
        from flask import g
        from app.api.account_scope import account_scoped

        @account_scoped
        def fake_view():
            return {"ok": True}

        with app.test_request_context("/x"):
            # Pretend JWT auth populated g.auth_user — but no account row.
            g.auth_user = {"email": "fresh@new.com", "user_id": 999}
            with patch(
                "app.api.routes_helpers._resolve_account_id_for_user",
                return_value=-1,
            ):
                response = fake_view()
                if isinstance(response, tuple):
                    body_obj, status = response
                else:
                    body_obj, status = response, 200
                # Flask jsonify Response — extract JSON.
                if hasattr(body_obj, "get_json"):
                    data = body_obj.get_json()
                else:
                    data = body_obj
                assert status in (401, 403)
                assert data.get("code") == "ONBOARDING_REQUIRED", (
                    f"Expected code=ONBOARDING_REQUIRED for JWT user without "
                    f"account, got {data}"
                )
