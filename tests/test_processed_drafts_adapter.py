# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les adapters ProcessedDrafts.

Ce module teste:
1. JsonProcessedDraftsTracker - herite de JsonItemTracker avec item_type='draft'
2. InMemoryProcessedDraftsTracker - herite de InMemoryItemTracker
3. Compatibilite avec ItemTrackerPort
4. Integration avec le systeme de tracking de brouillons

TDD: Tests ecrits pour valider l'implementation.
Clean Architecture: Infrastructure layer (Adapters).
"""

import json
import pytest
from pathlib import Path

from app.domain.ports.item_tracker_port import (
    ItemTrackerPort,
    ProcessedDraftsTrackerPort,
)
from app.infrastructure.adapters.processed_drafts_adapter import (
    JsonProcessedDraftsTracker,
    InMemoryProcessedDraftsTracker,
)
from app.infrastructure.adapters.item_tracker_adapter import (
    JsonItemTracker,
    InMemoryItemTracker,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_file(tmp_path) -> Path:
    """Cree un fichier temporaire pour les tests."""
    return tmp_path / "processed_drafts.json"


@pytest.fixture
def json_drafts_tracker(temp_file) -> JsonProcessedDraftsTracker:
    """Cree un tracker JSON pour les brouillons."""
    return JsonProcessedDraftsTracker(filepath=temp_file)


@pytest.fixture
def memory_drafts_tracker() -> InMemoryProcessedDraftsTracker:
    """Cree un tracker en memoire pour les brouillons."""
    return InMemoryProcessedDraftsTracker()


# =============================================================================
# TESTS - JsonProcessedDraftsTracker INHERITANCE
# =============================================================================


class TestJsonProcessedDraftsTrackerInheritance:
    """Tests pour l'heritage de JsonProcessedDraftsTracker."""

    def test_inherits_from_json_item_tracker(self, json_drafts_tracker):
        """JsonProcessedDraftsTracker herite de JsonItemTracker."""
        assert isinstance(json_drafts_tracker, JsonItemTracker)

    def test_implements_item_tracker_port(self, json_drafts_tracker):
        """Implemente ItemTrackerPort."""
        assert isinstance(json_drafts_tracker, ItemTrackerPort)

    def test_implements_processed_drafts_tracker_port(self, json_drafts_tracker):
        """Implemente ProcessedDraftsTrackerPort (alias)."""
        assert isinstance(json_drafts_tracker, ProcessedDraftsTrackerPort)

    def test_item_type_is_draft(self, json_drafts_tracker):
        """item_type est 'draft'."""
        assert json_drafts_tracker.item_type == "draft"


# =============================================================================
# TESTS - JsonProcessedDraftsTracker BASIC OPERATIONS
# =============================================================================


class TestJsonProcessedDraftsTrackerBasicOperations:
    """Tests pour les operations basiques."""

    def test_initially_empty(self, json_drafts_tracker):
        """Un nouveau tracker est vide."""
        assert json_drafts_tracker.count() == 0
        assert json_drafts_tracker.get_all_ids() == set()

    def test_mark_processed(self, json_drafts_tracker):
        """mark_processed ajoute un ID de brouillon."""
        json_drafts_tracker.mark_processed("draft-001")
        assert json_drafts_tracker.is_processed("draft-001")
        assert json_drafts_tracker.count() == 1

    def test_is_processed_returns_false_for_unknown(self, json_drafts_tracker):
        """is_processed retourne False pour un brouillon inconnu."""
        assert not json_drafts_tracker.is_processed("unknown-draft")

    def test_clear(self, json_drafts_tracker):
        """clear supprime tous les brouillons traites."""
        json_drafts_tracker.mark_processed("draft-1")
        json_drafts_tracker.mark_processed("draft-2")
        json_drafts_tracker.clear()
        assert json_drafts_tracker.count() == 0

    def test_get_all_ids(self, json_drafts_tracker):
        """get_all_ids retourne tous les IDs."""
        json_drafts_tracker.mark_processed("draft-1")
        json_drafts_tracker.mark_processed("draft-2")
        ids = json_drafts_tracker.get_all_ids()
        assert ids == {"draft-1", "draft-2"}


