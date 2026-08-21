# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'API REST EmailTemplates.

pytest tests/api/test_email_templates.py -v
"""

import json
import pytest
from unittest.mock import patch

from flask import Flask

from app.api.email_templates import (
    email_templates_bp,
    reset_store,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def app(tmp_path):
    """App Flask de test."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(email_templates_bp, url_prefix="/api")

    # Reset le store global et utiliser un fichier temporaire
    reset_store()

    # Patch le filepath du store
    with patch(
        "app.infrastructure.email_template_store.TEMPLATES_FILE",
        tmp_path / "test_templates.json",
    ):
        yield app

    reset_store()


@pytest.fixture
def client(app):
    """Client de test."""
    return app.test_client()


@pytest.fixture
def sample_template_data():
    """Données de template de test."""
    return {
        "name": "Test Template",
        "category": "OTHER",  # Valid category for testing
        "template_body": "Hello ${sender_name}!",
        "description": "A test template",
        "language": "en",
        "priority": 50,
    }


# ============================================================================
# TESTS LIST TEMPLATES
# ============================================================================


class TestListTemplates:
    """Tests pour GET /api/templates."""

    def test_list_templates_returns_200(self, client):
        """List templates retourne 200."""
        response = client.get("/api/templates")
        assert response.status_code == 200

    def test_list_templates_returns_json(self, client):
        """List templates retourne du JSON."""
        response = client.get("/api/templates")
        assert response.content_type == "application/json"

    def test_list_templates_contains_templates_key(self, client):
        """List templates contient la clé templates."""
        response = client.get("/api/templates")
        data = json.loads(response.data)
        assert "templates" in data
        assert "count" in data

    def test_list_templates_with_category_filter(self, client):
        """List templates avec filtre catégorie."""
        response = client.get("/api/templates?category=URGENT")
        data = json.loads(response.data)
        assert response.status_code == 200
        for template in data["templates"]:
            assert template["category"] == "URGENT"

    def test_list_templates_with_unknown_category(self, client):
        """List templates avec catégorie inconnue retourne 400."""
        response = client.get("/api/templates?category=UNKNOWN_XYZ")
        # Validation now rejects invalid categories
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data


# ============================================================================
# TESTS CREATE TEMPLATE
# ============================================================================


class TestCreateTemplate:
    """Tests pour POST /api/templates."""

    def test_create_template_returns_201(self, client, sample_template_data):
        """Create template retourne 201."""
        response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        assert response.status_code == 201

    def test_create_template_returns_created_template(
        self, client, sample_template_data
    ):
        """Create template retourne le template créé."""
        response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data["name"] == sample_template_data["name"]
        assert "id" in data

    def test_create_template_generates_id_if_missing(
        self, client, sample_template_data
    ):
        """Create template génère un ID si manquant."""
        response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data["id"] is not None
        assert len(data["id"]) == 8

    def test_create_template_uses_provided_id(self, client, sample_template_data):
        """Create template utilise l'ID fourni."""
        sample_template_data["id"] = "custom-id"
        response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data["id"] == "custom-id"

    def test_create_template_requires_json(self, client):
        """Create template requiert JSON."""
        response = client.post("/api/templates")
        # Flask retourne 415 quand pas de Content-Type, 400 quand JSON vide
        assert response.status_code in [400, 415]

    def test_create_template_missing_name(self, client, sample_template_data):
        """Create template avec nom manquant."""
        del sample_template_data["name"]
        response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "Name" in data["error"] or "name" in data["error"].lower()

    def test_create_template_missing_category(self, client, sample_template_data):
        """Create template avec catégorie manquante."""
        del sample_template_data["category"]
        response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "Category" in data["error"] or "category" in data["error"].lower()

    def test_create_template_missing_template_body(self, client, sample_template_data):
        """Create template avec corps manquant."""
        del sample_template_data["template_body"]
        response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "Template body" in data["error"] or "template_body" in data["error"].lower()


# ============================================================================
# TESTS GET TEMPLATE
# ============================================================================


class TestGetTemplate:
    """Tests pour GET /api/templates/<id>."""

    def test_get_template_returns_200(self, client, sample_template_data):
        """Get template retourne 200."""
        # Créer d'abord
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        created = json.loads(create_response.data)

        response = client.get(f"/api/templates/{created['id']}")
        assert response.status_code == 200

    def test_get_template_returns_template(self, client, sample_template_data):
        """Get template retourne le template."""
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        created = json.loads(create_response.data)

        response = client.get(f"/api/templates/{created['id']}")
        data = json.loads(response.data)
        assert data["name"] == sample_template_data["name"]

    def test_get_template_not_found(self, client):
        """Get template non trouvé retourne 404."""
        response = client.get("/api/templates/nonexistent-id")
        assert response.status_code == 404
        data = json.loads(response.data)
        assert "error" in data


