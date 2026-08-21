# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Unit tests for Search API endpoints.

Tests email search endpoints.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask

from app.api.search import (
    _search_via_provider,
    _standard_emails_to_results,
    search_alias_bp,
    search_bp,
)
from app.services.search_service import SearchResult, SearchResponse


@pytest.fixture
def app():
    """Create test Flask application."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(search_bp)
    app.register_blueprint(search_alias_bp)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture(autouse=True)
def no_current_account(monkeypatch):
    """Keep unit tests independent from the developer's local account config."""
    monkeypatch.setattr(
        "app.api.routes_helpers._resolve_account_id_for_user",
        lambda: -1,
    )


class TestSearchEndpoint:
    """Tests for GET /api/emails/search endpoint."""

    def test_provider_metadata_snippet_is_used_when_body_empty(self):
        """Header-only Gmail fallback still returns a useful snippet."""
        email = SimpleNamespace(
            id="gmail-1",
            subject="Test Agentys",
            sender="sender@example.com",
            received_at=None,
            body="",
            html_body="",
            raw_metadata={"snippet": "Bonjour, le créneau de 14h convient."},
            is_read=True,
            is_starred=False,
        )

        results = _standard_emails_to_results([email], "14h")

        assert len(results) == 1
        assert results[0].email_id == "gmail-1"
        assert "14h" in results[0].snippet

    @patch("app.providers.factory.get_pooled_provider")
    def test_provider_fallback_uses_gmail_metadata_search(self, mock_get_provider):
        """Search fallback must not fetch full Gmail bodies for list results."""
        provider = MagicMock()
        provider._provider_type = "gmail"
        provider.search_emails.return_value = [
            SimpleNamespace(
                id="gmail-1",
                subject="Test Agentys",
                sender="sender@example.com",
                received_at=None,
                body="",
                html_body="",
                raw_metadata={"snippet": "Message trouvé via Gmail."},
                is_read=True,
                is_starred=False,
            )
        ]
        mock_get_provider.return_value = provider

        results = _search_via_provider("Test Agentys", "hash-account", limit=20)

        provider.search_emails.assert_called_once_with(
            "Test Agentys",
            limit=20,
            include_body=False,
        )
        assert len(results) == 1
        assert results[0].email_id == "gmail-1"

    @patch("app.api.search.get_search_service")
    def test_search_with_query(self, mock_get_service, client):
        """Test basic search with query."""
        mock_service = MagicMock()
        mock_service.search_emails.return_value = SearchResponse(
            query="meeting",
            total=2,
            results=[
                SearchResult(
                    id=1, email_id="a", subject="Meeting notes",
                    sender="test@example.com", date="2026-01-18",
                    snippet="...<mark>meeting</mark>...", relevance_score=0.9,
                ),
                SearchResult(
                    id=2, email_id="b", subject="Meeting agenda",
                    sender="boss@example.com", date="2026-01-17",
                    snippet="...<mark>meeting</mark>...", relevance_score=0.8,
                ),
            ],
            duration_ms=15.5,
            has_more=False,
        )
        mock_get_service.return_value = mock_service

        response = client.get("/api/emails/search?q=meeting")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["query"] == "meeting"
        assert data["total"] == 2
        assert len(data["results"]) == 2
        assert data["duration_ms"] == 15.5

    @patch("app.api.search._search_via_provider_with_timeout")
    @patch("app.api.search.get_search_service")
    def test_search_does_not_block_on_provider_when_sqlite_has_results(
        self,
        mock_get_service,
        mock_provider_fallback,
        client,
    ):
        """Local hits should return immediately instead of waiting on Gmail."""
        mock_service = MagicMock()
        mock_service.search_emails.return_value = SearchResponse(
            query="meeting",
            total=1,
            results=[
                SearchResult(
                    id=1,
                    email_id="a",
                    subject="Meeting notes",
                    sender="test@example.com",
                    date="2026-01-18",
                    snippet="meeting",
                    relevance_score=0.9,
                )
            ],
            duration_ms=5.0,
            has_more=False,
        )
        mock_get_service.return_value = mock_service

        response = client.get("/api/emails/search?q=meeting")

        assert response.status_code == 200
        assert response.get_json()["total"] == 1
        mock_provider_fallback.assert_not_called()

    @patch("app.api.search.get_search_service")
    def test_legacy_search_alias_delegates_to_canonical_handler(self, mock_get_service, client):
        """GET /api/search stays as a compatibility alias for monitors."""
        mock_service = MagicMock()
        mock_service.search_emails.return_value = SearchResponse(
            query="meeting",
            total=0,
            results=[],
            duration_ms=3.0,
            has_more=False,
        )
        mock_get_service.return_value = mock_service

        response = client.get("/api/search?q=meeting")

        assert response.status_code == 200
        assert response.get_json()["success"] is True
        mock_service.search_emails.assert_called_once_with(
            query="meeting",
            account_id=None,
            limit=50,
            offset=0,
        )

    @patch("app.api.search.get_search_service")
    def test_search_empty_query(self, mock_get_service, client):
        """Test search with empty query returns recent emails."""
        mock_service = MagicMock()
        mock_service.search_emails.return_value = SearchResponse(
            query="",
            total=0,
            results=[],
            duration_ms=5.0,
            has_more=False,
        )
        mock_get_service.return_value = mock_service

        response = client.get("/api/emails/search?q=")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["query"] == ""

    @patch("app.api.search.get_search_service")
    def test_search_with_account_id(self, mock_get_service, client):
        """Test search filtered by account_id."""
        mock_service = MagicMock()
        mock_service.search_emails.return_value = SearchResponse(
            query="test",
            total=0,
            results=[],
            duration_ms=5.0,
            has_more=False,
        )
        mock_get_service.return_value = mock_service

        response = client.get("/api/emails/search?q=test&account_id=1")

        assert response.status_code == 200
        mock_service.search_emails.assert_called_with(
            query="test",
            account_id=1,
            limit=50,
            offset=0,
        )

    def test_search_invalid_account_id(self, client):
        """Test search with invalid account_id."""
        response = client.get("/api/emails/search?q=test&account_id=invalid")

        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert "account_id" in data["error"]

    def test_search_negative_account_id(self, client):
        """Test search with negative account_id."""
        response = client.get("/api/emails/search?q=test&account_id=-1")

        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False

    @patch("app.api.search.get_search_service")
    def test_search_with_limit(self, mock_get_service, client):
        """Test search with custom limit."""
        mock_service = MagicMock()
        mock_service.search_emails.return_value = SearchResponse(
            query="test",
            total=0,
            results=[],
            duration_ms=5.0,
            has_more=False,
        )
        mock_get_service.return_value = mock_service

        response = client.get("/api/emails/search?q=test&limit=25")

        assert response.status_code == 200
        mock_service.search_emails.assert_called_with(
            query="test",
            account_id=None,
            limit=25,
            offset=0,
        )

    @patch("app.api.search.get_search_service")
    def test_search_limit_capped_at_100(self, mock_get_service, client):
        """Test that limit is capped at 100."""
        mock_service = MagicMock()
        mock_service.search_emails.return_value = SearchResponse(
            query="test",
            total=0,
            results=[],
            duration_ms=5.0,
            has_more=False,
        )
        mock_get_service.return_value = mock_service

        response = client.get("/api/emails/search?q=test&limit=500")

        assert response.status_code == 200
        mock_service.search_emails.assert_called_with(
            query="test",
            account_id=None,
            limit=100,  # Capped at MAX_LIMIT
            offset=0,
        )

    @patch("app.api.search.get_search_service")
    def test_search_with_offset(self, mock_get_service, client):
        """Test search with pagination offset."""
        mock_service = MagicMock()
        mock_service.search_emails.return_value = SearchResponse(
            query="test",
            total=0,
            results=[],
            duration_ms=5.0,
            has_more=False,
        )
        mock_get_service.return_value = mock_service

        response = client.get("/api/emails/search?q=test&offset=50")

        assert response.status_code == 200
        mock_service.search_emails.assert_called_with(
            query="test",
            account_id=None,
            limit=50,
            offset=50,
        )

    def test_search_query_too_long(self, client):
        """Test search with query exceeding max length."""
        long_query = "a" * 501

        response = client.get(f"/api/emails/search?q={long_query}")

        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert "Query too long" in data["error"]

    @patch("app.api.search.get_search_service")
    def test_search_has_more_flag(self, mock_get_service, client):
        """Test search with has_more flag."""
        mock_service = MagicMock()
        mock_service.search_emails.return_value = SearchResponse(
            query="test",
            total=100,
            results=[],
            duration_ms=5.0,
            has_more=True,
        )
        mock_get_service.return_value = mock_service

        response = client.get("/api/emails/search?q=test")

        assert response.status_code == 200
        data = response.get_json()
        assert data["has_more"] is True


