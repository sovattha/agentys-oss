# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""BUG-I001 (Session I, 2026-04-26): Action/Info filter tabs returned empty
even though the inbox showed badges for the same labels.

Root cause: ``LabelStore.get_emails_by_label`` consulted the SQL
``email_labels`` table and returned its result *even when empty*. The
dual-write to that table is best-effort (skipped when the email row is
not yet in ``emails``), and the JSON store is the authoritative source
per the file-level docstring.

Fix: when SQL returns 0 rows for a known account, fall through to the
JSON store. The route-layer intersection with the account's actual inbox
prevents cross-account leakage from the global JSON cache (provider IDs
are unique per account namespace).

This test guards against a regression where someone re-tightens the SQL
path to trust ``[]`` as authoritative — which would silently re-break
the filter tabs for any user whose dual-writes have lagged.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.domain.entities.email_labels import LabelAssignment
from app.infrastructure.adapters.label_store import LabelStore


@pytest.fixture
def tmp_label_dir():
    with tempfile.TemporaryDirectory(prefix="agentys-label-i001-") as tmp:
        yield Path(tmp)


def test_falls_back_to_json_when_sql_returns_empty_for_known_account(
    tmp_label_dir,
):
    """Repro: SQL ``email_labels`` empty for account 5, JSON has ``Action``
    on three messages → must return those three IDs, not []."""
    store = LabelStore(storage_dir=str(tmp_label_dir))

    # Seed JSON store with three Action assignments — represents the
    # state right after the auto-classifier ran but before the dual-write
    # caught up (or got skipped because emails rows hadn't landed yet).
    for eid in ("msg-claude", "msg-brevo", "msg-quora"):
        store.save_assignment(
            LabelAssignment(email_id=eid, labels=["Action"])
        )

    class _EmptyResult:
        def fetchall(self):
            return []

        def first(self):
            return None

    class _StubSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            return _EmptyResult()

    with patch(
        "app.db.database.get_db_session",
        side_effect=lambda: _StubSession(),
    ):
        result = store.get_emails_by_label("Action", account_id=5)

    assert set(result) == {"msg-claude", "msg-brevo", "msg-quora"}, (
        "When the SQL row count for an account-scoped label query is 0, "
        "the function MUST fall through to the JSON store (the "
        "authoritative source per the file docstring). Returning [] from "
        "the SQL path causes Action/Info filter tabs to render empty "
        "while the inbox still shows badges from the JSON store — the "
        "exact symptom reported in BUG-I001 (Session I, 2026-04-26). "
        f"Got {result!r}."
    )


def test_unions_sql_and_json_when_both_have_records(tmp_label_dir):
    """Current contract (post-divergence fix): the function unions SQL + JSON
    even when SQL has rows. The docstring in ``label_store.py:480`` explains
    the rationale — SQL is a lossy mirror because ``save_assignment()`` skips
    the SQL write when the corresponding ``emails`` row hasn't synced yet,
    so a label can live in JSON alone for some time.

    The previous contract (SQL-only when SQL has rows) re-introduced the
    "111 counted, 2 listed" divergence between ``/api/labels/counts``
    (reads JSON) and the Action/Info filter tabs (read SQL) that BUG-I001
    was originally meant to fix. Cross-account safety is handled
    downstream by ``get_by_account(email_ids=…)`` which layers an
    ``account_id = :aid`` SQL filter on top — see the docstring at
    ``label_store.py:506-511``.

    This test guards against a regression where someone re-narrows the
    union back to SQL-only when SQL is non-empty.
    """
    store = LabelStore(storage_dir=str(tmp_label_dir))
    # JSON has 2 records that the SQL stub doesn't know about — represents
    # the dual-write lag (label written to JSON, emails row not in SQL yet).
    for eid in ("json-only-1", "json-only-2"):
        store.save_assignment(LabelAssignment(email_id=eid, labels=["Action"]))

    class _SqlResult:
        def fetchall(self):
            return [("sql-msg-1",), ("sql-msg-2",)]

        def first(self):
            return None

    class _StubSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            return _SqlResult()

    with patch(
        "app.db.database.get_db_session",
        side_effect=lambda: _StubSession(),
    ):
        result = store.get_emails_by_label("Action", account_id=42)

    assert set(result) == {
        "sql-msg-1", "sql-msg-2", "json-only-1", "json-only-2",
    }, (
        "Expected the union of SQL and JSON results. SQL alone would miss "
        f"json-only-* (dual-write lag); JSON alone would miss the SQL-only "
        f"records once they sync. Got {result!r}."
    )


def test_valid_email_ids_filter_applied_in_json_fallback(tmp_label_dir):
    """The route layer can pass ``valid_email_ids`` to scope the result
    to the current inbox. The JSON fallback must honour it."""
    store = LabelStore(storage_dir=str(tmp_label_dir))
    for eid in ("inbox-1", "inbox-2", "other-account-msg"):
        store.save_assignment(LabelAssignment(email_id=eid, labels=["Action"]))

    class _EmptyResult:
        def fetchall(self):
            return []

        def first(self):
            return None

    class _StubSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            return _EmptyResult()

    with patch(
        "app.db.database.get_db_session",
        side_effect=lambda: _StubSession(),
    ):
        result = store.get_emails_by_label(
            "Action",
            valid_email_ids={"inbox-1", "inbox-2"},
            account_id=5,
        )

    assert set(result) == {"inbox-1", "inbox-2"}, (
        "JSON fallback must respect the valid_email_ids filter so callers "
        f"can scope to the current inbox. Got {result!r}."
    )
