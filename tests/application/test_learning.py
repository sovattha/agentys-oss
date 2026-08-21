# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les use cases du système d'apprentissage automatique.

pytest tests/application/test_learning.py -v
"""

import pytest
from unittest.mock import Mock

from app.application.learning import (
    AnalyzeFeedbackUseCase,
    ExtractPatternsUseCase,
    ShouldRequireReviewUseCase,
    GenerateAdjustmentUseCase,
    GetLearningStatsUseCase,
    GetActiveAdjustmentsUseCase,
    EnhancePromptUseCase,
    _extract_rating,
    _extract_json_from_response,
)
from app.domain.entities.learning import (
    LearningInsights,
    LearnedPattern,
    PromptAdjustment,
    PatternType,
)
from app.domain.ports.learning_port import (
    LearningFeedbackProviderPort,
    LearningPatternStorePort,
    AdjustmentStorePort,
)
from app.domain.ports.llm_port import LLMPort


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_feedback_store():
    """Mock du feedback store."""
    return Mock(spec=LearningFeedbackProviderPort)


@pytest.fixture
def mock_pattern_store():
    """Mock du pattern store."""
    return Mock(spec=LearningPatternStorePort)


@pytest.fixture
def mock_adjustment_store():
    """Mock du adjustment store."""
    return Mock(spec=AdjustmentStorePort)


@pytest.fixture
def mock_llm():
    """Mock du LLM."""
    return Mock(spec=LLMPort)


@pytest.fixture
def sample_feedback_good():
    """Feedback positif (5 étoiles)."""
    feedback = Mock()
    feedback.rating = 5
    feedback.comment = "Très bon email!"
    feedback.status = "V1"
    return feedback


@pytest.fixture
def sample_feedback_bad():
    """Feedback négatif (1 étoile)."""
    feedback = Mock()
    feedback.rating = 1
    feedback.comment = "Horrible!"
    feedback.status = "V1"
    return feedback


@pytest.fixture
def sample_feedback_neutral():
    """Feedback neutre (3 étoiles)."""
    feedback = Mock()
    feedback.rating = 3
    feedback.comment = "Correct."
    feedback.status = "V1"
    return feedback


@pytest.fixture
def sample_feedback_v2():
    """Feedback pour version V2."""
    feedback = Mock()
    feedback.rating = 5
    feedback.comment = "Excellent!"
    feedback.status = "V2"
    return feedback


@pytest.fixture
def sample_learned_pattern_bad():
    """Pattern BAD de test."""
    return LearnedPattern.create(
        pattern_type=PatternType.BAD,
        trigger="Utilise de l'argot",
        correction="Utilise un langage professionnel",
    )


@pytest.fixture
def sample_learned_pattern_good():
    """Pattern GOOD de test."""
    return LearnedPattern.create(
        pattern_type=PatternType.GOOD,
        trigger="Début avec salutation personnelle",
        correction="",
    )


@pytest.fixture
def sample_adjustment():
    """Ajustement de test."""
    return PromptAdjustment.create(
        section="DRAFTER_SYSTEM_PROMPT",
        adjustment="Évite: l'argot. Utilise un langage professionnel.",
        reason="Pattern détecté 5 fois",
    )


# =============================================================================
# TESTS HELPER FUNCTIONS
# =============================================================================


class TestExtractRating:
    """Tests pour _extract_rating."""

    def test_extract_rating_from_rating_attribute(self):
        """Extrait le rating depuis l'attribut 'rating'."""
        feedback = Mock()
        feedback.rating = 4
        result = _extract_rating(feedback)
        assert result == 4

    def test_extract_rating_from_feedback_rating_attribute(self):
        """Extrait le rating depuis l'attribut 'feedback_rating'."""
        feedback = Mock()
        feedback.rating = None
        feedback.feedback_rating = 3
        result = _extract_rating(feedback)
        assert result == 3

    def test_extract_rating_returns_none_when_missing(self):
        """Retourne None si aucun rating trouvé."""
        feedback = Mock(spec=[])
        result = _extract_rating(feedback)
        assert result is None

    def test_extract_rating_with_zero(self):
        """Gère le rating zéro."""
        feedback = Mock()
        feedback.rating = 0
        result = _extract_rating(feedback)
        assert result == 0

    def test_extract_rating_prefers_rating_over_feedback_rating(self):
        """Préfère 'rating' à 'feedback_rating'."""
        feedback = Mock()
        feedback.rating = 5
        feedback.feedback_rating = 2
        result = _extract_rating(feedback)
        assert result == 5


