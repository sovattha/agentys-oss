# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests pour AnonymizeContentUseCase et RestoreContentUseCase."""
import re
import pytest
from unittest.mock import Mock

from app.application.anonymize_content import AnonymizeContentUseCase
from app.application.restore_content import RestoreContentUseCase
from app.domain.entities.sensitive_data import (
    SensitiveDataDetection,
    SensitiveDataItem,
    SensitiveDataType,
)
from app.domain.ports.encryption_port import EncryptionPort
from app.domain.ports.sensitive_data_port import SensitiveDataDetectorPort


class TestAnonymizeContentUseCase:
    @pytest.fixture
    def mock_detector(self) -> Mock:
        return Mock(spec=SensitiveDataDetectorPort)

    @pytest.fixture
    def mock_encryption(self) -> Mock:
        mock = Mock(spec=EncryptionPort)
        mock.encrypt_mapping.return_value = "encrypted_token_abc"
        return mock

    @pytest.fixture
    def use_case(self, mock_detector, mock_encryption) -> AnonymizeContentUseCase:
        return AnonymizeContentUseCase(
            detector=mock_detector,
            encryption=mock_encryption,
        )

    def test_returns_original_when_no_sensitive_data(self, use_case, mock_detector):
        mock_detector.detect.return_value = SensitiveDataDetection.default()
        content = "Hello World, this is a test."

        result = use_case.execute(content, "test@example.com")

        assert result.anonymized_content == content
        assert result.encrypted_token == ""
        assert result.items_anonymized == 0
        assert result.has_redactions is False

    def test_anonymizes_single_sensitive_item(self, use_case, mock_detector, mock_encryption):
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone number",
                    snippet="+33612345678",
                )
            ],
            analysis_summary="Phone detected",
        )
        mock_detector.detect.return_value = detection

        result = use_case.execute(
            "Mon numéro est +33612345678, appelez-moi.",
            "external@company.com"
        )

        assert "+33612345678" not in result.anonymized_content
        assert "[REDACTED_" in result.anonymized_content
        assert result.items_anonymized == 1
        assert result.encrypted_token == "encrypted_token_abc"
        mock_encryption.encrypt_mapping.assert_called_once()

    def test_anonymizes_multiple_sensitive_items(self, use_case, mock_detector, mock_encryption):
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.98,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone",
                    snippet="+33612345678",
                ),
                SensitiveDataItem(
                    data_type=SensitiveDataType.FINANCIAL,
                    description="IBAN",
                    snippet="FR76123456789",
                ),
            ],
            analysis_summary="Multiple items",
        )
        mock_detector.detect.return_value = detection

        result = use_case.execute(
            "Tel: +33612345678, IBAN: FR76123456789",
            "external@company.com"
        )

        assert "+33612345678" not in result.anonymized_content
        assert "FR76123456789" not in result.anonymized_content
        assert result.items_anonymized == 2

    def test_generates_unique_markers_for_each_item(self, use_case, mock_detector, mock_encryption):
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.98,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone 1",
                    snippet="111",
                ),
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone 2",
                    snippet="222",
                ),
            ],
            analysis_summary="Multiple items",
        )
        mock_detector.detect.return_value = detection

        result = use_case.execute("111 and 222", "test@example.com")

        markers = re.findall(r"\[REDACTED_[a-f0-9]+\]", result.anonymized_content)
        assert len(markers) == 2
        assert markers[0] != markers[1]

    def test_generates_unique_markers_when_uuid_repeats(self, use_case, mock_detector, mock_encryption, monkeypatch):
        class FixedUuid:
            hex = "51285a93abcdef00"

        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.98,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone 1",
                    snippet="111",
                ),
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone 2",
                    snippet="222",
                ),
            ],
            analysis_summary="Multiple items",
        )
        mock_detector.detect.return_value = detection
        monkeypatch.setattr("app.application.anonymize_content.uuid.uuid4", lambda: FixedUuid())

        result = use_case.execute("111 and 222", "test@example.com")

        markers = re.findall(r"\[REDACTED_[a-f0-9]+\]", result.anonymized_content)
        assert len(markers) == 2
        assert markers[0] != markers[1]

    def test_preserves_detection_in_result(self, use_case, mock_detector):
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone",
                    snippet="12345",
                )
            ],
            analysis_summary="Found phone",
        )
        mock_detector.detect.return_value = detection

        result = use_case.execute("Call 12345", "test@example.com")

        assert result.detection == detection


