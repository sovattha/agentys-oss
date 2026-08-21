# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the HTTP method-override shim (app/api/app.py).

Context: some embedded-webview HTTP stacks and endpoint-security software drop
PATCH/PUT/DELETE, so the frontend retries them as POST carrying an
`X-HTTP-Method-Override` header. The WSGI shim rewrites REQUEST_METHOD before
Flask's URL-map matching so the original method-scoped route runs unchanged.
"""
import pytest

from app.api.app import create_app


@pytest.fixture
def app():
    app = create_app({"TESTING": True})

    # Method-scoped probe route — echoes the method Flask actually routed on.
    @app.route("/api/_mo_probe", methods=["PATCH", "PUT", "DELETE"])
    def _mo_probe():
        from flask import jsonify, request

        return jsonify({"method": request.method}), 200

    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.mark.parametrize("verb", ["PATCH", "PUT", "DELETE"])
def test_override_routes_post_to_the_method_scoped_handler(client, verb):
    """POST + X-HTTP-Method-Override → the route runs as that verb."""
    resp = client.post("/api/_mo_probe", headers={"X-HTTP-Method-Override": verb})
    assert resp.status_code == 200
    assert resp.get_json()["method"] == verb


def test_plain_post_without_override_is_not_rewritten(client):
    """A POST with no override header stays POST → 405 on a PATCH-only route."""
    resp = client.post("/api/_mo_probe")
    assert resp.status_code == 405


def test_override_only_applies_to_post(client):
    """The shim must never rewrite a real GET (only POST carries the override)."""
    resp = client.get("/api/_mo_probe", headers={"X-HTTP-Method-Override": "PATCH"})
    assert resp.status_code == 405  # GET stays GET; route doesn't allow it


def test_override_whitelist_rejects_unsafe_values(client):
    """Only PATCH/PUT/DELETE are honored; anything else is ignored → stays POST."""
    resp = client.post("/api/_mo_probe", headers={"X-HTTP-Method-Override": "GET"})
    assert resp.status_code == 405


def test_override_is_case_insensitive(client):
    """Lowercase override values are normalized before the whitelist check."""
    resp = client.post("/api/_mo_probe", headers={"X-HTTP-Method-Override": "patch"})
    assert resp.status_code == 200
    assert resp.get_json()["method"] == "PATCH"
