# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter pour l'historique des brouillons.

Implemente DraftHistoryPort en utilisant JsonFileStore
pour la persistance JSON.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

from app.config import should_persist_email_content
from app.domain.ports.draft_history_port import DraftHistoryPort
from app.domain.entities.draft_history import DraftRecord
from .json_file_store import JsonFileStore


class LegacyDraftHistoryAdapter(JsonFileStore[DraftRecord], DraftHistoryPort):
    """
    Adapter pour l'historique des brouillons.

    Herite de JsonFileStore pour la persistance et implemente
    DraftHistoryPort pour respecter le contrat du domaine.
    """

    def __init__(self, history_file: Path = None):
        """
        Initialise l'adapter.

        Args:
            history_file: Chemin du fichier d'historique.
                         Si None, utilise le chemin par defaut.
        """
        if history_file is None:
            from app.config import PROJECT_ROOT
            history_file = PROJECT_ROOT / "data" / "history" / "drafts_history.json"
        super().__init__(history_file)

    @staticmethod
    def _unscoped_is_forbidden() -> bool:
        import os
        return os.environ.get("ALLOW_UNSCOPED_DRAFT_HISTORY", "0") != "1"

    _CONTENT_FIELDS = ("email_preview", "draft_v1", "critique", "draft_final")

    @classmethod
    def _minimize_record_dict(cls, record_dict: Dict[str, Any]) -> Dict[str, Any]:
        if should_persist_email_content():
            return record_dict
        for field in cls._CONTENT_FIELDS:
            record_dict[field] = ""
        return record_dict

    def _entity_to_dict(self, record: DraftRecord) -> Dict[str, Any]:
        """Convertit un DraftRecord en dict pour stockage."""
        return self._minimize_record_dict({
            "id": record.id,
            "timestamp": record.timestamp,
            "email_id": record.email_id,
            "email_sender": record.email_sender,
            "email_subject": record.email_subject,
            "email_preview": record.email_preview,
            "draft_v1": record.draft_v1,
            "critique": record.critique,
            "draft_final": record.draft_final,
            "status": record.status,
            "account_id": record.account_id,
            "draft_id": record.draft_id,
            "tokens_used": record.tokens_used,
            "model": record.model,
            "processing_time_ms": record.processing_time_ms,
            "priority_score": record.priority_score,
            "category": record.category,
            "feedback": record.feedback,
            "feedback_comment": record.feedback_comment,
            "feedback_rating": record.feedback_rating,
        })

    def _dict_to_entity(self, data: Dict[str, Any]) -> DraftRecord:
        """Convertit un dict en DraftRecord."""
        _account_raw = data.get("account_id")
        _account_id: Optional[int] = None
        if isinstance(_account_raw, int) and _account_raw > 0:
            _account_id = _account_raw
        elif isinstance(_account_raw, str) and _account_raw.isdigit():
            _account_id = int(_account_raw)
        return DraftRecord(
            id=data.get("id", ""),
            timestamp=data.get("timestamp", ""),
            email_id=data.get("email_id", ""),
            email_sender=data.get("email_sender", ""),
            email_subject=data.get("email_subject", ""),
            email_preview=data.get("email_preview", data.get("email_body", "")),
            draft_v1=data.get("draft_v1", ""),
            critique=data.get("critique", ""),
            draft_final=data.get("draft_final", ""),
            status=data.get("status", ""),
            account_id=_account_id,
            draft_id=data.get("draft_id"),
            tokens_used=data.get("tokens_used", 0),
            model=data.get("model", ""),
            processing_time_ms=data.get("processing_time_ms", 0),
            priority_score=data.get("priority_score"),
            category=data.get("category"),
            feedback=data.get("feedback"),
            feedback_comment=data.get("feedback_comment"),
            feedback_rating=data.get("feedback_rating"),
        )

    # =========================================================================
    # Implementation de DraftHistoryPort
    # =========================================================================

    def add(self, record: DraftRecord) -> None:
        """Ajoute ou met à jour un brouillon dans l'historique.

        Exige account_id > 0 en prod. Sous ALLOW_UNSCOPED_DRAFT_HISTORY=1
        (tests legacy / migrations), l'insertion sans account_id est tolérée
        — mais la ligne est marquée NULL et donc quarantinée à la lecture.
        """
        if (not record.account_id or record.account_id <= 0) and self._unscoped_is_forbidden():
            raise ValueError(
                "DraftRecord.account_id is required (must be > 0) for multi-account isolation."
            )
        # Vérifier si le brouillon existe déjà (éviter les doublons)
        records = self._load_raw()
        existing_idx = next(
            (i for i, r in enumerate(records) if r.get("id") == record.id),
            None
        )

        if existing_idx is not None:
            # Mettre à jour l'entrée existante
            records[existing_idx] = self._entity_to_dict(record)
        else:
            # Insérer en début de liste
            records.insert(0, self._entity_to_dict(record))

        self._save_raw(records)

    # =========================================================================
    # Méthodes scoped — filtrent sur account_id
    # =========================================================================

    def get_all_for_account(
        self, account_id: int, limit: int = 1000
    ) -> List[DraftRecord]:
        if not account_id or account_id <= 0:
            return []
        return [
            r for r in self._load_all()
            if r.account_id == account_id
        ][:limit]

    def get_by_id_for_account(
        self, draft_id: str, account_id: int
    ) -> Optional[DraftRecord]:
        if not account_id or account_id <= 0:
            return None
        for r in self._load_all():
            if r.id == draft_id and r.account_id == account_id:
                return r
        return None

    def get_recent_for_account(
        self, account_id: int, days: int = 7
    ) -> List[DraftRecord]:
        if not account_id or account_id <= 0:
            return []
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return [
            r for r in self._load_all()
            if r.account_id == account_id and r.timestamp >= cutoff
        ]

    def update_feedback_for_account(
        self,
        draft_id: str,
        account_id: int,
        feedback: str,
        rating: Optional[int] = None,
    ) -> bool:
        if not account_id or account_id <= 0:
            return False
        records = self._load_raw()
        for i, r in enumerate(records):
            if r.get("id") == draft_id and r.get("account_id") == account_id:
                r["feedback"] = feedback
                r["feedback_rating"] = rating
                records[i] = r
                self._save_raw(records)
                return True
        return False

    # =========================================================================
    # Méthodes non scopées — lèvent en prod
    # =========================================================================

    def get_by_id(self, draft_id: str) -> Optional[DraftRecord]:
        if self._unscoped_is_forbidden():
            raise RuntimeError(
                "get_by_id() non scopé interdit — utiliser get_by_id_for_account"
            )
        return self._find_by_key("id", draft_id)

    def get_all(self, limit: int = 1000) -> List[DraftRecord]:
        if self._unscoped_is_forbidden():
            raise RuntimeError(
                "get_all() non scopé interdit — utiliser get_all_for_account"
            )
        return self._load_all()[:limit]

    def get_recent(self, days: int = 7) -> List[DraftRecord]:
        if self._unscoped_is_forbidden():
            raise RuntimeError(
                "get_recent() non scopé interdit — utiliser get_recent_for_account"
            )
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return [
            record for record in self._load_all()
            if record.timestamp >= cutoff
        ]

    def update_feedback(
        self,
        draft_id: str,
        feedback: str,
        rating: Optional[int] = None,
    ) -> bool:
        if self._unscoped_is_forbidden():
            raise RuntimeError(
                "update_feedback() non scopé interdit — utiliser update_feedback_for_account"
            )
        return self._update_by_key(
            "id",
            draft_id,
            {"feedback": feedback, "feedback_rating": rating},
        )

    def get_with_feedback(self, limit: int = 100) -> List[DraftRecord]:
        """Recupere les brouillons ayant un feedback."""
        all_records = self._load_all()
        with_feedback = [r for r in all_records if r.feedback]
        return with_feedback[:limit]

    def count(self) -> int:
        """Compte le nombre total de brouillons."""
        return self._count()

    def count_by_status(self) -> dict:
        """Compte les brouillons par statut."""
        return self._count_by_field("status")

    def count_by_category(self) -> dict:
        """Compte les brouillons par categorie."""
        return self._count_by_field("category")

    def count_today(self) -> int:
        """Compte les brouillons créés aujourd'hui."""
        today = datetime.now().strftime("%Y-%m-%d")
        return sum(
            1 for record in self._load_raw()
            if record.get("timestamp", "").startswith(today)
        )

    def get_stats(self) -> dict:
        """
        Calcule les statistiques de l'historique.

        Returns:
            Dictionnaire de statistiques.
        """
        from collections import defaultdict

        records = self._load_raw()

        if not records:
            return {
                "total": 0,
                "validated_v1": 0,
                "corrected_v2": 0,
                "v1_percent": 0,
                "v2_percent": 0,
                "avg_rating": 0,
                "ratings_count": 0,
                "total_tokens": 0,
                "time_saved_minutes": 0,
                "time_saved_hours": 0,
                "avg_processing_time_ms": 0,
                "avg_processing_time_sec": 0,
                "automation_rate": 0,
                "daily_stats": [],
            }

        total = len(records)

        # Compter par statut
        validated_v1 = sum(1 for r in records if "V1" in r.get("status", ""))
        corrected_v2 = sum(1 for r in records if "V2" in r.get("status", ""))

        # Calcul des ratings
        ratings = [r.get("feedback_rating") for r in records if r.get("feedback_rating")]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0
        ratings_count = len(ratings)

        # Temps de traitement moyen
        processing_times = [
            r.get("processing_time_ms", 0)
            for r in records
            if r.get("processing_time_ms", 0) > 0
        ]
        avg_processing_time_ms = (
            sum(processing_times) / len(processing_times) if processing_times else 0
        )

        # Taux d'automatisation (V1 = 100%, V2 = 50%)
        automation_rate = (
            round((validated_v1 * 100 + corrected_v2 * 50) / total) if total > 0 else 0
        )

        total_tokens = sum(r.get("tokens_used", 0) for r in records)
        time_saved_minutes = total * 5  # 5 min par email traité

        # Statistiques journalières
        daily = defaultdict(lambda: {"date": "", "total": 0, "v1": 0, "v2": 0, "tokens": 0})
        for r in records:
            timestamp = r.get("timestamp", "")
            if timestamp:
                date = timestamp[:10]  # YYYY-MM-DD
                daily[date]["date"] = date
                daily[date]["total"] += 1
                if "V1" in r.get("status", ""):
                    daily[date]["v1"] += 1
                if "V2" in r.get("status", ""):
                    daily[date]["v2"] += 1
                daily[date]["tokens"] += r.get("tokens_used", 0)
        sorted_days = sorted(daily.values(), key=lambda x: x["date"])
        daily_stats = sorted_days[-30:]

        return {
            "total": total,
            "validated_v1": validated_v1,
            "corrected_v2": corrected_v2,
            "v1_percent": round(validated_v1 / total * 100) if total > 0 else 0,
            "v2_percent": round(corrected_v2 / total * 100) if total > 0 else 0,
            "avg_rating": round(avg_rating, 1),
            "ratings_count": ratings_count,
            "total_tokens": total_tokens,
            "time_saved_minutes": time_saved_minutes,
            "time_saved_hours": round(time_saved_minutes / 60, 1),
            "avg_processing_time_ms": round(avg_processing_time_ms),
            "avg_processing_time_sec": round(avg_processing_time_ms / 1000, 1),
            "automation_rate": automation_rate,
            "daily_stats": daily_stats,
        }
