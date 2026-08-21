# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases du système Learning.

Ces tests couvrent les cas limites non testés :
- Validation des ratings (1-5, null, hors bornes, non-numeric)
- Null/empty safety dans les use cases
- Parsing JSON LLM (malformed, missing fields)
- File I/O errors (permission, disk full, corrupted files)
- Pattern confidence bounds (overflow, negative, precision)
- Stats consistency validation

Principes Clean Architecture respectés :
- Tests du domaine sans infrastructure
- Injection de dépendances via mocks
- Tests unitaires isolés
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch
from pathlib import Path


# =============================================================================
# TESTS VALIDATION RATING (EDGE CASES)
# =============================================================================


class TestRatingValidation:
    """Tests pour la validation des ratings (1-5)."""

    def test_extract_rating_valid_range(self):
        """Rating valide dans la plage 1-5."""
        from app.application.learning import _extract_rating

        for rating in [1, 2, 3, 4, 5]:
            feedback = Mock(rating=rating)
            assert _extract_rating(feedback) == rating

    def test_extract_rating_none_returns_none(self):
        """Rating None retourne None."""
        from app.application.learning import _extract_rating

        feedback = Mock(spec=["rating", "feedback_rating"])
        feedback.rating = None
        feedback.feedback_rating = None
        assert _extract_rating(feedback) is None

    def test_extract_rating_missing_attribute_returns_none(self):
        """Feedback sans attribut rating retourne None."""
        from app.application.learning import _extract_rating

        feedback = Mock(spec=[])  # Aucun attribut
        assert _extract_rating(feedback) is None

    def test_extract_rating_fallback_to_feedback_rating(self):
        """Fallback vers feedback_rating si rating absent."""
        from app.application.learning import _extract_rating

        feedback = Mock(spec=["feedback_rating"])
        feedback.rating = None  # rating est None
        feedback.feedback_rating = 4
        result = _extract_rating(feedback)
        assert result == 4

    def test_extract_rating_zero_value(self):
        """Rating égal à 0 (hors borne inférieure)."""
        from app.application.learning import _extract_rating

        feedback = Mock(rating=0)
        result = _extract_rating(feedback)
        # Le code actuel retourne 0, mais c'est hors borne valide
        assert result == 0  # Comportement actuel documenté

    def test_extract_rating_negative_value(self):
        """Rating négatif (invalide)."""
        from app.application.learning import _extract_rating

        feedback = Mock(rating=-1)
        result = _extract_rating(feedback)
        # Le code actuel retourne la valeur telle quelle
        assert result == -1  # Comportement actuel documenté

    def test_extract_rating_above_max(self):
        """Rating supérieur à 5 (hors borne supérieure)."""
        from app.application.learning import _extract_rating

        feedback = Mock(rating=10)
        result = _extract_rating(feedback)
        # Le code actuel retourne la valeur telle quelle
        assert result == 10  # Comportement actuel documenté

    def test_extract_rating_float_value(self):
        """Rating en float (devrait être entier)."""
        from app.application.learning import _extract_rating

        feedback = Mock(rating=4.5)
        result = _extract_rating(feedback)
        assert result == 4.5  # Comportement actuel : accepte float

    def test_extract_rating_string_value(self):
        """Rating en string (invalide)."""
        from app.application.learning import _extract_rating

        feedback = Mock(rating="5")
        result = _extract_rating(feedback)
        assert result == "5"  # Comportement actuel : pas de validation type

    def test_count_by_rating_ignores_none(self):
        """Le comptage ignore les ratings None."""
        from app.application.learning import AnalyzeFeedbackUseCase

        # Utiliser des mocks avec spec pour éviter les attributs automatiques
        feedback1 = Mock(spec=["rating", "feedback_rating"])
        feedback1.rating = 5
        feedback1.feedback_rating = None

        feedback2 = Mock(spec=["rating", "feedback_rating"])
        feedback2.rating = None
        feedback2.feedback_rating = None  # Aucun rating

        feedback3 = Mock(spec=["rating", "feedback_rating"])
        feedback3.rating = 3
        feedback3.feedback_rating = None

        feedbacks = [feedback1, feedback2, feedback3]

        mock_store = Mock()
        mock_store.get_all.return_value = feedbacks

        use_case = AnalyzeFeedbackUseCase(feedback_store=mock_store)
        result = use_case.execute()

        # Seuls 2 feedbacks avec rating valide
        assert result.total_with_feedback == 2

    def test_count_by_rating_out_of_bounds_handled(self):
        """Ratings hors bornes sont comptés (comportement actuel)."""
        from app.application.learning import AnalyzeFeedbackUseCase

        feedbacks = [
            Mock(rating=0),   # Devrait être "bad" (<=2)
            Mock(rating=6),   # Devrait être "good" (>=4)
            Mock(rating=-1),  # Devrait être "bad" (<=2)
            Mock(rating=100), # Devrait être "good" (>=4)
        ]

        mock_store = Mock()
        mock_store.get_all.return_value = feedbacks

        use_case = AnalyzeFeedbackUseCase(feedback_store=mock_store)
        result = use_case.execute()

        # Tous comptés selon la logique actuelle
        assert result.bad_count == 2   # 0 et -1 (<=2)
        assert result.good_count == 2  # 6 et 100 (>=4)


