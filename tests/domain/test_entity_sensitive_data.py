# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.domain.entities.sensitive_data."""

import pytest
from app.domain.entities.sensitive_data import (
    SensitiveDataType,
    SensitiveDataItem,
    SensitiveDataDetection,
)
from app.domain.exceptions import InvalidBoundsError


# ============================================================================
# SensitiveDataType
# ============================================================================

class TestSensitiveDataType:
    """Tests pour l'enum SensitiveDataType."""

    def test_all_types_exist(self):
        assert SensitiveDataType.FINANCIAL.value == "financial"
        assert SensitiveDataType.PERSONAL.value == "personal"
        assert SensitiveDataType.COMMERCIAL_SECRET.value == "commercial"
        assert SensitiveDataType.CREDENTIAL.value == "credential"

    def test_enum_count(self):
        assert len(SensitiveDataType) == 4


# ============================================================================
# SensitiveDataItem
# ============================================================================

class TestSensitiveDataItem:
    """Tests pour SensitiveDataItem."""

    def test_create_item(self):
        item = SensitiveDataItem(
            data_type=SensitiveDataType.FINANCIAL,
            description="Numéro de carte bancaire",
            snippet="4532-XXXX-XXXX-1234",
        )
        assert item.data_type == SensitiveDataType.FINANCIAL
        assert item.description == "Numéro de carte bancaire"

    def test_to_dict(self):
        item = SensitiveDataItem(
            data_type=SensitiveDataType.CREDENTIAL,
            description="API key",
            snippet="sk-abc123...",
        )
        d = item.to_dict()
        assert d == {
            "data_type": "credential",
            "description": "API key",
            "snippet": "sk-abc123...",
        }

    def test_all_data_types_serialize(self):
        for dtype in SensitiveDataType:
            item = SensitiveDataItem(data_type=dtype, description="test", snippet="x")
            d = item.to_dict()
            assert d["data_type"] == dtype.value


# ============================================================================
# SensitiveDataDetection
# ============================================================================

class TestSensitiveDataDetection:
    """Tests pour SensitiveDataDetection."""

    def test_create_valid_detection(self):
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[],
            analysis_summary="Sensitive data found",
        )
        assert detection.is_sensitive is True
        assert detection.confidence == 0.95

    def test_confidence_zero_is_valid(self):
        detection = SensitiveDataDetection(
            is_sensitive=False, confidence=0.0, detected_items=[], analysis_summary=""
        )
        assert detection.confidence == 0.0

    def test_confidence_one_is_valid(self):
        detection = SensitiveDataDetection(
            is_sensitive=True, confidence=1.0, detected_items=[], analysis_summary=""
        )
        assert detection.confidence == 1.0

    def test_confidence_negative_raises(self):
        with pytest.raises(InvalidBoundsError):
            SensitiveDataDetection(
                is_sensitive=False, confidence=-0.1, detected_items=[], analysis_summary=""
            )

    def test_confidence_above_one_raises(self):
        with pytest.raises(InvalidBoundsError):
            SensitiveDataDetection(
                is_sensitive=True, confidence=1.1, detected_items=[], analysis_summary=""
            )

    def test_default_factory(self):
        detection = SensitiveDataDetection.default()
        assert detection.is_sensitive is False
        assert detection.confidence == 0.0
        assert detection.detected_items == []
        assert detection.analysis_summary == "No analysis performed"

    def test_to_dict_with_items(self):
        item = SensitiveDataItem(
            data_type=SensitiveDataType.PERSONAL,
            description="Email address",
            snippet="user@example.com",
        )
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.8,
            detected_items=[item],
            analysis_summary="Personal data detected",
        )
        d = detection.to_dict()
        assert d["is_sensitive"] is True
        assert d["confidence"] == 0.8
        assert len(d["detected_items"]) == 1
        assert d["detected_items"][0]["data_type"] == "personal"

    def test_to_dict_empty_items(self):
        detection = SensitiveDataDetection.default()
        d = detection.to_dict()
        assert d["detected_items"] == []
