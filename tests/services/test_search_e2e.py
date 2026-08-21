"""
E2E tests for search query parsing, filter combination, and SQL generation.

Tests the full search pipeline: query parsing → filter extraction → SQL/FTS construction.
Validates multi-filter combinations, edge cases, and fallback behavior.

pytest tests/services/test_search_e2e.py -v
"""

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from app.services.search_service import (
    SearchService,
    QueryParser,
    ParsedQuery,
)


# ============================================================================
# HELPERS
# ============================================================================


def parse(query: str) -> ParsedQuery:
    """Shortcut to parse a query into ParsedQuery."""
    return QueryParser(original_query=query).parse_advanced()


def sql_filters(query: str, account_id=None) -> tuple:
    """Return (where_parts, params) from parsing a query."""
    parsed = parse(query)
    params = {}
    parts = SearchService._apply_sql_filters("", params, parsed, account_id)
    return parts, params


# ============================================================================
# 1. SINGLE FILTER PARSING
# ============================================================================


class TestSingleFilterParsing:
    """Each filter type parsed correctly in isolation."""

    def test_from_filter(self):
        p = parse("from:alice@company.com")
        assert p.from_filters == ["alice@company.com"]
        assert p.fts_query == ""

    def test_to_filter(self):
        p = parse("to:bob@team.com")
        assert p.to_filters == ["bob@team.com"]
        assert p.fts_query == ""

    def test_cc_filter(self):
        p = parse("cc:manager@corp.com")
        assert p.cc_filters == ["manager@corp.com"]
        assert p.fts_query == ""

    def test_subject_filter(self):
        p = parse("subject:meeting")
        assert p.subject_filters == ["meeting"]
        assert "subject:meeting*" in p.fts_query

    def test_subject_filter_multi_word_quoted(self):
        """subject:"project update" — tokenizer splits at quote, subject: gets empty value."""
        p = parse('subject:"project update"')
        # Currently tokenizer splits this into subject: and "project update"
        # The quoted phrase goes to FTS, subject: is empty
        assert '"project update"' in p.fts_query

    def test_body_filter(self):
        p = parse("body:invoice")
        assert "body_text:invoice*" in p.fts_query

    def test_contenu_filter_fr(self):
        p = parse("contenu:facture")
        assert "body_text:facture*" in p.fts_query

    def test_label_filter(self):
        p = parse("label:Action")
        assert p.label_filter == "Action"

    def test_has_attachment(self):
        p = parse("has:attachment")
        assert p.has_attachment is True

    def test_has_unread(self):
        p = parse("has:unread")
        assert p.has_unread is True

    def test_is_unread(self):
        p = parse("is:unread")
        assert p.has_unread is True

    def test_after_date(self):
        p = parse("after:2026-01-15")
        assert p.after_date == "2026-01-15"

    def test_before_date(self):
        p = parse("before:2026-03-01")
        assert p.before_date == "2026-03-01"

    def test_after_date_slash_format(self):
        p = parse("after:2026/01/15")
        assert p.after_date == "2026-01-15"

    def test_exclude_term(self):
        p = parse("-spam")
        assert p.exclude_terms == ["spam"]
        assert "NOT spam" in p.fts_query

    def test_free_text(self):
        p = parse("agentys")
        assert p.fts_query == "agentys*"

    def test_quoted_phrase(self):
        p = parse('"exact phrase"')
        assert p.fts_query == '"exact phrase"'

    def test_de_alias_for_from(self):
        """FR alias de: — not handled at backend level (frontend maps it)."""
        p = parse("de:alice@test.com")
        # Backend doesn't handle de: alias — frontend SmartSearchBar does
        # de: is treated as free text by backend
        assert p.from_filters == [] or "alice@test.com" in str(p.fts_query)

    def test_objet_alias_for_subject(self):
        """FR alias objet: — not handled at backend level (frontend maps it)."""
        p = parse("objet:urgent")
        # Backend doesn't handle objet: alias — frontend SmartSearchBar does
        assert p.subject_filters == [] or "urgent" in str(p.fts_query)


# ============================================================================
# 2. MULTI-FILTER COMBINATIONS
# ============================================================================


