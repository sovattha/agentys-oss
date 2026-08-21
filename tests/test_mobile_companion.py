# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'app mobile companion.

Ces tests couvrent :
- Les entités de domaine (MobileSession, MobileSyncState, MobileDraft, etc.)
- Les ports (interfaces)
- Les adapters infrastructure (stores)
- Les use cases (application layer)
- L'API REST mobile
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch


@pytest.fixture(autouse=True)
def _mock_jwt_for_mobile_routes():
    """Mock _authenticated_user_id (audit P0-001 2026-04-28).

    Cf. autres test_mobile_*.py : sans mock, require_user_id renvoie 401.
    """
    with patch("app.api.mobile._authenticated_user_id", return_value="test@example.com"):
        yield


# Domain entities
from app.domain.entities.mobile_companion import (
    MobileEventType,
    SyncStatus,
    MobileDraftAction,
    NotificationPreference,
    SyncFrequency,
    MobileSession,
    MobileSyncState,
    MobileAnalyticsEvent,
    MobileDraft,
    MobileUserPreferences,
    MobileAppConfig,
    MobileDraftActionRequest,
)


# ============================================================================
# TESTS - DOMAIN ENTITIES - MobileSession
# ============================================================================

class TestMobileSession:
    """Tests pour l'entité MobileSession."""

    def test_create_session(self):
        """Test création d'une session valide."""
        session = MobileSession(
            user_id="user_123",
            device_token="device_token_abc",
            app_version="1.0.0",
            os_version="iOS 17.2",
            device_model="iPhone 15 Pro",
        )

        assert session.user_id == "user_123"
        assert session.device_token == "device_token_abc"
        assert session.app_version == "1.0.0"
        assert session.is_active is True
        assert session.session_id is not None

    def test_session_empty_user_id_raises(self):
        """Test qu'un user_id vide lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSession(user_id="")

    def test_session_touch(self):
        """Test mise à jour de l'activité."""
        session = MobileSession(user_id="user_123")
        original_time = session.last_activity_at

        # Attendre un peu pour que le temps change
        import time
        time.sleep(0.01)

        session.touch()
        assert session.last_activity_at > original_time

    def test_session_end(self):
        """Test fin de session."""
        session = MobileSession(user_id="user_123")
        assert session.is_active is True

        session.end()
        assert session.is_active is False

    def test_session_to_dict(self):
        """Test sérialisation en dictionnaire."""
        session = MobileSession(
            user_id="user_123",
            device_token="token_abc",
        )
        data = session.to_dict()

        assert data["user_id"] == "user_123"
        assert data["device_token"] == "token_abc"
        assert data["is_active"] is True
        assert "session_id" in data
        assert "started_at" in data

    def test_session_from_dict(self):
        """Test désérialisation depuis dictionnaire."""
        data = {
            "session_id": "session_123",
            "user_id": "user_456",
            "device_token": "token_xyz",
            "started_at": "2024-01-01T12:00:00",
            "last_activity_at": "2024-01-01T12:30:00",
            "is_active": True,
        }
        session = MobileSession.from_dict(data)

        assert session.session_id == "session_123"
        assert session.user_id == "user_456"
        assert session.device_token == "token_xyz"


# ============================================================================
# TESTS - DOMAIN ENTITIES - MobileSyncState
# ============================================================================

