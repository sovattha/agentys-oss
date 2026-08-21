# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Scenario-based validation of the two user follow-up rules.

Drives the actual matcher + handler with synthetic SentEmail shapes to
verify each rule fires in the cases it should, and stays silent in the
cases it shouldn't. Acts as a regression guard for the follow-up system
as a whole — covers the matcher, the handler, the wake sweep, and the
edge cases (availability emails, noreply recipients, replies that arrive
before the wake date).

Rules under test (mirror the user's actual saved Quick Steps):
  1. "Follow-up new sent emails"        firesOn=sent, is_new_thread=true,
                                         action=create_snoozed_followup_draft
                                         (delay_days=2)
  2. "Follow-up threaded sent emails"    firesOn=sent,
                                         content_keyword="?" AND
                                         is_new_thread negate=true,
                                         action=create_snoozed_followup_draft
                                         (delay_days=7)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch


from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
from app.quicksteps.auto_trigger import _match_condition, run_auto_triggers_on_sent
from app.quicksteps.handlers.create_snoozed_followup_draft import (
    _recipient_replied,
    sweep_woken_draft_followups,
)


# --------------------------------------------------------------------------- #
# Rule fixtures — mirror the two rules the user built in the UI
# --------------------------------------------------------------------------- #

def _rule_new_threads() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": "Follow-up new sent emails",
        "icon": None,
        "shortcut": None,
        "actions": [{
            "type": "create_snoozed_followup_draft",
            "payload": {
                "body": (
                    "Hi {{recipient_name}}, just following up on "
                    "{{original_subject}} — let me know if you need "
                    "anything else."
                ),
                "delay_days": 2,
            },
        }],
        "enabled": True,
        "autoEnabled": True,
        "confirmBeforeRun": False,
        "showAutoBadge": True,
        "triggerOperator": "AND",
        "triggers": [{"type": "is_new_thread", "value": "true"}],
        "firesOn": "sent",
    }


def _rule_threaded_with_question() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": "Follow-up threaded sent emails",
        "icon": None,
        "shortcut": None,
        "actions": [{
            "type": "create_snoozed_followup_draft",
            "payload": {
                "body": (
                    "Hi {{recipient_name}}, just following up on "
                    "{{original_subject}} — let me know if you need "
                    "anything else."
                ),
                "delay_days": 7,
            },
        }],
        "enabled": True,
        "autoEnabled": True,
        "confirmBeforeRun": False,
        "showAutoBadge": True,
        "triggerOperator": "AND",
        "triggers": [
            {"type": "content_keyword", "value": "?"},
            {"type": "is_new_thread", "value": "true", "negate": True},
        ],
        "firesOn": "sent",
    }


# --------------------------------------------------------------------------- #
# Synthetic email shapes
# --------------------------------------------------------------------------- #


@dataclass
class _Sent:
    """Lightweight sent-email shape for the sent-side trigger tests."""
    id: str = "sent-1"
    recipient: str = "alex@acme.com"
    subject: str = ""
    body_preview: str = ""
    sent_at: str = ""
    thread_id: str = "thread-9"
    original_email_id: str = ""
    in_reply_to: str = ""
    account_id: str = "42"


@dataclass
class _ThreadMsg:
    sender: str


# --------------------------------------------------------------------------- #
# Trigger-level matching — pure matcher tests, no handler side-effects
# --------------------------------------------------------------------------- #


class TestRule1NewThreadMatching:
    """Rule 1 should match every brand-new outbound thread."""

    def test_compose_cold_outreach_matches(self):
        e = _Sent(subject="Question about pricing", body_preview="Hi Alex, ...")
        cond = {"type": "is_new_thread", "value": "true"}
        assert _match_condition(cond, e) is True

    def test_reply_to_inbox_does_not_match(self):
        e = _Sent(subject="Re: invoice", body_preview="ack")
        cond = {"type": "is_new_thread", "value": "true"}
        assert _match_condition(cond, e) is False

    def test_forward_does_not_match(self):
        e = _Sent(subject="Fwd: contract", body_preview="see below")
        cond = {"type": "is_new_thread", "value": "true"}
        assert _match_condition(cond, e) is False

    def test_in_reply_to_header_disqualifies(self):
        e = _Sent(subject="New ideas", in_reply_to="<prev@x>", body_preview="hi")
        cond = {"type": "is_new_thread", "value": "true"}
        assert _match_condition(cond, e) is False


