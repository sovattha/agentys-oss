# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit-defense tests for the 12-optimization batch landed 2026-05-04.

Covers the new helpers, env flags, and integration paths that the batch
introduced. Codex audit suite checks on:

  - `_compute_content_hash` — Re/Fwd/Tr normalization stability
  - `_score_complex_candidate` + `_pick_best_complex_draft` — branch coverage
  - Cross-UID cache hit via the content-hash side index
  - `_content_hash_index` 500-entry eviction cap (A5)
  - `format_conversation_history(max_emails=...)` — backward-compat & cap
  - `LLMResponse.stop_reason` field — backward-compat default + adapter wiring
  - `DrafterAgent` retry-on-truncation: triggers, no-ops above retry ceiling (A4)
  - Daemon's default-sentinel detection (A3) — exact shape match only

These are unit tests — no live LLM calls. Adapter wiring is tested by
constructing minimal stand-ins that mirror the LLMPort contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


# ============================================================================
# Section 1 — _compute_content_hash
# ============================================================================

class TestComputeContentHash:
    """Hash stability + Re/Fwd/Tr normalization (smart_routing.py)."""

    def test_hash_is_16_chars_hex(self):
        from app.smart_routing import _compute_content_hash
        h = _compute_content_hash("Subject", "Body")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_re_prefix_normalized(self):
        from app.smart_routing import _compute_content_hash
        assert _compute_content_hash("Hello", "Body") == _compute_content_hash("Re: Hello", "Body")
        assert _compute_content_hash("Hello", "Body") == _compute_content_hash("RE: Hello", "Body")

    def test_fwd_prefix_normalized(self):
        from app.smart_routing import _compute_content_hash
        assert _compute_content_hash("Hello", "Body") == _compute_content_hash("Fwd: Hello", "Body")
        assert _compute_content_hash("Hello", "Body") == _compute_content_hash("Fw: Hello", "Body")
        assert _compute_content_hash("Hello", "Body") == _compute_content_hash("Tr: Hello", "Body")

    def test_body_truncated_to_500(self):
        # Two emails differing only after char 500 should hash the same.
        from app.smart_routing import _compute_content_hash
        body_a = "x" * 500 + "DIFFERENT_TAIL_A"
        body_b = "x" * 500 + "DIFFERENT_TAIL_B"
        assert _compute_content_hash("S", body_a) == _compute_content_hash("S", body_b)

    def test_different_subjects_produce_different_hashes(self):
        from app.smart_routing import _compute_content_hash
        assert _compute_content_hash("A", "Body") != _compute_content_hash("B", "Body")

    def test_handles_empty_inputs(self):
        from app.smart_routing import _compute_content_hash
        h = _compute_content_hash("", "")
        assert len(h) == 16  # still produces valid hash, no crash


# ============================================================================
# Section 2 — _score_complex_candidate + _pick_best_complex_draft
# ============================================================================

class TestSelfConsistencyPicker:
    """Best-of-2 self-consistency picker for COMPLEX-tier drafts."""

    def test_score_clean_draft_is_zero_zero(self):
        from app.smart_routing import _score_complex_candidate
        assert _score_complex_candidate("Yes the price is 1500 EUR.") == (0, 0)

    def test_score_placeholder_penalizes(self):
        from app.smart_routing import _score_complex_candidate
        ph, _ = _score_complex_candidate("Yes we will deliver on [TBD].")
        assert ph >= 1

    def test_score_hedging_opener_penalizes(self):
        from app.smart_routing import _score_complex_candidate
        _, hedging = _score_complex_candidate("Je vais vérifier et reviens.")
        assert hedging >= 1

    def test_score_a_confirmer_anywhere_penalizes(self):
        from app.smart_routing import _score_complex_candidate
        _, hedging = _score_complex_candidate("Confirmé pour mardi à confirmer plus tard.")
        assert hedging >= 1

    def test_empty_draft_max_penalty(self):
        from app.smart_routing import _score_complex_candidate
        ph, hedging = _score_complex_candidate("")
        assert ph == 10 and hedging == 10  # sentinel — empty always loses

    def test_pick_both_empty(self):
        from app.smart_routing import _pick_best_complex_draft
        d, r = _pick_best_complex_draft("", "")
        assert d == "" and r == "both_empty"

    def test_pick_a_empty_returns_b(self):
        from app.smart_routing import _pick_best_complex_draft
        d, r = _pick_best_complex_draft("", "Hello")
        assert d == "Hello" and r == "a_empty"

    def test_pick_b_empty_returns_a(self):
        from app.smart_routing import _pick_best_complex_draft
        d, r = _pick_best_complex_draft("Hello", "")
        assert d == "Hello" and r == "b_empty"

    def test_pick_clean_over_placeholder(self):
        from app.smart_routing import _pick_best_complex_draft
        clean = "Yes the price is 1500 EUR."
        placeholder = "Yes the price is [TBD] EUR."
        d, r = _pick_best_complex_draft(clean, placeholder)
        assert d == clean
        assert r.startswith("a_wins_score")

    def test_pick_clean_over_hedging(self):
        from app.smart_routing import _pick_best_complex_draft
        direct = "The deadline is May 15."
        hedging = "Je vais vérifier la deadline."
        d, r = _pick_best_complex_draft(direct, hedging)
        assert d == direct
        assert r.startswith("a_wins_score")

    def test_pick_tiebreak_by_length(self):
        from app.smart_routing import _pick_best_complex_draft
        short = "OK."
        longer = "OK, I confirm we'll deliver on Friday afternoon."
        d, r = _pick_best_complex_draft(short, longer)
        assert d == longer
        assert r.startswith("b_wins_length")

    def test_pick_reason_starts_with_a_or_b(self):
        """Critical for the corr_a/corr_b dispatch in _generate_complex."""
        from app.smart_routing import _pick_best_complex_draft
        for a, b in [("draft1", "draft2"), ("", "x"), ("y", ""), ("", ""), ("aa", "bb")]:
            _, r = _pick_best_complex_draft(a, b)
            assert r.startswith(("a_", "b_", "both_")), f"unexpected reason {r!r}"


# ============================================================================
# Section 3 — Cross-UID cache hit via content_hash side index (#6)
# ============================================================================

