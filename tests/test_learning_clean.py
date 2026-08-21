# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour la migration du module Learning vers la Clean Architecture.

Ces tests définissent le comportement attendu avant l'implémentation.
"""

from unittest.mock import Mock
import json


# =============================================================================
# TESTS DES ENTITÉS
# =============================================================================


class TestLearningInsightsEntity:
    """Tests pour l'entité LearningInsights."""

    def test_create_default_insights(self):
        """Création avec valeurs par défaut."""
        from app.domain.entities.learning import LearningInsights

        insights = LearningInsights()

        assert insights.total_with_feedback == 0
        assert insights.good_count == 0
        assert insights.bad_count == 0
        assert insights.neutral_count == 0
        assert insights.v1_good_rate == 0
        assert insights.v2_good_rate == 0
        assert insights.common_issues == []
        assert insights.strengths == []

    def test_create_insights_with_values(self):
        """Création avec valeurs personnalisées."""
        from app.domain.entities.learning import LearningInsights

        insights = LearningInsights(
            total_with_feedback=100,
            good_count=60,
            bad_count=20,
            neutral_count=20,
            v1_good_rate=50,
            v2_good_rate=80,
            common_issues=["ton trop formel"],
            strengths=["réponses concises"],
        )

        assert insights.total_with_feedback == 100
        assert insights.good_count == 60
        assert insights.bad_count == 20
        assert insights.v1_good_rate == 50
        assert insights.v2_good_rate == 80

    def test_insights_overall_satisfaction_rate(self):
        """Calcul du taux de satisfaction global."""
        from app.domain.entities.learning import LearningInsights

        insights = LearningInsights(
            total_with_feedback=100,
            good_count=70,
            bad_count=10,
            neutral_count=20,
        )

        assert insights.satisfaction_rate == 70.0

    def test_insights_satisfaction_rate_zero_feedback(self):
        """Taux de satisfaction avec zéro feedback."""
        from app.domain.entities.learning import LearningInsights

        insights = LearningInsights()

        assert insights.satisfaction_rate == 0.0


class TestLearnedPatternEntity:
    """Tests pour l'entité LearnedPattern."""

    def test_create_learned_pattern(self):
        """Création d'un pattern appris."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Réponses courtes et directes",
            correction="",
        )

        assert pattern.id is not None
        assert pattern.pattern_type == PatternType.GOOD
        assert pattern.trigger == "Réponses courtes et directes"
        assert pattern.frequency == 1
        assert pattern.confidence == 0.5

    def test_increment_frequency(self):
        """Incrémenter la fréquence d'un pattern."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Ton trop formel",
            correction="Utiliser un ton plus conversationnel",
        )

        # Incrémenter plusieurs fois pour atteindre une confiance suffisante
        for _ in range(5):
            pattern.increment_frequency()

        assert pattern.frequency == 6
        # La confiance = frequency / 10, donc 6/10 = 0.6 > 0.5
        assert pattern.confidence > 0.5

    def test_pattern_reliability(self):
        """Vérifier si un pattern est fiable."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )
        pattern.confidence = 0.7

        assert pattern.is_reliable()
        assert pattern.is_reliable(min_confidence=0.8) is False


class TestPromptAdjustmentEntity:
    """Tests pour l'entité PromptAdjustment."""

    def test_create_adjustment(self):
        """Création d'un ajustement de prompt."""
        from app.domain.entities.learning import PromptAdjustment

        adjustment = PromptAdjustment.create(
            section="DRAFTER_SYSTEM_PROMPT",
            adjustment="Éviter les formulations trop formelles",
            reason="Pattern détecté 5 fois",
        )

        assert adjustment.id is not None
        assert adjustment.active is True
        assert adjustment.section == "DRAFTER_SYSTEM_PROMPT"
        assert "formelles" in adjustment.adjustment

    def test_deactivate_adjustment(self):
        """Désactiver un ajustement."""
        from app.domain.entities.learning import PromptAdjustment

        adjustment = PromptAdjustment.create(
            section="test",
            adjustment="test",
            reason="test",
        )

        adjustment.deactivate()

        assert adjustment.active is False


