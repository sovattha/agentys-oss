# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'API REST Labels.

pytest tests/api/test_labels.py -v
"""

import pytest
from unittest.mock import ANY, MagicMock, patch

from flask import Flask

from app.api.labels import (
    labels_bp,
    validate_label_name,
    validate_email_address,
    MAX_NAME_LENGTH,
    MAX_CONDITION_LENGTH,
)
from app.domain.entities.email_labels import (
    EmailLabel,
    LabelAssignment,
    LabelingRule,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def app():
    """App Flask de test.

    Isolation : ``labels_bp`` est un singleton module-level. L'enregistrer ici
    pose ``_got_registered_once=True`` de façon permanente ; un ``create_app()``
    ultérieur (autre fichier de test du même shard) verrait alors
    ``add_auth_guard`` sauter le before_request d'auth (app/api/auth.py — skip si
    le blueprint est déjà enregistré) et ``g.auth_user`` ne serait jamais posé
    (régression observée sur test_isolation…learn_identity en shard CI). On
    restaure le marqueur en teardown.
    """
    app = Flask(__name__)
    app.config["TESTING"] = True
    _was_registered = getattr(labels_bp, "_got_registered_once", False)
    app.register_blueprint(labels_bp, url_prefix="/api/labels")
    yield app
    labels_bp._got_registered_once = _was_registered


@pytest.fixture
def client(app):
    """Client de test."""
    return app.test_client()


@pytest.fixture(autouse=True)
def active_account():
    """Compte actif par défaut pour les routes labels scopées par compte."""
    with patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
        yield


@pytest.fixture
def mock_container():
    """Mock du container avec tous les services nécessaires."""
    # Invalide le cache module-level entre les tests pour éviter les faux positifs.
    # C-1 audit (2026-04-25): _labels_cache became a dict keyed per
    # account_id; use the public invalidator instead of touching the
    # backing storage so the test stays robust if the shape changes again.
    import app.api.labels as labels_module
    labels_module._invalidate_labels_cache()

    container = MagicMock()
    store = MagicMock()

    # Configuration par défaut du store
    store.get_labels.return_value = []
    store.get_label.return_value = None
    store.add_label.return_value = True
    store.update_label.return_value = True
    store.delete_label.return_value = True
    store.get_rules.return_value = []
    store.add_rule.return_value = True
    store.delete_rule.return_value = True
    store.get_vip_senders.return_value = []
    store.get_assignment.return_value = None
    store.save_assignment.return_value = True
    store.get_rules_markdown.return_value = "# Rules\n\nNo rules yet."

    container.get_label_store.return_value = store

    # Mock use cases
    label_use_case = MagicMock()
    learn_use_case = MagicMock()
    container.get_label_email_use_case.return_value = label_use_case
    container.get_learn_labeling_rule_use_case.return_value = learn_use_case

    return container, store, label_use_case, learn_use_case


@pytest.fixture
def sample_label():
    """Label de test."""
    return EmailLabel(
        name="TestLabel",
        color="#ff0000",
        description="A test label",
        is_default=False,
        is_favorite=True,
    )


@pytest.fixture
def sample_rule():
    """Règle de test."""
    return LabelingRule(
        rule_id="abc12345",
        label_name="TestLabel",
        condition_type="sender",
        condition_value="test@example.com",
        priority=50,
        confidence=0.9,
    )


@pytest.fixture
def sample_assignment():
    """Assignation de test."""
    return LabelAssignment(
        email_id="email-123",
        labels=["TestLabel"],
        confidences={"TestLabel": 0.9},
        reasons={"TestLabel": "Matched sender rule"},
        assigned_by="ai",
    )


class TestGetLabelCounts:
    """Tests pour GET /api/labels/counts."""

    def test_counts_use_one_canonical_assignment_per_email(self, client):
        """Les badges ne doivent pas compter un ancien label global en conflit."""

        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        class _Session:
            def execute(self, statement, params):
                sql = str(statement)
                assert params == {"aid": 7, "is_sent": False}
                if "FROM email_labels" in sql:
                    return _Result([
                        ("m2", "Noise"),  # duplicate of JSON, should count once
                        ("m3", "Noise"),  # SQL-only Noise, should still count
                        ("m4", "FYI"),
                    ])
                return _Result([("m1",), ("m2",), ("m3",), ("m4",)])

        class _SessionContext:
            def __enter__(self):
                return _Session()

            def __exit__(self, *_exc):
                return False

        global_store = MagicMock()
        global_store.get_assignments_batch.return_value = {
            "m1": LabelAssignment(email_id="m1", labels=["Action"]),
            "m2": LabelAssignment(email_id="m2", labels=["FYI"]),
        }
        account_store = MagicMock()
        account_store.get_assignments_batch.return_value = {
            "m2": LabelAssignment(email_id="m2", labels=["Noise"]),
        }
        container = MagicMock()
        container.get_label_store.side_effect = (
            lambda *_, **kwargs: account_store
            if kwargs.get("account_id") == 7
            else global_store
        )

        with (
            patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=7),
            patch("app.db.database.get_db_session", return_value=_SessionContext()),
            patch("app.api.labels.get_container", return_value=container),
        ):
            response = client.get("/api/labels/counts")

        assert response.status_code == 200
        data = response.get_json()
        assert data["total"] == 4
        assert data["counts"] == {"Action": 1, "Noise": 2, "FYI": 1}


# ============================================================================
# TESTS VALIDATION HELPERS
# ============================================================================


class TestValidateLabelName:
    """Tests pour validate_label_name()."""

    def test_valid_name(self):
        """Nom valide retourne True."""
        valid, error = validate_label_name("MyLabel")
        assert valid is True
        assert error is None

    def test_valid_name_with_spaces(self):
        """Nom avec espaces est valide."""
        valid, error = validate_label_name("My Label")
        assert valid is True

    def test_valid_name_with_underscore(self):
        """Nom avec underscore est valide."""
        valid, error = validate_label_name("My_Label")
        assert valid is True

    def test_valid_name_with_dash(self):
        """Nom avec tiret est valide."""
        valid, error = validate_label_name("My-Label")
        assert valid is True

    def test_valid_name_with_numbers(self):
        """Nom avec chiffres est valide."""
        valid, error = validate_label_name("Label123")
        assert valid is True

    def test_empty_name(self):
        """Nom vide retourne erreur."""
        valid, error = validate_label_name("")
        assert valid is False
        assert "required" in error.lower()

    def test_whitespace_only_name(self):
        """Nom avec espaces seulement retourne erreur."""
        valid, error = validate_label_name("   ")
        assert valid is False
        assert "required" in error.lower()

    def test_name_too_long(self):
        """Nom trop long retourne erreur."""
        long_name = "A" * (MAX_NAME_LENGTH + 1)
        valid, error = validate_label_name(long_name)
        assert valid is False
        assert "max length" in error.lower()

    def test_name_with_special_chars(self):
        """Nom avec caractères spéciaux retourne erreur."""
        valid, error = validate_label_name("Label@#$")
        assert valid is False
        assert "invalid characters" in error.lower()

    def test_name_with_unicode(self):
        """L'app française accepte les caractères unicode (é, à, ç, etc.)."""
        # SAFE_NAME_PATTERN utilise re.UNICODE — les lettres accentuées sont valides
        valid, error = validate_label_name("Labelé")
        assert valid is True


