# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix — the auto-trigger failure/exception branches emit a
``quickstep_failed`` WebSocket event, symmetric to the success branch's
``quickstep_fired``.

Before the fix, ``_apply_steps_to_snapshot`` only notified the frontend on
success; a failed (``report.success`` False) or raised step was log-only, so
the user never saw that a background rule had errored. Both branches now call
``_emit_quickstep_failed_event``.
"""
from __future__ import annotations

from app.quicksteps import auto_trigger


def _step(sid: str, name: str) -> dict:
    return {
        "id": sid,
        "name": name,
        "enabled": True,
        "autoEnabled": True,
        "firesOn": "received",
        "triggers": [{"type": "x"}],
        "actions": [{"type": "archive"}],
    }


def test_failure_branch_emits_quickstep_failed(monkeypatch):
    """report.success == False → emits a quickstep_failed event."""
    emitted: list[dict] = []

    class _Report:
        success = False
        error = "archive_failed"

    monkeypatch.setattr("app.quicksteps.engine.execute", lambda **kw: _Report())
    monkeypatch.setattr(auto_trigger, "_evaluate_triggers", lambda *a, **k: True)
    monkeypatch.setattr(
        auto_trigger, "_emit_quickstep_failed_event",
        lambda **kw: emitted.append(kw),
    )

    n = auto_trigger._apply_steps_to_snapshot(
        1, "email-1", object(), [_step("sX", "X")],
    )

    assert n == 1
    assert len(emitted) == 1
    assert emitted[0]["account_id"] == 1
    assert emitted[0]["step_name"] == "X"
    assert emitted[0]["email_id"] == "email-1"
    assert emitted[0]["error"] == "archive_failed"


def test_exception_branch_emits_quickstep_failed(monkeypatch):
    """engine.execute raising → emits a quickstep_failed event."""
    emitted: list[dict] = []

    def _boom(**kw):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.quicksteps.engine.execute", _boom)
    monkeypatch.setattr(auto_trigger, "_evaluate_triggers", lambda *a, **k: True)
    monkeypatch.setattr(
        auto_trigger, "_emit_quickstep_failed_event",
        lambda **kw: emitted.append(kw),
    )

    auto_trigger._apply_steps_to_snapshot(
        1, "email-1", object(), [_step("sX", "X")],
    )

    assert len(emitted) == 1
    assert emitted[0]["account_id"] == 1
    assert emitted[0]["step_name"] == "X"
    assert emitted[0]["email_id"] == "email-1"
    assert "boom" in emitted[0]["error"]


def test_failed_emit_payload_shape_and_truncation(monkeypatch):
    """_emit_quickstep_failed_event mirrors the fired emitter's plumbing:
    daemon_event / type quickstep_failed, account-scoped, sanitized error."""
    calls: list[tuple] = []

    import app.api.websocket as ws

    monkeypatch.setattr(
        ws, "emit_to_account",
        lambda event, data, account_id: calls.append((event, data, account_id)),
    )

    auto_trigger._emit_quickstep_failed_event(
        account_id=7,
        step_name="My Step",
        email_id="e-9",
        error="x" * 500,
    )

    assert len(calls) == 1
    event, data, account_id = calls[0]
    assert event == "daemon_event"
    assert account_id == 7
    assert data["type"] == "quickstep_failed"
    assert data["email_id"] == "e-9"
    assert data["payload"]["step_name"] == "My Step"
    # error truncated to keep the surfaced detail short
    assert len(data["payload"]["error"]) == 160


def test_failed_emit_noop_on_invalid_account(monkeypatch):
    """account_id <= 0 → never reaches the emitter (mirrors fired helper)."""
    calls: list = []
    import app.api.websocket as ws
    monkeypatch.setattr(
        ws, "emit_to_account",
        lambda *a, **k: calls.append(a),
    )

    auto_trigger._emit_quickstep_failed_event(
        account_id=0, step_name="S", email_id="e", error="boom",
    )
    auto_trigger._emit_quickstep_failed_event(
        account_id=-1, step_name="S", email_id="e", error="boom",
    )

    assert calls == []
