# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités pour les notifications push mobiles.

Ce module définit les entités du domaine pour :
- DeviceToken : représente un appareil enregistré pour les push notifications
- PushNotification : représente une notification à envoyer
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class DevicePlatform(Enum):
    """Plateformes supportées pour les devices."""
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class PushNotificationStatus(Enum):
    """Statut d'une notification push."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class PushNotificationCategory(Enum):
    """Catégories de notifications push."""
    DRAFT_CREATED = "draft.created"
    DRAFT_FAILED = "draft.failed"
    FOLLOWUP_SENT = "followup.sent"
    HEALTH_ALERT = "health.alert"
    BUDGET_WARNING = "budget.warning"
    ERROR = "error"
    INFO = "info"


@dataclass
class DeviceToken:
    """
    Représente un appareil enregistré pour les notifications push.

    Attributes:
        token: Le token unique du device (FCM token, Expo push token, etc.)
        platform: La plateforme (ios, android, web)
        user_id: Identifiant optionnel de l'utilisateur associé
        device_name: Nom optionnel du device (ex: "iPhone de Jean")
        app_version: Version de l'app installée
        created_at: Date d'enregistrement du token
        last_used_at: Dernière utilisation (envoi de notification)
        is_active: Si le token est actif (pas révoqué)
    """
    token: str
    platform: DevicePlatform
    user_id: Optional[str] = None
    device_name: Optional[str] = None
    app_version: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_used_at: Optional[datetime] = None
    is_active: bool = True

    def __post_init__(self):
        """Validation post-initialisation."""
        if not self.token or not self.token.strip():
            raise ValueError("Device token cannot be empty")
        if isinstance(self.platform, str):
            self.platform = DevicePlatform(self.platform)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour persistance."""
        return {
            "token": self.token,
            "platform": self.platform.value,
            "user_id": self.user_id,
            "device_name": self.device_name,
            "app_version": self.app_version,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeviceToken":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            token=data["token"],
            platform=DevicePlatform(data["platform"]),
            user_id=data.get("user_id"),
            device_name=data.get("device_name"),
            app_version=data.get("app_version"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            last_used_at=datetime.fromisoformat(data["last_used_at"]) if data.get("last_used_at") else None,
            is_active=data.get("is_active", True),
        )


@dataclass
class PushNotification:
    """
    Représente une notification push à envoyer.

    Attributes:
        title: Titre de la notification
        body: Corps du message
        category: Catégorie de la notification
        data: Données additionnelles (payload JSON)
        badge: Nombre à afficher sur l'icône de l'app (iOS)
        sound: Son à jouer (True pour défaut, ou nom du fichier)
        priority: Priorité (low, normal, high)
        ttl: Time-to-live en secondes
        collapse_key: Clé pour regrouper/remplacer les notifications
        image_url: URL d'une image à afficher
    """
    title: str
    body: str
    category: PushNotificationCategory = PushNotificationCategory.INFO
    data: Optional[Dict[str, Any]] = None
    badge: Optional[int] = None
    sound: bool = True
    priority: str = "normal"
    ttl: int = 86400  # 24 heures par défaut
    collapse_key: Optional[str] = None
    image_url: Optional[str] = None

    def __post_init__(self):
        """Validation post-initialisation."""
        if not self.title or not self.title.strip():
            raise ValueError("Notification title cannot be empty")
        if not self.body or not self.body.strip():
            raise ValueError("Notification body cannot be empty")
        if isinstance(self.category, str):
            self.category = PushNotificationCategory(self.category)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour envoi via adapter."""
        return {
            "title": self.title,
            "body": self.body,
            "category": self.category.value,
            "data": self.data or {},
            "badge": self.badge,
            "sound": self.sound,
            "priority": self.priority,
            "ttl": self.ttl,
            "collapse_key": self.collapse_key,
            "image_url": self.image_url,
        }


@dataclass
class PushNotificationRecord:
    """
    Enregistrement d'une notification envoyée (pour historique).

    Attributes:
        notification: La notification envoyée
        device_token: Token du device ciblé
        status: Statut de l'envoi
        message_id: ID retourné par le provider
        sent_at: Date d'envoi
        error_message: Message d'erreur si échec
    """
    notification: PushNotification
    device_token: str
    status: PushNotificationStatus = PushNotificationStatus.PENDING
    message_id: Optional[str] = None
    sent_at: datetime = field(default_factory=datetime.now)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour persistance."""
        return {
            "notification": self.notification.to_dict(),
            "device_token": self.device_token,
            "status": self.status.value,
            "message_id": self.message_id,
            "sent_at": self.sent_at.isoformat(),
            "error_message": self.error_message,
        }
