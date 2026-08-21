# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités pour l'app mobile companion.

Ce module définit les entités du domaine pour :
- MobileSession : session utilisateur mobile
- MobileSyncState : état de synchronisation des données
- MobileAnalyticsEvent : événement d'analytics mobile
- MobileDraft : brouillon optimisé pour le mobile
- MobileAppConfig : configuration de l'app mobile
- MobileUserPreferences : préférences utilisateur mobile
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
import uuid


class MobileEventType(Enum):
    """Types d'événements analytics mobiles."""
    APP_OPEN = "app.open"
    APP_BACKGROUND = "app.background"
    APP_CLOSE = "app.close"
    DRAFT_VIEW = "draft.view"
    DRAFT_APPROVE = "draft.approve"
    DRAFT_REJECT = "draft.reject"
    DRAFT_EDIT = "draft.edit"
    DRAFT_SEND = "draft.send"
    NOTIFICATION_OPEN = "notification.open"
    NOTIFICATION_DISMISS = "notification.dismiss"
    SETTINGS_CHANGE = "settings.change"
    SYNC_START = "sync.start"
    SYNC_COMPLETE = "sync.complete"
    SYNC_ERROR = "sync.error"
    SCREEN_VIEW = "screen.view"
    ERROR = "error"


class SyncStatus(Enum):
    """Statut de synchronisation."""
    IDLE = "idle"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class MobileDraftAction(Enum):
    """Actions possibles sur un brouillon mobile."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    SENT = "sent"


class NotificationPreference(Enum):
    """Préférences de notifications."""
    ALL = "all"
    IMPORTANT_ONLY = "important_only"
    NONE = "none"


class SyncFrequency(Enum):
    """Fréquence de synchronisation."""
    REALTIME = "realtime"
    EVERY_5_MIN = "5min"
    EVERY_15_MIN = "15min"
    EVERY_HOUR = "1hour"
    MANUAL = "manual"


@dataclass
class MobileSession:
    """
    Représente une session utilisateur mobile.

    Attributes:
        session_id: Identifiant unique de la session
        user_id: Identifiant de l'utilisateur
        device_token: Token push du device
        started_at: Début de la session
        last_activity_at: Dernière activité
        app_version: Version de l'app
        os_version: Version de l'OS (iOS 17.2, Android 14, etc.)
        device_model: Modèle du device
        is_active: Session active ou terminée
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    device_token: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    last_activity_at: datetime = field(default_factory=datetime.now)
    app_version: Optional[str] = None
    os_version: Optional[str] = None
    device_model: Optional[str] = None
    is_active: bool = True

    def __post_init__(self):
        """Validation post-initialisation."""
        if not self.user_id or not str(self.user_id).strip():
            raise ValueError("User ID cannot be empty")

    def touch(self) -> None:
        """Met à jour l'activité de la session."""
        self.last_activity_at = datetime.now()

    def end(self) -> None:
        """Termine la session."""
        self.is_active = False
        self.last_activity_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour persistance."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "device_token": self.device_token,
            "started_at": self.started_at.isoformat(),
            "last_activity_at": self.last_activity_at.isoformat(),
            "app_version": self.app_version,
            "os_version": self.os_version,
            "device_model": self.device_model,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobileSession":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            session_id=data.get("session_id", str(uuid.uuid4())),
            user_id=data["user_id"],
            device_token=data.get("device_token"),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else datetime.now(),
            last_activity_at=datetime.fromisoformat(data["last_activity_at"]) if data.get("last_activity_at") else datetime.now(),
            app_version=data.get("app_version"),
            os_version=data.get("os_version"),
            device_model=data.get("device_model"),
            is_active=data.get("is_active", True),
        )


