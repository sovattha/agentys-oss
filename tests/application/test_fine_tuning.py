# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour le module de fine-tuning.

Ce module teste tous les use cases de fine-tuning:
- RecordCorrectionUseCase
- RecordFeedbackUseCase
- ExtractPatternsUseCase
- CreateImprovementModelUseCase
- ActivateModelUseCase
- ApplyImprovementsUseCase
- GetPromptEnhancementsUseCase
- RunFineTuningSessionUseCase
- GetFineTuningStatsUseCase
- ListPatternsUseCase
- ListModelsUseCase
- DisableModelUseCase
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from app.application.fine_tuning import (
    RecordCorrectionUseCase,
    RecordCorrectionResult,
    RecordFeedbackUseCase,
    RecordFeedbackResult,
    ExtractPatternsUseCase,
    ExtractPatternsResult,
    CreateImprovementModelUseCase,
    CreateModelResult,
    ActivateModelUseCase,
    ApplyImprovementsUseCase,
    ApplyImprovementsResult,
    GetPromptEnhancementsUseCase,
    RunFineTuningSessionUseCase,
    FineTuningSessionResult,
    GetFineTuningStatsUseCase,
    ListPatternsUseCase,
    ListModelsUseCase,
    DisableModelUseCase,
)
from app.domain.entities.fine_tuning import (
    FineTuningStats,
    CorrectionType,
    ImprovementStatus,
    FeedbackSentiment,
)
from app.domain.ports.fine_tuning_port import (
    UserCorrectionPort,
    UserFeedbackPort,
    CorrectionPatternPort,
    ImprovementModelPort,
    FineTuningSessionPort,
    FineTuningAnalyzerPort,
)


# =============================================================================
# RECORD CORRECTION USE CASE TESTS
# =============================================================================


class TestRecordCorrectionUseCase(unittest.TestCase):
    """Tests pour RecordCorrectionUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.correction_store = MagicMock(spec=UserCorrectionPort)
        self.pattern_store = MagicMock(spec=CorrectionPatternPort)
        self.analyzer = MagicMock(spec=FineTuningAnalyzerPort)

        self.use_case = RecordCorrectionUseCase(
            correction_store=self.correction_store,
            pattern_store=self.pattern_store,
            analyzer=self.analyzer,
        )

    def test_execute_happy_path(self):
        """Teste l'enregistrement complet d'une correction avec changements significatifs."""
        draft_id = "draft-123"
        original = "This is great email"
        corrected = "This is a great email"

        self.correction_store.save.return_value = "corr-456"
        self.analyzer.analyze_correction.return_value = [CorrectionType.GRAMMAR]
        self.pattern_store.find_similar.return_value = None

        result = self.use_case.execute(
            draft_id=draft_id,
            original_text=original,
            corrected_text=corrected,
        )

        self.assertIsInstance(result, RecordCorrectionResult)
        self.assertEqual(result.correction_id, "corr-456")
        self.assertEqual(result.correction_types, [CorrectionType.GRAMMAR])
        self.assertTrue(result.has_significant_changes)
        self.assertEqual(result.patterns_found, 0)
        self.correction_store.save.assert_called_once()

    def test_execute_with_context_and_comment(self):
        """Teste l'enregistrement avec contexte et commentaire."""
        draft_id = "draft-789"
        original = "Hello world"
        corrected = "Hi world"
        context = {"sender": "client@example.com", "category": "greeting"}
        user_comment = "More informal tone"

        self.correction_store.save.return_value = "corr-999"
        self.analyzer.analyze_correction.return_value = [CorrectionType.TONE, CorrectionType.VOCABULARY]
        self.pattern_store.find_similar.return_value = None

        result = self.use_case.execute(
            draft_id=draft_id,
            original_text=original,
            corrected_text=corrected,
            context=context,
            user_comment=user_comment,
        )

        self.assertIsNotNone(result)
        saved_correction = self.correction_store.save.call_args[0][0]
        self.assertEqual(saved_correction.context, context)
        self.assertEqual(saved_correction.user_comment, user_comment)

    def test_execute_no_significant_changes(self):
        """Teste quand les changements ne sont pas significatifs."""
        # Textes identiques = pas de changement significatif
        original = "Test email content here for testing purposes very long text"
        corrected = "Test email content here for testing purposes very long text"

        self.correction_store.save.return_value = "corr-111"
        self.analyzer.analyze_correction.return_value = []

        result = self.use_case.execute(
            draft_id="draft-222",
            original_text=original,
            corrected_text=corrected,
        )

        self.assertFalse(result.has_significant_changes)
        self.assertEqual(result.patterns_found, 0)

    def test_execute_reinforces_existing_patterns(self):
        """Teste le renforcement des patterns existants."""
        original = "This is great email"
        corrected = "This is a great email"

        mock_pattern = MagicMock()
        mock_pattern.pattern_type = CorrectionType.GRAMMAR
        mock_pattern.examples = []

        self.correction_store.save.return_value = "corr-333"
        self.analyzer.analyze_correction.return_value = [CorrectionType.GRAMMAR]
        self.pattern_store.find_similar.return_value = mock_pattern

        result = self.use_case.execute(
            draft_id="draft-444",
            original_text=original,
            corrected_text=corrected,
        )

        self.assertEqual(result.patterns_found, 1)
        mock_pattern.increment_occurrence.assert_called_once()
        self.pattern_store.update.assert_called_once_with(mock_pattern)

    def test_execute_multiple_correction_types(self):
        """Teste avec plusieurs types de corrections détectés."""
        original = "Hello world test"
        corrected = "Hi there comprehensive example"

        self.correction_store.save.return_value = "corr-555"
        self.analyzer.analyze_correction.return_value = [
            CorrectionType.TONE,
            CorrectionType.VOCABULARY,
            CorrectionType.CONTENT,
        ]
        self.pattern_store.find_similar.return_value = None

        result = self.use_case.execute(
            draft_id="draft-666",
            original_text=original,
            corrected_text=corrected,
        )

        self.assertEqual(len(result.correction_types), 3)
        self.assertIn(CorrectionType.TONE, result.correction_types)

    def test_execute_mismatched_pattern_type(self):
        """Teste quand le pattern trouvé n'a pas le bon type."""
        original = "Test email"
        corrected = "Test message"

        mock_pattern = MagicMock()
        mock_pattern.pattern_type = CorrectionType.VOCABULARY

        self.correction_store.save.return_value = "corr-777"
        self.analyzer.analyze_correction.return_value = [CorrectionType.TONE]
        self.pattern_store.find_similar.return_value = mock_pattern

        result = self.use_case.execute(
            draft_id="draft-888",
            original_text=original,
            corrected_text=corrected,
        )

        # Pattern ne doit pas être renforcé car type ne correspond pas
        self.assertEqual(result.patterns_found, 0)


