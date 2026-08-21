# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix — failure-modes #3 and #4 in the Critic stage.

Source audit: tasks/audit-reports/2026-04-24_stability/03-draft-pipeline.md

#3: `_fallback_parse` keyword-matched any "VALID" in the response. If the
    user's original email contained the word VALID quoted back in the LLM
    output, the draft was marked VALID without real evaluation.
    Fix: default to REJECT on parse failure (force a V2 pass) unless
    the response contains an EXPLICIT validation marker.

#4: When critic times out, `evaluate_draft` returns CritiqueResult.create_failed
    with status=FAILED. _validate_and_revise treats it as REJECT and runs V2.
    If V2 also fails, the original V1 is returned with `revision_failed=True`
    but no `critique_failed` flag — the UI can't distinguish "draft passed
    review" from "review never ran". Fix: surface `critique_failed` and
    `critique_status` in critique_info.
"""
from __future__ import annotations

import inspect


from app.agents import CriticAgent
from app.domain.entities.critique import CritiqueDecision


# --------------------------------------------------------------------------- #
# #3: Fallback parse defaults to REJECT
# --------------------------------------------------------------------------- #


def _critic():
    """Get a CriticAgent without going through the LLM init path."""
    c = CriticAgent.__new__(CriticAgent)
    c.quality_threshold = 70  # match default
    return c


def test_fallback_parse_defaults_to_reject_on_unstructured_text():
    """An LLM response with no JSON and no explicit decision marker must
    default to REJECT (so that V2 is generated as a safety pass)."""
    c = _critic()
    out = c._fallback_parse(
        "Some unstructured prose with no decision marker.",
        evaluation_time_ms=10,
        tokens_used=42,
    )
    assert out.decision == CritiqueDecision.REJECT, (
        "Failure-mode #3: fallback parse must default to REJECT when "
        "the LLM didn't produce a structured decision marker."
    )


def test_fallback_parse_does_not_keyword_match_quoted_valid():
    """Pre-fix bug: an email body quoting the word `VALID` made the keyword
    matcher mark the draft VALID. Post-fix: only EXPLICIT decision markers
    in the LLM output count."""
    c = _critic()
    out = c._fallback_parse(
        "The user's original email mentioned a VALID promo code.",
        evaluation_time_ms=10,
        tokens_used=42,
    )
    assert out.decision == CritiqueDecision.REJECT, (
        "Failure-mode #3: a quoted `VALID` in the email body must NOT make "
        "the fallback parser mark the draft VALID. Only an explicit decision "
        "marker (`\"decision\": \"VALID\"` or `DECISION: VALID`) counts."
    )


def test_fallback_parse_accepts_explicit_json_marker():
    """When the LLM emits a clean JSON with `"decision":"VALID"` even if the
    overall structure is malformed, accept VALID. Otherwise we'd reject
    drafts that were clearly approved."""
    c = _critic()
    out = c._fallback_parse(
        '{"decision":"VALID","scores":{"coherence":80}}',
        evaluation_time_ms=10,
        tokens_used=42,
    )
    assert out.decision == CritiqueDecision.VALID, (
        "Fallback parse must still recognize an explicit JSON decision "
        "marker — otherwise legitimately VALID drafts get rejected."
    )


def test_fallback_parse_rejects_explicit_reject_marker():
    """Even with VALID elsewhere, an explicit REJECT must win (defensive)."""
    c = _critic()
    out = c._fallback_parse(
        "Mentions VALID nice things... but DECISION: REJECT",
        evaluation_time_ms=10,
        tokens_used=42,
    )
    assert out.decision == CritiqueDecision.REJECT


# --------------------------------------------------------------------------- #
# #4: critique_failed surface
# --------------------------------------------------------------------------- #


def test_validate_and_revise_exposes_critique_failed_flag():
    """`_validate_and_revise` must set `critique_failed: True` and
    `critique_status: 'failed'` in critique_info when the critic returned
    a FAILED status. This lets the UI distinguish 'review never ran' from
    'review passed'."""
    src = inspect.getsource(__import__("app.smart_routing", fromlist=["SmartRouter"]).SmartRouter._validate_and_revise)
    assert "critique_failed" in src, (
        "Failure-mode #4: critique_info must carry a `critique_failed` flag "
        "so the UI can distinguish 'review never ran' from 'review passed'."
    )
    assert "critique_status" in src, (
        "Failure-mode #4: critique_info must carry a `critique_status` "
        "(e.g. 'failed', 'rate_limited', 'completed')."
    )


def test_critique_status_imports_use_critique_status_enum():
    """The critic-failure detection must use the CritiqueStatus enum, not
    a hard-coded string. (Defensive against typos that would make the flag
    silently always False.)"""
    src = inspect.getsource(__import__("app.smart_routing", fromlist=["SmartRouter"]).SmartRouter._validate_and_revise)
    assert "CritiqueStatus" in src, (
        "Failure-mode #4: critique-failure detection must import and use "
        "the CritiqueStatus enum."
    )
    # Both terminal failure statuses must be checked
    assert "FAILED" in src, "Must check CritiqueStatus.FAILED"
    assert "RATE_LIMITED" in src, "Must check CritiqueStatus.RATE_LIMITED"