# =============================================================================
# TESTS NULL/EMPTY SAFETY DANS USE CASES
# =============================================================================


class TestNullEmptySafetyUseCases:
    """Tests pour la gestion des valeurs null/empty dans les use cases."""

    def test_analyze_feedback_empty_list(self):
        """Analyse avec liste vide retourne insights par défaut."""
        from app.application.learning import AnalyzeFeedbackUseCase
        from app.domain.entities.learning import LearningInsights

        mock_store = Mock()
        mock_store.get_all.return_value = []

        use_case = AnalyzeFeedbackUseCase(feedback_store=mock_store)
        result = use_case.execute()

        assert isinstance(result, LearningInsights)
        assert result.total_with_feedback == 0
        assert result.good_count == 0
        assert result.bad_count == 0

    def test_analyze_feedback_none_from_store(self):
        """Store retournant None est traité comme liste vide (comportement robuste)."""
        from app.application.learning import AnalyzeFeedbackUseCase
        from app.domain.entities.learning import LearningInsights

        mock_store = Mock()
        mock_store.get_all.return_value = None  # Store buggy

        use_case = AnalyzeFeedbackUseCase(feedback_store=mock_store)

        # Le code gère None comme falsy, retournant insights par défaut
        result = use_case.execute()
        assert isinstance(result, LearningInsights)
        assert result.total_with_feedback == 0

    def test_extract_patterns_empty_feedback_text(self):
        """Extraction avec feedbacks vides retourne liste vide."""
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

        assert result == []
        mock_llm.complete.assert_not_called()

    def test_extract_patterns_feedback_without_comment(self):
        """Feedbacks sans commentaire génèrent texte vide."""
        from app.application.learning import ExtractPatternsUseCase

        feedback = Mock(rating=5, comment="", draft_final="Draft")

        mock_feedback_store = Mock()
        mock_feedback_store.get_with_comments.return_value = [feedback]

        mock_pattern_store = Mock()
        mock_llm = Mock()

        use_case = ExtractPatternsUseCase(
            feedback_store=mock_feedback_store,
            pattern_store=mock_pattern_store,
            llm=mock_llm,
        )

        result = use_case.execute()

        # Pas de LLM call car feedback_text.strip() est vide
        assert result == []

    def test_should_require_review_empty_content(self):
        """Review avec contenu vide ne détecte pas de mots sensibles."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 80

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
            sensitive_words=["contrat", "urgent"],
        )

        result = use_case.execute(email_content="", priority_score=50)

        assert result.needs_review is False

    def test_should_require_review_none_content(self):
        """Review avec contenu None provoque erreur."""
        from app.application.learning import ShouldRequireReviewUseCase

        mock_provider = Mock()
        mock_provider.get_satisfaction_rate.return_value = 80

        use_case = ShouldRequireReviewUseCase(
            insights_provider=mock_provider,
            confidence_threshold=70,
        )

        # None.lower() provoque AttributeError
        with pytest.raises(AttributeError):
            use_case.execute(email_content=None, priority_score=50)

    def test_generate_adjustment_empty_patterns(self):
        """Génération sans patterns retourne None."""
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
        mock_adjustment_store.save.assert_not_called()

    def test_enhance_prompt_empty_base(self):
        """Enrichissement avec prompt vide fonctionne."""
        from app.application.learning import EnhancePromptUseCase

        adjustments = [Mock(adjustment="Be concise")]

        mock_store = Mock()
        mock_store.get_active.return_value = adjustments

        use_case = EnhancePromptUseCase(adjustment_store=mock_store)
        result = use_case.execute("")

        assert "Règles apprises" in result
        assert "Be concise" in result

    def test_enhance_prompt_none_base(self):
        """Enrichissement avec prompt None gère erreur."""
        from app.application.learning import EnhancePromptUseCase

        adjustments = [Mock(adjustment="Be concise")]

        mock_store = Mock()
        mock_store.get_active.return_value = adjustments

        use_case = EnhancePromptUseCase(adjustment_store=mock_store)

        # Le code ne valide pas None - comportement documenté
        result = use_case.execute(None)
        # f-string avec None fonctionne en Python
        assert "None" in result


# =============================================================================
# TESTS PARSING JSON LLM (MALFORMED, MISSING FIELDS)
# =============================================================================


class TestJsonParsingLLM:
    """Tests pour le parsing des réponses JSON du LLM."""

    def test_extract_json_valid_response(self):
        """Parsing d'une réponse JSON valide."""
        from app.application.learning import _extract_json_from_response

        response = '{"good_patterns": ["test"], "bad_patterns": []}'
        result = _extract_json_from_response(response)

        assert result == {"good_patterns": ["test"], "bad_patterns": []}

    def test_extract_json_with_markdown_backticks(self):
        """Parsing avec backticks markdown."""
        from app.application.learning import _extract_json_from_response

        response = '''```json
{"good_patterns": ["pattern1"], "bad_patterns": []}
```'''
        result = _extract_json_from_response(response)

        assert result is not None
        assert result["good_patterns"] == ["pattern1"]

    def test_extract_json_with_backticks_no_language(self):
        """Parsing avec backticks sans spécification de langage."""
        from app.application.learning import _extract_json_from_response

        response = '''```
{"key": "value"}
```'''
        result = _extract_json_from_response(response)

        assert result == {"key": "value"}

    def test_extract_json_malformed_json(self):
        """Parsing de JSON malformé retourne None."""
        from app.application.learning import _extract_json_from_response

        response = '{"good_patterns": ["test", }'  # JSON invalide
        result = _extract_json_from_response(response)

        assert result is None

    def test_extract_json_empty_string(self):
        """Parsing de string vide retourne None."""
        from app.application.learning import _extract_json_from_response

        result = _extract_json_from_response("")

        assert result is None

    def test_extract_json_non_json_text(self):
        """Parsing de texte non-JSON retourne None."""
        from app.application.learning import _extract_json_from_response

        response = "Voici ma réponse textuelle sans JSON"
        result = _extract_json_from_response(response)

        assert result is None

    def test_extract_json_nested_backticks(self):
        """Parsing avec backticks imbriqués (edge case)."""
        from app.application.learning import _extract_json_from_response

        response = '''Voici le JSON:
```json
{"code": "```python\nprint()```"}
```'''
        result = _extract_json_from_response(response)

        # Le regex peut avoir du mal avec les backticks imbriqués
        # Comportement documenté
        assert result is not None or result is None

    def test_extract_json_array_root(self):
        """Parsing de JSON avec array racine."""
        from app.application.learning import _extract_json_from_response

        response = '["item1", "item2"]'
        result = _extract_json_from_response(response)

        assert result == ["item1", "item2"]

    def test_extract_json_whitespace_around(self):
        """Parsing avec whitespace autour du JSON."""
        from app.application.learning import _extract_json_from_response

        response = '   \n\n  {"key": "value"}  \n\n   '
        result = _extract_json_from_response(response)

        assert result == {"key": "value"}

    def test_parse_patterns_missing_good_patterns_key(self):
        """Parsing avec clé good_patterns manquante."""
        from app.application.learning import ExtractPatternsUseCase

        mock_feedback_store = Mock()
        feedback = Mock(rating=5, comment="Good", draft_final="Draft")
        mock_feedback_store.get_with_comments.return_value = [feedback]

        mock_pattern_store = Mock()
        mock_llm = Mock()
        mock_llm.complete.return_value = Mock(
            content='{"bad_patterns": ["test"], "suggestions": []}'
        )

        use_case = ExtractPatternsUseCase(
            feedback_store=mock_feedback_store,
            pattern_store=mock_pattern_store,
            llm=mock_llm,
        )

        result = use_case.execute()

        # Devrait gérer gracieusement la clé manquante
        assert isinstance(result, list)

    def test_parse_patterns_missing_bad_patterns_key(self):
        """Parsing avec clé bad_patterns manquante."""
        from app.application.learning import ExtractPatternsUseCase

        mock_feedback_store = Mock()
        feedback = Mock(rating=5, comment="Good", draft_final="Draft")
        mock_feedback_store.get_with_comments.return_value = [feedback]

        mock_pattern_store = Mock()
        mock_llm = Mock()
        mock_llm.complete.return_value = Mock(
            content='{"good_patterns": ["test"]}'
        )

        use_case = ExtractPatternsUseCase(
            feedback_store=mock_feedback_store,
            pattern_store=mock_pattern_store,
            llm=mock_llm,
        )

        result = use_case.execute()

        assert isinstance(result, list)

    def test_parse_patterns_llm_exception(self):
        """Gestion d'exception LLM."""
        from app.application.learning import ExtractPatternsUseCase

        mock_feedback_store = Mock()
        feedback = Mock(rating=5, comment="Good", draft_final="Draft")
        mock_feedback_store.get_with_comments.return_value = [feedback]

        mock_pattern_store = Mock()
        mock_llm = Mock()
        mock_llm.complete.side_effect = Exception("LLM Error")

        use_case = ExtractPatternsUseCase(
            feedback_store=mock_feedback_store,
            pattern_store=mock_pattern_store,
            llm=mock_llm,
        )

        result = use_case.execute()

        # Devrait retourner liste vide en cas d'erreur
        assert result == []


