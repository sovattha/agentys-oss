# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Daemon thread that delivers scheduled emails when they come due.

Polls `ScheduledEmailStore.list_due()` every CHECK_INTERVAL_SECONDS, claims
each row atomically (pending -> sending) so concurrent processes can't
double-deliver, then dispatches via the existing email provider.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from app.api.websocket import emit_email_schedule_failed, emit_email_sent_scheduled
from app.services.scheduled_email_store import (
    ScheduledEmailStore,
    get_default_store,
    _idempotency_key_for,
)

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60
INITIAL_DELAY_SECONDS = 30
# B-02 (audit 2026-06-11): cap on delivery attempts before a transient
# failure becomes terminal. `claim_for_send` increments the `attempts`
# column, so the value carried by a claimed row dict is the count BEFORE
# the current attempt.
MAX_SEND_ATTEMPTS = 3


def _is_transient_send_error(exc: BaseException) -> bool:
    """Conservative transient-failure classification (B-02).

    Network/timeout/OS-level errors are worth a retry on a later tick
    (`requests.RequestException` subclasses IOError, so it is covered).
    Validation errors (e.g. ValueError from attachment decoding) and the
    fail-closed RuntimeError from `_resolve_previous_attempt` stay terminal.
    """
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def _load_account(account_id: int):
    """Load an Account by primary key. Returns None if missing or inactive."""
    try:
        from app.db.database import get_db_session
        from app.db.models.account import Account

        with get_db_session() as session:
            acct = session.get(Account, int(account_id))
            if acct is None or not getattr(acct, "is_active", True):
                return None
            return acct
    except Exception:
        logger.exception("ScheduledEmailScheduler: account load failure")
        return None


