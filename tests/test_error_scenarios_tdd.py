# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les scénarios d'erreur et cas limites.

Ce module teste les comportements en cas d'erreur :
1. Erreurs de parsing et de validation
2. Null/None handling
3. Erreurs d'I/O et de réseau
4. Boundary conditions

Principes Clean Architecture respectés :
- Tests des entités sans dépendances externes
- Mocks pour les ports
- Isolation des couches
"""

import pytest

# Domain Entities
from app.domain.entities import (
    Email,
    Draft,
    Critique,
    DraftStatus,
    TokenUsage,
    DraftInput,
    DraftInputTone,
    CompletedDraft,
    DeviceToken,
    DevicePlatform,
    PushNotification,
    PushNotificationCategory,
    WizardConfig,
    BusinessSector,
    CompanySize,
    UserCorrection,
    UserFeedback,
    FeedbackSentiment,
    CorrectionPattern,
    CorrectionType,
    ImprovementModel,
    ImprovementStatus,
    MobileSession,
    MobileSyncState,
    SyncStatus,
    MobileDraft,
    MobileDraftAction,
    MobileUserPreferences,
    MobileAppConfig,
    MobileDraftActionRequest,
)

# Domain Ports

# Infrastructure


# ============================================================================
# TESTS - NULL / NONE HANDLING
# ============================================================================

class TestNullNoneHandling:
    """Tests pour la gestion des valeurs null/None."""

    def test_email_with_none_thread_id(self):
        """Email avec thread_id None."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="sender@test.com",
            thread_id=None
        )
        assert email.thread_id is None

    def test_email_with_none_received_at(self):
        """Email avec received_at None."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="sender@test.com",
            received_at=None
        )
        assert email.received_at is None

    def test_critique_with_none_reason(self):
        """Critique valide avec reason None."""
        critique = Critique(
            raw_response="VALID",
            is_valid=True,
            reason=None
        )
        assert critique.reason is None
        assert critique.is_valid is True

    def test_draft_input_all_optional_none(self):
        """DraftInput avec tous les champs optionnels None."""
        draft_input = DraftInput(
            raw_input="test",
            recipient=None,
            subject_hint=None,
            tone=DraftInputTone.NEUTRAL,
            key_points=[]
        )
        assert draft_input.recipient is None
        assert draft_input.subject_hint is None

    def test_completed_draft_with_none_recipient(self):
        """CompletedDraft avec recipient None."""
        draft = CompletedDraft(
            subject="Test",
            body="Body",
            recipient=None
        )
        assert draft.recipient is None

    def test_token_usage_with_empty_model(self):
        """TokenUsage avec modèle vide (équivalent None)."""
        usage = TokenUsage(
            input_tokens=1000,
            output_tokens=500,
            model=""
        )
        # Utilise le tarif par défaut (Sonnet)
        assert usage.cost > 0


# ============================================================================
# TESTS - VALIDATION ERRORS
# ============================================================================

class TestValidationErrors:
    """Tests pour les erreurs de validation."""

    def test_device_token_empty_raises_value_error(self):
        """DeviceToken avec token vide lève ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token="", platform=DevicePlatform.IOS)

    def test_device_token_whitespace_only_raises(self):
        """DeviceToken avec token espaces seulement lève ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token="   ", platform=DevicePlatform.IOS)

    def test_push_notification_empty_title_raises(self):
        """PushNotification avec titre vide lève ValueError."""
        with pytest.raises(ValueError, match="title cannot be empty"):
            PushNotification(title="", body="Body")

    def test_push_notification_empty_body_raises(self):
        """PushNotification avec body vide lève ValueError."""
        with pytest.raises(ValueError, match="body cannot be empty"):
            PushNotification(title="Title", body="")

    def test_user_feedback_rating_zero_raises(self):
        """UserFeedback avec note 0 lève ValueError."""
        with pytest.raises(ValueError, match="between 1 and 5"):
            UserFeedback.create(draft_id="d1", rating=0)

    def test_user_feedback_rating_six_raises(self):
        """UserFeedback avec note 6 lève ValueError."""
        with pytest.raises(ValueError, match="between 1 and 5"):
            UserFeedback.create(draft_id="d1", rating=6)

    def test_user_feedback_rating_negative_raises(self):
        """UserFeedback avec note négative lève ValueError."""
        with pytest.raises(ValueError, match="between 1 and 5"):
            UserFeedback.create(draft_id="d1", rating=-1)

    def test_mobile_session_empty_user_id_raises(self):
        """MobileSession avec user_id vide lève ValueError."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSession(user_id="")

    def test_mobile_sync_state_empty_user_id_raises(self):
        """MobileSyncState avec user_id vide lève ValueError."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSyncState(user_id="", device_token="token")

    def test_mobile_sync_state_empty_device_token_raises(self):
        """MobileSyncState avec device_token vide lève ValueError."""
        with pytest.raises(ValueError, match="Device token cannot be empty"):
            MobileSyncState(user_id="user-1", device_token="")

    def test_mobile_draft_empty_draft_id_raises(self):
        """MobileDraft avec draft_id vide lève ValueError."""
        with pytest.raises(ValueError, match="Draft ID cannot be empty"):
            MobileDraft(draft_id="", subject="S", recipient="r@r.com")

    def test_mobile_draft_empty_subject_raises(self):
        """MobileDraft avec subject vide lève ValueError."""
        with pytest.raises(ValueError, match="Subject cannot be empty"):
            MobileDraft(draft_id="d-1", subject="", recipient="r@r.com")

    def test_mobile_user_preferences_invalid_threshold_low(self):
        """MobileUserPreferences avec seuil négatif lève ValueError."""
        with pytest.raises(ValueError, match="between 0 and 100"):
            MobileUserPreferences(user_id="user-1", auto_approve_threshold=-1)

    def test_mobile_user_preferences_invalid_threshold_high(self):
        """MobileUserPreferences avec seuil > 100 lève ValueError."""
        with pytest.raises(ValueError, match="between 0 and 100"):
            MobileUserPreferences(user_id="user-1", auto_approve_threshold=101)

    def test_mobile_draft_action_request_empty_draft_id_raises(self):
        """MobileDraftActionRequest avec draft_id vide lève ValueError."""
        with pytest.raises(ValueError, match="Draft ID cannot be empty"):
            MobileDraftActionRequest(
                draft_id="",
                action=MobileDraftAction.APPROVED,
                user_id="user-1"
            )

    def test_mobile_draft_action_request_empty_user_id_raises(self):
        """MobileDraftActionRequest avec user_id vide lève ValueError."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileDraftActionRequest(
                draft_id="d-1",
                action=MobileDraftAction.APPROVED,
                user_id=""
            )

    def test_mobile_draft_action_request_edit_without_body_raises(self):
        """MobileDraftActionRequest edit sans body lève ValueError."""
        with pytest.raises(ValueError, match="Edited body is required"):
            MobileDraftActionRequest(
                draft_id="d-1",
                action=MobileDraftAction.EDITED,
                user_id="user-1"
            )


