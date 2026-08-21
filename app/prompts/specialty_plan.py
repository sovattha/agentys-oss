# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Prompts pour le flow 2-call spécialité : Sonnet plan → Haiku rédaction.

Utilisé par /api/refine-text quand use_specialty=true et qu'une spécialité
active match les notes de l'utilisateur.

Flow :
1. Sonnet (llm_drafting_smart) reçoit le contexte expert + les notes → produit
   un plan structuré en markdown (Points clés, Cadre légal, Ton, Garde-fous,
   Sources — utilisées pour audit, pas pour footnote).
2. Haiku (llm_drafting) reçoit ce plan + les notes → rédige l'email en PROSE
   FLUIDE en suivant le plan, en citant les articles INLINE dans la prose
   ("(arts. 1726-1733 CCQ)") — plus de footnote "--- Sources : ...".

La liste `applied_sources` extraite du plan reste exposée dans la réponse
HTTP (`specialty_info["applied_sources"]`) pour audit/observabilité (badge
debug frontend, eval harness), mais n'est plus collée en footnote du corps.
"""

import re


SOURCES_SECTION_RE = re.compile(
    r"##\s*Sources\s+à\s+citer[^\n]*\n(.*?)(?=\n##|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def build_specialty_plan_prompt(
    notes: str,
    subject: str,
    specialty_context: str,
    style_context: str,
    instruction: str,
    specialty_name: str,
) -> tuple[str, str]:
    """
    Construit le prompt Sonnet pour la phase PLAN.

    Returns:
        (system_prompt, user_prompt) — à passer à llm_drafting_smart.complete().

    Issue #457 (Phase 1) : `instruction` et `notes` sont des contenus
    user-controlled. On les enveloppe dans des balises de défense (sentinelle
    explicite + auto-échappement du tag fermant) — `instruction` est
    pré-sanitisé chevron-wise au point d'intake (`routes_drafts.refine_text`),
    `notes` reçoit uniquement l'échappement minimal du wrapper pour préserver
    son contenu littéral.
    """
    from app.prompts.builders import wrap_untrusted
    system = f"""Tu es un conseiller expert en rédaction professionnelle ({specialty_name}).

MISSION : produire un PLAN structuré que le rédacteur utilisera pour écrire l'email.
Tu ne rédiges PAS l'email. Tu rédiges uniquement le plan.

FORMAT DE SORTIE — EXACTEMENT ces 5 sections, dans cet ordre :

