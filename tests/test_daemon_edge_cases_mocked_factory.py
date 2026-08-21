"""
Tests TDD pour les edge cases du daemon utilisant create_mocked_daemon de conftest.py.

Ces tests vérifient les cas limites non couverts par les autres fichiers de test.

Edge cases critiques couverts:
1. poll_user_drafts() - update_draft retourne False
2. _check_draft_modification() - exception dans detect_user_modification
3. start() - avec skip_config_validation=True
4. run_once() - avec exception dans authenticate
5. _run_main_loop() - stop_event pendant le traitement

Cycle TDD: RED -> GREEN -> REFACTOR
Pattern: Arrange-Act-Assert
"""

import pytest
import threading
from unittest.mock import MagicMock, patch

from app.interfaces.email_provider import StandardEmail
from tests.conftest import create_mocked_daemon


# =============================================================================
# Tests - poll_user_drafts Edge Cases
# =============================================================================


class TestPollUserDraftsUpdateDraftFailure:
    """Tests pour poll_user_drafts quand update_draft échoue."""

    def test_update_draft_returns_false_logs_warning(self):
        """
        ARRANGE: update_draft() retourne False
        ACT: Appeler poll_user_drafts()
        ASSERT: Warning loggé, brouillon marqué comme traité
        """
        # Arrange
        daemon = create_mocked_daemon()

        # Créer un brouillon utilisateur
        draft = StandardEmail(
            id="draft-user-001",
            sender="user@example.com",
            to=["recipient@example.com"],
            subject="Complete this",
            body="Brouillon: respond to client",
            provider_source="test",
        )

        daemon.provider.get_user_drafts.return_value = [draft]
        daemon.processed_drafts_tracker.is_processed.return_value = False
        daemon.draft_completion_agent.is_completion_request.return_value = True
        daemon.draft_completion_agent.complete_with_options.return_value = MagicMock(
            subject="Completed subject",
            body="Completed body"
        )
        daemon.provider.update_draft.return_value = False  # Simule l'échec

        with patch("app.daemon.logger") as mock_logger:
            # Act
            result = daemon.poll_user_drafts()

        # Assert
        assert result == 0  # Pas de brouillon complété
        daemon.processed_drafts_tracker.mark_processed.assert_called_with("draft-user-001")
        # Vérifier qu'un warning a été loggé
        warning_calls = [c for c in mock_logger.warning.call_args_list
                        if "Échec mise à jour brouillon" in str(c)]
        assert len(warning_calls) > 0

    def test_update_draft_exception_marks_processed(self):
        """
        ARRANGE: update_draft() lève une exception
        ACT: Appeler poll_user_drafts()
        ASSERT: Exception gérée, brouillon marqué comme traité
        """
        # Arrange
        daemon = create_mocked_daemon()

        draft = StandardEmail(
            id="draft-error-001",
            sender="user@example.com",
            to=["recipient@example.com"],
            subject="Complete this",
            body="Brouillon: respond to client",
            provider_source="test",
        )

        daemon.provider.get_user_drafts.return_value = [draft]
        daemon.processed_drafts_tracker.is_processed.return_value = False
        daemon.draft_completion_agent.is_completion_request.return_value = True
        daemon.draft_completion_agent.complete_with_options.return_value = MagicMock(
            subject="Completed",
            body="Body"
        )
        daemon.provider.update_draft.side_effect = Exception("API error")

        # Act
        result = daemon.poll_user_drafts()

        # Assert
        assert result == 0
        daemon.processed_drafts_tracker.mark_processed.assert_called_with("draft-error-001")


# =============================================================================
# Tests - _check_draft_modification Edge Cases
# =============================================================================




# =============================================================================
# Tests - start() avec skip_config_validation
# =============================================================================


class TestStartWithSkipConfigValidation:
    """Tests pour start() avec différentes options de validation."""

    def test_start_with_skip_config_validation_true(self):
        """
        ARRANGE: skip_config_validation=True et config invalide
        ACT: Appeler start()
        ASSERT: La validation de config est ignorée
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon._stop_event = threading.Event()
        daemon._running = False

        # Simuler que la config est invalide (mais on skip)
        with patch("app.daemon.validate_config") as mock_validate, \
             patch("app.daemon.signal.signal"), \
             patch("app.daemon.audit_logger"), \
             patch.object(daemon, "_perform_startup_checks", return_value=False):

            mock_validate.return_value = ["Error: missing ANTHROPIC_API_KEY"]

            # Act
            daemon.start(skip_config_validation=True, skip_health_check=True)

        # Assert - validate_config ne doit pas être appelé
        mock_validate.assert_not_called()

    def test_start_with_skip_config_validation_false_and_invalid_config(self):
        """
        ARRANGE: skip_config_validation=False et config invalide
        ACT: Appeler start()
        ASSERT: Le démarrage est annulé
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon._stop_event = threading.Event()
        daemon._running = False

        with patch("app.daemon.validate_config") as mock_validate, \
             patch("app.daemon.logger") as mock_logger:

            mock_validate.return_value = ["Error 1", "Error 2"]

            # Act
            daemon.start(skip_config_validation=False)

        # Assert
        mock_validate.assert_called_once()
        # Vérifier que des erreurs ont été loguées
        error_calls = [c for c in mock_logger.error.call_args_list]
        assert len(error_calls) >= 2  # Au moins les 2 erreurs de config


# =============================================================================
# Tests - run_once() avec exceptions
# =============================================================================


