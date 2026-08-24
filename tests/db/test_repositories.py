# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Tests for database repositories.
"""

from datetime import datetime
import json

import pytest
from sqlalchemy import Text

from app.db.models import Account, Email, Contact, Draft
from app.db.repositories import (
    AccountRepository,
    EmailRepository,
    ContactRepository,
    DraftRepository,
)


class TestBaseRepository:
    """Tests for BaseRepository common operations."""

    def test_get(self, session, sample_account):
        """Test getting entity by ID."""
        repo = AccountRepository(session)
        account = repo.get(sample_account.id)

        assert account is not None
        assert account.id == sample_account.id

    def test_get_nonexistent(self, session):
        """Test getting nonexistent entity returns None."""
        repo = AccountRepository(session)
        account = repo.get(99999)

        assert account is None

    def test_get_all(self, session, sample_account, sample_account_outlook):
        """Test getting all entities."""
        repo = AccountRepository(session)
        accounts = repo.get_all()

        assert len(accounts) == 2

    def test_get_all_with_pagination(self, session, db_sample_emails):
        """Test pagination in get_all."""
        repo = EmailRepository(session)

        page1 = repo.get_all(limit=5, offset=0)
        page2 = repo.get_all(limit=5, offset=5)

        assert len(page1) == 5
        assert len(page2) == 5
        # Check no overlap
        page1_ids = {e.id for e in page1}
        page2_ids = {e.id for e in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_count(self, session, db_sample_emails):
        """Test counting entities."""
        repo = EmailRepository(session)
        count = repo.count()

        assert count == 10  # db_sample_emails creates 10

    def test_create(self, session):
        """Test creating entity."""
        repo = AccountRepository(session)
        account = Account(
            email="created@example.com",
            provider="imap",
        )
        created = repo.create(account)
        session.commit()

        assert created.id is not None
        assert session.get(Account, created.id) is not None

    def test_create_all(self, session, sample_account):
        """Test bulk creating entities."""
        repo = EmailRepository(session)
        emails = [
            Email(
                email_id=f"bulk_{i}",
                account_id=sample_account.id,
                sender=f"bulk{i}@example.com",
                date=datetime.utcnow(),
            )
            for i in range(5)
        ]
        created = repo.create_all(emails)
        session.commit()

        assert len(created) == 5
        assert all(e.id is not None for e in created)

    def test_delete(self, session, sample_contact):
        """Test deleting entity."""
        repo = ContactRepository(session)
        contact_id = sample_contact.id

        repo.delete(sample_contact)
        session.commit()

        assert session.get(Contact, contact_id) is None

    def test_delete_by_id(self, session, sample_contact):
        """Test deleting entity by ID."""
        repo = ContactRepository(session)
        contact_id = sample_contact.id

        result = repo.delete_by_id(contact_id)
        session.commit()

        assert result is True
        assert session.get(Contact, contact_id) is None

    def test_delete_by_id_nonexistent(self, session):
        """Test deleting nonexistent entity returns False."""
        repo = ContactRepository(session)
        result = repo.delete_by_id(99999)

        assert result is False

    def test_exists(self, session, sample_account):
        """Test exists check."""
        repo = AccountRepository(session)

        assert repo.exists(sample_account.id) is True
        assert repo.exists(99999) is False


class TestAccountRepository:
    """Tests for AccountRepository."""

    def test_last_history_id_is_unbounded_text(self):
        """Outlook deltaLink checkpoints are longer than Gmail history IDs."""
        assert isinstance(Account.__table__.c.last_history_id.type, Text)

    def test_get_by_email(self, session, sample_account):
        """Test getting account by email."""
        repo = AccountRepository(session)
        account = repo.get_by_email("test@example.com")

        assert account is not None
        assert account.id == sample_account.id

    def test_get_by_email_not_found(self, session):
        """Test get_by_email returns None for unknown email."""
        repo = AccountRepository(session)
        account = repo.get_by_email("unknown@example.com")

        assert account is None

    def test_get_active_accounts(self, session, sample_account, sample_account_outlook):
        """Test getting active accounts."""
        # Deactivate one
        sample_account_outlook.is_active = False
        session.commit()

        repo = AccountRepository(session)
        active = repo.get_active_accounts()

        assert len(active) == 1
        assert active[0].email == "test@example.com"

    def test_get_by_provider(self, session, sample_account, sample_account_outlook):
        """Test getting accounts by provider."""
        repo = AccountRepository(session)

        gmail_accounts = repo.get_by_provider("gmail")
        outlook_accounts = repo.get_by_provider("outlook")

        assert len(gmail_accounts) == 1
        assert len(outlook_accounts) == 1

    def test_deactivate(self, session, sample_account):
        """Test deactivating account."""
        repo = AccountRepository(session)

        assert sample_account.is_active is True

        result = repo.deactivate(sample_account.id)
        session.commit()

        assert result is True
        session.expire(sample_account)
        assert sample_account.is_active is False

    def test_update_sync_time(self, session, sample_account):
        """Test updating sync time."""
        repo = AccountRepository(session)
        original_sync = sample_account.last_sync_at

        result = repo.update_sync_time(sample_account.id)
        session.commit()

        assert result is True
        session.expire(sample_account)
        assert sample_account.last_sync_at is not None
        if original_sync:
            assert sample_account.last_sync_at > original_sync


class TestEmailRepository:
    """Tests for EmailRepository."""

    def test_get_by_email_id(self, session, db_sample_email):
        """Test getting email by provider's email_id."""
        repo = EmailRepository(session)
        email = repo.get_by_email_id("msg_12345")

        assert email is not None
        assert email.id == db_sample_email.id

    def test_get_by_account(self, session, sample_account, db_sample_emails):
        """Test getting emails for an account."""
        repo = EmailRepository(session)
        emails = repo.get_by_account(sample_account.id, limit=5)

        assert len(emails) == 5
        # Should be ordered by date descending
        dates = [e.date for e in emails]
        assert dates == sorted(dates, reverse=True)

    def test_get_by_account_unread_only(self, session, sample_account, db_sample_emails):
        """Test getting only unread emails."""
        repo = EmailRepository(session)
        unread = repo.get_by_account(sample_account.id, unread_only=True)

        # db_sample_emails alternates read/unread
        assert len(unread) == 5
        assert all(not e.is_read for e in unread)

    def test_get_by_account_excludes_archived_by_default(self, session, sample_account):
        """folder='archived' rows must NOT appear in the default inbox view."""
        session.add_all([
            Email(email_id="i_1", account_id=sample_account.id, sender="x@a.com",
                  is_sent=False, folder="inbox", date=datetime.utcnow()),
            Email(email_id="a_1", account_id=sample_account.id, sender="y@a.com",
                  is_sent=False, folder="archived", date=datetime.utcnow()),
        ])
        session.commit()

        emails = EmailRepository(session).get_by_account(sample_account.id)
        email_ids = {e.email_id for e in emails}
        assert "i_1" in email_ids
        assert "a_1" not in email_ids, "default inbox view must stay inbox-only"

    def test_get_by_account_include_archived(self, session, sample_account):
        """include_archived=True widens the view to cover archived rows too."""
        session.add_all([
            Email(email_id="i_2", account_id=sample_account.id, sender="x@a.com",
                  is_sent=False, folder="inbox", date=datetime.utcnow()),
            Email(email_id="a_2", account_id=sample_account.id, sender="y@a.com",
                  is_sent=False, folder="archived", date=datetime.utcnow()),
            Email(email_id="n_2", account_id=sample_account.id, sender="z@a.com",
                  is_sent=False, folder=None, date=datetime.utcnow()),
        ])
        session.commit()

        emails = EmailRepository(session).get_by_account(
            sample_account.id, include_archived=True
        )
        email_ids = {e.email_id for e in emails}
        assert email_ids == {"i_2", "a_2", "n_2"}, (
            "include_archived must cover inbox + archived + folder=NULL"
        )

    def test_get_by_thread(self, session, sample_account, db_sample_emails):
        """Test getting emails in a thread."""
        repo = EmailRepository(session)
        thread_emails = repo.get_by_thread("thread_000", sample_account.id)

        # db_sample_emails creates 3 emails per thread (10 emails, 3 threads)
        assert len(thread_emails) >= 3
        # Should be ordered by date ascending
        dates = [e.date for e in thread_emails]
        assert dates == sorted(dates)

    def test_get_by_sender(self, session, sample_account, db_sample_emails):
        """Test getting emails from a sender."""
        repo = EmailRepository(session)
        sender_emails = repo.get_by_sender("sender0@example.com", sample_account.id)

        # db_sample_emails creates 5 different senders
        assert len(sender_emails) >= 2

    def test_count_by_account(self, session, sample_account, db_sample_emails):
        """Test counting emails per account."""
        repo = EmailRepository(session)
        count = repo.count_by_account(sample_account.id)

        assert count == 10

    def test_count_unread_by_account(self, session, sample_account, db_sample_emails):
        """Test counting unread emails."""
        repo = EmailRepository(session)
        unread_count = repo.count_unread_by_account(sample_account.id)

        assert unread_count == 5  # db_sample_emails alternates read/unread

    def test_mark_as_read(self, session, db_sample_email):
        """Test marking email as read."""
        repo = EmailRepository(session)
        assert db_sample_email.is_read is False

        result = repo.mark_as_read(db_sample_email.id)
        session.commit()

        assert result is True
        session.expire(db_sample_email)
        assert db_sample_email.is_read is True

    def test_mark_as_unread(self, session, db_sample_email):
        """Test marking email as unread."""
        repo = EmailRepository(session)
        db_sample_email.is_read = True
        session.commit()

        result = repo.mark_as_unread(db_sample_email.id)
        session.commit()

        assert result is True
        session.expire(db_sample_email)
        assert db_sample_email.is_read is False

    def test_toggle_starred(self, session, db_sample_email):
        """Test toggling starred status."""
        repo = EmailRepository(session)
        assert db_sample_email.is_starred is False

        # Toggle on
        result1 = repo.toggle_starred(db_sample_email.id)
        session.commit()
        assert result1 is True

        # Toggle off
        session.expire(db_sample_email)
        result2 = repo.toggle_starred(db_sample_email.id)
        session.commit()
        assert result2 is False

    def test_delete_oldest_by_account(self, session, sample_account, db_sample_emails):
        """Test deleting oldest emails to enforce cache limit."""
        repo = EmailRepository(session)

        # Keep only 5 of 10 emails
        deleted_count = repo.delete_oldest_by_account(sample_account.id, keep_count=5)
        session.commit()

        assert deleted_count == 5
        assert repo.count_by_account(sample_account.id) == 5

    def test_delete_oldest_no_action_under_limit(self, session, sample_account, db_sample_emails):
        """Test no deletion when under limit."""
        repo = EmailRepository(session)

        deleted_count = repo.delete_oldest_by_account(sample_account.id, keep_count=100)

        assert deleted_count == 0
        assert repo.count_by_account(sample_account.id) == 10

    def test_get_date_range(self, session, sample_account, db_sample_emails):
        """Test getting date range of emails."""
        repo = EmailRepository(session)
        date_range = repo.get_date_range(sample_account.id)

        assert date_range["oldest_date"] is not None
        assert date_range["newest_date"] is not None

    def test_exists_by_email_id(self, session, db_sample_email):
        """Test checking if email exists by provider ID."""
        repo = EmailRepository(session)

        assert repo.exists_by_email_id("msg_12345") is True
        assert repo.exists_by_email_id("nonexistent") is False


