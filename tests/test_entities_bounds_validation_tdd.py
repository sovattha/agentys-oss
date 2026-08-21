# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour la validation stricte des bornes des entités du domaine.

Ce module implémente les tests RED (qui doivent échouer) pour forcer
l'ajout de validation dans les entités. Les tests sont écrits AVANT
le code de validation selon les principes TDD.

Edge cases testés:
1. Email: id/subject/sender vides, format email invalide
2. Classification: confidence hors [0.0, 1.0]
3. Priority: urgency/vip hors [0, 100], sentiment hors [-1, 1]
4. TokenUsage: tokens négatifs
5. Draft: version <= 0

Clean Architecture:
- Ces tests ciblent la couche Domain (Entities)
- Aucune dépendance infrastructure
- Isolation totale
"""

import pytest

from app.domain.entities import (
    Email,
    Classification,
    EmailCategory,
    Priority,
    TokenUsage,
    Draft,
    Critique,
)
from app.domain.exceptions import (
    EmptyValueError,
    InvalidBoundsError,
    InvalidFormatError,
)


# ============================================================================
# TESTS - EMAIL ENTITY VALIDATION
# ============================================================================

class TestEmailValidation:
    """Tests de validation pour l'entité Email."""

    def test_email_valid_minimal(self):
        """Email avec données minimales valides."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="test@example.com"
        )
        assert email.id == "123"
        assert email.sender == "test@example.com"

    def test_email_empty_id_should_raise(self):
        """TDD RED: id vide devrait lever EmptyValueError.

        ACTUELLEMENT: Pas de validation, le test échoue.
        ATTENDU: L'entité rejette les IDs vides.
        """
        # Ce test doit ÉCHOUER actuellement (RED phase)
        # Une fois la validation ajoutée, il passera (GREEN phase)
        with pytest.raises((ValueError, EmptyValueError)):
            Email(
                id="",
                subject="Test",
                body="Body",
                sender="test@example.com"
            )

    def test_email_whitespace_only_id_should_raise(self):
        """TDD RED: id avec espaces seulement devrait lever EmptyValueError."""
        with pytest.raises((ValueError, EmptyValueError)):
            Email(
                id="   ",
                subject="Test",
                body="Body",
                sender="test@example.com"
            )

    def test_email_none_id_should_raise(self):
        """TDD RED: id=None devrait lever TypeError ou EmptyValueError."""
        with pytest.raises((TypeError, ValueError, EmptyValueError)):
            Email(
                id=None,  # type: ignore
                subject="Test",
                body="Body",
                sender="test@example.com"
            )

    def test_email_empty_sender_should_raise(self):
        """TDD RED: sender vide devrait lever EmptyValueError."""
        with pytest.raises((ValueError, EmptyValueError)):
            Email(
                id="123",
                subject="Test",
                body="Body",
                sender=""
            )

    def test_email_invalid_sender_format_should_raise(self):
        """TDD RED: sender sans @ devrait lever InvalidFormatError."""
        with pytest.raises((ValueError, InvalidFormatError)):
            Email(
                id="123",
                subject="Test",
                body="Body",
                sender="not-an-email"
            )

    def test_email_sender_without_domain_should_raise(self):
        """TDD RED: sender sans domaine devrait lever InvalidFormatError."""
        with pytest.raises((ValueError, InvalidFormatError)):
            Email(
                id="123",
                subject="Test",
                body="Body",
                sender="user@"
            )

    def test_email_empty_subject_is_valid(self):
        """Subject vide est valide (certains emails n'ont pas de sujet)."""
        email = Email(
            id="123",
            subject="",
            body="Body",
            sender="test@example.com"
        )
        assert email.subject == ""

    def test_email_empty_body_is_valid(self):
        """Body vide est valide (forward d'email vide)."""
        email = Email(
            id="123",
            subject="Test",
            body="",
            sender="test@example.com"
        )
        assert email.body == ""

    def test_email_is_cc_only_no_recipients(self):
        """is_cc_only retourne True si pas de destinataires mais CC."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="test@example.com",
            recipients=[],
            cc=["cc@example.com"]
        )
        assert email.is_cc_only is True

    def test_email_is_cc_only_with_recipients(self):
        """is_cc_only retourne False si destinataires présents."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="test@example.com",
            recipients=["recipient@example.com"],
            cc=["cc@example.com"]
        )
        assert email.is_cc_only is False

    def test_email_content_for_processing_format(self):
        """content_for_processing retourne le bon format."""
        email = Email(
            id="123",
            subject="Subject",
            body="Body content",
            sender="sender@test.com"
        )
        content = email.content_for_processing
        assert "De: sender@test.com" in content
        assert "Sujet: Subject" in content
        assert "Body content" in content


