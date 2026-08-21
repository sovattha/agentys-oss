# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter Expo Push pour les notifications push.

Ce module implémente l'envoi de notifications push via Expo Push Notifications,
le service de notifications pour les apps React Native/Expo.

L'avantage d'Expo est qu'il ne nécessite pas de configuration Firebase/APNs
et fonctionne directement avec les tokens Expo.

Usage:
    from app.adapters.push import ExpoAdapter

    adapter = ExpoAdapter()
    result = adapter.send(
        device_token="ExponentPushToken[xxx]",
        title="Nouveau brouillon",
        body="Réponse créée pour john@example.com",
    )
"""

import os
import logging
from typing import List, Optional
from dataclasses import dataclass

from app.domain.ports.notification_port import (
    NotificationPort,
    NotificationPriority,
    PushNotificationResult,
)

logger = logging.getLogger(__name__)

# URL de l'API Expo Push
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


@dataclass
class ExpoConfig:
    """Configuration pour Expo Push."""
    access_token: Optional[str] = None  # Optionnel, pour les quotas élevés

    @classmethod
    def from_env(cls) -> "ExpoConfig":
        """Charge la configuration depuis les variables d'environnement."""
        return cls(
            access_token=os.getenv("EXPO_ACCESS_TOKEN"),
        )


