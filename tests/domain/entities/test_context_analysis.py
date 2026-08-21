"""Tests pour les entités ContextAnalysisInput et ContextAnalysisResult.

TDD Tests - Story 4-7 Task 1
"""

import pytest


class TestContextAnalysisInput:
    """Tests pour l'entité ContextAnalysisInput."""

    def test_create_with_required_fields(self):
        """Test création avec les champs obligatoires."""
        from app.domain.entities.context_analysis import ContextAnalysisInput

        input_data = ContextAnalysisInput(
            account_id=1,
            contact_email="contact@example.com",
            emails=[{"subject": "Test", "body": "Hello"}],
        )

        assert input_data.account_id == 1
        assert input_data.contact_email == "contact@example.com"
        assert len(input_data.emails) == 1

    def test_create_with_all_fields(self):
        """Test création avec tous les champs."""
        from app.domain.entities.context_analysis import ContextAnalysisInput

        input_data = ContextAnalysisInput(
            account_id=1,
            contact_email="contact@example.com",
            emails=[{"subject": "Test", "body": "Hello"}],
            user_instructions="Be formal",
            session_id="sess-123",
        )

        assert input_data.user_instructions == "Be formal"
        assert input_data.session_id == "sess-123"

    def test_invalid_email_raises_error(self):
        """Test que email invalide lève une erreur."""
        from app.domain.entities.context_analysis import ContextAnalysisInput

        with pytest.raises(ValueError, match="valid email"):
            ContextAnalysisInput(
                account_id=1,
                contact_email="invalid-email",
                emails=[],
            )

    def test_empty_email_raises_error(self):
        """Test que email vide lève une erreur."""
        from app.domain.entities.context_analysis import ContextAnalysisInput

        with pytest.raises(ValueError, match="cannot be empty"):
            ContextAnalysisInput(
                account_id=1,
                contact_email="",
                emails=[],
            )

    def test_negative_account_id_raises_error(self):
        """Test que account_id négatif lève une erreur."""
        from app.domain.entities.context_analysis import ContextAnalysisInput

        with pytest.raises(ValueError, match="positive"):
            ContextAnalysisInput(
                account_id=-1,
                contact_email="test@example.com",
                emails=[],
            )

    def test_to_dict(self):
        """Test sérialisation en dictionnaire."""
        from app.domain.entities.context_analysis import ContextAnalysisInput

        input_data = ContextAnalysisInput(
            account_id=1,
            contact_email="contact@example.com",
            emails=[{"subject": "Test", "body": "Hello"}],
            user_instructions="Be formal",
        )

        result = input_data.to_dict()

        assert result["account_id"] == 1
        assert result["contact_email"] == "contact@example.com"
        assert result["user_instructions"] == "Be formal"


