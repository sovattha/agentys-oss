# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port Notification - Interface pour les providers de notifications push.

Ce port définit le contrat que tout adapter de notification push doit implémenter,
qu'il s'agisse de Firebase Cloud Messaging (FCM), Expo Push, ou autre.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum


class NotificationPlatform(Enum):
    """Plateformes supportées pour les notifications push."""
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class NotificationPriority(Enum):
    """Priorité de la notification."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass
class PushNotificationResult:
    """Résultat de l'envoi d'une notification push."""
    success: bool
    message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class NotificationPort(ABC):
    """
    Interface abstraite pour un provider de notification push.

    Tout adapter (FCM, Expo, etc.) doit implémenter cette interface.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du provider (ex: 'fcm', 'expo')."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Vérifie si le provider est disponible et configuré.

        Returns:
            True si le provider est prêt à envoyer des notifications.
        """
        pass

    @abstractmethod
    def send(
        self,
        device_token: str,
        title: str,
        body: str,
        data: Optional[dict] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> PushNotificationResult:
        """
        Envoie une notification push à un device.

        Args:
            device_token: Token du device cible.
            title: Titre de la notification.
            body: Corps du message.
            data: Données additionnelles (payload).
            priority: Priorité de la notification.

        Returns:
            Résultat de l'envoi.
        """
        pass

    @abstractmethod
    def send_batch(
        self,
        device_tokens: List[str],
        title: str,
        body: str,
        data: Optional[dict] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> List[PushNotificationResult]:
        """
        Envoie une notification push à plusieurs devices.

        Args:
            device_tokens: Liste des tokens des devices cibles.
            title: Titre de la notification.
            body: Corps du message.
            data: Données additionnelles (payload).
            priority: Priorité de la notification.

        Returns:
            Liste des résultats d'envoi (un par device).
        """
        pass

    @abstractmethod
    def validate_token(self, device_token: str) -> bool:
        """
        Valide qu'un token de device est valide.

        Args:
            device_token: Token à valider.

        Returns:
            True si le token est valide.
        """
        pass
