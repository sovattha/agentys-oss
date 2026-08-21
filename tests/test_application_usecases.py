# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les Use Cases de la couche Application.

Ces tests couvrent les edge cases non testés :
- Erreurs LLM (API down, timeout, réponse vide)
- Inputs null/invalides
- Gestion des erreurs
- Cas limites
"""

import pytest
from unittest.mock import MagicMock

from app.domain.entities import (
    Email,
    Draft,
    Critique,
    ProcessingResult,
    DraftStatus,
    TokenUsage,
    PushNotificationCategory,
)
from app.domain.ports import LLMPort, LLMResponse, NotificationPort, NotificationPriority, PushNotificationResult
from app.application import (
    DraftEmailUseCase,
    CritiqueEmailUseCase,
    ProcessEmailUseCase,
    SendPushNotificationUseCase,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_email():
    """Email de test."""
    return Email(
        id="email-123",
        subject="Test Subject",
        body="Test body content",
        sender="sender@test.com",
        recipients=["recipient@test.com"],
    )


@pytest.fixture
def empty_email():
    """Email avec contenu vide mais id/sender valides."""
    return Email(
        id="empty-123",
        subject="",
        body="",
        sender="empty@test.com",
    )


@pytest.fixture
def mock_llm():
    """LLM mocké."""
    mock = MagicMock(spec=LLMPort)
    mock.name = "mock-llm"
    mock.model = "mock-model"
    mock.complete.return_value = LLMResponse(
        content="Réponse générée",
        input_tokens=100,
        output_tokens=50,
        model="mock-model"
    )
    return mock


@pytest.fixture
def mock_llm_valid_critique():
    """LLM mocké qui retourne VALID."""
    mock = MagicMock(spec=LLMPort)
    mock.complete.return_value = LLMResponse(
        content="VALID",
        input_tokens=100,
        output_tokens=10,
        model="mock-model"
    )
    return mock


@pytest.fixture
def mock_llm_invalid_critique():
    """LLM mocké qui retourne REJET."""
    mock = MagicMock(spec=LLMPort)
    mock.complete.return_value = LLMResponse(
        content="REJET : Ton inapproprié",
        input_tokens=100,
        output_tokens=30,
        model="mock-model"
    )
    return mock


@pytest.fixture
def knowledge_base():
    """Knowledge base de test."""
    return "# Base de connaissances test\n\n- Règle 1\n- Règle 2"


@pytest.fixture
def token_usage():
    """TokenUsage de test."""
    return TokenUsage()


# ============================================================================
# TESTS - DRAFT EMAIL USE CASE
# ============================================================================

class TestDraftEmailUseCase:
    """Tests pour DraftEmailUseCase avec edge cases."""

    def test_execute_success(self, sample_email, mock_llm, knowledge_base, token_usage):
        """Exécution réussie."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        draft = use_case.execute(sample_email)

        assert isinstance(draft, Draft)
        assert draft.version == 1
        assert draft.content == "Réponse générée"
        mock_llm.complete.assert_called_once()

    def test_execute_tracks_tokens(self, sample_email, mock_llm, knowledge_base, token_usage):
        """Les tokens sont trackés."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        use_case.execute(sample_email)

        assert token_usage.input_tokens == 100
        assert token_usage.output_tokens == 50
        assert token_usage.model == "mock-model"

    def test_execute_with_empty_email(self, empty_email, mock_llm, knowledge_base, token_usage):
        """Exécution avec email vide."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        draft = use_case.execute(empty_email)

        assert isinstance(draft, Draft)
        # Le LLM est appelé même avec email vide
        mock_llm.complete.assert_called_once()

    def test_execute_with_empty_knowledge_base(self, sample_email, mock_llm, token_usage):
        """Exécution avec knowledge base vide."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage
        )
        draft = use_case.execute(sample_email)

        assert isinstance(draft, Draft)

    def test_execute_revision_success(self, sample_email, mock_llm, knowledge_base, token_usage):
        """Révision réussie."""
        mock_llm.complete.return_value = LLMResponse(
            content="Réponse corrigée",
            input_tokens=150,
            output_tokens=60,
            model="mock-model"
        )
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        draft = use_case.execute_revision(sample_email, "Ton trop formel")

        assert isinstance(draft, Draft)
        assert draft.version == 2
        assert draft.content == "Réponse corrigée"

    def test_execute_revision_with_empty_critique(self, sample_email, mock_llm, knowledge_base, token_usage):
        """Révision avec critique vide."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        draft = use_case.execute_revision(sample_email, "")

        assert isinstance(draft, Draft)
        assert draft.version == 2

    def test_llm_returns_empty_content(self, sample_email, mock_llm, knowledge_base, token_usage):
        """LLM retourne contenu vide."""
        mock_llm.complete.return_value = LLMResponse(
            content="",
            input_tokens=100,
            output_tokens=0,
            model="mock-model"
        )
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        draft = use_case.execute(sample_email)

        assert draft.content == ""

    def test_llm_raises_exception(self, sample_email, mock_llm, knowledge_base, token_usage):
        """LLM lève une exception."""
        mock_llm.complete.side_effect = Exception("API Error")
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        with pytest.raises(Exception, match="API Error"):
            use_case.execute(sample_email)

    def test_token_usage_auto_created(self, sample_email, mock_llm, knowledge_base):
        """TokenUsage créé automatiquement si non fourni."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
        )
        assert use_case.token_usage is not None
        assert isinstance(use_case.token_usage, TokenUsage)

    def test_max_tokens_passed_to_llm(self, sample_email, mock_llm, knowledge_base, token_usage):
        """max_tokens passé au LLM."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            max_tokens=2048,
            token_usage=token_usage
        )
        use_case.execute(sample_email)

        call_kwargs = mock_llm.complete.call_args[1]
        assert call_kwargs["max_tokens"] == 2048


