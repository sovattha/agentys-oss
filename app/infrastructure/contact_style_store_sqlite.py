# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
SQLite (SQLCipher) adapter for :class:`ContactStyleStorePort` — PR6 follow-up.

Per-row storage of ``ContactStyleProfile`` with primary key
``(account_id, email_lower)``. Row-level locking via SQLite transactions
replaces the global ``_FILE_LOCK`` that ``FileWritingStyleStore`` needed to
prevent JSON corruption under concurrent writes (4 onboarding agents).

The schema is created lazily on first use via ``CREATE TABLE IF NOT
EXISTS`` so callers don't need a separate migration step. The same
DB connection used by the rest of the app is reused (SQLCipher key /
``AGENTYS_ENCRYPTION_KEY`` already configured by ``app.db.database``).

PR6 status (deferred runtime adoption) — see the port docstring. This
adapter is wired into ``Container`` as additive infrastructure but
the runtime draft path still reads ``WritingStyleProfile.contact_profiles``
(the JSON dict). The senior dev review will decide when to flip.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import text

from app.db.database import get_db_session
from app.domain.entities.writing_style import ContactStyleProfile
from app.domain.ports.contact_style_store_port import ContactStyleStorePort

logger = logging.getLogger(__name__)


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS contact_styles (
    account_id          INTEGER NOT NULL,
    email_lower         TEXT    NOT NULL,
    email               TEXT    NOT NULL,
    formality_override  TEXT,
    formality_pending   TEXT,
    formality_locked    INTEGER NOT NULL DEFAULT 0,
    formality_updated_at TEXT,
    preferred_greeting  TEXT,
    preferred_closing   TEXT,
    preferred_signature TEXT,
    langue              TEXT,
    langue_variante     TEXT,
    nickname            TEXT,
    PRIMARY KEY (account_id, email_lower)
)
"""

_CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_contact_styles_account "
    "ON contact_styles(account_id)"
)


def _row_to_profile(row) -> ContactStyleProfile:
    """Hydrate a DB row into a ``ContactStyleProfile`` instance.

    Uses ``ContactStyleProfile.from_dict`` so the field-coercion logic
    (string→enum, defaults for new fields) lives in exactly one place.
    """
    return ContactStyleProfile.from_dict({
        "email": row.email,
        "formality_override": row.formality_override,
        "formality_pending": row.formality_pending,
        "formality_locked": bool(row.formality_locked),
        "formality_updated_at": row.formality_updated_at,
        "preferred_greeting": row.preferred_greeting,
        "preferred_closing": row.preferred_closing,
        "preferred_signature": getattr(row, "preferred_signature", None),
        "langue": row.langue,
        "langue_variante": row.langue_variante,
        "nickname": row.nickname,
    })


def _profile_to_params(account_id: int, profile: ContactStyleProfile) -> dict:
    """Flatten a profile into kwargs ready for the upsert statement."""
    formality_override = (
        profile.formality_override.value
        if profile.formality_override is not None
        else None
    )
    formality_pending = (
        profile.formality_pending.value
        if profile.formality_pending is not None
        else None
    )
    return {
        "account_id": account_id,
        "email_lower": profile.email.lower(),
        "email": profile.email,
        "formality_override": formality_override,
        "formality_pending": formality_pending,
        "formality_locked": 1 if profile.formality_locked else 0,
        "formality_updated_at": profile.formality_updated_at,
        "preferred_greeting": profile.preferred_greeting,
        "preferred_closing": profile.preferred_closing,
        "preferred_signature": profile.preferred_signature,
        "langue": profile.langue,
        "langue_variante": profile.langue_variante,
        "nickname": profile.nickname,
    }


_UPSERT_SQL = text("""
    INSERT INTO contact_styles (
        account_id, email_lower, email, formality_override, formality_pending,
        formality_locked, formality_updated_at, preferred_greeting,
        preferred_closing, preferred_signature, langue, langue_variante, nickname
    ) VALUES (
        :account_id, :email_lower, :email, :formality_override, :formality_pending,
        :formality_locked, :formality_updated_at, :preferred_greeting,
        :preferred_closing, :preferred_signature, :langue, :langue_variante, :nickname
    )
    ON CONFLICT(account_id, email_lower) DO UPDATE SET
        email = excluded.email,
        formality_override = excluded.formality_override,
        formality_pending = excluded.formality_pending,
        formality_locked = excluded.formality_locked,
        formality_updated_at = excluded.formality_updated_at,
        preferred_greeting = excluded.preferred_greeting,
        preferred_closing = excluded.preferred_closing,
        preferred_signature = excluded.preferred_signature,
        langue = excluded.langue,
        langue_variante = excluded.langue_variante,
        nickname = excluded.nickname