class TestRestoreContentUseCase:
    @pytest.fixture
    def mock_encryption(self) -> Mock:
        return Mock(spec=EncryptionPort)

    @pytest.fixture
    def use_case(self, mock_encryption) -> RestoreContentUseCase:
        return RestoreContentUseCase(encryption=mock_encryption)

    def test_restores_single_redaction(self, use_case, mock_encryption):
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_abc12345]": "+33612345678"
        }

        result = use_case.execute(
            "Mon numéro est [REDACTED_abc12345], appelez-moi.",
            "encrypted_token"
        )

        assert result == "Mon numéro est +33612345678, appelez-moi."
        mock_encryption.decrypt_mapping.assert_called_once_with("encrypted_token")

    def test_restores_multiple_redactions(self, use_case, mock_encryption):
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_aaa]": "secret1",
            "[REDACTED_bbb]": "secret2",
        }

        result = use_case.execute(
            "[REDACTED_aaa] and [REDACTED_bbb]",
            "token"
        )

        assert result == "secret1 and secret2"

    def test_returns_content_unchanged_when_empty_token(self, use_case, mock_encryption):
        result = use_case.execute("Hello World", "")

        assert result == "Hello World"
        mock_encryption.decrypt_mapping.assert_not_called()

    def test_preserves_unmatched_text(self, use_case, mock_encryption):
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_xyz]": "secret"
        }

        result = use_case.execute(
            "Prefix [REDACTED_xyz] suffix",
            "token"
        )

        assert result == "Prefix secret suffix"


class TestAnonymizeContentUseCaseEdgeCases:
    """Tests des cas limites pour AnonymizeContentUseCase."""

    @pytest.fixture
    def mock_detector(self) -> Mock:
        return Mock(spec=SensitiveDataDetectorPort)

    @pytest.fixture
    def mock_encryption(self) -> Mock:
        mock = Mock(spec=EncryptionPort)
        mock.encrypt_mapping.return_value = "encrypted_token"
        return mock

    @pytest.fixture
    def use_case(self, mock_detector, mock_encryption) -> AnonymizeContentUseCase:
        return AnonymizeContentUseCase(
            detector=mock_detector,
            encryption=mock_encryption,
        )

    def test_empty_content(self, use_case, mock_detector):
        mock_detector.detect.return_value = SensitiveDataDetection.default()

        result = use_case.execute("", "test@example.com")

        assert result.anonymized_content == ""
        assert result.items_anonymized == 0

    def test_empty_recipient(self, use_case, mock_detector):
        mock_detector.detect.return_value = SensitiveDataDetection.default()

        result = use_case.execute("Hello World", "")

        mock_detector.detect.assert_called_once_with("Hello World", "")
        assert result.anonymized_content == "Hello World"

    def test_snippet_not_found_in_content(self, use_case, mock_detector, mock_encryption):
        """Si le snippet détecté n'est pas dans le contenu, il reste inchangé."""
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone",
                    snippet="NOT_IN_CONTENT",
                )
            ],
            analysis_summary="Phone detected",
        )
        mock_detector.detect.return_value = detection

        result = use_case.execute("Hello World", "test@example.com")

        # Le contenu reste inchangé car le snippet n'est pas trouvé
        assert result.anonymized_content == "Hello World"
        # Mais le mapping est quand même créé (comportement actuel)
        assert result.items_anonymized == 1

    def test_snippet_appears_multiple_times(self, use_case, mock_detector, mock_encryption):
        """Seule la première occurrence du snippet est remplacée."""
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Secret",
                    snippet="SECRET",
                )
            ],
            analysis_summary="Secret detected",
        )
        mock_detector.detect.return_value = detection

        result = use_case.execute("SECRET and SECRET again", "test@example.com")

        # Une seule occurrence est remplacée (replace avec count=1)
        assert result.anonymized_content.count("SECRET") == 1
        assert result.anonymized_content.count("[REDACTED_") == 1

    def test_unicode_content(self, use_case, mock_detector, mock_encryption):
        """Le contenu avec caractères unicode est traité correctement."""
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
            analysis_summary="Name detected",
        )
        mock_detector.detect.return_value = detection

        result = use_case.execute("Bonjour François, ça va?", "test@example.com")

        assert "François" not in result.anonymized_content
        assert "[REDACTED_" in result.anonymized_content
        assert "ça va?" in result.anonymized_content

    def test_emoji_content(self, use_case, mock_detector, mock_encryption):
        """Le contenu avec emojis est traité correctement."""
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Phone",
                    snippet="123456",
                )
            ],
            analysis_summary="Phone detected",
        )
        mock_detector.detect.return_value = detection

        result = use_case.execute("Call me 📞 123456 🎉", "test@example.com")

        assert "123456" not in result.anonymized_content
        assert "📞" in result.anonymized_content
        assert "🎉" in result.anonymized_content

    def test_detector_raises_exception(self, use_case, mock_detector):
        """L'exception du detector est propagée."""
        mock_detector.detect.side_effect = RuntimeError("Detector failed")

        with pytest.raises(RuntimeError, match="Detector failed"):
            use_case.execute("Content", "test@example.com")

    def test_encryption_raises_exception(self, use_case, mock_detector, mock_encryption):
        """L'exception de l'encryption est propagée."""
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Secret",
                    snippet="secret123",
                )
            ],
            analysis_summary="Secret detected",
        )
        mock_detector.detect.return_value = detection
        mock_encryption.encrypt_mapping.side_effect = RuntimeError("Encryption failed")

        with pytest.raises(RuntimeError, match="Encryption failed"):
            use_case.execute("My secret123", "test@example.com")

    def test_very_long_content(self, use_case, mock_detector, mock_encryption):
        """Le contenu très long est traité correctement."""
        long_content = "A" * 100000 + "SECRET" + "B" * 100000
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[
                SensitiveDataItem(
                    data_type=SensitiveDataType.PERSONAL,
                    description="Secret",
                    snippet="SECRET",
                )
            ],
            analysis_summary="Secret detected",
        )
        mock_detector.detect.return_value = detection

        result = use_case.execute(long_content, "test@example.com")

        assert "SECRET" not in result.anonymized_content
        assert len(result.anonymized_content) > 200000

    def test_whitespace_only_content(self, use_case, mock_detector):
        """Le contenu avec uniquement des espaces."""
        mock_detector.detect.return_value = SensitiveDataDetection.default()

        result = use_case.execute("   \n\t  ", "test@example.com")

        assert result.anonymized_content == "   \n\t  "
        assert result.items_anonymized == 0


