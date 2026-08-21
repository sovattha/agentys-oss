# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Regenerer un brouillon de reponse email avec de nouvelles instructions.

Pipeline complet : Context -> Draft -> Critique -> (Correction si besoin)
"""

from dataclasses import dataclass
from typing import Optional

from app.domain.entities import Email, Draft, Critique, TokenUsage, DraftStatus
from app.domain.ports import LLMPort


@dataclass
class RegenerateResult:
    """Resultat du pipeline de regeneration."""
    draft_v1: Draft
    critique: Critique
    draft_final: Draft
    status: DraftStatus
    was_corrected: bool
    instructions_used: str

    @property
    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour l'API."""
        return {
            "draft_v1": self.draft_v1.content,
            "critique": {
                "is_valid": self.critique.is_valid,
                "feedback": self.critique.reason or self.critique.raw_response,
            },
            "was_corrected": self.was_corrected,
            "instructions_used": self.instructions_used,
        }


@dataclass
class RegenerateEmailUseCase:
    """
    Pipeline complet de regeneration : Draft V1 -> Critique -> (Correction si besoin)

    Ce use case regenere un brouillon completement depuis zero
    en utilisant les nouvelles instructions fournies par l'utilisateur.
    """
    llm: LLMPort
    knowledge_base: str
    max_tokens_draft: int = 1024
    max_tokens_critique: int = 256
    token_usage: TokenUsage = None

    def __post_init__(self):
        if self.token_usage is None:
            self.token_usage = TokenUsage()

    def execute(
        self,
        email: Email,
        instructions: str,
        context_summary: Optional[str] = None,
    ) -> RegenerateResult:
        """
        Regenere un brouillon avec le pipeline complet.

        Args:
            email: L'email original auquel repondre.
            instructions: Les nouvelles instructions de l'utilisateur.
            context_summary: Resume du contexte (historique emails, etc.) optionnel.

        Returns:
            Le resultat du pipeline avec V1, critique, et V2 si necessaire.
        """
        # Etape 1 : Generer le brouillon V1 avec les nouvelles instructions
        draft_v1 = self._generate_draft(email, instructions, context_summary)

        # Etape 2 : Evaluer le brouillon
        critique = self._critique_draft(draft_v1, email, instructions)

        # Etape 3 : Corriger si necessaire
        if critique.is_valid:
            draft_final = draft_v1
            status = DraftStatus.VALIDATED_V1
            was_corrected = False
        else:
            draft_final = self._revise_draft(draft_v1, critique.raw_response, email, instructions)
            status = DraftStatus.CORRECTED_V2
            was_corrected = True

        return RegenerateResult(
            draft_v1=draft_v1,
            critique=critique,
            draft_final=draft_final,
            status=status,
            was_corrected=was_corrected,
            instructions_used=instructions,
        )

    def _generate_draft(
        self,
        email: Email,
        instructions: str,
        context_summary: Optional[str] = None,
    ) -> Draft:
        """Genere la version V1 du brouillon."""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_draft_prompt(email, instructions, context_summary)

        response = self.llm.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.max_tokens_draft
        )

        self.token_usage.add(
            response.input_tokens,
            response.output_tokens,
            response.model
        )

        return Draft(content=response.content, version=1)

    def _critique_draft(self, draft: Draft, email: Email, instructions: str) -> Critique:
        """Évalue le brouillon généré."""
        system_prompt = self._build_critique_system_prompt()
        user_prompt = self._build_critique_prompt(draft, email, instructions)

        response = self.llm.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.max_tokens_critique
        )

        self.token_usage.add(
            response.input_tokens,
            response.output_tokens,
            response.model
        )

        return Critique.from_response(response.content)

    def _revise_draft(
        self,
        draft_v1: Draft,
        critique: str,
        email: Email,
        instructions: str,
    ) -> Draft:
        """Genere la version V2 corrigee."""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_revision_prompt(draft_v1, critique, email, instructions)

        response = self.llm.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.max_tokens_draft
        )

        self.token_usage.add(
            response.input_tokens,
            response.output_tokens,
            response.model
        )

        return Draft(content=response.content, version=2)

    def _build_system_prompt(self) -> str:
        """Construit le prompt systeme pour le drafter."""
        return f"""Tu es un assistant de redaction d'emails professionnels.

CONTEXTE ET REGLES :
{self.knowledge_base}

INSTRUCTIONS :
- Respecte les instructions specifiques de l'utilisateur
- Reponds dans la meme langue que l'email recu
- Adapte le niveau de formalite (tu/vous) selon l'email
- Sois concis et professionnel
- Ne fais pas de promesses que tu ne peux pas tenir
- N'invente pas d'informations

Genere UNIQUEMENT le corps de la reponse, sans objet ni signature."""

    def _build_draft_prompt(
        self,
        email: Email,
        instructions: str,
        context_summary: Optional[str] = None,
    ) -> str:
        """Construit le prompt de generation."""
        context_part = ""
        if context_summary:
            context_part = f"""CONTEXTE HISTORIQUE (emails precedents avec ce contact) :
{context_summary}

"""
        return f"""{context_part}EMAIL ORIGINAL AUQUEL REPONDRE :
{email.content_for_processing}

INSTRUCTIONS DE L'UTILISATEUR : {instructions}

Redige une reponse en suivant les instructions ci-dessus.

REPONSE :"""

    def _build_critique_system_prompt(self) -> str:
        """Construit le prompt systeme pour le critique."""
        return f"""Tu es un auditeur de reponses emails. Tu dois evaluer si une reponse est acceptable.

CONTEXTE ET REGLES A RESPECTER :
{self.knowledge_base}

CRITERES D'EVALUATION :
1. Respect des instructions utilisateur
2. Coherence et clarte du message
3. Professionnalisme du ton
4. Pas d'informations inventees (hallucinations)
5. Respect des regles du contexte
6. Reponse complete

REPONSE ATTENDUE :
- Si acceptable : "VALID"
- Si probleme : "REJET : [raison precise et actionnable]"

Sois strict mais constructif."""

    def _build_critique_prompt(
        self,
        draft: Draft,
        email: Email,
        instructions: str,
    ) -> str:
        """Construit le prompt d'evaluation."""
        return f"""EMAIL ORIGINAL :
{email.content_for_processing}

INSTRUCTIONS DE L'UTILISATEUR : {instructions}

REPONSE PROPOSEE :
{draft.content}

VERDICT :"""

    def _build_revision_prompt(
        self,
        draft_v1: Draft,
        critique: str,
        email: Email,
        instructions: str,
    ) -> str:
        """Construit le prompt de correction."""
        return f"""Le brouillon suivant a recu cette critique :

CRITIQUE : {critique}

EMAIL ORIGINAL :
{email.content_for_processing}

INSTRUCTIONS DE L'UTILISATEUR : {instructions}

BROUILLON V1 :
{draft_v1.content}

Redige une nouvelle version qui corrige les problemes mentionnes tout en respectant les instructions.

VERSION CORRIGEE :"""