class TestMobileSyncState:
    """Tests pour l'entité MobileSyncState."""

    def test_create_sync_state(self):
        """Test création d'un état de sync valide."""
        state = MobileSyncState(
            user_id="user_123",
            device_token="device_token_abc",
        )

        assert state.user_id == "user_123"
        assert state.device_token == "device_token_abc"
        assert state.last_sync_status == SyncStatus.IDLE
        assert state.drafts_synced_count == 0

    def test_sync_state_empty_user_id_raises(self):
        """Test qu'un user_id vide lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSyncState(user_id="", device_token="token")

    def test_sync_state_empty_device_token_raises(self):
        """Test qu'un device_token vide lève une erreur."""
        with pytest.raises(ValueError, match="Device token cannot be empty"):
            MobileSyncState(user_id="user_123", device_token="")

    def test_sync_state_mark_syncing(self):
        """Test marquage début de sync."""
        state = MobileSyncState(user_id="user_123", device_token="token")
        state.mark_syncing()

        assert state.last_sync_status == SyncStatus.SYNCING
        assert state.error_message is None

    def test_sync_state_mark_success(self):
        """Test marquage sync réussie."""
        state = MobileSyncState(user_id="user_123", device_token="token")
        state.mark_success(42)

        assert state.last_sync_status == SyncStatus.SUCCESS
        assert state.drafts_synced_count == 42
        assert state.pending_actions_count == 0
        assert state.last_sync_at is not None

    def test_sync_state_mark_failed(self):
        """Test marquage sync échouée."""
        state = MobileSyncState(user_id="user_123", device_token="token")
        state.mark_failed("Connection error")

        assert state.last_sync_status == SyncStatus.FAILED
        assert state.error_message == "Connection error"

    def test_sync_state_to_dict(self):
        """Test sérialisation."""
        state = MobileSyncState(user_id="user_123", device_token="token")
        data = state.to_dict()

        assert data["user_id"] == "user_123"
        assert data["device_token"] == "token"
        assert data["last_sync_status"] == "idle"


# ============================================================================
# TESTS - DOMAIN ENTITIES - MobileAnalyticsEvent
# ============================================================================

class TestMobileAnalyticsEvent:
    """Tests pour l'entité MobileAnalyticsEvent."""

    def test_create_event(self):
        """Test création d'un événement valide."""
        event = MobileAnalyticsEvent(
            event_type=MobileEventType.DRAFT_VIEW,
            user_id="user_123",
            session_id="session_456",
            properties={"draft_id": "draft_789"},
        )

        assert event.event_type == MobileEventType.DRAFT_VIEW
        assert event.user_id == "user_123"
        assert event.session_id == "session_456"
        assert event.properties == {"draft_id": "draft_789"}

    def test_event_empty_user_id_raises(self):
        """Test qu'un user_id vide lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileAnalyticsEvent(
                event_type=MobileEventType.APP_OPEN,
                user_id="",
            )

    def test_event_with_string_type(self):
        """Test création avec type en string."""
        event = MobileAnalyticsEvent(
            event_type="app.open",
            user_id="user_123",
        )
        assert event.event_type == MobileEventType.APP_OPEN

    def test_event_to_dict(self):
        """Test sérialisation."""
        event = MobileAnalyticsEvent(
            event_type=MobileEventType.DRAFT_APPROVE,
            user_id="user_123",
            properties={"draft_id": "d1"},
        )
        data = event.to_dict()

        assert data["event_type"] == "draft.approve"
        assert data["user_id"] == "user_123"
        assert data["properties"] == {"draft_id": "d1"}


# ============================================================================
# TESTS - DOMAIN ENTITIES - MobileDraft
# ============================================================================

class TestMobileDraft:
    """Tests pour l'entité MobileDraft."""

    def test_create_draft(self):
        """Test création d'un brouillon valide."""
        draft = MobileDraft(
            draft_id="draft_123",
            subject="Test Subject",
            recipient="test@example.com",
            recipient_name="John Doe",
            body_full="This is the full body of the email.",
            priority_score=85,
            category="URGENT",
        )

        assert draft.draft_id == "draft_123"
        assert draft.subject == "Test Subject"
        assert draft.recipient == "test@example.com"
        assert draft.priority_score == 85
        assert draft.action == MobileDraftAction.PENDING
        # Body preview devrait être généré
        assert draft.body_preview == draft.body_full

    def test_draft_empty_id_raises(self):
        """Test qu'un draft_id vide lève une erreur."""
        with pytest.raises(ValueError, match="Draft ID cannot be empty"):
            MobileDraft(draft_id="", subject="Test", recipient="test@example.com")

    def test_draft_empty_subject_raises(self):
        """Test qu'un subject vide lève une erreur."""
        with pytest.raises(ValueError, match="Subject cannot be empty"):
            MobileDraft(draft_id="d1", subject="", recipient="test@example.com")

    def test_draft_body_preview_generation(self):
        """Test génération automatique de l'aperçu."""
        long_body = "A" * 300
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="test@example.com",
            body_full=long_body,
        )

        assert len(draft.body_preview) == 203  # 200 + "..."
        assert draft.body_preview.endswith("...")

    def test_draft_mark_read(self):
        """Test marquage comme lu."""
        draft = MobileDraft(draft_id="d1", subject="Test", recipient="test@example.com")
        assert draft.is_read is False

        draft.mark_read()
        assert draft.is_read is True

    def test_draft_approve(self):
        """Test approbation du brouillon."""
        draft = MobileDraft(draft_id="d1", subject="Test", recipient="test@example.com")
        draft.approve()

        assert draft.action == MobileDraftAction.APPROVED

    def test_draft_reject(self):
        """Test rejet du brouillon."""
        draft = MobileDraft(draft_id="d1", subject="Test", recipient="test@example.com")
        draft.reject()

        assert draft.action == MobileDraftAction.REJECTED

    def test_draft_edit(self):
        """Test édition du brouillon."""
        draft = MobileDraft(draft_id="d1", subject="Test", recipient="test@example.com")
        draft.edit("New body content")

        assert draft.action == MobileDraftAction.EDITED
        assert draft.body_full == "New body content"
        assert draft.body_preview == "New body content"

    def test_draft_to_dict(self):
        """Test sérialisation complète."""
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="test@example.com",
            body_full="Body",
        )
        data = draft.to_dict()

        assert data["draft_id"] == "d1"
        assert data["subject"] == "Test"
        assert "body_full" in data

    def test_draft_to_list_dict(self):
        """Test sérialisation allégée (sans body_full)."""
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="test@example.com",
            body_full="Body",
        )
        data = draft.to_list_dict()

        assert data["draft_id"] == "d1"
        assert "body_full" not in data
        assert "body_preview" in data