class TestMultiFilterCombinations:
    """Multiple filters combined correctly."""

    def test_from_and_subject(self):
        """The exact user scenario: from:X subject:Y."""
        p = parse("from:alexandre@hotmail.com subject:agentys")
        assert p.from_filters == ["alexandre@hotmail.com"]
        assert p.subject_filters == ["agentys"]
        assert "subject:agentys*" in p.fts_query

    def test_from_and_free_text(self):
        p = parse("from:john meeting")
        assert p.from_filters == ["john"]
        assert "meeting*" in p.fts_query

    def test_from_and_to(self):
        p = parse("from:alice@co.com to:bob@co.com")
        assert p.from_filters == ["alice@co.com"]
        assert p.to_filters == ["bob@co.com"]

    def test_from_subject_and_text(self):
        p = parse("from:boss subject:review urgent")
        assert p.from_filters == ["boss"]
        assert p.subject_filters == ["review"]
        assert "urgent*" in p.fts_query
        assert "subject:review*" in p.fts_query

    def test_from_and_date_range(self):
        p = parse("from:client@co.com after:2026-01-01 before:2026-03-01")
        assert p.from_filters == ["client@co.com"]
        assert p.after_date == "2026-01-01"
        assert p.before_date == "2026-03-01"

    def test_subject_and_label(self):
        p = parse("subject:invoice label:Action")
        assert p.subject_filters == ["invoice"]
        assert p.label_filter == "Action"

    def test_from_and_has_attachment(self):
        p = parse("from:vendor@co.com has:attachment")
        assert p.from_filters == ["vendor@co.com"]
        assert p.has_attachment is True

    def test_text_with_exclusion(self):
        p = parse("meeting -cancelled")
        assert "meeting*" in p.fts_query
        assert "NOT cancelled" in p.fts_query

    def test_from_to_subject_text_date(self):
        """Kitchen sink: all filter types combined."""
        p = parse("from:alice to:bob subject:budget report after:2026-01-01")
        assert p.from_filters == ["alice"]
        assert p.to_filters == ["bob"]
        assert p.subject_filters == ["budget"]
        assert "report*" in p.fts_query
        assert p.after_date == "2026-01-01"

    def test_multiple_from_filters(self):
        p = parse("from:alice from:bob")
        assert p.from_filters == ["alice", "bob"]

    def test_multiple_subject_filters(self):
        p = parse("subject:meeting subject:urgent")
        assert p.subject_filters == ["meeting", "urgent"]


# ============================================================================
# 3. SQL FILTER GENERATION
# ============================================================================


class TestSQLFilterGeneration:
    """_apply_sql_filters generates correct SQL parts and params."""

    def test_from_generates_like(self):
        parts, params = sql_filters("from:alice@co.com")
        assert any("e.sender LIKE" in p for p in parts)
        assert params["from_0"] == "%alice@co.com%"

    def test_subject_generates_like(self):
        parts, params = sql_filters("subject:meeting")
        assert any("e.subject LIKE" in p for p in parts)
        assert params["subj_0"] == "%meeting%"

    def test_to_generates_like(self):
        parts, params = sql_filters("to:bob@co.com")
        assert any("e.recipients LIKE" in p for p in parts)
        assert params["to_0"] == "%bob@co.com%"

    def test_cc_generates_like(self):
        parts, params = sql_filters("cc:manager@co.com")
        assert any("e.cc LIKE" in p for p in parts)
        assert params["cc_0"] == "%manager@co.com%"

    def test_has_attachment_sql(self):
        parts, _ = sql_filters("has:attachment")
        assert any("attachments_meta" in p for p in parts)

    def test_has_unread_sql(self):
        parts, params = sql_filters("has:unread")
        assert any("is_read = :is_read_unread" in p for p in parts)
        assert params["is_read_unread"] is False

    def test_folder_filters_use_boolean_params(self):
        parts, params = sql_filters("in:sent in:inbox")
        joined = " ".join(parts)

        assert "e.is_sent = :folder_is_sent_true" in joined
        assert "e.is_sent = :folder_is_sent_false" in joined
        assert params["folder_is_sent_true"] is True
        assert params["folder_is_sent_false"] is False

    def test_after_date_sql(self):
        parts, params = sql_filters("after:2026-01-15")
        assert any("e.date >= :after_date" in p for p in parts)
        assert params["after_date"] == "2026-01-15"

    def test_before_date_sql(self):
        parts, params = sql_filters("before:2026-03-01")
        assert any("e.date <= :before_date" in p for p in parts)
        assert params["before_date"] == "2026-03-01"

    def test_account_id_filter(self):
        parts, params = sql_filters("meeting", account_id=1)
        assert any("account_id" in p for p in parts)
        assert params["account_id"] == 1

    def test_combined_from_subject_sql(self):
        """from + subject both generate SQL AND conditions."""
        parts, params = sql_filters("from:alice@co.com subject:agentys")
        sender_parts = [p for p in parts if "sender" in p]
        subject_parts = [p for p in parts if "subject" in p]
        assert len(sender_parts) == 1
        assert len(subject_parts) == 1
        assert params["from_0"] == "%alice@co.com%"
        assert params["subj_0"] == "%agentys%"

    def test_multiple_from_generates_or(self):
        """Multiple from: → OR within the from condition."""
        parts, params = sql_filters("from:alice from:bob")
        from_part = [p for p in parts if "sender" in p][0]
        assert "OR" in from_part
        assert params["from_0"] == "%alice%"
        assert params["from_1"] == "%bob%"


