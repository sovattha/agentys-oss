# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour la documentation OpenAPI/Swagger.

Spécifications:
- Endpoint /api/docs accessible avec Swagger UI
- Endpoint /api/apispec.json retourne la spec OpenAPI
- Au minimum 5 endpoints documentés (health, stats, emails, drafts, process)
"""

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def openapi_spec(client):
    """Fixture providing parsed OpenAPI spec JSON (DRY: avoids repeated HTTP calls)."""
    response = client.get("/api/apispec.json")
    return response.get_json()


def _get_path(paths: dict, endpoint: str) -> dict | None:
    """Helper to get path spec with or without /api prefix (DRY)."""
    return paths.get(f"/api{endpoint}") or paths.get(endpoint)


class TestSwaggerIntegration:

    def test_swagger_ui_accessible(self, client):
        response = client.get("/api/docs/")
        assert response.status_code == 200
        assert b"swagger" in response.data.lower()

    def test_openapi_spec_accessible(self, client):
        response = client.get("/api/apispec.json")
        assert response.status_code == 200
        data = response.get_json()
        assert "openapi" in data
        assert data["openapi"].startswith("3.0")

    def test_openapi_spec_has_info(self, openapi_spec):
        assert "info" in openapi_spec
        assert openapi_spec["info"]["title"] == "Agentys API"
        assert "version" in openapi_spec["info"]

    def test_openapi_spec_has_paths(self, openapi_spec):
        assert "paths" in openapi_spec

    def test_health_endpoint_documented(self, openapi_spec):
        paths = openapi_spec.get("paths", {})
        assert _get_path(paths, "/health") is not None

    def test_stats_endpoint_documented(self, openapi_spec):
        paths = openapi_spec.get("paths", {})
        assert _get_path(paths, "/stats") is not None

    def test_emails_endpoint_documented(self, openapi_spec):
        paths = openapi_spec.get("paths", {})
        assert _get_path(paths, "/emails") is not None

    def test_drafts_endpoint_documented(self, openapi_spec):
        paths = openapi_spec.get("paths", {})
        assert _get_path(paths, "/drafts") is not None

    def test_process_email_endpoint_documented(self, openapi_spec):
        paths = openapi_spec.get("paths", {})
        has_process = any("process" in path for path in paths.keys())
        assert has_process

    def test_at_least_5_endpoints_documented(self, openapi_spec):
        paths = openapi_spec.get("paths", {})
        assert len(paths) >= 5

    def test_generate_endpoint_documented(self, openapi_spec):
        paths = openapi_spec.get("paths", {})
        assert _get_path(paths, "/generate") is not None


class TestOpenAPISpecStructure:
    """Tests pour la structure complète de la spec OpenAPI."""

    def test_spec_content_type_is_json(self, client):
        """Vérifie que la spec est retournée en JSON."""
        response = client.get("/api/apispec.json")
        assert response.content_type.startswith("application/json")

    def test_spec_has_servers(self, openapi_spec):
        """Vérifie que les serveurs sont documentés."""
        assert "servers" in openapi_spec
        assert len(openapi_spec["servers"]) > 0

    def test_spec_server_has_url(self, openapi_spec):
        """Vérifie que chaque serveur a une URL."""
        for server in openapi_spec.get("servers", []):
            assert "url" in server

    def test_spec_info_has_contact(self, openapi_spec):
        """Vérifie que les informations de contact sont présentes."""
        assert "contact" in openapi_spec.get("info", {})

    def test_spec_info_has_description(self, openapi_spec):
        """Vérifie que la description de l'API est présente."""
        assert "description" in openapi_spec.get("info", {})
        assert len(openapi_spec["info"]["description"]) > 0