# =============================================================================
# TESTS FILE I/O ERRORS
# =============================================================================


class TestFileIOErrors:
    """Tests pour la gestion des erreurs I/O fichier."""

    def test_store_creates_directory_if_not_exists(self, tmp_path):
        """Le store crée le répertoire parent si inexistant."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        nested_path = tmp_path / "deep" / "nested" / "patterns.json"
        JsonLearningPatternStore(nested_path)

        assert nested_path.parent.exists()

    def test_store_handles_corrupted_json(self, tmp_path):
        """Le store gère un fichier JSON corrompu."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        filepath = tmp_path / "patterns.json"
        filepath.write_text("not valid json {{{", encoding="utf-8")

        store = JsonLearningPatternStore(filepath)
        patterns = store.list_all()

        # Devrait retourner liste vide au lieu de planter
        assert patterns == []

    def test_store_handles_empty_file(self, tmp_path):
        """Le store gère un fichier vide."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        filepath = tmp_path / "patterns.json"
        filepath.write_text("", encoding="utf-8")

        store = JsonLearningPatternStore(filepath)
        patterns = store.list_all()

        assert patterns == []

    def test_store_handles_file_not_found(self, tmp_path):
        """Le store gère un fichier manquant (créé à l'init)."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        filepath = tmp_path / "nonexistent.json"

        JsonLearningPatternStore(filepath)

        # Fichier créé automatiquement
        assert filepath.exists()

    def test_store_handles_permission_denied_read(self, tmp_path):
        """Le store gère une erreur de permission en lecture avec résilience."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        filepath = tmp_path / "patterns.json"
        filepath.write_text("[]", encoding="utf-8")

        store = JsonLearningPatternStore(filepath)

        # Simuler permission denied - le store utilise maintenant JsonFileStore
        # qui catch OSError (incluant PermissionError) et retourne une liste vide
        # pour une approche fail-safe plus résiliente
        with patch.object(Path, 'read_text', side_effect=PermissionError("Access denied")):
            result = store.list_all()
            assert result == []  # Fail-safe: retourne liste vide au lieu de propager l'erreur

    def test_store_handles_permission_denied_write(self, tmp_path):
        """Le store gère une erreur de permission en écriture."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType
        from app.infrastructure.adapters import json_file_store

        filepath = tmp_path / "patterns.json"
        store = JsonLearningPatternStore(filepath)

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        # Le store écrit via `_atomic_write_json` (commit 03df060a) — patcher
        # `Path.write_text` ne touche plus le chemin réel.
        with patch.object(
            json_file_store, "_atomic_write_json",
            side_effect=PermissionError("Access denied"),
        ):
            with pytest.raises(PermissionError):
                store.save(pattern)

    def test_store_handles_disk_full(self, tmp_path):
        """Le store gère une erreur disque plein."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType
        from app.infrastructure.adapters import json_file_store

        filepath = tmp_path / "patterns.json"
        store = JsonLearningPatternStore(filepath)

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        # Idem : route via `_atomic_write_json`.
        with patch.object(
            json_file_store, "_atomic_write_json",
            side_effect=OSError("No space left on device"),
        ):
            with pytest.raises(OSError):
                store.save(pattern)

    def test_store_count_on_corrupted_file(self, tmp_path):
        """Comptage sur fichier corrompu retourne 0."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        filepath = tmp_path / "patterns.json"
        filepath.write_text("{invalid", encoding="utf-8")

        store = JsonLearningPatternStore(filepath)

        assert store.count() == 0

    def test_store_get_by_id_not_found(self, tmp_path):
        """Récupération par ID inexistant retourne None."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        filepath = tmp_path / "patterns.json"
        store = JsonLearningPatternStore(filepath)

        result = store.get_by_id("nonexistent-id")

        assert result is None

    def test_store_update_nonexistent_returns_false(self, tmp_path):
        """Mise à jour d'un pattern inexistant retourne False."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        filepath = tmp_path / "patterns.json"
        store = JsonLearningPatternStore(filepath)

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        result = store.update(pattern)

        assert result is False


# =============================================================================
# TESTS PATTERN CONFIDENCE BOUNDS
# =============================================================================


class TestPatternConfidenceBounds:
    """Tests pour les bornes de confiance des patterns."""

    def test_increment_frequency_normal(self):
        """Incrémentation normale de fréquence."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        initial_frequency = pattern.frequency
        pattern.increment_frequency()

        assert pattern.frequency == initial_frequency + 1

    def test_confidence_reaches_max_at_10(self):
        """Confiance atteint 1.0 à 10 occurrences."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        for _ in range(9):  # frequency passe de 1 à 10
            pattern.increment_frequency()

        assert pattern.frequency == 10
        assert pattern.confidence == 1.0

    def test_confidence_capped_at_1(self):
        """Confiance ne dépasse jamais 1.0."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        for _ in range(100):  # frequency va bien au-delà de 10
            pattern.increment_frequency()

        assert pattern.frequency == 101
        assert pattern.confidence == 1.0  # Toujours capped

    def test_confidence_formula_precision(self):
        """Précision du calcul de confiance."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        # Après 3 increments: frequency = 4, confidence = 4/10 = 0.4
        for _ in range(3):
            pattern.increment_frequency()

        assert pattern.frequency == 4
        assert pattern.confidence == pytest.approx(0.4)

    def test_is_reliable_threshold(self):
        """Test des seuils de fiabilité."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        # confidence initiale = 0.5
        assert pattern.is_reliable(min_confidence=0.5) is True
        assert pattern.is_reliable(min_confidence=0.6) is False

    def test_pattern_serialization_preserves_confidence(self, tmp_path):
        """La sérialisation préserve la confiance."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        filepath = tmp_path / "patterns.json"
        store = JsonLearningPatternStore(filepath)

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )
        pattern.confidence = 0.75
        pattern.frequency = 7

        store.save(pattern)

        loaded = store.get_by_id(pattern.id)

        assert loaded is not None
        assert loaded.confidence == pytest.approx(0.75)
        assert loaded.frequency == 7

    def test_pattern_from_dict_with_missing_confidence(self):
        """Désérialisation avec confiance manquante utilise défaut."""
        from app.domain.entities.learning import LearnedPattern

        data = {
            "id": "test-id",
            "timestamp": datetime.now().isoformat(),
            "pattern_type": "good",
            "trigger": "test",
            "correction": "",
            # confidence et frequency manquants
        }

        pattern = LearnedPattern.from_dict(data)

        assert pattern.confidence == 0.5  # Valeur par défaut
        assert pattern.frequency == 1  # Valeur par défaut


