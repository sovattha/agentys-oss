# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Mock Adapter pour les notifications push (tests).

Ce module fournit un adapter mock qui simule l'envoi de notifications
sans faire de vraies requêtes réseau. Utile pour les tests unitaires.

Usage:
    from app.adapters.push import MockPushAdapter

    adapter = MockPushAdapter()
    result = adapter.send(
        device_token="test_token",
        title="Test",
        body="Test notification",
    )

    # Vérifier les notifications envoyées
    assert len(adapter.sent_notifications) == 1
"""

import logging
from typing import List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from app.domain.ports.notification_port import (
    NotificationPort,
    NotificationPriority,
    PushNotificationResult,
)

logger = logging.getLogger(__name__)


@dataclass
class MockNotificationRecord:
    """Enregistrement d'une notification mock envoyée."""
    device_token: str
    title: str
    body: str
    data: Optional[dict]
    priority: NotificationPriority
    sent_at: datetime = field(default_factory=datetime.now)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


class MockPushAdapter(NotificationPort):
    """
    Adapter mock pour les notifications push.

    Ne fait pas de vraies requêtes, stocke les notifications en mémoire.
    Permet de simuler des succès et des échecs pour les tests.
    """

    def __init__(
        self,
        should_fail: bool = False,
        failure_error: str = "Mock failure",
        invalid_tokens: Optional[List[str]] = None,
    ):
        """
        Initialise le mock adapter.

        Args:
            should_fail: Si True, toutes les notifications échouent.
            failure_error: Message d'erreur en cas d'échec.
            invalid_tokens: Liste de tokens à considérer comme invalides.
        """
        self.should_fail = should_fail
        self.failure_error = failure_error
        self.invalid_tokens = invalid_tokens or []
        self.sent_notifications: List[MockNotificationRecord] = []

    @property
    def name(self) -> str:
        """Nom du provider."""
        return "mock"

    def is_available(self) -> bool:
        """Le mock est toujours disponible."""
        return True

    def send(
        self,
        device_token: str,
        title: str,
        body: str,
        data: Optional[dict] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> PushNotificationResult:
        """
        Simule l'envoi d'une notification push.

        Args:
            device_token: Token du device (peut être n'importe quoi).
            title: Titre de la notification.
            body: Corps du message.
            data: Données additionnelles.
            priority: Priorité de la notification.

        Returns:
            Résultat simulé.
        """
        # Vérifier si le token est dans la liste des tokens invalides
        if device_token in self.invalid_tokens:
            return PushNotificationResult(
                success=False,
                error_code="INVALID_TOKEN",
                error_message=f"Token {device_token} is invalid",
            )

        # Simuler un échec si configuré
        if self.should_fail:
            return PushNotificationResult(
                success=False,
                error_code="MOCK_FAILURE",
                error_message=self.failure_error,
            )

        # Enregistrer la notification
        record = MockNotificationRecord(
            device_token=device_token,
            title=title,
            body=body,
            data=data,
            priority=priority,
        )
        self.sent_notifications.append(record)

        logger.debug(f"Mock notification sent: {record.message_id}")

        return PushNotificationResult(
            success=True,
            message_id=record.message_id,
        )

    def send_batch(
        self,
        device_tokens: List[str],
        title: str,
        body: str,
        data: Optional[dict] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> List[PushNotificationResult]:
        """
        Simule l'envoi de notifications à plusieurs devices.

        Args:
            device_tokens: Liste des tokens.
            title: Titre de la notification.
            body: Corps du message.
            data: Données additionnelles.
            priority: Priorité de la notification.

        Returns:
            Liste des résultats simulés.
        """
        return [
            self.send(token, title, body, data, priority)
            for token in device_tokens
        ]

    def validate_token(self, device_token: str) -> bool:
        """
        Valide un token (accepte tout sauf ceux dans invalid_tokens).

        Args:
            device_token: Token à valider.

        Returns:
            True si le token n'est pas dans la liste des tokens invalides.
        """
        if not device_token:
            return False
        return device_token not in self.invalid_tokens

    # Méthodes utilitaires pour les tests
    def clear(self) -> None:
        """Efface toutes les notifications envoyées."""
        self.sent_notifications.clear()

    def get_notifications_for_token(self, device_token: str) -> List[MockNotificationRecord]:
        """Récupère les notifications envoyées à un token spécifique."""
        return [n for n in self.sent_notifications if n.device_token == device_token]

    def get_notifications_count(self) -> int:
        """Retourne le nombre de notifications envoyées."""
        return len(self.sent_notifications)

    def set_should_fail(self, should_fail: bool, error: str = "Mock failure") -> None:
        """Configure le mock pour échouer ou réussir."""
        self.should_fail = should_fail
        self.failure_error = error

    def add_invalid_token(self, token: str) -> None:
        """Ajoute un token à la liste des tokens invalides."""
        if token not in self.invalid_tokens:
            self.invalid_tokens.append(token)

    def remove_invalid_token(self, token: str) -> None:
        """Retire un token de la liste des tokens invalides."""
        if token in self.invalid_tokens:
            self.invalid_tokens.remove(token)
