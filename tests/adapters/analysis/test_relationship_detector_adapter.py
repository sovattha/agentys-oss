# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for RelationshipDetectorAdapter.
"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.domain.entities.relationship_type import (
    RelationshipType,
    CommunicationFrequency,
)


class TestRelationshipDetectorAdapterInit:
    """Tests for adapter initialization."""

    def test_init_with_llm(self):
        """Test initialization with LLM port."""
        from app.adapters.analysis.relationship_detector_adapter import (
            RelationshipDetectorAdapter,
        )

        mock_llm = MagicMock()
        adapter = RelationshipDetectorAdapter(llm=mock_llm)
        assert adapter._llm is mock_llm

    def test_is_available_returns_llm_status(self):
        """Test is_available delegates to LLM."""
        from app.adapters.analysis.relationship_detector_adapter import (
            RelationshipDetectorAdapter,
        )

        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        adapter = RelationshipDetectorAdapter(llm=mock_llm)

        assert adapter.is_available() is True
        mock_llm.is_available.assert_called_once()


class TestRelationshipDetectorAdapterDetect:
    """Tests for detect method."""

    @pytest.fixture
    def adapter_with_mock_llm(self):
        """Create adapter with mocked LLM."""
        from app.adapters.analysis.relationship_detector_adapter import (
            RelationshipDetectorAdapter,
        )

        mock_llm = MagicMock()
        adapter = RelationshipDetectorAdapter(llm=mock_llm)
        return adapter, mock_llm

    def test_detect_colleague_relationship(self, adapter_with_mock_llm):
        """Test detecting a colleague relationship."""
        adapter, mock_llm = adapter_with_mock_llm

        # Mock LLM response
        llm_response = MagicMock()
        llm_response.content = json.dumps(
            {
                "relationship_type": "colleague",
                "confidence": 0.85,
                "communication_frequency": "daily",
                "typical_hours": [9, 10, 11, 14, 15, 16],
                "reasoning": "Work-related discussions, formal tone",
            }
        )
        mock_llm.complete.return_value = llm_response

        # Mock email data
        mock_emails = [
            MagicMock(
                sender="colleague@company.com",
                subject="Re: Sprint Planning",
                date=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
            )
        ]

        result = adapter.detect(
            account_id=1,
            contact_email="colleague@company.com",
            emails=mock_emails,
        )

        assert result is not None
        assert result.relationship_type == RelationshipType.COLLEAGUE
        assert result.confidence == 0.85
        assert result.communication_frequency == CommunicationFrequency.DAILY
        assert 10 in result.typical_hours

    def test_detect_client_relationship(self, adapter_with_mock_llm):
        """Test detecting a client relationship."""
        adapter, mock_llm = adapter_with_mock_llm

        llm_response = MagicMock()
        llm_response.content = json.dumps(
            {
                "relationship_type": "client",
                "confidence": 0.92,
                "communication_frequency": "weekly",
                "typical_hours": [9, 10, 11],
                "reasoning": "Business inquiries, professional tone",
            }
        )
        mock_llm.complete.return_value = llm_response

        mock_emails = [MagicMock()]

        result = adapter.detect(
            account_id=1,
            contact_email="client@acme.com",
            emails=mock_emails,
        )

        assert result.relationship_type == RelationshipType.CLIENT
        assert result.confidence == 0.92
        assert result.communication_frequency == CommunicationFrequency.WEEKLY

    def test_detect_friend_relationship(self, adapter_with_mock_llm):
        """Test detecting a friend relationship."""
        adapter, mock_llm = adapter_with_mock_llm

        llm_response = MagicMock()
        llm_response.content = json.dumps(
            {
                "relationship_type": "friend",
                "confidence": 0.78,
                "communication_frequency": "sporadic",
                "typical_hours": [19, 20, 21],
                "reasoning": "Personal topics, casual language",
            }
        )
        mock_llm.complete.return_value = llm_response

        mock_emails = [MagicMock()]

        result = adapter.detect(
            account_id=1,
            contact_email="friend@personal.com",
            emails=mock_emails,
        )

        assert result.relationship_type == RelationshipType.FRIEND
        assert result.communication_frequency == CommunicationFrequency.SPORADIC

    def test_detect_returns_none_on_empty_emails(self, adapter_with_mock_llm):
        """Test that detect returns None when no emails provided."""
        adapter, mock_llm = adapter_with_mock_llm

        result = adapter.detect(
            account_id=1,
            contact_email="unknown@example.com",
            emails=[],
        )

        assert result is None
        mock_llm.complete.assert_not_called()

    def test_detect_returns_unknown_on_llm_failure(self, adapter_with_mock_llm):
        """Test returns UNKNOWN when LLM fails."""
        adapter, mock_llm = adapter_with_mock_llm

        mock_llm.complete.return_value = None

        mock_emails = [MagicMock()]

        result = adapter.detect(
            account_id=1,
            contact_email="unknown@example.com",
            emails=mock_emails,
        )

        assert result is not None
        assert result.relationship_type == RelationshipType.UNKNOWN
        assert result.confidence == 0.0

    def test_detect_handles_json_parse_error(self, adapter_with_mock_llm):
        """Test handles invalid JSON response."""
        adapter, mock_llm = adapter_with_mock_llm

        llm_response = MagicMock()
        llm_response.content = "Not valid JSON"
        mock_llm.complete.return_value = llm_response

        mock_emails = [MagicMock()]

        result = adapter.detect(
            account_id=1,
            contact_email="unknown@example.com",
            emails=mock_emails,
        )

        assert result.relationship_type == RelationshipType.UNKNOWN
        assert result.confidence == 0.0

    def test_detect_handles_markdown_wrapped_json(self, adapter_with_mock_llm):
        """Test handles JSON wrapped in markdown code blocks."""
        adapter, mock_llm = adapter_with_mock_llm

        llm_response = MagicMock()
        llm_response.content = """```json
{
    "relationship_type": "manager",
    "confidence": 0.88,
    "communication_frequency": "daily",
    "typical_hours": [9, 10, 11, 14, 15],
    "reasoning": "Direct reports, task assignments"
}
```"""
        mock_llm.complete.return_value = llm_response

        mock_emails = [MagicMock()]

        result = adapter.detect(
            account_id=1,
            contact_email="boss@company.com",
            emails=mock_emails,
        )

        assert result.relationship_type == RelationshipType.MANAGER
        assert result.confidence == 0.88


