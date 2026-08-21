"""
Admin API Blueprint — Dashboard statistiques admin.

Endpoints:
  GET  /api/admin/users       — liste paginée des utilisateurs avec métriques
  GET  /api/admin/users/<email>/detail — détail d'un utilisateur (time-series)
  GET  /api/admin/aggregate   — cartes résumé (total users, MRR, coûts, marge)
  GET  /api/admin/export      — export CSV
"""

import csv
import io
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, request, jsonify, g, Response

from .auth import require_auth
from .utils.errors import error_response

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)

# Admin emails from env (comma-separated) + admin_users table
ADMIN_EMAILS = set(
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
)


def _is_admin(email: str) -> bool:
    """Vérifie si un email est admin (env var ou table admin_users)."""
    if email.lower() in ADMIN_EMAILS:
        return True
    try:
        from app.infrastructure.database import db
        row = db.fetchone(
            "SELECT email FROM admin_users WHERE email = ?",
            (email.lower(),)
        )
        return row is not None
    except Exception:
        return False


def require_admin(f):
    """Décorateur : exige un JWT valide + statut admin."""
    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        email = g.auth_user.get("email", "")
        if not _is_admin(email):
            return error_response("ADMIN_ACCESS_ONLY", "Reserved for administrators", 403)
        return f(*args, **kwargs)
    return decorated


def _expected_admin_token() -> str:
    """Token serveur pour l'app `agentys-admin/`.

    `AGENTYS_ADMIN_TOKEN` est le nom canonique (#551). `ADMIN_DASHBOARD_TOKEN`
    reste accepté pour faciliter une rotation progressive des environnements.
    """
    return (
        os.environ.get("AGENTYS_ADMIN_TOKEN", "").strip()
        or os.environ.get("ADMIN_DASHBOARD_TOKEN", "").strip()
    )


def require_admin_token(f):
    """Décorateur : exige `X-Admin-Token` pour les endpoints ops privés."""
    @wraps(f)
    def decorated(*args, **kwargs):
        expected = _expected_admin_token()
        if not expected:
            return jsonify({"error": "Admin token not configured"}), 503
        provided = request.headers.get("X-Admin-Token", "").strip()
        if not provided or not secrets.compare_digest(provided, expected):
            return error_response("ADMIN_ACCESS_ONLY", "Reserved for administrators", 403)
        return f(*args, **kwargs)
    return decorated


def require_admin_or_token(f):
    """Accept either the admin JWT session or the server-to-server admin token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        expected = _expected_admin_token()
        provided = request.headers.get("X-Admin-Token", "").strip()
        if expected and provided and secrets.compare_digest(provided, expected):
            return f(*args, **kwargs)
        return require_admin(f)(*args, **kwargs)
    return decorated


def _table_exists(table_name: str) -> bool:
    from app.infrastructure.database import db

    row = db.fetchone(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    return row is not None


def _table_has_column(table_name: str, column_name: str) -> bool:
    try:
        from app.infrastructure.database import db

        rows = db.fetchall(f"PRAGMA table_info({table_name})")
        return any(row["name"] == column_name for row in rows)
    except Exception:
        return False


_DB_BROWSER_MAX_LIMIT = 100

_DB_BROWSER_TABLES = {
    "accounts": {
        "label": "Comptes",
        "columns": [
            "id", "email", "provider", "display_name", "user_id", "is_active",
            "last_sync_at", "token_expires_at", "gmail_watch_expiration",
            "created_at", "updated_at",
        ],
        "search": ["email", "provider", "display_name"],
        "order": ("id", "DESC"),
    },
    "emails": {
        "label": "Emails",
        "columns": [
            "id", "email_id", "thread_id", "account_id", "subject", "sender",
            "sender_name", "date", "snippet", "is_read", "is_starred",
            "is_draft", "is_sent", "labels", "folder", "deadline_at",
            "created_at", "updated_at",
        ],
        "search": ["email_id", "thread_id", "subject", "sender", "sender_name", "snippet", "folder"],
        "order": ("date", "DESC"),
    },
    "contacts": {
        "label": "Contacts",
        "columns": [
            "id", "account_id", "email", "name", "company", "title",
            "email_count", "sent_count", "received_count", "last_contacted_at",
            "relationship_strength", "detected_tone", "created_at", "updated_at",
        ],
        "search": ["email", "name", "company", "title"],
        "order": ("last_contacted_at", "DESC"),
    },
    "drafts": {
        "label": "Drafts",
        "columns": [
            "id", "account_id", "original_email_id", "subject", "recipients",
            "status", "agent_model", "iteration_count", "tokens_used",
            "feedback_rating", "sent_at", "sent_email_id", "created_at", "updated_at",
        ],
        "search": ["subject", "recipients", "status", "agent_model", "sent_email_id"],
        "order": ("updated_at", "DESC"),
    },
    "draft_history": {
        "label": "Historique drafts",
        "columns": [
            "id", "account_id", "email_id", "email_sender", "email_subject",
            "status", "draft_id", "tokens_used", "model", "processing_time_ms",
            "priority_score", "category", "created_at", "feedback_score",
        ],
        "search": ["email_id", "email_sender", "email_subject", "status", "draft_id", "model", "category"],
        "order": ("created_at", "DESC"),
    },
    "pending_actions": {
        "label": "Actions en attente",
        "columns": [
            "id", "account_id", "action_type", "email_id", "status",
            "retry_count", "processed_at", "created_at", "updated_at",
        ],
        "search": ["action_type", "email_id", "status"],
        "order": ("created_at", "DESC"),
    },
    "email_labels": {
        "label": "Labels emails",
        "columns": ["id", "email_id", "account_id", "label_name"],
        "search": ["email_id", "label_name"],
        "order": ("id", "DESC"),
    },
    "onboarding_results": {
        "label": "Onboarding",
        "columns": [
            "id", "account_id", "status", "emails_analysed", "error_message",
            "started_at", "completed_at", "created_at", "updated_at",
        ],
        "search": ["status", "error_message"],
        "order": ("created_at", "DESC"),
    },
    "knowledge_entries": {
        "label": "Knowledge",
        "columns": ["id", "account_id", "title", "category", "source", "created_at", "updated_at"],
        "search": ["id", "title", "category", "source"],
        "order": ("updated_at", "DESC"),
    },
    "token_usage_log": {
        "label": "Usage tokens",
        "columns": [
            "id", "account_id", "user_id", "agent", "agent_name", "feature",
            "model", "input_tokens", "output_tokens", "cache_creation_input_tokens",
            "cache_read_input_tokens", "cost_usd", "created_at",
        ],
        "search": ["agent", "agent_name", "feature", "model"],
        "order": ("created_at", "DESC"),
    },
    "api_usage_log": {
        "label": "Usage API",
        "columns": [
            "id", "account_id", "user_id", "feature", "provider", "method",
            "url_host", "url_path", "status_code", "success", "duration_ms",
            "auth_present", "auth_type", "process_name", "created_at",
        ],
        "search": ["feature", "provider", "method", "url_host", "url_path", "auth_type", "process_name"],
        "order": ("created_at", "DESC"),
    },
    "audit_log": {
        "label": "Audit app",
        "columns": [
            "id", "timestamp", "event_type", "success", "email_id", "draft_id",
            "user", "duration_ms", "error",
        ],
        "search": ["event_type", "email_id", "draft_id", "user", "error"],
        "order": ("timestamp", "DESC"),
    },
    "admin_audit_log": {
        "label": "Audit admin",
        "columns": ["id", "actor", "action", "ip_address", "created_at"],
        "search": ["actor", "action", "ip_address"],
        "order": ("created_at", "DESC"),
    },
    "user_activity": {
        "label": "Activité utilisateurs",
        "columns": ["id", "user_email", "action", "created_at"],
        "search": ["user_email", "action"],
        "order": ("created_at", "DESC"),
    },
    "revenue_events": {
        "label": "Revenus",
        "columns": ["id", "user_email", "event_type", "amount_usd", "plan", "created_at"],
        "search": ["user_email", "event_type", "plan"],
        "order": ("created_at", "DESC"),
    },
    "referrals": {
        "label": "Parrainages",
        "columns": ["id", "referrer_email", "referred_email", "status", "created_at"],
        "search": ["referrer_email", "referred_email", "status"],
        "order": ("created_at", "DESC"),
    },
    "extracted_tasks": {
        "label": "Tâches extraites",
        "columns": ["id", "account_id", "email_id", "title", "priority", "deadline", "status", "created_at", "completed_at"],
        "search": ["email_id", "title", "priority", "deadline", "status"],
        "order": ("created_at", "DESC"),
    },
}


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _db_browser_columns(table_name: str) -> list[str]:
    if table_name not in _DB_BROWSER_TABLES or not _table_exists(table_name):
        return []
    from app.infrastructure.database import db

    existing = {
        row["name"]
        for row in db.fetchall(f"PRAGMA table_info({_quote_identifier(table_name)})")
    }
    return [column for column in _DB_BROWSER_TABLES[table_name]["columns"] if column in existing]


def _db_browser_search_columns(table_name: str) -> list[str]:
    visible = set(_db_browser_columns(table_name))
    return [column for column in _DB_BROWSER_TABLES[table_name].get("search", []) if column in visible]


def _db_browser_limit() -> int:
    limit = request.args.get("limit", 50, type=int) or 50
    return max(1, min(limit, _DB_BROWSER_MAX_LIMIT))


def _db_browser_offset() -> int:
    return max(0, request.args.get("offset", 0, type=int) or 0)


def _db_browser_where(table_name: str, query: str) -> tuple[str, tuple]:
    query = query.strip().lower()
    if not query:
        return "", ()
    clauses = [
        f"LOWER(CAST({_quote_identifier(column)} AS TEXT)) LIKE ?"
        for column in _db_browser_search_columns(table_name)
    ]
    if not clauses:
        return "", ()
    return " WHERE " + " OR ".join(clauses), tuple(f"%{query}%" for _ in clauses)


def _db_browser_order(table_name: str, columns: list[str]) -> str:
    order_column, direction = _DB_BROWSER_TABLES[table_name]["order"]
    if order_column not in columns:
        order_column = "id" if "id" in columns else columns[0]
    direction = "DESC" if str(direction).upper() == "DESC" else "ASC"
    return f" ORDER BY {_quote_identifier(order_column)} {direction}"


def _db_browser_cell(value):
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    text = str(value)
    return text if len(text) <= 240 else text[:237] + "..."


@admin_bp.route("/db/tables", methods=["GET"])
@require_admin_token
def db_tables():
    """Expose le catalogue read-only des tables consultables dans l'admin."""
    from app.infrastructure.database import db

    _log_admin_access("db_tables")
    tables = []
    for table_name, config in _DB_BROWSER_TABLES.items():
        columns = _db_browser_columns(table_name)
        if not columns:
            continue
        try:
            row = db.fetchone(f"SELECT COUNT(*) AS count FROM {_quote_identifier(table_name)}")
            row_count = int(row["count"] or 0) if row else 0
        except Exception:
            row_count = 0
        tables.append({
            "name": table_name,
            "label": config["label"],
            "row_count": row_count,
            "columns": columns,
            "search_columns": _db_browser_search_columns(table_name),
        })
    return jsonify({"tables": tables})


