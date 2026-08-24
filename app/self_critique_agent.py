# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SelfCritiqueAgent — agent isolé qui évalue la qualité d'un brouillon (Phase 1).

Phase 1 livre cet agent en standalone : il n'est PAS encore branché dans le
pipeline reply/compose. Le branchement (gate d'escalade) arrive en Phase 3.
Cette isolation permet de mesurer/calibrer le seuil `self_score` sur logs
réels avant de toucher au routing existant.

Architecture mirroir CriticAgent (`app/agents.py:976`) :
- @dataclass + _llm field injecté via Container.llm_label (Haiku)
- Méthode `evaluate(draft, context, mode) -> SelfCritique`
- Propage `LLMRateLimitError` (gestion retry au niveau supérieur)
- Catch `Exception` générique → SelfCritique.create_failed (force escalade)
- _track_token_usage après chaque appel LLM réussi
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.domain.entities.self_critique import (
    RISK_CATEGORIES,
    Confidence,
    SelfCritique,
)
from app.domain.exceptions import LLMError, LLMRateLimitError
from app.domain.ports import LLMPort
from app.prompts.self_critique import (
    Mode,
    get_self_critique_system_prompt,
    get_self_critique_user_prompt,
)
from app.utils.json_parser import extract_json_from_response

_logger = logging.getLogger(__name__)


# Self-critique returns a short JSON. Empirically a draft with 4-5 risks
# + complete fields fits in ~120 tokens; we leave 200 to absorb verbose
# models without truncating valid output (review R2). Cost increment negligible
# (~$0.0001 per call at Haiku rates).
_MAX_TOKENS_SELF_CRITIQUE = 200
_VALID_CONFIDENCES: frozenset[str] = frozenset({"low", "med", "high"})


@dataclass
class SelfCritiqueAgent:
    """Agent d'auto-critique sur un brouillon généré par le Drafter.

    Le Container fournit `llm_label` (Haiku) — modèle peu coûteux, latence ~400ms,
    largement suffisant pour évaluer un brouillon court selon une rubrique fermée.
    """

    _llm: Optional[LLMPort] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._llm is None:
            # Lazy-bound to allow tests to inject a FakeLLM via __new__.
            from app.infrastructure.container import get_container
            self._llm = get_container().llm_label

    def evaluate(
        self,
        draft: str,
        context: str,
        mode: Mode = "reply",
    ) -> SelfCritique:
        """Évalue un brouillon, retourne un SelfCritique typé.

        Args:
            draft : Le brouillon à évaluer.
            context : L'email original (mode='reply') ou l'instruction (mode='compose').
            mode : 'reply' ou 'compose'. Tout autre valeur lève ValueError.

        Returns:
            SelfCritique avec self_score 0-100, risks, a_confirmer_count, confidence.
            En cas d'échec LLM/parse/IO, retourne SelfCritique.create_failed
            (self_score=0 → force escalade côté gate).

        Raises:
            ValueError : mode invalide (programmer error).
            LLMRateLimitError : propagée pour gestion retry par l'appelant.
            AttributeError/TypeError/KeyError : programmer errors — laissés remonter
            pour que les régressions soient visibles en CI/dev (review R3).
        """
        # Validate mode early — invalid mode is a programmer error, must crash
        if mode not in ("reply", "compose"):
            raise ValueError(f"Unknown mode: {mode!r} (expected 'reply' or 'compose')")

        # Empty draft : no point calling the LLM, escalate immediately
        if not draft or not draft.strip():
            _logger.debug("[SelfCritique] empty draft — fail-safe, no LLM call")
            return SelfCritique.create_failed(reason="empty_draft")

        try:
            response = self._llm.complete(  # type: ignore[union-attr]
                system=get_self_critique_system_prompt(),
                user=get_self_critique_user_prompt(draft, context, mode=mode),
                max_tokens=_MAX_TOKENS_SELF_CRITIQUE,
                temperature=0.0,
            )
            # Track usage for cost reporting (mirrors CriticAgent pattern).
            # Wrapped in best-effort try : telemetry failure must never break
            # the eval. Local import: app.agents pulls in ~20MB of agent stack;
            # we lazy-load to keep cold start of self_critique_agent fast for
            # callers that only need the entity.
            try:
                from app.agents import _track_token_usage
                _track_token_usage(response)
            except Exception:  # pragma: no cover — telemetry is non-critical
                pass

            return self._parse_response(response.content)

        except LLMRateLimitError:
            # Propagate — caller decides whether to retry/backoff
            _logger.warning("[SelfCritique] rate limit — propagating")
            raise

        except (LLMError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
            # Operational failures (LLM provider, network, malformed JSON) →
            # fail-safe to escalation. AttributeError/TypeError/KeyError are
            # programmer bugs and must crash loudly — they bypass this clause.
            _logger.error(f"[SelfCritique] operational failure: {e}", exc_info=True)
            return SelfCritique.create_failed(reason=str(e))

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str) -> SelfCritique:
        """Parse la réponse LLM en SelfCritique. Tolérant aux outputs partiels."""
        if not raw or not raw.strip():
            return SelfCritique.create_failed(reason="empty_llm_response")

        data = extract_json_from_response(raw) or {}
        if not isinstance(data, dict) or "self_score" not in data:
            # No score parsed → no signal we can trust → force escalade
            return SelfCritique.create_failed(reason="json_parse_failed")

        # Clamp score to [0, 100] — defends against LLM hallucinating 150 / -10
        try:
            score = int(data.get("self_score", 0))
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(100, score))

        # Filter risks against closed vocabulary (lesson : never trust LLM-output
        # vocabulary drift; gate logic depends on exact category strings).
        # Stored as tuple for immutability (review R7).
        raw_risks = data.get("risks") or []
        if not isinstance(raw_risks, list):
            raw_risks = []
        risks = tuple(r for r in raw_risks if isinstance(r, str) and r in RISK_CATEGORIES)

        # a_confirmer_count : non-negative int
        try:
            a_count = max(0, int(data.get("a_confirmer_count", 0)))
        except (TypeError, ValueError):
            a_count = 0

        # confidence : closed set, default to most pessimistic on drift
        conf_raw = data.get("confidence", "low")
        if not isinstance(conf_raw, str) or conf_raw.lower() not in _VALID_CONFIDENCES:
            confidence: Confidence = "low"
        else:
            confidence = conf_raw.lower()  # type: ignore[assignment]

        return SelfCritique(
            self_score=score,
            risks=risks,
            a_confirmer_count=a_count,
            confidence=confidence,
        )
