"""Tests pour les entités Classification, Priority, EmailAnalysis.

Tests TDD pour les entités de classification et priorisation des emails.
Couvre:
- EmailCategory enum
- Classification entity (category, confidence, reason)
- Priority entity (urgency, vip, sentiment, deadline, priority_score)
- EmailAnalysis entity (email_id, classification, priority, analyzed_at)
"""

import pytest

from app.domain.entities.classification import (
    EmailCategory,
    Classification,
    Priority,
    EmailAnalysis,
)
from app.domain.exceptions import (
    InvalidBoundsError,
    EmptyValueError,
    InvalidFormatError,
)


# =============================================================================
# Tests EmailCategory Enum
# =============================================================================


class TestEmailCategory:
    """Tests pour l'enum EmailCategory."""

    def test_all_categories_exist(self):
        """Test que toutes les catégories existent."""
        expected_categories = {
            "URGENT",
            "IMPORTANT",
            "NORMAL",
            "NEWSLETTER",
            "PROMO",
            "CC_ONLY",
            "SPAM",
        }
        actual_categories = {cat.name for cat in EmailCategory}

        assert actual_categories == expected_categories

    def test_category_values(self):
        """Test les valeurs des catégories."""
        assert EmailCategory.URGENT.value == "URGENT"
        assert EmailCategory.IMPORTANT.value == "IMPORTANT"
        assert EmailCategory.NORMAL.value == "NORMAL"
        assert EmailCategory.NEWSLETTER.value == "NEWSLETTER"
        assert EmailCategory.PROMO.value == "PROMO"
        assert EmailCategory.CC_ONLY.value == "CC_ONLY"
        assert EmailCategory.SPAM.value == "SPAM"

    def test_create_from_string(self):
        """Test création d'un enum à partir d'une string."""
        urgent = EmailCategory("URGENT")
        assert urgent == EmailCategory.URGENT

        normal = EmailCategory("NORMAL")
        assert normal == EmailCategory.NORMAL

    def test_invalid_category_raises_error(self):
        """Test qu'une catégorie invalide lève une erreur."""
        with pytest.raises(ValueError):
            EmailCategory("INVALID_CATEGORY")


# =============================================================================
# Tests Classification Entity
# =============================================================================


class TestClassificationCreation:
    """Tests de création de l'entité Classification."""

    def test_create_with_valid_values(self):
        """Test création avec des valeurs valides."""
        classification = Classification(
            category=EmailCategory.URGENT,
            confidence=0.95,
            reason="Critical issue reported",
        )

        assert classification.category == EmailCategory.URGENT
        assert classification.confidence == 0.95
        assert classification.reason == "Critical issue reported"

    def test_create_with_confidence_min_boundary(self):
        """Test création avec confidence à la limite inférieure (0.0)."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.0,
            reason="Low confidence classification",
        )

        assert classification.confidence == 0.0

    def test_create_with_confidence_max_boundary(self):
        """Test création avec confidence à la limite supérieure (1.0)."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=1.0,
            reason="High confidence classification",
        )

        assert classification.confidence == 1.0

    def test_create_with_confidence_mid_range(self):
        """Test création avec confidence au milieu de la plage."""
        classification = Classification(
            category=EmailCategory.IMPORTANT,
            confidence=0.5,
            reason="Medium confidence",
        )

        assert classification.confidence == 0.5

    def test_create_with_empty_reason_string(self):
        """Test création avec une raison vide (string vide OK)."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.5,
            reason="",
        )

        assert classification.reason == ""


class TestClassificationValidation:
    """Tests de validation de Classification."""

    def test_confidence_below_min_raises_error(self):
        """Test que confidence < 0.0 lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Classification(
                category=EmailCategory.NORMAL,
                confidence=-0.1,
                reason="Invalid confidence",
            )

        exc = exc_info.value
        assert exc.field == "confidence"
        assert exc.value == -0.1
        assert exc.min_val == 0.0
        assert exc.max_val == 1.0

    def test_confidence_above_max_raises_error(self):
        """Test que confidence > 1.0 lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Classification(
                category=EmailCategory.NORMAL,
                confidence=1.5,
                reason="Invalid confidence",
            )

        exc = exc_info.value
        assert exc.field == "confidence"
        assert exc.value == 1.5
        assert exc.min_val == 0.0
        assert exc.max_val == 1.0

    def test_confidence_far_below_min_raises_error(self):
        """Test que confidence très négatif lève une erreur."""
        with pytest.raises(InvalidBoundsError):
            Classification(
                category=EmailCategory.NORMAL,
                confidence=-100.0,
                reason="Way out of bounds",
            )

    def test_confidence_far_above_max_raises_error(self):
        """Test que confidence très élevé lève une erreur."""
        with pytest.raises(InvalidBoundsError):
            Classification(
                category=EmailCategory.NORMAL,
                confidence=999.0,
                reason="Way out of bounds",
            )

    def test_reason_none_raises_type_error(self):
        """Test que reason=None lève TypeError."""
        with pytest.raises(TypeError) as exc_info:
            Classification(
                category=EmailCategory.NORMAL,
                confidence=0.5,
                reason=None,
            )

        assert "reason cannot be None" in str(exc_info.value)

    def test_invalid_category_type_accepted_but_not_enum(self):
        """Test qu'une catégorie string invalide est acceptée mais n'est pas un enum."""
        # Python dataclasses accept any type, so passing a string works
        # but it won't be an EmailCategory enum
        classification = Classification(
            category="INVALID_CATEGORY",  # type: ignore
            confidence=0.5,
            reason="Invalid category",
        )

        # The value is a string, not an enum
        assert classification.category != EmailCategory.NORMAL
        assert isinstance(classification.category, str)


class TestClassificationDefaultMethod:
    """Tests de la méthode default() de Classification."""

    def test_default_returns_normal_classification(self):
        """Test que default() retourne NORMAL."""
        classification = Classification.default()

        assert classification.category == EmailCategory.NORMAL
        assert classification.confidence == 0.5
        assert classification.reason == "Classification par défaut"

    def test_default_creates_new_instance(self):
        """Test que default() crée une nouvelle instance."""
        class1 = Classification.default()
        class2 = Classification.default()

        assert class1 is not class2
        assert class1.category == class2.category
        assert class1.confidence == class2.confidence

    def test_default_instance_is_valid(self):
        """Test que l'instance par défaut est valide."""
        classification = Classification.default()

        # Ne doit pas lever d'erreur de validation
        assert isinstance(classification, Classification)