@admin_bp.route("/db/rows", methods=["GET"])
@require_admin_token
def db_rows():
    """Retourne des lignes paginées d'une table whitelisted, en lecture seule."""
    from app.infrastructure.database import db

    table_name = request.args.get("table", "", type=str)
    if table_name not in _DB_BROWSER_TABLES or not _table_exists(table_name):
        return error_response("ADMIN_DB_TABLE_NOT_ALLOWED", "Table is not available in admin DB browser", 404)

    columns = _db_browser_columns(table_name)
    if not columns:
        return error_response("ADMIN_DB_TABLE_EMPTY_SCHEMA", "No safe columns available for this table", 404)

    limit = _db_browser_limit()
    offset = _db_browser_offset()
    query = request.args.get("q", "", type=str) or ""
    where_sql, where_params = _db_browser_where(table_name, query)
    select_sql = ", ".join(_quote_identifier(column) for column in columns)
    table_sql = _quote_identifier(table_name)
    order_sql = _db_browser_order(table_name, columns)

    count_row = db.fetchone(f"SELECT COUNT(*) AS count FROM {table_sql}{where_sql}", where_params)
    total = int(count_row["count"] or 0) if count_row else 0
    rows = db.fetchall(
        f"SELECT {select_sql} FROM {table_sql}{where_sql}{order_sql} LIMIT ? OFFSET ?",
        (*where_params, limit, offset),
    )

    _log_admin_access("db_rows", {"table": table_name, "limit": limit, "offset": offset, "q": bool(query.strip())})

    return jsonify({
        "table": table_name,
        "label": _DB_BROWSER_TABLES[table_name]["label"],
        "columns": columns,
        "rows": [
            {column: _db_browser_cell(row[column]) for column in columns}
            for row in rows
        ],
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_more": offset + limit < total,
        "q": query,
    })


def _safe_days() -> int:
    days = request.args.get("days", 7, type=int)
    return max(1, min(days or 7, 90))


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return int(ordered[index])


def _admin_actor() -> str:
    return request.headers.get("X-Admin-Actor", "").strip() or "agentys-admin"


