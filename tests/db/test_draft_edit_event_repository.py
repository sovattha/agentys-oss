"""Tests d'intégration pour DraftEditEventRepository (#196).

Utilise la fixture ``session`` de ``tests/db/conftest.py`` qui crée un SQLite
temporaire avec toutes les tables via ``Base.metadata.create_all``.
"""

import pytest

from app.db.repositories.draft_edit_event_repository import DraftEditEventRepository
from app.domain.entities.draft_edit_event import EditCategory
from app.services.edit_analyzer_service import build_event


@pytest.fixture
def repo(session):
    return DraftEditEventRepository(session)


@pytest.fixture
def account_id(sample_account):
    return sample_account.id


class TestDraftEditEventRepository:
    def test_add_persists_and_returns_id(self, repo, session, account_id):
        event = build_event(
            draft_id="draft_abc123",
            account_id=account_id,
            initial="Hi, confirmed for tomorrow.",
            final=(
                "Hi, confirmed for tomorrow. "
                "I'll bring the Q3 report. "
                "Sophie will join us too."
            ),
        )
        event_id = repo.add(event)
        session.commit()
        assert event_id > 0

    def test_list_for_account_ordered_by_recent(self, repo, session, account_id):
        for i in range(3):
            repo.add(
                build_event(
                    draft_id=f"draft_{i}",
                    account_id=account_id,
                    initial="short",
                    final="a much much much longer final version",
                )
            )
        session.commit()

        events = repo.list_for_account(account_id, limit=10)
        assert len(events) == 3
        # Le plus récent en premier.
        assert events[0].draft_id == "draft_2"

    def test_list_filtered_by_category(self, repo, session, account_id):
        repo.add(
            build_event(
                draft_id="draft_short",
                account_id=account_id,
                initial="a" * 100,
                final="a" * 50,  # length_adjustment
            )
        )
        repo.add(
            build_event(
                draft_id="draft_cosmetic",
                account_id=account_id,
                initial="Hello Marc, how are you today?",
                final="Hello Marc; how are you today?",  # minor_typo_fix
            )
        )
        session.commit()

        length_events = repo.list_for_account(
            account_id, category=EditCategory.LENGTH_ADJUSTMENT
        )
        assert len(length_events) == 1
        assert length_events[0].draft_id == "draft_short"

    def test_isolation_by_account(self, repo, session, sample_account, sample_account_outlook):
        repo.add(
            build_event(
                draft_id="draft_gmail",
                account_id=sample_account.id,
                initial="a",
                final="abc def ghi",
            )
        )
        repo.add(
            build_event(
                draft_id="draft_outlook",
                account_id=sample_account_outlook.id,
                initial="b",
                final="bcd efg hij",
            )
        )
        session.commit()

        gmail_events = repo.list_for_account(sample_account.id)
        outlook_events = repo.list_for_account(sample_account_outlook.id)
        assert [e.draft_id for e in gmail_events] == ["draft_gmail"]
        assert [e.draft_id for e in outlook_events] == ["draft_outlook"]

    def test_category_counts(self, repo, session, account_id):
        # Deux length_adjustment + un minor_typo_fix.
        for _ in range(2):
            repo.add(
                build_event(
                    draft_id="d",
                    account_id=account_id,
                    initial="a" * 100,
                    final="a" * 40,
                )
            )
        repo.add(
            build_event(
                draft_id="d",
                account_id=account_id,
                initial="Hello Marc today.",
                final="Hello Marc today!",
            )
        )
        session.commit()

        counts = repo.category_counts(account_id)
        assert counts.get("length_adjustment") == 2
        assert counts.get("minor_typo_fix") == 1
