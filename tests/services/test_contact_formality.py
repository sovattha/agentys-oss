# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for `app/services/contact_formality.py`.

Covers the post-send auto-derivation path :
  - body → formality_override mapping (1–2 → casual, 3 → mixed, 4–5 → formal),
  - lock honoured (no mutation when `formality_locked == True`),
  - idempotency (same level does not bump `formality_updated_at`),
  - missing contact entry / empty body are no-ops,
  - the manual lock helpers `lock_contact_formality` /
    `unlock_contact_formality` round-trip cleanly.
"""

from __future__ import annotations

import pytest

from app.domain.entities.writing_style import (
    ContactStyleProfile,
    FormalityLevel,
    WritingStyleProfile,
)
from app.services.contact_formality import (
    _score_to_level,
    lock_contact_formality,
    unlock_contact_formality,
    update_contact_formality_from_send,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def profile_with_contact() -> WritingStyleProfile:
    """Empty `WritingStyleProfile` with one contact entry already
    populated. Tests mutate this in-place to assert the helper's effects."""
    parent = WritingStyleProfile.create_empty(account_id=1)
    parent.contact_profiles["alice@example.com"] = ContactStyleProfile(
        email="alice@example.com",
    ).to_dict()
    return parent


# ── _score_to_level mapping ───────────────────────────────────────────


@pytest.mark.parametrize(
    "score,expected",
    [
        (1, FormalityLevel.CASUAL),
        (2, FormalityLevel.CASUAL),
        (3, FormalityLevel.MIXED),
        (4, FormalityLevel.FORMAL),
        (5, FormalityLevel.FORMAL),
    ],
)
def test_score_to_level_mapping(score: int, expected: FormalityLevel) -> None:
    assert _score_to_level(score) == expected


# ── update_contact_formality_from_send ────────────────────────────────


def test_first_send_stamps_formality_and_timestamp(profile_with_contact: WritingStyleProfile) -> None:
    """A casual body on a contact with no prior override sets it + the timestamp."""
    body = "Salut Alice, on se voit demain ? Tkt c'est cool"
    changed = update_contact_formality_from_send(profile_with_contact, "alice@example.com", body)
    assert changed is True
    after = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after.formality_override == FormalityLevel.CASUAL
    assert after.formality_updated_at is not None  # ISO timestamp


def test_locked_profile_is_not_mutated(profile_with_contact: WritingStyleProfile) -> None:
    """`formality_locked == True` short-circuits the helper — nothing changes."""
    raw = profile_with_contact.contact_profiles["alice@example.com"]
    raw["formality_locked"] = True
    raw["formality_override"] = FormalityLevel.FORMAL.value
    profile_with_contact.contact_profiles["alice@example.com"] = raw
    body = "Salut Alice, c'est cool"  # would normally derive CASUAL
    changed = update_contact_formality_from_send(profile_with_contact, "alice@example.com", body)
    assert changed is False
    after = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after.formality_override == FormalityLevel.FORMAL  # unchanged


def test_same_level_is_idempotent(profile_with_contact: WritingStyleProfile) -> None:
    """No mutation (and no timestamp bump) when the new derived level matches the existing one."""
    raw = profile_with_contact.contact_profiles["alice@example.com"]
    raw["formality_override"] = FormalityLevel.CASUAL.value
    raw["formality_updated_at"] = "2026-01-01T00:00:00+00:00"
    profile_with_contact.contact_profiles["alice@example.com"] = raw
    body = "Salut Alice, t'inquiète c'est cool, à+"  # CASUAL
    changed = update_contact_formality_from_send(profile_with_contact, "alice@example.com", body)
    assert changed is False
    after = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after.formality_updated_at == "2026-01-01T00:00:00+00:00"  # untouched


def test_missing_contact_entry_is_noop(profile_with_contact: WritingStyleProfile) -> None:
    """Auto-derivation only runs on existing contact entries — fresh contacts are
    handled by the onboarding/learning path, not this helper."""
    changed = update_contact_formality_from_send(
        profile_with_contact, "unknown@example.com", "Cordialement, Jean"
    )
    assert changed is False
    assert "unknown@example.com" not in profile_with_contact.contact_profiles


