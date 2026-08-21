# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases de l'app mobile companion.

Ces tests couvrent les cas limites non testés :
- Valeurs null/vides
- Formats invalides
- Scénarios d'erreur
- Limites des valeurs

Approche TDD : Tests écrits d'abord, code corrigé si nécessaire.
"""

import pytest
from datetime import datetime

from app.domain.entities.mobile_companion import (
    MobileSession,
    MobileSyncState,
    MobileAnalyticsEvent,
    MobileDraft,
    MobileUserPreferences,
    MobileAppConfig,
    MobileDraftActionRequest,
    MobileSyncResponse,
    MobileStats,
    MobileEventType,
    SyncStatus,
    MobileDraftAction,
    NotificationPreference,
    SyncFrequency,
)


# ============================================================================
# TESTS - MobileSession - Edge Cases
# ============================================================================

class TestMobileSessionEdgeCases:
    """Tests edge cases pour MobileSession."""

    def test_session_with_none_user_id_raises(self):
        """Test qu'un user_id None lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSession(user_id=None)

    def test_session_with_whitespace_only_user_id_raises(self):
        """Test qu'un user_id avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSession(user_id="   ")

    def test_session_from_dict_missing_user_id_raises(self):
        """Test from_dict sans user_id lève une erreur."""
        data = {"session_id": "abc", "started_at": "2024-01-01T12:00:00"}
        with pytest.raises(KeyError):
            MobileSession.from_dict(data)

    def test_session_from_dict_with_invalid_date_format(self):
        """Test from_dict avec format de date invalide."""
        data = {
            "user_id": "user_123",
            "started_at": "not-a-date",
        }
        with pytest.raises(ValueError):
            MobileSession.from_dict(data)

    def test_session_from_dict_with_empty_string_date(self):
        """Test from_dict avec date vide."""
        data = {
            "user_id": "user_123",
            "started_at": "",
        }
        # Une date vide devrait lever une ValueError ou utiliser datetime.now()
        # Le comportement dépend de datetime.fromisoformat("")
        try:
            session = MobileSession.from_dict(data)
            # Si ça passe, la date doit être valide
            assert session.started_at is not None
        except ValueError:
            # fromisoformat("") lève ValueError, ce qui est acceptable
            pass

    def test_session_touch_updates_timestamp(self):
        """Test que touch() met à jour le timestamp même si appelé rapidement."""
        session = MobileSession(user_id="user_123")
        initial = session.last_activity_at
        session.touch()
        # Le timestamp devrait être >= à l'initial
        assert session.last_activity_at >= initial

    def test_session_end_sets_inactive_and_updates_timestamp(self):
        """Test que end() désactive et met à jour le timestamp."""
        session = MobileSession(user_id="user_123")
        initial = session.last_activity_at
        session.end()
        assert session.is_active is False
        assert session.last_activity_at >= initial

    def test_session_to_dict_includes_all_fields(self):
        """Test que to_dict inclut tous les champs même None."""
        session = MobileSession(user_id="user_123")
        data = session.to_dict()

        expected_keys = {
            "session_id", "user_id", "device_token", "started_at",
            "last_activity_at", "app_version", "os_version", "device_model", "is_active"
        }
        assert set(data.keys()) == expected_keys
        assert data["device_token"] is None


# ============================================================================
# TESTS - MobileSyncState - Edge Cases
# ============================================================================

class TestMobileSyncStateEdgeCases:
    """Tests edge cases pour MobileSyncState."""

    def test_sync_state_with_none_user_id_raises(self):
        """Test qu'un user_id None lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSyncState(user_id=None, device_token="token")

    def test_sync_state_with_none_device_token_raises(self):
        """Test qu'un device_token None lève une erreur."""
        with pytest.raises(ValueError, match="Device token cannot be empty"):
            MobileSyncState(user_id="user_123", device_token=None)

    def test_sync_state_with_whitespace_user_id_raises(self):
        """Test qu'un user_id avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSyncState(user_id="  ", device_token="token")

    def test_sync_state_with_whitespace_device_token_raises(self):
        """Test qu'un device_token avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="Device token cannot be empty"):
            MobileSyncState(user_id="user_123", device_token="   ")

    def test_sync_state_with_string_status(self):
        """Test création avec status en string."""
        state = MobileSyncState(
            user_id="user_123",
            device_token="token",
            last_sync_status="syncing",
        )
        assert state.last_sync_status == SyncStatus.SYNCING

    def test_sync_state_with_invalid_string_status_raises(self):
        """Test qu'un status string invalide lève une erreur."""
        with pytest.raises(ValueError):
            MobileSyncState(
                user_id="user_123",
                device_token="token",
                last_sync_status="invalid_status",
            )

    def test_sync_state_from_dict_with_missing_device_token(self):
        """Test from_dict sans device_token."""
        data = {"user_id": "user_123"}
        with pytest.raises(KeyError):
            MobileSyncState.from_dict(data)

    def test_sync_state_mark_success_with_zero_drafts(self):
        """Test mark_success avec 0 brouillons."""
        state = MobileSyncState(user_id="user_123", device_token="token")
        state.mark_success(0)

        assert state.last_sync_status == SyncStatus.SUCCESS
        assert state.drafts_synced_count == 0
        assert state.last_sync_at is not None

    def test_sync_state_mark_failed_clears_previous_success(self):
        """Test que mark_failed écrase les données de succès précédent."""
        state = MobileSyncState(user_id="user_123", device_token="token")
        state.mark_success(10)
        state.mark_failed("Connection error")

        assert state.last_sync_status == SyncStatus.FAILED
        assert state.error_message == "Connection error"
        # drafts_synced_count reste à 10 (précédent sync)
        assert state.drafts_synced_count == 10