class TestClassificationShouldSkip:
    """Tests de la méthode should_skip() de Classification."""

    def test_should_skip_newsletter(self):
        """Test que NEWSLETTER doit être ignoré."""
        classification = Classification(
            category=EmailCategory.NEWSLETTER,
            confidence=0.9,
            reason="Newsletter detected",
        )

        assert classification.should_skip() is True

    def test_should_skip_promo(self):
        """Test que PROMO doit être ignoré."""
        classification = Classification(
            category=EmailCategory.PROMO,
            confidence=0.9,
            reason="Promotional email",
        )

        assert classification.should_skip() is True

    def test_should_skip_spam(self):
        """Test que SPAM doit être ignoré."""
        classification = Classification(
            category=EmailCategory.SPAM,
            confidence=0.95,
            reason="Spam detected",
        )

        assert classification.should_skip() is True

    def test_should_skip_cc_only(self):
        """Test que CC_ONLY doit être ignoré."""
        classification = Classification(
            category=EmailCategory.CC_ONLY,
            confidence=0.8,
            reason="User is only in CC",
        )

        assert classification.should_skip() is True

    def test_should_not_skip_urgent(self):
        """Test que URGENT ne doit pas être ignoré."""
        classification = Classification(
            category=EmailCategory.URGENT,
            confidence=0.95,
            reason="Critical issue",
        )

        assert classification.should_skip() is False

    def test_should_not_skip_important(self):
        """Test que IMPORTANT ne doit pas être ignoré."""
        classification = Classification(
            category=EmailCategory.IMPORTANT,
            confidence=0.85,
            reason="Client question",
        )

        assert classification.should_skip() is False

    def test_should_not_skip_normal(self):
        """Test que NORMAL ne doit pas être ignoré."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.5,
            reason="Standard email",
        )

        assert classification.should_skip() is False


class TestClassificationToDict:
    """Tests de la méthode to_dict() de Classification."""

    def test_to_dict_basic(self):
        """Test sérialisation basique en dictionnaire."""
        classification = Classification(
            category=EmailCategory.URGENT,
            confidence=0.95,
            reason="Critical issue",
        )

        result = classification.to_dict()

        assert isinstance(result, dict)
        assert result["category"] == "URGENT"
        assert result["confidence"] == 0.95
        assert result["reason"] == "Critical issue"

    def test_to_dict_with_all_categories(self):
        """Test to_dict() pour chaque catégorie."""
        categories = [
            EmailCategory.URGENT,
            EmailCategory.IMPORTANT,
            EmailCategory.NORMAL,
            EmailCategory.NEWSLETTER,
            EmailCategory.PROMO,
            EmailCategory.CC_ONLY,
            EmailCategory.SPAM,
        ]

        for category in categories:
            classification = Classification(
                category=category,
                confidence=0.5,
                reason="Test",
            )

            result = classification.to_dict()

            assert result["category"] == category.value
            assert result["confidence"] == 0.5
            assert result["reason"] == "Test"

    def test_to_dict_preserves_confidence_precision(self):
        """Test que to_dict() préserve la précision de confidence."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.123456789,
            reason="Precision test",
        )

        result = classification.to_dict()

        assert result["confidence"] == 0.123456789

    def test_to_dict_with_empty_reason(self):
        """Test to_dict() avec une raison vide."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.5,
            reason="",
        )

        result = classification.to_dict()

        assert result["reason"] == ""


# =============================================================================
# Tests Priority Entity
# =============================================================================


class TestPriorityCreation:
    """Tests de création de l'entité Priority."""

    def test_create_with_valid_values(self):
        """Test création avec des valeurs valides."""
        priority = Priority(
            urgency=80,
            vip=70,
            sentiment=0.5,
            deadline=None,
            priority_score=75,
        )

        assert priority.urgency == 80
        assert priority.vip == 70
        assert priority.sentiment == 0.5
        assert priority.deadline is None
        assert priority.priority_score == 75

    def test_create_with_min_boundaries(self):
        """Test création avec les limites minimales."""
        priority = Priority(
            urgency=0,
            vip=0,
            sentiment=-1.0,
            deadline=None,
            priority_score=0,
        )

        assert priority.urgency == 0
        assert priority.vip == 0
        assert priority.sentiment == -1.0
        assert priority.priority_score == 0

    def test_create_with_max_boundaries(self):
        """Test création avec les limites maximales."""
        priority = Priority(
            urgency=100,
            vip=100,
            sentiment=1.0,
            deadline=None,
            priority_score=100,
        )

        assert priority.urgency == 100
        assert priority.vip == 100
        assert priority.sentiment == 1.0
        assert priority.priority_score == 100

    def test_create_with_iso_deadline(self):
        """Test création avec une deadline en format ISO."""
        deadline = "2026-03-25T14:30:00"
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=deadline,
            priority_score=50,
        )

        assert priority.deadline == deadline

    def test_create_with_iso_deadline_with_timezone(self):
        """Test création avec une deadline ISO avec timezone."""
        deadline = "2026-03-25T14:30:00+02:00"
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=deadline,
            priority_score=50,
        )

        assert priority.deadline == deadline

    def test_create_with_iso_deadline_z_format(self):
        """Test création avec une deadline ISO au format Z."""
        deadline = "2026-03-25T14:30:00Z"
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=deadline,
            priority_score=50,
        )

        assert priority.deadline == deadline