class TestReviewRequirementEntity:
    """Tests pour l'entité ReviewRequirement."""

    def test_create_review_required(self):
        """Création d'une exigence de review."""
        from app.domain.entities.learning import ReviewRequirement

        requirement = ReviewRequirement(
            needs_review=True,
            reasons=["Email priorité haute", "Contenu sensible"],
            priority_score=95,
        )

        assert requirement.needs_review is True
        assert len(requirement.reasons) == 2

    def test_create_no_review_needed(self):
        """Pas de review nécessaire."""
        from app.domain.entities.learning import ReviewRequirement

        requirement = ReviewRequirement(
            needs_review=False,
            reasons=[],
            priority_score=50,
        )

        assert requirement.needs_review is False


# =============================================================================
# TESTS DU PORT
# =============================================================================


class TestLearningServicePort:
    """Tests pour le port LearningServicePort."""

    def test_port_has_analyze_feedback_method(self):
        """Le port doit avoir une méthode analyze_feedback."""
        from app.domain.ports.learning_port import LearningServicePort

        assert hasattr(LearningServicePort, "analyze_feedback")
        assert callable(getattr(LearningServicePort, "analyze_feedback"))

    def test_port_has_extract_patterns_method(self):
        """Le port doit avoir une méthode extract_patterns."""
        from app.domain.ports.learning_port import LearningServicePort

        assert hasattr(LearningServicePort, "extract_patterns")

    def test_port_has_generate_adjustment_method(self):
        """Le port doit avoir une méthode generate_adjustment."""
        from app.domain.ports.learning_port import LearningServicePort

        assert hasattr(LearningServicePort, "generate_adjustment")

    def test_port_has_should_require_review_method(self):
        """Le port doit avoir une méthode should_require_review."""
        from app.domain.ports.learning_port import LearningServicePort

        assert hasattr(LearningServicePort, "should_require_review")

    def test_port_has_get_active_adjustments_method(self):
        """Le port doit avoir une méthode get_active_adjustments."""
        from app.domain.ports.learning_port import LearningServicePort

        assert hasattr(LearningServicePort, "get_active_adjustments")


class TestLearningPatternStorePort:
    """Tests pour le port de stockage des patterns."""

    def test_port_has_save_pattern(self):
        """Le port doit avoir une méthode save."""
        from app.domain.ports.learning_port import LearningPatternStorePort

        assert hasattr(LearningPatternStorePort, "save")

    def test_port_has_list_patterns(self):
        """Le port doit avoir une méthode list_all."""
        from app.domain.ports.learning_port import LearningPatternStorePort

        assert hasattr(LearningPatternStorePort, "list_all")

    def test_port_has_get_by_type(self):
        """Le port doit avoir une méthode get_by_type."""
        from app.domain.ports.learning_port import LearningPatternStorePort

        assert hasattr(LearningPatternStorePort, "get_by_type")


# =============================================================================
# TESTS DES USE CASES
# =============================================================================


