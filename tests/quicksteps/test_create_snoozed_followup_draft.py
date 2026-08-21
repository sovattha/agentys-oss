# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the `create_snoozed_followup_draft` Quick Step action.

Covers:
  - schema validation (allowlist, payload, firesOn pairing, sent-action gate)
  - handler creates PendingDraft + reminder with correct delay/account/tier
  - handler renders {{recipient_name}}, {{recipient_first_name}} +
    {{original_subject}} placeholders
  - handler rolls back the PendingDraft if reminder creation fails
  - wake-time sweep deletes draft when recipient replied,
    promotes (marks notified) when no reply, no-ops when nothing is due
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

import pytest

from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
from app.quicksteps import schema
from app.quicksteps.handlers.create_snoozed_followup_draft import (
    _html_to_text,
    _humanise_recipient,
    _recipient_replied,
    _render_body,
    handle_create_snoozed_followup_draft,
    sweep_woken_draft_followups,
)
from app.quicksteps.types import ExecutionContext


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _step(*, actions, triggers=None, fires_on="sent", auto_enabled=True):
    return {
        "id": str(uuid.uuid4()),
        "name": "snoozed-draft",
        "icon": None,
        "shortcut": None,
        "actions": actions,
        "enabled": True,
        "confirmBeforeRun": False,
        "autoEnabled": auto_enabled,
        "triggerOperator": "AND",
        "triggers": triggers or [{"type": "is_new_thread", "value": "true"}],
        "firesOn": fires_on,
    }


@dataclass
class _SentEmail:
    recipient: str = "alex.doe@acme.com"
    subject: str = "Project kickoff"
    thread_id: str = "thread-9"
    id: str = "sent-1"
    body_preview: str = ""


@dataclass
class _ThreadMsg:
    sender: str


class _InMemoryStore:
    """Minimal PendingDraft store double for handler tests.

    Mirrors the surface ``handle_create_snoozed_followup_draft`` and
    ``sweep_woken_draft_followups`` actually exercise: ``add``, ``delete``,
    ``get_by_id``. Avoids the singleton + disk-persist side effects of the
    real ``InMemoryPendingDraftStore``.
    """
    def __init__(self):
        self.items: dict[str, PendingDraft] = {}

    def add(self, draft: PendingDraft) -> str:
        self.items[draft.id] = draft
        return draft.id

    def delete(self, draft_id: str) -> bool:
        return self.items.pop(draft_id, None) is not None

    def get_by_id(self, draft_id: str) -> Optional[PendingDraft]:
        return self.items.get(draft_id)


class _Container:
    def __init__(self, store):
        self._store = store

    def get_pending_draft_store(self):
        return self._store