class TestOpenAPITags:
    """Tests pour les tags dans la spec OpenAPI."""

    def test_health_has_system_tag(self, openapi_spec):
        """Vérifie que /health a le tag System."""
        paths = openapi_spec.get("paths", {})
        health_path = _get_path(paths, "/health")
        if health_path and "get" in health_path:
            tags = health_path["get"].get("tags", [])
            assert "System" in tags

    def test_stats_has_statistics_tag(self, openapi_spec):
        """Vérifie que /stats a le tag Statistics."""
        paths = openapi_spec.get("paths", {})
        stats_path = _get_path(paths, "/stats")
        if stats_path and "get" in stats_path:
            tags = stats_path["get"].get("tags", [])
            assert "Statistics" in tags

    def test_emails_has_emails_tag(self, openapi_spec):
        """Vérifie que /emails a le tag Emails."""
        paths = openapi_spec.get("paths", {})
        emails_path = _get_path(paths, "/emails")
        if emails_path and "get" in emails_path:
            tags = emails_path["get"].get("tags", [])
            assert "Emails" in tags

    def test_drafts_has_drafts_tag(self, openapi_spec):
        """Vérifie que /drafts a le tag Drafts."""
        paths = openapi_spec.get("paths", {})
        drafts_path = _get_path(paths, "/drafts")
        if drafts_path and "get" in drafts_path:
            tags = drafts_path["get"].get("tags", [])
            assert "Drafts" in tags

    def test_generate_has_generate_tag(self, openapi_spec):
        """Vérifie que /generate a le tag Generate."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            tags = generate_path["post"].get("tags", [])
            assert "Generate" in tags


class TestOpenAPIResponses:
    """Tests pour les réponses documentées dans la spec OpenAPI."""

    def test_health_has_200_response(self, openapi_spec):
        """Vérifie que /health a une réponse 200 documentée."""
        paths = openapi_spec.get("paths", {})
        health_path = _get_path(paths, "/health")
        if health_path and "get" in health_path:
            responses = health_path["get"].get("responses", {})
            assert "200" in responses or 200 in responses

    def test_health_has_503_response(self, openapi_spec):
        """Vérifie que /health a une réponse 503 documentée."""
        paths = openapi_spec.get("paths", {})
        health_path = _get_path(paths, "/health")
        if health_path and "get" in health_path:
            responses = health_path["get"].get("responses", {})
            assert "503" in responses or 503 in responses

    def test_emails_has_400_response(self, openapi_spec):
        """Vérifie que /emails a une réponse 400 documentée."""
        paths = openapi_spec.get("paths", {})
        emails_path = _get_path(paths, "/emails")
        if emails_path and "get" in emails_path:
            responses = emails_path["get"].get("responses", {})
            assert "400" in responses or 400 in responses

    def test_generate_has_200_response(self, openapi_spec):
        """Vérifie que /generate a une réponse 200 documentée."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            responses = generate_path["post"].get("responses", {})
            assert "200" in responses or 200 in responses

    def test_generate_has_400_response(self, openapi_spec):
        """Vérifie que /generate a une réponse 400 documentée."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            responses = generate_path["post"].get("responses", {})
            assert "400" in responses or 400 in responses

    def test_generate_has_401_response(self, openapi_spec):
        """Vérifie que /generate a une réponse 401 documentée."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            responses = generate_path["post"].get("responses", {})
            assert "401" in responses or 401 in responses

    def test_generate_has_404_response(self, openapi_spec):
        """Vérifie que /generate a une réponse 404 documentée."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            responses = generate_path["post"].get("responses", {})
            assert "404" in responses or 404 in responses

    def test_generate_has_500_response(self, openapi_spec):
        """Vérifie que /generate a une réponse 500 documentée."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            responses = generate_path["post"].get("responses", {})
            assert "500" in responses or 500 in responses


class TestOpenAPIParameters:
    """Tests pour les paramètres documentés dans la spec OpenAPI."""

    def test_emails_has_limit_parameter(self, openapi_spec):
        """Vérifie que /emails a le paramètre limit documenté."""
        paths = openapi_spec.get("paths", {})
        emails_path = _get_path(paths, "/emails")
        if emails_path and "get" in emails_path:
            params = emails_path["get"].get("parameters", [])
            param_names = [p.get("name") for p in params]
            assert "limit" in param_names

    def test_drafts_has_pagination_parameters(self, openapi_spec):
        """Vérifie que /drafts a les paramètres de pagination."""
        paths = openapi_spec.get("paths", {})
        drafts_path = _get_path(paths, "/drafts")
        if drafts_path and "get" in drafts_path:
            params = drafts_path["get"].get("parameters", [])
            param_names = [p.get("name") for p in params]
            assert "limit" in param_names
            assert "offset" in param_names

    def test_drafts_has_category_filter_parameter(self, openapi_spec):
        """Vérifie que /drafts a le paramètre category."""
        paths = openapi_spec.get("paths", {})
        drafts_path = _get_path(paths, "/drafts")
        if drafts_path and "get" in drafts_path:
            params = drafts_path["get"].get("parameters", [])
            param_names = [p.get("name") for p in params]
            assert "category" in param_names


class TestOpenAPIPathParameters:
    """Tests pour les path parameters documentés."""

    def test_process_email_has_email_id_parameter(self, openapi_spec):
        """Vérifie que process a le path parameter email_id."""
        paths = openapi_spec.get("paths", {})
        # Chercher un endpoint avec {email_id} dans le path
        process_paths = [
            path for path in paths.keys()
            if "process" in path and "{email_id}" in path
        ]
        assert len(process_paths) > 0, "No process endpoint with {email_id} found"

    def test_path_parameters_are_required(self, openapi_spec):
        """Vérifie que les path parameters sont marqués required."""
        paths = openapi_spec.get("paths", {})
        for path, methods in paths.items():
            if "{" in path:  # Path avec paramètre
                for method, spec in methods.items():
                    if isinstance(spec, dict) and "parameters" in spec:
                        for param in spec["parameters"]:
                            if param.get("in") == "path":
                                assert param.get("required") is True, \
                                    f"Path param in {path} should be required"


