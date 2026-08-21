# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-14 (P0.1) — prompt caching structure of the SmartRouter
STANDARD reply path.

Background
----------
Before P0.1, ``get_standard_draft_prompts`` returned a single ``str`` system
prompt where per-contact, per-thread and per-email content was concatenated
onto a short skeleton. The Anthropic adapter then wrapped the whole blob in
a single ``cache_control: ephemeral`` block. Two structural problems:

  1. The skeleton + global stub KB (≈100–500 tokens) sat below the Haiku
     prompt-cache floor (~1024 tokens). The cache marker was silently
     ignored. Production telemetry: 64/64 ``[USAGE_STATS]`` lines with
     ``cache_w=0 cache_r=0 cache_hit_rate=0.000``.
  2. Even when the prompt did cross the floor, the appended per-contact
     content made every call's system block byte-unique, so the prefix
     was never reused.

P0.1 restructures the system into ``list[SystemSegment]``:

  * segment[0] — ``cacheable=True`` — skeleton + KB + ``REPLY_QUALITY_GUARDRAILS``.
    Byte-stable for a given account.
  * segment[1] — ``cacheable=False`` — style_context + per-contact + per-thread
    + per-email blocks. Sent fresh; not part of the cached prefix.

These tests pin every invariant the fix relies on. If any of them fail, the
prompt cache silently goes back to 0% in production.
"""

from __future__ import annotations

import pytest

from app.domain.ports.llm_port import SystemSegment
from app.prompts.builders import get_standard_draft_prompts, _segments_to_text


# --- A KB chunk big enough to be substantive but small enough to keep tests
#     fast. Mirrors the shape of `build_knowledge_markdown` output (profile +
#     savoir + règles) without bringing in the onboarding DB layer. ---
_FIXTURE_KB = (
    "## Profil\n"
    "- **Nom complet**: Test User\n"
    "- **Entreprise**: ACME\n"
    "- **Titre**: Engineering Lead\n"
    "- **Ton par défaut**: Direct\n"
    "- **Langue**: Français\n\n"
    "## Savoir\n"
    "### What is the refund policy?\n"
    "Refunds within 14 days, no questions asked.\n\n"
    "### Quels sont les tarifs ?\n"
    "Starter à 29€/mois, Pro à 79€/mois, Enterprise sur devis.\n\n"
    "## Règles\n"
    "- Toujours signer avec le prénom.\n"
    "- Ne JAMAIS promettre une date sans la valider en amont.\n"
)


class TestReturnShape:
    """Contract: the builder returns (list[SystemSegment], str)."""

    def test_returns_segment_list_and_user_string(self):
        result = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="Hi",
            body="Quick question.",
            knowledge_base=_FIXTURE_KB,
            account_id=None,
        )
        assert isinstance(result, tuple) and len(result) == 2
        segments, user_prompt = result
        assert isinstance(segments, list), (
            "P0.1 requires the system to be a list[SystemSegment] so the "
            "Anthropic adapter can mark a stable cacheable prefix."
        )
        assert all(isinstance(s, SystemSegment) for s in segments)
        assert isinstance(user_prompt, str) and user_prompt, (
            "User prompt remains a plain string."
        )

    def test_at_least_one_segment(self):
        segments, _ = get_standard_draft_prompts(
            sender="x@y.com", subject="s", body="b", account_id=None,
        )
        assert len(segments) >= 1


class TestSegmentOneIsTheCacheablePrefix:
    """Contract: segment[0] is cacheable, stable per account, and sized to
    clear Haiku's ~1024-token prompt-cache floor.
    """

    def test_segment_one_is_marked_cacheable(self):
        segments, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="Hi", body="Question.",
            knowledge_base=_FIXTURE_KB,
            account_id=None,
        )
        assert segments[0].cacheable is True, (
            "segment[0] MUST be cacheable=True — that's what tells the "
            "adapter to emit `cache_control: ephemeral` on it. Without "
            "this marker the Anthropic API does not cache the prefix and "
            "P0.1's whole point is gone."
        )

    def test_segment_one_byte_stable_across_different_contacts(self):
        """The single byte-stability invariant. If this regresses, every
        reply pays full input cost and we go back to 0% cache hit rate.
        """
        seg_a, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="First subject",
            body="First body, longer content here for variety.",
            knowledge_base=_FIXTURE_KB,
            contact="alice@example.com",
            account_id=None,
        )
        seg_b, _ = get_standard_draft_prompts(
            sender="bob@somewhere.org",
            subject="Completely different subject",
            body="Totally different body talking about other things.",
            knowledge_base=_FIXTURE_KB,
            contact="bob@somewhere.org",
            account_id=None,
        )
        assert seg_a[0].text == seg_b[0].text, (
            "segment[0] must be byte-identical for two calls with the "
            "same account_id + KB. Anthropic's prompt cache is a PREFIX "
            "cache — any byte difference invalidates the cached block. "
            "If different sender/body/contact leak into segment[0], the "
            "cache will never hit."
        )

    def test_segment_one_byte_stable_with_or_without_dynamic_content(self):
        """style_context, history, contact summary etc. must NOT leak into
        segment[0]. They belong in segment[1] (or the user message).
        """
        seg_a, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="s", body="b",
            knowledge_base=_FIXTURE_KB,
            style_context="<some style hints for Alice>",
            conversation_history=[{
                "sender": "alice@example.com",
                "subject": "Older",
                "body": "Older message body content.",
            }],
            account_id=None,
        )
        seg_b, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="s", body="b",
            knowledge_base=_FIXTURE_KB,
            style_context="",
            conversation_history=None,
            account_id=None,
        )
        assert seg_a[0].text == seg_b[0].text, (
            "Whether style_context / conversation_history are passed must "
            "not change segment[0]. They are per-call content and belong "
            "in segment[1]."
        )

    def test_segment_one_includes_skeleton_and_guardrails(self):
        segments, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="s", body="b",
            knowledge_base=_FIXTURE_KB,
            account_id=None,
        )
        seg_text = segments[0].text
        # Skeleton marker (from standard_draft_system_prompt.txt)
        assert "MIRROR THE CONTACT" in seg_text or "Output ONLY the reply text" in seg_text, (
            "segment[0] must contain the STANDARD_DRAFT_SYSTEM_PROMPT skeleton."
        )
        # KB block
        assert "<CONTEXTE>" in seg_text and "Engineering Lead" in seg_text, (
            "segment[0] must contain the knowledge_base inside <CONTEXTE> tags."
        )
        # Guardrails marker (from reply_quality_guardrails.txt)
        assert "QUALITY GUARDRAILS" in seg_text, (
            "segment[0] must include the REPLY_QUALITY_GUARDRAILS block — "
            "that's what (a) lifts quality at the source by anti-slop "
            "calibration, and (b) makes segment[0] large enough to clear "
            "the Haiku prompt-cache floor."
        )

    @pytest.mark.xfail(
        reason=(
            "Haiku 4.5's real min cacheable prefix is 4096 tokens, NOT ~1024. "
            "segment[0] (skeleton+KB+guardrails) is ~1830-2440 tokens for a "
            "typical account, so it sits BELOW the floor and is NOT cached — a "
            "known no-op on the reply path (reply-latency audit 2026-06-23). "
            "Do NOT pad seg[0] to cross the floor (net-negative on the "
            "dominant single-draft case). Kept as xfail so it flips to XPASS "
            "if the cacheable prefix ever legitimately grows past 4096."
        ),
        strict=False,
    )
    def test_segment_one_size_clears_cache_floor(self):
        """Documents the gap, not a passing contract. Haiku 4.5's min
        cacheable prefix is 4096 tokens (approx at 3 chars/token). Today
        segment[0] is below that floor, so Anthropic does NOT write the cache
        on this path — this test is expected to fail until the prefix grows."""
        segments, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="s", body="b",
            knowledge_base=_FIXTURE_KB,
            account_id=None,
        )
        seg_chars = len(segments[0].text)
        approx_tokens = seg_chars / 3.0  # conservative ratio
        assert approx_tokens >= 4096, (
            f"segment[0] approximates {approx_tokens:.0f} tokens "
            f"({seg_chars} chars) — Haiku 4.5 needs >=4096 to actually "
            f"prompt-cache. Below the floor the cacheable prefix is a no-op."
        )


class TestSegmentTwoCarriesDynamicContent:
    """Contract: per-call content lands in segment[1] (or is empty)."""

    def test_style_context_lands_in_segment_two_not_one(self):
        unique = "Bisous-Bisous-12345 SURNOM Hokey Pokey"
        segments, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="s", body="b",
            knowledge_base=_FIXTURE_KB,
            style_context=unique,
            account_id=None,
        )
        assert unique not in segments[0].text, (
            "style_context is per-recipient — it must NOT leak into "
            "segment[0] (the cached prefix)."
        )
        flat = _segments_to_text(segments)
        assert unique in flat, (
            "style_context must still reach the model — flattened view "
            "must contain it (it just lives in segment[1] now)."
        )

    def test_specialty_and_faq_in_segment_two_not_one(self):
        specialty = "<UNIQUE_SPECIALTY_MARKER> droit du logement local"
        faq = "Q: Quelle est ma deadline ?\nR: Demain 17h."
        segments, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="s", body="b",
            knowledge_base=_FIXTURE_KB,
            specialty_context=specialty,
            faq_context=faq,
            account_id=None,
        )
        assert specialty not in segments[0].text, (
            "specialty_context is per-email — must not leak into the "
            "cached prefix."
        )
        assert "UNIQUE_SPECIALTY_MARKER" not in segments[0].text
        assert "Quelle est ma deadline" not in segments[0].text
        flat = _segments_to_text(segments)
        assert "UNIQUE_SPECIALTY_MARKER" in flat
        assert "Quelle est ma deadline" in flat

    def test_no_dynamic_means_single_segment(self, monkeypatch):
        """No style_context, no specialty, no FAQ, no history, no account,
        and no global learning rules → only the static segment is returned.
        Keeps the API payload tight by not emitting an empty trailing block.

        Stubs `_get_learning_section` because the real draft_learning store
        in this environment has process-global learned corrections that
        would otherwise leak into segment[1] even with `account_id=None`.
        """
        from app.prompts import builders as _builders_mod
        monkeypatch.setattr(_builders_mod, "_get_learning_section", lambda **kw: "")
        # Also neutralise the writing-style service call so it can't push
        # anything into segment[1] from a leftover container singleton.
        monkeypatch.setattr(
            _builders_mod, "compute_style_metrics", lambda *a, **kw: ""
        )

        segments, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="s", body="b",
            knowledge_base=_FIXTURE_KB,
            account_id=None,
        )
        # With every dynamic source neutralised, segment[1] should be
        # absent (or empty if accidentally appended).
        if len(segments) > 1:
            assert segments[1].text.strip() == "", (
                "When there is no dynamic content, segment[1] should not "
                "exist or be empty — keeping the API payload tight."
            )


class TestNoSemanticRegression:
    """Contract: P0.1 reorganises content but loses none. The flattened
    system prompt must still contain every signal the pre-P0.1 prompt did.
    """

    def test_flattened_contains_mirror_rule(self):
        segments, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="s", body="b",
            knowledge_base=_FIXTURE_KB,
            account_id=None,
        )
        flat_lower = _segments_to_text(segments).lower()
        assert "mirror" in flat_lower or "miroir" in flat_lower, (
            "Mirror-of-tone directive must survive P0.1."
        )

    def test_flattened_contains_kb(self):
        segments, _ = get_standard_draft_prompts(
            sender="alice@example.com",
            subject="What is your refund policy?",
            body="Hi, asking about refunds.",
            knowledge_base=_FIXTURE_KB,
            account_id=None,
        )
        flat = _segments_to_text(segments)
        assert "<CONTEXTE>" in flat
        assert "Refunds within 14 days" in flat

    def test_segments_text_helper_is_idempotent_on_string(self):
        """_segments_to_text accepts a plain string — useful for callers
        (the batch enqueue path) that may receive either shape historically.
        """
        assert _segments_to_text("already a string") == "already a string"

    def test_segments_text_helper_concats_with_blank_line(self):
        seg = [
            SystemSegment(text="hello", cacheable=True),
            SystemSegment(text="world", cacheable=False),
        ]
        assert _segments_to_text(seg) == "hello\n\nworld"

    def test_segments_text_helper_skips_empty(self):
        seg = [
            SystemSegment(text="hello", cacheable=True),
            SystemSegment(text="", cacheable=False),
            SystemSegment(text="world", cacheable=False),
        ]
        assert _segments_to_text(seg) == "hello\n\nworld"
