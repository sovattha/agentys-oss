# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""STT keyterms — boost the speech-to-text recognition of proper nouns
(project names, custom vocabulary) per account.

Two sources merged at read time :

- **Auto** : `EmailLabel.name` for labels with `is_project=True`. Read from
  the per-account `LabelStore` via the DI container.
- **Custom** : explicit user overrides stored in the `stt_keyterms` table
  (this module's own SQLite file). Things the auto-seed misses — nicknames,
  jargon, phonetic variants the user actually pronounces.

The merged list is fed to Deepgram's ``keyterm`` query parameter, which
biases the decoder at inference time (no model retraining). Cap at 50
because Deepgram's documented limit is around there and longer lists
just dilute the boost.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Deepgram's keyterm prompt is most effective when the list is focused.
# Past ~50 the boost dilutes.
KEYTERM_CAP = 50

# Per-term length guard — long sentences make no sense as keyterms and
# would just be noise in the URL.
_MAX_TERM_LEN = 80

_local = threading.local()


def _resolve_db_path() -> str:
    """Lazy import of DATA_DIR — keeps import-time side effects out so
    tests that monkey-patch AGENTYS_DATA_DIR after import still see the
    override."""
    from app.config import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return str(Path(DATA_DIR) / "stt_keyterms.db")


def _get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Thread-local connection. Mirrors ScheduledEmailStore — separate
    SQLite file (not the main encrypted agentys.db), low risk, easy to
    delete to reset."""
    path = db_path or _resolve_db_path()
    attr = f"_stt_keyterms_conn_{path}"
    conn = getattr(_local, attr, None)
    if conn is None:
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stt_keyterms (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id  INTEGER NOT NULL,
                term        TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_stt_keyterms_unique
                ON stt_keyterms (account_id, term COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_stt_keyterms_account
                ON stt_keyterms (account_id);
            CREATE TABLE IF NOT EXISTS stt_keyterms_excluded (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id  INTEGER NOT NULL,
                term        TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_stt_keyterms_excluded_unique
                ON stt_keyterms_excluded (account_id, term COLLATE NOCASE);
            """
        )
        conn.commit()
        setattr(_local, attr, conn)
    return conn


def _normalize(term: str) -> str:
    """Strip + collapse whitespace + clamp length. Returns '' if invalid."""
    if not term:
        return ""
    cleaned = " ".join(term.split())
    if not cleaned:
        return ""
    return cleaned[:_MAX_TERM_LEN]


def list_custom(account_id: int, *, db_path: Optional[str] = None) -> list[str]:
    """User overrides for `account_id`, oldest-first."""
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT term FROM stt_keyterms WHERE account_id = ? ORDER BY id ASC",
        (int(account_id),),
    ).fetchall()
    return [r["term"] for r in rows]


def add_keyterm(
    account_id: int, term: str, *, db_path: Optional[str] = None
) -> bool:
    """Insert a custom keyterm. Returns True on insert, False on duplicate
    (unique index hit). Empty/whitespace input returns False without
    touching the DB."""
    cleaned = _normalize(term)
    if not cleaned:
        return False
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO stt_keyterms (account_id, term, created_at) VALUES (?, ?, ?)",
            (int(account_id), cleaned, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_keyterm(
    account_id: int, term: str, *, db_path: Optional[str] = None
) -> bool:
    """Remove a custom keyterm (case-insensitive match on the term).
    Returns True iff a row was deleted."""
    cleaned = _normalize(term)
    if not cleaned:
        return False
    conn = _get_conn(db_path)
    cur = conn.execute(
        "DELETE FROM stt_keyterms WHERE account_id = ? AND term = ? COLLATE NOCASE",
        (int(account_id), cleaned),
    )
    conn.commit()
    return cur.rowcount > 0


def list_excluded_auto(account_id: int, *, db_path: Optional[str] = None) -> list[str]:
    """Auto-seed terms the user has hidden for `account_id`."""
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT term FROM stt_keyterms_excluded WHERE account_id = ? ORDER BY id ASC",
        (int(account_id),),
    ).fetchall()
    return [r["term"] for r in rows]


def exclude_auto_keyterm(
    account_id: int, term: str, *, db_path: Optional[str] = None
) -> bool:
    """Hide an auto-seeded term from the merged list. Returns True on insert."""
    cleaned = _normalize(term)
    if not cleaned:
        return False
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO stt_keyterms_excluded (account_id, term, created_at) VALUES (?, ?, ?)",
            (int(account_id), cleaned, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def list_auto(account_id: int, *, db_path: Optional[str] = None) -> list[str]:
    """Project label names for `account_id`, minus any the user excluded."""
    if account_id is None or int(account_id) < 0:
        return []
    try:
        from app.infrastructure.container import get_container
        store = get_container().get_label_store(account_id=int(account_id))
        labels = store.get_labels() or []
    except Exception as e:  # noqa: BLE001
        logger.info("stt_keyterms.list_auto: label store unavailable (%s)", e)
        return []
    excluded = {t.lower() for t in list_excluded_auto(int(account_id), db_path=db_path)}
    out: list[str] = []
    for lbl in labels:
        if not getattr(lbl, "is_project", False):
            continue
        name = (getattr(lbl, "name", "") or "").strip()
        if name and name.lower() not in excluded:
            out.append(name)
    return out


# Vocabulaire produit toujours boosté (device 2026-08-04 : « nouveau test
# depuis agentys » transcrit SANS le dernier mot — nom propre inconnu du
# décodeur). Nourrit le `keyterm` Deepgram ET le `prompt` Whisper fallback.
BASE_KEYTERMS: list[str] = ["Agentys"]


def get_keyterms_for_account(
    account_id: Optional[int],
    *,
    cap: int = KEYTERM_CAP,
    db_path: Optional[str] = None,
) -> list[str]:
    """Final list passed to Deepgram. Custom first (user overrides), then
    auto (project labels). Dedup is case-insensitive but the original
    casing of the first occurrence wins. Capped at `cap`.

    Custom leads the merge so a user's explicitly curated vocabulary always
    wins the limited keyterm budget — auto-seeded labels only fill the slots
    left over. Before 2026-06 the order was auto-first, which silently dropped
    custom words for accounts with many project labels (they never reached the
    decoder). The write-time cap (KEYTERM_CAP) now matches this read cap, so
    every stored custom term is guaranteed to be boosted.

    Returns [] for invalid account_id (e.g. -1 sentinel) — callers should
    just skip the keyterm param in that case.
    """
    if account_id is None or int(account_id) < 0:
        return []
    seen: set[str] = set()
    merged: list[str] = []
    # BASE_KEYTERMS en DERNIER : le vocabulaire produit ne mange jamais le
    # budget des termes utilisateur — il remplit les slots restants.
    for source in (
        list_custom(int(account_id), db_path=db_path),
        list_auto(int(account_id)),
        BASE_KEYTERMS,
    ):
        for term in source:
            cleaned = _normalize(term)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
            if len(merged) >= cap:
                return merged
    return merged
