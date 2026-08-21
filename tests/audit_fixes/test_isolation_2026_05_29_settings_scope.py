# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 — specialties + agent-marketplace read/wrote the GLOBAL
data/settings.json (no account_id), so one tenant's Expert-Mode activations /
installed agents leaked to and were toggleable by every other tenant.

Fix: both thread account_id into load_settings/save_settings (matching the
canonical /api/settings path), so state lives in the per-account DB store.

Run: pytest tests/audit_fixes/test_isolation_2026_05_29_settings_scope.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

REMOTE = {"REMOTE_ADDR": "203.0.113.10"}
AUTH = {"Authorization": "Bearer tok"}
JWT = {"sub": "7", "email": "tenant7@corp.com"}
ACCT = 7


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


# --------------------------------------------------------------------------- #
# Specialties
# --------------------------------------------------------------------------- #

def test_specialties_list_loads_per_account(client):
    engine = MagicMock()
    engine.list_specialties.return_value = []
    load = MagicMock(return_value={})
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.specialties.get_specialty_engine", return_value=engine), \
         patch("app.api.specialties._get_current_account_id", return_value=ACCT), \
         patch("app.api.specialties.load_settings", load):
        resp = client.get("/api/specialties", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    load.assert_called_once_with(account_id=ACCT)


def test_specialties_activate_saves_per_account(client):
    engine = MagicMock()
    engine.get_specialty.return_value = {"specialty_id": "legal"}
    save = MagicMock(return_value=True)
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.specialties.get_specialty_engine", return_value=engine), \
         patch("app.api.specialties._get_current_account_id", return_value=ACCT), \
         patch("app.api.specialties.load_settings", MagicMock(return_value={})), \
         patch("app.api.specialties.save_settings", save):
        resp = client.post("/api/specialties/legal/activate", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    assert save.call_args.kwargs.get("account_id") == ACCT


# --------------------------------------------------------------------------- #
# Agent marketplace
# --------------------------------------------------------------------------- #

def test_marketplace_installed_loads_per_account(client):
    load = MagicMock(return_value={})
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.agent_marketplace._get_current_account_id", return_value=ACCT), \
         patch("app.api.agent_marketplace.load_settings", load):
        resp = client.get("/api/agent-marketplace/installed", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    load.assert_called_once_with(account_id=ACCT)


def test_marketplace_subscribe_saves_per_account(client):
    save = MagicMock(return_value=True)
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.agent_marketplace._CATALOG", [{"id": "faq", "name": "FAQ"}]), \
         patch("app.api.agent_marketplace._get_current_account_id", return_value=ACCT), \
         patch("app.api.agent_marketplace.load_settings", MagicMock(return_value={})), \
         patch("app.api.agent_marketplace.save_settings", save):
        resp = client.post("/api/agent-marketplace/faq/subscribe", headers=AUTH, environ_base=REMOTE)
    assert resp.status_code == 200
    assert save.call_args.kwargs.get("account_id") == ACCT
