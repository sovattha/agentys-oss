# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour les entités sensitive_data."""

import pytest
from app.domain.entities.sensitive_data import (
    SensitiveDataType,
    SensitiveDataItem,
    SensitiveDataDetection,
)
from app.domain.exceptions import InvalidBoundsError


class TestSensitiveDataType:
    """Tests pour l'enum SensitiveDataType."""

    def test_financial_value(self):
        assert SensitiveDataType.FINANCIAL.value == "financial"

    def test_personal_value(self):
        assert SensitiveDataType.PERSONAL.value == "personal"

    def test_commercial_secret_value(self):
        assert SensitiveDataType.COMMERCIAL_SECRET.value == "commercial"

    def test_credential_value(self):
        assert SensitiveDataType.CREDENTIAL.value == "credential"

    def test_all_types_count(self):
        assert len(SensitiveDataType) == 4


class TestSensitiveDataItem:
    """Tests pour SensitiveDataItem."""

    def test_create_item(self):
        item = SensitiveDataItem(
            data_type=SensitiveDataType.FINANCIAL,
            description="Credit card number",
            snippet="4111-XXXX-XXXX-1234",
        )
        assert item.data_type == SensitiveDataType.FINANCIAL
        assert item.description == "Credit card number"

    def test_to_dict(self):
        item = SensitiveDataItem(
            data_type=SensitiveDataType.CREDENTIAL,
            description="API key",
            snippet="sk-1234...",
        )
        d = item.to_dict()
        assert d == {
            "data_type": "credential",
            "description": "API key",
            "snippet": "sk-1234...",
        }

    def test_to_dict_personal_type(self):
        item = SensitiveDataItem(
            data_type=SensitiveDataType.PERSONAL,
            description="SSN",
            snippet="123-XX-XXXX",
        )
        assert item.to_dict()["data_type"] == "personal"


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

    def test_confidence_zero_valid(self):
        detection = SensitiveDataDetection(
            is_sensitive=False, confidence=0.0, detected_items=[], analysis_summary=""
        )
        assert detection.confidence == 0.0

    def test_confidence_one_valid(self):
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
            data_type=SensitiveDataType.FINANCIAL,
            description="IBAN",
            snippet="FR76...",
        )
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.8,
            detected_items=[item],
            analysis_summary="Found IBAN",
        )
        d = detection.to_dict()
        assert d["is_sensitive"] is True
        assert d["confidence"] == 0.8
        assert len(d["detected_items"]) == 1
        assert d["detected_items"][0]["data_type"] == "financial"

    def test_to_dict_empty_items(self):
        detection = SensitiveDataDetection.default()
        d = detection.to_dict()
        assert d["detected_items"] == []

    def test_multiple_items(self):
        items = [
            SensitiveDataItem(SensitiveDataType.FINANCIAL, "Card", "4111..."),
            SensitiveDataItem(SensitiveDataType.PERSONAL, "Phone", "+33..."),
            SensitiveDataItem(SensitiveDataType.CREDENTIAL, "Password", "pass..."),
        ]
        detection = SensitiveDataDetection(
            is_sensitive=True, confidence=0.99, detected_items=items, analysis_summary="Multiple"
        )
        assert len(detection.detected_items) == 3
        d = detection.to_dict()
        assert len(d["detected_items"]) == 3
