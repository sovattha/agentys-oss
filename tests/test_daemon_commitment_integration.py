# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests d'intégration pour la détection automatique des engagements dans le daemon.

Ces tests vérifient que le daemon détecte et enregistre automatiquement
les engagements (commitments) faits dans les emails envoyés.

TDD: Ces tests sont écrits AVANT l'implémentation (RED phase).
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from app.daemon import EmailDaemon
from app.interfaces.email_provider import StandardEmail
from app.infrastructure.adapters.processed_emails_adapter import (
    InMemoryProcessedEmailsTracker,
)
from app.agents import CommitmentExtractorAgent, ExtractedCommitment
from app.application.commitment_tracking import CommitmentTrackingUseCase


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_email():
    """Email de test pour simulation de réception."""
    return StandardEmail(
        id="test-email-123",
        sender="client@example.com",
        sender_name="Client",
        to=["user@example.com"],
        cc=[],
        subject="Request for proposal",
        body="Please send me your proposal for the project.",
        body_html="<p>Please send me your proposal.</p>",
        received_at=datetime.now().isoformat(),
        is_read=False,
        has_attachments=False,
        conversation_id="thread-123",
        provider_source="test",
    )


@pytest.fixture
def mock_sent_email():
    """Email envoyé contenant un engagement."""
    return StandardEmail(
        id="sent-email-456",
        sender="user@example.com",
        sender_name="User",
        to=["client@example.com"],
        cc=[],
        subject="Re: Request for proposal",
        body="Je vous envoie ma proposition demain. Je vous rappelle vendredi.",
        body_html="<p>Je vous envoie ma proposition demain.</p>",
        received_at=datetime.now().isoformat(),
        is_read=True,
        has_attachments=False,
        conversation_id="thread-123",
        provider_source="test",
    )


@pytest.fixture
def mock_provider(mock_email):
    """Provider mock."""
    provider = MagicMock()
    provider.authenticate.return_value = True
    provider.get_unread_messages.return_value = [mock_email]
    provider.create_draft.return_value = "draft-456"
    provider.mark_as_read.return_value = True
    provider.apply_label.return_value = True
    provider.get_sent_messages.return_value = []
    provider.get_user_drafts.return_value = []
    return provider


@pytest.fixture
def mock_drafter():
    """Drafter agent mock."""
    drafter = MagicMock()
    drafter.draft.return_value = "Je vous envoie le document demain."
    drafter.revise.return_value = "Revised response."
    return drafter


@pytest.fixture
def mock_critic():
    """Critic agent mock."""
    critic = MagicMock()
    critic.evaluate.return_value = "VALID"
    critic.is_valid.return_value = True
    return critic


@pytest.fixture
def mock_prioritizer():
    """Prioritizer mock."""
    prioritizer = MagicMock()
    prioritizer.analyze.return_value = {"priority_score": 75}
    return prioritizer


@pytest.fixture
def mock_classifier():
    """Classifier mock."""
    classifier = MagicMock()
    classifier.classify.return_value = {"category": "NORMAL"}
    classifier.should_skip.return_value = False
    return classifier


@pytest.fixture
def mock_learning_manager():
    """Learning manager mock."""
    manager = MagicMock()
    manager.should_require_review.return_value = False
    manager.get_stats.return_value = {"patterns_count": 0}
    return manager


@pytest.fixture
def mock_tracker():
    """Tracker en mémoire."""
    return InMemoryProcessedEmailsTracker()


@pytest.fixture
def mock_draft_history():
    """Draft history mock."""
    history = MagicMock()
    history.add.return_value = None
    history.get_by_id.return_value = None
    history.get_all.return_value = []
    history.count.return_value = 0
    return history


@pytest.fixture
def mock_draft_completion_agent():
    """Draft completion agent mock."""
    agent = MagicMock()
    agent.is_completion_request.return_value = False
    return agent


@pytest.fixture
def mock_processed_drafts_tracker():
    """Processed drafts tracker mock."""
    tracker = MagicMock()
    tracker.is_processed.return_value = False
    tracker.mark_processed.return_value = None
    tracker.count.return_value = 0
    return tracker


@pytest.fixture
def mock_message_router():
    """Message router mock."""
    router = MagicMock()
    router.route.return_value = MagicMock(routing_decision=None, supervision_result=None)
    router.get_final_agent_id.return_value = "default_agent"
    return router


@pytest.fixture
def mock_task_extractor():
    """Task extractor mock."""
    extractor = MagicMock()
    extractor.extract.return_value = []
    return extractor


@pytest.fixture
def mock_commitment_extractor():
    """Commitment extractor mock retournant des engagements."""
    extractor = MagicMock(spec=CommitmentExtractorAgent)
    extractor.extract.return_value = [
        ExtractedCommitment(
            description="Envoyer la proposition",
            deadline="2024-01-15"
        ),
        ExtractedCommitment(
            description="Rappeler vendredi",
            deadline=None
        ),
    ]
    return extractor


@pytest.fixture
def mock_commitment_tracker():
    """Commitment tracker mock (port implementation)."""
    tracker = MagicMock()
    tracker.add_commitment.return_value = None
    tracker.get_pending.return_value = []
    tracker.get_by_email.return_value = []
    tracker.get_by_id.return_value = None
    tracker.get_all.return_value = []
    tracker.mark_completed.return_value = True
    tracker.mark_cancelled.return_value = True
    tracker.get_overdue.return_value = []
    return tracker


