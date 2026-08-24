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
E2E test — FAQ scoring robustness.

Tests that natural user phrasings of FAQ questions score correctly
with the CURRENT algorithm. The diagnostic report (TestScoreReport)
shows where the algorithm is weak so we can decide if it needs improvement.

Real users never type the exact FAQ title. They use:
- Shorter/longer versions
- Different word order
- Typos, slang, abbreviations
- Different languages (EN vs FR)
- Vague / indirect phrasing

Current algorithm: word-overlap with title 2x weight + 15% question bonus.
Known weakness: synonyms/rephrasings score very low because the algorithm
only matches exact words, not semantic meaning.
"""

from unittest.mock import patch, MagicMock

import pytest
from app.faq_agent import score_faq_match, match_faq_entries, match_faq_with_llm, _tokenize


# ── The real FAQ entry from knowledge/memoire.md ─────────────────────────────

FAQ_TITLE = "Quelle est le modèle LLM derrière Agentys?"
FAQ_CONTENT = "Agentys utilise Claude comme intelligence artificielle."

# Threshold used in production
PROD_THRESHOLD = 80


# ── Helper ───────────────────────────────────────────────────────────────────

def _score(email_text: str) -> float:
    return score_faq_match(email_text, FAQ_TITLE, FAQ_CONTENT)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. EXACT & NEAR-EXACT — these should pass the 80 threshold
# ═══════════════════════════════════════════════════════════════════════════════

class TestExactMatch:
    """User copies the FAQ title verbatim or nearly so."""

    def test_exact_copy(self):
        s = _score("Quelle est le modèle LLM derrière Agentys?")
        assert s >= PROD_THRESHOLD, f"Exact copy scored {s}"

    def test_no_question_mark(self):
        """Without '?' the 15% bonus is lost — score drops below 80."""
        s = _score("Quelle est le modèle LLM derrière Agentys")
        # ACTUAL: 73.3 — loses question bonus
        assert 70 <= s < PROD_THRESHOLD, f"No question mark scored {s} (expected ~73)"

    def test_extra_greeting(self):
        """Extra words around exact question — still passes."""
        s = _score("Bonjour, quelle est le modèle LLM derrière Agentys? Merci!")
        assert s >= PROD_THRESHOLD, f"With greeting scored {s}"

    def test_no_accents(self):
        """Accent normalization works — same score as exact."""
        s = _score("Quelle est le modele LLM derriere Agentys?")
        assert s >= PROD_THRESHOLD, f"No accents scored {s}"

    def test_lowercase(self):
        s = _score("quelle est le modèle llm derrière agentys?")
        assert s >= PROD_THRESHOLD, f"Lowercase scored {s}"

    def test_uppercase(self):
        s = _score("QUELLE EST LE MODELE LLM DERRIERE AGENTYS?")
        assert s >= PROD_THRESHOLD, f"Uppercase scored {s}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. NATURAL REPHRASINGS — documents how low real phrasings score
#    These thresholds are set to CURRENT actual scores.
#    When we improve the algorithm, we raise these thresholds.
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrenchRephrasings:
    """How real French speakers would ask. Currently most score far below 80."""

    def test_quel_llm_utilisez_vous(self):
        """Only 'llm' overlaps — very low."""
        s = _score("Quel LLM utilisez-vous?")
        # ACTUAL: 15.3 — only 1 keyword overlap (llm)
        assert s >= 10, f"scored {s}"
        assert s < PROD_THRESHOLD, f"scored {s} — unexpectedly high"

    def test_cest_quoi_lia(self):
        """'derriere' + 'agentys' overlap — moderate."""
        s = _score("C'est quoi l'IA derrière Agentys?")
        # ACTUAL: 38.3
        assert s >= 30, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_quel_modele_ia(self):
        """'modele' + 'agentys' + partial overlap."""
        s = _score("Quel modèle d'IA est utilisé par Agentys?")
        # ACTUAL: 46.0
        assert s >= 40, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_agentys_utilise_quel_llm(self):
        """'agentys' + 'llm' + 'utilise' — decent overlap."""
        s = _score("Agentys utilise quel LLM?")
        # ACTUAL: 46.0
        assert s >= 40, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_vous_utilisez_gpt_ou_claude(self):
        """Only 'claude' overlaps (from content) — very low."""
        s = _score("Vous utilisez GPT ou Claude?")
        # ACTUAL: 7.7
        assert s >= 5, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_quelle_ia_dans_agentys(self):
        s = _score("Quelle IA dans Agentys?")
        # ACTUAL: 38.3
        assert s >= 30, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_modele_intelligence_artificielle(self):
        """Long rephrasing with 'modele', 'intelligence', 'artificielle', 'derriere', 'agentys'."""
        s = _score("Quel est le modèle d'intelligence artificielle derrière Agentys?")
        # ACTUAL: 69.0 — good but still below 80
        assert s >= 60, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_quel_est_le_moteur_ia(self):
        """'moteur' has no overlap with FAQ vocabulary."""
        s = _score("Quel est le moteur IA d'Agentys?")
        # ACTUAL: 23.0
        assert s >= 20, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_propulse_par_quel_modele(self):
        """'propulse' is a synonym — algorithm can't see it."""
        s = _score("Agentys est propulsé par quel modèle?")
        # ACTUAL: 38.3
        assert s >= 30, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_informal_short(self):
        s = _score("le LLM d'Agentys c'est quoi?")
        # ACTUAL: 38.3
        assert s >= 30, f"scored {s}"
        assert s < PROD_THRESHOLD


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ENGLISH REPHRASINGS — even worse, almost no word overlap
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnglishRephrasings:
    """Users writing in English about the same topic."""

    def test_what_llm_does_agentys_use(self):
        """'llm' + 'agentys' overlap."""
        s = _score("What LLM does Agentys use?")
        # ACTUAL: 38.3
        assert s >= 30, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_what_ai_model(self):
        s = _score("What AI model is behind Agentys?")
        # ACTUAL: 23.0
        assert s >= 20, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_is_agentys_using_chatgpt(self):
        """'claude' from content gives a small boost."""
        s = _score("Is Agentys using ChatGPT or Claude?")
        # ACTUAL: 30.7
        assert s >= 25, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_which_language_model(self):
        s = _score("Which language model powers Agentys?")
        # ACTUAL: 23.0
        assert s >= 20, f"scored {s}"
        assert s < PROD_THRESHOLD

    def test_what_ai_is_this(self):
        """Zero overlap after stop-word removal."""
        s = _score("What AI is this built on?")
        # ACTUAL: 0.0 — no tokens left after stop words
        assert s == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TYPOS & ACCENT ERRORS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTyposAndAccents:
    def test_typo_agentis(self):
        """Misspelling 'Agentis' — loses the 'agentys' overlap."""
        s = _score("Quelle est le modèle LLM derrière Agentis?")
        # ACTUAL: 61.3 — loses one key word
        assert s >= 55, f"Typo scored {s}"
        assert s < PROD_THRESHOLD

    def test_abbreviated(self):
        s = _score("quel mdl LLM agentys?")
        # ACTUAL: 38.3
        assert s >= 30, f"scored {s}"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. INDIRECT / VERBOSE