# ============================================================================
# TESTS - CLASSIFICATION VALIDATION STRICTE
# ============================================================================

class TestClassificationStrictValidation:
    """Tests de validation stricte pour Classification.

    Ces tests remplacent les assertions documentant le bug actuel
    par des assertions sur le comportement attendu.
    """

    def test_classification_confidence_negative_raises(self):
        """TDD RED: confidence < 0.0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Classification(
                category=EmailCategory.NORMAL,
                confidence=-0.1,
                reason="Test"
            )

    def test_classification_confidence_above_one_raises(self):
        """TDD RED: confidence > 1.0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Classification(
                category=EmailCategory.NORMAL,
                confidence=1.01,
                reason="Test"
            )

    def test_classification_confidence_at_boundaries(self):
        """confidence=0.0 et confidence=1.0 sont valides."""
        c1 = Classification(EmailCategory.NORMAL, 0.0, "Min")
        assert c1.confidence == 0.0

        c2 = Classification(EmailCategory.URGENT, 1.0, "Max")
        assert c2.confidence == 1.0

    def test_classification_confidence_mid_range(self):
        """confidence entre 0 et 1 est valide."""
        c = Classification(EmailCategory.IMPORTANT, 0.5, "Mid")
        assert c.confidence == 0.5

    def test_classification_empty_reason_is_valid(self):
        """reason vide est valide."""
        c = Classification(EmailCategory.NORMAL, 0.5, "")
        assert c.reason == ""

    def test_classification_none_reason_raises(self):
        """TDD RED: reason=None devrait lever TypeError."""
        with pytest.raises(TypeError):
            Classification(
                category=EmailCategory.NORMAL,
                confidence=0.5,
                reason=None  # type: ignore
            )

    def test_classification_should_skip_categories(self):
        """should_skip() retourne True pour les bonnes catégories."""
        skip_categories = [
            EmailCategory.NEWSLETTER,
            EmailCategory.PROMO,
            EmailCategory.SPAM,
            EmailCategory.CC_ONLY,
        ]
        for cat in skip_categories:
            c = Classification(cat, 0.9, "Test")
            assert c.should_skip() is True

    def test_classification_should_not_skip_categories(self):
        """should_skip() retourne False pour URGENT, IMPORTANT, NORMAL."""
        no_skip_categories = [
            EmailCategory.URGENT,
            EmailCategory.IMPORTANT,
            EmailCategory.NORMAL,
        ]
        for cat in no_skip_categories:
            c = Classification(cat, 0.9, "Test")
            assert c.should_skip() is False


# ============================================================================
# TESTS - PRIORITY VALIDATION STRICTE
# ============================================================================

