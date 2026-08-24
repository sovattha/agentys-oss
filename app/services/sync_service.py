# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Background email sync service.

Runs in a daemon thread to sync emails from all connected accounts
at configurable intervals (default 2 minutes).
"""

import functools
import html
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, List, Optional, TypeVar

from sqlalchemy.orm import Session

from app.config import should_persist_email_content
from app.services.email_metadata import serialize_classification_headers
from app.db.database import get_db_session, get_db_session_with_retry
from app.db.models import Account, Email
from app.db.repositories import AccountRepository, EmailRepository, ContactRepository
from app.services.cache_manager import get_cache_manager

logger = logging.getLogger(__name__)

SENT_DELTA_PULL_INTERVAL = timedelta(minutes=30)
SENT_DELTA_PULL_LIMIT = 25

# Type variable for retry decorator
T = TypeVar("T")


def _serialize_classification_headers(std_email) -> Optional[str]:
    """Extract RFC bulk-detection headers from a StandardEmail's raw_metadata
    and return them as a compact JSON string suitable for Email.raw_headers.

    Returns None when no relevant headers are present so we don't waste a row
    write on an empty `{}`.
    """
    raw_meta = getattr(std_email, "raw_metadata", None)
    if not isinstance(raw_meta, dict):
        return None
    cls_headers = raw_meta.get("classification_headers")
    if not isinstance(cls_headers, dict) or not cls_headers:
        return None
    return serialize_classification_headers(cls_headers)


@dataclass
class SyncResult:
    """Result of a sync operation for one account."""

    account_id: int
    account_email: str
    success: bool
    new_emails_count: int = 0
    error_message: Optional[str] = None
    duration_ms: int = 0


@dataclass
class SyncStatus:
    """Current status of the sync service."""

    is_running: bool = False
    is_syncing: bool = False
    last_sync_at: Optional[datetime] = None
    next_sync_at: Optional[datetime] = None
    sync_interval_seconds: int = 120
    last_results: List[SyncResult] = field(default_factory=list)


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """
    Decorator for retrying functions with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts.
        base_delay: Initial delay in seconds before first retry.
        exponential_base: Base for exponential backoff (delay = base_delay * exponential_base^attempt).
        exceptions: Tuple of exception types to catch and retry.

    Returns:
        Decorated function with retry logic.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        delay = base_delay * (exponential_base ** attempt)
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_attempts} failed for {func.__name__}: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_attempts} attempts failed for {func.__name__}: {e}"
                        )

            raise last_exception

        return wrapper
    return decorator


def _get_account_setting(account: Account, key: str, default=None):
    """Read a key from Account.settings_json (JSON-encoded dict) with fallback."""
    if not account.settings_json:
        return default
    try:
        return json.loads(account.settings_json).get(key, default)
    except Exception:
        return default


def _set_account_setting(account: Account, key: str, value) -> None:
    """Upsert a key into Account.settings_json. Caller commits the session."""
    data: dict = {}
    if account.settings_json:
        try:
            data = json.loads(account.settings_json)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    data[key] = value
    account.settings_json = json.dumps(data)


def _register_deferred_auto_reply_hooks(session: Session) -> None:
    """Wire after_commit/after_rollback hooks on the sync session so
    deferred auto-reply dispatches (stashed in
    ``session.info["_deferred_auto_replies"]`` by ``_store_emails``)
    fire only AFTER a successful commit, and are dropped on rollback.

    Audit F-06 (2026-05-16): the pre-fix path dispatched SMTP inline
    inside the open write transaction. Any later rollback left the
    email row gone but the OOO reply already sent; combined with the
    process-local ``_REPLIED_SENDERS`` set being wiped by a Railway
    redeploy, the next sync re-fired the same auto-reply.
    """
    from sqlalchemy import event as _sa_event

    def _drain(s, *_args, **_kwargs) -> None:
        jobs = s.info.pop("_deferred_auto_replies", None) or []
        for job in jobs:
            try:
                job()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Deferred auto-reply dispatch raised: {e!r}")

    def _clear(s, *_args, **_kwargs) -> None:
        s.info.pop("_deferred_auto_replies", None)

    try:
        _sa_event.listen(session, "after_commit", _drain)
        _sa_event.listen(session, "after_rollback", _clear)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Could not register deferred-auto-reply hooks: {e!r}")


def _finish_sync_db_batch(session: Session, account_email: str, next_phase: str) -> None:
    """Close any open sync transaction before the next provider/network phase."""
    try:
        in_transaction = session.in_transaction()
    except Exception:
        in_transaction = True
    if not in_transaction:
        return

    try:
        session.commit()
    except Exception as e:
        # Audit Cluster D (2026-05-17) B-10: previously the nested rollback
        # failure was swallowed with bare `pass`, leaving the session in a
        # PendingRollbackError state. Every subsequent query then hit
        # "current transaction is aborted, commands ignored" and sync went
        # silently dead. Log + force-close so the next call rebuilds.
        try:
            session.rollback()
        except Exception as rb_err:
            logger.error(
                "sync_service: rollback itself failed for %s before %s: %s",
                account_email, next_phase, rb_err, exc_info=True,
            )
            try:
                session.close()
            except Exception:
                pass
        logger.warning(
            "Failed to close sync DB transaction before %s for %s: %s",
            next_phase,
            account_email,
            e,
        )
        raise


def _is_auth_expired_error(exc: BaseException) -> bool:
    """Heuristique : est-ce que ``exc`` ressemble à un token expiré ?

    On reconnaît :
    - googleapiclient ``HttpError`` avec ``resp.status`` 401
    - googleapiclient ``HttpError`` 403 quand Google signale des scopes OAuth
      manquants (l'utilisateur a refusé une autorisation)
    - msgraph / azure ``HttpResponseError`` avec ``status_code`` 401
    - les erreurs Google ``RefreshError`` (refresh token révoqué/expiré)
    - les ``RuntimeError`` levées par ``_ensure_authenticated`` quand
      ``authenticate()`` échoue
    - tout exception dont le message contient "401", "Unauthorized" ou
      "invalid_grant" (filet de sécurité pour les exceptions custom des
      providers tiers — IMAP, Outlook, etc.)

    Volontairement permissif : un faux-positif déclenche une re-auth qui
    est idempotente et coûte ~50ms ; un faux-négatif laisse le sync rapporter
    succès partiel sans alerter (le bug qu'on fixe). Asymétrie en notre faveur.
    """
    # Cas typés ; on évite l'import top-level pour ne pas forcer la dep.
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 401:
        return True
    msg = str(exc).lower()
    if status == 403 and _is_reauth_required_error_message(msg):
        return True
    if getattr(exc, "status_code", None) == 401:
        return True
    name = type(exc).__name__
    if name in {"RefreshError", "InvalidGrantError", "UnauthorizedError"}:
        return True
    if _is_reauth_required_error_message(msg):
        return True
    if "authentification" in msg and ("requise" in msg or "cooldown" in msg):
        # `_ensure_authenticated` côté gmail_adapter
        return True
    return False


def _is_reauth_required_error_message(message: str) -> bool:
    msg = message.lower()
    return any(token in msg for token in (
        "401",
        "unauthorized",
        "invalid_grant",
        "consent_required",
        "interaction_required",
    )) or _is_missing_oauth_scope_error_message(msg)


def _is_missing_oauth_scope_error_message(message: str) -> bool:
    msg = message.lower()
    return any(token in msg for token in (
        "insufficient authentication scopes",
        "insufficientpermissions",
        "insufficient permissions",
        "access_token_scope_insufficient",
        "insufficientscope",
    ))


def _provider_low_priority_retry_after_seconds(adapter) -> int:
    """Return provider-advertised cooldown for non-critical metadata fetches."""
    if getattr(type(adapter), "low_priority_quota_retry_after_seconds", None) is None:
        return 0
    getter = getattr(adapter, "low_priority_quota_retry_after_seconds", None)
    if not callable(getter):
        return 0
    try:
        return max(0, int(getter()))
    except Exception:
        return 0


def _skip_low_priority_provider_fetch(adapter, account_email: str, phase: str) -> bool:
    retry_after = _provider_low_priority_retry_after_seconds(adapter)
    if retry_after <= 0:
        return False
    logger.info(
        "Skipping low-priority provider fetch phase=%s account=%s retry_after=%ss",
        phase,
        account_email,
        retry_after,
    )
    return True


# Cap on how many recently-fetched bodies the sync warms into the in-memory
# detail cache per batch. Stays well under that cache's 150-entry bound so the
# most-recent mail (what users actually open) is not evicted by its own warm.
_SYNC_BODY_PREFETCH_LIMIT = 100

# Minimal HTML-tag probe — text-only bodies are wrapped so they satisfy
# get_email's body_ready gate (mirrors _fetch_body_html_background).
_BODY_HTML_TAG_RE = re.compile(
    r'<(div|p|br|table|span|a\s|img|ul|ol|li|h[1-6]|blockquote)[^>]*>',
    re.IGNORECASE,
)


def _warm_detail_cache_from_sync(emails: List, account: Account) -> int:
    """Warm the in-memory email-detail cache with bodies the sync already
    pulled from the provider, so the first on-demand open is instant.

    Metadata-only mode (the default) does NOT persist bodies to SQLite, so
    without this every email open re-fetches the body from the provider. On a
    freshly-connected account those on-demand fetches compete with the initial
    sync for Microsoft Graph quota and get 429-throttled — the ~8-30s "cold
    open" latency. The sync already fetched these bodies (Graph `$select`
    includes `body`), so reusing them costs ZERO extra provider calls.

    Only touches the existing RAM-only, TTL'd, account-keyed detail cache — the
    same transient store the on-demand path already populates — so it keeps the
    metadata-only privacy posture (no new persistence). Bounded to the most
    recent N, inserted oldest-first so the newest (most-likely-opened) mail
    sits at the MRU end and survives eviction longest.

    Skips emails with attachments or unresolved inline `cid:` images: their
    cache entry would fail get_email's body_ready/att_ok gate and fall through
    to the on-demand fetch anyway, so warming them is dead weight.

    Returns the number of bodies warmed (for logging/tests).
    """
    try:
        from app.api.routes_helpers import _set_cached_email_detail
    except Exception:  # pragma: no cover — best-effort, helper import optional
        return 0

    warmed = 0
    # Most-recent first from the provider; reverse so the newest is inserted
    # LAST (MRU end) and is evicted last under the 150-entry bound.
    batch = list(emails)[:_SYNC_BODY_PREFETCH_LIMIT]
    for std in reversed(batch):
        eid = getattr(std, "id", None)
        if not eid or getattr(std, "has_attachments", False):
            continue
        body_text = getattr(std, "body", "") or ""
        body_html = getattr(std, "body_html", "") or ""
        if not body_html and body_text:
            body_html = (
                body_text if _BODY_HTML_TAG_RE.search(body_text)
                else f'<div style="white-space:pre-wrap">{html.escape(body_text)}</div>'
            )
        # Mirror get_email's body_ready gate — never cache an entry it would
        # reject (that would just mask a needed re-fetch).
        if not body_html or 'cid:' in body_html.lower():
            continue
        try:
            _set_cached_email_detail(eid, {
                "id": eid,
                "sender": getattr(std, "sender", "") or "",
                "sender_name": getattr(std, "sender_name", None),
                "subject": getattr(std, "subject", "") or "",
                "received_at": str(getattr(std, "received_at", "") or ""),
                "body": body_text,
                "body_html": body_html,
                "body_preview": body_text[:200],
                "body_text": body_text,
                "is_read": getattr(std, "is_read", True),
                "has_attachments": False,
                "attachments": [],
                "meeting_meta": None,
                "cc": list(getattr(std, "cc", []) or []),
                "labels": [],
                "conversation_id": getattr(std, "conversation_id", None) or eid,
                "has_pending_draft": False,
            }, account_id=account.id)
            warmed += 1
        except Exception:  # pragma: no cover — caching is best-effort
            continue
    if warmed:
        logger.debug(
            "Sync warmed %d email bodies into the detail cache for account %s",
            warmed, getattr(account, "id", "?"),
        )
    return warmed