class TestExtractJsonFromResponse:
    """Tests pour _extract_json_from_response."""

    def test_extract_json_from_plain_json(self):
        """Extrait JSON depuis réponse plain."""
        response = '{"key": "value", "number": 42}'
        result = _extract_json_from_response(response)
        assert result == {"key": "value", "number": 42}

    def test_extract_json_from_markdown_backticks(self):
        """Extrait JSON depuis backticks markdown."""
        response = '```json\n{"key": "value"}\n```'
        result = _extract_json_from_response(response)
        assert result == {"key": "value"}

    def test_extract_json_from_markdown_without_json_tag(self):
        """Extrait JSON depuis backticks sans 'json' tag."""
        response = '```\n{"key": "value"}\n```'
        result = _extract_json_from_response(response)
        assert result == {"key": "value"}

    def test_extract_json_with_whitespace(self):
        """Gère les espaces autour du JSON."""
        response = '   ```json\n  {"key": "value"}  \n```   '
        result = _extract_json_from_response(response)
        assert result == {"key": "value"}

    def test_extract_json_with_invalid_json_returns_none(self):
        """Retourne None pour JSON invalide."""
        response = '{"key": invalid}'
        result = _extract_json_from_response(response)
        assert result is None

    def test_extract_json_with_nested_structure(self):
        """Gère les structures imbriquées."""
        response = '{"data": {"nested": [1, 2, 3]}, "count": 3}'
        result = _extract_json_from_response(response)
        assert result == {"data": {"nested": [1, 2, 3]}, "count": 3}

    def test_extract_json_with_array(self):
        """Extrait un tableau JSON."""
        response = '[{"id": 1}, {"id": 2}]'
        result = _extract_json_from_response(response)
        assert result == [{"id": 1}, {"id": 2}]

    def test_extract_json_empty_object(self):
        """Gère un objet vide."""
        response = '{}'
        result = _extract_json_from_response(response)
        assert result == {}


# =============================================================================
# TESTS ANALYZE FEEDBACK USE CASE
# =============================================================================


class TestAnalyzeFeedbackUseCase:
    """Tests pour AnalyzeFeedbackUseCase."""

    def test_init_stores_feedback_store(self, mock_feedback_store):
        """L'initialisation stocke le feedback store."""
        use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        assert use_case.feedback_store == mock_feedback_store

    def test_execute_returns_empty_insights_when_no_feedbacks(self, mock_feedback_store):
        """Execute retourne des insights vides si pas de feedbacks."""
        mock_feedback_store.get_all.return_value = []
        use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        result = use_case.execute()
        assert isinstance(result, LearningInsights)
        assert result.total_with_feedback == 0
        assert result.good_count == 0

    def test_execute_counts_feedbacks_correctly(
        self,
        mock_feedback_store,
        sample_feedback_good,
        sample_feedback_bad,
        sample_feedback_neutral,
    ):
        """Execute compte correctement les feedbacks par catégorie."""
        feedbacks = [sample_feedback_good, sample_feedback_bad, sample_feedback_neutral]
        mock_feedback_store.get_all.return_value = feedbacks

        use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        result = use_case.execute()

        assert result.total_with_feedback == 3
        assert result.good_count == 1
        assert result.bad_count == 1
        assert result.neutral_count == 1

    def test_execute_handles_rating_4_as_good(self, mock_feedback_store):
        """Execute traite rating 4 comme 'good'."""
        feedback = Mock()
        feedback.rating = 4
        feedback.status = "V1"
        mock_feedback_store.get_all.return_value = [feedback]

        use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        result = use_case.execute()

        assert result.good_count == 1
        assert result.bad_count == 0

    def test_execute_handles_rating_2_as_bad(self, mock_feedback_store):
        """Execute traite rating 2 comme 'bad'."""
        feedback = Mock()
        feedback.rating = 2
        feedback.status = "V1"
        mock_feedback_store.get_all.return_value = [feedback]

        use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        result = use_case.execute()

        assert result.bad_count == 1
        assert result.good_count == 0

    def test_execute_skips_feedbacks_without_rating(self, mock_feedback_store, sample_feedback_good):
        """Execute ignore les feedbacks sans rating."""
        feedback_no_rating = Mock()
        feedback_no_rating.rating = None
        feedback_no_rating.feedback_rating = None

        feedbacks = [sample_feedback_good, feedback_no_rating]
        mock_feedback_store.get_all.return_value = feedbacks

        use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        result = use_case.execute()

        assert result.total_with_feedback == 1
        assert result.good_count == 1

    def test_execute_calculates_v1_good_rate(self, mock_feedback_store):
        """Execute calcule correctement le taux de satisfaction V1."""
        feedback1 = Mock()
        feedback1.rating = 5
        feedback1.status = "V1"

        feedback2 = Mock()
        feedback2.rating = 1
        feedback2.status = "V1"

        mock_feedback_store.get_all.return_value = [feedback1, feedback2]

        use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        result = use_case.execute()

        # 1 good sur 2 = 50%
        assert result.v1_good_rate == 50

    def test_execute_calculates_v2_good_rate(self, mock_feedback_store):
        """Execute calcule correctement le taux de satisfaction V2."""
        feedback1 = Mock()
        feedback1.rating = 5
        feedback1.status = "V2"

        feedback2 = Mock()
        feedback2.rating = 5
        feedback2.status = "V2"

        feedback3 = Mock()
        feedback3.rating = 1
        feedback3.status = "V1"

        mock_feedback_store.get_all.return_value = [feedback1, feedback2, feedback3]

        use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        result = use_case.execute()

        # V2: 2 good sur 2 = 100%
        assert result.v2_good_rate == 100

    def test_execute_with_custom_limit(self, mock_feedback_store):
        """Execute passe la limite au store."""
        mock_feedback_store.get_all.return_value = []
        use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        use_case.execute(limit=500)
        mock_feedback_store.get_all.assert_called_once_with(limit=500)

    def test_execute_handles_feedbacks_without_status(self, mock_feedback_store):
        """Execute gère les feedbacks sans attribut 'status'."""
        feedback = Mock(spec=[])
        feedback.rating = 5
        mock_feedback_store.get_all.return_value = [feedback]

        use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        result = use_case.execute()

        # Ne compte pas dans V1 ou V2, mais compte dans les totaux
        assert result.good_count == 1
        assert result.v1_good_rate == 0
        assert result.v2_good_rate == 0


