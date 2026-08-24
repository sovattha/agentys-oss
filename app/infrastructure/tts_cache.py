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
Cache disque pour les MP3 générés par ElevenLabs.

Clé = SHA256(voice_id|model_id|text). Valeur = fichier MP3 sur disque +
ligne SQLite avec métadonnées (chars, bytes, timestamps).

Économie : un même email relu n'appelle ElevenLabs qu'une seule fois.
Eviction LRU déclenchée lazy quand la taille totale dépasse 500 MB.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
from pathlib import Path

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

TTS_CACHE_DIR = DATA_DIR / "tts_cache"
_DB_PATH = TTS_CACHE_DIR / "tts_cache.db"
_MAX_BYTES_DEFAULT = 500 * 1024 * 1024  # 500 MB

_db_lock = threading.Lock()
_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _db_lock:
        if _schema_ready:
            return
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tts_cache (
                    hash TEXT PRIMARY KEY,
                    voice_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    chars INTEGER NOT NULL,
                    bytes INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_used_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tts_cache_last_used ON tts_cache(last_used_at)"
            )
            # F-02 (regression audit, 2026-04-29): voice_id → owner mapping.
            # ElevenLabs voices live in a single global account but are
            # tenant-scoped from the app's perspective. Without this table,
            # any tenant could DELETE any other tenant's cloned voice via
            # /api/tts/voices/<id>. Owner is identified by JWT user_id (int)
            # AND email, so we can audit cross-tenant attempts.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tts_voice_owners (
                    voice_id TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    owner_email TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()
        _schema_ready = True


# F-02 (regression audit, 2026-04-29): voice ownership tracking.
def set_voice_owner(voice_id: str, owner_user_id: int, owner_email: str) -> None:
    """Persist ownership of a freshly-cloned voice. Idempotent (REPLACE)."""
    _ensure_schema()
    now = int(time.time())
    with _db_lock, sqlite3.connect(str(_DB_PATH)) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO tts_voice_owners(voice_id, owner_user_id, owner_email, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (voice_id, int(owner_user_id), owner_email.lower(), now),
        )
        conn.commit()


def get_voice_owner(voice_id: str) -> tuple[int, str] | None:
    """Return (owner_user_id, owner_email) if known, None otherwise."""
    _ensure_schema()
    with _db_lock, sqlite3.connect(str(_DB_PATH)) as conn:
        cur = conn.execute(
            "SELECT owner_user_id, owner_email FROM tts_voice_owners WHERE voice_id = ?",
            (voice_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return int(row[0]), row[1]


def delete_voice_owner(voice_id: str) -> None:
    """Best-effort cleanup of the owner row (after a successful DELETE)."""
    _ensure_schema()
    with _db_lock, sqlite3.connect(str(_DB_PATH)) as conn:
        conn.execute("DELETE FROM tts_voice_owners WHERE voice_id = ?", (voice_id,))
        conn.commit()


def compute_hash(text: str, voice_id: str, model_id: str, language_code: str | None = None) -> str:
    # language_code fait partie de la clé : un même texte synthétisé en "fr"
    # vs "en" donne 2 MP3 différents (phonétique change). Les appels legacy
    # sans language_code restent compatibles (hash identique à l'ancien).
    lang_part = f"|{language_code}" if language_code else ""
    payload = f"{voice_id}|{model_id}|{text}{lang_part}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _path_for(hash_: str) -> Path:
    return TTS_CACHE_DIR / f"{hash_}.mp3"


def get_cached(hash_: str) -> Path | None:
    _ensure_schema()
    path = _path_for(hash_)
    if not path.exists():
        return None
    now = int(time.time())
    with _db_lock, sqlite3.connect(str(_DB_PATH)) as conn:
        cur = conn.execute("SELECT 1 FROM tts_cache WHERE hash = ?", (hash_,))
        row = cur.fetchone()
        if not row:
            # Fichier orphelin sur disque — on nettoie pour cohérence
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        conn.execute(
            "UPDATE tts_cache SET last_used_at = ? WHERE hash = ?", (now, hash_)
        )
        conn.commit()
    return path


def put(
    hash_: str,
    mp3_bytes: bytes,
    voice_id: str,
    model_id: str,
    chars: int,
    max_bytes: int = _MAX_BYTES_DEFAULT,
) -> Path:
    _ensure_schema()
    path = _path_for(hash_)
    path.write_bytes(mp3_bytes)
    now = int(time.time())
    size = len(mp3_bytes)
    with _db_lock, sqlite3.connect(str(_DB_PATH)) as conn:
        conn.execute(
            """
            INSERT INTO tts_cache(hash, voice_id, model_id, chars, bytes, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hash) DO UPDATE SET last_used_at = excluded.last_used_at
            """,
            (hash_, voice_id, model_id, chars, size, now, now),
        )
        conn.commit()
    _maybe_evict(max_bytes)
    return path


def _maybe_evict(max_bytes: int) -> None:
    """Eviction LRU lazy — ne s'exécute que si on dépasse le seuil."""
    with _db_lock, sqlite3.connect(str(_DB_PATH)) as conn:
        cur = conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM tts_cache")
        total = cur.fetchone()[0] or 0
        if total <= max_bytes:
            return
        target = int(max_bytes * 0.8)  # on redescend à 80% pour éviter de re-évictor à chaque put
        cur = conn.execute(
            "SELECT hash, bytes FROM tts_cache ORDER BY last_used_at ASC"
        )
        to_delete: list[str] = []
        freed = 0
        for hash_, size in cur:
            if total - freed <= target:
                break
            to_delete.append(hash_)
            freed += size
        for hash_ in to_delete:
            try:
                _path_for(hash_).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("TTS cache: échec suppression %s: %s", hash_, exc)
            conn.execute("DELETE FROM tts_cache WHERE hash = ?", (hash_,))
        conn.commit()
        if to_delete:
            logger.info(
                "TTS cache eviction: %d fichiers supprimés, %.1f MB libérés",
                len(to_delete),
                freed / 1024 / 1024,
            )


def total_chars_since(since_ts: int) -> int:
    """Somme des chars synthétisés depuis `since_ts` (pour suivi coût)."""
    _ensure_schema()
    with _db_lock, sqlite3.connect(str(_DB_PATH)) as conn:
        cur = conn.execute(
            "SELECT COALESCE(SUM(chars), 0) FROM tts_cache WHERE created_at >= ?",
            (since_ts,),
        )
        return cur.fetchone()[0] or 0
