# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adaptateur Outlook Calendar (Microsoft Graph API).

Implémente l'interface CalendarProvider pour Microsoft Graph Calendar.
Réutilise les tokens OAuth des comptes Outlook existants.
"""

import logging
from datetime import datetime
from typing import List, Optional

import requests

from app.interfaces.calendar_provider import CalendarProvider, Calendar, CalendarEvent, CalendarScopeError, normalize_organizer

logger = logging.getLogger(__name__)

# Outbound HTTP timeout (seconds) for Microsoft Graph Calendar.
# Calendar fetches can be slower than token refresh on large mailboxes;
# 30s prevents worker starvation if Graph becomes unresponsive.
_HTTP_TIMEOUT = 30


class OutlookCalendarAdapter(CalendarProvider):
    """
    Adaptateur Microsoft Outlook Calendar via Graph API.

    Réutilise les tokens OAuth des comptes Outlook pour accéder au calendrier.
    Les scopes Calendars.Read doivent être demandés lors de l'authentification OAuth initiale.
    """

    PROVIDER_NAME = "outlook_calendar"

    # Microsoft Graph Calendar endpoints
    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(
        self,
        account_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        """
        Initialise l'adaptateur Outlook Calendar.

        Args:
            account_id: ID du compte pour tokens server-side (OAuth web).
            access_token: Access token direct (optionnel).
        """
        self.account_id = account_id
        self._access_token = access_token
        self._authenticated = False
        self._last_meet_link: Optional[str] = None

    @property
    def provider_name(self) -> str:
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
                    return None

            return token_data

        except Exception as e:
            logger.error(f"Erreur récupération tokens serveur: {e}")
            return None

    def authenticate(self) -> bool:
        """
        Authentifie via Microsoft OAuth2.

        Réutilise les tokens OAuth du compte Outlook associé.

        Returns:
            True si l'authentification réussit.
        """
        try:
            # Récupérer les tokens stockés côté serveur
            if self.account_id:
                server_tokens = self._get_server_tokens()
                if server_tokens:
                    self._access_token = server_tokens.get("access_token")
                    if self._access_token:
                        logger.info(f"Tokens serveur chargés pour calendrier {self.account_id}")

            if not self._access_token:
                logger.error("Pas de tokens disponibles pour Outlook Calendar")
                return False

            self._authenticated = True
            logger.info("[OK] Authentification Outlook Calendar réussie")
            return True

        except Exception as e:
            logger.error(f"[FAIL] Authentification Outlook Calendar échouée: {e}")
            self._authenticated = False
            return False

    def _ensure_authenticated(self) -> None:
        """S'assure que le service est authentifié."""
        if not self._authenticated or not self._access_token:
            if not self.authenticate():
                raise RuntimeError("Authentification Outlook Calendar requise")

    def _get_headers(self) -> dict:
        """Retourne les headers d'authentification."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Prefer": 'outlook.timezone="UTC"',
        }

    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """
        Effectue une requête GET vers l'API Microsoft Graph.

        Args:
            endpoint: Endpoint de l'API (sans le base URL).
            params: Paramètres de requête optionnels.

        Returns:
            Réponse JSON ou None en cas d'erreur.
        """
        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=_HTTP_TIMEOUT)
            if response.ok:
                return response.json()
            elif response.status_code == 403:
                logger.warning(f"Outlook Calendar 403 for {self.account_id}: insufficient scopes")
                raise CalendarScopeError(account_id=self.account_id or "", provider="outlook")
            else:
                logger.error(f"Graph API error: {response.status_code} - {response.text}")
                return None
        except CalendarScopeError:
            raise
        except Exception as e:
            logger.error(f"Graph API request failed: {e}")
            return None

    def _parse_datetime(self, dt_data: dict) -> datetime:
        """Parse une date/heure depuis le format Microsoft Graph."""
        from dateutil import parser, tz

        dt_str = dt_data.get("dateTime", "")
        tz_str = dt_data.get("timeZone", "UTC")

        if dt_str:
            dt = parser.parse(dt_str)
            # If the parsed datetime is naive, attach the timezone from Graph
            if dt.tzinfo is None and tz_str:
                try:
                    tzinfo = tz.gettz(tz_str)
                    if tzinfo:
                        dt = dt.replace(tzinfo=tzinfo)
                except Exception:
                    pass
            return dt

        return datetime.now()

    def _map_to_calendar(self, cal_data: dict) -> Calendar:
        """Convertit un calendrier Outlook en Calendar standard."""
        is_default = cal_data.get("isDefaultCalendar", False)
        return Calendar(
            # Use 'primary' for the default calendar so it matches the hardcoded
            # calendar_id="primary" in _map_to_event — fixes visibleCalendarIds filter
            id="primary" if is_default else cal_data.get("id", ""),
            name=cal_data.get("name", "Sans nom"),
            description=None,  # Not available in Graph API
            color=cal_data.get("color"),
            is_primary=is_default,
            can_edit=cal_data.get("canEdit", True),
            provider_source=self.PROVIDER_NAME,
        )

    @staticmethod
    def _extract_recurrence_rule(recurrence: dict | None) -> str | None:
        """Extract a human-readable recurrence description from Graph API recurrence object."""
        if not recurrence:
            return None
        try:
            pattern = recurrence.get("pattern", {})
            rtype = pattern.get("type", "")
            interval = pattern.get("interval", 1)
            days = pattern.get("daysOfWeek", [])
            if rtype == "daily":
                return f"Every {interval} day(s)" if interval > 1 else "Daily"
            elif rtype == "weekly":
                days_str = ", ".join(days) if days else ""
                return f"Weekly on {days_str}" if days_str else "Weekly"
            elif rtype in ("absoluteMonthly", "relativeMonthly"):
                return f"Monthly (every {interval} month(s))" if interval > 1 else "Monthly"
            elif rtype in ("absoluteYearly", "relativeYearly"):
                return "Yearly"
            return rtype or None
        except Exception:
            return None

    @staticmethod
    def _clean_location(location: str, meet_link: Optional[str]) -> str:
        """Remove auto-injected Teams location when a meet_link already exists."""
        if not location or not meet_link:
            return location
        low = location.lower()
        if "microsoft teams" in low or "teams meeting" in low or "réunion teams" in low:
            return ""
        return location

    def _map_to_event(self, event_data: dict) -> CalendarEvent:
        """Convertit un événement Outlook en CalendarEvent standard."""
        # Parser les dates
        start = self._parse_datetime(event_data.get("start", {}))
        end = self._parse_datetime(event_data.get("end", {}))

        # Déterminer si c'est un événement journée entière
        is_all_day = event_data.get("isAllDay", False)
        if is_all_day:
            # Read-path mirror of the Gmail all-day handling: drop the tz and pin
            # to midnight so _serialize_event emits an offset-less ISO. A tz-aware
            # UTC midnight ("2026-06-15T00:00:00+00:00") makes the FE new Date()
            # shift west-of-UTC users back a day (birthday/PTO on the wrong column).
            start = start.replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
            end = end.replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)

        # Extraire les participants (with RSVP status in raw_metadata)
        attendees = []
        attendee_responses = {}
        for attendee in event_data.get("attendees", []):
            email_addr = attendee.get("emailAddress", {})
            email = email_addr.get("address")
            if email:
                attendees.append(email)
                att_status = attendee.get("status", {})
                attendee_responses[email] = att_status.get("response", "none")

        # Extraire l'organisateur (masque les ids opaques, préfère le nom — cf. bug 2026-06-01)
        organizer = None
        if event_data.get("organizer"):
            organizer_email = event_data["organizer"].get("emailAddress", {})
            organizer = normalize_organizer(organizer_email.get("address"), organizer_email.get("name"))

        # Déterminer le statut
        response_status = event_data.get("responseStatus", {}).get("response", "none")
        if event_data.get("isCancelled", False):
            status = "cancelled"
        elif response_status == "tentativelyAccepted":
            status = "tentative"
        else:
            status = "confirmed"

        # Extraire le corps/description (text preferred, fallback to stripped HTML)
        import html as _html
        import re
        body = event_data.get("body", {})
        body_content = body.get("content")
        if body.get("contentType") == "text":
            description = _html.unescape(body_content).strip() or None if body_content else body_content
        elif body_content:
            description = _html.unescape(re.sub(r'<[^>]+>', '', body_content)).strip() or None
        else:
            description = None

        # Strip Teams meeting boilerplate injected by Microsoft into event body
        if description:
            # Remove everything from the Teams join block onward
            description = re.split(
                r'[-_\s]*Rejoignez la réunion|[-_\s]*Join the meeting|[-_\s]*Microsoft Teams meeting|'
                r'[-_\s]*Rejoignez la r\u00e9union Teams|[-_\s]*Join Microsoft Teams',
                description, maxsplit=1, flags=re.IGNORECASE
            )[0].strip()
            # Also strip trailing separator lines (dashes, underscores, dots)
            description = re.sub(r'[\s_\-\.]{4,}$', '', description).strip()
            if not description:
                description = None

        # Extract Teams meeting link
        online_meeting = event_data.get("onlineMeeting")
        meet_link = online_meeting.get("joinUrl") if online_meeting else None

        return CalendarEvent(
            id=event_data.get("id", ""),
            title=event_data.get("subject", "(Sans titre)"),
            start=start,
            end=end,
            is_all_day=is_all_day,
            location=self._clean_location(event_data.get("location", {}).get("displayName") or "", meet_link),
            description=description,
            attendees=attendees,
            calendar_id="primary",  # Outlook doesn't include calendar ID in event
            status=status,
            provider_source=self.PROVIDER_NAME,
            organizer=organizer,
            is_recurring=event_data.get("recurrence") is not None,
            recurrence_rule=self._extract_recurrence_rule(event_data.get("recurrence")),
            html_link=event_data.get("webLink"),
            color=None,
            meet_link=meet_link,
            raw_metadata={
                "importance": event_data.get("importance"),
                "showAs": event_data.get("showAs"),
                "sensitivity": event_data.get("sensitivity"),
                "categories": event_data.get("categories", []),
                "attendee_responses": attendee_responses,
            }
        )

    def list_calendars(self) -> List[Calendar]:
        """
        Liste les calendriers de l'utilisateur.

        Returns:
            Liste des calendriers disponibles.
        """
        self._ensure_authenticated()

        result = self._make_request("/me/calendars")
        if not result:
            return []

        calendars = result.get("value", [])
        mapped = [self._map_to_calendar(cal) for cal in calendars]
        # Fallback: if no calendar was detected as default (Hotmail accounts may not
        # set isDefaultCalendar=True), force the first calendar to use id="primary"
        # so it matches the hardcoded calendar_id="primary" on events.
        if mapped and not any(c.id == "primary" for c in mapped):
            mapped[0] = Calendar(
                id="primary",
                name=mapped[0].name,
                description=mapped[0].description,
                color=mapped[0].color,
                is_primary=True,
                can_edit=mapped[0].can_edit,
                provider_source=mapped[0].provider_source,
            )
        return mapped

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
            Liste d'événements normalisés.
        """
        self._ensure_authenticated()

        # Formater les dates en ISO 8601 avec timezone UTC
        # Microsoft Graph calendarView requires timezone-aware datetimes
        start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Construire l'endpoint
        if calendar_id == "primary":
            endpoint = "/me/calendar/calendarView"
        else:
            endpoint = f"/me/calendars/{calendar_id}/calendarView"

        params = {
            "startDateTime": start_iso,
            "endDateTime": end_iso,
            "$top": max_results,
            "$orderby": "start/dateTime",
            "$select": "id,subject,start,end,isAllDay,location,body,attendees,organizer,isCancelled,recurrence,webLink,importance,showAs,sensitivity,categories,responseStatus,onlineMeeting,isOnlineMeeting"
        }

        all_events = []
        result = self._make_request(endpoint, params)
        if not result:
            return []

        all_events.extend(result.get("value", []))

        # Follow @odata.nextLink pagination
        # Audit 2026-05-11 F-03: pagination requests had a hard-coded
        # 15s timeout, while the module-wide _HTTP_TIMEOUT (30s) exists
        # specifically because Graph getEvents can stall under load.
        # Mismatch caused the loop to silently truncate calendar pages
        # under Graph slowness — double-booking risk. Log the failure
        # cause so a truncated page isn't silently swallowed.
        next_link = result.get("@odata.nextLink")
        while next_link and len(all_events) < max_results:
            try:
                resp = requests.get(next_link, headers=self._get_headers(), timeout=_HTTP_TIMEOUT)
                if not resp.ok:
                    logger.warning(
                        "[OutlookCalendar] pagination break: status=%s body=%s",
                        resp.status_code, resp.text[:200],
                    )
                    break
                page = resp.json()
                all_events.extend(page.get("value", []))
                next_link = page.get("@odata.nextLink")
            except Exception as exc:
                logger.warning("[OutlookCalendar] pagination aborted: %s", exc)
                break

        events = all_events[:max_results]
        logger.info(f"Outlook Calendar: {len(events)} événements trouvés")

        return [self._map_to_event(event) for event in events]

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
        self._ensure_authenticated()

        endpoint = f"/me/events/{event_id}"
        params = {
            "$select": "id,subject,start,end,isAllDay,location,body,attendees,organizer,isCancelled,recurrence,webLink,importance,showAs,sensitivity,categories,responseStatus,onlineMeeting,isOnlineMeeting"
        }

        result = self._make_request(endpoint, params)
        if not result:
            return None

        return self._map_to_event(result)

    # ------------------------------------------------------------------ #
    #  CRUD: create / update / delete                                     #
    # ------------------------------------------------------------------ #

    def _format_datetime(self, dt: datetime, all_day: bool = False) -> dict:
        """
        Formate une datetime pour l'API Microsoft Graph.

        Args:
            dt: La datetime à formater.
            all_day: Si c'est un événement journée entière.

        Returns:
            Dict avec dateTime et timeZone pour l'API Graph.
        """
        # Use the datetime's IANA timezone name if available — for all-day
        # events this prevents the day-shift bug where `Europe/Paris` midnight
        # was sent as `UTC` and rendered -1 day for users west of UTC
        # (audit Calendar-MEDIUM-5 "Outlook all-day timezone bug").
        tz_name = "UTC"
        try:
            if dt.tzinfo is not None:
                tz_str = str(dt.tzinfo)
                # Filter out raw UTC offset reprs like "UTC+02:00" — keep IANA
                # names ("Europe/Paris") which Microsoft Graph accepts directly.
                if "/" in tz_str or tz_str in ("UTC", "GMT"):
                    tz_name = tz_str
        except Exception:
            tz_name = "UTC"

        if all_day:
            return {
                "dateTime": dt.strftime("%Y-%m-%dT00:00:00"),
                "timeZone": tz_name,
            }
        return {
            "dateTime": dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": tz_name,
        }

    def _build_event_body(self, event) -> dict:
        """
        Construit le body JSON pour l'API Microsoft Graph depuis un événement.

        Supporte à la fois DomainCalendarEvent (start_time/end_time/all_day)
        et CalendarEvent interface (start/end/is_all_day).
        """
        start_dt = getattr(event, "start_time", None) or getattr(event, "start", None)
        end_dt = getattr(event, "end_time", None) or getattr(event, "end", None)
        all_day = getattr(event, "all_day", None)
        if all_day is None:
            all_day = getattr(event, "is_all_day", False)

        body: dict = {
            "subject": event.title,
            "body": {
                "contentType": "text",
                "content": getattr(event, "description", "") or "",
            },
            "start": self._format_datetime(start_dt, all_day),
            "end": self._format_datetime(end_dt, all_day),
            "isAllDay": bool(all_day),
        }

        location = getattr(event, "location", None)
        if location:
            body["location"] = {"displayName": location}

        # None = leave attendees untouched (a drag/resize PATCH omits the field);
        # [] = clear them (Graph PATCH drops attendees only when the empty array is
        # sent explicitly — omitting the key preserves the existing guest list).
        attendees = getattr(event, "attendees", None)
        if attendees is not None:
            body["attendees"] = [
                {"emailAddress": {"address": email}, "type": "required"}
                for email in attendees
            ]

        reminders = getattr(event, "reminders", [])
        if reminders:
            body["isReminderOn"] = True
            body["reminderMinutesBeforeStart"] = reminders[0]
            if len(reminders) > 1:
                # Microsoft Graph supports only ONE reminder per event
                # (reminderMinutesBeforeStart). Gmail honours every entry in the
                # list, so a multi-reminder event silently lost its extra
                # reminders on Outlook. Keep the first and WARN rather than drop
                # silently (chaos audit 2026-06-02, provider parity).
                logger.warning(
                    "Outlook calendar supports a single reminder; keeping %s min "
                    "and dropping %d extra reminder(s): %s",
                    reminders[0], len(reminders) - 1, reminders[1:],
                )

        # Teams online meeting. Request teamsForBusiness explicitly so work/school
        # (Entra ID) tenants reliably mint a Teams join link instead of depending
        # on the tenant's default online-meeting provider (which an admin may have
        # left unset). create_event() retries WITHOUT this field if the tenant
        # rejects it — personal Hotmail/Outlook.com accounts only accept the
        # provider-less form and 400 on teamsForBusiness.
        if getattr(event, "conference", False):
            body["isOnlineMeeting"] = True
            body["onlineMeetingProvider"] = "teamsForBusiness"

        return body

    def create_event(self, event, calendar_id: str = "primary"):
        """
        Crée un nouvel événement dans le calendrier Outlook.

        Args:
            event: L'événement à créer (DomainCalendarEvent ou CalendarEvent).
            calendar_id: ID du calendrier cible.

        Returns:
            Dict {"event_id": str, "meet_link": str|None} ou None en cas d'échec.
        """
        self._ensure_authenticated()

        try:
            event_body = self._build_event_body(event)
            wants_conference = getattr(event, "conference", False)

            if calendar_id == "primary":
                url = f"{self.GRAPH_BASE_URL}/me/calendar/events"
            else:
                url = f"{self.GRAPH_BASE_URL}/me/calendars/{calendar_id}/events"

            response = requests.post(url, headers=self._get_headers(), json=event_body, timeout=_HTTP_TIMEOUT)

            # Personal Microsoft accounts (Hotmail/Outlook.com) reject
            # onlineMeetingProvider=teamsForBusiness with HTTP 400. Retry once
            # with the provider field removed so event creation still succeeds
            # (the consumer pipeline mints a link from isOnlineMeeting alone, and
            # the no-link re-PATCH fallback below still applies).
            if (
                wants_conference
                and response.status_code == 400
                and "onlineMeetingProvider" in event_body
            ):
                logger.info(
                    "[OutlookCalendar] teamsForBusiness rejected (likely personal "
                    "account) — retrying event create without provider"
                )
                retry_body = dict(event_body)
                retry_body.pop("onlineMeetingProvider", None)
                response = requests.post(url, headers=self._get_headers(), json=retry_body, timeout=_HTTP_TIMEOUT)

            if response.status_code == 403:
                raise CalendarScopeError(account_id=self.account_id or "", provider="outlook")

            if not response.ok:
                logger.error(f"Erreur création événement Outlook: {response.status_code} - {response.text}")
                return None

            created = response.json()
            event_id = created.get("id")

            # Extract Teams meeting link from response
            online_meeting = created.get("onlineMeeting")
            meet_link = online_meeting.get("joinUrl") if online_meeting else None

            # If no link was returned, re-PATCH with isOnlineMeeting only
            # (no provider field) — works for personal Hotmail/Outlook.com accounts.
            if wants_conference and not meet_link and event_id:
                try:
                    patch_url = f"{self.GRAPH_BASE_URL}/me/events/{event_id}"
                    retry_resp = requests.patch(patch_url, headers=self._get_headers(), json={
                        "isOnlineMeeting": True,
                    }, timeout=_HTTP_TIMEOUT)
                    if retry_resp.ok:
                        retry_data = retry_resp.json()
                        online_meeting = retry_data.get("onlineMeeting")
                        meet_link = online_meeting.get("joinUrl") if online_meeting else None
                        if meet_link:
                            logger.info(f"[OutlookCalendar] Visio via consumer fallback: {meet_link}")
                        else:
                            logger.warning("[OutlookCalendar] No Teams link returned — account may not support online meetings")
                except Exception as e:
                    logger.debug(f"[OutlookCalendar] Consumer fallback PATCH failed: {e}")

            self._last_meet_link: Optional[str] = meet_link

            logger.info(f"[OutlookCalendar] Événement créé: {event_id}" + (f" | Teams: {meet_link}" if meet_link else ""))
            return {"event_id": event_id, "meet_link": meet_link}

        except CalendarScopeError:
            raise
        except Exception as e:
            logger.error(f"[OutlookCalendar] Erreur création événement: {e}")
            return None

    def update_event(self, event, calendar_id: str = "primary") -> bool:
        """
        Met à jour un événement existant dans le calendrier Outlook.

        Args:
            event: L'événement avec les modifications.
            calendar_id: ID du calendrier.

        Returns:
            True si la mise à jour réussit.
        """
        self._ensure_authenticated()

        try:
            event_body = self._build_event_body(event)
            event_id = getattr(event, "provider_event_id", None) or event.id
            url = f"{self.GRAPH_BASE_URL}/me/events/{event_id}"

            response = requests.patch(url, headers=self._get_headers(), json=event_body, timeout=_HTTP_TIMEOUT)

            if response.status_code == 403:
                raise CalendarScopeError(account_id=self.account_id or "", provider="outlook")

            if response.status_code == 404:
                logger.warning(f"Événement non trouvé pour mise à jour: {event_id}")
                return False

            if not response.ok:
                logger.error(f"Erreur mise à jour Outlook: {response.status_code} - {response.text}")
                return False

            logger.info(f"[OutlookCalendar] Événement mis à jour: {event_id}")
            return True

        except CalendarScopeError:
            raise
        except Exception as e:
            logger.error(f"[OutlookCalendar] Erreur mise à jour événement: {e}")
            return False

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """
        Supprime un événement du calendrier Outlook.

        Args:
            event_id: ID de l'événement à supprimer.
            calendar_id: ID du calendrier.

        Returns:
            True si la suppression réussit.
        """
        self._ensure_authenticated()

        try:
            url = f"{self.GRAPH_BASE_URL}/me/events/{event_id}"
            response = requests.delete(url, headers=self._get_headers(), timeout=_HTTP_TIMEOUT)

            if response.status_code == 403:
                raise CalendarScopeError(account_id=self.account_id or "", provider="outlook")

            if response.status_code == 404:
                logger.warning(f"Événement non trouvé pour suppression: {event_id}")
                return False

            if response.status_code not in [200, 204]:
                logger.error(f"Erreur suppression Outlook: {response.status_code}")
                return False

            logger.info(f"[OutlookCalendar] Événement supprimé: {event_id}")
            return True

        except CalendarScopeError:
            raise
        except Exception as e:
            logger.error(f"[OutlookCalendar] Erreur suppression événement: {e}")
            return False

    def get_freebusy(
        self,
        attendees: List[str],
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """Query Microsoft Graph getSchedule across the user + attendees.

        Mirrors the working implementation in outlook_calendar_adapter.py so
        the rsvp_meeting Quick Action can detect conflicts before
        auto-accepting an Outlook invitation.
        """
        self._ensure_authenticated()
        try:
            schedules: list[str] = list(attendees or [])
            try:
                me_resp = requests.get(
                    f"{self.GRAPH_BASE_URL}/me",
                    headers=self._get_headers(),
                    timeout=15,
                )
                if me_resp.ok:
                    j = me_resp.json()
                    my_email = j.get("mail") or j.get("userPrincipalName", "")
                    if my_email and my_email not in schedules:
                        schedules.insert(0, my_email)
            except Exception:
                pass  # Best effort — attendees still queried

            url = f"{self.GRAPH_BASE_URL}/me/calendar/getSchedule"
            calendars: dict[str, list] = {}
            # Audit 2026-05-11 B-06 (P2): Microsoft Graph getSchedule caps
            # `schedules` at 20. Without chunking, requests with >20 attendees
            # silently returned empty calendars and the UI rendered "everyone
            # is free". Chunk and merge.
            _MAX_PER_CALL = 20
            for i in range(0, max(len(schedules), 1), _MAX_PER_CALL):
                chunk = schedules[i:i + _MAX_PER_CALL]
                if not chunk:
                    break
                body = {
                    "schedules": chunk,
                    "startTime": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
                    "endTime": {"dateTime": end_time.isoformat(), "timeZone": "UTC"},
                    "availabilityViewInterval": 15,
                }
                response = requests.post(
                    url,
                    headers=self._get_headers(),
                    json=body,
                    timeout=15,
                )
                if not response.ok:
                    logger.error(
                        f"[OutlookCalendar] getSchedule chunk {i}-{i + len(chunk)} "
                        f"{response.status_code}: {response.text[:200]}"
                    )
                    continue
                data = response.json()
                for schedule in data.get("value", []):
                    email = schedule.get("scheduleId", "")
                    busy_blocks = []
                    for item in schedule.get("scheduleItems", []):
                        item_status = item.get("status")
                        if item_status in ("busy", "tentative", "oof"):
                            s = item.get("start", {})
                            e = item.get("end", {})
                            # Preserve the Outlook `showAs` status so the frontend
                            # scheduling-assistant grid can colour-code the block
                            # (busy vs tentative vs out-of-office). Google's freebusy
                            # API does not expose status — its blocks land without
                            # this field and the UI treats them as plain 'busy'.
                            busy_blocks.append({
                                "start": s.get("dateTime", ""),
                                "end": e.get("dateTime", ""),
                                "status": item_status,
                            })
                    calendars[email] = busy_blocks

            return {"calendars": calendars}

        except Exception as e:
            logger.error(f"[OutlookCalendar] FreeBusy error: {e}")
            return {"calendars": {}}

    def get_meeting_time_from_email(self, email_id: str) -> Optional[dict]:
        """Extract DTSTART / DTEND via Graph message→event navigation.

        Returns {"dtstart": datetime, "dtend": datetime} or None.
        """
        self._ensure_authenticated()
        try:
            import urllib.parse
            encoded_id = urllib.parse.quote(email_id, safe="")
            url = f"{self.GRAPH_BASE_URL}/me/messages/{encoded_id}/event"
            resp = requests.get(url, headers=self._get_headers(), timeout=_HTTP_TIMEOUT)
            if not resp.ok:
                return None
            event = resp.json()
            # Audit 2026-05-11 F-01: _parse_datetime returns a single datetime,
            # not a tuple. The previous tuple-unpack raised TypeError every
            # call → caught by the broad except below → silently returned
            # None, which made the new `available_for_invite` Quick Step
            # trigger never fire for any Outlook user.
            start_dt = self._parse_datetime(event.get("start", {}))
            end_dt = self._parse_datetime(event.get("end", {}))
            return {"dtstart": start_dt, "dtend": end_dt}
        except Exception as exc:
            logger.warning("[OutlookCalendar] get_meeting_time_from_email failed: %s", exc)
            return None

    def rsvp_event(self, email_id: str, response: str) -> dict:
        """RSVP to a meeting invitation received by email.

        Uses the Microsoft Graph message→event navigation property to find the
        calendar event, then calls the appropriate accept/decline/tentativelyAccept
        action endpoint.

        Args:
            email_id: Outlook message ID (URL-safe base64 or raw Graph ID).
            response: 'accepted' | 'declined' | 'tentative'

        Returns:
            dict with keys: ok (bool), event_id (str|None), error (str|None)
        """
        _VALID = {"accepted", "declined", "tentative"}
        if response not in _VALID:
            return {"ok": False, "error": "invalid_response"}

        self._ensure_authenticated()

        # Fetch the event linked to this invitation email.
        try:
            import urllib.parse
            encoded_id = urllib.parse.quote(email_id, safe="")
            url = f"{self.GRAPH_BASE_URL}/me/messages/{encoded_id}/event"
            resp = requests.get(url, headers=self._get_headers(), timeout=_HTTP_TIMEOUT)
            if resp.status_code == 404:
                return {"ok": False, "error": "event_not_found"}
            if resp.status_code == 403:
                raise CalendarScopeError(account_id=self.account_id or "", provider="outlook")
            if not resp.ok:
                return {"ok": False, "error": f"event_fetch_failed:{resp.status_code}"}
            event_id = resp.json().get("id")
            if not event_id:
                return {"ok": False, "error": "no_event_id"}
        except CalendarScopeError:
            raise
        except Exception as exc:
            logger.error("[OutlookCalendar] rsvp: event fetch failed: %s", exc)
            return {"ok": False, "error": "event_fetch_failed"}

        # Map response to Graph action verb.
        _action_map = {
            "accepted": "accept",
            "declined": "decline",
            "tentative": "tentativelyAccept",
        }
        action = _action_map[response]

        try:
            encoded_event_id = urllib.parse.quote(event_id, safe="")
            action_url = f"{self.GRAPH_BASE_URL}/me/events/{encoded_event_id}/{action}"
            action_resp = requests.post(
                action_url,
                headers=self._get_headers(),
                json={"sendResponse": True, "comment": ""},
                timeout=_HTTP_TIMEOUT,
            )
            if action_resp.status_code == 403:
                raise CalendarScopeError(account_id=self.account_id or "", provider="outlook")
            if not action_resp.ok and action_resp.status_code != 202:
                return {"ok": False, "error": f"rsvp_action_failed:{action_resp.status_code}"}
            logger.info("[OutlookCalendar] rsvp: %s → %s (event %s)", email_id, response, event_id)
            return {"ok": True, "event_id": event_id, "response": response}
        except CalendarScopeError:
            raise
        except Exception as exc:
            logger.error("[OutlookCalendar] rsvp: action failed: %s", exc)
            return {"ok": False, "error": "rsvp_action_failed"}