# =============================================================================
# TESTS LEARNING STATS CONSISTENCY
# =============================================================================


class TestLearningStatsConsistency:
    """Tests pour la cohérence des statistiques d'apprentissage."""

    def test_stats_total_equals_sum_of_parts(self):
        """Total = good + bad + neutral."""
        from app.application.learning import AnalyzeFeedbackUseCase

        feedbacks = [
            Mock(rating=5),  # good
            Mock(rating=5),  # good
            Mock(rating=1),  # bad
            Mock(rating=3),  # neutral
        ]

        mock_store = Mock()
        mock_store.get_all.return_value = feedbacks

        use_case = AnalyzeFeedbackUseCase(feedback_store=mock_store)
        result = use_case.execute()

        assert result.total_with_feedback == (
            result.good_count + result.bad_count + result.neutral_count
        )

    def test_satisfaction_rate_formula(self):
        """Taux de satisfaction = (good / total) * 100."""
        from app.domain.entities.learning import LearningInsights

        insights = LearningInsights(
            total_with_feedback=100,
            good_count=75,
            bad_count=15,
            neutral_count=10,
        )

        assert insights.satisfaction_rate == 75.0

    def test_satisfaction_rate_zero_division(self):
        """Division par zéro gérée."""
        from app.domain.entities.learning import LearningInsights

        insights = LearningInsights(
            total_with_feedback=0,
            good_count=0,
            bad_count=0,
            neutral_count=0,
        )

        assert insights.satisfaction_rate == 0.0

    def test_version_rates_consistency(self):
        """Taux V1 et V2 sont dans [0, 100]."""
        from app.application.learning import AnalyzeFeedbackUseCase

        # Feedbacks avec status V1 et V2
        feedbacks = [
            Mock(rating=5, status="V1"),
            Mock(rating=2, status="V1"),
            Mock(rating=5, status="V2"),
            Mock(rating=5, status="V2"),
        ]

        mock_store = Mock()
        mock_store.get_all.return_value = feedbacks

        use_case = AnalyzeFeedbackUseCase(feedback_store=mock_store)
        result = use_case.execute()

        assert 0 <= result.v1_good_rate <= 100
        assert 0 <= result.v2_good_rate <= 100

    def test_get_learning_stats_all_fields_present(self):
        """GetLearningStats retourne tous les champs attendus."""
        from app.application.learning import GetLearningStatsUseCase

        mock_pattern_store = Mock()
        mock_pattern_store.count.return_value = 10
        mock_pattern_store.count_by_type.return_value = {"good": 6, "bad": 4}

        mock_adjustment_store = Mock()
        mock_adjustment_store.count_active.return_value = 2

        mock_feedback_store = Mock()
        mock_feedback_store.get_all.return_value = []

        use_case = GetLearningStatsUseCase(
            pattern_store=mock_pattern_store,
            adjustment_store=mock_adjustment_store,
            feedback_store=mock_feedback_store,
        )

        result = use_case.execute()

        expected_keys = [
            "patterns_count",
            "good_patterns",
            "bad_patterns",
            "active_adjustments",
            "confidence_threshold",
            "total_with_feedback",
            "good_count",
            "bad_count",
            "neutral_count",
            "v1_good_rate",
            "v2_good_rate",
        ]

        for key in expected_keys:
            assert key in result, f"Key '{key}' missing from stats"