class TestSwaggerUIEdgeCases:
    """Tests edge cases pour Swagger UI."""

    def test_swagger_ui_trailing_slash_redirect(self, client):
        """Vérifie le comportement avec/sans trailing slash."""
        # Sans trailing slash devrait rediriger ou fonctionner
        response = client.get("/api/docs")
        assert response.status_code in (200, 301, 302, 308)

    def test_swagger_ui_with_trailing_slash(self, client):
        """Vérifie Swagger UI avec trailing slash."""
        response = client.get("/api/docs/")
        assert response.status_code == 200

    def test_swagger_static_accessible(self, client):
        """Vérifie que les ressources statiques flasgger sont accessibles."""
        # Note: le path exact peut varier selon la config
        response = client.get("/flasgger_static/swagger-ui.css")
        # Devrait être 200 si configuré, ou 404 si non présent
        assert response.status_code in (200, 404)

    def test_apispec_head_method(self, client):
        """Vérifie que HEAD fonctionne sur apispec."""
        response = client.head("/api/apispec.json")
        assert response.status_code == 200

    def test_apispec_options_cors(self, client):
        """Vérifie les headers CORS sur apispec."""
        response = client.options("/api/apispec.json")
        # OPTIONS devrait être géré (200 ou 405 si non supporté)
        assert response.status_code in (200, 204, 405)


