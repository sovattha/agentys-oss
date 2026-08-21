# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour le système de Fine-tuning avec feedback utilisateur.

Ces tests vérifient :
- Les entités du domaine (UserCorrection, UserFeedback, CorrectionPattern, etc.)
- Les use cases (RecordCorrection, ExtractPatterns, CreateModel, etc.)
- Les stores JSON (persistence)
- L'analyseur de corrections
- L'API REST
"""

import pytest
import tempfile
from pathlib import Path

# Domain Entities
from app.domain.entities.fine_tuning import (
    UserCorrection,
    UserFeedback,
    CorrectionPattern,
    ImprovementModel,
    FineTuningSession,
    CorrectionType,
    ImprovementStatus,
    FeedbackSentiment,
)

# Ports

# Use Cases
from app.application.fine_tuning import (
    RecordCorrectionUseCase,
    RecordFeedbackUseCase,
    ExtractPatternsUseCase,
    CreateImprovementModelUseCase,
    ActivateModelUseCase,
    ApplyImprovementsUseCase,
    GetPromptEnhancementsUseCase,
    GetFineTuningStatsUseCase,
)

# Infrastructure
from app.infrastructure.fine_tuning_store import (
    JsonUserCorrectionStore,
    JsonUserFeedbackStore,
    JsonCorrectionPatternStore,
    JsonImprovementModelStore,
    JsonFineTuningSessionStore,
    DefaultFineTuningAnalyzer,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_dir():
    """Crée un répertoire temporaire pour les tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def correction_store(temp_dir):
    """Store de corrections avec fichier temporaire."""
    return JsonUserCorrectionStore(temp_dir / "corrections.json")


@pytest.fixture
def feedback_store(temp_dir):
    """Store de feedbacks avec fichier temporaire."""
    return JsonUserFeedbackStore(temp_dir / "feedbacks.json")


@pytest.fixture
def pattern_store(temp_dir):
    """Store de patterns avec fichier temporaire."""
    return JsonCorrectionPatternStore(temp_dir / "patterns.json")


@pytest.fixture
def model_store(temp_dir):
    """Store de modèles avec fichier temporaire."""
    return JsonImprovementModelStore(temp_dir / "models.json")


@pytest.fixture
def session_store(temp_dir):
    """Store de sessions avec fichier temporaire."""
    return JsonFineTuningSessionStore(temp_dir / "sessions.json")


@pytest.fixture
def analyzer():
    """Analyseur par défaut."""
    return DefaultFineTuningAnalyzer()


@pytest.fixture
def sample_correction():
    """Correction utilisateur exemple."""
    return UserCorrection.create(
        draft_id="draft-123",
        original_text="Bonjour, Merci pour votre message. Cordialement,",
        corrected_text="Bonjour, Je vous remercie pour votre message. Bien à vous,",
        context={"sender": "test@example.com", "category": "support"},
        user_comment="Ton trop formel",
    )


@pytest.fixture
def sample_feedback():
    """Feedback utilisateur exemple."""
    return UserFeedback.create(
        draft_id="draft-456",
        rating=4,
        comment="Bonne réponse mais un peu longue",
        tags=["length", "style"],
    )


@pytest.fixture
def sample_pattern():
    """Pattern de correction exemple."""
    return CorrectionPattern.create(
        pattern_type=CorrectionType.TONE,
        original_pattern="Cordialement,",
        replacement="Bien à vous,",
        context={"domain": "support"},
    )


@pytest.fixture
def sample_model():
    """Modèle d'amélioration exemple."""
    return ImprovementModel.create(
        name="Test Model",
        description="Modèle de test",
        version="1.0.0",
    )


# =============================================================================
# TESTS ENTITIES
# =============================================================================