def _ctx(**overrides) -> ExecutionContext:
    defaults = dict(
        provider=None,
        account_id=42,
        account_email="me@x.com",
        account_display_name="Me",
        email=_SentEmail(),
        email_id="sent-1",
        raw_id="sent-1",
        template_vars={},
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


class TestSchema:
    def test_action_validates_with_sent_firing(self):
        cleaned = schema.validate_quick_step(_step(
            actions=[{
                "type": "create_snoozed_followup_draft",
                "payload": {"body": "Hi {{recipient_name}}, ping?", "delay_days": 7},
            }],
        ))
        assert cleaned["actions"][0]["payload"]["delay_days"] == 7
        assert cleaned["actions"][0]["payload"]["body"] == (
            "Hi {{recipient_name}}, ping?"
        )

    def test_default_delay_is_seven(self):
        cleaned = schema.validate_quick_step(_step(
            actions=[{
                "type": "create_snoozed_followup_draft",
                "payload": {"body": "Hi"},
            }],
        ))
        assert cleaned["actions"][0]["payload"]["delay_days"] == 7

    def test_rejects_empty_body(self):
        with pytest.raises(schema.ValidationError, match="cannot be empty"):
            schema.validate_quick_step(_step(
                actions=[{
                    "type": "create_snoozed_followup_draft",
                    "payload": {"body": "   ", "delay_days": 7},
                }],
            ))

    def test_rejects_out_of_range_delay(self):
        with pytest.raises(schema.ValidationError, match="between 1 and"):
            schema.validate_quick_step(_step(
                actions=[{
                    "type": "create_snoozed_followup_draft",
                    "payload": {"body": "Hi", "delay_days": 0},
                }],
            ))
        with pytest.raises(schema.ValidationError, match="between 1 and"):
            schema.validate_quick_step(_step(
                actions=[{
                    "type": "create_snoozed_followup_draft",
                    "payload": {"body": "Hi", "delay_days": 999},
                }],
            ))

    def test_rejects_received_pairing(self):
        with pytest.raises(schema.ValidationError, match="requires firesOn='sent'"):
            schema.validate_quick_step(_step(
                actions=[{
                    "type": "create_snoozed_followup_draft",
                    "payload": {"body": "Hi", "delay_days": 7},
                }],
                fires_on="received",
            ))

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class TestHelpers:
    def test_humanise_recipient_basic(self):
        assert _humanise_recipient("alex.doe@acme.com") == "Alex Doe"

    def test_humanise_recipient_plus_separator(self):
        assert _humanise_recipient("bob+work@example.com") == "Bob Work"

    def test_humanise_recipient_single_token(self):
        assert _humanise_recipient("support@stripe.com") == "Support"

    def test_humanise_recipient_empty(self):
        assert _humanise_recipient("") == ""

    def test_render_body_substitutes_both_slots(self):
        rendered = _render_body(
            "Hi {{recipient_name}}, re: {{original_subject}} — any news?",
            recipient_addr="alex.doe@acme.com",
            original_subject="Q3 plan",
        )
        assert rendered == "Hi Alex Doe, re: Q3 plan — any news?"

    def test_render_body_substitutes_first_name_slot(self):
        rendered = _render_body(
            "Hi {{recipient_first_name}}, any news on {{original_subject}}?",
            recipient_addr="alex.doe@acme.com",
            original_subject="Q3 plan",
        )
        # First-name slot resolves to the first token of the humanised name,
        # leaving the full-name slot untouched elsewhere.
        assert rendered == "Hi Alex, any news on Q3 plan?"

    def test_render_body_first_name_single_token_recipient(self):
        # support@stripe.com → "Support"; first name is the whole token.
        rendered = _render_body(
            "Hi {{recipient_first_name}}",
            recipient_addr="support@stripe.com",
            original_subject="x",
        )
        assert rendered == "Hi Support"

    def test_render_body_both_recipient_slots_coexist(self):
        # The longer alternative must win — {{recipient_first_name}} is not
        # clobbered by the {{recipient_name}} prefix match.
        rendered = _render_body(
            "{{recipient_name}} / {{recipient_first_name}}",
            recipient_addr="alex.doe@acme.com",
            original_subject="x",
        )
        assert rendered == "Alex Doe / Alex"

    def test_render_body_preserves_unknown_braces(self):
        # Unknown placeholders are left intact (regex only matches the two
        # allowed names).
        rendered = _render_body(
            "Hi {{recipient_name}} - your tracking is {shipping_id}",
            recipient_addr="alex@acme.com",
            original_subject="x",
        )
        assert rendered == "Hi Alex - your tracking is {shipping_id}"

    def test_recipient_replied_detects_external_sender(self):
        msgs = [
            _ThreadMsg(sender="me@x.com"),
            _ThreadMsg(sender='"Alex" <alex@acme.com>'),
        ]
        assert _recipient_replied(msgs, "me@x.com") is True

    def test_recipient_replied_false_when_only_self(self):
        msgs = [_ThreadMsg(sender="me@x.com")]
        assert _recipient_replied(msgs, "me@x.com") is False

    def test_recipient_replied_false_on_empty_input(self):
        assert _recipient_replied([], "me@x.com") is False
        assert _recipient_replied([_ThreadMsg(sender="x")], "") is False


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #


class TestHandler:
    def test_creates_pending_draft_and_reminder(self):
        store = _InMemoryStore()
        captured = {}

        def _fake_add_reminder(
            *, email_id, subject, reminder_date_iso, account_id, reminder_type,
        ):
            captured.update(
                email_id=email_id, subject=subject,
                reminder_date_iso=reminder_date_iso,
                account_id=account_id, reminder_type=reminder_type,
            )
            return "rem-id-1"

        with patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ), patch(
            "app.services.reminder_service.add_reminder", _fake_add_reminder,
        ):
            result = handle_create_snoozed_followup_draft(
                _ctx(),
                {
                    "body": "Hi {{recipient_name}}, following up on {{original_subject}}",
                    "delay_days": 7,
                },
            )

        assert result.ok
        # PendingDraft persisted with the followup tier
        assert len(store.items) == 1
        draft = next(iter(store.items.values()))
        assert draft.routing_tier == "followup"
        assert draft.status == PendingDraftStatus.PENDING
        assert draft.account_id == "42"
        assert draft.email_id == "thread-9"  # uses thread_id, not raw_id
        assert draft.draft_subject == "Re: Project kickoff"
        assert draft.draft_body == "Hi Alex Doe, following up on Project kickoff"
        # email_sender must be the recipient (the conversation partner),
        # not the user's address — otherwise `_filter_self_sent_drafts`
        # in routes_helpers.py would hide it.
        assert draft.email_sender == "alex.doe@acme.com"

        # Reminder typed and dated correctly
        assert captured["reminder_type"] == "draft_followup"
        assert captured["email_id"] == draft.id
        assert captured["account_id"] == 42
        wake = datetime.fromisoformat(captured["reminder_date_iso"])
        delta = wake - datetime.now(timezone.utc)
        assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)

        # Artifact surfaces the ids for downstream consumers
        assert result.artifact["pending_draft_id"] == draft.id
        assert result.artifact["reminder_id"] == "rem-id-1"
        assert result.artifact["delay_days"] == 7

    def test_sets_followup_emoji_marker(self):
        """The follow-up draft carries 🔁 on itself — NOT inherited from the
        sent email row (a sibling `mark_with_emoji` action races send-time
        persistence and returns email_not_found). This is what renders the
        circular-arrow chip on the Drafts row (PendingDraftList.tsx)."""
        store = _InMemoryStore()
        with patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ), patch(
            "app.services.reminder_service.add_reminder",
            return_value="rem-id-1",
        ):
            result = handle_create_snoozed_followup_draft(
                _ctx(), {"body": "Hi {{recipient_name}}", "delay_days": 7},
            )

        assert result.ok
        draft = next(iter(store.items.values()))
        assert draft.emoji_marker == {"emoji": "🔁"}
        # Survives the store's JSON persistence round-trip…
        assert (
            PendingDraft.from_dict(draft.to_dict()).emoji_marker
            == {"emoji": "🔁"}
        )
        # …and rides the lightweight list payload the Drafts panel reads.
        assert draft.to_dict_summary()["emoji_marker"] == {"emoji": "🔁"}

    def test_rejects_missing_recipient(self):
        store = _InMemoryStore()
        with patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ):
            result = handle_create_snoozed_followup_draft(
                _ctx(email=_SentEmail(recipient="")),
                {"body": "Hi", "delay_days": 7},
            )
        assert not result.ok
        assert result.error == "snoozed_draft_missing_recipient"
        assert store.items == {}

    def test_rejects_empty_rendered_body(self):
        store = _InMemoryStore()
        with patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ):
            result = handle_create_snoozed_followup_draft(
                _ctx(),
                {"body": "   ", "delay_days": 7},
            )
        assert not result.ok
        assert result.error == "snoozed_draft_empty_body"

    def test_rolls_back_draft_when_reminder_fails(self):
        store = _InMemoryStore()

        def _boom(**_kw):
            raise RuntimeError("disk full")

        with patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ), patch(
            "app.services.reminder_service.add_reminder", _boom,
        ):
            result = handle_create_snoozed_followup_draft(
                _ctx(),
                {"body": "Hi {{recipient_name}}", "delay_days": 3},
            )

        assert not result.ok
        assert "snoozed_draft_reminder_error" in result.error
        # Critically, the draft was rolled back — no half-applied state.
        assert store.items == {}