class TestValidateEmailAddress:
    """Tests pour validate_email_address()."""

    def test_valid_email(self):
        """Email valide retourne True."""
        valid, error = validate_email_address("test@example.com")
        assert valid is True
        assert error is None

    def test_valid_email_with_subdomain(self):
        """Email avec sous-domaine est valide."""
        valid, error = validate_email_address("test@sub.example.com")
        assert valid is True

    def test_valid_email_with_plus(self):
        """Email avec + est valide."""
        valid, error = validate_email_address("test+tag@example.com")
        assert valid is True

    def test_empty_email(self):
        """Email vide retourne erreur."""
        valid, error = validate_email_address("")
        assert valid is False
        assert "required" in error.lower()

    def test_whitespace_only_email(self):
        """Email avec espaces seulement retourne erreur."""
        valid, error = validate_email_address("   ")
        assert valid is False
        assert "required" in error.lower()

    def test_email_too_long(self):
        """Email trop long retourne erreur."""
        # MAX_EMAIL_LENGTH is 254, so we need to exceed it
        long_email = "a" * 250 + "@test.com"  # 260 chars total > 254
        valid, error = validate_email_address(long_email)
        assert valid is False
        assert "max length" in error.lower()

    def test_invalid_email_no_at(self):
        """Email sans @ retourne erreur."""
        valid, error = validate_email_address("testexample.com")
        assert valid is False
        assert "invalid email" in error.lower()

    def test_invalid_email_no_domain(self):
        """Email sans domaine retourne erreur."""
        valid, error = validate_email_address("test@")
        assert valid is False
        assert "invalid email" in error.lower()

    def test_invalid_email_no_tld(self):
        """Email sans TLD retourne erreur."""
        valid, error = validate_email_address("test@example")
        assert valid is False
        assert "invalid email" in error.lower()


# ============================================================================
# TESTS LIST LABELS
# ============================================================================


class TestListLabels:
    """Tests pour GET /api/labels."""

    def test_list_labels_empty(self, client, mock_container):
        """Liste vide de labels."""
        container, store, _, _ = mock_container
        store.get_labels.return_value = []

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels")

        assert response.status_code == 200
        data = response.get_json()
        assert data["labels"] == []
        assert data["count"] == 0

    def test_list_labels_with_data(self, client, mock_container, sample_label):
        """Liste avec labels."""
        container, store, _, _ = mock_container
        store.get_labels.return_value = [sample_label]

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["labels"]) == 1
        assert data["count"] == 1
        assert data["labels"][0]["name"] == "TestLabel"

    def test_list_labels_multiple(self, client, mock_container):
        """Liste avec plusieurs labels."""
        container, store, _, _ = mock_container
        labels = [
            EmailLabel(name="Label1", color="#ff0000"),
            EmailLabel(name="Label2", color="#00ff00"),
            EmailLabel(name="Label3", color="#0000ff"),
        ]
        store.get_labels.return_value = labels

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["labels"]) == 3
        assert data["count"] == 3

    def test_list_labels_error(self, client, mock_container):
        """Erreur lors du listing."""
        container, store, _, _ = mock_container
        store.get_labels.side_effect = Exception("Database error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels")

        assert response.status_code == 500
        data = response.get_json()
        assert "error" in data


# ============================================================================
# TESTS CREATE LABEL
# ============================================================================


class TestCreateLabel:
    """Tests pour POST /api/labels."""

    def test_create_label_success(self, client, mock_container):
        """Création de label réussie."""
        container, store, _, _ = mock_container
        store.add_label.return_value = True

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels",
                json={"name": "NewLabel", "color": "#ff0000"},
                content_type="application/json",
            )

        assert response.status_code == 201
        data = response.get_json()
        assert data["label"]["name"] == "NewLabel"
        assert "created" in data["message"].lower()

    def test_create_label_with_description(self, client, mock_container):
        """Création avec description."""
        container, store, _, _ = mock_container
        store.add_label.return_value = True

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels",
                json={
                    "name": "NewLabel",
                    "description": "A new label",
                },
                content_type="application/json",
            )

        assert response.status_code == 201
        data = response.get_json()
        assert data["label"]["description"] == "A new label"

    def test_create_label_with_favorite(self, client, mock_container):
        """Création avec is_favorite."""
        container, store, _, _ = mock_container
        store.add_label.return_value = True

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels",
                json={
                    "name": "NewLabel",
                    "is_favorite": True,
                },
                content_type="application/json",
            )

        assert response.status_code == 201
        data = response.get_json()
        assert data["label"]["is_favorite"] is True

    def test_create_label_no_json(self, client):
        """Création sans JSON retourne erreur (400 or 415)."""
        response = client.post("/api/labels")
        # Flask returns 415 for missing Content-Type, or 400 from require_json
        assert response.status_code in [400, 415]

    def test_create_label_empty_json_body_is_400_not_500(self, client):
        """Audit 2026-05-19 STAB-02: an empty JSON body must return a clean 400,
        never a 500 that re-wraps werkzeug's error inside the broad except."""
        response = client.post(
            "/api/labels",
            data="",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_create_label_json_array_body_is_400_not_500(self, client):
        """The core STAB-02 win: a JSON array (valid JSON, wrong shape) used to
        hit `.get('name')` on a list → AttributeError → 500 with the raw
        exception string leaked. The isinstance(dict) guard now returns a clean
        JSON 400 with a generic message."""
        response = client.post(
            "/api/labels",
            json=["not", "an", "object"],
        )
        assert response.status_code == 400
        body = response.get_json()
        assert "error" in body
        assert "Traceback" not in body["error"]
        assert "has no attribute" not in body["error"]  # no leaked AttributeError

    def test_create_label_empty_name(self, client, mock_container):
        """Création avec nom vide retourne erreur."""
        container, store, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels",
                json={"name": ""},
                content_type="application/json",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_create_label_invalid_name(self, client, mock_container):
        """Création avec nom invalide retourne erreur."""
        container, store, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels",
                json={"name": "Label@#$"},
                content_type="application/json",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert "invalid" in data["error"].lower()

    def test_create_label_already_exists(self, client, mock_container):
        """Création de label existant retourne 409."""
        container, store, _, _ = mock_container
        store.add_label.return_value = False

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels",
                json={"name": "ExistingLabel"},
                content_type="application/json",
            )

        assert response.status_code == 409
        data = response.get_json()
        assert "exists" in data["error"].lower()

    def test_create_label_value_error(self, client, mock_container):
        """Création avec ValueError retourne 400."""
        container, store, _, _ = mock_container
        store.add_label.side_effect = ValueError("Invalid value")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels",
                json={"name": "NewLabel"},
                content_type="application/json",
            )

        assert response.status_code == 400

    def test_create_label_exception(self, client, mock_container):
        """Création avec exception retourne 500."""
        container, store, _, _ = mock_container
        store.add_label.side_effect = Exception("Database error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels",
                json={"name": "NewLabel"},
                content_type="application/json",
            )

        assert response.status_code == 500


