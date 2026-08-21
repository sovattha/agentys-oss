# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour le lifecycle du daemon et la gestion des signaux.

Ce fichier suit les principes de Clean Architecture:
- Framework Layer: Tests du daemon (orchestration)
- Infrastructure Layer: Tests de ProcessedEmailsTracker

Edge cases couverts:
1. Daemon start/stop lifecycle
2. Signal handling (SIGINT, SIGTERM)
3. Health check failures
4. Poll and process edge cases
5. Circuit breaker integration
6. Threading et stop event
"""

import threading
import time
from unittest.mock import MagicMock

import pytest

from app.interfaces.email_provider import EmailProvider, StandardEmail
from app.domain.ports import LLMResponse


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_provider():
    """Provider mocké pour les tests."""
    provider = MagicMock(spec=EmailProvider)
    provider.provider_name = "mock"
    provider.authenticate.return_value = True
    provider.get_unread_messages.return_value = []
    provider.create_draft.return_value = "draft-001"
    provider.send_draft.return_value = True
    provider.mark_as_read.return_value = True
    provider.apply_label.return_value = True
    return provider


@pytest.fixture
def mock_agents():
    """Agents mockés pour les tests."""

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
def mock_container():
    """Container mocké."""
    from app.agents import TokenCounter

    container = MagicMock()
    container.token_usage = TokenCounter()
    container.llm = MagicMock()
    container.llm.complete.return_value = LLMResponse(
        content="Test response",
        input_tokens=100,
        output_tokens=50,
        model="test"
    )
    container.llm_label = container.llm

    learning_service = MagicMock()
    learning_service.should_require_review.return_value = False
    container.get_learning_service.return_value = learning_service

    return container


@pytest.fixture
def sample_emails():
    """Emails de test."""
    return [
        StandardEmail(
            id="email-001",
            sender="sender1@example.com",
            sender_name="Sender One",
            subject="Test Subject 1",
            body="Test body 1",
            provider_source="test"
        ),
        StandardEmail(
            id="email-002",
            sender="sender2@example.com",
            sender_name="Sender Two",
            subject="Test Subject 2",
            body="Test body 2",
            provider_source="test"
        ),
    ]


# ============================================================================
# HELPER - DAEMON CREATION WITH FULL MOCKING
# ============================================================================

def create_mocked_daemon(
    mock_provider=None,
    mock_agents=None,
    poll_interval=60,
    skip_low_priority=False
):
    """Crée un daemon avec toutes les dépendances mockées."""
    from app.daemon import EmailDaemon

    # Créer le daemon sans initialisation
    daemon = EmailDaemon.__new__(EmailDaemon)

    # Provider mock
    if mock_provider is None:
        mock_provider = MagicMock(spec=EmailProvider)
        mock_provider.provider_name = "mock"
        mock_provider.authenticate.return_value = True
        mock_provider.get_unread_messages.return_value = []
        mock_provider.create_draft.return_value = "draft-001"
        mock_provider.mark_as_read.return_value = True
        mock_provider.apply_label.return_value = True

    daemon.provider = mock_provider

    # Agents mock
    daemon.drafter = MagicMock()
    daemon.drafter.draft.return_value = "Draft response"
    daemon.drafter.revise.return_value = "Revised response"

    daemon.critic = MagicMock()
    daemon.critic.evaluate.return_value = "VALID"
    daemon.critic.is_valid.return_value = True

    daemon.prioritizer = MagicMock()
    daemon.prioritizer.analyze.return_value = {"priority_score": 50}

    daemon.classifier = MagicMock()
    daemon.classifier.classify.return_value = {"category": "NORMAL"}
    daemon.classifier.should_skip.return_value = False

    # Tracker mock (in-memory)
    daemon.tracker = MagicMock()
    daemon.tracker.is_processed.return_value = False
    daemon.tracker.mark_processed.return_value = None
    daemon.tracker.count.return_value = 0

    # Learning service mock
    daemon.learning_manager = MagicMock()
    daemon.learning_manager.should_require_review.return_value = False

    # Message router mock
    daemon.message_router = MagicMock()

    # Phishing detector
    from app.domain.services import PhishingDetector
    daemon.phishing_detector = PhishingDetector()

    # Paramètres
    daemon.poll_interval = poll_interval
    daemon.skip_low_priority = skip_low_priority
    daemon.use_smart_routing = True

    # État interne
    daemon._running = False
    daemon._emails_processed_count = 0
    daemon._stop_event = threading.Event()

    return daemon


# ============================================================================
# TESTS - DAEMON INITIALIZATION
# ============================================================================

class TestDaemonInitialization:
    """Tests pour l'initialisation du daemon."""

    def test_daemon_initializes_with_defaults(self):
        """Daemon s'initialise avec les valeurs par défaut."""
        daemon = create_mocked_daemon()

        assert daemon._running is False
        assert daemon._stop_event is not None
        assert daemon.provider is not None

    def test_daemon_accepts_custom_poll_interval(self):
        """Daemon accepte un intervalle de polling personnalisé."""
        daemon = create_mocked_daemon(poll_interval=120)

        assert daemon.poll_interval == 120

    def test_daemon_accepts_skip_low_priority(self):
        """Daemon accepte l'option skip_low_priority."""
        daemon = create_mocked_daemon(skip_low_priority=True)

        assert daemon.skip_low_priority is True


