# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests d'intégration pour le daemon.

Couvre:
- Lifecycle du daemon (start/stop)
- Pipeline de traitement complet
- Gestion des erreurs
- Health check
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.daemon import EmailDaemon
from app.interfaces.email_provider import StandardEmail
from app.infrastructure.adapters.processed_emails_adapter import (
    InMemoryProcessedEmailsTracker,
    JsonProcessedEmailsTracker,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_email():
    """Crée un email mock pour les tests."""
    return StandardEmail(
        id="test-email-123",
        sender="sender@example.com",
        sender_name="John Doe",
        to=["recipient@example.com"],
        cc=[],
        subject="Test Subject",
        body="Hello, this is a test email. Please respond.",
        body_html="<p>Hello, this is a test email.</p>",
        received_at=datetime.now().isoformat(),
        is_read=False,
        has_attachments=False,
        conversation_id="thread-123",
        provider_source="test",
    )


@pytest.fixture
def mock_provider(mock_email):
    """Crée un provider mock."""
    provider = MagicMock()
    provider.authenticate.return_value = True
    provider.get_unread_messages.return_value = [mock_email]
    provider.get_messages.return_value = [mock_email]  # méthode actuelle de poll_and_process
    provider.create_draft.return_value = "draft-456"
    provider.mark_as_read.return_value = True
    provider.apply_label.return_value = True
    return provider


@pytest.fixture
def mock_drafter():
    """Crée un drafter agent mock."""
    drafter = MagicMock()
    drafter.draft.return_value = "This is a generated response."
    drafter.revise.return_value = "This is a revised response."
    return drafter


@pytest.fixture
def mock_critic():
    """Crée un critic agent mock."""
    critic = MagicMock()
    critic.evaluate.return_value = "VALID: Response is appropriate."
    critic.is_valid.return_value = True
    return critic


@pytest.fixture
def mock_prioritizer():
    """Crée un prioritizer agent mock."""
    prioritizer = MagicMock()
    prioritizer.analyze.return_value = {"priority_score": 75}
    return prioritizer


@pytest.fixture
def mock_classifier():
    """Crée un classifier agent mock."""
    classifier = MagicMock()
    classifier.classify.return_value = {"category": "NORMAL"}
    classifier.should_skip.return_value = False
    return classifier


@pytest.fixture
def mock_learning_manager():
    """Crée un learning manager mock."""
    manager = MagicMock()
    manager.should_require_review.return_value = False
    manager.get_stats.return_value = {"patterns_count": 0}
    return manager


@pytest.fixture
def temp_tracker(tmp_path):
    """Crée un tracker temporaire (Clean Architecture adapter)."""
    return JsonProcessedEmailsTracker(tmp_path / "processed.json")


@pytest.fixture
def mock_tracker():
    """Crée un tracker en memoire pour les tests."""
    return InMemoryProcessedEmailsTracker()


@pytest.fixture
def mock_draft_history():
    """Crée un mock du draft history port."""
    history = MagicMock()
    history.add.return_value = None
    history.get_by_id.return_value = None
    history.get_all.return_value = []
    history.count.return_value = 0
    return history


@pytest.fixture
def mock_draft_completion_agent():
    """Crée un mock du draft completion agent."""
    agent = MagicMock()
    agent.is_completion_request.return_value = False
    agent.complete_with_options.return_value = MagicMock(
        subject="Completed Subject",
        body="Completed body"
    )
    return agent


@pytest.fixture
def mock_processed_drafts_tracker():
    """Crée un mock du processed drafts tracker."""
    tracker = MagicMock()
    tracker.is_processed.return_value = False
    tracker.mark_processed.return_value = None
    tracker.count.return_value = 0
    return tracker


@pytest.fixture
def mock_message_router():
    """Crée un mock du message router."""
    router = MagicMock()
    router.route.return_value = MagicMock(routing_decision=None, supervision_result=None)
    router.get_final_agent_id.return_value = "default_agent"
    return router


@pytest.fixture
def mock_task_extractor():
    """Crée un mock du TaskExtractorAgent."""
    extractor = MagicMock()
    extractor.extract.return_value = []
    return extractor


@pytest.fixture
def mock_container():
    """Mock du container IoC pour isoler les tests pipeline du store réel."""
    mock_draft_store = MagicMock()
    mock_draft_store.get_by_email_id.return_value = None  # pas de draft existant
    mock_label_store = MagicMock()
    mock_label_store.get_assignment.return_value = None  # pas de label Action
    container = MagicMock()
    container.get_pending_draft_store.return_value = mock_draft_store
    container.get_label_store.return_value = mock_label_store
    with patch('app.daemon.get_container', return_value=container):
        yield container


# ============================================================================
# TESTS PROCESSED EMAILS TRACKER
# ============================================================================

class TestProcessedEmailsTracker:
    """Tests pour JsonProcessedEmailsTracker (Clean Architecture adapter)."""

    def test_init_empty(self, tmp_path):
        """Initialisation avec fichier inexistant."""
        tracker = JsonProcessedEmailsTracker(tmp_path / "new.json")

        assert tracker.count() == 0

    def test_mark_and_check(self, tmp_path):
        """Marquer et vérifier un email."""
        tracker = JsonProcessedEmailsTracker(tmp_path / "test.json")

        assert not tracker.is_processed("email-1")

        tracker.mark_processed("email-1")

        assert tracker.is_processed("email-1")

    def test_persistence(self, tmp_path):
        """Persistance entre instances."""
        filepath = tmp_path / "persist.json"

        # Premier tracker
        tracker1 = JsonProcessedEmailsTracker(filepath)
        tracker1.mark_processed("email-a")
        tracker1.mark_processed("email-b")

        # Deuxième tracker (recharge depuis le fichier)
        tracker2 = JsonProcessedEmailsTracker(filepath)

        assert tracker2.is_processed("email-a")
        assert tracker2.is_processed("email-b")
        assert tracker2.count() == 2

    def test_count(self, tmp_path):
        """Le comptage est correct."""
        tracker = JsonProcessedEmailsTracker(tmp_path / "count.json")

        tracker.mark_processed("e1")
        tracker.mark_processed("e2")
        tracker.mark_processed("e3")

        assert tracker.count() == 3


# ============================================================================
# TESTS DAEMON LIFECYCLE
# ============================================================================

class TestDaemonLifecycle:
    """Tests pour le lifecycle du daemon."""

    def test_daemon_init(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor
    ):
        """Initialisation du daemon."""
        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
            poll_interval=1,
        )

        assert daemon.provider is not None
        assert daemon.drafter is not None
        assert daemon._running is False

    def test_daemon_health_check(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor
    ):
        """Health check au démarrage."""
        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
        )

        health = daemon.health_check()

        assert health["email_provider"] is True
        assert health["llm"] is True
        assert health["overall"] is True

    def test_daemon_health_check_fails_provider(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """Health check échoue si provider échoue."""
        mock_provider.authenticate.return_value = False

        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
        )

        health = daemon.health_check()

        assert health["email_provider"] is False
        assert health["overall"] is False

    def test_daemon_stop(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """Arrêt propre du daemon."""
        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
            poll_interval=1,
        )

        # Simuler un démarrage dans un thread
        daemon._running = True
        daemon._stop_event.clear()

        # Appeler stop
        daemon.stop()

        assert daemon._running is False
        assert daemon._stop_event.is_set()

    def test_daemon_run_once(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager,
        mock_tracker, mock_draft_history, mock_email,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """run_once traite un seul cycle."""
        mock_provider.get_unread_messages.return_value = [mock_email]
        mock_provider.get_messages.return_value = [mock_email]

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
        )

        with patch('app.daemon.audit_logger'), \
             patch('app.agents.token_counter'):
            processed = daemon.run_once()

        assert processed == 1
        assert mock_tracker.is_processed(mock_email.id)


