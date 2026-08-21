"""
Tests TDD pour l'intégration de DraftCorrectionManager dans le daemon.

Ces tests vérifient que:
1. DraftCorrectionManager est correctement initialisé dans EmailDaemon
2. Les corrections apprises sont appliquées lors de la génération de brouillons
3. Les modifications utilisateur sont détectées et enregistrées
4. Le contexte inclut les métadonnées pertinentes
"""

from unittest.mock import MagicMock, patch
import pytest

from app.daemon import EmailDaemon
from app.draft_correction import DraftCorrectionManager


@pytest.fixture
def mock_container():
    with patch("app.daemon.get_container") as mock:
        container = MagicMock()
        container.get_processed_emails_tracker.return_value = MagicMock()
        container.get_processed_drafts_tracker.return_value = MagicMock()
        container.get_learning_service.return_value = MagicMock()
        container.get_draft_history.return_value = MagicMock()
        container.get_commitment_tracker.return_value = MagicMock()
        mock.return_value = container
        yield container


@pytest.fixture
def mock_dependencies(mock_container):
    # F-02 (audit 2026-05-14): `ClassifierAgent` and `TaskExtractorAgent` were
    # removed from `app.daemon` during the 2026-05-05 dead-code purge. The
    # corresponding `patch("app.daemon.ClassifierAgent")` / `TaskExtractorAgent`
    # entries were left dangling here and raised `AttributeError` at fixture
    # setup time, failing all 24 tests in this module at collection. Dropped
    # those patches + their `mock_*.return_value = MagicMock()` setups; the
    # remaining patches still resolve against the current `app.daemon` symbols.
    with patch("app.daemon.get_email_provider") as mock_provider, \
         patch("app.daemon.get_message_router") as mock_router, \
         patch("app.daemon.DrafterAgent") as mock_drafter, \
         patch("app.daemon.CriticAgent") as mock_critic, \
         patch("app.daemon.PrioritizationAgent") as mock_prioritizer, \
         patch("app.daemon.DraftCompletionAgent") as mock_completion, \
         patch("app.daemon.TaskRepository") as mock_task_repo, \
         patch("app.daemon.PhishingDetector") as mock_phishing, \
         patch("app.daemon.CommitmentExtractorAgent") as mock_commitment, \
         patch("app.daemon.CommitmentTrackingUseCase") as mock_commitment_uc, \
         patch("app.daemon.SensitiveDataDetectorAgent") as mock_sensitive:
        mock_provider.return_value = MagicMock()
        mock_router.return_value = MagicMock()
        mock_drafter.return_value = MagicMock()
        mock_critic.return_value = MagicMock()
        mock_prioritizer.return_value = MagicMock()
        mock_completion.return_value = MagicMock()
        mock_task_repo.return_value = MagicMock()
        mock_phishing.return_value = MagicMock()
        mock_commitment.return_value = MagicMock()
        mock_commitment_uc.return_value = MagicMock()
        mock_sensitive.return_value = MagicMock()
        yield {
            "provider": mock_provider,
            "router": mock_router,
            "drafter": mock_drafter,
            "critic": mock_critic,
        }


@pytest.fixture
def mock_correction_manager(mock_dependencies):
    """Fixture pour mocker DraftCorrectionManager avec valeurs par défaut."""
    with patch("app.daemon.get_correction_manager") as mock_get_cm:
        mock_cm = MagicMock(spec=DraftCorrectionManager)
        # Valeurs par défaut (peuvent être overridées dans les tests)
        mock_cm.apply_learned_corrections.return_value = ("Original draft V1", [])
        mock_cm.detect_user_modification.return_value = False
        mock_get_cm.return_value = mock_cm
        yield mock_cm


class TestCorrectionManagerInitialization:
    def test_correction_manager_initialized(self, mock_correction_manager):
        daemon = EmailDaemon()

        assert daemon.correction_manager is not None
        assert daemon.correction_manager == mock_correction_manager

    def test_correction_manager_uses_singleton(self, mock_dependencies):
        with patch("app.daemon.get_correction_manager") as mock_get_cm:
            mock_cm = MagicMock(spec=DraftCorrectionManager)
            mock_get_cm.return_value = mock_cm

            EmailDaemon()

            mock_get_cm.assert_called_once()






















