# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour la validation des entités du domaine.

Ce module teste les edge cases de validation non couverts :
- Classification: confidence bounds (0.0-1.0)
- Priority: numeric ranges (urgency, vip 0-100, sentiment -1 to 1)
- TokenUsage: negative token counts, cost precision
- TextDiff: index bounds validation
- PushNotification: TTL validation (negative/zero)
- LearnedPattern: frequency/confidence bounds
- Draft: version validation

Principes TDD/Clean Architecture appliqués :
1. Tests écrits AVANT les corrections (Red phase)
2. Chaque test cible une règle métier spécifique
3. Isolation complète - aucune dépendance externe
"""

import pytest

from app.domain.entities import (
    Classification,
    EmailCategory,
    Priority,
    TokenUsage,
    Draft,
    Critique,
    LearnedPattern,
    PatternType,
    PushNotification,
    DeviceToken,
    DevicePlatform,
)
from app.domain.entities.realtime_edit import TextDiff, Suggestion


# ============================================================================
# TESTS - CLASSIFICATION ENTITY VALIDATION
# ============================================================================

class TestClassificationBoundsValidation:
    """Tests de validation des bornes pour Classification."""

    def test_classification_confidence_at_zero(self):
        """confidence=0.0 est valide (cas limite inférieur)."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.0,
            reason="Test"
        )
        assert classification.confidence == 0.0

    def test_classification_confidence_at_one(self):
        """confidence=1.0 est valide (cas limite supérieur)."""
        classification = Classification(
            category=EmailCategory.URGENT,
            confidence=1.0,
            reason="Test"
        )
        assert classification.confidence == 1.0

    def test_classification_confidence_negative_should_be_invalid(self):
        """confidence < 0.0 lève maintenant InvalidBoundsError.

        IMPLÉMENTÉ: Validation ajoutée dans Classification.__post_init__
        """
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            Classification(
                category=EmailCategory.NORMAL,
                confidence=-0.5,
                reason="Test"
            )

    def test_classification_confidence_above_one_should_be_invalid(self):
        """confidence > 1.0 lève maintenant InvalidBoundsError.

        IMPLÉMENTÉ: Validation ajoutée dans Classification.__post_init__
        """
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            Classification(
                category=EmailCategory.NORMAL,
                confidence=1.5,
                reason="Test"
            )

    def test_classification_default_has_valid_confidence(self):
        """Classification.default() retourne une confidence valide."""
        default = Classification.default()
        assert 0.0 <= default.confidence <= 1.0

    def test_classification_to_dict_preserves_confidence(self):
        """to_dict() préserve la valeur de confidence."""
        classification = Classification(
            category=EmailCategory.IMPORTANT,
            confidence=0.85,
            reason="High confidence"
        )
        result = classification.to_dict()
        assert result["confidence"] == 0.85

    def test_classification_empty_reason(self):
        """Classification avec reason vide est valide."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.5,
            reason=""
        )
        assert classification.reason == ""


# ============================================================================
# TESTS - PRIORITY ENTITY VALIDATION
# ============================================================================

class TestPriorityBoundsValidation:
    """Tests de validation des bornes pour Priority."""

    def test_priority_urgency_at_zero(self):
        """urgency=0 est valide (minimum)."""
        priority = Priority(
            urgency=0, vip=50, sentiment=0.0, deadline=None, priority_score=50
        )
        assert priority.urgency == 0

    def test_priority_urgency_at_hundred(self):
        """urgency=100 est valide (maximum)."""
        priority = Priority(
            urgency=100, vip=50, sentiment=0.0, deadline=None, priority_score=100
        )
        assert priority.urgency == 100

    def test_priority_urgency_negative_should_be_invalid(self):
        """urgency < 0 lève maintenant InvalidBoundsError."""
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            Priority(
                urgency=-10, vip=50, sentiment=0.0, deadline=None, priority_score=50
            )

    def test_priority_urgency_above_hundred_should_be_invalid(self):
        """urgency > 100 lève maintenant InvalidBoundsError."""
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            Priority(
                urgency=150, vip=50, sentiment=0.0, deadline=None, priority_score=50
            )

    def test_priority_vip_bounds(self):
        """vip doit être entre 0 et 100."""
        # Test valide
        priority_valid = Priority(
            urgency=50, vip=0, sentiment=0.0, deadline=None, priority_score=50
        )
        assert priority_valid.vip == 0

        priority_max = Priority(
            urgency=50, vip=100, sentiment=0.0, deadline=None, priority_score=50
        )
        assert priority_max.vip == 100

    def test_priority_sentiment_at_negative_one(self):
        """sentiment=-1.0 est valide (très négatif)."""
        priority = Priority(
            urgency=50, vip=50, sentiment=-1.0, deadline=None, priority_score=50
        )
        assert priority.sentiment == -1.0

    def test_priority_sentiment_at_positive_one(self):
        """sentiment=1.0 est valide (très positif)."""
        priority = Priority(
            urgency=50, vip=50, sentiment=1.0, deadline=None, priority_score=50
        )
        assert priority.sentiment == 1.0

    def test_priority_sentiment_below_negative_one_should_be_invalid(self):
        """sentiment < -1.0 lève maintenant InvalidBoundsError."""
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            Priority(
                urgency=50, vip=50, sentiment=-2.0, deadline=None, priority_score=50
            )

    def test_priority_sentiment_above_positive_one_should_be_invalid(self):
        """sentiment > 1.0 lève maintenant InvalidBoundsError."""
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            Priority(
                urgency=50, vip=50, sentiment=2.5, deadline=None, priority_score=50
            )

    def test_priority_from_components_clamps_score(self):
        """from_components() clamp le score entre 0 et 100."""
        # Valeurs extrêmes qui devraient générer un score > 100
        priority = Priority.from_components(
            urgency=100, vip=100, sentiment=1.0
        )
        assert priority.priority_score <= 100

        # Valeurs qui devraient générer un score < 0 (impossible ici)
        priority_low = Priority.from_components(
            urgency=0, vip=0, sentiment=-1.0
        )
        assert priority_low.priority_score >= 0

    def test_priority_from_components_formula_correctness(self):
        """from_components() applique la bonne formule."""
        # Formule: urgency * 0.4 + vip * 0.3 + (sentiment + 1) * 15
        priority = Priority.from_components(
            urgency=50, vip=50, sentiment=0.0
        )
        expected = int(50 * 0.4 + 50 * 0.3 + (0.0 + 1) * 15)  # 20 + 15 + 15 = 50
        assert priority.priority_score == expected

    def test_priority_default_has_valid_bounds(self):
        """Priority.default() retourne des valeurs dans les bornes."""
        default = Priority.default()
        assert 0 <= default.urgency <= 100
        assert 0 <= default.vip <= 100
        assert -1.0 <= default.sentiment <= 1.0
        assert 0 <= default.priority_score <= 100

    def test_priority_is_high_priority_boundary(self):
        """is_high_priority() teste correctement le seuil 70."""
        priority_69 = Priority(
            urgency=50, vip=50, sentiment=0.0, deadline=None, priority_score=69
        )
        assert priority_69.is_high_priority() is False

        priority_70 = Priority(
            urgency=50, vip=50, sentiment=0.0, deadline=None, priority_score=70
        )
        assert priority_70.is_high_priority() is True

    def test_priority_is_low_priority_boundary(self):
        """is_low_priority() teste correctement le seuil 30."""
        priority_29 = Priority(
            urgency=50, vip=50, sentiment=0.0, deadline=None, priority_score=29
        )
        assert priority_29.is_low_priority() is True

        priority_30 = Priority(
            urgency=50, vip=50, sentiment=0.0, deadline=None, priority_score=30
        )
        assert priority_30.is_low_priority() is False


# ============================================================================
# TESTS - TOKEN USAGE VALIDATION
# ============================================================================

class TestTokenUsageValidation:
    """Tests de validation pour TokenUsage."""

    def test_token_usage_zero_values(self):
        """TokenUsage avec zéro tokens est valide."""
        usage = TokenUsage(input_tokens=0, output_tokens=0, model="test")
        assert usage.total == 0
        assert usage.cost == 0.0

    def test_token_usage_negative_input_should_be_invalid(self):
        """input_tokens < 0 lève maintenant InvalidBoundsError."""
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            TokenUsage(input_tokens=-100, output_tokens=50, model="test")

    def test_token_usage_negative_output_should_be_invalid(self):
        """output_tokens < 0 lève maintenant InvalidBoundsError."""
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            TokenUsage(input_tokens=100, output_tokens=-50, model="test")

    def test_token_usage_negative_total(self):
        """Tokens négatifs lèvent maintenant InvalidBoundsError."""
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            TokenUsage(input_tokens=-100, output_tokens=-50, model="test")

    def test_token_usage_add_negative_should_be_invalid(self):
        """add() avec valeurs négatives lève maintenant InvalidBoundsError."""
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        usage = TokenUsage()
        with pytest.raises(InvalidBoundsError):
            usage.add(input_tokens=-50, output_tokens=100)

    def test_token_usage_cost_precision(self):
        """Le coût est calculé avec une précision suffisante."""
        usage = TokenUsage(
            input_tokens=1,
            output_tokens=1,
            model="claude-sonnet-4-20250514"
        )
        # Cost = (1 * 3.0 + 1 * 15.0) / 1_000_000 = 0.000018
        expected_cost = 18 / 1_000_000
        assert abs(usage.cost - expected_cost) < 1e-10

    def test_token_usage_cost_with_large_numbers(self):
        """Le coût est correct avec de grands nombres de tokens."""
        usage = TokenUsage(
            input_tokens=10_000_000,  # 10M tokens
            output_tokens=5_000_000,  # 5M tokens
            model="claude-sonnet-4-20250514"
        )
        # Cost = (10M * 3.0 + 5M * 15.0) / 1M = 30 + 75 = 105$
        expected_cost = 105.0
        assert usage.cost == expected_cost

    def test_token_usage_unknown_model_uses_default(self):
        """Modèle inconnu utilise les coûts par défaut (Sonnet)."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="unknown-model-xyz"
        )
        # Default Sonnet: input=3.0, output=15.0 per million
        expected = 3.0 + 15.0
        assert usage.cost == expected

    def test_token_usage_ollama_model_free(self):
        """Modèles Ollama sont gratuits."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="mixtral:latest"
        )
        assert usage.cost == 0.0

    def test_token_usage_reset_clears_all(self):
        """reset() remet tout à zéro."""
        usage = TokenUsage(input_tokens=100, output_tokens=50, model="test")
        usage.reset()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.model == ""

    def test_token_usage_aliases_work(self):
        """Les propriétés input/output sont des alias valides."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.input == 100
        assert usage.output == 50


