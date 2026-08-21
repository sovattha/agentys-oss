# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases des Use Cases.

Ces tests couvrent les cas limites non testés :
- Exceptions dans les ports
- Données invalides
- Scénarios d'erreur complexes
- Comportements aux limites

Approche TDD : Tests écrits d'abord, code corrigé si nécessaire.
Clean Architecture : Tests unitaires des Use Cases avec mocks des ports.
"""

from datetime import datetime, timedelta
from unittest.mock import Mock

from app.domain.entities.mobile_companion import (
    MobileSession,
    MobileSyncState,
    MobileDraft,
    MobileUserPreferences,
    MobileAppConfig,
    MobileDraftActionRequest,
    MobileDraftAction,
)


# ============================================================================
# TESTS - StartMobileSessionUseCase - Edge Cases
# ============================================================================

class TestStartMobileSessionUseCaseEdgeCases:
    """Tests edge cases pour StartMobileSessionUseCase."""

    def test_start_session_port_raises_exception(self):
        """Test quand session_port.create lève une exception."""
        from app.application.mobile_companion import StartMobileSessionUseCase

        session_port = Mock()
        config_port = Mock()
        preferences_port = Mock()

        config_port.get.return_value = MobileAppConfig()
        session_port.create.side_effect = RuntimeError("Database connection failed")

        uc = StartMobileSessionUseCase(
            session_port=session_port,
            config_port=config_port,
            preferences_port=preferences_port,
        )

        result = uc.execute(user_id="user_123")

        assert result.success is False
        assert "Database connection failed" in result.error_message

    def test_start_session_config_port_raises_exception(self):
        """Test quand config_port.get lève une exception."""
        from app.application.mobile_companion import StartMobileSessionUseCase

        session_port = Mock()
        config_port = Mock()
        preferences_port = Mock()

        config_port.get.side_effect = RuntimeError("Config not available")

        uc = StartMobileSessionUseCase(
            session_port=session_port,
            config_port=config_port,
            preferences_port=preferences_port,
        )

        result = uc.execute(user_id="user_123")

        assert result.success is False
        assert "Config not available" in result.error_message

    def test_start_session_preferences_port_returns_none(self):
        """Test quand preferences_port.get retourne None."""
        from app.application.mobile_companion import StartMobileSessionUseCase

        session_port = Mock()
        config_port = Mock()
        preferences_port = Mock()

        session_port.create.return_value = MobileSession(user_id="user_123")
        config_port.get.return_value = MobileAppConfig()
        preferences_port.get.return_value = None
        preferences_port.save.return_value = MobileUserPreferences(user_id="user_123")

        uc = StartMobileSessionUseCase(
            session_port=session_port,
            config_port=config_port,
            preferences_port=preferences_port,
        )

        result = uc.execute(user_id="user_123")

        assert result.success is True
        # Devrait créer des préférences par défaut
        preferences_port.save.assert_called_once()

    def test_start_session_with_exact_min_version(self):
        """Test avec version exactement égale à min_version."""
        from app.application.mobile_companion import StartMobileSessionUseCase

        session_port = Mock()
        config_port = Mock()
        preferences_port = Mock()

        config = MobileAppConfig(min_version="2.0.0")
        config_port.get.return_value = config
        session_port.create.return_value = MobileSession(user_id="user_123")
        preferences_port.get.return_value = MobileUserPreferences(user_id="user_123")

        uc = StartMobileSessionUseCase(
            session_port=session_port,
            config_port=config_port,
            preferences_port=preferences_port,
        )

        result = uc.execute(user_id="user_123", app_version="2.0.0")

        assert result.success is True

    def test_start_session_with_version_below_min(self):
        """Test avec version en-dessous de min_version."""
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

        result = uc.execute(user_id="user_123", app_version="1.9.9")

        assert result.success is False
        assert "not supported" in result.error_message
        # Session ne devrait pas être créée
        session_port.create.assert_not_called()

    def test_start_session_maintenance_mode_with_message(self):
        """Test en mode maintenance avec message personnalisé."""
        from app.application.mobile_companion import StartMobileSessionUseCase

        session_port = Mock()
        config_port = Mock()
        preferences_port = Mock()

        config = MobileAppConfig(
            maintenance_mode=True,
            maintenance_message="Server update in progress",
        )
        config_port.get.return_value = config

        uc = StartMobileSessionUseCase(
            session_port=session_port,
            config_port=config_port,
            preferences_port=preferences_port,
        )

        result = uc.execute(user_id="user_123")

        assert result.success is False
        assert "maintenance" in result.error_message.lower() or "Server update" in result.error_message

    def test_start_session_maintenance_mode_without_message(self):
        """Test en mode maintenance sans message personnalisé."""
        from app.application.mobile_companion import StartMobileSessionUseCase

        session_port = Mock()
        config_port = Mock()
        preferences_port = Mock()

        config = MobileAppConfig(
            maintenance_mode=True,
            maintenance_message=None,
        )
        config_port.get.return_value = config

        uc = StartMobileSessionUseCase(
            session_port=session_port,
            config_port=config_port,
            preferences_port=preferences_port,
        )

        result = uc.execute(user_id="user_123")

        assert result.success is False
        assert result.error_message is not None


# ============================================================================
# TESTS - EndMobileSessionUseCase - Edge Cases
# ============================================================================

class TestEndMobileSessionUseCaseEdgeCases:
    """Tests edge cases pour EndMobileSessionUseCase."""

    def test_end_session_not_found(self):
        """Test fin de session inexistante."""
        from app.application.mobile_companion import EndMobileSessionUseCase

        session_port = Mock()
        analytics_port = Mock()

        session_port.end.return_value = False

        uc = EndMobileSessionUseCase(
            session_port=session_port,
            analytics_port=analytics_port,
        )

        result = uc.execute(session_id="nonexistent", user_id="user_123")

        assert result is False
        # Analytics ne devrait pas être appelé
        analytics_port.track_event.assert_not_called()

    def test_end_session_port_raises_exception(self):
        """Test quand session_port.end lève une exception."""
        from app.application.mobile_companion import EndMobileSessionUseCase

        session_port = Mock()
        analytics_port = Mock()

        session_port.end.side_effect = RuntimeError("Database error")

        uc = EndMobileSessionUseCase(
            session_port=session_port,
            analytics_port=analytics_port,
        )

        result = uc.execute(session_id="session_123", user_id="user_123")

        assert result is False

    def test_end_session_analytics_fails_silently(self):
        """Test que l'échec analytics n'empêche pas la fin de session."""
        from app.application.mobile_companion import EndMobileSessionUseCase

        session_port = Mock()
        analytics_port = Mock()

        session_port.end.return_value = True
        analytics_port.track_event.side_effect = RuntimeError("Analytics unavailable")

        uc = EndMobileSessionUseCase(
            session_port=session_port,
            analytics_port=analytics_port,
        )

        # Ne devrait pas lever d'exception
        uc.execute(session_id="session_123", user_id="user_123")

        # Le résultat dépend de l'implémentation - on vérifie juste qu'il n'y a pas d'exception


# ============================================================================
# TESTS - SyncMobileDataUseCase - Edge Cases
# ============================================================================

class TestSyncMobileDataUseCaseEdgeCases:
    """Tests edge cases pour SyncMobileDataUseCase."""

    def test_sync_with_exception_during_sync(self):
        """Test exception pendant la synchronisation."""
        from app.application.mobile_companion import SyncMobileDataUseCase

        sync_port = Mock()
        analytics_port = Mock()

        sync_port.get_sync_state.return_value = None
        sync_port.get_drafts_since.side_effect = RuntimeError("Network error")
        sync_port.update_sync_state.return_value = None
        analytics_port.track_event.return_value = True

        uc = SyncMobileDataUseCase(
            sync_port=sync_port,
            analytics_port=analytics_port,
        )

        result = uc.execute(user_id="user_123", device_token="token")

        assert result.success is False
        assert "Network error" in result.error_message

    def test_sync_with_existing_sync_state(self):
        """Test sync avec état existant."""
        from app.application.mobile_companion import SyncMobileDataUseCase

        sync_port = Mock()
        analytics_port = Mock()

        existing_state = MobileSyncState(
            user_id="user_123",
            device_token="token",
            last_sync_at=datetime.now() - timedelta(hours=1),
        )
        sync_port.get_sync_state.return_value = existing_state
        sync_port.get_drafts_since.return_value = ([], None, False)
        sync_port.update_sync_state.return_value = existing_state
        analytics_port.track_event.return_value = True

        uc = SyncMobileDataUseCase(
            sync_port=sync_port,
            analytics_port=analytics_port,
        )

        result = uc.execute(user_id="user_123", device_token="token")

        assert result.success is True
        # Devrait utiliser last_sync_at de l'état existant
        sync_port.get_drafts_since.assert_called_once()

    def test_sync_with_pagination(self):
        """Test sync avec pagination."""
        from app.application.mobile_companion import SyncMobileDataUseCase

        sync_port = Mock()
        analytics_port = Mock()

        drafts = [
            MobileDraft(draft_id=f"d{i}", subject=f"Draft {i}", recipient="a@b.com")
            for i in range(10)
        ]
        sync_port.get_sync_state.return_value = None
        sync_port.get_drafts_since.return_value = (drafts, "cursor_abc", True)
        sync_port.update_sync_state.return_value = MobileSyncState(
            user_id="user_123", device_token="token"
        )
        analytics_port.track_event.return_value = True

        uc = SyncMobileDataUseCase(
            sync_port=sync_port,
            analytics_port=analytics_port,
        )

        result = uc.execute(user_id="user_123", device_token="token", limit=10)

        assert result.success is True
        assert result.has_more is True
        assert result.next_cursor == "cursor_abc"

    def test_sync_marks_state_failed_on_error(self):
        """Test que l'état est marqué comme échoué en cas d'erreur."""
        from app.application.mobile_companion import SyncMobileDataUseCase

        sync_port = Mock()
        analytics_port = Mock()

        initial_state = MobileSyncState(user_id="user_123", device_token="token")
        sync_port.get_sync_state.return_value = initial_state
        sync_port.get_drafts_since.side_effect = RuntimeError("Sync failed")
        analytics_port.track_event.return_value = True

        uc = SyncMobileDataUseCase(
            sync_port=sync_port,
            analytics_port=analytics_port,
        )

        result = uc.execute(user_id="user_123", device_token="token")

        assert result.success is False
        # L'état devrait avoir été mis à jour avec l'échec
        sync_port.update_sync_state.assert_called()


# ============================================================================
# TESTS - ApplyDraftActionUseCase - Edge Cases
# ============================================================================

class TestApplyDraftActionUseCaseEdgeCases:
    """Tests edge cases pour ApplyDraftActionUseCase."""

    def test_action_port_returns_false(self):
        """Test quand action_port.apply_action retourne False."""
        from app.application.mobile_companion import ApplyDraftActionUseCase

        action_port = Mock()
        sync_port = Mock()
        analytics_port = Mock()

        action_port.apply_action.return_value = False

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

        assert result.success is False
        assert "Failed to apply action" in result.error_message

    def test_action_draft_not_found_after_action(self):
        """Test quand le brouillon n'est pas trouvé après l'action."""
        from app.application.mobile_companion import ApplyDraftActionUseCase

        action_port = Mock()
        sync_port = Mock()
        analytics_port = Mock()

        action_port.apply_action.return_value = True
        sync_port.get_draft.return_value = None
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
        assert result.draft is None

    def test_action_port_raises_exception(self):
        """Test quand action_port lève une exception."""
        from app.application.mobile_companion import ApplyDraftActionUseCase

        action_port = Mock()
        sync_port = Mock()
        analytics_port = Mock()

        action_port.apply_action.side_effect = RuntimeError("Database error")

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

        assert result.success is False
        assert "Database error" in result.error_message

    def test_action_with_offline_timestamp(self):
        """Test action avec timestamp offline."""
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

        offline_time = datetime(2024, 1, 15, 10, 30, 0)
        request = MobileDraftActionRequest(
            draft_id="d1",
            action=MobileDraftAction.APPROVED,
            user_id="user_123",
            offline_timestamp=offline_time,
        )

        result = uc.execute(request)

        assert result.success is True
        # Vérifier que le flag offline est dans les analytics
        call_args = analytics_port.track_event.call_args[0][0]
        assert call_args.properties.get("offline") is True


# ============================================================================
# TESTS - ApplyBatchActionsUseCase - Edge Cases
# ============================================================================

class TestApplyBatchActionsUseCaseEdgeCases:
    """Tests edge cases pour ApplyBatchActionsUseCase."""

    def test_batch_empty_list(self):
        """Test batch avec liste vide."""
        from app.application.mobile_companion import ApplyBatchActionsUseCase

        action_port = Mock()
        analytics_port = Mock()

        action_port.apply_batch_actions.return_value = {}

        uc = ApplyBatchActionsUseCase(
            action_port=action_port,
            analytics_port=analytics_port,
        )

        result = uc.execute(requests=[], user_id="user_123")

        assert result.success is True
        assert result.error_count == 0

    def test_batch_all_failures(self):
        """Test batch avec tous échecs."""
        from app.application.mobile_companion import ApplyBatchActionsUseCase

        action_port = Mock()
        analytics_port = Mock()

        action_port.apply_batch_actions.return_value = {
            "d1": False,
            "d2": False,
            "d3": False,
        }

        uc = ApplyBatchActionsUseCase(
            action_port=action_port,
            analytics_port=analytics_port,
        )

        requests = [
            MobileDraftActionRequest(draft_id=f"d{i}", action=MobileDraftAction.APPROVED, user_id="user_123")
            for i in range(1, 4)
        ]

        result = uc.execute(requests=requests, user_id="user_123")

        assert result.success is False
        assert result.error_count == 3

    def test_batch_partial_failures(self):
        """Test batch avec échecs partiels."""
        from app.application.mobile_companion import ApplyBatchActionsUseCase

        action_port = Mock()
        analytics_port = Mock()

        action_port.apply_batch_actions.return_value = {
            "d1": True,
            "d2": False,
            "d3": True,
        }
        analytics_port.track_event.return_value = True

        uc = ApplyBatchActionsUseCase(
            action_port=action_port,
            analytics_port=analytics_port,
        )

        requests = [
            MobileDraftActionRequest(draft_id=f"d{i}", action=MobileDraftAction.APPROVED, user_id="user_123")
            for i in range(1, 4)
        ]

        result = uc.execute(requests=requests, user_id="user_123")

        assert result.success is False  # Au moins un échec
        assert result.error_count == 1

    def test_batch_exception(self):
        """Test exception pendant le batch."""
        from app.application.mobile_companion import ApplyBatchActionsUseCase

        action_port = Mock()
        analytics_port = Mock()

        action_port.apply_batch_actions.side_effect = RuntimeError("Batch failed")

        uc = ApplyBatchActionsUseCase(
            action_port=action_port,
            analytics_port=analytics_port,
        )

        requests = [
            MobileDraftActionRequest(draft_id="d1", action=MobileDraftAction.APPROVED, user_id="user_123")
        ]

        result = uc.execute(requests=requests, user_id="user_123")

        assert result.success is False
        assert result.error_count == 1


# ============================================================================
# TESTS - SendPushNotificationUseCase - Edge Cases
# ============================================================================

class TestSendPushNotificationUseCaseEdgeCases:
    """Tests edge cases pour SendPushNotificationUseCase."""

    def test_execute_with_invalid_token(self):
        """Test envoi avec token invalide."""
        from app.application.send_push_notification import SendPushNotificationUseCase
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter(invalid_tokens=["invalid_token"])
        uc = SendPushNotificationUseCase(notification_adapter=adapter)

        result = uc.execute(
            device_token="invalid_token",
            title="Test",
            body="Body",
        )

        assert result.success is False
        assert result.error_code == "INVALID_TOKEN"

    def test_execute_adapter_in_failure_mode(self):
        """Test avec adapter en mode échec."""
        from app.application.send_push_notification import SendPushNotificationUseCase
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter(should_fail=True, failure_error="Service unavailable")
        uc = SendPushNotificationUseCase(notification_adapter=adapter)

        result = uc.execute(
            device_token="token",
            title="Test",
            body="Body",
        )

        assert result.success is False
        assert "Service unavailable" in result.error_message

    def test_execute_batch_with_empty_list(self):
        """Test batch avec liste vide."""
        from app.application.send_push_notification import SendPushNotificationUseCase
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter()
        uc = SendPushNotificationUseCase(notification_adapter=adapter)

        results = uc.execute_batch(
            device_tokens=[],
            title="Test",
            body="Body",
        )

        assert results == []

    def test_notify_draft_created_with_high_priority(self):
        """Test notification brouillon avec priorité élevée."""
        from app.application.send_push_notification import SendPushNotificationUseCase
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter()
        uc = SendPushNotificationUseCase(notification_adapter=adapter)

        results = uc.notify_draft_created(
            device_tokens=["token1"],
            recipient="john@example.com",
            subject="Urgent Meeting",
            draft_id="draft_123",
            priority_score=95,
        )

        assert len(results) == 1
        assert results[0].success is True

        # Vérifier les données de la notification
        notif = adapter.sent_notifications[0]
        assert notif.data["priority_score"] == 95

    def test_notify_budget_warning_calculations(self):
        """Test calcul du pourcentage budget."""
        from app.application.send_push_notification import SendPushNotificationUseCase
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter()
        uc = SendPushNotificationUseCase(notification_adapter=adapter)

        results = uc.notify_budget_warning(
            device_tokens=["token1"],
            current_spend=75.0,
            budget_limit=100.0,
        )

        assert len(results) == 1
        notif = adapter.sent_notifications[0]
        assert notif.data["percent_used"] == 75.0

    def test_notify_budget_warning_zero_limit(self):
        """Test alerte budget avec limite à zéro."""
        from app.application.send_push_notification import SendPushNotificationUseCase
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter()
        uc = SendPushNotificationUseCase(notification_adapter=adapter)

        # Avec limite à 0, le calcul du pourcentage pourrait poser problème
        results = uc.notify_budget_warning(
            device_tokens=["token1"],
            current_spend=50.0,
            budget_limit=0.0,
        )

        # Le comportement dépend de l'implémentation
        # On vérifie juste qu'il n'y a pas d'exception division par zéro
        assert len(results) == 1

    def test_get_stats_empty(self):
        """Test statistiques avec aucune notification."""
        from app.application.send_push_notification import SendPushNotificationUseCase
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter()
        uc = SendPushNotificationUseCase(notification_adapter=adapter)

        stats = uc.get_stats()

        assert stats["total"] == 0
        assert stats["sent"] == 0
        assert stats["failed"] == 0

    def test_get_records_limit(self):
        """Test limite sur l'historique."""
        from app.application.send_push_notification import SendPushNotificationUseCase
        from app.adapters.push.mock_adapter import MockPushAdapter

        adapter = MockPushAdapter()
        uc = SendPushNotificationUseCase(notification_adapter=adapter)

        # Envoyer plusieurs notifications
        for i in range(10):
            uc.execute(device_token=f"token_{i}", title=f"Test {i}", body="Body")

        records = uc.get_records(limit=5)
        assert len(records) <= 5


