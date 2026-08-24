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
Tests for the FAQ Agent — matching, scoring, and processing logic.
"""

from unittest.mock import patch, MagicMock

from app.faq_agent import (
    score_faq_match,
    match_faq_entries,
    match_faq_with_llm,
    find_relevant_faqs_for_drafter,
    FaqMatch,
)


# ── Word-overlap scoring ─────────────────────────────────────────────────────

class TestScoreFaqMatch:
    def test_perfect_match(self):
        """FAQ title words all appear in email → high score."""
        score = score_faq_match(
            "Comment réinitialiser mon mot de passe ?",
            "Comment réinitialiser mon mot de passe ?",
            "Allez dans Paramètres > Sécurité > Réinitialiser le mot de passe.",
        )
        assert score >= 60

    def test_no_match(self):
        """Completely unrelated email → very low score."""
        score = score_faq_match(
            "Bonjour, je voudrais commander 3 pizzas margherita.",
            "Comment réinitialiser mon mot de passe ?",
            "Allez dans Paramètres > Sécurité > Réinitialiser le mot de passe.",
        )
        assert score < 30

    def test_partial_match(self):
        """Some overlapping keywords → medium score."""
        score = score_faq_match(
            "J'ai oublié mon mot de passe, comment faire ?",
            "Comment réinitialiser mon mot de passe ?",
            "Allez dans Paramètres > Sécurité > Réinitialiser le mot de passe.",
        )
        assert score >= 40

    def test_empty_email(self):
        """Empty email → 0 score."""
        score = score_faq_match("", "Title", "Content")
        assert score == 0.0

    def test_empty_faq(self):
        """Empty FAQ → 0 score."""
        score = score_faq_match("Some email text", "", "")
        assert score == 0.0

    def test_question_bonus(self):
        """Both email and FAQ title are questions → bonus applied."""
        score_no_q = score_faq_match(
            "password reset please",
            "How to reset password",
            "Go to settings and click reset.",
        )
        score_with_q = score_faq_match(
            "password reset please?",
            "How to reset password?",
            "Go to settings and click reset.",
        )
        # Question bonus should increase score slightly
        assert score_with_q >= score_no_q

    def test_title_weighted_higher(self):
        """Title words count more than content words."""
        # Email matches title keywords exactly
        score_title_match = score_faq_match(
            "refund policy",
            "refund policy",
            "We accept returns within 30 days of purchase.",
        )
        # Email matches only content keywords
        score_content_match = score_faq_match(
            "returns purchase days",
            "refund policy",
            "We accept returns within 30 days of purchase.",
        )
        assert score_title_match > score_content_match


# ── FAQ matching ─────────────────────────────────────────────────────────────

class TestMatchFaqEntries:
    FAQ_ENTRIES = [
        {
            "id": "1",
            "title": "Comment réinitialiser mon mot de passe ?",
            "content": "Allez dans Paramètres > Sécurité > Réinitialiser.",
        },
        {
            "id": "2",
            "title": "Quelle est votre politique de remboursement ?",
            "content": "Remboursement sous 30 jours, produits non ouverts.",
        },
        {
            "id": "3",
            "title": "Comment contacter le support ?",
            "content": "Envoyez un email à support@example.com ou appelez le 01-23-45.",
        },
    ]

    def test_match_above_threshold(self):
        """Direct match with high overlap should return matches."""
        matches = match_faq_entries(
            "Je veux réinitialiser mon mot de passe",
            "Mot de passe",
            self.FAQ_ENTRIES,
            threshold=30,
        )
        assert len(matches) >= 1
        assert matches[0].entry_id == "1"
        assert matches[0].score >= 30

    def test_no_match_below_threshold(self):
        """Unrelated email returns no matches at high threshold."""
        matches = match_faq_entries(
            "Bonjour, quand est la prochaine réunion d'équipe ?",
            "Réunion",
            self.FAQ_ENTRIES,
            threshold=80,
        )
        assert len(matches) == 0

    def test_sorted_by_score(self):
        """Matches are sorted by score descending."""
        matches = match_faq_entries(
            "mot de passe remboursement support contacter",
            "Question",
            self.FAQ_ENTRIES,
            threshold=10,
        )
        if len(matches) > 1:
            for i in range(len(matches) - 1):
                assert matches[i].score >= matches[i + 1].score

    def test_empty_entries(self):
        """No FAQ entries → no matches."""
        matches = match_faq_entries("test", "test", [], threshold=50)
        assert len(matches) == 0


# ── FaqMatch dataclass ───────────────────────────────────────────────────────

class TestFaqMatch:
    def test_creation(self):
        m = FaqMatch(
            entry_id="abc",
            entry_title="Test",
            entry_content="Content",
            score=85.5,
        )
        assert m.entry_id == "abc"
        assert m.score == 85.5


# ── LLM semantic matching ──────────────────────────────────────────────────

class TestMatchFaqWithLlm:
    FAQ_ENTRIES = [
        {"id": "1", "title": "Comment réinitialiser mon mot de passe ?", "content": "Paramètres > Sécurité."},
        {"id": "2", "title": "Quelle est le modèle LLM derrière Agentys?", "content": "Agentys utilise Claude."},
        {"id": "3", "title": "Quel est le prix d'Agentys?", "content": "29€/mois plan Pro."},
    ]

    def _mock_llm_response(self, text):
        """Create a mock LLM response with .content attribute."""
        resp = MagicMock()
        resp.content = text
        return resp

    def test_llm_returns_match_number(self):
        """LLM returns '2' → matches FAQ entry #2 with score 95."""
        mock_container = MagicMock()
        mock_container.llm_label.complete.return_value = self._mock_llm_response("2")
        mock_container.llm_background.complete.return_value = self._mock_llm_response("2")

        with patch("app.infrastructure.container.get_container", return_value=mock_container):
            matches = match_faq_with_llm(
                "Quel LLM utilisez-vous?", "Question IA",
                self.FAQ_ENTRIES,
            )

        assert len(matches) == 1
        assert matches[0].entry_id == "2"
        assert matches[0].score == 95.0
        assert matches[0].entry_title == "Quelle est le modèle LLM derrière Agentys?"

    def test_llm_returns_none(self):
        """LLM returns 'NONE' → no matches."""
        mock_container = MagicMock()
        mock_container.llm_label.complete.return_value = self._mock_llm_response("NONE")
        mock_container.llm_background.complete.return_value = self._mock_llm_response("NONE")

        with patch("app.infrastructure.container.get_container", return_value=mock_container):
            matches = match_faq_with_llm(
                "Je veux commander une pizza", "Pizza",
                self.FAQ_ENTRIES,
            )

        assert len(matches) == 0

    def test_llm_fails_fallback_to_word_overlap(self):
        """LLM raises exception → falls back to match_faq_entries."""
        mock_container = MagicMock()
        mock_container.llm_label.complete.side_effect = RuntimeError("API down")
        mock_container.llm_background.complete.side_effect = RuntimeError("API down")

        with patch("app.infrastructure.container.get_container", return_value=mock_container):
            matches = match_faq_with_llm(
                "Comment réinitialiser mon mot de passe ?", "Mot de passe",
                self.FAQ_ENTRIES,
                threshold=30,
            )

        # Fallback to word-overlap should find at least entry #1
        assert len(matches) >= 1
        assert matches[0].entry_id == "1"

    def test_llm_returns_out_of_range(self):
        """LLM returns number > len(entries) → empty list."""
        mock_container = MagicMock()
        mock_container.llm_label.complete.return_value = self._mock_llm_response("99")
        mock_container.llm_background.complete.return_value = self._mock_llm_response("99")

        with patch("app.infrastructure.container.get_container", return_value=mock_container):
            matches = match_faq_with_llm(
                "Some question", "Subject",
                self.FAQ_ENTRIES,
            )

        assert len(matches) == 0

    def test_llm_returns_zero(self):
        """LLM returns '0' → out of range (1-indexed), empty list."""
        mock_container = MagicMock()
        mock_container.llm_label.complete.return_value = self._mock_llm_response("0")
        mock_container.llm_background.complete.return_value = self._mock_llm_response("0")

        with patch("app.infrastructure.container.get_container", return_value=mock_container):
            matches = match_faq_with_llm(
                "Some question", "Subject",
                self.FAQ_ENTRIES,
            )

        assert len(matches) == 0

    def test_empty_entries(self):
        """No FAQ entries → immediate empty return, no LLM call."""
        matches = match_faq_with_llm("Some question", "Subject", [])
        assert len(matches) == 0

    def test_empty_email(self):
        """Empty email body and subject → immediate empty return."""
        matches = match_faq_with_llm("", "", self.FAQ_ENTRIES)
        assert len(matches) == 0

    def test_llm_returns_garbage(self):
        """LLM returns non-numeric text → empty list."""
        mock_container = MagicMock()
        mock_container.llm_label.complete.return_value = self._mock_llm_response("I don't know")
        mock_container.llm_background.complete.return_value = self._mock_llm_response("I don't know")

        with patch("app.infrastructure.container.get_container", return_value=mock_container):
            matches = match_faq_with_llm(
                "Some question", "Subject",
                self.FAQ_ENTRIES,
            )

        assert len(matches) == 0