# =============================================================================
# TESTS EXTRACT PATTERNS USE CASE
# =============================================================================


class TestExtractPatternsUseCase:
    """Tests pour ExtractPatternsUseCase."""

    def test_init_stores_dependencies(
        self, mock_feedback_store, mock_pattern_store, mock_llm
    ):
        """L'initialisation stocke les dépendances."""
        use_case = ExtractPatternsUseCase(mock_feedback_store, mock_pattern_store, mock_llm)
        assert use_case.feedback_store == mock_feedback_store
        assert use_case.pattern_store == mock_pattern_store
        assert use_case.llm == mock_llm

    def test_execute_returns_empty_list_when_no_feedbacks(
        self, mock_feedback_store, mock_pattern_store, mock_llm
    ):
        """Execute retourne liste vide si pas de feedbacks."""
        mock_feedback_store.get_with_comments.return_value = []
        use_case = ExtractPatternsUseCase(mock_feedback_store, mock_pattern_store, mock_llm)
        result = use_case.execute()
        assert result == []

    def test_execute_calls_llm_with_feedbacks(
        self, mock_feedback_store, mock_pattern_store, mock_llm
    ):
        """Execute appelle le LLM avec les feedbacks."""
        feedback = Mock()
        feedback.comment = "Pas assez professionnel"
        feedback.rating = 2
        feedback.draft_final = "Email draft text here"
        mock_feedback_store.get_with_comments.return_value = [feedback]

        mock_llm.complete.return_value = Mock(content='{"good_patterns": [], "bad_patterns": [], "suggestions": []}')
        mock_pattern_store.save_many.return_value = []

        use_case = ExtractPatternsUseCase(mock_feedback_store, mock_pattern_store, mock_llm)
        use_case.execute()

        mock_llm.complete.assert_called_once()
        call_kwargs = mock_llm.complete.call_args[1]
        assert "professionnel" in call_kwargs["user"].lower()

    def test_execute_parses_llm_response_with_good_patterns(
        self, mock_feedback_store, mock_pattern_store, mock_llm
    ):
        """Execute parse les good patterns de la réponse LLM."""
        feedback = Mock()
        feedback.comment = "Bon!"
        feedback.rating = 5
        feedback.draft_final = "Email text"
        mock_feedback_store.get_with_comments.return_value = [feedback]

        response_json = '{"good_patterns": ["Début avec salutation", "Ton professionnel"], "bad_patterns": [], "suggestions": []}'
        mock_llm.complete.return_value = Mock(content=response_json)

        use_case = ExtractPatternsUseCase(mock_feedback_store, mock_pattern_store, mock_llm)
        result = use_case.execute()

        assert len(result) == 2
        assert all(p.pattern_type == PatternType.GOOD for p in result)
        assert result[0].trigger == "Début avec salutation"
        assert result[1].trigger == "Ton professionnel"

    def test_execute_parses_llm_response_with_bad_patterns(
        self, mock_feedback_store, mock_pattern_store, mock_llm
    ):
        """Execute parse les bad patterns avec corrections."""
        feedback = Mock()
        feedback.comment = "Mauvais!"
        feedback.rating = 1
        feedback.draft_final = "Email text"
        mock_feedback_store.get_with_comments.return_value = [feedback]

        response_json = '{"good_patterns": [], "bad_patterns": ["Trop formel"], "suggestions": ["Sois plus naturel"]}'
        mock_llm.complete.return_value = Mock(content=response_json)

        use_case = ExtractPatternsUseCase(mock_feedback_store, mock_pattern_store, mock_llm)
        result = use_case.execute()

        assert len(result) == 1
        assert result[0].pattern_type == PatternType.BAD
        assert result[0].trigger == "Trop formel"
        assert result[0].correction == "Sois plus naturel"

    def test_execute_saves_patterns_to_store(
        self, mock_feedback_store, mock_pattern_store, mock_llm
    ):
        """Execute sauvegarde les patterns dans le store."""
        feedback = Mock()
        feedback.comment = "Bon!"
        feedback.rating = 5
        feedback.draft_final = "Email text"
        mock_feedback_store.get_with_comments.return_value = [feedback]

        response_json = '{"good_patterns": ["Pattern 1"], "bad_patterns": [], "suggestions": []}'
        mock_llm.complete.return_value = Mock(content=response_json)

        use_case = ExtractPatternsUseCase(mock_feedback_store, mock_pattern_store, mock_llm)
        use_case.execute()

        mock_pattern_store.save_many.assert_called_once()

    def test_execute_handles_llm_exception(
        self, mock_feedback_store, mock_pattern_store, mock_llm
    ):
        """Execute retourne liste vide si le LLM échoue."""
        feedback = Mock()
        feedback.comment = "Bon!"
        feedback.rating = 5
        feedback.draft_final = "Email text"
        mock_feedback_store.get_with_comments.return_value = [feedback]

        mock_llm.complete.side_effect = RuntimeError("LLM error")

        use_case = ExtractPatternsUseCase(mock_feedback_store, mock_pattern_store, mock_llm)
        result = use_case.execute()

        assert result == []

    def test_execute_handles_invalid_json_response(
        self, mock_feedback_store, mock_pattern_store, mock_llm
    ):
        """Execute gère une réponse JSON invalide."""
        feedback = Mock()
        feedback.comment = "Bon!"
        feedback.rating = 5
        feedback.draft_final = "Email text"
        mock_feedback_store.get_with_comments.return_value = [feedback]

        mock_llm.complete.return_value = Mock(content='Not valid JSON')

        use_case = ExtractPatternsUseCase(mock_feedback_store, mock_pattern_store, mock_llm)
        result = use_case.execute()

        assert result == []

    def test_execute_limits_feedbacks_to_20(
        self, mock_feedback_store, mock_pattern_store, mock_llm
    ):
        """Execute limite les feedbacks à 20 pour l'analyse."""
        feedbacks = []
        for _ in range(30):
            f = Mock()
            f.comment = "test"
            f.rating = 5
            f.draft_final = "Email text"
            feedbacks.append(f)
        mock_feedback_store.get_with_comments.return_value = feedbacks

        mock_llm.complete.return_value = Mock(content='{"good_patterns": [], "bad_patterns": [], "suggestions": []}')
        mock_pattern_store.save_many.return_value = []

        use_case = ExtractPatternsUseCase(mock_feedback_store, mock_pattern_store, mock_llm)
        use_case.execute()

        # Vérifier que seulement 20 feedbacks sont utilisés
        call_kwargs = mock_llm.complete.call_args[1]
        feedback_text = call_kwargs["user"]
        # Devrait contenir environ 20 feedbacks
        assert feedback_text.count("Rating:") <= 20


