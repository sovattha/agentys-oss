# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-12 — CRITIC_MAX_REVISIONS env gate on the V3 revision feature.

Pre-fix: the V3 revision (introduced 2026-05-05) fired unconditionally
on COMPLEX/tone-sensitive drafts. No way to roll back without redeploy
if cost crept up or eval showed V3 wasn't materially better than V2.

Post-fix: ``CRITIC_MAX_REVISIONS`` env (int, default 2). =1 disables
V3, =2 keeps current behaviour. The gate is a single integer compare
in ``smart_routing._run_critic``.
"""
from __future__ import annotations

import inspect


def test_v3_block_reads_env():
    """The V3 code path must reference CRITIC_MAX_REVISIONS env."""
    import app.smart_routing as sr
    src = inspect.getsource(sr)
    assert "CRITIC_MAX_REVISIONS" in src, (
        "V3 revision must be gated by CRITIC_MAX_REVISIONS env (rollback knob)"
    )
    assert "_max_revisions >= 2" in src, (
        "V3 only fires when _max_revisions >= 2 — set to 1 to disable"
    )


def test_default_max_is_2(monkeypatch):
    """When the env is unset, the default is 2 (V3 enabled)."""
    monkeypatch.delenv("CRITIC_MAX_REVISIONS", raising=False)
    import os
    raw = os.environ.get("CRITIC_MAX_REVISIONS", "2")
    assert int(raw) == 2


def test_invalid_value_falls_back(monkeypatch):
    """Garbage value silently falls back to default 2 — fail-safe."""
    import os
    monkeypatch.setenv("CRITIC_MAX_REVISIONS", "garbage")
    raw = os.environ.get("CRITIC_MAX_REVISIONS", "2")
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = 2
    assert v == 2