class TestAnalyzeFeedbackUseCase:
    """Tests pour le use case AnalyzeFeedback."""

    def test_analyze_feedback_returns_insights(self):
        """Analyser les feedbacks retourne des insights."""
        from app.application.learning import AnalyzeFeedbackUseCase
        from app.domain.entities.learning import LearningInsights

        # Mock du port
        mock_feedback_store = Mock()
        mock_feedback_store.get_all.return_value = []

        use_case = AnalyzeFeedbackUseCase(feedback_store=mock_feedback_store)
        result = use_case.execute()

        assert isinstance(result, LearningInsights)

    def test_analyze_with_feedbacks(self):
        """Analyser avec des feedbacks existants."""
        from app.application.learning import AnalyzeFeedbackUseCase
        from app.domain.entities.fine_tuning import FeedbackSentiment

        # Créer des feedbacks mockés
        feedbacks = [
            Mock(rating=5, sentiment=FeedbackSentiment.POSITIVE),
            Mock(rating=5, sentiment=FeedbackSentiment.POSITIVE),
            Mock(rating=3, sentiment=FeedbackSentiment.NEUTRAL),
            Mock(rating=1, sentiment=FeedbackSentiment.NEGATIVE),
        ]

        mock_feedback_store = Mock()
        mock_feedback_store.get_all.return_value = feedbacks

        use_case = AnalyzeFeedbackUseCase(feedback_store=mock_feedback_store)
        result = use_case.execute()

        assert result.total_with_feedback == 4
        assert result.good_count == 2
        assert result.bad_count == 1
        assert result.neutral_count == 1


class TestExtractPatternsUseCase:
    """Tests pour le use case ExtractPatterns."""

    def test_extract_patterns_from_feedbacks(self):
        """Extraire des patterns des feedbacks."""
        from app.application.learning import ExtractPatternsUseCase

        mock_feedback_store = Mock()
        mock_feedback_store.get_with_comments.return_value = []
        mock_pattern_store = Mock()
        mock_llm = Mock()

        use_case = ExtractPatternsUseCase(
            feedback_store=mock_feedback_store,
            pattern_store=mock_pattern_store,
            llm=mock_llm,
        )

        result = use_case.execute()

        assert isinstance(result, list)

    def test_extract_patterns_saves_to_store(self):
        """Les patterns extraits sont sauvegardés."""
        from app.application.learning import ExtractPatternsUseCase

        # Mock feedbacks avec commentaires - configurer les attributs correctement
        feedback1 = Mock()
        feedback1.rating = 5
        feedback1.comment = "Très bien, réponse rapide"
        feedback1.draft_final = "Draft content here for testing"

        feedback2 = Mock()
        feedback2.rating = 2
        feedback2.comment = "Trop formel"
        feedback2.draft_final = "Another draft content"

        feedbacks = [feedback1, feedback2]

        mock_feedback_store = Mock()
        mock_feedback_store.get_with_comments.return_value = feedbacks

        mock_pattern_store = Mock()

        # Mock LLM response
        mock_llm = Mock()
        mock_llm.complete.return_value = Mock(
            content='{"good_patterns": ["Réponses rapides"], "bad_patterns": ["Ton formel"]}'
        )

        use_case = ExtractPatternsUseCase(
            feedback_store=mock_feedback_store,
            pattern_store=mock_pattern_store,
            llm=mock_llm,
        )

        use_case.execute()

        # Vérifier que les patterns ont été sauvegardés
        assert mock_pattern_store.save.called or mock_pattern_store.save_many.called


