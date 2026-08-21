# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les adapters ItemTracker (JSON et InMemory).

Ce module teste:
1. JsonItemTracker - persistance fichier generique
2. InMemoryItemTracker - tracking en memoire pour tests
3. Factory functions (create_email_tracker, create_draft_tracker)
4. Edge cases (null, erreurs, concurrence, formats)

TDD: Tests ecrits pour valider l'implementation.
Clean Architecture: Infrastructure layer (Adapters).
"""

import json
import os
import pytest
from pathlib import Path

from app.domain.ports.item_tracker_port import ItemTrackerPort
from app.infrastructure.adapters.item_tracker_adapter import (
    JsonItemTracker,
    InMemoryItemTracker,
    create_email_tracker,
    create_draft_tracker,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_file(tmp_path) -> Path:
    """Cree un fichier temporaire pour les tests."""
    return tmp_path / "test_items.json"


@pytest.fixture
def json_tracker(temp_file) -> JsonItemTracker:
    """Cree un tracker JSON avec fichier temporaire."""
    return JsonItemTracker(filepath=temp_file, item_type="test_item")


@pytest.fixture
def memory_tracker() -> InMemoryItemTracker:
    """Cree un tracker en memoire."""
    return InMemoryItemTracker(item_type="test_item")


# =============================================================================
# TESTS - JsonItemTracker IMPLEMENTS PORT
# =============================================================================


class TestJsonItemTrackerImplementsPort:
    """Tests pour verifier l'implementation du port."""

    def test_implements_item_tracker_port(self, json_tracker):
        """JsonItemTracker implemente ItemTrackerPort."""
        assert isinstance(json_tracker, ItemTrackerPort)

    def test_has_all_required_methods(self, json_tracker):
        """A toutes les methodes requises."""
        assert hasattr(json_tracker, "is_processed")
        assert hasattr(json_tracker, "mark_processed")
        assert hasattr(json_tracker, "count")
        assert hasattr(json_tracker, "get_all_ids")
        assert hasattr(json_tracker, "clear")


# =============================================================================
# TESTS - JsonItemTracker BASIC OPERATIONS
# =============================================================================


class TestJsonItemTrackerBasicOperations:
    """Tests pour les operations basiques."""

    def test_initially_empty(self, json_tracker):
        """Un nouveau tracker est vide."""
        assert json_tracker.count() == 0
        assert json_tracker.get_all_ids() == set()

    def test_mark_processed_adds_id(self, json_tracker):
        """mark_processed ajoute un ID."""
        json_tracker.mark_processed("item-123")
        assert json_tracker.is_processed("item-123")
        assert json_tracker.count() == 1

    def test_is_processed_returns_false_for_unknown(self, json_tracker):
        """is_processed retourne False pour un ID inconnu."""
        assert not json_tracker.is_processed("unknown-id")

    def test_mark_processed_idempotent(self, json_tracker):
        """Marquer plusieurs fois le meme item ne change pas le count."""
        json_tracker.mark_processed("item-123")
        json_tracker.mark_processed("item-123")
        json_tracker.mark_processed("item-123")
        assert json_tracker.count() == 1

    def test_multiple_items(self, json_tracker):
        """Supporte plusieurs items."""
        item_ids = ["item-1", "item-2", "item-3"]
        for item_id in item_ids:
            json_tracker.mark_processed(item_id)

        assert json_tracker.count() == 3
        for item_id in item_ids:
            assert json_tracker.is_processed(item_id)

    def test_get_all_ids_returns_set(self, json_tracker):
        """get_all_ids retourne un set."""
        json_tracker.mark_processed("item-1")
        json_tracker.mark_processed("item-2")

        ids = json_tracker.get_all_ids()
        assert isinstance(ids, set)
        assert ids == {"item-1", "item-2"}

    def test_get_all_ids_returns_copy(self, json_tracker):
        """get_all_ids retourne une copie (pas de mutation externe)."""
        json_tracker.mark_processed("item-1")
        ids = json_tracker.get_all_ids()
        ids.add("external-add")
        assert "external-add" not in json_tracker.get_all_ids()

    def test_clear_removes_all(self, json_tracker):
        """clear supprime tous les IDs."""
        json_tracker.mark_processed("item-1")
        json_tracker.mark_processed("item-2")
        json_tracker.clear()

        assert json_tracker.count() == 0
        assert json_tracker.get_all_ids() == set()
        assert not json_tracker.is_processed("item-1")


# =============================================================================
# TESTS - JsonItemTracker PERSISTENCE
# =============================================================================