class TestSearchSuggestionsEndpoint:
    """Tests for GET /api/emails/search/suggestions endpoint."""

    def test_suggestions_short_query(self, client):
        """Test suggestions with query shorter than 2 chars."""
        response = client.get("/api/emails/search/suggestions?q=a")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["suggestions"] == []

    def test_suggestions_empty_query(self, client):
        """Test suggestions with empty query."""
        response = client.get("/api/emails/search/suggestions?q=")

        assert response.status_code == 200
        data = response.get_json()
        assert data["suggestions"] == []

    def test_suggestions_valid_query(self, client):
        """Test suggestions with valid query."""
        response = client.get("/api/emails/search/suggestions?q=me")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        # Currently returns empty - TODO: implement suggestions


class TestRebuildIndexEndpoint:
    """Tests for POST /api/emails/search/rebuild-index endpoint.

    M-2 (audit security.md, issue #536): the route is now `@require_admin`.
    The autouse fixture stubs admin auth and auto-injects the Bearer header
    so the existing happy-path / failure-path assertions stay focused on
    the service behaviour rather than auth plumbing. Cross-tenant /
    non-admin rejection is regression-tested in
    `tests/audit_fixes/test_m_02_search_index_admin.py`.
    """

    @pytest.fixture(autouse=True)
    def _stub_admin(self, monkeypatch, client):
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        original_post = client.post

        def _post_with_admin(*args, **kwargs):
            headers = kwargs.pop("headers", None) or {}
            if "Authorization" not in headers:
                headers["Authorization"] = "Bearer admin-stub"
            return original_post(*args, headers=headers, **kwargs)

        monkeypatch.setattr(client, "post", _post_with_admin)
        yield

    @patch("app.api.search.get_search_service")
    def test_rebuild_index_success(self, mock_get_service, client):
        """Test successful index rebuild."""
        mock_service = MagicMock()
        mock_service.rebuild_index.return_value = True
        mock_get_service.return_value = mock_service

        response = client.post("/api/emails/search/rebuild-index")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    @patch("app.api.search.get_search_service")
    def test_rebuild_index_failure(self, mock_get_service, client):
        """Test index rebuild failure."""
        mock_service = MagicMock()
        mock_service.rebuild_index.return_value = False
        mock_get_service.return_value = mock_service

        response = client.post("/api/emails/search/rebuild-index")

        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False