class TestPriorityStrictValidation:
    """Tests de validation stricte pour Priority."""

    def test_priority_urgency_negative_raises(self):
        """TDD RED: urgency < 0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority(
                urgency=-1,
                vip=50,
                sentiment=0.0,
                deadline=None,
                priority_score=50
            )

    def test_priority_urgency_above_100_raises(self):
        """TDD RED: urgency > 100 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority(
                urgency=101,
                vip=50,
                sentiment=0.0,
                deadline=None,
                priority_score=50
            )

    def test_priority_vip_negative_raises(self):
        """TDD RED: vip < 0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority(
                urgency=50,
                vip=-1,
                sentiment=0.0,
                deadline=None,
                priority_score=50
            )

    def test_priority_vip_above_100_raises(self):
        """TDD RED: vip > 100 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority(
                urgency=50,
                vip=101,
                sentiment=0.0,
                deadline=None,
                priority_score=50
            )

    def test_priority_sentiment_below_minus_one_raises(self):
        """TDD RED: sentiment < -1.0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority(
                urgency=50,
                vip=50,
                sentiment=-1.01,
                deadline=None,
                priority_score=50
            )

    def test_priority_sentiment_above_one_raises(self):
        """TDD RED: sentiment > 1.0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority(
                urgency=50,
                vip=50,
                sentiment=1.01,
                deadline=None,
                priority_score=50
            )

    def test_priority_score_negative_raises(self):
        """TDD RED: priority_score < 0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority(
                urgency=50,
                vip=50,
                sentiment=0.0,
                deadline=None,
                priority_score=-1
            )

    def test_priority_score_above_100_raises(self):
        """TDD RED: priority_score > 100 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority(
                urgency=50,
                vip=50,
                sentiment=0.0,
                deadline=None,
                priority_score=101
            )

    def test_priority_all_at_boundaries_valid(self):
        """Valeurs aux limites sont valides."""
        # Min values
        p1 = Priority(urgency=0, vip=0, sentiment=-1.0, deadline=None, priority_score=0)
        assert p1.urgency == 0
        assert p1.vip == 0
        assert p1.sentiment == -1.0
        assert p1.priority_score == 0

        # Max values
        p2 = Priority(urgency=100, vip=100, sentiment=1.0, deadline=None, priority_score=100)
        assert p2.urgency == 100
        assert p2.vip == 100
        assert p2.sentiment == 1.0
        assert p2.priority_score == 100

    def test_priority_from_components_validates_inputs(self):
        """TDD RED: from_components() doit valider ses entrées."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority.from_components(urgency=-10, vip=50, sentiment=0.0)

        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority.from_components(urgency=50, vip=150, sentiment=0.0)

        with pytest.raises((ValueError, InvalidBoundsError)):
            Priority.from_components(urgency=50, vip=50, sentiment=2.0)

    def test_priority_from_components_clamps_output(self):
        """from_components() clamp le score entre 0 et 100."""
        # Valeurs maximales = score = 100*0.4 + 100*0.3 + 2*15 = 40+30+30 = 100
        p = Priority.from_components(urgency=100, vip=100, sentiment=1.0)
        assert 0 <= p.priority_score <= 100

        # Valeurs minimales = score = 0*0.4 + 0*0.3 + 0*15 = 0
        p2 = Priority.from_components(urgency=0, vip=0, sentiment=-1.0)
        assert p2.priority_score >= 0

    def test_priority_deadline_iso_format_valid(self):
        """deadline au format ISO est valide."""
        p = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline="2024-12-31T23:59:59",
            priority_score=50
        )
        assert p.deadline == "2024-12-31T23:59:59"

    def test_priority_deadline_invalid_format_should_raise(self):
        """TDD RED: deadline avec format invalide devrait lever InvalidFormatError."""
        with pytest.raises((ValueError, InvalidFormatError)):
            Priority(
                urgency=50,
                vip=50,
                sentiment=0.0,
                deadline="not-a-date",
                priority_score=50
            )


# ============================================================================
# TESTS - TOKEN USAGE VALIDATION STRICTE
# ============================================================================

class TestTokenUsageStrictValidation:
    """Tests de validation stricte pour TokenUsage."""

    def test_token_usage_negative_input_raises(self):
        """TDD RED: input_tokens < 0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            TokenUsage(input_tokens=-1, output_tokens=0, model="test")

    def test_token_usage_negative_output_raises(self):
        """TDD RED: output_tokens < 0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            TokenUsage(input_tokens=0, output_tokens=-1, model="test")

    def test_token_usage_zero_is_valid(self):
        """Tokens à zéro sont valides."""
        usage = TokenUsage(input_tokens=0, output_tokens=0, model="test")
        assert usage.total == 0
        assert usage.cost == 0.0

    def test_token_usage_add_negative_raises(self):
        """TDD RED: add() avec valeurs négatives doit lever InvalidBoundsError."""
        usage = TokenUsage()
        with pytest.raises((ValueError, InvalidBoundsError)):
            usage.add(input_tokens=-10, output_tokens=0)

        with pytest.raises((ValueError, InvalidBoundsError)):
            usage.add(input_tokens=0, output_tokens=-10)

    def test_token_usage_add_accumulates(self):
        """add() accumule correctement les tokens."""
        usage = TokenUsage()
        usage.add(100, 50, "model1")
        usage.add(200, 100, "model2")
        assert usage.input_tokens == 300
        assert usage.output_tokens == 150
        assert usage.model == "model2"  # Dernier modèle utilisé

    def test_token_usage_cost_known_models(self):
        """Cost correct pour les modèles connus."""
        # Claude Sonnet
        usage_sonnet = TokenUsage(1_000_000, 500_000, "claude-sonnet-4-20250514")
        # 1M * 3.0 + 0.5M * 15.0 = 3 + 7.5 = 10.5$
        assert usage_sonnet.cost == 10.5

        # Claude Opus
        usage_opus = TokenUsage(1_000_000, 500_000, "claude-opus-4-20250514")
        # 1M * 15.0 + 0.5M * 75.0 = 15 + 37.5 = 52.5$
        assert usage_opus.cost == 52.5

        # Ollama (gratuit)
        usage_ollama = TokenUsage(1_000_000, 500_000, "mixtral:latest")
        assert usage_ollama.cost == 0.0

    def test_token_usage_large_numbers_overflow(self):
        """Gestion des très grands nombres de tokens."""
        # Test avec des valeurs très grandes
        usage = TokenUsage(
            input_tokens=1_000_000_000,  # 1 milliard
            output_tokens=500_000_000,
            model="claude-sonnet-4-20250514"
        )
        # 1B * 3.0 + 0.5B * 15.0 = 3000 + 7500 = 10500$
        assert usage.cost == 10500.0
        assert usage.total == 1_500_000_000


# ============================================================================
# TESTS - DRAFT VALIDATION STRICTE
# ============================================================================

class TestDraftStrictValidation:
    """Tests de validation stricte pour Draft."""

    def test_draft_version_zero_raises(self):
        """TDD RED: version=0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Draft(content="Test", version=0)

    def test_draft_version_negative_raises(self):
        """TDD RED: version < 0 doit lever InvalidBoundsError."""
        with pytest.raises((ValueError, InvalidBoundsError)):
            Draft(content="Test", version=-1)

    def test_draft_version_one_is_valid(self):
        """version=1 (défaut) est valide."""
        draft = Draft(content="Test")
        assert draft.version == 1

    def test_draft_version_higher_is_valid(self):
        """version > 1 est valide (révisions)."""
        draft = Draft(content="Revision", version=5)
        assert draft.version == 5

    def test_draft_empty_content_is_valid(self):
        """Contenu vide est valide (brouillon initial)."""
        draft = Draft(content="", version=1)
        assert draft.content == ""

    def test_draft_str_returns_content(self):
        """__str__ retourne le contenu."""
        draft = Draft(content="My draft")
        assert str(draft) == "My draft"


