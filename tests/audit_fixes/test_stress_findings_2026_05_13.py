"""
Audit fix — 2026-05-13 stress test findings
============================================

The 1000-case post-LLM pipeline stress test (tools/stress_test_pipeline.py)
surfaced three pipeline bugs in addition to the scrubber regression fixed
earlier the same day:

- Bug B — `_truncate_for_short_body` strips user-notes content when the
  source email is < 100 chars. The function decided "the source is short
  so the reply should be short too" — but when the user passes /expand
  notes, those notes ARE the intended reply content.

- Bug C — `_strip_markdown_artifacts` removed `- ` / `* ` bullet markers
  before `strip_reasoning_leakage` got a chance to detect bullet-style
  reasoning enumerations. The leakage detector relies on the markers.

- Bug D — `_compute_greeting_hint` returned ``""`` when sender_name was
  empty. An empty hint causes `_enforce_greeting` to STRIP whatever
  greeting the LLM emitted (intended for hot-thread continuation),
  leaving the draft opening cold.

These tests pin the post-fix behavior.
"""

from __future__ import annotations

from app.smart_routing import _extract_first_name, _truncate_for_short_body
from app.utils.draft_cleanup import strip_reasoning_leakage
from app.prompts import _compute_greeting_hint
from app.prompts.identity import _signature_name_matching_email, _signature_person_name


# -- Bug B: truncate respects user_context ----------------------------------


class TestTruncateForShortBodyUserContext:
    def test_long_draft_kept_when_user_context_present(self):
        """User typed /expand notes → reply should not be truncated.

        Source body is 28 chars (very short), so the legacy heuristic
        would have stripped down to greeting + 1 sentence. With notes
        present, the full body must survive.
        """
        body = "Tu confirmes pour vendredi ?"  # 28 chars
        draft = (
            "Salut Alex,\n\n"
            "Oui, je confirme pour vendredi. "
            "Je passe vers 14h avec le dossier Pinterest et les devis Lambda. "
            "On fait le point sur la suite ensemble.\n\n"
            "À bientôt,"
        )
        user_context = (
            "Confirmer demain 15h, apporter le dossier Pinterest et "
            "le devis Lambda."
        )

        result = _truncate_for_short_body(draft, body, user_context=user_context)

        # Both substantive sentences must survive.
        assert "Pinterest" in result
        assert "Lambda" in result
        assert result == draft

    def test_short_body_still_truncates_without_user_context(self):
        """Legacy short-source truncation still applies when no notes."""
        body = "OK ?"  # 4 chars → max 1 content sentence
        draft = (
            "Salut Alex,\n\n"
            "Oui, c'est bon.\n\n"
            "J'ajoute un complément ici qui devrait être truncé.\n\n"
            "À bientôt,"
        )

        result = _truncate_for_short_body(draft, body, user_context="")

        # The third paragraph must be dropped.
        assert "complément" not in result

    def test_long_body_no_truncation_either_way(self):
        """Source >= 100 chars: function is a no-op regardless of notes."""
        body = "x" * 200
        draft = "Salut,\n\nLine 1.\n\nLine 2.\n\nLine 3.\n\nÀ bientôt,"

        assert _truncate_for_short_body(draft, body) == draft
        assert _truncate_for_short_body(draft, body, user_context="anything") == draft


# -- Bug C: reasoning leakage detects bullets BEFORE markdown is stripped ---


class TestReasoningLeakageDetectsBullets:
    def test_bullet_reasoning_block_is_stripped(self):
        """Bulleted reasoning enumeration must be detected and removed.

        The combination of "Je dois X :" header + `- ` bullets is the
        classic Haiku reasoning-leak shape. The pipeline must run this
        check before any step strips the bullet markers.
        """
        draft = (
            "Je dois être direct mais poli :\n"
            "- Vérifier l'instruction utilisateur\n"
            "- Adapter la critique au ton\n"
            "\n"
            "Salut Alex,\n"
            "\n"
            "Oui je confirme.\n"
            "\n"
            "À bientôt,"
        )

        result = strip_reasoning_leakage(draft)

        assert "Je dois" not in result, (
            "Reasoning header survived the strip pass."
        )
        assert "Vérifier l'instruction" not in result, (
            "Reasoning bullet survived the strip pass."
        )
        assert "Adapter la critique" not in result
        # Body must survive.
        assert "Oui je confirme" in result
        assert result.startswith("Salut Alex,") or "Salut Alex," in result.split("\n")[0]


# -- Bug D: _compute_greeting_hint falls back on empty sender_name ----------


