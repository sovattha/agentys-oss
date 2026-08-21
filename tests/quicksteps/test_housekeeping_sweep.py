# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Housekeeping sweep — timer-driven re-evaluation of passive time rules.

``email_older_than_days`` / ``no_reply_after_days`` only flip truth value as
wall-clock advances, but the event path (``run_auto_triggers``) only fires on
arrival / state change. So an inbox email that ages past the threshold while
sitting there never re-triggers. ``run_housekeeping_sweep`` closes that gap
on the existing 5-min scheduler tick: it loads the account's auto-enabled
received rules that carry a time condition, gathers bounded inbox candidates,
and runs them through the SAME dedup+execute helper as the event path.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models.email import Email
from app.quicksteps import auto_trigger


@pytest.fixture
def db_session(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False)

    @contextmanager
    def fake_session_cm():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.db.database.get_db_session", fake_session_cm)
        yield SessionLocal()


def _insert(session, *, account_id, email_id, days_ago, is_sent=False,
            is_draft=False, labels="INBOX"):
    session.add(Email(
        email_id=email_id,
        account_id=account_id,
        thread_id=f"thread-{email_id}",
        sender="ext@partner.com",
        subject="Old newsletter",
        date=datetime.utcnow() - timedelta(days=days_ago),
        is_sent=is_sent,
        is_draft=is_draft,
        labels=labels,
    ))
    session.commit()


def _archive_after_30d_rule() -> dict:
    return {
        "id": "11111111-1111-5111-8111-111111111111",
        "name": "Archive old inbox",
        "enabled": True,
        "autoEnabled": True,
        "firesOn": "received",
        "triggerOperator": "AND",
        "triggers": [{"type": "email_older_than_days", "value": "30"}],
        "actions": [{"type": "archive", "payload": {}}],
    }


def _sender_rule() -> dict:
    """A rule with NO time condition — the sweep must ignore it."""
    return {
        "id": "22222222-2222-5222-8222-222222222222",
        "name": "Label boss",
        "enabled": True,
        "autoEnabled": True,
        "firesOn": "received",
        "triggerOperator": "AND",
        "triggers": [{"type": "sender", "match_mode": "is", "value": "boss@corp.com"}],
        "actions": [{"type": "apply_label", "payload": {"label": "VIP"}}],
    }


@pytest.fixture
def capture_apply(monkeypatch):
    """Replace the shared execute helper so the sweep is tested in isolation
    from the engine / provider. Records (email_id, [step names])."""
    calls: list[dict] = []

    def _fake_apply(account_id, email_id, snapshot, steps, *, fired_pairs=None):
        calls.append({"email_id": email_id, "steps": [s["name"] for s in steps]})
        return len(steps)

    monkeypatch.setattr(auto_trigger, "_apply_steps_to_snapshot", _fake_apply)
    return calls


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

class TestTimeConditionDetection:
    def test_detects_email_older_than_days(self):
        assert auto_trigger._step_has_time_condition(_archive_after_30d_rule()) is True

    def test_detects_no_reply_after_days(self):
        step = {"triggers": [{"type": "no_reply_after_days", "value": "5"}]}
        assert auto_trigger._step_has_time_condition(step) is True

    def test_ignores_non_time_rule(self):
        assert auto_trigger._step_has_time_condition(_sender_rule()) is False


# --------------------------------------------------------------------------- #
# Sweep behaviour
# --------------------------------------------------------------------------- #

