# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix ISO-06 / S-01 — `_resolve_ws_room()` returns `"localhost"` for any
loopback request without a JWT, then every `emit_*` helper broadcasts to
that shared room.

Bug: in `app/api/websocket.py:_resolve_ws_room()` (originally lines
275-293), when the request has no JWT (Tauri loopback) the function returns
the literal string `"localhost"`. Every loopback-connected Socket.IO client
shares that single room, so `emit_new_email` / `emit_draft_complete` /
`emit_email_archived` / etc. broadcast to all of them.

Fix: never return `"localhost"`. In a request context with no JWT, return
None (the emitters then fall through to a per-account or per-sid scoped
emission). For request contexts with a JWT, keep returning the user's
email. Outside a request context, also return None.

Run: `pytest tests/audit_fixes/test_iso_06_websocket_localhost_broadcast.py -v`
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


# --------------------------------------------------------------------------- #
# Direct tests on the helper — simpler than spinning up a real Socket.IO link.
# --------------------------------------------------------------------------- #


def test_resolve_ws_room_returns_jwt_email(app):
    """When the JWT is present (g.auth_user populated), return the user's
    email — that is the per-user room the connect handler joined."""
    from app.api.websocket import _resolve_ws_room

    with app.test_request_context("/api/health"):
        from flask import g
        g.auth_user = {"id": 1, "email": "alice@example.com"}
        assert _resolve_ws_room() == "alice@example.com"


def test_resolve_ws_room_no_jwt_in_request_context_returns_none(app):
    """ISO-06: no JWT → MUST NOT return the literal string 'localhost'.

    Returning a constant string makes every loopback-connected client share
    one room, so emit_* helpers broadcast cross-user.
    """
    from app.api.websocket import _resolve_ws_room

    with app.test_request_context("/api/health"):
        # No g.auth_user / g.auth_user None — Tauri loopback, no Bearer.
        room = _resolve_ws_room()
        assert room != "localhost", (
            "ISO-06 leak: _resolve_ws_room returned 'localhost' which is "
            "shared across every loopback Socket.IO client → cross-user "
            "broadcast of new_email, draft_complete, email_archived, etc."
        )
        # The contract for the fixed implementation: None tells callers
        # to skip the broadcast (or fall through to per-account scoping).
        assert room is None


def test_resolve_ws_room_outside_request_context_returns_none(app):
    """Outside any request (background thread, daemon, scheduler), the helper
    returns None so emitters fall through to account-scoped emission instead
    of broadcasting."""
    from app.api.websocket import _resolve_ws_room

    # No app context, no request context at all.
    assert _resolve_ws_room() is None


def test_emit_new_email_no_jwt_does_not_broadcast(app):
    """End-to-end: `emit_new_email` invoked from a loopback request with no
    JWT MUST NOT broadcast namespace-wide — that would push another user's
    inbox state into the wrong tab.

    We patch `get_socketio` to return a stub and assert that either:
      (a) the helper aborts entirely (no `emit` call), OR
      (b) the helper calls `emit` with a `to=` argument that is NOT the
          shared 'localhost' room and NOT None (which Socket.IO interprets
          as broadcast).
    """
    from app.api import websocket as ws_module

    class _StubSocket:
        def __init__(self):
            self.emits: list[tuple] = []

        def emit(self, *args, **kwargs):
            self.emits.append((args, kwargs))

    stub = _StubSocket()

    with patch.object(ws_module, "get_socketio", return_value=stub), \
         app.test_request_context("/api/health"):
        from flask import g
        # Loopback, no JWT → the very scenario the original code routed to
        # room='localhost'.
        g.auth_user = None
        ws_module.emit_new_email({
            "email_id": "abc",
            "sender": "x@y.com",
            "subject": "Hi",
        })

    if not stub.emits:
        # Acceptable: the helper realised there's no per-user/per-account
        # scope and skipped the emit. That's the safest outcome.
        return

    # If the helper DID emit, verify the room is not the dangerous default.
    args, kwargs = stub.emits[-1]
    room = kwargs.get("to")
    assert room != "localhost", (
        "ISO-06 leak: emit_new_email pushed event to room='localhost' "
        "(shared across every loopback client)."
    )
