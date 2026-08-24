# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Entités pour l'orchestration du pipeline de génération.

Story 5-3: Draft Regeneration Loop
Task 1: Créer entities OrchestrationRequest, OrchestrationResult, IterationRecord

Ces dataclasses représentent les entrées et sorties
du DraftOrchestrator qui coordonne le pipeline DrafterAgent <-> CriticAgent.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.entities.draft_generation import DraftRequest, DraftResult
    from app.domain.entities.critique import CritiqueResult
    from app.domain.entities.context_analysis import ContextAnalysisResult


class OrchestrationStatus(Enum):
    """Statut de l'orchestration du pipeline.

    IN_PROGRESS: Le pipeline est en cours d'exécution.
    COMPLETED: Le pipeline a terminé avec succès (VALID ou max iterations).
    TIMEOUT: Le pipeline a dépassé le timeout global.
    FAILED: Le pipeline a échoué avec une erreur.
    """

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    FAILED = "failed"


@dataclass
class IterationRecord:
    """Enregistrement d'une itération du pipeline de régénération.

    Contient les résultats d'une passe DrafterAgent -> CriticAgent.

    Attributes:
        draft_result: Résultat de la génération du brouillon.
        critique_result: Résultat de l'évaluation (peut être None si timeout).
        iteration_number: Numéro de l'itération (1-based).
        duration_ms: Durée de l'itération en millisecondes.
        started_at: Timestamp de début de l'itération.
    """

    draft_result: "DraftResult"
    critique_result: Optional["CritiqueResult"]
    iteration_number: int
    duration_ms: int
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        """Validation après initialisation."""
        if self.iteration_number < 1:
            raise ValueError("iteration_number must be >= 1")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")

    def get_score(self) -> int:
        """Retourne le score de critique de cette itération.

        Returns:
            Score global (0-100) ou 0 si pas de critique disponible.
        """
        if self.critique_result:
            return self.critique_result.scores.calculate_overall()
        return 0

    def is_valid(self) -> bool:
        """Vérifie si le draft de cette itération a été validé.

        Returns:
            True si le CriticAgent a validé le draft.
        """
        if self.critique_result:
            from app.domain.entities.critique import CritiqueDecision
            return self.critique_result.decision == CritiqueDecision.VALID
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "iteration_number": self.iteration_number,
            "draft_content": self.draft_result.content[:200] + "..."
                if len(self.draft_result.content) > 200 else self.draft_result.content,
            "draft_confidence": self.draft_result.confidence,
            "draft_status": self.draft_result.status.value,
            "critique_score": self.get_score(),
            "critique_decision": self.critique_result.decision.value
                if self.critique_result else None,
            "critique_suggestions": self.critique_result.suggestions[:3]
                if self.critique_result else [],
            "duration_ms": self.duration_ms,
            "is_valid": self.is_valid(),
            "started_at": self.started_at.isoformat(),
        }


