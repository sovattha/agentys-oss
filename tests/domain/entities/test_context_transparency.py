# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'entité ContextTransparencyData.

Ces tests vérifient la création, validation et sérialisation
des données de transparence du contexte IA.
"""

import pytest
from datetime import datetime
from app.domain.entities.context_transparency import (
    ContextTransparencyData,
    AnalyzedEmailSummary,
    StyleProfileSummary,
    RelationshipSummary,
)


class TestAnalyzedEmailSummary:
    """Tests pour AnalyzedEmailSummary."""

    def test_create_valid_summary(self):
        """Test création d'un résumé d'email valide."""
        summary = AnalyzedEmailSummary(
            email_id="email123",
            subject="Test Subject",
            sender="sender@example.com",
            date=datetime(2026, 1, 19, 10, 30),
            relevant_excerpts=["excerpt 1", "excerpt 2"],
            relevance_score=0.85,
        )

        assert summary.email_id == "email123"
        assert summary.subject == "Test Subject"
        assert summary.sender == "sender@example.com"
        assert summary.relevance_score == 0.85
        assert len(summary.relevant_excerpts) == 2

    def test_empty_email_id_raises_error(self):
        """Test qu'un email_id vide lève une erreur."""
        with pytest.raises(ValueError, match="email_id cannot be empty"):
            AnalyzedEmailSummary(
                email_id="",
                subject="Test",
                sender="test@example.com",
                date=datetime.utcnow(),
                relevant_excerpts=[],
                relevance_score=0.5,
            )

    def test_invalid_sender_email_raises_error(self):
        """Test qu'un sender invalide lève une erreur."""
        with pytest.raises(ValueError, match="sender must be a valid email"):
            AnalyzedEmailSummary(
                email_id="email123",
                subject="Test",
                sender="invalid-email",
                date=datetime.utcnow(),
                relevant_excerpts=[],
                relevance_score=0.5,
            )

    def test_relevance_score_out_of_bounds_raises_error(self):
        """Test que relevance_score hors limites lève une erreur."""
        with pytest.raises(ValueError, match="relevance_score must be between"):
            AnalyzedEmailSummary(
                email_id="email123",
                subject="Test",
                sender="test@example.com",
                date=datetime.utcnow(),
                relevant_excerpts=[],
                relevance_score=1.5,
            )

    def test_to_dict(self):
        """Test conversion en dictionnaire."""
        dt = datetime(2026, 1, 19, 10, 30)
        summary = AnalyzedEmailSummary(
            email_id="email123",
            subject="Test Subject",
            sender="sender@example.com",
            date=dt,
            relevant_excerpts=["excerpt 1"],
            relevance_score=0.75,
        )

        result = summary.to_dict()

        assert result["email_id"] == "email123"
        assert result["subject"] == "Test Subject"
        assert result["sender"] == "sender@example.com"
        assert result["date"] == dt.isoformat()
        assert result["relevant_excerpts"] == ["excerpt 1"]
        assert result["relevance_score"] == 0.75


class TestStyleProfileSummary:
    """Tests pour StyleProfileSummary."""

    def test_create_valid_summary(self):
        """Test création d'un résumé de profil de style valide."""
        summary = StyleProfileSummary(
            formality_level="professional",
            characteristic_phrases=["Bien cordialement", "Merci d'avance"],
            greeting_style="Bonjour",
            closing_style="Cordialement",
            confidence=0.78,
        )

        assert summary.formality_level == "professional"
        assert len(summary.characteristic_phrases) == 2
        assert summary.greeting_style == "Bonjour"
        assert summary.confidence == 0.78

    def test_confidence_out_of_bounds_raises_error(self):
        """Test que confidence hors limites lève une erreur."""
        with pytest.raises(ValueError, match="confidence must be between"):
            StyleProfileSummary(
                formality_level="casual",
                characteristic_phrases=[],
                greeting_style="Salut",
                closing_style="A+",
                confidence=-0.1,
            )

    def test_to_dict(self):
        """Test conversion en dictionnaire."""
        summary = StyleProfileSummary(
            formality_level="formal",
            characteristic_phrases=["phrase1"],
            greeting_style="Madame, Monsieur",
            closing_style="Respectueusement",
            confidence=0.9,
        )

        result = summary.to_dict()

        assert result["formality_level"] == "formal"
        assert result["characteristic_phrases"] == ["phrase1"]
        assert result["greeting_style"] == "Madame, Monsieur"
        assert result["closing_style"] == "Respectueusement"
        assert result["confidence"] == 0.9


