# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression: prevent double-fire of `firesOn=sent` Quick Steps under a
concurrent-caller race.

Before the fix, the in-memory dedup dict ``_sent_quickstep_fired`` was
populated by the *caller* of ``run_auto_triggers_on_sent`` AFTER the call
returned. Two callers running concurrently for the same sent_id (the
immediate post-send hook racing the scheduler tick) both passed their
``_already_fired`` check, both fired the action, and the user saw two
identical ``quickstep_fired`` toasts in the bottom-right.

The fix moves the marking inline: ``run_auto_triggers_on_sent`` now
accepts a ``_mark_fired`` callback and invokes it BEFORE running the
action handlers. The contract verified here is exactly that ordering.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from unittest.mock import patch

from app.quicksteps import auto_trigger
from app.quicksteps.types import ActionResult


@dataclass
class _SentEmail:
    recipient: str = "alex@acme.com"
    subject: str = "Project kickoff"
    thread_id: str = "thread-1"
    id: str = "sent-abc"
    body_preview: str = ""


def _step(step_id: str):
    return {
        "id": step_id,
        "name": "test-step",
        "actions": [{"type": "create_snoozed_followup_draft", "payload": {"body": "Hi"}}],
        "enabled": True,
        "autoEnabled": True,
        "firesOn": "sent",
        "triggers": [{"type": "is_new_thread", "value": "true"}],
        "triggerOperator": "AND",
    }


def test_mark_fired_called_before_handler():
    """``_mark_fired`` must run before the action handler so a concurrent
    caller checking ``_already_fired`` sees the step as claimed."""
    step_id = str(uuid.uuid4())
    call_order: list[str] = []

    def fake_handler(ctx, payload):
        call_order.append("handler")
        return ActionResult(ok=True)

    def fake_mark(sid):
        call_order.append(f"mark:{sid}")

    with (
        patch("app.quicksteps.store.load_quick_steps", return_value=[_step(step_id)]),
        patch.object(auto_trigger, "_evaluate_triggers", return_value=True),
        patch.dict(auto_trigger._SENT_ACTION_DISPATCH, {"create_snoozed_followup_draft": fake_handler}, clear=False),
    ):
        fired = auto_trigger.run_auto_triggers_on_sent(
            account_id=1,
            sent_email=_SentEmail(),
            _mark_fired=fake_mark,
        )

    assert fired == [step_id]
    assert call_order == [f"mark:{step_id}", "handler"], (
        f"mark must fire before handler; got {call_order}"
    )


def test_concurrent_callers_only_fire_once():
    """The real race: two threads enter ``run_auto_triggers_on_sent`` for
    the same sent_id simultaneously. With production's lock-protected
    check-and-set (``_sent_quickstep_fired_lock`` in quicksteps_scheduler.py),
    exactly one wins the gate and the handler runs once.

    Audit regressions (2026-05-18 batch5) F-04: the previous body of this
    test ran both callers sequentially in one thread — caller 1 completed
    (mark + handler) before caller 2 entered. The test would have passed
    even if the fix moved marking back to AFTER the handler. This rewrite
    uses ``threading.Barrier(2)`` so both threads hit the gate at the same
    instant, faithfully reproducing the immediate-hook + scheduler-tick race.
    """
    step_id = str(uuid.uuid4())
    handler_calls: list[int] = []
    handler_lock = threading.Lock()

    def fake_handler(ctx, payload):
        # Hold the lock so we can detect double-fire under any interleaving.
        with handler_lock:
            handler_calls.append(1)
        return ActionResult(ok=True)

    # Mirror production's lock-protected dedup set (quicksteps_scheduler.py:
    # `_sent_quickstep_fired` + `_sent_quickstep_fired_lock`).
    fired_set: set[str] = set()
    fired_lock = threading.Lock()

    def already_fired(sid):
        with fired_lock:
            return sid in fired_set

    def mark_fired(sid):
        with fired_lock:
            fired_set.add(sid)

    barrier = threading.Barrier(2)
    results: list[list[str]] = [[], []]

    def caller(slot: int):
        # Pre-barrier work: patches are entered once in main thread, so each
        # caller just synchronises and dives in.
        barrier.wait(timeout=5.0)
        results[slot] = auto_trigger.run_auto_triggers_on_sent(
            account_id=1,
            sent_email=_SentEmail(),
            _already_fired=already_fired,
            _mark_fired=mark_fired,
        )

    with (
        patch("app.quicksteps.store.load_quick_steps", return_value=[_step(step_id)]),
        patch.object(auto_trigger, "_evaluate_triggers", return_value=True),
        patch.dict(auto_trigger._SENT_ACTION_DISPATCH, {"create_snoozed_followup_draft": fake_handler}, clear=False),
    ):
        t1 = threading.Thread(target=caller, args=(0,), daemon=True)
        t2 = threading.Thread(target=caller, args=(1,), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)

    fired_count = sum(1 for r in results if r == [step_id])
    skipped_count = sum(1 for r in results if r == [])
    assert fired_count == 1, (
        f"exactly one thread must fire the step; got {fired_count} firers, results={results}"
    )
    assert skipped_count == 1, (
        f"exactly one thread must see the step pre-claimed; got {skipped_count} skippers, results={results}"
    )
    assert handler_calls == [1], (
        f"handler must run exactly once across concurrent callers; got {len(handler_calls)} calls"
    )
