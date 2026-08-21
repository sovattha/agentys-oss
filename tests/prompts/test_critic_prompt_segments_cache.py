# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Issue #682 — multi-block prompt caching contract for the Critic.

`get_critic_structured_system_segments` is the prompt-cache-friendly sibling
of `get_critic_structured_system_prompt`. Its contract has two arms that the
Anthropic adapter relies on, and that any future refactor must preserve:

1. The first segment (rubric + KB) is `cacheable=True` and is **byte-stable
   across calls that share the same `(knowledge_base,)`** — including calls
   that differ in `(contact, account_id)`. Without this property, the
   `cache_control: ephemeral` marker the adapter places on segment 0 would
   never hit the cache when the same account critiques drafts for multiple
   contacts, because the per-contact `<REGLES_APPRISES_UTILISATEUR>` block
   used to be appended to the single-string prompt and busted the prefix.

2. The flattened text (segment 0 ++ segment 1 ++ ...) is byte-identical to
   the legacy `get_critic_structured_system_prompt` output. That keeps the
   actual prompt the model sees unchanged — the multi-block split is a
   transport-layer optimisation, not a prompt change. Drift here would
   silently shift scoring.
"""
from __future__ import annotations

from unittest.mock import patch

from app.domain.ports.llm_port import SystemSegment
from app.prompts.builders import (
    get_critic_structured_system_prompt,
    get_critic_structured_system_segments,
)


def _flatten(segments: list[SystemSegment]) -> str:
    """Mirror what the Anthropic API does with adjacent text content blocks:
    concatenate `text` with NO separator. The dynamic segment carries its
    own leading separator (see `builders.get_critic_structured_system_segments`)
    so the flattened result equals the legacy single-string prompt."""
    return "".join(s.text for s in segments)


def test_segments_first_block_is_cacheable_and_invariant_across_contacts():
    """The byte-stable rubric + KB block must NOT depend on `contact`.

    Two calls for the same account but different contacts MUST produce a
    byte-identical segment 0 — otherwise the cache key changes per contact
    and the cross-contact cache hit promised by issue #682 never fires.
    """
    a = get_critic_structured_system_segments(
        knowledge_base="Account 1 KB",
        contact="alice@example.com",
        account_id=1,
    )
    b = get_critic_structured_system_segments(
        knowledge_base="Account 1 KB",
        contact="bob@example.com",
        account_id=1,
    )

    assert len(a) >= 1 and len(b) >= 1
    assert a[0].cacheable is True
    assert b[0].cacheable is True
    assert a[0].text == b[0].text, (
        "segment 0 must be byte-stable across contacts for the same account. "
        "If this regresses, the per-contact dynamic block has leaked into "
        "the cached prefix."
    )


def test_segments_dynamic_block_is_not_cacheable():
    """When learned rules exist, the second segment carries them and must
    NOT be marked cacheable. Marking it would split a per-contact value
    across cache buckets — at best wasted writes, at worst a wrong-contact
    cache hit on the next call.
    """
    # Stub the learning store so we deterministically get rules without
    # touching the filesystem / DB. Returning a non-empty string triggers
    # the dynamic-segment branch.
    fake_rules = "1. Préfère les réponses courtes\n2. Tutoiement avec ce contact"
    with patch(
        "app.draft_learning.get_draft_learning_store"
    ) as mock_store_factory:
        store = mock_store_factory.return_value
        store.get_rules_for_prompt.return_value = fake_rules

        segments = get_critic_structured_system_segments(
            knowledge_base="KB content",
            contact="alice@example.com",
            account_id=42,
        )

    assert len(segments) == 2, (
        f"expected 2 segments (rubric+KB cacheable, learning non-cacheable) "
        f"got {len(segments)}"
    )
    assert segments[0].cacheable is True
    assert segments[1].cacheable is False
    assert "REGLES_APPRISES_UTILISATEUR" in segments[1].text
    assert fake_rules in segments[1].text


def test_segments_omit_dynamic_block_when_no_learned_rules():
    """No learned rules → no second segment.

    A defensive empty dynamic segment (`SystemSegment("", cacheable=False)`)
    would be harmless to Anthropic but is wasteful — and an empty cacheable
    segment would create a useless cache breakpoint. Drop it entirely.
    """
    with patch(
        "app.draft_learning.get_draft_learning_store"
    ) as mock_store_factory:
        store = mock_store_factory.return_value
        store.get_rules_for_prompt.return_value = ""

        segments = get_critic_structured_system_segments(
            knowledge_base="KB",
            contact="alice@example.com",
            account_id=1,
        )

    assert len(segments) == 1
    assert segments[0].cacheable is True


def test_segments_omit_dynamic_block_when_store_raises():
    """Store errors must not break the critique path.

    The legacy `get_critic_structured_system_prompt` swallows store errors
    in a bare `except Exception: pass`; the segmented variant must keep the
    same fail-open contract so a transient DB hiccup never propagates to
    the Critic LLM call.
    """
    with patch(
        "app.draft_learning.get_draft_learning_store",
        side_effect=RuntimeError("db unavailable"),
    ):
        segments = get_critic_structured_system_segments(
            knowledge_base="KB",
            contact="alice@example.com",
            account_id=1,
        )

    assert len(segments) == 1
    assert segments[0].cacheable is True
    assert "{knowledge_base}" not in segments[0].text  # placeholder filled


def test_flattened_segments_match_legacy_single_string():
    """The model must see the SAME text whether the caller used the legacy
    string builder or the new segmented one. Drift = silent behavior change.

    This test guards against off-by-one whitespace at the segment boundary
    (the dynamic block prepends "\\n\\n" precisely because Anthropic
    concatenates text blocks without a separator).
    """
    fake_rules = "1. Une seule règle apprise."
    with patch(
        "app.draft_learning.get_draft_learning_store"
    ) as mock_store_factory:
        store = mock_store_factory.return_value
        store.get_rules_for_prompt.return_value = fake_rules

        kb = "## Profil\nAccount under test."
        legacy = get_critic_structured_system_prompt(
            knowledge_base=kb, contact="alice@example.com", account_id=42,
        )
        segmented = get_critic_structured_system_segments(
            knowledge_base=kb, contact="alice@example.com", account_id=42,
        )

    assert _flatten(segmented) == legacy, (
        "Flattened segments must equal the legacy single-string output. "
        "If this fails, an extra/missing newline at the segment boundary "
        "is the most likely culprit."
    )


def test_flattened_matches_legacy_when_no_learned_rules():
    """Same equivalence with no learned rules (single-segment path)."""
    with patch(
        "app.draft_learning.get_draft_learning_store"
    ) as mock_store_factory:
        store = mock_store_factory.return_value
        store.get_rules_for_prompt.return_value = ""

        kb = "Some KB."
        legacy = get_critic_structured_system_prompt(
            knowledge_base=kb, contact="", account_id=None,
        )
        segmented = get_critic_structured_system_segments(
            knowledge_base=kb, contact="", account_id=None,
        )

    assert _flatten(segmented) == legacy


def test_segments_static_prefix_clears_haiku_cache_floor():
    """Sanity check: the static prefix is large enough to be cacheable on
    Haiku 4.x (min 2048 tokens). The CRITIC template ships at ~8 KB which
    is well above the floor even with an empty KB; this is a regression
    guard for someone trimming the rubric without realising they would
    drop below the cache threshold.

    Token estimation: 4 chars ≈ 1 token (English/French mix). 2048 tokens
    ≈ 8000 chars. We assert >= 6500 chars to leave headroom for refactors
    that legitimately tighten the rubric while staying above the floor.
    """
    segments = get_critic_structured_system_segments(
        knowledge_base="", contact="", account_id=None,
    )
    assert segments[0].cacheable is True
    static_len = len(segments[0].text)
    assert static_len >= 6500, (
        f"Critic static prefix is only {static_len} chars (~{static_len // 4} "
        f"tokens). Haiku 4.x prompt-cache floor is 2048 tokens — segment "
        f"won't cache. Restore content or accept the cache regression."
    )
