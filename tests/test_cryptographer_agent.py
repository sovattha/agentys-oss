# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests unitaires pour le CryptographerAgent."""
import pytest
from unittest.mock import Mock

from app.agents import CryptographerAgent
from app.domain.entities.anonymized_result import AnonymizedResult
from app.domain.entities.sensitive_data import (
    SensitiveDataDetection,
    SensitiveDataItem,
    SensitiveDataType,
)


class TestCryptographerAgent:
    @pytest.fixture
    def mock_detector(self):
        """Fixture pour créer un mock du SensitiveDataDetectorAgent."""
        detector = Mock()
        detector.detect.return_value = SensitiveDataDetection.default()
        return detector

    @pytest.fixture
    def mock_encryption(self):
        """Fixture pour créer un mock de l'encryption."""
        encryption = Mock()
        encryption.encrypt_mapping.return_value = "encrypted_token"
        encryption.decrypt_mapping.return_value = {}
        return encryption

    def test_anonymize_returns_anonymized_result(self, mock_detector, mock_encryption):
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        result = agent.anonymize("Test content", "test@example.com")

        assert isinstance(result, AnonymizedResult)

    def test_anonymize_with_no_sensitive_data(self, mock_detector, mock_encryption):
        mock_detector.detect.return_value = SensitiveDataDetection.default()

        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)
        result = agent.anonymize("Hello World", "test@example.com")

        assert result.anonymized_content == "Hello World"
        assert result.items_anonymized == 0

    def test_anonymize_replaces_sensitive_data(self, mock_encryption):
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone",
                    snippet="+33612345678",
                )
            ],
            analysis_summary="Phone found",
        )
        mock_detector = Mock()
        mock_detector.detect.return_value = detection

        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)
        result = agent.anonymize(
            "Call me at +33612345678",
            "external@example.com"
        )

        assert "+33612345678" not in result.anonymized_content
        assert "[REDACTED_" in result.anonymized_content
        assert result.items_anonymized == 1

    def test_restore_returns_original_content(self, mock_detector):
        mock_encryption = Mock()
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_abc12345]": "secret_value"
        }

        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)
        result = agent.restore(
            "Data is [REDACTED_abc12345]",
            "encrypted_token"
        )

        assert result == "Data is secret_value"
        mock_encryption.decrypt_mapping.assert_called_once_with("encrypted_token")

    def test_restore_with_empty_token_returns_unchanged(self, mock_detector, mock_encryption):
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)
        result = agent.restore("Hello World", "")

        assert result == "Hello World"

    def test_agent_is_dataclass(self):
        from dataclasses import is_dataclass
        assert is_dataclass(CryptographerAgent)


class TestCryptographerAgentIntegration:
    """Tests d'intégration avec les vrais composants."""

    @pytest.fixture
    def agent(self) -> CryptographerAgent:
        return CryptographerAgent()

    def test_full_anonymize_restore_cycle(self):
        """Test d'intégration avec detector mocké mais encryption réelle."""
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Secret code",
                    snippet="SECRET123",
                )
            ],
            analysis_summary="Secret found",
        )
        mock_detector = Mock()
        mock_detector.detect.return_value = detection

        # Utilise l'encryption réelle mais detector mocké
        agent = CryptographerAgent(_detector=mock_detector)
        original = "The code is SECRET123, don't share it."

        anonymized = agent.anonymize(original, "external@example.com")

        assert "SECRET123" not in anonymized.anonymized_content
        assert anonymized.has_redactions

        restored = agent.restore(
            anonymized.anonymized_content,
            anonymized.encrypted_token
        )

        assert restored == original


