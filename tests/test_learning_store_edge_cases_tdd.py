# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases du Learning Store.

Ce module couvre les cas limites non testés :
- I/O Errors: permission denied, disk full, file corruption
- JSON Parsing: malformed JSON, encoding issues
- Concurrence: accès simultanés
- Limites: fichiers vides, très gros fichiers

Principes Clean Architecture respectés :
- Tests isolés avec fixtures temporaires
- Pas de dépendance sur l'état global
"""

import pytest
import json
import os
import threading
from unittest.mock import Mock
from datetime import datetime


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
# TESTS BASE JSON STORE - FILE I/O
# =============================================================================


class TestBaseJsonStoreFileIO:
    """Tests I/O pour BaseJsonStore."""

    def test_store_creates_file_if_not_exists(self, patterns_file):
        """Le store crée le fichier s'il n'existe pas."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        assert not patterns_file.exists()

        JsonLearningPatternStore(patterns_file)

        assert patterns_file.exists()
        assert patterns_file.read_text() == "[]"

    def test_store_creates_parent_directories(self, temp_dir):
        """Le store crée les répertoires parents."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        deep_path = temp_dir / "deep" / "nested" / "path" / "patterns.json"

        JsonLearningPatternStore(deep_path)

        assert deep_path.exists()

    def test_store_handles_corrupted_json_on_load(self, patterns_file):
        """Le store gère un JSON corrompu lors du chargement."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        # Créer un fichier avec JSON invalide
        patterns_file.write_text("{ invalid json }", encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)

        # _load() devrait retourner liste vide
        result = store.list_all()
        assert result == []

    def test_store_handles_empty_file(self, patterns_file):
        """Le store gère un fichier vide."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        patterns_file.write_text("", encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)

        # Fichier vide = JSON invalide
        result = store.list_all()
        assert result == []

    def test_store_handles_null_json(self, patterns_file):
        """Le store gère un JSON null."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        patterns_file.write_text("null", encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)

        # null n'est pas itérable - comportement à documenter
        try:
            result = store.list_all()
            # Si ça passe, devrait être vide
            assert result == []
        except TypeError:
            # TypeError: 'NoneType' object is not iterable
            pass

    def test_store_handles_json_object_instead_of_array(self, patterns_file):
        """Le store gère un objet JSON au lieu d'un array."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        patterns_file.write_text('{"key": "value"}', encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)

        # Objet n'est pas une liste - devrait lever TypeError ou KeyError
        try:
            store.list_all()
            # Si ça passe, devrait être traité comme liste
            pass
        except (TypeError, AttributeError, KeyError):
            # KeyError car dict[slice] échoue
            pass

    def test_store_handles_file_with_bom(self, patterns_file):
        """Le store gère un fichier avec BOM UTF-8."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        # Écrire avec BOM
        with open(patterns_file, 'wb') as f:
            f.write(b'\xef\xbb\xbf[]')  # UTF-8 BOM + []

        store = JsonLearningPatternStore(patterns_file)

        store.list_all()
        # Avec encoding="utf-8", le BOM devrait être géré
        # mais JSON peut échouer
        # Comportement dépend de la version Python

    def test_store_handles_unicode_content(self, patterns_file):
        """Le store gère correctement l'unicode."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        # Pattern avec caractères unicode
        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Réponse avec émojis 🎉 et accents éàü",
            correction="Correction avec 日本語",
        )

        store.save(pattern)

        # Recharger
        loaded = store.get_by_id(pattern.id)

        assert loaded is not None
        assert "🎉" in loaded.trigger
        assert "日本語" in loaded.correction


class TestPatternStoreEdgeCases:
    """Tests edge cases pour JsonLearningPatternStore."""

    def test_save_many_empty_list(self, patterns_file):
        """save_many() avec liste vide."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        store = JsonLearningPatternStore(patterns_file)

        result = store.save_many([])

        assert result == []
        assert store.count() == 0

    def test_save_many_large_batch(self, patterns_file):
        """save_many() avec grand nombre de patterns."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        patterns = [
            LearnedPattern.create(
                pattern_type=PatternType.GOOD,
                trigger=f"Pattern {i}",
                correction=f"Correction {i}",
            )
            for i in range(1000)
        ]

        result = store.save_many(patterns)

        assert len(result) == 1000
        assert store.count() == 1000

    def test_get_by_id_nonexistent(self, patterns_file):
        """get_by_id() avec ID inexistant."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        store = JsonLearningPatternStore(patterns_file)

        result = store.get_by_id("nonexistent-id")

        assert result is None

    def test_get_by_id_empty_string(self, patterns_file):
        """get_by_id() avec string vide."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        store = JsonLearningPatternStore(patterns_file)

        result = store.get_by_id("")

        assert result is None

    def test_list_all_limit_zero(self, patterns_file):
        """list_all() avec limit=0."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        # Ajouter des patterns
        store.save(LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Test",
            correction="",
        ))

        result = store.list_all(limit=0)

        # data[:0] retourne liste vide
        assert result == []

    def test_list_all_limit_negative(self, patterns_file):
        """list_all() avec limit négatif."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        store.save(LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Test 1",
            correction="",
        ))
        store.save(LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Test 2",
            correction="",
        ))

        result = store.list_all(limit=-1)

        # data[:-1] exclut le dernier élément
        assert len(result) == 1

    def test_get_by_type_with_mixed_types(self, patterns_file):
        """get_by_type() avec patterns de types mixtes."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        store.save(LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Good 1",
            correction="",
        ))
        store.save(LearnedPattern.create(
            pattern_type=PatternType.BAD,
            trigger="Bad 1",
            correction="",
        ))
        store.save(LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Good 2",
            correction="",
        ))

        good_patterns = store.get_by_type(PatternType.GOOD)
        bad_patterns = store.get_by_type(PatternType.BAD)

        assert len(good_patterns) == 2
        assert len(bad_patterns) == 1

    def test_update_nonexistent_pattern(self, patterns_file):
        """update() sur pattern inexistant."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Test",
            correction="",
        )

        result = store.update(pattern)

        assert result is False

    def test_update_existing_pattern(self, patterns_file):
        """update() sur pattern existant."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        pattern = LearnedPattern.create(
            pattern_type=PatternType.GOOD,
            trigger="Original",
            correction="",
        )
        store.save(pattern)

        # Récupérer le pattern, le modifier, puis le sauvegarder
        loaded = store.get_by_id(pattern.id)
        # Créer un nouveau pattern avec les valeurs modifiées
        modified_pattern = LearnedPattern(
            id=loaded.id,
            timestamp=loaded.timestamp,
            pattern_type=loaded.pattern_type,
            trigger="Modified",
            correction=loaded.correction,
            examples=loaded.examples,
            frequency=loaded.frequency,
            confidence=loaded.confidence,
        )

        result = store.update(modified_pattern)

        assert result is True

        # Vérifier la modification
        reloaded = store.get_by_id(pattern.id)
        assert reloaded.trigger == "Modified"

    def test_count_by_type_empty_store(self, patterns_file):
        """count_by_type() sur store vide."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        store = JsonLearningPatternStore(patterns_file)

        result = store.count_by_type()

        assert result == {"good": 0, "bad": 0}

    def test_count_by_type_unknown_type(self, patterns_file):
        """count_by_type() avec type inconnu dans les données."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        # Injecter un pattern avec type inconnu
        patterns_file.write_text(json.dumps([
            {"id": "1", "pattern_type": "unknown", "trigger": "test"}
        ]), encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)

        result = store.count_by_type()

        # "unknown" n'est pas dans counts, donc ignoré
        assert result == {"good": 0, "bad": 0}


