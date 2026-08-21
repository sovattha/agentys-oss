# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Adapter LLM synthétique pour les tests de charge locaux."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence

from app.domain.ports.llm_port import (
    LLMPort,
    LLMResponse,
    LLMStreamChunk,
    SystemPrompt,
    SystemSegment,
)


_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in _TRUE_VALUES


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _prompt_text(value: SystemPrompt) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return "\n".join(
            segment.text if isinstance(segment, SystemSegment) else str(segment)
            for segment in value
        )
    return str(value)


class MockLLMAdapter(LLMPort):
    """LLM déterministe utilisé quand ``AGENTYS_MOCK_LLM=true``.

    Le but est de charger l'API et le pipeline de draft sans appel réseau ni
    coût Anthropic. Les compteurs synthétiques peuvent être persistés avec
    ``AGENTYS_MOCK_LLM_RECORD_USAGE=true`` quand on veut tester l'attribution.
    """

    def __init__(self, *, model: str | None = None, tier: str = "default") -> None:
        self._tier = tier
        self._model = model or os.getenv("AGENTYS_MOCK_LLM_MODEL", f"mock-{tier}")
        self._latency_ms = max(0, _env_int("AGENTYS_MOCK_LLM_LATENCY_MS", 40))
        self._input_tokens = max(0, _env_int("AGENTYS_MOCK_LLM_INPUT_TOKENS", 900))
        self._output_tokens = max(0, _env_int("AGENTYS_MOCK_LLM_OUTPUT_TOKENS", 180))
        self._record_usage = _env_bool("AGENTYS_MOCK_LLM_RECORD_USAGE", False)

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        system: SystemPrompt,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> LLMResponse:
        if self._latency_ms:
            time.sleep(self._latency_ms / 1000)

        content = self._response_for(_prompt_text(system), user)
        output_tokens = min(self._output_tokens, max_tokens)
        usage_recorded = False
        if self._record_usage:
            try:
                from app.infrastructure.token_usage_writer import record_usage

                record_usage(
                    model=self.model,
                    input_tokens=self._input_tokens,
                    output_tokens=output_tokens,
                )
                usage_recorded = True
            except Exception:
                usage_recorded = False
        else:
            # Prevent synthetic load-test tokens from being persisted by callers
            # that also invoke agents._track_token_usage().
            usage_recorded = True

        return LLMResponse(
            content=content,
            input_tokens=self._input_tokens,
            output_tokens=output_tokens,
            model=self.model,
            stop_reason="end_turn",
            usage_recorded=usage_recorded,
        )

    def stream(
        self,
        system: SystemPrompt,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ):
        response = self.complete(
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        yield LLMStreamChunk(
            text=response.content,
            input_tokens=response.input_tokens,
            output_tokens_so_far=response.output_tokens,
            is_final=False,
            model=response.model,
            usage_recorded=response.usage_recorded,
        )
        yield LLMStreamChunk(
            text="",
            input_tokens=0,
            output_tokens_so_far=response.output_tokens,
            is_final=True,
            model=response.model,
            stop_reason=response.stop_reason,
            usage_recorded=response.usage_recorded,
        )

    def _response_for(self, system: str, user: str) -> str:
        override = os.getenv("AGENTYS_MOCK_LLM_OUTPUT")
        if override:
            return override

        prompt = f"{system}\n{user}".lower()

        if "faq_index" in prompt:
            return json.dumps(
                {"faq_index": 0, "confidence": 0.0, "response": ""},
                ensure_ascii=False,
            )

        if "suggestions" in prompt and "json" in prompt:
            return json.dumps(
                {
                    "suggestions": [
                        "Merci, je m'en occupe.",
                        "Je reviens vers vous rapidement.",
                    ]
                },
                ensure_ascii=False,
            )

        if self._looks_like_critic_prompt(prompt):
            return json.dumps(
                {
                    "coherence": 94,
                    "tone": 92,
                    "completeness": 91,
                    "errors": 96,
                    "conciseness": 90,
                    "over_commitment": 95,
                    "emotional_intelligence": 91,
                    "suggestions": [],
                    "explanation": "Évaluation synthétique pour test de charge.",
                },
                ensure_ascii=False,
            )

        if self._looks_like_label_prompt(prompt):
            return "0|Action|0.90|Classification synthétique"

        if self._looks_like_combined_draft_prompt(prompt):
            return json.dumps(
                {
                    "classification": "Action",
                    "classification_reason": "Email de test nécessitant une réponse.",
                    "label": "Action",
                    "priority": 70,
                    "draft": self._default_draft(),
                },
                ensure_ascii=False,
            )

        if "json" in prompt and "label" in prompt:
            return json.dumps(
                {"label": "Action", "draft": self._default_draft()},
                ensure_ascii=False,
            )

        return self._default_draft()

    @staticmethod
    def _looks_like_critic_prompt(prompt: str) -> bool:
        return all(
            key in prompt
            for key in (
                "coherence",
                "tone",
                "completeness",
                "over_commitment",
            )
        )

    @staticmethod
    def _looks_like_label_prompt(prompt: str) -> bool:
        return "output one line per email" in prompt or "pipe-separated" in prompt

    @staticmethod
    def _looks_like_combined_draft_prompt(prompt: str) -> bool:
        return (
            "classification" in prompt
            and "draft" in prompt
            and ("priority" in prompt or "label" in prompt)
        )

    @staticmethod
    def _default_draft() -> str:
        return "Je vérifie le délai prévu et je reviens vers vous dès que possible."