class TestCryptographerAgentEdgeCases:
    """Tests des cas limites pour CryptographerAgent."""

    @pytest.fixture
    def mock_detector(self):
        detector = Mock()
        detector.detect.return_value = SensitiveDataDetection.default()
        return detector

    @pytest.fixture
    def mock_encryption(self):
        encryption = Mock()
        encryption.encrypt_mapping.return_value = "encrypted_token"
        encryption.decrypt_mapping.return_value = {}
        return encryption

    def test_anonymize_empty_content(self, mock_detector, mock_encryption):
        """Anonymisation d'un contenu vide."""
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        result = agent.anonymize("", "test@example.com")

        assert result.anonymized_content == ""
        assert result.items_anonymized == 0

    def test_anonymize_empty_recipient(self, mock_detector, mock_encryption):
        """Anonymisation avec recipient vide."""
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        result = agent.anonymize("Hello World", "")

        mock_detector.detect.assert_called_once_with("Hello World", "")
        assert result.anonymized_content == "Hello World"

    def test_restore_empty_content(self, mock_detector, mock_encryption):
        """Restauration d'un contenu vide."""
        mock_encryption.decrypt_mapping.return_value = {}
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        result = agent.restore("", "token")

        assert result == ""

    def test_restore_with_none_like_empty_token(self, mock_detector, mock_encryption):
        """Restauration avec un token vide (pas d'appel au décryptage)."""
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        result = agent.restore("Hello World", "")

        assert result == "Hello World"
        mock_encryption.decrypt_mapping.assert_not_called()

    def test_detector_exception_propagates(self, mock_encryption):
        """L'exception du detector est propagée."""
        mock_detector = Mock()
        mock_detector.detect.side_effect = RuntimeError("Detector error")
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        with pytest.raises(RuntimeError, match="Detector error"):
            agent.anonymize("Content", "test@example.com")

    def test_encryption_exception_propagates_on_anonymize(self, mock_encryption):
        """L'exception d'encryption est propagée lors de l'anonymisation."""
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Secret",
                    snippet="secret",
                )
            ],
            analysis_summary="Secret found",
        )
        mock_detector = Mock()
        mock_detector.detect.return_value = detection
        mock_encryption.encrypt_mapping.side_effect = RuntimeError("Encrypt error")

        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        with pytest.raises(RuntimeError, match="Encrypt error"):
            agent.anonymize("My secret", "test@example.com")

    def test_decryption_exception_propagates_on_restore(self, mock_detector, mock_encryption):
        """L'exception de décryptage est propagée lors de la restauration."""
        mock_encryption.decrypt_mapping.side_effect = RuntimeError("Decrypt error")
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        with pytest.raises(RuntimeError, match="Decrypt error"):
            agent.restore("[REDACTED_abc]", "invalid_token")

    def test_anonymize_unicode_content(self, mock_encryption):
        """Anonymisation de contenu avec caractères unicode."""
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Nom",
                    snippet="François",
                )
            ],
            analysis_summary="Name found",
        )
        mock_detector = Mock()
        mock_detector.detect.return_value = detection
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        result = agent.anonymize("Bonjour François!", "test@example.com")

        assert "François" not in result.anonymized_content
        assert "[REDACTED_" in result.anonymized_content

    def test_restore_unicode_values(self, mock_detector, mock_encryption):
        """Restauration de valeurs avec caractères unicode."""
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_abc]": "François 🎉"
        }
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        result = agent.restore("Hello [REDACTED_abc]!", "token")

        assert result == "Hello François 🎉!"

    def test_default_initialization_creates_encryption(self, mock_detector):
        """L'agent crée l'encryption par défaut si non fournie."""
        # On injecte le detector pour éviter de charger anthropic
        agent = CryptographerAgent(_detector=mock_detector)

        # Vérifie que l'encryption est initialisée par défaut
        assert agent._encryption is not None
        from app.infrastructure.adapters.encryption_adapter import FernetEncryptionAdapter
        assert isinstance(agent._encryption, FernetEncryptionAdapter)

    def test_custom_dependencies_injection(self, mock_detector, mock_encryption):
        """L'agent accepte des dépendances personnalisées."""
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        assert agent._encryption is mock_encryption
        assert agent._detector is mock_detector

    def test_partial_dependency_injection_detector_only(self, mock_detector):
        """L'agent accepte seulement le detector, crée l'encryption par défaut."""
        agent = CryptographerAgent(_detector=mock_detector)

        assert agent._detector is mock_detector
        assert agent._encryption is not None
        from app.infrastructure.adapters.encryption_adapter import FernetEncryptionAdapter
        assert isinstance(agent._encryption, FernetEncryptionAdapter)

    def test_anonymize_multiple_sensitive_items(self, mock_encryption):
        """Anonymisation de plusieurs items sensibles."""
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.98,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone",
                    snippet="0612345678",
                ),
                SensitiveDataItem(
                    data_type=SensitiveDataType.FINANCIAL,
                    description="IBAN",
                    snippet="FR7612345",
                ),
            ],
            analysis_summary="Multiple items",
        )
        mock_detector = Mock()
        mock_detector.detect.return_value = detection
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        result = agent.anonymize("Tel: 0612345678, IBAN: FR7612345", "test@example.com")

        assert "0612345678" not in result.anonymized_content
        assert "FR7612345" not in result.anonymized_content
        assert result.items_anonymized == 2

    def test_idempotent_restore_on_already_restored_content(self, mock_detector, mock_encryption):
        """Restauration sur un contenu déjà restauré (pas de marqueurs)."""
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_abc]": "secret"
        }
        agent = CryptographerAgent(_encryption=mock_encryption, _detector=mock_detector)

        result = agent.restore("Hello World, no markers here", "token")

        assert result == "Hello World, no markers here"
