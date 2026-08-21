# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les entités du domaine.

Ces tests couvrent les edge cases non testés :
- Valeurs null/vides
- Formats spéciaux
- Cas limites
- Erreurs de validation
"""

import pytest
from datetime import datetime

from app.domain.entities import (
    Email,
    Draft,
    Critique,
    ProcessingResult,
    DraftStatus,
    TokenUsage,
)


# ============================================================================
# TESTS - EMAIL ENTITY
# ============================================================================

class TestEmailEntity:
    """Tests pour l'entité Email avec edge cases."""

    def test_email_minimal_valid(self):
        """Email avec uniquement les champs requis."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="test@example.com",
        )
        assert email.id == "123"
        assert email.recipients == []
        assert email.cc == []
        assert email.is_read is False

    def test_email_empty_id(self):
        """Email avec ID vide lève EmptyValueError."""
        from app.domain.exceptions import EmptyValueError
        with pytest.raises(EmptyValueError):
            Email(id="", subject="Test", body="Body", sender="sender@test.com")

    def test_email_empty_subject(self):
        """Email avec sujet vide est valide."""
        email = Email(id="123", subject="", body="Body", sender="sender@test.com")
        assert email.subject == ""

    def test_email_empty_body(self):
        """Email avec corps vide est valide."""
        email = Email(id="123", subject="Test", body="", sender="sender@test.com")
        assert email.body == ""

    def test_email_empty_sender(self):
        """Email avec expéditeur vide lève EmptyValueError."""
        from app.domain.exceptions import EmptyValueError
        with pytest.raises(EmptyValueError):
            Email(id="123", subject="Test", body="Body", sender="")

    def test_email_with_special_characters_in_subject(self):
        """Email avec caractères spéciaux dans le sujet."""
        special_subject = "Test <script>alert('xss')</script> & \"quotes\" 'apostrophe'"
        email = Email(
            id="123",
            subject=special_subject,
            body="Body",
            sender="test@example.com",
        )
        assert email.subject == special_subject

    def test_email_with_unicode_body(self):
        """Email avec caractères unicode dans le corps."""
        unicode_body = "Bonjour 🌍 Émojis et accents: é à ü ñ 中文 日本語"
        email = Email(
            id="123",
            subject="Test",
            body=unicode_body,
            sender="test@example.com",
        )
        assert email.body == unicode_body

    def test_email_with_very_long_body(self):
        """Email avec corps très long."""
        long_body = "A" * 100000  # 100k caractères
        email = Email(
            id="123",
            subject="Test",
            body=long_body,
            sender="test@example.com",
        )
        assert len(email.body) == 100000

    def test_email_is_cc_only_with_no_recipients(self):
        """is_cc_only retourne True si pas de recipients mais des cc."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="sender@test.com",
            recipients=[],
            cc=["cc@test.com"],
        )
        assert email.is_cc_only is True

    def test_email_is_cc_only_with_recipients(self):
        """is_cc_only retourne False si recipients présents."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="sender@test.com",
            recipients=["recipient@test.com"],
            cc=["cc@test.com"],
        )
        assert email.is_cc_only is False

    def test_email_is_cc_only_empty_both(self):
        """is_cc_only retourne False si recipients et cc vides."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="sender@test.com",
            recipients=[],
            cc=[],
        )
        assert email.is_cc_only is False

    def test_email_content_for_processing_format(self):
        """content_for_processing génère le bon format."""
        email = Email(
            id="123",
            subject="Sujet Test",
            body="Corps du message",
            sender="expéditeur@test.com",
        )
        content = email.content_for_processing
        assert "De: expéditeur@test.com" in content
        assert "Sujet: Sujet Test" in content
        assert "Corps du message" in content

    def test_email_content_for_processing_with_empty_fields(self):
        """content_for_processing avec sujet/body vides mais sender valide."""
        email = Email(id="123", subject="", body="", sender="test@example.com")
        content = email.content_for_processing
        assert "De: test@example.com" in content
        assert "Sujet: " in content

    def test_email_with_none_received_at(self):
        """Email avec received_at None."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="test@example.com",
            received_at=None,
        )
        assert email.received_at is None

    def test_email_with_datetime_received_at(self):
        """Email avec received_at valide."""
        now = datetime.now()
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="test@example.com",
            received_at=now,
        )
        assert email.received_at == now

    def test_email_with_thread_id(self):
        """Email avec thread_id."""
        email = Email(
            id="123",
            subject="Test",
            body="Body",
            sender="test@example.com",
            thread_id="thread-456",
        )
        assert email.thread_id == "thread-456"


# ============================================================================
# TESTS - DRAFT ENTITY
# ============================================================================

class TestDraftEntity:
    """Tests pour l'entité Draft avec edge cases."""

    def test_draft_minimal(self):
        """Draft minimal valide."""
        draft = Draft(content="Réponse")
        assert draft.content == "Réponse"
        assert draft.version == 1

    def test_draft_empty_content(self):
        """Draft avec contenu vide."""
        draft = Draft(content="")
        assert draft.content == ""

    def test_draft_with_version(self):
        """Draft avec version spécifiée."""
        draft = Draft(content="V2", version=2)
        assert draft.version == 2

    def test_draft_version_zero(self):
        """Draft avec version 0 lève InvalidBoundsError."""
        from app.domain.exceptions import InvalidBoundsError
        with pytest.raises(InvalidBoundsError):
            Draft(content="Test", version=0)

    def test_draft_version_negative(self):
        """Draft avec version négative lève InvalidBoundsError."""
        from app.domain.exceptions import InvalidBoundsError
        with pytest.raises(InvalidBoundsError):
            Draft(content="Test", version=-1)

    def test_draft_str_representation(self):
        """__str__ retourne le contenu."""
        draft = Draft(content="Mon contenu")
        assert str(draft) == "Mon contenu"

    def test_draft_with_unicode_content(self):
        """Draft avec unicode."""
        unicode_content = "Réponse avec émojis 🎉 et accents éàüñ"
        draft = Draft(content=unicode_content)
        assert draft.content == unicode_content

    def test_draft_with_html_content(self):
        """Draft avec contenu HTML (pas d'échappement côté entité)."""
        html_content = "<p>Bonjour</p><script>alert('test')</script>"
        draft = Draft(content=html_content)
        assert draft.content == html_content

    def test_draft_with_multiline_content(self):
        """Draft avec contenu multi-lignes."""
        multiline = "Ligne 1\nLigne 2\n\nLigne 4 après saut"
        draft = Draft(content=multiline)
        assert "\n" in draft.content
        assert draft.content.count("\n") == 3


# ============================================================================
# TESTS - CRITIQUE ENTITY
# ============================================================================

class TestCritiqueEntity:
    """Tests pour l'entité Critique avec edge cases."""

    def test_critique_valid_uppercase(self):
        """Critique VALID en majuscules."""
        critique = Critique.from_response("VALID")
        assert critique.is_valid is True
        assert critique.reason is None

    def test_critique_valid_lowercase(self):
        """Critique valid en minuscules."""
        critique = Critique.from_response("valid")
        assert critique.is_valid is True

    def test_critique_valid_mixed_case(self):
        """Critique Valid en mixed case."""
        critique = Critique.from_response("Valid")
        assert critique.is_valid is True

    def test_critique_valid_with_comment(self):
        """Critique VALID avec commentaire."""
        critique = Critique.from_response("VALID - Good response")
        assert critique.is_valid is True

    def test_critique_valid_with_whitespace(self):
        """Critique VALID avec espaces."""
        critique = Critique.from_response("  VALID  ")
        assert critique.is_valid is True

    def test_critique_valid_with_newlines(self):
        """Critique VALID avec retours à la ligne."""
        critique = Critique.from_response("\n\nVALID\n")
        assert critique.is_valid is True

    def test_critique_rejet_simple(self):
        """Critique REJET simple."""
        critique = Critique.from_response("REJET : Ton inapproprié")
        assert critique.is_valid is False
        assert critique.reason == "REJET : Ton inapproprié"

    def test_critique_rejet_lowercase(self):
        """Critique rejet en minuscules."""
        critique = Critique.from_response("rejet: ton trop formel")
        assert critique.is_valid is False

    def test_critique_empty_response(self):
        """Critique avec réponse vide."""
        critique = Critique.from_response("")
        assert critique.is_valid is False
        assert critique.reason == ""

    def test_critique_whitespace_only(self):
        """Critique avec espaces uniquement."""
        critique = Critique.from_response("   ")
        assert critique.is_valid is False

    def test_critique_unknown_format(self):
        """Critique avec format inconnu."""
        critique = Critique.from_response("Peut-être valide mais pas sûr")
        assert critique.is_valid is False
        assert "Peut-être" in critique.reason

    def test_critique_str_representation(self):
        """__str__ retourne la réponse brute."""
        critique = Critique(
            raw_response="VALID",
            is_valid=True,
            reason=None
        )
        assert str(critique) == "VALID"

    def test_critique_rejet_with_multiline_reason(self):
        """Critique REJET avec raison multi-lignes."""
        response = "REJET : Problème 1\nProblème 2\nProblème 3"
        critique = Critique.from_response(response)
        assert critique.is_valid is False
        assert "\n" in critique.reason

    def test_critique_almost_valid(self):
        """Critique qui ressemble à VALID mais n'en est pas."""
        critique = Critique.from_response("INVALID")
        assert critique.is_valid is False

        critique2 = Critique.from_response("NOT VALID")
        assert critique2.is_valid is False

        critique3 = Critique.from_response("VALIDATION FAILED")
        assert critique3.is_valid is True  # Commence par VALID


