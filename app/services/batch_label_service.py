# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Post-onboarding batch labeling via Anthropic Message Batches API.

Audit 2026-05-06: when a user finishes onboarding, the rule sweep
(``OnboardingManager._apply_rules_from_db``) labels emails that match
the user's learned rules, but emails that don't match any rule fall
through to ``LabelEmailUseCase`` which fires a Haiku classification per
email. For ~500-1000 emails this is non-realtime work that fits the
Batch API perfectly: 50 % Anthropic discount, 24 h SLA (latency we
don't care about — labels surface on the next sync).

This service is opt-in via env ``POST_ONBOARDING_BATCH_LABEL=true``
because the integration touches user-visible state and we want a clean
rollback knob.

Flow:
  1. Onboarding completes → manager calls
     ``submit_post_onboarding_label_batch(account_id, emails)``.
  2. We build one ``BatchRequest`` per email with a tight Haiku prompt
     and a custom_id of ``label::<email_id>::<account_id>``.
  3. ``ClaudeBatchAdapter.submit_batch`` returns a batch_id; we record
     the (batch_id, account_id, count) tuple in a small SQLite table
     so a poller can find it later.
  4. A periodic poller (Hetzner cron, see scripts/poll_batch_labels.py
     in a follow-up) calls ``poll_and_apply_results(batch_id)`` which
     fetches results, parses each completion JSON, and writes label
     assignments to the per-account ``label_store``.

Failure modes:
  - submit_batch returns None (network / auth) → log + return None;
    onboarding completes without batch (legacy per-email path resumes).
  - poll returns "in_progress" → the poller exits, comes back later.
  - poll returns "errored" / "expired" → log + drop; emails will be
    classified one-by-one on the next sync.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Tracking table — separate from the main batch_queue (which is per-draft).
# ----------------------------------------------------------------------------
_TABLE_NAME = "post_onboarding_batches"
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        from app.config import DATA_DIR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = str(DATA_DIR / "batch_label_jobs.db")
        c = sqlite3.connect(path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
                batch_id     TEXT PRIMARY KEY,
                account_id   INTEGER NOT NULL,
                request_count INTEGER NOT NULL,
                status       TEXT NOT NULL DEFAULT 'in_progress',
                applied_count INTEGER NOT NULL DEFAULT 0,
                submitted_at TEXT NOT NULL,
                completed_at TEXT,
                error        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pob_status ON {_TABLE_NAME}(status);
            CREATE INDEX IF NOT EXISTS idx_pob_account ON {_TABLE_NAME}(account_id);
            """
        )
        c.commit()
        _local.conn = c
    return _local.conn


def is_enabled() -> bool:
    """Opt-in via env. Default OFF — operator must flip to enable."""
    return os.environ.get("POST_ONBOARDING_BATCH_LABEL", "").strip().lower() in (
        "1", "true", "yes", "on"
    )


# ----------------------------------------------------------------------------
# Build labeling prompts (kept tight — Haiku-friendly)
# ----------------------------------------------------------------------------
_LABEL_SYSTEM_PROMPT = (
    "Tu classes un email entrant dans EXACTEMENT UNE catégorie : "
    "Action (réponse demandée), Waiting (en attente de quelqu'un), "
    "FYI (info pour mémoire), Noise (notifications, marketing, bruit). "
    "Réponds UNIQUEMENT avec un JSON {\"label\": \"…\", \"confidence\": 0.0-1.0}."
)


def _build_user_prompt(sender: str, subject: str, body: str) -> str:
    body_short = (body or "")[:1500]
    return (
        f"De: {sender}\n"
        f"Sujet: {subject}\n\n"
        f"{body_short}\n\n"
        "Catégorie + confidence ?"
    )


def _custom_id_for(email_id: str, account_id: int) -> str:
    return f"label::{email_id}::{account_id}"


def _parse_custom_id(custom_id: str) -> tuple[Optional[str], Optional[int]]:
    parts = custom_id.split("::")
    if len(parts) != 3 or parts[0] != "label":
        return None, None
    try:
        return parts[1], int(parts[2])
    except (TypeError, ValueError):
        return parts[1], None


# ----------------------------------------------------------------------------
# Submit
# ----------------------------------------------------------------------------
def submit_post_onboarding_label_batch(
    account_id: int,
    emails: Iterable[dict],
) -> Optional[str]:
    """Submit a batch of (email_id, sender, subject, body) for labeling.

    Args:
        account_id: per-account scope.
        emails: iterable of dicts with keys ``email_id``, ``sender``,
            ``subject``, ``body``. Anything missing skips that email.

    Returns:
        Anthropic batch_id on success, None on no-op (disabled / empty
        / submit failed). Caller should not block on the return value —
        this is fire-and-forget; the poller picks up the work later.
    """
    if not is_enabled():
        logger.info("[batch_label] feature disabled (POST_ONBOARDING_BATCH_LABEL)")
        return None
    if not account_id or account_id <= 0:
        return None

    try:
        from app.adapters.llm.claude_batch_adapter import ClaudeBatchAdapter, BatchRequest
    except Exception as e:
        logger.warning("[batch_label] ClaudeBatchAdapter unavailable: %s", e)
        return None

    # Always submit Haiku — labeling is dirt-cheap on the cheap model.
    # Lookup model name via Container so a single env var flip reflects.
    try:
        from app.infrastructure.container import get_container
        from app.config import CLAUDE_MODEL_LABEL
        llm_label = get_container().llm_onboarding_label
        model = getattr(llm_label, "model", "") or CLAUDE_MODEL_LABEL
    except Exception:
        from app.config import CLAUDE_MODEL_LABEL
        model = CLAUDE_MODEL_LABEL

    requests: list[BatchRequest] = []
    for e in emails:
        eid = (e or {}).get("email_id")
        if not eid:
            continue
        sender = (e.get("sender") or "")
        subject = (e.get("subject") or "")
        body = (e.get("body") or "")
        if not sender and not subject and not body:
            continue
        requests.append(BatchRequest(
            custom_id=_custom_id_for(str(eid), account_id),
            model=model,
            system_prompt=_LABEL_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(sender, subject, body),
            max_tokens=64,
            temperature=0.0,
        ))

    if not requests:
        logger.info("[batch_label] account=%d: no requests built", account_id)
        return None

    try:
        adapter = ClaudeBatchAdapter()
        batch_id = adapter.submit_batch(requests)
    except Exception as e:
        logger.warning("[batch_label] submit_batch failed for account=%d: %s", account_id, e)
        return None

    if not batch_id:
        return None

    try:
        conn = _get_conn()
        conn.execute(
            f"INSERT INTO {_TABLE_NAME} "
            "(batch_id, account_id, request_count, status, submitted_at) "
            "VALUES (?, ?, ?, 'in_progress', ?)",
            (
                batch_id, int(account_id), len(requests),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning("[batch_label] tracking insert failed: %s", e)

    logger.info(
        "[batch_label] submitted batch_id=%s account=%d count=%d (50%% discount)",
        batch_id, account_id, len(requests),
    )
    return batch_id


# ----------------------------------------------------------------------------
# Poll + apply
# ----------------------------------------------------------------------------
def poll_and_apply_results(batch_id: str) -> dict:
    """Poll one batch; if completed, apply label assignments.

    Returns a small dict with ``status`` and counters for the admin
    dashboard / tests. Idempotent — re-applying a completed batch is a
    no-op because the row's status flips to ``applied``.
    """
    out = {"batch_id": batch_id, "status": "unknown", "applied": 0}
    try:
        from app.adapters.llm.claude_batch_adapter import ClaudeBatchAdapter
        adapter = ClaudeBatchAdapter()
        status = adapter.get_batch_status(batch_id)
    except Exception as e:
        out["status"] = "poll_error"
        out["error"] = str(e)
        return out

    out["status"] = (getattr(status, "processing_status", None)
                     or getattr(status, "status", None) or "unknown")
    if out["status"] not in ("ended", "completed", "succeeded"):
        return out

    # Batch ended — fetch results and apply.
    try:
        results = list(adapter.fetch_batch_results(batch_id))
    except Exception as e:
        out["status"] = "fetch_error"
        out["error"] = str(e)
        return out

    applied = 0
    failed = 0
    skipped = 0
    for r in results:
        if getattr(r, "status", "") not in ("succeeded",):
            # B-05: count non-succeeded LLM results instead of dropping them
            # silently — surfaced in the aggregate warning below.
            skipped += 1
            continue
        eid, account_id = _parse_custom_id(getattr(r, "custom_id", "") or "")
        if not eid or not account_id:
            continue
        try:
            payload = json.loads(getattr(r, "content", "") or "{}")
        except Exception:
            continue
        label = (payload.get("label") or "").strip()
        try:
            confidence = float(payload.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if not label or label not in ("Action", "Waiting", "FYI", "Noise"):
            continue
        try:
            from app.infrastructure.container import get_container
            from app.domain.entities.email_labels import LabelAssignment
            store = get_container().get_label_store(account_id=account_id)
            existing = store.get_assignment(eid)
            if existing and existing.assigned_by == "user":
                # Never overwrite a manual label.
                continue
            if not existing:
                existing = LabelAssignment(email_id=eid, assigned_by="batch_label")
            existing.set_default_label(label, confidence, "batch-label (post-onboarding)")
            existing._rebuild_labels()
            store.save_assignment(existing)
            applied += 1
        except Exception as e:
            failed += 1
            logger.debug("[batch_label] apply failed for email=%s: %s", eid, e)

    # B-05 (audit 2026-06-11): the batch stays 'applied' (no state-machine
    # change) but the per-email losses are no longer invisible — aggregate
    # warning + the `error` column feeds get_batch_summary's `errored`.
    error_note = None
    if failed or skipped:
        error_note = f"failed={failed} skipped={skipped}"
        logger.warning(
            "[batch_label] partial apply for batch_id=%s: applied=%d failed=%d skipped=%d",
            batch_id, applied, failed, skipped,
        )

    try:
        conn = _get_conn()
        conn.execute(
            f"UPDATE {_TABLE_NAME} SET status='applied', applied_count=?, completed_at=?, error=? "
            "WHERE batch_id=?",
            (applied, datetime.now(timezone.utc).isoformat(), error_note, batch_id),
        )
        conn.commit()
    except Exception as e:
        logger.warning("[batch_label] tracking update failed: %s", e)

    out["applied"] = applied
    out["failed"] = failed
    out["skipped"] = skipped
    out["status"] = "applied"
    logger.info("[batch_label] applied %d labels from batch_id=%s", applied, batch_id)
    return out


def list_pending_batches() -> list[dict]:
    """Snapshot of in_progress batches for the admin dashboard."""
    try:
        conn = _get_conn()
        rows = conn.execute(
            f"SELECT batch_id, account_id, request_count, status, "
            "applied_count, submitted_at FROM "
            f"{_TABLE_NAME} WHERE status NOT IN ('applied') "
            "ORDER BY submitted_at DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_batch_summary(account_id: int) -> dict:
    """Per-account summary for the admin dashboard."""
    try:
        conn = _get_conn()
        rows = conn.execute(
            f"SELECT status, COUNT(*) as cnt, COALESCE(SUM(applied_count), 0) as applied "
            f"FROM {_TABLE_NAME} WHERE account_id=? GROUP BY status",
            (int(account_id),),
        ).fetchall()
        out = {"in_progress": 0, "applied": 0, "errored": 0, "total_applied": 0}
        for r in rows:
            d = dict(r)
            s = d.get("status") or "unknown"
            if s in out:
                out[s] = int(d.get("cnt") or 0)
            out["total_applied"] += int(d.get("applied") or 0)
        # B-05: no code path ever writes status='errored', so the field was
        # always 0. Count batches that recorded apply errors (error column
        # set by poll_and_apply_results) — their status stays 'applied'.
        err_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM {_TABLE_NAME} "
            "WHERE account_id=? AND error IS NOT NULL",
            (int(account_id),),
        ).fetchone()
        if err_row is not None:
            out["errored"] = int(dict(err_row).get("cnt") or 0)
        return out
    except Exception:
        return {"in_progress": 0, "applied": 0, "errored": 0, "total_applied": 0}
