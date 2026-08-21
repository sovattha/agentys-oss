# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests complets pour app/domain/entities/fine_tuning.py

Couvre:
- Enums (CorrectionType, ImprovementStatus, FeedbackSentiment)
- UserCorrection (create, has_significant_changes)
- UserFeedback (create, sentiment deduction)
- CorrectionPattern (create, increment_occurrence, is_reliable)
- ImprovementModel (create, state transitions, pattern/adjustment management)
- FineTuningSession (create, complete, fail)
- FineTuningStats (dataclass validation)
"""

import pytest
from datetime import datetime
from uuid import UUID

from app.domain.entities.fine_tuning import (
    CorrectionType,
    ImprovementStatus,
    FeedbackSentiment,
    UserCorrection,
    UserFeedback,
    CorrectionPattern,
    ImprovementModel,
    FineTuningSession,
    FineTuningStats,
)


# ============================================================================
# Tests des Enums
# ============================================================================

class TestCorrectionTypeEnum:
    """Tests pour l'enum CorrectionType."""

    def test_correction_type_values(self):
        """Vérifie que tous les types de correction sont définis."""
        assert CorrectionType.TONE.value == "tone"
        assert CorrectionType.GRAMMAR.value == "grammar"
        assert CorrectionType.STYLE.value == "style"
        assert CorrectionType.CONTENT.value == "content"
        assert CorrectionType.FORMAT.value == "format"
        assert CorrectionType.LENGTH.value == "length"
        assert CorrectionType.VOCABULARY.value == "vocabulary"
        assert CorrectionType.STRUCTURE.value == "structure"

    def test_correction_type_enum_count(self):
        """Vérifie qu'il y a exactement 8 types de correction."""
        assert len(CorrectionType) == 8

    def test_correction_type_members(self):
        """Vérifie les noms des membres."""
        members = [e.name for e in CorrectionType]
        assert "TONE" in members
        assert "GRAMMAR" in members
        assert "STYLE" in members
        assert "CONTENT" in members
        assert "FORMAT" in members
        assert "LENGTH" in members
        assert "VOCABULARY" in members
        assert "STRUCTURE" in members


class TestImprovementStatusEnum:
    """Tests pour l'enum ImprovementStatus."""

    def test_improvement_status_values(self):
        """Vérifie que tous les statuts sont définis."""
        assert ImprovementStatus.PENDING.value == "pending"
        assert ImprovementStatus.ACTIVE.value == "active"
        assert ImprovementStatus.DISABLED.value == "disabled"
        assert ImprovementStatus.DEPRECATED.value == "deprecated"

    def test_improvement_status_enum_count(self):
        """Vérifie qu'il y a exactement 4 statuts."""
        assert len(ImprovementStatus) == 4


class TestFeedbackSentimentEnum:
    """Tests pour l'enum FeedbackSentiment."""

    def test_feedback_sentiment_values(self):
        """Vérifie que tous les sentiments sont définis."""
        assert FeedbackSentiment.POSITIVE.value == "positive"
        assert FeedbackSentiment.NEUTRAL.value == "neutral"
        assert FeedbackSentiment.NEGATIVE.value == "negative"

    def test_feedback_sentiment_enum_count(self):
        """Vérifie qu'il y a exactement 3 sentiments."""
        assert len(FeedbackSentiment) == 3


# ============================================================================
# Tests de UserCorrection
# ============================================================================

class TestUserCorrectionCreate:
    """Tests pour la méthode create de UserCorrection."""

    def test_create_basic(self):
        """Crée une correction avec les paramètres obligatoires."""
        correction = UserCorrection.create(
            draft_id="draft_123",
            original_text="Hello world",
            corrected_text="Hello World",
        )

        assert correction.draft_id == "draft_123"
        assert correction.original_text == "Hello world"
        assert correction.corrected_text == "Hello World"
        assert correction.user_comment is None
        assert correction.context == {}
        assert correction.correction_types == []
        assert isinstance(correction.id, str)
        # Vérifier que l'ID est un UUID valide
        UUID(correction.id)

    def test_create_with_context(self):
        """Crée une correction avec contexte."""
        context = {"sender": "john@example.com", "category": "work"}
        correction = UserCorrection.create(
            draft_id="draft_456",
            original_text="text1",
            corrected_text="text2",
            context=context,
        )

        assert correction.context == context
        assert correction.context["sender"] == "john@example.com"

    def test_create_with_comment(self):
        """Crée une correction avec commentaire utilisateur."""
        correction = UserCorrection.create(
            draft_id="draft_789",
            original_text="original",
            corrected_text="corrected",
            user_comment="This sounds better",
        )

        assert correction.user_comment == "This sounds better"

    def test_create_with_all_parameters(self):
        """Crée une correction avec tous les paramètres."""
        context = {"sender": "jane@example.com", "importance": "high"}
        correction = UserCorrection.create(
            draft_id="draft_full",
            original_text="old text",
            corrected_text="new text",
            context=context,
            user_comment="Much better!",
        )

        assert correction.draft_id == "draft_full"
        assert correction.context == context
        assert correction.user_comment == "Much better!"

    def test_create_timestamp(self):
        """Vérifie que le timestamp est défini."""
        before = datetime.now()
        correction = UserCorrection.create(
            draft_id="draft_ts",
            original_text="text",
            corrected_text="text2",
        )
        after = datetime.now()

        assert before <= correction.created_at <= after

    def test_create_unique_ids(self):
        """Vérifie que chaque correction a un ID unique."""
        c1 = UserCorrection.create(
            draft_id="draft1", original_text="t1", corrected_text="t2"
        )
        c2 = UserCorrection.create(
            draft_id="draft2", original_text="t3", corrected_text="t4"
        )

        assert c1.id != c2.id


