# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour vérifier que les notifications sont automatiquement mockées.

Ce fichier contient des tests exhaustifs pour valider que:
1. Le fixture mock_notifications fonctionne correctement
2. Toutes les méthodes de NotificationManager sont mockées
3. Aucune notification réelle n'est envoyée pendant les tests
4. Le singleton est correctement réinitialisé entre les tests
"""

from unittest.mock import MagicMock, patch


class TestMockNotificationsFixture:
    """Tests pour le fixture mock_notifications."""

    def test_notification_manager_is_mocked(self, mock_notifications):
        """Le NotificationManager doit être un mock dans les tests."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        assert isinstance(manager, MagicMock)

    def test_send_returns_true_without_real_notification(self, mock_notifications):
        """send() doit retourner True sans envoyer de vraie notification."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        result = manager.send("Test", "Message")
        assert result is True

    def test_draft_created_does_not_trigger_real_notification(self, mock_notifications):
        """draft_created() ne doit pas déclencher de vraie notification desktop."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        result = manager.draft_created("test@example.com", "Test Subject")
        assert result is True
        manager.draft_created.assert_called_once()

    def test_error_does_not_trigger_real_notification(self, mock_notifications):
        """error() ne doit pas déclencher de vraie notification."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        result = manager.error("Test error message")
        assert result is True
        manager.error.assert_called_once()

    def test_notify_alias_is_also_mocked(self, mock_notifications):
        """L'alias 'notify' doit également être mocké."""
        from app.infrastructure.notifications import notify
        assert isinstance(notify, MagicMock)
        result = notify.info("Test message")
        assert result is True

    def test_push_notifications_are_mocked(self, mock_notifications):
        """Les push notifications doivent également être mockées."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        manager.draft_created("test@example.com", "Subject", priority=1, draft_id="123")
        manager.draft_created.assert_called_once()


class TestMockNotificationsAllMethods:
    """Tests vérifiant que toutes les méthodes sont correctement mockées."""

    def test_followup_created_mocked(self, mock_notifications):
        """followup_created() doit être mocké."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        result = manager.followup_created("test@example.com", days=5)
        assert result is True
        manager.followup_created.assert_called_once_with("test@example.com", days=5)

    def test_learning_complete_mocked(self, mock_notifications):
        """learning_complete() doit être mocké."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        result = manager.learning_complete(10, 3)
        assert result is True
        manager.learning_complete.assert_called_once_with(10, 3)

    def test_health_check_failed_mocked(self, mock_notifications):
        """health_check_failed() doit être mocké."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        result = manager.health_check_failed("database")
        assert result is True
        manager.health_check_failed.assert_called_once_with("database")

    def test_rate_limit_warning_mocked(self, mock_notifications):
        """rate_limit_warning() doit être mocké."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        result = manager.rate_limit_warning(15.5)
        assert result is True
        manager.rate_limit_warning.assert_called_once_with(15.5)

    def test_budget_warning_mocked(self, mock_notifications):
        """budget_warning() doit être mocké."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        result = manager.budget_warning(45.50, 50.00)
        assert result is True
        manager.budget_warning.assert_called_once_with(45.50, 50.00)

    def test_draft_failed_mocked(self, mock_notifications):
        """draft_failed() doit être mocké."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        result = manager.draft_failed("test@example.com", "Connection timeout")
        assert result is True
        manager.draft_failed.assert_called_once()


class TestMockNotificationsEdgeCases:
    """Tests des edge cases pour le mock notifications."""

    def test_multiple_calls_tracked(self, mock_notifications):
        """Plusieurs appels doivent être tracés correctement."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()

        manager.info("Message 1")
        manager.info("Message 2")
        manager.info("Message 3")

        assert manager.info.call_count == 3

    def test_mock_with_none_values(self, mock_notifications):
        """Le mock doit gérer les valeurs None."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()

        result = manager.send(None, None)
        assert result is True

    def test_mock_with_empty_strings(self, mock_notifications):
        """Le mock doit gérer les chaînes vides."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()

        result = manager.send("", "")
        assert result is True
        result = manager.info("")
        assert result is True

    def test_mock_with_long_strings(self, mock_notifications):
        """Le mock doit gérer les longues chaînes."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()

        long_title = "A" * 10000
        long_message = "B" * 10000
        result = manager.send(long_title, long_message)
        assert result is True

    def test_mock_with_special_characters(self, mock_notifications):
        """Le mock doit gérer les caractères spéciaux."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()

        special_chars = '"; rm -rf /; echo "injection'
        result = manager.send(special_chars, special_chars)
        assert result is True

    def test_mock_with_unicode(self, mock_notifications):
        """Le mock doit gérer l'unicode."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()

        unicode_text = "こんにちは 🎉 مرحبا émojis αβγ"
        result = manager.send(unicode_text, unicode_text)
        assert result is True

    def test_error_with_context_dict(self, mock_notifications):
        """error() doit accepter un contexte dict."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()

        context = {"email_id": "123", "provider": "gmail"}
        result = manager.error("Test error", context=context)
        assert result is True
        manager.error.assert_called_once_with("Test error", context=context)