class TestComputeGreetingHintFallback:
    def test_french_informal_fallback_when_sender_empty(self):
        result = _compute_greeting_hint(
            sender_name="", formality=2, language="FRENCH",
        )
        assert result == "Salut,"

    def test_french_formal_fallback_when_sender_empty(self):
        result = _compute_greeting_hint(
            sender_name="", formality=4, language="FRENCH",
        )
        assert result == "Bonjour,"

    def test_english_informal_fallback_when_sender_empty(self):
        result = _compute_greeting_hint(
            sender_name="", formality=2, language="ENGLISH",
        )
        assert result == "Hi,"

    def test_english_formal_fallback_when_sender_empty(self):
        result = _compute_greeting_hint(
            sender_name="", formality=4, language="ENGLISH",
        )
        assert result == "Hello,"

    def test_present_sender_unaffected(self):
        """Existing behavior with a real sender name is preserved."""
        result = _compute_greeting_hint(
            sender_name="Alexandre Simon", formality=2, language="FRENCH",
        )
        # Some specific greeting (not the bare fallback).
        assert result != "Salut,"
        assert "Alex" in result or "Salut" in result

    def test_branded_display_name_uses_personal_email_local_part(self):
        result = _compute_greeting_hint(
            sender_name="Crypto Formation",
            formality=2,
            language="FRENCH",
            sender_email="alexandre.simon@example.com",
        )

        assert result == "Salut Alexandre,"

    def test_signature_expands_short_email_first_name(self):
        body = (
            "Salut Nat,\n\n"
            "Petit test.\n\n"
            "À bientôt,\n"
            "Alexandre Simon\n"
            "Co-fondateur, Agentys"
        )

        result = _compute_greeting_hint(
            sender_name="Crypto Formation",
            formality=2,
            language="FRENCH",
            sender_email="alex.simon@example.com",
            signature_text=body,
        )

        assert result == "Salut Alexandre,"

    def test_signature_recovers_person_when_brand_email_has_no_name_signal(self):
        body = (
            "Bonjour Nat,\n\n"
            "As-tu essayé l'application aujourd'hui ? Je vais continuer à l'utiliser.\n\n"
            "A+\n\n"
            "Alexandre Simon\n"
            "Co-fondateur d'Agentys"
        )

        result = _compute_greeting_hint(
            sender_name="Crypto Université",
            formality=2,
            language="FRENCH",
            sender_email="cours.universite@gmail.com",
            signature_text=body,
        )

        assert result == "Salut Alexandre,"

    def test_signature_recovers_first_name_when_display_is_last_name_only(self):
        body = (
            "Bonjour,\n\n"
            "Voici le retour demandé.\n\n"
            "Alexandra Simon\n"
            "Directrice marketing"
        )

        result = _compute_greeting_hint(
            sender_name="Simon",
            formality=2,
            language="FRENCH",
            sender_email="a.simon@example.com",
            signature_text=body,
        )

        assert result == "Salut Alexandra,"

    def test_explicit_service_display_name_stays_generic(self):
        result = _compute_greeting_hint(
            sender_name="Acme Support",
            formality=2,
            language="FRENCH",
            sender_email="john.doe@example.com",
        )

        assert result == "Salut,"

    def test_explicit_service_display_name_ignores_unmatched_signature_name(self):
        body = (
            "Bonjour,\n\n"
            "Votre ticket est bien pris en compte.\n\n"
            "John Doe\n"
            "Support"
        )

        result = _compute_greeting_hint(
            sender_name="Acme Support",
            formality=2,
            language="FRENCH",
            sender_email="john.doe@acme.example",
            signature_text=body,
        )

        assert result == "Salut,"

    def test_unknown_sender_name_uses_email_local_part(self):
        result = _compute_greeting_hint(
            sender_name="Unknown",
            formality=2,
            language="FRENCH",
            sender_email="emilie.gauthier@example.com",
        )

        assert result == "Salut Emilie,"

    def test_unknown_sender_name_without_email_uses_generic_fallback(self):
        result = _compute_greeting_hint(
            sender_name="Unknown",
            formality=2,
            language="FRENCH",
        )

        assert result == "Salut,"


class TestSimpleTemplateFirstNameExtraction:
    def test_branded_display_name_uses_personal_email_local_part(self):
        result = _extract_first_name(
            '"Crypto Formation" <alexandre.simon@example.com>'
        )

        assert result == "Alexandre"

    def test_signature_expands_short_email_first_name(self):
        body = (
            "À bientôt,\n"
            "Alexandre Simon\n"
            "Co-fondateur"
        )

        result = _extract_first_name(
            '"Crypto Formation" <alex.simon@example.com>',
            signature_text=body,
        )

        assert result == "Alexandre"

    def test_signature_recovers_person_when_brand_email_has_no_name_signal(self):
        body = (
            "A+\n\n"
            "Alexandre Simon\n"
            "Co-fondateur d'Agentys"
        )

        result = _extract_first_name(
            '"Crypto Université" <cours.universite@gmail.com>',
            signature_text=body,
        )

        assert result == "Alexandre"

    def test_explicit_service_display_name_returns_no_first_name(self):
        result = _extract_first_name('"Acme Support" <john.doe@example.com>')

        assert result == ""

    def test_explicit_service_display_name_ignores_matching_signature_name(self):
        body = (
            "Bonjour,\n\n"
            "Votre ticket est bien pris en compte.\n\n"
            "John Doe\n"
            "Support"
        )

        result = _extract_first_name(
            '"Acme Support" <john.doe@example.com>',
            signature_text=body,
        )

        assert result == ""


class TestSignatureNameMatchingEmail:
    def test_extracts_signature_name_matching_email_local_part(self):
        body = (
            "Merci,\n\n"
            "Alexandre Simon\n"
            "Co-fondateur, Agentys"
        )

        result = _signature_name_matching_email(
            body,
            "alex.simon@example.com",
        )

        assert result == "Alexandre Simon"

    def test_ignores_signature_name_unrelated_to_email(self):
        body = (
            "Merci,\n\n"
            "Nathan Roy\n"
            "Agentys"
        )

        result = _signature_name_matching_email(
            body,
            "alex.simon@example.com",
        )

        assert result == ""

    def test_extracts_plausible_signature_name_without_email_match(self):
        body = (
            "A+\n\n"
            "Alexandre Simon\n"
            "Co-fondateur d'Agentys"
        )

        result = _signature_person_name(body)

        assert result == "Alexandre Simon"
