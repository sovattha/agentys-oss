# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Unit tests for the per-account pinned-email helpers.

Mocks ``get_db_session`` with a fake Account so the JSON-list mutation and
the idempotency rules are exercised without a real database.
"""
import json
from contextlib import contextmanager
from unittest.mock import patch

from app.services.pinned_emails import add_pinned_email_id, remove_pinned_email_id


class _FakeAccount:
    def __init__(self, raw=None):
        self.pinned_email_ids_json = raw


class _FakeSession:
    def __init__(self, account):
        self._account = account

    def get(self, _model, _pk):
        return self._account


def _patch_db(account):
    @contextmanager
    def _cm():
        yield _FakeSession(account)
    # Helper imports get_db_session from app.db.database at call time.
    return patch("app.db.database.get_db_session", _cm)


class TestAddPinned:
    def test_adds_to_empty_list(self):
        acct = _FakeAccount(None)
        with _patch_db(acct):
            assert add_pinned_email_id(42, "thread-9") is True
        assert json.loads(acct.pinned_email_ids_json) == ["thread-9"]

    def test_appends_preserving_existing(self):
        acct = _FakeAccount('["a"]')
        with _patch_db(acct):
            assert add_pinned_email_id(42, "b") is True
        assert json.loads(acct.pinned_email_ids_json) == ["a", "b"]

    def test_idempotent_when_already_pinned(self):
        acct = _FakeAccount('["b"]')
        with _patch_db(acct):
            assert add_pinned_email_id(42, "b") is False
        assert json.loads(acct.pinned_email_ids_json) == ["b"]

    def test_malformed_json_treated_as_empty(self):
        acct = _FakeAccount("not json{")
        with _patch_db(acct):
            assert add_pinned_email_id(42, "x") is True
        assert json.loads(acct.pinned_email_ids_json) == ["x"]

    def test_missing_account_returns_false(self):
        with _patch_db(None):
            assert add_pinned_email_id(42, "x") is False

    def test_empty_inputs_are_noops(self):
        # No DB touch when inputs are empty.
        assert add_pinned_email_id(0, "x") is False
        assert add_pinned_email_id(42, "") is False


class TestRemovePinned:
    def test_removes_present_id(self):
        acct = _FakeAccount('["a", "b", "c"]')
        with _patch_db(acct):
            assert remove_pinned_email_id(42, "b") is True
        assert json.loads(acct.pinned_email_ids_json) == ["a", "c"]

    def test_idempotent_when_absent(self):
        acct = _FakeAccount('["a"]')
        with _patch_db(acct):
            assert remove_pinned_email_id(42, "b") is False
        assert json.loads(acct.pinned_email_ids_json) == ["a"]

    def test_missing_account_returns_false(self):
        with _patch_db(None):
            assert remove_pinned_email_id(42, "x") is False

    def test_empty_inputs_are_noops(self):
        assert remove_pinned_email_id(0, "x") is False
        assert remove_pinned_email_id(42, "") is False


class TestConcurrentPinNoLostUpdate:
    """Regression (chaos audit 2026-06-02): the read-modify-write on the JSON
    array had no lock, so concurrent pins dropped each other (last-writer-wins).
    `_pin_lock` now serializes the RMW. The fake account's getter has a tiny
    delay to WIDEN the RMW window so a missing lock would lose updates here."""

    def test_concurrent_adds_are_all_retained(self):
        import threading
        import time

        class _RacyAccount:
            def __init__(self):
                self._raw = "[]"

            @property
            def pinned_email_ids_json(self):
                time.sleep(0.001)  # widen read→write window
                return self._raw

            @pinned_email_ids_json.setter
            def pinned_email_ids_json(self, v):
                self._raw = v

        acct = _RacyAccount()

        @contextmanager
        def _cm():
            yield _FakeSession(acct)

        n = 40
        # Hoist the patch OUTSIDE the threads (mock.patch is not thread-safe;
        # LIFO restore from inside threads pollutes globally).
        with patch("app.db.database.get_db_session", _cm):
            threads = [
                threading.Thread(target=add_pinned_email_id, args=(42, f"id-{i}"))
                for i in range(n)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        ids = json.loads(acct._raw)
        assert len(ids) == n  # no lost updates
        assert set(ids) == {f"id-{i}" for i in range(n)}