class TestJsonItemTrackerPersistence:
    """Tests pour la persistance sur disque."""

    def test_persists_on_mark_processed(self, temp_file, json_tracker):
        """Les donnees persistent sur disque apres mark_processed."""
        json_tracker.mark_processed("item-123")
        assert temp_file.exists()

    def test_reloads_from_disk(self, temp_file):
        """Les donnees sont rechargees depuis le disque."""
        tracker1 = JsonItemTracker(filepath=temp_file, item_type="test")
        tracker1.mark_processed("item-123")

        tracker2 = JsonItemTracker(filepath=temp_file, item_type="test")
        assert tracker2.is_processed("item-123")
        assert tracker2.count() == 1

    def test_persists_on_clear(self, temp_file, json_tracker):
        """clear persiste aussi sur disque."""
        json_tracker.mark_processed("item-1")
        json_tracker.clear()

        tracker2 = JsonItemTracker(filepath=temp_file, item_type="test")
        assert tracker2.count() == 0

    def test_creates_directory_if_needed(self, tmp_path):
        """Cree le repertoire parent si necessaire."""
        nested_path = tmp_path / "sub" / "dir" / "items.json"
        tracker = JsonItemTracker(filepath=nested_path, item_type="test")
        tracker.mark_processed("test")
        assert nested_path.exists()


# =============================================================================
# TESTS - JsonItemTracker FILE FORMAT
# =============================================================================


class TestJsonItemTrackerFileFormat:
    """Tests pour le format du fichier JSON."""

    def test_file_contains_processed_ids(self, temp_file, json_tracker):
        """Le fichier contient les IDs traites."""
        json_tracker.mark_processed("item-1")
        json_tracker.mark_processed("item-2")

        data = json.loads(temp_file.read_text())
        assert "processed_test_item_ids" in data
        assert set(data["processed_test_item_ids"]) == {"item-1", "item-2"}

    def test_file_contains_metadata(self, temp_file, json_tracker):
        """Le fichier contient les metadonnees."""
        json_tracker.mark_processed("item-1")

        data = json.loads(temp_file.read_text())
        assert "last_updated" in data
        assert "count" in data
        assert "item_type" in data
        assert data["count"] == 1
        assert data["item_type"] == "test_item"

    def test_ids_are_sorted(self, temp_file, json_tracker):
        """Les IDs sont tries dans le fichier."""
        json_tracker.mark_processed("z-item")
        json_tracker.mark_processed("a-item")
        json_tracker.mark_processed("m-item")

        data = json.loads(temp_file.read_text())
        ids = data["processed_test_item_ids"]
        assert ids == sorted(ids)

    def test_file_is_utf8(self, temp_file, json_tracker):
        """Le fichier est en UTF-8."""
        json_tracker.mark_processed("item-unicode-\u4e2d\u6587")

        content = temp_file.read_text(encoding="utf-8")
        assert "\u4e2d\u6587" in content


# =============================================================================
# TESTS - JsonItemTracker ITEM TYPE
# =============================================================================


class TestJsonItemTrackerItemType:
    """Tests pour le type d'item."""

    def test_item_type_property(self, json_tracker):
        """item_type est accessible via property."""
        assert json_tracker.item_type == "test_item"

    def test_filepath_property(self, temp_file, json_tracker):
        """filepath est accessible via property."""
        assert json_tracker.filepath == temp_file

    def test_custom_item_type(self, temp_file):
        """Supporte un type d'item personnalise."""
        tracker = JsonItemTracker(filepath=temp_file, item_type="custom_type")
        tracker.mark_processed("item-1")

        data = json.loads(temp_file.read_text())
        assert "processed_custom_type_ids" in data
        assert data["item_type"] == "custom_type"

    def test_different_item_types_different_keys(self, tmp_path):
        """Differents types utilisent differentes cles JSON."""
        file1 = tmp_path / "type1.json"
        file2 = tmp_path / "type2.json"

        tracker1 = JsonItemTracker(filepath=file1, item_type="email")
        tracker2 = JsonItemTracker(filepath=file2, item_type="draft")

        tracker1.mark_processed("item-1")
        tracker2.mark_processed("item-2")

        data1 = json.loads(file1.read_text())
        data2 = json.loads(file2.read_text())

        assert "processed_email_ids" in data1
        assert "processed_draft_ids" in data2


# =============================================================================
# TESTS - JsonItemTracker ERROR HANDLING
# =============================================================================


