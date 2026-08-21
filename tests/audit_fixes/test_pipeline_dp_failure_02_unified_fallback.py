# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix DP-failure-mode #2 — `DrafterAgent.draft_unified` fallback returned garbage.

Bug: when Claude returned a malformed response (e.g. JSON parse error), the
fallback at `app/agents.py:466-475` returned ``{"draft": raw}`` directly —
including raw markdown reasoning, JSON-with-typos, or empty strings.
`_strip_clarification_draft` doesn't catch these, so the user saw a
PendingDraft containing JSON braces or reasoning.

Fix: validate the raw fallback content. Reject empty strings AND content
that LOOKS like JSON (starts/ends with braces, contains `"draft":` keys).
Surface as ``UNIFIED_FALLBACK_EMPTY`` so upstream code skips persisting.

Run: `pytest tests/audit_fixes/test_pipeline_dp_failure_02_unified_fallback.py -v`
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock



def _build_drafter():
    """Build a DrafterAgent with stubbed LLM/dependencies."""
    from app.agents import DrafterAgent

    drafter = DrafterAgent.__new__(DrafterAgent)
    # Hand-set required attrs (skip __init__ which loads KB/style)
    drafter._llm = MagicMock()
    drafter.max_tokens = 800
    drafter.knowledge_base = ""
    return drafter


def _stub_llm_response(drafter, raw_content: str):
    fake_resp = MagicMock()
    fake_resp.content = raw_content
    fake_resp.usage_input_tokens = 100
    fake_resp.usage_output_tokens = 50
    drafter._llm.complete.return_value = fake_resp


# --------------------------------------------------------------------------- #
# Reproduce: malformed JSON → previously persisted garbage; now rejected
# --------------------------------------------------------------------------- #


def test_unified_fallback_rejects_empty_raw():
    """If Claude returned empty content, status must be UNIFIED_FALLBACK_EMPTY."""
    drafter = _build_drafter()
    _stub_llm_response(drafter, "")

    with patch("app.agents._track_token_usage", return_value=None):
        result = drafter.draft_unified(email_content="Hello!")
    assert result["status"] == "UNIFIED_FALLBACK_EMPTY", (
        f"Expected UNIFIED_FALLBACK_EMPTY for empty raw, got {result['status']!r}"
    )
    assert result["draft"] == ""


def test_unified_fallback_rejects_json_garbage():
    """If Claude emitted broken JSON like `{"draf` (parse fails) — must reject."""
    drafter = _build_drafter()
    _stub_llm_response(drafter, '{"draf')

    with patch("app.agents._track_token_usage", return_value=None):
        result = drafter.draft_unified(email_content="Hello!")

    assert result["status"] == "UNIFIED_FALLBACK_EMPTY"
    assert result["draft"] == ""


def test_unified_fallback_rejects_full_json_no_draft_key():
    """If Claude emitted JSON without a `draft` key, the regular path doesn't
    return; the fallback must reject it instead of dumping the JSON to the
    user as the draft body.
    """
    drafter = _build_drafter()
    # Valid JSON but missing the `draft` field — falls through to fallback
    _stub_llm_response(drafter, '{"classification":"Action","priority":50}')

    with patch("app.agents._track_token_usage", return_value=None):
        result = drafter.draft_unified(email_content="Hello!")

    assert result["status"] == "UNIFIED_FALLBACK_EMPTY", (
        f"Got {result['status']!r}, draft={result['draft']!r}"
    )


def test_unified_fallback_accepts_plain_text_response():
    """Sanity: when Claude emits a plain-text reply (no JSON wrapping), the
    fallback should still succeed (use the raw text as the draft)."""
    drafter = _build_drafter()
    _stub_llm_response(drafter, "Hi Alice,\n\nGreat, I'll see you tomorrow.\n\nBest,\nBob")

    with patch("app.agents._track_token_usage", return_value=None):
        result = drafter.draft_unified(email_content="Hello!")

    assert result["status"] == "UNIFIED_FALLBACK"
    assert "Hi Alice" in result["draft"]