# ============================================================================
# TESTS - DRAFT ENTITY VALIDATION
# ============================================================================

class TestDraftValidation:
    """Tests de validation pour Draft."""

    def test_draft_version_default_is_one(self):
        """version par défaut est 1."""
        draft = Draft(content="Test")
        assert draft.version == 1

    def test_draft_version_zero_should_be_invalid(self):
        """version=0 lève maintenant InvalidBoundsError."""
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            Draft(content="Test", version=0)

    def test_draft_version_negative_should_be_invalid(self):
        """version < 0 lève maintenant InvalidBoundsError."""
        import pytest
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            Draft(content="Test", version=-1)

    def test_draft_empty_content_is_valid(self):
        """Draft avec contenu vide est techniquement valide."""
        draft = Draft(content="", version=1)
        assert draft.content == ""

    def test_draft_str_returns_content(self):
        """__str__ retourne le contenu."""
        draft = Draft(content="Mon brouillon")
        assert str(draft) == "Mon brouillon"


# ============================================================================
# TESTS - CRITIQUE ENTITY VALIDATION
# ============================================================================

class TestCritiqueValidation:
    """Tests de validation pour Critique."""

    def test_critique_from_response_valid(self):
        """Réponse 'VALID' est correctement parsée."""
        critique = Critique.from_response("VALID - Tout est correct")
        assert critique.is_valid is True
        assert critique.reason is None

    def test_critique_from_response_valid_lowercase(self):
        """Réponse 'valid' (minuscules) est correctement parsée."""
        critique = Critique.from_response("valid")
        assert critique.is_valid is True

    def test_critique_from_response_invalid(self):
        """Réponse invalide retourne is_valid=False."""
        critique = Critique.from_response("Le ton est trop formel")
        assert critique.is_valid is False
        assert critique.reason == "Le ton est trop formel"

    def test_critique_from_response_empty(self):
        """Réponse vide est traitée comme invalide."""
        critique = Critique.from_response("")
        assert critique.is_valid is False

    def test_critique_from_response_whitespace_only(self):
        """Réponse avec espaces seulement est traitée comme invalide."""
        critique = Critique.from_response("   \n\t  ")
        assert critique.is_valid is False

    def test_critique_from_response_valid_with_extra_spaces(self):
        """VALID avec espaces au début/fin est correctement parsé."""
        critique = Critique.from_response("  VALID  ")
        assert critique.is_valid is True