# ============================================================================
# TESTS - ENUM VALIDATION
# ============================================================================

class TestEnumValidation:
    """Tests pour la validation des enums."""

    def test_draft_status_invalid_value_raises(self):
        """DraftStatus avec valeur invalide lève ValueError."""
        with pytest.raises(ValueError):
            DraftStatus("invalid_status")

    def test_device_platform_invalid_raises(self):
        """DevicePlatform avec valeur invalide lève ValueError."""
        with pytest.raises(ValueError):
            DeviceToken(token="abc", platform="invalid_platform")

    def test_push_notification_invalid_category_raises(self):
        """PushNotification avec category invalide lève ValueError."""
        with pytest.raises(ValueError):
            PushNotification(title="T", body="B", category="invalid.category")

    def test_business_sector_all_values(self):
        """Test toutes les valeurs de BusinessSector."""
        sectors = list(BusinessSector)
        assert len(sectors) >= 5  # Au moins 5 secteurs

    def test_company_size_all_values(self):
        """Test toutes les valeurs de CompanySize."""
        sizes = list(CompanySize)
        assert len(sizes) >= 4  # Au moins 4 tailles

    def test_correction_type_all_values(self):
        """Test toutes les valeurs de CorrectionType."""
        types = list(CorrectionType)
        assert len(types) >= 3  # Au moins 3 types

    def test_feedback_sentiment_all_values(self):
        """Test toutes les valeurs de FeedbackSentiment."""
        sentiments = list(FeedbackSentiment)
        assert FeedbackSentiment.POSITIVE in sentiments
        assert FeedbackSentiment.NEUTRAL in sentiments
        assert FeedbackSentiment.NEGATIVE in sentiments


