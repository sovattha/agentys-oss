# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module pending_draft_store.

Ce module teste l'implémentation InMemoryPendingDraftStore
qui gère les brouillons en attente de validation.
"""

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

import app.infrastructure.pending_draft_store as pds
from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
from app.infrastructure.pending_draft_store import (
    InMemoryPendingDraftStore,
    get_pending_draft_store,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_persist_path(tmp_path):
    """Crée un chemin temporaire pour la persistance."""
    return str(tmp_path / "pending_drafts.json")


@pytest.fixture
def store(temp_persist_path):
    """Crée une instance de store avec chemin temporaire."""
    return InMemoryPendingDraftStore(persist_path=temp_persist_path)


@pytest.fixture
def sample_draft():
    """Crée un brouillon sample."""
    return PendingDraft(
        id="draft-123",
        email_id="email-456",
        email_sender="sender@example.com",
        email_sender_name="Sender Name",
        email_subject="Test Subject",
        email_body="Test body content",
        email_received_at="2025-01-15T10:00:00",
        draft_subject="Re: Test Subject",
        draft_body="Draft body content",
        draft_v1="First version",
        critique="Critique content",
        classification="support",
        priority=60,
        confidence=0.9,
        status=PendingDraftStatus.PENDING,
    )


@pytest.fixture
def multiple_drafts():
    """Crée plusieurs brouillons pour les tests."""
    drafts = []
    for i in range(5):
        draft = PendingDraft(
            id=f"draft-{i}",
            email_id=f"email-{i}",
            email_sender=f"sender{i}@example.com",
            email_subject=f"Subject {i}",
            draft_subject=f"Re: Subject {i}",
            draft_body=f"Body {i}",
            status=PendingDraftStatus.PENDING if i < 3 else PendingDraftStatus.VALIDATED,
        )
        drafts.append(draft)
    return drafts


# ============================================================================
# Tests Initialization
# ============================================================================


class TestInMemoryPendingDraftStoreInit:
    """Tests pour l'initialisation du store."""

    def test_init_creates_empty_store(self, temp_persist_path):
        """Test que le store est initialement vide."""
        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        assert store._store == {}

    def test_init_with_default_persist_path(self, tmp_path, monkeypatch):
        """Le chemin par défaut vit sous DATA_DIR (co-localisé avec
        reminders.json et les autres stores JSON), plus jamais sous
        ~/.agentys. Voir audit 2026-05-26 (orphan snoozed follow-up drafts)."""
        monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
        # Legacy absent → pas de migration parasite qui créerait le fichier.
        monkeypatch.setattr(
            pds, "_LEGACY_PERSIST_PATH", str(tmp_path / "absent" / "pending_drafts.json")
        )
        store = InMemoryPendingDraftStore()
        assert store._persist_path == str(tmp_path / "pending_drafts.json")

    def test_init_with_custom_persist_path(self, temp_persist_path):
        """Test l'initialisation avec un chemin personnalisé."""
        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        assert store._persist_path == temp_persist_path

    def test_init_creates_lock(self, temp_persist_path):
        """Test que le store crée un verrou pour le thread-safety."""
        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        assert isinstance(store._lock, type(threading.Lock()))


# ============================================================================
# Tests Persist-path co-location (audit 2026-05-26)
# ============================================================================


