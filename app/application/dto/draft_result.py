"""DraftServiceResult — output du DraftService.generate().

Mutable car construit progressivement par le service :
1. Drafter produit le body initial → DraftServiceResult(body=..., version_index=1)
2. SelfCritiqueAgent produit le verdict → result.self_critique = ...
3. Si gate d'escalade trigger → result.escalated = True
4. Critic + V2 → result.critique = ...; result.body = V2; result.version_index = 2

Le suffixe `Service` distingue volontairement de `app.domain.entities.draft_generation.DraftResult`
qui est l'entité de domaine du Drafter individuel — éviter la confusion à la lecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.domain.entities.self_critique import SelfCritique


@dataclass
class DraftServiceResult:
    """Output unifié des paths reply et compose.

    Champs :
        body : le brouillon final (V1 si pas escaladé, V2 si revisionné)
        pipeline_info : dict émis via WebSocket (front consomme pour l'UI
                        AIDraftingPanel — score donut, risks chips, etc.)
        tier : tier final assigné par le routeur (SIMPLE/STANDARD/COMPLEX/...)
        cost_usd : coût LLM cumulé du flow (Drafter + SelfCritique + Critic + V2 si applicable)
        latency_ms : latence wall-clock du generate() complet
        escalated : True si le gate a déclenché Critic+V2 après SelfCritique
        self_critique : verdict d'auto-critique (Phase 1) — None si feature flag off
        critique : dict du verdict CriticAgent — None si pas escaladé
        version_index : 1 pour V1, 2 si V2 a été générée après escalade
    """
    body: str
    pipeline_info: dict[str, Any] = field(default_factory=dict)
    tier: Optional[str] = None
    cost_usd: float = 0.0
    latency_ms: int = 0
    escalated: bool = False
    self_critique: Optional[SelfCritique] = None
    critique: Optional[dict[str, Any]] = None
    version_index: int = 1