# ============================================================================
# TESTS - BOUNDARY CONDITIONS
# ============================================================================

class TestBoundaryConditions:
    """Tests pour les conditions aux limites."""

    def test_token_usage_zero_tokens(self):
        """TokenUsage avec zéro tokens."""
        usage = TokenUsage(input_tokens=0, output_tokens=0)
        assert usage.total == 0
        assert usage.cost == 0.0

    def test_token_usage_max_int(self):
        """TokenUsage avec très grand nombre."""
        import sys
        large = sys.maxsize // 2  # Grand mais pas overflow
        usage = TokenUsage(input_tokens=large, output_tokens=large)
        assert usage.total == large * 2

    def test_user_feedback_boundary_ratings(self):
        """UserFeedback avec notes aux limites."""
        feedback_1 = UserFeedback.create(draft_id="d1", rating=1)
        assert feedback_1.sentiment == FeedbackSentiment.NEGATIVE

        feedback_5 = UserFeedback.create(draft_id="d1", rating=5)
        assert feedback_5.sentiment == FeedbackSentiment.POSITIVE

    def test_mobile_user_preferences_boundary_thresholds(self):
        """MobileUserPreferences avec seuils aux limites."""
        prefs_0 = MobileUserPreferences(user_id="u1", auto_approve_threshold=0)
        assert prefs_0.auto_approve_threshold == 0

        prefs_100 = MobileUserPreferences(user_id="u1", auto_approve_threshold=100)
        assert prefs_100.auto_approve_threshold == 100

    def test_draft_version_boundary(self):
        """Draft avec versions aux limites."""
        from app.domain.exceptions import InvalidBoundsError

        # version=0 lève maintenant une erreur
        with pytest.raises(InvalidBoundsError):
            Draft(content="Test", version=0)

        # version=1 (minimum valide)
        draft_min = Draft(content="Test", version=1)
        assert draft_min.version == 1

        # Très grande version est toujours valide
        draft_max = Draft(content="Test", version=2**31 - 1)
        assert draft_max.version == 2**31 - 1

    def test_correction_pattern_confidence_boundaries(self):
        """CorrectionPattern avec confidence aux limites."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.TONE,
            original_pattern="a",
            replacement="b",
            confidence=0.0
        )
        assert pattern.confidence == 0.0

        pattern_high = CorrectionPattern(
            id="p2",
            pattern_type=CorrectionType.TONE,
            original_pattern="a",
            replacement="b",
            confidence=1.0
        )
        assert pattern_high.confidence == 1.0


# ============================================================================
# TESTS - STRING FORMATTING EDGE CASES
# ============================================================================

class TestStringFormattingEdgeCases:
    """Tests pour le formatage de strings en edge cases."""

    def test_email_content_with_newlines_tabs(self):
        """Email avec newlines et tabs dans le contenu."""
        email = Email(
            id="123",
            subject="Subject\twith\ttabs",
            body="Body\nwith\nnewlines\n\nand\ttabs",
            sender="sender@test.com"
        )
        content = email.content_for_processing
        assert "\t" in content or "\n" in content

    def test_draft_str_with_special_chars(self):
        """Draft __str__ avec caractères spéciaux."""
        draft = Draft(content="<script>alert('xss')</script>")
        result = str(draft)
        assert "<script>" in result  # Non échappé au niveau entité

    def test_critique_str_with_unicode(self):
        """Critique __str__ avec unicode."""
        critique = Critique(
            raw_response="REJET : Problème 日本語 🚫",
            is_valid=False,
            reason="REJET : Problème 日本語 🚫"
        )
        result = str(critique)
        assert "日本語" in result
        assert "🚫" in result

    def test_completed_draft_str_very_long_subject(self):
        """CompletedDraft __str__ avec sujet très long."""
        long_subject = "A" * 1000
        draft = CompletedDraft(subject=long_subject, body="Body")
        result = str(draft)
        assert long_subject in result


# ============================================================================
# TESTS - STATE TRANSITIONS
# ============================================================================

class TestStateTransitions:
    """Tests pour les transitions d'état."""

    def test_mobile_session_touch_updates_activity(self):
        """MobileSession.touch() met à jour last_activity_at."""
        session = MobileSession(user_id="user-1")
        old_time = session.last_activity_at
        import time
        time.sleep(0.01)
        session.touch()
        assert session.last_activity_at > old_time

    def test_mobile_session_end_deactivates(self):
        """MobileSession.end() désactive la session."""
        session = MobileSession(user_id="user-1")
        assert session.is_active is True
        session.end()
        assert session.is_active is False

    def test_mobile_sync_state_status_transitions(self):
        """MobileSyncState transitions de statut."""
        state = MobileSyncState(user_id="u1", device_token="token")
        assert state.last_sync_status == SyncStatus.IDLE

        state.mark_syncing()
        assert state.last_sync_status == SyncStatus.SYNCING

        state.mark_success(drafts_count=5)
        assert state.last_sync_status == SyncStatus.SUCCESS
        assert state.drafts_synced_count == 5

    def test_mobile_sync_state_failed_transition(self):
        """MobileSyncState transition vers FAILED."""
        state = MobileSyncState(user_id="u1", device_token="token")
        state.mark_syncing()
        state.mark_failed("Network error")
        assert state.last_sync_status == SyncStatus.FAILED
        assert state.error_message == "Network error"

    def test_mobile_draft_action_transitions(self):
        """MobileDraft transitions d'action."""
        draft = MobileDraft(draft_id="d1", subject="S", recipient="r@r.com")
        assert draft.action == MobileDraftAction.PENDING

        draft.approve()
        assert draft.action == MobileDraftAction.APPROVED

        # Peut changer d'avis
        draft.reject()
        assert draft.action == MobileDraftAction.REJECTED

    def test_improvement_model_status_transitions(self):
        """ImprovementModel transitions de statut."""
        model = ImprovementModel.create(name="Test", description="Test")
        assert model.status == ImprovementStatus.PENDING

        model.activate()
        assert model.status == ImprovementStatus.ACTIVE

        model.disable()
        assert model.status == ImprovementStatus.DISABLED

        model.deprecate()
        assert model.status == ImprovementStatus.DEPRECATED

    def test_correction_pattern_confidence_increment(self):
        """CorrectionPattern increment ne dépasse pas 1.0."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.TONE,
            original_pattern="a",
            replacement="b",
            occurrences=9,
            confidence=0.9
        )
        pattern.increment_occurrence()
        assert pattern.confidence == 1.0

        # Même après plus d'incréments
        pattern.increment_occurrence()
        assert pattern.confidence == 1.0


# ============================================================================
# TESTS - SERIALIZATION EDGE CASES
# ============================================================================

class TestSerializationEdgeCases:
    """Tests pour la sérialisation/désérialisation."""

    def test_device_token_roundtrip(self):
        """DeviceToken sérialisation/désérialisation roundtrip."""
        original = DeviceToken(
            token="abc123",
            platform=DevicePlatform.ANDROID,
            user_id="user-1",
            device_name="Mon Téléphone 📱"
        )
        data = original.to_dict()
        restored = DeviceToken.from_dict(data)
        assert restored.token == original.token
        assert restored.platform == original.platform
        assert restored.user_id == original.user_id
        assert restored.device_name == original.device_name

    def test_push_notification_roundtrip(self):
        """PushNotification sérialisation roundtrip."""
        original = PushNotification(
            title="Titre 🔔",
            body="Corps avec unicode éàü",
            category=PushNotificationCategory.DRAFT_CREATED,
            data={"key": "value"},
            badge=5
        )
        data = original.to_dict()
        assert data["title"] == "Titre 🔔"
        assert data["body"] == "Corps avec unicode éàü"
        assert data["badge"] == 5

    def test_wizard_config_roundtrip(self):
        """WizardConfig sérialisation/désérialisation roundtrip."""
        original = WizardConfig(
            config_id="cfg-123",
            company_name="Test Corp",
            sector=BusinessSector.TECH,
            size=CompanySize.STARTUP
        )
        original.activate_agent("agent-1", priority=80)
        data = original.to_dict()
        restored = WizardConfig.from_dict(data)
        assert restored.config_id == original.config_id
        assert restored.sector == original.sector
        assert len(restored.agents) == 1

    def test_mobile_session_roundtrip(self):
        """MobileSession sérialisation/désérialisation roundtrip."""
        original = MobileSession(
            user_id="user-1",
            device_token="token-abc",
            app_version="2.1.0"
        )
        data = original.to_dict()
        restored = MobileSession.from_dict(data)
        assert restored.user_id == original.user_id
        assert restored.device_token == original.device_token
        assert restored.app_version == original.app_version

    def test_mobile_draft_roundtrip(self):
        """MobileDraft sérialisation roundtrip."""
        original = MobileDraft(
            draft_id="d-1",
            subject="Test Subject",
            recipient="test@test.com",
            recipient_name="Test User",
            body_full="Full body content here"
        )
        data = original.to_dict()
        assert data["draft_id"] == "d-1"
        assert data["subject"] == "Test Subject"
        assert data["recipient_name"] == "Test User"


# ============================================================================
# TESTS - VERSION COMPARISON (MOBILE APP CONFIG)
# ============================================================================

class TestVersionComparison:
    """Tests pour la comparaison de versions."""

    def test_version_same_supported(self):
        """Version identique est supportée."""
        config = MobileAppConfig(min_version="2.0.0")
        assert config.is_version_supported("2.0.0") is True

    def test_version_higher_supported(self):
        """Version supérieure est supportée."""
        config = MobileAppConfig(min_version="2.0.0")
        assert config.is_version_supported("2.1.0") is True
        assert config.is_version_supported("3.0.0") is True

    def test_version_lower_not_supported(self):
        """Version inférieure n'est pas supportée."""
        config = MobileAppConfig(min_version="2.0.0")
        assert config.is_version_supported("1.9.9") is False
        assert config.is_version_supported("1.0.0") is False

    def test_version_needs_update(self):
        """needs_update détecte correctement."""
        config = MobileAppConfig(latest_version="2.5.0")
        assert config.needs_update("2.4.0") is True
        assert config.needs_update("2.4.9") is True
        assert config.needs_update("2.5.0") is False
        assert config.needs_update("2.6.0") is False

    def test_version_partial_format(self):
        """Versions avec format partiel (sans patch)."""
        config = MobileAppConfig(min_version="2.0", latest_version="2.5")
        assert config.is_version_supported("2.0") is True
        assert config.is_version_supported("2.0.0") is True
        assert config.needs_update("2.4") is True