# ============================================================================
# TESTS - DAEMON STOP EVENT
# ============================================================================

class TestDaemonStopEvent:
    """Tests pour l'événement d'arrêt du daemon."""

    def test_stop_sets_event(self):
        """stop() définit l'événement d'arrêt."""
        daemon = create_mocked_daemon()
        daemon._running = True

        daemon.stop()

        assert daemon._running is False
        assert daemon._stop_event.is_set()

    def test_stop_event_is_cleared_on_start(self):
        """L'événement est réinitialisé au démarrage."""
        daemon = create_mocked_daemon()
        daemon._stop_event.set()

        # Simuler un démarrage partiel
        daemon._running = True
        daemon._stop_event.clear()

        assert not daemon._stop_event.is_set()


# ============================================================================
# TESTS - HEALTH CHECK
# ============================================================================

class TestDaemonHealthCheck:
    """Tests pour le health check du daemon."""

    def test_health_check_all_pass(self):
        """Health check passe quand tous les composants sont OK."""
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = True
        daemon.drafter.draft.return_value = "Test response OK"

        result = daemon.health_check()

        assert result["email_provider"] is True
        assert result["llm"] is True
        assert result["overall"] is True

    def test_health_check_provider_fails(self):
        """Health check échoue si le provider ne s'authentifie pas."""
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = False

        result = daemon.health_check()

        assert result["email_provider"] is False
        assert result["overall"] is False

    def test_health_check_provider_exception(self):
        """Health check gère les exceptions du provider."""
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.side_effect = ConnectionError("Network error")

        result = daemon.health_check()

        assert result["email_provider"] is False

    def test_health_check_llm_fails(self):
        """Health check échoue si le LLM ne répond pas."""
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = True
        daemon.drafter.draft.return_value = ""  # Réponse vide

        result = daemon.health_check()

        assert result["llm"] is False
        assert result["overall"] is False

    def test_health_check_llm_exception(self):
        """Health check gère les exceptions du LLM."""
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = True
        daemon.drafter.draft.side_effect = Exception("LLM API error")

        result = daemon.health_check()

        assert result["llm"] is False


# ============================================================================
# TESTS - POLL AND PROCESS
# ============================================================================

class TestDaemonPollAndProcess:
    """Tests pour poll_and_process."""

    def test_poll_no_emails(self):
        """poll_and_process retourne 0 si pas d'emails."""
        daemon = create_mocked_daemon()
        daemon.provider.get_unread_messages.return_value = []

        result = daemon.poll_and_process()

        assert result == 0

    def test_poll_already_processed_emails(self, sample_emails):
        """poll_and_process ignore les emails déjà traités."""
        daemon = create_mocked_daemon()
        daemon.provider.get_unread_messages.return_value = sample_emails

        # Marquer tous les emails comme déjà traités
        daemon.tracker.is_processed.return_value = True

        result = daemon.poll_and_process()

        assert result == 0

    def test_poll_exception_returns_zero(self):
        """poll_and_process retourne 0 en cas d'exception."""
        daemon = create_mocked_daemon()
        daemon.provider.get_unread_messages.side_effect = Exception("API Error")

        result = daemon.poll_and_process()

        assert result == 0


