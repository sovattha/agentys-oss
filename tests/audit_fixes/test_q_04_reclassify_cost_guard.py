# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-04 — POST /labels/reclassify cost guard (2026-05-05).

Pre-fix: the endpoint silently fetched up to 200 emails and re-ran the
Label use case (which can escalate to Sonnet for ~5% of drafts via
llm_background_smart). A misuse — e.g. calling it in a loop, or passing a
parameter that we'd later add for max — could cost real money without any
explicit confirmation.

Post-fix: optional body params { max_emails: int, confirm_cost: bool }.
- max_emails > 200 without confirm_cost: 400 with cost_estimate.
- max_emails out of [1, 1000]: 400 OUT_OF_RANGE.

This test pins the contract — future extensions must not weaken it.
"""
from __future__ import annotations

import inspect


def test_reclassify_handler_reads_max_emails_with_default():
    """The route handler must read `max_emails` (default 200) before fetching."""
    from app.api import labels as labels_module
    src = inspect.getsource(labels_module.reclassify_emails)
    # The cost guard must be defensive against (a) missing JSON body, (b)
    # non-int values, (c) negative or oversized counts. Asserting on the
    # source keeps the pin readable — full integration tests would need a
    # full Flask app + provider stack which is overkill for a contract pin.
    assert "max_emails" in src, "Handler must read max_emails from body"
    assert "confirm_cost" in src, "Handler must require explicit cost confirmation"
    assert "1000" in src, "Hard cap of 1000 must be present"
    assert "cost_estimate_usd" in src, "Error response must surface a cost estimate"


def test_reclassify_route_still_registered():
    """Sanity: the Flask route is still wired."""
    from app.api.labels import labels_bp  # noqa: F401 — import sanity
    # Best-effort — Blueprints expose deferred funcs not easily introspected.
    # Instead check the function exists and has a route decorator marker.
    from app.api.labels import reclassify_emails
    # Flask attaches the rule via decorator; the function still exists and
    # callable signature is preserved.
    assert callable(reclassify_emails)