# ============================================================================
# TESTS - PushNotificationService - Edge Cases
# ============================================================================

class TestPushNotificationServiceEdgeCases:
    """Tests edge cases pour PushNotificationService."""

    def test_notify_all_with_no_devices(self):
        """Test notification à tous sans devices enregistrés."""
        from app.application.push_notification_service import PushNotificationService
        from app.adapters.push.mock_adapter import MockPushAdapter

        device_store = Mock()
        adapter = MockPushAdapter()

        device_store.get_tokens.return_value = []

        service = PushNotificationService(
            device_store=device_store,
            notification_adapter=adapter,
        )

        count = service.notify_all_draft_created(
            recipient="john@example.com",
            subject="Test",
            draft_id="d1",
        )

        assert count == 0
        assert adapter.get_notifications_count() == 0

    def test_send_to_token_updates_last_used(self):
        """Test que send_to_token met à jour last_used."""
        from app.application.push_notification_service import PushNotificationService
        from app.adapters.push.mock_adapter import MockPushAdapter

        device_store = Mock()
        adapter = MockPushAdapter()

        service = PushNotificationService(
            device_store=device_store,
            notification_adapter=adapter,
        )

        result = service.send_to_token(
            token="test_token",
            title="Test",
            body="Body",
        )

        assert result.success is True
        device_store.update_last_used.assert_called_once_with("test_token")

    def test_send_to_token_failure_no_update(self):
        """Test que send_to_token n'update pas last_used en cas d'échec."""
        from app.application.push_notification_service import PushNotificationService
        from app.adapters.push.mock_adapter import MockPushAdapter

        device_store = Mock()
        adapter = MockPushAdapter(invalid_tokens=["bad_token"])

        service = PushNotificationService(
            device_store=device_store,
            notification_adapter=adapter,
        )

        result = service.send_to_token(
            token="bad_token",
            title="Test",
            body="Body",
        )

        assert result.success is False
        device_store.update_last_used.assert_not_called()

    def test_broadcast_mixed_results(self):
        """Test broadcast avec résultats mixtes."""
        from app.application.push_notification_service import PushNotificationService
        from app.adapters.push.mock_adapter import MockPushAdapter

        device_store = Mock()
        adapter = MockPushAdapter(invalid_tokens=["bad_token"])

        device_store.get_tokens.return_value = ["good_token", "bad_token", "another_good"]

        service = PushNotificationService(
            device_store=device_store,
            notification_adapter=adapter,
        )

        results = service.broadcast(title="Test", body="Body")

        success_count = sum(1 for r in results if r.success)
        assert success_count == 2
        assert len(results) == 3


