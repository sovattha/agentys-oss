# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the sent-side Quick Step flow.

The reminder-only ``follow_up`` action was removed 2026-05 — both follow-up
flavours ("Follow-up new thread" / "Follow-up existing thread") now generate
a snoozed draft via ``create_snoozed_followup_draft``. This file keeps the
generic sent-side coverage:
  - schema validation (firesOn field, cross-flow rejection, dead-action
    rejection for ``follow_up``)
  - trigger matcher ``is_new_thread``
  - ``run_auto_triggers_on_sent`` only fires ``firesOn="sent"`` rules

``create_snoozed_followup_draft`` is the sent-side cobaye throughout.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from app.quicksteps import auto_trigger, schema


def _step(
    *,
    actions,
    triggers=None,
    fires_on="received",
    auto_enabled=False,
    operator="AND",
):
    return {
        "id": str(uuid.uuid4()),
        "name": "test",
        "icon": None,
        "shortcut": None,
        "actions": actions,
        "enabled": True,
        "confirmBeforeRun": False,
        "autoEnabled": auto_enabled,
        "triggerOperator": operator,
        "triggers": triggers or [],
        "firesOn": fires_on,
    }


def _snoozed_draft_action():
    return {"type": "create_snoozed_followup_draft", "payload": {"body": "Hi", "delay_days": 7}}


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


class TestSchema:
    def test_create_snoozed_draft_validates_on_sent(self):
        cleaned = schema.validate_quick_step(_step(
            actions=[_snoozed_draft_action()],
            triggers=[{"type": "is_new_thread", "value": "true"}],
            fires_on="sent",
            auto_enabled=True,
        ))
        assert cleaned["actions"][0]["type"] == "create_snoozed_followup_draft"
        assert cleaned["firesOn"] == "sent"

    def test_follow_up_action_is_rejected(self):
        """The reminder-only ``follow_up`` action was removed — the schema
        must no longer accept it (an "unknown action type" rejection)."""
        with pytest.raises(schema.ValidationError):
            schema.validate_quick_step(_step(
                actions=[{"type": "follow_up", "payload": {"delay_days": 7, "nudge": "both"}}],
                triggers=[{"type": "is_new_thread", "value": "true"}],
                fires_on="sent",
                auto_enabled=True,
            ))

    def test_fires_on_sent_rejects_non_followup_actions(self):
        with pytest.raises(schema.ValidationError, match="firesOn='sent' Quick Steps only support"):
            schema.validate_quick_step(_step(
                actions=[{"type": "archive"}],
                triggers=[{"type": "is_new_thread", "value": "true"}],
                fires_on="sent",
                auto_enabled=True,
            ))

    def test_create_snoozed_draft_rejects_received_pairing(self):
        with pytest.raises(schema.ValidationError, match="firesOn='sent'"):
            schema.validate_quick_step(_step(
                actions=[_snoozed_draft_action()],
                triggers=[{"type": "is_new_thread", "value": "true"}],
                fires_on="received",
                auto_enabled=True,
            ))

    def test_fires_on_defaults_to_received(self):
        cleaned = schema.validate_quick_step({
            "id": str(uuid.uuid4()),
            "name": "x",
            "actions": [{"type": "archive"}],
            "triggers": [],
        })
        assert cleaned["firesOn"] == "received"

    def test_is_new_thread_trigger_accepted(self):
        cleaned = schema.validate_quick_step(_step(
            actions=[{"type": "archive"}],
            triggers=[{"type": "is_new_thread", "value": "true"}],
            auto_enabled=True,
        ))
        assert cleaned["triggers"][0]["type"] == "is_new_thread"


# --------------------------------------------------------------------------- #
# Trigger matchers
# --------------------------------------------------------------------------- #


@dataclass
class _Email:
    sender: str = ""
    subject: str = ""
    body: str = ""
    body_html: str = ""
    recipients: str = ""
    attachments_meta: str = ""
    id: str = ""
    thread_id: str = ""
    original_email_id: str = ""
    in_reply_to: str = ""
    references: str = ""


