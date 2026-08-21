# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour StyleInferenceService (issue #187).

Le service doit analyser l'outbox et produire des métriques statistiques
100% lexicales (regex + stdlib, pas de LLM) en < 5s sur 500 emails.
"""

import time
from dataclasses import dataclass
from typing import Optional

import pytest

from app.domain.services.style_inference_service import StyleInferenceService


@dataclass
class FakeEmail:
    """Duck-typed Email pour les tests (évite la construction SQLAlchemy)."""

    body_text: str
    subject: str = ""
    body_html: Optional[str] = None


@pytest.fixture
def service() -> StyleInferenceService:
    return StyleInferenceService()


# ---------------------------------------------------------------------------
# Fixtures de corpus
# ---------------------------------------------------------------------------

FORMAL_CORPUS = [
    FakeEmail(
        body_text=(
            "Madame, Monsieur,\n\n"
            "Je vous prie de bien vouloir trouver ci-joint le document "
            "que vous avez demandé lors de notre précédent échange. "
            "Je reste à votre entière disposition pour toute précision complémentaire "
            "et vous prie d'agréer l'expression de mes salutations distinguées."
        ),
        subject="Document demandé",
    ),
    FakeEmail(
        body_text=(
            "Monsieur le Directeur,\n\n"
            "Nous avons bien reçu votre courrier concernant la facture n° [À confirmer]. "
            "Nous vous informons que le règlement sera effectué dans les meilleurs délais. "
            "Je vous remercie de votre confiance."
        ),
        subject="Accusé de réception facture",
    ),
    FakeEmail(
        body_text=(
            "Chère Madame,\n\n"
            "Suite à notre entretien téléphonique, je vous confirme les termes "
            "de notre accord. Je vous serais reconnaissant de bien vouloir me "
            "retourner le document signé."
        ),
        subject="Confirmation accord",
    ),
]

CASUAL_CORPUS = [
    FakeEmail(
        body_text=(
            "Salut !\n\n"
            "T'as vu le message de Paul ? 😄 C'est génial ! On fait quoi ce soir ?\n"
            "Tiens moi au jus 👍"
        ),
        subject="Ce soir ?",
    ),
    FakeEmail(
        body_text=(
            "Hey !\n\n"
            "Super idée ! J'adore ! 🎉\n"
            "Tu me dis quand t'es dispo, je me libère !"
        ),
        subject="RE: sortie",
    ),
    FakeEmail(
        body_text=(
            "Yo !\n"
            "Trop bien ton truc ! On teste ça demain ?\n"
            "Bisous 😘"
        ),
        subject="RE: projet",
    ),
]

BULLET_CORPUS = [
    FakeEmail(
        body_text=(
            "Bonjour,\n\n"
            "Voici les points à traiter :\n"
            "- Point A\n"
            "- Point B\n"
            "- Point C\n\n"
            "Cordialement."
        ),
        subject="Points à traiter",
    ),
    FakeEmail(
        body_text=(
            "Hello,\n\n"
            "Tasks:\n"
            "• Première tâche\n"
            "• Deuxième tâche\n\n"
            "Merci."
        ),
        subject="Tasks",
    ),
    FakeEmail(
        body_text=(
            "Hi,\n\n"
            "1. Premier\n"
            "2. Deuxième\n"
            "3. Troisième\n\n"
            "Bonne journée."
        ),
        subject="Ordered list",
    ),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalyzeOutboxBasic:
    def test_empty_corpus_returns_neutral_metrics(self, service):
        """Corpus vide → métriques neutres/zéro, pas d'exception."""
        metrics = service.analyze_outbox([])
        assert metrics["avg_sentence_length"] == 0.0
        assert metrics["sentence_length_variance"] == 0.0
        assert metrics["vocabulary_density"] == 0.0
        assert metrics["formality_score"] == 0.5  # Neutre par défaut
        assert metrics["emoji_rate"] == 0.0
        assert metrics["exclamation_rate"] == 0.0
        assert metrics["bullet_usage_rate"] == 0.0

    def test_returns_dict_with_all_expected_keys(self, service):
        metrics = service.analyze_outbox(FORMAL_CORPUS)
        expected_keys = {
            "avg_sentence_length",
            "sentence_length_variance",
            "vocabulary_density",
            "formality_score",
            "emoji_rate",
            "exclamation_rate",
            "bullet_usage_rate",
            "avg_paragraph_count",
        }
        assert expected_keys.issubset(set(metrics.keys()))