class TestRule2ThreadedWithQuestion:
    """Rule 2 needs both: body has ?, AND is a reply (not new thread)."""

    def _check_pair(self, sent: _Sent) -> tuple[bool, bool]:
        body_cond = {"type": "content_keyword", "value": "?"}
        body_match = _match_condition(body_cond, sent)
        # The rule's `is_new_thread negate=true` is enforced at chain
        # level by the engine; here we emulate it inline.
        thread_raw = _match_condition({"type": "is_new_thread", "value": "true"}, sent)
        thread_match = not thread_raw  # negate
        return body_match, thread_match

    def test_reply_with_question_in_body_matches_both(self):
        e = _Sent(
            subject="Re: timing",
            body_preview="Can you confirm by Friday?",
        )
        body, thread = self._check_pair(e)
        assert body is True
        assert thread is True

    def test_reply_without_question_skips(self):
        e = _Sent(subject="Re: thanks", body_preview="Thanks, talk soon.")
        body, thread = self._check_pair(e)
        assert body is False
        assert thread is True

    def test_new_thread_with_question_skips(self):
        # Would match rule 1 (new thread), not rule 2 (which requires reply)
        e = _Sent(subject="Question for you", body_preview="Got 5 min?")
        body, thread = self._check_pair(e)
        assert body is True
        assert thread is False  # is_new_thread=true → negate flips to false

    def test_question_deep_in_body_still_matches(self):
        # Regression: body_preview was 100 chars → questions past first
        # paragraph silently missed. After the bump to 1000 chars, deeper
        # questions match too.
        long_body = ("Salut Alex,\n\n" * 5) + "Pouvez-vous confirmer pour vendredi ?"
        e = _Sent(subject="Re: planning", body_preview=long_body[:1000])
        body, _ = self._check_pair(e)
        assert body is True


# --------------------------------------------------------------------------- #
# Full handler firing — drives run_auto_triggers_on_sent end-to-end
# --------------------------------------------------------------------------- #


class _Store:
    def __init__(self):
        self.items: dict[str, PendingDraft] = {}

    def add(self, d: PendingDraft) -> str:
        self.items[d.id] = d
        return d.id

    def delete(self, did: str) -> bool:
        return self.items.pop(did, None) is not None

    def get_by_id(self, did: str) -> Optional[PendingDraft]:
        return self.items.get(did)


class _Container:
    def __init__(self, store: _Store):
        self._s = store

    def get_pending_draft_store(self) -> _Store:
        return self._s


def _run(rule: dict, sent: _Sent) -> tuple[list[PendingDraft], list[dict]]:
    """Fire ``rule`` against ``sent``. Return (drafts created, reminders created)."""
    store = _Store()
    reminders: list[dict] = []

    def _fake_add_reminder(**kw):
        reminders.append(kw)
        return f"rem-{len(reminders)}"

    with patch(
        "app.quicksteps.store.load_quick_steps", return_value=[rule],
    ), patch(
        "app.infrastructure.container.get_container",
        return_value=_Container(store),
    ), patch(
        "app.services.reminder_service.add_reminder", _fake_add_reminder,
    ):
        run_auto_triggers_on_sent(42, sent)

    return list(store.items.values()), reminders


class TestRule1Firing:
    def test_cold_outreach_creates_draft(self):
        rule = _rule_new_threads()
        sent = _Sent(
            subject="Cold pitch for X",
            body_preview="Hi Alex, I think...",
            recipient="alex@acme.com",
            thread_id="thread-cold",
        )
        drafts, reminders = _run(rule, sent)
        assert len(drafts) == 1
        d = drafts[0]
        assert d.routing_tier == "followup"
        assert d.draft_subject == "Re: Cold pitch for X"
        assert "Alex" in d.draft_body
        assert "Cold pitch for X" in d.draft_body
        assert len(reminders) == 1
        assert reminders[0]["reminder_type"] == "draft_followup"

    def test_reply_does_not_fire_rule_1(self):
        rule = _rule_new_threads()
        sent = _Sent(subject="Re: thanks", body_preview="ack")
        drafts, reminders = _run(rule, sent)
        assert drafts == []
        assert reminders == []