class TestHousekeepingSweep:
    def test_applies_time_rule_to_old_inbox_email(self, db_session, sample_account, capture_apply, monkeypatch):
        monkeypatch.setattr("app.quicksteps.store.load_quick_steps",
                            lambda _aid: [_archive_after_30d_rule()])
        _insert(db_session, account_id=sample_account.id, email_id="old-1", days_ago=40)

        counters = auto_trigger.run_housekeeping_sweep(sample_account.id)

        assert counters["steps"] == 1
        assert counters["candidates"] == 1
        assert len(capture_apply) == 1
        assert capture_apply[0]["email_id"] == "old-1"
        assert capture_apply[0]["steps"] == ["Archive old inbox"]

    def test_skips_recent_email_below_threshold(self, db_session, sample_account, capture_apply, monkeypatch):
        monkeypatch.setattr("app.quicksteps.store.load_quick_steps",
                            lambda _aid: [_archive_after_30d_rule()])
        _insert(db_session, account_id=sample_account.id, email_id="recent-1", days_ago=2)

        counters = auto_trigger.run_housekeeping_sweep(sample_account.id)

        assert counters["candidates"] == 0
        assert capture_apply == []

    def test_excludes_sent_and_archived(self, db_session, sample_account, capture_apply, monkeypatch):
        monkeypatch.setattr("app.quicksteps.store.load_quick_steps",
                            lambda _aid: [_archive_after_30d_rule()])
        _insert(db_session, account_id=sample_account.id, email_id="old-sent", days_ago=40, is_sent=True)
        _insert(db_session, account_id=sample_account.id, email_id="old-archived", days_ago=40, labels="ARCHIVE")
        _insert(db_session, account_id=sample_account.id, email_id="old-inbox", days_ago=40, labels="INBOX")

        auto_trigger.run_housekeeping_sweep(sample_account.id)

        seen = {c["email_id"] for c in capture_apply}
        assert seen == {"old-inbox"}

    def test_account_scoped(self, db_session, sample_account, sample_account_outlook, capture_apply, monkeypatch):
        monkeypatch.setattr("app.quicksteps.store.load_quick_steps",
                            lambda _aid: [_archive_after_30d_rule()])
        _insert(db_session, account_id=sample_account_outlook.id, email_id="other-old", days_ago=40)

        auto_trigger.run_housekeeping_sweep(sample_account.id)

        assert capture_apply == []  # the other account's old email is invisible

    def test_no_time_rule_is_a_noop(self, db_session, sample_account, capture_apply, monkeypatch):
        monkeypatch.setattr("app.quicksteps.store.load_quick_steps",
                            lambda _aid: [_sender_rule()])
        _insert(db_session, account_id=sample_account.id, email_id="old-1", days_ago=40)

        counters = auto_trigger.run_housekeeping_sweep(sample_account.id)

        assert counters["steps"] == 0
        assert capture_apply == []

    def test_only_time_steps_passed_to_helper(self, db_session, sample_account, capture_apply, monkeypatch):
        # Account has a time rule AND a non-time rule; only the time rule is
        # swept (the non-time rule already had its chance on the event path).
        monkeypatch.setattr("app.quicksteps.store.load_quick_steps",
                            lambda _aid: [_archive_after_30d_rule(), _sender_rule()])
        _insert(db_session, account_id=sample_account.id, email_id="old-1", days_ago=40)

        auto_trigger.run_housekeeping_sweep(sample_account.id)

        assert len(capture_apply) == 1
        assert capture_apply[0]["steps"] == ["Archive old inbox"]


# --------------------------------------------------------------------------- #
# Scheduler wiring
# --------------------------------------------------------------------------- #

class TestSchedulerWiring:
    def test_scheduled_tick_invokes_housekeeping_sweep(self, monkeypatch):
        from app.api import quicksteps_scheduler as sched

        sched._scheduler_last_run.clear()
        swept: list[int] = []
        monkeypatch.setattr(sched, "sweep_woken_snoozed_drafts", lambda **kw: None)
        # run_housekeeping_sweep is referenced through the auto_trigger module.
        monkeypatch.setattr(
            "app.quicksteps.auto_trigger.run_housekeeping_sweep",
            lambda account_id, **kw: swept.append(account_id) or {"steps": 0},
        )

        sched.run_quicksteps_scheduled("1")  # digit → account_id_int = 1

        assert swept == [1]


