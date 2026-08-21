# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression : "Re: Accepted: <event>" RSVP responses must land in Noise.

Bug class : the calendar HARD-NOISE patterns (RSVP responses, cancellations,
updated invitations) live in `_apply_builtin_rules` (step 1b-cal-noise),
which only runs in step 3 of the pipeline. Step 0.5 (thread-context signal)
runs earlier and sees the `"Re:"` prefix + a non-automated sender → labels
the email **Action** with conf 0.70. Once a default label is set, step 3
short-circuits (`if not assignment.default_label`) and the hard-noise
patterns never fire. Result: "Re: Accepted: Sync @ 3pm" lands in Action
inbox (user-visible bug, see screenshot 2026-05-12).

The fix moves a calendar-hard-noise gate to step 0.15 — runs BEFORE
the thread-context signal, locks Noise with conf 0.95 (survives the
contact-floor carve-out at step 3b).

These tests assert the gate via `execute()` end-to-end and would have
caught the regression had they existed pre-fix.
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.application.label_email import LabelEmailUseCase
from app.domain.entities.email_labels import DefaultLabel, get_default_labels


@pytest.fixture
def labels():
    return get_default_labels()


@pytest.fixture
def use_case(labels):
    """Use case with a Mock LLM that asserts it's NEVER called. The
    calendar-hard-noise gate short-circuits before LLM — if it doesn't,
    the test fails noisily because llm.complete() would return a Mock and
    downstream code would crash on the malformed response."""
    llm = Mock()
    llm.complete.side_effect = AssertionError(
        "LLM should not be called for calendar hard-noise emails — they "
        "must be locked Noise by the deterministic gate at step 0.15"
    )
    return LabelEmailUseCase(llm=llm, labels=labels, rules=[])


def _make_email(subject: str, *, sender: str = "alice@externalcompany.com", body: str = "Thanks!", thread_id: str | None = None):
    """Build an email dict-like mock whose attribute defaults are real
    strings/lists (not auto-mocked) — the use-case reads `attachments_meta`
    as a string-containing value (the `".ics" in ...` membership test).
    Using `spec=[...]` would tighten the surface but we lean on explicit
    attribute setting + a non-iterable `Mock()` would crash inside
    `_execute_impl` at line 490, masking the real signal.
    """
    email = Mock()
    email.id = "test-rsvp"
    email.sender = sender
    email.subject = subject
    email.body = body
    email.body_html = ""
    email.to = "me@agentys.app"
    email.cc = ""
    email.recipients = ["me@agentys.app"]
    email.thread_id = thread_id
    email.received_at = "2026-05-12T12:00:00Z"
    email.attachments_meta = ""  # string, not Mock — used in `".ics" in attachments_meta` check
    email.has_ics_attachment = False
    email.raw_metadata = None
    email.labels = []
    return email


class TestReAcceptedRsvpResponse:
    """The exact scenario from the user report : "Re: Accepted: sssddff @
    Thu May 21, 2026 10am - 10:30am (EDT) (Crypto Université)" labeled
    Action instead of Noise."""

    def test_re_accepted_lands_noise_not_action(self, use_case):
        # User sees this email in their inbox: someone (or their other
        # account) has accepted a meeting they organized. Nothing to do.
        email = _make_email("Re: Accepted: sssddff @ Thu May 21, 2026 10am - 10:30am (EDT)")
        result = use_case.execute(email)
        assert result.default_label == DefaultLabel.NOISE.value, (
            f"Expected NOISE, got {result.default_label!r}. The thread-context "
            f"signal at step 0.5 captured the 'Re:' prefix before the "
            f"calendar-hard-noise gate could fire — see step 0.15."
        )

    def test_accepted_bare_lands_noise(self, use_case):
        # "Accepted: ..." without the Re: prefix — the original RSVP
        # notification from Outlook/Google when an invitee accepts.
        email = _make_email("Accepted: Team Sync @ Tue Mar 4, 2pm-3pm")
        result = use_case.execute(email)
        assert result.default_label == DefaultLabel.NOISE.value

    def test_declined_lands_noise(self, use_case):
        email = _make_email("Re: Declined: 1:1 @ Mon 9am")
        result = use_case.execute(email)
        assert result.default_label == DefaultLabel.NOISE.value

    def test_tentative_lands_noise(self, use_case):
        email = _make_email("Re: Tentative: Quarterly review")
        result = use_case.execute(email)
        assert result.default_label == DefaultLabel.NOISE.value

    def test_french_accepte_lands_noise(self, use_case):
        # Outlook FR uses "Accepté:" / "Refusé:".
        email = _make_email("Re: Accepté : Réunion équipe @ jeu 14 mai 10h")
        result = use_case.execute(email)
        assert result.default_label == DefaultLabel.NOISE.value

    def test_canceled_event_lands_noise(self, use_case):
        email = _make_email("Canceled event: Sync @ Wed 11am")
        result = use_case.execute(email)
        assert result.default_label == DefaultLabel.NOISE.value

    def test_updated_invitation_lands_noise(self, use_case):
        email = _make_email("Updated invitation: All-hands @ Fri 4pm")
        result = use_case.execute(email)
        assert result.default_label == DefaultLabel.NOISE.value

    def test_re_prefix_does_not_bypass_for_real_thread(self, use_case):
        # Add a thread_id to simulate a real conversation — the
        # thread-context signal at step 0.5 would normally upgrade this
        # to Action with conf 0.85. The calendar-hard-noise gate at
        # step 0.15 must still win because it runs first.
        email = _make_email(
            "Re: Accepted: Marketing planning sync",
            thread_id="<active-thread-12345@gmail.com>",
        )
        result = use_case.execute(email)
        assert result.default_label == DefaultLabel.NOISE.value


class TestNonRsvpStillReachesNormalPipeline:
    """Sanity check: the new gate is narrow — non-RSVP emails still flow
    through the normal pipeline (LLM gets called for ambiguous cases).
    Without this, the gate could be over-eager and silently classify
    legitimate Action emails as Noise."""

    def test_real_invitation_does_not_trigger_gate(self, labels):
        # A NEW meeting invitation should be Action — and importantly,
        # should NOT be caught by the hard-noise gate (no match against
        # "Accepted:"/"Declined:"/etc.).
        llm = Mock()
        llm.complete.return_value = Mock(
            content='{"labels": [{"label": "Action", "confidence": 0.9, "reason": "test"}]}',
            input_tokens=10, output_tokens=5, model="test",
        )
        use_case = LabelEmailUseCase(llm=llm, labels=labels, rules=[])

        email = _make_email(
            "Invitation: Sync @ Wed 3pm-4pm",
            sender="bob@partner.com",
            body="Please join.",
        )
        result = use_case.execute(email)
        # Either the invitation-action gate at step 1b-cal-action fires
        # (rule-based Action), or LLM picks it up — either way Action.
        # The key assertion: NOT misclassified as Noise by an over-eager
        # hard-noise gate.
        assert result.default_label != DefaultLabel.NOISE.value, (
            f"New invitation must not be caught by the calendar-hard-noise "
            f"gate — got {result.default_label!r}"
        )