class TestFormalityDetection:
    def test_formal_corpus_has_high_formality_score(self, service):
        """Un corpus très formel (vouvoiement, formules) → formality_score > 0.7."""
        metrics = service.analyze_outbox(FORMAL_CORPUS)
        assert metrics["formality_score"] > 0.7, (
            f"Expected high formality for formal corpus, got {metrics['formality_score']}"
        )

    def test_casual_corpus_has_low_formality_score(self, service):
        """Un corpus décontracté (tutoiement, emojis) → formality_score < 0.4."""
        metrics = service.analyze_outbox(CASUAL_CORPUS)
        assert metrics["formality_score"] < 0.4, (
            f"Expected low formality for casual corpus, got {metrics['formality_score']}"
        )

    def test_formality_score_always_in_range(self, service):
        """formality_score est toujours dans [0, 1]."""
        for corpus in (FORMAL_CORPUS, CASUAL_CORPUS, BULLET_CORPUS):
            metrics = service.analyze_outbox(corpus)
            assert 0.0 <= metrics["formality_score"] <= 1.0


class TestLexicalMetrics:
    def test_emoji_rate_on_casual_corpus(self, service):
        """Les emojis sont détectés et comptés par email."""
        metrics = service.analyze_outbox(CASUAL_CORPUS)
        # Chaque email du corpus casual a 1-2 emojis → rate > 0.5
        assert metrics["emoji_rate"] >= 1.0, (
            f"Expected emoji_rate >= 1.0 for casual corpus, got {metrics['emoji_rate']}"
        )

    def test_emoji_rate_zero_on_formal_corpus(self, service):
        metrics = service.analyze_outbox(FORMAL_CORPUS)
        assert metrics["emoji_rate"] == 0.0

    def test_exclamation_rate_higher_on_casual(self, service):
        formal = service.analyze_outbox(FORMAL_CORPUS)
        casual = service.analyze_outbox(CASUAL_CORPUS)
        assert casual["exclamation_rate"] > formal["exclamation_rate"]

    def test_vocabulary_density_in_zero_one_range(self, service):
        metrics = service.analyze_outbox(FORMAL_CORPUS)
        assert 0.0 <= metrics["vocabulary_density"] <= 1.0

    def test_bullet_usage_rate_detects_lists(self, service):
        """Un corpus avec listes à puces → bullet_usage_rate > 0.5."""
        metrics = service.analyze_outbox(BULLET_CORPUS)
        assert metrics["bullet_usage_rate"] > 0.5

    def test_bullet_usage_rate_zero_without_bullets(self, service):
        metrics = service.analyze_outbox(FORMAL_CORPUS)
        # Le corpus formel n'a pas de listes
        assert metrics["bullet_usage_rate"] == 0.0

    def test_avg_sentence_length_reflects_corpus(self, service):
        """Un corpus avec phrases longues → avg_sentence_length > 10."""
        metrics = service.analyze_outbox(FORMAL_CORPUS)
        assert metrics["avg_sentence_length"] > 10.0

    def test_sentence_length_variance_positive_when_variety(self, service):
        """Variance > 0 quand il y a des phrases de tailles différentes."""
        metrics = service.analyze_outbox(FORMAL_CORPUS)
        assert metrics["sentence_length_variance"] > 0.0


class TestPerformance:
    def test_analyze_500_emails_under_5s(self, service):
        """Perf requirement : 500 emails analysés en < 5s."""
        corpus = [
            FakeEmail(
                body_text=(
                    "Bonjour, "
                    "Voici un message de test avec plusieurs phrases. "
                    "La première dit quelque chose. La seconde aussi. "
                    "Je conclus en remerciant pour votre attention. "
                    "Cordialement."
                ),
                subject=f"Email de test #{i}",
            )
            for i in range(500)
        ]
        start = time.perf_counter()
        metrics = service.analyze_outbox(corpus)
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"analyze_outbox on 500 emails took {elapsed:.2f}s (>5s budget)"
        # Sanity check
        assert metrics["avg_sentence_length"] > 0.0


class TestEdgeCases:
    def test_emails_with_empty_body_handled(self, service):
        """Un email sans corps ne doit pas crasher."""
        emails = [FakeEmail(body_text="", subject="Empty")]
        metrics = service.analyze_outbox(emails)
        # Doit retourner des valeurs neutres sans exception
        assert metrics["avg_sentence_length"] == 0.0

    def test_emails_with_none_body_handled(self, service):
        emails = [FakeEmail(body_text=None, subject="None body")]  # type: ignore[arg-type]
        metrics = service.analyze_outbox(emails)
        assert metrics is not None

    def test_single_email_corpus(self, service):
        """Un seul email produit des métriques valides."""
        metrics = service.analyze_outbox([FORMAL_CORPUS[0]])
        assert metrics["avg_sentence_length"] > 0.0
