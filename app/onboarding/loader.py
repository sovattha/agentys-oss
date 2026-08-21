# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Email loader for the onboarding pipeline.

Provides a unified interface to load emails from:
- JSON fixture files (for testing)
- The EmailRepository (for production usage)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from app.onboarding.schemas import EmailDirection, Language

logger = logging.getLogger(__name__)


@dataclass
class OnboardingEmail:
    """
    Unified email representation for the onboarding pipeline.

    This normalises data from both JSON fixtures and the Email SQLAlchemy
    model so that downstream analysis agents see a single interface.
    """
    id: str
    sender_email: str
    sender_name: Optional[str]
    recipients: List[str]
    cc: List[str]
    subject: str
    body: str
    date: datetime
    direction: EmailDirection
    thread_id: Optional[str] = None
    signature: Optional[str] = None
    language: Language = Language.FR
    labels: List[str] = field(default_factory=list)
    has_attachments: bool = False


class FixtureLoader:
    """Load emails from a JSON fixture file."""

    def __init__(self, fixture_path: str | Path):
        self.fixture_path = Path(fixture_path)

    def load(self) -> tuple[List[OnboardingEmail], dict]:
        """
        Load and parse all emails from the fixture file.

        Returns:
            Tuple of (list of OnboardingEmail, metadata dict).
        """
        with open(self.fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        metadata = data.get("metadata", {})
        raw_emails = data.get("emails", [])

        emails = []
        for raw in raw_emails:
            email = OnboardingEmail(
                id=raw["id"],
                sender_email=raw["from"]["email"],
                sender_name=raw["from"].get("name"),
                recipients=[r["email"] for r in raw.get("to", [])],
                cc=[r["email"] for r in raw.get("cc", [])],
                subject=raw.get("subject", ""),
                body=raw.get("body", ""),
                date=datetime.fromisoformat(raw["date"].replace("Z", "+00:00")),
                direction=EmailDirection(raw["direction"]),
                thread_id=raw.get("thread_id"),
                signature=raw.get("signature"),
                language=Language(raw.get("language", "fr")),
                labels=raw.get("labels", []),
                has_attachments=bool(raw.get("attachments")),
            )
            emails.append(email)

        logger.info("Loaded %d emails from fixture %s", len(emails), self.fixture_path.name)
        return emails, metadata


class RepositoryLoader:
    """Load emails from the existing EmailRepository (production)."""

    def __init__(self, email_repository, account_id: int, user_email: str):
        self.repo = email_repository
        self.account_id = account_id
        self.user_email = user_email

    def load(self, limit: int = 250, since_date: Optional[datetime] = None) -> tuple[List[OnboardingEmail], dict]:
        """
        Load emails from the database for the given account.

        Args:
            limit: Hard cap on the TOTAL number of emails (sent + inbox)
                fed to the analysis pipeline. Default 250 → 100 sent + 150
                inbox. The sent slice saturates agent caps (ProfileAgent
                keeps 15, StyleAgent groups by recipient × 5), so extra
                sent beyond ~100 adds I/O without signal. Extra inbox, on
                the other hand, sharpens KnowledgeAgent's contact metrics
                (bidirectional ranking, threads).
            since_date: If provided, only load emails from this date onwards.

        Returns:
            Tuple of (list of OnboardingEmail, metadata dict).
        """
        sent_cap = max(1, int(limit * 0.4))
        inbox_cap = max(1, limit - sent_cap)

        db_sent: Sequence = self.repo.get_sent_emails(
            self.account_id, limit=sent_cap, offset=0, since_date=since_date
        )
        # include_archived=True: archived threads contain the user's most
        # engaged bidirectional conversations (they got replied-to then
        # tidied out of Inbox). Without them, KnowledgeAgent's
        # bidirectional ranking starves and StyleAgent learns from a
        # shallow inbox subset. See Email.folder='archived' (populated by
        # sync_service archive backfill).
        db_inbox: Sequence = self.repo.get_by_account(
            self.account_id,
            limit=inbox_cap,
            offset=0,
            since_date=since_date,
            include_archived=True,
        )

        emails = []
        for db_email in list(db_inbox) + list(db_sent):
            direction = (
                EmailDirection.SENT
                if db_email.is_sent or db_email.sender == self.user_email
                else EmailDirection.RECEIVED
            )

            recipients = (
                db_email.recipients.split(",") if db_email.recipients else []
            )
            cc = db_email.cc.split(",") if db_email.cc else []

            email = OnboardingEmail(
                id=db_email.email_id,
                sender_email=db_email.sender,
                sender_name=db_email.sender_name,
                recipients=[r.strip() for r in recipients],
                cc=[c.strip() for c in cc],
                subject=db_email.subject or "",
                body=db_email.body_text or "",
                date=db_email.date,
                direction=direction,
                thread_id=db_email.thread_id,
                labels=db_email.labels.split(",") if db_email.labels else [],
                has_attachments=bool(db_email.attachments_meta),
            )
            emails.append(email)

        metadata = {
            "user_email": self.user_email,
            "account_id": self.account_id,
            "total_emails": len(emails),
        }

        logger.info(
            "Loaded %d emails from repository for account %d",
            len(emails), self.account_id,
        )
        return emails, metadata
