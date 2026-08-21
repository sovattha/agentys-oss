# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Générer un brouillon de réponse email.
"""

from dataclasses import dataclass

from app.domain.entities import Email, Draft, TokenUsage
from app.domain.ports import LLMPort


@dataclass
class DraftEmailUseCase:
    """
    Génère un brouillon de réponse à un email.

    Ce use case utilise un LLM pour rédiger une réponse professionnelle
    en respectant le contexte fourni (knowledge base).
    """
    llm: LLMPort
    knowledge_base: str
    max_tokens: int = 1024
    token_usage: TokenUsage = None

    def __post_init__(self):
        if self.token_usage is None:
            self.token_usage = TokenUsage()

    def execute(self, email: Email) -> Draft:
        """
        Génère un brouillon V1.

        Args:
            email: L'email auquel répondre.

        Returns:
            Le brouillon généré.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(email)

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

        return Draft(content=response.content, version=1)

    def execute_revision(self, email: Email, critique: str) -> Draft:
        """
        Génère un brouillon V2 basé sur une critique.

        Args:
            email: L'email original.
            critique: La critique du brouillon V1.

        Returns:
            Le brouillon corrigé.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_revision_prompt(email, critique)

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

        return Draft(content=response.content, version=2)

    def _build_system_prompt(self) -> str:
        """Construit le prompt système."""
        return f"""Tu es un assistant de rédaction d'emails professionnels.

CONTEXTE ET RÈGLES :
{self.knowledge_base}

INSTRUCTIONS :
- Réponds dans la même langue que l'email reçu
- Adapte le niveau de formalité (tu/vous) selon l'email
- Sois concis et professionnel
- Ne fais pas de promesses que tu ne peux pas tenir
- N'invente pas d'informations

Génère UNIQUEMENT le corps de la réponse, sans objet ni signature."""

    def _build_user_prompt(self, email: Email) -> str:
        """Construit le prompt utilisateur."""
        return f"""Rédige une réponse à cet email :

{email.content_for_processing}

RÉPONSE :"""

    def _build_revision_prompt(self, email: Email, critique: str) -> str:
        """Construit le prompt de correction."""
        return f"""L'email suivant a reçu cette critique :

CRITIQUE : {critique}

EMAIL ORIGINAL :
{email.content_for_processing}

Rédige une nouvelle version qui corrige les problèmes mentionnés.

RÉPONSE CORRIGÉE :"""
