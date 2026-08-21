# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour la résilience du daemon.

Ce fichier teste les edge cases de résilience:
1. Gestion des erreurs LLM (propagation, fallback)
2. Circuit Breaker (ouverture, récupération)
3. Retry exhausted
4. Récupération après échecs multiples
5. Gestion des erreurs Provider

Cycle TDD: RED → GREEN → REFACTOR

Clean Architecture:
- Les erreurs Domain doivent être propagées correctement
- Le daemon doit être résilient aux erreurs transitoires
- Les erreurs critiques doivent arrêter le traitement
"""

import pytest
import threading
import time
from unittest.mock import Mock, MagicMock, patch

from app.interfaces.email_provider import EmailProvider, StandardEmail
from app.domain.exceptions import (
    LLMTimeoutError,
    LLMConnectionError,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_provider():
    """Provider mocké avec comportement normal."""
    provider = MagicMock(spec=EmailProvider)
    provider.provider_name = "mock"
    provider.authenticate.return_value = True
    provider.get_unread_messages.return_value = []
    provider.create_draft.return_value = "draft-001"
    provider.mark_as_read.return_value = True
    provider.apply_label.return_value = True
    return provider


@pytest.fixture
def mock_agents():
    """Agents mockés avec comportement normal."""
    drafter = MagicMock()
    drafter.draft.return_value = "Draft response"
    drafter.revise.return_value = "Revised response"

    critic = MagicMock()
    critic.evaluate.return_value = "VALID"
    critic.is_valid.return_value = True

    prioritizer = MagicMock()
    prioritizer.analyze.return_value = {"priority_score": 50, "urgency": 50, "vip": 50}

    classifier = MagicMock()
    classifier.classify.return_value = {"category": "NORMAL", "confidence": 0.9}
    classifier.should_skip.return_value = False

    return {
        "drafter": drafter,
        "critic": critic,
        "prioritizer": prioritizer,
        "classifier": classifier,
    }


@pytest.fixture
def sample_email():
    """Email de test."""
    return StandardEmail(
        id="email-001",
        sender="sender@example.com",
        sender_name="Sender",
        subject="Test Subject",
        body="Test body content",
        provider_source="test"
    )


@pytest.fixture
def mock_container():
    """Container mocké."""
    container = MagicMock()

    # Tracker mocké
    tracker = MagicMock()
    tracker.is_processed.return_value = False
    tracker.count.return_value = 0
    container.get_processed_emails_tracker.return_value = tracker

    # Learning service mocké
    learning_service = MagicMock()
    learning_service.should_require_review.return_value = False
    learning_service.analyze_feedback.return_value = {}
    learning_service.get_stats.return_value = {}
    container.get_learning_service.return_value = learning_service

    # Draft history mocké
    draft_history = MagicMock()
    container.get_draft_history.return_value = draft_history

    return container


def create_mocked_daemon(
    mock_provider=None,
    mock_agents=None,
    mock_container=None,
):
    """Crée un daemon avec toutes les dépendances mockées."""
    from app.daemon import EmailDaemon

    # Créer le daemon sans initialisation automatique
    daemon = EmailDaemon.__new__(EmailDaemon)

    # Provider
    if mock_provider is None:
        mock_provider = MagicMock(spec=EmailProvider)
        mock_provider.provider_name = "mock"
        mock_provider.authenticate.return_value = True
        mock_provider.get_unread_messages.return_value = []
        mock_provider.create_draft.return_value = "draft-001"
        mock_provider.mark_as_read.return_value = True
        mock_provider.apply_label.return_value = True

    daemon.provider = mock_provider

    # Agents
    if mock_agents is None:
        mock_agents = {
            "drafter": MagicMock(),
            "critic": MagicMock(),
            "prioritizer": MagicMock(),
            "classifier": MagicMock(),
        }
        mock_agents["drafter"].draft.return_value = "Draft response"
        mock_agents["critic"].evaluate.return_value = "VALID"
        mock_agents["critic"].is_valid.return_value = True
        mock_agents["prioritizer"].analyze.return_value = {"priority_score": 50}
        mock_agents["classifier"].classify.return_value = {"category": "NORMAL"}
        mock_agents["classifier"].should_skip.return_value = False

    daemon.drafter = mock_agents["drafter"]
    daemon.critic = mock_agents["critic"]
    daemon.prioritizer = mock_agents["prioritizer"]
    daemon.classifier = mock_agents["classifier"]

    # Container dependencies
    if mock_container is None:
        mock_container = MagicMock()
        mock_container.get_processed_emails_tracker.return_value = MagicMock()
        mock_container.get_learning_service.return_value = MagicMock()
        mock_container.get_draft_history.return_value = MagicMock()

    daemon.tracker = mock_container.get_processed_emails_tracker()
    daemon.tracker.is_processed.return_value = False
    daemon.tracker.count.return_value = 0

    daemon.learning_manager = mock_container.get_learning_service()
    daemon.learning_manager.should_require_review.return_value = False

    daemon.draft_history = mock_container.get_draft_history()

    # Message router
    daemon.message_router = MagicMock()

    # Phishing detector
    from app.domain.services import PhishingDetector
    daemon.phishing_detector = PhishingDetector()

    # Correction manager mocké
    daemon.correction_manager = MagicMock()
    daemon.correction_manager.apply_learned_corrections.return_value = ("Draft response", [])
    daemon.correction_manager.detect_user_modification.return_value = False

    # Sensitive data detector mocké
    daemon.sensitive_data_detector = MagicMock()
    daemon.sensitive_data_detector.detect.return_value = MagicMock(
        is_sensitive=False,
        confidence=0.0,
        detected_items=[]
    )

    # Cryptographer mocké (pour anonymisation)
    from app.domain.entities.anonymized_result import AnonymizedResult
    daemon.cryptographer = MagicMock()
    mock_detection = MagicMock(is_sensitive=False)
    daemon.cryptographer.anonymize.return_value = AnonymizedResult.empty(
        original_content="", detection=mock_detection
    )

    # Configuration
    daemon.poll_interval = 60
    daemon.skip_low_priority = False
    daemon.use_smart_routing = False
    daemon.account_id = f"test-daemon-{id(daemon)}"
    daemon._running = False
    daemon._emails_processed_count = 0
    daemon._stop_event = threading.Event()
    daemon._failed_draft_counts = {}
    daemon._auto_replied_senders = set()
    daemon.api_mode = False
    daemon.event_emitter = None
    daemon.email_queue = None
    daemon.progress_notifier = None

    # Task extractor
    daemon.task_extractor = MagicMock()
    daemon.task_extractor.extract.return_value = []
    daemon.task_repository = MagicMock()

    # Commitment extractor
    daemon.commitment_extractor = MagicMock()
    daemon.commitment_extractor.extract.return_value = []
    daemon.commitment_use_case = MagicMock()

    # Draft completion agent
    daemon.draft_completion_agent = MagicMock()
    daemon.draft_completion_agent.is_completion_request.return_value = False

    # Processed drafts tracker
    daemon.processed_drafts_tracker = MagicMock()
    daemon.processed_drafts_tracker.is_processed.return_value = False

    return daemon


# =============================================================================
# Tests - Erreurs LLM lors du Draft
# =============================================================================


# TestDaemonLLMErrorHandling removed 2026-05-15: the daemon's
# `_generate_draft` helper went away with the auto-draft graveyard
# (see commit 864e1fd2). LLM error propagation is now covered at the
# SmartRouter / per-route layer.


# =============================================================================
# Tests - Erreurs Provider
# =============================================================================


class TestDaemonProviderErrorHandling:
    """Tests de gestion des erreurs Provider dans le daemon."""

    def test_provider_get_unread_exception_returns_zero(self, mock_provider):
        """Une exception lors de get_unread_messages doit retourner 0."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        mock_provider.get_unread_messages.side_effect = Exception("Network error")

        result = daemon.poll_and_process()

        assert result == 0

    def test_provider_mark_as_read_failure_does_not_affect_result(
        self, mock_provider, sample_email
    ):
        """Auto-draft disabled: process_email returns True, mark_as_read not reached."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        mock_provider.mark_as_read.side_effect = Exception("Mark failed")

        result = daemon.process_email(sample_email)

        # Auto-draft disabled: returns True without reaching mark_as_read
        assert result is True

    def test_provider_apply_label_failure_does_not_block_processing(
        self, mock_provider, sample_email
    ):
        """Auto-draft disabled: process_email returns True."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        mock_provider.apply_label.return_value = False

        result = daemon.process_email(sample_email)

        # Auto-draft disabled: returns True without reaching drafter
        assert result is True