class TestFindRelevantFaqsForDrafter:
    """Tests for the drafter-grounding helper (permissive matching)."""

    FAQ_ENTRIES = [
        {'id': '1', 'title': 'Quel modele d IA utilisez vous?', 'content': 'Agentys utilise Claude par Anthropic comme intelligence artificielle.'},
        {'id': '2', 'title': 'Quel est votre tarif?', 'content': 'Le tarif standard est de 50 euros par mois sans engagement.'},
        {'id': '3', 'title': 'Comment installer le logiciel?', 'content': 'Telechargez Docker Desktop puis lancez docker-compose up -d dans le repertoire.'},
    ]

    def test_returns_match_above_threshold(self):
        """Email mentioning a FAQ topic returns the matching entry."""
        matches = find_relevant_faqs_for_drafter(
            email_subject='Question modele',
            email_body='Bonjour, quel modele utilisez vous?',
            faq_entries=self.FAQ_ENTRIES,
            threshold=30.0,
        )
        assert len(matches) >= 1
        assert matches[0].entry_id == '1'

    def test_caps_at_max_entries(self):
        """Helper returns at most max_entries even if many match."""
        matches = find_relevant_faqs_for_drafter(
            email_subject='installer modele tarif logiciel',
            email_body='installer modele tarif logiciel utilisez Claude Docker',
            faq_entries=self.FAQ_ENTRIES,
            threshold=10.0,
            max_entries=2,
        )
        assert len(matches) <= 2

    def test_below_threshold_returns_empty(self):
        """Email with no overlap returns empty list."""
        matches = find_relevant_faqs_for_drafter(
            email_subject='Bonjour',
            email_body='Comment vas tu mon ami',
            faq_entries=self.FAQ_ENTRIES,
            threshold=30.0,
        )
        assert matches == []

    def test_empty_faq_list(self):
        """No FAQ entries returns empty."""
        matches = find_relevant_faqs_for_drafter('subject', 'body', [], threshold=30.0)
        assert matches == []

    def test_matches_sorted_by_score_desc(self):
        """When multiple matches, the highest score comes first."""
        matches = find_relevant_faqs_for_drafter(
            email_subject='modele tarif',
            email_body='Quel modele d IA utilisez vous et quel est le tarif',
            faq_entries=self.FAQ_ENTRIES,
            threshold=20.0,
        )
        assert len(matches) >= 2
        assert matches[0].score >= matches[1].score

