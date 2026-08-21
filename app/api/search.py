# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Search API Blueprint.

Provides endpoints for email search functionality.
"""

import logging
import re
import threading
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

from app.api.admin import require_admin
from app.services.search_service import SearchResult, SearchResponse, get_search_service, normalize_utc_iso

logger = logging.getLogger(__name__)

# ── Provider fallback constants ──────────────────────────────────────────────
# Trigger provider search when SQLite returns fewer than this many results
_PROVIDER_FALLBACK_MIN = 5
# Always try provider when query contains a date filter older than N days
_OLD_DATE_THRESHOLD_DAYS = 120


def _has_old_date_filter(query: str) -> bool:
    """Return True if query has after:/before: referencing a date older than threshold."""
    cutoff = date.today() - timedelta(days=_OLD_DATE_THRESHOLD_DAYS)
    for m in re.finditer(r'(?:after|before):(\d{4}[-/]\d{1,2}[-/]\d{1,2})', query, re.IGNORECASE):
        try:
            d = datetime.strptime(m.group(1).replace('/', '-'), '%Y-%m-%d').date()
            if d < cutoff:
                return True
        except ValueError:
            pass
    return False


def _to_gmail_query(query: str) -> str:
    """Adapt Agentys query syntax to Gmail API search syntax.

    Gmail understands from:, subject:, to:, etc. natively.
    Only date format needs conversion: after:YYYY-MM-DD → after:YYYY/MM/DD.
    """
    def _repl(m: re.Match) -> str:
        return f"{m.group(1)}:{m.group(2).replace('-', '/')}"
    return re.sub(r'(after|before):(\d{4}-\d{2}-\d{2})', _repl, query, flags=re.IGNORECASE)


def _extract_snippet(body: str, query: str, window: int = 160) -> str:
    """Extrait un snippet contextuel autour du premier terme libre de la query.

    Ignore les prefixes from:, to:, subject:, after:, before:, label:, body:, has:.
    Retourne body[:200] si aucun terme ou aucun match.
    """
    # Extraire les termes libres (sans prefix)
    free_terms = []
    for token in query.split():
        if not re.match(r'^(?:from|to|cc|subject|objet|body|contenu|label|after|before|has|is):', token, re.IGNORECASE):
            free_terms.append(re.escape(token))

    if not free_terms or not body:
        return body[:200].replace('\n', ' ').strip()

    # Chercher la première occurrence du premier terme
    pattern = free_terms[0]
    m = re.search(pattern, body, re.IGNORECASE)
    if not m:
        return body[:200].replace('\n', ' ').strip()

    center = m.start()
    start = max(0, center - window // 2)
    end = min(len(body), center + window // 2)
    excerpt = body[start:end].replace('\n', ' ').strip()

    if start > 0:
        excerpt = '...' + excerpt
    if end < len(body):
        excerpt = excerpt + '...'

    return excerpt


def _standard_emails_to_results(emails: list, query: str = "") -> list[SearchResult]:
    """Convert a list of StandardEmail objects to SearchResult objects."""
    results = []
    for e in emails:
        try:
            date_str = normalize_utc_iso(e.received_at)
            raw_metadata = getattr(e, 'raw_metadata', None) or {}
            body = (
                getattr(e, 'body', '')
                or getattr(e, 'html_body', '')
                or raw_metadata.get("snippet", "")
                or ''
            )
            snippet = _extract_snippet(body, query) if query else body[:200].replace('\n', ' ').strip()
            results.append(SearchResult(
                id=0,
                email_id=str(e.id),
                subject=e.subject or "",
                sender=e.sender or "",
                date=date_str,
                snippet=snippet,
                relevance_score=0.0,
                is_read=getattr(e, 'is_read', True),
                is_starred=getattr(e, 'is_starred', False),
            ))
        except Exception as exc:
            logger.debug(f"Could not convert provider email to SearchResult: {exc}")
    return results


def _search_via_provider(query: str, account_id_str: str | None, limit: int, offset: int = 0) -> list[SearchResult]:
    """Query the live email provider for emails not in the SQLite cache.

    Returns an empty list on any error so callers can degrade gracefully.
    """
    try:
        from app.providers.factory import get_pooled_provider
        if not account_id_str:
            return []
        provider = get_pooled_provider(account_id=account_id_str)
        if not provider:
            return []
        if not hasattr(provider, 'search_emails'):
            return []

        # Adapt query syntax for Gmail (IMAP accepts its own subset)
        provider_type = getattr(provider, '_provider_type', '') or type(provider).__name__.lower()
        adapted_query = _to_gmail_query(query) if 'gmail' in provider_type else query

        provider_kwargs = {"limit": limit}
        if offset > 0:
            provider_kwargs["offset"] = offset
        if 'gmail' in provider_type:
            provider_kwargs["include_body"] = False
        try:
            raw = provider.search_emails(adapted_query, **provider_kwargs)
        except TypeError:
            provider_kwargs.pop("include_body", None)
            raw = provider.search_emails(adapted_query, **provider_kwargs)
        results = _standard_emails_to_results(raw, query)

        # Cache provider results in background
        if raw and account_id_str:
            t = threading.Thread(
                target=_cache_provider_results_bg,
                args=(raw, account_id_str),
                daemon=True,
            )
            t.start()

        return results
    except Exception as exc:
        logger.warning(f"Provider search fallback failed: {exc}")
        return []


def _cache_provider_results_bg(emails: list, account_id_str: str) -> None:
    """Upsert provider search results into SQLite (headers only) en background."""
    try:
        from app.db.repositories.email_repository import EmailRepository
        from app.db.models.email import Email as EmailModel
        from app.db.database import get_db_session

        try:
            account_id_int = int(account_id_str)
        except (ValueError, TypeError):
            return

        with get_db_session() as session:
            repo = EmailRepository(session)
            for e in emails:
                try:
                    email_id = str(e.id) if hasattr(e, 'id') else None
                    if not email_id:
                        continue
                    existing = repo.get_by_email_id(email_id, account_id=account_id_int)
                    if existing:
                        continue
                    model = EmailModel(
                        email_id=email_id,
                        account_id=account_id_int,
                        folder='provider_cache',
                        subject=getattr(e, 'subject', '') or '',
                        sender=getattr(e, 'sender', '') or '',
                        recipients=getattr(e, 'recipients', '') or '',
                        received_at=getattr(e, 'received_at', None),
                        is_read=getattr(e, 'is_read', True),
                        is_starred=getattr(e, 'is_starred', False),
                        body='',
                    )
                    repo.create(model)
                except Exception:
                    pass
    except Exception:
        pass


def _search_via_provider_with_timeout(
    query: str,
    account_id_str: str | None,
    limit: int,
    offset: int = 0,
    timeout_s: float = 30.0,
) -> list[SearchResult]:
    """Lance _search_via_provider avec un timeout borné.

    Retourne les résultats disponibles ou [] si timeout atteint.
    """
    result_container: list[list[SearchResult]] = [[]]
    done_event = threading.Event()

    def _run() -> None:
        try:
            result_container[0] = _search_via_provider(query, account_id_str, limit, offset)
        except Exception:
            pass
        finally:
            done_event.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    if not done_event.wait(timeout=timeout_s):
        logger.info("Provider search fallback timed out after %.1fs", timeout_s)
    return result_container[0]


def _merge_results(
    sqlite_results: list[SearchResult],
    provider_results: list[SearchResult],
    limit: int,
) -> list[SearchResult]:
    """Merge SQLite and provider results, deduplicating by email_id.

    SQLite results (with BM25 scores) take priority; provider results
    fill in emails that are not in the local cache.
    """
    seen: set[str] = {r.email_id for r in sqlite_results}
    extra = [r for r in provider_results if r.email_id not in seen]

    # Sort extra by date descending
    extra.sort(key=lambda r: r.date, reverse=True)

    return (sqlite_results + extra)[:limit]

search_bp = Blueprint("search", __name__, url_prefix="/api/emails")
search_alias_bp = Blueprint("search_alias", __name__, url_prefix="/api")

# Constants for input validation
MAX_QUERY_LENGTH = 500
MAX_LIMIT = 100
DEFAULT_LIMIT = 50


@search_bp.route("/search", methods=["GET"])
def search_emails() -> tuple:
    """
    Search emails using full-text search.

    Query Parameters:
        q: Search query string (required unless empty for recent emails)
        account_id: Filter by account ID (optional)
        limit: Maximum results to return (default 50, max 100)
        offset: Pagination offset (default 0)

    Returns:
        JSON with search results:
        {
            "success": true,
            "query": "meeting",
            "total": 23,
            "results": [...],
            "duration_ms": 12.5,
            "has_more": true
        }

    Examples:
        GET /api/emails/search?q=meeting
        GET /api/emails/search?q=from:john
        GET /api/emails/search?q="project update"
        GET /api/emails/search?q=subject:urgent&account_id=1
    """
    # Get and validate query parameter
    query = request.args.get("q", "").strip()
    if len(query) > MAX_QUERY_LENGTH:
        return jsonify({
            "success": False,
            "error": f"Query too long (max {MAX_QUERY_LENGTH} characters)"
        }), 400

    # Get and validate account_id — defense against cross-tenant enumeration.
    # Pre-fix: a JWT user could pass `?account_id=<other_tenant>` and the
    # handler trusted it verbatim, leaking subjects + 200-char body snippets
    # of any other tenant's emails. Now: empty → resolve from JWT;
    # supplied → validate ownership via `require_owned_account_id`
    # (mirrors `agent_marketplace.py:487` faq_stats / faq_history pattern).
    from app.api.routes_helpers import (
        _resolve_account_id_for_user,
        require_owned_account_id,
        _NO_ACCOUNT_SENTINEL,
    )
    account_id = None
    account_id_raw = request.args.get("account_id")
    if account_id_raw:
        try:
            parsed_account_id = int(account_id_raw)
        except (ValueError, TypeError):
            return jsonify({
                "success": False,
                "error": "Invalid account_id format"
            }), 400
        if parsed_account_id <= 0:
            return jsonify({
                "success": False,
                "error": "Invalid account_id format"
            }), 400
        owned = require_owned_account_id(account_id_raw)
        if owned == _NO_ACCOUNT_SENTINEL:
            return jsonify({
                "success": False,
                "error": "account not found"
            }), 404
        account_id = owned
    else:
        scoped = _resolve_account_id_for_user()
        if scoped and scoped != _NO_ACCOUNT_SENTINEL:
            account_id = scoped
    if account_id is None:
        try:
            from app.api.auth import is_trusted_loopback
            if not is_trusted_loopback():
                return jsonify({
                    "success": False,
                    "error": "account not found",
                }), 404
        except Exception:
            return jsonify({
                "success": False,
                "error": "account not found",
            }), 404

    # Get and validate limit
    try:
        limit = min(int(request.args.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
        if limit < 1:
            limit = DEFAULT_LIMIT
    except (ValueError, TypeError):
        limit = DEFAULT_LIMIT

    # Get and validate offset
    try:
        offset = max(int(request.args.get("offset", 0)), 0)
    except (ValueError, TypeError):
        offset = 0

    # Raw account_id string for provider routing — derived from the validated
    # int (NOT request.args directly), so an unowned X-Account-Id header
    # cannot reach the provider via the fallback path.
    from app.api import routes_helpers as _rh
    account_id_str = _rh._resolve_oauth_account_id_for_db_account(account_id)

    # Perform SQLite full-text search
    search_service = get_search_service()
    try:
        response = search_service.search_emails(
            query=query,
            account_id=account_id,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.warning(f"SQLite search failed for q='{query[:50]}': {e}, will try provider fallback")
        # Don't return early — create empty response so provider fallback can run
        response = SearchResponse(
            query=query,
            total=0,
            results=[],
            duration_ms=0,
            has_more=False,
        )

    # Provider fallback: search live mailbox for emails older than the local cache.
    # Triggered when: first page + query not empty + (few SQLite results OR old date filter).
    should_wait_for_provider = (
        query
        and offset == 0
        and (response.total == 0 or _has_old_date_filter(query))
    )
    if should_wait_for_provider:
        provider_results = _search_via_provider_with_timeout(query, account_id_str, limit, offset=offset)
        if provider_results:
            merged = _merge_results(response.results, provider_results, limit)
            response.results = merged
            response.total = len(merged)
            response.has_more = response.has_more or len(provider_results) >= limit
            logger.info(
                f"Provider fallback added {len(provider_results)} results "
                f"(total after merge: {response.total})"
            )

    # Log search for analytics
    if query:
        logger.info(
            f"Search: q='{query[:50]}' account={account_id} "
            f"results={response.total} duration={response.duration_ms:.1f}ms"
        )

    return jsonify({
        "success": True,
        **response.to_dict()
    }), 200


@search_alias_bp.route("/search", methods=["GET"])
def search_emails_legacy_alias() -> tuple:
    """Legacy alias for older monitors and clients.

    The canonical endpoint is `/api/emails/search`. Keeping `/api/search`
    as an alias avoids a false-negative health signal without duplicating
    search logic or creating a second contract.
    """
    return search_emails()


@search_bp.route("/search/suggestions", methods=["GET"])
def search_suggestions() -> tuple:
    """
    Get search suggestions based on partial query.

    Query Parameters:
        q: Partial search query (min 2 characters)
        account_id: Filter by account ID (optional)
        limit: Maximum suggestions (default 5, max 10)

    Returns:
        JSON with suggestions:
        {
            "success": true,
            "suggestions": ["meeting notes", "meeting agenda", ...]
        }
    """
    query = request.args.get("q", "").strip()

    if len(query) < 2:
        return jsonify({
            "success": True,
            "suggestions": []
        }), 200

    # Get account_id — same ownership validation as `/search` to prevent
    # tenant enumeration via the suggestions endpoint.
    #
    # Audit F-01 (2026-05-16): the prior implementation did
    # `try: int(raw) except: pass`, so a hex id from `/api/accounts`
    # raised ValueError → `pass` → account_id stayed None → SQL omitted
    # the account filter and returned sender/subject suggestions from
    # every tenant. The frontend uses hex exclusively, so this fired
    # per-keystroke on every multi-tenant install. Switch to
    # `require_owned_account_id` (canonical dual-format handler, see
    # routes_contacts autocomplete pattern and the autocomplete-handler
    # comment at routes_contacts.py:122-138).
    from app.api.routes_helpers import (
        _resolve_account_id_for_user,
        require_owned_account_id,
        _NO_ACCOUNT_SENTINEL,
    )
    account_id = None
    account_id_raw = request.args.get("account_id")
    if account_id_raw:
        owned = require_owned_account_id(account_id_raw)
        if owned == _NO_ACCOUNT_SENTINEL:
            return jsonify({
                "success": False,
                "error": "account not found"
            }), 404
        account_id = owned
    else:
        scoped = _resolve_account_id_for_user()
        if scoped and scoped != _NO_ACCOUNT_SENTINEL:
            account_id = scoped

    # Get limit (max 10 for suggestions)
    try:
        limit = min(int(request.args.get("limit", 5)), 10)
    except (ValueError, TypeError):
        limit = 5

    search_service = get_search_service()
    try:
        data = search_service.get_suggestions(query, account_id, limit)
    except Exception as e:
        logger.error(f"Suggestions failed for q='{query[:50]}': {e}")
        data = {"senders": [], "subjects": [], "labels": []}

    return jsonify({
        "success": True,
        **data,
    }), 200


@search_bp.route("/search/rebuild-index", methods=["POST"])
@require_admin
def rebuild_search_index() -> tuple:
    """
    Rebuild the FTS5 search index. **Admin only.**

    This is an admin endpoint that should be called if the index
    gets out of sync with the emails table.

    M-2 (audit security.md, issue #536): the docstring already said
    "admin endpoint" but the decorator was missing — any authenticated
    user could spam this CPU-bound rebuild over the full emails table
    and starve the SQLite write lock for everyone (DoS). Aligned with
    `/sync/trigger` (#535) and `/push/broadcast` (#523) — same
    `auth ≠ admin` lesson (cf. `tasks/lessons.md`).

    Returns:
        JSON indicating success or failure.
    """
    search_service = get_search_service()
    success = search_service.rebuild_index()

    if success:
        return jsonify({
            "success": True,
            "message": "Search index rebuilt successfully"
        }), 200
    else:
        return jsonify({
            "success": False,
            "error": "Failed to rebuild search index"
        }), 500


@search_bp.route("/search/optimize-index", methods=["POST"])
@require_admin
def optimize_search_index() -> tuple:
    """
    Optimize the FTS5 search index. **Admin only.**

    Merges index segments for better performance.
    Should be run periodically (e.g., weekly).

    M-2 (audit security.md, issue #536): same DoS surface as
    `rebuild_search_index` — segment merge runs CPU-bound under the
    write lock. Sibling op, sibling guard.

    Returns:
        JSON indicating success or failure.
    """
    search_service = get_search_service()
    success = search_service.optimize_index()

    if success:
        return jsonify({
            "success": True,
            "message": "Search index optimized successfully"
        }), 200
    else:
        return jsonify({
            "success": False,
            "error": "Failed to optimize search index"
        }), 500