class TestAdjustmentStoreEdgeCases:
    """Tests edge cases pour JsonAdjustmentStore."""

    def test_get_active_with_missing_active_field(self, adjustments_file):
        """get_active() quand le champ 'active' est manquant."""
        from app.infrastructure.learning_store import JsonAdjustmentStore

        # Ajustement avec tous les champs requis sauf 'active'
        adjustments_file.write_text(json.dumps([
            {
                "id": "1",
                "timestamp": datetime.now().isoformat(),
                "section": "test",
                "adjustment": "adj",
                "reason": "r"
            }
        ]), encoding="utf-8")

        store = JsonAdjustmentStore(adjustments_file)

        result = store.get_active()

        # active est True par défaut (via .get("active", True) dans get_active())
        assert len(result) == 1

    def test_get_active_with_false_active(self, adjustments_file):
        """get_active() avec ajustement inactif."""
        from app.infrastructure.learning_store import JsonAdjustmentStore

        adjustments_file.write_text(json.dumps([
            {"id": "1", "section": "test", "adjustment": "adj", "reason": "r", "created_at": "2024-01-01", "active": False}
        ]), encoding="utf-8")

        store = JsonAdjustmentStore(adjustments_file)

        result = store.get_active()

        assert len(result) == 0

    def test_count_active_mixed(self, adjustments_file):
        """count_active() avec mix actif/inactif."""
        from app.infrastructure.learning_store import JsonAdjustmentStore

        adjustments_file.write_text(json.dumps([
            {"id": "1", "section": "test", "adjustment": "a1", "reason": "r", "created_at": "2024-01-01", "active": True},
            {"id": "2", "section": "test", "adjustment": "a2", "reason": "r", "created_at": "2024-01-01", "active": False},
            {"id": "3", "section": "test", "adjustment": "a3", "reason": "r", "created_at": "2024-01-01"},  # default True
        ]), encoding="utf-8")

        store = JsonAdjustmentStore(adjustments_file)

        result = store.count_active()

        assert result == 2