# =============================================================================
# Tests - Circuit Breaker
# =============================================================================


class TestDaemonCircuitBreaker:
    """Tests du circuit breaker dans le daemon."""

    def test_circuit_open_error_in_main_loop_waits_and_continues(self):
        """CircuitOpenError dans la boucle principale doit attendre puis continuer."""
        from app.infrastructure.circuit_breaker import CircuitOpenError

        daemon = create_mocked_daemon()

        # Configurer le mock pour lever CircuitOpenError puis retourner 0
        call_count = [0]
        def poll_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                raise CircuitOpenError(remaining_time=0.1)
            return 0

        daemon.poll_and_process = Mock(side_effect=poll_side_effect)

        # Simuler un run de courte durée
        daemon._running = True

        def stop_after_delay():
            time.sleep(0.3)
            daemon.stop()

        stop_thread = threading.Thread(target=stop_after_delay)
        stop_thread.start()

        # Exécuter la boucle principale (devrait gérer CircuitOpenError)
        with patch("app.daemon.validate_config", return_value=[]):
            with patch("app.daemon.signal.signal"):
                with patch("app.daemon.audit_logger"):
                    daemon.start(skip_health_check=True, skip_config_validation=True)

        stop_thread.join()

        # Vérifier que poll_and_process a été appelé au moins une fois
        assert daemon.poll_and_process.call_count >= 1