class TestPriorityValidation:
    """Tests de validation de Priority."""

    def test_urgency_below_min_raises_error(self):
        """Test que urgency < 0 lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority(
                urgency=-1,
                vip=50,
                sentiment=0.0,
                deadline=None,
                priority_score=50,
            )

        exc = exc_info.value
        assert exc.field == "urgency"
        assert exc.value == -1
        assert exc.min_val == 0
        assert exc.max_val == 100

    def test_urgency_above_max_raises_error(self):
        """Test que urgency > 100 lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority(
                urgency=101,
                vip=50,
                sentiment=0.0,
                deadline=None,
                priority_score=50,
            )

        exc = exc_info.value
        assert exc.field == "urgency"
        assert exc.value == 101
        assert exc.min_val == 0
        assert exc.max_val == 100

    def test_vip_below_min_raises_error(self):
        """Test que vip < 0 lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority(
                urgency=50,
                vip=-1,
                sentiment=0.0,
                deadline=None,
                priority_score=50,
            )

        exc = exc_info.value
        assert exc.field == "vip"

    def test_vip_above_max_raises_error(self):
        """Test que vip > 100 lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority(
                urgency=50,
                vip=101,
                sentiment=0.0,
                deadline=None,
                priority_score=50,
            )

        exc = exc_info.value
        assert exc.field == "vip"

    def test_sentiment_below_min_raises_error(self):
        """Test que sentiment < -1.0 lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority(
                urgency=50,
                vip=50,
                sentiment=-1.5,
                deadline=None,
                priority_score=50,
            )

        exc = exc_info.value
        assert exc.field == "sentiment"
        assert exc.min_val == -1.0
        assert exc.max_val == 1.0

    def test_sentiment_above_max_raises_error(self):
        """Test que sentiment > 1.0 lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority(
                urgency=50,
                vip=50,
                sentiment=1.5,
                deadline=None,
                priority_score=50,
            )

        exc = exc_info.value
        assert exc.field == "sentiment"

    def test_priority_score_below_min_raises_error(self):
        """Test que priority_score < 0 lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority(
                urgency=50,
                vip=50,
                sentiment=0.0,
                deadline=None,
                priority_score=-1,
            )

        exc = exc_info.value
        assert exc.field == "priority_score"

    def test_priority_score_above_max_raises_error(self):
        """Test que priority_score > 100 lève InvalidBoundsError."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority(
                urgency=50,
                vip=50,
                sentiment=0.0,
                deadline=None,
                priority_score=101,
            )

        exc = exc_info.value
        assert exc.field == "priority_score"

    def test_invalid_deadline_format_raises_error(self):
        """Test que deadline format invalide lève InvalidFormatError."""
        with pytest.raises(InvalidFormatError) as exc_info:
            Priority(
                urgency=50,
                vip=50,
                sentiment=0.0,
                deadline="2026-13-45",  # Invalid date
                priority_score=50,
            )

        exc = exc_info.value
        assert exc.field == "deadline"
        assert "ISO 8601" in exc.expected_format

    def test_invalid_deadline_not_iso_format_raises_error(self):
        """Test que deadline non ISO lève une erreur."""
        with pytest.raises(InvalidFormatError):
            Priority(
                urgency=50,
                vip=50,
                sentiment=0.0,
                deadline="25/03/2026",  # Not ISO format
                priority_score=50,
            )

    def test_empty_deadline_string_is_acceptable(self):
        """Test que deadline vide ne lève pas d'erreur."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline="",
            priority_score=50,
        )

        assert priority.deadline == ""

    def test_whitespace_only_deadline_is_acceptable(self):
        """Test que deadline avec seulement des espaces ne lève pas d'erreur."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline="   ",
            priority_score=50,
        )

        assert priority.deadline == "   "


