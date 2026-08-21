# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix M-4 (issue #538) — Socket.IO orchestration/learning emitters
migration ISO-06 incomplète.

Bug: les helpers `emit_orchestration_*` (`websocket.py:1452-1686`) et
`emit_learning_*` (`:1694-1823`) ne prenaient pas de paramètre
`account_id`, contrairement à `emit_draft_*` / `emit_critique_*`
migrés sous ISO-06. Ils dépendaient
exclusivement de `_resolve_ws_room()` qui retourne `None` hors contexte
Flask request → l'event était silencieusement droppé. Posture sûre
aujourd'hui (drop), mais régression dangereuse si quelqu'un retire le
guard `if room is None: return` pour "fix" les events droppés —
broadcast namespace-wide, leak orchestration/learning state cross-tenant.

Fix : threader `account_id: int | None = None` sur les 6 emitters
orchestration + 4 emitters learning (correction_recorded, label_corrected,
analysis_completed, rule_extracted), et router via `emit_to_account` quand
fourni. Callers connus migrés (`learning_refresh.py`, `routes_pending.py`).

Run: `pytest tests/audit_fixes/test_m_04_orchestration_learning_emitters_account_scoped.py -v`
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")


# --------------------------------------------------------------------------- #
# Signature checks: each emitter must accept account_id as a kwarg
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", [
    "emit_orchestration_start",
    "emit_orchestration_iteration_start",
    "emit_orchestration_iteration_complete",
    "emit_orchestration_complete",
    "emit_orchestration_timeout",
    "emit_orchestration_error",
    "emit_learning_correction_recorded",
    "emit_learning_label_corrected",
    "emit_learning_analysis_completed",
    "emit_learning_rule_extracted",
])
def test_emitter_accepts_account_id_kwarg(name):
    """M-4: every migrated emitter must declare `account_id` as a
    keyword argument so background callers can route via `emit_to_account`.
    """
    import inspect
    from app.api import websocket
    fn = getattr(websocket, name)
    sig = inspect.signature(fn)
    assert "account_id" in sig.parameters, (
        f"{name} is missing the `account_id` parameter — M-4 fix has been "
        f"regressed. Callers in BG threads cannot route this event."
    )
    # Default must be None (the documented "no scope → drop" sentinel).
    assert sig.parameters["account_id"].default is None, (
        f"{name}.account_id default is not None — could leak across tenants "
        f"if a caller forgets to pass it explicitly."
    )


# --------------------------------------------------------------------------- #
# Routing check: when account_id is passed, the event MUST go via
# emit_to_account, never via the namespace-wide socketio.emit fallback
# --------------------------------------------------------------------------- #


@pytest.fixture
def stub_socketio():
    """Stub for `get_socketio()` that records every emit call."""
    socket = MagicMock()
    with patch("app.api.websocket.get_socketio", return_value=socket):
        yield socket


@pytest.fixture
def stub_room_resolution():
    """Stub `_resolve_room_for_account` so emit_to_account never touches
    the DB (the in-memory account hashmap)."""
    with patch(
        "app.api.websocket._resolve_room_for_account",
        return_value="alice@example.com",
    ):
        yield


# Each tuple: (emitter_name, args, expected_event_name)
EMITTER_CASES = [
    ("emit_orchestration_start",
     ("email-1",), "orchestration_start"),
    ("emit_orchestration_iteration_start",
     ("email-2", 1), "orchestration_iteration_start"),
    ("emit_orchestration_iteration_complete",
     ("email-3", 1, 75, "VALID"), "orchestration_iteration_complete"),
    ("emit_orchestration_complete",
     ("email-4", "draft", 80, 2, 1500, True), "orchestration_complete"),
    ("emit_orchestration_timeout",
     ("email-5", "draft", 60, 3, 30000), "orchestration_timeout"),
    ("emit_orchestration_error",
     ("email-6", "boom"), "orchestration_error"),
    ("emit_learning_correction_recorded",
     ("email-7", True, 0.5), "learning:correction_recorded"),
    ("emit_learning_label_corrected",
     ("email-8", "Action", "FYI"), "learning:label_corrected"),
    ("emit_learning_analysis_completed",
     (3, 1), "learning:analysis_completed"),
    ("emit_learning_rule_extracted",
     ("rule-9", "Toujours signer 'Bonne journée'", "ton"),
     "learning:rule_extracted"),
]


