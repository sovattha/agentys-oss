# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Compléter un brouillon à partir d'idées brèves.

Ce use case transforme des bullet points ou idées courtes
en un email professionnel complet et structuré.
"""

from dataclasses import dataclass, field

from app.domain.entities import DraftInput, DraftInputTone, CompletedDraft, TokenUsage
from app.domain.ports import LLMPort


COMPLETION_SYSTEM_PROMPT = """Tu transformes des idées brèves ou bullet points en courriel complet prêt à envoyer.

RÈGLES :
1. Intègre TOUS les points fournis. N'invente aucun détail absent des notes.
2. Adapte le ton selon les indications (formel, amical, urgent, neutre).
3. ZÉRO formule IA : pas de "N'hésite pas", "Je reste à votre disposition", "Je me permets de".
4. Direct et concis — chaque phrase apporte une info des notes.
5. Pas de signature — ajoutée automatiquement.

FORMAT :
OBJET: [L'objet du courriel]

[Corps du courriel avec salutation et contenu]"""


COMPLETION_USER_PROMPT_TEMPLATE = """Transforme ces idées en courriel professionnel complet :

{key_points}

{context}

Génère le courriel complet au format demandé."""


@dataclass
class CompleteDraftUseCase:
    """
    Complète un brouillon à partir d'idées brèves.

    Ce use case utilise un LLM pour transformer des notes
    ou bullet points en email professionnel.
    """
    llm: LLMPort
    knowledge_base: str = ""
    max_tokens: int = 1024
    token_usage: TokenUsage = field(default=None)

    def __post_init__(self):
        if self.token_usage is None:
            self.token_usage = TokenUsage()

    def execute(self, draft_input: DraftInput) -> CompletedDraft:
        """
        Complète un brouillon à partir d'idées brèves.

        Args:
            draft_input: Les idées brèves de l'utilisateur.

        Returns:
            Le brouillon complété.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(draft_input)

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

        return self._parse_response(response.content, draft_input)

    def _build_system_prompt(self) -> str:
        """Construit le prompt système."""
        base_prompt = COMPLETION_SYSTEM_PROMPT

        if self.knowledge_base:
            base_prompt += f"\n\nCONTEXTE ENTREPRISE :\n{self.knowledge_base}"

        return base_prompt

    def _build_user_prompt(self, draft_input: DraftInput) -> str:
        """Construit le prompt utilisateur."""
        # Formater les points clés
        key_points_text = "\n".join(
            f"- {point}" for point in draft_input.key_points
        )
        if not key_points_text:
            key_points_text = draft_input.raw_input

        # Construire le contexte additionnel
        context_parts = []

        if draft_input.recipient:
            context_parts.append(f"Destinataire : {draft_input.recipient}")

        if draft_input.subject_hint:
            context_parts.append(f"Sujet probable : {draft_input.subject_hint}")

        tone_descriptions = {
            DraftInputTone.FORMAL: "Ton formel et professionnel (vouvoiement)",
            DraftInputTone.FRIENDLY: "Ton amical et décontracté (tutoiement possible)",
            DraftInputTone.URGENT: "Ton urgent mais professionnel",
            DraftInputTone.CONCILIATORY: "Ton conciliant et empathique",
            DraftInputTone.NEUTRAL: "Ton neutre et professionnel",
        }
        context_parts.append(f"Ton souhaité : {tone_descriptions[draft_input.tone]}")

        context_text = "\n".join(context_parts) if context_parts else ""

        return COMPLETION_USER_PROMPT_TEMPLATE.format(
            key_points=key_points_text,
            context=context_text
        )

    def _parse_response(
        self,
        response: str,
        draft_input: DraftInput
    ) -> CompletedDraft:
        """
        Parse la réponse du LLM pour extraire le sujet et le corps.

        Args:
            response: La réponse brute du LLM.
            draft_input: L'entrée originale.

        Returns:
            Le brouillon complété et structuré.
        """
        lines = response.strip().split('\n')
        subject = ""
        body_lines = []

        for line in lines:
            line_upper = line.upper().strip()

            # Détecter la ligne d'objet
            if line_upper.startswith("OBJET:") or line_upper.startswith("OBJET :"):
                subject = line.split(":", 1)[1].strip() if ":" in line else ""
                continue

            # Ignorer les lignes vides entre objet et corps
            if not subject and not line.strip():
                continue

            # Tout le reste fait partie du corps
            if subject or line.strip():
                body_lines.append(line)

        body = "\n".join(body_lines).strip()

        # Fallback si pas d'objet détecté
        if not subject and draft_input.subject_hint:
            subject = draft_input.subject_hint
        elif not subject and draft_input.key_points:
            # Générer un objet à partir du premier point
            first_point = draft_input.key_points[0]
            subject = first_point[:50] + ("..." if len(first_point) > 50 else "")

        # Si le corps contient encore "OBJET:", c'est que le parsing a échoué
        if not body:
            body = response.strip()

        return CompletedDraft(
            subject=subject,
            body=body,
            recipient=draft_input.recipient,
            tone_used=draft_input.tone
        )