class TestShouldRequireReviewUseCase:
    """Tests pour le use case ShouldRequireReview."""

    def test_high_priority_requires_review(self):
        """Haute priorité nécessite review."""
        from app.application.learning import ShouldRequireReviewUseCase
        from app.domain.entities.learning import ReviewRequirement

        mock_insights_provider = Mock()
        mock_insights_provider.get_satisfaction_rate.return_value = 80

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_insights_provider,
            confidence_threshold=70,
        )

        result = use_case.execute(
            email_content="Test email",
            priority_score=95,
        )

        assert isinstance(result, ReviewRequirement)
        assert result.needs_review is True
        assert "priorité" in " ".join(result.reasons).lower()

    def test_sensitive_content_requires_review(self):
        """Contenu sensible nécessite review."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_insights_provider = Mock()
        mock_insights_provider.get_satisfaction_rate.return_value = 80

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_insights_provider,
            confidence_threshold=70,
            sensitive_words=["contrat", "juridique", "avocat"],
        )

        result = use_case.execute(
            email_content="Veuillez consulter le contrat joint",
            priority_score=50,
        )

        assert result.needs_review is True

    def test_low_confidence_requires_review(self):
        """Faible confiance nécessite review."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_insights_provider = Mock()
        mock_insights_provider.get_satisfaction_rate.return_value = 50  # < 70%

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_insights_provider,
            confidence_threshold=70,
        )

        result = use_case.execute(
            email_content="Email normal",
            priority_score=50,
        )

        assert result.needs_review is True
        assert "confiance" in " ".join(result.reasons).lower()

    def test_normal_email_no_review(self):
        """Email normal ne nécessite pas review."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_insights_provider = Mock()
        mock_insights_provider.get_satisfaction_rate.return_value = 80

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_insights_provider,
            confidence_threshold=70,
        )

        result = use_case.execute(
            email_content="Bonjour, merci pour votre message.",
            priority_score=50,
        )

        assert result.needs_review is False


class TestGenerateAdjustmentUseCase:
    """Tests pour le use case GenerateAdjustment."""

    def test_generate_adjustment_from_patterns(self):
        """Générer un ajustement depuis les patterns."""
        from app.application.learning import GenerateAdjustmentUseCase
        from app.domain.entities.learning import PromptAdjustment, PatternType

        # Mock patterns avec un pattern fréquent
        bad_pattern = Mock(
            pattern_type=PatternType.BAD,
            trigger="Ton trop formel",
            correction="Être plus conversationnel",
            frequency=5,
        )

        mock_pattern_store = Mock()
        mock_pattern_store.get_by_type.return_value = [bad_pattern]

        mock_adjustment_store = Mock()

        use_case = GenerateAdjustmentUseCase(
            pattern_store=mock_pattern_store,
            adjustment_store=mock_adjustment_store,
        )

        result = use_case.execute()

        assert result is not None
        assert isinstance(result, PromptAdjustment)
        assert mock_adjustment_store.save.called

    def test_no_adjustment_when_no_patterns(self):
        """Pas d'ajustement sans patterns."""
        from app.application.learning import GenerateAdjustmentUseCase

        mock_pattern_store = Mock()
        mock_pattern_store.get_by_type.return_value = []

        mock_adjustment_store = Mock()

        use_case = GenerateAdjustmentUseCase(
            pattern_store=mock_pattern_store,
            adjustment_store=mock_adjustment_store,
        )

        result = use_case.execute()

        assert result is None
        assert not mock_adjustment_store.save.called

    def test_no_adjustment_when_pattern_frequency_below_threshold(self):
        """Pas d'ajustement si patterns détectés moins de 3 fois (seuil de confiance)."""
        from app.application.learning import GenerateAdjustmentUseCase
        from app.domain.entities.learning import PatternType

        # Pattern avec frequency=2 (< 3 minimum)
        low_freq_pattern = Mock(
            pattern_type=PatternType.BAD,
            trigger="Ton trop formel",
            correction="Être plus conversationnel",
            frequency=2,
        )

        mock_pattern_store = Mock()
        mock_pattern_store.get_by_type.return_value = [low_freq_pattern]

        mock_adjustment_store = Mock()

        use_case = GenerateAdjustmentUseCase(
            pattern_store=mock_pattern_store,
            adjustment_store=mock_adjustment_store,
        )

        result = use_case.execute()

        # Pattern avec frequency < 3 doit être ignoré
        assert result is None
        assert not mock_adjustment_store.save.called

    def test_adjustment_generated_when_pattern_frequency_at_threshold(self):
        """Ajustement généré si pattern détecté 3+ fois (seuil atteint)."""
        from app.application.learning import GenerateAdjustmentUseCase
        from app.domain.entities.learning import PromptAdjustment, PatternType

        # Pattern avec frequency=3 (= minimum)
        reliable_pattern = Mock(
            pattern_type=PatternType.BAD,
            trigger="Ton trop formel",
            correction="Être plus conversationnel",
            frequency=3,
        )

        mock_pattern_store = Mock()
        mock_pattern_store.get_by_type.return_value = [reliable_pattern]

        mock_adjustment_store = Mock()

        use_case = GenerateAdjustmentUseCase(
            pattern_store=mock_pattern_store,
            adjustment_store=mock_adjustment_store,
        )

        result = use_case.execute()

        assert result is not None
        assert isinstance(result, PromptAdjustment)
        assert mock_adjustment_store.save.called


