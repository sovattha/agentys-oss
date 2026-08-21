"""
Audit fix — 2026-05-13 Simon bug
====================================

User report: a Casual-LOCKED contact (Alexandre Simon, nickname
"Alexandre", greeting "Salut", closing "À bientôt,") produced a draft that
opened with "M. Simon," and closed with "Merci!,". Both signals
overridden by the user via the Training UI were ignored:

  1. The locked-Casual + nickname directive should have forced "Salut
     Alexandre," as the greeting. The LLM kept the formal greeting it had
     copied from the user's dictated notes, and the post-LLM normalisation
     saw "M." as a valid greeting prefix → returned the draft as-is.

  2. The per-contact preferred_closing "À bientôt," was never consulted —
     `_compute_closing_hint` only looked at the user-level preferred_closings
     and the user's most-frequent "Merci!" leaked through.

  3. "Merci!," is a sub-bug: `_compute_closing_hint` stripped trailing
     punctuation but not "!", then appended a comma → "Merci!," which the
     user never writes.

Three fixes covered here:

  - `_ensure_starts_with_greeting(..., strict_replace=True)` overwrites a
    non-matching first-line greeting when the contact has explicit overrides.
  - `_format_closing` (extracted helper) does not append a comma after "!" / "?".
  - The refine-text / closing path is exercised at the unit level via
    `_compute_closing_hint` — the route wiring (`contact_preferred_closing`
    prepended to the closings list) is covered by reading the route directly
    in a smoke test.
"""

from __future__ import annotations

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

from app.prompts.identity import _compute_closing_hint, _format_closing
from app.smart_routing import _ensure_starts_with_greeting


# --------------------------------------------------------------------------- #
# _ensure_starts_with_greeting — strict_replace mode
# --------------------------------------------------------------------------- #


class TestStrictReplaceGreeting:
    def test_strict_replaces_formal_when_contact_is_casual_locked(self):
        """The Simon scenario: LLM kept "M. Simon," from dictated
        notes, the contact card says nickname=Alexandre + locked Casual +
        greeting=Salut → the post-LLM pass must overwrite the greeting."""
        draft = (
            "M. Simon,\n\n"
            "Oui, je vais être là pour la rencontre Teams. Merci beaucoup. "
            "On se voit bientôt.\n\n"
            "À bientôt,"
        )
        out = _ensure_starts_with_greeting(
            draft, "Salut Alexandre,", strict_replace=True,
        )
        assert out.startswith("Salut Alexandre,\n\n")
        assert "M. Simon," not in out
        # The body must be preserved verbatim — we only touch the greeting line.
        assert "Oui, je vais être là pour la rencontre Teams" in out
        assert out.endswith("À bientôt,")

    def test_strict_replaces_informal_with_different_informal(self):
        """When the LLM picked the wrong nickname (e.g. "Salut Alex," when
        the contact card pins "Salut Alexandre,"), strict mode rewrites it."""
        draft = "Salut Alex,\n\nDispo demain.\n\nÀ bientôt,"
        out = _ensure_starts_with_greeting(
            draft, "Salut Alexandre,", strict_replace=True,
        )
        assert out.startswith("Salut Alexandre,\n\n")
        assert "Salut Alex," not in out
        assert "Dispo demain" in out

    def test_strict_skip_when_already_matches(self):
        """No-op when the LLM already produced the mandatory opening."""
        draft = "Salut Alexandre,\n\nÇa roule pour demain.\n\nÀ bientôt,"
        out = _ensure_starts_with_greeting(
            draft, "Salut Alexandre,", strict_replace=True,
        )
        assert out == draft

    def test_legacy_soft_mode_preserves_llm_choice(self):
        """When strict_replace=False (the default — reply pipeline, no
        per-contact override) the legacy permissive behaviour stands:
        Monsieur stays Monsieur."""
        draft = "Monsieur Simon,\n\nJe vous écris.\n\nCordialement,"
        # No `strict_replace=` keyword — legacy callsites are unaffected.
        out = _ensure_starts_with_greeting(draft, "Salut Alexandre,")
        assert out == draft

    def test_strict_still_prepends_when_no_greeting_at_all(self):
        """Strict mode must still prepend when the LLM dropped the
        salutation entirely — same path as legacy."""
        draft = "Demain je suis dispo.\n\nÀ bientôt,"
        out = _ensure_starts_with_greeting(
            draft, "Salut Alexandre,", strict_replace=True,
        )
        assert out.startswith("Salut Alexandre,\n\n")
        assert "Demain je suis dispo" in out


# --------------------------------------------------------------------------- #
# _format_closing — "Merci!," fix
# --------------------------------------------------------------------------- #


class TestFormatClosing:
    def test_exclamation_preserves_terminal_punctuation(self):
        """The user wrote "Merci!" — appending a comma produces "Merci!,"
        which is not a thing. Keep the bang."""
        assert _format_closing("Merci!") == "Merci!"

    def test_question_mark_preserves_terminal_punctuation(self):
        """Same rule for "?" sign-offs (rare but real: "Bonne soirée?")."""
        assert _format_closing("Bonne soirée?") == "Bonne soirée?"

    def test_plain_word_gets_comma(self):
        assert _format_closing("Cordialement") == "Cordialement,"
        assert _format_closing("À bientôt") == "À bientôt,"
        assert _format_closing("Best regards") == "Best regards,"

    def test_compute_closing_hint_routes_through_format_closing(self):
        """End-to-end: "Merci!" in preferred_closings yields "Merci!", not
        "Merci!,"."""
        out = _compute_closing_hint(2, "FRENCH", ["Merci!"])
        assert out == "Merci!"


# --------------------------------------------------------------------------- #
# _compute_closing_hint — contact preferred_closing priority
# --------------------------------------------------------------------------- #


class TestContactClosingPriority:
    def test_contact_preferred_closing_beats_user_preferred(self):
        """Simon scenario at the unit level: a contact preferred_closing
        prepended to the list wins over the user's most-frequent closing."""
        # Simulates what the refine-text path does after the 2026-05-13 fix:
        # the route prepends `contact_preferred_closing` before calling
        # `_compute_closing_hint`.
        preferred = ["À bientôt,", "Merci!", "Cordialement"]
        out = _compute_closing_hint(2, "FRENCH", preferred)
        assert out == "À bientôt,"

    def test_falls_back_to_user_preferred_when_no_contact_signal(self):
        """No contact preferred_closing prepended → user's first entry wins
        (the legacy behaviour, unchanged)."""
        preferred = ["Merci!", "Cordialement"]
        out = _compute_closing_hint(2, "FRENCH", preferred)
        # The exclamation fix applies here too — but the priority is intact.
        assert out == "Merci!"
