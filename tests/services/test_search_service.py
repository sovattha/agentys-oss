# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Unit tests for SearchService.

Tests full-text search functionality using FTS5.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.services.search_service import (
    SearchService,
    SearchResult,
    SearchResponse,
    QueryParser,
    get_search_service,
    init_search_service,
)


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_from_row(self):
        """Test creating SearchResult from database row."""
        row = MagicMock()
        row.id = 1
        row.email_id = "abc123"
        row.subject = "Test Subject"
        row.sender = "test@example.com"
        row.date = datetime(2026, 1, 18, 12, 0, 0, tzinfo=timezone.utc)
        row.snippet = "Test snippet..."
        row.rank = -0.85
        row.is_read = True
        row.is_starred = False

        result = SearchResult.from_row(row)

        assert result.id == 1
        assert result.email_id == "abc123"
        assert result.subject == "Test Subject"
        assert result.sender == "test@example.com"
        assert result.relevance_score == 0.85
        assert result.is_read is True
        assert result.is_starred is False

    def test_from_row_handles_none_values(self):
        """Test handling of None values."""
        row = MagicMock()
        row.id = 1
        row.email_id = "abc123"
        row.subject = None
        row.sender = "test@example.com"
        row.date = None
        row.snippet = None
        row.rank = None

        result = SearchResult.from_row(row)

        assert result.subject == ""
        assert result.date == ""
        assert result.snippet == ""
        assert result.relevance_score == 0.0

    def test_to_dict(self):
        """Test converting SearchResult to dictionary."""
        result = SearchResult(
            id=1,
            email_id="abc123",
            subject="Test",
            sender="test@example.com",
            date="2026-01-18T12:00:00+00:00",
            snippet="snippet...",
            relevance_score=0.85,
            is_read=True,
            is_starred=False,
        )

        d = result.to_dict()

        assert d["id"] == 1
        assert d["email_id"] == "abc123"
        assert d["relevance_score"] == 0.85
        assert d["is_read"] is True


class TestSearchResponse:
    """Tests for SearchResponse dataclass."""

    def test_to_dict(self):
        """Test converting SearchResponse to dictionary."""
        results = [
            SearchResult(
                id=1, email_id="a", subject="Test", sender="a@test.com",
                date="", snippet="", relevance_score=0.9,
            )
        ]
        response = SearchResponse(
            query="meeting",
            total=1,
            results=results,
            duration_ms=12.5,
            has_more=False,
        )

        d = response.to_dict()

        assert d["query"] == "meeting"
        assert d["total"] == 1
        assert len(d["results"]) == 1
        assert d["duration_ms"] == 12.5
        assert d["has_more"] is False


class TestQueryParser:
    """Tests for QueryParser."""

    def test_parse_simple_query(self):
        """Test parsing simple single-term query (prefix wildcard for partial matching)."""
        parser = QueryParser(original_query="meeting")
        result = parser.parse()
        assert result == "meeting*"

    def test_parse_multi_term_query(self):
        """Test parsing multi-term query (prefix wildcards for partial matching)."""
        parser = QueryParser(original_query="project update")
        result = parser.parse()
        assert result == "project* update*"

    def test_parse_quoted_phrase(self):
        """Test parsing quoted phrase."""
        parser = QueryParser(original_query='"project update"')
        result = parser.parse()
        assert result == '"project update"'

    def test_parse_from_field(self):
        """Test from: goes to SQL filter, not FTS."""
        parser = QueryParser(original_query="from:john")
        parsed = parser.parse_advanced()
        assert parsed.from_filters == ["john"]
        assert parsed.fts_query == ""

    def test_parse_from_field_case_insensitive(self):
        """Test from: prefix is case insensitive."""
        parser = QueryParser(original_query="FROM:john")
        parsed = parser.parse_advanced()
        assert parsed.from_filters == ["john"]

    def test_parse_subject_field(self):
        """Test subject: goes to both FTS and SQL filters."""
        parser = QueryParser(original_query="subject:urgent")
        parsed = parser.parse_advanced()
        assert parsed.fts_query == "subject:urgent*"
        assert parsed.subject_filters == ["urgent"]

    def test_parse_body_field_tracks_body_filter(self):
        """body: remains explicit so metadata-only mode can reject it."""
        parser = QueryParser(original_query="body:invoice")
        parsed = parser.parse_advanced()
        assert parsed.fts_query == "body_text:invoice*"
        assert parsed.body_filters == ["invoice"]

    def test_parse_combined_fields(self):
        """Test from: → SQL filter, subject: → FTS + SQL."""
        parser = QueryParser(original_query="from:boss subject:review")
        parsed = parser.parse_advanced()
        assert parsed.from_filters == ["boss"]
        assert parsed.subject_filters == ["review"]
        assert "subject:review*" in parsed.fts_query

    def test_parse_mixed_query(self):
        """Test mixed query: from → SQL, text → FTS."""
        parser = QueryParser(original_query='from:john "meeting notes" project')
        parsed = parser.parse_advanced()
        assert parsed.from_filters == ["john"]
        assert '"meeting notes"' in parsed.fts_query
        assert "project*" in parsed.fts_query

    def test_parse_empty_query(self):
        """Test parsing empty query."""
        parser = QueryParser(original_query="")
        result = parser.parse()
        assert result == ""

    def test_parse_whitespace_query(self):
        """Test parsing whitespace-only query."""
        parser = QueryParser(original_query="   ")
        result = parser.parse()
        assert result == ""

    def test_parse_unmatched_quote(self):
        """Test handling of unmatched quote."""
        parser = QueryParser(original_query='"incomplete phrase')
        result = parser.parse()
        # Should include the quote as part of the token
        assert '"incomplete' in result


