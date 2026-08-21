"""Tests d'isolation WebSocket par compte.

Vérifie que emit_to_account() route les événements uniquement à la room
du compte ciblé, et ne fuit jamais entre comptes même quand l'appel
vient d'un worker background sans contexte request.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api import websocket as ws


class _FakeAccount:
    def __init__(self, id: int, email: str) -> None:
        self.id = id
        self.email = email


@pytest.fixture
def fake_socketio():
    socketio = MagicMock()
    with patch.object(ws, "_socketio", socketio):
        yield socketio


@pytest.fixture
def lookup_accounts(monkeypatch):
    """Patch _resolve_room_for_account pour simuler 2 comptes DB."""
    mapping = {1: "alice@example.com", 2: "bob@example.com"}

    def _fake(account_id):
        if not account_id or account_id <= 0:
            return None
        return mapping.get(account_id)

    monkeypatch.setattr(ws, "_resolve_room_for_account", _fake)
    return mapping


# --------------------------------------------------------------------------- #


def test_emit_to_account_routes_to_correct_room(fake_socketio, lookup_accounts):
    result = ws.emit_to_account("new_email", {"count": 3}, account_id=1)

    assert result is True
    fake_socketio.emit.assert_called_once_with(
        "new_email",
        {"count": 3},
        namespace="/daemon",
        to="alice@example.com",
    )


def test_emit_to_account_does_not_leak_to_other_account(
    fake_socketio, lookup_accounts
):
    ws.emit_to_account("draft_ready", {"draft_id": "d1"}, account_id=1)

    (_event, _data, kwargs) = (
        fake_socketio.emit.call_args.args[0],
        fake_socketio.emit.call_args.args[1],
        fake_socketio.emit.call_args.kwargs,
    )

    # Jamais bob@example.com
    assert kwargs["to"] == "alice@example.com"
    assert kwargs["to"] != "bob@example.com"


def test_emit_to_account_skips_unknown_account(fake_socketio, lookup_accounts):
    result = ws.emit_to_account("new_email", {"count": 1}, account_id=999)

    # Safer default : skip plutôt que broadcast
    assert result is False
    fake_socketio.emit.assert_not_called()


@pytest.mark.parametrize("invalid", [None, 0, -1, -42])
def test_emit_to_account_skips_invalid_account_id(
    fake_socketio, lookup_accounts, invalid
):
    result = ws.emit_to_account("new_email", {"count": 1}, account_id=invalid)

    assert result is False
    fake_socketio.emit.assert_not_called()


def test_emit_to_account_no_socketio_returns_false(lookup_accounts):
    with patch.object(ws, "_socketio", None):
        result = ws.emit_to_account("new_email", {"count": 1}, account_id=1)

    assert result is False


def test_emit_to_account_never_broadcasts_without_room(
    fake_socketio, monkeypatch
):
    """Garantie critique : si aucune room résolue, on ne diffuse PAS
    à tous les clients. C'était la fuite historique (`socketio.emit()`
    sans `to=`)."""
    monkeypatch.setattr(ws, "_resolve_room_for_account", lambda _: None)

    result = ws.emit_to_account("new_email", {"count": 1}, account_id=1)

    assert result is False
    fake_socketio.emit.assert_not_called()
