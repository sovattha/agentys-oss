# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'entité ContactContext et ses composants.

Couvre:
- DominantTone enum
- TopicInfo création, validation, sérialisation
- ContactContext création, validation, sérialisation
- ContactContext.create_incomplete()
"""

from datetime import datetime
import pytest
from app.domain.entities.contact_context import (
    ContactContext,
    DominantTone,
    TopicInfo,
)


# ============================================================================
# DominantTone Tests
# ============================================================================

class TestDominantToneEnum:
    """Tests pour l'énumération DominantTone."""

    def test_formal_value(self):
        assert DominantTone.FORMAL.value == "formal"

    def test_friendly_value(self):
        assert DominantTone.FRIENDLY.value == "friendly"

    def test_professional_value(self):
        assert DominantTone.PROFESSIONAL.value == "professional"

    def test_casual_value(self):
        assert DominantTone.CASUAL.value == "casual"

    def test_has_four_values(self):
        assert len(DominantTone) == 4

    def test_creation_from_string(self):
        assert DominantTone("formal") == DominantTone.FORMAL

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            DominantTone("unknown")

    def test_is_str_subclass(self):
        """DominantTone hérite de str, donc on peut l'utiliser comme chaîne."""
        assert isinstance(DominantTone.FORMAL, str)
        assert DominantTone.FORMAL == "formal"


# ============================================================================
# TopicInfo Tests
# ============================================================================

class TestTopicInfoCreation:
    """Tests pour la création de TopicInfo."""

    def test_create_minimal(self):
        topic = TopicInfo(topic="Budget Q2", frequency=5)
        assert topic.topic == "Budget Q2"
        assert topic.frequency == 5
        assert topic.last_mentioned is None

    def test_create_with_last_mentioned(self):
        dt = datetime(2026, 3, 20, 10, 0, 0)
        topic = TopicInfo(topic="Projet Alpha", frequency=3, last_mentioned=dt)
        assert topic.last_mentioned == dt

    def test_empty_topic_raises(self):
        with pytest.raises(ValueError, match="topic cannot be empty"):
            TopicInfo(topic="", frequency=1)

    def test_whitespace_only_topic_raises(self):
        with pytest.raises(ValueError, match="topic cannot be empty"):
            TopicInfo(topic="   ", frequency=1)

    def test_negative_frequency_raises(self):
        with pytest.raises(ValueError, match="frequency must be non-negative"):
            TopicInfo(topic="Test", frequency=-1)

    def test_zero_frequency_is_valid(self):
        topic = TopicInfo(topic="Test", frequency=0)
        assert topic.frequency == 0


class TestTopicInfoToDict:
    """Tests pour TopicInfo.to_dict()."""

    def test_to_dict_minimal(self):
        topic = TopicInfo(topic="Budget", frequency=3)
        data = topic.to_dict()
        assert data["topic"] == "Budget"
        assert data["frequency"] == 3
        assert data["last_mentioned"] is None

    def test_to_dict_with_last_mentioned(self):
        dt = datetime(2026, 3, 20, 10, 0, 0)
        topic = TopicInfo(topic="Budget", frequency=3, last_mentioned=dt)
        data = topic.to_dict()
        assert data["last_mentioned"] == "2026-03-20T10:00:00"


# ============================================================================
# ContactContext Tests
# ============================================================================

class TestContactContextCreation:
    """Tests pour la création de ContactContext."""

    def test_create_minimal(self):
        ctx = ContactContext(
            contact_email="alice@example.com",
            account_id=1,
            email_count=10,
            dominant_tone=DominantTone.PROFESSIONAL,
            tone_confidence=0.85,
        )
        assert ctx.contact_email == "alice@example.com"
        assert ctx.account_id == 1
        assert ctx.email_count == 10
        assert ctx.dominant_tone == DominantTone.PROFESSIONAL
        assert ctx.tone_confidence == 0.85
        assert ctx.recurring_topics == []
        assert ctx.relationship_strength == 0
        assert ctx.is_complete is True

    def test_create_with_all_fields(self):
        first = datetime(2025, 1, 1)
        last = datetime(2026, 3, 20)
        topics = [TopicInfo(topic="Budget", frequency=5)]
        ctx = ContactContext(
            contact_email="bob@example.com",
            account_id=2,
            email_count=50,
            dominant_tone=DominantTone.FRIENDLY,
            tone_confidence=0.92,
            recurring_topics=topics,
            relationship_strength=75,
            first_interaction=first,
            last_interaction=last,
            analysis_duration_ms=1500,
        )
        assert ctx.relationship_strength == 75
        assert ctx.first_interaction == first
        assert ctx.last_interaction == last
        assert ctx.analysis_duration_ms == 1500
        assert len(ctx.recurring_topics) == 1

    def test_tone_string_auto_converted_to_enum(self):
        """Test que dominant_tone accepte une chaîne et la convertit."""
        ctx = ContactContext(
            contact_email="test@example.com",
            account_id=1,
            email_count=5,
            dominant_tone="casual",
            tone_confidence=0.5,
        )
        assert ctx.dominant_tone == DominantTone.CASUAL


