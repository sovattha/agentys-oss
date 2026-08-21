# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix H-1/H-2 (2026-04-25 isolation report) — `routes_contacts.py`
read `?account_id=` directly from the request and forwarded it to the
service, so any authenticated caller could enumerate other tenants'
contacts and relationship overrides by changing the query param.

This test locks in:
  - When the JWT-resolved caller has account_id A and the request asks
    for account_id B, the helper returns a 403.
  - When ids match, the helper returns None (allow path).
  - When no caller is resolved (Tauri loopback, caller_aid==0), the
    helper allows whatever the client passed — that's the single-user
    desktop install, no impersonation surface.

Run: `pytest tests/audit_fixes/test_h01_h02_contacts_cross_account.py -v`
"""

from __future__ import annotations

from unittest.mock import patch


def test_block_cross_account_returns_403_when_caller_mismatches():
    from app.api import routes_contacts

    with patch.object(routes_contacts, "_resolve_account_id_for_user", return_value=1):
        from flask import Flask
        with Flask(__name__).test_request_context("/"):
            response = routes_contacts._block_cross_account_access(2)

    assert response is not None, "must reject mismatch"
    body, status = response
    assert status == 403
    assert "Forbidden" in body.get_json()["error"]


def test_block_cross_account_allows_matching_ids():
    from app.api import routes_contacts

    with patch.object(routes_contacts, "_resolve_account_id_for_user", return_value=1):
        from flask import Flask
        with Flask(__name__).test_request_context("/"):
            response = routes_contacts._block_cross_account_access(1)

    assert response is None, "matching ids must pass through"


def test_block_cross_account_allows_loopback_caller():
    """No JWT + loopback REMOTE_ADDR → trust the explicit account_id param.

    Tauri desktop path: the local app has no JWT, so
    `_resolve_account_id_for_user` returns 0/-1 and we have no
    impersonation surface to defend against on 127.0.0.1.

    Audit F-02 (2026-05-16) tightened the guard: when caller_aid<=0
    we now require the request to originate from a loopback peer
    before allowing through (the pre-fix code allowed ANY caller with
    caller_aid<=0, which was the pre-OAuth-JWT-on-cloud bypass vector).
    Tests must therefore set REMOTE_ADDR explicitly to express intent.
    """
    from app.api import routes_contacts

    with patch.object(routes_contacts, "_resolve_account_id_for_user", return_value=0):
        from flask import Flask
        with Flask(__name__).test_request_context(
            "/", environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        ):
            response = routes_contacts._block_cross_account_access(42)

    assert response is None, "loopback (no JWT) must allow explicit param"


def test_block_cross_account_allows_when_resolver_raises():
    """Resolver exceptions on a loopback peer are treated as no-caller (Tauri)."""
    from app.api import routes_contacts

    with patch.object(
        routes_contacts,
        "_resolve_account_id_for_user",
        side_effect=RuntimeError("no JWT"),
    ):
        from flask import Flask
        with Flask(__name__).test_request_context(
            "/", environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        ):
            response = routes_contacts._block_cross_account_access(99)

    assert response is None, "exceptions on loopback must default to allow"


def test_block_cross_account_rejects_no_jwt_from_non_loopback():
    """F-02 (2026-05-16) regression: pre-OAuth JWT user on cloud (caller_aid==-1)
    coming from a non-loopback peer MUST be rejected. Pre-fix this code path
    fell through `if caller_aid > 0` and let the request enumerate any
    tenant's contact data on the 5 endpoints that call this helper.
    """
    from app.api import routes_contacts
    from app.api.routes_helpers import _NO_ACCOUNT_SENTINEL

    with patch.object(
        routes_contacts,
        "_resolve_account_id_for_user",
        return_value=_NO_ACCOUNT_SENTINEL,
    ):
        from flask import Flask
        with Flask(__name__).test_request_context(
            "/", environ_overrides={"REMOTE_ADDR": "203.0.113.42"},
        ):
            response = routes_contacts._block_cross_account_access(7)

    assert response is not None, "pre-OAuth JWT from non-loopback must be rejected"
    body, status = response
    assert status == 403
    assert "Forbidden" in body.get_json()["error"]
