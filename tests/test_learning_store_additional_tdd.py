# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD supplémentaires pour les edge cases du Learning Store.

Ces tests couvrent les cas limites additionnels :
- Rétrocompatibilité des données (created_at -> timestamp)
- Gestion des IDs dupliqués
- Limites de taille de fichier
- Caractères spéciaux dans les IDs
- Sérialization/désérialization edge cases
- Entités avec valeurs par défaut manquantes

Principes Clean Architecture respectés :
- Tests isolés avec fixtures temporaires
- Pas de dépendance sur l'état global
"""

import pytest
import json
from unittest.mock import Mock

# Note: Les entités LearnedPattern et PromptAdjustment utilisent datetime
# pour le timestamp, pas une chaîne ISO. Il faut utiliser .create() pour
# les créer correctement ou passer un objet datetime.


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_dir(tmp_path):
    """Crée un répertoire temporaire pour les tests."""
    return tmp_path


@pytest.fixture
def patterns_file(temp_dir):
    """Crée un fichier patterns temporaire."""
    return temp_dir / "patterns.json"


@pytest.fixture
def adjustments_file(temp_dir):
    """Crée un fichier adjustments temporaire."""
    return temp_dir / "adjustments.json"


# =============================================================================
# TESTS RÉTROCOMPATIBILITÉ
# =============================================================================


class TestRetrocompatibility:
    """Tests pour la rétrocompatibilité des données."""

    def test_pattern_store_handles_created_at_field(self, patterns_file):
        """Le store gère l'ancien champ 'created_at' au lieu de 'timestamp'."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        # Ancien format avec created_at
        old_format = [{
            "id": "old-pattern",
            "created_at": "2023-01-15T10:00:00",  # Ancien champ
            "pattern_type": "good",
            "trigger": "Old trigger",
            "correction": "",
            "examples": [],
            "frequency": 1,
            "confidence": 0.5
        }]
        patterns_file.write_text(json.dumps(old_format), encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)
        pattern = store.get_by_id("old-pattern")

        assert pattern is not None
        assert pattern.timestamp is not None

    def test_pattern_store_handles_missing_timestamp(self, patterns_file):
        """Le store gère les patterns sans timestamp ni created_at."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        # Format sans timestamp
        no_timestamp = [{
            "id": "no-time-pattern",
            "pattern_type": "good",
            "trigger": "No timestamp",
            "correction": "",
            "examples": [],
            "frequency": 1,
            "confidence": 0.5
        }]
        patterns_file.write_text(json.dumps(no_timestamp), encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)
        pattern = store.get_by_id("no-time-pattern")

        assert pattern is not None
        # Un timestamp par défaut devrait être généré
        assert pattern.timestamp is not None

    def test_adjustment_store_handles_created_at_field(self, adjustments_file):
        """Le store adjustment gère l'ancien champ 'created_at'."""
        from app.infrastructure.learning_store import JsonAdjustmentStore

        old_format = [{
            "id": "old-adj",
            "created_at": "2023-01-15T10:00:00",
            "section": "DRAFTER",
            "adjustment": "Test",
            "reason": "Test",
            "active": True
        }]
        adjustments_file.write_text(json.dumps(old_format), encoding="utf-8")

        store = JsonAdjustmentStore(adjustments_file)
        adj = store.get_by_id("old-adj")

        assert adj is not None
        assert adj.timestamp is not None


# =============================================================================
# TESTS IDS DUPLIQUÉS
# =============================================================================


