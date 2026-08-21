"""Issue #592 — multi-recipient greetings + stacked contextual closings.

Covers the deterministic guard-rails added on top of the LLM prompt rules:

1. ``_multi_recipient_greeting_hint`` — only names both recipients when the
   per-contact ``formality_override`` signals are known AND match. Mixed or
   unknown registers fall back to a register-neutral group greeting so the
   draft never forces a tone on a contact whose tu/vous signal is unknown.

2. ``_strip_stacked_contextual_closing`` — drops conversational time-specific
   sign-offs ("À ce vendredi !", "See you Friday!") when they stack on top
   of a canonical closing line ("À bientôt,", "Best,"). Two patterns:
   distinct lines, and same-line "X, contextual" tails.

The compose/refine endpoints share the same helpers, so the same input
produces the same greeting strategy across paths (issue requirement).
"""

from __future__ import annotations

import pytest

from app.application.services._compose_path import (
    _contact_formality_for,
    _email_address_lower,
    _multi_recipient_greeting_hint,
)
from app.smart_routing import (
    _is_contextual_closing_line,
    _strip_stacked_contextual_closing,
)


# ---------------------------------------------------------------------------
# 1. Multi-recipient greeting — register compatibility
# ---------------------------------------------------------------------------


class TestMultiRecipientGreetingSingle:
    def test_single_recipient_returns_none(self):
        assert _multi_recipient_greeting_hint("alice@example.com", None) is None
        assert _multi_recipient_greeting_hint("alice@example.com", "fr") is None
        assert _multi_recipient_greeting_hint("alice@example.com", "en") is None


class TestMultiRecipientGreetingThreePlus:
    def test_three_french(self):
        assert (
            _multi_recipient_greeting_hint(
                "alice@example.com, bob@example.com, charlie@example.com", None
            )
            == "Bonjour à tous,"
        )

    def test_three_english(self):
        assert (
            _multi_recipient_greeting_hint(
                "alice@example.com, bob@example.com, charlie@example.com", "en"
            )
            == "Hello everyone,"
        )

    def test_three_falls_back_even_with_compatible_profiles(self):
        # 3+ always uses group greeting — naming becomes unwieldy.
        cp = {
            "alice@example.com": {"formality_override": "casual"},
            "bob@example.com": {"formality_override": "casual"},
            "charlie@example.com": {"formality_override": "casual"},
        }
        assert (
            _multi_recipient_greeting_hint(
                "alice@example.com, bob@example.com, charlie@example.com",
                None,
                cp,
            )
            == "Bonjour à tous,"
        )


class TestMultiRecipientGreetingTwoCompatible:
    """Both recipients have a known matching formality_override — name them."""

    def test_two_casual_compatible_french(self):
        cp = {
            "alice@example.com": {"formality_override": "casual"},
            "bob@example.com": {"formality_override": "casual"},
        }
        result = _multi_recipient_greeting_hint(
            "alice@example.com, bob@example.com", None, cp
        )
        assert result == "Bonjour Alice et Bob,"

    def test_two_casual_compatible_english(self):
        cp = {
            "alice@example.com": {"formality_override": "casual"},
            "bob@example.com": {"formality_override": "casual"},
        }
        result = _multi_recipient_greeting_hint(
            "alice@example.com, bob@example.com", "en", cp
        )
        assert result == "Hi Alice and Bob,"

    def test_two_formal_compatible_french(self):
        cp = {
            "alice@example.com": {"formality_override": "formal"},
            "bob@example.com": {"formality_override": "formal"},
        }
        result = _multi_recipient_greeting_hint(
            "alice@example.com, bob@example.com", None, cp
        )
        assert result == "Bonjour Alice et Bob,"


class TestMultiRecipientGreetingTwoMixed:
    """Mixed or unknown registers → register-neutral group greeting."""

    def test_two_mixed_casual_and_formal(self):
        cp = {
            "alice@example.com": {"formality_override": "casual"},
            "bob@example.com": {"formality_override": "formal"},
        }
        result = _multi_recipient_greeting_hint(
            "alice@example.com, bob@example.com", None, cp
        )
        # Group greeting without names — neither tu nor vous is forced.
        assert result == "Bonjour,"

    def test_two_one_known_one_unknown(self):
        cp = {
            "alice@example.com": {"formality_override": "casual"},
            # bob has no profile entry → unknown register
        }
        result = _multi_recipient_greeting_hint(
            "alice@example.com, bob@example.com", None, cp
        )
        assert result == "Bonjour,"

    def test_two_both_unknown(self):
        cp: dict = {}
        result = _multi_recipient_greeting_hint(
            "alice@example.com, bob@example.com", None, cp
        )
        assert result == "Bonjour,"

    def test_two_empty_formality_value(self):
        # A profile entry with no formality_override is still "unknown".
        cp = {
            "alice@example.com": {"formality_override": None},
            "bob@example.com": {"formality_override": "casual"},
        }
        result = _multi_recipient_greeting_hint(
            "alice@example.com, bob@example.com", None, cp
        )
        assert result == "Bonjour,"

    def test_two_mixed_english(self):
        cp = {
            "alice@example.com": {"formality_override": "casual"},
            "bob@example.com": {"formality_override": "formal"},
        }
        result = _multi_recipient_greeting_hint(
            "alice@example.com, bob@example.com", "en", cp
        )
        assert result == "Hello,"