# =============================================================================
# TESTS SHOULD REQUIRE REVIEW USE CASE
# =============================================================================


class TestShouldRequireReviewUseCase:
    """Tests pour ShouldRequireReviewUseCase."""

    def test_init_with_default_confidence_threshold(self, mock_feedback_store):
        """L'initialisation utilise le seuil par défaut."""
        use_case = ShouldRequireReviewUseCase(mock_feedback_store)
        assert use_case.confidence_threshold == 70

    def test_init_with_custom_confidence_threshold(self, mock_feedback_store):
        """L'initialisation accepte un seuil personnalisé."""
        use_case = ShouldRequireReviewUseCase(mock_feedback_store, confidence_threshold=80)
        assert use_case.confidence_threshold == 80

    def test_init_with_default_sensitive_words(self, mock_feedback_store):
        """L'initialisation utilise les mots sensibles par défaut."""
        use_case = ShouldRequireReviewUseCase(mock_feedback_store)
        assert "contrat" in use_case.sensitive_words
        assert "juridique" in use_case.sensitive_words

    def test_init_with_custom_sensitive_words(self, mock_feedback_store):
        """L'initialisation accepte des mots sensibles personnalisés."""
        custom_words = ["secret", "confidentiel"]
        use_case = ShouldRequireReviewUseCase(
            mock_feedback_store, sensitive_words=custom_words
        )
        assert use_case.sensitive_words == custom_words

    def test_execute_requires_review_for_high_priority(self, mock_feedback_store):
        """Execute demande une review si priorité >= 90."""
        mock_feedback_store.get_satisfaction_rate.return_value = 100
        use_case = ShouldRequireReviewUseCase(mock_feedback_store)

        result = use_case.execute("Normal content", priority_score=90)

        assert result.needs_review is True
        assert "priorité" in result.reasons[0].lower()

    def test_execute_requires_review_for_sensitive_content(self, mock_feedback_store):
        """Execute demande une review si contenu sensible détecté."""
        mock_feedback_store.get_satisfaction_rate.return_value = 100
        use_case = ShouldRequireReviewUseCase(mock_feedback_store)

        result = use_case.execute("Email avec contrat et juridique", priority_score=50)

        assert result.needs_review is True
        assert any("contrat" in r.lower() for r in result.reasons)

    def test_execute_detects_sensitive_words_case_insensitive(self, mock_feedback_store):
        """Execute détecte les mots sensibles indépendamment de la casse."""
        mock_feedback_store.get_satisfaction_rate.return_value = 100
        use_case = ShouldRequireReviewUseCase(mock_feedback_store)

        result = use_case.execute("Email avec CONTRAT urgent", priority_score=50)

        assert result.needs_review is True

    def test_execute_requires_review_for_low_confidence(self, mock_feedback_store):
        """Execute demande une review si confiance faible."""
        mock_feedback_store.get_satisfaction_rate.return_value = 50  # < 70
        use_case = ShouldRequireReviewUseCase(mock_feedback_store, confidence_threshold=70)

        result = use_case.execute("Normal content", priority_score=50)

        assert result.needs_review is True
        assert "confiance" in result.reasons[0].lower()

    def test_execute_no_review_for_safe_content(self, mock_feedback_store):
        """Execute ne demande pas de review pour contenu sûr."""
        mock_feedback_store.get_satisfaction_rate.return_value = 90
        use_case = ShouldRequireReviewUseCase(mock_feedback_store, confidence_threshold=70)

        result = use_case.execute("Safe content", priority_score=30)

        assert result.needs_review is False
        assert len(result.reasons) == 0

    def test_execute_multiple_reasons(self, mock_feedback_store):
        """Execute accumule les raisons."""
        mock_feedback_store.get_satisfaction_rate.return_value = 50
        use_case = ShouldRequireReviewUseCase(mock_feedback_store)

        result = use_case.execute("Email avec contrat", priority_score=95)

        assert result.needs_review is True
        assert len(result.reasons) >= 2

    def test_execute_only_one_sensitive_word_reason(self, mock_feedback_store):
        """Execute ajoute qu'une seule raison pour mots sensibles."""
        mock_feedback_store.get_satisfaction_rate.return_value = 100
        use_case = ShouldRequireReviewUseCase(mock_feedback_store)

        result = use_case.execute("Email avec contrat et juridique et urgent", priority_score=50)

        sensitive_reasons = [r for r in result.reasons if "sensible" in r.lower()]
        assert len(sensitive_reasons) == 1


