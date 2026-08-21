"""
Email repository for email-specific database operations.
"""

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select, func, delete, or_

from app.db.models.email import Email
from app.db.repositories.base import BaseRepository


class EmailRepository(BaseRepository[Email]):
    """
    Repository for Email model operations.
    """

    model = Email

    def get_by_email_id(self, email_id: str, account_id: int | None = None) -> Optional[Email]:
        """
        Get email by provider's email ID, optionally scoped to an account.

        Args:
            email_id: Provider's unique message ID.
            account_id: If provided, restrict to this account (multi-user isolation).

        Returns:
            Email if found, None otherwise.
        """
        stmt = select(Email).where(Email.email_id == email_id)
        if account_id is not None:
            stmt = stmt.where(Email.account_id == account_id)
        return self.session.scalar(stmt)

    def get_by_account(
        self,
        account_id: int,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
        email_ids: set[str] | None = None,
        since_date: Optional[datetime] = None,
        exclude_email_ids: set[str] | None = None,
        skip_folder_filter: bool = False,
        include_archived: bool = False,
    ) -> Sequence[Email]:
        """
        Get emails for an account.

        Args:
            account_id: Account ID to filter by.
            limit: Maximum number of results.
            offset: Number of results to skip.
            unread_only: If True, only return unread emails.
            email_ids: If provided, only return emails with these provider IDs.
            since_date: If provided, only return emails from this date onwards.
            exclude_email_ids: If provided, exclude emails with these provider IDs.
            skip_folder_filter: If True, search all folders (not just inbox). Used for label filtering.
            include_archived: If True, also include folder='archived' rows alongside
                inbox. Used by onboarding to enrich the learning corpus with
                archived bidirectional threads. Default False preserves the
                inbox-only contract for the email list UI.

        Returns:
            List of emails ordered by date descending.
        """
        stmt = select(Email).where(
            Email.account_id == account_id,
            Email.is_sent == False,  # noqa: E712 — exclude sent emails from inbox cache
        )
        if not skip_folder_filter:
            if include_archived:
                stmt = stmt.where(or_(
                    Email.folder == "inbox",
                    Email.folder == "archived",
                    Email.folder.is_(None),
                ))
            else:
                stmt = stmt.where(or_(Email.folder == "inbox", Email.folder.is_(None)))

        if unread_only:
            stmt = stmt.where(Email.is_read == False)  # noqa: E712

        if email_ids is not None:
            stmt = stmt.where(Email.email_id.in_(email_ids))

        if exclude_email_ids:
            stmt = stmt.where(Email.email_id.notin_(exclude_email_ids))

        if since_date is not None:
            stmt = stmt.where(Email.date >= since_date)

        stmt = stmt.order_by(Email.date.desc()).limit(limit).offset(offset)
        return self.session.scalars(stmt).all()

    def get_sent_emails(
        self,
        account_id: int,
        limit: int = 50,
        offset: int = 0,
        max_age_seconds: int | None = None,
        since_date: Optional[datetime] = None,
    ) -> Sequence[Email]:
        """Get sent emails for an account (is_sent=True), ordered by date desc.

        Args:
            max_age_seconds: If set, only return rows whose created_at is within
                             this many seconds. Stale rows → cache miss → provider re-fetch.
            since_date: If set, only return emails from this date onwards.
        """
        from datetime import timedelta
        stmt = (
            select(Email)
            .where(Email.account_id == account_id, Email.is_sent == True)  # noqa: E712
        )
        if max_age_seconds is not None:
            cutoff = datetime.utcnow() - timedelta(seconds=max_age_seconds)
            stmt = stmt.where(Email.created_at >= cutoff)
        if since_date is not None:
            stmt = stmt.where(Email.date >= since_date)
        stmt = stmt.order_by(Email.date.desc()).limit(limit).offset(offset)
        return self.session.scalars(stmt).all()

    def get_sent_by_subject_prefix(
        self,
        account_id: int,
        prefix: str,
        limit: int = 100,
    ) -> Sequence[Email]:
        """Get sent emails whose subject contains the given prefix."""
        stmt = (
            select(Email)
            .where(
                Email.account_id == account_id,
                Email.is_sent == True,  # noqa: E712
                Email.subject.ilike(f"%{prefix}%"),
            )
            .order_by(Email.date.desc())
            .limit(limit)
        )
        return self.session.scalars(stmt).all()

    def delete_by_is_sent(self, account_id: int) -> int:
        """Delete all cached sent emails for an account. Forces fresh fetch after send."""
        stmt = delete(Email).where(
            Email.account_id == account_id,
            Email.is_sent == True,  # noqa: E712
        )
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    def dedupe_sent_by_content(self, account_id: int) -> int:
        """Collapse duplicate is_sent=True rows that represent the same logical send.

        Two rows are treated as the same logical email when they share
        ``(subject, recipients, date-minute)`` on the same account. Causes :

        - Synthetic ``compose-<ts>`` placeholder written at send-time vs. the
          real provider row arriving via ``_refresh_sent_cache_bg`` — both
          survive when the refresh races a DB-lock.
        - Provider returns the same message twice (Gmail label propagation,
          Outlook ``conversationId`` echo, IMAP UID re-issue).

        Preference order for which row to keep :
        1. Real provider ``email_id`` (NOT starting with ``compose-``).
        2. Most recent ``created_at`` (the freshest sync).

        Returns the number of rows deleted.
        """
        from collections import defaultdict

        rows = self.session.execute(
            select(
                Email.id, Email.email_id, Email.subject,
                Email.recipients, Email.date, Email.created_at,
            )
            .where(Email.account_id == account_id, Email.is_sent == True)  # noqa: E712
        ).all()

        groups: dict[tuple, list] = defaultdict(list)
        for r in rows:
            if not r.date:
                # Without a date we can't group safely — keep the row.
                continue
            minute = r.date.replace(second=0, microsecond=0)
            key = (
                (r.subject or "").strip().lower(),
                (r.recipients or "").strip().lower(),
                minute,
            )
            groups[key].append(r)

        to_delete: list[int] = []
        for group in groups.values():
            if len(group) <= 1:
                continue
            # Sort: real provider id first (synthetic compose-/reply- last),
            # then by created_at desc so the freshest real row wins.
            group.sort(
                key=lambda r: (
                    (r.email_id or "").startswith(("compose-", "reply-")),
                    -(r.created_at.timestamp() if r.created_at else 0),
                )
            )
            # Keep group[0], delete the rest.
            to_delete.extend(r.id for r in group[1:])

        if to_delete:
            self.session.execute(delete(Email).where(Email.id.in_(to_delete)))
            self.session.flush()
        return len(to_delete)

    def delete_by_folder(self, account_id: int, folder: str) -> int:
        """Delete all cached emails for an account+folder. Forces fresh fetch."""
        stmt = delete(Email).where(
            Email.account_id == account_id,
            Email.folder == folder,
        )
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    def get_by_folder(
        self,
        account_id: int,
        folder: str,
        limit: int = 50,
        offset: int = 0,
        max_age_seconds: int | None = None,
    ) -> Sequence[Email]:
        """Get emails for a specific folder (trash, archived, spam) by folder column."""
        from datetime import timedelta
        stmt = (
            select(Email)
            .where(Email.account_id == account_id, Email.folder == folder)
        )
        if max_age_seconds is not None:
            cutoff = datetime.utcnow() - timedelta(seconds=max_age_seconds)
            stmt = stmt.where(Email.created_at >= cutoff)
        stmt = stmt.order_by(Email.date.desc()).limit(limit).offset(offset)
        return self.session.scalars(stmt).all()

    def get_by_thread(self, thread_id: str, account_id: int) -> Sequence[Email]:
        """
        Get all emails in a thread, hiding synthetic placeholders that have
        been superseded by a real provider row.

        Synthetic rows use ``email_id`` prefixed by ``compose-`` or ``reply-``
        and are written at send-time so the user sees their just-sent message
        in the Sent folder before the provider's IMAP/Graph sync catches up.
        Once the real row arrives we'd otherwise show both copies in the
        thread view, doubling the badge count.

        Rule : drop synthetic rows whose ``(subject, recipients, date-minute)``
        matches at least one real row. Synthetic rows with no real counterpart
        survive — that's the window between send and the first refresh, and
        the user needs to see their message somewhere.

        Args:
            thread_id: Thread ID to filter by.
            account_id: Account ID to filter by.

        Returns:
            List of emails in the thread ordered by date asc.
        """
        stmt = (
            select(Email)
            .where(Email.thread_id == thread_id, Email.account_id == account_id)
            .order_by(Email.date.asc())
        )
        rows = list(self.session.scalars(stmt).all())
        if len(rows) <= 1:
            return rows

        def _is_synthetic(eid: str | None) -> bool:
            return bool(eid) and (eid.startswith("compose-") or eid.startswith("reply-"))

        def _content_key(r: Email) -> tuple:
            minute = r.date.replace(second=0, microsecond=0) if r.date else None
            return (
                (r.subject or "").strip().lower(),
                (r.recipients or "").strip().lower(),
                minute,
            )

        real_keys = {_content_key(r) for r in rows if not _is_synthetic(r.email_id)}
        if not real_keys:
            return rows
        return [r for r in rows if not (_is_synthetic(r.email_id) and _content_key(r) in real_keys)]

    def get_by_sender(self, sender: str, account_id: int, limit: int = 50) -> Sequence[Email]:
        """
        Get emails from a specific sender.

        Args:
            sender: Sender email address.
            account_id: Account ID to filter by.
            limit: Maximum number of results.

        Returns:
            List of emails from the sender.
        """
        stmt = (
            select(Email)
            .where(Email.sender == sender, Email.account_id == account_id)
            .order_by(Email.date.desc())
            .limit(limit)
        )
        return self.session.scalars(stmt).all()

    def get_latest_message_id_by_sender(
        self, sender: str, account_id: int
    ) -> Optional[str]:
        """Return the provider email_id of the most recent message from a sender.

        Used to detect staleness of a cached contact summary: if this id
        differs from contact.summary_last_message_id, the summary was
        computed before a new message arrived and needs regeneration.
        """
        stmt = (
            select(Email.email_id)
            .where(Email.sender == sender, Email.account_id == account_id)
            .order_by(Email.date.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def count_by_account(self, account_id: int) -> int:
        """
        Count emails for an account.

        Args:
            account_id: Account ID to count emails for.

        Returns:
            Number of emails for the account.
        """
        stmt = select(func.count(Email.id)).where(Email.account_id == account_id)
        return self.session.scalar(stmt) or 0

    def count_unread_by_account(self, account_id: int) -> int:
        """
        Count unread emails for an account.

        Args:
            account_id: Account ID to count unread emails for.

        Returns:
            Number of unread emails.
        """
        stmt = select(func.count(Email.id)).where(
            Email.account_id == account_id,
            Email.is_read == False,  # noqa: E712
        )
        return self.session.scalar(stmt) or 0

    def mark_as_read(self, email_id: int) -> bool:
        """
        Mark an email as read.

        Args:
            email_id: ID of the email to mark as read.

        Returns:
            True if updated, False if not found.
        """
        email = self.get(email_id)
        if email:
            email.is_read = True
            self.session.flush()
            return True
        return False

    def mark_as_unread(self, email_id: int) -> bool:
        """
        Mark an email as unread.

        Args:
            email_id: ID of the email to mark as unread.

        Returns:
            True if updated, False if not found.
        """
        email = self.get(email_id)
        if email:
            email.is_read = False
            self.session.flush()
            return True
        return False

    def toggle_starred(self, email_id: int) -> Optional[bool]:
        """
        Toggle the starred status of an email.

        Args:
            email_id: ID of the email.

        Returns:
            New starred status, or None if not found.
        """
        email = self.get(email_id)
        if email:
            email.is_starred = not email.is_starred
            self.session.flush()
            return email.is_starred
        return None

    def bulk_update_read_status(
        self,
        email_ids: list[str],
        is_read: bool,
        account_id: int | None = None,
    ) -> int:
        """Update is_read for multiple emails in a single query (WHERE IN).

        Args:
            email_ids: List of provider email IDs to update.
            is_read: New read status.
            account_id: Scope to a single account. Provider email IDs (IMAP
                UIDs) are only unique per account — without scoping, two
                accounts that share a UID would both be flipped. Audit
                2026-04-25 (sub-report 02 H-3) made this parameter required
                in spirit; left optional for backwards compat with internal
                callers, but every public route MUST pass it.

        Returns:
            Number of rows updated.
        """
        if not email_ids:
            return 0
        from sqlalchemy import update as sa_update
        stmt = sa_update(Email).where(Email.email_id.in_(email_ids))
        if account_id is not None:
            stmt = stmt.where(Email.account_id == account_id)
        stmt = stmt.values(is_read=is_read)
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    def bulk_update_folder(
        self,
        email_ids: list[str],
        folder: str,
        account_id: int | None = None,
    ) -> int:
        """Update folder for multiple emails in a single query (WHERE IN).

        Args:
            email_ids: List of provider email IDs to update. Callers must
                strip any "sent:" prefix — the DB stores the raw provider ID.
            folder: New folder name.
            account_id: Scope updates to this account. Provider IDs are only
                unique *per account*, so callers SHOULD pass account_id to
                avoid mutating rows belonging to another user.

        Returns:
            Number of rows updated.
        """
        if not email_ids:
            return 0
        from sqlalchemy import update as sa_update
        stmt = sa_update(Email).where(Email.email_id.in_(email_ids))
        if account_id is not None:
            stmt = stmt.where(Email.account_id == account_id)
        stmt = stmt.values(folder=folder, created_at=datetime.utcnow())
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    def delete_by_account(self, account_id: int) -> int:
        """
        Delete all cached emails for an account.

        Used when force-refreshing to clear stale IMAP UIDs.

        Args:
            account_id: Account ID to delete emails for.

        Returns:
            Number of emails deleted.
        """
        delete_stmt = delete(Email).where(Email.account_id == account_id)
        result = self.session.execute(delete_stmt)
        self.session.flush()
        return result.rowcount

    def delete_by_email_id(self, email_id: str, account_id: int | None = None) -> bool:
        """Delete a single email from cache by its provider email_id (UID).

        Audit 2026-04-25 (sub-report 02 H-3): account_id parameter added so
        callers can avoid wiping rows from another tenant when IMAP UIDs
        collide. Optional only for legacy single-tenant Tauri paths.
        """
        delete_stmt = delete(Email).where(Email.email_id == email_id)
        if account_id is not None:
            delete_stmt = delete_stmt.where(Email.account_id == account_id)
        result = self.session.execute(delete_stmt)
        self.session.flush()
        return result.rowcount > 0

    def update_folder_by_email_id(
        self,
        email_id: str,
        folder: str,
        account_id: int | None = None,
    ) -> bool:
        """Update the folder of a cached email by its provider email_id.

        Used when an email moves between folders (e.g. inbox → archived, inbox → trash).
        Returns True if the email was found and updated.

        Audit 2026-04-25 (sub-report 02 H-3): account_id scoping added.
        """
        from sqlalchemy import update as sa_update
        stmt = sa_update(Email).where(Email.email_id == email_id)
        if account_id is not None:
            stmt = stmt.where(Email.account_id == account_id)
        stmt = stmt.values(folder=folder, created_at=datetime.utcnow())
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount > 0

    def delete_oldest_by_account(self, account_id: int, keep_count: int = 500) -> int:
        """
        Delete oldest emails exceeding the keep count.

        Used for cache limit enforcement.

        Args:
            account_id: Account ID to clean up.
            keep_count: Number of emails to keep (default 500).

        Returns:
            Number of emails deleted.
        """
        # Get count of emails for account
        total_count = self.count_by_account(account_id)

        if total_count <= keep_count:
            return 0

        # Calculate how many to delete
        delete_count = total_count - keep_count

        # Get IDs of oldest emails to delete
        oldest_stmt = (
            select(Email.id)
            .where(Email.account_id == account_id)
            .order_by(Email.date.asc())
            .limit(delete_count)
        )
        oldest_ids = self.session.scalars(oldest_stmt).all()

        if not oldest_ids:
            return 0

        # Delete those emails
        delete_stmt = delete(Email).where(Email.id.in_(oldest_ids))
        result = self.session.execute(delete_stmt)
        self.session.flush()

        return result.rowcount

    def get_date_range(self, account_id: int) -> dict:
        """
        Get the date range of emails for an account.

        Args:
            account_id: Account ID to check.

        Returns:
            Dict with oldest_date and newest_date.
        """
        oldest_stmt = (
            select(Email.date).where(Email.account_id == account_id).order_by(Email.date.asc()).limit(1)
        )
        newest_stmt = (
            select(Email.date).where(Email.account_id == account_id).order_by(Email.date.desc()).limit(1)
        )

        oldest = self.session.scalar(oldest_stmt)
        newest = self.session.scalar(newest_stmt)

        return {
            "oldest_date": oldest.isoformat() if oldest else None,
            "newest_date": newest.isoformat() if newest else None,
        }

    def exists_by_email_id(self, email_id: str, account_id: int | None = None) -> bool:
        """
        Check if an email exists by provider's email ID.

        Args:
            email_id: Provider's unique message ID.
            account_id: Scope the existence check (audit 2026-04-25 H-3).

        Returns:
            True if email exists, False otherwise.
        """
        stmt = select(func.count(Email.id)).where(Email.email_id == email_id)
        if account_id is not None:
            stmt = stmt.where(Email.account_id == account_id)
        return (self.session.scalar(stmt) or 0) > 0

    def get_existing_ids(self, email_ids: list[str], account_id: int) -> list[str]:
        """
        Return email IDs that already exist in the database for a given account.

        Batch existence check: single SELECT ... WHERE email_id IN (...) query
        instead of N individual SELECT COUNT queries.

        Args:
            email_ids: List of provider email IDs to check.
            account_id: Account ID to scope the check.

        Returns:
            List of email_id strings that already exist.
        """
        if not email_ids:
            return []
        stmt = select(Email.email_id).where(
            Email.email_id.in_(email_ids),
            Email.account_id == account_id,
        )
        results = self.session.scalars(stmt).all()
        return list(results)

    def get_by_email_ids(
        self, email_ids, account_id: int | None = None
    ) -> dict[str, Email]:
        """
        Batch-fetch full Email rows by provider email ID, keyed by email_id.

        Collapses the N individual ``get_by_email_id`` round-trips the sync loop
        used to issue (one per already-cached email, defeating the batch
        existence check right above it) into a single
        ``SELECT ... WHERE email_id IN (...)`` (deep audit 2026-06-02 F). The
        returned ORM instances are session-attached, so callers can mutate +
        flush them exactly as with ``get_by_email_id``.

        Args:
            email_ids: Provider email IDs to fetch (list/set/iterable).
            account_id: If provided, restrict to this account (isolation).

        Returns:
            ``{email_id: Email}`` for the rows that exist; missing IDs are absent.
        """
        ids = list(email_ids)
        if not ids:
            return {}
        stmt = select(Email).where(Email.email_id.in_(ids))
        if account_id is not None:
            stmt = stmt.where(Email.account_id == account_id)
        return {row.email_id: row for row in self.session.scalars(stmt).all()}

    def bulk_insert_headers(self, email_objects: list, account_id: int, folder: str = "inbox") -> int:
        """
        Insert multiple email header records in a single batch.

        Skips emails that already exist (by email_id) to avoid UNIQUE constraint
        violations during concurrent or repeated syncs. Also deduplicates within
        the batch itself (IMAP can return the same UID twice on flaky connections).

        Args:
            email_objects: List of domain email objects with attributes
                          (id, conversation_id, subject, sender, sender_name,
                           received_at, body, is_read).
            account_id: Account ID to associate with the emails.

        Returns:
            Number of emails actually inserted (skips duplicates).
        """
        if not email_objects:
            return 0

        from datetime import datetime as dt, timezone
        from app.config import should_persist_email_content

        # Deduplicate within the batch (keep last occurrence)
        seen: dict[str, object] = {}
        for email_obj in email_objects:
            eid = str(getattr(email_obj, 'id', ''))
            if eid:
                seen[eid] = email_obj
        unique_objects = list(seen.values())

        # Filter out email_ids already in the DB
        candidate_ids = list(seen.keys())
        existing_ids = set(self.get_existing_ids(candidate_ids, account_id))
        new_objects = [e for e in unique_objects if str(getattr(e, 'id', '')) not in existing_ids]

        if not new_objects:
            return 0

        objects = []
        persist_content = should_persist_email_content()
        for email_obj in new_objects:
            received_at = email_obj.received_at
            # Normalize to UTC before storing (SQLite loses timezone info)
            if isinstance(received_at, dt) and received_at.tzinfo is not None:
                received_at = received_at.astimezone(timezone.utc).replace(tzinfo=None)
            obj = Email(
                email_id=str(getattr(email_obj, 'id', '')),
                account_id=account_id,
                thread_id=getattr(email_obj, 'conversation_id', None),
                subject=email_obj.subject,
                sender=email_obj.sender,
                sender_name=getattr(email_obj, 'sender_name', None),
                recipients=None,
                date=received_at if isinstance(received_at, dt) else dt.now(),
                body_text=None,  # Headers only -- body filled by background sync
                body_html=None,
                snippet=(
                    getattr(email_obj, 'body', '')[:200]
                    if persist_content and getattr(email_obj, 'body', None)
                    else None
                ),
                is_read=getattr(email_obj, 'is_read', False) if isinstance(getattr(email_obj, 'is_read', False), bool) else False,
                is_starred=False,
                attachments_meta='[{"has":true}]' if getattr(email_obj, 'has_attachments', False) else None,
                folder=folder,
            )
            objects.append(obj)

        self.session.add_all(objects)
        self.session.flush()
        return len(objects)

    def get_emails_missing_snippet(
        self,
        email_ids: list[str],
        account_id: int | None = None,
    ) -> list[Email]:
        """
        Return emails that exist but have no snippet (need body backfill).

        Single query: WHERE email_id IN (...) AND snippet IS NULL.

        Args:
            email_ids: List of provider email IDs to check.
            account_id: Optional account scope. Provider IDs are only unique
                per mailbox, so callers with account context must pass it.

        Returns:
            List of Email objects missing snippet data.
        """
        if not email_ids:
            return []
        stmt = select(Email).where(
            Email.email_id.in_(email_ids),
            Email.snippet == None,  # noqa: E711
            Email.body_text == None,  # noqa: E711
        )
        if account_id is not None:
            stmt = stmt.where(Email.account_id == account_id)
        return list(self.session.scalars(stmt).all())

    def get_with_contact(
        self,
        contact_email: str,
        account_id: int,
        limit: int = 20,
    ) -> Sequence[Email]:
        """
        Get emails exchanged with a specific contact.

        Returns both emails sent TO and received FROM the contact.
        Includes emails where contact is in recipients or CC.

        Args:
            contact_email: Email address of the contact.
            account_id: Account ID to filter by.
            limit: Maximum number of results (default 20).

        Returns:
            List of emails ordered by date descending.
        """

        # Build conditions for contact in various fields
        # - sender == contact_email (emails FROM contact)
        # - recipients contains contact_email (emails TO contact)
        # - cc contains contact_email (emails CC contact)
        stmt = (
            select(Email)
            .where(
                Email.account_id == account_id,
                or_(
                    Email.sender == contact_email,
                    Email.recipients.contains(contact_email),
                    Email.cc.contains(contact_email),
                ),
            )
            .order_by(Email.date.desc())
            .limit(limit)
        )
        return self.session.scalars(stmt).all()
