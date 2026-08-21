# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter Firebase Cloud Messaging (FCM) pour les notifications push.

Ce module implémente l'envoi de notifications push via Firebase Cloud Messaging,
le service de Google pour Android, iOS et Web.

Configuration requise:
- FIREBASE_CREDENTIALS_PATH: Chemin vers le fichier JSON des credentials Firebase
- ou FIREBASE_PROJECT_ID + FIREBASE_PRIVATE_KEY + FIREBASE_CLIENT_EMAIL

Usage:
    from app.adapters.push import FCMAdapter

    adapter = FCMAdapter()
    if adapter.is_available():
        result = adapter.send(
            device_token="fcm_token_xxx",
            title="Nouveau brouillon",
            body="Réponse créée pour john@example.com",
        )
"""

import os
import json
import logging
from typing import List, Optional
from dataclasses import dataclass

from app.domain.ports.notification_port import (
    NotificationPort,
    NotificationPriority,
    PushNotificationResult,
)

logger = logging.getLogger(__name__)


@dataclass
class FCMConfig:
    """Configuration pour Firebase Cloud Messaging."""
    credentials_path: Optional[str] = None
    project_id: Optional[str] = None
    private_key: Optional[str] = None
    client_email: Optional[str] = None

    @classmethod
    def from_env(cls) -> "FCMConfig":
        """Charge la configuration depuis les variables d'environnement."""
        return cls(
            credentials_path=os.getenv("FIREBASE_CREDENTIALS_PATH"),
            project_id=os.getenv("FIREBASE_PROJECT_ID"),
            private_key=os.getenv("FIREBASE_PRIVATE_KEY"),
            client_email=os.getenv("FIREBASE_CLIENT_EMAIL"),
        )