class SyncService:
    """
    Background email sync service.

    Runs in a daemon thread to periodically sync emails from all
    connected accounts. Supports delta sync (only new emails since
    last sync) and retry logic with exponential backoff.

    Usage:
        sync_service = SyncService(sync_interval=120)
        sync_service.start()
        # ... app runs ...
        sync_service.stop()
    """

    def __init__(
        self,
        sync_interval: int = 120,
        on_sync_started: Optional[Callable[[List[int]], None]] = None,
        on_sync_progress: Optional[Callable[[int, str], None]] = None,
        on_sync_complete: Optional[Callable[[List[SyncResult], int], None]] = None,
        on_sync_error: Optional[Callable[[int, str], None]] = None,
        on_new_email: Optional[Callable[[dict], None]] = None,
        max_concurrent_account_syncs: Optional[int] = None,
    ):
        """
        Initialize the sync service.

        Args:
            sync_interval: Interval between syncs in seconds (default 120 = 2 minutes).
            on_sync_started: Callback when sync starts, receives list of account IDs.
            on_sync_progress: Callback for progress, receives (account_id, status).
            on_sync_complete: Callback when sync completes, receives (results, duration_ms).
            on_sync_error: Callback on error, receives (account_id, error_message).
            on_new_email: Callback for each new email, receives email dict.
        """
        self.sync_interval = sync_interval
        self._stop_flag = threading.Event()
        self._sync_thread: Optional[threading.Thread] = None
        self._is_syncing = False
        self._sync_lock = threading.Lock()
        self._sync_started_at_monotonic: Optional[float] = None
        self._sync_generation = 0
        self._active_full_sync_generation: Optional[int] = None
        self._active_account_sync_generations: dict[int, int] = {}
        self._active_account_sync_started_at: dict[int, float] = {}
        self._pending_account_sync_ids: set[int] = set()
        raw_max_concurrency = (
            max_concurrent_account_syncs
            if max_concurrent_account_syncs is not None
            else os.getenv("AGENTYS_MAX_CONCURRENT_ACCOUNT_SYNCS", "4")
        )
        try:
            self.max_concurrent_account_syncs = max(1, int(raw_max_concurrency))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid AGENTYS_MAX_CONCURRENT_ACCOUNT_SYNCS=%r; using 4",
                raw_max_concurrency,
            )
            self.max_concurrent_account_syncs = 4
        self._STALE_SYNC_SECONDS = 10 * 60

        # Auth failure backoff. The third tuple slot is the monotonic
        # timestamp of the *last* update — used to evict stale entries
        # for deleted / disabled accounts that would otherwise leak one
        # row per delete-after-failure for the lifetime of the process
        # (cf. 2026-04-25 audit M-2).
        self._auth_backoff: dict[int, tuple[int, float, float]] = {}
        self._AUTH_BACKOFF_BASE = 60  # 1 min initial backoff
        self._AUTH_BACKOFF_MAX = 3600  # 1 hour max backoff
        self._AUTH_BACKOFF_TTL = 7 * 24 * 3600  # 7 days — drop entries older than this
        # Au-delà de N échecs d'auth PERMANENTS consécutifs (invalid_grant =
        # token révoqué côté IdP), désactiver le compte au lieu de re-tenter
        # pour toujours. Audit 2026-06-09 : 5 comptes Outlook zombies
        # re-tentés 67× chacun (+ bannières token_expired et appels IdP à
        # chaque cycle). 10 échecs ≈ ~9 h de retries avec le backoff actuel.
        self._AUTH_DEACTIVATE_AFTER = 10

        # Status tracking
        self._status = SyncStatus(sync_interval_seconds=sync_interval)

        # Callbacks for WebSocket events
        self._on_sync_started = on_sync_started
        self._on_sync_progress = on_sync_progress
        self._on_sync_complete = on_sync_complete
        self._on_sync_error = on_sync_error
        self._on_new_email = on_new_email

    @property
    def status(self) -> SyncStatus:
        """Get current sync status."""
        with self._sync_lock:
            self._clear_stale_sync_flag_locked()
        return self._status

    def _clear_stale_sync_flag_locked(self, now: Optional[float] = None) -> bool:
        """Release a sync flag that has been stuck for too long.

        The caller must hold ``_sync_lock``. This does not stop the stale
        daemon thread, but it prevents one hung provider call from blocking
        future Gmail push/manual sync triggers until process restart.
        """
        now = now if now is not None else time.monotonic()
        cleared = False

        if self._active_full_sync_generation is not None:
            started_at = self._sync_started_at_monotonic
            if started_at is not None:
                elapsed = now - started_at
                if elapsed >= self._STALE_SYNC_SECONDS:
                    logger.warning(
                        "Full sync marked in progress for %.1fs; clearing stale flag",
                        elapsed,
                    )
                    self._active_full_sync_generation = None
                    self._sync_started_at_monotonic = None
                    cleared = True

        stale_account_ids = [
            account_id
            for account_id, started_at in self._active_account_sync_started_at.items()
            if (now - started_at) >= self._STALE_SYNC_SECONDS
        ]
        for account_id in stale_account_ids:
            elapsed = now - self._active_account_sync_started_at[account_id]
            logger.warning(
                "Account sync %s marked in progress for %.1fs; clearing stale flag",
                account_id,
                elapsed,
            )
            self._active_account_sync_started_at.pop(account_id, None)
            self._active_account_sync_generations.pop(account_id, None)
            cleared = True

        has_structured_sync = (
            self._active_full_sync_generation is not None
            or bool(self._active_account_sync_generations)
        )
        if has_structured_sync:
            self._is_syncing = True
            self._status.is_syncing = True
            return cleared

        if cleared:
            self._is_syncing = False
            self._status.is_syncing = False
            return True

        if not self._is_syncing:
            self._status.is_syncing = False
            return cleared

        # Compatibility path for tests or older in-process state where only
        # the legacy global flag was set.
        if self._sync_started_at_monotonic is None:
            return cleared

        elapsed = now - self._sync_started_at_monotonic
        if elapsed < self._STALE_SYNC_SECONDS:
            return cleared

        logger.warning(
            "Sync marked in progress for %.1fs; clearing stale flag",
            elapsed,
        )
        self._is_syncing = False
        self._status.is_syncing = False
        self._sync_started_at_monotonic = None
        return True

    def _has_structured_sync_locked(self) -> bool:
        """Return True when a full or account-scoped sync is registered."""
        return (
            self._active_full_sync_generation is not None
            or bool(self._active_account_sync_generations)
        )

    def _refresh_syncing_flag_locked(self) -> None:
        """Mirror structured sync reservations onto the public status flag."""
        self._is_syncing = self._has_structured_sync_locked()
        self._status.is_syncing = self._is_syncing

    def _reserve_account_syncs_locked(
        self,
        account_ids: Iterable[int] = (),
    ) -> list[tuple[int, int]]:
        """Reserve pending account sync slots up to the concurrency cap.

        The caller must hold ``_sync_lock``. Requested ids are first merged into
        the deduplicated pending set, then only free accounts are promoted into
        active reservations. This is the backpressure point that prevents a
        Gmail push burst from creating one thread per account.
        """
        requested_account_ids = {int(account_id) for account_id in account_ids}
        if requested_account_ids:
            self._pending_account_sync_ids.update(requested_account_ids)

        if self._active_full_sync_generation is not None:
            self._refresh_syncing_flag_locked()
            return []

        active_account_ids = set(self._active_account_sync_generations)
        free_slots = self.max_concurrent_account_syncs - len(active_account_ids)
        if free_slots <= 0:
            self._refresh_syncing_flag_locked()
            return []

        if requested_account_ids:
            candidate_account_ids = requested_account_ids - active_account_ids
        else:
            candidate_account_ids = self._pending_account_sync_ids - active_account_ids
        ready_account_ids = sorted(candidate_account_ids)[:free_slots]
        if not ready_account_ids:
            self._refresh_syncing_flag_locked()
            return []

        self._sync_generation += 1
        sync_generation = self._sync_generation
        started_at = time.monotonic()
        for account_id in ready_account_ids:
            self._active_account_sync_generations[account_id] = sync_generation
            self._active_account_sync_started_at[account_id] = started_at
            self._pending_account_sync_ids.discard(account_id)

        self._refresh_syncing_flag_locked()
        return [(account_id, sync_generation) for account_id in ready_account_ids]

    def _start_reserved_account_syncs(
        self,
        reserved_account_syncs: Iterable[tuple[int, int]],
    ) -> None:
        """Start one bounded worker per pre-reserved account sync slot."""
        for account_id, sync_generation in reserved_account_syncs:
            threading.Thread(
                target=self._perform_sync,
                kwargs={
                    "only_account_ids": [account_id],
                    "claimed_account_sync_generation": sync_generation,
                },
                daemon=True,
                name=f"AccountSyncThread-{account_id}",
            ).start()

    def get_reauth_required_accounts(self, threshold: int = 3) -> list[int]:
        """Return account_ids en backoff auth (tokens OAuth révoqués/invalides).

        Un compte est considéré "needs_reauth" s'il a accumulé ≥ threshold
        échecs d'authentification consécutifs. Utilisé par l'API pour exposer
        l'état au frontend → bannière "Reconnectez votre compte X" au lieu
        d'un spinner "Loading..." infini quand l'onboarding attend un sync
        qui ne viendra jamais tant que l'utilisateur ne re-OAuth pas.
        """
        with self._sync_lock:
            return [
                account_id
                for account_id, entry in self._auth_backoff.items()
                if entry[0] >= threshold  # entry = (failures, next_retry, last_update)
            ]

    def evict_auth_backoff(self, account_id: int) -> bool:
        """Audit P1-A4 (mother-of-all 2026-04-25) — drop l'entrée backoff.

        À appeler par les handlers qui désactivent / suppriment un compte
        (``account_repository.deactivate``, route admin, etc.). Sans cette
        éviction explicite, l'entrée vit jusqu'au TTL (7j) et bloque la
        re-création du même compte si l'AccountManager réutilise un
        ``account_id`` (rare mais possible avec un soft-delete + restore).

        Le TTL eviction (M-2 dans le code ci-dessus) reste un filet de
        sécurité pour les chemins qui oublient d'appeler ce hook.

        Retourne True si une entrée a été évincée, False sinon.
        """
        with self._sync_lock:
            return self._auth_backoff.pop(account_id, None) is not None

    @property
    def is_running(self) -> bool:
        """Check if sync service is running."""
        return self._status.is_running

    @property
    def is_syncing(self) -> bool:
        """Check if a sync is currently in progress."""
        return self._is_syncing

    def start(self) -> None:
        """Start the background sync thread."""
        if self._status.is_running:
            logger.warning("Sync service already running")
            return

        self._stop_flag.clear()
        self._sync_thread = threading.Thread(
            target=self._sync_loop,
            daemon=True,
            name="EmailSyncThread"
        )
        self._sync_thread.start()
        self._status.is_running = True
        logger.info(f"Sync service started (interval: {self.sync_interval}s)")

    def stop(self, timeout: float = 5.0) -> None:
        """
        Signal the sync thread to stop.

        Args:
            timeout: Maximum time to wait for thread to finish.
        """
        if not self._status.is_running:
            return

        logger.info("Stopping sync service...")
        self._stop_flag.set()

        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=timeout)
            if self._sync_thread.is_alive():
                logger.warning("Sync thread did not stop gracefully")

        self._status.is_running = False
        logger.info("Sync service stopped")

    def trigger_sync(self) -> bool:
        """
        Trigger an immediate sync if not already syncing.

        Returns:
            True if sync was triggered, False if already syncing.
        """
        with self._sync_lock:
            if self._is_syncing and not self._clear_stale_sync_flag_locked():
                logger.info("Sync already in progress, skipping trigger")
                return False

        # Run sync in a separate thread to not block
        threading.Thread(
            target=self._perform_sync,
            daemon=True,
            name="ManualSyncThread"
        ).start()

        return True

    def trigger_account_sync(self, account_id: int) -> bool:
        """Trigger an immediate sync for one DB account only.

        Gmail push callbacks are already scoped to a concrete mailbox. Running
        the full all-account sync for every push amplifies Pub/Sub bursts into
        provider rate limits and leaves new messages waiting behind unrelated
        accounts.
        """
        account_id = int(account_id)
        reserved_account_syncs: list[tuple[int, int]] = []
        with self._sync_lock:
            self._clear_stale_sync_flag_locked()
            legacy_busy = (
                self._is_syncing
                and not self._has_structured_sync_locked()
            )
            if legacy_busy:
                self._pending_account_sync_ids.add(account_id)
                logger.info(
                    "Legacy sync already in progress, queued trigger for account %s",
                    account_id,
                )
                return True

            was_pending = account_id in self._pending_account_sync_ids
            was_active = account_id in self._active_account_sync_generations
            full_sync_active = self._active_full_sync_generation is not None
            reserved_account_syncs = self._reserve_account_syncs_locked([account_id])
            if not reserved_account_syncs and not was_pending and not was_active:
                reason = (
                    "full sync in progress" if full_sync_active else "capacity full"
                )
                logger.info(
                    "Queued trigger for account %s (%s)",
                    account_id,
                    reason,
                )

        self._start_reserved_account_syncs(reserved_account_syncs)
        return True

    def _sync_loop(self) -> None:
        """Main sync loop running in background thread.

        H-3 fix (2026-04-25 audit): the loop body is wrapped in try/except
        so that any unexpected exception (clock changes, monkey-patched
        datetime in tests, RTC anomalies on Windows, interpreter
        shutdown races) doesn't kill the thread permanently. Without
        this guard the API stayed up but syncing silently stopped until
        process restart, with no signal to the user. On exception we
        log + back off 30s before retrying.
        """
        logger.debug("Sync loop started")

        # Perform initial sync
        try:
            self._perform_sync()
        except Exception:
            logger.exception("Initial sync raised; continuing into the polling loop")

        # Quiet window — if a user request was handled within the last
        # _USER_QUIET_SEC, defer the next sync by up to _MAX_DEFER_SEC so
        # heavy multi-account polling doesn't collide with interactive
        # endpoints (transcribe, compose, refine).
        _USER_QUIET_SEC = 8.0
        _MAX_DEFER_SEC = 20.0

        while not self._stop_flag.is_set():
            try:
                # Calculate next sync time
                self._status.next_sync_at = datetime.now(timezone.utc).replace(
                    microsecond=0
                )

                # Wait for interval or stop signal
                if self._stop_flag.wait(timeout=self.sync_interval):
                    break

                # Defer if a user just interacted — capped to _MAX_DEFER_SEC
                # so we never starve the sync indefinitely.
                try:
                    from app.services.user_activity import seconds_since_activity
                    waited = 0.0
                    while waited < _MAX_DEFER_SEC:
                        since = seconds_since_activity()
                        if since >= _USER_QUIET_SEC:
                            break
                        step = min(2.0, _MAX_DEFER_SEC - waited)
                        if self._stop_flag.wait(timeout=step):
                            return
                        waited += step
                    if waited > 0:
                        logger.debug(
                            "Sync deferred %.1fs for user quiet window", waited
                        )
                except Exception:
                    logger.debug("user_activity check failed", exc_info=True)

                # Perform sync
                self._perform_sync()
            except Exception:
                logger.exception(
                    "Sync loop iteration failed; backing off 30s before retry"
                )
                if self._stop_flag.wait(timeout=30):
                    break

        logger.debug("Sync loop stopped")

    def _perform_sync(
        self,
        only_account_ids: Optional[Iterable[int]] = None,
        claimed_account_sync_generation: Optional[int] = None,
    ) -> None:
        """Perform a single sync cycle.

        If ``only_account_ids`` is provided, only those DB accounts are synced.
        This is used by Gmail push callbacks, which already identify the mailbox
        that changed.
        """
        requested_account_ids = (
            {int(account_id) for account_id in only_account_ids}
            if only_account_ids is not None
            else None
        )
        sync_generation: Optional[int] = None
        claimed_account_ids: set[int] = set()
        claimed_full_sync = False
        with self._sync_lock:
            self._clear_stale_sync_flag_locked()
            legacy_busy = (
                self._is_syncing
                and not self._has_structured_sync_locked()
            )
            if legacy_busy:
                if requested_account_ids is not None:
                    self._pending_account_sync_ids.update(requested_account_ids)
                return

            if claimed_account_sync_generation is not None:
                if not requested_account_ids:
                    return
                claimed_account_ids = {
                    account_id
                    for account_id in requested_account_ids
                    if self._active_account_sync_generations.get(account_id)
                    == claimed_account_sync_generation
                }
                if not claimed_account_ids:
                    return
                sync_generation = claimed_account_sync_generation
                requested_account_ids = claimed_account_ids
            elif requested_account_ids is None:
                if self._has_structured_sync_locked():
                    return
                self._sync_generation += 1
                sync_generation = self._sync_generation
                claimed_full_sync = True
                self._active_full_sync_generation = sync_generation
                self._sync_started_at_monotonic = time.monotonic()
                self._refresh_syncing_flag_locked()
            else:
                reserved_account_syncs = self._reserve_account_syncs_locked(
                    requested_account_ids
                )
                if not reserved_account_syncs:
                    return
                claimed_account_ids = {
                    account_id for account_id, _ in reserved_account_syncs
                }
                sync_generation = reserved_account_syncs[0][1]
                requested_account_ids = claimed_account_ids

        start_time = time.monotonic()
        results: List[SyncResult] = []

        try:
            # Load accounts in a short-lived read session — isolated from sync writes
            try:
                with get_db_session() as session:
                    account_repo = AccountRepository(session)
                    accounts = list(account_repo.get_active_accounts())
                    if requested_account_ids is not None:
                        accounts = [
                            account
                            for account in accounts
                            if int(account.id) in requested_account_ids
                        ]
            except Exception as e:
                logger.error(f"Error loading accounts for sync: {e}", exc_info=True)
                return

            # Audit P1-A4 (2026-04-26) — TTL eviction must run even when there
            # are zero active accounts. Otherwise, deleting all accounts leaves
            # orphan backoff entries that live forever (the sync loop returns
            # early at line `if not accounts` and never reaches the inner
            # eviction at the per-account loop).
            now_pre = time.monotonic()
            try:
                with self._sync_lock:
                    stale_pre = [
                        aid for aid, entry in self._auth_backoff.items()
                        if (now_pre - entry[2]) > self._AUTH_BACKOFF_TTL
                    ]
                    for aid in stale_pre:
                        self._auth_backoff.pop(aid, None)
                if stale_pre:
                    logger.info(
                        "Evicted %d stale auth backoff entries (no-account path)",
                        len(stale_pre),
                    )
            except Exception:
                logger.debug("Auth backoff pre-eviction failed", exc_info=True)

            if not accounts:
                logger.debug("No active accounts to sync")
                return

            account_ids = [a.id for a in accounts]

            # Emit sync started event
            if self._on_sync_started:
                try:
                    self._on_sync_started(account_ids)
                except Exception as e:
                    logger.error(f"Error in on_sync_started callback: {e}")

            # Sync each account in its own isolated session.
            # This prevents one account's DB error from poisoning the session
            # used by other accounts (PendingRollbackError cross-contamination).
            now = time.monotonic()
            # Evict stale backoff entries (M-2): drop rows whose last
            # update is older than the TTL — these are typically deleted
            # accounts that would otherwise accumulate forever.
            try:
                with self._sync_lock:
                    stale = [
                        aid for aid, entry in self._auth_backoff.items()
                        if (now - entry[2]) > self._AUTH_BACKOFF_TTL
                    ]
                    for aid in stale:
                        self._auth_backoff.pop(aid, None)
                if stale:
                    logger.info(
                        "Evicted %d stale auth backoff entries", len(stale)
                    )
            except Exception:
                logger.debug("Auth backoff eviction failed", exc_info=True)
            for account in accounts:
                # Skip accounts in auth backoff
                with self._sync_lock:
                    backoff_info = self._auth_backoff.get(account.id)
                if backoff_info:
                    failures, next_retry, _ = backoff_info
                    if now < next_retry:
                        logger.debug(
                            f"Skipping {account.email} — auth backoff "
                            f"({failures} failures, retry in {int(next_retry - now)}s)"
                        )
                        results.append(SyncResult(
                            account_id=account.id,
                            account_email=account.email,
                            success=False,
                            error_message=f"Auth backoff ({failures} consecutive failures)",
                        ))
                        continue

                result = self._sync_account_isolated(account)
                results.append(result)

                # Update auth backoff tracking
                if not result.success and result.error_message and (
                    "Authentication failed" in result.error_message
                    or "Authentification IMAP" in result.error_message
                    or "Reconnexion IMAP" in result.error_message
                    or _is_reauth_required_error_message(result.error_message)
                ):
                    prev_failures = backoff_info[0] if backoff_info else 0
                    new_failures = prev_failures + 1
                    delay = min(
                        self._AUTH_BACKOFF_BASE * (2 ** (new_failures - 1)),
                        self._AUTH_BACKOFF_MAX,
                    )
                    now_mono = time.monotonic()
                    with self._sync_lock:
                        self._auth_backoff[account.id] = (
                            new_failures, now_mono + delay, now_mono
                        )
                    logger.warning(
                        f"Auth failed for {account.email} ({new_failures}x) — "
                        f"backing off {delay}s"
                    )
                    # Token révoqué (invalid_grant & co.) re-tenté au-delà du
                    # seuil → compte mort : on le désactive. La reconnexion
                    # OAuth remet is_active=True (chemins store de oauth.py).
                    if (
                        new_failures >= self._AUTH_DEACTIVATE_AFTER
                        and _is_reauth_required_error_message(result.error_message)
                    ):
                        self._deactivate_dead_account(
                            account.id, account.email, new_failures
                        )
                elif result.success:
                    # Audit P2 (mother-of-all 2026-04-25) : "recovered" est
                    # trompeur si le compte n'avait subi qu'une seule failure
                    # (souvent du noise réseau, pas une vraie panne d'auth).
                    # On log au niveau "recovery" seulement si on était en
                    # backoff substantiel (≥2 failures), sinon debug-only.
                    with self._sync_lock:
                        _prev_entry = self._auth_backoff.pop(account.id, None)
                    if _prev_entry:
                        _prev_failures = _prev_entry[0]
                        if _prev_failures >= 2:
                            logger.info(
                                f"Auth recovered for {account.email} after "
                                f"{_prev_failures} failures — backoff cleared"
                            )
                        else:
                            logger.debug(
                                f"Backoff cleared for {account.email} "
                                f"(was {_prev_failures} failure)"
                            )

                # Emit progress event
                if self._on_sync_progress:
                    try:
                        status = "success" if result.success else "error"
                        self._on_sync_progress(account.id, status)
                    except Exception as e:
                        logger.error(f"Error in on_sync_progress callback: {e}")

            # Enforce cache limits in a separate session
            try:
                with get_db_session() as session:
                    self._enforce_cache_limits(session, account_ids)
            except Exception as e:
                logger.warning(f"Cache limit enforcement failed: {e}")

        except Exception as e:
            logger.error(f"Error during sync: {e}", exc_info=True)

        finally:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self._status.last_sync_at = datetime.now(timezone.utc)
            self._status.last_results = results
            released_current_generation = False
            reserved_queued_account_syncs: list[tuple[int, int]] = []
            with self._sync_lock:
                if (
                    claimed_full_sync
                    and self._active_full_sync_generation == sync_generation
                ):
                    self._active_full_sync_generation = None
                    self._sync_started_at_monotonic = None
                    released_current_generation = True
                for account_id in claimed_account_ids:
                    if (
                        self._active_account_sync_generations.get(account_id)
                        == sync_generation
                    ):
                        self._active_account_sync_generations.pop(account_id, None)
                        self._active_account_sync_started_at.pop(account_id, None)
                        released_current_generation = True

                self._refresh_syncing_flag_locked()
                if self._active_full_sync_generation is None:
                    reserved_queued_account_syncs = self._reserve_account_syncs_locked()

            # Emit sync complete event
            if self._on_sync_complete and released_current_generation:
                try:
                    self._on_sync_complete(results, duration_ms)
                except Exception as e:
                    logger.error(f"Error in on_sync_complete callback: {e}")

            total_new = sum(r.new_emails_count for r in results)
            if released_current_generation:
                logger.info(
                    f"Sync complete: {len(results)} accounts, "
                    f"{total_new} new emails, {duration_ms}ms"
                )
            else:
                logger.warning(
                    "Stale sync reservation finished after a newer sync; "
                    "skipping completion event"
                )

            if reserved_queued_account_syncs:
                queued_account_ids = [
                    account_id for account_id, _ in reserved_queued_account_syncs
                ]
                logger.info(
                    "Starting queued account sync for %d account(s): %s",
                    len(queued_account_ids),
                    queued_account_ids,
                )
                self._start_reserved_account_syncs(reserved_queued_account_syncs)

    def _deactivate_dead_account(
        self, account_id: int, account_email: str, failures: int
    ) -> None:
        """Désactive (is_active=False) un compte dont l'auth échoue de façon
        permanente — token révoqué côté IdP, jamais récupérable par retry.

        Symétrique du flow disconnect (oauth.py MIGRATE-005) : le sync
        l'ignore ensuite via ``get_active_accounts()``, et une reconnexion
        OAuth le réactive. L'entrée de backoff est purgée pour ne pas
        polluer les logs d'éviction.
        """
        try:
            with get_db_session_with_retry() as session:
                account_repo = AccountRepository(session)
                db_acct = account_repo.get(account_id)
                if db_acct is None:
                    return
                db_acct.is_active = False
                session.commit()
            with self._sync_lock:
                self._auth_backoff.pop(account_id, None)
            logger.warning(
                f"Compte {account_email} désactivé après {failures} échecs "
                f"d'authentification permanents consécutifs (token révoqué). "
                f"Reconnecter le compte pour le réactiver."
            )
        except Exception as e:
            logger.error(
                f"Échec de désactivation du compte mort {account_email}: {e}"
            )

    def _sync_account_isolated(self, account: Account) -> SyncResult:
        """
        Sync a single account in its own isolated DB session.

        Each account gets a fresh session so that a DB error (e.g. "database is
        locked") on one account cannot leave the session in PendingRollbackError
        state and corrupt subsequent accounts' transactions.
        """
        # Audit 2026-05-11 P0: when the inner session was rolled back by a
        # PendingRollbackError, the except clause below would lazy-load
        # `account.email` on the now-expired ORM state and crash a *second*
        # time, dwarfing the original traceback. Capture both fields to
        # locals before the try so the error path is always safe to log.
        _account_id = account.id
        _account_email = account.email
        try:
            with get_db_session_with_retry() as session:
                # Audit F-06 (2026-05-16): hook the session so deferred
                # auto-reply dispatches fire only on a successful commit
                # and are cleared on rollback. Without this, the inline
                # SMTP in ``_store_emails`` could fire before the row
                # rolled back, producing duplicate OOO sends on retry.
                _register_deferred_auto_reply_hooks(session)

                account_repo = AccountRepository(session)
                fresh_account = account_repo.get(_account_id)
                if not fresh_account:
                    return SyncResult(
                        account_id=_account_id,
                        account_email=_account_email,
                        success=False,
                        error_message="Account not found in DB",
                    )
                tokens = None
                try:
                    from app.infrastructure.cost_manager import set_usage_context

                    tokens = set_usage_context(
                        account_id=fresh_account.id,
                        user_id=getattr(fresh_account, "user_id", None),
                        feature="sync",
                    )
                except Exception:
                    tokens = None
                try:
                    return self._sync_account(session, fresh_account)
                finally:
                    try:
                        from app.infrastructure.cost_manager import reset_usage_context

                        reset_usage_context(tokens)
                    except Exception:
                        pass
        except Exception as e:
            # get_db_session_with_retry() already called rollback; log as a last resort
            # Auth failures are expected (expired credentials) — warn, not error
            _is_auth_error = "Authentification IMAP" in str(e) or "Reconnexion IMAP" in str(e)
            if _is_auth_error:
                logger.warning(f"Auth sync failed for {_account_email}: {e}")
            else:
                logger.error(f"Isolated sync failed for {_account_email}: {e}", exc_info=True)
            return SyncResult(
                account_id=_account_id,
                account_email=_account_email,
                success=False,
                error_message=str(e),
            )

    def _sync_account(self, session: Session, account: Account) -> SyncResult:
        """
        Sync emails for a single account.

        Args:
            session: Database session.
            account: Account to sync.

        Returns:
            SyncResult with sync outcome.
        """
        start_time = time.monotonic()
        account_id = account.id
        account_email = account.email
        account_provider = account.provider

        adapter = None
        try:
            # `account` was loaded by SQLAlchemy just before this method, which
            # opens a DB transaction even for a plain SELECT. Provider auth/fetch
            # can take >30s on Railway; close the read transaction first so
            # Postgres does not kill it as idle-in-transaction before the write.
            _finish_sync_db_batch(session, account_email, "provider authentication")

            # Get provider adapter
            adapter = self._get_adapter_for_account(account)
            if not adapter:
                return SyncResult(
                    account_id=account_id,
                    account_email=account_email,
                    success=False,
                    error_message=f"No adapter for provider: {account_provider}"
                )

            # Authenticate (handles token refresh)
            if not adapter.authenticate():
                return SyncResult(
                    account_id=account_id,
                    account_email=account_email,
                    success=False,
                    error_message="Authentication failed"
                )

            # One-shot archive backfill BEFORE the sync branches below.
            #
            # Lives here (not inside the fallback path) because Gmail accounts
            # with a historyId checkpoint take the delta branch and return
            # early — they would never reach the fallback's archive fetch.
            # Running it up front also means new adapters that only implement
            # delta sync still get archived history populated.
            self._maybe_archive_backfill(session, adapter, account)
            _finish_sync_db_batch(session, account_email, "inbox backfill")
            self._maybe_inbox_backfill(session, adapter, account)
            _finish_sync_db_batch(session, account_email, "sent backfill")
            self._maybe_sent_backfill(session, adapter, account)
            _finish_sync_db_batch(session, account_email, "provider delta fetch")

            # Capturé AVANT le bloc delta : update_sync_time() bump last_sync_at
            # en effet de bord, donc lire account.last_sync_at après un échec
            # delta ferait fetcher le fallback depuis « maintenant » et sauterait
            # le batch perdu (audit 2026-06-11 B-01).
            fallback_since = account.last_sync_at

            # Try historyId-based delta sync first (Gmail only, much faster)
            new_history_id = None
            if account.last_history_id and hasattr(adapter, "get_history_changes"):
                try:
                    changes = adapter.get_history_changes(account.last_history_id)
                    new_history_id = changes.get("new_history_id")

                    if new_history_id is None:
                        # historyId expired (or a legacy poisoned Outlook
                        # checkpoint self-healed) — fall through to the timestamp
                        # sync, which re-initialises a fresh checkpoint via
                        # get_current_history_id at its end.
                        if changes.get("poisoned"):
                            # The id-only checkpoint already persisted blank
                            # "(No subject)" / empty-sender rows. Clear the
                            # inbox-backfill marker so the NEXT tick re-fetches up
                            # to 1000 inbox messages WITH metadata; _store_emails'
                            # existing-row heal then repairs those rows in place —
                            # no manual POST /api/sync/full required.
                            _set_account_setting(account, "inbox_backfilled_at", None)
                            logger.warning(
                                "Outlook account %s had a poisoned (id-only) delta "
                                "checkpoint — re-initialising and scheduling an "
                                "inbox backfill to heal blank rows", account.email,
                            )
                        else:
                            logger.info(f"historyId expired for {account.email}, doing full sync")
                    else:
                        emails = changes["added"]
                        new_count = self._store_emails(
                            session, account, emails,
                            auto_reply_adapter=adapter,
                        )

                        # Handle deletions from delta sync
                        deleted_ids = changes.get("deleted", [])
                        if deleted_ids:
                            email_repo = EmailRepository(session)
                            for del_id in deleted_ids:
                                try:
                                    email_repo.delete_by_email_id(
                                        str(del_id), account_id=account.id,
                                    )
                                except Exception:
                                    pass
                            logger.info(f"Delta sync: deleted {len(deleted_ids)} emails for {account.email}")

                        # Handle label changes from delta sync
                        label_changes = changes.get("label_changes", [])
                        if label_changes:
                            email_repo = EmailRepository(session)
                            for lc in label_changes:
                                msg_id = lc.get("message_id") or lc.get("id")
                                added_labels = set(lc.get("added") or [])
                                removed_labels = set(lc.get("removed") or [])
                                if not msg_id:
                                    continue
                                if "UNREAD" in added_labels:
                                    email_repo.bulk_update_read_status(
                                        [str(msg_id)], False, account_id=account.id,
                                    )
                                elif "UNREAD" in removed_labels:
                                    email_repo.bulk_update_read_status(
                                        [str(msg_id)], True, account_id=account.id,
                                    )
                                # Check for TRASH/SPAM label additions → move to that folder
                                if "TRASH" in added_labels:
                                    email_repo.update_folder_by_email_id(
                                        str(msg_id), "trash", account_id=account.id,
                                    )
                                elif "SPAM" in added_labels:
                                    email_repo.update_folder_by_email_id(
                                        str(msg_id), "spam", account_id=account.id,
                                    )
                                elif "TRASH" in removed_labels or "SPAM" in removed_labels:
                                    email_repo.update_folder_by_email_id(
                                        str(msg_id), "inbox", account_id=account.id,
                                    )
                            logger.info(f"Delta sync: processed {len(label_changes)} label changes for {account.email}")

                        # Belt-and-braces SENT pull on every delta tick.
                        #
                        # Gmail's history API does NOT reliably surface every
                        # SENT label addition: messages sent from Gmail Web /
                        # mobile that round-trip through SMTP-side relays can
                        # land in the user's Sent folder without producing a
                        # `messageAdded` history event the delta picks up. The
                        # symptom is `Contact.sent_count = 0` for real recipients
                        # the user replied to outside Agentys → bidirectional
                        # filter hides them in Settings → Per-Contact (lessons.md
                        # 2026-05-04 entry).
                        #
                        # Pull a small SENT sample periodically, not on every
                        # 2-minute tick: Gmail rate-limits message metadata
                        # batches quickly when several accounts sync together.
                        # `_store_emails` dedups via `get_by_email_id` so any
                        # overlap with `changes["added"]` is a no-op.
                        _finish_sync_db_batch(session, account_email, "delta SENT pull")
                        try:
                            sent_count = self._delta_pull_sent(session, account, adapter)
                            new_count += sent_count
                        except Exception as e:
                            logger.warning(
                                f"Delta SENT pull failed for {account.email}: {e}"
                            )
                            # Un échec DB ici (ex. « database is locked » pendant
                            # que le bulk-worker écrit) laisse la session en
                            # PendingRollbackError ; sans rollback, le
                            # update_sync_time juste après crashe avec « This
                            # Session's transaction has been rolled back » qui
                            # MASQUE l'erreur d'origine (audit 2026-06-09).
                            try:
                                session.rollback()
                            except Exception:
                                pass

                        account_repo = AccountRepository(session)
                        account_repo.update_sync_time(account.id, history_id=new_history_id)
                        _finish_sync_db_batch(session, account_email, "provider disconnect")

                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        return SyncResult(
                            account_id=account_id,
                            account_email=account_email,
                            success=True,
                            new_emails_count=new_count,
                            duration_ms=duration_ms
                        )
                except Exception as e:
                    logger.warning(f"History sync failed for {account.email}: {e}, falling back to timestamp")
                    # CRITICAL: rollback to clear any PendingRollbackError state before fallback
                    try:
                        session.rollback()
                    except Exception as rb_err:
                        logger.error(f"Rollback failed for {account.email}: {rb_err}")
                    # Audit 2026-06-11 B-01 (annule P0-A1) : on ne persiste PLUS
                    # le history_id ici. update_sync_time() bump last_sync_at en
                    # effet de bord → le fallback timestamp lisait « maintenant »
                    # et ne re-fetchait jamais le batch fetché-mais-non-stocké ;
                    # et si le fallback échouait aussi, le checkpoint avancé
                    # sautait définitivement ces emails. Le fallback ci-dessous
                    # persiste de toute façon un history_id frais à sa fin
                    # (get_current_history_id) une fois le store réussi — le
                    # surcoût quota ne dure que tant que les échecs persistent.

            # Fallback: timestamp-based sync.
            # IMPORTANT: fetch ALL data from network BEFORE any DB write.
            # session.flush() inside _store_emails() starts a SQLite write transaction;
            # holding that lock during slow IMAP calls causes "database is locked" for
            # concurrent writers (auto-label, background sync, etc.).
            since = fallback_since
            emails = self._fetch_emails_with_retry(adapter, since)

            # Pre-fetch sent emails while no write transaction is open yet
            sent_emails_data: list = []
            if hasattr(adapter, "get_sent_emails"):
                if _skip_low_priority_provider_fetch(adapter, account.email, "timestamp_sent"):
                    sent_emails_data = []
                else:
                    try:
                        sent_limit = 200 if since is None else 50
                        # Brief cooldown after large initial fetch to avoid rate-limiting
                        if since is None and emails:
                            time.sleep(2.0)
                        # Pass `since` so adapters that support it do a proper delta
                        # instead of always fetching the N most recent sent emails.
                        try:
                            sent_emails_data = adapter.get_sent_emails(limit=sent_limit, since=since)
                        except TypeError:
                            sent_emails_data = adapter.get_sent_emails(limit=sent_limit)
                    except Exception as e:
                        logger.warning(f"Failed to fetch sent emails for {account.email}: {e}")

            # Pre-fetch historyId while no write transaction is open yet
            if hasattr(adapter, "get_current_history_id"):
                new_history_id = adapter.get_current_history_id()

            # All network I/O done — now write in a short burst (minimises lock window)
            # Pass adapter so live-delta inbox inserts fire the OOO auto-reply.
            # `since` is None only on the very first sync (initial backfill),
            # in which case we MUST NOT auto-reply to historical mail.
            new_count = self._store_emails(
                session, account, emails,
                auto_reply_adapter=adapter if since is not None else None,
            )

            sent_count = 0
            if sent_emails_data:
                sent_count = self._store_emails(session, account, sent_emails_data, is_sent=True)
                if sent_count > 0:
                    logger.info(f"Synced {sent_count} new sent emails for {account.email}")

            new_count += sent_count

            # Update last sync time + historyId checkpoint
            account_repo = AccountRepository(session)
            account_repo.update_sync_time(account.id, history_id=new_history_id)
            _finish_sync_db_batch(session, account_email, "provider disconnect")

            duration_ms = int((time.monotonic() - start_time) * 1000)

            return SyncResult(
                account_id=account_id,
                account_email=account_email,
                success=True,
                new_emails_count=new_count,
                duration_ms=duration_ms
            )

        except Exception as e:
            auth_expired = _is_auth_expired_error(e)
            if auth_expired:
                logger.warning(
                    "Sync skipped for %s: account needs reauth (%s)",
                    account_email,
                    e,
                )
            else:
                logger.error(f"Error syncing account {account_email}: {e}", exc_info=True)

            # Rollback to clear PendingRollbackError state (e.g. from "database is locked")
            try:
                session.rollback()
            except Exception:
                pass

            # Emit error event
            if self._on_sync_error and not auth_expired:
                try:
                    self._on_sync_error(account_id, str(e))
                except Exception as callback_error:
                    logger.error(f"Error in on_sync_error callback: {callback_error}")

            duration_ms = int((time.monotonic() - start_time) * 1000)

            return SyncResult(
                account_id=account_id,
                account_email=account_email,
                success=False,
                error_message=str(e),
                duration_ms=duration_ms
            )
        finally:
            if adapter and hasattr(adapter, 'disconnect'):
                try:
                    adapter.disconnect()
                except Exception:
                    pass

    # Une création d'adapter qui échoue sur de la CONFIG (ex. imap_smtp sans
    # IMAP_HOST/USER/PASSWORD) est permanente jusqu'à changement d'env —
    # re-tenter à chaque cycle de sync spammait un warning toutes les ~2 min
    # (669 occurrences, audit 2026-06-09). On mémorise l'échec et on ne
    # retente qu'après ce délai.
    _ADAPTER_FAILURE_RETRY_S = 1800  # 30 min

    def _get_adapter_for_account(self, account: Account):
        """
        Get the appropriate email adapter for an account.

        Args:
            account: Account to get adapter for.

        Returns:
            Email provider adapter or None.
        """
        from app.providers.factory import get_email_provider
        import hashlib

        memo: dict = getattr(self, "_adapter_failure_memo", None) or {}
        self._adapter_failure_memo = memo
        last_failure = memo.get(account.id)
        if (
            last_failure is not None
            and (time.monotonic() - last_failure) < self._ADAPTER_FAILURE_RETRY_S
        ):
            return None

        try:
            # Compute the OAuth hash ID (same as oauth.py callback)
            # so the GmailAdapter can load server-side tokens
            oauth_account_id = hashlib.sha256(
                f"{account.provider}:{account.email}".encode()
            ).hexdigest()[:16]

            adapter = get_email_provider(
                provider_type=account.provider,
                account_id=oauth_account_id,
                refresh_token=account.refresh_token,
            )
            memo.pop(account.id, None)
            return adapter
        except Exception as e:
            memo[account.id] = time.monotonic()
            logger.warning(
                f"Failed to create adapter for {account.provider}: {e} — "
                f"prochain essai dans {self._ADAPTER_FAILURE_RETRY_S // 60} min"
            )
            return None

    @with_retry(
        max_attempts=3,
        base_delay=1.0,
        exponential_base=2.0,
        # Only retry on transient network/IO errors.
        # RuntimeError = auth failure (wrong credentials, server rejection) — not retryable.
        # Retrying on RuntimeError causes 9 useless auth attempts and misleading logs.
        exceptions=(OSError, TimeoutError, ConnectionError),
    )
    def _fetch_emails_with_retry(self, adapter, since: Optional[datetime]) -> List:
        """
        Fetch emails from provider with one re-auth retry on 401-class errors.

        Args:
            adapter: Email provider adapter.
            since: Fetch emails since this timestamp (None for initial sync).

        Returns:
            List of StandardEmail objects.

        Audit P0-A2 : avant ce wrapper, ``adapter.authenticate()`` n'était
        appelé qu'une fois en début de sync. Si le token expirait au milieu
        de la pagination (typique sur les comptes peu utilisés où le sync
        prend > 1h pour épuiser le retard), les requêtes Gmail/Graph
        retournaient 401 et la fetch loop renvoyait une liste vide sans
        alerter. Le sync rapportait succès partiel et les emails étaient
        manqués jusqu'au prochain tick.

        Stratégie : tenter le fetch, si on attrape un signal "auth expired"
        (HttpError 401, RuntimeError d'``_ensure_authenticated``, ou un
        ``UnauthorizedError`` générique côté Outlook) on rappelle
        ``adapter.authenticate()`` puis on re-essaie une fois. Tout autre
        échec est laissé propager au sync loop pour entrer en backoff.
        """
        def _do_fetch() -> List:
            if since:
                if hasattr(adapter, "fetch_messages_since"):
                    return adapter.fetch_messages_since(since, limit=200)
                logger.warning(
                    f"Adapter {adapter.provider_name} doesn't support delta sync, "
                    "falling back to recent messages"
                )
                return adapter.get_messages(limit=200)
            from app.config import DEFAULT_CACHE_CONFIG
            initial_limit = DEFAULT_CACHE_CONFIG.initial_sync_limit
            logger.info(f"Initial sync: fetching {initial_limit} emails (read + unread)")
            return adapter.get_messages(limit=initial_limit)

        try:
            return _do_fetch()
        except Exception as e:
            if not _is_auth_expired_error(e):
                raise
            logger.warning(
                f"Auth-expired-style error mid-fetch for {getattr(adapter, 'provider_name', '?')}: "
                f"{e!r}. Re-authenticating once and retrying."
            )
            try:
                # `authenticate()` est idempotent — il refait un refresh propre
                # via le file lock partagé (gmail) ou un fresh credential build
                # (outlook). Si le refresh échoue, on lève → entrée en backoff.
                if not adapter.authenticate():
                    raise RuntimeError(
                        f"Re-auth returned False for {getattr(adapter, 'provider_name', '?')}"
                    )
            except Exception as reauth_err:
                if _is_auth_expired_error(reauth_err):
                    logger.warning(
                        f"Re-auth failed because account needs reauth for "
                        f"{getattr(adapter, 'provider_name', '?')}: {reauth_err!r}"
                    )
                else:
                    logger.error(
                        f"Re-auth failed for {getattr(adapter, 'provider_name', '?')}: {reauth_err!r}"
                    )
                raise
            # Une seule re-tentative — si elle re-fail le sync entrera en backoff via
            # son propre handler. Pas de boucle de retry pour éviter de spammer
            # le provider quand le token est définitivement révoqué.
            return _do_fetch()

    def _maybe_archive_backfill(
        self, session: Session, adapter, account: Account
    ) -> int:
        """One-shot archive fetch per account, gated by a persistent marker.

        Archived threads (not in Inbox/Sent/Spam/Trash) are invisible to the
        default INBOX-only fetch. Any bidirectional conversation the user
        has tidied away — often their most engaged correspondence — never
        enters the Email table without this step, starving both the
        bidirectional contacts list and the onboarding agents.

        Idempotent: stamps Account.settings_json.archive_backfilled_at on
        success (even 0 messages). Failed fetches leave the marker unset so
        the next sync tick retries. Providers without get_archived_messages
        (IMAP/SMTP) silently skip.

        Returns the number of archived rows actually inserted.
        """
        if _get_account_setting(account, "archive_backfilled_at") is not None:
            return 0
        if not hasattr(adapter, "get_archived_messages"):
            return 0

        try:
            # 200 is a deliberately modest initial cap:
            # - Rich enough to cover a typical user's bidirectional archive
            #   (most people have ≤ 20 real bidirectional contacts × ≤ 10
            #   archived messages each).
            # - Small enough to avoid piling Gmail/Graph 429s on top of the
            #   inbox + sent fetches that run in the same sync tick.
            # - One-shot: the marker persists, so future syncs skip this.
            #   Clear Account.settings_json['archive_backfilled_at'] to
            #   re-run with a larger limit if a specific user needs deeper
            #   archive history.
            # Brief cooldown so the archive fetch doesn't land inside the
            # inbox-fetch rate-limit window.
            time.sleep(1.5)
            archived = adapter.get_archived_messages(limit=200)
        except Exception as e:
            logger.warning(f"Archive backfill fetch failed for {account.email}: {e}")
            return 0

        stored = 0
        if archived:
            try:
                stored = self._store_emails(
                    session, account, archived,
                    is_sent=False, folder_override="archived",
                )
            except Exception as e:
                logger.warning(f"Archive backfill store failed for {account.email}: {e}")
                # Leave the marker unset so a future sync retries.
                return 0

        logger.info(
            f"Archive backfill: fetched {len(archived)} / stored {stored} new "
            f"archived rows for {account.email}"
        )
        _set_account_setting(
            account, "archive_backfilled_at", datetime.utcnow().isoformat()
        )
        # The outer sync will commit; flush so the marker is visible to the
        # next branch's own flush without lock contention.
        session.flush()
        return stored

    def _maybe_inbox_backfill(
        self, session: Session, adapter, account: Account
    ) -> int:
        """One-shot deep Inbox fetch per account — counterpart of archive backfill.

        Delta sync (Gmail historyId, Outlook receivedDateTime>since) only
        returns events *after* the checkpoint. Any email received before
        the user installed Agentys — still sitting in their Inbox,
        un-archived — never lands in the Email table. Senders whose only
        incoming message predates install therefore stay received_count=0
        and disappear from the bidirectional contacts list, even when the
        user has clearly been corresponding with them.

        Idempotent: marker Account.settings_json.inbox_backfilled_at. Clear
        the marker to re-run with a different cap. Providers without
        get_inbox_backfill (IMAP/SMTP) silently skip.
        """
        if _get_account_setting(account, "inbox_backfilled_at") is not None:
            return 0
        if not hasattr(adapter, "get_inbox_backfill"):
            return 0

        try:
            # 1000 cap: covers a year of inbox for a moderately active user,
            # matches Gmail's per-page max via our pagination, and stays
            # under the rate-limit ceiling when stacked with archive backfill
            # in the same tick. Cooldown matches _maybe_archive_backfill.
            time.sleep(1.5)
            inbox_msgs = adapter.get_inbox_backfill(limit=1000)
        except Exception as e:
            logger.warning(f"Inbox backfill fetch failed for {account.email}: {e}")
            return 0

        stored = 0
        if inbox_msgs:
            try:
                stored = self._store_emails(
                    session, account, inbox_msgs,
                    is_sent=False, folder_override="inbox",
                )
            except Exception as e:
                logger.warning(f"Inbox backfill store failed for {account.email}: {e}")
                return 0

        logger.info(
            f"Inbox backfill: fetched {len(inbox_msgs)} / stored {stored} new "
            f"inbox rows for {account.email}"
        )
        _set_account_setting(
            account, "inbox_backfilled_at", datetime.utcnow().isoformat()
        )
        session.flush()
        return stored

    def _maybe_sent_backfill(
        self, session: Session, adapter, account: Account
    ) -> int:
        """One-shot deep Sent fetch per account — counterpart of inbox backfill.

        Symmetric to :meth:`_maybe_inbox_backfill` for the SENT folder. Without
        this step, every email the user sent through Gmail Web / mobile / IMAP
        BEFORE installing Agentys is invisible to the local Email table — the
        delta sync only fires after install — and ``Contact.sent_count`` for
        every prior recipient stays at 0. The bidirectional filter then hides
        these contacts from Settings → Per-Contact, even when the relationship
        is plainly real (cf. ``aubert@creation.example`` regression
        documented in lessons.md, 2026-05-04).

        Idempotent: marker ``Account.settings_json.sent_backfilled_at``. Clear
        the marker to re-run. Providers without ``get_sent_backfill`` (IMAP /
        Outlook today) silently skip — the timestamp-fallback branch's
        ``get_sent_emails(limit=200)`` already covers them on the first sync.
        """
        if _get_account_setting(account, "sent_backfilled_at") is not None:
            return 0
        if not hasattr(adapter, "get_sent_backfill"):
            return 0
        if _skip_low_priority_provider_fetch(adapter, account.email, "sent_backfill"):
            return 0

        try:
            # Same 1000-cap and cooldown as inbox backfill — the two run on
            # the same tick for fresh accounts and we want them to share the
            # rate-limit budget rather than stepping on each other.
            time.sleep(1.5)
            sent_msgs = adapter.get_sent_backfill(limit=1000)
        except Exception as e:
            logger.warning(f"Sent backfill fetch failed for {account.email}: {e}")
            return 0

        quota_retry_after = _provider_low_priority_retry_after_seconds(adapter)
        stored = 0
        if sent_msgs:
            try:
                stored = self._store_emails(
                    session, account, sent_msgs,
                    is_sent=True, folder_override="sent",
                )
            except Exception as e:
                logger.warning(f"Sent backfill store failed for {account.email}: {e}")
                # Leave the marker unset so a future sync retries — same
                # contract as archive/inbox backfills.
                return 0

        logger.info(
            f"Sent backfill: fetched {len(sent_msgs)} / stored {stored} new "
            f"sent rows for {account.email}"
        )
        if quota_retry_after > 0:
            logger.warning(
                "Sent backfill not marked complete for %s: provider quota "
                "backoff retry_after=%ss",
                account.email,
                quota_retry_after,
            )
            session.flush()
            return stored

        _set_account_setting(
            account, "sent_backfilled_at", datetime.utcnow().isoformat()
        )
        session.flush()
        return stored

    def _delta_pull_sent(
        self, session: Session, account: Account, adapter
    ) -> int:
        """Pull the most recent SENT messages alongside the delta sync.

        Gmail's history API misses some SENT label additions (notably for
        messages sent through Gmail Web / mobile that flow through SMTP
        relays). This method explicitly fetches a small recent SENT sample
        every few sync ticks so the local Email table converges with the
        user's actual outgoing mail without hammering Gmail metadata quotas.

        ``_store_emails`` dedups via ``EmailRepository.get_by_email_id``, so
        overlap with ``changes["added"]`` is harmless. Failures are logged
        and swallowed by the caller — this is opportunistic backfill, not a
        critical path.
        """
        if not hasattr(adapter, "get_sent_emails"):
            return 0
        if _skip_low_priority_provider_fetch(adapter, account.email, "delta_sent"):
            return 0

        last_checked = _get_account_setting(account, "sent_delta_pulled_at")
        if last_checked:
            try:
                last_dt = datetime.fromisoformat(last_checked)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - last_dt < SENT_DELTA_PULL_INTERVAL:
                    logger.debug(
                        "Delta SENT pull skipped for %s; last check was recent",
                        account.email,
                    )
                    return 0
            except (TypeError, ValueError):
                pass

        sent_msgs = adapter.get_sent_emails(limit=SENT_DELTA_PULL_LIMIT)
        quota_retry_after = _provider_low_priority_retry_after_seconds(adapter)
        if quota_retry_after <= 0:
            _set_account_setting(
                account,
                "sent_delta_pulled_at",
                datetime.now(timezone.utc).isoformat(),
            )
        else:
            logger.warning(
                "Delta SENT pull not marked fresh for %s: provider quota "
                "backoff retry_after=%ss",
                account.email,
                quota_retry_after,
            )
        if not sent_msgs:
            return 0
        return self._store_emails(
            session, account, sent_msgs,
            is_sent=True, folder_override="sent",
        )

    @staticmethod
    def _extract_email_address(raw: Optional[str]) -> str:
        """Extract bare ``addr@host`` from a sender header that may be
        ``"Name <addr@host>"``. Used by the is_sent guard so display-name
        formatting can't trick the sender-vs-account comparison.
        """
        if not raw:
            return ""
        s = str(raw).strip().lower()
        if "<" in s and ">" in s:
            s = s.split("<", 1)[1].split(">", 1)[0].strip()
        return s

    def _store_emails(
        self, session: Session, account: Account, emails: List,
        is_sent: bool = False,
        folder_override: Optional[str] = None,
        auto_reply_adapter=None,
    ) -> int:
        """
        Store fetched emails in the database.

        Args:
            session: Database session.
            account: Account the emails belong to.
            emails: List of StandardEmail objects.
            is_sent: If True, mark all emails as sent — but only when the
                email's sender actually matches the account's address. Mismatches
                are downgraded to received (see sender-vs-account guard below).
            auto_reply_adapter: Authenticated provider adapter used to
                dispatch the OOO auto-reply on each newly inserted inbox
                email. Pass it ONLY for live delta syncs — backfills bring
                in historical mail and must not flood old senders with
                belated OOO replies. When None, no auto-reply fires from
                this method. GH#622: without this hook Gmail OAuth users
                never received an auto-reply because the legacy
                ``daemon.process_email`` path is no longer used for them.

        Returns:
            Number of new emails stored.
        """
        if not emails:
            return 0

        email_repo = EmailRepository(session)
        contact_repo = ContactRepository(session)
        new_count = 0

        account_addr = (account.email or "").strip().lower()
        persist_content = should_persist_email_content()

        for std_email in emails:
            # Sender-vs-account guard (2026-05-05, Carol/Rachel report).
            #
            # When the caller forces ``is_sent=True`` (``_delta_pull_sent``,
            # ``_maybe_sent_backfill``, fallback `get_sent_emails` pull, or
            # the routes_emails sent-folder cache write) we still verify that
            # the email's actual sender matches the account's own address.
            # The provider folder/label is a hint, the From: header is the
            # contract. Mismatches are downgraded to received so they land in
            # the inbox view where the user actually expects to find them.
            #
            # Why this matters: provider SENT-bucket queries can leak received
            # messages in practice — Gmail label propagation via SMTP relays /
            # mailing lists / BCC-self rules; IMAP server-side rules that
            # copy replies into the Sent folder; Outlook shared-mailbox or
            # delegate-store quirks. Without this guard, Rachel's reply ends
            # up with is_sent=True and disappears from Carol's inbox (the
            # exact symptom that prompted this fix).
            sender_addr = self._extract_email_address(getattr(std_email, "sender", ""))
            effective_is_sent = is_sent
            effective_folder_override = folder_override
            if is_sent and account_addr and sender_addr and sender_addr != account_addr:
                logger.warning(
                    "Provider returned email %s as SENT but sender %s != account %s. "
                    "Storing as received to avoid hiding it from the inbox view.",
                    getattr(std_email, "id", "?"), sender_addr, account_addr,
                )
                effective_is_sent = False
                # Force inbox folder regardless of folder_override='sent' — the
                # row must appear in the inbox query.
                effective_folder_override = "inbox"

            # Check if email already exists
            existing = email_repo.get_by_email_id(std_email.id, account_id=account.id)
            if existing:
                # Update body if it was stored as headers-only (body_text/body_html are NULL)
                if persist_content and not existing.body_text and not existing.body_html:
                    if std_email.body or std_email.body_html:
                        existing.body_text = std_email.body
                        existing.body_html = std_email.body_html
                        if not existing.snippet and std_email.preview:
                            existing.snippet = std_email.preview
                        # Re-run the deadline extractor now that the body
                        # finally landed — the initial headers-only insert
                        # saw an empty body and stamped deadline_at=NULL,
                        # so any rule keyed on `has_deadline_detected` would
                        # silently never match. Only updates when we don't
                        # already have a deadline, to avoid clobbering a
                        # subsequent re-classification.
                        if not existing.is_sent and existing.deadline_at is None:
                            try:
                                from app.quicksteps.deadline_extractor import extract_deadline
                                _dl = extract_deadline(
                                    body=std_email.body or "",
                                    subject=std_email.subject or existing.subject or "",
                                    account_id=getattr(account, "id", None),
                                )
                                if _dl is not None:
                                    existing.deadline_at = _dl.replace(tzinfo=None)
                            except Exception as _dl_err:  # noqa: BLE001
                                logger.debug(
                                    "deadline backfill on body-update failed for %s: %s",
                                    std_email.id, _dl_err,
                                )
                # Heal rows stored blank by the legacy poisoned Outlook delta
                # checkpoint (2026-06-23). An id-only delta inserted the row with
                # BOTH subject and sender empty — and, because the payload also
                # lacked receivedDateTime / conversationId / isRead, it stamped a
                # bogus sync-time `date`, a NULL thread_id and is_read=False. When
                # a richer fetch (the post-poison inbox backfill, or
                # POST /api/sync/full) later re-encounters the same email_id WITH
                # metadata, restore the human-visible headers AND those structural
                # fields so the row renders, sorts and threads correctly.
                #
                # Keyed on the row being genuinely blank (subject AND sender both
                # empty) so a normal delta re-pass of a healthy row is never
                # touched, and only applied when the fresh copy actually carries
                # data — an id-only delta can therefore never wipe a good row.
                _row_was_blank = (
                    not (existing.subject or "").strip()
                    and not (existing.sender or "").strip()
                )
                if _row_was_blank and (std_email.subject or std_email.sender):
                    if std_email.subject:
                        existing.subject = std_email.subject
                    if std_email.sender:
                        existing.sender = std_email.sender
                        if std_email.sender_name:
                            existing.sender_name = std_email.sender_name
                    if std_email.to:
                        existing.recipients = ",".join(std_email.to)
                    if std_email.cc:
                        existing.cc = ",".join(std_email.cc)
                    # Restore the real received time (the blank insert stamped the
                    # sync time, clustering every healed row at connect-time) and
                    # the threading id; reconcile read-state to the provider truth.
                    if std_email.received_at:
                        existing.date = std_email.received_at
                    if std_email.conversation_id and not (existing.thread_id or "").strip():
                        existing.thread_id = std_email.conversation_id
                    existing.is_read = std_email.is_read
                # Backfill raw_headers when the row was stored before the
                # column existed (NULL) and the freshly-fetched StandardEmail
                # carries classification headers from the provider. This lets
                # silent re-syncs hydrate the labelizer's bulk-detection
                # signals without needing the dedicated backfill endpoint.
                if not existing.raw_headers:
                    _hydrated = _serialize_classification_headers(std_email)
                    if _hydrated:
                        existing.raw_headers = _hydrated
                # Audit P0-A3 (mother-of-all 2026-04-25): on ne re-bump PAS le
                # contact ici. Le bump a eu lieu lors de l'insert initial.
                # Le re-bumper introduirait du double-count à chaque tick de
                # delta sync (les delta peuvent inclure des emails déjà connus
                # dont le label/folder a changé). L'edge case « insert OK mais
                # bump KO sur sync précédent » → la fonction _ensure_contact_for_email
                # ci-dessous (call defensif) garantit l'EXISTENCE du contact,
                # même sans re-bumper le compteur.
                self._ensure_contact_for_email(contact_repo, std_email, account, effective_is_sent)
                continue

            # Create new email record
            _att_meta = None
            if getattr(std_email, 'attachments', None):
                import json as _json_sync
                _att_meta = _json_sync.dumps(std_email.attachments)
            elif getattr(std_email, 'has_attachments', False):
                _att_meta = '[{"has":true}]'
            # RFC bulk-classification headers (List-Unsubscribe, Precedence,
            # Auto-Submitted, X-Mailer, Reply-To) extracted by the provider
            # adapter. Persisted as JSON so the labelizer's RFC noise rules
            # actually fire — without this the headers were lost on save.
            _raw_headers_str = _serialize_classification_headers(std_email)
            # Auto-extract a deadline from the body for received emails (regex
            # over "due / by / expires / payment due / RSVP by / date limite /
            # échéance / avant le …"). Cheap, no-LLM; surfaces as a clock chip
            # on the inbox row and feeds the `has_deadline_detected` Quick Step
            # trigger condition. Skipped for outbound (we don't deadline-tag
            # the user's own sent mail).
            _deadline_naive = None
            if not effective_is_sent:
                try:
                    from app.quicksteps.deadline_extractor import extract_deadline
                    _dl = extract_deadline(
                        body=std_email.body or "",
                        subject=std_email.subject or "",
                        account_id=getattr(account, "id", None),
                    )
                    if _dl is not None:
                        _deadline_naive = _dl.replace(tzinfo=None)
                except Exception as _dl_err:  # noqa: BLE001
                    logger.debug("deadline extract failed for %s: %s", std_email.id, _dl_err)

            email = Email(
                email_id=std_email.id,
                account_id=account.id,
                thread_id=std_email.conversation_id,
                subject=std_email.subject,
                sender=std_email.sender,
                sender_name=std_email.sender_name,
                recipients=",".join(std_email.to) if std_email.to else None,
                cc=",".join(std_email.cc) if std_email.cc else None,
                date=std_email.received_at or datetime.now(timezone.utc),
                body_text=std_email.body if persist_content else None,
                body_html=std_email.body_html if persist_content else None,
                snippet=std_email.preview if persist_content else None,
                is_read=std_email.is_read,
                is_sent=effective_is_sent,
                attachments_meta=_att_meta,
                raw_headers=_raw_headers_str,
                deadline_at=_deadline_naive,
                # Fix #77: tag inbox emails explicitly so spam emails moved by Outlook
                # after sync don't linger in the inbox (folder=NULL was treated as inbox).
                # folder_override lets callers tag archive-backfill rows (`'archived'`)
                # so get_by_account can opt them into the onboarding corpus without
                # polluting the inbox view.
                folder=effective_folder_override if effective_folder_override is not None else (None if effective_is_sent else "inbox"),
            )

            # Audit FI-002 (2026-04-27): wrap each insert in a SAVEPOINT so a
            # UNIQUE collision rolls back only this row, not the whole batch.
            # Previous `session.rollback()` discarded every prior insert +
            # contact bump in the current transaction → silent data loss
            # whenever any one of the N emails in the batch raced.
            try:
                with session.begin_nested():
                    session.add(email)
                    session.flush()
                new_count += 1
            except Exception as _insert_err:
                logger.info(
                    f"UNIQUE collision sync for email {std_email.id} on account "
                    f"{account.id}: another thread/process won the insert race "
                    f"({_insert_err.__class__.__name__})"
                )
                self._ensure_contact_for_email(contact_repo, std_email, account, effective_is_sent)
                continue

            # 2026-05-05 — invalidate the in-memory ContactSummary cache for the
            # sender so the next draft picks up a fresh summary instead of
            # serving the stale cached one. The DB-level staleness check
            # (summary_last_message_id) already catches this on the slow path,
            # but the in-memory cache has a 15-min TTL — without explicit
            # invalidation, a draft generated within 15 min of a new email
            # would use the pre-arrival summary. Sent emails (is_sent=True)
            # are skipped — the user is the sender and the cache is keyed by
            # the contact, not the user.
            if not effective_is_sent and std_email.sender:
                try:
                    from app.services.contact_summary_service import invalidate_contact_summary
                    invalidate_contact_summary(account.id, std_email.sender)
                except Exception as _inv_err:  # pragma: no cover — defensive only
                    logger.debug(f"contact_summary cache invalidation skipped: {_inv_err}")

            # Update contact information (get_or_create handles UNIQUE races internally)
            #
            # Direction matters: on a received email the "other party" is the sender
            # (bump received_count). On a sent email the "other party" is each
            # recipient in To + CC — the sender field is the user's own address,
            # which must never become a contact. Processing sent-folder recipients
            # here is what makes the bidirectional contacts list work regardless
            # of whether the user hit Send in Agentys, Gmail, Outlook, or IMAP:
            # every channel ends up in the Sent folder and flows through sync.
            #
            # Use ``effective_is_sent`` (post-guard) so a downgraded received
            # email registers its actual sender as a contact and bumps
            # received_count rather than the user's own recipients/sent_count.
            if effective_is_sent:
                user_email = (account.email or "").strip().lower()
                seen: set[str] = set()
                raw_recipients = list(std_email.to or []) + list(std_email.cc or [])
                for raw in raw_recipients:
                    if not raw:
                        continue
                    addr = str(raw).strip().lower()
                    if "<" in addr and ">" in addr:
                        addr = addr.split("<", 1)[1].split(">", 1)[0].strip()
                    if not addr or "@" not in addr or addr == user_email or addr in seen:
                        continue
                    seen.add(addr)
                    try:
                        contact, _ = contact_repo.get_or_create(
                            email=addr,
                            account_id=account.id,
                        )
                        contact_repo.increment_email_count(
                            contact_id=contact.id,
                            is_sent=True,
                        )
                    except Exception as e:
                        logger.debug(f"Failed to update sent contact for {addr}: {e}")
            elif std_email.sender:
                try:
                    contact, _ = contact_repo.get_or_create(
                        email=std_email.sender,
                        account_id=account.id,
                        name=std_email.sender_name,
                    )
                    contact_repo.increment_email_count(
                        contact_id=contact.id,
                        is_sent=False,
                    )
                except Exception as e:
                    logger.warning(f"Failed to update contact for {std_email.sender}: {e}")

            # Emit new email event (skip sent emails — not relevant for inbox refresh).
            # Use effective_is_sent so a downgraded received email DOES fire the
            # callback and the inbox view actually refreshes for it.
            if self._on_new_email and not effective_is_sent:
                try:
                    _received_at = getattr(std_email, "received_at", None)
                    self._on_new_email({
                        "email_id": std_email.id,
                        "account_id": account.id,
                        "sender": std_email.sender,
                        "sender_name": std_email.sender_name,
                        "subject": std_email.subject,
                        "received_at": (
                            _received_at.isoformat()
                            if hasattr(_received_at, "isoformat")
                            else str(_received_at or "")
                        ),
                        "is_read": std_email.is_read,
                        "has_attachments": std_email.has_attachments,
                        "conversation_id": std_email.conversation_id,
                        "body_preview": std_email.preview if persist_content else "",
                        "snippet": std_email.preview if persist_content else "",
                    })
                except Exception as e:
                    logger.error(f"Error in on_new_email callback: {e}")

            # GH#622 — fire out-of-office auto-reply on newly stored inbox
            # emails. Only when the caller passed an adapter AND this row
            # is genuinely received (not a downgraded-from-sent edge case).
            # Detect auto-reply on the incoming body so we don't loop with
            # other OOO bots. Wrapped so a provider hiccup never aborts the
            # sync.
            #
            # Audit F-06 (2026-05-16): the prior implementation dispatched
            # the SMTP send inline, INSIDE the open SQL transaction. On any
            # rollback later in the batch (e.g. "database is locked" on a
            # subsequent row), the email row was discarded but the SMTP
            # had already left the building. Combined with a Railway
            # redeploy clearing the in-memory ``_REPLIED_SENDERS`` dedupe
            # set, the next sync re-saw the same email as new and fired
            # a second OOO send — duplicate recipient-visible mails. Fix:
            # stash the dispatch on ``session.info`` and execute via the
            # ``after_commit`` listener registered in ``_sync_account_isolated``
            # so the SMTP fires only after the row is durably committed.
            if auto_reply_adapter is not None and not effective_is_sent:
                try:
                    from app.utils.email_cleaner import detect_auto_reply

                    own_emails = None
                    try:
                        acct_repo = AccountRepository(session)
                        own = acct_repo.get_active_accounts()
                        own_emails = {a.email for a in own if a.email}
                    except Exception:
                        own_emails = {account.email} if account.email else None

                    is_auto = detect_auto_reply(
                        getattr(std_email, "body", "") or "",
                        getattr(std_email, "subject", "") or "",
                    )
                    # Capture primitives so the deferred dispatch doesn't
                    # touch session-bound ORM state post-commit.
                    _acc_id = account.id
                    _acc_email = account.email
                    _eml = std_email
                    _ar_adapter = auto_reply_adapter
                    _is_auto = is_auto
                    _own = own_emails

                    def _deferred_dispatch(
                        _ar=_ar_adapter, _aid=_acc_id, _e=_eml, _ia=_is_auto,
                        _ae=_acc_email, _oe=_own, _eid=getattr(std_email, "id", ""),
                    ) -> None:
                        try:
                            from app.services.auto_reply import (
                                send_auto_reply_if_needed,
                            )
                            send_auto_reply_if_needed(
                                provider=_ar,
                                account_id=_aid,
                                email=_e,
                                is_auto_reply=_ia,
                                account_email=_ae,
                                own_account_emails=_oe,
                            )
                        except Exception as e:
                            logger.warning(
                                f"Auto-reply post-commit dispatch failed for "
                                f"{_eid} on account {_aid}: {e!r}"
                            )

                    session.info.setdefault(
                        "_deferred_auto_replies", []
                    ).append(_deferred_dispatch)
                except Exception as e:
                    logger.warning(
                        f"Auto-reply staging failed for {std_email.id} "
                        f"on account {account.id}: {e!r}"
                    )

        # Warm the on-demand detail cache with the bodies we just fetched so
        # the first open is instant instead of a Graph-throttled re-fetch.
        # Only in metadata-only mode — full-cache already persists bodies to
        # SQLite, so get_email serves them without a provider round-trip.
        if not persist_content and emails:
            try:
                _warm_detail_cache_from_sync(emails, account)
            except Exception as _warm_err:  # pragma: no cover — best-effort
                logger.debug("detail-cache warm skipped: %s", _warm_err)

        return new_count

    def _ensure_contact_for_email(
        self,
        contact_repo,
        std_email,
        account,
        is_sent: bool,
    ) -> None:
        """Audit P0-A3 : garantit qu'un contact existe pour cet email, sans
        bumper son compteur.

        Appelé sur les deux chemins « email déjà connu » :
        - ``if existing`` (email déjà en DB depuis une sync précédente)
        - UNIQUE collision dans le insert (race entre threads de sync)

        Pourquoi ne PAS re-bumper le compteur :
        - Sur ``if existing`` → le bump a eu lieu à l'insert initial.
        - Sur UNIQUE collision → le bump a eu lieu chez le thread gagnant.
        Re-bumper ici introduirait du double-count à chaque delta sync (les
        delta renvoient régulièrement les mêmes emails dont les labels/folders
        ont changé).

        Pourquoi quand même appeler ``get_or_create`` :
        - Recovery edge case : si le bump avait échoué (DB hiccup) lors de
          l'insert initial, le contact pouvait ne pas exister. Sur
          re-rencontre on le crée idempotemment. Mieux vaut un contact à
          ``count=0`` qu'un contact absent → la liste contacts reste fidèle.

        Tolérant aux erreurs : log et continue. Cette méthode ne doit jamais
        casser la sync.
        """
        try:
            user_email = (account.email or "").strip().lower()
            if is_sent:
                seen: set[str] = set()
                raw_recipients = list(std_email.to or []) + list(std_email.cc or [])
                for raw in raw_recipients:
                    if not raw:
                        continue
                    addr = str(raw).strip().lower()
                    if "<" in addr and ">" in addr:
                        addr = addr.split("<", 1)[1].split(">", 1)[0].strip()
                    if not addr or "@" not in addr or addr == user_email or addr in seen:
                        continue
                    seen.add(addr)
                    contact_repo.get_or_create(email=addr, account_id=account.id)
            elif std_email.sender:
                contact_repo.get_or_create(
                    email=std_email.sender,
                    account_id=account.id,
                    name=std_email.sender_name,
                )
        except Exception as e:
            logger.debug(
                f"_ensure_contact_for_email failed for email {std_email.id} "
                f"on account {account.id}: {e!r}"
            )

    def _enforce_cache_limits(self, session: Session, account_ids: List[int]) -> None:
        """
        Enforce email cache limits after sync.

        Removes oldest emails (by date) when account exceeds cache limit.

        Args:
            session: Database session.
            account_ids: List of account IDs to check.
        """
        cache_manager = get_cache_manager()
        results = cache_manager.enforce_limit_all_accounts(session, account_ids)

        # Log any cleanup that occurred
        for result in results:
            if result.emails_deleted > 0:
                logger.info(
                    f"Cache cleanup for account {result.account_id}: "
                    f"deleted {result.emails_deleted} oldest emails "
                    f"(limit: {cache_manager.cache_limit})"
                )


# Global sync service instance
_sync_service: Optional[SyncService] = None


def get_sync_service() -> Optional[SyncService]:
    """Get the global sync service instance."""
    return _sync_service


def init_sync_service(
    sync_interval: int = 120,
    **callbacks
) -> SyncService:
    """
    Initialize the global sync service.

    Args:
        sync_interval: Interval between syncs in seconds.
        **callbacks: Event callbacks (on_sync_started, on_sync_complete, etc.).

    Returns:
        The initialized SyncService instance.
    """
    global _sync_service

    if _sync_service is not None:
        logger.warning("Sync service already initialized, stopping existing instance")
        _sync_service.stop()

    _sync_service = SyncService(sync_interval=sync_interval, **callbacks)
    return _sync_service
