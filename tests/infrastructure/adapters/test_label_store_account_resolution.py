# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression: ``LabelStore.get_emails_by_label`` must translate the
multi-account hash id (e.g. ``f9057edfed0d4574``) into the SQL integer
``account_id`` before querying ``email_labels``.

Bug observed 2026-04-25 on a secondary Gmail account:
  * 42 Noise rows existed in ``email_labels`` with ``account_id=5``.
  * The old code consulted ``AccountManager.get_current_account().id``
    directly and produced the string hash ``f9057edfed0d4574`` for the
    WHERE clause.
  * SQLite happily compared INT 5 to the string hash and returned no rows,
    so the Noise tab rendered "No 'Noise' email" while a different code
    path counted the same labels for the badge — the two were silently
    desynced.

The fix re-resolves the hash via the email column on the accounts table
and casts to int. This test asserts the lookup chain is wired through to
that resolver instead of dereferencing ``.id`` directly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.infrastructure.adapters.label_store import LabelStore


@pytest.fixture
def tmp_label_dir():
    with tempfile.TemporaryDirectory(prefix="agentys-label-acct-") as tmp:
        yield Path(tmp)


def test_get_emails_by_label_resolves_hash_to_int_via_accounts_table(
    tmp_label_dir,
):
    """Hash id ``f9057edfed0d4574`` must be turned into INT 5 by querying
    the accounts table on email — never passed straight into the WHERE."""
    store = LabelStore(storage_dir=str(tmp_label_dir))

    captured: dict[str, object] = {}

    class _StubAccount:
        id = "f9057edfed0d4574"
        email = "cours.universite@gmail.com"

    class _StubManager:
        def get_current_account(self):
            return _StubAccount()

    class _StubResult:
        def __init__(self, row):
            self._row = row

        def first(self):
            return self._row

        def fetchall(self):
            return [("msg-after-fix",)]

    class _StubSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            sql = str(stmt)
            captured.setdefault("queries", []).append((sql, params))
            if "FROM accounts" in sql:
                # Resolver lookup: hash → INT
                return _StubResult((5,))
            if "FROM email_labels" in sql:
                # Final read: must receive the INT, not the hash
                captured["account_id_used"] = params.get("aid")
                return _StubResult(None)
            return _StubResult(None)

    def _stub_session_factory():
        return _StubSession()

    with patch(
        "app.multi_accounts.get_account_manager",
        return_value=_StubManager(),
    ), patch(
        "app.db.database.get_db_session",
        side_effect=_stub_session_factory,
    ):
        store.get_emails_by_label("Noise")

    assert captured.get("account_id_used") == 5, (
        "The email_labels SELECT must use the INT account_id resolved "
        "from the accounts table, not the multi-account hash. "
        f"Got {captured.get('account_id_used')!r}."
    )

    queries = captured.get("queries", [])
    assert any("FROM accounts" in q[0] for q in queries), (
        "The hash must be resolved via SELECT FROM accounts WHERE email="
        " — that step is what stops the SQL hash/INT comparison from "
        "silently returning empty results."
    )


def test_get_emails_by_label_explicit_account_id_wins_over_singleton(
    tmp_label_dir,
):
    """The explicit ``account_id=`` argument must always override the
    process-global current account. On a multi-user deployment, the
    singleton reflects whoever activated last across all sessions; if a
    request handler has already resolved the caller's INT id, that value
    is the source of truth and must be honoured verbatim — never
    re-derived from the singleton.

    Regression for the 2026-04-25 bug: routes_emails.list_emails resolves
    ``account_id = _resolve_account_id_for_email(current.email)`` from
    the JWT user, but the original LabelStore code ignored that and read
    ``get_account_manager().get_current_account()`` instead, producing
    another user's IDs whenever they were the last to activate."""
    store = LabelStore(storage_dir=str(tmp_label_dir))

    captured: dict[str, object] = {}

    class _StubResult:
        def fetchall(self):
            return [("explicit-id-msg",)]

        def first(self):
            return None

    class _StubSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            captured["params"] = params
            captured["sql"] = str(stmt)
            return _StubResult()

    class _SingletonAccount:
        # The "wrong" account: another user happened to activate last.
        id = "ffffffffffffffff"
        email = "intruder@example.com"

    class _SingletonManager:
        def get_current_account(self):
            captured["singleton_consulted"] = True
            return _SingletonAccount()

    with patch(
        "app.multi_accounts.get_account_manager",
        return_value=_SingletonManager(),
    ), patch(
        "app.db.database.get_db_session",
        side_effect=lambda: _StubSession(),
    ):
        store.get_emails_by_label("Noise", account_id=5)

    assert captured.get("params", {}).get("aid") == 5, (
        "When account_id=5 is passed explicitly, the SQL WHERE clause "
        "must receive 5, not whatever the global singleton currently "
        f"holds. Got params={captured.get('params')!r}."
    )
    assert "singleton_consulted" not in captured, (
        "Explicit account_id must short-circuit the singleton lookup so "
        "we never fall back to the wrong user on a multi-user deployment."
    )


def test_get_emails_by_label_falls_back_to_json_when_resolution_fails(
    tmp_label_dir,
):
    """If the account row can't be resolved (boot-time, tests, deleted
    user), the function must still fall back to the JSON cache instead of
    silently returning an empty list — which is what masked the bug."""
    from app.domain.entities.email_labels import LabelAssignment

    store = LabelStore(storage_dir=str(tmp_label_dir))
    store.save_assignment(
        LabelAssignment(email_id="orphan-msg-1", labels=["Noise"])
    )

    class _StubAccount:
        id = "0000000000000000"
        email = "ghost@example.com"

    class _StubManager:
        def get_current_account(self):
            return _StubAccount()

    class _Empty:
        def first(self):
            return None

    class _StubSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **kw):
            return _Empty()

    with patch(
        "app.multi_accounts.get_account_manager",
        return_value=_StubManager(),
    ), patch(
        "app.db.database.get_db_session",
        side_effect=lambda: _StubSession(),
    ):
        result = store.get_emails_by_label("Noise")

    assert "orphan-msg-1" in result, (
        "When the hash id resolves to no accounts row, the function must "
        "fall through to the JSON cache rather than return [] — that "
        f"silent empty was the original bug. Got {result!r}."
    )
