# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour le calendrier.

Endpoints disponibles:
- GET /api/calendar/calendars - Liste des calendriers de l'utilisateur
- GET /api/calendar/events - Événements dans une plage de dates
- GET /api/calendar/events/<id> - Détail d'un événement

Ces endpoints réutilisent l'authentification OAuth des comptes email existants.
Seuls les comptes Gmail et Outlook supportent le calendrier.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time as _cache_time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from flask import Blueprint, g, has_request_context, request, jsonify

from app.interfaces.calendar_provider import CalendarScopeError, CalendarEventPermissionError
from app.domain.entities.calendar_event import CalendarEvent as DomainCalendarEvent
from app.providers.calendar_factory import (
    create_calendar_provider,
    supports_calendar,
)
from app.multi_accounts import get_account_manager
from app.api._auth_helpers import get_auth_user_id, check_account_ownership

logger = logging.getLogger(__name__)

calendar_routes_bp = Blueprint("calendar_routes", __name__)

# ============================================================================
# CALENDAR CACHE (shorter TTL than emails - events change more frequently)
# ============================================================================
_calendar_events_cache = {}  # Key: (account_id, start, end, cal_scope) -> {"data": [], "timestamp": float}
_calendar_events_cache_lock = threading.Lock()
CALENDAR_CACHE_TTL_SECONDS = 60  # Cache for 1 minute

# Separate short-lived cache for /upcoming (external API call, ~600ms without cache)
_upcoming_events_cache: dict = {}  # Key: (account_id, hours, limit) -> {"data": dict, "timestamp": float}
_upcoming_events_cache_lock = threading.Lock()
UPCOMING_CACHE_TTL_SECONDS = 30  # 30s — fresh enough for meeting banner accuracy


def _get_cached_events(account_id: str, start: str, end: str, cal_scope: str = "primary"):
    """Get cached events if fresh. cal_scope distinguishes single-calendar vs multi-calendar requests."""
    cache_key = (account_id, start, end, cal_scope)
    with _calendar_events_cache_lock:
        entry = _calendar_events_cache.get(cache_key)
        if entry and (_cache_time.time() - entry["timestamp"]) < CALENDAR_CACHE_TTL_SECONDS:
            return entry["data"]
    return None


def _set_cached_events(account_id: str, start: str, end: str, events: list, cal_scope: str = "primary"):
    """Cache events response."""
    cache_key = (account_id, start, end, cal_scope)
    with _calendar_events_cache_lock:
        _calendar_events_cache[cache_key] = {
            "data": events,
            "timestamp": _cache_time.time(),
        }
        # Limit cache size (keep last 20 queries)
        if len(_calendar_events_cache) > 20:
            oldest_key = min(_calendar_events_cache, key=lambda k: _calendar_events_cache[k]["timestamp"])
            del _calendar_events_cache[oldest_key]


def _invalidate_account_calendar_cache(account_id: str):
    """Efface tous les événements en cache pour un compte donné après mutation."""
    with _calendar_events_cache_lock:
        keys_to_delete = [k for k in _calendar_events_cache if k[0] == account_id]
        for k in keys_to_delete:
            del _calendar_events_cache[k]


def _empty_passive_calendar_payload(
    account_id: str | None,
    message: str,
    *,
    needs_reauth: bool = True,
    **extra,
) -> dict:
    """Payload 200 pour les lectures passives calendrier.

    Ces endpoints alimentent des surfaces d'arrière-plan (Deep Work, meeting
    reminders). Une absence de calendrier connecté ne doit pas polluer la
    console navigateur avec des 4xx.
    """
    return {
        "events": [],
        "count": 0,
        "account_id": account_id,
        "calendar_unavailable": True,
        "needs_reauth": needs_reauth,
        "message": message,
        **extra,
    }


