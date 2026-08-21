"""
Contact repository for contact-specific database operations.
"""

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.contact_summary_privacy import minimize_contact_summary_json
from app.config import should_persist_email_content
from app.db.models.contact import Contact
from app.db.repositories.base import BaseRepository


class ContactRepository(BaseRepository[Contact]):
    """
    Repository for Contact model operations.
    """

    model = Contact

    def get_by_email(self, email: str, account_id: int) -> Optional[Contact]:
        """
        Get contact by email address for a specific account.

        Args:
            email: Contact's email address.
            account_id: Account ID to filter by.

        Returns:
            Contact if found, None otherwise.
        """
        stmt = select(Contact).where(Contact.email == email, Contact.account_id == account_id)
        return self.session.scalar(stmt)

    def get_by_account(
        self,
        account_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Contact]:
        """
        Get contacts for an account.

        Args:
            account_id: Account ID to filter by.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of contacts ordered by email count descending.
        """
        stmt = (
            select(Contact)
            .where(Contact.account_id == account_id)
            .order_by(Contact.email_count.desc())
            .limit(limit)
            .offset(offset)
        )
        return self.session.scalars(stmt).all()

    def get_top_contacts(self, account_id: int, limit: int = 10) -> Sequence[Contact]:
        """
        Get top contacts by email count.

        Args:
            account_id: Account ID to filter by.
            limit: Number of top contacts to return.

        Returns:
            List of top contacts.
        """
        stmt = (
            select(Contact)
            .where(Contact.account_id == account_id)
            .order_by(Contact.email_count.desc())
            .limit(limit)
        )
        return self.session.scalars(stmt).all()

    def get_recent_contacts(self, account_id: int, limit: int = 10) -> Sequence[Contact]:
        """
        Get recently contacted contacts.

        Args:
            account_id: Account ID to filter by.
            limit: Number of recent contacts to return.

        Returns:
            List of recent contacts.
        """
        stmt = (
            select(Contact)
            .where(Contact.account_id == account_id, Contact.last_contacted_at.isnot(None))
            .order_by(Contact.last_contacted_at.desc())
            .limit(limit)
        )
        return self.session.scalars(stmt).all()

    def search_by_name_or_email(
        self,
        query: str,
        account_id: int,
        limit: int = 20,
    ) -> Sequence[Contact]:
        """
        Search contacts by name or email.

        Args:
            query: Search query string.
            account_id: Account ID to filter by.
            limit: Maximum number of results.

        Returns:
            List of matching contacts.
        """
        search_pattern = f"%{query}%"
        stmt = (
            select(Contact)
            .where(
                Contact.account_id == account_id,
                (Contact.email.ilike(search_pattern)) | (Contact.name.ilike(search_pattern)),
            )
            .order_by(Contact.email_count.desc())
            .limit(limit)
        )
        return self.session.scalars(stmt).all()

    def count_by_account(self, account_id: int) -> int:
        """
        Count contacts for an account.

        Args:
            account_id: Account ID to count contacts for.

        Returns:
            Number of contacts.
        """
        stmt = select(func.count(Contact.id)).where(Contact.account_id == account_id)
        return self.session.scalar(stmt) or 0

    def get_or_create(
        self,
        email: str,
        account_id: int,
        name: Optional[str] = None,
    ) -> tuple[Contact, bool]:
        """
        Get existing contact or create a new one.

        Args:
            email: Contact's email address.
            account_id: Account ID.
            name: Optional contact name.

        Returns:
            Tuple of (Contact, created) where created is True if new.
        """
        existing = self.get_by_email(email, account_id)
        if existing:
            return existing, False

        # Use a savepoint so a UNIQUE race (another thread inserted between our
        # SELECT and INSERT) only rolls back this nested transaction, not the
        # caller's outer transaction (which may hold other pending inserts).
        try:
            with self.session.begin_nested():
                contact = Contact(
                    email=email,
                    account_id=account_id,
                    name=name,
                    email_count=0,
                    sent_count=0,
                    received_count=0,
                )
                self.session.add(contact)
                self.session.flush()
            return contact, True
        except IntegrityError:
            # Race condition: another thread won the INSERT — fetch the winner
            existing = self.get_by_email(email, account_id)
            if existing:
                return existing, False
            raise

    def increment_email_count(
        self,
        contact_id: int,
        is_sent: bool = False,
        contacted_at: Optional[datetime] = None,
    ) -> bool:
        """
        Increment email count for a contact.

        Args:
            contact_id: ID of the contact.
            is_sent: True if email was sent to contact, False if received.
            contacted_at: Timestamp of the interaction.

        Returns:
            True if updated, False if not found.
        """
        contact = self.get(contact_id)
        if not contact:
            return False

        contact.email_count += 1
        if is_sent:
            contact.sent_count += 1
        else:
            contact.received_count += 1

        if contacted_at:
            if contact.first_contacted_at is None:
                contact.first_contacted_at = contacted_at
            if contact.last_contacted_at is None or contacted_at > contact.last_contacted_at:
                contact.last_contacted_at = contacted_at

        # No explicit flush — let the caller's session commit batch all pending
        # changes at once. An eager flush here causes "database is locked" errors
        # when multiple threads have concurrent write transactions.
        return True

    def recompute_counts_from_emails(self, account_id: int) -> dict[str, int]:
        """Derive sent_count / received_count from the Email table.

        Single source of truth is the Email table. Historical sends from before
        the sync fix (sent_count never bumped) and any incremental drift get
        reconciled in one idempotent pass. Safe to run repeatedly.

        Returns a dict with stats: {"contacts": N, "created": M, "updated": K}.
        """
        from collections import defaultdict
        from app.db.models.account import Account
        from app.db.models.email import Email

        account = self.session.get(Account, int(account_id))
        user_email = (account.email or "").strip().lower() if account else ""

        received: dict[str, int] = defaultdict(int)
        for (sender,) in self.session.execute(
            select(Email.sender).where(
                Email.account_id == int(account_id),
                Email.is_sent.is_(False),
                Email.sender.isnot(None),
            )
        ):
            addr = (sender or "").strip().lower()
            if "<" in addr and ">" in addr:
                addr = addr.split("<", 1)[1].split(">", 1)[0].strip()
            if not addr or "@" not in addr or addr == user_email:
                continue
            received[addr] += 1

        sent: dict[str, int] = defaultdict(int)
        for recipients_str, cc_str in self.session.execute(
            select(Email.recipients, Email.cc).where(
                Email.account_id == int(account_id),
                Email.is_sent.is_(True),
            )
        ):
            seen_in_email: set[str] = set()
            for raw_list in ((recipients_str or ""), (cc_str or "")):
                for part in raw_list.split(","):
                    addr = part.strip().lower()
                    if "<" in addr and ">" in addr:
                        addr = addr.split("<", 1)[1].split(">", 1)[0].strip()
                    if not addr or "@" not in addr or addr == user_email:
                        continue
                    if addr in seen_in_email:
                        continue
                    seen_in_email.add(addr)
                    sent[addr] += 1

        all_addrs = set(received) | set(sent)
        created = 0
        updated = 0
        now = datetime.utcnow()
        for addr in all_addrs:
            contact = self.get_by_email(addr, int(account_id))
            if contact is None:
                contact, was_created = self.get_or_create(email=addr, account_id=int(account_id))
                if was_created:
                    created += 1
            rec = received.get(addr, 0)
            snt = sent.get(addr, 0)
            if contact.received_count != rec or contact.sent_count != snt:
                contact.received_count = rec
                contact.sent_count = snt
                contact.email_count = rec + snt
                if contact.first_contacted_at is None:
                    contact.first_contacted_at = now
                if contact.last_contacted_at is None:
                    contact.last_contacted_at = now
                updated += 1

        return {"contacts": len(all_addrs), "created": created, "updated": updated}

    def update_summary(
        self,
        contact_id: int,
        summary_json: str,
        last_message_id: Optional[str],
    ) -> bool:
        """Persist a pre-computed contact summary + staleness marker.

        Args:
            contact_id: ID of the contact.
            summary_json: Serialized JSON of the structured summary.
            last_message_id: provider email_id of the most recent email
                considered when generating the summary. Used to detect
                staleness on the next read.

        Returns:
            True if updated, False if contact not found.
        """
        contact = self.get(contact_id)
        if not contact:
            return False
        if should_persist_email_content():
            contact.summary_json = summary_json
        else:
            contact.summary_json = minimize_contact_summary_json(summary_json)
        contact.summary_last_message_id = last_message_id
        contact.summary_updated_at = datetime.utcnow()
        return True

    def update_relationship_strength(self, contact_id: int, score: int) -> bool:
        """
        Update relationship strength score for a contact.

        Args:
            contact_id: ID of the contact.
            score: Relationship strength score (0-100).

        Returns:
            True if updated, False if not found.
        """
        if not 0 <= score <= 100:
            raise ValueError("Score must be between 0 and 100")

        contact = self.get(contact_id)
        if contact:
            contact.relationship_strength = score
            self.session.flush()
            return True
        return False
