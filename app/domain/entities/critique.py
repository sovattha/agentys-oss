"""Entités pour l'évaluation critique des brouillons.

Story 5-2: CriticAgent Implementation
Task 1: Créer entities CritiqueRequest, CritiqueResult, CritiqueDecision

Ces dataclasses représentent les entrées et sorties
du CriticAgent enrichi avec scoring détaillé.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class ToneClassification(Enum):
    """Classification du ton d'un brouillon email (Story 5-5).

    FORMAL: Style professionnel et structuré, adapté aux communications officielles.
    FRIENDLY: Style détendu et cordial, adapté aux échanges entre collègues.
    NEUTRAL: Style informatif et objectif, sans tonalité émotionnelle.
    URGENT: Style pressant nécessitant une action rapide.
    """

    FORMAL = "formal"
    FRIENDLY = "friendly"
    NEUTRAL = "neutral"
    URGENT = "urgent"


# Descriptions des tons en français pour l'UI
TONE_DESCRIPTIONS = {
    ToneClassification.FORMAL: {
        "label": "Formel",
        "description": "Style professionnel et structuré, adapté aux communications officielles.",
        "color": "blue",
    },
    ToneClassification.FRIENDLY: {
        "label": "Amical",
        "description": "Style détendu et cordial, adapté aux échanges entre collègues.",
        "color": "green",
    },
    ToneClassification.NEUTRAL: {
        "label": "Neutre",
        "description": "Style informatif et objectif, sans tonalité émotionnelle.",
        "color": "gray",
    },
    ToneClassification.URGENT: {
        "label": "Urgent",
        "description": "Style pressant nécessitant une action rapide.",
        "color": "red",
    },
}


@dataclass
class ToneResult:
    """Résultat de classification de ton d'un brouillon (Story 5-5).

    Attributes:
        classification: Le ton classifié (FORMAL, FRIENDLY, NEUTRAL, URGENT).
        confidence: Niveau de confiance de la classification (0.0-1.0).
        explanation: Explication de pourquoi ce ton a été détecté.
    """

    classification: ToneClassification
    confidence: float
    explanation: str

    def __post_init__(self):
        """Validation après initialisation."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if isinstance(self.classification, str):
            try:
                self.classification = ToneClassification(self.classification.lower())
            except ValueError:
                self.classification = ToneClassification.NEUTRAL

    @staticmethod
    def from_tone_score(
        tone_score: int,
        analysis_text: str = "",  # noqa: ARG004 — réservé pour future extraction d'indices
        urgency_keywords: bool = False,
    ) -> "ToneResult":
        """Classifie le ton basé sur le score et l'analyse.

        Mapping des scores (Story 5-5 AC2):
        - URGENT: Si mots-clés d'urgence détectés (override)
        - FORMAL: 80-100 (style professionnel structuré)
        - FRIENDLY: 60-79 (style détendu cordial)
        - NEUTRAL: 40-59 (style informatif sans émotion)
        - Pour scores < 40: tendance NEUTRAL car ton problématique

        Args:
            tone_score: Score de ton (0-100) du CritiqueScores.
            analysis_text: Texte d'analyse pour extraction d'indices.
            urgency_keywords: True si des mots-clés d'urgence ont été détectés.

        Returns:
            ToneResult avec classification, confidence et explication.
        """
        # URGENT override si mots-clés détectés
        if urgency_keywords:
            return ToneResult(
                classification=ToneClassification.URGENT,
                confidence=0.85,
                explanation="Détection de mots-clés d'urgence dans le brouillon.",
            )

        # Classification basée sur le score
        if tone_score >= 80:
            classification = ToneClassification.FORMAL
            confidence = min(0.95, 0.7 + (tone_score - 80) * 0.0125)
            explanation = "Le brouillon utilise un style professionnel et structuré."
        elif tone_score >= 60:
            classification = ToneClassification.FRIENDLY
            confidence = min(0.90, 0.6 + (tone_score - 60) * 0.015)
            explanation = "Le brouillon adopte un ton détendu et cordial."
        elif tone_score >= 40:
            classification = ToneClassification.NEUTRAL
            confidence = min(0.85, 0.5 + (tone_score - 40) * 0.0175)
            explanation = "Le brouillon est informatif et objectif."
        else:
            # Score faible = ton problématique, classifier comme NEUTRAL par défaut
            classification = ToneClassification.NEUTRAL
            confidence = 0.4
            explanation = "Le ton du brouillon est difficile à classifier (score faible)."

        return ToneResult(
            classification=classification,
            confidence=confidence,
            explanation=explanation,
        )

    def get_label(self) -> str:
        """Retourne le label français du ton."""
        return TONE_DESCRIPTIONS[self.classification]["label"]

    def get_description(self) -> str:
        """Retourne la description française du ton."""
        return TONE_DESCRIPTIONS[self.classification]["description"]

    def get_color(self) -> str:
        """Retourne la couleur associée au ton (pour l'UI)."""
        return TONE_DESCRIPTIONS[self.classification]["color"]

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "classification": self.classification.value,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "label": self.get_label(),
            "description": self.get_description(),
            "color": self.get_color(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToneResult":
        """Crée une instance depuis un dictionnaire."""
        classification_str = data.get("classification", "neutral")
        try:
            classification = ToneClassification(classification_str.lower())
        except ValueError:
            classification = ToneClassification.NEUTRAL

        return cls(
            classification=classification,
            confidence=float(data.get("confidence", 0.5)),
            explanation=str(data.get("explanation", "")),
        )

    @classmethod
    def create_default(cls) -> "ToneResult":
        """Crée un résultat par défaut (NEUTRAL avec faible confiance)."""
        return cls(
            classification=ToneClassification.NEUTRAL,
            confidence=0.3,
            explanation="Classification par défaut.",
        )


class CritiqueDecision(Enum):
    """Décision du CriticAgent sur la qualité du brouillon.

    VALID: Le brouillon est acceptable et peut être présenté à l'utilisateur.
    REJECT: Le brouillon nécessite des améliorations.
    """

    VALID = "valid"
    REJECT = "reject"


class CritiqueStatus(Enum):
    """Statut de l'évaluation critique."""

    PENDING = "pending"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


@dataclass
class CritiqueScores:
    """Scores détaillés d'évaluation du brouillon.

    Chaque score est noté de 0 à 100:
    - 0-40: Très faible, problèmes majeurs
    - 41-60: Faible, améliorations nécessaires
    - 61-70: Acceptable, quelques ajustements possibles
    - 71-85: Bon, qualité satisfaisante
    - 86-100: Excellent, prêt pour l'utilisateur

    Attributes:
        coherence: Le brouillon répond-il à l'email original? (0-100)
        tone: Le ton est-il approprié au contexte? (0-100)
        completeness: Toutes les questions sont-elles adressées? (0-100)
        errors: Absence de fautes, hallucinations, incohérences (0-100)
        conciseness: La longueur est-elle proportionnée au contexte? (0-100)
        over_commitment: Le brouillon évite-t-il les promesses non fondées? (0-100)
        emotional_intelligence: Le brouillon reconnaît-il l'émotion de l'expéditeur? (0-100)
    """

    coherence: int
    tone: int
    completeness: int
    errors: int
    conciseness: int
    over_commitment: int
    emotional_intelligence: int

    def __post_init__(self):
        """Validation des scores."""
        for name in ["coherence", "tone", "completeness", "errors", "conciseness", "over_commitment", "emotional_intelligence"]:
            value = getattr(self, name)
            if not isinstance(value, int) or not 0 <= value <= 100:
                raise ValueError(f"{name} must be an integer between 0 and 100")

    def calculate_overall(self) -> int:
        """Calcule le score global (moyenne simple des 7 critères).

        Returns:
            Score global de 0 à 100.
        """
        return (self.coherence + self.tone + self.completeness + self.errors + self.conciseness + self.over_commitment + self.emotional_intelligence) // 7

    def calculate_weighted(
        self,
        coherence_weight: float = 0.20,
        tone_weight: float = 0.15,
        completeness_weight: float = 0.20,
        errors_weight: float = 0.15,
        conciseness_weight: float = 0.10,
        over_commitment_weight: float = 0.10,
        emotional_intelligence_weight: float = 0.10,
    ) -> int:
        """Calcule le score global avec pondération personnalisée.

        Args:
            coherence_weight: Poids de la cohérence (default: 0.20)
            tone_weight: Poids du ton (default: 0.15)
            completeness_weight: Poids de la complétude (default: 0.20)
            errors_weight: Poids des erreurs (default: 0.15)
            conciseness_weight: Poids de la concision (default: 0.10)
            over_commitment_weight: Poids du sur-engagement (default: 0.10)
            emotional_intelligence_weight: Poids de l'intelligence émotionnelle (default: 0.10)

        Returns:
            Score global pondéré de 0 à 100.
        """
        total_weight = (coherence_weight + tone_weight + completeness_weight + errors_weight
                        + conciseness_weight + over_commitment_weight + emotional_intelligence_weight)
        if abs(total_weight - 1.0) > 0.001:
            # Normaliser les poids
            coherence_weight /= total_weight
            tone_weight /= total_weight
            completeness_weight /= total_weight
            errors_weight /= total_weight
            conciseness_weight /= total_weight
            over_commitment_weight /= total_weight
            emotional_intelligence_weight /= total_weight

        weighted_sum = (
            self.coherence * coherence_weight
            + self.tone * tone_weight
            + self.completeness * completeness_weight
            + self.errors * errors_weight
            + self.conciseness * conciseness_weight
            + self.over_commitment * over_commitment_weight
            + self.emotional_intelligence * emotional_intelligence_weight
        )
        return int(round(weighted_sum))

    def get_weak_criteria(self, threshold: int = 70) -> List[str]:
        """Identifie les critères sous le seuil.

        Args:
            threshold: Seuil minimum acceptable (default: 70)

        Returns:
            Liste des noms de critères faibles.
        """
        weak = []
        if self.coherence < threshold:
            weak.append("coherence")
        if self.tone < threshold:
            weak.append("tone")
        if self.completeness < threshold:
            weak.append("completeness")
        if self.errors < threshold:
            weak.append("errors")
        if self.conciseness < threshold:
            weak.append("conciseness")
        if self.over_commitment < threshold:
            weak.append("over_commitment")
        if self.emotional_intelligence < threshold:
            weak.append("emotional_intelligence")
        return weak

    def to_dict(self) -> Dict[str, int]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "coherence": self.coherence,
            "tone": self.tone,
            "completeness": self.completeness,
            "errors": self.errors,
            "conciseness": self.conciseness,
            "over_commitment": self.over_commitment,
            "emotional_intelligence": self.emotional_intelligence,
            "overall": self.calculate_overall(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CritiqueScores":
        """Crée une instance depuis un dictionnaire."""
        return cls(
            coherence=int(data.get("coherence", 50)),
            tone=int(data.get("tone", 50)),
            completeness=int(data.get("completeness", 50)),
            errors=int(data.get("errors", 50)),
            conciseness=int(data.get("conciseness", 50)),
            over_commitment=int(data.get("over_commitment", 50)),
            emotional_intelligence=int(data.get("emotional_intelligence", 50)),
        )

    @classmethod
    def create_default(cls) -> "CritiqueScores":
        """Crée des scores par défaut (50/100 pour tous)."""
        return cls(coherence=50, tone=50, completeness=50, errors=50, conciseness=50, over_commitment=50, emotional_intelligence=50)


@dataclass
class CritiqueRequest:
    """Entrée pour l'évaluation critique d'un brouillon.

    Contient toutes les données nécessaires pour que le CriticAgent
    évalue un brouillon de réponse email.

    Attributes:
        draft_content: Contenu du brouillon à évaluer.
        original_email: Email original auquel le brouillon répond.
        email_id: ID de l'email pour tracking.
        context: Contexte additionnel (instructions utilisateur, etc.).
        style_context: Contexte de style de l'utilisateur (optionnel).
        expected_tone: Ton attendu pour le brouillon (optionnel).
        session_id: Identifiant de session pour tracking.
    """

    draft_content: str
    original_email: str
    email_id: Optional[str] = None
    context: Optional[str] = None
    style_context: Optional[str] = None
    expected_tone: Optional[str] = None
    session_id: Optional[str] = None
    # Audit R-002 (2026-04-27): per-account WS routing for BG threads.
    account_id: Optional[int] = None
    # Audit 2026-05-06: tier and intent let the Critic adjust its quality
    # threshold per email risk profile (decline/RH = 78, simple ack = 60,
    # default = 70). Both optional — when None the legacy uniform threshold
    # applies. cf. CriticAgent._effective_threshold.
    tier: Optional[str] = None
    intent: Optional[str] = None

    def __post_init__(self):
        """Validation après initialisation."""
        if not self.draft_content or not self.draft_content.strip():
            raise ValueError("draft_content cannot be empty")
        if not self.original_email or not self.original_email.strip():
            raise ValueError("original_email cannot be empty")

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "draft_content": self.draft_content,
            "original_email": self.original_email,
            "email_id": self.email_id,
            "context": self.context,
            "style_context": self.style_context,
            "expected_tone": self.expected_tone,
            "session_id": self.session_id,
        }

    def has_context(self) -> bool:
        """Vérifie si un contexte additionnel est disponible."""
        return self.context is not None and bool(self.context.strip())


@dataclass
class CritiqueResult:
    """Résultat complet de l'évaluation critique.

    Contient les scores détaillés, la décision, et les suggestions
    d'amélioration si le brouillon n'est pas acceptable.

    Attributes:
        scores: Scores détaillés de l'évaluation.
        decision: Décision VALID ou REJECT.
        suggestions: Liste de suggestions d'amélioration.
        explanation: Explication détaillée de la décision.
        evaluation_time_ms: Durée de l'évaluation en millisecondes.
        tokens_used: Nombre de tokens Claude utilisés.
        status: Statut de l'évaluation.
        retry_count: Nombre de tentatives effectuées.
        error_message: Message d'erreur si échec.
        evaluated_at: Timestamp de l'évaluation.
        draft_content: Contenu du brouillon évalué (pour la révision, Story 5-3).
    """

    scores: CritiqueScores
    decision: CritiqueDecision
    suggestions: List[str] = field(default_factory=list)
    explanation: str = ""
    evaluation_time_ms: int = 0
    tokens_used: int = 0
    status: CritiqueStatus = CritiqueStatus.COMPLETED
    retry_count: int = 0
    error_message: Optional[str] = None
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    draft_content: Optional[str] = None  # Story 5-3: Pour la révision avec critique
    tone_classification: Optional[ToneResult] = None  # Story 5-5: Classification du ton

    def __post_init__(self):
        """Validation après initialisation."""
        if self.evaluation_time_ms < 0:
            raise ValueError("evaluation_time_ms must be non-negative")
        if self.tokens_used < 0:
            raise ValueError("tokens_used must be non-negative")
        if self.retry_count < 0:
            raise ValueError("retry_count must be non-negative")

        # Convert strings to enums if needed
        if isinstance(self.decision, str):
            try:
                self.decision = CritiqueDecision(self.decision.lower())
            except ValueError:
                # Default to REJECT if unknown
                self.decision = CritiqueDecision.REJECT
        if isinstance(self.status, str):
            try:
                self.status = CritiqueStatus(self.status.lower())
            except ValueError:
                self.status = CritiqueStatus.COMPLETED

    def is_acceptable(self, threshold: int = 70) -> bool:
        """Vérifie si le brouillon est acceptable selon le seuil.

        Args:
            threshold: Score minimum requis (default: 70)

        Returns:
            True si le score global >= threshold et decision == VALID.
        """
        return (
            self.decision == CritiqueDecision.VALID
            and self.scores.calculate_overall() >= threshold
        )

    def is_successful(self) -> bool:
        """Vérifie si l'évaluation a réussi."""
        return self.status == CritiqueStatus.COMPLETED

    def was_rate_limited(self) -> bool:
        """Vérifie si l'évaluation a été limitée par rate limit."""
        return self.status == CritiqueStatus.RATE_LIMITED

    def get_overall_score(self) -> int:
        """Raccourci pour obtenir le score global."""
        return self.scores.calculate_overall()

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        result = {
            "scores": self.scores.to_dict(),
            "decision": self.decision.value,
            "suggestions": self.suggestions,
            "explanation": self.explanation,
            "evaluation_time_ms": self.evaluation_time_ms,
            "tokens_used": self.tokens_used,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "error_message": self.error_message,
            "evaluated_at": self.evaluated_at.isoformat(),
            "overall_score": self.get_overall_score(),
            "is_acceptable": self.is_acceptable(),
            "draft_content": self.draft_content,
        }
        # Story 5-5: Ajouter la classification du ton si disponible
        if self.tone_classification is not None:
            result["tone"] = self.tone_classification.to_dict()
        return result

    @classmethod
    def create_failed(
        cls,
        error_message: str,
        status: CritiqueStatus = CritiqueStatus.FAILED,
        retry_count: int = 0,
        evaluation_time_ms: int = 0,
    ) -> "CritiqueResult":
        """Crée un résultat d'échec avec scores par défaut.

        Args:
            error_message: Description de l'erreur.
            status: Statut d'échec (FAILED ou RATE_LIMITED).
            retry_count: Nombre de tentatives effectuées.
            evaluation_time_ms: Durée totale des tentatives.

        Returns:
            CritiqueResult avec décision REJECT et statut d'erreur.
        """
        return cls(
            scores=CritiqueScores.create_default(),
            decision=CritiqueDecision.REJECT,
            suggestions=["Unable to evaluate draft due to error"],
            explanation=f"Evaluation failed: {error_message}",
            status=status,
            error_message=error_message,
            retry_count=retry_count,
            evaluation_time_ms=evaluation_time_ms,
        )

    @classmethod
    def create_rate_limited(
        cls,
        retry_count: int,
        evaluation_time_ms: int = 0,
    ) -> "CritiqueResult":
        """Crée un résultat pour rate limit atteint.

        Args:
            retry_count: Nombre de tentatives effectuées.
            evaluation_time_ms: Durée totale des tentatives.

        Returns:
            CritiqueResult avec statut RATE_LIMITED.
        """
        return cls.create_failed(
            error_message="Rate limit exceeded after maximum retries",
            status=CritiqueStatus.RATE_LIMITED,
            retry_count=retry_count,
            evaluation_time_ms=evaluation_time_ms,
        )

    @classmethod
    def create_valid(
        cls,
        scores: CritiqueScores,
        explanation: str = "Draft meets quality standards",
        evaluation_time_ms: int = 0,
        tokens_used: int = 0,
    ) -> "CritiqueResult":
        """Crée un résultat positif (VALID).

        Args:
            scores: Scores de l'évaluation.
            explanation: Explication de la validation.
            evaluation_time_ms: Durée de l'évaluation.
            tokens_used: Tokens utilisés.

        Returns:
            CritiqueResult avec décision VALID.
        """
        return cls(
            scores=scores,
            decision=CritiqueDecision.VALID,
            suggestions=[],
            explanation=explanation,
            evaluation_time_ms=evaluation_time_ms,
            tokens_used=tokens_used,
        )

    @classmethod
    def create_reject(
        cls,
        scores: CritiqueScores,
        suggestions: List[str],
        explanation: str,
        evaluation_time_ms: int = 0,
        tokens_used: int = 0,
    ) -> "CritiqueResult":
        """Crée un résultat négatif (REJECT).

        Args:
            scores: Scores de l'évaluation.
            suggestions: Suggestions d'amélioration.
            explanation: Explication du rejet.
            evaluation_time_ms: Durée de l'évaluation.
            tokens_used: Tokens utilisés.

        Returns:
            CritiqueResult avec décision REJECT.
        """
        return cls(
            scores=scores,
            decision=CritiqueDecision.REJECT,
            suggestions=suggestions,
            explanation=explanation,
            evaluation_time_ms=evaluation_time_ms,
            tokens_used=tokens_used,
        )