# ============================================================================
# TESTS PIPELINE TRAITEMENT
# ============================================================================

class TestPipelineTraitement:
    """Tests pour le pipeline de traitement des emails."""

    def test_process_email_success(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager,
        mock_tracker, mock_draft_history, mock_email,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor, mock_container    ):
        """Traitement réussi d'un email.

        Note: auto-draft is disabled so process_email() returns True
        after auto-labeling without reaching draft generation.
        """
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
        )

        with patch('app.daemon.audit_logger'), \
             patch('app.agents.token_counter'), \
             patch.object(daemon, '_has_noise_or_fyi_label', return_value=False):
            success = daemon.process_email(mock_email)

        # Auto-draft disabled: process_email returns True but skips draft generation
        assert success is True
        mock_drafter.draft.assert_not_called()
        mock_provider.create_draft.assert_not_called()

    def test_process_email_with_revision(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager,
        mock_tracker, mock_draft_history, mock_email,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor, mock_container    ):
        """Traitement avec révision (critique invalide).

        Note: auto-draft is disabled so process_email() returns True
        after auto-labeling. Draft generation (and revision) is not reached.
        Test _generate_draft directly for revision logic.
        """
        mock_critic.is_valid.return_value = False

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
        )

        with patch('app.daemon.audit_logger'), \
             patch('app.agents.token_counter'), \
             patch.object(daemon, '_has_noise_or_fyi_label', return_value=False):
            success = daemon.process_email(mock_email)

        # Auto-draft disabled: process_email returns True but skips draft generation
        assert success is True
        mock_drafter.revise.assert_not_called()

    def test_process_email_skip_auto_reply(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """Les auto-replies sont ignorés."""
        auto_reply_email = StandardEmail(
            id="auto-reply-123",
            sender="noreply@example.com",
            to=["user@example.com"],
            subject="Out of Office: Re: Your message",
            body="I am currently out of office.",
            received_at=datetime.now().isoformat(),
        )

        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
        )

        with patch('app.daemon.audit_logger'):
            success = daemon.process_email(auto_reply_email)

        assert success is True
        # Pas de draft généré pour un auto-reply
        mock_drafter.draft.assert_not_called()

    def test_process_email_skip_low_priority(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker, mock_email,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """Les emails à basse priorité sont ignorés si configuré."""
        mock_classifier.classify.return_value = {"category": "NEWSLETTER"}
        mock_classifier.should_skip.return_value = True

        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
            skip_low_priority=True,
        )

        with patch('app.daemon.audit_logger'):
            success = daemon.process_email(mock_email)

        assert success is True
        mock_drafter.draft.assert_not_called()

    def test_process_email_action_label_overrides_skip_low_priority(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager,
        mock_tracker, mock_draft_history, mock_email,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """Un email classé NEWSLETTER avec label Action: auto-draft disabled returns True.

        Note: auto-draft is disabled so even with Action label,
        process_email() returns True at step 2.6b without generating a draft.
        The Action label override logic exists but is unreachable while auto-draft is off.
        """
        mock_classifier.classify.return_value = {"category": "NEWSLETTER"}
        mock_classifier.should_skip.return_value = True

        # Label store retourne "Action" pour cet email
        mock_label_store = MagicMock()
        mock_assignment = MagicMock()
        mock_assignment.labels = ["Action"]
        mock_label_store.get_assignment.return_value = mock_assignment

        mock_draft_store = MagicMock()
        mock_draft_store.get_by_email_id.return_value = None

        container = MagicMock()
        container.get_pending_draft_store.return_value = mock_draft_store
        container.get_label_store.return_value = mock_label_store

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
            skip_low_priority=True,
        )

        with patch('app.daemon.get_container', return_value=container), \
             patch('app.daemon.audit_logger'), \
             patch('app.agents.token_counter'), \
             patch.object(daemon, '_has_noise_or_fyi_label', return_value=False):
            success = daemon.process_email(mock_email)

        assert success is True
        # Auto-draft disabled: draft not generated even with Action label
        mock_drafter.draft.assert_not_called()

    def test_process_email_draft_failure(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager,
        mock_tracker, mock_draft_history, mock_email,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor, mock_container    ):
        """Gestion d'échec de création de brouillon.

        Note: auto-draft is disabled so process_email() returns True
        without reaching draft creation. Draft failure is tested via
        _create_and_save_draft() directly.
        """
        mock_provider.create_draft.return_value = None

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
        )

        with patch('app.daemon.audit_logger'), \
             patch('app.agents.token_counter'), \
             patch.object(daemon, '_has_noise_or_fyi_label', return_value=False):
            success = daemon.process_email(mock_email)

        # Auto-draft disabled: returns True (email processed, just no draft generated)
        assert success is True


