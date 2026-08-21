# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix — knowledge `_resolve_account_id` must NOT fall back to the first
active tenant (`accounts[0]`) for in-request callers.

Before the fix, when `_resolve_account_id_for_user()` raised inside a request,
`_resolve_account_id` silently returned `accounts[0].id` — the first active
tenant — exposing another user's knowledge base (list/create/patch/delete) in a
multi-tenant request. This mirrors routes_helpers `_get_current_account_for_user`
(ISO C-2, #522): refuse the singleton in request context.

Out-of-request callers (background tasks / CLI) keep the singleton fallback by
construction.

Run: pytest tests/audit_fixes/test_audit_fix_knowledge_fallback.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")

from flask import Flask  # noqa: E402

from app.api import knowledge  # noqa: E402


def _accounts_with_first_tenant():
    """A repo whose get_active_accounts() would yield accounts[0].id == 777."""
    first = MagicMock()
    first.id = 777
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    repo = MagicMock()
    repo.get_active_accounts.return_value = [first]
    return session, repo


def test_resolve_account_id_returns_none_in_request_on_resolver_exception():
    """In-request: resolver raises -> return None (NOT accounts[0].id)."""
    session, repo = _accounts_with_first_tenant()
    app = Flask(__name__)
    with app.test_request_context("/api/knowledge/entries"):
        with patch(
            "app.api.routes_helpers._resolve_account_id_for_user",
            side_effect=RuntimeError("boom"),
        ), patch(
            "app.db.database.get_db_session", return_value=session
        ), patch(
            "app.db.repositories.account_repository.AccountRepository",
            return_value=repo,
        ):
            result = knowledge._resolve_account_id()

    assert result is None  # singleton fallback refused in request context
    repo.get_active_accounts.assert_not_called()  # never even queried the store


def test_resolve_account_id_keeps_singleton_fallback_out_of_request():
    """Out-of-request (background / CLI): resolver raises -> accounts[0].id."""
    session, repo = _accounts_with_first_tenant()
    with patch(
        "app.api.routes_helpers._resolve_account_id_for_user",
        side_effect=RuntimeError("boom"),
    ), patch(
        "app.db.database.get_db_session", return_value=session
    ), patch(
        "app.db.repositories.account_repository.AccountRepository",
        return_value=repo,
    ):
        result = knowledge._resolve_account_id()

    assert result == 777  # trusted singleton fallback preserved outside requests
