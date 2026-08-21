# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entite DraftRecord pour le domaine.

Represente un enregistrement de brouillon genere par le systeme.
Pure entity sans dependance externe.
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class DraftRecord:
    """
    Enregistrement d'un brouillon genere.

    Attributes:
        id: Identifiant unique du brouillon.
        timestamp: Date/heure ISO de creation.
        email_id: ID de l'email original.
        email_sender: Expediteur de l'email.
        email_subject: Sujet de l'email.
        email_preview: Apercu du contenu (100 premiers caracteres).
        draft_v1: Premiere version du brouillon.
        critique: Evaluation du CriticAgent.
        draft_final: Version finale apres eventuelle revision.
        status: Statut (V1 = valide directement, V2 = corrige).
        draft_id: ID du brouillon cree dans le provider email.
        tokens_used: Nombre de tokens utilises.
        model: Modele LLM utilise.
        processing_time_ms: Temps de traitement en millisecondes.
        priority_score: Score de priorite (0-100).
        category: Categorie de l'email (URGENT, NORMAL, etc.).
        feedback: Type de feedback utilisateur.
        feedback_comment: Commentaire de feedback.
        feedback_rating: Note de feedback (1-5).
    """

    # Champs obligatoires
    id: str
    timestamp: str
    email_id: str
    email_sender: str
    email_subject: str
    email_preview: str
    draft_v1: str
    critique: str
    draft_final: str
    status: str

    # account_id — REQUIS pour l'isolation multi-compte. Les rows legacy
    # sans account_id (valeur None) ne sont jamais retournés par les
    # méthodes scoped des adapters. Toute nouvelle insertion DOIT fournir
    # un account_id > 0 sous peine d'assertion.
    account_id: Optional[int] = None

    # Champs optionnels
    draft_id: Optional[str] = None
    tokens_used: int = 0
    model: str = ""
    processing_time_ms: int = 0
    priority_score: Optional[int] = None
    category: Optional[str] = None
    feedback: Optional[str] = None
    feedback_comment: Optional[str] = None
    feedback_rating: Optional[int] = None

    # Alias pour retrocompatibilite avec le module legacy
    @property
    def email_body(self) -> str:
        """Alias pour email_preview (retrocompatibilite)."""
        return self.email_preview

    def to_correction_context(self) -> Dict[str, Optional[str]]:
        """
        Retourne un dictionnaire de contexte pour les corrections utilisateur.

        Ce contexte est utilisé par le DraftCorrectionManager pour enrichir
        l'apprentissage des corrections avec les métadonnées de l'email original.

        Returns:
            Dictionnaire contenant sender, subject et category.
        """
        return {
            "sender": self.email_sender,
            "subject": self.email_subject,
            "category": self.category,
        }

    def with_feedback(
        self,
        feedback: str,
        comment: str = "",
        rating: Optional[int] = None,
    ) -> "DraftRecord":
        """
        Retourne une copie avec le feedback mis a jour.

        Args:
            feedback: Type de feedback (positive, negative, neutral).
            comment: Commentaire optionnel.
            rating: Note de 1 a 5 (optionnel).

        Returns:
            Nouvelle instance avec le feedback.
        """
        return DraftRecord(
            id=self.id,
            timestamp=self.timestamp,
            email_id=self.email_id,
            email_sender=self.email_sender,
            email_subject=self.email_subject,
            email_preview=self.email_preview,
            draft_v1=self.draft_v1,
            critique=self.critique,
            draft_final=self.draft_final,
            status=self.status,
            account_id=self.account_id,
            draft_id=self.draft_id,
            tokens_used=self.tokens_used,
            model=self.model,
            processing_time_ms=self.processing_time_ms,
            priority_score=self.priority_score,
            category=self.category,
            feedback=feedback,
            feedback_comment=comment,
            feedback_rating=rating,
        )
