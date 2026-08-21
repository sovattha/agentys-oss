# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Analytics et métriques de qualité pour Agentys.

Ce module permet de :
- Comparer les réponses IA vs réponses humaines
- Analyser la qualité des réponses générées
- Calculer des scores de performance
- Générer des rapports d'analytics
"""

import json
from datetime import datetime, timedelta
from dataclasses import asdict
from typing import List, Optional
from collections import defaultdict

from app.config import PROJECT_ROOT
from app.domain.entities.analytics import HumanEdit, PerformanceMetrics, QualityScore
from app.history import draft_history


# ============================================================================
# CONFIGURATION
# ============================================================================

ANALYTICS_DIR = PROJECT_ROOT / "data" / "analytics"
HUMAN_EDITS_FILE = ANALYTICS_DIR / "human_edits.json"
QUALITY_METRICS_FILE = ANALYTICS_DIR / "quality_metrics.json"


__all__ = [
    "HumanEdit",
    "QualityScore",
    "PerformanceMetrics",
    "AnalyticsManager",
    "get_analytics_manager",
    "ANALYTICS_DIR",
    "HUMAN_EDITS_FILE",
    "QUALITY_METRICS_FILE",
]


# ============================================================================
# GESTIONNAIRE D'ANALYTICS
# ============================================================================

class AnalyticsManager:
    """
    Gestionnaire des analytics et métriques de qualité.
    """

    def __init__(self):
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Crée les dossiers si nécessaire."""
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)

    # ========================================================================
    # COMPARAISON IA VS HUMAIN
    # ========================================================================

    def record_human_edit(
        self,
        draft_id: str,
        original_draft: str,
        edited_draft: str,
        editor_notes: str = ""
    ) -> HumanEdit:
        """
        Enregistre une modification humaine sur un brouillon.

        Args:
            draft_id: ID du brouillon original
            original_draft: Texte original généré par l'IA
            edited_draft: Texte modifié par l'humain
            editor_notes: Notes de l'éditeur

        Returns:
            HumanEdit enregistré
        """
        import uuid

        # Calculer les métriques de modification
        edit_distance = self._levenshtein_distance(original_draft, edited_draft)
        max_len = max(len(original_draft), len(edited_draft))
        edit_ratio = edit_distance / max_len if max_len > 0 else 0

        # Compter les mots changés
        original_words = set(original_draft.lower().split())
        edited_words = set(edited_draft.lower().split())
        word_changes = len(original_words.symmetric_difference(edited_words))

        edit = HumanEdit(
            id=str(uuid.uuid4())[:8],
            draft_id=draft_id,
            original_draft=original_draft,
            edited_draft=edited_draft,
            edit_distance=edit_distance,
            edit_ratio=round(edit_ratio, 4),
            word_changes=word_changes,
            timestamp=datetime.now().isoformat(),
            editor_notes=editor_notes,
        )

        # Sauvegarder
        edits = self._load_human_edits()
        edits.append(asdict(edit))
        self._save_human_edits(edits)

        # Mettre à jour le score de qualité
        self._update_quality_from_edit(draft_id, edit_ratio)

        return edit

    def get_human_edits(self, limit: int = 100) -> List[HumanEdit]:
        """Récupère les modifications humaines récentes."""
        edits = self._load_human_edits()
        return [HumanEdit(**e) for e in edits[-limit:]]

    def get_ai_vs_human_comparison(self) -> dict:
        """
        Génère une comparaison IA vs réponses humaines.

        Returns:
            Dictionnaire avec métriques de comparaison
        """
        edits = self._load_human_edits()

        if not edits:
            return {
                "total_edits": 0,
                "avg_edit_ratio": 0,
                "avg_similarity": 100,
                "distribution": {},
                "common_changes": [],
            }

        # Calculer les statistiques
        total = len(edits)
        avg_ratio = sum(e.get("edit_ratio", 0) for e in edits) / total
        avg_similarity = (1 - avg_ratio) * 100

        # Distribution par niveau de modification
        distribution = {
            "no_change": sum(1 for e in edits if e.get("edit_ratio", 0) < 0.05),
            "minor": sum(1 for e in edits if 0.05 <= e.get("edit_ratio", 0) < 0.2),
            "moderate": sum(1 for e in edits if 0.2 <= e.get("edit_ratio", 0) < 0.5),
            "major": sum(1 for e in edits if e.get("edit_ratio", 0) >= 0.5),
        }

        # Analyser les types de changements courants
        common_changes = self._analyze_common_changes(edits)

        return {
            "total_edits": total,
            "avg_edit_ratio": round(avg_ratio * 100, 1),
            "avg_similarity": round(avg_similarity, 1),
            "distribution": distribution,
            "common_changes": common_changes[:5],
        }

    # ========================================================================
    # SCORES DE QUALITÉ
    # ========================================================================

    def record_quality_score(
        self,
        draft_id: str,
        tone_score: float = 0,
        completeness_score: float = 0,
        professionalism_score: float = 0,
        relevance_score: float = 0,
        user_rating: Optional[int] = None,
    ) -> QualityScore:
        """
        Enregistre un score de qualité pour un brouillon.

        Args:
            draft_id: ID du brouillon
            tone_score: Score de ton (0-100)
            completeness_score: Score de complétude (0-100)
            professionalism_score: Score de professionnalisme (0-100)
            relevance_score: Score de pertinence (0-100)
            user_rating: Note utilisateur (1-5)

        Returns:
            QualityScore enregistré
        """
        # Calculer le score global
        scores = [s for s in [tone_score, completeness_score,
                              professionalism_score, relevance_score] if s > 0]
        overall_score = sum(scores) / len(scores) if scores else 0

        # Ajuster avec la note utilisateur si présente
        if user_rating:
            user_score = (user_rating / 5) * 100
            overall_score = (overall_score * 0.7) + (user_score * 0.3)

        quality = QualityScore(
            draft_id=draft_id,
            overall_score=round(overall_score, 1),
            tone_score=tone_score,
            completeness_score=completeness_score,
            professionalism_score=professionalism_score,
            relevance_score=relevance_score,
            user_rating=user_rating,
            timestamp=datetime.now().isoformat(),
        )

        # Sauvegarder
        metrics = self._load_quality_metrics()
        metrics.append(asdict(quality))
        self._save_quality_metrics(metrics)

        return quality

    def get_quality_stats(self) -> dict:
        """
        Calcule les statistiques de qualité globales.

        Returns:
            Dictionnaire avec les statistiques de qualité
        """
        metrics = self._load_quality_metrics()

        if not metrics:
            return {
                "total_scored": 0,
                "avg_overall_score": 0,
                "avg_user_rating": 0,
                "score_distribution": {},
                "by_category": {},
                "trend": [],
            }

        total = len(metrics)

        # Moyennes
        avg_score = sum(m.get("overall_score", 0) for m in metrics) / total
        ratings = [m.get("user_rating") for m in metrics if m.get("user_rating")]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0

        # Distribution par niveau
        score_distribution = {
            "excellent": sum(1 for m in metrics if m.get("overall_score", 0) >= 90),
            "good": sum(1 for m in metrics if 75 <= m.get("overall_score", 0) < 90),
            "acceptable": sum(1 for m in metrics if 50 <= m.get("overall_score", 0) < 75),
            "needs_improvement": sum(1 for m in metrics if m.get("overall_score", 0) < 50),
        }

        # Tendance sur les 7 derniers jours
        trend = self._calculate_quality_trend(metrics, days=7)

        return {
            "total_scored": total,
            "avg_overall_score": round(avg_score, 1),
            "avg_user_rating": round(avg_rating, 2),
            "score_distribution": score_distribution,
            "trend": trend,
        }

    def auto_score_draft(self, draft_text: str, email_context: dict) -> QualityScore:
        """
        Calcule automatiquement un score de qualité pour un brouillon.

        Utilise des heuristiques simples pour évaluer la qualité.

        Args:
            draft_text: Texte du brouillon
            email_context: Contexte de l'email original

        Returns:
            QualityScore calculé
        """
        import uuid

        scores = {}

        # Vérifier le ton
        scores["tone"] = self._score_tone(draft_text)

        # Vérifier la complétude
        scores["completeness"] = self._score_completeness(draft_text, email_context)

        # Vérifier le professionnalisme
        scores["professionalism"] = self._score_professionalism(draft_text)

        # Vérifier la pertinence
        scores["relevance"] = self._score_relevance(draft_text, email_context)

        return QualityScore(
            draft_id=str(uuid.uuid4())[:8],
            overall_score=round(sum(scores.values()) / len(scores), 1),
            tone_score=scores["tone"],
            completeness_score=scores["completeness"],
            professionalism_score=scores["professionalism"],
            relevance_score=scores["relevance"],
            timestamp=datetime.now().isoformat(),
        )

    # ========================================================================
    # MÉTRIQUES DE PERFORMANCE
    # ========================================================================

    def get_performance_metrics(self, days: int = 30) -> PerformanceMetrics:
        """
        Calcule les métriques de performance sur une période.

        Args:
            days: Nombre de jours à analyser

        Returns:
            PerformanceMetrics pour la période
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Récupérer les données
        quality_metrics = self._load_quality_metrics()
        human_edits = self._load_human_edits()
        draft_stats = draft_history.get_stats()

        # Filtrer par période
        quality_in_period = [
            m for m in quality_metrics
            if m.get("timestamp") and
            start_date <= datetime.fromisoformat(m["timestamp"]) <= end_date
        ]

        edits_in_period = [
            e for e in human_edits
            if e.get("timestamp") and
            start_date <= datetime.fromisoformat(e["timestamp"]) <= end_date
        ]

        # Calculer les métriques
        total_drafts = draft_stats.get("total", 0)
        avg_quality = (
            sum(m.get("overall_score", 0) for m in quality_in_period) /
            len(quality_in_period) if quality_in_period else 0
        )

        ratings = [m.get("user_rating") for m in quality_in_period if m.get("user_rating")]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0

        edit_rate = (len(edits_in_period) / total_drafts * 100) if total_drafts > 0 else 0
        avg_edit_ratio = (
            sum(e.get("edit_ratio", 0) for e in edits_in_period) /
            len(edits_in_period) if edits_in_period else 0
        )

        v1_rate = draft_stats.get("v1_percent", 0)

        # Calculer la tendance d'amélioration
        improvement_trend = self._calculate_improvement_trend(quality_in_period)

        return PerformanceMetrics(
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
            total_drafts=total_drafts,
            avg_quality_score=round(avg_quality, 1),
            avg_user_rating=round(avg_rating, 2),
            edit_rate=round(edit_rate, 1),
            avg_edit_ratio=round(avg_edit_ratio * 100, 1),
            v1_acceptance_rate=v1_rate,
            improvement_trend=round(improvement_trend, 2),
        )

    def get_analytics_summary(self) -> dict:
        """
        Génère un résumé complet des analytics.

        Returns:
            Dictionnaire avec toutes les métriques
        """
        return {
            "quality": self.get_quality_stats(),
            "comparison": self.get_ai_vs_human_comparison(),
            "performance": asdict(self.get_performance_metrics()),
            "recommendations": self._generate_recommendations(),
        }

    # ========================================================================
    # MÉTHODES PRIVÉES
    # ========================================================================

    def _load_human_edits(self) -> List[dict]:
        """Charge les modifications humaines."""
        if not HUMAN_EDITS_FILE.exists():
            return []
        try:
            return json.loads(HUMAN_EDITS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_human_edits(self, edits: List[dict]) -> None:
        """Sauvegarde les modifications humaines."""
        HUMAN_EDITS_FILE.write_text(
            json.dumps(edits, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def _load_quality_metrics(self) -> List[dict]:
        """Charge les métriques de qualité."""
        if not QUALITY_METRICS_FILE.exists():
            return []
        try:
            return json.loads(QUALITY_METRICS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_quality_metrics(self, metrics: List[dict]) -> None:
        """Sauvegarde les métriques de qualité."""
        QUALITY_METRICS_FILE.write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calcule la distance de Levenshtein entre deux chaînes."""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def _analyze_common_changes(self, edits: List[dict]) -> List[dict]:
        """Analyse les types de changements courants."""
        change_types = defaultdict(int)

        for edit in edits:
            ratio = edit.get("edit_ratio", 0)
            if ratio < 0.1:
                change_types["punctuation"] += 1
            elif ratio < 0.3:
                change_types["wording"] += 1
            elif ratio < 0.5:
                change_types["restructuring"] += 1
            else:
                change_types["rewrite"] += 1

        return [
            {"type": k, "count": v}
            for k, v in sorted(change_types.items(), key=lambda x: -x[1])
        ]

    def _update_quality_from_edit(self, draft_id: str, edit_ratio: float) -> None:
        """Met à jour le score de qualité basé sur les modifications."""
        metrics = self._load_quality_metrics()

        for m in metrics:
            if m.get("draft_id") == draft_id:
                m["was_edited"] = True
                m["edit_ratio"] = edit_ratio
                # Réduire le score si beaucoup de modifications
                if edit_ratio > 0.3:
                    m["overall_score"] = max(0, m.get("overall_score", 50) - 20)
                break
        else:
            # Pas de score existant, en créer un
            metrics.append({
                "draft_id": draft_id,
                "overall_score": max(0, 80 - edit_ratio * 100),
                "was_edited": True,
                "edit_ratio": edit_ratio,
                "timestamp": datetime.now().isoformat(),
            })

        self._save_quality_metrics(metrics)

    def _calculate_quality_trend(self, metrics: List[dict], days: int = 7) -> List[dict]:
        """Calcule la tendance de qualité par jour."""
        by_day = defaultdict(list)

        for m in metrics:
            if m.get("timestamp"):
                day = m["timestamp"][:10]
                by_day[day].append(m.get("overall_score", 0))

        trend = []
        for day in sorted(by_day.keys())[-days:]:
            scores = by_day[day]
            trend.append({
                "date": day,
                "avg_score": round(sum(scores) / len(scores), 1),
                "count": len(scores),
            })

        return trend

    def _calculate_improvement_trend(self, metrics: List[dict]) -> float:
        """Calcule la tendance d'amélioration (-1 à 1)."""
        if len(metrics) < 2:
            return 0.0

        # Diviser en deux moitiés
        mid = len(metrics) // 2
        first_half = metrics[:mid]
        second_half = metrics[mid:]

        avg_first = sum(m.get("overall_score", 0) for m in first_half) / len(first_half)
        avg_second = sum(m.get("overall_score", 0) for m in second_half) / len(second_half)

        # Normaliser entre -1 et 1
        if avg_first == 0:
            return 0.0
        improvement = (avg_second - avg_first) / avg_first
        return max(-1, min(1, improvement))

    def _score_tone(self, text: str) -> float:
        """Évalue le ton du texte."""
        score = 70  # Base

        # Bonus pour politesse
        polite_words = ["merci", "cordialement", "s'il vous plaît", "sincèrement"]
        for word in polite_words:
            if word in text.lower():
                score += 5

        # Malus pour ton négatif
        negative_words = ["malheureusement", "impossible", "refus", "problème"]
        for word in negative_words:
            if word in text.lower():
                score -= 5

        return min(100, max(0, score))

    def _score_completeness(self, text: str, context: dict) -> float:
        """Évalue la complétude de la réponse."""
        score = 50  # Base

        # Bonus pour longueur appropriée
        word_count = len(text.split())
        if 50 <= word_count <= 200:
            score += 30
        elif 20 <= word_count < 50 or 200 < word_count <= 400:
            score += 15

        # Bonus pour salutation et signature
        if any(x in text.lower() for x in ["bonjour", "hello", "cher", "dear"]):
            score += 10
        if any(x in text.lower() for x in ["cordialement", "regards", "sincèrement"]):
            score += 10

        return min(100, max(0, score))

    def _score_professionalism(self, text: str) -> float:
        """Évalue le professionnalisme du texte."""
        score = 70  # Base

        # Malus pour langage informel
        informal = ["lol", "mdr", "ptdr", "haha", "!!!", "???"]
        for word in informal:
            if word in text.lower():
                score -= 10

        # Bonus pour structure
        if "\n\n" in text:  # Paragraphes
            score += 10

        # Malus pour fautes typiques
        if "  " in text:  # Double espaces
            score -= 5

        return min(100, max(0, score))

    def _score_relevance(self, text: str, context: dict) -> float:
        """Évalue la pertinence par rapport au contexte."""
        score = 60  # Base

        # Vérifier si des mots-clés du contexte sont repris
        context_text = str(context.get("subject", "")) + " " + str(context.get("body", ""))
        context_words = set(word.lower() for word in context_text.split() if len(word) > 4)
        text_words = set(word.lower() for word in text.split() if len(word) > 4)

        common = context_words.intersection(text_words)
        if context_words:
            relevance_ratio = len(common) / len(context_words)
            score += int(relevance_ratio * 40)

        return min(100, max(0, score))

    def _generate_recommendations(self) -> List[str]:
        """Génère des recommandations basées sur les analytics."""
        recommendations = []
        comparison = self.get_ai_vs_human_comparison()
        quality = self.get_quality_stats()

        # Recommandations basées sur les modifications
        if comparison.get("avg_edit_ratio", 0) > 30:
            recommendations.append(
                "Taux de modification élevé (>30%). "
                "Considérez améliorer les prompts ou la knowledge base."
            )

        # Recommandations basées sur la qualité
        if quality.get("avg_overall_score", 0) < 70:
            recommendations.append(
                "Score de qualité moyen bas (<70). "
                "Analysez les retours utilisateurs pour identifier les points faibles."
            )

        # Recommandations basées sur les notes
        if quality.get("avg_user_rating", 0) < 3.5:
            recommendations.append(
                "Note utilisateur moyenne basse (<3.5). "
                "Collectez plus de feedback pour comprendre les attentes."
            )

        if not recommendations:
            recommendations.append(
                "Performances satisfaisantes. "
                "Continuez à collecter du feedback pour maintenir la qualité."
            )

        return recommendations


# ============================================================================
# SINGLETON
# ============================================================================

_analytics_manager: Optional[AnalyticsManager] = None


def get_analytics_manager() -> AnalyticsManager:
    """Retourne l'instance singleton du gestionnaire d'analytics."""
    global _analytics_manager
    if _analytics_manager is None:
        _analytics_manager = AnalyticsManager()
    return _analytics_manager
