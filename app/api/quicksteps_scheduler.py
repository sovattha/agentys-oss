# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Background scheduler + wake-engine for Quick Steps follow-ups.

This module owns the two Quick-Step plumbing concerns that survived the
retirement of the legacy ``auto_followup`` nudge loop:

  1. ``fire_sent_quicksteps_immediate(sent_email, account_id_or_oauth)``
     — fires ``firesOn="sent"`` rules synchronously at send completion.
     Called from the send/compose/reply HTTP handlers.

  2. ``run_quicksteps_scheduled(oauth_account_id, emails)`` — the
     background tick. Throttled per-account (5 min); runs the wake-time
     sweep for snoozed follow-up drafts.

No LLM calls anywhere in this module. The wake-time sweep + label apply
live in ``app/quicksteps/handlers/create_snoozed_followup_draft.py``.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Per-account throttle for the scheduler tick. 5 min is enough to absorb
# the cadence of inbox-open callers without overwhelming the DB. The
# underlying operations are idempotent + cheap-on-empty, so this is just
# insurance — not load-bearing for correctness.
_scheduler_last_run: dict[str, float] = {}
_SCHEDULER_MIN_INTERVAL = 300  # seconds
_scheduler_lock = threading.Lock()
_scheduler_running = False

# In-process dedup of (sent_email_id, step_id) firings for the sent-side
# Quick Step pass — both the immediate hook and the scheduler safety-net
# read/write here so the same rule doesn't fire twice on the same send.
# Memory-only: reminder_service de-dupes on (email_id, account_id), so
# survival across restarts is not required (worst case is a status bump
# on an existing reminder).
#
# Audit F-06 (2026-05-17 deep-audit): ``fire_sent_quicksteps_immediate``
# runs in HTTP-worker threads, so concurrent sends mutate this dict from
# several threads at once. Concurrent dict mutation during a
# ``list(...).items()`` iteration can raise ``RuntimeError: dictionary
# changed size during iteration`` and any miss in the dedup-check skews
# to a duplicate fire
# (mitigated downstream by reminder_service de-dup, but still produces
# duplicate ``quick_step_audit_log`` rows + extra Haiku calls). Wrap
# every access in this lock — dict ops are O(1) so the critical section
# is trivial.
_sent_quickstep_fired: dict[tuple[str, str], float] = {}
_sent_quickstep_fired_lock = threading.Lock()
_SENT_QUICKSTEP_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _prune_expired_sent_quickstep_fired(now: float | None = None) -> None:
    """Evict ``_sent_quickstep_fired`` entries older than the TTL budget.

    The map gains one entry per fired ``firesOn="sent"`` step and, before
    this prune, was never trimmed — it grew for the whole API-process
    lifetime (``_SENT_QUICKSTEP_TTL_SECONDS`` was defined but never
    enforced). ``fire_sent_quicksteps_immediate`` — the single sent-side
    entry point — calls this on every send, so the map stays bounded to
    ~7 days of recent firings.

    Eviction is safe: re-processing a >7-day-old send is not a real flow,
    and ``reminder_service`` de-dupes durably on ``(email_id, account_id)``,
    so a dropped mark can at worst bump an existing reminder's status — it
    cannot produce a duplicate action. Must be called WITHOUT holding
    ``_sent_quickstep_fired_lock`` (it acquires the lock itself).
    """
    cutoff = (time.time() if now is None else now) - _SENT_QUICKSTEP_TTL_SECONDS
    with _sent_quickstep_fired_lock:
        expired = [key for key, ts in _sent_quickstep_fired.items() if ts < cutoff]
        for key in expired:
            del _sent_quickstep_fired[key]


def _resolve_oauth_account_to_int(oauth_account_id: str) -> int | None:
    """Translate a hex multi-accounts manager id to the integer Account.id
    used by the settings table. Returns None when no matching DB row
    exists (e.g. account not yet persisted)."""
    try:
        from app.multi_accounts import get_account_manager
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
    except Exception:
        return None
    cfg = get_account_manager().get_account(oauth_account_id)
    if not cfg or not getattr(cfg, "email", None):
        return None
    with get_db_session() as session:
        row = AccountRepository(session).get_by_email(cfg.email)
        return int(row.id) if row else None


