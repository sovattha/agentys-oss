"""
Canal de communication generique pour la centralisation des donnees.

Ce module definit l'entite CommunicationChannel (Aggregate Root) et ses
Value Objects associes pour modeliser les differents canaux de communication
(email, Discord, SMS, voix, push notifications).
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
import re

from app.domain.exceptions import EmptyValueError, InvalidFormatError


class ChannelType(Enum):
    """Types de canaux de communication supportes."""
    EMAIL = "email"
    DISCORD = "discord"
    SMS = "sms"
    VOICE = "voice"
    PUSH_NOTIFICATION = "push_notification"


class ChannelStatus(Enum):
    """Etat operationnel d'un canal."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING_SETUP = "pending_setup"


@dataclass(frozen=True)
class ChannelConfig:
    """
    Configuration d'un canal (credentials, endpoints).

    Value Object immutable contenant les parametres de connexion.
    """
    credentials: Dict[str, str]
    endpoint: Optional[str] = None
    webhook_url: Optional[str] = None
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelMetrics:
    """
    Metriques d'utilisation d'un canal.

    Value Object immutable pour le suivi des statistiques.
    """
    messages_sent: int = 0
    messages_received: int = 0
    last_used_at: Optional[datetime] = None
    error_count: int = 0


UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass
class CommunicationChannel:
    """
    Canal de communication generique (Aggregate Root).

    Attributes:
        id: Identifiant unique au format UUID.
        channel_type: Type de canal (EMAIL, DISCORD, etc.).
        name: Nom descriptif du canal (max 100 caracteres).
        config: Configuration du canal (credentials, endpoints).
        status: Statut operationnel du canal.
        metrics: Metriques d'utilisation.
        created_at: Date de creation.
        updated_at: Date de derniere modification.
    """

    id: str
    channel_type: ChannelType
    name: str
    config: ChannelConfig
    status: ChannelStatus = ChannelStatus.PENDING_SETUP
    metrics: ChannelMetrics = field(default_factory=ChannelMetrics)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        self._validate_id()
        self._validate_name()

    def _validate_id(self) -> None:
        if not self.id or not self.id.strip():
            raise EmptyValueError("id", "L'identifiant ne peut pas etre vide")
        if not UUID_PATTERN.match(self.id):
            raise InvalidFormatError(
                "id",
                f"L'identifiant '{self.id}' n'est pas au format UUID valide",
            )

    def _validate_name(self) -> None:
        if not self.name or not self.name.strip():
            raise EmptyValueError("name", "Le nom ne peut pas etre vide")
        if len(self.name) > 100:
            raise ValueError("Le nom ne peut pas depasser 100 caracteres")

    def activate(self) -> "CommunicationChannel":
        """Retourne une copie avec le statut ACTIVE."""
        return replace(self, status=ChannelStatus.ACTIVE)

    def deactivate(self) -> "CommunicationChannel":
        """Retourne une copie avec le statut INACTIVE."""
        return replace(self, status=ChannelStatus.INACTIVE)

    def mark_error(self) -> "CommunicationChannel":
        """Retourne une copie avec le statut ERROR."""
        return replace(self, status=ChannelStatus.ERROR)

    def record_message_sent(self) -> "CommunicationChannel":
        """Retourne une copie avec messages_sent incremente."""
        new_metrics = replace(
            self.metrics,
            messages_sent=self.metrics.messages_sent + 1,
            last_used_at=datetime.now(),
        )
        return replace(self, metrics=new_metrics)

    def record_message_received(self) -> "CommunicationChannel":
        """Retourne une copie avec messages_received incremente."""
        new_metrics = replace(
            self.metrics,
            messages_received=self.metrics.messages_received + 1,
            last_used_at=datetime.now(),
        )
        return replace(self, metrics=new_metrics)

    def record_error(self) -> "CommunicationChannel":
        """Retourne une copie avec error_count incremente."""
        new_metrics = replace(
            self.metrics,
            error_count=self.metrics.error_count + 1,
        )
        return replace(self, metrics=new_metrics)