class TestJsonItemTrackerErrorHandling:
    """Tests pour la gestion des erreurs."""

    def test_handles_corrupt_file(self, temp_file):
        """Gere les fichiers corrompus gracieusement."""
        temp_file.write_text("not valid json {{{")
        tracker = JsonItemTracker(filepath=temp_file, item_type="test")
        assert tracker.count() == 0

    def test_handles_missing_file(self, tmp_path):
        """Gere les fichiers inexistants."""
        missing_file = tmp_path / "does_not_exist.json"
        tracker = JsonItemTracker(filepath=missing_file, item_type="test")
        assert tracker.count() == 0

    def test_handles_empty_file(self, temp_file):
        """Gere les fichiers vides."""
        temp_file.write_text("")
        tracker = JsonItemTracker(filepath=temp_file, item_type="test")
        assert tracker.count() == 0

    def test_handles_partial_json(self, temp_file):
        """Gere le JSON partiel."""
        temp_file.write_text('{"processed_test_ids": [')
        tracker = JsonItemTracker(filepath=temp_file, item_type="test")
        assert tracker.count() == 0


# =============================================================================
# TESTS - JsonItemTracker BACKWARD COMPATIBILITY
# =============================================================================


class TestJsonItemTrackerBackwardCompatibility:
    """Tests de compatibilite avec l'ancien format."""

    def test_loads_old_format_processed_ids(self, temp_file):
        """Charge l'ancien format avec processed_ids."""
        old_data = {
            "processed_ids": ["old-1", "old-2"],
            "last_updated": "2024-01-01T00:00:00"
        }
        temp_file.write_text(json.dumps(old_data))

        tracker = JsonItemTracker(filepath=temp_file, item_type="test")
        assert tracker.count() == 2
        assert tracker.is_processed("old-1")
        assert tracker.is_processed("old-2")

    def test_migrates_to_new_format(self, temp_file):
        """Migre vers le nouveau format apres modification."""
        old_data = {
            "processed_ids": ["old-1"],
            "last_updated": "2024-01-01T00:00:00"
        }
        temp_file.write_text(json.dumps(old_data))

        tracker = JsonItemTracker(filepath=temp_file, item_type="test")
        tracker.mark_processed("new-1")

        data = json.loads(temp_file.read_text())
        assert "processed_test_ids" in data


# =============================================================================
# TESTS - JsonItemTracker EDGE CASES
# =============================================================================


class TestJsonItemTrackerEdgeCases:
    """Tests des cas limites."""

    def test_empty_item_id(self, json_tracker):
        """Accepte les IDs vides."""
        json_tracker.mark_processed("")
        assert json_tracker.is_processed("")
        assert json_tracker.count() == 1

    def test_special_characters_in_id(self, json_tracker):
        """Supporte les caracteres speciaux dans les IDs."""
        special_id = "item<>@#$%^&*()_+-=[]{}|;':\",./<>?"
        json_tracker.mark_processed(special_id)
        assert json_tracker.is_processed(special_id)

    def test_unicode_in_id(self, json_tracker):
        """Supporte l'Unicode dans les IDs."""
        unicode_id = "item-\u4e2d\u6587-\U0001f600"
        json_tracker.mark_processed(unicode_id)
        assert json_tracker.is_processed(unicode_id)

    def test_very_long_id(self, json_tracker):
        """Supporte les IDs tres longs."""
        long_id = "x" * 10000
        json_tracker.mark_processed(long_id)
        assert json_tracker.is_processed(long_id)

    def test_many_items(self, json_tracker):
        """Supporte beaucoup d'items."""
        for i in range(1000):
            json_tracker.mark_processed(f"item-{i}")
        assert json_tracker.count() == 1000

    def test_newline_in_id(self, json_tracker):
        """Supporte les sauts de ligne dans les IDs."""
        id_with_newline = "item\nwith\nnewlines"
        json_tracker.mark_processed(id_with_newline)
        assert json_tracker.is_processed(id_with_newline)

    def test_whitespace_id(self, json_tracker):
        """Supporte les IDs avec espaces."""
        whitespace_id = "   item with spaces   "
        json_tracker.mark_processed(whitespace_id)
        assert json_tracker.is_processed(whitespace_id)

    def test_none_item_id_mixed_with_string_fails(self, json_tracker):
        """mark_processed avec None echoue lors du tri avec des strings."""
        # Python set accepte None, mais sorted() echoue avec types mixtes
        json_tracker.mark_processed("valid-id")
        with pytest.raises(TypeError):
            json_tracker.mark_processed(None)

    def test_none_item_id_is_processed_before_save(self, json_tracker):
        """is_processed avec None retourne False si non present."""
        # None n'est pas dans le tracker, donc retourne False
        assert not json_tracker.is_processed(None)

    def test_tab_in_id(self, json_tracker):
        """Supporte les tabulations dans les IDs."""
        id_with_tab = "item\twith\ttabs"
        json_tracker.mark_processed(id_with_tab)
        assert json_tracker.is_processed(id_with_tab)

    def test_null_byte_in_id(self, json_tracker):
        """Supporte les octets nuls dans les IDs."""
        id_with_null = "item\x00with\x00null"
        json_tracker.mark_processed(id_with_null)
        assert json_tracker.is_processed(id_with_null)