# ============================================================================
# TESTS - PROCESSING RESULT
# ============================================================================

class TestProcessingResult:
    """Tests pour l'entité ProcessingResult avec edge cases."""

    @pytest.fixture
    def sample_draft(self):
        """Draft de test."""
        return Draft(content="Draft content", version=1)

    @pytest.fixture
    def valid_critique(self):
        """Critique valide."""
        return Critique(raw_response="VALID", is_valid=True)

    @pytest.fixture
    def invalid_critique(self):
        """Critique invalide."""
        return Critique(raw_response="REJET : Raison", is_valid=False, reason="REJET : Raison")

    def test_processing_result_validated_v1(self, sample_draft, valid_critique):
        """ProcessingResult validé en V1."""
        result = ProcessingResult(
            email_id="email-123",
            draft_v1=sample_draft,
            critique=valid_critique,
            draft_final=sample_draft,
            status=DraftStatus.VALIDATED_V1,
        )
        assert result.was_corrected is False
        assert result.status == DraftStatus.VALIDATED_V1

    def test_processing_result_corrected_v2(self, sample_draft, invalid_critique):
        """ProcessingResult corrigé en V2."""
        draft_v2 = Draft(content="Draft V2", version=2)
        result = ProcessingResult(
            email_id="email-123",
            draft_v1=sample_draft,
            critique=invalid_critique,
            draft_final=draft_v2,
            status=DraftStatus.CORRECTED_V2,
        )
        assert result.was_corrected is True
        assert result.status == DraftStatus.CORRECTED_V2

    def test_processing_result_rejected_status(self, sample_draft, invalid_critique):
        """ProcessingResult avec statut REJECTED."""
        result = ProcessingResult(
            email_id="email-123",
            draft_v1=sample_draft,
            critique=invalid_critique,
            draft_final=sample_draft,
            status=DraftStatus.REJECTED,
        )
        assert result.was_corrected is False
        assert result.status == DraftStatus.REJECTED

    def test_processing_result_pending_status(self, sample_draft, valid_critique):
        """ProcessingResult avec statut PENDING."""
        result = ProcessingResult(
            email_id="email-123",
            draft_v1=sample_draft,
            critique=valid_critique,
            draft_final=sample_draft,
            status=DraftStatus.PENDING,
        )
        assert result.was_corrected is False


# ============================================================================
# TESTS - DRAFT STATUS ENUM
# ============================================================================

class TestDraftStatus:
    """Tests pour l'enum DraftStatus."""

    def test_all_statuses_exist(self):
        """Vérifie que tous les statuts existent."""
        assert DraftStatus.PENDING.value == "pending"
        assert DraftStatus.VALIDATED_V1.value == "validated_v1"
        assert DraftStatus.CORRECTED_V2.value == "corrected_v2"
        assert DraftStatus.REJECTED.value == "rejected"

    def test_status_from_value(self):
        """Création depuis valeur string."""
        assert DraftStatus("pending") == DraftStatus.PENDING
        assert DraftStatus("validated_v1") == DraftStatus.VALIDATED_V1

    def test_invalid_status_raises(self):
        """Statut invalide lève une erreur."""
        with pytest.raises(ValueError):
            DraftStatus("invalid_status")


# ============================================================================
# TESTS - TOKEN USAGE
# ============================================================================

class TestTokenUsageEntity:
    """Tests pour l'entité TokenUsage avec edge cases."""

    def test_token_usage_initial_state(self):
        """État initial à zéro."""
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total == 0
        assert usage.model == ""
        assert usage.cost == 0.0

    def test_token_usage_aliases(self):
        """Les alias input/output fonctionnent."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.input == 100
        assert usage.output == 50

    def test_token_usage_add_without_model(self):
        """Add sans modèle."""
        usage = TokenUsage()
        usage.add(100, 50)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.model == ""

    def test_token_usage_add_with_model(self):
        """Add avec modèle."""
        usage = TokenUsage()
        usage.add(100, 50, "claude-sonnet-4-20250514")
        assert usage.model == "claude-sonnet-4-20250514"

    def test_token_usage_add_accumulates(self):
        """Add accumule les tokens."""
        usage = TokenUsage()
        usage.add(100, 50)
        usage.add(200, 100)
        assert usage.input_tokens == 300
        assert usage.output_tokens == 150
        assert usage.total == 450

    def test_token_usage_reset(self):
        """Reset remet tout à zéro."""
        usage = TokenUsage(input_tokens=100, output_tokens=50, model="test")
        usage.reset()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.model == ""

    def test_token_usage_cost_sonnet(self):
        """Coût pour Sonnet."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=100_000,
            model="claude-sonnet-4-20250514"
        )
        # $3/M input + $15/M output = 3 + 1.5 = 4.5
        assert usage.cost == pytest.approx(4.5)

    def test_token_usage_cost_haiku(self):
        """Coût pour Haiku 3.5."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=100_000,
            model="claude-3-5-haiku-20241022"
        )
        # Prix à jour : $0.80/M input + $4.00/M output = 0.80 + 0.40 = 1.20
        assert usage.cost == pytest.approx(1.2)

    def test_token_usage_cost_opus(self):
        """Coût pour Opus."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=100_000,
            model="claude-opus-4-20250514"
        )
        # $15/M input + $75/M output = 15 + 7.5 = 22.5
        assert usage.cost == pytest.approx(22.5)

    def test_token_usage_cost_ollama_free(self):
        """Coût pour Ollama (gratuit)."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=100_000,
            model="mixtral:latest"
        )
        assert usage.cost == 0.0

    def test_token_usage_cost_unknown_model(self):
        """Modèle inconnu utilise coût Sonnet par défaut."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=100_000,
            model="unknown-model"
        )
        # Défaut Sonnet: $3/M input + $15/M output = 4.5
        assert usage.cost == pytest.approx(4.5)

    def test_token_usage_cost_zero_tokens(self):
        """Coût avec zéro tokens."""
        usage = TokenUsage(
            input_tokens=0,
            output_tokens=0,
            model="claude-opus-4-20250514"
        )
        assert usage.cost == 0.0

    def test_token_usage_cost_empty_model(self):
        """Coût avec modèle vide (utilise défaut)."""
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=100_000,
            model=""
        )
        # Défaut Sonnet
        assert usage.cost == pytest.approx(4.5)

    def test_token_usage_str_with_cost(self):
        """__str__ avec coût."""
        usage = TokenUsage(
            input_tokens=1000,
            output_tokens=500,
            model="claude-sonnet-4-20250514"
        )
        result = str(usage)
        assert "1,000↓" in result
        assert "500↑" in result
        assert "$" in result
        assert "sonnet" in result

    def test_token_usage_str_ollama_no_cost(self):
        """__str__ Ollama sans coût affiché."""
        usage = TokenUsage(
            input_tokens=1000,
            output_tokens=500,
            model="mixtral:latest"
        )
        result = str(usage)
        assert "1,000↓" in result
        # Le $ peut ne pas apparaître si coût = 0

    def test_token_usage_str_no_model(self):
        """__str__ sans modèle."""
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        result = str(usage)
        assert "1,000↓" in result
        assert "500↑" in result

    def test_token_usage_large_numbers(self):
        """Grands nombres de tokens."""
        usage = TokenUsage(
            input_tokens=100_000_000,
            output_tokens=50_000_000,
            model="claude-sonnet-4-20250514"
        )
        assert usage.total == 150_000_000
        # 100M * $3/M + 50M * $15/M = 300 + 750 = 1050
        assert usage.cost == pytest.approx(1050.0)

    def test_token_usage_negative_tokens_edge_case(self):
        """Tokens négatifs lèvent maintenant InvalidBoundsError."""
        from app.domain.exceptions import InvalidBoundsError
        with pytest.raises(InvalidBoundsError):
            TokenUsage(input_tokens=-100, output_tokens=-50)


# ============================================================================
# TESTS - PUSH NOTIFICATION ENTITIES
# ============================================================================

from app.domain.entities import (
    DeviceToken,
    DevicePlatform,
    PushNotification,
    PushNotificationStatus,
    PushNotificationCategory,
    PushNotificationRecord,
)