class TestDuplicateIds:
    """Tests pour la gestion des IDs dupliqués."""

    def test_save_with_duplicate_id(self, patterns_file):
        """save() avec ID dupliqué ajoute un nouveau record."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        # Créer deux patterns avec le même ID via .create()
        pattern1 = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="First",
            correction="",
        )
        # Forcer le même ID
        pattern1_id = pattern1.id

        pattern2 = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Second",
            correction="",
        )
        # Modifier l'ID pour créer un doublon
        pattern2 = LearnedPattern(
            id=pattern1_id,
            timestamp=pattern2.timestamp,
            pattern_type=pattern2.pattern_type,
            trigger=pattern2.trigger,
            correction=pattern2.correction,
            examples=pattern2.examples,
            frequency=pattern2.frequency,
            confidence=pattern2.confidence,
        )

        store.save(pattern1)
        store.save(pattern2)

        # Comportement actuel: les deux sont sauvegardés (pas de contrainte d'unicité)
        assert store.count() == 2

    def test_get_by_id_with_duplicates_returns_first(self, patterns_file):
        """get_by_id() avec IDs dupliqués retourne le premier."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        # Injecter des données avec IDs dupliqués
        duplicates = [
            {"id": "dup", "pattern_type": "good", "trigger": "First", "timestamp": "2024-01-01"},
            {"id": "dup", "pattern_type": "bad", "trigger": "Second", "timestamp": "2024-01-02"},
        ]
        patterns_file.write_text(json.dumps(duplicates), encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)
        result = store.get_by_id("dup")

        # Retourne le premier trouvé
        assert result is not None
        assert result.trigger == "First"


# =============================================================================
# TESTS CARACTÈRES SPÉCIAUX
# =============================================================================


class TestSpecialCharacters:
    """Tests pour les caractères spéciaux."""

    def test_pattern_with_special_chars_in_id(self, patterns_file):
        """Pattern avec caractères spéciaux dans l'ID."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        special_id = "id-with-émojis-🎉-and/slashes\\backslash"

        # Créer via .create() puis modifier l'ID
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Test",
            correction="",
        )
        # Recréer avec l'ID spécial
        pattern = LearnedPattern(
            id=special_id,
            timestamp=pattern.timestamp,
            pattern_type=pattern.pattern_type,
            trigger=pattern.trigger,
            correction=pattern.correction,
            examples=pattern.examples,
            frequency=pattern.frequency,
            confidence=pattern.confidence,
        )

        store.save(pattern)
        loaded = store.get_by_id(special_id)

        assert loaded is not None
        assert loaded.id == special_id

    def test_pattern_with_newlines_in_fields(self, patterns_file):
        """Pattern avec sauts de ligne dans les champs."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Line 1\nLine 2\nLine 3",
            correction="Correction\nwith\nnewlines",
        )

        store.save(pattern)
        loaded = store.get_by_id(pattern.id)

        assert "\n" in loaded.trigger
        assert loaded.trigger.count("\n") == 2

    def test_pattern_with_json_special_chars(self, patterns_file):
        """Pattern avec caractères spéciaux JSON."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger='Contains "quotes" and {braces}',
            correction="Has [brackets] and \\backslash",
        )

        store.save(pattern)
        loaded = store.get_by_id(pattern.id)

        assert '"quotes"' in loaded.trigger
        assert "[brackets]" in loaded.correction


# =============================================================================
# TESTS VALEURS PAR DÉFAUT
# =============================================================================


class TestDefaultValues:
    """Tests pour les valeurs par défaut."""

    def test_pattern_missing_optional_fields(self, patterns_file):
        """Pattern avec champs optionnels manquants."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        # Pattern minimaliste
        minimal = [{
            "id": "minimal",
            "timestamp": "2024-01-01",
            "pattern_type": "good",
            "trigger": "Test"
            # correction, examples, frequency, confidence manquants
        }]
        patterns_file.write_text(json.dumps(minimal), encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)
        pattern = store.get_by_id("minimal")

        assert pattern is not None
        # Valeurs par défaut
        assert pattern.correction == ""
        assert pattern.examples == []
        assert pattern.frequency == 1
        assert pattern.confidence == 0.5

    def test_adjustment_missing_active_field(self, adjustments_file):
        """Ajustement sans champ 'active'."""
        from app.infrastructure.learning_store import JsonAdjustmentStore

        minimal = [{
            "id": "adj1",
            "timestamp": "2024-01-01",
            "section": "DRAFTER",
            "adjustment": "Test",
            "reason": "Test"
            # active manquant
        }]
        adjustments_file.write_text(json.dumps(minimal), encoding="utf-8")

        store = JsonAdjustmentStore(adjustments_file)
        adj = store.get_by_id("adj1")

        assert adj is not None
        # active par défaut = True
        assert adj.active is True


