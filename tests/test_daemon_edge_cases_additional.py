"""
Tests TDD additionnels pour les edge cases du daemon.

Edge cases critiques couverts:
1. _format_email_for_agent() - body/subject None
2. _prioritize_emails() - empty list, single email, exception
3. poll_and_process() - get_unread_messages returns None
4. _create_and_save_draft() - non-empty CC, retry exhaustion
5. _perform_startup_checks() - specific component failures

Cycle TDD: RED -> GREEN -> REFACTOR
Pattern: Arrange-Act-Assert
"""

import pytest
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.interfaces.email_provider import EmailProvider, StandardEmail


# =============================================================================
# Helper - Daemon Creation with Full Mocking
# =============================================================================


def create_mocked_daemon(
    mock_provider=None,
    poll_interval=60,
    skip_low_priority=False,
    use_smart_routing=False,
):
    """Crée un daemon avec toutes les dépendances mockées."""
    from app.daemon import EmailDaemon

    # Créer le daemon sans initialisation automatique
    daemon = EmailDaemon.__new__(EmailDaemon)

    # Provider mock
    if mock_provider is None:
        mock_provider = MagicMock(spec=EmailProvider)
        mock_provider.provider_name = "mock"
        mock_provider.authenticate.return_value = True
        mock_provider.get_unread_messages.return_value = []
        mock_provider.get_user_drafts.return_value = []
        mock_provider.create_draft.return_value = "draft-001"
        mock_provider.update_draft.return_value = True
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

    # Tracker mock
    daemon.tracker = MagicMock()
    daemon.tracker.is_processed.return_value = False
    daemon.tracker.mark_processed.return_value = None
    daemon.tracker.count.return_value = 0

    # Processed drafts tracker mock
    daemon.processed_drafts_tracker = MagicMock()
    daemon.processed_drafts_tracker.is_processed.return_value = False
    daemon.processed_drafts_tracker.mark_processed.return_value = None

    # Draft completion agent mock
    daemon.draft_completion_agent = MagicMock()
    daemon.draft_completion_agent.is_completion_request.return_value = False

    # Learning service mock
    daemon.learning_manager = MagicMock()
    daemon.learning_manager.should_require_review.return_value = False
    daemon.learning_manager.analyze_feedback.return_value = {}
    daemon.learning_manager.get_stats.return_value = {}

    # Draft history mock
    daemon.draft_history = MagicMock()

    # Message router mock
    daemon.message_router = MagicMock()

    # Phishing detector
    from app.domain.services import PhishingDetector
    daemon.phishing_detector = PhishingDetector()

    # Task extractor mock
    daemon.task_extractor = MagicMock()
    daemon.task_extractor.extract.return_value = []
    daemon.task_repository = MagicMock()

    # Commitment extractor mock
    daemon.commitment_extractor = MagicMock()
    daemon.commitment_extractor.extract.return_value = []
    daemon.commitment_use_case = MagicMock()

    # Sensitive data detector mock
    daemon.sensitive_data_detector = MagicMock()
    daemon.sensitive_data_detector.detect.return_value = MagicMock(
        is_sensitive=False, confidence=0.0, detected_items=[]
    )

    # Cryptographer mock (pour anonymisation)
    from app.domain.entities.anonymized_result import AnonymizedResult
    daemon.cryptographer = MagicMock()
    mock_detection = MagicMock(is_sensitive=False)
    daemon.cryptographer.anonymize.return_value = AnonymizedResult.empty(
        original_content="", detection=mock_detection
    )

    # Correction manager mock
    daemon.correction_manager = MagicMock()
    daemon.correction_manager.apply_learned_corrections.return_value = ("Draft response", [])
    daemon.correction_manager.detect_user_modification.return_value = False

    # Configuration
    daemon.poll_interval = poll_interval
    daemon.skip_low_priority = skip_low_priority
    daemon.use_smart_routing = use_smart_routing
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

    return daemon


# =============================================================================
# Tests - _format_email_for_agent Edge Cases (NULL handling)
# =============================================================================


