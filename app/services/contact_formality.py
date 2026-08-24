# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Auto-derivation of `ContactStyleProfile.formality_override` from the most
recently sent email.

The Training UI surfaces `formality_override` per contact (chip + relative
"Updated …" caption). Without this service the field is set once at
onboarding (or via a manual edit) and never tracks the actual evolution of
the relationship. This helper plugs into the post-send background path and
re-derives the override from each newly-sent body, unless the user has
locked the value via the editor.

PR5 — stability filter. The original "last sent email wins" policy turned
out too noisy : a one-line acknowledgement ("ok merci à+") could flip a
Formal client to Casual on its own. We now require **two consecutive sends
to agree** before promoting a divergent measurement to the override. The
intermediate state lives on `ContactStyleProfile.formality_pending`. A
virgin override (None) bypasses the buffer — the very first measurement on
a fresh contact is written directly because there is no prior signal to
disagree with.

The user can still pin a value via the lock (`formality_locked = True`),
which short-circuits the entire helper.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.domain.entities.writing_style import (
    ContactStyleProfile,
    FormalityLevel,
    WritingStyleProfile,
)
from app.prompts.helpers import analyze_email_formality


def _score_to_level(score: int) -> FormalityLevel:
    """Map the 1–5 heuristic score from `analyze_email_formality` to the
    discrete `FormalityLevel` we persist on the contact profile."""
    # 1–2 = casual, 3 = mixed (semi-formal), 4–5 = formal.
    if score <= 2:
        return FormalityLevel.CASUAL
    if score >= 4:
        return FormalityLevel.FORMAL
    return FormalityLevel.MIXED


def _stamp_now() -> str:
    """ISO-8601 UTC timestamp with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def update_contact_formality_from_send(
    profile: WritingStyleProfile,
    contact_email: str,
    sent_body: str,
) -> bool:
    """Re-derive `formality_override` for `contact_email` from `sent_body`.

    Returns True if the contact entry was mutated (the caller is responsible
    for persisting the parent ``WritingStyleProfile``). Returns False when:
      - the body is empty/whitespace,
      - the contact entry doesn't exist on the profile,
      - the contact's `formality_locked` is True,
      - the new derived level matches the existing override AND no pending
        measurement is buffered (true no-op).

    State machine (PR5 stability filter):
      - override is None   → first measure : write override directly.
      - new == override    → user reverted to their established style :
                             clear any pending buffer, idempotent otherwise.
      - new == pending     → 2 consecutive sends concur → promote to override.
      - else                → buffer new value as pending (no override flip).

    The helper is intentionally pure — no I/O, no logging side-effects on
    the happy path — so it stays unit-testable in isolation.
    """
    if not sent_body or not sent_body.strip():
        return False
    if not contact_email:
        return False

    key = contact_email.lower()
    raw = profile.contact_profiles.get(key)
    if not raw:
        # We only auto-update existing contact entries. Creating a fresh
        # profile here would race with the onboarding/learning path that
        # owns the entity's lifecycle.
        return False

    contact = ContactStyleProfile.from_dict(raw)
    if contact.formality_locked:
        return False

    new_level = _score_to_level(analyze_email_formality(sent_body))

    # First measurement on a virgin override : take it at face value.
    # Nothing to disagree with, so the stability filter doesn't apply.
    if contact.formality_override is None:
        contact.formality_override = new_level
        contact.formality_pending = None
        contact.formality_updated_at = _stamp_now()
        profile.contact_profiles[key] = contact.to_dict()
        return True

    # New send agrees with established override : the user reverted to their
    # base style. Clear any half-formed pending measurement, otherwise no-op.
    if new_level == contact.formality_override:
        if contact.formality_pending is not None:
            contact.formality_pending = None
            profile.contact_profiles[key] = contact.to_dict()
            return True
        return False

    # New send confirms a previously buffered measurement : promote to override.
    if new_level == contact.formality_pending:
        contact.formality_override = new_level
        contact.formality_pending = None
        contact.formality_updated_at = _stamp_now()
        profile.contact_profiles[key] = contact.to_dict()
        return True

    # Divergent send (disagrees with both override and pending) : park as the
    # new pending candidate. The override is left intact — a single dissent
    # is no longer enough to flip a stable relationship.
    contact.formality_pending = new_level
    profile.contact_profiles[key] = contact.to_dict()
    return True


def lock_contact_formality(
    profile: WritingStyleProfile,
    contact_email: str,
    new_level: Optional[FormalityLevel] = None,
) -> bool:
    """Set `formality_locked = True` on a contact profile, optionally
    overriding the level. Used by the Training UI when the user manually
    edits the formality chip — locking ensures the auto-derivation path
    won't overwrite their choice on the next send.

    Returns True when the profile was mutated.
    """
    if not contact_email:
        return False
    key = contact_email.lower()
    raw = profile.contact_profiles.get(key)
    if not raw:
        return False

    contact = ContactStyleProfile.from_dict(raw)
    changed = False
    if new_level is not None and contact.formality_override != new_level:
        contact.formality_override = new_level
        contact.formality_updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        changed = True
    if not contact.formality_locked:
        contact.formality_locked = True
        changed = True
    if changed:
        profile.contact_profiles[key] = contact.to_dict()
    return changed


def unlock_contact_formality(
    profile: WritingStyleProfile,
    contact_email: str,
) -> bool:
    """Flip `formality_locked` back to False so future sends re-derive the
    override. The current value is left intact — the next send will
    overwrite it if the formality has actually changed."""
    if not contact_email:
        return False
    key = contact_email.lower()
    raw = profile.contact_profiles.get(key)
    if not raw:
        return False
    contact = ContactStyleProfile.from_dict(raw)
    if not contact.formality_locked:
        return False
    contact.formality_locked = False
    profile.contact_profiles[key] = contact.to_dict()
    return True