# =============================================================================
# TESTS - JsonProcessedDraftsTracker PERSISTENCE
# =============================================================================


class TestJsonProcessedDraftsTrackerPersistence:
    """Tests pour la persistance."""

    def test_persists_on_disk(self, temp_file, json_drafts_tracker):
        """Les donnees persistent sur disque."""
        json_drafts_tracker.mark_processed("draft-123")
        assert temp_file.exists()

    def test_reloads_from_disk(self, temp_file):
        """Les donnees sont rechargees depuis le disque."""
        tracker1 = JsonProcessedDraftsTracker(filepath=temp_file)
        tracker1.mark_processed("draft-123")

        tracker2 = JsonProcessedDraftsTracker(filepath=temp_file)
        assert tracker2.is_processed("draft-123")

    def test_file_uses_draft_key(self, temp_file, json_drafts_tracker):
        """Le fichier utilise la cle processed_draft_ids."""
        json_drafts_tracker.mark_processed("draft-1")

        data = json.loads(temp_file.read_text())
        assert "processed_draft_ids" in data
        assert "draft-1" in data["processed_draft_ids"]
        assert data["item_type"] == "draft"


# =============================================================================
# TESTS - JsonProcessedDraftsTracker EDGE CASES
# =============================================================================


class TestJsonProcessedDraftsTrackerEdgeCases:
    """Tests des cas limites."""

    def test_empty_draft_id(self, json_drafts_tracker):
        """Accepte les IDs vides."""
        json_drafts_tracker.mark_processed("")
        assert json_drafts_tracker.is_processed("")

    def test_special_characters_in_id(self, json_drafts_tracker):
        """Supporte les caracteres speciaux dans les IDs."""
        special_id = "draft/with/slashes:and:colons"
        json_drafts_tracker.mark_processed(special_id)
        assert json_drafts_tracker.is_processed(special_id)

    def test_unicode_in_id(self, json_drafts_tracker):
        """Supporte l'Unicode dans les IDs."""
        unicode_id = "brouillon-\u00e9bauche-\u4e2d\u6587"
        json_drafts_tracker.mark_processed(unicode_id)
        assert json_drafts_tracker.is_processed(unicode_id)

    def test_very_long_id(self, json_drafts_tracker):
        """Supporte les IDs tres longs."""
        long_id = "draft-" + "x" * 5000
        json_drafts_tracker.mark_processed(long_id)
        assert json_drafts_tracker.is_processed(long_id)

    def test_idempotent_marking(self, json_drafts_tracker):
        """Marquer plusieurs fois ne duplique pas."""
        json_drafts_tracker.mark_processed("draft-1")
        json_drafts_tracker.mark_processed("draft-1")
        json_drafts_tracker.mark_processed("draft-1")
        assert json_drafts_tracker.count() == 1


# =============================================================================
# TESTS - InMemoryProcessedDraftsTracker INHERITANCE
# =============================================================================


class TestInMemoryProcessedDraftsTrackerInheritance:
    """Tests pour l'heritage de InMemoryProcessedDraftsTracker."""

    def test_inherits_from_in_memory_item_tracker(self, memory_drafts_tracker):
        """InMemoryProcessedDraftsTracker herite de InMemoryItemTracker."""
        assert isinstance(memory_drafts_tracker, InMemoryItemTracker)

    def test_implements_item_tracker_port(self, memory_drafts_tracker):
        """Implemente ItemTrackerPort."""
        assert isinstance(memory_drafts_tracker, ItemTrackerPort)

    def test_item_type_is_draft(self, memory_drafts_tracker):
        """item_type est 'draft'."""
        assert memory_drafts_tracker.item_type == "draft"