# =============================================================================
# RECORD FEEDBACK USE CASE TESTS
# =============================================================================


class TestRecordFeedbackUseCase(unittest.TestCase):
    """Tests pour RecordFeedbackUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.feedback_store = MagicMock(spec=UserFeedbackPort)
        self.use_case = RecordFeedbackUseCase(feedback_store=self.feedback_store)

    def test_execute_positive_feedback(self):
        """Teste l'enregistrement d'un feedback positif."""
        self.feedback_store.save.return_value = "feedback-123"

        result = self.use_case.execute(
            draft_id="draft-001",
            rating=5,
            comment="Excellent draft!",
        )

        self.assertIsInstance(result, RecordFeedbackResult)
        self.assertEqual(result.feedback_id, "feedback-123")
        self.assertEqual(result.sentiment, FeedbackSentiment.POSITIVE)
        self.assertFalse(result.requires_analysis)

    def test_execute_negative_feedback_with_long_comment(self):
        """Teste feedback négatif avec commentaire suffisamment long."""
        self.feedback_store.save.return_value = "feedback-456"

        result = self.use_case.execute(
            draft_id="draft-002",
            rating=1,
            comment="This is completely wrong and needs major revisions",
        )

        self.assertEqual(result.sentiment, FeedbackSentiment.NEGATIVE)
        self.assertTrue(result.requires_analysis)

    def test_execute_negative_feedback_short_comment(self):
        """Teste feedback négatif avec commentaire trop court."""
        self.feedback_store.save.return_value = "feedback-789"

        result = self.use_case.execute(
            draft_id="draft-003",
            rating=2,
            comment="Bad",  # Moins de 10 caractères
        )

        self.assertEqual(result.sentiment, FeedbackSentiment.NEGATIVE)
        self.assertFalse(result.requires_analysis)

    def test_execute_neutral_feedback(self):
        """Teste feedback neutre (note 3)."""
        self.feedback_store.save.return_value = "feedback-111"

        result = self.use_case.execute(
            draft_id="draft-004",
            rating=3,
            comment="It's okay but could be better",
        )

        self.assertEqual(result.sentiment, FeedbackSentiment.NEUTRAL)
        self.assertFalse(result.requires_analysis)

    def test_execute_negative_feedback_no_comment(self):
        """Teste feedback négatif sans commentaire."""
        self.feedback_store.save.return_value = "feedback-222"

        result = self.use_case.execute(
            draft_id="draft-005",
            rating=1,
        )

        self.assertEqual(result.sentiment, FeedbackSentiment.NEGATIVE)
        self.assertFalse(result.requires_analysis)

    def test_execute_with_tags(self):
        """Teste l'enregistrement avec tags."""
        self.feedback_store.save.return_value = "feedback-333"
        tags = ["tone", "clarity", "structure"]

        self.use_case.execute(
            draft_id="draft-006",
            rating=2,
            comment="Not quite right on multiple fronts",
            tags=tags,
        )

        saved_feedback = self.feedback_store.save.call_args[0][0]
        self.assertEqual(saved_feedback.tags, tags)


# =============================================================================
# EXTRACT PATTERNS USE CASE TESTS
# =============================================================================