# ============================================================================
# TESTS POLLING ET PRIORISATION
# ============================================================================

class TestPollingAndPrioritization:
    """Tests pour le polling et la priorisation."""

    def test_poll_and_process_empty(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """Polling sans emails."""
        mock_provider.get_unread_messages.return_value = []
        mock_provider.get_messages.return_value = []

        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
        )

        processed = daemon.poll_and_process()

        assert processed == 0

    def test_poll_skips_already_processed(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker, mock_email,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor, mock_container    ):
        """Les emails déjà traités sont ignorés."""
        temp_tracker.mark_processed(mock_email.id)
        mock_provider.get_unread_messages.return_value = [mock_email]
        mock_provider.get_messages.return_value = [mock_email]

        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
        )

        processed = daemon.poll_and_process()

        assert processed == 0
        mock_drafter.draft.assert_not_called()

    def test_poll_prioritizes_emails(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager,
        mock_tracker, mock_draft_history,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """Les emails sont triés par priorité."""
        email1 = StandardEmail(
            id="email-1",
            sender="normal@example.com",
            to=["user@example.com"],
            subject="Normal email",
            body="Normal content",
            received_at=datetime.now().isoformat(),
        )
        email2 = StandardEmail(
            id="email-2",
            sender="urgent@example.com",
            to=["user@example.com"],
            subject="URGENT: Important",
            body="Urgent content",
            received_at=datetime.now().isoformat(),
        )

        mock_provider.get_unread_messages.return_value = [email1, email2]
        mock_provider.get_messages.return_value = [email1, email2]

        # email2 a une priorité plus élevée
        def mock_analyze(content, sender):
            if "urgent" in sender.lower():
                return {"priority_score": 90}
            return {"priority_score": 50}

        mock_prioritizer.analyze.side_effect = mock_analyze

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
        )

        with patch('app.daemon.audit_logger'), \
             patch('app.agents.token_counter'):
            processed = daemon.poll_and_process()

        assert processed == 2