class TestPriorityDefaultMethod:
    """Tests de la méthode default() de Priority."""

    def test_default_returns_medium_priority(self):
        """Test que default() retourne une priorité moyenne."""
        priority = Priority.default()

        assert priority.urgency == 50
        assert priority.vip == 50
        assert priority.sentiment == 0.0
        assert priority.deadline is None
        assert priority.priority_score == 50

    def test_default_creates_new_instance(self):
        """Test que default() crée une nouvelle instance."""
        p1 = Priority.default()
        p2 = Priority.default()

        assert p1 is not p2

    def test_default_instance_is_valid(self):
        """Test que l'instance par défaut est valide."""
        priority = Priority.default()

        assert isinstance(priority, Priority)
        assert not priority.is_high_priority()
        assert not priority.is_low_priority()


class TestPriorityFromComponents:
    """Tests de la méthode from_components() de Priority."""

    def test_from_components_basic(self):
        """Test creation from_components avec des valeurs basiques."""
        priority = Priority.from_components(
            urgency=80,
            vip=70,
            sentiment=0.5,
            deadline=None,
        )

        assert priority.urgency == 80
        assert priority.vip == 70
        assert priority.sentiment == 0.5
        assert priority.deadline is None

    def test_from_components_calculates_score(self):
        """Test que from_components() calcule le score correctement."""
        # Formula: int(urgency * 0.4 + vip * 0.3 + (sentiment + 1) * 15)
        # = int(80 * 0.4 + 70 * 0.3 + (0.5 + 1) * 15)
        # = int(32 + 21 + 22.5)
        # = int(75.5)
        # = 75

        priority = Priority.from_components(
            urgency=80,
            vip=70,
            sentiment=0.5,
        )

        assert priority.priority_score == 75

    def test_from_components_with_negative_sentiment(self):
        """Test calcul du score avec sentiment négatif."""
        # Formula: int(100 * 0.4 + 0 * 0.3 + (-1.0 + 1) * 15)
        # = int(40 + 0 + 0)
        # = 40

        priority = Priority.from_components(
            urgency=100,
            vip=0,
            sentiment=-1.0,
        )

        assert priority.priority_score == 40

    def test_from_components_with_positive_sentiment(self):
        """Test calcul du score avec sentiment positif."""
        # Formula: int(0 * 0.4 + 100 * 0.3 + (1.0 + 1) * 15)
        # = int(0 + 30 + 30)
        # = 60

        priority = Priority.from_components(
            urgency=0,
            vip=100,
            sentiment=1.0,
        )

        assert priority.priority_score == 60

    def test_from_components_score_clamped_to_max(self):
        """Test que le score est clampé à 100."""
        # Formula would give > 100, test clamping
        priority = Priority.from_components(
            urgency=100,
            vip=100,
            sentiment=1.0,
        )

        # Formula: int(100 * 0.4 + 100 * 0.3 + (1 + 1) * 15)
        # = int(40 + 30 + 30) = 100
        assert priority.priority_score == 100
        assert priority.priority_score <= 100

    def test_from_components_score_clamped_to_min(self):
        """Test que le score ne peut pas être négatif."""
        priority = Priority.from_components(
            urgency=0,
            vip=0,
            sentiment=-1.0,
        )

        # Formula: int(0 * 0.4 + 0 * 0.3 + (-1 + 1) * 15) = 0
        assert priority.priority_score >= 0

    def test_from_components_with_deadline(self):
        """Test from_components() avec une deadline."""
        deadline = "2026-03-25T14:30:00"
        priority = Priority.from_components(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=deadline,
        )

        assert priority.deadline == deadline

    def test_from_components_validates_urgency(self):
        """Test que from_components() valide urgency."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority.from_components(
                urgency=101,
                vip=50,
                sentiment=0.0,
            )

        assert exc_info.value.field == "urgency"

    def test_from_components_validates_vip(self):
        """Test que from_components() valide vip."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority.from_components(
                urgency=50,
                vip=-1,
                sentiment=0.0,
            )

        assert exc_info.value.field == "vip"

    def test_from_components_validates_sentiment(self):
        """Test que from_components() valide sentiment."""
        with pytest.raises(InvalidBoundsError) as exc_info:
            Priority.from_components(
                urgency=50,
                vip=50,
                sentiment=2.0,
            )

        assert exc_info.value.field == "sentiment"

    def test_from_components_score_formula_mid_range(self):
        """Test calcul du score avec valeurs mid-range."""
        # Formula: int(50 * 0.4 + 50 * 0.3 + (0 + 1) * 15)
        # = int(20 + 15 + 15) = 50

        priority = Priority.from_components(
            urgency=50,
            vip=50,
            sentiment=0.0,
        )

        assert priority.priority_score == 50


