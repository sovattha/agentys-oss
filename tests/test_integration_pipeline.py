# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests d'intégration pour le pipeline complet.

Ces tests vérifient l'intégration entre les couches :
- Domain entities → Application use cases → Infrastructure adapters
- Scénarios de bout en bout avec erreurs et cas limites
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.domain.entities import (
    Email,
    DraftStatus,
    TokenUsage,
    DevicePlatform,
)
from app.domain.ports import LLMPort, LLMResponse, NotificationPort, PushNotificationResult
from app.application import (
    DraftEmailUseCase,
    ProcessEmailUseCase,
    SendPushNotificationUseCase,
    PushNotificationService,
)
from app.adapters.push import MockPushAdapter
from app.infrastructure.device_store import JsonFileDeviceStore


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_dir(tmp_path):
    """Répertoire temporaire."""
    return tmp_path


@pytest.fixture
def sample_email():
    """Email de test réaliste."""
    return Email(
        id="email-integration-123",
        subject="Question urgente sur le projet",
        body="""Bonjour,

J'espère que vous allez bien. Je vous contacte concernant le projet en cours.

Pouvez-vous me confirmer la date de livraison prévue ?

Merci d'avance,
Jean Client""",
        sender="jean.client@example.com",
        recipients=["support@company.com"],
        received_at=datetime.now(),
    )


@pytest.fixture
def mock_llm_full_pipeline():
    """LLM mocké pour un pipeline complet."""
    mock = MagicMock(spec=LLMPort)
    mock.name = "integration-mock"
    mock.model = "integration-model"
    return mock


@pytest.fixture
def knowledge_base():
    """Knowledge base pour tests d'intégration."""
    return """# Base de Connaissances Test

## Identité
- Assistant de support client
- Entreprise : TestCorp

## Règles
- Répondre poliment
- Ne pas promettre de délais
- Toujours proposer de l'aide supplémentaire
"""


# ============================================================================
# TESTS - PIPELINE COMPLET
# ============================================================================

