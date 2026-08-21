# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les notifications de progression.

Milestone 4.3: Notifications de progression
- Après 10 emails : "L'IA s'adapte à votre style"
- Après 50 emails : "Patterns détectés : signature, formule..."
- Après 100 emails : "Taux de validation directe : 85%"
"""

from unittest.mock import Mock, patch


class TestProgressNotificationService:
    """Tests pour le service de notifications de progression."""

    def test_no_notification_before_milestone(self):
        """Aucune notification avant d'atteindre un milestone."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        service = ProgressNotificationService(notifier=notifier)

        service.check_and_notify(emails_processed=5)

        notifier.info.assert_not_called()
        notifier.send.assert_not_called()

    def test_notification_at_10_emails(self):
        """Notification après 10 emails: L'IA s'adapte."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        service = ProgressNotificationService(notifier=notifier)

        service.check_and_notify(emails_processed=10)

        notifier.send.assert_called_once()
        call_kwargs = notifier.send.call_args.kwargs
        assert "adapte" in call_kwargs["message"].lower() or "adapte" in str(call_kwargs)

    def test_notification_at_50_emails(self):
        """Notification après 50 emails: Patterns détectés."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        learning_service = Mock()
        learning_service.get_stats.return_value = {
            "patterns_count": 5,
            "signature_detected": True,
            "formulas_count": 3,
        }
        service = ProgressNotificationService(
            notifier=notifier,
            learning_service=learning_service,
        )

        service.check_and_notify(emails_processed=50)

        notifier.send.assert_called_once()
        call_kwargs = notifier.send.call_args.kwargs
        message = call_kwargs["message"]
        assert "pattern" in message.lower()

    def test_notification_at_100_emails(self):
        """Notification après 100 emails: Taux de validation."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        learning_service = Mock()
        learning_service.get_stats.return_value = {
            "validation_rate_v1": 85.0,
            "total_validated": 100,
            "validated_v1": 85,
        }
        service = ProgressNotificationService(
            notifier=notifier,
            learning_service=learning_service,
        )

        service.check_and_notify(emails_processed=100)

        notifier.send.assert_called_once()
        call_kwargs = notifier.send.call_args.kwargs
        message = call_kwargs["message"]
        assert "85" in message or "validation" in message.lower()

    def test_no_duplicate_notification(self):
        """Pas de notification dupliquée pour le même milestone."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        service = ProgressNotificationService(notifier=notifier)

        service.check_and_notify(emails_processed=10)
        service.check_and_notify(emails_processed=10)  # Même milestone

        assert notifier.send.call_count == 1

    def test_all_milestones_triggered_in_sequence(self):
        """Tous les milestones déclenchent leurs notifications en séquence."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        learning_service = Mock()
        learning_service.get_stats.return_value = {
            "patterns_count": 5,
            "validation_rate_v1": 85.0,
        }
        service = ProgressNotificationService(
            notifier=notifier,
            learning_service=learning_service,
        )

        service.check_and_notify(emails_processed=10)
        service.check_and_notify(emails_processed=50)
        service.check_and_notify(emails_processed=100)

        assert notifier.send.call_count == 3

    def test_milestone_200_cycles_back(self):
        """Les milestones 200, 500 ne déclenchent pas de notification (>100 silencieux)."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        service = ProgressNotificationService(notifier=notifier)

        # Simule que les milestones 10, 50, 100 ont déjà été passés
        service._notified_milestones = {10, 50, 100}

        service.check_and_notify(emails_processed=200)

        notifier.send.assert_not_called()

    def test_custom_milestones_can_be_configured(self):
        """Les milestones peuvent être configurés."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        service = ProgressNotificationService(
            notifier=notifier,
            custom_messages={25: "Quart du chemin !"},
        )

        service.check_and_notify(emails_processed=25)

        notifier.send.assert_called_once()

    def test_notification_includes_encouragement(self):
        """Les notifications incluent un message d'encouragement."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        service = ProgressNotificationService(notifier=notifier)

        service.check_and_notify(emails_processed=10)

        call_kwargs = notifier.send.call_args.kwargs
        title = call_kwargs["title"]
        # Le titre doit être positif/encourageant
        assert any(word in title.lower() for word in ["bravo", "super", "progrès", "agentys", "apprend"])

    def test_notification_type_is_success(self):
        """Les notifications de progression sont de type SUCCESS."""
        from app.application.progress_notification_service import ProgressNotificationService
        from app.infrastructure.notifications import NotificationType

        notifier = Mock()
        service = ProgressNotificationService(notifier=notifier)

        service.check_and_notify(emails_processed=10)

        call_args = notifier.send.call_args
        notification_type = call_args[1].get("notification_type") if call_args[1] else call_args[0][2]
        assert notification_type == NotificationType.SUCCESS


class TestProgressNotificationIntegration:
    """Tests d'intégration avec le NotificationManager."""

    @patch("app.application.progress_notification_service.get_notification_manager")
    def test_uses_notification_manager(self, mock_get_manager):
        """Le service utilise le NotificationManager."""
        from app.application.progress_notification_service import ProgressNotificationService

        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        service = ProgressNotificationService()
        service.check_and_notify(emails_processed=10)

        mock_manager.send.assert_called_once()

    def test_graceful_failure_if_notifier_fails(self):
        """Le service gère gracieusement les erreurs du notifier."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        notifier.send.side_effect = Exception("Notification failed")
        service = ProgressNotificationService(notifier=notifier)

        # Ne doit pas lever d'exception
        result = service.check_and_notify(emails_processed=10)
        assert result is False


class TestProgressNotificationMessages:
    """Tests pour les messages de notification."""

    def test_message_10_emails_mentions_adaptation(self):
        """Le message pour 10 emails mentionne l'adaptation."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        service = ProgressNotificationService(notifier=notifier)

        service.check_and_notify(emails_processed=10)

        call_kwargs = notifier.send.call_args.kwargs
        message = call_kwargs["message"]
        assert "adapte" in message.lower() or "apprend" in message.lower()

    def test_message_50_emails_includes_patterns_count(self):
        """Le message pour 50 emails inclut le nombre de patterns."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        learning_service = Mock()
        learning_service.get_stats.return_value = {"patterns_count": 7}
        service = ProgressNotificationService(
            notifier=notifier,
            learning_service=learning_service,
        )

        service.check_and_notify(emails_processed=50)

        call_kwargs = notifier.send.call_args.kwargs
        message = call_kwargs["message"]
        assert "7" in message or "pattern" in message.lower()

    def test_message_100_emails_includes_validation_rate(self):
        """Le message pour 100 emails inclut le taux de validation."""
        from app.application.progress_notification_service import ProgressNotificationService

        notifier = Mock()
        learning_service = Mock()
        learning_service.get_stats.return_value = {"validation_rate_v1": 92.5}
        service = ProgressNotificationService(
            notifier=notifier,
            learning_service=learning_service,
        )

        service.check_and_notify(emails_processed=100)

        call_kwargs = notifier.send.call_args.kwargs
        message = call_kwargs["message"]
        # Doit inclure le pourcentage arrondi
        assert "92" in message or "93" in message
