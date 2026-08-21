# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Évaluer un brouillon de réponse email.
"""

from dataclasses import dataclass

from app.domain.entities import Email, Draft, Critique, TokenUsage
from app.domain.ports import LLMPort


@dataclass
class CritiqueEmailUseCase:
    """
    Évalue un brouillon de réponse email.

    Ce use case utilise un LLM pour auditer une réponse selon des critères
    stricts : cohérence du ton, respect du contexte, absence d'hallucinations.
    """
    llm: LLMPort
    knowledge_base: str
    max_tokens: int = 256
    token_usage: TokenUsage = None

    def __post_init__(self):
        if self.token_usage is None:
            self.token_usage = TokenUsage()

    def execute(self, email: Email, draft: Draft) -> Critique:
        """
        Évalue un brouillon.

        Args:
            email: L'email original.
            draft: Le brouillon à évaluer.

        Returns:
            La critique du brouillon.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(email, draft)

        response = self.llm.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.max_tokens
        )

        self.token_usage.add(
            response.input_tokens,
            response.output_tokens,
            response.model
        )

        return Critique.from_response(response.content)

    def _build_system_prompt(self) -> str:
        """Construit le prompt système."""
        return f"""Tu es un auditeur de réponses emails. Tu dois évaluer si une réponse est acceptable.

CONTEXTE ET RÈGLES À RESPECTER :
{self.knowledge_base}

CRITÈRES D'ÉVALUATION :
1. Cohérence du ton avec l'email original
2. Respect de la langue de l'email (FR, EN, etc.)
3. Pas d'informations inventées (hallucinations)
4. Respect des règles du contexte
5. Réponse complète et professionnelle

RÉPONSE ATTENDUE :
- Si acceptable : "VALID"
- Si problème : "REJET : [raison précise et actionnable]"

Sois strict mais constructif."""

    def _build_user_prompt(self, email: Email, draft: Draft) -> str:
        """Construit le prompt utilisateur."""
        return f"""Évalue cette réponse :

EMAIL ORIGINAL :
{email.content_for_processing}

RÉPONSE PROPOSÉE :
{draft.content}

VERDICT :"""