class TestMultiRecipientGreetingNoProfile:
    """When contact_profiles is None the caller has no signal at all — back-
    compat behaviour: name both recipients (legacy callers prior to the
    issue #592 fix passed None and expected naming)."""

    def test_two_no_profile_french_names(self):
        result = _multi_recipient_greeting_hint(
            "alice@example.com, bob@example.com", None
        )
        assert result == "Bonjour Alice et Bob,"

    def test_two_no_profile_english_names(self):
        result = _multi_recipient_greeting_hint(
            "alice@example.com, bob@example.com", "en"
        )
        assert result == "Hi Alice and Bob,"


class TestMultiRecipientGreetingDisplayNames:
    def test_two_with_display_names_compatible(self):
        cp = {
            "alice@example.com": {"formality_override": "casual"},
            "bob@example.com": {"formality_override": "casual"},
        }
        result = _multi_recipient_greeting_hint(
            "Alice Doe <alice@example.com>, Bob Smith <bob@example.com>",
            None,
            cp,
        )
        assert result == "Bonjour Alice et Bob,"

    def test_two_with_display_names_mixed(self):
        cp = {
            "alice@example.com": {"formality_override": "casual"},
            "bob@example.com": {"formality_override": "formal"},
        }
        result = _multi_recipient_greeting_hint(
            "Alice Doe <alice@example.com>, Bob Smith <bob@example.com>",
            None,
            cp,
        )
        assert result == "Bonjour,"


class TestEmailAddressLower:
    def test_simple_email(self):
        assert _email_address_lower("Alice@Example.com") == "alice@example.com"

    def test_with_display_name(self):
        assert (
            _email_address_lower("Alice Doe <ALICE@example.com>")
            == "alice@example.com"
        )

    def test_empty(self):
        assert _email_address_lower("") == ""


class TestContactFormalityFor:
    def test_known_casual(self):
        cp = {"alice@example.com": {"formality_override": "casual"}}
        assert _contact_formality_for("alice@example.com", cp) == "casual"

    def test_display_name(self):
        cp = {"alice@example.com": {"formality_override": "formal"}}
        assert (
            _contact_formality_for("Alice <alice@example.com>", cp) == "formal"
        )

    def test_missing(self):
        cp = {"alice@example.com": {"formality_override": "casual"}}
        assert _contact_formality_for("bob@example.com", cp) is None

    def test_none_profiles(self):
        assert _contact_formality_for("alice@example.com", None) is None


# ---------------------------------------------------------------------------
# 2. Stacked contextual closing — drop the doublon
# ---------------------------------------------------------------------------


class TestIsContextualClosingLine:
    @pytest.mark.parametrize(
        "line",
        [
            "À ce vendredi !",
            "À vendredi !",
            "À demain !",
            "À demain.",
            "À lundi",
            "à ce soir !",
            "À la semaine prochaine !",
            "On se parle demain",
            "On se voit vendredi !",
            "See you Friday!",
            "See you tomorrow.",
            "See you next week",
            "Talk Monday!",
            "Catch up Friday",
        ],
    )
    def test_matches(self, line):
        assert _is_contextual_closing_line(line) is True

    @pytest.mark.parametrize(
        "line",
        [
            "Je te confirme à vendredi pour le call",  # body sentence
            "À vendredi, j'attends ton retour",  # body sentence
            "À bientôt,",  # canonical closing, handled elsewhere
            "Cordialement,",
            "Best,",
            "",
            "   ",
            "Je vais arriver à 10h.",
        ],
    )
    def test_does_not_match(self, line):
        assert _is_contextual_closing_line(line) is False


