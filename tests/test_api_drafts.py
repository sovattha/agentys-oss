# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour GET /api/drafts - Lister les brouillons générés.

pytest tests/test_api_drafts.py -v
"""

from dataclasses import dataclass
from typing import Optional
from unittest.mock import Mock, patch

import pytest


@pytest.fixture(autouse=True)
def _resolve_account_id(monkeypatch):
    """Force _resolve_account_id_for_user à retourner 1 dans ces tests
    (auth JWT non simulée). Sans ça, les routes drafts renvoient [] à
    cause de l'isolation multi-compte."""
    monkeypatch.setattr(
        "app.api.routes_helpers._resolve_account_id_for_user",
        lambda: 1,
    )
    yield


@dataclass
class MockDraftRecord:
    """DraftRecord mock pour les tests."""

    id: str
    timestamp: str
    email_sender: str
    email_subject: str
    status: str
    category: Optional[str] = None
    priority_score: Optional[int] = None
    tokens_used: int = 0
    processing_time_ms: int = 0
    feedback: Optional[str] = None
    feedback_comment: Optional[str] = None
    # Champs requis par _draft_to_summary_dict
    email_body: Optional[str] = None
    draft_v1: Optional[str] = None
    draft_final: Optional[str] = None
    critique: Optional[str] = None
    draft_id: Optional[str] = None