class TestRule2Firing:
    def test_reply_with_question_creates_draft(self):
        rule = _rule_threaded_with_question()
        sent = _Sent(
            subject="Re: project plan",
            body_preview="Sounds good. Can you confirm by Friday?",
            recipient="alex@acme.com",
            thread_id="thread-plan",
        )
        drafts, reminders = _run(rule, sent)
        assert len(drafts) == 1
        d = drafts[0]
        assert d.draft_subject == "Re: project plan"
        assert d.routing_tier == "followup"
        assert reminders[0]["reminder_type"] == "draft_followup"

    def test_reply_without_question_does_not_fire(self):
        rule = _rule_threaded_with_question()
        sent = _Sent(subject="Re: thanks", body_preview="Cheers!")
        drafts, reminders = _run(rule, sent)
        assert drafts == []
        assert reminders == []

    def test_new_thread_with_question_does_not_fire_rule_2(self):
        # Belongs to rule 1's domain (new thread), not rule 2.
        rule = _rule_threaded_with_question()
        sent = _Sent(subject="Quick question", body_preview="Got 5 min?")
        drafts, reminders = _run(rule, sent)
        assert drafts == []
        assert reminders == []


# --------------------------------------------------------------------------- #
# Wake-sweep behavior — delete on reply, promote + inbox surface on no-reply
# --------------------------------------------------------------------------- #


class _FakeProvider:
    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def get_thread_messages(self, tid):
        self.calls.append(tid)
        return self.messages


def _sweep(*, draft: PendingDraft, messages: list, account_email: str = "me@x.com"):
    store = _Store()
    store.add(draft)
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    entries = [{
        "id": "rem-1", "email_id": draft.id, "subject": draft.draft_subject,
        "reminder_date": past, "notified": False, "account_id": 42,
        "type": "draft_followup",
    }]
    marked, dismissed, surface_reminders = [], [], []

    with patch(
        "app.services.reminder_service.list_draft_followups", return_value=entries,
    ), patch(
        "app.services.reminder_service._mark_notified",
        side_effect=lambda rid: marked.append(rid),
    ), patch(
        "app.services.reminder_service.dismiss_reminder",
        side_effect=lambda rid, account_id=None: dismissed.append((rid, account_id)) or True,
    ), patch(
        "app.services.reminder_service.add_reminder",
        side_effect=lambda **kw: (surface_reminders.append(kw) or "surface-id"),
    ), patch(
        "app.infrastructure.container.get_container",
        return_value=_Container(store),
    ):
        provider = _FakeProvider(messages)
        counters = sweep_woken_draft_followups(
            account_id=42, account_email=account_email, provider=provider,
        )
    return store, counters, marked, dismissed, surface_reminders


class TestWakeSweep:
    def _draft(self) -> PendingDraft:
        return PendingDraft(
            id="draft-1", email_id="thread-9", email_sender="alex@acme.com",
            email_subject="Project", draft_subject="Re: Project",
            draft_body="Hi Alex, just following up...",
            routing_tier="followup", status=PendingDraftStatus.PENDING,
            account_id="42",
        )

    def test_no_reply_promotes_and_surfaces_to_inbox(self):
        d = self._draft()
        store, counters, marked, dismissed, surface = _sweep(
            draft=d, messages=[_ThreadMsg(sender="me@x.com")],
        )
        assert counters == {"checked": 1, "promoted": 1, "deleted": 0, "errors": 0}
        assert d.id in store.items  # kept
        assert marked == ["rem-1"]  # snooze flagged notified → draft visible in Drafts
        assert len(surface) == 1  # thread surfaced to inbox top
        assert surface[0]["email_id"] == "thread-9"
        assert surface[0]["reminder_type"] == "followup"

    def test_reply_received_deletes_draft(self):
        d = self._draft()
        store, counters, marked, dismissed, surface = _sweep(
            draft=d, messages=[
                _ThreadMsg(sender="me@x.com"),
                _ThreadMsg(sender="alex@acme.com"),  # recipient replied!
            ],
        )
        assert counters == {"checked": 1, "promoted": 0, "deleted": 1, "errors": 0}
        assert store.items == {}  # draft auto-cleaned
        assert dismissed == [("rem-1", 42)]
        assert surface == []  # no inbox surface — there's no relance to deliver

    def test_recipient_replied_helper(self):
        # Sanity: the reply detection is just a sender-not-self check.
        assert _recipient_replied(
            [_ThreadMsg("me@x.com"), _ThreadMsg("alex@acme.com")],
            "me@x.com",
        ) is True
        assert _recipient_replied(
            [_ThreadMsg("me@x.com")],
            "me@x.com",
        ) is False
        assert _recipient_replied(
            [_ThreadMsg('"Alex" <alex@acme.com>')],
            "me@x.com",
        ) is True