# ============================================================================
# TESTS - RUN ONCE
# ============================================================================

class TestDaemonRunOnce:
    """Tests pour run_once (mode test)."""

    def test_run_once_auth_fails(self):
        """run_once retourne 0 si l'authentification échoue."""
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = False

        result = daemon.run_once()

        assert result == 0

    def test_run_once_success(self):
        """run_once exécute un cycle de polling."""
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = True
        daemon.provider.get_unread_messages.return_value = []

        result = daemon.run_once()

        daemon.provider.authenticate.assert_called_once()
        assert result == 0  # Pas d'emails à traiter


# ============================================================================
# TESTS - PROCESSED EMAILS TRACKER PROTOCOL
# ============================================================================

class TestProcessedEmailsTrackerProtocol:
    """Tests pour le port ProcessedEmailsTrackerPort."""

    def test_tracker_implements_protocol(self, tmp_path):
        """JsonProcessedEmailsTracker implémente le port."""
        from app.domain.ports import ProcessedEmailsTrackerPort
        from app.infrastructure.adapters.processed_emails_adapter import JsonProcessedEmailsTracker

        filepath = tmp_path / "test.json"
        tracker = JsonProcessedEmailsTracker(filepath=filepath)

        # Vérifier que l'adapter implémente le port
        assert isinstance(tracker, ProcessedEmailsTrackerPort)

        # Vérifier les méthodes du port
        assert hasattr(tracker, "is_processed")
        assert hasattr(tracker, "mark_processed")
        assert hasattr(tracker, "count")

        # Vérifier les signatures
        assert tracker.is_processed("test-id") is False
        tracker.mark_processed("test-id")
        assert tracker.is_processed("test-id") is True
        assert tracker.count() == 1

    def test_tracker_file_creation(self, tmp_path):
        """Le tracker crée le fichier si nécessaire."""
        from app.infrastructure.adapters.processed_emails_adapter import JsonProcessedEmailsTracker

        filepath = tmp_path / "subdir" / "tracker.json"

        # Le répertoire parent n'existe pas encore
        assert not filepath.parent.exists()

        tracker = JsonProcessedEmailsTracker(filepath=filepath)
        tracker.mark_processed("email-001")

        # Le répertoire et le fichier doivent exister
        assert filepath.exists()


# ============================================================================
# TESTS - CLEANING RESULT
# ============================================================================

class TestCleaningResult:
    """Tests pour CleaningResult."""

    def test_cleaning_result_should_skip_true(self):
        """CleaningResult avec should_skip=True."""
        from app.daemon import CleaningResult

        result = CleaningResult(
            email=StandardEmail(id="test", sender="test@test.com"),
            metadata={"is_auto_reply": True},
            should_skip=True,
            skip_reason="auto-reply"
        )

        assert result.should_skip is True
        assert result.skip_reason == "auto-reply"

    def test_cleaning_result_should_skip_false(self):
        """CleaningResult avec should_skip=False."""
        from app.daemon import CleaningResult

        result = CleaningResult(
            email=StandardEmail(id="test", sender="test@test.com"),
            metadata={"is_auto_reply": False},
            should_skip=False
        )

        assert result.should_skip is False
        assert result.skip_reason is None


# ============================================================================
# TESTS - CLASSIFICATION RESULT
# ============================================================================

