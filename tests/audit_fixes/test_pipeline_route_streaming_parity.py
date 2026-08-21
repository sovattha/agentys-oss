# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix — `route_streaming` parity gaps with `route()`.

Source audit: tasks/audit-reports/2026-04-24_stability/03-draft-pipeline.md
              — rows #22 (refund detection), #23 (correction_details),
              and parity matrix (refund_info, REFUND_PENDING/EXECUTED status).

Pre-fix behavior:
- `route_streaming` ran refund detection but never injected the result into
  `critique_info`, so the UI's refund approval banner was missing for any
  email triggered through `/process` (which uses streaming=True).
- `route_streaming` returned `correction_details=None` (default), so REST-
  triggered drafts had an empty Pipeline transparency card.
- `route_streaming` set status to `STANDARD_STREAMING` even when refund was
  detected, so `sync_service.py` REFUND_PENDING/EXECUTED branches missed
  streaming-generated refunds.

Post-fix behavior:
- `_refund_result_s` is propagated into `critique_info["refund_info"]`.
- Status mirrors `route()`: `REFUND_PENDING` / `REFUND_EXECUTED` win over
  `STANDARD_STREAMING_V2`.
- `_generate_standard_streaming` tracks the pipeline labels and exposes
  them to `route_streaming` via `self._last_streaming_correction_details`.

Status (2026-04-30) — module skipped:
Le commit cbcd54af ("feat: chips compose IA + slim pipeline + self-critique
scaffolding", PR #448) a explicitement *désactivé* les tiers
QUICK_REPLY/REFUND/ACCOUNT/SUBSCRIPTION dans `route()` et `route_streaming()`
("agents conservés, désactivés depuis route()/streaming"). Le contrat
`SI on détecte refund THEN on injecte` testé ici n'a plus d'objet : la
détection est retirée par design. Si la feature refund-streaming est
réactivée plus tard, retirer ce skip pour réinstaurer la garde.
"""
from __future__ import annotations

import inspect

import pytest

from app.smart_routing import SmartRouter

pytestmark = pytest.mark.skip(
    reason=(
        "Tiers REFUND/ACCOUNT/SUBSCRIPTION désactivés dans route_streaming() "
        "par cbcd54af (PR #448). Re-activer ces tests si la feature revient."
    )
)


# --------------------------------------------------------------------------- #
# Source-level checks (pin the contract; cheaper than spinning up the LLM).
# --------------------------------------------------------------------------- #


def test_route_streaming_propagates_refund_info_to_critique_info():
    """`route_streaming` must inject `_refund_result_s.to_dict()` into
    `critique_info["refund_info"]` on the STANDARD branch."""
    src = inspect.getsource(SmartRouter.route_streaming)
    assert 'critique_info["refund_info"]' in src, (
        "DP-22: route_streaming STANDARD branch must inject refund_info "
        "into critique_info; pre-fix the streaming path detected refunds "
        "but silently dropped the result."
    )


def test_route_streaming_returns_refund_status_codes():
    """`route_streaming` must return REFUND_PENDING / REFUND_EXECUTED when
    a refund is detected, not just STANDARD_STREAMING."""
    src = inspect.getsource(SmartRouter.route_streaming)
    assert "REFUND_PENDING" in src, (
        "DP-22: route_streaming must produce REFUND_PENDING status so "
        "sync_service.py can route to the refund flow."
    )
    assert "REFUND_EXECUTED" in src, (
        "DP-22: route_streaming must produce REFUND_EXECUTED status."
    )


def test_route_streaming_plumbs_correction_details():
    """`route_streaming` must propagate correction_details out of
    `_generate_standard_streaming`. Pre-fix it always returned None."""
    src = inspect.getsource(SmartRouter.route_streaming)
    assert "_last_streaming_correction_details" in src, (
        "DP-23: route_streaming must read correction_details that "
        "_generate_standard_streaming stashes on self."
    )


def test_generate_standard_streaming_tracks_correction_labels():
    """`_generate_standard_streaming` must build a list of fired post-LLM
    pipeline labels via a `_track_s` helper, and stash it on self for the
    caller to consume."""
    src = inspect.getsource(SmartRouter._generate_standard_streaming)
    assert "_streaming_corrections" in src, (
        "DP-23: streaming pipeline must track which post-LLM steps fired."
    )
    assert "_track_s" in src, "DP-23: streaming pipeline must use the _track_s helper."
    assert "self._last_streaming_correction_details" in src, (
        "DP-23: streaming pipeline must stash the corrections on self for route_streaming to read."
    )


def test_complex_branch_propagates_refund_info():
    """The COMPLEX streaming branch also must propagate refund_info — the
    audit row #22 calls out that BOTH STANDARD and COMPLEX missed it."""
    src = inspect.getsource(SmartRouter.route_streaming)
    # The COMPLEX branch lives in the same method, so we look for the
    # COMPLEX-side injection (search for the comment we added).
    assert "COMPLEX path too" in src or src.count('critique_info["refund_info"]') >= 2, (
        "DP-22: COMPLEX streaming branch must also inject refund_info. "
        "Without this, COMPLEX-tier streaming drafts miss the banner."
    )


# --------------------------------------------------------------------------- #
# Lightweight functional check on _track_s logic — no LLM, no IO.
# --------------------------------------------------------------------------- #


def test_track_s_increments_correction_list_when_step_changes():
    """Replicate the _track_s helper from _generate_standard_streaming and
    confirm it appends labels only on actual changes."""
    corrections: list[str] = []

    def _track_s(before: str, after: str, label: str) -> str:
        if before != after:
            corrections.append(label)
        return after

    # No-op step
    out = _track_s("Hello", "Hello", "noop")
    assert out == "Hello"
    assert corrections == []

    # Step that mutates
    out = _track_s("hello [TBD]", "hello", "placeholder_removed")
    assert out == "hello"
    assert corrections == ["placeholder_removed"]

    # Multiple steps
    out = _track_s("hello", "Hello.", "auto_capitalize")
    assert corrections == ["placeholder_removed", "auto_capitalize"]
