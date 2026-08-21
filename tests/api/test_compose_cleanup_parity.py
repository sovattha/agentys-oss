# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression (chaos audit 2026-06-02, differential lens).

The three compose code paths — legacy blocking (`compose_email`),
DraftService blocking (`_compose_email_via_service`) and streaming
(`_compose_stream_bg`) — hand-maintained three copies of the post-LLM cleanup
pipeline that drifted: `strip_reasoning_leakage` was missing from ALL three and
the structural-placeholder scrub from the two blocking ones, so a leaked
chain-of-thought line or a trailing "Reply body," placeholder could ship in a
composed email (the reply/refine paths stripped both). They now share one
helper, `_apply_compose_body_cleanup`. These tests pin (1) the helper applies
both strips, and (2) all three paths route through it so they can't diverge
again.
"""

from __future__ import annotations

import inspect

from app.api import routes_misc
from app.api.routes_misc import _apply_compose_body_cleanup


class TestComposeCleanupHelper:
    def test_strips_reasoning_leak_and_structural_placeholder(self):
        body = (
            "Je dois adopter un ton formel:\n"
            "[Reply body]\n"
            "Bonjour Madame Dupont,\n\n"
            "Je vous confirme la réception de votre dossier."
        )
        out = _apply_compose_body_cleanup(body, typical_signature=None)
        # chain-of-thought meta-narration gone
        assert "Je dois adopter" not in out
        # structural placeholder line gone
        assert "Reply body" not in out and "[Reply body]" not in out
        # real content preserved
        assert "Je vous confirme la réception de votre dossier" in out

    def test_normal_body_preserved(self):
        body = (
            "Bonjour Alex,\n\n"
            "Merci pour ton message. Je te réponds demain matin."
        )
        out = _apply_compose_body_cleanup(body, typical_signature=None)
        assert "Merci pour ton message" in out
        assert "Je te réponds demain matin" in out

    def test_empty_body_is_safe(self):
        assert _apply_compose_body_cleanup("", None) == ""


class TestAllComposePathsShareCleanup:
    """Guards the divergence from re-appearing: every compose path must route
    through the shared helper rather than re-inlining its own pipeline."""

    def test_each_compose_path_calls_the_shared_helper(self):
        for fn in (
            routes_misc.compose_email,
            routes_misc._compose_email_via_service,
            routes_misc._compose_stream_bg,
        ):
            src = inspect.getsource(fn)
            assert "_apply_compose_body_cleanup" in src, (
                f"{fn.__name__} must route through _apply_compose_body_cleanup "
                f"(chaos audit 2026-06-02 compose cleanup parity)."
            )
