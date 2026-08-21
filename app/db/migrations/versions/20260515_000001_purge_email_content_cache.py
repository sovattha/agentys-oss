"""Purge persisted email-derived content caches.

Revision ID: 030_purge_email_content_cache
Revises: 029_add_provider_quota_windows
Create Date: 2026-05-15 00:00:01
"""
import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "030_purge_email_content_cache"
down_revision: Union[str, None] = "029_add_provider_quota_windows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BATCH_SIZE = 5_000
_ALLOWED_RELATION_TYPES = {
    "client",
    "colleague",
    "manager",
    "friend",
    "vendor",
    "prospect",
    "other",
}
_ALLOWED_TONES = {"formal", "semi_formal", "casual", "very_casual"}
_ALLOWED_LANGUAGES = {"fr", "en", "es", "de", "it", "pt", "other"}


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _has_email_content_columns(bind) -> bool:
    if "emails" not in _table_names(bind):
        return False
    columns = {column["name"] for column in sa.inspect(bind).get_columns("emails")}
    return {"body_text", "body_html", "snippet"}.issubset(columns)


def _has_draft_history_content_columns(bind) -> bool:
    if "draft_history" not in _table_names(bind):
        return False
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("draft_history")
    }
    return {"email_body", "draft_v1", "critique", "draft_final"}.issubset(columns)


def _has_draft_free_text_columns(bind) -> bool:
    if "drafts" not in _table_names(bind):
        return False
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("drafts")
    }
    return {"generation_prompt", "user_edits", "feedback_notes"}.issubset(columns)


def _has_learned_pattern_examples_column(bind) -> bool:
    if "learned_patterns" not in _table_names(bind):
        return False
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("learned_patterns")
    }
    return "examples" in columns


def _has_sent_emails_body_preview_column(bind) -> bool:
    if "sent_emails" not in _table_names(bind):
        return False
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("sent_emails")
    }
    return "body_preview" in columns


def _has_contact_summary_column(bind) -> bool:
    if "contacts" not in _table_names(bind):
        return False
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("contacts")
    }
    return "summary_json" in columns


