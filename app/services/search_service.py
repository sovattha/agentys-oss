# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Full-text search service for emails using SQLite FTS5.

Provides fast email search with:
- Full-text search on subject, body, and sender
- Field-specific search (from:, subject:)
- Phrase search with quotes
- Relevance ranking using BM25
- Search result highlighting
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import should_persist_email_content
from app.db.database import get_db_session
from app.db.models.email import Email

logger = logging.getLogger(__name__)

# Module-level singleton
_search_service: Optional["SearchService"] = None


def normalize_utc_iso(value) -> str:
    """Serialize a DB date (naive-UTC datetime or string) as ISO 8601 UTC ('Z').

    The emails table stores naive UTC timestamps. Returning them without a
    timezone marker made the frontend parse them as *local* time, which
    shifted dates by a day for users west of UTC (QA 2026-06-10: the same
    email showed "May 13th" in the inbox but "May 14th" in search results).
    Mirrors `_to_iso_utc` used by the /api/emails serializer.
    """
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        s = value.isoformat()
    else:
        # SQLite raw rows come back as "YYYY-MM-DD HH:MM:SS[.ffffff]"
        s = str(value).strip().replace(" ", "T", 1)
    if not s:
        return ""
    if s.endswith("+00:00"):
        return s[:-6] + "Z"
    # Naive timestamp (no tz suffix) → it is UTC; mark it so JS parses it as such.
    tail = s[10:]
    if not s.endswith("Z") and "+" not in tail and "-" not in tail:
        s += "Z"
    return s


@dataclass
class SearchResult:
    """Represents a single search result."""

    id: int
    email_id: str
    subject: str
    sender: str
    date: str
    snippet: str
    relevance_score: float
    is_read: bool = False
    is_starred: bool = False

    @classmethod
    def from_row(cls, row) -> "SearchResult":
        """Create SearchResult from database row."""
        return cls(
            id=row.id,
            email_id=row.email_id,
            subject=row.subject or "",
            sender=row.sender,
            date=normalize_utc_iso(row.date),
            snippet=row.snippet or "",
            relevance_score=abs(row.rank) if row.rank else 0.0,
            is_read=row.is_read if hasattr(row, "is_read") else False,
            is_starred=row.is_starred if hasattr(row, "is_starred") else False,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "email_id": self.email_id,
            "subject": self.subject,
            "sender": self.sender,
            "date": self.date,
            "snippet": self.snippet,
            "relevance_score": self.relevance_score,
            "is_read": self.is_read,
            "is_starred": self.is_starred,
        }


def _session_dialect_name(session: Session) -> str:
    """Return the SQLAlchemy dialect name, defaulting tests/mocks to SQLite."""
    try:
        bind = session.get_bind()
        name = getattr(getattr(bind, "dialect", None), "name", "")
    except Exception:
        return "sqlite"
    return name if name in {"sqlite", "postgresql"} else "sqlite"


@dataclass
class SearchResponse:
    """Response from a search query."""

    query: str
    total: int
    results: List[SearchResult]
    duration_ms: float
    has_more: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "query": self.query,
            "total": self.total,
            "results": [r.to_dict() for r in self.results],
            "duration_ms": round(self.duration_ms, 2),
            "has_more": self.has_more,
        }


@dataclass
class ParsedQuery:
    """
    Result of parsing an advanced search query.

    Separates FTS-compatible parts from SQL-level filters that must be
    applied outside of the FTS5 MATCH clause.
    """

    fts_query: str = ""
    from_filters: List[str] = field(default_factory=list)
    to_filters: List[str] = field(default_factory=list)
    cc_filters: List[str] = field(default_factory=list)
    subject_filters: List[str] = field(default_factory=list)
    body_filters: List[str] = field(default_factory=list)
    label_filter: Optional[str] = None
    folder_filters: List[str] = field(default_factory=list)  # inbox, sent, archived, spam, trash
    has_attachment: bool = False
    has_unread: bool = False
    after_date: Optional[str] = None  # YYYY-MM-DD
    before_date: Optional[str] = None  # YYYY-MM-DD
    exclude_terms: List[str] = field(default_factory=list)

    @property
    def to_filter(self) -> Optional[str]:
        """Backward-compat: returns first to_filter value."""
        return self.to_filters[0] if self.to_filters else None