# ---------------------------------------------------------------------------
# 1. Immediate sent-side Quick Steps fire
# ---------------------------------------------------------------------------

def fire_sent_quicksteps_immediate(sent_email, account_id_or_oauth) -> None:
    """Fire ``firesOn="sent"`` Quick Step rules right after a send completes.

    This is the single entry point for sent-side rules. Calling it from the
    send-completion code path lets actions like
    ``create_snoozed_followup_draft`` surface their snoozed drafts in
    "Later" the moment the send returns 200.

    Best-effort: any exception is swallowed because the email has already
    been sent — failing the rule fire shouldn't break the send response.

    ``account_id_or_oauth`` accepts either an integer DB id (as ``str``
    or ``int``) or the hex multi-accounts manager id; we resolve to the
    int Account.id the engine needs.

    Records each fired step in the shared ``_sent_quickstep_fired`` map so a
    concurrent send (another HTTP worker) checking ``_already_fired`` sees
    the step as claimed and doesn't re-fire it.
    """
    try:
        account_id_int: int | None = None
        if isinstance(account_id_or_oauth, int):
            account_id_int = account_id_or_oauth
        elif isinstance(account_id_or_oauth, str) and account_id_or_oauth:
            if account_id_or_oauth.isdigit():
                account_id_int = int(account_id_or_oauth)
            else:
                account_id_int = _resolve_oauth_account_to_int(account_id_or_oauth)
        if not account_id_int or account_id_int <= 0:
            # Audit F-02 (2026-05-17 deep-audit): the previous silent `return`
            # made a hex account_id with no matching `Account` DB row look
            # like a working install — every `firesOn="sent"` Quick Step
            # would silently never fire and ops had no log line to trace it
            # back to a missing AccountRepository row. Warn loud enough that
            # the dead path is observable in prod.
            if isinstance(account_id_or_oauth, str) and not account_id_or_oauth.isdigit():
                logger.warning(
                    "[QS-SCHED] hex account_id %r did not resolve to a DB Account row; "
                    "sent-side Quick Steps will not fire for this send",
                    account_id_or_oauth,
                )
            return
        # Bound the in-process dedup map before doing work: evict firings
        # older than the TTL so it can't grow for the API-process lifetime.
        _prune_expired_sent_quickstep_fired()
        from app.quicksteps.auto_trigger import run_auto_triggers_on_sent
        sent_id = getattr(sent_email, "id", "") or ""

        def _already_fired_locked(step_id, _sid=sent_id):
            with _sent_quickstep_fired_lock:
                return (_sid, step_id) in _sent_quickstep_fired

        already_fired = _already_fired_locked if sent_id else None

        def _mark_fired_locked(step_id, _sid=sent_id):
            if not _sid or not step_id:
                return
            with _sent_quickstep_fired_lock:
                _sent_quickstep_fired[(_sid, step_id)] = time.time()

        mark_fired = _mark_fired_locked if sent_id else None
        try:
            fired_step_ids = run_auto_triggers_on_sent(
                account_id_int,
                sent_email,
                _already_fired=already_fired,
                _mark_fired=mark_fired,
            )
        except TypeError:
            # auto_trigger built without the dedup hook — accept the
            # fire-without-check; reminder_service de-dupes on
            # (email_id, account_id) so the worst case is a status bump,
            # not a duplicate reminder.
            fired_step_ids = run_auto_triggers_on_sent(account_id_int, sent_email)
        # Safety-net: re-mark on return in case _mark_fired wasn't honored
        # (older auto_trigger fallback path). Inline marking is the primary
        # defense against the immediate-vs-scheduler race.
        if sent_id and fired_step_ids:
            now = time.time()
            with _sent_quickstep_fired_lock:
                for step_id in fired_step_ids:
                    if step_id:
                        _sent_quickstep_fired[(sent_id, step_id)] = now
    except Exception as exc:  # noqa: BLE001
        # Audit F-02 (2026-05-17 deep-audit): the previous logger.debug
        # buried real auto_trigger failures (e.g. broken QS configs,
        # transient DB errors). Promote to warning so operators see
        # repeated failures in the regular log without enabling DEBUG.
        logger.warning("immediate sent-side quicksteps fire failed: %s", exc)


# ---------------------------------------------------------------------------
# 2. Background scheduler tick
# ---------------------------------------------------------------------------

