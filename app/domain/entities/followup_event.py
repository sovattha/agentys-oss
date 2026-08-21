# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entité FollowupEvent.

Représente un follow-up créé manuellement par l'utilisateur
ou par l'IA pour suivre un email.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from enum import Enum


class FollowupEventStatus(Enum):
    """Statut d'un follow-up."""
    PENDING = "pending"       # En attente
    COMPLETED = "completed"   # Terminé (réponse reçue ou action faite)
    SNOOZED = "snoozed"       # Reporté
    CANCELLED = "cancelled"   # Annulé


@dataclass
class FollowupEvent:
    """
    Représente un follow-up lié à un email.

    Le follow-up est stocké localement et peut être synchronisé
    vers Google Calendar ou Outlook comme un événement.

    Attributes:
        id: Identifiant unique du follow-up.
        email_id: ID de l'email associé (requis).
        account_id: ID du compte email.
        title: Titre du rappel.
        description: Notes sur le follow-up.
        due_date: Date/heure d'échéance.
        status: Statut actuel.
        created_at: Date de création.
        completed_at: Date de complétion.
        snoozed_until: Date de report si snoozé.
        snooze_count: Nombre de fois reporté.
        calendar_event_id: ID de l'événement calendrier si synchronisé.
        sync_to_calendar: Si le follow-up doit être synced au calendrier.
        email_subject: Sujet de l'email (pour affichage).
        email_sender: Expéditeur de l'email (pour affichage).
        auto_created: Si créé automatiquement par l'IA.
        ai_reason: Raison de création par l'IA (si auto_created).
    """

    id: str
    email_id: str
    account_id: str
    title: str
    due_date: datetime
    description: str = ""
    status: FollowupEventStatus = FollowupEventStatus.PENDING
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    snoozed_until: Optional[datetime] = None
    snooze_count: int = 0
    calendar_event_id: Optional[str] = None
    sync_to_calendar: bool = False
    email_subject: str = ""
    email_sender: str = ""
    auto_created: bool = False
    ai_reason: Optional[str] = None

    def __post_init__(self):
        """Validation après initialisation."""
        if not self.id:
            raise ValueError("FollowupEvent id cannot be empty")
        if not self.email_id:
            raise ValueError("FollowupEvent email_id is required")
        if not self.account_id:
            raise ValueError("FollowupEvent account_id is required")
        if not self.title:
            raise ValueError("FollowupEvent title cannot be empty")

    @property
    def is_overdue(self) -> bool:
        """Vérifie si le follow-up est en retard."""
        if self.status != FollowupEventStatus.PENDING:
            return False
        now = datetime.now(timezone.utc) if self.due_date.tzinfo else datetime.now()
        return now > self.due_date

    @property
    def is_snoozed(self) -> bool:
        """Vérifie si le follow-up est actuellement snoozé."""
        if self.status != FollowupEventStatus.SNOOZED:
            return False
        if not self.snoozed_until:
            return False
        now = datetime.now(timezone.utc) if self.snoozed_until.tzinfo else datetime.now()
        return now < self.snoozed_until

    def complete(self) -> "FollowupEvent":
        """Retourne une copie marquée comme complétée."""
        return FollowupEvent(
            id=self.id,
            email_id=self.email_id,
            account_id=self.account_id,
            title=self.title,
            due_date=self.due_date,
            description=self.description,
            status=FollowupEventStatus.COMPLETED,
            created_at=self.created_at,
            completed_at=datetime.now(timezone.utc),
            snoozed_until=None,
            snooze_count=self.snooze_count,
            calendar_event_id=self.calendar_event_id,
            sync_to_calendar=self.sync_to_calendar,
            email_subject=self.email_subject,
            email_sender=self.email_sender,
            auto_created=self.auto_created,
            ai_reason=self.ai_reason,
        )

    def snooze(self, until: datetime) -> "FollowupEvent":
        """Retourne une copie reportée à une nouvelle date."""
        return FollowupEvent(
            id=self.id,
            email_id=self.email_id,
            account_id=self.account_id,
            title=self.title,
            due_date=until,  # Update due_date
            description=self.description,
            status=FollowupEventStatus.SNOOZED,
            created_at=self.created_at,
            completed_at=None,
            snoozed_until=until,
            snooze_count=self.snooze_count + 1,
            calendar_event_id=self.calendar_event_id,
            sync_to_calendar=self.sync_to_calendar,
            email_subject=self.email_subject,
            email_sender=self.email_sender,
            auto_created=self.auto_created,
            ai_reason=self.ai_reason,
        )

    def cancel(self) -> "FollowupEvent":
        """Retourne une copie annulée."""
        return FollowupEvent(
            id=self.id,
            email_id=self.email_id,
            account_id=self.account_id,
            title=self.title,
            due_date=self.due_date,
            description=self.description,
            status=FollowupEventStatus.CANCELLED,
            created_at=self.created_at,
            completed_at=datetime.now(),
            snoozed_until=self.snoozed_until,
            snooze_count=self.snooze_count,
            calendar_event_id=self.calendar_event_id,
            sync_to_calendar=self.sync_to_calendar,
            email_subject=self.email_subject,
            email_sender=self.email_sender,
            auto_created=self.auto_created,
            ai_reason=self.ai_reason,
        )

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour JSON."""
        return {
            "id": self.id,
            "email_id": self.email_id,
            "account_id": self.account_id,
            "title": self.title,
            "description": self.description,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "snoozed_until": self.snoozed_until.isoformat() if self.snoozed_until else None,
            "snooze_count": self.snooze_count,
            "calendar_event_id": self.calendar_event_id,
            "sync_to_calendar": self.sync_to_calendar,
            "email_subject": self.email_subject,
            "email_sender": self.email_sender,
            "auto_created": self.auto_created,
            "ai_reason": self.ai_reason,
            "is_overdue": self.is_overdue,
            "is_snoozed": self.is_snoozed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FollowupEvent":
        """Crée depuis un dictionnaire."""
        # Parse datetime strings
        due_date = data.get("due_date")
        if isinstance(due_date, str):
            due_date = datetime.fromisoformat(due_date.replace("Z", "+00:00"))

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))

        snoozed_until = data.get("snoozed_until")
        if isinstance(snoozed_until, str):
            snoozed_until = datetime.fromisoformat(snoozed_until.replace("Z", "+00:00"))

        # Parse enum
        status = data.get("status", "pending")
        if isinstance(status, str):
            status = FollowupEventStatus(status)

        return cls(
            id=data["id"],
            email_id=data["email_id"],
            account_id=data["account_id"],
            title=data["title"],
            description=data.get("description", ""),
            due_date=due_date,
            status=status,
            created_at=created_at,
            completed_at=completed_at,
            snoozed_until=snoozed_until,
            snooze_count=data.get("snooze_count", 0),
            calendar_event_id=data.get("calendar_event_id"),
            sync_to_calendar=data.get("sync_to_calendar", False),
            email_subject=data.get("email_subject", ""),
            email_sender=data.get("email_sender", ""),
            auto_created=data.get("auto_created", False),
            ai_reason=data.get("ai_reason"),
        )
