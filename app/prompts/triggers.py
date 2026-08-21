"""Triggers comportementaux injectables dans le draft (#198).

Research behavioral (Boomerang 2016, etc.) montre qu'un trigger bien placé
peut doubler le taux de réponse. Ce module encode 4 triggers éprouvés :

- ``URGENCY``       : deadline contextuelle RÉELLE (pas de fake "24h")
- ``CURIOSITY``     : information gap dans le subject — le destinataire veut savoir
- ``SOCIAL_PROOF``  : case study ou credential pertinent (vérifié)
- ``RECIPROCITY``   : offrir une valeur concrète avant de demander

Principes anti-abus :

1. **Opt-in explicite** : aucun trigger appliqué par défaut. L'utilisateur
   active dans ses settings, ou le système les active quand il a des données
   montrant un bénéfice pour ce destinataire (phase future).
2. **1 trigger max par draft** : éviter l'empilement manipulatoire.
3. **Guardrails par intent** : certains triggers sont bannis dans certains
   contextes (ex : pas d'urgence sur une OBJECTION — c'est agressif).
4. **Pas de fausse urgency** : le prompt interdit explicitement les urgences
   inventées. Si pas de vraie deadline, URGENCY est remplacé par NONE.
5. **Guardrails DISC (phase future)** : quand #190 arrivera, bannir URGENCY
   pour les destinataires S (Steadiness) qui le vivent comme agressif.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Set

from app.domain.entities.classification import IntentCategory


class TriggerKey(str, Enum):
    URGENCY = "URGENCY"
    CURIOSITY = "CURIOSITY"
    SOCIAL_PROOF = "SOCIAL_PROOF"
    RECIPROCITY = "RECIPROCITY"
    NONE = "NONE"


@dataclass(frozen=True)
class Trigger:
    key: TriggerKey
    name: str
    description: str
    snippet: str  # Injecté dans le system prompt.
    anti_abuse_clause: str = ""

    def to_prompt_block(self) -> str:
        if self.key == TriggerKey.NONE:
            return ""
        lines = [
            "<TRIGGER_COMPORTEMENTAL>",
            f"Trigger actif : {self.name}",
            self.snippet,
        ]
        if self.anti_abuse_clause:
            lines.append(f"IMPÉRATIF : {self.anti_abuse_clause}")
        lines.append("Applique UN SEUL trigger. Zéro empilement.")
        lines.append("</TRIGGER_COMPORTEMENTAL>")
        return "\n".join(lines)


_TRIGGERS: Dict[TriggerKey, Trigger] = {
    TriggerKey.URGENCY: Trigger(
        key=TriggerKey.URGENCY,
        name="Urgence contextuelle",
        description="Deadline ou fenêtre réelle qui justifie une action rapide.",
        snippet=(
            "Mentionne une deadline ou fenêtre temporelle RÉELLE extraite du "
            "contexte (date dans l'email, échéance projet, disponibilité connue). "
            "Formule la sobrement — pas de dramatisation."
        ),
        anti_abuse_clause=(
            "Si aucune deadline réelle n'existe dans le contexte, N'INVENTE PAS "
            "d'urgence. Retourne une réponse sans trigger."
        ),
    ),
    TriggerKey.CURIOSITY: Trigger(
        key=TriggerKey.CURIOSITY,
        name="Curiosité / Information gap",
        description="Créer un écart d'information que le destinataire veut combler.",
        snippet=(
            "Introduis un élément concret et intrigant (résultat chiffré, "
            "anecdote pertinente, finding inattendu) sans dévoiler la totalité. "
            "Le destinataire doit vouloir en savoir plus — pas un clickbait vide."
        ),
        anti_abuse_clause=(
            "Pas d'ambiguïté vague type 'j'ai quelque chose à te dire'. "
            "L'écart doit être précis et lié au sujet."
        ),
    ),
    TriggerKey.SOCIAL_PROOF: Trigger(
        key=TriggerKey.SOCIAL_PROOF,
        name="Preuve sociale",
        description="Case study, chiffre ou credential vérifiable.",
        snippet=(
            "Cite un exemple concret, un chiffre vérifiable ou une référence "
            "pertinente pour l'industrie/le contexte du destinataire. "
            "Une seule preuve, spécifique, sans superlatifs."
        ),
        anti_abuse_clause=(
            "N'invente aucun nom de client, chiffre ou citation. "
            "Si tu n'as pas de preuve vérifiée dans le contexte, retourne "
            "une réponse sans trigger."
        ),
    ),
    TriggerKey.RECIPROCITY: Trigger(
        key=TriggerKey.RECIPROCITY,
        name="Réciprocité",
        description="Offrir une valeur concrète avant de demander.",
        snippet=(
            "Offre quelque chose d'utile et immédiatement actionnable "
            "(analyse rapide, ressource ciblée, intro pertinente) AVANT "
            "toute demande ou CTA. La valeur doit être réelle et sans condition."
        ),
        anti_abuse_clause=(
            "La valeur offerte doit pouvoir exister — ne promets pas une ressource "
            "inventée. Préférer une observation réelle tirée du contexte."
        ),
    ),
    TriggerKey.NONE: Trigger(
        key=TriggerKey.NONE,
        name="Aucun",
        description="Pas de trigger.",
        snippet="",
    ),
}


# Mapping par défaut (conservateur) : uniquement des triggers sûrs pour l'intent.
_DEFAULT_MAPPING: Dict[IntentCategory, TriggerKey] = {
    IntentCategory.INQUIRY: TriggerKey.CURIOSITY,
    IntentCategory.NEGOTIATION: TriggerKey.RECIPROCITY,
    IntentCategory.FOLLOW_UP: TriggerKey.URGENCY,
    IntentCategory.OBJECTION: TriggerKey.SOCIAL_PROOF,
    IntentCategory.ESCALATION: TriggerKey.NONE,
    IntentCategory.INFORMATIONAL: TriggerKey.NONE,
    IntentCategory.OTHER: TriggerKey.NONE,
}

# Triggers BANNIS par intent (guardrails contre manipulation mal placée).
_BANNED_BY_INTENT: Dict[IntentCategory, Set[TriggerKey]] = {
    IntentCategory.OBJECTION: {TriggerKey.URGENCY},  # Empiler urgence sur objection = agressif.
    IntentCategory.ESCALATION: {
        TriggerKey.URGENCY,
        TriggerKey.CURIOSITY,
        TriggerKey.SOCIAL_PROOF,
        TriggerKey.RECIPROCITY,
    },
    IntentCategory.INFORMATIONAL: {TriggerKey.URGENCY, TriggerKey.CURIOSITY},
}


def select_trigger(
    intent: IntentCategory,
    *,
    enabled: bool = False,
    override: Optional[TriggerKey] = None,
) -> Trigger:
    """Retourne le trigger à appliquer pour un intent donné.

    Args:
        intent: Intent classifié de l'email entrant.
        enabled: Opt-in global utilisateur. Si False, retourne systématiquement NONE.
        override: Trigger forcé par l'utilisateur (soumis aux guardrails).

    Returns:
        Le trigger sélectionné, ou NONE si opt-out, banni, ou ESCALATION.
    """
    if not enabled:
        return _TRIGGERS[TriggerKey.NONE]

    candidate = override if override is not None else _DEFAULT_MAPPING.get(
        intent, TriggerKey.NONE
    )
    # Guardrail : si banni pour cet intent, retomber sur NONE (même avec override).
    banned = _BANNED_BY_INTENT.get(intent, set())
    if candidate in banned:
        return _TRIGGERS[TriggerKey.NONE]
    return _TRIGGERS[candidate]


def get_trigger(key: TriggerKey) -> Trigger:
    return _TRIGGERS[key]


def build_trigger_prompt_block(
    intent: IntentCategory,
    *,
    enabled: bool = False,
    override: Optional[TriggerKey] = None,
) -> str:
    """Shortcut : sélection + rendu du bloc prompt."""
    return select_trigger(intent, enabled=enabled, override=override).to_prompt_block()