@dataclass
class QueryParser:
    """
    Parses user search queries into FTS5 MATCH syntax + SQL filters.

    Supports:
    - Simple terms: meeting -> meeting
    - Phrases: "project update" -> "project update"
    - Field-specific: from:john -> sender:john (FTS5)
    - Subject-specific: subject:urgent -> subject:urgent (FTS5)
    - Body-specific: body:invoice / contenu:facture -> body_text:... (FTS5)
    - Recipient: to:alice -> SQL filter on recipients/cc
    - Label: label:Action -> post-filter on label assignments
    - Attachment: has:attachment -> SQL filter on attachments_meta
    - Unread: has:unread -> SQL filter on is_read
    - Date range: after:2026/01/01, before:2026/02/01 -> SQL filter on date
    - Exclusion: -word -> NOT term in FTS5
    - Combined: from:boss subject:review -> sender:boss AND subject:review
    """

    original_query: str
    fts_query: str = ""
    errors: List[str] = field(default_factory=list)

    def parse(self) -> str:
        """
        Parse the query and return FTS5-compatible syntax.

        Returns:
            FTS5 MATCH query string (only FTS-compatible parts).
        """
        parsed = self.parse_advanced()
        return parsed.fts_query

    def parse_advanced(self) -> ParsedQuery:
        """
        Parse the query into FTS parts and SQL-level filters.

        Returns:
            ParsedQuery with separated concerns.
        """
        query = self.original_query.strip()
        result = ParsedQuery()

        if not query:
            return result

        # Tokenize first
        tokens = self._tokenize(query)

        fts_tokens = []
        for token in tokens:
            lower = token.lower()

            # to:value -> SQL filter (not in FTS index), supports multiple
            if lower.startswith("to:"):
                result.to_filters.append(token[3:])
                continue

            # cc:value -> SQL filter on cc column
            if lower.startswith("cc:"):
                result.cc_filters.append(token[3:])
                continue

            # has:attachment -> SQL filter
            if lower == "has:attachment":
                result.has_attachment = True
                continue

            # after:YYYY/MM/DD -> SQL filter
            if lower.startswith("after:"):
                date_str = token[6:].replace("/", "-")
                result.after_date = date_str
                continue

            # before:YYYY/MM/DD -> SQL filter
            if lower.startswith("before:"):
                date_str = token[7:].replace("/", "-")
                result.before_date = date_str
                continue

            # -term -> exclusion (FTS5 NOT)
            if token.startswith("-") and len(token) > 1 and not token.startswith("-\""):
                result.exclude_terms.append(token[1:])
                continue

            # from:value -> SQL LIKE filter on sender (handles emails with @/. reliably)
            if lower.startswith("from:"):
                result.from_filters.append(token[5:])
                continue

            # subject:value -> FTS5 column filter + SQL fallback
            if lower.startswith("subject:"):
                val = token[8:]
                if val:
                    result.subject_filters.append(val.strip('"'))
                    if not val.startswith('"'):
                        fts_tokens.append(f"subject:{val}*")
                    else:
                        fts_tokens.append(token)
                continue

            # body:/contenu: -> body_text: (FTS5 column filter with prefix wildcard)
            if lower.startswith("body:"):
                val = token[5:]
                if val:
                    result.body_filters.append(val.strip('"'))
                fts_tokens.append(f"body_text:{val}*" if val and not val.startswith('"') else f"body_text:{val}")
                continue
            if lower.startswith("contenu:"):
                val = token[8:]
                if val:
                    result.body_filters.append(val.strip('"'))
                fts_tokens.append(f"body_text:{val}*" if val and not val.startswith('"') else f"body_text:{val}")
                continue

            # label:value -> SQL filter (not in FTS index)
            if lower.startswith("label:"):
                result.label_filter = token[6:]
                continue

            # in:/folder:/dossier: -> SQL filter on folder/is_sent
            if lower.startswith("in:") or lower.startswith("folder:") or lower.startswith("dossier:"):
                val = token.split(":", 1)[1].lower().strip()
                # Normalize French aliases
                folder_map = {
                    "inbox": "inbox", "reception": "inbox", "réception": "inbox",
                    "sent": "sent", "envoyés": "sent", "envoyes": "sent", "envoyé": "sent",
                    "archived": "archived", "archivés": "archived", "archives": "archived",
                    "spam": "spam",
                    "trash": "trash", "corbeille": "trash",
                }
                normalized = folder_map.get(val, val)
                if normalized == "all":
                    result.folder_filters.clear()  # "all" = no filter
                elif normalized in ("inbox", "sent", "archived", "spam", "trash"):
                    result.folder_filters.append(normalized)
                continue

            # has:unread / is:unread -> SQL filter on is_read
            if lower in ("has:unread", "is:unread"):
                result.has_unread = True
                continue

            # Regular term or quoted phrase
            # Add prefix wildcard for partial matching (meet -> meet*)
            # Skip for quoted phrases and field:value tokens
            if not token.startswith('"') and ":" not in token and len(token) >= 2:
                fts_tokens.append(f"{token}*")
            else:
                fts_tokens.append(token)

        # Build FTS query with exclusions
        if fts_tokens or result.exclude_terms:
            parts = []
            if fts_tokens:
                parts.append(" ".join(fts_tokens))
            for term in result.exclude_terms:
                parts.append(f"NOT {term}")
            result.fts_query = " ".join(parts)

        self.fts_query = result.fts_query
        return result

    def _tokenize(self, query: str) -> List[str]:
        """
        Tokenize query preserving quoted phrases and field:value pairs.

        Args:
            query: The search query string.

        Returns:
            List of tokens.
        """
        tokens = []
        i = 0
        current_token = []

        while i < len(query):
            char = query[i]

            if char == '"':
                # Start of quoted phrase
                end_quote = query.find('"', i + 1)
                if end_quote != -1:
                    # Include the quotes for FTS5
                    phrase = query[i : end_quote + 1]
                    tokens.append(phrase)
                    i = end_quote + 1
                else:
                    # Unmatched quote - treat as regular char
                    current_token.append(char)
                    i += 1
            elif char.isspace():
                # End of token
                if current_token:
                    tokens.append("".join(current_token))
                    current_token = []
                i += 1
            else:
                current_token.append(char)
                i += 1

        # Don't forget last token
        if current_token:
            tokens.append("".join(current_token))

        return tokens