class TestGetLearningStatsUseCase:
    """Tests pour le use case GetLearningStats."""

    def test_get_stats(self):
        """Récupérer les statistiques d'apprentissage."""
        from app.application.learning import GetLearningStatsUseCase

        mock_pattern_store = Mock()
        mock_pattern_store.count.return_value = 10
        mock_pattern_store.count_by_type.return_value = {"good": 6, "bad": 4}

        mock_adjustment_store = Mock()
        mock_adjustment_store.count_active.return_value = 3

        # Configurer le feedback store pour retourner une liste vide itérable
        mock_feedback_store = Mock()
        mock_feedback_store.count.return_value = 100
        mock_feedback_store.get_all.return_value = []  # Liste vide pour éviter l'erreur

        use_case = GetLearningStatsUseCase(
            pattern_store=mock_pattern_store,
            adjustment_store=mock_adjustment_store,
            feedback_store=mock_feedback_store,
        )

        result = use_case.execute()

        assert result["patterns_count"] == 10
        assert result["good_patterns"] == 6
        assert result["bad_patterns"] == 4
        assert result["active_adjustments"] == 3


class TestEnhancePromptUseCase:
    """Tests pour le use case EnhancePrompt."""

    def test_enhance_prompt_with_adjustments(self):
        """Enrichir le prompt avec les ajustements."""
        from app.application.learning import EnhancePromptUseCase

        adjustments = [
            Mock(adjustment="Éviter le ton formel", active=True),
            Mock(adjustment="Être concis", active=True),
        ]

        mock_adjustment_store = Mock()
        mock_adjustment_store.get_active.return_value = adjustments

        use_case = EnhancePromptUseCase(adjustment_store=mock_adjustment_store)

        result = use_case.execute("Tu es un assistant email.")

        assert "Tu es un assistant email." in result
        assert "Règles apprises" in result
        assert "Éviter le ton formel" in result

    def test_enhance_prompt_no_adjustments(self):
        """Pas de modification sans ajustements."""
        from app.application.learning import EnhancePromptUseCase

        mock_adjustment_store = Mock()
        mock_adjustment_store.get_active.return_value = []

        use_case = EnhancePromptUseCase(adjustment_store=mock_adjustment_store)

        base_prompt = "Tu es un assistant email."
        result = use_case.execute(base_prompt)

        assert result == base_prompt


# =============================================================================
# TESTS DE L'ADAPTER (INFRASTRUCTURE)
# =============================================================================


