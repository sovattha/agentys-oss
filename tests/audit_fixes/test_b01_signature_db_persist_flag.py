# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit e2e 2026-06-10 B-01 : échec du persist DB signature → flag honnête.

Avant le fix, un échec de la persistance SQLite de la signature (exception DB,
row accounts absente) était avalé en ``logger.warning`` et l'endpoint répondait
``success: true`` sec. Or ``get_account_signature`` lit la row DB en priorité :
les ENVOIS continuaient avec l'ancienne signature pendant que le Settings (qui
lit le JSON) affichait la nouvelle — et la perte de ``signature_user_modified``
laissait le prochain re-login OAuth écraser la signature custom.

Contrat : quand le persist DB échoue, la réponse porte
``signature_db_persisted: false`` (le JSON, lui, a bien été mis à jour, donc
``success`` reste true). Quand tout passe, le flag est absent (pas de bruit).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_account(email: str = "jean@hotmail.com"):
    account = MagicMock()
    account.id = "acc-123"
    account.name = "Perso"
    account.email = email
    account.provider = "gmail"
    account.status = "connected"
    account.signature = "Ancienne"
    account.signature_html = "<p>Ancienne</p>"
    account.check_interval_minutes = 5
    account.max_emails_per_batch = 10
    account.auto_reply_enabled = True
    account.draft_only = False
    account.default_language = "fr"
    account.created_at = "2026-01-01T00:00:00"
    account.last_sync = None
    account.last_error = None
    account.email_count = 0
    account.user_id = None
    return account


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _put_signature(client, db_session_patch):
    account = _mock_account()
    with patch("app.api.accounts.get_account_manager") as mock_mgr, \
         db_session_patch, \
         patch("app.api.accounts._get_auth_user_id", return_value=None):
        mgr = MagicMock()
        mgr.get_account.return_value = account
        mgr.update_account.return_value = account
        mock_mgr.return_value = mgr
        return client.patch(
            f"/api/accounts/{account.id}",
            json={"signature": "Nouvelle signature"},
        )


def test_put_signature_db_failure_flags_response(client):
    resp = _put_signature(
        client,
        patch("app.api.accounts.get_db_session", side_effect=RuntimeError("database is locked")),
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["signature_db_persisted"] is False


def test_put_signature_db_ok_has_no_flag(client):
    # get_db_session en MagicMock pur : le context manager rend une session
    # factice dont la chaîne query → first() retourne un db_acc truthy.
    resp = _put_signature(client, patch("app.api.accounts.get_db_session"))

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "signature_db_persisted" not in data


def test_sync_signature_db_failure_flags_response(client):
    account = _mock_account()
    mock_provider = MagicMock()
    mock_provider.authenticate.return_value = True
    mock_provider.get_signature.return_value = {"html": "<p>Sig</p>", "text": "Sig"}

    with patch("app.api.accounts.get_account_manager") as mock_mgr, \
         patch("app.multi_accounts.create_provider_for_account", return_value=mock_provider), \
         patch("app.api.accounts.get_db_session", side_effect=RuntimeError("database is locked")), \
         patch("app.api.accounts._get_auth_user_id", return_value=None):
        mgr = MagicMock()
        mgr.get_account.return_value = account
        mgr.update_account.return_value = account
        mock_mgr.return_value = mgr

        resp = client.post(f"/api/accounts/{account.id}/sync-signature")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["signature_db_persisted"] is False