@dataclass
class MobileSyncState:
    """
    État de synchronisation des données mobiles.

    Attributes:
        user_id: Identifiant de l'utilisateur
        device_token: Token du device
        last_sync_at: Dernière synchronisation réussie
        last_sync_status: Statut de la dernière sync
        drafts_synced_count: Nombre de brouillons synchronisés
        pending_actions_count: Actions en attente de sync (offline)
        error_message: Message d'erreur si échec
        sync_version: Version du schéma de sync (pour migrations)
    """
    user_id: str
    device_token: str
    last_sync_at: Optional[datetime] = None
    last_sync_status: SyncStatus = SyncStatus.IDLE
    drafts_synced_count: int = 0
    pending_actions_count: int = 0
    error_message: Optional[str] = None
    sync_version: int = 1

    def __post_init__(self):
        """Validation post-initialisation."""
        if not self.user_id or not str(self.user_id).strip():
            raise ValueError("User ID cannot be empty")
        if not self.device_token or not str(self.device_token).strip():
            raise ValueError("Device token cannot be empty")
        if isinstance(self.last_sync_status, str):
            self.last_sync_status = SyncStatus(self.last_sync_status)

    def mark_syncing(self) -> None:
        """Marque le début d'une synchronisation."""
        self.last_sync_status = SyncStatus.SYNCING
        self.error_message = None

    def mark_success(self, drafts_count: int) -> None:
        """Marque une synchronisation réussie."""
        self.last_sync_at = datetime.now()
        self.last_sync_status = SyncStatus.SUCCESS
        self.drafts_synced_count = drafts_count
        self.pending_actions_count = 0
        self.error_message = None

    def mark_failed(self, error: str) -> None:
        """Marque une synchronisation échouée."""
        self.last_sync_status = SyncStatus.FAILED
        self.error_message = error

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour persistance."""
        return {
            "user_id": self.user_id,
            "device_token": self.device_token,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "last_sync_status": self.last_sync_status.value,
            "drafts_synced_count": self.drafts_synced_count,
            "pending_actions_count": self.pending_actions_count,
            "error_message": self.error_message,
            "sync_version": self.sync_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobileSyncState":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            user_id=data["user_id"],
            device_token=data["device_token"],
            last_sync_at=datetime.fromisoformat(data["last_sync_at"]) if data.get("last_sync_at") else None,
            last_sync_status=SyncStatus(data.get("last_sync_status", "idle")),
            drafts_synced_count=data.get("drafts_synced_count", 0),
            pending_actions_count=data.get("pending_actions_count", 0),
            error_message=data.get("error_message"),
            sync_version=data.get("sync_version", 1),
        )


@dataclass
class MobileAnalyticsEvent:
    """
    Événement d'analytics mobile.

    Attributes:
        event_id: Identifiant unique
        event_type: Type d'événement
        user_id: Identifiant de l'utilisateur
        session_id: Identifiant de la session
        timestamp: Date/heure de l'événement
        properties: Propriétés additionnelles
        device_info: Informations sur le device
    """
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: MobileEventType = MobileEventType.APP_OPEN
    user_id: str = ""
    session_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    properties: Dict[str, Any] = field(default_factory=dict)
    device_info: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validation post-initialisation."""
        if not self.user_id:
            raise ValueError("User ID cannot be empty")
        if isinstance(self.event_type, str):
            self.event_type = MobileEventType(self.event_type)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour persistance."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "properties": self.properties,
            "device_info": self.device_info,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobileAnalyticsEvent":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            event_type=MobileEventType(data["event_type"]),
            user_id=data["user_id"],
            session_id=data.get("session_id"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
            properties=data.get("properties", {}),
            device_info=data.get("device_info", {}),
        )