class TestUserCorrection:
    """Tests pour l'entité UserCorrection."""

    def test_create_correction(self):
        """Test de création d'une correction."""
        correction = UserCorrection.create(
            draft_id="draft-123",
            original_text="Hello",
            corrected_text="Bonjour",
        )

        assert correction.id is not None
        assert correction.draft_id == "draft-123"
        assert correction.original_text == "Hello"
        assert correction.corrected_text == "Bonjour"
        assert correction.created_at is not None

    def test_has_significant_changes(self):
        """Test de détection de changements significatifs."""
        # Changements significatifs
        correction = UserCorrection.create(
            draft_id="draft-123",
            original_text="Hello world, this is a test message.",
            corrected_text="Bonjour le monde, ceci est un message de test.",
        )
        assert correction.has_significant_changes()

        # Pas de changements significatifs
        correction2 = UserCorrection.create(
            draft_id="draft-123",
            original_text="Hello",
            corrected_text="Hello",
        )
        assert not correction2.has_significant_changes()

    def test_correction_with_context(self):
        """Test avec contexte."""
        correction = UserCorrection.create(
            draft_id="draft-123",
            original_text="test",
            corrected_text="TEST",
            context={"sender": "test@example.com"},
            user_comment="Commentaire",
        )

        assert correction.context == {"sender": "test@example.com"}
        assert correction.user_comment == "Commentaire"


class TestUserFeedback:
    """Tests pour l'entité UserFeedback."""

    def test_create_feedback_positive(self):
        """Test de création d'un feedback positif."""
        feedback = UserFeedback.create(
            draft_id="draft-123",
            rating=5,
        )

        assert feedback.rating == 5
        assert feedback.sentiment == FeedbackSentiment.POSITIVE

    def test_create_feedback_negative(self):
        """Test de création d'un feedback négatif."""
        feedback = UserFeedback.create(
            draft_id="draft-123",
            rating=2,
        )

        assert feedback.rating == 2
        assert feedback.sentiment == FeedbackSentiment.NEGATIVE

    def test_create_feedback_neutral(self):
        """Test de création d'un feedback neutre."""
        feedback = UserFeedback.create(
            draft_id="draft-123",
            rating=3,
        )

        assert feedback.rating == 3
        assert feedback.sentiment == FeedbackSentiment.NEUTRAL

    def test_create_feedback_invalid_rating(self):
        """Test avec note invalide."""
        with pytest.raises(ValueError):
            UserFeedback.create(draft_id="draft-123", rating=6)

        with pytest.raises(ValueError):
            UserFeedback.create(draft_id="draft-123", rating=0)

    def test_feedback_with_tags(self):
        """Test avec tags."""
        feedback = UserFeedback.create(
            draft_id="draft-123",
            rating=4,
            comment="Good",
            tags=["tone", "style"],
        )

        assert feedback.tags == ["tone", "style"]
        assert feedback.comment == "Good"


class TestCorrectionPattern:
    """Tests pour l'entité CorrectionPattern."""

    def test_create_pattern(self):
        """Test de création d'un pattern."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="test",
            replacement="TEST",
        )

        assert pattern.pattern_type == CorrectionType.TONE
        assert pattern.original_pattern == "test"
        assert pattern.replacement == "TEST"
        assert pattern.confidence == 0.5
        assert pattern.occurrences == 1

    def test_increment_occurrence(self):
        """Test d'incrément des occurrences."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.GRAMMAR,
            original_pattern="errur",
            replacement="erreur",
        )

        # Initiales
        assert pattern.occurrences == 1
        assert pattern.confidence == 0.5

        # Après 4 incréments (5 occurrences total)
        for _ in range(4):
            pattern.increment_occurrence()

        assert pattern.occurrences == 5
        assert pattern.confidence == 0.5  # 5/10 = 0.5
        assert pattern.last_used is not None

    def test_is_reliable(self):
        """Test de fiabilité du pattern."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.STYLE,
            original_pattern="test",
            replacement="TEST",
        )

        # Pas fiable initialement
        assert not pattern.is_reliable(min_confidence=0.6)

        # Devenir fiable après plusieurs occurrences
        for _ in range(6):
            pattern.increment_occurrence()

        assert pattern.is_reliable(min_confidence=0.6)


class TestImprovementModel:
    """Tests pour l'entité ImprovementModel."""

    def test_create_model(self):
        """Test de création d'un modèle."""
        model = ImprovementModel.create(
            name="Test Model",
            description="Description",
            version="1.0.0",
        )

        assert model.name == "Test Model"
        assert model.version == "1.0.0"
        assert model.status == ImprovementStatus.PENDING
        assert len(model.patterns) == 0

    def test_activate_model(self):
        """Test d'activation."""
        model = ImprovementModel.create(
            name="Test",
            description="Test",
        )

        model.activate()
        assert model.status == ImprovementStatus.ACTIVE

    def test_disable_model(self):
        """Test de désactivation."""
        model = ImprovementModel.create(
            name="Test",
            description="Test",
        )

        model.activate()
        model.disable()
        assert model.status == ImprovementStatus.DISABLED

    def test_add_pattern_and_adjustment(self):
        """Test d'ajout de patterns et ajustements."""
        model = ImprovementModel.create(
            name="Test",
            description="Test",
        )

        model.add_pattern("pattern-1")
        model.add_pattern("pattern-2")
        model.add_prompt_adjustment("Évite le ton trop formel")

        assert len(model.patterns) == 2
        assert len(model.prompt_adjustments) == 1

    def test_record_improvement(self):
        """Test d'enregistrement d'amélioration."""
        model = ImprovementModel.create(
            name="Test",
            description="Test",
        )

        model.record_improvement()
        model.record_improvement()

        assert model.drafts_improved == 2