# ============================================================================
# TESTS - CRITIQUE EMAIL USE CASE
# ============================================================================

class TestCritiqueEmailUseCase:
    """Tests pour CritiqueEmailUseCase avec edge cases."""

    @pytest.fixture
    def sample_draft(self):
        """Draft de test."""
        return Draft(content="Contenu du brouillon", version=1)

    def test_execute_valid_critique(self, sample_email, sample_draft, mock_llm_valid_critique, knowledge_base, token_usage):
        """Critique VALID."""
        use_case = CritiqueEmailUseCase(
            llm=mock_llm_valid_critique,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        critique = use_case.execute(sample_email, sample_draft)

        assert isinstance(critique, Critique)
        assert critique.is_valid is True

    def test_execute_invalid_critique(self, sample_email, sample_draft, mock_llm_invalid_critique, knowledge_base, token_usage):
        """Critique REJET."""
        use_case = CritiqueEmailUseCase(
            llm=mock_llm_invalid_critique,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        critique = use_case.execute(sample_email, sample_draft)

        assert isinstance(critique, Critique)
        assert critique.is_valid is False
        assert "Ton inapproprié" in critique.reason

    def test_execute_tracks_tokens(self, sample_email, sample_draft, mock_llm_valid_critique, knowledge_base, token_usage):
        """Les tokens sont trackés."""
        use_case = CritiqueEmailUseCase(
            llm=mock_llm_valid_critique,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        use_case.execute(sample_email, sample_draft)

        assert token_usage.input_tokens == 100
        assert token_usage.output_tokens == 10

    def test_execute_with_empty_draft(self, sample_email, mock_llm_valid_critique, knowledge_base, token_usage):
        """Critique d'un draft vide."""
        empty_draft = Draft(content="")
        use_case = CritiqueEmailUseCase(
            llm=mock_llm_valid_critique,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        critique = use_case.execute(sample_email, empty_draft)

        assert isinstance(critique, Critique)

    def test_llm_returns_empty_response(self, sample_email, sample_draft, mock_llm, knowledge_base, token_usage):
        """LLM retourne réponse vide."""
        mock_llm.complete.return_value = LLMResponse(
            content="",
            input_tokens=100,
            output_tokens=0,
            model="mock-model"
        )
        use_case = CritiqueEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        critique = use_case.execute(sample_email, sample_draft)

        # Réponse vide = invalide
        assert critique.is_valid is False

    def test_llm_returns_whitespace_only(self, sample_email, sample_draft, mock_llm, knowledge_base, token_usage):
        """LLM retourne uniquement des espaces."""
        mock_llm.complete.return_value = LLMResponse(
            content="   \n\n   ",
            input_tokens=100,
            output_tokens=5,
            model="mock-model"
        )
        use_case = CritiqueEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        critique = use_case.execute(sample_email, sample_draft)

        assert critique.is_valid is False


# ============================================================================
# TESTS - PROCESS EMAIL USE CASE
# ============================================================================

class TestProcessEmailUseCase:
    """Tests pour ProcessEmailUseCase avec edge cases."""

    def test_execute_validated_v1(self, sample_email, mock_llm, knowledge_base, token_usage):
        """Pipeline avec V1 validée."""
        # Setup: draft puis VALID
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft V1", input_tokens=100, output_tokens=50, model="mock"),
            LLMResponse(content="VALID", input_tokens=150, output_tokens=10, model="mock"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        result = use_case.execute(sample_email)

        assert isinstance(result, ProcessingResult)
        assert result.status == DraftStatus.VALIDATED_V1
        assert result.was_corrected is False
        assert result.draft_v1 == result.draft_final
        assert mock_llm.complete.call_count == 2

    def test_execute_corrected_v2(self, sample_email, mock_llm, knowledge_base, token_usage):
        """Pipeline avec correction V2."""
        # Setup: draft, REJET, revision
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft V1", input_tokens=100, output_tokens=50, model="mock"),
            LLMResponse(content="REJET : Ton trop formel", input_tokens=150, output_tokens=20, model="mock"),
            LLMResponse(content="Draft V2 corrigé", input_tokens=200, output_tokens=60, model="mock"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        result = use_case.execute(sample_email)

        assert result.status == DraftStatus.CORRECTED_V2
        assert result.was_corrected is True
        assert result.draft_v1.content == "Draft V1"
        assert result.draft_final.content == "Draft V2 corrigé"
        assert mock_llm.complete.call_count == 3

    def test_execute_tracks_all_tokens(self, sample_email, mock_llm, knowledge_base, token_usage):
        """Tous les tokens sont trackés."""
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft V1", input_tokens=100, output_tokens=50, model="mock"),
            LLMResponse(content="VALID", input_tokens=150, output_tokens=10, model="mock"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        use_case.execute(sample_email)

        assert token_usage.input_tokens == 250  # 100 + 150
        assert token_usage.output_tokens == 60  # 50 + 10

    def test_execute_with_empty_email(self, empty_email, mock_llm, knowledge_base, token_usage):
        """Pipeline avec email au contenu vide (subject/body vides)."""
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft", input_tokens=50, output_tokens=20, model="mock"),
            LLMResponse(content="VALID", input_tokens=50, output_tokens=5, model="mock"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )
        result = use_case.execute(empty_email)

        assert isinstance(result, ProcessingResult)
        assert result.email_id == "empty-123"  # ID valide mais contenu vide

    def test_llm_error_on_draft(self, sample_email, mock_llm, knowledge_base, token_usage):
        """Erreur LLM lors du draft."""
        mock_llm.complete.side_effect = Exception("LLM unavailable")

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        with pytest.raises(Exception, match="LLM unavailable"):
            use_case.execute(sample_email)

    def test_llm_error_on_critique(self, sample_email, mock_llm, knowledge_base, token_usage):
        """Erreur LLM lors de la critique."""
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft V1", input_tokens=100, output_tokens=50, model="mock"),
            Exception("Critique failed"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        with pytest.raises(Exception, match="Critique failed"):
            use_case.execute(sample_email)

    def test_llm_error_on_revision(self, sample_email, mock_llm, knowledge_base, token_usage):
        """Erreur LLM lors de la révision."""
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft V1", input_tokens=100, output_tokens=50, model="mock"),
            LLMResponse(content="REJET : Problème", input_tokens=150, output_tokens=20, model="mock"),
            Exception("Revision failed"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        with pytest.raises(Exception, match="Revision failed"):
            use_case.execute(sample_email)


# ============================================================================
# TESTS - SEND PUSH NOTIFICATION USE CASE
# ============================================================================

class TestSendPushNotificationUseCase:
    """Tests pour SendPushNotificationUseCase avec edge cases."""

    @pytest.fixture
    def mock_notification_adapter(self):
        """Adapter de notification mocké."""
        mock = MagicMock(spec=NotificationPort)
        mock.name = "mock"
        mock.is_available.return_value = True
        mock.send.return_value = PushNotificationResult(
            success=True,
            message_id="msg-123"
        )
        mock.send_batch.return_value = [
            PushNotificationResult(success=True, message_id="msg-1"),
            PushNotificationResult(success=True, message_id="msg-2"),
        ]
        return mock

    @pytest.fixture
    def use_case(self, mock_notification_adapter):
        """Use case avec mock adapter."""
        return SendPushNotificationUseCase(notification_adapter=mock_notification_adapter)

    def test_execute_success(self, use_case, mock_notification_adapter):
        """Envoi réussi."""
        result = use_case.execute(
            device_token="token-123",
            title="Test",
            body="Body",
        )

        assert result.success is True
        assert result.message_id == "msg-123"
        mock_notification_adapter.send.assert_called_once()

    def test_execute_failure(self, use_case, mock_notification_adapter):
        """Envoi échoué."""
        mock_notification_adapter.send.return_value = PushNotificationResult(
            success=False,
            error_code="INVALID_TOKEN",
            error_message="Token expired"
        )

        result = use_case.execute(
            device_token="bad-token",
            title="Test",
            body="Body",
        )

        assert result.success is False
        assert result.error_code == "INVALID_TOKEN"

    def test_execute_records_notification(self, use_case):
        """Notification enregistrée dans l'historique."""
        use_case.execute(
            device_token="token-123",
            title="Test Title",
            body="Test Body",
        )

        assert len(use_case.records) == 1
        record = use_case.records[0]
        assert record.device_token == "token-123"
        assert record.notification.title == "Test Title"

    def test_execute_batch_empty_tokens(self, use_case, mock_notification_adapter):
        """Batch avec liste vide."""
        results = use_case.execute_batch(
            device_tokens=[],
            title="Test",
            body="Body",
        )

        assert results == []
        mock_notification_adapter.send_batch.assert_not_called()

    def test_execute_batch_success(self, use_case, mock_notification_adapter):
        """Batch réussi."""
        results = use_case.execute_batch(
            device_tokens=["token-1", "token-2"],
            title="Batch Test",
            body="Body",
        )

        assert len(results) == 2
        assert all(r.success for r in results)

    def test_execute_batch_partial_failure(self, use_case, mock_notification_adapter):
        """Batch avec échecs partiels."""
        mock_notification_adapter.send_batch.return_value = [
            PushNotificationResult(success=True, message_id="msg-1"),
            PushNotificationResult(success=False, error_message="Failed"),
        ]

        results = use_case.execute_batch(
            device_tokens=["token-1", "token-2"],
            title="Test",
            body="Body",
        )

        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is False

    def test_notify_draft_created_high_priority(self, use_case, mock_notification_adapter):
        """Notification brouillon haute priorité."""
        use_case.notify_draft_created(
            device_tokens=["token-1"],
            recipient="john@example.com",
            subject="Urgent meeting",
            draft_id="draft-123",
            priority_score=90,  # >= 80 = high
        )

        call_args = mock_notification_adapter.send_batch.call_args
        assert call_args[1]["priority"] == NotificationPriority.HIGH

    def test_notify_draft_created_normal_priority(self, use_case, mock_notification_adapter):
        """Notification brouillon priorité normale."""
        use_case.notify_draft_created(
            device_tokens=["token-1"],
            recipient="john@example.com",
            subject="Normal meeting",
            draft_id="draft-123",
            priority_score=50,  # < 80 = normal
        )

        call_args = mock_notification_adapter.send_batch.call_args
        assert call_args[1]["priority"] == NotificationPriority.NORMAL

    def test_notify_budget_warning_zero_budget(self, use_case):
        """Alerte budget avec budget = 0."""
        results = use_case.notify_budget_warning(
            device_tokens=["token-1"],
            current_spend=10.0,
            budget_limit=0.0,  # Division par zéro
        )

        # Devrait gérer sans crash
        assert len(results) == 2  # Basé sur le mock

    def test_get_stats_empty(self, use_case):
        """Statistiques sans notifications."""
        stats = use_case.get_stats()

        assert stats["total"] == 0
        assert stats["sent"] == 0
        assert stats["failed"] == 0
        assert stats["success_rate"] == 0  # Évite division par zéro

    def test_get_stats_with_notifications(self, use_case, mock_notification_adapter):
        """Statistiques avec notifications."""
        # Envoyer quelques notifications
        use_case.execute("t1", "Title 1", "Body", category=PushNotificationCategory.INFO)
        use_case.execute("t2", "Title 2", "Body", category=PushNotificationCategory.ERROR)

        # Simuler un échec
        mock_notification_adapter.send.return_value = PushNotificationResult(
            success=False, error_message="Failed"
        )
        use_case.execute("t3", "Title 3", "Body")

        stats = use_case.get_stats()

        assert stats["total"] == 3
        assert stats["sent"] == 2
        assert stats["failed"] == 1

    def test_get_records_limit(self, use_case, mock_notification_adapter):
        """Limite sur les enregistrements."""
        # Créer plusieurs notifications
        for i in range(10):
            use_case.execute(f"token-{i}", f"Title {i}", "Body")

        records = use_case.get_records(limit=5)

        assert len(records) == 5

    def test_priority_mapping(self, use_case):
        """Mapping des priorités string -> enum."""
        assert use_case._map_priority("low") == NotificationPriority.LOW
        assert use_case._map_priority("normal") == NotificationPriority.NORMAL
        assert use_case._map_priority("high") == NotificationPriority.HIGH
        assert use_case._map_priority("unknown") == NotificationPriority.NORMAL

    def test_execute_with_all_categories(self, use_case, mock_notification_adapter):
        """Test toutes les catégories."""
        for category in PushNotificationCategory:
            use_case.execute(
                device_token="token",
                title="Test",
                body="Body",
                category=category,
            )

        assert len(use_case.records) == len(PushNotificationCategory)

    def test_execute_with_data_payload(self, use_case, mock_notification_adapter):
        """Notification avec payload data."""
        use_case.execute(
            device_token="token",
            title="Test",
            body="Body",
            data={"key1": "value1", "key2": 123},
        )

        call_args = mock_notification_adapter.send.call_args
        data = call_args[1]["data"]
        assert "key1" in data
        assert "category" in data  # Ajouté automatiquement
        assert "timestamp" in data  # Ajouté automatiquement

    def test_execute_with_empty_title(self, mock_notification_adapter):
        """Notification avec titre vide (devrait lever une erreur dans PushNotification)."""
        use_case = SendPushNotificationUseCase(notification_adapter=mock_notification_adapter)

        with pytest.raises(ValueError, match="title cannot be empty"):
            use_case.execute(
                device_token="token",
                title="",
                body="Body",
            )

    def test_execute_with_empty_body(self, mock_notification_adapter):
        """Notification avec corps vide (devrait lever une erreur dans PushNotification)."""
        use_case = SendPushNotificationUseCase(notification_adapter=mock_notification_adapter)

        with pytest.raises(ValueError, match="body cannot be empty"):
            use_case.execute(
                device_token="token",
                title="Title",
                body="",
            )