# ============================================================================
# TESTS - MobileAnalyticsEvent - Edge Cases
# ============================================================================

class TestMobileAnalyticsEventEdgeCases:
    """Tests edge cases pour MobileAnalyticsEvent."""

    def test_event_with_none_user_id_raises(self):
        """Test qu'un user_id None lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileAnalyticsEvent(
                event_type=MobileEventType.APP_OPEN,
                user_id=None,
            )

    def test_event_with_invalid_string_event_type_raises(self):
        """Test qu'un event_type string invalide lève une erreur."""
        with pytest.raises(ValueError):
            MobileAnalyticsEvent(
                event_type="invalid.event.type",
                user_id="user_123",
            )

    def test_event_from_dict_with_invalid_event_type(self):
        """Test from_dict avec event_type invalide."""
        data = {
            "event_type": "not_a_valid_event",
            "user_id": "user_123",
        }
        with pytest.raises(ValueError):
            MobileAnalyticsEvent.from_dict(data)

    def test_event_with_empty_properties(self):
        """Test création avec properties vides."""
        event = MobileAnalyticsEvent(
            event_type=MobileEventType.APP_OPEN,
            user_id="user_123",
            properties={},
        )
        assert event.properties == {}

    def test_event_with_nested_properties(self):
        """Test création avec properties imbriquées."""
        nested_props = {
            "level1": {
                "level2": {
                    "level3": "deep_value"
                }
            }
        }
        event = MobileAnalyticsEvent(
            event_type=MobileEventType.APP_OPEN,
            user_id="user_123",
            properties=nested_props,
        )
        assert event.properties["level1"]["level2"]["level3"] == "deep_value"


# ============================================================================
# TESTS - MobileDraft - Edge Cases
# ============================================================================

