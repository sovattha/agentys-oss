# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port SecondBrain — façade unifiée de la mémoire projet (issue #261).

Aujourd'hui, la connaissance Agentys est fragmentée sur 4 stores :
  1. knowledge/memoire.md      (fichier markdown global, legacy)
  2. DB SQLite par compte      (load_knowledge_from_db(account_id))
  3. MemPalace vectoriel       (ai_team/memory/palace/chroma.sqlite3)
  4. Graphe MCP memory         (19 entités + 21 relations bootstrappées)

Ce port expose une API unique pour que les agents aillent chercher leur
contexte en première intention dans un `SecondBrain` plutôt qu'en chargeant
leur propre knowledge_base. Il ne remplace pas encore les 4 sources — il les
agrège derrière une façade.

Pattern : retrieval local (zéro appel LLM), le coût est en amont du prompt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional


MemoryScope = Literal["agentys", "ai_team", "account"]
"""Scope d'isolation d'une mémoire.

- `agentys`  : projet global (roadmap, décisions, patterns cross-account)
- `ai_team`  : équipe IA autonome (rooms muse/bugs/veille…)
- `account`  : spécifique à un compte utilisateur (KB par compte)
"""


@dataclass(frozen=True)
class MemoryEntry:
    """Unité de mémoire retournée par le SecondBrain.

    Peut provenir de n'importe quelle source (vector hit, node du graphe,
    section markdown). Le champ `source` indique l'origine pour debug /
    scoring downstream.
    """
    content: str
    source: str                     # "mempalace" | "graph" | "memoire_md" | "account_db" | "fallback"
    score: float = 0.0              # 0-1, plus haut = plus pertinent
    scope: MemoryScope = "agentys"
    entity_name: Optional[str] = None  # si issu du graphe, nom de l'entité
    metadata: dict = field(default_factory=dict)

    def to_prompt_line(self) -> str:
        """Rendu compact pour injection dans un prompt système."""
        header = f"[{self.source}"
        if self.entity_name:
            header += f":{self.entity_name}"
        if self.score:
            header += f" score={self.score:.2f}"
        header += "]"
        return f"{header} {self.content.strip()[:800]}"


@dataclass(frozen=True)
class RetrievedContext:
    """Ensemble de `MemoryEntry` retourné pour une requête `retrieve()`."""
    entries: tuple[MemoryEntry, ...]
    query: str
    total_sources_queried: int = 0
    fallback_used: bool = False     # True si on est tombé sur memoire.md par défaut

    def to_prompt_block(self, *, max_chars: int = 4000) -> str:
        """Rendu texte complet (header + bullets) pour prompt injection."""
        if not self.entries:
            return ""
        lines = [f"## Mémoire projet pertinente pour: {self.query}"]
        used = 0
        for entry in self.entries:
            line = f"- {entry.to_prompt_line()}"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

    def is_empty(self) -> bool:
        return len(self.entries) == 0


@dataclass(frozen=True)
class Entity:
    """Nœud du graphe (projet, composant, personne, décision)."""
    name: str
    entity_type: str                 # "Project" | "Component" | "Decision" | ...
    observations: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()  # ex: ("uses:MemPalace", "deployed_to:Railway")


class SecondBrainPort(ABC):
    """Façade de la mémoire projet.

    Les agents génériques (cf. issue #261) doivent en première intention
    appeler `retrieve(role, task)` pour récupérer leur contexte. Ils ne
    chargent plus `knowledge/memoire.md` ni leurs `.txt` de prompts
    directement.

    Toutes les méthodes doivent être **non-bloquantes et idempotentes** :
    aucune n'a le droit de muter le second brain (les writers restent
    `nightly-memory-ingest.sh` et les outils MCP côté humain).
    """

    @abstractmethod
    def retrieve(
        self,
        *,
        role: str,
        task: str,
        k: int = 5,
        scope: Optional[MemoryScope] = None,
        account_id: Optional[int] = None,
    ) -> RetrievedContext:
        """Retourne les `k` meilleures mémoires pertinentes.

        Args:
            role: le rôle de l'agent appelant (`drafter`, `muse`, `espion`…).
                  Sert à booster les entries taggées pour ce rôle.
            task: une description courte de la tâche actuelle (sert de query
                  vectorielle). Exemple : "daily muse brainstorm".
            k: nombre max d'entries retournées.
            scope: si défini, limite la recherche (utile pour `account`).
            account_id: requis si scope="account".
        """

    @abstractmethod
    def get_role_prompt(self, role: str, *, default: Optional[str] = None) -> str:
        """Retourne le system prompt stocké pour ce rôle.

        Permet de sortir les prompts hardcodés des fichiers Python. Fallback
        sur `default` si le rôle n'est pas enregistré dans la mémoire.
        """

    @abstractmethod
    def get_entity(self, name: str) -> Optional[Entity]:
        """Retourne l'entité nommée depuis le graphe, ou None."""

    @abstractmethod
    def health_check(self) -> dict:
        """Retourne un dict décrivant l'état de chaque source.

        Format suggéré::

            {
              "sources_up": ["memoire_md", "account_db"],
              "sources_down": ["mempalace", "graph"],
              "healthy": True,
            }

        `healthy` est `True` si au moins 1 source est up (on fallback toujours
        sur memoire.md en dernier recours).
        """
