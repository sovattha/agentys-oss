# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Cache-prefix invariants for the structured Critic system prompt.

Audit 2026-05-04: prompt caching only fires when two requests share an
identical PREFIX. Until 2026-05-04 the Critic template injected
``{knowledge_base}`` at the top — which busts the prefix on every cross-
account call (each user has a different KB). This test pins the
restructured shape so any future edit that re-introduces variable content
ahead of the static rules trips the test before shipping.

These tests are deliberately structural — they don't measure real cache
hits (that needs Anthropic + ``[USAGE_STATS]`` log scraping in prod) but
they enforce the architectural property that makes hits possible.
"""

from __future__ import annotations

import pytest

from app.prompts.builders import get_critic_structured_system_prompt


# A length below which "static prefix" claims become trivial.
_MIN_STATIC_PREFIX_CHARS = 1500


@pytest.mark.parametrize(
    "kb_a, kb_b",
    [
        ("Account A KB content.", "Account B KB content."),
        ("", "Some KB"),
        ("## Profil\nAlice — startup", "## Profil\nBob — agency\n## Tone\nCasual"),
    ],
)
def test_critic_prompt_prefix_is_account_invariant(kb_a: str, kb_b: str):
    """Two prompts built with different KB content share an identical prefix.

    Without this property, the Anthropic ephemeral cache_control on the
    system block can NEVER hit across different accounts.
    """
    a = get_critic_structured_system_prompt(kb_a, contact="", account_id=None)
    b = get_critic_structured_system_prompt(kb_b, contact="", account_id=None)

    # Find the longest common prefix.
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    common_prefix = a[:i]

    assert len(common_prefix) >= _MIN_STATIC_PREFIX_CHARS, (
        f"static prefix too short ({len(common_prefix)} chars). "
        f"At least {_MIN_STATIC_PREFIX_CHARS} are needed for the rubric to "
        f"plausibly fill the model's cache eligibility threshold. "
        f"Did the template re-introduce variable content before the rules?"
    )

    # And the rules content must come BEFORE the KB block in the prefix.
    assert "FORMAT DE SORTIE STRICT" in common_prefix
    assert "Barème" in common_prefix
    assert "COHERENCE" in common_prefix and "INTELLIGENCE ÉMOTIONNELLE" in common_prefix


def test_critic_prompt_kb_is_at_the_end():
    """The KB block lives AFTER the rubric, not before it."""
    prompt = get_critic_structured_system_prompt(
        "MARKER_FOR_KB_POSITION_TEST", contact="", account_id=None,
    )
    kb_pos = prompt.find("MARKER_FOR_KB_POSITION_TEST")
    rubric_pos = prompt.find("INTELLIGENCE ÉMOTIONNELLE")
    assert kb_pos > rubric_pos > 0, (
        f"KB block must come after the rubric for cross-account cache reuse. "
        f"KB at char {kb_pos}, last rubric line at char {rubric_pos}."
    )


def test_critic_prompt_max_tokens_hint_matches_config():
    """The in-prompt 'Maximum N tokens' hint must equal MAX_TOKENS_CRITIC.

    Drift here means the model self-truncates while the SDK happily allowed
    more, or vice versa — both lead to wasted budget or silent malformed
    JSON. Keep them in lockstep.
    """
    from app.config import MAX_TOKENS_CRITIC

    prompt = get_critic_structured_system_prompt("", contact="", account_id=None)
    expected = f"Maximum {MAX_TOKENS_CRITIC} tokens"
    assert expected in prompt, (
        f"prompt must contain '{expected}' to match MAX_TOKENS_CRITIC={MAX_TOKENS_CRITIC}. "
        f"If you bumped the config, also bump the in-prompt hint in "
        f"`app/prompts/templates/critic_structured_system_prompt.txt`."
    )