class TestPersistPathColocation:
    """Le store des pending drafts doit partager la racine DATA_DIR avec
    reminders.json (et tous les autres stores JSON), pas s'ancrer sous
    ~/.agentys (HOME-relatif). Le split de racines orphelinait les brouillons
    de relance snoozés : leur reminder draft_followup (DATA_DIR/reminders.json)
    survivait alors que la ligne de draft (~/.agentys) disparaissait quand HOME
    changeait entre deux lancements (dev vs sidecar packagé) → onglet "Plus
    tard" vide."""

    def test_default_path_under_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
        monkeypatch.setattr(
            pds, "_LEGACY_PERSIST_PATH", str(tmp_path / "absent" / "pending_drafts.json")
        )
        store = InMemoryPendingDraftStore()
        assert store._persist_path == str(tmp_path / "pending_drafts.json")

    def test_default_path_not_under_home_agentys(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
        monkeypatch.setattr(
            pds, "_LEGACY_PERSIST_PATH", str(tmp_path / "absent" / "pending_drafts.json")
        )
        store = InMemoryPendingDraftStore()
        legacy_dir = os.path.join(os.path.expanduser("~"), ".agentys")
        assert os.path.abspath(legacy_dir) not in os.path.abspath(store._persist_path)

    def test_default_persist_path_helper_reads_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
        assert pds._default_persist_path() == str(tmp_path / "pending_drafts.json")

    def test_legacy_store_migrated_on_init(self, tmp_path, monkeypatch, sample_draft):
        """Legacy présent + canonical absent → drafts migrés et chargés."""
        new_dir = tmp_path / "data"
        new_dir.mkdir()
        legacy = tmp_path / "home_agentys" / "pending_drafts.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps([sample_draft.to_dict()]), encoding="utf-8")
        monkeypatch.setattr("app.config.DATA_DIR", new_dir)
        monkeypatch.setattr(pds, "_LEGACY_PERSIST_PATH", str(legacy))

        store = InMemoryPendingDraftStore()

        assert sample_draft.id in store._store
        assert os.path.exists(str(new_dir / "pending_drafts.json"))
        # Le legacy reste intact (copy, pas move) — filet de sécurité.
        assert os.path.exists(str(legacy))

    def test_legacy_migration_skipped_when_canonical_exists(
        self, tmp_path, monkeypatch, sample_draft
    ):
        """Canonical présent → on NE l'écrase PAS avec le legacy."""
        new_dir = tmp_path / "data"
        new_dir.mkdir()
        (new_dir / "pending_drafts.json").write_text(json.dumps([]), encoding="utf-8")
        legacy = tmp_path / "home_agentys" / "pending_drafts.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps([sample_draft.to_dict()]), encoding="utf-8")
        monkeypatch.setattr("app.config.DATA_DIR", new_dir)
        monkeypatch.setattr(pds, "_LEGACY_PERSIST_PATH", str(legacy))

        store = InMemoryPendingDraftStore()

        assert store._store == {}

    def test_legacy_migration_noop_when_legacy_absent(self, tmp_path, monkeypatch):
        """Legacy absent → init sans crash, store vide."""
        new_dir = tmp_path / "data"
        new_dir.mkdir()
        monkeypatch.setattr("app.config.DATA_DIR", new_dir)
        monkeypatch.setattr(
            pds, "_LEGACY_PERSIST_PATH", str(tmp_path / "nope" / "pending_drafts.json")
        )

        store = InMemoryPendingDraftStore()

        assert store._store == {}

    def test_custom_persist_path_skips_migration(
        self, tmp_path, monkeypatch, sample_draft
    ):
        """Un persist_path explicite (tests, isolation) NE déclenche JAMAIS la
        migration legacy."""
        legacy = tmp_path / "home_agentys" / "pending_drafts.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps([sample_draft.to_dict()]), encoding="utf-8")
        monkeypatch.setattr(pds, "_LEGACY_PERSIST_PATH", str(legacy))
        custom = str(tmp_path / "custom" / "pending_drafts.json")

        store = InMemoryPendingDraftStore(persist_path=custom)

        assert store._store == {}
        assert not os.path.exists(custom)

    def test_stores_colocated_under_data_dir(self):
        """Invariant : store pending-drafts ET reminder_service dérivent de la
        MÊME racine app.config.DATA_DIR."""
        import app.config
        from app.services import reminder_service

        assert Path(pds._default_persist_path()).parent == app.config.DATA_DIR
        assert reminder_service._REMINDERS_FILE.parent == app.config.DATA_DIR

    def test_reset_all_data_targets_pending_drafts_under_data_dir(self):
        """Le store ayant migré vers DATA_DIR, /reset-all-data doit le purger
        à son NOUVEL emplacement — sinon un reset complet laisse des drafts
        obsolètes. Garde-fou de régression du déplacement de chemin."""
        from app.api import routes_reset

        assert "pending_drafts.json" in routes_reset.DATA_DIR_FILES


# ============================================================================
# Tests Load from Disk
# ============================================================================


class TestLoadFromDisk:
    """Tests pour le chargement depuis le disque."""

    def test_load_from_empty_path(self, temp_persist_path):
        """Test le chargement quand le fichier n'existe pas."""
        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        assert store._store == {}

    def test_load_from_existing_file(self, temp_persist_path, sample_draft):
        """Test le chargement depuis un fichier existant."""
        # Écrire des données dans le fichier
        os.makedirs(os.path.dirname(temp_persist_path), exist_ok=True)
        with open(temp_persist_path, "w", encoding="utf-8") as f:
            json.dump([sample_draft.to_dict()], f)

        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        assert len(store._store) == 1
        assert sample_draft.id in store._store

    def test_load_from_corrupted_file(self, temp_persist_path):
        """Test le chargement depuis un fichier corrompu."""
        os.makedirs(os.path.dirname(temp_persist_path), exist_ok=True)
        with open(temp_persist_path, "w", encoding="utf-8") as f:
            f.write("not valid json{{{")

        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        assert store._store == {}

    def test_load_from_empty_file(self, temp_persist_path):
        """Test le chargement depuis un fichier vide."""
        os.makedirs(os.path.dirname(temp_persist_path), exist_ok=True)
        with open(temp_persist_path, "w", encoding="utf-8") as f:
            f.write("")

        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        assert store._store == {}

    def test_load_multiple_drafts(self, temp_persist_path, multiple_drafts):
        """Test le chargement de plusieurs brouillons."""
        os.makedirs(os.path.dirname(temp_persist_path), exist_ok=True)
        with open(temp_persist_path, "w", encoding="utf-8") as f:
            json.dump([d.to_dict() for d in multiple_drafts], f)

        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        assert len(store._store) == len(multiple_drafts)


# ============================================================================
# Tests Save to Disk
# ============================================================================


class TestSaveToDisk:
    """Tests pour la sauvegarde sur disque."""

    def test_save_creates_directory_if_missing(self, tmp_path):
        """Test que la sauvegarde crée le répertoire parent."""
        persist_path = str(tmp_path / "subdir" / "pending_drafts.json")
        store = InMemoryPendingDraftStore(persist_path=persist_path)
        sample = PendingDraft(id="test-1", email_id="email-1")
        store.add(sample)
        store.flush()
        assert os.path.exists(persist_path)

    def test_save_writes_valid_json(self, temp_persist_path, sample_draft):
        """Test que la sauvegarde écrit un JSON valide."""
        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        store.add(sample_draft)
        store.flush()

        with open(temp_persist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["id"] == sample_draft.id

    def test_save_with_unicode_content(self, temp_persist_path):
        """Test la sauvegarde avec du contenu unicode."""
        draft = PendingDraft(
            id="unicode-1",
            email_id="email-u",
            email_subject="Sujet avec accents éèêë",
            draft_body="Contenu avec emojis 🎉 et caractères spéciaux ñ",
        )
        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        store.add(draft)
        store.flush()

        with open(temp_persist_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "éèêë" in content
        assert "🎉" in content

    def test_save_metadata_only_drops_source_content_and_intermediate_artifacts(
        self,
        temp_persist_path,
        monkeypatch,
    ):
        """pending_drafts.json must not retain source email bodies in cloud mode."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        draft = PendingDraft(
            id="privacy-1",
            email_id="email-privacy",
            email_body="PRIVATE SOURCE EMAIL BODY",
            conversation_history=[{"body": "PRIVATE THREAD BODY"}],
            draft_subject="Re: Privacy",
            draft_body="User-facing generated draft",
            draft_v1="PRIVATE FIRST VERSION",
            critique="PRIVATE CRITIQUE WITH SOURCE QUOTE",
            pipeline_summary="PRIVATE PIPELINE SUMMARY FROM SOURCE BODY",
        )

        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        store.add(draft)
        store.flush()

        with open(temp_persist_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        persisted = data[0]
        assert persisted["email_body"] == ""
        assert persisted["conversation_history"] == []
        assert persisted["draft_v1"] == ""
        assert persisted["critique"] == ""
        assert persisted["pipeline_summary"] is None
        assert persisted["draft_body"] == "User-facing generated draft"

    def test_save_legacy_full_cache_keeps_source_content_for_local_migration(
        self,
        temp_persist_path,
        monkeypatch,
    ):
        """legacy_full_cache preserves the historical file shape explicitly."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        draft = PendingDraft(
            id="legacy-1",
            email_id="email-legacy",
            email_body="SOURCE EMAIL BODY",
            conversation_history=[{"body": "THREAD BODY"}],
            draft_body="Generated draft",
            draft_v1="First version",
            critique="Critique",
            pipeline_summary="Pipeline summary",
        )

        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        store.add(draft)
        store.flush()

        with open(temp_persist_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        persisted = data[0]
        assert persisted["email_body"] == "SOURCE EMAIL BODY"
        assert persisted["conversation_history"] == [{"body": "THREAD BODY"}]
        assert persisted["draft_v1"] == "First version"
        assert persisted["critique"] == "Critique"
        assert persisted["pipeline_summary"] == "Pipeline summary"

    def test_load_metadata_only_sanitizes_legacy_disk_content(
        self,
        temp_persist_path,
        monkeypatch,
    ):
        """Legacy pending_drafts.json content must not rehydrate source text."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        os.makedirs(os.path.dirname(temp_persist_path), exist_ok=True)
        with open(temp_persist_path, "w", encoding="utf-8") as f:
            json.dump([
                {
                    "id": "legacy-privacy",
                    "email_id": "email-privacy",
                    "email_body": "LEGACY SOURCE BODY",
                    "conversation_history": [{"body": "LEGACY THREAD BODY"}],
                    "draft_body": "User-facing draft",
                    "draft_v1": "LEGACY DRAFT V1",
                    "critique": "LEGACY CRITIQUE",
                    "pipeline_summary": "LEGACY SUMMARY FROM BODY",
                }
            ], f)

        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        draft = store.get_by_id("legacy-privacy")

        assert draft is not None
        assert draft.email_body == ""
        assert draft.conversation_history == []
        assert draft.draft_v1 == ""
        assert draft.critique == ""
        assert draft.pipeline_summary is None
        assert draft.draft_body == "User-facing draft"

    def test_save_handles_error_gracefully(self, store, sample_draft):
        """Test que la sauvegarde gère les erreurs gracieusement."""
        store.add(sample_draft)
        # Simuler une erreur de permission
        with patch("builtins.open", side_effect=PermissionError("No permission")):
            # Ne devrait pas lever d'exception
            store._save_to_disk()


# ============================================================================
# Tests Add
# ============================================================================


class TestAdd:
    """Tests pour l'ajout de brouillons."""

    def test_add_returns_draft_id(self, store, sample_draft):
        """Test que add retourne l'ID du brouillon."""
        draft_id = store.add(sample_draft)
        assert draft_id == sample_draft.id

    def test_add_stores_draft(self, store, sample_draft):
        """Test que add stocke le brouillon."""
        store.add(sample_draft)
        assert sample_draft.id in store._store
        assert store._store[sample_draft.id] == sample_draft

    def test_add_persists_to_disk(self, store, sample_draft):
        """Test que add persiste sur le disque."""
        store.add(sample_draft)
        store.flush()
        assert os.path.exists(store._persist_path)

    def test_add_multiple_drafts(self, store, multiple_drafts):
        """Test l'ajout de plusieurs brouillons."""
        for draft in multiple_drafts:
            store.add(draft)
        assert len(store._store) == len(multiple_drafts)

    def test_add_replaces_existing_draft(self, store, sample_draft):
        """Test que add remplace un brouillon existant."""
        store.add(sample_draft)
        modified = PendingDraft(
            id=sample_draft.id,
            email_id="new-email",
            draft_body="Modified content",
        )
        store.add(modified)
        assert store._store[sample_draft.id].draft_body == "Modified content"

    def test_add_syncs_shared_pending_draft(self, store):
        """Test que add publie aussi le brouillon pour les workers RQ séparés."""
        draft = PendingDraft(
            id="draft-shared",
            email_id="email-shared",
            account_id="14",
            draft_body="Contenu partagé",
            status=PendingDraftStatus.PENDING,
        )

        with patch("app.infrastructure.draft_job_queue.store_shared_pending_draft") as shared_store:
            store.add(draft)

        shared_store.assert_called_once()
        assert shared_store.call_args.kwargs["draft_id"] == "draft-shared"
        assert shared_store.call_args.kwargs["email_id"] == "email-shared"
        assert shared_store.call_args.kwargs["account_id"] == "14"


# ============================================================================
# Tests Get By ID
# ============================================================================


class TestGetById:
    """Tests pour la récupération par ID."""

    def test_get_by_id_existing(self, store, sample_draft):
        """Test la récupération d'un brouillon existant."""
        store.add(sample_draft)
        result = store.get_by_id(sample_draft.id)
        assert result == sample_draft

    def test_get_by_id_non_existing(self, store):
        """Test la récupération d'un brouillon inexistant."""
        result = store.get_by_id("non-existing-id")
        assert result is None

    def test_get_by_id_empty_string(self, store):
        """Test la récupération avec ID vide."""
        result = store.get_by_id("")
        assert result is None

    def test_get_by_id_hydrates_shared_pending_draft(self, store):
        """Test la récupération d'un brouillon créé par un worker RQ."""
        payload = PendingDraft(
            id="draft-redis",
            email_id="email-redis",
            account_id="14",
            draft_body="Réponse Redis",
            status=PendingDraftStatus.PENDING,
        ).to_dict()

        with patch(
            "app.infrastructure.draft_job_queue.get_shared_pending_draft_by_id",
            return_value=payload,
        ) as shared_lookup:
            result = store.get_by_id("draft-redis")

        assert result is not None
        assert result.id == "draft-redis"
        assert result.draft_body == "Réponse Redis"
        assert store._store["draft-redis"].email_id == "email-redis"
        shared_lookup.assert_called_once_with("draft-redis")


# ============================================================================
# Tests Get Pending
# ============================================================================


class TestGetPending:
    """Tests pour la récupération des brouillons en attente."""

    def test_get_pending_returns_only_pending(self, store, multiple_drafts):
        """Test que seuls les brouillons PENDING sont retournés."""
        for draft in multiple_drafts:
            store.add(draft)
        pending = store.get_pending()
        assert all(d.status == PendingDraftStatus.PENDING for d in pending)
        assert len(pending) == 3  # 3 pending dans multiple_drafts

    def test_get_pending_with_limit(self, store, multiple_drafts):
        """Test la limite de résultats."""
        for draft in multiple_drafts:
            store.add(draft)
        pending = store.get_pending(limit=2)
        assert len(pending) <= 2

    def test_get_pending_sorted_by_created_at(self, store):
        """Test que les résultats sont triés par date de création."""
        draft1 = PendingDraft(
            id="d1",
            email_id="e1",
            created_at="2025-01-01T10:00:00",
        )
        draft2 = PendingDraft(
            id="d2",
            email_id="e2",
            created_at="2025-01-02T10:00:00",
        )
        store.add(draft1)
        store.add(draft2)
        pending = store.get_pending()
        # Plus récent en premier
        assert pending[0].id == "d2"
        assert pending[1].id == "d1"

    def test_get_pending_empty_store(self, store):
        """Test la récupération depuis un store vide."""
        pending = store.get_pending()
        assert pending == []


# ============================================================================
# Tests Get All
# ============================================================================


class TestGetAll:
    """Tests pour la récupération de tous les brouillons."""

    def test_get_all_returns_all_drafts(self, store, multiple_drafts):
        """Test que tous les brouillons sont retournés."""
        for draft in multiple_drafts:
            store.add(draft)
        all_drafts = store.get_all()
        assert len(all_drafts) == len(multiple_drafts)

    def test_get_all_with_limit(self, store, multiple_drafts):
        """Test la limite de résultats."""
        for draft in multiple_drafts:
            store.add(draft)
        all_drafts = store.get_all(limit=2)
        assert len(all_drafts) == 2

    def test_get_all_sorted_by_created_at(self, store):
        """Test que les résultats sont triés par date de création."""
        draft1 = PendingDraft(id="d1", email_id="e1", created_at="2025-01-01T10:00:00")
        draft2 = PendingDraft(id="d2", email_id="e2", created_at="2025-01-02T10:00:00")
        store.add(draft1)
        store.add(draft2)
        all_drafts = store.get_all()
        assert all_drafts[0].id == "d2"

    def test_get_all_empty_store(self, store):
        """Test la récupération depuis un store vide."""
        all_drafts = store.get_all()
        assert all_drafts == []


# ============================================================================
# Tests Update Status
# ============================================================================


class TestUpdateStatus:
    """Tests pour la mise à jour de statut."""

    def test_update_status_existing_draft(self, store, sample_draft):
        """Test la mise à jour du statut d'un brouillon existant."""
        store.add(sample_draft)
        result = store.update_status(sample_draft.id, PendingDraftStatus.VALIDATED)
        assert result is True
        assert store._store[sample_draft.id].status == PendingDraftStatus.VALIDATED

    def test_update_status_non_existing_draft(self, store):
        """Test la mise à jour du statut d'un brouillon inexistant."""
        result = store.update_status("non-existing", PendingDraftStatus.VALIDATED)
        assert result is False

    def test_update_status_sets_processed_at(self, store, sample_draft):
        """Test que processed_at est défini lors de la mise à jour."""
        store.add(sample_draft)
        store.update_status(sample_draft.id, PendingDraftStatus.VALIDATED)
        assert store._store[sample_draft.id].processed_at is not None

    def test_update_status_with_gmail_draft_id(self, store, sample_draft):
        """Test la mise à jour avec gmail_draft_id."""
        store.add(sample_draft)
        store.update_status(
            sample_draft.id,
            PendingDraftStatus.VALIDATED,
            gmail_draft_id="gmail-123"
        )
        assert store._store[sample_draft.id].gmail_draft_id == "gmail-123"

    def test_update_status_persists_to_disk(self, store, sample_draft):
        """Test que la mise à jour persiste sur le disque."""
        store.add(sample_draft)
        store.update_status(sample_draft.id, PendingDraftStatus.REJECTED)
        store.flush()

        # Recharger depuis le disque
        new_store = InMemoryPendingDraftStore(persist_path=store._persist_path)
        assert new_store._store[sample_draft.id].status == PendingDraftStatus.REJECTED

    def test_update_status_to_all_statuses(self, store):
        """Test la mise à jour vers tous les statuts possibles."""
        for status in PendingDraftStatus:
            draft = PendingDraft(id=f"draft-{status.value}", email_id=f"email-{status.value}")
            store.add(draft)
            result = store.update_status(draft.id, status)
            assert result is True
            assert store._store[draft.id].status == status


# ============================================================================
# Tests Update Content
# ============================================================================


class TestUpdateContent:
    """Tests pour la mise à jour du contenu."""

    def test_update_content_existing_draft(self, store, sample_draft):
        """Test la mise à jour du contenu d'un brouillon existant."""
        store.add(sample_draft)
        result = store.update_content(
            sample_draft.id,
            draft_subject="New Subject",
            draft_body="New Body"
        )
        assert result is True
        assert store._store[sample_draft.id].draft_subject == "New Subject"
        assert store._store[sample_draft.id].draft_body == "New Body"

    def test_update_content_non_existing_draft(self, store):
        """Test la mise à jour du contenu d'un brouillon inexistant."""
        result = store.update_content("non-existing", "Subject", "Body")
        assert result is False

    def test_update_content_persists_to_disk(self, store, sample_draft):
        """Test que la mise à jour du contenu persiste sur le disque."""
        store.add(sample_draft)
        store.update_content(sample_draft.id, "Updated Subject", "Updated Body")
        store.flush()

        new_store = InMemoryPendingDraftStore(persist_path=store._persist_path)
        assert new_store._store[sample_draft.id].draft_subject == "Updated Subject"

    def test_update_content_with_unicode(self, store, sample_draft):
        """Test la mise à jour avec du contenu unicode."""
        store.add(sample_draft)
        result = store.update_content(
            sample_draft.id,
            "Sujet avec émojis 🎉",
            "Corps avec accents éèêë"
        )
        assert result is True
        assert "🎉" in store._store[sample_draft.id].draft_subject


# ============================================================================
# Tests Delete
# ============================================================================


class TestDelete:
    """Tests pour la suppression."""

    def test_delete_existing_draft(self, store, sample_draft):
        """Test la suppression d'un brouillon existant."""
        store.add(sample_draft)
        result = store.delete(sample_draft.id)
        assert result is True
        assert sample_draft.id not in store._store

    def test_delete_non_existing_draft(self, store):
        """Test la suppression d'un brouillon inexistant (idempotent)."""
        result = store.delete("non-existing")
        assert result is True

    def test_delete_persists_to_disk(self, store, sample_draft):
        """Test que la suppression persiste sur le disque."""
        store.add(sample_draft)
        store.delete(sample_draft.id)
        store.flush()

        new_store = InMemoryPendingDraftStore(persist_path=store._persist_path)
        assert sample_draft.id not in new_store._store

    def test_delete_from_empty_store(self, store):
        """Test la suppression depuis un store vide (idempotent)."""
        result = store.delete("any-id")
        assert result is True


# ============================================================================
# Tests Count Pending
# ============================================================================


class TestCountPending:
    """Tests pour le comptage des brouillons en attente."""

    def test_count_pending_empty_store(self, store):
        """Test le comptage d'un store vide."""
        count = store.count_pending()
        assert count == 0

    def test_count_pending_with_pending_drafts(self, store, multiple_drafts):
        """Test le comptage avec des brouillons PENDING."""
        for draft in multiple_drafts:
            store.add(draft)
        count = store.count_pending()
        assert count == 3  # 3 pending dans multiple_drafts

    def test_count_pending_all_validated(self, store):
        """Test le comptage quand tous sont validés."""
        draft = PendingDraft(
            id="validated-1",
            email_id="email-1",
            status=PendingDraftStatus.VALIDATED
        )
        store.add(draft)
        count = store.count_pending()
        assert count == 0


# ============================================================================
# Tests Get By Email ID
# ============================================================================


class TestGetByEmailId:
    """Tests pour la récupération par email ID."""

    def test_get_by_email_id_existing(self, store, sample_draft):
        """Test la récupération par email ID existant."""
        store.add(sample_draft)
        result = store.get_by_email_id(sample_draft.email_id)
        assert result == sample_draft

    def test_get_by_email_id_non_existing(self, store):
        """Test la récupération par email ID inexistant."""
        result = store.get_by_email_id("non-existing-email-id")
        assert result is None

    def test_get_by_email_id_empty_string(self, store):
        """Test la récupération avec email ID vide."""
        result = store.get_by_email_id("")
        assert result is None

    def test_get_by_email_id_multiple_drafts(self, store, multiple_drafts):
        """Test la récupération parmi plusieurs brouillons."""
        for draft in multiple_drafts:
            store.add(draft)
        result = store.get_by_email_id("email-2")
        assert result is not None
        assert result.email_id == "email-2"

    def test_get_by_email_id_hydrates_shared_pending_draft(self, store):
        """Test que l'API peut voir un brouillon écrit par le worker RQ."""
        payload = PendingDraft(
            id="draft-redis",
            email_id="email-redis",
            account_id="14",
            draft_body="Réponse Redis",
            status=PendingDraftStatus.PENDING,
        ).to_dict()

        with patch(
            "app.infrastructure.draft_job_queue.get_shared_pending_draft_by_email",
            return_value=payload,
        ) as shared_lookup:
            result = store.get_by_email_id("email-redis", account_id="14")

        assert result is not None
        assert result.id == "draft-redis"
        assert result.draft_body == "Réponse Redis"
        assert store.get_by_id("draft-redis") == result
        shared_lookup.assert_called_once_with(
            account_id="14",
            email_id="email-redis",
        )


# ============================================================================
# Tests Thread Safety
# ============================================================================


class TestThreadSafety:
    """Tests pour la sécurité multi-thread."""

    def test_concurrent_adds(self, store):
        """Test des ajouts concurrents."""
        errors = []

        def add_draft(i):
            try:
                draft = PendingDraft(id=f"concurrent-{i}", email_id=f"email-{i}")
                store.add(draft)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_draft, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(store._store) == 10

    def test_concurrent_reads_and_writes(self, store, sample_draft):
        """Test des lectures et écritures concurrentes."""
        store.add(sample_draft)
        errors = []

        def read_draft():
            try:
                for _ in range(10):
                    store.get_by_id(sample_draft.id)
            except Exception as e:
                errors.append(e)

        def write_draft(i):
            try:
                draft = PendingDraft(id=f"new-{i}", email_id=f"email-{i}")
                store.add(draft)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=read_draft))
            threads.append(threading.Thread(target=write_draft, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ============================================================================
# Tests Singleton
# ============================================================================


class TestSingleton:
    """Tests pour le pattern singleton."""

    def test_get_pending_draft_store_returns_instance(self):
        """Test que get_pending_draft_store retourne une instance."""
        with patch("app.infrastructure.pending_draft_store._pending_draft_store", None):
            with patch("os.path.exists", return_value=False):
                store = get_pending_draft_store()
                assert isinstance(store, InMemoryPendingDraftStore)

    def test_get_pending_draft_store_returns_same_instance(self):
        """Test que get_pending_draft_store retourne la même instance."""
        with patch("app.infrastructure.pending_draft_store._pending_draft_store", None):
            with patch("os.path.exists", return_value=False):
                store1 = get_pending_draft_store()
                store2 = get_pending_draft_store()
                assert store1 is store2


# ============================================================================
# Tests Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_add_draft_with_empty_id(self, store):
        """Test l'ajout d'un brouillon avec ID vide."""
        draft = PendingDraft(id="", email_id="email-1")
        draft_id = store.add(draft)
        assert draft_id == ""
        assert "" in store._store

    def test_update_status_multiple_times(self, store, sample_draft):
        """Test la mise à jour du statut plusieurs fois."""
        store.add(sample_draft)
        store.update_status(sample_draft.id, PendingDraftStatus.VALIDATED)
        store.update_status(sample_draft.id, PendingDraftStatus.REJECTED)
        store.update_status(sample_draft.id, PendingDraftStatus.MODIFIED)
        assert store._store[sample_draft.id].status == PendingDraftStatus.MODIFIED

    def test_get_pending_large_limit(self, store, sample_draft):
        """Test avec une limite très grande."""
        store.add(sample_draft)
        pending = store.get_pending(limit=10000)
        assert len(pending) == 1

    def test_get_all_large_limit(self, store, sample_draft):
        """Test get_all avec une limite très grande."""
        store.add(sample_draft)
        all_drafts = store.get_all(limit=10000)
        assert len(all_drafts) == 1

    def test_persistence_roundtrip(self, temp_persist_path, sample_draft):
        """Test aller-retour complet de persistance."""
        # Créer store, ajouter, fermer
        store1 = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        store1.add(sample_draft)
        store1.flush()

        # Nouveau store, vérifier données
        store2 = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        loaded = store2.get_by_id(sample_draft.id)
        assert loaded is not None
        assert loaded.email_id == sample_draft.email_id
        assert loaded.draft_subject == sample_draft.draft_subject

    def test_load_with_missing_fields(self, temp_persist_path):
        """Test le chargement avec des champs manquants."""
        os.makedirs(os.path.dirname(temp_persist_path), exist_ok=True)
        # Données minimales
        minimal_data = [{"id": "min-1", "status": "pending"}]
        with open(temp_persist_path, "w", encoding="utf-8") as f:
            json.dump(minimal_data, f)

        store = InMemoryPendingDraftStore(persist_path=temp_persist_path)
        assert len(store._store) == 1

    def test_special_characters_in_content(self, store):
        """Test avec des caractères spéciaux dans le contenu."""
        draft = PendingDraft(
            id="special-1",
            email_id="email-s",
            email_subject='Subject with "quotes" and \\backslashes\\',
            draft_body="Body with <html> tags & ampersands",
        )
        store.add(draft)
        loaded = store.get_by_id("special-1")
        assert loaded.email_subject == 'Subject with "quotes" and \\backslashes\\'
        assert loaded.draft_body == "Body with <html> tags & ampersands"