class TestContentHashSideIndex:
    """Cross-UID dedup via the side index, eviction, backward-compat."""

    def setup_method(self):
        # Each test starts with empty caches.
        from app.smart_routing import _draft_cache, _content_hash_index
        _draft_cache.clear()
        _content_hash_index.clear()

    def test_cross_uid_hit_via_content_hash(self):
        from app.smart_routing import _cache_draft, _get_cached_draft, _compute_content_hash
        ch = _compute_content_hash("Subject", "Body content")
        _cache_draft("uid-A", "drafted reply", account_id=42, content_hash=ch)
        # Same content arrives with a different IMAP UID.
        hit = _get_cached_draft("uid-B", account_id=42, content_hash=ch)
        assert hit == "drafted reply"

    def test_cross_uid_no_hit_without_content_hash(self):
        from app.smart_routing import _cache_draft, _get_cached_draft
        _cache_draft("uid-A", "drafted reply", account_id=42)  # no hash
        hit = _get_cached_draft("uid-B", account_id=42, content_hash="anything")
        assert hit is None  # side index never populated → no fallback

    def test_account_isolation(self):
        from app.smart_routing import _cache_draft, _get_cached_draft, _compute_content_hash
        ch = _compute_content_hash("Subject", "Body")
        _cache_draft("uid-A", "account-1 draft", account_id=1, content_hash=ch)
        # Different account, same content — must NOT cross.
        hit = _get_cached_draft("uid-A", account_id=2, content_hash=ch)
        assert hit is None

    def test_backward_compat_no_content_hash(self):
        from app.smart_routing import _cache_draft, _get_cached_draft
        _cache_draft("uid-X", "old draft", account_id=42)
        assert _get_cached_draft("uid-X", account_id=42) == "old draft"

    def test_eviction_caps_index_at_500(self):
        """A5: index drops to ~250 entries when it crosses 500."""
        from app.smart_routing import _cache_draft, _content_hash_index
        # Insert 600 distinct hashes — eviction kicks in once we cross 500.
        for i in range(600):
            _cache_draft(f"uid-{i}", "draft", account_id=42, content_hash=f"h{i:04d}")
        # After eviction, the index should be ≤ 500 (we drop oldest half).
        assert len(_content_hash_index) <= 500


# ============================================================================
# Section 4 — format_conversation_history(max_emails=...)
# ============================================================================

class TestFormatConversationHistory:
    """Backward-compat default of 2 emails + override to 1 when summary present."""

    def _hist(self, n: int) -> list:
        return [
            {"sender": f"a{i}@x.com", "subject": f"s{i}", "date": f"d{i}", "body": f"b{i}"}
            for i in range(n)
        ]

    def test_default_caps_at_two(self):
        from app.prompts.builders import format_conversation_history
        out = format_conversation_history(self._hist(5))
        assert "Email 1" in out
        assert "Email 2" in out
        assert "Email 3" not in out

    def test_override_to_one(self):
        from app.prompts.builders import format_conversation_history
        out = format_conversation_history(self._hist(5), max_emails=1)
        assert "Email 1" in out
        assert "Email 2" not in out

    def test_zero_or_negative_clamps_to_one(self):
        from app.prompts.builders import format_conversation_history
        out = format_conversation_history(self._hist(3), max_emails=0)
        assert "Email 1" in out

    def test_empty_history(self):
        from app.prompts.builders import format_conversation_history
        assert format_conversation_history([]) == "Aucun historique disponible"
        assert format_conversation_history(None) == "Aucun historique disponible"

    def test_split_builder_trims_when_summary_present(self):
        from app.prompts.builders import get_drafter_system_prompt_with_history_split
        hist = self._hist(3)
        # Without summary → 2 emails
        sys_a, dyn_a = get_drafter_system_prompt_with_history_split("KB", hist)
        assert "Email 1" in dyn_a and "Email 2" in dyn_a
        # With summary → 1 email
        sys_b, dyn_b = get_drafter_system_prompt_with_history_split(
            "KB", hist, contact_summary={"relation_type": "client", "habitual_tone": "formal"}
        )
        assert "Email 1" in dyn_b
        assert "Email 2" not in dyn_b


# ============================================================================
# Section 5 — LLMResponse.stop_reason field
# ============================================================================

class TestLLMResponseStopReason:
    """Backward-compat default + adapter wiring."""

    def test_default_is_empty_string(self):
        from app.domain.ports.llm_port import LLMResponse
        r = LLMResponse(content="x")
        assert r.stop_reason == ""

    def test_settable_to_max_tokens(self):
        from app.domain.ports.llm_port import LLMResponse
        r = LLMResponse(content="truncated", stop_reason="max_tokens")
        assert r.stop_reason == "max_tokens"

    def test_legacy_module_mirror_has_field(self):
        """app/llm/base.py mirrors the canonical port — kept in sync."""
        from app.llm.base import LLMResponse as LegacyResponse
        r = LegacyResponse(content="x")
        assert hasattr(r, "stop_reason")
        assert r.stop_reason == ""


# ============================================================================
# Section 6 — DrafterAgent retry-on-truncation (#3)
# ============================================================================

@dataclass
class _FakeLLMResponse:
    """Shape that matches LLMResponse for DrafterAgent.draft asserts."""
    content: str
    input_tokens: int = 100
    output_tokens: int = 100
    model: str = "claude-haiku-4-5-20251001"
    stop_reason: str = "end_turn"


