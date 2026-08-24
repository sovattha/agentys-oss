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
Draft Quality Tracker — Measures "sent without edit" rate.

Tracks every send event and computes quality metrics:
- Unmodified rate (% of drafts sent as-is)
- Edit ratio distribution
- Breakdown by intent, tier, contact

Storage: SQLite in AGENTYS_DATA_DIR/draft_quality.db or ~/.agentys/draft_quality.db
"""

import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

def _default_db_path() -> str:
    primary_db_path = os.environ.get("AGENTYS_DB_PATH")
    if primary_db_path:
        return primary_db_path.replace("agentys.db", "draft_quality.db")

    data_dir = os.environ.get("AGENTYS_DATA_DIR")
    if data_dir:
        return os.path.join(data_dir, "draft_quality.db")

    return os.path.join(os.path.expanduser("~"), ".agentys", "draft_quality.db")


_DB_PATH = _default_db_path()
_instance: Optional["DraftQualityTracker"] = None
_lock = threading.Lock()


def get_tracker() -> "DraftQualityTracker":
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = DraftQualityTracker()
    return _instance


class DraftQualityTracker:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or _default_db_path()
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS send_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email_id TEXT NOT NULL,
                        contact TEXT DEFAULT '',
                        intent TEXT DEFAULT '',
                        tier TEXT DEFAULT '',
                        sent_unmodified INTEGER DEFAULT 0,
                        edit_ratio REAL DEFAULT 0.0,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_send_events_date
                    ON send_events(created_at)
                """)
                # Feature usage events (compose_ai, refine_ai, attachment_reminder, shortcut)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS feature_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        feature TEXT NOT NULL,
                        count INTEGER DEFAULT 1,
                        account_id TEXT DEFAULT '',
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feature_events_date
                    ON feature_events(created_at)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feature_events_account_date
                    ON feature_events(account_id, created_at)
                """)
                # Email interaction events (reply, ignore, etc.)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS email_interactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email_id TEXT NOT NULL,
                        contact TEXT DEFAULT '',
                        action TEXT NOT NULL,
                        time_spent_sec REAL DEFAULT 0,
                        sent_length INTEGER DEFAULT 0,
                        cc_added TEXT DEFAULT '',
                        metadata TEXT DEFAULT '{}',
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_email_interactions_contact
                    ON email_interactions(contact)
                """)
        except Exception as e:
            logger.warning(f"DraftQualityTracker: failed to init db: {e}")
        self._migrate_db()

    def _migrate_db(self) -> None:
        """Ajoute les colonnes manquantes pour la rétro-compatibilité."""
        try:
            with self._get_conn() as conn:
                for tbl in ("send_events", "email_interactions", "feature_events"):
                    try:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN account_id TEXT DEFAULT ''")
                    except Exception:
                        pass  # Colonne déjà présente
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feature_events_account_date
                    ON feature_events(account_id, created_at)
                """)
        except Exception as e:
            logger.warning(f"DraftQualityTracker: migration failed: {e}")

    def record_send(
        self,
        email_id: str,
        contact: str = "",
        intent: str = "",
        tier: str = "",
        sent_unmodified: bool = False,
        edit_ratio: float = 0.0,
        account_id: str = "",
    ) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO send_events
                       (email_id, contact, intent, tier, sent_unmodified, edit_ratio, account_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (email_id, contact, intent, tier,
                     1 if sent_unmodified else 0, edit_ratio, account_id),
                )
            logger.info(
                f"QualityTracker: recorded send email_id={email_id[:20]}, "
                f"unmodified={sent_unmodified}, edit_ratio={edit_ratio:.2f}"
            )
        except Exception as e:
            logger.warning(f"QualityTracker: failed to record send: {e}")

    def record_feature(self, feature: str, count: int = 1, account_id: str = "") -> None:
        """Record a feature usage event (compose_ai, refine_ai, attachment_reminder, shortcut)."""
        if feature not in self._TIME_SAVED:
            logger.warning(f"QualityTracker: unknown feature '{feature}'")
            return
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO feature_events (feature, count, account_id) VALUES (?, ?, ?)",
                    (feature, count, str(account_id or "")),
                )
        except Exception as e:
            logger.warning(f"QualityTracker: failed to record feature '{feature}': {e}")

    def record_interaction(
        self,
        email_id: str,
        contact: str,
        action: str,
        time_spent_sec: float = 0,
        sent_length: int = 0,
        cc_added: str = "",
        metadata: str = "{}",
        account_id: str = "",
    ) -> None:
        """Record an email interaction (reply, reject, ignore, etc.)."""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO email_interactions
                       (email_id, contact, action, time_spent_sec, sent_length, cc_added, metadata, account_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (email_id, contact, action, time_spent_sec, sent_length, cc_added, metadata, account_id),
                )
        except Exception as e:
            logger.debug(f"QualityTracker: failed to record interaction: {e}")

    def get_top_contacts(
        self, limit: int = 20, days: int = 60, account_id: Optional[str] = None
    ) -> list[dict]:
        """Get top contacts by send volume with aggregated stats."""
        try:
            # Format SQLite-compatible : `datetime('now')` retourne
            # "YYYY-MM-DD HH:MM:SS" (espace, UTC, sans microseconds).
            # `datetime.now().isoformat()` retourne "YYYY-MM-DDTHH:MM:SS.ffffff"
            # (T, heure locale, avec microseconds) → comparaison lexicographique
            # cassée à la position 10 (' ' < 'T') et offset TZ silencieux.
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            with self._get_conn() as conn:
                if account_id:
                    rows = conn.execute(
                        """SELECT contact,
                             COUNT(*) as total,
                             SUM(sent_unmodified) as unmodified,
                             AVG(edit_ratio) as avg_edit
                           FROM send_events
                           WHERE created_at >= ? AND contact != ''
                             AND (account_id = ? OR account_id = '')
                           GROUP BY contact
                           ORDER BY total DESC
                           LIMIT ?""",
                        (cutoff, account_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT contact,
                             COUNT(*) as total,
                             SUM(sent_unmodified) as unmodified,
                             AVG(edit_ratio) as avg_edit
                           FROM send_events
                           WHERE created_at >= ? AND contact != ''
                           GROUP BY contact
                           ORDER BY total DESC
                           LIMIT ?""",
                        (cutoff, limit),
                    ).fetchall()
                return [
                    {
                        "contact": r["contact"],
                        "total": r["total"],
                        "unmodified": r["unmodified"] or 0,
                        "avg_edit_ratio": round(r["avg_edit"] or 0, 3),
                    }
                    for r in rows
                ] if rows else []
        except Exception as e:
            logger.warning(f"QualityTracker: failed to get top contacts: {e}")
            return []

    def get_contact_avg_length(
        self, contact: str, days: int = 60, account_id: Optional[str] = None
    ) -> int | None:
        """Get average sent reply length for a contact.

        Audit F-02 (2026-05-16): account_id is required to prevent
        cross-tenant aggregate leak on shared-SQLite deployments. Same
        partitioning pattern as `get_top_contacts`: `account_id = ?
        OR account_id = ''` keeps legacy pre-migration rows visible
        only to their original tenant set (which was empty → safe).
        """
        try:
            # Format SQLite-compatible : `datetime('now')` retourne
            # "YYYY-MM-DD HH:MM:SS" (espace, UTC, sans microseconds).
            # `datetime.now().isoformat()` retourne "YYYY-MM-DDTHH:MM:SS.ffffff"
            # (T, heure locale, avec microseconds) → comparaison lexicographique
            # cassée à la position 10 (' ' < 'T') et offset TZ silencieux.
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            with self._get_conn() as conn:
                if account_id:
                    row = conn.execute(
                        """SELECT AVG(sent_length) as avg_len, COUNT(*) as cnt
                           FROM email_interactions
                           WHERE contact = ? AND action = 'reply' AND sent_length > 0
                           AND created_at >= ?
                           AND (account_id = ? OR account_id = '')""",
                        (contact, cutoff, account_id),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """SELECT AVG(sent_length) as avg_len, COUNT(*) as cnt
                           FROM email_interactions
                           WHERE contact = ? AND action = 'reply' AND sent_length > 0
                           AND created_at >= ?""",
                        (contact, cutoff),
                    ).fetchone()
                if row and row["cnt"] >= 2:
                    return int(row["avg_len"])
        except Exception:
            pass
        return None

    def get_contact_cc_patterns(
        self, contact: str, days: int = 90, account_id: Optional[str] = None
    ) -> list[str]:
        """Get frequently added CC addresses when replying to a contact.

        Audit F-02 (2026-05-16): account_id is required — cc_added
        contains real email addresses from co-recipients; leaking them
        across tenants on shared SQLite is the PII portion of the
        contacts-insights leak.
        """
        try:
            # Format SQLite-compatible : `datetime('now')` retourne
            # "YYYY-MM-DD HH:MM:SS" (espace, UTC, sans microseconds).
            # `datetime.now().isoformat()` retourne "YYYY-MM-DDTHH:MM:SS.ffffff"
            # (T, heure locale, avec microseconds) → comparaison lexicographique
            # cassée à la position 10 (' ' < 'T') et offset TZ silencieux.
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            with self._get_conn() as conn:
                if account_id:
                    rows = conn.execute(
                        """SELECT cc_added, COUNT(*) as cnt
                           FROM email_interactions
                           WHERE contact = ? AND cc_added != '' AND created_at >= ?
                           AND (account_id = ? OR account_id = '')
                           GROUP BY cc_added
                           HAVING cnt >= 2
                           ORDER BY cnt DESC
                           LIMIT 5""",
                        (contact, cutoff, account_id),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT cc_added, COUNT(*) as cnt
                           FROM email_interactions
                           WHERE contact = ? AND cc_added != '' AND created_at >= ?
                           GROUP BY cc_added
                           HAVING cnt >= 2
                           ORDER BY cnt DESC
                           LIMIT 5""",
                        (contact, cutoff),
                    ).fetchall()
                return [r["cc_added"] for r in rows] if rows else []
        except Exception:
            return []

    def get_ignored_senders(self, days: int = 14, min_ignored: int = 2) -> list[dict]:
        """Get senders whose emails are consistently ignored (no reply/validate action)."""
        try:
            # Format SQLite-compatible : `datetime('now')` retourne
            # "YYYY-MM-DD HH:MM:SS" (espace, UTC, sans microseconds).
            # `datetime.now().isoformat()` retourne "YYYY-MM-DDTHH:MM:SS.ffffff"
            # (T, heure locale, avec microseconds) → comparaison lexicographique
            # cassée à la position 10 (' ' < 'T') et offset TZ silencieux.
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            with self._get_conn() as conn:
                rows = conn.execute(
                    """SELECT contact, COUNT(*) as ignored_count
                       FROM email_interactions
                       WHERE action = 'ignored' AND created_at >= ?
                       AND contact != ''
                       GROUP BY contact
                       HAVING ignored_count >= ?
                       ORDER BY ignored_count DESC
                       LIMIT 20""",
                    (cutoff, min_ignored),
                ).fetchall()
                return [{"contact": r["contact"], "count": r["ignored_count"]} for r in rows] if rows else []
        except Exception:
            return []

    def get_contact_edit_stats(
        self, contact: str, days: int = 30, account_id: Optional[str] = None
    ) -> dict | None:
        """Get average edit_ratio and send count for a specific contact.

        Audit F-02 (2026-05-16): account_id is required — `send_events`
        rows are tenant-scoped on the same shared-SQLite surface as
        `email_interactions`. Without the filter the avg_edit_ratio for
        a shared contact merges every tenant's send pattern (reveals
        whether other tenants edit heavily vs. send verbatim).
        """
        try:
            # Format SQLite-compatible : `datetime('now')` retourne
            # "YYYY-MM-DD HH:MM:SS" (espace, UTC, sans microseconds).
            # `datetime.now().isoformat()` retourne "YYYY-MM-DDTHH:MM:SS.ffffff"
            # (T, heure locale, avec microseconds) → comparaison lexicographique
            # cassée à la position 10 (' ' < 'T') et offset TZ silencieux.
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            with self._get_conn() as conn:
                if account_id:
                    row = conn.execute(
                        """SELECT COUNT(*) as count, AVG(edit_ratio) as avg_edit_ratio
                           FROM send_events
                           WHERE contact = ? AND created_at >= ?
                           AND (account_id = ? OR account_id = '')""",
                        (contact, cutoff, account_id),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """SELECT COUNT(*) as count, AVG(edit_ratio) as avg_edit_ratio
                           FROM send_events
                           WHERE contact = ? AND created_at >= ?""",
                        (contact, cutoff),
                    ).fetchone()
                if row and row["count"] > 0:
                    return {
                        "count": row["count"],
                        "avg_edit_ratio": row["avg_edit_ratio"] or 0.0,
                    }
        except Exception:
            pass
        return None

    def get_stats(self, days: int = 7, account_id: Optional[str] = None) -> dict:
        """Get quality stats for the last N days.

        Audit 2026-05-29: account_id scopes the stats to the caller's tenant
        (the `account_id = ? OR account_id = ''` partition keeps legacy
        pre-migration rows visible). None = global single-user (Tauri)."""
        try:
            # Format SQLite-compatible : `datetime('now')` retourne
            # "YYYY-MM-DD HH:MM:SS" (espace, UTC, sans microseconds).
            # `datetime.now().isoformat()` retourne "YYYY-MM-DDTHH:MM:SS.ffffff"
            # (T, heure locale, avec microseconds) → comparaison lexicographique
            # cassée à la position 10 (' ' < 'T') et offset TZ silencieux.
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            _acct = " AND (account_id = ? OR account_id = '')" if account_id else ""
            _ap = (account_id,) if account_id else ()
            with self._get_conn() as conn:
                row = conn.execute(
                    f"""SELECT
                         COUNT(*) as total,
                         SUM(sent_unmodified) as unmodified,
                         AVG(edit_ratio) as avg_edit
                       FROM send_events
                       WHERE created_at >= ?{_acct}""",
                    (cutoff, *_ap),
                ).fetchone()

                total = row["total"] or 0
                unmodified = row["unmodified"] or 0
                avg_edit = row["avg_edit"] or 0.0
                rate = (unmodified / total * 100) if total > 0 else 0.0

                # By intent
                intent_rows = conn.execute(
                    f"""SELECT intent,
                         COUNT(*) as total,
                         SUM(sent_unmodified) as unmodified
                       FROM send_events
                       WHERE created_at >= ? AND intent != ''{_acct}
                       GROUP BY intent""",
                    (cutoff, *_ap),
                ).fetchall()

                by_intent = {}
                for r in intent_rows:
                    t = r["total"]
                    u = r["unmodified"] or 0
                    by_intent[r["intent"]] = {
                        "total": t,
                        "unmodified": u,
                        "rate": round(u / t * 100, 1) if t > 0 else 0,
                    }

                # By tier
                tier_rows = conn.execute(
                    f"""SELECT tier,
                         COUNT(*) as total,
                         SUM(sent_unmodified) as unmodified
                       FROM send_events
                       WHERE created_at >= ? AND tier != ''{_acct}
                       GROUP BY tier""",
                    (cutoff, *_ap),
                ).fetchall()

                by_tier = {}
                for r in tier_rows:
                    t = r["total"]
                    u = r["unmodified"] or 0
                    by_tier[r["tier"]] = {
                        "total": t,
                        "unmodified": u,
                        "rate": round(u / t * 100, 1) if t > 0 else 0,
                    }

                # Daily trend (last 7 days)
                daily_rows = conn.execute(
                    f"""SELECT date(created_at) as day,
                         COUNT(*) as total,
                         SUM(sent_unmodified) as unmodified
                       FROM send_events
                       WHERE created_at >= ?{_acct}
                       GROUP BY date(created_at)
                       ORDER BY day""",
                    (cutoff, *_ap),
                ).fetchall()

                daily = []
                for r in daily_rows:
                    t = r["total"]
                    u = r["unmodified"] or 0
                    daily.append({
                        "date": r["day"],
                        "total": t,
                        "unmodified": u,
                        "rate": round(u / t * 100, 1) if t > 0 else 0,
                    })

                return {
                    "period_days": days,
                    "total_sent": total,
                    "sent_unmodified": unmodified,
                    "unmodified_rate": round(rate, 1),
                    "avg_edit_ratio": round(avg_edit, 3),
                    "by_intent": by_intent,
                    "by_tier": by_tier,
                    "daily": daily,
                }
        except Exception as e:
            logger.warning(f"QualityTracker: failed to get stats: {e}")
            return {
                "period_days": days,
                "total_sent": 0,
                "sent_unmodified": 0,
                "unmodified_rate": 0,
                "avg_edit_ratio": 0,
                "by_intent": {},
                "by_tier": {},
                "daily": [],
            }

    # ── Time saved per feature ────────────────────────────────────────────
    # Estimated minutes saved per action type
    _TIME_SAVED = {
        "simple": 1.2,      # Short ack/template → ~1 min saved (original 2 min × 0.6)
        "standard": 3,      # Normal composition → 3 min saved (original 5 min × 0.6)
        "complex": 6,       # Multi-part reply → 6 min saved (original 10 min × 0.6)
        "followup": 2,      # Follow-up reminder → 2 min saved (search + recall context)
        "archive": 0.17,    # Auto-archive → ~10 sec saved (KLM 1983 + Superhuman 2024)
        "label": 0.25,      # Auto-label → 15 sec saved
        "compose_ai": 5,    # AI-assisted email → 5 min saved
        "refine_ai": 1.5,   # Refine pass on a manual draft → ~1.5 min saved (rewrite + tone)
        "auto_reply": 1,    # Auto-reply d'absence → ~1 min saved
        "attachment_reminder": 3,  # Caught forgotten attachment → 3 min saved (avoids follow-up)
        "deep_work_min": 0,      # Minutes in concentration mode (tracking only, no time saved)
        "deep_work_emails": 1.067, # 64s per blocked email interruption (Jackson et al., 2003) → 64/60 min
        "shortcut": 0.0167,  # Keyboard shortcut → ~1 sec saved per action (Grossman et al., 2016)
        "suggestion_click": 0,  # Smart Suggestion click — tracking only, no time saved
        "smart_schedule": 0,    # Removed
        "auto_label": 0.25,  # Auto-label applied → 15 sec saved vs manual sorting
        "auto_archive_action": 0.17,  # Auto-archive of Action email → ~10 sec saved (KLM 1983)
    }

    def get_activity(self, account_id=None) -> dict:
        """Activity stats for 'this week' and 'today' with refined time savings.

        ``account_id`` (audit 2026-05-29) scopes the live time-saved indicator
        to one tenant. When None (Tauri desktop single-user) the behaviour is
        unchanged — global aggregate across the single-user host.
        """
        try:
            # Use UTC to match SQLite datetime('now') which stores UTC
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            # Monday of current week
            week_start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).strftime("%Y-%m-%d %H:%M:%S")

            with self._get_conn() as conn:
                week = self._activity_for_period(conn, week_start, account_id=account_id)
                today = self._activity_for_period(conn, today_start, account_id=account_id)

            return {"week": week, "today": today}
        except Exception as e:
            logger.warning(f"QualityTracker: failed to get activity: {e}")
            empty = self._empty_activity()
            return {"week": empty, "today": empty}

    def get_month_activity(self, month: str, account_id=None) -> dict:
        """Activity stats for a specific month (YYYY-MM format).

        ``account_id`` (audit 2026-05-29) scopes the monthly recap to one
        tenant. When None (the live week/today dashboard) the behaviour is
        unchanged — global aggregate across the single-user host.
        """
        try:
            year, m = int(month[:4]), int(month[5:7])
            month_start = f"{month}-01 00:00:00"
            if m == 12:
                month_end = f"{year + 1}-01-01 00:00:00"
            else:
                month_end = f"{year}-{m + 1:02d}-01 00:00:00"
            with self._get_conn() as conn:
                return self._activity_for_period(
                    conn, month_start, end_cutoff=month_end, account_id=account_id
                )
        except Exception as e:
            logger.warning(f"QualityTracker: failed to get month activity for {month}: {e}")
            return self._empty_activity()

    def _activity_for_period(self, conn, cutoff: str, end_cutoff: str = None, account_id=None) -> dict:
        """Aggregate activity stats since cutoff datetime (optionally bounded by end_cutoff)."""
        date_filter = "created_at >= ?"
        params_base = [cutoff]
        if end_cutoff:
            date_filter = "created_at >= ? AND created_at < ?"
            params_base = [cutoff, end_cutoff]

        # Audit 2026-05-29: scope send_events to the account when provided so
        # the monthly recap stops summing EVERY tenant's tiers/drafts.
        # send_events carries account_id (legacy rows = ''); keep '' visible
        # for backward-compat (pre-isolation sends). feature_events is stricter:
        # legacy global rows are excluded from scoped recaps because they cannot
        # be attributed safely to a tenant.
        send_filter = date_filter
        send_params = list(params_base)
        feature_filter = date_filter
        feature_params = list(params_base)
        if account_id is not None:
            send_filter = date_filter + " AND (account_id = ? OR account_id = '')"
            send_params = list(params_base) + [str(account_id)]
            feature_filter = date_filter + " AND account_id = ?"
            feature_params = list(params_base) + [str(account_id)]

        # Tier counts
        tier_rows = conn.execute(
            f"""SELECT LOWER(tier) as tier, COUNT(*) as cnt
               FROM send_events
               WHERE {send_filter} AND tier != ''
               GROUP BY LOWER(tier)""",
            send_params,
        ).fetchall()
        tiers = {r["tier"]: r["cnt"] for r in tier_rows}

        # Total drafts (including those without tier)
        total_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM send_events WHERE {send_filter}",
            send_params,
        ).fetchone()
        total_drafts = total_row["cnt"] if total_row else 0

        # Time saved calculation per tier
        time_drafts = sum(
            tiers.get(t, 0) * self._TIME_SAVED.get(t, 5)
            for t in ("simple", "standard", "complex")
        )
        # Follow-up reminders
        time_followup = tiers.get("followup", 0) * self._TIME_SAVED["followup"]
        # Drafts without tier → default 5 min
        known_tiers = sum(tiers.get(t, 0) for t in ("simple", "standard", "complex", "followup"))
        untiered = total_drafts - known_tiers
        time_drafts += max(0, untiered) * 5

        # Feature events (compose_ai, refine_ai, auto_reply, attachment_reminder, shortcut,
        # auto_label applied to incoming emails, auto_archive_action triggered on Action-labeled emails)
        features = {"compose_ai": 0, "refine_ai": 0, "auto_reply": 0, "attachment_reminder": 0, "deep_work_min": 0, "deep_work_emails": 0, "shortcut": 0, "smart_schedule": 0, "auto_label": 0, "auto_archive_action": 0}
        try:
            feat_rows = conn.execute(
                f"""SELECT feature, SUM(count) as total
                   FROM feature_events
                   WHERE {feature_filter}
                   GROUP BY feature""",
                feature_params,
            ).fetchall()
            for r in feat_rows:
                if r["feature"] in features:
                    features[r["feature"]] = r["total"] or 0
        except Exception:
            pass  # Table may not exist yet in old DBs

        time_compose = features["compose_ai"] * self._TIME_SAVED["compose_ai"]
        time_refine = features["refine_ai"] * self._TIME_SAVED["refine_ai"]
        time_auto_reply = features["auto_reply"] * self._TIME_SAVED["auto_reply"]
        time_attachment = features["attachment_reminder"] * self._TIME_SAVED["attachment_reminder"]
        # 64s saved per email received during active concentration mode
        time_deep_work = features["deep_work_emails"] * self._TIME_SAVED["deep_work_emails"]
        time_shortcuts = features["shortcut"] * self._TIME_SAVED["shortcut"]
        time_smart_schedule = features["smart_schedule"] * self._TIME_SAVED["smart_schedule"]
        # Auto-label on incoming emails (tracked via record_feature in _auto_assign_labels_background)
        time_label = features["auto_label"] * self._TIME_SAVED["auto_label"]
        # Auto-archive of Action emails (tracked via record_feature in _auto_archive_if_action)
        time_archive = features["auto_archive_action"] * self._TIME_SAVED["auto_archive_action"]

        # Merge compose/refine/auto_reply into drafts (all are AI-assisted writing)
        time_drafts += time_compose + time_refine + time_auto_reply
        time_features = time_attachment + time_deep_work + time_shortcuts + time_smart_schedule

        time_total = round(time_drafts + time_followup + time_archive + time_label + time_features, 1)

        return {
            "drafts": total_drafts,
            "tiers": {
                "simple": tiers.get("simple", 0),
                "standard": tiers.get("standard", 0),
                "complex": tiers.get("complex", 0),
                "followup": tiers.get("followup", 0),
            },
            "archives": features["auto_archive_action"],
            "labels": features["auto_label"],
            "features": features,
            "time_saved_min": time_total,
            "time_breakdown": {
                "drafts": round(time_drafts, 1),
                "followup": round(time_followup, 1),
                "archive": round(time_archive, 1),
                "label": round(time_label, 1),
                "attachment_reminder": round(time_attachment, 1),
                "deep_work": round(time_deep_work, 1),
                "shortcuts": round(time_shortcuts, 1),
                "smart_schedule": round(time_smart_schedule, 1),
            },
        }

    @staticmethod
    def _empty_activity() -> dict:
        return {
            "drafts": 0,
            "tiers": {"simple": 0, "standard": 0, "complex": 0, "followup": 0},
            "archives": 0,
            "labels": 0,
            "features": {"compose_ai": 0, "refine_ai": 0, "auto_reply": 0, "attachment_reminder": 0, "deep_work_min": 0, "deep_work_emails": 0, "shortcut": 0, "smart_schedule": 0, "auto_label": 0, "auto_archive_action": 0},
            "time_saved_min": 0,
            "time_breakdown": {
                "drafts": 0, "followup": 0, "archive": 0, "label": 0,
                "attachment_reminder": 0,
                "deep_work": 0, "shortcuts": 0, "smart_schedule": 0,
            },
        }