# ============================================================================
# TESTS - TEXT DIFF VALIDATION
# ============================================================================

class TestTextDiffValidation:
    """Tests de validation pour TextDiff."""

    def test_textdiff_valid_indices(self):
        """TextDiff avec indices valides."""
        diff = TextDiff(start=0, end=5, original="hello", replacement="world")
        assert diff.start == 0
        assert diff.end == 5

    def test_textdiff_negative_start_should_be_invalid(self):
        """TDD: start < 0 devrait lever une erreur."""
        diff = TextDiff(start=-1, end=5, original="hello", replacement="world")
        # ATTENDU: ValueError
        # ACTUEL: Pas d'erreur
        assert diff.start == -1  # Comportement actuel (à corriger)

    def test_textdiff_negative_end_should_be_invalid(self):
        """TDD: end < 0 devrait lever une erreur."""
        diff = TextDiff(start=0, end=-1, original="hello", replacement="world")
        # ATTENDU: ValueError
        # ACTUEL: Pas d'erreur
        assert diff.end == -1  # Comportement actuel (à corriger)

    def test_textdiff_start_greater_than_end_should_be_invalid(self):
        """TDD: start > end devrait lever une erreur."""
        diff = TextDiff(start=10, end=5, original="hello", replacement="world")
        # ATTENDU: ValueError
        # ACTUEL: Pas d'erreur
        assert diff.start > diff.end  # Comportement actuel (à corriger)

    def test_textdiff_is_insertion(self):
        """is_insertion détecte correctement les insertions."""
        diff = TextDiff(start=5, end=5, original="", replacement="new text")
        assert diff.is_insertion is True
        assert diff.is_deletion is False

    def test_textdiff_is_deletion(self):
        """is_deletion détecte correctement les suppressions."""
        diff = TextDiff(start=0, end=5, original="hello", replacement="")
        assert diff.is_deletion is True
        assert diff.is_insertion is False

    def test_textdiff_is_replacement(self):
        """Remplacement n'est ni insertion ni suppression."""
        diff = TextDiff(start=0, end=5, original="hello", replacement="world")
        assert diff.is_insertion is False
        assert diff.is_deletion is False


