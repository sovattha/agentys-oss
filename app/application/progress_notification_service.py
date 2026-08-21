# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Service de notifications de progression.

Envoie des notifications encourageantes aux utilisateurs lorsqu'ils atteignent
des milestones d'utilisation (10, 50, 100 emails traités).

Milestone 4.3:
- Après 10 emails : "L'IA s'adapte à votre style"
- Après 50 emails : "Patterns détectés : signature, formule..."
- Après 100 emails : "Taux de validation directe : 85%"
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Set

from app.infrastructure.notifications import (
    NotificationManager,
    NotificationType,
    get_notification_manager,
)

logger = logging.getLogger(__name__)


# Messages par défaut pour chaque milestone
DEFAULT_MILESTONE_MESSAGES = {
    10: {
        "title": "Agentys apprend !",
        "message": "L'IA s'adapte à votre style d'écriture",
    },
    50: {
        "title": "Progrès remarquables !",
        "message": "{patterns_count} patterns détectés : signature, formules...",
    },
    100: {
        "title": "Bravo, expert Agentys !",
        "message": "Taux de validation directe : {validation_rate:.0f}%",
    },
}


@dataclass
class ProgressNotificationService:
    """
    Service de notifications de progression.

    Envoie des notifications encourageantes lorsque l'utilisateur atteint
    des milestones d'utilisation.
    """

    notifier: Optional[NotificationManager] = None
    learning_service: Optional[Any] = None
    custom_messages: Optional[Dict[int, str]] = None
    _notified_milestones: Set[int] = field(default_factory=set)

    def __post_init__(self):
        if self.notifier is None:
            self.notifier = get_notification_manager()
        if self.custom_messages is None:
            self.custom_messages = {}

    def check_and_notify(self, emails_processed: int) -> bool:
        """
        Vérifie si un milestone a été atteint et envoie une notification.

        Args:
            emails_processed: Nombre total d'emails traités.

        Returns:
            True si une notification a été envoyée, False sinon.
        """
        milestone = self._get_milestone(emails_processed)

        if milestone is None:
            return False

        if milestone in self._notified_milestones:
            return False

        try:
            result = self._send_milestone_notification(milestone)
            if result:
                self._notified_milestones.add(milestone)
            return result
        except Exception as e:
            logger.debug(f"Failed to send progress notification: {e}")
            return False

    def _get_milestone(self, emails_processed: int) -> Optional[int]:
        """Retourne le milestone atteint, ou None."""
        all_milestones = set(DEFAULT_MILESTONE_MESSAGES.keys())
        all_milestones.update(self.custom_messages.keys())

        for milestone in sorted(all_milestones, reverse=True):
            if emails_processed == milestone:
                return milestone

        return None

    def _send_milestone_notification(self, milestone: int) -> bool:
        """Envoie la notification pour un milestone."""
        title, message = self._get_notification_content(milestone)

        return self.notifier.send(
            title=title,
            message=message,
            notification_type=NotificationType.SUCCESS,
            sound=True,
        )

    def _get_notification_content(self, milestone: int) -> tuple[str, str]:
        """Retourne le titre et message pour un milestone."""
        # Custom message override
        if milestone in self.custom_messages:
            return "Agentys - Progrès", self.custom_messages[milestone]

        # Default messages avec enrichissement dynamique
        if milestone not in DEFAULT_MILESTONE_MESSAGES:
            return "Agentys - Progrès", f"{milestone} emails traités !"

        template = DEFAULT_MILESTONE_MESSAGES[milestone]
        title = template["title"]
        message_template = template["message"]

        # Enrichissement avec les stats du learning service
        stats = self._get_learning_stats()
        message = self._format_message(message_template, stats)

        return title, message

    def _get_learning_stats(self) -> Dict[str, Any]:
        """Récupère les stats du learning service."""
        if self.learning_service is None:
            return {
                "patterns_count": 0,
                "validation_rate": 0.0,
            }

        try:
            raw_stats = self.learning_service.get_stats()
            return {
                "patterns_count": raw_stats.get("patterns_count", 0),
                "validation_rate": raw_stats.get("validation_rate_v1", 0.0),
            }
        except Exception:
            return {
                "patterns_count": 0,
                "validation_rate": 0.0,
            }

    def _format_message(self, template: str, stats: Dict[str, Any]) -> str:
        """Formate le message avec les stats."""
        try:
            return template.format(**stats)
        except KeyError:
            return template

    def reset(self) -> None:
        """Réinitialise les milestones notifiés (pour les tests)."""
        self._notified_milestones.clear()