def test_empty_body_is_noop(profile_with_contact: WritingStyleProfile) -> None:
    assert update_contact_formality_from_send(profile_with_contact, "alice@example.com", "") is False
    assert update_contact_formality_from_send(profile_with_contact, "alice@example.com", "   \n\t") is False


def test_single_dissent_buffers_as_pending_without_flipping_override(
    profile_with_contact: WritingStyleProfile,
) -> None:
    """PR5 stability filter — a single divergent send DOES NOT flip the override.

    Replaces the legacy behavior where a one-shot reply could flip a stable
    relationship. The new value is buffered on `formality_pending` and the
    override is preserved until a second consecutive send confirms.
    """
    raw = profile_with_contact.contact_profiles["alice@example.com"]
    raw["formality_override"] = FormalityLevel.CASUAL.value
    profile_with_contact.contact_profiles["alice@example.com"] = raw
    body = (
        "Cher Monsieur, je vous prie d'agréer l'expression de mes salutations distinguées. "
        "Veuillez nous faire parvenir le contrat. Cordialement."
    )
    changed = update_contact_formality_from_send(profile_with_contact, "alice@example.com", body)
    # The contact entry IS mutated (pending set), but the override stays put.
    assert changed is True
    after = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after.formality_override == FormalityLevel.CASUAL  # unchanged
    assert after.formality_pending == FormalityLevel.FORMAL


def test_two_consecutive_dissenting_sends_promote_pending_to_override(
    profile_with_contact: WritingStyleProfile,
) -> None:
    """Two consecutive sends agreeing on a new level → flip override."""
    raw = profile_with_contact.contact_profiles["alice@example.com"]
    raw["formality_override"] = FormalityLevel.CASUAL.value
    profile_with_contact.contact_profiles["alice@example.com"] = raw
    formal_body = (
        "Cher Monsieur, je vous prie d'agréer l'expression de mes salutations "
        "distinguées. Veuillez nous faire parvenir le contrat. Cordialement."
    )

    # Send 1 — buffer formal as pending
    update_contact_formality_from_send(profile_with_contact, "alice@example.com", formal_body)
    after_1 = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after_1.formality_override == FormalityLevel.CASUAL
    assert after_1.formality_pending == FormalityLevel.FORMAL

    # Send 2 — confirm formal → promote
    changed = update_contact_formality_from_send(profile_with_contact, "alice@example.com", formal_body)
    assert changed is True
    after_2 = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after_2.formality_override == FormalityLevel.FORMAL
    assert after_2.formality_pending is None
    assert after_2.formality_updated_at is not None


def test_revert_to_override_clears_pending(profile_with_contact: WritingStyleProfile) -> None:
    """Pending was buffered, but the next send reverts to the established
    override → clear pending (the user did not actually change style)."""
    raw = profile_with_contact.contact_profiles["alice@example.com"]
    raw["formality_override"] = FormalityLevel.CASUAL.value
    raw["formality_pending"] = FormalityLevel.FORMAL.value
    profile_with_contact.contact_profiles["alice@example.com"] = raw

    casual_body = "Salut Alice, t'inquiète c'est cool, à+"
    changed = update_contact_formality_from_send(profile_with_contact, "alice@example.com", casual_body)
    assert changed is True  # pending cleared, that counts as a mutation
    after = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after.formality_override == FormalityLevel.CASUAL
    assert after.formality_pending is None


def test_third_dissent_replaces_pending_candidate(profile_with_contact: WritingStyleProfile) -> None:
    """Three different levels in a row : pending tracks the latest candidate.

    override=CASUAL, send formal (pending=FORMAL), send mixed (pending=MIXED).
    The second dissent is treated as a new candidate, not a confirmation.
    """
    raw = profile_with_contact.contact_profiles["alice@example.com"]
    raw["formality_override"] = FormalityLevel.CASUAL.value
    profile_with_contact.contact_profiles["alice@example.com"] = raw

    formal_body = "Cher Monsieur, veuillez agréer mes salutations distinguées. Cordialement."
    update_contact_formality_from_send(profile_with_contact, "alice@example.com", formal_body)
    after_1 = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after_1.formality_pending == FormalityLevel.FORMAL  # baseline

    # `analyze_email_formality` scores this body at 3 → MIXED — distinct from
    # both CASUAL (override) and FORMAL (pending). We avoid "votre" / "vos"
    # here because those now count toward the vouvoiement signal and would
    # bump the score to 4 (FORMAL).
    mixed_body = "Hello Sophie, demande bien notée, retour demain."
    changed = update_contact_formality_from_send(profile_with_contact, "alice@example.com", mixed_body)
    assert changed is True
    after = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after.formality_override == FormalityLevel.CASUAL
    assert after.formality_pending == FormalityLevel.MIXED


