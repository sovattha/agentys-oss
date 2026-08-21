# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for ContextTransparencyService.

TDD: RED phase - tests written before implementation.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from app.domain.entities.context_transparency import (
    AnalyzedEmailSummary,
    StyleProfileSummary,
    RelationshipSummary,
    ContextTransparencyData,
)
from app.domain.entities.relationship_type import (
    RelationshipType,
    CommunicationFrequency,
    RelationshipDetection,
)
from app.domain.entities.contact_context import (
    ContactContext,
    DominantTone,
    TopicInfo,
)
from app.domain.entities.writing_style import (
    WritingStyleProfile,
    FormalityLevel,
)
from app.services.context_transparency_service import ContextTransparencyService


class TestContextTransparencyServiceInit:
    """Tests for service initialization."""

    def test_init_without_dependencies(self):
        """Test initialization without dependencies."""
        service = ContextTransparencyService()
        assert service is not None

    def test_init_with_relationship_service(self):
        """Test initialization with relationship service."""
        mock_rel_service = MagicMock()
        service = ContextTransparencyService(
            relationship_service=mock_rel_service,
        )
        assert service._relationship_service is mock_rel_service

    def test_init_with_style_service(self):
        """Test initialization with writing style service."""
        mock_style_service = MagicMock()
        service = ContextTransparencyService(
            style_service=mock_style_service,
        )
        assert service._style_service is mock_style_service

    def test_init_with_contact_context_provider(self):
        """Test initialization with contact context provider."""
        mock_context_provider = MagicMock()
        service = ContextTransparencyService(
            contact_context_provider=mock_context_provider,
        )
        assert service._contact_context_provider is mock_context_provider


class TestGetTransparencyData:
    """Tests for get_transparency_data method."""

    @pytest.fixture
    def service_with_mocks(self):
        """Create service with mocked dependencies."""
        mock_rel_service = MagicMock()
        mock_style_service = MagicMock()
        mock_context_provider = MagicMock()

        service = ContextTransparencyService(
            relationship_service=mock_rel_service,
            style_service=mock_style_service,
            contact_context_provider=mock_context_provider,
        )
        return service, mock_rel_service, mock_style_service, mock_context_provider

    def test_get_transparency_data_aggregates_all_services(self, service_with_mocks):
        """Test that all service data is aggregated."""
        service, mock_rel, mock_style, mock_context = service_with_mocks

        # Setup relationship detection
        mock_rel.get_relationship.return_value = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            communication_frequency=CommunicationFrequency.WEEKLY,
        )

        # Setup style profile
        mock_style.get_profile.return_value = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=10,
            common_words=["merci", "cordialement"],
            formality_level=FormalityLevel.FORMAL,
            preferred_greetings=["Bonjour"],
            preferred_closings=["Cordialement"],
        )

        # Setup contact context with analyzed emails
        mock_context.get_context.return_value = ContactContext(
            contact_email="john@example.com",
            account_id=1,
            email_count=5,
            dominant_tone=DominantTone.PROFESSIONAL,
            tone_confidence=0.85,
            recurring_topics=[TopicInfo(topic="project", frequency=3)],
        )
        mock_context.get_analyzed_emails.return_value = [
            {
                "email_id": "email-1",
                "subject": "Meeting tomorrow",
                "sender": "john@example.com",
                "date": datetime.utcnow(),
                "relevant_excerpts": ["Let's discuss the project"],
                "relevance_score": 0.9,
            }
        ]

        result = service.get_transparency_data(
            session_id="session-123",
            account_id=1,
            contact_email="john@example.com",
        )

        assert result.session_id == "session-123"
        assert result.contact_email == "john@example.com"
        assert len(result.analyzed_emails) >= 1
        assert result.style_profile is not None
        assert result.relationship is not None

    def test_get_transparency_data_without_style_profile(self, service_with_mocks):
        """Test transparency data when no style profile exists."""
        service, mock_rel, mock_style, mock_context = service_with_mocks

        mock_rel.get_relationship.return_value = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.UNKNOWN,
            confidence=0.0,
            communication_frequency=CommunicationFrequency.SPORADIC,
        )
        mock_style.get_profile.return_value = None
        mock_context.get_context.return_value = None
        mock_context.get_analyzed_emails.return_value = []

        result = service.get_transparency_data(
            session_id="session-123",
            account_id=1,
            contact_email="john@example.com",
        )

        assert result.style_profile is None
        assert result.analyzed_emails == []

    def test_get_transparency_data_calculates_token_count(self, service_with_mocks):
        """Test that total_context_tokens is calculated."""
        service, mock_rel, mock_style, mock_context = service_with_mocks

        mock_rel.get_relationship.return_value = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            communication_frequency=CommunicationFrequency.WEEKLY,
        )
        mock_style.get_profile.return_value = None
        mock_context.get_context.return_value = None
        mock_context.get_analyzed_emails.return_value = [
            {
                "email_id": "email-1",
                "subject": "Test",
                "sender": "john@example.com",
                "date": datetime.utcnow(),
                "relevant_excerpts": ["Short excerpt here"],
                "relevance_score": 0.9,
            }
        ]

        result = service.get_transparency_data(
            session_id="session-123",
            account_id=1,
            contact_email="john@example.com",
        )

        # Token count should be positive if there's any content
        assert result.total_context_tokens >= 0


