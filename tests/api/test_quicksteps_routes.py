# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Routes API pour /api/quicksteps.

Tests de niveau route : validation, auth, conflits de raccourcis, 404,
idempotency-key passé à l'engine. La logique d'exécution proprement dite
est couverte par tests/quicksteps/test_engine.py — ici on mocke le store
et l'engine pour isoler le contrôleur HTTP.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy.orm import sessionmaker

from app.api.quicksteps import quicksteps_bp
from app.quicksteps import engine as engine_module
# Import the audit-log model at MODULE level so it registers with
# Base.metadata BEFORE the `engine` fixture runs `create_all` — otherwise
# the table is missing in the test SQLite schema and inserts blow up.
from app.db.models.quick_step_audit_log import QuickStepAuditLog


def _new_id() -> str:
    return str(uuid.uuid4())


def _step_payload(**overrides) -> dict:
    base = {
        "id": _new_id(),
        "name": "Newsletter",
        "actions": [{"type": "archive"}],
        "shortcut": "1",
    }
    base.update(overrides)
    return base


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(quicksteps_bp, url_prefix="/api")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def authed():
    """JWT resolves to account_id=1. Patch the helper everywhere it is read."""
    with patch(
        "app.api.routes_helpers._resolve_account_id_for_user",
        return_value=1,
    ):
        yield


@pytest.fixture
def store_state():
    """Replace the store module with an in-memory dict so we can introspect
    saved state without spinning up the DB. Returns the state dict."""
    state = {"steps": [], "save_should_fail": False}

    def fake_load(account_id: int):
        return list(state["steps"])

    def fake_save(account_id: int, steps: list[dict]):
        if state["save_should_fail"]:
            return False
        state["steps"] = list(steps)
        return True

    def fake_transact(account_id: int, mutator):
        if state["save_should_fail"]:
            raise RuntimeError("save failed")
        new_steps = mutator(list(state["steps"]))
        state["steps"] = list(new_steps)
        return new_steps

    with patch("app.api.quicksteps.store_module.load_quick_steps", side_effect=fake_load), \
         patch("app.api.quicksteps.store_module.save_quick_steps", side_effect=fake_save), \
         patch("app.api.quicksteps.store_module.transact_quick_steps", side_effect=fake_transact):
        yield state


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

class TestAuth:
    def test_unauthenticated_returns_401(self, client):
        with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=0):
            resp = client.get("/api/quicksteps")
        assert resp.status_code == 401
        assert resp.get_json()["code"] == "NO_ACCOUNT_SCOPE"


# --------------------------------------------------------------------------- #
# GET /api/quicksteps
# --------------------------------------------------------------------------- #

class TestList:
    def test_empty_list_when_no_steps(self, client, authed, store_state):
        resp = client.get("/api/quicksteps")
        assert resp.status_code == 200
        assert resp.get_json() == {"quick_steps": []}

    def test_returns_saved_steps(self, client, authed, store_state):
        store_state["steps"] = [_step_payload(name="Saved")]
        resp = client.get("/api/quicksteps")
        body = resp.get_json()
        assert body["quick_steps"][0]["name"] == "Saved"


# --------------------------------------------------------------------------- #
# POST /api/quicksteps
# --------------------------------------------------------------------------- #

class TestCreate:
    def test_creates_valid_step(self, client, authed, store_state):
        body = _step_payload(name="Newsletter")
        resp = client.post("/api/quicksteps", json=body)
        assert resp.status_code == 201
        assert resp.get_json()["name"] == "Newsletter"
        assert len(store_state["steps"]) == 1

    def test_no_body_returns_400(self, client, authed, store_state):
        resp = client.post("/api/quicksteps")
        assert resp.status_code in (400, 415)

    def test_invalid_payload_returns_400(self, client, authed, store_state):
        resp = client.post("/api/quicksteps", json={"id": "not-a-uuid"})
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "VALIDATION_ERROR"

    def test_shortcut_collision_returns_400(self, client, authed, store_state):
        existing = _step_payload(shortcut="1", name="A")
        store_state["steps"] = [existing]
        new = _step_payload(shortcut="1", name="B")
        resp = client.post("/api/quicksteps", json=new)
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "SHORTCUT_CONFLICT"

    def test_shortcut_collision_with_self_id_is_allowed(self, client, authed, store_state):
        # POST with the same id is upsert — same shortcut on the same step is fine.
        original = _step_payload(shortcut="1", name="A")
        store_state["steps"] = [original]
        resp = client.post("/api/quicksteps", json={**original, "name": "A renamed"})
        assert resp.status_code == 201
        assert store_state["steps"][0]["name"] == "A renamed"

    def test_quota_enforced_for_new_id(self, client, authed, store_state):
        from app.quicksteps import schema
        store_state["steps"] = [
            _step_payload(shortcut=None) for _ in range(schema.MAX_QUICK_STEPS_PER_ACCOUNT)
        ]
        new = _step_payload(shortcut=None)
        resp = client.post("/api/quicksteps", json=new)
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "LIMIT_REACHED"

    def test_save_failure_returns_500(self, client, authed, store_state):
        store_state["save_should_fail"] = True
        resp = client.post("/api/quicksteps", json=_step_payload())
        assert resp.status_code == 500