# =============================================================================
# TESTS - InMemoryProcessedDraftsTracker BASIC OPERATIONS
# =============================================================================


class TestInMemoryProcessedDraftsTrackerBasicOperations:
    """Tests pour les operations basiques en memoire."""

    def test_initially_empty(self, memory_drafts_tracker):
        """Un nouveau tracker est vide."""
        assert memory_drafts_tracker.count() == 0

    def test_mark_and_check(self, memory_drafts_tracker):
        """Marque et verifie un brouillon."""
        memory_drafts_tracker.mark_processed("draft-mem-1")
        assert memory_drafts_tracker.is_processed("draft-mem-1")

    def test_clear(self, memory_drafts_tracker):
        """Clear efface tout."""
        memory_drafts_tracker.mark_processed("draft-1")
        memory_drafts_tracker.clear()
        assert memory_drafts_tracker.count() == 0

    def test_get_all_ids(self, memory_drafts_tracker):
        """get_all_ids retourne tous les IDs."""
        memory_drafts_tracker.mark_processed("draft-1")
        memory_drafts_tracker.mark_processed("draft-2")
        ids = memory_drafts_tracker.get_all_ids()
        assert ids == {"draft-1", "draft-2"}


# =============================================================================
# TESTS - InMemoryProcessedDraftsTracker NO PERSISTENCE
# =============================================================================


class TestInMemoryProcessedDraftsTrackerNoPersistence:
    """Tests pour l'absence de persistance."""

    def test_no_persistence_between_instances(self):
        """Pas de persistance entre instances."""
        tracker1 = InMemoryProcessedDraftsTracker()
        tracker1.mark_processed("draft-1")

        tracker2 = InMemoryProcessedDraftsTracker()
        assert not tracker2.is_processed("draft-1")


# =============================================================================
# TESTS - INTEGRATION WITH DAEMON
# =============================================================================


class TestDraftsTrackerDaemonIntegration:
    """Tests d'integration avec le workflow du daemon."""

    def test_tracks_multiple_drafts(self, json_drafts_tracker):
        """Suit plusieurs brouillons."""
        drafts = ["draft-001", "draft-002", "draft-003"]
        for draft_id in drafts:
            json_drafts_tracker.mark_processed(draft_id)

        assert json_drafts_tracker.count() == 3
        for draft_id in drafts:
            assert json_drafts_tracker.is_processed(draft_id)

    def test_skips_already_processed(self, json_drafts_tracker):
        """Permet d'ignorer les brouillons deja traites."""
        json_drafts_tracker.mark_processed("draft-001")

        # Simule le workflow du daemon
        draft_ids = ["draft-001", "draft-002"]  # draft-001 deja traite
        new_to_process = [
            d for d in draft_ids
            if not json_drafts_tracker.is_processed(d)
        ]

        assert new_to_process == ["draft-002"]

    def test_workflow_mark_after_completion(self, json_drafts_tracker):
        """Workflow: marquer apres completion reussie."""
        draft_id = "draft-user-request"

        # 1. Verifier non traite
        assert not json_drafts_tracker.is_processed(draft_id)

        # 2. Simuler le traitement
        # (dans le vrai code: DraftCompletionAgent.complete())

        # 3. Marquer comme traite
        json_drafts_tracker.mark_processed(draft_id)

        # 4. Ne sera plus retraite
        assert json_drafts_tracker.is_processed(draft_id)


# =============================================================================
# TESTS - COMPATIBILITY WITH EMAILS TRACKER
# =============================================================================