# ============================================================================
# TESTS UPDATE TEMPLATE
# ============================================================================


class TestUpdateTemplate:
    """Tests pour PUT /api/templates/<id>."""

    def test_update_template_returns_200(self, client, sample_template_data):
        """Update template retourne 200."""
        # Créer d'abord
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        created = json.loads(create_response.data)

        # Mettre à jour
        sample_template_data["name"] = "Updated Name"
        response = client.put(
            f"/api/templates/{created['id']}",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_update_template_changes_data(self, client, sample_template_data):
        """Update template modifie les données."""
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        created = json.loads(create_response.data)

        sample_template_data["name"] = "Updated Name"
        response = client.put(
            f"/api/templates/{created['id']}",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data["name"] == "Updated Name"

    def test_update_template_not_found(self, client, sample_template_data):
        """Update template non trouvé retourne 404."""
        response = client.put(
            "/api/templates/nonexistent-id",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_update_template_requires_json(self, client):
        """Update template requiert JSON."""
        response = client.put("/api/templates/some-id")
        # Flask retourne 415 quand pas de Content-Type, 400 quand JSON vide
        assert response.status_code in [400, 415]


# ============================================================================
# TESTS DELETE TEMPLATE
# ============================================================================


class TestDeleteTemplate:
    """Tests pour DELETE /api/templates/<id>."""

    def test_delete_template_returns_200(self, client, sample_template_data):
        """Delete template retourne 200."""
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        created = json.loads(create_response.data)

        response = client.delete(f"/api/templates/{created['id']}")
        assert response.status_code == 200

    def test_delete_template_removes_template(self, client, sample_template_data):
        """Delete template supprime le template."""
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        created = json.loads(create_response.data)

        client.delete(f"/api/templates/{created['id']}")

        get_response = client.get(f"/api/templates/{created['id']}")
        assert get_response.status_code == 404

    def test_delete_template_not_found(self, client):
        """Delete template non trouvé retourne 404."""
        response = client.delete("/api/templates/nonexistent-id")
        assert response.status_code == 404


# ============================================================================
# TESTS MATCH TEMPLATE
# ============================================================================


class TestMatchTemplate:
    """Tests pour POST /api/templates/match."""

    def test_match_template_returns_200(self, client):
        """Match template retourne 200."""
        response = client.post(
            "/api/templates/match",
            data=json.dumps({
                "category": "URGENT",
                "subject": "Important",
                "body": "Urgent matter",
            }),
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_match_template_returns_match(self, client):
        """Match template retourne un match."""
        response = client.post(
            "/api/templates/match",
            data=json.dumps({
                "category": "URGENT",
                "subject": "Important",
                "body": "Urgent matter",
            }),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert "match" in data
        if data["match"]:
            assert "template" in data["match"]
            assert "score" in data["match"]

    def test_match_template_with_language(self, client):
        """Match template avec langue."""
        response = client.post(
            "/api/templates/match",
            data=json.dumps({
                "category": "URGENT",
                "subject": "Important",
                "body": "Urgent",
                "language": "fr",
            }),
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_match_template_requires_json(self, client):
        """Match template requiert JSON."""
        response = client.post("/api/templates/match")
        # Flask retourne 415 quand pas de Content-Type, 400 quand JSON vide
        assert response.status_code in [400, 415]

    def test_match_template_missing_category(self, client):
        """Match template avec catégorie manquante."""
        response = client.post(
            "/api/templates/match",
            data=json.dumps({
                "subject": "Subject",
                "body": "Body",
            }),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "category" in data["error"]

    def test_match_template_missing_subject(self, client):
        """Match template avec sujet manquant."""
        response = client.post(
            "/api/templates/match",
            data=json.dumps({
                "category": "URGENT",
                "body": "Body",
            }),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "subject" in data["error"]

    def test_match_template_missing_body(self, client):
        """Match template avec corps manquant."""
        response = client.post(
            "/api/templates/match",
            data=json.dumps({
                "category": "URGENT",
                "subject": "Subject",
            }),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "body" in data["error"]

    def test_match_template_no_match_returns_null(self, client):
        """Match template avec catégorie invalide retourne 400."""
        response = client.post(
            "/api/templates/match",
            data=json.dumps({
                "category": "UNKNOWN_CATEGORY_XYZ",
                "subject": "Subject",
                "body": "Body",
            }),
            content_type="application/json",
        )
        # Validation now rejects invalid categories
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data


# ============================================================================
# TESTS RENDER TEMPLATE
# ============================================================================


class TestRenderTemplate:
    """Tests pour POST /api/templates/<id>/render."""

    def test_render_template_returns_200(self, client, sample_template_data):
        """Render template retourne 200."""
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        created = json.loads(create_response.data)

        response = client.post(
            f"/api/templates/{created['id']}/render",
            data=json.dumps({"variables": {"sender_name": "John"}}),
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_render_template_returns_rendered(self, client, sample_template_data):
        """Render template retourne le rendu."""
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        created = json.loads(create_response.data)

        response = client.post(
            f"/api/templates/{created['id']}/render",
            data=json.dumps({"variables": {"sender_name": "John"}}),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert "rendered" in data
        assert "John" in data["rendered"]

    def test_render_template_not_found(self, client):
        """Render template non trouvé retourne 404."""
        response = client.post(
            "/api/templates/nonexistent-id/render",
            data=json.dumps({"variables": {}}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_render_template_requires_json(self, client, sample_template_data):
        """Render template requiert JSON."""
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        created = json.loads(create_response.data)

        response = client.post(f"/api/templates/{created['id']}/render")
        # Flask retourne 415 quand pas de Content-Type, 400 quand JSON vide
        assert response.status_code in [400, 415]

    def test_render_template_empty_variables(self, client, sample_template_data):
        """Render template avec variables vides."""
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        created = json.loads(create_response.data)

        # Le require_json décorator demande un body JSON non-vide
        # donc on passe un object avec variables vide
        response = client.post(
            f"/api/templates/{created['id']}/render",
            data=json.dumps({"variables": {}}),
            content_type="application/json",
        )
        assert response.status_code == 200


# ============================================================================
# TESTS GET STATS
# ============================================================================


class TestGetStats:
    """Tests pour GET /api/templates/stats."""

    def test_get_stats_returns_200(self, client):
        """Get stats retourne 200."""
        response = client.get("/api/templates/stats")
        assert response.status_code == 200

    def test_get_stats_returns_stats(self, client):
        """Get stats retourne les stats."""
        response = client.get("/api/templates/stats")
        data = json.loads(response.data)
        assert "total" in data
        assert "enabled" in data
        assert "by_category" in data


# ============================================================================
# TESTS EDGE CASES
# ============================================================================


class TestApiEdgeCases:
    """Tests des cas limites pour l'API."""

    def test_create_template_with_unicode(self, client):
        """Create template avec unicode."""
        response = client.post(
            "/api/templates",
            data=json.dumps({
                "name": "Événement Spécial 🎉",
                "category": "MEETING",  # Valid category
                "template_body": "Bonjour ${nom}! 日本語",
            }),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = json.loads(response.data)
        assert "🎉" in data["name"]

    def test_create_template_with_special_characters(self, client):
        """Create template avec caractères spéciaux."""
        response = client.post(
            "/api/templates",
            data=json.dumps({
                "name": "Test <script> & \"quotes\"",
                "category": "OTHER",  # Valid category
                "template_body": "<html>${content}</html>",
            }),
            content_type="application/json",
        )
        assert response.status_code == 201

    def test_invalid_json_returns_400(self, client):
        """JSON invalide retourne 400."""
        response = client.post(
            "/api/templates",
            data="not valid json {{{",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_empty_json_object_returns_400(self, client):
        """Objet JSON vide retourne 400."""
        response = client.post(
            "/api/templates",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_get_template_with_special_characters_in_id(
        self, client, sample_template_data
    ):
        """Get template avec caractères spéciaux dans l'ID retourne 400."""
        # ID validation now rejects special characters for security
        sample_template_data["id"] = "special-@#$"
        create_response = client.post(
            "/api/templates",
            data=json.dumps(sample_template_data),
            content_type="application/json",
        )
        # Creation should fail with invalid ID
        assert create_response.status_code == 400

        # Get with invalid ID should also fail validation
        response = client.get("/api/templates/special-@#$")
        assert response.status_code == 400
