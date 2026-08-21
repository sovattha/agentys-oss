# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités du domaine pour le Fine-tuning avec feedback utilisateur.

Ce module définit les entités métier pour le système de fine-tuning
basé sur les corrections et feedbacks des utilisateurs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
import uuid


class CorrectionType(Enum):
    """Type de correction apportée par l'utilisateur."""
    TONE = "tone"  # Changement de ton (formel/informel)
    GRAMMAR = "grammar"  # Corrections grammaticales
    STYLE = "style"  # Améliorations stylistiques
    CONTENT = "content"  # Ajout/suppression de contenu
    FORMAT = "format"  # Mise en forme (bullet points, paragraphes)
    LENGTH = "length"  # Ajustement de longueur
    VOCABULARY = "vocabulary"  # Choix de mots
    STRUCTURE = "structure"  # Organisation du texte


class ImprovementStatus(Enum):
    """Statut d'un modèle d'amélioration."""
    PENDING = "pending"  # En attente de validation
    ACTIVE = "active"  # Actif et appliqué
    DISABLED = "disabled"  # Désactivé par l'utilisateur
    DEPRECATED = "deprecated"  # Remplacé par une version plus récente


class FeedbackSentiment(Enum):
    """Sentiment du feedback utilisateur."""
    POSITIVE = "positive"  # Note >= 4
    NEUTRAL = "neutral"  # Note == 3
    NEGATIVE = "negative"  # Note <= 2


@dataclass
class UserCorrection:
    """
    Représente une correction apportée par l'utilisateur sur un draft.

    Attributes:
        id: Identifiant unique de la correction
        draft_id: ID du draft corrigé
        original_text: Texte original généré par l'IA
        corrected_text: Texte corrigé par l'utilisateur
        correction_types: Types de corrections détectées
        context: Contexte de l'email (expéditeur, catégorie, etc.)
        created_at: Date de création
        user_comment: Commentaire optionnel de l'utilisateur
    """
    id: str
    draft_id: str
    original_text: str
    corrected_text: str
    correction_types: List[CorrectionType] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    user_comment: Optional[str] = None
    account_id: Optional[int] = None  # tenant owner (cross-tenant isolation, 2026-05-30)

    @classmethod
    def create(
        cls,
        draft_id: str,
        original_text: str,
        corrected_text: str,
        context: Optional[Dict[str, Any]] = None,
        user_comment: Optional[str] = None,
        account_id: Optional[int] = None,
    ) -> "UserCorrection":
        """Crée une nouvelle correction utilisateur."""
        return cls(
            id=str(uuid.uuid4()),
            draft_id=draft_id,
            original_text=original_text,
            corrected_text=corrected_text,
            context=context or {},
            user_comment=user_comment,
            account_id=account_id,
        )

    def has_significant_changes(self, min_diff_ratio: float = 0.05) -> bool:
        """Vérifie si la correction contient des changements significatifs."""
        if len(self.original_text) == 0:
            return len(self.corrected_text) > 0
        diff_chars = abs(len(self.original_text) - len(self.corrected_text))
        diff_chars += sum(
            1 for a, b in zip(self.original_text, self.corrected_text) if a != b
        )
        ratio = diff_chars / max(len(self.original_text), 1)
        return ratio >= min_diff_ratio


@dataclass
class UserFeedback:
    """
    Représente un feedback utilisateur sur un draft.

    Attributes:
        id: Identifiant unique du feedback
        draft_id: ID du draft évalué
        rating: Note de 1 à 5
        sentiment: Sentiment déduit de la note
        comment: Commentaire textuel
        tags: Tags associés (optionnel)
        created_at: Date de création
    """
    id: str
    draft_id: str
    rating: int
    sentiment: FeedbackSentiment
    comment: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    account_id: Optional[int] = None  # tenant owner (cross-tenant isolation, 2026-05-30)

    @classmethod
    def create(
        cls,
        draft_id: str,
        rating: int,
        comment: Optional[str] = None,
        tags: Optional[List[str]] = None,
        account_id: Optional[int] = None,
    ) -> "UserFeedback":
        """Crée un nouveau feedback utilisateur."""
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")

        sentiment = (
            FeedbackSentiment.POSITIVE if rating >= 4
            else FeedbackSentiment.NEGATIVE if rating <= 2
            else FeedbackSentiment.NEUTRAL
        )

        return cls(
            id=str(uuid.uuid4()),
            draft_id=draft_id,
            rating=rating,
            sentiment=sentiment,
            comment=comment,
            tags=tags or [],
            account_id=account_id,
        )


