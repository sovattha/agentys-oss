"""Repair Alembic schema contract for fresh databases.

Revision ID: 032_schema_contract
Revises: 031_token_usage_context
Create Date: 2026-05-30 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "032_schema_contract"
down_revision: Union[str, None] = "031_token_usage_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _table_exists(table_name: str) -> bool:
    return table_name in _table_names()


def _columns(table_name: str) -> set[str]:
    if not _table_exists(table_name):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    if not _table_exists(table_name):
        return set()
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(
    name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if name in _indexes(table_name):
        return
    op.create_index(name, table_name, columns, unique=unique)


def _drop_index_if_present(name: str, table_name: str) -> None:
    if name not in _indexes(table_name):
        return
    op.drop_index(name, table_name=table_name)


def _alter_type(
    table_name: str,
    column_name: str,
    type_: sa.types.TypeEngine,
    *,
    existing_type: sa.types.TypeEngine,
    existing_nullable: bool,
) -> None:
    if column_name not in _columns(table_name):
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=existing_type,
            type_=type_,
            existing_nullable=existing_nullable,
        )


def _create_missing_orm_tables() -> None:
    if not _table_exists("scheduler_heartbeats"):
        op.create_table(
            "scheduler_heartbeats",
            sa.Column("name", sa.String(length=128), primary_key=True, nullable=False),
            sa.Column("last_run_at", sa.DateTime(), nullable=False),
            sa.Column("last_status", sa.String(length=32), nullable=False),
            sa.Column("expected_interval_seconds", sa.Integer(), nullable=False),
        )

    if not _table_exists("faq_agent_logs"):
        op.create_table(
            "faq_agent_logs",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column(
                "account_id",
                sa.Integer(),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("email_id", sa.String(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("matched_entry_id", sa.String(), nullable=True),
            sa.Column("matched_entry_title", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_faq_agent_logs_account_id", "faq_agent_logs", ["account_id"])

    if not _table_exists("knowledge_entries"):
        op.create_table(
            "knowledge_entries",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column(
                "account_id",
                sa.Integer(),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("category", sa.String(), nullable=False, server_default="GENERAL"),
            sa.Column("source", sa.String(), nullable=False, server_default="manual"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_knowledge_entries_account_id", "knowledge_entries", ["account_id"])
        op.create_index("ix_knowledge_entries_category", "knowledge_entries", ["category"])

    if not _table_exists("pending_actions"):
        op.create_table(
            "pending_actions",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column(
                "account_id",
                sa.Integer(),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action_type", sa.String(length=50), nullable=False),
            sa.Column("email_id", sa.String(length=255), nullable=False),
            sa.Column("payload", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_pending_actions_account_id", "pending_actions", ["account_id"])
        op.create_index("ix_pending_actions_email_id", "pending_actions", ["email_id"])
        op.create_index("ix_pending_actions_status", "pending_actions", ["status"])
        op.create_index(
            "ix_pending_actions_account_status",
            "pending_actions",
            ["account_id", "status"],
        )
        op.create_index(
            "ix_pending_actions_status_created",
            "pending_actions",
            ["status", "created_at"],
        )

    if not _table_exists("relationship_overrides"):
        op.create_table(
            "relationship_overrides",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "account_id",
                sa.Integer(),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("contact_email", sa.String(length=255), nullable=False),
            sa.Column("relationship_type", sa.String(length=50), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "account_id",
                "contact_email",
                name="uq_account_contact_relationship",
            ),
        )
        op.create_index(
            "ix_relationship_override_account_contact",
            "relationship_overrides",
            ["account_id", "contact_email"],
        )
        op.create_index(
            "ix_relationship_overrides_account_id",
            "relationship_overrides",
            ["account_id"],
        )


def upgrade() -> None:
    _create_missing_orm_tables()

    if "preferred_language" not in _columns("accounts"):
        op.add_column(
            "accounts",
            sa.Column(
                "preferred_language",
                sa.String(length=10),
                nullable=False,
                server_default="fr",
            ),
        )

    _alter_type(
        "accounts",
        "access_token",
        sa.Text(),
        existing_type=sa.String(length=2048),
        existing_nullable=True,
    )
    _alter_type(
        "accounts",
        "refresh_token",
        sa.Text(),
        existing_type=sa.String(length=2048),
        existing_nullable=True,
    )
    _alter_type(
        "accounts",
        "signature_html",
        sa.Text(),
        existing_type=sa.String(length=8192),
        existing_nullable=True,
    )
    _alter_type(
        "accounts",
        "user_id",
        sa.BigInteger(),
        existing_type=sa.Integer(),
        existing_nullable=True,
    )
    _alter_type(
        "bulk_jobs",
        "user_id",
        sa.BigInteger(),
        existing_type=sa.Integer(),
        existing_nullable=True,
    )
    _alter_type(
        "contacts",
        "email",
        sa.String(length=1024),
        existing_type=sa.String(length=255),
        existing_nullable=False,
    )
    _create_index_if_missing("ix_contacts_name", "contacts", ["name"])
    _create_index_if_missing(
        "ix_contacts_account_emailcount",
        "contacts",
        ["account_id", "email_count"],
    )
    _create_index_if_missing(
        "ix_contacts_account_lastcontacted",
        "contacts",
        ["account_id", "last_contacted_at"],
    )
    _create_index_if_missing(
        "ix_drafts_account_status_created",
        "drafts",
        ["account_id", "status", "created_at"],
    )
    _create_index_if_missing(
        "ix_drafts_account_status_updated",
        "drafts",
        ["account_id", "status", "updated_at"],
    )
    _alter_type(
        "emails",
        "sender",
        sa.String(length=1024),
        existing_type=sa.String(length=255),
        existing_nullable=False,
    )
    for index_name, columns in (
        ("ix_emails_sender_account_date", ["sender", "account_id", "date"]),
        ("ix_emails_thread_account_date", ["thread_id", "account_id", "date"]),
        ("ix_emails_account_read_date", ["account_id", "is_read", "date"]),
        ("ix_emails_account_starred_date", ["account_id", "is_starred", "date"]),
        ("ix_emails_account_folder_date", ["account_id", "folder", "date"]),
        ("ix_emails_recipients", ["recipients"]),
        ("ix_emails_is_sent_recipients", ["is_sent", "recipients"]),
    ):
        _create_index_if_missing(index_name, "emails", columns)

    for column_name in (
        "user_id",
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        _alter_type(
            "token_usage_log",
            column_name,
            sa.BigInteger(),
            existing_type=sa.Integer(),
            existing_nullable=column_name == "user_id",
        )
    _drop_index_if_present("ix_token_usage_log_account_id", "token_usage_log")
    _drop_index_if_present("ix_token_usage_log_agent", "token_usage_log")

    if "emails_analysed" in _columns("onboarding_results"):
        op.execute(
            sa.text("UPDATE onboarding_results SET emails_analysed = 0 WHERE emails_analysed IS NULL")
        )
        with op.batch_alter_table("onboarding_results") as batch_op:
            batch_op.alter_column(
                "emails_analysed",
                existing_type=sa.Integer(),
                existing_nullable=True,
                nullable=False,
            )


def downgrade() -> None:
    for column_name in (
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "output_tokens",
        "input_tokens",
        "user_id",
    ):
        _alter_type(
            "token_usage_log",
            column_name,
            sa.Integer(),
            existing_type=sa.BigInteger(),
            existing_nullable=column_name == "user_id",
        )
    _alter_type(
        "emails",
        "sender",
        sa.String(length=255),
        existing_type=sa.String(length=1024),
        existing_nullable=False,
    )
    _alter_type(
        "contacts",
        "email",
        sa.String(length=255),
        existing_type=sa.String(length=1024),
        existing_nullable=False,
    )
    _alter_type(
        "bulk_jobs",
        "user_id",
        sa.Integer(),
        existing_type=sa.BigInteger(),
        existing_nullable=True,
    )
    _alter_type(
        "accounts",
        "user_id",
        sa.Integer(),
        existing_type=sa.BigInteger(),
        existing_nullable=True,
    )
    if "preferred_language" in _columns("accounts"):
        op.drop_column("accounts", "preferred_language")

    for table_name in (
        "relationship_overrides",
        "pending_actions",
        "knowledge_entries",
        "faq_agent_logs",
        "scheduler_heartbeats",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)