class TestDeviceToken:
    """Tests pour l'entité DeviceToken avec edge cases."""

    def test_device_token_minimal_valid(self):
        """DeviceToken avec champs minimaux."""
        token = DeviceToken(token="abc123", platform=DevicePlatform.IOS)
        assert token.token == "abc123"
        assert token.platform == DevicePlatform.IOS
        assert token.is_active is True
        assert token.user_id is None

    def test_device_token_empty_token_raises(self):
        """DeviceToken avec token vide lève une erreur."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token="", platform=DevicePlatform.IOS)

    def test_device_token_platform_from_string(self):
        """DeviceToken avec platform string se convertit."""
        token = DeviceToken(token="abc123", platform="android")
        assert token.platform == DevicePlatform.ANDROID

    def test_device_token_invalid_platform_raises(self):
        """DeviceToken avec platform invalide lève une erreur."""
        with pytest.raises(ValueError):
            DeviceToken(token="abc123", platform="invalid_platform")

    def test_device_token_all_platforms(self):
        """Test toutes les plateformes supportées."""
        for platform in DevicePlatform:
            token = DeviceToken(token="abc", platform=platform)
            assert token.platform == platform

    def test_device_token_to_dict(self):
        """Sérialisation vers dictionnaire."""
        token = DeviceToken(
            token="abc123",
            platform=DevicePlatform.ANDROID,
            user_id="user-1",
            device_name="Mon Téléphone",
        )
        data = token.to_dict()
        assert data["token"] == "abc123"
        assert data["platform"] == "android"
        assert data["user_id"] == "user-1"
        assert data["device_name"] == "Mon Téléphone"
        assert "created_at" in data

    def test_device_token_from_dict(self):
        """Désérialisation depuis dictionnaire."""
        data = {
            "token": "xyz789",
            "platform": "ios",
            "user_id": "user-2",
            "created_at": "2024-01-15T10:30:00",
            "is_active": False,
        }
        token = DeviceToken.from_dict(data)
        assert token.token == "xyz789"
        assert token.platform == DevicePlatform.IOS
        assert token.is_active is False

    def test_device_token_from_dict_minimal(self):
        """Désérialisation avec champs minimaux."""
        data = {"token": "abc", "platform": "web"}
        token = DeviceToken.from_dict(data)
        assert token.token == "abc"
        assert token.platform == DevicePlatform.WEB
        assert token.is_active is True

    def test_device_token_with_unicode_device_name(self):
        """DeviceToken avec nom unicode."""
        token = DeviceToken(
            token="abc123",
            platform=DevicePlatform.IOS,
            device_name="iPhone de François 📱"
        )
        assert "François" in token.device_name
        assert "📱" in token.device_name


class TestPushNotification:
    """Tests pour l'entité PushNotification avec edge cases."""

    def test_push_notification_minimal_valid(self):
        """PushNotification avec champs minimaux."""
        notif = PushNotification(title="Hello", body="World")
        assert notif.title == "Hello"
        assert notif.body == "World"
        assert notif.category == PushNotificationCategory.INFO

    def test_push_notification_empty_title_raises(self):
        """PushNotification avec titre vide lève une erreur."""
        with pytest.raises(ValueError, match="title cannot be empty"):
            PushNotification(title="", body="Content")

    def test_push_notification_whitespace_title_raises(self):
        """PushNotification avec titre espaces uniquement lève une erreur."""
        with pytest.raises(ValueError, match="title cannot be empty"):
            PushNotification(title="   ", body="Content")

    def test_push_notification_empty_body_raises(self):
        """PushNotification avec body vide lève une erreur."""
        with pytest.raises(ValueError, match="body cannot be empty"):
            PushNotification(title="Title", body="")

    def test_push_notification_whitespace_body_raises(self):
        """PushNotification avec body espaces uniquement lève une erreur."""
        with pytest.raises(ValueError, match="body cannot be empty"):
            PushNotification(title="Title", body="   ")

    def test_push_notification_category_from_string(self):
        """PushNotification avec category string se convertit."""
        notif = PushNotification(title="T", body="B", category="draft.created")
        assert notif.category == PushNotificationCategory.DRAFT_CREATED

    def test_push_notification_invalid_category_raises(self):
        """PushNotification avec category invalide lève une erreur."""
        with pytest.raises(ValueError):
            PushNotification(title="T", body="B", category="invalid.category")

    def test_push_notification_all_categories(self):
        """Test toutes les catégories de notification."""
        for cat in PushNotificationCategory:
            notif = PushNotification(title="T", body="B", category=cat)
            assert notif.category == cat

    def test_push_notification_with_data(self):
        """PushNotification avec données additionnelles."""
        notif = PushNotification(
            title="Alert",
            body="Something happened",
            data={"email_id": "123", "action": "view"}
        )
        assert notif.data["email_id"] == "123"

    def test_push_notification_with_badge(self):
        """PushNotification avec badge."""
        notif = PushNotification(title="T", body="B", badge=5)
        assert notif.badge == 5

    def test_push_notification_with_zero_badge(self):
        """PushNotification avec badge zéro (reset badge)."""
        notif = PushNotification(title="T", body="B", badge=0)
        assert notif.badge == 0

    def test_push_notification_priority_values(self):
        """PushNotification avec différentes priorités."""
        for priority in ["low", "normal", "high"]:
            notif = PushNotification(title="T", body="B", priority=priority)
            assert notif.priority == priority

    def test_push_notification_to_dict(self):
        """Sérialisation vers dictionnaire."""
        notif = PushNotification(
            title="Nouveau brouillon",
            body="Vous avez un brouillon en attente",
            category=PushNotificationCategory.DRAFT_CREATED,
            data={"draft_id": "d123"},
            badge=3,
        )
        data = notif.to_dict()
        assert data["title"] == "Nouveau brouillon"
        assert data["category"] == "draft.created"
        assert data["badge"] == 3
        assert data["data"]["draft_id"] == "d123"

    def test_push_notification_with_unicode_content(self):
        """PushNotification avec contenu unicode."""
        notif = PushNotification(
            title="Alerte 🔔",
            body="Émail de François reçu! 中文"
        )
        assert "🔔" in notif.title
        assert "François" in notif.body


class TestPushNotificationRecord:
    """Tests pour l'entité PushNotificationRecord avec edge cases."""

    def test_push_notification_record_minimal(self):
        """PushNotificationRecord avec champs minimaux."""
        notif = PushNotification(title="T", body="B")
        record = PushNotificationRecord(
            notification=notif,
            device_token="token123"
        )
        assert record.status == PushNotificationStatus.PENDING
        assert record.message_id is None

    def test_push_notification_record_all_statuses(self):
        """Test tous les statuts de notification."""
        notif = PushNotification(title="T", body="B")
        for status in PushNotificationStatus:
            record = PushNotificationRecord(
                notification=notif,
                device_token="token",
                status=status
            )
            assert record.status == status

    def test_push_notification_record_to_dict(self):
        """Sérialisation vers dictionnaire."""
        notif = PushNotification(title="T", body="B")
        record = PushNotificationRecord(
            notification=notif,
            device_token="token123",
            status=PushNotificationStatus.SENT,
            message_id="msg-456"
        )
        data = record.to_dict()
        assert data["device_token"] == "token123"
        assert data["status"] == "sent"
        assert data["message_id"] == "msg-456"
        assert "notification" in data

    def test_push_notification_record_with_error(self):
        """PushNotificationRecord avec erreur."""
        notif = PushNotification(title="T", body="B")
        record = PushNotificationRecord(
            notification=notif,
            device_token="token",
            status=PushNotificationStatus.FAILED,
            error_message="Device not registered"
        )
        assert record.error_message == "Device not registered"


# ============================================================================
# TESTS - DRAFT INPUT ENTITIES
# ============================================================================

from app.domain.entities import (
    DraftInput,
    DraftInputTone,
    CompletedDraft,
)


