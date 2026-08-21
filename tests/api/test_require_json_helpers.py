# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-19 STAB-02 — the shared JSON-body guards must return a clean
400 for any missing / non-JSON / wrong-shape body, never raise (which, inside a
handler's try/except, became a 500 leaking the werkzeug/exception string).

Covers:
- `app.api.helpers.require_json` decorator
- `app.api.routes_helpers.require_json()` function

pytest tests/api/test_require_json_helpers.py -v
"""

import pytest
from flask import Flask, jsonify

from app.api.helpers import require_json as require_json_decorator
from app.api.routes_helpers import require_json as require_json_fn


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/decorated", methods=["POST"])
    @require_json_decorator
    def decorated():
        return jsonify({"ok": True}), 200

    @app.route("/fn", methods=["POST"])
    def fn():
        data, err = require_json_fn()
        if err:
            return err
        return jsonify({"name": data.get("name")}), 200

    return app.test_client()


class TestRequireJsonDecorator:
    def test_valid_object_passes(self, client):
        r = client.post("/decorated", json={"a": 1})
        assert r.status_code == 200

    def test_missing_body_is_clean_400(self, client):
        r = client.post("/decorated")
        assert r.status_code == 400
        assert r.get_json()["error"] == "JSON body required"

    def test_empty_object_is_400(self, client):
        r = client.post("/decorated", json={})
        assert r.status_code == 400

    def test_array_body_is_400_not_passed_through(self, client):
        r = client.post("/decorated", json=[1, 2, 3])
        assert r.status_code == 400

    def test_garbage_body_is_400(self, client):
        r = client.post("/decorated", data="not json", content_type="application/json")
        assert r.status_code == 400


class TestRequireJsonFunction:
    def test_valid_object_returns_data_no_error(self, client):
        r = client.post("/fn", json={"name": "x"})
        assert r.status_code == 200
        assert r.get_json()["name"] == "x"

    def test_missing_body_is_clean_400(self, client):
        r = client.post("/fn")
        assert r.status_code == 400

    def test_array_body_is_400(self, client):
        r = client.post("/fn", json=[1, 2])
        assert r.status_code == 400
