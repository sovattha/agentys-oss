# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Store de réputation des expéditeurs.

Stocke l'historique des classifications par expéditeur pour permettre
une classification plus rapide et fiable des emails récurrents.
"""

import logging
import threading
from typing import Optional, Dict

from app.infrastructure.database import Database

logger = logging.getLogger(__name__)

# Domaines communs exclus de la réputation par domaine
COMMON_DOMAINS = frozenset({
    "gmail.com", "googlemail.com",
    "outlook.com", "outlook.fr", "hotmail.com", "hotmail.fr",
    "live.com", "live.fr", "msn.com",
    "yahoo.com", "yahoo.fr", "yahoo.ca",
    "protonmail.com", "proton.me", "pm.me",
    "icloud.com", "me.com", "mac.com",
    "aol.com", "aol.fr",
    "mail.com", "zoho.com",
})


class SenderReputationStore:
    """Stocke et interroge la réputation des expéditeurs basée sur l'historique de classification."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._db = Database()
        self._ensure_table()

    def _ensure_table(self):
        """Crée la table sender_reputation si elle n'existe pas."""
        try:
            conn = self._db._get_connection()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sender_reputation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_email TEXT NOT NULL,
                    sender_domain TEXT NOT NULL,
                    label_name TEXT NOT NULL,
                    source TEXT DEFAULT 'auto',
                    account_id INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_sender_rep_email
                    ON sender_reputation(sender_email, account_id);
                CREATE INDEX IF NOT EXISTS idx_sender_rep_domain
                    ON sender_reputation(sender_domain, account_id);
            """)
            conn.commit()
        except Exception as e:
            logger.warning(f"[SenderReputation] Failed to create table: {e}")

    def record_classification(
        self, sender: str, label: str, source: str = "auto", account_id: int = 1
    ) -> None:
        """Enregistre une classification pour un expéditeur."""
        if not sender or not label:
            return

        sender_lower = sender.lower().strip()
        domain = sender_lower.split("@")[-1] if "@" in sender_lower else ""

        try:
            conn = self._db._get_connection()
            conn.execute(
                """INSERT INTO sender_reputation
                   (sender_email, sender_domain, label_name, source, account_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (sender_lower, domain, label, source, account_id),
            )
            conn.commit()
        except Exception as e:
            logger.debug(f"[SenderReputation] record_classification failed: {e}")

    def get_sender_reputation(
        self, sender: str, account_id: int = 1
    ) -> Optional[Dict]:
        """
        Retourne la réputation d'un expéditeur si 3+ entrées existent.

        Returns:
            {"dominant_label": str, "confidence": float, "count": int} ou None
        """
        if not sender:
            return None

        sender_lower = sender.lower().strip()

        try:
            conn = self._db._get_connection()
            rows = conn.execute(
                """SELECT label_name,
                          SUM(CASE WHEN source = 'user_correction' THEN 3 ELSE 1 END) as weighted_count
                   FROM sender_reputation
                   WHERE sender_email = ? AND account_id = ?
                   GROUP BY label_name
                   ORDER BY weighted_count DESC""",
                (sender_lower, account_id),
            ).fetchall()

            if not rows:
                return None

            total_weighted = sum(r[1] for r in rows)
            # Need at least 3 raw entries
            raw_count = conn.execute(
                "SELECT COUNT(*) FROM sender_reputation WHERE sender_email = ? AND account_id = ?",
                (sender_lower, account_id),
            ).fetchone()[0]

            if raw_count < 2:
                return None

            dominant_label = rows[0][0]
            dominant_weight = rows[0][1]
            dominance = dominant_weight / total_weighted if total_weighted > 0 else 0

            return {
                "dominant_label": dominant_label,
                "confidence": dominance,
                "count": raw_count,
            }

        except Exception as e:
            logger.debug(f"[SenderReputation] get_sender_reputation failed: {e}")
            return None

    def get_domain_reputation(
        self, domain: str, account_id: int = 1
    ) -> Optional[Dict]:
        """
        Retourne la réputation d'un domaine si 3+ entrées existent.
        Exclut les domaines communs (gmail, outlook, etc.).

        Returns:
            {"dominant_label": str, "confidence": float, "count": int} ou None
        """
        if not domain:
            return None

        domain_lower = domain.lower().strip()
        if domain_lower in COMMON_DOMAINS:
            return None

        try:
            conn = self._db._get_connection()
            rows = conn.execute(
                """SELECT label_name,
                          SUM(CASE WHEN source = 'user_correction' THEN 3 ELSE 1 END) as weighted_count
                   FROM sender_reputation
                   WHERE sender_domain = ? AND account_id = ?
                   GROUP BY label_name
                   ORDER BY weighted_count DESC""",
                (domain_lower, account_id),
            ).fetchall()

            if not rows:
                return None

            total_weighted = sum(r[1] for r in rows)
            raw_count = conn.execute(
                "SELECT COUNT(*) FROM sender_reputation WHERE sender_domain = ? AND account_id = ?",
                (domain_lower, account_id),
            ).fetchone()[0]

            if raw_count < 3:
                return None

            dominant_label = rows[0][0]
            dominant_weight = rows[0][1]
            dominance = dominant_weight / total_weighted if total_weighted > 0 else 0

            return {
                "dominant_label": dominant_label,
                "confidence": dominance,
                "count": raw_count,
            }

        except Exception as e:
            logger.debug(f"[SenderReputation] get_domain_reputation failed: {e}")
            return None

    def invalidate_sender(self, sender: str, account_id: int = 1) -> None:
        """Supprime toutes les entrées pour un expéditeur (après correction utilisateur)."""
        if not sender:
            return

        sender_lower = sender.lower().strip()
        try:
            conn = self._db._get_connection()
            conn.execute(
                "DELETE FROM sender_reputation WHERE sender_email = ? AND account_id = ?",
                (sender_lower, account_id),
            )
            conn.commit()
            logger.debug(f"[SenderReputation] Invalidated sender: {sender_lower}")
        except Exception as e:
            logger.debug(f"[SenderReputation] invalidate_sender failed: {e}")


def get_reputation_store() -> SenderReputationStore:
    """Singleton accessor."""
    return SenderReputationStore()