class TestUserCorrectionHasSignificantChanges:
    """Tests pour la méthode has_significant_changes de UserCorrection."""

    def test_no_change(self):
        """Pas de changement = pas de changements significatifs."""
        correction = UserCorrection.create(
            draft_id="d1", original_text="same text", corrected_text="same text"
        )

        assert not correction.has_significant_changes()

    def test_small_change_below_threshold(self):
        """Petit changement en dessous du seuil personnalisé de 15%."""
        # original: "Hello world" (11 chars)
        # changed: "Hello World" (1 char change) -> 1/11 = 9% < 15%
        correction = UserCorrection.create(
            draft_id="d1", original_text="Hello world", corrected_text="Hello World"
        )

        assert not correction.has_significant_changes(min_diff_ratio=0.15)

    def test_exact_threshold(self):
        """Change exactement au seuil de 5%."""
        # original: "test" (4 chars)
        # At 5%, need 0.2 chars minimum, so with 1 char changed: 1/4 = 25% > 5%
        correction = UserCorrection.create(
            draft_id="d1", original_text="test", corrected_text="best"
        )

        assert correction.has_significant_changes(min_diff_ratio=0.05)

    def test_length_change_addition(self):
        """Ajout de texte = changement significatif."""
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="Hello",
            corrected_text="Hello world",
        )

        assert correction.has_significant_changes()

    def test_length_change_deletion(self):
        """Suppression de texte = changement significatif."""
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="Hello world",
            corrected_text="Hello",
        )

        assert correction.has_significant_changes()

    def test_empty_original_text_with_content(self):
        """Original vide avec contenu ajouté = significatif."""
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="",
            corrected_text="New content",
        )

        assert correction.has_significant_changes()

    def test_empty_original_and_corrected(self):
        """Original et corrigé vides = non significatif."""
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="",
            corrected_text="",
        )

        assert not correction.has_significant_changes()

    def test_empty_original_empty_corrected_is_no_change(self):
        """Original avec contenu, corrigé vide."""
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="content",
            corrected_text="",
        )

        assert correction.has_significant_changes()

    def test_custom_threshold_low(self):
        """Utilise un seuil bas personnalisé."""
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="abcdefghij",  # 10 chars
            corrected_text="abcdefgxij",  # 1 changement = 10%
        )

        assert not correction.has_significant_changes(min_diff_ratio=0.15)
        assert correction.has_significant_changes(min_diff_ratio=0.05)

    def test_major_rewrite(self):
        """Réécriture importante = changement significatif."""
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="The quick brown fox jumps over the lazy dog",
            corrected_text="A fast auburn fox leaps beyond the sluggish canine",
        )

        assert correction.has_significant_changes()

    def test_case_change_only(self):
        """Changement de casse seul."""
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="hello",
            corrected_text="HELLO",
        )

        # 5 changements sur 5 chars = 100% > 5%
        assert correction.has_significant_changes()

    def test_whitespace_only_change(self):
        """Changement d'espaces uniquement."""
        correction = UserCorrection.create(
            draft_id="d1",
            original_text="hello world",
            corrected_text="hello  world",  # 2 espaces au lieu de 1
        )

        assert correction.has_significant_changes()


# ============================================================================
# Tests de UserFeedback
# ============================================================================

