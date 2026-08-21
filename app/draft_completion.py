# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Service de complétion de brouillons.

Ce module expose une façade simple pour transformer des idées brèves
en emails professionnels complets.

Exemple d'utilisation :
    agent = DraftCompletionAgent()
    result = agent.complete("Brouillon: Remercier Sophie pour son retour rapide")
"""

from dataclasses import dataclass, field
from typing import Optional

from app.config import MODEL_DEFAULT, MAX_TOKENS_DRAFT
from app.domain.entities import (
    DraftInput,
    DraftInputTone,
    CompletedDraft,
)
from app.domain.ports import LLMPort
from app.application import CompleteDraftUseCase
from app.infrastructure.container import get_container
from app.prompts import load_knowledge_base


@dataclass
class DraftCompletionAgent:
    """
    Agent responsable de la complétion de brouillons.

    Transforme des idées brèves, bullet points ou notes
    en emails professionnels structurés et prêts à envoyer.

    Cette classe est une façade qui délègue au CompleteDraftUseCase.
    """
    model: str = MODEL_DEFAULT
    max_tokens: int = MAX_TOKENS_DRAFT
    knowledge_base: str = field(default_factory=load_knowledge_base)
    _llm: Optional[LLMPort] = field(default=None, repr=False)
    _use_case: Optional[CompleteDraftUseCase] = field(default=None, repr=False)

    def __post_init__(self):
        container = get_container()
        # User-facing draft auto-completion → drafting key (Haiku for cost).
        self._llm = container.llm_drafting
        self._use_case = CompleteDraftUseCase(
            llm=self._llm,
            knowledge_base=self.knowledge_base,
            max_tokens=self.max_tokens,
            token_usage=container.token_usage,
        )

    def complete(self, raw_input: str) -> CompletedDraft:
        """
        Complète un brouillon à partir d'idées brèves.

        Args:
            raw_input: Les idées brèves de l'utilisateur.
                       Peut être préfixé par "Brouillon:", "Draft:", etc.
                       Ou simplement contenir des bullet points.

        Returns:
            Le brouillon complété avec objet et corps.
        """
        draft_input = DraftInput.from_raw_text(raw_input)
        return self._use_case.execute(draft_input)

    def complete_with_options(
        self,
        raw_input: str,
        recipient: Optional[str] = None,
        tone: Optional[DraftInputTone] = None,
        subject_hint: Optional[str] = None,
    ) -> CompletedDraft:
        """
        Complète un brouillon avec des options explicites.

        Args:
            raw_input: Les idées brèves.
            recipient: Le destinataire (si connu).
            tone: Le ton souhaité.
            subject_hint: Un indice sur le sujet.

        Returns:
            Le brouillon complété.
        """
        draft_input = DraftInput.from_raw_text(raw_input)

        # Override avec les options explicites
        if recipient:
            draft_input.recipient = recipient
        if tone:
            draft_input.tone = tone
        if subject_hint:
            draft_input.subject_hint = subject_hint

        return self._use_case.execute(draft_input)

    @staticmethod
    def is_completion_request(text: str) -> bool:
        """
        Détecte si le texte est une demande de complétion de brouillon.

        Args:
            text: Le texte à analyser.

        Returns:
            True si c'est une demande de complétion.
        """
        return DraftInput.is_draft_input(text)


def complete_draft(raw_input: str) -> CompletedDraft:
    """
    Fonction utilitaire pour compléter un brouillon.

    Args:
        raw_input: Les idées brèves de l'utilisateur.

    Returns:
        Le brouillon complété.

    Example:
        >>> result = complete_draft("Brouillon: Remercier Sophie")
        >>> print(result.formatted_output)
    """
    agent = DraftCompletionAgent()
    return agent.complete(raw_input)


def is_draft_request(text: str) -> bool:
    """
    Vérifie si le texte est une demande de complétion.

    Args:
        text: Le texte à analyser.

    Returns:
        True si c'est une demande de complétion.

    Example:
        >>> is_draft_request("Brouillon: Remercier Sophie")
        True
        >>> is_draft_request("Bonjour, comment allez-vous ?")
        False
    """
    return DraftInput.is_draft_input(text)