class TestRelationshipDetectorPromptBuilding:
    """Tests for prompt building."""

    def test_build_user_prompt_includes_email_content(self):
        """Test that user prompt includes email data."""
        from app.adapters.analysis.relationship_detector_adapter import (
            RelationshipDetectorAdapter,
        )

        mock_llm = MagicMock()
        adapter = RelationshipDetectorAdapter(llm=mock_llm)

        mock_emails = [
            MagicMock(
                sender="john@example.com",
                subject="Project Update",
                date=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
                body_text="Hi team, here's the weekly update...",
                snippet="Hi team, here's the weekly update...",
            )
        ]

        prompt = adapter._build_user_prompt(
            contact_email="john@example.com",
            emails=mock_emails,
        )

        assert "john@example.com" in prompt
        assert "Project Update" in prompt

    def test_build_user_prompt_limits_email_body(self):
        """Test that email body is truncated for long content."""
        from app.adapters.analysis.relationship_detector_adapter import (
            RelationshipDetectorAdapter,
        )

        mock_llm = MagicMock()
        adapter = RelationshipDetectorAdapter(llm=mock_llm)

        long_body = "A" * 1000
        mock_emails = [
            MagicMock(
                sender="john@example.com",
                subject="Long Email",
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                body_text=long_body,
                snippet=long_body[:100],
            )
        ]

        prompt = adapter._build_user_prompt(
            contact_email="john@example.com",
            emails=mock_emails,
        )

        # Body should be truncated
        assert "A" * 500 in prompt
        assert "A" * 1000 not in prompt
