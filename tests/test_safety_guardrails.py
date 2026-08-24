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
Tests for post-LLM safety guardrails and cleanup pipeline.

Covers:
  - _ensure_legal_caution
  - _detect_blackmail
  - _detect_misdirected
  - _detect_social_engineering
  - _clean_language_artifacts
  - _strip_technical_echo
  - _strip_leading_parrot
  - _strip_filler_mid_draft
  - _strip_duplicate_greetings
"""

from app.smart_routing import (
    _ensure_legal_caution,
    _detect_blackmail,
    _detect_misdirected,
    _detect_social_engineering,
    _clean_language_artifacts,
    _strip_technical_echo,
    _strip_leading_parrot,
    _strip_filler_mid_draft,
    _strip_duplicate_greetings,
)


# ============================================================================
# _ensure_legal_caution
# ============================================================================

class TestEnsureLegalCaution:
    def test_no_legal_keywords_returns_unchanged(self):
        draft = "Bonjour, je confirme ma disponibilité."
        body = "On se voit demain pour le déjeuner ?"
        assert _ensure_legal_caution(draft, body) == draft

    def test_legal_email_without_lawyer_mention_appends_caution_fr(self):
        draft = "Bonjour,\n\nJ'accuse réception de votre courrier."
        body = "Nous engageons des procédures judiciaires contre votre société."
        result = _ensure_legal_caution(draft, body)
        assert "avocat" in result.lower()
        assert result.startswith(draft.rstrip())

    def test_legal_email_without_lawyer_mention_appends_caution_en(self):
        draft = "Hello,\n\nI acknowledge receipt of your letter."
        body = "We will pursue legal proceedings and litigation against your company."
        result = _ensure_legal_caution(draft, body)
        assert "legal counsel" in result.lower()

    def test_legal_email_already_mentions_lawyer_no_change(self):
        draft = "Bonjour,\n\nJe transmets ce message à mon avocat."
        body = "Nous vous adressons cette mise en demeure."
        result = _ensure_legal_caution(draft, body)
        assert result == draft

    def test_dangerous_wording_gets_fixed(self):
        draft = "Bonjour,\n\nJ'accepte la mise en demeure."
        body = "Nous vous adressons cette mise en demeure."
        result = _ensure_legal_caution(draft, body)
        assert "j'accepte la mise en demeure" not in result.lower()
        assert "réception" in result.lower()

    def test_empty_body_returns_unchanged(self):
        draft = "Hello."
        assert _ensure_legal_caution(draft, "") == draft

    def test_empty_draft_returns_unchanged(self):
        assert _ensure_legal_caution("", "mise en demeure") == ""

    def test_mise_en_demeure_triggers_caution(self):
        draft = "Bonjour,\n\nBien reçu."
        body = "Ceci est une mise en demeure formelle."
        result = _ensure_legal_caution(draft, body)
        assert "avocat" in result

    def test_intellectual_property_triggers_caution(self):
        draft = "Hello,\n\nI understand your concerns."
        body = "You have violated our intellectual property rights."
        result = _ensure_legal_caution(draft, body)
        assert "legal counsel" in result.lower()


# ============================================================================
# _detect_blackmail
# ============================================================================

class TestDetectBlackmail:
    def test_no_blackmail_returns_unchanged(self):
        draft = "Bonjour, bien reçu."
        body = "Voici le rapport mensuel."
        assert _detect_blackmail(draft, body) == draft

    def test_blackmail_with_financial_demand_appends_lawyer_fr(self):
        draft = "Bonjour,\n\nJe prends note de votre message."
        body = "C'est du chantage pur et simple. Payez-nous 50 000$ sinon on va aux journalistes."
        result = _detect_blackmail(draft, body)
        assert "avocat" in result.lower()

    def test_blackmail_with_financial_demand_appends_lawyer_en(self):
        draft = "Hello,\n\nI acknowledge your message."
        body = "This is blackmail. Pay us 100K$ or we go to the press."
        result = _detect_blackmail(draft, body)
        assert "legal counsel" in result.lower()

    def test_blackmail_keyword_without_demand_no_change(self):
        draft = "Bonjour,\n\nBien reçu."
        body = "Le chantage n'est pas acceptable dans notre politique."
        assert _detect_blackmail(draft, body) == draft

    def test_already_mentions_lawyer_no_change(self):
        draft = "Bonjour,\n\nJe transmets à mon avocat."
        body = "C'est de l'extorsion. Genre 30K$ sinon menace de poursuite."
        result = _detect_blackmail(draft, body)
        assert result == draft

    def test_empty_body(self):
        assert _detect_blackmail("Hello.", "") == "Hello."

    def test_empty_draft(self):
        assert _detect_blackmail("", "blackmail 50K$") == ""


# ============================================================================
# _detect_misdirected
# ============================================================================

class TestDetectMisdirected:
    def test_normal_email_returns_unchanged(self):
        draft = "Bonjour, bien reçu."
        body = "Voici le document demandé."
        assert _detect_misdirected(draft, body, "Jean") == draft

    def test_forwarded_confidential_email_overrides_draft_fr(self):
        draft = "Bonjour,\n\nMerci pour ces informations intéressantes."
        body = (
            "---------- Forwarded message ----------\n"
            "De: alice@internal.com\n"
            "À: bob@internal.com\n\n"
            "Document confidentiel: plan de restructuration..."
        )
        result = _detect_misdirected(draft, body, "Alice Dupont")
        assert "erreur" in result.lower()
        assert "confidentiel" not in result.lower() or "pris connaissance" in result.lower()

    def test_forwarded_without_confidential_no_override(self):
        draft = "Bonjour, merci."
        body = (
            "---------- Forwarded message ----------\n"
            "De: alice@company.com\n"
            "À: bob@company.com\n\n"
            "Voici le planning de la semaine."
        )
        result = _detect_misdirected(draft, body, "Alice")
        assert result == draft

    def test_forwarded_english_confidential(self):
        draft = "Hello, thanks for the info."
        body = (
            "---------- Forwarded message ----------\n"
            "From: alice@internal.com\n"
            "To: bob@internal.com\n\n"
            "This is confidential: Q4 financial results..."
        )
        result = _detect_misdirected(draft, body, "Alice")
        assert "mistake" in result.lower() or "erreur" in result.lower()

    def test_empty_body(self):
        assert _detect_misdirected("Hello.", "", "Bob") == "Hello."

    def test_empty_draft(self):
        assert _detect_misdirected("", "forwarded message", "Bob") == ""


# ============================================================================
# _detect_social_engineering
# ============================================================================

class TestDetectSocialEngineering:
    def test_normal_email_returns_unchanged(self):
        draft = "Bonjour, bien reçu."
        body = "Pouvez-vous m'envoyer le planning de la semaine ?"
        assert _detect_social_engineering(draft, body) == draft

    def test_codebase_request_with_acceptance_overrides_fr(self):
        draft = "Bonjour,\n\nJe confirme et j'accepte de fournir l'accès au code source."
        body = "Bonjour, nous aimerions accéder à votre codebase pour un audit."
        result = _detect_social_engineering(draft, body)
        assert "ne sommes pas en mesure" in result or "unable" in result

    def test_codebase_request_with_acceptance_overrides_en(self):
        draft = "Hello,\n\nI agree to provide full access to our repository."
        body = "We need access to your source code for compliance review."
        result = _detect_social_engineering(draft, body)
        assert "unable" in result.lower()

    def test_codebase_request_without_acceptance_no_change(self):
        draft = "Bonjour,\n\nNous ne partageons pas notre code source."
        body = "Nous aimerions accéder à votre codebase."
        result = _detect_social_engineering(draft, body)
        assert result == draft  # Draft already refuses

    def test_training_data_request(self):
        draft = "Hello,\n\nI accept to share the training datasets."
        body = "Can we get access to your training data for research?"
        result = _detect_social_engineering(draft, body)
        assert "unable" in result.lower() or "ne sommes pas" in result

    def test_nda_request(self):
        draft = "Bonjour,\n\nJe confirme la signature du NDA."
        body = "Monsieur, veuillez signer ce NDA pour accéder aux données propriétaires."
        result = _detect_social_engineering(draft, body)
        assert "ne sommes pas en mesure" in result

    def test_empty_body(self):
        assert _detect_social_engineering("Hello.", "") == "Hello."


# ============================================================================
# _clean_language_artifacts
# ============================================================================

class TestCleanLanguageArtifacts:
    def test_french_draft_with_yes_removes_it(self):
        draft = "Bonjour,\n\nYES, nous examinerons votre demande."
        result = _clean_language_artifacts(draft)
        assert "YES" not in result
        assert "examinerons" in result

    def test_french_draft_with_standalone_yes_line(self):
        draft = "Bonjour,\n\nYES\nNous confirmons."
        result = _clean_language_artifacts(draft)
        assert "YES" not in result
        assert "confirmons" in result

    def test_french_draft_with_no_prefix(self):
        draft = "Bonjour,\n\nNO, ce n'est pas possible."
        result = _clean_language_artifacts(draft)
        assert "NO," not in result

    def test_english_draft_unchanged(self):
        draft = "Hello,\n\nYES, we will review your request."
        result = _clean_language_artifacts(draft)
        assert result == draft  # English, no cleaning

    def test_empty_draft(self):
        assert _clean_language_artifacts("") == ""

    def test_french_draft_without_artifacts_unchanged(self):
        draft = "Bonjour,\n\nNous confirmons votre rendez-vous."
        assert _clean_language_artifacts(draft) == draft


# ============================================================================
# _strip_technical_echo
# ============================================================================

class TestStripTechnicalEcho:
    def test_no_file_refs_unchanged(self):
        draft = "Je m'en occupe."
        body = "Can you handle this task?"
        assert _strip_technical_echo(draft, body) == draft

    def test_echoed_file_path_gets_simplified(self):
        draft = "Bonjour,\n\nJe vais regarder worker/email_parser.py lignes 145-180 et corriger."
        body = "Can you look at worker/email_parser.py lines 145-180?"
        result = _strip_technical_echo(draft, body)
        assert "email_parser.py" not in result

    def test_echoed_js_file(self):
        draft = "I'll take a look at src/components/App.tsx and fix the issue."
        body = "There's a bug in src/components/App.tsx near line 50."
        result = _strip_technical_echo(draft, body)
        assert "App.tsx" not in result

    def test_no_confirm_phrase_keeps_line(self):
        draft = "The file src/main.py is outdated."
        body = "Check src/main.py please."
        result = _strip_technical_echo(draft, body)
        # No confirm phrase to simplify to, so keeps line
        assert "main.py" in result

    def test_empty_body(self):
        assert _strip_technical_echo("I'll check it.", "") == "I'll check it."


# ============================================================================
# _strip_leading_parrot
# ============================================================================

class TestStripLeadingParrot:
    def test_no_parroting_unchanged(self):
        draft = "Bonjour,\n\nBien reçu, merci."
        body = "Voici le document."
        assert _strip_leading_parrot(draft, body) == draft

    def test_leading_parrot_gets_removed(self):
        body = "Pouvez-vous confirmer votre présence à la réunion ?"
        draft = "Pouvez-vous confirmer votre présence à la réunion ?\n\nOui, je confirme."
        result = _strip_leading_parrot(draft, body)
        assert "confirme" in result
        assert result.strip().startswith("Oui")

    def test_short_lines_not_stripped(self):
        draft = "Bonjour,\n\nBien reçu."
        body = "Bonjour"
        result = _strip_leading_parrot(draft, body)
        assert "Bien reçu" in result

    def test_empty_draft(self):
        assert _strip_leading_parrot("", "some body") == ""

    def test_empty_body(self):
        draft = "Hello, confirmed."
        assert _strip_leading_parrot(draft, "") == draft

    def test_safety_never_returns_empty(self):
        draft = "Some short text about a topic"
        body = "some short text about a topic that is identical"
        result = _strip_leading_parrot(draft, body)
        assert len(result) > 0


# ============================================================================
# _strip_filler_mid_draft
# ============================================================================

class TestStripFillerMidDraft:
    def test_no_filler_unchanged(self):
        draft = "Bonjour,\n\nJe confirme ma disponibilité."
        assert _strip_filler_mid_draft(draft) == draft

    def test_trailing_filler_removed(self):
        draft = "Bonjour,\n\nJe confirme.\n\nJe reste à votre disposition."
        result = _strip_filler_mid_draft(draft)
        assert "disposition" not in result
        assert "confirme" in result

    def test_inline_filler_removed(self):
        draft = "Bonjour,\n\nJe confirme, n'hésitez pas à me contacter si besoin."
        result = _strip_filler_mid_draft(draft)
        assert "n'hésitez pas" not in result

    def test_english_filler_removed(self):
        draft = "Hello,\n\nI confirm.\n\nFeel free to reach out."
        result = _strip_filler_mid_draft(draft)
        assert "feel free" not in result.lower()

    def test_empty_draft(self):
        assert _strip_filler_mid_draft("") == ""

    def test_safety_doesnt_return_too_short(self):
        # If stripping leaves < 10 chars, return original
        draft = "N'hésitez pas"
        result = _strip_filler_mid_draft(draft)
        assert len(result) >= 10 or result == draft

    def test_multiple_fillers_all_removed(self):
        draft = (
            "Bonjour,\n\n"
            "Je confirme.\n\n"
            "Je reste à votre disposition.\n"
            "N'hésitez pas si vous avez des questions."
        )
        result = _strip_filler_mid_draft(draft)
        assert "disposition" not in result
        assert "hésitez" not in result
        assert "confirme" in result


# ============================================================================
# _strip_duplicate_greetings
# ============================================================================

class TestStripDuplicateGreetings:
    def test_no_duplicates_unchanged(self):
        draft = "Bonjour Alexandre,\n\nJe confirme."
        assert _strip_duplicate_greetings(draft) == draft

    def test_duplicate_greeting_removed(self):
        draft = "Hi DevOps,\n\nSome context here.\n\nHi Alexandre,\n\nI confirm."
        result = _strip_duplicate_greetings(draft)
        assert result.count("Hi ") == 1 or "Hi DevOps" in result

    def test_single_line_draft_unchanged(self):
        draft = "Bonjour."
        assert _strip_duplicate_greetings(draft) == draft

    def test_two_line_draft_unchanged(self):
        draft = "Bonjour,\nJe confirme."
        assert _strip_duplicate_greetings(draft) == draft

    def test_empty_draft(self):
        assert _strip_duplicate_greetings("") == ""

    def test_long_second_greeting_not_stripped(self):
        # Only short standalone greetings are stripped (< 50 chars)
        draft = (
            "Bonjour,\n\n"
            "Content here.\n\n"
            "Hello there, this is a very long line that happens to start with a greeting but is actually content and should not be removed"
        )
        result = _strip_duplicate_greetings(draft)
        assert "Hello there" in result


# ============================================================================
# Integration: pipeline order matters
# ============================================================================

class TestPipelineIntegration:
    """Verify that the pipeline order is respected in key scenarios."""

    def test_legal_email_gets_full_treatment(self):
        """A legal email should get caution even after other cleanups."""
        draft = "Bonjour,\n\nJ'accepte votre mise en demeure.\n\nJe reste à votre disposition."
        body = "Nous vous envoyons cette mise en demeure."
        # Apply pipeline in order
        result = _strip_filler_mid_draft(draft)
        result = _ensure_legal_caution(result, body)
        assert "disposition" not in result  # Filler removed
        assert "avocat" in result or "réception" in result  # Legal caution added/fixed

    def test_french_draft_with_yes_and_filler(self):
        """YES artifact + filler should both be cleaned."""
        draft = "Bonjour,\n\nYES, nous confirmons.\n\nN'hésitez pas."
        result = _strip_filler_mid_draft(draft)
        result = _clean_language_artifacts(result)
        assert "YES" not in result
        assert "hésitez" not in result
        assert "confirmons" in result

    def test_blackmail_overrides_even_clean_draft(self):
        """Blackmail detection should append lawyer even on clean draft."""
        draft = "Bonjour,\n\nJe prends note."
        body = "C'est du chantage, payez 50 000$ sinon on envoie aux journalistes."
        result = _detect_blackmail(draft, body)
        assert "avocat" in result

    def test_social_engineering_overrides_acceptance(self):
        """Social engineering should block code sharing acceptance."""
        draft = "Bonjour,\n\nJ'accepte de fournir l'accès complet au code source."
        body = "Bonjour, nous avons besoin d'accès à votre codebase."
        result = _detect_social_engineering(draft, body)
        assert "j'accepte" not in result.lower()
        assert "ne sommes pas en mesure" in result