class SearchService:
    """
    Email search service using SQLite FTS5.

    Provides full-text search with relevance ranking, highlighting,
    and support for advanced search syntax.
    """

    def __init__(self, session_factory=None):
        """
        Initialize search service.

        Args:
            session_factory: Optional session factory for testing.
        """
        self._session_factory = session_factory or get_db_session

    def search_emails(
        self,
        query: str,
        account_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResponse:
        """
        Search emails using FTS5 full-text search.

        Args:
            query: Search query string.
            account_id: Optional account ID to filter by.
            limit: Maximum number of results (default 50, max 100).
            offset: Offset for pagination.

        Returns:
            SearchResponse with results and metadata.
        """
        limit = min(limit, 100)
        start_time = time.perf_counter()

        # Parse query into FTS + SQL filters
        parser = QueryParser(original_query=query)
        parsed = parser.parse_advanced()

        if parsed.body_filters and not should_persist_email_content():
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "Body search skipped in metadata-only mode for query '%s'",
                query[:50],
            )
            return SearchResponse(
                query=query,
                total=0,
                results=[],
                duration_ms=duration_ms,
                has_more=False,
            )

        if not parsed.fts_query and not any([
            parsed.from_filters, parsed.to_filters, parsed.cc_filters,
            parsed.subject_filters, parsed.folder_filters,
            parsed.has_attachment, parsed.has_unread,
            parsed.after_date, parsed.before_date, parsed.label_filter,
        ]):
            # Empty query - return recent emails
            return self._get_recent_emails(account_id, limit, offset, start_time)

        # Label-only search: fetch matching email_ids from label store first,
        # then query the DB directly — avoids the LIMIT-50 post-filter bug.
        if parsed.label_filter and not parsed.fts_query and not any([
            parsed.to_filters, parsed.cc_filters, parsed.has_attachment, parsed.has_unread,
            parsed.after_date, parsed.before_date,
        ]):
            with self._session_factory() as session:
                results, total = self._search_by_label(
                    session, parsed.label_filter, account_id, limit, offset
                )
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                f"Label search '{parsed.label_filter}' returned {len(results)}/{total} "
                f"results in {duration_ms:.1f}ms"
            )
            return SearchResponse(
                query=query,
                total=total,
                results=results,
                duration_ms=duration_ms,
                has_more=(offset + len(results)) < total,
            )

        with self._session_factory() as session:
            dialect_name = _session_dialect_name(session)
            if dialect_name != "sqlite":
                results, total = self._execute_like_search(
                    session, query, account_id, limit, offset,
                    parsed=parsed,
                )
            else:
                try:
                    results, total = self._execute_fts_search(
                        session, parsed, account_id, limit, offset
                    )
                    # If FTS returned 0 results but we have structured filters, try LIKE fallback
                    if total == 0 and (parsed.from_filters or parsed.to_filters or parsed.cc_filters):
                        logger.info(f"FTS returned 0 results for '{query[:50]}', trying LIKE fallback")
                        results, total = self._execute_like_search(
                            session, query, account_id, limit, offset,
                            parsed=parsed,
                        )
                except Exception as e:
                    logger.warning(f"FTS search error for '{query}': {e}")
                    try:
                        session.rollback()
                    except Exception:
                        pass
                    # Fall back to LIKE search if FTS fails
                    results, total = self._execute_like_search(
                        session, query, account_id, limit, offset,
                        parsed=parsed,
                    )

        # Label filtering now happens inside _apply_sql_filters (DB-level
        # intersect via EXISTS on email_labels) so combined label+text search
        # paginates and counts correctly — no single-page post-filter
        # (audit 2026-05-29). _filter_by_label is retained for legacy callers.

        duration_ms = (time.perf_counter() - start_time) * 1000
        has_more = (offset + len(results)) < total

        logger.info(
            f"Search '{query}' returned {len(results)}/{total} results in {duration_ms:.1f}ms"
        )

        return SearchResponse(
            query=query,
            total=total,
            results=results,
            duration_ms=duration_ms,
            has_more=has_more,
        )

    def _filter_by_label(
        self,
        results: List[SearchResult],
        total: int,
        label_name: str,
    ) -> tuple:
        """Filter search results by label using SQLite email_labels table."""
        if not results:
            return results, total
        try:
            email_ids = [r.email_id for r in results]
            placeholders = ", ".join(f":id_{i}" for i in range(len(email_ids)))
            params: dict = {f"id_{i}": eid for i, eid in enumerate(email_ids)}
            params["label_name"] = label_name.lower()

            with self._session_factory() as session:
                sql = f"""
                    SELECT DISTINCT email_id FROM email_labels
                    WHERE email_id IN ({placeholders})
                    AND LOWER(label_name) = :label_name
                """
                rows = session.execute(text(sql), params).fetchall()
            matching_ids = {row[0] for row in rows}
            filtered = [r for r in results if r.email_id in matching_ids]
            return filtered, len(filtered)
        except Exception as e:
            logger.warning(f"Label filter SQL error for '{label_name}': {e}, falling back to JSON")
            # Fallback to JSON scan
            try:
                from app.infrastructure.adapters.label_store import LabelStore
                import os
                storage_dir = os.environ.get("AGENTYS_DATA_DIR", "data")
                label_store = LabelStore(storage_dir=os.path.join(storage_dir, "labels"))
                assignments = label_store.get_assignments(limit=10000)
                matching_ids = set()
                lower_label = label_name.lower()
                for assignment in assignments:
                    if any(lbl.lower() == lower_label for lbl in assignment.labels):
                        matching_ids.add(assignment.email_id)
                filtered = [r for r in results if r.email_id in matching_ids]
                return filtered, len(filtered)
            except Exception as e2:
                logger.warning(f"Label filter JSON fallback error for '{label_name}': {e2}")
                return results, total

    def _search_by_label(
        self,
        session: Session,
        label_name: str,
        account_id: Optional[int],
        limit: int,
        offset: int,
    ) -> tuple:
        """
        Label-first search via SQLite JOIN on email_labels table.
        Falls back to JSON scan if the table doesn't exist yet.
        """
        try:
            return self._search_by_label_sql(session, label_name, account_id, limit, offset)
        except Exception as e:
            logger.warning(f"Label SQL search failed for '{label_name}': {e}, falling back to JSON")
            return self._search_by_label_json(session, label_name, account_id, limit, offset)

    def _search_by_label_sql(
        self,
        session: Session,
        label_name: str,
        account_id: Optional[int],
        limit: int,
        offset: int,
    ) -> tuple:
        """Fast label search using JOIN on email_labels table."""
        params: dict = {"label_name": label_name.lower(), "limit": limit, "offset": offset}

        account_filter = ""
        if account_id is not None:
            account_filter = " AND el.account_id = :account_id"
            params["account_id"] = account_id

        count_sql = f"""
            SELECT COUNT(DISTINCT e.id)
            FROM emails e
            JOIN email_labels el ON el.email_id = e.email_id
            WHERE LOWER(el.label_name) = :label_name{account_filter}
        """
        total = session.execute(text(count_sql), params).scalar() or 0

        if total == 0:
            return [], 0

        sql = f"""
            SELECT
                e.id,
                e.email_id,
                e.subject,
                e.sender,
                e.date,
                e.is_read,
                e.is_starred,
                e.snippet,
                0 as rank
            FROM emails e
            JOIN email_labels el ON el.email_id = e.email_id
            WHERE LOWER(el.label_name) = :label_name{account_filter}
            GROUP BY e.id
            ORDER BY e.date DESC
            LIMIT :limit OFFSET :offset
        """
        rows = session.execute(text(sql), params).fetchall()
        results = [SearchResult.from_row(row) for row in rows]
        return results, total

    def _search_by_label_json(
        self,
        session: Session,
        label_name: str,
        account_id: Optional[int],
        limit: int,
        offset: int,
    ) -> tuple:
        """Legacy label search via JSON assignments scan (fallback)."""
        try:
            from app.infrastructure.adapters.label_store import LabelStore
            import os

            storage_dir = os.environ.get("AGENTYS_DATA_DIR", "data")
            label_store = LabelStore(storage_dir=os.path.join(storage_dir, "labels"))
            assignments = label_store.get_assignments(limit=10000)

            lower_label = label_name.lower()
            matching_ids = [
                a.email_id for a in assignments
                if any(lbl.lower() == lower_label for lbl in a.labels)
            ]
        except Exception as e:
            logger.warning(f"Label JSON lookup failed for '{label_name}': {e}")
            return [], 0

        if not matching_ids:
            return [], 0

        total = len(matching_ids)
        page_ids = matching_ids[offset: offset + limit]

        if not page_ids:
            return [], total

        placeholders = ", ".join(f":id_{i}" for i in range(len(page_ids)))
        params: dict = {f"id_{i}": eid for i, eid in enumerate(page_ids)}

        where_extra = ""
        if account_id is not None:
            where_extra = " AND e.account_id = :account_id"
            params["account_id"] = account_id

        sql = f"""
            SELECT
                e.id,
                e.email_id,
                e.subject,
                e.sender,
                e.date,
                e.is_read,
                e.is_starred,
                e.snippet,
                0 as rank
            FROM emails e
            WHERE e.email_id IN ({placeholders}){where_extra}
            ORDER BY e.date DESC
        """
        rows = session.execute(text(sql), params).fetchall()
        results = [SearchResult.from_row(row) for row in rows]
        return results, total

    @staticmethod
    def _apply_sql_filters(
        where_clause: str,
        params: dict,
        parsed: ParsedQuery,
        account_id: Optional[int],
        like_operator: str = "LIKE",
    ) -> List[str]:
        """Apply SQL-level filters from ParsedQuery to WHERE clause and params."""
        if account_id is not None:
            where_clause_parts = ["e.account_id = :account_id"]
            params["account_id"] = account_id
        else:
            where_clause_parts = []

        if parsed.from_filters:
            conds = " OR ".join(
                f"(e.sender {like_operator} :from_{i} OR e.sender_name {like_operator} :from_{i})"
                for i in range(len(parsed.from_filters))
            )
            where_clause_parts.append(f"({conds})")
            for i, v in enumerate(parsed.from_filters):
                params[f"from_{i}"] = f"%{v}%"

        if parsed.subject_filters:
            conds = " AND ".join(
                f"e.subject {like_operator} :subj_{i}"
                for i in range(len(parsed.subject_filters))
            )
            where_clause_parts.append(f"({conds})")
            for i, v in enumerate(parsed.subject_filters):
                params[f"subj_{i}"] = f"%{v}%"

        if parsed.to_filters:
            conds = " OR ".join(
                f"(e.recipients {like_operator} :to_{i} OR e.cc {like_operator} :to_{i})"
                for i in range(len(parsed.to_filters))
            )
            where_clause_parts.append(f"({conds})")
            for i, v in enumerate(parsed.to_filters):
                params[f"to_{i}"] = f"%{v}%"

        if parsed.cc_filters:
            conds = " OR ".join(
                f"e.cc {like_operator} :cc_{i}" for i in range(len(parsed.cc_filters))
            )
            where_clause_parts.append(f"({conds})")
            for i, v in enumerate(parsed.cc_filters):
                params[f"cc_{i}"] = f"%{v}%"

        if parsed.has_attachment:
            where_clause_parts.append(
                "e.attachments_meta IS NOT NULL AND e.attachments_meta != ''"
            )

        if parsed.has_unread:
            where_clause_parts.append("e.is_read = :is_read_unread")
            params["is_read_unread"] = False

        if parsed.after_date:
            where_clause_parts.append("e.date >= :after_date")
            params["after_date"] = parsed.after_date

        if parsed.before_date:
            where_clause_parts.append("e.date <= :before_date")
            params["before_date"] = parsed.before_date

        if parsed.folder_filters:
            folder_conds = []
            for i, f in enumerate(parsed.folder_filters):
                if f == "sent":
                    folder_conds.append("e.is_sent = :folder_is_sent_true")
                    params["folder_is_sent_true"] = True
                elif f == "inbox":
                    folder_conds.append(
                        "(e.is_sent = :folder_is_sent_false "
                        "AND (e.folder = 'inbox' OR e.folder IS NULL))"
                    )
                    params["folder_is_sent_false"] = False
                else:
                    folder_conds.append(f"e.folder = :folder_{i}")
                    params[f"folder_{i}"] = f
            where_clause_parts.append(f"({' OR '.join(folder_conds)})")

        if parsed.label_filter:
            # Intersect with email_labels at the DB so a combined label+text
            # search paginates and counts correctly (audit 2026-05-29: the label
            # was post-filtered on a single FTS page → wrong total and has_more
            # stuck false). EXISTS is dialect-portable (email_labels is a real
            # table in both SQLite and Postgres) and ties to the already
            # account-scoped `e`, so tenant isolation is preserved.
            where_clause_parts.append(
                "EXISTS (SELECT 1 FROM email_labels el "
                "WHERE el.email_id = e.email_id "
                "AND LOWER(el.label_name) = :label_filter_name)"
            )
            params["label_filter_name"] = parsed.label_filter.lower()

        return where_clause_parts

    def _execute_fts_search(
        self,
        session: Session,
        parsed: ParsedQuery,
        account_id: Optional[int],
        limit: int,
        offset: int,
    ) -> tuple:
        """
        Execute FTS5 search query with advanced filters.

        Args:
            session: Database session.
            parsed: ParsedQuery with FTS query and SQL filters.
            account_id: Optional account ID filter.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            Tuple of (results list, total count).
        """
        params = {"limit": limit, "offset": offset}
        persist_content = should_persist_email_content()
        snippet_expr = (
            "snippet(emails_fts, 1, '<mark>', '</mark>', '...', 32)"
            if persist_content
            else "''"
        )

        # If there's an FTS query, use MATCH; otherwise just use SQL filters
        if parsed.fts_query:
            where_clause = "WHERE emails_fts MATCH :query"
            params["query"] = parsed.fts_query
            extra_parts = self._apply_sql_filters("", params, parsed, account_id)
            for part in extra_parts:
                where_clause += f" AND {part}"

            sql = f"""
                SELECT
                    e.id,
                    e.email_id,
                    e.subject,
                    e.sender,
                    e.date,
                    e.is_read,
                    e.is_starred,
                    {snippet_expr} as snippet,
                    bm25(emails_fts) as rank
                FROM emails_fts
                JOIN emails e ON e.id = emails_fts.rowid
                {where_clause}
                ORDER BY rank
                LIMIT :limit OFFSET :offset
            """
        else:
            # No FTS query — only SQL filters (e.g., to:, has:attachment, dates)
            extra_parts = self._apply_sql_filters("", params, parsed, account_id)
            where_clause = "WHERE " + " AND ".join(extra_parts) if extra_parts else ""

            sql = f"""
                SELECT
                    e.id,
                    e.email_id,
                    e.subject,
                    e.sender,
                    e.date,
                    e.is_read,
                    e.is_starred,
                    e.snippet,
                    0 as rank
                FROM emails e
                {where_clause}
                ORDER BY e.date DESC
                LIMIT :limit OFFSET :offset
            """

        rows = session.execute(text(sql), params).fetchall()
        results = [SearchResult.from_row(row) for row in rows]

        # Get total count (without LIMIT)
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        if parsed.fts_query:
            count_sql = f"""
                SELECT COUNT(*) as cnt
                FROM emails_fts
                JOIN emails e ON e.id = emails_fts.rowid
                {where_clause}
            """
        else:
            count_sql = f"""
                SELECT COUNT(*) as cnt
                FROM emails e
                {where_clause}
            """
        total = session.execute(text(count_sql), count_params).scalar() or 0

        return results, total

    def _execute_like_search(
        self,
        session: Session,
        query: str,
        account_id: Optional[int],
        limit: int,
        offset: int,
        parsed: Optional[ParsedQuery] = None,
    ) -> tuple:
        """
        Fallback LIKE search when FTS fails.

        Args:
            session: Database session.
            query: Original search query.
            account_id: Optional account ID filter.
            limit: Maximum results.
            offset: Pagination offset.
            parsed: Optional ParsedQuery with SQL-level filters.

        Returns:
            Tuple of (results list, total count).
        """
        # Build LIKE fallback from parsed filters (not raw query string)
        params = {"limit": limit, "offset": offset}
        where_parts = []
        like_operator = "ILIKE" if _session_dialect_name(session) == "postgresql" else "LIKE"

        if account_id is not None:
            where_parts.append("e.account_id = :account_id")
            params["account_id"] = account_id

        # Apply structured SQL filters from parsed query (from:, to:, dates, etc.)
        if parsed:
            extra_parts = self._apply_sql_filters(
                "",
                params,
                parsed,
                None if account_id is not None else account_id,
                like_operator=like_operator,
            )
            for part in extra_parts:
                if "account_id" in part and account_id is not None:
                    continue
                where_parts.append(part)

            # Free-text terms from FTS query (not field:value) as broad LIKE
            if parsed.fts_query:
                import re as _re
                free_terms = _re.sub(r'\b(?:subject|body_text|sender):\S+', '', parsed.fts_query).strip()
                free_terms = _re.sub(r'NOT\s+\S+', '', free_terms).strip()
                if free_terms:
                    clean = free_terms.replace('*', '')
                    if clean:
                        if should_persist_email_content():
                            where_parts.append(f"(e.subject {like_operator} :free_search OR e.body_text {like_operator} :free_search OR e.sender {like_operator} :free_search)")
                        else:
                            where_parts.append(f"(e.subject {like_operator} :free_search OR e.sender {like_operator} :free_search)")
                        params["free_search"] = f"%{clean}%"

        if not where_parts:
            # No parsed filters — use raw query as fallback
            search_term = f"%{query}%"
            if should_persist_email_content():
                where_parts.append(f"(e.subject {like_operator} :search OR e.body_text {like_operator} :search OR e.sender {like_operator} :search)")
            else:
                where_parts.append(f"(e.subject {like_operator} :search OR e.sender {like_operator} :search)")
            params["search"] = search_term

        where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""

        sql = f"""
            SELECT
                e.id,
                e.email_id,
                e.subject,
                e.sender,
                e.date,
                e.is_read,
                e.is_starred,
                e.snippet,
                0 as rank
            FROM emails e
            {where_clause}
            ORDER BY e.date DESC
            LIMIT :limit OFFSET :offset
        """

        rows = session.execute(text(sql), params).fetchall()
        results = [SearchResult.from_row(row) for row in rows]

        # Get total count
        count_sql = f"""
            SELECT COUNT(*) as cnt
            FROM emails e
            {where_clause}
        """
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        total = session.execute(text(count_sql), count_params).scalar() or 0

        return results, total

    def _get_recent_emails(
        self,
        account_id: Optional[int],
        limit: int,
        offset: int,
        start_time: float,
    ) -> SearchResponse:
        """
        Get recent emails when query is empty.

        Args:
            account_id: Optional account ID filter.
            limit: Maximum results.
            offset: Pagination offset.
            start_time: Query start time for duration calculation.

        Returns:
            SearchResponse with recent emails.
        """
        with self._session_factory() as session:
            query = (
                session.query(Email)
                .filter(
                    Email.account_id == account_id
                    if account_id is not None
                    else Email.account_id.isnot(None)
                )
                .order_by(Email.date.desc())
            )

            total = query.count()
            emails = query.offset(offset).limit(limit).all()

            results = [
                SearchResult(
                    id=e.id,
                    email_id=e.email_id,
                    subject=e.subject or "",
                    sender=e.sender,
                    date=e.date.isoformat() if e.date else "",
                    snippet=e.snippet or "",
                    relevance_score=0.0,
                    is_read=e.is_read,
                    is_starred=e.is_starred,
                )
                for e in emails
            ]

        duration_ms = (time.perf_counter() - start_time) * 1000
        has_more = (offset + len(results)) < total

        return SearchResponse(
            query="",
            total=total,
            results=results,
            duration_ms=duration_ms,
            has_more=has_more,
        )

    def get_suggestions(
        self,
        query: str,
        account_id: Optional[int] = None,
        limit: int = 5,
    ) -> dict:
        """
        Return search suggestions for a partial query.

        Returns up to `limit` senders, subjects, and labels matching the query.
        """
        q = query.strip().lower()
        if len(q) < 2:
            return {"senders": [], "subjects": [], "labels": []}

        senders = []
        subjects = []
        labels = []

        try:
            with self._session_factory() as session:
                # Senders matching the prefix (by email or name)
                sender_params: dict = {"q": f"{q}%", "limit": limit}
                account_cond = ""
                if account_id is not None:
                    account_cond = " AND account_id = :account_id"
                    sender_params["account_id"] = account_id

                sender_sql = f"""
                    SELECT sender, sender_name, COUNT(*) as cnt
                    FROM emails
                    WHERE (LOWER(sender) LIKE :q OR LOWER(sender_name) LIKE :q){account_cond}
                    GROUP BY sender, sender_name
                    ORDER BY cnt DESC
                    LIMIT :limit
                """
                for row in session.execute(text(sender_sql), sender_params).fetchall():
                    senders.append({
                        "email": row[0] or "",
                        "name": row[1] or "",
                    })

                # Subjects matching the prefix (recent first)
                subject_params: dict = {"q": f"%{q}%", "limit": limit}
                if account_id is not None:
                    subject_params["account_id"] = account_id

                subject_sql = f"""
                    SELECT DISTINCT subject
                    FROM emails
                    WHERE LOWER(subject) LIKE :q{account_cond}
                    ORDER BY date DESC
                    LIMIT :limit
                """
                for row in session.execute(text(subject_sql), subject_params).fetchall():
                    if row[0]:
                        subjects.append(row[0])
        except Exception as e:
            logger.warning(f"Suggestions query error: {e}")

        # Labels: filter in-memory from label store
        try:
            import os
            from app.infrastructure.adapters.label_store import LabelStore
            storage_dir = os.environ.get("AGENTYS_DATA_DIR", "data")
            label_store = LabelStore(storage_dir=os.path.join(storage_dir, "labels"))
            for lbl in label_store.get_labels():
                if q in lbl.name.lower():
                    labels.append({"name": lbl.name, "color": lbl.color})
        except Exception as e:
            logger.warning(f"Suggestions labels error: {e}")

        return {"senders": senders[:limit], "subjects": subjects[:limit], "labels": labels[:limit]}

    def highlight_text(self, text: str, query: str, marker: str = "mark") -> str:
        """
        Highlight search terms in text.

        Args:
            text: Text to highlight.
            query: Search query with terms to highlight.
            marker: HTML tag name for highlighting (default: mark).

        Returns:
            Text with highlighted terms.
        """
        if not text or not query:
            return text

        # Extract terms from query
        terms = []

        # First, extract quoted phrases
        phrase_matches = re.findall(r'"([^"]+)"', query)
        terms.extend(phrase_matches)

        # Remove quoted phrases from query for further processing
        remaining = re.sub(r'"[^"]*"', '', query)

        # Extract individual words, ignoring field prefixes like "from:" or "subject:"
        for word in remaining.split():
            # Skip field prefixes
            if ':' in word:
                # Get the part after the colon if it exists
                parts = word.split(':', 1)
                if len(parts) > 1 and parts[1]:
                    terms.append(parts[1])
            else:
                terms.append(word)

        # Highlight each term
        for term in terms:
            if term and len(term) >= 2:  # Only highlight terms with 2+ chars
                # Case-insensitive replacement
                pattern = re.compile(re.escape(term), re.IGNORECASE)
                text = pattern.sub(f"<{marker}>\\g<0></{marker}>", text)

        return text

    def rebuild_index(self) -> bool:
        """
        Rebuild the FTS5 index from the emails table.

        Use this if the index gets out of sync.

        Returns:
            True if successful.
        """
        try:
            with self._session_factory() as session:
                session.execute(text("INSERT INTO emails_fts(emails_fts) VALUES('rebuild')"))
                session.commit()
            logger.info("FTS5 index rebuilt successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to rebuild FTS5 index: {e}")
            return False

    def optimize_index(self) -> bool:
        """
        Optimize the FTS5 index (merge segments).

        Should be run periodically for best performance.

        Returns:
            True if successful.
        """
        try:
            with self._session_factory() as session:
                session.execute(text("INSERT INTO emails_fts(emails_fts) VALUES('optimize')"))
                session.commit()
            logger.info("FTS5 index optimized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to optimize FTS5 index: {e}")
            return False


def get_search_service() -> SearchService:
    """
    Get the singleton SearchService instance.

    Returns:
        SearchService instance.
    """
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service


def init_search_service(session_factory=None) -> SearchService:
    """
    Initialize and return a new SearchService instance.

    Args:
        session_factory: Optional session factory for testing.

    Returns:
        New SearchService instance.
    """
    global _search_service
    _search_service = SearchService(session_factory=session_factory)
    return _search_service