@dataclass
class OrchestrationRequest:
    """Entrée pour l'orchestration du pipeline de génération.

    Contient toutes les données nécessaires pour exécuter le pipeline
    complet DrafterAgent -> CriticAgent avec régénération.

    Attributes:
        email_content: Contenu de l'email auquel répondre.
        email_id: ID de l'email pour tracking WebSocket.
        context_result: Résultat de l'analyse de contexte (optionnel).
        instructions: Instructions utilisateur pour la génération.
        style_context: Contexte de style de l'utilisateur (optionnel).
        max_iterations: Nombre maximum d'itérations (default: 2).
        quality_threshold: Seuil de qualité pour validation (default: 70).
        timeout_seconds: Timeout global en secondes (default: 240).
        iteration_timeout_seconds: Timeout par itération (default: 60).
        session_id: Identifiant de session pour tracking.
        recipient_email: Email du destinataire.
        subject: Sujet de l'email.
        account_id: ID du compte email.
        conversation_history: Historique des 20 derniers échanges avec le contact.
    """

    email_content: str
    email_id: Optional[str] = None
    context_result: Optional["ContextAnalysisResult"] = None
    instructions: Optional[str] = None
    style_context: Optional[str] = None
    max_iterations: int = 2
    quality_threshold: int = 70
    timeout_seconds: int = 240
    iteration_timeout_seconds: int = 60
    session_id: Optional[str] = None
    recipient_email: Optional[str] = None
    subject: Optional[str] = None
    account_id: Optional[int] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None  # Last 20 emails with contact

    def __post_init__(self):
        """Validation après initialisation."""
        if not self.email_content or not self.email_content.strip():
            raise ValueError("email_content cannot be empty")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.max_iterations > 5:
            raise ValueError("max_iterations must be <= 5 to prevent runaway loops")
        if not 0 <= self.quality_threshold <= 100:
            raise ValueError("quality_threshold must be between 0 and 100")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.iteration_timeout_seconds <= 0:
            raise ValueError("iteration_timeout_seconds must be positive")

    def to_draft_request(self) -> "DraftRequest":
        """Convertit en DraftRequest pour le DrafterAgent.

        Returns:
            DraftRequest configuré pour la génération.
        """
        from app.domain.entities.draft_generation import DraftRequest
        return DraftRequest(
            email_content=self.email_content,
            instructions=self.instructions,
            context_result=self.context_result,
            style_context=self.style_context,
            recipient_email=self.recipient_email,
            subject=self.subject,
            account_id=self.account_id,
            session_id=self.session_id,
            conversation_history=self.conversation_history,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        result = {
            "email_content": self.email_content[:200] + "..."
                if len(self.email_content) > 200 else self.email_content,
            "email_id": self.email_id,
            "instructions": self.instructions,
            "style_context": self.style_context[:100] + "..."
                if self.style_context and len(self.style_context) > 100 else self.style_context,
            "max_iterations": self.max_iterations,
            "quality_threshold": self.quality_threshold,
            "timeout_seconds": self.timeout_seconds,
            "iteration_timeout_seconds": self.iteration_timeout_seconds,
            "session_id": self.session_id,
            "recipient_email": self.recipient_email,
            "subject": self.subject,
            "account_id": self.account_id,
            "has_context": self.context_result is not None,
        }
        return result


@dataclass
class OrchestrationResult:
    """Résultat complet de l'orchestration du pipeline.

    Contient le brouillon final, l'historique des itérations,
    et les métriques de performance.

    Attributes:
        final_draft: Le brouillon final sélectionné.
        iterations: Historique de toutes les itérations.
        total_duration_ms: Durée totale du pipeline en millisecondes.
        status: Statut final de l'orchestration.
        total_tokens_used: Nombre total de tokens utilisés.
        error_message: Message d'erreur si échec.
        completed_at: Timestamp de fin de l'orchestration.
    """

    final_draft: "DraftResult"
    iterations: List[IterationRecord] = field(default_factory=list)
    total_duration_ms: int = 0
    status: OrchestrationStatus = OrchestrationStatus.COMPLETED
    total_tokens_used: int = 0
    error_message: Optional[str] = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        """Validation après initialisation."""
        if self.total_duration_ms < 0:
            raise ValueError("total_duration_ms must be non-negative")
        if self.total_tokens_used < 0:
            raise ValueError("total_tokens_used must be non-negative")

        # Convert string to enum if needed
        if isinstance(self.status, str):
            try:
                self.status = OrchestrationStatus(self.status.lower())
            except ValueError:
                self.status = OrchestrationStatus.FAILED

    def get_iteration_count(self) -> int:
        """Retourne le nombre d'itérations effectuées."""
        return len(self.iterations)

    def get_best_draft(self) -> "DraftResult":
        """Retourne le draft avec le meilleur score de critique.

        Si aucune itération n'a de critique, retourne le final_draft.

        Returns:
            Le DraftResult avec le meilleur score.
        """
        if not self.iterations:
            return self.final_draft

        # Filtrer les itérations avec critique
        scored_iterations = [
            it for it in self.iterations
            if it.critique_result is not None
        ]

        if not scored_iterations:
            return self.final_draft

        # Trouver le meilleur score
        best = max(scored_iterations, key=lambda it: it.get_score())
        return best.draft_result

    def get_best_score(self) -> int:
        """Retourne le meilleur score obtenu.

        Returns:
            Score maximal (0-100) ou 0 si aucune évaluation.
        """
        if not self.iterations:
            return 0

        scores = [it.get_score() for it in self.iterations if it.critique_result]
        return max(scores) if scores else 0

    def get_final_score(self) -> int:
        """Retourne le score du draft final.

        Returns:
            Score du dernier draft évalué ou 0.
        """
        if self.iterations and self.iterations[-1].critique_result:
            return self.iterations[-1].get_score()
        return 0

    def was_validated(self) -> bool:
        """Vérifie si le pipeline a produit un draft validé.

        Returns:
            True si la dernière itération a été validée.
        """
        if self.iterations:
            return self.iterations[-1].is_valid()
        return False

    def is_successful(self) -> bool:
        """Vérifie si l'orchestration a réussi.

        Returns:
            True si status est COMPLETED et draft_content non vide.
        """
        return (
            self.status == OrchestrationStatus.COMPLETED
            and self.final_draft is not None
            and bool(self.final_draft.content)
        )

    def was_timeout(self) -> bool:
        """Vérifie si l'orchestration a dépassé le timeout."""
        return self.status == OrchestrationStatus.TIMEOUT

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "final_draft": self.final_draft.to_dict() if self.final_draft else None,
            "iterations": [it.to_dict() for it in self.iterations],
            "iteration_count": self.get_iteration_count(),
            "total_duration_ms": self.total_duration_ms,
            "status": self.status.value,
            "total_tokens_used": self.total_tokens_used,
            "error_message": self.error_message,
            "completed_at": self.completed_at.isoformat(),
            "best_score": self.get_best_score(),
            "final_score": self.get_final_score(),
            "was_validated": self.was_validated(),
            "is_successful": self.is_successful(),
        }

    @classmethod
    def create_failed(
        cls,
        error_message: str,
        status: OrchestrationStatus = OrchestrationStatus.FAILED,
        iterations: Optional[List[IterationRecord]] = None,
        total_duration_ms: int = 0,
        total_tokens_used: int = 0,
    ) -> "OrchestrationResult":
        """Crée un résultat d'échec.

        Args:
            error_message: Description de l'erreur.
            status: Statut d'échec (FAILED ou TIMEOUT).
            iterations: Itérations effectuées avant l'échec.
            total_duration_ms: Durée totale.
            total_tokens_used: Tokens utilisés.

        Returns:
            OrchestrationResult avec statut d'erreur.
        """
        from app.domain.entities.draft_generation import DraftResult, DraftStatus

        # Utiliser le meilleur draft disponible ou créer un échec
        best_draft = None
        if iterations:
            scored = [it for it in iterations if it.critique_result]
            if scored:
                best = max(scored, key=lambda it: it.get_score())
                best_draft = best.draft_result

        if best_draft is None:
            best_draft = DraftResult.create_failed(
                error_message=error_message,
                status=DraftStatus.FAILED,
            )

        return cls(
            final_draft=best_draft,
            iterations=iterations or [],
            total_duration_ms=total_duration_ms,
            status=status,
            total_tokens_used=total_tokens_used,
            error_message=error_message,
        )

    @classmethod
    def create_timeout(
        cls,
        iterations: List[IterationRecord],
        total_duration_ms: int,
        total_tokens_used: int = 0,
    ) -> "OrchestrationResult":
        """Crée un résultat pour timeout atteint.

        Retourne le meilleur draft disponible parmi les itérations.

        Args:
            iterations: Itérations effectuées avant le timeout.
            total_duration_ms: Durée totale.
            total_tokens_used: Tokens utilisés.

        Returns:
            OrchestrationResult avec le meilleur draft et statut TIMEOUT.
        """
        from app.domain.entities.draft_generation import DraftResult, DraftStatus

        # Trouver le meilleur draft
        best_draft = None
        if iterations:
            # D'abord, essayer avec les scores
            scored = [it for it in iterations if it.critique_result]
            if scored:
                best = max(scored, key=lambda it: it.get_score())
                best_draft = best.draft_result
            else:
                # Prendre le dernier draft disponible
                best_draft = iterations[-1].draft_result

        if best_draft is None:
            best_draft = DraftResult.create_failed(
                error_message="Timeout reached with no drafts",
                status=DraftStatus.FAILED,
            )

        return cls(
            final_draft=best_draft,
            iterations=iterations,
            total_duration_ms=total_duration_ms,
            status=OrchestrationStatus.TIMEOUT,
            total_tokens_used=total_tokens_used,
            error_message="Global timeout reached, returning best draft",
        )