# ============================================================================
# TESTS - GetPreferencesUseCase - Edge Cases
# ============================================================================

class TestGetPreferencesUseCaseEdgeCases:
    """Tests edge cases pour GetPreferencesUseCase."""

    def test_get_preferences_creates_default_when_none(self):
        """Test création de préférences par défaut si inexistantes."""
        from app.application.mobile_companion import GetPreferencesUseCase

        preferences_port = Mock()
        preferences_port.get.return_value = None
        preferences_port.save.return_value = MobileUserPreferences(user_id="user_123")

        uc = GetPreferencesUseCase(preferences_port=preferences_port)

        result = uc.execute(user_id="user_123")

        assert result.user_id == "user_123"
        preferences_port.save.assert_called_once()

    def test_get_preferences_returns_existing(self):
        """Test retour de préférences existantes."""
        from app.application.mobile_companion import GetPreferencesUseCase

        existing = MobileUserPreferences(user_id="user_123", dark_mode=True)

        preferences_port = Mock()
        preferences_port.get.return_value = existing

        uc = GetPreferencesUseCase(preferences_port=preferences_port)

        result = uc.execute(user_id="user_123")

        assert result.dark_mode is True
        preferences_port.save.assert_not_called()


# ============================================================================
# TESTS - UpdatePreferencesUseCase - Edge Cases
# ============================================================================

