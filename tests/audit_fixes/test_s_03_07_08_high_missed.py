# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fixes for the HIGH-severity findings missed by the previous audit pass.

S-03 — `_last_bg_jobs_time` is a single float shared across accounts → the
60s throttle for auto-reply / follow-ups / secondary folder prefetch fires
at most once per 60s GLOBALLY, so all but the first account are starved.

S-07 — Several routes spawn `threading.Thread(...)` background threads that
later import `emit_*` helpers without capturing `account_id`. The bg
target's `_resolve_ws_room()` returns None outside a request context,
producing namespace-wide broadcasts.

S-08 — `emit_sync_started`, `emit_sync_progress`, `emit_new_email`
callbacks broadcast cross-account when called from the sync thread (the
sync thread has no Flask request context, `_resolve_ws_room()` returns
None, and the previous behavior was a global broadcast).

Run: `pytest tests/audit_fixes/test_s_03_07_08_high_missed.py -v`
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


# ──────────────────────────────────────────────────────────────────────────
# S-03 — per-account `_last_bg_jobs_time`
# ──────────────────────────────────────────────────────────────────────────


def test_s_03_last_bg_jobs_time_is_per_account():
    """S-03: the bg-jobs throttle must be keyed by account, not a single
    shared float. Otherwise account A's "last run" silently throttles
    account B's run for 60s."""
    import app.api.routes_helpers as rh

    # The fix replaces the module-level float with a dict keyed by
    # oauth_account_id (or DB account_id, depending on the call site).
    assert hasattr(rh, "_last_bg_jobs_time_per_account"), (
        "S-03 leak: routes_helpers still uses a single global "
        "_last_bg_jobs_time float — bg jobs starve across accounts."
    )
    container = rh._last_bg_jobs_time_per_account
    assert isinstance(container, dict), (
        "S-03 leak: _last_bg_jobs_time_per_account must be a dict mapping "
        "account_id -> float."
    )

    # Verify isolation: setting account A's key doesn't affect account B's
    container.clear()
    container["account_A"] = 1.0
    assert container.get("account_B", 0.0) == 0.0


def test_s_03_throttle_helper_uses_per_account_key():
    """S-03: there should be a helper that returns whether the per-account
    throttle has elapsed, taking the account_id as input."""
    import app.api.routes_helpers as rh

    assert hasattr(rh, "should_run_bg_jobs"), (
        "S-03 leak: routes_helpers must expose a `should_run_bg_jobs"
        "(account_id, now)` helper that the routes can call. The legacy "
        "global comparison can't express per-account throttling."
    )

    rh._last_bg_jobs_time_per_account.clear()
    # First call for account A: throttle empty → should run
    assert rh.should_run_bg_jobs("account_A", now=100.0) is True
    # Concurrent call for account B with a fresh now: should also run
    # (independent throttle)
    assert rh.should_run_bg_jobs("account_B", now=100.5) is True
    # Second call for account A within 60s: throttled
    assert rh.should_run_bg_jobs("account_A", now=130.0) is False
    # Account B not affected by A's throttle
    assert rh.should_run_bg_jobs("account_B", now=130.0) is False
    # Account A after the window: should run again
    assert rh.should_run_bg_jobs("account_A", now=200.0) is True


# ──────────────────────────────────────────────────────────────────────────
# S-07 — bg thread emitters must be account-scoped
# ──────────────────────────────────────────────────────────────────────────


def test_s_07_bg_emitters_can_target_specific_account():
    """S-07: the websocket helpers used by bg threads (email_archived,
    email_deleted, email_updated) must accept an `account_id` parameter
    so the caller can pass the resolved id captured before thread.start()."""
    from app.api.websocket import (
        emit_email_archived,
        emit_email_deleted,
        emit_email_updated,
        emit_email_restored,
        emit_email_spam_changed,
    )

    for fn in (
        emit_email_archived,
        emit_email_deleted,
        emit_email_updated,
        emit_email_restored,
        emit_email_spam_changed,
    ):
        sig = inspect.signature(fn)
        assert "account_id" in sig.parameters, (
            f"S-07 leak: {fn.__name__} has no account_id parameter — "
            f"bg threads can't route to a specific account's room."
        )


def test_s_07_emit_email_archived_routes_to_account_when_id_provided():
    """S-07: when account_id is provided, the helper routes via
    emit_to_account instead of falling back to broadcast-prone
    _resolve_ws_room path."""
    from app.api import websocket as ws_module

    calls: list[tuple] = []

    def _fake_emit_to_account(event, data, account_id):
        calls.append((event, data, account_id))
        return True

    with patch.object(ws_module, "emit_to_account", side_effect=_fake_emit_to_account):
        ws_module.emit_email_archived("abc", account_id=42)

    assert len(calls) == 1
    event, data, account_id = calls[0]
    assert event == "email_archived"
    assert account_id == 42
    assert data["email_id"] == "abc"