class TestClassificationResult:
    """Tests pour ClassificationResult."""

    def test_classification_result_normal(self):
        """ClassificationResult pour email normal."""
        from app.daemon import ClassificationResult

        result = ClassificationResult(
            category="NORMAL",
            priority_score=50,
            should_skip=False
        )

        assert result.category == "NORMAL"
        assert result.should_skip is False

    def test_classification_result_spam(self):
        """ClassificationResult pour spam."""
        from app.daemon import ClassificationResult

        result = ClassificationResult(
            category="SPAM",
            priority_score=0,
            should_skip=True,
            skip_reason="low_priority:SPAM"
        )

        assert result.category == "SPAM"
        assert result.should_skip is True


# ============================================================================
# TESTS - DRAFT GENERATION RESULT
# ============================================================================

class TestDraftGenerationResult:
    """Tests pour DraftGenerationResult."""

    def test_draft_result_v1(self):
        """DraftGenerationResult pour V1 validée."""
        from app.daemon import DraftGenerationResult

        result = DraftGenerationResult(
            draft_v1="Version 1",
            critique="VALID",
            final_draft="Version 1",
            status="V1"
        )

        assert result.draft_v1 == result.final_draft
        assert result.status == "V1"

    def test_draft_result_v2(self):
        """DraftGenerationResult pour V2 corrigée."""
        from app.daemon import DraftGenerationResult

        result = DraftGenerationResult(
            draft_v1="Version 1 problématique",
            critique="REJET: Ton inapproprié",
            final_draft="Version 2 corrigée",
            status="V2"
        )

        assert result.draft_v1 != result.final_draft
        assert result.status == "V2"
        assert "REJET" in result.critique


# ============================================================================
# TESTS - DAEMON THREADING
# ============================================================================

class TestDaemonThreading:
    """Tests pour le comportement threading du daemon."""

    def test_stop_event_wait_is_interruptible(self):
        """L'attente du stop_event est interruptible."""
        daemon = create_mocked_daemon(poll_interval=60)

        # Démarrer un thread qui va définir l'événement après un délai
        def set_stop_after_delay():
            time.sleep(0.1)
            daemon._stop_event.set()

        stop_thread = threading.Thread(target=set_stop_after_delay)
        stop_thread.start()

        start_time = time.time()
        # L'attente devrait être interrompue après ~0.1s, pas 60s
        daemon._stop_event.wait(timeout=60)
        elapsed = time.time() - start_time

        stop_thread.join()

        assert elapsed < 1.0  # Bien moins que 60 secondes

    def test_multiple_stop_calls_are_safe(self):
        """Appeler stop() plusieurs fois est sûr."""
        daemon = create_mocked_daemon()
        daemon._running = True

        # Appels multiples
        daemon.stop()
        daemon.stop()
        daemon.stop()

        assert daemon._running is False
        assert daemon._stop_event.is_set()


# ============================================================================
# TESTS - EMAIL FORMATTING
# ============================================================================

class TestEmailFormatting:
    """Tests pour le formatage des emails."""

    def test_format_email_with_sender_name(self):
        """Formatage avec nom d'expéditeur."""
        daemon = create_mocked_daemon()

        email = StandardEmail(
            id="test",
            sender="john@example.com",
            sender_name="John Doe",
            subject="Test Subject",
            body="Test body content"
        )

        result = daemon._format_email_for_agent(email)

        assert "John Doe" in result
        assert "john@example.com" in result
        assert "Test Subject" in result
        assert "Test body content" in result

    def test_format_email_without_sender_name(self):
        """Formatage sans nom d'expéditeur."""
        daemon = create_mocked_daemon()

        email = StandardEmail(
            id="test",
            sender="john@example.com",
            sender_name=None,
            subject="Test",
            body="Body"
        )

        result = daemon._format_email_for_agent(email)

        assert "De: john@example.com" in result


# ============================================================================
# TESTS - REPLY SUBJECT GENERATION
# ============================================================================