class _FakeLLM:
    """Records max_tokens of each call and returns scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.model = "claude-haiku-4-5-20251001"

    def complete(self, system, user, max_tokens=1024, temperature=None):
        self.calls.append({"max_tokens": max_tokens, "temperature": temperature})
        if not self._responses:
            return _FakeLLMResponse(content="default")
        return self._responses.pop(0)


class TestDrafterRetryOnTruncation:
    """Retry path triggers on stop_reason='max_tokens', no-op above retry ceiling.

    Tests use a body long enough (≥ 700 chars) that the B4-lite adaptive
    budget tier resolves to MAX_TOKENS_DRAFT (600). Short bodies would land
    in the 250-tier and obscure the retry-vs-adaptive distinction.
    """

    # Body > 1500 chars → tier 4 → 600 tokens (matches MAX_TOKENS_DRAFT in
    # rev 2). Long enough that the adaptive budget doesn't kick in BELOW
    # MAX_TOKENS_DRAFT, so the retry test sees the expected first-call budget.
    _LONG_BODY = "De: x@y.com\nSujet: t\n\n" + ("body content. " * 120)  # ~1700 chars

    def test_no_retry_on_normal_stop(self):
        from app.agents import DrafterAgent
        from app.config import MAX_TOKENS_DRAFT
        fake = _FakeLLM([_FakeLLMResponse(content="full reply", stop_reason="end_turn")])
        agent = DrafterAgent.__new__(DrafterAgent)
        agent.knowledge_base = "KB"
        agent.account_id = None
        agent.max_tokens = MAX_TOKENS_DRAFT
        agent.timeout_seconds = 120
        agent.max_retries = 3
        agent._llm = fake
        out = agent.draft(self._LONG_BODY)
        assert out == "full reply"
        assert len(fake.calls) == 1
        # Rev 2 tier 4 (>1500 chars) → 600 = MAX_TOKENS_DRAFT
        assert fake.calls[0]["max_tokens"] == MAX_TOKENS_DRAFT

    def test_retry_when_truncated(self):
        from app.agents import DrafterAgent
        from app.config import MAX_TOKENS_DRAFT, MAX_TOKENS_DRAFT_RETRY
        fake = _FakeLLM([
            _FakeLLMResponse(content="cut off…", stop_reason="max_tokens"),
            _FakeLLMResponse(content="full reply complete.", stop_reason="end_turn"),
        ])
        agent = DrafterAgent.__new__(DrafterAgent)
        agent.knowledge_base = "KB"
        agent.account_id = None
        agent.max_tokens = MAX_TOKENS_DRAFT
        agent.timeout_seconds = 120
        agent.max_retries = 3
        agent._llm = fake
        out = agent.draft(self._LONG_BODY)
        assert out == "full reply complete."
        assert len(fake.calls) == 2
        # First call uses tier 4 (600 tokens); retry escalates to ceiling.
        assert fake.calls[0]["max_tokens"] == MAX_TOKENS_DRAFT
        assert fake.calls[1]["max_tokens"] == MAX_TOKENS_DRAFT_RETRY

    def test_no_retry_when_max_tokens_above_ceiling(self):
        """A4: caller-overridden max_tokens >= ceiling → retry no-ops."""
        from app.agents import DrafterAgent
        from app.config import MAX_TOKENS_DRAFT_RETRY
        fake = _FakeLLM([_FakeLLMResponse(content="cut", stop_reason="max_tokens")])
        agent = DrafterAgent.__new__(DrafterAgent)
        agent.knowledge_base = "KB"
        agent.account_id = None
        agent.max_tokens = MAX_TOKENS_DRAFT_RETRY + 100
        agent.timeout_seconds = 120
        agent.max_retries = 3
        agent._llm = fake
        out = agent.draft(self._LONG_BODY)
        assert out == "cut"
        assert len(fake.calls) == 1  # no retry — already at/above ceiling


# ============================================================================
# Section 7 — Daemon ClassificationResult frozen invariant
# ============================================================================

class TestClassificationResultFrozen:
    """`ClassificationResult` stays a frozen dataclass — caller-side mutation
    must raise, otherwise the daemon's "should_skip" flag could be flipped
    underneath a downstream consumer.
    """

    def test_classification_result_is_frozen(self):
        from app.daemon import ClassificationResult
        r = ClassificationResult(
            category="NORMAL", priority_score=50, should_skip=False,
        )
        with pytest.raises(Exception):  # FrozenInstanceError on dataclass(frozen=True)
            r.priority_score = 99  # type: ignore[misc]


# ============================================================================
# Section 8 — Env flags wiring
# ============================================================================

class TestEnvFlags:
    """Assert the new env flags exist with expected defaults."""

    # `test_auto_draft_default_off` was retired 2026-05-05: the
    # AUTO_DRAFT_ENABLED flag was deleted entirely when the dead auto-draft
    # pipeline was removed from process_email. The successor assertion
    # lives in TestPhishingMovedIntoAutoLabel.test_auto_draft_enabled_flag_removed
    # which now verifies the flag is *gone*, not that it defaults off.

    def test_self_consistency_complex_default_on(self):
        from app.config import SELF_CONSISTENCY_COMPLEX_ENABLED
        assert SELF_CONSISTENCY_COMPLEX_ENABLED is True

    def test_max_tokens_draft_default_600(self):
        import os
        if "MAX_TOKENS_DRAFT" in os.environ:
            pytest.skip("env override active")
        from app.config import MAX_TOKENS_DRAFT
        assert MAX_TOKENS_DRAFT == 600

    def test_max_tokens_draft_retry_default_1024(self):
        import os
        if "MAX_TOKENS_DRAFT_RETRY" in os.environ:
            pytest.skip("env override active")
        from app.config import MAX_TOKENS_DRAFT_RETRY
        assert MAX_TOKENS_DRAFT_RETRY == 1024

    def test_model_versions_bumped(self):
        from app.config import CLAUDE_MODEL_FAST, CLAUDE_MODEL_OPUS
        assert CLAUDE_MODEL_FAST == "claude-sonnet-4-6"
        assert CLAUDE_MODEL_OPUS == "claude-opus-4-7"


# ============================================================================
# Section 10 — Adaptive draft budget (B4-lite)
# ============================================================================

class TestAdaptiveDraftBudget:
    """Body-length-tier'd max_tokens budget (rev 2 — 2026-05-05 tighter tiers)."""

    def test_tier1_tiny_body(self):
        from app.config import adaptive_draft_max_tokens
        # ≤100 chars → 150 tokens (rev 2 — was 250 in rev 1)
        assert adaptive_draft_max_tokens(50) == 150
        assert adaptive_draft_max_tokens(100) == 150

    def test_tier2_short_body(self):
        from app.config import adaptive_draft_max_tokens
        # 101-400 chars → 250 tokens (rev 2 — was 400 in rev 1)
        assert adaptive_draft_max_tokens(101) == 250
        assert adaptive_draft_max_tokens(400) == 250

    def test_tier3_medium_body(self):
        from app.config import adaptive_draft_max_tokens
        # 401-1500 chars → 450 tokens (rev 2 — was 600 / MAX_TOKENS_DRAFT in rev 1)
        assert adaptive_draft_max_tokens(401) == 450
        assert adaptive_draft_max_tokens(1500) == 450

    def test_tier4_long_body(self):
        from app.config import adaptive_draft_max_tokens
        # >1500 chars → 600 tokens (rev 2 — was 800 in rev 1)
        assert adaptive_draft_max_tokens(1501) == 600
        assert adaptive_draft_max_tokens(5000) == 600

    def test_negative_or_zero_treated_as_tier1(self):
        from app.config import adaptive_draft_max_tokens
        assert adaptive_draft_max_tokens(0) == 150
        assert adaptive_draft_max_tokens(-100) == 150

    def test_disabled_flag_returns_default(self):
        from app.config import adaptive_draft_max_tokens, MAX_TOKENS_DRAFT
        from app import config as cfg
        original = cfg.ADAPTIVE_DRAFT_BUDGET_ENABLED
        try:
            cfg.ADAPTIVE_DRAFT_BUDGET_ENABLED = False
            assert adaptive_draft_max_tokens(50) == MAX_TOKENS_DRAFT
        finally:
            cfg.ADAPTIVE_DRAFT_BUDGET_ENABLED = original

    def test_drafter_uses_adaptive_budget(self):
        """DrafterAgent.draft adapts max_tokens to body length when at default."""
        from app.agents import DrafterAgent
        fake = _FakeLLM([_FakeLLMResponse(content="ok", stop_reason="end_turn")])
        agent = DrafterAgent.__new__(DrafterAgent)
        agent.knowledge_base = "KB"
        agent.account_id = None
        from app.config import MAX_TOKENS_DRAFT
        agent.max_tokens = MAX_TOKENS_DRAFT  # default budget → adaptive applies
        agent.timeout_seconds = 120
        agent.max_retries = 3
        agent._llm = fake
        agent.draft("De: x@y.com\nSujet: t\n\nshort")  # tiny body (~25 chars)
        # Rev 2 tier 1 (≤100 chars body) → 150 tokens
        assert fake.calls[0]["max_tokens"] == 150

    def test_drafter_skips_adaptive_when_caller_overrides(self):
        """Caller-overridden max_tokens wins — adaptive only applies at default."""
        from app.agents import DrafterAgent
        fake = _FakeLLM([_FakeLLMResponse(content="ok", stop_reason="end_turn")])
        agent = DrafterAgent.__new__(DrafterAgent)
        agent.knowledge_base = "KB"
        agent.account_id = None
        agent.max_tokens = 800  # caller-explicit, NOT the default
        agent.timeout_seconds = 120
        agent.max_retries = 3
        agent._llm = fake
        agent.draft("De: x@y.com\nSujet: t\n\nshort")
        assert fake.calls[0]["max_tokens"] == 800  # untouched