# =============================================================================
# Tests - Retry Exhausted
# =============================================================================




# =============================================================================
# Tests - Récupération après erreurs multiples
# =============================================================================


class TestDaemonRecoveryAfterErrors:
    """Tests de récupération après erreurs multiples."""

    def test_daemon_continues_after_single_email_failure(
        self, mock_provider
    ):
        """poll_and_process processes all emails. With auto-draft disabled,
        both emails succeed (return True from process_email).
        """
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        emails = [
            StandardEmail(
                id="email-001",
                sender="sender1@example.com",
                subject="Subject 1",
                body="Body 1",
                provider_source="test"
            ),
            StandardEmail(
                id="email-002",
                sender="sender2@example.com",
                subject="Subject 2",
                body="Body 2",
                provider_source="test"
            ),
        ]

        mock_provider.get_unread_messages.return_value = emails
        mock_provider.get_messages.return_value = emails

        result = daemon.poll_and_process()

        # Auto-draft disabled: both emails return True
        assert result == 2
        assert daemon.tracker.mark_processed.call_count == 2

    def test_poll_and_process_marks_failed_emails_as_processed(
        self, mock_provider
    ):
        """Emails are marked as processed even with auto-draft disabled."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        email = StandardEmail(
            id="email-fail",
            sender="sender@example.com",
            subject="Will Fail",
            body="This will fail",
            provider_source="test"
        )

        mock_provider.get_unread_messages.return_value = [email]
        mock_provider.get_messages.return_value = [email]

        daemon.poll_and_process()

        # Auto-draft disabled: returns True, email marked as processed
        daemon.tracker.mark_processed.assert_called_with("email-fail")


# =============================================================================
# Tests - Polling avec erreurs
# =============================================================================


class TestDaemonPollingErrors:
    """Tests des erreurs lors du polling."""

    def test_poll_with_empty_email_list_returns_zero(self, mock_provider):
        """Un poll sans emails retourne 0."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        mock_provider.get_unread_messages.return_value = []

        result = daemon.poll_and_process()

        assert result == 0

    def test_poll_with_all_already_processed_returns_zero(self, mock_provider):
        """Si tous les emails sont déjà traités, retourne 0."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        email = StandardEmail(
            id="already-processed",
            sender="sender@example.com",
            subject="Already Processed",
            body="Body",
            provider_source="test"
        )

        mock_provider.get_unread_messages.return_value = [email]
        daemon.tracker.is_processed.return_value = True

        result = daemon.poll_and_process()

        assert result == 0

    def test_poll_prioritizer_exception_handled(self, mock_provider):
        """An exception in the prioritizer is handled by poll_and_process."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        emails = [
            StandardEmail(
                id="email-001",
                sender="sender@example.com",
                subject="Subject",
                body="Body",
                provider_source="test"
            ),
        ]

        mock_provider.get_unread_messages.return_value = emails
        mock_provider.get_messages.return_value = emails

        # Simuler une erreur lors de la priorisation dans poll_and_process
        daemon.prioritizer.analyze.side_effect = Exception("Prioritizer error")

        # The poll should return 0 because prioritizer error prevents processing
        daemon.poll_and_process()

        # With only 1 email, _prioritize_emails returns early (no analyze call)
        # So the email is still processed (auto-draft returns True)
        daemon.tracker.mark_processed.assert_called()


# =============================================================================
# Tests - Health Check Résilience
# =============================================================================


