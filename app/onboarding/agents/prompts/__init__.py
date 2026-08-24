# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prompt loader for onboarding agents."""

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


_SUPPORTED_LANGS = ("fr", "en")
_AGENT_PROMPTS = ("profile", "knowledge", "style", "label")

# Shared partials (audit 2026-05-04 — tone inference dedup):
# Some rules duplicate across agents — for example the salutation→tone
# inference rule lives in BOTH style.txt and knowledge.txt because each
# agent gets its own system prompt and can't reference the other. To
# avoid maintaining 2 verbatim copies, we extract the shared text into
# `_tone_inference.txt` and substitute the `{{TONE_INFERENCE}}` marker
# at load time. Every agent prompt that needs the rule keeps the
# substitution token; the partial is the single source of truth.
_PARTIAL_MARKERS: dict[str, str] = {
    "{{TONE_INFERENCE}}": "_tone_inference",
}


@lru_cache(maxsize=16)
def _load_partial(name: str, lang: str = "fr") -> str:
    """Read a shared partial (e.g. ``_tone_inference``) from the prompts dir.

    Picks the language variant ``{name}_{lang}.txt`` when present, falls back
    to ``{name}.txt`` (treated as the FR canonical). Cached because the 4
    agents triggered in parallel will all hit the same partials at startup;
    we want a single read + a stable string.
    """
    if lang and lang != "fr":
        variant = _DIR / f"{name}_{lang}.txt"
        if variant.exists():
            return variant.read_text(encoding="utf-8").strip()
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


def _expand_partials(text: str, lang: str = "fr") -> str:
    """Substitute every `{{PARTIAL_MARKER}}` placeholder by its content.

    Markers that don't appear in the text are no-ops — the substitution
    is idempotent and order-independent. ``lang`` is forwarded so partials
    pick up their own language variant.
    """
    for marker, partial_name in _PARTIAL_MARKERS.items():
        if marker in text:
            text = text.replace(marker, _load_partial(partial_name, lang=lang))
    return text


@lru_cache(maxsize=32)
def load_prompt(name: str, lang: str = "fr") -> str:
    """Load a prompt file by name (without extension).

    When ``lang`` is provided (e.g. ``"en"``), the loader first looks for a
    language-specific variant ``{name}_{lang}.txt`` and falls back to the
    base ``{name}.txt`` if the variant does not exist. This lets us ship
    language-specific prompt tuning without duplicating logic for every
    supported locale.

    Shared partials (e.g. ``_tone_inference``) are spliced in via the
    ``{{MARKER}}`` substitution table — see ``_PARTIAL_MARKERS`` above.

    OB-03 (audit 2026-04-24): for unsupported languages (e.g. ``"es"``,
    ``"it"``, ``"unsupported"``), we fall back to the **English** prompt
    because feeding a French system prompt to a Spanish/Italian inbox is
    actively worse than English (Anthropic's Claude family handles
    multilingual instructions well in English). The orchestrator still
    flags the run as partial so the user knows training quality is
    degraded, but the agents won't crash.

    Results are cached because the 4 onboarding agents call this on every
    run and the prompt files never change at runtime — we care about both
    file-I/O cost and deterministic timing (the agents run in parallel
    threads sharing a single LLM mock in tests; predictable no-op reads
    keep the agent order stable).
    """
    effective_lang = lang
    if lang and lang not in _SUPPORTED_LANGS:
        # Unsupported language → English fallback (better than French).
        effective_lang = "en"
    if effective_lang and effective_lang != "fr":
        variant = _DIR / f"{name}_{effective_lang}.txt"
        if variant.exists():
            return _expand_partials(
                variant.read_text(encoding="utf-8").strip(), lang=effective_lang,
            )
    return _expand_partials(
        (_DIR / f"{name}.txt").read_text(encoding="utf-8").strip(),
        lang=effective_lang or "fr",
    )


def is_supported_language(lang: str) -> bool:
    """Return True iff a dedicated prompt variant exists for ``lang``.

    Used by the orchestrator to decide whether to flag the run as partial
    (with reason ``"unsupported_language"``) — we still run the analysis
    on a best-effort English prompt, but we tell the user the training
    will be lower quality until we add their language.
    """
    return bool(lang) and lang in _SUPPORTED_LANGS


# Eagerly warm the cache at import time so the 4 onboarding agents (which
# run in parallel threads) hit an in-memory dict on their first call rather
# than racing each other on file-I/O. Without this, small scheduling deltas
# can reorder the shared-mock `side_effect` consumption in tests.
for _n in _AGENT_PROMPTS:
    for _l in _SUPPORTED_LANGS:
        try:
            load_prompt(_n, lang=_l)
        except FileNotFoundError:
            pass