# ============================================================================
# TESTS LEARNING
# ============================================================================

class TestLearning:
    """Tests pour l'intégration du learning."""

    def test_run_learning_analysis(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """L'analyse learning s'exécute sans erreur."""
        mock_learning_manager.analyze_feedback.return_value = {"total_with_feedback": 5}
        mock_learning_manager.extract_patterns_from_feedback.return_value = []

        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
        )

        # Should not raise
        daemon.run_learning_analysis()

        mock_learning_manager.analyze_feedback.assert_called_once()


# ============================================================================
# TESTS HELPERS
# ============================================================================

class TestHelpers:
    """Tests pour les méthodes utilitaires."""

    def test_format_email_for_agent(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker, mock_email,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """Formatage d'email pour les agents."""
        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
        )

        formatted = daemon._format_email_for_agent(mock_email)

        assert "John Doe" in formatted
        assert "sender@example.com" in formatted
        assert "Test Subject" in formatted
        assert mock_email.body in formatted

    def test_generate_reply_subject(
        self, mock_provider, mock_drafter, mock_critic,
        mock_prioritizer, mock_classifier, mock_learning_manager, temp_tracker,
        mock_draft_completion_agent, mock_processed_drafts_tracker, mock_message_router,
        mock_task_extractor    ):
        """Génération du sujet de réponse."""
        daemon = EmailDaemon(
            provider=mock_provider,
            drafter=mock_drafter,
            critic=mock_critic,
            prioritizer=mock_prioritizer,
            classifier=mock_classifier,
            learning_manager=mock_learning_manager,
            tracker=temp_tracker,
            draft_completion_agent=mock_draft_completion_agent,
            processed_drafts_tracker=mock_processed_drafts_tracker,
            message_router=mock_message_router,
            task_extractor=mock_task_extractor,
        )

        # Sujet normal
        assert daemon._generate_reply_subject("Hello") == "Re: Hello"

        # Sujet déjà en Re:
        assert daemon._generate_reply_subject("Re: Hello") == "Re: Hello"
        assert daemon._generate_reply_subject("RE: Hello") == "RE: Hello"
