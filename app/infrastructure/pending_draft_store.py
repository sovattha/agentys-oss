# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Implémentation in-memory du store des brouillons en attente.

Pour une utilisation en production, une implémentation persistante
(SQLite, Redis, etc.) serait préférable.
"""

import atexit
import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import app.config as _app_config
from app.config import (
    get_pending_draft_active_retention_days,
    get_pending_draft_terminal_retention_days,
    should_persist_email_content,
)
from app.domain.entities.pending_draft import PendingDraft, PendingDraftStatus
from app.domain.ports import PendingDraftStorePort

logger = logging.getLogger(__name__)

# Audit HIGH-4 (2026-04-25): cap on persisted SENT/REJECTED rows. Older
# entries are evicted at flush time to keep pending_drafts.json bounded.
_TERMINAL_RETENTION_DAYS = 30
_TERMINAL_STATUSES = (PendingDraftStatus.SENT, PendingDraftStatus.REJECTED)
_ACTIVE_RETENTION_DAYS = 30
_ACTIVE_STATUSES = (
    PendingDraftStatus.PENDING,
    PendingDraftStatus.VALIDATED,
    PendingDraftStatus.MODIFIED,
)

# Legacy HOME-relative store path. Before 2026-05-26 the pending-draft store
# persisted here while reminders.json + every other JSON store lived under
# DATA_DIR. A change of HOME / launch context (dev `python run_api.py` vs a
# packaged Tauri sidecar) silently pointed the store at a *different* file,
# orphaning snoozed follow-up drafts whose draft_followup reminders (in
# DATA_DIR/reminders.json) had survived → the "Later" tab rendered empty.
# Kept only as the one-time migration SOURCE; nothing writes here anymore.
_LEGACY_PERSIST_PATH = os.path.join(
    os.path.expanduser("~"), ".agentys", "pending_drafts.json"
)


def _default_persist_path() -> str:
    """Canonical store path, co-located with reminders.json under the
    env-aware DATA_DIR (honours AGENTYS_DATA_DIR, e.g. the Railway volume).

    Reads ``AGENTYS_DATA_DIR`` at call time (not import time) so a runtime
    override / test monkeypatch is always picked up — ``_app_config.DATA_DIR``
    is resolved once at import and would otherwise miss a later override.
    """
    data_dir = os.environ.get("AGENTYS_DATA_DIR")
    if data_dir:
        return os.path.join(data_dir, "pending_drafts.json")
    return str(_app_config.DATA_DIR / "pending_drafts.json")


class InMemoryPendingDraftStore(PendingDraftStorePort):
    """
    Store in-memory pour les brouillons en attente.

    Thread-safe avec persistance optionnelle sur disque.
    """

    def __init__(self, persist_path: Optional[str] = None):
        """
        Initialise le store.

        Args:
            persist_path: Chemin du fichier de persistance (optionnel).
        """
        self._store: dict[str, PendingDraft] = {}
        # Audit C-3 (2026-04-25): index keyed by (account_id, email_id) tuple
        # to prevent IMAP UID collisions across accounts from leaking drafts.
        # account_id is normalized via _normalize_account_id (str|None).
        self._email_id_index: dict[Tuple[Optional[str], str], str] = {}
        self._secure_passwords: dict[str, str] = {}  # draft_id -> generated_password_full (never persisted)
        self._lock = threading.Lock()
        # Audit concurrency C4 (2026-04-24): per-draft critical-section lock.
        # Used to serialize /refine and /validate when both fire close
        # together for the same PendingDraft. Without it, the slower op's
        # write can clobber the faster op's update.
        self._draft_locks: dict[str, threading.Lock] = {}
        # Audit P0-4: per-draft refine-in-progress locks (try_acquire pattern,
        # cf. `try_acquire_refining_lock` ci-dessous).
        self._refining_locks: dict[str, threading.Lock] = {}
        self._draft_locks_master = threading.Lock()
        self._last_disk_mtime: float = 0
        self._dirty = False
        self._save_timer: Optional[threading.Timer] = None
        self._SAVE_DEBOUNCE_SECONDS = 2.0
        # Default to the canonical DATA_DIR location (co-located with
        # reminders.json + every other JSON store). A custom persist_path
        # (tests) stays isolated and never triggers the legacy migration.
        if persist_path is None:
            self._persist_path = _default_persist_path()
            self._maybe_migrate_legacy_store()
        else:
            self._persist_path = persist_path
        self._load_from_disk()
        # Audit MED-2 (2026-04-25): flush pending mutations on interpreter exit
        # so the 2 s debounce window doesn't lose writes during shutdown.
        # Must be after _load_from_disk so the timer is in a consistent state.
        atexit.register(self._atexit_flush)

    @staticmethod
    def _normalize_account_id(value) -> Optional[str]:
        """Normalise un account_id pour la clé d'index (None si vide)."""
        if value is None:
            return None
        s = str(value)
        return s if s else None

    def _index_key(self, draft: PendingDraft) -> Optional[Tuple[Optional[str], str]]:
        """Construit la clé d'index (account_id, email_id) pour un draft.

        Retourne None si email_id est absent (pas de besoin d'indexation).
        """
        if not draft.email_id:
            return None
        return (self._normalize_account_id(draft.account_id), draft.email_id)

    def _atexit_flush(self) -> None:
        """Flush au shutdown du processus (atexit hook)."""
        try:
            self.flush()
        except Exception as e:
            logger.warning(f"atexit flush failed: {e}")

    def get_draft_lock(self, draft_id: str) -> threading.Lock:
        """Return a per-draft lock for serializing /refine vs /validate.

        Audit concurrency C4 fix (2026-04-24).
        Callers should use it as `with store.get_draft_lock(id): ...`.
        """
        with self._draft_locks_master:
            lock = self._draft_locks.get(draft_id)
            if lock is None:
                lock = threading.Lock()
                self._draft_locks[draft_id] = lock
            return lock

    def release_draft_lock(self, draft_id: str) -> None:
        """Best-effort cleanup — drop the per-draft lock when no longer needed
        (e.g. after the draft is sent or rejected). Safe to call on missing
        ids — silently no-ops."""
        with self._draft_locks_master:
            lock = self._draft_locks.get(draft_id)
            if lock is not None and not lock.locked():
                self._draft_locks.pop(draft_id, None)

    # Audit P0-4 (2026-04-25 mother-of-all): empêche deux /refine concurrents
    # sur le même draft. Le `_draft_lock` ci-dessus sérialise refine vs validate
    # sur l'écriture finale, mais l'appel LLM tourne DELIBÉRÉMENT hors lock
    # (cf. routes_drafts.py:594-595) pour ne pas bloquer /validate pendant
    # 30s. Conséquence : si l'utilisateur spamme Ctrl+G, deux appels LLM
    # partent en parallèle, deux `pending_draft.draft_v1` se collident, le
    # dernier-arrivé gagne — et la critique du premier est perdue.
    #
    # Ce verrou non-bloquant `try_acquire` short-circuite avec un 409 dès le
    # 2ème appel concurrent. Le user récupère immédiatement un signal que la
    # première génération est encore en route.
    def try_acquire_refining_lock(self, draft_id: str) -> bool:
        """Tente d'acquérir le verrou refine pour ce draft.

        Retourne True si on l'a obtenu (le caller DOIT appeler
        ``release_refining_lock`` à la fin, en finally). False si un autre
        refine est déjà en cours pour ce draft.
        """
        with self._draft_locks_master:
            lock = self._refining_locks.get(draft_id)
            if lock is None:
                lock = threading.Lock()
                self._refining_locks[draft_id] = lock
        return lock.acquire(blocking=False)

    def release_refining_lock(self, draft_id: str) -> None:
        """Libère le verrou refine. Idempotent — safe à appeler dans un finally
        même si le try_acquire a retourné False (no-op dans ce cas).

        Audit MED-8 (2026-04-25): pop le lock du master dict une fois libéré
        pour empêcher la croissance unbounded (~1 KB par lock × N drafts).
        """
        with self._draft_locks_master:
            lock = self._refining_locks.get(draft_id)
        if lock is None:
            return
        try:
            lock.release()
        except RuntimeError:
            # Le lock n'était pas acquis par ce thread (double release ou
            # release après try_acquire=False) — silencieux par design.
            pass
        with self._draft_locks_master:
            existing = self._refining_locks.get(draft_id)
            if existing is lock and not lock.locked():
                self._refining_locks.pop(draft_id, None)

    def _maybe_migrate_legacy_store(self) -> None:
        """One-time migration from the legacy ``~/.agentys/pending_drafts.json``
        to the canonical DATA_DIR path (cf. module-level ``_LEGACY_PERSIST_PATH``).

        Fires only when the canonical file is absent AND the legacy file is
        present & non-empty — so it runs once, then never again. Copies (not
        moves) so the legacy file stays as a safety net. Best-effort: any
        error is logged and swallowed; a failed migration must never break
        store init (the store just starts empty, exactly as before this fix).
        """
        try:
            if os.path.exists(self._persist_path):
                return  # canonical store already present — nothing to migrate
            legacy = _LEGACY_PERSIST_PATH
            if not legacy:
                return
            if os.path.abspath(legacy) == os.path.abspath(self._persist_path):
                return  # legacy == canonical (HOME == DATA_DIR edge) — no-op
            if not (os.path.exists(legacy) and os.path.getsize(legacy) > 0):
                return  # nothing worth migrating
            dest_dir = os.path.dirname(self._persist_path)
            os.makedirs(dest_dir, exist_ok=True)
            # Atomic publish (mirrors _flush_to_disk): copy into a temp file in
            # the destination dir, then os.replace() onto the canonical path.
            # The store singletons are instantiated lazily without a lock, so a
            # concurrent first-init (or a crash mid-copy) must never leave a
            # half-written canonical file for _load_from_disk to read. Each
            # racing migration does its own atomic replace with identical
            # content, so the worst case is a redundant — never partial — write.
            fd, tmp_path = tempfile.mkstemp(
                prefix=os.path.basename(self._persist_path) + ".",
                suffix=".migrating",
                dir=dest_dir,
            )
            os.close(fd)
            try:
                shutil.copy2(legacy, tmp_path)
                os.replace(tmp_path, self._persist_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            logger.info(
                "Migrated legacy pending-draft store %s → %s",
                legacy,
                self._persist_path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Legacy pending-draft store migration skipped: %s", exc)

    def _load_from_disk(self) -> None:
        """Charge les données depuis le disque si le fichier existe."""
        try:
            if os.path.exists(self._persist_path) and os.path.getsize(self._persist_path) > 0:
                with open(self._persist_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._store.clear()
                    self._email_id_index.clear()
                    for item in data:
                        draft = PendingDraft.from_dict(item)
                        draft = self._to_runtime_draft(draft)
                        self._store[draft.id] = draft
                        key = self._index_key(draft)
                        if key is not None:
                            self._email_id_index[key] = draft.id
                self._last_disk_mtime = os.path.getmtime(self._persist_path)
                logger.info(f"Loaded {len(self._store)} pending drafts from {self._persist_path}")
        except Exception as e:
            logger.warning(f"Could not load pending drafts: {e}")

    def _rebuild_email_id_index(self) -> None:
        """Rebuild the (account_id, email_id) -> draft_id secondary index."""
        self._email_id_index.clear()
        for draft in self._store.values():
            key = self._index_key(draft)
            if key is not None:
                self._email_id_index[key] = draft.id

    def _reload_if_changed(self) -> None:
        """Recharge depuis le disque si le fichier a été modifié par un autre processus."""
        try:
            if os.path.exists(self._persist_path):
                mtime = os.path.getmtime(self._persist_path)
                if mtime != getattr(self, '_last_disk_mtime', 0):
                    self._load_from_disk()
        except Exception:
            pass

    def _save_to_disk(self) -> None:
        """Schedule a debounced save to disk (coalesces rapid mutations)."""
        self._dirty = True
        # Skip cancel+recreate if an existing timer is still pending
        if self._save_timer is not None and self._save_timer.is_alive():
            return
        # Schedule a new save after debounce delay
        self._save_timer = threading.Timer(self._SAVE_DEBOUNCE_SECONDS, self._flush_to_disk)
        self._save_timer.daemon = True
        try:
            self._save_timer.start()
        except RuntimeError as exc:
            self._save_timer = None
            if "interpreter shutdown" in str(exc):
                logger.debug("Pending draft debounce skipped during interpreter shutdown")
                return
            raise

    @staticmethod
    def _is_older_than(ts: str | None, *, days: int) -> bool:
        if not ts:
            return False
        try:
            ref = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        now = datetime.now(ref.tzinfo) if ref.tzinfo else datetime.now()
        return ref < now - timedelta(days=days)

    def _drop_draft_locked(self, draft_id: str) -> bool:
        draft = self._store.get(draft_id)
        if draft is None:
            return False
        key = self._index_key(draft)
        if key is not None and self._email_id_index.get(key) == draft_id:
            self._email_id_index.pop(key, None)
        self._store.pop(draft_id, None)
        self._secure_passwords.pop(draft_id, None)
        with self._draft_locks_master:
            self._draft_locks.pop(draft_id, None)
            self._refining_locks.pop(draft_id, None)
        return True

    def _evict_expired_drafts(self) -> int:
        """Drop expired persisted drafts. Caller must hold ``_lock``.

        Terminal statuses are always bounded. In metadata-only mode, active
        user-facing generated drafts are also bounded because they still contain
        email-derived content.
        """
        terminal_days = get_pending_draft_terminal_retention_days()
        active_days = get_pending_draft_active_retention_days()
        should_evict_active = not should_persist_email_content()
        evicted = 0
        ids_to_drop: list[str] = []
        for draft_id, draft in self._store.items():
            if draft.status in _TERMINAL_STATUSES:
                ref_ts = draft.processed_at or draft.created_at
                if self._is_older_than(ref_ts, days=terminal_days):
                    ids_to_drop.append(draft_id)
                continue
            if should_evict_active and draft.status in _ACTIVE_STATUSES:
                if self._is_older_than(draft.created_at, days=active_days):
                    ids_to_drop.append(draft_id)
        for draft_id in ids_to_drop:
            if self._drop_draft_locked(draft_id):
                evicted += 1
        if evicted:
            logger.info("Évincé %s pending drafts expirés", evicted)
        return evicted

    def _flush_to_disk(self) -> None:
        """Actually write data to disk (called by debounce timer).

        Audit MED-1 (2026-04-25): write atomically via tempfile + os.replace
        pour éviter qu'un crash mid-write (Railway SIGKILL) laisse un fichier
        JSON tronqué.
        """
        with self._lock:
            if not self._dirty:
                return
            self._evict_expired_drafts()
            try:
                os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
                data = [self._to_persisted_dict(draft) for draft in self._store.values()]
                fd, tmp_path = tempfile.mkstemp(
                    prefix=os.path.basename(self._persist_path) + ".",
                    suffix=".tmp",
                    dir=os.path.dirname(self._persist_path),
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                        f.flush()
                        try:
                            os.fsync(f.fileno())
                        except OSError:
                            pass
                    os.replace(tmp_path, self._persist_path)
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
                self._dirty = False
                self._last_disk_mtime = os.path.getmtime(self._persist_path)
            except Exception as e:
                logger.warning(f"Impossible de sauvegarder les pending drafts: {e}")

    @staticmethod
    def _to_runtime_draft(draft: PendingDraft) -> PendingDraft:
        """Apply the storage policy to drafts loaded from legacy files."""
        if not should_persist_email_content():
            draft.email_body = ""
            draft.conversation_history = []
            draft.draft_v1 = ""
            draft.critique = ""
            draft.pipeline_summary = None
        return draft

    @staticmethod
    def _to_persisted_dict(draft: PendingDraft) -> dict:
        """Serialize a PendingDraft for durable storage.

        In metadata-only mode, the disk file keeps the user-facing generated
        draft but drops source email content, intermediate AI artifacts and
        pipeline explanations that can quote or summarize the source message.
        """
        data = draft.to_dict()
        if not should_persist_email_content():
            data["email_body"] = ""
            data["conversation_history"] = []
            data["draft_v1"] = ""
            data["critique"] = ""
            data["pipeline_summary"] = None
        return data

    def _sync_shared_pending_draft(self, draft: PendingDraft) -> None:
        try:
            from app.infrastructure.draft_job_queue import store_shared_pending_draft

            store_shared_pending_draft(
                draft=draft.to_dict(),
                account_id=draft.account_id,
                email_id=draft.email_id,
                draft_id=draft.id,
            )
        except Exception:
            logger.warning("Shared pending draft sync failed", exc_info=True)

    def _delete_shared_pending_draft(self, draft: PendingDraft) -> None:
        try:
            from app.infrastructure.draft_job_queue import delete_shared_pending_draft

            delete_shared_pending_draft(
                draft_id=draft.id,
                account_id=draft.account_id,
                email_id=draft.email_id,
            )
        except Exception:
            logger.warning("Shared pending draft delete failed", exc_info=True)

    def _hydrate_shared_pending_draft(self, data: dict | None) -> Optional[PendingDraft]:
        if not data:
            return None
        try:
            draft = PendingDraft.from_dict(data)
        except Exception:
            logger.warning("Shared pending draft payload invalid", exc_info=True)
            return None

        with self._lock:
            existing = self._store.get(draft.id)
            if existing:
                return existing

            key = self._index_key(draft)
            if key is not None and key in self._email_id_index:
                old_draft_id = self._email_id_index[key]
                if old_draft_id != draft.id:
                    self._store.pop(old_draft_id, None)
            self._store[draft.id] = draft
            if key is not None:
                self._email_id_index[key] = draft.id
            self._save_to_disk()
            logger.info("Pending draft hydraté depuis Redis: %s", draft.id)
            return draft

    def flush(self) -> None:
        """Force an immediate save (for shutdown or critical operations)."""
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
        self._flush_to_disk()

    def prune_expired(self) -> int:
        """Évince immédiatement les brouillons expirés et persiste le résultat."""
        with self._lock:
            self._reload_if_changed()
            removed = self._evict_expired_drafts()
            if removed:
                self._dirty = True
        if removed:
            self.flush()
        return removed

    def add(self, pending_draft: PendingDraft) -> str:
        """Ajoute un brouillon en attente.

        Si un brouillon existe déjà pour le même (account_id, email_id), l'ancien
        est supprimé pour éviter les doublons dans la liste des brouillons.
        """
        with self._lock:
            key = self._index_key(pending_draft)
            # Remove any existing draft for the same (account, email_id) to prevent duplicates
            if key is not None and key in self._email_id_index:
                old_draft_id = self._email_id_index[key]
                if old_draft_id != pending_draft.id and old_draft_id in self._store:
                    del self._store[old_draft_id]
                    logger.debug(
                        f"Ancien brouillon supprimé (key={key}): {old_draft_id}"
                    )
            self._store[pending_draft.id] = pending_draft
            if key is not None:
                self._email_id_index[key] = pending_draft.id
            self._save_to_disk()
            logger.info(f"Pending draft ajouté: {pending_draft.id}")
        self._sync_shared_pending_draft(pending_draft)
        return pending_draft.id

    def get_by_id(self, draft_id: str) -> Optional[PendingDraft]:
        """Récupère un brouillon par son ID."""
        with self._lock:
            self._reload_if_changed()
            draft = self._store.get(draft_id)
        if draft:
            return draft

        try:
            from app.infrastructure.draft_job_queue import get_shared_pending_draft_by_id

            shared = get_shared_pending_draft_by_id(draft_id)
        except Exception:
            logger.warning("Shared pending draft lookup by id failed", exc_info=True)
            shared = None
        return self._hydrate_shared_pending_draft(shared)

    def get_pending(self, limit: int = 50, account_id: Optional[str] = None) -> List[PendingDraft]:
        """Récupère les brouillons en attente de validation.

        Audit P1-008 (2026-04-28): un draft persisté avec ``account_id=None``
        n'appartient à aucun appelant en mode multi-compte. Il est désormais
        EXCLU des résultats scopés. Le filtre permissif précédent
        (``d.account_id is None or ...``) faisait fuiter ces orphelins entre
        comptes.
        """
        with self._lock:
            self._reload_if_changed()
            pending = [
                d for d in self._store.values()
                if d.status == PendingDraftStatus.PENDING
                and (account_id is None or str(d.account_id) == str(account_id))
            ]
            pending.sort(key=lambda x: x.created_at, reverse=True)
            return pending[:limit]

    def get_all(self, limit: int = 100, account_id: Optional[str] = None) -> List[PendingDraft]:
        """Récupère tous les brouillons.

        Audit P1-008 (2026-04-28): voir ``get_pending`` — pas de fallback
        permissif sur ``d.account_id is None`` quand l'appelant scope la
        requête.
        """
        with self._lock:
            self._reload_if_changed()
            all_drafts = [
                d for d in self._store.values()
                if account_id is None or str(d.account_id) == str(account_id)
            ]
            all_drafts.sort(key=lambda x: x.created_at, reverse=True)
            return all_drafts[:limit]

    def update_status(
        self,
        draft_id: str,
        status: PendingDraftStatus,
        gmail_draft_id: Optional[str] = None,
    ) -> bool:
        """Met à jour le statut d'un brouillon."""
        with self._lock:
            draft = self._store.get(draft_id)
            if not draft:
                return False

            # P1-001: block SENT→REJECTED transition so a concurrent cleanup-all
            # can't corrupt a draft whose send just completed.
            if draft.status == PendingDraftStatus.SENT and status == PendingDraftStatus.REJECTED:
                logger.warning(
                    "Blocked SENT→REJECTED transition for draft %s (concurrent cleanup-all)",
                    draft_id,
                )
                return False

            draft.status = status
            draft.processed_at = datetime.now().isoformat()
            if gmail_draft_id:
                draft.gmail_draft_id = gmail_draft_id

            self._save_to_disk()
            logger.info(f"Pending draft {draft_id} mis à jour: {status.value}")
        if status in _TERMINAL_STATUSES:
            self._delete_shared_pending_draft(draft)
        else:
            self._sync_shared_pending_draft(draft)
        return True

    def update_content(
        self,
        draft_id: str,
        draft_subject: str,
        draft_body: str,
    ) -> bool:
        """Met à jour le contenu d'un brouillon."""
        with self._lock:
            draft = self._store.get(draft_id)
            if not draft:
                return False

            draft.draft_subject = draft_subject
            draft.draft_body = draft_body

            self._save_to_disk()
        self._sync_shared_pending_draft(draft)
        return True

    def update_account_info(self, draft_id: str, account_info: dict) -> bool:
        """Met à jour les informations de compte d'un brouillon."""
        with self._lock:
            draft = self._store.get(draft_id)
            if not draft:
                return False
            draft.account_info = account_info
            self._save_to_disk()
            return True

    def store_secure_password(self, draft_id: str, password: str) -> None:
        """Store generated password in memory (never persisted to disk)."""
        with self._lock:
            self._secure_passwords[draft_id] = password

    def get_secure_password(self, draft_id: str) -> Optional[str]:
        """Retrieve generated password from memory."""
        with self._lock:
            return self._secure_passwords.get(draft_id)

    def clear_secure_password(self, draft_id: str) -> None:
        """Clear generated password from memory."""
        with self._lock:
            self._secure_passwords.pop(draft_id, None)

    def delete(self, draft_id: str) -> bool:
        """Supprime un brouillon. Retourne True même si déjà absent (idempotent)."""
        with self._lock:
            self._reload_if_changed()
            if draft_id not in self._store:
                return True

            draft = self._store[draft_id]
            key = self._index_key(draft)
            if key is not None and self._email_id_index.get(key) == draft_id:
                del self._email_id_index[key]
            del self._store[draft_id]
            self._secure_passwords.pop(draft_id, None)
            # Audit MED-8 (2026-04-25): purge per-draft locks lors du delete
            # pour empêcher la croissance unbounded de _refining_locks /
            # _draft_locks (~1 KB par lock × N drafts long-vivants).
            with self._draft_locks_master:
                self._draft_locks.pop(draft_id, None)
                self._refining_locks.pop(draft_id, None)
            self._save_to_disk()
            logger.info(f"Pending draft supprimé: {draft_id}")
        self._delete_shared_pending_draft(draft)
        return True

    def delete_by_account(self, account_id: str | int | None) -> int:
        """Supprime tous les brouillons associés à un compte."""
        normalized = self._normalize_account_id(account_id)
        removed = 0
        removed_drafts: list[PendingDraft] = []
        with self._lock:
            self._reload_if_changed()
            draft_ids = [
                draft_id for draft_id, draft in self._store.items()
                if self._normalize_account_id(draft.account_id) == normalized
            ]
            for draft_id in draft_ids:
                draft = self._store.get(draft_id)
                if self._drop_draft_locked(draft_id):
                    removed += 1
                    if draft:
                        removed_drafts.append(draft)
            if removed:
                self._dirty = True
        if removed:
            self.flush()
            for draft in removed_drafts:
                self._delete_shared_pending_draft(draft)
            logger.info(
                "Pending drafts supprimés pour account_id=%s: %s",
                normalized,
                removed,
            )
        return removed

    def count_pending(self) -> int:
        """Compte les brouillons en attente."""
        with self._lock:
            self._reload_if_changed()
            return sum(
                1 for d in self._store.values()
                if d.status == PendingDraftStatus.PENDING
            )

    def get_unsent(self, limit: int = 50, account_id: Optional[str] = None) -> List[PendingDraft]:
        """
        Récupère les brouillons non envoyés (pour badge "Draft prêt").

        Inclut PENDING, VALIDATED et MODIFIED - le badge reste affiché
        tant que l'utilisateur n'a pas envoyé la réponse.

        Returns:
            Liste des brouillons non envoyés triés par date.
        """
        with self._lock:
            self._reload_if_changed()
            unsent_statuses = (
                PendingDraftStatus.PENDING,
                PendingDraftStatus.VALIDATED,
                PendingDraftStatus.MODIFIED,
            )
            unsent = [
                d for d in self._store.values()
                if d.status in unsent_statuses
                and (account_id is None or str(d.account_id) == str(account_id))
            ]
            unsent.sort(key=lambda x: x.created_at, reverse=True)
            return unsent[:limit]

    def _lookup_by_email_id(
        self,
        email_id: str,
        account_id: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve a draft_id from (account_id, email_id) with safe fallback.

        Audit C-3 (2026-04-25): account_id-aware index lookup. If account_id
        is supplied we require an exact tuple match — this is the safe path
        for any caller in possession of the JWT-resolved account_id. If
        account_id is None the lookup is restricted to drafts that were
        also stored with account_id=None (single-tenant legacy data); we
        never scan across accounts. See P1-008 audit (2026-04-28).
        """
        # Audit P1-008 (2026-04-28): always look up via the exact
        # (account_id, email_id) index key — never scan across accounts.
        # The previous code had an "if exactly one candidate, return it"
        # fallback when account_id was None; in single-account dev installs
        # everything is "exactly one", so unscoped callers happily picked
        # up another tenant's draft. Direct index lookup keeps legitimate
        # account_id=None matches (single-tenant legacy) while making
        # cross-tenant leaks impossible (a None-scoped lookup returns only
        # drafts that were also stored with account_id=None).
        normalized = self._normalize_account_id(account_id)
        return self._email_id_index.get((normalized, email_id))

    def get_by_email_id_including_rejected(
        self,
        email_id: str,
        account_id: Optional[str] = None,
    ) -> Optional[PendingDraft]:
        """Récupère un brouillon par email_id, y compris REJECTED.

        Utilisé par le daemon pour bloquer la régénération d'un draft rejeté par l'utilisateur.
        ``account_id`` est facultatif pour la rétro-compat mais devrait être
        passé par tout caller authentifié (cf. C-3 audit 2026-04-25).
        """
        from app.domain.entities.pending_draft import PendingDraftStatus
        with self._lock:
            self._reload_if_changed()
            draft_id = self._lookup_by_email_id(email_id, account_id)
            if draft_id:
                draft = self._store.get(draft_id)
                # Seuls les drafts SENT ne bloquent pas la régénération
                if draft and draft.status != PendingDraftStatus.SENT:
                    return draft
            return None

    def get_by_email_id(
        self,
        email_id: str,
        account_id: Optional[str] = None,
    ) -> Optional[PendingDraft]:
        """Récupère un brouillon actif par l'ID de l'email source (exclut rejected/sent/validated).

        Uses O(1) secondary index instead of O(n) linear scan.

        Audit C-3 (2026-04-25): ``account_id`` désormais facultatif mais
        FORTEMENT recommandé pour éviter les collisions IMAP UID entre
        comptes. Sans account_id, on ne retourne un hit que si un SEUL
        candidat existe pour cet email_id.
        """
        from app.domain.entities.pending_draft import PendingDraftStatus
        excluded = {PendingDraftStatus.REJECTED, PendingDraftStatus.SENT, PendingDraftStatus.VALIDATED}
        with self._lock:
            self._reload_if_changed()
            draft_id = self._lookup_by_email_id(email_id, account_id)
            if draft_id:
                draft = self._store.get(draft_id)
                if draft and draft.status not in excluded:
                    return draft

        try:
            from app.infrastructure.draft_job_queue import get_shared_pending_draft_by_email

            shared = get_shared_pending_draft_by_email(
                account_id=account_id,
                email_id=email_id,
            )
        except Exception:
            logger.warning("Shared pending draft lookup by email failed", exc_info=True)
            shared = None

        draft = self._hydrate_shared_pending_draft(shared)
        if not draft or draft.status in excluded:
            return None
        if account_id is not None and self._normalize_account_id(
            draft.account_id
        ) != self._normalize_account_id(account_id):
            return None
        return draft


# Singleton pour l'application
_pending_draft_store: Optional[InMemoryPendingDraftStore] = None


def get_pending_draft_store() -> InMemoryPendingDraftStore:
    """Retourne le singleton du store."""
    global _pending_draft_store
    if _pending_draft_store is None:
        _pending_draft_store = InMemoryPendingDraftStore()
    return _pending_draft_store