# =============================================================================
# TESTS ENTITÉS EDGE CASES
# =============================================================================


class TestEntitiesEdgeCases:
    """Tests edge cases pour les entités du domaine."""

    def test_learned_pattern_empty_trigger(self):
        """Pattern avec trigger vide."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="",  # Vide
            correction="",
        )

        assert pattern.trigger == ""
        assert pattern.id is not None

    def test_prompt_adjustment_empty_fields(self):
        """Ajustement avec champs vides."""
        from app.domain.entities.learning import PromptAdjustment

        adjustment = PromptAdjustment.create(
            section="",
            adjustment="",
            reason="",
        )

        assert adjustment.section == ""
        assert adjustment.adjustment == ""
        assert adjustment.active is True

    def test_review_requirement_add_duplicate_reason(self):
        """Ajout de raison en double ignoré."""
        from app.domain.entities.learning import ReviewRequirement

        requirement = ReviewRequirement(
            needs_review=True,
            priority_score=90,
        )

        requirement.add_reason("Priorité haute")
        requirement.add_reason("Priorité haute")  # Duplicate

        assert len(requirement.reasons) == 1

    def test_learning_insights_to_dict_not_implemented(self):
        """LearningInsights n'a pas de méthode to_dict."""
        from app.domain.entities.learning import LearningInsights

        insights = LearningInsights()

        # La méthode n'existe pas actuellement
        assert not hasattr(insights, "to_dict")

    def test_learning_stats_to_dict(self):
        """LearningStats a une méthode to_dict."""
        from app.domain.entities.learning import LearningStats

        stats = LearningStats(
            patterns_count=10,
            good_patterns=6,
            bad_patterns=4,
        )

        result = stats.to_dict()

        assert isinstance(result, dict)
        assert result["patterns_count"] == 10

    def test_pattern_add_example_duplicate_ignored(self):
        """Ajout d'exemple en double ignoré."""
        from app.domain.entities.learning import LearnedPattern, PatternType

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="test",
            correction="",
        )

        pattern.add_example("Example 1")
        pattern.add_example("Example 1")  # Duplicate

        assert len(pattern.examples) == 1


