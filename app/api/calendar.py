# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
API REST pour le calendrier et les follow-ups (Issue #26).

Endpoints:
- GET /api/calendar/events - Liste les événements du calendrier
- POST /api/calendar/events - Crée un événement
- PATCH /api/calendar/events/<id> - Met à jour un événement
- DELETE /api/calendar/events/<id> - Supprime un événement
- GET /api/calendar/calendars - Liste les calendriers disponibles

- GET /api/followups - Liste les follow-ups
- POST /api/followups - Crée un follow-up lié à un email
- PATCH /api/followups/<id> - Met à jour un follow-up (reporter, compléter)
- DELETE /api/followups/<id> - Supprime un follow-up
- GET /api/followups/<id>/email - Récupère l'email associé
"""

import os
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from flask import Blueprint, request, jsonify
from threading import Lock

from app.multi_accounts import get_account_manager, ProviderType
from app.api._auth_helpers import get_auth_user_id, check_account_ownership
from app.domain.entities import (
    CalendarEvent,
    CalendarEventType,
)

logger = logging.getLogger(__name__)

calendar_bp = Blueprint("calendar", __name__)

# =============================================================================
# Follow-up Storage — table ``followups`` via app.services.followup_store
# (migration 041, chantier « web tier stateless »). Le lock ne protège plus
# un dict mémoire mais sérialise les séquences read-modify-write des routes
# (PATCH/DELETE) dans ce process, comme avant.
# =============================================================================

from app.services import followup_store as _fu_store

_followups_lock = Lock()


def _coerce_aware_dt(value: str) -> datetime:
    """Parse an ISO-8601 string into a tz-aware datetime, coercing naive
    inputs to UTC (audit Calendar-MEDIUM-7 "naive vs tz-aware crash")."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# NB : plus de chargement à l'import — la table ``followups`` est la source
# de vérité ; l'import du JSON legacy est paresseux (followup_store).


# =============================================================================
# Helper Functions
# =============================================================================


def _get_calendar_adapter(account_id: str):
    """
    Get the appropriate calendar adapter for an account.

    Args:
        account_id: The account ID.

    Returns:
        Calendar adapter instance or None.
    """
    try:
        manager = get_account_manager()
        account = manager.get_account(account_id)

        if not account:
            logger.error(f"Account not found: {account_id}")
            return None

        # Convert string provider to enum if needed
        provider = account.provider
        if isinstance(provider, str):
            try:
                provider = ProviderType(provider)
            except ValueError:
                logger.error(f"Invalid provider type: {provider}")
                return None

        if provider == ProviderType.GMAIL:
            from app.providers.google_calendar_adapter import GoogleCalendarAdapter
            adapter = GoogleCalendarAdapter(
                account_id=account_id,
                client_id=os.getenv("GOOGLE_CLIENT_ID"),
                client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            )
        elif provider == ProviderType.OUTLOOK:
            from app.providers.outlook_calendar_adapter import OutlookCalendarAdapter
            adapter = OutlookCalendarAdapter(account_id=account_id)
        else:
            logger.error(f"Unsupported provider for calendar: {provider}")
            return None

        try:
            if adapter.authenticate():
                return adapter
            logger.error(f"Calendar authentication failed for {account_id}")
            return None
        except Exception as _auth_err:
            # SEC-007: distinguish token-expired (401) from generic failure.
            from app.providers.google_calendar_adapter import CalendarAuthExpiredError
            if isinstance(_auth_err, CalendarAuthExpiredError):
                raise
            logger.error(f"Calendar authentication error for {account_id}: {_auth_err}")
            return None

    except Exception as e:
        logger.error(f"Error getting calendar adapter: {e}")
        return None


def _validate_account_ownership(account_id: Optional[str]) -> Optional[str]:
    """Validate that account_id belongs to the authenticated user.

    Returns the account_id if ownership is confirmed, None otherwise.
    """
    if not account_id:
        return None
    try:
        manager = get_account_manager()
        account = manager.get_account(account_id)
        auth_user_id = get_auth_user_id()
        if account and check_account_ownership(account, auth_user_id):
            return account_id
        return None
    except Exception as e:
        logger.error(f"Error validating account ownership for {account_id}: {e}")
        return None


def _get_current_account_id() -> Optional[str]:
    """Get the current account ID for the authenticated user."""
    try:
        manager = get_account_manager()
        auth_user_id = get_auth_user_id()
        current_id = manager.get_current_for_user(auth_user_id)
        if current_id:
            account = manager.get_account(current_id)
            if account and check_account_ownership(account, auth_user_id):
                return current_id
        return None
    except Exception as e:
        logger.error(f"Error getting current account: {e}")
        return None


# =============================================================================
# Calendar Events Endpoints
# =============================================================================


# GET/POST/PATCH/DELETE /events are handled by calendar_routes_bp (camelCase serialization + dedup)


@calendar_bp.route("/freebusy", methods=["POST"])
def get_freebusy():
    """
    Recherche les créneaux libres pour les participants.
    ---
    tags:
      - Calendar
    summary: FreeBusy + Smart Scheduler
    """
    from app.services.smart_scheduler import find_available_slots

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    attendees = list(data.get("attendees", []))

    raw_account_id = data.get("account_id")
    account_id = _validate_account_ownership(raw_account_id) if raw_account_id else _get_current_account_id()
    if not account_id:
        return jsonify({"error": "No account configured"}), 400

    # Note: the adapter handles the user's own calendar ("primary" for Google,
    # "me/" for Outlook), so we don't add the user email here to avoid duplicates.

    try:
        adapter = _get_calendar_adapter(account_id)
    except Exception as _ce:
        from app.providers.google_calendar_adapter import CalendarAuthExpiredError
        if isinstance(_ce, CalendarAuthExpiredError):
            # SEC-007: token expired → 401 so frontend can prompt re-auth.
            return jsonify({"error": "Calendar authentication expired", "reauth_required": True}), 401
        return jsonify({"error": "Calendar not available"}), 503
    if not adapter:
        return jsonify({"error": "Calendar not available"}), 503

    try:
        start = datetime.fromisoformat(data["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(data["end"].replace("Z", "+00:00"))
    except (KeyError, ValueError) as e:
        return jsonify({"error": f"Invalid date: {e}"}), 400

    # Audit 2026-05-11 P0/P1: /freebusy accepted negative / zero
    # duration_minutes (broken ICS invites with end<start) and inverted
    # date ranges (silent empty result, debugging nightmare). Validate at
    # the boundary.
    if end <= start:
        return jsonify({"error": "end must be strictly greater than start"}), 400

    raw_duration = data.get("duration_minutes", 60)
    try:
        duration_minutes = int(raw_duration)
    except (TypeError, ValueError):
        return jsonify({"error": "duration_minutes must be an integer"}), 400
    if not (1 <= duration_minutes <= 1440):
        return jsonify({"error": "duration_minutes must be between 1 and 1440"}), 400

    def _coerce_int(name: str, default: int, lo: int, hi: int) -> int | None:
        raw = data.get(name, default)
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return None
        return v if lo <= v <= hi else None

    work_hours_only = bool(data.get("work_hours_only", True))
    work_start = _coerce_int("work_start", 8, 0, 23)
    work_end = _coerce_int("work_end", 17, 1, 24)
    lunch_start = _coerce_int("lunch_start", 12, 0, 23)
    lunch_end = _coerce_int("lunch_end", 13, 1, 24)
    tz_offset_minutes = _coerce_int("tz_offset_minutes", 0, -14 * 60, 14 * 60)
    if None in (work_start, work_end, lunch_start, lunch_end, tz_offset_minutes):
        return jsonify({
            "error": "work_start/work_end/lunch_start/lunch_end out of range"
        }), 400
    if work_start >= work_end:
        return jsonify({"error": "work_start must be < work_end"}), 400
    if lunch_start >= lunch_end:
        return jsonify({"error": "lunch_start must be < lunch_end"}), 400

    # Cap attendees to avoid Microsoft Graph getSchedule's hard cap of 20
    # producing a silently-empty response (B-06). Outlook adapter chunks
    # internally now, but rejecting absurd requests at the boundary keeps
    # the surface honest.
    if len(attendees) > 200:
        return jsonify({"error": "too many attendees (max 200)"}), 400

    # Extra busy blocks (e.g. local Deep Work blocks from frontend)
    extra_busy = data.get("extra_busy", [])

    # Get freebusy data from provider
    logger.info(f"[FreeBusy] Querying freebusy for {len(attendees)} attendees: {attendees}")
    freebusy_data = adapter.get_freebusy(attendees, start, end)
    total_blocks = sum(len(blocks) for blocks in freebusy_data.get("calendars", {}).values())
    logger.info(f"[FreeBusy] Provider returned {total_blocks} busy blocks across {len(freebusy_data.get('calendars', {}))} calendars")
    if extra_busy:
        logger.info(f"[FreeBusy] Frontend sent {len(extra_busy)} extra busy blocks")

    # Find available slots
    slots = find_available_slots(
        freebusy_data=freebusy_data,
        start=start,
        end=end,
        duration_minutes=duration_minutes,
        work_hours_only=work_hours_only,
        work_start=work_start,
        work_end=work_end,
        lunch_start=lunch_start,
        lunch_end=lunch_end,
        tz_offset_minutes=tz_offset_minutes,
        extra_busy=extra_busy,
    )

    # Expose per-attendee busy blocks so the frontend timeline-grid view (the
    # Outlook scheduling-assistant equivalent) can render each attendee's
    # calendar as its own row. The adapter already collects this data —
    # previously discarded — now passed through with the original status
    # field (Outlook only; Google blocks land without status and the UI
    # defaults them to "busy").
    return jsonify({
        "slots": slots,
        "attendees": attendees,
        "duration_minutes": duration_minutes,
        "per_attendee_busy": freebusy_data.get("calendars", {}),
    })



# DELETE /events/<event_id> is handled by calendar_routes_bp (with proper cache invalidation)
# GET /calendars is handled by calendar_routes_bp (camelCase serialization for frontend)


# =============================================================================
# Follow-ups Endpoints
# =============================================================================


def _get_followups_as_events(account_id: str, start: datetime, end: datetime) -> list:
    """Convert follow-ups to calendar event format for display."""
    events = []
    for fid, fdata in _fu_store.records_for_account(account_id):
        if fdata.get("status") in ["completed", "cancelled"]:
            continue

        try:
            due_date = _coerce_aware_dt(fdata.get("due_date", ""))
        except (ValueError, AttributeError):
            # Malformed due_date — skip this entry, don't crash the whole list
            logger.warning(f"Skipping followup {fid} with invalid due_date: {fdata.get('due_date')}")
            continue
        if start <= due_date <= end:
            # Create a calendar event representation
            events.append({
                "id": f"followup_{fid}",
                "title": f"[FU] {fdata.get('title', 'Follow-up')}",
                "description": fdata.get("description", ""),
                "start_time": fdata.get("due_date"),
                "end_time": (due_date + timedelta(hours=1)).isoformat(),
                "all_day": False,
                "location": "",
                "attendees": [],
                "status": "confirmed",
                "event_type": "followup",
                "provider": "agentys",
                "email_id": fdata.get("email_id"),
                "email_subject": fdata.get("email_subject"),
                "email_sender": fdata.get("email_sender"),
                "is_overdue": due_date < datetime.now(timezone.utc),
                "color": "#FF6B35" if due_date < datetime.now(timezone.utc) else "#4A90D9",  # Orange if overdue
            })

    return events


def _wake_snoozed_followups():
    """Réactive les follow-ups snoozés dont la date est dépassée."""
    _fu_store.wake_snoozed()


@calendar_bp.route("/followups", methods=["GET"])
def list_followups():
    """
    Liste les follow-ups.

    Query params:
    - account_id: ID du compte
    - status: Filtrer par statut (pending, completed, snoozed, cancelled)
    - email_id: Filtrer par email associé
    ---
    tags:
      - Follow-ups
    summary: Liste les follow-ups
    """
    _wake_snoozed_followups()

    raw_account_id = request.args.get("account_id")
    account_id = _validate_account_ownership(raw_account_id) if raw_account_id else _get_current_account_id()
    status_filter = request.args.get("status")
    email_id_filter = request.args.get("email_id")

    followups = []
    if account_id:
        candidates = _fu_store.records_for_account(account_id)
    else:
        # No active account — only include followups we own (F3: exclude
        # orphans too). L'ownership se valide followup par followup.
        candidates = [
            (fid, fdata) for fid, fdata in _fu_store.all_records()
            if fdata.get("account_id") and _validate_account_ownership(fdata.get("account_id"))
        ]
    for fid, fdata in candidates:
        # Filter by status
        if status_filter and fdata.get("status") != status_filter:
            continue
        # Filter by email
        if email_id_filter and fdata.get("email_id") != email_id_filter:
            continue

        followups.append({"id": fid, **fdata})

    # Sort by due_date
    followups.sort(key=lambda f: f.get("due_date", ""))

    return jsonify({
        "count": len(followups),
        "followups": followups,
    })


@calendar_bp.route("/followups", methods=["POST"])
def create_followup():
    """
    Crée un follow-up lié à un email.
    ---
    tags:
      - Follow-ups
    summary: Crée un follow-up
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    # Validate required fields
    required = ["email_id", "title", "due_date"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400

    raw_account_id = data.get("account_id")
    account_id = _validate_account_ownership(raw_account_id) if raw_account_id else _get_current_account_id()
    if not account_id:
        return jsonify({"error": "No account configured"}), 400

    # Parse due_date
    try:
        due_date = datetime.fromisoformat(data["due_date"].replace("Z", "+00:00"))
    except ValueError as e:
        return jsonify({"error": f"Invalid date format: {e}"}), 400

    followup_id = str(uuid.uuid4())
    followup_data = {
        "email_id": data["email_id"],
        "account_id": account_id,
        "title": data["title"],
        "description": data.get("description", ""),
        "due_date": due_date.isoformat(),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "snoozed_until": None,
        "snooze_count": 0,
        "calendar_event_id": None,
        "sync_to_calendar": data.get("sync_to_calendar", False),
        "email_subject": data.get("email_subject", ""),
        "email_sender": data.get("email_sender", ""),
        "auto_created": data.get("auto_created", False),
        "ai_reason": data.get("ai_reason"),
    }

    _fu_store.save_record(followup_id, followup_data)

    # Optionally sync to calendar
    if data.get("sync_to_calendar"):
        _sync_followup_to_calendar(followup_id, followup_data, account_id)

    logger.info(f"Follow-up created: {followup_id} for email {data['email_id']}")

    return jsonify({
        "success": True,
        "id": followup_id,
        "followup": {"id": followup_id, **followup_data},
    }), 201


@calendar_bp.route("/followups/<followup_id>", methods=["PATCH"])
def update_followup(followup_id: str):
    """
    Met à jour un follow-up (reporter, compléter, etc).
    ---
    tags:
      - Follow-ups
    summary: Met à jour un follow-up
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    with _followups_lock:
        followup = _fu_store.get_record(followup_id)
        if followup is None:
            return jsonify({"error": "Follow-up not found"}), 404

        # Ownership check
        if not _validate_account_ownership(followup.get("account_id")):
            return jsonify({"error": "Access denied"}), 403

        # Handle special actions
        action = data.get("action")
        if action == "complete":
            followup["status"] = "completed"
            followup["completed_at"] = datetime.now(timezone.utc).isoformat()
        elif action == "snooze":
            new_due = data.get("snooze_until") or data.get("due_date")
            if not new_due:
                return jsonify({"error": "snooze_until is required for snooze action"}), 400
            # Audit F-09 (2026-05-16): mirror the validation the sibling
            # `due_date` branch does at L637-642. Without it, a garbage
            # string ("banana", "next tuesday", a truncated ISO) lands in
            # the row; `_wake_snoozed_followups` then ValueErrors, the
            # bare `except: pass` at L465-466 eats it, and the followup
            # stays stuck in `snoozed` forever with no UI recourse.
            try:
                datetime.fromisoformat(str(new_due).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid snooze_until format (must be ISO-8601)"}), 400
            followup["status"] = "snoozed"
            followup["snoozed_until"] = new_due
            followup["due_date"] = new_due
            followup["snooze_count"] = followup.get("snooze_count", 0) + 1
        elif action == "cancel":
            followup["status"] = "cancelled"
            followup["completed_at"] = datetime.now(timezone.utc).isoformat()
        elif action == "reopen":
            followup["status"] = "pending"
            followup["completed_at"] = None
        else:
            # Regular field updates
            if "title" in data:
                followup["title"] = data["title"]
            if "description" in data:
                followup["description"] = data["description"]
            if "due_date" in data:
                try:
                    datetime.fromisoformat(str(data["due_date"]).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    return jsonify({"error": "Invalid due_date format"}), 400
                followup["due_date"] = data["due_date"]
            if "status" in data:
                valid_statuses = {"pending", "completed", "cancelled", "snoozed"}
                if data["status"] not in valid_statuses:
                    return jsonify({"error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}), 400
                followup["status"] = data["status"]
            if "sync_to_calendar" in data:
                followup["sync_to_calendar"] = data["sync_to_calendar"]

        _fu_store.save_record(followup_id, followup)

    logger.info(f"Follow-up updated: {followup_id}")

    return jsonify({
        "success": True,
        "followup": {"id": followup_id, **followup},
    })


@calendar_bp.route("/followups/<followup_id>", methods=["DELETE"])
def delete_followup(followup_id: str):
    """
    Supprime un follow-up.
    ---
    tags:
      - Follow-ups
    summary: Supprime un follow-up
    """
    with _followups_lock:
        followup = _fu_store.get_record(followup_id)
        if followup is None:
            return jsonify({"error": "Follow-up not found"}), 404

        # Ownership check
        if not _validate_account_ownership(followup.get("account_id")):
            return jsonify({"error": "Access denied"}), 403

        # If synced to calendar, delete the calendar event
        if followup.get("calendar_event_id"):
            _delete_followup_from_calendar(followup, followup.get("account_id"))

        _fu_store.delete_record(followup_id)

    logger.info(f"Follow-up deleted: {followup_id}")

    return jsonify({
        "success": True,
        "message": "Follow-up deleted",
    })


@calendar_bp.route("/followups/<followup_id>/email", methods=["GET"])
def get_followup_email(followup_id: str):
    """
    Récupère l'email associé à un follow-up.
    ---
    tags:
      - Follow-ups
    summary: Récupère l'email associé
    """
    followup = _fu_store.get_record(followup_id)
    if followup is None:
        return jsonify({"error": "Follow-up not found"}), 404

    # Ownership check
    if not _validate_account_ownership(followup.get("account_id")):
        return jsonify({"error": "Access denied"}), 403

    email_id = followup.get("email_id")
    account_id = followup.get("account_id")

    if not email_id:
        return jsonify({"error": "No email associated with this follow-up"}), 404

    # Fetch the email from the provider
    try:
        from app.providers import get_pooled_provider

        provider = get_pooled_provider(account_id)
        if not provider:
            return jsonify({"error": "Email provider not available"}), 503

        email = provider.get_message_by_id(email_id)
        if not email:
            return jsonify({"error": "Email not found"}), 404

        return jsonify({
            "email": {
                "id": email.id,
                "subject": email.subject,
                "sender": email.sender,
                "sender_name": email.sender_name,
                "body": email.body,
                "body_html": email.body_html,
                "received_at": email.received_at.isoformat() if email.received_at else None,
                "is_read": email.is_read,
            },
            "followup_id": followup_id,
        })

    except Exception as e:
        logger.error(f"Error fetching email for followup: {e}")
        return jsonify({"error": "Failed to fetch email"}), 500


# =============================================================================
# Calendar Sync Helpers
# =============================================================================


def _sync_followup_to_calendar(followup_id: str, followup: dict, account_id: str):
    """Sync a follow-up to the user's calendar.

    Returns the created calendar event id on success, or ``None`` if no
    adapter is available or the sync failed (so callers can report the
    real sync status instead of assuming success).
    """
    try:
        adapter = _get_calendar_adapter(account_id)
        if not adapter:
            logger.warning(f"Cannot sync followup {followup_id}: no calendar adapter")
            return None

        due_date = datetime.fromisoformat(followup["due_date"].replace("Z", "+00:00"))

        event = CalendarEvent(
            id=f"agentys_followup_{followup_id}",
            title=f"[FU] {followup['title']}",
            description=f"Follow-up pour: {followup.get('email_subject', 'Email')}\n\n{followup.get('description', '')}",
            start_time=due_date,
            end_time=due_date + timedelta(hours=1),
            all_day=False,
            event_type=CalendarEventType.FOLLOWUP,
            email_id=followup.get("email_id"),
            reminders=[30, 60],  # 30 min and 1 hour before
        )

        event_id = adapter.create_event(event)

        if event_id:
            with _followups_lock:
                record = _fu_store.get_record(followup_id)
                if record is not None:
                    record["calendar_event_id"] = event_id
                    _fu_store.save_record(followup_id, record)
            logger.info(f"Follow-up {followup_id} synced to calendar as {event_id}")

        return event_id

    except Exception as e:
        logger.error(f"Failed to sync followup to calendar: {e}")
        return None


def _delete_followup_from_calendar(followup: dict, account_id: str):
    """Delete a follow-up event from the calendar."""
    try:
        event_id = followup.get("calendar_event_id")
        if not event_id:
            return

        adapter = _get_calendar_adapter(account_id)
        if adapter:
            adapter.delete_event(event_id)
            logger.info(f"Calendar event {event_id} deleted for followup")

    except Exception as e:
        logger.error(f"Failed to delete followup from calendar: {e}")


# =============================================================================
# AI Commitment Suggestions (Issue #26 — Follow-up Suggestions)
# =============================================================================

# Suggestions persistées dans la table ``calendar_suggestions`` (migration
# 042 — l'audit Calendar-HIGH-2 « suggestions in-memory only » est réglé
# structurellement). Le lock sérialise les read-modify-write in-process.
from app.services import calendar_suggestion_store as _sugg_store

_suggestions_lock = Lock()


def add_suggestion(
    email_id: str,
    account_id: str,
    description: str,
    deadline: Optional[str] = None,
    email_subject: str = "",
    email_sender: str = "",
    draft_body: str = "",
) -> str:
    """
    Store a new AI-detected commitment suggestion.

    Called from routes.py after CommitmentExtractorAgent runs on a sent draft.

    Returns:
        The suggestion ID.
    """
    suggestion_id = str(uuid.uuid4())
    suggestion = {
        "email_id": email_id,
        "account_id": account_id,
        "description": description,
        "deadline": deadline,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "email_subject": email_subject,
        "email_sender": email_sender,
        "draft_body_preview": draft_body[:200] if draft_body else "",
    }

    _sugg_store.save_record(suggestion_id, suggestion)

    logger.info(f"Commitment suggestion created: {suggestion_id}")
    return suggestion_id


@calendar_bp.route("/suggestions", methods=["GET"])
def list_suggestions():
    """
    List AI-detected commitment suggestions.

    Query params:
    - email_id: Filter by email (optional)
    - status: Filter by status (pending, accepted, rejected; default: all)
    ---
    tags:
      - Suggestions
    summary: Liste les suggestions de follow-up IA
    """
    email_id_filter = request.args.get("email_id")
    status_filter = request.args.get("status")

    results = []
    for sid, sdata in _sugg_store.all_records():
        # Ownership check — only show suggestions for accounts the user owns
        if not _validate_account_ownership(sdata.get("account_id")):
            continue
        if email_id_filter and sdata.get("email_id") != email_id_filter:
            continue
        if status_filter and sdata.get("status") != status_filter:
            continue
        results.append({"id": sid, **sdata})

    results.sort(key=lambda s: s.get("created_at", ""), reverse=True)

    return jsonify({
        "count": len(results),
        "suggestions": results,
    })


@calendar_bp.route("/suggestions/<suggestion_id>/accept", methods=["POST"])
def accept_suggestion(suggestion_id: str):
    """
    Accept a suggestion — creates a follow-up and optionally syncs to calendar.

    Request body (optional):
    - sync_to_calendar: bool (default false)
    - due_date: ISO 8601 override (default: suggestion deadline or +1 day)
    ---
    tags:
      - Suggestions
    summary: Accepter une suggestion de follow-up
    """
    with _suggestions_lock:
        suggestion = _sugg_store.get_record(suggestion_id)
        if suggestion is None:
            return jsonify({"error": "Suggestion not found"}), 404

        # Ownership check
        if not _validate_account_ownership(suggestion.get("account_id")):
            return jsonify({"error": "Access denied"}), 403

        if suggestion["status"] != "pending":
            return jsonify({"error": f"Suggestion already {suggestion['status']}"}), 400
        suggestion["status"] = "accepted"
        _sugg_store.save_record(suggestion_id, suggestion)

    data = request.get_json(silent=True) or {}
    sync_to_cal = data.get("sync_to_calendar", False)

    # Determine due date
    due_date_str = data.get("due_date") or suggestion.get("deadline")
    if due_date_str:
        try:
            due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
        except ValueError:
            due_date = datetime.now(timezone.utc) + timedelta(days=1)
    else:
        due_date = datetime.now(timezone.utc) + timedelta(days=1)

    # Create a real follow-up from this suggestion
    followup_id = str(uuid.uuid4())
    followup_data = {
        "email_id": suggestion.get("email_id", ""),
        "account_id": suggestion.get("account_id", ""),
        "title": suggestion.get("description", "Follow-up"),
        "description": f"Auto-détecté par IA: {suggestion.get('description', '')}",
        "due_date": due_date.isoformat(),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "snoozed_until": None,
        "snooze_count": 0,
        "calendar_event_id": None,
        "sync_to_calendar": sync_to_cal,
        "email_subject": suggestion.get("email_subject", ""),
        "email_sender": suggestion.get("email_sender", ""),
        "auto_created": True,
        "ai_reason": suggestion.get("description"),
    }

    _fu_store.save_record(followup_id, followup_data)

    # Optionally sync to calendar
    calendar_event_id = None
    if sync_to_cal:
        calendar_event_id = _sync_followup_to_calendar(
            followup_id, followup_data, suggestion.get("account_id", "")
        )

    logger.info(f"Suggestion {suggestion_id} accepted → followup {followup_id}")

    return jsonify({
        "success": True,
        "suggestion_id": suggestion_id,
        "followup_id": followup_id,
        "calendar_synced": bool(calendar_event_id),
        "calendar_event_id": calendar_event_id,
        "followup": {"id": followup_id, **followup_data},
    })


@calendar_bp.route("/suggestions/<suggestion_id>/reject", methods=["POST"])
def reject_suggestion(suggestion_id: str):
    """
    Reject/dismiss a suggestion.
    ---
    tags:
      - Suggestions
    summary: Rejeter une suggestion de follow-up
    """
    with _suggestions_lock:
        suggestion = _sugg_store.get_record(suggestion_id)
        if suggestion is None:
            return jsonify({"error": "Suggestion not found"}), 404

        # Ownership check
        if not _validate_account_ownership(suggestion.get("account_id")):
            return jsonify({"error": "Access denied"}), 403

        if suggestion["status"] != "pending":
            return jsonify({"error": f"Suggestion already {suggestion['status']}"}), 400
        suggestion["status"] = "rejected"
        _sugg_store.save_record(suggestion_id, suggestion)

    logger.info(f"Suggestion {suggestion_id} rejected")

    return jsonify({
        "success": True,
        "suggestion_id": suggestion_id,
    })
