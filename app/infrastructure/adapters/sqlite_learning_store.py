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
Adapters SQLite pour le système d'apprentissage.

Implémentent les ports du domaine avec persistance SQLite
au lieu du stockage JSON.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Set

from app.domain.entities.learning import (
    LearnedPattern,
    PatternType,
    PromptAdjustment,
)
from app.domain.ports.learning_port import (
    AdjustmentStorePort,
    LearningPatternStorePort,
)
from app.domain.ports.processed_emails_port import ProcessedEmailsTrackerPort
from app.domain.entities.draft_history import DraftRecord
from app.domain.ports.draft_history_port import DraftHistoryPort
from app.config import should_persist_email_content
from app.infrastructure.database import Database

logger = logging.getLogger(__name__)


# =============================================================================
# LEARNED PATTERNS
# =============================================================================


class SqliteLearningPatternStore(LearningPatternStorePort):
    """Adapter SQLite pour les patterns appris."""

    def __init__(self, database: Database) -> None:
        self.db = database

    @staticmethod
    def _examples_for_storage(pattern: LearnedPattern) -> List[str]:
        if should_persist_email_content():
            return pattern.examples
        return []

    def _row_to_entity(self, row: Dict[str, Any]) -> LearnedPattern:
        raw = dict(row)
        examples = json.loads(raw.get("examples") or "[]")
        if not should_persist_email_content():
            examples = []
        return LearnedPattern(
            id=str(raw["id"]),
            timestamp=datetime.fromisoformat(raw["created_at"]),
            pattern_type=PatternType(raw["pattern_type"]),
            trigger=raw["pattern_value"],
            correction=raw.get("correction", ""),
            examples=examples,
            frequency=raw.get("occurrences", 1),
            confidence=raw.get("confidence", 0.5),
        )

    def save(self, pattern: LearnedPattern) -> str:
        self.db.execute(
            """INSERT INTO learned_patterns
            (pattern_type, pattern_value, correction, examples, confidence, occurrences)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                pattern.pattern_type.value,
                pattern.trigger,
                pattern.correction,
                json.dumps(self._examples_for_storage(pattern), ensure_ascii=False),
                pattern.confidence,
                pattern.frequency,
            ),
        )
        self.db.commit()
        row = self.db.fetchone(
            "SELECT last_insert_rowid() as id"
        )
        return str(row["id"]) if row else pattern.id

    def save_many(self, patterns: List[LearnedPattern]) -> List[str]:
        ids = []
        for p in patterns:
            ids.append(self.save(p))
        return ids

    def get_by_id(self, pattern_id: str) -> Optional[LearnedPattern]:
        row = self.db.fetchone(
            "SELECT * FROM learned_patterns WHERE id = ?", (pattern_id,)
        )
        return self._row_to_entity(row) if row else None

    def list_all(self, limit: int = 100) -> List[LearnedPattern]:
        rows = self.db.fetchall(
            "SELECT * FROM learned_patterns WHERE is_active = 1 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_entity(r) for r in rows]

    def get_by_type(self, pattern_type: PatternType) -> List[LearnedPattern]:
        rows = self.db.fetchall(
            "SELECT * FROM learned_patterns WHERE pattern_type = ? AND is_active = 1",
            (pattern_type.value,),
        )
        return [self._row_to_entity(r) for r in rows]

    def update(self, pattern: LearnedPattern) -> bool:
        cursor = self.db.execute(
            """UPDATE learned_patterns
            SET pattern_value = ?, correction = ?, examples = ?,
                confidence = ?, occurrences = ?, last_seen_at = ?
            WHERE id = ?""",
            (
                pattern.trigger,
                pattern.correction,
                json.dumps(self._examples_for_storage(pattern), ensure_ascii=False),
                pattern.confidence,
                pattern.frequency,
                datetime.now().isoformat(),
                pattern.id,
            ),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def count(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) as c FROM learned_patterns WHERE is_active = 1"
        )
        return row["c"] if row else 0

    def count_by_type(self) -> dict:
        rows = self.db.fetchall(
            """SELECT pattern_type, COUNT(*) as c
            FROM learned_patterns WHERE is_active = 1
            GROUP BY pattern_type"""
        )
        return {r["pattern_type"]: r["c"] for r in rows}


# =============================================================================
# PROMPT ADJUSTMENTS
# =============================================================================


class SqliteAdjustmentStore(AdjustmentStorePort):
    """Adapter SQLite pour les ajustements de prompt."""

    def __init__(self, database: Database) -> None:
        self.db = database
        self._ensure_columns()

    def _ensure_columns(self) -> None:
        """Ajoute les colonnes manquantes au schéma existant."""
        try:
            self.db.execute(
                "ALTER TABLE prompt_adjustments ADD COLUMN section TEXT DEFAULT ''"
            )
            self.db.commit()
        except Exception:
            pass  # colonne existe déjà

    def _row_to_entity(self, row: Dict[str, Any]) -> PromptAdjustment:
        raw = dict(row)
        return PromptAdjustment(
            id=str(raw["id"]),
            timestamp=datetime.fromisoformat(raw["created_at"]),
            section=raw.get("section", ""),
            adjustment=raw["adjustment"],
            reason=raw.get("reason", ""),
            active=bool(raw.get("is_active", 1)),
        )

    def save(self, adjustment: PromptAdjustment) -> str:
        self.db.execute(
            """INSERT INTO prompt_adjustments
            (adjustment, reason, section, is_active)
            VALUES (?, ?, ?, ?)""",
            (
                adjustment.adjustment,
                adjustment.reason,
                adjustment.section,
                1 if adjustment.active else 0,
            ),
        )
        self.db.commit()
        row = self.db.fetchone("SELECT last_insert_rowid() as id")
        return str(row["id"]) if row else adjustment.id

    def get_by_id(self, adjustment_id: str) -> Optional[PromptAdjustment]:
        row = self.db.fetchone(
            "SELECT * FROM prompt_adjustments WHERE id = ?",
            (adjustment_id,),
        )
        return self._row_to_entity(row) if row else None

    def get_active(self) -> List[PromptAdjustment]:
        rows = self.db.fetchall(
            "SELECT * FROM prompt_adjustments WHERE is_active = 1 ORDER BY created_at DESC"
        )
        return [self._row_to_entity(r) for r in rows]

    def list_all(self) -> List[PromptAdjustment]:
        rows = self.db.fetchall(
            "SELECT * FROM prompt_adjustments ORDER BY created_at DESC"
        )
        return [self._row_to_entity(r) for r in rows]

    def update(self, adjustment: PromptAdjustment) -> bool:
        cursor = self.db.execute(
            """UPDATE prompt_adjustments
            SET adjustment = ?, reason = ?, section = ?,
                is_active = ?, applied_count = applied_count
            WHERE id = ?""",
            (
                adjustment.adjustment,
                adjustment.reason,
                adjustment.section,
                1 if adjustment.active else 0,
                adjustment.id,
            ),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def count_active(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) as c FROM prompt_adjustments WHERE is_active = 1"
        )
        return row["c"] if row else 0


# =============================================================================
# DRAFT HISTORY
# =============================================================================


class SqliteDraftHistoryAdapter(DraftHistoryPort):
    """Adapter SQLite pour l'historique des brouillons."""

    def __init__(self, database: Database) -> None:
        self.db = database

    # Environnement : seules les méthodes scoped sont autorisées en prod.
    # ALLOW_UNSCOPED_DRAFT_HISTORY=1 autorise temporairement les méthodes
    # non scopées (pour migration et tests legacy uniquement).
    @staticmethod
    def _unscoped_is_forbidden() -> bool:
        import os
        return os.environ.get("ALLOW_UNSCOPED_DRAFT_HISTORY", "0") != "1"

    def _row_to_entity(self, row: Dict[str, Any]) -> DraftRecord:
        raw = dict(row)
        _account_id = raw.get("account_id")
        return DraftRecord(
            id=str(raw["id"]),
            timestamp=raw.get("created_at", ""),
            email_id=raw.get("email_id", ""),
            email_sender=raw.get("email_sender", ""),
            email_subject=raw.get("email_subject", ""),
            email_preview=raw.get("email_body", "")[:100] if raw.get("email_body") else "",
            draft_v1=raw.get("draft_v1") or "",
            critique=raw.get("critique") or "",
            draft_final=raw.get("draft_final") or "",
            status=raw.get("status", ""),
            account_id=int(_account_id) if _account_id is not None else None,
            draft_id=raw.get("draft_id"),
            tokens_used=raw.get("tokens_used", 0),
            model=raw.get("model", ""),
            processing_time_ms=raw.get("processing_time_ms", 0),
            priority_score=raw.get("priority_score", 50),
            category=raw.get("category", "NORMAL"),
            feedback=raw.get("feedback"),
            feedback_comment=None,
            feedback_rating=raw.get("feedback_score"),
        )

    def add(self, record: DraftRecord) -> None:
        """Insère un draft. Exige account_id > 0 en prod.

        Sous ALLOW_UNSCOPED_DRAFT_HISTORY=1 (tests legacy / migrations),
        insère tel quel avec account_id NULL — la row reste quarantinée
        à la lecture puisque les méthodes scoped filtrent sur account_id.
        """
        if (not record.account_id or record.account_id <= 0) and self._unscoped_is_forbidden():
            raise ValueError(
                "DraftRecord.account_id is required (must be > 0) for multi-account isolation. "
                "Résolvez-le via _resolve_account_id_for_user() ou le contexte daemon."
            )
        persist_content = should_persist_email_content()
        self.db.execute(
            """INSERT INTO draft_history
            (account_id, email_id, email_sender, email_subject, email_body,
             draft_v1, critique, draft_final, status, draft_id,
             tokens_used, model, processing_time_ms, priority_score,
             category, feedback, feedback_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.account_id,
                record.email_id,
                record.email_sender,
                record.email_subject,
                record.email_preview if persist_content else None,
                record.draft_v1 if persist_content else None,
                record.critique if persist_content else None,
                record.draft_final if persist_content else None,
                record.status,
                record.draft_id,
                record.tokens_used,
                record.model,
                record.processing_time_ms,
                record.priority_score,
                record.category,
                record.feedback,
                record.feedback_rating,
            ),
        )
        self.db.commit()

    # =========================================================================
    # Méthodes scoped par account_id — toujours préférer celles-ci
    # =========================================================================

    def get_all_for_account(
        self, account_id: int, limit: int = 1000
    ) -> List[DraftRecord]:
        if not account_id or account_id <= 0:
            return []
        rows = self.db.fetchall(
            """SELECT * FROM draft_history
            WHERE account_id = ?
            ORDER BY created_at DESC LIMIT ?""",
            (account_id, limit),
        )
        return [self._row_to_entity(r) for r in rows]

    def get_by_id_for_account(
        self, draft_id: str, account_id: int
    ) -> Optional[DraftRecord]:
        if not account_id or account_id <= 0:
            return None
        row = self.db.fetchone(
            """SELECT * FROM draft_history
            WHERE (id = ? OR draft_id = ?) AND account_id = ?""",
            (draft_id, draft_id, account_id),
        )
        return self._row_to_entity(row) if row else None

    def get_recent_for_account(
        self, account_id: int, days: int = 7
    ) -> List[DraftRecord]:
        if not account_id or account_id <= 0:
            return []
        rows = self.db.fetchall(
            """SELECT * FROM draft_history
            WHERE account_id = ?
              AND created_at >= datetime('now', ?)
            ORDER BY created_at DESC""",
            (account_id, f"-{days} days"),
        )
        return [self._row_to_entity(r) for r in rows]

    def update_feedback_for_account(
        self,
        draft_id: str,
        account_id: int,
        feedback: str,
        rating: Optional[int] = None,
    ) -> bool:
        if not account_id or account_id <= 0:
            return False
        cursor = self.db.execute(
            """UPDATE draft_history
            SET feedback = ?, feedback_score = ?
            WHERE (id = ? OR draft_id = ?) AND account_id = ?""",
            (feedback, rating, draft_id, draft_id, account_id),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def get_stats_for_account(self, account_id: int) -> dict:
        """Stats d'historique scopés à un seul compte (M-3 fix).

        Empty stats si account_id <= 0 — évite le leak global du dashboard
        legacy quand aucun compte courant n'est résolu.
        """
        empty = {
            "total": 0, "validated_v1": 0, "corrected_v2": 0,
            "v1_percent": 0, "v2_percent": 0,
            "by_category": {}, "by_status": {},
            "daily_stats": [],
        }
        if not account_id or account_id <= 0:
            return empty

        total_row = self.db.fetchone(
            "SELECT COUNT(*) as c FROM draft_history WHERE account_id = ?",
            (account_id,),
        )
        total = total_row["c"] if total_row else 0
        if total == 0:
            return empty

        v1_row = self.db.fetchone(
            "SELECT COUNT(*) as c FROM draft_history WHERE account_id = ? AND status LIKE '%V1%'",
            (account_id,),
        )
        v2_row = self.db.fetchone(
            "SELECT COUNT(*) as c FROM draft_history WHERE account_id = ? AND status LIKE '%V2%'",
            (account_id,),
        )
        validated_v1 = v1_row["c"] if v1_row else 0
        corrected_v2 = v2_row["c"] if v2_row else 0

        cat_rows = self.db.fetchall(
            "SELECT category, COUNT(*) as c FROM draft_history WHERE account_id = ? GROUP BY category",
            (account_id,),
        )
        status_rows = self.db.fetchall(
            "SELECT status, COUNT(*) as c FROM draft_history WHERE account_id = ? GROUP BY status",
            (account_id,),
        )
        daily_rows = self.db.fetchall(
            """SELECT date(created_at) as d, COUNT(*) as c
               FROM draft_history WHERE account_id = ?
               GROUP BY date(created_at) ORDER BY d DESC LIMIT 30""",
            (account_id,),
        )

        return {
            "total": total,
            "validated_v1": validated_v1,
            "corrected_v2": corrected_v2,
            "v1_percent": round(validated_v1 / total * 100) if total else 0,
            "v2_percent": round(corrected_v2 / total * 100) if total else 0,
            "by_category": {r["category"] or "NORMAL": r["c"] for r in cat_rows},
            "by_status": {r["status"] or "": r["c"] for r in status_rows},
            "daily_stats": [{"date": r["d"], "total": r["c"]} for r in reversed(daily_rows)],
        }

    # =========================================================================
    # Méthodes non scopées — interdites en prod, conservées pour admin only
    # =========================================================================

    def get_by_id(self, draft_id: str) -> Optional[DraftRecord]:
        if self._unscoped_is_forbidden():
            raise RuntimeError(
                "get_by_id() non scopé interdit — utiliser get_by_id_for_account(draft_id, account_id)"
            )
        row = self.db.fetchone(
            "SELECT * FROM draft_history WHERE id = ? OR draft_id = ?",
            (draft_id, draft_id),
        )
        return self._row_to_entity(row) if row else None

    def get_all(self, limit: int = 1000) -> List[DraftRecord]:
        if self._unscoped_is_forbidden():
            raise RuntimeError(
                "get_all() non scopé interdit — utiliser get_all_for_account(account_id)"
            )
        rows = self.db.fetchall(
            "SELECT * FROM draft_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_entity(r) for r in rows]

    def get_recent(self, days: int = 7) -> List[DraftRecord]:
        if self._unscoped_is_forbidden():
            raise RuntimeError(
                "get_recent() non scopé interdit — utiliser get_recent_for_account(account_id)"
            )
        rows = self.db.fetchall(
            """SELECT * FROM draft_history
            WHERE created_at >= datetime('now', ?)
            ORDER BY created_at DESC""",
            (f"-{days} days",),
        )
        return [self._row_to_entity(r) for r in rows]

    def update_feedback(
        self, draft_id: str, feedback: str, rating: Optional[int] = None
    ) -> bool:
        if self._unscoped_is_forbidden():
            raise RuntimeError(
                "update_feedback() non scopé interdit — utiliser update_feedback_for_account"
            )
        cursor = self.db.execute(
            "UPDATE draft_history SET feedback = ?, feedback_score = ? WHERE id = ? OR draft_id = ?",
            (feedback, rating, draft_id, draft_id),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def get_with_feedback(self, limit: int = 100) -> List[DraftRecord]:
        # Admin/analytics only — en prod on loggue pour surveillance.
        if self._unscoped_is_forbidden():
            logger.warning(
                "get_with_feedback() appelé en mode unscoped — utilisation admin/analytics only"
            )
        rows = self.db.fetchall(
            """SELECT * FROM draft_history
            WHERE feedback IS NOT NULL AND feedback != ''
            ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        return [self._row_to_entity(r) for r in rows]

    def count(self) -> int:
        row = self.db.fetchone("SELECT COUNT(*) as c FROM draft_history")
        return row["c"] if row else 0

    def count_by_status(self) -> dict:
        rows = self.db.fetchall(
            "SELECT status, COUNT(*) as c FROM draft_history GROUP BY status"
        )
        return {r["status"]: r["c"] for r in rows}

    def count_by_category(self) -> dict:
        rows = self.db.fetchall(
            "SELECT category, COUNT(*) as c FROM draft_history GROUP BY category"
        )
        return {r["category"]: r["c"] for r in rows}

    def count_today(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) as c FROM draft_history WHERE date(created_at) = date('now')"
        )
        return row["c"] if row else 0


# =============================================================================
# PROCESSED EMAILS TRACKER
# =============================================================================


class SqliteProcessedEmailsTracker(ProcessedEmailsTrackerPort):
    """Adapter SQLite pour le suivi des emails traités."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def is_processed(self, item_id: str) -> bool:
        row = self.db.fetchone(
            "SELECT id FROM processed_emails WHERE id = ?", (item_id,)
        )
        return row is not None

    def mark_processed(self, item_id: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO processed_emails (id) VALUES (?)",
            (item_id,),
        )
        self.db.commit()

    def count(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) as c FROM processed_emails"
        )
        return row["c"] if row else 0

    def get_all_ids(self) -> Set[str]:
        rows = self.db.fetchall("SELECT id FROM processed_emails")
        return {r["id"] for r in rows}

    def clear(self) -> None:
        self.db.execute("DELETE FROM processed_emails")
        self.db.commit()
