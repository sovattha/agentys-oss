# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Interface abstraite pour les fournisseurs de calendrier.

Cette abstraction permet de découpler le code métier des implémentations
spécifiques (Google Calendar, Outlook Calendar). Les composants ne voient
que des CalendarEvent standardisés.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


# Google returns the *calendar id* as ``organizer.email`` for events owned by a
# secondary / shared / resource calendar — e.g.
# ``47f9e61e4f267a2cb9173be1af598ec880047dbffc92938ac687d7f937596…@group.calendar.google.com``
# or a holiday / contacts calendar. These are opaque hashes, never something a
# user should see in an "Organisateur" field (bug 2026-06-01: the event modal
# showed a 64-char hex string instead of an email).
_OPAQUE_CAL_DOMAIN = re.compile(r"@[\w.-]*calendar\.google\.com$", re.IGNORECASE)
_OPAQUE_HEX_LOCAL = re.compile(r"^[0-9a-f]{30,}$", re.IGNORECASE)


def normalize_organizer(email: Optional[str], display_name: Optional[str] = None) -> Optional[str]:
    """Return a human-meaningful organizer string, or ``None`` to hide the field.

    A real email passes through unchanged (the user asked to "show the email").
    When the email is an opaque Google calendar id (a hex hash, or any
    ``…calendar.google.com`` address) we fall back to the human-readable display
    name; if there is none, we return ``None`` so the UI omits the row rather
    than surfacing a meaningless hash.
    """
    email = (email or "").strip()
    display = (display_name or "").strip()
    local = email.split("@", 1)[0]
    is_opaque = bool(_OPAQUE_CAL_DOMAIN.search(email) or _OPAQUE_HEX_LOCAL.match(local))
    if email and not is_opaque:
        return email
    return display or None


@dataclass
class Calendar:
    """
    Représentation normalisée d'un calendrier.

    Permet d'afficher les calendriers Google ou Outlook
    de manière uniforme dans l'interface.
    """
    id: str
    name: str
    description: Optional[str] = None
    color: Optional[str] = None  # Hex color code
    is_primary: bool = False
    can_edit: bool = True
    provider_source: str = "unknown"


@dataclass
class CalendarEvent:
    """
    Représentation normalisée d'un événement de calendrier.

    Peu importe le fournisseur source (Google Calendar, Outlook, etc.),
    tous les événements sont convertis vers ce format standard.
    """
    id: str
    title: str
    start: datetime
    end: datetime
    is_all_day: bool = False
    location: Optional[str] = None
    description: Optional[str] = None
    attendees: List[str] = field(default_factory=list)
    calendar_id: str = "primary"
    status: str = "confirmed"  # confirmed, tentative, cancelled
    provider_source: str = "unknown"

    # Optional fields for richer data
    organizer: Optional[str] = None
    is_recurring: bool = False
    recurrence_rule: Optional[str] = None
    html_link: Optional[str] = None
    color: Optional[str] = None
    meet_link: Optional[str] = None

    # Raw metadata from provider (for debug/audit)
    raw_metadata: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.provider_source}] {self.title} ({self.start} - {self.end})"

    @property
    def duration_minutes(self) -> int:
        """Retourne la durée de l'événement en minutes."""
        delta = self.end - self.start
        return int(delta.total_seconds() / 60)

    @property
    def is_happening_now(self) -> bool:
        """Vérifie si l'événement est en cours."""
        now = datetime.now(self.start.tzinfo) if self.start.tzinfo else datetime.now(timezone.utc)
        return self.start <= now <= self.end


class CalendarScopeError(Exception):
    """
    Raised when OAuth tokens lack required calendar scopes.

    This happens when a user connected their account before calendar scopes
    were added, or when the user denied calendar permissions during OAuth.
    The frontend should prompt the user to reconnect their account.
    """

    def __init__(self, account_id: str = "", provider: str = ""):
        self.account_id = account_id
        self.provider = provider
        super().__init__(
            f"Missing calendar scopes for account {account_id} ({provider}). "
            "User needs to reconnect to grant calendar permissions."
        )


class CalendarEventPermissionError(Exception):
    """
    Raised when a calendar WRITE operation is forbidden for a reason that is
    NOT a missing OAuth scope — typically the authenticated user is not the
    organizer of the event (Google ``forbiddenForNonOrganizer``) or the target
    calendar is read-only.

    Distinct from :class:`CalendarScopeError`: re-authenticating does NOT help
    here (the token already carries calendar write scope). The frontend should
    surface a clear "you can't edit this event" message, never a reconnect
    prompt. See audit 2026-05-27 (drag-drop move mislabeled as missing scope).
    """

    def __init__(self, account_id: str = "", provider: str = "", reason: str = ""):
        self.account_id = account_id
        self.provider = provider
        self.reason = reason
        super().__init__(
            f"Calendar event edit forbidden for account {account_id} ({provider}); "
            f"reason={reason or 'unknown'}. Not a scope problem — likely "
            "non-organizer or read-only calendar."
        )


class CalendarProvider(ABC):
    """
    Interface abstraite pour les fournisseurs de calendrier.

    Toutes les implémentations concrètes (GmailCalendarAdapter, OutlookCalendarAdapter)
    doivent hériter de cette classe et implémenter ses méthodes abstraites.

    Cela garantit que le code métier reste agnostique du fournisseur.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Retourne le nom du fournisseur (ex: 'google', 'outlook')."""
        pass

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authentifie la connexion au fournisseur.

        Returns:
            True si l'authentification réussit, False sinon.
        """
        pass

    @abstractmethod
    def list_calendars(self) -> List[Calendar]:
        """
        Liste les calendriers de l'utilisateur.

        Returns:
            Liste des calendriers disponibles.
        """
        pass

    @abstractmethod
    def get_events(
        self,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
        max_results: int = 100
    ) -> List[CalendarEvent]:
        """
        Récupère les événements dans une plage de dates.

        Args:
            start: Date/heure de début de la plage.
            end: Date/heure de fin de la plage.
            calendar_id: ID du calendrier (défaut: principal).
            max_results: Nombre maximum d'événements à récupérer.

        Returns:
            Liste d'événements normalisés (CalendarEvent).
        """
        pass

    @abstractmethod
    def get_event_by_id(
        self,
        event_id: str,
        calendar_id: str = "primary"
    ) -> Optional[CalendarEvent]:
        """
        Récupère un événement spécifique par son ID.

        Args:
            event_id: Identifiant unique de l'événement.
            calendar_id: ID du calendrier.

        Returns:
            L'événement normalisé ou None si non trouvé.
        """
        pass

    def get_upcoming_events(
        self,
        hours: int = 24,
        calendar_id: str = "primary",
        max_results: int = 10
    ) -> List[CalendarEvent]:
        """
        Récupère les événements à venir dans les prochaines heures.

        Args:
            hours: Nombre d'heures à considérer (défaut: 24h).
            calendar_id: ID du calendrier.
            max_results: Nombre maximum d'événements.

        Returns:
            Liste d'événements à venir.
        """
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=hours)
        return self.get_events(now, end, calendar_id, max_results)

    def get_today_events(
        self,
        calendar_id: str = "primary"
    ) -> List[CalendarEvent]:
        """
        Récupère les événements du jour.

        Args:
            calendar_id: ID du calendrier.

        Returns:
            Liste des événements d'aujourd'hui.
        """
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today.replace(hour=23, minute=59, second=59)
        return self.get_events(today, tomorrow, calendar_id)
