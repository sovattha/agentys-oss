# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the onboarding email indexer."""

from pathlib import Path

import pytest

from app.onboarding.loader import FixtureLoader
from app.onboarding.indexer import EmailIndexer, IndexedEmails
from app.onboarding.schemas import EmailDirection

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "test_emails.json"


@pytest.fixture
def loaded_emails():
    """Load fixture emails for tests."""
    loader = FixtureLoader(FIXTURE_PATH)
    emails, metadata = loader.load()
    return emails, metadata


@pytest.fixture
def indexed(loaded_emails):
    """Provide indexed emails."""
    emails, metadata = loaded_emails
    indexer = EmailIndexer(metadata["user_email"])
    return indexer.index(emails)


class TestEmailIndexer:
    """Tests for EmailIndexer."""

    def test_index_returns_indexed_emails(self, indexed):
        assert isinstance(indexed, IndexedEmails)

    def test_counts_match(self, indexed):
        assert indexed.total_count == 100
        assert indexed.sent_count + indexed.received_count == 100
        assert indexed.sent_count > 0
        assert indexed.received_count > 0

    def test_emails_sorted_by_date(self, indexed):
        dates = [e.date for e in indexed.all_emails]
        assert dates == sorted(dates)

    def test_sent_received_split(self, indexed):
        for e in indexed.sent_emails:
            assert e.direction == EmailDirection.SENT
        for e in indexed.received_emails:
            assert e.direction == EmailDirection.RECEIVED

    def test_by_contact_groups(self, indexed):
        assert len(indexed.by_contact) > 5
        # Pierre Durand should be a top contact
        assert "pierre.durand@techcorp.fr" in indexed.by_contact

    def test_by_thread_groups(self, indexed):
        assert len(indexed.by_thread) > 10
        # Each thread should have at least 1 email
        for thread in indexed.by_thread.values():
            assert len(thread.emails) >= 1
            assert thread.thread_id
            assert thread.subject

    def test_thread_emails_sorted_by_date(self, indexed):
        for thread in indexed.by_thread.values():
            dates = [e.date for e in thread.emails]
            assert dates == sorted(dates)

    def test_thread_participants(self, indexed):
        for thread in indexed.by_thread.values():
            assert len(thread.participants) >= 1

    def test_contact_metrics(self, indexed):
        pierre = indexed.contact_metrics.get("pierre.durand@techcorp.fr")
        assert pierre is not None
        assert pierre.total_count > 5
        assert pierre.sent_count > 0
        assert pierre.first_interaction is not None
        assert pierre.last_interaction is not None

    def test_top_contacts(self, indexed):
        assert len(indexed.top_contacts) > 0
        assert len(indexed.top_contacts) <= 20
        # Top contact should be Pierre Durand (most interactions)
        assert indexed.top_contacts[0] == "pierre.durand@techcorp.fr"

    def test_date_range(self, indexed):
        assert indexed.date_range is not None
        start, end = indexed.date_range
        assert start < end

    def test_user_email_excluded_from_contacts(self, indexed):
        user = indexed.user_email
        assert user not in indexed.contact_metrics
        assert user not in indexed.by_contact

    def test_received_emails_counted_in_metrics(self, indexed):
        # Contacts who only write TO the user must still appear — the
        # previous behaviour (SENT only) masked them and broke the
        # contact list for users with low outbound volume.
        any_received_only = any(
            m.received_count > 0 and m.sent_count == 0
            for m in indexed.contact_metrics.values()
        )
        assert any_received_only, (
            "indexer should now count received-only contacts"
        )

    def test_noise_senders_filtered(self):
        from datetime import datetime, timezone
        from app.onboarding.loader import OnboardingEmail
        from app.onboarding.schemas import Language

        user = "me@example.com"
        now = datetime.now(timezone.utc)

        def mk(sender, direction):
            return OnboardingEmail(
                id=f"id-{sender}",
                sender_email=sender,
                sender_name=None,
                recipients=[user] if direction == EmailDirection.RECEIVED else ["alice@example.com"],
                cc=[],
                subject="hello",
                body="hi there, this is a body of enough length to pass filters",
                date=now,
                direction=direction,
                thread_id=f"thread-{sender}",
                language=Language.EN,
            )

        emails = [
            mk("noreply@github.com", EmailDirection.RECEIVED),
            mk("newsletter@acme.io", EmailDirection.RECEIVED),
            mk("mailer-daemon@mail.example.com", EmailDirection.RECEIVED),
            mk("real.person@company.com", EmailDirection.RECEIVED),
            mk(user, EmailDirection.SENT),  # user writes to alice
        ]
        indexer = EmailIndexer(user)
        result = indexer.index(emails)

        # Real human stays, automated senders get filtered out.
        assert "real.person@company.com" in result.contact_metrics
        assert "noreply@github.com" not in result.contact_metrics
        assert "newsletter@acme.io" not in result.contact_metrics
        assert "mailer-daemon@mail.example.com" not in result.contact_metrics

    def test_bidirectional_contacts_ranked_first(self):
        from datetime import datetime, timezone
        from app.onboarding.loader import OnboardingEmail
        from app.onboarding.schemas import Language

        user = "me@example.com"
        now = datetime.now(timezone.utc)

        def mk(sender, recipients, direction):
            return OnboardingEmail(
                id=f"{sender}-{direction.value}",
                sender_email=sender,
                sender_name=None,
                recipients=recipients,
                cc=[],
                subject="re: x",
                body="message body long enough to survive filters",
                date=now,
                direction=direction,
                thread_id=f"thread-{sender}",
                language=Language.EN,
            )

        # recv_only has 5 received, 0 sent  -> total=5 one-way
        # bidir has 1 received + 1 sent     -> total=2 bidirectional
        emails = [
            *[mk("recv_only@x.com", [user], EmailDirection.RECEIVED) for _ in range(5)],
            mk("bidir@y.com", [user], EmailDirection.RECEIVED),
            mk(user, ["bidir@y.com"], EmailDirection.SENT),
        ]
        indexer = EmailIndexer(user)
        result = indexer.index(emails)

        # Bidirectional wins over higher-volume one-way.
        assert result.top_contacts[0] == "bidir@y.com"