# ============================================================================
# TESTS - PUSH NOTIFICATION VALIDATION
# ============================================================================

class TestPushNotificationValidation:
    """Tests de validation pour PushNotification."""

    def test_push_notification_valid(self):
        """PushNotification avec données valides."""
        notif = PushNotification(
            title="Test",
            body="Message de test",
            ttl=3600
        )
        assert notif.title == "Test"
        assert notif.ttl == 3600

    def test_push_notification_empty_title_raises(self):
        """title vide lève ValueError."""
        with pytest.raises(ValueError, match="title cannot be empty"):
            PushNotification(title="", body="Test body")

    def test_push_notification_whitespace_title_raises(self):
        """title avec espaces seulement lève ValueError."""
        with pytest.raises(ValueError, match="title cannot be empty"):
            PushNotification(title="   ", body="Test body")

    def test_push_notification_empty_body_raises(self):
        """body vide lève ValueError."""
        with pytest.raises(ValueError, match="body cannot be empty"):
            PushNotification(title="Test", body="")

    def test_push_notification_ttl_negative_should_be_invalid(self):
        """TDD: ttl < 0 devrait lever une erreur."""
        # Actuellement, ttl négatif est accepté
        notif = PushNotification(title="Test", body="Body", ttl=-100)
        # ATTENDU: ValueError
        # ACTUEL: Pas d'erreur
        assert notif.ttl == -100  # Comportement actuel (à corriger)

    def test_push_notification_ttl_zero_should_be_invalid(self):
        """TDD: ttl=0 devrait lever une erreur (expiration immédiate)."""
        notif = PushNotification(title="Test", body="Body", ttl=0)
        # ATTENDU: ValueError ou ttl minimum de 1
        # ACTUEL: Pas d'erreur
        assert notif.ttl == 0  # Comportement actuel (à corriger)

    def test_push_notification_default_ttl(self):
        """TTL par défaut est 24h (86400 secondes)."""
        notif = PushNotification(title="Test", body="Body")
        assert notif.ttl == 86400