def run_quicksteps_scheduled(oauth_account_id: str, emails: Optional[list] = None) -> None:
    """Per-account scheduler tick — safety-net QS eval + wake-time sweep.

    Replaces the legacy ``_check_followups_bg`` nudge loop. Throttled to
    once per ``_SCHEDULER_MIN_INTERVAL`` seconds per account so high-
    frequency callers (every inbox-open) don't thrash the DB.

    One job: ``sweep_woken_snoozed_drafts`` — promote/delete snoozed
    follow-up drafts whose snooze elapsed (reply check via the provider).

    ``emails`` is accepted for caller compatibility but no longer used.
    Account-scoped throughout; safe to call concurrently for different
    accounts.
    """
    throttle_key = oauth_account_id or "_no_account"
    now = time.time()
    if now - _scheduler_last_run.get(throttle_key, 0.0) < _SCHEDULER_MIN_INTERVAL:
        return

    if not _scheduler_lock.acquire(blocking=False):
        # Audit F-03 (2026-05-16): do NOT bump _scheduler_last_run on
        # lock contention. The throttle key is per-account but the
        # lock is module-global; bumping account B's throttle because
        # account A holds the lock starves B for the full
        # _SCHEDULER_MIN_INTERVAL. The winning account (A) bumps its
        # own throttle inside the lock-held branch below, so the
        # "flood of A calls" backoff still works. The losing account
        # (B) returns immediately and retries on the next user action;
        # A releases within a few seconds and B's next attempt wins.
        return

    global _scheduler_running
    try:
        _scheduler_running = True

        # Resolve account id once for both downstream jobs. dual-format per
        # CLAUDE.md (int from /api/init, hex from /api/accounts).
        account_id_int: int | None = None
        if oauth_account_id:
            if oauth_account_id.isdigit():
                account_id_int = int(oauth_account_id)
            else:
                try:
                    account_id_int = _resolve_oauth_account_to_int(oauth_account_id)
                except Exception:  # noqa: BLE001
                    account_id_int = None

        if not account_id_int or account_id_int <= 0:
            _scheduler_last_run[throttle_key] = time.time()
            return

        try:
            sweep_woken_snoozed_drafts(
                account_id=account_id_int,
                oauth_account_id=oauth_account_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[QS-SCHED] sweep_woken_snoozed_drafts failed: {exc}")

        # Re-evaluate passive time-based Quick Steps (email_older_than_days /
        # no_reply_after_days) over the stored inbox. These never re-trigger
        # on the event path once an email is sitting in place, so the timer
        # tick is the only thing that lets "auto-archive inbox > 30d" fire.
        # Best-effort + idempotent (per-(step,email) audit dedup downstream).
        try:
            from app.quicksteps.auto_trigger import run_housekeeping_sweep
            run_housekeeping_sweep(account_id_int)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[QS-SCHED] run_housekeeping_sweep failed: {exc}")

        _scheduler_last_run[throttle_key] = time.time()

    except Exception as exc:  # noqa: BLE001
        logger.error(f"[QS-SCHED] scheduler tick failed: {exc}")
    finally:
        _scheduler_running = False
        _scheduler_lock.release()


def sweep_woken_snoozed_drafts(*, account_id: int, oauth_account_id: str) -> None:
    """Process any draft_followup reminders whose date just elapsed.

    Acquires the provider once and delegates to
    ``sweep_woken_draft_followups`` in the QS handler. Cheap when there
    are no woken entries (single JSON read), bounded by the number of
    expired-but-not-yet-checked drafts otherwise.
    """
    try:
        from app.services.reminder_service import list_draft_followups
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[QS-SCHED] draft_followup module unavailable: {exc}")
        return

    # Cheap early-exit: skip the provider acquisition (network setup) when
    # there's nothing waking up. Reading the JSON once is the fast path.
    pending_entries = list_draft_followups(account_id=account_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    if not any(
        not e.get("notified", False) and (e.get("reminder_date") or "") <= now_iso
        for e in pending_entries
    ):
        return

    # Resolve account email + provider. Both are required for the reply
    # check; if either is missing, defer to the next sweep.
    try:
        from app.multi_accounts import get_account_manager
        cfg = get_account_manager().get_account(oauth_account_id)
        account_email = getattr(cfg, "email", "") if cfg else ""
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[QS-SCHED] account email lookup failed: {exc}")
        return
    if not account_email:
        return

    # Audit F-01 (2026-05-13 deep-audit pass): the provider factory keys
    # its account map by hex OAuth id (multi_accounts.py:444-446). Passing
    # `str(account_id)` (the int Account.id) made every wake-sweep raise
    # "Account ... not found" and silently swallow at .debug — the snoozed
    # follow-up surface was dead on every install. Use the hex id we
    # already have in scope.
    try:
        from app.providers.factory import get_pooled_provider
        provider = get_pooled_provider(account_id=oauth_account_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[QS-SCHED] provider acquisition failed: {exc}")
        return

    try:
        from app.quicksteps.handlers.create_snoozed_followup_draft import (
            sweep_woken_draft_followups,
        )
        counters = sweep_woken_draft_followups(
            account_id=account_id,
            account_email=account_email,
            provider=provider,
        )
        if counters.get("checked"):
            logger.info(
                "[SNOOZED_DRAFT] sweep account=%s: %s",
                account_id, counters,
            )
    finally:
        try:
            provider.disconnect()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# 3. Event-driven snoozed-draft cleanup (issue #689, refactor 2026-05-20)
# ---------------------------------------------------------------------------
#
# Gmail Pub/Sub push → SyncService.trigger_account_sync(account_id) → on
# sync completion, SyncService fires `on_sync_complete(results, duration_ms)`.
# `run_api.on_sync_complete_callback` walks results and calls
# `process_snoozed_draft_replies_after_sync(...)` for each successful
# account.
#
# NOTE 2026-06-09 : `process_replies_after_sync` (détection de réponses via
# le FollowupTracker legacy) a été retiré — le refactor 316c3434 avait
# supprimé le tracker et `Container.get_followup_tracker()` mais laissé la
# fonction et son appel dans run_api, qui loggait « tracker port
# unavailable » à CHAQUE sync (696 occurrences, audit 2026-06-09). Le
# nettoyage event-driven passe par le PendingDraft store ci-dessous.


def _thread_has_engagement_beyond_cold_send(emails) -> bool:
    """True iff the thread contains more than the original cold send — i.e.
    at least one inbound reply OR an outbound message the user sent later.

    Direction-agnostic: any new row past the original send obsoletes the
    auto-followup. Uses **row count** rather than `row.date > draft.created_at`
    because `Email.date` storage is mixed (some SQLite roundtrips strip
    tzinfo and the DB ends up holding naive local time, while
    `draft.created_at` is naive-UTC) — date comparisons silently mis-fire
    by the local↔UTC offset. Counting rows is timezone-immune and matches
    the product intent: a thread with >1 message is engaged.

    `EmailRepository.get_by_thread` already drops synthetic `compose-*` /
    `reply-*` placeholder rows when a real provider row exists in the
    same thread, so we don't double-count the just-sent message.
    """
    return len(emails or []) > 1


def _kill_snoozed_followup_for_thread(
    *, thread_id: str, account_id: int,
) -> bool:
    """Delete the PendingDraft + dismiss its draft_followup reminder for
    a thread that no longer needs an automated follow-up.

    Mirrors the recipient-replied branch of `sweep_woken_draft_followups`
    but runs eagerly off the sync hook instead of waiting for the wake
    date. Returns True iff a draft was actually deleted. Best-effort:
    never raises — the sync callback must stay robust.
    """
    if not thread_id or not account_id or account_id <= 0:
        return False
    try:
        from app.infrastructure.container import get_container
        from app.services.reminder_service import (
            dismiss_reminder, list_draft_followups,
        )

        store = get_container().get_pending_draft_store()
        draft = store.get_by_email_id(thread_id, account_id=str(account_id))
        if draft is None or (draft.routing_tier or "") != "followup":
            return False

        reminder_id = ""
        try:
            for entry in list_draft_followups(account_id=account_id):
                if entry.get("email_id") == draft.id:
                    reminder_id = entry.get("id", "") or ""
                    break
        except Exception as _list_exc:  # noqa: BLE001
            logger.debug(
                "[FU-EVENT] list_draft_followups failed for %s: %s",
                account_id, _list_exc,
            )

        try:
            store.delete(draft.id)
        except Exception as _del_exc:  # noqa: BLE001
            logger.warning(
                "[FU-EVENT] PendingDraft delete failed for %s: %s",
                draft.id, _del_exc,
            )
            return False

        if reminder_id:
            try:
                dismiss_reminder(reminder_id, account_id=account_id)
            except Exception as _dis_exc:  # noqa: BLE001
                logger.debug(
                    "[FU-EVENT] dismiss_reminder(%s) failed: %s",
                    reminder_id, _dis_exc,
                )

        logger.info(
            "[FU-EVENT] thread=%s engaged → deleted snoozed draft %s",
            thread_id, draft.id,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "[FU-EVENT] _kill_snoozed_followup_for_thread(%s) failed: %s",
            thread_id, exc,
        )
        return False


def process_snoozed_draft_replies_after_sync(
    account_id: int, account_email: str,
) -> int:
    """Eager cleanup of snoozed follow-up drafts whose thread has any new
    activity past the cold send.

    Triggers on EITHER:
      - Inbound reply from the recipient.
      - Outbound message from the user (they re-engaged the thread, e.g.
        replied to a reply or sent a follow-up manually).

    Without this, the snoozed draft sat in Drafts/Later until its own
    wake date (~7 days) arrived. Wired into `on_sync_complete` so it
    runs after every Gmail sync (incremental or push-triggered).

    Returns the number of drafts killed.
    """
    if not account_id or account_id <= 0 or not account_email:
        return 0
    try:
        from app.infrastructure.container import get_container
        from app.db.database import get_db_session
        from app.db.repositories.email_repository import EmailRepository

        store = get_container().get_pending_draft_store()
        candidates = store.get_pending(limit=200, account_id=str(account_id))
        followups = [
            d for d in candidates if (d.routing_tier or "") == "followup"
        ]
        if not followups:
            return 0
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "[FU-DRAFT-EVENT] preflight failed for %s: %s", account_id, exc,
        )
        return 0

    killed = 0
    try:
        with get_db_session() as session:
            repo = EmailRepository(session)
            for d in followups:
                thread_id = (d.email_id or "").strip()
                if not thread_id:
                    continue
                try:
                    rows = repo.get_by_thread(thread_id, int(account_id))
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "[FU-DRAFT-EVENT] get_by_thread(%s) failed: %s",
                        thread_id, exc,
                    )
                    continue
                if not _thread_has_engagement_beyond_cold_send(rows):
                    continue
                if _kill_snoozed_followup_for_thread(
                    thread_id=thread_id, account_id=int(account_id),
                ):
                    killed += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[FU-DRAFT-EVENT] DB session failed for %s: %s",
            account_id, exc,
        )
    return killed