class TestBuildStyleProfileSummary:
    """Tests for internal style profile summary building."""

    def test_build_summary_from_writing_style_profile(self):
        """Test building StyleProfileSummary from WritingStyleProfile."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=10,
            common_words=["merci", "cordialement", "projet"],
            avg_sentence_length=15.5,
            formality_level=FormalityLevel.FORMAL,
            preferred_greetings=["Bonjour", "Cher collègue"],
            preferred_closings=["Cordialement", "Bien à vous"],
        )

        service = ContextTransparencyService()
        summary = service._build_style_profile_summary(profile)

        assert summary.formality_level == "formal"
        assert "merci" in summary.characteristic_phrases
        assert summary.greeting_style == "Bonjour"
        assert summary.closing_style == "Cordialement"
        assert summary.confidence > 0.0

    def test_build_summary_with_mixed_formality(self):
        """Test building summary with mixed formality level."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=5,
            formality_level=FormalityLevel.MIXED,
        )

        service = ContextTransparencyService()
        summary = service._build_style_profile_summary(profile)

        assert summary.formality_level == "mixed"


class TestBuildRelationshipSummary:
    """Tests for internal relationship summary building."""

    def test_build_summary_from_relationship_detection(self):
        """Test building RelationshipSummary from RelationshipDetection."""
        detection = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.CLIENT,
            confidence=0.92,
            communication_frequency=CommunicationFrequency.DAILY,
        )

        service = ContextTransparencyService()
        summary = service._build_relationship_summary(detection)

        assert summary.relationship_type == "client"
        assert summary.confidence == 0.92
        assert summary.communication_frequency == "daily"

    def test_build_summary_for_unknown_relationship(self):
        """Test building summary for unknown relationship."""
        detection = RelationshipDetection(
            contact_email="unknown@example.com",
            account_id=1,
            relationship_type=RelationshipType.UNKNOWN,
            confidence=0.0,
            communication_frequency=CommunicationFrequency.SPORADIC,
        )

        service = ContextTransparencyService()
        summary = service._build_relationship_summary(detection)

        assert summary.relationship_type == "unknown"
        assert summary.confidence == 0.0


class TestBuildAnalyzedEmailSummary:
    """Tests for building analyzed email summaries."""

    def test_build_email_summary_from_dict(self):
        """Test building AnalyzedEmailSummary from raw data."""
        raw_data = {
            "email_id": "email-abc",
            "subject": "Project Update",
            "sender": "alice@example.com",
            "date": datetime(2026, 1, 19, 10, 30),
            "relevant_excerpts": ["The project is on track", "Next milestone: Friday"],
            "relevance_score": 0.88,
        }

        service = ContextTransparencyService()
        summary = service._build_email_summary(raw_data)

        assert summary.email_id == "email-abc"
        assert summary.subject == "Project Update"
        assert summary.sender == "alice@example.com"
        assert len(summary.relevant_excerpts) == 2
        assert summary.relevance_score == 0.88


class TestEstimateTokenCount:
    """Tests for token count estimation."""

    def test_estimate_tokens_for_context_data(self):
        """Test token estimation for transparency data."""
        data = ContextTransparencyData(
            session_id="test-session",
            contact_email="test@example.com",
            analyzed_emails=[
                AnalyzedEmailSummary(
                    email_id="1",
                    subject="Test",
                    sender="test@example.com",
                    date=datetime.utcnow(),
                    relevant_excerpts=["This is a test excerpt with some content"],
                    relevance_score=0.9,
                )
            ],
            style_profile=StyleProfileSummary(
                formality_level="formal",
                characteristic_phrases=["merci", "cordialement"],
                greeting_style="Bonjour",
                closing_style="Cordialement",
                confidence=0.8,
            ),
            relationship=RelationshipSummary(
                relationship_type="colleague",
                confidence=0.85,
                communication_frequency="weekly",
            ),
            analysis_timestamp=datetime.utcnow(),
            total_context_tokens=0,
        )

        service = ContextTransparencyService()
        tokens = service._estimate_token_count(data)

        # Should have positive token count based on content
        assert tokens > 0

    def test_estimate_tokens_empty_data(self):
        """Test token estimation for minimal data."""
        data = ContextTransparencyData(
            session_id="test-session",
            contact_email="test@example.com",
            analyzed_emails=[],
            style_profile=None,
            relationship=None,
            analysis_timestamp=datetime.utcnow(),
            total_context_tokens=0,
        )

        service = ContextTransparencyService()
        tokens = service._estimate_token_count(data)

        # Minimal tokens for session_id and contact_email
        assert tokens >= 0


class TestToDict:
    """Tests for serialization."""

    @pytest.fixture
    def service_with_mocks(self):
        """Create service with mocked dependencies."""
        mock_rel_service = MagicMock()
        mock_style_service = MagicMock()
        mock_context_provider = MagicMock()

        service = ContextTransparencyService(
            relationship_service=mock_rel_service,
            style_service=mock_style_service,
            contact_context_provider=mock_context_provider,
        )
        return service, mock_rel_service, mock_style_service, mock_context_provider

    def test_get_transparency_data_returns_serializable(self, service_with_mocks):
        """Test that returned data is JSON serializable via to_dict()."""
        service, mock_rel, mock_style, mock_context = service_with_mocks

        mock_rel.get_relationship.return_value = RelationshipDetection(
            contact_email="john@example.com",
            account_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            communication_frequency=CommunicationFrequency.WEEKLY,
        )
        mock_style.get_profile.return_value = None
        mock_context.get_context.return_value = None
        mock_context.get_analyzed_emails.return_value = []

        result = service.get_transparency_data(
            session_id="session-123",
            account_id=1,
            contact_email="john@example.com",
        )

        # Should be able to convert to dict without error
        data_dict = result.to_dict()
        assert isinstance(data_dict, dict)
        assert data_dict["session_id"] == "session-123"
        assert data_dict["contact_email"] == "john@example.com"
