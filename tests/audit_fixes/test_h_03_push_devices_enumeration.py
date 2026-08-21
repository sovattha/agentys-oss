# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix H-3 (issue #529) — `GET /push/devices` énumération cross-tenant.

Bug: la route `GET /push/devices` (`app/api/push_notifications.py:117`)
listait l'inventaire COMPLET des devices enregistrés (token masqué + nom
d'appareil "Nat's iPhone", plateforme, app_version, last-used timestamps).
Le `?user_id=` query param était attaquant-controlled, permettant de
scanner ciblement un autre tenant. Combiné avec H-2, le token masqué était
la seule barrière contre l'usurpation de devices.

Fix:
  - JWT non-admin : ignore `?user_id=` et scope strict sur le caller
    (match `device.user_id` contre `auth_user["id"]` OU `auth_user["email"]`,
    case-insensitive — symétrique avec H-2).
  - Admin : `?user_id=` honoré comme override explicite.
  - Loopback Tauri sans JWT : trust legacy (single-user host).

Run: `pytest tests/audit_fixes/test_h_03_push_devices_enumeration.py -v`
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

from app.domain.entities import DeviceToken, DevicePlatform


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _device(token: str, *, user_id: str | None, name: str = "iPhone") -> DeviceToken:
    return DeviceToken(
        token=token,
        platform=DevicePlatform.IOS,
        user_id=user_id,
        device_name=name,
        app_version="1.0.0",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )


@pytest.fixture
def seeded_store():
    """Patch the device store with three devices spanning two tenants.

    - alice's iPhone, registered by email
    - alice's iPad, registered by sub-id ("42")
    - bob's iPhone, registered by email — must NEVER leak to alice
    """
    devices = [
        _device("expo_alice_iphone_xxxxxxxxxxxxxx", user_id="alice@example.com",
                name="Alice iPhone"),
        _device("expo_alice_ipad_xxxxxxxxxxxxxxxx", user_id="42",
                name="Alice iPad"),
        _device("expo_bob_iphone_xxxxxxxxxxxxxxxx", user_id="bob@example.com",
                name="Bob's secret phone"),
    ]
    with patch("app.api.push_notifications._get_device_store") as mock_getter:
        store = MagicMock()
        # `get_all(user_id)`: filtre exact si fourni, sinon tous.
        def _get_all(user_id=None):
            if user_id is None:
                return list(devices)
            return [d for d in devices if d.user_id == user_id]
        store.get_all.side_effect = _get_all
        mock_getter.return_value = store
        yield store


REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}


# --------------------------------------------------------------------------- #
# Reproduction: cross-tenant enumeration MUST be blocked.
# --------------------------------------------------------------------------- #


def test_non_admin_jwt_only_sees_own_devices(client, seeded_store):
    """Alice's JWT lists devices → only Alice's iPhone + iPad, never Bob's."""
    fake_payload = {"sub": "42", "email": "alice@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=False):
        resp = client.get(
            "/push/devices",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200
    body = resp.get_json()
    names = sorted(d["device_name"] for d in body["devices"])
    assert names == ["Alice iPad", "Alice iPhone"]
    assert "Bob's secret phone" not in [d["device_name"] for d in body["devices"]]
    assert body["count"] == 2


def test_non_admin_user_id_override_is_ignored(client, seeded_store):
    """Alice sets `?user_id=bob@example.com`. Must NOT return Bob's device —
    the param is silently ignored for non-admins."""
    fake_payload = {"sub": "42", "email": "alice@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=False):
        resp = client.get(
            "/push/devices?user_id=bob@example.com",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200
    body = resp.get_json()
    leaked = [d["device_name"] for d in body["devices"]]
    assert "Bob's secret phone" not in leaked
    assert body["count"] == 2  # alice's two devices, NOT bob's


def test_unrelated_jwt_sees_empty_list(client, seeded_store):
    """A JWT for a user who has no registered devices gets an empty list,
    NOT the full inventory — proves the fix isn't conditional on the param."""
    fake_payload = {"sub": "999", "email": "carol@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=False):
        resp = client.get(
            "/push/devices",
            headers={"Authorization": "Bearer carol-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == 0
    assert body["devices"] == []


def test_email_match_is_case_insensitive(client, seeded_store):
    """JWT with `Alice@Example.COM` still matches alice's email-registered
    device (mailbox local-part casing is not authoritative)."""
    fake_payload = {"sub": "9999", "email": "Alice@Example.COM"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=False):
        resp = client.get(
            "/push/devices",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200
    body = resp.get_json()
    names = [d["device_name"] for d in body["devices"]]
    # iPhone matches via email. iPad won't (sub mismatch in this scenario).
    assert "Alice iPhone" in names
    assert "Bob's secret phone" not in names


# --------------------------------------------------------------------------- #
# Admin override
# --------------------------------------------------------------------------- #


def test_admin_can_filter_by_user_id(client, seeded_store):
    """Admin JWT + `?user_id=bob@example.com` returns Bob's devices (ops use)."""
    fake_payload = {"sub": "1", "email": "admin@test.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=True):
        resp = client.get(
            "/push/devices?user_id=bob@example.com",
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200
    body = resp.get_json()
    names = [d["device_name"] for d in body["devices"]]
    assert names == ["Bob's secret phone"]


def test_admin_without_user_id_still_scoped(client, seeded_store):
    """Without `?user_id=`, even admin only sees their own — full enum is
    intentionally NOT exposed via this route. Admins use /api/admin/...
    tooling for inventory; this prevents an admin's leaked JWT from
    being a one-shot mobile address-book dump."""
    fake_payload = {"sub": "1", "email": "admin@test.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=True):
        resp = client.get(
            "/push/devices",
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200
    body = resp.get_json()
    # Admin has no devices registered — empty inventory, not full list.
    assert body["count"] == 0


# --------------------------------------------------------------------------- #
# Loopback Tauri: legacy single-host behaviour preserved
# --------------------------------------------------------------------------- #


def test_loopback_no_jwt_sees_full_inventory(client, seeded_store):
    """Tauri desktop without JWT is trusted — single-user host means the
    inventory contains only this user's devices anyway."""
    resp = client.get(
        "/push/devices",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == 3  # legacy behaviour: full list
