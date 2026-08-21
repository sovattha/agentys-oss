# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Affiner un brouillon de réponse email selon une instruction utilisateur.

Pipeline : Refine V1 → Critique → (Correction si besoin)
"""

from dataclasses import dataclass
from typing import Optional

from app.domain.entities import Email, Draft, Critique, TokenUsage, DraftStatus
from app.domain.ports import LLMPort
from app.utils.draft_cleanup import (
    strip_ai_dashes as _strip_ai_dashes,
    strip_reasoning_leakage as _strip_reasoning_leakage,
)


@dataclass
class RefineResult:
    """Résultat du pipeline de refinement."""
    draft_v1: Draft
    critique: Critique
    draft_final: Draft
    status: DraftStatus
    was_corrected: bool

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
        }


@dataclass
class RefineEmailUseCase:
    """
    Pipeline complet de refinement : Refine V1 → Critique → (Correction si besoin)

    Ce use case orchestre le workflow de modification d'un brouillon existant
    selon une instruction utilisateur, puis valide via le critique.

    Audit 2026-05-04 (refine parity) : ajout de 4 champs optionnels pour
    l'enrichissement du system prompt à parité avec le draft initial.
    Quand renseignés, ils permettent d'injecter dans le system prompt les
    mêmes éléments que ``get_standard_draft_prompts`` du chemin reply :
    few-shot examples (sent_examples + user_formulas), style metrics
    (tu/vous, longueur de phrases), learned rules (corrections passées),
    contact summary. Sans eux, le comportement reste celui d'avant —
    backward-compatible pour les callers existants.
    """
    llm: LLMPort
    knowledge_base: str
    max_tokens_draft: int = 1024
    max_tokens_critique: int = 256
    token_usage: TokenUsage = None

    # Audit 2026-05-04 — refine parity. Tous optionnels, default no-op.
    account_id: Optional[int] = None
    user_email: str = ""
    contact_email: str = ""
    conversation_history: Optional[list] = None

    def __post_init__(self):
        if self.token_usage is None:
            self.token_usage = TokenUsage()

    def execute(
        self,
        current_draft: str,
        instruction: str,
        email: Email = None,
    ) -> RefineResult:
        """
        Affine un brouillon avec le pipeline complet.

        Args:
            current_draft: Le brouillon actuel à affiner.
            instruction: L'instruction utilisateur (ex: "raccourcir", "plus formel").
            email: L'email original (optionnel, pour le contexte).

        Returns:
            Le résultat du pipeline avec V1, critique, et V2 si nécessaire.
        """
        # Étape 1 : Générer le brouillon affiné V1
        draft_v1 = self._refine_draft(current_draft, instruction, email)

        # Étape 2 : Évaluer le brouillon
        critique = self._critique_draft(draft_v1, email, instruction)

        # Étape 3 : Corriger si nécessaire
        if critique.is_valid:
            draft_final = draft_v1
            status = DraftStatus.VALIDATED_V1
            was_corrected = False
        else:
            draft_final = self._revise_draft(draft_v1, critique.raw_response, instruction, email)
            status = DraftStatus.CORRECTED_V2
            was_corrected = True

        return RefineResult(
            draft_v1=draft_v1,
            critique=critique,
            draft_final=draft_final,
            status=status,
            was_corrected=was_corrected,
        )

    def _refine_draft(self, current_draft: str, instruction: str, email: Email = None) -> Draft:
        """Génère la version affinée V1."""
        is_generation = not current_draft or not current_draft.strip()
        system_prompt = self._build_system_prompt(is_generation=is_generation)
        user_prompt = self._build_refine_prompt(current_draft, instruction, email)

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

        return Draft(content=_strip_ai_dashes(_strip_reasoning_leakage(response.content)), version=1)

    def _critique_draft(self, draft: Draft, email: Email = None, instruction: str = "") -> Critique:
        """Évalue le brouillon affiné."""
        system_prompt = self._build_critique_system_prompt(instruction)
        user_prompt = self._build_critique_prompt(draft, email)

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
        instruction: str,
        email: Email = None
    ) -> Draft:
        """Génère la version V2 corrigée."""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_revision_prompt(draft_v1, critique, instruction, email)

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

        return Draft(content=_strip_ai_dashes(_strip_reasoning_leakage(response.content)), version=2)

    def _build_context_blocks(self) -> str:
        """Construit les blocs de contexte enrichi pour la parité avec le draft initial.

        Audit 2026-05-04 — refine parity : injecte les mêmes éléments que
        ``get_standard_draft_prompts`` du path initial draft, quand les
        champs ``account_id`` / ``user_email`` / ``contact_email`` /
        ``conversation_history`` sont renseignés. Tous les blocs sont
        no-op si la donnée nécessaire est absente — le caller minimal
        (``RefineEmailUseCase(llm, knowledge_base)`` sans contexte)
        produit le même prompt qu'avant.

        Blocs injectés (chacun fail-safe via try/except) :
            1. ``extract_sent_examples`` — few-shot des emails déjà
               envoyés par l'utilisateur, ancre la voix.
            2. ``extract_user_formulas`` — formulations habituelles.
            3. ``compute_style_metrics`` — métriques quantitatives
               (tu/vous, longueur, exclamation rate).
            4. ``_get_learning_section`` — règles apprises depuis les
               corrections passées (per-contact si possible).
            5. ``contact_summary_service`` + ``format_contact_summary`` —
               résumé long-terme du contact.
        """
        # Aucun contexte fourni → rien à injecter.
        if not (self.account_id or self.conversation_history):
            return ""

        blocks: list[str] = []

        # 1-3. Style-related blocks need ``conversation_history`` + ``user_email``.
        if self.conversation_history and self.user_email:
            try:
                from app.prompts import (
                    extract_sent_examples,
                    extract_user_formulas,
                    compute_style_metrics,
                )
                sent = extract_sent_examples(
                    self.conversation_history, self.user_email, max_examples=2,
                )
                if sent:
                    blocks.append(sent)
                formulas = extract_user_formulas(self.conversation_history, self.user_email)
                if formulas:
                    blocks.append(formulas)
                metrics = compute_style_metrics(
                    self.conversation_history, self.user_email,
                    contact=self.contact_email or "",
                )
                if metrics:
                    blocks.append(metrics)
            except Exception:
                # Style helpers should never break refine.
                pass

        # 4. Learned rules (depends only on account_id; contact is best-effort).
        if self.account_id:
            try:
                from app.prompts.builders import _get_learning_section
                learned = _get_learning_section(
                    contact=self.contact_email or "",
                    conversation_history=self.conversation_history,
                    user_email=self.user_email,
                    account_id=self.account_id,
                )
                if learned:
                    blocks.append(learned)
            except Exception:
                pass

        # 5. Contact summary (long-term per-contact).
        if self.account_id and self.contact_email:
            try:
                from app.services.contact_summary_service import get_summary_for_prompt
                from app.prompts.builders import format_contact_summary
                summary = get_summary_for_prompt(
                    account_id=self.account_id,
                    contact_email=self.contact_email,
                    user_email=self.user_email,
                )
                summary_block = format_contact_summary(summary)
                if summary_block:
                    blocks.append(summary_block)
            except Exception:
                pass

        return "\n\n".join(b for b in blocks if b)

    def _build_system_prompt(self, is_generation: bool = False) -> str:
        """Construit le prompt système pour le drafter."""
        # Audit 2026-05-04 — refine parity : append rich context blocks
        # when the caller provided account_id / conversation_history etc.
        # Empty string when no context is available — preserves prior
        # behaviour for the minimal caller pattern.
        context_blocks = self._build_context_blocks()
        context_section = f"\n\n{context_blocks}" if context_blocks else ""

        if is_generation:
            return f"""Tu es un assistant de rédaction d'emails.

