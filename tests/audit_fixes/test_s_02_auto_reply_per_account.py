# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix S-02 — `_auto_reply_running` is a module-level bool shared
across all accounts.

Bug: in `app/api/routes_emails.py:153-169`, when account A's inbox fetch
spawns the auto-reply background thread, `_auto_reply_running` flips to
True. Account B's concurrent inbox fetch sees the flag and silently
returns without sending B's vacation replies. With 2+ accounts, only one
account's auto-reply ever fires per overlapping window.

Fix: scope the running flag per `oauth_account_id`.

Run: `pytest tests/audit_fixes/test_s_02_auto_reply_per_account.py -v`
"""

from __future__ import annotations



def test_auto_reply_running_is_per_account():
    """S-02: the "running" guard must be keyed by account, not global.

    We don't actually run the thread (it talks to IMAP). Instead we check
    that the module exposes a per-account dict (or equivalent), and that
    setting one account's flag doesn't gate another's.
    """
    import app.api.routes_emails as re_mod

    # Reset state for a clean test environment.
    if hasattr(re_mod, "_auto_reply_running_per_account"):
        re_mod._auto_reply_running_per_account.clear()

    # The contract for the fixed implementation: there should be a
    # per-account container (dict / set), or the helper should accept the
    # account_id and gate per-key.
    has_per_account_state = (
        hasattr(re_mod, "_auto_reply_running_per_account")
    )
    assert has_per_account_state, (
        "S-02 leak: routes_emails.py still uses a single global "
        "`_auto_reply_running` bool — auto-replies are starved across "
        "multiple accounts."
    )

    # If the per-account container exists, simulate account A's flag set
    # and verify account B's lookup is independent.
    re_mod._auto_reply_running_per_account["account_A"] = True
    assert re_mod._auto_reply_running_per_account.get("account_B", False) is False
