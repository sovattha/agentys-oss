# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression: contact profile greetings must not address the account owner.

Alex -> Nat emails can legitimately contain openings such as "Salut Nat,".
Those lines describe how the contact greets the user; they must never become
the mandatory opening for a reply from the user back to Alex.
"""

from app.domain.entities.writing_style import (
    ContactStyleProfile,
    FormalityLevel,
    WritingStyleProfile,
)
from app.prompts.builders import (
    _resolve_contact_overrides,
    format_contact_summary,
    get_standard_draft_prompts,
)


CONTACT_EMAIL = "alex@example.com"


def _profile_with_polluted_alex_greeting() -> WritingStyleProfile:
    profile = WritingStyleProfile.create_empty(account_id=42)
    contact = ContactStyleProfile(
        email=CONTACT_EMAIL,
        nickname="Alex",
        formality_override=FormalityLevel.CASUAL,
        preferred_greeting="Salut Nat,",
        preferred_closing="A+",
        langue="français",
    )
    profile.contact_profiles[CONTACT_EMAIL] = contact.to_dict()
    return profile


def _patch_writing_style_store(monkeypatch, profile: WritingStyleProfile) -> None:
    class _StubStore:
        def load(self, account_id):
            return profile if account_id == 42 else None

    class _StubContainer:
        def get_writing_style_store(self):
            return _StubStore()

    monkeypatch.setattr(
        "app.infrastructure.container.get_container",
        lambda: _StubContainer(),
    )


def test_contact_summary_does_not_expose_contact_openings_as_reply_formulas():
    block = format_contact_summary(
        {
            "relation_type": "cofounder",
            "habitual_tone": "casual",
            "user_formulas_opening": ["Salut Alex,"],
            "user_formulas_closing": ["A+"],
            "contact_formulas_opening": ["Salut Nat,"],
        }
    )

    assert "Salut Alex," in block
    assert "Salut Nat," not in block
    assert "Salutations du contact" not in block


def test_resolve_contact_overrides_rejects_greeting_addressed_to_someone_else(
    monkeypatch,
):
    _patch_writing_style_store(monkeypatch, _profile_with_polluted_alex_greeting())

    nickname, greeting, variant, formality, _closing = _resolve_contact_overrides(
        account_id=42,
        sender=f"Alexandre Simon <{CONTACT_EMAIL}>",
        detected_language="FRENCH",
    )

    assert nickname == "Alex"
    assert greeting == ""
    assert variant == ""
    assert formality == "casual"


def test_standard_prompt_falls_back_to_contact_name_when_profile_greeting_is_polluted(
    monkeypatch,
):
    _patch_writing_style_store(monkeypatch, _profile_with_polluted_alex_greeting())

    _, user_prompt = get_standard_draft_prompts(
        sender=f"Alexandre Simon <{CONTACT_EMAIL}>",
        subject="Vérification brouillons automatiques",
        body=(
            "Salut Nat,\n\n"
            "Je voulais vérifier si la fonction de brouillons automatiques "
            "fonctionne correctement."
        ),
        account_id=42,
    )

    assert "YOUR REPLY MUST START WITH EXACTLY: Salut Alex," in user_prompt
    assert "YOUR REPLY MUST START WITH EXACTLY: Salut Nat," not in user_prompt