# =============================================================================
# TESTS LIMITES DE TAILLE
# =============================================================================


class TestSizeLimits:
    """Tests pour les limites de taille."""

    def test_pattern_with_very_long_trigger(self, patterns_file):
        """Pattern avec trigger très long."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        # 100KB de texte
        long_trigger = "A" * 100_000

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger=long_trigger,
            correction="",
        )

        store.save(pattern)
        loaded = store.get_by_id(pattern.id)

        assert loaded is not None
        assert len(loaded.trigger) == 100_000

    def test_pattern_with_many_examples(self, patterns_file, monkeypatch):
        """Pattern avec beaucoup d'exemples."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Test",
            correction="",
        )

        # Ajouter 1000 exemples
        for i in range(1000):
            pattern.add_example(f"Example {i}")

        store.save(pattern)
        loaded = store.get_by_id(pattern.id)

        assert loaded is not None
        assert len(loaded.examples) == 1000

    def test_store_with_large_number_of_records(self, patterns_file):
        """Store avec beaucoup d'enregistrements."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        # Sauvegarder 5000 patterns
        patterns = [
            LearnedPattern.create(
                pattern_type=PatternType.GOOD if i % 2 == 0 else PatternType.BAD,
                trigger=f"Pattern {i}",
                correction=f"Correction {i}",
            )
            for i in range(5000)
        ]

        ids = store.save_many(patterns)

        assert len(ids) == 5000
        assert store.count() == 5000

        # Vérifier que les opérations restent fonctionnelles
        first = store.get_by_id(ids[0])
        last = store.get_by_id(ids[-1])
        assert first is not None
        assert last is not None


# =============================================================================
# TESTS SERIALIZATION/DESERIALIZATION
# =============================================================================


class TestSerialization:
    """Tests pour la sérialization/désérialization."""

    def test_pattern_roundtrip_preserves_all_fields(self, patterns_file, monkeypatch):
        """Le roundtrip préserve tous les champs."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        # Créer via .create() pour avoir un timestamp datetime valide
        original = LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Original trigger",
            correction="Original correction",
        )
        # Modifier les champs pour le test
        original.frequency = 42
        original.confidence = 0.87
        original.examples = ["Ex1", "Ex2", "Ex3"]

        store.save(original)
        loaded = store.get_by_id(original.id)

        assert loaded.id == original.id
        # Comparer les timestamps en ISO (car reload = datetime, original = datetime)
        assert loaded.timestamp.isoformat() == original.timestamp.isoformat()
        assert loaded.pattern_type == original.pattern_type
        assert loaded.trigger == original.trigger
        assert loaded.correction == original.correction
        assert loaded.examples == original.examples
        assert loaded.frequency == original.frequency
        assert loaded.confidence == pytest.approx(original.confidence)

    def test_adjustment_roundtrip_preserves_all_fields(self, adjustments_file):
        """Le roundtrip adjustment préserve tous les champs."""
        from app.infrastructure.learning_store import JsonAdjustmentStore
        from app.domain.entities.learning import PromptAdjustment

        store = JsonAdjustmentStore(adjustments_file)

        # Créer via .create() pour avoir un timestamp datetime valide
        original = PromptAdjustment.create(
            section="CRITIC",
            adjustment="Test adjustment",
            reason="Test reason",
        )
        # Désactiver pour le test
        original.deactivate()

        store.save(original)
        loaded = store.get_by_id(original.id)

        assert loaded.id == original.id
        # Comparer les timestamps en ISO
        assert loaded.timestamp.isoformat() == original.timestamp.isoformat()
        assert loaded.section == original.section
        assert loaded.adjustment == original.adjustment
        assert loaded.reason == original.reason
        assert loaded.active == original.active