class TestExtractPatternsUseCase(unittest.TestCase):
    """Tests pour ExtractPatternsUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.correction_store = MagicMock(spec=UserCorrectionPort)
        self.pattern_store = MagicMock(spec=CorrectionPatternPort)
        self.analyzer = MagicMock(spec=FineTuningAnalyzerPort)

        self.use_case = ExtractPatternsUseCase(
            correction_store=self.correction_store,
            pattern_store=self.pattern_store,
            analyzer=self.analyzer,
        )

    def test_execute_insufficient_corrections(self):
        """Teste quand il n'y a pas assez de corrections."""
        self.correction_store.get_recent.return_value = [
            MagicMock(),
            MagicMock(),
        ]  # Moins que min_corrections=5

        result = self.use_case.execute(min_corrections=5)

        self.assertIsInstance(result, ExtractPatternsResult)
        self.assertEqual(result.patterns_extracted, 0)
        self.assertEqual(result.patterns_reinforced, 0)
        self.assertEqual(len(result.new_patterns), 0)

    def test_execute_happy_path(self):
        """Teste l'extraction complète avec nouveaux et anciens patterns."""
        corrections = [MagicMock() for _ in range(10)]

        new_pattern1 = MagicMock()
        new_pattern1.original_pattern = "is great"
        new_pattern1.contexts = []
        new_pattern1.examples = []

        existing_pattern = MagicMock()
        existing_pattern.contexts = []
        existing_pattern.examples = []

        self.correction_store.get_recent.return_value = corrections
        self.analyzer.extract_patterns.return_value = [new_pattern1, existing_pattern]
        self.pattern_store.find_similar.side_effect = [None, existing_pattern]

        result = self.use_case.execute(min_corrections=5)

        self.assertEqual(result.patterns_extracted, 2)
        self.assertEqual(result.patterns_reinforced, 1)
        self.assertEqual(len(result.new_patterns), 1)
        self.pattern_store.save.assert_called_once()

    def test_execute_all_new_patterns(self):
        """Teste quand tous les patterns extraits sont nouveaux."""
        corrections = [MagicMock() for _ in range(7)]

        patterns = [MagicMock() for _ in range(3)]
        for p in patterns:
            p.contexts = []
            p.examples = []

        self.correction_store.get_recent.return_value = corrections
        self.analyzer.extract_patterns.return_value = patterns
        self.pattern_store.find_similar.return_value = None

        result = self.use_case.execute(min_corrections=5)

        self.assertEqual(result.patterns_extracted, 3)
        self.assertEqual(result.patterns_reinforced, 0)
        self.assertEqual(len(result.new_patterns), 3)
        self.assertEqual(self.pattern_store.save.call_count, 3)

    def test_execute_with_custom_since_date(self):
        """Teste avec une date personnalisée."""
        since = datetime.now() - timedelta(days=14)
        corrections = [MagicMock() for _ in range(8)]

        self.correction_store.get_recent.return_value = corrections
        self.analyzer.extract_patterns.return_value = []

        self.use_case.execute(since=since, min_corrections=5)

        self.correction_store.get_recent.assert_called_once_with(limit=500, since=since)

    def test_execute_reinforces_existing_contexts_and_examples(self):
        """Teste que les contextes et exemples sont bien étendus."""
        corrections = [MagicMock() for _ in range(6)]

        extracted_pattern = MagicMock()
        extracted_pattern.original_pattern = "test"
        extracted_pattern.contexts = [{"test": "context"}]
        extracted_pattern.examples = [{"original": "test", "corrected": "exam"}]

        existing_pattern = MagicMock()
        existing_pattern.contexts = []
        existing_pattern.examples = []

        self.correction_store.get_recent.return_value = corrections
        self.analyzer.extract_patterns.return_value = [extracted_pattern]
        self.pattern_store.find_similar.return_value = existing_pattern

        self.use_case.execute(min_corrections=5)

        existing_pattern.increment_occurrence.assert_called_once()
        # Vérifier que extend a été appelé
        self.pattern_store.update.assert_called_once_with(existing_pattern)


# =============================================================================
# CREATE IMPROVEMENT MODEL USE CASE TESTS
# =============================================================================