# =============================================================================
# TESTS GENERATE ADJUSTMENT USE CASE
# =============================================================================


class TestGenerateAdjustmentUseCase:
    """Tests pour GenerateAdjustmentUseCase."""

    def test_init_stores_dependencies(self, mock_pattern_store, mock_adjustment_store):
        """L'initialisation stocke les dépendances."""
        use_case = GenerateAdjustmentUseCase(mock_pattern_store, mock_adjustment_store)
        assert use_case.pattern_store == mock_pattern_store
        assert use_case.adjustment_store == mock_adjustment_store

    def test_execute_returns_none_when_no_bad_patterns(
        self, mock_pattern_store, mock_adjustment_store
    ):
        """Execute retourne None s'il n'y a pas de bad patterns."""
        mock_pattern_store.get_by_type.return_value = []
        use_case = GenerateAdjustmentUseCase(mock_pattern_store, mock_adjustment_store)
        result = use_case.execute()
        assert result is None

    def test_execute_returns_none_when_patterns_below_frequency_threshold(
        self, mock_pattern_store, mock_adjustment_store, sample_learned_pattern_bad
    ):
        """Execute retourne None si patterns sous MIN_PATTERN_FREQUENCY."""
        sample_learned_pattern_bad.frequency = 2  # < MIN_PATTERN_FREQUENCY (3)
        mock_pattern_store.get_by_type.return_value = [sample_learned_pattern_bad]

        use_case = GenerateAdjustmentUseCase(mock_pattern_store, mock_adjustment_store)
        result = use_case.execute()

        assert result is None

    def test_execute_generates_adjustment_for_reliable_pattern(
        self, mock_pattern_store, mock_adjustment_store, sample_learned_pattern_bad
    ):
        """Execute génère un ajustement pour un pattern fiable."""
        sample_learned_pattern_bad.frequency = 5
        mock_pattern_store.get_by_type.return_value = [sample_learned_pattern_bad]

        use_case = GenerateAdjustmentUseCase(mock_pattern_store, mock_adjustment_store)
        result = use_case.execute()

        assert result is not None
        assert isinstance(result, PromptAdjustment)

    def test_execute_selects_most_frequent_pattern(
        self, mock_pattern_store, mock_adjustment_store
    ):
        """Execute sélectionne le pattern le plus fréquent."""
        pattern1 = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Pattern 1",
            correction="Fix 1"
        )
        pattern1.frequency = 3

        pattern2 = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Pattern 2",
            correction="Fix 2"
        )
        pattern2.frequency = 7

        mock_pattern_store.get_by_type.return_value = [pattern1, pattern2]

        use_case = GenerateAdjustmentUseCase(mock_pattern_store, mock_adjustment_store)
        result = use_case.execute()

        assert "Pattern 2" in result.adjustment

    def test_execute_saves_adjustment_to_store(
        self, mock_pattern_store, mock_adjustment_store, sample_learned_pattern_bad
    ):
        """Execute sauvegarde l'ajustement dans le store."""
        sample_learned_pattern_bad.frequency = 5
        mock_pattern_store.get_by_type.return_value = [sample_learned_pattern_bad]

        use_case = GenerateAdjustmentUseCase(mock_pattern_store, mock_adjustment_store)
        use_case.execute()

        mock_adjustment_store.save.assert_called_once()

    def test_execute_adjustment_contains_pattern_info(
        self, mock_pattern_store, mock_adjustment_store, sample_learned_pattern_bad
    ):
        """Execute crée un ajustement contenant les infos du pattern."""
        sample_learned_pattern_bad.frequency = 5
        mock_pattern_store.get_by_type.return_value = [sample_learned_pattern_bad]

        use_case = GenerateAdjustmentUseCase(mock_pattern_store, mock_adjustment_store)
        result = use_case.execute()

        assert sample_learned_pattern_bad.trigger in result.adjustment
        assert sample_learned_pattern_bad.correction in result.adjustment
        assert str(sample_learned_pattern_bad.frequency) in result.reason

    def test_execute_filters_patterns_below_min_frequency(
        self, mock_pattern_store, mock_adjustment_store
    ):
        """Execute filtre les patterns sous la fréquence minimale."""
        pattern1 = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Pattern 1",
            correction="Fix 1"
        )
        pattern1.frequency = 2  # Rejeté

        pattern2 = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Pattern 2",
            correction="Fix 2"
        )
        pattern2.frequency = 3  # Accepté

        mock_pattern_store.get_by_type.return_value = [pattern1, pattern2]

        use_case = GenerateAdjustmentUseCase(mock_pattern_store, mock_adjustment_store)
        result = use_case.execute()

        assert result is not None
        assert "Pattern 2" in result.adjustment


