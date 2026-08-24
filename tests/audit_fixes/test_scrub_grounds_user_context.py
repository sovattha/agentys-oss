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
Audit fix — 2026-05-13 user-reported regression
================================================

The `/expand notes` flow lets the user type notes in the reply composer,
then asks the AI to expand them into a real email. The user's notes are
passed to the drafter via the `instructions` parameter — they are NOT
present in the source email body.

Post-LLM, two scrubbers run against `body + subject` to catch
hallucinations:

  - `_scrub_ungrounded_nouns`  → drops sentences with proper nouns absent
    from the source.
  - `_scrub_novel_situation`   → for SHORT source emails (<150 chars),
    drops lines that introduce a personal situation using common nouns
    absent from the source.

Pre-fix, when the source email was a short message like "est-tu en VIP?"
and the user typed notes such as "j'ai obtenu mon accès VIP", the drafter
correctly expanded the notes into a sentence using «accès», but
`_scrub_novel_situation` then deleted the line because «accès» was not in
the 16-char source — leaving the user with a 25-char placeholder reply.

Fix: both scrubbers now accept a `user_context` argument; words in there
count as grounded.
"""

from __future__ import annotations


from app.smart_routing import _scrub_novel_situation, _scrub_ungrounded_nouns


# -- _scrub_novel_situation -------------------------------------------------


class TestScrubNovelSituationUserContext:
    def test_user_notes_word_is_grounded(self):
        """User typed «accès» in notes → drafter used it → must survive."""
        body = "est-tu en VIP?"
        draft = (
            "Salut Alexandre,\n\n"
            "Oui, j'ai réussi à avoir mon accès VIP la semaine dernière.\n\n"
            "À bientôt,"
        )
        user_context = "Salut. Oui, j'ai réussi à avoir mon accès VIP."

        cleaned = _scrub_novel_situation(
            draft, body, subject="test label", user_context=user_context,
        )

        # The line MUST be preserved — «accès» is grounded in user_context.
        assert "accès VIP" in cleaned, (
            f"Scrubber stripped user-provided content. Got:\n{cleaned}"
        )

    def test_default_behavior_without_user_context_still_scrubs(self):
        """Hallucinations are still removed when no user_context is given."""
        body = "est-tu en VIP?"
        draft = (
            "Salut Alexandre,\n\n"
            "Je suis en vacances jusqu'au 20 mai.\n\n"
            "À bientôt,"
        )

        cleaned = _scrub_novel_situation(draft, body, subject="test label")

        # «vacances» is a classic hallucinated personal situation pattern
        # ("je suis en X") — must be scrubbed.
        assert "vacances" not in cleaned, (
            "Scrubber failed to remove hallucinated personal situation."
        )

    def test_empty_user_context_does_not_break(self):
        """Defaulting `user_context=""` keeps prior behavior intact."""
        body = "est-tu en VIP?"
        draft = "Salut Alexandre,\n\nJe te confirme.\n\nÀ bientôt,"

        cleaned = _scrub_novel_situation(
            draft, body, subject="", user_context="",
        )

        assert "Je te confirme" in cleaned


# -- _scrub_ungrounded_nouns -----------------------------------------------


class TestScrubUngroundedNounsUserContext:
    def test_user_notes_proper_noun_is_grounded(self):
        """Proper nouns from user notes count as grounded.

        Example: user typed «Pinterest» in notes — drafter mentions
        Pinterest in the reply — must survive even though the source
        email never said «Pinterest».
        """
        body = "Tu as une minute?"
        draft = (
            "Salut Alexandre,\n\n"
            "Oui, je voulais te parler du dossier Pinterest.\n\n"
            "À bientôt,"
        )
        user_context = "Parler du dossier Pinterest avec lui."

        cleaned = _scrub_ungrounded_nouns(
            draft, body, subject="dispo", sender="alex@example.com",
            user_context=user_context,
        )

        assert "Pinterest" in cleaned, (
            f"Scrubber stripped user-provided proper noun. Got:\n{cleaned}"
        )

    def test_default_behavior_without_user_context_still_scrubs(self):
        """Genuinely hallucinated proper nouns are still removed."""
        body = "Tu as une minute?"
        draft = (
            "Salut Alexandre,\n\n"
            "Oui, je voulais te parler du dossier Marcus.\n\n"
            "À bientôt,"
        )

        cleaned = _scrub_ungrounded_nouns(
            draft, body, subject="dispo", sender="alex@example.com",
        )

        # «Marcus» is hallucinated — neither in source nor user context.
        assert "Marcus" not in cleaned, (
            "Scrubber failed to remove hallucinated proper noun."
        )

    def test_english_contractions_are_not_treated_as_proper_nouns(self):
        """`I'll` used mid-sentence must not become hallucinated noun `Ill`."""
        body = "backend-tests failed; please check the run"
        draft = (
            "Hi Nathan,\n\n"
            "I've reviewed the run. One backend test job failed; I'll check the annotation.\n\n"
            "Best regards,"
        )

        cleaned = _scrub_ungrounded_nouns(
            draft,
            body,
            subject="CI failed",
            sender="github@example.com",
            user_context="backend-tests failed",
        )

        assert "I'll check the annotation" in cleaned