def _log_admin_access(action: str, metadata: dict | None = None) -> None:
    """Audit non-bloquant de chaque accès admin."""
    try:
        from app.infrastructure.database import db

        db.execute(
            """
            INSERT INTO admin_audit_log (actor, action, metadata, ip_address, user_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                _admin_actor(),
                action,
                json.dumps(metadata or {}, ensure_ascii=False),
                request.remote_addr,
                request.headers.get("User-Agent", "")[:300],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.commit()
    except Exception as exc:
        logger.debug("[ADMIN] audit log skipped: %s", exc)


def _empty_overview(days: int) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "summary": {
            "spend_usd": 0.0,
            "spend_change_pct": 0.0,
            "total_tokens": 0,
            "request_count": 0,
            "avg_cost_per_request": 0.0,
            "avg_cost_per_draft": 0.0,
            "cache_hit_rate": 0.0,
            "draft_count": 0,
            "draft_latency_p50_ms": 0,
            "draft_latency_p95_ms": 0,
            "quality_score_avg": None,
        },
        "series": [],
        "tokens": {"by_model": [], "top_accounts": [], "top_features": []},
        "api_usage": {
            "total_calls": 0,
            "success_rate": 0.0,
            "p95_duration_ms": 0,
            "by_provider": [],
            "top_accounts": [],
            "top_users": [],
            "top_features": [],
        },
        "product": {"draft_status": [], "drafts_table_status": []},
        "infra": {"cron_runs": [], "sentinel_alerts": [], "deployments": []},
        "security": {"admin_audit": [], "unusual_logins": [], "provider_quotas": []},
    }


def _known_users_file_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data",
        "known_users.json",
    )


def _known_user_email_by_id() -> dict[int, str]:
    """Map JWT user IDs back to emails when the known-users registry exists."""
    users_file = _known_users_file_path()
    if not os.path.exists(users_file):
        return {}
    try:
        with open(users_file, "r", encoding="utf-8") as f:
            users = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

    from .auth import user_id_from_email

    email_by_id: dict[int, str] = {}
    for user in users:
        email = (user.get("email") or "").strip().lower()
        if email:
            email_by_id[user_id_from_email(email)] = email
    return email_by_id


def _split_group_concat(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _canonical_token_rollup(days: int, now: datetime) -> dict | None:
    """Read LLM token usage from the canonical SQLAlchemy/Postgres store.

    `ops_overview` still uses the legacy DB helper for product/API metrics, but
    token writes now go through `app.db.database` in prod. Returning `None`
    keeps local SQLite tests on the legacy path.
    """
    try:
        from sqlalchemy import text
        from app.db.database import get_db_session
    except Exception:
        return None

    start_dt = now.astimezone(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    prev_start_dt = start_dt - timedelta(days=days)
    known_user_email_by_id = _known_user_email_by_id()

    try:
        with get_db_session() as session:
            bind = session.get_bind()
            if bind.dialect.name != "postgresql":
                return None

            current = session.execute(
                text(
                    """
                    SELECT
                        COALESCE(SUM(cost_usd), 0) AS spend_usd,
                        COALESCE(SUM(input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens), 0) AS total_tokens,
                        COALESCE(SUM(input_tokens), 0) AS input_tokens,
                        COALESCE(SUM(output_tokens), 0) AS output_tokens,
                        COALESCE(SUM(cache_creation_input_tokens), 0) AS cache_creation_input_tokens,
                        COALESCE(SUM(cache_read_input_tokens), 0) AS cache_read_input_tokens,
                        COUNT(*) AS request_count
                    FROM token_usage_log
                    WHERE created_at >= :start_dt
                    """
                ),
                {"start_dt": start_dt},
            ).mappings().first()
            previous = session.execute(
                text(
                    """
                    SELECT COALESCE(SUM(cost_usd), 0) AS spend_usd
                    FROM token_usage_log
                    WHERE created_at >= :prev_start_dt AND created_at < :start_dt
                    """
                ),
                {"prev_start_dt": prev_start_dt, "start_dt": start_dt},
            ).mappings().first()

            daily_rows = session.execute(
                text(
                    """
                    SELECT CAST(created_at AS date) AS day,
                           COALESCE(SUM(cost_usd), 0) AS spend_usd,
                           COALESCE(SUM(input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens), 0) AS tokens,
                           COUNT(*) AS request_count
                    FROM token_usage_log
                    WHERE created_at >= :start_dt
                    GROUP BY CAST(created_at AS date)
                    ORDER BY day
                    """
                ),
                {"start_dt": start_dt},
            ).mappings().all()
            daily_by_day = {str(row["day"]): row for row in daily_rows}
            series = []
            for offset in range(days - 1, -1, -1):
                day = (now - timedelta(days=offset)).date().isoformat()
                row = daily_by_day.get(day)
                series.append({
                    "date": day,
                    "spend_usd": round(float(row["spend_usd"] or 0), 4) if row else 0.0,
                    "tokens": int(row["tokens"] or 0) if row else 0,
                    "request_count": int(row["request_count"] or 0) if row else 0,
                    "drafts": 0,
                })

            by_model = [
                {
                    "model": row["model"],
                    "spend_usd": round(float(row["spend_usd"] or 0), 4),
                    "tokens": int(row["tokens"] or 0),
                    "request_count": int(row["request_count"] or 0),
                }
                for row in session.execute(
                    text(
                        """
                        SELECT model,
                               COALESCE(SUM(cost_usd), 0) AS spend_usd,
                               COALESCE(SUM(input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens), 0) AS tokens,
                               COUNT(*) AS request_count
                        FROM token_usage_log
                        WHERE created_at >= :start_dt
                        GROUP BY model
                        ORDER BY spend_usd DESC
                        """
                    ),
                    {"start_dt": start_dt},
                ).mappings().all()
            ]

            top_features = [
                {
                    "feature": row["feature"] or "unknown",
                    "spend_usd": round(float(row["spend_usd"] or 0), 4),
                    "tokens": int(row["tokens"] or 0),
                    "request_count": int(row["request_count"] or 0),
                }
                for row in session.execute(
                    text(
                        """
                        SELECT COALESCE(feature, 'unknown') AS feature,
                               COALESCE(SUM(cost_usd), 0) AS spend_usd,
                               COALESCE(SUM(input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens), 0) AS tokens,
                               COUNT(*) AS request_count
                        FROM token_usage_log
                        WHERE created_at >= :start_dt
                        GROUP BY COALESCE(feature, 'unknown')
                        ORDER BY spend_usd DESC
                        LIMIT 10
                        """
                    ),
                    {"start_dt": start_dt},
                ).mappings().all()
            ]

            top_accounts = [
                {
                    "account_id": row["account_id"],
                    "account_label": row["account_label"],
                    "spend_usd": round(float(row["spend_usd"] or 0), 4),
                    "tokens": int(row["tokens"] or 0),
                    "request_count": int(row["request_count"] or 0),
                }
                for row in session.execute(
                    text(
                        """
                        SELECT l.account_id,
                               COALESCE(a.email, 'account #' || CAST(l.account_id AS text), 'unknown') AS account_label,
                               COALESCE(SUM(l.cost_usd), 0) AS spend_usd,
                               COALESCE(SUM(l.input_tokens + l.output_tokens + l.cache_creation_input_tokens + l.cache_read_input_tokens), 0) AS tokens,
                               COUNT(*) AS request_count
                        FROM token_usage_log l
                        LEFT JOIN accounts a ON a.id = l.account_id
                        WHERE l.created_at >= :start_dt
                        GROUP BY l.account_id, a.email
                        ORDER BY spend_usd DESC
                        LIMIT 10
                        """
                    ),
                    {"start_dt": start_dt},
                ).mappings().all()
            ]

            token_users = []
            for row in session.execute(
                text(
                    """
                    SELECT COALESCE(l.user_id, a.user_id) AS user_id,
                           COALESCE(CAST(COALESCE(l.user_id, a.user_id) AS text), 'account:' || CAST(l.account_id AS text), 'background') AS user_key,
                           STRING_AGG(DISTINCT NULLIF(a.email, ''), ',') AS account_emails,
                           COUNT(DISTINCT l.account_id) AS account_count,
                           COALESCE(SUM(l.cost_usd), 0) AS spend_usd,
                           COALESCE(SUM(l.input_tokens), 0) AS input_tokens,
                           COALESCE(SUM(l.output_tokens), 0) AS output_tokens,
                           COALESCE(SUM(l.cache_creation_input_tokens), 0) AS cache_creation_input_tokens,
                           COALESCE(SUM(l.cache_read_input_tokens), 0) AS cache_read_input_tokens,
                           COALESCE(SUM(l.input_tokens + l.output_tokens + l.cache_creation_input_tokens + l.cache_read_input_tokens), 0) AS tokens,
                           COUNT(*) AS request_count
                    FROM token_usage_log l
                    LEFT JOIN accounts a ON a.id = l.account_id
                    WHERE l.created_at >= :start_dt
                      AND lower(COALESCE(l.model, '')) LIKE 'claude%%'
                    GROUP BY user_key, COALESCE(l.user_id, a.user_id)
                    ORDER BY tokens DESC, spend_usd DESC
                    """
                ),
                {"start_dt": start_dt},
            ).mappings().all():
                user_id = row["user_id"]
                user_key = row["user_key"] or "background"
                account_emails = _split_group_concat(row["account_emails"])
                user_email = known_user_email_by_id.get(int(user_id)) if user_id is not None else None
                user_email = user_email or (account_emails[0] if account_emails else None)
                user_label = user_email
                if not user_label:
                    if user_id is not None:
                        user_label = f"user #{user_id}"
                    elif str(user_key).startswith("account:"):
                        user_label = "account #" + str(user_key).split(":", 1)[1]
                    else:
                        user_label = "background"

                token_users.append({
                    "user_key": user_key,
                    "user_id": user_id,
                    "user_email": user_email,
                    "user_label": user_label,
                    "account_count": int(row["account_count"] or 0),
                    "account_labels": account_emails,
                    "spend_usd": round(float(row["spend_usd"] or 0), 4),
                    "tokens": int(row["tokens"] or 0),
                    "input_tokens": int(row["input_tokens"] or 0),
                    "output_tokens": int(row["output_tokens"] or 0),
                    "cache_creation_input_tokens": int(row["cache_creation_input_tokens"] or 0),
                    "cache_read_input_tokens": int(row["cache_read_input_tokens"] or 0),
                    "request_count": int(row["request_count"] or 0),
                })

        input_tokens = int(current["input_tokens"] or 0) if current else 0
        cache_creation = int(current["cache_creation_input_tokens"] or 0) if current else 0
        cache_read = int(current["cache_read_input_tokens"] or 0) if current else 0
        cache_denominator = input_tokens + cache_creation + cache_read
        return {
            "current": dict(current or {}),
            "spend": float(current["spend_usd"] or 0) if current else 0.0,
            "prev_spend": float(previous["spend_usd"] or 0) if previous else 0.0,
            "request_count": int(current["request_count"] or 0) if current else 0,
            "cache_hit_rate": (cache_read / cache_denominator) if cache_denominator else 0.0,
            "series": series,
            "by_model": by_model,
            "top_features": top_features,
            "top_accounts": top_accounts,
            "token_users": token_users,
        }
    except Exception as exc:
        logger.debug("[admin/ops_overview] canonical token rollup unavailable: %s", exc)
        return None


@admin_bp.route("/ops/overview", methods=["GET"])
@require_admin_token
def ops_overview():
    """Dashboard ops privé pour `agentys-admin/`.

    Retourne uniquement métriques et agrégats : aucun contenu email, contact ou
    draft n'est exposé.
    """
    from app.infrastructure.database import db

    days = _safe_days()
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=days)
    prev_start_dt = start_dt - timedelta(days=days)
    start_iso = start_dt.isoformat()
    prev_start_iso = prev_start_dt.isoformat()

    _log_admin_access("ops_overview", {"days": days})

    canonical_tokens = _canonical_token_rollup(days, now)

    if not _table_exists("token_usage_log") and canonical_tokens is None:
        return jsonify(_empty_overview(days))

    current = db.fetchone(
        """
        SELECT
            COALESCE(SUM(cost_usd), 0) AS spend_usd,
            COALESCE(SUM(input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens), 0) AS total_tokens,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cache_creation_input_tokens), 0) AS cache_creation_input_tokens,
            COALESCE(SUM(cache_read_input_tokens), 0) AS cache_read_input_tokens,
            COUNT(*) AS request_count
        FROM token_usage_log
        WHERE created_at >= ?
        """,
        (start_iso,),
    )
    previous = db.fetchone(
        """
        SELECT COALESCE(SUM(cost_usd), 0) AS spend_usd
        FROM token_usage_log
        WHERE created_at >= ? AND created_at < ?
        """,
        (prev_start_iso, start_iso),
    )

    spend = float(current["spend_usd"] or 0) if current else 0.0
    prev_spend = float(previous["spend_usd"] or 0) if previous else 0.0
    request_count = int(current["request_count"] or 0) if current else 0
    cache_denominator = (
        int(current["input_tokens"] or 0)
        + int(current["cache_creation_input_tokens"] or 0)
        + int(current["cache_read_input_tokens"] or 0)
        if current else 0
    )
    cache_hit_rate = (
        (int(current["cache_read_input_tokens"] or 0) / cache_denominator)
        if cache_denominator else 0.0
    )

    daily_rows = db.fetchall(
        """
        SELECT date(created_at) AS day,
               COALESCE(SUM(cost_usd), 0) AS spend_usd,
               COALESCE(SUM(input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens), 0) AS tokens,
               COUNT(*) AS request_count
        FROM token_usage_log
        WHERE created_at >= ?
        GROUP BY date(created_at)
        ORDER BY day
        """,
        (start_iso,),
    )
    daily_by_day = {row["day"]: row for row in daily_rows}
    series = []
    for offset in range(days - 1, -1, -1):
        day = (now - timedelta(days=offset)).date().isoformat()
        row = daily_by_day.get(day)
        series.append({
            "date": day,
            "spend_usd": round(float(row["spend_usd"] or 0), 4) if row else 0.0,
            "tokens": int(row["tokens"] or 0) if row else 0,
            "request_count": int(row["request_count"] or 0) if row else 0,
            "drafts": 0,
        })

    by_model = [
        {
            "model": row["model"],
            "spend_usd": round(float(row["spend_usd"] or 0), 4),
            "tokens": int(row["tokens"] or 0),
            "request_count": int(row["request_count"] or 0),
        }
        for row in db.fetchall(
            """
            SELECT model,
                   COALESCE(SUM(cost_usd), 0) AS spend_usd,
                   COALESCE(SUM(input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens), 0) AS tokens,
                   COUNT(*) AS request_count
            FROM token_usage_log
            WHERE created_at >= ?
            GROUP BY model
            ORDER BY spend_usd DESC
            """,
            (start_iso,),
        )
    ]

    top_features = [
        {
            "feature": row["feature"] or "unknown",
            "spend_usd": round(float(row["spend_usd"] or 0), 4),
            "tokens": int(row["tokens"] or 0),
            "request_count": int(row["request_count"] or 0),
        }
        for row in db.fetchall(
            """
            SELECT COALESCE(feature, 'unknown') AS feature,
                   COALESCE(SUM(cost_usd), 0) AS spend_usd,
                   COALESCE(SUM(input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens), 0) AS tokens,
                   COUNT(*) AS request_count
            FROM token_usage_log
            WHERE created_at >= ?
            GROUP BY COALESCE(feature, 'unknown')
            ORDER BY spend_usd DESC
            LIMIT 10
            """,
            (start_iso,),
        )
    ]

    accounts_table_exists = _table_exists("accounts")
    if accounts_table_exists:
        account_sql = """
            SELECT l.account_id,
                   COALESCE(a.email, 'account #' || l.account_id, 'unknown') AS account_label,
                   COALESCE(SUM(l.cost_usd), 0) AS spend_usd,
                   COALESCE(SUM(l.input_tokens + l.output_tokens + l.cache_creation_input_tokens + l.cache_read_input_tokens), 0) AS tokens,
                   COUNT(*) AS request_count
            FROM token_usage_log l
            LEFT JOIN accounts a ON a.id = l.account_id
            WHERE l.created_at >= ?
            GROUP BY l.account_id, a.email
            ORDER BY spend_usd DESC
            LIMIT 10
        """
    else:
        account_sql = """
            SELECT account_id,
                   COALESCE('account #' || account_id, 'unknown') AS account_label,
                   COALESCE(SUM(cost_usd), 0) AS spend_usd,
                   COALESCE(SUM(input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens), 0) AS tokens,
                   COUNT(*) AS request_count
            FROM token_usage_log
            WHERE created_at >= ?
            GROUP BY account_id
            ORDER BY spend_usd DESC
            LIMIT 10
        """
    top_accounts = [
        {
            "account_id": row["account_id"],
            "account_label": row["account_label"],
            "spend_usd": round(float(row["spend_usd"] or 0), 4),
            "tokens": int(row["tokens"] or 0),
            "request_count": int(row["request_count"] or 0),
        }
        for row in db.fetchall(account_sql, (start_iso,))
    ]

    token_has_user_id = _table_has_column("token_usage_log", "user_id")
    accounts_has_user_id = accounts_table_exists and _table_has_column("accounts", "user_id")
    if token_has_user_id and accounts_has_user_id:
        token_user_expr = "COALESCE(l.user_id, a.user_id)"
    elif token_has_user_id:
        token_user_expr = "l.user_id"
    elif accounts_has_user_id:
        token_user_expr = "a.user_id"
    else:
        token_user_expr = "NULL"
    token_user_key_expr = (
        f"COALESCE(CAST({token_user_expr} AS TEXT), 'account:' || l.account_id, 'background')"
    )
    token_from_sql = "token_usage_log l"
    account_emails_select = "NULL AS account_emails"
    if accounts_table_exists:
        token_from_sql = "token_usage_log l LEFT JOIN accounts a ON a.id = l.account_id"
        account_emails_select = "GROUP_CONCAT(DISTINCT NULLIF(a.email, '')) AS account_emails"

    token_user_sql = f"""
        SELECT {token_user_expr} AS user_id,
               {token_user_key_expr} AS user_key,
               {account_emails_select},
               COUNT(DISTINCT l.account_id) AS account_count,
               COALESCE(SUM(l.cost_usd), 0) AS spend_usd,
               COALESCE(SUM(l.input_tokens), 0) AS input_tokens,
               COALESCE(SUM(l.output_tokens), 0) AS output_tokens,
               COALESCE(SUM(l.cache_creation_input_tokens), 0) AS cache_creation_input_tokens,
               COALESCE(SUM(l.cache_read_input_tokens), 0) AS cache_read_input_tokens,
               COALESCE(
                   SUM(
                       l.input_tokens
                       + l.output_tokens
                       + l.cache_creation_input_tokens
                       + l.cache_read_input_tokens
                   ),
                   0
               ) AS tokens,
               COUNT(*) AS request_count
        FROM {token_from_sql}
        WHERE l.created_at >= ?
          AND lower(COALESCE(l.model, '')) LIKE 'claude%'
        GROUP BY {token_user_key_expr}
        ORDER BY tokens DESC, spend_usd DESC
    """
    known_user_email_by_id = _known_user_email_by_id()
    token_users = []
    for row in db.fetchall(token_user_sql, (start_iso,)):
        user_id = row["user_id"]
        user_key = row["user_key"] or "background"
        account_emails = _split_group_concat(row["account_emails"])
        user_email = known_user_email_by_id.get(int(user_id)) if user_id is not None else None
        user_email = user_email or (account_emails[0] if account_emails else None)
        user_label = user_email
        if not user_label:
            if user_id is not None:
                user_label = f"user #{user_id}"
            elif str(user_key).startswith("account:"):
                user_label = "account #" + str(user_key).split(":", 1)[1]
            else:
                user_label = "background"

        token_users.append({
            "user_key": user_key,
            "user_id": user_id,
            "user_email": user_email,
            "user_label": user_label,
            "account_count": int(row["account_count"] or 0),
            "account_labels": account_emails,
            "spend_usd": round(float(row["spend_usd"] or 0), 4),
            "tokens": int(row["tokens"] or 0),
            "input_tokens": int(row["input_tokens"] or 0),
            "output_tokens": int(row["output_tokens"] or 0),
            "cache_creation_input_tokens": int(row["cache_creation_input_tokens"] or 0),
            "cache_read_input_tokens": int(row["cache_read_input_tokens"] or 0),
            "request_count": int(row["request_count"] or 0),
        })

    api_usage = {
        "total_calls": 0,
        "success_rate": 0.0,
        "p95_duration_ms": 0,
        "by_provider": [],
        "top_accounts": [],
        "top_users": [],
        "top_features": [],
    }
    if _table_exists("api_usage_log"):
        api_current = db.fetchone(
            """
            SELECT COUNT(*) AS total_calls,
                   COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success_count
            FROM api_usage_log
            WHERE created_at >= ?
            """,
            (start_iso,),
        )
        api_total = int(api_current["total_calls"] or 0) if api_current else 0
        api_success = int(api_current["success_count"] or 0) if api_current else 0
        duration_rows = db.fetchall(
            """
            SELECT duration_ms
            FROM api_usage_log
            WHERE created_at >= ? AND duration_ms IS NOT NULL AND duration_ms >= 0
            """,
            (start_iso,),
        )
        api_usage["total_calls"] = api_total
        api_usage["success_rate"] = round(api_success / api_total, 4) if api_total else 0.0
        api_usage["p95_duration_ms"] = _percentile([int(row["duration_ms"]) for row in duration_rows], 0.95)
        api_usage["by_provider"] = [
            {
                "provider": row["provider"] or "unknown",
                "calls": int(row["calls"] or 0),
                "success_rate": round(float(row["success_count"] or 0) / int(row["calls"] or 1), 4),
                "avg_duration_ms": int(row["avg_duration_ms"] or 0),
            }
            for row in db.fetchall(
                """
                SELECT COALESCE(provider, 'unknown') AS provider,
                       COUNT(*) AS calls,
                       COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                       COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
                FROM api_usage_log
                WHERE created_at >= ?
                GROUP BY COALESCE(provider, 'unknown')
                ORDER BY calls DESC
                LIMIT 12
                """,
                (start_iso,),
            )
        ]
        if _table_exists("accounts"):
            api_account_sql = """
                SELECT l.account_id,
                       COALESCE(a.email, 'account #' || l.account_id, 'unknown') AS account_label,
                       COUNT(*) AS calls,
                       COALESCE(SUM(CASE WHEN l.success = 1 THEN 1 ELSE 0 END), 0) AS success_count
                FROM api_usage_log l
                LEFT JOIN accounts a ON a.id = l.account_id
                WHERE l.created_at >= ?
                GROUP BY l.account_id, a.email
                ORDER BY calls DESC
                LIMIT 10
            """
        else:
            api_account_sql = """
                SELECT account_id,
                       COALESCE('account #' || account_id, 'unknown') AS account_label,
                       COUNT(*) AS calls,
                       COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success_count
                FROM api_usage_log
                WHERE created_at >= ?
                GROUP BY account_id
                ORDER BY calls DESC
                LIMIT 10
            """
        api_usage["top_accounts"] = [
            {
                "account_id": row["account_id"],
                "account_label": row["account_label"],
                "calls": int(row["calls"] or 0),
                "success_rate": round(float(row["success_count"] or 0) / int(row["calls"] or 1), 4),
            }
            for row in db.fetchall(api_account_sql, (start_iso,))
        ]
        accounts_table_exists = _table_exists("accounts")
        accounts_has_user_id = accounts_table_exists and _table_has_column("accounts", "user_id")
        resolved_user_expr = "COALESCE(l.user_id, a.user_id)" if accounts_has_user_id else "l.user_id"
        user_key_expr = (
            f"COALESCE(CAST({resolved_user_expr} AS TEXT), 'account:' || l.account_id, 'background')"
        )
        detail_from_sql = "api_usage_log l"
        account_email_select = "NULL AS account_emails"
        if accounts_table_exists:
            detail_from_sql = "api_usage_log l LEFT JOIN accounts a ON a.id = l.account_id"
            account_email_select = "GROUP_CONCAT(DISTINCT NULLIF(a.email, '')) AS account_emails"

        api_user_sql = f"""
            SELECT {resolved_user_expr} AS user_id,
                   {user_key_expr} AS user_key,
                   {account_email_select},
                   COUNT(DISTINCT l.account_id) AS account_count,
                   COUNT(*) AS calls,
                   COALESCE(SUM(CASE WHEN l.success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                   COALESCE(AVG(l.duration_ms), 0) AS avg_duration_ms
            FROM {detail_from_sql}
            WHERE l.created_at >= ?
            GROUP BY {user_key_expr}
            ORDER BY calls DESC
            LIMIT 10
        """

        account_emails_by_user_id: dict[int, list[str]] = {}
        account_ids_by_user_id: dict[int, list[int]] = {}
        if accounts_has_user_id:
            for row in db.fetchall(
                """
                SELECT user_id,
                       GROUP_CONCAT(DISTINCT id) AS account_ids,
                       GROUP_CONCAT(DISTINCT NULLIF(email, '')) AS emails
                FROM accounts
                WHERE user_id IS NOT NULL
                GROUP BY user_id
                """
            ):
                resolved_user_id = int(row["user_id"])
                account_emails_by_user_id[resolved_user_id] = _split_group_concat(row["emails"])
                account_ids_by_user_id[resolved_user_id] = [
                    int(account_id) for account_id in _split_group_concat(row["account_ids"])
                ]

        def _api_usage_detail_filter(row_user_id, row_user_key: str) -> tuple[str, tuple]:
            clauses = ["l.created_at >= ?"]
            params: list = [start_iso]
            if row_user_id is not None:
                resolved_user_id = int(row_user_id)
                account_ids = account_ids_by_user_id.get(resolved_user_id, [])
                if account_ids:
                    placeholders = ",".join("?" for _ in account_ids)
                    clauses.append(
                        f"(l.account_id IN ({placeholders}) OR (l.user_id = ? AND l.account_id IS NULL))"
                    )
                    params.extend(account_ids)
                    params.append(resolved_user_id)
                else:
                    clauses.append("l.user_id = ?")
                    params.append(resolved_user_id)
            elif str(row_user_key).startswith("account:"):
                clauses.append("l.account_id = ?")
                params.append(int(str(row_user_key).split(":", 1)[1]))
            else:
                clauses.append("l.user_id IS NULL AND l.account_id IS NULL")
            return " AND ".join(clauses), tuple(params)

        known_user_email_by_id = _known_user_email_by_id()

        api_usage["top_users"] = []
        for row in db.fetchall(api_user_sql, (start_iso,)):
            user_id = row["user_id"]
            user_key = row["user_key"] or "background"
            calls = int(row["calls"] or 0)
            success_count = int(row["success_count"] or 0)
            account_emails = _split_group_concat(row["account_emails"])
            if user_id is not None:
                account_emails = account_emails or account_emails_by_user_id.get(int(user_id), [])
            user_email = known_user_email_by_id.get(int(user_id)) if user_id is not None else None
            user_email = user_email or (account_emails[0] if account_emails else None)
            account_label = user_email or (account_emails[0] if account_emails else "background")
            user_label = user_email or account_label
            if not user_label or user_label == "background":
                user_label = "background" if user_id is None else f"user #{user_id}"

            if user_id is None and user_key == "background":
                api_usage["top_users"].append(
                    {
                        "user_key": user_key,
                        "user_id": user_id,
                        "user_email": user_email,
                        "user_label": user_label,
                        "account_label": account_label,
                        "account_count": int(row["account_count"] or 0),
                        "calls": calls,
                        "success_rate": round(success_count / calls, 4) if calls else 0.0,
                        "failure_count": max(0, calls - success_count),
                        "avg_duration_ms": int(row["avg_duration_ms"] or 0),
                        "accounts": [],
                        "providers": [],
                        "features": [],
                        "daily": [],
                        "hourly": [
                            {
                                "hour": hour,
                                "calls": 0,
                                "success_rate": 0.0,
                                "failure_count": 0,
                                "avg_duration_ms": 0,
                            }
                            for hour in range(24)
                        ],
                        "status_codes": [],
                        "endpoints": [],
                        "processes": [],
                        "recent_failures": [],
                    }
                )
                continue

            detail_where_sql, detail_params = _api_usage_detail_filter(user_id, user_key)
            accounts = []
            if accounts_table_exists:
                accounts = [
                    {
                        "account_id": account_row["account_id"],
                        "account_label": account_row["account_label"] or "background",
                        "calls": int(account_row["calls"] or 0),
                        "success_rate": round(
                            float(account_row["success_count"] or 0) / int(account_row["calls"] or 1),
                            4,
                        ),
                    }
                    for account_row in db.fetchall(
                        f"""
                        SELECT l.account_id,
                               COALESCE(a.email, 'account #' || l.account_id, 'background') AS account_label,
                               COUNT(*) AS calls,
                               COALESCE(SUM(CASE WHEN l.success = 1 THEN 1 ELSE 0 END), 0) AS success_count
                        FROM api_usage_log l
                        LEFT JOIN accounts a ON a.id = l.account_id
                        WHERE {detail_where_sql}
                        GROUP BY l.account_id, a.email
                        ORDER BY calls DESC
                        LIMIT 6
                        """,
                        detail_params,
                    )
                    if account_row["account_id"] is not None
                ]

            providers = [
                {
                    "provider": provider_row["provider"] or "unknown",
                    "calls": int(provider_row["calls"] or 0),
                    "success_rate": round(
                        float(provider_row["success_count"] or 0) / int(provider_row["calls"] or 1),
                        4,
                    ),
                    "avg_duration_ms": int(provider_row["avg_duration_ms"] or 0),
                }
                for provider_row in db.fetchall(
                    f"""
                    SELECT COALESCE(l.provider, 'unknown') AS provider,
                           COUNT(*) AS calls,
                           COALESCE(SUM(CASE WHEN l.success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                           COALESCE(AVG(l.duration_ms), 0) AS avg_duration_ms
                    FROM api_usage_log l
                    WHERE {detail_where_sql}
                    GROUP BY COALESCE(l.provider, 'unknown')
                    ORDER BY calls DESC
                    LIMIT 6
                    """,
                    detail_params,
                )
            ]

            features = [
                {
                    "feature": feature_row["feature"] or "unknown",
                    "calls": int(feature_row["calls"] or 0),
                    "success_rate": round(
                        float(feature_row["success_count"] or 0) / int(feature_row["calls"] or 1),
                        4,
                    ),
                }
                for feature_row in db.fetchall(
                    f"""
                    SELECT COALESCE(l.feature, 'unknown') AS feature,
                           COUNT(*) AS calls,
                           COALESCE(SUM(CASE WHEN l.success = 1 THEN 1 ELSE 0 END), 0) AS success_count
                    FROM api_usage_log l
                    WHERE {detail_where_sql}
                    GROUP BY COALESCE(l.feature, 'unknown')
                    ORDER BY calls DESC
                    LIMIT 6
                    """,
                    detail_params,
                )
            ]

            daily = [
                {
                    "date": daily_row["date"] or "unknown",
                    "calls": int(daily_row["calls"] or 0),
                    "success_rate": round(
                        float(daily_row["success_count"] or 0) / int(daily_row["calls"] or 1),
                        4,
                    ),
                    "failure_count": max(
                        0,
                        int(daily_row["calls"] or 0) - int(daily_row["success_count"] or 0),
                    ),
                    "avg_duration_ms": int(daily_row["avg_duration_ms"] or 0),
                }
                for daily_row in db.fetchall(
                    f"""
                    SELECT SUBSTR(l.created_at, 1, 10) AS date,
                           COUNT(*) AS calls,
                           COALESCE(SUM(CASE WHEN l.success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                           COALESCE(AVG(l.duration_ms), 0) AS avg_duration_ms
                    FROM api_usage_log l
                    WHERE {detail_where_sql}
                    GROUP BY SUBSTR(l.created_at, 1, 10)
                    ORDER BY date ASC
                    LIMIT 90
                    """,
                    detail_params,
                )
            ]

            hourly_rows = {
                int(hourly_row["hour"] or 0): {
                    "hour": int(hourly_row["hour"] or 0),
                    "calls": int(hourly_row["calls"] or 0),
                    "success_rate": round(
                        float(hourly_row["success_count"] or 0) / int(hourly_row["calls"] or 1),
                        4,
                    ),
                    "failure_count": max(
                        0,
                        int(hourly_row["calls"] or 0) - int(hourly_row["success_count"] or 0),
                    ),
                    "avg_duration_ms": int(hourly_row["avg_duration_ms"] or 0),
                }
                for hourly_row in db.fetchall(
                    f"""
                    SELECT CAST(SUBSTR(l.created_at, 12, 2) AS INTEGER) AS hour,
                           COUNT(*) AS calls,
                           COALESCE(SUM(CASE WHEN l.success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                           COALESCE(AVG(l.duration_ms), 0) AS avg_duration_ms
                    FROM api_usage_log l
                    WHERE {detail_where_sql}
                    GROUP BY CAST(SUBSTR(l.created_at, 12, 2) AS INTEGER)
                    ORDER BY hour ASC
                    """,
                    detail_params,
                )
            }
            hourly = [
                hourly_rows.get(
                    hour,
                    {
                        "hour": hour,
                        "calls": 0,
                        "success_rate": 0.0,
                        "failure_count": 0,
                        "avg_duration_ms": 0,
                    },
                )
                for hour in range(24)
            ]

            status_codes = [
                {
                    "status_code": status_row["status_code"] or "none",
                    "calls": int(status_row["calls"] or 0),
                    "success_rate": round(
                        float(status_row["success_count"] or 0) / int(status_row["calls"] or 1),
                        4,
                    ),
                    "avg_duration_ms": int(status_row["avg_duration_ms"] or 0),
                }
                for status_row in db.fetchall(
                    f"""
                    SELECT COALESCE(CAST(l.status_code AS TEXT), 'none') AS status_code,
                           COUNT(*) AS calls,
                           COALESCE(SUM(CASE WHEN l.success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                           COALESCE(AVG(l.duration_ms), 0) AS avg_duration_ms
                    FROM api_usage_log l
                    WHERE {detail_where_sql}
                    GROUP BY COALESCE(CAST(l.status_code AS TEXT), 'none')
                    ORDER BY calls DESC
                    LIMIT 8
                    """,
                    detail_params,
                )
            ]

            endpoints = [
                {
                    "method": endpoint_row["method"] or "GET",
                    "host": endpoint_row["url_host"] or "unknown",
                    "path": endpoint_row["url_path"] or "/",
                    "calls": int(endpoint_row["calls"] or 0),
                    "success_rate": round(
                        float(endpoint_row["success_count"] or 0) / int(endpoint_row["calls"] or 1),
                        4,
                    ),
                    "avg_duration_ms": int(endpoint_row["avg_duration_ms"] or 0),
                }
                for endpoint_row in db.fetchall(
                    f"""
                    SELECT COALESCE(l.method, 'GET') AS method,
                           COALESCE(l.url_host, 'unknown') AS url_host,
                           COALESCE(l.url_path, '/') AS url_path,
                           COUNT(*) AS calls,
                           COALESCE(SUM(CASE WHEN l.success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                           COALESCE(AVG(l.duration_ms), 0) AS avg_duration_ms
                    FROM api_usage_log l
                    WHERE {detail_where_sql}
                    GROUP BY COALESCE(l.method, 'GET'), COALESCE(l.url_host, 'unknown'), COALESCE(l.url_path, '/')
                    ORDER BY calls DESC
                    LIMIT 8
                    """,
                    detail_params,
                )
            ]

            processes = [
                {
                    "process_name": process_row["process_name"] or "unknown",
                    "calls": int(process_row["calls"] or 0),
                    "success_rate": round(
                        float(process_row["success_count"] or 0) / int(process_row["calls"] or 1),
                        4,
                    ),
                    "avg_duration_ms": int(process_row["avg_duration_ms"] or 0),
                }
                for process_row in db.fetchall(
                    f"""
                    SELECT COALESCE(l.process_name, 'unknown') AS process_name,
                           COUNT(*) AS calls,
                           COALESCE(SUM(CASE WHEN l.success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                           COALESCE(AVG(l.duration_ms), 0) AS avg_duration_ms
                    FROM api_usage_log l
                    WHERE {detail_where_sql}
                    GROUP BY COALESCE(l.process_name, 'unknown')
                    ORDER BY calls DESC
                    LIMIT 6
                    """,
                    detail_params,
                )
            ]

            recent_failures = [
                {
                    "created_at": failure_row["created_at"],
                    "provider": failure_row["provider"] or "unknown",
                    "feature": failure_row["feature"] or "unknown",
                    "method": failure_row["method"] or "GET",
                    "host": failure_row["url_host"] or "unknown",
                    "path": failure_row["url_path"] or "/",
                    "status_code": failure_row["status_code"],
                    "duration_ms": int(failure_row["duration_ms"] or 0),
                    "auth_type": failure_row["auth_type"] or "unknown",
                    "process_name": failure_row["process_name"] or "unknown",
                }
                for failure_row in db.fetchall(
                    f"""
                    SELECT l.created_at,
                           l.provider,
                           l.feature,
                           l.method,
                           l.url_host,
                           l.url_path,
                           l.status_code,
                           l.duration_ms,
                           l.auth_type,
                           l.process_name
                    FROM api_usage_log l
                    WHERE {detail_where_sql} AND l.success != 1
                    ORDER BY l.created_at DESC
                    LIMIT 6
                    """,
                    detail_params,
                )
            ]

            api_usage["top_users"].append(
                {
                    "user_key": user_key,
                    "user_id": user_id,
                    "user_email": user_email,
                    "user_label": user_label,
                    "account_label": account_label,
                    "account_count": int(row["account_count"] or 0),
                    "calls": calls,
                    "success_rate": round(success_count / calls, 4) if calls else 0.0,
                    "failure_count": max(0, calls - success_count),
                    "avg_duration_ms": int(row["avg_duration_ms"] or 0),
                    "accounts": accounts,
                    "providers": providers,
                    "features": features,
                    "daily": daily,
                    "hourly": hourly,
                    "status_codes": status_codes,
                    "endpoints": endpoints,
                    "processes": processes,
                    "recent_failures": recent_failures,
                }
            )
        api_usage["top_features"] = [
            {
                "feature": row["feature"] or "unknown",
                "calls": int(row["calls"] or 0),
                "success_rate": round(float(row["success_count"] or 0) / int(row["calls"] or 1), 4),
            }
            for row in db.fetchall(
                """
                SELECT COALESCE(feature, 'unknown') AS feature,
                       COUNT(*) AS calls,
                       COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success_count
                FROM api_usage_log
                WHERE created_at >= ?
                GROUP BY COALESCE(feature, 'unknown')
                ORDER BY calls DESC
                LIMIT 10
                """,
                (start_iso,),
            )
        ]

    draft_count = 0
    avg_cost_per_draft = 0.0
    latency_p50 = 0
    latency_p95 = 0
    quality_score_avg = None
    draft_status = []
    if _table_exists("draft_history"):
        draft_rows = db.fetchall(
            """
            SELECT status, COUNT(*) AS count
            FROM draft_history
            WHERE created_at >= ?
            GROUP BY status
            ORDER BY count DESC
            """,
            (start_iso,),
        )
        draft_status = [{"status": row["status"] or "unknown", "count": row["count"]} for row in draft_rows]
        draft_count = sum(int(row["count"] or 0) for row in draft_rows)
        avg_cost_per_draft = spend / draft_count if draft_count else 0.0
        latency_rows = db.fetchall(
            """
            SELECT processing_time_ms
            FROM draft_history
            WHERE created_at >= ? AND processing_time_ms IS NOT NULL AND processing_time_ms > 0
            """,
            (start_iso,),
        )
        latencies = [int(row["processing_time_ms"]) for row in latency_rows]
        latency_p50 = _percentile(latencies, 0.50)
        latency_p95 = _percentile(latencies, 0.95)
        score_row = db.fetchone(
            """
            SELECT AVG(feedback_score) AS score
            FROM draft_history
            WHERE created_at >= ? AND feedback_score IS NOT NULL
            """,
            (start_iso,),
        )
        if score_row and score_row["score"] is not None:
            quality_score_avg = round(float(score_row["score"]), 2)

        draft_daily = db.fetchall(
            """
            SELECT date(created_at) AS day, COUNT(*) AS count
            FROM draft_history
            WHERE created_at >= ?
            GROUP BY date(created_at)
            """,
            (start_iso,),
        )
        drafts_by_day = {row["day"]: int(row["count"] or 0) for row in draft_daily}
        for point in series:
            point["drafts"] = drafts_by_day.get(point["date"], 0)

    drafts_table_status = []
    if _table_exists("drafts"):
        drafts_table_status = [
            {"status": row["status"] or "unknown", "count": row["count"]}
            for row in db.fetchall(
                """
                SELECT status, COUNT(*) AS count
                FROM drafts
                WHERE created_at >= ?
                GROUP BY status
                ORDER BY count DESC
                """,
                (start_iso,),
            )
        ]

    cron_runs = []
    if _table_exists("cron_runs"):
        cron_runs = [
            dict(row)
            for row in db.fetchall(
                """
                SELECT *
                FROM cron_runs
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
        ]

    sentinel_alerts = []
    if _table_exists("audit_log"):
        sentinel_alerts = [
            {
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "success": bool(row["success"]),
                "error": row["error"],
            }
            for row in db.fetchall(
                """
                SELECT timestamp, event_type, success, error
                FROM audit_log
                WHERE lower(event_type) LIKE '%sentinel%' OR lower(event_type) LIKE '%alert%'
                ORDER BY timestamp DESC
                LIMIT 30
                """
            )
        ]

    admin_audit = []
    if _table_exists("admin_audit_log"):
        admin_audit = [
            {
                "actor": row["actor"],
                "action": row["action"],
                "created_at": row["created_at"],
            }
            for row in db.fetchall(
                """
                SELECT actor, action, created_at
                FROM admin_audit_log
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
        ]

    if canonical_tokens is not None:
        draft_counts_by_day = {point["date"]: point.get("drafts", 0) for point in series}
        series = canonical_tokens["series"]
        for point in series:
            point["drafts"] = draft_counts_by_day.get(point["date"], 0)
        current = canonical_tokens["current"]
        spend = canonical_tokens["spend"]
        prev_spend = canonical_tokens["prev_spend"]
        request_count = canonical_tokens["request_count"]
        cache_hit_rate = canonical_tokens["cache_hit_rate"]
        avg_cost_per_draft = spend / draft_count if draft_count else 0.0
        by_model = canonical_tokens["by_model"]
        top_accounts = canonical_tokens["top_accounts"]
        top_features = canonical_tokens["top_features"]
        token_users = canonical_tokens["token_users"]

    return jsonify({
        "generated_at": now.isoformat(),
        "period_days": days,
        "summary": {
            "spend_usd": round(spend, 4),
            "spend_change_pct": _pct_change(spend, prev_spend),
            "total_tokens": int(current["total_tokens"] or 0) if current else 0,
            "request_count": request_count,
            "avg_cost_per_request": round(spend / request_count, 6) if request_count else 0.0,
            "avg_cost_per_draft": round(avg_cost_per_draft, 6),
            "cache_hit_rate": round(cache_hit_rate, 4),
            "draft_count": draft_count,
            "draft_latency_p50_ms": latency_p50,
            "draft_latency_p95_ms": latency_p95,
            "quality_score_avg": quality_score_avg,
        },
        "series": series,
        "tokens": {
            "by_model": by_model,
            "top_accounts": top_accounts,
            "top_features": top_features,
            "by_user": token_users,
        },
        "api_usage": api_usage,
        "product": {
            "draft_status": draft_status,
            "drafts_table_status": drafts_table_status,
        },
        "infra": {
            "cron_runs": cron_runs,
            "sentinel_alerts": sentinel_alerts,
            "deployments": [],
        },
        "security": {
            "admin_audit": admin_audit,
            "unusual_logins": [],
            "provider_quotas": [],
        },
    })


def _get_period_range(period: str):
    """Retourne (start_date, end_date) ISO strings pour la période."""
    now = datetime.now(timezone.utc)
    if period == "7d":
        start = now - timedelta(days=7)
    elif period == "30d":
        start = now - timedelta(days=30)
    elif period == "90d":
        start = now - timedelta(days=90)
    else:  # all
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return start.isoformat(), now.isoformat()


def _get_previous_period_range(period: str):
    """Retourne la période précédente pour le calcul du % change."""
    now = datetime.now(timezone.utc)
    if period == "7d":
        delta = timedelta(days=7)
    elif period == "30d":
        delta = timedelta(days=30)
    elif period == "90d":
        delta = timedelta(days=90)
    else:
        return None, None
    end = now - delta
    start = end - delta
    return start.isoformat(), end.isoformat()


def _load_known_users_for_admin() -> list[dict]:
    """Load the known_users.json registry via the (test-patchable) path helper.

    Both readers used to inline the path, bypassing ``_known_users_file_path``;
    routing through it keeps them consistent and unit-test-controllable.
    """
    users_file = _known_users_file_path()
    if not os.path.exists(users_file):
        return []
    try:
        with open(users_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def _coerce_iso(value) -> str | None:
    """Normalize a datetime/str column value to an ISO string (or None)."""
    if not value:
        return None
    if isinstance(value, str):
        return value
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _min_iso(a: str | None, b: str | None) -> str | None:
    candidates = [v for v in (a, b) if v]
    return min(candidates) if candidates else None


def _max_iso(a: str | None, b: str | None) -> str | None:
    candidates = [v for v in (a, b) if v]
    return max(candidates) if candidates else None


def _enumerate_accounts() -> list[dict] | None:
    """Return account rows from the canonical store, then the legacy layer.

    Each row: ``{id, email, user_id, created_at, last_sync_at}``. Returns
    ``None`` when no accounts source is reachable so callers fall back to the
    known_users.json registry (keeps SQLite-only unit tests and pre-accounts
    installs working).
    """
    # Canonical store (prod Postgres + encrypted desktop sqlcipher).
    try:
        from sqlalchemy import select
        from app.db.database import get_db_session
        from app.db.models.account import Account

        with get_db_session() as session:
            rows = session.execute(
                select(
                    Account.id,
                    Account.email,
                    Account.user_id,
                    Account.created_at,
                    Account.last_sync_at,
                )
            ).all()
        if rows:
            return [
                {
                    "id": row[0],
                    "email": row[1],
                    "user_id": row[2],
                    "created_at": _coerce_iso(row[3]),
                    "last_sync_at": _coerce_iso(row[4]),
                }
                for row in rows
            ]
    except Exception as exc:
        logger.debug("[admin/users] canonical accounts unavailable: %s", exc)

    # Legacy SQLite layer (same encrypted file on desktop; seeded in tests).
    if _table_exists("accounts"):
        try:
            from app.infrastructure.database import db

            has_created = _table_has_column("accounts", "created_at")
            has_sync = _table_has_column("accounts", "last_sync_at")
            columns = ["id", "email", "user_id"]
            if has_created:
                columns.append("created_at")
            if has_sync:
                columns.append("last_sync_at")
            rows = db.fetchall(f"SELECT {', '.join(columns)} FROM accounts")
            return [
                {
                    "id": row["id"],
                    "email": row["email"],
                    "user_id": row["user_id"],
                    "created_at": _coerce_iso(row["created_at"]) if has_created else None,
                    "last_sync_at": _coerce_iso(row["last_sync_at"]) if has_sync else None,
                }
                for row in rows
            ]
        except Exception as exc:
            logger.debug("[admin/users] legacy accounts query failed: %s", exc)
    return None


def _dashboard_user_registry() -> list[dict]:
    """Canonical user list for the admin dashboard.

    Source of truth is the ``accounts`` table — one entry per JWT ``user_id``,
    with NULL-user_id accounts (legacy/Tauri desktop) kept as standalone
    users — merged with the known_users.json registry for ``registered_at`` /
    ``last_seen``. Falls back to known_users.json alone when accounts are
    unreachable.

    Previously the dashboard read known_users.json *alone*. That side-file
    ignores ``AGENTYS_DATA_DIR`` (unlike the DB), so on any environment where it
    was empty or wiped (e.g. a container redeploy) the dashboard showed "no
    users" even though accounts existed. Entries keep the known_users.json shape
    (``{email, registered_at, last_seen}``) so downstream metric code is
    unchanged.
    """
    from .auth import user_id_from_email

    by_email: dict[str, dict] = {}
    for entry in _load_known_users_for_admin():
        email = (entry.get("email") or "").strip().lower()
        if not email:
            continue
        by_email[email] = {
            "email": email,
            "user_id": user_id_from_email(email),
            "registered_at": entry.get("registered_at", ""),
            "last_seen": entry.get("last_seen"),
        }

    accounts = _enumerate_accounts()
    if accounts is None:
        return list(by_email.values())

    login_email_by_id = _known_user_email_by_id()

    grouped: dict = {}
    for account in accounts:
        email = (account.get("email") or "").strip().lower()
        user_id = account.get("user_id")
        if user_id is not None:
            key: tuple = ("uid", int(user_id))
        else:
            key = ("acct", account.get("id"), email)
        bucket = grouped.setdefault(
            key, {"user_id": user_id, "emails": [], "created": None, "synced": None}
        )
        if email and email not in bucket["emails"]:
            bucket["emails"].append(email)
        bucket["created"] = _min_iso(bucket["created"], account.get("created_at"))
        bucket["synced"] = _max_iso(bucket["synced"], account.get("last_sync_at"))

    for bucket in grouped.values():
        user_id = bucket["user_id"]
        representative = None
        if user_id is not None:
            # The JWT login email is what user_activity rows are keyed by.
            representative = login_email_by_id.get(int(user_id))
        if not representative and bucket["emails"]:
            representative = bucket["emails"][0]
        if not representative:
            continue
        representative = representative.strip().lower()
        resolved_uid = int(user_id) if user_id is not None else user_id_from_email(representative)

        existing = by_email.get(representative)
        if existing:
            if user_id is not None:
                # The account's JWT user_id is authoritative for billing lookup.
                existing["user_id"] = int(user_id)
            existing.setdefault("user_id", resolved_uid)
            if not existing.get("registered_at") and bucket["created"]:
                existing["registered_at"] = bucket["created"]
            if not existing.get("last_seen") and bucket["synced"]:
                existing["last_seen"] = bucket["synced"]
        else:
            by_email[representative] = {
                "email": representative,
                "user_id": resolved_uid,
                "registered_at": bucket["created"] or "",
                "last_seen": bucket["synced"],
            }

    return list(by_email.values())


_FREE_TIER = {"tier": "free", "plan": "free", "subscription_status": "none"}


def _classify_tier(plan, status, period_end, now: datetime | None = None) -> dict:
    """Bucket a billing_subscriptions row into the Free/Paid admin tiers.

    Paid = currently *entitled*: status in {active, trialing} on a non-free
    plan, with the billing period not expired — mirrors the app's
    ``ai_enabled`` rule (ACTIVE_AI_STATUSES + period check). Everything else
    (no subscription, free plan, past_due/canceled/unpaid, expired period) is
    Free. The exact plan + status are returned alongside so the dashboard can
    show nuance.
    """
    from app.billing.entitlements import ACTIVE_AI_STATUSES, PLAN_ALIASES

    now = now or datetime.now(timezone.utc)
    status_l = (status or "none").lower()
    plan_l = (plan or "free").lower()
    plan_l = PLAN_ALIASES.get(plan_l, plan_l)

    period_active = True
    if period_end is not None:
        if isinstance(period_end, str):
            try:
                period_end = datetime.fromisoformat(period_end)
            except ValueError:
                period_end = None
        if period_end is not None:
            if period_end.tzinfo is None:
                period_end = period_end.replace(tzinfo=timezone.utc)
            period_active = period_end > now

    is_paid = status_l in ACTIVE_AI_STATUSES and period_active and plan_l != "free"
    return {
        "tier": "paid" if is_paid else "free",
        "plan": plan_l,
        "subscription_status": status_l,
    }


def _subscription_tier_map() -> dict[int, dict]:
    """Map user_id → {tier, plan, subscription_status} from billing_subscriptions.

    One canonical query; users without a row (or when billing is unreachable)
    are treated as Free by the callers. Keyed by JWT user_id.
    """
    result: dict[int, dict] = {}
    try:
        from sqlalchemy import select
        from app.db.database import get_db_session
        from app.db.models import BillingSubscription

        with get_db_session() as session:
            rows = session.execute(
                select(
                    BillingSubscription.user_id,
                    BillingSubscription.plan,
                    BillingSubscription.status,
                    BillingSubscription.current_period_end,
                )
            ).all()
        now = datetime.now(timezone.utc)
        for user_id, plan, status, period_end in rows:
            if user_id is None:
                continue
            result[int(user_id)] = _classify_tier(plan, status, period_end, now)
    except Exception as exc:
        logger.debug("[admin/users] subscription tier map unavailable: %s", exc)
    return result


def _fetch_user_metrics(start_iso: str, end_iso: str, search: str = None, tier: str = None):
    """Récupère les métriques par utilisateur pour la période."""
    from app.infrastructure.database import db

    # Source of truth = the accounts table (real connected users), enriched
    # with the known_users.json registry. See _dashboard_user_registry for why
    # reading known_users.json alone produced "no users" after redeploys.
    users = _dashboard_user_registry()

    if search:
        search_lower = search.lower()
        users = [u for u in users if search_lower in u.get("email", "").lower()]

    tier_map = _subscription_tier_map()
    tier_filter = (tier or "").strip().lower()
    if tier_filter in ("free", "paid"):
        users = [
            u for u in users
            if tier_map.get(u.get("user_id"), _FREE_TIER)["tier"] == tier_filter
        ]

    results = []
    for user in users:
        email = user.get("email", "")

        # Activity: count from user_activity
        row = db.fetchone(
            "SELECT COUNT(*) as total, COUNT(DISTINCT date(created_at)) as active_days "
            "FROM user_activity WHERE user_email = ? AND created_at >= ? AND created_at <= ?",
            (email, start_iso, end_iso)
        )
        total_actions = row["total"] if row else 0
        active_days = row["active_days"] if row else 0

        # AI compose count
        row = db.fetchone(
            "SELECT COUNT(*) as cnt FROM user_activity "
            "WHERE user_email = ? AND action = 'compose_ai' AND created_at >= ? AND created_at <= ?",
            (email, start_iso, end_iso)
        )
        compose_ai = row["cnt"] if row else 0

        # Emails sent
        row = db.fetchone(
            "SELECT COUNT(*) as cnt FROM user_activity "
            "WHERE user_email = ? AND action = 'email_sent' AND created_at >= ? AND created_at <= ?",
            (email, start_iso, end_iso)
        )
        emails_sent = row["cnt"] if row else 0

        # Cost from activity metadata
        row = db.fetchone(
            "SELECT COALESCE(SUM(json_extract(metadata, '$.cost')), 0) as total_cost "
            "FROM user_activity WHERE user_email = ? AND created_at >= ? AND created_at <= ?",
            (email, start_iso, end_iso)
        )
        cost_usd = row["total_cost"] if row else 0.0

        # Revenue
        row = db.fetchone(
            "SELECT COALESCE(SUM(amount_usd), 0) as total_rev "
            "FROM revenue_events WHERE user_email = ? AND created_at >= ? AND created_at <= ?",
            (email, start_iso, end_iso)
        )
        revenue = row["total_rev"] if row else 0.0

        # Last activity
        row = db.fetchone(
            "SELECT MAX(created_at) as last_active FROM user_activity WHERE user_email = ?",
            (email,)
        )
        last_active = row["last_active"] if row else user.get("last_seen")

        # Sparkline: last 7 days actions per day
        sparkline_rows = db.fetchall(
            "SELECT date(created_at) as d, COUNT(*) as cnt "
            "FROM user_activity WHERE user_email = ? AND created_at >= ? "
            "GROUP BY date(created_at) ORDER BY d DESC LIMIT 7",
            (email, (datetime.now(timezone.utc) - timedelta(days=7)).isoformat())
        )
        sparkline = [r["cnt"] for r in reversed(sparkline_rows)]

        # Churn risk: days since last activity / account age
        registered_at = user.get("registered_at", "")
        churn_risk = 0.0
        if last_active and registered_at:
            try:
                last_dt = datetime.fromisoformat(last_active.replace("Z", "+00:00"))
                reg_dt = datetime.fromisoformat(registered_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days_inactive = (now - last_dt).days
                account_age = max((now - reg_dt).days, 1)
                churn_risk = min(days_inactive / account_age, 1.0)
            except (ValueError, TypeError):
                pass

        margin = revenue - cost_usd
        tier_info = tier_map.get(user.get("user_id"), _FREE_TIER)

        results.append({
            "email": email,
            "registered_at": registered_at,
            "last_active": last_active,
            "active_days": active_days,
            "total_actions": total_actions,
            "compose_ai": compose_ai,
            "emails_sent": emails_sent,
            "cost_usd": round(cost_usd, 4),
            "revenue_usd": round(revenue, 2),
            "margin_usd": round(margin, 2),
            "churn_risk": round(churn_risk, 2),
            "tier": tier_info["tier"],
            "plan": tier_info["plan"],
            "subscription_status": tier_info["subscription_status"],
            "sparkline": sparkline,
        })

    return results


@admin_bp.route("/users", methods=["GET"])
@require_admin
def list_users():
    """Liste paginée des utilisateurs avec métriques."""
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 25, type=int)
    sort_by = request.args.get("sort_by", "last_active")
    sort_dir = request.args.get("sort_dir", "desc")
    search = request.args.get("search", "").strip() or None
    tier = request.args.get("tier", "").strip().lower() or None
    period = request.args.get("period", "30d")

    start_iso, end_iso = _get_period_range(period)
    users = _fetch_user_metrics(start_iso, end_iso, search, tier)

    # Sort
    reverse = sort_dir == "desc"
    if sort_by in ("email", "registered_at", "last_active", "plan", "subscription_status", "tier"):
        users.sort(key=lambda u: u.get(sort_by) or "", reverse=reverse)
    else:
        users.sort(key=lambda u: u.get(sort_by, 0) or 0, reverse=reverse)

    # Paginate
    total = len(users)
    start = (page - 1) * page_size
    end = start + page_size
    page_users = users[start:end]

    return jsonify({
        "users": page_users,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    })


@admin_bp.route("/users/<path:email>/detail", methods=["GET"])
@require_admin
def user_detail(email: str):
    """Détail d'un utilisateur avec time-series."""
    from app.infrastructure.database import db

    days = request.args.get("days", 30, type=int)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Daily activity
    daily = db.fetchall(
        "SELECT date(created_at) as d, COUNT(*) as actions, "
        "COALESCE(SUM(json_extract(metadata, '$.cost')), 0) as cost "
        "FROM user_activity WHERE user_email = ? AND created_at >= ? "
        "GROUP BY date(created_at) ORDER BY d",
        (email, cutoff)
    )
    daily_data = [{"date": r["d"], "actions": r["actions"], "cost": round(r["cost"], 4)} for r in daily]

    # Actions breakdown
    breakdown = db.fetchall(
        "SELECT action, COUNT(*) as cnt FROM user_activity "
        "WHERE user_email = ? AND created_at >= ? GROUP BY action ORDER BY cnt DESC",
        (email, cutoff)
    )
    actions_breakdown = {r["action"]: r["cnt"] for r in breakdown}

    # Feedback scores
    row = db.fetchone(
        "SELECT AVG(feedback_score) as avg_score, COUNT(feedback_score) as cnt "
        "FROM draft_history WHERE email_sender = ? AND feedback_score IS NOT NULL "
        "AND created_at >= ?",
        (email, cutoff)
    )
    ai_satisfaction = {
        "avg_score": round(row["avg_score"], 2) if row and row["avg_score"] else None,
        "count": row["cnt"] if row else 0,
    }

    return jsonify({
        "email": email,
        "daily": daily_data,
        "actions_breakdown": actions_breakdown,
        "ai_satisfaction": ai_satisfaction,
    })


@admin_bp.route("/aggregate", methods=["GET"])
@require_admin
def aggregate():
    """Cartes résumé globales."""
    from app.infrastructure.database import db

    period = request.args.get("period", "30d")
    start_iso, end_iso = _get_period_range(period)
    prev_start, prev_end = _get_previous_period_range(period)

    # Total users = real connected accounts ∪ known_users.json registry.
    # (Was len(known_users.json), which read empty after redeploys because that
    # side-file ignores AGENTYS_DATA_DIR — see _dashboard_user_registry.)
    registry = _dashboard_user_registry()
    tier_map = _subscription_tier_map()
    total_users = len(registry)
    paid_users = sum(
        1 for u in registry
        if tier_map.get(u.get("user_id"), _FREE_TIER)["tier"] == "paid"
    )
    free_users = total_users - paid_users

    # Active users this period
    row = db.fetchone(
        "SELECT COUNT(DISTINCT user_email) as cnt FROM user_activity "
        "WHERE created_at >= ? AND created_at <= ?",
        (start_iso, end_iso)
    )
    active_users = row["cnt"] if row else 0

    # Total cost
    row = db.fetchone(
        "SELECT COALESCE(SUM(json_extract(metadata, '$.cost')), 0) as total "
        "FROM user_activity WHERE created_at >= ? AND created_at <= ?",
        (start_iso, end_iso)
    )
    total_cost = round(row["total"] if row else 0, 2)

    # Total revenue
    row = db.fetchone(
        "SELECT COALESCE(SUM(amount_usd), 0) as total "
        "FROM revenue_events WHERE created_at >= ? AND created_at <= ?",
        (start_iso, end_iso)
    )
    total_revenue = round(row["total"] if row else 0, 2)

    # Previous period for % change
    prev_cost = 0
    prev_revenue = 0
    prev_active = 0
    if prev_start and prev_end:
        row = db.fetchone(
            "SELECT COUNT(DISTINCT user_email) as cnt FROM user_activity "
            "WHERE created_at >= ? AND created_at <= ?",
            (prev_start, prev_end)
        )
        prev_active = row["cnt"] if row else 0

        row = db.fetchone(
            "SELECT COALESCE(SUM(json_extract(metadata, '$.cost')), 0) as total "
            "FROM user_activity WHERE created_at >= ? AND created_at <= ?",
            (prev_start, prev_end)
        )
        prev_cost = round(row["total"] if row else 0, 2)

        row = db.fetchone(
            "SELECT COALESCE(SUM(amount_usd), 0) as total "
            "FROM revenue_events WHERE created_at >= ? AND created_at <= ?",
            (prev_start, prev_end)
        )
        prev_revenue = round(row["total"] if row else 0, 2)

    def pct_change(current, previous):
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return round(((current - previous) / previous) * 100, 1)

    return jsonify({
        "total_users": total_users,
        "free_users": free_users,
        "paid_users": paid_users,
        "active_users": active_users,
        "active_users_change": pct_change(active_users, prev_active),
        "total_cost_usd": total_cost,
        "cost_change": pct_change(total_cost, prev_cost),
        "total_revenue_usd": total_revenue,
        "revenue_change": pct_change(total_revenue, prev_revenue),
        "margin_usd": round(total_revenue - total_cost, 2),
        "margin_change": pct_change(total_revenue - total_cost, prev_revenue - prev_cost),
    })


@admin_bp.route("/export", methods=["GET"])
@require_admin
def export_csv():
    """Export CSV des métriques utilisateurs."""
    period = request.args.get("period", "30d")
    search = request.args.get("search", "").strip() or None
    tier = request.args.get("tier", "").strip().lower() or None

    start_iso, end_iso = _get_period_range(period)
    users = _fetch_user_metrics(start_iso, end_iso, search, tier)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "email", "tier", "plan", "subscription_status", "registered_at",
        "last_active", "active_days", "total_actions", "compose_ai",
        "emails_sent", "cost_usd", "revenue_usd", "margin_usd", "churn_risk",
    ])
    writer.writeheader()
    for u in users:
        row = {k: u[k] for k in writer.fieldnames}
        writer.writerow(row)

    csv_content = output.getvalue()
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=agentys_users_{period}.csv"},
    )


# ============================================================================
# LLM OPS ENDPOINTS (audit 2026-05-06)
# ============================================================================
# These endpoints back the "AI Operations" panel of the admin dashboard.
# Sources:
#   - /llm-stats : in-process counters (cache hit, critic skip, latency)
#                  + token_usage_log SQL aggregate (cost by agent).
#   - /draft-feedback : draft_feedback table aggregate.
# All require admin auth (same gate as the rest of the blueprint).
# ============================================================================


@admin_bp.route("/llm-stats", methods=["GET"])
@require_admin_or_token
def llm_stats():
    """LLM operational metrics for the admin dashboard.

    Returns a single payload combining:
      - cache_hit_rate (rolling 1k-call window + lifetime)
      - critic skip_rate (heuristic gate bypass ratio)
      - draft latency p50/p95/p99 by tier
      - token_usage_writer queue health
      - cost-by-agent (from token_usage_log, last N days via ?days=)
    """
    days = request.args.get("days", 30, type=int)
    days = max(1, min(days, 365))

    payload: dict = {}
    try:
        from app.adapters.llm.claude_adapter import get_cache_hit_stats, get_truncation_stats
        payload["cache"] = get_cache_hit_stats()
        payload["truncation"] = get_truncation_stats()
    except Exception as e:
        logger.debug("[admin/llm-stats] cache/truncation stats unavailable: %s", e)
        payload["cache"] = {"error": str(e)}
        payload["truncation"] = {"error": str(e)}

    try:
        from app.smart_routing import get_critic_skip_stats, get_draft_latency_stats
        payload["critic_skip"] = get_critic_skip_stats()
        payload["latency"] = get_draft_latency_stats()
    except Exception as e:
        logger.debug("[admin/llm-stats] routing stats unavailable: %s", e)
        payload["critic_skip"] = {"error": str(e)}
        payload["latency"] = {}

    try:
        from app.infrastructure.token_usage_writer import get_writer_stats
        payload["token_writer"] = get_writer_stats()
    except Exception as e:
        logger.debug("[admin/llm-stats] writer stats unavailable: %s", e)
        payload["token_writer"] = {"error": str(e)}

    # Cost by agent (last N days) — falls back to {} if the table doesn't
    # exist yet (migration 021 not applied) or the SQL session is borked.
    try:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        from app.db.database import get_db_session
        from app.db.repositories.token_usage_log_repository import (
            TokenUsageLogRepository,
        )

        cutoff = _dt.now(_tz.utc) - _td(days=days)
        with get_db_session() as session:
            repo = TokenUsageLogRepository(session)
            payload["cost_by_agent"] = repo.cost_by_agent(since=cutoff)
            full_cost_by_account = repo.cost_by_account(since=cutoff)
            full_cost_by_user = repo.cost_by_user(since=cutoff)
            total_usage = repo.total_usage(since=cutoff)
            payload["cost_by_account"] = full_cost_by_account[:50]
            payload["cost_by_user"] = full_cost_by_user[:50]
            payload["daily_cost"] = repo.daily_cost(days=days)
            active_users = len(full_cost_by_user)
            total_spend = total_usage["cost_usd"]
            payload["active_accounts"] = len(full_cost_by_account)
            payload["active_users"] = active_users
            payload["mau"] = active_users
            payload["total_spend_usd"] = total_spend
            payload["token_calls"] = total_usage["calls"]
            payload["total_tokens"] = total_usage["total_tokens"]
            payload["cost_per_mau"] = round(total_spend / active_users, 4) if active_users > 0 else 0.0
            if _table_exists("stripe_usage_meter_events"):
                from sqlalchemy import func, select
                from app.billing.usage_metering import UsageMeteringConfig
                from app.db.models import StripeUsageMeterEvent

                credit_price = float(UsageMeteringConfig.from_env().credit_price_usd)
                sent_credits, event_count = session.execute(
                    select(
                        func.sum(StripeUsageMeterEvent.metered_credits),
                        func.count(StripeUsageMeterEvent.id),
                    )
                    .where(StripeUsageMeterEvent.created_at >= cutoff.replace(tzinfo=None))
                    .where(StripeUsageMeterEvent.status == "sent")
                ).one()
                payload["stripe_usage_metering"] = {
                    "sent_credits": int(sent_credits or 0),
                    "sent_revenue_usd": round(int(sent_credits or 0) * credit_price, 2),
                    "sent_events": int(event_count or 0),
                }
            else:
                payload["stripe_usage_metering"] = {
                    "sent_credits": 0,
                    "sent_revenue_usd": 0.0,
                    "sent_events": 0,
                }
        payload["window_days"] = days
    except Exception as e:
        logger.debug("[admin/llm-stats] cost rollup unavailable: %s", e)
        payload["cost_by_agent"] = {}
        payload["cost_by_account"] = []
        payload["cost_by_user"] = []
        payload["daily_cost"] = []
        payload["active_accounts"] = 0
        payload["active_users"] = 0
        payload["mau"] = 0
        payload["total_spend_usd"] = 0.0
        payload["token_calls"] = 0
        payload["total_tokens"] = 0
        payload["cost_per_mau"] = 0.0
        payload["stripe_usage_metering"] = {
            "sent_credits": 0,
            "sent_revenue_usd": 0.0,
            "sent_events": 0,
        }

    return jsonify(payload)


@admin_bp.route("/cost-cap", methods=["GET"])
@require_admin_or_token
def cost_cap():
    """Snapshot of cost-cap state for the admin dashboard.

    Returns enforcement on/off, the configured global+per-user caps,
    current global month spend, and the top-10 spenders today. The
    dashboard "Budget" card reads from this single endpoint.

    Reads are cached by ``cost_enforcer`` (60 s TTL) so hammering the
    endpoint won't 10x DB QPS.
    """
    payload: dict = {}
    try:
        from app.infrastructure import cost_enforcer as ce

        global_status = ce.get_global_monthly_status()
        payload["enforcement_enabled"] = ce._is_enforcement_enabled()
        payload["global_monthly"] = {
            "cap_usd": global_status.cap_usd,
            "current_usd": global_status.current_usd,
            "pct": round(global_status.pct, 4),
            "hard_block": global_status.hard_block,
            "soft_warn": global_status.soft_warn,
        }
        payload["user_daily_cap_usd"] = ce._user_daily_cap_usd()
        payload["warn_pct"] = ce._warn_pct()
        payload["top_spenders_today"] = ce.get_top_spenders_today(limit=10)
    except Exception as e:
        logger.debug("[admin/cost-cap] snapshot failed: %s", e)
        payload = {"error": str(e), "enforcement_enabled": False}
    return jsonify(payload)


@admin_bp.route("/draft-feedback", methods=["GET"])
@require_admin_or_token
def draft_feedback_summary():
    """Aggregate user verdicts (accept / edit / reject) for the dashboard.

    Returns global counts + per-account top-rejection list. The
    ``avg_edit_distance`` is the mean over rows with action='edit' and
    a non-null edit_distance (used by the future Critic-threshold tuner
    to flag accounts where users systematically heavy-edit).
    """
    payload: dict = {}
    try:
        from app.db.database import get_db_session
        from app.db.models.draft_feedback import DraftFeedbackRecord
        from sqlalchemy import func, select

        with get_db_session() as session:
            # Global counts across all accounts.
            stmt = (
                select(
                    DraftFeedbackRecord.action,
                    func.count(DraftFeedbackRecord.id),
                )
                .group_by(DraftFeedbackRecord.action)
            )
            counts = {a: int(c or 0) for a, c in session.execute(stmt).all()}

            # Global mean edit_distance across edit rows.
            edit_avg_stmt = (
                select(func.avg(DraftFeedbackRecord.edit_distance))
                .where(DraftFeedbackRecord.action == "edit")
                .where(DraftFeedbackRecord.edit_distance.isnot(None))
            )
            edit_avg = session.execute(edit_avg_stmt).scalar()

            # Top-rejecting accounts (last 30d).
            from datetime import datetime as _dt, timedelta as _td, timezone as _tz
            cutoff = _dt.now(_tz.utc) - _td(days=30)
            top_stmt = (
                select(
                    DraftFeedbackRecord.account_id,
                    func.count(DraftFeedbackRecord.id),
                )
                .where(DraftFeedbackRecord.action == "reject")
                .where(DraftFeedbackRecord.created_at >= cutoff)
                .group_by(DraftFeedbackRecord.account_id)
                .order_by(func.count(DraftFeedbackRecord.id).desc())
                .limit(20)
            )
            top_rejecters = [
                {"account_id": int(aid), "rejects": int(c or 0)}
                for aid, c in session.execute(top_stmt).all()
            ]

        total = sum(counts.values()) or 1
        payload = {
            "counts": counts,
            "total": total,
            "rates": {a: round(v / total, 4) for a, v in counts.items()},
            "avg_edit_distance": (
                round(float(edit_avg), 4) if edit_avg is not None else None
            ),
            "top_rejecters_30d": top_rejecters,
        }
    except Exception as e:
        logger.debug("[admin/draft-feedback] aggregate failed: %s", e)
        payload = {"error": str(e), "counts": {}, "total": 0}

    return jsonify(payload)


# ============================================================================
# INSTRUMENTATION HELPER
# ============================================================================

def record_user_activity(email: str, action: str, metadata: dict = None):
    """Enregistre une action utilisateur pour les analytics admin."""
    if not email:
        return
    try:
        from app.infrastructure.database import db
        db.execute(
            "INSERT INTO user_activity (user_email, action, metadata, created_at) VALUES (?, ?, ?, ?)",
            (email.lower(), action, json.dumps(metadata) if metadata else None,
             datetime.now(timezone.utc).isoformat())
        )
        db.commit()
    except Exception as e:
        logger.debug(f"[ADMIN] Erreur enregistrement activité: {e}")