class TestUserFeedbackCreate:
    """Tests pour la méthode create de UserFeedback."""

    def test_create_with_rating_5_positive(self):
        """Rating 5 = sentiment POSITIVE."""
        feedback = UserFeedback.create(
            draft_id="draft_1",
            rating=5,
        )

        assert feedback.draft_id == "draft_1"
        assert feedback.rating == 5
        assert feedback.sentiment == FeedbackSentiment.POSITIVE

    def test_create_with_rating_4_positive(self):
        """Rating 4 = sentiment POSITIVE."""
        feedback = UserFeedback.create(
            draft_id="draft_1",
            rating=4,
        )

        assert feedback.rating == 4
        assert feedback.sentiment == FeedbackSentiment.POSITIVE

    def test_create_with_rating_3_neutral(self):
        """Rating 3 = sentiment NEUTRAL."""
        feedback = UserFeedback.create(
            draft_id="draft_1",
            rating=3,
        )

        assert feedback.rating == 3
        assert feedback.sentiment == FeedbackSentiment.NEUTRAL

    def test_create_with_rating_2_negative(self):
        """Rating 2 = sentiment NEGATIVE."""
        feedback = UserFeedback.create(
            draft_id="draft_1",
            rating=2,
        )

        assert feedback.rating == 2
        assert feedback.sentiment == FeedbackSentiment.NEGATIVE

    def test_create_with_rating_1_negative(self):
        """Rating 1 = sentiment NEGATIVE."""
        feedback = UserFeedback.create(
            draft_id="draft_1",
            rating=1,
        )

        assert feedback.rating == 1
        assert feedback.sentiment == FeedbackSentiment.NEGATIVE

    def test_create_with_comment(self):
        """Crée un feedback avec commentaire."""
        feedback = UserFeedback.create(
            draft_id="draft_1",
            rating=4,
            comment="Very good!",
        )

        assert feedback.comment == "Very good!"

    def test_create_with_tags(self):
        """Crée un feedback avec tags."""
        feedback = UserFeedback.create(
            draft_id="draft_1",
            rating=5,
            tags=["professional", "concise"],
        )

        assert feedback.tags == ["professional", "concise"]

    def test_create_with_all_parameters(self):
        """Crée un feedback avec tous les paramètres."""
        feedback = UserFeedback.create(
            draft_id="draft_complete",
            rating=4,
            comment="Excellent draft",
            tags=["tag1", "tag2"],
        )

        assert feedback.draft_id == "draft_complete"
        assert feedback.rating == 4
        assert feedback.sentiment == FeedbackSentiment.POSITIVE
        assert feedback.comment == "Excellent draft"
        assert feedback.tags == ["tag1", "tag2"]

    def test_create_rating_out_of_range_high(self):
        """Rating > 5 lève une ValueError."""
        with pytest.raises(ValueError, match="Rating must be between 1 and 5"):
            UserFeedback.create(draft_id="draft_1", rating=6)

    def test_create_rating_out_of_range_low(self):
        """Rating < 1 lève une ValueError."""
        with pytest.raises(ValueError, match="Rating must be between 1 and 5"):
            UserFeedback.create(draft_id="draft_1", rating=0)

    def test_create_unique_ids(self):
        """Chaque feedback a un ID unique."""
        f1 = UserFeedback.create(draft_id="d1", rating=4)
        f2 = UserFeedback.create(draft_id="d2", rating=5)

        assert f1.id != f2.id

    def test_create_timestamp(self):
        """Le timestamp est défini correctement."""
        before = datetime.now()
        feedback = UserFeedback.create(draft_id="d1", rating=3)
        after = datetime.now()

        assert before <= feedback.created_at <= after

    def test_create_default_tags_empty_list(self):
        """Les tags par défaut forment une liste vide."""
        feedback = UserFeedback.create(draft_id="d1", rating=2)

        assert feedback.tags == []

    def test_create_sentiment_boundary_rating_4(self):
        """Rating 4 est la limite basse de POSITIVE."""
        f4 = UserFeedback.create(draft_id="d1", rating=4)
        f3 = UserFeedback.create(draft_id="d2", rating=3)

        assert f4.sentiment == FeedbackSentiment.POSITIVE
        assert f3.sentiment == FeedbackSentiment.NEUTRAL

    def test_create_sentiment_boundary_rating_2(self):
        """Rating 2 est la limite haute de NEGATIVE."""
        f2 = UserFeedback.create(draft_id="d1", rating=2)
        f3 = UserFeedback.create(draft_id="d2", rating=3)

        assert f2.sentiment == FeedbackSentiment.NEGATIVE
        assert f3.sentiment == FeedbackSentiment.NEUTRAL


# ============================================================================
# Tests de CorrectionPattern
# ============================================================================

