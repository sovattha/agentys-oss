# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Ports (Interfaces) pour le système de Fine-tuning.

Ces interfaces définissent les contrats que les adapters doivent implémenter
pour le stockage et la récupération des données de fine-tuning.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Dict, Any

from app.domain.entities.fine_tuning import (
    UserCorrection,
    UserFeedback,
    CorrectionPattern,
    ImprovementModel,
    FineTuningSession,
    FineTuningStats,
    CorrectionType,
    ImprovementStatus,
    FeedbackSentiment,
)


class UserCorrectionPort(ABC):
    """Interface pour le stockage des corrections utilisateur."""

    @abstractmethod
    def save(self, correction: UserCorrection) -> str:
        """
        Sauvegarde une correction utilisateur.

        Args:
            correction: La correction à sauvegarder.

        Returns:
            L'ID de la correction sauvegardée.
        """
        pass

    @abstractmethod
    def get_by_id(self, correction_id: str) -> Optional[UserCorrection]:
        """
        Récupère une correction par son ID.

        Args:
            correction_id: L'ID de la correction.

        Returns:
            La correction ou None si non trouvée.
        """
        pass

    @abstractmethod
    def get_by_draft_id(self, draft_id: str) -> List[UserCorrection]:
        """
        Récupère toutes les corrections pour un draft.

        Args:
            draft_id: L'ID du draft.

        Returns:
            Liste des corrections.
        """
        pass

    @abstractmethod
    def get_recent(
        self,
        limit: int = 100,
        since: Optional[datetime] = None,
    ) -> List[UserCorrection]:
        """
        Récupère les corrections récentes.

        Args:
            limit: Nombre maximum de corrections.
            since: Date à partir de laquelle récupérer.

        Returns:
            Liste des corrections.
        """
        pass

    @abstractmethod
    def get_by_correction_type(
        self,
        correction_type: CorrectionType,
        limit: int = 100,
    ) -> List[UserCorrection]:
        """
        Récupère les corrections par type.

        Args:
            correction_type: Type de correction.
            limit: Nombre maximum.

        Returns:
            Liste des corrections.
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """Retourne le nombre total de corrections."""
        pass

    @abstractmethod
    def delete(self, correction_id: str) -> bool:
        """
        Supprime une correction.

        Args:
            correction_id: L'ID de la correction.

        Returns:
            True si supprimée, False sinon.
        """
        pass


class UserFeedbackPort(ABC):
    """Interface pour le stockage des feedbacks utilisateur."""

    @abstractmethod
    def save(self, feedback: UserFeedback) -> str:
        """
        Sauvegarde un feedback utilisateur.

        Args:
            feedback: Le feedback à sauvegarder.

        Returns:
            L'ID du feedback sauvegardé.
        """
        pass

    @abstractmethod
    def get_by_id(self, feedback_id: str) -> Optional[UserFeedback]:
        """
        Récupère un feedback par son ID.

        Args:
            feedback_id: L'ID du feedback.

        Returns:
            Le feedback ou None si non trouvé.
        """
        pass

    @abstractmethod
    def get_by_draft_id(self, draft_id: str) -> Optional[UserFeedback]:
        """
        Récupère le feedback pour un draft.

        Args:
            draft_id: L'ID du draft.

        Returns:
            Le feedback ou None.
        """
        pass

    @abstractmethod
    def get_by_sentiment(
        self,
        sentiment: FeedbackSentiment,
        limit: int = 100,
    ) -> List[UserFeedback]:
        """
        Récupère les feedbacks par sentiment.

        Args:
            sentiment: Le sentiment recherché.
            limit: Nombre maximum.

        Returns:
            Liste des feedbacks.
        """
        pass

    @abstractmethod
    def get_by_rating_range(
        self,
        min_rating: int,
        max_rating: int,
        limit: int = 100,
    ) -> List[UserFeedback]:
        """
        Récupère les feedbacks par plage de notes.

        Args:
            min_rating: Note minimum.
            max_rating: Note maximum.
            limit: Nombre maximum.

        Returns:
            Liste des feedbacks.
        """
        pass

    @abstractmethod
    def get_recent(
        self,
        limit: int = 100,
        since: Optional[datetime] = None,
    ) -> List[UserFeedback]:
        """
        Récupère les feedbacks récents.

        Args:
            limit: Nombre maximum.
            since: Date à partir de laquelle récupérer.

        Returns:
            Liste des feedbacks.
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """Retourne le nombre total de feedbacks."""
        pass

    @abstractmethod
    def get_average_rating(self) -> float:
        """Retourne la note moyenne."""
        pass

    @abstractmethod
    def get_sentiment_distribution(self) -> Dict[str, int]:
        """Retourne la distribution des sentiments."""
        pass