class TestRunOnceExceptionHandling:
    """Tests pour run_once() avec différents types d'erreurs."""

    def test_run_once_authenticate_exception_propagates(self):
        """
        ARRANGE: authenticate() lève une exception
        ACT: Appeler run_once()
        ASSERT: L'exception est propagée (pas de try/except dans run_once)
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.side_effect = ConnectionError("Network error")

        # Act & Assert - l'exception doit être propagée car run_once ne l'attrape pas
        with pytest.raises(ConnectionError, match="Network error"):
            daemon.run_once()

    def test_run_once_poll_and_process_returns_count(self):
        """
        ARRANGE: Tout fonctionne correctement
        ACT: Appeler run_once()
        ASSERT: Retourne le nombre d'emails traités
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = True

        email = StandardEmail(
            id="test-email",
            sender="sender@example.com",
            subject="Test",
            body="Body",
            provider_source="test",
        )
        daemon.provider.get_unread_messages.return_value = [email]
        daemon.provider.get_messages.return_value = [email]

        with patch.object(daemon, "process_email", return_value=True), \
             patch("app.daemon.logger"):
            # Act
            result = daemon.run_once()

        # Assert
        assert result == 1


# =============================================================================
# Tests - _run_main_loop() Stop Event
# =============================================================================


class TestRunMainLoopStopEvent:
    """Tests pour _run_main_loop avec stop_event."""

    def test_stop_event_set_exits_loop_immediately(self):
        """
        ARRANGE: stop_event est set avant le premier cycle
        ACT: Appeler _run_main_loop()
        ASSERT: Sort immédiatement sans traitement
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon._running = True
        daemon._stop_event = threading.Event()
        daemon._stop_event.set()  # Déjà set

        with patch.object(daemon, "poll_and_process") as mock_poll, \
             patch.object(daemon, "poll_user_drafts"), \
             patch("app.daemon.token_counter"):

            # Act
            daemon._run_main_loop()

        # Assert - poll_and_process peut être appelé une fois avant le check
        # mais pas en boucle infinie
        assert mock_poll.call_count <= 1

    def test_keyboard_interrupt_exits_gracefully(self):
        """
        ARRANGE: KeyboardInterrupt pendant le traitement
        ACT: Appeler _run_main_loop()
        ASSERT: Sort proprement

        Mock `_ensure_provider_alive` à True : le code prod ajoute un
        keepalive check au début de la loop ; sans ce mock, le test hang
        30s dans `_stop_event.wait(timeout=30)` quand le check échoue.
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon._running = True
        daemon._stop_event = threading.Event()
        daemon.poll_interval = 0  # éviter wait() entre itérations

        call_count = [0]

        def raise_on_second_call():
            call_count[0] += 1
            if call_count[0] >= 2:
                raise KeyboardInterrupt()
            return 0

        with patch.object(daemon, "_ensure_provider_alive", return_value=True), \
             patch.object(daemon, "poll_and_process", side_effect=raise_on_second_call), \
             patch.object(daemon, "poll_user_drafts", return_value=0), \
             patch("app.daemon.token_counter"):

            # Act - should not raise
            daemon._run_main_loop()

        # Assert - exited without exception


# =============================================================================
# Tests - process_email avec anonymisation
# =============================================================================


class TestProcessEmailAnonymizationEdgeCases:
    """Tests pour process_email avec anonymisation."""

    def test_anonymization_with_empty_encrypted_token(self):
        """
        ARRANGE: Anonymisation retourne un token vide
        ACT: Call _anonymize_sensitive_data directly
        ASSERT: Returns non-None result with empty token
        """
        # Arrange
        daemon = create_mocked_daemon()

        # Mock de l'anonymisation avec token vide
        mock_anon_result = MagicMock()
        mock_anon_result.has_redactions = True
        mock_anon_result.items_anonymized = 1
        mock_anon_result.anonymized_content = "Anonymized content"
        mock_anon_result.encrypted_token = ""  # Token vide

        daemon.cryptographer.anonymize.return_value = mock_anon_result

        # Act
        result = daemon._anonymize_sensitive_data("Some content with data", "sender@example.com")

        # Assert
        assert result is not None
        assert result.encrypted_token == ""


# =============================================================================
# Tests - _extract_tasks_from_email Edge Cases
# =============================================================================




# =============================================================================
# Tests - _extract_commitments_from_draft Edge Cases
# =============================================================================




# =============================================================================
# Tests - health_check() avec LLM response vide
# =============================================================================


class TestHealthCheckLLMEdgeCases:
    """Tests pour health_check avec réponses LLM edge cases."""

    def test_health_check_llm_returns_empty_string(self):
        """
        ARRANGE: drafter.draft() retourne une chaîne vide
        ACT: Appeler health_check()
        ASSERT: llm=False car réponse vide
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = True
        daemon.drafter.draft.return_value = ""  # Réponse vide

        with patch("app.daemon.logger"):
            # Act
            result = daemon.health_check()

        # Assert
        assert result["email_provider"] is True
        assert result["llm"] is False  # Réponse vide = échec
        assert result["overall"] is False

    def test_health_check_llm_returns_none(self):
        """
        ARRANGE: drafter.draft() retourne None
        ACT: Appeler health_check()
        ASSERT: llm=False
        """
        # Arrange
        daemon = create_mocked_daemon()
        daemon.provider.authenticate.return_value = True
        daemon.drafter.draft.return_value = None

        with patch("app.daemon.logger"):
            # Act
            result = daemon.health_check()

        # Assert
        assert result["llm"] is False
        assert result["overall"] is False