class TestOptimizeIndexEndpoint:
    """Tests for POST /api/emails/search/optimize-index endpoint.

    M-2: same admin gate as rebuild — same auto-admin fixture.
    """

    @pytest.fixture(autouse=True)
    def _stub_admin(self, monkeypatch, client):
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        original_post = client.post

        def _post_with_admin(*args, **kwargs):
            headers = kwargs.pop("headers", None) or {}
            if "Authorization" not in headers:
                headers["Authorization"] = "Bearer admin-stub"
            return original_post(*args, headers=headers, **kwargs)

        monkeypatch.setattr(client, "post", _post_with_admin)
        yield

    @patch("app.api.search.get_search_service")
    def test_optimize_index_success(self, mock_get_service, client):
        """Test successful index optimization."""
        mock_service = MagicMock()
        mock_service.optimize_index.return_value = True
        mock_get_service.return_value = mock_service

        response = client.post("/api/emails/search/optimize-index")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    @patch("app.api.search.get_search_service")
    def test_optimize_index_failure(self, mock_get_service, client):
        """Test index optimization failure."""
        mock_service = MagicMock()
        mock_service.optimize_index.return_value = False
        mock_get_service.return_value = mock_service

        response = client.post("/api/emails/search/optimize-index")

        assert response.status_code == 500
        data = response.get_json()
        assert data["success"] is False