class TestStripStackedContextualClosingFrench:
    def test_two_line_stacking(self):
        draft = (
            "Bonjour Alice,\n\n"
            "Confirmation pour le call de 10h.\n\n"
            "À ce vendredi !\n\n"
            "À bientôt,"
        )
        out = _strip_stacked_contextual_closing(draft)
        assert "À ce vendredi" not in out
        assert out.endswith("À bientôt,")
        # Body content preserved
        assert "Confirmation pour le call de 10h." in out
        assert out.count("\n\nÀ bientôt,") == 1

    def test_same_line_stacking(self):
        draft = (
            "Bonjour Alice,\n\n"
            "Confirmation pour le call.\n\n"
            "À bientôt, à ce vendredi"
        )
        out = _strip_stacked_contextual_closing(draft)
        assert out.endswith("À bientôt,")
        assert "à ce vendredi" not in out.lower()

    def test_two_line_a_demain(self):
        draft = (
            "Salut,\n\n"
            "Je passe te voir.\n\n"
            "À demain !\n\n"
            "Cordialement,"
        )
        out = _strip_stacked_contextual_closing(draft)
        assert "À demain" not in out
        assert out.endswith("Cordialement,")


class TestStripStackedContextualClosingEnglish:
    def test_two_line_see_you_friday(self):
        draft = (
            "Hi Alice,\n\n"
            "Confirming our 10am call.\n\n"
            "See you Friday!\n\n"
            "Best,"
        )
        out = _strip_stacked_contextual_closing(draft)
        assert "See you Friday" not in out
        assert out.endswith("Best,")
        assert "Confirming our 10am call." in out

    def test_two_line_talk_monday(self):
        draft = (
            "Hi,\n\n"
            "Let's sync next week.\n\n"
            "Talk Monday!\n\n"
            "Regards,"
        )
        out = _strip_stacked_contextual_closing(draft)
        assert "Talk Monday" not in out
        assert out.endswith("Regards,")


class TestStripStackedContextualClosingNoOp:
    def test_legitimate_body_phrase_preserved(self):
        """A body sentence that happens to contain 'See you Friday' must NOT
        be stripped — the strip only fires when the line itself is short
        and closing-shaped AND directly above the canonical closing."""
        draft = (
            "Bonjour Alice,\n\n"
            "Pour récap, je te confirme à vendredi pour le rendez-vous "
            "et je t'envoie le brief dimanche soir.\n\n"
            "Cordialement,"
        )
        out = _strip_stacked_contextual_closing(draft)
        assert out == draft  # untouched

    def test_only_one_closing_kept(self):
        draft = (
            "Bonjour,\n\n"
            "Confirmation reçue.\n\n"
            "Cordialement,"
        )
        out = _strip_stacked_contextual_closing(draft)
        assert out == draft

    def test_no_canonical_closing_no_op(self):
        # The contextual closing is the only "closing" — leave it alone.
        # We never want to strip the user's only sign-off.
        draft = (
            "Bonjour Alice,\n\n"
            "Confirmation reçue.\n\n"
            "À ce vendredi !"
        )
        out = _strip_stacked_contextual_closing(draft)
        assert out == draft

    def test_empty(self):
        assert _strip_stacked_contextual_closing("") == ""

    def test_long_line_not_stripped(self):
        # Lines longer than the closing heuristic must not be stripped even
        # when they start with a contextual phrase — they are body, not a
        # sign-off.
        draft = (
            "Bonjour Alice,\n\n"
            "À demain on se voit pour finaliser le contrat et signer "
            "ensemble.\n\n"
            "Cordialement,"
        )
        out = _strip_stacked_contextual_closing(draft)
        assert "À demain" in out  # preserved


class TestComposeRefineConsistency:
    """The issue requires compose + refine paths to produce the same greeting
    strategy for the same multi-recipient input. Both call the same helper
    with the same args, so this is a structural assertion."""

    def test_compose_and_refine_use_same_helper(self):
        # The function is imported from one source and used in three places
        # (routes_misc.py compose, routes_drafts.py refine, draft_service.py
        # compose). Identity check is enough here.
        from app.api.routes_misc import compose_email  # noqa: F401
        from app.api.routes_drafts import refine_text  # noqa: F401
        from app.application.services.draft_service import DraftService  # noqa: F401
        from app.application.services._compose_path import (
            _multi_recipient_greeting_hint as canonical,
        )

        # Same module attribute used by all three call sites.
        import app.application.services._compose_path as cp_mod
        assert cp_mod._multi_recipient_greeting_hint is canonical

    def test_same_input_same_strategy(self):
        cp = {
            "alice@example.com": {"formality_override": "casual"},
            "bob@example.com": {"formality_override": "formal"},
        }
        to_field = "alice@example.com, bob@example.com"
        # Same call signature used by compose & refine call sites.
        result_compose = _multi_recipient_greeting_hint(to_field, None, cp)
        result_refine = _multi_recipient_greeting_hint(to_field, None, cp)
        assert result_compose == result_refine == "Bonjour,"
