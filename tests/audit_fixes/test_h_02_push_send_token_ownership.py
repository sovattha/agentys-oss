# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix H-2 (issue #528) — `POST /push/send` sans check ownership token.

Bug: la route `POST /push/send` (`app/api/push_notifications.py:178`) était
gardée par le blueprint auth guard (Bearer JWT obligatoire en remote) MAIS ne
vérifiait jamais que les `tokens[]` du body appartenaient au caller. Tout
user authentifié pouvait push à n'importe quel device dont il connaissait le
token (DM screenshot, leak de logs, install antérieure) — surface de phishing
mobile évidente.

Fix: ajout d'un helper `_caller_owns_token(token)` invoqué pour chaque token
du body. Si l'un d'eux n'est pas owned par le JWT caller (`device.user_id`
ne match ni `auth_user["id"]` ni `auth_user["email"]`), 403 all-or-nothing
avec code `TOKEN_OWNERSHIP_DENIED`. Loopback Tauri sans JWT reste autorisé
(single-user host).

Run: `pytest tests/audit_fixes/test_h_02_push_send_token_ownership.py -v`
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

from app.domain.entities import DeviceToken, DevicePlatform
from app.domain.ports import PushNotificationResult


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


def _device(token: str, *, user_id: str | None) -> DeviceToken:
    return DeviceToken(
        token=token,
        platform=DevicePlatform.IOS,
        user_id=user_id,
        device_name="iPhone",
        app_version="1.0.0",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )


@pytest.fixture
def mock_device_store():
    """Patch the device store getter — tests seed `.get` per case."""
    with patch("app.api.push_notifications._get_device_store") as mock_getter:
        store = MagicMock()
        store.get.return_value = None  # default: unknown token
        mock_getter.return_value = store
        yield store


@pytest.fixture
def mock_push_service():
    with patch("app.api.push_notifications._get_push_notification_service") as g:
        svc = MagicMock()
        svc.send_to_token.return_value = PushNotificationResult(
            success=True, message_id="msg-1"
        )
        svc.send_to_tokens.return_value = [
            PushNotificationResult(success=True, message_id="msg-1"),
        ]
        g.return_value = svc
        yield svc


REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}
SEND_BODY = {"title": "Phish", "body": "Click here"}


# --------------------------------------------------------------------------- #
# Reproduction: cross-tenant push from a remote attacker MUST be rejected.
# --------------------------------------------------------------------------- #