# =============================================================================
# TESTS GET LEARNING STATS USE CASE
# =============================================================================


class TestGetLearningStatsUseCase:
    """Tests pour GetLearningStatsUseCase."""

    def test_init_stores_dependencies(
        self, mock_pattern_store, mock_adjustment_store, mock_feedback_store
    ):
        """L'initialisation stocke les dépendances."""
        use_case = GetLearningStatsUseCase(
            mock_pattern_store, mock_adjustment_store, mock_feedback_store
        )
        assert use_case.pattern_store == mock_pattern_store
        assert use_case.adjustment_store == mock_adjustment_store
        assert use_case.feedback_store == mock_feedback_store

    def test_execute_returns_dict(
        self, mock_pattern_store, mock_adjustment_store, mock_feedback_store
    ):
        """Execute retourne un dictionnaire."""
        mock_pattern_store.count.return_value = 5
        mock_pattern_store.count_by_type.return_value = {"good": 3, "bad": 2}
        mock_adjustment_store.count_active.return_value = 1
        mock_feedback_store.get_all.return_value = []

        use_case = GetLearningStatsUseCase(
            mock_pattern_store, mock_adjustment_store, mock_feedback_store
        )
        result = use_case.execute()

        assert isinstance(result, dict)

    def test_execute_includes_pattern_counts(
        self, mock_pattern_store, mock_adjustment_store, mock_feedback_store
    ):
        """Execute inclut les comptages de patterns."""
        mock_pattern_store.count.return_value = 5
        mock_pattern_store.count_by_type.return_value = {"good": 3, "bad": 2}
        mock_adjustment_store.count_active.return_value = 0
        mock_feedback_store.get_all.return_value = []

        use_case = GetLearningStatsUseCase(
            mock_pattern_store, mock_adjustment_store, mock_feedback_store
        )
        result = use_case.execute()

        assert result["patterns_count"] == 5
        assert result["good_patterns"] == 3
        assert result["bad_patterns"] == 2

    def test_execute_includes_adjustment_counts(
        self, mock_pattern_store, mock_adjustment_store, mock_feedback_store
    ):
        """Execute inclut les comptages d'ajustements."""
        mock_pattern_store.count.return_value = 0
        mock_pattern_store.count_by_type.return_value = {}
        mock_adjustment_store.count_active.return_value = 2
        mock_feedback_store.get_all.return_value = []

        use_case = GetLearningStatsUseCase(
            mock_pattern_store, mock_adjustment_store, mock_feedback_store
        )
        result = use_case.execute()

        assert result["active_adjustments"] == 2

    def test_execute_includes_feedback_insights(
        self, mock_pattern_store, mock_adjustment_store, mock_feedback_store
    ):
        """Execute inclut les insights des feedbacks."""
        feedback = Mock()
        feedback.rating = 5
        feedback.status = "V1"
        mock_feedback_store.get_all.return_value = [feedback]

        mock_pattern_store.count.return_value = 0
        mock_pattern_store.count_by_type.return_value = {}
        mock_adjustment_store.count_active.return_value = 0

        use_case = GetLearningStatsUseCase(
            mock_pattern_store, mock_adjustment_store, mock_feedback_store
        )
        result = use_case.execute()

        assert result["total_with_feedback"] == 1
        assert result["good_count"] == 1

    def test_execute_includes_confidence_threshold(
        self, mock_pattern_store, mock_adjustment_store, mock_feedback_store
    ):
        """Execute inclut le seuil de confiance."""
        mock_pattern_store.count.return_value = 0
        mock_pattern_store.count_by_type.return_value = {}
        mock_adjustment_store.count_active.return_value = 0
        mock_feedback_store.get_all.return_value = []

        use_case = GetLearningStatsUseCase(
            mock_pattern_store,
            mock_adjustment_store,
            mock_feedback_store,
            confidence_threshold=75,
        )
        result = use_case.execute()

        assert result["confidence_threshold"] == 75