@pytest.mark.parametrize("name,args,event_name", EMITTER_CASES)
def test_emitter_with_account_id_routes_via_emit_to_account(
    stub_socketio, stub_room_resolution, name, args, event_name,
):
    """When account_id=N is passed, the event must hit the per-room
    socketio.emit (`to="alice@example.com"`) — never the no-`to` broadcast."""
    from app.api import websocket
    fn = getattr(websocket, name)
    fn(*args, account_id=42)

    # emit_to_account → socketio.emit(event, payload, namespace="/daemon", to=room)
    assert stub_socketio.emit.called, (
        f"{name} did not call socketio.emit when account_id was provided"
    )
    call = stub_socketio.emit.call_args
    assert call.args[0] == event_name, (
        f"{name} emitted '{call.args[0]}', expected '{event_name}'"
    )
    assert call.kwargs.get("to") == "alice@example.com", (
        f"{name}: emit must target the account's room, got "
        f"{call.kwargs.get('to')!r} (would broadcast)"
    )
    assert call.kwargs.get("namespace") == "/daemon"


@pytest.mark.parametrize("name,args,event_name", EMITTER_CASES)
def test_emitter_drops_event_when_no_account_and_no_request_context(
    stub_socketio, name, args, event_name,
):
    """Defense-in-depth: outside any Flask request context AND without
    account_id, the emitter must NOT broadcast namespace-wide. Pre-migration,
    `_resolve_ws_room()` returned None and the event was silently dropped —
    the fix preserves that drop while making explicit account routing
    possible. A future careless "fix" that removes the `if room is None:
    return` guard would broadcast cross-tenant; this test catches it."""
    from app.api import websocket
    fn = getattr(websocket, name)
    # No account_id, no request context.
    fn(*args)
    # Must NOT have called socketio.emit — that would broadcast.
    assert not stub_socketio.emit.called, (
        f"{name} called socketio.emit with no account_id and no request "
        f"context — would broadcast namespace-wide. Args: "
        f"{stub_socketio.emit.call_args}"
    )


# --------------------------------------------------------------------------- #
# Lookup check: emit_to_account is invoked with the correct account_id
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name,args,event_name", EMITTER_CASES)
def test_emitter_calls_emit_to_account_with_correct_account_id(
    name, args, event_name,
):
    """The account_id passed to the emitter MUST flow through unchanged to
    emit_to_account. Catches regressions where someone refactors an
    emitter and accidentally hardcodes account_id or drops it."""
    from app.api import websocket
    fn = getattr(websocket, name)

    captured = {}

    def fake_emit_to_account(event, data, account_id):
        captured["event"] = event
        captured["account_id"] = account_id
        captured["data"] = data
        return True

    # Each emitter early-returns when get_socketio() is falsy, so we must
    # also stub it to a truthy value (what's returned doesn't matter — the
    # patched emit_to_account never reads it).
    with patch(
        "app.api.websocket.get_socketio", return_value=MagicMock()
    ), patch(
        "app.api.websocket.emit_to_account", side_effect=fake_emit_to_account
    ):
        fn(*args, account_id=777)

    assert captured.get("account_id") == 777, (
        f"{name} did not forward account_id=777 to emit_to_account "
        f"(captured: {captured})"
    )
    assert captured.get("event") == event_name


# --------------------------------------------------------------------------- #
# Regression: legacy callers (request-context only, no account_id) still work
# --------------------------------------------------------------------------- #