def test_send_to_other_users_token_is_rejected(
    client, mock_device_store, mock_push_service
):
    """Caller A (sub=42, alice@x) tries to push to Bob's token. 403."""
    bob_token = "expo_bob_device_token_xxxxxxxxxxxx"
    mock_device_store.get.return_value = _device(bob_token, user_id="bob@example.com")

    fake_payload = {"sub": "42", "email": "alice@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload):
        resp = client.post(
            "/push/send",
            json={**SEND_BODY, "token": bob_token},
            content_type="application/json",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 403, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["code"] == "TOKEN_OWNERSHIP_DENIED"
    # The push service must NEVER have been invoked.
    mock_push_service.send_to_token.assert_not_called()
    mock_push_service.send_to_tokens.assert_not_called()


def test_send_with_one_foreign_token_is_all_or_nothing(
    client, mock_device_store, mock_push_service
):
    """Mixed body (1 owned + 1 foreign) → 403, NO partial send."""
    alice_token = "expo_alice_token_xxxxxxxxxxxxxxxx"
    bob_token = "expo_bob_token_xxxxxxxxxxxxxxxxxx"

    def _lookup(t):
        if t == alice_token:
            return _device(alice_token, user_id="alice@example.com")
        if t == bob_token:
            return _device(bob_token, user_id="bob@example.com")
        return None

    mock_device_store.get.side_effect = _lookup

    fake_payload = {"sub": "42", "email": "alice@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload):
        resp = client.post(
            "/push/send",
            json={**SEND_BODY, "tokens": [alice_token, bob_token]},
            content_type="application/json",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 403
    assert resp.get_json()["code"] == "TOKEN_OWNERSHIP_DENIED"
    mock_push_service.send_to_token.assert_not_called()
    mock_push_service.send_to_tokens.assert_not_called()


def test_send_to_unknown_token_is_rejected(
    client, mock_device_store, mock_push_service
):
    """A token that's not even registered → 403 (uniform with foreign tokens
    so the endpoint isn't an existence oracle)."""
    mock_device_store.get.return_value = None

    fake_payload = {"sub": "42", "email": "alice@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload):
        resp = client.post(
            "/push/send",
            json={**SEND_BODY, "token": "expo_unknown_xxxxxxxxxxxxxxxxxx"},
            content_type="application/json",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 403
    assert resp.get_json()["code"] == "TOKEN_OWNERSHIP_DENIED"
    mock_push_service.send_to_token.assert_not_called()


def test_send_to_unclaimed_device_is_rejected(
    client, mock_device_store, mock_push_service
):
    """A registered device with `user_id=None` is unclaimed — no caller
    legitimately owns it. Must reject (otherwise the previous attack
    re-opens for any device that happened to be registered without a uid)."""
    token = "expo_unclaimed_token_xxxxxxxxxxxxx"
    mock_device_store.get.return_value = _device(token, user_id=None)

    fake_payload = {"sub": "42", "email": "alice@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload):
        resp = client.post(
            "/push/send",
            json={**SEND_BODY, "token": token},
            content_type="application/json",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 403
    mock_push_service.send_to_token.assert_not_called()


# --------------------------------------------------------------------------- #
# Sanity: legitimate flows still work.
# --------------------------------------------------------------------------- #


def test_send_to_own_token_by_email_succeeds(
    client, mock_device_store, mock_push_service
):
    """Owner addresses their own device (registered with email-shaped uid)."""
    alice_token = "expo_alice_token_xxxxxxxxxxxxxxxx"
    mock_device_store.get.return_value = _device(
        alice_token, user_id="alice@example.com"
    )

    fake_payload = {"sub": "42", "email": "alice@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload):
        resp = client.post(
            "/push/send",
            json={**SEND_BODY, "token": alice_token},
            content_type="application/json",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    mock_push_service.send_to_token.assert_called_once()


def test_send_to_own_token_by_sub_id_succeeds(
    client, mock_device_store, mock_push_service
):
    """Some clients register with the JWT subject (numeric id) instead of
    email — both forms must be accepted to avoid breaking existing devices."""
    alice_token = "expo_alice_by_id_xxxxxxxxxxxxxxx"
    mock_device_store.get.return_value = _device(alice_token, user_id="42")

    fake_payload = {"sub": "42", "email": "alice@example.com"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload):
        resp = client.post(
            "/push/send",
            json={**SEND_BODY, "token": alice_token},
            content_type="application/json",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    mock_push_service.send_to_token.assert_called_once()


def test_send_email_match_is_case_insensitive(
    client, mock_device_store, mock_push_service
):
    """Mailbox-local-part and provider-side casing should never be a leak
    vector. `Alice@Example.COM` JWT matches `alice@example.com` device."""
    alice_token = "expo_alice_case_xxxxxxxxxxxxxxxxx"
    mock_device_store.get.return_value = _device(
        alice_token, user_id="alice@example.com"
    )

    fake_payload = {"sub": "42", "email": "Alice@Example.COM"}
    with patch("app.api.auth._decode_jwt", return_value=fake_payload):
        resp = client.post(
            "/push/send",
            json={**SEND_BODY, "token": alice_token},
            content_type="application/json",
            headers={"Authorization": "Bearer alice-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    mock_push_service.send_to_token.assert_called_once()


def test_loopback_no_jwt_is_trusted(client, mock_device_store, mock_push_service):
    """Tauri desktop (loopback, no Bearer) is trusted as before — single
    user host means no cross-tenant threat. Don't break the desktop flow."""
    # Even with no device registered for the token, loopback Tauri can push.
    mock_device_store.get.return_value = None

    resp = client.post(
        "/push/send",
        json={**SEND_BODY, "token": "expo_local_xxxxxxxxxxxxxxxxxxxxx"},
        content_type="application/json",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    mock_push_service.send_to_token.assert_called_once()
