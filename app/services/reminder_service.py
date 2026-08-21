# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Service de rappels pour Agentys.

Persiste les rappels follow-up dans data/reminders.json et émet
une notification Windows desktop quand l'heure est atteinte.
"""

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

# Co-located with the pending-draft store under the env-aware DATA_DIR
# (honours AGENTYS_DATA_DIR, e.g. the Railway volume). Previously hard-coded to
# PROJECT_ROOT/data, which ignored any AGENTYS_DATA_DIR override and — paired
# with the old HOME-relative pending-draft store — let reminders and their
# drafts drift into different roots, orphaning snoozed follow-ups. When
# AGENTYS_DATA_DIR is unset, DATA_DIR defaults to PROJECT_ROOT/data, so this
# is a no-op locally. See audit 2026-05-26.
_REMINDERS_FILE = DATA_DIR / "reminders.json"
_lock = threading.Lock()

# Parsed-snapshot cache for _read(). /api/pending-drafts (polled by 4 frontend
# hooks) and /api/pending-drafts/snoozed call _read() on every request, which
# used to re-read + json.loads the whole file each time while holding _lock —
# contending with the reminder/followup background writers that fsync the same
# file. We now re-parse only when the file's (mtime_ns, size) signature changes.
# Invariant: every _read()/_write() runs under _lock (verified for all call
# sites), so this cache needs no separate lock. _write() resets it so a
# coarse-mtime filesystem cannot serve a stale snapshot after a same-tick
# rewrite.
_read_cache_sig: tuple[int, int] | None = None
_read_cache_data: list[dict] = []

# Audit regressions (2026-05-17 batch4) F-02: cap re-attempts so a permanently
# broken notifier layer (missing osascript, no notify-send, locked DLL) does
# not retry every 60s forever. After this many failures, log error + mark
# notified to release the entry. 5 ≈ 5 minutes of warnings before quarantine,
# which is enough signal for ops without log spam.
_MAX_NOTIFY_ATTEMPTS = 5


# ─── Persistance ─────────────────────────────────────────────────────────────

def _read() -> list[dict]:
    """Read reminders from disk, reusing the cached parse when the file is
    unchanged.

    Returns a fresh per-call copy so callers can mutate the returned list
    (append a reminder, flip ``notified``, bump ``notify_attempts``) without
    corrupting the shared cached snapshot. Reminder dicts are flat (scalar
    values only), so a shallow ``dict(r)`` per row is a sufficient deep copy.
    """
    global _read_cache_sig, _read_cache_data
    try:
        st = _REMINDERS_FILE.stat()
    except (FileNotFoundError, OSError):
        _read_cache_sig = None
        _read_cache_data = []
        return []
    sig = (st.st_mtime_ns, st.st_size)
    if _read_cache_sig is not None and sig == _read_cache_sig:
        return [dict(r) for r in _read_cache_data]
    try:
        data = json.loads(_REMINDERS_FILE.read_text(encoding="utf-8"))
        # reminders.json is always a JSON array (written by _write); guard
        # against a hand-edited object/scalar so callers that iterate rows
        # never crash on non-dict items.
        parsed = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
        _read_cache_data = parsed
        _read_cache_sig = sig
        return [dict(r) for r in parsed]
    except Exception as e:
        # Stability (audit 2026-05-19 CONC-DATA-01): a truncated/half-written
        # reminders.json (crash/SIGKILL/redeploy mid-write) used to be swallowed
        # silently, wiping every reminder with no recovery path. Quarantine the
        # corrupt file (mirrors calendar.py followups.json handling) so the loss
        # is loud and the bad bytes survive for forensics instead of being
        # overwritten by the next _write.
        logger.error("reminders.json unreadable (%s) — quarantining corrupt file", e)
        try:
            quarantine = f"{_REMINDERS_FILE}.corrupt-{int(time.time())}"
            os.replace(_REMINDERS_FILE, quarantine)
            logger.warning("Corrupt reminders.json moved to %s", quarantine)
        except OSError as rename_exc:
            logger.warning("Could not quarantine corrupt reminders.json: %s", rename_exc)
        _read_cache_sig = None
        _read_cache_data = []
        return []


def _write(reminders: list[dict]) -> None:
    """Write atomically (temp file + fsync + os.replace) so a crash mid-write
    can never truncate the live file (audit 2026-05-19 CONC-DATA-01)."""
    global _read_cache_sig, _read_cache_data
    _REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = f"{_REMINDERS_FILE}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(reminders, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # tmpfs and some filesystems don't support fsync — best effort.
                pass
        os.replace(tmp_path, _REMINDERS_FILE)
        # Invalidate the read cache: the next _read() must re-stat + re-parse.
        # mtime alone is insufficient on coarse-resolution filesystems where a
        # rewrite within the same tick keeps the old (mtime_ns, size) signature.
        _read_cache_sig = None
        _read_cache_data = []
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ─── API publique ─────────────────────────────────────────────────────────────

def add_reminder(
    email_id: str,
    subject: str,
    reminder_date_iso: str,
    account_id: int | None = None,
    reminder_type: str = "snooze",
) -> str:
    """Ajoute un rappel et retourne son id.

    AUTHZ-VULN-05 (Shannon pentest 2026-05-05, issue #557): account_id est
    désormais persisté pour scoper les lectures et les suppressions par
    tenant. Les anciennes entrées (sans account_id) sont quarantainées —
    invisibles à tous les utilisateurs jusqu'à backfill manuel.

    ``reminder_type`` differentiates downstream consumers:
      - ``"snooze"`` (default, legacy) — a snoozed inbox email
      - ``"followup"`` — a reminder to look at a sent thread again
      - ``"draft_followup"`` — gates a PendingDraft (``email_id`` is a draft
        id, not a provider email id) until the wake date; consumed by
        ``/api/drafts`` to hide the draft, and by ``SnoozedView`` to show
        it under "Later" with a Snoozed badge.
    """
    reminder_id = str(uuid.uuid4())
    entry = {
        "id": reminder_id,
        "email_id": email_id,
        "subject": subject,
        "reminder_date": reminder_date_iso,
        "notified": False,
        "account_id": account_id,
        "type": reminder_type,
    }
    with _lock:
        reminders = _read()
        # Remplace un éventuel rappel existant pour le même
        # (account, email, type). Avant le fix #557, le filtre était global →
        # un user pouvait écraser le rappel d'un autre user pour le même
        # email_id. Le scope par `type` (ajouté 2026-05 avec l'action
        # create_reminder) évite qu'un rappel "deadline" écrase silencieusement
        # un "snooze" manuel posé sur le même email — les deux intentions
        # coexistent ; ré-poser le MÊME type remplace toujours (re-snooze,
        # ré-exécution d'une Quick Step).
        reminders = [
            r for r in reminders
            if not (
                r.get("email_id") == email_id
                and r.get("account_id") == account_id
                and r.get("type", "snooze") == reminder_type
            )
        ]
        reminders.append(entry)
        _write(reminders)
    logger.info("[REMINDER] Rappel créé : %s → %s", email_id, reminder_date_iso)
    return reminder_id


def get_all_pending(account_id: int | None = None) -> list[dict]:
    """Retourne tous les rappels non encore notifiés (filtrés par account_id si fourni).

    AUTHZ-VULN-05 (issue #557): si account_id est None, retourne tous les
    rappels (pour compat avec le scheduler interne `check_and_notify`).
    Pour les appels API, TOUJOURS passer account_id pour scoper.
    """
    with _lock:
        rows = [r for r in _read() if not r.get("notified", False)]
    if account_id is None:
        return rows
    return [r for r in rows if r.get("account_id") == account_id]


def dismiss_reminder(reminder_id: str, account_id: int | None = None) -> bool:
    """Supprime un rappel par id, optionnellement scopé par account_id.

    AUTHZ-VULN-05 (issue #557): pré-fix, tout user authentifié pouvait
    supprimer le rappel d'un autre user en devinant son uuid. Désormais
    on refuse la suppression si l'account_id ne correspond pas.

    Returns:
        True si le rappel a été supprimé, False sinon (introuvable ou
        appartenant à un autre tenant).
    """
    with _lock:
        reminders = _read()
        target = next((r for r in reminders if r.get("id") == reminder_id), None)
        if target is None:
            return False
        # Quarantaine NULL : si l'entrée n'a pas d'account_id (legacy), seul
        # le scheduler interne (account_id=None) peut la supprimer.
        if account_id is not None and target.get("account_id") != account_id:
            return False
        new_reminders = [r for r in reminders if r.get("id") != reminder_id]
        _write(new_reminders)
        return True


def _mark_notified(reminder_id: str) -> None:
    with _lock:
        reminders = _read()
        for r in reminders:
            if r.get("id") == reminder_id:
                r["notified"] = True
        _write(reminders)


def _increment_notify_attempts(reminder_id: str) -> int:
    """F-02 (audit regressions 2026-05-17): track per-reminder failed attempts
    so ``check_and_notify`` can quarantine after ``_MAX_NOTIFY_ATTEMPTS``.
    Returns the new attempt count for the caller's gate.
    """
    new_count = 0
    with _lock:
        reminders = _read()
        for r in reminders:
            if r.get("id") == reminder_id:
                new_count = int(r.get("notify_attempts", 0)) + 1
                r["notify_attempts"] = new_count
                break
        _write(reminders)
    return new_count


def get_draft_followup_entry(
    draft_id: str,
    account_id: int | None = None,
) -> dict | None:
    """Return the active draft_followup reminder for ``draft_id``, or None.

    Used by ``/api/drafts`` to hide drafts whose snooze hasn't elapsed, and
    by the wake-time sweep to find drafts ready for the
    ``get_thread_messages`` reply check. ``account_id`` scopes the lookup
    per tenant — pass it whenever you have it.
    """
    with _lock:
        rows = _read()
    for r in rows:
        if r.get("type") != "draft_followup":
            continue
        if r.get("email_id") != draft_id:
            continue
        if account_id is not None and r.get("account_id") != account_id:
            continue
        return r
    return None


def list_draft_followups(account_id: int | None = None) -> list[dict]:
    """Return all draft_followup reminders for ``account_id``.

    Used by the drafts list to compute the set of snoozed draft ids in one
    pass instead of N per-draft lookups. Includes both still-sleeping
    (reminder_date > now) and already-woken (reminder_date <= now) entries
    — the caller decides what to do with each.
    """
    with _lock:
        rows = _read()
    out: list[dict] = []
    for r in rows:
        if r.get("type") != "draft_followup":
            continue
        if account_id is not None and r.get("account_id") != account_id:
            continue
        out.append(r)
    return out


def check_and_notify() -> None:
    """Vérifie les rappels échus et émet une notification desktop.

    ``draft_followup`` entries are intentionally skipped here: their wake
    surface is the drafts list, not a desktop toast, AND their wake
    transition is owned exclusively by the wake-time sweep
    (``sweep_woken_draft_followups``). That sweep does a
    ``get_thread_messages`` reply check, then either deletes the draft
    (recipient replied) or flips ``notified=True`` to surface it (no reply).
    We must NOT mark them notified here: doing so surfaced the draft via
    ``/api/drafts`` with no reply check AND starved the sweep (it
    early-continues on ``notified=True``), so delete-on-reply / inbox-surface
    / the "Follow up" label never fired. Leaving them untouched costs only a
    no-op skip each tick (F-01, 2026-05-21).
    """
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        reminders = _read()
        due = [
            r for r in reminders
            if not r.get("notified", False) and r.get("reminder_date", "") <= now
        ]

    for r in due:
        if r.get("type") == "draft_followup":
            # F-01 (2026-05-21): the wake-time sweep owns this reminder type.
            # Marking it notified here would (a) surface the draft via
            # /api/drafts with no reply check and (b) make the sweep skip it
            # (it early-continues on notified=True), killing delete-on-reply,
            # inbox-surface and the "Follow up" label. No toast for these — so
            # just skip and leave notified=False for the sweep to claim.
            continue
        subject = r.get("subject", "Email sans objet")[:60]
        # Audit regressions (2026-05-17 batch4) F-02: B-05's earlier fix only
        # caught raises and treated `notify.send` returning False as success.
        # All 4 platform notifiers (Mac/Linux/Windows/Fallback) catch their
        # internal subprocess errors and `return False` — i.e. the exact
        # silent-failure mode the B-05 comment claimed to fix never reached
        # the except branch. Now: capture the bool, only mark notified on
        # True, and increment a per-reminder attempt counter so a perma-
        # broken notifier doesn't re-fire every 60s forever.
        sent = False
        try:
            from app.infrastructure.notifications import notify, NotificationType
            sent = bool(notify.send(
                title="Agentys — Rappel",
                message=f"Rappel : {subject}",
                notification_type=NotificationType.INFO,
                sound=True,
            ))
        except Exception as e:
            logger.warning("[REMINDER] Notification raised (will retry next tick): %s", e)
            attempts = _increment_notify_attempts(r["id"])
            if attempts >= _MAX_NOTIFY_ATTEMPTS:
                logger.error(
                    "[REMINDER] Quarantining reminder %s after %d failed attempts (raise path)",
                    r.get("id"), attempts,
                )
                _mark_notified(r["id"])
            continue
        if not sent:
            logger.warning(
                "[REMINDER] notify.send returned False for %s (will retry next tick)",
                subject,
            )
            attempts = _increment_notify_attempts(r["id"])
            if attempts >= _MAX_NOTIFY_ATTEMPTS:
                logger.error(
                    "[REMINDER] Quarantining reminder %s after %d failed attempts (False return)",
                    r.get("id"), attempts,
                )
                _mark_notified(r["id"])
            continue
        logger.info("[REMINDER] Notification envoyée : %s", subject)
        _mark_notified(r["id"])