def _fetch_events_multi(provider, calendar_ids: list[str], start: datetime, end: datetime, limit: int):
    """Fetch events from multiple calendars in parallel and merge.

    Deduplicates by event id (Google can return the same accepted invitation from
    multiple calendars; the first occurrence wins). Per-calendar errors are logged
    but don't fail the whole request — a single broken calendar shouldn't blank
    out the calendar view.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    merged: list = []
    seen_ids: set[str] = set()
    # Per-calendar limit — request `limit` from each so we don't truncate any
    # single calendar before merging. The caller still caps via list slicing.
    per_cal_limit = limit if limit else 100
    max_workers = min(len(calendar_ids), 8)

    def _fetch(cal_id: str):
        try:
            return cal_id, provider.get_events(start, end, cal_id, per_cal_limit), None
        except CalendarScopeError:
            # Re-raised below — scope errors are fatal for the whole request.
            raise
        except Exception as exc:
            return cal_id, [], exc

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch, cid): cid for cid in calendar_ids}
        for future in as_completed(futures):
            cal_id = futures[future]
            try:
                _, events, err = future.result()
                if err:
                    logger.warning(f"[CAL] multi-fetch failed for {cal_id}: {err}")
                    continue
                for event in events:
                    if event.id in seen_ids:
                        continue
                    seen_ids.add(event.id)
                    merged.append(event)
            except CalendarScopeError:
                raise

    # Sort by start as ISO string — avoids tz-naive/aware comparison errors
    # that bite when mixing all-day events (naive) with timed events (aware).
    def _sort_key(e):
        dt = getattr(e, "start", None) or getattr(e, "start_time", None)
        return dt.isoformat() if dt else ""
    merged.sort(key=_sort_key)
    return merged


def _serialize_event(event) -> dict:
    """Serialize a CalendarEvent to JSON-serializable dict.

    Supports both interface CalendarEvent (is_all_day, start, end)
    and domain CalendarEvent (all_day, start_time, end_time).
    """
    start = getattr(event, "start", None) or getattr(event, "start_time", None)
    end = getattr(event, "end", None) or getattr(event, "end_time", None)
    is_all_day = getattr(event, "is_all_day", None)
    if is_all_day is None:
        is_all_day = getattr(event, "all_day", False)

    return {
        "id": event.id,
        "title": event.title,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "isAllDay": is_all_day,
        "location": getattr(event, "location", None),
        "description": getattr(event, "description", None),
        "attendees": getattr(event, "attendees", []),
        "calendarId": getattr(event, "calendar_id", "primary"),
        "status": getattr(event, "status", "confirmed"),
        "providerSource": getattr(event, "provider_source", "unknown"),
        "organizer": getattr(event, "organizer", None),
        "isRecurring": getattr(event, "is_recurring", False),
        "htmlLink": getattr(event, "html_link", None),
        "color": getattr(event, "color", None),
        "meetLink": getattr(event, "meet_link", None),
    }


def _serialize_calendar(calendar) -> dict:
    """Serialize a Calendar to JSON-serializable dict."""
    return {
        "id": calendar.id,
        "name": calendar.name,
        "description": calendar.description,
        "color": calendar.color,
        "isPrimary": calendar.is_primary,
        "canEdit": calendar.can_edit,
        "providerSource": calendar.provider_source,
    }


def _get_auth_email() -> str:
    auth_user = getattr(g, "auth_user", None) if has_request_context() else None
    return ((auth_user or {}).get("email") or "").strip().lower()


def _resolve_numeric_db_account_id(raw_id: str) -> str | None:
    """Map a DB account id from /api/init to the OAuth account id used by calendar."""
    try:
        db_account_id = int(raw_id)
    except (TypeError, ValueError):
        return None

    auth_user_id = get_auth_user_id()
    auth_email = _get_auth_email()
    try:
        from app.api.routes_helpers import get_db_session
        from app.db.repositories.account_repository import AccountRepository

        with get_db_session() as session:
            db_account = AccountRepository(session).get(db_account_id)
            if not db_account:
                return None

            email = (getattr(db_account, "email", "") or "").strip()
            provider_type = (getattr(db_account, "provider", "") or "").strip().lower()

            if auth_user_id is not None:
                db_user_id = getattr(db_account, "user_id", None)
                email_matches_jwt = bool(auth_email and email.lower() == auth_email)
                if db_user_id is None:
                    if not email_matches_jwt:
                        return None
                else:
                    try:
                        if int(db_user_id) != int(auth_user_id):
                            return None
                    except (TypeError, ValueError):
                        return None
    except Exception as e:
        logger.error(f"Error resolving numeric calendar account_id {raw_id}: {e}")
        return None

    if not email or not supports_calendar(provider_type):
        return None

    try:
        manager = get_account_manager()
        oauth_account = manager.get_account_by_email(email)
        if oauth_account:
            if auth_user_id is not None and getattr(oauth_account, "user_id", None) is None:
                updated = manager.update_account(oauth_account.id, user_id=auth_user_id)
                oauth_account = updated or oauth_account

            if check_account_ownership(oauth_account, auth_user_id):
                oauth_provider = (
                    oauth_account.provider.value
                    if hasattr(oauth_account.provider, "value")
                    else str(oauth_account.provider)
                )
                if supports_calendar(oauth_provider.lower()):
                    return oauth_account.id
    except Exception as e:
        logger.error(f"Error resolving OAuth account for DB account_id {raw_id}: {e}")

    try:
        import hashlib
        from app.api.oauth import get_tokens_server

        candidate_id = hashlib.sha256(f"{provider_type}:{email}".encode()).hexdigest()[:16]
        token_data = get_tokens_server(candidate_id)
        token_email = (token_data or {}).get("email", "").strip().lower()
        token_provider = (token_data or {}).get("provider", "").strip().lower()
        if token_email == email.lower() and token_provider == provider_type:
            return candidate_id
    except Exception as e:
        logger.debug(f"Token-based calendar account resolution skipped for {raw_id}: {e}")

    return None


def _resolve_account_id(raw_id: str | None) -> str | None:
    """Resolve a numeric DB ID or OAuth ID to the actual OAuth account ID.

    The frontend /api/init returns numeric IDs (e.g. 8) while calendar
    routes need the OAuth account ID (e.g. 'ca85336e01d3bc46').
    Numeric IDs can't be OAuth IDs, so map them through the DB account email
    before falling back to the active OAuth account.

    Validates ownership: rejects account IDs that don't belong to the
    authenticated user.
    """
    if not raw_id:
        return _get_active_account_id()
    # Numeric IDs come from the DB — resolve to the matching OAuth account.
    # If the client supplied an explicit stale/foreign ID, fail closed instead
    # of falling back to the active account and masking the frontend bug.
    if raw_id.isdigit():
        return _resolve_numeric_db_account_id(raw_id)
    # Validate ownership of explicitly provided account ID (F5: wrapped in try/except)
    try:
        manager = get_account_manager()
        account = manager.get_account(raw_id)
        auth_user_id = get_auth_user_id()
        if account and check_account_ownership(account, auth_user_id):
            return raw_id
        return None
    except Exception as e:
        logger.error(f"Error resolving account_id ownership: {e}")
        return None


def _get_active_account_id() -> str | None:
    """Get the active account ID (current account if it supports calendar).

    Uses per-user isolation: only returns accounts owned by the authenticated user.
    """
    try:
        manager = get_account_manager()
        auth_user_id = get_auth_user_id()

        # Prefer the currently selected account for this user
        current_id = manager.get_current_for_user(auth_user_id)
        if current_id:
            current = manager.get_account(current_id)
            if current and check_account_ownership(current, auth_user_id):
                provider_type = current.provider.value if hasattr(current.provider, 'value') else str(current.provider)
                if supports_calendar(provider_type.lower()):
                    return current.id

        # Fallback: first account with calendar support owned by this user
        for account in manager.get_all_accounts():
            if not check_account_ownership(account, auth_user_id):
                continue
            provider_type = account.provider.value if hasattr(account.provider, 'value') else str(account.provider)
            if supports_calendar(provider_type.lower()):
                return account.id

        auth_email = _get_auth_email()
        if auth_email:
            try:
                from app.api.routes_helpers import get_db_session
                from app.db.repositories.account_repository import AccountRepository

                with get_db_session() as session:
                    db_account = AccountRepository(session).get_by_email(auth_email)
                    if db_account and getattr(db_account, "is_active", True):
                        resolved = _resolve_numeric_db_account_id(str(db_account.id))
                        if resolved:
                            return resolved
            except Exception as e:
                logger.error(f"Error resolving active DB calendar account: {e}")

        return None
    except Exception as e:
        logger.error(f"Error getting active account: {e}")
        return None


def _make_scope_error_response(e: CalendarScopeError):
    """Return a structured 403 response for missing calendar scopes."""
    return jsonify({
        "error": "missing_calendar_scope",
        "needs_reauth": True,
        # Kept English to prevent French leakage; FE shows its own localized
        # "needs reauth" banner driven by the `needs_reauth: true` flag.
        "message": "Your account must be reconnected to access the calendar.",
        "account_id": e.account_id,
        "provider": e.provider,
    }), 403


def _make_event_forbidden_response(e: CalendarEventPermissionError):
    """Return a structured 403 for a calendar WRITE forbidden for a reason that
    is NOT a missing scope — typically a non-organizer move or a read-only
    calendar. Unlike _make_scope_error_response, ``needs_reauth`` is False:
    reconnecting would not help, so the FE shows a clear "can't edit this
    event" message instead of a reconnect banner. See audit 2026-05-27."""
    return jsonify({
        "error": "calendar_event_forbidden",
        "needs_reauth": False,
        # English message; the FE localizes off the `error` code.
        "message": "You can't change this event — only its organizer can reschedule it.",
        "reason": getattr(e, "reason", "") or "forbidden",
        "account_id": e.account_id,
        "provider": e.provider,
    }), 403


# ============================================================================
# ROUTES
# ============================================================================