@pytest.fixture
def app():
    """Application Flask de test."""
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Client de test Flask."""
    return app.test_client()


@pytest.fixture
def sample_drafts():
    """Liste de brouillons mock pour les tests."""
    return [
        MockDraftRecord(
            id="draft-001",
            timestamp="2024-01-15T10:30:00Z",
            email_sender="alice@example.com",
            email_subject="Question urgente",
            status="V1",
            category="URGENT",
            priority_score=85,
            tokens_used=150,
            processing_time_ms=1200,
            feedback="positive",
            feedback_comment="Très bonne réponse",
        ),
        MockDraftRecord(
            id="draft-002",
            timestamp="2024-01-15T11:00:00Z",
            email_sender="bob@example.com",
            email_subject="Suivi projet",
            status="V2",
            category="NORMAL",
            priority_score=50,
            tokens_used=200,
            processing_time_ms=1500,
            feedback=None,
            feedback_comment=None,
        ),
        MockDraftRecord(
            id="draft-003",
            timestamp="2024-01-15T12:00:00Z",
            email_sender="carol@example.com",
            email_subject="Information",
            status="V1",
            category="LOW",
            priority_score=20,
            tokens_used=100,
            processing_time_ms=800,
            feedback=None,
            feedback_comment=None,
        ),
    ]


class TestListDraftsEndpoint:
    """Tests pour GET /api/drafts."""

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_success(self, mock_get_container, client, sample_drafts):
        """Liste les brouillons avec succès."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 3
        assert data["limit"] == 50
        assert data["offset"] == 0
        assert len(data["drafts"]) == 3
        assert data["drafts"][0]["id"] == "draft-001"
        assert data["drafts"][0]["email_sender"] == "alice@example.com"
        assert data["drafts"][1]["id"] == "draft-002"
        assert data["drafts"][2]["id"] == "draft-003"

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_default_limit(self, mock_get_container, client, sample_drafts):
        """Vérifie que la limite par défaut est 50."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts")
        data = response.get_json()

        assert response.status_code == 200
        assert data["limit"] == 50

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_custom_limit(self, mock_get_container, client, sample_drafts):
        """Limite personnalisée est respectée."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?limit=2")
        data = response.get_json()

        assert response.status_code == 200
        assert data["limit"] == 2
        assert data["total"] == 3  # Total reste 3
        assert len(data["drafts"]) == 2  # Mais seulement 2 retournés

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_offset(self, mock_get_container, client, sample_drafts):
        """Offset pour pagination fonctionne."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?offset=1")
        data = response.get_json()

        assert response.status_code == 200
        assert data["offset"] == 1
        assert data["total"] == 3
        assert len(data["drafts"]) == 2  # 3 - offset 1 = 2
        assert data["drafts"][0]["id"] == "draft-002"

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_limit_and_offset(self, mock_get_container, client, sample_drafts):
        """Combinaison limit + offset fonctionne."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?limit=1&offset=1")
        data = response.get_json()

        assert response.status_code == 200
        assert data["limit"] == 1
        assert data["offset"] == 1
        assert data["total"] == 3
        assert len(data["drafts"]) == 1
        assert data["drafts"][0]["id"] == "draft-002"

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_filter_by_category(self, mock_get_container, client, sample_drafts):
        """Filtre par catégorie fonctionne."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?category=URGENT")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 1
        assert len(data["drafts"]) == 1
        assert data["drafts"][0]["id"] == "draft-001"
        assert data["drafts"][0]["category"] == "URGENT"

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_category_not_found(self, mock_get_container, client, sample_drafts):
        """Catégorie inexistante retourne liste vide."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?category=NONEXISTENT")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 0
        assert data["drafts"] == []

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_empty(self, mock_get_container, client):
        """Retourne une liste vide si aucun brouillon."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = []
        mock_draft_history.get_all.return_value = []
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 0
        assert data["drafts"] == []

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_offset_beyond_total(self, mock_get_container, client, sample_drafts):
        """Offset au-delà du total retourne liste vide."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?offset=100")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 3
        assert data["offset"] == 100
        assert data["drafts"] == []

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_category_with_pagination(
        self, mock_get_container, client, sample_drafts
    ):
        """Filtre catégorie + pagination combinés."""
        # Ajouter un deuxième brouillon URGENT pour tester la pagination
        sample_drafts.append(
            MockDraftRecord(
                id="draft-004",
                timestamp="2024-01-15T13:00:00Z",
                email_sender="dave@example.com",
                email_subject="Autre urgence",
                status="V1",
                category="URGENT",
                priority_score=90,
            )
        )
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?category=URGENT&limit=1&offset=1")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 2  # 2 URGENT
        assert len(data["drafts"]) == 1
        assert data["drafts"][0]["id"] == "draft-004"

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_all_fields_returned(self, mock_get_container, client, sample_drafts):
        """Vérifie que tous les champs sont retournés."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = [sample_drafts[0]]
        mock_draft_history.get_all.return_value = [sample_drafts[0]]
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts")
        data = response.get_json()

        assert response.status_code == 200
        draft = data["drafts"][0]
        assert draft["id"] == "draft-001"
        assert draft["timestamp"] == "2024-01-15T10:30:00Z"
        assert draft["email_sender"] == "alice@example.com"
        assert draft["email_subject"] == "Question urgente"
        assert draft["status"] == "V1"
        assert draft["category"] == "URGENT"
        assert draft["priority_score"] == 85
        assert draft["tokens_used"] == 150
        assert draft["processing_time_ms"] == 1200
        assert draft["feedback"] == "positive"
        assert draft["feedback_comment"] == "Très bonne réponse"

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_optional_fields_none(self, mock_get_container, client):
        """Brouillon avec champs optionnels à None."""
        draft_minimal = MockDraftRecord(
            id="draft-minimal",
            timestamp="2024-01-15T10:00:00Z",
            email_sender="test@example.com",
            email_subject="Test",
            status="V1",
            category=None,
            priority_score=None,
            tokens_used=0,
            processing_time_ms=0,
            feedback=None,
            feedback_comment=None,
        )
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = [draft_minimal]
        mock_draft_history.get_all.return_value = [draft_minimal]
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 1
        draft = data["drafts"][0]
        assert draft["category"] is None
        assert draft["priority_score"] is None
        assert draft["feedback"] is None
        assert draft["feedback_comment"] is None

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_multiple_categories(self, mock_get_container, client, sample_drafts):
        """Filtre ne retourne que la catégorie demandée."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        # Vérifier NORMAL
        response = client.get("/api/drafts?category=NORMAL")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 1
        assert data["drafts"][0]["category"] == "NORMAL"

        # Vérifier LOW
        response = client.get("/api/drafts?category=LOW")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 1
        assert data["drafts"][0]["category"] == "LOW"

    # ========================================================================
    # EDGE CASES - Limites extrêmes
    # ========================================================================

    def test_list_drafts_limit_zero(self, client):
        """Limit = 0 retourne erreur 400."""
        response = client.get("/api/drafts?limit=0")
        data = response.get_json()

        # Security: limit=0 is rejected
        assert response.status_code == 400
        assert "error" in data
        assert "Limit must be between" in data["error"]

    def test_list_drafts_limit_larger_than_total(self, client):
        """Limit > max (500) retourne erreur 400."""
        response = client.get("/api/drafts?limit=1000")
        data = response.get_json()

        # Security: limit > 500 is rejected
        assert response.status_code == 400
        assert "error" in data
        assert "Limit must be between" in data["error"]

    def test_list_drafts_limit_negative(self, client):
        """Limit négatif retourne erreur 400."""
        response = client.get("/api/drafts?limit=-1")
        data = response.get_json()

        # Security: negative limit is rejected
        assert response.status_code == 400
        assert "error" in data
        assert "Limit must be between" in data["error"]

    def test_list_drafts_offset_negative(self, client):
        """Offset négatif retourne erreur 400."""
        response = client.get("/api/drafts?offset=-1")
        data = response.get_json()

        # Security: negative offset is rejected
        assert response.status_code == 400
        assert "error" in data
        assert "Offset must be between" in data["error"]

    # ========================================================================
    # EDGE CASES - Paramètres invalides
    # ========================================================================

    def test_list_drafts_limit_non_integer(self, client):
        """Limit non-entier retourne erreur 400."""
        response = client.get("/api/drafts?limit=abc")
        data = response.get_json()

        # Security: non-integer limit is rejected
        assert response.status_code == 400
        assert "error" in data
        assert "valid integer" in data["error"]

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_offset_non_integer(self, mock_get_container, client, sample_drafts):
        """Offset non-entier utilise la valeur par défaut."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?offset=xyz")
        data = response.get_json()

        assert response.status_code == 200
        assert data["offset"] == 0  # Valeur par défaut

    # ========================================================================
    # EDGE CASES - Category
    # ========================================================================

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_category_empty_string(self, mock_get_container, client, sample_drafts):
        """Catégorie vide retourne tous les drafts (paramètre ignoré)."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?category=")
        data = response.get_json()

        assert response.status_code == 200
        # Chaîne vide est falsy en Python, donc le filtre n'est pas appliqué
        assert data["total"] == 3

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_category_case_sensitive(self, mock_get_container, client, sample_drafts):
        """Catégorie est case-sensitive."""
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = sample_drafts
        mock_draft_history.get_all.return_value = sample_drafts
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        # 'urgent' en minuscules ne match pas 'URGENT'
        response = client.get("/api/drafts?category=urgent")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 0
        assert data["drafts"] == []

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_category_with_special_chars(self, mock_get_container, client):
        """Catégorie avec caractères spéciaux."""
        draft_special = MockDraftRecord(
            id="draft-special",
            timestamp="2024-01-15T10:00:00Z",
            email_sender="test@example.com",
            email_subject="Test",
            status="V1",
            category="TEST-CATEGORY_123",
        )
        mock_draft_history = Mock()
        mock_draft_history.get_all_for_account.return_value = [draft_special]
        mock_draft_history.get_all.return_value = [draft_special]
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts?category=TEST-CATEGORY_123")
        data = response.get_json()

        assert response.status_code == 200
        assert data["total"] == 1
        assert data["drafts"][0]["category"] == "TEST-CATEGORY_123"

    def test_list_drafts_category_too_long(self, client):
        """Catégorie trop longue (> 100 chars) retourne erreur 400."""
        long_category = "A" * 101
        response = client.get(f"/api/drafts?category={long_category}")
        data = response.get_json()

        assert response.status_code == 400
        assert "error" in data
        assert "exceeds maximum length of 100" in data["error"]

    # ========================================================================
    # EDGE CASES - Erreurs
    # ========================================================================

    @patch("app.api.routes_helpers._get_container")
    def test_list_drafts_repository_exception(self, mock_get_container, client):
        """Exception du repository retourne une erreur 500 avec message générique."""
        mock_draft_history = Mock()
        mock_draft_history.get_all.side_effect = Exception("Database connection failed")
        mock_container = Mock()
        mock_container.get_draft_history.return_value = mock_draft_history
        mock_get_container.return_value = mock_container

        response = client.get("/api/drafts")

        assert response.status_code == 500
        data = response.get_json()
        assert "error" in data
        assert data["error"] == "An internal error occurred while listing drafts"
        # Sécurité: le message d'erreur interne ne doit pas être exposé
        assert "Database connection failed" not in data["error"]