class TestDraftInput:
    """Tests pour l'entité DraftInput avec edge cases."""

    def test_draft_input_is_draft_input_with_prefix(self):
        """is_draft_input détecte les préfixes connus (case insensitive)."""
        assert DraftInput.is_draft_input("Brouillon : mes idées") is True
        assert DraftInput.is_draft_input("Draft: my ideas") is True
        assert DraftInput.is_draft_input("draft : something") is True
        assert DraftInput.is_draft_input("BROUILLON: test") is True  # case insensitive

    def test_draft_input_is_draft_input_with_bullets(self):
        """is_draft_input détecte les bullet points."""
        text = """- Point 1
- Point 2
- Point 3"""
        assert DraftInput.is_draft_input(text) is True

    def test_draft_input_is_draft_input_with_numbered_list(self):
        """is_draft_input détecte les listes numérotées."""
        text = """1. Premier point
2. Deuxième point
3. Troisième point"""
        assert DraftInput.is_draft_input(text) is True

    def test_draft_input_is_draft_input_normal_text(self):
        """is_draft_input retourne False pour texte normal."""
        text = "Bonjour, ceci est un email normal sans bullet points."
        assert DraftInput.is_draft_input(text) is False

    def test_draft_input_is_draft_input_mixed_content(self):
        """is_draft_input avec contenu mixte."""
        text = """Intro text
- Bullet 1
Normal line
- Bullet 2"""
        # Moins de 50% bullets
        assert DraftInput.is_draft_input(text) is True  # 50% bullets

    def test_draft_input_is_draft_input_empty_text(self):
        """is_draft_input avec texte vide."""
        assert DraftInput.is_draft_input("") is False
        assert DraftInput.is_draft_input("   ") is False

    def test_draft_input_from_raw_text_extracts_recipient(self):
        """from_raw_text extrait le destinataire."""
        text = "Brouillon : email à Jean-Pierre pour la réunion"
        draft_input = DraftInput.from_raw_text(text)
        assert draft_input.recipient is not None
        # Le préfixe est nettoyé
        assert "Jean" in draft_input.recipient or draft_input.recipient == "Pierre"

    def test_draft_input_from_raw_text_extracts_tone_urgent(self):
        """from_raw_text détecte le ton urgent."""
        text = "Draft: urgent reminder about deadline"
        draft_input = DraftInput.from_raw_text(text)
        assert draft_input.tone == DraftInputTone.URGENT

    def test_draft_input_from_raw_text_extracts_tone_formal(self):
        """from_raw_text détecte le ton formel."""
        text = "Brouillon: email formel professionnel"
        draft_input = DraftInput.from_raw_text(text)
        assert draft_input.tone == DraftInputTone.FORMAL

    def test_draft_input_from_raw_text_extracts_tone_friendly(self):
        """from_raw_text détecte le ton amical."""
        text = "Brouillon: message amical et sympathique"
        draft_input = DraftInput.from_raw_text(text)
        assert draft_input.tone == DraftInputTone.FRIENDLY

    def test_draft_input_from_raw_text_default_tone(self):
        """from_raw_text retourne ton neutre par défaut."""
        text = "Brouillon: simple email"
        draft_input = DraftInput.from_raw_text(text)
        assert draft_input.tone == DraftInputTone.NEUTRAL

    def test_draft_input_from_raw_text_extracts_key_points(self):
        """from_raw_text extrait les points clés."""
        text = """Brouillon:
- Premier point important
- Deuxième point
- Troisième point"""
        draft_input = DraftInput.from_raw_text(text)
        assert len(draft_input.key_points) == 3
        assert "Premier point important" in draft_input.key_points[0]

    def test_draft_input_from_raw_text_extracts_subject(self):
        """from_raw_text extrait le sujet."""
        text = "Brouillon: sujet: Réunion de demain\n- Point 1"
        draft_input = DraftInput.from_raw_text(text)
        assert draft_input.subject_hint is not None

    def test_draft_input_has_enough_context(self):
        """has_enough_context vérifie les points clés."""
        draft = DraftInput(raw_input="test", key_points=[])
        assert draft.has_enough_context is False

        draft2 = DraftInput(raw_input="test", key_points=["Point 1"])
        assert draft2.has_enough_context is True

    def test_draft_input_tones_enum(self):
        """Test tous les tons disponibles."""
        assert DraftInputTone.FORMAL.value == "formal"
        assert DraftInputTone.FRIENDLY.value == "friendly"
        assert DraftInputTone.URGENT.value == "urgent"
        assert DraftInputTone.CONCILIATORY.value == "conciliatory"
        assert DraftInputTone.NEUTRAL.value == "neutral"


class TestCompletedDraft:
    """Tests pour l'entité CompletedDraft avec edge cases."""

    def test_completed_draft_minimal(self):
        """CompletedDraft avec champs minimaux."""
        draft = CompletedDraft(subject="Sujet", body="Corps")
        assert draft.subject == "Sujet"
        assert draft.body == "Corps"
        assert draft.tone_used == DraftInputTone.NEUTRAL

    def test_completed_draft_str_format(self):
        """__str__ génère le bon format."""
        draft = CompletedDraft(subject="Test Sujet", body="Corps du message")
        result = str(draft)
        assert "Objet : Test Sujet" in result
        assert "Corps du message" in result

    def test_completed_draft_str_empty_subject(self):
        """__str__ avec sujet vide."""
        draft = CompletedDraft(subject="", body="Corps")
        result = str(draft)
        # Le sujet vide est quand même présent
        assert "Corps" in result

    def test_completed_draft_formatted_output(self):
        """formatted_output inclut les séparateurs et instructions."""
        draft = CompletedDraft(subject="S", body="B")
        output = draft.formatted_output
        assert "---" in output
        assert "courriel rédigé" in output
        assert "modifier" in output

    def test_completed_draft_with_unicode(self):
        """CompletedDraft avec unicode."""
        draft = CompletedDraft(
            subject="Réunion: 日本語",
            body="Bonjour, émojis 🎉"
        )
        assert "日本語" in str(draft)
        assert "🎉" in str(draft)


# ============================================================================
# TESTS - WIZARD CONFIG ENTITIES
# ============================================================================

from app.domain.entities import (
    WizardConfig,
    BusinessSector,
    CompanySize,
    AgentActivation,
    KnowledgeBaseConfig,
)


class TestWizardConfig:
    """Tests pour l'entité WizardConfig avec edge cases."""

    def test_wizard_config_minimal(self):
        """WizardConfig avec champs minimaux."""
        config = WizardConfig(config_id="cfg-1", company_name="Test Corp")
        assert config.config_id == "cfg-1"
        assert config.company_name == "Test Corp"
        assert config.sector == BusinessSector.OTHER
        assert config.size == CompanySize.SMB

    def test_wizard_config_all_sectors(self):
        """Test tous les secteurs d'activité."""
        for sector in BusinessSector:
            config = WizardConfig(
                config_id="cfg",
                company_name="Test",
                sector=sector
            )
            assert config.sector == sector

    def test_wizard_config_all_sizes(self):
        """Test toutes les tailles d'entreprise."""
        for size in CompanySize:
            config = WizardConfig(
                config_id="cfg",
                company_name="Test",
                size=size
            )
            assert config.size == size

    def test_wizard_config_activate_agent_new(self):
        """activate_agent ajoute un nouvel agent."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.activate_agent("agent-1", priority=80)
        assert len(config.agents) == 1
        assert config.agents[0].agent_id == "agent-1"
        assert config.agents[0].priority == 80
        assert config.agents[0].enabled is True

    def test_wizard_config_activate_agent_existing(self):
        """activate_agent met à jour un agent existant."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.activate_agent("agent-1", priority=50)
        config.activate_agent("agent-1", priority=90)
        assert len(config.agents) == 1
        assert config.agents[0].priority == 90

    def test_wizard_config_deactivate_agent(self):
        """deactivate_agent désactive un agent."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.activate_agent("agent-1")
        config.deactivate_agent("agent-1")
        assert config.agents[0].enabled is False

    def test_wizard_config_deactivate_nonexistent_agent(self):
        """deactivate_agent sur agent inexistant ne fait rien."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.deactivate_agent("nonexistent")  # Pas d'erreur
        assert len(config.agents) == 0

    def test_wizard_config_is_agent_active(self):
        """is_agent_active vérifie l'activation."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        assert config.is_agent_active("agent-1") is False
        config.activate_agent("agent-1")
        assert config.is_agent_active("agent-1") is True
        config.deactivate_agent("agent-1")
        assert config.is_agent_active("agent-1") is False

    def test_wizard_config_get_active_agents_sorted(self):
        """get_active_agents retourne les agents triés par priorité."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        config.activate_agent("agent-low", priority=10)
        config.activate_agent("agent-high", priority=100)
        config.activate_agent("agent-mid", priority=50)
        config.deactivate_agent("agent-mid")

        active = config.get_active_agents()
        assert len(active) == 2
        assert active[0].agent_id == "agent-high"
        assert active[1].agent_id == "agent-low"

    def test_wizard_config_mark_complete(self):
        """mark_complete met à jour is_complete et updated_at."""
        config = WizardConfig(config_id="cfg", company_name="Test")
        assert config.is_complete is False
        old_updated = config.updated_at
        config.mark_complete()
        assert config.is_complete is True
        assert config.updated_at >= old_updated

    def test_wizard_config_to_dict(self):
        """Sérialisation vers dictionnaire."""
        config = WizardConfig(
            config_id="cfg-123",
            company_name="Acme Inc",
            sector=BusinessSector.TECH,
            size=CompanySize.STARTUP,
        )
        config.activate_agent("drafter")
        data = config.to_dict()
        assert data["config_id"] == "cfg-123"
        assert data["sector"] == "tech"
        assert data["size"] == "startup"
        assert len(data["agents"]) == 1

    def test_wizard_config_from_dict(self):
        """Désérialisation depuis dictionnaire."""
        data = {
            "config_id": "cfg-456",
            "company_name": "Test Corp",
            "sector": "finance",
            "size": "enterprise",
            "primary_language": "en",
            "supported_languages": ["en", "fr", "de"],
            "agents": [
                {"agent_id": "agent-1", "enabled": True, "priority": 75}
            ],
            "knowledge_base": {
                "company_name": "Test",
                "forbidden_topics": ["legal", "confidential"]
            },
            "is_complete": True,
        }
        config = WizardConfig.from_dict(data)
        assert config.config_id == "cfg-456"
        assert config.sector == BusinessSector.FINANCE
        assert config.size == CompanySize.ENTERPRISE
        assert len(config.agents) == 1
        assert config.is_complete is True
        assert "legal" in config.knowledge_base.forbidden_topics

    def test_wizard_config_from_dict_minimal(self):
        """Désérialisation avec champs minimaux."""
        data = {"config_id": "cfg"}
        config = WizardConfig.from_dict(data)
        assert config.config_id == "cfg"
        assert config.company_name == ""
        assert config.sector == BusinessSector.OTHER


class TestAgentActivation:
    """Tests pour l'entité AgentActivation."""

    def test_agent_activation_defaults(self):
        """AgentActivation avec valeurs par défaut."""
        activation = AgentActivation(agent_id="test-agent")
        assert activation.agent_id == "test-agent"
        assert activation.enabled is True
        assert activation.priority == 50
        assert activation.custom_prompt_override is None

    def test_agent_activation_with_override(self):
        """AgentActivation avec override de prompt."""
        activation = AgentActivation(
            agent_id="custom",
            custom_prompt_override="Custom system prompt"
        )
        assert activation.custom_prompt_override == "Custom system prompt"


