# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for Context Transparency API endpoints.

TDD: RED phase - tests written before implementation.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.api.app import create_app
from app.domain.entities.context_transparency import (
    AnalyzedEmailSummary,
    StyleProfileSummary,
    RelationshipSummary,
    ContextTransparencyData,
)


@pytest.fixture
def client():
    """Create test client."""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client


class TestGetContextTransparencyEndpoint:
    """Tests for GET /context/transparency/<session_id> endpoint."""

    def test_get_transparency_data_success(self, client):
        """Test successful transparency data retrieval."""
        with patch(
            "app.api.routes_misc._resolve_account_id_for_user",
            return_value=1,
        ), patch(
            "app.api.routes_misc.get_context_transparency_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.get_transparency_data.return_value = ContextTransparencyData(
                session_id="session-123",
                contact_email="john@example.com",
                analyzed_emails=[
                    AnalyzedEmailSummary(
                        email_id="email-1",
                        subject="Meeting tomorrow",
                        sender="john@example.com",
                        date=datetime.now(timezone.utc),
                        relevant_excerpts=["Let's discuss the project"],
                        relevance_score=0.9,
                    )
                ],
                style_profile=StyleProfileSummary(
                    formality_level="formal",
                    characteristic_phrases=["merci", "cordialement"],
                    greeting_style="Bonjour",
                    closing_style="Cordialement",
                    confidence=0.8,
                ),
                relationship=RelationshipSummary(
                    relationship_type="colleague",
                    confidence=0.85,
                    communication_frequency="weekly",
                ),
                analysis_timestamp=datetime.now(timezone.utc),
                total_context_tokens=150,
            )
            mock_get_service.return_value = mock_service

            response = client.get(
                "/api/context/transparency/session-123?account_id=1&contact_email=john@example.com"
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["data"]["session_id"] == "session-123"
            assert data["data"]["contact_email"] == "john@example.com"
            assert len(data["data"]["analyzed_emails"]) == 1
            assert data["data"]["style_profile"]["formality_level"] == "formal"
            assert data["data"]["relationship"]["relationship_type"] == "colleague"
            assert data["data"]["total_context_tokens"] == 150

    def test_get_transparency_missing_account_id(self, client):
        """Test error when no active account is resolved (sentinel -1)."""
        with patch(
            "app.api.routes_misc._resolve_account_id_for_user", return_value=-1
        ):
            response = client.get(
                "/api/context/transparency/session-123?contact_email=john@example.com"
            )
        assert response.status_code == 400
        assert "account" in response.get_json()["error"].lower()

    def test_get_transparency_missing_contact_email(self, client):
        """Test error when contact_email is missing."""
        with patch(
            "app.api.routes_misc._resolve_account_id_for_user", return_value=1
        ):
            response = client.get(
                "/api/context/transparency/session-123?account_id=1"
            )
        assert response.status_code == 400
        assert "contact_email" in response.get_json()["error"].lower()

    def test_get_transparency_invalid_account_id(self, client):
        """Test error when resolved account_id is sentinel (no account)."""
        with patch(
            "app.api.routes_misc._resolve_account_id_for_user", return_value=-1
        ):
            response = client.get(
                "/api/context/transparency/session-123?account_id=abc&contact_email=john@example.com"
            )
        assert response.status_code == 400
        assert "account" in response.get_json()["error"].lower()

    def test_get_transparency_invalid_contact_email(self, client):
        """Test error with invalid contact email."""
        with patch(
            "app.api.routes_misc._resolve_account_id_for_user", return_value=1
        ):
            response = client.get(
                "/api/context/transparency/session-123?account_id=1&contact_email=not-an-email"
            )
        assert response.status_code == 400
        assert "email" in response.get_json()["error"].lower()

    def test_get_transparency_without_style_profile(self, client):
        """Test transparency data when no style profile exists."""
        with patch(
            "app.api.routes_misc._resolve_account_id_for_user",
            return_value=1,
        ), patch(
            "app.api.routes_misc.get_context_transparency_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.get_transparency_data.return_value = ContextTransparencyData(
                session_id="session-123",
                contact_email="john@example.com",
                analyzed_emails=[],
                style_profile=None,
                relationship=None,
                analysis_timestamp=datetime.now(timezone.utc),
                total_context_tokens=10,
            )
            mock_get_service.return_value = mock_service

            response = client.get(
                "/api/context/transparency/session-123?account_id=1&contact_email=john@example.com"
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["data"]["style_profile"] is None
            assert data["data"]["relationship"] is None

    def test_get_transparency_service_error(self, client):
        """Test handling of service errors."""
        with patch(
            "app.api.routes_misc._resolve_account_id_for_user",
            return_value=1,
        ), patch(
            "app.api.routes_misc.get_context_transparency_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.get_transparency_data.side_effect = Exception("Service error")
            mock_get_service.return_value = mock_service

            response = client.get(
                "/api/context/transparency/session-123?account_id=1&contact_email=john@example.com"
            )

            assert response.status_code == 500
            assert "error" in response.get_json()

    def test_get_transparency_empty_session_id(self, client):
        """Test handling of empty session ID."""
        response = client.get(
            "/api/context/transparency/?account_id=1&contact_email=john@example.com"
        )
        assert response.status_code == 404


class TestContextTransparencyEndpointValidation:
    """Tests for input validation."""

    def test_session_id_too_long(self, client):
        """Test that overly long session_id is rejected."""
        long_session_id = "x" * 256
        response = client.get(
            f"/api/context/transparency/{long_session_id}?account_id=1&contact_email=john@example.com"
        )
        assert response.status_code == 400

    def test_contact_email_too_long(self, client):
        """Test that overly long contact_email is rejected."""
        long_email = "a" * 200 + "@example.com"
        with patch(
            "app.api.routes_misc._resolve_account_id_for_user", return_value=1
        ):
            response = client.get(
                f"/api/context/transparency/session-123?account_id=1&contact_email={long_email}"
            )
        assert response.status_code == 400