@dataclass
class MobileDraft:
    """
    Représentation optimisée d'un brouillon pour le mobile.

    Attributes:
        draft_id: Identifiant du brouillon
        subject: Sujet de l'email
        recipient: Destinataire
        recipient_name: Nom du destinataire (affiché)
        body_preview: Aperçu du corps (premiers 200 caractères)
        body_full: Corps complet
        status: Statut du brouillon
        action: Action prise sur le mobile
        priority_score: Score de priorité (0-100)
        category: Catégorie de l'email
        created_at: Date de création
        updated_at: Date de modification
        is_read: Lu sur mobile
        thread_id: ID du thread email
    """
    draft_id: str
    subject: str
    recipient: str
    recipient_name: Optional[str] = None
    body_preview: str = ""
    body_full: str = ""
    status: str = "pending"
    action: MobileDraftAction = MobileDraftAction.PENDING
    priority_score: int = 50
    category: str = "NORMAL"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    is_read: bool = False
    thread_id: Optional[str] = None

    def __post_init__(self):
        """Validation et génération de l'aperçu."""
        if not self.draft_id or not str(self.draft_id).strip():
            raise ValueError("Draft ID cannot be empty")
        if not self.subject or not str(self.subject).strip():
            raise ValueError("Subject cannot be empty")
        if isinstance(self.action, str):
            self.action = MobileDraftAction(self.action)
        # Générer l'aperçu si pas fourni
        if not self.body_preview and self.body_full:
            self.body_preview = self.body_full[:200] + "..." if len(self.body_full) > 200 else self.body_full

    def mark_read(self) -> None:
        """Marque le brouillon comme lu."""
        self.is_read = True
        self.updated_at = datetime.now()

    def approve(self) -> None:
        """Approuve le brouillon."""
        self.action = MobileDraftAction.APPROVED
        self.updated_at = datetime.now()

    def reject(self) -> None:
        """Rejette le brouillon."""
        self.action = MobileDraftAction.REJECTED
        self.updated_at = datetime.now()

    def edit(self, new_body: str) -> None:
        """Édite le brouillon."""
        self.body_full = new_body
        self.body_preview = new_body[:200] + "..." if len(new_body) > 200 else new_body
        self.action = MobileDraftAction.EDITED
        self.updated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour l'API."""
        return {
            "draft_id": self.draft_id,
            "subject": self.subject,
            "recipient": self.recipient,
            "recipient_name": self.recipient_name,
            "body_preview": self.body_preview,
            "body_full": self.body_full,
            "status": self.status,
            "action": self.action.value,
            "priority_score": self.priority_score,
            "category": self.category,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_read": self.is_read,
            "thread_id": self.thread_id,
        }

    def to_list_dict(self) -> Dict[str, Any]:
        """Version allégée pour les listes (sans body_full)."""
        return {
            "draft_id": self.draft_id,
            "subject": self.subject,
            "recipient": self.recipient,
            "recipient_name": self.recipient_name,
            "body_preview": self.body_preview,
            "status": self.status,
            "action": self.action.value,
            "priority_score": self.priority_score,
            "category": self.category,
            "created_at": self.created_at.isoformat(),
            "is_read": self.is_read,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobileDraft":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            draft_id=data["draft_id"],
            subject=data["subject"],
            recipient=data["recipient"],
            recipient_name=data.get("recipient_name"),
            body_preview=data.get("body_preview", ""),
            body_full=data.get("body_full", ""),
            status=data.get("status", "pending"),
            action=MobileDraftAction(data.get("action", "pending")),
            priority_score=data.get("priority_score", 50),
            category=data.get("category", "NORMAL"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
            is_read=data.get("is_read", False),
            thread_id=data.get("thread_id"),
        )


@dataclass
class MobileUserPreferences:
    """
    Préférences utilisateur pour l'app mobile.

    Attributes:
        user_id: Identifiant de l'utilisateur
        notification_preference: Préférence de notifications
        sync_frequency: Fréquence de synchronisation
        auto_approve_threshold: Seuil de confiance pour auto-approbation (0-100)
        dark_mode: Mode sombre activé
        language: Langue de l'interface
        biometric_enabled: Authentification biométrique activée
        offline_mode: Mode offline activé
        updated_at: Date de modification
    """
    user_id: str
    notification_preference: NotificationPreference = NotificationPreference.ALL
    sync_frequency: SyncFrequency = SyncFrequency.EVERY_5_MIN
    auto_approve_threshold: int = 0  # 0 = désactivé
    dark_mode: bool = False
    language: str = "fr"
    biometric_enabled: bool = False
    offline_mode: bool = True
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Validation post-initialisation."""
        if not self.user_id or not str(self.user_id).strip():
            raise ValueError("User ID cannot be empty")
        if isinstance(self.notification_preference, str):
            self.notification_preference = NotificationPreference(self.notification_preference)
        if isinstance(self.sync_frequency, str):
            self.sync_frequency = SyncFrequency(self.sync_frequency)
        if not 0 <= self.auto_approve_threshold <= 100:
            raise ValueError("Auto-approve threshold must be between 0 and 100")

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour persistance."""
        return {
            "user_id": self.user_id,
            "notification_preference": self.notification_preference.value,
            "sync_frequency": self.sync_frequency.value,
            "auto_approve_threshold": self.auto_approve_threshold,
            "dark_mode": self.dark_mode,
            "language": self.language,
            "biometric_enabled": self.biometric_enabled,
            "offline_mode": self.offline_mode,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobileUserPreferences":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            user_id=data["user_id"],
            notification_preference=NotificationPreference(data.get("notification_preference", "all")),
            sync_frequency=SyncFrequency(data.get("sync_frequency", "5min")),
            auto_approve_threshold=data.get("auto_approve_threshold", 0),
            dark_mode=data.get("dark_mode", False),
            language=data.get("language", "fr"),
            biometric_enabled=data.get("biometric_enabled", False),
            offline_mode=data.get("offline_mode", True),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )


@dataclass
class MobileAppConfig:
    """
    Configuration de l'app mobile côté serveur.

    Attributes:
        min_version: Version minimale requise de l'app
        latest_version: Dernière version disponible
        force_update: Forcer la mise à jour
        maintenance_mode: Mode maintenance activé
        maintenance_message: Message de maintenance
        feature_flags: Flags de fonctionnalités
        api_endpoints: Endpoints API
        sync_config: Configuration de synchronisation
        updated_at: Date de modification
    """
    min_version: str = "1.0.0"
    latest_version: str = "1.0.0"
    force_update: bool = False
    maintenance_mode: bool = False
    maintenance_message: Optional[str] = None
    feature_flags: Dict[str, bool] = field(default_factory=lambda: {
        "offline_mode": True,
        "biometric_auth": True,
        "dark_mode": True,
        "quick_actions": True,
        "batch_approve": True,
        "voice_input": False,
    })
    api_endpoints: Dict[str, str] = field(default_factory=lambda: {
        "sync": "/api/mobile/sync",
        "drafts": "/api/mobile/drafts",
        "actions": "/api/mobile/actions",
        "preferences": "/api/mobile/preferences",
        "analytics": "/api/mobile/analytics",
    })
    sync_config: Dict[str, Any] = field(default_factory=lambda: {
        "max_drafts_per_sync": 100,
        "sync_timeout_seconds": 30,
        "retry_attempts": 3,
        "batch_size": 20,
    })
    updated_at: datetime = field(default_factory=datetime.now)

    def is_version_supported(self, app_version: str) -> bool:
        """Vérifie si une version de l'app est supportée."""
        return self._compare_versions(app_version, self.min_version) >= 0

    def needs_update(self, app_version: str) -> bool:
        """Vérifie si une mise à jour est disponible."""
        return self._compare_versions(app_version, self.latest_version) < 0

    def _compare_versions(self, v1: str, v2: str) -> int:
        """Compare deux versions semver. Retourne -1, 0, ou 1."""
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]
        # Compléter les parties manquantes avec des 0
        while len(parts1) < 3:
            parts1.append(0)
        while len(parts2) < 3:
            parts2.append(0)
        for i in range(3):
            if parts1[i] < parts2[i]:
                return -1
            elif parts1[i] > parts2[i]:
                return 1
        return 0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour l'API."""
        return {
            "min_version": self.min_version,
            "latest_version": self.latest_version,
            "force_update": self.force_update,
            "maintenance_mode": self.maintenance_mode,
            "maintenance_message": self.maintenance_message,
            "feature_flags": self.feature_flags,
            "api_endpoints": self.api_endpoints,
            "sync_config": self.sync_config,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobileAppConfig":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            min_version=data.get("min_version", "1.0.0"),
            latest_version=data.get("latest_version", "1.0.0"),
            force_update=data.get("force_update", False),
            maintenance_mode=data.get("maintenance_mode", False),
            maintenance_message=data.get("maintenance_message"),
            feature_flags=data.get("feature_flags", {}),
            api_endpoints=data.get("api_endpoints", {}),
            sync_config=data.get("sync_config", {}),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )


@dataclass
class MobileSyncResponse:
    """
    Réponse d'une synchronisation mobile.

    Attributes:
        success: Synchronisation réussie
        drafts: Liste des brouillons synchronisés
        sync_state: État de synchronisation mis à jour
        server_timestamp: Timestamp serveur
        has_more: Plus de données disponibles
        next_cursor: Curseur pour pagination
    """
    success: bool
    drafts: List[MobileDraft] = field(default_factory=list)
    sync_state: Optional[MobileSyncState] = None
    server_timestamp: datetime = field(default_factory=datetime.now)
    has_more: bool = False
    next_cursor: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour l'API."""
        return {
            "success": self.success,
            "drafts": [d.to_list_dict() for d in self.drafts],
            "sync_state": self.sync_state.to_dict() if self.sync_state else None,
            "server_timestamp": self.server_timestamp.isoformat(),
            "has_more": self.has_more,
            "next_cursor": self.next_cursor,
            "error_message": self.error_message,
        }


@dataclass
class MobileDraftActionRequest:
    """
    Requête d'action sur un brouillon depuis le mobile.

    Attributes:
        draft_id: Identifiant du brouillon
        action: Action à effectuer
        user_id: Identifiant de l'utilisateur
        edited_body: Nouveau corps si édité
        device_token: Token du device
        offline_timestamp: Timestamp de l'action offline (si applicable)
    """
    draft_id: str
    action: MobileDraftAction
    user_id: str
    edited_body: Optional[str] = None
    device_token: Optional[str] = None
    offline_timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Validation post-initialisation."""
        if not self.draft_id or not str(self.draft_id).strip():
            raise ValueError("Draft ID cannot be empty")
        if not self.user_id or not str(self.user_id).strip():
            raise ValueError("User ID cannot be empty")
        if isinstance(self.action, str):
            self.action = MobileDraftAction(self.action)
        # Valider que edited_body est fourni pour les éditions
        if self.action == MobileDraftAction.EDITED and not self.edited_body:
            raise ValueError("Edited body is required for edit action")

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "draft_id": self.draft_id,
            "action": self.action.value,
            "user_id": self.user_id,
            "edited_body": self.edited_body,
            "device_token": self.device_token,
            "offline_timestamp": self.offline_timestamp.isoformat() if self.offline_timestamp else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobileDraftActionRequest":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            draft_id=data["draft_id"],
            action=MobileDraftAction(data["action"]),
            user_id=data["user_id"],
            edited_body=data.get("edited_body"),
            device_token=data.get("device_token"),
            offline_timestamp=datetime.fromisoformat(data["offline_timestamp"]) if data.get("offline_timestamp") else None,
        )


@dataclass
class MobileStats:
    """
    Statistiques pour le dashboard mobile.

    Attributes:
        user_id: Identifiant de l'utilisateur
        total_drafts: Total de brouillons
        pending_drafts: Brouillons en attente
        approved_today: Approuvés aujourd'hui
        rejected_today: Rejetés aujourd'hui
        avg_response_time_seconds: Temps moyen de réponse
        ai_accuracy_percentage: Précision de l'IA
        time_saved_minutes: Temps économisé (minutes)
        period_start: Début de la période
        period_end: Fin de la période
    """
    user_id: str
    total_drafts: int = 0
    pending_drafts: int = 0
    approved_today: int = 0
    rejected_today: int = 0
    avg_response_time_seconds: float = 0.0
    ai_accuracy_percentage: float = 0.0
    time_saved_minutes: int = 0
    period_start: datetime = field(default_factory=datetime.now)
    period_end: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour l'API."""
        return {
            "user_id": self.user_id,
            "total_drafts": self.total_drafts,
            "pending_drafts": self.pending_drafts,
            "approved_today": self.approved_today,
            "rejected_today": self.rejected_today,
            "avg_response_time_seconds": self.avg_response_time_seconds,
            "ai_accuracy_percentage": self.ai_accuracy_percentage,
            "time_saved_minutes": self.time_saved_minutes,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
        }
