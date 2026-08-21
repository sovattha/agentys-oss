# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests — 2026-05-14 deep audit.

F-02 — `_nickname_matches_recipient` must not suppress a legitimate
user-set per-contact nickname on a *weak* signal. The function is a
safety net against stale / cross-contaminated nickname rows (the
2026-05-14 motivating incident: `alexandre.simon@hotmail.com`
carried Nathan's nickname "Nat", poisoning every draft greeting).
But the original loop returned False whenever no local-part token
shared a 3-char prefix with — or was a substring of — the nickname,
which silently discarded a perfectly legitimate nickname for every
initials-style address (nickname "Jean" vs `jdupont@…`). The fix
suppresses ONLY on a strong signal: a multi-token firstname.lastname
local-part where nothing matched. A lone token fails open.

(F-01 — the `STRING_AGG`→`GROUP_CONCAT` revert in `app/api/admin.py` —
is already covered by `tests/api/test_admin_ops_overview.py`, which
seeds an accounts row and exercises the aggregation branch.)
"""
from __future__ import annotations

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

from app.prompts.identity import _nickname_matches_recipient


class TestF02NicknameMatchesRecipient:
    """`_nickname_matches_recipient(nickname, recipient_email) -> bool`.

    True  = nickname is plausibly this recipient's, OR nothing reliable to
            check against (fail open — never silently discard a nickname).
    False = the local-part exposes a STRONG, multi-token name signal and
            none of it relates to the nickname (corrupt-row signal).
    """

    # ── the flagged regression: weak signal must NOT suppress ──────────────
    def test_initials_style_address_keeps_legit_nickname(self):
        """`jdupont` is j+dupont — it cannot spell "Jean", but a lone
        initials-style token is a weak signal, not a corrupt-row signal.
        Returned False before the fix; must return True."""
        assert _nickname_matches_recipient("Jean", "jdupont@gmail.com") is True

    def test_single_token_surname_address_fails_open(self):
        """`asmith` — one token, weak signal → keep the nickname."""
        assert _nickname_matches_recipient("Anna", "asmith@example.com") is True

    # ── the safety net still works on a STRONG signal ─────────────────────
    def test_motivating_incident_still_suppressed(self):
        """`alexandre.simon@hotmail.com` + nickname "Nat" (Nathan's):
        a 2-token firstname.lastname local-part, neither token relates to
        "nat" — the net must still catch this corrupt-row case."""
        assert (
            _nickname_matches_recipient("Nat", "alexandre.simon@hotmail.com")
            is False
        )

    def test_full_name_address_with_unrelated_nickname_suppressed(self):
        """`bob.smith@example.com` + "Jean": 2 tokens, strong signal,
        nothing matches → suppress."""
        assert (
            _nickname_matches_recipient("Jean", "bob.smith@example.com") is False
        )

    # ── matching paths unchanged ──────────────────────────────────────────
    def test_prefix_match_still_accepted(self):
        """Alex <-> Alexandre via the 3-char shared prefix."""
        assert (
            _nickname_matches_recipient("Alex", "alexandre.dupont@x.com") is True
        )

    def test_substring_match_still_accepted(self):
        """`nathanroy` shares a 3-char prefix with "Nat" → accepted."""
        assert (
            _nickname_matches_recipient("Nat", "nathanroy@gmail.com") is True
        )

    def test_handle_style_address_fails_open(self):
        """No name tokens at all (handle-style) → fail open (unchanged)."""
        assert _nickname_matches_recipient("Jean", "0xfastlife@gmx.com") is True

    # ── empty inputs fail open ────────────────────────────────────────────
    def test_empty_nickname_fails_open(self):
        assert _nickname_matches_recipient("", "jdupont@gmail.com") is True

    def test_empty_recipient_fails_open(self):
        assert _nickname_matches_recipient("Jean", "") is True


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