# --------------------------------------------------------------------------- #
# Wake-time sweep
# --------------------------------------------------------------------------- #


class _FakeProvider:
    def __init__(self, *, thread_messages=None, raises=False):
        self._messages = thread_messages or []
        self._raises = raises
        self.calls: list[str] = []

    def get_thread_messages(self, thread_id):
        self.calls.append(thread_id)
        if self._raises:
            raise RuntimeError("provider down")
        return self._messages


def _seed_draft(store, *, draft_id="draft-1", thread_id="thread-9"):
    draft = PendingDraft(
        id=draft_id,
        email_id=thread_id,
        email_sender="me@x.com",
        draft_subject="Re: Test",
        draft_body="follow up",
        routing_tier="followup",
        status=PendingDraftStatus.PENDING,
        account_id="42",
    )
    store.add(draft)
    return draft


class TestSweep:
    def test_deletes_draft_when_recipient_replied(self):
        store = _InMemoryStore()
        draft = _seed_draft(store)
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        entries = [{
            "id": "rem-1",
            "email_id": draft.id,
            "subject": "Re: Test",
            "reminder_date": past,
            "notified": False,
            "account_id": 42,
            "type": "draft_followup",
        }]
        marked, dismissed = [], []

        provider = _FakeProvider(thread_messages=[
            _ThreadMsg(sender="me@x.com"),
            _ThreadMsg(sender="alex@acme.com"),  # the reply
        ])
        with patch(
            "app.services.reminder_service.list_draft_followups",
            return_value=entries,
        ), patch(
            "app.services.reminder_service._mark_notified",
            side_effect=lambda rid: marked.append(rid),
        ), patch(
            "app.services.reminder_service.dismiss_reminder",
            side_effect=lambda rid, account_id=None: (
                dismissed.append((rid, account_id)) or True
            ),
        ), patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ):
            counters = sweep_woken_draft_followups(
                account_id=42, account_email="me@x.com", provider=provider,
            )

        assert counters == {"checked": 1, "promoted": 0, "deleted": 1, "errors": 0}
        assert provider.calls == ["thread-9"]
        assert store.items == {}  # draft is gone
        assert dismissed == [("rem-1", 42)]
        assert marked == []  # the deletion path dismisses, never marks-notified

    def test_promotes_draft_when_no_reply(self):
        store = _InMemoryStore()
        draft = _seed_draft(store)
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        entries = [{
            "id": "rem-1",
            "email_id": draft.id,
            "subject": "Re: Test",
            "reminder_date": past,
            "notified": False,
            "account_id": 42,
            "type": "draft_followup",
        }]
        marked = []
        surface_reminders: list[dict] = []

        provider = _FakeProvider(thread_messages=[
            _ThreadMsg(sender="me@x.com"),  # only self → no reply
        ])
        with patch(
            "app.services.reminder_service.list_draft_followups",
            return_value=entries,
        ), patch(
            "app.services.reminder_service._mark_notified",
            side_effect=lambda rid: marked.append(rid),
        ), patch(
            "app.services.reminder_service.dismiss_reminder",
            side_effect=lambda *_a, **_k: True,
        ), patch(
            "app.services.reminder_service.add_reminder",
            side_effect=lambda **kw: (surface_reminders.append(kw) or "surface-rem"),
        ), patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ):
            counters = sweep_woken_draft_followups(
                account_id=42, account_email="me@x.com", provider=provider,
            )

        assert counters == {"checked": 1, "promoted": 1, "deleted": 0, "errors": 0}
        assert draft.id in store.items  # draft kept
        assert marked == ["rem-1"]  # reminder marked notified → drafts API surfaces it
        # Inbox surface: an immediate-date 'followup' reminder on the
        # original sent thread so useSnooze wakes it back to the inbox top.
        assert len(surface_reminders) == 1
        s = surface_reminders[0]
        assert s["email_id"] == draft.email_id  # thread_id
        assert s["reminder_type"] == "followup"
        assert s["account_id"] == 42

    def test_pins_thread_on_no_reply_promotion(self):
        # No reply → the woken follow-up is pinned (thread_id), driving the
        # "Pinned" section of both inbox and Drafts.
        store = _InMemoryStore()
        draft = _seed_draft(store)
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        entries = [{
            "id": "rem-1",
            "email_id": draft.id,
            "subject": "Re: Test",
            "reminder_date": past,
            "notified": False,
            "account_id": 42,
            "type": "draft_followup",
        }]
        pinned_calls: list = []

        provider = _FakeProvider(thread_messages=[_ThreadMsg(sender="me@x.com")])
        with patch(
            "app.services.reminder_service.list_draft_followups",
            return_value=entries,
        ), patch(
            "app.services.reminder_service._mark_notified",
            side_effect=lambda rid: None,
        ), patch(
            "app.services.reminder_service.dismiss_reminder",
            side_effect=lambda *_a, **_k: True,
        ), patch(
            "app.services.reminder_service.add_reminder",
            side_effect=lambda **kw: "surface-rem",
        ), patch(
            "app.services.pinned_emails.add_pinned_email_id",
            side_effect=lambda aid, eid: pinned_calls.append((aid, eid)),
        ), patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ):
            counters = sweep_woken_draft_followups(
                account_id=42, account_email="me@x.com", provider=provider,
            )

        assert counters["promoted"] == 1
        # thread_id (== draft.email_id) pinned for the int account id.
        assert pinned_calls == [(42, "thread-9")]

    def test_does_not_pin_when_recipient_replied(self):
        # Reply detected → draft deleted, NOT pinned.
        store = _InMemoryStore()
        _seed_draft(store)
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        entries = [{
            "id": "rem-1",
            "email_id": "draft-1",
            "subject": "Re: Test",
            "reminder_date": past,
            "notified": False,
            "account_id": 42,
            "type": "draft_followup",
        }]
        pinned_calls: list = []

        provider = _FakeProvider(thread_messages=[
            _ThreadMsg(sender="me@x.com"),
            _ThreadMsg(sender="alex@acme.com"),  # the reply
        ])
        with patch(
            "app.services.reminder_service.list_draft_followups",
            return_value=entries,
        ), patch(
            "app.services.reminder_service._mark_notified",
            side_effect=lambda rid: None,
        ), patch(
            "app.services.reminder_service.dismiss_reminder",
            side_effect=lambda *_a, **_k: True,
        ), patch(
            "app.services.pinned_emails.add_pinned_email_id",
            side_effect=lambda aid, eid: pinned_calls.append((aid, eid)),
        ), patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ):
            counters = sweep_woken_draft_followups(
                account_id=42, account_email="me@x.com", provider=provider,
            )

        assert counters["deleted"] == 1
        assert pinned_calls == []  # never pin a thread that already got a reply

    def test_skips_surface_and_pin_when_draft_deleted_concurrently(self):
        # Regression (chaos audit 2026-06-02): the concurrent
        # _kill_snoozed_followup_for_thread task can delete this draft DURING
        # get_thread_messages. The sweep must re-check before surfacing/pinning
        # so it doesn't leave a pinned inbox thread + reminder for a gone draft.
        store = _InMemoryStore()
        draft = _seed_draft(store)
        # get_by_id: present at the initial read, GONE at the TOCTOU re-check.
        _calls = {"n": 0}

        def _racy_get_by_id(_id):
            _calls["n"] += 1
            return draft if _calls["n"] == 1 else None

        store.get_by_id = _racy_get_by_id

        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        entries = [{
            "id": "rem-1",
            "email_id": draft.id,
            "subject": "Re: Test",
            "reminder_date": past,
            "notified": False,
            "account_id": 42,
            "type": "draft_followup",
        }]
        pinned_calls: list = []
        dismissed: list = []

        # No reply in the thread → without the re-check this would surface + pin.
        provider = _FakeProvider(thread_messages=[_ThreadMsg(sender="me@x.com")])
        with patch(
            "app.services.reminder_service.list_draft_followups",
            return_value=entries,
        ), patch(
            "app.services.reminder_service._mark_notified",
            side_effect=lambda rid: None,
        ), patch(
            "app.services.reminder_service.dismiss_reminder",
            side_effect=lambda *_a, **_k: dismissed.append(_a) or True,
        ), patch(
            "app.services.reminder_service.add_reminder",
            side_effect=lambda **kw: "surface-rem",
        ), patch(
            "app.services.pinned_emails.add_pinned_email_id",
            side_effect=lambda aid, eid: pinned_calls.append((aid, eid)),
        ), patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ):
            counters = sweep_woken_draft_followups(
                account_id=42, account_email="me@x.com", provider=provider,
            )

        # No orphan: nothing pinned, nothing promoted; reminder cleaned up.
        assert pinned_calls == []
        assert counters["promoted"] == 0
        assert dismissed  # the orphan reminder was dismissed instead

    def test_skips_unexpired_entries(self):
        store = _InMemoryStore()
        draft = _seed_draft(store)
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        entries = [{
            "id": "rem-1",
            "email_id": draft.id,
            "subject": "x",
            "reminder_date": future,
            "notified": False,
            "account_id": 42,
            "type": "draft_followup",
        }]

        provider = _FakeProvider()
        with patch(
            "app.services.reminder_service.list_draft_followups",
            return_value=entries,
        ), patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ):
            counters = sweep_woken_draft_followups(
                account_id=42, account_email="me@x.com", provider=provider,
            )
        assert counters == {"checked": 0, "promoted": 0, "deleted": 0, "errors": 0}
        assert provider.calls == []  # zero API calls for not-yet-due entries

    def test_cleans_orphaned_reminder_when_draft_deleted(self):
        # User manually deleted the draft before its snooze elapsed —
        # the sweep should drop the orphan reminder, not crash.
        store = _InMemoryStore()
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        entries = [{
            "id": "rem-orphan",
            "email_id": "gone-draft-id",
            "subject": "x",
            "reminder_date": past,
            "notified": False,
            "account_id": 42,
            "type": "draft_followup",
        }]
        dismissed = []

        provider = _FakeProvider()
        with patch(
            "app.services.reminder_service.list_draft_followups",
            return_value=entries,
        ), patch(
            "app.services.reminder_service.dismiss_reminder",
            side_effect=lambda rid, account_id=None: (
                dismissed.append((rid, account_id)) or True
            ),
        ), patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ):
            counters = sweep_woken_draft_followups(
                account_id=42, account_email="me@x.com", provider=provider,
            )

        assert counters["checked"] == 1
        assert counters["promoted"] == 0
        assert counters["deleted"] == 0
        assert dismissed == [("rem-orphan", 42)]
        assert provider.calls == []  # never called provider for the orphan

    def test_provider_error_increments_errors_and_continues(self):
        store = _InMemoryStore()
        draft = _seed_draft(store)
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        entries = [{
            "id": "rem-1",
            "email_id": draft.id,
            "subject": "x",
            "reminder_date": past,
            "notified": False,
            "account_id": 42,
            "type": "draft_followup",
        }]

        provider = _FakeProvider(raises=True)
        with patch(
            "app.services.reminder_service.list_draft_followups",
            return_value=entries,
        ), patch(
            "app.infrastructure.container.get_container",
            return_value=_Container(store),
        ):
            counters = sweep_woken_draft_followups(
                account_id=42, account_email="me@x.com", provider=provider,
            )

        assert counters == {"checked": 1, "promoted": 0, "deleted": 0, "errors": 1}
        # Draft + reminder are intact — the next sweep will retry.
        assert draft.id in store.items

    def test_no_account_returns_empty_counters(self):
        provider = _FakeProvider()
        with patch(
            "app.services.reminder_service.list_draft_followups",
            return_value=[],
        ):
            counters = sweep_woken_draft_followups(
                account_id=0, account_email="me@x.com", provider=provider,
            )
        assert counters == {"checked": 0, "promoted": 0, "deleted": 0, "errors": 0}