class TestFineTuningSession:
    """Tests pour l'entité FineTuningSession."""

    def test_create_session(self):
        """Test de création d'une session."""
        session = FineTuningSession.create()

        assert session.id is not None
        assert session.status == "running"
        assert session.ended_at is None

    def test_complete_session(self):
        """Test de complétion d'une session."""
        session = FineTuningSession.create()
        session.corrections_count = 50
        session.patterns_extracted = 10

        session.complete(model_id="model-123")

        assert session.status == "completed"
        assert session.model_id == "model-123"
        assert session.ended_at is not None

    def test_fail_session(self):
        """Test d'échec d'une session."""
        session = FineTuningSession.create()
        session.fail("Connection error")

        assert "failed" in session.status
        assert "Connection error" in session.status


# =============================================================================
# TESTS STORES (INFRASTRUCTURE)
# =============================================================================


class TestJsonUserCorrectionStore:
    """Tests pour le store de corrections."""

    def test_save_and_get(self, correction_store, sample_correction):
        """Test de sauvegarde et récupération."""
        correction_id = correction_store.save(sample_correction)

        retrieved = correction_store.get_by_id(correction_id)
        assert retrieved is not None
        assert retrieved.draft_id == sample_correction.draft_id

    def test_get_by_draft_id(self, correction_store, sample_correction):
        """Test de récupération par draft_id."""
        correction_store.save(sample_correction)

        corrections = correction_store.get_by_draft_id("draft-123")
        assert len(corrections) == 1

    def test_get_recent(self, correction_store):
        """Test de récupération des corrections récentes."""
        for i in range(5):
            correction = UserCorrection.create(
                draft_id=f"draft-{i}",
                original_text=f"original-{i}",
                corrected_text=f"corrected-{i}",
            )
            correction_store.save(correction)

        recent = correction_store.get_recent(limit=3)
        assert len(recent) == 3

    def test_count(self, correction_store, sample_correction):
        """Test du comptage."""
        assert correction_store.count() == 0
        correction_store.save(sample_correction)
        assert correction_store.count() == 1

    def test_delete(self, correction_store, sample_correction):
        """Test de suppression."""
        correction_id = correction_store.save(sample_correction)
        assert correction_store.count() == 1

        result = correction_store.delete(correction_id)
        assert result is True
        assert correction_store.count() == 0


class TestJsonUserFeedbackStore:
    """Tests pour le store de feedbacks."""

    def test_save_and_get(self, feedback_store, sample_feedback):
        """Test de sauvegarde et récupération."""
        feedback_id = feedback_store.save(sample_feedback)

        retrieved = feedback_store.get_by_id(feedback_id)
        assert retrieved is not None
        assert retrieved.rating == sample_feedback.rating

    def test_get_by_sentiment(self, feedback_store):
        """Test de récupération par sentiment."""
        # Créer feedbacks de différents sentiments
        positive = UserFeedback.create(draft_id="d1", rating=5)
        negative = UserFeedback.create(draft_id="d2", rating=1)
        neutral = UserFeedback.create(draft_id="d3", rating=3)

        feedback_store.save(positive)
        feedback_store.save(negative)
        feedback_store.save(neutral)

        positives = feedback_store.get_by_sentiment(FeedbackSentiment.POSITIVE)
        assert len(positives) == 1
        assert positives[0].rating == 5

    def test_get_average_rating(self, feedback_store):
        """Test du calcul de la moyenne."""
        for rating in [5, 4, 3, 2, 1]:
            fb = UserFeedback.create(draft_id=f"d-{rating}", rating=rating)
            feedback_store.save(fb)

        avg = feedback_store.get_average_rating()
        assert avg == 3.0

    def test_get_sentiment_distribution(self, feedback_store):
        """Test de la distribution des sentiments."""
        feedbacks = [
            UserFeedback.create(draft_id="d1", rating=5),
            UserFeedback.create(draft_id="d2", rating=4),
            UserFeedback.create(draft_id="d3", rating=3),
            UserFeedback.create(draft_id="d4", rating=1),
        ]
        for fb in feedbacks:
            feedback_store.save(fb)

        dist = feedback_store.get_sentiment_distribution()
        assert dist["positive"] == 2
        assert dist["neutral"] == 1
        assert dist["negative"] == 1