class TestFormatEmailForAgentNullCases:
    """Tests pour les edge cases null/None de _format_email_for_agent()."""

    def test_format_email_body_none_should_handle_gracefully(self):
        """
        ARRANGE: Email avec body=None
        ACT: Appeler _format_email_for_agent()
        ASSERT: Ne lève pas d'exception, body traité comme chaîne

        BUG POTENTIEL: Concaténation avec None peut causer des problèmes
        """
        # Arrange
        daemon = create_mocked_daemon()
        email = StandardEmail(
            id="test-none-body",
            sender="sender@example.com",
            sender_name="Sender",
            subject="Test Subject",
            body=None,  # None body
            provider_source="test",
        )

        # Act & Assert - should not raise
        try:
            result = daemon._format_email_for_agent(email)
            # Le résultat doit être une chaîne
            assert isinstance(result, str)
            assert "Test Subject" in result
        except (TypeError, AttributeError) as e:
            pytest.fail(
                f"_format_email_for_agent avec body=None a levé {type(e).__name__}: {e}. "
                "Le code devrait gérer None gracieusement."
            )

    def test_format_email_subject_none_should_handle_gracefully(self):
        """
        ARRANGE: Email avec subject=None
        ACT: Appeler _format_email_for_agent()
        ASSERT: Ne lève pas d'exception

        BUG POTENTIEL: Concaténation avec None peut causer des problèmes
        """
        # Arrange
        daemon = create_mocked_daemon()
        email = StandardEmail(
            id="test-none-subject",
            sender="sender@example.com",
            sender_name="Sender",
            subject=None,  # None subject
            body="Test body",
            provider_source="test",
        )

        # Act & Assert - should not raise
        try:
            result = daemon._format_email_for_agent(email)
            assert isinstance(result, str)
            assert "Test body" in result
        except (TypeError, AttributeError) as e:
            pytest.fail(
                f"_format_email_for_agent avec subject=None a levé {type(e).__name__}: {e}. "
                "Le code devrait gérer None gracieusement."
            )

    def test_format_email_sender_name_empty_string(self):
        """
        ARRANGE: Email avec sender_name=""
        ACT: Appeler _format_email_for_agent()
        ASSERT: Utilise juste l'email sans le nom vide
        """
        # Arrange
        daemon = create_mocked_daemon()
        email = StandardEmail(
            id="test-empty-name",
            sender="sender@example.com",
            sender_name="",  # Empty string
            subject="Test",
            body="Body",
            provider_source="test",
        )

        # Act
        result = daemon._format_email_for_agent(email)

        # Assert - Empty string is falsy, so should use email only
        assert "De: sender@example.com" in result


# =============================================================================
# Tests - _prioritize_emails Edge Cases
# =============================================================================


class TestPrioritizeEmailsEdgeCases:
    """Tests pour les edge cases de _prioritize_emails()."""

    def test_prioritize_empty_list_returns_empty(self):
        """
        ARRANGE: Liste d'emails vide
        ACT: Appeler _prioritize_emails([])
        ASSERT: Retourne une liste vide
        """
        # Arrange
        daemon = create_mocked_daemon()

        # Act
        result = daemon._prioritize_emails([])

        # Assert
        assert result == []
        # Prioritizer ne doit pas être appelé
        daemon.prioritizer.analyze.assert_not_called()

    def test_prioritize_single_email_skips_sorting(self):
        """
        ARRANGE: Liste avec un seul email
        ACT: Appeler _prioritize_emails([email])
        ASSERT: Retourne l'email sans appeler prioritizer (optimisation)
        """
        # Arrange
        daemon = create_mocked_daemon()
        email = StandardEmail(
            id="single-email",
            sender="sender@example.com",
            subject="Test",
            body="Body",
            provider_source="test",
        )

        # Act
        result = daemon._prioritize_emails([email])

        # Assert - should return as-is without calling prioritizer
        assert len(result) == 1
        assert result[0].id == "single-email"
        # Le code fait un early return pour len <= 1
        daemon.prioritizer.analyze.assert_not_called()

    def test_prioritize_multiple_emails_sorts_by_recency_without_llm(self):
        """
        Audit 2026-06-02 (P1 coût) : _prioritize_emails ne fait plus d'appel
        LLM par email. Il trie du plus récent au plus ancien via received_at.

        ARRANGE: Plusieurs emails avec des dates received_at différentes
        ACT: Appeler _prioritize_emails()
        ASSERT: Triés du plus récent au plus ancien, SANS appeler le prioritizer
        """
        # Arrange
        daemon = create_mocked_daemon()
        now = datetime(2026, 6, 2, 12, 0, 0)
        email_old = StandardEmail(
            id="email-old",
            sender="old@example.com",
            subject="Old",
            body="Body",
            provider_source="test",
            received_at=now - timedelta(hours=2),
        )
        email_new = StandardEmail(
            id="email-new",
            sender="new@example.com",
            subject="New",
            body="Body",
            provider_source="test",
            received_at=now,
        )
        email_mid = StandardEmail(
            id="email-mid",
            sender="mid@example.com",
            subject="Mid",
            body="Body",
            provider_source="test",
            received_at=now - timedelta(hours=1),
        )

        # Act — input order deliberately scrambled
        result = daemon._prioritize_emails([email_old, email_new, email_mid])

        # Assert - newest first
        assert [e.id for e in result] == ["email-new", "email-mid", "email-old"]
        # The per-email Haiku call was removed — that IS the cost fix.
        daemon.prioritizer.analyze.assert_not_called()

    def test_prioritize_emails_handles_missing_received_at(self):
        """
        Audit 2026-06-02 : received_at peut être None selon le provider (et
        mélanger naïf/aware). Le tri ne doit jamais crasher et doit conserver
        tous les emails. (Remplace l'ancien test de propagation d'exception du
        prioritizer, devenu caduc avec la suppression de l'appel LLM.)
        """
        # Arrange
        daemon = create_mocked_daemon()
        email_none = StandardEmail(
            id="email-none",
            sender="sender@example.com",
            subject="Test",
            body="Body",
            provider_source="test",
        )  # received_at None
        email_dated = StandardEmail(
            id="email-dated",
            sender="sender2@example.com",
            subject="Test 2",
            body="Body 2",
            provider_source="test",
            received_at=datetime(2026, 6, 2, 12, 0, 0),
        )

        # Act
        result = daemon._prioritize_emails([email_none, email_dated])

        # Assert - no crash, both kept; dated email sorts ahead of the None one
        assert len(result) == 2
        assert {e.id for e in result} == {"email-none", "email-dated"}
        assert result[0].id == "email-dated"
        daemon.prioritizer.analyze.assert_not_called()