class TestPriorityIsHighPriority:
    """Tests de la méthode is_high_priority() de Priority."""

    def test_is_high_priority_score_70(self):
        """Test que score >= 70 retourne True."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=None,
            priority_score=70,
        )

        assert priority.is_high_priority() is True

    def test_is_high_priority_score_above_70(self):
        """Test que score > 70 retourne True."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=None,
            priority_score=85,
        )

        assert priority.is_high_priority() is True

    def test_is_high_priority_score_100(self):
        """Test que score 100 retourne True."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=None,
            priority_score=100,
        )

        assert priority.is_high_priority() is True

    def test_is_not_high_priority_score_69(self):
        """Test que score < 70 retourne False."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=None,
            priority_score=69,
        )

        assert priority.is_high_priority() is False

    def test_is_not_high_priority_score_0(self):
        """Test que score 0 retourne False."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=None,
            priority_score=0,
        )

        assert priority.is_high_priority() is False


class TestPriorityIsLowPriority:
    """Tests de la méthode is_low_priority() de Priority."""

    def test_is_low_priority_score_below_30(self):
        """Test que score < 30 retourne True."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=None,
            priority_score=29,
        )

        assert priority.is_low_priority() is True

    def test_is_low_priority_score_0(self):
        """Test que score 0 retourne True."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=None,
            priority_score=0,
        )

        assert priority.is_low_priority() is True

    def test_is_not_low_priority_score_30(self):
        """Test que score >= 30 retourne False."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=None,
            priority_score=30,
        )

        assert priority.is_low_priority() is False

    def test_is_not_low_priority_score_above_30(self):
        """Test que score > 30 retourne False."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=0.0,
            deadline=None,
            priority_score=50,
        )

        assert priority.is_low_priority() is False


class TestPriorityToDict:
    """Tests de la méthode to_dict() de Priority."""

    def test_to_dict_basic(self):
        """Test sérialisation basique en dictionnaire."""
        priority = Priority(
            urgency=80,
            vip=70,
            sentiment=0.5,
            deadline=None,
            priority_score=75,
        )

        result = priority.to_dict()

        assert isinstance(result, dict)
        assert result["urgency"] == 80
        assert result["vip"] == 70
        assert result["sentiment"] == 0.5
        assert result["deadline"] is None
        assert result["priority_score"] == 75

    def test_to_dict_with_deadline(self):
        """Test to_dict() avec une deadline."""
        deadline = "2026-03-25T14:30:00"
        priority = Priority(
            urgency=80,
            vip=70,
            sentiment=0.5,
            deadline=deadline,
            priority_score=75,
        )

        result = priority.to_dict()

        assert result["deadline"] == deadline

    def test_to_dict_with_negative_sentiment(self):
        """Test to_dict() avec sentiment négatif."""
        priority = Priority(
            urgency=50,
            vip=50,
            sentiment=-0.8,
            deadline=None,
            priority_score=40,
        )

        result = priority.to_dict()

        assert result["sentiment"] == -0.8

    def test_to_dict_preserves_all_fields(self):
        """Test que to_dict() préserve tous les champs."""
        deadline = "2026-03-25T10:00:00Z"
        priority = Priority(
            urgency=100,
            vip=100,
            sentiment=1.0,
            deadline=deadline,
            priority_score=100,
        )

        result = priority.to_dict()

        assert len(result) == 5
        assert "urgency" in result
        assert "vip" in result
        assert "sentiment" in result
        assert "deadline" in result
        assert "priority_score" in result


# =============================================================================
# Tests EmailAnalysis Entity
# =============================================================================


class TestEmailAnalysisCreation:
    """Tests de création de l'entité EmailAnalysis."""

    def test_create_with_required_fields(self):
        """Test création avec les champs obligatoires."""
        classification = Classification.default()
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-123",
            classification=classification,
            priority=priority,
        )

        assert analysis.email_id == "email-123"
        assert analysis.classification == classification
        assert analysis.priority == priority
        assert analysis.analyzed_at != ""

    def test_create_sets_analyzed_at_automatically(self):
        """Test que analyzed_at est défini automatiquement."""
        classification = Classification.default()
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-123",
            classification=classification,
            priority=priority,
        )

        # Should be in ISO format
        assert "T" in analysis.analyzed_at
        assert "-" in analysis.analyzed_at or "+" in analysis.analyzed_at

    def test_create_with_explicit_analyzed_at(self):
        """Test création avec analyzed_at explicite."""
        classification = Classification.default()
        priority = Priority.default()
        analyzed_at = "2026-03-23T10:00:00"

        analysis = EmailAnalysis(
            email_id="email-123",
            classification=classification,
            priority=priority,
            analyzed_at=analyzed_at,
        )

        assert analysis.analyzed_at == analyzed_at

    def test_create_with_urgent_classification(self):
        """Test création avec classification URGENT."""
        classification = Classification(
            category=EmailCategory.URGENT,
            confidence=0.95,
            reason="Critical issue",
        )
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-456",
            classification=classification,
            priority=priority,
        )

        assert analysis.classification.category == EmailCategory.URGENT

    def test_create_with_high_priority(self):
        """Test création avec priorité élevée."""
        classification = Classification.default()
        priority = Priority.from_components(
            urgency=100,
            vip=100,
            sentiment=1.0,
        )

        analysis = EmailAnalysis(
            email_id="email-789",
            classification=classification,
            priority=priority,
        )

        assert analysis.priority.is_high_priority() is True


