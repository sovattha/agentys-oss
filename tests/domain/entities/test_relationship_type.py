# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for RelationshipType and RelationshipDetection entities.
"""

import pytest
from datetime import datetime
from app.domain.entities.relationship_type import (
    RelationshipType,
    CommunicationFrequency,
    RelationshipDetection,
)


class TestRelationshipType:
    """Tests for RelationshipType enum."""

    def test_relationship_type_values(self):
        """Test all expected relationship types exist."""
        assert RelationshipType.COLLEAGUE.value == "colleague"
        assert RelationshipType.CLIENT.value == "client"
        assert RelationshipType.FRIEND.value == "friend"
        assert RelationshipType.MANAGER.value == "manager"
        assert RelationshipType.VENDOR.value == "vendor"
        assert RelationshipType.UNKNOWN.value == "unknown"

    def test_relationship_type_from_string(self):
        """Test creating RelationshipType from string."""
        assert RelationshipType("colleague") == RelationshipType.COLLEAGUE
        assert RelationshipType("client") == RelationshipType.CLIENT

    def test_invalid_relationship_type_raises(self):
        """Test invalid relationship type raises ValueError."""
        with pytest.raises(ValueError):
            RelationshipType("invalid_type")


class TestCommunicationFrequency:
    """Tests for CommunicationFrequency enum."""

    def test_communication_frequency_values(self):
        """Test all expected frequency values exist."""
        assert CommunicationFrequency.DAILY.value == "daily"
        assert CommunicationFrequency.WEEKLY.value == "weekly"
        assert CommunicationFrequency.MONTHLY.value == "monthly"
        assert CommunicationFrequency.SPORADIC.value == "sporadic"


class TestRelationshipDetection:
    """Tests for RelationshipDetection dataclass."""

    def test_create_valid_relationship_detection(self):
        """Test creating a valid RelationshipDetection."""
        detection = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            communication_frequency=CommunicationFrequency.WEEKLY,
            typical_hours=[9, 10, 14, 15],
            is_user_override=False,
        )
        assert detection.contact_email == "john@example.com"
        assert detection.account_id == 1
        assert detection.relationship_type == RelationshipType.COLLEAGUE
        assert detection.confidence == 0.85
        assert detection.communication_frequency == CommunicationFrequency.WEEKLY
        assert detection.typical_hours == [9, 10, 14, 15]
        assert detection.is_user_override is False
        assert isinstance(detection.detected_at, datetime)

    def test_relationship_detection_empty_email_raises(self):
        """Test empty email raises ValueError."""
        with pytest.raises(ValueError, match="contact_email cannot be empty"):
            RelationshipDetection(
                contact_email="",
                account_id=1,
                relationship_type=RelationshipType.COLLEAGUE,
                confidence=0.85,
                communication_frequency=CommunicationFrequency.WEEKLY,
            )

    def test_relationship_detection_invalid_email_raises(self):
        """Test invalid email raises ValueError."""
        with pytest.raises(ValueError, match="valid email"):
            RelationshipDetection(
                contact_email="not-an-email",
                account_id=1,
                relationship_type=RelationshipType.COLLEAGUE,
                confidence=0.85,
                communication_frequency=CommunicationFrequency.WEEKLY,
            )

    def test_relationship_detection_invalid_confidence_raises(self):
        """Test confidence outside 0-1 raises ValueError."""
        with pytest.raises(ValueError, match="confidence must be between"):
            RelationshipDetection(
                contact_email="john@example.com",
                account_id=1,
                relationship_type=RelationshipType.COLLEAGUE,
                confidence=1.5,
                communication_frequency=CommunicationFrequency.WEEKLY,
            )

    def test_relationship_detection_negative_confidence_raises(self):
        """Test negative confidence raises ValueError."""
        with pytest.raises(ValueError, match="confidence must be between"):
            RelationshipDetection(
                contact_email="john@example.com",
                account_id=1,
                relationship_type=RelationshipType.COLLEAGUE,
                confidence=-0.1,
                communication_frequency=CommunicationFrequency.WEEKLY,
            )

    def test_relationship_detection_string_relationship_type(self):
        """Test that string relationship type is converted to enum."""
        detection = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type="client",
            confidence=0.85,
            communication_frequency=CommunicationFrequency.WEEKLY,
        )
        assert detection.relationship_type == RelationshipType.CLIENT

    def test_relationship_detection_string_frequency(self):
        """Test that string frequency is converted to enum."""
        detection = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            communication_frequency="daily",
        )
        assert detection.communication_frequency == CommunicationFrequency.DAILY

    def test_relationship_detection_to_dict(self):
        """Test to_dict serialization."""
        detection = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            communication_frequency=CommunicationFrequency.WEEKLY,
            typical_hours=[9, 14],
            is_user_override=True,
        )
        result = detection.to_dict()

        assert result["contact_email"] == "john@example.com"
        assert result["account_id"] == 1
        assert result["relationship_type"] == "colleague"
        assert result["confidence"] == 0.85
        assert result["communication_frequency"] == "weekly"
        assert result["typical_hours"] == [9, 14]
        assert result["is_user_override"] is True
        assert "detected_at" in result

    def test_relationship_detection_default_typical_hours(self):
        """Test default empty typical_hours list."""
        detection = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            communication_frequency=CommunicationFrequency.WEEKLY,
        )
        assert detection.typical_hours == []

    def test_relationship_detection_user_override_flag(self):
        """Test is_user_override flag."""
        detection_auto = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            communication_frequency=CommunicationFrequency.WEEKLY,
            is_user_override=False,
        )
        detection_manual = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.CLIENT,
            confidence=1.0,
            communication_frequency=CommunicationFrequency.WEEKLY,
            is_user_override=True,
        )
        assert detection_auto.is_user_override is False
        assert detection_manual.is_user_override is True
        assert detection_manual.confidence == 1.0

    def test_relationship_detection_invalid_hours_raises(self):
        """Test typical_hours outside 0-23 raises ValueError."""
        with pytest.raises(ValueError, match="typical_hours.*0-23"):
            RelationshipDetection(
                contact_email="john@example.com",
                account_id=1,
                relationship_type=RelationshipType.COLLEAGUE,
                confidence=0.85,
                communication_frequency=CommunicationFrequency.WEEKLY,
                typical_hours=[25, 10],
            )
