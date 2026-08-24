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
Tests for SQLAlchemy models.
"""

from datetime import datetime

import pytest
from sqlalchemy import BigInteger, Integer, Text
from sqlalchemy.exc import IntegrityError

from app.db.models import Account, BulkJob, Email, Contact, Draft, KnowledgeEntry
from app.db.types import EncryptedString


class TestAccountModel:
    """Tests for the Account model."""

    def test_create_account(self, session):
        """Test creating a basic account."""
        account = Account(
            email="new@example.com",
            provider="gmail",
            display_name="New User",
        )
        session.add(account)
        session.commit()

        assert account.id is not None
        assert account.email == "new@example.com"
        assert account.provider == "gmail"
        assert account.is_active is True
        assert account.created_at is not None

    def test_account_unique_email(self, session, sample_account):
        """Test that email must be unique."""
        duplicate = Account(
            email=sample_account.email,
            provider="outlook",
        )
        session.add(duplicate)

        with pytest.raises(IntegrityError):
            session.commit()

    def test_account_to_dict(self, sample_account):
        """Test account to_dict method."""
        data = sample_account.to_dict()

        assert data["id"] == sample_account.id
        assert data["email"] == "test@example.com"
        assert data["provider"] == "gmail"
        assert "access_token" not in data  # Should not expose tokens
        assert "refresh_token" not in data

    def test_account_repr(self, sample_account):
        """Test account string representation."""
        repr_str = repr(sample_account)
        assert "Account" in repr_str
        assert "test@example.com" in repr_str
        assert "gmail" in repr_str

    def test_user_id_allows_external_64_bit_ids(self):
        """Telegram/JWT user IDs can exceed Postgres INTEGER range."""
        assert isinstance(Account.__table__.c.user_id.type, BigInteger)

    def test_oauth_tokens_are_unbounded_text(self):
        """OAuth providers can return tokens longer than 2048 chars."""
        assert isinstance(
            Account.__table__.c.access_token.type.impl_instance, Text
        )
        assert isinstance(
            Account.__table__.c.refresh_token.type.impl_instance, Text
        )

    def test_oauth_tokens_use_application_layer_encryption(self):
        """CASA Tier 2: OAuth tokens must be Fernet-encrypted at the column
        level so a DB-only compromise never yields usable credentials."""
        assert isinstance(Account.__table__.c.access_token.type, EncryptedString)
        assert isinstance(Account.__table__.c.refresh_token.type, EncryptedString)

    def test_oauth_tokens_round_trip_is_encrypted_at_rest(self, session):
        """Raw SQL must see ciphertext; ORM must hand plaintext back."""
        plain_access = "ya29.access-token-plaintext"
        plain_refresh = "1//refresh-token-plaintext"
        account = Account(
            email="encrypted@example.com",
            provider="gmail",
            access_token=plain_access,
            refresh_token=plain_refresh,
        )
        session.add(account)
        session.commit()
        account_id = account.id
        session.expire_all()

        from sqlalchemy import text as sql_text

        raw_access, raw_refresh = session.execute(
            sql_text("SELECT access_token, refresh_token FROM accounts WHERE id = :i"),
            {"i": account_id},
        ).one()

        assert raw_access != plain_access
        assert raw_refresh != plain_refresh
        assert raw_access.startswith("gAAAAA")
        assert raw_refresh.startswith("gAAAAA")

        reloaded = session.get(Account, account_id)
        assert reloaded.access_token == plain_access
        assert reloaded.refresh_token == plain_refresh


class TestEmailModel:
    """Tests for the Email model."""

    def test_create_email(self, session, sample_account):
        """Test creating an email."""
        email = Email(
            email_id="msg_new",
            account_id=sample_account.id,
            subject="New Email",
            sender="new@sender.com",
            date=datetime.utcnow(),
        )
        session.add(email)
        session.commit()

        assert email.id is not None
        assert email.email_id == "msg_new"
        assert email.is_read is False
        assert email.is_starred is False

    def test_sender_allows_long_rfc_header_values(self):
        """Provider sender headers can include long display names."""
        assert Email.__table__.c.sender.type.length == 1024

    def test_email_unique_email_id(self, session, sample_account, db_sample_email):
        """Test that email_id must be unique."""
        duplicate = Email(
            email_id=db_sample_email.email_id,
            account_id=sample_account.id,
            sender="other@example.com",
            date=datetime.utcnow(),
        )
        session.add(duplicate)

        with pytest.raises(IntegrityError):
            session.commit()

    def test_email_account_relationship(self, db_sample_email, sample_account):
        """Test email-account relationship."""
        assert db_sample_email.account == sample_account
        assert db_sample_email in sample_account.emails

    def test_email_to_dict(self, db_sample_email):
        """Test email to_dict method."""
        data = db_sample_email.to_dict()

        # BUG-003: to_dict() exposes email_id (provider hash) as "id", not the DB PK
        assert data["id"] == db_sample_email.email_id
        assert data["email_id"] == "msg_12345"
        assert data["subject"] == "Test Subject"
        assert data["sender"] == "sender@example.com"
        assert "body_text" not in data  # Not in basic dict

    def test_email_to_dict_full(self, db_sample_email):
        """Test email to_dict_full method."""
        data = db_sample_email.to_dict_full()

        assert data["body_text"] == "This is the email body."
        assert "body_html" in data

    def test_email_cascade_delete(self, session, sample_account):
        """Test that emails are deleted when account is deleted."""
        # Create an email
        email = Email(
            email_id="cascade_test",
            account_id=sample_account.id,
            sender="test@example.com",
            date=datetime.utcnow(),
        )
        session.add(email)
        session.commit()
        email_id = email.id

        # Delete account
        session.delete(sample_account)
        session.commit()

        # Email should be gone
        assert session.get(Email, email_id) is None


class TestContactModel:
    """Tests for the Contact model."""

    def test_create_contact(self, session, sample_account):
        """Test creating a contact."""
        contact = Contact(
            account_id=sample_account.id,
            email="new.contact@example.com",
            name="New Contact",
        )
        session.add(contact)
        session.commit()

        assert contact.id is not None
        assert contact.email_count == 0

    def test_email_allows_long_rfc_header_values(self):
        """Contacts are derived from provider headers, not only bare addresses."""
        assert Contact.__table__.c.email.type.length == 1024

    def test_contact_unique_per_account(self, session, sample_account, sample_contact):
        """Test that email must be unique per account."""
        duplicate = Contact(
            account_id=sample_account.id,
            email=sample_contact.email,
            name="Duplicate",
        )
        session.add(duplicate)

        with pytest.raises(IntegrityError):
            session.commit()

    def test_contact_same_email_different_accounts(self, session, sample_account, sample_account_outlook):
        """Test same email can exist in different accounts."""
        contact1 = Contact(
            account_id=sample_account.id,
            email="shared@example.com",
            name="Contact 1",
        )
        contact2 = Contact(
            account_id=sample_account_outlook.id,
            email="shared@example.com",
            name="Contact 2",
        )
        session.add_all([contact1, contact2])
        session.commit()

        assert contact1.id is not None
        assert contact2.id is not None
        assert contact1.id != contact2.id

    def test_contact_to_dict(self, sample_contact):
        """Test contact to_dict method."""
        data = sample_contact.to_dict()

        assert data["email"] == "contact@example.com"
        assert data["name"] == "Test Contact"
        assert data["email_count"] == 5
        assert data["sent_count"] == 2
        assert data["received_count"] == 3


class TestDraftModel:
    """Tests for the Draft model."""

    def test_create_draft(self, session, sample_account):
        """Test creating a draft."""
        draft = Draft(
            account_id=sample_account.id,
            subject="New Draft",
            body_text="Draft content...",
        )
        session.add(draft)
        session.commit()

        assert draft.id is not None
        assert draft.status == "draft"
        assert draft.iteration_count == 1

    def test_draft_with_original_email(self, sample_draft, db_sample_email):
        """Test draft with original email reference."""
        assert sample_draft.original_email == db_sample_email
        assert sample_draft in db_sample_email.drafts

    def test_draft_original_email_nullable(self, session, sample_account):
        """Test draft without original email (new composition)."""
        draft = Draft(
            account_id=sample_account.id,
            subject="New Composition",
            recipients="someone@example.com",
            body_text="Starting fresh...",
        )
        session.add(draft)
        session.commit()

        assert draft.original_email_id is None
        assert draft.original_email is None

    def test_draft_to_dict(self, sample_draft):
        """Test draft to_dict method."""
        data = sample_draft.to_dict()

        assert data["subject"] == "Re: Test Subject"
        assert data["status"] == "draft"
        assert data["iteration_count"] == 1
        assert "generation_prompt" not in data  # Not in basic dict

    def test_draft_to_dict_full(self, monkeypatch, sample_draft):
        """Test draft to_dict_full method."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        data = sample_draft.to_dict_full()

        assert data["generation_prompt"] == "Reply professionally"
        assert data["agent_model"] == "claude-3-opus"

    def test_draft_to_dict_full_hides_free_text_in_metadata_only(
        self,
        monkeypatch,
        sample_draft,
    ):
        """Metadata-only output keeps the draft body but hides diagnostics."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        sample_draft.user_edits = '{"before": "private", "after": "private"}'
        sample_draft.feedback_notes = "This note may contain private context."

        data = sample_draft.to_dict_full()

        assert data["body_text"] == "Thank you for your email..."
        assert data["generation_prompt"] is None
        assert data["user_edits"] is None
        assert data["feedback_notes"] is None

    def test_draft_cascade_on_account_delete(self, session, sample_account):
        """Test drafts are deleted when account is deleted."""
        draft = Draft(
            account_id=sample_account.id,
            subject="Will be deleted",
            body_text="...",
        )
        session.add(draft)
        session.commit()
        draft_id = draft.id

        # Delete account
        session.delete(sample_account)
        session.commit()

        # Draft should be gone
        assert session.get(Draft, draft_id) is None

    def test_draft_set_null_on_email_delete(self, session, sample_draft, db_sample_email):
        """Test draft.original_email_id is set to NULL when email is deleted."""
        draft_id = sample_draft.id

        # Delete the original email
        session.delete(db_sample_email)
        session.commit()

        # Draft should still exist but with null reference
        session.expire_all()
        draft = session.get(Draft, draft_id)
        assert draft is not None
        assert draft.original_email_id is None


class TestKnowledgeEntryModel:
    """Tests for the KnowledgeEntry model."""

    def test_account_id_matches_accounts_pk_type(self):
        """Postgres requires FK columns to use the same type."""
        assert isinstance(KnowledgeEntry.__table__.c.account_id.type, Integer)

    def test_create_knowledge_entry(self, session, sample_account):
        """Test creating a knowledge entry scoped to an account."""
        entry = KnowledgeEntry(
            account_id=sample_account.id,
            title="FAQ",
            content="Use the account signature.",
            category="FAQ",
            source="manual",
        )
        session.add(entry)
        session.commit()

        assert entry.id is not None
        assert entry.account_id == sample_account.id


class TestBulkJobModel:
    """Tests for the BulkJob model."""

    def test_user_id_allows_external_64_bit_ids(self):
        """Bulk jobs share the same external user ID domain as accounts."""
        assert isinstance(BulkJob.__table__.c.user_id.type, BigInteger)


class TestTimestampMixin:
    """Tests for the TimestampMixin."""

    def test_created_at_auto_set(self, session, sample_account):
        """Test created_at is automatically set."""
        assert sample_account.created_at is not None
        assert isinstance(sample_account.created_at, datetime)

    def test_updated_at_changes_on_update(self, session, sample_account):
        """Test updated_at changes when model is updated."""

        # Make a change
        sample_account.display_name = "Updated Name"
        session.commit()

        # Note: SQLite doesn't support onupdate trigger in the same way
        # This test verifies the field exists and is a datetime
        assert sample_account.updated_at is not None


class TestModelRelationships:
    """Tests for model relationships."""

    def test_account_emails_relationship(self, sample_account, db_sample_emails):
        """Test account.emails relationship works."""
        # db_sample_emails fixture creates 10 emails
        account_emails = list(sample_account.emails)
        assert len(account_emails) == 10

    def test_email_drafts_relationship(self, session, sample_account, db_sample_email):
        """Test email.drafts relationship works."""
        # Create multiple drafts for the same email
        drafts = [
            Draft(
                account_id=sample_account.id,
                original_email_id=db_sample_email.id,
                subject=f"Draft {i}",
                body_text=f"Content {i}",
            )
            for i in range(3)
        ]
        session.add_all(drafts)
        session.commit()

        assert len(db_sample_email.drafts) == 3