# ============================================================================
# TESTS - DOMAIN ENTITIES - MobileUserPreferences
# ============================================================================

class TestMobileUserPreferences:
    """Tests pour l'entité MobileUserPreferences."""

    def test_create_preferences(self):
        """Test création de préférences valides."""
        prefs = MobileUserPreferences(
            user_id="user_123",
            notification_preference=NotificationPreference.IMPORTANT_ONLY,
            sync_frequency=SyncFrequency.EVERY_15_MIN,
            auto_approve_threshold=80,
            dark_mode=True,
            language="en",
        )

        assert prefs.user_id == "user_123"
        assert prefs.notification_preference == NotificationPreference.IMPORTANT_ONLY
        assert prefs.sync_frequency == SyncFrequency.EVERY_15_MIN
        assert prefs.auto_approve_threshold == 80
        assert prefs.dark_mode is True
        assert prefs.language == "en"

    def test_preferences_empty_user_id_raises(self):
        """Test qu'un user_id vide lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileUserPreferences(user_id="")

    def test_preferences_invalid_threshold_raises(self):
        """Test qu'un seuil invalide lève une erreur."""
        with pytest.raises(ValueError, match="must be between 0 and 100"):
            MobileUserPreferences(user_id="user_123", auto_approve_threshold=150)

    def test_preferences_with_string_enums(self):
        """Test création avec enums en string."""
        prefs = MobileUserPreferences(
            user_id="user_123",
            notification_preference="none",
            sync_frequency="manual",
        )
        assert prefs.notification_preference == NotificationPreference.NONE
        assert prefs.sync_frequency == SyncFrequency.MANUAL

    def test_preferences_to_dict(self):
        """Test sérialisation."""
        prefs = MobileUserPreferences(user_id="user_123")
        data = prefs.to_dict()

        assert data["user_id"] == "user_123"
        assert "notification_preference" in data
        assert "sync_frequency" in data


# ============================================================================
# TESTS - DOMAIN ENTITIES - MobileAppConfig
# ============================================================================