class TestCreateImprovementModelUseCase(unittest.TestCase):
    """Tests pour CreateImprovementModelUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.model_store = MagicMock(spec=ImprovementModelPort)
        self.pattern_store = MagicMock(spec=CorrectionPatternPort)
        self.analyzer = MagicMock(spec=FineTuningAnalyzerPort)

        self.use_case = CreateImprovementModelUseCase(
            model_store=self.model_store,
            pattern_store=self.pattern_store,
            analyzer=self.analyzer,
        )

    def test_execute_happy_path(self):
        """Teste la création complète d'un modèle."""
        pattern1 = MagicMock()
        pattern1.id = "pattern-1"
        pattern2 = MagicMock()
        pattern2.id = "pattern-2"

        self.model_store.get_latest.return_value = MagicMock(version="1.0.0")
        self.pattern_store.get_reliable_patterns.return_value = [pattern1, pattern2]
        self.analyzer.generate_prompt_adjustments.return_value = [
            "Adjustment 1",
            "Adjustment 2",
        ]
        self.model_store.save.return_value = "model-123"

        result = self.use_case.execute(
            name="Test Model",
            description="A test improvement model",
        )

        self.assertIsInstance(result, CreateModelResult)
        self.assertEqual(result.model_id, "model-123")
        self.assertEqual(result.model_name, "Test Model")
        self.assertEqual(result.patterns_included, 2)
        self.assertEqual(result.prompt_adjustments, 2)

    def test_execute_version_increment(self):
        """Teste l'incrémentation automatique de version."""
        self.model_store.get_latest.return_value = MagicMock(version="2.1.5")
        self.pattern_store.get_reliable_patterns.return_value = []
        self.analyzer.generate_prompt_adjustments.return_value = []
        self.model_store.save.return_value = "model-456"

        self.use_case.execute(
            name="New Model",
            description="Updated model",
        )

        saved_model = self.model_store.save.call_args[0][0]
        self.assertEqual(saved_model.version, "2.1.6")

    def test_execute_first_model_version(self):
        """Teste la création du premier modèle."""
        self.model_store.get_latest.return_value = None
        self.pattern_store.get_reliable_patterns.return_value = []
        self.analyzer.generate_prompt_adjustments.return_value = []
        self.model_store.save.return_value = "model-789"

        self.use_case.execute(
            name="First Model",
            description="The first model",
        )

        saved_model = self.model_store.save.call_args[0][0]
        self.assertEqual(saved_model.version, "1.0.0")

    def test_execute_custom_version(self):
        """Teste avec une version personnalisée."""
        self.pattern_store.get_reliable_patterns.return_value = []
        self.analyzer.generate_prompt_adjustments.return_value = []
        self.model_store.save.return_value = "model-111"

        self.use_case.execute(
            name="Custom Model",
            description="With custom version",
            version="3.2.1",
        )

        saved_model = self.model_store.save.call_args[0][0]
        self.assertEqual(saved_model.version, "3.2.1")

    def test_execute_min_confidence_filter(self):
        """Teste le filtre de confiance minimale."""
        patterns = [MagicMock() for _ in range(3)]

        self.model_store.get_latest.return_value = None
        self.pattern_store.get_reliable_patterns.return_value = patterns
        self.analyzer.generate_prompt_adjustments.return_value = []
        self.model_store.save.return_value = "model-222"

        self.use_case.execute(
            name="Test",
            description="Test",
            min_confidence=0.8,
        )

        self.pattern_store.get_reliable_patterns.assert_called_once_with(
            min_confidence=0.8
        )

    def test_execute_adds_patterns_and_adjustments(self):
        """Teste que patterns et adjustments sont bien ajoutés au modèle."""
        pattern1 = MagicMock()
        pattern1.id = "p1"
        pattern2 = MagicMock()
        pattern2.id = "p2"

        self.model_store.get_latest.return_value = None
        self.pattern_store.get_reliable_patterns.return_value = [pattern1, pattern2]
        self.analyzer.generate_prompt_adjustments.return_value = ["Adj1", "Adj2", "Adj3"]
        self.model_store.save.return_value = "model-333"

        self.use_case.execute(
            name="Complete Model",
            description="With patterns and adjustments",
        )

        saved_model = self.model_store.save.call_args[0][0]
        self.assertEqual(len(saved_model.patterns), 2)
        self.assertEqual(len(saved_model.prompt_adjustments), 3)


# =============================================================================
# ACTIVATE MODEL USE CASE TESTS
# =============================================================================


class TestActivateModelUseCase(unittest.TestCase):
    """Tests pour ActivateModelUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.model_store = MagicMock(spec=ImprovementModelPort)
        self.use_case = ActivateModelUseCase(model_store=self.model_store)

    def test_execute_happy_path(self):
        """Teste l'activation simple d'un modèle."""
        model = MagicMock()
        model.id = "model-123"

        self.model_store.get_by_id.return_value = model
        self.model_store.get_active_models.return_value = []
        self.model_store.update.return_value = True

        result = self.use_case.execute("model-123")

        self.assertTrue(result)
        model.activate.assert_called_once()
        self.model_store.update.assert_called_once_with(model)

    def test_execute_deactivates_existing_active_models(self):
        """Teste la désactivation des modèles actifs existants."""
        new_model = MagicMock()
        new_model.id = "model-new"

        active_model1 = MagicMock()
        active_model1.id = "model-active1"
        active_model2 = MagicMock()
        active_model2.id = "model-active2"

        self.model_store.get_by_id.return_value = new_model
        self.model_store.get_active_models.return_value = [active_model1, active_model2]
        self.model_store.update.return_value = True

        self.use_case.execute("model-new")

        active_model1.deprecate.assert_called_once()
        active_model2.deprecate.assert_called_once()
        self.assertEqual(self.model_store.update.call_count, 3)

    def test_execute_model_not_found(self):
        """Teste quand le modèle n'existe pas."""
        self.model_store.get_by_id.return_value = None

        with self.assertRaises(ValueError) as context:
            self.use_case.execute("nonexistent-model")

        self.assertIn("not found", str(context.exception))

    def test_execute_does_not_deprecate_same_model(self):
        """Teste qu'on ne désactive pas le modèle qu'on active."""
        model = MagicMock()
        model.id = "model-123"

        active = MagicMock()
        active.id = "model-123"  # Même ID

        self.model_store.get_by_id.return_value = model
        self.model_store.get_active_models.return_value = [active]
        self.model_store.update.return_value = True

        self.use_case.execute("model-123")

        # deprecate() ne doit pas être appelé sur le même modèle
        active.deprecate.assert_not_called()


