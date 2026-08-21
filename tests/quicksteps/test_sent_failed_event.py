# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit e2e 2026-06-10 B-02 : le chemin sent doit émettre ``quickstep_failed``.

Avant le fix, ``run_auto_triggers_on_sent`` loggait l'échec d'une action en
warning mais — contrairement au chemin received (``_run_steps_on_email``) —
n'émettait AUCUN événement d'échec. Le claim d'idempotence ayant déjà eu lieu
(volontaire, course immediate-hook/scheduler), l'échec réel d'un brouillon de
relance 🔁 n'était ni retenté ni visible : l'utilisateur croyait sa relance
armée.

Contrat vérifié ici :
- échec réel (store/reminder error, exception handler) → 1 événement failed ;
- skip de configuration voulu (no-reply, corps vide…) → AUCUN événement ;
- succès → aucun événement failed (parité avec l'existant).
Le claim n'est PAS dé-marqué sur échec — on ne rouvre pas la course 2026-05-17.
"""
from __future__ import annotations

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


def _run_with_handler(handler):
    step_id = str(uuid.uuid4())
    with (
        patch("app.quicksteps.store.load_quick_steps", return_value=[_step(step_id)]),
        patch.object(auto_trigger, "_evaluate_triggers", return_value=True),
        patch.dict(
            auto_trigger._SENT_ACTION_DISPATCH,
            {"create_snoozed_followup_draft": handler},
            clear=False,
        ),
        patch.object(auto_trigger, "_emit_quickstep_failed_event") as emit_failed,
        patch.object(auto_trigger, "_emit_quickstep_fired_event"),
    ):
        fired = auto_trigger.run_auto_triggers_on_sent(
            account_id=1,
            sent_email=_SentEmail(),
        )
    return fired, emit_failed, step_id


def test_store_error_emits_failed_event():
    def failing_handler(ctx, payload):
        return ActionResult(ok=False, error="snoozed_draft_store_error: disk full")

    fired, emit_failed, step_id = _run_with_handler(failing_handler)

    emit_failed.assert_called_once()
    kwargs = emit_failed.call_args.kwargs
    assert kwargs["account_id"] == 1
    assert kwargs["step_name"] == "test-step"
    assert kwargs["email_id"] == "sent-abc"
    assert "snoozed_draft_store_error" in kwargs["error"]
    # Le step reste claimé (pas de dé-claim) : il figure dans la liste fired.
    assert fired == [step_id]


def test_benign_config_skip_does_not_emit():
    def skipping_handler(ctx, payload):
        return ActionResult(ok=False, error="snoozed_draft_noreply_recipient")

    _, emit_failed, _ = _run_with_handler(skipping_handler)

    emit_failed.assert_not_called()


def test_handler_crash_emits_failed_event():
    def crashing_handler(ctx, payload):
        raise RuntimeError("boom")

    _, emit_failed, _ = _run_with_handler(crashing_handler)

    emit_failed.assert_called_once()
    assert "boom" in emit_failed.call_args.kwargs["error"]


def test_success_does_not_emit_failed():
    def ok_handler(ctx, payload):
        return ActionResult(ok=True)

    _, emit_failed, _ = _run_with_handler(ok_handler)

    emit_failed.assert_not_called()