@dataclass
class CorrectionPattern:
    """
    Pattern de correction détecté dans les feedbacks utilisateur.

    Attributes:
        id: Identifiant unique du pattern
        pattern_type: Type de correction
        original_pattern: Motif original (ce qui était écrit)
        replacement: Remplacement suggéré
        occurrences: Nombre de fois observé
        confidence: Score de confiance (0.0 - 1.0)
        contexts: Contextes où ce pattern s'applique
        examples: Exemples de ce pattern
        created_at: Date de création
        last_used: Dernière utilisation
    """
    id: str
    pattern_type: CorrectionType
    original_pattern: str
    replacement: str
    occurrences: int = 1
    confidence: float = 0.5
    contexts: List[Dict[str, Any]] = field(default_factory=list)
    examples: List[Dict[str, str]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_used: Optional[datetime] = None
    account_id: Optional[int] = None  # tenant owner (cross-tenant isolation, 2026-05-30)

    @classmethod
    def create(
        cls,
        pattern_type: CorrectionType,
        original_pattern: str,
        replacement: str,
        context: Optional[Dict[str, Any]] = None,
        account_id: Optional[int] = None,
    ) -> "CorrectionPattern":
        """Crée un nouveau pattern de correction."""
        return cls(
            id=str(uuid.uuid4()),
            pattern_type=pattern_type,
            original_pattern=original_pattern,
            replacement=replacement,
            contexts=[context] if context else [],
            account_id=account_id,
        )

    def increment_occurrence(self) -> None:
        """Incrémente le compteur et ajuste la confiance."""
        self.occurrences += 1
        # Confiance augmente avec le nombre d'occurrences (max 1.0 à 10 occurrences)
        self.confidence = min(1.0, self.occurrences / 10)
        self.last_used = datetime.now()

    def is_reliable(self, min_confidence: float = 0.6) -> bool:
        """Vérifie si le pattern est suffisamment fiable pour être appliqué."""
        return self.confidence >= min_confidence


@dataclass
class ImprovementModel:
    """
    Modèle d'amélioration pour le fine-tuning.

    Représente un ensemble de règles apprises qui peuvent être
    appliquées aux futurs drafts.

    Attributes:
        id: Identifiant unique du modèle
        version: Version du modèle
        name: Nom descriptif
        description: Description du modèle
        patterns: Patterns de correction inclus
        prompt_adjustments: Ajustements de prompt associés
        status: Statut du modèle
        impact_score: Score d'impact mesuré (0.0 - 1.0)
        drafts_improved: Nombre de drafts améliorés
        created_at: Date de création
        updated_at: Date de mise à jour
        account_id: Tenant propriétaire (C-6, audit issue #526). `None` =
            legacy model écrit avant le fix — invisible pour toute lookup
            scopée (pas de takeover possible) ; un opérateur peut migrer
            manuellement via le JSON store si besoin.
    """
    id: str
    version: str
    name: str
    description: str
    patterns: List[str] = field(default_factory=list)  # IDs des patterns
    prompt_adjustments: List[str] = field(default_factory=list)  # Textes d'ajustement
    status: ImprovementStatus = ImprovementStatus.PENDING
    impact_score: float = 0.0
    drafts_improved: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    account_id: Optional[int] = None

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        version: str = "1.0.0",
        account_id: Optional[int] = None,
    ) -> "ImprovementModel":
        """Crée un nouveau modèle d'amélioration.

        `account_id` doit être fourni en prod (multi-tenant) ; les use cases
        qui passent None produisent un modèle legacy invisible aux lookups
        scopées — utile uniquement pour les tests / chemins admin globaux.
        """
        return cls(
            id=str(uuid.uuid4()),
            version=version,
            name=name,
            description=description,
            account_id=account_id,
        )

    def activate(self) -> None:
        """Active le modèle."""
        self.status = ImprovementStatus.ACTIVE
        self.updated_at = datetime.now()

    def disable(self) -> None:
        """Désactive le modèle."""
        self.status = ImprovementStatus.DISABLED
        self.updated_at = datetime.now()

    def deprecate(self) -> None:
        """Marque le modèle comme obsolète."""
        self.status = ImprovementStatus.DEPRECATED
        self.updated_at = datetime.now()

    def add_pattern(self, pattern_id: str) -> None:
        """Ajoute un pattern au modèle."""
        if pattern_id not in self.patterns:
            self.patterns.append(pattern_id)
            self.updated_at = datetime.now()

    def add_prompt_adjustment(self, adjustment: str) -> None:
        """Ajoute un ajustement de prompt."""
        if adjustment not in self.prompt_adjustments:
            self.prompt_adjustments.append(adjustment)
            self.updated_at = datetime.now()

    def record_improvement(self) -> None:
        """Enregistre une amélioration réussie."""
        self.drafts_improved += 1
        self.updated_at = datetime.now()

    def update_impact_score(self, new_score: float) -> None:
        """Met à jour le score d'impact."""
        # Moyenne mobile avec le nouveau score
        if self.drafts_improved > 0:
            self.impact_score = (
                self.impact_score * (self.drafts_improved - 1) + new_score
            ) / self.drafts_improved
        else:
            self.impact_score = new_score
        self.updated_at = datetime.now()


