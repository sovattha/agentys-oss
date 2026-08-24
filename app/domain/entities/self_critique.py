# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SelfCritique entity — output of the SelfCritiqueAgent (Phase 1 of unified pipeline).

This entity is the typed contract between the Drafter and the escalation gate.
It carries the model's self-evaluation of its own draft, used downstream to
decide whether the external CriticAgent + V2 revision loop must run.

Design notes:
- frozen dataclass : the verdict is immutable once produced
- Closed risk vocabulary : the gate logic depends on a fixed set of categories;
  any unknown string returned by the LLM is filtered out at parse time
- create_failed() : when the LLM call or JSON parse fails, we return a forced-
  escalation verdict (self_score=0) instead of raising — keeps the pipeline
  fail-safe (degrade to current behaviour, never crash a draft generation)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# Closed vocabulary — adding a category requires updating both the prompt
# rubric (app/prompts/self_critique.py) AND the gate logic (Phase 3).
#
# Audit ultrathink 2026-05-03 : 3 catégories ajoutées pour fermer les gaps de
# couverture vs le Critic structuré + post-processing pipeline. Sans elles,
# le gate "no risks" validait des drafts avec langue erronée, signature double,
# ou longueur excessive — bugs visibles côté utilisateur que le Critic+pipeline
# captent aujourd'hui.
RISK_CATEGORIES: frozenset[str] = frozenset({
    "hallucination",      # Affirmation factuelle non sourcée
    "placeholder",        # [À confirmer], [TBD], [REDACTE], etc.
    "tone_mismatch",      # Tu/vous mix, registre incohérent
    "off_topic",          # Le draft ne répond pas à la question/contexte
    "filler",             # Formules creuses ("happy to help", "n'hésitez pas")
    # Ajouts 2026-05-03 :
    "language_drift",     # Brouillon en langue ≠ celle de l'email original
    "length_excessive",   # > 6 phrases pour une question simple, > 300 mots général
    "signature_doubled",  # Termine par "Cordialement," / prénom seul → double sig
})

RiskCategory = Literal[
    "hallucination",
    "placeholder",
    "tone_mismatch",
    "off_topic",
    "filler",
    "language_drift",
    "length_excessive",
    "signature_doubled",
]

Confidence = Literal["low", "med", "high"]


@dataclass(frozen=True)
class SelfCritique:
    """Verdict d'auto-évaluation produit par SelfCritiqueAgent.

    Champs :
        self_score : 0-100, plus haut = plus confiant que V1 est livrable
        risks : sous-ensemble immuable de RISK_CATEGORIES détecté dans le draft.
                Tuple (pas list) pour préserver l'invariant de vocabulaire fermé
                — un consumer ne peut pas .append() un risque hors-vocabulaire.
        a_confirmer_count : nombre de placeholders `[À confirmer]` ou similaires
        confidence : low/med/high — méta-évaluation par le modèle de sa propre
                     évaluation. "low" implique escalade systématique côté gate.
        failure_reason : non-vide uniquement quand l'évaluation LLM a échoué
                         (timeout, parse, erreur API). Sert au logging/sentinel.
    """
    self_score: int
    risks: tuple[RiskCategory, ...] = field(default_factory=tuple)
    a_confirmer_count: int = 0
    confidence: Confidence = "low"
    failure_reason: str = ""

    def to_pipeline_info(self) -> dict:
        """Sérialisation JSON-safe pour émission via WebSocket pipeline_info."""
        return {
            "self_score": int(self.self_score),
            "risks": list(self.risks),
            "a_confirmer_count": int(self.a_confirmer_count),
            "confidence": str(self.confidence),
            "failure_reason": self.failure_reason or "",
        }

    @classmethod
    def create_failed(cls, reason: str) -> "SelfCritique":
        """Verdict d'échec — force l'escalade côté gate. Ne jamais raise dans
        le pipeline d'évaluation : un échec d'auto-critique est traité comme
        un signal de risque (on ne sait pas, donc on demande au Critic externe).
        """
        return cls(
            self_score=0,
            risks=[],
            a_confirmer_count=0,
            confidence="low",
            failure_reason=reason or "unknown",
        )