# --------------------------------------------------------------------------- #
# PATCH /api/quicksteps/<id>
# --------------------------------------------------------------------------- #

class TestUpdate:
    def test_updates_existing_step(self, client, authed, store_state):
        original = _step_payload(name="Old")
        store_state["steps"] = [original]
        resp = client.patch(
            f"/api/quicksteps/{original['id']}",
            json={"name": "New"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "New"
        assert store_state["steps"][0]["name"] == "New"

    def test_unknown_id_returns_404(self, client, authed, store_state):
        resp = client.patch(f"/api/quicksteps/{_new_id()}", json={"name": "x"})
        assert resp.status_code == 404

    def test_id_mismatch_in_body_rejected(self, client, authed, store_state):
        existing = _step_payload()
        store_state["steps"] = [existing]
        resp = client.patch(
            f"/api/quicksteps/{existing['id']}",
            json={"id": _new_id(), "name": "x"},
        )
        assert resp.status_code == 400

    def test_shortcut_collision_with_other_step(self, client, authed, store_state):
        a = _step_payload(name="A", shortcut="1")
        b = _step_payload(name="B", shortcut="2")
        store_state["steps"] = [a, b]
        resp = client.patch(
            f"/api/quicksteps/{b['id']}",
            json={"shortcut": "1"},  # collide with A
        )
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "SHORTCUT_CONFLICT"

    def test_invalid_payload_returns_400(self, client, authed, store_state):
        existing = _step_payload()
        store_state["steps"] = [existing]
        resp = client.patch(
            f"/api/quicksteps/{existing['id']}",
            json={"actions": []},  # empty actions reject
        )
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# DELETE /api/quicksteps/<id>
# --------------------------------------------------------------------------- #

class TestDelete:
    def test_deletes_existing_step(self, client, authed, store_state):
        existing = _step_payload()
        store_state["steps"] = [existing]
        resp = client.delete(f"/api/quicksteps/{existing['id']}")
        assert resp.status_code == 200
        assert store_state["steps"] == []

    def test_unknown_id_returns_404(self, client, authed, store_state):
        resp = client.delete(f"/api/quicksteps/{_new_id()}")
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# POST /api/quicksteps/<id>/execute
# --------------------------------------------------------------------------- #

class TestExecute:
    @pytest.fixture
    def captured(self, store_state):
        """Patch engine.execute to record calls and return a controllable report."""
        captured: dict = {}

        def fake_execute(*, account_id, step, email_id, idempotency_key, **_kwargs):
            captured["account_id"] = account_id
            captured["step_id"] = step["id"]
            captured["email_id"] = email_id
            captured["idempotency_key"] = idempotency_key
            return engine_module.ExecutionReport(
                success=True,
                step_id=step["id"],
                email_id=email_id,
                executed=len(step["actions"]),
                actions=[
                    engine_module.ActionStatus(type=a["type"], ok=True)
                    for a in step["actions"]
                ],
            )

        with patch("app.api.quicksteps.engine_module.execute", side_effect=fake_execute):
            yield captured

    def test_executes_known_step(self, client, authed, store_state, captured):
        step = _step_payload()
        store_state["steps"] = [step]
        resp = client.post(
            f"/api/quicksteps/{step['id']}/execute",
            json={"email_id": "msg-abc"},
            headers={"Idempotency-Key": "key-1"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert captured["account_id"] == 1
        assert captured["step_id"] == step["id"]
        assert captured["email_id"] == "msg-abc"
        assert captured["idempotency_key"] == "key-1"

    def test_unknown_step_returns_404(self, client, authed, store_state, captured):
        resp = client.post(
            f"/api/quicksteps/{_new_id()}/execute",
            json={"email_id": "msg-abc"},
        )
        assert resp.status_code == 404

    def test_disabled_step_returns_409(self, client, authed, store_state, captured):
        step = _step_payload(enabled=False)
        store_state["steps"] = [step]
        resp = client.post(
            f"/api/quicksteps/{step['id']}/execute",
            json={"email_id": "msg-abc"},
        )
        assert resp.status_code == 409
        assert resp.get_json()["code"] == "STEP_DISABLED"

    def test_missing_email_id_returns_400(self, client, authed, store_state, captured):
        step = _step_payload()
        store_state["steps"] = [step]
        resp = client.post(f"/api/quicksteps/{step['id']}/execute", json={})
        assert resp.status_code == 400

    def test_email_not_found_translates_to_404(self, client, authed, store_state):
        step = _step_payload()
        store_state["steps"] = [step]

        def stub_execute(**_kw):
            return engine_module.ExecutionReport(
                success=False, step_id=step["id"], email_id="x",
                error="email_not_found",
            )

        with patch("app.api.quicksteps.engine_module.execute", side_effect=stub_execute):
            resp = client.post(
                f"/api/quicksteps/{step['id']}/execute",
                json={"email_id": "x"},
            )
        assert resp.status_code == 404

    def test_template_unknown_var_returns_400(self, client, authed, store_state):
        step = _step_payload()
        store_state["steps"] = [step]

        def stub_execute(**_kw):
            return engine_module.ExecutionReport(
                success=False, step_id=step["id"], email_id="x",
                error="template_unknown_variables: nope.foo",
            )

        with patch("app.api.quicksteps.engine_module.execute", side_effect=stub_execute):
            resp = client.post(
                f"/api/quicksteps/{step['id']}/execute",
                json={"email_id": "x"},
            )
        assert resp.status_code == 400

    def test_provider_failure_returns_502(self, client, authed, store_state):
        step = _step_payload()
        store_state["steps"] = [step]

        def stub_execute(**_kw):
            return engine_module.ExecutionReport(
                success=False, step_id=step["id"], email_id="x",
                error="provider_archive_failed",
            )

        with patch("app.api.quicksteps.engine_module.execute", side_effect=stub_execute):
            resp = client.post(
                f"/api/quicksteps/{step['id']}/execute",
                json={"email_id": "x"},
            )
        assert resp.status_code == 502


# --------------------------------------------------------------------------- #
# GET /api/quicksteps/auto-badges
# --------------------------------------------------------------------------- #
#
# Real-DB tests : the endpoint runs an actual SQLAlchemy query against
# `quick_step_audit_log` and we want to prove the filter shape (source=auto,
# success=true, step_id in allowed set, account_id matches). Mocking the
# query chain would test the mock more than the route. We use the shared
# `engine` + `sample_account` fixtures from tests.db._fixtures and rebind
# `get_db_session` to that engine for the duration of each test.

@pytest.fixture
def real_db(engine, sample_account):
    SessionLocal = sessionmaker(bind=engine, autoflush=False)

    @contextmanager
    def fake_session_cm():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    with patch("app.db.database.get_db_session", fake_session_cm), \
         patch(
             "app.api.routes_helpers._resolve_account_id_for_user",
             return_value=sample_account.id,
         ):
        yield {"account_id": sample_account.id, "SessionLocal": SessionLocal}


def _insert_audit_row(
    SessionLocal,
    *,
    account_id: int,
    step_id: str,
    step_name: str,
    email_id: str,
    source: str = "auto",
    success: bool = True,
    created_at: datetime | None = None,
) -> None:
    s = SessionLocal()
    try:
        row = QuickStepAuditLog(
            account_id=account_id,
            step_id=step_id,
            step_name=step_name,
            email_id=email_id,
            source=source,
            success=success,
            executed=1,
            created_at=created_at or datetime.utcnow(),
        )
        s.add(row)
        s.commit()
    finally:
        s.close()


class TestAutoBadgesEndpoint:
    def test_no_ids_returns_empty(self, client, real_db, store_state):
        resp = client.get("/api/quicksteps/auto-badges")
        assert resp.status_code == 200
        assert resp.get_json() == {"badges": {}}

    def test_empty_ids_returns_empty(self, client, real_db, store_state):
        resp = client.get("/api/quicksteps/auto-badges?ids=")
        assert resp.status_code == 200
        assert resp.get_json() == {"badges": {}}

    def test_no_steps_returns_empty(self, client, real_db, store_state):
        # store_state.steps stays [] → no allowed_step_ids → short-circuit
        resp = client.get("/api/quicksteps/auto-badges?ids=e1,e2")
        assert resp.status_code == 200
        assert resp.get_json() == {"badges": {}}

    def test_returns_badge_for_actioned_email(self, client, real_db, store_state):
        step_id = _new_id()
        store_state["steps"] = [
            _step_payload(id=step_id, name="Newsletter Triage", showAutoBadge=True),
        ]
        _insert_audit_row(
            real_db["SessionLocal"],
            account_id=real_db["account_id"],
            step_id=step_id,
            step_name="Newsletter Triage",
            email_id="e-actioned",
        )
        resp = client.get("/api/quicksteps/auto-badges?ids=e-actioned,e-other")
        assert resp.status_code == 200
        badges = resp.get_json()["badges"]
        assert "e-actioned" in badges
        assert badges["e-actioned"]["stepId"] == step_id
        assert badges["e-actioned"]["stepName"] == "Newsletter Triage"
        assert badges["e-actioned"]["executedAt"].endswith("Z")
        # e-other had no audit row → no badge
        assert "e-other" not in badges

    def test_manual_execution_ignored(self, client, real_db, store_state):
        step_id = _new_id()
        store_state["steps"] = [_step_payload(id=step_id, showAutoBadge=True)]
        _insert_audit_row(
            real_db["SessionLocal"],
            account_id=real_db["account_id"],
            step_id=step_id, step_name="X",
            email_id="e1",
            source="manual",
        )
        resp = client.get("/api/quicksteps/auto-badges?ids=e1")
        assert resp.get_json()["badges"] == {}

    def test_failed_execution_ignored(self, client, real_db, store_state):
        step_id = _new_id()
        store_state["steps"] = [_step_payload(id=step_id, showAutoBadge=True)]
        _insert_audit_row(
            real_db["SessionLocal"],
            account_id=real_db["account_id"],
            step_id=step_id, step_name="X",
            email_id="e1",
            success=False,
        )
        resp = client.get("/api/quicksteps/auto-badges?ids=e1")
        assert resp.get_json()["badges"] == {}

    def test_step_with_badge_off_excluded(self, client, real_db, store_state):
        """showAutoBadge=false on the step → the email is auto-actioned
        successfully but the badge is suppressed (user opted out)."""
        step_id = _new_id()
        store_state["steps"] = [_step_payload(id=step_id, showAutoBadge=False)]
        _insert_audit_row(
            real_db["SessionLocal"],
            account_id=real_db["account_id"],
            step_id=step_id, step_name="Silent",
            email_id="e1",
        )
        resp = client.get("/api/quicksteps/auto-badges?ids=e1")
        assert resp.get_json()["badges"] == {}

    def test_deleted_step_excluded(self, client, real_db, store_state):
        """Audit row exists but the step has been deleted → no badge.
        We filter by the CURRENT step list, not by the audit-time snapshot."""
        step_id = _new_id()
        store_state["steps"] = []  # step deleted
        _insert_audit_row(
            real_db["SessionLocal"],
            account_id=real_db["account_id"],
            step_id=step_id, step_name="Deleted",
            email_id="e1",
        )
        resp = client.get("/api/quicksteps/auto-badges?ids=e1")
        assert resp.get_json()["badges"] == {}

    def test_most_recent_row_wins_for_same_email(self, client, real_db, store_state):
        step_a = _new_id()
        step_b = _new_id()
        store_state["steps"] = [
            _step_payload(id=step_a, name="Older", showAutoBadge=True),
            _step_payload(id=step_b, name="Newer", showAutoBadge=True),
        ]
        older = datetime.utcnow() - timedelta(hours=2)
        newer = datetime.utcnow()
        _insert_audit_row(
            real_db["SessionLocal"], account_id=real_db["account_id"],
            step_id=step_a, step_name="Older", email_id="e1",
            created_at=older,
        )
        _insert_audit_row(
            real_db["SessionLocal"], account_id=real_db["account_id"],
            step_id=step_b, step_name="Newer", email_id="e1",
            created_at=newer,
        )
        resp = client.get("/api/quicksteps/auto-badges?ids=e1")
        badges = resp.get_json()["badges"]
        # Most-recent step wins — that's the one the user just experienced.
        assert badges["e1"]["stepId"] == step_b

    def test_current_step_name_preferred_over_audit_snapshot(self, client, real_db, store_state):
        """Step was renamed after the audit row was written — surface the
        current name (the user's mental model is "my rule today, not yesterday")."""
        step_id = _new_id()
        store_state["steps"] = [_step_payload(
            id=step_id, name="Renamed Today", showAutoBadge=True,
        )]
        _insert_audit_row(
            real_db["SessionLocal"], account_id=real_db["account_id"],
            step_id=step_id, step_name="Old Name", email_id="e1",
        )
        resp = client.get("/api/quicksteps/auto-badges?ids=e1")
        assert resp.get_json()["badges"]["e1"]["stepName"] == "Renamed Today"

    def test_cap_on_id_count(self, client, real_db, store_state):
        """Too many ids: only the first _AUTO_BADGES_MAX_IDS are processed.
        We don't assert exact slicing semantics — just that the endpoint
        returns 200 without choking on a 1000-id input."""
        many = ",".join(f"e{i}" for i in range(1000))
        resp = client.get(f"/api/quicksteps/auto-badges?ids={many}")
        assert resp.status_code == 200
        assert resp.get_json()["badges"] == {}  # no audit rows for those ids