class TestTriggerMatchers:
    def test_is_new_thread_true_on_fresh_email(self):
        cond = {"type": "is_new_thread", "value": "true"}
        email = _Email(sender="me@x.com", subject="Project kickoff", body="hello")
        assert auto_trigger._match_condition(cond, email) is True

    def test_is_new_thread_false_on_reply_via_in_reply_to(self):
        cond = {"type": "is_new_thread", "value": "true"}
        email = _Email(sender="me@x.com", subject="Re: kickoff", body="thanks", in_reply_to="<prev@x>")
        assert auto_trigger._match_condition(cond, email) is False

    def test_is_new_thread_false_on_subject_re_prefix(self):
        cond = {"type": "is_new_thread", "value": "true"}
        email = _Email(sender="me@x.com", subject="Re: kickoff", body="thanks")
        assert auto_trigger._match_condition(cond, email) is False

    def test_is_new_thread_false_on_original_email_id(self):
        cond = {"type": "is_new_thread", "value": "true"}
        email = _Email(sender="me@x.com", subject="Update", body="ok", original_email_id="msg-prev")
        assert auto_trigger._match_condition(cond, email) is False


# --------------------------------------------------------------------------- #
# run_auto_triggers_on_sent
# --------------------------------------------------------------------------- #


class TestSentSideRunner:
    def test_only_fires_sent_rules(self):
        sent_rule = _step(
            actions=[_snoozed_draft_action()],
            triggers=[{"type": "is_new_thread", "value": "true"}],
            fires_on="sent", auto_enabled=True,
        )
        received_rule = _step(
            actions=[{"type": "archive"}],
            triggers=[{"type": "is_new_thread", "value": "true"}],
            fires_on="received", auto_enabled=True,
        )
        sent_email = _Email(sender="me@x.com", subject="Kickoff", body="here we go?", id="sent-1", thread_id="t-1")

        called = {"count": 0}

        def _fake_handler(_ctx, _payload):
            called["count"] += 1
            from app.quicksteps.types import ActionResult
            return ActionResult(ok=True)

        with patch("app.quicksteps.store.load_quick_steps", return_value=[sent_rule, received_rule]), \
             patch.dict(auto_trigger._SENT_ACTION_DISPATCH, {"create_snoozed_followup_draft": _fake_handler}, clear=True), \
             patch.object(auto_trigger, "_resolve_oauth_account_id", return_value=None):
            fired = auto_trigger.run_auto_triggers_on_sent(account_id=1, sent_email=sent_email)
        assert len(fired) == 1
        assert fired[0] == sent_rule["id"]
        assert called["count"] == 1

    def test_already_fired_hook_skips_step(self):
        sent_rule = _step(
            actions=[_snoozed_draft_action()],
            triggers=[{"type": "is_new_thread", "value": "true"}],
            fires_on="sent", auto_enabled=True,
        )
        sent_email = _Email(sender="me@x.com", subject="Kickoff", body="text", id="sent-1")

        called = {"count": 0}

        def _fake_handler(_ctx, _payload):
            called["count"] += 1
            from app.quicksteps.types import ActionResult
            return ActionResult(ok=True)

        with patch("app.quicksteps.store.load_quick_steps", return_value=[sent_rule]), \
             patch.dict(auto_trigger._SENT_ACTION_DISPATCH, {"create_snoozed_followup_draft": _fake_handler}, clear=True), \
             patch.object(auto_trigger, "_resolve_oauth_account_id", return_value=None):
            fired = auto_trigger.run_auto_triggers_on_sent(
                account_id=1,
                sent_email=sent_email,
                _already_fired=lambda step_id: step_id == sent_rule["id"],
            )
        assert fired == []
        assert called["count"] == 0

    def test_disabled_rule_skipped(self):
        disabled = _step(
            actions=[_snoozed_draft_action()],
            triggers=[{"type": "is_new_thread", "value": "true"}],
            fires_on="sent", auto_enabled=True,
        )
        disabled["enabled"] = False
        sent_email = _Email(id="sent-1", subject="x", body="?")

        with patch("app.quicksteps.store.load_quick_steps", return_value=[disabled]), \
             patch.object(auto_trigger, "_resolve_oauth_account_id", return_value=None):
            fired = auto_trigger.run_auto_triggers_on_sent(account_id=1, sent_email=sent_email)
        assert fired == []

    def test_zero_account_id_returns_empty(self):
        assert auto_trigger.run_auto_triggers_on_sent(account_id=0, sent_email=_Email()) == []