class TestRelationshipSummary:
    """Tests pour RelationshipSummary."""

    def test_create_valid_summary(self):
        """Test création d'un résumé de relation valide."""
        summary = RelationshipSummary(
            relationship_type="colleague",
            confidence=0.82,
            communication_frequency="weekly",
        )

        assert summary.relationship_type == "colleague"
        assert summary.confidence == 0.82
        assert summary.communication_frequency == "weekly"

    def test_invalid_relationship_type_raises_error(self):
        """Test qu'un type de relation invalide lève une erreur."""
        with pytest.raises(ValueError, match="relationship_type must be one of"):
            RelationshipSummary(
                relationship_type="invalid_type",
                confidence=0.5,
                communication_frequency="weekly",
            )

    def test_invalid_frequency_raises_error(self):
        """Test qu'une fréquence invalide lève une erreur."""
        with pytest.raises(ValueError, match="communication_frequency must be one of"):
            RelationshipSummary(
                relationship_type="client",
                confidence=0.5,
                communication_frequency="biweekly",
            )

    def test_to_dict(self):
        """Test conversion en dictionnaire."""
        summary = RelationshipSummary(
            relationship_type="manager",
            confidence=0.95,
            communication_frequency="daily",
        )

        result = summary.to_dict()

        assert result["relationship_type"] == "manager"
        assert result["confidence"] == 0.95
        assert result["communication_frequency"] == "daily"