class TestContactRepository:
    """Tests for ContactRepository."""

    def test_get_by_email(self, session, sample_account, sample_contact):
        """Test getting contact by email."""
        repo = ContactRepository(session)
        contact = repo.get_by_email("contact@example.com", sample_account.id)

        assert contact is not None
        assert contact.id == sample_contact.id

    def test_get_by_account(self, session, sample_account):
        """Test getting contacts for account."""
        # Create multiple contacts
        contacts = [
            Contact(
                account_id=sample_account.id,
                email=f"contact{i}@example.com",
                email_count=i,
            )
            for i in range(5)
        ]
        session.add_all(contacts)
        session.commit()

        repo = ContactRepository(session)
        result = repo.get_by_account(sample_account.id)

        assert len(result) == 5
        # Should be ordered by email_count descending
        counts = [c.email_count for c in result]
        assert counts == sorted(counts, reverse=True)

    def test_get_top_contacts(self, session, sample_account):
        """Test getting top contacts."""
        contacts = [
            Contact(
                account_id=sample_account.id,
                email=f"top{i}@example.com",
                email_count=i * 10,
            )
            for i in range(10)
        ]
        session.add_all(contacts)
        session.commit()

        repo = ContactRepository(session)
        top = repo.get_top_contacts(sample_account.id, limit=3)

        assert len(top) == 3
        assert top[0].email_count == 90
        assert top[1].email_count == 80
        assert top[2].email_count == 70

    def test_search_by_name_or_email(self, session, sample_account):
        """Test searching contacts."""
        contacts = [
            Contact(account_id=sample_account.id, email="john@example.com", name="John Doe"),
            Contact(account_id=sample_account.id, email="jane@example.com", name="Jane Smith"),
            Contact(account_id=sample_account.id, email="bob@company.com", name="Bob Johnson"),
        ]
        session.add_all(contacts)
        session.commit()

        repo = ContactRepository(session)

        # Search by name
        results = repo.search_by_name_or_email("john", sample_account.id)
        assert len(results) == 2  # John and Bob Johnson

        # Search by email domain
        results = repo.search_by_name_or_email("example.com", sample_account.id)
        assert len(results) == 2

    def test_get_or_create_existing(self, session, sample_account, sample_contact):
        """Test get_or_create returns existing contact."""
        repo = ContactRepository(session)
        contact, created = repo.get_or_create(
            "contact@example.com",
            sample_account.id,
        )

        assert created is False
        assert contact.id == sample_contact.id

    def test_get_or_create_new(self, session, sample_account):
        """Test get_or_create creates new contact."""
        repo = ContactRepository(session)
        contact, created = repo.get_or_create(
            "new@example.com",
            sample_account.id,
            name="New Person",
        )
        session.commit()

        assert created is True
        assert contact.id is not None
        assert contact.name == "New Person"

    def test_increment_email_count(self, session, sample_contact):
        """Test incrementing email count."""
        repo = ContactRepository(session)
        original_count = sample_contact.email_count

        result = repo.increment_email_count(
            sample_contact.id,
            is_sent=True,
            contacted_at=datetime.utcnow(),
        )
        session.commit()

        assert result is True
        session.expire(sample_contact)
        assert sample_contact.email_count == original_count + 1
        assert sample_contact.sent_count == 3  # Was 2

    def test_update_relationship_strength(self, session, sample_contact):
        """Test updating relationship strength."""
        repo = ContactRepository(session)

        result = repo.update_relationship_strength(sample_contact.id, 75)
        session.commit()

        assert result is True
        session.expire(sample_contact)
        assert sample_contact.relationship_strength == 75

    def test_update_relationship_strength_invalid(self, session, sample_contact):
        """Test invalid relationship strength raises error."""
        repo = ContactRepository(session)

        with pytest.raises(ValueError):
            repo.update_relationship_strength(sample_contact.id, 150)

    def test_update_summary_minimizes_content_by_default(
        self,
        monkeypatch,
        session,
        sample_contact,
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        repo = ContactRepository(session)
        payload = {
            "relation_type": "client",
            "habitual_tone": "casual",
            "language": "fr",
            "recurring_topics": ["contrat secret"],
            "user_formulas_opening": ["Salut Jean,"],
            "key_facts": ["travaille sur l'appel d'offres privé"],
            "last_interaction_summary": "A demandé le prix confidentiel.",
        }

        result = repo.update_summary(
            sample_contact.id,
            json.dumps(payload, ensure_ascii=False),
            "msg-42",
        )
        session.commit()
        session.expire(sample_contact)

        assert result is True
        assert json.loads(sample_contact.summary_json) == {
            "habitual_tone": "casual",
            "language": "fr",
            "relation_type": "client",
        }
        assert sample_contact.summary_last_message_id == "msg-42"

    def test_update_summary_legacy_full_cache_preserves_content(
        self,
        monkeypatch,
        session,
        sample_contact,
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        repo = ContactRepository(session)
        payload = {
            "relation_type": "client",
            "recurring_topics": ["contrat secret"],
        }

        repo.update_summary(sample_contact.id, json.dumps(payload), "msg-43")
        session.commit()
        session.expire(sample_contact)

        assert json.loads(sample_contact.summary_json) == payload

    def test_recompute_counts_from_emails_bidirectional(self, session, sample_account):
        """karine scenario: received from AND sent to → sent_count>0 AND received_count>0."""
        # 2 received from karine (is_sent=False, sender=karine)
        session.add_all([
            Email(
                email_id=f"rcv_{i}", account_id=sample_account.id,
                sender="karine.morel@gmail.com", sender_name="Karine",
                recipients=sample_account.email, is_sent=False,
                date=datetime.utcnow(),
            )
            for i in range(2)
        ])
        # 1 sent to karine (is_sent=True, sender=user, recipients=karine)
        session.add(Email(
            email_id="snt_1", account_id=sample_account.id,
            sender=sample_account.email, sender_name="Me",
            recipients="karine.morel@gmail.com", is_sent=True,
            date=datetime.utcnow(),
        ))
        session.commit()

        stats = ContactRepository(session).recompute_counts_from_emails(sample_account.id)
        session.commit()

        assert stats["contacts"] == 1
        contact = ContactRepository(session).get_by_email(
            "karine.morel@gmail.com", sample_account.id
        )
        assert contact is not None
        assert contact.received_count == 2
        assert contact.sent_count == 1
        assert contact.email_count == 3

    def test_recompute_counts_one_way_sender(self, session, sample_account):
        """Newsletter sender (received only, no reply) stays with sent_count=0."""
        session.add(Email(
            email_id="nws_1", account_id=sample_account.id,
            sender="news@substack.com", is_sent=False,
            recipients=sample_account.email, date=datetime.utcnow(),
        ))
        session.commit()

        ContactRepository(session).recompute_counts_from_emails(sample_account.id)
        session.commit()

        contact = ContactRepository(session).get_by_email(
            "news@substack.com", sample_account.id
        )
        assert contact is not None
        assert contact.received_count == 1
        assert contact.sent_count == 0

    def test_recompute_counts_handles_cc(self, session, sample_account):
        """CC recipients on sent emails count toward sent_count."""
        session.add(Email(
            email_id="cc_1", account_id=sample_account.id,
            sender=sample_account.email,
            recipients="primary@example.com",
            cc="cc1@example.com,cc2@example.com",
            is_sent=True, date=datetime.utcnow(),
        ))
        session.commit()

        ContactRepository(session).recompute_counts_from_emails(sample_account.id)
        session.commit()

        repo = ContactRepository(session)
        for addr in ("primary@example.com", "cc1@example.com", "cc2@example.com"):
            contact = repo.get_by_email(addr, sample_account.id)
            assert contact is not None, f"{addr} should have been created"
            assert contact.sent_count == 1

    def test_recompute_counts_excludes_self(self, session, sample_account):
        """User's own email (sent-to-self) never becomes a contact."""
        session.add(Email(
            email_id="self_1", account_id=sample_account.id,
            sender=sample_account.email,
            recipients=sample_account.email,
            is_sent=True, date=datetime.utcnow(),
        ))
        session.commit()

        ContactRepository(session).recompute_counts_from_emails(sample_account.id)
        session.commit()

        contact = ContactRepository(session).get_by_email(
            sample_account.email, sample_account.id
        )
        assert contact is None

    def test_recompute_counts_idempotent(self, session, sample_account):
        """Running recompute twice yields the same result (overwrite, not increment)."""
        session.add_all([
            Email(
                email_id="rcv_x", account_id=sample_account.id,
                sender="x@example.com", is_sent=False,
                recipients=sample_account.email, date=datetime.utcnow(),
            ),
            Email(
                email_id="snt_x", account_id=sample_account.id,
                sender=sample_account.email,
                recipients="x@example.com", is_sent=True,
                date=datetime.utcnow(),
            ),
        ])
        session.commit()

        repo = ContactRepository(session)
        repo.recompute_counts_from_emails(sample_account.id)
        session.commit()
        first = repo.get_by_email("x@example.com", sample_account.id)
        first_rec, first_snt = first.received_count, first.sent_count

        repo.recompute_counts_from_emails(sample_account.id)
        session.commit()
        second = repo.get_by_email("x@example.com", sample_account.id)
        assert second.received_count == first_rec == 1
        assert second.sent_count == first_snt == 1

    def test_recompute_counts_reconciles_wrong_counter(self, session, sample_account):
        """A contact with an incorrectly-inflated sent_count gets corrected."""
        # Seed a contact with bogus counts (simulates double-counting from old code)
        bogus = Contact(
            account_id=sample_account.id, email="reconcile@example.com",
            email_count=99, sent_count=42, received_count=17,
        )
        session.add(bogus)
        # But only 1 sent email actually exists
        session.add(Email(
            email_id="r_1", account_id=sample_account.id,
            sender=sample_account.email,
            recipients="reconcile@example.com", is_sent=True,
            date=datetime.utcnow(),
        ))
        session.commit()

        ContactRepository(session).recompute_counts_from_emails(sample_account.id)
        session.commit()

        fixed = ContactRepository(session).get_by_email(
            "reconcile@example.com", sample_account.id
        )
        assert fixed.sent_count == 1
        assert fixed.received_count == 0
        assert fixed.email_count == 1


class TestDraftRepository:
    """Tests for DraftRepository."""

    def test_get_by_account(self, session, sample_account, sample_draft):
        """Test getting drafts for account."""
        repo = DraftRepository(session)
        drafts = repo.get_by_account(sample_account.id)

        assert len(drafts) == 1
        assert drafts[0].id == sample_draft.id

    def test_get_by_account_with_status_filter(self, session, sample_account):
        """Test filtering drafts by status."""
        drafts = [
            Draft(account_id=sample_account.id, subject="Draft 1", status="draft"),
            Draft(account_id=sample_account.id, subject="Sent 1", status="sent"),
            Draft(account_id=sample_account.id, subject="Draft 2", status="draft"),
        ]
        session.add_all(drafts)
        session.commit()

        repo = DraftRepository(session)
        draft_only = repo.get_by_account(sample_account.id, status="draft")
        sent_only = repo.get_by_account(sample_account.id, status="sent")

        assert len(draft_only) == 2
        assert len(sent_only) == 1

    def test_get_by_original_email(self, session, sample_account, db_sample_email):
        """Test getting drafts for an email."""
        drafts = [
            Draft(
                account_id=sample_account.id,
                original_email_id=db_sample_email.id,
                subject=f"Reply {i}",
            )
            for i in range(3)
        ]
        session.add_all(drafts)
        session.commit()

        repo = DraftRepository(session)
        email_drafts = repo.get_by_original_email(db_sample_email.id)

        assert len(email_drafts) == 3

    def test_get_pending_drafts(self, session, sample_account):
        """Test getting pending drafts."""
        drafts = [
            Draft(account_id=sample_account.id, subject="D1", status="draft"),
            Draft(account_id=sample_account.id, subject="D2", status="reviewed"),
            Draft(account_id=sample_account.id, subject="D3", status="approved"),
            Draft(account_id=sample_account.id, subject="D4", status="sent"),
            Draft(account_id=sample_account.id, subject="D5", status="discarded"),
        ]
        session.add_all(drafts)
        session.commit()

        repo = DraftRepository(session)
        pending = repo.get_pending_drafts(sample_account.id)

        assert len(pending) == 3  # draft, reviewed, approved

    def test_update_status(self, session, sample_draft):
        """Test updating draft status."""
        repo = DraftRepository(session)

        result = repo.update_status(sample_draft.id, "reviewed")
        session.commit()

        assert result is True
        session.expire(sample_draft)
        assert sample_draft.status == "reviewed"

    def test_update_status_invalid(self, session, sample_draft):
        """Test invalid status raises error."""
        repo = DraftRepository(session)

        with pytest.raises(ValueError):
            repo.update_status(sample_draft.id, "invalid_status")

    def test_mark_as_sent(self, session, sample_draft):
        """Test marking draft as sent."""
        repo = DraftRepository(session)

        result = repo.mark_as_sent(sample_draft.id, sent_email_id="sent_msg_123")
        session.commit()

        assert result is True
        session.expire(sample_draft)
        assert sample_draft.status == "sent"
        assert sample_draft.sent_at is not None
        assert sample_draft.sent_email_id == "sent_msg_123"

    def test_update_content(self, session, sample_draft):
        """Test updating draft content."""
        repo = DraftRepository(session)
        original_iteration = sample_draft.iteration_count

        result = repo.update_content(
            sample_draft.id,
            subject="Updated Subject",
            body_text="Updated body content...",
        )
        session.commit()

        assert result is True
        session.expire(sample_draft)
        assert sample_draft.subject == "Updated Subject"
        assert sample_draft.body_text == "Updated body content..."
        assert sample_draft.iteration_count == original_iteration + 1

    def test_add_feedback(self, monkeypatch, session, sample_draft):
        """Test adding feedback to draft."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        repo = DraftRepository(session)

        result = repo.add_feedback(sample_draft.id, rating=4, notes="Good draft")
        session.commit()

        assert result is True
        session.expire(sample_draft)
        assert sample_draft.feedback_rating == 4
        assert sample_draft.feedback_notes == "Good draft"

    def test_add_feedback_metadata_only_drops_free_text(
        self,
        monkeypatch,
        session,
        sample_draft,
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        repo = DraftRepository(session)

        result = repo.add_feedback(
            sample_draft.id,
            rating=4,
            notes="Private detail from a customer email",
        )
        session.commit()

        assert result is True
        session.expire(sample_draft)
        assert sample_draft.feedback_rating == 4
        assert sample_draft.feedback_notes is None

    def test_add_feedback_invalid_rating(self, session, sample_draft):
        """Test invalid feedback rating raises error."""
        repo = DraftRepository(session)

        with pytest.raises(ValueError):
            repo.add_feedback(sample_draft.id, rating=10)

    def test_record_user_edits(self, monkeypatch, session, sample_draft):
        """Test recording user edits."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        repo = DraftRepository(session)

        result = repo.record_user_edits(sample_draft.id, '{"changed": "subject"}')
        session.commit()

        assert result is True
        session.expire(sample_draft)
        assert sample_draft.user_edits == '{"changed": "subject"}'
        assert sample_draft.status == "reviewed"

    def test_record_user_edits_metadata_only_drops_free_text(
        self,
        monkeypatch,
        session,
        sample_draft,
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        repo = DraftRepository(session)

        result = repo.record_user_edits(
            sample_draft.id,
            '{"before": "private old draft", "after": "private new draft"}',
        )
        session.commit()

        assert result is True
        session.expire(sample_draft)
        assert sample_draft.user_edits is None
        assert sample_draft.status == "reviewed"

    def test_create_metadata_only_drops_generation_diagnostics(
        self,
        monkeypatch,
        session,
        sample_account,
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        repo = DraftRepository(session)
        draft = Draft(
            account_id=sample_account.id,
            subject="Re: Proposal",
            body_text="User-facing final draft",
            generation_prompt="Prompt with private email body",
            user_edits='{"before": "private", "after": "private"}',
            feedback_notes="Private note",
        )

        created = repo.create(draft)
        session.commit()
        session.expire(created)

        assert created.body_text == "User-facing final draft"
        assert created.generation_prompt is None
        assert created.user_edits is None
        assert created.feedback_notes is None

    def test_get_stats_by_account(self, session, sample_account):
        """Test getting draft statistics."""
        drafts = [
            Draft(account_id=sample_account.id, status="draft"),
            Draft(account_id=sample_account.id, status="draft"),
            Draft(account_id=sample_account.id, status="sent", feedback_rating=5),
            Draft(account_id=sample_account.id, status="sent", feedback_rating=3),
            Draft(account_id=sample_account.id, status="discarded"),
        ]
        session.add_all(drafts)
        session.commit()

        repo = DraftRepository(session)
        stats = repo.get_stats_by_account(sample_account.id)

        assert stats["total"] == 5
        assert stats["pending"] == 2
        assert stats["sent"] == 2
        assert stats["discarded"] == 1
        assert stats["average_rating"] == 4.0