def test_s_07_emit_email_deleted_routes_to_account_when_id_provided():
    from app.api import websocket as ws_module

    calls: list[tuple] = []

    def _fake_emit_to_account(event, data, account_id):
        calls.append((event, data, account_id))
        return True

    with patch.object(ws_module, "emit_to_account", side_effect=_fake_emit_to_account):
        ws_module.emit_email_deleted("xyz", account_id=99)

    assert len(calls) == 1
    event, data, account_id = calls[0]
    assert event == "email_deleted"
    assert account_id == 99
    assert data["email_id"] == "xyz"


def test_s_07_emit_email_updated_routes_to_account_when_id_provided():
    from app.api import websocket as ws_module

    calls: list[tuple] = []

    def _fake_emit_to_account(event, data, account_id):
        calls.append((event, data, account_id))
        return True

    with patch.object(ws_module, "emit_to_account", side_effect=_fake_emit_to_account):
        ws_module.emit_email_updated("abc", {"is_read": True}, account_id=7)

    assert len(calls) == 1
    event, data, account_id = calls[0]
    assert event == "email_updated"
    assert account_id == 7
    assert data["email_id"] == "abc"
    assert data["updates"] == {"is_read": True}


# ──────────────────────────────────────────────────────────────────────────
# S-08 — sync emits must be account-scoped
# ──────────────────────────────────────────────────────────────────────────


def test_s_08_emit_sync_progress_accepts_routing_kwarg():
    """S-08: the sync emitters need to be able to route to a specific
    account's room. Otherwise account A's sync_progress event leaks to
    account B's tab."""
    from app.api.websocket import emit_sync_progress

    sig = inspect.signature(emit_sync_progress)
    # Either takes account_id explicitly (it already does for the data
    # payload), or accepts a per-account routing knob.
    # In our fix, emit_sync_progress(account_id, status) routes via
    # emit_to_account internally.
    assert "account_id" in sig.parameters


def test_s_08_emit_sync_progress_routes_via_emit_to_account():
    """S-08: emit_sync_progress(account_id, status) must use
    emit_to_account so the event lands in that account's user room
    (not a global broadcast)."""
    from app.api import websocket as ws_module

    calls: list[tuple] = []

    def _fake_emit_to_account(event, data, account_id):
        calls.append((event, data, account_id))
        return True

    with patch.object(ws_module, "emit_to_account", side_effect=_fake_emit_to_account):
        ws_module.emit_sync_progress(account_id=42, status="success")

    assert len(calls) == 1
    event, data, account_id = calls[0]
    assert event == "sync_progress"
    assert account_id == 42
    assert data["account_id"] == 42
    assert data["status"] == "success"


def test_s_08_emit_new_email_accepts_account_id():
    """S-08: emit_new_email must accept an optional account_id so the sync
    thread can pass r.account_id rather than rely on the broken
    _resolve_ws_room path."""
    from app.api.websocket import emit_new_email

    sig = inspect.signature(emit_new_email)
    assert "account_id" in sig.parameters, (
        "S-08 leak: emit_new_email has no account_id parameter — sync "
        "thread can't route to the right user's room."
    )


def test_s_08_emit_new_email_routes_via_emit_to_account():
    from app.api import websocket as ws_module

    calls: list[tuple] = []

    def _fake_emit_to_account(event, data, account_id):
        calls.append((event, data, account_id))
        return True

    with patch.object(ws_module, "emit_to_account", side_effect=_fake_emit_to_account):
        ws_module.emit_new_email(
            {"email_id": "id-1", "sender": "x@y", "subject": "Hello"},
            account_id=42,
        )

    assert len(calls) == 1
    event, data, account_id = calls[0]
    assert event == "daemon_event"
    assert account_id == 42
    assert data.get("type") == "new_email"
    assert data.get("email_id") == "id-1"


def test_s_08_emit_sync_started_accepts_account_ids_and_targets_each():
    """S-08: emit_sync_started must fan-out to each account's room, not
    broadcast."""
    from app.api import websocket as ws_module

    calls: list[tuple] = []

    def _fake_emit_to_account(event, data, account_id):
        calls.append((event, data, account_id))
        return True

    with patch.object(ws_module, "emit_to_account", side_effect=_fake_emit_to_account):
        ws_module.emit_sync_started([1, 2, 3])

    # One emit per account, each scoped to that account's room
    assert {c[2] for c in calls} == {1, 2, 3}
    for ev, payload, _aid in calls:
        assert ev == "sync_started"
        assert payload["account_id"] == _aid
        assert payload["accounts"] == [_aid]
