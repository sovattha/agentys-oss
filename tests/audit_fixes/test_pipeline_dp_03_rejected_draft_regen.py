# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix DP-03 — `batch_queue.py` bypassed the rejected-draft regen guard.

Bug: `batch_queue.py:603` (`_save_draft`) and `batch_queue.py:701`
(`_fallback_realtime`) used `pending_store.get_by_email_id(email_id)` which
EXCLUDES rejected drafts. So when a user explicitly rejected a draft and the
email was later re-queued (relabel, batch retry), a fresh draft was saved on
top — silently overriding the user's rejection.

The daemon path uses `get_by_email_id_including_rejected` for this reason.

Fix: switch both call sites to `get_by_email_id_including_rejected` AND
short-circuit when status == REJECTED so we don't even produce a new draft.

Run: `pytest tests/audit_fixes/test_pipeline_dp_03_rejected_draft_regen.py -v`
"""

from __future__ import annotations

import inspect


from app.domain.entities.pending_draft import (
    PendingDraft,
    PendingDraftStatus,
)


# --------------------------------------------------------------------------- #
# DP-03 — code-level: batch_queue is no longer using the broken accessor
# --------------------------------------------------------------------------- #


def test_batch_queue_save_draft_uses_including_rejected_accessor():
    """`_save_draft` must call `get_by_email_id_including_rejected`, not the
    plain accessor that drops REJECTED.
    """
    from app.batch_queue import BatchWorker

    src = inspect.getsource(BatchWorker._save_draft)

    assert "get_by_email_id_including_rejected" in src, (
        "DP-03: BatchWorker._save_draft must use get_by_email_id_including_rejected "
        "to preserve user's rejection. The plain `get_by_email_id` excludes "
        "REJECTED, allowing a silent override."
    )


def test_batch_queue_fallback_realtime_uses_including_rejected_accessor():
    """Same thing for `_fallback_realtime`."""
    from app.batch_queue import BatchWorker

    src = inspect.getsource(BatchWorker._fallback_realtime)

    assert "get_by_email_id_including_rejected" in src, (
        "DP-03: BatchWorker._fallback_realtime must also use the rejection-aware "
        "accessor — same hole, different code path."
    )


# --------------------------------------------------------------------------- #
# DP-03 — behavioural: a rejected draft survives a batch fallback
# --------------------------------------------------------------------------- #


def test_batch_fallback_does_not_regenerate_after_user_rejection():
    """End-to-end behavioural test:
      1. User rejects a draft (REJECTED status).
      2. Batch fallback fires for the same email_id.
      3. The rejected draft must remain rejected — no new save happens.
    """
    from app.batch_queue import BatchWorker

    rejected = PendingDraft(
        id="rejected-1",
        email_id="msg-99",
        draft_body="[old draft]",
        status=PendingDraftStatus.REJECTED,
    )

    # In-memory stub store
    saved: list = []

    class _StubStore:
        def __init__(self):
            self._by_email_id_including_rejected = {"msg-99": rejected}

        def get_by_email_id_including_rejected(self, email_id):
            return self._by_email_id_including_rejected.get(email_id)

        def get_by_email_id(self, email_id):
            # Pre-fix path — used by older code; kept here to verify the test
            # would FAIL on pre-fix code.
            d = self._by_email_id_including_rejected.get(email_id)
            if d and d.status == PendingDraftStatus.REJECTED:
                return None
            return d

        def add(self, draft):
            saved.append(draft)
            return draft.id

    store = _StubStore()

    # Stub the container.get_pending_draft_store
    from types import SimpleNamespace
    from unittest.mock import patch

    fake_container = SimpleNamespace(get_pending_draft_store=lambda: store)

    item = {
        "email_id": "msg-99",
        "tier": "fallback",
        "metadata": '{"sender": "x@y.com", "subject": "Re: x", "body": "y"}',
    }

    # Bypass __init__ to avoid SQLite setup
    worker = BatchWorker.__new__(BatchWorker)

    with patch("app.infrastructure.container.get_container", return_value=fake_container):
        # _fallback_realtime would call SmartRouter to generate, but our short-
        # circuit must trigger BEFORE that. We verify by patching SmartRouter
        # to assert it's never called.
        with patch("app.smart_routing.SmartRouter") as mock_router_cls:
            mock_router_cls.return_value.route.return_value = (
                # Sanity payload — should never be reached if short-circuit works
                None
            )
            worker._fallback_realtime(item)

            # The router must NOT have generated a fresh draft for a rejected email
            assert not mock_router_cls.return_value.route.called, (
                "DP-03: SmartRouter.route was called even though the email had "
                "a REJECTED PendingDraft. The user's rejection was silently "
                "overridden."
            )

    # No new draft was added either
    assert saved == [], (
        f"DP-03: a new draft was saved on top of a rejected one: {saved}"
    )