class TestContextAnalysisResult:
    """Tests pour l'entité ContextAnalysisResult."""

    def test_create_with_required_fields(self):
        """Test création avec les champs obligatoires."""
        from app.domain.entities.context_analysis import (
            ContextAnalysisResult,
            RelationshipType,
        )

        result = ContextAnalysisResult(
            contact_context="Professional relationship",
            style_hints=["formal", "concise"],
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
        )

        assert result.contact_context == "Professional relationship"
        assert "formal" in result.style_hints
        assert result.relationship_type == RelationshipType.COLLEAGUE
        assert result.confidence == 0.85

    def test_create_with_all_fields(self):
        """Test création avec tous les champs."""
        from app.domain.entities.context_analysis import (
            ContextAnalysisResult,
            RelationshipType,
        )

        result = ContextAnalysisResult(
            contact_context="Professional relationship",
            style_hints=["formal", "concise"],
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            raw_analysis={"topics": ["project", "deadline"]},
            analysis_duration_ms=150,
            tokens_used=500,
            cached=False,
        )

        assert result.raw_analysis["topics"] == ["project", "deadline"]
        assert result.analysis_duration_ms == 150
        assert result.tokens_used == 500
        assert result.cached is False

    def test_confidence_bounds_lower(self):
        """Test que confidence < 0 lève une erreur."""
        from app.domain.entities.context_analysis import (
            ContextAnalysisResult,
            RelationshipType,
        )

        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            ContextAnalysisResult(
                contact_context="Test",
                style_hints=[],
                relationship_type=RelationshipType.COLLEAGUE,
                confidence=-0.1,
            )

    def test_confidence_bounds_upper(self):
        """Test que confidence > 1 lève une erreur."""
        from app.domain.entities.context_analysis import (
            ContextAnalysisResult,
            RelationshipType,
        )

        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            ContextAnalysisResult(
                contact_context="Test",
                style_hints=[],
                relationship_type=RelationshipType.COLLEAGUE,
                confidence=1.5,
            )

    def test_relationship_type_enum_values(self):
        """Test tous les types de relation."""
        from app.domain.entities.context_analysis import RelationshipType

        assert RelationshipType.COLLEAGUE.value == "colleague"
        assert RelationshipType.CLIENT.value == "client"
        assert RelationshipType.MANAGER.value == "manager"
        assert RelationshipType.FRIEND.value == "friend"
        assert RelationshipType.UNKNOWN.value == "unknown"

    def test_relationship_type_from_string(self):
        """Test conversion string vers enum."""
        from app.domain.entities.context_analysis import (
            ContextAnalysisResult,
            RelationshipType,
        )

        result = ContextAnalysisResult(
            contact_context="Test",
            style_hints=[],
            relationship_type="client",  # String instead of enum
            confidence=0.5,
        )

        assert result.relationship_type == RelationshipType.CLIENT

    def test_to_dict(self):
        """Test sérialisation en dictionnaire."""
        from app.domain.entities.context_analysis import (
            ContextAnalysisResult,
            RelationshipType,
        )

        result = ContextAnalysisResult(
            contact_context="Professional relationship",
            style_hints=["formal", "concise"],
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.85,
            raw_analysis={"topics": ["project"]},
        )

        data = result.to_dict()

        assert data["contact_context"] == "Professional relationship"
        assert data["relationship_type"] == "colleague"
        assert data["confidence"] == 0.85

    def test_is_high_confidence(self):
        """Test méthode is_high_confidence."""
        from app.domain.entities.context_analysis import (
            ContextAnalysisResult,
            RelationshipType,
        )

        high_conf = ContextAnalysisResult(
            contact_context="Test",
            style_hints=[],
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.8,
        )
        low_conf = ContextAnalysisResult(
            contact_context="Test",
            style_hints=[],
            relationship_type=RelationshipType.COLLEAGUE,
            confidence=0.5,
        )

        assert high_conf.is_high_confidence() is True
        assert low_conf.is_high_confidence() is False

    def test_create_fallback(self):
        """Test création d'un résultat fallback."""
        from app.domain.entities.context_analysis import ContextAnalysisResult

        fallback = ContextAnalysisResult.create_fallback(
            reason="API timeout"
        )

        assert fallback.confidence == 0.0
        assert fallback.raw_analysis["fallback_reason"] == "API timeout"
        assert fallback.cached is False


class TestRelationshipType:
    """Tests pour l'enum RelationshipType."""

    def test_all_values_exist(self):
        """Test que toutes les valeurs existent."""
        from app.domain.entities.context_analysis import RelationshipType

        expected = ["colleague", "client", "manager", "friend", "unknown"]
        actual = [r.value for r in RelationshipType]

        assert sorted(actual) == sorted(expected)

    def test_from_string_valid(self):
        """Test conversion depuis string valide."""
        from app.domain.entities.context_analysis import RelationshipType

        assert RelationshipType("colleague") == RelationshipType.COLLEAGUE
        assert RelationshipType("client") == RelationshipType.CLIENT

    def test_from_string_invalid(self):
        """Test conversion depuis string invalide."""
        from app.domain.entities.context_analysis import RelationshipType

        with pytest.raises(ValueError):
            RelationshipType("invalid_type")
