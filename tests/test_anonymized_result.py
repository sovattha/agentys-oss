# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests unitaires pour l'entité AnonymizedResult."""
import pytest
from app.domain.entities.anonymized_result import AnonymizedResult
from app.domain.entities.sensitive_data import (
    SensitiveDataDetection,
    SensitiveDataItem,
    SensitiveDataType,
)


class TestAnonymizedResult:
    def test_create_with_valid_data(self):
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
            analysis_summary="Found phone number",
        )

        result = AnonymizedResult(
            anonymized_content="Contact: [REDACTED_abc123]",
            encrypted_token="encrypted_data_here",
            items_anonymized=1,
            detection=detection,
        )

        assert result.anonymized_content == "Contact: [REDACTED_abc123]"
        assert result.encrypted_token == "encrypted_data_here"
        assert result.items_anonymized == 1
        assert result.detection == detection

    def test_create_empty_when_no_sensitive_data(self):
        detection = SensitiveDataDetection.default()

        result = AnonymizedResult.empty(
            original_content="Hello World",
            detection=detection,
        )

        assert result.anonymized_content == "Hello World"
        assert result.encrypted_token == ""
        assert result.items_anonymized == 0
        assert result.detection == detection

    def test_has_redactions_returns_true_when_items_anonymized(self):
        detection = SensitiveDataDetection.default()
        result = AnonymizedResult(
            anonymized_content="[REDACTED_abc]",
            encrypted_token="token",
            items_anonymized=1,
            detection=detection,
        )

        assert result.has_redactions is True

    def test_has_redactions_returns_false_when_no_items(self):
        detection = SensitiveDataDetection.default()
        result = AnonymizedResult(
            anonymized_content="Hello",
            encrypted_token="",
            items_anonymized=0,
            detection=detection,
        )

        assert result.has_redactions is False

    def test_items_anonymized_cannot_be_negative(self):
        detection = SensitiveDataDetection.default()

        with pytest.raises(ValueError, match="items_anonymized"):
            AnonymizedResult(
                anonymized_content="content",
                encrypted_token="",
                items_anonymized=-1,
                detection=detection,
            )

    def test_to_dict(self):
        detection = SensitiveDataDetection.default()
        result = AnonymizedResult(
            anonymized_content="[REDACTED]",
            encrypted_token="token123",
            items_anonymized=1,
            detection=detection,
        )

        data = result.to_dict()

        assert data["anonymized_content"] == "[REDACTED]"
        assert data["encrypted_token"] == "token123"
        assert data["items_anonymized"] == 1
        assert "detection" in data


class TestAnonymizedResultEdgeCases:
    """Tests des cas limites pour AnonymizedResult."""

    def test_empty_anonymized_content(self):
        """Contenu anonymisé vide est valide."""
        detection = SensitiveDataDetection.default()

        result = AnonymizedResult(
            anonymized_content="",
            encrypted_token="",
            items_anonymized=0,
            detection=detection,
        )

        assert result.anonymized_content == ""
        assert result.has_redactions is False

    def test_empty_encrypted_token_with_items(self):
        """Token vide avec items > 0 est techniquement valide."""
        detection = SensitiveDataDetection.default()

        result = AnonymizedResult(
            anonymized_content="[REDACTED_abc]",
            encrypted_token="",
            items_anonymized=1,
            detection=detection,
        )

        # Techniquement valide même si incohérent
        assert result.has_redactions is True
        assert result.encrypted_token == ""

    def test_frozen_dataclass_immutability(self):
        """Le dataclass est frozen et ne peut pas être modifié."""
        detection = SensitiveDataDetection.default()
        result = AnonymizedResult(
            anonymized_content="content",
            encrypted_token="token",
            items_anonymized=1,
            detection=detection,
        )

        with pytest.raises(AttributeError):
            result.anonymized_content = "new_content"

        with pytest.raises(AttributeError):
            result.items_anonymized = 2

    def test_unicode_content_in_result(self):
        """Le contenu unicode est supporté."""
        detection = SensitiveDataDetection.default()

        result = AnonymizedResult(
            anonymized_content="Bonjour [REDACTED_abc] 🎉",
            encrypted_token="token",
            items_anonymized=1,
            detection=detection,
        )

        assert "🎉" in result.anonymized_content
        assert result.to_dict()["anonymized_content"] == "Bonjour [REDACTED_abc] 🎉"

    def test_very_long_content(self):
        """Contenu très long est supporté."""
        detection = SensitiveDataDetection.default()
        long_content = "A" * 1000000

        result = AnonymizedResult(
            anonymized_content=long_content,
            encrypted_token="token",
            items_anonymized=0,
            detection=detection,
        )

        assert len(result.anonymized_content) == 1000000

    def test_very_long_token(self):
        """Token très long est supporté."""
        detection = SensitiveDataDetection.default()
        long_token = "x" * 100000

        result = AnonymizedResult(
            anonymized_content="content",
            encrypted_token=long_token,
            items_anonymized=0,
            detection=detection,
        )

        assert len(result.encrypted_token) == 100000

    def test_large_items_anonymized(self):
        """Grand nombre d'items anonymisés est supporté."""
        detection = SensitiveDataDetection.default()

        result = AnonymizedResult(
            anonymized_content="content",
            encrypted_token="token",
            items_anonymized=999999,
            detection=detection,
        )

        assert result.items_anonymized == 999999
        assert result.has_redactions is True

    def test_zero_items_anonymized_with_empty_factory(self):
        """Le factory method empty() retourne 0 items."""
        detection = SensitiveDataDetection.default()

        result = AnonymizedResult.empty("original", detection)

        assert result.items_anonymized == 0
        assert result.has_redactions is False

    def test_empty_with_long_original_content(self):
        """Le factory empty() accepte du contenu très long."""
        detection = SensitiveDataDetection.default()
        long_original = "B" * 500000

        result = AnonymizedResult.empty(long_original, detection)

        assert result.anonymized_content == long_original
        assert len(result.anonymized_content) == 500000

    def test_to_dict_with_sensitive_detection(self):
        """to_dict() fonctionne avec une détection sensible."""
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

        result = AnonymizedResult(
            anonymized_content="[REDACTED_abc]",
            encrypted_token="encrypted",
            items_anonymized=1,
            detection=detection,
        )

        data = result.to_dict()

        assert data["detection"]["is_sensitive"] is True
        assert data["detection"]["confidence"] == 0.95

    def test_special_characters_in_content(self):
        """Caractères spéciaux dans le contenu."""
        detection = SensitiveDataDetection.default()

        result = AnonymizedResult(
            anonymized_content="Content with <html> & \"quotes\" + 'apostrophes'",
            encrypted_token="token",
            items_anonymized=0,
            detection=detection,
        )

        assert "<html>" in result.anonymized_content
        assert "&" in result.anonymized_content

    def test_newlines_and_tabs_in_content(self):
        """Retours à la ligne et tabulations dans le contenu."""
        detection = SensitiveDataDetection.default()

        result = AnonymizedResult(
            anonymized_content="Line1\nLine2\tTabbed",
            encrypted_token="token",
            items_anonymized=0,
            detection=detection,
        )

        assert "\n" in result.anonymized_content
        assert "\t" in result.anonymized_content
