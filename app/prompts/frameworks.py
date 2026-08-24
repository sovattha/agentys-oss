# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Frameworks de copywriting sélectionnés selon l'intent entrant (#197).

Un email est un véhicule de persuasion. Une grammaire parfaite sans structure
psychologique échoue à convertir. Ce module fournit :

1. Une taxonomie de frameworks (AIDA, PAS, BAB, APP, 5Cs)
2. Un selector qui mappe :class:`IntentCategory` vers un framework par défaut
3. Des snippets de prompt courts, injectables dans le system prompt du Drafter

Les snippets sont volontairement condensés (2-6 lignes) pour ne pas exploser le
token budget du prompt. Le LLM reçoit la structure attendue et l'applique ;
si l'input ne s'y prête pas, il doit pouvoir dégrader gracieusement vers
une réponse directe plutôt que de forcer une structure artificielle.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

from app.domain.entities.classification import IntentCategory


class FrameworkKey(str, Enum):
    """Identifiant stable d'un framework. Sérialisable dans la DB."""
    AIDA = "AIDA"
    PAS = "PAS"
    BAB = "BAB"
    APP = "APP"
    FIVE_CS = "FIVE_CS"
    NONE = "NONE"  # Cas d'escalation : pas de framework, halt pipeline.


@dataclass(frozen=True)
class Framework:
    """Métadonnées + prompt snippet d'un framework de copywriting."""
    key: FrameworkKey
    name: str
    structure: str
    snippet: str  # Injecté dans le system prompt.

    def to_prompt_block(self) -> str:
        if self.key == FrameworkKey.NONE:
            return ""
        return (
            f"<FRAMEWORK_REPONSE>\n"
            f"Structure à appliquer : {self.name} — {self.structure}\n"
            f"{self.snippet}\n"
            f"Si l'email entrant ne se prête pas à cette structure, dégrade "
            f"gracieusement vers une réponse directe plutôt que de forcer "
            f"une articulation artificielle.\n"
            f"</FRAMEWORK_REPONSE>"
        )


_FRAMEWORKS: Dict[FrameworkKey, Framework] = {
    FrameworkKey.AIDA: Framework(
        key=FrameworkKey.AIDA,
        name="AIDA",
        structure="Attention → Interest → Desire → Action",
        snippet=(
            "1. Capte l'attention en 1 phrase (point saillant, pas de formule générique). "
            "2. Intéresse en reliant à un enjeu du destinataire. "
            "3. Crée le désir via un bénéfice concret et mesurable. "
            "4. Termine par une action unique et non-ambiguë."
        ),
    ),
    FrameworkKey.PAS: Framework(
        key=FrameworkKey.PAS,
        name="PAS",
        structure="Problem → Agitation → Solution",
        snippet=(
            "1. Reformule le problème ou la préoccupation avec précision (montre l'écoute). "
            "2. Reconnais brièvement l'impact (sans dramatiser). "
            "3. Propose la solution ou le repositionnement avec un bénéfice clair."
        ),
    ),
    FrameworkKey.BAB: Framework(
        key=FrameworkKey.BAB,
        name="BAB",
        structure="Before → After → Bridge",
        snippet=(
            "1. Rappelle brièvement l'état actuel ou la dernière interaction. "
            "2. Esquisse l'état visé ou le bénéfice attendu. "
            "3. Propose le pont concret (prochaine étape, ressource, décision)."
        ),
    ),
    FrameworkKey.APP: Framework(
        key=FrameworkKey.APP,
        name="APP",
        structure="Awareness → Problem → Positioning",
        snippet=(
            "1. Reconnais une croyance ou un contexte partagé. "
            "2. Introduis une nuance ou un problème moins visible. "
            "3. Positionne un angle distinctif sans vendre agressivement."
        ),
    ),
    FrameworkKey.FIVE_CS: Framework(
        key=FrameworkKey.FIVE_CS,
        name="5 Cs",
        structure="Clair, Concis, Convaincant, Crédible, orienté Client",
        snippet=(
            "Optimise chaque phrase selon les 5 C : Clair (zéro ambiguïté), "
            "Concis (pas de remplissage), Convaincant (bénéfice concret), "
            "Crédible (faits > superlatifs), orienté Client (ce qui compte pour lui)."
        ),
    ),
    FrameworkKey.NONE: Framework(
        key=FrameworkKey.NONE,
        name="Aucun",
        structure="Pas de framework",
        snippet="",
    ),
}


# Mapping par défaut intent → framework. Peut être override par utilisateur
# ou par signal de stade du cycle (cold / warm / active) dans une phase future.
_DEFAULT_MAPPING: Dict[IntentCategory, FrameworkKey] = {
    IntentCategory.INQUIRY: FrameworkKey.AIDA,
    IntentCategory.NEGOTIATION: FrameworkKey.PAS,
    IntentCategory.FOLLOW_UP: FrameworkKey.BAB,
    IntentCategory.OBJECTION: FrameworkKey.PAS,
    IntentCategory.ESCALATION: FrameworkKey.NONE,  # Halt pipeline.
    IntentCategory.INFORMATIONAL: FrameworkKey.FIVE_CS,
    IntentCategory.OTHER: FrameworkKey.FIVE_CS,
}


def select_framework(
    intent: IntentCategory,
    override: Optional[FrameworkKey] = None,
) -> Framework:
    """Retourne le framework à appliquer pour un intent donné.

    Args:
        intent: Intent classifié de l'email entrant.
        override: Si fourni, supplante le mapping par défaut (paramètre UI).
    """
    key = override if override is not None else _DEFAULT_MAPPING.get(intent, FrameworkKey.FIVE_CS)
    return _FRAMEWORKS[key]


def get_framework(key: FrameworkKey) -> Framework:
    """Lookup direct par clé (tests, composants admin)."""
    return _FRAMEWORKS[key]


def build_framework_prompt_block(
    intent: IntentCategory,
    override: Optional[FrameworkKey] = None,
) -> str:
    """Shortcut : sélection + rendu du bloc prompt."""
    return select_framework(intent, override).to_prompt_block()