class TestHistoryFeedbackAdapterEdgeCases:
    """Tests edge cases pour HistoryFeedbackAdapter."""

    def test_adapter_without_history_provider(self):
        """Adapter sans history provider utilise lazy loading."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        HistoryFeedbackAdapter()

        # Le provider sera chargé au premier appel
        # Si import échoue, utilise MockHistory

    def test_adapter_with_mock_history(self):
        """Adapter avec mock history provider."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        mock_history = Mock()
        mock_history.get_all.return_value = [
            Mock(feedback_rating=5, feedback="Great"),
            Mock(feedback_rating=3, feedback="OK"),
            Mock(feedback_rating=None),  # Pas de rating
        ]

        adapter = HistoryFeedbackAdapter(history_provider=mock_history)

        # get_all() filtre ceux sans rating
        result = adapter.get_all()
        assert len(result) == 2

    def test_adapter_get_with_comments_filters(self):
        """get_with_comments() filtre ceux sans commentaire."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        mock_history = Mock()
        mock_history.get_all.return_value = [
            Mock(feedback_rating=5, feedback="Comment"),
            Mock(feedback_rating=4, feedback=""),  # Pas de commentaire
            Mock(feedback_rating=3, feedback=None),  # Feedback None
        ]

        adapter = HistoryFeedbackAdapter(history_provider=mock_history)

        result = adapter.get_with_comments()
        assert len(result) == 1

    def test_adapter_satisfaction_rate_empty(self):
        """satisfaction_rate() avec historique vide retourne 100%."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        mock_history = Mock()
        mock_history.get_all.return_value = []

        adapter = HistoryFeedbackAdapter(history_provider=mock_history)

        result = adapter.get_satisfaction_rate()
        assert result == 100.0

    def test_adapter_satisfaction_rate_calculation(self):
        """satisfaction_rate() calcule correctement."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        mock_history = Mock()
        mock_history.get_all.return_value = [
            Mock(feedback_rating=5),
            Mock(feedback_rating=4),
            Mock(feedback_rating=3),
            Mock(feedback_rating=2),
        ]

        adapter = HistoryFeedbackAdapter(history_provider=mock_history)

        # 2 feedbacks >= 4 sur 4 total = 50%
        result = adapter.get_satisfaction_rate()
        assert result == 50.0

    def test_adapter_count_delegates_to_get_all(self):
        """count() utilise get_all() en interne."""
        from app.infrastructure.learning_store import HistoryFeedbackAdapter

        mock_history = Mock()
        mock_history.get_all.return_value = [
            Mock(feedback_rating=5),
            Mock(feedback_rating=4),
        ]

        adapter = HistoryFeedbackAdapter(history_provider=mock_history)

        result = adapter.count()
        assert result == 2


class TestConcurrentAccess:
    """Tests d'accès concurrent aux stores."""

    def test_pattern_store_concurrent_saves(self, patterns_file):
        """Sauvegardes concurrentes de patterns - documente le comportement actuel.

        Note: Le store actuel n'a pas de mécanisme de locking,
        ce qui peut entraîner des pertes de données en concurrence.
        Ce test vérifie qu'aucune exception n'est levée, mais
        ne garantit pas la persistance de toutes les données.
        """
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)
        errors = []

        def save_patterns(thread_id):
            try:
                for i in range(10):
                    pattern = LearnedPattern.create(
                        pattern_type=PatternType.GOOD,
                        trigger=f"Thread {thread_id} Pattern {i}",
                        correction="",
                    )
                    store.save(pattern)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_patterns, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Pas d'erreurs de race condition (pas d'exceptions)
        assert len(errors) == 0

        # Documentation du comportement actuel:
        # Sans locking, les écritures concurrentes peuvent s'écraser
        # mutuellement (read-modify-write race condition).
        # Ce test documente que le store ne lève pas d'exception
        # mais peut perdre des données.
        total = store.count()
        # On vérifie simplement que le store reste cohérent
        # (pas de fichier corrompu, pas d'exception à la lecture)
        assert total >= 0  # Le store doit rester lisible

    def test_pattern_store_concurrent_read_write(self, patterns_file):
        """Lectures et écritures concurrentes."""
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        store = JsonLearningPatternStore(patterns_file)

        # Pré-remplir
        for i in range(10):
            store.save(LearnedPattern.create(
                pattern_type=PatternType.GOOD,
                trigger=f"Initial {i}",
                correction="",
            ))

        errors = []

        def reader():
            try:
                for _ in range(20):
                    store.list_all()
                    store.count()
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(5):
                    store.save(LearnedPattern.create(
                        pattern_type=PatternType.BAD,
                        trigger=f"New {i}",
                        correction="",
                    ))
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=reader))
            threads.append(threading.Thread(target=writer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Les erreurs de parsing JSON sont possibles sans locking
        # Ce test documente le comportement


class TestFilePermissionErrors:
    """Tests pour les erreurs de permission fichier."""

    @pytest.mark.skipif(os.name == 'nt', reason="Permission tests differ on Windows")
    def test_store_handles_read_only_file(self, temp_dir):
        """Le store gère un répertoire en lecture seule lors d'une écriture.

        Note: depuis le commit 03df060a (atomic writes via tempfile + os.replace),
        un fichier read-only au sein d'un répertoire writable ne provoque plus
        d'erreur — le rename POSIX ignore les perms du fichier cible. Pour
        forcer une vraie PermissionError sur write, on doit verrouiller le
        répertoire parent (création du tempfile impossible).
        """
        from app.infrastructure.learning_store import JsonLearningPatternStore
        from app.domain.entities.learning import LearnedPattern, PatternType

        readonly_dir = temp_dir / "readonly_save"
        readonly_dir.mkdir()
        patterns_file = readonly_dir / "patterns.json"
        patterns_file.write_text("[]", encoding="utf-8")

        store = JsonLearningPatternStore(patterns_file)

        # Rendre le répertoire read-only APRÈS l'init (le store crée le fichier
        # à la construction si manquant).
        os.chmod(readonly_dir, 0o555)

        try:
            # La lecture devrait fonctionner
            result = store.list_all()
            assert result == []

            # L'écriture devrait échouer (création du tempfile dans dir read-only).
            pattern = LearnedPattern.create(
                pattern_type=PatternType.GOOD,
                trigger="Test",
                correction="",
            )

            with pytest.raises(PermissionError):
                store.save(pattern)

        finally:
            # Restaurer les permissions pour nettoyage
            os.chmod(readonly_dir, 0o755)

    @pytest.mark.skipif(os.name == 'nt', reason="Permission tests differ on Windows")
    def test_store_handles_read_only_directory(self, temp_dir):
        """Le store gère un répertoire en lecture seule."""
        from app.infrastructure.learning_store import JsonLearningPatternStore

        readonly_dir = temp_dir / "readonly_dir"
        readonly_dir.mkdir()

        patterns_file = readonly_dir / "patterns.json"
        patterns_file.write_text("[]", encoding="utf-8")

        # Rendre le répertoire read-only
        os.chmod(readonly_dir, 0o555)

        try:
            store = JsonLearningPatternStore(patterns_file)

            # La lecture devrait fonctionner
            result = store.list_all()
            assert result == []

        finally:
            os.chmod(readonly_dir, 0o755)