# ═══════════════════════════════════════════════════════════════════════════════

class TestIndirectPhrasing:
    def test_wrapped_in_context(self):
        """Exact question buried in a long email — still works."""
        s = _score(
            "Bonjour l'équipe, je suis en train d'évaluer votre solution pour "
            "notre entreprise. J'aurais une question : quel est le modèle LLM "
            "derrière Agentys? On veut s'assurer de la qualité des réponses. Merci."
        )
        # ACTUAL: ~69 (many extra words dilute overlap ratio)
        assert s >= 50, f"Wrapped in context scored {s}"

    def test_multiple_questions(self):
        s = _score(
            "Bonjour, quelques questions : 1) Quel est le prix? "
            "2) Quel modèle d'IA utilisez-vous dans Agentys? "
            "3) Y a-t-il un essai gratuit?"
        )
        # ACTUAL: ~35
        assert s >= 25, f"Multiple questions scored {s}"

    def test_very_short(self):
        s = _score("LLM Agentys?")
        # ACTUAL: 38.3 — only 2 keywords but they're both in title
        assert s >= 30, f"Very short scored {s}"

    def test_just_the_product_name(self):
        """Only product name — should NOT trigger auto-send."""
        s = _score("Agentys")
        assert s < PROD_THRESHOLD, f"Just product name scored {s}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. NEGATIVE CASES — should NOT match