class TestJsonCorrectionPatternStore:
    """Tests pour le store de patterns."""

    def test_save_and_get(self, pattern_store, sample_pattern):
        """Test de sauvegarde et récupération."""
        pattern_id = pattern_store.save(sample_pattern)

        retrieved = pattern_store.get_by_id(pattern_id)
        assert retrieved is not None
        assert retrieved.pattern_type == sample_pattern.pattern_type

    def test_update(self, pattern_store, sample_pattern):
        """Test de mise à jour."""
        pattern_store.save(sample_pattern)

        sample_pattern.increment_occurrence()
        result = pattern_store.update(sample_pattern)

        assert result is True
        retrieved = pattern_store.get_by_id(sample_pattern.id)
        assert retrieved.occurrences == 2

    def test_get_reliable_patterns(self, pattern_store):
        """Test de récupération des patterns fiables."""
        # Pattern fiable
        reliable = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="test1",
            replacement="TEST1",
        )
        for _ in range(10):
            reliable.increment_occurrence()
        pattern_store.save(reliable)

        # Pattern non fiable
        unreliable = CorrectionPattern.create(
            pattern_type=CorrectionType.STYLE,
            original_pattern="test2",
            replacement="TEST2",
        )
        pattern_store.save(unreliable)

        patterns = pattern_store.get_reliable_patterns(min_confidence=0.6)
        assert len(patterns) == 1
        assert patterns[0].original_pattern == "test1"

    def test_find_similar(self, pattern_store, sample_pattern):
        """Test de recherche de patterns similaires."""
        pattern_store.save(sample_pattern)

        # Chercher un pattern similaire
        similar = pattern_store.find_similar("Cordialement,", threshold=0.8)
        assert similar is not None
        assert similar.id == sample_pattern.id

        # Chercher un pattern non similaire
        not_similar = pattern_store.find_similar("Bonjour", threshold=0.8)
        assert not_similar is None


class TestJsonImprovementModelStore:
    """Tests pour le store de modèles."""

    def test_save_and_get(self, model_store, sample_model):
        """Test de sauvegarde et récupération."""
        model_id = model_store.save(sample_model)

        retrieved = model_store.get_by_id(model_id)
        assert retrieved is not None
        assert retrieved.name == sample_model.name

    def test_get_active_models(self, model_store):
        """Test de récupération des modèles actifs."""
        model1 = ImprovementModel.create(
            name="Model 1",
            description="Active",
        )
        model1.activate()
        model_store.save(model1)

        model2 = ImprovementModel.create(
            name="Model 2",
            description="Pending",
        )
        model_store.save(model2)

        active = model_store.get_active_models()
        assert len(active) == 1
        assert active[0].name == "Model 1"

    def test_get_latest(self, model_store):
        """Test de récupération du dernier modèle."""
        for i in range(3):
            model = ImprovementModel.create(
                name=f"Model {i}",
                description=f"Version {i}",
            )
            model_store.save(model)

        latest = model_store.get_latest()
        assert latest is not None
        assert latest.name == "Model 2"


# =============================================================================
# TESTS ANALYZER
# =============================================================================


