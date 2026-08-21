# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour les emails — liste, détails, actions, envoi.
"""

import logging
import os
import re
import threading
import time as _cache_time
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Optional
from flask import request, jsonify, g, Response, abort
from werkzeug.exceptions import HTTPException

from app.config import should_persist_email_content
from app.db.models.email import Email
from app.interfaces.email_provider import InsufficientScopeError
from app.api.utils.bulk_validation import validate_bulk_email_ids
from app.api.utils.errors import error_response
from app.utils.dates import cached_date_needs_heal, to_naive_utc, utc_now_naive

# Module-level import for mutable variable access (_last_bg_jobs_time)
import app.api.routes_helpers as _rh

from .routes_helpers import (
    api_bp,
    MAX_OFFSET,
    _to_iso_utc,
    _resolve_account_id_for_user,
    _resolve_account_id_cached,
    _get_current_account_for_user,
    _get_authenticated_provider,
    _resolve_account_id_for_provider,
    _validate_email_id,
    _sanitize_for_log,
    _get_email_by_id,
    _rate_limited,
    _safe_call,
    require_json,
    _detach_provider_from_request,
    _get_blocked_senders_set,
    _filter_blocked_senders,
    _get_spammed_senders_set,
    _get_spammed_domains_set,
    _filter_spammed_senders,
    _learn_spam_pattern,
    _unlearn_spammed_sender,
    _get_cached_email_response,
    _set_cached_email_response,  # noqa: F401 - kept patchable for folder-list tests
    _invalidate_folder_cache,
    _get_cached_email_detail,
    _set_cached_email_detail,
    _get_label_batch_cached,
    _set_label_batch_cached,
    _invalidate_label_batch_cache,
    _find_sent_email_in_list_cache,
    _find_email_in_list_cache,
    _evict_sent_sqlite_cache,
    _refresh_sent_cache_bg,
    _prefetch_sent_bodies,
    _resolve_folder_for_provider,
    _evict_email_from_all_caches,
    _validate_limit,
    _validate_optional_string,
    _create_draft_and_mark_read_no_bg,
    _fetch_conversation_history_for_contact,
    _process_email_with_use_case,
    _email_detail_cache,
    _email_detail_cache_lock,
    _RE_STYLE_TAG,
    _RE_HTML_TAG,
    _RE_WHITESPACE,
    LegacyModuleLoader,
)

# Security: Input validation constants for list_emails
LIST_EMAILS_MIN_LIMIT = 1
LIST_EMAILS_MAX_LIMIT = 500
LIST_EMAILS_DEFAULT_LIMIT = 50

# Security: Input length limits
MAX_SUBJECT_LENGTH = 998  # RFC 5322 recommends max 78 chars, but allows up to 998
MAX_BODY_LENGTH = 1_000_000  # 1MB reasonable max for email body

logger = logging.getLogger(__name__)


def _invalidate_label_counts_cache(account_id: Optional[int] = None) -> None:
    """Invalidate `/api/labels/counts` cache after read/folder/label changes."""
    try:
        from app.api.labels import _invalidate_labels_cache

        _invalidate_labels_cache(account_id=account_id)
    except Exception as exc:
        logger.debug("Label counts cache invalidation failed: %s", exc)


def _best_effort_bulk_read_status_update(
    email_ids: list[str],
    is_read: bool,
    account_id: Optional[int],
    log_prefix: str,
) -> None:
    """Mirror bulk read-status changes locally without blocking the HTTP route."""
    all_ids = email_ids + [eid[5:] for eid in email_ids if eid.startswith("sent:")]
    try:
        with _rh.get_db_session() as session:
            bind = session.get_bind()
            if getattr(getattr(bind, "dialect", None), "name", "") == "sqlite":
                session.connection().exec_driver_sql("PRAGMA busy_timeout = 100")
            repo = _rh.EmailRepository(session)
            repo.bulk_update_read_status(all_ids, is_read, account_id=account_id)
            session.commit()
    except Exception as exc:
        logger.warning("%s SQLite update failed: %s", log_prefix, exc)
    finally:
        _invalidate_label_counts_cache(account_id=account_id)


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _positive_float_env(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _mock_load_test_rate_limit_bypass() -> bool:
    """Bypass draft rate limits only for explicit mocked load tests."""
    return (
        _env_flag("AGENTYS_LOAD_TEST_MODE")
        and _env_flag("AGENTYS_LOAD_TEST_BYPASS_RATE_LIMIT")
        and _env_flag("AGENTYS_MOCK_LLM")
        and _env_flag("AGENTYS_MOCK_EMAIL_PROVIDER")
    )


def _mock_load_test_account_header() -> int | None:
    """Use synthetic account partitions only for mocked load tests."""
    if not (
        _env_flag("AGENTYS_LOAD_TEST_MODE")
        and _env_flag("AGENTYS_MOCK_LLM")
        and _env_flag("AGENTYS_MOCK_EMAIL_PROVIDER")
    ):
        return None
    raw = (request.headers.get("X-Account-Id") or "").strip()
    if not raw:
        return None
    try:
        account_id = int(raw)
    except ValueError:
        return None
    return account_id if account_id > 0 else None


def _is_auth_expired_error(exc: BaseException) -> bool:
    """Return True when a provider exception means the account needs reauth."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 401:
        return True
    if getattr(exc, "status_code", None) == 401:
        return True
    if type(exc).__name__ in {"RefreshError", "InvalidGrantError", "UnauthorizedError"}:
        return True
    msg = str(exc).lower()
    return (
        "401" in msg
        or "unauthorized" in msg
        or "invalid_grant" in msg
        or "token has been expired" in msg
        or "token révoqué" in msg
    )


DRAFT_BODY_CACHE_WAIT_SECONDS = _positive_float_env("AGENTYS_DRAFT_BODY_CACHE_WAIT_SECONDS", 3.0)
DRAFT_BODY_CACHE_POLL_SECONDS = _positive_float_env("AGENTYS_DRAFT_BODY_CACHE_POLL_SECONDS", 0.5)
DRAFT_PROVIDER_QUOTA_WAIT_SECONDS = _positive_float_env("AGENTYS_DRAFT_PROVIDER_QUOTA_WAIT_SECONDS", 5.0)


def _sanitize_provider_error(raw: str) -> str:
    """Strip raw provider exception repr from error strings before returning
    them to the client.

    Audit Cluster A (2026-05-10) U-01: providers stash the str() of the
    underlying SDK exception in ``_last_error``. For Google's API client this
    yields strings like
        ``<HttpError 400 when requesting https://gmail.googleapis.com/... returned "Invalid To header".>``
    which (a) leaks the API endpoint URL, (b) renders as ugly technical noise
    in user-facing toasts. This helper extracts the useful human reason from
    the quoted ``returned "<reason>"`` segment when present, otherwise returns
    a generic message. It is intentionally conservative — anything matching
    ``<…HttpError…>`` or containing ``googleapis.com`` is rewritten.
    """
    import re as _re_san

    if not raw:
        return "Failed to send email"
    text = str(raw)

    # Try to extract `returned "<reason>"` first so we keep useful info
    # like "Invalid To header".
    m = _re_san.search(r'returned\s+"([^"]+)"', text)
    extracted = m.group(1).strip() if m else ""

    looks_like_repr = text.startswith("<") and "Error" in text[:80]
    leaks_endpoint = "googleapis.com" in text or "graph.microsoft.com" in text
    if looks_like_repr or leaks_endpoint:
        if extracted:
            return extracted[:300]
        return "Provider rejected the request"

    return text[:300]


def _normalize_reply_recipients(recipients: list[str]) -> str:
    return ",".join(r.strip().lower() for r in recipients if isinstance(r, str) and r.strip())


def _find_recent_sent_reply(
    *,
    account_id: int,
    subject: str,
    recipients: list[str],
    body: str,
    body_with_signature: str,
    thread_id: str | None = None,
) -> str | None:
    """Return an existing sent message id for a likely retry of the same reply.

    Browser/proxy timeouts can happen after the provider accepted the send.
    A manual retry must not send the same email twice; the send path writes a
    sent-cache row before returning, so this guard can turn that retry into an
    idempotent success response.
    """
    recipients_key = _normalize_reply_recipients(recipients)
    if not account_id or not subject or not recipients_key:
        return None

    body_plain = (body or "").strip()
    body_signed = (body_with_signature or "").strip()
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30)

    try:
        from sqlalchemy import select

        stmt = (
            select(
                Email.email_id,
                Email.recipients,
                Email.body_text,
                Email.body_html,
                Email.thread_id,
            )
            .where(
                Email.account_id == account_id,
                Email.is_sent == True,  # noqa: E712
                Email.subject == subject,
                Email.date >= cutoff,
            )
            .order_by(Email.date.desc())
            .limit(50)
        )
        if thread_id:
            stmt = stmt.where(Email.thread_id == thread_id)

        with _rh.get_db_session() as session:
            rows = session.execute(stmt).all()
    except Exception as exc:
        logger.warning("recent sent-reply lookup failed: %s", exc, exc_info=True)
        return None

    for row in rows:
        if _normalize_reply_recipients((row.recipients or "").split(",")) != recipients_key:
            continue
        row_body_html = (row.body_html or "").strip()
        row_body_text = (row.body_text or "").strip()
        if (body_signed and row_body_html == body_signed) or (body_plain and row_body_text == body_plain):
            return row.email_id or "sent-directly"
    return None


def _get_email_for_reply_action(provider, email_id: str, account_id: int | None):
    """Load enough email context for reply actions without forcing body fetch.

    Sending or saving a reply needs sender, subject and thread metadata, not the
    original body. In metadata-only mode, `_get_email_by_id` may fetch the full
    Gmail body synchronously; this helper first accepts a header-only SQLite row
    and only falls back to the provider if the row is missing.
    """
    lookup_id = email_id[5:] if email_id.startswith("sent:") else email_id
    try:
        from app.api.routes_helpers import _get_email_from_cache

        cached = _get_email_from_cache(
            lookup_id,
            account_id=account_id,
            allow_bodyless=True,
        )
        if cached:
            return cached
    except Exception as exc:
        logger.debug(
            "reply action header-cache lookup failed for %s: %s",
            _sanitize_for_log(email_id),
            exc,
        )

    return _get_email_by_id(provider, email_id, account_id=account_id)


@api_bp.route("/emails/debug", methods=["GET"])
def debug_emails():
    """Diagnostic endpoint to debug IMAP issues."""
    try:
        # Réutilise le provider déjà authentifié (pool partagé) — évite une nouvelle connexion IMAP
        provider = _get_authenticated_provider()
        provider_type = type(provider).__name__

        # Headers seulement — rapide, pas de fetch de body
        emails = provider.get_message_headers(limit=5, unread_only=False) if hasattr(provider, 'get_message_headers') else provider.get_messages(limit=5, unread_only=False)

        return jsonify({
            "provider_type": provider_type,
            "authenticated": True,
            "email_count": len(emails),
            "emails": [
                {
                    "id": e.id,
                    "sender": e.sender,
                    "sender_name": e.sender_name,
                    "subject": e.subject[:50] if e.subject else "",
                    "received_at": str(e.received_at) if e.received_at else None
                }
                for e in emails
            ]
        })
    except Exception as e:
        import traceback
        logger.error(f"Debug endpoint error: {traceback.format_exc()}")
        return jsonify({
            "error": str(e),
        }), 500


# ── Process-email cancellation registry ──
# Maps (account_id, email_id) → threading.Event; set the event to request
# cancellation. The composite key matters because provider email_ids are
# only unique *per account*, so two users processing emails with the same
# provider ID must not share a cancellation event.
_cancel_registry: dict = {}
_cancel_registry_lock = threading.Lock()

# ── Per-draft in-flight send guard (P1-004) ──
# Prevents double-send when the user double-clicks the Send button and two
# requests race for the same draft_id. Keyed by draft_id string.
_send_in_flight: set[str] = set()
_send_in_flight_lock = threading.Lock()


def _cancel_key(account_id: int | None, email_id: str) -> tuple[int | None, str]:
    return (account_id, email_id)


def _register_cancel_event(account_id: int | None, email_id: str) -> threading.Event:
    with _cancel_registry_lock:
        key = _cancel_key(account_id, email_id)
        event = _cancel_registry.get(key)
        if event is None:
            event = threading.Event()
            _cancel_registry[key] = event
    return event


def _unregister_cancel_event(account_id: int | None, email_id: str) -> None:
    with _cancel_registry_lock:
        _cancel_registry.pop(_cancel_key(account_id, email_id), None)


def _is_cancelled(account_id: int | None, email_id: str) -> bool:
    with _cancel_registry_lock:
        event = _cancel_registry.get(_cancel_key(account_id, email_id))
    return event is not None and event.is_set()


# ── Auto-reply background handler (fires from list_emails for inbox) ──

_auto_reply_lock = threading.Lock()
# S-02 fix (2026-04-24): the running guard is now keyed by oauth_account_id.
# Previously a single module-level bool meant account A's auto-reply run
# silently starved account B's run during the overlap window — B's
# vacation messages never went out.
_auto_reply_running_per_account: dict[str, bool] = {}
# Legacy global kept for callers we may have missed; treated as a fallback
# when oauth_account_id is unknown.
_auto_reply_running = False


def _resolve_email_owner_account_id(email_id: str) -> int | None:
    """Return the DB ``account_id`` that owns this ``email_id``.

    Direct SQL lookup against the ``emails`` table — bypasses the JWT
    default-account resolver, which is wrong for multi-account users
    (different mailboxes, different labels store). Returns None when the
    email is not in the cache (caller falls back to the JWT default).
    """
    if not email_id:
        return None
    lookup_id = email_id[5:] if email_id.startswith("sent:") else email_id
    try:
        from sqlalchemy import select
        from app.db.database import get_db_session
        from app.db.models.email import Email
        with get_db_session() as session:
            stmt = select(Email.account_id).where(Email.email_id == lookup_id).limit(1)
            row = session.execute(stmt).scalar_one_or_none()
            return int(row) if row else None
    except Exception as exc:  # noqa: BLE001
        # Audit B-05 (2026-05-12): elevated to .warning. When this returns
        # None the caller falls back to the JWT default account_id which can
        # be the wrong account on multi-account installs — the fallback must
        # be visible in prod logs (Railway default level = INFO).
        logger.warning(
            "[qs-reeval] email-owner resolve failed for email_id=%s: %s — "
            "caller will fall back to JWT default", email_id, exc,
        )
        return None


def _reeval_auto_triggers_async(email_id: str, email_obj) -> None:
    """Spawn a daemon thread that re-evaluates auto-triggers for one email.

    Hooked from state-change routes (mark-as-read, …) so Quick Steps whose
    conditions depend on post-arrival state (e.g. ``is_read=true``) fire
    when the state actually flips. Per-(step, email) dedup lives inside
    ``run_auto_triggers`` (audit-log query) so rules that already fired at
    arrival don't double-execute.

    Latency is moved off the request thread on purpose — a synchronous
    re-eval inside the mark-as-read route would block the 200 by 5-500 ms
    depending on rule shape, killing the UI's snappy feel.

    account_id MUST be resolved by EMAIL OWNERSHIP, not by JWT default.
    The same user can have multiple accounts (Gmail 13 + Outlook 14); the
    JWT default returns ONE — usually the last-added — and `has_label`
    lookups for an email owned by a different account would miss. Resolve
    via the ``emails`` SQL table (email_id → account_id) so the trigger
    scan reads labels from the correct ``data/labels/{account_id}/``
    store. The JWT on ``flask.g`` is gone in the daemon thread, so do the
    resolution here in the request context.
    """
    if not email_id or email_obj is None:
        logger.info(f"[qs-reeval] skip: email_id={email_id!r} email_obj={email_obj!r}")
        return
    try:
        account_id = _resolve_email_owner_account_id(email_id)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"[qs-reeval] skip: email-owner resolve failed: {exc}")
        return
    if not account_id or account_id <= 0:
        # Fallback to the JWT default — handles emails missing from the
        # SQL cache (fresh sync, transient gap). May resolve to the wrong
        # account in multi-account setups, but better than skipping.
        try:
            account_id = _rh._resolve_account_id_for_user()
        except Exception as exc:  # noqa: BLE001
            logger.info(f"[qs-reeval] skip: JWT fallback resolve failed: {exc}")
            return
        if not account_id or account_id <= 0:
            logger.info(f"[qs-reeval] skip: bad account_id={account_id!r}")
            return
        logger.info(f"[qs-reeval] using JWT fallback account_id={account_id} for email_id={email_id}")

    try:
        from flask import has_app_context, current_app
        flask_app = current_app._get_current_object() if has_app_context() else None
    except Exception:
        flask_app = None

    logger.info(f"[qs-reeval] spawning thread for email_id={email_id} account_id={account_id}")

    def _worker(_aid: int = int(account_id)) -> None:
        try:
            from app.quicksteps.auto_trigger import run_auto_triggers
            logger.info(f"[qs-reeval] worker start for email_id={email_id} aid={_aid} is_read={getattr(email_obj, 'is_read', '?')}")

            def _go() -> None:
                run_auto_triggers(_aid, email_id, email_obj)
                logger.info(f"[qs-reeval] worker done for email_id={email_id}")

            if flask_app is not None:
                with flask_app.app_context():
                    _go()
            else:
                _go()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[qs-reeval] worker failed: {exc}", exc_info=True)

    import threading
    threading.Thread(target=_worker, daemon=True, name="qs-reeval").start()


def _persist_auto_reply_tracker(replied_senders: dict, tracker_path: str) -> bool:
    """Atomically persist the auto-reply tracker. Used for both the
    pending pre-mark (F-02) and the post-cycle final flush.

    Returns True on success, False if the write failed. The pre-mark caller MUST
    check this (deep audit 2026-06-02 J / BS-09): if the dedup record never
    reaches disk, the next 60s cycle reloads a tracker without this sender and
    re-sends — so a failed pre-mark must skip the send, not fire it.
    """
    import json
    import os
    import tempfile
    try:
        os.makedirs("data", exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir="data",
            delete=False, suffix=".tmp"
        ) as tmp:
            json.dump(replied_senders, tmp, ensure_ascii=False, indent=2)
            tmp_name = tmp.name
        os.replace(tmp_name, tracker_path)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[AUTO-REPLY] tracker persist failed: {exc}")
        return False

# S-10 fix (2026-04-24): bound concurrent draft-generation threads PER ACCOUNT.
# Without this, a burst of /process requests (offline-resume, deep focus) spawns
# unbounded threads → unbounded LLM streams → cascading 429s.
# A per-account ceiling of 4 keeps a single user's queue from saturating the
# Anthropic rate limit while leaving room for other accounts to make progress.
_PROCESS_PER_ACCOUNT_MAX = 4
_process_semaphores_lock = threading.Lock()
_process_semaphores: dict[str, threading.Semaphore] = {}


def _get_process_semaphore(account_id) -> threading.Semaphore:
    """Return the per-account semaphore for /process draft generation.

    S-10: lazily-initialised, never released (process lifetime is fine for
    a Semaphore — only the in-flight permit count matters).
    """
    key = str(account_id) if account_id not in (None, "", -1) else "__global__"
    with _process_semaphores_lock:
        sem = _process_semaphores.get(key)
        if sem is None:
            sem = threading.Semaphore(_PROCESS_PER_ACCOUNT_MAX)
            _process_semaphores[key] = sem
        return sem


def _send_auto_replies_bg(emails, oauth_account_id: str, account_id: int = None):
    """
    Background thread: send auto-replies for new unread inbox emails.
    Uses a persistent JSON tracker to avoid duplicate sends across restarts.
    Accepts both domain email objects and SQLite Email model objects.
    account_id must be resolved by the caller (inside request context).
    """
    global _auto_reply_running
    # S-02 fix: per-account "running" gate.
    _scope_key = str(oauth_account_id) if oauth_account_id else "__global__"
    with _auto_reply_lock:
        if _auto_reply_running_per_account.get(_scope_key):
            logger.debug(
                "[AUTO-REPLY] Skipped: another run is already in flight for account=%s",
                _scope_key,
            )
            return
        _auto_reply_running_per_account[_scope_key] = True
        # Keep legacy global flag in sync for backward-compat reads.
        _auto_reply_running = True

    try:
        import json
        import os
        from app.api.settings import load_settings

        settings = load_settings(account_id=account_id)
        if not settings.get("auto_reply_enabled", False):
            logger.debug(
                "[AUTO-REPLY] Disabled for account=%s (auto_reply_enabled=False)",
                _scope_key,
            )
            return
        message = settings.get("auto_reply_message", "").strip()
        if not message:
            return
        start_date = settings.get("auto_reply_start", "")
        end_date = settings.get("auto_reply_end", "")
        if not start_date or not end_date:
            return

        # NOTE: no global today-vs-range check here. Each email's received_at
        # is checked individually below, so auto-replies still fire for emails
        # that arrived during the vacation period even after it ends (e.g.
        # user returns, opens inbox, and missed emails get their reply).

        # Load persistent tracker (survives restarts) — scoped per-account so
        # auto-replies sent from account A don't suppress those of account B.
        # Reads fall back to the legacy global file once for migration, but
        # writes always target the per-account file going forward.
        legacy_tracker_path = os.path.join("data", "auto_reply_tracker.json")
        tracker_path = os.path.join("data", f"auto_reply_tracker_{oauth_account_id}.json")
        tracker_read_path = tracker_path if os.path.exists(tracker_path) else legacy_tracker_path
        replied_senders = {}
        if os.path.exists(tracker_read_path):
            try:
                with open(tracker_read_path, "r", encoding="utf-8") as f:
                    replied_senders = json.load(f)
            except Exception as e:
                logger.warning(f"[AUTO-REPLY] Failed to load tracker JSON (corrupt file?): {e}")
                replied_senders = {}
        if not isinstance(replied_senders, dict):
            logger.warning("[AUTO-REPLY] Tracker JSON has unexpected schema (not a dict) — resetting.")
            replied_senders = {}

        # Clean old entries (different period)
        replied_senders = {
            k: v for k, v in replied_senders.items()
            if v.get("period") == f"{start_date}_{end_date}"
        }

        # F-02: legacy entries were keyed on the raw envelope string (e.g.
        # `"bob smith" <bob@x>`). Re-key onto the parsed RFC5322 address so a
        # mid-period deploy doesn't duplicate-fire on already-replied senders.
        from email.utils import parseaddr as _parse_addr_for_migration
        _migrated: dict = {}
        for _k, _v in replied_senders.items():
            _, _addr = _parse_addr_for_migration(str(_k))
            _new_key = (_addr or _k).strip().lower()
            # Preserve the strictest existing status on collision (sent > pending).
            _prev = _migrated.get(_new_key)
            if not _prev or (_prev.get("status") != "sent" and _v.get("status") == "sent"):
                _migrated[_new_key] = _v
        replied_senders = _migrated

        # Filter: unread inbox emails from real senders
        try:
            from app.smart_routing import _SKIP_SENDER_PATTERNS
        except ImportError:
            _SKIP_SENDER_PATTERNS = None

        # Resolve the account owner's email so we can skip self-replies.
        # Forwarding a message back to the same inbox (or threading weirdness)
        # could otherwise produce an auto-reply loop against the user's own
        # address, which the noreply filter wouldn't catch.
        _owner_email = ""
        try:
            from app.multi_accounts import get_account_manager
            _own_acct = get_account_manager().get_account(oauth_account_id)
            if _own_acct:
                _owner_email = (getattr(_own_acct, "email", "") or "").lower().strip()
        except Exception as _own_err:
            # Audit B-10 (2026-05-12): elevated to .warning + guard. If the
            # owner lookup fails the self-reply detector can't filter the
            # user's own address out of the auto-reply target list, which
            # could trigger an auto-reply loop against themselves.
            logger.warning(
                "[AUTO-REPLY] owner lookup failed for oauth_account_id=%s: %s "
                "— self-reply detection degraded",
                oauth_account_id, _own_err,
            )

        from email.utils import parseaddr as _parse_addr

        new_replies = []
        for email_obj in emails:
            # Support both domain objects and SQLite Email models
            sender = getattr(email_obj, 'sender', '') or ''
            email_id = getattr(email_obj, 'email_id', None) or getattr(email_obj, 'id', '')
            is_read = getattr(email_obj, 'is_read', False)

            if not sender:
                continue

            # Skip emails that arrived outside the auto-reply period.
            # Compare YYYY-MM-DD so missed emails still get their reply
            # when the user opens the inbox after vacation.
            _email_dt = getattr(email_obj, 'received_at', None) or getattr(email_obj, 'date', None)
            if _email_dt:
                _ds = _email_dt.strftime("%Y-%m-%d") if isinstance(_email_dt, datetime) else str(_email_dt)[:10]
                if _ds < start_date or _ds > end_date:
                    continue

            sender_lower = sender.lower().strip()
            # RFC 5322 parser — handles "Display Name" <addr>, nested brackets,
            # unquoted display names, and bare addresses correctly.
            _, _parsed_addr = _parse_addr(sender_lower)
            _sender_addr = (_parsed_addr or sender_lower).strip()
            if _owner_email and _sender_addr == _owner_email:
                continue
            # F-02: dedup on the parsed RFC5322 address, not the raw envelope.
            # Marketing/transactional senders and humans rotating clients vary
            # the display name across messages — keying on `sender_lower` would
            # treat each variant as a fresh sender and double-fire the reply.
            if _sender_addr in replied_senders:
                continue
            if _SKIP_SENDER_PATTERNS and _SKIP_SENDER_PATTERNS.search(sender_lower):
                continue
            # Skip read emails (already seen before auto-reply was enabled)
            if is_read:
                continue
            new_replies.append((email_obj, sender, str(email_id), _sender_addr))

        if not new_replies:
            return

        # Get a fresh provider for sending (thread-safe)
        from app.providers.factory import get_pooled_provider
        send_provider = get_pooled_provider(account_id=oauth_account_id)

        try:
            for email_obj, sender, eid, _sender_addr in new_replies:
                try:
                    from app.utils.email_cleaner import build_reply_subject
                    subject = build_reply_subject(getattr(email_obj, 'subject', '') or '')

                    from app.utils.signature import append_signature
                    body_with_sig = append_signature(
                        message,
                        account_id=account_id,
                        recipient_email=sender,
                    )
                    # The auto-reply message now comes from a rich text editor;
                    # detect HTML so providers send the right Content-Type.
                    import re as _re_html
                    is_html_body = bool(_re_html.search(r"<[a-zA-Z][\s\S]*>", body_with_sig))
                    draft_id = send_provider.create_draft(
                        to=[sender],
                        subject=subject,
                        body=body_with_sig,
                        reply_to_id=eid,
                        is_html=is_html_body,
                    )
                    if draft_id:
                        # F-02 fix: pre-mark the sender as "pending" and persist
                        # BEFORE send_draft. Outlook/Graph and SMTP+IMAP can
                        # commit the send and then return False on a network
                        # timeout — without this guard, the next 60s polling
                        # cycle would re-create-and-re-send, doubling replies.
                        # Tradeoff vs the prior "retry-on-failure" intent
                        # (P0-002): true send failures will not auto-retry on
                        # the same period; that's the smaller harm versus
                        # duplicates landing in the recipient's inbox.
                        replied_senders[_sender_addr] = {
                            "period": f"{start_date}_{end_date}",
                            "sent_at": None,
                            "status": "pending",
                        }
                        if not _persist_auto_reply_tracker(replied_senders, tracker_path):
                            # Deep audit 2026-06-02 J (BS-09): the pre-mark write
                            # failed, so the dedup record isn't on disk. Sending now
                            # would let the next 60s cycle (which reloads the tracker
                            # from disk) re-send a duplicate. Skip this sender this
                            # cycle instead — drop the in-memory pending entry so the
                            # final flush doesn't persist a "pending" that would block
                            # the retry, and let the next cycle re-attempt cleanly.
                            replied_senders.pop(_sender_addr, None)
                            logger.error(
                                f"[AUTO-REPLY] tracker pre-mark persist failed for {sender} — "
                                f"skipping send this cycle to avoid a duplicate; will retry next cycle"
                            )
                            continue
                        sent = send_provider.send_draft(draft_id)
                        if sent:
                            replied_senders[_sender_addr] = {
                                "period": f"{start_date}_{end_date}",
                                "sent_at": datetime.now().isoformat(),
                                "status": "sent",
                            }
                            logger.info(f"[AUTO-REPLY] Envoyé à {sender}")
                        else:
                            logger.error(
                                f"[AUTO-REPLY] Draft créé mais envoi a retourné False pour {sender} — "
                                f"entrée 'pending' conservée pour éviter un double envoi (provider non-atomique)"
                            )
                    else:
                        logger.warning(f"[AUTO-REPLY] Échec création draft pour {sender}")
                except Exception as e:
                    logger.warning(f"[AUTO-REPLY] Erreur pour {sender}: {e}")

            # Final flush — picks up sent_at upgrades and any pending entries.
            _persist_auto_reply_tracker(replied_senders, tracker_path)

            # --- Auto-transfer: forward emails to a designated address ---
            transfer_enabled = settings.get("auto_transfer_enabled", False)
            transfer_email = settings.get("auto_transfer_email", "").strip()
            if transfer_enabled and not transfer_email:
                transfer_enabled = False

            if transfer_enabled:
                # Per-account tracker, with one-shot read fallback to legacy global file.
                legacy_transfer_path = os.path.join("data", "auto_transfer_tracker.json")
                transfer_tracker_path = os.path.join("data", f"auto_transfer_tracker_{oauth_account_id}.json")
                transfer_read_path = transfer_tracker_path if os.path.exists(transfer_tracker_path) else legacy_transfer_path
                transferred_ids = {}
                if os.path.exists(transfer_read_path):
                    try:
                        with open(transfer_read_path, "r", encoding="utf-8") as f:
                            transferred_ids = json.load(f)
                    except Exception as e:
                        logger.debug(f"[AUTO-TRANSFER] Failed to load tracker JSON: {e}")
                        transferred_ids = {}

                # Clean old entries (different period)
                transferred_ids = {
                    k: v for k, v in transferred_ids.items()
                    if v.get("period") == f"{start_date}_{end_date}"
                }

                for email_obj, sender, eid, _sender_addr in new_replies:
                    if eid in transferred_ids:
                        continue
                    try:
                        from app.utils.email_cleaner import build_forward_subject
                        fwd_subject = build_forward_subject(getattr(email_obj, 'subject', '') or '')

                        # Get original body
                        body_text = getattr(email_obj, 'body_text', None) or getattr(email_obj, 'body', None) or ''
                        if not body_text and hasattr(send_provider, 'get_message_by_id'):
                            try:
                                detail = send_provider.get_message_by_id(eid)
                                body_text = getattr(detail, 'body_text', None) or getattr(detail, 'body', '') or ''
                            except Exception as e:
                                logger.debug(f"[AUTO-TRANSFER] Failed to fetch body for {eid}: {e}")
                                body_text = ''

                        # Compose forwarded message — en-tête toujours en français
                        # ("Message transféré / De / Date"), donc heure au format
                        # FR `17h00` (et non `17:00`). Cf. audit format heure 2026-06-23.
                        date_str = datetime.now().strftime("%d/%m/%Y %Hh%M")
                        fwd_body = (
                            f"---------- Message transféré ----------\n"
                            f"De : {sender}\n"
                            f"Date : {date_str}\n"
                            f"Objet : {fwd_subject}\n\n"
                            f"{body_text}"
                        )

                        from app.utils.signature import append_signature
                        fwd_body = append_signature(fwd_body, account_id=account_id)

                        draft_id = send_provider.create_draft(
                            to=[transfer_email],
                            subject=fwd_subject,
                            body=fwd_body,
                        )
                        if draft_id:
                            sent = send_provider.send_draft(draft_id)
                            if sent:
                                transferred_ids[eid] = {
                                    "period": f"{start_date}_{end_date}",
                                    "sent_at": datetime.now().isoformat(),
                                }
                                logger.info(f"[AUTO-TRANSFER] Transféré {eid} à {transfer_email}")
                            else:
                                logger.warning(f"[AUTO-TRANSFER] Échec envoi {eid}")
                        else:
                            logger.warning(f"[AUTO-TRANSFER] Échec création draft {eid}")
                    except Exception as e:
                        logger.warning(f"[AUTO-TRANSFER] Erreur pour {eid}: {e}")

                # Persist transfer tracker (atomic: temp file + os.replace avoids
                # partial-write corruption on crash or concurrent access).
                import tempfile
                os.makedirs("data", exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir="data",
                    delete=False, suffix=".tmp"
                ) as tmp:
                    json.dump(transferred_ids, tmp, ensure_ascii=False, indent=2)
                    tmp_name = tmp.name
                os.replace(tmp_name, transfer_tracker_path)

        finally:
            if hasattr(send_provider, 'disconnect'):
                try:
                    send_provider.disconnect()
                except Exception as e:
                    logger.debug(f"[AUTO-REPLY] Provider disconnect failed: {e}")

    except Exception as e:
        # S-16 lite: keep traceback for ops debugging.
        logger.warning(f"[AUTO-REPLY] Erreur globale: {e}", exc_info=True)
    finally:
        # Release the per-account gate (S-02) AND the legacy global flag.
        with _auto_reply_lock:
            _auto_reply_running_per_account.pop(_scope_key, None)
            _auto_reply_running = bool(_auto_reply_running_per_account)



@api_bp.route("/emails", methods=["GET"])
def list_emails():
    """
    Liste les emails (tous ou non lus) avec pagination.
    ---
    tags:
      - Emails
    summary: Liste les emails
    parameters:
      - name: limit
        in: query
        description: Nombre maximum d'emails à retourner
        schema:
          type: integer
          minimum: 1
          maximum: 500
          default: 50
      - name: offset
        in: query
        description: Nombre d'emails à sauter (pour pagination/infinite scroll)
        schema:
          type: integer
          minimum: 0
          default: 0
      - name: filter
        in: query
        description: Filtre pour les emails (all ou unread)
        schema:
          type: string
          enum: [all, unread]
          default: all
    responses:
      200:
        description: Liste des emails
        content:
          application/json:
            schema:
              type: object
              properties:
                count:
                  type: integer
                  description: Nombre d'emails retournés
                offset:
                  type: integer
                  description: Offset appliqué
                has_more:
                  type: boolean
                  description: True si plus d'emails disponibles
                filter:
                  type: string
                  description: Filtre appliqué
                emails:
                  type: array
                  items:
                    type: object
                    properties:
                      id:
                        type: string
                      subject:
                        type: string
                      sender:
                        type: string
                      received_at:
                        type: string
                        format: date-time
                      is_read:
                        type: boolean
      400:
        description: Paramètre invalide
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
    """
    # bg-jobs throttle lives in routes_helpers — call _rh.should_run_bg_jobs()
    # (S-03 fix: was a single shared float, now per-account dict).
    import time as _time
    _t_start = _time.time()

    limit, error = _validate_limit(
        LIST_EMAILS_MIN_LIMIT,
        LIST_EMAILS_MAX_LIMIT,
        LIST_EMAILS_DEFAULT_LIMIT
    )
    if error:
        return error

    # Paramètre offset (0 par défaut, max MAX_OFFSET to prevent DoS)
    try:
        offset = min(MAX_OFFSET, max(0, int(request.args.get("offset", 0))))
    except (ValueError, TypeError):
        offset = 0

    # Paramètre filter (all par défaut)
    email_filter = request.args.get("filter", "all")
    if email_filter not in ("all", "unread"):
        email_filter = "all"

    # Paramètre label (filtrage par label côté serveur)
    label_param = request.args.get("label", "").strip()
    # NB: deferred until account_id is resolved below — get_emails_by_label
    # must run scoped to the *caller's* account id, not the process-global
    # current account (which leaks across users on multi-user deployments).
    label_email_ids: Optional[set] = None

    # Paramètre exclude_label (exclure les emails avec ce label, ex: Noise)
    # Note: the actual label ID lookup is deferred until needed (SQLite path).
    # The memory cache path filters by label name directly (no ID lookup needed).
    exclude_label_param = request.args.get("exclude_label", "").strip()
    exclude_label_ids: set | None = None

    # Paramètre folder (inbox par défaut)
    folder = request.args.get("folder", "inbox").lower()

    # snoozed est géré côté frontend (localStorage) — aucun dossier IMAP correspondant
    if folder == "snoozed":
        return jsonify({"emails": [], "count": 0, "offset": 0, "has_more": False,
                        "filter": email_filter, "source": "frontend-only"})

    # Map frontend folder names to IMAP folder names
    # The actual resolution is provider-aware (via resolve_folder_name below),
    # but we validate the logical name first.
    _KNOWN_FOLDERS = {"inbox", "sent", "archived", "spam", "trash", "draft"}
    if folder not in _KNOWN_FOLDERS:
        return jsonify({"emails": [], "count": 0, "offset": 0, "has_more": False,
                        "filter": email_filter, "error": f"Unknown folder: {folder}"}), 200

    unread_only = email_filter == "unread"

    # Force refresh parameter: bypass all caches and go directly to provider
    force_refresh = request.args.get("force_refresh", "").lower() in ("true", "1", "yes")

    # Skip memory cache: bypass in-memory cache but still use SQLite (for WS-triggered refreshes)
    skip_memory_cache = request.args.get("skip_cache", "").lower() in ("true", "1", "yes")

    # Audit P1-005 (2026-04-28): if X-Account-Id is supplied it MUST belong
    # to the JWT caller. A bogus / foreign id falls through to the JWT
    # default in the legacy path; reject explicitly here so the multi-
    # account UI can never silently shadow the wrong tenant.
    _x_account_header = request.headers.get("X-Account-Id")
    if _x_account_header:
        from app.api.routes_helpers import require_owned_account_id, _NO_ACCOUNT_SENTINEL
        _owned = require_owned_account_id(_x_account_header)
        if _owned == _NO_ACCOUNT_SENTINEL:
            return jsonify({
                "error": "Account not found or not owned by caller",
                "code": "INVALID_ACCOUNT_HEADER",
            }), 404

    # Use current OAuth account if available, fallback to default
    from app.multi_accounts import get_account_manager, switch_account
    from flask import has_request_context
    auth_user = getattr(g, 'auth_user', None) if has_request_context() else None
    current = _get_current_account_for_user()
    if not current:
        # Auto-activate if a single account exists but none is current
        # Multi-user: only consider accounts belonging to this user
        manager = get_account_manager()
        all_accounts = manager.get_all_accounts()
        uid = None
        if auth_user and auth_user.get("id"):
            try:
                uid = int(auth_user["id"])
                all_accounts = [a for a in all_accounts if a.user_id == uid]
            except (ValueError, TypeError) as e:
                logger.debug(f"Suppressed: {e}")
        if len(all_accounts) == 1:
            switch_account(all_accounts[0].id, user_id=uid if auth_user and auth_user.get("id") else None)
            current = _get_current_account_for_user()
        if not current:
            return jsonify({
                "count": 0,
                "offset": 0,
                "has_more": False,
                "filter": email_filter,
                "source": "none",
                "no_account": True,
                "emails": [],
            })
    # Map multi-account string ID to DB integer account_id for SQLite queries.
    # Use current.email explicitly (not the singleton) to eliminate race conditions
    # where the singleton could change between _get_current_account_for_user() and here.
    account_id = _rh._resolve_account_id_for_email(current.email) if current else _resolve_account_id_cached()

    # Resolve OAuth account ID early — needed by cache-hit path for auto-replies/sync
    oauth_account_id = current.id if current else str(account_id)

    # Now that the caller's account_id is known, resolve the label filter
    # against THIS account specifically. Previously the lookup ran before
    # account resolution and fell back to the process-global current
    # account, which on a multi-user deployment leaks the wrong user's
    # email IDs into the WHERE clause and silently returns no matches.
    if label_param:
        try:
            label_email_ids = _get_inbox_label_email_ids_for_filter(
                account_id,
                label_param,
            )
        except Exception as e:
            logger.warning(
                f"Failed to get label email IDs for '{label_param}': {e}"
            )
            label_email_ids = set()

    # Retour immédiat si le label store ne contient aucun email pour ce label
    # (évite une requête IMAP lente inutile)
    if label_email_ids is not None and not label_email_ids:
        return jsonify({
            "count": 0, "offset": offset, "has_more": False,
            "filter": email_filter, "source": "empty_label", "emails": [],
        })

    if not force_refresh and not skip_memory_cache:
        # === IN-MEMORY CACHE (fastest path) ===
        # When filtering by label, label_email_ids provides the set of matching
        # email IDs — _get_cached_email_response filters the cached list by ID.
        cached_response = _get_cached_email_response(folder, email_filter, limit, offset, label_email_ids, account_id=oauth_account_id, exclude_label_name=exclude_label_param)
        if cached_response:
            # Enrich labels on cache hit — background labeling may have completed
            # since the cache was populated. Check first 5 emails; if all lack labels,
            # fetch fresh labels and merge them into the cached response.
            _cached_emails = cached_response.get("emails", [])
            if _cached_emails and folder != "sent":
                _sample = _cached_emails[:5]
                _has_labels = any(e.get("labels") for e in _sample)
                if not _has_labels:
                    _all_ids = [str(e.get("id", "")) for e in _cached_emails if e.get("id")]
                    _fresh_labels = _get_email_labels_batch(_all_ids, account_id=account_id)
                    if any(_fresh_labels.values()):
                        for e in _cached_emails:
                            _eid = str(e.get("id", ""))
                            if _eid in _fresh_labels and _fresh_labels[_eid]:
                                e["labels"] = _fresh_labels[_eid]
                        logger.info(f"Memory cache hit: enriched labels for {sum(1 for v in _fresh_labels.values() if v)} emails")
            logger.info(f"Memory cache hit: {cached_response['count']} emails")
            return jsonify(cached_response)
    elif force_refresh:
        # Web-first refresh: queue provider work asynchronously and keep serving
        # the existing DB cache. Never clear SQLite here — a hard refresh should
        # not blank the user's inbox while Gmail/Outlook is still syncing.
        _invalidate_folder_cache(folder)
        _invalidate_label_batch_cache()
        if folder in _rh.SECONDARY_SYNC_FOLDERS:
            # The recorded outcome describes the PREVIOUS refresh attempt; a
            # manual retry must report the new attempt's result, not echo the
            # old failure while the fresh job is still running.
            _rh.clear_folder_sync_outcome(account_id, folder)
        _start_background_sync(
            account_id,
            limit,
            unread_only,
            oauth_account_id,
            folder,
            source="force_refresh",
            debounce=False,
        )
        logger.info(
            "Force refresh converted to async sync job (account=%s, folder=%s)",
            account_id,
            folder,
        )

    # === CACHE-FIRST LOADING ===
    # Step 1: Try to load from SQLite cache (fast path <500ms)
    if folder == "sent":
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                # Fresh check (< 2 min) — no revalidation needed
                fresh_emails = repo.get_sent_emails(
                    account_id=account_id,
                    limit=limit + 1,
                    offset=offset,
                    max_age_seconds=120,
                )
                # Stale-while-revalidate: if fresh hit, return immediately.
                # If stale (> 5 min), also return immediately but trigger background refresh.
                cached_emails = fresh_emails or repo.get_sent_emails(
                    account_id=account_id,
                    limit=limit + 1,
                    offset=offset,
                    max_age_seconds=None,  # any age
                )
                if cached_emails:
                    _tc_map = _compute_thread_counts(
                        session, account_id, (ce.thread_id for ce in cached_emails)
                    )
                    email_dicts = []
                    for ce in cached_emails:
                        d = ce.to_dict_headers()
                        raw_id = str(d.get("id", ""))
                        if not raw_id.startswith("sent:"):
                            d["id"] = f"sent:{raw_id}"
                        d["has_pending_draft"] = False
                        d["labels"] = []
                        d["conversation_id"] = ce.thread_id
                        d["thread_count"] = _tc_map.get(ce.thread_id, 1) if ce.thread_id else 1
                        d["body_preview"] = d.pop("snippet", "")
                        if ce.recipients:
                            d["to"] = [r.strip() for r in ce.recipients.split(",") if r.strip()]
                        email_dicts.append(d)

                    has_more = len(email_dicts) > limit
                    emails_to_return = email_dicts[:limit]

                    # Trigger background refresh when cache is stale
                    if not fresh_emails:
                        logger.info("Sent cache stale — returning stale data + queuing background refresh")
                        _start_background_sync(account_id, limit + 1, False, oauth_account_id, "sent")
                    else:
                        logger.info(f"Cache hit: {len(emails_to_return)} sent emails from SQLite (fresh)")

                    return jsonify({
                        "count": len(emails_to_return),
                        "offset": offset,
                        "has_more": has_more,
                        "filter": email_filter,
                        "source": "cache",
                        "emails": emails_to_return,
                    })
        except Exception as cache_error:
            logger.warning(f"Sent cache read failed: {cache_error}, queuing provider sync")

    if folder in ("trash", "archived", "spam", "draft"):
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                # Try fresh cache first (< 2 min)
                fresh_emails = repo.get_by_folder(
                    account_id=account_id,
                    folder=folder,
                    limit=limit + 1,
                    offset=offset,
                    max_age_seconds=120,
                )
                # Stale-while-revalidate: if no fresh data, accept any age
                cached_emails = fresh_emails or repo.get_by_folder(
                    account_id=account_id,
                    folder=folder,
                    limit=limit + 1,
                    offset=offset,
                    max_age_seconds=None,  # any age
                )
                if cached_emails:
                    pending_email_ids = _get_pending_draft_email_ids(account_id=account_id)
                    _tc_map = _compute_thread_counts(
                        session, account_id, (ce.thread_id for ce in cached_emails)
                    )
                    email_dicts = []
                    for ce in cached_emails:
                        d = ce.to_dict_headers()
                        d["has_pending_draft"] = d["id"] in pending_email_ids
                        d["labels"] = []
                        d["conversation_id"] = ce.thread_id
                        d["thread_count"] = _tc_map.get(ce.thread_id, 1) if ce.thread_id else 1
                        d["to"] = [r.strip() for r in ce.recipients.split(",") if r.strip()] if ce.recipients else []
                        snippet = d.pop("snippet", "")
                        if not snippet and ce.body_text:
                            snippet = ce.body_text[:150]
                        d["body_preview"] = snippet
                        email_dicts.append(d)
                    # Enrich with labels (same as inbox path)
                    all_ids = [str(d["id"]) for d in email_dicts]
                    labels_map = _get_email_labels_batch(all_ids, account_id=account_id)
                    for d in email_dicts:
                        d["labels"] = labels_map.get(str(d["id"]), [])
                        d["draft_skipped"] = not d["has_pending_draft"] and any(
                            lb.get("name") == "Noise" for lb in d["labels"]
                        )
                    has_more = len(email_dicts) > limit
                    emails_to_return = email_dicts[:limit]

                    # Trigger background refresh when cache is stale
                    if not fresh_emails:
                        logger.info(f"{folder} cache stale — returning stale data + queuing background refresh")
                        _start_background_sync(account_id, limit + 1, False, oauth_account_id, folder)
                    else:
                        logger.info(f"Cache hit: {len(emails_to_return)} {folder} emails from SQLite (fresh)")

                    return jsonify({
                        "count": len(emails_to_return),
                        "offset": offset,
                        "has_more": has_more,
                        "filter": email_filter,
                        "source": "cache",
                        "emails": emails_to_return,
                    })
                else:
                    # Empty cache is ambiguous: never-synced vs synced-and-empty
                    # vs sync broken. Without the recorded outcome of the last
                    # completed refresh, this fell through to the syncing
                    # response below on EVERY request, so an empty Trash/Spam
                    # (or one whose refresh fails persistently) kept the FE
                    # skeleton ladder (~72 s) re-running forever — "les onglets
                    # Corbeille/Indésirables ne s'ouvrent pas" (2026-06-09).
                    outcome = (
                        _rh.get_folder_sync_outcome(account_id, folder)
                        if folder in _rh.SECONDARY_SYNC_FOLDERS and offset == 0
                        else None
                    )
                    if outcome is not None:
                        # Stale-while-revalidate: keep a (debounced) refresh
                        # going so server-side changes still land.
                        _start_background_sync(account_id, limit + 1, False, oauth_account_id, folder)
                        payload = {
                            "count": 0,
                            "offset": offset,
                            "has_more": False,
                            "filter": email_filter,
                            "source": "cache",
                            "emails": [],
                        }
                        if not outcome.get("ok"):
                            payload["sync_failed"] = True
                        return jsonify(payload)
                    logger.info(f"{folder} cache empty — queueing provider sync")
        except Exception as cache_error:
            logger.warning(f"{folder} cache read failed: {cache_error}, queuing provider sync")

    if folder == "inbox":
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)

                # When filtering by label, push email_ids filter to SQL (fast)
                # inbox-only: label tabs show the same scope as the Inbox tab
                if label_email_ids is not None:
                    if not label_email_ids:
                        # Empty set — no emails match this label, skip SQL query
                        cached_emails = []
                    else:
                        cached_emails = repo.get_by_account(
                            account_id=account_id,
                            limit=limit + 1,
                            offset=offset,
                            unread_only=unread_only,
                            email_ids=label_email_ids,
                        )
                else:
                    # Deferred exclude_label lookup — only resolve IDs when
                    # we actually need them (SQLite path, not memory cache).
                    # Pass account_id so the lookup is scoped to the caller
                    # rather than the process-global current account.
                    if exclude_label_param and exclude_label_ids is None:
                        try:
                            exclude_label_ids = _get_inbox_label_email_ids_for_filter(
                                account_id,
                                exclude_label_param,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to get exclude_label email IDs for '{exclude_label_param}': {e}")

                    # SQL NOT IN already excludes Noise email IDs at the DB level,
                    # so limit+1 is sufficient (no post-filtering needed).
                    cached_emails = repo.get_by_account(
                        account_id=account_id,
                        limit=limit + 1,
                        offset=offset,
                        unread_only=unread_only,
                        exclude_email_ids=exclude_label_ids,
                    )

                # If exclude_label filtered out ALL SQLite results, return empty
                # immediately. Falling through to the provider would fetch the
                # same Noise emails from Gmail API (which may be rate-limited,
                # causing 30+ second hangs). Background sync will discover any
                # new non-Noise emails asynchronously.
                # Distinguish cold-start (account has zero rows in SQLite) from
                # the everything-is-Noise edge case: only the cold-start case
                # should set sync_in_progress so the frontend keeps its
                # skeleton; otherwise the user sees a misleading loader on a
                # legitimately empty inbox.
                if not cached_emails and exclude_label_ids:
                    is_cold_start = (
                        offset == 0
                        and isinstance(account_id, int)
                        and account_id > 0
                        and repo.count_by_account(account_id) == 0
                    )
                    if offset == 0:
                        _start_background_sync(account_id, limit, unread_only, oauth_account_id, "inbox")
                    payload = {
                        "count": 0, "offset": offset, "has_more": False,
                        "filter": email_filter, "source": "cache", "emails": []
                    }
                    if is_cold_start:
                        payload["source"] = "syncing"
                        payload["sync_in_progress"] = True
                    return jsonify(payload)

                # When paginating (offset > 0) and SQLite returns nothing,
                # we've walked off the end of the user's stored emails.
                # The provider would only return *recent* messages we already
                # have — and a 30s+ Gmail roundtrip on every "end of list"
                # check freezes the infinite-scroll loading sentinel.
                if not cached_emails and offset > 0:
                    return jsonify({
                        "count": 0, "offset": offset, "has_more": False,
                        "filter": email_filter, "source": "cache", "emails": []
                    })

                # Serve from cache if we have enough data — better to show some emails
                # instantly than to hang waiting for a slow IMAP connection.
                # Background sync will populate the full inbox asynchronously.
                # When exclude_label filtering is active and the cache has very few
                # results, fall through to the provider which fetches more emails.
                _min_cache_threshold = 3 if (exclude_label_ids and len(exclude_label_ids) > 10) else 1
                if len(cached_emails) >= _min_cache_threshold:
                    # Stale-while-revalidate: serve SQLite data instantly but trigger
                    # background provider sync when data is stale, so the NEXT request
                    # gets fresh emails. Without this, the inbox goes permanently
                    # stale if the daemon stops running.
                    # Check freshness: newest email's created_at vs now
                    _newest_created = max(
                        (getattr(e, 'created_at', None) for e in cached_emails),
                        default=None,
                    )
                    _cache_age_s = (
                        (_cache_time.time() - _newest_created.timestamp())
                        if _newest_created else float('inf')
                    )
                    _cache_stale = _cache_age_s > 120  # > 2 min = stale
                    if _cache_stale and offset == 0:
                        _start_background_sync(account_id, limit, unread_only, oauth_account_id, "inbox")

                    # Label unlabeled emails in background (non-blocking)
                    _rh.submit_background(_label_cached_emails_if_needed, cached_emails, account_id)

                    # Pré-fetcher les bodies manquants en arrière-plan (accélère le premier clic)
                    _inbox_ids = [str(ce.email_id) for ce in cached_emails if ce.email_id]
                    if _inbox_ids:
                        _rh.submit_background(_prefetch_bodies_bg, _inbox_ids, oauth_account_id, account_id)

                    # Auto-reply, follow-ups, secondary folder prefetch (throttled: max once/60s).
                    # S-03 fix: throttle is per-account so accounts don't starve each other.
                    # Prefer oauth_account_id as scope (stable across DB/migrations); fall back
                    # to the int DB id when oauth id is unavailable.
                    _bg_scope_key = oauth_account_id or account_id
                    if offset == 0 and _rh.should_run_bg_jobs(_bg_scope_key):
                        _rh.submit_background(_send_auto_replies_bg, cached_emails, oauth_account_id, account_id)
                        from app.api.quicksteps_scheduler import run_quicksteps_scheduled
                        _rh.submit_background(run_quicksteps_scheduled, oauth_account_id, cached_emails)
                        # Keep inbox listing DB/cache-only. Opportunistic Gmail
                        # folder warming can block the SocketIO runtime long
                        # enough to starve even /api/health.

                    # Get pending draft email IDs for badge display
                    pending_email_ids = _get_pending_draft_email_ids(account_id=account_id)

                    # Add has_pending_draft and labels to each email (batch lookup)
                    email_dicts = [e.to_dict_headers() for e in cached_emails]
                    all_ids = [str(d["id"]) for d in email_dicts]
                    labels_map = _get_email_labels_batch(all_ids, account_id=account_id)
                    draft_info_map = _get_pending_draft_info_map(account_id=account_id)

                    # Enrich IMAP entries: find cross-format duplicates with attachment metadata
                    # IMAP entries may lack attachment data that Gmail API entries have
                    # Only query SQLite when there are IMAP-style numeric IDs missing attachments
                    _imap_no_att = [
                        d for d in email_dicts
                        if not d.get("has_attachments") and str(d.get("id", "")).isdigit()
                    ]
                    if _imap_no_att and len(_imap_no_att) <= 100:
                        _att_keys = {}
                        for d in _imap_no_att:
                            key = f"{d.get('subject', '')}___{(d.get('received_at') or '')[:16]}___{d.get('sender', '')}"
                            _att_keys[key] = d
                        try:
                            from sqlalchemy import select as _sa_sel
                            _att_rows = session.execute(
                                _sa_sel(Email.email_id, Email.subject, Email.date, Email.sender, Email.attachments_meta)
                                .where(Email.attachments_meta.isnot(None), Email.account_id == account_id)
                                .limit(len(_imap_no_att) * 2)
                            ).all()
                            for _ar in _att_rows:
                                _ar_ts = _ar.date.replace(tzinfo=timezone.utc).strftime('%Y-%m-%dT%H:%M') if _ar.date else ''
                                _ar_key = f"{_ar.subject}___{_ar_ts}___{_ar.sender}"
                                if _ar_key in _att_keys:
                                    _att_keys[_ar_key]["has_attachments"] = True
                        except Exception as e:
                            logger.debug(f"Attachment metadata enrichment from SQLite failed: {e}")

                    # Thread counts: single GROUP BY bounded by the page's thread_ids.
                    _thread_count_map = _compute_thread_counts(
                        session, account_id, (em.thread_id for em in cached_emails)
                    )

                    for d, em in zip(email_dicts, cached_emails):
                        d["has_pending_draft"] = d.get("has_pending_draft") or (d["id"] in pending_email_ids)
                        d["labels"] = labels_map.get(str(d["id"]), [])
                        d["conversation_id"] = em.thread_id
                        d["thread_count"] = _thread_count_map.get(em.thread_id, 1) if em.thread_id else 1
                        d["to"] = [r.strip() for r in em.recipients.split(",") if r.strip()] if em.recipients else []
                        d["draft_skipped"] = not d["has_pending_draft"] and any(
                            lb.get("name") == "Noise" for lb in d["labels"]
                        )
                        snippet = d.pop("snippet", "")
                        if not snippet and em.body_text:
                            snippet = em.body_text[:150]
                        d["body_preview"] = snippet
                        info = draft_info_map.get(str(d["id"]), {})
                        d["classification"] = info.get("classification")
                        d["priority"] = info.get("priority", 0)

                    # Deduplicate: pass 1 = exact ID, pass 2 = IMAP/Gmail cross-format
                    seen_ids = set()
                    unique_dicts = []
                    for d in email_dicts:
                        eid = str(d.get("id", ""))
                        if eid and eid not in seen_ids:
                            seen_ids.add(eid)
                            unique_dicts.append(d)

                    # Pass 2: merge IMAP UID / Gmail hex ID pairs (same subject+sender+minute)
                    content_map = {}       # key -> dict
                    content_idx_map = {}   # key -> index in merged_dicts (O(1) replace)
                    merged_dicts = []
                    for d in unique_dicts:
                        subj = d.get("subject", "") or ""
                        sender = d.get("sender", "") or ""
                        ts = (d.get("received_at", "") or "")[:16]
                        key = f"{subj}___{ts}___{sender}"
                        existing = content_map.get(key)
                        if existing is None:
                            content_idx_map[key] = len(merged_dicts)
                            content_map[key] = d
                            merged_dicts.append(d)
                        else:
                            # Merge best fields into winner (prefer hex ID for draft matching)
                            eid = str(d.get("id", ""))
                            is_hex = len(eid) > 10 and not eid.isdigit()
                            existing_id = str(existing.get("id", ""))
                            existing_is_hex = len(existing_id) > 10 and not existing_id.isdigit()
                            if is_hex and not existing_is_hex:
                                # Replace IMAP entry with hex, merge flags
                                d["has_attachments"] = d.get("has_attachments") or existing.get("has_attachments")
                                d["has_pending_draft"] = d.get("has_pending_draft") or existing.get("has_pending_draft")
                                idx = content_idx_map[key]
                                merged_dicts[idx] = d
                                content_map[key] = d
                            else:
                                # Keep existing, merge flags from duplicate
                                existing["has_attachments"] = existing.get("has_attachments") or d.get("has_attachments")
                                existing["has_pending_draft"] = existing.get("has_pending_draft") or d.get("has_pending_draft")
                    email_dicts = merged_dicts

                    # Filter blocked senders
                    email_dicts = _filter_blocked_senders(email_dicts, _get_blocked_senders_set())
                    # Filter spammed senders (inbox only)
                    if folder == "inbox":
                        email_dicts = _filter_spammed_senders(email_dicts, _get_spammed_senders_set(), _get_spammed_domains_set())

                    # SQL already applied label filter + offset + limit
                    has_more = len(email_dicts) > limit
                    emails_to_return = email_dicts[:limit]

                    _t_sqlite_done = _time.time()
                    logger.info(f"Cache hit: {len(emails_to_return)} emails from SQLite in {(_t_sqlite_done-_t_start)*1000:.0f}ms (offset={offset}, label={label_param or 'none'})")
                    return jsonify({
                        "count": len(emails_to_return),
                        "offset": offset,
                        "has_more": has_more,
                        "filter": email_filter,
                        "source": "cache",
                        "emails": emails_to_return,
                    })
        except Exception as cache_error:
            logger.warning(f"Cache read failed: {cache_error}, queuing provider sync")

    _t_cache = _time.time()
    logger.debug("[TIMING] Cache check took: %.0fms", (_t_cache-_t_start)*1000)

    # Cold start: inbox SQLite cache is empty (typically right after
    # onboarding, before the first sync has populated rows). Short-circuit
    # the provider fetch — it would block this HTTP response 3-10s while
    # IMAP/Gmail returns the initial batch. Instead, return [] instantly
    # with sync_in_progress=true so the frontend keeps its skeleton, and
    # kick off a background sync. WebSocket new_email events will trigger
    # the next refresh as emails land in SQLite.
    # This branch is only for the normal first load. A manual force refresh
    # still returns immediately too, but goes through the generic DB-miss path
    # below so the client gets the same provider_touched=false marker.
    if (
        folder == "inbox"
        and offset == 0
        and not force_refresh
        and not label_email_ids
        and not exclude_label_ids
        and isinstance(account_id, int)
        and account_id > 0
    ):
        _start_background_sync(account_id, limit, unread_only, oauth_account_id, "inbox")
        logger.info("Cold-start inbox: returning empty + triggered background sync (account=%s)", account_id)
        return jsonify({
            "count": 0,
            "offset": 0,
            "has_more": False,
            "filter": email_filter,
            "source": "syncing",
            "sync_in_progress": True,
            "provider_touched": False,
            "emails": [],
        })

    # Step 2: DB cache miss. Web reads must never call Gmail/Outlook/IMAP
    # synchronously; queue a provider sync and return immediately.
    if offset == 0:
        _start_background_sync(
            account_id,
            limit,
            unread_only,
            oauth_account_id=oauth_account_id,
            folder=folder,
        )

    logger.info(
        "DB-only email list cache miss: account=%s folder=%s offset=%s force_refresh=%s",
        account_id,
        folder,
        offset,
        force_refresh,
    )
    # Bug Karine 2026-06-09 : ne prétendre `sync_in_progress` que si un sync a
    # réellement pu être enfilé (account_id résolu). Avec le sentinel -1, le
    # frontend bouclait ~72 s de skeleton sur une promesse jamais tenue à
    # chaque visite de Corbeille/Spam.
    _sync_possible = isinstance(account_id, int) and account_id > 0
    return jsonify({
        "count": 0,
        "offset": offset,
        "has_more": False,
        "filter": email_filter,
        "source": "syncing" if _sync_possible else "no_db_account",
        "sync_in_progress": offset == 0 and _sync_possible,
        "provider_touched": False,
        "emails": [],
    })


@api_bp.route("/emails/snoozed", methods=["GET"])
def list_snoozed_emails_legacy():
    """Legacy endpoint for the old snoozed email folder path.

    The supported API is now `/api/emails?folder=snoozed`. Returning the same
    frontend-only empty payload keeps old monitors and clients from falling
    through to `/api/emails/<email_id>` with `email_id='snoozed'`.
    """
    return jsonify({
        "emails": [],
        "count": 0,
        "offset": 0,
        "has_more": False,
        "filter": request.args.get("filter", "all"),
        "source": "frontend-only",
    })


# Outlook categories → standard label mapping (used as fallback when no stored labels)
_OUTLOOK_CATEGORY_MAP = {
    'Agentys-Action':  {'name': 'Action',  'color': '#dc2626'},
    'Agentys-Info':    {'name': 'Info',    'color': '#3b82f6'},
    'Agentys-Noise':   {'name': 'Noise',   'color': '#9ca3af'},
    'Agentys-Bruit':   {'name': 'Noise',   'color': '#9ca3af'},
    'Agentys-Waiting': {'name': 'Waiting', 'color': '#f59e0b'},
    'Agentys-Attente': {'name': 'Waiting', 'color': '#f59e0b'},
}

def _labels_from_outlook_categories(categories: list) -> list:
    """Convertit les catégories Outlook Agentys-* en dicts de labels."""
    result = []
    for cat in (categories or []):
        mapping = _OUTLOOK_CATEGORY_MAP.get(cat)
        if mapping:
            result.append(mapping)
    return result

# Pre-compiled regex patterns for _email_to_dict body preview (avoids 350 re.compile/request)
_RE_STYLE_SCRIPT = re.compile(r'<(style|script)[^>]*>.*?</\1>', re.DOTALL | re.IGNORECASE)
_RE_HTML_TAGS = re.compile(r'<[^>]+>')
_RE_CURLY_BLOCKS = re.compile(r'\{[^}]*\}')
_RE_AT_RULES = re.compile(r'@[\w-]+[^;{]*[;]?')
_RE_IMPORTANT = re.compile(r'!important')
_RE_CSS_PROPS = re.compile(r'\b[\w-]+\s*:\s*[\w%#(),.!\s-]+;')
_RE_CSS_JUNK = re.compile(r'@media|!important|\{|\}|min-width|max-width|display\s*:', re.IGNORECASE)



def _email_to_dict(
    email,
    pending_email_ids: set = None,
    labels_map: dict = None,
    account_id: Optional[int] = None,
) -> dict:
    """Convertit un email en dictionnaire pour la sérialisation JSON.

    `account_id` is only used for the badge fallback when `pending_email_ids`
    is None — keeps the badge scoped to the caller's account.
    """
    # Generate body preview (first 100 chars, stripped of HTML/CSS)
    body_preview = ""
    body = getattr(email, 'body', None)
    if isinstance(body, str) and body:
        clean = body
        # Remove style/script tags and their content
        clean = _RE_STYLE_SCRIPT.sub('', clean)
        # Remove all remaining HTML tags
        clean = _RE_HTML_TAGS.sub(' ', clean)
        # Remove curly-brace blocks (multiple passes for nested braces)
        for _ in range(5):
            prev = clean
            clean = _RE_CURLY_BLOCKS.sub(' ', clean)
            if clean == prev:
                break
        # Remove @-rules (media queries, etc.)
        clean = _RE_AT_RULES.sub(' ', clean)
        # Remove !important
        clean = _RE_IMPORTANT.sub(' ', clean)
        # Remove CSS property patterns (e.g. "display:block;")
        clean = _RE_CSS_PROPS.sub(' ', clean)
        # Collapse whitespace
        clean = _RE_WHITESPACE.sub(' ', clean).strip()
        # If result is still mostly CSS junk, discard it
        if clean and _RE_CSS_JUNK.search(clean):
            clean = ""
        body_preview = clean[:100] + "..." if len(clean) > 100 else clean

    # Get is_read status (handle Mock objects that return MagicMock)
    is_read = getattr(email, 'is_read', False)
    if not isinstance(is_read, bool):
        is_read = False

    # Check if there's a pending draft for this email
    if pending_email_ids is None:
        pending_email_ids = _get_pending_draft_email_ids(account_id=account_id)
    has_pending_draft = email.id in pending_email_ids

    # Get labels for this email (use batch map if available, else individual lookup)
    email_id_str = str(email.id)
    labels = labels_map.get(email_id_str, []) if labels_map is not None else _get_email_labels(email_id_str, account_id=account_id)
    # Fallback: extract from Outlook categories when no stored labels found
    if not labels:
        raw_meta = getattr(email, 'raw_metadata', None)
        if isinstance(raw_meta, dict) and raw_meta.get('categories'):
            labels = _labels_from_outlook_categories(raw_meta['categories'])

    result = {
        "id": email.id,
        "sender": email.sender,
        "sender_name": email.sender_name,
        "subject": email.subject,
        "received_at": _to_iso_utc(email.received_at) if hasattr(email.received_at, 'isoformat') else (email.received_at or ""),
        "has_attachments": email.has_attachments,
        "conversation_id": email.conversation_id,
        "is_read": is_read,
        "body_preview": body_preview,
        "has_pending_draft": has_pending_draft,
        "draft_skipped": not has_pending_draft and any(
            lb.get("name") == "Noise" for lb in labels
        ) if labels else False,
        "labels": labels,
    }

    # Include recipients and CC for reply-all support
    to_list = getattr(email, 'to', None) or getattr(email, 'recipients', None)
    if to_list:
        if isinstance(to_list, str):
            result["to"] = [r.strip() for r in to_list.split(",") if r.strip()]
        else:
            result["to"] = to_list
    cc_list = getattr(email, 'cc', None)
    if cc_list:
        if isinstance(cc_list, str):
            result["cc"] = [r.strip() for r in cc_list.split(",") if r.strip()]
        else:
            result["cc"] = cc_list

    # Expose is_sent so the frontend can identify outgoing messages even when
    # sender fields are empty (e.g. freshly-inserted sent-cache entries).
    is_sent_val = getattr(email, 'is_sent', None)
    if is_sent_val is not None:
        result["is_sent"] = bool(is_sent_val)

    return result


def _is_noise_attachment(att: dict) -> bool:
    """Filter out noise attachments embedded by email services (favicons, tracking pixels)."""
    name = (att.get("filename") or att.get("name") or "").lower()
    if name == "favicon.ico":
        return True
    size = att.get("size", 0) or 0
    if 0 < size < 3072:
        import re as _re_att
        if _re_att.match(r'^(icon|logo|spacer|pixel|tracking|transparent|blank)\b', name, _re_att.IGNORECASE):
            return True
        if _re_att.search(r'\.(gif|png)$', name, _re_att.IGNORECASE) and size < 200:
            return True
    return False


def _filter_noise_attachments(attachments: list) -> list:
    """Return only real (non-noise) attachments."""
    return [a for a in (attachments or []) if not _is_noise_attachment(a)]


def _email_to_full_dict(email, account_id: Optional[int] = None) -> dict:
    """Convertit un email en dictionnaire complet avec body."""
    result = _email_to_dict(email, account_id=account_id)
    # Prefer HTML body for rich content (newsletters, receipts, etc.)
    # Fall back to plain text body if no HTML available
    if hasattr(email, 'body_html') and email.body_html:
        result["body"] = None  # body_html present — no need to duplicate
        result["body_html"] = email.body_html
        result["body_text"] = email.body  # Keep plain text as fallback
    else:
        result["body"] = email.body
        result["body_html"] = None
        result["body_text"] = email.body
    # Include attachment metadata if available on the StandardEmail
    # Filter noise (favicons, tracking pixels) so has_attachments stays consistent
    raw_atts = getattr(email, 'attachments', []) or []
    real_atts = _filter_noise_attachments(raw_atts)
    result["attachments"] = real_atts
    result["has_attachments"] = bool(real_atts)
    return result


def _db_email_to_standard(db_email):
    """Convert a SQLite Email model to a StandardEmail-like object for serialization."""
    from app.interfaces.email_provider import StandardEmail
    import json as _json_db
    _attachments = []
    if db_email.attachments_meta:
        try:
            _attachments = _json_db.loads(db_email.attachments_meta)
            if _attachments and not any(a.get("filename") for a in _attachments):
                _attachments = []
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Failed to parse attachments_meta for email {db_email.email_id}: {e}")
            _attachments = []
    return StandardEmail(
        id=db_email.email_id,
        sender=db_email.sender or "",
        sender_name=db_email.sender_name,
        subject=db_email.subject or "",
        body=db_email.body_text or db_email.snippet or "",
        body_html=db_email.body_html,
        received_at=db_email.date,
        is_read=db_email.is_read if isinstance(db_email.is_read, bool) else False,
        has_attachments=bool(_attachments) or bool(db_email.attachments_meta),
        conversation_id=db_email.thread_id,
        to=db_email.recipients.split(",") if db_email.recipients else [],
        cc=db_email.cc.split(",") if getattr(db_email, 'cc', None) else [],
        attachments=_attachments,
    )


# Caches keyed by account_id so badges don't bleed across users on
# multi-user Railway deployments. Pre-fix (2026-04-25 audit, isolation
# report C-2): both caches were process-globals shared by all callers,
# so user A's pending drafts surfaced as has_pending_draft=True for
# user B for up to 30s. The helpers now accept an explicit account_id;
# None falls back to the legacy scan-all behaviour for boot-time and
# Tauri loopback callers that pre-date JWT resolution — log this path
# at debug so we can spot stragglers.
_pending_draft_ids_cache: dict[Optional[int], dict] = {}
_PENDING_DRAFT_IDS_TTL = 30  # 30 second cache

_pending_draft_info_cache: dict[Optional[int], dict] = {}


def _invalidate_pending_draft_cache(account_id: Optional[int] = None) -> None:
    """Force a refresh of the pending-draft caches.

    `account_id=None` clears every account's entry (used by cleanup-all
    style admin paths). Otherwise only that account's entry is dropped.
    """
    if account_id is None:
        _pending_draft_ids_cache.clear()
        _pending_draft_info_cache.clear()
    else:
        _pending_draft_ids_cache.pop(account_id, None)
        _pending_draft_info_cache.pop(account_id, None)


def _get_pending_draft_info_map(account_id: Optional[int] = None) -> dict:
    """
    Retourne un dict {email_id: {"classification": str|None, "priority": int}}
    pour les drafts en attente du compte `account_id`. Résultat mis en
    cache 30s par compte.
    """
    now = _cache_time.time()
    entry = _pending_draft_info_cache.get(account_id)
    if entry and (now - entry["timestamp"]) < _PENDING_DRAFT_IDS_TTL:
        return entry["data"]
    try:
        store = _rh._get_container().get_pending_draft_store()
        if account_id is not None:
            unsent_drafts = store.get_unsent(account_id=account_id)
        else:
            unsent_drafts = store.get_unsent()
        info: dict = {}
        _PRIORITY_MAP = {"Action": 1, "FYI": 2, "Noise": 3}
        for d in (unsent_drafts or []):
            if d.email_id:
                classification = getattr(d, "classification", None)
                info[d.email_id] = {
                    "classification": classification,
                    "priority": _PRIORITY_MAP.get(classification, 0),
                }
        _pending_draft_info_cache[account_id] = {"data": info, "timestamp": now}
        return info
    except Exception as exc:  # noqa: BLE001
        # Audit B-06 (2026-05-12): silent {} return makes the pending-draft
        # badge disappear without any signal. Log the failure so ops can see
        # transient DB issues; still return {} so the UI keeps rendering.
        logger.warning(
            "[pending-draft-info] lookup failed for account_id=%s: %s",
            account_id, exc,
        )
        return {}


def _get_pending_draft_email_ids(account_id: Optional[int] = None) -> set:
    """
    Get set of email IDs that have unsent AI drafts for `account_id`.

    Returns email IDs for the 50 most recent drafts with status
    PENDING, VALIDATED, or MODIFIED. Limited to 50 to avoid
    badge noise from old accumulated drafts.

    Cross-references draft email_ids against the DB to filter out stale drafts
    whose email_id was reassigned to a different email (IMAP UID reuse).
    Results are cached for 30s per account to avoid repeated DB queries.

    `account_id=None` keeps the legacy scan-all behaviour for callers that
    can't resolve the account (boot, orphan cleanup) — those paths are
    inherently leaky on multi-user installs and should be migrated.
    """
    # Return cached result if fresh
    now = _cache_time.time()
    entry = _pending_draft_ids_cache.get(account_id)
    if entry and (now - entry["timestamp"]) < _PENDING_DRAFT_IDS_TTL:
        return entry["ids"]

    try:
        store = _rh._get_container().get_pending_draft_store()
        # Audit P-002 (2026-04-27): cap fetch at 400 instead of 2000. We dedupe
        # to 200 unique email_ids anyway and this function runs every ~3s on
        # active sessions; loading 2000 drafts/iteration was a measurable hot
        # path with 5k+ pending drafts. 400 is enough headroom for the worst
        # observed dup ratio (~0.5).
        _FETCH_CAP = 400
        if account_id is not None:
            unsent_drafts = store.get_unsent(account_id=account_id, limit=_FETCH_CAP)
        else:
            unsent_drafts = store.get_unsent(limit=_FETCH_CAP)
        if not unsent_drafts:
            _pending_draft_ids_cache[account_id] = {"ids": set(), "timestamp": now}
            return set()

        # Build map of email_id -> expected subject (deduplicated, keep first = most recent)
        draft_map = {}
        for d in unsent_drafts:
            if d.email_id and d.email_id not in draft_map:
                draft_map[d.email_id] = d.email_subject
                if len(draft_map) >= 200:
                    break

        # Cross-reference with DB to filter out stale drafts. When account_id
        # is provided we also constrain the lookup to that account so a draft
        # of user A can't be validated against an email of user B that
        # happens to share the same IMAP UID (cross-provider collisions).
        try:
            from sqlalchemy import select as sa_select
            with _rh.get_db_session() as session:
                email_ids_list = list(draft_map.keys())
                stmt = sa_select(Email.email_id, Email.subject).where(
                    Email.email_id.in_(email_ids_list)
                )
                if account_id is not None:
                    stmt = stmt.where(Email.account_id == account_id)
                rows = session.execute(stmt).all()
                db_subjects = {row.email_id: row.subject for row in rows}

                valid_ids = set()
                for eid, expected_subject in draft_map.items():
                    db_subject = db_subjects.get(eid)
                    if db_subject is None:
                        # Email no longer in DB — draft is orphaned, skip
                        continue
                    # Compare subjects (strip "Re:" prefix for matching)
                    draft_subj = re.sub(r'^Re:\s*', '', expected_subject or '', flags=re.IGNORECASE).strip()
                    db_subj = re.sub(r'^Re:\s*', '', db_subject or '', flags=re.IGNORECASE).strip()
                    if draft_subj == db_subj or not draft_subj:
                        valid_ids.add(eid)
                    else:
                        logger.debug(
                            "Stale draft filtered: email_id=%s, draft_subject_len=%s, db_subject_len=%s",
                            eid, len(expected_subject or ""), len(db_subject or ""),
                        )
                _pending_draft_ids_cache[account_id] = {"ids": valid_ids, "timestamp": now}
                return valid_ids
        except Exception as e:
            logger.warning(f"Draft cross-reference failed, returning all: {e}")
            result = set(draft_map.keys())
            _pending_draft_ids_cache[account_id] = {"ids": result, "timestamp": now}
            return result
    except Exception as exc:  # noqa: BLE001
        # Audit B-08 (2026-05-12): silent set() return hides every pending
        # draft badge from the UI without any operator signal. Log the
        # failure so it surfaces in prod.
        logger.warning(
            "[pending-draft-ids] lookup failed for account_id=%s: %s",
            account_id, exc,
        )
        return set()


# Default account ID for single-account mode (to be replaced by multi-account later)
DEFAULT_ACCOUNT_ID = 1

# Background sync debouncing (prevent rapid sync requests)
_last_sync_time: dict = {}
_secondary_folder_prefetch_last: dict = {}
_sync_lock = threading.Lock()
SYNC_DEBOUNCE_SECONDS = 120
INBOX_BACKGROUND_SYNC_LIMIT = 100
SECONDARY_BACKGROUND_SYNC_LIMIT = 50
PROVIDER_COMPENSATED_FETCH_LIMIT = 150


def _background_sync_limit(limit: int, folder: str = "inbox") -> int:
    """Cap UI-triggered provider refreshes so page reloads don't crawl Gmail."""
    try:
        requested = int(limit)
    except (TypeError, ValueError):
        requested = 0

    cap = (
        INBOX_BACKGROUND_SYNC_LIMIT
        if folder == "inbox"
        else SECONDARY_BACKGROUND_SYNC_LIMIT
    )
    if requested <= 0:
        return cap
    return max(1, min(requested, cap))


def _compensated_fetch_count(offset: int, limit: int) -> int:
    """Fetch extra rows for label filters without jumping straight to 500."""
    return max(
        offset + limit + 1,
        min(offset + limit * 3, PROVIDER_COMPENSATED_FETCH_LIMIT),
    )


def _get_inbox_label_email_ids_for_filter(account_id: int, label_name: str) -> set[str]:
    """Use the same merged label source as the header counters."""
    from app.api.labels import _get_inbox_label_email_ids

    return _get_inbox_label_email_ids(account_id, label_name)


def _sync_emails_to_cache(account_id: int, limit: int = 50, unread_only: bool = False, oauth_account_id: str = "", folder: str = "inbox") -> int:
    """
    Sync emails from provider to SQLite cache (background task).

    Creates a fresh provider instance in the background thread to avoid
    sharing mutable state across threads.

    Args:
        account_id: Account ID for cache storage (DB integer).
        limit: Number of emails to sync.
        unread_only: If True, only sync unread emails.
        oauth_account_id: OAuth hash ID for server-side token lookup.
        folder: Logical folder name (inbox/trash/archived/spam).

    Returns:
        Number of new rows + meaningful updates (read-status, deletions,
        folder moves) — used by ``_run_sync_job`` to populate the
        ``sync_complete`` WS event so the FE can refresh immediately on
        user-triggered folder syncs.
    """
    synced_count_outer = 0
    provider = None
    try:
        # Create a FRESH (non-pooled) provider — background sync needs exclusive
        # connection ownership. Using the pooled provider and then calling
        # authenticate()/disconnect() on it races with concurrent request threads
        # sharing the same instance, causing SSLEOFError.
        if not oauth_account_id:
            logger.error("Background sync: no oauth_account_id — aborting to prevent cross-account contamination")
            return
        try:
            from app.multi_accounts import get_account_manager, create_provider_for_account
            mgr = get_account_manager()
            account = mgr.get_account(oauth_account_id)
            if not account:
                logger.error(f"Background sync: account {oauth_account_id} not found — aborting")
                return
            provider = create_provider_for_account(account)
        except Exception as e:
            logger.error(f"Background sync: OAuth lookup failed for {oauth_account_id}: {e} — aborting to prevent cross-account contamination")
            return

        if not provider.authenticate():
            logger.warning("Background sync: authentication failed")
            return

        # Provider-aware folder resolution (handles Gmail, Outlook, IMAP)
        imap_folder = _resolve_folder_for_provider(provider, folder)

        delta_changes = None
        new_history_id = None
        if folder == "inbox" and not unread_only and hasattr(provider, "get_history_changes"):
            try:
                from app.db.models.account import Account
                with _rh.get_db_session() as session:
                    db_account = session.get(Account, account_id)
                    last_history_id = getattr(db_account, "last_history_id", None)
                if last_history_id:
                    changes = provider.get_history_changes(str(last_history_id), limit=limit)
                    if changes.get("new_history_id") is not None:
                        delta_changes = changes
                        new_history_id = str(changes["new_history_id"])
                        emails = list(changes.get("added") or [])
                        logger.info(
                            "Background sync: Gmail delta fetched %s added emails "
                            "for account=%s",
                            len(emails),
                            account_id,
                        )
                    else:
                        logger.info(
                            "Background sync: Gmail historyId expired for account=%s; "
                            "falling back to full fetch",
                            account_id,
                        )
            except Exception as e:
                logger.warning(
                    "Background sync: Gmail delta failed for account=%s: %s; "
                    "falling back to full fetch",
                    account_id,
                    e,
                )
                delta_changes = None
                new_history_id = None

        if delta_changes is None:
            logger.info(f"Background sync: fetching {limit} emails from {folder} ({imap_folder})")
            if hasattr(provider, 'get_message_headers'):
                emails = provider.get_message_headers(limit=limit, unread_only=unread_only, folder=imap_folder)
            else:
                emails = provider.get_messages(limit=limit, unread_only=unread_only, folder=imap_folder)

        # Disconnect IMAP immediately after fetching — free the connection slot
        if hasattr(provider, 'disconnect'):
            provider.disconnect()
            provider = None

        # Guard: never write with invalid account_id (prevents cross-account contamination)
        if account_id <= 0:
            logger.error(f"Background sync: invalid account_id={account_id} — aborting SQLite writes")
            return

        with _rh.get_db_session() as session:
            repo = _rh.EmailRepository(session)
            synced_count = 0
            new_email_events = []
            persist_content = should_persist_email_content()

            # Batch existence check: 1 query instead of N
            all_email_ids = [email.id for email in emails if email.id]
            existing_ids = set(repo.get_existing_ids(all_email_ids, account_id)) if all_email_ids else set()
            # Batch-fetch the existing rows in 1 query too (deep audit 2026-06-02 F):
            # the loop below used to call repo.get_by_email_id PER already-cached
            # email, re-introducing the N+1 the existence check just eliminated.
            existing_rows = repo.get_by_email_ids(existing_ids, account_id) if existing_ids else {}
            existing_read_ids: list[str] = []
            existing_unread_ids: list[str] = []

            # Chemin delta : les changements lu/non-lu d'emails DÉJÀ en base
            # arrivent via label_changes (UNREAD ajouté/retiré), jamais dans
            # `added`. Les adapters les collectaient mais personne ne les
            # consommait : marquer un email non lu dans Gmail ne resurfaçait
            # jamais dans Agentys (device 2026-07-29). bulk_update_read_status
            # (WHERE IN) ignore les ids inconnus — pas de filtre d'existence.
            if delta_changes is not None:
                for change in delta_changes.get("label_changes") or []:
                    mid = str(change.get("message_id") or "")
                    if not mid:
                        continue
                    if "UNREAD" in (change.get("added") or []):
                        existing_unread_ids.append(mid)
                    elif "UNREAD" in (change.get("removed") or []):
                        existing_read_ids.append(mid)

            for email in emails:
                # Check if email already exists in cache
                if email.id in existing_ids:
                    # Backfill body/snippet/recipients for existing emails missing data
                    db_email = existing_rows.get(email.id)
                    # Bug 2026-06-09 : les lignes écrites avant la normalisation UTC
                    # portent l'heure murale locale (décalées de l'offset du fuseau,
                    # ex: 18:47 stocké pour 22:47 UTC) et ne guériraient jamais —
                    # réaligner sur l'heure provider quand la dérive dépasse 60 s.
                    if db_email is not None:
                        _provider_date = to_naive_utc(getattr(email, 'received_at', None))
                        if cached_date_needs_heal(db_email.date, _provider_date):
                            db_email.date = _provider_date
                            session.flush()
                    is_read = getattr(email, 'is_read', None)
                    if (
                        db_email
                        and isinstance(is_read, bool)
                        and db_email.is_read != is_read
                    ):
                        if is_read:
                            existing_read_ids.append(str(email.id))
                        else:
                            existing_unread_ids.append(str(email.id))

                    if db_email and not db_email.recipients:
                        _to = getattr(email, 'to', None)
                        if _to:
                            db_email.recipients = ",".join(_to)
                            session.flush()
                    if persist_content and db_email and not db_email.snippet:
                        body = getattr(email, 'body', None)
                        if body:
                            if not db_email.body_text:
                                db_email.body_text = body
                            db_email.snippet = body[:200]
                            if db_email.body_html is None:
                                db_email.body_html = getattr(email, 'body_html', None)
                            session.flush()
                            synced_count += 1
                            logger.debug("Backfilled snippet for email %s (body_len=%s)", email.id, len(body))
                        elif db_email.body_text and not db_email.snippet:
                            db_email.snippet = db_email.body_text[:200]
                            session.flush()
                            synced_count += 1
                    continue

                # Create new Email model from StandardEmail
                cached_email = Email(
                    email_id=email.id,
                    account_id=account_id,
                    thread_id=getattr(email, 'conversation_id', None),
                    subject=email.subject,
                    sender=email.sender,
                    sender_name=email.sender_name,
                    recipients=",".join(getattr(email, 'to', None) or []) or None,
                    # Bug 2026-06-09 (liste 14:47 vs fil 18:47) : UTC naïf obligatoire —
                    # la colonne perd l'offset des datetimes aware au round-trip SQLite.
                    date=to_naive_utc(email.received_at) or utc_now_naive(),
                    body_text=getattr(email, 'body', None) if persist_content else None,
                    body_html=(getattr(email, 'body_html', None) or "") if persist_content else None,
                    snippet=(getattr(email, 'body', '')[:200] if getattr(email, 'body', None) else '') if persist_content else None,
                    is_read=getattr(email, 'is_read', False) if isinstance(getattr(email, 'is_read', False), bool) else False,
                    is_starred=False,
                    attachments_meta='[{"has":true}]' if getattr(email, 'has_attachments', False) else None,
                    folder=folder,
                )
                repo.create(cached_email)
                synced_count += 1
                _received_at = cached_email.date
                new_email_events.append({
                    "email_id": email.id,
                    "account_id": account_id,
                    "sender": email.sender,
                    "sender_name": email.sender_name,
                    "subject": email.subject,
                    # Z explicite — un isoformat naïf serait re-interprété comme heure
                    # locale par `new Date()` côté frontend (bug 2026-06-09).
                    "received_at": _to_iso_utc(_received_at) if _received_at else "",
                    "is_read": cached_email.is_read,
                    "has_attachments": bool(getattr(email, "has_attachments", False)),
                    "conversation_id": getattr(email, "conversation_id", None),
                    "body_preview": cached_email.snippet or "",
                    "snippet": cached_email.snippet or "",
                })

            read_status_updates = 0
            if existing_read_ids:
                read_status_updates += repo.bulk_update_read_status(
                    existing_read_ids, True, account_id=account_id,
                )
            if existing_unread_ids:
                read_status_updates += repo.bulk_update_read_status(
                    existing_unread_ids, False, account_id=account_id,
                )

            deleted_count = 0
            folder_updates = 0
            if delta_changes is not None:
                for deleted_id in delta_changes.get("deleted", []) or []:
                    if repo.delete_by_email_id(str(deleted_id), account_id=account_id):
                        deleted_count += 1

                for label_change in delta_changes.get("label_changes", []) or []:
                    msg_id = label_change.get("message_id") or label_change.get("id")
                    if not msg_id:
                        continue
                    added_labels = set(label_change.get("added") or [])
                    removed_labels = set(label_change.get("removed") or [])
                    if "UNREAD" in added_labels:
                        read_status_updates += repo.bulk_update_read_status(
                            [str(msg_id)], False, account_id=account_id,
                        )
                    elif "UNREAD" in removed_labels:
                        read_status_updates += repo.bulk_update_read_status(
                            [str(msg_id)], True, account_id=account_id,
                        )

                    if "TRASH" in added_labels:
                        folder_updates += int(
                            repo.update_folder_by_email_id(
                                str(msg_id), "trash", account_id=account_id,
                            )
                        )
                    elif "SPAM" in added_labels:
                        folder_updates += int(
                            repo.update_folder_by_email_id(
                                str(msg_id), "spam", account_id=account_id,
                            )
                        )
                    elif "TRASH" in removed_labels or "SPAM" in removed_labels:
                        folder_updates += int(
                            repo.update_folder_by_email_id(
                                str(msg_id), "inbox", account_id=account_id,
                            )
                        )

                if new_history_id is not None:
                    from app.db.repositories.account_repository import AccountRepository
                    AccountRepository(session).update_sync_time(
                        account_id,
                        history_id=new_history_id,
                    )

            logger.info(
                "Background sync complete: %s new emails, %s read-status updates, "
                "%s deletions, %s folder updates cached for %s",
                synced_count,
                read_status_updates,
                deleted_count,
                folder_updates,
                folder,
            )
            # Captured for the function's outer return value — feeds the
            # ``new_emails`` field of the ``sync_complete`` WS event.
            synced_count_outer = (
                synced_count + read_status_updates + deleted_count + folder_updates
            )

            # Invalidate in-memory cache so next API call returns fresh data
            if synced_count > 0 or read_status_updates > 0 or deleted_count > 0 or folder_updates > 0:
                _invalidate_folder_cache(folder)
                logger.info(
                    "Background sync: invalidated %s cache "
                    "(%s new, %s read-status updates, %s deletions, %s folder updates)",
                    folder,
                    synced_count,
                    read_status_updates,
                    deleted_count,
                    folder_updates,
                )

                # Notify frontend. New rows need a list refresh; read-status
                # corrections can be patched in place.
                try:
                    if new_email_events:
                        from app.api.websocket import emit_new_email
                        for event_data in new_email_events:
                            emit_new_email(event_data, account_id=account_id)
                        logger.info(
                            "[WS] daemon_event new_email emitted "
                            "(bg sync rows=%s, account=%s)",
                            len(new_email_events),
                            account_id,
                        )
                    else:
                        from app.api.websocket import emit_email_updated
                        for email_id in existing_read_ids:
                            emit_email_updated(email_id, {"is_read": True}, account_id)
                        for email_id in existing_unread_ids:
                            emit_email_updated(email_id, {"is_read": False}, account_id)
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")

    except Exception as e:
        msg = str(e)
        # Auth errors are expected (token expiré, compte déconnecté) — warning only, pas Sentry
        if "Authentification IMAP requise" in msg or "Reconnexion IMAP échouée" in msg:
            logger.warning(f"Background sync: auth unavailable for folder={folder}, skipping ({e})")
        else:
            logger.error(f"Background sync error: {type(e).__name__}: {e}")
    finally:
        if provider and hasattr(provider, 'disconnect'):
            try:
                provider.disconnect()
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

    return synced_count_outer


def _start_background_sync(
    account_id: int,
    limit: int,
    unread_only: bool,
    oauth_account_id: str = "",
    folder: str = "inbox",
    *,
    source: str = "auto",
    debounce: bool = True,
) -> None:
    """
    Start background email sync through the coalescing sync-job queue.

    The queue owns deduplication by ``(account_id, folder)``. A local debounce
    is kept only for the direct fallback path, otherwise a stale debounce entry
    can drop the very job that should wake the UI out of ``syncing``.
    """
    import time

    # Bug Karine 2026-06-09 : un job pour le sentinel -1 ne peut jamais aboutir
    # (la résolution OAuth échoue) et la sync directe de repli récupérait les
    # emails du provider pour les jeter ("invalid account_id=-1 — aborting
    # SQLite writes"). Ne rien enfiler — le resolver self-heal (routes_helpers)
    # recrée la ligne accounts manquante quand c'est possible.
    if not isinstance(account_id, int) or account_id <= 0:
        logger.warning(
            "Background sync skipped: unresolvable account_id=%s (folder=%s)",
            account_id, folder,
        )
        return

    safe_limit = _background_sync_limit(limit, folder)
    if safe_limit != limit:
        logger.debug(
            "Background sync limit capped for %s: requested=%s safe=%s",
            folder, limit, safe_limit,
        )
    debounce_key = (account_id, folder, "queue")
    if debounce:
        with _sync_lock:
            last_sync = _last_sync_time.get(debounce_key, 0)
            now = time.time()
            if now - last_sync < SYNC_DEBOUNCE_SECONDS:
                logger.debug(
                    "Background sync queue debounced for %s (account=%s, last sync %.1fs ago)",
                    folder,
                    account_id,
                    now - last_sync,
                )
                return
            _last_sync_time[debounce_key] = now

    try:
        from app.services.sync_jobs import enqueue_sync_job

        enqueue_sync_job(
            account_id=account_id,
            folder=folder,
            limit=safe_limit,
            unread_only=unread_only,
            source=source,
        )
    except Exception as exc:
        logger.warning(
            "Sync job enqueue failed for account=%s folder=%s, falling back to direct background sync: %s",
            account_id,
            folder,
            exc,
        )
        debounce_key = (account_id, folder, "direct")
        with _sync_lock:
            last_sync = _last_sync_time.get(debounce_key, 0)
            now = time.time()
            if now - last_sync < SYNC_DEBOUNCE_SECONDS:
                logger.debug(
                    "Direct background sync fallback debounced for %s (last sync %.1fs ago)",
                    folder,
                    now - last_sync,
                )
                return
            _last_sync_time[debounce_key] = now
        _rh.submit_background(
            _sync_emails_to_cache,
            account_id,
            safe_limit,
            unread_only,
            oauth_account_id,
            folder,
        )


# ============================================================================
# AUTO-LABELING (Background)
# ============================================================================
_labeling_lock = threading.Lock()
_labeling_in_progress = set()  # email_ids currently being labeled
_labeling_progress = {"total": 0, "done": 0, "failed": 0, "running": False}


def _provider_email_id(email) -> str:
    """Return the provider message ID for any email-like object.

    ORM ``Email`` rows expose ``.id`` (int PK) AND ``.email_id`` (provider
    hash); ``StandardEmail``/adapters expose only ``.id`` (= provider hash).
    Label assignments, WS events and provider APIs are all keyed by the
    provider hash — using the int PK writes orphaned records the UI can
    never read (bug: assignment saved under "2775" instead of the Gmail
    message id, 2026-06-11).
    """
    return str(getattr(email, 'email_id', None) or getattr(email, 'id', '') or '')


def _emit_labeling_activity(event_type: str, account_id: Optional[int], **payload) -> None:
    if not account_id:
        return
    try:
        from app.api.websocket import emit_to_account
        emit_to_account(
            "daemon_event",
            {"type": event_type, **payload},
            account_id,
        )
    except Exception as ws_err:
        logger.debug("Labeling activity emit failed (%s): %s", event_type, ws_err)


def _auto_assign_labels_background(
    emails: list, force: bool = False, account_id: Optional[int] = None
) -> None:
    """
    Assigne automatiquement des labels aux emails en background.

    Utilise LabelEmailUseCase pour assigner des labels basés sur:
    - Règles définies par l'utilisateur
    - Règles apprises des corrections
    - Classification IA (fallback)

    Args:
        emails: Liste d'objets email à labelliser.
        force: If True, re-classify emails even if already assigned
            (but still preserve user corrections).
    """
    try:
        container = _rh._get_container()
        label_store = container.get_label_store(account_id=account_id)

        # Filtrer les emails qui n'ont pas encore d'assignation.
        # ORM `Email` rows have `.id` (int PK) and `.email_id` (provider hash);
        # `StandardEmail` has only `.id` (= provider hash). Prefer `email_id`
        # so downstream code (auto-trigger, label_store) always receives the
        # provider message ID. Without this, late-reclassify paths pass the
        # DB int (e.g. 2941) to Gmail's API → email_fetch_failed.
        emails_to_label = []
        for email in emails:
            email_id = _provider_email_id(email)
            if not email_id:
                continue

            # Skip si déjà en cours de labeling
            with _labeling_lock:
                if email_id in _labeling_in_progress:
                    continue

            # Skip si déjà assigné (unless force mode)
            existing = label_store.get_assignment(email_id)
            if existing:
                if force:
                    # In force mode, only skip user-corrected assignments
                    if existing.assigned_by == "user":
                        continue
                else:
                    continue

            emails_to_label.append(email)

        if not emails_to_label:
            logger.debug("No emails need labeling")
            return

        logger.info(f"Auto-labeling {len(emails_to_label)} emails in background")
        _emit_labeling_activity(
            "labels_classification_started",
            account_id,
            count=len(emails_to_label),
        )

        # Progress tracking
        _labeling_progress["total"] = len(emails_to_label)
        _labeling_progress["done"] = 0
        _labeling_progress["failed"] = 0
        _labeling_progress["running"] = True

        # Marquer comme en cours — provider hash, même clé que le skip-check
        # ci-dessus (str(email.id) = int PK sur les rows ORM → le garde-fou
        # "déjà en cours" ne matchait jamais).
        with _labeling_lock:
            for email in emails_to_label:
                _labeling_in_progress.add(_provider_email_id(email))

        try:
            # Get user email for CC detection — scope to the account being
            # labeled, NOT _accts[0] (audit B-03 2026-05-12: _accts[0] returns
            # the lowest-id active account in the install, which breaks
            # CC/self-sent detection on multi-account installs and leaks
            # classification across accounts).
            _bg_user_email = ""
            try:
                from app.db.database import get_db_session as _bg_get_db
                from app.db.repositories import AccountRepository as _BgAcctRepo
                with _bg_get_db() as _bg_sess:
                    _bg_owner = _BgAcctRepo(_bg_sess).get(account_id)
                    if _bg_owner is not None:
                        _bg_user_email = _bg_owner.email or ""
                    else:
                        logger.warning(
                            "[labeling-bg] no Account row for account_id=%s — "
                            "CC detection will degrade", account_id,
                        )
            except Exception as e:
                logger.warning(
                    "[labeling-bg] account email lookup failed for account_id=%s: %s",
                    account_id, e,
                )
            label_use_case = container.get_label_email_use_case(
                user_email=_bg_user_email, account_id=account_id,
            )

            # Build batch inputs: one pass over all emails to build DomainEmails.
            # execute_batch() runs the full rules-only pipeline per email and
            # batches only the LLM-fallback calls (1 call per 10 emails). For a
            # typical 50-email background sync this collapses 15-30 LLM calls
            # into 2-3 — the single biggest cost saver across the 5 optimizations.
            from app.domain.entities import Email as DomainEmail
            try:
                from app.api.routes_helpers import sender_is_real_contact
            except Exception:
                sender_is_real_contact = lambda *a, **k: False  # noqa: E731

            batch_inputs = []
            input_emails = []  # parallel list — we need to update progress per source email
            for email in emails_to_label:
                try:
                    body = _extract_plaintext_body(email)
                    # Provider hash, PAS l'int PK ORM : l'assignment est persisté
                    # sous DomainEmail.id — str(email.id) sur un row ORM écrivait
                    # un enregistrement orphelin (ex. clé "2775") que ni la liste
                    # ni les compteurs ne relisent jamais.
                    _bg_provider_id = _provider_email_id(email)
                    logger.info("Labeling email %s (%s): body=%d chars",
                                _bg_provider_id, (email.subject or "")[:50], len(body))
                    _bg_to = getattr(email, 'to', None) or getattr(email, 'recipients', None) or ''
                    _bg_cc = getattr(email, 'cc', None) or ''
                    _bg_to_list = _bg_to.split(',') if isinstance(_bg_to, str) and _bg_to else (_bg_to if isinstance(_bg_to, list) else [])
                    _bg_cc_list = _bg_cc.split(',') if isinstance(_bg_cc, str) and _bg_cc else (_bg_cc if isinstance(_bg_cc, list) else [])

                    domain_email = DomainEmail(
                        id=_bg_provider_id,
                        sender=getattr(email, 'sender', ''),
                        subject=getattr(email, 'subject', ''),
                        body=body,
                        recipients=[r.strip() for r in _bg_to_list if r.strip()],
                        cc=[c.strip() for c in _bg_cc_list if c.strip()],
                        received_at=getattr(email, 'received_at', None) or getattr(email, 'date', None),
                    )
                    raw_meta: dict = {}
                    try:
                        raw_meta["sender_is_real_contact"] = sender_is_real_contact(
                            getattr(email, 'account_id', None), getattr(email, 'sender', '')
                        )
                    except Exception:
                        pass
                    # Hydrate classification_headers from the persisted raw_headers
                    # JSON column. Without this the labelizer's RFC noise rules
                    # (List-Unsubscribe → Noise @ 0.95) silently never fire.
                    _stored_headers = getattr(email, 'raw_headers', None)
                    if _stored_headers:
                        try:
                            import json as _json_lbl
                            _parsed_headers = _json_lbl.loads(_stored_headers)
                            if isinstance(_parsed_headers, dict) and _parsed_headers:
                                raw_meta["classification_headers"] = _parsed_headers
                        except (ValueError, TypeError):
                            pass
                    existing = label_store.get_assignment(_bg_provider_id) if force else None
                    batch_inputs.append({
                        "email": domain_email,
                        "existing_assignment": existing,
                        "raw_metadata": raw_meta,
                    })
                    input_emails.append(email)
                except Exception as e:
                    logger.error(f"Error preparing email {getattr(email, 'id', '?')} for labeling: {e}")
                    _labeling_progress["failed"] += 1

            # Single batched execution — 1 LLM call per BATCH_SIZE_DEFAULT (10)
            # deferred emails instead of 1 LLM call per email.
            if batch_inputs:
                try:
                    assignments = label_use_case.execute_batch(batch_inputs)
                except Exception as e:
                    logger.error("execute_batch failed: %s — falling back to per-email execute()", e)
                    assignments = []
                    for inp in batch_inputs:
                        try:
                            assignments.append(label_use_case.execute(
                                inp["email"],
                                existing_assignment=inp.get("existing_assignment"),
                                raw_metadata=inp.get("raw_metadata"),
                            ))
                        except Exception as ex:
                            logger.error("Per-email fallback failed for %s: %s", inp["email"].id, ex)
                            assignments.append(None)

                # Batch the persistence (deep audit 2026-06-02 G): save_assignment
                # rewrites the whole assignments JSON file + opens a fresh DB
                # session per call, so a 10-email LLM batch meant 10 full-file
                # rewrites + 10 transactions. Collect here and persist once. Safe in
                # THIS path because triggers run only after ALL saves (the separate
                # loop below), unlike _sync_label_emails which fires triggers inline.
                # NB: increment_rule_match_counts STAYS per email — it de-dupes its
                # input via a set, so accumulating rule_ids across emails would
                # undercount total_matches; it only rewrites the rules file when a
                # rule actually matched (rare on the LLM path).
                _to_persist = []
                for src_email, assignment in zip(input_emails, assignments):
                    if assignment is None:
                        _labeling_progress["failed"] += 1
                        continue
                    _to_persist.append(assignment)
                    if assignment.matched_rule_ids:
                        try:
                            label_store.increment_rule_match_counts(assignment.matched_rule_ids)
                        except Exception as _inc_err:
                            logger.debug("increment_rule_match_counts failed for %s: %s", src_email.id, _inc_err)
                    logger.debug("Labeled email %s: %s", src_email.id, assignment.labels)
                if _to_persist:
                    try:
                        label_store.save_assignments_batch(_to_persist)
                        _labeling_progress["done"] += len(_to_persist)
                    except Exception as e:
                        logger.error("save_assignments_batch failed: %s", e)
                        _labeling_progress["failed"] += len(_to_persist)

            # Track successful auto-label events for Time Saved panel
            _done = _labeling_progress.get("done", 0)
            if _done > 0:
                try:
                    from app.draft_quality_tracker import get_tracker
                    get_tracker().record_feature("auto_label", count=_done, account_id=str(account_id or ""))
                except Exception as _trk_err:
                    logger.debug(f"Time-saved tracking (auto_label) suppressed: {_trk_err}")

            # Run Quick Steps auto-triggers on freshly synced emails. The
            # daemon path (daemon.py:2196) does this for emails that arrive
            # via background polling, but emails synced through the live API
            # (this code path) were skipping it — meaning the user's
            # auto-enabled Quick Steps (e.g. "Auto-accept meeting invites")
            # never fired on incoming mail while the app was open. Best-
            # effort: per-email, swallow exceptions, never block the
            # labelling response.
            # account_id is passed as a function arg by callers; the per-email
            # objects don't always carry it (DomainEmail wrappers, detached
            # ORM rows). Use the function-scope account_id directly.
            _trigger_aid = 0
            try:
                _trigger_aid = int(account_id) if account_id else 0
            except (TypeError, ValueError):
                _trigger_aid = 0

            if _trigger_aid > 0 and emails_to_label:
                try:
                    from app.quicksteps.auto_trigger import run_auto_triggers
                    logger.info(
                        "auto_trigger: invoking on %d email(s) for account %d",
                        len(emails_to_label), _trigger_aid,
                    )
                    for src_email in emails_to_label:
                        # Same dual-id concern as above: ORM rows expose .id
                        # as the int PK, but auto-trigger / Gmail API need
                        # the provider hash (.email_id on ORM rows).
                        _provider_id = _provider_email_id(src_email)
                        try:
                            run_auto_triggers(
                                _trigger_aid, _provider_id, src_email,
                            )
                        except Exception as _trig_err:
                            logger.warning(
                                "auto_trigger raised for %s: %s",
                                _provider_id or "?", _trig_err,
                            )
                except Exception as _import_err:
                    logger.warning("auto_trigger module import failed: %s", _import_err)
            elif emails_to_label:
                logger.info(
                    "auto_trigger: skipping %d email(s) — no account_id available",
                    len(emails_to_label),
                )
        finally:
            _labeling_progress["running"] = False
            # Retirer de la liste en cours (même clé provider hash qu'à l'ajout)
            with _labeling_lock:
                for email in emails_to_label:
                    _labeling_in_progress.discard(_provider_email_id(email))

            # Invalidate email cache so next request picks up new labels
            if emails_to_label:
                _invalidate_folder_cache("inbox")
                logger.debug("Inbox cache invalidated after labeling %s emails", len(emails_to_label))

            # Emit labels_updated event so frontend can update badges in-place
            if emails_to_label:
                try:
                    from app.api.websocket import get_socketio
                    socketio = get_socketio()
                    if socketio:
                        # Build label map for labeled emails
                        updates = {}
                        for email in emails_to_label:
                            # Provider hash : le FE matche les rows par id provider,
                            # un event keyé sur l'int PK ORM est silencieusement ignoré.
                            eid = _provider_email_id(email)
                            assignment = label_store.get_assignment(eid)
                            if assignment:
                                labels = label_store.get_labels()
                                color_map = {lbl.name: lbl.color for lbl in labels}
                                updates[eid] = [
                                    {"name": n, "color": color_map.get(n, "#6b7280")}
                                    for n in assignment.labels
                                ]
                        if updates:
                            # Isolation multi-compte : router à la room du
                            # compte propriétaire (jamais broadcast).
                            from app.api.websocket import emit_to_account
                            emit_to_account(
                                "daemon_event",
                                {"type": "labels_updated", "updates": updates},
                                account_id,
                            )
                            logger.debug("WebSocket: labels_updated emitted for %s emails (account=%s)", len(updates), account_id)
                except Exception as ws_err:
                    logger.warning(f"Failed to emit labels_updated: {ws_err}")

            # Emit relabel_complete event if force mode was used
            if force and emails_to_label:
                try:
                    from app.api.websocket import emit_to_account
                    emit_to_account(
                        "relabel_complete",
                        {"relabeled": len(emails_to_label)},
                        account_id,
                    )
                    logger.debug("WebSocket: relabel_complete emitted: %s emails (account=%s)", len(emails_to_label), account_id)
                except Exception as ws_err:
                    logger.warning(f"Failed to emit relabel_complete: {ws_err}")

            _emit_labeling_activity(
                "labels_classification_complete",
                account_id,
                count=_labeling_progress.get("done", 0),
                failed=_labeling_progress.get("failed", 0),
            )

    except Exception as e:
        logger.error(f"Auto-labeling error: {type(e).__name__}: {e}")


def _label_cached_emails_if_needed(cached_emails: list, account_id: int | None = None) -> None:
    """
    Label emails from SQLite cache that have no label assignment yet.

    The SyncService stores new emails in SQLite but never labels them.
    This function detects unlabeled emails and runs:
    1. Synchronous built-in rules (instant)
    2. Background LLM fallback for the rest

    account_id is required to scope WebSocket events to the owning account.
    """
    try:
        container = _rh._get_container()
        label_store = container.get_label_store(account_id=account_id)

        # Batch check: single cache load instead of N file reads
        all_ids = [str(e.email_id) for e in cached_emails if e.email_id]
        assignments = label_store.get_assignments_batch(all_ids)
        labeled_ids = set(assignments.keys())

        unlabeled = [e for e in cached_emails if str(e.email_id) not in labeled_ids and e.email_id]

        if not unlabeled:
            return

        logger.info(f"Found {len(unlabeled)} unlabeled emails in SQLite cache, labeling...")

        # Adapt DB Email objects to the interface expected by _sync_label_emails
        # (uses getattr for 'id', 'sender', 'subject', 'body', 'body_html')
        class _EmailAdapter:
            __slots__ = ('id', 'sender', 'sender_name', 'subject', 'body', 'body_html', 'has_attachments', 'conversation_id', 'received_at', 'recipients', 'cc', 'to', 'raw_headers')
            def __init__(self, db_email):
                self.id = db_email.email_id
                self.sender = db_email.sender or ''
                self.sender_name = db_email.sender_name or ''
                self.subject = db_email.subject or ''
                self.body = db_email.body_text or ''
                self.body_html = db_email.body_html or ''
                self.has_attachments = bool(db_email.attachments_meta)
                self.conversation_id = db_email.thread_id
                self.received_at = db_email.date
                self.recipients = db_email.recipients or ''
                self.to = db_email.recipients or ''
                self.cc = db_email.cc or ''
                # Carry the persisted RFC headers so the rules-only pass can fire
                # List-Unsubscribe / Precedence → Noise. Audit 2026-06-13: without
                # this slot the fast inbox-labeling path dropped every RFC signal.
                self.raw_headers = getattr(db_email, 'raw_headers', None)

        adapted = [_EmailAdapter(e) for e in unlabeled]

        # Synchronous built-in rules
        _sync_label_emails(adapted, account_id=account_id)

        # Emit labels_updated for sync-labeled emails so frontend shows labels immediately
        try:
            container = _rh._get_container()
            label_store = container.get_label_store(account_id=account_id)
            all_adapted_ids = [str(a.id) for a in adapted]
            sync_assignments = label_store.get_assignments_batch(all_adapted_ids)
            if sync_assignments:
                labels = label_store.get_labels()
                color_map = {lbl.name: lbl.color for lbl in labels}
                updates = {
                    eid: [{"name": n, "color": color_map.get(n, "#6b7280")} for n in asgn.labels]
                    for eid, asgn in sync_assignments.items()
                    if asgn.labels
                }
                if updates:
                    from app.api.websocket import emit_to_account
                    emit_to_account(
                        "daemon_event",
                        {"type": "labels_updated", "updates": updates},
                        account_id,
                    )
                    logger.debug("Sync-label: labels_updated emitted for %s emails (account=%s)", len(updates), account_id)
        except Exception as ws_err:
            logger.debug("Sync-label: failed to emit labels_updated: %s", ws_err)

        # Background LLM fallback for emails that still have no label
        _start_auto_labeling(adapted, account_id=account_id)

    except Exception as e:
        logger.error(f"Error labeling cached emails: {e}")


def _label_new_emails_bg(account_id: int) -> None:
    """Hook post-sync (bootstrap) : classifie les non-lus inbox fraîchement syncés.

    Constat device 2026-07-16 : la classification ne tournait QUE comme
    bg-job de ``GET /api/emails`` — donc uniquement quand la WEBAPP listait
    l'inbox. Le mobile, qui n'appelle pas ``/api/emails`` tant que les
    compteurs sont à 0, restait à « 0 à traiter » dès que la webapp était
    fermée (51 non-lus inbox jamais classés sur le compte principal). Ce
    hook rend la classification pilotée par l'ARRIVÉE des emails, pas par
    la navigation web.

    Idempotent et borné : ``_label_cached_emails_if_needed`` re-filtre les
    emails déjà labellisés (rules d'abord, LLM en fallback) ; on ne charge
    que les 200 non-lus inbox les plus récents.
    """
    try:
        from app.db.database import get_db_session
        from app.db.models.email import Email

        with get_db_session() as session:
            recent = (
                session.query(Email)
                .filter(
                    Email.account_id == account_id,
                    Email.is_read.is_(False),
                    Email.is_sent.is_(False),
                )
                .filter((Email.folder == "inbox") | (Email.folder.is_(None)))
                .order_by(Email.date.desc())
                .limit(200)
                .all()
            )
            if recent:
                _label_cached_emails_if_needed(recent, account_id)
    except Exception as e:
        logger.warning("[LABEL-SYNC] post-sync labeling failed for account %s: %s", account_id, e)


def _prefetch_bodies_bg(email_ids: list, oauth_account_id: str, account_id: int | None = None) -> None:
    """
    Pré-fetche les bodies HTML des emails manquants en arrière-plan.

    Quand la liste inbox est servie depuis le cache SQLite (headers-only),
    les emails ont body_html=None. Ce thread les charge via le provider
    et persiste en SQLite — ainsi le prochain clic sera <10ms (cache chaud).

    Args:
        email_ids: IDs des emails à vérifier (max 10 traités).
        oauth_account_id: ID compte pour le provider.
        account_id: DB int account_id pour scoper les lookups SQLite (CASA P1-8 —
            prévient les fuites cross-tenant quand 2 comptes partagent un IMAP UID).
            None = caller legacy sans account_id résolu (fallback no-op).
    """
    if not should_persist_email_content():
        logger.debug("[PREFETCH] skipped in metadata-only mode")
        return

    try:
        # Trouver les emails avec body_html IS NULL
        with _rh.get_db_session() as session:
            from app.db.models import Email as _EmailModel
            from sqlalchemy import select as _select
            stmt = _select(_EmailModel).where(
                _EmailModel.email_id.in_(email_ids),
                _EmailModel.body_html == None,  # noqa: E711
            )
            if account_id is not None:
                stmt = stmt.where(_EmailModel.account_id == account_id)
            stmt = stmt.limit(10)
            missing = list(session.scalars(stmt).all())

        if not missing:
            return

        missing_ids = [e.email_id for e in missing]
        logger.info(f"[PREFETCH] {len(missing_ids)} emails sans body — démarrage prefetch")

        from app.providers.factory import get_pooled_provider as _get_provider
        bp = _get_provider(account_id=oauth_account_id) if oauth_account_id else _get_provider()
        if not bp.authenticate():
            logger.warning("[PREFETCH] Authentification échouée, prefetch annulé")
            return

        updated = 0
        for email_id in missing_ids:
            try:
                # Vérifier le cache mémoire d'abord
                cached = _get_cached_email_detail(email_id)
                if cached and cached.get("body_html") is not None:
                    continue

                em = bp.get_message_by_id(email_id)
                if not em:
                    continue

                with _rh.get_db_session() as sess:
                    from app.db.repositories.email_repository import EmailRepository as _EmailRepo
                    repo = _EmailRepo(sess)
                    # CASA P1-8: account_id threaded through from caller (line 950)
                    # to scope the lookup. None means caller didn't have it (legacy
                    # path) — repo treats None as no-op filter.
                    db_em = repo.get_by_email_id(email_id, account_id=account_id)
                    if db_em:
                        body_html = getattr(em, 'body_html', None)
                        db_em.body_html = body_html if body_html is not None else ""
                        if not db_em.body_text:
                            db_em.body_text = getattr(em, 'body', None)
                        if not db_em.snippet and db_em.body_text:
                            db_em.snippet = db_em.body_text[:200]
                        sess.flush()
                        updated += 1
                        logger.info(f"[PREFETCH] body chargé pour {email_id}")
            except Exception as e:
                logger.debug(f"[PREFETCH] Échec pour {email_id}: {e}")

        if hasattr(bp, 'disconnect'):
            bp.disconnect()

        if updated > 0:
            logger.info(f"[PREFETCH] {updated}/{len(missing_ids)} bodies persistés en SQLite")
    except Exception as e:
        # S-16 fix: keep traceback for ops debugging.
        logger.warning(f"[PREFETCH] Erreur prefetch arrière-plan: {e}", exc_info=True)


def _prefetch_secondary_folders_bg(oauth_account_id: str, account_id: int) -> None:
    """
    Pré-fetche les headers sent/trash/archived en arrière-plan lors du chargement inbox.

    Spawné silencieusement quand GET /api/emails?folder=inbox&offset=0 est servi.
    Réchauffe le cache SQLite AVANT que l'utilisateur clique sur ces dossiers.
    Résultat : premier clic sur Envoyés/Corbeille/Archives = <200ms (cache hit).

    Args:
        oauth_account_id: ID compte OAuth pour le provider.
        account_id: ID compte interne (pour SQLite).
    """
    _PREFETCH_TTL = 3600  # Skip si SQLite frais depuis moins d'1h
    _PREFETCH_LIMIT = 10  # Keep folder warming cheap enough for Gmail quotas

    _FOLDERS_TO_PREFETCH = ["sent", "trash", "archived", "spam"]

    try:
        from app.providers.factory import get_pooled_provider as _get_prov
        provider = _get_prov(account_id=oauth_account_id) if oauth_account_id else _get_prov()
        if not provider.authenticate():
            logger.warning("[PREFETCH_FOLDER] Authentification échouée — prefetch annulé")
            return
    except Exception as e:
        logger.warning(f"[PREFETCH_FOLDER] Provider init failed: {e}")
        return

    # Resolve folder names for this provider (handles Gmail, Outlook, IMAP)
    folders_to_prefetch = []
    for folder_name in _FOLDERS_TO_PREFETCH:
        if folder_name == "sent":
            folders_to_prefetch.append((folder_name, None))
        else:
            resolved = _resolve_folder_for_provider(provider, folder_name)
            folders_to_prefetch.append((folder_name, resolved))

    for folder_name, imap_folder in folders_to_prefetch:
        try:
            attempt_key = (account_id, folder_name)
            now = _cache_time.time()
            last_attempt = _secondary_folder_prefetch_last.get(attempt_key, 0)
            if now - last_attempt < _PREFETCH_TTL:
                logger.debug(f"[PREFETCH_FOLDER] {folder_name} tentative récente — skip")
                continue
            _secondary_folder_prefetch_last[attempt_key] = now

            # Vérifier fraîcheur SQLite — skip si déjà frais
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                if folder_name == "sent":
                    existing = repo.get_sent_emails(
                        account_id=account_id,
                        limit=1,
                        max_age_seconds=_PREFETCH_TTL,
                    )
                else:
                    existing = repo.get_by_folder(
                        account_id=account_id,
                        folder=folder_name,
                        limit=1,
                        max_age_seconds=_PREFETCH_TTL,
                    )
            if existing:
                logger.debug(f"[PREFETCH_FOLDER] {folder_name} déjà frais — skip")
                continue

            # Fetch headers depuis IMAP
            if folder_name == "sent":
                if not hasattr(provider, 'get_sent_emails'):
                    continue
                emails = provider.get_sent_emails(limit=_PREFETCH_LIMIT)
                for e in emails:
                    if not str(getattr(e, 'id', '')).startswith("sent:"):
                        e.id = f"sent:{e.id}"
            else:
                if hasattr(provider, 'get_message_headers'):
                    emails = provider.get_message_headers(
                        limit=_PREFETCH_LIMIT,
                        unread_only=False,
                        folder=imap_folder,
                    )
                else:
                    emails = provider.get_messages(
                        limit=_PREFETCH_LIMIT,
                        unread_only=False,
                        folder=imap_folder,
                    )

            if not emails:
                logger.debug(f"[PREFETCH_FOLDER] {folder_name} — aucun email retourné")
                continue

            # Persister en SQLite
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                saved = 0
                persist_content = should_persist_email_content()
                for email_obj in emails:
                    eid = str(getattr(email_obj, 'id', ''))
                    raw_eid = eid[5:] if eid.startswith("sent:") else eid
                    if not raw_eid:
                        continue
                    cached_email = Email(
                        email_id=raw_eid,
                        account_id=account_id,
                        thread_id=getattr(email_obj, 'conversation_id', None),
                        subject=email_obj.subject,
                        sender=email_obj.sender,
                        sender_name=email_obj.sender_name,
                        recipients=",".join(getattr(email_obj, 'to', []) or []),
                        # Bug 2026-06-09 : même normalisation UTC naïf que les autres writers.
                        date=to_naive_utc(getattr(email_obj, 'received_at', None)) or utc_now_naive(),
                        body_text=getattr(email_obj, 'body', None) if persist_content else None,
                        body_html=(getattr(email_obj, 'body_html', None) or "") if persist_content else None,
                        snippet=(getattr(email_obj, 'body', '')[:200] if getattr(email_obj, 'body', None) else '') if persist_content else None,
                        is_read=getattr(email_obj, 'is_read', True),
                        is_starred=getattr(email_obj, 'is_starred', False),
                        is_sent=(folder_name == "sent"),
                        folder=None if folder_name == "sent" else folder_name,
                        attachments_meta='[{"has":true}]' if getattr(email_obj, 'has_attachments', False) else None,
                    )
                    # CASA P1-8: scope by account_id (already in scope from fn signature)
                    existing = repo.get_by_email_id(raw_eid, account_id=account_id)
                    if existing:
                        # Update headers only — don't overwrite body if already fetched
                        existing.subject = cached_email.subject
                        existing.sender = cached_email.sender
                        existing.sender_name = cached_email.sender_name
                        existing.recipients = cached_email.recipients
                        existing.date = cached_email.date
                        # Fix #77: update folder so emails moved to spam/trash/archived
                        # after the initial inbox sync are no longer shown in inbox.
                        if folder_name != "sent":
                            existing.folder = folder_name
                        saved += 1
                    else:
                        try:
                            repo.create(cached_email)
                            saved += 1
                        except Exception:
                            session.rollback()
                session.commit()
                logger.info(f"[PREFETCH_FOLDER] {saved} headers chargés pour {folder_name}")

            # After caching sent headers, prefetch bodies in same flow
            if folder_name == "sent":
                try:
                    _prefetch_sent_bodies(account_id)
                except Exception as pf_err:
                    logger.debug(f"[PREFETCH_FOLDER] sent body prefetch failed: {pf_err}")

        except Exception as e:
            logger.warning(f"[PREFETCH_FOLDER] Erreur pour {folder_name}: {e}")

    try:
        if hasattr(provider, 'disconnect'):
            provider.disconnect()
    except Exception as e:
        logger.debug(f"Suppressed: {e}")


def _strip_html_to_text(html: str) -> str:
    """Strip HTML to plain text using pre-compiled regexes."""
    text = _RE_STYLE_TAG.sub('', html)
    text = _RE_HTML_TAG.sub(' ', text)
    return _RE_WHITESPACE.sub(' ', text).strip()


def _looks_like_calendar_invite(body_text: str, body_html: str, attachments_meta: str) -> bool:
    """Quick check: does this email content look like a meeting invitation?

    Mirrors the rule in label_email.py:443 (0-cal-ics) — same patterns,
    ASCII-only so mangled UTF-8 from Hotmail invites still matches. Used
    by the lazy body-fetch path to decide whether to re-classify an email
    that was originally labelled with body=0 (the body and attachments_meta
    only land in the DB once the lazy fetch completes).
    """
    blob = ((body_text or "") + " " + (body_html or "")).lower()
    meta = (attachments_meta or "").lower()
    if ".ics" in meta or "text/calendar" in blob or "begin:vcalendar" in blob:
        return True
    # Booking-tool confirmations (Calendly) carry no iCal — the appointment
    # details live in HTML. Trigger the body fetch so extract_meeting_from_body
    # can build an appointment card (add-to-calendar / reschedule / cancel).
    if "calendly.com" in blob or "powered by calendly" in blob or "alimenté par calendly" in blob:
        return True
    if any(s in blob for s in (
        "microsoft teams", "google meet", "zoom meeting", "webex meeting",
        "join the meeting", "meeting id:", "meeting id :",
    )):
        return True
    if any(s in blob for s in (
        "teams.microsoft.com/l/meetup-join", "teams.microsoft.com/l/meetup",
        "teams.microsoft.com/meet/", "teams.live.com/meet/",
        "join.microsoft.com/meet/", "meet.google.com/",
        "zoom.us/j/", "zoom.us/meeting", "webex.com/meet", "webex.com/join",
    )):
        return True
    return False


def _extract_plaintext_body(email_obj) -> str:
    """Return the best plain-text body for label classification.

    Falls back to stripping body_html when body is empty/whitespace, and
    strips HTML tags when the body field itself contains HTML markup.
    """
    import re as _re
    body = getattr(email_obj, 'body', '') or ''
    if not body.strip():
        body_html = getattr(email_obj, 'body_html', '') or ''
        if body_html:
            body = _re.sub(r'<style[^>]*>.*?</style>', '', body_html, flags=_re.DOTALL)
            body = _re.sub(r'<script[^>]*>.*?</script>', '', body, flags=_re.DOTALL)
            body = _re.sub(r'<[^>]+>', ' ', body)
            body = _re.sub(r'&nbsp;|&amp;|&lt;|&gt;|&#\d+;', ' ', body)
            body = _re.sub(r'\s+', ' ', body).strip()
    elif '<html' in body.lower()[:200] or '<div' in body.lower()[:500] or '<table' in body.lower()[:500]:
        body = _re.sub(r'<style[^>]*>.*?</style>', '', body, flags=_re.DOTALL)
        body = _re.sub(r'<script[^>]*>.*?</script>', '', body, flags=_re.DOTALL)
        body = _re.sub(r'<[^>]+>', ' ', body)
        body = _re.sub(r'&nbsp;|&amp;|&lt;|&gt;|&#\d+;', ' ', body)
        body = _re.sub(r'\s+', ' ', body).strip()
    return body


def _sync_label_emails(emails: list, account_id: int | None = None) -> None:
    """
    Synchronous labeling using built-in rules only (instant, no LLM).
    Called BEFORE building the API response so labels are immediately available.
    """
    try:
        container = _rh._get_container()
        label_store = container.get_label_store(account_id=account_id)

        # Get user email for CC detection — scope to the account being
        # labeled, NOT _accts[0]. See audit B-02 (2026-05-12): the previous
        # _accts[0] fallback returned the lowest-id active account, which
        # leaks the "is the user in CC" check across accounts on multi-account
        # installs.
        _user_email = ""
        try:
            from app.db.repositories import AccountRepository
            with _rh.get_db_session() as _sess:
                _owner = AccountRepository(_sess).get(account_id)
                if _owner is not None:
                    _user_email = _owner.email or ""
                else:
                    logger.warning(
                        "[labeling-sync] no Account row for account_id=%s — "
                        "CC detection will degrade", account_id,
                    )
        except Exception as e:
            logger.warning(
                "[labeling-sync] account email lookup failed for account_id=%s: %s",
                account_id, e,
            )

        # Collect email IDs for batch lookup (fix N+1)
        email_map = {}  # email_id -> email object
        for email in emails:
            email_id = str(getattr(email, 'id', ''))
            if email_id:
                email_map[email_id] = email

        if not email_map:
            return

        # Batch lookup: 1 query instead of N
        existing_assignments = label_store.get_assignments_batch(list(email_map.keys()))

        for email_id, email in email_map.items():
            # Skip if already assigned
            if email_id in existing_assignments:
                continue

            try:
                from app.domain.entities import Email as DomainEmail
                from app.application.label_email import LabelEmailUseCase

                body = getattr(email, 'body', '') or ''
                if not body.strip():
                    body_html = getattr(email, 'body_html', '') or ''
                    if body_html:
                        body = _strip_html_to_text(body_html)
                else:
                    body_lower = body[:500].lower()
                    if '<html' in body_lower[:200] or '<div' in body_lower:
                        body = _strip_html_to_text(body)

                # Normalize cc/recipients from any email-like object
                _to_raw = getattr(email, 'to', None) or getattr(email, 'recipients', None) or ''
                _cc_raw = getattr(email, 'cc', None) or ''
                _to_list = _to_raw.split(',') if isinstance(_to_raw, str) and _to_raw else (_to_raw if isinstance(_to_raw, list) else [])
                _cc_list = _cc_raw.split(',') if isinstance(_cc_raw, str) and _cc_raw else (_cc_raw if isinstance(_cc_raw, list) else [])

                domain_email = DomainEmail(
                    id=email_id,
                    sender=getattr(email, 'sender', ''),
                    subject=getattr(email, 'subject', ''),
                    body=body,
                    recipients=[r.strip() for r in _to_list if r.strip()],
                    cc=[c.strip() for c in _cc_list if c.strip()],
                )

                # Hydrate RFC classification headers (List-Unsubscribe /
                # Precedence / Auto-Submitted) + real-contact signal so the
                # rules-only pass can fire the decisive newsletter→Noise rule
                # and the contact floor. Audit 2026-06-13: this fast path
                # previously passed NO raw_metadata, silently disabling every
                # RFC header rule and letting newsletters leak to Action/Info.
                _rules_meta: dict = {}
                _stored_headers = getattr(email, 'raw_headers', None)
                if _stored_headers:
                    try:
                        import json as _json_hdr
                        _parsed = _json_hdr.loads(_stored_headers) if isinstance(_stored_headers, str) else _stored_headers
                        if isinstance(_parsed, dict) and _parsed:
                            _rules_meta["classification_headers"] = _parsed
                    except (ValueError, TypeError):
                        pass
                try:
                    from app.api.routes_helpers import sender_is_real_contact as _sirc
                    _rules_meta["sender_is_real_contact"] = _sirc(
                        account_id, getattr(email, 'sender', '')
                    )
                except Exception:
                    pass

                # Try built-in rules only (no LLM) for instant labeling
                assignment = LabelEmailUseCase.classify_by_rules_only(
                    domain_email, label_store, user_email=_user_email,
                    raw_metadata=_rules_meta or None,
                )
                if assignment:
                    label_store.save_assignment(assignment)
                    if assignment.matched_rule_ids:
                        label_store.increment_rule_match_counts(assignment.matched_rule_ids)
                    _invalidate_label_batch_cache()
                    logger.debug("Sync-labeled email %s: %s", email_id, assignment.labels)
                    # Run Quick Step auto-triggers — without this, sync-labelled
                    # emails (the fast path) would write the assignment then exit
                    # without firing user rules, and `_auto_assign_labels_background`
                    # would later skip them as "already assigned" — meaning the
                    # `has_label` triggers (e.g. VIP PIN) NEVER fired on emails
                    # that the rules-only path could handle.
                    if account_id and account_id > 0:
                        try:
                            from app.quicksteps.auto_trigger import run_auto_triggers
                            run_auto_triggers(int(account_id), email_id, domain_email)
                        except Exception as _trig_err:
                            logger.warning(
                                "auto_trigger raised for sync-labeled %s: %s",
                                email_id, _trig_err,
                            )

            except Exception as e:
                logger.warning("Sync-labeling skipped for %s: %s", email_id, e)

    except Exception as e:
        logger.error(f"Sync-labeling error: {e}")


def _start_auto_labeling(emails: list, account_id: Optional[int] = None) -> None:
    """
    Lance l'auto-labeling en background thread (LLM fallback).
    Only processes emails that weren't labeled by _sync_label_emails.

    Args:
        emails: Liste d'emails à labelliser.
        account_id: Compte propriétaire (pour router les events WebSocket
            uniquement à ce compte — isolation multi-compte).
    """
    if not emails:
        return

    # Résolution de l'account_id pour les events WS (propagation à travers
    # le background thread qui n'a pas de request context).
    if account_id is None:
        try:
            account_id = _rh._resolve_account_id_for_user()
        except Exception:
            account_id = None
    _rh.submit_background(_auto_assign_labels_background, emails, False, account_id)


def _compute_thread_counts(session, account_id: int, thread_ids) -> dict[str, int]:
    """Return {thread_id: message_count} for the given thread_ids on this account.

    Single GROUP BY against ix_emails_thread_account_date (indexed), so cost
    is ~O(k log n) where k = unique thread_ids on the page (~20-50). Safe to
    call on every list request.

    Synthetic ``compose-*`` rows (transient placeholders written at send-time
    before the provider's real message id arrives) are excluded from the
    count so the badge stays consistent with the thread-detail view, which
    fetches by provider thread id and never sees the placeholder.
    """
    ids = {tid for tid in thread_ids if tid}
    if not ids:
        return {}
    try:
        from sqlalchemy import func as _sa_func, select as _sa_sel
        rows = session.execute(
            _sa_sel(Email.thread_id, _sa_func.count(Email.id))
            .where(
                Email.account_id == account_id,
                Email.thread_id.in_(ids),
                ~Email.email_id.like("compose-%"),
                ~Email.email_id.like("reply-%"),
            )
            .group_by(Email.thread_id)
        ).all()
        return {tid: cnt for tid, cnt in rows if tid}
    except Exception as e:
        logger.debug(f"Thread count aggregation failed: {e}")
        return {}


def _is_synthetic_thread_email(email) -> bool:
    """Return True for immediate-send placeholders stored before provider sync."""
    email_id = getattr(email, "id", None) or getattr(email, "email_id", None)
    return bool(email_id) and str(email_id).startswith(("compose-", "reply-"))


def _thread_cache_needs_provider_refresh(thread_emails, requested_email_id: str) -> bool:
    """Detect cache states that are useful for speed but unsafe for full thread views."""
    if not thread_emails:
        return True

    raw_requested_id = requested_email_id[5:] if requested_email_id.startswith("sent:") else requested_email_id
    cached_ids = {
        str(getattr(email, "id", None) or getattr(email, "email_id", None) or "")
        for email in thread_emails
    }
    if raw_requested_id not in cached_ids:
        return True

    return any(_is_synthetic_thread_email(email) for email in thread_emails)


def _thread_content_key(email) -> tuple:
    received_at = getattr(email, "received_at", None)
    if isinstance(received_at, datetime):
        minute = received_at.replace(second=0, microsecond=0)
    elif received_at:
        minute = str(received_at)[:16]
    else:
        minute = None
    recipients = getattr(email, "to", None) or getattr(email, "recipients", None) or []
    if isinstance(recipients, (list, tuple, set)):
        recipients_key = ",".join(str(item).strip().lower() for item in recipients if item)
    else:
        recipients_key = str(recipients).strip().lower()
    return (
        (getattr(email, "subject", "") or "").strip().lower(),
        (getattr(email, "sender", "") or "").strip().lower(),
        recipients_key,
        minute,
    )


def _merge_provider_thread_with_cache(provider_thread, cached_thread):
    """Prefer provider rows, keeping only synthetic placeholders not yet synced."""
    merged = list(provider_thread or [])
    provider_ids = {
        str(getattr(email, "id", None) or getattr(email, "email_id", None) or "")
        for email in merged
    }
    provider_keys = {_thread_content_key(email) for email in merged}

    for cached_email in cached_thread or []:
        cached_id = str(
            getattr(cached_email, "id", None)
            or getattr(cached_email, "email_id", None)
            or ""
        )
        if cached_id in provider_ids:
            continue
        if _is_synthetic_thread_email(cached_email) and _thread_content_key(cached_email) in provider_keys:
            continue
        merged.append(cached_email)
    return merged


def _get_email_labels_batch(email_ids: list, account_id: int | None = None) -> dict:
    """
    Batch-récupère les labels pour une liste d'emails (1 cache load au lieu de N file reads).
    Résultat mis en cache 60s pour éviter les re-lectures SQLite sur chaque /api/emails.

    Returns:
        Dict email_id -> list of label dicts.
    """
    if not email_ids:
        return {}

    cached = _get_label_batch_cached(email_ids)
    if cached is not None:
        return cached

    result = {eid: [] for eid in email_ids}
    try:
        container = _rh._get_container()
        label_store = container.get_label_store(account_id=account_id)
        labels = label_store.get_labels()
        label_colors = {label.name: label.color for label in labels}

        # Single batch lookup instead of N individual get_assignment() calls
        assignments = label_store.get_assignments_batch(email_ids)

        for email_id, assignment in assignments.items():
            for label_name in assignment.labels:
                label_info = {
                    "name": label_name,
                    "color": label_colors.get(label_name, "#6b7280"),
                }
                if label_name in assignment.confidences:
                    label_info["confidence"] = assignment.confidences[label_name]
                result[email_id].append(label_info)

        _set_label_batch_cached(email_ids, result)
    except Exception as e:
        logger.error(f"Error batch-getting labels: {e}")
    return result


def _get_email_labels(email_id: str, account_id: int | None = None) -> list:
    """
    Récupère les labels assignés à un email avec leurs couleurs.

    Args:
        email_id: ID de l'email.

    Returns:
        Liste de dicts avec name, color et optionnellement confidence.
    """
    try:
        container = _rh._get_container()
        label_store = container.get_label_store(account_id=account_id)
        assignment = label_store.get_assignment(email_id)
        if assignment:
            # Get label definitions to include colors
            labels = label_store.get_labels()
            label_colors = {label.name: label.color for label in labels}

            result = []
            for label_name in assignment.labels:
                label_info = {
                    "name": label_name,
                    "color": label_colors.get(label_name, "#6b7280"),  # Default grey
                }
                # Include confidence if available
                if label_name in assignment.confidences:
                    label_info["confidence"] = assignment.confidences[label_name]
                result.append(label_info)
            return result
    except Exception as e:
        logger.error(f"Error getting labels for {email_id}: {e}")
    return []



def _fetch_sent_body_bg(email_id: str, raw_email_id: str, account_id: int | None = None) -> None:
    """Background: fetch sent email body from IMAP and update cache/SQLite.

    Args:
        account_id: DB int account_id to scope the SQLite lookup (CASA P1-8).
            None = caller didn't have it (no-op filter at repo level).
    """
    try:
        if not account_id or account_id <= 0:
            logger.warning("Sent body bg fetch skipped without account_id for %s", email_id)
            return
        from app.providers.factory import get_pooled_provider
        oauth_account_id = _rh._resolve_oauth_account_id_for_db_account(account_id)
        if not oauth_account_id:
            logger.warning("Sent body bg fetch skipped: no OAuth account for %s", account_id)
            return
        provider = get_pooled_provider(account_id=oauth_account_id)
        import os as _os
        _imap_host = (_os.getenv("IMAP_HOST") or "").lower()
        sent_folders = ["[Gmail]/Sent Mail", "Sent"] if "gmail" in _imap_host else                        ["Sent", "Sent Items", "INBOX.Sent", "[Gmail]/Sent Mail", "Sent Messages"]
        email_obj = None
        for sf in sent_folders:
            try:
                email_obj = provider.get_message_by_id(raw_email_id, folder=sf)
                if email_obj:
                    break
            except (TypeError, Exception):
                continue
        if not email_obj:
            return
        # Update in-memory cache
        full_dict = _email_to_full_dict(email_obj)
        full_dict["id"] = email_id
        full_dict["labels"] = []
        _set_cached_email_detail(email_id, full_dict, account_id=account_id)
        # Persist body to SQLite
        if should_persist_email_content():
            try:
                with _rh.get_db_session() as session:
                    repo = _rh.EmailRepository(session)
                    # CASA P1-8: scope by account_id (None = legacy callers, no-op)
                    db_email = repo.get_by_email_id(raw_email_id, account_id=account_id)
                    if db_email:
                        if not db_email.body_text:
                            db_email.body_text = getattr(email_obj, 'body', '') or ''
                        if db_email.body_html is None or db_email.body_html == "":
                            db_email.body_html = getattr(email_obj, 'body_html', '') or ''
                        session.commit()
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
    except Exception as e:
        logger.debug(f"Envoi body fetch background échoué pour {raw_email_id}: {e}")


_body_fetch_semaphore = threading.Semaphore(3)  # max 3 concurrent background fetches
_body_fetch_inflight: set[tuple[int | None, str]] = set()
_body_fetch_inflight_lock = threading.Lock()
_PROVIDER_DETAIL_CONCURRENCY = _positive_int_env("EMAIL_DETAIL_FETCH_CONCURRENCY", 4)
_PROVIDER_DETAIL_WAIT_SECONDS = _positive_float_env("EMAIL_DETAIL_FETCH_WAIT_SECONDS", 5.0)
_PROVIDER_DETAIL_QUOTA_WAIT_SECONDS = _positive_float_env("EMAIL_DETAIL_QUOTA_WAIT_SECONDS", 2.0)
_PROVIDER_DETAIL_RETRY_AFTER_SECONDS = _positive_int_env("EMAIL_DETAIL_FETCH_RETRY_AFTER_SECONDS", 5)
_provider_detail_semaphore = threading.Semaphore(_PROVIDER_DETAIL_CONCURRENCY)


def _body_fetch_key(email_id: str, db_account_id: int | None) -> tuple[int | None, str]:
    return (db_account_id, str(email_id))


def _is_body_fetch_inflight(email_id: str, db_account_id: int | None) -> bool:
    with _body_fetch_inflight_lock:
        return _body_fetch_key(email_id, db_account_id) in _body_fetch_inflight


def _provider_detail_busy_response() -> Response:
    response = jsonify({
        "error": "rate_limited",
        "code": "EMAIL_DETAIL_FETCH_BUSY",
        "retry_after": _PROVIDER_DETAIL_RETRY_AFTER_SECONDS,
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(_PROVIDER_DETAIL_RETRY_AFTER_SECONDS)
    return response


def _provider_detail_quota_backoff_response(exc: BaseException) -> Response:
    retry_after = _PROVIDER_DETAIL_RETRY_AFTER_SECONDS
    try:
        retry_after = max(1, int(getattr(exc, "retry_after")))
    except (TypeError, ValueError):
        pass
    provider = str(getattr(exc, "provider", "") or "gmail")
    response = jsonify({
        "error": "rate_limited",
        "code": "EMAIL_PROVIDER_BACKOFF",
        "provider": provider,
        "retry_after": retry_after,
        "server_status": "ok",
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


def _is_provider_quota_backoff(exc: BaseException) -> bool:
    return getattr(exc, "code", None) == "GMAIL_QUOTA_BACKOFF"


@api_bp.route("/load-test/provider-probe", methods=["GET"])
def load_test_provider_probe():
    """Call the mocked email provider directly during isolated load tests."""
    if not (_env_flag("AGENTYS_LOAD_TEST_MODE") and _env_flag("AGENTYS_MOCK_EMAIL_PROVIDER")):
        abort(404)

    operation = (request.args.get("operation") or "detail").strip().lower()
    if operation not in {"detail", "list", "sent"}:
        return jsonify({"error": "Invalid provider probe operation"}), 400

    max_limit = _positive_int_env("LOAD_TEST_PROVIDER_PROBE_MAX_LIMIT", 200)
    try:
        limit = max(1, min(max_limit, int(request.args.get("limit", "20"))))
    except (TypeError, ValueError):
        limit = 20
    message_id = (request.args.get("message_id") or f"load-email-{uuid.uuid4().hex}").strip()
    provider_kind = (request.args.get("provider_kind") or "").strip().lower()
    provider_context = nullcontext()
    if provider_kind:
        if provider_kind not in {"gmail", "google", "outlook", "microsoft", "graph"}:
            return jsonify({"error": "Invalid provider kind"}), 400
        from app.providers.mock_load_provider import provider_kind_override

        provider_context = provider_kind_override(provider_kind)
    started = _cache_time.perf_counter()
    try:
        with provider_context:
            provider = _get_authenticated_provider()
            if operation == "detail":
                email = provider.get_message_by_id(message_id)
                count = 1 if email is not None else 0
            elif operation == "sent":
                count = len(provider.get_sent_emails(limit=limit))
            else:
                count = len(provider.get_messages(limit=limit, unread_only=False))

            latency_ms = int((_cache_time.perf_counter() - started) * 1000)
            return jsonify({
                "success": True,
                "provider": getattr(provider, "provider_name", "unknown"),
                "operation": operation,
                "count": count,
                "latency_ms": latency_ms,
            })
    except Exception as exc:
        if _is_provider_quota_backoff(exc):
            return _provider_detail_quota_backoff_response(exc)
        raise


def _get_email_by_id_for_detail(provider, raw_email_id: str):
    def _fetch_from_provider():
        email = provider.get_message_by_id(raw_email_id)
        if not email:
            abort(404, description="Email not found")
        return email

    if getattr(type(provider), "limited_quota_wait", None) is None:
        return _fetch_from_provider()

    limiter = getattr(provider, "limited_quota_wait", None)
    if callable(limiter):
        context = limiter(_PROVIDER_DETAIL_QUOTA_WAIT_SECONDS)
        if hasattr(context, "__enter__") and hasattr(context, "__exit__"):
            with context:
                return _fetch_from_provider()
    return _fetch_from_provider()

# Persisted in `body_html` when the provider has nothing to return for an email
# (truly-empty MIME, deleted message, parse failure, …). Stored as a real HTML
# value so `body_ready` evaluates to True on subsequent reads — that's what
# breaks the bg-fetch loop documented in incident 2026-05-04: an empty
# body_html stayed NULL forever, every GET respawned _fetch_body_html_background,
# every spawn re-emitted email_body_ready, the frontend re-fetched on each event,
# and the cycle ran at ~6 req/s until the modal closed.
EMPTY_BODY_PLACEHOLDER = (
    '<div data-agentys-empty="true" '
    'style="color:#888;font-style:italic;padding:1.5rem;'
    'text-align:center;font-size:0.9rem;">'
    'Cet email ne contient pas de contenu textuel.'
    '</div>'
)


def _detail_payload_has_visible_body(payload: dict | None) -> bool:
    """True when a detail/list-cache payload can satisfy an email open."""
    if not payload:
        return False
    body_html = payload.get("body_html")
    if isinstance(body_html, str) and body_html.strip() and "cid:" not in body_html.lower():
        return True
    for field in ("body", "body_text"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _get_account_config_for_db_account_id(db_account_id: int | None):
    """Return the AccountConfig matching a scoped DB account id."""
    if db_account_id is None or db_account_id == getattr(_rh, "_NO_ACCOUNT_SENTINEL", -1):
        return None
    try:
        from app.db.models.account import Account
        from app.multi_accounts import get_account_manager

        with _rh.get_db_session() as session:
            db_account = session.get(Account, int(db_account_id))
            email = db_account.email if db_account else ""
        if not email:
            return None
        return get_account_manager().get_account_by_email(email)
    except Exception as exc:
        logger.warning(
            "Email detail: failed to resolve AccountConfig for db_account_id=%s: %s",
            db_account_id,
            exc,
        )
        return None


def _fetch_body_html_background(email_id: str, raw_email_id: str, is_sent: bool, account_id: str = None, db_account_id: int | None = None) -> None:
    """Background thread: fetch full body_html from IMAP and update SQLite + cache.

    Args:
        account_id: OAuth hash account ID (used by AccountManager to instantiate provider).
        db_account_id: DB int account_id for SQLite scoping (CASA P1-8). Resolved
            from `account_id` via AccountManager if not provided.
    """
    import threading
    from flask import current_app
    _app = current_app._get_current_object()
    _fetch_key = _body_fetch_key(email_id, db_account_id)
    with _body_fetch_inflight_lock:
        if _fetch_key in _body_fetch_inflight:
            return
        _body_fetch_inflight.add(_fetch_key)

    def _do_fetch():
        if not _body_fetch_semaphore.acquire(blocking=False):
            # Max concurrent background fetches already running. Logged (was a
            # silent skip) so the starvation that hid behind it is diagnosable
            # — incident 2026-05-20: metadata_only opens stuck on "could not be
            # loaded". The synchronous fetch in get_email is now the reliable
            # primary path; this async fetch is a refresh/busy-fallback only.
            logger.debug(
                "Background body fetch for %s skipped: max concurrent "
                "background fetches already running (semaphore busy)",
                email_id,
            )
            # Release the in-flight guard (5ae95ab1) before bailing, else the key
            # stays "in-flight" forever and blocks every future fetch for this email.
            with _body_fetch_inflight_lock:
                _body_fetch_inflight.discard(_fetch_key)
            return
        try:
            with _app.app_context():
                # Create a fresh authenticated provider — never reuse the pool here,
                # as the pooled instance may have a stale OAuth token and skip re-auth.
                _acct = None
                try:
                    if account_id:
                        from app.multi_accounts import get_account_manager, create_provider_for_account
                        _acct = get_account_manager().get_account(account_id)
                        if _acct:
                            provider = create_provider_for_account(_acct)
                            if not provider.authenticate():
                                logger.warning(f"Background body: auth failed for account {account_id}")
                                return
                        else:
                            provider = _get_authenticated_provider()
                    else:
                        provider = _get_authenticated_provider()
                except Exception as _auth_exc:
                    logger.warning(f"Background body: provider creation failed: {_auth_exc}")
                    return
                email_obj = provider.get_message_by_id(raw_email_id)
                if not email_obj:
                    # Provider can't find this message. Write the sentinel so body_html
                    # is no longer NULL — stops repeated background-fetch spawning on
                    # every subsequent GET (same incident as 2026-05-04, but for the
                    # "message not found" case instead of "empty body" case).
                    if should_persist_email_content():
                        try:
                            _aid = db_account_id
                            if _aid is None and account_id:
                                try:
                                    from app.multi_accounts import get_account_manager
                                    _acct_obj = get_account_manager().get_account(account_id)
                                    if _acct_obj is not None:
                                        _aid = getattr(_acct_obj, 'db_id', None) or getattr(_acct_obj, 'id', None)
                                except Exception:
                                    _aid = None
                            with _rh.get_db_session() as _sess:
                                _repo = _rh.EmailRepository(_sess)
                                _db_em = _repo.get_by_email_id(raw_email_id, account_id=_aid)
                                if _db_em and not _db_em.body_html:
                                    _db_em.body_html = EMPTY_BODY_PLACEHOLDER
                                    logger.info(f"Background body: message {raw_email_id} not found by provider, stored sentinel")
                        except Exception as _e:
                            logger.debug(f"Background body: failed to write sentinel for {raw_email_id}: {_e}")
                    return
                body_html = getattr(email_obj, 'body_html', '') or ''
                body_text = getattr(email_obj, 'body', '') or ''
                persist_content = should_persist_email_content()
                # For text-only emails (no HTML body), wrap plain text in minimal HTML
                # so the cache considers the body as "fetched" and avoids repeated re-fetches.
                if not body_html and body_text:
                    import re as _re_mod
                    import html as _html_mod
                    _html_tag_re = _re_mod.compile(r'<(div|p|br|table|span|a\s|img|ul|ol|li|h[1-6]|blockquote)[^>]*>', _re_mod.IGNORECASE)
                    if _html_tag_re.search(body_text):
                        # body_text already contains HTML (e.g. signature) — use as-is
                        body_html = body_text
                    else:
                        body_html = f'<div style="white-space:pre-wrap">{_html_mod.escape(body_text)}</div>'
                # Effective HTML written to SQLite + cache. Sentinel when provider
                # returned nothing — body_ready check accepts it, so subsequent
                # GETs short-circuit instead of respawning this background fetch.
                _effective_body_html = body_html if body_html else EMPTY_BODY_PLACEHOLDER
                # Did we actually advance the user-visible state? Drives the WS
                # emit below — emitting on no-change re-feeds the frontend handler
                # which re-fetches, which respawns this fetch, which re-emits, …
                # (incident 2026-05-04: 890 fetches in 4 minutes for one email).
                _has_real_new_content = False
                if not persist_content and (body_text or body_html):
                    _has_real_new_content = True
                _bg_att_list = getattr(email_obj, 'attachments', []) or []
                # Extract meeting metadata UPFRONT — independent of DB state, since
                # it must populate the in-memory cache even when db_email is None
                # (cross-thread account_id resolution sometimes fails to find the
                # row, but the user-facing cache update still needs meeting_meta).
                _meeting_meta = None
                try:
                    from app.providers.gmail_calendar import extract_meeting_from_body
                    # 1. iCal embedded in body text/HTML (IMAP-style)
                    _meeting_meta = extract_meeting_from_body(body_text, body_html)
                    if _meeting_meta:
                        logger.info(f"[MEETING] {raw_email_id}: extracted from body HTML")
                    # 2. iCal from provider.ical_text (Gmail: payload-scanned inline
                    #    .ics parts that have no separate attachmentId — common for
                    #    small Teams/Google Meet invites)
                    if _meeting_meta is None:
                        _ical_raw = getattr(email_obj, 'ical_text', None)
                        logger.info(f"[MEETING] {raw_email_id}: ical_text len={len(_ical_raw) if _ical_raw else 0}")
                        if _ical_raw:
                            _meeting_meta = extract_meeting_from_body(_ical_raw)
                            if _meeting_meta:
                                logger.info(f"[MEETING] {raw_email_id}: extracted from ical_text")
                    # 3. .ics as a separate attachment (larger files / non-Gmail
                    #    providers where ical_text is not populated)
                    if _meeting_meta is None:
                        _ics_att = next(
                            (a for a in _bg_att_list
                             if (a.get("filename") or "").lower().endswith(".ics")),
                            None,
                        )
                        if _ics_att and hasattr(provider, "download_attachment"):
                            _ics_data, _, _ = provider.download_attachment(
                                raw_email_id, _ics_att["id"]
                            )
                            _ics_text = (
                                _ics_data.decode("utf-8", errors="replace")
                                if isinstance(_ics_data, bytes)
                                else str(_ics_data)
                            )
                            _meeting_meta = extract_meeting_from_body(_ics_text)
                            if _meeting_meta:
                                logger.info(f"[MEETING] {raw_email_id}: extracted from .ics download")
                except Exception as _meet_err:
                    logger.debug(
                        f"Background body: meeting extraction failed for {raw_email_id}: {_meet_err}"
                    )
                # Persist only allowed metadata in SQLite. Raw body persistence is
                # gated by AGENTYS_EMAIL_CONTENT_STORAGE_MODE=legacy_full_cache.
                try:
                    with _rh.get_db_session() as session:
                        repo = _rh.EmailRepository(session)
                        # CASA P1-8: resolve DB int from OAuth hash if needed
                        _aid = db_account_id
                        if _aid is None and account_id:
                            try:
                                from app.multi_accounts import get_account_manager
                                _acct_obj = get_account_manager().get_account(account_id)
                                if _acct_obj is not None:
                                    _aid = getattr(_acct_obj, 'db_id', None) or getattr(_acct_obj, 'id', None)
                            except Exception:
                                _aid = None
                        db_email = repo.get_by_email_id(raw_email_id, account_id=_aid)
                        if not db_email:
                            logger.info(f"[MEETING] {raw_email_id}: db_email not found (aid={_aid})")
                        if db_email:
                            _prev_html = db_email.body_html
                            _prev_text = db_email.body_text
                            _prev_has_real_att_meta = bool(
                                db_email.attachments_meta
                                and '"filename"' in (db_email.attachments_meta or '')
                            )
                            if persist_content:
                                if body_html:
                                    # Real provider HTML — write iff different from existing.
                                    # Skipping the no-op write avoids emitting a WS event for
                                    # repeated identical fetches.
                                    if _prev_html != body_html:
                                        db_email.body_html = body_html
                                        _has_real_new_content = True
                                elif _prev_html is None or _prev_html == '':
                                    # Provider has nothing AND SQLite has nothing — write the
                                    # sentinel so body_ready=True next read and the loop
                                    # documented in incident 2026-05-04 cannot start.
                                    db_email.body_html = EMPTY_BODY_PLACEHOLDER
                                # else: SQLite already has real content (e.g. CID-stale
                                # body_html the bg fetch was supposed to refresh) — don't
                                # downgrade to sentinel just because this fetch came back empty.
                                if body_text and not _prev_text:
                                    db_email.body_text = body_text
                                    _has_real_new_content = True
                            # Persist attachment metadata + meeting metadata to SQLite
                            # (extraction was already done above).
                            import json as _json_bg
                            _should_write_att = _bg_att_list and not _prev_has_real_att_meta
                            if _should_write_att or _meeting_meta is not None:
                                if _meeting_meta:
                                    db_email.attachments_meta = _json_bg.dumps({
                                        "files": _bg_att_list,
                                        "meeting": _meeting_meta,
                                    })
                                else:
                                    db_email.attachments_meta = _json_bg.dumps(_bg_att_list)
                                # Attachment-only changes don't trigger _has_real_new_content
                                # (frontend email_body_ready handler ignores att-only updates).
                            # Don't clear placeholder: Gmail API may not return attachments
                            # even when they exist (IMAP Content-Type detected them correctly)
                            session.commit()
                            # If the freshly-fetched body reveals a calendar invite the
                            # initial labelling could not see (Hotmail-from-Gmail invites
                            # arrive with body=0 + meta=null), re-run labelling +
                            # auto-trigger so the Quick Action that auto-accepts meeting
                            # invitations actually fires. force=True overrides the stale
                            # Noise label, but `_auto_assign_labels_background` still
                            # preserves any user correction (assigned_by="user").
                            try:
                                _looks_like_invite = _looks_like_calendar_invite(
                                    body_text, body_html, db_email.attachments_meta or "",
                                )
                            except Exception:
                                _looks_like_invite = False
                            if _looks_like_invite and _aid:
                                _reclassify_email_id = raw_email_id
                                _reclassify_aid = _aid
                                def _late_reclassify():
                                    try:
                                        with _rh.get_db_session() as _s2:
                                            _r2 = _rh.EmailRepository(_s2)
                                            _fresh = _r2.get_by_email_id(
                                                _reclassify_email_id,
                                                account_id=_reclassify_aid,
                                            )
                                            if _fresh is not None:
                                                _s2.expunge(_fresh)
                                        if _fresh is not None:
                                            logger.info(
                                                "Late re-classify: %s looks like invite, re-running labelling + auto-trigger",
                                                _reclassify_email_id,
                                            )
                                            _auto_assign_labels_background(
                                                [_fresh],
                                                force=True,
                                                account_id=_reclassify_aid,
                                            )
                                    except Exception as _rc_err:
                                        logger.warning(
                                            "Late re-classify failed for %s: %s",
                                            _reclassify_email_id, _rc_err,
                                        )
                                threading.Thread(target=_late_reclassify, daemon=True).start()
                except Exception as db_err:
                    logger.warning(f"Background body persist to SQLite failed for {email_id}: {db_err}")
                # Always update the in-memory detail cache with the fetched body + attachments.
                # Key format is (db_account_id, email_id) — matches _set_cached_email_detail and
                # _get_cached_email_detail. Writing a bare string key here used to poison the
                # cache and make `_get_email_from_memory_list_cache` crash with
                # "too many values to unpack (expected 2)".
                _db_account_id: int | None = db_account_id
                try:
                    if _db_account_id is None and _acct and getattr(_acct, 'email', None):
                        _db_account_id = _rh._resolve_account_id_for_email(_acct.email)
                except Exception:
                    pass
                if _db_account_id is None:
                    _db_account_id = _rh._resolve_account_id_for_user()
                _detail_key = (_db_account_id, email_id)
                with _email_detail_cache_lock:
                    existing = _email_detail_cache.get(_detail_key)
                    if _meeting_meta is not None:
                        logger.info(f"[MEETING] {raw_email_id}: cache update existing={'yes' if existing else 'NO'} key={_detail_key}")
                    if existing:
                        existing["data"]["body"] = body_text
                        # Mirror SQLite's effective html (real or sentinel) so the
                        # body_ready check on the next cache hit matches reality.
                        existing["data"]["body_html"] = _effective_body_html
                        if _bg_att_list:
                            existing["data"]["attachments"] = _bg_att_list
                            existing["data"]["has_attachments"] = True
                        if _meeting_meta is not None:
                            existing["data"]["meeting_meta"] = _meeting_meta
                            logger.info(f"[MEETING] {raw_email_id}: meeting_meta written to cache")
                    elif body_text or body_html or _bg_att_list:
                        # No detail cache entry yet — build one from the email object.
                        # Skip when we have nothing real (sentinel-only): the next GET
                        # will repopulate the cache from SQLite, which now has the
                        # sentinel and will short-circuit without spawning another
                        # background fetch.
                        import time as _time_mod
                        _email_detail_cache[_detail_key] = {
                            "data": {
                                "id": email_id,
                                "sender": getattr(email_obj, 'sender', ''),
                                "sender_name": getattr(email_obj, 'sender_name', None),
                                "subject": getattr(email_obj, 'subject', ''),
                                "received_at": str(getattr(email_obj, 'received_at', '')),
                                "body": body_text,
                                "body_html": _effective_body_html,
                                "body_preview": (body_text or '')[:200],
                                "body_text": body_text,
                                "is_read": getattr(email_obj, 'is_read', True),
                                "has_attachments": bool(_bg_att_list) or getattr(email_obj, 'has_attachments', False),
                                "attachments": _bg_att_list,
                                "meeting_meta": _meeting_meta,
                                "cc": [],
                                "labels": _get_email_labels(str(raw_email_id), account_id=_db_account_id) if not is_sent else [],
                                "conversation_id": email_id,
                                "has_pending_draft": False,
                            },
                            "timestamp": _time_mod.time(),
                        }
                logger.info(
                    f"Background body fetch done for {email_id} "
                    f"(real_content={'yes' if _has_real_new_content else 'no'})"
                )
                # Emit only when the user-visible state actually moved forward.
                # Skipping emits on (a) sentinel-only persistence and (b) unchanged
                # content prevents the WS-refetch storm documented in incident
                # 2026-05-04 — the frontend handler would refetch on every emit,
                # respawning this fetch, which would re-emit, ad infinitum.
                if _has_real_new_content:
                    try:
                        from app.api.websocket import emit_to_account
                        emit_to_account('email_body_ready', {'email_id': email_id}, _db_account_id)
                    except Exception as ws_err:
                        logger.debug(f"Background body WebSocket notify failed for {email_id}: {ws_err}")
        except Exception as e:
            # Was logger.debug — the silent swallow hid WHY bodies never loaded
            # (incident 2026-05-20: metadata_only opens stuck on "could not be
            # loaded"). exc_info surfaces the provider/auth traceback for audit.
            logger.warning(
                f"Background body fetch failed for {email_id}: {e}", exc_info=True
            )
        finally:
            _body_fetch_semaphore.release()
            with _body_fetch_inflight_lock:
                _body_fetch_inflight.discard(_fetch_key)

    threading.Thread(target=_do_fetch, daemon=True).start()



@api_bp.route("/emails/<email_id>", methods=["GET"])
def get_email(email_id: str):
    """
    Recupere un email par son ID.

    Args:
        email_id: ID de l'email a recuperer.

    Returns:
        200: Details complets de l'email (incluant body)
        400: email_id invalide
        401: Authentification échouée
        404: Email non trouve
        500: Erreur interne
    """
    # BUG-J002 fix: guard against reserved path segments being captured as
    # email_id by Werkzeug's variable rule when the static rule in a sibling
    # blueprint should have taken precedence.  Flask prefers static over
    # variable routes, but defensive exclusion prevents mismatches on edge
    # cases (blueprint registration order, Werkzeug version quirks, etc.).
    _RESERVED_EMAIL_PATH_SEGMENTS = frozenset({
        'scheduled', 'search', 'counts', 'all', 'vip', 'thread', 'bulk',
    })
    if email_id in _RESERVED_EMAIL_PATH_SEGMENTS:
        abort(404)

    # Detect sent email prefix (IMAP UIDs are folder-specific)
    is_sent_email = email_id.startswith("sent:")
    raw_email_id = email_id[5:] if is_sent_email else email_id

    if not _validate_email_id(raw_email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    # Resolve the request-scoped account before any cache/provider access.
    # Do not read the process-global current account here: in cloud mode it can
    # point at another mailbox and Gmail will answer "message not found" for a
    # perfectly valid email in the requested account.
    _x_account_header = request.headers.get("X-Account-Id")
    _requested_account_id = _rh.require_owned_account_id(_x_account_header)
    if _x_account_header and _requested_account_id == _rh._NO_ACCOUNT_SENTINEL:
        return jsonify({
            "error": "Account not found or not owned by caller",
            "code": "INVALID_ACCOUNT_HEADER",
        }), 404

    from app.multi_accounts import get_account_manager, switch_account
    from flask import has_request_context
    _current = _get_account_config_for_db_account_id(_requested_account_id)
    if not _current:
        _current = _get_current_account_for_user()
    if not _current and _requested_account_id == _rh._NO_ACCOUNT_SENTINEL:
        _manager = get_account_manager()
        _all = _manager.get_all_accounts()
        auth_user = getattr(g, 'auth_user', None) if has_request_context() else None
        uid = None
        if auth_user and auth_user.get("id"):
            try:
                uid = int(auth_user["id"])
                _all = [a for a in _all if a.user_id == uid]
            except (ValueError, TypeError) as exc:
                logger.debug("Email detail account auto-activate skipped: %s", exc)
        if len(_all) == 1:
            switch_account(_all[0].id, user_id=uid)
            _current = _get_current_account_for_user()

    _acct_id = (
        _requested_account_id
        if _requested_account_id != _rh._NO_ACCOUNT_SENTINEL
        else (
            _rh._resolve_account_id_for_email(_current.email)
            if _current and getattr(_current, "email", None)
            else _resolve_account_id_for_user()
        )
    )
    _oauth_account_id = _current.id if _current else None

    _provider_detail_slot_acquired = False

    def _release_provider_detail_slot() -> None:
        nonlocal _provider_detail_slot_acquired
        if _provider_detail_slot_acquired:
            _provider_detail_slot_acquired = False
            _provider_detail_semaphore.release()

    # Regression fix (2026-05-20, ref 1b5721e8 "serve email headers while body
    # loads"): when SQLite / list-cache only has headers and no body — the norm
    # in metadata_only mode, which is the DEFAULT (email_content_storage.py) —
    # we now attempt the bounded synchronous provider fetch below instead of
    # relying solely on the async background fetch. That async path
    # (Semaphore(3) + fresh provider+authenticate() on every call + silent
    # failures) proved unreliable in metadata_only mode where EVERY open needs a
    # live fetch: bodies never arrived and the modal showed "could not be
    # loaded". This holds the headers-only payload so we can still serve headers
    # + kick the async fetch when the provider semaphore is busy/slow.
    _headers_fallback_payload: dict | None = None

    try:
        # Check in-memory cache first (5 min TTL) — uses prefixed ID
        cached = _get_cached_email_detail(email_id, account_id=_acct_id)
        if cached:
            # Prefer fetched HTML when it is usable, but do not ignore a real
            # text body. In privacy mode raw bodies are not persisted to SQLite;
            # the background fetch can only put the full body in this memory
            # cache. If we require body_html here, the UI stays on
            # "Chargement..." even after the background fetch succeeded.
            cached_html = cached.get("body_html")
            html_ready = (
                cached_html is not None
                and cached_html != ""
                and 'cid:' not in cached_html.lower()
            )
            body_ready = html_ready or _detail_payload_has_visible_body(cached)
            # Also check attachment integrity: has_attachments=True but no real metadata → fall through
            _cached_atts = cached.get("attachments") or []
            _att_ok = not cached.get("has_attachments") or (
                len(_cached_atts) > 0 and _cached_atts[0].get("filename")
            )
            if body_ready and _att_ok:
                if not html_ready and cached.get("body") and cached.get("body_html"):
                    cached = {**cached, "body_html": None}
                # Lazy inject meeting_meta for cached entries that predate the feature
                if cached.get("meeting_meta") is None and (cached.get("body") or cached.get("body_html")):
                    try:
                        from app.providers.gmail_calendar import extract_meeting_from_body
                        _m = extract_meeting_from_body(
                            cached.get("body") or "", cached.get("body_html") or ""
                        )
                        if _m:
                            cached["meeting_meta"] = _m
                    except Exception:
                        pass
                # When meeting_meta is still null, spawn a background fetch so the
                # provider can extract iCal content via email_obj.ical_text.
                # Triggers on the same broad meeting-invite signal as labelling
                # (_looks_like_calendar_invite) — covers Teams invites where the
                # .ics is inline (no attachmentId) and never appears in the
                # cached attachment list, but the HTML body still says "Microsoft
                # Teams" / contains a meetup-join URL.
                if cached.get("meeting_meta") is None:
                    _cached_atts_meta = ",".join(
                        f'"filename":"{a.get("filename","")}"'
                        for a in (cached.get("attachments") or [])
                    )
                    if _looks_like_calendar_invite(
                        cached.get("body") or "",
                        cached.get("body_html") or "",
                        _cached_atts_meta,
                    ):
                        logger.info(f"[MEETING] cache-path: triggering bg fetch for {email_id} to extract meeting_meta")
                        _fetch_body_html_background(
                            email_id, raw_email_id, is_sent_email,
                            account_id=_oauth_account_id,
                            db_account_id=_acct_id,
                        )
                return jsonify(cached)
            # If body not ready or attachments incomplete, fall through to provider fetch

        # Check SQLite cache (fast fallback before slow IMAP fetch)
        # _refresh_sent_cache_bg stores sent emails with raw_eid (no "sent:" prefix)
        sqlite_lookup_id = raw_email_id
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                db_email = repo.get_by_email_id(sqlite_lookup_id, account_id=_acct_id)
                if db_email:
                    # body_html=None/"" or contains unresolved cid: → fall through to IMAP to get
                    # inline images (CID resolved to base64). Only serve from cache when HTML
                    # has been fetched, is non-empty, and has no stale CID references.
                    # "" means "never properly fetched" (set by list-mode backfill that skips CID resolution).
                    body_ready = (
                        db_email.body_html is not None
                        and db_email.body_html != ""
                        and 'cid:' not in db_email.body_html.lower()
                    )
                    # Build common fields from SQLite row
                    labels = [] if is_sent_email else _get_email_labels(str(raw_email_id), account_id=_acct_id)
                    pending_email_ids = _get_pending_draft_email_ids(account_id=_acct_id)
                    has_draft = sqlite_lookup_id in pending_email_ids

                    body_preview = ""
                    body_src = db_email.body_text or db_email.snippet or ""
                    if body_src:
                        import re as _re
                        clean = _re.sub(r'<[^>]+>', ' ', body_src)
                        clean = _re.sub(r'\s+', ' ', clean).strip()
                        body_preview = clean[:100] + "..." if len(clean) > 100 else clean

                    _att_meta = []
                    _meeting_meta_db = None
                    if db_email.attachments_meta:
                        try:
                            import json as _json
                            _raw = _json.loads(db_email.attachments_meta)
                            if isinstance(_raw, dict):
                                _att_meta = _raw.get("files", [])
                                _meeting_meta_db = _raw.get("meeting")
                            else:
                                _att_meta = _raw
                            # Filter out placeholder entries (e.g. [{"has":true}]) — keep only real metadata
                            if _att_meta and not any(a.get("filename") for a in _att_meta):
                                _att_meta = []
                        except (ValueError, TypeError, KeyError) as e:
                            logger.warning(f"Failed to parse attachments_meta: {e}")
                            _att_meta = []
                    # Filter noise attachments (favicons, tracking pixels) for consistency
                    _att_meta = _filter_noise_attachments(_att_meta)
                    # Lazy fallback: if no stored meeting_meta but body contains iCal, extract now.
                    # Covers emails synced before this feature was deployed.
                    if _meeting_meta_db is None and (db_email.body_text or db_email.body_html):
                        try:
                            from app.providers.gmail_calendar import extract_meeting_from_body
                            _meeting_meta_db = extract_meeting_from_body(
                                db_email.body_text or "", db_email.body_html or ""
                            )
                        except Exception:
                            pass
                    email_dict = {
                        "id": email_id,  # Return prefixed ID (sent:xxx) for frontend consistency
                        "sender": db_email.sender,
                        "sender_name": db_email.sender_name,
                        "subject": db_email.subject,
                        "received_at": _to_iso_utc(db_email.date) if db_email.date else None,
                        "has_attachments": bool(_att_meta),
                        "attachments": _att_meta,
                        "meeting_meta": _meeting_meta_db,
                        "conversation_id": db_email.thread_id,
                        "is_read": db_email.is_read,
                        "body_preview": body_preview,
                        "has_pending_draft": has_draft,
                        "labels": labels,
                        "body": (db_email.body_text or db_email.snippet or "") if not body_ready else None,
                        "body_html": db_email.body_html if body_ready else None,
                        "body_text": db_email.body_text or db_email.snippet or "",
                        "to": [r.strip() for r in db_email.recipients.split(",") if r.strip()] if db_email.recipients else [],
                        "cc": [r.strip() for r in db_email.cc.split(",") if r.strip()] if db_email.cc else [],
                    }

                    # If email has attachments but metadata is placeholder, fall through
                    # to provider fetch so attachment chips show filename + download
                    _needs_att_fetch = bool(db_email.attachments_meta) and not _att_meta

                    if body_ready and not _needs_att_fetch:
                        _set_cached_email_detail(email_id, email_dict, account_id=_acct_id)
                        # If attachments_meta is NULL, trigger background check.
                        # Also trigger when meeting_meta is null and the email looks
                        # like a meeting invite — .ics may be inline (no attachmentId)
                        # so it won't appear in _att_meta; reuse the labelling-side
                        # _looks_like_calendar_invite for body-text signals like
                        # "microsoft teams" / meetup-join URLs.
                        _needs_meeting_fetch = (
                            _meeting_meta_db is None
                            and _looks_like_calendar_invite(
                                db_email.body_text or "",
                                db_email.body_html or "",
                                db_email.attachments_meta or "",
                            )
                        )
                        if _needs_meeting_fetch:
                            logger.info(f"[MEETING] sqlite-path: triggering bg fetch for {email_id} to extract meeting_meta")
                        if db_email.attachments_meta is None or _needs_meeting_fetch:
                            _fetch_body_html_background(email_id, raw_email_id, is_sent_email, account_id=_oauth_account_id, db_account_id=_acct_id)
                        return jsonify(email_dict)

                    # body_html not ready or attachments need metadata — serve what
                    # we have immediately and fetch the rest in background.  This avoids
                    # blocking the user on a slow Graph API / IMAP call.
                    logger.info(f"Email {email_id}: serving from SQLite (body_html={'ready' if body_ready else 'pending'}, att={'ok' if not _needs_att_fetch else 'pending'})")
                    _has_visible_body = bool(
                        (db_email.body_text or db_email.snippet or "").strip()
                        or (db_email.body_html or "").strip()
                    )
                    if _has_visible_body:
                        # We have something to show (text / snippet / partial
                        # HTML). Serve it instantly and refresh the rest
                        # (CID-resolved HTML, attachments, meeting meta) async.
                        _fetch_body_html_background(
                            email_id,
                            raw_email_id,
                            is_sent_email,
                            account_id=_oauth_account_id,
                            db_account_id=_acct_id,
                        )
                        return jsonify(email_dict)
                    # No body at all — fall through to the bounded synchronous
                    # provider fetch (reliable; ≤5s via _provider_detail_semaphore,
                    # pooled provider, no per-call re-auth). Keep these headers as
                    # the payload to serve + async-refresh only if the provider
                    # semaphore is busy. See the _headers_fallback_payload note above.
                    logger.info(f"Email {email_id}: SQLite row has no body, attempting synchronous provider fetch")
                    email_dict["body_fetch_pending"] = True
                    _headers_fallback_payload = email_dict
        except Exception as db_err:
            logger.debug("SQLite fallback failed for %s: %s", sqlite_lookup_id, db_err)

        # Try list cache — serve whatever we have to avoid provider fetch.
        # Scope the lookup to the caller's account to prevent cross-tenant leaks
        # when two accounts happen to share a cached email_id.
        _list_hit = _find_email_in_list_cache(email_id, account_key=_oauth_account_id)
        if _list_hit:
            if _detail_payload_has_visible_body(_list_hit):
                logger.info(f"Email {email_id}: serving from list cache")
                return jsonify(_list_hit)
            # Headers-only list hit — fall through to the synchronous provider
            # fetch (reliable). Keep these headers as the busy-fallback payload
            # if SQLite didn't already supply one (SQLite headers carry labels).
            logger.info(f"Email {email_id}: list cache has metadata only, attempting synchronous provider fetch")
            _list_hit.setdefault("body", "")
            _list_hit.setdefault("body_html", None)
            _list_hit.setdefault("body_text", _list_hit.get("snippet") or "")
            _list_hit["body_fetch_pending"] = True
            if _headers_fallback_payload is None:
                _headers_fallback_payload = _list_hit

        # Final fallback - fetch from provider (slow IMAP)
        # Bounded to prevent provider connection storms, but metadata-only mode
        # makes inline detail fetches common. Wait briefly and return a
        # Retry-After-aware 429 so the frontend retries once instead of
        # surfacing a hard error to the user.
        if not _provider_detail_semaphore.acquire(timeout=_PROVIDER_DETAIL_WAIT_SECONDS):
            logger.warning(
                "Email %s: provider fetch busy after %.1fs "
                "(concurrency=%d)",
                email_id,
                _PROVIDER_DETAIL_WAIT_SECONDS,
                _PROVIDER_DETAIL_CONCURRENCY,
            )
            # Busy/slow → async fallback (2026-05-20): if we already have the
            # headers (the no-body SQLite/list-cache case), serve them + kick the
            # background body fetch so the frontend can poll it in, instead of a
            # hard 429. A genuine no-data request still gets the retryable 429.
            if _headers_fallback_payload is not None:
                logger.info(f"Email {email_id}: provider busy, serving headers + background body fetch")
                _fetch_body_html_background(
                    email_id,
                    raw_email_id,
                    is_sent_email,
                    account_id=_oauth_account_id,
                    db_account_id=_acct_id,
                )
                return jsonify(_headers_fallback_payload)
            return _provider_detail_busy_response()
        _provider_detail_slot_acquired = True
        logger.info(f"Email {email_id}: no cache/SQLite data at all, falling back to provider fetch")
        try:
            from app.providers.factory import get_pooled_provider
            provider = get_pooled_provider(account_id=_oauth_account_id) if _oauth_account_id else _get_authenticated_provider()
        except Exception as _auth_exc:
            if _headers_fallback_payload is not None and _is_auth_expired_error(_auth_exc):
                logger.warning(
                    "Email %s: provider auth unavailable, serving cached headers",
                    _sanitize_for_log(email_id),
                )
                _release_provider_detail_slot()
                return jsonify({
                    **_headers_fallback_payload,
                    "body_fetch_pending": True,
                    "provider_unavailable": True,
                    "needs_reauth": True,
                })
            if is_sent_email:
                # Auth failed for sent email — serve partial data from SQLite rather than 401
                logger.warning(f"Sent email {email_id}: auth failed ({_auth_exc}), serving SQLite fallback")
                _is_synthetic_sent = bool(re.fullmatch(r"reply-\d+", raw_email_id))
                try:
                    with _rh.get_db_session() as _s:
                        _db = _rh.EmailRepository(_s).get_by_email_id(sqlite_lookup_id, account_id=_acct_id)
                        if _db:
                            _body_text = _db.body_text or _db.snippet or ""
                            _release_provider_detail_slot()
                            return jsonify({
                                "id": email_id,
                                "sender": _db.sender,
                                "sender_name": _db.sender_name,
                                "subject": _db.subject,
                                "received_at": _to_iso_utc(_db.date) if _db.date else None,
                                "has_attachments": bool(_db.attachments_meta),
                                "attachments": [],
                                "conversation_id": _db.thread_id,
                                "is_read": _db.is_read,
                                "body_preview": _body_text[:100],
                                "has_pending_draft": sqlite_lookup_id in _get_pending_draft_email_ids(account_id=_acct_id),
                                "labels": _get_email_labels(str(raw_email_id), account_id=_acct_id) if not is_sent_email else [],
                                "body_fetch_pending": not _is_synthetic_sent,
                                "body": _body_text,
                                "body_html": None,
                                "body_text": _body_text,
                                "to": [r.strip() for r in _db.recipients.split(",") if r.strip()] if _db.recipients else [],
                                "cc": [r.strip() for r in _db.cc.split(",") if r.strip()] if _db.cc else [],
                            })
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
                # SQLite miss — try in-memory list cache as last resort
                _list_hit = _find_sent_email_in_list_cache(email_id, account_key=_oauth_account_id)
                if _list_hit:
                    logger.info(f"Sent email {email_id}: auth failed, serving from list cache")
                    _release_provider_detail_slot()
                    return jsonify(_list_hit)
                _release_provider_detail_slot()
                abort(404, description="Email not found")
            raise

        # If the email exists in SQLite (without body), it was synced via IMAP.
        # The OAuth provider may be Gmail API which uses different IDs than IMAP UIDs.
        # Try fetching via IMAP legacy provider as fallback if the primary provider fails.
        _need_imap_fallback = False
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                # Audit 2026-04-25 (HIGH-Iso-3): scope by current account.
                _need_imap_fallback = repo.exists_by_email_id(sqlite_lookup_id, account_id=_acct_id)
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        if is_sent_email:
            email = None
            try:
                email = provider.get_message_by_id(raw_email_id)
            except Exception as _e:
                logger.debug(f"Sent email {raw_email_id}: get_message_by_id failed: {_e}")
            if not email:
                # Last resort: try to find the email in the in-memory list cache
                # (scoped to the caller's account to prevent cross-tenant leaks)
                _list_fallback = _find_sent_email_in_list_cache(email_id, account_key=_oauth_account_id)
                if _list_fallback:
                    logger.info(f"Sent email {email_id}: serving from list cache fallback")
                    _release_provider_detail_slot()
                    return jsonify(_list_fallback)
                # Provider miss ≠ gone (2026-06-11): synthetic `reply-<ts>`
                # placeholder rows — inserted at send time for immediate Sent
                # visibility and normally removed later by
                # dedupe_sent_by_content — have no provider counterpart at all,
                # and deployments that don't persist email content can never
                # dedupe them. Serve the SQLite headers instead of a hard 404
                # (the inbox branch has had this fallback since the IMAP/OAuth
                # id-mismatch fix; the auth-failed branch above too).
                _is_synthetic_sent = bool(re.fullmatch(r"reply-\d+", raw_email_id))
                if _headers_fallback_payload is not None:
                    logger.info(f"Sent email {email_id}: provider miss, serving SQLite headers fallback")
                    if _is_synthetic_sent:
                        # No provider counterpart — claiming a pending body
                        # fetch would make the frontend poll forever.
                        _headers_fallback_payload["body_fetch_pending"] = False
                    else:
                        _fetch_body_html_background(
                            email_id,
                            raw_email_id,
                            is_sent_email,
                            account_id=_oauth_account_id,
                            db_account_id=_acct_id,
                        )
                    _release_provider_detail_slot()
                    return jsonify(_headers_fallback_payload)
                try:
                    with _rh.get_db_session() as _s:
                        _db = _rh.EmailRepository(_s).get_by_email_id(sqlite_lookup_id, account_id=_acct_id)
                        if _db:
                            _body_text = _db.body_text or _db.snippet or ""
                            _release_provider_detail_slot()
                            return jsonify({
                                "id": email_id,
                                "sender": _db.sender,
                                "sender_name": _db.sender_name,
                                "subject": _db.subject,
                                "received_at": _to_iso_utc(_db.date) if _db.date else None,
                                "has_attachments": bool(_db.attachments_meta),
                                "attachments": [],
                                "conversation_id": _db.thread_id,
                                "is_read": _db.is_read,
                                "body_preview": _body_text[:100],
                                "has_pending_draft": sqlite_lookup_id in _get_pending_draft_email_ids(account_id=_acct_id),
                                "labels": [],
                                "body": _body_text,
                                "body_html": None,
                                "body_text": _body_text,
                                "to": [r.strip() for r in _db.recipients.split(",") if r.strip()] if _db.recipients else [],
                                "cc": [r.strip() for r in _db.cc.split(",") if r.strip()] if _db.cc else [],
                                "body_fetch_pending": not _is_synthetic_sent,
                            })
                except HTTPException:
                    raise
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
                abort(404, description="Email not found")
        else:
            try:
                email = _get_email_by_id_for_detail(provider, raw_email_id)
            except HTTPException as he:
                if he.code == 404 and _need_imap_fallback:
                    # Primary provider (e.g. Gmail API) failed — try IMAP legacy provider
                    # This happens when emails were synced via IMAP (numeric UIDs)
                    # but the OAuth provider uses Gmail API (hex message IDs)
                    import os as _os_imap_chk
                    _has_imap_creds = bool(
                        _os_imap_chk.getenv("IMAP_HOST")
                        and _os_imap_chk.getenv("IMAP_USER")
                        and _os_imap_chk.getenv("IMAP_PASSWORD")
                    )
                    if _rh._is_web_request_context() or not _has_imap_creds:
                        # No IMAP credentials configured (OAuth-only user) — serve from SQLite
                        # with body_text/snippet as body rather than returning 404.
                        # In authenticated web requests, never fall back to
                        # env-level IMAP credentials: those are process-global
                        # and can belong to another tenant.
                        logger.debug(f"Email {raw_email_id}: no safe IMAP fallback, serving SQLite text fallback")
                        try:
                            with _rh.get_db_session() as _s:
                                _db = _rh.EmailRepository(_s).get_by_email_id(sqlite_lookup_id, account_id=_acct_id)
                                if _db:
                                    _labels = [] if is_sent_email else _get_email_labels(str(raw_email_id), account_id=_acct_id)
                                    _body_text = _db.body_text or _db.snippet or ""
                                    email_dict = {
                                        "id": email_id,
                                        "sender": _db.sender,
                                        "sender_name": _db.sender_name,
                                        "subject": _db.subject,
                                        "received_at": _to_iso_utc(_db.date) if _db.date else None,
                                        "has_attachments": bool(_db.attachments_meta),
                                        "attachments": [],
                                        "conversation_id": _db.thread_id,
                                        "is_read": _db.is_read,
                                        "body_preview": _body_text[:100],
                                        "has_pending_draft": sqlite_lookup_id in _get_pending_draft_email_ids(account_id=_acct_id),
                                        "labels": _labels,
                                        "body": _body_text,
                                        "body_html": None,
                                        "body_text": _body_text,
                                        "to": [r.strip() for r in _db.recipients.split(",") if r.strip()] if _db.recipients else [],
                                        "cc": [r.strip() for r in _db.cc.split(",") if r.strip()] if _db.cc else [],
                                    }
                                    _set_cached_email_detail(email_id, email_dict, account_id=_acct_id)
                                    _release_provider_detail_slot()
                                    return jsonify(email_dict)
                        except Exception as e:
                            logger.debug(f"Suppressed: {e}")
                        abort(404, description="Email not found")

                    logger.info(f"Email {raw_email_id}: primary provider 404, trying IMAP fallback")
                    email = None
                    try:
                        imap_provider = LegacyModuleLoader.email_provider()
                        if imap_provider.authenticate():
                            email = imap_provider.get_message_by_id(raw_email_id)
                            if hasattr(imap_provider, 'disconnect'):
                                imap_provider.disconnect()
                        if not email:
                            abort(404, description="Email not found")
                    except HTTPException:
                        raise
                    except Exception as imap_err:
                        logger.error(f"IMAP fallback failed for {raw_email_id}: {imap_err}")
                        abort(404, description="Email not found")
                else:
                    raise
            except Exception as quota_exc:
                if _is_provider_quota_backoff(quota_exc):
                    retry_after = getattr(
                        quota_exc, "retry_after", _PROVIDER_DETAIL_RETRY_AFTER_SECONDS
                    )
                    logger.warning(
                        "Email %s: provider quota backoff, retry_after=%ss",
                        email_id,
                        retry_after,
                    )
                    _release_provider_detail_slot()
                    if _headers_fallback_payload is not None:
                        return jsonify({
                            **_headers_fallback_payload,
                            "body_fetch_pending": True,
                            "provider_unavailable": True,
                            "provider_backoff": True,
                            "retry_after": retry_after,
                        })
                    return _provider_detail_quota_backoff_response(quota_exc)
                if _headers_fallback_payload is not None and _is_auth_expired_error(quota_exc):
                    logger.warning(
                        "Email %s: provider body fetch skipped, account needs reauth",
                        _sanitize_for_log(email_id),
                    )
                    _release_provider_detail_slot()
                    return jsonify({
                        **_headers_fallback_payload,
                        "body_fetch_pending": True,
                        "provider_unavailable": True,
                        "needs_reauth": True,
                    })
                raise
        email_dict = _email_to_full_dict(email, account_id=_acct_id)
        _provider_html = getattr(email, 'body_html', None)
        logger.info(
            "Email %s: provider returned body_html_len=%s, body_len=%s",
            email_id,
            len(_provider_html) if _provider_html else 0,
            len(email.body) if email.body else 0,
        )

        # Ensure attachments from provider are included in the response
        # (Gmail API returns them via _extract_attachment_metadata)
        if is_sent_email:
            email_dict["id"] = email_id  # Keep prefixed ID for consistency
            email_dict["labels"] = []    # No labels for sent emails

        # Cache the result in memory (only if body was retrieved)
        if email_dict.get("body"):
            _set_cached_email_detail(email_id, email_dict, account_id=_acct_id)

        # Persist attachment metadata, and body only in explicit legacy full-cache mode.
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                db_email = repo.get_by_email_id(raw_email_id if is_sent_email else sqlite_lookup_id, account_id=_acct_id)
                if db_email:
                    body_text = getattr(email, 'body', None) or email_dict.get('body_text', '')
                    body_html = getattr(email, 'body_html', None) or email_dict.get('body_html', '')
                    updated = False
                    persist_content = should_persist_email_content()
                    if persist_content:
                        if not db_email.body_text and body_text:
                            db_email.body_text = body_text
                            updated = True
                        _has_stale_cid = (
                            db_email.body_html is not None
                            and 'cid:' in db_email.body_html.lower()
                        )
                        if db_email.body_html is None or db_email.body_html == "" or _has_stale_cid:
                            # Store "" (not None) when HTML is absent — None means "never checked"
                            # Overwrite stale body_html that still contains unresolved cid: references
                            db_email.body_html = body_html or ""
                            updated = True
                        # Always backfill snippet from body_text for list preview
                        if not db_email.snippet and (body_text or db_email.body_text):
                            db_email.snippet = (body_text or db_email.body_text)[:200]
                            updated = True
                    # Persist attachment metadata so subsequent SQLite reads include it
                    _email_attachments = email_dict.get("attachments") or []
                    # Overwrite placeholder metadata (e.g. [{"has":true}]) with real attachment info
                    _has_real_meta = db_email.attachments_meta and '"filename"' in db_email.attachments_meta
                    if _email_attachments and not _has_real_meta:
                        import json as _json
                        db_email.attachments_meta = _json.dumps(_email_attachments)
                        updated = True
                    elif not _email_attachments and not _has_real_meta and db_email.attachments_meta:
                        # Provider returned no attachments — clear placeholder
                        db_email.attachments_meta = None
                        updated = True
                    if updated:
                        session.commit()
                        logger.info(f"Persisted metadata to SQLite for email {sqlite_lookup_id}")
        except Exception:
            pass  # Non-critical: memory cache still works

        _release_provider_detail_slot()
        return jsonify(email_dict)

    except HTTPException:
        _release_provider_detail_slot()
        raise
    except Exception as e:
        _release_provider_detail_slot()
        # exc_info=True surfaces the full traceback. Pre-fix we logged only
        # `{e}` which gave the message but not the stack — so when a transient
        # 500 was reported by a user (~21:02 UTC 2026-05-04), we couldn't
        # identify the root cause from logs. Cf. lessons.md
        # "[Frontend] Transient 5xx on /api/emails/<id>".
        logger.error(
            f"Error getting email {_sanitize_for_log(email_id)}: {e}",
            exc_info=True,
        )
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/<email_id>/attachments/<path:att_id>/download", methods=["GET"])
def download_email_attachment(email_id: str, att_id: str):
    """Télécharge une pièce jointe d'un email."""
    from urllib.parse import unquote

    att_id = unquote(att_id)
    is_sent_email = email_id.startswith("sent:")
    raw_email_id = email_id[5:] if is_sent_email else email_id

    if not _validate_email_id(raw_email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    from app.multi_accounts import get_account_manager, switch_account
    from flask import has_request_context
    _current = _get_current_account_for_user()
    if not _current:
        _manager = get_account_manager()
        _all = _manager.get_all_accounts()
        auth_user = getattr(g, 'auth_user', None) if has_request_context() else None
        uid = None
        if auth_user and auth_user.get("id"):
            try:
                uid = int(auth_user["id"])
                _all = [a for a in _all if a.user_id == uid]
            except (ValueError, TypeError) as exc:
                logger.debug("download attachment account auto-activate skipped: %s", exc)
        if len(_all) == 1:
            switch_account(_all[0].id, user_id=uid)
            _current = _get_current_account_for_user()
    _oauth_account_id = _current.id if _current else None

    try:
        from app.providers.factory import get_pooled_provider
        provider = get_pooled_provider(account_id=_oauth_account_id) if _oauth_account_id else _get_authenticated_provider()
    except Exception as _auth_exc:
        logger.error(f"download_email_attachment: auth failed: {_auth_exc}")
        return jsonify({"error": "Authentication failed"}), 401

    try:
        data_bytes, content_type, filename = provider.download_attachment(raw_email_id, att_id)
    except Exception as _e:
        logger.error(f"download_email_attachment {email_id}/{att_id}: {_e}")
        return jsonify({"error": "Attachment not found"}), 404

    from urllib.parse import quote as _quote
    safe_filename = _quote(filename)
    return Response(
        data_bytes,
        mimetype=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
            "Content-Length": str(len(data_bytes)),
        }
    )


@api_bp.route("/emails/<email_id>/attachments/download-all", methods=["GET"])
def download_all_email_attachments(email_id: str):
    """Télécharge toutes les pièces jointes d'un email en une archive zip.

    Un zip unique plutôt que N téléchargements : dans l'app desktop (Tauri),
    chaque téléchargement ouvre une boîte « Enregistrer sous » — N dialogues
    pour un seul clic serait inutilisable.
    """
    import io
    import re as _re
    import zipfile

    is_sent_email = email_id.startswith("sent:")
    raw_email_id = email_id[5:] if is_sent_email else email_id

    if not _validate_email_id(raw_email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    # Même résolution de compte que le téléchargement unitaire ci-dessus.
    from app.multi_accounts import get_account_manager, switch_account
    from flask import has_request_context
    _current = _get_current_account_for_user()
    if not _current:
        _manager = get_account_manager()
        _all = _manager.get_all_accounts()
        auth_user = getattr(g, 'auth_user', None) if has_request_context() else None
        uid = None
        if auth_user and auth_user.get("id"):
            try:
                uid = int(auth_user["id"])
                _all = [a for a in _all if a.user_id == uid]
            except (ValueError, TypeError) as exc:
                logger.debug("download-all account auto-activate skipped: %s", exc)
        if len(_all) == 1:
            switch_account(_all[0].id, user_id=uid)
            _current = _get_current_account_for_user()
    _oauth_account_id = _current.id if _current else None

    try:
        from app.providers.factory import get_pooled_provider
        provider = get_pooled_provider(account_id=_oauth_account_id) if _oauth_account_id else _get_authenticated_provider()
    except Exception as _auth_exc:
        logger.error(f"download_all_email_attachments: auth failed: {_auth_exc}")
        return jsonify({"error": "Authentication failed"}), 401

    # Liste des pièces jointes relue côté provider (jamais depuis le client) :
    # le provider est scoppé au compte courant, donc pas de fuite cross-tenant.
    try:
        email_obj = provider.get_message_by_id(raw_email_id)
    except Exception as _e:
        logger.error(f"download_all_email_attachments {email_id}: {_e}")
        email_obj = None
    if email_obj is None:
        return jsonify({"error": "Email not found"}), 404

    attachments = _filter_noise_attachments(getattr(email_obj, "attachments", None) or [])
    if not attachments:
        return jsonify({"error": "No attachments"}), 404

    def _safe_name(raw: str) -> str:
        cleaned = _re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", raw or "").lstrip(".").strip()
        return cleaned or "attachment"

    buf = io.BytesIO()
    used_names: set = set()
    # Audit 2026-06-10 F-02 : un échec unitaire ne doit JAMAIS produire un zip
    # silencieusement incomplet (200 indiscernable d'un succès total) — on
    # collecte les fichiers perdus pour les remonter au client via header.
    failed_names: list = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for att in attachments:
            att_id = att.get("id")
            if not att_id:
                failed_names.append(att.get("filename") or "attachment")
                continue
            try:
                data_bytes, _ct, fallback_name = provider.download_attachment(raw_email_id, att_id)
            except Exception as _e:
                logger.error(f"download_all {email_id}/{att_id}: {_e}")
                failed_names.append(att.get("filename") or str(att_id))
                continue
            name = _safe_name(att.get("filename") or fallback_name)
            base, counter = name, 1
            while name in used_names:
                counter += 1
                stem, dot, ext = base.rpartition(".")
                name = f"{stem} ({counter}).{ext}" if dot else f"{base} ({counter})"
            used_names.add(name)
            zf.writestr(name, data_bytes)

    if not used_names:
        return jsonify({"error": "Attachment not found"}), 404

    subject = (getattr(email_obj, "subject", "") or "").strip()
    zip_base = _safe_name(subject)[:80].strip() if subject else "pieces-jointes"
    from urllib.parse import quote as _quote
    safe_filename = _quote(f"{zip_base}.zip")
    payload = buf.getvalue()
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        "Content-Length": str(len(payload)),
    }
    if failed_names:
        # URL-encodé : les valeurs de header doivent rester latin-1 ; le FE
        # décode via decodeURIComponent (utils/downloadAttachment.ts).
        # Borné à 20 noms × 80 chars (review F5) : un header multi-Ko se fait
        # rejeter par les proxies edge et l'avertissement de succès partiel
        # se transformerait en échec réseau total.
        shown = [n[:80] for n in failed_names[:20]]
        headers["X-Failed-Attachments"] = ",".join(_quote(n) for n in shown)
    return Response(payload, mimetype="application/zip", headers=headers)


@api_bp.route("/emails/<email_id>/thread", methods=["GET"])
def get_email_thread(email_id: str):
    """
    Recupere tous les emails d'un thread/conversation.

    Args:
        email_id: ID de l'email dont on veut le thread.

    Returns:
        200: Liste des emails du thread triés chronologiquement
        400: email_id invalide
        401: Authentification échouée
        404: Email non trouve
        500: Erreur interne
    """
    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    try:
        provider = _get_authenticated_provider()

        # Resolve caller's DB account_id ONCE and thread it through every
        # layer (email lookup + thread fetch) so a collision on provider
        # email_id / thread_id cannot leak another tenant's data.
        _account_id = _resolve_account_id_for_provider(provider)

        def _with_detail_quota_deadline(fetch):
            if getattr(type(provider), "limited_quota_wait", None) is None:
                return fetch()
            limiter = getattr(provider, "limited_quota_wait", None)
            if callable(limiter):
                context = limiter(_PROVIDER_DETAIL_QUOTA_WAIT_SECONDS)
                if hasattr(context, "__enter__") and hasattr(context, "__exit__"):
                    with context:
                        return fetch()
            return fetch()

        # Find the original email — account-scoped to prevent IDOR.
        original_email = _with_detail_quota_deadline(
            lambda: _get_email_by_id(provider, email_id, account_id=_account_id)
        )
        conversation_id = original_email.conversation_id

        # If no conversation_id, return just this email
        if not conversation_id:
            return jsonify({
                "count": 1,
                "emails": [_email_to_full_dict(original_email, account_id=_account_id)]
            })

        # SQLite first: use indexed thread lookup instead of fetching 500 emails from IMAP.
        # If it only contains send-time placeholders, refresh from the provider so
        # the thread view does not miss older real messages in the same Gmail thread.
        thread_emails = []
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                cached_thread = repo.get_by_thread(conversation_id, _account_id)
                if cached_thread:
                    thread_emails = [_db_email_to_standard(e) for e in cached_thread]
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        should_fetch_provider_thread = _thread_cache_needs_provider_refresh(thread_emails, email_id)

        # Fallback to provider if SQLite has no thread data or only partial
        # placeholder-backed thread data.
        if should_fetch_provider_thread:
            if hasattr(provider, "get_thread_messages"):
                # Gmail: direct threads().get() API — fetches all messages (read+unread)
                provider_thread = _with_detail_quota_deadline(
                    lambda: provider.get_thread_messages(conversation_id)
                )
                if provider_thread:
                    thread_emails = _merge_provider_thread_with_cache(provider_thread, thread_emails)
            else:
                # IMAP/Outlook: search all messages (not just unread)
                all_emails = _with_detail_quota_deadline(
                    lambda: provider.get_messages(limit=200)
                )
                provider_thread = [
                    e for e in all_emails
                    if e.conversation_id == conversation_id
                ]
                if provider_thread:
                    thread_emails = provider_thread

        # Sort by date (oldest first for thread view)
        thread_emails.sort(key=lambda e: e.received_at or "")

        return jsonify({
            "count": len(thread_emails),
            "emails": [_email_to_full_dict(e, account_id=_account_id) for e in thread_emails]
        })

    except HTTPException:
        raise
    except Exception as e:
        if _is_provider_quota_backoff(e):
            logger.warning(
                "Email thread %s: provider quota backoff, retry_after=%ss",
                email_id,
                getattr(e, "retry_after", _PROVIDER_DETAIL_RETRY_AFTER_SECONDS),
            )
            return _provider_detail_quota_backoff_response(e)
        logger.error(f"Error getting email thread {_sanitize_for_log(email_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/generate", methods=["POST"])
def generate_preview():
    """
    Genere une preview de reponse IA sans creer de brouillon.
    ---
    tags:
      - Generate
    summary: Genere une preview de reponse IA pour un email
    description: |
      Endpoint pour le mode "Controle" de l'app Tauri.
      L'utilisateur peut ensuite Valider/Modifier/Ignorer la reponse generee.

    Rate limited: 10 calls per 60 seconds.

    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required:
              - email_id
            properties:
              email_id:
                type: string
                description: ID de l'email source
                example: "abc123"
              tone:
                type: string
                description: Ton de la reponse (optionnel)
                enum: [formal, friendly, neutral]
                example: "neutral"
    responses:
      200:
        description: Preview generee avec succes
        content:
          application/json:
            schema:
              type: object
              properties:
                success:
                  type: boolean
                  example: true
                email_id:
                  type: string
                  example: "abc123"
                classification:
                  type: string
                  description: Categorie de l'email
                  example: "QUESTION"
                priority:
                  type: integer
                  description: Score de priorite (1-5)
                  example: 3
                status:
                  type: string
                  description: Version du draft (V1 si valide directement, V2 si revise)
                  enum: [V1, V2]
                  example: "V1"
                draft:
                  type: object
                  properties:
                    subject:
                      type: string
                      example: "Re: Question about API"
                    body:
                      type: string
                      example: "Bonjour,\n\nMerci pour votre message..."
                    tokens_used:
                      type: integer
                      example: 150
                agents_trace:
                  type: array
                  items:
                    type: object
                  description: Trace des agents (vide pour l'instant)
      400:
        description: Requete invalide
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
                  example: "email_id is required"
      401:
        description: Authentification échouée
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
                  example: "Authentication failed"
      404:
        description: Email non trouve
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
                  example: "Email not found"
      500:
        description: Erreur interne
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
                  example: "An internal error occurred"
    """
    # H-8 (audit security.md, issue #534): per-tenant bucket. La clé
    # littérale "generate" mutualisait les 10 req/min cross-tenant — un
    # user pouvait DoS l'endpoint Anthropic paid pour tout le monde et
    # drainer le crédit du compte. Pattern aligné sur voice_intent (déjà
    # corrigé dans routes_misc.py).
    try:
        _aid = _resolve_account_id_cached()
    except Exception:
        _aid = "anonymous"
    allowed, retry_after = _rate_limited(
        f"generate:{_aid}", max_calls=10, window_seconds=60
    )
    if not allowed:
        return jsonify({"error": "Rate limit exceeded", "retry_after": retry_after}), 429

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    email_id = data.get("email_id")
    if not email_id:
        return jsonify({"error": "email_id is required"}), 400

    # Validate email_id format early to avoid unnecessary provider calls
    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    try:
        provider = _get_authenticated_provider()
        email = _get_email_by_id(provider, email_id)

        container = _rh._get_container()
        container.token_usage.reset()

        final_draft, status, classification, priority, _tier = _process_email_with_use_case(
            email, provider=provider, allow_faq_auto_send=False
        )

        return jsonify({
            "success": True,
            "email_id": email_id,
            "classification": classification,
            "priority": priority,
            "status": status,
            "draft": {
                "subject": _build_reply_subject(email.subject),
                "body": final_draft,
                "tokens_used": container.token_usage.total,
            },
            "agents_trace": [],
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating preview for email {_sanitize_for_log(email_id)}: {type(e).__name__}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/<email_id>/preview", methods=["POST"])
def preview_email(email_id: str):
    """
    Génère une preview de réponse IA pour un email (alias de /generate).
    ---
    tags:
      - Emails
    summary: Génère une preview de réponse IA
    parameters:
      - name: email_id
        in: path
        required: true
        description: ID de l'email
        schema:
          type: string
    responses:
      200:
        description: Preview générée avec succès
    """
    try:
        provider = _get_authenticated_provider()
        email = _get_email_by_id(provider, email_id)

        container = _rh._get_container()
        container.token_usage.reset()

        final_draft, status, classification, priority, _tier, details = _process_email_with_use_case(
            email, include_details=True, provider=provider, allow_faq_auto_send=False
        )

        # Extract commitments from generated draft
        commitments_data = []
        try:
            from app.agents import CommitmentExtractorAgent
            extractor = CommitmentExtractorAgent()
            commitments = extractor.extract(final_draft)
            commitments_data = [
                {"description": c.description, "deadline": c.deadline}
                for c in commitments
            ]
        except Exception as ce:
            logger.warning(f"Commitment extraction in preview failed: {ce}")

        return jsonify({
            "success": True,
            "email_id": email_id,
            "classification": classification,
            "priority": priority,
            "status": status,
            "draft": {
                "id": f"preview-{email_id}",
                "subject": _build_reply_subject(email.subject),
                "body": final_draft,
                "tokens_used": container.token_usage.total,
                "confidence": 0.85 if details["critique"]["is_valid"] else 0.65,
            },
            "pipeline_details": {
                "draft_v1": details["draft_v1"],
                "critique": details["critique"],
                "was_corrected": details["was_corrected"],
            },
            "commitments": commitments_data,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating preview for email {_sanitize_for_log(email_id)}: {type(e).__name__}")
        return jsonify({"error": "An internal error occurred"}), 500


def _passive_detect_contact_variant(account_id: int, sender_email: str, body: str) -> None:
    """Détecte et enregistre silencieusement la variante linguistique d'un contact.

    Priorité : adresse postale dans la signature > domaine email.
    Ne fait rien si une variante est déjà définie pour ce contact.
    Toutes les erreurs sont silencieusement ignorées.
    """
    try:
        from app.domain.entities.writing_style import (
            detect_variant_from_signature, detect_variant_from_domain,
        )
        from app.utils.signature import extract_signature_zone as _extract_signature_zone

        container = _rh._get_container()
        style_store = container.get_writing_style_store()
        profile = style_store.load(account_id)
        if not profile:
            return

        # Ne rien faire si ce contact n'est pas déjà un vrai contact
        # (contact_profiles ne doit contenir QUE des destinataires d'emails envoyés ;
        # la détection passive depuis un email entrant ne doit jamais créer d'entrée).
        key = sender_email.lower()
        existing = profile.contact_profiles.get(key)
        if not existing:
            return
        if existing.get('langue_variante'):
            return

        # 1) Essayer depuis la signature (adresse postale)
        variant = ''
        if body:
            signature_zone = _extract_signature_zone(body)
            if signature_zone:
                variant = detect_variant_from_signature(signature_zone)

        # 2) Fallback sur le domaine email
        if not variant:
            variant = detect_variant_from_domain(sender_email)

        if variant:
            profile.update_contact_profile(email=key, langue_variante=variant)
            style_store.save(profile)
            logger.info(f"[VARIANT] Variante '{variant}' détectée et enregistrée pour {key}")
    except Exception:
        pass  # Complètement silencieux — détection passive non-bloquante


def _parse_cached_email_received_at(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _validate_cached_email_string(payload: dict, key: str, max_length: int):
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        return None
    if len(value) > max_length:
        return None
    return value


def _validate_cached_email_list(payload: dict, key: str):
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    if len(value) > 100:
        return None
    cleaned = []
    for item in value:
        if not isinstance(item, str) or len(item) > MAX_SUBJECT_LENGTH:
            return None
        cleaned.append(item)
    return cleaned


def _standard_email_from_cached_process_payload(email_id: str, payload):
    """Build a request-scoped StandardEmail from the browser body cache.

    The object is used only in memory for draft generation. The caller must not
    persist its body in PendingDraft or any server-side email cache.
    """
    if payload is None:
        return None, None
    if not isinstance(payload, dict):
        return None, (jsonify({"error": "Invalid cached_email payload"}), 400)

    body = _validate_cached_email_string(payload, "body", MAX_BODY_LENGTH)
    body_text = _validate_cached_email_string(payload, "body_text", MAX_BODY_LENGTH)
    body_html = _validate_cached_email_string(payload, "body_html", MAX_BODY_LENGTH)
    sender = _validate_cached_email_string(payload, "sender", MAX_SUBJECT_LENGTH)
    sender_name = _validate_cached_email_string(payload, "sender_name", MAX_SUBJECT_LENGTH)
    subject = _validate_cached_email_string(payload, "subject", MAX_SUBJECT_LENGTH)
    conversation_id = _validate_cached_email_string(payload, "conversation_id", MAX_SUBJECT_LENGTH)
    to = _validate_cached_email_list(payload, "to")
    cc = _validate_cached_email_list(payload, "cc")

    validated_values = (
        body,
        body_text,
        body_html,
        sender,
        sender_name,
        subject,
        conversation_id,
        to,
        cc,
    )
    if any(value is None for value in validated_values):
        return None, (jsonify({"error": "Invalid cached_email payload"}), 400)

    visible_body = body or body_text or _strip_html_to_text(body_html or "")
    if not visible_body or not sender or not subject:
        return None, None

    from app.interfaces.email_provider import StandardEmail

    return StandardEmail(
        id=email_id,
        sender=sender,
        sender_name=sender_name or None,
        to=to,
        cc=cc,
        subject=subject,
        body=visible_body,
        body_html=body_html or None,
        received_at=_parse_cached_email_received_at(payload.get("received_at")),
        conversation_id=conversation_id or None,
        provider_source="client_cache",
        raw_metadata={"source": "local_email_body_cache"},
    ), None


def _standard_email_from_detail_cache(email_id: str, account_id: int | None):
    """Build a StandardEmail from the RAM-only detail cache when the body is ready."""
    cached = _get_cached_email_detail(email_id, account_id=account_id)
    if not _detail_payload_has_visible_body(cached):
        return None

    body_html = cached.get("body_html") or ""
    body = cached.get("body") or cached.get("body_text") or _strip_html_to_text(body_html)
    if not (body or "").strip():
        return None

    from app.interfaces.email_provider import StandardEmail

    return StandardEmail(
        id=email_id,
        sender=cached.get("sender") or "",
        sender_name=cached.get("sender_name") or None,
        to=cached.get("to") or [],
        cc=cached.get("cc") or [],
        subject=cached.get("subject") or "",
        body=body,
        body_html=body_html or None,
        received_at=_parse_cached_email_received_at(cached.get("received_at")),
        is_read=bool(cached.get("is_read", False)),
        has_attachments=bool(cached.get("has_attachments", False)),
        attachments=cached.get("attachments") or [],
        conversation_id=cached.get("conversation_id") or None,
        provider_source="detail_cache",
        raw_metadata={"source": "email_detail_cache"},
    )


def _wait_for_detail_cache_email(email_id: str, account_id: int | None):
    """Wait briefly for an in-flight detail body fetch to populate RAM cache."""
    deadline = _cache_time.perf_counter() + DRAFT_BODY_CACHE_WAIT_SECONDS
    while True:
        email = _standard_email_from_detail_cache(email_id, account_id)
        if email is not None:
            return email
        if not _is_body_fetch_inflight(email_id, account_id):
            return None
        remaining = deadline - _cache_time.perf_counter()
        if remaining <= 0:
            return None
        _cache_time.sleep(min(DRAFT_BODY_CACHE_POLL_SECONDS, remaining))


def _draft_history_status(status: str, details: dict | None) -> str:
    """Map router statuses to the legacy DraftRecord V1/V2/V3 analytics label."""
    if isinstance(details, dict):
        critique = details.get("critique")
        if isinstance(critique, dict) and critique.get("was_revised_v3"):
            return "V3"
        if details.get("was_corrected"):
            return "V2"
    status_text = str(status or "").upper()
    if "V3" in status_text:
        return "V3"
    if "V2" in status_text:
        return "V2"
    return "V1"


def _positive_int_or_none(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _record_pending_draft_history(
    *,
    email,
    email_id: str,
    account_id,
    draft_id: str,
    draft_v1: str,
    critique_text: str,
    final_draft: str,
    status: str,
    details: dict | None,
    priority,
    classification: str,
    processing_time_ms: int,
) -> None:
    """Persist draft analytics after PendingDraft is safely stored."""
    account_id_int = _positive_int_or_none(account_id)
    if account_id_int is None:
        logger.debug(
            "[DRAFT_HISTORY] skipped email_id=%s unresolved account_id=%s",
            _sanitize_for_log(email_id),
            account_id,
        )
        return

    try:
        from app.domain.entities.draft_history import DraftRecord

        priority_score = _positive_int_or_none(priority) or 50
        record = DraftRecord(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            email_id=email_id,
            email_sender=getattr(email, "sender", "") or "",
            email_subject=getattr(email, "subject", "") or "",
            email_preview=(getattr(email, "body", "") or "")[:200],
            draft_v1=draft_v1 or final_draft or "",
            critique=critique_text or "",
            draft_final=final_draft or "",
            status=_draft_history_status(status, details),
            account_id=account_id_int,
            draft_id=draft_id,
            tokens_used=0,
            model="",
            processing_time_ms=max(0, int(processing_time_ms or 0)),
            priority_score=priority_score,
            category=classification or None,
        )
        _rh._get_container().get_draft_history().add(record)
        logger.info(
            "[DRAFT_HISTORY] recorded email_id=%s account_id=%s draft_id=%s status=%s",
            _sanitize_for_log(email_id),
            account_id_int,
            draft_id,
            record.status,
        )
    except Exception as exc:
        logger.debug("[DRAFT_HISTORY] write skipped: %s", exc, exc_info=True)


def _process_email_draft_job(
    *,
    email_id: str,
    provider,
    cached_email,
    instructions: str,
    force_regen: bool,
    _bg_account_id,
    _bg_user_email: str,
    _process_enqueued_t0: float | None = None,
    _cancel_event=None,
    _email_body_from_request: bool = False,
) -> None:
    """Run the draft generation job outside the Flask request context.

    The HTTP handler calls this through the in-memory queue. RQ workers call the
    same function after recreating the provider from a serializable payload.
    """
    import uuid

    if _process_enqueued_t0 is None:
        _process_enqueued_t0 = _cache_time.perf_counter()
    _process_total_t0 = _process_enqueued_t0
    try:
        # Check if cancelled before doing any work
        if _cancel_event is not None and _cancel_event.is_set():
            _unregister_cancel_event(_bg_account_id, email_id)
            return

        # Fetching a full Gmail body can be slow when the list cache only
        # contains metadata. Keep the HTTP /process request fast; the
        # frontend already waits for draft_ready via WebSocket/polling.
        _email_load_t0 = _cache_time.perf_counter()
        _email_source = "browser_cache"
        if cached_email is not None:
            email = cached_email
        else:
            _cache_wait_t0 = _cache_time.perf_counter()
            email = _standard_email_from_detail_cache(email_id, _bg_account_id)
            if email is None:
                email = _wait_for_detail_cache_email(email_id, _bg_account_id)
            logger.info(
                "[PERF-DRAFT] phase=email_body_cache_wait email_id=%s "
                "account_id=%s hit=%s ms=%s",
                _sanitize_for_log(email_id),
                _bg_account_id,
                email is not None,
                int((_cache_time.perf_counter() - _cache_wait_t0) * 1000),
            )
            if email is not None:
                _email_source = "detail_cache"
            else:
                _email_source = "provider_or_db"
                limiter = getattr(provider, "limited_quota_wait", None)
                if callable(limiter):
                    with limiter(DRAFT_PROVIDER_QUOTA_WAIT_SECONDS):
                        email = _get_email_by_id(
                            provider, email_id, account_id=_bg_account_id
                        )
                else:
                    email = _get_email_by_id(
                        provider, email_id, account_id=_bg_account_id
                    )
        if not (getattr(email, "body", "") or "").strip():
            raise RuntimeError(
                "Le contenu de l'email est encore en chargement. "
                "Réessayez dans quelques secondes."
            )
        logger.info(
            "[PERF-DRAFT] phase=email_load email_id=%s account_id=%s "
            "source=%s body_chars=%s ms=%s",
            _sanitize_for_log(email_id),
            _bg_account_id,
            _email_source,
            len(getattr(email, "body", "") or ""),
            int((_cache_time.perf_counter() - _email_load_t0) * 1000),
        )

        # Détection passive de variante linguistique depuis la signature
        if _bg_account_id and not email_id.startswith("sent:"):
            _passive_detect_contact_variant(
                _bg_account_id,
                getattr(email, 'sender', '') or '',
                getattr(email, 'body', '') or '',
            )

        # For sent emails: the user IS the sender, so the reply should address
        # the recipient (not the sender).
        is_sent = email_id.startswith("sent:")
        reply_contact = email.sender
        reply_contact_name = getattr(email, 'sender_name', '') or ''
        if is_sent:
            original_to = getattr(email, 'to', []) or []
            if original_to:
                reply_contact = original_to[0]
                reply_contact_name = ''
                logger.info(f"Sent email detected: reply contact = {reply_contact}")

        # ── NOISE SKIP — no LLM call for automated/no-reply emails ──
        if not instructions:
            try:
                _label_store = _rh._get_container().get_label_store(account_id=_bg_account_id)
                _assignment = _label_store.get_assignment(email_id)
                if _assignment and _assignment.label == "Noise":
                    logger.info(f"[NOISE_SKIP] Email {email_id} classified as Noise, skipping draft generation")
                    # Remove any existing draft
                    store = _rh._get_container().get_pending_draft_store()
                    existing = store.get_by_email_id(email_id, account_id=_bg_account_id)
                    if existing:
                        store.remove(existing.id)
                    # Notify frontend (scoped to the current account)
                    try:
                        from app.api.websocket import emit_to_account
                        emit_to_account("daemon_event", {
                            "type": "draft_skipped",
                            "data": {
                                "email_id": email_id,
                                "reason": "noise",
                            }
                        }, _bg_account_id)
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                    return
            except Exception as _label_err:
                logger.debug(f"process: noise check failed, proceeding normally: {_label_err}")

        # Fetch conversation history ONCE (gated by USE_CONVERSATION_HISTORY)
        _conv_history = []
        from app.config import USE_CONVERSATION_HISTORY as _UCH
        if _UCH:
            try:
                _conv_history = _fetch_conversation_history_for_contact(provider, reply_contact, account_id=_bg_account_id)
            except Exception as conv_err:
                logger.debug(f"process: conversation history fetch failed: {conv_err}")

        # Override sender for sent emails
        if is_sent and reply_contact != email.sender:
            email.sender = reply_contact
            email.sender_name = reply_contact_name

        _use_case_t0 = _cache_time.perf_counter()
        final_draft, status, classification, priority, routing_tier, details = _process_email_with_use_case(
            email, provider=provider, instructions=instructions,
            conversation_history=_conv_history,
            use_streaming=True,
            include_details=True,
            _user_email=_bg_user_email,
            _account_id=_bg_account_id,
            force=force_regen,
            allow_faq_auto_send=False,
        )
        logger.info(
            "[PERF-DRAFT] phase=process_use_case email_id=%s account_id=%s "
            "status=%s tier=%s body_chars=%s draft_chars=%s ms=%s",
            _sanitize_for_log(email_id),
            _bg_account_id,
            status,
            routing_tier,
            len(getattr(email, "body", "") or ""),
            len(final_draft or ""),
            int((_cache_time.perf_counter() - _use_case_t0) * 1000),
        )

        # FAQ auto-sent — skip PendingDraft creation entirely
        if status == "FAQ_AUTO_SENT":
            logger.info(f"FAQ auto-sent for email {email_id}, skipping PendingDraft creation")
            store = _rh._get_container().get_pending_draft_store()
            existing = store.get_by_email_id(email_id, account_id=_bg_account_id)
            if existing:
                store.delete(existing.id)
                logger.info(f"  Cleaned up existing PendingDraft {existing.id}")

            # Background: mark as read + label badge + auto-archive if setting enabled
            _faq_eid = email_id
            _faq_prov = provider
            _faq_sent_id = details.get("faq_sent_message_id") if details else None

            def _faq_post_send_bg():
                try:
                    # 1. Mark as read
                    if hasattr(_faq_prov, "mark_as_read"):
                        _safe_call(_faq_prov.mark_as_read, _faq_eid)

                    # 2. Add "FAQ" badge label to original email AND sent reply
                    try:
                        from app.domain.entities.email_labels import LabelAssignment
                        _ls = _rh._get_container().get_label_store(account_id=_bg_account_id)

                        def _apply_faq_label(eid):
                            _a = _ls.get_assignment(eid)
                            if _a:
                                if "FAQ" not in _a.custom_labels:
                                    _a.custom_labels.append("FAQ")
                                    _a._rebuild_labels()
                            else:
                                _a = LabelAssignment(
                                    email_id=eid,
                                    custom_labels=["FAQ"],
                                    assigned_by="ai",
                                )
                            _ls.save_assignment(_a)

                        _apply_faq_label(_faq_eid)
                        if _faq_sent_id:
                            _apply_faq_label(f"sent:{_faq_sent_id}")
                    except Exception as _le:
                        logger.debug("[FaqAgent] Label badge failed: %s", _le)

                    # 3. Auto-archive if setting enabled
                    from app.api.settings import load_settings
                    _settings = load_settings()
                    if _settings.get("auto_archive_action", False):
                        if hasattr(_faq_prov, "archive_email"):
                            _safe_call(_faq_prov.archive_email, _faq_eid)
                        _evict_email_from_all_caches(_faq_eid, move_to_folder="archived")
                        try:
                            # S-07 fix: forward _bg_account_id captured BEFORE
                            # thread.start() so the event lands in the right
                            # user's room (bg thread has no Flask request ctx).
                            from app.api.websocket import emit_email_archived
                            emit_email_archived(_faq_eid, account_id=_bg_account_id)
                        except Exception as e:
                            logger.debug(f"Suppressed: {e}")
                        logger.info(
                            "[FaqAgent] Auto-archived email %s",
                            _sanitize_for_log(_faq_eid),
                        )

                    # 4. Invalidate sent cache so reply appears immediately
                    _evict_sent_sqlite_cache()
                except Exception as _e:
                    # S-16 fix: include traceback for ops debugging.
                    logger.warning(
                        "[FaqAgent] Post-send background failed: %s",
                        _e, exc_info=True,
                    )

            _rh.submit_background(_faq_post_send_bg)

            # Notify frontend via WebSocket (scoped to the current account)
            try:
                from app.api.websocket import emit_to_account
                emit_to_account("daemon_event", {
                    "type": "faq_auto_sent",
                    "email_id": email_id,
                    "payload": {},
                }, _bg_account_id)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
            return

        # BUG-G001 fix: SmartRouter.route() catches its own exceptions and
        # returns status="ERROR" with an empty draft instead of raising.
        # Without this guard the empty draft falls through to the
        # `_strip_clarification_draft` check and emits a misleading
        # "draft_skipped / no_reply_needed" instead of a real error.
        if status == "ERROR":
            logger.warning(f"SmartRouter returned ERROR status for {_sanitize_for_log(email_id)} — emitting draft_error")
            try:
                from app.api.websocket import emit_draft_error
                emit_draft_error(
                    email_id=email_id,
                    error="Erreur interne du pipeline IA — veuillez réessayer.",
                    account_id=_bg_account_id,
                )
            except Exception as _e:
                logger.debug(f"Suppressed: {_e}")
            return

        # Extract pipeline details for storage
        draft_v1 = ""
        critique_text = ""
        if details:
            draft_v1 = details.get("draft_v1", "")
            critique_raw = details.get("critique", "")
            if isinstance(critique_raw, dict):
                critique_text = (
                    critique_raw.get("explanation")
                    or critique_raw.get("feedback")
                    or ""
                )
                if critique_raw.get("suggestions"):
                    _suggestions = critique_raw["suggestions"]
                    if isinstance(_suggestions, list):
                        critique_text += "\n" + "\n".join(f"- {s}" for s in _suggestions)
            elif isinstance(critique_raw, str):
                critique_text = critique_raw

        # Extract pipeline transparency fields
        _classification_reason = ""
        _correction_details = None
        if details:
            _classification_reason = details.get("classification_reason", "")
            _correction_details = details.get("correction_details") or None

        # Post-LLM guard: discard drafts that explain why no reply is needed.
        # Quand l'utilisateur a explicitement demandé (force_regen=True)
        # ET fourni ses propres instructions, on respecte son intent —
        # le LLM ne doit pas second-guess sa volonté de répondre.
        # (Sans ce bypass, mobile drive-mode dictant sur un mail
        # auto-sender se voit toujours discarder en post-LLM même si
        # le prefilter a été contourné côté SmartRouter.)
        from app.smart_routing import _strip_clarification_draft
        _user_forced = bool(force_regen and instructions and instructions.strip())
        _checked = (final_draft or "") if _user_forced else _strip_clarification_draft(final_draft or "")
        if not _checked.strip():
            logger.info(f"[SKIP] Draft was a 'no reply needed' explanation, discarding for {email_id}")
            # Notify frontend via WebSocket (scoped to the current account)
            try:
                from app.api.websocket import emit_to_account
                emit_to_account("daemon_event", {
                    "type": "draft_skipped",
                    "data": {
                        "email_id": email_id,
                        "reason": "no_reply_needed",
                        "classification": classification,
                    }
                }, _bg_account_id)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
            return

        # Save as PendingDraft
        subject = _build_reply_subject(email.subject)
        draft_id = str(uuid.uuid4())

        quick_replies = None
        smart_suggestions = None
        specialty_info = None
        account_info = None
        if details:
            critique_raw = details.get("critique", {})
            if isinstance(critique_raw, dict):
                quick_replies = critique_raw.get("quick_replies")
                # DP-01 fix (2026-04-24): SmartRouter now produces smart_suggestions
                # in critique_info; extract here so the REST `/process` path matches
                # the daemon path and the frontend chips render.
                smart_suggestions = critique_raw.get("smart_suggestions")
                specialty_info = critique_raw.get("specialty")
                account_info = critique_raw.get("account_info")

        # Inject password into draft body immediately (replaces [MOT_DE_PASSE] placeholder)
        _pw_full_for_draft = None
        if account_info and account_info.get("action") == "password_reset":
            _pw_full_for_draft = account_info.get("_generated_password_full")
            if _pw_full_for_draft:
                _brand = account_info.get("brand_name") or ""
                _brand_label = f" sur {_brand}" if _brand else ""
                _pw_line = f"Votre nouveau mot de passe{_brand_label} : {_pw_full_for_draft}"
                if "[MOT_DE_PASSE]" in (final_draft or ""):
                    final_draft = final_draft.replace("[MOT_DE_PASSE]", _pw_line)
                    logger.info("[AccountAgent] Mot de passe injecté dans le brouillon (placeholder)")
                else:
                    # LLM n'a pas écrit le placeholder — injection de secours avant la dernière ligne
                    _lines = (final_draft or "").split("\n")
                    # trouver la dernière ligne non-vide pour insérer avant
                    _last_idx = len(_lines) - 1
                    while _last_idx > 0 and not _lines[_last_idx].strip():
                        _last_idx -= 1
                    _lines.insert(_last_idx, "")
                    _lines.insert(_last_idx, _pw_line)
                    final_draft = "\n".join(_lines)
                    logger.info("[AccountAgent] Placeholder absent — mot de passe injecté en position finale")
                # Update smart_routing draft cache so subsequent hits return the injected version
                try:
                    from app.smart_routing import _cache_draft as _sc_cache_draft
                    _sc_cache_draft(email_id, final_draft, account_id=_bg_account_id)
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")

        from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
        _persist_email_body = (
            should_persist_email_content()
            and not _email_body_from_request
            and bool(email.body)
        )

        # Build memory trace — capture what KB data was available to the Drafter
        _mem_trace = None
        _mem_trace_t0 = _cache_time.perf_counter()
        try:
            from app.domain.services.memory_trace_builder import build_memory_trace
            _mem_trace = build_memory_trace(
                account_id=_bg_account_id if _bg_account_id and _bg_account_id > 0 else None,
                contact_email=email.sender or "",
            )
        except Exception:
            pass
        finally:
            logger.info(
                "[PERF-DRAFT] phase=memory_trace email_id=%s account_id=%s "
                "has_trace=%s ms=%s",
                _sanitize_for_log(email_id),
                _bg_account_id,
                bool(_mem_trace),
                int((_cache_time.perf_counter() - _mem_trace_t0) * 1000),
            )

        pending_draft = PendingDraft(
            id=draft_id,
            email_id=email_id,
            email_sender=email.sender,
            email_sender_name=getattr(email, 'sender_name', '') or '',
            email_subject=email.subject,
            email_body=email.body[:2000] if _persist_email_body else "",
            email_received_at=email.received_at,
            draft_subject=subject,
            draft_body=final_draft,
            draft_v1=draft_v1,
            critique=critique_text,
            conversation_history=_conv_history,
            routing_tier=routing_tier or "",
            classification=classification,
            priority=int(priority) if priority else 50,
            status=PendingDraftStatus.PENDING,
            quick_replies=quick_replies,
            smart_suggestions=smart_suggestions,
            specialty_info=specialty_info,
            account_info=account_info,
            account_id=str(_bg_account_id) if _bg_account_id else str(_resolve_account_id_cached()),
            memory_trace=_mem_trace,
            classification_reason=_classification_reason,
            correction_details=_correction_details,
        )
        store = _rh._get_container().get_pending_draft_store()
        _store_add_t0 = _cache_time.perf_counter()
        store.add(pending_draft)
        _record_pending_draft_history(
            email=email,
            email_id=email_id,
            account_id=_bg_account_id,
            draft_id=draft_id,
            draft_v1=draft_v1,
            critique_text=critique_text,
            final_draft=final_draft,
            status=status,
            details=details,
            priority=priority,
            classification=classification,
            processing_time_ms=int((_cache_time.perf_counter() - _use_case_t0) * 1000),
        )
        logger.info(
            "[PERF-DRAFT] phase=pending_draft_store_add email_id=%s "
            "account_id=%s draft_id=%s ms=%s",
            _sanitize_for_log(email_id),
            _bg_account_id,
            draft_id,
            int((_cache_time.perf_counter() - _store_add_t0) * 1000),
        )

        # Store secure password in memory for Confirm button (WordPress API call)
        if _pw_full_for_draft:
            account_info.pop("_generated_password_full", None)
            store.store_secure_password(draft_id, _pw_full_for_draft)

        logger.info(f"Pending draft saved: {draft_id}")

        # Track generated AI draft for monthly recap. This path creates a
        # pending draft but does not always create a draft_history row.
        try:
            from app.draft_quality_tracker import get_tracker
            get_tracker().record_feature("compose_ai", account_id=str(_bg_account_id or ""))
        except Exception as _trk_err:
            logger.debug(f"Time-saved tracking (compose_ai) suppressed: {_trk_err}")
        try:
            from app.services.recap_tracker import get_recap_tracker
            get_recap_tracker().record_activity(
                account_id=_bg_account_id if _bg_account_id and _bg_account_id > 0 else None
            )
        except Exception as _recap_err:
            logger.debug(f"Recap activity tracking suppressed: {_recap_err}")

        # Record activity for admin analytics
        try:
            from app.api.admin import record_user_activity
            _user_email = getattr(g, 'auth_user', {}).get('email', '')
            if _user_email:
                record_user_activity(_user_email, 'compose_ai', {
                    'email_id': email_id,
                    'routing_tier': routing_tier or '',
                })
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        # Notify frontend via WebSocket (draft_ready + draft_complete events)
        # draft_ready  → refreshes email list, plays sound
        # draft_complete → triggers ReplyComposer stream subscriber (sets isComplete=true)
        #   Without draft_complete, ReplyComposer never exits "generating" state and
        #   relies solely on HTTP polling (which can time out before the LLM finishes).
        _ws_emit_t0 = _cache_time.perf_counter()
        try:
            # BUG-G001 fix (2026-04-26): use emit_to_account_or_room so that
            # draft_ready / draft_complete reach the frontend even when
            # _bg_account_id is -1 (sentinel — DB lookup failed). In that case
            # the WS room IS the user's email, which we captured as _bg_user_email
            # before the thread started.
            from app.api.websocket import emit_to_account, emit_to_account_or_room, emit_draft_complete
            # DP-02 fix (2026-04-24): use canonical payload helper. The previous
            # `{data: {...}}` shape was not parsed by the frontend's
            # `mapDaemonEvent` (websocket.ts:430-461) — the email list never
            # refreshed after a REST-triggered draft completed.
            from app.domain.entities.pending_draft import build_draft_ready_payload
            _dr_payload = build_draft_ready_payload(
                email_id=email_id,
                pending_draft_id=draft_id,
                draft_content=final_draft or "",
                subject=subject or "",
                confidence=0.90,
            )
            emit_to_account_or_room("daemon_event", {
                "type": "draft_ready",
                **_dr_payload,
            }, _bg_account_id, fallback_room=_bg_user_email)
            # Also emit draft_complete so the open ReplyComposer composer
            # gets the body immediately without waiting for HTTP polling.
            # S-09 fix: forward `_bg_account_id` so the event lands in
            # the right user's room (was previously namespace-broadcast
            # because the bg thread had no JWT in context).
            emit_draft_complete(
                email_id=email_id,
                draft_content=final_draft or "",
                confidence=0.9,
                generation_time_ms=0,
                tokens_used=0,
                tone_detected="professional",
                account_id=_bg_account_id,
                fallback_room=_bg_user_email,
            )
            # Extra event when an account action requires manual approval
            if account_info and account_info.get("status") == "pending":
                emit_to_account("daemon_event", {
                    "type": "account_pending",
                    "data": {
                        "draft_id": draft_id,
                        "email_id": email_id,
                        "action": account_info.get("action"),
                        "wp_username": account_info.get("wp_username"),
                    }
                }, _bg_account_id)
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        finally:
            logger.info(
                "[PERF-DRAFT] phase=draft_ws_emit email_id=%s "
                "account_id=%s ms=%s",
                _sanitize_for_log(email_id),
                _bg_account_id,
                int((_cache_time.perf_counter() - _ws_emit_t0) * 1000),
            )

        if smart_suggestions is None and len((email.body or "").strip()) >= 20:
            _suggest_subject = email.subject or subject or ""
            _suggest_body = email.body or ""
            _suggest_sender_name = getattr(email, "sender_name", "") or ""

            def _populate_smart_suggestions_bg():
                _ss_t0 = _cache_time.perf_counter()
                _has_suggestions = False
                try:
                    from app.prompts import _detect_language
                    from app.smart_routing import SmartRouter

                    _lang = _detect_language(
                        f"{_suggest_subject} {_suggest_body}",
                        fallback_language="FRENCH",
                    )
                    _suggestions = SmartRouter()._generate_smart_suggestions(
                        subject=_suggest_subject,
                        body=_suggest_body,
                        sender_name=_suggest_sender_name,
                        language=_lang,
                        account_id=_bg_account_id,
                    )
                    _has_suggestions = bool(_suggestions)
                    if not _suggestions:
                        return

                    _fresh_draft = store.get_by_id(draft_id)
                    if not _fresh_draft:
                        return

                    _fresh_draft.smart_suggestions = _suggestions
                    store.add(_fresh_draft)
                    _invalidate_pending_draft_cache(account_id=_bg_account_id)
                except Exception as _ss_bg_err:
                    logger.warning(
                        "smart_suggestions background update failed for %s: %s",
                        _sanitize_for_log(email_id),
                        _ss_bg_err,
                        exc_info=True,
                    )
                finally:
                    logger.info(
                        "[PERF-DRAFT] phase=smart_suggestions_background "
                        "email_id=%s account_id=%s draft_id=%s "
                        "has_suggestions=%s ms=%s",
                        _sanitize_for_log(email_id),
                        _bg_account_id,
                        draft_id,
                        _has_suggestions,
                        int((_cache_time.perf_counter() - _ss_t0) * 1000),
                    )

            _rh.submit_background(_populate_smart_suggestions_bg)

    except Exception as e:
        logger.error(f"Background process_email failed for {_sanitize_for_log(email_id)}: {e}", exc_info=True)
        # Build a user-friendly error message
        error_str = str(e)
        if "ANTHROPIC_API_KEY" in error_str or "api_key" in error_str.lower():
            user_error = "Clé API manquante — configurez ANTHROPIC_API_KEY dans Paramètres > Agentys AI."
        elif "401" in error_str or "Unauthorized" in error_str or "unauthorized" in error_str:
            user_error = "Clé API invalide ou expirée — vérifiez votre configuration dans Paramètres > Agentys AI."
        elif "model" in error_str.lower() and ("not found" in error_str.lower() or "invalid" in error_str.lower()):
            user_error = "Modèle IA non trouvé — vérifiez la configuration du modèle dans Paramètres > Agentys AI."
        else:
            user_error = error_str[:200]
        # Notify frontend of error via WebSocket (scoped to the current account).
        try:
            from app.api.websocket import emit_draft_error, emit_to_account_or_room

            try:
                account_id_int = (
                    int(_bg_account_id)
                    if _bg_account_id is not None
                    else None
                )
            except (TypeError, ValueError):
                account_id_int = None

            if account_id_int and account_id_int > 0:
                emit_draft_error(
                    email_id=email_id,
                    error=user_error,
                    account_id=account_id_int,
                )
            else:
                emit_to_account_or_room(
                    "draft_error",
                    {"email_id": email_id, "error": user_error, "retry_count": 0},
                    account_id_int,
                    fallback_room=_bg_user_email,
                )
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
    finally:
        logger.info(
            "[PERF-DRAFT] phase=process_background_total email_id=%s "
            "account_id=%s ms=%s",
            _sanitize_for_log(email_id),
            _bg_account_id,
            int((_cache_time.perf_counter() - _process_total_t0) * 1000),
        )
        if _cancel_event is not None:
            _unregister_cancel_event(_bg_account_id, email_id)


def _build_process_email_draft_payload(
    *,
    email_id: str,
    instructions: str,
    force_regen: bool,
    cached_email_payload,
    account_id,
    account_hash: str | None,
    user_email: str,
    user_id,
    task_id: str,
    email_body_from_request: bool,
) -> dict:
    return {
        "email_id": email_id,
        "instructions": instructions,
        "force_regen": bool(force_regen),
        "cached_email": cached_email_payload if isinstance(cached_email_payload, dict) else None,
        "account_id": account_id,
        "account_hash": account_hash or "",
        "user_email": user_email or "",
        "user_id": user_id,
        "task_id": task_id,
        "email_body_from_request": bool(email_body_from_request),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _account_config_from_db_account_id(account_id):
    try:
        db_account_id = int(account_id)
    except (TypeError, ValueError):
        return None
    if db_account_id <= 0:
        return None

    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        from app.multi_accounts import AccountConfig
        import hashlib

        with get_db_session() as session:
            db_account = AccountRepository(session).get(db_account_id)
            if db_account is None:
                return None
            email = str(getattr(db_account, "email", "") or "").strip()
            provider = str(getattr(db_account, "provider", "") or "").strip().lower()
            display_name = str(getattr(db_account, "display_name", "") or "").strip()
            signature_html = getattr(db_account, "signature_html", None)
            signature_text = getattr(db_account, "signature_text", None)
            user_id = getattr(db_account, "user_id", None)

        if not email or not provider:
            return None

        provider = {
            "google": "gmail",
            "microsoft": "outlook",
            "imap": "imap_smtp",
        }.get(provider, provider)
        if provider in {"gmail", "outlook"}:
            account_hash = hashlib.sha256(f"{provider}:{email}".encode()).hexdigest()[:16]
        else:
            account_hash = str(db_account_id)

        return AccountConfig(
            id=account_hash,
            name=display_name or email,
            email=email,
            provider=provider,
            signature=signature_text,
            signature_html=signature_html,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning(
            "Draft worker DB account fallback failed account_id=%s: %s",
            account_id,
            exc,
        )
        return None


def _create_provider_for_draft_payload(payload: dict):
    if _env_flag("AGENTYS_MOCK_EMAIL_PROVIDER"):
        from app.providers.mock_load_provider import LoadTestEmailProvider

        return LoadTestEmailProvider()

    from app.multi_accounts import create_provider_for_account, get_account_manager

    manager = get_account_manager()
    account = None
    account_hash = str(payload.get("account_hash") or "").strip()
    if account_hash:
        account = manager.get_account(account_hash)
    if account is None:
        user_email = str(payload.get("user_email") or "").strip()
        if user_email:
            account = manager.get_account_by_email(user_email)
    if account is None:
        account = _account_config_from_db_account_id(payload.get("account_id"))
    if account is not None:
        provider = create_provider_for_account(account)
        if provider.authenticate():
            return provider
        raise RuntimeError("Email provider authentication failed")

    provider = LegacyModuleLoader.email_provider()
    if not provider.authenticate():
        raise RuntimeError("Email provider authentication failed")
    return provider


def process_email_draft_payload(payload: dict) -> None:
    """Run a serialized draft job from RQ."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid draft job payload")

    email_id = str(payload.get("email_id") or "")
    if not email_id:
        raise ValueError("Missing email_id in draft job payload")

    cached_email = None
    cached_payload = payload.get("cached_email")
    if cached_payload is not None:
        cached_email, cached_error = _standard_email_from_cached_process_payload(
            email_id,
            cached_payload,
        )
        if cached_error:
            raise ValueError("Invalid cached_email payload")

    account_id = payload.get("account_id")
    user_id = payload.get("user_id")
    provider = _create_provider_for_draft_payload(payload)
    usage_tokens = None
    try:
        try:
            from app.infrastructure.cost_manager import set_usage_context

            usage_tokens = set_usage_context(
                account_id=account_id,
                user_id=user_id,
                feature="drafting",
            )
        except Exception:
            usage_tokens = None

        _process_email_draft_job(
            email_id=email_id,
            provider=provider,
            cached_email=cached_email,
            instructions=str(payload.get("instructions") or ""),
            force_regen=bool(payload.get("force_regen")),
            _bg_account_id=account_id,
            _bg_user_email=str(payload.get("user_email") or ""),
            _cancel_event=None,
            _email_body_from_request=bool(payload.get("email_body_from_request")),
        )
    finally:
        if usage_tokens is not None:
            try:
                from app.infrastructure.cost_manager import reset_usage_context

                reset_usage_context(usage_tokens)
            except Exception:
                pass
        try:
            disconnect = getattr(provider, "disconnect", None)
            if callable(disconnect):
                disconnect()
        except Exception:
            logger.debug("Draft worker provider disconnect failed", exc_info=True)


@api_bp.route("/draft-jobs/<task_id>", methods=["GET"])
def get_draft_job_status(task_id: str):
    """Return the shared Redis/RQ status for an asynchronous draft job."""
    task_id = (task_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", task_id):
        return jsonify({"error": "Invalid task ID"}), 400

    from app.infrastructure.draft_job_queue import get_draft_job_status as _get_status

    status = _get_status(task_id)
    if status is None:
        return jsonify({"task_id": task_id, "status": "unknown", "ready": False}), 404
    return jsonify({"task_id": task_id, **status}), 200


@api_bp.route("/emails/<email_id>/process", methods=["POST"])
def process_email(email_id: str):
    """
    Traite un email spécifique et génère un brouillon.
    ---
    tags:
      - Emails
    summary: Traite un email et génère un brouillon de réponse
    parameters:
      - name: email_id
        in: path
        required: true
        description: ID de l'email à traiter
        schema:
          type: string
    requestBody:
      required: false
      content:
        application/json:
          schema:
            type: object
            properties:
              instructions:
                type: string
                description: Instructions optionnelles pour la génération du brouillon
                maxLength: 500
              reply_type:
                type: string
                enum: [reply, reply_all]
                default: reply
                description: Type de réponse
    responses:
      200:
        description: Brouillon généré avec succès
        content:
          application/json:
            schema:
              type: object
              properties:
                success:
                  type: boolean
                draft_id:
                  type: string
                email_id:
                  type: string
                classification:
                  type: string
                priority:
                  type: string
                status:
                  type: string
                draft_preview:
                  type: string
                instructions:
                  type: string
                reply_type:
                  type: string
      404:
        description: Email non trouvé
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
      500:
        description: Erreur interne
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
    """
    # Early input validation — saves a provider auth roundtrip + returns
    # the expected 400 for malformed IDs, never a 503 (no provider) which
    # would hide the client-side bug.
    from app.api.routes_helpers import _validate_email_id
    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email ID"}), 400

    # Rate limit: max 30 LLM calls per 60s, per-tenant.
    # H-8 follow-up (issue #534): bucket key was the literal "process" — a
    # single user could DoS the LLM draft generation for the whole tenant
    # by saturating the global 30/min budget. Pattern aligned on
    # voice_draft / voice_intent / generate (already keyed).
    try:
        _aid = _resolve_account_id_cached()
    except Exception:
        _aid = "anonymous"
    if not _mock_load_test_rate_limit_bypass():
        allowed, retry_after = _rate_limited(f"process:{_aid}", max_calls=30, window_seconds=60)
        if not allowed:
            return jsonify({"error": "Rate limit exceeded", "retry_after": retry_after}), 429

    try:
        payload = request.get_json(silent=True) if request.is_json else {}
        if not isinstance(payload, dict):
            payload = {}

        instructions = payload.get("instructions", "") or ""
        if instructions:
            _, error = _validate_optional_string(
                instructions, "instructions", 500
            )
            if error:
                return error

        reply_type = payload.get("reply_type", "reply") or "reply"
        if reply_type not in ("reply", "reply_all"):
            reply_type = "reply"

        force_regen = payload.get("force", False)
        cached_email_payload = payload.get("cached_email")
        cached_email, cached_email_error = _standard_email_from_cached_process_payload(
            email_id,
            cached_email_payload,
        )
        if cached_email_error:
            return cached_email_error

        provider = _get_authenticated_provider()
        _email_body_from_request = cached_email is not None
        if cached_email is not None:
            logger.info(
                "process: using browser local body cache for %s",
                _sanitize_for_log(email_id),
            )

        # Skip if a pending draft already exists (prevent duplicate generation
        # from concurrent triggers: daemon, relabel backend, or manual request)
        # force_regen param allows the frontend "Processus IA" button to bypass cache
        if not instructions and not force_regen:
            existing_store = _rh._get_container().get_pending_draft_store()
            # Audit 2026-04-25 CRIT-Iso-3: scope to caller account so an IMAP
            # UID collision across two accounts can't return another tenant's
            # draft preview.
            try:
                _ed_aid = str(_resolve_account_id_cached())
            except Exception:
                _ed_aid = None
            existing_draft = existing_store.get_by_email_id(email_id, account_id=_ed_aid)
            if existing_draft:
                _existing_priority = getattr(existing_draft, "priority", 50)
                if not isinstance(_existing_priority, (int, float)):
                    _existing_priority = 50
                _existing_classification = getattr(existing_draft, "classification", "")
                if not isinstance(_existing_classification, str):
                    _existing_classification = ""
                return jsonify({
                    "success": True,
                    "draft_id": existing_draft.id,
                    "email_id": email_id,
                    "classification": _existing_classification,
                    "priority": int(_existing_priority),
                    "status": "existing",
                    "draft_preview": _truncate_text(existing_draft.draft_body, 500),
                    "instructions": "",
                    "reply_type": reply_type,
                })
        if force_regen:
            # Remove old draft so the new one replaces it
            try:
                existing_store = _rh._get_container().get_pending_draft_store()
                try:
                    _force_aid = str(_resolve_account_id_cached())
                except Exception:
                    _force_aid = None
                existing_draft = existing_store.get_by_email_id(email_id, account_id=_force_aid)
                if existing_draft:
                    # DP-05 fix (2026-04-24): pending_draft_store exposes .delete(), not .remove().
                    # The previous .remove() raised AttributeError silently swallowed by the
                    # outer try/except, leaving the stale draft in place — so force_regen
                    # never actually replaced anything.
                    existing_store.delete(existing_draft.id)
                    logger.info(f"Removed old draft for forced regeneration: {existing_draft.id}")
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
            # Also evict from SmartRouter in-memory/disk cache. Scope to
            # the caller's account so we don't drop other users' cached
            # drafts that happen to share the same email_id (cf. C-3).
            try:
                from app.smart_routing import evict_draft_cache
                try:
                    _evict_aid = _resolve_account_id_cached()
                except Exception:
                    _evict_aid = None
                evict_draft_cache(email_id, account_id=_evict_aid)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

        # Capture request-context values before background thread starts
        # (g not available in threads — values captured here in request context)
        _bg_user_email = ""
        _bg_user_id = None
        _bg_account_id = None
        _bg_account_hash = None
        try:
            try:
                from app.api._auth_helpers import get_auth_user_id

                _bg_user_id = get_auth_user_id()
            except Exception:
                _bg_user_id = None
            _bg_account = _get_current_account_for_user()
            _bg_user_email = _bg_account.email if _bg_account else ""
            _bg_account_hash = getattr(_bg_account, "id", None) if _bg_account else None
            if _bg_user_id is None and _bg_account is not None:
                try:
                    _raw_user_id = getattr(_bg_account, "user_id", None)
                    _bg_user_id = int(_raw_user_id) if _raw_user_id is not None else None
                except (TypeError, ValueError):
                    _bg_user_id = None
            _load_test_account_id = _mock_load_test_account_header()
            if _load_test_account_id is not None:
                _bg_account_id = _load_test_account_id
            else:
                _bg_resolved = _resolve_account_id_cached()
                if _bg_resolved is not None:
                    _bg_account_id = _bg_resolved
            if _bg_account_id is None:
                _provider_account_id = _resolve_account_id_for_provider(provider)
                if _provider_account_id is not None:
                    _bg_account_id = _provider_account_id
        except Exception as acct_err:
            logger.debug(f"process: account resolution failed, using defaults: {acct_err}")

        # Generate a task_id for tracking
        import uuid
        task_id = str(uuid.uuid4())

        from app.infrastructure.draft_job_queue import draft_queue_backend, enqueue_draft_job

        _queue_backend = draft_queue_backend()
        # Register a cancellation event so the caller can abort this task.
        # Scoped by (account_id, email_id) because provider email_ids are only
        # unique per account. External workers cannot observe the in-memory
        # cancellation registry, so cancellation stays local to the memory backend.
        _cancel_event = (
            None
            if _queue_backend == "redis"
            else _register_cancel_event(_bg_account_id, email_id)
        )
        _process_enqueued_t0 = _cache_time.perf_counter()

        # Return 202 Accepted immediately — draft will arrive via WebSocket
        # This prevents blocking the HTTP thread for 5-20s during LLM calls.
        def _process_with_usage_context():
            usage_tokens = None
            try:
                try:
                    from app.infrastructure.cost_manager import set_usage_context

                    usage_tokens = set_usage_context(
                        account_id=_bg_account_id,
                        user_id=_bg_user_id,
                        feature="drafting",
                    )
                except Exception:
                    usage_tokens = None
                _process_email_draft_job(
                    email_id=email_id,
                    provider=provider,
                    cached_email=cached_email,
                    instructions=instructions,
                    force_regen=force_regen,
                    _bg_account_id=_bg_account_id,
                    _bg_user_email=_bg_user_email,
                    _process_enqueued_t0=_process_enqueued_t0,
                    _cancel_event=_cancel_event,
                    _email_body_from_request=_email_body_from_request,
                )
            finally:
                if usage_tokens is not None:
                    try:
                        from app.infrastructure.cost_manager import reset_usage_context

                        reset_usage_context(usage_tokens)
                    except Exception:
                        pass

        _job_key = f"{_bg_account_id if _bg_account_id not in (None, '', -1) else '__global__'}:{email_id}"
        _job_payload = _build_process_email_draft_payload(
            email_id=email_id,
            instructions=instructions,
            force_regen=force_regen,
            cached_email_payload=cached_email_payload,
            account_id=_bg_account_id,
            account_hash=_bg_account_hash,
            user_email=_bg_user_email,
            user_id=_bg_user_id,
            task_id=task_id,
            email_body_from_request=_email_body_from_request,
        )
        submission = enqueue_draft_job(
            key=_job_key,
            account_id=_bg_account_id,
            email_id=email_id,
            task_id=task_id,
            run=_process_with_usage_context,
            payload=_job_payload,
        )

        if submission.full:
            if _cancel_event is not None:
                _unregister_cancel_event(_bg_account_id, email_id)
            rejection_reason = getattr(submission, "rejection_reason", "") or submission.status
            logger.warning(
                "[DRAFT-QUEUE] status=full email_id=%s account_id=%s "
                "queue_status=%s reason=%s backend=%s queue_depth=%s queue_max=%s "
                "active_workers=%s active_for_account=%s retry_after=%s",
                _sanitize_for_log(email_id),
                _bg_account_id,
                submission.status,
                rejection_reason,
                getattr(submission, "backend", "unknown"),
                submission.queue_depth,
                submission.queue_max,
                submission.active_workers,
                submission.active_for_account,
                submission.retry_after_seconds,
            )
            response = jsonify({
                "error": "Draft generation queue is full",
                "status": "busy",
                "queue_status": submission.status,
                "reason": rejection_reason,
                "backend": getattr(submission, "backend", "unknown"),
                "email_id": email_id,
                "task_id": task_id,
                "retry_after": submission.retry_after_seconds,
                "queue_depth": submission.queue_depth,
                "queue_max": submission.queue_max,
                "active_workers": submission.active_workers,
                "active_for_account": submission.active_for_account,
            })
            response.headers["Retry-After"] = str(submission.retry_after_seconds)
            return response, 429

        if submission.duplicate:
            logger.info(
                "[DRAFT-QUEUE] status=duplicate email_id=%s account_id=%s "
                "task_id=%s queue_depth=%s active_workers=%s",
                _sanitize_for_log(email_id),
                _bg_account_id,
                submission.task_id,
                submission.queue_depth,
                submission.active_workers,
            )
        else:
            # Detach provider only for in-process jobs. Redis/RQ workers recreate
            # their own provider, so the request provider should close normally.
            if getattr(submission, "backend", "memory") == "memory":
                _detach_provider_from_request(provider)
            logger.info(
                "[DRAFT-QUEUE] status=enqueued email_id=%s account_id=%s "
                "task_id=%s queue_depth=%s active_workers=%s active_for_account=%s",
                _sanitize_for_log(email_id),
                _bg_account_id,
                task_id,
                submission.queue_depth,
                submission.active_workers,
                submission.active_for_account,
            )

        # Return 202 immediately — frontend will receive result via WebSocket
        return jsonify({
            "success": True,
            "email_id": email_id,
            "task_id": submission.task_id,
            "status": "processing",
            "message": "Draft generation started. Result will arrive via WebSocket.",
            "queue_status": submission.status,
            "queue_depth": submission.queue_depth,
            "status_url": f"/api/draft-jobs/{submission.task_id}",
        }), 202

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing email {_sanitize_for_log(email_id)}: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while processing email"}), 500


@api_bp.route("/emails/<email_id>/cancel-process", methods=["POST"])
def cancel_process_email(email_id: str):
    """Annule la génération de brouillon en cours pour un email."""
    _acct_id = _resolve_account_id_cached()
    with _cancel_registry_lock:
        event = _cancel_registry.get(_cancel_key(_acct_id, email_id))

    if event is None:
        return jsonify({"success": False, "message": "No active processing task for this email"}), 404

    event.set()
    logger.info(f"Cancellation requested for email {_sanitize_for_log(email_id)}")

    # Notify frontend via WebSocket so the workflow status updates immediately
    try:
        from app.api.websocket import emit_to_account
        emit_to_account("daemon_event", {
            "type": "processing_cancelled",
            "data": {"email_id": email_id}
        }, _acct_id)
    except Exception as e:
        logger.debug(f"Suppressed WebSocket notify on cancel: {e}")

    return jsonify({"success": True, "email_id": email_id, "status": "cancelling"}), 200


def _build_reply_subject(original_subject: str) -> str:
    """Construit le sujet de réponse (ajoute Re: si nécessaire)."""
    if original_subject.lower().startswith("re:"):
        return original_subject
    return f"Re: {original_subject}"


def _truncate_text(text: str, max_length: int) -> str:
    """Tronque le texte à la longueur maximale avec ellipse."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


@api_bp.route("/emails/<email_id>/draft", methods=["POST"])
def create_draft_from_content(email_id: str):
    """
    Crée un brouillon à partir d'un contenu fourni par l'utilisateur.

    Cet endpoint permet de sauvegarder un brouillon après validation/modification
    de la preview par l'utilisateur (mode "Contrôle").

    Args:
        email_id: ID de l'email original.

    Body JSON:
        subject: Sujet du brouillon (requis, non vide)
        body: Corps du brouillon (requis, peut être vide)

    Returns:
        201: Brouillon créé avec succès
        400: Validation échouée
        401: Authentification échouée
        404: Email non trouvé
        500: Erreur interne
    """
    data, error = require_json()
    if error:
        return error

    subject = data.get("subject")
    body = data.get("body")

    if subject is None or not isinstance(subject, str):
        return jsonify({"error": "subject is required and must be a string"}), 400

    if not subject.strip():
        return jsonify({"error": "subject cannot be empty"}), 400

    # Security: Limit subject length to prevent DoS
    if len(subject) > MAX_SUBJECT_LENGTH:
        return jsonify({"error": f"subject exceeds maximum length of {MAX_SUBJECT_LENGTH} characters"}), 400

    if body is None or not isinstance(body, str):
        return jsonify({"error": "body is required and must be a string"}), 400

    # Security: Limit body length to prevent DoS
    if len(body) > MAX_BODY_LENGTH:
        return jsonify({"error": f"body exceeds maximum length of {MAX_BODY_LENGTH} characters"}), 400

    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    # Optional: custom recipients (for reply_all / forward)
    to_raw = data.get("to")
    cc_raw = data.get("cc")
    to_list = None
    cc_list = None
    if to_raw and isinstance(to_raw, list):
        to_list = [t.strip() for t in to_raw if isinstance(t, str) and t.strip()]
    if cc_raw and isinstance(cc_raw, list):
        cc_list = [c.strip() for c in cc_raw if isinstance(c, str) and c.strip()]

    bcc_raw = data.get("bcc")
    bcc_list = None
    if bcc_raw and isinstance(bcc_raw, list):
        bcc_list = [b.strip() for b in bcc_raw if isinstance(b, str) and b.strip()]

    # Optional: attachments as base64-encoded objects
    attachments_raw = data.get("attachments")
    attachments = None
    if attachments_raw and isinstance(attachments_raw, list):
        import base64 as b64
        MAX_TOTAL_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB
        attachments = []
        total_size = 0
        for att in attachments_raw:
            if not isinstance(att, dict):
                continue
            filename = att.get("filename", "")
            data_b64 = att.get("data_base64", "")
            content_type = att.get("content_type", "application/octet-stream")
            if not filename or not data_b64:
                continue
            # Sanitize filename: strip path traversal and directory separators
            import os as _os
            filename = _os.path.basename(filename).replace("\x00", "")
            if not filename or filename.startswith("."):
                filename = "attachment"
            try:
                file_bytes = b64.b64decode(data_b64)
            except Exception:
                return jsonify({"error": f"Invalid base64 for attachment '{filename}'"}), 400
            total_size += len(file_bytes)
            if total_size > MAX_TOTAL_ATTACHMENT_SIZE:
                return jsonify({"error": "Total attachment size exceeds 25 MB"}), 400
            attachments.append((filename, file_bytes, content_type))
        if not attachments:
            attachments = None

    # Only a real JSON boolean true may send. Strings like "false" are truthy
    # in Python and must never accidentally turn a draft request into a send.
    send_immediately = data.get("send") is True
    archive_after = data.get("archive") is True

    try:
        provider = _get_authenticated_provider()
        _request_account_id = _resolve_account_id_for_provider(provider)
        email = _get_email_for_reply_action(provider, email_id, _request_account_id)

        from app.utils.signature import append_signature
        body_with_signature = append_signature(
            body,
            account_id=_request_account_id,
            recipient_email=email.sender,
        )
        recipients = to_list if to_list else [email.sender]
        _raw_thread_id = getattr(email, "conversation_id", None) or getattr(email, "thread_id", None)
        _thread_id = _raw_thread_id.strip() if isinstance(_raw_thread_id, str) and _raw_thread_id.strip() else None

        if send_immediately:
            duplicate_sent_id = _find_recent_sent_reply(
                account_id=_request_account_id,
                subject=subject,
                recipients=recipients,
                body=body,
                body_with_signature=body_with_signature,
                thread_id=_thread_id,
            )
            if duplicate_sent_id:
                logger.info(
                    "duplicate reply send suppressed email_id=%s account_id=%s sent_id=%s",
                    _sanitize_for_log(email_id),
                    _request_account_id,
                    _sanitize_for_log(duplicate_sent_id),
                )
                return jsonify({
                    "success": True,
                    "draft_id": "sent-directly",
                    "email_id": email_id,
                    "sent": duplicate_sent_id,
                    "duplicate": True,
                }), 200

        sent = False
        draft_id = None

        _provider_name = getattr(provider, 'PROVIDER_NAME', '')
        _provider_supports_bcc = _provider_name in ('outlook',)  # Outlook send_reply_directly handles BCC
        if send_immediately and hasattr(provider, 'send_reply_directly') and (not bcc_list or _provider_supports_bcc):
            # Fast path: single API call (messages.send) instead of create_draft + send_draft
            # Outlook supports BCC in send_reply_directly; Gmail does not
            # Resolve thread_id — only pass valid Gmail hex IDs, not IMAP UIDs
            _raw_thread_id = getattr(email, 'thread_id', None) or getattr(email, 'conversation_id', None)
            _valid_thread_id = _raw_thread_id if (_raw_thread_id and len(_raw_thread_id) >= 12 and not _raw_thread_id.isdigit()) else None
            _reply_kwargs = {
                "to": recipients,
                "subject": subject,
                "body": body_with_signature,
                "reply_to_id": email.id,
                "cc": cc_list,
                "attachments": attachments,
                "thread_id": _valid_thread_id,
                "is_html": True,
            }
            if _provider_name == 'gmail':
                _raw_meta = getattr(email, "raw_metadata", None) or {}
                if isinstance(_raw_meta, dict):
                    _message_id_header = (
                        _raw_meta.get("message_id")
                        or _raw_meta.get("Message-ID")
                        or _raw_meta.get("message_id_header")
                    )
                    if _message_id_header:
                        _reply_kwargs["message_id_header"] = _message_id_header
            if _provider_supports_bcc:
                _reply_kwargs["bcc"] = bcc_list
            sent = provider.send_reply_directly(**_reply_kwargs)
            if sent:
                draft_id = "sent-directly"
            else:
                logger.warning(f"send_reply_directly failed for email_id={_sanitize_for_log(email_id)}, falling back to 2-step")

        if not sent:
            # Fallback: create draft (+ optionally send via 2-step)
            draft_id = _create_draft_and_mark_read_no_bg(
                provider, email, subject, body,
                to=to_list, cc=cc_list, bcc=bcc_list,
                attachments=attachments,
                account_id=_request_account_id,
            )
            if send_immediately and draft_id:
                sent = provider.send_draft(draft_id)
                if not sent:
                    logger.warning(f"send_draft returned False after fallback for {_sanitize_for_log(str(draft_id))}, trying send_email directly")
                    # IMAP_SMTP: send_draft uses in-memory dict (IMAP UID doesn't match) — send directly via SMTP
                    try:
                        sent = provider.send_email(
                            to=recipients,
                            subject=subject,
                            body=body_with_signature,
                            cc=cc_list or None,
                            is_html=True,
                            attachments=attachments,
                        )
                    except Exception as _se:
                        logger.error(f"send_email fallback also failed: {_se}")
                        # Audit Cluster D (2026-05-17) B-08: capture the
                        # blocking-layer error so downstream surfaces report
                        # the actually-blocking failure (send_email), not
                        # whatever `send_draft._last_error` was already
                        # holding from the earlier path.
                        try:
                            provider._last_error = str(_se)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                if not sent:
                    return jsonify({"error": "Draft created but send failed"}), 502

        if sent:
            # Post-send: move original email to archived in SQLite (instead of
            # deleting) so it remains findable in the archives view.
            _evict_email_from_all_caches(email_id, move_to_folder="archived")

            # Bump Contact.sent_count + ensure ContactStyleProfile for recipients
            try:
                from app.api.routes_helpers import record_sent_recipients
                _all_rcpts = list(recipients or [])
                if cc_list:
                    _all_rcpts.extend(cc_list)
                if bcc_list:
                    _all_rcpts.extend(bcc_list)
                record_sent_recipients(_request_account_id, _all_rcpts)
            except Exception as _rc_err:
                # Audit Cluster C (2026-05-11) B-10: failures here silently
                # degrade per-contact style learning forever. Promote so ops
                # can see the rot.
                logger.warning(
                    "record_sent_recipients (reply) failed: %s",
                    _rc_err, exc_info=True,
                )

            # Insert reply into SQLite sent cache for immediate visibility
            try:
                _account_id = _request_account_id
                with _rh.get_db_session() as _sess:
                    from app.db.repositories import AccountRepository as _AccountRepository
                    _sender_db_account = _AccountRepository(_sess).get(_account_id)
                    _sender_email = getattr(provider, '_email', '') or (getattr(_sender_db_account, 'email', '') if _sender_db_account else '') or ''
                    _sender_name = (getattr(_sender_db_account, 'display_name', '') or '') if _sender_db_account else ''
                    _repo = _rh.EmailRepository(_sess)
                    _now = datetime.now(timezone.utc).replace(tzinfo=None)
                    _persist_content = should_persist_email_content()
                    _sent_email = Email(
                        email_id=f"reply-{int(_now.timestamp())}",
                        account_id=_account_id,
                        thread_id=getattr(email, 'conversation_id', None),
                        subject=subject or '',
                        sender=_sender_email,
                        sender_name=_sender_name,
                        recipients=",".join(recipients) if recipients else '',
                        date=_now,
                        body_text=(body or '') if _persist_content else None,
                        body_html=body_with_signature if _persist_content else None,
                        snippet=(body[:200] if body else '') if _persist_content else None,
                        is_read=True,
                        is_starred=False,
                        is_sent=True,
                        attachments_meta='[{"has":true}]' if attachments else None,
                    )
                    _repo.create(_sent_email)
                    try:
                        _repo.dedupe_sent_by_content(_account_id)
                    except Exception as _dedup_err:
                        logger.debug(f"reply dedupe failed: {_dedup_err}")
                    _sess.commit()
            except Exception as _ins_err:
                logger.warning(f"Failed to insert sent reply into cache: {_ins_err}")

            _invalidate_folder_cache("sent")

            # Quick Steps: re-evaluate auto-triggers on the original inbox
            # email now that the user replied. Enables rules of the form
            # "thread_has_user_reply=true → archive" — the modern,
            # configurable replacement for the global "auto-archive after
            # reply" setting. Dedup audit row prevents re-fires.
            try:
                from app.quicksteps.auto_trigger import run_auto_triggers_async
                run_auto_triggers_async(_request_account_id, email_id, email)
            except Exception as _qs_err:
                logger.debug(f"post-reply qs re-eval suppressed: {_qs_err}")

            # Fire firesOn="sent" Quick Steps on the freshly-sent reply so
            # rules like "Follow-up existing thread" (reply with a question)
            # can match it — same immediate pass as the compose path.
            try:
                from app.api.quicksteps_scheduler import fire_sent_quicksteps_immediate
                from app.quicksteps.types import SentEmailRef
                _fu_acct = str(_resolve_account_id_cached())
                _fu_now = datetime.now(timezone.utc)
                _fu_id = f"reply-{int(_fu_now.timestamp())}"
                _fu_thread = (
                    getattr(provider, "_last_sent_thread_id", "")
                    or getattr(email, "conversation_id", "")
                    or ""
                )
                # Reply: the To list is the original sender — that's
                # who we're following up with. Pick the first recipient.
                _fu_recipient = (recipients[0] if recipients else "") or ""
                _fu_record = SentEmailRef(
                    id=_fu_id,
                    recipient=_fu_recipient,
                    subject=subject or "(Sans objet)",
                    body_preview=body[:1000] if body else "",
                    thread_id=_fu_thread,
                )
                # Fire custom firesOn="sent" Quick Steps on the freshly-sent
                # reply (e.g. "Follow-up existing thread"). The snoozed-draft
                # handler applies its own availability-email skip.
                fire_sent_quicksteps_immediate(_fu_record, _fu_acct)
            except Exception as _fu_err:
                logger.debug(f"Sent-side Quick Step fire (reply) failed: {_fu_err}")

            _eid = email_id
            _do_archive = archive_after
            # S-07 fix: capture account_id BEFORE thread.start() so the bg
            # emit lands in the right user's room (the bg thread has no
            # Flask request context — _resolve_ws_room() would return None
            # and the previous behavior was a namespace-wide broadcast).
            _post_send_account_id = _request_account_id
            _detach_provider_from_request(provider)
            def _post_send_bg():
                try:
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        pool.submit(_safe_call, provider.mark_as_read, _eid)
                        if _do_archive:
                            pool.submit(_safe_call, provider.archive_email, _eid)
                    # Re-evict cache after archive completes (prevents stale cache race)
                    if _do_archive:
                        _evict_email_from_all_caches(_eid, move_to_folder="archived")
                        try:
                            from app.api.websocket import emit_email_archived
                            emit_email_archived(_eid, account_id=_post_send_account_id)
                        except Exception as e:
                            logger.debug(f"Suppressed: {e}")
                finally:
                    try:
                        provider.disconnect()
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
            _rh.submit_background(_post_send_bg)

        # Audit Cluster A (2026-05-10) B-01: do NOT return 201 success=false
        # when provider.create_draft returned None — the frontend trusts the
        # 2xx and shows a confirmation toast for a draft that does not exist.
        if not draft_id and not sent:
            err_detail = (getattr(provider, "_last_error", "") or "Failed to create draft")
            err_detail = _sanitize_provider_error(err_detail)
            return jsonify({"error": err_detail, "draft_id": None, "sent": False}), 502

        return jsonify({
            "success": bool(draft_id),
            "draft_id": draft_id,
            "email_id": email_id,
            "sent": sent,
        }), 201

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating draft for email {_sanitize_for_log(email_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/<email_id>/skip", methods=["POST"])
def skip_email(email_id: str):
    """
    Ignore un email sans créer de brouillon.

    L'email est marqué comme lu pour le retirer de la liste des non-lus.
    Optionnellement, une raison peut être fournie pour analytics futur.

    Args:
        email_id: ID de l'email à ignorer.

    Body JSON (optionnel):
        reason: Raison du skip (pour analytics futur)

    Returns:
        200: {success: true, email_id: "..."}
        400: email_id invalide
        401: Authentification échouée
        404: Email non trouvé
        500: Erreur interne
    """
    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    try:
        provider = _get_authenticated_provider()
        email = _get_email_by_id(provider, email_id)

        # Audit Cluster D (2026-05-17) B-04: previously the boolean return
        # value of `mark_as_read` was dropped on the floor, so 403 (Gmail
        # Insufficient permissions) / refused IMAP STORE / refreshed-token
        # races all returned `success: true` to the client. Inbox-Zero auto-
        # trigger reeval then skipped because no real state change occurred
        # — but the user thought they'd skipped the email. Mirror the
        # `/emails/<id>/read` PATCH route (line ~5721): surface
        # `provider_synced` so the FE can flag a discreet retry hint.
        provider_synced = bool(provider.mark_as_read(email.id))
        if not provider_synced:
            logger.warning(
                "[SKIP] provider.mark_as_read returned False for %s",
                _sanitize_for_log(email_id),
            )

        return jsonify({
            "success": True,
            "email_id": email_id,
            "provider_synced": provider_synced,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error skipping email {_sanitize_for_log(email_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/<email_id>/read", methods=["PATCH"])
def update_email_read_status(email_id: str):
    """
    Met à jour le statut lu/non lu d'un email.

    L'email peut être marqué comme lu ou non lu selon le body JSON.

    Args:
        email_id: ID de l'email à modifier.

    Body JSON:
        is_read: True pour marquer comme lu, False pour marquer comme non lu.

    Returns:
        200: {success: true, email_id: "...", is_read: bool, provider_synced: bool}
             provider_synced reflects whether the provider mark_as_read/unread
             call actually took effect; success stays True even when it did not
             (idempotent already-read), so callers gate on provider_synced.
        400: email_id invalide ou JSON manquant
        401: Authentification échouée
        404: Email non trouvé
        500: Erreur interne
    """
    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    data, error = require_json()
    if error:
        return error

    if "is_read" not in data:
        return jsonify({"error": "is_read field is required"}), 400

    is_read = data.get("is_read")
    if not isinstance(is_read, bool):
        return jsonify({"error": "is_read must be a boolean"}), 400

    raw_id = email_id[5:] if email_id.startswith("sent:") else email_id

    try:
        provider = _get_authenticated_provider()
        # Strip "sent:" prefix — provider expects raw IMAP UID / Gmail ID.
        # Do not call _get_email_by_id here: in metadata-only mode that can
        # fetch the full provider body just to toggle a read flag, making the
        # UI-visible PATCH vulnerable to provider latency/timeouts that Chrome
        # surfaces as a misleading CORS/ERR_FAILED error.

        if is_read:
            success = provider.mark_as_read(raw_id)
        else:
            success = provider.mark_as_unread(raw_id)

        # Update caches so inbox reflects the change immediately
        _invalidate_folder_cache("inbox", "sent")
        # Evict email detail cache so re-fetch gets updated is_read
        _account_id = _resolve_account_id_for_user()
        with _email_detail_cache_lock:
            _email_detail_cache.pop(str(email_id), None)
            _email_detail_cache.pop((_account_id, str(email_id)), None)
            _email_detail_cache.pop((_account_id, str(raw_id)), None)
        _invalidate_label_batch_cache()
        cached = None
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                cached = repo.get_by_email_id(raw_id, account_id=_account_id)
                if cached:
                    cached.is_read = is_read
                    session.commit()
        except Exception as _db_err:
            logger.debug("read-status cache update failed for %s: %s", _sanitize_for_log(raw_id), _db_err)
        _invalidate_label_counts_cache(account_id=_account_id)

        if not success:
            logger.warning(f"Provider mark_as_read returned False for {_sanitize_for_log(email_id)}")

        try:
            from app.api.websocket import emit_email_updated
            emit_email_updated(email_id, {"is_read": is_read})
        except Exception as _e:
            logger.debug(f"emit_email_updated failed: {_e}")

        # Re-evaluate auto-triggers off the request thread so rules whose
        # conditions depend on read state (e.g. "Has label Info AND is_read
        # → Archive") fire when the user marks an email as read. Audit-log
        # dedup in run_auto_triggers prevents rules that already fired at
        # arrival from re-running.
        # Note: we fire the reeval whenever the CALLER asked for is_read=True
        # — not gated on provider success. Idempotent provider mark-as-read
        # may return False on already-read emails (some IMAP servers do
        # this); we still want the trigger to fire on the FE-driven open
        # path so historical already-read emails benefit from the rule.
        if is_read and cached is not None:
            try:
                # Reflect the new state on the snapshot the auto-trigger
                # will read — the in-memory email object may still have
                # is_read=False from before the provider call.
                try:
                    cached.is_read = True
                except Exception:  # noqa: BLE001
                    pass
                _reeval_auto_triggers_async(raw_id, cached)
            except Exception as _e:
                logger.debug(f"auto-trigger re-eval kick-off failed: {_e}")

        # Contract: top-level "success" stays True even when the provider
        # sync returned False. mark_as_read/mark_as_unread is idempotent —
        # some IMAP servers return False for an already-read email, which is
        # benign, and callers may rely on success:true for that case. The
        # accurate provider outcome is surfaced as "provider_synced" so a
        # caller that needs to distinguish a real sync from a no-op/failure
        # can gate on provider_synced:false without us breaking the existing
        # success:true contract.
        return jsonify({
            "success": True,
            "email_id": email_id,
            "is_read": is_read,
            "provider_synced": success,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        if _is_auth_expired_error(e):
            logger.warning(
                "Read status provider sync skipped for %s: account needs reauth",
                _sanitize_for_log(email_id),
            )
            _account_id = _resolve_account_id_for_user()
            local_updated = False
            try:
                with _rh.get_db_session() as session:
                    repo = _rh.EmailRepository(session)
                    cached = repo.get_by_email_id(raw_id, account_id=_account_id)
                    if cached:
                        cached.is_read = is_read
                        session.commit()
                        local_updated = True
            except Exception as _db_err:
                logger.debug("read-status local fallback failed for %s: %s", _sanitize_for_log(raw_id), _db_err)

            if local_updated:
                _invalidate_folder_cache("inbox", "sent")
                with _email_detail_cache_lock:
                    _email_detail_cache.pop(str(email_id), None)
                    _email_detail_cache.pop((_account_id, str(email_id)), None)
                    _email_detail_cache.pop((_account_id, str(raw_id)), None)
                _invalidate_label_batch_cache()
                _invalidate_label_counts_cache(account_id=_account_id)
                try:
                    from app.api.websocket import emit_email_updated
                    emit_email_updated(email_id, {"is_read": is_read})
                except Exception as _emit_err:
                    logger.debug(f"emit_email_updated failed: {_emit_err}")

            return jsonify({
                "success": True,
                "email_id": email_id,
                "is_read": is_read,
                "provider_synced": False,
                "local_updated": local_updated,
                "needs_reauth": True,
            }), 200
        logger.error(f"Error updating read status for {_sanitize_for_log(email_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/<email_id>/delete", methods=["POST"])
def delete_email(email_id: str):
    """
    Supprime un email en le déplaçant vers la corbeille.

    L'email sera définitivement supprimé après 30 jours.

    Args:
        email_id: ID de l'email à supprimer.

    Returns:
        200: {success: true, email_id: "...", message: str}
        400: email_id invalide
        401: Authentification échouée
        404: Email non trouvé
        502: Suppression refusée ou échouée côté provider
    """
    # Strip "sent:" prefix — provider expects raw IMAP UID / Gmail ID
    raw_id = email_id[5:] if email_id.startswith("sent:") else email_id

    if not _validate_email_id(raw_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    try:
        provider = _get_authenticated_provider()

        # Check if provider has delete_email method
        if not hasattr(provider, "delete_email"):
            return jsonify({"error": "Delete not supported by this provider"}), 501

        success = provider.delete_email(raw_id)
        if not success:
            logger.warning(f"[DELETE] provider.delete_email failed for {_sanitize_for_log(raw_id)}")
            return jsonify({
                "error": "Failed to delete email",
                "provider_synced": False,
            }), 502

        # Evict from caches only after the provider accepts the move. A 200
        # from this endpoint must mean Gmail/Outlook/IMAP actually received
        # the delete; otherwise the frontend optimistic rollback is bypassed.
        _evict_email_from_all_caches(email_id, move_to_folder="trash")
        _evict_email_from_all_caches(raw_id, move_to_folder="trash")

        try:
            from app.api.websocket import emit_email_deleted
            emit_email_deleted(email_id)
        except Exception as _e:
            logger.debug(f"emit_email_deleted failed: {_e}")

        return jsonify({
            "success": True,
            "email_id": email_id,
            "message": "Email moved to trash",
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        if _is_auth_expired_error(e):
            logger.warning(
                "Delete provider sync failed for %s: account needs reauth",
                _sanitize_for_log(email_id),
            )
            return jsonify({
                "error": "Email provider authentication failed",
                "provider_synced": False,
                "needs_reauth": True,
            }), 401
        logger.error(f"Error deleting email {_sanitize_for_log(email_id)}: {e}")
        return jsonify({
            "error": "Failed to delete email",
            "provider_synced": False,
        }), 502


def _email_exists_in_cache(email_id: str, account_id: int | None = None) -> bool:
    """Audit Cluster E (2026-05-11) U-02 helper: cheap SQLite check that
    the email actually exists locally. Used by mutation endpoints to
    avoid silently 200-ing on a stale-list bug.

    Patched in tests via `app.api.routes_emails._email_exists_in_cache`.
    """
    try:
        with _rh.get_db_session() as session:
            repo = _rh.EmailRepository(session)
            row = repo.get_by_email_id(email_id, account_id=account_id)
            return row is not None
    except Exception as exc:  # noqa: BLE001
        # Fail open — if the cache lookup itself errors, don't block the
        # archive. We're protecting against silent no-ops, not building
        # a hard gate.
        logger.debug("_email_exists_in_cache lookup failed: %s", exc)
        return True


@api_bp.route("/emails/<email_id>/archive", methods=["POST"])
def archive_email(email_id: str):
    """
    Archive un email en le retirant de la boîte de réception.

    L'email reste accessible dans les archives.

    Args:
        email_id: ID de l'email à archiver.

    Returns:
        200: {success: true, email_id: "...", message: str}
        400: email_id invalide
        401: Authentification échouée
        404: Email non trouvé
        500: Erreur interne
    """
    # Strip "sent:" prefix — provider expects raw IMAP UID / Gmail ID
    is_sent_email = email_id.startswith("sent:")
    raw_id = email_id[5:] if is_sent_email else email_id

    if not _validate_email_id(raw_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    # Audit Cluster E (2026-05-11) U-02: 404 if the email isn't even
    # in the local cache. Otherwise the optimistic UI strips the row and
    # the user thinks something happened, when in reality the provider
    # call will fail in the background with no surfaced error.
    try:
        _aid_for_check = _resolve_account_id_cached()
    except Exception:
        _aid_for_check = None
    if isinstance(_aid_for_check, int) and _aid_for_check > 0:
        # F-01 (audit 2026-05-11): _refresh_sent_cache_bg stores sent emails
        # with raw_eid (no "sent:" prefix). Looking up with the prefixed
        # email_id missed every sent-folder row → 404 on every Archive click.
        if not _email_exists_in_cache(raw_id, account_id=_aid_for_check):
            return jsonify({
                "error": "Email not found",
                "code": "EMAIL_NOT_FOUND",
            }), 404

    try:
        provider = _get_authenticated_provider()

        # Sent emails are already outside INBOX — archiving is a no-op for the provider.
        # Calling archive_email with a Sent UID on INBOX would fail (UID not found there).
        if is_sent_email:
            # Move the cached row to 'archived' rather than deleting it — a
            # no-folder _evict takes the BG delete_by_email_id branch and the
            # email vanishes from both Sent and Archives until a full re-sync.
            _evict_email_from_all_caches(email_id, move_to_folder="archived")
            _evict_email_from_all_caches(raw_id, move_to_folder="archived")
            try:
                from app.api.websocket import emit_email_archived
                emit_email_archived(email_id)
            except Exception as _e:
                logger.debug(f"emit_email_archived failed: {_e}")
            return jsonify({"success": True, "email_id": email_id, "message": "Email archived"}), 200

        # Check if provider has archive_email method
        if not hasattr(provider, "archive_email"):
            return jsonify({"error": "Archive not supported by this provider"}), 501

        # Evict from caches BEFORE the slow IMAP op (~60s)
        _evict_email_from_all_caches(email_id, move_to_folder="archived")
        _evict_email_from_all_caches(raw_id, move_to_folder="archived")

        # Audit Cluster E (2026-05-11) #325: capture account_id BEFORE the
        # bg thread so emit_email_updated has a target room. Without this
        # the failure remained completely silent — frontend never learned
        # the optimistic archive didn't take, user saw the row reappear at
        # the next sync with no toast.
        _archive_acct_id = (
            _aid_for_check
            if isinstance(_aid_for_check, int) and _aid_for_check > 0
            else None
        )

        # Run IMAP archive in background — respond immediately
        def _bg_archive():
            failure_reason: str | None = None
            try:
                success = provider.archive_email(raw_id)
                if not success:
                    logger.warning(f"[ARCHIVE] provider.archive_email failed for {_sanitize_for_log(raw_id)}")
                    failure_reason = "provider_archive_returned_false"
            except Exception as _e:
                logger.error(f"[ARCHIVE] background archive failed for {_sanitize_for_log(raw_id)}: {_e}")
                failure_reason = f"provider_archive_exception: {_e}"
            if failure_reason:
                # Surface to the frontend so the optimistic state can revert.
                try:
                    from app.api.websocket import emit_email_updated
                    emit_email_updated(
                        email_id,
                        {"archive_failed": True, "reason": failure_reason[:200]},
                        account_id=_archive_acct_id,
                    )
                except Exception as _emit_err:
                    logger.error(
                        "[ARCHIVE] emit_email_updated(archive_failed) itself failed: %s",
                        _emit_err, exc_info=True,
                    )
        import threading
        threading.Thread(target=_bg_archive, daemon=True).start()

        try:
            from app.api.websocket import emit_email_archived
            emit_email_archived(email_id)
        except Exception as _e:
            logger.debug(f"emit_email_archived failed: {_e}")

        # Learning: check if this email was archived without reply (= ignored)
        try:
            pd_store = _rh._get_container().get_pending_draft_store()
            try:
                _hd_aid = str(_resolve_account_id_cached())
            except Exception:
                _hd_aid = None
            had_draft = pd_store.get_by_email_id(email_id, account_id=_hd_aid)
            if not had_draft:
                sender = request.json.get("sender", "") if request.is_json else ""
                from app.draft_quality_tracker import get_tracker
                get_tracker().record_interaction(
                    email_id=email_id,
                    contact=sender,
                    action="ignored",
                    account_id=str(_hd_aid or ""),
                )
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        return jsonify({
            "success": True,
            "email_id": email_id,
            "message": "Email archived",
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error archiving email {_sanitize_for_log(email_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


def _enqueue_bulk_job(
    *,
    job_type: str,
    raw_ids: list,
    params: dict | None = None,
) -> str | None:
    """Persist a manual bulk-job for ``raw_ids`` and return its ``job_id``.

    Returns None when enqueue isn't possible (no resolvable account, or the
    enqueue raised) — callers fall back to the synchronous path rather than
    500-ing. Unlike :func:`_enqueue_bulk_if_above_threshold` this does *not*
    gate on ``INLINE_THRESHOLD``: callers that have already decided the wave
    is large (``cleanup-all`` summing two folders) or that are inherently
    background work (``clean-noise``'s provider trashing) use this directly.
    """
    try:
        from app.api._auth_helpers import get_auth_user_id
        from app.db.models.bulk_job import JOB_SOURCE_MANUAL
        from app.services.bulk_jobs.repository import NewBulkJob
        from app.services.bulk_jobs.worker import enqueue_job

        account_id = _resolve_account_id_cached()
        if not account_id or account_id <= 0:
            return None
        return enqueue_job(
            NewBulkJob(
                user_id=get_auth_user_id(),
                account_id=int(account_id),
                job_type=job_type,
                target_msg_ids=list(raw_ids),
                source=JOB_SOURCE_MANUAL,
                params=params or {},
            )
        )
    except Exception as e:
        logger.warning(
            f"[bulk async] enqueue failed for {job_type} (falling back to sync): {e}"
        )
        return None


def _enqueue_bulk_if_above_threshold(
    *,
    job_type: str,
    raw_ids: list,
    params: dict | None = None,
) -> str | None:
    """Try to enqueue a bulk-job; return its `job_id` on success.

    Returns None when:
      - the wave is at-or-below ``INLINE_THRESHOLD`` (caller stays on
        the sync path for a snappy UX),
      - enqueue itself raised (we fall through to sync rather than
        500-ing — at worst the user pays the slow path),
      - no account_id can be resolved (caller will produce its own 401).

    Only the *enqueue* is centralized here. Each endpoint still owns
    its own optimistic cache eviction + SQLite folder update because
    those vary per operation (archive moves to "archived", bulk-delete
    to "trash", etc.) and merging them would force a switch statement
    that's worse than the small duplication.
    """
    from app.services.bulk_jobs.worker import INLINE_THRESHOLD
    if len(raw_ids) <= INLINE_THRESHOLD:
        return None
    return _enqueue_bulk_job(job_type=job_type, raw_ids=raw_ids, params=params)


def _async_response(job_id: str, total: int) -> tuple:
    """Standard 202 envelope returned by every endpoint that enqueued."""
    from flask import jsonify
    return jsonify({
        "accepted": True,
        "mode": "async",
        "job_id": job_id,
        "target_total": total,
    }), 202


def _is_count_only() -> bool:
    """Return True when the caller passed ?count_only=true.

    Used by bulk cleanup endpoints (clean-inbox, empty-trash, empty-spam,
    clean-noise) to short-circuit the action and return just the count of
    affected items. Powers the "Archive ~N emails — queued in background"
    affordances in the UI without doing the mutation.
    """
    return request.args.get('count_only', '').lower() in ('true', '1', 'yes')


def _count_only_response(count: int) -> tuple:
    """Standard envelope for ?count_only=true requests."""
    from app.services.bulk_jobs.worker import INLINE_THRESHOLD
    from flask import jsonify
    return jsonify({
        "count": int(count),
        "will_be_async": int(count) > INLINE_THRESHOLD,
    }), 200


def _purge_local_trash_rows(account_id: int | None) -> int:
    """Drop SQLite cache rows where folder='trash' for `account_id`.

    Used by /emails/empty-trash so the inbox UI reflects the cleanup the
    instant the request returns — well before the bulk-jobs worker has
    finished hitting the provider. Safe at-least-once semantics: if a
    later sync re-discovers a deleted message (unlikely; provider already
    accepted the delete), it'll appear back as a normal trash row.
    """
    if not account_id or account_id <= 0:
        return 0
    try:
        with _rh.get_db_session() as session:
            repo = _rh.EmailRepository(session)
            n = repo.delete_by_folder(account_id, "trash")
            session.commit()
            return int(n or 0)
    except Exception as e:
        logger.warning(f"[empty-trash] local purge failed: {e}")
        return 0


def _purge_local_spam_rows(account_id: int | None) -> int:
    """Same as `_purge_local_trash_rows` for the spam folder."""
    if not isinstance(account_id, int) or account_id <= 0:
        return 0
    try:
        with _rh.get_db_session() as session:
            repo = _rh.EmailRepository(session)
            n = repo.delete_by_folder(account_id, "spam")
            session.commit()
            return int(n or 0)
    except Exception as e:
        logger.warning(f"[empty-spam] local purge failed: {e}")
        return 0


# Local-DB enumeration page size used by empty-trash / empty-spam.
# Picked at 1000 because:
#   - SQLite `SELECT WHERE folder=? LIMIT 1000` returns in <50 ms even
#     on a 100k-row table, so the loop overhead is negligible;
#   - the bulk-jobs queue inserts items in one transaction per page,
#     so we never hold a giant session open for the whole scan.
_FOLDER_ENUM_PAGE_SIZE = 1000

# Hard ceiling so a runaway query doesn't blow up. 100k trash emails
# is *way* beyond any plausible user state (Gmail's UI itself caps
# the visible trash listing at much less). At 30 ops/s rate-limit,
# 100k still drains in 55 minutes — bounded.
_FOLDER_ENUM_HARD_CAP = 100_000


def _list_all_email_ids_in_folder(
    account_id: int, folder: str
) -> list[str]:
    """Enumerate every email_id where `account.folder == folder`.

    Paginated — no implicit cap at 500. The empty-trash / empty-spam
    routes use this so a corbeille with 1000+ items gets cleaned up in
    a single click rather than 500 at a time.

    Returns an empty list on any failure (caller falls back to provider
    enumeration). Empty list also when account_id is unresolvable.
    """
    if not account_id or account_id <= 0:
        return []
    collected: list[str] = []
    offset = 0
    try:
        with _rh.get_db_session() as session:
            repo = _rh.EmailRepository(session)
            while True:
                rows = repo.get_by_folder(
                    account_id=account_id,
                    folder=folder,
                    limit=_FOLDER_ENUM_PAGE_SIZE,
                    offset=offset,
                )
                if not rows:
                    break
                collected.extend(
                    str(r.email_id) for r in rows if r.email_id
                )
                if len(rows) < _FOLDER_ENUM_PAGE_SIZE:
                    break
                offset += _FOLDER_ENUM_PAGE_SIZE
                if len(collected) >= _FOLDER_ENUM_HARD_CAP:
                    logger.warning(
                        "[empty-%s] hit hard cap %d; remainder will be "
                        "picked up on next click",
                        folder, _FOLDER_ENUM_HARD_CAP,
                    )
                    break
        return collected
    except Exception as e:
        logger.warning(
            f"[empty-{folder}] paginated DB enumeration failed: {e}"
        )
        return collected  # whatever we managed to collect before the failure


def _bulk_provider_op(provider, email_ids: list, op_fn, op_name: str) -> int:
    """Execute a provider operation on multiple emails.

    Uses ThreadPoolExecutor(5) for API-based providers (Gmail, Outlook)
    since each op is an independent HTTP call. Falls back to sequential
    for IMAP providers (not thread-safe on a single connection).
    """
    is_api_provider = not hasattr(provider, '_connection')

    if is_api_provider and len(email_ids) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        updated = 0
        with ThreadPoolExecutor(max_workers=min(5, len(email_ids))) as executor:
            futures = {executor.submit(op_fn, eid): eid for eid in email_ids}
            for future in as_completed(futures):
                eid = futures[future]
                try:
                    if future.result():
                        updated += 1
                except Exception as e:
                    logger.warning(f"Failed to {op_name} email {_sanitize_for_log(eid)}: {e}")
        return updated

    # Sequential path for IMAP or single email
    updated = 0
    for eid in email_ids:
        try:
            if op_fn(eid):
                updated += 1
        except Exception as e:
            logger.warning(f"Failed to {op_name} email {_sanitize_for_log(eid)}: {e}")
    return updated


@api_bp.route("/emails/bulk-read", methods=["GET", "POST", "PUT", "DELETE"])
def bulk_mark_read_method_not_allowed():
    """Return a real 405 for unsupported bulk-read methods.

    Without this exact route, GET /emails/bulk-read falls through to
    /emails/<email_id> and tries to load an email whose id is "bulk-read".
    """
    return jsonify({"error": "Method not allowed"}), 405


@api_bp.route("/emails/bulk-read", methods=["PATCH"])
def bulk_update_email_read_status():
    """
    Met à jour le statut lu/non lu de plusieurs emails en une seule requête.

    Body JSON:
        email_ids: Liste des IDs d'emails à modifier.
        is_read: True pour marquer comme lu, False pour marquer comme non lu.

    Returns:
        200: {success: true, updated_count: int, email_ids: [...], is_read: bool}
        400: JSON manquant ou email_ids invalide
        401: Authentification échouée
        500: Erreur interne
    """
    data, error = require_json()
    if error:
        return error

    email_ids, id_error = validate_bulk_email_ids(
        data, action_label="update",
        validate_id_fn=_validate_email_id, sanitize_fn=_sanitize_for_log,
    )
    if id_error:
        return id_error

    is_read = data.get("is_read")
    if not isinstance(is_read, bool):
        return jsonify({"error": "is_read must be a boolean"}), 400

    _x_account_header = request.headers.get("X-Account-Id")
    if _x_account_header:
        from app.api.routes_helpers import require_owned_account_id, _NO_ACCOUNT_SENTINEL
        if require_owned_account_id(_x_account_header) == _NO_ACCOUNT_SENTINEL:
            return jsonify({
                "error": "Account not found or not owned by caller",
                "code": "INVALID_ACCOUNT_HEADER",
            }), 404

    raw_ids = [eid[5:] if eid.startswith("sent:") else eid for eid in email_ids]

    # Async path above the threshold (cf. bulk-archive). Read-status
    # changes are cheap operations but a 500-message wave still trips
    # provider quotas if the user fires several toggles in a row.
    from app.db.models.bulk_job import JOB_TYPE_MARK_READ, JOB_TYPE_MARK_UNREAD
    job_id = _enqueue_bulk_if_above_threshold(
        job_type=JOB_TYPE_MARK_READ if is_read else JOB_TYPE_MARK_UNREAD,
        raw_ids=raw_ids,
    )
    if job_id is not None:
        # Optimistic SQLite + memory cache update so the UI reflects the
        # toggle immediately. Provider state catches up via the worker.
        _invalidate_folder_cache("inbox", "sent")
        with _email_detail_cache_lock:
            for eid in email_ids:
                _email_detail_cache.pop(str(eid), None)
        _invalidate_label_batch_cache()
        _bulk_aid = _resolve_account_id_cached()
        _best_effort_bulk_read_status_update(
            email_ids,
            is_read,
            account_id=_bulk_aid,
            log_prefix="[bulk-read async]",
        )
        return _async_response(job_id, len(raw_ids))

    try:
        provider = _get_authenticated_provider()

        updated_count = _bulk_provider_op(
            provider, raw_ids,
            provider.mark_as_read if is_read else provider.mark_as_unread,
            "update read status",
        )

        # Update caches so inbox reflects changes immediately
        if updated_count > 0:
            _invalidate_folder_cache("inbox", "sent")
            with _email_detail_cache_lock:
                for eid in email_ids:
                    _email_detail_cache.pop(str(eid), None)
            _invalidate_label_batch_cache()
            # Audit 2026-04-25 (HIGH-Iso-3): scope bulk update by account.
            _bulk_aid = _resolve_account_id_cached()
            _best_effort_bulk_read_status_update(
                email_ids,
                is_read,
                account_id=_bulk_aid,
                log_prefix="[bulk-read sync]",
            )

        # Re-evaluate auto-triggers on each freshly-read email so Quick
        # Steps like "Has label Info AND is_read → Archive" fire from the
        # bulk path too. Mirror of the single-email route hook.
        if updated_count > 0 and is_read:
            for eid in email_ids:
                try:
                    _email_obj = _get_email_by_id(provider, eid)
                    try:
                        _email_obj.is_read = True
                    except Exception:  # noqa: BLE001
                        pass
                    _reeval_auto_triggers_async(eid, _email_obj)
                except Exception as _e:
                    logger.debug(f"[bulk-read] reeval kick-off failed for {eid}: {_e}")

        return jsonify({
            "success": True,
            "updated_count": updated_count,
            "email_ids": email_ids,
            "is_read": is_read,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk read status update: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/bulk-archive", methods=["POST"])
def bulk_archive_emails():
    """
    Archive plusieurs emails en une seule requête.

    Body JSON:
        email_ids: Liste des IDs d'emails à archiver.

    Returns:
        200: petite vague (≤ INLINE_THRESHOLD) — exécution sync,
             {success: true, updated_count: int, email_ids: [...]}
        202: vague large — opération asynchrone via la file bulk_jobs,
             {accepted: true, job_id: str, target_total: int, mode: "async"}
        207: succès partiel (sync only)
        400: JSON manquant ou email_ids invalide
        401: Authentification échouée
        500: Erreur interne

    Migration 2026-05-04: au-delà de INLINE_THRESHOLD emails, la requête
    est rate-limited via la file bulk_jobs (cf. app.services.bulk_jobs)
    plutôt que d'exécuter inline. Cela évite de hammer Gmail/Outlook
    quand l'utilisateur archive 5000 emails d'un coup, et offre une UI
    de progression dans Settings → Background Tasks.
    """
    data, error = require_json()
    if error:
        return error

    email_ids, id_error = validate_bulk_email_ids(
        data, action_label="archive",
        validate_id_fn=_validate_email_id, sanitize_fn=_sanitize_for_log,
    )
    if id_error:
        return id_error

    raw_ids = [eid[5:] if eid.startswith("sent:") else eid for eid in email_ids]

    # ── Async path: enqueue when the wave is large enough that running
    # it inline would tie up a request worker for >2 s and risk hitting
    # provider rate limits.
    from app.db.models.bulk_job import JOB_TYPE_ARCHIVE as _JT_ARCHIVE
    job_id = _enqueue_bulk_if_above_threshold(
        job_type=_JT_ARCHIVE, raw_ids=raw_ids,
    )
    if job_id is not None:
        # Optimistic local-cache eviction so the inbox view feels
        # snappy. The actual provider mutation lands within seconds
        # (rate-limited but typical).
        _invalidate_folder_cache("inbox")
        with _email_detail_cache_lock:
            for eid in email_ids:
                _email_detail_cache.pop(eid, None)
            for eid in raw_ids:
                _email_detail_cache.pop(eid, None)
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                repo.bulk_update_folder(
                    raw_ids, "archived",
                    account_id=_resolve_account_id_cached(),
                )
                session.commit()
        except Exception as e:
            logger.warning(
                f"[bulk-archive async] SQLite folder update failed: {e}"
            )
        return _async_response(job_id, len(raw_ids))

    # ── Sync path (small wave) ──────────────────────────────────────────
    try:
        provider = _get_authenticated_provider()

        updated_count = _bulk_provider_op(provider, raw_ids, provider.archive_email, "archive")

        if updated_count == 0:
            return jsonify({"error": "Failed to archive emails", "updated_count": 0}), 500

        # Move emails to "archived" in SQLite cache + invalidate in-memory caches
        _invalidate_folder_cache("inbox")
        with _email_detail_cache_lock:
            for eid in email_ids:
                _email_detail_cache.pop(eid, None)
            for eid in raw_ids:
                _email_detail_cache.pop(eid, None)
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                # DB stores the raw provider ID (never the "sent:" prefix).
                repo.bulk_update_folder(raw_ids, "archived", account_id=_resolve_account_id_cached())
                session.commit()
        except Exception as e:
            logger.warning(f"Failed to update folder in SQLite for bulk archive: {e}")

        if updated_count < len(raw_ids):
            return jsonify({
                "success": True,
                "partial": True,
                "updated_count": updated_count,
                "email_ids": email_ids,
            }), 207

        return jsonify({
            "success": True,
            "updated_count": updated_count,
            "email_ids": email_ids,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk archive: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/bulk-delete", methods=["POST"])
def bulk_delete_emails():
    """
    Supprimer plusieurs emails en une seule requête.

    Body JSON:
        email_ids: Liste des IDs d'emails à supprimer.

    Returns:
        200: {success: true, updated_count: int, email_ids: [...]}
        400: JSON manquant ou email_ids invalide
        401: Authentification échouée
        500: Erreur interne
    """
    data, error = require_json()
    if error:
        return error

    email_ids, id_error = validate_bulk_email_ids(
        data, action_label="delete",
        validate_id_fn=_validate_email_id, sanitize_fn=_sanitize_for_log,
    )
    if id_error:
        return id_error

    raw_ids = [eid[5:] if eid.startswith("sent:") else eid for eid in email_ids]

    # Async path: large bulk-delete waves (e.g. user selects 500 emails
    # via shift-click) are the textbook case for the queue.
    from app.db.models.bulk_job import JOB_TYPE_MOVE_TO_TRASH
    job_id = _enqueue_bulk_if_above_threshold(
        job_type=JOB_TYPE_MOVE_TO_TRASH, raw_ids=raw_ids,
    )
    if job_id is not None:
        _invalidate_folder_cache()
        _invalidate_label_batch_cache()
        with _email_detail_cache_lock:
            for eid in email_ids + raw_ids:
                _email_detail_cache.pop(str(eid), None)
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                repo.bulk_update_folder(
                    raw_ids, "trash",
                    account_id=_resolve_account_id_cached(),
                )
                session.commit()
        except Exception as e:
            logger.warning(f"[bulk-delete async] SQLite update failed: {e}")
        return _async_response(job_id, len(raw_ids))

    try:
        provider = _get_authenticated_provider()

        updated_count = _bulk_provider_op(provider, raw_ids, provider.delete_email, "delete")

        if updated_count == 0:
            return jsonify({"error": "Failed to delete emails", "updated_count": 0}), 500

        # Move emails to trash in SQLite + invalidate caches (batch)
        _invalidate_folder_cache()
        _invalidate_label_batch_cache()
        with _email_detail_cache_lock:
            for eid in email_ids + raw_ids:
                _email_detail_cache.pop(str(eid), None)
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                # DB stores the raw provider ID (never the "sent:" prefix).
                repo.bulk_update_folder(raw_ids, "trash", account_id=_resolve_account_id_cached())
                session.commit()
        except Exception as e:
            logger.warning(f"Failed to update folder in SQLite for bulk delete: {e}")

        if updated_count < len(raw_ids):
            return jsonify({
                "success": True,
                "partial": True,
                "updated_count": updated_count,
                "email_ids": email_ids,
            }), 207

        return jsonify({
            "success": True,
            "updated_count": updated_count,
            "email_ids": email_ids,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk delete: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/<email_id>/not-spam", methods=["POST"])
def mark_not_spam(email_id: str):
    """
    Déplace un email du spam vers la boîte de réception.

    Args:
        email_id: ID de l'email à restaurer.

    Returns:
        200: {success: true, email_id: "...", message: str}
        400: email_id invalide
        500: Erreur interne
    """
    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    # F-04: a JWT user with no DB account resolves to _NO_ACCOUNT_SENTINEL;
    # letting that flow into the account-scoped SQLite folder move would
    # touch zero rows while the UI reports success and the email reappears
    # in spam on the next refresh. Resolve up front and reject early.
    _spam_acct_id = _rh._resolve_account_id_for_user()
    if _spam_acct_id == _rh._NO_ACCOUNT_SENTINEL:
        return jsonify({"error": "No account associated with this user"}), 403

    try:
        provider = _get_authenticated_provider()

        if not hasattr(provider, "move_to_inbox"):
            return jsonify({"error": "Not-spam not supported by this provider"}), 501

        raw_id = email_id[5:] if email_id.startswith("sent:") else email_id

        # Idempotency: if the message is already gone from the provider
        # (user moved it via the native client, or it was deleted), the
        # user's intent is satisfied — treat 404 as success. Without this,
        # Gmail's HttpError bubbles up and the UI shows "Erreur lors du
        # déplacement" even though the row should disappear from spam.
        try:
            success = provider.move_to_inbox(raw_id)
        except Exception as move_err:
            status = getattr(getattr(move_err, "resp", None), "status", None)
            if status == 404:
                logger.info(
                    f"[NOT-SPAM] {_sanitize_for_log(raw_id)} introuvable côté provider (404) — traité comme succès idempotent"
                )
                success = True
            else:
                raise

        if success:
            # F-09: move the cached row to 'inbox' rather than deleting it.
            # The previous code called _evict without move_to_folder (→ a BG
            # delete_by_email_id) AND a separate sync UPDATE folder='inbox';
            # the two raced and the DELETE usually won, wiping the row. Both
            # writes now target folder='inbox' — idempotent, no DELETE.
            _evict_email_from_all_caches(email_id, move_to_folder="inbox", account_id=_spam_acct_id)
            _evict_email_from_all_caches(raw_id, move_to_folder="inbox", account_id=_spam_acct_id)
            try:
                from app.api.websocket import emit_email_spam_changed
                emit_email_spam_changed(email_id, is_spam=False)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

            # Spam learning + a synchronous folder='inbox' write so the row
            # is correct even before the BG _evict task runs (mirrors
            # bulk_not_spam at l.6665). _spam_acct_id was resolved and
            # sentinel-checked at handler entry.
            try:
                with _rh.get_db_session() as session:
                    repo = _rh.EmailRepository(session)
                    email_record = repo.get_by_email_id(raw_id, account_id=_spam_acct_id)
                    if email_record and email_record.sender:
                        _unlearn_spammed_sender(email_record.sender)
                    repo.bulk_update_folder([raw_id], "inbox", account_id=_spam_acct_id)
                    session.commit()
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

            return jsonify({
                "success": True,
                "email_id": email_id,
                "message": "Email moved to inbox",
            }), 200
        else:
            return jsonify({
                "error": "Failed to move email to inbox"
            }), 500

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking not-spam {_sanitize_for_log(email_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/<email_id>/move-to-spam", methods=["POST"])
def move_email_to_spam(email_id: str):
    """
    Déplace un email vers le dossier spam/indésirables et apprend l'expéditeur.

    Args:
        email_id: ID de l'email à déplacer.

    Request Body (optionnel):
        sender (str): Adresse email de l'expéditeur (fast-path depuis le frontend).

    Returns:
        200: {success: true, email_id: "...", message: str}
        400: email_id invalide
        501: Non supporté par ce fournisseur
        500: Erreur interne
    """
    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    # F-04: a JWT user with no DB account resolves to _NO_ACCOUNT_SENTINEL;
    # letting that flow into the account-scoped SQLite folder move would
    # touch zero rows while the UI reports success. Resolve up front and
    # reject before any provider or DB mutation.
    _spam_acct_id = _rh._resolve_account_id_for_user()
    if _spam_acct_id == _rh._NO_ACCOUNT_SENTINEL:
        return jsonify({"error": "No account associated with this user"}), 403

    try:
        provider = _get_authenticated_provider()

        if not hasattr(provider, "move_to_spam"):
            return jsonify({"error": "Move to spam not supported by this provider"}), 501

        raw_id = email_id[5:] if email_id.startswith("sent:") else email_id
        success = provider.move_to_spam(raw_id)

        if success:
            # Move the cached row to 'spam' rather than deleting it — a
            # no-folder _evict takes the BG delete_by_email_id branch and
            # the email disappears from Agentys entirely until a re-sync.
            _evict_email_from_all_caches(email_id, move_to_folder="spam", account_id=_spam_acct_id)
            _evict_email_from_all_caches(raw_id, move_to_folder="spam", account_id=_spam_acct_id)
            try:
                from app.api.websocket import emit_email_spam_changed
                emit_email_spam_changed(email_id, is_spam=True)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

            # Spam learning: auto-analyse et crée des règles
            data = request.get_json(silent=True)
            sender_email = (data or {}).get("sender", "").strip()
            if not sender_email:
                try:
                    # CASA P1-8: scope SQLite read by caller's account
                    # (_spam_acct_id resolved + sentinel-checked at handler entry)
                    with _rh.get_db_session() as session:
                        repo = _rh.EmailRepository(session)
                        email_record = repo.get_by_email_id(raw_id, account_id=_spam_acct_id)
                        if email_record and email_record.sender:
                            sender_email = email_record.sender
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
            if sender_email:
                _learn_spam_pattern(sender_email, email_id)

            return jsonify({
                "success": True,
                "email_id": email_id,
                "message": "Email moved to spam",
            }), 200
        else:
            return jsonify({
                "error": "Failed to move email to spam"
            }), 500

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error moving to spam {_sanitize_for_log(email_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/bulk-not-spam", methods=["POST"])
def bulk_not_spam():
    """
    Déplace plusieurs emails du spam vers la boîte de réception.

    Body JSON:
        email_ids: Liste des IDs d'emails à restaurer.

    Returns:
        200: {success: true, updated_count: int, email_ids: [...]}
        400: JSON manquant ou email_ids invalide
        500: Erreur interne
    """
    data, error = require_json()
    if error:
        return error

    email_ids = data.get("email_ids")
    if not email_ids or not isinstance(email_ids, list):
        return jsonify({"error": "email_ids must be a non-empty list"}), 400

    if len(email_ids) > 100:
        return jsonify({"error": "Cannot process more than 100 emails at once"}), 400

    for eid in email_ids:
        if not _validate_email_id(eid):
            return jsonify({"error": f"Invalid email_id format: {_sanitize_for_log(eid)}"}), 400

    raw_ids = [eid[5:] if eid.startswith("sent:") else eid for eid in email_ids]
    _acct_id = _resolve_account_id_cached()

    # Async path for large not-spam waves. Spam → inbox is harmless to
    # retry (label set ops are idempotent on Gmail/Graph).
    from app.db.models.bulk_job import JOB_TYPE_MOVE_TO_INBOX
    job_id = _enqueue_bulk_if_above_threshold(
        job_type=JOB_TYPE_MOVE_TO_INBOX, raw_ids=raw_ids,
    )
    if job_id is not None:
        _invalidate_folder_cache("inbox", "spam")
        with _email_detail_cache_lock:
            for eid in email_ids:
                _email_detail_cache.pop(eid, None)
            for raw_eid in raw_ids:
                _email_detail_cache.pop(raw_eid, None)
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                repo.bulk_update_folder(raw_ids, "inbox", account_id=_acct_id)
                session.commit()
        except Exception as e:
            logger.debug(f"[bulk-not-spam async] suppressed: {e}")
        return _async_response(job_id, len(raw_ids))

    try:
        provider = _get_authenticated_provider()

        updated_count = 0
        for eid, raw_id in zip(email_ids, raw_ids):
            try:
                if provider.move_to_inbox(raw_id):
                    updated_count += 1
            except Exception as e:
                logger.warning(f"Failed to move email to inbox {_sanitize_for_log(eid)}: {e}")

        # Invalidate caches + update SQLite folder
        _invalidate_folder_cache("inbox", "spam")
        with _email_detail_cache_lock:
            for eid in email_ids:
                _email_detail_cache.pop(eid, None)
            for raw_eid in raw_ids:
                _email_detail_cache.pop(raw_eid, None)
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                # DB stores raw provider IDs — the prior code passed the
                # prefixed "sent:..." list which silently matched zero rows.
                repo.bulk_update_folder(raw_ids, "inbox", account_id=_acct_id)
                session.commit()
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        return jsonify({
            "success": True,
            "updated_count": updated_count,
            "email_ids": email_ids,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk not-spam: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/empty-spam", methods=["POST"])
def empty_spam():
    """
    Vide le dossier spam.

    Sémantique : déplace les emails « bruyants » (sans label autre que
    Noise) vers la corbeille, et restaure dans l'inbox les emails ayant
    un label métier (Action, Info, Agentys, ...) — c'est la « rescue
    logic » qui évite de jeter du courrier important mal classé en spam.

    Returns:
        200 : sync (≤ INLINE_THRESHOLD), {success, deleted_count, rescued_count}
        202 : async (file bulk_jobs), {accepted, mode:"async", trash_job_id?, rescue_job_id?, target_total}
        500 : erreur interne
    """
    # Resolve account_id up-front for the optimistic-purge helper
    # regardless of which enumeration path succeeds.
    raw_account_id = _resolve_account_id_cached()
    try:
        account_id = int(raw_account_id) if isinstance(raw_account_id, (int, str)) else None
    except (TypeError, ValueError):
        account_id = None

    # count_only short-circuit — cheap COUNT(*) before any provider call.
    if _is_count_only():
        cnt = 0
        try:
            if account_id and account_id > 0:
                from sqlalchemy import select as _select, func as _func
                from app.db.models.email import Email
                with _rh.get_db_session() as session:
                    cnt = session.scalar(
                        _select(_func.count(Email.email_id)).where(
                            Email.account_id == account_id,
                            Email.folder == "spam",
                        )
                    ) or 0
        except Exception as e:
            logger.debug(f"[empty-spam count_only] suppressed: {e}")
        return _count_only_response(cnt)

    try:
        provider = _get_authenticated_provider()

        # ── Enumerate from local DB first (UI's source of truth) ──────
        # Same rationale as empty-trash: provider.get_messages can return
        # 0 on Gmail when emails are SPAM-labeled in cache but not flagged
        # at the API level, producing a misleading "0 deleted" while the
        # spam folder is visibly populated.
        spam_ids: list[str] = []
        try:
            if account_id and account_id > 0:
                with _rh.get_db_session() as session:
                    repo_e = _rh.EmailRepository(session)
                    rows = repo_e.get_by_folder(
                        account_id=account_id, folder="spam", limit=500,
                    )
                    spam_ids = [str(r.email_id) for r in rows if r.email_id]
        except Exception as e:
            logger.warning(
                f"[empty-spam] local DB enumeration failed (will fall back "
                f"to provider): {e}"
            )

        if not spam_ids:
            spam_folder = _resolve_folder_for_provider(provider, "spam")
            try:
                spam_emails = provider.get_messages(
                    limit=500, label_ids=[spam_folder]
                )
            except Exception as e:
                logger.warning(f"[empty-spam] provider enumeration failed: {e}")
                spam_emails = []
            spam_ids = [
                str(getattr(e, 'id', '')) for e in spam_emails or []
                if getattr(e, 'id', None)
            ]

        if not spam_ids:
            return jsonify({"success": True, "deleted_count": 0, "rescued_count": 0}), 200

        # Classify rescue vs noise via the local label store (zero
        # provider calls). Same algorithm as the sync path so behaviour
        # stays stable when the wave is enqueued.
        rescue_ids: set[str] = set()
        try:
            container = _rh._get_container()
            label_store = container.get_label_store(account_id=account_id)
            assignments = label_store.get_assignments_batch(spam_ids)
            for eid, assignment in assignments.items():
                non_noise = [lb for lb in assignment.labels if lb != "Noise"]
                if non_noise:
                    rescue_ids.add(eid)
        except Exception as e:
            logger.warning(f"Label lookup failed, treating all as noise: {e}")

        noise_ids = [eid for eid in spam_ids if eid not in rescue_ids]
        rescue_id_list = [eid for eid in spam_ids if eid in rescue_ids]

        # ── Async path: total > threshold ──────────────────────────────
        # We split into two sibling jobs (trash + rescue) so the user
        # can pause/cancel each independently, and so the worker
        # interleaves them naturally with other accounts' jobs through
        # the per-account FIFO.
        from app.db.models.bulk_job import (
            JOB_TYPE_MOVE_TO_INBOX,
            JOB_TYPE_MOVE_TO_TRASH,
        )
        from app.services.bulk_jobs.worker import INLINE_THRESHOLD
        if len(spam_ids) > INLINE_THRESHOLD:
            trash_job_id = (
                _enqueue_bulk_if_above_threshold(
                    job_type=JOB_TYPE_MOVE_TO_TRASH, raw_ids=noise_ids
                )
                if noise_ids
                else None
            )
            rescue_job_id = (
                _enqueue_bulk_if_above_threshold(
                    job_type=JOB_TYPE_MOVE_TO_INBOX, raw_ids=rescue_id_list
                )
                if rescue_id_list
                else None
            )
            if trash_job_id or rescue_job_id:
                # Optimistic local purge: spam folder rows go away
                # immediately. Rescued items will reappear in the inbox
                # via the worker's `move_to_inbox` job and the next sync
                # tick (which re-fetches the inbox from the provider).
                _purge_local_spam_rows(account_id)
                _invalidate_folder_cache("spam")
                if rescue_job_id:
                    _invalidate_folder_cache("inbox")
                with _email_detail_cache_lock:
                    for mid in spam_ids:
                        _email_detail_cache.pop(mid, None)
                return jsonify({
                    "accepted": True,
                    "mode": "async",
                    "trash_job_id": trash_job_id,
                    "rescue_job_id": rescue_job_id,
                    "target_total": len(spam_ids),
                    "rescued_target": len(rescue_id_list),
                    "trashed_target": len(noise_ids),
                }), 202
            # Both enqueues silently fell back to sync — fall through.

        # ── Sync path (small wave or enqueue failure) ──────────────────
        deleted_count = 0
        rescued_count = 0

        if hasattr(provider, 'batch_modify_labels'):
            # Gmail batch API: trash noise emails (SPAM → TRASH)
            if noise_ids:
                deleted_count = provider.batch_modify_labels(
                    noise_ids,
                    add_label_ids=["TRASH"],
                    remove_label_ids=["SPAM"]
                )
            # Gmail batch API: rescue non-noise emails (SPAM → INBOX)
            if rescue_id_list:
                rescued_count = provider.batch_modify_labels(
                    rescue_id_list,
                    add_label_ids=["INBOX"],
                    remove_label_ids=["SPAM"]
                )
        else:
            # Fallback for non-Gmail providers: sequential operations
            for eid in noise_ids:
                try:
                    if provider.delete_email(eid):
                        deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete spam email {eid}: {e}")
            for eid in rescue_id_list:
                try:
                    if hasattr(provider, 'move_to_inbox') and provider.move_to_inbox(eid):
                        rescued_count += 1
                except Exception as e:
                    logger.warning(f"Failed to rescue spam email {eid}: {e}")

        # Sync path: same local-purge + cache invalidation as async so
        # the spam folder UI clears even if the provider responded with
        # zero affected rows (e.g. labels-only mismatch).
        purged_local = _purge_local_spam_rows(account_id)
        _invalidate_folder_cache("spam")
        if rescued_count > 0:
            _invalidate_folder_cache("inbox")
        with _email_detail_cache_lock:
            for mid in spam_ids:
                _email_detail_cache.pop(mid, None)

        # Same "max of provider-reported vs locally-purged" logic as
        # empty-trash so the toast count matches what the user sees.
        reported_deleted = max(deleted_count, purged_local - rescued_count)
        return jsonify({
            "success": True,
            "deleted_count": max(reported_deleted, 0),
            "rescued_count": rescued_count,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error emptying spam folder: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


# ============================================================================
# NOISE AUTO-CLEANUP
# ============================================================================
_noise_cleanup_lock = threading.Lock()
_noise_cleanup_running = False        # flag pour l'auto-cleanup (run_api.py)
_noise_manual_cleanup_running = False  # flag pour le cleanup manuel (bouton UI)
_noise_auto_cleanup_last_started: dict[int, float] = {}
_NOISE_AUTO_CLEANUP_DEFAULT_INTERVAL_SECONDS = 3600

_BOUNCE_SENDERS = ("mailer-daemon@", "postmaster@", "noreply@bounce", "delivery-notification@")


def _mark_noise_auto_cleanup_started(account_id: int) -> bool:
    """Throttle auto Noise cleanup per account.

    This is intentionally process-local. The cleanup is a defensive best-effort
    task after sync; if labels or SQL mirrors drift, it must not hammer Gmail
    every 120 seconds. Manual cleanup is not throttled.
    """
    interval = _positive_int_env(
        "AGENTYS_AUTO_CLEANUP_NOISE_MIN_INTERVAL_SECONDS",
        _NOISE_AUTO_CLEANUP_DEFAULT_INTERVAL_SECONDS,
    )
    now = _cache_time.monotonic()
    with _noise_cleanup_lock:
        last_started = _noise_auto_cleanup_last_started.get(account_id)
        if last_started is not None and now - last_started < interval:
            remaining = max(1, int(interval - (now - last_started)))
            logger.info(
                "[NOISE-CLEANUP] Auto skip account=%s throttled remaining=%ss",
                account_id,
                remaining,
            )
            return False
        _noise_auto_cleanup_last_started[account_id] = now
        return True


def _cleanup_noise_bg(account_id: int, oauth_account_id: str, manual: bool = False):
    """
    Trash read Noise emails and delete old bounce-backs.

    Auto mode (manual=False): only trash Noise older than cleanup_noise_days.
    Manual mode (manual=True): trash ALL read Noise emails regardless of age.

    Returns (archived_count, deleted_count) or None if skipped.
    """
    global _noise_cleanup_running, _noise_manual_cleanup_running
    if manual:
        # Mode manuel : utilise un flag séparé — ne pas bloquer sur l'auto-cleanup
        with _noise_cleanup_lock:
            if _noise_manual_cleanup_running:
                return None
            _noise_manual_cleanup_running = True
    else:
        # Mode auto : bloquer si déjà en cours
        if _noise_cleanup_running:
            return None
        with _noise_cleanup_lock:
            if _noise_cleanup_running:
                return None
            _noise_cleanup_running = True

    archived_count = 0
    deleted_count = 0
    provider = None
    try:
        # Skip cleanly when the account isn't registered with the multi-account
        # manager. After a sync, run_api.py schedules cleanup for every account
        # in the sync result — including IMAP_SMTP / disabled / mid-deletion
        # accounts that have no OAuth provider config. Without this guard, the
        # provider pool below raised "Account X not found — refusing to fallback
        # to env provider" and that warning fired *every* sync cycle forever.
        if oauth_account_id:
            try:
                from app.multi_accounts import get_account_manager
                if get_account_manager().get_account(oauth_account_id) is None:
                    logger.info(
                        "[NOISE-CLEANUP] Skipping account %s (not registered with multi-account manager)",
                        oauth_account_id,
                    )
                    return None
            except Exception as exc:  # noqa: BLE001
                logger.debug("[NOISE-CLEANUP] account lookup failed: %s", exc)

        from app.api.settings import load_settings
        settings = load_settings()
        if not manual and not settings.get("auto_cleanup_noise", True):
            return None

        days = settings.get("cleanup_noise_days", 7)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        bounce_cutoff = datetime.now(timezone.utc) - timedelta(days=3)

        # Get Noise email IDs from label store
        container = _rh._get_container()
        label_store = container.get_label_store(account_id=account_id)
        noise_ids = set(label_store.get_emails_by_label("Noise"))
        if not noise_ids:
            if manual:
                # Même si vide, notifier le frontend pour forcer un refresh
                _invalidate_folder_cache("inbox")
                _invalidate_label_batch_cache()
                try:
                    from app.api.websocket import emit_to_account
                    emit_to_account("noise_cleanup_complete", {"archived_count": 0, "deleted_count": 0}, account_id)
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
            return (0, 0)

        if not manual and not _mark_noise_auto_cleanup_started(account_id):
            return None

        if manual:
            # Mode manuel : retirer les labels IMMÉDIATEMENT pour vider la liste dans l'UI
            # puis continuer les suppressions IMAP en background
            archive_ids = list(noise_ids)
            delete_ids = []
            total_noise = len(noise_ids)

            try:
                label_store.bulk_remove_label(noise_ids, "Noise")
            except Exception as e:
                logger.warning(f"[NOISE-CLEANUP] bulk_remove_label failed: {e}")

            _invalidate_folder_cache("inbox")
            _invalidate_label_batch_cache()

            try:
                from app.api.websocket import emit_to_account
                sent = emit_to_account(
                    "noise_cleanup_complete",
                    {"archived_count": total_noise, "deleted_count": 0},
                    account_id,
                )
                if sent:
                    logger.info(f"[NOISE-CLEANUP] noise_cleanup_complete emitted (count={total_noise}, account_id={account_id})")
                else:
                    logger.warning(f"[NOISE-CLEANUP] emit_to_account skipped (account_id={account_id} has no room)")
            except Exception as ws_err:
                logger.warning(f"[NOISE-CLEANUP] WebSocket emit failed: {ws_err}")

            logger.info(f"[NOISE-CLEANUP] Manual: {total_noise} labels cleared, continuing IMAP trash in background")
        else:
            # Mode auto : cross-ref SQLite pour filtrer par âge et détecter les bounces
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                db_emails = list(repo.get_by_account(
                    account_id=account_id,
                    limit=500,
                    email_ids=noise_ids,
                    skip_folder_filter=True,
                ))

            if not db_emails:
                return (0, 0)

            archive_ids = []
            delete_ids = []
            for em in db_emails:
                folder_value = getattr(em, "folder", None)
                folder = folder_value.lower() if isinstance(folder_value, str) and folder_value else "inbox"
                if getattr(em, "is_sent", False) is True or folder != "inbox":
                    continue
                sender = (em.sender or "").lower()
                is_bounce = any(p in sender for p in _BOUNCE_SENDERS)
                email_date = em.date.replace(tzinfo=timezone.utc) if em.date and em.date.tzinfo is None else em.date

                if is_bounce and email_date and email_date < bounce_cutoff:
                    delete_ids.append(em.email_id)
                elif em.is_read and email_date and email_date < cutoff:
                    archive_ids.append(em.email_id)

        if not archive_ids and not delete_ids:
            return (0, 0)

        # Get provider
        from app.providers.factory import get_pooled_provider
        provider = get_pooled_provider(account_id=oauth_account_id)
        if not manual and getattr(type(provider), "low_priority_quota_retry_after_seconds", None) is not None:
            try:
                retry_after = int(provider.low_priority_quota_retry_after_seconds())
            except Exception:
                retry_after = 0
            if retry_after > 0:
                logger.info(
                    "[NOISE-CLEANUP] Auto skip account=%s provider backoff retry_after=%ss",
                    account_id,
                    retry_after,
                )
                return None

        # Trash noise emails — track actually-trashed IDs (not index slicing)
        trashed_ids = []
        for eid in archive_ids:
            raw_id = eid[5:] if eid.startswith("sent:") else eid
            try:
                if provider.delete_email(raw_id):
                    trashed_ids.append(eid)
                else:
                    logger.warning(f"[NOISE-CLEANUP] trash returned False for {eid}")
            except Exception as e:
                logger.warning(f"[NOISE-CLEANUP] trash failed for {eid}: {e}")
        archived_count = len(trashed_ids)

        # Delete bounce-backs — track actually-deleted IDs.
        # Providers return False on transient HttpError / 404 / rate-limit;
        # treat that the same as a raised exception so we don't strip the
        # Noise label off an email that still exists in the user's INBOX
        # upstream (Gmail re-imports it on next sync → flicker between
        # Inbox/Noise tabs as the classifier re-labels and the next
        # cleanup pass strips the label again).
        permanently_deleted_ids = []
        # Scope complet https://mail.google.com/ absent → messages.delete
        # impossible (403 permanent). Dans ce cas on dégrade vers la
        # corbeille : Gmail la purge nativement après 30 jours, et garder
        # le label « Noise » faisait re-tenter les mêmes bounce-backs à
        # CHAQUE passe de cleanup (tempête de 2 107 erreurs 403, audit
        # 2026-06-09).
        scope_missing = False
        for eid in delete_ids:
            raw_id = eid[5:] if eid.startswith("sent:") else eid
            try:
                if scope_missing or not hasattr(provider, 'permanently_delete'):
                    ok = provider.delete_email(raw_id)
                else:
                    try:
                        ok = provider.permanently_delete(raw_id)
                    except InsufficientScopeError:
                        scope_missing = True
                        logger.warning(
                            "[NOISE-CLEANUP] scope complet manquant — "
                            "suppression définitive impossible, bascule vers "
                            "la corbeille (purge native Gmail à 30 jours)"
                        )
                        ok = provider.delete_email(raw_id)
                if ok:
                    permanently_deleted_ids.append(eid)
                else:
                    logger.warning(f"[NOISE-CLEANUP] permanent delete returned False for {eid} — keeping label")
            except Exception as e:
                logger.warning(f"[NOISE-CLEANUP] delete failed for {eid}: {e}")
        deleted_count = len(permanently_deleted_ids)

        # Update label store — mode auto seulement (mode manuel déjà traité avant la boucle)
        if not manual and (archived_count > 0 or deleted_count > 0):
            try:
                label_store.bulk_remove_label(set(trashed_ids) | set(permanently_deleted_ids), "Noise")
            except Exception as e:
                logger.warning(f"[NOISE-CLEANUP] bulk_remove_label failed: {e}")

        # Update SQLite (best-effort — table may not exist)
        if archived_count > 0 or deleted_count > 0:
            try:
                with _rh.get_db_session() as session:
                    repo = _rh.EmailRepository(session)
                    if trashed_ids:
                        _raw_trashed = [t[5:] if t.startswith("sent:") else t for t in trashed_ids]
                        repo.bulk_update_folder(_raw_trashed, "trash", account_id=account_id)
                    if permanently_deleted_ids:
                        for did in permanently_deleted_ids:
                            # CASA P1-8: scope by account_id (in scope from _cleanup_noise_bg signature)
                            db_em = repo.get_by_email_id(did, account_id=account_id)
                            if db_em:
                                session.delete(db_em)
                    session.commit()
            except Exception as e:
                logger.warning(f"[NOISE-CLEANUP] SQLite update failed: {e}")

        # Invalidate caches and notify frontend after IMAP work completes
        if archived_count > 0 or deleted_count > 0:
            _invalidate_folder_cache("inbox")
            _invalidate_folder_cache("trash")
            _invalidate_label_batch_cache()
            _invalidate_label_counts_cache(account_id=account_id)

            try:
                from app.api.websocket import emit_to_account
                emit_to_account(
                    "noise_cleanup_complete",
                    {"archived_count": archived_count, "deleted_count": deleted_count},
                    account_id,
                )
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

        logger.info(f"[NOISE-CLEANUP] {'Manual' if manual else 'Auto'}: archived={archived_count}, deleted={deleted_count}")
        return (archived_count, deleted_count)

    except Exception as e:
        logger.warning(f"[NOISE-CLEANUP] Error: {e}")
        return None
    finally:
        if manual:
            _noise_manual_cleanup_running = False
        else:
            _noise_cleanup_running = False


@api_bp.route("/emails/clean-noise", methods=["POST"])
def clean_noise():
    """Remove Noise labels synchronously, then trash the emails via the
    rate-limited bulk-jobs queue.

    Label removal is synchronous so the next list refresh sees no Noise
    emails immediately. The actual provider trashing is inherently
    background work — it's routed through the bulk-jobs queue (job_type
    ``move_to_trash``) so it is rate-limited, retried on transient
    failures, visible/pausable in Settings → Background Tasks, and
    survives a backend restart. The legacy fire-and-forget thread
    (``_trash_noise_emails_bg``) had none of those properties.

    Returns:
        200 : nothing to trash, or sync fallback when enqueue is
              unavailable — {success, pending, archived_count, deleted_count}
        202 : trashing queued — {success, pending:false, accepted, mode:"async",
              job_id, archived_count, deleted_count, target_total}
    """
    global _noise_manual_cleanup_running

    # count_only short-circuit before touching the global lock. Cheap
    # call into the label store — same path the action would take.
    if _is_count_only():
        cnt = 0
        try:
            account_id = _resolve_account_id_cached()
            container = _rh._get_container()
            label_store = container.get_label_store(account_id=account_id)
            cnt = len(list(label_store.get_emails_by_label("Noise")))
        except Exception as e:
            logger.debug(f"[clean-noise count_only] suppressed: {e}")
        return _count_only_response(cnt)

    # The flag still coordinates with `_cleanup_noise_bg(manual=True)` so
    # two manual cleanups can't race. Cleared in `finally` — the request
    # now returns fast (enqueue is instant), there is no long-lived thread
    # left to track.
    with _noise_cleanup_lock:
        if _noise_manual_cleanup_running:
            return jsonify({
                "success": True, "pending": True,
                "archived_count": 0, "deleted_count": 0,
            })
        _noise_manual_cleanup_running = True

    try:
        account_id = _resolve_account_id_cached()
        container = _rh._get_container()
        label_store = container.get_label_store(account_id=account_id)
        noise_ids = list(label_store.get_emails_by_label("Noise"))
        total = len(noise_ids)

        # 1. Remove labels SYNCHRONOUSLY (instant — JSON file update) so
        #    the next inbox refresh shows zero Noise emails.
        if noise_ids:
            label_store.bulk_remove_label(set(noise_ids), "Noise")
        _invalidate_folder_cache("inbox")
        _invalidate_label_batch_cache()
        _invalidate_label_counts_cache(account_id=account_id)

        if not noise_ids:
            return jsonify({
                "success": True, "pending": False,
                "archived_count": 0, "deleted_count": 0,
            }), 200

        # 2. Trash the emails through the bulk-jobs queue.
        from app.db.models.bulk_job import JOB_TYPE_MOVE_TO_TRASH
        job_id = _enqueue_bulk_job(
            job_type=JOB_TYPE_MOVE_TO_TRASH,
            raw_ids=noise_ids,
            params={"reason": "noise_manual"},
        )

        if job_id is not None:
            # Optimistic SQLite folder update so trash/inbox counts reflect
            # the move immediately; the worker drives the provider trashing.
            try:
                with _rh.get_db_session() as session:
                    repo = _rh.EmailRepository(session)
                    _raw = [e[5:] if e.startswith("sent:") else e for e in noise_ids]
                    repo.bulk_update_folder(_raw, "trash", account_id=account_id)
                    session.commit()
            except Exception as e:
                logger.warning(f"[clean-noise] optimistic SQLite update failed: {e}")
            _invalidate_folder_cache("trash")
            return jsonify({
                "success": True, "pending": False,
                "accepted": True, "mode": "async", "job_id": job_id,
                "archived_count": total, "deleted_count": 0,
                "target_total": total,
            }), 202

        # Enqueue unavailable (no resolvable account / enqueue raised) —
        # trash inline so the action still completes. Labels are already
        # removed, so at worst the user just waits a moment longer.
        logger.warning("[clean-noise] enqueue unavailable, trashing inline")
        provider = _get_authenticated_provider()
        raw_ids = [e[5:] if e.startswith("sent:") else e for e in noise_ids]
        trashed = _bulk_provider_op(
            provider, raw_ids, provider.delete_email, "trash noise",
        )
        if trashed:
            try:
                with _rh.get_db_session() as session:
                    repo = _rh.EmailRepository(session)
                    repo.bulk_update_folder(raw_ids, "trash", account_id=account_id)
                    session.commit()
            except Exception as e:
                logger.warning(f"[clean-noise sync] SQLite update failed: {e}")
            _invalidate_folder_cache("trash")
        return jsonify({
            "success": True, "pending": False,
            "archived_count": total, "deleted_count": 0,
        }), 200
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"clean_noise error: {e}")
        return jsonify({"error": "An internal error occurred"}), 500
    finally:
        _noise_manual_cleanup_running = False

@api_bp.route("/emails/mark-noise-read", methods=["POST"])
def mark_noise_read():
    """Mark all Noise-labeled emails as read without removing the label."""
    if _is_count_only():
        cnt = 0
        try:
            account_id = _resolve_account_id_cached()
            container = _rh._get_container()
            label_store = container.get_label_store(account_id=account_id)
            cnt = len(list(label_store.get_emails_by_label("Noise")))
        except Exception as e:
            logger.debug(f"[mark-noise-read count_only] suppressed: {e}")
        return _count_only_response(cnt)

    try:
        account_id = _resolve_account_id_cached()
        container = _rh._get_container()
        label_store = container.get_label_store(account_id=account_id)
        noise_ids = list(label_store.get_emails_by_label("Noise"))
        total = len(noise_ids)

        if not noise_ids:
            return jsonify({
                "success": True,
                "updated_count": 0,
                "email_ids": [],
                "is_read": True,
            }), 200

        raw_ids = [eid[5:] if eid.startswith("sent:") else eid for eid in noise_ids]

        from app.db.models.bulk_job import JOB_TYPE_MARK_READ
        job_id = _enqueue_bulk_if_above_threshold(
            job_type=JOB_TYPE_MARK_READ,
            raw_ids=raw_ids,
            params={"reason": "noise_mark_read"},
        )
        if job_id is not None:
            _invalidate_folder_cache("inbox", "sent")
            with _email_detail_cache_lock:
                for eid in noise_ids:
                    _email_detail_cache.pop(str(eid), None)
            _invalidate_label_batch_cache()
            try:
                with _rh.get_db_session() as session:
                    repo = _rh.EmailRepository(session)
                    all_ids = noise_ids + [eid[5:] for eid in noise_ids if eid.startswith("sent:")]
                    repo.bulk_update_read_status(all_ids, True, account_id=account_id)
                    session.commit()
            except Exception as exc:
                logger.warning("[mark-noise-read async] SQLite update failed: %s", exc)
            _invalidate_label_counts_cache(account_id=account_id)

            return jsonify({
                "success": True,
                "accepted": True,
                "mode": "async",
                "job_id": job_id,
                "target_total": total,
                "updated_count": total,
                "email_ids": noise_ids,
                "is_read": True,
            }), 202

        provider = _get_authenticated_provider()
        updated_count = _bulk_provider_op(
            provider,
            raw_ids,
            provider.mark_as_read,
            "mark noise read",
        )

        _invalidate_folder_cache("inbox", "sent")
        with _email_detail_cache_lock:
            for eid in noise_ids:
                _email_detail_cache.pop(str(eid), None)
        _invalidate_label_batch_cache()
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                all_ids = noise_ids + [eid[5:] for eid in noise_ids if eid.startswith("sent:")]
                repo.bulk_update_read_status(all_ids, True, account_id=account_id)
                session.commit()
        except Exception as exc:
            logger.warning("[mark-noise-read] SQLite update failed: %s", exc)
        _invalidate_label_counts_cache(account_id=account_id)

        return jsonify({
            "success": True,
            "updated_count": updated_count,
            "email_ids": noise_ids,
            "is_read": True,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"mark_noise_read error: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


def _caller_owns_account(owner_int) -> bool:
    """True if the JWT caller owns DB account ``owner_int`` (or Tauri loopback).

    Audit 2026-05-29: the owner-resolved provider path in restore_email would
    otherwise authenticate as ANY tenant whose email_id was supplied, allowing
    cross-mailbox writes. Legit same-user multi-account (Gmail + Outlook share
    one user_id) stays allowed; cross-tenant owners are rejected so the caller
    falls back to their own JWT-scoped provider.
    """
    try:
        from app.api._auth_helpers import get_auth_user_id, check_account_ownership
        uid = get_auth_user_id()
        if uid is None:
            return True  # Tauri loopback — single-user host, no restriction
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        with get_db_session() as session:
            acc = AccountRepository(session).get(owner_int)
            if acc is None:
                return False
            return check_account_ownership(acc, uid)
    except Exception:
        return False


@api_bp.route("/emails/<email_id>/restore", methods=["POST"])
def restore_email(email_id: str):
    """
    Restaure un email de la corbeille vers la boîte de réception.

    Args:
        email_id: ID de l'email à restaurer.

    Returns:
        200: {success: true, email_id: "...", message: str}
        400: email_id invalide
        500: Erreur interne
    """
    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email_id format"}), 400

    try:
        # Resolve the provider by EMAIL OWNERSHIP, not by UI-active account.
        # Multi-account Tauri sessions can have a Gmail email_id while the
        # UI sits on the Outlook account; _get_authenticated_provider()
        # would return Outlook, and unarchive_email("<gmail_id>") would
        # silently no-op or fail. Resolve owner → oauth hash → pooled
        # provider for that account so we hit the correct mailbox.
        provider = None
        try:
            owner_int = _resolve_email_owner_account_id(email_id)
            # Only authenticate as the owning account if the JWT caller owns
            # it (audit 2026-05-29). A cross-tenant email_id falls through to
            # the caller's own provider below, where the restore no-ops on a
            # mailbox that doesn't contain it — no cross-mailbox write.
            if owner_int and owner_int > 0 and _caller_owns_account(owner_int):
                from app.quicksteps.auto_trigger import _resolve_oauth_account_id
                oauth_id = _resolve_oauth_account_id(owner_int)
                if oauth_id:
                    from app.providers.factory import get_pooled_provider
                    provider = get_pooled_provider(account_id=str(oauth_id))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"restore: owner-based provider resolution failed: {exc}")
        if provider is None:
            provider = _get_authenticated_provider()

        raw_id = email_id[5:] if email_id.startswith("sent:") else email_id
        source_folder = request.args.get("folder", "trash")

        if source_folder == "archived":
            if hasattr(provider, "unarchive_email"):
                success = provider.unarchive_email(raw_id)
            elif hasattr(provider, "move_to_inbox"):
                success = provider.move_to_inbox(raw_id)
            else:
                return jsonify({"error": "Unarchive not supported by this provider"}), 501
        else:
            if not hasattr(provider, "restore_from_trash"):
                return jsonify({"error": "Restore not supported by this provider"}), 501
            success = provider.restore_from_trash(raw_id)

        if success:
            # Pass `move_to_folder="inbox"` so the SQLite cache row is
            # re-tagged folder='inbox' rather than deleted. Without this
            # the email vanishes from every folder cache and the next
            # inbox refresh doesn't pull it back until the next provider
            # sync (could be minutes).
            _owner_aid = _resolve_email_owner_account_id(email_id)
            _evict_email_from_all_caches(
                email_id,
                move_to_folder="inbox",
                account_id=_owner_aid,
            )
            if raw_id != email_id:
                _evict_email_from_all_caches(
                    raw_id,
                    move_to_folder="inbox",
                    account_id=_owner_aid,
                )
            try:
                from app.api.websocket import emit_email_restored
                # Pass the owning account so the WS event reaches the right
                # room; fall back to broadcast on /daemon so a multi-account
                # FE tab subscribed to a different room still updates.
                try:
                    emit_email_restored(email_id, account_id=_owner_aid)
                except TypeError:
                    emit_email_restored(email_id)
                try:
                    from app.api.websocket import get_socketio
                    _sio = get_socketio()
                    if _sio is not None:
                        _sio.emit("email_restored", {"email_id": email_id}, namespace="/daemon")
                except Exception as _e:
                    logger.debug(f"restore: broadcast failed: {_e}")
            except Exception as e:
                logger.debug(f"Suppressed: {e}")

            return jsonify({
                "success": True,
                "email_id": email_id,
                "message": "Email restored to inbox",
            }), 200
        else:
            logger.warning(
                f"restore: provider {type(provider).__name__} returned False for {_sanitize_for_log(email_id)}"
            )
            return jsonify({
                "error": "Failed to restore email"
            }), 500

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restoring email {_sanitize_for_log(email_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/bulk-restore", methods=["POST"])
def bulk_restore():
    """
    Restaure plusieurs emails de la corbeille vers la boîte de réception.

    Body JSON:
        email_ids: Liste des IDs d'emails à restaurer.

    Returns:
        200: {success: true, updated_count: int, email_ids: [...]}
        400: JSON manquant ou email_ids invalide
        500: Erreur interne
    """
    data, error = require_json()
    if error:
        return error

    email_ids, id_error = validate_bulk_email_ids(
        data, action_label="process",
        validate_id_fn=_validate_email_id, sanitize_fn=_sanitize_for_log,
    )
    if id_error:
        return id_error

    raw_ids = [eid[5:] if eid.startswith("sent:") else eid for eid in email_ids]
    _acct_id = _resolve_account_id_cached()

    # Async path: bulk-restore from trash is the symmetric counterpart
    # of bulk-delete. Same idempotence reasoning applies.
    from app.db.models.bulk_job import JOB_TYPE_RESTORE_FROM_TRASH
    job_id = _enqueue_bulk_if_above_threshold(
        job_type=JOB_TYPE_RESTORE_FROM_TRASH, raw_ids=raw_ids,
    )
    if job_id is not None:
        _invalidate_folder_cache("inbox", "trash")
        with _email_detail_cache_lock:
            for eid in email_ids:
                _email_detail_cache.pop(eid, None)
            for raw_eid in raw_ids:
                _email_detail_cache.pop(raw_eid, None)
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                repo.bulk_update_folder(raw_ids, "inbox", account_id=_acct_id)
                session.commit()
        except Exception as e:
            logger.debug(f"[bulk-restore async] suppressed: {e}")
        return _async_response(job_id, len(raw_ids))

    try:
        provider = _get_authenticated_provider()

        updated_count = 0
        for eid, raw_id in zip(email_ids, raw_ids):
            try:
                if provider.restore_from_trash(raw_id):
                    updated_count += 1
            except Exception as e:
                logger.warning(f"Failed to restore email {_sanitize_for_log(eid)}: {e}")

        # Invalidate caches + update SQLite folder
        _invalidate_folder_cache("inbox", "trash")
        with _email_detail_cache_lock:
            for eid in email_ids:
                _email_detail_cache.pop(eid, None)
            for raw_eid in raw_ids:
                _email_detail_cache.pop(raw_eid, None)
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                # DB stores raw provider IDs — passing the prefixed list
                # would silently match zero rows (Phase 18 regression).
                repo.bulk_update_folder(raw_ids, "inbox", account_id=_acct_id)
                session.commit()
        except Exception as e:
            logger.debug(f"Suppressed: {e}")

        return jsonify({
            "success": True,
            "updated_count": updated_count,
            "email_ids": email_ids,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk restore: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/empty-trash", methods=["POST"])
def empty_trash():
    """
    Vide la corbeille en supprimant définitivement tous les messages.

    Supports `?count_only=true` to return just `{count, will_be_async}`
    without mutating — used by the UI to show the count in the
    confirmation dialog before the user commits.

    Source-of-truth pour l'énumération : la DB locale (table `emails`
    filtrée sur `folder='trash'`). C'est exactement ce que l'utilisateur
    voit dans l'UI — `provider.get_messages(label_ids=['TRASH'])` peut
    retourner 0 sur Gmail si le compte a été synchronisé avec un autre
    flag (label-only vs trashed), ce qui causait un faux "0 supprimé"
    alors que la corbeille était visiblement pleine. Fallback sur le
    provider seulement si la DB locale est vide (premier boot avant
    sync, account fraîchement reconnecté, etc.).

    Returns:
        200 : sync (≤ INLINE_THRESHOLD), {success, deleted_count}
        202 : async (file bulk_jobs), {accepted, mode:"async", job_id, target_total}
        500 : erreur interne
    """
    # account_id resolved up-front so the optimistic-purge helper has it
    # whether or not local DB enumeration succeeded.
    account_id = _resolve_account_id_cached()

    # count_only short-circuit — cheap COUNT(*) before any provider call.
    if _is_count_only():
        cnt = 0
        try:
            if account_id and account_id > 0:
                from sqlalchemy import select as _select, func as _func
                from app.db.models.email import Email
                with _rh.get_db_session() as session:
                    cnt = session.scalar(
                        _select(_func.count(Email.email_id)).where(
                            Email.account_id == account_id,
                            Email.folder == "trash",
                        )
                    ) or 0
        except Exception as e:
            logger.debug(f"[empty-trash count_only] suppressed: {e}")
        return _count_only_response(cnt)

    try:
        provider = _get_authenticated_provider()

        # ── Enumerate from local DB first ──────────────────────────────
        message_ids: list[str] = []
        try:
            if account_id and account_id > 0:
                with _rh.get_db_session() as session:
                    repo = _rh.EmailRepository(session)
                    rows = repo.get_by_folder(
                        account_id=account_id, folder="trash", limit=500,
                    )
                    message_ids = [
                        str(r.email_id) for r in rows if r.email_id
                    ]
        except Exception as e:
            logger.warning(
                f"[empty-trash] local DB enumeration failed (will fall back "
                f"to provider): {e}"
            )

        # Fallback to live provider scan when the cache is empty (fresh
        # install, account just reconnected, etc.).
        if not message_ids:
            trash_folder = _resolve_folder_for_provider(provider, "trash")
            try:
                trash_emails = provider.get_messages(
                    limit=500, label_ids=[trash_folder]
                )
            except Exception as e:
                logger.warning(f"[empty-trash] provider enumeration failed: {e}")
                trash_emails = []
            message_ids = [
                str(getattr(e, "id", "")) for e in trash_emails or []
                if getattr(e, "id", None)
            ]

        if not message_ids:
            _invalidate_folder_cache("trash")
            return jsonify({"success": True, "deleted_count": 0}), 200

        # ── Async path: enqueue delete_forever ─────────────────────────
        from app.db.models.bulk_job import JOB_TYPE_DELETE_FOREVER
        job_id = _enqueue_bulk_if_above_threshold(
            job_type=JOB_TYPE_DELETE_FOREVER, raw_ids=message_ids,
        )
        if job_id is not None:
            # Optimistic local purge: drop the trash rows from SQLite + memory
            # cache immediately so the UI reflects "empty trash" without
            # waiting on the worker. The worker drives the provider deletes
            # in the background; if any fail (404 already-gone is the common
            # case), the user is unaffected because the local row is already
            # gone too.
            _purge_local_trash_rows(account_id)
            _invalidate_folder_cache("trash")
            with _email_detail_cache_lock:
                for mid in message_ids:
                    _email_detail_cache.pop(mid, None)
            return _async_response(job_id, len(message_ids))

        # ── Sync path: small wave (≤ INLINE_THRESHOLD) ────────────────
        # Try batch permanent delete first (requires mail.google.com
        # scope), fall back to batch label removal (gmail.modify scope).
        deleted_count = 0
        requires_full_scope = False
        if hasattr(provider, 'batch_modify_labels'):
            try:
                for eid in message_ids:
                    try:
                        if provider.permanently_delete(eid):
                            deleted_count += 1
                    except InsufficientScopeError:
                        # Permanent : scope complet https://mail.google.com/
                        # absent — la suite passe par le retrait de label.
                        requires_full_scope = True
                        break
                    except Exception:
                        break  # autre échec → fall through to label removal

                if deleted_count == 0:
                    remaining = message_ids
                    deleted_count = provider.batch_modify_labels(
                        remaining,
                        remove_label_ids=["TRASH"],
                    )
            except Exception as e:
                logger.warning(f"Batch empty-trash fallback error: {e}")
        else:
            for eid in message_ids:
                try:
                    if provider.permanently_delete(eid):
                        deleted_count += 1
                except InsufficientScopeError:
                    requires_full_scope = True
                    logger.warning(
                        "Empty-trash: suppression définitive impossible "
                        "(scope complet manquant) — éléments laissés en corbeille"
                    )
                    break
                except Exception as e:
                    logger.warning(f"Failed to delete trash email {eid}: {e}")

        # Sync path also purges local DB so the inbox UI doesn't show
        # ghost rows on the next refresh. The provider has accepted the
        # delete (even when batch_modify_labels just removed TRASH —
        # which on Gmail effectively orphans the row, hidden from any
        # folder view).
        purged_local = _purge_local_trash_rows(account_id)
        _invalidate_folder_cache("trash")
        with _email_detail_cache_lock:
            for mid in message_ids:
                _email_detail_cache.pop(mid, None)

        # Report the user-visible count: even if the provider reported 0
        # (label-only mismatch on Gmail), what the user observes is that
        # the local trash is now empty. Lying about provider success
        # would be wrong, but reporting "0 deleted" while the UI clearly
        # shows the trash empty is its own bug — pick the larger of the
        # two so success messaging matches reality.
        reported = max(deleted_count, purged_local)
        return jsonify({
            "success": True,
            "deleted_count": reported,
            # True quand la suppression définitive a été dégradée en retrait
            # de label faute du scope complet https://mail.google.com/ —
            # permet à l'UI d'être honnête sur ce qui s'est passé.
            "requires_full_scope": requires_full_scope,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error emptying trash folder: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/cleanup-all", methods=["POST"])
def cleanup_all():
    """Empty trash + spam and purge drafts in one shot.

    Trash and spam are routed through the rate-limited bulk-jobs queue —
    ``delete_forever`` for trash, ``move_to_trash`` for spam, the same
    semantics as ``/emails/empty-trash`` and ``/emails/empty-spam`` — so a
    large mailbox doesn't hammer the provider synchronously and the user
    can watch / pause the work in Settings → Background Tasks. Drafts are
    local ``PendingDraft`` rows, not provider messages: they have no
    provider id, so there's nothing for the queue to rate-limit and they
    are purged synchronously inline.

    Returns:
        200 : small wave (≤ INLINE_THRESHOLD combined, or enqueue
              unavailable) — ran sync,
              {success, trash_deleted, spam_deleted, drafts_deleted}
        202 : large wave — trash/spam queued,
              {accepted, mode:"async", trash_job_id?, spam_job_id?,
               drafts_deleted, target_total}
    """
    from app.db.models.bulk_job import (
        JOB_TYPE_DELETE_FOREVER,
        JOB_TYPE_MOVE_TO_TRASH,
    )
    from app.services.bulk_jobs.worker import INLINE_THRESHOLD

    account_id = _resolve_account_id_cached()

    # ── Enumerate trash + spam from the local cache (UI source of truth,
    #    same rationale as empty-trash / empty-spam). ───────────────────
    trash_ids: list[str] = []
    spam_ids: list[str] = []
    if account_id and account_id > 0:
        trash_ids = _list_all_email_ids_in_folder(account_id, "trash")
        spam_ids = _list_all_email_ids_in_folder(account_id, "spam")

    # ── Purge drafts synchronously — local store, fast, not a provider op.
    drafts_deleted = 0
    try:
        from app.domain.entities.pending_draft import PendingDraftStatus
        store = _rh._get_container().get_pending_draft_store()
        # Scope the purge to the CALLER's account. get_all(account_id=None)
        # spans EVERY tenant, so the prior unscoped purge rejected+deleted
        # other tenants' pending and follow-up drafts from the shared store
        # (cross-tenant data loss, audit 2026-05-29). account_id is resolved
        # at the top of this handler; None only for Tauri/loopback (one
        # account → no cross-tenant impact).
        _scoped_aid = str(account_id) if account_id and account_id > 0 else None
        for draft in store.get_all(limit=500, account_id=_scoped_aid):
            try:
                # P1-001: skip already-sent drafts — marking them REJECTED
                # would corrupt the state machine if send_draft just
                # finished concurrently.
                if draft.status == PendingDraftStatus.SENT:
                    continue
                if store.update_status(draft.id, PendingDraftStatus.REJECTED):
                    drafts_deleted += 1
            except Exception:
                continue
        _invalidate_pending_draft_cache(
            account_id=account_id if account_id and account_id > 0 else None
        )
    except Exception as e:
        logger.warning(f"[cleanup-all] drafts error: {e}")

    # ── Async path: combined wave large enough to be worth rate-limiting.
    #    One job per non-empty folder so each can be paused/cancelled
    #    independently and interleaves naturally with other accounts. ────
    if len(trash_ids) + len(spam_ids) > INLINE_THRESHOLD:
        trash_job_id = (
            _enqueue_bulk_job(
                job_type=JOB_TYPE_DELETE_FOREVER, raw_ids=trash_ids,
                params={"reason": "cleanup_all"},
            )
            if trash_ids else None
        )
        spam_job_id = (
            _enqueue_bulk_job(
                job_type=JOB_TYPE_MOVE_TO_TRASH, raw_ids=spam_ids,
                params={"reason": "cleanup_all"},
            )
            if spam_ids else None
        )
        if trash_job_id or spam_job_id:
            # Optimistic local purge for the folders that went async so the
            # UI clears immediately; the worker drives the provider deletes.
            if trash_job_id:
                _purge_local_trash_rows(account_id)
                _invalidate_folder_cache("trash")
            if spam_job_id:
                _purge_local_spam_rows(account_id)
                _invalidate_folder_cache("spam")
            return jsonify({
                "accepted": True,
                "mode": "async",
                "trash_job_id": trash_job_id,
                "spam_job_id": spam_job_id,
                "drafts_deleted": drafts_deleted,
                "target_total": len(trash_ids) + len(spam_ids),
            }), 202
        # Both enqueues fell back (no account / enqueue raised) — fall
        # through to the sync path rather than silently doing nothing.

    # ── Sync path: small wave (or enqueue failure). ────────────────────
    results = {
        "trash_deleted": 0,
        "spam_deleted": 0,
        "drafts_deleted": drafts_deleted,
    }
    provider = None
    try:
        provider = _get_authenticated_provider()
    except Exception as e:
        logger.warning(f"[cleanup-all] provider unavailable for sync path: {e}")

    if provider is not None:
        for eid in trash_ids:
            try:
                if provider.permanently_delete(eid):
                    results["trash_deleted"] += 1
            except InsufficientScopeError:
                # Permanent (scope complet absent) — inutile de re-tenter
                # chaque id. Les éléments restent en corbeille : Gmail les
                # purge nativement après 30 jours.
                logger.warning(
                    "[cleanup-all] suppression définitive impossible "
                    "(scope complet manquant) — éléments laissés en corbeille"
                )
                break
            except Exception:
                continue
        # Spam → trash (move, not permanent delete) for parity with
        # /emails/empty-spam; the trash cron finishes the job for users
        # who also auto-empty trash.
        for eid in spam_ids:
            try:
                if provider.delete_email(eid):
                    results["spam_deleted"] += 1
            except Exception:
                continue
        if trash_ids:
            _purge_local_trash_rows(account_id)
            _invalidate_folder_cache("trash")
        if spam_ids:
            _purge_local_spam_rows(account_id)
            _invalidate_folder_cache("spam")

    return jsonify({"success": True, **results}), 200


@api_bp.route("/emails/clean-inbox", methods=["POST"])
def clean_inbox():
    """
    Archive old emails from inbox to achieve "inbox zero".

    Enumerates inbox messages from the local SQLite cache filtered by
    `older_than_days` (and optionally `keep_unread`), then routes through
    the bulk-jobs queue when the wave exceeds INLINE_THRESHOLD. Below the
    threshold the request stays sync for snappy UX.

    Body JSON:
        older_than_days: positive int (max 1825)
        keep_unread: if true, unread emails are skipped (default: true)
        unsubscribe_newsletters: reserved for future use

    Returns:
        200: small wave — sync archive: {success, archived_count, message}
        202: large wave — queued: {accepted, mode: "async", job_id, target_total}
        400: invalid JSON / params
        401: auth failed
        500: internal error
    """
    data, error = require_json()
    if error:
        return error

    older_than_days = data.get("older_than_days")
    if not older_than_days or not isinstance(older_than_days, int) or older_than_days < 1:
        return jsonify({"error": "older_than_days must be a positive integer"}), 400

    if older_than_days > 365 * 5:
        return jsonify({"error": "older_than_days cannot exceed 1825 (5 years)"}), 400

    keep_unread = bool(data.get("keep_unread", True))

    try:
        from datetime import datetime, timedelta
        from sqlalchemy import select as _select, func as _func

        account_id = _resolve_account_id_cached()
        if not account_id or account_id <= 0:
            return jsonify({"error": "Account not resolved"}), 401

        cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)

        from app.db.models.email import Email

        # ── count_only short-circuit: cheap COUNT(*), no enumeration ───
        if _is_count_only():
            with _rh.get_db_session() as session:
                count_stmt = (
                    _select(_func.count(Email.email_id))
                    .where(
                        Email.account_id == account_id,
                        Email.folder == "inbox",
                        Email.date < cutoff_date,
                    )
                )
                if keep_unread:
                    count_stmt = count_stmt.where(Email.is_read.is_(True))
                cnt = session.scalar(count_stmt) or 0
            return _count_only_response(cnt)

        # Enumerate candidate email_ids from local cache — no provider call
        # here. The bulk-jobs worker pages through them rate-limited.
        with _rh.get_db_session() as session:
            stmt = (
                _select(Email.email_id)
                .where(
                    Email.account_id == account_id,
                    Email.folder == "inbox",
                    Email.date < cutoff_date,
                )
            )
            if keep_unread:
                stmt = stmt.where(Email.is_read.is_(True))
            raw_ids = list(session.scalars(stmt).all())

        if not raw_ids:
            return jsonify({
                "success": True,
                "archived_count": 0,
                "unsubscribed_count": 0,
                "message": "No emails matched the cleanup criteria",
            }), 200

        # ── Async path: enqueue when above INLINE_THRESHOLD ─────────────
        from app.db.models.bulk_job import JOB_TYPE_ARCHIVE as _JT_ARCHIVE
        job_id = _enqueue_bulk_if_above_threshold(
            job_type=_JT_ARCHIVE, raw_ids=raw_ids,
        )
        if job_id is not None:
            # Optimistic local cache eviction so the inbox feels snappy;
            # actual provider mutations land within seconds via the worker.
            _invalidate_folder_cache("inbox")
            with _email_detail_cache_lock:
                for eid in raw_ids:
                    _email_detail_cache.pop(eid, None)
            try:
                with _rh.get_db_session() as session:
                    repo = _rh.EmailRepository(session)
                    repo.bulk_update_folder(
                        raw_ids, "archived", account_id=account_id,
                    )
                    session.commit()
            except Exception as e:
                logger.warning(f"[clean-inbox async] SQLite folder update failed: {e}")
            return _async_response(job_id, len(raw_ids))

        # ── Sync path: small wave (≤ INLINE_THRESHOLD) ──────────────────
        provider = _get_authenticated_provider()
        archived_count = _bulk_provider_op(provider, raw_ids, provider.archive_email, "archive")

        _invalidate_folder_cache("inbox")
        with _email_detail_cache_lock:
            for eid in raw_ids:
                _email_detail_cache.pop(eid, None)
        try:
            with _rh.get_db_session() as session:
                repo = _rh.EmailRepository(session)
                repo.bulk_update_folder(raw_ids, "archived", account_id=account_id)
                session.commit()
        except Exception as e:
            logger.warning(f"[clean-inbox sync] SQLite folder update failed: {e}")

        message = f"Archived {archived_count} email{'s' if archived_count != 1 else ''}"
        if keep_unread:
            message += " (kept unread emails)"

        return jsonify({
            "success": True,
            "archived_count": archived_count,
            "unsubscribed_count": 0,
            "message": message,
        }), 200

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in clean inbox: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


def _auto_label_by_prefix(email_id: str, subject: str, account_id: int | None = None) -> None:
    """Auto-assign project label if subject starts with a known subject_prefix."""
    try:
        container = _rh._get_container()
        label_store = container.get_label_store(account_id=account_id)
        all_labels = label_store.get_labels()

        clean_subj = re.sub(
            r'^(re|fwd?|tr)\s*:\s*', '', (subject or ''), flags=re.IGNORECASE
        ).strip().lower()

        for label in all_labels:
            if not label.subject_prefix:
                continue
            prefix = label.subject_prefix.lower().strip()
            if clean_subj.startswith(prefix):
                from app.domain.entities.email_labels import LabelAssignment
                assignment = LabelAssignment(email_id=email_id)
                assignment.add_custom_label(
                    label.name, 0.99,
                    f"Auto-label envoi: subject prefix '{label.subject_prefix}'"
                )
                label_store.save_assignment(assignment)
                logger.info(f"Auto-labeled sent email {_sanitize_for_log(email_id)} → {label.name}")
                break  # Premier match suffit
    except Exception as e:
        logger.warning(f"Auto-label by prefix failed: {e}")


@api_bp.route("/emails/send-new", methods=["POST"])
def send_new_email():
    """
    Envoie un nouveau message (pas une réponse).

    Crée un brouillon puis l'envoie immédiatement.

    Request Body:
        to (str): Adresse email du destinataire.
        subject (str): Objet du message.
        body (str): Corps du message.
        cc (str, optional): Adresses CC séparées par des virgules.

    Returns:
        JSON avec le statut de l'envoi.
    """
    # Per-tenant bucket (H-8 follow-up #534): le "send_email" littéral
    # mutualisait les 10 envois/min sur tous les tenants — un user pouvait
    # DoS l'envoi pour les autres en saturant la quota.
    try:
        _aid = _resolve_account_id_cached()
    except Exception:
        _aid = "anonymous"
    allowed, retry_after = _rate_limited(f"send_email:{_aid}", max_calls=10, window_seconds=60)
    if not allowed:
        return error_response(
            "TOO_MANY_SENDS",
            "Too many sends, try again later",
            429,
            extra={"retry_after": retry_after},
        )

    # P0-001: validate X-Account-Id ownership before proceeding (defense-in-depth,
    # matches the pattern used by list_emails and other mutation endpoints).
    # Stale localStorage accountId from a different tenant must be rejected here
    # rather than silently ignored.
    _x_acct_hdr = request.headers.get("X-Account-Id")
    if _x_acct_hdr:
        from app.api.routes_helpers import require_owned_account_id, _NO_ACCOUNT_SENTINEL
        if require_owned_account_id(_x_acct_hdr) == _NO_ACCOUNT_SENTINEL:
            return jsonify({"error": "Account not found or not owned by caller", "code": "INVALID_ACCOUNT_HEADER"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    def _strip_text(value) -> str:
        if isinstance(value, str):
            return value.strip()
        return ""

    def _strip_recipient_field(value) -> str:
        if isinstance(value, list):
            return ",".join(
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )
        return _strip_text(value)

    to_email = _strip_recipient_field(data.get("to"))
    subject = _strip_text(data.get("subject"))
    body = _strip_text(data.get("body"))
    cc_raw = _strip_recipient_field(data.get("cc"))
    bcc_raw = _strip_recipient_field(data.get("bcc"))
    from_name = _strip_text(data.get("from_name")) or None
    client_send_id = _strip_text(data.get("client_send_id"))
    if client_send_id.startswith("sent:"):
        client_send_id = client_send_id[len("sent:"):]

    if not to_email:
        return jsonify({"error": "to field is required"}), 400
    if not body:
        return jsonify({"error": "body field is required"}), 400
    if len(subject) > 998:
        return jsonify({"error": "Subject too long (max 998 chars)"}), 400
    if client_send_id and (
        not client_send_id.startswith("compose-") or not _validate_email_id(client_send_id)
    ):
        return jsonify({"error": "Invalid client_send_id format"}), 400

    # Audit 2026-04-25 (sub-report 01 MED-04 / MED-07): reject CRLF in headers.
    # CR/LF in `subject` or `from_name` could be folded into a Bcc:/From:
    # injection by the receiving MTA; even if Gmail's API rejects most
    # malformed payloads, the IMAP_SMTP path is wide open.
    import re as _crlf_re
    _crlf = _crlf_re.compile(r"[\r\n]")
    if _crlf.search(subject):
        return jsonify({"error": "Subject contains invalid characters"}), 400
    if from_name:
        if _crlf.search(from_name):
            return jsonify({"error": "from_name contains invalid characters"}), 400
        # Display-name spoofing defence (sub-report 01 MED-07): reject angle
        # brackets and `@` so the rendered From: header can't impersonate
        # another mailbox.
        if any(ch in from_name for ch in "<>@,;\""):
            return jsonify({"error": "from_name contains invalid characters"}), 400

    # Basic email format validation (RFC 5322 minimal: contains @ with local and domain parts)
    import re as _re_email
    _email_re = _re_email.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

    def _validate_email_list(raw: str) -> list | None:
        if not raw:
            return None
        addrs = [a.strip() for a in raw.split(",") if a.strip()]
        for addr in addrs:
            if not _email_re.match(addr):
                return None  # Invalid address found
        return addrs

    # Audit Cluster A (2026-05-10) U-01: validate `to` against the RFC-5322
    # minimal regex BEFORE calling the provider. Previously the regex only
    # fired through `_validate_email_list` on CC/BCC lists; a single bad
    # token in `to` (e.g. "not-an-email") slipped through to Gmail and the
    # provider's HttpError repr was leaked back to the user via _last_error.
    to_list_validated = _validate_email_list(to_email)
    if to_list_validated is None or not to_list_validated:
        return jsonify({"error": "Invalid recipient email address"}), 400

    try:
        provider = _get_authenticated_provider()
        _request_account_id = _resolve_account_id_for_provider(provider)

        # Parse CC / BCC lists with validation
        cc_list = _validate_email_list(cc_raw)
        bcc_list = _validate_email_list(bcc_raw)
        if cc_raw and cc_list is None:
            return jsonify({"error": "Invalid CC email address"}), 400
        if bcc_raw and bcc_list is None:
            return jsonify({"error": "Invalid BCC email address"}), 400

        # Parse attachments (base64-encoded)
        raw_attachments = data.get("attachments", [])
        attachments = None
        if raw_attachments:
            import base64 as b64mod
            import binascii as _binascii
            attachments = []
            for att in raw_attachments:
                filename = att.get("filename", "file")
                content_type = att.get("content_type", "application/octet-stream")
                try:
                    file_data = b64mod.b64decode(att.get("data", ""), validate=False)
                except (_binascii.Error, ValueError):
                    return error_response(
                        "ATTACHMENT_INVALID_BASE64",
                        f'Invalid attachment: "{filename}" (corrupt base64 encoding)',
                        400,
                        context={"filename": filename},
                    )
                attachments.append((filename, file_data, content_type))

            # Gmail messages.send hard-limits the raw MIME at ~25 MB. Reject early
            # with an actionable message instead of letting the API call fail with
            # a generic 500. Limit applies to total payload; ~33 MB base64 → 25 MB raw.
            GMAIL_MAX_RAW_BYTES = 25 * 1024 * 1024
            total_bytes = sum(len(d) for _, d, _ in attachments)
            if total_bytes > GMAIL_MAX_RAW_BYTES:
                size_mb = total_bytes // (1024 * 1024)
                return error_response(
                    "ATTACHMENTS_TOO_LARGE_GMAIL",
                    f"Attachments too large ({size_mb} MB) — Gmail limit 25 MB.",
                    413,
                    context={"size_mb": size_mb},
                )

        # Assemble HTML body with rendered signature if provided
        signature_html = _strip_text(data.get("signature_html"))
        # If body already contains the signature (user-edited in textarea), skip auto-append
        # Also skip if signature_html is provided (it will handle the signature below)
        if not data.get("skip_signature") and not signature_html:
            from app.utils.signature import append_signature
            body = append_signature(body, account_id=_request_account_id)

        if signature_html:
            from app.utils.signature import _inline_signature_images
            signature_html = _inline_signature_images(signature_html)
            body = (
                f'<div style="font-family:inherit">{body.replace(chr(10), "<br>")}</div>'
                f'<div><br></div>'
                f'<div class="agentys-signature" style="margin-top:16px;padding-top:12px;'
                f'border-top:1px solid #e0e0e0">{signature_html}</div>'
            )
        elif "<" not in body and "&" not in body:
            # Plain-text body without signature — wrap in <div> and convert
            # newlines so providers that always interpret as HTML (is_html=True
            # below) don't collapse line breaks (audit Send-MEDIUM
            # "is_html=True even for plain-text bodies").
            body = (
                '<div style="font-family:inherit;white-space:normal">'
                + body.replace(chr(10), "<br>")
                + '</div>'
            )

        # Send message — fast path: single API call (messages.send)
        to_list = [t.strip() for t in to_email.split(",") if t.strip()]
        success = False

        if hasattr(provider, 'send_new_directly'):
            msg_id = provider.send_new_directly(
                to=to_list,
                subject=subject or "(Sans objet)",
                body=body,
                cc=cc_list,
                bcc=bcc_list,
                attachments=attachments,
                is_html=True,
                from_name=from_name,
            )
            success = msg_id is not None
        else:
            # Fallback: 2-step create_draft + send_draft
            draft_id = provider.create_draft(
                to=to_list,
                subject=subject or "(Sans objet)",
                body=body,
                cc=cc_list,
                bcc=bcc_list,
                is_html=True,
                attachments=attachments,
                from_name=from_name,
            )
            if not draft_id:
                err_detail = getattr(provider, "_last_error", "") or "Failed to create draft"
                return jsonify({"error": _sanitize_provider_error(err_detail)}), 500
            success = provider.send_draft(draft_id)

        if success:
            logger.info(f"New email sent to {_sanitize_for_log(to_email)}")
            _send_now_utc = datetime.now(timezone.utc)
            _sent_cache_email_id = client_send_id or f"compose-{int(_send_now_utc.timestamp())}"

            # Emit email_sent so other devices/views refresh the Sent folder
            # (audit Send-MEDIUM "no email_sent WS event").
            try:
                from app.api.websocket import emit_email_sent
                emit_email_sent(_sent_cache_email_id,
                                account_id=_request_account_id, is_reply=False)
            except Exception as _ws_err:
                logger.debug(f"emit_email_sent (compose) failed: {_ws_err}")

            # Bump Contact.sent_count + ensure ContactStyleProfile for recipients
            try:
                from app.api.routes_helpers import record_sent_recipients
                _all_rcpts = list(to_list or [])
                if cc_list:
                    _all_rcpts.extend(cc_list)
                if bcc_list:
                    _all_rcpts.extend(bcc_list)
                record_sent_recipients(_request_account_id, _all_rcpts)
            except Exception as _rc_err:
                # Audit Cluster C (2026-05-11) B-10.
                logger.warning(
                    "record_sent_recipients (compose) failed: %s",
                    _rc_err, exc_info=True,
                )

            # Track compose AI usage
            if data.get("ai_assisted"):
                try:
                    from app.draft_quality_tracker import get_tracker
                    get_tracker().record_feature("compose_ai", account_id=str(_request_account_id or ""))
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")

            # Extract commitments from composed email in background.
            # Capture account_id inside request context — the background thread
            # has no access to Flask g and data.get("account_id","") was leaving
            # the field blank, detaching suggestions from their owner.
            _commit_acct_id = _request_account_id

            def _extract_compose_commitments():
                try:
                    from app.agents import CommitmentExtractorAgent
                    from app.api.calendar import add_suggestion
                    extractor = CommitmentExtractorAgent()
                    commitments = extractor.extract(body)
                    for c in commitments:
                        add_suggestion(
                            email_id="",
                            account_id=_commit_acct_id,
                            description=c.description,
                            deadline=c.deadline,
                            email_subject=subject,
                            email_sender=to_email,
                            draft_body=body,
                        )
                except Exception as e:
                    # Audit Cluster C (2026-05-11) B-09: commitment extraction
                    # failures silently break the calendar-suggestions feature
                    # for an entire session. Promote to error+exc_info so ops
                    # can see the rot in Sentry / log aggregation.
                    logger.error(
                        "Commitment extraction failed for compose: %s",
                        e, exc_info=True,
                    )

            _rh.submit_background(_extract_compose_commitments)

            # Synchronously insert sent email into SQLite + invalidate cache
            # so the "Envoyés" folder is up-to-date before the HTTP response returns.
            _provider_email = getattr(provider, '_email', '') or ''
            _provider_account_id = (
                getattr(provider, 'account_id', None)
                or getattr(provider, '_account_id', None)
            )
            _account_id_main = _request_account_id
            try:
                with _rh.get_db_session() as _sess:
                    _repo = _rh.EmailRepository(_sess)
                    _now = _send_now_utc.replace(tzinfo=None)
                    _persist_content = should_persist_email_content()
                    _sent_email = Email(
                        email_id=_sent_cache_email_id,
                        account_id=_account_id_main,
                        thread_id=None,
                        subject=subject or "(Sans objet)",
                        sender=_provider_email,
                        sender_name=from_name or '',
                        recipients=to_email,
                        date=_now,
                        body_text=(body or '') if _persist_content else None,
                        body_html='' if _persist_content else None,
                        snippet=(body[:200] if body else '') if _persist_content else None,
                        is_read=True,
                        is_starred=False,
                        is_sent=True,
                        attachments_meta='[{"has":true}]' if attachments else None,
                    )
                    _repo.create(_sent_email)
                    # Collapse rapid-double-click duplicates (same recipient +
                    # subject within the same minute) BEFORE the row becomes
                    # visible. The post-send refresh will dedupe again after
                    # the provider returns the real id, but doing it here
                    # too avoids a transient (2) badge in the inbox list.
                    try:
                        _repo.dedupe_sent_by_content(_account_id_main)
                    except Exception as _dedup_err:
                        logger.debug(f"post-send synchronous dedupe failed: {_dedup_err}")
                    _sess.commit()
                _invalidate_folder_cache("sent")

                # Auto-label by subject prefix (project emails)
                _auto_label_by_prefix(_sent_email.email_id, subject, account_id=_account_id_main)
            except Exception as _ins_err:
                logger.warning(f"Sent cache insert failed: {_ins_err}")

            # Background: refresh IMAP to replace the fake ID with the real Gmail ID
            def _post_send_new_bg():
                try:
                    _oauth_id = _provider_account_id or str(_account_id_main)
                    _refresh_sent_cache_bg(_account_id_main, _oauth_id, 51)
                except Exception as _bg_err:
                    # S-16 fix: include traceback for ops debugging.
                    logger.warning(
                        f"Post-send background refresh failed: {_bg_err}",
                        exc_info=True,
                    )

            _rh.submit_background(_post_send_new_bg)

            # Fire custom firesOn="sent" Quick Steps on the freshly-sent
            # email (e.g. "Follow-up new thread"). The snoozed-draft handler
            # applies its own availability-email skip.
            try:
                from app.api.quicksteps_scheduler import fire_sent_quicksteps_immediate
                from app.quicksteps.types import SentEmailRef
                _fu_acct = str(_resolve_account_id_cached())
                _fu_id = _sent_cache_email_id
                # Pull the real Gmail/Outlook threadId set by the provider
                # during send so reply-detection can pair it back later.
                _fu_thread = getattr(provider, "_last_sent_thread_id", "") or ""
                _fu_record = SentEmailRef(
                    id=_fu_id,
                    recipient=to_email,
                    subject=subject or "(Sans objet)",
                    body_preview=body[:1000] if body else "",
                    thread_id=_fu_thread,
                )
                fire_sent_quicksteps_immediate(_fu_record, _fu_acct)
            except Exception as _fu_err:
                # Audit e2e 2026-06-10 B-03 : promu debug→warning — une panne
                # ici tue silencieusement toutes les règles firesOn=sent.
                logger.warning(f"Sent-side Quick Step fire (compose) failed: {_fu_err}")

            return jsonify({
                "success": True,
                "message": "Email sent successfully",
            })

        # Surface provider's last error so the frontend can show the actual reason
        # (Gmail "Message too large", quota, MIME invalide, etc.) instead of a
        # generic toast. Audit Cluster A (2026-05-10) U-01: pass through the
        # sanitizer so raw `<HttpError …>` reprs and Google endpoint URLs do
        # not leak to the client.
        err_detail = getattr(provider, "_last_error", "") or "Failed to send email"
        return jsonify({"error": _sanitize_provider_error(err_detail)}), 500

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending new email: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@api_bp.route("/emails/save-draft", methods=["POST"])
def save_new_draft():
    """
    Sauvegarde un nouveau message comme brouillon sans l'envoyer.
    Utilisé quand l'utilisateur ferme le modal de composition.
    """
    # Audit Cluster C (2026-05-11) B-05: validate X-Account-Id ownership
    # the same way send_new_email does — a stale localStorage accountId
    # from a foreign tenant must be rejected, not silently fall back to
    # the JWT user's default.
    _x_acct_hdr = request.headers.get("X-Account-Id")
    if _x_acct_hdr:
        from app.api.routes_helpers import require_owned_account_id, _NO_ACCOUNT_SENTINEL
        if require_owned_account_id(_x_acct_hdr) == _NO_ACCOUNT_SENTINEL:
            return jsonify({
                "error": "Account not found or not owned by caller",
                "code": "INVALID_ACCOUNT_HEADER",
            }), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    subject = (data.get("subject") or "").strip()
    body = data.get("body") or ""
    to_raw = (data.get("to") or "").strip()
    cc_raw = (data.get("cc") or "").strip()
    bcc_raw = (data.get("bcc") or "").strip()

    if len(subject) > 998:
        return jsonify({"error": "Subject too long"}), 400
    if len(body) > MAX_BODY_LENGTH:
        return jsonify({"error": "Body too long"}), 400

    import re as _crlf_re2
    if _crlf_re2.search(r"[\r\n]", subject):
        return jsonify({"error": "Subject contains invalid characters"}), 400

    try:
        provider = _get_authenticated_provider()
        _request_account_id = _resolve_account_id_for_provider(provider)

        to_list = [t.strip() for t in to_raw.split(",") if t.strip()] if to_raw else []
        cc_list = [c.strip() for c in cc_raw.split(",") if c.strip()] or None
        bcc_list = [b.strip() for b in bcc_raw.split(",") if b.strip()] or None

        signature_html = (data.get("signature_html") or "").strip()
        if not data.get("skip_signature") and not signature_html:
            from app.utils.signature import append_signature
            body = append_signature(body, account_id=_request_account_id)
        if signature_html:
            from app.utils.signature import _inline_signature_images
            signature_html = _inline_signature_images(signature_html)
            body = (
                f'<div style="font-family:inherit">{body.replace(chr(10), "<br>")}</div>'
                f'<div><br></div>'
                f'<div class="agentys-signature" style="margin-top:16px;padding-top:12px;'
                f'border-top:1px solid #e0e0e0">{signature_html}</div>'
            )

        draft_id = provider.create_draft(
            to=to_list,
            subject=subject or "(Sans objet)",
            body=body,
            cc=cc_list,
            bcc=bcc_list,
            is_html=True,
        )

        if not draft_id:
            err = getattr(provider, "_last_error", "") or "Failed to save draft"
            return jsonify({"error": err[:300]}), 500

        logger.info(f"New compose draft saved: {draft_id}")
        return jsonify({"success": True, "draft_id": draft_id}), 201

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving new draft: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


def _emit_archive_outcome(email_id, archived_ok, account_id, *, reason: str = "post_send_archive_failed") -> None:
    """Emit the right websocket signal after a BACKGROUND archive attempt.

    On success -> ``emit_email_archived`` (the FE keeps the row removed). On
    failure -> ``emit_email_updated({archive_failed})`` so the FE REVERTS the
    optimistic remove and toasts, instead of the original email silently
    reappearing on the next provider sync. Mirrors the manual-archive path
    (Audit Cluster E #325); added to the post-send archive path by the chaos
    audit 2026-06-02 (the post-send path previously emitted "archived"
    unconditionally, so a swallowed 429 / token-expiry archive went silent).
    """
    from app.api.websocket import emit_email_archived, emit_email_updated
    if archived_ok:
        emit_email_archived(email_id, account_id=account_id)
    else:
        logger.warning(
            "[ARCHIVE] background archive failed for %s — surfacing archive_failed to FE",
            _sanitize_for_log(email_id),
        )
        emit_email_updated(
            email_id,
            {"archive_failed": True, "reason": reason},
            account_id=account_id,
        )


@api_bp.route("/emails/<draft_id>/send", methods=["POST"])
def send_draft(draft_id: str):
    """
    Envoie un brouillon de reponse email.

    Utilise le provider email pour envoyer le draft.

    Args:
        draft_id: ID du brouillon a envoyer.

    Returns:
        JSON avec le statut de l'envoi.
    """
    # Per-tenant bucket — same fix shape as send_new_email (#534 follow-up).
    try:
        _aid = _resolve_account_id_cached()
    except Exception:
        _aid = "anonymous"
    allowed, retry_after = _rate_limited(f"send_email:{_aid}", max_calls=10, window_seconds=60)
    if not allowed:
        return error_response(
            "TOO_MANY_SENDS",
            "Too many sends, try again later",
            429,
            extra={"retry_after": retry_after},
        )

    # Validate draft_id format BEFORE authentication (fail fast)
    if not _validate_email_id(draft_id):
        return jsonify({"error": "Invalid draft ID format"}), 400

    # P1-004: guard against double-send from rapid double-click.
    with _send_in_flight_lock:
        if draft_id in _send_in_flight:
            return error_response(
                "SEND_IN_PROGRESS",
                "Send already in progress",
                409,
                extra={"code": "SEND_IN_PROGRESS"},  # legacy `code` field — keep for callers still reading it
            )
        _send_in_flight.add(draft_id)

    try:
        provider = _get_authenticated_provider()
        _request_account_id = _resolve_account_id_for_provider(provider)

        # Lookup original email_id from pending draft store
        store = _rh._get_container().get_pending_draft_store()
        pending = store.get_by_id(draft_id)
        if pending and getattr(pending, "account_id", None) is not None and str(pending.account_id) != str(_request_account_id):
            return jsonify({"error": "Draft not found"}), 404
        original_email_id = pending.email_id if pending else None

        success = provider.send_draft(draft_id)

        # Fallback for SMTP: provider.send_draft relies on in-memory drafts
        # which are lost between requests. Use PendingDraft data to send directly.
        if not success and pending and pending.draft_body:
            logger.info(f"send_draft failed, falling back to send_email for {_sanitize_for_log(draft_id)}")
            from app.utils.signature import append_signature
            body_with_sig = append_signature(
                pending.draft_body,
                account_id=_request_account_id,
                recipient_email=pending.email_sender,
            )
            recipient = pending.email_sender  # reply to original sender
            subject = pending.draft_subject or f"Re: {pending.email_subject}"
            success = provider.send_email(
                to=[recipient],
                subject=subject,
                body=body_with_sig,
                is_html=True,
            )

        if success:
            logger.info(f"Draft sent: {_sanitize_for_log(draft_id)}")

            # Bump Contact.sent_count + ensure ContactStyleProfile for the recipient
            try:
                from app.api.routes_helpers import record_sent_recipients
                _rcpt = pending.email_sender if pending else None
                if _rcpt:
                    record_sent_recipients(_request_account_id, [_rcpt])
            except Exception as _rc_err:
                # Audit Cluster C (2026-05-11) B-10.
                logger.warning(
                    "record_sent_recipients (draft-send) failed: %s",
                    _rc_err, exc_info=True,
                )

            # Post-send: insert reply into sent cache + evict original email cache
            if original_email_id:
                _evict_email_from_all_caches(original_email_id)

                # Insert sent reply into SQLite for immediate visibility in "Envoyés"
                try:
                    _account_id = _request_account_id
                    _reply_subject = (pending.draft_subject or f"Re: {pending.email_subject}") if pending else "Re:"
                    _reply_body = pending.draft_body if pending else ""
                    with _rh.get_db_session() as _sess:
                        _repo = _rh.EmailRepository(_sess)
                        _now = datetime.now(timezone.utc).replace(tzinfo=None)
                        # Retrieve thread_id from original email for accurate thread count
                        _orig = _repo.get_by_email_id(original_email_id, _account_id)
                        _thread_id = _orig.thread_id if _orig else None
                        _persist_content = should_persist_email_content()
                        _sent_email = Email(
                            email_id=f"reply-{int(_now.timestamp())}",
                            account_id=_account_id,
                            thread_id=_thread_id,
                            subject=_reply_subject,
                            sender=getattr(provider, '_email', '') or '',
                            sender_name='',
                            recipients=pending.email_sender if pending else '',
                            date=_now,
                            body_text=(_reply_body or '') if _persist_content else None,
                            body_html='' if _persist_content else None,
                            snippet=(_reply_body[:200] if _reply_body else '') if _persist_content else None,
                            is_read=True,
                            is_starred=False,
                            is_sent=True,
                            attachments_meta=None,
                        )
                        _repo.create(_sent_email)
                        try:
                            _repo.dedupe_sent_by_content(_account_id)
                        except Exception as _dedup_err:
                            logger.debug(f"reply dedupe failed: {_dedup_err}")
                        _sess.commit()
                except Exception as _ins_err:
                    logger.warning(f"Failed to insert sent reply into cache: {_ins_err}")

                _invalidate_folder_cache("sent")

                # SIL-004: update pending draft status so the daemon doesn't
                # regenerate this draft after the email has been sent.
                if pending:
                    try:
                        from app.domain.entities.pending_draft import PendingDraftStatus as _EPDS
                        store.update_status(draft_id, _EPDS.SENT)
                    except Exception as _su_err:
                        logger.warning("Failed to update pending draft status after send: %s", _su_err)

                _oeid = original_email_id
                # S-07 fix: capture account_id BEFORE thread.start().
                _post_send_account_id = _request_account_id
                _post_send_oauth_id = (
                    getattr(provider, 'account_id', None)
                    or getattr(provider, '_account_id', None)
                    or str(_request_account_id)
                )
                _detach_provider_from_request(provider)
                def _post_send_bg():
                    try:
                        from concurrent.futures import ThreadPoolExecutor
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            pool.submit(_safe_call, provider.mark_as_read, _oeid)
                            _f_archive = pool.submit(_safe_call, provider.archive_email, _oeid)
                        # _safe_call returns archive_email's bool, or None on a
                        # swallowed 429 / token-expiry / timeout. Chaos audit
                        # 2026-06-02: emit the REAL outcome — previously we emitted
                        # "archived" unconditionally, so a failed background archive
                        # was silent and the original reappeared at the next sync.
                        _archived_ok = bool(_f_archive.result())
                        # Re-evict cache after archive completes (prevents stale cache race)
                        _evict_email_from_all_caches(_oeid)
                        try:
                            _emit_archive_outcome(_oeid, _archived_ok, _post_send_account_id)
                        except Exception as e:
                            logger.debug(f"Suppressed: {e}")
                        # Refresh sent cache in background to replace placeholder with real IMAP email
                        try:
                            _refresh_sent_cache_bg(_post_send_account_id, _post_send_oauth_id, 51)
                        except Exception as e:
                            logger.debug(f"Suppressed: {e}")
                    finally:
                        try:
                            provider.disconnect()
                        except Exception as e:
                            logger.debug(f"Suppressed: {e}")
                _rh.submit_background(_post_send_bg)

            return jsonify({
                "success": True,
                "draft_id": draft_id,
                "message": "Email sent successfully"
            })

        return jsonify({"error": "Failed to send draft"}), 502

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending draft {_sanitize_for_log(draft_id)}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500
    finally:
        with _send_in_flight_lock:
            _send_in_flight.discard(draft_id)


# ---------------------------------------------------------------------------
# Pin / Unpin (backend-persisted so daemon auto-trigger pins survive refreshes)
# ---------------------------------------------------------------------------

@api_bp.route("/emails/pinned", methods=["GET"])
def get_pinned_email_ids():
    """Return the account's persisted pinned email IDs.

    Returns:
        200: {pinned_ids: string[]}
    """
    import json
    from app.db.models.account import Account
    try:
        acct_id = _resolve_account_id_for_user()
        if not acct_id:
            return jsonify({"pinned_ids": []})
        with _rh.get_db_session() as session:
            account = session.get(Account, acct_id)
            if not account:
                return jsonify({"pinned_ids": []})
            pinned = json.loads(account.pinned_email_ids_json or "[]")
        return jsonify({"pinned_ids": pinned})
    except Exception as e:
        logger.error("get_pinned_email_ids error: %s", e)
        return jsonify({"pinned_ids": []})


@api_bp.route("/emails/<email_id>/pin", methods=["POST", "DELETE"])
def toggle_email_pin(email_id: str):
    """Pin (POST) or unpin (DELETE) an email for the current account.

    Audit Cluster E (2026-05-11) U-10: the response no longer carries the
    full ``pinned_ids`` array. The frontend only consumes pinned_ids from
    the dedicated GET /api/emails/pinned endpoint at mount time; toggle
    responses were fire-and-forget (`pinEmail(id).catch(() => {})` in
    `usePinned`). Shipping a 79-element (and growing) array on every
    pin/unpin click was unbounded bandwidth + memory tax for zero use.

    Returns:
        200: {ok: true, pinned: boolean}
        400: invalid email_id
        404: account not found
        500: internal error
    """
    from app.db.models.account import Account
    if not _validate_email_id(email_id):
        return jsonify({"error": "Invalid email_id format"}), 400
    try:
        acct_id = _resolve_account_id_for_user()
        if not acct_id:
            return jsonify({"error": "No account"}), 400
        # Preserve the 404 contract …
        with _rh.get_db_session() as session:
            if session.get(Account, acct_id) is None:
                return jsonify({"error": "Account not found"}), 404
        # … then mutate through the locked helpers so this HTTP path, the wake
        # sweep, and the draft paths all serialize on the same _pin_lock — no
        # last-writer-wins lost pin/unpin (chaos audit 2026-06-02).
        from app.services.pinned_emails import add_pinned_email_id, remove_pinned_email_id
        if request.method == "POST":
            add_pinned_email_id(acct_id, email_id)
            is_pinned = True
        else:
            remove_pinned_email_id(acct_id, email_id)
            is_pinned = False
        return jsonify({"ok": True, "pinned": is_pinned})
    except Exception as e:
        logger.error("toggle_email_pin error: %s", e)
        return jsonify({"error": "Internal error"}), 500