# ============================================================================
# TESTS GET LABEL
# ============================================================================


class TestGetLabel:
    """Tests pour GET /api/labels/<name>."""

    def test_get_label_success(self, client, mock_container, sample_label):
        """Récupération de label réussie."""
        container, store, _, _ = mock_container
        store.get_label.return_value = sample_label

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/TestLabel")

        assert response.status_code == 200
        data = response.get_json()
        assert data["label"]["name"] == "TestLabel"

    def test_get_label_not_found(self, client, mock_container):
        """Récupération de label inexistant retourne 404."""
        container, store, _, _ = mock_container
        store.get_label.return_value = None

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/NonExistent")

        assert response.status_code == 404
        data = response.get_json()
        assert "not found" in data["error"].lower()

    def test_get_label_invalid_name(self, client, mock_container):
        """Récupération avec nom invalide retourne 400."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            # URL encode the special characters
            response = client.get("/api/labels/Label%40%23%24")

        assert response.status_code == 400
        data = response.get_json()
        assert "invalid" in data["error"].lower()

    def test_get_label_exception(self, client, mock_container):
        """Récupération avec exception retourne 500."""
        container, store, _, _ = mock_container
        store.get_label.side_effect = Exception("Database error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/TestLabel")

        assert response.status_code == 500


# ============================================================================
# TESTS UPDATE LABEL
# ============================================================================


class TestUpdateLabel:
    """Tests pour PUT /api/labels/<name>."""

    def test_update_label_color(self, client, mock_container, sample_label):
        """Mise à jour de la couleur."""
        container, store, _, _ = mock_container
        store.update_label.return_value = True
        updated_label = EmailLabel(name="TestLabel", color="#00ff00")
        store.get_label.return_value = updated_label

        with patch("app.api.labels.get_container", return_value=container):
            response = client.put(
                "/api/labels/TestLabel",
                json={"color": "#00ff00"},
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["label"]["color"] == "#00ff00"
        assert "updated" in data["message"].lower()

    def test_update_label_description(self, client, mock_container, sample_label):
        """Mise à jour de la description."""
        container, store, _, _ = mock_container
        store.update_label.return_value = True
        updated_label = EmailLabel(name="TestLabel", description="Updated desc")
        store.get_label.return_value = updated_label

        with patch("app.api.labels.get_container", return_value=container):
            response = client.put(
                "/api/labels/TestLabel",
                json={"description": "Updated desc"},
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["label"]["description"] == "Updated desc"

    def test_update_label_is_favorite(self, client, mock_container, sample_label):
        """Mise à jour de is_favorite."""
        container, store, _, _ = mock_container
        store.update_label.return_value = True
        updated_label = EmailLabel(name="TestLabel", is_favorite=False)
        store.get_label.return_value = updated_label

        with patch("app.api.labels.get_container", return_value=container):
            response = client.put(
                "/api/labels/TestLabel",
                json={"is_favorite": False},
                content_type="application/json",
            )

        assert response.status_code == 200
        store.update_label.assert_called_once()
        call_args = store.update_label.call_args[0]
        assert call_args[1]["is_favorite"] is False

    def test_update_label_no_json(self, client):
        """Mise à jour sans JSON retourne erreur (400 or 415)."""
        response = client.put("/api/labels/TestLabel")
        # Flask returns 415 for missing Content-Type, or 400 from require_json
        assert response.status_code in [400, 415]

    def test_update_label_invalid_name(self, client, mock_container):
        """Mise à jour avec nom invalide retourne 400."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.put(
                "/api/labels/Label%40%23%24",
                json={"color": "#ff0000"},
                content_type="application/json",
            )

        assert response.status_code == 400

    def test_update_label_not_found(self, client, mock_container):
        """Mise à jour de label inexistant retourne 404."""
        container, store, _, _ = mock_container
        store.update_label.return_value = False

        with patch("app.api.labels.get_container", return_value=container):
            response = client.put(
                "/api/labels/NonExistent",
                json={"color": "#ff0000"},
                content_type="application/json",
            )

        assert response.status_code == 404

    def test_update_label_exception(self, client, mock_container):
        """Mise à jour avec exception retourne 500."""
        container, store, _, _ = mock_container
        store.update_label.side_effect = Exception("Database error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.put(
                "/api/labels/TestLabel",
                json={"color": "#ff0000"},
                content_type="application/json",
            )

        assert response.status_code == 500

    def test_update_label_truncates_description(self, client, mock_container, sample_label):
        """Description trop longue est tronquée."""
        container, store, _, _ = mock_container
        store.update_label.return_value = True
        store.get_label.return_value = sample_label

        long_desc = "A" * 300  # Plus que MAX_DESCRIPTION_LENGTH (200)

        with patch("app.api.labels.get_container", return_value=container):
            response = client.put(
                "/api/labels/TestLabel",
                json={"description": long_desc},
                content_type="application/json",
            )

        assert response.status_code == 200
        # Vérifier que la description a été tronquée
        call_args = store.update_label.call_args[0]
        assert len(call_args[1]["description"]) == 200