def test_legacy_request_context_caller_still_works(stub_socketio):
    """If a caller has a Flask request context with `g.auth_user` set
    (legacy ISO-06-compliant request handler) but doesn't pass account_id,
    the emitter must still route via the user's email room. Avoids breaking
    existing pre-migration callers."""
    from flask import Flask, g
    from app.api import websocket

    app = Flask(__name__)
    with app.test_request_context("/foo"):
        g.auth_user = {"id": 1, "email": "alice@example.com"}
        websocket.emit_orchestration_start("email-legacy")

    assert stub_socketio.emit.called, (
        "Legacy request-context caller broke — emit_orchestration_start "
        "must still resolve the user's room from g.auth_user when "
        "account_id is not provided."
    )
    call = stub_socketio.emit.call_args
    assert call.kwargs.get("to") == "alice@example.com"


# --------------------------------------------------------------------------- #
# Caller-side: pipelines must thread account_id when invoking these emitters
# --------------------------------------------------------------------------- #


def test_learning_refresh_correction_recorded_threads_account_id():
    """`LearningRefreshCoordinator.on_email_sent` runs in a BG thread
    (post-send recording); it MUST pass account_id when calling
    emit_learning_correction_recorded so the WS event reaches the user."""
    import inspect
    from app import learning_refresh

    src = inspect.getsource(learning_refresh.LearningRefreshCoordinator.on_email_sent)
    # The fix passes `account_id=account_id` to the emitter.
    assert "emit_learning_correction_recorded" in src
    assert "account_id=account_id" in src, (
        "M-4 regression: learning_refresh.on_email_sent no longer threads "
        "account_id to emit_learning_correction_recorded — events will "
        "silently drop in BG threads."
    )


def test_learning_refresh_label_corrected_threads_account_id():
    import inspect
    from app import learning_refresh

    src = inspect.getsource(learning_refresh.LearningRefreshCoordinator.on_label_corrected)
    assert "emit_learning_label_corrected" in src
    assert "account_id=account_id" in src, (
        "M-4 regression: learning_refresh.on_label_corrected no longer "
        "threads account_id to emit_learning_label_corrected."
    )


def test_routes_pending_extract_rules_threads_account_id():
    """The `_extract_rules_bg` worker in routes_pending.py must capture
    `_resolved_acct_id` and pass it to emit_learning_rule_extracted."""
    import inspect
    from app.api import routes_pending

    src = inspect.getsource(routes_pending)
    # We expect the call site to look like
    # `emit_learning_rule_extracted(... , account_id=...)`.
    idx = src.find("emit_learning_rule_extracted(")
    assert idx > 0, "emit_learning_rule_extracted call not found in routes_pending"
    # Take the next 600 chars after the call (covers the kwargs block).
    snippet = src[idx : idx + 600]
    assert "account_id=" in snippet, (
        "M-4 regression: routes_pending.py _extract_rules_bg does not pass "
        "account_id to emit_learning_rule_extracted — rule extraction "
        "events silently dropped in BG worker."
    )


# --------------------------------------------------------------------------- #
# Source-grep guard: the canonical emit_to_account branch must remain
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", [
    "emit_orchestration_start",
    "emit_orchestration_iteration_start",
    "emit_orchestration_iteration_complete",
    "emit_orchestration_complete",
    "emit_orchestration_timeout",
    "emit_orchestration_error",
    "emit_learning_correction_recorded",
    "emit_learning_label_corrected",
    "emit_learning_analysis_completed",
    "emit_learning_rule_extracted",
])
def test_emitter_source_uses_emit_to_account(name):
    """Source-level lock: the emit_to_account routing branch must remain.
    Catches a refactor that drops the branch or replaces it with a raw
    socketio.emit (which would broadcast)."""
    import inspect
    from app.api import websocket
    fn = getattr(websocket, name)
    src = inspect.getsource(fn)
    assert "emit_to_account(" in src, (
        f"{name} no longer calls emit_to_account — the M-4 fix has been "
        f"regressed; events from BG threads will not reach the right user."
    )
