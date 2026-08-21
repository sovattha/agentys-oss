# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Template label cache — skip the LLM for emails that match a previously-seen template.

Many inboxes receive dozens of variations of the same 5-10 newsletter/notification
templates per month (Stripe payouts, GitHub digests, Substack posts...). Labelling
each of them with a fresh LLM call is pure waste. This cache keys by a fuzzy
fingerprint of sender domain + normalised subject. In explicit legacy full-cache
mode it also includes a body prefix; metadata-only mode deliberately omits body
content from the durable fingerprint.

The fingerprint is intentionally loose:
- Exact sender domain (not full email — "alerts@stripe.com" and "notifications@stripe.com"
  share a domain, but we key only on the domain to catch template reuse).
- Subject with Re:/Fwd: prefixes stripped, digits/dates scrubbed, whitespace collapsed.
- First 64 chars of body only when `AGENTYS_EMAIL_CONTENT_STORAGE_MODE` is
  `legacy_full_cache`. Metadata-only mode never stores a hash derived from the
  body prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from typing import Any, Dict, Optional, Tuple

from app.config import should_persist_email_content

logger = logging.getLogger(__name__)

# Lifespan of a cached label. A template that hasn't re-occurred in 90 days is
# likely gone, and the user's labelling preferences may have drifted.
DEFAULT_TTL_DAYS = 90

# Soft cap on cache size. JSON persistence is cheap below ~10k entries; beyond
# that, we evict least-recently-used.
MAX_ENTRIES = 5_000