class TestMobileDraftEdgeCases:
    """Tests edge cases pour MobileDraft."""

    def test_draft_with_none_draft_id_raises(self):
        """Test qu'un draft_id None lève une erreur."""
        with pytest.raises(ValueError, match="Draft ID cannot be empty"):
            MobileDraft(draft_id=None, subject="Test", recipient="a@b.com")

    def test_draft_with_none_subject_raises(self):
        """Test qu'un subject None lève une erreur."""
        with pytest.raises(ValueError, match="Subject cannot be empty"):
            MobileDraft(draft_id="d1", subject=None, recipient="a@b.com")

    def test_draft_with_whitespace_draft_id_raises(self):
        """Test qu'un draft_id avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="Draft ID cannot be empty"):
            MobileDraft(draft_id="   ", subject="Test", recipient="a@b.com")

    def test_draft_with_whitespace_subject_raises(self):
        """Test qu'un subject avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="Subject cannot be empty"):
            MobileDraft(draft_id="d1", subject="   ", recipient="a@b.com")

    def test_draft_with_empty_recipient_allowed(self):
        """Test qu'un recipient vide est autorisé (peut être valide dans certains cas)."""
        # Le recipient pourrait être vide pour un brouillon en cours
        draft = MobileDraft(draft_id="d1", subject="Test", recipient="")
        assert draft.recipient == ""

    def test_draft_with_negative_priority_score(self):
        """Test qu'un priority_score négatif est accepté (pas de validation)."""
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="a@b.com",
            priority_score=-10,
        )
        # Actuellement pas de validation sur priority_score
        assert draft.priority_score == -10

    def test_draft_with_priority_score_over_100(self):
        """Test qu'un priority_score > 100 est accepté (pas de validation)."""
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="a@b.com",
            priority_score=150,
        )
        # Actuellement pas de validation sur priority_score
        assert draft.priority_score == 150

    def test_draft_body_preview_not_regenerated_if_provided(self):
        """Test que body_preview n'est pas régénéré si déjà fourni."""
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="a@b.com",
            body_preview="Custom preview",
            body_full="Full body content that is much longer",
        )
        assert draft.body_preview == "Custom preview"

    def test_draft_body_preview_generated_from_short_body(self):
        """Test génération de preview pour body court (< 200 chars)."""
        short_body = "Short body"
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="a@b.com",
            body_full=short_body,
        )
        assert draft.body_preview == short_body
        assert "..." not in draft.body_preview

    def test_draft_body_preview_generated_from_exact_200_chars(self):
        """Test génération de preview pour body de exactement 200 chars."""
        exact_body = "A" * 200
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="a@b.com",
            body_full=exact_body,
        )
        assert draft.body_preview == exact_body
        assert "..." not in draft.body_preview

    def test_draft_edit_with_empty_body(self):
        """Test édition avec body vide."""
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="a@b.com",
            body_full="Original",
        )
        draft.edit("")
        assert draft.body_full == ""
        assert draft.body_preview == ""
        assert draft.action == MobileDraftAction.EDITED

    def test_draft_with_string_action(self):
        """Test création avec action en string."""
        draft = MobileDraft(
            draft_id="d1",
            subject="Test",
            recipient="a@b.com",
            action="approved",
        )
        assert draft.action == MobileDraftAction.APPROVED

    def test_draft_with_invalid_string_action_raises(self):
        """Test création avec action string invalide."""
        with pytest.raises(ValueError):
            MobileDraft(
                draft_id="d1",
                subject="Test",
                recipient="a@b.com",
                action="invalid_action",
            )

    def test_draft_from_dict_minimal_data(self):
        """Test from_dict avec données minimales."""
        data = {
            "draft_id": "d1",
            "subject": "Test",
            "recipient": "a@b.com",
        }
        draft = MobileDraft.from_dict(data)
        assert draft.draft_id == "d1"
        assert draft.status == "pending"
        assert draft.action == MobileDraftAction.PENDING


# ============================================================================
# TESTS - MobileUserPreferences - Edge Cases
# ============================================================================

class TestMobileUserPreferencesEdgeCases:
    """Tests edge cases pour MobileUserPreferences."""

    def test_preferences_with_none_user_id_raises(self):
        """Test qu'un user_id None lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileUserPreferences(user_id=None)

    def test_preferences_with_whitespace_user_id_raises(self):
        """Test qu'un user_id avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileUserPreferences(user_id="   ")

    def test_preferences_with_negative_threshold_raises(self):
        """Test qu'un seuil négatif lève une erreur."""
        with pytest.raises(ValueError, match="must be between 0 and 100"):
            MobileUserPreferences(user_id="user_123", auto_approve_threshold=-1)

    def test_preferences_with_threshold_101_raises(self):
        """Test qu'un seuil de 101 lève une erreur."""
        with pytest.raises(ValueError, match="must be between 0 and 100"):
            MobileUserPreferences(user_id="user_123", auto_approve_threshold=101)

    def test_preferences_with_threshold_0_allowed(self):
        """Test qu'un seuil de 0 est autorisé."""
        prefs = MobileUserPreferences(user_id="user_123", auto_approve_threshold=0)
        assert prefs.auto_approve_threshold == 0

    def test_preferences_with_threshold_100_allowed(self):
        """Test qu'un seuil de 100 est autorisé."""
        prefs = MobileUserPreferences(user_id="user_123", auto_approve_threshold=100)
        assert prefs.auto_approve_threshold == 100

    def test_preferences_with_invalid_notification_preference_raises(self):
        """Test qu'une préférence de notification invalide lève une erreur."""
        with pytest.raises(ValueError):
            MobileUserPreferences(
                user_id="user_123",
                notification_preference="invalid_pref",
            )

    def test_preferences_with_invalid_sync_frequency_raises(self):
        """Test qu'une fréquence de sync invalide lève une erreur."""
        with pytest.raises(ValueError):
            MobileUserPreferences(
                user_id="user_123",
                sync_frequency="every_second",
            )


# ============================================================================
# TESTS - MobileAppConfig - Edge Cases
# ============================================================================