# ============================================================================
# TESTS - WIZARD CONFIG AGENT MANAGEMENT
# ============================================================================

class TestWizardConfigAgentManagement:
    """Tests pour la gestion des agents dans WizardConfig."""

    def test_activate_agent_creates_new(self):
        """activate_agent crée un nouvel agent si inexistant."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.activate_agent("agent-1", priority=75)
        assert len(config.agents) == 1
        assert config.agents[0].agent_id == "agent-1"
        assert config.agents[0].priority == 75
        assert config.agents[0].enabled is True

    def test_activate_agent_updates_existing(self):
        """activate_agent met à jour un agent existant."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.activate_agent("agent-1", priority=50)
        config.activate_agent("agent-1", priority=90)
        assert len(config.agents) == 1
        assert config.agents[0].priority == 90

    def test_deactivate_agent_disables(self):
        """deactivate_agent désactive un agent existant."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.activate_agent("agent-1")
        config.deactivate_agent("agent-1")
        assert config.agents[0].enabled is False

    def test_deactivate_nonexistent_no_error(self):
        """deactivate_agent sur agent inexistant ne lève pas d'erreur."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.deactivate_agent("nonexistent")  # Pas d'erreur
        assert len(config.agents) == 0

    def test_get_active_agents_sorted_by_priority(self):
        """get_active_agents retourne les agents triés par priorité décroissante."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.activate_agent("low", priority=10)
        config.activate_agent("high", priority=100)
        config.activate_agent("medium", priority=50)
        config.deactivate_agent("medium")  # Désactivé

        active = config.get_active_agents()
        assert len(active) == 2
        assert active[0].agent_id == "high"
        assert active[1].agent_id == "low"

    def test_is_agent_active_true(self):
        """is_agent_active retourne True pour agent actif."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.activate_agent("agent-1")
        assert config.is_agent_active("agent-1") is True

    def test_is_agent_active_false_after_deactivate(self):
        """is_agent_active retourne False après désactivation."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.activate_agent("agent-1")
        config.deactivate_agent("agent-1")
        assert config.is_agent_active("agent-1") is False

    def test_is_agent_active_false_nonexistent(self):
        """is_agent_active retourne False pour agent inexistant."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        assert config.is_agent_active("nonexistent") is False