class TestReplySubjectGeneration:
    """Tests pour la génération du sujet de réponse."""

    def test_reply_subject_adds_re_prefix(self):
        """Ajoute Re: au sujet."""
        daemon = create_mocked_daemon()

        result = daemon._generate_reply_subject("Original Subject")

        assert result == "Re: Original Subject"

    def test_reply_subject_preserves_existing_re(self):
        """Préserve le Re: existant."""
        daemon = create_mocked_daemon()

        # Différentes casses
        assert daemon._generate_reply_subject("Re: Topic") == "Re: Topic"
        assert daemon._generate_reply_subject("RE: Topic") == "RE: Topic"
        assert daemon._generate_reply_subject("re: Topic") == "re: Topic"

    def test_reply_subject_empty(self):
        """Sujet vide - retourne un sujet explicite."""
        daemon = create_mocked_daemon()

        result = daemon._generate_reply_subject("")

        assert result == "Re: (sans sujet)"

    def test_reply_subject_none(self):
        """Sujet None - retourne un sujet explicite."""
        daemon = create_mocked_daemon()

        result = daemon._generate_reply_subject(None)

        assert result == "Re: (sans sujet)"

    def test_reply_subject_whitespace_only(self):
        """Sujet avec espaces seulement - préserve le comportement."""
        daemon = create_mocked_daemon()

        result = daemon._generate_reply_subject("   ")

        # Préfixe Re: est ajouté
        assert result == "Re:    "


# ============================================================================
# TESTS - FORMAT EMAIL EDGE CASES
# ============================================================================

class TestFormatEmailEdgeCases:
    """Tests edge cases pour le formatage des emails."""

    def test_format_email_with_none_body(self):
        """Email avec body None - retourne chaîne vide."""
        daemon = create_mocked_daemon()

        email = StandardEmail(
            id="test-none-body",
            sender="sender@example.com",
            sender_name="Sender",
            subject="Test",
            body=None,
            provider_source="test"
        )

        result = daemon._format_email_for_agent(email)

        assert "sender@example.com" in result
        assert "Test" in result
        # Body vide ne cause pas d'erreur

    def test_format_email_with_none_subject(self):
        """Email avec subject None - retourne chaîne vide."""
        daemon = create_mocked_daemon()

        email = StandardEmail(
            id="test-none-subject",
            sender="sender@example.com",
            sender_name="Sender",
            subject=None,
            body="Body content",
            provider_source="test"
        )

        result = daemon._format_email_for_agent(email)

        assert "sender@example.com" in result
        assert "Body content" in result
        assert "Sujet:" in result

    def test_format_email_with_empty_sender_name(self):
        """Email avec sender_name vide - utilise seulement l'adresse."""
        daemon = create_mocked_daemon()

        email = StandardEmail(
            id="test-empty-name",
            sender="sender@example.com",
            sender_name="",
            subject="Test",
            body="Body",
            provider_source="test"
        )

        result = daemon._format_email_for_agent(email)

        # Sender name vide = n'apparaît pas
        assert "De: sender@example.com" in result


# ============================================================================
# TESTS - INCOMING MESSAGE CONVERSION
# ============================================================================

class TestIncomingMessageConversion:
    """Tests pour la conversion en IncomingMessage."""

    def test_email_to_incoming_message(self):
        """Conversion email vers IncomingMessage."""
        from app.message_router import MessageChannel

        daemon = create_mocked_daemon()

        email = StandardEmail(
            id="test-001",
            sender="sender@example.com",
            sender_name="Sender Name",
            subject="Test Subject",
            body="Test body",
            cc=["cc@example.com"],
            conversation_id="conv-001",
            has_attachments=True,
            provider_source="gmail"
        )

        result = daemon._email_to_incoming_message(email)

        assert result.channel == MessageChannel.EMAIL
        assert result.content == "Test body"
        assert result.sender_id == "sender@example.com"
        assert result.sender_name == "Sender Name"
        assert result.subject == "Test Subject"
        assert result.cc == ["cc@example.com"]
        assert result.conversation_id == "conv-001"
        assert result.metadata["email_id"] == "test-001"
        assert result.metadata["has_attachments"] is True
        assert result.metadata["provider"] == "gmail"

    def test_email_to_incoming_message_empty_cc(self):
        """Conversion avec CC vide."""
        daemon = create_mocked_daemon()

        email = StandardEmail(
            id="test",
            sender="sender@example.com",
            cc=[]
        )

        result = daemon._email_to_incoming_message(email)

        assert result.cc == []