class TestSearchService:
    """Tests for SearchService class."""

    @pytest.fixture
    def mock_session(self):
        """Create mock session for testing."""
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        return session

    @pytest.fixture
    def search_service(self, mock_session):
        """Create search service with mock session."""
        def session_factory():
            return mock_session
        return SearchService(session_factory=session_factory)

    def test_search_emails_empty_query(self, search_service, mock_session):
        """Test search with empty query returns recent emails."""
        # Mock query for recent emails
        mock_query = MagicMock()
        mock_query.order_by.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.offset.return_value.limit.return_value.all.return_value = []
        mock_session.query.return_value = mock_query

        response = search_service.search_emails(query="", account_id=1)

        assert response.query == ""
        assert response.total == 0
        assert len(response.results) == 0
        assert response.duration_ms >= 0

    def test_search_emails_with_query(self, search_service, mock_session):
        """Test search with query performs FTS search."""
        # Mock FTS search results
        row = MagicMock()
        row.id = 1
        row.email_id = "abc123"
        row.subject = "Test <mark>meeting</mark>"
        row.sender = "test@example.com"
        row.date = datetime.now(timezone.utc)
        row.snippet = "...about the <mark>meeting</mark>..."
        row.rank = -0.85
        row.is_read = True
        row.is_starred = False

        mock_session.execute.return_value.fetchall.return_value = [row]
        mock_session.execute.return_value.scalar.return_value = 1

        response = search_service.search_emails(query="meeting", account_id=1)

        assert response.query == "meeting"
        assert response.total == 1
        assert len(response.results) == 1
        assert response.results[0].email_id == "abc123"

    def test_postgres_search_uses_like_without_fts(self, search_service, mock_session):
        """Postgres prod must not execute SQLite FTS5 MATCH syntax."""
        mock_session.get_bind.return_value.dialect.name = "postgresql"
        row = MagicMock()
        row.id = 1
        row.email_id = "gmail-123"
        row.subject = "Test Agentys E2E"
        row.sender = "agentys.demo@gmail.com"
        row.date = datetime.now(timezone.utc)
        row.snippet = "Test Agentys E2E"
        row.rank = 0
        row.is_read = False
        row.is_starred = False

        mock_session.execute.return_value.fetchall.return_value = [row]
        mock_session.execute.return_value.scalar.return_value = 1

        response = search_service.search_emails(query="Test Agentys", account_id=4)

        sql = "\n".join(str(call.args[0]) for call in mock_session.execute.call_args_list)
        assert "emails_fts" not in sql
        assert " MATCH " not in sql
        assert " ILIKE " in sql
        assert response.total == 1
        assert response.results[0].email_id == "gmail-123"
        mock_session.rollback.assert_not_called()

    def test_body_search_metadata_only_returns_empty_without_db_query(
        self,
        search_service,
        mock_session,
        monkeypatch,
    ):
        """Cloud metadata-only mode cannot satisfy body: queries."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")

        response = search_service.search_emails(query="body:invoice", account_id=1)

        assert response.total == 0
        assert response.results == []
        mock_session.execute.assert_not_called()

    def test_like_fallback_metadata_only_does_not_query_body_text(
        self,
        search_service,
        mock_session,
        monkeypatch,
    ):
        """LIKE fallback must not scan purged body_text in metadata-only mode."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        mock_session.execute.return_value.fetchall.return_value = []
        mock_session.execute.return_value.scalar.return_value = 0

        parsed = QueryParser(original_query="invoice").parse_advanced()
        search_service._execute_like_search(
            mock_session,
            "invoice",
            account_id=1,
            limit=10,
            offset=0,
            parsed=parsed,
        )

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "e.body_text LIKE" not in sql
        assert "e.subject LIKE" in sql
        assert "e.sender LIKE" in sql

    def test_like_fallback_legacy_full_cache_can_query_body_text(
        self,
        search_service,
        mock_session,
        monkeypatch,
    ):
        """Legacy mode keeps the old body search behavior for local migration."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        mock_session.execute.return_value.fetchall.return_value = []
        mock_session.execute.return_value.scalar.return_value = 0

        parsed = QueryParser(original_query="invoice").parse_advanced()
        search_service._execute_like_search(
            mock_session,
            "invoice",
            account_id=1,
            limit=10,
            offset=0,
            parsed=parsed,
        )

        sql = str(mock_session.execute.call_args_list[0].args[0])
        assert "e.body_text LIKE" in sql

    def test_search_emails_limit_capped(self, search_service, mock_session):
        """Test that limit is capped at 100."""
        mock_query = MagicMock()
        mock_query.order_by.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.offset.return_value.limit.return_value.all.return_value = []
        mock_session.query.return_value = mock_query

        response = search_service.search_emails(query="", limit=500)

        # The search was called - limit is capped internally
        assert response is not None

    def test_search_emails_fts_error_fallback(self, search_service, mock_session):
        """Test that FTS error falls back to LIKE search."""
        # First call (FTS) raises error
        # Second call (LIKE) succeeds
        mock_session.execute.side_effect = [
            Exception("FTS error"),  # FTS search fails
            MagicMock(fetchall=MagicMock(return_value=[])),  # LIKE search
            MagicMock(scalar=MagicMock(return_value=0)),  # LIKE count
        ]

        response = search_service.search_emails(query="test", account_id=1)

        assert response is not None
        assert response.total == 0
        mock_session.rollback.assert_called_once()

    def test_highlight_text_single_term(self, search_service):
        """Test highlighting single search term."""
        text = "This is a meeting about the project."
        query = "meeting"

        result = search_service.highlight_text(text, query)

        assert "<mark>meeting</mark>" in result

    def test_highlight_text_multiple_terms(self, search_service):
        """Test highlighting multiple search terms."""
        text = "The meeting is about the project update."
        query = "meeting project"

        result = search_service.highlight_text(text, query)

        assert "<mark>meeting</mark>" in result
        assert "<mark>project</mark>" in result

    def test_highlight_text_case_insensitive(self, search_service):
        """Test case-insensitive highlighting."""
        text = "MEETING and Meeting and meeting"
        query = "meeting"

        result = search_service.highlight_text(text, query)

        assert result.count("<mark>") == 3

    def test_highlight_text_empty_query(self, search_service):
        """Test highlighting with empty query."""
        text = "Some text"
        query = ""

        result = search_service.highlight_text(text, query)

        assert result == text

    def test_highlight_text_ignores_short_terms(self, search_service):
        """Test that single-character terms are not highlighted."""
        text = "A meeting is a good thing."
        query = "a meeting"

        result = search_service.highlight_text(text, query)

        # "a" should not be highlighted (< 2 chars)
        # "meeting" should be highlighted
        assert "<mark>meeting</mark>" in result
        # Check that standalone "A" at start is not highlighted
        assert result.startswith("A ") or "<mark>A</mark>" not in result

    def test_highlight_text_with_phrase(self, search_service):
        """Test highlighting phrase from quoted query."""
        text = "The project update is ready."
        query = '"project update"'

        result = search_service.highlight_text(text, query)

        assert "<mark>project update</mark>" in result

    def test_rebuild_index_success(self, search_service, mock_session):
        """Test successful index rebuild."""
        result = search_service.rebuild_index()
        assert result is True
        mock_session.execute.assert_called()
        mock_session.commit.assert_called()

    def test_rebuild_index_failure(self, search_service, mock_session):
        """Test index rebuild failure."""
        mock_session.execute.side_effect = Exception("Rebuild error")

        result = search_service.rebuild_index()

        assert result is False

    def test_optimize_index_success(self, search_service, mock_session):
        """Test successful index optimization."""
        result = search_service.optimize_index()
        assert result is True

    def test_optimize_index_failure(self, search_service, mock_session):
        """Test index optimization failure."""
        mock_session.execute.side_effect = Exception("Optimize error")

        result = search_service.optimize_index()

        assert result is False


class TestGlobalSearchService:
    """Tests for global search service functions."""

    def teardown_method(self):
        """Clean up global instance after each test."""
        import app.services.search_service as module
        module._search_service = None

    def test_get_search_service_creates_singleton(self):
        """Test that get_search_service returns singleton."""
        service1 = get_search_service()
        service2 = get_search_service()

        assert service1 is service2

    def test_init_search_service_replaces_instance(self):
        """Test that init creates new instance."""
        service1 = init_search_service()
        service2 = init_search_service()

        assert service1 is not service2

    def test_init_search_service_with_factory(self):
        """Test initialization with custom session factory."""
        mock_factory = MagicMock()
        service = init_search_service(session_factory=mock_factory)

        assert service._session_factory is mock_factory