class TestCorrectionPatternCreate:
    """Tests pour la méthode create de CorrectionPattern."""

    def test_create_basic(self):
        """Crée un pattern avec les paramètres obligatoires."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.GRAMMAR,
            original_pattern="dont",
            replacement="don't",
        )

        assert pattern.pattern_type == CorrectionType.GRAMMAR
        assert pattern.original_pattern == "dont"
        assert pattern.replacement == "don't"
        assert pattern.occurrences == 1
        assert pattern.confidence == 0.5
        assert pattern.contexts == []
        assert pattern.examples == []
        assert pattern.last_used is None
        UUID(pattern.id)

    def test_create_with_context(self):
        """Crée un pattern avec contexte."""
        context = {"category": "technical"}
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.VOCABULARY,
            original_pattern="utilize",
            replacement="use",
            context=context,
        )

        assert pattern.contexts == [context]
        assert pattern.contexts[0]["category"] == "technical"

    def test_create_all_correction_types(self):
        """Crée des patterns pour tous les types."""
        for ctype in CorrectionType:
            pattern = CorrectionPattern.create(
                pattern_type=ctype,
                original_pattern="orig",
                replacement="repl",
            )
            assert pattern.pattern_type == ctype

    def test_create_timestamp(self):
        """Le timestamp de création est défini."""
        before = datetime.now()
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="x",
            replacement="y",
        )
        after = datetime.now()

        assert before <= pattern.created_at <= after

    def test_create_unique_ids(self):
        """Chaque pattern a un ID unique."""
        p1 = CorrectionPattern.create(
            pattern_type=CorrectionType.STYLE,
            original_pattern="a",
            replacement="b",
        )
        p2 = CorrectionPattern.create(
            pattern_type=CorrectionType.STYLE,
            original_pattern="a",
            replacement="b",
        )

        assert p1.id != p2.id


class TestCorrectionPatternIncrementOccurrence:
    """Tests pour la méthode increment_occurrence de CorrectionPattern."""

    def test_increment_occurrence_basic(self):
        """Incrémente le compteur d'occurrences."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.GRAMMAR,
            original_pattern="dont",
            replacement="don't",
        )

        assert pattern.occurrences == 1
        pattern.increment_occurrence()
        assert pattern.occurrences == 2

    def test_increment_occurrence_multiple_times(self):
        """Incrémente plusieurs fois."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.GRAMMAR,
            original_pattern="x",
            replacement="y",
        )

        for i in range(1, 6):
            assert pattern.occurrences == i
            pattern.increment_occurrence()
        assert pattern.occurrences == 6

    def test_increment_confidence_calculation(self):
        """La confiance est recalculée à min(1.0, occurrences/10) après chaque incrément."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="a",
            replacement="b",
        )

        # Défaut: occurrences=1, confidence=0.5 (valeur par défaut du dataclass)
        assert pattern.occurrences == 1
        assert pattern.confidence == pytest.approx(0.5)

        pattern.increment_occurrence()  # occurrences=2, confidence = 2/10 = 0.2
        assert pattern.occurrences == 2
        assert pattern.confidence == pytest.approx(0.2)

        pattern.increment_occurrence()  # occurrences=3, confidence = 3/10 = 0.3
        assert pattern.occurrences == 3
        assert pattern.confidence == pytest.approx(0.3)

    def test_confidence_caps_at_1_0(self):
        """La confiance ne dépasse pas 1.0."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.VOCABULARY,
            original_pattern="x",
            replacement="y",
        )

        # Incrémente jusqu'à 10 occurrences
        for _ in range(9):
            pattern.increment_occurrence()

        assert pattern.occurrences == 10
        assert pattern.confidence == pytest.approx(1.0)

        # Continuer devrait rester à 1.0
        pattern.increment_occurrence()
        assert pattern.occurrences == 11
        assert pattern.confidence == pytest.approx(1.0)

    def test_last_used_updated(self):
        """last_used est mis à jour."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.FORMAT,
            original_pattern="x",
            replacement="y",
        )

        assert pattern.last_used is None

        before = datetime.now()
        pattern.increment_occurrence()
        after = datetime.now()

        assert pattern.last_used is not None
        assert before <= pattern.last_used <= after

    def test_last_used_updated_on_each_increment(self):
        """last_used se met à jour à chaque incrément."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.STYLE,
            original_pattern="x",
            replacement="y",
        )

        pattern.increment_occurrence()
        first_use = pattern.last_used

        import time
        time.sleep(0.01)  # Petit délai pour que datetime.now() change

        pattern.increment_occurrence()
        second_use = pattern.last_used

        assert first_use < second_use


class TestCorrectionPatternIsReliable:
    """Tests pour la méthode is_reliable de CorrectionPattern."""

    def test_is_reliable_below_threshold(self):
        """Confiance < seuil = pas fiable."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="x",
            replacement="y",
        )

        # confidence = 0.5, min_confidence = 0.6
        assert not pattern.is_reliable(min_confidence=0.6)

    def test_is_reliable_at_threshold(self):
        """Confiance == seuil = fiable."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="x",
            replacement="y",
        )

        # confidence = 0.5
        assert pattern.is_reliable(min_confidence=0.5)

    def test_is_reliable_above_threshold(self):
        """Confiance > seuil = fiable."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="x",
            replacement="y",
        )

        # confidence = 0.5, min_confidence = 0.4
        assert pattern.is_reliable(min_confidence=0.4)

    def test_is_reliable_default_threshold(self):
        """Utilise le seuil par défaut de 0.6."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="x",
            replacement="y",
        )

        # confidence = 0.5, default min = 0.6 -> Not reliable
        assert not pattern.is_reliable()

        # Incrémenter jusqu'à confiance >= 0.6
        for _ in range(5):  # 6 occurrences, confiance = 0.6
            pattern.increment_occurrence()

        assert pattern.is_reliable()

    def test_is_reliable_after_increments(self):
        """Est fiable après suffisamment d'incréments."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.VOCABULARY,
            original_pattern="dont",
            replacement="don't",
        )

        # Incrémenter 5 fois pour avoir 6 occurrences -> confiance = 0.6
        for _ in range(5):
            pattern.increment_occurrence()

        assert pattern.is_reliable(min_confidence=0.6)

    def test_is_reliable_at_max_confidence(self):
        """Avec confiance 1.0, est toujours fiable."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.GRAMMAR,
            original_pattern="x",
            replacement="y",
        )

        # Incrémenter 9 fois pour avoir 10 occurrences -> confiance = 1.0
        for _ in range(9):
            pattern.increment_occurrence()

        assert pattern.is_reliable(min_confidence=1.0)
        assert pattern.is_reliable(min_confidence=0.0)


# ============================================================================
# Tests de ImprovementModel
# ============================================================================

class TestImprovementModelCreate:
    """Tests pour la méthode create de ImprovementModel."""

    def test_create_basic(self):
        """Crée un modèle avec les paramètres obligatoires."""
        model = ImprovementModel.create(
            name="Grammar Fixer",
            description="Fixes common grammar mistakes",
        )

        assert model.name == "Grammar Fixer"
        assert model.description == "Fixes common grammar mistakes"
        assert model.version == "1.0.0"
        assert model.status == ImprovementStatus.PENDING
        assert model.impact_score == 0.0
        assert model.drafts_improved == 0
        assert model.patterns == []
        assert model.prompt_adjustments == []
        UUID(model.id)

    def test_create_with_custom_version(self):
        """Crée un modèle avec version personnalisée."""
        model = ImprovementModel.create(
            name="Model",
            description="Desc",
            version="2.1.0",
        )

        assert model.version == "2.1.0"

    def test_create_timestamp(self):
        """Les timestamps sont définis."""
        before = datetime.now()
        model = ImprovementModel.create(
            name="Test",
            description="Test",
        )
        after = datetime.now()

        assert before <= model.created_at <= after
        assert before <= model.updated_at <= after

    def test_create_unique_ids(self):
        """Chaque modèle a un ID unique."""
        m1 = ImprovementModel.create(name="M1", description="D1")
        m2 = ImprovementModel.create(name="M2", description="D2")

        assert m1.id != m2.id


class TestImprovementModelStateTransitions:
    """Tests pour les transitions d'état du modèle."""

    def test_activate_changes_status(self):
        """activate() change le statut à ACTIVE."""
        model = ImprovementModel.create(name="Test", description="Test")

        assert model.status == ImprovementStatus.PENDING
        model.activate()
        assert model.status == ImprovementStatus.ACTIVE

    def test_disable_changes_status(self):
        """disable() change le statut à DISABLED."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.activate()

        model.disable()
        assert model.status == ImprovementStatus.DISABLED

    def test_deprecate_changes_status(self):
        """deprecate() change le statut à DEPRECATED."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.activate()

        model.deprecate()
        assert model.status == ImprovementStatus.DEPRECATED

    def test_activate_updates_timestamp(self):
        """activate() met à jour updated_at."""
        model = ImprovementModel.create(name="Test", description="Test")
        initial_updated = model.updated_at

        import time
        time.sleep(0.01)

        model.activate()

        assert model.updated_at > initial_updated

    def test_disable_updates_timestamp(self):
        """disable() met à jour updated_at."""
        model = ImprovementModel.create(name="Test", description="Test")
        initial_updated = model.updated_at

        import time
        time.sleep(0.01)

        model.disable()

        assert model.updated_at > initial_updated

    def test_deprecate_updates_timestamp(self):
        """deprecate() met à jour updated_at."""
        model = ImprovementModel.create(name="Test", description="Test")
        initial_updated = model.updated_at

        import time
        time.sleep(0.01)

        model.deprecate()

        assert model.updated_at > initial_updated

    def test_multiple_state_transitions(self):
        """Peut faire plusieurs transitions d'état."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.activate()
        assert model.status == ImprovementStatus.ACTIVE

        model.disable()
        assert model.status == ImprovementStatus.DISABLED

        model.deprecate()
        assert model.status == ImprovementStatus.DEPRECATED


class TestImprovementModelPatternManagement:
    """Tests pour la gestion des patterns du modèle."""

    def test_add_pattern_basic(self):
        """Ajoute un pattern au modèle."""
        model = ImprovementModel.create(name="Test", description="Test")
        pattern_id = "pattern_123"

        model.add_pattern(pattern_id)

        assert pattern_id in model.patterns
        assert len(model.patterns) == 1

    def test_add_pattern_multiple(self):
        """Ajoute plusieurs patterns."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.add_pattern("p1")
        model.add_pattern("p2")
        model.add_pattern("p3")

        assert model.patterns == ["p1", "p2", "p3"]

    def test_add_pattern_no_duplicate(self):
        """Ne duplique pas les patterns."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.add_pattern("p1")
        model.add_pattern("p1")

        assert model.patterns == ["p1"]

    def test_add_pattern_updates_timestamp(self):
        """add_pattern() met à jour updated_at."""
        model = ImprovementModel.create(name="Test", description="Test")
        initial_updated = model.updated_at

        import time
        time.sleep(0.01)

        model.add_pattern("p1")

        assert model.updated_at > initial_updated

    def test_add_pattern_no_timestamp_update_for_duplicate(self):
        """L'ajout d'un doublon ne met pas à jour le timestamp."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.add_pattern("p1")
        updated_after_first = model.updated_at

        import time
        time.sleep(0.01)

        model.add_pattern("p1")

        # Ne devrait pas changer puisque p1 est déjà présent
        assert model.updated_at == updated_after_first


