# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix C-3 (issue #523) — `POST /push/broadcast` accessible à tout user
authentifié.

Bug: la route `POST /push/broadcast` (`app/api/push_notifications.py:261`)
était couverte par le blueprint auth guard (donc derrière un Bearer JWT)
mais n'avait PAS `@require_admin`. Conséquence: n'importe quel user qui
avait obtenu un magic link pouvait pousser une notif phishing à toute la
base mobile en un seul appel.

Fix: ajout de `@require_admin` sur `broadcast_notification` —
même pattern que `marketplace.approve_agent`.

Run: `pytest tests/audit_fixes/test_c_03_push_broadcast_admin_only.py -v`
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_push_service():
    from unittest.mock import MagicMock
    with patch("app.api.push_notifications._get_push_notification_service") as g:
        svc = MagicMock()
        svc.broadcast.return_value = []
        g.return_value = svc
        yield svc


REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}
PHISH_BODY = {"title": "Account compromised", "body": "Click here to fix"}


# --------------------------------------------------------------------------- #
# Reproduction: a non-admin authenticated user MUST NOT broadcast
# --------------------------------------------------------------------------- #


def test_broadcast_non_admin_jwt_must_be_rejected(client, mock_push_service):
    """C-3: a magic-link JWT for a normal user MUST be 403, not 200."""
    fake_payload = {"sub": "42", "email": "victim@example.com"}

    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.admin._is_admin",
        return_value=False,
    ):
        resp = client.post(
            "/push/broadcast",
            json=PHISH_BODY,
            content_type="application/json",
            headers={"Authorization": "Bearer normal-user-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 403, (
        f"C-3 leak: non-admin authenticated user got {resp.status_code} "
        f"with body {resp.get_data(as_text=True)[:200]}"
    )
    # The broadcast service must not have been invoked.
    mock_push_service.broadcast.assert_not_called()


def test_broadcast_no_jwt_remote_must_be_rejected(client, mock_push_service):
    """Belt-and-suspenders: an anonymous remote caller is also rejected."""
    resp = client.post(
        "/push/broadcast",
        json=PHISH_BODY,
        content_type="application/json",
        environ_base=REMOTE_ATTACKER,
    )
    # Either the blueprint auth guard returns 401 first, or @require_auth
    # returns 401 — both acceptable, neither must be 200.
    assert resp.status_code in (401, 403), (
        f"C-3 leak: anonymous remote caller got {resp.status_code}"
    )
    mock_push_service.broadcast.assert_not_called()


def test_broadcast_loopback_no_jwt_must_be_rejected(client, mock_push_service):
    """Tauri loopback callers are NOT exempt from @require_admin.
    Without a Bearer the @require_auth wrapper inside @require_admin
    rejects the call — desktop must not bypass admin gating either."""
    resp = client.post(
        "/push/broadcast",
        json=PHISH_BODY,
        content_type="application/json",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 401
    mock_push_service.broadcast.assert_not_called()


# --------------------------------------------------------------------------- #
# Sanity: legitimate admin still works
# --------------------------------------------------------------------------- #


def test_broadcast_admin_jwt_succeeds(client, mock_push_service):
    """Regression: a real admin JWT must still be able to broadcast."""
    fake_payload = {"sub": "1", "email": "admin@test.com"}

    with patch(
        "app.api.auth._decode_jwt",
        return_value=fake_payload,
    ), patch(
        "app.api.admin._is_admin",
        return_value=True,
    ):
        resp = client.post(
            "/push/broadcast",
            json={"title": "Maintenance", "body": "Down 22h-23h"},
            content_type="application/json",
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200, (
        f"Admin broadcast unexpectedly rejected: {resp.status_code} "
        f"{resp.get_data(as_text=True)[:200]}"
    )
    mock_push_service.broadcast.assert_called_once()


# --------------------------------------------------------------------------- #
# Static check: the decorator is actually present on the view function
# --------------------------------------------------------------------------- #


def test_broadcast_source_has_require_admin_decorator():
    """Source-level sanity check: prevents a future refactor from silently
    removing the decorator. functools.wraps makes runtime introspection
    unreliable (qualnames are copied), so we grep the source instead."""
    import inspect

    from app.api import push_notifications

    src = inspect.getsource(push_notifications)
    # Find the broadcast_notification def and check the preceding decorators.
    idx = src.find("def broadcast_notification(")
    assert idx > 0, "broadcast_notification not found in source"
    # Look backwards 400 chars — enough to span the decorator stack.
    preamble = src[max(0, idx - 400) : idx]
    assert "@require_admin" in preamble, (
        "@require_admin missing immediately above broadcast_notification — "
        "the C-3 fix has been regressed.\nPreamble:\n" + preamble
    )