def run_scheduled_sweeps_after_sync(account_id: int, account_email: str) -> None:
    """Run the throttled per-account background tick after a server-side sync.

    Wired into ``run_api.on_sync_complete`` so the housekeeping sweep
    (``email_older_than_days`` / ``no_reply_after_days`` rules) AND the
    snoozed-draft wake sweep actually run in the background — not only when
    the user opens the inbox (the legacy ``routes_emails`` trigger). The
    5-min per-account throttle inside ``run_quicksteps_scheduled`` bounds the
    cadence no matter how often syncs fire.

    ``run_quicksteps_scheduled`` keys its snoozed-draft provider lookup on the
    hex multi_accounts id, so we resolve it from ``account_email`` first.
    Falling back to the int id (as str) still runs the SQL-only housekeeping
    sweep (the snoozed-draft sweep no-ops without the hex). Best-effort — must
    never raise into the sync callback.
    """
    if not account_id or account_id <= 0 or not account_email:
        return
    oauth_id: str | None = None
    try:
        from app.multi_accounts import get_account_manager
        cfg = get_account_manager().get_account_by_email(account_email)
        oauth_id = getattr(cfg, "id", None) if cfg else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[QS-SCHED] hex resolve failed for %s: %s", account_email, exc)
    try:
        run_quicksteps_scheduled(oauth_id or str(account_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[QS-SCHED] run_scheduled_sweeps_after_sync failed: %s", exc)


__all__ = [
    "fire_sent_quicksteps_immediate",
    "run_quicksteps_scheduled",
    "run_scheduled_sweeps_after_sync",
    "sweep_woken_snoozed_drafts",
    "process_snoozed_draft_replies_after_sync",
]