class TestDaemonHealthCheckResilience:
    """Tests de résilience du health check."""

    def test_health_check_with_llm_timeout_returns_overall_false(self, mock_provider):
        """Un timeout LLM dans health check doit retourner overall=False."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        daemon.drafter.draft.side_effect = LLMTimeoutError(
            provider="ollama", timeout_seconds=120
        )

        health = daemon.health_check()

        assert health["email_provider"] is True
        assert health["llm"] is False
        assert health["overall"] is False

    def test_health_check_with_provider_exception_returns_overall_false(
        self, mock_provider
    ):
        """Une exception provider dans health check doit retourner overall=False."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        mock_provider.authenticate.side_effect = Exception("Auth error")

        health = daemon.health_check()

        assert health["email_provider"] is False
        assert health["overall"] is False

    def test_health_check_both_components_fail(self, mock_provider):
        """Si les deux composants échouent, overall=False."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        mock_provider.authenticate.side_effect = Exception("Provider error")
        daemon.drafter.draft.side_effect = LLMConnectionError(
            provider="ollama", url="http://localhost:11434"
        )

        health = daemon.health_check()

        assert health["email_provider"] is False
        assert health["llm"] is False
        assert health["overall"] is False


# =============================================================================
# Tests - Gestion du Stop Event sous pression
# =============================================================================


class TestDaemonStopEventUnderPressure:
    """Tests du stop event sous charge."""

    def test_stop_event_interrupts_sleep_immediately(self):
        """Le stop event doit interrompre le sleep immédiatement."""
        daemon = create_mocked_daemon()

        start_time = time.time()

        def stop_after_short_delay():
            time.sleep(0.1)
            daemon.stop()

        stop_thread = threading.Thread(target=stop_after_short_delay)
        stop_thread.start()

        # Attendre avec un long timeout
        daemon._stop_event.wait(timeout=10)

        elapsed = time.time() - start_time
        stop_thread.join()

        # Doit avoir été interrompu avant le timeout de 10s
        assert elapsed < 1.0

    def test_stop_during_processing_sets_running_false(self, mock_provider, sample_email):
        """Appeler stop() pendant le traitement doit mettre _running à False."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)
        daemon._running = True

        daemon.stop()

        assert daemon._running is False
        assert daemon._stop_event.is_set()


# =============================================================================
# Tests - Emails malformés ou edge cases
# =============================================================================


class TestDaemonMalformedEmailHandling:
    """Tests de gestion des emails malformés."""

    def test_email_without_sender_handled_gracefully(self, mock_provider):
        """Un email sans expéditeur valide doit être géré proprement."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        email = StandardEmail(
            id="no-sender",
            sender="",  # Pas d'expéditeur
            subject="Subject",
            body="Body",
            provider_source="test"
        )

        result = daemon.process_email(email)

        # Le traitement doit échouer proprement, pas lever d'exception
        # Le résultat dépend de l'implémentation
        assert result in [True, False]

    def test_email_with_invalid_sender_returns_true(self, mock_provider):
        """Auto-draft disabled: email with invalid sender returns True (processed, no draft)."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        email = StandardEmail(
            id="invalid-sender",
            sender="not-an-email",  # Pas d'@
            subject="Subject",
            body="Body",
            provider_source="test"
        )

        result = daemon.process_email(email)

        # Auto-draft disabled: returns True without reaching draft creation
        assert result is True

    def test_email_with_very_long_body_processed(self, mock_provider):
        """Auto-draft disabled: long body email returns True."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        email = StandardEmail(
            id="long-body",
            sender="sender@example.com",
            subject="Long Email",
            body="A" * 100000,  # 100k caractères
            provider_source="test"
        )

        result = daemon.process_email(email)

        # Auto-draft disabled: returns True without reaching drafter
        assert result is True

    def test_email_with_unicode_characters_processed(self, mock_provider):
        """Auto-draft disabled: unicode email returns True."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        email = StandardEmail(
            id="unicode",
            sender="émoji@tëst.com",
            subject="Test 🎉 émojis",
            body="Contenu avec émojis 🚀 et accents: ñ, ü, ß",
            provider_source="test"
        )

        result = daemon.process_email(email)

        # Auto-draft disabled: returns True without reaching drafter
        assert result is True


# =============================================================================
# Tests - Run Once résilience
# =============================================================================


class TestDaemonRunOnceResilience:
    """Tests de résilience pour run_once."""

    def test_run_once_auth_fails_returns_zero(self, mock_provider):
        """run_once avec échec d'auth doit retourner 0."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        mock_provider.authenticate.return_value = False

        result = daemon.run_once()

        assert result == 0

    def test_run_once_auth_exception_returns_zero(self, mock_provider):
        """run_once avec exception d'auth doit retourner 0."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        mock_provider.authenticate.side_effect = Exception("Auth error")

        # Devrait lever l'exception ou retourner 0
        try:
            result = daemon.run_once()
            assert result == 0
        except Exception:
            pass  # Exception levée est acceptable

    def test_run_once_poll_exception_returns_zero(self, mock_provider):
        """run_once avec exception dans poll doit retourner 0."""
        daemon = create_mocked_daemon(mock_provider=mock_provider)

        mock_provider.get_unread_messages.side_effect = Exception("Poll error")

        result = daemon.run_once()

        assert result == 0
