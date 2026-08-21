# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adaptateur Google Calendar pour Google API.

Implémente l'interface CalendarPort pour Google Calendar.
Réutilise les tokens OAuth du GmailAdapter.
"""

import os
import logging
from datetime import datetime
from typing import List, Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.domain.ports import CalendarPort


class CalendarAuthExpiredError(Exception):
    """Raised when OAuth tokens are missing or can no longer be refreshed.
    Callers should surface this as HTTP 401 with a re-auth prompt.
    """
from app.domain.entities import (
    CalendarEvent,
    CalendarEventStatus,
    CalendarEventType,
)

logger = logging.getLogger(__name__)


class GoogleCalendarAdapter(CalendarPort):
    """
    Adaptateur Google Calendar via Google API.

    Réutilise l'infrastructure d'authentification de GmailAdapter.
    Les tokens sont partagés entre Gmail et Calendar.
    """

    PROVIDER_NAME = "google_calendar"

    # Scopes requis pour le calendrier
    SCOPES = [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
    ]

    def __init__(
        self,
        account_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        """
        Initialise l'adaptateur Google Calendar.

        Args:
            account_id: ID du compte pour tokens server-side (OAuth web).
            client_id: Google Client ID (pour refresh).
            client_secret: Google Client Secret (pour refresh).
        """
        self.account_id = account_id
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")

        self._credentials: Optional[Credentials] = None
        self._service = None
        self._authenticated = False

    @property
    def name(self) -> str:
        return self.PROVIDER_NAME

    def _get_server_tokens(self) -> Optional[dict]:
        """
        Récupère les tokens depuis le stockage serveur.

        Returns:
            Token data dict ou None si non trouvé.
        """
        if not self.account_id:
            return None

        try:
            from app.api.oauth import get_tokens_server, _refresh_tokens_server
            import time

            token_data = get_tokens_server(self.account_id)
            if not token_data:
                return None

            # Auto-refresh si nécessaire (5 min buffer)
            expires_at = token_data.get("expires_at", 0)
            if time.time() > (expires_at - 5 * 60):
                logger.info(f"Token expirant pour {self.account_id}, rafraîchissement...")
                token_data = _refresh_tokens_server(self.account_id)
                if not token_data:
                    logger.error(f"Échec du rafraîchissement pour {self.account_id}")
                    # SEC-007: raise typed exception so callers can return 401.
                    raise CalendarAuthExpiredError(
                        f"Token refresh failed for account {self.account_id}"
                    )

            return token_data

        except Exception as e:
            logger.error(f"Erreur récupération tokens serveur: {e}")
            return None

    def authenticate(self) -> bool:
        """
        Authentifie via Google OAuth2.

        Réutilise les tokens du compte Gmail associé.

        Returns:
            True si l'authentification réussit.
        """
        try:
            creds = None

            # Méthode principale : Tokens stockés côté serveur (OAuth web)
            if self.account_id:
                server_tokens = self._get_server_tokens()
                if server_tokens:
                    access_token = server_tokens.get("access_token")
                    refresh_token = server_tokens.get("refresh_token")
                    if access_token:
                        creds = Credentials(
                            token=access_token,
                            refresh_token=refresh_token,
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=self.client_id,
                            client_secret=self.client_secret,
                            scopes=self.SCOPES
                        )
                        logger.info(f"Tokens serveur chargés pour Calendar {self.account_id}")

            if not creds:
                logger.error("Pas de tokens disponibles pour Google Calendar")
                return False

            # Rafraîchir si nécessaire
            if creds.refresh_token and (not creds.valid or creds.expired):
                creds.refresh(Request())

            self._credentials = creds
            self._service = build("calendar", "v3", credentials=creds)
            self._authenticated = True
            logger.info("[OK] Authentification Google Calendar réussie")
            return True

        except Exception as e:
            logger.error(f"[FAIL] Authentification Google Calendar échouée: {e}")
            self._authenticated = False
            return False

    def _ensure_authenticated(self) -> None:
        """S'assure que le service est authentifié."""
        if not self._authenticated or not self._service:
            if not self.authenticate():
                raise RuntimeError("Authentification Google Calendar requise")

    def is_available(self) -> bool:
        """Vérifie si le calendrier est accessible."""
        return self._authenticated and self._service is not None

    def _parse_datetime(self, dt_info: dict) -> tuple[datetime, bool]:
        """
        Parse la date/heure depuis le format Google Calendar.

        Args:
            dt_info: Dict avec 'dateTime' ou 'date'.

        Returns:
            Tuple (datetime, is_all_day).
        """
        if "dateTime" in dt_info:
            # Format ISO avec timezone
            dt_str = dt_info["dateTime"]
            # Handle Z suffix
            dt_str = dt_str.replace("Z", "+00:00")
            return datetime.fromisoformat(dt_str), False
        elif "date" in dt_info:
            # Événement journée entière (format YYYY-MM-DD)
            return datetime.strptime(dt_info["date"], "%Y-%m-%d"), True
        else:
            raise ValueError(f"Invalid datetime format: {dt_info}")

    def _format_datetime(self, dt: datetime, all_day: bool = False) -> dict:
        """
        Formate datetime pour Google Calendar API.

        Args:
            dt: La datetime à formater.
            all_day: Si c'est un événement journée entière.

        Returns:
            Dict pour l'API Google Calendar.
        """
        if all_day:
            return {"date": dt.strftime("%Y-%m-%d")}
        else:
            return {"dateTime": dt.isoformat(), "timeZone": "UTC"}

    def _map_to_calendar_event(self, event: dict, source_calendar_id: str = "primary") -> CalendarEvent:
        """Convertit un événement Google Calendar en CalendarEvent."""
        # Parse dates
        start_info = event.get("start", {})
        end_info = event.get("end", {})

        start_time, all_day = self._parse_datetime(start_info)
        end_time, _ = self._parse_datetime(end_info)

        # Parse status
        status_str = event.get("status", "confirmed")
        try:
            status = CalendarEventStatus(status_str)
        except ValueError:
            status = CalendarEventStatus.CONFIRMED

        # Parse attendees
        attendees = []
        for attendee in event.get("attendees", []):
            email = attendee.get("email")
            if email:
                attendees.append(email)

        # Parse created/updated times
        created_at = None
        if event.get("created"):
            created_at = datetime.fromisoformat(
                event["created"].replace("Z", "+00:00")
            )

        updated_at = None
        if event.get("updated"):
            updated_at = datetime.fromisoformat(
                event["updated"].replace("Z", "+00:00")
            )

        # Parse reminders
        reminders = []
        reminder_overrides = event.get("reminders", {}).get("overrides", [])
        for r in reminder_overrides:
            if r.get("method") == "popup":
                reminders.append(r.get("minutes", 30))

        return CalendarEvent(
            id=event["id"],
            title=event.get("summary", "(Sans titre)"),
            description=event.get("description", ""),
            start_time=start_time,
            end_time=end_time,
            all_day=all_day,
            location=event.get("location", ""),
            attendees=attendees,
            status=status,
            event_type=CalendarEventType.USER_EVENT,
            provider=self.PROVIDER_NAME,
            provider_event_id=event["id"],
            calendar_id=source_calendar_id,
            created_at=created_at,
            updated_at=updated_at,
            recurrence=event.get("recurrence", [None])[0] if event.get("recurrence") else None,
            reminders=reminders or [30],
            color=event.get("colorId"),
            html_link=event.get("htmlLink"),
        )

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
        self._ensure_authenticated()

        try:
            # Format times for API
            time_min = start_time.isoformat()
            if not time_min.endswith("Z") and "+" not in time_min:
                time_min += "Z"

            time_max = end_time.isoformat()
            if not time_max.endswith("Z") and "+" not in time_max:
                time_max += "Z"

            events_result = self._service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,  # Expand recurring events
                orderBy="startTime",
            ).execute()

            events = events_result.get("items", [])
            calendar_events = []

            for event in events:
                try:
                    calendar_events.append(self._map_to_calendar_event(event, source_calendar_id=calendar_id))
                except Exception as e:
                    logger.warning(f"Erreur parsing événement {event.get('id')}: {e}")
                    continue

            logger.info(f"Google Calendar: {len(calendar_events)} événements récupérés")
            return calendar_events

        except HttpError as e:
            logger.error(f"Erreur API Google Calendar: {e}")
            return []

    def get_event(self, event_id: str, calendar_id: str = "primary") -> Optional[CalendarEvent]:
        """
        Récupère un événement par son ID.

        Args:
            event_id: ID de l'événement.
            calendar_id: ID du calendrier.

        Returns:
            L'événement ou None si non trouvé.
        """
        self._ensure_authenticated()

        try:
            event = self._service.events().get(
                calendarId=calendar_id,
                eventId=event_id,
            ).execute()

            return self._map_to_calendar_event(event, source_calendar_id=calendar_id)

        except HttpError as e:
            logger.error(f"Événement non trouvé: {event_id} - {e}")
            return None

    def create_event(self, event: CalendarEvent, calendar_id: str = "primary") -> Optional[str]:
        """
        Crée un nouvel événement.

        Args:
            event: L'événement à créer.
            calendar_id: ID du calendrier cible.

        Returns:
            L'ID de l'événement créé ou None en cas d'échec.
        """
        self._ensure_authenticated()

        try:
            event_body = {
                "summary": event.title,
                "description": event.description,
                "location": event.location,
                "start": self._format_datetime(event.start_time, event.all_day),
                "end": self._format_datetime(event.end_time, event.all_day),
            }

            # Add color if present (Google Calendar colorId: "1"-"11")
            if event.color:
                event_body["colorId"] = str(event.color)

            # Add attendees if present
            if event.attendees:
                event_body["attendees"] = [{"email": email} for email in event.attendees]

            # Add reminders
            if event.reminders:
                event_body["reminders"] = {
                    "useDefault": False,
                    "overrides": [{"method": "popup", "minutes": m} for m in event.reminders],
                }

            # Add recurrence if present
            if event.recurrence:
                event_body["recurrence"] = [event.recurrence]

            # Add Google Meet conference link
            insert_kwargs: dict = {"calendarId": calendar_id, "body": event_body}
            if getattr(event, "conference", False):
                import uuid as _uuid
                event_body["conferenceData"] = {
                    "createRequest": {
                        "requestId": str(_uuid.uuid4()),
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                }
                insert_kwargs["conferenceDataVersion"] = 1

            created_event = self._service.events().insert(**insert_kwargs).execute()

            event_id = created_event.get("id")
            # Extract Google Meet link
            meet_link = created_event.get("hangoutLink")
            if not meet_link:
                for ep in created_event.get("conferenceData", {}).get("entryPoints", []):
                    if ep.get("entryPointType") == "video":
                        meet_link = ep.get("uri")
                        break
            self._last_meet_link: Optional[str] = meet_link
            logger.info(f"Événement créé: {event_id}" + (f" | Meet: {meet_link}" if meet_link else ""))
            return event_id

        except HttpError as e:
            logger.error(f"Erreur création événement: {e}")
            return None

    def get_freebusy(
        self,
        attendees: list[str],
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """Récupère les créneaux occupés via Google FreeBusy API."""
        self._ensure_authenticated()
        try:
            # Query ALL user calendars (not just "primary") to catch events
            # on sub-calendars (Work, Personal, shared calendars, etc.)
            items = []
            seen: set[str] = set()
            try:
                cal_list = self._service.calendarList().list().execute()
                for cal in cal_list.get("items", []):
                    cal_id = cal.get("id", "")
                    if cal_id and cal_id not in seen:
                        items.append({"id": cal_id})
                        seen.add(cal_id)
                logger.info(f"[FreeBusy] Querying {len(items)} user calendars")
            except HttpError as e:
                logger.warning(f"[FreeBusy] Cannot list calendars, falling back to primary: {e}")
                items = [{"id": "primary"}]
                seen = {"primary"}

            # Ensure "primary" is always included
            if "primary" not in seen:
                items.insert(0, {"id": "primary"})
                seen.add("primary")

            # Add external attendees
            for email in attendees:
                if email not in seen:
                    items.append({"id": email})
                    seen.add(email)

            body = {
                "timeMin": start_time.isoformat(),
                "timeMax": end_time.isoformat(),
                "items": items,
            }
            result = self._service.freebusy().query(body=body).execute()
            calendars = {}
            for email, info in result.get("calendars", {}).items():
                busy = [
                    {"start": b["start"], "end": b["end"]}
                    for b in info.get("busy", [])
                ]
                if busy:
                    logger.info(f"[FreeBusy] {email}: {len(busy)} busy blocks")
                calendars[email] = busy

            # Fallback: freebusy silently omits transparent/declined events.
            # If the user's own calendars returned 0 blocks, use events().list()
            # on "primary" to catch all opaque events (the reliable source).
            attendee_set = set(attendees)
            own_busy_count = sum(
                len(v) for k, v in calendars.items() if k not in attendee_set
            )
            if own_busy_count == 0:
                logger.warning(
                    "[FreeBusy] 0 blocs depuis les calendriers propres — "
                    "fallback events.list() sur primary"
                )
                try:
                    ev_result = self._service.events().list(
                        calendarId="primary",
                        timeMin=body["timeMin"],
                        timeMax=body["timeMax"],
                        singleEvents=True,
                        orderBy="startTime",
                        maxResults=100,
                    ).execute()
                    fallback = []
                    for ev in ev_result.get("items", []):
                        if ev.get("transparency") == "transparent":
                            continue
                        if ev.get("status") == "cancelled":
                            continue
                        s = ev.get("start", {})
                        e = ev.get("end", {})
                        ev_start = s.get("dateTime") or s.get("date")
                        ev_end   = e.get("dateTime") or e.get("date")
                        if ev_start and ev_end:
                            fallback.append({"start": ev_start, "end": ev_end})
                    if fallback:
                        logger.info(
                            f"[FreeBusy] Fallback events.list(): {len(fallback)} blocs"
                        )
                        calendars["__primary_fallback__"] = fallback
                except HttpError as fb_err:
                    logger.error(f"[FreeBusy] Fallback events.list() échoué: {fb_err}")

            return {"calendars": calendars}
        except HttpError as e:
            logger.error(f"Erreur FreeBusy: {e}")
            return {"calendars": {}}

    def update_event(self, event: CalendarEvent, calendar_id: str = "primary") -> bool:
        """
        Met à jour un événement existant.

        Args:
            event: L'événement avec les modifications.
            calendar_id: ID du calendrier.

        Returns:
            True si la mise à jour réussit.
        """
        self._ensure_authenticated()

        try:
            event_body = {
                "summary": event.title,
                "description": event.description,
                "location": event.location,
                "start": self._format_datetime(event.start_time, event.all_day),
                "end": self._format_datetime(event.end_time, event.all_day),
            }

            # Add attendees if present
            if event.attendees:
                event_body["attendees"] = [{"email": email} for email in event.attendees]

            # Add reminders
            if event.reminders:
                event_body["reminders"] = {
                    "useDefault": False,
                    "overrides": [{"method": "popup", "minutes": m} for m in event.reminders],
                }

            self._service.events().update(
                calendarId=calendar_id,
                eventId=event.provider_event_id or event.id,
                body=event_body,
            ).execute()

            logger.info(f"Événement mis à jour: {event.id}")
            return True

        except HttpError as e:
            logger.error(f"Erreur mise à jour événement: {e}")
            return False

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """
        Supprime un événement.

        Args:
            event_id: ID de l'événement à supprimer.
            calendar_id: ID du calendrier.

        Returns:
            True si la suppression réussit.
        """
        self._ensure_authenticated()

        try:
            self._service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
            ).execute()

            logger.info(f"Événement supprimé: {event_id}")
            return True

        except HttpError as e:
            if e.resp.status in (404, 410):
                logger.debug(f"Événement {event_id} déjà supprimé — considéré comme succès")
                return True
            logger.error(f"Erreur suppression événement: {e}")
            return False

    def list_calendars(self) -> List[dict]:
        """
        Liste les calendriers disponibles.

        Returns:
            Liste de dictionnaires avec id, name, primary.
        """
        self._ensure_authenticated()

        try:
            calendar_list = self._service.calendarList().list().execute()
            calendars = []

            for cal in calendar_list.get("items", []):
                calendars.append({
                    "id": cal.get("id", ""),
                    "name": cal.get("summary", ""),
                    "primary": cal.get("primary", False),
                    "access_role": cal.get("accessRole", "reader"),
                    "background_color": cal.get("backgroundColor"),
                })

            logger.info(f"Google Calendar: {len(calendars)} calendriers trouvés")
            return calendars

        except HttpError as e:
            logger.error(f"Erreur liste calendriers: {e}")
            return [{"id": "primary", "name": "Primary", "primary": True}]