class TestOpenAPISchemaContent:
    """Tests pour le contenu des schemas dans la spec."""

    def test_health_response_has_status_property(self, openapi_spec):
        """Vérifie que la réponse health a la propriété status."""
        paths = openapi_spec.get("paths", {})
        health_path = _get_path(paths, "/health")
        if health_path and "get" in health_path:
            responses = health_path["get"].get("responses", {})
            resp_200 = responses.get("200") or responses.get(200)
            if resp_200:
                content = resp_200.get("content", {})
                json_schema = content.get("application/json", {}).get("schema", {})
                properties = json_schema.get("properties", {})
                assert "status" in properties

    def test_emails_response_has_count_property(self, openapi_spec):
        """Vérifie que la réponse emails a la propriété count."""
        paths = openapi_spec.get("paths", {})
        emails_path = _get_path(paths, "/emails")
        if emails_path and "get" in emails_path:
            responses = emails_path["get"].get("responses", {})
            resp_200 = responses.get("200") or responses.get(200)
            if resp_200:
                content = resp_200.get("content", {})
                json_schema = content.get("application/json", {}).get("schema", {})
                properties = json_schema.get("properties", {})
                assert "count" in properties

    def test_drafts_response_has_pagination_properties(self, openapi_spec):
        """Vérifie que la réponse drafts a les propriétés de pagination."""
        paths = openapi_spec.get("paths", {})
        drafts_path = _get_path(paths, "/drafts")
        if drafts_path and "get" in drafts_path:
            responses = drafts_path["get"].get("responses", {})
            resp_200 = responses.get("200") or responses.get(200)
            if resp_200:
                content = resp_200.get("content", {})
                json_schema = content.get("application/json", {}).get("schema", {})
                properties = json_schema.get("properties", {})
                assert "total" in properties
                assert "limit" in properties
                assert "offset" in properties

    def test_generate_response_has_required_properties(self, openapi_spec):
        """Vérifie que /generate a toutes les propriétés requises."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            responses = generate_path["post"].get("responses", {})
            resp_200 = responses.get("200") or responses.get(200)
            if resp_200:
                content = resp_200.get("content", {})
                json_schema = content.get("application/json", {}).get("schema", {})
                properties = json_schema.get("properties", {})
                assert "success" in properties
                assert "email_id" in properties
                assert "classification" in properties
                assert "priority" in properties
                assert "status" in properties
                assert "draft" in properties

    def test_generate_has_request_body(self, openapi_spec):
        """Vérifie que /generate a un request body documenté."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            request_body = generate_path["post"].get("requestBody", {})
            assert request_body.get("required") is True
            content = request_body.get("content", {})
            assert "application/json" in content

    def test_generate_request_body_has_email_id(self, openapi_spec):
        """Vérifie que le body de /generate a email_id requis."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            request_body = generate_path["post"].get("requestBody", {})
            content = request_body.get("content", {})
            schema = content.get("application/json", {}).get("schema", {})
            properties = schema.get("properties", {})
            assert "email_id" in properties
            required = schema.get("required", [])
            assert "email_id" in required

    def test_generate_request_body_has_optional_tone(self, openapi_spec):
        """Vérifie que le body de /generate a tone avec enum."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            request_body = generate_path["post"].get("requestBody", {})
            content = request_body.get("content", {})
            schema = content.get("application/json", {}).get("schema", {})
            properties = schema.get("properties", {})
            assert "tone" in properties
            tone_prop = properties.get("tone", {})
            assert "enum" in tone_prop

    def test_generate_tone_enum_values(self, openapi_spec):
        """Vérifie que l'enum tone contient les valeurs attendues."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            request_body = generate_path["post"].get("requestBody", {})
            content = request_body.get("content", {})
            schema = content.get("application/json", {}).get("schema", {})
            properties = schema.get("properties", {})
            tone_prop = properties.get("tone", {})
            enum_values = tone_prop.get("enum", [])
            assert "formal" in enum_values
            assert "friendly" in enum_values
            assert "neutral" in enum_values
            assert len(enum_values) == 3

    def test_generate_tone_is_not_required(self, openapi_spec):
        """Vérifie que tone n'est PAS dans les champs required."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            request_body = generate_path["post"].get("requestBody", {})
            content = request_body.get("content", {})
            schema = content.get("application/json", {}).get("schema", {})
            required = schema.get("required", [])
            assert "tone" not in required

    def test_generate_has_summary(self, openapi_spec):
        """Vérifie que /generate a un summary documenté."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            summary = generate_path["post"].get("summary", "")
            assert len(summary) > 0

    def test_generate_has_description(self, openapi_spec):
        """Vérifie que /generate a une description documentée."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            description = generate_path["post"].get("description", "")
            assert len(description) > 0

    def test_generate_draft_has_nested_properties(self, openapi_spec):
        """Vérifie que le schema draft a les propriétés subject, body, tokens_used."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            responses = generate_path["post"].get("responses", {})
            resp_200 = responses.get("200") or responses.get(200)
            if resp_200:
                content = resp_200.get("content", {})
                json_schema = content.get("application/json", {}).get("schema", {})
                properties = json_schema.get("properties", {})
                draft = properties.get("draft", {})
                draft_properties = draft.get("properties", {})
                assert "subject" in draft_properties
                assert "body" in draft_properties
                assert "tokens_used" in draft_properties

    def test_generate_agents_trace_is_array(self, openapi_spec):
        """Vérifie que agents_trace est documenté comme array."""
        paths = openapi_spec.get("paths", {})
        generate_path = _get_path(paths, "/generate")
        if generate_path and "post" in generate_path:
            responses = generate_path["post"].get("responses", {})
            resp_200 = responses.get("200") or responses.get(200)
            if resp_200:
                content = resp_200.get("content", {})
                json_schema = content.get("application/json", {}).get("schema", {})
                properties = json_schema.get("properties", {})
                agents_trace = properties.get("agents_trace", {})
                assert agents_trace.get("type") == "array"


class TestSwaggerSecurityProduction:
    """Tests pour la sécurité de Swagger en production."""

    def test_swagger_ui_disabled_in_production_flask_env(self, monkeypatch):
        """Vérifie que Swagger UI est désactivé avec FLASK_ENV=production."""
        monkeypatch.setenv("FLASK_ENV", "production")
        from app.api.app import create_app
        app = create_app(config={"TESTING": True})
        client = app.test_client()

        response = client.get("/api/docs/")
        # Swagger UI désactivé = 404 ou pas de swagger dans le contenu
        if response.status_code == 200:
            assert b"swagger" not in response.data.lower()
        else:
            assert response.status_code == 404

    def test_swagger_ui_disabled_in_production_environment(self, monkeypatch):
        """Vérifie que Swagger UI est désactivé avec ENVIRONMENT=production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        from app.api.app import create_app
        app = create_app(config={"TESTING": True})
        client = app.test_client()

        response = client.get("/api/docs/")
        if response.status_code == 200:
            assert b"swagger" not in response.data.lower()
        else:
            assert response.status_code == 404

    @pytest.mark.skip(reason="Obsolète post audits sécurité 2026-04 — auth/admin requise. À refactorer hors scope migration runner Hetzner.")
    def test_apispec_still_available_in_production(self, monkeypatch):
        """Vérifie que la spec OpenAPI reste disponible en production.

        Note: La spec JSON reste accessible car certaines intégrations
        en ont besoin (monitoring, tests automatisés).
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        from app.api.app import create_app
        app = create_app(config={"TESTING": True})
        client = app.test_client()

        response = client.get("/api/apispec.json")
        assert response.status_code == 200

    def test_swagger_ui_enabled_in_development(self, monkeypatch):
        """Vérifie que Swagger UI est activé en développement."""
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        from app.api.app import create_app
        app = create_app(config={"TESTING": True})
        client = app.test_client()

        response = client.get("/api/docs/")
        assert response.status_code == 200
        assert b"swagger" in response.data.lower()