class TestUpdatePreferencesUseCaseEdgeCases:
    """Tests edge cases pour UpdatePreferencesUseCase."""

    def test_update_preferences_not_found(self):
        """Test mise à jour de préférences inexistantes."""
        from app.application.mobile_companion import UpdatePreferencesUseCase

        preferences_port = Mock()
        analytics_port = Mock()

        preferences_port.update.return_value = None

        uc = UpdatePreferencesUseCase(
            preferences_port=preferences_port,
            analytics_port=analytics_port,
        )

        result = uc.execute(user_id="unknown", updates={"dark_mode": True})

        assert result is None
        analytics_port.track_event.assert_not_called()

    def test_update_preferences_tracks_analytics(self):
        """Test que la mise à jour enregistre un événement analytics."""
        from app.application.mobile_companion import UpdatePreferencesUseCase

        preferences_port = Mock()
        analytics_port = Mock()

        updated = MobileUserPreferences(user_id="user_123", dark_mode=True)
        preferences_port.update.return_value = updated
        analytics_port.track_event.return_value = True

        uc = UpdatePreferencesUseCase(
            preferences_port=preferences_port,
            analytics_port=analytics_port,
        )

        result = uc.execute(
            user_id="user_123",
            updates={"dark_mode": True, "language": "en"},
        )

        assert result is not None
        analytics_port.track_event.assert_called_once()

        # Vérifier que les champs modifiés sont dans l'événement
        event = analytics_port.track_event.call_args[0][0]
        assert "changed_fields" in event.properties
        assert "dark_mode" in event.properties["changed_fields"]
        assert "language" in event.properties["changed_fields"]