# ============================================================================
# 4. FTS QUERY CONSTRUCTION
# ============================================================================


class TestFTSQueryConstruction:
    """FTS5 MATCH queries built correctly."""

    def test_simple_term_gets_wildcard(self):
        p = parse("meeting")
        assert p.fts_query == "meeting*"

    def test_short_term_gets_wildcard(self):
        p = parse("hi")
        assert p.fts_query == "hi*"

    def test_single_char_no_wildcard(self):
        """Single char term should not get wildcard (len < 2)."""
        p = parse("a")
        assert p.fts_query == "a"

    def test_quoted_no_wildcard(self):
        p = parse('"exact match"')
        assert p.fts_query == '"exact match"'
        assert "*" not in p.fts_query

    def test_subject_gets_wildcard(self):
        p = parse("subject:urgent")
        assert p.fts_query == "subject:urgent*"

    def test_body_gets_wildcard(self):
        p = parse("body:invoice")
        assert p.fts_query == "body_text:invoice*"

    def test_contenu_maps_to_body_text(self):
        p = parse("contenu:facture")
        assert p.fts_query == "body_text:facture*"

    def test_exclusion_in_fts(self):
        p = parse("meeting -spam")
        assert "meeting*" in p.fts_query
        assert "NOT spam" in p.fts_query

    def test_from_not_in_fts(self):
        """from: should NOT appear in FTS query."""
        p = parse("from:john")
        assert p.fts_query == ""
        assert "john" not in p.fts_query

    def test_mixed_fts_and_sql(self):
        """Only FTS-compatible parts in fts_query."""
        p = parse("from:alice subject:review project")
        assert "subject:review*" in p.fts_query
        assert "project*" in p.fts_query
        assert "alice" not in p.fts_query


# ============================================================================
# 5. EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_empty_query(self):
        p = parse("")
        assert p.fts_query == ""
        assert p.from_filters == []
        assert p.subject_filters == []

    def test_whitespace_only(self):
        p = parse("   ")
        assert p.fts_query == ""

    def test_from_with_no_value(self):
        p = parse("from:")
        assert p.from_filters == [""]

    def test_subject_with_no_value(self):
        p = parse("subject:")
        assert p.subject_filters == []

    def test_case_insensitive_prefix(self):
        p = parse("FROM:alice SUBJECT:urgent")
        assert p.from_filters == ["alice"]
        assert p.subject_filters == ["urgent"]

    def test_special_chars_in_value(self):
        """Email addresses with dots and @ should parse correctly."""
        p = parse("from:user.name+tag@sub.domain.com")
        assert p.from_filters == ["user.name+tag@sub.domain.com"]

    def test_multiple_colons_in_value(self):
        """Value containing colons (e.g. URL)."""
        p = parse("body:https://example.com")
        assert "body_text:https://example.com*" in p.fts_query

    def test_unicode_in_query(self):
        """French characters in search."""
        p = parse("subject:réunion")
        assert p.subject_filters == ["réunion"]

    def test_very_long_query(self):
        """Long query doesn't crash."""
        long_q = "from:a@b.com " + "word " * 50
        p = parse(long_q)
        assert p.from_filters == ["a@b.com"]
        assert len(p.fts_query) > 0

    def test_duplicate_filters(self):
        """Same filter repeated."""
        p = parse("from:alice from:alice")
        assert p.from_filters == ["alice", "alice"]


# ============================================================================
# 6. LIKE FALLBACK
# ============================================================================