class TestDraftsTrackerCompatibilityWithEmails:
    """Tests de compatibilite avec le tracker d'emails."""

    def test_same_interface_as_emails_tracker(self, json_drafts_tracker):
        """Meme interface que le tracker d'emails."""
        # Ces methodes existent aussi sur ProcessedEmailsTracker
        assert hasattr(json_drafts_tracker, "is_processed")
        assert hasattr(json_drafts_tracker, "mark_processed")
        assert hasattr(json_drafts_tracker, "count")
        assert hasattr(json_drafts_tracker, "get_all_ids")
        assert hasattr(json_drafts_tracker, "clear")

    def test_independent_from_emails_tracker(self, tmp_path):
        """Independent du tracker d'emails."""
        from app.infrastructure.adapters.item_tracker_adapter import create_email_tracker

        email_file = tmp_path / "emails.json"
        draft_file = tmp_path / "drafts.json"

        email_tracker = create_email_tracker(email_file)
        draft_tracker = JsonProcessedDraftsTracker(filepath=draft_file)

        # Meme ID dans les deux trackers
        email_tracker.mark_processed("msg-001")
        draft_tracker.mark_processed("msg-001")

        # Independants
        email_tracker.clear()
        assert not email_tracker.is_processed("msg-001")
        assert draft_tracker.is_processed("msg-001")  # Pas affecte


# =============================================================================
# TESTS - ERROR SCENARIOS
# =============================================================================


class TestDraftsTrackerErrorScenarios:
    """Tests pour les scenarios d'erreur."""

    def test_handles_corrupt_file(self, temp_file):
        """Gere les fichiers corrompus."""
        temp_file.write_text("{invalid json")
        tracker = JsonProcessedDraftsTracker(filepath=temp_file)
        assert tracker.count() == 0

    def test_handles_missing_directory(self, tmp_path):
        """Cree le repertoire si necessaire."""
        nested_file = tmp_path / "sub" / "dir" / "drafts.json"
        tracker = JsonProcessedDraftsTracker(filepath=nested_file)
        tracker.mark_processed("draft-1")
        assert nested_file.exists()

    def test_recovers_from_empty_file(self, temp_file):
        """Recupere d'un fichier vide."""
        temp_file.write_text("")
        tracker = JsonProcessedDraftsTracker(filepath=temp_file)
        tracker.mark_processed("draft-1")
        assert tracker.count() == 1


# =============================================================================
# TESTS - FIXTURE USABLE IN OTHER TESTS
# =============================================================================


class TestDraftsTrackerAsFixture:
    """Tests pour l'usage comme fixture dans d'autres tests."""

    def test_memory_tracker_for_fast_tests(self, memory_drafts_tracker):
        """Le tracker en memoire est adapte aux tests rapides."""
        # Pas de I/O disque
        for i in range(100):
            memory_drafts_tracker.mark_processed(f"draft-{i}")
        assert memory_drafts_tracker.count() == 100

    def test_json_tracker_for_integration_tests(self, json_drafts_tracker):
        """Le tracker JSON est adapte aux tests d'integration."""
        json_drafts_tracker.mark_processed("draft-integration")
        assert json_drafts_tracker.is_processed("draft-integration")


# =============================================================================
# TESTS - CLEAN ARCHITECTURE COMPLIANCE
# =============================================================================


class TestDraftsTrackerCleanArchitecture:
    """Tests de conformite Clean Architecture."""

    def test_adapter_in_infrastructure_layer(self):
        """L'adapter est dans la couche Infrastructure."""
        import app.infrastructure.adapters.processed_drafts_adapter as module
        assert "infrastructure" in module.__file__

    def test_depends_on_domain_port(self, json_drafts_tracker):
        """Depend du port du domaine."""
        assert isinstance(json_drafts_tracker, ItemTrackerPort)

    def test_no_business_logic_in_adapter(self, json_drafts_tracker):
        """L'adapter ne contient pas de logique metier."""
        # Les methodes sont simples: add/remove/check
        # Pas de validation complexe ni de regles metier
        json_drafts_tracker.mark_processed("test")
        assert json_drafts_tracker.is_processed("test")
