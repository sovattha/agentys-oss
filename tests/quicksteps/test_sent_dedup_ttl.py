# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression: the in-process sent-side dedup map must stay bounded.

``_sent_quickstep_fired`` gains one ``(sent_id, step_id) -> timestamp``
entry per fired ``firesOn="sent"`` Quick Step. ``_SENT_QUICKSTEP_TTL_SECONDS``
(7 days) was defined but never enforced, so the map grew for the whole
API-process lifetime. The fix prunes expired entries on every send via
``_prune_expired_sent_quickstep_fired``, called from the single sent-side
entry point ``fire_sent_quicksteps_immediate``.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.api import quicksteps_scheduler as qss


@pytest.fixture(autouse=True)
def _clear_dedup_map():
    """The dedup map is a module global — isolate every test from the next."""
    qss._sent_quickstep_fired.clear()
    yield
    qss._sent_quickstep_fired.clear()


def test_prune_evicts_only_expired_entries():
    now = 1_000_000.0
    ttl = qss._SENT_QUICKSTEP_TTL_SECONDS
    qss._sent_quickstep_fired[("old", "step")] = now - ttl - 1      # just expired
    qss._sent_quickstep_fired[("ancient", "step")] = now - ttl * 3  # long expired
    qss._sent_quickstep_fired[("fresh", "step")] = now - 60         # 1 min ago

    qss._prune_expired_sent_quickstep_fired(now=now)

    assert ("fresh", "step") in qss._sent_quickstep_fired
    assert ("old", "step") not in qss._sent_quickstep_fired
    assert ("ancient", "step") not in qss._sent_quickstep_fired


def test_prune_keeps_boundary_entry():
    """An entry exactly at the cutoff (ts == now - TTL) is NOT evicted —
    eviction is strictly older-than, so a fresh fire is never dropped."""
    now = 1_000_000.0
    ttl = qss._SENT_QUICKSTEP_TTL_SECONDS
    qss._sent_quickstep_fired[("edge", "step")] = now - ttl

    qss._prune_expired_sent_quickstep_fired(now=now)

    assert ("edge", "step") in qss._sent_quickstep_fired


def test_prune_is_noop_on_empty_map():
    qss._prune_expired_sent_quickstep_fired(now=1_000_000.0)
    assert qss._sent_quickstep_fired == {}


def test_fire_immediate_prunes_stale_entries():
    """The prune must be WIRED into the hot path: a stale entry present
    when ``fire_sent_quicksteps_immediate`` runs is gone afterward, even
    when the send fires no new steps. This is the test that fails if the
    helper exists but nobody calls it (the actual pre-fix bug)."""
    ttl = qss._SENT_QUICKSTEP_TTL_SECONDS
    qss._sent_quickstep_fired[("sent-OLD", "step-OLD")] = time.time() - ttl - 3600

    sent_email = SimpleNamespace(
        id="sent-NEW", thread_id="t1", recipient="a@b.com",
        subject="s", body_preview="",
    )

    # int account_id resolves without a DB lookup; no steps fire (return []).
    with patch(
        "app.quicksteps.auto_trigger.run_auto_triggers_on_sent",
        return_value=[],
    ) as mock_run:
        qss.fire_sent_quicksteps_immediate(sent_email, 1)

    mock_run.assert_called_once()
    assert ("sent-OLD", "step-OLD") not in qss._sent_quickstep_fired, (
        "fire_sent_quicksteps_immediate must prune expired dedup entries"
    )