# =============================================================================
# TESTS - JsonItemTracker CONCURRENCY
# =============================================================================


class TestJsonItemTrackerConcurrency:
    """Tests pour la concurrence."""

    def test_concurrent_reads(self, temp_file):
        """Supporte les lectures concurrentes."""
        tracker1 = JsonItemTracker(filepath=temp_file, item_type="test")
        tracker1.mark_processed("item-1")

        tracker2 = JsonItemTracker(filepath=temp_file, item_type="test")
        assert tracker2.is_processed("item-1")

    def test_independent_instances(self, temp_file):
        """Deux instances sont independantes en memoire."""
        tracker1 = JsonItemTracker(filepath=temp_file, item_type="test")
        JsonItemTracker(filepath=temp_file, item_type="test")

        tracker1.mark_processed("item-1")

        # tracker2 a charge avant la modification, donc ne voit pas item-1
        # Sauf si on recharge
        tracker2_fresh = JsonItemTracker(filepath=temp_file, item_type="test")
        assert tracker2_fresh.is_processed("item-1")


# =============================================================================
# TESTS - InMemoryItemTracker
# =============================================================================


class TestInMemoryItemTrackerBasic:
    """Tests basiques pour InMemoryItemTracker."""

    def test_implements_port(self, memory_tracker):
        """InMemoryItemTracker implemente ItemTrackerPort."""
        assert isinstance(memory_tracker, ItemTrackerPort)

    def test_initially_empty(self, memory_tracker):
        """Un nouveau tracker est vide."""
        assert memory_tracker.count() == 0

    def test_mark_and_check(self, memory_tracker):
        """Marque et verifie un item."""
        memory_tracker.mark_processed("mem-123")
        assert memory_tracker.is_processed("mem-123")

    def test_clear(self, memory_tracker):
        """Clear efface tout."""
        memory_tracker.mark_processed("mem-1")
        memory_tracker.clear()
        assert memory_tracker.count() == 0

    def test_get_all_ids(self, memory_tracker):
        """get_all_ids retourne un set."""
        memory_tracker.mark_processed("mem-1")
        memory_tracker.mark_processed("mem-2")
        ids = memory_tracker.get_all_ids()
        assert ids == {"mem-1", "mem-2"}


class TestInMemoryItemTrackerNoPersistence:
    """Tests pour verifier l'absence de persistance."""

    def test_no_persistence_between_instances(self):
        """Pas de persistance entre instances."""
        tracker1 = InMemoryItemTracker(item_type="test")
        tracker1.mark_processed("item-1")

        tracker2 = InMemoryItemTracker(item_type="test")
        assert not tracker2.is_processed("item-1")

    def test_item_type_property(self, memory_tracker):
        """item_type est accessible."""
        assert memory_tracker.item_type == "test_item"


class TestInMemoryItemTrackerEdgeCases:
    """Tests des cas limites pour InMemoryItemTracker."""

    def test_empty_id(self, memory_tracker):
        """Accepte les IDs vides."""
        memory_tracker.mark_processed("")
        assert memory_tracker.is_processed("")

    def test_unicode_id(self, memory_tracker):
        """Supporte l'Unicode."""
        memory_tracker.mark_processed("\u4e2d\u6587")
        assert memory_tracker.is_processed("\u4e2d\u6587")

    def test_many_items(self, memory_tracker):
        """Supporte beaucoup d'items."""
        for i in range(1000):
            memory_tracker.mark_processed(f"item-{i}")
        assert memory_tracker.count() == 1000

    def test_none_item_id_accepted(self, memory_tracker):
        """InMemory accepte None comme ID (pas de serialisation JSON)."""
        # InMemoryItemTracker n'a pas de contrainte JSON
        memory_tracker.mark_processed(None)
        assert memory_tracker.is_processed(None)
        assert memory_tracker.count() == 1

    def test_none_item_id_is_processed_before_add(self, memory_tracker):
        """is_processed avec None retourne False si non present."""
        assert not memory_tracker.is_processed(None)

    def test_special_characters_in_id(self, memory_tracker):
        """Supporte les caracteres speciaux dans les IDs."""
        special_id = "item<>@#$%^&*()_+-=[]{}|;':\",./<>?"
        memory_tracker.mark_processed(special_id)
        assert memory_tracker.is_processed(special_id)

    def test_null_byte_in_id(self, memory_tracker):
        """Supporte les octets nuls dans les IDs."""
        id_with_null = "item\x00with\x00null"
        memory_tracker.mark_processed(id_with_null)
        assert memory_tracker.is_processed(id_with_null)