class ScheduledEmailScheduler:
    def __init__(
        self,
        *,
        store: Optional[ScheduledEmailStore] = None,
        check_interval: int = CHECK_INTERVAL_SECONDS,
        initial_delay: int = INITIAL_DELAY_SECONDS,
    ):
        self._store = store or get_default_store()
        self._check_interval = check_interval
        self._initial_delay = initial_delay
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        # FIX EMAIL-003 (audit P1): rows stuck in 'sending' from a previous
        # crash/kill are invisible to list_due() and would be silently lost.
        # Recover them on startup so the next tick retries delivery.
        try:
            recovered = self._store.recover_stuck_sending(threshold_minutes=10)
            if recovered:
                logger.warning(
                    "ScheduledEmailScheduler: recovered %d row(s) stuck in 'sending' from a previous run",
                    recovered,
                )
        except Exception:
            logger.exception("ScheduledEmailScheduler: recover_stuck_sending failed")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="ScheduledEmailScheduler",
        )
        self._thread.start()
        logger.info("ScheduledEmailScheduler started (poll=%ss)", self._check_interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("ScheduledEmailScheduler stopped")

    def _run(self) -> None:
        if self._stop_event.wait(timeout=self._initial_delay):
            return
        while not self._stop_event.is_set():
            # Issue #577 item 4 — heartbeat at the START of each tick.
            # `record_heartbeat` is contract-bound to never raise, so a
            # DB outage cannot kill the scheduler that this very call
            # is meant to monitor. Tolerance = 2× interval so a single
            # missed tick does not alert.
            from app.services.scheduler_heartbeat import record_heartbeat

            record_heartbeat(
                "scheduled_email_scheduler",
                status="ok",
                expected_interval_seconds=self._check_interval * 2,
            )
            try:
                self._process_due()
            except Exception:
                logger.exception("ScheduledEmailScheduler tick failed")
                record_heartbeat(
                    "scheduled_email_scheduler",
                    status="error",
                    expected_interval_seconds=self._check_interval * 2,
                )
            if self._stop_event.wait(timeout=self._check_interval):
                return

    def _process_due(self) -> None:
        now = datetime.now(timezone.utc)
        due_rows = self._store.list_due(now=now)
        if not due_rows:
            return
        logger.info("ScheduledEmailScheduler: %d due row(s)", len(due_rows))

        # Group by account so we build one provider per account, not per row.
        # Saves OAuth refresh + IMAP connect for batches sharing an account.
        by_account: dict[int, list[dict]] = {}
        for row in due_rows:
            by_account.setdefault(int(row["account_id"]), []).append(row)

        for account_id, rows in by_account.items():
            self._send_for_account(account_id, rows)

    def _send_for_account(self, account_id: int, rows: list[dict]) -> None:
        # Claim all rows up front — anyone we can't claim was already taken
        # by a concurrent tick / process and must be skipped.
        claimed = [r for r in rows if self._store.claim_for_send(r["id"])]
        if not claimed:
            return

        account = _load_account(account_id)
        if account is None:
            for r in claimed:
                self._store.mark_failed(
                    r["id"], error=f"Account {account_id} not found at send time"
                )
            return

        tokens = None
        try:
            from app.infrastructure.cost_manager import set_usage_context

            tokens = set_usage_context(
                account_id=account_id,
                user_id=getattr(account, "user_id", None),
                feature="scheduled_email",
            )
        except Exception:
            tokens = None

        try:
            provider = self._make_provider(account)
        except Exception as e:
            logger.exception("ScheduledEmailScheduler: provider load failed")
            error_msg = f"Provider load: {e}"
            for r in claimed:
                # B-02: a provider that can't be loaded (OAuth refresh blip,
                # network) is transient — revert the claim so the next tick
                # retries instead of terminally failing the scheduled send.
                attempt = int(r.get("attempts") or 0) + 1
                if attempt < MAX_SEND_ATTEMPTS:
                    logger.warning(
                        "ScheduledEmailScheduler: provider load failed, reverting "
                        "claim for %s (attempt %d/%d) — will retry next tick",
                        r["id"][:8], attempt, MAX_SEND_ATTEMPTS,
                    )
                    self._store.revert_claim(r["id"])
                    continue
                self._store.mark_failed(r["id"], error=error_msg)
                try:
                    emit_email_schedule_failed(r["id"], error=error_msg, account_id=account_id)
                except Exception:
                    logger.exception("ScheduledEmailScheduler: ws emit (provider failed) raised")
            try:
                from app.infrastructure.cost_manager import reset_usage_context

                reset_usage_context(tokens)
            except Exception:
                pass
            return

        try:
            for row in claimed:
                self._send_one(provider, account_id, row)
        finally:
            self._safe_disconnect(provider)
            try:
                from app.infrastructure.cost_manager import reset_usage_context

                reset_usage_context(tokens)
            except Exception:
                pass

    def _send_one(self, provider, account_id: int, row: dict) -> None:
        sched_id = row["id"]
        payload = row.get("payload") or {}
        idempotency_key = row.get("idempotency_key") or _idempotency_key_for(sched_id)

        try:
            recovered_message_id = self._resolve_previous_attempt(
                provider,
                row=row,
                idempotency_key=idempotency_key,
            )
            if recovered_message_id:
                self._store.mark_sent(sched_id, message_id=recovered_message_id)
                try:
                    emit_email_sent_scheduled(
                        scheduled_id=sched_id,
                        sent_message_id=recovered_message_id,
                        account_id=account_id,
                    )
                except Exception:
                    logger.exception("ScheduledEmailScheduler: ws emit failed")
                return

            sent_message_id = self._dispatch(
                provider,
                account_id,
                payload,
                idempotency_key=idempotency_key,
            )
        except Exception as e:
            logger.exception(
                "ScheduledEmailScheduler: send raised for %s", sched_id[:8]
            )
            error_msg = str(e)
            attempt = int(row.get("attempts") or 0) + 1
            if _is_transient_send_error(e) and attempt < MAX_SEND_ATTEMPTS:
                # B-02: network/timeout blip — revert to pending so the next
                # tick retries instead of a terminal mark_failed.
                logger.warning(
                    "ScheduledEmailScheduler: transient send failure for %s "
                    "(attempt %d/%d), reverting claim: %s",
                    sched_id[:8], attempt, MAX_SEND_ATTEMPTS, error_msg,
                )
                self._store.revert_claim(sched_id)
                return
            self._store.mark_failed(sched_id, error=error_msg)
            try:
                emit_email_schedule_failed(sched_id, error=error_msg, account_id=account_id)
            except Exception:
                logger.exception("ScheduledEmailScheduler: ws emit (failed) raised")
            return

        if not sent_message_id:
            error_msg = "provider returned no message_id"
            self._store.mark_failed(sched_id, error=error_msg)
            try:
                emit_email_schedule_failed(sched_id, error=error_msg, account_id=account_id)
            except Exception:
                logger.exception("ScheduledEmailScheduler: ws emit (failed) raised")
            return

        self._store.mark_sent(sched_id, message_id=sent_message_id)

        try:
            emit_email_sent_scheduled(
                scheduled_id=sched_id,
                sent_message_id=sent_message_id,
                account_id=account_id,
            )
        except Exception:
            logger.exception("ScheduledEmailScheduler: ws emit failed")

    def _resolve_previous_attempt(
        self,
        provider,
        *,
        row: dict,
        idempotency_key: str,
    ) -> Optional[str]:
        attempts = int(row.get("attempts") or 0)
        if attempts <= 0:
            return None

        lookup = getattr(provider, "find_sent_message_by_idempotency_key", None)
        if not callable(lookup):
            raise RuntimeError(
                "unknown delivery state after previous attempt; "
                "provider cannot verify Sent before retry"
            )

        try:
            return lookup(idempotency_key)
        except Exception as exc:
            raise RuntimeError(f"sent lookup failed before retry: {exc}") from exc

    def _dispatch(
        self,
        provider,
        account_id: int,
        payload: dict,
        *,
        idempotency_key: str,
    ) -> Optional[str]:
        to_list: list[str] = list(payload.get("to") or [])
        cc_list = payload.get("cc") or None
        bcc_list = payload.get("bcc") or None
        subject = payload.get("subject") or ""
        body = payload.get("body") or ""
        is_html = bool(payload.get("is_html", False))
        # Apply the signature the user captured at compose time. The scheduled
        # payload carries `signature_html` + `skip_signature` exactly like the
        # immediate send route (routes_emails send_new). _dispatch previously
        # shipped the raw body, so the signature was silently dropped on every
        # "send later". Mirror the route's signature assembly verbatim.
        signature_html = (payload.get("signature_html") or "").strip()
        if not payload.get("skip_signature") and not signature_html:
            try:
                from app.utils.signature import append_signature
                body = append_signature(body, account_id=account_id)
            except Exception:
                logger.exception("ScheduledEmailScheduler: append_signature failed")
        if signature_html:
            try:
                from app.utils.signature import _inline_signature_images
                signature_html = _inline_signature_images(signature_html)
                body = (
                    f'<div style="font-family:inherit">{body.replace(chr(10), "<br>")}</div>'
                    f'<div><br></div>'
                    f'<div class="agentys-signature" style="margin-top:16px;padding-top:12px;'
                    f'border-top:1px solid #e0e0e0">{signature_html}</div>'
                )
                is_html = True
            except Exception:
                logger.exception("ScheduledEmailScheduler: signature assembly failed")
        attachments = self._materialize_attachments(payload.get("attachments") or [])
        from_name = payload.get("from_name") or None

        if payload.get("reply_to_id"):
            return provider.send_reply_directly(
                to=to_list,
                subject=subject,
                body=body,
                reply_to_id=payload["reply_to_id"],
                cc=cc_list,
                attachments=attachments,
                thread_id=payload.get("thread_id") or None,
                is_html=is_html,
                idempotency_key=idempotency_key,
            )
        return provider.send_new_directly(
            to=to_list,
            subject=subject,
            body=body,
            cc=cc_list,
            bcc=bcc_list,
            attachments=attachments,
            is_html=is_html,
            from_name=from_name,
            idempotency_key=idempotency_key,
        )

    def _materialize_attachments(self, raw):
        if not raw:
            return None
        import base64

        out = []
        for att in raw:
            try:
                data = base64.b64decode(att.get("data", ""))
            except Exception as e:
                # SCHED-001: raise so _send_one marks the row failed rather than
                # silently sending the email without its attachment.
                raise ValueError(
                    f"Pièce jointe corrompue '{att.get('filename', '?')}': {e}"
                ) from e
            out.append(
                (
                    att.get("filename", "file"),
                    data,
                    att.get("content_type", "application/octet-stream"),
                )
            )
        return out or None

    def _make_provider(self, account):
        """FIX EMAIL-001 (audit P0): the previous code called
        `get_email_provider(account)` passing an SQLAlchemy ORM Account
        where the factory expects a provider-type *string* — every
        scheduled send AttributeError'd on `.upper()` and was marked
        failed. Resolve the AccountConfig (multi_accounts) by email and
        use the account-aware factory that handles OAuth / IMAP wiring.

        Extracted as a method so tests can mock it directly without
        touching multi_accounts internals.
        """
        from app.multi_accounts import (
            create_provider_for_account,
            get_account_manager,
        )
        config = get_account_manager().get_account_by_email(account.email)
        if config is None:
            raise RuntimeError(
                f"AccountConfig missing for {account.email} (DB id={account.id})"
            )
        return create_provider_for_account(config)

    def _safe_disconnect(self, provider) -> None:
        if provider is None or not hasattr(provider, "disconnect"):
            return
        try:
            provider.disconnect()
        except Exception:
            pass

    def dispatch_now(self, sched_id: str, *, account_id: int) -> tuple[bool, str | None]:
        """Synchronous override that sends a pending row immediately.

        Returns (success, error_message). The caller is the API layer for the
        "Send Now" button — bypasses the 60s poll so the user gets feedback in
        a few seconds, not up to a minute.
        """
        row = self._store.get_by_id(sched_id, account_id=account_id)
        if row is None:
            return False, "introuvable"
        if row["status"] != "pending":
            return False, f"statut {row['status']}"
        if not self._store.claim_for_send(sched_id):
            return False, "déjà claimé"

        account = _load_account(account_id)
        if account is None:
            err = f"Account {account_id} not found at send time"
            self._store.mark_failed(sched_id, error=err)
            return False, err

        try:
            provider = self._make_provider(account)
        except Exception as e:
            self._store.mark_failed(sched_id, error=f"Provider load: {e}")
            return False, f"Provider load: {e}"

        try:
            self._send_one(provider, account_id, row)
        finally:
            self._safe_disconnect(provider)

        refreshed = self._store.get_by_id(sched_id, account_id=account_id)
        if refreshed and refreshed["status"] == "sent":
            return True, None
        return False, (refreshed or {}).get("error") or "envoi échoué"


# ── Default singleton accessor ────────────────────────────────────────────
# Lets the API layer call dispatch_now() on the same scheduler instance the
# daemon thread is running on, so we share a single store reference.

_default_scheduler: Optional["ScheduledEmailScheduler"] = None
_default_scheduler_lock = threading.Lock()


def set_default_scheduler(scheduler: "ScheduledEmailScheduler") -> None:
    global _default_scheduler
    with _default_scheduler_lock:
        _default_scheduler = scheduler


def get_default_scheduler() -> "ScheduledEmailScheduler":
    global _default_scheduler
    with _default_scheduler_lock:
        if _default_scheduler is None:
            _default_scheduler = ScheduledEmailScheduler()
        return _default_scheduler