class TestImprovementModelPromptAdjustments:
    """Tests pour la gestion des ajustements de prompt."""

    def test_add_prompt_adjustment_basic(self):
        """Ajoute un ajustement de prompt."""
        model = ImprovementModel.create(name="Test", description="Test")
        adjustment = "Be more formal"

        model.add_prompt_adjustment(adjustment)

        assert adjustment in model.prompt_adjustments
        assert len(model.prompt_adjustments) == 1

    def test_add_prompt_adjustment_multiple(self):
        """Ajoute plusieurs ajustements."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.add_prompt_adjustment("Be formal")
        model.add_prompt_adjustment("Use active voice")
        model.add_prompt_adjustment("Keep it short")

        assert len(model.prompt_adjustments) == 3

    def test_add_prompt_adjustment_no_duplicate(self):
        """Ne duplique pas les ajustements."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.add_prompt_adjustment("Same")
        model.add_prompt_adjustment("Same")

        assert model.prompt_adjustments == ["Same"]

    def test_add_prompt_adjustment_updates_timestamp(self):
        """add_prompt_adjustment() met à jour updated_at."""
        model = ImprovementModel.create(name="Test", description="Test")
        initial_updated = model.updated_at

        import time
        time.sleep(0.01)

        model.add_prompt_adjustment("Adjust")

        assert model.updated_at > initial_updated


