# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter pour le systeme d'analytics.

Implemente AnalyticsPort en utilisant MultiFileJsonStore
pour la persistance JSON multi-fichiers.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.domain.ports.analytics_port import AnalyticsPort
from app.domain.entities.analytics import (
    QualityScore,
    QualityMetrics,
    AIVsHumanComparison,
    HumanEdit,
    PerformanceMetrics,
)
from .json_file_store import MultiFileJsonStore


class LegacyAnalyticsAdapter(MultiFileJsonStore, AnalyticsPort):
    """
    Adapter pour les analytics et metriques de qualite.

    Herite de MultiFileJsonStore pour gerer plusieurs fichiers JSON
    (quality metrics + human edits) et implemente AnalyticsPort.
    """

    QUALITY_FILE = "quality_metrics.json"
    EDITS_FILE = "human_edits.json"

    def __init__(self, data_dir: Path = None):
        """
        Initialise l'adapter.

        Args:
            data_dir: Repertoire de donnees.
                     Si None, utilise le chemin par defaut.
        """
        if data_dir is None:
            from app.config import PROJECT_ROOT
            data_dir = PROJECT_ROOT / "data" / "analytics"
        super().__init__(data_dir)

    # =========================================================================
    # Conversion QualityScore <-> Dict
    # =========================================================================

    def _score_to_dict(self, score: QualityScore) -> Dict[str, Any]:
        """Convertit un QualityScore en dict."""
        return {
            "draft_id": score.draft_id,
            "overall_score": score.overall_score,
            "tone_score": score.tone_score,
            "completeness_score": score.completeness_score,
            "professionalism_score": score.professionalism_score,
            "relevance_score": score.relevance_score,
            "user_rating": score.user_rating,
            "was_edited": score.was_edited,
            "edit_ratio": score.edit_ratio,
            "timestamp": score.timestamp or datetime.now().isoformat(),
        }

    def _dict_to_score(self, data: Dict[str, Any]) -> QualityScore:
        """Convertit un dict en QualityScore."""
        return QualityScore(
            draft_id=data.get("draft_id", ""),
            overall_score=data.get("overall_score", 0.0),
            tone_score=data.get("tone_score", 0.0),
            completeness_score=data.get("completeness_score", 0.0),
            professionalism_score=data.get("professionalism_score", 0.0),
            relevance_score=data.get("relevance_score", 0.0),
            user_rating=data.get("user_rating"),
            was_edited=data.get("was_edited", False),
            edit_ratio=data.get("edit_ratio", 0.0),
            timestamp=data.get("timestamp", ""),
        )

    # =========================================================================
    # Conversion HumanEdit <-> Dict
    # =========================================================================

    def _edit_to_dict(self, edit: HumanEdit) -> Dict[str, Any]:
        """Convertit un HumanEdit en dict."""
        return {
            "id": edit.id,
            "draft_id": edit.draft_id,
            "original_draft": edit.original_draft,
            "edited_draft": edit.edited_draft,
            "edit_distance": edit.edit_distance,
            "edit_ratio": edit.edit_ratio,
            "word_changes": edit.word_changes,
            "timestamp": edit.timestamp or datetime.now().isoformat(),
            "editor_notes": edit.editor_notes,
        }

    def _dict_to_edit(self, data: Dict[str, Any]) -> HumanEdit:
        """Convertit un dict en HumanEdit."""
        return HumanEdit(
            id=data.get("id", ""),
            draft_id=data.get("draft_id", ""),
            original_draft=data.get("original_draft", ""),
            edited_draft=data.get("edited_draft", ""),
            edit_distance=data.get("edit_distance", 0),
            edit_ratio=data.get("edit_ratio", 0.0),
            word_changes=data.get("word_changes", 0),
            timestamp=data.get("timestamp", ""),
            editor_notes=data.get("editor_notes", ""),
        )

    # =========================================================================
    # Helpers prives
    # =========================================================================

    def _load_quality(self) -> List[Dict[str, Any]]:
        """Charge les scores de qualite."""
        return self._load_file(self.QUALITY_FILE)

    def _save_quality(self, scores: List[Dict[str, Any]]) -> None:
        """Sauvegarde les scores."""
        self._save_file(self.QUALITY_FILE, scores)

    def _load_edits(self) -> List[Dict[str, Any]]:
        """Charge les modifications humaines."""
        return self._load_file(self.EDITS_FILE)

    def _save_edits(self, edits: List[Dict[str, Any]]) -> None:
        """Sauvegarde les modifications."""
        self._save_file(self.EDITS_FILE, edits)

    @staticmethod
    def _calculate_quality_level_counts(scores: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Calcule la repartition par niveau de qualite.

        Args:
            scores: Liste des scores.

        Returns:
            Dictionnaire {niveau: count}.
        """
        levels = {"excellent": 0, "good": 0, "acceptable": 0, "needs_improvement": 0}
        for score in scores:
            overall = score.get("overall_score", 0)
            if overall >= 90:
                levels["excellent"] += 1
            elif overall >= 75:
                levels["good"] += 1
            elif overall >= 50:
                levels["acceptable"] += 1
            else:
                levels["needs_improvement"] += 1
        return levels

    # =========================================================================
    # Metriques de qualite
    # =========================================================================

    def get_quality_metrics(self) -> Dict[str, Any]:
        """Recupere les metriques de qualite agregees."""
        scores = self._load_quality()
        total = len(scores)

        if total == 0:
            return {
                "avg_score": 0.0,
                "total_drafts": 0,
                "by_level": {
                    "excellent": 0,
                    "good": 0,
                    "acceptable": 0,
                    "needs_improvement": 0,
                },
            }

        total_score = sum(s.get("overall_score", 0) for s in scores)
        avg_score = total_score / total
        levels = self._calculate_quality_level_counts(scores)

        return {
            "avg_score": round(avg_score, 1),
            "total_drafts": total,
            "by_level": levels,
        }

    def get_detailed_quality_metrics(self) -> QualityMetrics:
        """Recupere les metriques de qualite detaillees."""
        metrics = self.get_quality_metrics()
        scores = self._load_quality()

        rated = [s for s in scores if s.get("user_rating") is not None]
        avg_rating = sum(s["user_rating"] for s in rated) / len(rated) if rated else 0.0

        return QualityMetrics(
            avg_score=metrics["avg_score"],
            total_drafts=metrics["total_drafts"],
            excellent_count=metrics["by_level"]["excellent"],
            good_count=metrics["by_level"]["good"],
            acceptable_count=metrics["by_level"]["acceptable"],
            needs_improvement_count=metrics["by_level"]["needs_improvement"],
            avg_user_rating=round(avg_rating, 1),
            rated_count=len(rated),
        )

    def record_quality_score(self, score: QualityScore) -> None:
        """Enregistre un score de qualite."""
        scores = self._load_quality()
        scores.insert(0, self._score_to_dict(score))
        self._save_quality(scores)

    def get_quality_score(self, draft_id: str) -> Optional[QualityScore]:
        """Recupere le score de qualite d'un brouillon."""
        for data in self._load_quality():
            if data.get("draft_id") == draft_id:
                return self._dict_to_score(data)
        return None

    # =========================================================================
    # Comparaison IA vs Humain
    # =========================================================================

    def get_ai_vs_human_comparison(self) -> Dict[str, Any]:
        """Compare les reponses IA avec les modifications humaines."""
        edits = self._load_edits()
        scores = self._load_quality()

        total = len(scores)
        edited = sum(1 for s in scores if s.get("was_edited", False))
        edit_rate = (edited / total * 100) if total > 0 else 0.0

        edit_ratios = [e.get("edit_ratio", 0) for e in edits]
        avg_edit_ratio = sum(edit_ratios) / len(edit_ratios) if edit_ratios else 0.0

        return {
            "total_drafts": total,
            "edited_count": edited,
            "edit_rate": round(edit_rate, 1),
            "avg_edit_ratio": round(avg_edit_ratio, 3),
        }

    def get_detailed_comparison(self) -> AIVsHumanComparison:
        """Recupere la comparaison detaillee IA vs humain."""
        comparison = self.get_ai_vs_human_comparison()
        edits = self._load_edits()

        word_changes = [e.get("word_changes", 0) for e in edits]
        avg_word_changes = sum(word_changes) / len(word_changes) if word_changes else 0.0

        return AIVsHumanComparison(
            total_drafts=comparison["total_drafts"],
            edited_count=comparison["edited_count"],
            edit_rate=comparison["edit_rate"],
            avg_edit_ratio=comparison["avg_edit_ratio"],
            avg_word_changes=round(avg_word_changes, 1),
            common_edit_types=[],
        )

    def record_human_edit(self, edit: HumanEdit) -> None:
        """Enregistre une modification humaine."""
        edits = self._load_edits()
        edits.insert(0, self._edit_to_dict(edit))
        self._save_edits(edits)

    def get_human_edits(self, limit: int = 100) -> List[HumanEdit]:
        """Recupere les modifications humaines recentes."""
        return [self._dict_to_edit(e) for e in self._load_edits()[:limit]]

    # =========================================================================
    # Performance
    # =========================================================================

    def get_performance_metrics(
        self,
        period_days: int = 30,
    ) -> PerformanceMetrics:
        """Recupere les metriques de performance sur une periode."""
        cutoff = (datetime.now() - timedelta(days=period_days)).isoformat()
        scores = self._load_quality()

        recent = [s for s in scores if s.get("timestamp", "") >= cutoff]
        total = len(recent)

        if total == 0:
            return PerformanceMetrics(
                period_start=cutoff,
                period_end=datetime.now().isoformat(),
            )

        avg_score = sum(s.get("overall_score", 0) for s in recent) / total
        rated = [s for s in recent if s.get("user_rating")]
        avg_rating = sum(s["user_rating"] for s in rated) / len(rated) if rated else 0.0
        edited = sum(1 for s in recent if s.get("was_edited", False))
        edit_rate = edited / total * 100

        return PerformanceMetrics(
            period_start=cutoff,
            period_end=datetime.now().isoformat(),
            total_drafts=total,
            avg_quality_score=round(avg_score, 1),
            avg_user_rating=round(avg_rating, 1),
            edit_rate=round(edit_rate, 1),
        )

    def get_trend(self, metric: str, days: int = 30) -> List[Dict[str, Any]]:
        """Recupere la tendance d'une metrique."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        scores = self._load_quality()
        recent = [s for s in scores if s.get("timestamp", "") >= cutoff]

        # Grouper par jour
        by_day: Dict[str, List[Dict[str, Any]]] = {}
        for score in recent:
            date = score.get("timestamp", "")[:10]
            if date not in by_day:
                by_day[date] = []
            by_day[date].append(score)

        trend = []
        for date, items in sorted(by_day.items()):
            if metric == "quality_score":
                value = sum(i.get("overall_score", 0) for i in items) / len(items)
            elif metric == "user_rating":
                rated = [i for i in items if i.get("user_rating")]
                value = sum(i["user_rating"] for i in rated) / len(rated) if rated else 0
            else:
                value = len(items)

            trend.append({"date": date, "value": round(value, 1)})

        return trend