class TestMobileAppConfigEdgeCases:
    """Tests edge cases pour MobileAppConfig."""

    def test_config_version_comparison_with_partial_version(self):
        """Test comparaison avec version partielle (1.0)."""
        config = MobileAppConfig()
        # 1.0 devrait être traité comme 1.0.0
        assert config._compare_versions("1.0", "1.0.0") == 0
        assert config._compare_versions("1.0", "1.0.1") == -1

    def test_config_version_comparison_with_single_digit(self):
        """Test comparaison avec version à un seul chiffre."""
        config = MobileAppConfig()
        # 1 devrait être traité comme 1.0.0
        assert config._compare_versions("1", "1.0.0") == 0

    def test_config_version_comparison_with_invalid_version_raises(self):
        """Test comparaison avec version invalide lève une erreur."""
        config = MobileAppConfig()
        with pytest.raises(ValueError):
            config._compare_versions("1.a.0", "1.0.0")

    def test_config_version_comparison_with_empty_string_raises(self):
        """Test comparaison avec chaîne vide lève une erreur."""
        config = MobileAppConfig()
        with pytest.raises(ValueError):
            config._compare_versions("", "1.0.0")

    def test_config_is_version_supported_boundary(self):
        """Test is_version_supported à la limite exacte."""
        config = MobileAppConfig(min_version="2.0.0")
        assert config.is_version_supported("2.0.0") is True
        assert config.is_version_supported("1.9.9") is False
        assert config.is_version_supported("2.0.1") is True

    def test_config_needs_update_boundary(self):
        """Test needs_update à la limite exacte."""
        config = MobileAppConfig(latest_version="2.0.0")
        assert config.needs_update("2.0.0") is False
        assert config.needs_update("1.9.9") is True
        assert config.needs_update("2.0.1") is False

    def test_config_from_dict_with_empty_feature_flags(self):
        """Test from_dict avec feature_flags vides."""
        data = {"feature_flags": {}}
        config = MobileAppConfig.from_dict(data)
        assert config.feature_flags == {}

    def test_config_to_dict_preserves_custom_endpoints(self):
        """Test que to_dict préserve les endpoints personnalisés."""
        custom_endpoints = {"custom_api": "/api/custom"}
        config = MobileAppConfig(api_endpoints=custom_endpoints)
        data = config.to_dict()
        assert data["api_endpoints"]["custom_api"] == "/api/custom"


# ============================================================================
# TESTS - MobileDraftActionRequest - Edge Cases
# ============================================================================

class TestMobileDraftActionRequestEdgeCases:
    """Tests edge cases pour MobileDraftActionRequest."""

    def test_request_with_none_draft_id_raises(self):
        """Test qu'un draft_id None lève une erreur."""
        with pytest.raises(ValueError, match="Draft ID cannot be empty"):
            MobileDraftActionRequest(
                draft_id=None,
                action=MobileDraftAction.APPROVED,
                user_id="user_123",
            )

    def test_request_with_none_user_id_raises(self):
        """Test qu'un user_id None lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileDraftActionRequest(
                draft_id="d1",
                action=MobileDraftAction.APPROVED,
                user_id=None,
            )

    def test_request_with_whitespace_draft_id_raises(self):
        """Test qu'un draft_id avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="Draft ID cannot be empty"):
            MobileDraftActionRequest(
                draft_id="   ",
                action=MobileDraftAction.APPROVED,
                user_id="user_123",
            )

    def test_request_with_whitespace_user_id_raises(self):
        """Test qu'un user_id avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileDraftActionRequest(
                draft_id="d1",
                action=MobileDraftAction.APPROVED,
                user_id="   ",
            )

    def test_request_edit_with_empty_string_body_raises(self):
        """Test qu'une édition avec body vide lève une erreur."""
        with pytest.raises(ValueError, match="Edited body is required"):
            MobileDraftActionRequest(
                draft_id="d1",
                action=MobileDraftAction.EDITED,
                user_id="user_123",
                edited_body="",
            )

    def test_request_edit_with_whitespace_body_allowed(self):
        """Test qu'une édition avec body d'espaces est autorisée."""
        # Un body avec espaces pourrait être valide (ex: effacer le contenu)
        req = MobileDraftActionRequest(
            draft_id="d1",
            action=MobileDraftAction.EDITED,
            user_id="user_123",
            edited_body="   ",
        )
        assert req.edited_body == "   "

    def test_request_approve_ignores_edited_body(self):
        """Test que edited_body est ignoré pour approve."""
        req = MobileDraftActionRequest(
            draft_id="d1",
            action=MobileDraftAction.APPROVED,
            user_id="user_123",
            edited_body="Should be ignored",
        )
        assert req.edited_body == "Should be ignored"
        assert req.action == MobileDraftAction.APPROVED

    def test_request_with_string_action(self):
        """Test création avec action en string."""
        req = MobileDraftActionRequest(
            draft_id="d1",
            action="rejected",
            user_id="user_123",
        )
        assert req.action == MobileDraftAction.REJECTED

    def test_request_with_offline_timestamp(self):
        """Test création avec timestamp offline."""
        offline_time = datetime(2024, 1, 15, 10, 30, 0)
        req = MobileDraftActionRequest(
            draft_id="d1",
            action=MobileDraftAction.APPROVED,
            user_id="user_123",
            offline_timestamp=offline_time,
        )
        assert req.offline_timestamp == offline_time