@dataclass
class FineTuningSession:
    """
    Session de fine-tuning regroupant corrections et feedbacks.

    Attributes:
        id: Identifiant unique de la session
        started_at: Début de la session
        ended_at: Fin de la session (si terminée)
        corrections_count: Nombre de corrections analysées
        feedbacks_count: Nombre de feedbacks analysés
        patterns_extracted: Nombre de patterns extraits
        model_id: ID du modèle généré (si applicable)
        status: Statut de la session
    """
    id: str
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    corrections_count: int = 0
    feedbacks_count: int = 0
    patterns_extracted: int = 0
    model_id: Optional[str] = None
    status: str = "running"
    account_id: Optional[int] = None  # tenant owner (cross-tenant isolation, 2026-05-30)

    @classmethod
    def create(cls, account_id: Optional[int] = None) -> "FineTuningSession":
        """Crée une nouvelle session de fine-tuning."""
        return cls(id=str(uuid.uuid4()), account_id=account_id)

    def complete(self, model_id: Optional[str] = None) -> None:
        """Marque la session comme terminée."""
        self.ended_at = datetime.now()
        self.model_id = model_id
        self.status = "completed"

    def fail(self, error: str) -> None:
        """Marque la session comme échouée."""
        self.ended_at = datetime.now()
        self.status = f"failed: {error}"


@dataclass
class FineTuningStats:
    """
    Statistiques du système de fine-tuning.

    Attributes:
        total_corrections: Total de corrections enregistrées
        total_feedbacks: Total de feedbacks reçus
        total_patterns: Total de patterns appris
        active_models: Nombre de modèles actifs
        average_impact: Impact moyen des améliorations
        top_correction_types: Types de correction les plus fréquents
        feedback_sentiment_distribution: Distribution des sentiments
    """
    total_corrections: int = 0
    total_feedbacks: int = 0
    total_patterns: int = 0
    active_models: int = 0
    average_impact: float = 0.0
    top_correction_types: Dict[str, int] = field(default_factory=dict)
    feedback_sentiment_distribution: Dict[str, int] = field(default_factory=dict)
    patterns_by_confidence: Dict[str, int] = field(default_factory=dict)
    improvement_rate: float = 0.0  # % de drafts améliorés vs total