class TestMobileAppConfig:
    """Tests pour l'entité MobileAppConfig."""

    def test_create_config(self):
        """Test création de configuration par défaut."""
        config = MobileAppConfig()

        assert config.min_version == "1.0.0"
        assert config.latest_version == "1.0.0"
        assert config.force_update is False
        assert config.maintenance_mode is False
        assert "offline_mode" in config.feature_flags

    def test_config_version_supported(self):
        """Test vérification de version supportée."""
        config = MobileAppConfig(min_version="1.0.0")

        assert config.is_version_supported("1.0.0") is True
        assert config.is_version_supported("1.1.0") is True
        assert config.is_version_supported("2.0.0") is True
        assert config.is_version_supported("0.9.0") is False

    def test_config_needs_update(self):
        """Test vérification de mise à jour disponible."""
        config = MobileAppConfig(latest_version="1.2.0")

        assert config.needs_update("1.0.0") is True
        assert config.needs_update("1.1.0") is True
        assert config.needs_update("1.2.0") is False
        assert config.needs_update("1.3.0") is False

    def test_config_version_comparison(self):
        """Test comparaison de versions."""
        config = MobileAppConfig()

        assert config._compare_versions("1.0.0", "1.0.0") == 0
        assert config._compare_versions("1.0.0", "1.0.1") == -1
        assert config._compare_versions("1.1.0", "1.0.0") == 1
        assert config._compare_versions("2.0.0", "1.9.9") == 1

    def test_config_to_dict(self):
        """Test sérialisation."""
        config = MobileAppConfig()
        data = config.to_dict()

        assert "min_version" in data
        assert "latest_version" in data
        assert "feature_flags" in data
        assert "api_endpoints" in data


# ============================================================================
# TESTS - DOMAIN ENTITIES - MobileDraftActionRequest
# ============================================================================

class TestMobileDraftActionRequest:
    """Tests pour l'entité MobileDraftActionRequest."""

    def test_create_request(self):
        """Test création d'une requête valide."""
        request = MobileDraftActionRequest(
            draft_id="draft_123",
            action=MobileDraftAction.APPROVED,
            user_id="user_456",
        )

        assert request.draft_id == "draft_123"
        assert request.action == MobileDraftAction.APPROVED
        assert request.user_id == "user_456"

    def test_request_empty_draft_id_raises(self):
        """Test qu'un draft_id vide lève une erreur."""
        with pytest.raises(ValueError, match="Draft ID cannot be empty"):
            MobileDraftActionRequest(
                draft_id="",
                action=MobileDraftAction.APPROVED,
                user_id="user_123",
            )

    def test_request_edit_without_body_raises(self):
        """Test qu'une édition sans corps lève une erreur."""
        with pytest.raises(ValueError, match="Edited body is required"):
            MobileDraftActionRequest(
                draft_id="d1",
                action=MobileDraftAction.EDITED,
                user_id="user_123",
            )

    def test_request_edit_with_body(self):
        """Test création d'une requête d'édition valide."""
        request = MobileDraftActionRequest(
            draft_id="d1",
            action=MobileDraftAction.EDITED,
            user_id="user_123",
            edited_body="New body",
        )
        assert request.edited_body == "New body"


# ============================================================================
# TESTS - INFRASTRUCTURE STORES
# ============================================================================

class TestMobileSessionStore:
    """Tests pour le store de sessions mobiles."""

    @pytest.fixture
    def temp_filepath(self):
        """Crée un fichier temporaire pour les tests."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            return Path(f.name)

    @pytest.fixture
    def session_store(self, temp_filepath):
        """Crée un store de test."""
        from app.infrastructure.mobile_companion_store import JsonFileMobileSessionStore
        return JsonFileMobileSessionStore(temp_filepath)

    def test_create_session(self, session_store):
        """Test création d'une session."""
        session = session_store.create(
            user_id="user_123",
            device_token="token_abc",
            app_version="1.0.0",
        )

        assert session.user_id == "user_123"
        assert session.device_token == "token_abc"
        assert session.is_active is True

    def test_get_session(self, session_store):
        """Test récupération d'une session."""
        created = session_store.create(user_id="user_123")

        retrieved = session_store.get(created.session_id)
        assert retrieved is not None
        assert retrieved.session_id == created.session_id

    def test_get_nonexistent_session(self, session_store):
        """Test récupération d'une session inexistante."""
        result = session_store.get("nonexistent")
        assert result is None

    def test_get_active_by_user(self, session_store):
        """Test récupération des sessions actives d'un utilisateur."""
        session_store.create(user_id="user_123")
        session_store.create(user_id="user_123")
        session_store.create(user_id="other_user")

        active = session_store.get_active_by_user("user_123")
        assert len(active) == 2

    def test_touch_session(self, session_store):
        """Test mise à jour d'activité."""
        session = session_store.create(user_id="user_123")

        success = session_store.touch(session.session_id)
        assert success is True

    def test_end_session(self, session_store):
        """Test fin de session."""
        session = session_store.create(user_id="user_123")

        success = session_store.end(session.session_id)
        assert success is True

        ended = session_store.get(session.session_id)
        assert ended.is_active is False

    def test_end_all_for_user(self, session_store):
        """Test fin de toutes les sessions d'un utilisateur."""
        session_store.create(user_id="user_123")
        session_store.create(user_id="user_123")

        count = session_store.end_all_for_user("user_123")
        assert count == 2