_SUBJECT_PREFIX_RE = re.compile(r"^\s*(?:re|fwd?|tr|fw)\s*:\s*", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\d+")
_WHITESPACE_RE = re.compile(r"\s+")
_SENDER_DOMAIN_RE = re.compile(r"<([^>]+)>")


def _extract_sender_domain(sender: str) -> str:
    """Extract domain from 'Name <addr@host>' or 'addr@host'. Returns lowercase."""
    if not sender:
        return ""
    s = sender.lower().strip()
    m = _SENDER_DOMAIN_RE.search(s)
    addr = m.group(1) if m else s
    if "@" not in addr:
        return ""
    return addr.split("@", 1)[1].strip()


def _normalise_subject(subject: str) -> str:
    """Strip Re:/Fwd: prefixes, scrub digits, collapse whitespace, lowercase."""
    if not subject:
        return ""
    s = subject.strip()
    # Strip repeated Re:/Fwd: prefixes ("Re: Fwd: Re: foo" → "foo")
    while True:
        s2 = _SUBJECT_PREFIX_RE.sub("", s)
        if s2 == s:
            break
        s = s2
    s = s.lower()
    s = _DIGITS_RE.sub("#", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def _normalise_body_prefix(body: str, n: int = 64) -> str:
    """First N chars of body, lowered and whitespace-collapsed."""
    if not body:
        return ""
    s = _WHITESPACE_RE.sub(" ", body.strip()).lower()
    return s[:n]


def compute_fingerprint(sender: str, subject: str, body: str, scope: str = "") -> str:
    """Compute a stable fingerprint for a (sender, subject, body) triple.

    Returns a 40-char hex sha1 (or ``"{scope}:{sha1}"`` when ``scope`` is set).
    Two emails sharing the same fingerprint are considered the same template.

    The optional ``scope`` argument prefixes the key so cache entries don't
    bleed across users sharing a single cache file. A real-life example: a
    "Stripe payout" template might be Noise for one user (high-volume merchant
    who treats it as routine) and Action for another (low-volume freelancer
    who reviews each one). Passing ``scope=user_id`` keeps each user's
    learned decisions separate. Empty scope (default) preserves legacy
    global-cache behaviour for callers that don't supply one.
    """
    body_part = _normalise_body_prefix(body) if should_persist_email_content() else ""
    parts = [
        _extract_sender_domain(sender),
        _normalise_subject(subject),
        body_part,
    ]
    joined = "\x00".join(parts)
    fp = hashlib.sha1(joined.encode("utf-8")).hexdigest()
    if scope:
        return f"{scope}:{fp}"
    return fp


@dataclass
class _Entry:
    label: str
    confidence: float
    reason: str
    created_at: str  # ISO datetime
    hit_count: int = 0
    last_used_at: str = ""

    def to_dict(self) -> Dict:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "reason": self.reason,
            "created_at": self.created_at,
            "hit_count": self.hit_count,
            "last_used_at": self.last_used_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "_Entry":
        return cls(
            label=str(d.get("label") or ""),
            confidence=float(d.get("confidence") or 0.0),
            reason=str(d.get("reason") or ""),
            created_at=str(d.get("created_at") or ""),
            hit_count=int(d.get("hit_count") or 0),
            last_used_at=str(d.get("last_used_at") or ""),
        )


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS template_label_cache (
    fingerprint TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    confidence REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tlc_last_used ON template_label_cache(last_used_at);
CREATE INDEX IF NOT EXISTS idx_tlc_created ON template_label_cache(created_at);
"""


class TemplateLabelCache:
    """Thread-safe, SQLite-backed cache of template → label decisions.

    SQLite was chosen over the legacy JSON blob (cost optim 2026-05-04) for:
      - atomic per-entry writes (no half-written JSON on crash)
      - indexed LRU eviction (last_used_at index)
      - alignment with the project's SQLCipher direction
      - cheap concurrent reads via WAL mode

    The on-disk file lives next to the legacy JSON path; if a JSON file is
    found at first load and the SQLite table is empty, entries are migrated
    once and the JSON file renamed ``…json.migrated`` so the next process
    boot reads only from SQLite.

    Usage (unchanged from the JSON version):
        cache = TemplateLabelCache(storage_dir)
        fp = cache.fingerprint(sender, subject, body)
        hit = cache.get(fp)
        if hit is None:
            label, conf, reason = call_llm(...)
            cache.set(fp, label, conf, reason)
    """

    def __init__(self, storage_dir: str, ttl_days: int = DEFAULT_TTL_DAYS, max_entries: int = MAX_ENTRIES):
        self.storage_dir = storage_dir
        self.ttl_days = ttl_days
        self.max_entries = max_entries
        self._json_path = os.path.join(storage_dir, "template_label_cache.json")  # legacy
        self._db_path = os.path.join(storage_dir, "template_label_cache.sqlite3")
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._cache: Optional[Dict[str, _Entry]] = None
        # Process-lifetime counters — not persisted. Reset on boot.
        # Used by /api/labels/cache-stats to compute hit_rate.
        self._session_hits = 0
        self._session_misses = 0
        self._session_llm_writes = 0
        os.makedirs(storage_dir, exist_ok=True)

    @staticmethod
    def fingerprint(sender: str, subject: str, body: str, scope: str = "") -> str:
        return compute_fingerprint(sender, subject, body, scope=scope)

    def _get_conn(self) -> sqlite3.Connection:
        """Open the SQLite connection lazily and ensure schema exists.

        ``check_same_thread=False`` lets the cache be shared across threads
        (callers serialise on ``self._lock`` for write operations). WAL mode
        keeps reads non-blocking when concurrent writers are present.
        """
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit — paired with WAL for atomic writes
            timeout=5.0,
        )
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            pass  # PRAGMAs are perf hints; safe to ignore failures
        for stmt in _SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        self._conn = conn
        return conn

    def _migrate_from_json_if_needed(self, conn: sqlite3.Connection) -> int:
        """If a legacy JSON file exists and SQLite is empty, copy it over.

        Runs at most once per process (called from ``_load``). Returns the
        number of entries migrated. The JSON file is renamed afterwards so
        subsequent boots don't re-migrate.
        """
        try:
            row = conn.execute("SELECT COUNT(*) FROM template_label_cache").fetchone()
            if row and int(row[0] or 0) > 0:
                return 0
            if not os.path.exists(self._json_path):
                return 0
            with open(self._json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return 0
            tuples = []
            for fp, raw in data.items():
                try:
                    e = _Entry.from_dict(raw)
                    tuples.append((fp, e.label, e.confidence, e.reason, e.created_at, e.hit_count, e.last_used_at))
                except (TypeError, ValueError):
                    continue
            if not tuples:
                return 0
            conn.executemany(
                "INSERT OR REPLACE INTO template_label_cache "
                "(fingerprint, label, confidence, reason, created_at, hit_count, last_used_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                tuples,
            )
            try:
                os.rename(self._json_path, self._json_path + ".migrated")
            except OSError as e:
                logger.debug("TemplateLabelCache: JSON rename after migration failed: %s", e)
            logger.info("TemplateLabelCache: migrated %d entries from JSON to SQLite", len(tuples))
            return len(tuples)
        except (json.JSONDecodeError, OSError, sqlite3.Error) as e:
            logger.warning("TemplateLabelCache: JSON→SQLite migration failed: %s", e)
            return 0

    def _load(self) -> Dict[str, _Entry]:
        """Load all entries from SQLite into the in-memory working set.

        Called lazily on first access. The working set is then used for hot
        reads and LRU bookkeeping; persistence happens via ``_upsert_row`` /
        ``_delete_row`` on each mutation.
        """
        if self._cache is not None:
            return self._cache
        conn = self._get_conn()
        self._migrate_from_json_if_needed(conn)
        cache: Dict[str, _Entry] = {}
        try:
            cursor = conn.execute(
                "SELECT fingerprint, label, confidence, reason, created_at, hit_count, last_used_at "
                "FROM template_label_cache"
            )
            for row in cursor:
                cache[row[0]] = _Entry(
                    label=row[1] or "",
                    confidence=float(row[2] or 0.0),
                    reason=row[3] or "",
                    created_at=row[4] or "",
                    hit_count=int(row[5] or 0),
                    last_used_at=row[6] or "",
                )
        except sqlite3.Error as e:
            logger.warning("TemplateLabelCache: load failed: %s", e)
        self._cache = cache
        return cache

    def _upsert_row(self, fp: str, entry: _Entry) -> None:
        try:
            self._get_conn().execute(
                "INSERT OR REPLACE INTO template_label_cache "
                "(fingerprint, label, confidence, reason, created_at, hit_count, last_used_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fp, entry.label, entry.confidence, entry.reason, entry.created_at, entry.hit_count, entry.last_used_at),
            )
        except sqlite3.Error as e:
            logger.warning("TemplateLabelCache: upsert failed: %s", e)

    def _delete_row(self, fp: str) -> None:
        try:
            self._get_conn().execute(
                "DELETE FROM template_label_cache WHERE fingerprint = ?", (fp,)
            )
        except sqlite3.Error as e:
            logger.warning("TemplateLabelCache: delete failed: %s", e)

    def _is_expired(self, entry: _Entry, now: datetime) -> bool:
        try:
            created = datetime.fromisoformat(entry.created_at)
        except (ValueError, TypeError):
            return True
        return (now - created) > timedelta(days=self.ttl_days)

    def get(self, fingerprint: str) -> Optional[Tuple[str, float, str]]:
        """Look up a cached label. Returns (label, conf, reason) or None.

        Persisting the hit_count + last_used_at on every read would double
        write IOPS for a marginal observability win. We update both in memory
        only — they get persisted opportunistically on the next ``set`` /
        ``invalidate`` for the same key, or lost on process restart (already
        the case in the legacy JSON impl).
        """
        if not fingerprint:
            return None
        with self._lock:
            cache = self._load()
            entry = cache.get(fingerprint)
            if entry is None:
                self._session_misses += 1
                return None
            now = datetime.now()
            if self._is_expired(entry, now):
                cache.pop(fingerprint, None)
                self._delete_row(fingerprint)
                self._session_misses += 1
                return None
            entry.hit_count += 1
            entry.last_used_at = now.isoformat()
            self._session_hits += 1
            return (entry.label, entry.confidence, entry.reason)

    def set(self, fingerprint: str, label: str, confidence: float, reason: str) -> None:
        """Store a label decision for a fingerprint."""
        if not fingerprint or not label:
            return
        with self._lock:
            cache = self._load()
            now_iso = datetime.now().isoformat()
            entry = _Entry(
                label=label,
                confidence=float(confidence),
                reason=reason,
                created_at=now_iso,
                hit_count=0,
                last_used_at=now_iso,
            )
            cache[fingerprint] = entry
            self._upsert_row(fingerprint, entry)
            self._session_llm_writes += 1
            # LRU-evict if needed (keep memory + DB in sync)
            if len(cache) > self.max_entries:
                victims = sorted(
                    cache.items(),
                    key=lambda kv: kv[1].last_used_at or kv[1].created_at,
                )[: max(1, len(cache) - self.max_entries)]
                for fp, _ in victims:
                    cache.pop(fp, None)
                    self._delete_row(fp)

    def invalidate(self, fingerprint: str) -> None:
        """Remove an entry (e.g. after a user correction)."""
        if not fingerprint:
            return
        with self._lock:
            cache = self._load()
            if cache.pop(fingerprint, None) is not None:
                self._delete_row(fingerprint)

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics for monitoring.

        ``lifetime_hits`` is the sum of hit_count across all in-memory entries.
        Note that hit_count updates between persist cycles only survive a
        process restart if a ``set`` or ``invalidate`` happened on the same
        key — same behaviour as the JSON impl.
        """
        with self._lock:
            cache = self._load()
            lifetime_hits = sum(e.hit_count for e in cache.values())
            session_lookups = self._session_hits + self._session_misses
            hit_rate = (self._session_hits / session_lookups) if session_lookups else 0.0
            return {
                "entries": len(cache),
                "max_entries": self.max_entries,
                "ttl_days": self.ttl_days,
                "lifetime_hits": lifetime_hits,
                "session_hits": self._session_hits,
                "session_misses": self._session_misses,
                "session_llm_writes": self._session_llm_writes,
                "session_lookups": session_lookups,
                "hit_rate": round(hit_rate, 4),
                "llm_calls_saved": self._session_hits,
            }

    def close(self) -> None:
        """Close the SQLite connection. Idempotent. Tests can call this to
        ensure the temp directory can be cleaned up on Windows."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None
            self._cache = None
