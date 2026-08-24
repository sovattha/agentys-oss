# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Entités pour la génération de brouillons IA.

Story 5-1: DrafterAgent Implementation
Task 1: Créer entity DraftRequest et DraftResult

Ces dataclasses représentent les entrées et sorties
du DrafterAgent enrichi avec contexte.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.entities.context_analysis import ContextAnalysisResult


class DraftTone(Enum):
    """Ton détecté ou demandé pour le brouillon.

    Représente le style de communication du brouillon généré.
    """

    FORMAL = "formal"
    FRIENDLY = "friendly"
    PROFESSIONAL = "professional"
    NEUTRAL = "neutral"
    URGENT = "urgent"


class DraftStatus(Enum):
    """Statut de la génération de brouillon."""

    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


@dataclass
class DraftRequest:
    """Entrée pour la génération de brouillon.

    Contient toutes les données nécessaires pour générer un brouillon
    de réponse email avec le DrafterAgent.

    Attributes:
        email_content: Contenu de l'email auquel répondre.
        instructions: Instructions utilisateur pour guider la génération.
        context_result: Résultat de l'analyse de contexte (optionnel).
        style_context: Contexte de style de l'utilisateur (optionnel, Story 4-4).
        recipient_email: Email du destinataire pour personnalisation.
        subject: Sujet de l'email de réponse.
        account_id: ID du compte email.
        session_id: Identifiant de session pour tracking.
        tone_hint: Ton souhaité (optionnel).
        max_length: Longueur maximale du brouillon en mots (optionnel).
        conversation_history: Historique des 20 derniers échanges avec le contact.
    """

    email_content: str
    instructions: Optional[str] = None
    context_result: Optional["ContextAnalysisResult"] = None
    style_context: Optional[str] = None
    recipient_email: Optional[str] = None
    subject: Optional[str] = None
    account_id: Optional[int] = None
    session_id: Optional[str] = None
    tone_hint: Optional[DraftTone] = None
    max_length: Optional[int] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None  # Last 20 emails with contact
    user_email: Optional[str] = None  # User's email address for few-shot learning
    thread_context: Optional[List[Dict[str, Any]]] = None  # All thread participants' messages

    def __post_init__(self):
        """Validation après initialisation."""
        if not self.email_content or not self.email_content.strip():
            raise ValueError("email_content cannot be empty")
        if self.max_length is not None and self.max_length <= 0:
            raise ValueError("max_length must be positive")
        # Convert string to enum if needed
        if isinstance(self.tone_hint, str):
            try:
                self.tone_hint = DraftTone(self.tone_hint)
            except ValueError:
                self.tone_hint = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        result = {
            "email_content": self.email_content,
            "instructions": self.instructions,
            "style_context": self.style_context,
            "recipient_email": self.recipient_email,
            "subject": self.subject,
            "account_id": self.account_id,
            "session_id": self.session_id,
            "tone_hint": self.tone_hint.value if self.tone_hint else None,
            "max_length": self.max_length,
            "conversation_history": self.conversation_history,
        }
        if self.context_result:
            result["context_result"] = self.context_result.to_dict()
        return result

    def has_context(self) -> bool:
        """Vérifie si un contexte d'analyse est disponible."""
        return self.context_result is not None

    def get_style_hints(self) -> List[str]:
        """Récupère les indices de style du contexte si disponible."""
        if self.context_result:
            return self.context_result.style_hints
        return []