class TestMobileSyncStore:
    """Tests pour le store de synchronisation."""

    @pytest.fixture
    def temp_filepath(self):
        """Crée un fichier temporaire pour les tests."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            return Path(f.name)

    @pytest.fixture
    def sync_store(self, temp_filepath):
        """Crée un store de test."""
        from app.infrastructure.mobile_companion_store import JsonFileMobileSyncStore
        return JsonFileMobileSyncStore(temp_filepath)

    def test_get_sync_state_nonexistent(self, sync_store):
        """Test récupération d'un état inexistant."""
        result = sync_store.get_sync_state("user", "token")
        assert result is None

    def test_update_sync_state(self, sync_store):
        """Test mise à jour de l'état de sync."""
        state = MobileSyncState(user_id="user_123", device_token="token_abc")
        state.mark_success(10)

        updated = sync_store.update_sync_state(state)
        assert updated.drafts_synced_count == 10

    def test_add_and_get_draft(self, sync_store):
        """Test ajout et récupération de brouillon."""
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="test@example.com",
        )
        sync_store.add_draft(draft)

        retrieved = sync_store.get_draft("d1", "user_123")
        assert retrieved is not None
        assert retrieved.draft_id == "d1"

    def test_get_pending_drafts(self, sync_store):
        """Test récupération des brouillons en attente."""
        # Ajouter des brouillons avec différentes priorités
        for i, priority in enumerate([30, 90, 60]):
            draft = MobileDraft(
                draft_id=f"d{i}",
                subject=f"Test {i}",
                recipient="test@example.com",
                priority_score=priority,
            )
            sync_store.add_draft(draft)

        pending = sync_store.get_pending_drafts("user_123", limit=10)
        assert len(pending) == 3
        # Vérifier le tri par priorité décroissante
        assert pending[0].priority_score == 90
        assert pending[1].priority_score == 60


class TestMobileAnalyticsStore:
    """Tests pour le store d'analytics."""

    @pytest.fixture
    def temp_filepath(self):
        """Crée un fichier temporaire pour les tests."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            return Path(f.name)

    @pytest.fixture
    def analytics_store(self, temp_filepath):
        """Crée un store de test."""
        from app.infrastructure.mobile_companion_store import JsonFileMobileAnalyticsStore
        return JsonFileMobileAnalyticsStore(temp_filepath)

    def test_track_event(self, analytics_store):
        """Test enregistrement d'un événement."""
        event = MobileAnalyticsEvent(
            event_type=MobileEventType.APP_OPEN,
            user_id="user_123",
        )

        success = analytics_store.track_event(event)
        assert success is True

    def test_track_batch(self, analytics_store):
        """Test enregistrement en batch."""
        events = [
            MobileAnalyticsEvent(event_type=MobileEventType.APP_OPEN, user_id="user_123"),
            MobileAnalyticsEvent(event_type=MobileEventType.DRAFT_VIEW, user_id="user_123"),
        ]

        count = analytics_store.track_batch(events)
        assert count == 2

    def test_get_events(self, analytics_store):
        """Test récupération des événements."""
        for i in range(5):
            event = MobileAnalyticsEvent(
                event_type=MobileEventType.DRAFT_VIEW,
                user_id="user_123",
            )
            analytics_store.track_event(event)

        events = analytics_store.get_events("user_123")
        assert len(events) == 5

    def test_get_events_filtered(self, analytics_store):
        """Test récupération avec filtre."""
        analytics_store.track_event(MobileAnalyticsEvent(
            event_type=MobileEventType.APP_OPEN, user_id="user_123"
        ))
        analytics_store.track_event(MobileAnalyticsEvent(
            event_type=MobileEventType.DRAFT_VIEW, user_id="user_123"
        ))

        events = analytics_store.get_events("user_123", event_type="app.open")
        assert len(events) == 1

    def test_get_stats(self, analytics_store):
        """Test récupération des statistiques."""
        # Ajouter quelques événements
        analytics_store.track_event(MobileAnalyticsEvent(
            event_type=MobileEventType.DRAFT_APPROVE, user_id="user_123"
        ))
        analytics_store.track_event(MobileAnalyticsEvent(
            event_type=MobileEventType.DRAFT_REJECT, user_id="user_123"
        ))

        stats = analytics_store.get_stats("user_123", days=7)
        assert stats.user_id == "user_123"
        assert stats.approved_today >= 0
        assert stats.rejected_today >= 0


