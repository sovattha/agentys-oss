# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
CASA V7.4 (#210) — error disclosure regression tests.

Asserts that error responses follow the canonical envelope
`{"success": false, "error": <generic-message>, "code": <CODE>}`
and never leak implementation details (tracebacks, file paths,
SQL fragments, raw exception strings) to the client.

The handlers under test live in `app/api/app.py` (errorhandlers
for 400/403/404/422/500/503 + the generic Exception catch-all).
"""

import logging

import pytest


@pytest.fixture
def app(monkeypatch):
    """Build a Flask app with our error handlers registered.

    Pin FLASK_ENV so the prod-detection helper sees `production` and the
    generic handler exercises the production branch (no propagate, no debug
    echo). monkeypatch keeps the env var change scoped to this fixture.
    """
    monkeypatch.setenv("FLASK_ENV", "testing")  # never "development"
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
    from app.api.app import create_app

    app = create_app()
    # Belt-and-suspenders — even if test env config flips on us, ensure no
    # exception propagation that would bypass our error handlers.
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.config["TRAP_HTTP_EXCEPTIONS"] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _assert_canonical_envelope(payload, *, code: str, status_label: str):
    """Every error envelope must have the same three keys with predictable
    types. `error` and `code` are stable strings (no dynamic interpolation).

    We INTENTIONALLY do not assert on the verbatim `error` text — Flask uses
    the handler's `description` arg for several 4xx codes, and that text is
    not part of the contract. The contract is the SHAPE.
    """
    assert isinstance(payload, dict), f"{status_label}: response is not a JSON object"
    assert payload.get("success") is False, (
        f"{status_label}: missing/false `success` (got {payload.get('success')!r})"
    )
    assert isinstance(payload.get("error"), str) and payload["error"], (
        f"{status_label}: missing or non-string `error` field"
    )
    assert payload.get("code") == code, (
        f"{status_label}: expected code={code!r}, got {payload.get('code')!r}"
    )


def test_404_returns_canonical_envelope(client):
    """A request to an unknown route returns 404 with the canonical shape."""
    resp = client.get("/api/this-route-does-not-exist-xyz")
    assert resp.status_code == 404
    payload = resp.get_json()
    _assert_canonical_envelope(payload, code="NOT_FOUND", status_label="404")
    # Critically: no traceback, no file path, no Python module name.
    assert "Traceback" not in resp.data.decode("utf-8")
    assert ".py" not in resp.data.decode("utf-8")


def test_405_does_not_leak_handler_internals(client):
    """A wrong-method request on a known route returns 4xx without leaking
    the route handler name or Python module path."""
    # /api/health is GET-only. POST should produce a 4xx (405 by default).
    resp = client.post("/api/health")
    assert resp.status_code in (400, 404, 405, 422)
    body = resp.data.decode("utf-8")
    assert "Traceback" not in body
    assert "/app/api/" not in body
    assert ".py" not in body


def test_unhandled_exception_returns_500_canonical(app, client):
    """A route that raises a non-HTTPException must hit the global Exception
    handler and produce the canonical envelope — not a Flask debug page."""
    @app.route("/__test__/forced-runtime-error")
    def _forced_500():
        raise RuntimeError("internal SQL detail: SELECT * FROM users WHERE id=42")

    resp = client.get("/__test__/forced-runtime-error")
    assert resp.status_code == 500
    payload = resp.get_json()
    _assert_canonical_envelope(payload, code="INTERNAL_ERROR", status_label="500")

    body = resp.data.decode("utf-8")
    # The internal SQL fragment must NOT surface in the response.
    assert "SELECT * FROM users" not in body
    assert "WHERE id=42" not in body
    # Generic error string is fine; raw RuntimeError repr is not.
    assert "RuntimeError" not in body
    assert "Traceback" not in body


def test_unhandled_exception_does_not_leak_filesystem_paths(app, client):
    """Forcing a FileNotFoundError must not surface `/app/api/...` paths."""
    @app.route("/__test__/forced-fnf")
    def _forced_fnf():
        # str(e) for FileNotFoundError contains the path that was tried.
        raise FileNotFoundError("/app/api/secret_internal_path/agentys.db")

    resp = client.get("/__test__/forced-fnf")
    assert resp.status_code == 500
    body = resp.data.decode("utf-8")
    assert "/app/api/" not in body
    assert "agentys.db" not in body
    payload = resp.get_json()
    _assert_canonical_envelope(payload, code="INTERNAL_ERROR", status_label="500-fnf")


def test_http_exception_passes_through_specific_handler(app, client):
    """Raising a 403 in a route should still hit the specific 403 handler
    (not be swallowed by the generic Exception catch-all)."""
    from werkzeug.exceptions import Forbidden

    @app.route("/__test__/forced-403")
    def _forced_403():
        raise Forbidden("Internal description that should NOT leak as-is")

    resp = client.get("/__test__/forced-403")
    assert resp.status_code == 403
    payload = resp.get_json()
    _assert_canonical_envelope(payload, code="FORBIDDEN", status_label="403")


def test_400_keeps_canonical_shape(app, client):
    from werkzeug.exceptions import BadRequest

    @app.route("/__test__/forced-400")
    def _forced_400():
        raise BadRequest("Some validation message")

    resp = client.get("/__test__/forced-400")
    assert resp.status_code == 400
    payload = resp.get_json()
    _assert_canonical_envelope(payload, code="BAD_REQUEST", status_label="400")


def test_unhandled_exception_logged_with_redaction(app, client, caplog):
    """The server-side log must capture the exception (for diagnosis) but
    pass through the redactor (so secrets in the exception message don't
    end up in Sentry / Railway logs)."""
    @app.route("/__test__/forced-token-leak")
    def _forced_token_leak():
        raise RuntimeError("Authorization Bearer eyJhbGciOi.payloadbase64.signaturebase64")

    with caplog.at_level(logging.ERROR):
        resp = client.get("/__test__/forced-token-leak")
    assert resp.status_code == 500
    # Server log retains diagnostic context but with redacted token.
    full_log = caplog.text
    assert "eyJhbGciOi.payloadbase64.signaturebase64" not in full_log
    # The structural marker is still there so logs remain searchable.
    assert "Bearer" in full_log or "[REDACTED]" in full_log


def test_response_content_type_is_json(app, client):
    """Even on 500, the canonical envelope must come back as application/json
    (not text/html — that would suggest the Flask default debug page leaked)."""
    @app.route("/__test__/forced-500-mime")
    def _forced_500_mime():
        raise ValueError("any value error")

    resp = client.get("/__test__/forced-500-mime")
    assert resp.status_code == 500
    assert resp.mimetype == "application/json", (
        f"Expected JSON envelope, got mimetype={resp.mimetype!r}"
    )
    # And the body parses as JSON, not HTML.
    payload = resp.get_json()
    assert payload is not None
