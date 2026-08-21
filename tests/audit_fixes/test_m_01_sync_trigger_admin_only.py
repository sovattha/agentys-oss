# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix M-1 (issue #535) — `POST /api/sync/trigger` accessible à tout
user authentifié.

Bug : `app/api/sync.py:trigger_sync` était couvert par le blueprint auth
guard (donc Bearer requis) mais pas par `@require_admin`. Le handler
appelle `sync_service.trigger_sync()` qui itère TOUS les comptes
configurés du singleton — un user authentifié pouvait donc déclencher
en boucle un fan-out global qui hit les rate limits Gmail/Outlook pour
toute la base. DoS amplification cross-tenant.

Fix : `@require_admin` sur `trigger_sync` — même pattern que
`push_notifications.broadcast_notification` (#523) et
`marketplace.approve_agent`.

Le refactor "scoper aux comptes du JWT caller" reste possible si une UX
"sync mes comptes" apparaît un jour côté frontend (aucun appel actuel
depuis `agentys-app/src/`).

Run: `pytest tests/audit_fixes/test_m_01_sync_trigger_admin_only.py -v`
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
def running_sync_service():
    """Singleton running, ready to accept a trigger."""
    svc = MagicMock()
    svc.is_running = True
    svc.trigger_sync.return_value = True
    with patch("app.api.sync.get_sync_service", return_value=svc):
        yield svc


# Remote attacker — hits the API from outside loopback so the auth guard
# enforces the Bearer requirement (loopback would `g.auth_user = None` and
# slip past the guard, but @require_admin then 401s anyway).
REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}


# --------------------------------------------------------------------------- #
# Reproduction: non-admin authenticated user MUST NOT trigger a global sync
# --------------------------------------------------------------------------- #


def test_trigger_no_bearer_remote_must_be_rejected(client, running_sync_service):
    """M-1: a remote caller without Bearer must hit 401 from the auth guard,
    NOT slip into the singleton sync."""
    response = client.post(
        "/api/sync/trigger",
        environ_base=REMOTE_ATTACKER,
    )
    assert response.status_code == 401, (
        f"expected 401 (no Bearer), got {response.status_code}: {response.get_json()}"
    )
    running_sync_service.trigger_sync.assert_not_called()


def test_trigger_non_admin_jwt_must_be_rejected(client, running_sync_service):
    """M-1: a magic-link JWT for a normal user MUST hit 403, NOT trigger."""
    fake_payload = {"sub": "42", "email": "user@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=False):
        response = client.post(
            "/api/sync/trigger",
            headers={"Authorization": "Bearer user-stub"},
        )

    assert response.status_code == 403, (
        f"expected 403 (admin only), got {response.status_code}: {response.get_json()}"
    )
    body = response.get_json()
    # i18n migration (commit 3850dea9) flipped backend error responses to
    # carry `error_code` + an English fallback for FE i18n lookup. The old
    # French `"administrateurs"` assertion broke when admin.py was migrated.
    assert body.get("error_code") == "ADMIN_ACCESS_ONLY", (
        f"expected error_code=ADMIN_ACCESS_ONLY, got {body!r}"
    )
    running_sync_service.trigger_sync.assert_not_called()


def test_trigger_invalid_jwt_must_be_rejected(client, running_sync_service):
    """M-1: a Bearer present but invalid (forged / expired) → 401."""
    with patch("app.api.auth._decode_jwt", return_value=None):
        response = client.post(
            "/api/sync/trigger",
            headers={"Authorization": "Bearer forged-token"},
            environ_base=REMOTE_ATTACKER,
        )

    assert response.status_code == 401
    running_sync_service.trigger_sync.assert_not_called()


# --------------------------------------------------------------------------- #
# Positive control: admin JWT still triggers (regression-resistance vs
# overzealous gating that would lock everyone out)
# --------------------------------------------------------------------------- #


def test_trigger_admin_jwt_succeeds(client, running_sync_service):
    """M-1: an admin Bearer reaches the handler and triggers the sync."""
    fake_payload = {"sub": "1", "email": "admin@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=True):
        response = client.post(
            "/api/sync/trigger",
            headers={"Authorization": "Bearer admin-stub"},
        )

    assert response.status_code == 202, response.get_data(as_text=True)
    body = response.get_json()
    assert body["success"] is True
    running_sync_service.trigger_sync.assert_called_once()


# --------------------------------------------------------------------------- #
# Belt-and-suspenders: the route is also resilient against a missing auth
# guard (a future regression where `sync_bp` is dropped from
# `_guarded_blueprints`). `@require_admin` itself wraps `@require_auth`,
# so even without the blueprint guard a remote no-Bearer caller must 401.
# --------------------------------------------------------------------------- #


def test_decorator_alone_rejects_no_bearer(client, running_sync_service):
    """M-1 defense-in-depth: even if the blueprint-level guard were removed,
    `@require_admin` (which wraps `@require_auth`) still 401s no-Bearer."""
    # Loopback path — would skip the blueprint guard. Should still be 401
    # because @require_auth demands a Bearer regardless of remote_addr.
    response = client.post("/api/sync/trigger")
    assert response.status_code == 401, (
        f"expected 401 from @require_auth, got {response.status_code}: "
        f"{response.get_json()}"
    )
    running_sync_service.trigger_sync.assert_not_called()