class TestKnowledgeBaseConfig:
    """Tests pour l'entité KnowledgeBaseConfig."""

    def test_knowledge_base_config_defaults(self):
        """KnowledgeBaseConfig avec valeurs par défaut."""
        kb = KnowledgeBaseConfig()
        assert kb.company_name == ""
        assert kb.forbidden_topics == []
        assert kb.custom_signatures == {}
        assert kb.faq_entries == {}

    def test_knowledge_base_config_with_data(self):
        """KnowledgeBaseConfig avec données."""
        kb = KnowledgeBaseConfig(
            company_name="Acme",
            company_description="Leading provider",
            forbidden_topics=["pricing", "competitors"],
            custom_signatures={"default": "Best regards,\nJohn"},
            faq_entries={"hours": "We're open 9-5"}
        )
        assert kb.company_name == "Acme"
        assert len(kb.forbidden_topics) == 2
        assert "default" in kb.custom_signatures


# ============================================================================
# TESTS - MARKETPLACE ENTITIES
# ============================================================================

from app.domain.entities import (
    AgentCategory,
    AgentPricingModel,
    AgentStatus,
    InstallationStatus,
    AgentPricing,
    MarketplaceAgent,
    AgentInstallation,
    AgentReview,
    MarketplaceSearchQuery,
    MarketplaceSearchResult,
)


class TestMarketplaceAgent:
    """Tests pour l'entité MarketplaceAgent avec edge cases."""

    def test_marketplace_agent_defaults(self):
        """MarketplaceAgent avec valeurs par défaut."""
        agent = MarketplaceAgent()
        assert agent.id is not None  # UUID généré
        assert agent.name == ""
        assert agent.category == AgentCategory.CUSTOM
        assert agent.status == AgentStatus.DRAFT

    def test_marketplace_agent_is_free(self):
        """is_free vérifie la gratuité."""
        agent = MarketplaceAgent()
        assert agent.is_free() is True

        agent.pricing = AgentPricing(model=AgentPricingModel.ONE_TIME, price_cents=999)
        assert agent.is_free() is False

    def test_marketplace_agent_is_published(self):
        """is_published vérifie le statut."""
        agent = MarketplaceAgent(status=AgentStatus.DRAFT)
        assert agent.is_published() is False

        agent.status = AgentStatus.PUBLISHED
        assert agent.is_published() is True

    def test_marketplace_agent_generate_slug(self):
        """generate_slug crée un slug URL-friendly."""
        agent = MarketplaceAgent(name="Customer Support Agent Pro")
        slug = agent.generate_slug()
        assert slug == "customer-support-agent-pro"

    def test_marketplace_agent_generate_slug_special_chars(self):
        """generate_slug gère les caractères spéciaux."""
        agent = MarketplaceAgent(name="Agent @#$% Spécial!")
        slug = agent.generate_slug()
        assert "@" not in slug
        assert "#" not in slug
        assert "-" in slug or slug == "agent-sp-cial"

    def test_marketplace_agent_generate_slug_empty_name(self):
        """generate_slug avec nom vide."""
        agent = MarketplaceAgent(name="")
        slug = agent.generate_slug()
        assert slug == ""

    def test_marketplace_agent_all_categories(self):
        """Test toutes les catégories d'agents."""
        for cat in AgentCategory:
            agent = MarketplaceAgent(category=cat)
            assert agent.category == cat

    def test_marketplace_agent_all_statuses(self):
        """Test tous les statuts d'agents."""
        for status in AgentStatus:
            agent = MarketplaceAgent(status=status)
            assert agent.status == status


class TestAgentPricing:
    """Tests pour l'entité AgentPricing."""

    def test_agent_pricing_defaults(self):
        """AgentPricing avec valeurs par défaut."""
        pricing = AgentPricing()
        assert pricing.model == AgentPricingModel.FREE
        assert pricing.price_cents == 0
        assert pricing.currency == "EUR"

    def test_agent_pricing_subscription(self):
        """AgentPricing pour abonnement."""
        pricing = AgentPricing(
            model=AgentPricingModel.SUBSCRIPTION,
            price_cents=2999,  # 29.99€/mois
            billing_period_days=30,
            trial_days=14
        )
        assert pricing.model == AgentPricingModel.SUBSCRIPTION
        assert pricing.billing_period_days == 30
        assert pricing.trial_days == 14

    def test_agent_pricing_usage_based(self):
        """AgentPricing basé sur l'usage."""
        pricing = AgentPricing(
            model=AgentPricingModel.USAGE_BASED,
            usage_price_per_call_cents=5
        )
        assert pricing.usage_price_per_call_cents == 5


class TestAgentInstallation:
    """Tests pour l'entité AgentInstallation avec edge cases."""

    def test_agent_installation_defaults(self):
        """AgentInstallation avec valeurs par défaut."""
        install = AgentInstallation(agent_id="agent-1", organization_id="org-1")
        assert install.status == InstallationStatus.ACTIVE
        assert install.is_active() is True

    def test_agent_installation_is_active_expired(self):
        """is_active retourne False si expiré."""
        from datetime import timedelta
        install = AgentInstallation(
            agent_id="agent-1",
            organization_id="org-1",
            expires_at=datetime.now() - timedelta(days=1)
        )
        assert install.is_active() is False

    def test_agent_installation_is_active_future_expiry(self):
        """is_active retourne True si expiration future."""
        from datetime import timedelta
        install = AgentInstallation(
            agent_id="agent-1",
            organization_id="org-1",
            expires_at=datetime.now() + timedelta(days=30)
        )
        assert install.is_active() is True

    def test_agent_installation_is_active_suspended(self):
        """is_active retourne False si suspendu."""
        install = AgentInstallation(
            agent_id="agent-1",
            organization_id="org-1",
            status=InstallationStatus.SUSPENDED
        )
        assert install.is_active() is False

    def test_agent_installation_all_statuses(self):
        """Test tous les statuts d'installation."""
        for status in InstallationStatus:
            install = AgentInstallation(
                agent_id="a",
                organization_id="o",
                status=status
            )
            assert install.status == status


class TestAgentReview:
    """Tests pour l'entité AgentReview."""

    def test_agent_review_defaults(self):
        """AgentReview avec valeurs par défaut."""
        review = AgentReview(agent_id="agent-1", organization_id="org-1")
        assert review.rating == 5
        assert review.is_approved is False
        assert review.is_verified_purchase is False

    def test_agent_review_with_response(self):
        """AgentReview avec réponse du publisher."""
        review = AgentReview(
            agent_id="agent-1",
            organization_id="org-1",
            rating=4,
            content="Great agent!",
            publisher_response="Thank you!",
            publisher_response_at=datetime.now()
        )
        assert review.publisher_response == "Thank you!"
        assert review.publisher_response_at is not None


class TestMarketplaceSearchQuery:
    """Tests pour l'entité MarketplaceSearchQuery."""

    def test_search_query_defaults(self):
        """MarketplaceSearchQuery avec valeurs par défaut."""
        query = MarketplaceSearchQuery()
        assert query.query == ""
        assert query.page == 1
        assert query.per_page == 20
        assert query.sort_by == "popularity"

    def test_search_query_with_filters(self):
        """MarketplaceSearchQuery avec filtres."""
        query = MarketplaceSearchQuery(
            query="support",
            category=AgentCategory.CUSTOMER_SERVICE,
            pricing_models=[AgentPricingModel.FREE, AgentPricingModel.SUBSCRIPTION],
            min_rating=4.0,
            verified_only=True
        )
        assert query.category == AgentCategory.CUSTOMER_SERVICE
        assert len(query.pricing_models) == 2
        assert query.min_rating == 4.0


class TestMarketplaceSearchResult:
    """Tests pour l'entité MarketplaceSearchResult."""

    def test_search_result_empty(self):
        """MarketplaceSearchResult vide."""
        result = MarketplaceSearchResult()
        assert result.agents == []
        assert result.total_count == 0

    def test_search_result_with_agents(self):
        """MarketplaceSearchResult avec résultats."""
        agents = [MarketplaceAgent(name="Agent 1"), MarketplaceAgent(name="Agent 2")]
        result = MarketplaceSearchResult(
            agents=agents,
            total_count=10,
            page=1,
            per_page=2,
            total_pages=5
        )
        assert len(result.agents) == 2
        assert result.total_pages == 5


# ============================================================================
# TESTS - FINE-TUNING ENTITIES
# ============================================================================