# ============================================================================
# TESTS - CRITIQUE EDGE CASES
# ============================================================================

class TestCritiqueEdgeCases:
    """Tests des edge cases pour Critique."""

    def test_critique_from_response_valid_uppercase(self):
        """VALID majuscule est reconnu."""
        c = Critique.from_response("VALID - Good draft")
        assert c.is_valid is True
        assert c.reason is None

    def test_critique_from_response_valid_lowercase(self):
        """valid minuscule est reconnu."""
        c = Critique.from_response("valid response")
        assert c.is_valid is True

    def test_critique_from_response_valid_mixed_case(self):
        """VaLiD (casse mixte) est reconnu."""
        c = Critique.from_response("VaLiD response")
        assert c.is_valid is True

    def test_critique_from_response_valid_with_whitespace(self):
        """VALID avec espaces est reconnu."""
        c = Critique.from_response("   VALID   ")
        assert c.is_valid is True

    def test_critique_from_response_invalid_reason(self):
        """Réponse invalide retourne la raison."""
        c = Critique.from_response("The tone is too formal")
        assert c.is_valid is False
        assert c.reason == "The tone is too formal"

    def test_critique_from_response_empty(self):
        """Réponse vide est invalide."""
        c = Critique.from_response("")
        assert c.is_valid is False

    def test_critique_from_response_whitespace_only(self):
        """Espaces seulement est invalide."""
        c = Critique.from_response("   \n\t  ")
        assert c.is_valid is False

    def test_critique_from_response_almost_valid(self):
        """'VALIDE' (avec E) est reconnu comme valid car startswith('VALID').

        Note: Ce comportement est intentionnel car dans un contexte FR,
        "VALIDE" est acceptable. Le parser vérifie startswith("VALID").
        """
        c = Critique.from_response("VALIDE - good")
        # Le code actuel considère "VALIDE" comme valid (starts with "VALID")
        # Ce comportement est acceptable pour supporter le français
        assert c.is_valid is True

    def test_critique_from_response_valid_in_middle(self):
        """VALID au milieu n'est pas reconnu (doit être au début)."""
        c = Critique.from_response("The response is VALID")
        assert c.is_valid is False


