"""SQLAlchemy models for the bulk-action queue.

The actual hot-path queries (claim_next_pending, atomic counter bumps)
go through raw SQL in `app/services/bulk_jobs/repository.py` to use
SQLite's `UPDATE … RETURNING` for race-free claims. These ORM models
exist so the schema stays declarative + visible in `init_db` and so
list/read endpoints can use familiar `session.scalars(...)` patterns.
"""

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


# Job lifecycle states. Kept as plain strings so SQLite migrations stay
# trivial; validation lives in the repository layer.
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_PAUSED = "paused"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELLED = "cancelled"
JOB_STATUSES_TERMINAL = frozenset(
    {JOB_STATUS_COMPLETED, JOB_STATUS_FAILED, JOB_STATUS_CANCELLED}
)
JOB_STATUSES_ACTIVE = frozenset(
    {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, JOB_STATUS_PAUSED}
)

# Per-item states.
ITEM_STATE_PENDING = "pending"
ITEM_STATE_IN_PROGRESS = "in_progress"
ITEM_STATE_SUCCEEDED = "succeeded"
ITEM_STATE_FAILED = "failed"
ITEM_STATE_SKIPPED = "skipped"

# Job sources (free-form but enumerated for log clarity).
JOB_SOURCE_MANUAL = "manual"
JOB_SOURCE_API = "api"
JOB_SOURCE_AUTO_DELETION = "auto_deletion"

# Job types — must match dispatch table in worker._execute_op.
JOB_TYPE_MARK_READ = "mark_read"
JOB_TYPE_MARK_UNREAD = "mark_unread"
JOB_TYPE_ARCHIVE = "archive"
JOB_TYPE_MOVE_TO_TRASH = "move_to_trash"
JOB_TYPE_RESTORE_FROM_TRASH = "restore_from_trash"
JOB_TYPE_MOVE_TO_INBOX = "move_to_inbox"
JOB_TYPE_ADD_LABEL = "add_label"
# Permanent removal (no trash). Used by empty-trash, empty-spam, and the
# auto-deletion scheduler. Idempotent across retries because providers
# return 404 on an already-deleted ID, which the worker maps to skipped.
JOB_TYPE_DELETE_FOREVER = "delete_forever"
JOB_TYPES_KNOWN = frozenset(
    {
        JOB_TYPE_MARK_READ,
        JOB_TYPE_MARK_UNREAD,
        JOB_TYPE_ARCHIVE,
        JOB_TYPE_MOVE_TO_TRASH,
        JOB_TYPE_RESTORE_FROM_TRASH,
        JOB_TYPE_MOVE_TO_INBOX,
        JOB_TYPE_ADD_LABEL,
        JOB_TYPE_DELETE_FOREVER,
    }
)


class BulkJob(Base):
    """One user-initiated or scheduled bulk email operation."""

    __tablename__ = "bulk_jobs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    target_total: Mapped[int] = mapped_column(Integer, nullable=False)
    succeeded_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    params_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index(
            "ix_bulk_jobs_user_status_created",
            "user_id",
            "status",
            "created_at",
        ),
        Index("ix_bulk_jobs_account_status", "account_id", "status"),
    )


class BulkJobItem(Base):
    """One per-message work unit inside a BulkJob."""

    __tablename__ = "bulk_job_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("bulk_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_msg_id: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("ix_bulk_job_items_job_state", "job_id", "state"),
        Index(
            "ix_bulk_job_items_pending",
            "job_id",
            "id",
            sqlite_where=text("state = 'pending'"),
            postgresql_where=text("state = 'pending'"),
        ),
    )