from app.domain.entities import (
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


class TestUserCorrection:
    """Tests pour l'entité UserCorrection avec edge cases."""

    def test_user_correction_create(self):
        """UserCorrection.create génère un ID."""
        correction = UserCorrection.create(
            draft_id="draft-1",
            original_text="Bonjour",
            corrected_text="Bonjour à tous"
        )
        assert correction.id is not None
        assert correction.draft_id == "draft-1"

    def test_user_correction_has_significant_changes_true(self):
        """has_significant_changes avec changements significatifs."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="Short text",
            corrected_text="Completely different and much longer text here"
        )
        assert correction.has_significant_changes() is True

    def test_user_correction_has_significant_changes_false(self):
        """has_significant_changes avec changements mineurs."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="This is a test text that is quite long",
            corrected_text="This is a test text that is quite lonG"  # 1 char diff
        )
        assert correction.has_significant_changes(min_diff_ratio=0.05) is False

    def test_user_correction_has_significant_changes_empty_original(self):
        """has_significant_changes avec original vide."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="",
            corrected_text="New content"
        )
        assert correction.has_significant_changes() is True

    def test_user_correction_has_significant_changes_both_empty(self):
        """has_significant_changes avec les deux vides."""
        correction = UserCorrection(
            id="c1",
            draft_id="d1",
            original_text="",
            corrected_text=""
        )
        assert correction.has_significant_changes() is False


class TestUserFeedback:
    """Tests pour l'entité UserFeedback avec edge cases."""

    def test_user_feedback_create_positive(self):
        """UserFeedback.create avec note positive."""
        feedback = UserFeedback.create(draft_id="d1", rating=5)
        assert feedback.sentiment == FeedbackSentiment.POSITIVE
        assert feedback.id is not None

    def test_user_feedback_create_negative(self):
        """UserFeedback.create avec note négative."""
        feedback = UserFeedback.create(draft_id="d1", rating=2)
        assert feedback.sentiment == FeedbackSentiment.NEGATIVE

    def test_user_feedback_create_neutral(self):
        """UserFeedback.create avec note neutre."""
        feedback = UserFeedback.create(draft_id="d1", rating=3)
        assert feedback.sentiment == FeedbackSentiment.NEUTRAL

    def test_user_feedback_create_invalid_rating_too_low(self):
        """UserFeedback.create avec note trop basse lève erreur."""
        with pytest.raises(ValueError, match="between 1 and 5"):
            UserFeedback.create(draft_id="d1", rating=0)

    def test_user_feedback_create_invalid_rating_too_high(self):
        """UserFeedback.create avec note trop haute lève erreur."""
        with pytest.raises(ValueError, match="between 1 and 5"):
            UserFeedback.create(draft_id="d1", rating=6)

    def test_user_feedback_create_with_tags(self):
        """UserFeedback.create avec tags."""
        feedback = UserFeedback.create(
            draft_id="d1",
            rating=4,
            tags=["helpful", "professional"]
        )
        assert len(feedback.tags) == 2


class TestCorrectionPattern:
    """Tests pour l'entité CorrectionPattern avec edge cases."""

    def test_correction_pattern_create(self):
        """CorrectionPattern.create génère un ID."""
        pattern = CorrectionPattern.create(
            pattern_type=CorrectionType.TONE,
            original_pattern="Salut",
            replacement="Bonjour"
        )
        assert pattern.id is not None
        assert pattern.confidence == 0.5

    def test_correction_pattern_increment_occurrence(self):
        """increment_occurrence met à jour compteur et confiance."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.TONE,
            original_pattern="a",
            replacement="b",
            occurrences=5,
            confidence=0.5
        )
        pattern.increment_occurrence()
        assert pattern.occurrences == 6
        assert pattern.confidence == 0.6
        assert pattern.last_used is not None

    def test_correction_pattern_confidence_max(self):
        """confidence ne dépasse pas 1.0."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.TONE,
            original_pattern="a",
            replacement="b",
            occurrences=9,
            confidence=0.9
        )
        pattern.increment_occurrence()  # 10
        assert pattern.confidence == 1.0
        pattern.increment_occurrence()  # 11
        assert pattern.confidence == 1.0  # Toujours 1.0

    def test_correction_pattern_is_reliable(self):
        """is_reliable vérifie le seuil de confiance."""
        pattern = CorrectionPattern(
            id="p1",
            pattern_type=CorrectionType.GRAMMAR,
            original_pattern="a",
            replacement="b",
            confidence=0.5
        )
        assert pattern.is_reliable(min_confidence=0.6) is False
        assert pattern.is_reliable(min_confidence=0.5) is True
        assert pattern.is_reliable(min_confidence=0.4) is True


class TestImprovementModel:
    """Tests pour l'entité ImprovementModel avec edge cases."""

    def test_improvement_model_create(self):
        """ImprovementModel.create génère un modèle."""
        model = ImprovementModel.create(
            name="Tone Improvement v1",
            description="Improves email tone"
        )
        assert model.id is not None
        assert model.status == ImprovementStatus.PENDING
        assert model.version == "1.0.0"

    def test_improvement_model_activate(self):
        """activate change le statut."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.activate()
        assert model.status == ImprovementStatus.ACTIVE

    def test_improvement_model_disable(self):
        """disable change le statut."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.disable()
        assert model.status == ImprovementStatus.DISABLED

    def test_improvement_model_deprecate(self):
        """deprecate change le statut."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.deprecate()
        assert model.status == ImprovementStatus.DEPRECATED

    def test_improvement_model_add_pattern(self):
        """add_pattern ajoute un pattern unique."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.add_pattern("pattern-1")
        model.add_pattern("pattern-2")
        model.add_pattern("pattern-1")  # Doublon
        assert len(model.patterns) == 2

    def test_improvement_model_add_prompt_adjustment(self):
        """add_prompt_adjustment ajoute un ajustement unique."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.add_prompt_adjustment("Use formal tone")
        model.add_prompt_adjustment("Be concise")
        model.add_prompt_adjustment("Use formal tone")  # Doublon
        assert len(model.prompt_adjustments) == 2

    def test_improvement_model_record_improvement(self):
        """record_improvement incrémente le compteur."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.record_improvement()
        model.record_improvement()
        assert model.drafts_improved == 2

    def test_improvement_model_update_impact_score(self):
        """update_impact_score calcule la moyenne mobile."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.record_improvement()
        model.update_impact_score(0.8)
        assert model.impact_score == 0.8

        model.record_improvement()
        model.update_impact_score(0.6)
        # Moyenne: (0.8 * 1 + 0.6) / 2 = 0.7
        assert model.impact_score == pytest.approx(0.7)

    def test_improvement_model_update_impact_score_no_improvements(self):
        """update_impact_score sans amélioration précédente."""
        model = ImprovementModel.create(name="Test", description="Test")
        model.update_impact_score(0.9)
        assert model.impact_score == 0.9


class TestFineTuningSession:
    """Tests pour l'entité FineTuningSession avec edge cases."""

    def test_finetuning_session_create(self):
        """FineTuningSession.create génère une session."""
        session = FineTuningSession.create()
        assert session.id is not None
        assert session.status == "running"
        assert session.ended_at is None

    def test_finetuning_session_complete(self):
        """complete termine la session."""
        session = FineTuningSession.create()
        session.complete(model_id="model-123")
        assert session.status == "completed"
        assert session.model_id == "model-123"
        assert session.ended_at is not None

    def test_finetuning_session_complete_without_model(self):
        """complete sans modèle généré."""
        session = FineTuningSession.create()
        session.complete()
        assert session.status == "completed"
        assert session.model_id is None

    def test_finetuning_session_fail(self):
        """fail marque la session en erreur."""
        session = FineTuningSession.create()
        session.fail("Not enough data")
        assert "failed" in session.status
        assert "Not enough data" in session.status
        assert session.ended_at is not None


class TestFineTuningStats:
    """Tests pour l'entité FineTuningStats."""

    def test_finetuning_stats_defaults(self):
        """FineTuningStats avec valeurs par défaut."""
        stats = FineTuningStats()
        assert stats.total_corrections == 0
        assert stats.total_feedbacks == 0
        assert stats.active_models == 0
        assert stats.improvement_rate == 0.0


# ============================================================================
# TESTS - MOBILE COMPANION ENTITIES
# ============================================================================

from app.domain.entities import (
    MobileEventType,
    SyncStatus,
    MobileDraftAction,
    NotificationPreference,
    SyncFrequency,
    MobileSession,
    MobileSyncState,
    MobileAnalyticsEvent,
    MobileDraft,
    MobileUserPreferences,
    MobileAppConfig,
    MobileSyncResponse,
    MobileDraftActionRequest,
    MobileStats,
)