@calendar_routes_bp.route("/status", methods=["GET"])
def calendar_status():
    """
    Quick check: can this account access calendar data?

    Checks stored token scopes without making a Google/Outlook API call.

    Query params:
        account_id: ID du compte (optionnel)

    Returns:
        ready: true if calendar scopes are present
        needs_reauth: true if reconnection is needed
    ---
    tags:
      - Calendar
    summary: Statut d'accès calendrier
    """
    account_id = _resolve_account_id(request.args.get("account_id"))

    if not account_id:
        return jsonify({
            "ready": False,
            "needs_reauth": False,
            "message": "No OAuth account found",
        })

    try:
        from app.api.oauth import get_tokens_server
        token_data = get_tokens_server(account_id)

        if not token_data:
            return jsonify({
                "ready": False,
                "needs_reauth": True,
                "message": "No tokens found for this account",
                "account_id": account_id,
            })

        scopes_str = token_data.get("scope", "")
        scope_set = set(scopes_str.split()) if scopes_str else set()

        provider = token_data.get("provider", "")

        # Check for calendar scopes
        from app.providers.calendar_factory import GOOGLE_CALENDAR_SCOPES, OUTLOOK_CALENDAR_SCOPES
        required = GOOGLE_CALENDAR_SCOPES if provider == "gmail" else OUTLOOK_CALENDAR_SCOPES
        has_calendar = bool(scope_set & required)

        if not has_calendar:
            return jsonify({
                "ready": False,
                "needs_reauth": True,
                # Kept English to prevent French leakage; FE shows its own localized
        # "needs reauth" banner driven by the `needs_reauth: true` flag.
        "message": "Your account must be reconnected to access the calendar.",
                "account_id": account_id,
                "provider": provider,
            })

        return jsonify({
            "ready": True,
            "needs_reauth": False,
            "account_id": account_id,
            "provider": provider,
        })

    except Exception as e:
        logger.error(f"Error checking calendar status: {e}")
        return jsonify({
            "ready": False,
            "needs_reauth": False,
            "message": str(e),
        }), 500


@calendar_routes_bp.route("/calendars", methods=["GET"])
def list_calendars():
    """
    Liste les calendriers de l'utilisateur.

    Query params:
        account_id: ID du compte (optionnel, utilise le compte actif par défaut)

    Returns:
        Liste des calendriers avec leurs métadonnées.
    ---
    tags:
      - Calendar
    summary: Liste des calendriers
    """
    account_id = _resolve_account_id(request.args.get("account_id"))

    if not account_id:
        return jsonify({
            "error": "No OAuth account found",
            "message": "Calendar requires a Gmail or Outlook account connected via OAuth",
            "calendars": [],
        }), 400

    try:
        provider = create_calendar_provider(account_id)
        if not provider:
            return jsonify({
                "error": "Calendar not supported",
                "message": "This account type does not support calendar integration",
                "calendars": [],
            }), 400

        calendars = provider.list_calendars()
        return jsonify({
            "calendars": [_serialize_calendar(cal) for cal in calendars],
            "count": len(calendars),
            "account_id": account_id,
        })

    except CalendarScopeError as e:
        return _make_scope_error_response(e)
    except Exception as e:
        logger.error(f"Error listing calendars: {e}")
        return jsonify({
            "error": "Failed to list calendars",
            "message": str(e),
            "calendars": [],
        }), 500


@calendar_routes_bp.route("/events", methods=["GET"])
def get_events():
    """
    Récupère les événements dans une plage de dates.

    Query params:
        start: Date de début (ISO 8601, défaut: aujourd'hui 00:00)
        end: Date de fin (ISO 8601, défaut: aujourd'hui + 7 jours)
        calendar_id: ID du calendrier (défaut: primary)
        account_id: ID du compte (optionnel)
        limit: Nombre max d'événements (défaut: 100)

    Returns:
        Liste des événements triés par date de début.
    ---
    tags:
      - Calendar
    summary: Événements du calendrier
    """
    _raw_aid = request.args.get("account_id")
    # Audit F-01 (2026-05-17 deep-audit): the previous `_raw_aid or _active_aid`
    # short-circuited ownership validation whenever the caller supplied any
    # account_id at all, letting any authenticated user read any other user's
    # Google/Outlook calendar with one HTTP call. Route through the same
    # `_resolve_account_id` helper every sibling route in this file uses
    # (it validates ownership and falls back to the authenticated user's
    # active account when raw_id is None).
    account_id = _resolve_account_id(_raw_aid)
    logger.debug(f"get_events: raw_param={repr(_raw_aid)}, resolved={repr(account_id)}")
    calendar_id = request.args.get("calendar_id", "primary")
    # calendar_ids (plural) — comma-separated list. When present, fetch + merge
    # events from every listed calendar in parallel. Lets the UI filter by toggles
    # over non-primary calendars (holidays, shared, etc.).
    calendar_ids_raw = request.args.get("calendar_ids")
    calendar_ids = [c.strip() for c in calendar_ids_raw.split(",") if c.strip()] if calendar_ids_raw else []
    try:
        limit = min(int(request.args.get("limit", 100)), 250)  # Max 250
    except (ValueError, TypeError):
        limit = 100

    # Parse dates
    try:
        start_str = request.args.get("start")
        if start_str:
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        else:
            start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        end_str = request.args.get("end")
        if end_str:
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        else:
            end = start + timedelta(days=7)
    except ValueError as e:
        return jsonify({
            "error": "Invalid date format",
            "message": f"Use ISO 8601 format (e.g., 2026-02-05T00:00:00): {e}",
            "events": [],
        }), 400

    if not account_id:
        return jsonify({
            "error": "No OAuth account found",
            "message": "Calendar requires a Gmail or Outlook account connected via OAuth",
            "events": [],
        }), 400

    # Check cache — separate scopes for single vs multi so they don't collide.
    start_cache_key = start.isoformat()
    end_cache_key = end.isoformat()
    cal_scope = "multi:" + ",".join(sorted(calendar_ids)) if calendar_ids else calendar_id
    cached = _get_cached_events(account_id, start_cache_key, end_cache_key, cal_scope)
    if cached is not None:
        return jsonify({
            "events": cached[:limit],
            "count": min(len(cached), limit),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "account_id": account_id,
            "source": "cache",
        })

    try:
        # Try creating provider — if it fails, retry with active account fallback
        provider = create_calendar_provider(account_id)
        if not provider and _raw_aid:
            # Param account_id resolved (ownership passed) but provider creation
            # failed — fall back to the authenticated user's active calendar
            # account as a UX recovery. Resolve at fallback time so we don't
            # leak per-user state from the request-args path.
            fallback_aid = _get_active_account_id()
            if fallback_aid and fallback_aid != account_id:
                logger.warning(f"[CAL] Provider failed for {account_id}, retrying with active account {fallback_aid}")
                account_id = fallback_aid
                provider = create_calendar_provider(account_id)
        if not provider:
            logger.warning(f"[CAL] Provider creation failed for {account_id}")
            return jsonify({
                "error": "Calendar not supported",
                "message": "This account type does not support calendar integration",
                "events": [],
            }), 400

        if calendar_ids:
            events = _fetch_events_multi(provider, calendar_ids, start, end, limit)
        else:
            events = provider.get_events(start, end, calendar_id, limit)
        serialized = [_serialize_event(event) for event in events]

        # Cache the results
        _set_cached_events(account_id, start_cache_key, end_cache_key, serialized, cal_scope)

        return jsonify({
            "events": serialized,
            "count": len(serialized),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "account_id": account_id,
            "source": "api",
        })

    except CalendarScopeError as e:
        return _make_scope_error_response(e)
    except Exception as e:
        logger.error(f"Error fetching events: {e}")
        return jsonify({
            "error": "Failed to fetch events",
            "message": str(e),
            "events": [],
        }), 500