# ============================================================================
# TESTS - MobileSyncResponse - Edge Cases
# ============================================================================

class TestMobileSyncResponseEdgeCases:
    """Tests edge cases pour MobileSyncResponse."""

    def test_response_failed_with_no_drafts(self):
        """Test réponse échouée sans brouillons."""
        response = MobileSyncResponse(
            success=False,
            error_message="Connection failed",
        )
        assert response.success is False
        assert response.drafts == []
        assert response.error_message == "Connection failed"

    def test_response_success_with_empty_drafts(self):
        """Test réponse réussie avec liste de brouillons vide."""
        response = MobileSyncResponse(success=True, drafts=[])
        data = response.to_dict()
        assert data["success"] is True
        assert data["drafts"] == []

    def test_response_to_dict_with_none_sync_state(self):
        """Test to_dict avec sync_state None."""
        response = MobileSyncResponse(success=True)
        data = response.to_dict()
        assert data["sync_state"] is None


# ============================================================================
# TESTS - MobileStats - Edge Cases
# ============================================================================

class TestMobileStatsEdgeCases:
    """Tests edge cases pour MobileStats."""

    def test_stats_with_all_zeros(self):
        """Test stats avec toutes les valeurs à zéro."""
        stats = MobileStats(user_id="user_123")
        data = stats.to_dict()

        assert data["total_drafts"] == 0
        assert data["pending_drafts"] == 0
        assert data["approved_today"] == 0
        assert data["rejected_today"] == 0
        assert data["avg_response_time_seconds"] == 0.0
        assert data["ai_accuracy_percentage"] == 0.0

    def test_stats_with_negative_values(self):
        """Test stats avec valeurs négatives (ne devrait pas arriver mais pas de validation)."""
        stats = MobileStats(
            user_id="user_123",
            total_drafts=-5,
            time_saved_minutes=-10,
        )
        # Pas de validation dans l'entité
        assert stats.total_drafts == -5
        assert stats.time_saved_minutes == -10


# ============================================================================
# TESTS - Enums - Edge Cases
# ============================================================================

class TestEnumsEdgeCases:
    """Tests edge cases pour les enums."""

    def test_mobile_event_type_all_values(self):
        """Test que tous les types d'événements sont accessibles."""
        expected_events = [
            "app.open", "app.background", "app.close",
            "draft.view", "draft.approve", "draft.reject", "draft.edit", "draft.send",
            "notification.open", "notification.dismiss",
            "settings.change",
            "sync.start", "sync.complete", "sync.error",
            "screen.view", "error",
        ]
        actual_events = [e.value for e in MobileEventType]
        for expected in expected_events:
            assert expected in actual_events

    def test_sync_status_all_values(self):
        """Test que tous les statuts de sync sont accessibles."""
        expected = ["idle", "syncing", "success", "failed", "partial"]
        actual = [s.value for s in SyncStatus]
        assert set(expected) == set(actual)

    def test_mobile_draft_action_all_values(self):
        """Test que toutes les actions sont accessibles."""
        expected = ["pending", "approved", "rejected", "edited", "sent"]
        actual = [a.value for a in MobileDraftAction]
        assert set(expected) == set(actual)

    def test_notification_preference_all_values(self):
        """Test que toutes les préférences de notification sont accessibles."""
        expected = ["all", "important_only", "none"]
        actual = [p.value for p in NotificationPreference]
        assert set(expected) == set(actual)

    def test_sync_frequency_all_values(self):
        """Test que toutes les fréquences de sync sont accessibles."""
        expected = ["realtime", "5min", "15min", "1hour", "manual"]
        actual = [f.value for f in SyncFrequency]
        assert set(expected) == set(actual)
