# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Tests TDD pour l'intégration CryptographerAgent dans le daemon.

Ce fichier teste:
1. Anonymisation des données sensibles au lieu de blocage
2. Stockage du token de restauration dans le contexte
3. Non-impact sur les brouillons sans données sensibles
4. Label SENSITIVE_DATA_ANONYMIZED appliqué correctement

Cycle TDD: RED → GREEN → REFACTOR
"""

import pytest
from unittest.mock import MagicMock

from app.interfaces.email_provider import EmailProvider, StandardEmail
from app.domain.entities.anonymized_result import AnonymizedResult
from app.domain.entities.sensitive_data import SensitiveDataDetection

# Réutilisation de la factory centralisée depuis conftest.py
from tests.conftest import create_mocked_daemon


@pytest.fixture
def mock_provider():
    provider = MagicMock(spec=EmailProvider)
    provider.provider_name = "mock"
    provider.authenticate.return_value = True
    provider.get_unread_messages.return_value = []
    provider.create_draft.return_value = "draft-001"
    provider.mark_as_read.return_value = True
    provider.apply_label.return_value = True
    return provider


@pytest.fixture
def sample_email():
    return StandardEmail(
        id="email-001",
        sender="sender@example.com",
        sender_name="Sender",
        subject="Test Subject",
        body="Test body content",
        provider_source="test",
    )


@pytest.fixture
def mock_container():
    container = MagicMock()

    tracker = MagicMock()
    tracker.is_processed.return_value = False
    tracker.count.return_value = 0
    container.get_processed_emails_tracker.return_value = tracker

    learning_service = MagicMock()
    learning_service.should_require_review.return_value = False
    container.get_learning_service.return_value = learning_service

    draft_history = MagicMock()
    container.get_draft_history.return_value = draft_history

    return container


class TestDaemonAnonymization:
    """Tests for anonymization integration in the daemon.

    Note: auto-draft is disabled in process_email(), so the anonymization
    step is never reached via process_email(). These tests now verify
    _anonymize_sensitive_data() directly instead.
    """

    def test_process_email_anonymizes_sensitive_data(
        self, mock_provider, sample_email, mock_container
    ):
        """Auto-draft disabled: process_email returns True without anonymization.
        Test _anonymize_sensitive_data directly instead."""
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = True
        anonymized_result = AnonymizedResult(
            anonymized_content="Draft with [REDACTED_IBAN_1] instead of real data",
            encrypted_token="encrypted_token_abc123",
            items_anonymized=1,
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = anonymized_result

        # Test _anonymize_sensitive_data directly
        result = daemon._anonymize_sensitive_data("Draft with real IBAN data", "sender@example.com")

        assert result is not None
        assert result.encrypted_token == "encrypted_token_abc123"
        daemon.cryptographer.anonymize.assert_called_once()

    def test_process_email_stores_encrypted_token_in_context(
        self, mock_provider, sample_email, mock_container
    ):
        """Test anonymization returns encrypted token when sensitive data found."""
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = True
        anonymized_result = AnonymizedResult(
            anonymized_content="Anonymized draft content",
            encrypted_token="my_encrypted_token_xyz",
            items_anonymized=2,
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = anonymized_result

        result = daemon._anonymize_sensitive_data("Content with sensitive data", "sender@example.com")

        assert result is not None
        assert result.encrypted_token == "my_encrypted_token_xyz"

    def test_process_email_no_impact_without_sensitive_data(
        self, mock_provider, sample_email, mock_container
    ):
        """Test anonymization returns None when no sensitive data found."""
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = False
        no_redaction_result = AnonymizedResult.empty(
            original_content="Draft without sensitive data",
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = no_redaction_result

        result = daemon._anonymize_sensitive_data("Draft without sensitive data", "sender@example.com")

        assert result is None

    def test_process_email_uses_anonymized_content_for_draft(
        self, mock_provider, sample_email, mock_container
    ):
        """Test anonymization returns anonymized content when sensitive data found."""
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = True
        anonymized_result = AnonymizedResult(
            anonymized_content="ANONYMIZED: [REDACTED_PHONE_1] is hidden",
            encrypted_token="token123",
            items_anonymized=1,
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = anonymized_result

        result = daemon._anonymize_sensitive_data("Content with phone number", "sender@example.com")

        assert result is not None
        assert result.anonymized_content == "ANONYMIZED: [REDACTED_PHONE_1] is hidden"


class TestDraftCreationContextWithToken:

    def test_draft_creation_context_has_encrypted_token_field(self):
        from app.daemon import DraftCreationContext

        email = StandardEmail(
            id="test-id",
            sender="test@test.com",
            sender_name="Test",
            subject="Test",
            body="Body",
            provider_source="test",
        )

        context = DraftCreationContext(
            email=email,
            draft_v1="v1",
            critique="critique",
            final_draft="final",
            status="VALID",
            category="NORMAL",
            priority_score=50,
            processing_time_ms=100,
            encrypted_token="my_secret_token",
        )

        assert context.encrypted_token == "my_secret_token"

    def test_draft_creation_context_encrypted_token_defaults_to_none(self):
        from app.daemon import DraftCreationContext

        email = StandardEmail(
            id="test-id",
            sender="test@test.com",
            sender_name="Test",
            subject="Test",
            body="Body",
            provider_source="test",
        )

        context = DraftCreationContext(
            email=email,
            draft_v1="v1",
            critique="critique",
            final_draft="final",
            status="VALID",
            category="NORMAL",
            priority_score=50,
            processing_time_ms=100,
        )

        assert context.encrypted_token is None


class TestAnonymizeSensitiveDataMethod:

    def test_anonymize_sensitive_data_returns_result_when_sensitive(
        self, mock_provider, mock_container
    ):
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = True
        expected_result = AnonymizedResult(
            anonymized_content="anonymized",
            encrypted_token="token",
            items_anonymized=1,
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = expected_result

        result = daemon._anonymize_sensitive_data("content with IBAN", "recipient@ex.com")

        assert result is expected_result
        daemon.cryptographer.anonymize.assert_called_once_with(
            "content with IBAN", "recipient@ex.com"
        )

    def test_anonymize_sensitive_data_returns_none_when_not_sensitive(
        self, mock_provider, mock_container
    ):
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = False
        no_redaction = AnonymizedResult.empty("clean content", detection)

        daemon.cryptographer.anonymize.return_value = no_redaction

        result = daemon._anonymize_sensitive_data("clean content", "recipient@ex.com")

        assert result is None


# =============================================================================
# Tests Edge Cases - Anonymisation dans le Daemon
# =============================================================================


class TestAnonymizationEdgeCases:
    """Tests pour les edge cases d'anonymisation dans le daemon."""

    def test_cryptographer_exception_is_handled_gracefully(
        self, mock_provider, sample_email, mock_container
    ):
        """
        ARRANGE: cryptographer.anonymize() lève une exception
        ACT: Appeler _anonymize_sensitive_data()
        ASSERT: L'exception propagates (caller handles it)

        Note: auto-draft disabled means process_email() returns True at step 2.6b
        before reaching anonymization. Test the method directly.
        """
        # Arrange
        daemon = create_mocked_daemon(mock_provider, mock_container)
        daemon.cryptographer.anonymize.side_effect = RuntimeError("Encryption key error")

        # Act & Assert - the exception propagates from _anonymize_sensitive_data
        with pytest.raises(RuntimeError, match="Encryption key error"):
            daemon._anonymize_sensitive_data("Content", "sender@example.com")

    def test_anonymize_empty_content_returns_empty_result(
        self, mock_provider, mock_container
    ):
        """
        ARRANGE: Contenu vide à anonymiser
        ACT: Appeler _anonymize_sensitive_data("")
        ASSERT: Retourne None (pas de données sensibles dans contenu vide)
        """
        # Arrange
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = False
        empty_result = AnonymizedResult.empty("", detection)
        daemon.cryptographer.anonymize.return_value = empty_result

        # Act
        result = daemon._anonymize_sensitive_data("", "recipient@example.com")

        # Assert
        assert result is None
        daemon.cryptographer.anonymize.assert_called_once_with("", "recipient@example.com")

    def test_anonymize_with_empty_recipient(self, mock_provider, mock_container):
        """
        ARRANGE: Recipient vide
        ACT: Appeler _anonymize_sensitive_data avec recipient=""
        ASSERT: Le cryptographer est appelé avec recipient vide
        """
        # Arrange
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = False
        no_redaction = AnonymizedResult.empty("content", detection)
        daemon.cryptographer.anonymize.return_value = no_redaction

        # Act
        result = daemon._anonymize_sensitive_data("content", "")

        # Assert
        daemon.cryptographer.anonymize.assert_called_once_with("content", "")
        assert result is None

    def test_anonymize_multiple_sensitive_items(
        self, mock_provider, sample_email, mock_container
    ):
        """
        ARRANGE: Content with multiple sensitive items (IBAN, phone, email)
        ACT: Call _anonymize_sensitive_data() directly
        ASSERT: All sensitive data is anonymized
        """
        # Arrange
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = True
        multi_item_result = AnonymizedResult(
            anonymized_content="Contact: [REDACTED_PHONE_1], IBAN: [REDACTED_IBAN_1], Email: [REDACTED_EMAIL_1]",
            encrypted_token="multi_token_xyz",
            items_anonymized=3,
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = multi_item_result

        # Act
        result = daemon._anonymize_sensitive_data("Content with phone, IBAN, email", "sender@example.com")

        # Assert
        assert result is not None
        assert result.encrypted_token == "multi_token_xyz"
        assert "[REDACTED_PHONE_1]" in result.anonymized_content
        assert "[REDACTED_IBAN_1]" in result.anonymized_content
        assert "[REDACTED_EMAIL_1]" in result.anonymized_content

    def test_anonymize_unicode_sensitive_data(
        self, mock_provider, mock_container
    ):
        """
        ARRANGE: Données sensibles avec caractères Unicode (émojis, accents)
        ACT: Appeler _anonymize_sensitive_data()
        ASSERT: Les caractères Unicode sont correctement gérés
        """
        # Arrange
        daemon = create_mocked_daemon(mock_provider, mock_container)

        content_with_unicode = "Bonjour François 🎉, voici mon IBAN: FR7612345"
        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = True
        unicode_result = AnonymizedResult(
            anonymized_content="Bonjour François 🎉, voici mon IBAN: [REDACTED_IBAN_1]",
            encrypted_token="unicode_token",
            items_anonymized=1,
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = unicode_result

        # Act
        result = daemon._anonymize_sensitive_data(
            content_with_unicode, "recipient@example.com"
        )

        # Assert
        assert result is not None
        assert result.items_anonymized == 1
        assert "François" in result.anonymized_content
        assert "🎉" in result.anonymized_content
        assert "[REDACTED_IBAN_1]" in result.anonymized_content

    def test_anonymize_with_empty_encrypted_token(
        self, mock_provider, sample_email, mock_container
    ):
        """
        ARRANGE: Anonymisation retourne un token vide mais items_anonymized > 0
        ACT: Call _anonymize_sensitive_data() directly
        ASSERT: Returns AnonymizedResult with empty token
        """
        # Arrange
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = True
        weird_result = AnonymizedResult(
            anonymized_content="Anonymized but with empty token",
            encrypted_token="",  # Empty token (edge case)
            items_anonymized=1,
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = weird_result

        # Act
        result = daemon._anonymize_sensitive_data("Content with sensitive data", "sender@example.com")

        # Assert - has_redactions is True because items_anonymized > 0
        assert result is not None
        assert result.encrypted_token == ""

    def test_cryptographer_none_fails_gracefully(
        self, mock_provider, sample_email, mock_container
    ):
        """
        ARRANGE: daemon.cryptographer = None (non initialisé)
        ACT: Appeler _anonymize_sensitive_data()
        ASSERT: Raises AttributeError (None has no .anonymize method)

        Note: auto-draft disabled means process_email() returns True at step 2.6b.
        Test the method directly.
        """
        # Arrange
        daemon = create_mocked_daemon(mock_provider, mock_container)
        daemon.cryptographer = None

        # Act & Assert - None has no .anonymize
        with pytest.raises(AttributeError):
            daemon._anonymize_sensitive_data("Content", "sender@example.com")

    def test_anonymize_very_long_content(self, mock_provider, mock_container):
        """
        ARRANGE: Contenu très long (>10000 caractères) avec données sensibles
        ACT: Appeler _anonymize_sensitive_data()
        ASSERT: Le cryptographer est appelé avec le contenu complet
        """
        # Arrange
        daemon = create_mocked_daemon(mock_provider, mock_container)

        long_content = "A" * 10000 + " IBAN: FR7612345 " + "B" * 10000
        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = True
        long_result = AnonymizedResult(
            anonymized_content="A" * 10000 + " IBAN: [REDACTED_IBAN_1] " + "B" * 10000,
            encrypted_token="long_token",
            items_anonymized=1,
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = long_result

        # Act
        result = daemon._anonymize_sensitive_data(long_content, "recipient@example.com")

        # Assert
        assert result is not None
        assert len(result.anonymized_content) > 20000
        assert result.items_anonymized == 1
        daemon.cryptographer.anonymize.assert_called_once_with(
            long_content, "recipient@example.com"
        )


class TestAnonymizationLabelApplication:
    """Tests pour l'application du label SENSITIVE_DATA_ANONYMIZED."""

    def test_label_applied_only_when_items_anonymized_positive(
        self, mock_provider, sample_email, mock_container
    ):
        """
        ARRANGE: items_anonymized = 0 but is_sensitive = True
        ACT: Call _anonymize_sensitive_data() directly
        ASSERT: Returns None (has_redactions=False when items_anonymized=0)
        """
        # Arrange
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = True  # Sensible mais pas d'items anonymisés
        no_items_result = AnonymizedResult(
            anonymized_content="Content unchanged",
            encrypted_token="",
            items_anonymized=0,  # Zero items
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = no_items_result

        # Act
        result = daemon._anonymize_sensitive_data("Content unchanged", "sender@example.com")

        # Assert - has_redactions is False when items_anonymized=0
        assert result is None

    def test_label_applied_when_items_anonymized_is_one(
        self, mock_provider, sample_email, mock_container
    ):
        """
        ARRANGE: items_anonymized = 1
        ACT: Call _anonymize_sensitive_data() directly
        ASSERT: Returns non-None result (label application happens in process_email)

        Note: auto-draft disabled means process_email returns True at step 2.6b.
        The label is applied in process_email's step 7 which is now unreachable.
        Test that _anonymize_sensitive_data returns the result correctly.
        """
        # Arrange
        daemon = create_mocked_daemon(mock_provider, mock_container)

        detection = MagicMock(spec=SensitiveDataDetection)
        detection.is_sensitive = True
        one_item_result = AnonymizedResult(
            anonymized_content="[REDACTED_DATA_1]",
            encrypted_token="token",
            items_anonymized=1,
            detection=detection,
        )

        daemon.cryptographer.anonymize.return_value = one_item_result

        # Act
        result = daemon._anonymize_sensitive_data("[REDACTED_DATA_1]", "sender@example.com")

        # Assert - result is not None means has_redactions is True
        assert result is not None
        assert result.items_anonymized == 1


class TestAnonymizationWithRevision:
    """Tests pour l'anonymisation avec le cycle de révision V1->V2."""