class TestImprovementModelImprovementTracking:
    """Tests pour le suivi des améliorations."""

    def test_record_improvement_increments_count(self):
        """record_improvement() incrémente le compteur."""
        model = ImprovementModel.create(name="Test", description="Test")

        assert model.drafts_improved == 0
        model.record_improvement()
        assert model.drafts_improved == 1

    def test_record_improvement_multiple(self):
        """Peut être appelé plusieurs fois."""
        model = ImprovementModel.create(name="Test", description="Test")

        for i in range(1, 6):
            assert model.drafts_improved == i - 1
            model.record_improvement()
        assert model.drafts_improved == 5

    def test_record_improvement_updates_timestamp(self):
        """record_improvement() met à jour updated_at."""
        model = ImprovementModel.create(name="Test", description="Test")
        initial_updated = model.updated_at

        import time
        time.sleep(0.01)

        model.record_improvement()

        assert model.updated_at > initial_updated

    def test_update_impact_score_first_improvement(self):
        """Premier score d'impact est assigné directement."""
        model = ImprovementModel.create(name="Test", description="Test")

        model.update_impact_score(0.8)

        assert model.impact_score == pytest.approx(0.8)

    def test_update_impact_score_moving_average(self):
        """Calcule une moyenne mobile."""
        model = ImprovementModel.create(name="Test", description="Test")

        # Enregistrer une amélioration
        model.record_improvement()
        model.update_impact_score(0.8)
        assert model.impact_score == pytest.approx(0.8)

        # Deuxième amélioration: moyenne = (0.8*1 + 0.6) / 2 = 0.7
        model.record_improvement()
        model.update_impact_score(0.6)
        assert model.impact_score == pytest.approx(0.7)

        # Troisième: moyenne = (0.7*2 + 0.9) / 3
        model.record_improvement()
        model.update_impact_score(0.9)
        assert model.impact_score == pytest.approx((0.7 * 2 + 0.9) / 3)

    def test_update_impact_score_without_improvements(self):
        """Si drafts_improved == 0, assigne le score directement."""
        model = ImprovementModel.create(name="Test", description="Test")

        assert model.drafts_improved == 0
        model.update_impact_score(0.75)

        assert model.impact_score == pytest.approx(0.75)

    def test_update_impact_score_updates_timestamp(self):
        """update_impact_score() met à jour updated_at."""
        model = ImprovementModel.create(name="Test", description="Test")
        initial_updated = model.updated_at

        import time
        time.sleep(0.01)

        model.update_impact_score(0.5)

        assert model.updated_at > initial_updated

    def test_impact_score_capped_range(self):
        """Le score d'impact peut être entre 0.0 et 1.0."""
        model = ImprovementModel.create(name="Test", description="Test")

        # L'entité elle-même ne valide pas, mais accepte ces valeurs
        model.update_impact_score(0.0)
        assert model.impact_score == pytest.approx(0.0)

        model.update_impact_score(1.0)
        assert model.impact_score == pytest.approx(1.0)


