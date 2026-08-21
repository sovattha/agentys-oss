"""Tests for the OAuth token migration script.

Behavior under test:
- Plaintext tokens are encrypted in place via Fernet.
- Already-encrypted rows are skipped (idempotent).
- NULL columns are not touched.
- The migration returns a summary `(encrypted, skipped, null)` per column.
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.models import Account
from scripts.encrypt_existing_oauth_tokens import encrypt_oauth_tokens_in_place


def _raw_token_columns(session, account_id: int) -> tuple[str | None, str | None]:
    row = session.execute(
        text("SELECT access_token, refresh_token FROM accounts WHERE id = :i"),
        {"i": account_id},
    ).one()
    return row[0], row[1]


def _insert_raw_account(
    session,
    *,
    email: str,
    access_token: str | None,
    refresh_token: str | None,
) -> int:
    """Insert an account bypassing the ORM so values land on disk verbatim."""
    from datetime import datetime

    now = datetime.utcnow()
    result = session.execute(
        text(
            "INSERT INTO accounts"
            " (email, provider, access_token, refresh_token, is_active,"
            "  signature_user_modified, preferred_language, created_at, updated_at)"
            " VALUES (:e, 'gmail', :a, :r, 1, 0, 'fr', :now, :now)"
        ),
        {"e": email, "a": access_token, "r": refresh_token, "now": now},
    )
    session.commit()
    return result.lastrowid  # type: ignore[attr-defined]


def test_encrypts_plaintext_tokens_in_place(session):
    account_id = _insert_raw_account(
        session,
        email="plain@example.com",
        access_token="ya29.plain-access",
        refresh_token="1//plain-refresh",
    )

    summary = encrypt_oauth_tokens_in_place(session)

    raw_access, raw_refresh = _raw_token_columns(session, account_id)
    assert raw_access is not None and raw_access.startswith("gAAAAA")
    assert raw_refresh is not None and raw_refresh.startswith("gAAAAA")
    assert summary.encrypted == 2
    assert summary.skipped == 0


def test_is_idempotent_on_already_encrypted_tokens(session):
    # First run encrypts.
    _insert_raw_account(
        session,
        email="already@example.com",
        access_token="ya29.first-pass",
        refresh_token=None,
    )
    first = encrypt_oauth_tokens_in_place(session)
    assert first.encrypted == 1

    # Second run is a no-op.
    second = encrypt_oauth_tokens_in_place(session)
    assert second.encrypted == 0
    assert second.skipped == 1


def test_leaves_null_tokens_untouched(session):
    account_id = _insert_raw_account(
        session,
        email="nulls@example.com",
        access_token=None,
        refresh_token=None,
    )

    summary = encrypt_oauth_tokens_in_place(session)

    raw_access, raw_refresh = _raw_token_columns(session, account_id)
    assert raw_access is None
    assert raw_refresh is None
    assert summary.encrypted == 0
    assert summary.null == 2


def test_post_migration_orm_load_yields_plaintext(session):
    account_id = _insert_raw_account(
        session,
        email="roundtrip@example.com",
        access_token="ya29.round",
        refresh_token="1//round",
    )

    encrypt_oauth_tokens_in_place(session)
    session.expire_all()

    reloaded = session.get(Account, account_id)
    assert reloaded.access_token == "ya29.round"
    assert reloaded.refresh_token == "1//round"
