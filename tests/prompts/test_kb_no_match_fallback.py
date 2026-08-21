# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for the KB no-match fallback in get_standard_draft_prompts.

Audit 2026-05-03 (Q4): when a non-empty knowledge_base is provided but no entry
matches the email body, _extract_knowledge_answer used to return "" and the
user prompt was built without any KB block — the LLM treated this as "no
constraints" and fabricated specifics (dates, prices, commitments).

The fix injects an explicit "NO MATCHING KB ENTRY" guidance block instead, so
the LLM is told outright not to invent. These tests pin the three branches:
no KB / KB with match / KB without match.
"""

from __future__ import annotations

from app.prompts.builders import get_standard_draft_prompts


# A KB entry that obviously does NOT match the email body below.
_KB_UNRELATED = """### What are your office hours?
Monday to Friday, 9am to 5pm UTC.

### Topic: Refund policy
Refunds are processed within 7 business days.
"""


# A KB entry that DOES match the email body below.
_KB_MATCHING = """### What is your shipping cost?
Shipping is free for orders over $50, otherwise $4.99 flat rate.
"""


def _user_prompt_for(body: str, knowledge_base: str = "") -> str:
    """Build the standard-tier user prompt and return it for substring assertions."""
    _, user_prompt = get_standard_draft_prompts(
        sender="alice@example.com",
        subject="Question",
        body=body,
        knowledge_base=knowledge_base,
    )
    return user_prompt


def test_no_kb_provided_emits_no_kb_section():
    """When knowledge_base is empty, neither block should appear."""
    user_prompt = _user_prompt_for("What is your shipping cost?", knowledge_base="")
    assert "NO MATCHING KNOWLEDGE BASE ENTRY" not in user_prompt
    assert "VERIFIED ANSWER FROM YOUR KNOWLEDGE BASE" not in user_prompt


def test_kb_with_matching_entry_emits_verified_answer_block():
    """When the email matches a KB entry, the existing VERIFIED ANSWER block wins.

    Pins the happy path so the no-match branch added by the audit fix can never
    accidentally hide a real KB answer. The email body deliberately reuses the
    KB heading verbatim — the underlying matcher is word-overlap with a 0.3
    threshold for Q&A entries, so we need ≥ ~3 shared words to clear it.
    """
    user_prompt = _user_prompt_for(
        "What is your shipping cost? Trying to plan my order.",
        knowledge_base=_KB_MATCHING,
    )
    assert "VERIFIED ANSWER FROM YOUR KNOWLEDGE BASE" in user_prompt
    assert "Shipping is free for orders over $50" in user_prompt
    # No-match block must not coexist with the verified block.
    assert "NO MATCHING KNOWLEDGE BASE ENTRY" not in user_prompt


def test_kb_without_matching_entry_emits_no_match_guidance():
    """When KB has entries but none matches, inject explicit no-invent guidance.

    This is the audit Q4 fix: the LLM must be told the KB has no answer, not
    left with an empty block (which it interpreted as license to fabricate).
    """
    user_prompt = _user_prompt_for(
        "What time does the moon rise tonight in Tokyo?",
        knowledge_base=_KB_UNRELATED,
    )
    assert "NO MATCHING KNOWLEDGE BASE ENTRY" in user_prompt
    assert "Do NOT invent specifics" in user_prompt
    # Verified block must NOT also fire when nothing matched.
    assert "VERIFIED ANSWER FROM YOUR KNOWLEDGE BASE" not in user_prompt