class TestDefaultFineTuningAnalyzer:
    """Tests pour l'analyseur de corrections."""

    def test_analyze_tone_change(self, analyzer):
        """Test de détection de changement de ton."""
        original = "Salut, comment ça va ?"
        corrected = "Bonjour, comment allez-vous ?"

        types = analyzer.analyze_correction(original, corrected)
        assert CorrectionType.TONE in types

    def test_analyze_format_change(self, analyzer):
        """Test de détection de changement de format."""
        original = "Item1 Item2 Item3"
        corrected = "- Item1\n- Item2\n- Item3"

        types = analyzer.analyze_correction(original, corrected)
        assert CorrectionType.FORMAT in types

    def test_analyze_length_change(self, analyzer):
        """Test de détection de changement de longueur."""
        original = "Ceci est un texte très long avec beaucoup de détails inutiles."
        corrected = "Court."

        types = analyzer.analyze_correction(original, corrected)
        assert CorrectionType.LENGTH in types

    def test_analyze_no_change(self, analyzer):
        """Test sans changement significatif."""
        original = "Bonjour"
        corrected = "Bonjour"

        types = analyzer.analyze_correction(original, corrected)
        # Retourne au moins STYLE par défaut
        assert len(types) >= 1

    def test_extract_patterns(self, analyzer):
        """Test d'extraction de patterns."""
        corrections = []
        for i in range(5):
            correction = UserCorrection.create(
                draft_id=f"d-{i}",
                original_text="Cordialement, Jean",
                corrected_text="Bien à vous, Jean",
            )
            correction.correction_types = [CorrectionType.TONE]
            corrections.append(correction)

        patterns = analyzer.extract_patterns(corrections)
        assert len(patterns) >= 1

    def test_generate_prompt_adjustments(self, analyzer):
        """Test de génération d'ajustements."""
        patterns = [
            CorrectionPattern.create(
                pattern_type=CorrectionType.TONE,
                original_pattern="trop formel",
                replacement="plus décontracté",
            ),
            CorrectionPattern.create(
                pattern_type=CorrectionType.LENGTH,
                original_pattern="long texte",
                replacement="court",
            ),
        ]
        # Rendre les patterns fiables
        for p in patterns:
            for _ in range(6):
                p.increment_occurrence()

        adjustments = analyzer.generate_prompt_adjustments(patterns)
        assert len(adjustments) == 2

    def test_apply_improvements(self, analyzer, sample_model, sample_pattern):
        """Test d'application des améliorations."""
        # Rendre le pattern fiable
        for _ in range(10):
            sample_pattern.increment_occurrence()

        text = "Bonjour, Cordialement, John"
        improved = analyzer.apply_improvements(text, sample_model, [sample_pattern])

        # Le texte devrait être modifié
        assert "Bien à vous" in improved


# =============================================================================
# TESTS USE CASES
# =============================================================================