@pytest.fixture
def mock_commitment_use_case(mock_commitment_tracker):
    """Use case pour le suivi des engagements."""
    return CommitmentTrackingUseCase(tracker=mock_commitment_tracker)


# ============================================================================
# TESTS - DAEMON COMMITMENT INTEGRATION
# ============================================================================


class TestDaemonCommitmentExtraction:
    """Tests pour l'extraction automatique des engagements dans le daemon."""

    def test_daemon_has_commitment_extractor_attribute(
        self,
        mock_provider,
        mock_drafter,
        mock_critic,
        mock_prioritizer,
        mock_classifier,
        mock_learning_manager,
        mock_tracker,
        mock_draft_history,
        mock_draft_completion_agent,
        mock_processed_drafts_tracker,
        mock_message_router,
        mock_task_extractor,
        mock_commitment_extractor,
        mock_commitment_use_case,
    ):
        """Le daemon doit avoir un attribut commitment_extractor."""
        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=mock_tracker,
            draft_history=mock_draft_history,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
            commitment_extractor=mock_commitment_extractor,
            commitment_use_case=mock_commitment_use_case,
        )

        assert hasattr(daemon, "commitment_extractor")
        assert daemon.commitment_extractor is not None

    def test_daemon_has_commitment_use_case_attribute(
        self,
        mock_provider,
        mock_drafter,
        mock_critic,
        mock_prioritizer,
        mock_classifier,
        mock_learning_manager,
        mock_tracker,
        mock_draft_history,
        mock_draft_completion_agent,
        mock_processed_drafts_tracker,
        mock_message_router,
        mock_task_extractor,
        mock_commitment_extractor,
        mock_commitment_use_case,
    ):
        """Le daemon doit avoir un attribut commitment_use_case."""
        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=mock_tracker,
            draft_history=mock_draft_history,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
            commitment_extractor=mock_commitment_extractor,
            commitment_use_case=mock_commitment_use_case,
        )

        assert hasattr(daemon, "commitment_use_case")
        assert daemon.commitment_use_case is not None

    def test_poll_user_drafts_extracts_commitments_on_successful_completion(self):
        """Regression test for audit F-01 (2026-05-15).

        The auto-draft graveyard removal in 864e1fd2 deleted
        ``EmailDaemon._extract_commitments_from_draft`` but missed the
        live caller in ``poll_user_drafts``. The fix in 344e08b6 inlined
        a try/except at the call site that calls
        ``self.commitment_extractor.extract(new_body)`` followed by
        ``self.commitment_use_case.track_from_extracted(...)``. This
        test pins both calls so a future refactor can't silently drop
        commitment extraction on the user-draft completion path.
        """
        from unittest.mock import MagicMock, patch
        from app.daemon import EmailDaemon
        from app.interfaces.email_provider import StandardEmail

        draft_id = "draft-with-commitment"
        original_body = "Brouillon:\n- Confirm Friday call with Marie"

        provider = MagicMock()
        provider.get_user_drafts.return_value = [
            StandardEmail(
                id=draft_id,
                sender="user@example.com",
                to=["marie@example.com"],
                subject="",
                body=original_body,
                provider_source="mock",
                raw_metadata={"is_user_draft": True},
            )
        ]
        provider.update_draft.return_value = True

        completion_agent = MagicMock()
        completion_agent.is_completion_request.return_value = True
        completion_agent.complete_with_options.return_value = MagicMock(
            body="Hi Marie, confirming our call Friday at 3pm.",
            subject="Confirming Friday call",
        )

        commitment_extractor = MagicMock()
        commitment_extractor.extract.return_value = [
            ExtractedCommitment(
                description="Call Marie Friday at 3pm",
                deadline="2026-05-22",
            )
        ]

        commitment_use_case = MagicMock()
        commitment_use_case.track_from_extracted.return_value = []

        processed_drafts_tracker = MagicMock()
        processed_drafts_tracker.is_processed.return_value = False

        # Bypass the full EmailDaemon constructor — only the attributes
        # touched by poll_user_drafts need to exist.
        daemon = EmailDaemon.__new__(EmailDaemon)
        daemon.provider = provider
        daemon.processed_drafts_tracker = processed_drafts_tracker
        daemon.draft_completion_agent = completion_agent
        daemon.commitment_extractor = commitment_extractor
        daemon.commitment_use_case = commitment_use_case

        with patch("app.daemon.audit_logger"), patch("app.daemon.notify"):
            daemon.poll_user_drafts()

        # Both inlined calls must fire on the success path. If a future
        # refactor drops them, this assertion catches the regression
        # before the AttributeError ships to prod.
        assert commitment_extractor.extract.called, (
            "commitment_extractor.extract was not called on successful draft completion"
        )
        commitment_extractor.extract.assert_called_once_with(
            "Hi Marie, confirming our call Friday at 3pm."
        )
        assert commitment_use_case.track_from_extracted.called, (
            "commitment_use_case.track_from_extracted was not called after extraction"
        )
        # The use case must receive the draft id (NOT the original email id)
        # so the commitment links back to the completed draft.
        track_call = commitment_use_case.track_from_extracted.call_args
        assert track_call.args[1] == draft_id, (
            f"track_from_extracted received wrong id: {track_call.args[1]!r} != {draft_id!r}"
        )






# ============================================================================
# EDGE CASES - COMMITMENT INTEGRATION
# ============================================================================