class CorrectionPatternPort(ABC):
    """Interface pour le stockage des patterns de correction."""

    @abstractmethod
    def save(self, pattern: CorrectionPattern) -> str:
        """
        Sauvegarde un pattern de correction.

        Args:
            pattern: Le pattern à sauvegarder.

        Returns:
            L'ID du pattern sauvegardé.
        """
        pass

    @abstractmethod
    def update(self, pattern: CorrectionPattern) -> bool:
        """
        Met à jour un pattern existant.

        Args:
            pattern: Le pattern avec les nouvelles valeurs.

        Returns:
            True si mis à jour, False sinon.
        """
        pass

    @abstractmethod
    def get_by_id(self, pattern_id: str) -> Optional[CorrectionPattern]:
        """
        Récupère un pattern par son ID.

        Args:
            pattern_id: L'ID du pattern.

        Returns:
            Le pattern ou None si non trouvé.
        """
        pass

    @abstractmethod
    def get_by_type(
        self,
        pattern_type: CorrectionType,
        limit: int = 100,
    ) -> List[CorrectionPattern]:
        """
        Récupère les patterns par type.

        Args:
            pattern_type: Type de pattern.
            limit: Nombre maximum.

        Returns:
            Liste des patterns.
        """
        pass

    @abstractmethod
    def get_reliable_patterns(
        self,
        min_confidence: float = 0.6,
        limit: int = 100,
    ) -> List[CorrectionPattern]:
        """
        Récupère les patterns fiables (haute confiance).

        Args:
            min_confidence: Confiance minimale.
            limit: Nombre maximum.

        Returns:
            Liste des patterns fiables.
        """
        pass

    @abstractmethod
    def find_similar(
        self,
        original_pattern: str,
        threshold: float = 0.8,
    ) -> Optional[CorrectionPattern]:
        """
        Trouve un pattern similaire existant.

        Args:
            original_pattern: Le motif à comparer.
            threshold: Seuil de similarité.

        Returns:
            Le pattern similaire ou None.
        """
        pass

    @abstractmethod
    def get_all(self, limit: int = 1000) -> List[CorrectionPattern]:
        """
        Récupère tous les patterns.

        Args:
            limit: Nombre maximum.

        Returns:
            Liste des patterns.
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """Retourne le nombre total de patterns."""
        pass

    @abstractmethod
    def delete(self, pattern_id: str) -> bool:
        """
        Supprime un pattern.

        Args:
            pattern_id: L'ID du pattern.

        Returns:
            True si supprimé, False sinon.
        """
        pass


class ImprovementModelPort(ABC):
    """Interface pour le stockage des modèles d'amélioration."""

    @abstractmethod
    def save(self, model: ImprovementModel) -> str:
        """
        Sauvegarde un modèle d'amélioration.

        Args:
            model: Le modèle à sauvegarder.

        Returns:
            L'ID du modèle sauvegardé.
        """
        pass

    @abstractmethod
    def update(self, model: ImprovementModel) -> bool:
        """
        Met à jour un modèle existant.

        Args:
            model: Le modèle avec les nouvelles valeurs.

        Returns:
            True si mis à jour, False sinon.
        """
        pass

    @abstractmethod
    def get_by_id(self, model_id: str) -> Optional[ImprovementModel]:
        """
        Récupère un modèle par son ID.

        Args:
            model_id: L'ID du modèle.

        Returns:
            Le modèle ou None si non trouvé.
        """
        pass

    @abstractmethod
    def get_active_models(self) -> List[ImprovementModel]:
        """
        Récupère tous les modèles actifs.

        Returns:
            Liste des modèles actifs.
        """
        pass

    @abstractmethod
    def get_by_status(
        self,
        status: ImprovementStatus,
        limit: int = 100,
    ) -> List[ImprovementModel]:
        """
        Récupère les modèles par statut.

        Args:
            status: Le statut recherché.
            limit: Nombre maximum.

        Returns:
            Liste des modèles.
        """
        pass

    @abstractmethod
    def get_latest(self) -> Optional[ImprovementModel]:
        """
        Récupère le modèle le plus récent.

        Returns:
            Le modèle le plus récent ou None.
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """Retourne le nombre total de modèles."""
        pass

    @abstractmethod
    def delete(self, model_id: str) -> bool:
        """
        Supprime un modèle.

        Args:
            model_id: L'ID du modèle.

        Returns:
            True si supprimé, False sinon.
        """
        pass


class FineTuningSessionPort(ABC):
    """Interface pour le stockage des sessions de fine-tuning."""

    @abstractmethod
    def save(self, session: FineTuningSession) -> str:
        """
        Sauvegarde une session de fine-tuning.

        Args:
            session: La session à sauvegarder.

        Returns:
            L'ID de la session sauvegardée.
        """
        pass

    @abstractmethod
    def update(self, session: FineTuningSession) -> bool:
        """
        Met à jour une session existante.

        Args:
            session: La session avec les nouvelles valeurs.

        Returns:
            True si mise à jour, False sinon.
        """
        pass

    @abstractmethod
    def get_by_id(self, session_id: str) -> Optional[FineTuningSession]:
        """
        Récupère une session par son ID.

        Args:
            session_id: L'ID de la session.

        Returns:
            La session ou None si non trouvée.
        """
        pass

    @abstractmethod
    def get_recent(self, limit: int = 10) -> List[FineTuningSession]:
        """
        Récupère les sessions récentes.

        Args:
            limit: Nombre maximum.

        Returns:
            Liste des sessions.
        """
        pass

    @abstractmethod
    def get_running(self) -> Optional[FineTuningSession]:
        """
        Récupère la session en cours d'exécution.

        Returns:
            La session en cours ou None.
        """
        pass


class FineTuningAnalyzerPort(ABC):
    """Interface pour l'analyse des corrections et l'extraction de patterns."""

    @abstractmethod
    def analyze_correction(
        self,
        original: str,
        corrected: str,
    ) -> List[CorrectionType]:
        """
        Analyse une correction et détecte les types de changements.

        Args:
            original: Texte original.
            corrected: Texte corrigé.

        Returns:
            Liste des types de corrections détectés.
        """
        pass

    @abstractmethod
    def extract_patterns(
        self,
        corrections: List[UserCorrection],
    ) -> List[CorrectionPattern]:
        """
        Extrait des patterns à partir d'une liste de corrections.

        Args:
            corrections: Liste des corrections à analyser.

        Returns:
            Liste des patterns extraits.
        """
        pass

    @abstractmethod
    def generate_prompt_adjustments(
        self,
        patterns: List[CorrectionPattern],
    ) -> List[str]:
        """
        Génère des ajustements de prompt à partir des patterns.

        Args:
            patterns: Les patterns à transformer.

        Returns:
            Liste des ajustements de prompt.
        """
        pass

    @abstractmethod
    def apply_improvements(
        self,
        text: str,
        model: ImprovementModel,
        patterns: List[CorrectionPattern],
    ) -> str:
        """
        Applique les améliorations d'un modèle à un texte.

        Args:
            text: Texte à améliorer.
            model: Le modèle d'amélioration.
            patterns: Les patterns disponibles.

        Returns:
            Le texte amélioré.
        """
        pass


class FineTuningStatsPort(ABC):
    """Interface pour les statistiques de fine-tuning."""

    @abstractmethod
    def get_stats(self) -> FineTuningStats:
        """
        Calcule et retourne les statistiques complètes.

        Returns:
            Les statistiques de fine-tuning.
        """
        pass

    @abstractmethod
    def get_correction_type_distribution(self) -> Dict[str, int]:
        """
        Retourne la distribution des types de correction.

        Returns:
            Dictionnaire type -> count.
        """
        pass

    @abstractmethod
    def get_improvement_rate(self) -> float:
        """
        Calcule le taux d'amélioration.

        Returns:
            Pourcentage de drafts améliorés.
        """
        pass

    @abstractmethod
    def get_pattern_effectiveness(
        self,
        pattern_id: str,
    ) -> Dict[str, Any]:
        """
        Calcule l'efficacité d'un pattern.

        Args:
            pattern_id: L'ID du pattern.

        Returns:
            Métriques d'efficacité.
        """
        pass