class TestRecordCorrectionUseCase:
    """Tests pour RecordCorrectionUseCase."""

    def test_execute_simple(self, correction_store, pattern_store, analyzer):
        """Test d'exécution simple."""
        use_case = RecordCorrectionUseCase(
            correction_store=correction_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(
            draft_id="draft-123",
            original_text="Hello",
            corrected_text="Bonjour",
        )

        assert result.correction_id is not None
        assert len(result.correction_types) > 0

    def test_execute_with_context(self, correction_store, pattern_store, analyzer):
        """Test avec contexte."""
        use_case = RecordCorrectionUseCase(
            correction_store=correction_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(
            draft_id="draft-123",
            original_text="Test original",
            corrected_text="Test corrigé avec plus de contenu",
            context={"sender": "test@example.com"},
            user_comment="Commentaire",
        )

        assert result.correction_id is not None
        assert result.has_significant_changes


class TestRecordFeedbackUseCase:
    """Tests pour RecordFeedbackUseCase."""

    def test_execute_positive(self, feedback_store):
        """Test avec feedback positif."""
        use_case = RecordFeedbackUseCase(feedback_store=feedback_store)

        result = use_case.execute(
            draft_id="draft-123",
            rating=5,
            comment="Excellent",
        )

        assert result.feedback_id is not None
        assert result.sentiment == FeedbackSentiment.POSITIVE
        assert not result.requires_analysis

    def test_execute_negative_requires_analysis(self, feedback_store):
        """Test avec feedback négatif nécessitant une analyse."""
        use_case = RecordFeedbackUseCase(feedback_store=feedback_store)

        result = use_case.execute(
            draft_id="draft-123",
            rating=1,
            comment="Très mauvaise réponse, le ton est complètement inapproprié",
        )

        assert result.sentiment == FeedbackSentiment.NEGATIVE
        assert result.requires_analysis


class TestExtractPatternsUseCase:
    """Tests pour ExtractPatternsUseCase."""

    def test_execute_not_enough_corrections(
        self, correction_store, pattern_store, analyzer
    ):
        """Test avec pas assez de corrections."""
        use_case = ExtractPatternsUseCase(
            correction_store=correction_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(min_corrections=10)

        assert result.patterns_extracted == 0
        assert len(result.new_patterns) == 0

    def test_execute_with_corrections(
        self, correction_store, pattern_store, analyzer
    ):
        """Test avec assez de corrections."""
        # Ajouter des corrections
        for i in range(10):
            correction = UserCorrection.create(
                draft_id=f"draft-{i}",
                original_text="Cordialement, Jean",
                corrected_text="Bien à vous, Jean",
            )
            correction.correction_types = [CorrectionType.TONE]
            correction_store.save(correction)

        use_case = ExtractPatternsUseCase(
            correction_store=correction_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(min_corrections=5)

        assert result.patterns_extracted >= 0


class TestCreateImprovementModelUseCase:
    """Tests pour CreateImprovementModelUseCase."""

    def test_execute_no_patterns(self, model_store, pattern_store, analyzer):
        """Test sans patterns fiables."""
        use_case = CreateImprovementModelUseCase(
            model_store=model_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(
            name="Test Model",
            description="Description",
        )

        assert result.model_id is not None
        assert result.patterns_included == 0

    def test_execute_with_patterns(self, model_store, pattern_store, analyzer):
        """Test avec patterns fiables."""
        # Créer un pattern fiable
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="test",
            replacement="TEST",
        )
        for _ in range(10):
            pattern.increment_occurrence()
        pattern_store.save(pattern)

        use_case = CreateImprovementModelUseCase(
            model_store=model_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(
            name="Test Model",
            description="Description",
            min_confidence=0.6,
        )

        assert result.patterns_included >= 1


class TestActivateModelUseCase:
    """Tests pour ActivateModelUseCase."""

    def test_activate_existing_model(self, model_store, sample_model):
        """Test d'activation d'un modèle existant."""
        model_store.save(sample_model)

        use_case = ActivateModelUseCase(model_store=model_store)
        result = use_case.execute(sample_model.id)

        assert result is True
        retrieved = model_store.get_by_id(sample_model.id)
        assert retrieved.status == ImprovementStatus.ACTIVE

    def test_activate_nonexistent_model(self, model_store):
        """Test d'activation d'un modèle inexistant."""
        use_case = ActivateModelUseCase(model_store=model_store)

        with pytest.raises(ValueError):
            use_case.execute("nonexistent-id")


class TestApplyImprovementsUseCase:
    """Tests pour ApplyImprovementsUseCase."""

    def test_execute_no_active_model(self, model_store, pattern_store, analyzer):
        """Test sans modèle actif."""
        use_case = ApplyImprovementsUseCase(
            model_store=model_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(text="Test text")

        assert result.improved_text == "Test text"
        assert result.improvements_applied == 0

    def test_execute_with_model(self, model_store, pattern_store, analyzer):
        """Test avec modèle actif."""
        # Créer un pattern fiable
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.VOCABULARY,
            original_pattern="Hello",
            replacement="Bonjour",
        )
        for _ in range(10):
            pattern.increment_occurrence()
        pattern_store.save(pattern)

        # Créer et activer un modèle
        model = ImprovementModel.create(name="Test", description="Test")
        model.add_pattern(pattern.id)
        model.activate()
        model_store.save(model)

        use_case = ApplyImprovementsUseCase(
            model_store=model_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(text="Hello world")

        assert "Bonjour" in result.improved_text


class TestGetPromptEnhancementsUseCase:
    """Tests pour GetPromptEnhancementsUseCase."""

    def test_execute_no_active_models(self, model_store, pattern_store):
        """Test sans modèles actifs."""
        use_case = GetPromptEnhancementsUseCase(
            model_store=model_store,
            pattern_store=pattern_store,
        )

        adjustments = use_case.execute()
        assert adjustments == []

    def test_execute_with_active_model(self, model_store, pattern_store):
        """Test avec modèle actif."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.add_prompt_adjustment("Évite le ton formel")
        model.add_prompt_adjustment("Sois plus concis")
        model.activate()
        model_store.save(model)

        use_case = GetPromptEnhancementsUseCase(
            model_store=model_store,
            pattern_store=pattern_store,
        )

        adjustments = use_case.execute()
        assert len(adjustments) == 2


class TestGetFineTuningStatsUseCase:
    """Tests pour GetFineTuningStatsUseCase."""

    def test_execute_empty(
        self, correction_store, feedback_store, pattern_store, model_store
    ):
        """Test avec données vides."""
        use_case = GetFineTuningStatsUseCase(
            correction_store=correction_store,
            feedback_store=feedback_store,
            pattern_store=pattern_store,
            model_store=model_store,
        )

        stats = use_case.execute()

        assert stats.total_corrections == 0
        assert stats.total_feedbacks == 0
        assert stats.total_patterns == 0
        assert stats.active_models == 0

    def test_execute_with_data(
        self, correction_store, feedback_store, pattern_store, model_store
    ):
        """Test avec données."""
        # Ajouter des données
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="test",
            corrected_text="TEST",
        )
        correction.correction_types = [CorrectionType.STYLE]
        correction_store.save(correction)

        feedback = UserFeedback.create(draft_id="d1", rating=5)
        feedback_store.save(feedback)

        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.STYLE,
            original_pattern="test",
            replacement="TEST",
        )
        pattern_store.save(pattern)

        model = ImprovementModel.create(name="Test", description="Test")
        model.activate()
        model_store.save(model)

        use_case = GetFineTuningStatsUseCase(
            correction_store=correction_store,
            feedback_store=feedback_store,
            pattern_store=pattern_store,
            model_store=model_store,
        )

        stats = use_case.execute()

        assert stats.total_corrections == 1
        assert stats.total_feedbacks == 1
        assert stats.total_patterns == 1
        assert stats.active_models == 1


# =============================================================================
# TESTS API (INTEGRATION)
# =============================================================================


import importlib.util
HAS_FLASK_CORS = importlib.util.find_spec("flask_cors") is not None


@pytest.mark.skipif(not HAS_FLASK_CORS, reason="flask_cors not installed")
class TestFineTuningAPI:
    """Tests d'intégration pour l'API REST."""

    @pytest.fixture
    def client(self, temp_dir, monkeypatch):
        """Client de test Flask."""
        # Importer et patcher les constantes
        import app.infrastructure.fine_tuning_store as store_module

        monkeypatch.setattr(
            store_module, "FINE_TUNING_DIR", temp_dir
        )
        monkeypatch.setattr(
            store_module, "CORRECTIONS_FILE", temp_dir / "corrections.json"
        )
        monkeypatch.setattr(
            store_module, "FEEDBACKS_FILE", temp_dir / "feedbacks.json"
        )
        monkeypatch.setattr(
            store_module, "PATTERNS_FILE", temp_dir / "patterns.json"
        )
        monkeypatch.setattr(
            store_module, "MODELS_FILE", temp_dir / "models.json"
        )
        monkeypatch.setattr(
            store_module, "SESSIONS_FILE", temp_dir / "sessions.json"
        )

        from app.api.app import create_app

        app = create_app({"TESTING": True})
        import app.api.fine_tuning as fine_tuning

        class _DraftHistory:
            def get_by_id_for_account(self, draft_id, account_id):
                if draft_id == "draft-123" and account_id == 1:
                    return object()
                return None

        class _Container:
            def get_draft_history(self):
                return _DraftHistory()

        monkeypatch.setattr(
            fine_tuning, "_resolve_account_id_for_user", lambda: 1
        )
        monkeypatch.setattr(
            fine_tuning, "_get_container", lambda: _Container()
        )
        with app.test_client() as client:
            yield client

    def test_record_correction(self, client):
        """Test POST /api/fine-tuning/corrections."""
        response = client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": "draft-123",
                "original_text": "Hello",
                "corrected_text": "Bonjour",
            },
        )

        assert response.status_code == 201
        data = response.get_json()
        assert "correction_id" in data

    def test_record_correction_missing_field(self, client):
        """Test POST /api/fine-tuning/corrections avec champ manquant."""
        response = client.post(
            "/api/fine-tuning/corrections",
            json={"draft_id": "draft-123"},
        )

        assert response.status_code == 400

    def test_list_corrections(self, client):
        """Test GET /api/fine-tuning/corrections."""
        # Ajouter une correction
        client.post(
            "/api/fine-tuning/corrections",
            json={
                "draft_id": "draft-123",
                "original_text": "Hello",
                "corrected_text": "Bonjour",
            },
        )

        response = client.get("/api/fine-tuning/corrections")

        assert response.status_code == 200
        data = response.get_json()
        assert "corrections" in data
        assert data["total"] >= 1

    def test_record_feedback(self, client):
        """Test POST /api/fine-tuning/feedbacks."""
        response = client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-123", "rating": 5, "comment": "Excellent"},
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["sentiment"] == "positive"

    def test_record_feedback_invalid_rating(self, client):
        """Test POST /api/fine-tuning/feedbacks avec note invalide."""
        response = client.post(
            "/api/fine-tuning/feedbacks",
            json={"draft_id": "draft-123", "rating": 10},
        )

        assert response.status_code == 400

    def test_list_patterns(self, client):
        """Test GET /api/fine-tuning/patterns."""
        response = client.get("/api/fine-tuning/patterns")

        assert response.status_code == 200
        data = response.get_json()
        assert "patterns" in data

    def test_create_model(self, client):
        """Test POST /api/fine-tuning/models."""
        response = client.post(
            "/api/fine-tuning/models",
            json={"name": "Test Model", "description": "Description de test"},
        )

        assert response.status_code == 201
        data = response.get_json()
        assert "model_id" in data

    def test_list_models(self, client):
        """Test GET /api/fine-tuning/models."""
        # Créer un modèle
        client.post(
            "/api/fine-tuning/models",
            json={"name": "Test", "description": "Test"},
        )

        response = client.get("/api/fine-tuning/models")

        assert response.status_code == 200
        data = response.get_json()
        assert "models" in data

    def test_get_stats(self, client):
        """Test GET /api/fine-tuning/stats."""
        response = client.get("/api/fine-tuning/stats")

        assert response.status_code == 200
        data = response.get_json()
        assert "total_corrections" in data
        assert "total_feedbacks" in data
        assert "total_patterns" in data

    def test_apply_improvements(self, client):
        """Test POST /api/fine-tuning/improve."""
        response = client.post(
            "/api/fine-tuning/improve",
            json={"text": "Hello world"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "improved_text" in data

    def test_get_prompt_enhancements(self, client):
        """Test GET /api/fine-tuning/prompt-enhancements."""
        response = client.get("/api/fine-tuning/prompt-enhancements")

        assert response.status_code == 200
        data = response.get_json()
        assert "adjustments" in data


# =============================================================================
# TESTS SUPPLÉMENTAIRES
# =============================================================================


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_text_correction(self, correction_store, pattern_store, analyzer):
        """Test avec texte vide."""
        use_case = RecordCorrectionUseCase(
            correction_store=correction_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(
            draft_id="draft-123",
            original_text="",
            corrected_text="Nouveau texte",
        )

        assert result.correction_id is not None

    def test_identical_texts(self, correction_store, pattern_store, analyzer):
        """Test avec textes identiques."""
        use_case = RecordCorrectionUseCase(
            correction_store=correction_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(
            draft_id="draft-123",
            original_text="Même texte",
            corrected_text="Même texte",
        )

        assert not result.has_significant_changes

    def test_very_long_text(self, correction_store, pattern_store, analyzer):
        """Test avec texte très long."""
        long_text = "x" * 10000
        long_corrected = "y" * 10000

        use_case = RecordCorrectionUseCase(
            correction_store=correction_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(
            draft_id="draft-123",
            original_text=long_text,
            corrected_text=long_corrected,
        )

        assert result.correction_id is not None

    def test_unicode_content(self, correction_store, pattern_store, analyzer):
        """Test avec contenu Unicode."""
        use_case = RecordCorrectionUseCase(
            correction_store=correction_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(
            draft_id="draft-123",
            original_text="Bonjour 你好 مرحبا",
            corrected_text="Hello 你好 مرحبا",
        )

        assert result.correction_id is not None

    def test_special_characters(self, correction_store, pattern_store, analyzer):
        """Test avec caractères spéciaux."""
        use_case = RecordCorrectionUseCase(
            correction_store=correction_store,
            pattern_store=pattern_store,
            analyzer=analyzer,
        )

        result = use_case.execute(
            draft_id="draft-123",
            original_text="Test <script>alert('xss')</script>",
            corrected_text="Test securisé",
        )

        assert result.correction_id is not None
