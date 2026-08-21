# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for app.quicksteps.store — DB load/save and pure list helpers."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.db.repositories.account_repository import AccountRepository
from app.quicksteps import store


@pytest.fixture
def db_engine_with_account(engine, sample_account):
    """Bind the sample_account session's engine so `with get_db_session()`
    in store.py reuses the same in-memory DB."""

    @event.listens_for(engine, "begin")
    def _noop(_):
        pass

    SessionLocal = sessionmaker(bind=engine, autoflush=False)

    def _fake_session_cm():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    from contextlib import contextmanager
    cm = contextmanager(_fake_session_cm)

    with patch("app.quicksteps.store.get_db_session", cm):
        yield engine, sample_account.id


class TestLoadSave:
    def test_first_load_seeds_starter_pack_auto_ready_but_disabled(self, db_engine_with_account):
        """First load on an account that has never had Quick Steps seeds
        the starter pack (cf. ``app/quicksteps/defaults.py``). All starters
        ship disabled, with automatic mode preselected, so they're inert
        until the user opts in. Replaces the old "returns ``[]`` when unset"
        contract which was relaxed when starter-pack seeding shipped."""
        _, account_id = db_engine_with_account
        loaded = store.load_quick_steps(account_id)
        assert len(loaded) > 0, "first load must seed the starter pack"
        for rule in loaded:
            assert rule["autoEnabled"] is True, (
                f"Starter rule {rule['name']!r} was not seeded in AUTO mode. "
                "Starter rules should be ready to run automatically once enabled."
            )
            assert rule["enabled"] is False, (
                f"Starter rule {rule['name']!r} was seeded enabled. Starter "
                "rules must stay off in Settings until the user enables them."
            )
        # Second load is a no-op (JSON is now non-NULL — preserved as-is).
        again = store.load_quick_steps(account_id)
        assert len(again) == len(loaded)

    def test_save_then_load_roundtrip(self, db_engine_with_account):
        _, account_id = db_engine_with_account
        steps = [
            {"id": "11111111-1111-4111-8111-111111111111", "name": "Archive", "actions": [{"type": "archive"}]},
            {"id": "22222222-2222-4222-8222-222222222222", "name": "Delete", "actions": [{"type": "delete"}]},
        ]
        assert store.save_quick_steps(account_id, steps) is True
        loaded = store.load_quick_steps(account_id)
        # ``_normalize_step_for_read`` injects defaults for legacy rows that
        # predate the auto-trigger fields. We only assert the identity-bearing
        # fields here; the defaults are exercised separately.
        assert len(loaded) == 2
        assert [s["id"] for s in loaded] == [steps[0]["id"], steps[1]["id"]]
        assert loaded[0]["name"] == "Archive"
        assert loaded[0]["actions"] == [{"type": "archive"}]
        assert loaded[1]["actions"] == [{"type": "delete"}]
        assert loaded[0]["triggers"] == []
        assert loaded[0]["triggerOperator"] == "OR"
        assert loaded[0]["enabled"] is True
        assert loaded[0]["autoEnabled"] is False
        # Legacy rows missing showAutoBadge default to True — preserves
        # the pre-feature transparency expectation when the toggle ships.
        assert loaded[0]["showAutoBadge"] is True

    def test_load_unknown_account_returns_empty(self, db_engine_with_account):
        assert store.load_quick_steps(999_999) == []

    def test_load_with_zero_account_id_returns_empty(self):
        assert store.load_quick_steps(0) == []
        assert store.load_quick_steps(-1) == []

    def test_save_with_zero_account_id_fails(self):
        assert store.save_quick_steps(0, [{"id": "x"}]) is False

    def test_save_overwrites_existing(self, db_engine_with_account):
        _, account_id = db_engine_with_account
        store.save_quick_steps(account_id, [{"id": "a", "name": "first"}])
        store.save_quick_steps(account_id, [{"id": "b", "name": "second"}])
        loaded = store.load_quick_steps(account_id)
        assert len(loaded) == 1
        assert loaded[0]["id"] == "b"

    def test_corrupt_json_is_swallowed(self, db_engine_with_account, engine):
        _, account_id = db_engine_with_account
        SessionLocal = sessionmaker(bind=engine, autoflush=False)
        session = SessionLocal()
        try:
            account = AccountRepository(session).get(account_id)
            account.quick_steps_json = "{not valid json"
            session.commit()
        finally:
            session.close()
        assert store.load_quick_steps(account_id) == []

    def test_non_list_payload_returns_empty(self, db_engine_with_account, engine):
        _, account_id = db_engine_with_account
        SessionLocal = sessionmaker(bind=engine, autoflush=False)
        session = SessionLocal()
        try:
            account = AccountRepository(session).get(account_id)
            account.quick_steps_json = json.dumps({"oops": "not a list"})
            session.commit()
        finally:
            session.close()
        assert store.load_quick_steps(account_id) == []


class TestPureHelpers:
    def test_find_step_hit(self):
        steps = [{"id": "a"}, {"id": "b"}]
        assert store.find_step(steps, "b") == {"id": "b"}

    def test_find_step_miss(self):
        assert store.find_step([{"id": "a"}], "z") is None

    def test_remove_step_drops_match(self):
        steps = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        assert store.remove_step(steps, "b") == [{"id": "a"}, {"id": "c"}]

    def test_remove_step_no_match_returns_copy(self):
        steps = [{"id": "a"}]
        out = store.remove_step(steps, "nope")
        assert out == steps

    def test_upsert_step_replaces_existing(self):
        steps = [{"id": "a", "name": "old"}]
        out = store.upsert_step(steps, {"id": "a", "name": "new"})
        assert out == [{"id": "a", "name": "new"}]

    def test_upsert_step_appends_new(self):
        steps = [{"id": "a"}]
        out = store.upsert_step(steps, {"id": "b"})
        assert [s["id"] for s in out] == ["a", "b"]

    def test_upsert_step_preserves_order(self):
        steps = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        out = store.upsert_step(steps, {"id": "b", "name": "updated"})
        assert [s["id"] for s in out] == ["a", "b", "c"]
        assert out[1]["name"] == "updated"
