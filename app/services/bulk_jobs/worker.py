"""Background worker that drains the bulk-job queue.

Runs as a single dispatcher thread plus one `_AccountQueue` thread per
active account. Each `_AccountQueue` owns:

- a per-provider `TokenBucket` (cf. rate_limiter.py)
- a cached, authenticated provider instance
- a tight loop: claim → execute → record → emit progress

Why this shape, not asyncio: Flask-SocketIO + SQLAlchemy + the email
provider SDKs are all sync. A worker thread per account is the simplest
isolation that survives one provider melting down (e.g. Gmail throttle
spike on user A) without starving user B's account.

Idempotency contract: every operation we dispatch *must* be safe to
re-run on a message that already had it applied (Gmail labels are
set-based, Outlook archive is already-archived no-op, IMAP STORE +FLAGS
is idempotent). On 404/410, the worker treats the item as `skipped`
rather than failed — the message is gone, nothing to do.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy import text

from app.db.database import get_session_factory
from app.interfaces.email_provider import InsufficientScopeError
from app.db.models.bulk_job import (
    ITEM_STATE_PENDING,
    JOB_STATUS_PAUSED,
    JOB_STATUSES_TERMINAL,
    JOB_TYPE_ADD_LABEL,
    JOB_TYPE_ARCHIVE,
    JOB_TYPE_DELETE_FOREVER,
    JOB_TYPE_MARK_READ,
    JOB_TYPE_MARK_UNREAD,
    JOB_TYPE_MOVE_TO_INBOX,
    JOB_TYPE_MOVE_TO_TRASH,
    JOB_TYPE_RESTORE_FROM_TRASH,
)
from app.services.bulk_jobs.rate_limiter import TokenBucket, make_bucket_for
from app.services.bulk_jobs.repository import (
    BulkJobRepository,
    ClaimedItem,
    NewBulkJob,
)

logger = logging.getLogger(__name__)


# Job types whose HTTP-side handler optimistically commits Email.folder
# BEFORE the worker confirms with the provider. When the worker later
# fails, we must revert that optimistic state so the email reappears in
# the user's inbox rather than vanishing into a phantom "archived"
# state that doesn't exist on the provider. See F-02 (audit 2026-05-11).
_OPTIMISTIC_FOLDER_TARGETS = {
    JOB_TYPE_ARCHIVE: "inbox",
    JOB_TYPE_MOVE_TO_TRASH: "inbox",
}

# Frontend payload key per job type — names the failed action so the
# UI can revert the right optimistic update (un-archive, un-trash, ...).
_OPTIMISTIC_FAILURE_KEY = {
    JOB_TYPE_ARCHIVE: "archive_failed",
    JOB_TYPE_MOVE_TO_TRASH: "trash_failed",
}


def _rollback_optimistic_state(
    session: Any,
    item: "ClaimedItem",
    reason: str,
) -> None:
    """Revert the HTTP handler's optimistic SQLite folder update and emit
    a WebSocket event so the frontend can un-strip the row.

    Pre-F-02, the bulk-archive HTTP path committed Email.folder='archived'
    at request time for every raw_id. If the worker hit a provider failure
    later, mark_item_failed recorded the queue state but never touched
    Email.folder — so the email vanished from the UI's inbox view (SQLite
    said archived) while still living in the provider's INBOX.

    Idempotent: on a job type that doesn't have an optimistic folder
    update, this is a no-op. Safe to call from every failure path.
    """
    target_folder = _OPTIMISTIC_FOLDER_TARGETS.get(item.job_type)
    if target_folder is None:
        return  # job type has no optimistic folder update to roll back

    failure_key = _OPTIMISTIC_FAILURE_KEY.get(item.job_type, "op_failed")

    # 1. Revert SQLite state. Use a fresh session-scoped repo so a failure
    #    here doesn't poison the caller's transaction.
    try:
        from app.db.repositories.email_repository import EmailRepository
        repo = EmailRepository(session)
        repo.update_folder_by_email_id(
            item.provider_msg_id,
            target_folder,
            account_id=item.account_id,
        )
    except Exception:
        logger.exception(
            "[bulk-worker] rollback SQLite folder failed for %s (item=%s)",
            item.provider_msg_id, item.item_id,
        )

    # 2. Emit WS event so the frontend can revert its optimistic removal.
    try:
        from app.api.websocket import emit_email_updated
        emit_email_updated(
            item.provider_msg_id,
            {failure_key: True, "error": reason},
            account_id=item.account_id,
        )
    except Exception:
        logger.exception(
            "[bulk-worker] emit_email_updated failed for %s",
            item.provider_msg_id,
        )


def _rollback_pending_optimistic_state(
    session: Any,
    repo: BulkJobRepository,
    item: "ClaimedItem",
    reason: str,
) -> None:
    """Rollback still-pending siblings before a structural job failure.

    Auth/provider failures fail the whole job at once. Those pending siblings
    never get claimed individually, so they need the same optimistic folder
    rollback here before the repository flips them to failed.
    """
    if _OPTIMISTIC_FOLDER_TARGETS.get(item.job_type) is None:
        return

    try:
        pending_items = repo.list_items(
            item.job_id,
            state=ITEM_STATE_PENDING,
            limit=100_000,
        )
    except Exception:
        logger.exception(
            "[bulk-worker] listing pending items for rollback failed (job=%s)",
            item.job_id,
        )
        return

    for row in pending_items:
        provider_msg_id = row.get("provider_msg_id")
        if not provider_msg_id:
            continue
        sibling = ClaimedItem(
            item_id=int(row.get("id") or 0),
            job_id=item.job_id,
            account_id=item.account_id,
            job_type=item.job_type,
            provider_msg_id=provider_msg_id,
            attempts=int(row.get("attempts") or 0),
            params=item.params or {},
        )
        _rollback_optimistic_state(session, sibling, reason)


def _set_permanent_delete_availability(account_id: int, *, available: bool) -> None:
    """Persist whether permanent-delete (the full Gmail scope) works for
    this account, so the auto-deletion scheduler stops re-enqueuing doomed
    `delete_forever` jobs daily (bug #2).

    Stored as the internal `_permanent_delete_unavailable` flag in the
    *per-account* settings override (DB `accounts.settings_json`), never
    the shared global store. Self-heals: a later successful permanent
    delete clears the flag, so adding the scope + reconnecting recovers
    the feature without a manual reset.
    """
    if not account_id or account_id <= 0:
        return
    try:
        from app.api.settings import (
            _load_account_settings_overrides,
            _save_account_settings,
        )

        overrides = _load_account_settings_overrides(account_id)
        currently_unavailable = bool(overrides.get("_permanent_delete_unavailable"))
        if available and currently_unavailable:
            overrides.pop("_permanent_delete_unavailable", None)
            _save_account_settings(overrides, account_id)
        elif (not available) and (not currently_unavailable):
            overrides["_permanent_delete_unavailable"] = True
            _save_account_settings(overrides, account_id)
    except Exception:
        logger.exception(
            "[bulk-worker] could not persist permanent-delete availability "
            "for account %s",
            account_id,
        )


# ── Configuration ──────────────────────────────────────────────────────
DISPATCHER_POLL_INTERVAL_S = 1.0
ACCOUNT_QUEUE_IDLE_TIMEOUT_S = 60.0
ITEM_MAX_ATTEMPTS = 3
PROGRESS_EMIT_THROTTLE_S = 1.0
DEFAULT_RETRY_AFTER_S = 30.0
SHUTDOWN_GRACE_S = 30.0
INLINE_THRESHOLD = 10  # below this many items, callers can run sync inline


# ── Operation outcome (worker-internal) ────────────────────────────────
@dataclass
class _OpOutcome:
    """Normalized result of a single provider call."""

    succeeded: bool
    skipped_reason: Optional[str] = None
    rate_limited_seconds: Optional[float] = None
    auth_failed: bool = False
    error: Optional[str] = None
    transient: bool = True  # only meaningful when succeeded == False
    # Structural failure that dooms *every* item in the job, not just this
    # one (e.g. missing OAuth scope for permanent delete). The worker
    # cascade-fails the rest of the job instead of firing N identical
    # provider calls (bug #1: the 403 storm).
    fatal_for_job: bool = False


# ── Provider error inspection ──────────────────────────────────────────
def _classify_provider_error(exc: BaseException) -> _OpOutcome:
    """Inspect a provider exception and decide how the worker should react.

    Lives here (not in adapters) because the bulk worker is the first
    code path that *needs* uniform classification across Gmail, Outlook,
    and IMAP. Adding it to each adapter would scatter the rule set.

    Heuristics, in priority order:
      1. Gmail's `googleapiclient.errors.HttpError` carries status +
         optional `Retry-After` header → exposed as `.resp.status`.
      2. Microsoft Graph's `requests.HTTPError` follows the same shape:
         `.response.status_code` + `Retry-After`.
      3. Generic `requests.HTTPError` / dict-like `.status` attribute.
      4. Anything mentioning "auth"/"unauthorized"/"invalid_grant" is
         treated as fatal (no point retrying).
      5. Network-y exceptions are transient → exponential backoff.
    """
    msg = str(exc) or exc.__class__.__name__

    # Scope OAuth manquant (ex. messages.delete sans https://mail.google.com/)
    # → fatal, PAS auth_failed : re-connecter le compte ne change pas les
    # scopes demandés par l'app, donc le CTA « reconnecter » serait mensonger.
    if isinstance(exc, InsufficientScopeError):
        return _OpOutcome(
            succeeded=False,
            error=f"insufficient OAuth scope: {msg}",
            transient=False,
            fatal_for_job=True,
        )

    # Gmail / Microsoft Graph: try the structured shape first.
    status: int | None = None
    retry_after: float | None = None
    resp = getattr(exc, "resp", None) or getattr(exc, "response", None)
    if resp is not None:
        status = (
            getattr(resp, "status", None)
            or getattr(resp, "status_code", None)
        )
        try:
            headers = getattr(resp, "headers", None) or {}
            ra = headers.get("Retry-After") or headers.get("retry-after")
            if ra is not None:
                retry_after = float(ra)
        except (TypeError, ValueError):
            retry_after = None

    if status == 404 or status == 410:
        return _OpOutcome(succeeded=False, skipped_reason=f"{status} not found")
    if status == 429 or status == 503:
        return _OpOutcome(
            succeeded=False,
            rate_limited_seconds=retry_after or DEFAULT_RETRY_AFTER_S,
            error=f"{status} rate-limited",
        )
    if status in (401, 403):
        # Some providers use 403 for quota *and* for permission; treat
        # as auth so we don't burn retries when credentials are dead.
        # The user surfaces a "reconnect" CTA from this state.
        return _OpOutcome(
            succeeded=False,
            auth_failed=True,
            error=f"{status} unauthorized",
            transient=False,
        )
    if status and 500 <= status < 600:
        return _OpOutcome(succeeded=False, error=f"{status} server error", transient=True)

    lowered = msg.lower()
    if any(
        token in lowered
        for token in ("unauthorized", "invalid_grant", "token has been expired")
    ):
        return _OpOutcome(
            succeeded=False, auth_failed=True, error=msg, transient=False
        )
    if "not found" in lowered or "no such message" in lowered:
        return _OpOutcome(succeeded=False, skipped_reason=msg)
    if "rate limit" in lowered or "quota exceeded" in lowered:
        return _OpOutcome(
            succeeded=False,
            rate_limited_seconds=retry_after or DEFAULT_RETRY_AFTER_S,
            error=msg,
        )

    return _OpOutcome(succeeded=False, error=msg, transient=True)


# ── Provider operations dispatch ───────────────────────────────────────
def _execute_op(provider: Any, item: ClaimedItem) -> _OpOutcome:
    """Run the provider call corresponding to `item.job_type`.

    Each branch swallows its return value and converts it to `_OpOutcome`
    so the worker loop has a uniform shape.
    """
    msg_id = item.provider_msg_id
    try:
        if item.job_type == JOB_TYPE_MARK_READ:
            ok = bool(provider.mark_as_read(msg_id))
        elif item.job_type == JOB_TYPE_MARK_UNREAD:
            ok = bool(provider.mark_as_unread(msg_id))
        elif item.job_type == JOB_TYPE_ARCHIVE:
            ok = bool(provider.archive_email(msg_id))
        elif item.job_type == JOB_TYPE_MOVE_TO_TRASH:
            ok = bool(provider.delete_email(msg_id))
        elif item.job_type == JOB_TYPE_RESTORE_FROM_TRASH:
            ok = bool(provider.restore_from_trash(msg_id))
        elif item.job_type == JOB_TYPE_MOVE_TO_INBOX:
            ok = bool(provider.move_to_inbox(msg_id))
        elif item.job_type == JOB_TYPE_ADD_LABEL:
            label = (item.params or {}).get("label", "")
            if not label:
                return _OpOutcome(
                    succeeded=False,
                    error="add_label requires params.label",
                    transient=False,
                )
            ok = bool(provider.apply_label(msg_id, label))
        elif item.job_type == JOB_TYPE_DELETE_FOREVER:
            # `permanently_delete` is implemented on Gmail, Outlook, and
            # IMAP adapters but missing from the abstract base — guard so
            # an unsupported provider gives us a fatal classification
            # instead of an AttributeError that the catch-all would label
            # as transient.
            if not hasattr(provider, "permanently_delete"):
                return _OpOutcome(
                    succeeded=False,
                    error="provider does not support permanent delete",
                    transient=False,
                )
            ok = bool(provider.permanently_delete(msg_id))
        else:
            return _OpOutcome(
                succeeded=False,
                error=f"unknown job_type {item.job_type!r}",
                transient=False,
            )
    except BaseException as exc:  # noqa: BLE001 — we re-raise after classification
        # KeyboardInterrupt + SystemExit must propagate so shutdown works.
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return _classify_provider_error(exc)

    if ok:
        return _OpOutcome(succeeded=True)
    # Provider returned falsy without raising — usually means "I logged
    # a warning but couldn't do it". Treat as transient so we retry once
    # before giving up.
    return _OpOutcome(succeeded=False, error="provider returned False", transient=True)


# ── Account-scoped queue ───────────────────────────────────────────────
class _AccountQueue:
    """One worker thread per active account.

    Holds the `TokenBucket`, the cached provider, and a small cache of
    job statuses so we don't slam the DB checking pause/cancel each
    iteration.
    """

    def __init__(
        self,
        account_id: int,
        worker: "BulkJobWorker",
    ) -> None:
        self._account_id = account_id
        self._worker = worker
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"BulkAccountQueue-{account_id}",
            daemon=True,
        )
        self._provider: Any | None = None
        self._provider_kind: str = "imap"  # conservative default
        self._account_email: str = ""
        self._bucket: TokenBucket | None = None
        self._last_progress_emit: dict[str, float] = {}
        # Dedup the permanent-delete availability persistence (bug #2) so a
        # 248-item delete job doesn't hammer settings once per item.
        self._pd_marked_available = False
        self._pd_marked_unavailable = False

    # ── lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    # ── main loop ──────────────────────────────────────────────────────
    def _run(self) -> None:
        """Drain pending items until idle for `ACCOUNT_QUEUE_IDLE_TIMEOUT_S`.

        Worker session is opened once and reused for every claim — this
        is safe because no Flask request thread shares it, and SQLite WAL
        mode lets us interleave reads with cross-thread writers.
        """
        tokens = None
        try:
            from app.infrastructure.cost_manager import set_usage_context

            tokens = set_usage_context(account_id=self._account_id, feature="bulk_job")
        except Exception:
            tokens = None

        session_factory = get_session_factory()
        session = session_factory()
        repo = BulkJobRepository(session)

        idle_since: float | None = None
        try:
            while not self._stop.is_set():
                try:
                    claimed = repo.claim_next_pending_for_account(self._account_id)
                    session.commit()
                except Exception as exc:  # noqa: BLE001
                    session.rollback()
                    if "database is locked" in str(exc).lower():
                        # Contention SQLite transitoire (writer concurrent —
                        # sync, labels). busy_timeout ne couvre pas l'upgrade
                        # de snapshot en WAL (SQLITE_BUSY immédiat) ; le retry
                        # 2 s ci-dessous suffit. Pas un incident → warning
                        # sans traceback (audit 2026-06-09).
                        logger.warning(
                            "[bulk-worker] claim contention for account %s "
                            "(database is locked) — retry in 2s",
                            self._account_id,
                        )
                    else:
                        logger.exception(
                            "[bulk-worker] claim error for account %s: %s",
                            self._account_id,
                            exc,
                        )
                    if self._stop.wait(timeout=2.0):
                        break
                    continue

                if claimed is None:
                    if idle_since is None:
                        idle_since = time.monotonic()
                    elif time.monotonic() - idle_since >= ACCOUNT_QUEUE_IDLE_TIMEOUT_S:
                        logger.info(
                            "[bulk-worker] account %s idle %.0fs, exiting",
                            self._account_id,
                            ACCOUNT_QUEUE_IDLE_TIMEOUT_S,
                        )
                        break
                    if self._stop.wait(timeout=DISPATCHER_POLL_INTERVAL_S):
                        break
                    continue

                idle_since = None

                # Re-check parent job status before doing real work. The
                # user may have hit Pause/Cancel between claim and now.
                parent_status = repo.get_job_status(claimed.job_id)
                if parent_status == JOB_STATUS_PAUSED:
                    # Put item back to pending so resume picks it up. A pause
                    # is not the item's fault — don't spend its retry budget
                    # (bug #9).
                    repo.requeue_item_for_retry(
                        claimed.item_id, error="paused mid-claim",
                        bump_attempts=False,
                    )
                    session.commit()
                    if self._stop.wait(timeout=2.0):
                        break
                    continue
                if parent_status in JOB_STATUSES_TERMINAL:
                    repo.mark_item_skipped(
                        claimed.item_id, claimed.job_id, "job not active"
                    )
                    session.commit()
                    self._maybe_finalize(repo, session, claimed.job_id)
                    continue

                self._process_claimed(repo, session, claimed)
        finally:
            try:
                session.close()
            except Exception:
                pass
            try:
                from app.infrastructure.cost_manager import reset_usage_context

                reset_usage_context(tokens)
            except Exception:
                pass
            self._worker._mark_queue_done(self._account_id)

    # ── per-item path ──────────────────────────────────────────────────
    def _process_claimed(
        self,
        repo: BulkJobRepository,
        session: Any,
        item: ClaimedItem,
    ) -> None:
        provider = self._ensure_provider()
        if provider is None:
            # Auth failed or account disappeared — cascade-fail all remaining
            # items so the user gets an immediate "reconnect" signal rather
            # than watching 100+ items grind through retries one by one.
            reason = "no authenticated provider"
            _rollback_optimistic_state(session, item, reason)
            _rollback_pending_optimistic_state(session, repo, item, reason)
            repo.mark_item_failed(item.item_id, item.job_id, reason)
            self._fail_remaining_for_job(repo, item.job_id, reason)
            session.commit()
            self._maybe_finalize(repo, session, item.job_id)
            return

        bucket = self._ensure_bucket()
        # Block until we have budget. `acquire` honors any active penalty.
        if not bucket.acquire(timeout=300):
            # Throttle, not the item's fault — don't spend the retry budget
            # (bug #9).
            repo.requeue_item_for_retry(
                item.item_id, error="rate-limit acquire timeout",
                bump_attempts=False,
            )
            session.commit()
            return

        outcome = _execute_op(provider, item)

        if outcome.succeeded:
            repo.mark_item_succeeded(item.item_id, item.job_id)
            # A successful permanent delete proves the full scope is present —
            # clear any stale "unavailable" flag so auto-deletion resumes
            # (bug #2 self-heal).
            if (
                item.job_type == JOB_TYPE_DELETE_FOREVER
                and not self._pd_marked_available
            ):
                _set_permanent_delete_availability(item.account_id, available=True)
                self._pd_marked_available = True
        elif outcome.skipped_reason:
            repo.mark_item_skipped(
                item.item_id, item.job_id, outcome.skipped_reason
            )
        elif outcome.rate_limited_seconds is not None:
            bucket.penalize(outcome.rate_limited_seconds)
            # Provider throttle — don't spend the retry budget (bug #9).
            repo.requeue_item_for_retry(
                item.item_id,
                error=outcome.error or "rate limited",
                bump_attempts=False,
            )
        elif outcome.fatal_for_job:
            # Structural failure that dooms every item in this job (missing
            # OAuth scope for permanent delete). Fail this item AND
            # cascade-fail the rest so we don't fire N identical 403s
            # (bug #1). Persist the unavailability so the scheduler stops
            # re-enqueuing this doomed job daily (bug #2).
            err = outcome.error or "fatal job error"
            _rollback_optimistic_state(session, item, err)
            _rollback_pending_optimistic_state(session, repo, item, err)
            repo.mark_item_failed(item.item_id, item.job_id, err)
            self._fail_remaining_for_job(repo, item.job_id, err)
            if (
                item.job_type == JOB_TYPE_DELETE_FOREVER
                and not self._pd_marked_unavailable
            ):
                _set_permanent_delete_availability(
                    item.account_id, available=False
                )
                self._pd_marked_unavailable = True
        elif outcome.auth_failed:
            # Treat as fatal for this item AND finalize the job as failed —
            # subsequent items will obviously fail too. Drop the cached
            # provider so the *next* job (after the user reconnects) has
            # a fresh attempt.
            self._provider = None
            # F-02 (audit 2026-05-11): revert the HTTP handler's optimistic
            # SQLite folder update + tell the frontend so the row reappears.
            _rollback_optimistic_state(session, item, outcome.error or "auth failed")
            _rollback_pending_optimistic_state(
                session, repo, item, outcome.error or "auth failed"
            )
            repo.mark_item_failed(
                item.item_id, item.job_id, outcome.error or "auth failed"
            )
            self._fail_remaining_for_job(repo, item.job_id, "auth failed")
        else:
            # Non-rate-limit, non-auth failure. If the classifier flagged
            # it as fatal (`transient=False`), there is nothing to gain
            # from retrying — fail fast. Otherwise we retry up to
            # ITEM_MAX_ATTEMPTS with exponential backoff. `item.attempts`
            # is the count *before* this run, so attempts+1 reflects the
            # run we just completed.
            next_attempts = item.attempts + 1
            err = outcome.error or "unknown error"
            if not outcome.transient or next_attempts >= ITEM_MAX_ATTEMPTS:
                # F-02 (audit 2026-05-11): item permanently failed — revert
                # the optimistic SQLite folder + notify the frontend.
                _rollback_optimistic_state(session, item, err)
                repo.mark_item_failed(item.item_id, item.job_id, err)
            else:
                repo.requeue_item_for_retry(item.item_id, error=err)
                # Sleep before letting this item be re-claimed. Exponential
                # but capped to keep the queue moving.
                backoff = min(2 ** next_attempts, 30)
                self._stop.wait(timeout=backoff)

        try:
            session.commit()
        except Exception:
            session.rollback()
            logger.exception(
                "[bulk-worker] commit failed for item %s", item.item_id
            )

        self._emit_progress(repo, item.job_id)
        self._maybe_finalize(repo, session, item.job_id)

    def _fail_remaining_for_job(
        self, repo: BulkJobRepository, job_id: str, reason: str
    ) -> None:
        """Mark every remaining pending item of `job_id` as failed.

        Used when the failure mode is structural (bad auth, banned
        provider) — burning through 5 000 items one-by-one would just
        add latency to the user discovering "you need to reconnect".
        """
        repo.fail_remaining_pending(job_id, reason)

    def _maybe_finalize(
        self, repo: BulkJobRepository, session: Any, job_id: str
    ) -> None:
        """Try to flip the job to a terminal status if no items remain."""
        new_status = repo.finalize_job_if_drained(job_id)
        if new_status is None:
            return
        try:
            session.commit()
        except Exception:
            session.rollback()
            logger.exception(
                "[bulk-worker] finalize commit failed for job %s", job_id
            )
            return

        snapshot = repo.get_job(job_id)
        if snapshot is None:
            return
        try:
            from app.api.websocket import emit_to_account

            emit_to_account(
                "bulk_job_completed",
                {
                    "job_id": job_id,
                    "status": new_status,
                    "succeeded": snapshot["succeeded_count"],
                    "failed": snapshot["failed_count"],
                    "skipped": snapshot["skipped_count"],
                    "total": snapshot["target_total"],
                },
                self._account_id,
            )
        except Exception:
            logger.debug("[bulk-worker] could not emit completion", exc_info=True)

    # ── progress emit (throttled) ──────────────────────────────────────
    def _emit_progress(self, repo: BulkJobRepository, job_id: str) -> None:
        now = time.monotonic()
        last = self._last_progress_emit.get(job_id, 0.0)
        if now - last < PROGRESS_EMIT_THROTTLE_S:
            return
        snapshot = repo.get_job(job_id)
        if snapshot is None:
            return
        self._last_progress_emit[job_id] = now
        try:
            from app.api.websocket import emit_to_account

            emit_to_account(
                "bulk_job_progress",
                {
                    "job_id": job_id,
                    "succeeded": snapshot["succeeded_count"],
                    "failed": snapshot["failed_count"],
                    "skipped": snapshot["skipped_count"],
                    "total": snapshot["target_total"],
                    "status": snapshot["status"],
                },
                self._account_id,
            )
        except Exception:
            logger.debug("[bulk-worker] could not emit progress", exc_info=True)

    # ── lazy provider construction ─────────────────────────────────────
    def _ensure_provider(self) -> Any | None:
        if self._provider is not None:
            return self._provider
        try:
            self._account_email, self._provider_kind = (
                self._worker._lookup_account(self._account_id)
            )
        except Exception:
            logger.exception(
                "[bulk-worker] account %s lookup failed", self._account_id
            )
            return None
        if not self._account_email:
            return None
        try:
            from app.multi_accounts import (
                create_provider_for_account,
                get_account_manager,
            )

            mgr = get_account_manager()
            cfg = mgr.get_account_by_email(self._account_email)
            if cfg is None:
                logger.warning(
                    "[bulk-worker] no AccountConfig for %s", self._account_email
                )
                return None
            provider = create_provider_for_account(cfg)
            if not provider.authenticate():
                logger.warning(
                    "[bulk-worker] authenticate() failed for %s",
                    self._account_email,
                )
                return None
            self._provider = provider
            return provider
        except Exception:
            logger.exception(
                "[bulk-worker] provider build failed for %s", self._account_email
            )
            return None

    def _ensure_bucket(self) -> TokenBucket:
        if self._bucket is None:
            # _ensure_provider populates _provider_kind on first call.
            self._bucket = make_bucket_for(
                self._provider_kind, account_label=str(self._account_id)
            )
        return self._bucket


# ── Top-level worker singleton ─────────────────────────────────────────
class BulkJobWorker:
    """Dispatcher that owns one `_AccountQueue` per active account."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._dispatcher: threading.Thread | None = None
        self._queues: dict[int, _AccountQueue] = {}
        self._queues_lock = threading.Lock()
        self._account_lookup_cache: dict[int, tuple[str, str]] = {}
        self._account_lookup_cache_at: dict[int, float] = {}

    # ── lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        if self._dispatcher and self._dispatcher.is_alive():
            return
        # Recover items left in_progress by a previous boot. Safe because
        # every supported op is idempotent; 404 → skipped.
        try:
            session_factory = get_session_factory()
            session = session_factory()
            try:
                repo = BulkJobRepository(session)
                recovered = repo.recover_orphaned_in_progress()
                session.commit()
                if recovered:
                    logger.info(
                        "[bulk-worker] recovered %d orphaned in_progress items",
                        recovered,
                    )
            finally:
                session.close()
        except Exception:
            logger.exception("[bulk-worker] orphan recovery failed (non-fatal)")

        self._stop.clear()
        self._dispatcher = threading.Thread(
            target=self._dispatcher_loop,
            name="BulkJobDispatcher",
            daemon=True,
        )
        self._dispatcher.start()
        logger.info("[bulk-worker] started")

    def stop(self, timeout: float = SHUTDOWN_GRACE_S) -> None:
        self._stop.set()
        # Tell every queue to stop, then join.
        with self._queues_lock:
            queues = list(self._queues.values())
        for q in queues:
            q.stop()
        if self._dispatcher:
            self._dispatcher.join(timeout=2.0)
        deadline = time.monotonic() + timeout
        for q in queues:
            remaining = max(0.0, deadline - time.monotonic())
            q.join(timeout=remaining)
        logger.info(
            "[bulk-worker] stopped (queues left alive: %d)",
            sum(1 for q in queues if q.is_alive()),
        )

    # ── dispatcher loop ────────────────────────────────────────────────
    def _dispatcher_loop(self) -> None:
        # Initial small delay so DB engine + WS are fully up.
        if self._stop.wait(timeout=2.0):
            return

        while not self._stop.is_set():
            try:
                self._spawn_queues_for_active_accounts()
            except Exception:
                logger.exception("[bulk-worker] dispatcher tick failed")

            self._reap_dead_queues()

            if self._stop.wait(timeout=DISPATCHER_POLL_INTERVAL_S):
                break

    def _spawn_queues_for_active_accounts(self) -> None:
        session_factory = get_session_factory()
        session = session_factory()
        try:
            repo = BulkJobRepository(session)
            account_ids = repo.list_active_account_ids()
        finally:
            session.close()
        if not account_ids:
            return
        with self._queues_lock:
            for aid in account_ids:
                existing = self._queues.get(aid)
                if existing is not None and existing.is_alive():
                    continue
                queue = _AccountQueue(account_id=aid, worker=self)
                self._queues[aid] = queue
                queue.start()
                logger.debug("[bulk-worker] spawned queue for account %s", aid)

    def _reap_dead_queues(self) -> None:
        with self._queues_lock:
            dead = [aid for aid, q in self._queues.items() if not q.is_alive()]
            for aid in dead:
                self._queues.pop(aid, None)

    def _mark_queue_done(self, account_id: int) -> None:
        with self._queues_lock:
            self._queues.pop(account_id, None)

    # ── account lookup (small TTL cache) ───────────────────────────────
    def _lookup_account(self, account_id: int) -> tuple[str, str]:
        """Return (email, provider_kind) for an account_id.

        Cached with a 5-minute TTL because providers don't change often
        but a stale cache through an account deletion would only emit
        ghost queue threads (they'd promptly idle-die when the dispatcher
        stops listing the account).
        """
        TTL = 300.0
        now = time.monotonic()
        ts = self._account_lookup_cache_at.get(account_id)
        if ts and now - ts < TTL:
            return self._account_lookup_cache[account_id]
        session_factory = get_session_factory()
        session = session_factory()
        try:
            row = session.execute(
                text("SELECT email, provider FROM accounts WHERE id = :id"),
                {"id": account_id},
            ).first()
        finally:
            session.close()
        if not row:
            return ("", "imap")
        result = (row.email or "", (row.provider or "imap").lower())
        self._account_lookup_cache[account_id] = result
        self._account_lookup_cache_at[account_id] = now
        return result


# ── Module-level singleton + helpers ───────────────────────────────────
_worker_singleton: Optional[BulkJobWorker] = None
_worker_lock = threading.Lock()


def init_worker() -> BulkJobWorker:
    """Instantiate (lazily) and start the global worker.

    Idempotent: calling twice from `run_api.py` is fine.
    """
    global _worker_singleton
    with _worker_lock:
        if _worker_singleton is None:
            _worker_singleton = BulkJobWorker()
        if _worker_singleton._dispatcher is None or not _worker_singleton._dispatcher.is_alive():
            _worker_singleton.start()
        return _worker_singleton


def get_worker() -> Optional[BulkJobWorker]:
    return _worker_singleton


def shutdown_worker(timeout: float = SHUTDOWN_GRACE_S) -> None:
    global _worker_singleton
    with _worker_lock:
        if _worker_singleton is None:
            return
        _worker_singleton.stop(timeout=timeout)
        _worker_singleton = None


def enqueue_job(spec: NewBulkJob, *, on_enqueued: Callable | None = None) -> str:
    """Public entrypoint for callers that just want "do this bulk thing".

    Persists the job, kicks the dispatcher (it'll pick the new account
    on the next tick anyway, but we hint anyway), and emits an
    `bulk_job_enqueued` WS event so the UI immediately shows the new row.

    `on_enqueued`, when provided, is called with the new job_id inside
    the same DB transaction — useful for callers that want to wire
    additional bookkeeping atomically (e.g. cache invalidation).
    """
    from app.db.database import get_db_session

    with get_db_session() as session:
        repo = BulkJobRepository(session)
        job_id = repo.create_job(spec)
        if on_enqueued is not None:
            try:
                on_enqueued(job_id)
            except Exception:
                logger.exception(
                    "[bulk-worker] on_enqueued callback failed for %s", job_id
                )

    # Make sure a worker is actually running (idempotent).
    init_worker()

    # Optimistic UI hint.
    try:
        from app.api.websocket import emit_to_account

        emit_to_account(
            "bulk_job_enqueued",
            {
                "job_id": job_id,
                "account_id": spec.account_id,
                "job_type": spec.job_type,
                "source": spec.source,
                "target_total": len(spec.target_msg_ids),
            },
            spec.account_id,
        )
    except Exception:
        logger.debug(
            "[bulk-worker] could not emit enqueued event", exc_info=True
        )

    return job_id