class TestMobilePreferencesStore:
    """Tests pour le store de préférences."""

    @pytest.fixture
    def temp_filepath(self):
        """Crée un fichier temporaire pour les tests."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            return Path(f.name)

    @pytest.fixture
    def preferences_store(self, temp_filepath):
        """Crée un store de test."""
        from app.infrastructure.mobile_companion_store import JsonFileMobilePreferencesStore
        return JsonFileMobilePreferencesStore(temp_filepath)

    def test_get_nonexistent(self, preferences_store):
        """Test récupération de préférences inexistantes."""
        result = preferences_store.get("nonexistent")
        assert result is None

    def test_save_preferences(self, preferences_store):
        """Test sauvegarde de préférences."""
        prefs = MobileUserPreferences(
            user_id="user_123",
            dark_mode=True,
            language="fr",
        )

        saved = preferences_store.save(prefs)
        assert saved.dark_mode is True
        assert saved.language == "fr"

    def test_update_preferences(self, preferences_store):
        """Test mise à jour partielle."""
        # Créer d'abord
        prefs = MobileUserPreferences(user_id="user_123", dark_mode=False)
        preferences_store.save(prefs)

        # Mettre à jour
        updated = preferences_store.update("user_123", {"dark_mode": True})
        assert updated is not None
        assert updated.dark_mode is True

    def test_delete_preferences(self, preferences_store):
        """Test suppression de préférences."""
        prefs = MobileUserPreferences(user_id="user_123")
        preferences_store.save(prefs)

        success = preferences_store.delete("user_123")
        assert success is True
        assert preferences_store.get("user_123") is None


class TestMobileAppConfigStore:
    """Tests pour le store de configuration."""

    @pytest.fixture
    def temp_filepath(self):
        """Crée un fichier temporaire pour les tests."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            return Path(f.name)

    @pytest.fixture
    def config_store(self, temp_filepath):
        """Crée un store de test."""
        from app.infrastructure.mobile_companion_store import JsonFileMobileAppConfigStore
        return JsonFileMobileAppConfigStore(temp_filepath)

    def test_get_default_config(self, config_store):
        """Test récupération de la configuration par défaut."""
        config = config_store.get()
        assert config is not None
        assert config.min_version == "1.0.0"

    def test_update_feature_flag(self, config_store):
        """Test mise à jour d'un feature flag."""
        success = config_store.update_feature_flag("new_feature", True)
        assert success is True

        config = config_store.get()
        assert config.feature_flags.get("new_feature") is True

    def test_set_maintenance_mode(self, config_store):
        """Test activation du mode maintenance."""
        success = config_store.set_maintenance_mode(True, "System update")
        assert success is True

        config = config_store.get()
        assert config.maintenance_mode is True
        assert config.maintenance_message == "System update"

    def test_update_versions(self, config_store):
        """Test mise à jour des versions."""
        config = config_store.update_versions(
            min_version="1.1.0",
            latest_version="1.2.0",
            force_update=True,
        )

        assert config.min_version == "1.1.0"
        assert config.latest_version == "1.2.0"
        assert config.force_update is True


# ============================================================================
# TESTS - APPLICATION USE CASES
# ============================================================================