# =============================================================================
# APPLY IMPROVEMENTS USE CASE TESTS
# =============================================================================


class TestApplyImprovementsUseCase(unittest.TestCase):
    """Tests pour ApplyImprovementsUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.model_store = MagicMock(spec=ImprovementModelPort)
        self.pattern_store = MagicMock(spec=CorrectionPatternPort)
        self.analyzer = MagicMock(spec=FineTuningAnalyzerPort)

        self.use_case = ApplyImprovementsUseCase(
            model_store=self.model_store,
            pattern_store=self.pattern_store,
            analyzer=self.analyzer,
        )

    def test_execute_happy_path(self):
        """Teste l'application réussie d'améliorations."""
        text = "This is test text"
        improved_text = "This is a test text"

        model = MagicMock()
        model.patterns = ["p1", "p2"]

        pattern1 = MagicMock()
        pattern1.id = "p1"
        pattern1.original_pattern = "is test"
        pattern1.is_reliable.return_value = True

        pattern2 = MagicMock()
        pattern2.id = "p2"
        pattern2.original_pattern = "unknown"
        pattern2.is_reliable.return_value = True

        self.model_store.get_by_id.return_value = model
        self.pattern_store.get_by_id.side_effect = [pattern1, pattern2]
        self.analyzer.apply_improvements.return_value = improved_text
        self.model_store.update.return_value = True

        result = self.use_case.execute(text, model_id="model-123")

        self.assertIsInstance(result, ApplyImprovementsResult)
        self.assertEqual(result.improved_text, improved_text)
        self.assertEqual(result.improvements_applied, 1)
        model.record_improvement.assert_called_once()

    def test_execute_no_active_model(self):
        """Teste quand aucun modèle actif n'existe."""
        text = "Original text"

        self.model_store.get_active_models.return_value = []

        result = self.use_case.execute(text)

        self.assertEqual(result.improved_text, text)
        self.assertEqual(result.improvements_applied, 0)
        self.assertEqual(len(result.patterns_used), 0)

    def test_execute_with_explicit_model_id(self):
        """Teste avec un ID de modèle explicite."""
        text = "Test"
        model = MagicMock()
        model.patterns = []

        self.model_store.get_by_id.return_value = model
        self.analyzer.apply_improvements.return_value = text
        self.model_store.update.return_value = True

        self.use_case.execute(text, model_id="specific-model")

        self.model_store.get_by_id.assert_called_once_with("specific-model")
        self.model_store.get_active_models.assert_not_called()

    def test_execute_filters_unreliable_patterns(self):
        """Teste que les patterns peu fiables ne sont pas utilisés."""
        text = "Test text"

        model = MagicMock()
        model.patterns = ["p1", "p2"]

        pattern1 = MagicMock()
        pattern1.is_reliable.return_value = False

        pattern2 = MagicMock()
        pattern2.is_reliable.return_value = True
        pattern2.original_pattern = "pattern"
        pattern2.id = "p2"

        self.model_store.get_by_id.return_value = model
        self.pattern_store.get_by_id.side_effect = [pattern1, pattern2]
        self.analyzer.apply_improvements.return_value = text
        self.model_store.update.return_value = True

        self.use_case.execute(text, model_id="model-123")

        # Seul le pattern fiable doit être passé à l'analyzer
        call_args = self.analyzer.apply_improvements.call_args
        self.assertEqual(len(call_args[0][2]), 1)  # patterns argument

    def test_execute_model_not_found(self):
        """Teste quand le modèle spécifié n'existe pas."""
        text = "Test"

        self.model_store.get_by_id.return_value = None

        result = self.use_case.execute(text, model_id="nonexistent")

        self.assertEqual(result.improved_text, text)
        self.assertEqual(result.improvements_applied, 0)


# =============================================================================
# GET PROMPT ENHANCEMENTS USE CASE TESTS
# =============================================================================