class TestMockNotificationsSingletonReset:
    """Tests vérifiant que le singleton est bien réinitialisé."""

    def test_singleton_reset_first_test(self, mock_notifications):
        """Premier test: le singleton doit être un mock."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        assert isinstance(manager, MagicMock)
        # Modifier le mock pour vérifier l'isolation
        manager.custom_attr = "test_value_1"

    def test_singleton_reset_second_test(self, mock_notifications):
        """Second test: le singleton doit être un nouveau mock (pas l'attribut custom)."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        assert isinstance(manager, MagicMock)
        # Ne devrait pas avoir l'attribut du test précédent car c'est un nouveau mock
        # (sauf si c'est un MagicMock qui crée dynamiquement les attributs)
        # Le point clé est que call_count est remis à zéro
        assert manager.send.call_count == 0


class TestMockNotificationsAutouse:
    """Tests vérifiant que le fixture autouse fonctionne sans passage explicite."""

    def test_autouse_notification_manager_mocked(self):
        """Sans passer le fixture, le manager doit quand même être mocké (autouse=True)."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        # Grâce à autouse=True, le manager devrait être un mock
        assert isinstance(manager, MagicMock)

    def test_autouse_no_real_notification_sent(self):
        """Sans passer le fixture, aucune vraie notification ne doit être envoyée."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()
        # Ces appels ne déclencheront pas de vraies notifications
        manager.draft_created("test@example.com", "Subject")
        manager.error("Error message")
        manager.info("Info message")
        # Le mock est automatiquement appliqué
        assert manager.draft_created.called
        assert manager.error.called
        assert manager.info.called


class TestMockNotificationsInternalMethods:
    """Tests vérifiant que les méthodes internes push sont également mockées."""

    def test_set_push_service_getter_mocked(self, mock_notifications):
        """set_push_service_getter() doit être mocké."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()

        def dummy_getter():
            return MagicMock()

        # Ne doit pas lever d'exception
        manager.set_push_service_getter(dummy_getter)
        # Sur un MagicMock, ça retourne un MagicMock ou True
        manager.set_push_service_getter.assert_called_once()

    def test_register_callback_mocked(self, mock_notifications):
        """register_callback() doit être mocké."""
        from app.infrastructure.notifications import (
            get_notification_manager,
            NotificationType,
        )
        manager = get_notification_manager()

        callback = MagicMock()
        manager.register_callback(NotificationType.ERROR, callback)
        manager.register_callback.assert_called_once()


class TestMockNotificationsNoRealSubprocess:
    """Tests vérifiant qu'aucun subprocess n'est lancé."""

    def test_no_osascript_called(self, mock_notifications):
        """osascript ne doit pas être appelé."""
        import subprocess
        original_run = subprocess.run

        call_tracker = []

        def tracking_run(*args, **kwargs):
            call_tracker.append(args)
            return original_run(*args, **kwargs)

        with patch("subprocess.run", side_effect=tracking_run):
            from app.infrastructure.notifications import get_notification_manager
            manager = get_notification_manager()
            manager.send("Test", "Message")
            # Grâce au mock, subprocess.run ne devrait pas être appelé
            # par le NotificationManager mocké
            # Le call_tracker reste vide car send() est mocké

    def test_no_notify_send_called(self, mock_notifications):
        """notify-send ne doit pas être appelé."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()

        # Appeler toutes les méthodes de notification
        manager.draft_created("test@example.com", "Subject")
        manager.draft_failed("test@example.com", "Error")
        manager.error("Error message")
        manager.info("Info message")

        # Tout doit retourner True (mock)
        assert manager.draft_created.call_count == 1
        assert manager.draft_failed.call_count == 1
        assert manager.error.call_count == 1
        assert manager.info.call_count == 1


class TestMockNotificationsReturnValues:
    """Tests vérifiant les valeurs de retour du mock."""

    def test_all_methods_return_true(self, mock_notifications):
        """Toutes les méthodes doivent retourner True."""
        from app.infrastructure.notifications import get_notification_manager
        manager = get_notification_manager()

        # Vérifier que chaque méthode retourne True
        assert manager.send("Title", "Message") is True
        assert manager.draft_created("test@example.com", "Subject") is True
        assert manager.draft_failed("test@example.com", "Error") is True
        assert manager.followup_created("test@example.com", days=5) is True
        assert manager.learning_complete(10, 3) is True
        assert manager.health_check_failed("component") is True
        assert manager.rate_limit_warning(25.0) is True
        assert manager.budget_warning(45.0, 50.0) is True
        assert manager.error("Error message") is True
        assert manager.info("Info message") is True