class TestJsonLearningPatternStore:
    """Tests pour l'adapter de stockage JSON des patterns."""

    def test_save_pattern(self, tmp_path):
        """Sauvegarder un pattern."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        filepath = tmp_path / "patterns.json"
        store = JsonLearningPatternStore(filepath)

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Test pattern",
            correction="",
        )

        store.save(pattern)

        # Vérifier la persistance
        assert filepath.exists()
        data = json.loads(filepath.read_text())
        assert len(data) == 1

    def test_list_all_patterns(self, tmp_path):
        """Lister tous les patterns."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        filepath = tmp_path / "patterns.json"
        store = JsonLearningPatternStore(filepath)

        # Sauvegarder quelques patterns
        for i in range(3):
            pattern = LearnedPattern.create(
                pattern_type=PatternType.GOOD,
                trigger=f"Pattern {i}",
                correction="",
            )
            store.save(pattern)

        patterns = store.list_all()

        assert len(patterns) == 3

    def test_get_by_type(self, tmp_path):
        """Récupérer les patterns par type."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        filepath = tmp_path / "patterns.json"
        store = JsonLearningPatternStore(filepath)

        # Sauvegarder des patterns de différents types
        good_pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Good one",
            correction="",
        )
        bad_pattern = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Bad one",
            correction="Fix it",
        )
        store.save(good_pattern)
        store.save(bad_pattern)

        bad_patterns = store.get_by_type(PatternType.BAD)

        assert len(bad_patterns) == 1
        assert bad_patterns[0].trigger == "Bad one"


class TestJsonAdjustmentStore:
    """Tests pour l'adapter de stockage JSON des ajustements."""

    def test_save_adjustment(self, tmp_path):
        """Sauvegarder un ajustement."""
        from app.infrastructure.learning_store import JsonAdjustmentStore
        from app.domain.entities.learning import PromptAdjustment

        filepath = tmp_path / "adjustments.json"
        store = JsonAdjustmentStore(filepath)

        adjustment = PromptAdjustment.create(
            section="DRAFTER",
            adjustment="Be concise",
            reason="Pattern detected",
        )

        store.save(adjustment)

        assert filepath.exists()

    def test_get_active_adjustments(self, tmp_path):
        """Récupérer les ajustements actifs."""
        from app.infrastructure.learning_store import JsonAdjustmentStore
        from app.domain.entities.learning import PromptAdjustment

        filepath = tmp_path / "adjustments.json"
        store = JsonAdjustmentStore(filepath)

        active = PromptAdjustment.create("DRAFTER", "Active one", "reason")
        inactive = PromptAdjustment.create("DRAFTER", "Inactive one", "reason")
        inactive.deactivate()

        store.save(active)
        store.save(inactive)

        actives = store.get_active()

        assert len(actives) == 1
        assert actives[0].adjustment == "Active one"


# =============================================================================
# TESTS D'INTÉGRATION CONTAINER
# =============================================================================


class TestContainerIntegration:
    """Tests d'intégration avec le Container."""

    def test_container_has_learning_use_cases(self):
        """Le container expose les use cases learning."""
        from app.infrastructure.container import get_container, reset_container

        reset_container()
        container = get_container()

        # Vérifier que les méthodes de factory existent
        assert hasattr(container, "get_analyze_feedback_use_case")
        assert hasattr(container, "get_should_require_review_use_case")
        assert hasattr(container, "get_enhance_prompt_use_case")
        assert hasattr(container, "get_learning_stats_use_case")

        reset_container()

    def test_container_provides_learning_stores(self):
        """Le container fournit les stores learning."""
        from app.infrastructure.container import get_container, reset_container

        reset_container()
        container = get_container()

        assert hasattr(container, "get_learning_pattern_store")
        assert hasattr(container, "get_adjustment_store")

        reset_container()


# =============================================================================
# TESTS DE COMPATIBILITÉ AVEC LE DAEMON
# =============================================================================


class TestDaemonCompatibility:
    """Tests de compatibilité avec le daemon existant."""

    def test_learning_service_facade_available(self):
        """Façade LearningService disponible pour le daemon."""
        from app.domain.services.learning_service import LearningService

        # La façade doit exposer les mêmes méthodes que l'ancien LearningManager
        assert hasattr(LearningService, "analyze_feedback")
        assert hasattr(LearningService, "extract_patterns_from_feedback")
        assert hasattr(LearningService, "generate_prompt_adjustment")
        assert hasattr(LearningService, "should_require_review")
        assert hasattr(LearningService, "get_stats")
        assert hasattr(LearningService, "get_active_adjustments")

    def test_enhance_prompt_method_available(self):
        """Méthode enhance_prompt disponible sur LearningService."""
        from app.domain.services.learning_service import LearningService

        # La méthode doit exister
        assert hasattr(LearningService, "enhance_prompt")