class TestGetPromptEnhancementsUseCase(unittest.TestCase):
    """Tests pour GetPromptEnhancementsUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.model_store = MagicMock(spec=ImprovementModelPort)
        self.pattern_store = MagicMock(spec=CorrectionPatternPort)

        self.use_case = GetPromptEnhancementsUseCase(
            model_store=self.model_store,
            pattern_store=self.pattern_store,
        )

    def test_execute_happy_path(self):
        """Teste la récupération des améliorations de prompt."""
        model1 = MagicMock()
        model1.prompt_adjustments = ["Adj1", "Adj2"]

        model2 = MagicMock()
        model2.prompt_adjustments = ["Adj3"]

        self.model_store.get_active_models.return_value = [model1, model2]

        result = self.use_case.execute()

        self.assertEqual(len(result), 3)
        self.assertIn("Adj1", result)
        self.assertIn("Adj2", result)
        self.assertIn("Adj3", result)

    def test_execute_no_active_models(self):
        """Teste quand aucun modèle actif."""
        self.model_store.get_active_models.return_value = []

        result = self.use_case.execute()

        self.assertEqual(len(result), 0)

    def test_execute_models_with_empty_adjustments(self):
        """Teste avec des modèles sans ajustements."""
        model1 = MagicMock()
        model1.prompt_adjustments = []

        model2 = MagicMock()
        model2.prompt_adjustments = ["Adj1"]

        self.model_store.get_active_models.return_value = [model1, model2]

        result = self.use_case.execute()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "Adj1")


# =============================================================================
# RUN FINE TUNING SESSION USE CASE TESTS
# =============================================================================


class TestRunFineTuningSessionUseCase(unittest.TestCase):
    """Tests pour RunFineTuningSessionUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.session_store = MagicMock(spec=FineTuningSessionPort)
        self.correction_store = MagicMock(spec=UserCorrectionPort)
        self.feedback_store = MagicMock(spec=UserFeedbackPort)
        self.pattern_store = MagicMock(spec=CorrectionPatternPort)
        self.model_store = MagicMock(spec=ImprovementModelPort)
        self.analyzer = MagicMock(spec=FineTuningAnalyzerPort)

        self.use_case = RunFineTuningSessionUseCase(
            session_store=self.session_store,
            correction_store=self.correction_store,
            feedback_store=self.feedback_store,
            pattern_store=self.pattern_store,
            model_store=self.model_store,
            analyzer=self.analyzer,
        )

    def test_execute_happy_path(self):
        """Teste l'exécution complète d'une session."""
        corrections = [MagicMock() for _ in range(15)]
        feedbacks = [MagicMock() for _ in range(5)]
        patterns = [MagicMock() for _ in range(4)]

        for p in patterns:
            p.original_pattern = f"pattern{p.id}"
            p.id = f"p{id(p)}"

        reliable_patterns = patterns[:3]

        self.correction_store.get_recent.return_value = corrections
        self.feedback_store.get_recent.return_value = feedbacks
        self.analyzer.extract_patterns.return_value = patterns
        self.pattern_store.find_similar.return_value = None
        self.pattern_store.get_reliable_patterns.return_value = reliable_patterns
        self.analyzer.generate_prompt_adjustments.return_value = ["Adj1"]
        self.model_store.save.return_value = "model-123"
        self.session_store.update.return_value = True

        result = self.use_case.execute(min_corrections=10)

        self.assertIsInstance(result, FineTuningSessionResult)
        self.assertEqual(result.corrections_analyzed, 15)
        self.assertEqual(result.feedbacks_analyzed, 5)
        self.assertEqual(result.patterns_extracted, 4)
        self.assertEqual(result.model_created, "model-123")

    def test_execute_insufficient_corrections(self):
        """Teste quand il n'y a pas assez de corrections."""
        self.correction_store.get_recent.return_value = [MagicMock() for _ in range(5)]
        self.feedback_store.get_recent.return_value = []
        self.session_store.update.return_value = True

        result = self.use_case.execute(min_corrections=10)

        self.assertEqual(result.corrections_analyzed, 5)
        self.assertIsNone(result.model_created)

    def test_execute_insufficient_reliable_patterns(self):
        """Teste quand pas assez de patterns fiables pour créer un modèle."""
        corrections = [MagicMock() for _ in range(15)]
        self.correction_store.get_recent.return_value = corrections
        self.feedback_store.get_recent.return_value = []
        self.analyzer.extract_patterns.return_value = [MagicMock()]
        self.pattern_store.find_similar.return_value = None
        self.pattern_store.get_reliable_patterns.return_value = []  # Pas de patterns fiables
        self.session_store.update.return_value = True

        result = self.use_case.execute(min_corrections=10)

        self.assertIsNone(result.model_created)

    def test_execute_with_auto_activate(self):
        """Teste l'activation automatique du modèle créé."""
        corrections = [MagicMock() for _ in range(15)]
        pattern = MagicMock()
        pattern.id = "p1"

        self.correction_store.get_recent.return_value = corrections
        self.feedback_store.get_recent.return_value = []
        self.analyzer.extract_patterns.return_value = [pattern, pattern, pattern, pattern]
        self.pattern_store.find_similar.return_value = None
        self.pattern_store.get_reliable_patterns.return_value = [pattern, pattern, pattern]
        self.analyzer.generate_prompt_adjustments.return_value = []
        self.model_store.save.return_value = "model-456"
        self.session_store.update.return_value = True

        self.use_case.execute(auto_activate=True, min_corrections=10)

        # Vérifier que le modèle a été activé (update appelé après activate)
        self.model_store.update.assert_called()
        updated_model = self.model_store.update.call_args[0][0]
        self.assertEqual(updated_model.status, ImprovementStatus.ACTIVE)

    def test_execute_handles_exception(self):
        """Teste la gestion des erreurs pendant la session."""
        self.correction_store.get_recent.side_effect = Exception("Database error")
        self.session_store.update.return_value = True

        with self.assertRaises(Exception):
            self.use_case.execute()

        # Vérifier que la session a été marquée comme échouée
        failed_session = self.session_store.update.call_args[0][0]
        self.assertIn("failed", failed_session.status)