class TestLikeFallback:
    """LIKE search fallback uses parsed filters correctly."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        return session

    @pytest.fixture
    def search_service(self, mock_session):
        def session_factory():
            return mock_session
        return SearchService(session_factory=session_factory)

    def test_fts_error_triggers_like_fallback(self, search_service, mock_session):
        """When FTS throws, LIKE search is used."""
        mock_session.execute.side_effect = [
            Exception("FTS error"),
            MagicMock(fetchall=MagicMock(return_value=[])),
            MagicMock(scalar=MagicMock(return_value=0)),
        ]
        response = search_service.search_emails(query="test", account_id=1)
        assert response.total == 0
        assert response.results == []

    def test_fts_zero_results_triggers_like_for_structured(self, search_service, mock_session):
        """When FTS returns 0 results with from: filter, LIKE fallback fires."""
        # FTS search returns 0
        mock_session.execute.return_value.fetchall.return_value = []
        mock_session.execute.return_value.scalar.return_value = 0

        search_service.search_emails(
            query="from:alice subject:agentys", account_id=1
        )
        # Should have attempted at least 2 execute calls (FTS + LIKE fallback)
        assert mock_session.execute.call_count >= 2

    def test_structured_query_not_used_as_raw_like(self, search_service, mock_session):
        """from:X subject:Y should NOT be used as '%from:X subject:Y%' LIKE."""
        mock_session.execute.side_effect = [
            Exception("FTS error"),
            MagicMock(fetchall=MagicMock(return_value=[])),
            MagicMock(scalar=MagicMock(return_value=0)),
        ]
        search_service.search_emails(query="from:alice subject:meeting", account_id=1)

        # Check that the LIKE params don't contain the raw query
        for call in mock_session.execute.call_args_list:
            if len(call.args) > 1 and isinstance(call.args[1], dict):
                for v in call.args[1].values():
                    if isinstance(v, str):
                        assert "from:alice" not in v, "Raw query should not be used in LIKE"


# ============================================================================
# 7. SEARCH SERVICE INTEGRATION
# ============================================================================


class TestSearchServiceIntegration:
    """Integration tests for SearchService.search_emails."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        return session

    @pytest.fixture
    def search_service(self, mock_session):
        def session_factory():
            return mock_session
        return SearchService(session_factory=session_factory)

    def _make_row(self, email_id="msg-1", subject="Test", sender="test@co.com"):
        row = MagicMock()
        row.id = 1
        row.email_id = email_id
        row.subject = subject
        row.sender = sender
        row.date = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        row.snippet = "..."
        row.rank = -0.5
        row.is_read = False
        row.is_starred = False
        return row

    def test_from_only_search(self, search_service, mock_session):
        """from: only → SQL-only path (no FTS)."""
        row = self._make_row(sender="alice@co.com")
        mock_session.execute.return_value.fetchall.return_value = [row]
        mock_session.execute.return_value.scalar.return_value = 1

        resp = search_service.search_emails(query="from:alice", account_id=1)
        assert resp.total == 1

    def test_subject_only_search(self, search_service, mock_session):
        """subject: → FTS + SQL path."""
        row = self._make_row(subject="Agentys AI")
        mock_session.execute.return_value.fetchall.return_value = [row]
        mock_session.execute.return_value.scalar.return_value = 1

        resp = search_service.search_emails(query="subject:agentys", account_id=1)
        assert resp.total == 1

    def test_combined_from_subject_search(self, search_service, mock_session):
        """from: + subject: → FTS + SQL filters combined."""
        row = self._make_row(sender="alice@hotmail.com", subject="Agentys AI")
        mock_session.execute.return_value.fetchall.return_value = [row]
        mock_session.execute.return_value.scalar.return_value = 1

        resp = search_service.search_emails(
            query="from:alice@hotmail.com subject:agentys", account_id=1
        )
        assert resp.total == 1

    def test_empty_query_returns_recent(self, search_service, mock_session):
        """Empty query → recent emails path."""
        mock_query = MagicMock()
        mock_query.order_by.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.offset.return_value.limit.return_value.all.return_value = []
        mock_session.query.return_value = mock_query

        resp = search_service.search_emails(query="", account_id=1)
        assert resp.total == 0

    def test_date_range_search(self, search_service, mock_session):
        """Date range with text → FTS + SQL dates."""
        row = self._make_row()
        mock_session.execute.return_value.fetchall.return_value = [row]
        mock_session.execute.return_value.scalar.return_value = 1

        resp = search_service.search_emails(
            query="meeting after:2026-01-01 before:2026-04-01", account_id=1
        )
        assert resp.total == 1