# --------------------------------------------------------------------------- #
# Sent-side dispatch wiring (auto_trigger._SENT_ACTION_DISPATCH)
# --------------------------------------------------------------------------- #


class TestSentDispatch:
    def test_handler_is_registered_on_sent_side(self):
        # Regression guard: the sent-side loop in auto_followup.py walks rules
        # via run_auto_triggers_on_sent → _SENT_ACTION_DISPATCH. Without this
        # entry the rule silently no-ops ("no sent-side handler — skipping").
        from app.quicksteps import auto_trigger
        assert "create_snoozed_followup_draft" in auto_trigger._SENT_ACTION_DISPATCH
        assert (
            auto_trigger._SENT_ACTION_DISPATCH["create_snoozed_followup_draft"]
            is handle_create_snoozed_followup_draft
        )

    def test_content_keyword_uses_body_preview_when_body_missing(self):
        # SentEmail has body_preview (first 100 chars) but no .body — the
        # matcher must fall back so `body_contains` rules work on sent-side.
        from app.quicksteps.auto_trigger import _match_condition

        @dataclass
        class _Sent:
            sender: str = "me@x.com"
            subject: str = "Question for you"
            body_preview: str = "Can you confirm by Friday?"

        cond = {"type": "content_keyword", "value": "?"}
        assert _match_condition(cond, _Sent()) is True

        # And that the full-body inbound path still works (no preview field).
        @dataclass
        class _Inbound:
            sender: str = "alice@x.com"
            subject: str = "Re: thing"
            body: str = "yes here is the info?"

        assert _match_condition(cond, _Inbound()) is True