# ============================================================================
# TESTS - CORRECTION PATTERN RELIABILITY
# ============================================================================

class TestCorrectionPatternReliability:
    """Tests pour la fiabilité des CorrectionPattern."""

    def test_is_reliable_with_low_confidence(self):
        """is_reliable retourne False avec faible confidence."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.TONE,
            original_pattern="a",
            replacement="b",
            confidence=0.3
        )
        assert pattern.is_reliable(min_confidence=0.5) is False

    def test_is_reliable_at_threshold(self):
        """is_reliable retourne True au seuil exact."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.TONE,
            original_pattern="a",
            replacement="b",
            confidence=0.5
        )
        assert pattern.is_reliable(min_confidence=0.5) is True

    def test_is_reliable_above_threshold(self):
        """is_reliable retourne True au-dessus du seuil."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.TONE,
            original_pattern="a",
            replacement="b",
            confidence=0.8
        )
        assert pattern.is_reliable(min_confidence=0.5) is True

    def test_increment_occurrence_updates_confidence(self):
        """increment_occurrence augmente confidence correctement."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.GRAMMAR,
            original_pattern="a",
            replacement="b",
            occurrences=5,
            confidence=0.5
        )
        pattern.increment_occurrence()
        assert pattern.occurrences == 6
        assert pattern.confidence == 0.6


