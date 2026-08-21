# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour app/api/routes_stt.py — REST CRUD des keyterms STT."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Flask

from app.api.routes_stt import stt_bp
from app.services import stt_keyterms


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
def db_path(tmp_path, monkeypatch):
    """DB SQLite isolée par test."""
    path = str(tmp_path / "stt_keyterms.db")
    monkeypatch.setattr(stt_keyterms, "_resolve_db_path", lambda: path)
    import threading
    monkeypatch.setattr(stt_keyterms, "_local", threading.local())
    return path


@pytest.fixture
def fake_account(monkeypatch):
    """Stub _resolve_account_id_for_user → 42 (a valid account)."""
    monkeypatch.setattr(
        "app.api.routes_stt._resolve_account_id_for_user",
        lambda: 42,
    )
    return 42


@pytest.fixture
def no_account(monkeypatch):
    """Stub _resolve_account_id_for_user → -1 (no account)."""
    monkeypatch.setattr(
        "app.api.routes_stt._resolve_account_id_for_user",
        lambda: -1,
    )


class TestListKeyterms:
    def test_returns_auto_and_custom(self, client, db_path, fake_account):
        stt_keyterms.add_keyterm(42, "Nat", db_path=db_path)
        with patch("app.services.stt_keyterms.list_auto", return_value=["Atlas"]):
            resp = client.get("/api/stt/keyterms")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["auto"] == ["Atlas"]
        assert data["custom"] == ["Nat"]

    def test_no_account_returns_empty_lists(self, client, no_account):
        resp = client.get("/api/stt/keyterms")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["auto"] == []
        assert data["custom"] == []

    def test_returns_effective_cap(self, client, db_path, fake_account):
        """GET exposes the dictation-effective cap so the UI can show 'X / cap'
        and warn at the limit."""
        with patch("app.services.stt_keyterms.list_auto", return_value=[]):
            resp = client.get("/api/stt/keyterms")
        assert resp.get_json()["cap"] == stt_keyterms.KEYTERM_CAP == 50


class TestAddKeyterm:
    def test_inserts_returns_201(self, client, db_path, fake_account):
        resp = client.post("/api/stt/keyterms", json={"term": "Nathan"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["inserted"] is True
        assert "Nathan" in data["custom"]

    def test_duplicate_returns_200(self, client, db_path, fake_account):
        client.post("/api/stt/keyterms", json={"term": "Nat"})
        resp = client.post("/api/stt/keyterms", json={"term": "nat"})
        assert resp.status_code == 200
        assert resp.get_json()["inserted"] is False

    def test_missing_term_returns_400(self, client, db_path, fake_account):
        resp = client.post("/api/stt/keyterms", json={})
        assert resp.status_code == 400

    def test_empty_term_returns_400(self, client, db_path, fake_account):
        resp = client.post("/api/stt/keyterms", json={"term": "   "})
        assert resp.status_code == 400

    def test_no_account_returns_404(self, client, no_account):
        resp = client.post("/api/stt/keyterms", json={"term": "Nat"})
        assert resp.status_code == 404

    def test_write_cap_equals_effective_keyterm_cap(self):
        """The write-time custom cap is reconciled to the read-time effective
        cap (KEYTERM_CAP=50), so there are no stored-but-never-boosted words."""
        from app.api.routes_stt import _MAX_CUSTOM_TERMS_PER_ACCOUNT
        assert _MAX_CUSTOM_TERMS_PER_ACCOUNT == stt_keyterms.KEYTERM_CAP == 50

    def test_cap_returns_409_with_limit_context(self, client, db_path, fake_account):
        from app.api.routes_stt import _MAX_CUSTOM_TERMS_PER_ACCOUNT
        for i in range(_MAX_CUSTOM_TERMS_PER_ACCOUNT):
            stt_keyterms.add_keyterm(42, f"term{i}", db_path=db_path)
        resp = client.post("/api/stt/keyterms", json={"term": "overflow"})
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error_code"] == "STT_TERM_LIMIT_REACHED"
        assert body["error_context"]["limit"] == _MAX_CUSTOM_TERMS_PER_ACCOUNT


class TestDeleteKeyterm:
    def test_removes_existing(self, client, db_path, fake_account):
        stt_keyterms.add_keyterm(42, "Atlas", db_path=db_path)
        resp = client.delete("/api/stt/keyterms/Atlas")
        assert resp.status_code == 200
        assert resp.get_json()["removed"] is True

    def test_unknown_returns_404(self, client, db_path, fake_account):
        resp = client.delete("/api/stt/keyterms/Nope")
        assert resp.status_code == 404

    def test_no_account_returns_404(self, client, no_account):
        resp = client.delete("/api/stt/keyterms/Atlas")
        assert resp.status_code == 404


class TestCrossAccountIsolation:
    def test_account_a_cannot_see_account_b(self, client, db_path, monkeypatch):
        # Account 1 inserts "Atlas".
        monkeypatch.setattr("app.api.routes_stt._resolve_account_id_for_user", lambda: 1)
        client.post("/api/stt/keyterms", json={"term": "Atlas"})

        # Account 2 lists — should NOT see Atlas.
        monkeypatch.setattr("app.api.routes_stt._resolve_account_id_for_user", lambda: 2)
        with patch("app.services.stt_keyterms.list_auto", return_value=[]):
            resp = client.get("/api/stt/keyterms")
        assert resp.get_json()["custom"] == []
