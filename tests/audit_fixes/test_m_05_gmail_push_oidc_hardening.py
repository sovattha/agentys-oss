# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix M-5 (issue #539) — `/api/gmail/push` OIDC verification + tenant
scoping.

The audit asked two questions:

1. **Crypto verification?** — yes. ``_verify_pubsub_jwt`` already calls
   ``google.oauth2.id_token.verify_oauth2_token`` which performs full RS256
   signature + audience + issuer + exp/iat checks. Existing tests in
   ``tests/test_gmail_push.py`` pin that contract (mocking the helper to
   return claims on success / raise ValueError on bad signature). No code
   change needed here — this regression suite captures the property
   explicitly so a refactor can't drop the call to verify_oauth2_token.

2. **Tenant scoping?** — by Gmail Pub/Sub design the OIDC ``email`` claim
   is the *publisher service account*, not the Gmail user. So we cannot
   "scope from the claim" the way the audit naively suggested. Instead the
   trust chain is: ``audience`` pin → ``SA email`` pin → DB lookup of
   ``payload.emailAddress`` (unknown account → ack-and-ignore, no sync).

   The hardening shipped: **``GMAIL_PUSH_SERVICE_ACCOUNT`` is now mandatory
   in production**. Without it, any Google-project SA token signed for our
   audience would pass.

Run: ``pytest tests/audit_fixes/test_m_05_gmail_push_oidc_hardening.py -v``
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.api import gmail_push as gp


@pytest.fixture(autouse=True)
def _restore_env():
    saved = {
        k: os.environ.get(k)
        for k in (
            gp.PUSH_AUDIENCE_ENV,
            gp.PUSH_SERVICE_ACCOUNT_ENV,
            "FLASK_ENV",
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_ENVIRONMENT_NAME",
        )
    }
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# --------------------------------------------------------------------------- #
# 1. Crypto verification IS the implementation — not just a presence check
# --------------------------------------------------------------------------- #


def test_uses_google_auth_verify_oauth2_token():
    """The implementation MUST call ``id_token.verify_oauth2_token`` —
    a refactor that drops it (e.g. naive jwt.decode without keyset
    fetching) would silently break crypto verification."""
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    os.environ.pop(gp.PUSH_SERVICE_ACCOUNT_ENV, None)
    fake_claims = {"email": "sa@example.iam.gserviceaccount.com", "iss": "google"}

    with patch(
        "google.oauth2.id_token.verify_oauth2_token", return_value=fake_claims
    ) as mock_verify:
        result = gp._verify_pubsub_jwt("Bearer abc.def.ghi")

    assert result == fake_claims
    mock_verify.assert_called_once()
    # Audience must be passed to the verifier — that's what binds the token
    # to our endpoint specifically, not just "any Google-signed token".
    _args, kwargs = mock_verify.call_args
    assert kwargs.get("audience") == "https://example.com/api/gmail/push"


def test_signature_verification_failure_returns_none():
    """``verify_oauth2_token`` raises ValueError on a bad signature — the
    helper must propagate that to a None result, not bubble or accept."""
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    with patch(
        "google.oauth2.id_token.verify_oauth2_token",
        side_effect=ValueError("Invalid signature"),
    ):
        assert gp._verify_pubsub_jwt("Bearer tampered.token.here") is None


# --------------------------------------------------------------------------- #
# 2. M-5 hardening: SA pin is MANDATORY in production
# --------------------------------------------------------------------------- #


def test_prod_without_sa_env_refuses_push(caplog):
    """Production + missing GMAIL_PUSH_SERVICE_ACCOUNT must refuse — the
    SA pin is what stops "any Google project's SA token" from passing."""
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    os.environ.pop(gp.PUSH_SERVICE_ACCOUNT_ENV, None)
    os.environ["FLASK_ENV"] = "production"

    with patch("google.oauth2.id_token.verify_oauth2_token") as mock_verify:
        result = gp._verify_pubsub_jwt("Bearer would.be.valid")

    assert result is None
    # Crucially: we MUST refuse before even calling the verifier — otherwise
    # a missing SA pin is just a warning, not a hard stop.
    mock_verify.assert_not_called()