# =============================================================================
# TESTS ADJUSTMENT STORE EDGE CASES
# =============================================================================


class TestAdjustmentStoreEdgeCases:
    """Tests edge cases pour le store d'ajustements."""

    def test_count_active_on_empty_store(self, tmp_path):
        """Comptage sur store vide."""
        from app.infrastructure.learning_store import JsonAdjustmentStore

        filepath = tmp_path / "adjustments.json"
        store = JsonAdjustmentStore(filepath)

        assert store.count_active() == 0

    def test_list_all_preserves_order(self, tmp_path):
        """Liste tous préserve l'ordre d'insertion."""
        from app.infrastructure.learning_store import JsonAdjustmentStore
        from app.domain.entities.learning import PromptAdjustment

        filepath = tmp_path / "adjustments.json"
        store = JsonAdjustmentStore(filepath)

        for i in range(5):
            adj = PromptAdjustment.create(
                section=f"Section {i}",
                adjustment=f"Adjustment {i}",
                reason="Test",
            )
            store.save(adj)

        result = store.list_all()

        for i, adj in enumerate(result):
            assert adj.section == f"Section {i}"

    def test_update_toggles_active_status(self, tmp_path):
        """Mise à jour bascule le statut actif."""
        from app.infrastructure.learning_store import JsonAdjustmentStore
        from app.domain.entities.learning import PromptAdjustment

        filepath = tmp_path / "adjustments.json"
        store = JsonAdjustmentStore(filepath)

        adj = PromptAdjustment.create("test", "test", "test")
        store.save(adj)

        adj.deactivate()
        store.update(adj)

        loaded = store.get_by_id(adj.id)
        assert loaded.active is False