class TestContextTransparencyData:
    """Tests pour ContextTransparencyData."""

    @pytest.fixture
    def sample_email_summaries(self):
        """Fixture pour des résumés d'emails valides."""
        return [
            AnalyzedEmailSummary(
                email_id="email1",
                subject="Project Update",
                sender="alice@example.com",
                date=datetime(2026, 1, 18, 9, 0),
                relevant_excerpts=["The deadline is next week"],
                relevance_score=0.9,
            ),
            AnalyzedEmailSummary(
                email_id="email2",
                subject="Re: Project Update",
                sender="alice@example.com",
                date=datetime(2026, 1, 17, 14, 30),
                relevant_excerpts=["Thanks for the update"],
                relevance_score=0.7,
            ),
        ]

    @pytest.fixture
    def sample_style_profile(self):
        """Fixture pour un profil de style valide."""
        return StyleProfileSummary(
            formality_level="professional",
            characteristic_phrases=["Bien cordialement"],
            greeting_style="Bonjour",
            closing_style="Cordialement",
            confidence=0.8,
        )

    @pytest.fixture
    def sample_relationship(self):
        """Fixture pour une relation valide."""
        return RelationshipSummary(
            relationship_type="colleague",
            confidence=0.85,
            communication_frequency="weekly",
        )

    def test_create_full_context(
        self, sample_email_summaries, sample_style_profile, sample_relationship
    ):
        """Test création d'un contexte complet."""
        context = ContextTransparencyData(
            session_id="session123",
            contact_email="alice@example.com",
            analyzed_emails=sample_email_summaries,
            style_profile=sample_style_profile,
            relationship=sample_relationship,
            analysis_timestamp=datetime(2026, 1, 19, 10, 0),
            total_context_tokens=1250,
        )

        assert context.session_id == "session123"
        assert context.contact_email == "alice@example.com"
        assert len(context.analyzed_emails) == 2
        assert context.style_profile is not None
        assert context.relationship is not None
        assert context.total_context_tokens == 1250

    def test_create_partial_context_no_style(
        self, sample_email_summaries, sample_relationship
    ):
        """Test création d'un contexte sans profil de style."""
        context = ContextTransparencyData(
            session_id="session456",
            contact_email="bob@example.com",
            analyzed_emails=sample_email_summaries,
            style_profile=None,
            relationship=sample_relationship,
            analysis_timestamp=datetime.utcnow(),
            total_context_tokens=800,
        )

        assert context.style_profile is None
        assert context.relationship is not None

    def test_create_partial_context_no_relationship(
        self, sample_email_summaries, sample_style_profile
    ):
        """Test création d'un contexte sans relation."""
        context = ContextTransparencyData(
            session_id="session789",
            contact_email="carol@example.com",
            analyzed_emails=sample_email_summaries,
            style_profile=sample_style_profile,
            relationship=None,
            analysis_timestamp=datetime.utcnow(),
            total_context_tokens=600,
        )

        assert context.style_profile is not None
        assert context.relationship is None

    def test_empty_session_id_raises_error(self, sample_email_summaries):
        """Test qu'un session_id vide lève une erreur."""
        with pytest.raises(ValueError, match="session_id cannot be empty"):
            ContextTransparencyData(
                session_id="",
                contact_email="test@example.com",
                analyzed_emails=sample_email_summaries,
                style_profile=None,
                relationship=None,
                analysis_timestamp=datetime.utcnow(),
                total_context_tokens=100,
            )

    def test_invalid_contact_email_raises_error(self, sample_email_summaries):
        """Test qu'un contact_email invalide lève une erreur."""
        with pytest.raises(ValueError, match="contact_email must be a valid email"):
            ContextTransparencyData(
                session_id="session123",
                contact_email="invalid-email",
                analyzed_emails=sample_email_summaries,
                style_profile=None,
                relationship=None,
                analysis_timestamp=datetime.utcnow(),
                total_context_tokens=100,
            )

    def test_negative_tokens_raises_error(self, sample_email_summaries):
        """Test que total_context_tokens négatif lève une erreur."""
        with pytest.raises(ValueError, match="total_context_tokens must be non-negative"):
            ContextTransparencyData(
                session_id="session123",
                contact_email="test@example.com",
                analyzed_emails=sample_email_summaries,
                style_profile=None,
                relationship=None,
                analysis_timestamp=datetime.utcnow(),
                total_context_tokens=-100,
            )

    def test_to_dict_full(
        self, sample_email_summaries, sample_style_profile, sample_relationship
    ):
        """Test conversion en dictionnaire avec toutes les données."""
        ts = datetime(2026, 1, 19, 10, 0)
        context = ContextTransparencyData(
            session_id="session123",
            contact_email="alice@example.com",
            analyzed_emails=sample_email_summaries,
            style_profile=sample_style_profile,
            relationship=sample_relationship,
            analysis_timestamp=ts,
            total_context_tokens=1250,
        )

        result = context.to_dict()

        assert result["session_id"] == "session123"
        assert result["contact_email"] == "alice@example.com"
        assert len(result["analyzed_emails"]) == 2
        assert result["analyzed_emails"][0]["email_id"] == "email1"
        assert result["style_profile"]["formality_level"] == "professional"
        assert result["relationship"]["relationship_type"] == "colleague"
        assert result["analysis_timestamp"] == ts.isoformat()
        assert result["total_context_tokens"] == 1250

    def test_to_dict_partial(self, sample_email_summaries):
        """Test conversion en dictionnaire avec données partielles."""
        context = ContextTransparencyData(
            session_id="session123",
            contact_email="test@example.com",
            analyzed_emails=sample_email_summaries,
            style_profile=None,
            relationship=None,
            analysis_timestamp=datetime.utcnow(),
            total_context_tokens=500,
        )

        result = context.to_dict()

        assert result["style_profile"] is None
        assert result["relationship"] is None

    def test_empty_analyzed_emails_allowed(self):
        """Test qu'une liste vide d'emails analysés est acceptée."""
        context = ContextTransparencyData(
            session_id="session123",
            contact_email="test@example.com",
            analyzed_emails=[],
            style_profile=None,
            relationship=None,
            analysis_timestamp=datetime.utcnow(),
            total_context_tokens=0,
        )

        assert len(context.analyzed_emails) == 0