class ExpoAdapter(NotificationPort):
    """
    Adapter pour Expo Push Notifications.

    Utilise l'API REST d'Expo pour envoyer des notifications
    aux apps React Native utilisant Expo.
    """

    def __init__(self, config: Optional[ExpoConfig] = None):
        """
        Initialise l'adapter Expo.

        Args:
            config: Configuration optionnelle. Si None, charge depuis env.
        """
        self.config = config or ExpoConfig.from_env()

    @property
    def name(self) -> str:
        """Nom du provider."""
        return "expo"

    def is_available(self) -> bool:
        """
        Vérifie si Expo Push est disponible.

        Expo fonctionne sans configuration (quota limité).
        Avec access_token, les quotas sont plus élevés.
        """
        return True  # Toujours disponible, même sans token

    def send(
        self,
        device_token: str,
        title: str,
        body: str,
        data: Optional[dict] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> PushNotificationResult:
        """
        Envoie une notification push via Expo.

        Args:
            device_token: Token Expo (ExponentPushToken[xxx]).
            title: Titre de la notification.
            body: Corps du message.
            data: Données additionnelles.
            priority: Priorité de la notification.

        Returns:
            Résultat de l'envoi.
        """
        # Valider le token
        if not self.validate_token(device_token):
            return PushNotificationResult(
                success=False,
                error_code="INVALID_TOKEN",
                error_message="Invalid Expo push token format",
            )

        # Mapper la priorité
        expo_priority = "high" if priority == NotificationPriority.HIGH else "default"

        # Construire le message Expo
        message = {
            "to": device_token,
            "title": title,
            "body": body,
            "priority": expo_priority,
            "sound": "default",
        }

        # Ajouter les données personnalisées
        if data:
            message["data"] = data

        try:
            import requests

            headers = {
                "Accept": "application/json",
                "Accept-encoding": "gzip, deflate",
                "Content-Type": "application/json",
            }

            # Ajouter le token d'accès si configuré
            if self.config.access_token:
                headers["Authorization"] = f"Bearer {self.config.access_token}"

            response = requests.post(
                EXPO_PUSH_URL,
                json=message,
                headers=headers,
                timeout=10,
            )

            if response.ok:
                result_data = response.json()
                ticket = result_data.get("data", {})

                if ticket.get("status") == "ok":
                    logger.debug(f"Expo notification sent: {ticket.get('id')}")
                    return PushNotificationResult(
                        success=True,
                        message_id=ticket.get("id"),
                    )
                else:
                    # Erreur dans le ticket
                    details = ticket.get("details", {})
                    return PushNotificationResult(
                        success=False,
                        error_code=details.get("error", "UNKNOWN"),
                        error_message=ticket.get("message", "Unknown error"),
                    )
            else:
                return PushNotificationResult(
                    success=False,
                    error_code=f"HTTP_{response.status_code}",
                    error_message=response.text,
                )

        except Exception as e:
            logger.error(f"Expo send error: {e}")
            return PushNotificationResult(
                success=False,
                error_code="SEND_ERROR",
                error_message=str(e),
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
        Envoie une notification à plusieurs devices en batch.

        Expo supporte l'envoi batch de 100 notifications max par requête.

        Args:
            device_tokens: Liste des tokens Expo.
            title: Titre de la notification.
            body: Corps du message.
            data: Données additionnelles.
            priority: Priorité de la notification.

        Returns:
            Liste des résultats (un par token).
        """
        if not device_tokens:
            return []

        # Valider tous les tokens
        valid_tokens = [t for t in device_tokens if self.validate_token(t)]
        invalid_tokens = [t for t in device_tokens if not self.validate_token(t)]

        results = []

        # Ajouter les erreurs pour les tokens invalides
        for token in invalid_tokens:
            results.append(PushNotificationResult(
                success=False,
                error_code="INVALID_TOKEN",
                error_message=f"Invalid token: {token[:20]}...",
            ))

        if not valid_tokens:
            return results

        # Mapper la priorité
        expo_priority = "high" if priority == NotificationPriority.HIGH else "default"

        # Construire les messages batch (max 100 par requête)
        batch_size = 100
        for i in range(0, len(valid_tokens), batch_size):
            batch_tokens = valid_tokens[i:i + batch_size]

            messages = []
            for token in batch_tokens:
                message = {
                    "to": token,
                    "title": title,
                    "body": body,
                    "priority": expo_priority,
                    "sound": "default",
                }
                if data:
                    message["data"] = data
                messages.append(message)

            try:
                import requests

                headers = {
                    "Accept": "application/json",
                    "Accept-encoding": "gzip, deflate",
                    "Content-Type": "application/json",
                }

                if self.config.access_token:
                    headers["Authorization"] = f"Bearer {self.config.access_token}"

                response = requests.post(
                    EXPO_PUSH_URL,
                    json=messages,
                    headers=headers,
                    timeout=30,
                )

                if response.ok:
                    result_data = response.json()
                    tickets = result_data.get("data", [])

                    for ticket in tickets:
                        if ticket.get("status") == "ok":
                            results.append(PushNotificationResult(
                                success=True,
                                message_id=ticket.get("id"),
                            ))
                        else:
                            details = ticket.get("details", {})
                            results.append(PushNotificationResult(
                                success=False,
                                error_code=details.get("error", "UNKNOWN"),
                                error_message=ticket.get("message", "Unknown error"),
                            ))
                else:
                    # Erreur HTTP pour tout le batch
                    for _ in batch_tokens:
                        results.append(PushNotificationResult(
                            success=False,
                            error_code=f"HTTP_{response.status_code}",
                            error_message=response.text[:100],
                        ))

            except Exception as e:
                logger.error(f"Expo batch send error: {e}")
                for _ in batch_tokens:
                    results.append(PushNotificationResult(
                        success=False,
                        error_code="SEND_ERROR",
                        error_message=str(e),
                    ))

        return results

    def validate_token(self, device_token: str) -> bool:
        """
        Valide un token Expo Push.

        Les tokens Expo ont le format: ExponentPushToken[xxx]

        Args:
            device_token: Token à valider.

        Returns:
            True si le format est valide.
        """
        if not device_token:
            return False

        # Format: ExponentPushToken[xxx] où xxx est une chaîne
        if device_token.startswith("ExponentPushToken[") and device_token.endswith("]"):
            # Extraire le contenu entre les crochets
            content = device_token[18:-1]
            return len(content) > 0

        # Format alternatif possible (sans les crochets pour les anciens tokens)
        return len(device_token) >= 20

    def get_push_receipts(self, receipt_ids: List[str]) -> List[dict]:
        """
        Récupère les receipts pour vérifier le statut de livraison.

        Args:
            receipt_ids: Liste des IDs de tickets.

        Returns:
            Liste des receipts avec leur statut.
        """
        if not receipt_ids:
            return []

        try:
            import requests

            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            if self.config.access_token:
                headers["Authorization"] = f"Bearer {self.config.access_token}"

            response = requests.post(
                "https://exp.host/--/api/v2/push/getReceipts",
                json={"ids": receipt_ids},
                headers=headers,
                timeout=10,
            )

            if response.ok:
                return response.json().get("data", {})

        except Exception as e:
            logger.error(f"Expo get receipts error: {e}")

        return []
