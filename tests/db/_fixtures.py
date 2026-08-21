"""
Pytest fixtures for database tests.
"""

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from app.db.models import Base, Account, Email, Contact, Draft


def _configure_sqlite_pragmas(dbapi_conn, connection_record) -> None:
    """Configure SQLite pragmas for testing (same as production)."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


@pytest.fixture(scope="function")
def test_db_path():
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)
    # Cleanup after test
    try:
        os.unlink(f.name)
    except OSError:
        pass


@pytest.fixture(scope="function")
def engine(test_db_path):
    """Create a test database engine."""
    db_url = f"sqlite:///{test_db_path}"
    engine = create_engine(db_url, echo=False)

    # Enable foreign keys for SQLite
    event.listen(engine, "connect", _configure_sqlite_pragmas)

    # Create all tables
    Base.metadata.create_all(bind=engine)

    yield engine

    engine.dispose()


@pytest.fixture(scope="function")
def session(engine) -> Session:
    """Create a test database session."""
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()

    yield session

    session.rollback()
    session.close()


@pytest.fixture
def sample_account(session) -> Account:
    """Create a sample account for testing."""
    account = Account(
        email="test@example.com",
        provider="gmail",
        display_name="Test User",
        is_active=True,
    )
    session.add(account)
    session.commit()
    return account


@pytest.fixture
def sample_account_outlook(session) -> Account:
    """Create a sample Outlook account for testing."""
    account = Account(
        email="outlook@example.com",
        provider="outlook",
        display_name="Outlook User",
        is_active=True,
    )
    session.add(account)
    session.commit()
    return account


@pytest.fixture
def db_sample_email(session, sample_account) -> Email:
    """Create a sample email for testing."""
    email = Email(
        email_id="msg_12345",
        thread_id="thread_001",
        account_id=sample_account.id,
        subject="Test Subject",
        sender="sender@example.com",
        sender_name="Sender Name",
        recipients="recipient@example.com",
        date=datetime.utcnow(),
        body_text="This is the email body.",
        snippet="This is the email...",
        is_read=False,
        is_starred=False,
    )
    session.add(email)
    session.commit()
    return email


@pytest.fixture
def db_sample_emails(session, sample_account) -> list[Email]:
    """Create multiple sample emails for testing."""
    base_date = datetime.utcnow()
    emails = []
    for i in range(10):
        email = Email(
            email_id=f"msg_{i:05d}",
            thread_id=f"thread_{i % 3:03d}",  # 3 different threads
            account_id=sample_account.id,
            subject=f"Test Subject {i}",
            sender=f"sender{i % 5}@example.com",  # 5 different senders
            date=base_date - timedelta(hours=i),
            body_text=f"Email body {i}",
            snippet=f"Email snippet {i}...",
            is_read=i % 2 == 0,  # Alternate read/unread
        )
        emails.append(email)

    session.add_all(emails)
    session.commit()
    return emails


@pytest.fixture
def sample_contact(session, sample_account) -> Contact:
    """Create a sample contact for testing."""
    contact = Contact(
        account_id=sample_account.id,
        email="contact@example.com",
        name="Test Contact",
        email_count=5,
        sent_count=2,
        received_count=3,
        last_contacted_at=datetime.utcnow(),
    )
    session.add(contact)
    session.commit()
    return contact


@pytest.fixture
def sample_draft(session, sample_account, db_sample_email) -> Draft:
    """Create a sample draft for testing."""
    draft = Draft(
        account_id=sample_account.id,
        original_email_id=db_sample_email.id,
        subject="Re: Test Subject",
        recipients="sender@example.com",
        body_text="Thank you for your email...",
        status="draft",
        generation_prompt="Reply professionally",
        agent_model="claude-3-opus",
        iteration_count=1,
    )
    session.add(draft)
    session.commit()
    return draft
