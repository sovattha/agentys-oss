# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for RelationshipDetectionService.
"""

import pytest
from unittest.mock import MagicMock

from app.domain.entities.relationship_type import (
    RelationshipType,
    CommunicationFrequency,
    RelationshipDetection,
)
from app.services.relationship_detection_service import RelationshipDetectionService


class TestRelationshipDetectionServiceInit:
    """Tests for service initialization."""

    def test_init_with_default_params(self):
        """Test initialization with default parameters."""
        service = RelationshipDetectionService()
        assert service is not None

    def test_init_with_custom_repository(self):
        """Test initialization with custom repository."""
        mock_repo = MagicMock()
        service = RelationshipDetectionService(repository=mock_repo)
        assert service._repository is mock_repo

    def test_init_with_custom_detector(self):
        """Test initialization with custom detector adapter."""
        mock_detector = MagicMock()
        service = RelationshipDetectionService(detector=mock_detector)
        assert service._detector is mock_detector


class TestGetRelationship:
    """Tests for get_relationship method."""

    @pytest.fixture
    def service_with_mocks(self):
        """Create service with mocked dependencies."""
        mock_repo = MagicMock()
        mock_detector = MagicMock()
        service = RelationshipDetectionService(
            repository=mock_repo,
            detector=mock_detector,
        )
        return service, mock_repo, mock_detector

    def test_get_relationship_returns_override_when_exists(self, service_with_mocks):
        """Test that user override takes precedence."""
        service, mock_repo, mock_detector = service_with_mocks

        # Setup override
        override = MagicMock()
        override.relationship_type = RelationshipType.CLIENT.value
        mock_repo.get_override.return_value = override

        result = service.get_relationship(
            account_id=1,
            contact_email="john@example.com",
        )

        assert result.relationship_type == RelationshipType.CLIENT
        assert result.is_user_override is True
        mock_repo.get_override.assert_called_once_with(1, "john@example.com")
        mock_detector.detect.assert_not_called()

    def test_get_relationship_detects_when_no_override(self, service_with_mocks):
        """Test detection when no override exists."""
        service, mock_repo, mock_detector = service_with_mocks

        mock_repo.get_override.return_value = None
        mock_detector.detect.return_value = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            communication_frequency=CommunicationFrequency.WEEKLY,
        )

        result = service.get_relationship(
            account_id=1,
            contact_email="john@example.com",
        )

        assert result.relationship_type == RelationshipType.COLLEAGUE
        assert result.is_user_override is False
        assert result.confidence == 0.85

    def test_get_relationship_returns_unknown_on_detection_failure(self, service_with_mocks):
        """Test returns UNKNOWN when detection fails."""
        service, mock_repo, mock_detector = service_with_mocks

        mock_repo.get_override.return_value = None
        mock_detector.detect.return_value = None

        result = service.get_relationship(
            account_id=1,
            contact_email="john@example.com",
        )

        assert result.relationship_type == RelationshipType.UNKNOWN
        assert result.confidence == 0.0


class TestSetRelationshipOverride:
    """Tests for set_relationship_override method."""

    @pytest.fixture
    def service_with_mocks(self):
        """Create service with mocked dependencies."""
        mock_repo = MagicMock()
        service = RelationshipDetectionService(repository=mock_repo)
        return service, mock_repo

    def test_set_override_saves_to_repository(self, service_with_mocks):
        """Test that override is saved to repository."""
        service, mock_repo = service_with_mocks

        saved_override = MagicMock()
        saved_override.relationship_type = RelationshipType.CLIENT.value
        mock_repo.save_override.return_value = saved_override

        result = service.set_relationship_override(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.CLIENT,
        )

        assert result.relationship_type == RelationshipType.CLIENT
        mock_repo.save_override.assert_called_once_with(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.CLIENT.value,
        )

    def test_set_override_with_string_type(self, service_with_mocks):
        """Test that string relationship type is converted to enum."""
        service, mock_repo = service_with_mocks

        saved_override = MagicMock()
        saved_override.relationship_type = "friend"
        mock_repo.save_override.return_value = saved_override

        result = service.set_relationship_override(
            account_id=1,
            contact_email="john@example.com",
            relationship_type="friend",
        )

        assert result.relationship_type == RelationshipType.FRIEND


class TestDeleteRelationshipOverride:
    """Tests for delete_relationship_override method."""

    def test_delete_override_returns_true_when_deleted(self):
        """Test successful deletion returns True."""
        mock_repo = MagicMock()
        mock_repo.delete_override.return_value = True
        service = RelationshipDetectionService(repository=mock_repo)

        result = service.delete_relationship_override(
            account_id=1,
            contact_email="john@example.com",
        )

        assert result is True
        mock_repo.delete_override.assert_called_once_with(1, "john@example.com")

    def test_delete_override_returns_false_when_not_found(self):
        """Test deletion returns False when override doesn't exist."""
        mock_repo = MagicMock()
        mock_repo.delete_override.return_value = False
        service = RelationshipDetectionService(repository=mock_repo)

        result = service.delete_relationship_override(
            account_id=1,
            contact_email="nonexistent@example.com",
        )

        assert result is False


class TestGetAllOverrides:
    """Tests for get_all_overrides method."""

    def test_get_all_overrides_for_account(self):
        """Test retrieving all overrides for an account."""
        mock_repo = MagicMock()
        mock_override1 = MagicMock()
        mock_override1.contact_email = "john@example.com"
        mock_override1.relationship_type = "client"
        mock_override2 = MagicMock()
        mock_override2.contact_email = "jane@example.com"
        mock_override2.relationship_type = "colleague"
        mock_repo.get_overrides_for_account.return_value = [mock_override1, mock_override2]

        service = RelationshipDetectionService(repository=mock_repo)
        results = service.get_all_overrides(account_id=1)

        assert len(results) == 2
        mock_repo.get_overrides_for_account.assert_called_once_with(1)

    def test_get_all_overrides_empty_list(self):
        """Test returns empty list when no overrides."""
        mock_repo = MagicMock()
        mock_repo.get_overrides_for_account.return_value = []

        service = RelationshipDetectionService(repository=mock_repo)
        results = service.get_all_overrides(account_id=1)

        assert results == []


class TestBatchGetRelationships:
    """Tests for batch_get_relationships method."""

    def test_batch_get_relationships(self):
        """Test getting relationships for multiple contacts."""
        mock_repo = MagicMock()
        mock_detector = MagicMock()

        # Setup override for john
        override_john = MagicMock()
        override_john.relationship_type = "client"

        def get_override_side_effect(account_id, contact_email):
            if contact_email == "john@example.com":
                return override_john
            return None

        mock_repo.get_override.side_effect = get_override_side_effect

        # Setup detection for jane
        mock_detector.detect.return_value = RelationshipDetection(
            contact_email="jane@example.com",
            account_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.9,
            communication_frequency=CommunicationFrequency.DAILY,
        )

        service = RelationshipDetectionService(
            repository=mock_repo,
            detector=mock_detector,
        )

        results = service.batch_get_relationships(
            account_id=1,
            contact_emails=["john@example.com", "jane@example.com"],
        )

        assert len(results) == 2
        assert results["john@example.com"].relationship_type == RelationshipType.CLIENT
        assert results["john@example.com"].is_user_override is True
        assert results["jane@example.com"].relationship_type == RelationshipType.COLLEAGUE
        assert results["jane@example.com"].is_user_override is False