# =============================================================================
# TESTS ÉTAT INVALIDE
# =============================================================================


class TestInvalidState:
    """Tests pour les états invalides."""

    def test_pattern_with_unknown_pattern_type(self, patterns_file):
        """Pattern avec type inconnu dans les données."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        invalid_type = [{
            "id": "invalid-type",
            "timestamp": "2024-01-01",
            "pattern_type": "unknown_type",  # Type invalide
            "trigger": "Test",
            "correction": "",
            "examples": [],
            "frequency": 1,
            "confidence": 0.5
        }]
        patterns_file.write_text(json.dumps(invalid_type), encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)

        # Comportement dépend de PatternType.from_string()
        try:
            pattern = store.get_by_id("invalid-type")
            # Si ça passe, vérifier que le type est géré
            assert pattern is not None
        except (ValueError, KeyError):
            # Erreur attendue pour type inconnu
            pass

    def test_pattern_with_negative_values(self, patterns_file):
        """Pattern avec valeurs négatives."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        negative = [{
            "id": "negative",
            "timestamp": "2024-01-01",
            "pattern_type": "good",
            "trigger": "Test",
            "correction": "",
            "examples": [],
            "frequency": -10,
            "confidence": -0.5
        }]
        patterns_file.write_text(json.dumps(negative), encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)
        pattern = store.get_by_id("negative")

        # Les valeurs négatives sont acceptées (pas de validation)
        assert pattern is not None
        assert pattern.frequency == -10
        assert pattern.confidence == -0.5


# =============================================================================
# TESTS HISTORY FEEDBACK ADAPTER
# =============================================================================


class TestHistoryFeedbackAdapterEdgeCasesAdditional:
    """Tests edge cases supplémentaires pour HistoryFeedbackAdapter."""

    def test_adapter_with_none_history_provider(self):
        """Adapter avec None comme provider utilise lazy loading."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        adapter = HistoryFeedbackAdapter(history_provider=None)

        # L'accès déclenche le lazy loading
        # Si app.history n'est pas disponible, utilise MockHistory
        result = adapter.get_all()
        assert isinstance(result, list)

    def test_adapter_get_all_with_attribute_error(self):
        """get_all() gère les objets sans feedback_rating."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        mock_history = Mock()
        # Objet sans attribut feedback_rating
        obj_without_rating = object()
        mock_history.get_all.return_value = [obj_without_rating]

        adapter = HistoryFeedbackAdapter(history_provider=mock_history)

        result = adapter.get_all()
        # getattr avec default None filtre les objets sans rating
        assert len(result) == 0

    def test_adapter_satisfaction_rate_with_zero_rating(self):
        """satisfaction_rate() avec rating 0 (non compté comme good)."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        mock_history = Mock()
        mock_history.get_all.return_value = [
            Mock(feedback_rating=0),  # 0 < 4, donc pas "good"
            Mock(feedback_rating=4),  # >= 4, donc "good"
        ]

        adapter = HistoryFeedbackAdapter(history_provider=mock_history)

        result = adapter.get_satisfaction_rate()
        # 1 good sur 2 = 50%
        assert result == 50.0

    def test_adapter_limit_parameter(self):
        """get_all() respecte le paramètre limit."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        mock_history = Mock()
        # Retourne 10 feedbacks
        mock_history.get_all.return_value = [
            Mock(feedback_rating=5) for _ in range(10)
        ]

        adapter = HistoryFeedbackAdapter(history_provider=mock_history)

        adapter.get_all(limit=5)

        # Vérifie que get_all a été appelé avec limit
        mock_history.get_all.assert_called_with(limit=5)