class TestMobileSession:
    """Tests pour l'entité MobileSession avec edge cases."""

    def test_mobile_session_minimal(self):
        """MobileSession avec champs minimaux."""
        session = MobileSession(user_id="user-1")
        assert session.user_id == "user-1"
        assert session.is_active is True
        assert session.session_id is not None

    def test_mobile_session_empty_user_id_raises(self):
        """MobileSession avec user_id vide lève erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSession(user_id="")

    def test_mobile_session_touch(self):
        """touch met à jour last_activity_at."""
        session = MobileSession(user_id="user-1")
        old_time = session.last_activity_at
        import time
        time.sleep(0.01)
        session.touch()
        assert session.last_activity_at > old_time

    def test_mobile_session_end(self):
        """end termine la session."""
        session = MobileSession(user_id="user-1")
        session.end()
        assert session.is_active is False

    def test_mobile_session_to_dict(self):
        """Sérialisation vers dictionnaire."""
        session = MobileSession(
            user_id="user-1",
            device_token="token-abc",
            app_version="2.1.0"
        )
        data = session.to_dict()
        assert data["user_id"] == "user-1"
        assert data["device_token"] == "token-abc"
        assert data["app_version"] == "2.1.0"

    def test_mobile_session_from_dict(self):
        """Désérialisation depuis dictionnaire."""
        data = {
            "user_id": "user-2",
            "session_id": "sess-123",
            "started_at": "2024-01-15T10:00:00",
            "last_activity_at": "2024-01-15T11:00:00",
            "is_active": True
        }
        session = MobileSession.from_dict(data)
        assert session.user_id == "user-2"
        assert session.session_id == "sess-123"


class TestMobileSyncState:
    """Tests pour l'entité MobileSyncState avec edge cases."""

    def test_mobile_sync_state_minimal(self):
        """MobileSyncState avec champs minimaux."""
        state = MobileSyncState(user_id="user-1", device_token="token-abc")
        assert state.last_sync_status == SyncStatus.IDLE
        assert state.drafts_synced_count == 0

    def test_mobile_sync_state_empty_user_id_raises(self):
        """MobileSyncState avec user_id vide lève erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSyncState(user_id="", device_token="token")

    def test_mobile_sync_state_empty_device_token_raises(self):
        """MobileSyncState avec device_token vide lève erreur."""
        with pytest.raises(ValueError, match="Device token cannot be empty"):
            MobileSyncState(user_id="user-1", device_token="")

    def test_mobile_sync_state_status_from_string(self):
        """MobileSyncState avec status string se convertit."""
        state = MobileSyncState(
            user_id="user-1",
            device_token="token",
            last_sync_status="syncing"
        )
        assert state.last_sync_status == SyncStatus.SYNCING

    def test_mobile_sync_state_mark_syncing(self):
        """mark_syncing change le statut."""
        state = MobileSyncState(user_id="user-1", device_token="token")
        state.mark_syncing()
        assert state.last_sync_status == SyncStatus.SYNCING
        assert state.error_message is None

    def test_mobile_sync_state_mark_success(self):
        """mark_success met à jour l'état."""
        state = MobileSyncState(user_id="user-1", device_token="token")
        state.pending_actions_count = 5
        state.mark_success(drafts_count=10)
        assert state.last_sync_status == SyncStatus.SUCCESS
        assert state.drafts_synced_count == 10
        assert state.pending_actions_count == 0
        assert state.last_sync_at is not None

    def test_mobile_sync_state_mark_failed(self):
        """mark_failed enregistre l'erreur."""
        state = MobileSyncState(user_id="user-1", device_token="token")
        state.mark_failed("Network error")
        assert state.last_sync_status == SyncStatus.FAILED
        assert state.error_message == "Network error"


class TestMobileAnalyticsEvent:
    """Tests pour l'entité MobileAnalyticsEvent avec edge cases."""

    def test_mobile_analytics_event_minimal(self):
        """MobileAnalyticsEvent avec champs minimaux."""
        event = MobileAnalyticsEvent(user_id="user-1")
        assert event.user_id == "user-1"
        assert event.event_type == MobileEventType.APP_OPEN
        assert event.event_id is not None

    def test_mobile_analytics_event_empty_user_id_raises(self):
        """MobileAnalyticsEvent avec user_id vide lève erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileAnalyticsEvent(user_id="")

    def test_mobile_analytics_event_type_from_string(self):
        """MobileAnalyticsEvent avec event_type string se convertit."""
        event = MobileAnalyticsEvent(user_id="user-1", event_type="draft.view")
        assert event.event_type == MobileEventType.DRAFT_VIEW

    def test_mobile_analytics_event_all_types(self):
        """Test tous les types d'événements."""
        for event_type in MobileEventType:
            event = MobileAnalyticsEvent(user_id="user-1", event_type=event_type)
            assert event.event_type == event_type


class TestMobileDraft:
    """Tests pour l'entité MobileDraft avec edge cases."""

    def test_mobile_draft_minimal(self):
        """MobileDraft avec champs minimaux."""
        draft = MobileDraft(
            draft_id="d-1",
            subject="Test Subject",
            recipient="user@example.com"
        )
        assert draft.draft_id == "d-1"
        assert draft.priority_score == 50
        assert draft.action == MobileDraftAction.PENDING

    def test_mobile_draft_empty_draft_id_raises(self):
        """MobileDraft avec draft_id vide lève erreur."""
        with pytest.raises(ValueError, match="Draft ID cannot be empty"):
            MobileDraft(draft_id="", subject="S", recipient="r@r.com")

    def test_mobile_draft_empty_subject_raises(self):
        """MobileDraft avec subject vide lève erreur."""
        with pytest.raises(ValueError, match="Subject cannot be empty"):
            MobileDraft(draft_id="d-1", subject="", recipient="r@r.com")

    def test_mobile_draft_action_from_string(self):
        """MobileDraft avec action string se convertit."""
        draft = MobileDraft(
            draft_id="d-1",
            subject="S",
            recipient="r@r.com",
            action="approved"
        )
        assert draft.action == MobileDraftAction.APPROVED

    def test_mobile_draft_generates_preview(self):
        """MobileDraft génère un aperçu automatiquement."""
        long_body = "A" * 300
        draft = MobileDraft(
            draft_id="d-1",
            subject="S",
            recipient="r@r.com",
            body_full=long_body
        )
        assert len(draft.body_preview) == 203  # 200 + "..."
        assert draft.body_preview.endswith("...")

    def test_mobile_draft_preview_short_body(self):
        """MobileDraft avec body court garde tout."""
        draft = MobileDraft(
            draft_id="d-1",
            subject="S",
            recipient="r@r.com",
            body_full="Short text"
        )
        assert draft.body_preview == "Short text"

    def test_mobile_draft_mark_read(self):
        """mark_read met à jour le statut."""
        draft = MobileDraft(draft_id="d-1", subject="S", recipient="r@r.com")
        assert draft.is_read is False
        draft.mark_read()
        assert draft.is_read is True

    def test_mobile_draft_approve(self):
        """approve change l'action."""
        draft = MobileDraft(draft_id="d-1", subject="S", recipient="r@r.com")
        draft.approve()
        assert draft.action == MobileDraftAction.APPROVED

    def test_mobile_draft_reject(self):
        """reject change l'action."""
        draft = MobileDraft(draft_id="d-1", subject="S", recipient="r@r.com")
        draft.reject()
        assert draft.action == MobileDraftAction.REJECTED

    def test_mobile_draft_edit(self):
        """edit met à jour le body et l'action."""
        draft = MobileDraft(
            draft_id="d-1",
            subject="S",
            recipient="r@r.com",
            body_full="Original"
        )
        draft.edit("New content that is longer than original")
        assert draft.body_full == "New content that is longer than original"
        assert draft.action == MobileDraftAction.EDITED

    def test_mobile_draft_to_dict(self):
        """Sérialisation vers dictionnaire."""
        draft = MobileDraft(
            draft_id="d-1",
            subject="Test",
            recipient="test@test.com",
            recipient_name="Test User"
        )
        data = draft.to_dict()
        assert data["draft_id"] == "d-1"
        assert data["recipient_name"] == "Test User"

    def test_mobile_draft_to_list_dict(self):
        """Sérialisation allégée pour listes."""
        draft = MobileDraft(
            draft_id="d-1",
            subject="Test",
            recipient="test@test.com",
            body_full="Very long body content..."
        )
        data = draft.to_list_dict()
        assert "body_full" not in data
        assert "body_preview" in data


class TestMobileUserPreferences:
    """Tests pour l'entité MobileUserPreferences avec edge cases."""

    def test_mobile_user_preferences_minimal(self):
        """MobileUserPreferences avec champs minimaux."""
        prefs = MobileUserPreferences(user_id="user-1")
        assert prefs.notification_preference == NotificationPreference.ALL
        assert prefs.sync_frequency == SyncFrequency.EVERY_5_MIN
        assert prefs.auto_approve_threshold == 0

    def test_mobile_user_preferences_empty_user_id_raises(self):
        """MobileUserPreferences avec user_id vide lève erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileUserPreferences(user_id="")

    def test_mobile_user_preferences_invalid_threshold_raises(self):
        """MobileUserPreferences avec seuil invalide lève erreur."""
        with pytest.raises(ValueError, match="between 0 and 100"):
            MobileUserPreferences(user_id="user-1", auto_approve_threshold=150)

    def test_mobile_user_preferences_threshold_bounds(self):
        """MobileUserPreferences avec seuils aux limites."""
        prefs0 = MobileUserPreferences(user_id="user-1", auto_approve_threshold=0)
        assert prefs0.auto_approve_threshold == 0

        prefs100 = MobileUserPreferences(user_id="user-1", auto_approve_threshold=100)
        assert prefs100.auto_approve_threshold == 100

    def test_mobile_user_preferences_enum_from_string(self):
        """MobileUserPreferences avec enums string se convertit."""
        prefs = MobileUserPreferences(
            user_id="user-1",
            notification_preference="important_only",
            sync_frequency="1hour"
        )
        assert prefs.notification_preference == NotificationPreference.IMPORTANT_ONLY
        assert prefs.sync_frequency == SyncFrequency.EVERY_HOUR


class TestMobileAppConfig:
    """Tests pour l'entité MobileAppConfig avec edge cases."""

    def test_mobile_app_config_defaults(self):
        """MobileAppConfig avec valeurs par défaut."""
        config = MobileAppConfig()
        assert config.min_version == "1.0.0"
        assert config.force_update is False
        assert config.maintenance_mode is False
        assert "offline_mode" in config.feature_flags

    def test_mobile_app_config_is_version_supported(self):
        """is_version_supported vérifie les versions."""
        config = MobileAppConfig(min_version="2.0.0")
        assert config.is_version_supported("2.0.0") is True
        assert config.is_version_supported("2.1.0") is True
        assert config.is_version_supported("1.9.0") is False

    def test_mobile_app_config_needs_update(self):
        """needs_update vérifie si mise à jour nécessaire."""
        config = MobileAppConfig(latest_version="2.5.0")
        assert config.needs_update("2.4.0") is True
        assert config.needs_update("2.5.0") is False
        assert config.needs_update("2.6.0") is False

    def test_mobile_app_config_version_comparison_parts(self):
        """Comparaison de versions avec parties manquantes."""
        config = MobileAppConfig(min_version="2.0", latest_version="2.1")
        assert config.is_version_supported("2.0.0") is True
        assert config.is_version_supported("2") is True
        assert config.needs_update("2.0") is True