## Points clés
- [Chaque point que l'email doit couvrir, un par ligne, MAX 4]
- [Ordre d'importance — le plus pertinent au cas d'abord]

## Cadre légal applicable
- [MAX 3 articles/règles/formulaires — sélectionne uniquement les PLUS pertinents au cas]
- [Format : "(art. X CCQ) — comment ça s'applique CONCRÈTEMENT à la situation décrite dans les notes"]
- [PAS de définition générale du concept, MAIS son APPLICATION au cas particulier]
- [Article cité TEXTUELLEMENT depuis le contexte expert — JAMAIS inventer un numéro]
- [SI le contexte expert n'a pas de référence précise : "Principe général — <description>"]

## Ton et formalité
- [Directive de ton cohérente avec le style profile du destinataire]
- [Longueur cible : proportionnée au courriel entrant — court → 150-200 mots, complexe → 250-350 mots]

## Garde-fous obligatoires
- [Clauses de responsabilité à inclure, ex: "orienter vers un professionnel — AVEC UNE ACTION CONCRÈTE", pas un générique "consultez un avocat"]
- [Choses à NE PAS dire]

## Sources à citer en footnote
[Liste de références séparées par virgules, correspondant à la section Cadre légal.
Format exact : "CCQ art. 1726-1733, OACIQ Formulaire DS".
Si aucune source précise : "Principes généraux".]

RÈGLES ABSOLUES :
1. Ne cite QUE des articles/règles/formulaires présents TEXTUELLEMENT dans le contexte expert.
2. Ne rédige PAS le corps de l'email. Uniquement le plan.
3. Aucun préambule avant "## Points clés".
4. Aucune prose après la section Sources.
5. Sois concis — chaque section MAX 4 bullets, jamais plus.

DIRECTIVES IMPÉRATIVES POUR LE RÉDACTEUR (à transmettre via le plan) :
- L'email final doit être en PROSE FLUIDE, 3-4 paragraphes courts.
- AUCUN en-tête markdown (`##`, `###`) ni de gras (`**texte**`) dans la sortie.
- AUCUNE énumération exhaustive de critères ou définitions juridiques.
- Citations d'articles INLINE, en parenthèse dans la prose : "(arts. 1726-1733 CCQ)".
- AUCUNE footnote "--- Sources : ..." en fin d'email — les citations sont dans le corps.
- Ouvrir sur la situation de la personne, PAS sur le concept juridique.
- Personnaliser CHAQUE principe au cas (fondation, 6 mois, etc.) — jamais une définition générale.
- Terminer par une question ouverte si pertinent, pour relancer la conversation.

PHRASES À BANNIR (signal "réponse robot") :
- "De façon générale, ..."
- "Selon les circonstances, ..."
- "À titre informatif, ..."
- "Je vous propose un aperçu des principes..."
- "Pour votre situation spécifique..."
- "Quatre critères doivent être réunis : (1)... (2)... (3)... (4)..."
- "Sans me substituer à un avis juridique..."
- "Dans les plus brefs délais..." """

    style_block = style_context.strip() if style_context else "(aucun profil de style pour ce destinataire)"

    wrapped_instruction = wrap_untrusted(instruction, tag="user-instruction")
    wrapped_notes = wrap_untrusted(notes, tag="user-notes")

    user = f"""CONTEXTE EXPERT ({specialty_name}) :

{specialty_context}

===

PROFIL DE STYLE DU DESTINATAIRE :

{style_block}

===

INSTRUCTION UTILISATEUR :
{wrapped_instruction}

SUJET DE L'EMAIL : {subject or "(aucun sujet)"}

NOTES DE L'UTILISATEUR (à transformer en email) :
{wrapped_notes}

===

Produis maintenant le plan."""

    return system, user


def extract_sources_from_plan(plan_md: str) -> list[str]:
    """
    Extrait la liste des sources de la section "## Sources à citer en footnote" du plan.

    Returns:
        Liste de strings (max 10). Vide si section absente ou vide.
    """
    match = SOURCES_SECTION_RE.search(plan_md)
    if not match:
        return []

    raw = match.group(1).strip()
    if not raw:
        return []

    raw = re.sub(r"^\s*[-*•]\s*", "", raw, flags=re.MULTILINE)
    items = [s.strip() for s in re.split(r"[,\n]", raw) if s.strip()]
    items = [s for s in items if len(s) >= 3]
    return items[:10]


def build_draft_augmentation(plan_text: str, applied_sources: list[str]) -> str:
    """
    Construit le bloc à appender au system_prompt Haiku.

    Le plan sert de référence factuelle — citations d'articles, ton, garde-fous.
    Les sources sont citées INLINE dans la prose, en parenthèse — pas en footnote.
    """
    _ = applied_sources  # Tracked in specialty_info for audit, not rendered.
    return f"""

<PLAN>
{plan_text}
</PLAN>

DIRECTIVE — UTILISATION DU PLAN :
- Suis le plan ci-dessus pour écrire l'email.
- Cite les articles/formulaires EXACTEMENT comme ils apparaissent dans "Cadre légal applicable".
- Place les citations INLINE, en parenthèse dans la prose — ex: "(arts. 1726-1733 CCQ)".
- N'invente JAMAIS un numéro d'article qui n'est pas dans le plan.
- Respecte les garde-fous listés.
- N'ajoute AUCUNE footnote, AUCUN bloc "---", AUCUN en-tête markdown (##, **bold**) — la sortie est en PROSE FLUIDE de 3-4 paragraphes courts."""
