# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-19 STAB-01 regression: POST /api/pending-drafts/purge-all must
TERMINATE even when `get_pending` keeps returning the same non-empty batch
(e.g. update_status no-ops, or a concurrent writer re-injects PENDING rows).

Before the fix the delete loop was an unbounded `while True` whose only exit was
an empty batch — under those conditions the Flask worker spun forever (livelock,
uncatchable by the surrounding try/except). The fix tracks already-attempted ids
in a `seen` set (forward progress) plus a hard MAX_PURGE_PASSES backstop.

pytest tests/api/test_purge_all_loop_bound.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask


@pytest.fixture
def client():
    from app.api.routes_helpers import api_bp
    import app.api.routes_pending  # noqa: F401 — registers the purge-all route

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api_bp, url_prefix="/api")
    return app.test_client()


def test_purge_all_terminates_when_get_pending_never_empties(client, monkeypatch):
    """The pathological case: get_pending ALWAYS returns the same draft (as it
    would if a concurrent producer keeps the PENDING set non-empty). The loop
    must still return, in a bounded number of get_pending calls."""
    same_draft = SimpleNamespace(id="draft-stuck-1")

    store = MagicMock()
    # Always hand back the same one-draft batch — never empties.
    store.get_pending.return_value = [same_draft]
    store.update_status.return_value = True

    container = MagicMock()
    container.get_pending_draft_store.return_value = store

    monkeypatch.setattr("app.api.routes_helpers._get_container", lambda: container)
    monkeypatch.setattr(
        "app.api.routes_pending._resolve_account_id_cached", lambda: 7
    )

    resp = client.post("/api/pending-drafts/purge-all")

    assert resp.status_code == 200
    body = resp.get_json()
    # The draft is attempted exactly once (deduped via the `seen` set).
    assert body["deleted_count"] == 1
    # Forward progress: pass 1 processes the draft, pass 2 sees it's already
    # `seen` → fresh==[] → break. So get_pending is called exactly twice, never
    # spinning toward the MAX_PURGE_PASSES backstop.
    assert store.get_pending.call_count == 2
    # And update_status fired only once for the single unique draft.
    assert store.update_status.call_count == 1


def test_purge_all_count_only_unaffected(client, monkeypatch):
    """Sanity: the count_only peek path still works and doesn't mutate."""
    store = MagicMock()
    store.get_pending.return_value = [SimpleNamespace(id=f"d{i}") for i in range(3)]
    container = MagicMock()
    container.get_pending_draft_store.return_value = store
    monkeypatch.setattr("app.api.routes_helpers._get_container", lambda: container)
    monkeypatch.setattr(
        "app.api.routes_pending._resolve_account_id_cached", lambda: 7
    )

    resp = client.post("/api/pending-drafts/purge-all?count_only=true")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == 3
    assert body["will_be_async"] is False
    store.update_status.assert_not_called()