# ============================================================================
# Tests de FineTuningSession
# ============================================================================

class TestFineTuningSessionCreate:
    """Tests pour la méthode create de FineTuningSession."""

    def test_create_basic(self):
        """Crée une session de fine-tuning."""
        session = FineTuningSession.create()

        assert session.status == "running"
        assert session.ended_at is None
        assert session.corrections_count == 0
        assert session.feedbacks_count == 0
        assert session.patterns_extracted == 0
        assert session.model_id is None
        UUID(session.id)

    def test_create_timestamp(self):
        """Le timestamp de démarrage est défini."""
        before = datetime.now()
        session = FineTuningSession.create()
        after = datetime.now()

        assert before <= session.started_at <= after

    def test_create_unique_ids(self):
        """Chaque session a un ID unique."""
        s1 = FineTuningSession.create()
        s2 = FineTuningSession.create()

        assert s1.id != s2.id


class TestFineTuningSessionComplete:
    """Tests pour la méthode complete de FineTuningSession."""

    def test_complete_basic(self):
        """complete() marque la session comme terminée."""
        session = FineTuningSession.create()

        assert session.status == "running"
        session.complete()

        assert session.status == "completed"
        assert session.ended_at is not None

    def test_complete_with_model_id(self):
        """complete() peut enregistrer un ID de modèle."""
        session = FineTuningSession.create()
        model_id = "model_123"

        session.complete(model_id=model_id)

        assert session.model_id == model_id
        assert session.status == "completed"

    def test_complete_without_model_id(self):
        """complete() fonctionne sans ID de modèle."""
        session = FineTuningSession.create()

        session.complete()

        assert session.model_id is None
        assert session.status == "completed"

    def test_complete_sets_end_time(self):
        """complete() définit le temps de fin."""
        session = FineTuningSession.create()
        before = datetime.now()

        session.complete()

        after = datetime.now()
        assert before <= session.ended_at <= after

    def test_complete_multiple_calls(self):
        """Peut être appelé plusieurs fois (derniers appels gagnent)."""
        session = FineTuningSession.create()

        session.complete(model_id="m1")
        assert session.model_id == "m1"

        session.complete(model_id="m2")
        assert session.model_id == "m2"


class TestFineTuningSessionFail:
    """Tests pour la méthode fail de FineTuningSession."""

    def test_fail_basic(self):
        """fail() marque la session comme échouée."""
        session = FineTuningSession.create()

        session.fail("Error occurred")

        assert session.status == "failed: Error occurred"
        assert session.ended_at is not None

    def test_fail_sets_end_time(self):
        """fail() définit le temps de fin."""
        session = FineTuningSession.create()
        before = datetime.now()

        session.fail("Some error")

        after = datetime.now()
        assert before <= session.ended_at <= after

    def test_fail_preserves_error_message(self):
        """fail() inclut le message d'erreur dans le statut."""
        session = FineTuningSession.create()
        error_msg = "Database connection failed"

        session.fail(error_msg)

        assert error_msg in session.status

    def test_fail_with_empty_error_message(self):
        """fail() fonctionne avec un message vide."""
        session = FineTuningSession.create()

        session.fail("")

        assert session.status == "failed: "

    def test_fail_overwrites_running_status(self):
        """fail() écrase le statut 'running'."""
        session = FineTuningSession.create()

        assert session.status == "running"
        session.fail("Error")

        assert session.status.startswith("failed:")

    def test_fail_multiple_calls(self):
        """Peut être appelé plusieurs fois."""
        session = FineTuningSession.create()

        session.fail("First error")
        first_status = session.status

        session.fail("Second error")

        assert session.status == "failed: Second error"
        assert session.status != first_status


# ============================================================================
# Tests de FineTuningStats
# ============================================================================