# ============================================================================
# TESTS - DEVICE TOKEN VALIDATION
# ============================================================================

class TestDeviceTokenValidation:
    """Tests de validation pour DeviceToken."""

    def test_device_token_valid(self):
        """DeviceToken avec données valides."""
        token = DeviceToken(token="abc123", platform=DevicePlatform.IOS)
        assert token.token == "abc123"

    def test_device_token_empty_raises(self):
        """token vide lève ValueError."""
        with pytest.raises(ValueError, match="token cannot be empty"):
            DeviceToken(token="", platform=DevicePlatform.IOS)

    def test_device_token_whitespace_raises(self):
        """token avec espaces seulement lève ValueError."""
        with pytest.raises(ValueError, match="token cannot be empty"):
            DeviceToken(token="   ", platform=DevicePlatform.IOS)

    def test_device_token_platform_string_conversion(self):
        """platform string est converti en enum."""
        token = DeviceToken(token="abc123", platform="android")
        assert token.platform == DevicePlatform.ANDROID

    def test_device_token_to_dict_from_dict_roundtrip(self):
        """to_dict/from_dict préservent les données."""
        original = DeviceToken(
            token="test-token",
            platform=DevicePlatform.WEB,
            user_id="user123",
            device_name="Test Device"
        )
        data = original.to_dict()
        restored = DeviceToken.from_dict(data)
        assert restored.token == original.token
        assert restored.platform == original.platform
        assert restored.user_id == original.user_id


# ============================================================================
# TESTS - LEARNED PATTERN VALIDATION
# ============================================================================

