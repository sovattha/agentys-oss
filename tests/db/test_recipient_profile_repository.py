"""Tests d'intégration pour RecipientProfileRepository (#190 phase 2)."""

import pytest

from app.db.repositories.recipient_profile_repository import (
    RecipientProfileRepository,
)
from app.domain.entities.recipient_profile import (
    DISCScores,
    DISCType,
    RecipientProfile,
)


@pytest.fixture
def repo(session):
    return RecipientProfileRepository(session)


@pytest.fixture
def account_id(sample_account):
    return sample_account.id


def _make_profile(email: str = "alice@example.com") -> RecipientProfile:
    return RecipientProfile(
        email=email,
        disc=DISCType.CONSCIENTIOUSNESS,
        disc_scores=DISCScores(0.15, 0.20, 0.20, 0.60),
        confidence=0.40,
        sample_size=5,
        source="heuristic",
    )


class TestGet:
    def test_get_returns_none_when_absent(self, repo, account_id):
        assert repo.get(account_id, "missing@example.com") is None

    def test_get_is_case_insensitive(self, repo, session, account_id):
        repo.upsert(account_id, _make_profile("Alice@Example.Com"))
        session.commit()
        assert repo.get(account_id, "alice@EXAMPLE.com") is not None


class TestUpsert:
    def test_insert_new_profile(self, repo, session, account_id):
        repo.upsert(account_id, _make_profile())
        session.commit()
        fetched = repo.get(account_id, "alice@example.com")
        assert fetched is not None
        assert fetched.disc == DISCType.CONSCIENTIOUSNESS
        assert fetched.sample_size == 5

    def test_update_existing_profile(self, repo, session, account_id):
        repo.upsert(account_id, _make_profile())
        session.commit()

        # Le contact se révèle finalement D après plus de données.
        updated = RecipientProfile(
            email="alice@example.com",
            disc=DISCType.DOMINANCE,
            disc_scores=DISCScores(0.70, 0.10, 0.10, 0.20),
            confidence=0.50,
            sample_size=12,
            source="heuristic",
        )
        repo.upsert(account_id, updated)
        session.commit()

        fetched = repo.get(account_id, "alice@example.com")
        assert fetched.disc == DISCType.DOMINANCE
        assert fetched.sample_size == 12
        assert fetched.confidence == 0.50

    def test_scores_roundtrip_via_json(self, repo, session, account_id):
        repo.upsert(account_id, _make_profile())
        session.commit()
        fetched = repo.get(account_id, "alice@example.com")
        assert fetched.disc_scores is not None
        assert fetched.disc_scores.conscientiousness == 0.60


class TestIsolation:
    def test_different_accounts_are_isolated(
        self, repo, session, sample_account, sample_account_outlook
    ):
        repo.upsert(sample_account.id, _make_profile("x@example.com"))
        repo.upsert(sample_account_outlook.id, RecipientProfile(
            email="x@example.com",
            disc=DISCType.DOMINANCE,
            disc_scores=DISCScores(0.6, 0.1, 0.1, 0.2),
            confidence=0.4,
            sample_size=3,
            source="heuristic",
        ))
        session.commit()

        p_gmail = repo.get(sample_account.id, "x@example.com")
        p_outlook = repo.get(sample_account_outlook.id, "x@example.com")
        assert p_gmail.disc == DISCType.CONSCIENTIOUSNESS
        assert p_outlook.disc == DISCType.DOMINANCE


class TestDelete:
    def test_delete_existing(self, repo, session, account_id):
        repo.upsert(account_id, _make_profile())
        session.commit()
        assert repo.delete(account_id, "alice@example.com")
        session.commit()
        assert repo.get(account_id, "alice@example.com") is None

    def test_delete_absent_returns_false(self, repo, account_id):
        assert not repo.delete(account_id, "nobody@example.com")


class TestCount:
    def test_count_for_account(self, repo, session, account_id):
        assert repo.count_for_account(account_id) == 0
        repo.upsert(account_id, _make_profile("a@example.com"))
        repo.upsert(account_id, _make_profile("b@example.com"))
        session.commit()
        assert repo.count_for_account(account_id) == 2


class TestUnknownDiscRoundtrip:
    def test_unknown_disc_preserved(self, repo, session, account_id):
        # Un profil UNKNOWN est valide et doit être re-hydraté correctement.
        profile = RecipientProfile(
            email="mystery@example.com",
            disc=DISCType.UNKNOWN,
            confidence=0.0,
            sample_size=0,
            source="heuristic",
        )
        repo.upsert(account_id, profile)
        session.commit()

        fetched = repo.get(account_id, "mystery@example.com")
        assert fetched.disc == DISCType.UNKNOWN
        assert not fetched.is_reliable()