CONTEXTE ET RÈGLES :
{self.knowledge_base}

INSTRUCTIONS :
- Rédige une réponse appropriée, professionnelle et complète à l'email fourni
- Adapte le ton au contexte (formel ou informel selon l'email reçu)

FORMAT DE SORTIE STRICT :
- Génère UNIQUEMENT le corps de l'email, sans objet ni signature
- NE MONTRE JAMAIS ton raisonnement, tes réflexions, tes hésitations ou tes explications
- Pas de méta-commentaire ("Je dois...", "Résolution", "Contradiction", "Note :")
- Le résultat doit être directement envoyable tel quel

INTERDIT — NE FAIS JAMAIS CECI :
- N'invente AUCUNE information (dates, lieux, heures, noms, raisons)
- Ne demande JAMAIS de clarification — rédige toujours une réponse complète
- Ne prends AUCUNE décision à la place de l'utilisateur (accepter, refuser, reporter){context_section}"""

        return f"""Tu es un assistant de rédaction d'emails.

CONTEXTE ET RÈGLES :
{self.knowledge_base}

INSTRUCTIONS :
- Applique UNIQUEMENT la modification demandée par l'utilisateur
- Garde le même sens, les mêmes informations, la même longueur approximative
- Adapte le ton si demandé
- Si l'utilisateur demande une traduction, traduis intégralement dans la langue cible

FORMAT DE SORTIE STRICT :
- Génère UNIQUEMENT le corps de l'email, sans objet ni signature
- NE MONTRE JAMAIS ton raisonnement, tes réflexions, tes hésitations ou tes explications
- Pas de méta-commentaire ("Je dois...", "Résolution", "Contradiction", "Note :")
- Le résultat doit être directement envoyable tel quel

INTERDIT — NE FAIS JAMAIS CECI :
- N'invente AUCUNE information (dates, lieux, heures, noms, raisons)
- Ne prends AUCUNE décision à la place de l'utilisateur (accepter, refuser, reporter)
- Ne propose PAS de créneaux, rendez-vous, alternatives ou suggestions
- N'ajoute PAS de contenu qui n'existe pas dans le brouillon original
- Ne rajoute PAS de phrases supplémentaires, de formules de politesse excessives
- Ne transforme PAS une phrase simple en paragraphe{context_section}"""

    def _build_refine_prompt(self, current_draft: str, instruction: str, email: Email = None) -> str:
        """Construit le prompt de refinement."""
        context = ""
        if email:
            context = f"""EMAIL ORIGINAL AUQUEL ON RÉPOND :
{email.content_for_processing}

"""
        # Empty draft → generation mode (no existing text to "apply" the instruction to)
        if not current_draft or not current_draft.strip():
            return f"""{context}INSTRUCTION : {instruction}

Il n'existe pas encore de brouillon. Génère une réponse complète, professionnelle et envoyable à cet email.
Ne montre pas ton raisonnement. Génère uniquement le corps de l'email, sans objet ni signature.

RÉPONSE :"""

        return f"""{context}BROUILLON ACTUEL :
{current_draft}

INSTRUCTION DE MODIFICATION : {instruction}

Applique l'instruction au brouillon. Ne rajoute RIEN qui n'est pas dans l'original. Même longueur approximative.

NOUVELLE VERSION :"""

    def _build_critique_system_prompt(self, instruction: str = "") -> str:
        """Construit le prompt système pour le critique."""
        return f"""Tu es un auditeur de réponses emails. Tu dois évaluer si une réponse est acceptable.

CONTEXTE ET RÈGLES À RESPECTER :
{self.knowledge_base}

INSTRUCTION DE L'UTILISATEUR : {instruction}

CRITÈRES D'ÉVALUATION :
1. Cohérence et clarté du message
2. Professionnalisme du ton
3. Pas d'informations inventées (hallucinations)
4. Respect des règles du contexte
5. Réponse complète

EXCEPTION IMPORTANTE :
- Si l'instruction de l'utilisateur demande explicitement une traduction ou un changement de langue, le changement de langue est AUTORISÉ et ne constitue PAS une violation des règles.
- Évalue uniquement si la traduction est correcte et le contenu fidèle.

RÉPONSE ATTENDUE :
- Si acceptable : "VALID"
- Si problème : "REJET : [raison précise et actionnable]"

Sois strict mais constructif."""

    def _build_critique_prompt(self, draft: Draft, email: Email = None) -> str:
        """Construit le prompt d'évaluation."""
        context = ""
        if email:
            context = f"""EMAIL ORIGINAL :
{email.content_for_processing}

"""
        return f"""{context}RÉPONSE PROPOSÉE :
{draft.content}

VERDICT :"""

    def _build_revision_prompt(
        self,
        draft_v1: Draft,
        critique: str,
        instruction: str,
        email: Email = None
    ) -> str:
        """Construit le prompt de correction."""
        context = ""
        if email:
            context = f"""EMAIL ORIGINAL :
{email.content_for_processing}

"""
        return f"""{context}Le brouillon suivant a reçu cette critique :

CRITIQUE : {critique}

BROUILLON V1 :
{draft_v1.content}

INSTRUCTION ORIGINALE : {instruction}

Rédige une nouvelle version qui corrige les problèmes mentionnés tout en respectant l'instruction originale.
IMPORTANT : Génère UNIQUEMENT le texte de l'email. Pas de raisonnement, pas d'explication, pas de méta-commentaire.

VERSION CORRIGÉE :"""
