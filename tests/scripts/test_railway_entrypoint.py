"""Tests for the Railway process dispatcher."""

from scripts import railway_entrypoint


def test_predeploy_skips_alembic_for_worker(monkeypatch):
    called = False

    def fake_call(_args):
        nonlocal called
        called = True
        return 1

    monkeypatch.setenv("AGENTYS_SERVICE_ROLE", "draft-worker")
    monkeypatch.setattr(railway_entrypoint.subprocess, "call", fake_call)

    assert railway_entrypoint.predeploy() == 0
    assert called is False


def test_predeploy_runs_alembic_for_web(monkeypatch):
    calls = []

    def fake_call(args):
        calls.append(args)
        return 0

    monkeypatch.delenv("AGENTYS_SERVICE_ROLE", raising=False)
    monkeypatch.delenv("AGENTYS_LOAD_TEST_MODE", raising=False)
    monkeypatch.setattr(railway_entrypoint.subprocess, "call", fake_call)

    assert railway_entrypoint.predeploy() == 0
    assert calls == [["alembic", "upgrade", "head"]]


def test_predeploy_skips_alembic_in_load_test_mode(monkeypatch):
    called = False

    def fake_call(_args):
        nonlocal called
        called = True
        return 1

    monkeypatch.delenv("AGENTYS_SERVICE_ROLE", raising=False)
    monkeypatch.setenv("AGENTYS_LOAD_TEST_MODE", "true")
    monkeypatch.setattr(railway_entrypoint.subprocess, "call", fake_call)

    assert railway_entrypoint.predeploy() == 0
    assert called is False


def test_start_dispatches_worker(monkeypatch):
    calls = []

    monkeypatch.setenv("AGENTYS_SERVICE_ROLE", "worker")
    monkeypatch.setattr(railway_entrypoint, "_exec_python", calls.append)

    railway_entrypoint.start()

    assert calls == [["-m", "app.workers.draft_worker"]]


def test_start_dispatches_web_to_gunicorn_by_default(monkeypatch):
    """Prod web role boots gunicorn (graceful drain on deploys), not Werkzeug."""
    calls = []

    monkeypatch.delenv("AGENTYS_SERVICE_ROLE", raising=False)
    monkeypatch.delenv("AGENTYS_LOAD_TEST_MODE", raising=False)
    monkeypatch.delenv("AGENTYS_WEB_SERVER", raising=False)
    monkeypatch.setenv("PORT", "5050")
    monkeypatch.setattr(railway_entrypoint, "_exec_process", calls.append)
    # Belt-and-braces: if the implementation regresses to the Werkzeug path,
    # fail with an assertion instead of os.execvp replacing the pytest process.
    monkeypatch.setattr(
        railway_entrypoint, "_exec_python", lambda args: calls.append(["PYTHON", *args])
    )

    railway_entrypoint.start()

    assert calls
    command = calls[0]
    assert command[0] != "PYTHON", f"web role still dispatches Werkzeug: {command}"
    assert command[:5] == ["gunicorn", "--workers", "1", "--worker-class", "gthread"]
    assert command[-1] == "app.api.gunicorn_app:app"


def test_start_web_rollback_to_werkzeug(monkeypatch):
    """AGENTYS_WEB_SERVER=werkzeug keeps the legacy dev-server path as an
    instant rollback knob (env var change on Railway, no code redeploy)."""
    calls = []

    monkeypatch.delenv("AGENTYS_SERVICE_ROLE", raising=False)
    monkeypatch.delenv("AGENTYS_LOAD_TEST_MODE", raising=False)
    monkeypatch.setenv("AGENTYS_WEB_SERVER", "werkzeug")
    monkeypatch.setattr(railway_entrypoint, "_exec_python", calls.append)
    monkeypatch.setattr(
        railway_entrypoint, "_exec_process", lambda args: calls.append(["PROCESS", *args])
    )

    railway_entrypoint.start()

    assert calls == [["run_api.py", "--host", "0.0.0.0"]]


def test_start_dispatches_load_test_web_to_gunicorn(monkeypatch):
    calls = []

    monkeypatch.delenv("AGENTYS_SERVICE_ROLE", raising=False)
    monkeypatch.setenv("AGENTYS_LOAD_TEST_MODE", "true")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setattr(railway_entrypoint, "_exec_process", calls.append)

    railway_entrypoint.start()

    assert calls
    command = calls[0]
    assert command[:5] == ["gunicorn", "--workers", "1", "--worker-class", "gthread"]
    assert "--threads" in command
    assert "256" in command
    assert "--bind" in command
    assert "0.0.0.0:8080" in command
    assert command[-1] == "app.api.gunicorn_app:app"