# =============================================================================
# GET FINE TUNING STATS USE CASE TESTS
# =============================================================================


class TestGetFineTuningStatsUseCase(unittest.TestCase):
    """Tests pour GetFineTuningStatsUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.correction_store = MagicMock(spec=UserCorrectionPort)
        self.feedback_store = MagicMock(spec=UserFeedbackPort)
        self.pattern_store = MagicMock(spec=CorrectionPatternPort)
        self.model_store = MagicMock(spec=ImprovementModelPort)

        self.use_case = GetFineTuningStatsUseCase(
            correction_store=self.correction_store,
            feedback_store=self.feedback_store,
            pattern_store=self.pattern_store,
            model_store=self.model_store,
        )

    def test_execute_happy_path(self):
        """Teste le calcul complet des statistiques."""
        correction1 = MagicMock()
        correction1.correction_types = [CorrectionType.GRAMMAR, CorrectionType.TONE]
        correction2 = MagicMock()
        correction2.correction_types = [CorrectionType.GRAMMAR]

        pattern1 = MagicMock()
        pattern1.confidence = 0.9
        pattern2 = MagicMock()
        pattern2.confidence = 0.7
        pattern3 = MagicMock()
        pattern3.confidence = 0.4

        model = MagicMock()
        model.impact_score = 0.85
        model.drafts_improved = 10

        self.correction_store.count.return_value = 25
        self.correction_store.get_recent.return_value = [correction1, correction2]
        self.feedback_store.count.return_value = 15
        self.feedback_store.get_sentiment_distribution.return_value = {
            "positive": 8,
            "neutral": 4,
            "negative": 3,
        }
        self.pattern_store.count.return_value = 12
        self.pattern_store.get_all.return_value = [pattern1, pattern2, pattern3]
        self.model_store.get_active_models.return_value = [model]

        result = self.use_case.execute()

        self.assertIsInstance(result, FineTuningStats)
        self.assertEqual(result.total_corrections, 25)
        self.assertEqual(result.total_feedbacks, 15)
        self.assertEqual(result.total_patterns, 12)
        self.assertEqual(result.active_models, 1)
        self.assertEqual(result.average_impact, 0.85)

    def test_execute_correction_types_distribution(self):
        """Teste la distribution des types de correction."""
        corr1 = MagicMock()
        corr1.correction_types = [CorrectionType.GRAMMAR, CorrectionType.GRAMMAR]
        corr2 = MagicMock()
        corr2.correction_types = [CorrectionType.TONE]

        self.correction_store.count.return_value = 2
        self.correction_store.get_recent.return_value = [corr1, corr2]
        self.feedback_store.count.return_value = 0
        self.feedback_store.get_sentiment_distribution.return_value = {}
        self.pattern_store.count.return_value = 0
        self.pattern_store.get_all.return_value = []
        self.model_store.get_active_models.return_value = []

        result = self.use_case.execute()

        self.assertEqual(result.top_correction_types["grammar"], 2)
        self.assertEqual(result.top_correction_types["tone"], 1)

    def test_execute_patterns_by_confidence(self):
        """Teste la distribution des patterns par confiance."""
        patterns = [
            MagicMock(confidence=0.95),  # high
            MagicMock(confidence=0.85),  # high
            MagicMock(confidence=0.75),  # medium
            MagicMock(confidence=0.65),  # medium
            MagicMock(confidence=0.45),  # low
        ]

        self.correction_store.count.return_value = 0
        self.correction_store.get_recent.return_value = []
        self.feedback_store.count.return_value = 0
        self.feedback_store.get_sentiment_distribution.return_value = {}
        self.pattern_store.count.return_value = 5
        self.pattern_store.get_all.return_value = patterns
        self.model_store.get_active_models.return_value = []

        result = self.use_case.execute()

        self.assertEqual(result.patterns_by_confidence["high"], 2)
        self.assertEqual(result.patterns_by_confidence["medium"], 2)
        self.assertEqual(result.patterns_by_confidence["low"], 1)

    def test_execute_improvement_rate(self):
        """Teste le calcul du taux d'amélioration."""
        model = MagicMock()
        model.drafts_improved = 20

        self.correction_store.count.return_value = 100
        self.correction_store.get_recent.return_value = []
        self.feedback_store.count.return_value = 50
        self.feedback_store.get_sentiment_distribution.return_value = {}
        self.pattern_store.count.return_value = 0
        self.pattern_store.get_all.return_value = []
        self.model_store.get_active_models.return_value = [model]

        result = self.use_case.execute()

        # improvement_rate = 20 / (100 + 50) * 100 = 13.33%
        self.assertAlmostEqual(result.improvement_rate, 20 / 150 * 100, places=1)

    def test_execute_no_data(self):
        """Teste avec aucune donnée."""
        self.correction_store.count.return_value = 0
        self.correction_store.get_recent.return_value = []
        self.feedback_store.count.return_value = 0
        self.feedback_store.get_sentiment_distribution.return_value = {}
        self.pattern_store.count.return_value = 0
        self.pattern_store.get_all.return_value = []
        self.model_store.get_active_models.return_value = []

        result = self.use_case.execute()

        self.assertEqual(result.total_corrections, 0)
        self.assertEqual(result.total_feedbacks, 0)
        self.assertEqual(result.active_models, 0)