class TestPlaceholderChipRendering:
    """`{x}` menu chips (data-ar-token spans) resolve to the recipient fields."""

    def test_render_body_resolves_first_name_chip(self):
        chip = (
            '<span class="ar-token" data-ar-token="recipient_first_name" '
            'contenteditable="false">Prénom du destinataire</span>'
        )
        rendered = _render_body(
            f"Hi {chip}, following up.",
            recipient_addr="alex.doe@acme.com",
            original_subject="Q3",
        )
        assert rendered == "Hi Alex, following up."
        assert "data-ar-token" not in rendered

    def test_render_body_resolves_name_and_subject_chips(self):
        name = (
            '<span data-ar-token="recipient_name" contenteditable="false">Nom</span>'
        )
        subj = (
            '<span data-ar-token="original_subject" contenteditable="false">Sujet</span>'
        )
        rendered = _render_body(
            f"{name} re {subj}",
            recipient_addr="alex.doe@acme.com",
            original_subject="Q3 plan",
        )
        assert rendered == "Alex Doe re Q3 plan"

    def test_plain_double_brace_tokens_still_work(self):
        # Backward-compat: rules saved before the chip UI used literal {{...}}.
        rendered = _render_body(
            "Hi {{recipient_first_name}}",
            recipient_addr="alex.doe@acme.com",
            original_subject="x",
        )
        assert rendered == "Hi Alex"

    def test_render_body_flattens_div_br_structure(self):
        # The rich editor wraps lines in <div> and uses <br> for blanks. The
        # rendered draft body is plain text — those tags must become newlines,
        # not survive as literal markup.
        html = (
            '<div>Hi <span data-ar-token="recipient_first_name" '
            'contenteditable="false">Prénom</span>,</div>'
            '<div><br></div>'
            '<div>Following up.</div>'
            '<div><br></div>'
            '<div>Cordialement,</div>'
        )
        rendered = _render_body(
            html,
            recipient_addr="alex.doe@acme.com",
            original_subject="x",
        )
        assert rendered == "Hi Alex,\n\nFollowing up.\n\nCordialement,"
        assert "<div>" not in rendered and "<br>" not in rendered


class TestHtmlToText:
    """`_html_to_text` mirrors the frontend `stripHtmlTags` so the stored
    draft body and the in-app preview agree on line breaks."""

    def test_noop_on_plain_text(self):
        # Tag-free templates render byte-for-byte unchanged (no stray trim).
        assert _html_to_text("Hi {shipping_id} — see you  ") == "Hi {shipping_id} — see you  "

    def test_br_and_div_become_newlines(self):
        assert _html_to_text("<div>a</div><div><br></div><div>b</div>") == "a\n\nb"

    def test_unescapes_common_entities(self):
        assert _html_to_text("<div>Tom &amp; Jerry&nbsp;</div>") == "Tom & Jerry"

    def test_collapses_excess_newlines(self):
        assert _html_to_text("<div>a</div><br><br><br><div>b</div>") == "a\n\nb"