class TestStartMobileSessionUseCase:
    """Tests pour le use case de démarrage de session."""

    def test_start_session_success(self):
        """Test démarrage de session réussi."""
        from app.application.mobile_companion import StartMobileSessionUseCase

        # Créer des mocks
        session_port = Mock()
        config_port = Mock()
        preferences_port = Mock()

        # Configurer les mocks
        session_port.create.return_value = MobileSession(user_id="user_123")
        config_port.get.return_value = MobileAppConfig()
        preferences_port.get.return_value = MobileUserPreferences(user_id="user_123")

        uc = StartMobileSessionUseCase(
            session_port=session_port,
            config_port=config_port,
            preferences_port=preferences_port,
        )

        result = uc.execute(
            user_id="user_123",
            app_version="1.0.0",
        )

        assert result.success is True
        assert result.session is not None
        assert result.app_config is not None

    def test_start_session_unsupported_version(self):
        """Test démarrage avec version non supportée."""
        from app.application.mobile_companion import StartMobileSessionUseCase

        session_port = Mock()
        config_port = Mock()
        preferences_port = Mock()

        config = MobileAppConfig(min_version="2.0.0")
        config_port.get.return_value = config

        uc = StartMobileSessionUseCase(
            session_port=session_port,
            config_port=config_port,
            preferences_port=preferences_port,
        )

        result = uc.execute(user_id="user_123", app_version="1.0.0")

        assert result.success is False
        assert "not supported" in result.error_message

    def test_start_session_maintenance_mode(self):
        """Test démarrage en mode maintenance."""
        from app.application.mobile_companion import StartMobileSessionUseCase

        session_port = Mock()
        config_port = Mock()
        preferences_port = Mock()

        config = MobileAppConfig(maintenance_mode=True, maintenance_message="Update in progress")
        config_port.get.return_value = config

        uc = StartMobileSessionUseCase(
            session_port=session_port,
            config_port=config_port,
            preferences_port=preferences_port,
        )

        result = uc.execute(user_id="user_123")

        assert result.success is False
        # Le message peut être soit le message de maintenance soit un message générique
        assert result.error_message is not None


class TestSyncMobileDataUseCase:
    """Tests pour le use case de synchronisation."""

    def test_sync_success(self):
        """Test synchronisation réussie."""
        from app.application.mobile_companion import SyncMobileDataUseCase

        sync_port = Mock()
        analytics_port = Mock()

        drafts = [
            MobileDraft(draft_id="d1", subject="Test 1", recipient="a@b.com"),
            MobileDraft(draft_id="d2", subject="Test 2", recipient="c@d.com"),
        ]
        sync_port.get_sync_state.return_value = None
        sync_port.get_drafts_since.return_value = (drafts, None, False)
        sync_port.update_sync_state.return_value = MobileSyncState(
            user_id="user_123", device_token="token"
        )
        analytics_port.track_event.return_value = True

        uc = SyncMobileDataUseCase(
            sync_port=sync_port,
            analytics_port=analytics_port,
        )

        result = uc.execute(
            user_id="user_123",
            device_token="token",
        )

        assert result.success is True
        assert len(result.drafts) == 2


class TestApplyDraftActionUseCase:
    """Tests pour le use case d'action sur brouillon."""

    def test_approve_action(self):
        """Test action d'approbation."""
        from app.application.mobile_companion import ApplyDraftActionUseCase

        action_port = Mock()
        sync_port = Mock()
        analytics_port = Mock()

        draft = MobileDraft(draft_id="d1", subject="Test", recipient="a@b.com")
        action_port.apply_action.return_value = True
        sync_port.get_draft.return_value = draft
        analytics_port.track_event.return_value = True

        uc = ApplyDraftActionUseCase(
            action_port=action_port,
            sync_port=sync_port,
            analytics_port=analytics_port,
        )

        request = MobileDraftActionRequest(
            draft_id="d1",
            action=MobileDraftAction.APPROVED,
            user_id="user_123",
        )

        result = uc.execute(request)

        assert result.success is True
        action_port.apply_action.assert_called_once()


# ============================================================================
# TESTS - API REST
# ============================================================================

