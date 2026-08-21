# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the onboarding email loader."""

from pathlib import Path

import pytest

from app.onboarding.loader import FixtureLoader, OnboardingEmail
from app.onboarding.schemas import EmailDirection, Language

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "test_emails.json"


class TestFixtureLoader:
    """Tests for FixtureLoader."""

    def test_load_returns_emails_and_metadata(self):
        loader = FixtureLoader(FIXTURE_PATH)
        emails, metadata = loader.load()

        assert isinstance(emails, list)
        assert isinstance(metadata, dict)
        assert len(emails) == 100
        assert metadata["user_email"] == "sophie.martin@techcorp.fr"

    def test_loaded_emails_are_onboarding_email_instances(self):
        loader = FixtureLoader(FIXTURE_PATH)
        emails, _ = loader.load()

        for email in emails:
            assert isinstance(email, OnboardingEmail)

    def test_email_fields_populated(self):
        loader = FixtureLoader(FIXTURE_PATH)
        emails, _ = loader.load()

        first_sent = next(e for e in emails if e.direction == EmailDirection.SENT)
        assert first_sent.id
        assert first_sent.sender_email
        assert first_sent.subject
        assert first_sent.body
        assert first_sent.date is not None

    def test_direction_parsed_correctly(self):
        loader = FixtureLoader(FIXTURE_PATH)
        emails, _ = loader.load()

        sent = [e for e in emails if e.direction == EmailDirection.SENT]
        received = [e for e in emails if e.direction == EmailDirection.RECEIVED]
        assert len(sent) > 0
        assert len(received) > 0
        assert len(sent) + len(received) == 100

    def test_language_parsed(self):
        loader = FixtureLoader(FIXTURE_PATH)
        emails, _ = loader.load()

        fr_emails = [e for e in emails if e.language == Language.FR]
        en_emails = [e for e in emails if e.language == Language.EN]
        assert len(fr_emails) > 0
        assert len(en_emails) > 0

    def test_thread_ids_present(self):
        loader = FixtureLoader(FIXTURE_PATH)
        emails, _ = loader.load()

        with_thread = [e for e in emails if e.thread_id]
        assert len(with_thread) > 50  # Most emails have threads

    def test_signatures_extracted(self):
        loader = FixtureLoader(FIXTURE_PATH)
        emails, _ = loader.load()

        with_sig = [e for e in emails if e.signature]
        assert len(with_sig) > 10

    def test_nonexistent_file_raises(self):
        loader = FixtureLoader("/nonexistent/file.json")
        with pytest.raises(FileNotFoundError):
            loader.load()