# =============================================================================
# TESTS GET ACTIVE ADJUSTMENTS USE CASE
# =============================================================================


class TestGetActiveAdjustmentsUseCase:
    """Tests pour GetActiveAdjustmentsUseCase."""

    def test_init_stores_adjustment_store(self, mock_adjustment_store):
        """L'initialisation stocke l'adjustment store."""
        use_case = GetActiveAdjustmentsUseCase(mock_adjustment_store)
        assert use_case.adjustment_store == mock_adjustment_store

    def test_execute_returns_empty_list_when_no_adjustments(self, mock_adjustment_store):
        """Execute retourne une liste vide si pas d'ajustements."""
        mock_adjustment_store.get_active.return_value = []
        use_case = GetActiveAdjustmentsUseCase(mock_adjustment_store)
        result = use_case.execute()
        assert result == []

    def test_execute_returns_adjustment_texts(self, mock_adjustment_store, sample_adjustment):
        """Execute retourne les textes des ajustements."""
        mock_adjustment_store.get_active.return_value = [sample_adjustment]
        use_case = GetActiveAdjustmentsUseCase(mock_adjustment_store)
        result = use_case.execute()

        assert len(result) == 1
        assert result[0] == sample_adjustment.adjustment

    def test_execute_returns_multiple_adjustment_texts(self, mock_adjustment_store):
        """Execute retourne les textes de plusieurs ajustements."""
        adj1 = PromptAdjustment.create(
            section="DRAFTER",
            adjustment="Ajustement 1",
            reason="Raison 1"
        )
        adj2 = PromptAdjustment.create(
            section="DRAFTER",
            adjustment="Ajustement 2",
            reason="Raison 2"
        )
        mock_adjustment_store.get_active.return_value = [adj1, adj2]

        use_case = GetActiveAdjustmentsUseCase(mock_adjustment_store)
        result = use_case.execute()

        assert len(result) == 2
        assert "Ajustement 1" in result
        assert "Ajustement 2" in result


# =============================================================================
# TESTS ENHANCE PROMPT USE CASE
# =============================================================================


