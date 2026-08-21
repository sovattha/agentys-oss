# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'API de bibliothèque de signatures multiples.

Couvre app/api/signatures.py :
- GET /api/accounts/<id>/signatures — liste + seed automatique depuis la signature compte
- POST — création (validation nom/html)
- PUT — mise à jour (propagation vers le compte si défaut)
- DELETE — suppression (promotion du suivant si défaut, clear compte si dernier)
- POST /<sig_id>/set-default — défaut exclusif + propagation vers accounts.signature/_html
- Guards : compte inconnu (404), ownership (403), account_id invalide (400)
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from app.api.app import create_app
from app.multi_accounts import AccountConfig


@pytest.fixture
def app():
    app = create_app({"TESTING": True})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def signatures_file(tmp_path):
    """Isole le store JSON dans un fichier temporaire."""
    path = tmp_path / "signatures.json"
    with patch("app.api.signatures.SIGNATURES_FILE", str(path)):
        yield path


def _make_account(signature="Cordialement,\nAlex", signature_html="<div>Cordialement,<br>Alex</div>"):
    return AccountConfig(
        id="acc1",
        name="Test",
        email="test@example.com",
        provider="gmail",
        signature=signature,
        signature_html=signature_html,
    )


@pytest.fixture
def mock_manager(signatures_file):
    """Mock du gestionnaire de comptes côté signatures API."""
    with patch("app.api.signatures.get_account_manager") as mock:
        manager = MagicMock()
        manager.get_account.return_value = _make_account()
        manager.update_account.return_value = _make_account()
        mock.return_value = manager
        yield manager


class TestListAndSeed:
    def test_list_seeds_from_account_signature(self, client, mock_manager):
        """Bibliothèque vide + compte avec signature → seed d'une entrée par défaut."""
        response = client.get("/api/accounts/acc1/signatures")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["signatures"]) == 1
        seeded = data["signatures"][0]
        assert seeded["name"] == "Signature 1"
        assert seeded["html"] == "<div>Cordialement,<br>Alex</div>"
        assert seeded["is_default"] is True
        assert data["default_id"] == seeded["id"]

    def test_list_empty_when_account_has_no_signature(self, client, mock_manager):
        mock_manager.get_account.return_value = _make_account(signature=None, signature_html=None)
        response = client.get("/api/accounts/acc1/signatures")
        assert response.status_code == 200
        data = response.get_json()
        assert data["signatures"] == []
        assert data["default_id"] is None

    def test_list_unknown_account_404(self, client, mock_manager):
        mock_manager.get_account.return_value = None
        response = client.get("/api/accounts/ghost/signatures")
        assert response.status_code == 404

    def test_list_invalid_account_id_400(self, client, mock_manager):
        response = client.get("/api/accounts/bad!id/signatures")
        assert response.status_code == 400

    def test_seed_is_idempotent(self, client, mock_manager):
        client.get("/api/accounts/acc1/signatures")
        response = client.get("/api/accounts/acc1/signatures")
        assert len(response.get_json()["signatures"]) == 1