""")


class SqliteContactStyleStore(ContactStyleStorePort):
    """SQLite-backed implementation of :class:`ContactStyleStorePort`.

    Schema is auto-created on first instantiation. The same DB engine
    used by the rest of the app (SQLCipher-encrypted in prod) is reused
    via ``app.db.database.get_db_session``.
    """

    def __init__(self) -> None:
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Create the table + index if they don't exist. Idempotent.

        Failure here is logged but not raised — onboarding/draft paths must
        not be blocked by a transient DB issue. Subsequent reads will simply
        return ``None`` until the schema lands.
        """
        try:
            with get_db_session() as session:
                session.execute(text(_CREATE_TABLE_SQL))
                dialect = session.get_bind().dialect.name
                if dialect == "sqlite":
                    columns = {
                        row[1]
                        for row in session.execute(text("PRAGMA table_info(contact_styles)")).all()
                    }
                    if "preferred_signature" not in columns:
                        session.execute(
                            text("ALTER TABLE contact_styles ADD COLUMN preferred_signature TEXT")
                        )
                else:
                    session.execute(
                        text("ALTER TABLE contact_styles ADD COLUMN IF NOT EXISTS preferred_signature TEXT")
                    )
                session.execute(text(_CREATE_INDEX_SQL))
                session.commit()
        except Exception as exc:
            logger.warning(
                "Could not ensure `contact_styles` schema (will retry on next call): %s",
                exc,
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get(self, account_id: int, email: str) -> Optional[ContactStyleProfile]:
        if not email:
            return None
        with get_db_session() as session:
            row = session.execute(
                text(
                    "SELECT email, formality_override, formality_pending, "
                    "formality_locked, formality_updated_at, preferred_greeting, "
                    "preferred_closing, preferred_signature, langue, langue_variante, nickname "
                    "FROM contact_styles "
                    "WHERE account_id = :aid AND email_lower = :elow"
                ),
                {"aid": account_id, "elow": email.lower()},
            ).first()
        if row is None:
            return None
        return _row_to_profile(row)

    def upsert(self, account_id: int, profile: ContactStyleProfile) -> bool:
        if not profile.email:
            return False
        try:
            with get_db_session() as session:
                session.execute(_UPSERT_SQL, _profile_to_params(account_id, profile))
                session.commit()
            return True
        except Exception as exc:
            logger.error(
                "Failed to upsert contact_style for account=%s email=%s: %s",
                account_id, profile.email, exc,
            )
            return False

    def delete(self, account_id: int, email: str) -> bool:
        if not email:
            return False
        with get_db_session() as session:
            result = session.execute(
                text(
                    "DELETE FROM contact_styles "
                    "WHERE account_id = :aid AND email_lower = :elow"
                ),
                {"aid": account_id, "elow": email.lower()},
            )
            session.commit()
            return (result.rowcount or 0) > 0

    def list_for_account(self, account_id: int) -> List[ContactStyleProfile]:
        with get_db_session() as session:
            rows = session.execute(
                text(
                    "SELECT email, formality_override, formality_pending, "
                    "formality_locked, formality_updated_at, preferred_greeting, "
                    "preferred_closing, preferred_signature, langue, langue_variante, nickname "
                    "FROM contact_styles "
                    "WHERE account_id = :aid "
                    "ORDER BY email_lower"
                ),
                {"aid": account_id},
            ).all()
        return [_row_to_profile(r) for r in rows]

    def count_for_account(self, account_id: int) -> int:
        with get_db_session() as session:
            row = session.execute(
                text(
                    "SELECT COUNT(*) AS c FROM contact_styles "
                    "WHERE account_id = :aid"
                ),
                {"aid": account_id},
            ).first()
        return int(row.c) if row else 0

    def replace_account(
        self, account_id: int, profiles: List[ContactStyleProfile]
    ) -> int:
        """Atomic replace : delete all rows for ``account_id``, bulk-insert.

        Wrapped in a single transaction so a mid-flight error rolls back to
        the previous state. Used by the JSON→SQLite one-shot migration.
        """
        with get_db_session() as session:
            try:
                session.execute(
                    text("DELETE FROM contact_styles WHERE account_id = :aid"),
                    {"aid": account_id},
                )
                inserted = 0
                for profile in profiles:
                    if not profile.email:
                        continue
                    session.execute(
                        _UPSERT_SQL, _profile_to_params(account_id, profile)
                    )
                    inserted += 1
                session.commit()
                return inserted
            except Exception:
                session.rollback()
                raise


def migrate_json_to_sqlite(
    *,
    account_id: int,
    contact_profiles_dict: dict,
    store: ContactStyleStorePort,
) -> int:
    """One-shot helper : copy a JSON-serialized ``contact_profiles`` dict
    (the legacy field on ``WritingStyleProfile``) into the SQLite store.

    Idempotent : calling it twice with the same input produces the same
    final state because :meth:`replace_account` clears the account's rows
    before re-inserting. Returns the number of rows written.

    Intended to be called once per account at boot time (or via a
    standalone admin script). Does NOT mutate the source dict — the JSON
    file remains the source of truth until the senior dev flips the
    runtime path.
    """
    profiles: List[ContactStyleProfile] = []
    for raw in contact_profiles_dict.values():
        if not isinstance(raw, dict):
            continue
        try:
            profiles.append(ContactStyleProfile.from_dict(raw))
        except Exception as exc:
            logger.warning(
                "Skipping malformed contact entry during migration "
                "(account=%s): %s",
                account_id, exc,
            )
    return store.replace_account(account_id, profiles)
