# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 — POST /api/emails/cleanup-all destroyed EVERY tenant's
pending drafts (``get_all(limit=500)`` with no account_id → all tenants, then
REJECTED one by one).

Fix: the purge is scoped to the caller's resolved account_id, so another
tenant's pending / follow-up drafts are never touched.

Run: pytest tests/audit_fixes/test_isolation_2026_05_29_cleanup_all.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

REMOTE = {"REMOTE_ADDR": "203.0.113.10"}
AUTH = {"Authorization": "Bearer tok"}
JWT = {"sub": "1", "email": "accountA@corp.com"}


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


def test_cleanup_all_only_purges_caller_account_drafts(client):
    """Account A (id=1) runs cleanup-all. Account B's (id=2) draft survives."""
    drafts = [
        SimpleNamespace(id="dA", status="PENDING", account_id="1"),
        SimpleNamespace(id="dB", status="PENDING", account_id="2"),
    ]

    store = MagicMock()

    def _get_all(limit=100, account_id=None):
        return [d for d in drafts if account_id is None or str(d.account_id) == str(account_id)]

    store.get_all.side_effect = _get_all
    store.update_status.return_value = True

    container = MagicMock()
    container.get_pending_draft_store.return_value = store

    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_emails._resolve_account_id_cached", return_value=1), \
         patch("app.api.routes_helpers._get_container", return_value=container), \
         patch("app.api.routes_emails._list_all_email_ids_in_folder", return_value=[]), \
         patch("app.api.routes_emails._invalidate_pending_draft_cache"):
        resp = client.post("/api/emails/cleanup-all", headers=AUTH, environ_base=REMOTE)

    assert resp.status_code == 200
    # get_all scoped to the caller's account, NOT the global (account_id=None)
    store.get_all.assert_called_once_with(limit=500, account_id="1")
    # update_status (REJECT) was only ever called for account A's draft
    rejected_ids = [c.args[0] for c in store.update_status.call_args_list]
    assert rejected_ids == ["dA"]
    assert "dB" not in rejected_ids