@calendar_routes_bp.route("/events/<event_id>", methods=["GET"])
def get_event_by_id(event_id: str):
    """
    Récupère un événement spécifique par son ID.

    Path params:
        event_id: ID de l'événement

    Query params:
        calendar_id: ID du calendrier (défaut: primary)
        account_id: ID du compte (optionnel)

    Returns:
        Détails de l'événement.
    ---
    tags:
      - Calendar
    summary: Détail d'un événement
    """
    account_id = _resolve_account_id(request.args.get("account_id"))
    calendar_id = request.args.get("calendar_id", "primary")

    if not account_id:
        return jsonify({
            "error": "No OAuth account found",
            "message": "Calendar requires a Gmail or Outlook account connected via OAuth",
        }), 400

    if not event_id:
        return jsonify({"error": "Event ID required"}), 400

    try:
        provider = create_calendar_provider(account_id)
        if not provider:
            return jsonify({
                "error": "Calendar not supported",
                "message": "This account type does not support calendar integration",
            }), 400

        event = provider.get_event_by_id(event_id, calendar_id)
        if not event:
            return jsonify({"error": "Event not found"}), 404

        return jsonify({
            "event": _serialize_event(event),
            "account_id": account_id,
        })

    except CalendarScopeError as e:
        return _make_scope_error_response(e)
    except Exception as e:
        logger.error(f"Error fetching event {event_id}: {e}")
        return jsonify({
            "error": "Failed to fetch event",
            "message": str(e),
        }), 500


# ============================================================================
# HOLIDAYS — Public holiday calendars (Google Calendar)
# ============================================================================

# Timezone → Google public holiday calendar ID
_TIMEZONE_HOLIDAY_MAP = {
    "America/New_York": "en.usa#holiday@group.v.calendar.google.com",
    "America/Los_Angeles": "en.usa#holiday@group.v.calendar.google.com",
    "America/Chicago": "en.usa#holiday@group.v.calendar.google.com",
    "America/Toronto": "en.canadian#holiday@group.v.calendar.google.com",
    "America/Montreal": "en.canadian#holiday@group.v.calendar.google.com",
    "America/Vancouver": "en.canadian#holiday@group.v.calendar.google.com",
    "America/Edmonton": "en.canadian#holiday@group.v.calendar.google.com",
    "America/Winnipeg": "en.canadian#holiday@group.v.calendar.google.com",
    "America/Halifax": "en.canadian#holiday@group.v.calendar.google.com",
    "America/Sao_Paulo": "pt-br.brazilian#holiday@group.v.calendar.google.com",
    "Europe/London": "en.uk#holiday@group.v.calendar.google.com",
    "Europe/Paris": "fr.french#holiday@group.v.calendar.google.com",
    "Europe/Moscow": "en.russian#holiday@group.v.calendar.google.com",
    "Asia/Dubai": "en.ae#holiday@group.v.calendar.google.com",
    "Asia/Kolkata": "en.indian#holiday@group.v.calendar.google.com",
    "Asia/Singapore": "en.singapore#holiday@group.v.calendar.google.com",
    "Asia/Shanghai": "en.china#holiday@group.v.calendar.google.com",
    "Asia/Tokyo": "en.japanese#holiday@group.v.calendar.google.com",
    "Australia/Sydney": "en.australian#holiday@group.v.calendar.google.com",
}

# Separate cache for holidays (longer TTL — holidays don't change)
_holidays_cache = {}  # Key: (account_id, calendar_id, start, end) -> {"data": [], "timestamp": float}
_holidays_cache_lock = threading.Lock()
HOLIDAYS_CACHE_TTL_SECONDS = 3600  # 1 hour


def _get_cached_holidays(account_id: str, calendar_id: str, start: str, end: str):
    cache_key = (account_id, calendar_id, start, end)
    with _holidays_cache_lock:
        entry = _holidays_cache.get(cache_key)
        if entry and (_cache_time.time() - entry["timestamp"]) < HOLIDAYS_CACHE_TTL_SECONDS:
            return entry["data"]
    return None


def _set_cached_holidays(account_id: str, calendar_id: str, start: str, end: str, data: list):
    cache_key = (account_id, calendar_id, start, end)
    with _holidays_cache_lock:
        _holidays_cache[cache_key] = {
            "data": data,
            "timestamp": _cache_time.time(),
        }
        if len(_holidays_cache) > 30:
            oldest_key = min(_holidays_cache, key=lambda k: _holidays_cache[k]["timestamp"])
            del _holidays_cache[oldest_key]