# ============================================================================
# Section 11 — 2026-05-05 audit batch
# ============================================================================

class TestPhishingMovedIntoAutoLabel:
    """P1: phishing detector now runs as part of _auto_label_email,
    BEFORE any LLM call, regardless of any draft toggle."""

    def test_phishing_check_lives_in_auto_label(self):
        """Source-level assertion: _auto_label_email body references _detect_phishing."""
        import inspect
        from app.daemon import EmailDaemon
        src = inspect.getsource(EmailDaemon._auto_label_email)
        assert "_detect_phishing" in src, (
            "phishing pre-check is missing from _auto_label_email — see P1 of "
            "the 2026-05-05 audit batch"
        )

    def test_auto_draft_enabled_flag_removed(self):
        """AUTO_DRAFT_ENABLED was deleted — auto-draft no longer exists."""
        import app.config as cfg
        assert not hasattr(cfg, "AUTO_DRAFT_ENABLED"), (
            "AUTO_DRAFT_ENABLED was supposed to be deleted — auto-draft pipeline "
            "is fully removed and the flag has no consumers"
        )


class TestDeadAgentsRemoved:
    """P2: ContextAnalyzerAgent and INTENT_CLASSIFIER_PROMPT removed."""

    def test_context_analyzer_agent_deleted(self):
        import app.agents as agents_mod
        assert not hasattr(agents_mod, "ContextAnalyzerAgent"), (
            "ContextAnalyzerAgent was supposed to be deleted (never wired in production)"
        )

    def test_context_analyzer_helpers_deleted(self):
        import app.agents as agents_mod
        for name in (
            "CONTEXT_ANALYZER_SYSTEM_PROMPT",
            "_build_context_user_prompt",
            "_parse_context_llm_response",
        ):
            assert not hasattr(agents_mod, name), f"{name} should be deleted"

    def test_intent_classifier_prompt_deleted(self):
        import app.agents as agents_mod
        assert not hasattr(agents_mod, "INTENT_CLASSIFIER_PROMPT"), (
            "INTENT_CLASSIFIER_PROMPT was supposed to be deleted (heuristic version "
            "in app/prompts/helpers.py is what production uses)"
        )


class TestModelPropertyConversion:
    """P4: model field → @property on 3 agents."""

    def test_commitment_extractor_model_is_property(self):
        from app.agents import CommitmentExtractorAgent
        assert isinstance(CommitmentExtractorAgent.__dict__.get("model"), property)

    def test_sensitive_data_detector_model_is_property(self):
        from app.agents import SensitiveDataDetectorAgent
        assert isinstance(SensitiveDataDetectorAgent.__dict__.get("model"), property)


class TestDrafterPromptCacheFloor:
    """P5: drafter prompt now exceeds Anthropic's 1024-token cache floor."""

    def test_drafter_template_size(self):
        """Read the on-disk template directly and verify it's large enough."""
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "app" / "prompts" / "templates" / "drafter_system_prompt.txt"
        text = path.read_text(encoding="utf-8")
        approx_tokens = len(text) // 4
        assert approx_tokens > 1024, (
            f"DRAFTER_SYSTEM_PROMPT is approx {approx_tokens} tokens — must be > 1024 "
            f"so cache_control writes fire reliably even before account-specific "
            f"context blocks are appended"
        )

    def test_template_contains_quality_guardrails_section(self):
        """The padding is meaningful content, not whitespace filler."""
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "app" / "prompts" / "templates" / "drafter_system_prompt.txt"
        text = path.read_text(encoding="utf-8")
        assert "QUALITY GUARDRAILS" in text