# ============================================================================
# TESTS - EMAIL ANALYSIS VALIDATION
# ============================================================================

class TestEmailAnalysisValidation:
    """Tests de validation pour EmailAnalysis."""

    def test_email_analysis_should_process_normal(self):
        """should_process() True pour email NORMAL."""
        from app.domain.entities import EmailAnalysis

        analysis = EmailAnalysis(
            email_id="123",
            classification=Classification(EmailCategory.NORMAL, 0.9, "Normal email"),
            priority=Priority.default()
        )
        assert analysis.should_process() is True

    def test_email_analysis_should_not_process_spam(self):
        """should_process() False pour SPAM."""
        from app.domain.entities import EmailAnalysis

        analysis = EmailAnalysis(
            email_id="123",
            classification=Classification(EmailCategory.SPAM, 0.95, "Spam detected"),
            priority=Priority.default()
        )
        assert analysis.should_process() is False

    def test_email_analysis_empty_email_id_should_raise(self):
        """TDD RED: email_id vide devrait lever EmptyValueError."""
        from app.domain.entities import EmailAnalysis

        with pytest.raises((ValueError, EmptyValueError)):
            EmailAnalysis(
                email_id="",
                classification=Classification.default(),
                priority=Priority.default()
            )

    def test_email_analysis_to_dict_complete(self):
        """to_dict() retourne toutes les données."""
        from app.domain.entities import EmailAnalysis

        analysis = EmailAnalysis(
            email_id="test-123",
            classification=Classification(EmailCategory.IMPORTANT, 0.8, "Important"),
            priority=Priority(50, 60, 0.5, None, 55)
        )
        result = analysis.to_dict()

        assert result["email_id"] == "test-123"
        assert "classification" in result
        assert "priority" in result
        assert "analyzed_at" in result


# ============================================================================
# TESTS - FORMATS DE DONNEES
# ============================================================================

class TestDataFormats:
    """Tests des formats de données."""

    def test_email_id_with_special_chars(self):
        """ID d'email avec caractères spéciaux."""
        email = Email(
            id="<message-123@server.com>",
            subject="Test",
            body="Body",
            sender="test@example.com"
        )
        assert "<" in email.id and ">" in email.id

    def test_email_unicode_subject(self):
        """Subject avec caractères Unicode."""
        email = Email(
            id="123",
            subject="Réunion urgent: nouveaux résultats 日本語",
            body="Body",
            sender="test@example.com"
        )
        assert "日本語" in email.subject

    def test_email_very_long_body(self):
        """Body très long (10KB)."""
        long_body = "x" * 10240
        email = Email(
            id="123",
            subject="Test",
            body=long_body,
            sender="test@example.com"
        )
        assert len(email.body) == 10240

    def test_classification_reason_with_newlines(self):
        """Classification reason avec retours à la ligne."""
        c = Classification(
            EmailCategory.NORMAL,
            0.7,
            "Reason line 1\nReason line 2\nReason line 3"
        )
        assert "\n" in c.reason

    def test_priority_deadline_empty_string(self):
        """deadline comme string vide."""
        p = Priority(50, 50, 0.0, "", 50)
        assert p.deadline == ""

    def test_token_usage_empty_model(self):
        """TokenUsage avec modèle vide utilise le défaut."""
        usage = TokenUsage(1000, 500, "")
        # Devrait utiliser les coûts par défaut (Sonnet)
        assert usage.cost > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