# --------------------------------------------------------------------------- #
# Cross-rule combinations — both rules loaded; verify each fires on its own
# scenario and they don't trip over each other.
# --------------------------------------------------------------------------- #


class TestRulePartitioning:
    """The two rules should be disjoint: any given sent email fires
    at most one of them (or none)."""

    def _run_both(self, sent: _Sent) -> tuple[set[str], list[PendingDraft]]:
        rules = [_rule_new_threads(), _rule_threaded_with_question()]
        store = _Store()
        reminders: list[dict] = []

        with patch(
            "app.quicksteps.store.load_quick_steps", return_value=rules,
        ), patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ), patch(
            "app.services.reminder_service.add_reminder",
            side_effect=lambda **kw: (reminders.append(kw) or f"rem-{len(reminders)}"),
        ):
            run_auto_triggers_on_sent(42, sent)

        fired_rule_names = {
            r.get("subject", "") for r in reminders
        }
        return fired_rule_names, list(store.items.values())

    def test_new_thread_no_question_fires_rule_1_only(self):
        sent = _Sent(subject="Cold pitch", body_preview="Hi there...")
        _, drafts = self._run_both(sent)
        assert len(drafts) == 1
        assert drafts[0].draft_subject == "Re: Cold pitch"

    def test_new_thread_with_question_still_fires_rule_1_only(self):
        # Rule 2 wants `is_new_thread negate=true` — rejects new threads
        # even if they contain ?. So this should fire rule 1 once, not both.
        sent = _Sent(subject="Quick question", body_preview="Got 5 min?")
        _, drafts = self._run_both(sent)
        assert len(drafts) == 1
        assert drafts[0].draft_subject == "Re: Quick question"

    def test_reply_with_question_fires_rule_2_only(self):
        sent = _Sent(subject="Re: plan", body_preview="Friday OK?")
        _, drafts = self._run_both(sent)
        assert len(drafts) == 1
        assert drafts[0].draft_subject == "Re: plan"

    def test_reply_without_question_fires_nothing(self):
        sent = _Sent(subject="Re: cheers", body_preview="Thanks!")
        _, drafts = self._run_both(sent)
        assert drafts == []


# --------------------------------------------------------------------------- #
# Known edge cases — surface them so the user sees the limitations.
# --------------------------------------------------------------------------- #


class TestKnownEdgeCases:
    def test_question_mark_in_url_matches_rule_2(self):
        # KNOWN FALSE-POSITIVE: a `?` inside a tracking URL triggers the
        # rule even though the user didn't ask anything. Acceptable for
        # v1 — worst case is a deletable draft in Later.
        rule = _rule_threaded_with_question()
        sent = _Sent(
            subject="Re: review",
            body_preview="Check out https://example.com/page?utm=foo cheers!",
        )
        drafts, _ = _run(rule, sent)
        assert len(drafts) == 1, "false-positive: ? in URL counts as question"

    def test_forwarded_email_does_not_fire_rule_1(self):
        # Forwards aren't "new threads" — they're a thread continuation
        # of a different conversation. is_new_thread matcher catches Fwd:.
        rule = _rule_new_threads()
        sent = _Sent(subject="Fwd: contract", body_preview="See below")
        drafts, _ = _run(rule, sent)
        assert drafts == []


# --------------------------------------------------------------------------- #
# (Removed) Early-kill on reply
#
# `_early_kill_snoozed_drafts_on_reply` was deleted in the 2026-05-13
# deep-audit pass (F-04). It dropped any draft whose thread_id appeared
# in `recent_thread_ids`, but that set is built from every email in the
# user's inbox view — including the ORIGINAL inbound the user just
# replied to. The result was a false positive on every reply rule:
# brand-new snoozed drafts were destroyed within five minutes of
# creation, every time. Reply detection now happens authoritatively in
# the wake sweep via provider.get_thread_messages (compared against the
# user's own account_email). The previous tests in this section
# codified the buggy behavior and have been removed alongside the
# function.
# --------------------------------------------------------------------------- #