class TestSyncCompleteWiring:
    """run_scheduled_sweeps_after_sync — the adapter run_api.on_sync_complete
    calls so the throttled background tick (incl. the housekeeping sweep) runs
    server-side after every sync, not only on inbox-open."""

    def test_resolves_hex_and_runs_scheduled_tick(self, monkeypatch):
        from app.api import quicksteps_scheduler as sched
        from app import multi_accounts

        class _Cfg:
            id = "hexabc"

        class _Mgr:
            def get_account_by_email(self, _email):
                return _Cfg()

        called: list[str] = []
        monkeypatch.setattr(multi_accounts, "get_account_manager", lambda: _Mgr())
        monkeypatch.setattr(sched, "run_quicksteps_scheduled", lambda oid: called.append(oid))

        sched.run_scheduled_sweeps_after_sync(13, "me@example.com")
        assert called == ["hexabc"]  # passes the hex id so the provider-backed sweep works

    def test_falls_back_to_int_when_hex_unresolved(self, monkeypatch):
        from app.api import quicksteps_scheduler as sched
        from app import multi_accounts

        class _Mgr:
            def get_account_by_email(self, _email):
                return None

        called: list[str] = []
        monkeypatch.setattr(multi_accounts, "get_account_manager", lambda: _Mgr())
        monkeypatch.setattr(sched, "run_quicksteps_scheduled", lambda oid: called.append(oid))

        sched.run_scheduled_sweeps_after_sync(13, "me@example.com")
        # Housekeeping still runs via the int id; the snoozed-draft sweep no-ops.
        assert called == ["13"]

    def test_noop_on_missing_account(self, monkeypatch):
        from app.api import quicksteps_scheduler as sched
        called: list[str] = []
        monkeypatch.setattr(sched, "run_quicksteps_scheduled", lambda oid: called.append(oid))

        sched.run_scheduled_sweeps_after_sync(0, "")
        sched.run_scheduled_sweeps_after_sync(13, "")
        assert called == []


class TestSweepDedupBatch:
    """#2 — the sweep batches the per-(step,email) dedup into one audit-log
    query instead of N. _fired_pairs returns the already-fired set;
    _apply_steps_to_snapshot honors it (event path still uses the per-pair
    query when fired_pairs is None)."""

    def test_fired_pairs_returns_only_success_auto_pairs(self, db_session, sample_account):
        from app.db.models.quick_step_audit_log import QuickStepAuditLog
        now = datetime.utcnow()
        for sid, eid, src, ok in [
            ("stepX", "emailA", "auto", True),
            ("stepX", "emailB", "auto", True),
            ("stepX", "emailC", "auto", False),    # failed → excluded
            ("stepY", "emailA", "manual", True),   # manual → excluded
        ]:
            db_session.add(QuickStepAuditLog(
                account_id=sample_account.id, step_id=sid, email_id=eid,
                source=src, success=ok, executed=1, created_at=now,
            ))
        db_session.commit()

        pairs = auto_trigger._fired_pairs(
            sample_account.id, ["stepX", "stepY"], ["emailA", "emailB", "emailC"],
        )
        assert pairs == {("stepX", "emailA"), ("stepX", "emailB")}

    def test_fired_pairs_empty_inputs(self, db_session, sample_account):
        assert auto_trigger._fired_pairs(sample_account.id, [], ["e1"]) == set()
        assert auto_trigger._fired_pairs(sample_account.id, ["s1"], []) == set()

    def test_fired_pairs_returns_none_on_db_error(self, monkeypatch):
        # On DB error, return None (NOT empty set) so the sweep falls back to
        # per-pair dedup rather than bypassing it for the whole candidate set.
        @contextmanager
        def _boom():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        monkeypatch.setattr("app.db.database.get_db_session", _boom)
        assert auto_trigger._fired_pairs(1, ["s1"], ["e1"]) is None

    def test_apply_skips_pairs_in_fired_set(self, monkeypatch):
        executed: list[str] = []

        class _Report:
            success = True
            error = None

        monkeypatch.setattr(
            "app.quicksteps.engine.execute",
            lambda **kw: (executed.append(kw["step"]["name"]), _Report())[1],
        )
        monkeypatch.setattr(auto_trigger, "_evaluate_triggers", lambda *a, **k: True)
        monkeypatch.setattr(auto_trigger, "_emit_quickstep_fired_event", lambda **kw: None)

        def _step(sid, name):
            return {"id": sid, "name": name, "enabled": True, "autoEnabled": True,
                    "firesOn": "received", "triggers": [{"type": "x"}],
                    "actions": [{"type": "archive"}]}

        n = auto_trigger._apply_steps_to_snapshot(
            1, "email-1", object(),
            [_step("sX", "X"), _step("sY", "Y")],
            fired_pairs={("sX", "email-1")},
        )
        assert executed == ["Y"]   # X already fired (in set) → skipped; Y runs
        assert n == 1