# ============================================================================
# TESTS DELETE LABEL
# ============================================================================


class TestDeleteLabel:
    """Tests pour DELETE /api/labels/<name>."""

    def test_delete_label_success(self, client, mock_container):
        """Suppression de label réussie."""
        container, store, _, _ = mock_container
        store.delete_label.return_value = True

        with patch("app.api.labels.get_container", return_value=container):
            response = client.delete("/api/labels/TestLabel")

        assert response.status_code == 200
        data = response.get_json()
        assert "deleted" in data["message"].lower()

    def test_delete_label_not_found_returns_200(self, client, mock_container):
        """Suppression de label inexistant retourne 200 (DELETE idempotent)."""
        container, store, _, _ = mock_container
        store.delete_label.return_value = 'not_found'

        with patch("app.api.labels.get_container", return_value=container):
            response = client.delete("/api/labels/NonExistent")

        assert response.status_code == 200

    def test_delete_label_is_default_returns_400(self, client, mock_container):
        """Suppression d'un label par défaut retourne 400."""
        container, store, _, _ = mock_container
        store.delete_label.return_value = 'is_default'

        with patch("app.api.labels.get_container", return_value=container):
            response = client.delete("/api/labels/Action")

        assert response.status_code == 400
        data = response.get_json()
        assert "cannot delete" in data["error"].lower()

    def test_delete_label_invalid_name(self, client, mock_container):
        """Suppression avec nom invalide retourne 400."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.delete("/api/labels/Label%40%23%24")

        assert response.status_code == 400

    def test_delete_label_exception(self, client, mock_container):
        """Suppression avec exception retourne 500."""
        container, store, _, _ = mock_container
        store.delete_label.side_effect = Exception("Database error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.delete("/api/labels/TestLabel")

        assert response.status_code == 500


# ============================================================================
# TESTS LIST RULES
# ============================================================================


class TestListRules:
    """Tests pour GET /api/labels/rules."""

    def test_list_rules_empty(self, client, mock_container):
        """Liste vide de règles."""
        container, store, _, _ = mock_container
        store.get_rules.return_value = []

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/rules")

        assert response.status_code == 200
        data = response.get_json()
        assert data["rules"] == []
        assert data["count"] == 0

    def test_list_rules_with_data(self, client, mock_container, sample_rule):
        """Liste avec règles."""
        container, store, _, _ = mock_container
        store.get_rules.return_value = [sample_rule]

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/rules")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["rules"]) == 1
        assert data["rules"][0]["label_name"] == "TestLabel"

    def test_list_rules_exception(self, client, mock_container):
        """Erreur lors du listing."""
        container, store, _, _ = mock_container
        store.get_rules.side_effect = Exception("Database error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/rules")

        assert response.status_code == 500


# ============================================================================
# TESTS CREATE RULE
# ============================================================================


class TestCreateRule:
    """Tests pour POST /api/labels/rules."""

    def test_create_rule_success(self, client, mock_container, sample_label):
        """Création de règle réussie."""
        container, store, _, _ = mock_container
        store.get_label.return_value = sample_label
        store.add_rule.return_value = True

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "label_name": "TestLabel",
                    "condition_type": "sender",
                    "condition_value": "test@example.com",
                },
                content_type="application/json",
            )

        assert response.status_code == 201
        data = response.get_json()
        assert data["rule"]["label_name"] == "TestLabel"

    def test_create_rule_with_priority(self, client, mock_container, sample_label):
        """Création avec priorité."""
        container, store, _, _ = mock_container
        store.get_label.return_value = sample_label
        store.add_rule.return_value = True

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "label_name": "TestLabel",
                    "condition_type": "sender",
                    "condition_value": "test@example.com",
                    "priority": 100,
                },
                content_type="application/json",
            )

        assert response.status_code == 201
        data = response.get_json()
        assert data["rule"]["priority"] == 100

    def test_create_rule_with_confidence(self, client, mock_container, sample_label):
        """Création avec confiance."""
        container, store, _, _ = mock_container
        store.get_label.return_value = sample_label
        store.add_rule.return_value = True

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "label_name": "TestLabel",
                    "condition_type": "subject",
                    "condition_value": "urgent",
                    "confidence": 0.8,
                },
                content_type="application/json",
            )

        assert response.status_code == 201
        data = response.get_json()
        assert data["rule"]["confidence"] == 0.8

    def test_create_rule_no_json(self, client):
        """Création sans JSON retourne erreur (400 or 415)."""
        response = client.post("/api/labels/rules")
        # Flask returns 415 for missing Content-Type, or 400 from require_json
        assert response.status_code in [400, 415]

    def test_create_rule_missing_label_name(self, client, mock_container):
        """Création sans label_name retourne erreur."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "condition_type": "sender",
                    "condition_value": "test@example.com",
                },
                content_type="application/json",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert "label_name" in data["error"].lower()

    def test_create_rule_invalid_condition_type(self, client, mock_container):
        """Création avec condition_type invalide retourne erreur."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "label_name": "TestLabel",
                    "condition_type": "invalid",
                    "condition_value": "test",
                },
                content_type="application/json",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert "condition_type" in data["error"].lower()

    def test_create_rule_missing_condition_value(self, client, mock_container):
        """Création sans condition_value retourne erreur."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "label_name": "TestLabel",
                    "condition_type": "sender",
                },
                content_type="application/json",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert "condition_value" in data["error"].lower()

    def test_create_rule_condition_value_too_long(self, client, mock_container):
        """Création avec condition_value trop long retourne erreur."""
        container, _, _, _ = mock_container
        long_value = "A" * (MAX_CONDITION_LENGTH + 1)

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "label_name": "TestLabel",
                    "condition_type": "sender",
                    "condition_value": long_value,
                },
                content_type="application/json",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert "too long" in data["error"].lower()

    def test_create_rule_label_not_found(self, client, mock_container):
        """Création avec label inexistant retourne 404."""
        container, store, _, _ = mock_container
        store.get_label.return_value = None

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "label_name": "NonExistent",
                    "condition_type": "sender",
                    "condition_value": "test@example.com",
                },
                content_type="application/json",
            )

        assert response.status_code == 404
        data = response.get_json()
        assert "not found" in data["error"].lower()

    def test_create_rule_already_exists(self, client, mock_container, sample_label):
        """Création de règle existante retourne 200 avec message."""
        container, store, _, _ = mock_container
        store.get_label.return_value = sample_label
        store.add_rule.return_value = False  # Similar rule exists

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "label_name": "TestLabel",
                    "condition_type": "sender",
                    "condition_value": "test@example.com",
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert "already exists" in data["message"].lower()

    def test_create_rule_value_error(self, client, mock_container, sample_label):
        """Création avec ValueError retourne 400."""
        container, store, _, _ = mock_container
        store.get_label.return_value = sample_label
        store.add_rule.side_effect = ValueError("Invalid priority")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "label_name": "TestLabel",
                    "condition_type": "sender",
                    "condition_value": "test@example.com",
                    "priority": "invalid",
                },
                content_type="application/json",
            )

        assert response.status_code == 400

    def test_create_rule_exception(self, client, mock_container, sample_label):
        """Création avec exception retourne 500."""
        container, store, _, _ = mock_container
        store.get_label.return_value = sample_label
        store.add_rule.side_effect = Exception("Database error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/rules",
                json={
                    "label_name": "TestLabel",
                    "condition_type": "sender",
                    "condition_value": "test@example.com",
                },
                content_type="application/json",
            )

        assert response.status_code == 500

    def test_create_rule_all_condition_types(self, client, mock_container, sample_label):
        """Création avec tous les types de condition valides."""
        container, store, _, _ = mock_container
        store.get_label.return_value = sample_label
        store.add_rule.return_value = True

        valid_types = ["sender", "subject", "body", "cc", "recipient"]

        for condition_type in valid_types:
            with patch("app.api.labels.get_container", return_value=container):
                response = client.post(
                    "/api/labels/rules",
                    json={
                        "label_name": "TestLabel",
                        "condition_type": condition_type,
                        "condition_value": "test",
                    },
                    content_type="application/json",
                )
            assert response.status_code == 201, f"Failed for {condition_type}"