class TestLearnedPatternValidation:
    """Tests de validation pour LearnedPattern."""

    def test_learned_pattern_default_confidence(self):
        """confidence par défaut est 0.5."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test"
        )
        assert pattern.confidence == 0.5

    def test_learned_pattern_confidence_bounds(self):
        """confidence reste entre 0.0 et 1.0."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test"
        )
        # Après 10 incréments, confidence = 1.0
        for _ in range(10):
            pattern.increment_frequency()
        assert pattern.confidence == 1.0

        # Après plus d'incréments, confidence reste à 1.0
        for _ in range(10):
            pattern.increment_frequency()
        assert pattern.confidence == 1.0

    def test_learned_pattern_frequency_never_negative(self):
        """frequency ne peut pas devenir négative."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="test"
        )
        assert pattern.frequency >= 1  # Minimum 1

    def test_learned_pattern_is_reliable_threshold(self):
        """is_reliable() utilise le bon seuil."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test"
        )
        # confidence = 0.5 < 0.6
        assert pattern.is_reliable() is False

        # Après 6 incréments: confidence = 0.7 >= 0.6
        for _ in range(6):
            pattern.increment_frequency()
        assert pattern.is_reliable() is True

    def test_learned_pattern_custom_min_confidence(self):
        """is_reliable() accepte un seuil personnalisé."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test"
        )
        # confidence = 0.5
        assert pattern.is_reliable(min_confidence=0.5) is True
        assert pattern.is_reliable(min_confidence=0.6) is False

    def test_learned_pattern_add_example_no_duplicates(self):
        """add_example() n'ajoute pas de doublons."""
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test"
        )
        pattern.add_example("example1")
        pattern.add_example("example1")  # Doublon
        pattern.add_example("example2")
        assert len(pattern.examples) == 2

    def test_learned_pattern_to_dict_from_dict_roundtrip(self):
        """to_dict/from_dict préservent les données."""
        original = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="test trigger",
            correction="test correction",
            examples=["ex1", "ex2"]
        )
        original.increment_frequency()
        original.increment_frequency()

        data = original.to_dict()
        restored = LearnedPattern.from_dict(data)

        assert restored.id == original.id
        assert restored.pattern_type == original.pattern_type
        assert restored.trigger == original.trigger
        assert restored.correction == original.correction
        assert restored.examples == original.examples
        assert restored.frequency == original.frequency
        assert restored.confidence == original.confidence


# ============================================================================
# TESTS - SUGGESTION CONFIDENCE VALIDATION
# ============================================================================

class TestSuggestionValidation:
    """Tests de validation pour Suggestion."""

    def test_suggestion_confidence_at_zero(self):
        """confidence=0.0 est valide."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.0
        )
        assert suggestion.confidence == 0.0

    def test_suggestion_confidence_at_one(self):
        """confidence=1.0 est valide."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=1.0
        )
        assert suggestion.confidence == 1.0

    def test_suggestion_confidence_negative_should_be_invalid(self):
        """TDD: confidence < 0.0 devrait lever une erreur."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=-0.5
        )
        # ATTENDU: ValueError
        # ACTUEL: Pas d'erreur
        assert suggestion.confidence == -0.5  # Comportement actuel (à corriger)

    def test_suggestion_confidence_above_one_should_be_invalid(self):
        """TDD: confidence > 1.0 devrait lever une erreur."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=1.5
        )
        # ATTENDU: ValueError
        # ACTUEL: Pas d'erreur
        assert suggestion.confidence == 1.5  # Comportement actuel (à corriger)

    def test_suggestion_get_diffs_empty_texts(self):
        """get_diffs() avec textes vides."""
        suggestion = Suggestion(
            original_text="",
            suggested_text="",
            confidence=1.0
        )
        diffs = suggestion.get_diffs()
        assert len(diffs) == 0

    def test_suggestion_accept_reject_status(self):
        """accept() et reject() changent le statut."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9
        )
        from app.domain.entities.realtime_edit import SuggestionStatus

        assert suggestion.status == SuggestionStatus.PENDING
        suggestion.accept()
        assert suggestion.status == SuggestionStatus.ACCEPTED

        suggestion2 = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9
        )
        suggestion2.reject()
        assert suggestion2.status == SuggestionStatus.REJECTED


# ============================================================================
# TESTS - LEARNING INSIGHTS DIVISION BY ZERO
# ============================================================================

class TestLearningInsightsValidation:
    """Tests de validation pour LearningInsights."""

    def test_learning_insights_satisfaction_rate_zero_total(self):
        """satisfaction_rate avec total_with_feedback=0 retourne 0.0."""
        from app.domain.entities import LearningInsights

        insights = LearningInsights(
            total_with_feedback=0,
            good_count=0,
            bad_count=0,
            neutral_count=0
        )
        # Ne doit pas lever ZeroDivisionError
        assert insights.satisfaction_rate == 0.0

    def test_learning_insights_satisfaction_rate_calculation(self):
        """satisfaction_rate calcule correctement le pourcentage."""
        from app.domain.entities import LearningInsights

        insights = LearningInsights(
            total_with_feedback=100,
            good_count=75,
            bad_count=15,
            neutral_count=10
        )
        assert insights.satisfaction_rate == 75.0