class FCMAdapter(NotificationPort):
    """
    Adapter pour Firebase Cloud Messaging.

    Utilise l'API HTTP v1 de FCM pour envoyer des notifications.
    Supporte Android, iOS et Web.
    """

    def __init__(self, config: Optional[FCMConfig] = None):
        """
        Initialise l'adapter FCM.

        Args:
            config: Configuration optionnelle. Si None, charge depuis env.
        """
        self.config = config or FCMConfig.from_env()
        self._initialized = False
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[float] = None

    @property
    def name(self) -> str:
        """Nom du provider."""
        return "fcm"

    def is_available(self) -> bool:
        """Vérifie si FCM est configuré et disponible."""
        # Vérifier si les credentials sont disponibles
        if self.config.credentials_path:
            return os.path.exists(self.config.credentials_path)

        # Vérifier si les credentials sont en variables d'environnement
        return bool(
            self.config.project_id
            and self.config.private_key
            and self.config.client_email
        )

    def _get_credentials(self) -> Optional[dict]:
        """Charge les credentials Firebase."""
        if self.config.credentials_path and os.path.exists(self.config.credentials_path):
            with open(self.config.credentials_path, encoding="utf-8") as f:
                return json.load(f)

        if self.config.project_id and self.config.private_key and self.config.client_email:
            return {
                "type": "service_account",
                "project_id": self.config.project_id,
                "private_key": self.config.private_key.replace("\\n", "\n"),
                "client_email": self.config.client_email,
                "token_uri": "https://oauth2.googleapis.com/token",
            }

        return None

    def _get_access_token(self) -> Optional[str]:
        """Obtient un access token OAuth2 pour FCM."""
        import time

        # Vérifier si le token actuel est encore valide
        if self._access_token and self._token_expiry:
            if time.time() < self._token_expiry - 60:  # 60s de marge
                return self._access_token

        credentials = self._get_credentials()
        if not credentials:
            return None

        try:
            import jwt
            import requests

            # Créer le JWT pour l'authentification
            now = int(time.time())
            payload = {
                "iss": credentials["client_email"],
                "scope": "https://www.googleapis.com/auth/firebase.messaging",
                "aud": credentials["token_uri"],
                "iat": now,
                "exp": now + 3600,
            }

            token = jwt.encode(payload, credentials["private_key"], algorithm="RS256")

            # Échanger contre un access token
            response = requests.post(
                credentials["token_uri"],
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": token,
                },
                timeout=10,
            )

            if response.ok:
                data = response.json()
                self._access_token = data["access_token"]
                self._token_expiry = now + data.get("expires_in", 3600)
                return self._access_token

        except ImportError:
            logger.warning("PyJWT not installed. Run: pip install PyJWT")
        except Exception as e:
            logger.error(f"FCM auth error: {e}")

        return None

    def send(
        self,
        device_token: str,
        title: str,
        body: str,
        data: Optional[dict] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> PushNotificationResult:
        """
        Envoie une notification push via FCM.

        Args:
            device_token: Token FCM du device.
            title: Titre de la notification.
            body: Corps du message.
            data: Données additionnelles.
            priority: Priorité de la notification.

        Returns:
            Résultat de l'envoi.
        """
        if not self.is_available():
            return PushNotificationResult(
                success=False,
                error_code="NOT_CONFIGURED",
                error_message="FCM is not configured",
            )

        access_token = self._get_access_token()
        if not access_token:
            return PushNotificationResult(
                success=False,
                error_code="AUTH_FAILED",
                error_message="Failed to obtain FCM access token",
            )

        credentials = self._get_credentials()
        project_id = credentials.get("project_id") if credentials else None

        if not project_id:
            return PushNotificationResult(
                success=False,
                error_code="NO_PROJECT_ID",
                error_message="Firebase project ID not found",
            )

        # Construire le message FCM
        android_priority = "high" if priority == NotificationPriority.HIGH else "normal"

        message = {
            "message": {
                "token": device_token,
                "notification": {
                    "title": title,
                    "body": body,
                },
                "android": {
                    "priority": android_priority,
                    "notification": {
                        "click_action": "OPEN_AGENTYS",
                    },
                },
                "apns": {
                    "headers": {
                        "apns-priority": "10" if priority == NotificationPriority.HIGH else "5",
                    },
                    "payload": {
                        "aps": {
                            "alert": {
                                "title": title,
                                "body": body,
                            },
                            "sound": "default",
                        },
                    },
                },
            }
        }

        # Ajouter les données personnalisées
        if data:
            message["message"]["data"] = {k: str(v) for k, v in data.items()}

        try:
            import requests

            url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            response = requests.post(url, json=message, headers=headers, timeout=10)

            if response.ok:
                result_data = response.json()
                message_id = result_data.get("name", "").split("/")[-1]
                logger.debug(f"FCM notification sent: {message_id}")
                return PushNotificationResult(
                    success=True,
                    message_id=message_id,
                )
            else:
                error_data = response.json()
                error = error_data.get("error", {})
                return PushNotificationResult(
                    success=False,
                    error_code=error.get("status", "UNKNOWN"),
                    error_message=error.get("message", response.text),
                )

        except Exception as e:
            logger.error(f"FCM send error: {e}")
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
        Envoie une notification à plusieurs devices.

        Args:
            device_tokens: Liste des tokens FCM.
            title: Titre de la notification.
            body: Corps du message.
            data: Données additionnelles.
            priority: Priorité de la notification.

        Returns:
            Liste des résultats (un par token).
        """
        results = []
        for token in device_tokens:
            result = self.send(token, title, body, data, priority)
            results.append(result)
        return results

    def validate_token(self, device_token: str) -> bool:
        """
        Valide un token FCM.

        Note: FCM ne fournit pas d'API de validation directe.
        On vérifie juste le format du token.

        Args:
            device_token: Token à valider.

        Returns:
            True si le format semble valide.
        """
        if not device_token:
            return False

        # Les tokens FCM sont des strings d'environ 152 caractères
        if len(device_token) < 100 or len(device_token) > 200:
            return False

        # Ils contiennent généralement des caractères alphanumériques, - et _
        import re
        pattern = r'^[A-Za-z0-9_:-]+$'
        return bool(re.match(pattern, device_token))