class TestExpandedHedgingOpeners:
    """P6: hedging vocabulary now covers EN and FR variants."""

    def test_french_hedging_phrases_present(self):
        from app.smart_routing import _HEDGING_OPENERS
        for phrase in (
            "je reviens vers vous",
            "je m'en occupe",
            "je vais voir",
        ):
            assert phrase in _HEDGING_OPENERS, f"missing FR phrase: {phrase!r}"

    def test_english_hedging_phrases_present(self):
        from app.smart_routing import _HEDGING_OPENERS
        for phrase in (
            "i'll get back to you",
            "i'll follow up",
            "i'll circle back",
            "let me get back",
        ):
            assert phrase in _HEDGING_OPENERS, f"missing EN phrase: {phrase!r}"

    def test_picker_penalizes_get_back_to_you(self):
        from app.smart_routing import _pick_best_complex_draft
        direct = "Yes the rate is 1500 EUR per month."
        hedging = "I'll get back to you on the rate."
        winner, reason = _pick_best_complex_draft(direct, hedging)
        assert winner == direct, f"expected direct to win, got {winner!r} ({reason})"

    def test_picker_penalizes_je_reviens_vers_vous(self):
        from app.smart_routing import _pick_best_complex_draft
        direct = "Le tarif est de 1500€ par mois."
        hedging = "Je reviens vers vous concernant le tarif."
        winner, reason = _pick_best_complex_draft(direct, hedging)
        assert winner == direct, f"expected direct to win, got {winner!r} ({reason})"


class TestExtractDisplayNameMemoized:
    """P7: _extract_display_name is wrapped with functools.lru_cache."""

    def test_lru_cache_attached(self):
        from app.prompts import _extract_display_name
        ci = _extract_display_name.cache_info()
        assert ci.maxsize == 1000, f"expected maxsize=1000, got {ci.maxsize}"

    def test_repeated_call_is_a_cache_hit(self):
        from app.prompts import _extract_display_name
        # Use a unique sender so this test is order-independent
        sender = "perftest_unique_2026_05_05@example.com"
        _extract_display_name.cache_clear()
        _extract_display_name(sender)
        before = _extract_display_name.cache_info()
        _extract_display_name(sender)
        after = _extract_display_name.cache_info()
        assert after.hits == before.hits + 1, (
            f"second call should hit cache — before={before}, after={after}"
        )

    def test_known_outputs_still_correct(self):
        """Memoization must not change semantics."""
        from app.prompts import _extract_display_name
        assert _extract_display_name("John Doe <john@example.com>") == "John Doe"
        assert _extract_display_name("alexandre.simon@hotmail.com") == "Alexandre Simon"
        assert _extract_display_name("noreply@example.com") == ""


# ============================================================================
# Section 12 — 2026-05-05 audit batch v2 (per-agent recommendations)
# ============================================================================

class TestSentinelPreFilter:
    """S1: SensitiveDataDetectorAgent skips short / no-PII drafts pre-LLM."""

    def _agent(self):
        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent.__new__(SensitiveDataDetectorAgent)
        agent._llm = None  # force test failure if pre-filter is bypassed
        return agent

    def test_skip_short_draft(self):
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        agent = self._agent()
        result = agent.detect("Merci à toi.", "alice@example.com")
        assert result.is_sensitive is False
        assert isinstance(result, SensitiveDataDetection)

    def test_skip_long_draft_with_no_pii_pattern(self):
        agent = self._agent()
        # Long but contains no digits/email/URL/credentials/secret keyword.
        clean_draft = (
            "Bonjour, je suis disponible pour un appel la semaine prochaine. "
            "Faites-moi savoir quand vous êtes libre. Cordialement."
        )
        result = agent.detect(clean_draft, "alice@example.com")
        assert result.is_sensitive is False

    def test_email_pattern_handled_by_regex_no_llm(self):
        """2026-05-05: regex detector handles emails directly — no LLM call."""
        from app.agents import SensitiveDataDetectorAgent
        from unittest.mock import MagicMock
        agent = SensitiveDataDetectorAgent.__new__(SensitiveDataDetectorAgent)
        agent._llm = MagicMock()
        with_email = (
            "Voici les coordonnées du contact pour la prochaine réunion : "
            "alice.dupont@example.com — n'hésitez pas à la solliciter."
        )
        result = agent.detect(with_email, "bob@example.com")
        assert agent._llm.complete.call_count == 0
        assert result.is_sensitive is True

    def test_digit_pattern_does_not_match_phone_alone(self):
        """A bare 8-digit reference number is not a real phone — regex
        requires 10+ digits. Result: regex finds NO PII → no LLM call →
        is_sensitive=False. This is intentional: short digit runs are
        product/order numbers, not personal data.
        """
        from app.agents import SensitiveDataDetectorAgent
        from unittest.mock import MagicMock
        agent = SensitiveDataDetectorAgent.__new__(SensitiveDataDetectorAgent)
        agent._llm = MagicMock()
        with_short_digits = (
            "Le numéro de référence interne est 12345678 pour cette commande "
            "qu'il faudra valider avant la fin de semaine."
        )
        result = agent.detect(with_short_digits, "bob@example.com")
        assert agent._llm.complete.call_count == 0
        # 8-digit ref number is not phone-shaped → not PII per regex layer.
        assert result.is_sensitive is False

    def test_credential_keyword_handled_by_regex(self):
        """2026-05-05: regex catches `mot de passe : <value>` directly."""
        from app.agents import SensitiveDataDetectorAgent
        from unittest.mock import MagicMock
        agent = SensitiveDataDetectorAgent.__new__(SensitiveDataDetectorAgent)
        agent._llm = MagicMock()
        # Use the explicit `key: value` shape that the regex pattern
        # expects (matches `(password|mot de passe|secret|...)\s*[:=]\s*\S{4,}`).
        with_secret = (
            "Voici les paramètres pour la connexion au portail interne. "
            "mot de passe : HunterTwo2024 — à mémoriser et ne pas partager."
        )
        result = agent.detect(with_secret, "bob@example.com")
        assert agent._llm.complete.call_count == 0
        assert result.is_sensitive is True
        assert any(
            item.description == "secret keyword"
            for item in result.detected_items
        )


