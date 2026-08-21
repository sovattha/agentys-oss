"""Initial database schema with Account, Email, Contact, Draft tables.

Revision ID: 001_initial
Revises:
Create Date: 2026-01-18 00:00:01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create accounts table
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("access_token", sa.String(length=2048), nullable=True),
        sa.Column("refresh_token", sa.String(length=2048), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounts_email", "accounts", ["email"], unique=True)

    # Create emails table
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_id", sa.String(length=255), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=1000), nullable=True),
        sa.Column("sender", sa.String(length=255), nullable=False),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("recipients", sa.Text(), nullable=True),
        sa.Column("cc", sa.Text(), nullable=True),
        sa.Column("bcc", sa.Text(), nullable=True),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("snippet", sa.String(length=500), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, default=False),
        sa.Column("is_starred", sa.Boolean(), nullable=False, default=False),
        sa.Column("is_draft", sa.Boolean(), nullable=False, default=False),
        sa.Column("is_sent", sa.Boolean(), nullable=False, default=False),
        sa.Column("labels", sa.Text(), nullable=True),
        sa.Column("folder", sa.String(length=255), nullable=True),
        sa.Column("attachments_meta", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_emails_email_id", "emails", ["email_id"], unique=True)
    op.create_index("ix_emails_thread_id", "emails", ["thread_id"], unique=False)
    op.create_index("ix_emails_account_id", "emails", ["account_id"], unique=False)
    op.create_index("ix_emails_sender", "emails", ["sender"], unique=False)
    op.create_index("ix_emails_date", "emails", ["date"], unique=False)
    op.create_index("ix_emails_account_date", "emails", ["account_id", "date"], unique=False)
    op.create_index("ix_emails_account_read", "emails", ["account_id", "is_read"], unique=False)

    # Create contacts table
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("email_count", sa.Integer(), nullable=False, default=0),
        sa.Column("sent_count", sa.Integer(), nullable=False, default=0),
        sa.Column("received_count", sa.Integer(), nullable=False, default=0),
        sa.Column("last_contacted_at", sa.DateTime(), nullable=True),
        sa.Column("first_contacted_at", sa.DateTime(), nullable=True),
        sa.Column("relationship_strength", sa.Integer(), nullable=True),
        sa.Column("detected_tone", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_account_id", "contacts", ["account_id"], unique=False)
    op.create_index("ix_contacts_email", "contacts", ["email"], unique=False)
    op.create_index("ix_contacts_account_email", "contacts", ["account_id", "email"], unique=True)

    # Create drafts table
    op.create_table(
        "drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("original_email_id", sa.Integer(), nullable=True),
        sa.Column("subject", sa.String(length=1000), nullable=True),
        sa.Column("recipients", sa.Text(), nullable=True),
        sa.Column("cc", sa.Text(), nullable=True),
        sa.Column("bcc", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, default="draft"),
        sa.Column("generation_prompt", sa.Text(), nullable=True),
        sa.Column("agent_model", sa.String(length=100), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=False, default=1),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("user_edits", sa.Text(), nullable=True),
        sa.Column("feedback_rating", sa.Integer(), nullable=True),
        sa.Column("feedback_notes", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("sent_email_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["original_email_id"], ["emails.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_drafts_account_id", "drafts", ["account_id"], unique=False)
    op.create_index("ix_drafts_original_email_id", "drafts", ["original_email_id"], unique=False)
    op.create_index("ix_drafts_status", "drafts", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("drafts")
    op.drop_table("contacts")
    op.drop_table("emails")
    op.drop_table("accounts")