class TestEmailAnalysisValidation:
    """Tests de validation de EmailAnalysis."""

    def test_empty_email_id_raises_error(self):
        """Test que email_id vide lève EmptyValueError."""
        classification = Classification.default()
        priority = Priority.default()

        with pytest.raises(EmptyValueError) as exc_info:
            EmailAnalysis(
                email_id="",
                classification=classification,
                priority=priority,
            )

        exc = exc_info.value
        assert exc.field == "email_id"

    def test_whitespace_only_email_id_raises_error(self):
        """Test que email_id avec seulement des espaces lève une erreur."""
        classification = Classification.default()
        priority = Priority.default()

        with pytest.raises(EmptyValueError):
            EmailAnalysis(
                email_id="   ",
                classification=classification,
                priority=priority,
            )

    def test_none_email_id_raises_error(self):
        """Test que email_id=None lève une erreur."""
        classification = Classification.default()
        priority = Priority.default()

        with pytest.raises((EmptyValueError, TypeError, AttributeError)):
            EmailAnalysis(
                email_id=None,  # type: ignore
                classification=classification,
                priority=priority,
            )

    def test_valid_email_id_accepted(self):
        """Test que email_id valide est accepté."""
        classification = Classification.default()
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="valid-email-id",
            classification=classification,
            priority=priority,
        )

        assert analysis.email_id == "valid-email-id"