class TestCriticPromptTrim:
    """C2: critic prompt slimmed from 5 → 3 calibration examples."""

    def test_critic_prompt_size_reduced(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "app" / "prompts" / "templates" / "critic_structured_system_prompt.txt"
        text = path.read_text(encoding="utf-8")
        # Original was 9117 bytes; trim should cut at least 1k bytes
        # while keeping > 1024 token cache floor.
        assert len(text) < 9000, f"prompt should be smaller, got {len(text)} bytes"
        approx_tokens = len(text) // 4
        assert approx_tokens > 1024, (
            f"prompt must stay above the cache floor — got {approx_tokens} tokens"
        )

    def test_critic_prompt_keeps_anchor_examples(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "app" / "prompts" / "templates" / "critic_structured_system_prompt.txt"
        text = path.read_text(encoding="utf-8")
        # Casual anchor (Franglais), placeholder reject anchor, formal B2B anchor.
        assert "Franglais hyper-casual" in text
        assert "Placeholder = REJECT" in text
        assert "Réponse B2B formelle" in text


class TestUIAgentsPanelSync:
    """U1: UI cards aligned with deployed agent set.

    `AgentsShowcase.tsx` was deleted in commit 14e186f2 ("retire l'Agent
    Marketplace et le modal AgentsShowcase de la web app"), so the two
    file-reading assertions about its contents are gone. The i18n locale
    contract below still applies — `agents.json` is consumed elsewhere.
    """

    def test_i18n_files_have_new_keys(self):
        from pathlib import Path
        import json
        locales_root = Path(__file__).resolve().parents[1] / "agentys-app" / "src" / "i18n" / "locales"
        for path in sorted(locales_root.glob("*/agents.json")):
            lang = path.parent.name
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("triagist_name", "triagist_desc", "watch_name", "watch_desc", "pipeline_triagist"):
                assert key in data, f"{lang}/agents.json missing key: {key}"
            # Stale keys must be gone
            for stale in ("analyst_name", "analyst_desc", "pipeline_analyst"):
                assert stale not in data, f"{lang}/agents.json still has stale key: {stale}"


# ============================================================================
# Section 13 — 2026-05-05 audit batch v3 (deferred items implementation)
# ============================================================================


class TestMultiBlockPromptCache:
    """Phase 1 (#3): SystemSegment + multi-block adapter wiring."""

    def test_system_segment_dataclass(self):
        from app.domain.ports.llm_port import SystemSegment
        seg = SystemSegment(text="hello", cacheable=True)
        assert seg.text == "hello"
        assert seg.cacheable is True
        # Frozen — mutation should raise
        with pytest.raises(Exception):
            seg.text = "mutated"  # type: ignore[misc]

    def test_adapter_helper_handles_str_legacy(self):
        from app.adapters.llm.claude_adapter import _build_anthropic_system_blocks
        out = _build_anthropic_system_blocks("hello world")
        assert len(out) == 1
        assert out[0]["text"] == "hello world"
        assert out[0]["cache_control"] == {"type": "ephemeral"}

    def test_adapter_helper_three_cacheable_segments(self):
        from app.adapters.llm.claude_adapter import _build_anthropic_system_blocks
        from app.domain.ports.llm_port import SystemSegment
        out = _build_anthropic_system_blocks([
            SystemSegment("A"), SystemSegment("B"), SystemSegment("C"),
        ])
        assert len(out) == 3
        assert all("cache_control" in b for b in out)

    def test_adapter_helper_mixed_cacheable(self):
        from app.adapters.llm.claude_adapter import _build_anthropic_system_blocks
        from app.domain.ports.llm_port import SystemSegment
        out = _build_anthropic_system_blocks([
            SystemSegment("static", cacheable=True),
            SystemSegment("dynamic", cacheable=False),
            SystemSegment("more static", cacheable=True),
        ])
        assert "cache_control" in out[0]
        assert "cache_control" not in out[1]
        assert "cache_control" in out[2]

    def test_adapter_helper_clamps_above_4_breakpoints(self):
        from app.adapters.llm.claude_adapter import _build_anthropic_system_blocks
        from app.domain.ports.llm_port import SystemSegment
        out = _build_anthropic_system_blocks([SystemSegment(f"s{i}") for i in range(6)])
        markers = sum(1 for b in out if "cache_control" in b)
        assert markers == 4
        # First 3 + LAST should keep their markers
        assert all("cache_control" in out[i] for i in (0, 1, 2, 5))

    def test_adapter_helper_rejects_bad_list_element(self):
        from app.adapters.llm.claude_adapter import _build_anthropic_system_blocks
        with pytest.raises(TypeError, match="SystemSegment"):
            _build_anthropic_system_blocks(["bad item"])

    def test_drafter_segments_builder_three_segments(self):
        from app.prompts import get_drafter_system_segments_with_history
        from app.domain.ports.llm_port import SystemSegment
        hist = [{"sender": "a@x.com", "subject": "s", "date": "d", "body": "b"}]
        segs, dyn = get_drafter_system_segments_with_history(
            knowledge_base="ACME info",
            conversation_history=hist,
            user_email="me@me.com",
        )
        assert len(segs) == 3
        assert all(isinstance(s, SystemSegment) for s in segs)
        # Segment 2 is the KB-only block.
        assert segs[1].text == "ACME info"

    def test_enable_multi_block_cache_flag(self):
        from app.config import ENABLE_MULTI_BLOCK_CACHE
        assert ENABLE_MULTI_BLOCK_CACHE is True


class TestPersistentContactSummaryInvalidation:
    """Phase 2 (#4): cache invalidation on new inbound email."""

    def test_invalidation_normalizes_email_case(self):
        from app.services import contact_summary_service as svc
        svc._memory_cache.clear()
        svc._cache_set((42, "alice@example.com"), {"tone": "casual"})
        assert (42, "alice@example.com") in svc._memory_cache
        # Mixed case sender should still invalidate
        svc.invalidate_contact_summary(42, "Alice@Example.com")
        assert (42, "alice@example.com") not in svc._memory_cache

    def test_invalidation_isolates_accounts(self):
        from app.services import contact_summary_service as svc
        svc._memory_cache.clear()
        svc._cache_set((1, "x@y.com"), {"tone": "formal"})
        svc._cache_set((2, "x@y.com"), {"tone": "casual"})
        svc.invalidate_contact_summary(1, "x@y.com")
        assert (1, "x@y.com") not in svc._memory_cache
        # Account 2 still cached
        assert (2, "x@y.com") in svc._memory_cache


class TestPiiRegexDetector:
    """Phase 3 (#2): regex detector replaces LLM for deterministic categories."""

    def test_email_match(self):
        from app.services.pii_detector import detect_pii
        m = detect_pii("Contact me at alice.dupont@example.com please.")
        assert any(x.category == "EMAIL" for x in m)

    def test_credit_card_luhn_valid(self):
        from app.services.pii_detector import detect_pii
        m = detect_pii("CC: 4111 1111 1111 1111 expires 12/25.")
        assert any(x.category == "CREDIT_CARD" for x in m)

    def test_credit_card_luhn_invalid_rejected(self):
        from app.services.pii_detector import detect_pii
        m = detect_pii("Random number: 4111 1111 1111 1112")
        assert not any(x.category == "CREDIT_CARD" for x in m)

    def test_iban_match(self):
        from app.services.pii_detector import detect_pii
        m = detect_pii("Compte FR7630006000011234567890189 Crédit Agricole.")
        assert any(x.category == "IBAN" for x in m)

    def test_us_ssn_match(self):
        from app.services.pii_detector import detect_pii
        m = detect_pii("My SSN is 123-45-6789 for the form.")
        assert any(x.category == "SSN_US" for x in m)

    def test_api_key_match_anthropic_style(self):
        from app.services.pii_detector import detect_pii
        m = detect_pii("Token: sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD")
        assert any(x.category == "API_KEY" for x in m)

    def test_api_key_match_aws_access_key(self):
        from app.services.pii_detector import detect_pii
        m = detect_pii("AWS key AKIAIOSFODNN7EXAMPLE for production.")
        assert any(x.category == "API_KEY" for x in m)

    def test_api_key_match_bearer(self):
        from app.services.pii_detector import detect_pii
        m = detect_pii("Authorization: Bearer eyJabcdefghijk0123456789ABCDEF")
        assert any(x.category == "API_KEY" for x in m)

    def test_secret_keyword_match(self):
        from app.services.pii_detector import detect_pii
        m = detect_pii("Password: HunterTwo2024!")
        assert any(x.category == "SECRET_KEYWORD" for x in m)

    def test_phone_match(self):
        from app.services.pii_detector import detect_pii
        m = detect_pii("Mon numero est 06 12 34 56 78 ce soir.")
        assert any(x.category == "PHONE" for x in m)

    def test_clean_draft_no_match(self):
        from app.services.pii_detector import has_pii
        assert not has_pii("Hello, I will be available next week. Best regards.")
        assert not has_pii("Bonjour, je suis disponible demain. Cordialement.")

    def test_categories_in_returns_sorted_distinct(self):
        from app.services.pii_detector import categories_in
        cats = categories_in("Email me@me.com or call 555-123-4567.")
        assert cats == sorted(cats)
        assert "EMAIL" in cats and "PHONE" in cats


class TestSensitiveDataDetectorRegexPath:
    """Phase 3 (#2): SensitiveDataDetectorAgent uses regex first, no LLM."""

    def _agent(self, llm_mock=None):
        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent.__new__(SensitiveDataDetectorAgent)
        agent._llm = llm_mock if llm_mock is not None else MagicMock()
        return agent

    def test_regex_match_skips_llm(self):
        agent = self._agent()
        result = agent.detect(
            "Voici la carte de crédit pour la facture : 4111 1111 1111 1111.",
            "alice@example.com",
        )
        assert result.is_sensitive is True
        assert agent._llm.complete.call_count == 0
        # Detected items are populated from regex categories
        assert len(result.detected_items) >= 1

    def test_clean_draft_no_llm(self):
        agent = self._agent()
        result = agent.detect(
            "Bonjour, je suis disponible la semaine prochaine pour un appel. Cordialement.",
            "alice@example.com",
        )
        assert result.is_sensitive is False
        assert agent._llm.complete.call_count == 0

    def test_short_draft_no_llm(self):
        agent = self._agent()
        result = agent.detect("Merci à toi.", "alice@example.com")
        assert result.is_sensitive is False
        assert agent._llm.complete.call_count == 0

    def test_legacy_llm_path_when_flag_off(self):
        from app import config as cfg
        original = cfg.USE_REGEX_PII_DETECTOR
        try:
            cfg.USE_REGEX_PII_DETECTOR = False
            llm = MagicMock()
            llm.complete.return_value = MagicMock(
                content='{"is_sensitive":true,"confidence":0.9,"detected_items":[],"analysis_summary":""}',
                input_tokens=80, output_tokens=30,
            )
            agent = self._agent(llm)
            agent.detect(
                "Voici 4111 1111 1111 1111 pour le paiement de la facture mensuelle.",
                "alice@example.com",
            )
            assert llm.complete.call_count == 1
        finally:
            cfg.USE_REGEX_PII_DETECTOR = original


class TestStreamV1BeforeCriticNondestructive:
    """Phase 4 (#1): non-destructive draft_revised event scaffolding."""

    # `test_flag_default_off` was retired 2026-05-05 PM when the frontend
    # handler shipped — the flag was flipped to default ON. The successor
    # assertion lives in TestStreamingNonDestructiveDefaultOn.

    def test_emit_draft_revised_helper_exists(self):
        from app.api.websocket import emit_draft_revised
        # Just check signature is callable — actual WS plumbing is tested elsewhere
        assert callable(emit_draft_revised)


class TestNewEnvFlagsConsistency:
    """All audit-batch flags exist with documented defaults."""

    def test_all_flags_present(self):
        from app import config as cfg
        # 2026-05-05 PM update: STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE flipped
        # to default ON now that the frontend handler ships.
        for name, expected in [
            ("ENABLE_MULTI_BLOCK_CACHE", True),
            ("USE_REGEX_PII_DETECTOR", True),
            ("STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE", True),
        ]:
            actual = getattr(cfg, name)
            assert actual is expected, f"{name}: expected {expected}, got {actual}"


# ============================================================================
# Section 14 — bug fixes from same-day audit (2026-05-05 PM)
# ============================================================================

class TestPiiCategoryToTypeMappingValid:
    """Bug fix: IP_ADDRESS used to map to 'technical' which is not a valid
    SensitiveDataType member. Now all mapped values must be valid enum keys."""

    def test_all_mapped_values_are_valid_enum_members(self):
        from app.domain.entities.sensitive_data import SensitiveDataType
        from app.agents import SensitiveDataDetectorAgent
        for cat, type_str in SensitiveDataDetectorAgent._REGEX_CATEGORY_TO_TYPE.items():
            try:
                SensitiveDataType(type_str)
            except ValueError:
                pytest.fail(
                    f"Mapping bug: {cat!r} → {type_str!r} is NOT a valid "
                    f"SensitiveDataType. Valid values: financial, personal, "
                    f"commercial, credential."
                )

    def test_ip_address_now_maps_to_personal_not_technical(self):
        from app.agents import SensitiveDataDetectorAgent
        assert SensitiveDataDetectorAgent._REGEX_CATEGORY_TO_TYPE["IP_ADDRESS"] == "personal"

    def test_credit_card_maps_to_financial(self):
        from app.agents import SensitiveDataDetectorAgent
        from app.domain.entities.sensitive_data import SensitiveDataType
        agent = SensitiveDataDetectorAgent.__new__(SensitiveDataDetectorAgent)
        agent._llm = None
        result = agent.detect(
            "Voici la carte 4111 1111 1111 1111 pour le paiement.",
            "alice@example.com",
        )
        assert result.is_sensitive
        # Filter to credit-card items and check type
        cc_items = [i for i in result.detected_items if i.description == "credit card"]
        assert cc_items
        assert cc_items[0].data_type == SensitiveDataType.FINANCIAL


class TestTinyEmailLabelIsValid:
    """Bug fix: tiny-email bypass used to assign 'Normal' label which is
    not in DefaultLabel vocabulary (Action / FYI / Noise). Now uses 'FYI'."""

    def test_tiny_bypass_uses_valid_label(self):
        """Source-level assertion: the bypass code references a valid label."""
        import inspect
        from app.daemon import EmailDaemon
        src = inspect.getsource(EmailDaemon._auto_label_email)
        # Must NOT use the invalid 'Normal' label
        assert '"Normal"' not in src and "'Normal'" not in src, (
            "tiny-email bypass still references invalid 'Normal' label"
        )
        # Must use one of the valid DefaultLabel values
        assert '"FYI"' in src or '"Noise"' in src or '"Action"' in src


# ============================================================================
# Section 15 — 2026-05-05 PM batch: dead-code deletion + prompt strengthening
# ============================================================================


class TestDeadHelpersFullyRemoved:
    """All four dead auto-draft helpers must be GONE (not just commented).
    The 2026-05-05 morning audit kept them as 'preserved for reference' which
    Codex flagged as archaeology debt. Now actually deleted."""

    def test_try_combined_label_and_draft_deleted(self):
        from app.daemon import EmailDaemon
        assert not hasattr(EmailDaemon, "_try_combined_label_and_draft"), (
            "_try_combined_label_and_draft was supposed to be deleted, not "
            "just made to return False"
        )

    def test_save_combined_draft_deleted(self):
        from app.daemon import EmailDaemon
        assert not hasattr(EmailDaemon, "_save_combined_draft"), (
            "_save_combined_draft was supposed to be deleted (only consumer "
            "was _try_combined_label_and_draft)"
        )

    def test_sender_warrants_auto_draft_deleted(self):
        from app.daemon import EmailDaemon
        assert not hasattr(EmailDaemon, "_sender_warrants_auto_draft")

    def test_account_db_id_for_outbound_check_deleted(self):
        from app.daemon import EmailDaemon
        assert not hasattr(EmailDaemon, "_account_db_id_for_outbound_check")

    def test_trigger_draft_for_action_email_deleted(self):
        import app.api.labels as labels_mod
        assert not hasattr(labels_mod, "_trigger_draft_for_action_email")


class TestDrafterPromptAntiPatterns:
    """Strengthening: anti-pattern entries added to drafter prompt to
    reduce the cleanup pipeline's load."""

    def test_drafter_prompt_has_13_anti_patterns(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "app" / "prompts" / "templates" / "drafter_system_prompt.txt"
        text = path.read_text(encoding="utf-8")
        # Each anti-pattern entry has a "BAD :" example.
        assert text.count("BAD :") == 13, (
            f"Expected 13 anti-pattern entries, got {text.count('BAD :')}"
        )

    def test_drafter_prompt_addresses_known_haiku_failure_modes(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "app" / "prompts" / "templates" / "drafter_system_prompt.txt"
        text = path.read_text(encoding="utf-8")
        # Each major cleanup-pipeline pattern should be addressed in prompt.
        for keyword in (
            "SYCOPHANCY",
            "OUVERTURES RÉPÉTITIVES",
            "EXCÈS D'EXCUSES",
            "MARKDOWN",
            "GREETINGS DUPLIQUÉS",
            "QUESTIONS NON DEMANDÉES",
            "MOTS-VIDES IA",
            "PHRASES RÉCAPITULATIVES",
            "AFFIRMATIONS REDONDANTES",
            "PATTERNS DE CONTRASTE LOURDS",
            "LANGAGE PROCESSUEL",
            "ECHO TECHNIQUE",
        ):
            assert keyword in text, f"missing anti-pattern: {keyword}"

    def test_drafter_prompt_above_cache_floor(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "app" / "prompts" / "templates" / "drafter_system_prompt.txt"
        text = path.read_text(encoding="utf-8")
        approx_tokens = len(text) // 4
        assert approx_tokens > 1024, (
            f"prompt is {approx_tokens} tokens — must stay > 1024 cache floor"
        )


class TestStreamingNonDestructiveDefaultOn:
    """The non-destructive flag flipped to default ON now that the frontend
    handler ships in `useWebSocketSync.ts` + `websocket.ts`."""

    def test_flag_default_on(self):
        import os
        if "STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE" in os.environ:
            pytest.skip("env override active")
        from app.config import STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE
        assert STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE is True

    def test_websocket_event_type_includes_draft_revised(self):
        """Source-level: TS files reference the new event type."""
        from pathlib import Path
        ts_path = Path(__file__).resolve().parents[1] / "agentys-app" / "src" / "services" / "websocket.ts"
        text = ts_path.read_text(encoding="utf-8")
        assert "'draft_revised'" in text or '"draft_revised"' in text
        assert "DraftRevisedData" in text

    def test_useWebSocketSync_handles_draft_revised(self):
        from pathlib import Path
        ts_path = Path(__file__).resolve().parents[1] / "agentys-app" / "src" / "hooks" / "useWebSocketSync.ts"
        text = ts_path.read_text(encoding="utf-8")
        assert "draft_revised" in text
        assert "revision" in text  # the new state field
