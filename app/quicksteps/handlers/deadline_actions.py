# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Deadline-driven Quick Step actions: ``create_reminder`` +
``create_calendar_event``.

Both fire from a ``firesOn="received"`` rule (typically gated by the
``has_deadline_detected`` trigger) and schedule something ``days_before``
the deadline the ingest pipeline stamped on the email
(``emails.deadline_at`` — see :mod:`app.quicksteps.deadline_extractor`).

Deadline resolution is layered so the action works regardless of how the
engine loaded ``ctx.email`` (a SQL ``Email`` row carries the column; a
provider object usually doesn't):

  1. ``ctx.email.deadline_at`` attribute (SQL row).
  2. Authoritative ingest-stamped value, fetched by ``(email_id, account_id)``
     — mirrors the ``_EmailSnapshot`` backfill in ``auto_trigger``.
  3. A live ``extract_deadline`` pass on subject + body (covers provider
     objects, older rows ingested before deadline stamping, and manual runs).

Neither action sends mail. ``create_reminder`` is fully local
(reminder_service); ``create_calendar_event`` writes one event to the
connected calendar via the same OAuth bridge ``handlers/rsvp.py`` uses.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Deadline resolution + timing
# --------------------------------------------------------------------------- #

def _aware_utc(dt: datetime) -> datetime:
    """Normalise a (possibly naive) datetime to timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_deadline_at(ctx: ExecutionContext) -> datetime | None:
    """Return the email's deadline as UTC-aware datetime, or None.

    Layered lookup (attribute → SQL column → live extraction) so the action
    is robust to the shape of ``ctx.email``. Every fallback is best-effort:
    a DB hiccup degrades to the next source rather than failing the action.
    """
    # 1. Attribute on the loaded object (SQL Email row exposes the column).
    dl = getattr(ctx.email, "deadline_at", None)
    if isinstance(dl, datetime):
        return _aware_utc(dl)

    # 2. Authoritative ingest-stamped value, keyed by provider id + account.
    #    Use the provider id (raw_id / email_id), NOT the int PK — the column
    #    is keyed on the provider's `email_id` string (cf. lessons.md 3738:
    #    passing the int PK to provider lookups yields email_fetch_failed).
    raw_id = ctx.raw_id or ctx.email_id or ""
    if raw_id and ctx.account_id and ctx.account_id > 0:
        try:
            from app.db.database import get_db_session
            from app.db.models.email import Email as _EmailModel
            with get_db_session() as session:
                row = (
                    session.query(_EmailModel.deadline_at)
                    .filter(
                        _EmailModel.account_id == ctx.account_id,
                        _EmailModel.email_id == raw_id,
                    )
                    .limit(1)
                    .first()
                )
            if row and isinstance(row[0], datetime):
                return _aware_utc(row[0])
        except Exception as exc:  # noqa: BLE001
            logger.debug("deadline SQL lookup failed for %s: %s", raw_id, exc)

    # 3. Live extraction fallback (provider objects, pre-stamping rows, manual).
    try:
        from app.quicksteps.deadline_extractor import extract_deadline
        body = (
            getattr(ctx.email, "body", "")
            or getattr(ctx.email, "body_html", "")
            or getattr(ctx.email, "body_text", "")
            or ""
        )
        subject = getattr(ctx.email, "subject", "") or ""
        # Pass account_id so relative tokens ("tomorrow"/EOD) resolve against the
        # user's local day, not UTC (chaos audit 2026-06-02).
        return extract_deadline(body=body, subject=subject, account_id=ctx.account_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("extract_deadline fallback failed: %s", exc)
        return None


def _compute_fire_at(deadline_at: datetime, days_before: int) -> datetime:
    """Fire time = ``days_before`` days before the deadline, clamped to ``now``.

    A deadline closer than ``days_before`` (or already past) would otherwise
    produce a fire time in the past that no consumer surfaces — clamp it to
    now so the user still gets the reminder/event immediately."""
    fire_at = deadline_at - timedelta(days=days_before)
    now = datetime.now(timezone.utc)
    return fire_at if fire_at > now else now


# --------------------------------------------------------------------------- #
# create_reminder
# --------------------------------------------------------------------------- #

def handle_create_reminder(ctx: ExecutionContext, payload: dict) -> ActionResult:
    """Schedule a local reminder ``days_before`` the detected deadline.

    Non-destructive: no provider write. Goes through ``reminder_service``
    with ``reminder_type="deadline"`` so it surfaces both as a desktop toast
    (``check_and_notify``) and in the reminders list / Later view
    (``get_all_pending`` is type-agnostic).

    ``reminder_service.add_reminder`` de-dupes on ``(email_id, account_id)``,
    so re-running this action on the same email replaces the reminder in
    place rather than stacking duplicates (idempotent).
    """
    days_before = int(payload.get("days_before", 2))

    deadline = _resolve_deadline_at(ctx)
    if deadline is None:
        return ActionResult(ok=False, error="no_deadline_detected")
    # A deadline already in the past would make `_compute_fire_at` clamp to
    # "now" and fire immediately on a stale date (e.g. a sender writing
    # "was due last month"). Skip instead — there is nothing to remind about.
    if deadline <= datetime.now(timezone.utc):
        return ActionResult(ok=False, error="deadline_in_past")

    fire_at = _compute_fire_at(deadline, days_before)
    subject = getattr(ctx.email, "subject", "") or "(sans objet)"
    email_id = ctx.email_id or ctx.raw_id or ""

    try:
        from app.services.reminder_service import add_reminder
        reminder_id = add_reminder(
            email_id=email_id,
            subject=subject,
            reminder_date_iso=fire_at.isoformat(),
            account_id=ctx.account_id if ctx.account_id and ctx.account_id > 0 else None,
            reminder_type="deadline",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("create_reminder: add_reminder failed: %s", exc)
        return ActionResult(ok=False, error=f"reminder_error: {exc}")

    return ActionResult(ok=True, artifact={
        "reminder_id": reminder_id,
        "fire_at": fire_at.isoformat(),
        "deadline_at": deadline.isoformat(),
        "days_before": days_before,
    })


# --------------------------------------------------------------------------- #
# create_calendar_event
# --------------------------------------------------------------------------- #

def _resolve_calendar(ctx: ExecutionContext):
    """Resolve a calendar provider via the OAuth-id bridge.

    Returns ``(provider, None)`` on success or ``(None, error_code)``.
    Mirrors ``handlers/rsvp.py``: the int DB account id is bridged to the
    hex multi-accounts id via the account email, so background-thread
    auto-triggers reach the same calendar the UI does.
    """
    if not ctx.account_email:
        logger.warning(
            "create_calendar_event: no account email for DB id %s", ctx.account_id
        )
        return None, "calendar_account_unresolved"
    try:
        from app.multi_accounts import get_account_manager
        cfg = get_account_manager().get_account_by_email(ctx.account_email)
    except Exception as exc:  # noqa: BLE001
        logger.warning("create_calendar_event: account lookup failed: %s", exc)
        return None, "calendar_account_unresolved"
    oauth_account_id = getattr(cfg, "id", None) if cfg else None
    if not oauth_account_id:
        logger.warning(
            "create_calendar_event: no OAuth account for %s (re-auth?)",
            ctx.account_email,
        )
        return None, "calendar_account_unresolved"
    try:
        from app.providers.calendar_factory import create_calendar_provider
        cal = create_calendar_provider(oauth_account_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("create_calendar_event: provider unavailable: %s", exc)
        return None, "calendar_not_supported"
    if not cal or not hasattr(cal, "create_event"):
        return None, "calendar_not_supported"
    return cal, None


def handle_create_calendar_event(ctx: ExecutionContext, payload: dict) -> ActionResult:
    """Create one calendar event ``days_before`` the detected deadline.

    The event is a ``duration_minutes``-long block at the computed time,
    titled with a clock marker + the email subject (language-neutral so we
    don't bake a locale into a background-thread write). Requires calendar
    write scope; a missing scope surfaces as the provider's error rather
    than crashing the chain.
    """
    days_before = int(payload.get("days_before", 2))
    duration_minutes = int(payload.get("duration_minutes", 30))

    deadline = _resolve_deadline_at(ctx)
    if deadline is None:
        return ActionResult(ok=False, error="no_deadline_detected")
    # A deadline already in the past would make `_compute_fire_at` clamp to
    # "now" and fire immediately on a stale date (e.g. a sender writing
    # "was due last month"). Skip instead — there is nothing to remind about.
    if deadline <= datetime.now(timezone.utc):
        return ActionResult(ok=False, error="deadline_in_past")

    cal, error = _resolve_calendar(ctx)
    if cal is None:
        return ActionResult(ok=False, error=error)

    start = _compute_fire_at(deadline, days_before)
    end = start + timedelta(minutes=duration_minutes)
    subject = getattr(ctx.email, "subject", "") or "(sans objet)"
    # The subject is attacker-controlled (inbound email) and uncapped on our
    # side (Email.subject is 1000 chars). Cap it so the event title stays sane
    # and well under the provider's summary limit.
    title = f"⏰ {subject}"[:140]

    try:
        from app.interfaces.calendar_provider import CalendarEvent
        event = CalendarEvent(
            id="",
            title=title,
            start=start,
            end=end,
            description=f"Agentys Quick Step · deadline {deadline.date().isoformat()}",
        )
        result = cal.create_event(event)
    except Exception as exc:  # noqa: BLE001
        logger.error("create_calendar_event: create_event raised: %s", exc)
        return ActionResult(ok=False, error=f"calendar_event_error: {exc}")

    if not result or not result.get("event_id"):
        return ActionResult(ok=False, error="calendar_event_failed")

    return ActionResult(ok=True, artifact={
        "event_id": result.get("event_id"),
        "start": start.isoformat(),
        "deadline_at": deadline.isoformat(),
        "days_before": days_before,
    })