class TestEmailAnalysisShouldProcess:
    """Tests de la méthode should_process() de EmailAnalysis."""

    def test_should_process_normal_email(self):
        """Test que NORMAL doit être traité."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.5,
            reason="Normal email",
        )
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-1",
            classification=classification,
            priority=priority,
        )

        assert analysis.should_process() is True

    def test_should_process_urgent_email(self):
        """Test que URGENT doit être traité."""
        classification = Classification(
            category=EmailCategory.URGENT,
            confidence=0.95,
            reason="Critical issue",
        )
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-2",
            classification=classification,
            priority=priority,
        )

        assert analysis.should_process() is True

    def test_should_process_important_email(self):
        """Test que IMPORTANT doit être traité."""
        classification = Classification(
            category=EmailCategory.IMPORTANT,
            confidence=0.85,
            reason="Client question",
        )
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-3",
            classification=classification,
            priority=priority,
        )

        assert analysis.should_process() is True

    def test_should_not_process_newsletter(self):
        """Test que NEWSLETTER ne doit pas être traité."""
        classification = Classification(
            category=EmailCategory.NEWSLETTER,
            confidence=0.9,
            reason="Newsletter",
        )
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-4",
            classification=classification,
            priority=priority,
        )

        assert analysis.should_process() is False

    def test_should_not_process_promo(self):
        """Test que PROMO ne doit pas être traité."""
        classification = Classification(
            category=EmailCategory.PROMO,
            confidence=0.85,
            reason="Promotional email",
        )
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-5",
            classification=classification,
            priority=priority,
        )

        assert analysis.should_process() is False

    def test_should_not_process_spam(self):
        """Test que SPAM ne doit pas être traité."""
        classification = Classification(
            category=EmailCategory.SPAM,
            confidence=0.99,
            reason="Spam detected",
        )
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-6",
            classification=classification,
            priority=priority,
        )

        assert analysis.should_process() is False

    def test_should_not_process_cc_only(self):
        """Test que CC_ONLY ne doit pas être traité."""
        classification = Classification(
            category=EmailCategory.CC_ONLY,
            confidence=0.8,
            reason="User is only in CC",
        )
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-7",
            classification=classification,
            priority=priority,
        )

        assert analysis.should_process() is False


class TestEmailAnalysisToDict:
    """Tests de la méthode to_dict() de EmailAnalysis."""

    def test_to_dict_basic(self):
        """Test sérialisation basique en dictionnaire."""
        classification = Classification(
            category=EmailCategory.URGENT,
            confidence=0.95,
            reason="Critical issue",
        )
        priority = Priority(
            urgency=80,
            vip=70,
            sentiment=0.5,
            deadline=None,
            priority_score=75,
        )
        analyzed_at = "2026-03-23T10:00:00"

        analysis = EmailAnalysis(
            email_id="email-123",
            classification=classification,
            priority=priority,
            analyzed_at=analyzed_at,
        )

        result = analysis.to_dict()

        assert isinstance(result, dict)
        assert result["email_id"] == "email-123"
        assert result["analyzed_at"] == analyzed_at

    def test_to_dict_includes_classification_dict(self):
        """Test que to_dict() inclut la classification comme dict."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.5,
            reason="Normal email",
        )
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-456",
            classification=classification,
            priority=priority,
        )

        result = analysis.to_dict()

        assert isinstance(result["classification"], dict)
        assert result["classification"]["category"] == "NORMAL"
        assert result["classification"]["confidence"] == 0.5
        assert result["classification"]["reason"] == "Normal email"

    def test_to_dict_includes_priority_dict(self):
        """Test que to_dict() inclut la priorité comme dict."""
        classification = Classification.default()
        priority = Priority(
            urgency=80,
            vip=70,
            sentiment=0.5,
            deadline=None,
            priority_score=75,
        )

        analysis = EmailAnalysis(
            email_id="email-789",
            classification=classification,
            priority=priority,
        )

        result = analysis.to_dict()

        assert isinstance(result["priority"], dict)
        assert result["priority"]["urgency"] == 80
        assert result["priority"]["vip"] == 70
        assert result["priority"]["sentiment"] == 0.5
        assert result["priority"]["priority_score"] == 75

    def test_to_dict_with_all_fields(self):
        """Test to_dict() avec tous les champs."""
        classification = Classification(
            category=EmailCategory.IMPORTANT,
            confidence=0.85,
            reason="Client question",
        )
        priority = Priority.from_components(
            urgency=90,
            vip=85,
            sentiment=0.5,
            deadline="2026-03-25T14:30:00",
        )
        analyzed_at = "2026-03-23T10:00:00"

        analysis = EmailAnalysis(
            email_id="email-complete",
            classification=classification,
            priority=priority,
            analyzed_at=analyzed_at,
        )

        result = analysis.to_dict()

        assert result["email_id"] == "email-complete"
        assert result["analyzed_at"] == analyzed_at
        assert isinstance(result["classification"], dict)
        assert isinstance(result["priority"], dict)

    def test_to_dict_serialization_is_flat_with_nested_dicts(self):
        """Test que to_dict() crée une structure avec dicts imbriquées."""
        classification = Classification.default()
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="email-struct",
            classification=classification,
            priority=priority,
        )

        result = analysis.to_dict()

        # Vérifier la structure
        assert len(result) == 4
        assert "email_id" in result
        assert "classification" in result
        assert "priority" in result
        assert "analyzed_at" in result