# =============================================================================
# LIST PATTERNS USE CASE TESTS
# =============================================================================


class TestListPatternsUseCase(unittest.TestCase):
    """Tests pour ListPatternsUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.pattern_store = MagicMock(spec=CorrectionPatternPort)
        self.use_case = ListPatternsUseCase(pattern_store=self.pattern_store)

    def test_execute_all_patterns(self):
        """Teste la récupération de tous les patterns."""
        patterns = [MagicMock() for _ in range(5)]

        self.pattern_store.get_all.return_value = patterns

        result = self.use_case.execute()

        self.assertEqual(len(result), 5)
        self.pattern_store.get_all.assert_called_once_with(limit=100)

    def test_execute_by_type(self):
        """Teste la récupération par type."""
        patterns = [MagicMock() for _ in range(3)]

        self.pattern_store.get_by_type.return_value = patterns

        result = self.use_case.execute(pattern_type=CorrectionType.GRAMMAR)

        self.assertEqual(len(result), 3)
        self.pattern_store.get_by_type.assert_called_once_with(
            pattern_type=CorrectionType.GRAMMAR,
            limit=100,
        )

    def test_execute_by_min_confidence(self):
        """Teste la récupération par confiance minimale."""
        patterns = [MagicMock() for _ in range(2)]

        self.pattern_store.get_reliable_patterns.return_value = patterns

        result = self.use_case.execute(min_confidence=0.75)

        self.assertEqual(len(result), 2)
        self.pattern_store.get_reliable_patterns.assert_called_once_with(
            min_confidence=0.75,
            limit=100,
        )

    def test_execute_custom_limit(self):
        """Teste avec une limite personnalisée."""
        patterns = [MagicMock() for _ in range(50)]

        self.pattern_store.get_all.return_value = patterns

        self.use_case.execute(limit=50)

        self.pattern_store.get_all.assert_called_once_with(limit=50)


# =============================================================================
# LIST MODELS USE CASE TESTS
# =============================================================================


class TestListModelsUseCase(unittest.TestCase):
    """Tests pour ListModelsUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.model_store = MagicMock(spec=ImprovementModelPort)
        self.use_case = ListModelsUseCase(model_store=self.model_store)

    def test_execute_all_models(self):
        """Teste la récupération de tous les modèles."""
        pending = [MagicMock() for _ in range(2)]
        active = [MagicMock() for _ in range(1)]
        disabled = [MagicMock() for _ in range(1)]
        deprecated = [MagicMock()]

        self.model_store.get_by_status.side_effect = [
            pending,
            active,
            disabled,
            deprecated,
        ]

        result = self.use_case.execute()

        self.assertEqual(len(result), 5)

    def test_execute_by_status(self):
        """Teste la récupération par statut."""
        models = [MagicMock() for _ in range(3)]

        self.model_store.get_by_status.return_value = models

        result = self.use_case.execute(status=ImprovementStatus.ACTIVE)

        self.assertEqual(len(result), 3)
        self.model_store.get_by_status.assert_called_once_with(
            status=ImprovementStatus.ACTIVE,
            limit=100,
        )

    def test_execute_custom_limit(self):
        """Teste avec une limite personnalisée."""
        self.model_store.get_by_status.return_value = []

        self.use_case.execute(limit=50)

        # get_by_status est appelé plusieurs fois pour chaque statut
        calls = self.model_store.get_by_status.call_args_list
        for call in calls:
            self.assertEqual(call[1]["limit"], 50)


# =============================================================================
# DISABLE MODEL USE CASE TESTS
# =============================================================================


class TestDisableModelUseCase(unittest.TestCase):
    """Tests pour DisableModelUseCase."""

    def setUp(self):
        """Configuration commune aux tests."""
        self.model_store = MagicMock(spec=ImprovementModelPort)
        self.use_case = DisableModelUseCase(model_store=self.model_store)

    def test_execute_happy_path(self):
        """Teste la désactivation simple d'un modèle."""
        model = MagicMock()

        self.model_store.get_by_id.return_value = model
        self.model_store.update.return_value = True

        result = self.use_case.execute("model-123")

        self.assertTrue(result)
        model.disable.assert_called_once()
        self.model_store.update.assert_called_once_with(model)

    def test_execute_model_not_found(self):
        """Teste quand le modèle n'existe pas."""
        self.model_store.get_by_id.return_value = None

        with self.assertRaises(ValueError) as context:
            self.use_case.execute("nonexistent-model")

        self.assertIn("not found", str(context.exception))

    def test_execute_update_fails(self):
        """Teste quand la mise à jour échoue."""
        model = MagicMock()

        self.model_store.get_by_id.return_value = model
        self.model_store.update.return_value = False

        result = self.use_case.execute("model-456")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