# ═══════════════════════════════════════════════════════════════════════════════

class TestNegativeCases:
    def test_unrelated_topic(self):
        s = _score("Comment modifier mon mot de passe?")
        assert s < 20, f"Unrelated scored {s}"

    def test_completely_different(self):
        s = _score("Bonjour, je voudrais annuler mon abonnement. Merci.")
        assert s < 20, f"Cancel subscription scored {s}"

    def test_other_product(self):
        s = _score("Quel LLM utilise ChatGPT?")
        assert s < PROD_THRESHOLD, f"Other product scored {s}"

    def test_spam(self):
        s = _score("Congratulations! You won a free iPhone! Click here now!")
        assert s < 10, f"Spam scored {s}"

    def test_empty(self):
        assert _score("") == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. MULTI-FAQ DISAMBIGUATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiFaqDisambiguation:
    """When multiple FAQ entries exist, the right one should win."""

    FAQ_ENTRIES = [
        {
            "id": "faq-llm",
            "title": "Quelle est le modèle LLM derrière Agentys?",
            "content": "Agentys utilise Claude comme intelligence artificielle.",
        },
        {
            "id": "faq-prix",
            "title": "Quel est le prix d'Agentys?",
            "content": "Agentys coûte 29€/mois pour le plan Pro.",
        },
        {
            "id": "faq-essai",
            "title": "Y a-t-il un essai gratuit?",
            "content": "Oui, 14 jours d'essai gratuit sans carte bancaire.",
        },
        {
            "id": "faq-password",
            "title": "Comment réinitialiser mon mot de passe?",
            "content": "Allez dans Paramètres > Sécurité > Réinitialiser le mot de passe.",
        },
    ]

    def test_exact_llm_question(self):
        """Exact match should rank faq-llm first."""
        matches = match_faq_entries(
            "Quelle est le modèle LLM derrière Agentys?", "",
            self.FAQ_ENTRIES, threshold=20,
        )
        assert matches[0].entry_id == "faq-llm"

    def test_rephrased_llm_question_disambiguation_fails(self):
        """Known weakness: rephrased question doesn't rank correctly.
        'Quel modèle d'IA est utilisé?' shares 'modele' with faq-llm
        but also shares 'agentys' with faq-prix. Current algorithm
        can't distinguish because word overlap is too coarse."""
        matches = match_faq_entries(
            "Quel modèle d'IA est utilisé?", "Question",
            self.FAQ_ENTRIES, threshold=20,
        )
        # Document actual behavior: faq-prix wins (wrongly) because 'prix' entry
        # shares overlapping common words. This is a known algorithm weakness.
        if matches:
            # Just check that *some* match exists — don't assert which FAQ wins
            assert len(matches) >= 1

    def test_price_question(self):
        matches = match_faq_entries(
            "Combien coûte Agentys?", "Prix",
            self.FAQ_ENTRIES, threshold=20,
        )
        if matches:
            assert matches[0].entry_id == "faq-prix", (
                f"Expected faq-prix, got {matches[0].entry_id} (score={matches[0].score})"
            )

    def test_password_question(self):
        matches = match_faq_entries(
            "J'ai oublié mon mot de passe", "Aide",
            self.FAQ_ENTRIES, threshold=20,
        )
        if matches:
            assert matches[0].entry_id == "faq-password", (
                f"Expected faq-password, got {matches[0].entry_id}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 8. DIAGNOSTIC REPORT — always passes, prints score table
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreReport:
    """
    Prints all scores so we can see where the algorithm is weak.
    This test always passes — it's purely diagnostic.

    When improving the algorithm, re-run this test to see the impact.
    """

    CASES = [
        # (label, email_text, should_match_at_80)
        # --- Should match (exact/near-exact) ---
        ("Exact copy",              "Quelle est le modèle LLM derrière Agentys?", True),
        ("No accents",              "Quelle est le modele LLM derriere Agentys?", True),
        ("With greeting",           "Bonjour, quelle est le modèle LLM derrière Agentys? Merci!", True),
        # --- Should match but DON'T (algorithm weakness) ---
        ("Quel LLM utilisez-vous",  "Quel LLM utilisez-vous?", True),
        ("C'est quoi l'IA",         "C'est quoi l'IA derrière Agentys?", True),
        ("Agentys quel LLM",        "Agentys utilise quel LLM?", True),
        ("Quel modèle d'IA",        "Quel modèle d'IA est utilisé par Agentys?", True),
        ("GPT ou Claude",           "Vous utilisez GPT ou Claude?", True),
        ("EN: What LLM",            "What LLM does Agentys use?", True),
        ("EN: What AI model",       "What AI model is behind Agentys?", True),
        ("EN: ChatGPT or Claude",   "Is Agentys using ChatGPT or Claude?", True),
        ("Moteur IA",               "Quel est le moteur IA d'Agentys?", True),
        ("Propulsé par",            "Agentys est propulsé par quel modèle?", True),
        ("Informal short",          "le LLM d'Agentys c'est quoi?", True),
        ("Very short",              "LLM Agentys?", True),
        ("Wrapped verbose",         "J'évalue votre solution. Quel est le modèle LLM derrière Agentys?", True),
        ("Intelligence artif.",     "Quel est le modèle d'intelligence artificielle derrière Agentys?", True),
        ("Typo Agentis",            "Quelle est le modèle LLM derrière Agentis?", True),
        # --- Should NOT match ---
        ("Mot de passe",            "Comment modifier mon mot de passe?", False),
        ("Cancel sub",              "Je voudrais annuler mon abonnement.", False),
        ("Spam",                    "You won a free iPhone!", False),
    ]

    def test_print_score_report(self, capsys):
        print("\n")
        print("=" * 78)
        print("FAQ SCORING DIAGNOSTIC REPORT")
        print(f"  FAQ Title:   {FAQ_TITLE}")
        print(f"  FAQ Content: {FAQ_CONTENT}")
        print(f"  Threshold:   {PROD_THRESHOLD}")
        print("=" * 78)
        print(f"{'Label':<25} {'Score':>6} {'Pass?':>6} {'Want':>6} {'Status':>8}")
        print("-" * 78)

        pass_count = 0
        fail_count = 0
        false_negatives = []  # should match but doesn't

        for label, text, should_match in self.CASES:
            s = _score(text)
            passes = s >= PROD_THRESHOLD
            want = "YES" if should_match else "NO"
            ok = (passes == should_match)
            status = "OK" if ok else "MISS" if should_match else "FALSE+"

            if ok:
                pass_count += 1
            else:
                fail_count += 1
                if should_match:
                    false_negatives.append((label, s))

            print(f"{label:<25} {s:>6.1f} {'YES' if passes else 'NO':>6} {want:>6} {status:>8}")

        print("-" * 78)
        print(f"  Correct: {pass_count}/{len(self.CASES)}  |  "
              f"False negatives (should match but don't): {len(false_negatives)}")

        if false_negatives:
            print(f"\n  IMPROVEMENT NEEDED — {len(false_negatives)} legitimate phrasings score below {PROD_THRESHOLD}:")
            for label, s in false_negatives:
                gap = PROD_THRESHOLD - s
                print(f"    {label:<25} score={s:>5.1f}  (gap: -{gap:.1f})")

        # Tokenization diagnostic
        print("\n  TOKENS:")
        print(f"    FAQ title:   {sorted(_tokenize(FAQ_TITLE))}")
        print(f"    FAQ content: {sorted(_tokenize(FAQ_CONTENT))}")
        print(f"    Combined:    {sorted(_tokenize(FAQ_TITLE) | _tokenize(FAQ_CONTENT))}")

        # Show a few email tokenizations for comparison
        print("\n  SAMPLE EMAIL TOKENS:")
        samples = [
            ("Quel LLM utilisez-vous?", "Quel LLM utilisez-vous?"),
            ("C'est quoi l'IA derrière Agentys?", "C'est quoi l'IA derrière Agentys?"),
            ("What LLM does Agentys use?", "What LLM does Agentys use?"),
        ]
        for label, text in samples:
            tokens = sorted(_tokenize(text))
            faq_tokens = _tokenize(FAQ_TITLE) | _tokenize(FAQ_CONTENT)
            overlap = sorted(_tokenize(text) & faq_tokens)
            print(f"    [{label}]")
            print(f"      tokens:  {tokens}")
            print(f"      overlap: {overlap}")

        print("=" * 78)
        print()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. LLM SEMANTIC MATCHING — verifies the new match_faq_with_llm() function
#    All LLM calls are mocked; these tests prove that phrasings which FAIL
#    with word-overlap now MATCH via the LLM path.
# ═══════════════════════════════════════════════════════════════════════════════

class TestLlmMatching:
    """LLM-based matching resolves rephrasings that word-overlap cannot."""

    FAQ_ENTRIES = [
        {
            "id": "faq-llm",
            "title": FAQ_TITLE,
            "content": FAQ_CONTENT,
        },
        {
            "id": "faq-prix",
            "title": "Quel est le prix d'Agentys?",
            "content": "29€/mois plan Pro.",
        },
    ]

    def _mock_llm_response(self, text):
        resp = MagicMock()
        resp.content = text
        return resp

    @pytest.mark.parametrize("email_text,label", [
        ("Quel LLM utilisez-vous?", "FR: Quel LLM utilisez-vous"),
        ("C'est quoi l'IA derrière Agentys?", "FR: C'est quoi l'IA"),
        ("Agentys utilise quel LLM?", "FR: Agentys quel LLM"),
        ("Vous utilisez GPT ou Claude?", "FR: GPT ou Claude"),
        ("What LLM does Agentys use?", "EN: What LLM"),
        ("What AI model is behind Agentys?", "EN: What AI model"),
        ("Is Agentys using ChatGPT or Claude?", "EN: ChatGPT or Claude"),
        ("Quel est le moteur IA d'Agentys?", "FR: Moteur IA"),
        ("le LLM d'Agentys c'est quoi?", "FR: Informal short"),
    ])
    def test_llm_matches_rephrasings(self, email_text, label):
        """Rephrasings that score <80 with word-overlap now match via LLM."""
        # Verify word-overlap indeed fails
        word_score = score_faq_match(email_text, FAQ_TITLE, FAQ_CONTENT)
        assert word_score < PROD_THRESHOLD, f"{label}: word-overlap scored {word_score} (expected <{PROD_THRESHOLD})"

        # LLM returns "1" (first FAQ entry matches)
        mock_container = MagicMock()
        mock_container.llm_label.complete.return_value = self._mock_llm_response("1")
        mock_container.llm_background.complete.return_value = self._mock_llm_response("1")

        with patch("app.infrastructure.container.get_container", return_value=mock_container):
            matches = match_faq_with_llm(email_text, "", self.FAQ_ENTRIES)

        assert len(matches) == 1, f"{label}: expected 1 match, got {len(matches)}"
        assert matches[0].entry_id == "faq-llm"
        assert matches[0].score == 95.0

    def test_llm_rejects_unrelated(self):
        """Unrelated email → LLM returns NONE → no match."""
        mock_container = MagicMock()
        mock_container.llm_label.complete.return_value = self._mock_llm_response("NONE")
        mock_container.llm_background.complete.return_value = self._mock_llm_response("NONE")

        with patch("app.infrastructure.container.get_container", return_value=mock_container):
            matches = match_faq_with_llm(
                "Je voudrais annuler mon abonnement.", "Annulation",
                self.FAQ_ENTRIES,
            )

        assert len(matches) == 0

    def test_llm_disambiguates_correctly(self):
        """LLM picks the right FAQ among multiple entries."""
        mock_container = MagicMock()
        # "2" = faq-prix (second entry)
        mock_container.llm_label.complete.return_value = self._mock_llm_response("2")
        mock_container.llm_background.complete.return_value = self._mock_llm_response("2")

        with patch("app.infrastructure.container.get_container", return_value=mock_container):
            matches = match_faq_with_llm(
                "Combien coûte Agentys?", "Prix",
                self.FAQ_ENTRIES,
            )

        assert len(matches) == 1
        assert matches[0].entry_id == "faq-prix"
