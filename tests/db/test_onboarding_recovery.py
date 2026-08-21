"""Test pour OnboardingManager.recover_orphaned_waiting (#onboarding-restart-bug).

Symptôme observé : après un redémarrage backend pendant qu'un onboarding est
en 'waiting_for_sync' ou 'running', le thread in-memory meurt mais la ligne
DB reste dans cet état. Le frontend voit un 'en attente...' sans fin.

Le fix : au démarrage de l'app (run_api.py), on marque ces lignes comme
failed pour que le frontend puisse les détecter et relancer /onboarding/start.
"""

from datetime import datetime

import pytest

from app.db.models import OnboardingResult
from app.onboarding.manager import OnboardingManager


@pytest.fixture
def manager(engine):
    """Create a manager using the test engine from conftest."""
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return OnboardingManager(session_factory=factory)


@pytest.fixture
def account(session, sample_account):
    return sample_account


def _create_onboarding(session, account_id: int, status: str) -> OnboardingResult:
    row = OnboardingResult(
        account_id=account_id,
        status=status,
        created_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    return row


class TestRecoverOrphanedWaiting:
    def test_marks_waiting_for_sync_as_failed(self, manager, session, account):
        _create_onboarding(session, account.id, "waiting_for_sync")
        count = manager.recover_orphaned_waiting()
        assert count == 1
        session.expire_all()
        row = session.query(OnboardingResult).filter_by(account_id=account.id).one()
        assert row.status == "failed"
        assert "redémarrage" in (row.error_message or "").lower()

    def test_marks_running_as_failed(self, manager, session, account):
        _create_onboarding(session, account.id, "running")
        count = manager.recover_orphaned_waiting()
        assert count == 1
        session.expire_all()
        row = session.query(OnboardingResult).filter_by(account_id=account.id).one()
        assert row.status == "failed"

    def test_leaves_completed_untouched(self, manager, session, account):
        _create_onboarding(session, account.id, "completed")
        count = manager.recover_orphaned_waiting()
        assert count == 0
        session.expire_all()
        row = session.query(OnboardingResult).filter_by(account_id=account.id).one()
        assert row.status == "completed"

    def test_leaves_failed_untouched(self, manager, session, account):
        _create_onboarding(session, account.id, "failed")
        count = manager.recover_orphaned_waiting()
        assert count == 0
        session.expire_all()
        row = session.query(OnboardingResult).filter_by(account_id=account.id).one()
        assert row.status == "failed"  # Unchanged

    def test_recovers_multiple_orphans_across_accounts(
        self, manager, session, sample_account, sample_account_outlook
    ):
        _create_onboarding(session, sample_account.id, "waiting_for_sync")
        _create_onboarding(session, sample_account_outlook.id, "running")
        count = manager.recover_orphaned_waiting()
        assert count == 2

    def test_idempotent_second_call_is_noop(self, manager, session, account):
        _create_onboarding(session, account.id, "waiting_for_sync")
        first = manager.recover_orphaned_waiting()
        second = manager.recover_orphaned_waiting()
        assert first == 1
        assert second == 0

    def test_no_orphans_returns_zero(self, manager, session, account):
        count = manager.recover_orphaned_waiting()
        assert count == 0
