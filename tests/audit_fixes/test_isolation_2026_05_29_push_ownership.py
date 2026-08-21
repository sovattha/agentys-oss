# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 — push notification endpoints leaked across tenants.

- DELETE /push/devices/<token>  had NO ownership check → anyone with a victim's
  full device token could unregister it (silence their push).
- GET /push/stats and GET /push/history  exposed the ENTIRE device inventory /
  notification volume (history even leaked titles+bodies) to any authenticated
  caller.

Fix: DELETE now calls _caller_owns_token (404 on mismatch); stats + history are
gated @require_admin, mirroring /broadcast.

Run: pytest tests/audit_fixes/test_isolation_2026_05_29_push_ownership.py -v
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

from app.domain.entities import DeviceToken, DevicePlatform

REMOTE = {"REMOTE_ADDR": "203.0.113.10"}
AUTH = {"Authorization": "Bearer tok"}


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


def _device(token, user_id):
    return DeviceToken(
        token=token, platform=DevicePlatform.IOS, user_id=user_id,
        device_name="x", app_version="1.0.0", created_at=datetime(2026, 1, 1),
    )


# --------------------------------------------------------------------------- #
# DELETE /push/devices/<token>
# --------------------------------------------------------------------------- #

def test_delete_device_rejects_non_owner(client):
    """Attacker holding the victim's token cannot unregister it."""
    victim_token = "expo_victim_token_xxxxxxxxxxxxxx"
    store = MagicMock()
    store.get.return_value = _device(victim_token, user_id="victim@corp.com")
    with patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "attacker@corp.com"}), \
         patch("app.api.push_notifications._get_device_store", return_value=store):
        resp = client.delete(f"/push/devices/{victim_token}", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 404
    store.unregister.assert_not_called()


def test_delete_device_allows_owner(client):
    token = "expo_owner_token_xxxxxxxxxxxxxxxx"
    store = MagicMock()
    store.get.return_value = _device(token, user_id="owner@corp.com")
    store.unregister.return_value = True
    with patch("app.api.auth._decode_jwt", return_value={"sub": "7", "email": "owner@corp.com"}), \
         patch("app.api.push_notifications._get_device_store", return_value=store):
        resp = client.delete(f"/push/devices/{token}", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    store.unregister.assert_called_once_with(token)


# --------------------------------------------------------------------------- #
# GET /push/stats and /push/history — admin-gated
# --------------------------------------------------------------------------- #

def test_stats_rejected_for_non_admin(client):
    with patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "user@corp.com"}), \
         patch("app.api.admin._is_admin", return_value=False):
        resp = client.get("/push/stats", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 403


def test_history_rejected_for_non_admin(client):
    with patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "user@corp.com"}), \
         patch("app.api.admin._is_admin", return_value=False):
        resp = client.get("/push/history", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 403


def test_stats_allowed_for_admin(client):
    svc = MagicMock()
    svc.get_stats.return_value = {"total": 0}
    store = MagicMock()
    store.get_all.return_value = []
    adapter = MagicMock()
    adapter.name = "expo"  # plain str — `name=` kwarg sets the mock repr, not .name
    with patch("app.api.auth._decode_jwt", return_value={"sub": "1", "email": "admin@corp.com"}), \
         patch("app.api.admin._is_admin", return_value=True), \
         patch("app.api.push_notifications._get_push_notification_service", return_value=svc), \
         patch("app.api.push_notifications._get_device_store", return_value=store), \
         patch("app.api.push_notifications._get_push_adapter", return_value=adapter):
        resp = client.get("/push/stats", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
