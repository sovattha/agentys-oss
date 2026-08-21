# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port Calendar - Interface pour les providers calendrier.

Ce port définit le contrat que tout adapter calendrier doit implémenter,
qu'il s'agisse de Google Calendar ou Outlook Calendar.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from app.domain.entities import CalendarEvent


class CalendarPort(ABC):
    """
    Interface abstraite pour un provider calendrier.

    Tout adapter calendrier (Google, Outlook) doit implémenter cette interface.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du provider (ex: 'google_calendar', 'outlook_calendar')."""
        pass

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authentifie le provider.

        Returns:
            True si l'authentification réussit.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Vérifie si le provider est disponible et configuré.

        Returns:
            True si le calendrier est accessible.
        """
        pass

    @abstractmethod
    def list_events(
        self,
        start_time: datetime,
        end_time: datetime,
        calendar_id: str = "primary",
        max_results: int = 100,
    ) -> List[CalendarEvent]:
        """
        Liste les événements dans une plage de dates.

        Args:
            start_time: Début de la plage.
            end_time: Fin de la plage.
            calendar_id: ID du calendrier (défaut: primary).
            max_results: Nombre maximum d'événements.

        Returns:
            Liste d'événements CalendarEvent.
        """
        pass

    @abstractmethod
    def get_event(self, event_id: str, calendar_id: str = "primary") -> Optional[CalendarEvent]:
        """
        Récupère un événement par son ID.

        Args:
            event_id: ID de l'événement.
            calendar_id: ID du calendrier.

        Returns:
            L'événement ou None si non trouvé.
        """
        pass

    @abstractmethod
    def create_event(self, event: CalendarEvent, calendar_id: str = "primary") -> Optional[str]:
        """
        Crée un nouvel événement.

        Args:
            event: L'événement à créer.
            calendar_id: ID du calendrier cible.

        Returns:
            L'ID de l'événement créé ou None en cas d'échec.
        """
        pass

    @abstractmethod
    def update_event(self, event: CalendarEvent, calendar_id: str = "primary") -> bool:
        """
        Met à jour un événement existant.

        Args:
            event: L'événement avec les modifications.
            calendar_id: ID du calendrier.

        Returns:
            True si la mise à jour réussit.
        """
        pass

    @abstractmethod
    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """
        Supprime un événement.

        Args:
            event_id: ID de l'événement à supprimer.
            calendar_id: ID du calendrier.

        Returns:
            True si la suppression réussit.
        """
        pass

    def get_freebusy(
        self,
        attendees: List[str],
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """
        Récupère les créneaux occupés des participants.

        Args:
            attendees: Liste des emails.
            start_time: Début de la plage.
            end_time: Fin de la plage.

        Returns:
            Dict avec clé 'calendars' → { email: [{ start, end }] }
        """
        return {"calendars": {}}

    def list_calendars(self) -> List[dict]:
        """
        Liste les calendriers disponibles.

        Returns:
            Liste de dictionnaires avec id, name, primary.
        """
        return [{"id": "primary", "name": "Primary", "primary": True}]