class TestFineTuningStats:
    """Tests pour la dataclass FineTuningStats."""

    def test_create_default_values(self):
        """Crée les stats avec les valeurs par défaut."""
        stats = FineTuningStats()

        assert stats.total_corrections == 0
        assert stats.total_feedbacks == 0
        assert stats.total_patterns == 0
        assert stats.active_models == 0
        assert stats.average_impact == 0.0
        assert stats.improvement_rate == 0.0
        assert stats.top_correction_types == {}
        assert stats.feedback_sentiment_distribution == {}
        assert stats.patterns_by_confidence == {}

    def test_create_with_values(self):
        """Crée les stats avec des valeurs personnalisées."""
        top_types = {"grammar": 10, "tone": 5}
        sentiment_dist = {"positive": 20, "neutral": 5, "negative": 3}
        conf_dist = {"high": 15, "medium": 8, "low": 5}

        stats = FineTuningStats(
            total_corrections=28,
            total_feedbacks=28,
            total_patterns=28,
            active_models=3,
            average_impact=0.75,
            improvement_rate=0.85,
            top_correction_types=top_types,
            feedback_sentiment_distribution=sentiment_dist,
            patterns_by_confidence=conf_dist,
        )

        assert stats.total_corrections == 28
        assert stats.total_feedbacks == 28
        assert stats.total_patterns == 28
        assert stats.active_models == 3
        assert stats.average_impact == pytest.approx(0.75)
        assert stats.improvement_rate == pytest.approx(0.85)
        assert stats.top_correction_types == top_types
        assert stats.feedback_sentiment_distribution == sentiment_dist
        assert stats.patterns_by_confidence == conf_dist

    def test_default_dicts_are_independent(self):
        """Les dicts par défaut ne sont pas partagés entre instances."""
        s1 = FineTuningStats()
        s2 = FineTuningStats()

        s1.top_correction_types["grammar"] = 5
        assert "grammar" not in s2.top_correction_types

    def test_modify_after_creation(self):
        """Les stats peuvent être modifiées après création."""
        stats = FineTuningStats()

        stats.total_corrections = 10
        stats.average_impact = 0.8
        stats.top_correction_types["tone"] = 3

        assert stats.total_corrections == 10
        assert stats.average_impact == pytest.approx(0.8)
        assert stats.top_correction_types == {"tone": 3}


# ============================================================================
# Tests d'intégration
# ============================================================================

class TestIntegration:
    """Tests d'intégration couvrant plusieurs entités ensemble."""

    def test_complete_workflow(self):
        """Workflow complet: correction -> pattern -> model -> session."""
        # Créer une correction
        correction = UserCorrection.create(
            draft_id="draft_1",
            original_text="dont worry",
            corrected_text="don't worry",
        )
        assert correction.has_significant_changes()

        # Créer un feedback
        feedback = UserFeedback.create(
            draft_id="draft_1",
            rating=5,
        )
        assert feedback.sentiment == FeedbackSentiment.POSITIVE

        # Créer un pattern
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.GRAMMAR,
            original_pattern="dont",
            replacement="don't",
        )
        assert not pattern.is_reliable()

        # Incrémenter pour rendre fiable
        for _ in range(5):
            pattern.increment_occurrence()
        assert pattern.is_reliable()

        # Créer un modèle
        model = ImprovementModel.create(
            name="Grammar Patterns",
            description="Learned grammar patterns",
        )
        model.add_pattern(pattern.id)
        model.activate()

        # Enregistrer des améliorations
        model.record_improvement()
        model.update_impact_score(0.9)

        assert model.status == ImprovementStatus.ACTIVE
        assert model.drafts_improved == 1
        assert model.impact_score == pytest.approx(0.9)

        # Créer une session
        session = FineTuningSession.create()
        session.corrections_count = 1
        session.feedbacks_count = 1
        session.patterns_extracted = 1
        session.complete(model_id=model.id)

        assert session.status == "completed"
        assert session.model_id == model.id

    def test_pattern_reliability_progression(self):
        """Un pattern progresse de non-fiable à fiable."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.VOCABULARY,
            original_pattern="utilize",
            replacement="use",
        )

        # Étape 1: Créé, pas fiable
        assert not pattern.is_reliable(min_confidence=0.6)

        # Étape 2: Après quelques occurrences
        for _ in range(3):
            pattern.increment_occurrence()
        assert not pattern.is_reliable(min_confidence=0.6)

        # Étape 3: Fiable
        for _ in range(2):
            pattern.increment_occurrence()
        assert pattern.is_reliable(min_confidence=0.6)

    def test_model_lifecycle(self):
        """Le modèle passe par tous les états possibles."""
        model = ImprovementModel.create(name="Test", description="Test")

        # PENDING -> ACTIVE
        assert model.status == ImprovementStatus.PENDING
        model.activate()
        assert model.status == ImprovementStatus.ACTIVE

        # ACTIVE -> DISABLED
        model.disable()
        assert model.status == ImprovementStatus.DISABLED

        # DISABLED -> DEPRECATED
        model.deprecate()
        assert model.status == ImprovementStatus.DEPRECATED

    def test_multiple_feedback_ratings_sentiment_mapping(self):
        """Teste le mapping de tous les ratings aux sentiments."""
        ratings_and_sentiments = [
            (1, FeedbackSentiment.NEGATIVE),
            (2, FeedbackSentiment.NEGATIVE),
            (3, FeedbackSentiment.NEUTRAL),
            (4, FeedbackSentiment.POSITIVE),
            (5, FeedbackSentiment.POSITIVE),
        ]

        for rating, expected_sentiment in ratings_and_sentiments:
            feedback = UserFeedback.create(
                draft_id=f"draft_{rating}",
                rating=rating,
            )
            assert feedback.sentiment == expected_sentiment
