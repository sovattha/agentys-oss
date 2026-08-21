"""Smoke test — the WS self-test endpoint detects the #290 failure mode.

Exercises `/api/_internal/ws-selftest` in three scenarios:
  1. Missing token → 401
  2. Wrong token → 401
  3. Correct token in a fresh Flask app → 200 with delivered=True

Layer 3 (the cron) depends on this endpoint being reachable and on
its contract (JSON shape, status codes). A CI test here prevents the
endpoint silently drifting and leaving the cron blind.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def app_client(monkeypatch: pytest.MonkeyPatch):
    """Flask test client with OBSERVABILITY_TOKEN configured AND socketio initialised.

    Using monkeypatch so the env var is scoped to the test — never leaks
    into neighbouring tests or the developer's shell. We also init
    socketio (normally done in run_api.py, not create_app) so that
    `emit_to_account` has a live transport to hand the event to; without
    it, the endpoint returns 503 `emit_returned_false` and we'd not be
    testing the real code path.
    """
    monkeypatch.setenv("OBSERVABILITY_TOKEN", "test-token-smoke")

    from app.api.app import create_app
    from app.api.websocket import init_socketio

    application = create_app()
    init_socketio(application)
    application.config["TESTING"] = True
    with application.test_client() as client:
        yield client


def test_missing_token_returns_401(app_client) -> None:
    """No header → 401. Ensures the endpoint is never accidentally open."""
    resp = app_client.post("/api/_internal/ws-selftest")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "unauthorized"}


def test_wrong_token_returns_401(app_client) -> None:
    """Bad header → 401. Constant-time compare isn't required (low volume),
    but the response body must not reveal whether the env var is set."""
    resp = app_client.post(
        "/api/_internal/ws-selftest",
        headers={"X-Observability-Token": "nope"},
    )
    assert resp.status_code == 401


def test_correct_token_returns_200_with_delivered_true(app_client) -> None:
    """Happy path — this is exactly what the cron expects every 10 min.

    Guards the contract: a layer-3 alert fires after 3 consecutive non-200
    responses, so any silent schema drift here would delay detection.
    """
    resp = app_client.post(
        "/api/_internal/ws-selftest",
        headers={"X-Observability-Token": "test-token-smoke"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["delivered"] is True
    assert body["room_resolved"] is True
    assert body["account_upserted"] is True
    assert body["reason"] is None
    assert isinstance(body["latency_ms"], int)


def test_env_var_missing_rejects_all_traffic(monkeypatch: pytest.MonkeyPatch) -> None:
    """If OBSERVABILITY_TOKEN is unset, the endpoint must fail-closed.

    A misconfigured deploy shouldn't silently degrade into an open probe.
    """
    monkeypatch.delenv("OBSERVABILITY_TOKEN", raising=False)
    from app.api.app import create_app
    application = create_app()
    application.config["TESTING"] = True
    with application.test_client() as client:
        resp = client.post(
            "/api/_internal/ws-selftest",
            headers={"X-Observability-Token": "anything"},
        )
    assert resp.status_code == 401