# =============================================================================
# Tests d'intégration multi-entités
# =============================================================================


class TestMultiEntityIntegration:
    """Tests d'intégration entre les différentes entités."""

    def test_skip_classification_leads_to_no_processing(self):
        """Test que classification à ignorer => should_process() False."""
        classification = Classification(
            category=EmailCategory.SPAM,
            confidence=0.99,
            reason="Spam detected",
        )
        priority = Priority.default()

        analysis = EmailAnalysis(
            email_id="spam-email",
            classification=classification,
            priority=priority,
        )

        assert classification.should_skip() is True
        assert analysis.should_process() is False

    def test_high_priority_low_confidence_classification(self):
        """Test email avec haute priorité et confiance basse."""
        classification = Classification(
            category=EmailCategory.IMPORTANT,
            confidence=0.2,
            reason="Uncertain, but appears important",
        )
        priority = Priority.from_components(
            urgency=100,
            vip=100,
            sentiment=1.0,
        )

        analysis = EmailAnalysis(
            email_id="high-priority-low-conf",
            classification=classification,
            priority=priority,
        )

        assert analysis.should_process() is True
        assert analysis.priority.is_high_priority() is True
        assert analysis.classification.confidence < 0.5

    def test_low_priority_high_confidence_normal(self):
        """Test email NORMAL avec confiance élevée mais priorité basse."""
        classification = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.95,
            reason="Definitely normal email",
        )
        priority = Priority.from_components(
            urgency=0,
            vip=0,
            sentiment=-1.0,
        )

        analysis = EmailAnalysis(
            email_id="low-priority-normal",
            classification=classification,
            priority=priority,
        )

        assert analysis.should_process() is True
        assert analysis.priority.is_low_priority() is True
        assert analysis.classification.confidence > 0.9

    def test_to_dict_round_trip(self):
        """Test que to_dict() peut être utilisé pour sérialisation JSON."""
        import json

        classification = Classification(
            category=EmailCategory.URGENT,
            confidence=0.95,
            reason="Critical issue",
        )
        priority = Priority.from_components(
            urgency=100,
            vip=90,
            sentiment=0.8,
            deadline="2026-03-25T14:30:00",
        )
        analyzed_at = "2026-03-23T10:00:00"

        analysis = EmailAnalysis(
            email_id="json-test",
            classification=classification,
            priority=priority,
            analyzed_at=analyzed_at,
        )

        # Convert to dict and to JSON
        result_dict = analysis.to_dict()
        json_str = json.dumps(result_dict)

        # Should not raise
        assert isinstance(json_str, str)
        assert len(json_str) > 0

        # Parse back
        parsed = json.loads(json_str)
        assert parsed["email_id"] == "json-test"
        assert parsed["classification"]["category"] == "URGENT"
        assert parsed["priority"]["urgency"] == 100
