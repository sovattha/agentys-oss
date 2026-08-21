# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entité CalendarEvent.

Représente un événement de calendrier (Google Calendar ou Outlook).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum


class CalendarEventStatus(Enum):
    """Statut d'un événement calendrier."""
    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    CANCELLED = "cancelled"


class CalendarEventType(Enum):
    """Type d'événement."""
    USER_EVENT = "user_event"  # Événement utilisateur (sync depuis Gmail/Outlook)
    FOLLOWUP = "followup"       # Follow-up Agentys (créé par l'IA ou manuellement)


@dataclass
class CalendarEvent:
    """
    Représente un événement de calendrier.

    Attributes:
        id: Identifiant unique de l'événement.
        title: Titre de l'événement.
        description: Description détaillée.
        start_time: Date/heure de début (ISO 8601).
        end_time: Date/heure de fin (ISO 8601).
        all_day: Si c'est un événement journée entière.
        location: Lieu de l'événement.
        attendees: Liste des participants (emails).
        status: Statut de l'événement.
        event_type: Type (user_event ou followup).
        provider: Source (gmail, outlook).
        provider_event_id: ID de l'événement chez le provider.
        calendar_id: ID du calendrier chez le provider.
        created_at: Date de création.
        updated_at: Date de dernière modification.
        email_id: ID de l'email associé (pour les follow-ups).
        recurrence: Règle de récurrence (RFC 5545 RRULE).
        reminders: Minutes avant l'événement pour rappels.
        color: Couleur de l'événement (hex).
        html_link: Lien vers l'événement dans le calendrier web.
    """

    id: str
    title: str
    start_time: datetime
    end_time: datetime
    description: str = ""
    all_day: bool = False
    location: str = ""
    # None is a valid value meaning "attendees not specified / leave untouched on
    # update"; [] means "no attendees / clear them". See gmail/outlook _build_event_body.
    attendees: Optional[List[str]] = field(default_factory=list)
    status: CalendarEventStatus = CalendarEventStatus.CONFIRMED
    event_type: CalendarEventType = CalendarEventType.USER_EVENT
    provider: str = ""
    provider_event_id: str = ""
    calendar_id: str = "primary"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    email_id: Optional[str] = None
    recurrence: Optional[str] = None
    reminders: List[int] = field(default_factory=lambda: [30])
    color: Optional[str] = None
    html_link: Optional[str] = None
    conference: bool = False

    def __post_init__(self):
        """Validation après initialisation."""
        if not self.id:
            raise ValueError("CalendarEvent id cannot be empty")
        if not self.title:
            raise ValueError("CalendarEvent title cannot be empty")
        if self.end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time")

    @property
    def duration_minutes(self) -> int:
        """Retourne la durée en minutes."""
        delta = self.end_time - self.start_time
        return int(delta.total_seconds() / 60)

    @property
    def is_followup(self) -> bool:
        """Vérifie si c'est un follow-up Agentys."""
        return self.event_type == CalendarEventType.FOLLOWUP

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour JSON."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "all_day": self.all_day,
            "location": self.location,
            "attendees": self.attendees,
            "status": self.status.value,
            "event_type": self.event_type.value,
            "provider": self.provider,
            "provider_event_id": self.provider_event_id,
            "calendar_id": self.calendar_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "email_id": self.email_id,
            "recurrence": self.recurrence,
            "reminders": self.reminders,
            "color": self.color,
            "html_link": self.html_link,
            "conference": self.conference,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CalendarEvent":
        """Crée depuis un dictionnaire."""
        # Parse datetime strings
        start_time = data.get("start_time")
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))

        end_time = data.get("end_time")
        if isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time.replace("Z", "+00:00"))

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))

        # Parse enums
        status = data.get("status", "confirmed")
        if isinstance(status, str):
            status = CalendarEventStatus(status)

        event_type = data.get("event_type", "user_event")
        if isinstance(event_type, str):
            event_type = CalendarEventType(event_type)

        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            start_time=start_time,
            end_time=end_time,
            all_day=data.get("all_day", False),
            location=data.get("location", ""),
            attendees=data.get("attendees", []),
            status=status,
            event_type=event_type,
            provider=data.get("provider", ""),
            provider_event_id=data.get("provider_event_id", ""),
            calendar_id=data.get("calendar_id", "primary"),
            created_at=created_at,
            updated_at=updated_at,
            email_id=data.get("email_id"),
            recurrence=data.get("recurrence"),
            reminders=data.get("reminders", [30]),
            color=data.get("color"),
            html_link=data.get("html_link"),
            conference=data.get("conference", False),
        )