@calendar_routes_bp.route("/holidays", methods=["GET"])
def get_holidays():
    """
    Récupère les jours fériés d'un pays via les calendriers publics Google.

    Query params:
        timezone: Fuseau horaire IANA (ex: America/New_York)
        start: Date de début (ISO 8601)
        end: Date de fin (ISO 8601)

    Returns:
        Liste des jours fériés (titre + date) pour le pays du fuseau.
    ---
    tags:
      - Calendar
    summary: Jours fériés par fuseau horaire
    """
    tz_param = request.args.get("timezone", "")
    if not tz_param:
        return jsonify({"error": "timezone parameter required", "holidays": []}), 400

    holiday_calendar_id = _TIMEZONE_HOLIDAY_MAP.get(tz_param)
    if not holiday_calendar_id:
        return jsonify({"error": f"No holiday calendar for timezone: {tz_param}", "holidays": []}), 404

    account_id = _resolve_account_id(request.args.get("account_id"))
    if not account_id:
        return jsonify({"error": "No OAuth account found", "holidays": []}), 400

    # Parse dates
    try:
        from datetime import timezone as _tz
        start_str = request.args.get("start")
        if start_str:
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        else:
            start = datetime.now(_tz.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        end_str = request.args.get("end")
        if end_str:
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        else:
            end = start + timedelta(days=7)
    except ValueError as e:
        return jsonify({"error": f"Invalid date format: {e}", "holidays": []}), 400

    # Check cache
    start_key = start.isoformat()
    end_key = end.isoformat()
    cached = _get_cached_holidays(account_id, holiday_calendar_id, start_key, end_key)
    if cached is not None:
        return jsonify({"holidays": cached, "timezone": tz_param, "source": "cache"})

    try:
        provider = create_calendar_provider(account_id)
        if not provider:
            return jsonify({"error": "Calendar provider not available", "holidays": []}), 400

        events = provider.get_events(start, end, calendar_id=holiday_calendar_id, max_results=50)
        holidays = [
            {
                "id": e.id,
                "title": e.title,
                "date": e.start.strftime("%Y-%m-%d") if e.start else None,
                "isAllDay": True,
            }
            for e in events
        ]

        _set_cached_holidays(account_id, holiday_calendar_id, start_key, end_key, holidays)

        return jsonify({"holidays": holidays, "timezone": tz_param, "source": "api"})

    except CalendarScopeError as e:
        return _make_scope_error_response(e)
    except Exception as e:
        logger.warning(f"Could not fetch holidays for {tz_param}: {e}")
        return jsonify({"holidays": [], "timezone": tz_param, "error": str(e)})


# ============================================================================
# PUBLIC HOLIDAYS — Nager.Date (provincial/regional, sans OAuth)
# ============================================================================

# Timezone IANA → (ISO country code, ISO 3166-2 region code or None)
# Region None = national holidays only; region code = national + regional
_TIMEZONE_REGION_MAP: dict[str, tuple[str, str | None]] = {
    # Canada — timezone identifies province
    "America/Toronto":             ("CA", "CA-ON"),
    "America/Montreal":            ("CA", "CA-QC"),
    "America/Vancouver":           ("CA", "CA-BC"),
    "America/Edmonton":            ("CA", "CA-AB"),
    "America/Winnipeg":            ("CA", "CA-MB"),
    "America/Halifax":             ("CA", "CA-NS"),
    "America/St_Johns":            ("CA", "CA-NL"),
    "America/Regina":              ("CA", "CA-SK"),
    "America/Moncton":             ("CA", "CA-NB"),
    "America/Whitehorse":          ("CA", "CA-YT"),
    "America/Yellowknife":         ("CA", "CA-NT"),
    "America/Iqaluit":             ("CA", "CA-NU"),
    # Australia — timezone identifies state
    "Australia/Sydney":            ("AU", "AU-NSW"),
    "Australia/Melbourne":         ("AU", "AU-VIC"),
    "Australia/Brisbane":          ("AU", "AU-QLD"),
    "Australia/Perth":             ("AU", "AU-WA"),
    "Australia/Adelaide":          ("AU", "AU-SA"),
    "Australia/Darwin":            ("AU", "AU-NT"),
    "Australia/Hobart":            ("AU", "AU-TAS"),
    "Australia/Lord_Howe":         ("AU", "AU-NSW"),
    # USA
    "America/New_York":            ("US", None),
    "America/Chicago":             ("US", None),
    "America/Denver":              ("US", None),
    "America/Los_Angeles":         ("US", None),
    "America/Phoenix":             ("US", None),
    "America/Anchorage":           ("US", None),
    "Pacific/Honolulu":            ("US", None),
    # Europe
    "Europe/Paris":                ("FR", None),
    "Europe/Berlin":               ("DE", None),
    "Europe/London":               ("GB", None),
    "Europe/Madrid":               ("ES", None),
    "Europe/Rome":                 ("IT", None),
    "Europe/Amsterdam":            ("NL", None),
    "Europe/Brussels":             ("BE", None),
    "Europe/Zurich":               ("CH", None),
    "Europe/Vienna":               ("AT", None),
    "Europe/Warsaw":               ("PL", None),
    "Europe/Stockholm":            ("SE", None),
    "Europe/Oslo":                 ("NO", None),
    "Europe/Copenhagen":           ("DK", None),
    "Europe/Helsinki":             ("FI", None),
    "Europe/Lisbon":               ("PT", None),
    "Europe/Athens":               ("GR", None),
    "Europe/Prague":               ("CZ", None),
    "Europe/Budapest":             ("HU", None),
    "Europe/Bucharest":            ("RO", None),
    "Europe/Moscow":               ("RU", None),
    "Europe/Istanbul":             ("TR", None),
    "Europe/Kiev":                 ("UA", None),
    "Europe/Dublin":               ("IE", None),
    "Europe/Bratislava":           ("SK", None),
    "Europe/Ljubljana":            ("SI", None),
    "Europe/Zagreb":               ("HR", None),
    "Europe/Belgrade":             ("RS", None),
    "Europe/Sofia":                ("BG", None),
    "Europe/Vilnius":              ("LT", None),
    "Europe/Riga":                 ("LV", None),
    "Europe/Tallinn":              ("EE", None),
    "Europe/Luxembourg":           ("LU", None),
    # Americas
    "America/Sao_Paulo":           ("BR", None),
    "America/Mexico_City":         ("MX", None),
    "America/Argentina/Buenos_Aires": ("AR", None),
    "America/Bogota":              ("CO", None),
    "America/Lima":                ("PE", None),
    "America/Santiago":            ("CL", None),
    "America/Caracas":             ("VE", None),
    # Asia
    "Asia/Tokyo":                  ("JP", None),
    "Asia/Shanghai":               ("CN", None),
    "Asia/Hong_Kong":              ("HK", None),
    "Asia/Singapore":              ("SG", None),
    "Asia/Seoul":                  ("KR", None),
    "Asia/Kolkata":                ("IN", None),
    "Asia/Dubai":                  ("AE", None),
    "Asia/Bangkok":                ("TH", None),
    "Asia/Jakarta":                ("ID", None),
    "Asia/Manila":                 ("PH", None),
    "Asia/Kuala_Lumpur":           ("MY", None),
    "Asia/Karachi":                ("PK", None),
    "Asia/Dhaka":                  ("BD", None),
    "Asia/Colombo":                ("LK", None),
    "Asia/Kathmandu":              ("NP", None),
    "Asia/Jerusalem":              ("IL", None),
    "Asia/Riyadh":                 ("SA", None),
    "Asia/Beirut":                 ("LB", None),
    "Asia/Amman":                  ("JO", None),
    # Africa
    "Africa/Cairo":                ("EG", None),
    "Africa/Johannesburg":         ("ZA", None),
    "Africa/Lagos":                ("NG", None),
    "Africa/Nairobi":              ("KE", None),
    "Africa/Casablanca":           ("MA", None),
    "Africa/Tunis":                ("TN", None),
    "Africa/Algiers":              ("DZ", None),
    # Pacific
    "Pacific/Auckland":            ("NZ", None),
}

# Cache: (country_code, region_or_none, year) → list of holidays
_public_holidays_cache: dict = {}
_public_holidays_cache_lock = threading.Lock()
PUBLIC_HOLIDAYS_CACHE_TTL = 86400  # 24h — holidays don't change within a year


def _get_public_holidays_cached(country: str, region: str | None, year: int):
    key = (country, region, year)
    with _public_holidays_cache_lock:
        entry = _public_holidays_cache.get(key)
        if entry and (_cache_time.time() - entry["ts"]) < PUBLIC_HOLIDAYS_CACHE_TTL:
            return entry["data"]
    return None


def _set_public_holidays_cached(country: str, region: str | None, year: int, data: list):
    key = (country, region, year)
    with _public_holidays_cache_lock:
        _public_holidays_cache[key] = {"data": data, "ts": _cache_time.time()}
        if len(_public_holidays_cache) > 200:
            oldest = min(_public_holidays_cache, key=lambda k: _public_holidays_cache[k]["ts"])
            del _public_holidays_cache[oldest]


# Strict ISO 3166 validation for the upstream Nager.Date URL fragment (audit
# L-2, issue #545). The hostname is fixed, but `country` is interpolated into
# the path — without these regexes, `country=FR/../OtherEndpoint` would hit a
# different upstream route. Region is interpolated downstream into the cache
# key, never the URL, but we lock its shape too so cache poisoning by garbage
# input is impossible. ISO 3166-2 subdivisions are up to 3 alphanumerics.
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_REGION_RE = re.compile(r"^(?:[A-Z]{2}-)?[A-Z0-9]{1,3}$")


def _fetch_nager_year(country: str, year: int) -> list:
    """Fetch all holidays for a country/year from Nager.Date. Returns raw list.

    Caller MUST pre-validate ``country`` against ``_COUNTRY_RE``. The hostname
    is fixed but ``country`` lives in the URL path, so a missing validation
    upstream would let a caller pivot to other routes on date.nager.at.
    """
    if not _COUNTRY_RE.fullmatch(country):
        raise ValueError(f"invalid country code: {country!r}")
    url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"
    req = urllib.request.Request(url, headers={"User-Agent": "Agentys/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def _filter_nager_by_region(raw: list, region: str | None) -> list:
    """Keep global holidays + regional ones matching region_code."""
    result = []
    for h in raw:
        if h.get("global"):
            result.append(h)
        elif region and h.get("counties") and region in h["counties"]:
            result.append(h)
    return result


def _holiday_range_dates(start_dt, end_dt, tz_param):
    """Return ``(start_date, end_date)`` as CALENDAR DATES in the requested IANA
    timezone, not UTC.

    The FE sends the visible-range bounds as local-midnight converted to
    Z-suffixed UTC (``toISOString``), so for east-of-UTC users they land at e.g.
    22:00 the PREVIOUS UTC day. Taking ``.date()`` in UTC then shifted the
    half-open holiday window back a day and dropped a holiday on the LAST visible
    grid day (chaos audit 2026-06-02). Falls back to the UTC date when the tz is
    missing/invalid (pre-fix behaviour).
    """
    tz = None
    if tz_param:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_param)
        except Exception:
            tz = None
    if tz is not None:
        return start_dt.astimezone(tz).date(), end_dt.astimezone(tz).date()
    return start_dt.date(), end_dt.date()


@calendar_routes_bp.route("/public-holidays", methods=["GET"])
def get_public_holidays():
    """
    Jours fériés provinciaux/régionaux via Nager.Date (sans OAuth).

    Query params:
        timezone: Fuseau horaire IANA (ex: America/Montreal)
        start: Date de début ISO 8601
        end: Date de fin ISO 8601

    Returns list of {id, title, date}.
    """
    tz_param = request.args.get("timezone", "")

    # Accept direct country+region from IP detection (bypasses timezone lookup).
    # Strict ISO validation (audit L-2, #545): country goes into the upstream
    # URL path so any non-ISO-3166 char would let a caller pivot to other
    # routes on date.nager.at; region goes into the cache key. Reject upfront
    # rather than escape downstream so the failure mode is "400 invalid
    # country" instead of an opaque upstream 404.
    direct_country = request.args.get("country", "").strip().upper()
    direct_region = request.args.get("region", "").strip().upper()  # ex: "QC" → becomes "CA-QC"

    if direct_country and not _COUNTRY_RE.fullmatch(direct_country):
        return jsonify({"holidays": [], "error": "invalid country code (expected ISO 3166-1 alpha-2)"}), 400
    if direct_region and not _REGION_RE.fullmatch(direct_region):
        return jsonify({"holidays": [], "error": "invalid region code (expected ISO 3166-2 subdivision)"}), 400

    if direct_country and direct_region:
        country_code = direct_country
        # Build ISO 3166-2 region code if not already prefixed
        region_code = direct_region if "-" in direct_region else f"{direct_country}-{direct_region}"
    elif direct_country:
        country_code = direct_country
        region_code = None
    else:
        if not tz_param:
            return jsonify({"holidays": [], "error": "timezone or country required"}), 400
        mapping = _TIMEZONE_REGION_MAP.get(tz_param)
        if not mapping:
            return jsonify({"holidays": [], "timezone": tz_param}), 200
        country_code, region_code = mapping

    try:
        from datetime import timezone as _tz
        start_str = request.args.get("start")
        end_str = request.args.get("end")
        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if start_str else datetime.now(_tz.utc)
        end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else start_dt + timedelta(days=7)
    except ValueError as e:
        return jsonify({"holidays": [], "error": f"Invalid date: {e}"}), 400

    years = list({start_dt.year, end_dt.year})
    all_raw: list = []

    for year in years:
        cached = _get_public_holidays_cached(country_code, region_code, year)
        if cached is not None:
            all_raw.extend(cached)
            continue
        try:
            raw = _fetch_nager_year(country_code, year)
            filtered = _filter_nager_by_region(raw, region_code)
            year_holidays = [
                {"id": h["date"], "title": h.get("localName") or h.get("name", ""), "date": h["date"]}
                for h in filtered
            ]
            _set_public_holidays_cached(country_code, region_code, year, year_holidays)
            all_raw.extend(year_holidays)
        except Exception as e:
            logger.warning(f"[public-holidays] Nager.Date fetch failed for {country_code}/{year}: {e}")

    # Normalize the visible-range bounds to a CALENDAR DATE in the REQUESTED
    # timezone, not UTC — see _holiday_range_dates (chaos audit 2026-06-02).
    start_date, end_date = _holiday_range_dates(start_dt, end_dt, tz_param)
    in_range = [
        h for h in all_raw
        if start_date <= datetime.strptime(h["date"], "%Y-%m-%d").date() < end_date
    ]

    return jsonify({"holidays": in_range, "timezone": tz_param, "country": country_code, "region": region_code})


# Cache for IP-based region detection (1 result per session, 6h TTL)
_detect_region_cache: dict = {}
_detect_region_lock = threading.Lock()
DETECT_REGION_TTL = 21600  # 6h


@calendar_routes_bp.route("/detect-region", methods=["GET"])
def detect_region():
    """
    Détecte la timezone précise de l'utilisateur via géolocalisation IP.

    Appelle ip-api.com depuis la machine locale (même IP publique que l'utilisateur).
    Retourne la timezone IANA précise (ex: America/Montreal pour Québec).
    Sans paramètre — pas d'auth requise.
    """
    with _detect_region_lock:
        cached = _detect_region_cache.get("result")
        if cached and (_cache_time.time() - cached["ts"]) < DETECT_REGION_TTL:
            return jsonify(cached["data"])

    try:
        # HTTPS so ISPs can't MITM the geoip response and inject a wrong
        # holiday set (audit Calendar-LOW-9 "ip-api.com over HTTP").
        url = "https://ip-api.com/json?fields=status,timezone,country,countryCode,region,regionName,city"
        req = urllib.request.Request(url, headers={"User-Agent": "Agentys/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())

        if data.get("status") == "success":
            result = {
                "detected": True,
                "timezone": data.get("timezone"),
                "country": data.get("countryCode"),
                "region": data.get("region"),
                "regionName": data.get("regionName"),
                "city": data.get("city"),
            }
            with _detect_region_lock:
                _detect_region_cache["result"] = {"data": result, "ts": _cache_time.time()}
            return jsonify(result)
    except Exception as e:
        logger.debug(f"[detect-region] ip-api.com failed: {e}")

    return jsonify({"detected": False, "timezone": None})


@calendar_routes_bp.route("/today", methods=["GET"])
def get_today_events():
    """
    Raccourci pour récupérer les événements du jour.

    Query params:
        account_id: ID du compte (optionnel)

    Returns:
        Liste des événements d'aujourd'hui.
    ---
    tags:
      - Calendar
    summary: Événements du jour
    """
    account_id = _resolve_account_id(request.args.get("account_id"))

    if not account_id:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return jsonify(_empty_passive_calendar_payload(
            None,
            "Calendar requires a Gmail or Outlook account connected via OAuth",
            needs_reauth=False,
            date=today.strftime("%Y-%m-%d"),
        ))

    try:
        provider = create_calendar_provider(account_id)
        if not provider:
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            return jsonify(_empty_passive_calendar_payload(
                account_id,
                "Calendar is unavailable for this account",
                date=today.strftime("%Y-%m-%d"),
            ))

        events = provider.get_today_events()
        serialized = [_serialize_event(event) for event in events]

        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        return jsonify({
            "events": serialized,
            "count": len(serialized),
            "date": today.strftime("%Y-%m-%d"),
            "account_id": account_id,
        })

    except CalendarScopeError as e:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return jsonify(_empty_passive_calendar_payload(
            account_id,
            str(e),
            provider=e.provider,
            date=today.strftime("%Y-%m-%d"),
        ))
    except Exception as e:
        logger.error(f"Error fetching today's events: {e}")
        return jsonify({
            "error": "Failed to fetch today's events",
            "message": str(e),
            "events": [],
        }), 500


@calendar_routes_bp.route("/upcoming", methods=["GET"])
def get_upcoming_events():
    """
    Raccourci pour récupérer les événements à venir.

    Query params:
        hours: Nombre d'heures à considérer (défaut: 24)
        limit: Nombre max d'événements (défaut: 10)
        account_id: ID du compte (optionnel)

    Returns:
        Liste des prochains événements.
    ---
    tags:
      - Calendar
    summary: Prochains événements
    """
    account_id = _resolve_account_id(request.args.get("account_id"))
    try:
        hours = min(int(request.args.get("hours", 24)), 168)  # Max 1 week
    except (ValueError, TypeError):
        hours = 24
    try:
        limit = min(int(request.args.get("limit", 10)), 50)
    except (ValueError, TypeError):
        limit = 10

    if not account_id:
        return jsonify(_empty_passive_calendar_payload(
            None,
            "Calendar requires a Gmail or Outlook account connected via OAuth",
            needs_reauth=False,
            hours=hours,
        ))

    # Serve from cache when fresh — avoids a ~600ms external API call on every tick
    _up_key = (str(account_id), hours, limit)
    with _upcoming_events_cache_lock:
        _up_entry = _upcoming_events_cache.get(_up_key)
        if _up_entry and (_cache_time.time() - _up_entry["timestamp"]) < UPCOMING_CACHE_TTL_SECONDS:
            return jsonify(_up_entry["data"])

    try:
        provider = create_calendar_provider(account_id)
        if not provider:
            return jsonify(_empty_passive_calendar_payload(
                account_id,
                "Calendar is unavailable for this account",
                hours=hours,
            ))

        events = provider.get_upcoming_events(hours=hours, max_results=limit)
        serialized = [_serialize_event(event) for event in events]

        payload = {
            "events": serialized,
            "count": len(serialized),
            "hours": hours,
            "account_id": account_id,
        }
        with _upcoming_events_cache_lock:
            _upcoming_events_cache[_up_key] = {"data": payload, "timestamp": _cache_time.time()}
            # Keep cache bounded
            if len(_upcoming_events_cache) > 10:
                oldest = min(_upcoming_events_cache, key=lambda k: _upcoming_events_cache[k]["timestamp"])
                del _upcoming_events_cache[oldest]

        return jsonify(payload)

    except CalendarScopeError as e:
        return jsonify(_empty_passive_calendar_payload(
            account_id,
            str(e),
            provider=e.provider,
            hours=hours,
        ))
    except Exception as e:
        logger.error(f"Error fetching upcoming events: {e}")
        return jsonify({
            "error": "Failed to fetch upcoming events",
            "message": str(e),
            "events": [],
        }), 500


# ============================================================================
# WRITE ROUTES — create, update, delete
# ============================================================================

def _parse_event_body(data: dict, event_id: str = "") -> DomainCalendarEvent:
    """Construit un DomainCalendarEvent depuis le body JSON de la requête."""
    start_str = data.get("start_time") or data.get("start")
    end_str   = data.get("end_time")   or data.get("end")
    if not start_str or not end_str:
        raise ValueError("start_time et end_time sont obligatoires")

    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
    end_dt   = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

    return DomainCalendarEvent(
        id=event_id or str(uuid.uuid4()),
        title=data.get("title", "Événement"),
        description=data.get("description", ""),
        start_time=start_dt,
        end_time=end_dt,
        all_day=bool(data.get("all_day", False)),
        location=data.get("location", ""),
        calendar_id=data.get("calendar_id", "primary"),
        # None (key absent) = "leave attendees untouched" — a drag/resize PATCH
        # omits this field and must NOT wipe the guest list. An explicit [] from
        # the edit form = "clear all attendees". See _build_event_body.
        attendees=data.get("attendees"),
        # Same None-vs-omitted contract as attendees: on UPDATE (event_id set) an
        # omitted "reminders" defaults to None so the builder leaves the provider's
        # existing reminders untouched — a drag/resize PATCH sends no reminders and
        # must NOT silently reset them to a single 30-min popup. On CREATE (no
        # event_id) default to [30]. An explicit [] still clears them.
        reminders=data.get("reminders", None if event_id else [30]),
        recurrence=data.get("recurrence"),
        conference=bool(data.get("conference", False)),
        color=data.get("color_id"),
    )


@calendar_routes_bp.route("/events", methods=["POST"])
def create_event():
    """
    Crée un nouvel événement dans le calendrier.

    Body JSON:
        title: Titre de l'événement
        start_time: ISO 8601 (ex: 2026-02-22T00:00:00)
        end_time: ISO 8601
        all_day: bool (optionnel)
        description: str (optionnel)
        calendar_id: str (optionnel, défaut: primary)

    Returns:
        {"success": true, "event_id": "<event_id>"}
    ---
    tags:
      - Calendar
    summary: Créer un événement
    """
    data = request.get_json(silent=True) or {}
    account_id = _resolve_account_id(request.args.get("account_id") or data.get("account_id"))
    if not account_id:
        return jsonify({"error": "No OAuth account found"}), 400

    try:
        event = _parse_event_body(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    calendar_id = data.get("calendar_id", "primary")

    try:
        provider = create_calendar_provider(account_id)
        if not provider:
            return jsonify({"error": "Calendar not supported"}), 400

        # Dedup: if an event with the same title+start already exists, return its ID instead
        # of creating a duplicate. Prevents React StrictMode double-mount duplicates.
        if event.title:
            try:
                existing = provider.get_events(event.start_time, event.end_time, calendar_id)
                for ex in existing:
                    ex_title = ex.title if hasattr(ex, 'title') else ex.get('title', '')
                    ex_id = ex.id if hasattr(ex, 'id') else ex.get('id', '')
                    if not ex_id or ex_title != event.title:
                        continue
                    ex_all_day = ex.all_day if hasattr(ex, 'all_day') else (
                        ex.is_all_day if hasattr(ex, 'is_all_day') else ex.get('isAllDay', False))
                    # All-day event: title + all-day flag is enough
                    if event.all_day and ex_all_day:
                        _invalidate_account_calendar_cache(account_id)
                        dedup_resp: dict = {"success": True, "event_id": ex_id}
                        ex_meet = getattr(ex, 'meet_link', None)
                        if ex_meet:
                            dedup_resp["meet_link"] = ex_meet
                        return jsonify(dedup_resp), 200
                    # Timed event: match on title + start time (within 60s tolerance)
                    if not event.all_day and not ex_all_day:
                        # CalendarEvent from interfaces uses `start`, domain entity uses `start_time`
                        ex_start = getattr(ex, 'start', None) or getattr(ex, 'start_time', None)
                        if ex_start and hasattr(event.start_time, 'timestamp') and hasattr(ex_start, 'timestamp'):
                            if abs((event.start_time - ex_start).total_seconds()) < 60:
                                _invalidate_account_calendar_cache(account_id)
                                dedup_resp2: dict = {"success": True, "event_id": ex_id}
                                ex_meet2 = getattr(ex, 'meet_link', None)
                                if ex_meet2:
                                    dedup_resp2["meet_link"] = ex_meet2
                                return jsonify(dedup_resp2), 200
            except Exception as _dedup_err:
                # Best-effort dedup — log so silent failures show up, but
                # don't block creation (audit Calendar-MEDIUM-6).
                logger.warning(
                    f"Calendar dedup pre-fetch failed (falling through to create): {_dedup_err}"
                )

        created_result = provider.create_event(event, calendar_id)
        if not created_result:
            return jsonify({"error": "Failed to create event"}), 500

        # create_event returns {"event_id": ..., "meet_link": ...} (dict)
        # or a plain string event_id (legacy adapters).
        if isinstance(created_result, dict):
            created_id = created_result.get("event_id")
            meet_link = created_result.get("meet_link")
        else:
            created_id = created_result
            meet_link = getattr(provider, "_last_meet_link", None)

        if not created_id:
            return jsonify({"error": "Failed to create event"}), 500

        _invalidate_account_calendar_cache(account_id)
        response_data: dict = {"success": True, "event_id": created_id}
        if meet_link:
            response_data["meet_link"] = meet_link
        return jsonify(response_data), 201

    except CalendarScopeError as e:
        return _make_scope_error_response(e)
    except Exception as e:
        logger.error(f"Error creating calendar event: {e}", exc_info=True)
        return jsonify({"error": "Failed to create event", "message": str(e)}), 500


@calendar_routes_bp.route("/events/<event_id>", methods=["PATCH"])
def update_event(event_id: str):
    """
    Met à jour un événement existant.

    Path params:
        event_id: ID de l'événement à modifier

    Body JSON: mêmes champs que POST /events

    Returns:
        {"ok": true}
    ---
    tags:
      - Calendar
    summary: Mettre à jour un événement
    """
    data = request.get_json(silent=True) or {}
    account_id = _resolve_account_id(request.args.get("account_id") or data.get("account_id"))
    if not account_id:
        return jsonify({"error": "No OAuth account found"}), 400

    try:
        event = _parse_event_body(data, event_id=event_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    calendar_id = data.get("calendar_id", "primary")

    try:
        provider = create_calendar_provider(account_id)
        if not provider:
            return jsonify({"error": "Calendar not supported"}), 400

        ok = provider.update_event(event, calendar_id)
        if not ok:
            return jsonify({"error": "Event not found or update failed"}), 404

        _invalidate_account_calendar_cache(account_id)
        return jsonify({"success": True})

    except CalendarEventPermissionError as e:
        return _make_event_forbidden_response(e)
    except CalendarScopeError as e:
        return _make_scope_error_response(e)
    except Exception as e:
        logger.error(f"Error updating calendar event {event_id}: {e}")
        return jsonify({"error": "Failed to update event", "message": str(e)}), 500


@calendar_routes_bp.route("/events/<event_id>", methods=["DELETE"])
def delete_event(event_id: str):
    """
    Supprime un événement du calendrier.

    Path params:
        event_id: ID de l'événement à supprimer

    Query params:
        calendar_id: ID du calendrier (défaut: primary)

    Returns:
        {"ok": true}
    ---
    tags:
      - Calendar
    summary: Supprimer un événement
    """
    data = request.get_json(silent=True) or {}
    account_id = _resolve_account_id(request.args.get("account_id") or data.get("account_id"))
    if not account_id:
        return jsonify({"error": "No OAuth account found"}), 400

    calendar_id = request.args.get("calendar_id") or data.get("calendar_id") or "primary"

    try:
        provider = create_calendar_provider(account_id)
        if not provider:
            return jsonify({"error": "Calendar not supported"}), 400

        ok = provider.delete_event(event_id, calendar_id)
        if not ok:
            return jsonify({"error": "Event not found or delete failed"}), 404

        _invalidate_account_calendar_cache(account_id)
        return jsonify({"success": True})

    except CalendarScopeError as e:
        return _make_scope_error_response(e)
    except Exception as e:
        logger.error(f"Error deleting calendar event {event_id}: {e}")
        return jsonify({"error": "Failed to delete event", "message": str(e)}), 500


@calendar_routes_bp.route("/rsvp", methods=["POST"])
def rsvp_meeting():
    """RSVP to a meeting invitation from an email.

    Body (JSON):
        email_id: Gmail or Outlook message ID
        response: 'accepted' | 'declined' | 'tentative'
        account_id: (optional) OAuth account ID

    Returns:
        {"ok": true, "event_id": "...", "response": "accepted"}
    ---
    tags:
      - Calendar
    summary: RSVP à une invitation de réunion
    """
    data = request.get_json(silent=True) or {}
    email_id = (data.get("email_id") or "").strip()
    response = (data.get("response") or "").strip().lower()
    account_id = _resolve_account_id(data.get("account_id"))

    if not email_id:
        return jsonify({"error": "email_id required"}), 400
    if response not in ("accepted", "declined", "tentative"):
        return jsonify({"error": "response must be accepted, declined, or tentative"}), 400
    if not account_id:
        return jsonify({"error": "No OAuth account found"}), 400

    try:
        provider = create_calendar_provider(account_id)
        if not provider or not hasattr(provider, "rsvp_event"):
            return jsonify({"error": "Calendar RSVP not supported for this provider"}), 400

        result = provider.rsvp_event(email_id, response)
        if not result.get("ok"):
            error = result.get("error", "unknown")
            if error == "no_ical_uid":
                return jsonify({"error": "Not a calendar invitation email"}), 422
            if error == "event_not_found":
                return jsonify({"error": "Calendar event not found"}), 404
            return jsonify({"error": error}), 500

        _invalidate_account_calendar_cache(account_id)

        # Post-RSVP relabel: an invitation that's now accepted/declined is
        # no longer actionable → demote default label from Action → Noise.
        # Mirrors the Quick Step rsvp_meeting handler. Best-effort: the
        # RSVP already succeeded, label drift never fails the response.
        # Bridge OAuth account_id → int DB account_id via the emails table.
        try:
            from app.quicksteps.handlers.rsvp import (
                relabel_invitation_as_noise_after_rsvp,
            )
            from app.db.database import get_db_session
            from sqlalchemy import text as _sql_text
            int_account_id: int | None = None
            with get_db_session() as _sess:
                row = _sess.execute(
                    _sql_text(
                        "SELECT account_id FROM emails WHERE email_id = :eid LIMIT 1"
                    ),
                    {"eid": email_id},
                ).scalar()
                if row is not None:
                    int_account_id = int(row)
            relabel_invitation_as_noise_after_rsvp(email_id, int_account_id, response)
        except Exception as _relabel_exc:  # noqa: BLE001
            logger.debug(
                "post-rsvp relabel (HTTP route) suppressed: %s", _relabel_exc
            )

        return jsonify({"ok": True, "event_id": result.get("event_id"), "response": response})

    except CalendarScopeError as e:
        return _make_scope_error_response(e)
    except Exception as e:
        logger.error(f"RSVP error for email {email_id}: {e}")
        return jsonify({"error": "RSVP failed", "message": str(e)}), 500