class TestCreate:
    def test_create_signature(self, client, mock_manager):
        client.get("/api/accounts/acc1/signatures")  # seed legacy d'abord (flux réel du modal)
        response = client.post(
            "/api/accounts/acc1/signatures",
            data=json.dumps({"name": "Pro", "html": "<div>Alex — CEO</div>"}),
            content_type="application/json",
        )
        assert response.status_code == 201
        sig = response.get_json()["signature"]
        assert sig["name"] == "Pro"
        assert sig["html"] == "<div>Alex — CEO</div>"
        # Une bibliothèque déjà seedée garde son défaut : la nouvelle n'est pas défaut
        listing = client.get("/api/accounts/acc1/signatures").get_json()
        assert len(listing["signatures"]) == 2
        assert sum(1 for s in listing["signatures"] if s["is_default"]) == 1

    def test_create_first_signature_becomes_default(self, client, mock_manager):
        """Compte sans signature : la première création devient le défaut et est propagée."""
        mock_manager.get_account.return_value = _make_account(signature=None, signature_html=None)
        response = client.post(
            "/api/accounts/acc1/signatures",
            data=json.dumps({"name": "Pro", "html": "<div>Alex</div>"}),
            content_type="application/json",
        )
        assert response.status_code == 201
        assert response.get_json()["signature"]["is_default"] is True
        # Propagation vers le compte (store JSON via update_account)
        assert mock_manager.update_account.called
        kwargs = mock_manager.update_account.call_args.kwargs
        assert kwargs.get("signature_html") == "<div>Alex</div>"

    def test_create_missing_name_400(self, client, mock_manager):
        response = client.post(
            "/api/accounts/acc1/signatures",
            data=json.dumps({"html": "<div>x</div>"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_create_missing_html_400(self, client, mock_manager):
        response = client.post(
            "/api/accounts/acc1/signatures",
            data=json.dumps({"name": "Pro"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_create_name_too_long_400(self, client, mock_manager):
        response = client.post(
            "/api/accounts/acc1/signatures",
            data=json.dumps({"name": "a" * 101, "html": "<div>x</div>"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_create_html_too_large_400(self, client, mock_manager):
        response = client.post(
            "/api/accounts/acc1/signatures",
            data=json.dumps({"name": "Pro", "html": "a" * 500_001}),
            content_type="application/json",
        )
        assert response.status_code == 400


class TestUpdate:
    def _seed_two(self, client):
        client.get("/api/accounts/acc1/signatures")  # seed default
        created = client.post(
            "/api/accounts/acc1/signatures",
            data=json.dumps({"name": "Pro", "html": "<div>Pro</div>"}),
            content_type="application/json",
        ).get_json()["signature"]
        return created

    def test_update_name_and_html(self, client, mock_manager):
        sig = self._seed_two(client)
        response = client.put(
            f"/api/accounts/acc1/signatures/{sig['id']}",
            data=json.dumps({"name": "Perso", "html": "<div>Perso</div>"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        updated = response.get_json()["signature"]
        assert updated["name"] == "Perso"
        assert updated["html"] == "<div>Perso</div>"

    def test_update_default_propagates_to_account(self, client, mock_manager):
        listing = client.get("/api/accounts/acc1/signatures").get_json()
        default_id = listing["default_id"]
        mock_manager.update_account.reset_mock()
        response = client.put(
            f"/api/accounts/acc1/signatures/{default_id}",
            data=json.dumps({"html": "<div>Nouvelle</div>"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        kwargs = mock_manager.update_account.call_args.kwargs
        assert kwargs.get("signature_html") == "<div>Nouvelle</div>"

    def test_update_unknown_signature_404(self, client, mock_manager):
        client.get("/api/accounts/acc1/signatures")
        response = client.put(
            "/api/accounts/acc1/signatures/sig_ghost",
            data=json.dumps({"name": "x"}),
            content_type="application/json",
        )
        assert response.status_code == 404


class TestSetDefault:
    def test_set_default_is_exclusive_and_propagates(self, client, mock_manager):
        client.get("/api/accounts/acc1/signatures")  # seed
        second = client.post(
            "/api/accounts/acc1/signatures",
            data=json.dumps({"name": "Pro", "html": "<div>Pro</div>"}),
            content_type="application/json",
        ).get_json()["signature"]
        mock_manager.update_account.reset_mock()

        response = client.post(f"/api/accounts/acc1/signatures/{second['id']}/set-default")
        assert response.status_code == 200

        listing = client.get("/api/accounts/acc1/signatures").get_json()
        assert listing["default_id"] == second["id"]
        defaults = [s for s in listing["signatures"] if s["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["id"] == second["id"]
        # Propagation : la signature par défaut devient la signature du compte
        kwargs = mock_manager.update_account.call_args.kwargs
        assert kwargs.get("signature_html") == "<div>Pro</div>"

    def test_set_default_unknown_signature_404(self, client, mock_manager):
        client.get("/api/accounts/acc1/signatures")
        response = client.post("/api/accounts/acc1/signatures/sig_ghost/set-default")
        assert response.status_code == 404


class TestDelete:
    def test_delete_non_default(self, client, mock_manager):
        client.get("/api/accounts/acc1/signatures")
        second = client.post(
            "/api/accounts/acc1/signatures",
            data=json.dumps({"name": "Pro", "html": "<div>Pro</div>"}),
            content_type="application/json",
        ).get_json()["signature"]
        response = client.delete(f"/api/accounts/acc1/signatures/{second['id']}")
        assert response.status_code == 200
        listing = client.get("/api/accounts/acc1/signatures").get_json()
        assert len(listing["signatures"]) == 1

    def test_delete_default_promotes_next(self, client, mock_manager):
        listing = client.get("/api/accounts/acc1/signatures").get_json()
        default_id = listing["default_id"]
        second = client.post(
            "/api/accounts/acc1/signatures",
            data=json.dumps({"name": "Pro", "html": "<div>Pro</div>"}),
            content_type="application/json",
        ).get_json()["signature"]
        mock_manager.update_account.reset_mock()

        response = client.delete(f"/api/accounts/acc1/signatures/{default_id}")
        assert response.status_code == 200
        listing = client.get("/api/accounts/acc1/signatures").get_json()
        assert listing["default_id"] == second["id"]
        # Le nouveau défaut est propagé au compte
        kwargs = mock_manager.update_account.call_args.kwargs
        assert kwargs.get("signature_html") == "<div>Pro</div>"

    def test_delete_last_clears_account_signature(self, client, mock_manager):
        listing = client.get("/api/accounts/acc1/signatures").get_json()
        default_id = listing["default_id"]
        mock_manager.update_account.reset_mock()

        response = client.delete(f"/api/accounts/acc1/signatures/{default_id}")
        assert response.status_code == 200
        kwargs = mock_manager.update_account.call_args.kwargs
        assert kwargs.get("signature_html") == ""
        # Le compte reflète maintenant le clear (comme le ferait le vrai manager) :
        # le GET suivant ne doit PAS re-seeder depuis une signature vide.
        mock_manager.get_account.return_value = _make_account(signature="", signature_html="")
        listing = client.get("/api/accounts/acc1/signatures").get_json()
        assert listing["signatures"] == []

    def test_delete_unknown_signature_404(self, client, mock_manager):
        client.get("/api/accounts/acc1/signatures")
        response = client.delete("/api/accounts/acc1/signatures/sig_ghost")
        assert response.status_code == 404


class TestOwnership:
    def test_foreign_account_403(self, client, mock_manager):
        """Un compte appartenant à un autre user JWT est rejeté."""
        with patch("app.api.signatures._check_account_ownership", return_value=False):
            response = client.get("/api/accounts/acc1/signatures")
        assert response.status_code == 403

    def test_remote_without_jwt_401(self, client, mock_manager):
        """signatures_bp est dans _guarded_blueprints : un appel distant sans
        Bearer doit être rejeté AVANT toute logique (la faille trouvée en
        review était précisément l'absence de ce guard)."""
        response = client.get(
            "/api/accounts/acc1/signatures",
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )
        assert response.status_code == 401

    def test_remote_without_jwt_401_on_mutations(self, client, mock_manager):
        for method, path in [
            ("post", "/api/accounts/acc1/signatures"),
            ("put", "/api/accounts/acc1/signatures/sig_x"),
            ("delete", "/api/accounts/acc1/signatures/sig_x"),
            ("post", "/api/accounts/acc1/signatures/sig_x/set-default"),
        ]:
            response = getattr(client, method)(
                path,
                data=json.dumps({"name": "x", "html": "<div>x</div>"}),
                content_type="application/json",
                environ_base={"REMOTE_ADDR": "203.0.113.10"},
            )
            assert response.status_code == 401, f"{method.upper()} {path} -> {response.status_code}"