class TestRestoreContentUseCaseEdgeCases:
    """Tests des cas limites pour RestoreContentUseCase."""

    @pytest.fixture
    def mock_encryption(self) -> Mock:
        return Mock(spec=EncryptionPort)

    @pytest.fixture
    def use_case(self, mock_encryption) -> RestoreContentUseCase:
        return RestoreContentUseCase(encryption=mock_encryption)

    def test_empty_content(self, use_case, mock_encryption):
        mock_encryption.decrypt_mapping.return_value = {}

        result = use_case.execute("", "token")

        assert result == ""

    def test_marker_not_in_content(self, use_case, mock_encryption):
        """Si le marqueur du mapping n'est pas dans le contenu, rien ne change."""
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_notexist]": "secret"
        }

        result = use_case.execute("Hello World", "token")

        assert result == "Hello World"

    def test_partial_marker_match(self, use_case, mock_encryption):
        """Un marqueur partiel ne doit pas être remplacé."""
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_abc]": "secret"
        }

        result = use_case.execute("[REDACTED_abc123]", "token")

        # Le marqueur abc123 ne correspond pas exactement à abc
        assert result == "[REDACTED_abc123]"

    def test_decrypt_raises_exception(self, use_case, mock_encryption):
        """L'exception de décryptage est propagée."""
        mock_encryption.decrypt_mapping.side_effect = RuntimeError("Decrypt failed")

        with pytest.raises(RuntimeError, match="Decrypt failed"):
            use_case.execute("Content", "invalid_token")

    def test_unicode_restoration(self, use_case, mock_encryption):
        """La restauration avec caractères unicode fonctionne."""
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_abc]": "François 🎉"
        }

        result = use_case.execute("Bonjour [REDACTED_abc]!", "token")

        assert result == "Bonjour François 🎉!"

    def test_multiple_same_marker(self, use_case, mock_encryption):
        """Plusieurs occurrences du même marqueur sont toutes remplacées."""
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_abc]": "secret"
        }

        result = use_case.execute("[REDACTED_abc] and [REDACTED_abc]", "token")

        assert result == "secret and secret"

    def test_very_long_content_restoration(self, use_case, mock_encryption):
        """La restauration fonctionne sur du contenu très long."""
        long_prefix = "A" * 100000
        long_suffix = "B" * 100000
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_x]": "SECRET"
        }

        result = use_case.execute(f"{long_prefix}[REDACTED_x]{long_suffix}", "token")

        assert result == f"{long_prefix}SECRET{long_suffix}"

    def test_nested_looking_markers(self, use_case, mock_encryption):
        """Des marqueurs qui ressemblent à des marqueurs imbriqués."""
        mock_encryption.decrypt_mapping.return_value = {
            "[REDACTED_outer]": "[REDACTED_inner]"
        }

        result = use_case.execute("Value: [REDACTED_outer]", "token")

        # Le résultat contient le texte "[REDACTED_inner]" littéralement
        assert result == "Value: [REDACTED_inner]"