# =============================================================================
# Tests - poll_and_process Edge Cases
# =============================================================================


class TestPollAndProcessNullCases:
    """Tests pour les edge cases null/None de poll_and_process()."""

    def test_get_unread_messages_returns_none_should_return_zero(self):
        """
        ARRANGE: provider.get_unread_messages() retourne None
        ACT: Appeler poll_and_process()
        ASSERT: Retourne 0 sans exception

        BUG POTENTIEL: iteration sur None peut lever TypeError
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon.provider.get_unread_messages.return_value = None

        # Act
        result = daemon.poll_and_process()

        # Assert - should handle None gracefully
        assert result == 0


# =============================================================================
# Tests - _create_and_save_draft Edge Cases
# =============================================================================




# =============================================================================
# Tests - _perform_startup_checks Edge Cases
# =============================================================================


class TestPerformStartupChecksEdgeCases:
    """Tests pour les edge cases de _perform_startup_checks()."""

    def test_skip_health_check_true_auth_succeeds(self):
        """
        ARRANGE: skip_health_check=True, auth réussit
        ACT: Appeler _perform_startup_checks(skip_health_check=True)
        ASSERT: Retourne True, health_check() non appelé
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = True

        with patch("app.daemon.audit_logger"):
            # Act
            result = daemon._perform_startup_checks(skip_health_check=True)

        # Assert
        assert result is True
        daemon.provider.authenticate.assert_called_once()

    def test_skip_health_check_true_auth_fails(self):
        """
        ARRANGE: skip_health_check=True, auth échoue
        ACT: Appeler _perform_startup_checks(skip_health_check=True)
        ASSERT: Retourne False
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = False

        with patch("app.daemon.audit_logger"):
            # Act
            result = daemon._perform_startup_checks(skip_health_check=True)

        # Assert
        assert result is False

    def test_health_check_partial_failure_returns_false(self):
        """
        ARRANGE: health_check() retourne overall=False (un composant échoue)
        ACT: Appeler _perform_startup_checks(skip_health_check=False)
        ASSERT: Retourne False, notification envoyée pour composant défaillant
        """
        # Arrange
        daemon = create_mocked_daemon()

        # Mock health_check to return partial failure
        daemon.health_check = MagicMock(return_value={
            "email_provider": True,
            "llm": False,  # LLM fails
            "overall": False,
        })

        with patch("app.daemon.audit_logger"), patch("app.daemon.notify") as mock_notify:
            # Act
            result = daemon._perform_startup_checks(skip_health_check=False)

        # Assert
        assert result is False
        # Notification should be called for failed component
        mock_notify.health_check_failed.assert_called_once_with("llm")


# =============================================================================
# Tests - _generate_reply_subject with edge cases
# =============================================================================


class TestGenerateReplySubjectEdgeCases:
    """Tests complémentaires pour _generate_reply_subject()."""

    def test_subject_with_leading_whitespace(self):
        """
        ARRANGE: subject avec espaces au début
        ACT: Appeler _generate_reply_subject()
        ASSERT: Le préfixe Re: est ajouté correctement
        """
        # Arrange
        daemon = create_mocked_daemon()

        # Act
        result = daemon._generate_reply_subject("  Subject with spaces")

        # Assert
        assert result == "Re:   Subject with spaces"

    def test_subject_re_with_extra_characters(self):
        """
        ARRANGE: subject commence par "Re:" mais suivi de caractères non-standard
        ACT: Appeler _generate_reply_subject()
        ASSERT: Pas de double Re:
        """
        # Arrange
        daemon = create_mocked_daemon()

        # Act - "Re:" au début
        result = daemon._generate_reply_subject("Re: Topic")

        # Assert
        assert result == "Re: Topic"  # Pas de double Re:

    def test_subject_only_re_prefix(self):
        """
        ARRANGE: subject = "Re:"
        ACT: Appeler _generate_reply_subject()
        ASSERT: Retourne "Re:" (pas de modification)
        """
        # Arrange
        daemon = create_mocked_daemon()

        # Act
        result = daemon._generate_reply_subject("Re:")

        # Assert
        assert result == "Re:"


# =============================================================================
# Tests - process_email Long Subject Truncation
# =============================================================================


class TestProcessEmailLogging:
    """Tests pour le logging dans process_email()."""

    def test_long_subject_is_truncated_in_log(self):
        """
        ARRANGE: Email avec sujet très long (>50 chars)
        ACT: Appeler process_email()
        ASSERT: Le sujet est tronqué dans le log (test implicite via mock)
        """
        # Arrange
        daemon = create_mocked_daemon()
        long_subject = "A" * 100  # 100 characters

        email = StandardEmail(
            id="test-long-subject",
            sender="sender@example.com",
            subject=long_subject,
            body="Body",
            provider_source="test",
        )

        with patch("app.daemon.clean_email_content") as mock_clean, \
             patch("app.daemon.audit_logger"), \
             patch("app.daemon.notify"), \
             patch("app.daemon.token_counter"):

            mock_clean.return_value = (
                "Body",
                {"is_auto_reply": False, "was_truncated": False},
            )

            # Act
            result = daemon.process_email(email)

        # Assert - The test passes if no error occurs
        # The truncation is in the log message: email.subject[:50]
        assert result is True  # Draft was created


# =============================================================================
# Tests - _validate_startup_config Edge Cases
# =============================================================================


class TestValidateStartupConfigEdgeCases:
    """Tests pour _validate_startup_config()."""

    def test_validate_config_with_errors_returns_false(self):
        """
        ARRANGE: validate_config() retourne des erreurs
        ACT: Appeler _validate_startup_config()
        ASSERT: Retourne False
        """
        # Arrange
        daemon = create_mocked_daemon()

        with patch("app.daemon.validate_config") as mock_validate:
            mock_validate.return_value = ["Missing API key", "Invalid provider"]

            # Act
            result = daemon._validate_startup_config()

        # Assert
        assert result is False

    def test_validate_config_without_errors_returns_true(self):
        """
        ARRANGE: validate_config() retourne une liste vide
        ACT: Appeler _validate_startup_config()
        ASSERT: Retourne True
        """
        # Arrange
        daemon = create_mocked_daemon()

        with patch("app.daemon.validate_config") as mock_validate:
            mock_validate.return_value = []

            # Act
            result = daemon._validate_startup_config()

        # Assert
        assert result is True


# =============================================================================
# Tests - _handle_draft_failure Edge Cases
# =============================================================================




# =============================================================================
# Tests - _handle_processing_error Edge Cases
# =============================================================================


class TestHandleProcessingErrorEdgeCases:
    """Tests pour _handle_processing_error()."""

    def test_handle_processing_error_with_none_processing_time(self):
        """
        ARRANGE: processing_time_ms=None
        ACT: Appeler _handle_processing_error()
        ASSERT: Ne lève pas d'exception
        """
        # Arrange
        daemon = create_mocked_daemon()
        email = StandardEmail(
            id="test-error",
            sender="sender@example.com",
            subject="Test",
            body="Body",
            provider_source="test",
        )
        error = ValueError("Test error")

        with patch("app.daemon.audit_logger"), \
             patch("app.daemon.notify"), \
             patch("app.daemon.wrap_exception") as mock_wrap, \
             patch("app.daemon.format_error") as mock_format:

            mock_wrapped = MagicMock()
            mock_wrapped.message = "Test error"
            mock_wrap.return_value = mock_wrapped
            mock_format.return_value = "Formatted error"

            # Act - should not raise
            daemon._handle_processing_error(email, error, processing_time_ms=None)

        # Assert - reached without exception
        mock_wrap.assert_called_once()


# =============================================================================
# Tests - Boundary Values
# (Removed 2026-05-15: TestBoundaryValues.test_processing_time_zero_ms
# targeted the deleted _create_and_save_draft helper.)
# =============================================================================
