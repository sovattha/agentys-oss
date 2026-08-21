# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adaptateur Outlook Calendar pour Microsoft Graph API.

Implémente l'interface CalendarPort pour Outlook Calendar.
Réutilise les tokens OAuth du OutlookAdapter.
"""

import logging
from datetime import datetime
from typing import List, Optional

import requests

from app.domain.ports import CalendarPort
from app.domain.entities import (
    CalendarEvent,
    CalendarEventStatus,
    CalendarEventType,
)

logger = logging.getLogger(__name__)

# Microsoft Graph API base URL
GRAPH_API_URL = "https://graph.microsoft.com/v1.0"

# Outbound HTTP timeout (seconds) for Microsoft Graph Calendar.
# Calendar fetches can be slower than token refresh on large mailboxes;
# 30s prevents worker starvation if Graph becomes unresponsive.
_HTTP_TIMEOUT = 30


class OutlookCalendarAdapter(CalendarPort):
    """
    Adaptateur Outlook Calendar via Microsoft Graph API.

    Utilise l'API REST directement avec les tokens OAuth
    stockés côté serveur (mêmes tokens que OutlookAdapter).
    """

    PROVIDER_NAME = "outlook_calendar"

    def __init__(
        self,
        account_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        """
        Initialise l'adaptateur Outlook Calendar.

        Args:
            account_id: ID du compte pour tokens server-side (OAuth web).
            access_token: Token d'accès direct (optionnel).
        """
        self.account_id = account_id
        self._access_token = access_token
        self._authenticated = False

    @property
    def name(self) -> str:
        return self.PROVIDER_NAME

    def _get_access_token(self) -> Optional[str]:
        """
        Récupère l'access token depuis le stockage serveur.

        Returns:
            Access token ou None si non trouvé.
        """
        if self._access_token:
            return self._access_token

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
                    return None

            return token_data.get("access_token")

        except Exception as e:
            logger.error(f"Erreur récupération token: {e}")
            return None

    def authenticate(self) -> bool:
        """
        Vérifie que les tokens sont disponibles.

        Returns:
            True si l'authentification réussit.
        """
        try:
            token = self._get_access_token()
            if not token:
                logger.error("Pas de token disponible pour Outlook Calendar")
                return False

            # Test la validité du token avec un appel simple
            response = requests.get(
                f"{GRAPH_API_URL}/me/calendar",
                headers={"Authorization": f"Bearer {token}"},
                timeout=_HTTP_TIMEOUT,
            )

            if response.ok:
                self._authenticated = True
                logger.info("[OK] Authentification Outlook Calendar réussie")
                return True
            else:
                logger.error(f"Token invalide: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"[FAIL] Authentification Outlook Calendar échouée: {e}")
            self._authenticated = False
            return False

    def _ensure_authenticated(self) -> None:
        """S'assure que le service est authentifié."""
        if not self._authenticated:
            if not self.authenticate():
                raise RuntimeError("Authentification Outlook Calendar requise")

    def is_available(self) -> bool:
        """Vérifie si le calendrier est accessible."""
        return self._authenticated

    def _get_headers(self) -> dict:
        """Retourne les headers avec le token."""
        token = self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _parse_datetime(self, dt_info: dict) -> tuple[datetime, bool]:
        """
        Parse la date/heure depuis le format Microsoft Graph.

        Args:
            dt_info: Dict avec 'dateTime' et 'timeZone'.

        Returns:
            Tuple (datetime, is_all_day).
        """
        dt_str = dt_info.get("dateTime", "")
        dt_info.get("timeZone", "UTC")

        # Microsoft Graph utilise toujours dateTime, isAllDay est un champ séparé
        # Le format est "2024-01-15T10:00:00.0000000"
        try:
            # Remove microseconds for parsing
            if "." in dt_str:
                dt_str = dt_str.split(".")[0]
            return datetime.fromisoformat(dt_str), False
        except ValueError:
            # Try date only format
            return datetime.strptime(dt_str[:10], "%Y-%m-%d"), True

    def _format_datetime(self, dt: datetime, all_day: bool = False) -> dict:
        """
        Formate datetime pour Microsoft Graph API.

        Args:
            dt: La datetime à formater.
            all_day: Si c'est un événement journée entière.

        Returns:
            Dict pour l'API Microsoft Graph.
        """
        if all_day:
            # Graph API attend minuit pour le début et 23:59:59 pour la fin
            # (le caller est responsable de passer la bonne valeur, mais on force ici
            # pour garantir la cohérence indépendamment des heures fournies)
            return {
                "dateTime": dt.strftime("%Y-%m-%dT00:00:00"),
                "timeZone": "UTC",
            }
        return {
            "dateTime": dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        }

    def _map_status(self, show_as: str) -> CalendarEventStatus:
        """Convertit showAs en CalendarEventStatus."""
        mapping = {
            "free": CalendarEventStatus.TENTATIVE,
            "tentative": CalendarEventStatus.TENTATIVE,
            "busy": CalendarEventStatus.CONFIRMED,
            "oof": CalendarEventStatus.CONFIRMED,  # Out of office
            "workingElsewhere": CalendarEventStatus.CONFIRMED,
        }
        return mapping.get(show_as, CalendarEventStatus.CONFIRMED)

    def _map_to_calendar_event(self, event: dict) -> CalendarEvent:
        """Convertit un événement Microsoft Graph en CalendarEvent."""
        # Parse dates
        start_info = event.get("start", {})
        end_info = event.get("end", {})

        start_time, _ = self._parse_datetime(start_info)
        end_time, _ = self._parse_datetime(end_info)

        # Check if all day event
        all_day = event.get("isAllDay", False)

        # Parse status from showAs field
        status = self._map_status(event.get("showAs", "busy"))

        # Check if cancelled
        if event.get("isCancelled", False):
            status = CalendarEventStatus.CANCELLED

        # Parse attendees
        attendees = []
        for attendee in event.get("attendees", []):
            email = attendee.get("emailAddress", {}).get("address")
            if email:
                attendees.append(email)

        # Parse created/updated times
        created_at = None
        if event.get("createdDateTime"):
            created_at = datetime.fromisoformat(
                event["createdDateTime"].replace("Z", "+00:00")
            )

        updated_at = None
        if event.get("lastModifiedDateTime"):
            updated_at = datetime.fromisoformat(
                event["lastModifiedDateTime"].replace("Z", "+00:00")
            )

        # Parse reminders (Microsoft uses reminderMinutesBeforeStart)
        reminders = []
        if event.get("isReminderOn", False):
            reminders = [event.get("reminderMinutesBeforeStart", 15)]

        return CalendarEvent(
            id=event["id"],
            title=event.get("subject", "(Sans titre)"),
            description=event.get("bodyPreview", ""),
            start_time=start_time,
            end_time=end_time,
            all_day=all_day,
            location=event.get("location", {}).get("displayName", ""),
            attendees=attendees,
            status=status,
            event_type=CalendarEventType.USER_EVENT,
            provider=self.PROVIDER_NAME,
            provider_event_id=event["id"],
            calendar_id=event.get("calendar", {}).get("id", "primary"),
            created_at=created_at,
            updated_at=updated_at,
            recurrence=event.get("recurrence", {}).get("pattern", {}).get("type") if event.get("recurrence") else None,
            reminders=reminders or [15],
            color=None,  # Microsoft doesn't expose color in the same way
            html_link=event.get("webLink"),
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
            calendar_id: ID du calendrier (défaut: primary = me/calendar).
            max_results: Nombre maximum d'événements.

        Returns:
            Liste d'événements CalendarEvent.
        """
        self._ensure_authenticated()

        try:
            # Format times for API (ISO 8601)
            time_min = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            time_max = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Build URL based on calendar_id
            if calendar_id == "primary":
                url = f"{GRAPH_API_URL}/me/calendar/calendarView"
            else:
                url = f"{GRAPH_API_URL}/me/calendars/{calendar_id}/calendarView"

            params = {
                "startDateTime": time_min,
                "endDateTime": time_max,
                "$top": max_results,
                "$orderby": "start/dateTime",
            }

            response = requests.get(url, headers=self._get_headers(), params=params, timeout=_HTTP_TIMEOUT)

            if not response.ok:
                logger.error(f"Erreur API Outlook Calendar: {response.status_code} - {response.text}")
                return []

            data = response.json()
            events = data.get("value", [])
            calendar_events = []

            for event in events:
                try:
                    calendar_events.append(self._map_to_calendar_event(event))
                except Exception as e:
                    logger.warning(f"Erreur parsing événement {event.get('id')}: {e}")
                    continue

            logger.info(f"Outlook Calendar: {len(calendar_events)} événements récupérés")
            return calendar_events

        except Exception as e:
            logger.error(f"Erreur liste événements Outlook: {e}")
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
            url = f"{GRAPH_API_URL}/me/events/{event_id}"
            response = requests.get(url, headers=self._get_headers(), timeout=_HTTP_TIMEOUT)

            if not response.ok:
                logger.error(f"Événement non trouvé: {event_id}")
                return None

            return self._map_to_calendar_event(response.json())

        except Exception as e:
            logger.error(f"Erreur récupération événement: {e}")
            return None

    def create_event(self, event: CalendarEvent, calendar_id: str = "primary") -> Optional[dict]:
        """
        Crée un nouvel événement.

        Args:
            event: L'événement à créer.
            calendar_id: ID du calendrier cible.

        Returns:
            Dict {"event_id": str, "meet_link": Optional[str]} ou None en cas d'échec.
        """
        self._ensure_authenticated()

        try:
            event_body = {
                "subject": event.title,
                "body": {
                    "contentType": "text",
                    "content": event.description,
                },
                "start": self._format_datetime(event.start_time, event.all_day),
                "end": self._format_datetime(event.end_time, event.all_day),
                "isAllDay": event.all_day,
            }

            # Add location
            if event.location:
                event_body["location"] = {"displayName": event.location}

            # Add attendees
            if event.attendees:
                event_body["attendees"] = [
                    {
                        "emailAddress": {"address": email},
                        "type": "required",
                    }
                    for email in event.attendees
                ]

            # Add reminder
            if event.reminders:
                event_body["isReminderOn"] = True
                event_body["reminderMinutesBeforeStart"] = event.reminders[0]

            # Add Teams online meeting — omit provider for personal account compat
            if getattr(event, "conference", False):
                event_body["isOnlineMeeting"] = True

            # Build URL
            if calendar_id == "primary":
                url = f"{GRAPH_API_URL}/me/calendar/events"
            else:
                url = f"{GRAPH_API_URL}/me/calendars/{calendar_id}/events"

            response = requests.post(url, headers=self._get_headers(), json=event_body, timeout=_HTTP_TIMEOUT)

            if not response.ok:
                logger.error(f"Erreur création événement: {response.status_code} - {response.text}")
                return None

            created_event = response.json()
            event_id = created_event.get("id")

            # Extract Teams meeting link from response
            meet_link = None
            online_meeting = created_event.get("onlineMeeting")
            if online_meeting:
                meet_link = online_meeting.get("joinUrl")
            self._last_meet_link: Optional[str] = meet_link
            logger.info(f"Événement créé: {event_id}" + (f" | Teams: {meet_link}" if meet_link else ""))
            return {"event_id": event_id, "meet_link": meet_link}

        except Exception as e:
            logger.error(f"Erreur création événement: {e}")
            return None

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
                "subject": event.title,
                "body": {
                    "contentType": "text",
                    "content": event.description,
                },
                "start": self._format_datetime(event.start_time, event.all_day),
                "end": self._format_datetime(event.end_time, event.all_day),
                "isAllDay": event.all_day,
            }

            # Add location
            if event.location:
                event_body["location"] = {"displayName": event.location}

            # Add reminder
            if event.reminders:
                event_body["isReminderOn"] = True
                event_body["reminderMinutesBeforeStart"] = event.reminders[0]

            event_id = event.provider_event_id or event.id
            url = f"{GRAPH_API_URL}/me/events/{event_id}"

            response = requests.patch(url, headers=self._get_headers(), json=event_body, timeout=_HTTP_TIMEOUT)

            if not response.ok:
                logger.error(f"Erreur mise à jour: {response.status_code} - {response.text}")
                return False

            logger.info(f"Événement mis à jour: {event_id}")
            return True

        except Exception as e:
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
            url = f"{GRAPH_API_URL}/me/events/{event_id}"
            response = requests.delete(url, headers=self._get_headers(), timeout=_HTTP_TIMEOUT)

            if response.status_code not in [200, 204]:
                logger.error(f"Erreur suppression: {response.status_code}")
                return False

            logger.info(f"Événement supprimé: {event_id}")
            return True

        except Exception as e:
            logger.error(f"Erreur suppression événement: {e}")
            return False

    def get_freebusy(
        self,
        attendees: list[str],
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """Récupère les créneaux occupés via Microsoft Graph getSchedule API."""
        self._ensure_authenticated()
        try:
            # Include the user's own calendar
            schedules = list(attendees)
            try:
                me_resp = requests.get(
                    f"{GRAPH_API_URL}/me",
                    headers=self._get_headers(),
                    timeout=_HTTP_TIMEOUT,
                )
                if me_resp.ok:
                    my_email = me_resp.json().get("mail") or me_resp.json().get("userPrincipalName", "")
                    if my_email and my_email not in schedules:
                        schedules.insert(0, my_email)
            except Exception:
                pass  # Best effort — attendees still queried

            url = f"{GRAPH_API_URL}/me/calendar/getSchedule"
            calendars: dict[str, list] = {}
            # Audit 2026-05-11 B-06 (P2) / 2026-06-02 #5: Microsoft Graph
            # getSchedule caps `schedules` at 20. Sending more in one call
            # silently returns an empty/partial response and the slot-finder
            # rendered "everyone is free". Chunk to 20 and merge — mirrors the
            # canonical OutlookCalendarAdapter in app/providers/outlook_calendar.py
            # (these two adapters are duplicated; keep get_freebusy in sync).
            _MAX_PER_CALL = 20
            for i in range(0, max(len(schedules), 1), _MAX_PER_CALL):
                chunk = schedules[i:i + _MAX_PER_CALL]
                if not chunk:
                    break
                body = {
                    "schedules": chunk,
                    "startTime": {
                        "dateTime": start_time.isoformat(),
                        "timeZone": "UTC",
                    },
                    "endTime": {
                        "dateTime": end_time.isoformat(),
                        "timeZone": "UTC",
                    },
                    "availabilityViewInterval": 15,
                }
                response = requests.post(
                    url,
                    headers=self._get_headers(),
                    json=body,
                    timeout=_HTTP_TIMEOUT,
                )

                if not response.ok:
                    logger.error(
                        f"Erreur getSchedule chunk {i}-{i + len(chunk)}: "
                        f"{response.status_code}"
                    )
                    continue

                data = response.json()
                for schedule in data.get("value", []):
                    email = schedule.get("scheduleId", "")
                    busy_blocks = []
                    for item in schedule.get("scheduleItems", []):
                        item_status = item.get("status")
                        if item_status in ("busy", "tentative", "oof"):
                            start_info = item.get("start", {})
                            end_info = item.get("end", {})
                            # Preserve the Outlook showAs status so the frontend
                            # scheduling grid can colour-code busy/tentative/oof
                            # (the /freebusy route forwards this as per_attendee_busy).
                            busy_blocks.append({
                                "start": start_info.get("dateTime", ""),
                                "end": end_info.get("dateTime", ""),
                                "status": item_status,
                            })
                    calendars[email] = busy_blocks

            return {"calendars": calendars}

        except Exception as e:
            logger.error(f"Erreur getSchedule Outlook: {e}")
            return {"calendars": {}}

    def list_calendars(self) -> List[dict]:
        """
        Liste les calendriers disponibles.

        Returns:
            Liste de dictionnaires avec id, name, primary.
        """
        self._ensure_authenticated()

        try:
            url = f"{GRAPH_API_URL}/me/calendars"
            response = requests.get(url, headers=self._get_headers(), timeout=_HTTP_TIMEOUT)

            if not response.ok:
                logger.error(f"Erreur liste calendriers: {response.status_code}")
                return [{"id": "primary", "name": "Calendrier", "primary": True}]

            data = response.json()
            calendars = []

            for cal in data.get("value", []):
                is_default = cal.get("isDefaultCalendar", False)
                calendars.append({
                    "id": "primary" if is_default else cal.get("id", ""),
                    "name": cal.get("name", ""),
                    "primary": is_default,
                    "can_edit": cal.get("canEdit", True),
                    "color": cal.get("color"),
                })

            logger.info(f"Outlook Calendar: {len(calendars)} calendriers trouvés")
            return calendars

        except Exception as e:
            logger.error(f"Erreur liste calendriers: {e}")
            return [{"id": "primary", "name": "Calendrier", "primary": True}]