def test_pending_field_round_trips_through_dict(profile_with_contact: WritingStyleProfile) -> None:
    """Sanity-check the to_dict/from_dict serialization of `formality_pending`."""
    raw = profile_with_contact.contact_profiles["alice@example.com"]
    raw["formality_override"] = FormalityLevel.MIXED.value
    raw["formality_pending"] = FormalityLevel.FORMAL.value
    profile_with_contact.contact_profiles["alice@example.com"] = raw

    after = ContactStyleProfile.from_dict(raw)
    assert after.formality_pending == FormalityLevel.FORMAL
    again = ContactStyleProfile.from_dict(after.to_dict())
    assert again.formality_pending == FormalityLevel.FORMAL


# ── lock / unlock helpers ─────────────────────────────────────────────


def test_lock_contact_formality_sets_lock_and_timestamp(profile_with_contact: WritingStyleProfile) -> None:
    changed = lock_contact_formality(
        profile_with_contact, "alice@example.com", new_level=FormalityLevel.FORMAL
    )
    assert changed is True
    after = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after.formality_locked is True
    assert after.formality_override == FormalityLevel.FORMAL
    assert after.formality_updated_at is not None


def test_unlock_lets_next_send_re_derive(profile_with_contact: WritingStyleProfile) -> None:
    raw = profile_with_contact.contact_profiles["alice@example.com"]
    raw["formality_locked"] = True
    raw["formality_override"] = FormalityLevel.FORMAL.value
    profile_with_contact.contact_profiles["alice@example.com"] = raw
    # Unlock — value preserved, lock released
    assert unlock_contact_formality(profile_with_contact, "alice@example.com") is True
    after = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert after.formality_locked is False
    assert after.formality_override == FormalityLevel.FORMAL  # not cleared

    # PR5 stability filter — post-unlock, the first dissenting send only
    # buffers a pending candidate. Two consecutive casual sends are required
    # to actually flip the override.
    casual_body = "Salut, à+ tkt"
    update_contact_formality_from_send(profile_with_contact, "alice@example.com", casual_body)
    update_contact_formality_from_send(profile_with_contact, "alice@example.com", casual_body)
    final = ContactStyleProfile.from_dict(profile_with_contact.contact_profiles["alice@example.com"])
    assert final.formality_override == FormalityLevel.CASUAL
    assert final.formality_pending is None


def test_unlock_already_unlocked_is_noop(profile_with_contact: WritingStyleProfile) -> None:
    """No churn when the user clicks "Back to auto" on an already-auto profile."""
    assert unlock_contact_formality(profile_with_contact, "alice@example.com") is False


# ── Round-trip with from_dict / to_dict (legacy payload compat) ──────


def test_legacy_payload_without_new_fields_loads_with_safe_defaults() -> None:
    """Old contact entries pre-dating this feature must still round-trip
    cleanly — `formality_locked` defaults to False, `formality_updated_at`
    to None."""
    legacy = {
        "email": "bob@example.com",
        "formality_override": "formal",
        "preferred_greeting": "Bonjour {first_name},",
        "preferred_closing": "Cordialement,",
        "langue_variante": "fr-FR",
        "langue": "francais",
        "nickname": "Bob",
    }
    contact = ContactStyleProfile.from_dict(legacy)
    assert contact.formality_locked is False
    assert contact.formality_updated_at is None
    # And it round-trips through to_dict → from_dict cleanly
    again = ContactStyleProfile.from_dict(contact.to_dict())
    assert again.formality_locked is False
    assert again.formality_updated_at is None