# ============================================================================
# TESTS DELETE RULE
# ============================================================================


class TestDeleteRule:
    """Tests pour DELETE /api/labels/rules/<rule_id>."""

    def test_delete_rule_success(self, client, mock_container):
        """Suppression de règle réussie."""
        container, store, _, _ = mock_container
        store.delete_rule.return_value = True

        with patch("app.api.labels.get_container", return_value=container):
            response = client.delete("/api/labels/rules/abc12345")

        assert response.status_code == 200
        data = response.get_json()
        assert "deleted" in data["message"].lower()

    def test_delete_rule_not_found(self, client, mock_container):
        """Suppression de règle inexistante retourne 404."""
        container, store, _, _ = mock_container
        store.delete_rule.return_value = False

        with patch("app.api.labels.get_container", return_value=container):
            response = client.delete("/api/labels/rules/nonexistent")

        assert response.status_code == 404
        data = response.get_json()
        assert "not found" in data["error"].lower()

    def test_delete_rule_invalid_id(self, client, mock_container):
        """Suppression avec ID invalide retourne 400."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.delete("/api/labels/rules/invalid@id")

        assert response.status_code == 400
        data = response.get_json()
        assert "invalid" in data["error"].lower()

    def test_delete_rule_exception(self, client, mock_container):
        """Suppression avec exception retourne 500."""
        container, store, _, _ = mock_container
        store.delete_rule.side_effect = Exception("Database error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.delete("/api/labels/rules/abc12345")

        assert response.status_code == 500


# ============================================================================
# TESTS VIP SENDERS
# ============================================================================


class TestListVipSenders:
    """Tests pour GET /api/labels/vip."""

    def test_list_vip_empty(self, client, mock_container):
        """Liste vide de VIP."""
        container, store, _, _ = mock_container
        store.get_vip_senders.return_value = []

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/vip")

        assert response.status_code == 200
        data = response.get_json()
        assert data["vip_senders"] == []
        assert data["count"] == 0

    def test_list_vip_with_data(self, client, mock_container):
        """Liste avec VIP."""
        container, store, _, _ = mock_container
        store.get_vip_senders.return_value = ["vip@example.com", "boss@company.com"]

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/vip")

        assert response.status_code == 200
        data = response.get_json()
        assert len(data["vip_senders"]) == 2
        assert data["count"] == 2

    def test_list_vip_exception(self, client, mock_container):
        """Erreur lors du listing."""
        container, store, _, _ = mock_container
        store.get_vip_senders.side_effect = Exception("Database error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/vip")

        assert response.status_code == 500


class TestAddVipSender:
    """Tests pour POST /api/labels/vip."""

    def test_add_vip_success(self, client, mock_container, sample_rule):
        """Ajout de VIP réussi."""
        container, store, _, _ = mock_container
        store.add_vip_sender.return_value = sample_rule

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/vip",
                json={"email": "vip@example.com"},
                content_type="application/json",
            )

        assert response.status_code == 201
        data = response.get_json()
        assert "rules" in data
        assert "added" in data["message"].lower()

    def test_add_vip_with_name(self, client, mock_container, sample_rule):
        """Ajout de VIP avec nom."""
        container, store, _, _ = mock_container
        store.add_vip_sender.return_value = sample_rule

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/vip",
                json={"email": "vip@example.com", "name": "VIP Person"},
                content_type="application/json",
            )

        assert response.status_code == 201
        store.add_vip_sender.assert_called_with("vip@example.com", "VIP Person")

    def test_add_vip_no_json(self, client):
        """Ajout sans JSON retourne erreur (400 or 415)."""
        response = client.post("/api/labels/vip")
        # Flask returns 415 for missing Content-Type, or 400 from require_json
        assert response.status_code in [400, 415]

    def test_add_vip_invalid_email(self, client, mock_container):
        """Ajout avec email invalide retourne erreur."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/vip",
                json={"email": "invalid-email"},
                content_type="application/json",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert "invalid" in data["error"].lower()

    def test_add_vip_empty_email(self, client, mock_container):
        """Ajout avec email vide retourne erreur."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/vip",
                json={"email": ""},
                content_type="application/json",
            )

        assert response.status_code == 400

    def test_add_vip_normalizes_email(self, client, mock_container, sample_rule):
        """Email est normalisé en minuscules."""
        container, store, _, _ = mock_container
        store.add_vip_sender.return_value = sample_rule

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/vip",
                json={"email": "VIP@EXAMPLE.COM"},
                content_type="application/json",
            )

        assert response.status_code == 201
        store.add_vip_sender.assert_called_with("vip@example.com", "")

    def test_add_vip_exception(self, client, mock_container):
        """Ajout avec exception retourne 500."""
        container, store, _, _ = mock_container
        store.add_vip_sender.side_effect = Exception("Database error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/vip",
                json={"email": "vip@example.com"},
                content_type="application/json",
            )

        assert response.status_code == 500


# ============================================================================
# TESTS ASSIGN LABELS
# ============================================================================


class TestAssignLabels:
    """Tests pour POST /api/labels/assign."""

    def test_assign_labels_success(self, client, mock_container, sample_assignment):
        """Assignation de labels réussie."""
        container, store, label_use_case, _ = mock_container
        label_use_case.execute.return_value = sample_assignment

        with patch("app.api.labels.get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
            response = client.post(
                "/api/labels/assign",
                json={
                    "email_id": "email-123",
                    "sender": "sender@example.com",
                    "subject": "Test subject",
                    "body": "Test body",
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert "assignment" in data
        assert "labels" in data

    def test_assign_labels_with_optional_fields(self, client, mock_container, sample_assignment):
        """Assignation avec champs optionnels."""
        container, store, label_use_case, _ = mock_container
        label_use_case.execute.return_value = sample_assignment

        with patch("app.api.labels.get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
            response = client.post(
                "/api/labels/assign",
                json={
                    "email_id": "email-123",
                    "sender": "sender@example.com",
                    "subject": "Test subject",
                    "body": "Test body",
                    "to": ["recipient@example.com"],
                    "cc": ["cc@example.com"],
                    "user_email": "user@example.com",
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        container.get_label_email_use_case.assert_called_with(
            user_email="user@example.com", account_id=ANY
        )

    def test_assign_labels_no_json(self, client):
        """Assignation sans JSON retourne erreur (400 or 415)."""
        response = client.post("/api/labels/assign")
        # Flask returns 415 for missing Content-Type, or 400 from require_json
        assert response.status_code in [400, 415]

    def test_assign_labels_missing_email_id(self, client, mock_container):
        """Assignation sans email_id retourne erreur."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/assign",
                json={
                    "sender": "sender@example.com",
                    "subject": "Test",
                    "body": "Test",
                },
                content_type="application/json",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert "email_id" in data["error"].lower()

    def test_assign_labels_empty_email_id(self, client, mock_container):
        """Assignation avec email_id vide retourne erreur."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/assign",
                json={
                    "email_id": "",
                    "sender": "sender@example.com",
                    "subject": "Test",
                    "body": "Test",
                },
                content_type="application/json",
            )

        assert response.status_code == 400

    def test_assign_labels_saves_assignment(self, client, mock_container, sample_assignment):
        """Assignation sauvegarde l'assignation."""
        container, store, label_use_case, _ = mock_container
        label_use_case.execute.return_value = sample_assignment

        with patch("app.api.labels.get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
            response = client.post(
                "/api/labels/assign",
                json={
                    "email_id": "email-123",
                    "sender": "sender@example.com",
                    "subject": "Test subject",
                    "body": "Test body",
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        store.save_assignment.assert_called_once_with(sample_assignment)

    def test_assign_labels_exception(self, client, mock_container):
        """Assignation avec exception retourne 500."""
        container, store, label_use_case, _ = mock_container
        label_use_case.execute.side_effect = Exception("LLM error")

        with patch("app.api.labels.get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=1):
            response = client.post(
                "/api/labels/assign",
                json={
                    "email_id": "email-123",
                    "sender": "sender@example.com",
                    "subject": "Test subject",
                    "body": "Test body",
                },
                content_type="application/json",
            )

        assert response.status_code == 500


# ============================================================================
# TESTS LEARN FROM CORRECTION
# ============================================================================


class TestLearnFromCorrection:
    """Tests pour POST /api/labels/learn."""

    def test_learn_success(self, client, mock_container, sample_rule):
        """Apprentissage réussi."""
        container, store, _, learn_use_case = mock_container
        learn_use_case.execute.return_value = [sample_rule]
        store.add_rule.return_value = True

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/learn",
                json={
                    "email_id": "email-123",
                    "sender": "sender@example.com",
                    "subject": "Test subject",
                    "body": "Test body",
                    "old_labels": ["Action"],
                    "new_labels": ["FYI"],
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert "learned_rules" in data
        assert data["rules_count"] == 1

    def test_learn_no_new_rules(self, client, mock_container):
        """Pas de nouvelles règles apprises."""
        container, store, _, learn_use_case = mock_container
        learn_use_case.execute.return_value = []

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/learn",
                json={
                    "email_id": "email-123",
                    "sender": "sender@example.com",
                    "subject": "Test subject",
                    "body": "Test body",
                    "old_labels": ["Action"],
                    "new_labels": ["Action"],  # Same labels
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["rules_count"] == 0

    def test_learn_saves_assignment(self, client, mock_container):
        """Apprentissage sauvegarde l'assignation corrigée."""
        container, store, _, learn_use_case = mock_container
        learn_use_case.execute.return_value = []

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/learn",
                json={
                    "email_id": "email-123",
                    "sender": "sender@example.com",
                    "subject": "Test subject",
                    "body": "Test body",
                    "old_labels": ["Action"],
                    "new_labels": ["FYI"],
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        store.save_assignment.assert_called()
        saved_assignment = store.save_assignment.call_args[0][0]
        assert saved_assignment.labels == ["FYI"]
        assert saved_assignment.assigned_by == "user"

    def test_learn_no_json(self, client):
        """Apprentissage sans JSON retourne erreur (400 or 415)."""
        response = client.post("/api/labels/learn")
        # Flask returns 415 for missing Content-Type, or 400 from require_json
        assert response.status_code in [400, 415]

    def test_learn_missing_email_id(self, client, mock_container):
        """Apprentissage sans email_id retourne erreur."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/learn",
                json={
                    "sender": "sender@example.com",
                    "subject": "Test",
                    "body": "Test",
                    "old_labels": [],
                    "new_labels": [],
                },
                content_type="application/json",
            )

        assert response.status_code == 400

    def test_learn_labels_not_arrays(self, client, mock_container):
        """Apprentissage avec labels non-arrays retourne erreur."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/learn",
                json={
                    "email_id": "email-123",
                    "sender": "sender@example.com",
                    "subject": "Test",
                    "body": "Test",
                    "old_labels": "Action",  # Not an array
                    "new_labels": ["Read"],
                },
                content_type="application/json",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert "arrays" in data["error"].lower()

    def test_learn_exception_returns_200_with_zero_rules(self, client, mock_container):
        """LLM failure is caught gracefully — label assignment saved, 0 rules learned."""
        container, store, _, learn_use_case = mock_container
        learn_use_case.execute.side_effect = Exception("LLM error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels/learn",
                json={
                    "email_id": "email-123",
                    "sender": "sender@example.com",
                    "subject": "Test",
                    "body": "Test",
                    "old_labels": [],
                    "new_labels": [],
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["rules_count"] == 0


# ============================================================================
# TESTS GET RULES MARKDOWN
# ============================================================================


class TestGetRulesMarkdown:
    """Tests pour GET /api/labels/rules.md."""

    def test_get_rules_markdown_success(self, client, mock_container):
        """Récupération du markdown réussie."""
        container, store, _, _ = mock_container
        store.get_rules_markdown.return_value = "# Rules\n\n- Rule 1\n- Rule 2"

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/rules.md")

        assert response.status_code == 200
        assert response.content_type.startswith("text/markdown")
        assert b"# Rules" in response.data

    def test_get_rules_markdown_empty(self, client, mock_container):
        """Récupération du markdown vide."""
        container, store, _, _ = mock_container
        store.get_rules_markdown.return_value = "# Rules\n\nNo rules yet."

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/rules.md")

        assert response.status_code == 200
        assert b"No rules" in response.data

    def test_get_rules_markdown_exception(self, client, mock_container):
        """Récupération avec exception retourne 500."""
        container, store, _, _ = mock_container
        store.get_rules_markdown.side_effect = Exception("File error")

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get("/api/labels/rules.md")

        assert response.status_code == 500


# ============================================================================
# TESTS GET ASSIGNMENT
# ============================================================================


class TestGetAssignment:
    """Tests pour GET /api/labels/assignments/<email_id>."""

    def test_get_assignment_success(self, client, mock_container, sample_assignment):
        """Récupération d'assignation réussie.

        Updated 2026-04-24 (ISO-07): the route now requires the email_id
        to belong to the caller's account. We stub `_resolve_account_id_for_user`
        and the scope check so the underlying store lookup runs.
        """
        from unittest.mock import MagicMock
        container, store, _, _ = mock_container
        store.get_assignment.return_value = sample_assignment

        # Stub the SQL scope check to confirm ownership.
        scope_session = MagicMock()
        scope_session.execute.return_value.scalar.return_value = 1

        with patch("app.api.labels.get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_for_user",
                   return_value=42), \
             patch("app.db.database.get_db_session") as mock_db:
            mock_db.return_value.__enter__.return_value = scope_session
            response = client.get("/api/labels/assignments/email-123")

        assert response.status_code == 200
        data = response.get_json()
        assert data["assignment"]["email_id"] == "email-123"

    def test_get_assignment_not_found(self, client, mock_container):
        """Récupération d'assignation inexistante retourne 404."""
        from unittest.mock import MagicMock
        container, store, _, _ = mock_container
        store.get_assignment.return_value = None

        scope_session = MagicMock()
        scope_session.execute.return_value.scalar.return_value = 1

        with patch("app.api.labels.get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_for_user",
                   return_value=42), \
             patch("app.db.database.get_db_session") as mock_db:
            mock_db.return_value.__enter__.return_value = scope_session
            response = client.get("/api/labels/assignments/nonexistent")

        assert response.status_code == 404
        data = response.get_json()
        assert "not found" in data["error"].lower()

    def test_get_assignment_invalid_id(self, client, mock_container):
        """Récupération avec ID invalide retourne 400."""
        container, _, _, _ = mock_container
        # ID trop long
        long_id = "a" * 101

        with patch("app.api.labels.get_container", return_value=container):
            response = client.get(f"/api/labels/assignments/{long_id}")

        assert response.status_code == 400

    def test_get_assignment_empty_id(self, client, mock_container):
        """Récupération avec ID vide retourne 400."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            # Flask routing won't match empty string, so this returns 404
            response = client.get("/api/labels/assignments/")

        # 308 or 404 depending on Flask version
        assert response.status_code in [308, 404]

    def test_get_assignment_exception(self, client, mock_container):
        """Récupération avec exception retourne 500."""
        from unittest.mock import MagicMock
        container, store, _, _ = mock_container
        store.get_assignment.side_effect = Exception("Database error")

        scope_session = MagicMock()
        scope_session.execute.return_value.scalar.return_value = 1

        with patch("app.api.labels.get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_for_user",
                   return_value=42), \
             patch("app.db.database.get_db_session") as mock_db:
            mock_db.return_value.__enter__.return_value = scope_session
            response = client.get("/api/labels/assignments/email-123")

        assert response.status_code == 500


# ============================================================================
# TESTS REQUIRE_JSON DECORATOR
# ============================================================================


class TestRequireJsonDecorator:
    """Tests pour le décorateur require_json."""

    def test_require_json_with_valid_json(self, client, mock_container):
        """Requête avec JSON valide passe."""
        container, store, _, _ = mock_container
        store.add_label.return_value = True

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels",
                json={"name": "TestLabel"},
                content_type="application/json",
            )

        assert response.status_code == 201

    def test_require_json_without_json(self, client):
        """Requête sans JSON retourne 400 or 415."""
        response = client.post("/api/labels")
        # Flask returns 415 for missing Content-Type, or 400 from require_json
        assert response.status_code in [400, 415]

    def test_require_json_with_empty_json(self, client, mock_container):
        """Requête avec JSON vide retourne 400."""
        container, _, _, _ = mock_container

        with patch("app.api.labels.get_container", return_value=container):
            response = client.post(
                "/api/labels",
                data="{}",
                content_type="application/json",
            )

        # Empty JSON {} is still valid JSON, should return 400 for missing name
        assert response.status_code == 400

    def test_require_json_with_invalid_content_type(self, client):
        """Requête avec content-type invalide retourne 400 or 415."""
        response = client.post(
            "/api/labels",
            data="name=TestLabel",
            content_type="application/x-www-form-urlencoded",
        )
        # Flask returns 415 for wrong Content-Type, or 400 from require_json
        assert response.status_code in [400, 415]


# ============================================================================
# /counts — unread_only query param
# ============================================================================


class TestLabelCountsUnreadOnly:
    """``GET /api/labels/counts?unread_only=true`` restricts the inbox scope
    to ``is_read = 0`` so the header tabs show Gmail-style unread badges.
    Without the flag the legacy total-count contract must be preserved
    (onboarding distribution + training settings rely on it).

    We pin the contract at the seam between the route handler and the inbox
    aggregator: the route must parse ``unread_only`` from the query string
    and forward it as a keyword arg to ``_get_inbox_label_counts``. The
    SQL-level behaviour is unit-tested via the helper itself rather than
    through the DB mock so the test does not depend on the (multi-source)
    implementation of the inbox aggregator.
    """

    def _hit(self, client, query: str, returned_counts, returned_total):
        with patch(
            "app.api.routes_helpers._resolve_account_id_for_user",
            return_value=42,
        ), patch(
            "app.api.labels._get_inbox_label_counts",
            return_value=(returned_counts, returned_total),
        ) as patched:
            response = client.get(f"/api/labels/counts{query}")
        return response, patched

    def test_default_call_passes_unread_only_false(self, client):
        """No query param → aggregator called with unread_only=False."""
        response, patched = self._hit(
            client,
            query="",
            returned_counts={"Action": 7, "Noise": 3},
            returned_total=10,
        )
        assert response.status_code == 200
        assert response.get_json() == {
            "counts": {"Action": 7, "Noise": 3},
            "total": 10,
        }
        patched.assert_called_once_with(42, unread_only=False)

    def test_unread_only_true_passes_flag_through(self, client):
        """``?unread_only=true`` forwards ``unread_only=True`` to the aggregator."""
        response, patched = self._hit(
            client,
            query="?unread_only=true",
            returned_counts={"Action": 2},
            returned_total=2,
        )
        assert response.status_code == 200
        assert response.get_json()["total"] == 2
        patched.assert_called_once_with(42, unread_only=True)

    def test_unread_only_falsy_keeps_total_scope(self, client):
        """Truthy parsing is strict — ``?unread_only=0`` stays on totals so
        accidental query strings can't silently flip the contract."""
        _, patched = self._hit(
            client,
            query="?unread_only=0",
            returned_counts={},
            returned_total=0,
        )
        patched.assert_called_once_with(42, unread_only=False)


class TestCollectInboxLabelEmailIdsUnreadFilter:
    """Verify the helper threads ``unread_only`` into the inbox SQL itself."""

    def test_unread_only_appends_is_read_false_param_to_inbox_sql(self):
        """``_collect_inbox_label_email_ids(account_id, unread_only=True)``
        must restrict both the inbox listing and the email_labels JOIN to
        unread rows with a bound boolean, so Postgres does not compare
        ``boolean = integer``.
        """
        executed_sql: list[str] = []
        executed_params: list[dict] = []

        class _RowResult:
            def fetchall(self):
                return []

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def execute(self, stmt, _params):
                executed_sql.append(str(stmt))
                executed_params.append(dict(_params))
                return _RowResult()

        from app.api import labels as labels_module

        # The inbox label scan is now cached per (account, unread_only); drop
        # any entry so this test observes a real (uncached) SQL execution
        # regardless of test ordering.
        labels_module._invalidate_labels_cache()

        fake_container = MagicMock()
        fake_container.get_label_store.return_value = MagicMock(
            get_assignments_batch=MagicMock(return_value={}),
        )

        with patch("app.db.database.get_db_session", return_value=_Session()), \
             patch.object(labels_module, "get_container", return_value=fake_container):
            counts, total = labels_module._collect_inbox_label_email_ids(
                account_id=42, unread_only=True,
            )

        assert counts == {}
        assert total == 0
        joined = " ".join(executed_sql).lower()
        assert "is_read = :is_read" in joined, (
            f"Unread-only SQL must filter on bound is_read. SQL: {joined!r}"
        )
        assert executed_params == [
            {"aid": 42, "is_sent": False, "is_read": False},
            {"aid": 42, "is_sent": False, "is_read": False},
        ]

    def test_default_call_omits_is_read_from_inbox_sql(self):
        """Without the flag the SQL keeps the legacy total-inbox scope."""
        executed_sql: list[str] = []

        class _RowResult:
            def fetchall(self):
                return []

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def execute(self, stmt, _params):
                executed_sql.append(str(stmt))
                return _RowResult()

        from app.api import labels as labels_module

        # The inbox label scan is now cached per (account, unread_only); drop
        # any entry so this test observes a real (uncached) SQL execution
        # regardless of test ordering.
        labels_module._invalidate_labels_cache()

        fake_container = MagicMock()
        fake_container.get_label_store.return_value = MagicMock(
            get_assignments_batch=MagicMock(return_value={}),
        )

        with patch("app.db.database.get_db_session", return_value=_Session()), \
             patch.object(labels_module, "get_container", return_value=fake_container):
            labels_module._collect_inbox_label_email_ids(account_id=42)

        joined = " ".join(executed_sql).lower()
        assert "is_read" not in joined, (
            f"Default call must not filter on is_read. SQL: {joined!r}"
        )


class TestCachedEmailLabelingAccountScope:
    """Regression tests for account scoping in cached-email label fallback."""

    def test_llm_fallback_preserves_cache_account_id(self):
        """Cached emails must not fall back to the ambient active account."""
        from types import SimpleNamespace

        from app.api import routes_emails as routes_emails_module

        store = MagicMock()
        store.get_assignments_batch.return_value = {}
        fake_container = MagicMock()
        fake_container.get_label_store.return_value = store

        cached_email = SimpleNamespace(
            email_id="msg-1",
            sender="sender@example.com",
            sender_name="Sender",
            subject="Subject",
            body_text="Body",
            body_html="<p>Body</p>",
            attachments_meta=None,
            thread_id="thread-1",
            date=None,
            recipients="owner@example.com",
            cc="",
        )

        with patch.object(routes_emails_module._rh, "_get_container", return_value=fake_container), \
             patch.object(routes_emails_module, "_sync_label_emails") as sync_label, \
             patch.object(routes_emails_module, "_start_auto_labeling") as start_auto_labeling:
            routes_emails_module._label_cached_emails_if_needed([cached_email], account_id=4)

        fake_container.get_label_store.assert_any_call(account_id=4)
        sync_label.assert_called_once()
        assert sync_label.call_args.kwargs["account_id"] == 4
        start_auto_labeling.assert_called_once()
        assert start_auto_labeling.call_args.kwargs["account_id"] == 4
        assert start_auto_labeling.call_args.args[0][0].id == "msg-1"