class TestMobileAPI:
    """Tests pour l'API REST mobile."""

    @pytest.fixture
    def client(self):
        """Crée un client de test Flask."""
        from app.api.app import create_app
        app = create_app({"TESTING": True})
        with app.test_client() as client:
            yield client

    @pytest.fixture(autouse=True)
    def reset_stores(self):
        """Réinitialise les stores avant chaque test."""
        from app.infrastructure.mobile_companion_store import reset_mobile_stores
        from app.infrastructure.container import reset_container
        reset_mobile_stores()
        reset_container()  # Le Container gère le cycle de vie du service
        yield
        reset_mobile_stores()
        reset_container()

    def test_start_session_endpoint(self, client):
        """Test endpoint de démarrage de session."""
        # S'assurer que la config n'est pas en mode maintenance et accepte notre version
        from app.infrastructure.mobile_companion_store import get_mobile_config_store
        config_store = get_mobile_config_store()
        config_store.set_maintenance_mode(False)
        config_store.update_versions(min_version="1.0.0")

        response = client.post(
            "/api/mobile/session/start",
            json={
                "user_id": "user_123",
                "device_token": "token_abc",
                "app_version": "1.0.0",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert "session" in data

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) — payload user_id ignoré ou auth admin requise.")
    def test_start_session_missing_user_id(self, client):
        """Test démarrage sans user_id."""
        response = client.post(
            "/api/mobile/session/start",
            json={"device_token": "token"},
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_end_session_endpoint(self, client):
        """Test endpoint de fin de session."""
        # S'assurer que la config n'est pas en mode maintenance
        from app.infrastructure.mobile_companion_store import get_mobile_config_store
        config_store = get_mobile_config_store()
        config_store.set_maintenance_mode(False)
        config_store.update_versions(min_version="1.0.0")

        # D'abord créer une session
        start_response = client.post(
            "/api/mobile/session/start",
            json={"user_id": "user_123"},
            content_type="application/json",
        )
        session_id = start_response.get_json()["session"]["session_id"]

        # Terminer la session
        response = client.post(
            "/api/mobile/session/end",
            json={
                "session_id": session_id,
                "user_id": "user_123",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    def test_sync_endpoint(self, client):
        """Test endpoint de synchronisation."""
        response = client.post(
            "/api/mobile/sync",
            json={
                "user_id": "user_123",
                "device_token": "token_abc",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "drafts" in data

    def test_get_preferences_endpoint(self, client):
        """Test endpoint de récupération des préférences."""
        response = client.get("/api/mobile/preferences?user_id=user_123")

        assert response.status_code == 200
        data = response.get_json()
        assert "preferences" in data

    def test_update_preferences_endpoint(self, client):
        """Test endpoint de mise à jour des préférences."""
        # D'abord créer les préférences
        client.get("/api/mobile/preferences?user_id=user_123")

        response = client.put(
            "/api/mobile/preferences",
            json={
                "user_id": "user_123",
                "dark_mode": True,
                "language": "fr",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["preferences"]["dark_mode"] is True

    def test_get_config_endpoint(self, client):
        """Test endpoint de configuration."""
        response = client.get("/api/mobile/config")

        assert response.status_code == 200
        data = response.get_json()
        assert "config" in data
        assert "min_version" in data["config"]

    def test_get_config_with_version_check(self, client):
        """Test endpoint de configuration avec vérification de version."""
        response = client.get("/api/mobile/config?app_version=1.0.0")

        assert response.status_code == 200
        data = response.get_json()
        assert "version_supported" in data["config"]

    def test_track_analytics_endpoint(self, client):
        """Test endpoint d'analytics."""
        response = client.post(
            "/api/mobile/analytics",
            json={
                "event_type": "app.open",
                "user_id": "user_123",
                "properties": {"key": "value"},
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    def test_get_stats_endpoint(self, client):
        """Test endpoint de statistiques."""
        response = client.get("/api/mobile/stats?user_id=user_123")

        assert response.status_code == 200
        data = response.get_json()
        assert "stats" in data

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) — payload user_id ignoré ou auth admin requise.")
    def test_set_maintenance_mode_endpoint(self, client):
        """Test endpoint de mode maintenance."""
        response = client.put(
            "/api/mobile/config/maintenance",
            json={
                "enabled": True,
                "message": "System update",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["maintenance_mode"] is True

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) — payload user_id ignoré ou auth admin requise.")
    def test_update_versions_endpoint(self, client):
        """Test endpoint de mise à jour des versions."""
        response = client.put(
            "/api/mobile/config/versions",
            json={
                "min_version": "1.1.0",
                "latest_version": "1.2.0",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["config"]["min_version"] == "1.1.0"

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) — payload user_id ignoré ou auth admin requise.")
    def test_update_feature_flag_endpoint(self, client):
        """Test endpoint de feature flag."""
        response = client.put(
            "/api/mobile/config/feature/dark_mode",
            json={"enabled": False},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["flag"] == "dark_mode"
        assert data["enabled"] is False
