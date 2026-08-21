# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for Relationship API endpoints.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.api.app import create_app
from app.domain.entities.relationship_type import (
    RelationshipType,
    CommunicationFrequency,
    RelationshipDetection,
)


@pytest.fixture
def client():
    """Create test client."""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def _bypass_cross_account_guard():
    """The audit `451f02f6` introduced ``_block_cross_account_access`` on the
    contacts blueprint. Without a JWT, it falls through to the global
    AccountManager singleton which on a developer workstation reflects the
    dev's actual account id (e.g. 6). The hardcoded ``?account_id=1`` in
    these tests then trips the guard and returns 403.

    These tests focus on the endpoint's business logic (mocking the
    relationship service), so we neutralise the guard at the fixture level
    instead of threading JWT auth through every assertion. Cross-account
    rejection itself is covered separately in
    ``tests/api/test_email_isolation_scoping.py`` and
    ``tests/audit_fixes/`` — no coverage is lost here.
    """
    with patch(
        "app.api.routes_contacts._block_cross_account_access",
        return_value=None,
    ):
        yield


class TestGetRelationshipEndpoint:
    """Tests for GET /contacts/<email>/relationship endpoint."""

    def test_get_relationship_success(self, client):
        """Test successful relationship retrieval."""
        with patch(
            "app.api.routes_contacts._make_relationship_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.get_relationship.return_value = RelationshipDetection(
                contact_email="john@example.com",
                account_id=1,
                relationship_type=RelationshipType.COLLEAGUE,
                confidence=0.85,
                communication_frequency=CommunicationFrequency.DAILY,
                typical_hours=[9, 10, 11, 14, 15],
                is_user_override=False,
            )
            mock_get_service.return_value = mock_service

            response = client.get(
                "/api/contacts/john@example.com/relationship?account_id=1"
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["data"]["relationship_type"] == "colleague"
            assert data["data"]["confidence"] == 0.85
            assert data["data"]["communication_frequency"] == "daily"
            assert data["data"]["is_user_override"] is False

    def test_get_relationship_missing_account_id(self, client):
        """Test error when account_id is missing."""
        response = client.get("/api/contacts/john@example.com/relationship")
        assert response.status_code == 400
        assert "account_id" in response.get_json()["error"].lower()

    def test_get_relationship_invalid_email(self, client):
        """Test error with invalid email format."""
        response = client.get(
            "/api/contacts/not-an-email/relationship?account_id=1"
        )
        assert response.status_code == 400

    def test_get_relationship_with_override(self, client):
        """Test relationship that was manually overridden."""
        with patch(
            "app.api.routes_contacts._make_relationship_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.get_relationship.return_value = RelationshipDetection(
                contact_email="john@example.com",
                account_id=1,
                relationship_type=RelationshipType.CLIENT,
                confidence=1.0,
                communication_frequency=CommunicationFrequency.SPORADIC,
                is_user_override=True,
            )
            mock_get_service.return_value = mock_service

            response = client.get(
                "/api/contacts/john@example.com/relationship?account_id=1"
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["data"]["relationship_type"] == "client"
            assert data["data"]["is_user_override"] is True


class TestSetRelationshipOverrideEndpoint:
    """Tests for PUT /contacts/<email>/relationship endpoint."""

    def test_set_override_success(self, client):
        """Test successful relationship override."""
        with patch(
            "app.api.routes_contacts._make_relationship_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.set_relationship_override.return_value = RelationshipDetection(
                contact_email="john@example.com",
                account_id=1,
                relationship_type=RelationshipType.CLIENT,
                confidence=1.0,
                communication_frequency=CommunicationFrequency.SPORADIC,
                is_user_override=True,
            )
            mock_get_service.return_value = mock_service

            response = client.put(
                "/api/contacts/john@example.com/relationship?account_id=1",
                json={"relationship_type": "client"},
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["data"]["relationship_type"] == "client"
            assert data["data"]["is_user_override"] is True

    def test_set_override_missing_relationship_type(self, client):
        """Test error when relationship_type is missing."""
        response = client.put(
            "/api/contacts/john@example.com/relationship?account_id=1",
            json={},
        )
        assert response.status_code == 400

    def test_set_override_invalid_relationship_type(self, client):
        """Test error with invalid relationship_type."""
        response = client.put(
            "/api/contacts/john@example.com/relationship?account_id=1",
            json={"relationship_type": "invalid_type"},
        )
        assert response.status_code == 400

    def test_set_override_missing_account_id(self, client):
        """Test error when account_id is missing."""
        response = client.put(
            "/api/contacts/john@example.com/relationship",
            json={"relationship_type": "client"},
        )
        assert response.status_code == 400


class TestDeleteRelationshipOverrideEndpoint:
    """Tests for DELETE /contacts/<email>/relationship endpoint."""

    def test_delete_override_success(self, client):
        """Test successful override deletion."""
        with patch(
            "app.api.routes_contacts._make_relationship_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.delete_relationship_override.return_value = True
            mock_get_service.return_value = mock_service

            response = client.delete(
                "/api/contacts/john@example.com/relationship?account_id=1"
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True

    def test_delete_override_not_found(self, client):
        """Test deletion when override doesn't exist."""
        with patch(
            "app.api.routes_contacts._make_relationship_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.delete_relationship_override.return_value = False
            mock_get_service.return_value = mock_service

            response = client.delete(
                "/api/contacts/john@example.com/relationship?account_id=1"
            )

            assert response.status_code == 404


class TestGetAllOverridesEndpoint:
    """Tests for GET /contacts/relationships/overrides endpoint."""

    def test_get_all_overrides_success(self, client):
        """Test retrieving all overrides for an account."""
        with patch(
            "app.api.routes_contacts._make_relationship_service"
        ) as mock_get_service:
            mock_service = MagicMock()

            override1 = MagicMock()
            override1.contact_email = "john@example.com"
            override1.relationship_type = "client"
            override1.created_at = MagicMock()
            override1.created_at.isoformat.return_value = "2024-01-15T10:00:00"
            override1.updated_at = MagicMock()
            override1.updated_at.isoformat.return_value = "2024-01-15T10:00:00"

            override2 = MagicMock()
            override2.contact_email = "jane@example.com"
            override2.relationship_type = "colleague"
            override2.created_at = MagicMock()
            override2.created_at.isoformat.return_value = "2024-01-14T10:00:00"
            override2.updated_at = MagicMock()
            override2.updated_at.isoformat.return_value = "2024-01-14T10:00:00"

            mock_service.get_all_overrides.return_value = [override1, override2]
            mock_get_service.return_value = mock_service

            response = client.get(
                "/api/contacts/relationships/overrides?account_id=1"
            )

            assert response.status_code == 200
            data = response.get_json()
            assert len(data["data"]) == 2
            assert data["data"][0]["contact_email"] == "john@example.com"
            assert data["data"][1]["contact_email"] == "jane@example.com"

    def test_get_all_overrides_empty(self, client):
        """Test empty list when no overrides."""
        with patch(
            "app.api.routes_contacts._make_relationship_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.get_all_overrides.return_value = []
            mock_get_service.return_value = mock_service

            response = client.get(
                "/api/contacts/relationships/overrides?account_id=1"
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["data"] == []