@dataclass
class DraftResult:
    """Résultat de la génération de brouillon.

    Contient le brouillon généré et les métadonnées associées.

    Attributes:
        content: Contenu du brouillon généré.
        confidence: Score de confiance de la génération (0.0-1.0).
        tone_detected: Ton détecté dans le brouillon.
        generation_time_ms: Durée de génération en millisecondes.
        tokens_used: Nombre de tokens Claude utilisés.
        status: Statut de la génération.
        retry_count: Nombre de tentatives effectuées.
        error_message: Message d'erreur si échec.
        word_count: Nombre de mots du brouillon.
        context_used: True si le contexte d'analyse a été utilisé.
        style_applied: True si le style utilisateur a été appliqué.
        generated_at: Timestamp de génération.
    """

    content: str
    confidence: float = 0.8
    tone_detected: DraftTone = DraftTone.PROFESSIONAL
    generation_time_ms: int = 0
    tokens_used: int = 0
    status: DraftStatus = DraftStatus.COMPLETED
    retry_count: int = 0
    error_message: Optional[str] = None
    word_count: int = 0
    context_used: bool = False
    style_applied: bool = False
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self):
        """Validation et calculs après initialisation."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.generation_time_ms < 0:
            raise ValueError("generation_time_ms must be non-negative")
        if self.tokens_used < 0:
            raise ValueError("tokens_used must be non-negative")
        if self.retry_count < 0:
            raise ValueError("retry_count must be non-negative")

        # Convert strings to enums if needed
        if isinstance(self.tone_detected, str):
            try:
                self.tone_detected = DraftTone(self.tone_detected)
            except ValueError:
                self.tone_detected = DraftTone.PROFESSIONAL
        if isinstance(self.status, str):
            try:
                self.status = DraftStatus(self.status)
            except ValueError:
                self.status = DraftStatus.COMPLETED

        # Calculate word count if not provided
        if self.word_count == 0 and self.content:
            self.word_count = len(self.content.split())

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            "content": self.content,
            "confidence": self.confidence,
            "tone_detected": self.tone_detected.value,
            "generation_time_ms": self.generation_time_ms,
            "tokens_used": self.tokens_used,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "error_message": self.error_message,
            "word_count": self.word_count,
            "context_used": self.context_used,
            "style_applied": self.style_applied,
            "generated_at": self.generated_at.isoformat(),
        }

    def is_successful(self) -> bool:
        """Vérifie si la génération a réussi."""
        return self.status == DraftStatus.COMPLETED and bool(self.content)

    def was_rate_limited(self) -> bool:
        """Vérifie si la génération a été limitée par rate limit."""
        return self.status == DraftStatus.RATE_LIMITED

    @classmethod
    def create_failed(
        cls,
        error_message: str,
        status: DraftStatus = DraftStatus.FAILED,
        retry_count: int = 0,
        generation_time_ms: int = 0,
    ) -> "DraftResult":
        """Crée un résultat d'échec.

        Args:
            error_message: Description de l'erreur.
            status: Statut d'échec (FAILED ou RATE_LIMITED).
            retry_count: Nombre de tentatives effectuées.
            generation_time_ms: Durée totale des tentatives.

        Returns:
            DraftResult avec contenu vide et statut d'erreur.
        """
        return cls(
            content="",
            confidence=0.0,
            status=status,
            error_message=error_message,
            retry_count=retry_count,
            generation_time_ms=generation_time_ms,
        )

    @classmethod
    def create_rate_limited(
        cls,
        retry_count: int,
        generation_time_ms: int = 0,
    ) -> "DraftResult":
        """Crée un résultat pour rate limit atteint.

        Args:
            retry_count: Nombre de tentatives effectuées.
            generation_time_ms: Durée totale des tentatives.

        Returns:
            DraftResult avec statut RATE_LIMITED.
        """
        return cls.create_failed(
            error_message="Rate limit exceeded after maximum retries",
            status=DraftStatus.RATE_LIMITED,
            retry_count=retry_count,
            generation_time_ms=generation_time_ms,
        )


@dataclass
class StreamingDraftChunk:
    """Chunk d'un brouillon en cours de génération (streaming).

    Utilisé pour envoyer des updates en temps réel via WebSocket.

    Attributes:
        chunk: Texte du chunk actuel.
        chunk_index: Index du chunk dans la séquence.
        accumulated_text: Texte total accumulé jusqu'ici.
        is_final: True si c'est le dernier chunk.
        progress_percent: Pourcentage estimé de progression.
        tokens_so_far: Nombre de tokens générés jusqu'ici.
    """

    chunk: str
    chunk_index: int
    accumulated_text: str
    is_final: bool = False
    progress_percent: float = 0.0
    tokens_so_far: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour émission WebSocket."""
        return {
            "chunk": self.chunk,
            "chunk_index": self.chunk_index,
            "accumulated_text": self.accumulated_text,
            "is_final": self.is_final,
            "progress_percent": self.progress_percent,
            "tokens_so_far": self.tokens_so_far,
        }
