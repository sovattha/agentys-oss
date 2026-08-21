# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix DP-04 — `/api/drafts/<id>/refine` assigned the bare string ``'modified'``
to ``PendingDraft.status``.

Bug: `routes_drafts.py:646` had
    ``pending_draft.status = 'modified'``

Field type is ``PendingDraftStatus`` enum. The string slips through `add()`
because `to_dict` coerces, but ``get_unsent`` filters by enum tuple:

    unsent_statuses = (
        PendingDraftStatus.PENDING,
        PendingDraftStatus.VALIDATED,
        PendingDraftStatus.MODIFIED,
    )
    unsent = [d for d in self._store.values() if d.status in unsent_statuses ...]

So ``"modified" not in unsent_statuses`` → the refined draft DISAPPEARS from
the list until the JSON round-trip on the next reload.

Fix: assign ``PendingDraftStatus.MODIFIED`` (the enum member).

Run: `pytest tests/audit_fixes/test_pipeline_dp_04_refine_status_enum.py -v`
"""

from __future__ import annotations

import inspect


from app.domain.entities.pending_draft import (
    PendingDraft,
    PendingDraftStatus,
)


# --------------------------------------------------------------------------- #
# DP-04-A: code-level — refine endpoint must assign the enum
# --------------------------------------------------------------------------- #


def test_refine_assigns_pending_draft_status_modified_enum():
    """The refine endpoint must use ``PendingDraftStatus.MODIFIED``, not the
    bare string ``'modified'``."""
    from app.api import routes_drafts

    src = inspect.getsource(routes_drafts.refine_draft_content)

    # Anti-regression: the bare-string assignment must NOT exist.
    assert "pending_draft.status = 'modified'" not in src, (
        "DP-04: status was assigned as a bare string. `get_unsent` filters by "
        "enum tuple, so the refined draft disappears from the list."
    )
    assert 'pending_draft.status = "modified"' not in src, (
        "DP-04: status was assigned as a bare string. `get_unsent` filters by "
        "enum tuple, so the refined draft disappears from the list."
    )

    # Positive: the enum member must be assigned somewhere. We accept either
    # the original symbol `PendingDraftStatus.MODIFIED` or any alias whose
    # right-hand side ends in `.MODIFIED` and is followed by `MODIFIED` on a
    # `pending_draft.status =` line.
    import re
    assignments = re.findall(
        r"pending_draft\.status\s*=\s*([A-Za-z_][A-Za-z_0-9]*)\.MODIFIED",
        src,
    )
    assert assignments, (
        "DP-04: refine endpoint must assign ``<PendingDraftStatus alias>.MODIFIED``. "
        "Source did not contain `pending_draft.status = X.MODIFIED`."
    )


# --------------------------------------------------------------------------- #
# DP-04-B: behavioural — get_unsent must surface MODIFIED drafts
# --------------------------------------------------------------------------- #


def test_get_unsent_returns_modified_drafts_when_status_is_enum():
    """Sanity: confirms the store filter accepts the enum form."""
    from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore

    store = InMemoryPendingDraftStore.__new__(InMemoryPendingDraftStore)
    # Bypass __init__ to avoid disk I/O — manually seed required attrs.
    import threading
    store._store = {}
    store._email_id_index = {}
    store._secure_passwords = {}
    store._lock = threading.RLock()
    store._save_to_disk = lambda: None  # no-op
    store._reload_if_changed = lambda: None  # no-op

    pd = PendingDraft(
        id="d1",
        email_id="m1",
        draft_body="x",
        status=PendingDraftStatus.MODIFIED,
    )
    store._store[pd.id] = pd
    store._email_id_index[pd.email_id] = pd.id

    out = store.get_unsent()
    assert len(out) == 1, (
        "Sanity: get_unsent must include MODIFIED drafts when status is an enum."
    )


def test_get_unsent_drops_modified_draft_when_status_is_bare_string():
    """Reproduction: pre-fix, a refined draft was hidden because its status was
    the bare string 'modified', not the enum.
    """
    from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore

    store = InMemoryPendingDraftStore.__new__(InMemoryPendingDraftStore)
    import threading
    store._store = {}
    store._email_id_index = {}
    store._secure_passwords = {}
    store._lock = threading.RLock()
    store._save_to_disk = lambda: None
    store._reload_if_changed = lambda: None

    pd = PendingDraft(
        id="d-string",
        email_id="m1",
        draft_body="x",
    )
    # Simulate the BAD pre-fix assignment
    pd.status = "modified"  # type: ignore[assignment]

    store._store[pd.id] = pd
    store._email_id_index[pd.email_id] = pd.id

    out = store.get_unsent()
    assert len(out) == 0, (
        "Repro: pre-fix bug — bare-string 'modified' is excluded from the "
        "enum-tuple filter, so the refined draft vanishes from the list."
    )