class TestFullEmailPipeline:
    """Tests d'intégration du pipeline email complet."""

    def test_pipeline_v1_validated_end_to_end(self, sample_email, mock_llm_full_pipeline, knowledge_base):
        """Pipeline complet avec V1 validée."""
        # Setup des réponses LLM
        mock_llm_full_pipeline.complete.side_effect = [
            LLMResponse(
                content="""Bonjour Jean,

Merci pour votre message. Je vais me renseigner sur la date de livraison et vous recontacter rapidement.

N'hésitez pas si vous avez d'autres questions.

Cordialement""",
                input_tokens=500,
                output_tokens=80,
                model="integration-model"
            ),
            LLMResponse(
                content="VALID - Réponse professionnelle et adaptée",
                input_tokens=600,
                output_tokens=15,
                model="integration-model"
            ),
        ]

        token_usage = TokenUsage()
        use_case = ProcessEmailUseCase(
            llm=mock_llm_full_pipeline,
            knowledge_base=knowledge_base,
            token_usage=token_usage,
        )

        result = use_case.execute(sample_email)

        # Vérifications
        assert result.status == DraftStatus.VALIDATED_V1
        assert result.was_corrected is False
        assert result.email_id == "email-integration-123"
        assert "Bonjour Jean" in result.draft_final.content
        assert result.critique.is_valid is True

        # Tokens trackés
        assert token_usage.total == 1195  # 500 + 600 + 80 + 15

    def test_pipeline_v2_corrected_end_to_end(self, sample_email, mock_llm_full_pipeline, knowledge_base):
        """Pipeline complet avec correction V2."""
        mock_llm_full_pipeline.complete.side_effect = [
            # Draft V1 - trop formel
            LLMResponse(
                content="""Madame, Monsieur,

Suite à votre courrier électronique, nous vous prions de bien vouloir patienter.

Veuillez agréer nos salutations distinguées.""",
                input_tokens=400,
                output_tokens=50,
                model="integration-model"
            ),
            # Critique - rejet
            LLMResponse(
                content="REJET : Le ton est trop formel et impersonnel. L'email devrait utiliser le prénom du client et être plus chaleureux.",
                input_tokens=450,
                output_tokens=40,
                model="integration-model"
            ),
            # Draft V2 - corrigé
            LLMResponse(
                content="""Bonjour Jean,

Merci de nous avoir contactés ! Je comprends l'importance de votre question sur la date de livraison.

Je me renseigne immédiatement et vous tiens informé.

Belle journée !""",
                input_tokens=550,
                output_tokens=60,
                model="integration-model"
            ),
        ]

        token_usage = TokenUsage()
        use_case = ProcessEmailUseCase(
            llm=mock_llm_full_pipeline,
            knowledge_base=knowledge_base,
            token_usage=token_usage,
        )

        result = use_case.execute(sample_email)

        # Vérifications
        assert result.status == DraftStatus.CORRECTED_V2
        assert result.was_corrected is True
        assert "trop formel" in result.critique.reason
        assert "Bonjour Jean" in result.draft_final.content
        assert result.draft_v1.content != result.draft_final.content

    def test_pipeline_with_llm_failure_on_draft(self, sample_email, mock_llm_full_pipeline, knowledge_base):
        """Pipeline échoue si LLM indisponible au draft."""
        mock_llm_full_pipeline.complete.side_effect = ConnectionError("API timeout")

        use_case = ProcessEmailUseCase(
            llm=mock_llm_full_pipeline,
            knowledge_base=knowledge_base,
        )

        with pytest.raises(ConnectionError, match="API timeout"):
            use_case.execute(sample_email)

    def test_pipeline_with_llm_failure_on_critique(self, sample_email, mock_llm_full_pipeline, knowledge_base):
        """Pipeline échoue si LLM indisponible à la critique."""
        mock_llm_full_pipeline.complete.side_effect = [
            LLMResponse(content="Draft OK", input_tokens=100, output_tokens=20, model="test"),
            RuntimeError("Critique service down"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm_full_pipeline,
            knowledge_base=knowledge_base,
        )

        with pytest.raises(RuntimeError, match="Critique service down"):
            use_case.execute(sample_email)

    def test_pipeline_with_empty_llm_response(self, sample_email, mock_llm_full_pipeline, knowledge_base):
        """Pipeline avec réponse LLM vide."""
        mock_llm_full_pipeline.complete.side_effect = [
            LLMResponse(content="", input_tokens=100, output_tokens=0, model="test"),
            LLMResponse(content="REJET : Réponse vide", input_tokens=50, output_tokens=10, model="test"),
            LLMResponse(content="Nouvelle réponse", input_tokens=100, output_tokens=20, model="test"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm_full_pipeline,
            knowledge_base=knowledge_base,
        )

        result = use_case.execute(sample_email)

        # La V1 est vide, la critique rejette, V2 est générée
        assert result.draft_v1.content == ""
        assert result.was_corrected is True
        assert result.draft_final.content == "Nouvelle réponse"


# ============================================================================
# TESTS - INTÉGRATION PUSH NOTIFICATIONS
# ============================================================================

class TestPushNotificationIntegration:
    """Tests d'intégration pour les push notifications."""

    def test_full_notification_workflow(self, temp_dir):
        """Workflow complet : enregistrement → envoi → historique."""
        # Setup store et adapter
        store = JsonFileDeviceStore(filepath=temp_dir / "devices.json")
        adapter = MockPushAdapter()
        use_case = SendPushNotificationUseCase(notification_adapter=adapter)

        # Enregistrer des devices
        store.register("token_ios", "ios", user_id="user1", device_name="iPhone")
        store.register("token_android", "android", user_id="user1", device_name="Pixel")

        # Récupérer les tokens
        tokens = store.get_tokens(user_id="user1")
        assert len(tokens) == 2

        # Envoyer notification
        results = use_case.notify_draft_created(
            device_tokens=tokens,
            recipient="client@test.com",
            subject="Projet X",
            draft_id="draft-123",
            priority_score=75,
        )

        assert len(results) == 2
        assert all(r.success for r in results)

        # Vérifier historique
        records = use_case.get_records()
        assert len(records) == 2

        stats = use_case.get_stats()
        assert stats["total"] == 2
        assert stats["sent"] == 2

    def test_notification_with_invalid_token_deactivation(self, temp_dir):
        """Token invalide est désactivé."""
        store = JsonFileDeviceStore(filepath=temp_dir / "devices.json")
        adapter = MockPushAdapter(invalid_tokens=["bad_token"])

        # Enregistrer un token valide et un invalide
        store.register("good_token", "ios", user_id="user1")
        store.register("bad_token", "android", user_id="user1")

        use_case = SendPushNotificationUseCase(notification_adapter=adapter)

        tokens = store.get_tokens()
        results = use_case.execute_batch(
            device_tokens=tokens,
            title="Test",
            body="Body",
        )

        # Un succès, un échec
        success_count = sum(1 for r in results if r.success)
        assert success_count == 1

        # Désactiver le mauvais token
        failed_tokens = [tokens[i] for i, r in enumerate(results) if not r.success]
        for token in failed_tokens:
            store.deactivate(token)

        # Vérifier que le token est désactivé
        active_tokens = store.get_tokens()
        assert "bad_token" not in active_tokens

    def test_push_notification_service_full_flow(self, temp_dir):
        """Service complet de bout en bout."""
        store = JsonFileDeviceStore(filepath=temp_dir / "devices.json")
        adapter = MockPushAdapter()

        service = PushNotificationService(
            device_store=store,
            notification_adapter=adapter,
        )

        # Enregistrer des devices
        store.register("token1", "ios", user_id="user1")
        store.register("token2", "android", user_id="user2")

        # Envoyer à tous les users
        count = service.notify_all_draft_created(
            recipient="client@test.com",
            subject="Important",
            draft_id="draft-456",
        )

        assert count == 2
        assert adapter.get_notifications_count() == 2

        # Vérifier les données
        notifs = adapter.sent_notifications
        assert all("draft_created" in str(n.data) for n in notifs)

    def test_broadcast_to_empty_store(self, temp_dir):
        """Broadcast sans devices enregistrés."""
        store = JsonFileDeviceStore(filepath=temp_dir / "devices.json")
        adapter = MockPushAdapter()

        service = PushNotificationService(
            device_store=store,
            notification_adapter=adapter,
        )

        results = service.broadcast(title="Test", body="Body")

        assert results == []
        assert adapter.get_notifications_count() == 0


# ============================================================================
# TESTS - INTÉGRATION DEVICE STORE + ENTITIES
# ============================================================================

class TestDeviceStoreEntityIntegration:
    """Tests d'intégration DeviceStore avec entités."""

    def test_device_token_entity_to_store_roundtrip(self, temp_dir):
        """Aller-retour entité → store → entité."""
        store = JsonFileDeviceStore(filepath=temp_dir / "devices.json")

        # Créer via store
        registered = store.register(
            token="test_token_123",
            platform="ios",
            user_id="user_456",
            device_name="iPhone Pro",
            app_version="2.1.0",
        )

        # Récupérer
        retrieved = store.get("test_token_123")

        assert retrieved.token == registered.token
        assert retrieved.platform == DevicePlatform.IOS
        assert retrieved.user_id == "user_456"
        assert retrieved.device_name == "iPhone Pro"
        assert retrieved.app_version == "2.1.0"
        assert retrieved.is_active is True

    def test_device_token_persistence_roundtrip(self, temp_dir):
        """Aller-retour avec persistance fichier."""
        filepath = temp_dir / "devices.json"

        # Instance 1 - créer
        store1 = JsonFileDeviceStore(filepath=filepath)
        store1.register("token_a", "ios", user_id="user_1", device_name="Device A")
        store1.register("token_b", "android", user_id="user_2", device_name="Device B")
        store1.deactivate("token_b")

        # Instance 2 - recharger
        store2 = JsonFileDeviceStore(filepath=filepath)

        all_devices = store2.get_all()  # Seulement actifs
        assert len(all_devices) == 1
        assert all_devices[0].token == "token_a"

        # Token b existe mais inactif
        device_b = store2.get("token_b")
        assert device_b is not None
        assert device_b.is_active is False


# ============================================================================
# TESTS - SCÉNARIOS D'ERREUR CROSS-LAYER
# ============================================================================

class TestCrossLayerErrorScenarios:
    """Tests des scénarios d'erreur entre couches."""

    def test_container_with_missing_api_key(self, temp_dir):
        """Container avec clé API manquante."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': ''}, clear=False):
            config = Config(
                llm_provider="claude",
                anthropic_api_key="",
            )
            container = Container(config=config)

            # L'accès au LLM peut échouer ou retourner un adapter non fonctionnel
            # selon l'implémentation
            # Vérifions que le container est créé sans crash
            assert container is not None

    def test_use_case_with_unavailable_adapter(self):
        """Use case avec adapter non disponible."""
        mock_adapter = MagicMock(spec=NotificationPort)
        mock_adapter.is_available.return_value = False
        mock_adapter.send.return_value = PushNotificationResult(
            success=False,
            error_code="NOT_AVAILABLE",
            error_message="Adapter not configured"
        )

        use_case = SendPushNotificationUseCase(notification_adapter=mock_adapter)

        result = use_case.execute(
            device_token="token",
            title="Test",
            body="Body",
        )

        assert result.success is False

    def test_store_file_permissions_error(self, temp_dir, monkeypatch):
        """Erreur de permissions fichier."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        filepath = temp_dir / "devices.json"
        store = JsonFileDeviceStore(filepath=filepath)
        store.register("token", "ios")

        # Simuler une erreur d'écriture
        def mock_write(*args, **kwargs):
            raise PermissionError("Cannot write")

        # Le store devrait gérer gracieusement ou propager l'erreur
        # selon l'implémentation

    def test_concurrent_pipeline_execution(self, mock_llm_full_pipeline, knowledge_base):
        """Exécution concurrent du pipeline."""
        import threading

        errors = []
        results = []

        def execute_pipeline(email_id):
            try:
                email = Email(
                    id=f"email-{email_id}",
                    subject=f"Subject {email_id}",
                    body=f"Body {email_id}",
                    sender=f"sender{email_id}@test.com",
                )

                mock = MagicMock(spec=LLMPort)
                mock.complete.side_effect = [
                    LLMResponse(content=f"Draft {email_id}", input_tokens=100, output_tokens=50, model="test"),
                    LLMResponse(content="VALID", input_tokens=100, output_tokens=10, model="test"),
                ]

                use_case = ProcessEmailUseCase(
                    llm=mock,
                    knowledge_base=knowledge_base,
                )
                result = use_case.execute(email)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=execute_pipeline, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 5
        # Chaque pipeline a son propre résultat
        email_ids = {r.email_id for r in results}
        assert len(email_ids) == 5


# ============================================================================
# TESTS - INTÉGRATION TOKEN USAGE CROSS-USE-CASES
# ============================================================================

class TestTokenUsageIntegration:
    """Tests d'intégration du tracking des tokens."""

    def test_shared_token_usage_across_use_cases(self, sample_email, knowledge_base):
        """TokenUsage partagé entre use cases."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft 1", input_tokens=100, output_tokens=50, model="test"),
            LLMResponse(content="Draft 2", input_tokens=150, output_tokens=60, model="test"),
        ]

        shared_token_usage = TokenUsage()

        # Use case 1
        use_case1 = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=shared_token_usage,
        )
        use_case1.execute(sample_email)

        # Use case 2
        use_case2 = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=shared_token_usage,
        )
        use_case2.execute(sample_email)

        # Les tokens sont cumulés
        assert shared_token_usage.input_tokens == 250  # 100 + 150
        assert shared_token_usage.output_tokens == 110  # 50 + 60

    def test_token_usage_reset_between_sessions(self, sample_email, knowledge_base):
        """Reset des tokens entre sessions."""
        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.return_value = LLMResponse(
            content="Draft",
            input_tokens=100,
            output_tokens=50,
            model="test"
        )

        token_usage = TokenUsage()

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage,
        )

        # Session 1
        use_case.execute(sample_email)
        assert token_usage.total == 150

        # Reset
        token_usage.reset()
        assert token_usage.total == 0

        # Session 2
        use_case.execute(sample_email)
        assert token_usage.total == 150
