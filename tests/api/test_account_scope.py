# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests pour le décorateur @account_scoped et require_matching_account_header.

Garantit :
  - Renvoie 401 si pas d'account résolu (JWT invalide, Tauri sans compte).
  - Injecte g.account_id si valide.
  - require_matching_account_header : 403 si JWT ≠ X-Account-Id.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Blueprint, Flask, g, jsonify

from app.api.account_scope import account_scoped, require_matching_account_header


@pytest.fixture
def app():
    app = Flask(__name__)
    bp = Blueprint("t", __name__)

    @bp.route("/scoped")
    @account_scoped
    def _scoped():
        return jsonify({"account_id": g.account_id})

    @bp.route("/header_matched")
    @account_scoped
    @require_matching_account_header
    def _header_matched():
        return jsonify({"account_id": g.account_id})

    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# --------------------------------------------------------------------------- #
# @account_scoped
# --------------------------------------------------------------------------- #


def test_account_scoped_returns_401_when_no_account(client):
    with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=-1):
        resp = client.get("/scoped")
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "NO_ACCOUNT_SCOPE"


def test_account_scoped_returns_401_when_account_is_zero(client):
    with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=0):
        resp = client.get("/scoped")
    assert resp.status_code == 401


def test_account_scoped_injects_g_account_id(client):
    with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=42):
        resp = client.get("/scoped")
    assert resp.status_code == 200
    assert resp.get_json()["account_id"] == 42


# --------------------------------------------------------------------------- #
# require_matching_account_header
# --------------------------------------------------------------------------- #


def test_header_mismatch_returns_403(client):
    with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
        resp = client.get("/header_matched", headers={"X-Account-Id": "2"})
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "ACCOUNT_HEADER_MISMATCH"


def test_header_match_succeeds(client):
    with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
        resp = client.get("/header_matched", headers={"X-Account-Id": "1"})
    assert resp.status_code == 200


def test_missing_header_is_allowed_for_backward_compat(client):
    with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
        resp = client.get("/header_matched")
    assert resp.status_code == 200


def test_invalid_header_returns_400(client):
    with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
        resp = client.get("/header_matched", headers={"X-Account-Id": "not-a-number"})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "INVALID_ACCOUNT_HEADER"
