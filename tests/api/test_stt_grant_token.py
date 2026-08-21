# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour POST /api/stt/grant-token — token Deepgram court pour le STT
streaming DIRECT (mobile → Deepgram), qui contourne le proxy Socket.IO
inutilisable sous le worker gunicorn gthread de prod."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.api.routes_stt import stt_bp


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(stt_bp, url_prefix="/api/stt")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def fake_account(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes_stt._resolve_account_id_for_user", lambda: 42
    )
    return 42


def _dg_response(status=200, json_data=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {} if json_data is None else json_data
    r.text = text
    return r


def test_grant_success_returns_token_and_keeps_master_key_server_side(
    client, fake_account, monkeypatch
):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "master-key")
    with patch(
        "requests.post",
        return_value=_dg_response(200, {"access_token": "tok123", "expires_in": 300}),
    ) as mock_post:
        resp = client.post("/api/stt/grant-token", json={"ttl_seconds": 120})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["token"] == "tok123"
    assert data["expires_in"] == 300
    # Le master key part vers Deepgram, jamais au client.
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Token master-key"
    assert kwargs["json"]["ttl_seconds"] == 120


def test_grant_no_account_404(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes_stt._resolve_account_id_for_user", lambda: -1
    )
    monkeypatch.setenv("DEEPGRAM_API_KEY", "master-key")
    resp = client.post("/api/stt/grant-token", json={})
    assert resp.status_code == 404


def test_grant_no_deepgram_key_503(client, fake_account, monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    resp = client.post("/api/stt/grant-token", json={})
    assert resp.status_code == 503


def test_grant_deepgram_upstream_error_502(client, fake_account, monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "master-key")
    with patch("requests.post", return_value=_dg_response(401, {}, "unauthorized")):
        resp = client.post("/api/stt/grant-token", json={})
    assert resp.status_code == 502


def test_grant_ttl_clamped_to_max(client, fake_account, monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "master-key")
    with patch(
        "requests.post",
        return_value=_dg_response(200, {"access_token": "t", "expires_in": 3600}),
    ) as mock_post:
        resp = client.post("/api/stt/grant-token", json={"ttl_seconds": 999999})

    assert resp.status_code == 200
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["ttl_seconds"] == 3600  # capped at Deepgram's max