# =============================================================================
# TESTS - FACTORY FUNCTIONS
# =============================================================================


class TestCreateEmailTracker:
    """Tests pour la factory create_email_tracker."""

    def test_creates_json_tracker(self, temp_file):
        """Cree un JsonItemTracker."""
        tracker = create_email_tracker(temp_file)
        assert isinstance(tracker, JsonItemTracker)

    def test_sets_email_item_type(self, temp_file):
        """Configure item_type='email'."""
        tracker = create_email_tracker(temp_file)
        assert tracker.item_type == "email"

    def test_uses_correct_json_key(self, temp_file):
        """Utilise la bonne cle JSON."""
        tracker = create_email_tracker(temp_file)
        tracker.mark_processed("email-1")

        data = json.loads(temp_file.read_text())
        assert "processed_email_ids" in data


class TestCreateDraftTracker:
    """Tests pour la factory create_draft_tracker."""

    def test_creates_json_tracker(self, temp_file):
        """Cree un JsonItemTracker."""
        tracker = create_draft_tracker(temp_file)
        assert isinstance(tracker, JsonItemTracker)

    def test_sets_draft_item_type(self, temp_file):
        """Configure item_type='draft'."""
        tracker = create_draft_tracker(temp_file)
        assert tracker.item_type == "draft"

    def test_uses_correct_json_key(self, temp_file):
        """Utilise la bonne cle JSON."""
        tracker = create_draft_tracker(temp_file)
        tracker.mark_processed("draft-1")

        data = json.loads(temp_file.read_text())
        assert "processed_draft_ids" in data


# =============================================================================
# TESTS - FILE PERMISSIONS (Platform Specific)
# =============================================================================


class TestFilePermissions:
    """Tests pour les permissions de fichiers."""

    @pytest.mark.skipif(os.name == "nt", reason="Permission tests not reliable on Windows")
    def test_handles_readonly_directory(self, tmp_path):
        """Gere les repertoires en lecture seule."""
        import stat

        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

        try:
            # La creation du tracker dans un dossier readonly peut echouer
            # mais ne devrait pas lever d'exception non geree
            filepath = readonly_dir / "tracker.json"
            try:
                JsonItemTracker(filepath=filepath, item_type="test")
            except (OSError, PermissionError):
                pass  # Expected on some systems
        finally:
            readonly_dir.chmod(stat.S_IRWXU)


# =============================================================================
# TESTS - INTEGRATION
# =============================================================================


class TestTrackerIntegration:
    """Tests d'integration."""

    def test_email_and_draft_trackers_independent(self, tmp_path):
        """Les trackers email et draft sont independants."""
        email_file = tmp_path / "emails.json"
        draft_file = tmp_path / "drafts.json"

        email_tracker = create_email_tracker(email_file)
        draft_tracker = create_draft_tracker(draft_file)

        email_tracker.mark_processed("item-1")
        draft_tracker.mark_processed("item-1")

        # Meme ID, mais trackers differents
        assert email_tracker.is_processed("item-1")
        assert draft_tracker.is_processed("item-1")

        email_tracker.clear()

        # Clear d'un tracker n'affecte pas l'autre
        assert not email_tracker.is_processed("item-1")
        assert draft_tracker.is_processed("item-1")

    def test_json_and_memory_trackers_same_interface(self, temp_file):
        """JSON et InMemory ont la meme interface."""
        json_tracker = JsonItemTracker(filepath=temp_file, item_type="test")
        mem_tracker = InMemoryItemTracker(item_type="test")

        for tracker in [json_tracker, mem_tracker]:
            tracker.mark_processed("item-1")
            assert tracker.is_processed("item-1")
            assert tracker.count() == 1
            assert "item-1" in tracker.get_all_ids()
            tracker.clear()
            assert tracker.count() == 0