def _minimize_contact_summary(summary: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(summary, dict):
        return {}

    minimized: dict[str, str] = {}

    relation = str(summary.get("relation_type") or "").lower().strip()
    if relation in _ALLOWED_RELATION_TYPES:
        minimized["relation_type"] = relation

    tone = str(summary.get("habitual_tone") or "").lower().strip()
    if tone in _ALLOWED_TONES:
        minimized["habitual_tone"] = tone

    language = str(summary.get("language") or "").lower().strip()
    if language in _ALLOWED_LANGUAGES:
        minimized["language"] = language

    return minimized


def _minimize_contact_summary_json(summary_json: str | None) -> str:
    if not summary_json:
        return "{}"
    try:
        parsed = json.loads(summary_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "{}"
    return json.dumps(
        _minimize_contact_summary(parsed),
        ensure_ascii=False,
        sort_keys=True,
    )


def _purge_email_content_postgres(bind, batch_size: int = _BATCH_SIZE) -> int:
    total = 0
    while True:
        rows = bind.execute(
            sa.text(
                """
                WITH batch AS (
                    SELECT id
                    FROM emails
                    WHERE body_text IS NOT NULL
                       OR body_html IS NOT NULL
                       OR snippet IS NOT NULL
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE emails AS e
                SET body_text = NULL,
                    body_html = NULL,
                    snippet = NULL
                FROM batch
                WHERE e.id = batch.id
                RETURNING e.id
                """
            ),
            {"batch_size": batch_size},
        ).fetchall()
        count = len(rows)
        total += count
        if count == 0:
            return total


def _purge_email_content_generic(bind, batch_size: int = _BATCH_SIZE) -> int:
    total = 0
    while True:
        ids = [
            int(row[0])
            for row in bind.execute(
                sa.text(
                    """
                    SELECT id
                    FROM emails
                    WHERE body_text IS NOT NULL
                       OR body_html IS NOT NULL
                       OR snippet IS NOT NULL
                    LIMIT :batch_size
                    """
                ),
                {"batch_size": batch_size},
            )
        ]
        if not ids:
            return total

        id_list = ",".join(str(row_id) for row_id in ids)
        bind.execute(
            sa.text(
                f"""
                UPDATE emails
                SET body_text = NULL,
                    body_html = NULL,
                    snippet = NULL
                WHERE id IN ({id_list})
                """
            )
        )
        total += len(ids)


def _purge_email_content(bind, batch_size: int = _BATCH_SIZE) -> int:
    if not _has_email_content_columns(bind):
        return 0
    if bind.dialect.name == "postgresql":
        return _purge_email_content_postgres(bind, batch_size=batch_size)
    return _purge_email_content_generic(bind, batch_size=batch_size)


def _purge_draft_history_content_postgres(bind, batch_size: int = _BATCH_SIZE) -> int:
    total = 0
    while True:
        rows = bind.execute(
            sa.text(
                """
                WITH batch AS (
                    SELECT id
                    FROM draft_history
                    WHERE email_body IS NOT NULL
                       OR draft_v1 IS NOT NULL
                       OR critique IS NOT NULL
                       OR draft_final IS NOT NULL
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE draft_history AS d
                SET email_body = NULL,
                    draft_v1 = NULL,
                    critique = NULL,
                    draft_final = NULL
                FROM batch
                WHERE d.id = batch.id
                RETURNING d.id
                """
            ),
            {"batch_size": batch_size},
        ).fetchall()
        count = len(rows)
        total += count
        if count == 0:
            return total


def _purge_draft_history_content_generic(bind, batch_size: int = _BATCH_SIZE) -> int:
    total = 0
    while True:
        ids = [
            int(row[0])
            for row in bind.execute(
                sa.text(
                    """
                    SELECT id
                    FROM draft_history
                    WHERE email_body IS NOT NULL
                       OR draft_v1 IS NOT NULL
                       OR critique IS NOT NULL
                       OR draft_final IS NOT NULL
                    LIMIT :batch_size
                    """
                ),
                {"batch_size": batch_size},
            )
        ]
        if not ids:
            return total

        id_list = ",".join(str(row_id) for row_id in ids)
        bind.execute(
            sa.text(
                f"""
                UPDATE draft_history
                SET email_body = NULL,
                    draft_v1 = NULL,
                    critique = NULL,
                    draft_final = NULL
                WHERE id IN ({id_list})
                """
            )
        )
        total += len(ids)


def _purge_draft_history_content(bind, batch_size: int = _BATCH_SIZE) -> int:
    if not _has_draft_history_content_columns(bind):
        return 0
    if bind.dialect.name == "postgresql":
        return _purge_draft_history_content_postgres(bind, batch_size=batch_size)
    return _purge_draft_history_content_generic(bind, batch_size=batch_size)


def _purge_draft_free_text_content(bind) -> int:
    if not _has_draft_free_text_columns(bind):
        return 0
    result = bind.execute(
        sa.text(
            """
            UPDATE drafts
            SET generation_prompt = NULL,
                user_edits = NULL,
                feedback_notes = NULL
            WHERE generation_prompt IS NOT NULL
               OR user_edits IS NOT NULL
               OR feedback_notes IS NOT NULL
            """
        )
    )
    return int(result.rowcount or 0)


def _purge_learned_pattern_examples(bind) -> int:
    if not _has_learned_pattern_examples_column(bind):
        return 0
    result = bind.execute(
        sa.text(
            """
            UPDATE learned_patterns
            SET examples = '[]'
            WHERE examples IS NOT NULL
              AND examples != '[]'
            """
        )
    )
    return int(result.rowcount or 0)


def _purge_sent_email_body_previews(bind) -> int:
    if not _has_sent_emails_body_preview_column(bind):
        return 0
    result = bind.execute(
        sa.text(
            """
            UPDATE sent_emails
            SET body_preview = NULL
            WHERE body_preview IS NOT NULL
              AND body_preview != ''
            """
        )
    )
    return int(result.rowcount or 0)


def _purge_contact_summary_content(bind, batch_size: int = _BATCH_SIZE) -> int:
    if not _has_contact_summary_column(bind):
        return 0

    total = 0
    last_id = 0
    while True:
        rows = bind.execute(
            sa.text(
                """
                SELECT id, summary_json
                FROM contacts
                WHERE id > :last_id
                  AND summary_json IS NOT NULL
                  AND summary_json != ''
                ORDER BY id
                LIMIT :batch_size
                """
            ),
            {"last_id": last_id, "batch_size": batch_size},
        ).fetchall()
        if not rows:
            return total

        for row_id, summary_json in rows:
            last_id = int(row_id)
            minimized = _minimize_contact_summary_json(summary_json)
            if minimized == summary_json:
                continue
            bind.execute(
                sa.text(
                    """
                    UPDATE contacts
                    SET summary_json = :summary_json
                    WHERE id = :id
                    """
                ),
                {"summary_json": minimized, "id": row_id},
            )
            total += 1


def _sqlite_fts_exists(bind) -> bool:
    if bind.dialect.name != "sqlite":
        return False
    row = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'emails_fts'
            LIMIT 1
            """
        )
    ).first()
    return row is not None


def _rebuild_sqlite_email_fts(bind) -> None:
    if _sqlite_fts_exists(bind):
        bind.execute(sa.text("INSERT INTO emails_fts(emails_fts) VALUES('rebuild')"))


def upgrade() -> None:
    bind = op.get_bind()
    _purge_email_content(bind)
    _purge_draft_history_content(bind)
    _purge_draft_free_text_content(bind)
    _purge_learned_pattern_examples(bind)
    _purge_sent_email_body_previews(bind)
    _purge_contact_summary_content(bind)
    _rebuild_sqlite_email_fts(bind)


def downgrade() -> None:
    # Irreversible by design: purged email content must not be restored from a
    # database migration. The provider remains the source of truth.
    return
