# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Pipeline complet de traitement d'un email.
"""

from dataclasses import dataclass

from app.domain.entities import Email, ProcessingResult, DraftStatus, TokenUsage
from app.domain.ports import LLMPort

from .draft_email import DraftEmailUseCase
from .critique_email import CritiqueEmailUseCase


@dataclass
class ProcessEmailUseCase:
    """
    Pipeline complet : Draft V1 → Critique → (Correction si besoin)

    Ce use case orchestre le workflow complet de génération de réponse.
    """
    llm: LLMPort
    knowledge_base: str
    max_tokens_draft: int = 1024
    max_tokens_critique: int = 256
    token_usage: TokenUsage = None

    def __post_init__(self):
        if self.token_usage is None:
            self.token_usage = TokenUsage()

    def execute(self, email: Email) -> ProcessingResult:
        """
        Traite un email avec le pipeline complet.

        Args:
            email: L'email à traiter.

        Returns:
            Le résultat du traitement.
        """
        # Initialiser les use cases avec le même token_usage
        drafter = DraftEmailUseCase(
            llm=self.llm,
            knowledge_base=self.knowledge_base,
            max_tokens=self.max_tokens_draft,
            token_usage=self.token_usage
        )

        critic = CritiqueEmailUseCase(
            llm=self.llm,
            knowledge_base=self.knowledge_base,
            max_tokens=self.max_tokens_critique,
            token_usage=self.token_usage
        )

        # Étape 1 : Générer le brouillon V1
        draft_v1 = drafter.execute(email)

        # Étape 2 : Évaluer le brouillon
        critique = critic.execute(email, draft_v1)

        # Étape 3 : Corriger si nécessaire
        if critique.is_valid:
            draft_final = draft_v1
            status = DraftStatus.VALIDATED_V1
        else:
            draft_final = drafter.execute_revision(email, critique.raw_response)
            status = DraftStatus.CORRECTED_V2

        return ProcessingResult(
            email_id=email.id,
            draft_v1=draft_v1,
            critique=critique,
            draft_final=draft_final,
            status=status
        )
