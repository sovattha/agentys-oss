# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DraftService — squelette du pipeline draft unifié (Phase 2a).

Cette classe livre le contrat (signature de `generate(ctx, mode)`) qui sera
implémenté en Phase 2b (compose) puis 2c (reply). En 2a, generate() lève
NotImplementedError volontairement — l'objectif de 2a est uniquement de
verrouiller la forme du service pour que les futures branches d'implémentation
n'aient pas à débattre de l'API.

Architecture (à venir en 2b/2c) :
    1. ctx + mode → choix du prompt drafter approprié
    2. Drafter → body V1 (streaming si mode='reply' avec compose_id)
    3. SelfCritiqueAgent.evaluate(body, ctx) → SelfCritique
    4. _should_escalate(self_critique, tier) → bool (gate d'escalade Phase 3)
    5. Si escalade : CriticAgent → si REJECT, Drafter.revise → body V2
    6. Build DraftServiceResult (body, pipeline_info, escalated, version_index, …)

Dépendances : injectées via __init__ (factories optionnelles). En production,
les endpoints API résolvent ces factories depuis le Container et les passent
au service. Cela garde l'application layer indépendante de l'infrastructure
(règle Clean Architecture documentée dans `app/application/__init__.py`).
"""

from __future__ import annotations

from typing import Callable, Literal, Optional

from app.application.dto.draft_context import DraftContext
from app.application.dto.draft_result import DraftServiceResult
from app.utils.draft_cleanup import strip_terminal_parenthetical_note


Mode = Literal["reply", "compose"]


class DraftService:
    """Orchestre le pipeline Drafter → SelfCritique → (Critic+V2 si escalade).

    Phase 2a (cette version) : skeleton uniquement. `generate()` lève
    NotImplementedError pour signaler aux callers (Phase 2b/2c) que la
    logique métier n'est pas branchée.
    """

    def __init__(
        self,
        drafter_factory: Optional[Callable[..., object]] = None,
        self_critique_factory: Optional[Callable[..., object]] = None,
        critic_factory: Optional[Callable[..., object]] = None,
    ) -> None:
        """Stocke les factories injectées. None → résolus par 2b/2c via Container."""
        self._drafter_factory = drafter_factory
        self._self_critique_factory = self_critique_factory
        self._critic_factory = critic_factory

    def generate(self, ctx: DraftContext, mode: Mode) -> DraftServiceResult:
        """Génère un brouillon unifié reply/compose.

        Args:
            ctx : DraftContext normalisé
            mode : 'reply' ou 'compose'

        Returns:
            DraftServiceResult avec body, pipeline_info, self_critique (compose),
            critique + escalated (reply uniquement, Phase 2c).

        Raises:
            ValueError : mode invalide (validation immédiate, programmer error)
            NotImplementedError : mode='reply' (implémentation Phase 2c)
        """
        # Validate mode early — invalid mode is a programmer bug, must crash
        # avec un message clair, pas un NotImplementedError trompeur (qui
        # suggérerait que 'banana' sera supporté un jour).
        if mode not in ("reply", "compose"):
            raise ValueError(
                f"Unknown mode: {mode!r} (expected 'reply' or 'compose')"
            )

        if mode == "compose":
            return self._generate_compose(ctx)

        # mode == "reply"
        raise NotImplementedError(
            "DraftService.generate(mode='reply') is a Phase 2a skeleton. "
            "Phase 2c implements reply mode (routes_drafts.py:generate_draft migration)."
        )

    # ------------------------------------------------------------------
    # Compose path (Phase 2b)
    # ------------------------------------------------------------------

    def _generate_compose(self, ctx: DraftContext) -> DraftServiceResult:
        """Pipeline compose : Drafter (Haiku, streaming si compose_id)
        → SelfCritique shadow (10% sampled) → regen si critique trigger
        → DraftServiceResult.

        Critic+V2 jamais invoqué en compose (décision verrouillée Phase 2b).
        Audit 2026-05-04 (P2.8) : regen 1× si self-critique sampled détecte
        score<60 + risques actionnables. Streaming bypass le regen (UX impact
        — on ne peut pas re-streamer après avoir déjà émis du contenu).
        """
        import time
        from app.application.services._compose_path import (
            build_compose_system_prompt,
            build_compose_user_prompt,
            build_regen_user_prompt,
            resolve_contact_profiles,
            resolve_per_contact_overrides,
            resolve_style_context,
            run_drafter_blocking,
            run_drafter_streaming,
            run_self_critique_shadow,
            should_regen_from_critique,
        )

        t0 = time.time()

        # 1. Per-contact overrides (nickname, greeting, formality, signature, closing)
        mandatory_opening, tone_directive, _signature, mandatory_closing = (
            resolve_per_contact_overrides(ctx)
        )

        # Multi-recipient greeting wins over per-contact single-name opening.
        # A nickname greeting ("Salut kiki,") addressing one person out of two
        # is exclusionary — replace it with the group greeting before the prompts
        # are built (both system_prompt and user_prompt use mandatory_opening).
        # Issue #592: contact_profiles is checked so that 2 recipients with
        # mixed/unknown registers fall back to a register-neutral group
        # greeting rather than "Bonjour Alice et Bob," which forces a tone
        # on the contact whose signal is unknown.
        from app.application.services._compose_path import _multi_recipient_greeting_hint
        _cp = resolve_contact_profiles(ctx)
        _multi_greeting = _multi_recipient_greeting_hint(
            ctx.recipient_email, ctx.language, _cp,
        )
        if _multi_greeting:
            mandatory_opening = _multi_greeting

        # 2. Style context (WritingStyleProfile + ContactStyleProfile dispatched)
        style_context = resolve_style_context(ctx)

        # 3. Build prompts
        system_prompt = build_compose_system_prompt(
            style_context=style_context,
            knowledge_base=ctx.knowledge_base or "",
            mandatory_opening=mandatory_opening,
            tone_directive=tone_directive,
            mandatory_closing=mandatory_closing,
        )
        user_prompt = build_compose_user_prompt(ctx, mandatory_opening, mandatory_closing)

        # 4. Resolve Drafter LLM (factory or fallback Container)
        drafter_llm = self._resolve_drafter_llm()

        # 5. Generate draft (streaming or blocking based on compose_id presence)
        if ctx.compose_id:
            body, usage = run_drafter_streaming(drafter_llm, system_prompt, user_prompt)
        else:
            body, usage = run_drafter_blocking(drafter_llm, system_prompt, user_prompt)

        # Issue #592: collapse stacked contextual + canonical closings
        # ("À ce vendredi !\n\nÀ bientôt," → "À bientôt,"). Cheap regex
        # pass, runs before the optional regen so the critique never sees
        # the doublon either.
        try:
            from app.smart_routing import _strip_stacked_contextual_closing
            body = _strip_stacked_contextual_closing(body)
        except Exception:
            pass
        body = strip_terminal_parenthetical_note(body)

        # 6. Self-Critique shadow (sampled 10% by default — cf. _compose_path.py)
        self_critique_agent = self._resolve_self_critique_agent()
        self_critique = run_self_critique_shadow(self_critique_agent, body, ctx)

        # 7. P2.8 — Regen trigger. Single retry, blocking-only path.
        # On streaming, the user has already seen partial content; re-emitting
        # would create a confusing flicker. Defer streaming-regen to a future
        # iteration that can stream into a hidden buffer until validated.
        version_index = 1
        regenerated = False
        if not ctx.compose_id and should_regen_from_critique(self_critique):
            regen_prompt = build_regen_user_prompt(
                user_prompt, self_critique, mandatory_opening, mandatory_closing
            )
            try:
                body, usage = run_drafter_blocking(
                    drafter_llm, system_prompt, regen_prompt
                )
                # Issue #592: also clean the regenerated body so a doublon
                # introduced on the second pass doesn't slip through.
                try:
                    from app.smart_routing import _strip_stacked_contextual_closing
                    body = _strip_stacked_contextual_closing(body)
                except Exception:
                    pass
                body = strip_terminal_parenthetical_note(body)
                version_index = 2
                regenerated = True
            except Exception as e:
                # Regen is best-effort — if the LLM fails, keep V1 body.
                # A failed regen must not break the compose flow.
                import logging
                logging.getLogger(__name__).warning(
                    f"compose regen failed (keeping V1): {e}"
                )

        # 8. Build pipeline_info
        pipeline_info: dict = {
            "tier": "compose",
            "mode": "compose",
            "model": usage.get("model", ""),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "regenerated": regenerated,
            "version_index": version_index,
        }
        if self_critique is not None:
            pipeline_info["self_critique"] = self_critique.to_pipeline_info()

        latency_ms = int((time.time() - t0) * 1000)

        return DraftServiceResult(
            body=body,
            pipeline_info=pipeline_info,
            tier="compose",
            cost_usd=0.0,  # actual cost computed by token tracker, not here
            latency_ms=latency_ms,
            escalated=False,  # compose never escalates (locked decision)
            self_critique=self_critique,
            critique=None,  # no external Critic in compose
            version_index=version_index,
        )

    # ------------------------------------------------------------------
    # Factory resolution helpers
    # ------------------------------------------------------------------

    def _resolve_drafter_llm(self):
        """Resolve Drafter LLM : injected factory or Container.llm_drafting fallback."""
        if self._drafter_factory is not None:
            return self._drafter_factory()
        from app.infrastructure.container import get_container
        return get_container().llm_drafting

    def _resolve_self_critique_agent(self):
        """Resolve SelfCritiqueAgent : injected factory or default instance."""
        if self._self_critique_factory is not None:
            return self._self_critique_factory()
        from app.self_critique_agent import SelfCritiqueAgent
        return SelfCritiqueAgent()