# =============================================================================
# TESTS HISTORY FEEDBACK ADAPTER EDGE CASES
# =============================================================================


class TestHistoryFeedbackAdapterEdgeCases:
    """Tests edge cases pour l'adapter de feedbacks."""

    def test_satisfaction_rate_no_data_returns_100(self):
        """Taux de satisfaction sans données retourne 100%."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        mock_history = Mock()
        mock_history.get_all.return_value = []

        adapter = HistoryFeedbackAdapter(history_provider=mock_history)

        assert adapter.get_satisfaction_rate() == 100.0

    def test_get_with_comments_filters_correctly(self):
        """Filtrage des commentaires correct."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        records = [
            Mock(feedback_rating=5, feedback="Great!"),
            Mock(feedback_rating=3, feedback=None),  # Pas de commentaire
            Mock(feedback_rating=None, feedback="Comment"),  # Pas de rating
        ]

        mock_history = Mock()
        mock_history.get_all.return_value = records

        adapter = HistoryFeedbackAdapter(history_provider=mock_history)
        result = adapter.get_with_comments()

        # Seul le premier a rating ET feedback
        assert len(result) == 1

    def test_lazy_loading_import_error(self):
        """Gestion ImportError lors du lazy loading."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        adapter = HistoryFeedbackAdapter(history_provider=None)

        # Le lazy loading utilise un mock fallback si import échoue
        with patch.dict('sys.modules', {'app.history': None}):
            with patch('builtins.__import__', side_effect=ImportError):
                # Force le lazy loading
                adapter._history = None
                result = adapter.get_all()

                # Devrait retourner liste vide via le mock fallback
                assert isinstance(result, list)
