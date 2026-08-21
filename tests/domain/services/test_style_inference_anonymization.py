# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests d'anonymisation + sélection d'exemples (S3 / issue #187).

Aucune fuite tolérée : emails, téléphones, URLs, montants, et noms propres
associés à des formules d'adresse doivent être remplacés par des placeholders.
"""

from dataclasses import dataclass
from typing import Optional

import pytest

from app.domain.entities.writing_style import ReferenceExample
from app.domain.services.style_inference_service import StyleInferenceService


@dataclass
class FakeEmail:
    body_text: str
    subject: str = ""
    body_html: Optional[str] = None
    email_id: Optional[str] = None


@pytest.fixture
def service() -> StyleInferenceService:
    return StyleInferenceService()


# ---------------------------------------------------------------------------
# Anonymisation — patterns structurés
# ---------------------------------------------------------------------------


class TestAnonymizeEmail:
    def test_redacts_email_addresses(self, service):
        text = "Envoie à alice@example.com pour validation."
        anonymized = service.anonymize_text(text)
        assert "alice@example.com" not in anonymized
        assert "[EMAIL]" in anonymized

    def test_redacts_multiple_emails(self, service):
        text = "CC: bob@corp.fr et marie.dupont@test.io en copie."
        anonymized = service.anonymize_text(text)
        assert "bob@corp.fr" not in anonymized
        assert "marie.dupont@test.io" not in anonymized
        assert anonymized.count("[EMAIL]") == 2


class TestAnonymizePhone:
    def test_redacts_french_phone(self, service):
        text = "Appelle-moi au 06 12 34 56 78 ou au 01.23.45.67.89."
        anonymized = service.anonymize_text(text)
        assert "06 12 34 56 78" not in anonymized
        assert "01.23.45.67.89" not in anonymized
        assert "[TEL]" in anonymized

    def test_redacts_international_phone(self, service):
        text = "Mon numéro : +33 6 12 34 56 78."
        anonymized = service.anonymize_text(text)
        assert "+33" not in anonymized
        assert "[TEL]" in anonymized


class TestAnonymizePhoneFalsePositives:
    """F8 — la regex tel ne doit PAS matcher dates, codes postaux, montants, commandes."""

    def test_does_not_match_year_then_digits(self, service):
        text = "En 2024, nous avons traité 42 58 63 dossiers."
        anonymized = service.anonymize_text(text)
        assert "[TEL]" not in anonymized

    def test_does_not_match_postal_code(self, service):
        text = "Adresse: 75001 Paris."
        anonymized = service.anonymize_text(text)
        assert "[TEL]" not in anonymized

    def test_does_not_match_order_number(self, service):
        text = "Commande N° 123456789 reçue."
        anonymized = service.anonymize_text(text)
        assert "[TEL]" not in anonymized

    def test_does_not_match_decimal_amount(self, service):
        text = "Le total est de 42,50 euros."
        anonymized = service.anonymize_text(text)
        # Le montant est redacté en [MONTANT], pas en [TEL]
        assert "[TEL]" not in anonymized


class TestAnonymizeUrl:
    def test_redacts_https_url(self, service):
        text = "Voir le lien : https://example.com/projet/abc123?x=1"
        anonymized = service.anonymize_text(text)
        assert "https://example.com" not in anonymized
        assert "[URL]" in anonymized

    def test_redacts_www_url(self, service):
        text = "Voir www.example.org pour plus d'info."
        anonymized = service.anonymize_text(text)
        assert "www.example.org" not in anonymized
        assert "[URL]" in anonymized


class TestAnonymizeAmount:
    def test_redacts_euro_amount(self, service):
        text = "Le devis est de 1 250 € pour le projet."
        anonymized = service.anonymize_text(text)
        assert "1 250 €" not in anonymized
        assert "[MONTANT]" in anonymized

    def test_redacts_dollar_amount(self, service):
        text = "Budget estimé : $5,000 USD."
        anonymized = service.anonymize_text(text)
        assert "$5,000" not in anonymized
        assert "[MONTANT]" in anonymized

    def test_redacts_amount_with_comma_decimal(self, service):
        text = "Total : 42,50 € TTC."
        anonymized = service.anonymize_text(text)
        assert "42,50 €" not in anonymized
        assert "[MONTANT]" in anonymized


class TestAnonymizeName:
    def test_redacts_name_after_bonjour(self, service):
        text = "Bonjour Jean,\n\nMerci pour ton retour."
        anonymized = service.anonymize_text(text)
        assert "Jean" not in anonymized
        assert "[PERSONNE]" in anonymized

    def test_redacts_name_after_cher(self, service):
        text = "Chère Marie-Louise,\n\nSuite à notre échange…"
        anonymized = service.anonymize_text(text)
        assert "Marie-Louise" not in anonymized
        assert "[PERSONNE]" in anonymized

    def test_redacts_monsieur_name(self, service):
        text = "Monsieur Dupont vous contactera demain."
        anonymized = service.anonymize_text(text)
        assert "Dupont" not in anonymized
        assert "[PERSONNE]" in anonymized

    def test_redacts_hello_name_english(self, service):
        text = "Hi Peter,\nHow are you?"
        anonymized = service.anonymize_text(text)
        assert "Peter" not in anonymized
        assert "[PERSONNE]" in anonymized

    def test_preserves_common_words_not_names(self, service):
        """Les mots communs non-capitalisés ne doivent pas être redacted."""
        text = "Le devis est bon."
        anonymized = service.anonymize_text(text)
        assert "devis" in anonymized


class TestAnonymizeCombined:
    def test_all_patterns_in_one_text(self, service):
        text = (
            "Bonjour Alice,\n\n"
            "Peux-tu m'envoyer le devis à alice@example.com ou m'appeler "
            "au 06 12 34 56 78 ? Le montant est de 1 500 €. "
            "Détails sur https://portal.example.com.\n\n"
            "Merci !"
        )
        anonymized = service.anonymize_text(text)
        # Aucune donnée sensible originale ne doit fuir
        forbidden = ["Alice", "alice@example.com", "06 12 34 56 78", "1 500 €",
                     "https://portal.example.com"]
        for leak in forbidden:
            assert leak not in anonymized, f"Leak: {leak} in {anonymized!r}"
        for marker in ["[PERSONNE]", "[EMAIL]", "[TEL]", "[MONTANT]", "[URL]"]:
            assert marker in anonymized


# ---------------------------------------------------------------------------
# Sélection d'exemples-référence
# ---------------------------------------------------------------------------


class TestSelectReferenceExamples:
    def _make_email(self, word_count: int, id_num: int = 0) -> FakeEmail:
        # Texte synthétique calibré sur word_count
        words = ["Bonjour"] + ["merci"] * (word_count - 1)
        return FakeEmail(
            body_text=" ".join(words),
            subject=f"Sujet #{id_num}",
        )

    def test_returns_three_examples_when_enough_data(self, service):
        """Avec un corpus varié, retourne 3 exemples (short/medium/long)."""
        corpus = (
            [self._make_email(20, i) for i in range(5)]      # short
            + [self._make_email(80, 10 + i) for i in range(5)]   # medium
            + [self._make_email(200, 20 + i) for i in range(5)]  # long
        )
        examples = service.select_reference_examples(corpus)
        assert len(examples) == 3
        buckets = {ex.length_bucket for ex in examples}
        assert buckets == {"short", "medium", "long"}

    def test_all_examples_are_anonymized(self, service):
        """Chaque exemple retourné a anonymized=True."""
        corpus = [
            FakeEmail(
                body_text="Bonjour Alice, contact : alice@test.com, tel 06 12 34 56 78. Mot " * 5,
                subject="Test",
            )
            for _ in range(6)
        ]
        examples = service.select_reference_examples(corpus)
        assert all(ex.anonymized for ex in examples)

    def test_anonymization_applied_to_body_excerpt(self, service):
        """Les body_excerpt ne contiennent aucune donnée sensible."""
        corpus = [
            FakeEmail(
                body_text=(
                    f"Bonjour Alice{i}, merci pour ton email à alice@test.com. "
                    "Pour info, le montant est de 1 000 €. "
                    "Détails sur https://example.com. "
                    "Contact: 06 12 34 56 78."
                ),
                subject="Important — contact alice@test.com",
            )
            for i in range(6)
        ]
        examples = service.select_reference_examples(corpus)
        for ex in examples:
            for leak in ["alice@test.com", "06 12 34", "https://example.com"]:
                assert leak not in ex.body_excerpt, f"Leak in body: {leak}"
                assert leak not in ex.subject, f"Leak in subject: {leak}"

    def test_missing_bucket_not_returned(self, service):
        """Si un bucket est vide, on ne retourne que les buckets disponibles."""
        # Que des emails courts
        corpus = [self._make_email(10, i) for i in range(10)]
        examples = service.select_reference_examples(corpus)
        # Seul short doit être présent
        assert all(ex.length_bucket == "short" for ex in examples)
        assert len(examples) >= 1

    def test_empty_corpus_returns_empty_list(self, service):
        assert service.select_reference_examples([]) == []

    def test_returns_reference_example_instances(self, service):
        corpus = [self._make_email(50, i) for i in range(5)]
        examples = service.select_reference_examples(corpus)
        assert all(isinstance(ex, ReferenceExample) for ex in examples)

    def test_word_count_set_on_examples(self, service):
        corpus = [self._make_email(50, i) for i in range(5)]
        examples = service.select_reference_examples(corpus)
        for ex in examples:
            assert ex.word_count > 0

    def test_source_email_id_set_on_examples(self, service):
        corpus = [
            FakeEmail(
                body_text="Bonjour " + "merci " * 50,
                subject="Sujet",
                email_id="provider-message-123",
            )
        ]
        examples = service.select_reference_examples(corpus)

        assert examples[0].source_email_id == "provider-message-123"
        assert examples[0].collected_at