class TestContactContextValidation:
    """Tests pour la validation de ContactContext."""

    def test_empty_email_raises(self):
        with pytest.raises(ValueError, match="contact_email cannot be empty"):
            ContactContext(
                contact_email="",
                account_id=1,
                email_count=0,
                dominant_tone=DominantTone.FORMAL,
                tone_confidence=0.5,
            )

    def test_invalid_email_raises(self):
        with pytest.raises(ValueError, match="contact_email must be a valid email"):
            ContactContext(
                contact_email="not-an-email",
                account_id=1,
                email_count=0,
                dominant_tone=DominantTone.FORMAL,
                tone_confidence=0.5,
            )

    def test_negative_email_count_raises(self):
        with pytest.raises(ValueError, match="email_count must be non-negative"):
            ContactContext(
                contact_email="a@b.com",
                account_id=1,
                email_count=-1,
                dominant_tone=DominantTone.FORMAL,
                tone_confidence=0.5,
            )

    def test_tone_confidence_above_1_raises(self):
        with pytest.raises(ValueError, match="tone_confidence must be between"):
            ContactContext(
                contact_email="a@b.com",
                account_id=1,
                email_count=0,
                dominant_tone=DominantTone.FORMAL,
                tone_confidence=1.5,
            )

    def test_tone_confidence_below_0_raises(self):
        with pytest.raises(ValueError, match="tone_confidence must be between"):
            ContactContext(
                contact_email="a@b.com",
                account_id=1,
                email_count=0,
                dominant_tone=DominantTone.FORMAL,
                tone_confidence=-0.1,
            )

    def test_relationship_strength_above_100_raises(self):
        with pytest.raises(ValueError, match="relationship_strength must be between"):
            ContactContext(
                contact_email="a@b.com",
                account_id=1,
                email_count=0,
                dominant_tone=DominantTone.FORMAL,
                tone_confidence=0.5,
                relationship_strength=101,
            )

    def test_negative_analysis_duration_raises(self):
        with pytest.raises(ValueError, match="analysis_duration_ms must be non-negative"):
            ContactContext(
                contact_email="a@b.com",
                account_id=1,
                email_count=0,
                dominant_tone=DominantTone.FORMAL,
                tone_confidence=0.5,
                analysis_duration_ms=-100,
            )


class TestContactContextToDict:
    """Tests pour ContactContext.to_dict()."""

    def test_to_dict_basic(self):
        ctx = ContactContext(
            contact_email="test@example.com",
            account_id=1,
            email_count=10,
            dominant_tone=DominantTone.PROFESSIONAL,
            tone_confidence=0.85,
        )
        data = ctx.to_dict()
        assert data["contact_email"] == "test@example.com"
        assert data["account_id"] == 1
        assert data["email_count"] == 10
        assert data["dominant_tone"] == "professional"
        assert data["tone_confidence"] == 0.85
        assert data["recurring_topics"] == []
        assert data["is_complete"] is True

    def test_to_dict_with_topics(self):
        topics = [
            TopicInfo(topic="Budget", frequency=5),
            TopicInfo(topic="Projet Alpha", frequency=3),
        ]
        ctx = ContactContext(
            contact_email="test@example.com",
            account_id=1,
            email_count=10,
            dominant_tone=DominantTone.FRIENDLY,
            tone_confidence=0.9,
            recurring_topics=topics,
        )
        data = ctx.to_dict()
        assert len(data["recurring_topics"]) == 2
        assert data["recurring_topics"][0]["topic"] == "Budget"


class TestContactContextCreateIncomplete:
    """Tests pour ContactContext.create_incomplete()."""

    def test_create_incomplete_basic(self):
        ctx = ContactContext.create_incomplete(
            contact_email="timeout@example.com",
            account_id=1,
            email_count=3,
            analysis_duration_ms=5000,
        )
        assert ctx.contact_email == "timeout@example.com"
        assert ctx.email_count == 3
        assert ctx.is_complete is False
        assert ctx.dominant_tone == DominantTone.PROFESSIONAL
        assert ctx.tone_confidence == 0.0
        assert ctx.recurring_topics == []
        assert ctx.relationship_strength == 0
        assert ctx.analysis_duration_ms == 5000