def test_prod_with_sa_env_passes_through_to_verifier():
    """Production + SA env set → normal verification path runs."""
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    os.environ[gp.PUSH_SERVICE_ACCOUNT_ENV] = "agentys-pubsub@example.iam.gserviceaccount.com"
    os.environ["FLASK_ENV"] = "production"

    fake_claims = {
        "email": "agentys-pubsub@example.iam.gserviceaccount.com",
        "iss": "google",
    }
    with patch(
        "google.oauth2.id_token.verify_oauth2_token", return_value=fake_claims
    ):
        result = gp._verify_pubsub_jwt("Bearer abc.def.ghi")

    assert result == fake_claims


def test_dev_without_sa_env_still_works():
    """Dev/test mode: skip the mandatory SA check so fixtures don't have
    to set it. The audience pin remains required even in dev."""
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    os.environ.pop(gp.PUSH_SERVICE_ACCOUNT_ENV, None)
    os.environ.pop("FLASK_ENV", None)
    os.environ.pop("RAILWAY_ENVIRONMENT", None)
    os.environ.pop("RAILWAY_ENVIRONMENT_NAME", None)

    fake_claims = {"email": "sa@example.iam.gserviceaccount.com", "iss": "google"}
    with patch(
        "google.oauth2.id_token.verify_oauth2_token", return_value=fake_claims
    ):
        result = gp._verify_pubsub_jwt("Bearer abc.def.ghi")

    assert result == fake_claims


def test_railway_production_env_also_triggers_sa_requirement():
    """`is_production()` reads RAILWAY_ENVIRONMENT too — make sure the
    SA mandate kicks in via Railway-set vars, not only FLASK_ENV."""
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    os.environ.pop(gp.PUSH_SERVICE_ACCOUNT_ENV, None)
    os.environ.pop("FLASK_ENV", None)
    os.environ["RAILWAY_ENVIRONMENT"] = "production"

    with patch("google.oauth2.id_token.verify_oauth2_token") as mock_verify:
        result = gp._verify_pubsub_jwt("Bearer abc.def.ghi")

    assert result is None
    mock_verify.assert_not_called()


def test_wrong_sa_email_rejected_even_with_valid_signature():
    """Belt-and-suspenders — already covered by the existing suite, but
    pin it here so the SA check stays right next to the SA-pin mandate."""
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    os.environ[gp.PUSH_SERVICE_ACCOUNT_ENV] = "expected@example.iam.gserviceaccount.com"

    fake_claims = {"email": "intruder@evil.com", "iss": "google"}
    with patch(
        "google.oauth2.id_token.verify_oauth2_token", return_value=fake_claims
    ):
        result = gp._verify_pubsub_jwt("Bearer abc.def.ghi")

    assert result is None


# --------------------------------------------------------------------------- #
# 3. Tenant scoping defence-in-depth — unknown emailAddress acks without sync
# --------------------------------------------------------------------------- #


def test_trigger_sync_for_unknown_email_does_not_run():
    """Even a JWT-validated push for an emailAddress we don't know must
    NOT trigger a sync (no row → ignored). This is the third line of
    defence in the M-5 trust chain (after audience + SA pins)."""
    from unittest.mock import MagicMock

    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.first.return_value = None

    with patch("app.api.gmail_push.get_session", return_value=fake_session):
        result = gp._trigger_history_sync("attacker@victim-domain.com", "999")

    assert result == {"status": "ignored", "reason": "unknown_account"}
    fake_session.commit.assert_not_called()


# --------------------------------------------------------------------------- #
# 4. The other gates stay intact (regression-lock)
# --------------------------------------------------------------------------- #


def test_missing_audience_env_still_refuses():
    """Audience env required — without it ANY Google-signed token would
    pass. Existing test in tests/test_gmail_push.py covers this; we
    re-pin it here so the M-5 file is self-contained."""
    os.environ.pop(gp.PUSH_AUDIENCE_ENV, None)
    assert gp._verify_pubsub_jwt("Bearer token") is None


def test_missing_bearer_header_returns_none():
    """No Bearer prefix → no verification attempted."""
    os.environ[gp.PUSH_AUDIENCE_ENV] = "https://example.com/api/gmail/push"
    assert gp._verify_pubsub_jwt(None) is None
    assert gp._verify_pubsub_jwt("Basic xxxxx") is None
    assert gp._verify_pubsub_jwt("") is None
