# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 — accounts.py handlers missing TARGET-ownership checks.

- POST /api/accounts/<id>/test           authenticated another tenant's stored
  credentials + flipped their status (no ownership check at all).
- POST /api/accounts/<id>/share-signature checked the SOURCE owner but resolved
  the TARGET purely from a client email → arbitrary signature-HTML injection
  into any tenant's outgoing mail.

Fix: both assert check_account_ownership on the target before acting; 404
(anti-enumeration) on mismatch, matching the sibling handlers.

Run: pytest tests/audit_fixes/test_isolation_2026_05_29_account_ownership.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

REMOTE = {"REMOTE_ADDR": "203.0.113.10"}
AUTH = {"Authorization": "Bearer tok"}
JWT = {"sub": "42", "email": "attacker@example.com"}
CALLER_UID = 42
VICTIM_UID = 99


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


# --------------------------------------------------------------------------- #
# POST /accounts/<id>/test
# --------------------------------------------------------------------------- #

def test_account_test_rejects_non_owner(client):
    """Attacker triggers /test on a victim's account → 404, provider NEVER built."""
    victim = SimpleNamespace(id="a1b2c3d4", email="victim@corp.com", user_id=VICTIM_UID)
    manager = MagicMock()
    manager.get_account.return_value = victim
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.accounts._validate_account_id", return_value=True), \
         patch("app.api.accounts._get_auth_user_id", return_value=CALLER_UID), \
         patch("app.api.accounts.get_account_manager", return_value=manager), \
         patch("app.multi_accounts.create_provider_for_account") as build:
        resp = client.post("/api/accounts/a1b2c3d4/test", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 404
    build.assert_not_called()
    manager.update_account_status.assert_not_called()


def test_account_test_allows_owner(client):
    owned = SimpleNamespace(id="a1b2c3d4", email="me@corp.com", user_id=CALLER_UID)
    manager = MagicMock()
    manager.get_account.return_value = owned
    provider = MagicMock()
    provider.authenticate.return_value = True
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.accounts._validate_account_id", return_value=True), \
         patch("app.api.accounts._get_auth_user_id", return_value=CALLER_UID), \
         patch("app.api.accounts.get_account_manager", return_value=manager), \
         patch("app.multi_accounts.create_provider_for_account", return_value=provider):
        resp = client.post("/api/accounts/a1b2c3d4/test", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


# --------------------------------------------------------------------------- #
# POST /accounts/<id>/share-signature
# --------------------------------------------------------------------------- #

def _session_ctx(mock_session):
    cm = MagicMock()
    cm.__enter__.return_value = mock_session
    cm.__exit__.return_value = False
    return cm


def test_share_signature_rejects_non_owned_target(client):
    """Attacker (owns source) targets a victim's email → 404, no signature write."""
    source = SimpleNamespace(id="src00001", email="attacker@corp.com",
                             user_id=CALLER_UID, signature="", signature_html="")
    manager = MagicMock()
    manager.get_account.return_value = source

    source_db = SimpleNamespace(signature_text="<b>Atk</b>", signature_html="<b>Atk</b>")
    target_db = SimpleNamespace(user_id=VICTIM_UID, signature_text="orig", signature_html="orig")
    repo = MagicMock()
    repo.get_by_email.side_effect = lambda e: source_db if e == "attacker@corp.com" else target_db
    session = MagicMock()

    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.accounts._validate_account_id", return_value=True), \
         patch("app.api.accounts._get_auth_user_id", return_value=CALLER_UID), \
         patch("app.api.accounts.get_account_manager", return_value=manager), \
         patch("app.api.accounts.get_db_session", return_value=_session_ctx(session)), \
         patch("app.api.accounts.AccountRepository", return_value=repo):
        resp = client.post(
            "/api/accounts/src00001/share-signature",
            headers=AUTH, environ_base=REMOTE,
            json={"target_email": "victim@corp.com"},
        )
    assert resp.status_code == 404
    # Victim's signature untouched + transaction never committed
    assert target_db.signature_html == "orig"
    assert target_db.signature_text == "orig"
    session.commit.assert_not_called()


def test_share_signature_allows_same_user_target(client):
    """Same user's other account (Gmail+Outlook share user_id) → write allowed."""
    source = SimpleNamespace(id="src00001", email="me-gmail@corp.com",
                             user_id=CALLER_UID, signature="", signature_html="")
    manager = MagicMock()
    manager.get_account.return_value = source
    manager.get_all_accounts.return_value = []

    source_db = SimpleNamespace(signature_text="Sig", signature_html="<i>Sig</i>")
    target_db = SimpleNamespace(user_id=CALLER_UID, signature_text="old", signature_html="old")
    repo = MagicMock()
    repo.get_by_email.side_effect = lambda e: source_db if "gmail" in e else target_db
    session = MagicMock()

    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.accounts._validate_account_id", return_value=True), \
         patch("app.api.accounts._get_auth_user_id", return_value=CALLER_UID), \
         patch("app.api.accounts.get_account_manager", return_value=manager), \
         patch("app.api.accounts.get_db_session", return_value=_session_ctx(session)), \
         patch("app.api.accounts.AccountRepository", return_value=repo):
        resp = client.post(
            "/api/accounts/src00001/share-signature",
            headers=AUTH, environ_base=REMOTE,
            json={"target_email": "me-outlook@corp.com"},
        )
    assert resp.status_code == 200
    assert target_db.signature_html == "<i>Sig</i>"
    session.commit.assert_called_once()