class TestEnhancePromptUseCase:
    """Tests pour EnhancePromptUseCase."""

    def test_init_stores_adjustment_store(self, mock_adjustment_store):
        """L'initialisation stocke l'adjustment store."""
        use_case = EnhancePromptUseCase(mock_adjustment_store)
        assert use_case.adjustment_store == mock_adjustment_store

    def test_execute_returns_base_prompt_when_no_adjustments(
        self, mock_adjustment_store
    ):
        """Execute retourne le prompt de base si pas d'ajustements."""
        mock_adjustment_store.get_active.return_value = []
        use_case = EnhancePromptUseCase(mock_adjustment_store)

        base = "Base prompt"
        result = use_case.execute(base)

        assert result == base

    def test_execute_appends_adjustments_to_prompt(
        self, mock_adjustment_store, sample_adjustment
    ):
        """Execute ajoute les ajustements au prompt."""
        mock_adjustment_store.get_active.return_value = [sample_adjustment]
        use_case = EnhancePromptUseCase(mock_adjustment_store)

        base = "Base prompt"
        result = use_case.execute(base)

        assert base in result
        assert sample_adjustment.adjustment in result

    def test_execute_includes_learned_rules_section(self, mock_adjustment_store, sample_adjustment):
        """Execute inclut la section 'Règles apprises'."""
        mock_adjustment_store.get_active.return_value = [sample_adjustment]
        use_case = EnhancePromptUseCase(mock_adjustment_store)

        result = use_case.execute("Base")

        assert "Règles apprises" in result

    def test_execute_formats_multiple_adjustments(self, mock_adjustment_store):
        """Execute formate plusieurs ajustements correctement."""
        adj1 = PromptAdjustment.create(
            section="DRAFTER",
            adjustment="Ajustement 1",
            reason="Raison 1"
        )
        adj2 = PromptAdjustment.create(
            section="DRAFTER",
            adjustment="Ajustement 2",
            reason="Raison 2"
        )
        mock_adjustment_store.get_active.return_value = [adj1, adj2]

        use_case = EnhancePromptUseCase(mock_adjustment_store)
        result = use_case.execute("Base")

        assert "- Ajustement 1" in result
        assert "- Ajustement 2" in result

    def test_execute_preserves_base_prompt_structure(self, mock_adjustment_store, sample_adjustment):
        """Execute préserve la structure du prompt de base."""
        mock_adjustment_store.get_active.return_value = [sample_adjustment]
        use_case = EnhancePromptUseCase(mock_adjustment_store)

        base = "Line 1\nLine 2\nLine 3"
        result = use_case.execute(base)

        assert result.startswith(base)

    def test_execute_with_empty_adjustment_text(self, mock_adjustment_store):
        """Execute gère les ajustements avec texte vide."""
        adj = PromptAdjustment.create(
            section="DRAFTER",
            adjustment="",
            reason="Test"
        )
        mock_adjustment_store.get_active.return_value = [adj]

        use_case = EnhancePromptUseCase(mock_adjustment_store)
        result = use_case.execute("Base")

        assert result != "Base"  # Au moins la section a été ajoutée


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestAnalyzeFeedbackAndGenerateStats:
    """Tests d'intégration pour AnalyzeFeedback et GetLearningStats."""

    def test_analyze_feedback_and_get_stats_integration(
        self,
        mock_pattern_store,
        mock_adjustment_store,
        mock_feedback_store,
        sample_feedback_good,
        sample_feedback_bad,
    ):
        """AnalyzeFeedback + GetLearningStats produisent des stats cohérentes."""
        mock_feedback_store.get_all.return_value = [sample_feedback_good, sample_feedback_bad]
        mock_pattern_store.count.return_value = 5
        mock_pattern_store.count_by_type.return_value = {"good": 2, "bad": 3}
        mock_adjustment_store.count_active.return_value = 1

        # Analyser les feedbacks
        analyze_use_case = AnalyzeFeedbackUseCase(mock_feedback_store)
        insights = analyze_use_case.execute()

        # Obtenir les stats
        stats_use_case = GetLearningStatsUseCase(
            mock_pattern_store, mock_adjustment_store, mock_feedback_store
        )
        stats = stats_use_case.execute()

        # Les stats doivent contenir les insights
        assert stats["total_with_feedback"] == insights.total_with_feedback
        assert stats["good_count"] == insights.good_count
        assert stats["bad_count"] == insights.bad_count


class TestExtractPatternAndGenerateAdjustment:
    """Tests d'intégration pour ExtractPatterns et GenerateAdjustment."""

    def test_extract_patterns_then_generate_adjustment(
        self, mock_feedback_store, mock_pattern_store, mock_adjustment_store, mock_llm
    ):
        """Extraction de patterns suivie de génération d'ajustement."""
        feedback = Mock()
        feedback.comment = "Mauvais ton"
        feedback.rating = 1
        feedback.draft_final = "Email text"
        mock_feedback_store.get_with_comments.return_value = [feedback]

        # Étape 1: Extraire patterns
        response_json = '{"good_patterns": [], "bad_patterns": ["Ton trop formel"], "suggestions": ["Sois naturel"]}'
        mock_llm.complete.return_value = Mock(content=response_json)

        extract_use_case = ExtractPatternsUseCase(
            mock_feedback_store, mock_pattern_store, mock_llm
        )
        patterns = extract_use_case.execute()

        # Étape 2: Générer ajustement
        bad_pattern = patterns[0]
        bad_pattern.frequency = 3

        mock_pattern_store.get_by_type.return_value = [bad_pattern]

        generate_use_case = GenerateAdjustmentUseCase(
            mock_pattern_store, mock_adjustment_store
        )
        adjustment = generate_use_case.execute()

        assert adjustment is not None
        assert bad_pattern.trigger in adjustment.adjustment