class TestMobileDraftActionRequest:
    """Tests pour l'entité MobileDraftActionRequest avec edge cases."""

    def test_mobile_draft_action_request_minimal(self):
        """MobileDraftActionRequest avec champs minimaux."""
        request = MobileDraftActionRequest(
            draft_id="d-1",
            action=MobileDraftAction.APPROVED,
            user_id="user-1"
        )
        assert request.draft_id == "d-1"
        assert request.action == MobileDraftAction.APPROVED

    def test_mobile_draft_action_request_empty_draft_id_raises(self):
        """MobileDraftActionRequest avec draft_id vide lève erreur."""
        with pytest.raises(ValueError, match="Draft ID cannot be empty"):
            MobileDraftActionRequest(
                draft_id="",
                action=MobileDraftAction.APPROVED,
                user_id="user-1"
            )

    def test_mobile_draft_action_request_empty_user_id_raises(self):
        """MobileDraftActionRequest avec user_id vide lève erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileDraftActionRequest(
                draft_id="d-1",
                action=MobileDraftAction.APPROVED,
                user_id=""
            )

    def test_mobile_draft_action_request_edit_without_body_raises(self):
        """MobileDraftActionRequest edit sans body lève erreur."""
        with pytest.raises(ValueError, match="Edited body is required"):
            MobileDraftActionRequest(
                draft_id="d-1",
                action=MobileDraftAction.EDITED,
                user_id="user-1"
            )

    def test_mobile_draft_action_request_edit_with_body(self):
        """MobileDraftActionRequest edit avec body valide."""
        request = MobileDraftActionRequest(
            draft_id="d-1",
            action=MobileDraftAction.EDITED,
            user_id="user-1",
            edited_body="New content"
        )
        assert request.edited_body == "New content"

    def test_mobile_draft_action_request_action_from_string(self):
        """MobileDraftActionRequest avec action string se convertit."""
        request = MobileDraftActionRequest(
            draft_id="d-1",
            action="rejected",
            user_id="user-1"
        )
        assert request.action == MobileDraftAction.REJECTED


class TestMobileSyncResponse:
    """Tests pour l'entité MobileSyncResponse."""

    def test_mobile_sync_response_success(self):
        """MobileSyncResponse succès."""
        response = MobileSyncResponse(success=True)
        assert response.success is True
        assert response.drafts == []
        assert response.has_more is False

    def test_mobile_sync_response_with_drafts(self):
        """MobileSyncResponse avec brouillons."""
        drafts = [
            MobileDraft(draft_id="d-1", subject="S1", recipient="r@r.com"),
            MobileDraft(draft_id="d-2", subject="S2", recipient="r@r.com")
        ]
        response = MobileSyncResponse(
            success=True,
            drafts=drafts,
            has_more=True,
            next_cursor="cursor-abc"
        )
        assert len(response.drafts) == 2
        assert response.has_more is True
        assert response.next_cursor == "cursor-abc"

    def test_mobile_sync_response_error(self):
        """MobileSyncResponse avec erreur."""
        response = MobileSyncResponse(
            success=False,
            error_message="Connection timeout"
        )
        assert response.success is False
        assert response.error_message == "Connection timeout"


class TestMobileStats:
    """Tests pour l'entité MobileStats."""

    def test_mobile_stats_defaults(self):
        """MobileStats avec valeurs par défaut."""
        stats = MobileStats(user_id="user-1")
        assert stats.total_drafts == 0
        assert stats.pending_drafts == 0
        assert stats.ai_accuracy_percentage == 0.0

    def test_mobile_stats_to_dict(self):
        """Sérialisation vers dictionnaire."""
        stats = MobileStats(
            user_id="user-1",
            total_drafts=100,
            approved_today=15,
            ai_accuracy_percentage=85.5
        )
        data = stats.to_dict()
        assert data["total_drafts"] == 100
        assert data["ai_accuracy_percentage"] == 85.5


# ============================================================================
# TESTS - DRAFT RECORD ENTITY (domain layer)
# ============================================================================

from app.domain.entities.draft_history import DraftRecord as DomainDraftRecord


class TestDomainDraftRecord:
    """Tests pour l'entité DraftRecord du domaine."""

    @pytest.fixture
    def sample_draft_record(self):
        """Crée un DraftRecord de test."""
        return DomainDraftRecord(
            id="test-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Test Subject",
            email_preview="Preview content",
            draft_v1="Draft V1 content",
            critique="Good draft",
            draft_final="Final draft content",
            status="VALIDÉ V1",
            category="URGENT",
        )

    def test_email_body_alias(self, sample_draft_record):
        """email_body est un alias pour email_preview."""
        assert sample_draft_record.email_body == "Preview content"
        assert sample_draft_record.email_body == sample_draft_record.email_preview

    def test_email_body_alias_empty(self):
        """email_body retourne chaîne vide si email_preview vide."""
        record = DomainDraftRecord(
            id="test-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Test Subject",
            email_preview="",
            draft_v1="Draft V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
        )
        assert record.email_body == ""

    def test_to_correction_context(self, sample_draft_record):
        """to_correction_context retourne le bon contexte."""
        context = sample_draft_record.to_correction_context()
        assert context == {
            "sender": "sender@example.com",
            "subject": "Test Subject",
            "category": "URGENT",
        }

    def test_to_correction_context_with_none_category(self):
        """to_correction_context gère category=None."""
        record = DomainDraftRecord(
            id="test-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="user@example.com",
            email_subject="Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
            category=None,
        )
        context = record.to_correction_context()
        assert context["category"] is None
        assert context["sender"] == "user@example.com"
        assert context["subject"] == "Subject"

    def test_with_feedback(self, sample_draft_record):
        """with_feedback retourne une copie avec feedback."""
        updated = sample_draft_record.with_feedback("positive", "Excellent work!")

        # Original inchangé
        assert sample_draft_record.feedback is None
        assert sample_draft_record.feedback_comment is None

        # Nouvelle instance avec feedback
        assert updated.feedback == "positive"
        assert updated.feedback_comment == "Excellent work!"

        # Autres champs copiés
        assert updated.id == sample_draft_record.id
        assert updated.email_sender == sample_draft_record.email_sender
        assert updated.category == sample_draft_record.category

    def test_with_feedback_empty_comment(self, sample_draft_record):
        """with_feedback avec commentaire vide."""
        updated = sample_draft_record.with_feedback("negative")
        assert updated.feedback == "negative"
        assert updated.feedback_comment == ""

    def test_with_feedback_preserves_all_fields(self, sample_draft_record):
        """with_feedback préserve tous les champs."""
        updated = sample_draft_record.with_feedback("neutral", "OK")

        assert updated.id == sample_draft_record.id
        assert updated.timestamp == sample_draft_record.timestamp
        assert updated.email_id == sample_draft_record.email_id
        assert updated.email_sender == sample_draft_record.email_sender
        assert updated.email_subject == sample_draft_record.email_subject
        assert updated.email_preview == sample_draft_record.email_preview
        assert updated.draft_v1 == sample_draft_record.draft_v1
        assert updated.critique == sample_draft_record.critique
        assert updated.draft_final == sample_draft_record.draft_final
        assert updated.status == sample_draft_record.status
        assert updated.draft_id == sample_draft_record.draft_id
        assert updated.tokens_used == sample_draft_record.tokens_used
        assert updated.model == sample_draft_record.model
        assert updated.processing_time_ms == sample_draft_record.processing_time_ms
        assert updated.priority_score == sample_draft_record.priority_score
        assert updated.category == sample_draft_record.category

    def test_default_values(self):
        """Valeurs par défaut des champs optionnels."""
        record = DomainDraftRecord(
            id="test-001",
            timestamp="2024-01-15T10:00:00",
            email_id="email-1",
            email_sender="sender@example.com",
            email_subject="Test Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
        )
        assert record.draft_id is None
        assert record.tokens_used == 0
        assert record.model == ""
        assert record.processing_time_ms == 0
        assert record.priority_score is None
        assert record.category is None
        assert record.feedback is None
        assert record.feedback_comment is None
