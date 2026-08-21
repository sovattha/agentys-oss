# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix S-09 — `emit_draft_complete` is called from a background thread
(`_process_in_background`) without passing `account_id`, so it falls back
to `_resolve_ws_room()` → None → `to=None` → namespace-wide broadcast.
Result: ReplyComposer on User A's tab receives the draft body for an
email being generated for User B.

Fix: `emit_draft_complete` now accepts an optional `account_id` parameter
and routes via `emit_to_account` when provided. The bg thread in
`routes_emails.py` was updated to forward `_bg_account_id`.

Run: `pytest tests/audit_fixes/test_s_09_emit_draft_complete_account_scope.py -v`
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


def test_emit_draft_complete_accepts_account_id_kwarg():
    """S-09: the helper signature must accept `account_id` so callers can
    opt into per-account routing instead of relying on the request
    context."""
    import inspect
    from app.api.websocket import emit_draft_complete
    sig = inspect.signature(emit_draft_complete)
    assert "account_id" in sig.parameters, (
        "S-09 leak: emit_draft_complete still has no account_id "
        "parameter — bg threads can't route the event."
    )


def test_emit_draft_complete_routes_to_account_when_id_provided(app):
    """S-09: when `account_id` is provided, the helper must route via
    `emit_to_account` (which scopes to that account's room) rather than
    fall back to the broadcast-prone _resolve_ws_room path."""
    from app.api import websocket as ws_module

    calls = []

    def _fake_emit_to_account(event, data, account_id):
        calls.append((event, data, account_id))
        return True

    with patch.object(ws_module, "emit_to_account", side_effect=_fake_emit_to_account):
        ws_module.emit_draft_complete(
            email_id="abc",
            draft_content="Hello",
            confidence=0.9,
            generation_time_ms=42,
            tokens_used=10,
            tone_detected="professional",
            account_id=42,
        )

    assert len(calls) == 1, calls
    event, data, account_id = calls[0]
    assert event == "draft_complete"
    assert account_id == 42
    assert data["email_id"] == "abc"
    assert data["draft"] == "Hello"


def test_emit_draft_complete_no_account_does_not_broadcast(app):
    """Sanity: when no account_id is passed AND there's no JWT in the
    request context, the helper falls through to _resolve_ws_room which
    now returns None → no emit → no broadcast leak."""
    from app.api import websocket as ws_module

    class _StubSocket:
        def __init__(self):
            self.emits = []

        def emit(self, *args, **kwargs):
            self.emits.append((args, kwargs))

    stub = _StubSocket()

    with patch.object(ws_module, "get_socketio", return_value=stub), \
         app.test_request_context("/api/health"):
        from flask import g
        g.auth_user = None
        ws_module.emit_draft_complete(
            email_id="abc",
            draft_content="Hello",
            confidence=0.9,
            generation_time_ms=42,
            tokens_used=10,
            tone_detected="professional",
        )

    # When there's no scope at all, the helper must NOT emit at all
    # (skip is safer than broadcast).
    assert stub.emits == []
