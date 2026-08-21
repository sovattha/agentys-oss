# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-05 — Cross-thread few-shot fallback for the Drafter (2026-05-05).

Pre-fix: `extract_sent_examples` only reads `conversation_history`. New
contacts (no prior user reply in the thread) → the drafter sees zero
positive few-shot, only the BAD/GOOD anti-patterns in
drafter_system_prompt.txt. Quality regresses on cold-start replies.

Post-fix: `extract_cross_thread_examples(account_id)` returns 1–2
anonymized exemplars from `WritingStyleProfile.reference_examples` as a
fallback. Strict safety: only `anonymized=True` examples are surfaced;
any leak risk is dropped silently.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


def _make_example(text: str, *, anonymized: bool = True, bucket: str = "medium"):
    from app.domain.entities.writing_style import ReferenceExample
    return ReferenceExample(
        length_bucket=bucket,
        body_excerpt=text,
        subject="Sujet anonymisé",
        anonymized=anonymized,
        word_count=len(text.split()),
    )


def _make_profile(examples):
    from app.domain.entities.writing_style import WritingStyleProfile, FormalityLevel
    return WritingStyleProfile(
        account_id=1,
        analyzed_at=datetime.now(timezone.utc),
        email_count=10,
        formality_level=FormalityLevel.FORMAL,
        reference_examples=examples,
    )


def test_returns_empty_without_account_id():
    from app.prompts.helpers import extract_cross_thread_examples
    assert extract_cross_thread_examples(None) == ""
    assert extract_cross_thread_examples(0) == ""
    assert extract_cross_thread_examples(-1) == ""


def test_returns_empty_when_no_profile():
    from app.prompts.helpers import extract_cross_thread_examples
    container = MagicMock()
    container.get_writing_style_profile.return_value = None
    with patch("app.infrastructure.container.get_container", return_value=container):
        assert extract_cross_thread_examples(42) == ""


def test_drops_non_anonymized_examples():
    """Safety: a profile with only un-anonymized examples must produce ''.

    A regression here would leak real names/emails/amounts into prompt logs
    and Anthropic's pipeline. The filter is the only guard.
    """
    from app.prompts.helpers import extract_cross_thread_examples
    profile = _make_profile([_make_example("Hello [name]", anonymized=False)])
    container = MagicMock()
    container.get_writing_style_profile.return_value = profile
    with patch("app.infrastructure.container.get_container", return_value=container):
        assert extract_cross_thread_examples(42) == ""


def test_returns_block_for_anonymized_examples():
    from app.prompts.helpers import extract_cross_thread_examples
    profile = _make_profile([
        _make_example("Court message anonymisé.", bucket="short"),
        _make_example("Message moyen avec un peu plus de détails.", bucket="medium"),
    ])
    container = MagicMock()
    container.get_writing_style_profile.return_value = profile
    with patch("app.infrastructure.container.get_container", return_value=container):
        block = extract_cross_thread_examples(42)
    assert "<TES_RÉPONSES_PRÉCÉDENTES>" in block
    assert "</TES_RÉPONSES_PRÉCÉDENTES>" in block
    assert "Court message anonymisé." in block
    assert "Message moyen" in block


def test_fail_cheap_on_container_exception():
    """Any error in the lookup path → '' (never raise)."""
    from app.prompts.helpers import extract_cross_thread_examples
    with patch(
        "app.infrastructure.container.get_container",
        side_effect=RuntimeError("DB down"),
    ):
        assert extract_cross_thread_examples(42) == ""