# ============================================================================
# TESTS - USER CORRECTION SIGNIFICANT CHANGES
# ============================================================================

class TestUserCorrectionSignificantChanges:
    """Tests pour has_significant_changes de UserCorrection."""

    def test_significant_changes_large_diff(self):
        """has_significant_changes avec grande différence."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="Short",
            corrected_text="This is a completely different and much longer text"
        )
        assert correction.has_significant_changes() is True

    def test_significant_changes_small_diff(self):
        """has_significant_changes avec petite différence."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="This is a fairly long text that has many words",
            corrected_text="This is a fairly long text that has many Words"  # 1 char
        )
        assert correction.has_significant_changes(min_diff_ratio=0.1) is False

    def test_significant_changes_empty_original(self):
        """has_significant_changes avec original vide."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="",
            corrected_text="New content"
        )
        assert correction.has_significant_changes() is True

    def test_significant_changes_both_empty(self):
        """has_significant_changes avec les deux vides."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="",
            corrected_text=""
        )
        assert correction.has_significant_changes() is False

    def test_significant_changes_identical(self):
        """has_significant_changes avec textes identiques."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="Same text",
            corrected_text="Same text"
        )
        assert correction.has_significant_changes() is False


# ============================================================================
# TESTS - MOBILE DRAFT PREVIEW GENERATION
# ============================================================================

class TestMobileDraftPreview:
    """Tests pour la génération de preview de MobileDraft."""

    def test_preview_short_body_unchanged(self):
        """Preview avec body court reste inchangé."""
        draft = MobileDraft(
            draft_id="d1",
            subject="S",
            recipient="r@r.com",
            body_full="Short text"
        )
        assert draft.body_preview == "Short text"

    def test_preview_long_body_truncated(self):
        """Preview avec body long est tronqué."""
        long_body = "A" * 300
        draft = MobileDraft(
            draft_id="d1",
            subject="S",
            recipient="r@r.com",
            body_full=long_body
        )
        assert len(draft.body_preview) == 203  # 200 + "..."
        assert draft.body_preview.endswith("...")

    def test_preview_exactly_200_chars(self):
        """Preview avec body de exactement 200 caractères."""
        body_200 = "A" * 200
        draft = MobileDraft(
            draft_id="d1",
            subject="S",
            recipient="r@r.com",
            body_full=body_200
        )
        assert draft.body_preview == body_200
        assert not draft.body_preview.endswith("...")

    def test_preview_201_chars_truncated(self):
        """Preview avec body de 201 caractères est tronqué."""
        body_201 = "A" * 201
        draft = MobileDraft(
            draft_id="d1",
            subject="S",
            recipient="r@r.com",
            body_full=body_201
        )
        assert len(draft.body_preview) == 203
        assert draft.body_preview.endswith("...")
