# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour le Container DI (Dependency Injection).

Ce module teste le Container central qui:
- Crée les adapters (implémentations concrètes)
- Câble les use cases avec leurs dépendances
- Gère le cycle de vie des singletons (lazy loading)
"""

import pytest
from pathlib import Path
import tempfile
import shutil


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_data_dir():
    """Crée un répertoire temporaire pour les tests."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_config(temp_data_dir):
    """Configuration mockée avec répertoire de données temporaire.

    Utilise Ollama par défaut pour éviter la dépendance à anthropic.
    """
    from app.infrastructure.config import Config

    config = Config(
        project_root=temp_data_dir,
        llm_provider="ollama",
        llm_model="llama2",
        anthropic_api_key=None,
        ollama_base_url="http://localhost:11434",
        max_tokens_draft=1000,
        max_tokens_critique=500,
    )
    return config


@pytest.fixture
def mock_config_claude(temp_data_dir):
    """Configuration mockée avec Claude pour tests spécifiques."""
    from app.infrastructure.config import Config

    config = Config(
        project_root=temp_data_dir,
        llm_provider="claude",
        llm_model="claude-3-opus-20240229",
        anthropic_api_key="test-api-key",
        ollama_base_url="http://localhost:11434",
        max_tokens_draft=1000,
        max_tokens_critique=500,
    )
    return config


@pytest.fixture
def container(mock_config, temp_data_dir):
    """Crée un Container avec configuration mockée."""
    from app.infrastructure.container import Container

    # Créer la structure de répertoires
    (temp_data_dir / "data").mkdir(parents=True, exist_ok=True)
    (temp_data_dir / "knowledge").mkdir(parents=True, exist_ok=True)

    container = Container(config=mock_config)
    return container


# ============================================================================
# TESTS - CONTAINER INITIALIZATION
# ============================================================================

class TestContainerInitialization:
    """Tests d'initialisation du Container."""

    def test_container_creates_with_default_config(self):
        """Container se crée avec la configuration par défaut."""
        from app.infrastructure.container import Container

        container = Container()
        assert container.config is not None
        assert container._llm is None  # Lazy loading
        assert container._knowledge_base is None

    def test_container_creates_with_custom_config(self, mock_config):
        """Container se crée avec une configuration personnalisée."""
        from app.infrastructure.container import Container

        container = Container(config=mock_config)
        assert container.config == mock_config

    def test_container_lazy_loads_token_usage(self, container):
        """Token usage est initialisé avec valeurs par défaut."""
        from app.domain.entities import TokenUsage

        assert isinstance(container.token_usage, TokenUsage)
        assert container.token_usage.total == 0


# ============================================================================
# TESTS - LLM CREATION
# ============================================================================

class TestLLMCreation:
    """Tests de création du provider LLM."""

    def test_creates_claude_adapter_when_configured(self, temp_data_dir, mock_config_claude):
        """Crée un ClaudeAdapter si configuré."""
        pytest.importorskip("anthropic")
        from app.infrastructure.container import Container
        from app.adapters.llm import ClaudeAdapter

        (temp_data_dir / "knowledge").mkdir(parents=True, exist_ok=True)
        container = Container(config=mock_config_claude)
        llm = container.llm
        assert isinstance(llm, ClaudeAdapter)

    def test_creates_ollama_adapter_by_default(self, container):
        """Crée un OllamaAdapter avec configuration par défaut (Ollama)."""
        from app.adapters.llm import OllamaAdapter

        llm = container.llm
        assert isinstance(llm, OllamaAdapter)

    def test_llm_is_cached(self, container):
        """Le LLM est mis en cache (singleton)."""
        llm1 = container.llm
        llm2 = container.llm
        assert llm1 is llm2


# ============================================================================
# TESTS - KNOWLEDGE BASE
# ============================================================================

class TestKnowledgeBase:
    """Tests de chargement de la knowledge base."""

    def test_creates_default_kb_if_missing(self, container, temp_data_dir):
        """Crée une knowledge base par défaut si absente."""
        kb = container.knowledge_base
        assert kb is not None
        assert "Base de Connaissances" in kb

    def test_loads_existing_kb(self, container, temp_data_dir):
        """Charge une knowledge base existante."""
        # Créer un fichier KB
        kb_path = temp_data_dir / "knowledge" / "memoire.md"
        kb_path.parent.mkdir(parents=True, exist_ok=True)
        kb_path.write_text("# Custom KB\nTest content", encoding="utf-8")

        # Force reload
        container._knowledge_base = None
        kb = container.knowledge_base
        assert "Custom KB" in kb

    def test_kb_is_cached(self, container):
        """La knowledge base est mise en cache."""
        kb1 = container.knowledge_base
        kb2 = container.knowledge_base
        assert kb1 is kb2


# ============================================================================
# TESTS - CORE USE CASE FACTORIES
# ============================================================================

class TestCoreUseCaseFactories:
    """Tests des factories de use cases core."""

    def test_get_draft_use_case(self, container):
        """Crée un DraftEmailUseCase correctement câblé."""
        from app.application import DraftEmailUseCase

        use_case = container.get_draft_use_case()
        assert isinstance(use_case, DraftEmailUseCase)

    def test_get_critique_use_case(self, container):
        """Crée un CritiqueEmailUseCase correctement câblé."""
        from app.application import CritiqueEmailUseCase

        use_case = container.get_critique_use_case()
        assert isinstance(use_case, CritiqueEmailUseCase)

    def test_get_process_use_case(self, container):
        """Crée un ProcessEmailUseCase correctement câblé."""
        from app.application import ProcessEmailUseCase

        use_case = container.get_process_use_case()
        assert isinstance(use_case, ProcessEmailUseCase)

    def test_get_health_check_use_case(self, container):
        """Crée un HealthCheckUseCase correctement câblé."""
        from app.application import HealthCheckUseCase

        use_case = container.get_health_check_use_case()
        assert isinstance(use_case, HealthCheckUseCase)

    def test_get_complete_draft_use_case(self, container):
        """Crée un CompleteDraftUseCase correctement câblé."""
        from app.application import CompleteDraftUseCase

        use_case = container.get_complete_draft_use_case()
        assert isinstance(use_case, CompleteDraftUseCase)


# ============================================================================
# TESTS - STORE FACTORIES
# ============================================================================

class TestStoreFactories:
    """Tests des factories de stores."""

    def test_get_wizard_config_store(self, container):
        """Crée un WizardConfigStore."""
        from app.domain.ports import WizardConfigPort

        store = container.get_wizard_config_store()
        assert isinstance(store, WizardConfigPort)

    def test_wizard_store_is_singleton(self, container):
        """WizardConfigStore est un singleton."""
        store1 = container.get_wizard_config_store()
        store2 = container.get_wizard_config_store()
        assert store1 is store2

    def test_get_device_store(self, container):
        """Crée un DeviceStore."""
        from app.domain.ports import DeviceStorePort

        store = container.get_device_store()
        assert isinstance(store, DeviceStorePort)

    def test_get_cryptographer(self, container):
        """Retourne une instance de CryptographerPort."""
        from app.domain.ports import CryptographerPort

        cryptographer = container.get_cryptographer()
        assert isinstance(cryptographer, CryptographerPort)

    def test_cryptographer_is_singleton(self, container):
        """CryptographerPort est un singleton."""
        crypto1 = container.get_cryptographer()
        crypto2 = container.get_cryptographer()
        assert crypto1 is crypto2

    def test_cryptographer_can_encrypt_decrypt(self, container):
        """Le cryptographer retourne par le container fonctionne."""
        cryptographer = container.get_cryptographer()
        original = "secret message"
        encrypted = cryptographer.encrypt(original)
        decrypted = cryptographer.decrypt(encrypted)
        assert decrypted == original

    def test_cryptographer_uses_env_key_if_present(self, mock_config, temp_data_dir):
        """Le cryptographer utilise la cle depuis l'environnement si presente."""
        from cryptography.fernet import Fernet
        from app.infrastructure.container import Container
        import os

        # Generer une cle Fernet valide
        test_key = Fernet.generate_key().decode("utf-8")

        # Creer la structure de repertoires
        (temp_data_dir / "data").mkdir(parents=True, exist_ok=True)
        (temp_data_dir / "knowledge").mkdir(parents=True, exist_ok=True)

        # Patcher l'environnement
        original_key = os.environ.get("AGENTYS_ENCRYPTION_KEY")
        os.environ["AGENTYS_ENCRYPTION_KEY"] = test_key

        try:
            container = Container(config=mock_config)
            crypto = container.get_cryptographer()

            # Verifier que l'encrypt/decrypt fonctionne avec cette cle
            encrypted = crypto.encrypt("test")
            decrypted = crypto.decrypt(encrypted)
            assert decrypted == "test"

            # Creer un autre container, devrait utiliser la meme cle
            container2 = Container(config=mock_config)
            crypto2 = container2.get_cryptographer()

            # Les deux cryptographers doivent pouvoir se dechiffrer mutuellement
            decrypted2 = crypto2.decrypt(encrypted)
            assert decrypted2 == "test"
        finally:
            # Restaurer l'environnement
            if original_key is None:
                os.environ.pop("AGENTYS_ENCRYPTION_KEY", None)
            else:
                os.environ["AGENTYS_ENCRYPTION_KEY"] = original_key

    def test_cryptographer_without_env_key_generates_key(self, mock_config, temp_data_dir):
        """Le cryptographer genere une cle si aucune n'est dans l'environnement."""
        from app.infrastructure.container import Container
        import os

        # Creer la structure de repertoires
        (temp_data_dir / "data").mkdir(parents=True, exist_ok=True)
        (temp_data_dir / "knowledge").mkdir(parents=True, exist_ok=True)

        # S'assurer qu'il n'y a pas de cle dans l'environnement
        original_key = os.environ.pop("AGENTYS_ENCRYPTION_KEY", None)
        original_env = os.environ.pop("AGENTYS_ENV", None)

        try:
            container = Container(config=mock_config)
            crypto = container.get_cryptographer()

            # Verifier que l'encrypt/decrypt fonctionne
            encrypted = crypto.encrypt("test data")
            decrypted = crypto.decrypt(encrypted)
            assert decrypted == "test data"
        finally:
            # Restaurer l'environnement
            if original_key is not None:
                os.environ["AGENTYS_ENCRYPTION_KEY"] = original_key
            if original_env is not None:
                os.environ["AGENTYS_ENV"] = original_env

    def test_cryptographer_raises_in_production_without_key(self, mock_config, temp_data_dir):
        """Le cryptographer leve une erreur en production sans cle configuree."""
        from app.infrastructure.container import Container
        import os

        # Creer la structure de repertoires
        (temp_data_dir / "data").mkdir(parents=True, exist_ok=True)
        (temp_data_dir / "knowledge").mkdir(parents=True, exist_ok=True)

        # Sauvegarder l'environnement original
        original_key = os.environ.pop("AGENTYS_ENCRYPTION_KEY", None)
        original_fernet = os.environ.pop("AGENTYS_FERNET_KEY", None)
        original_oauth_key = os.environ.pop("OAUTH_TOKEN_ENCRYPTION_KEY", None)
        original_flask_env = os.environ.get("FLASK_ENV")

        try:
            # CASA #206 follow-up: prod detection is now centralized via
            # `is_production()` (FLASK_ENV / ENVIRONMENT / RAILWAY_ENVIRONMENT[_NAME]).
            # The cryptographer reads AGENTYS_FERNET_KEY or OAUTH_TOKEN_ENCRYPTION_KEY
            # (legacy alias) — no hex SQLCipher key collision.
            os.environ["FLASK_ENV"] = "production"

            container = Container(config=mock_config)

            # Doit fail-close en production sans cle Fernet
            with pytest.raises(RuntimeError) as exc_info:
                container.get_cryptographer()

            assert "AGENTYS_FERNET_KEY" in str(exc_info.value) or \
                   "OAUTH_TOKEN_ENCRYPTION_KEY" in str(exc_info.value)
        finally:
            # Restaurer l'environnement
            if original_key is not None:
                os.environ["AGENTYS_ENCRYPTION_KEY"] = original_key
            if original_fernet is not None:
                os.environ["AGENTYS_FERNET_KEY"] = original_fernet
            if original_oauth_key is not None:
                os.environ["OAUTH_TOKEN_ENCRYPTION_KEY"] = original_oauth_key
            if original_flask_env is not None:
                os.environ["FLASK_ENV"] = original_flask_env
            else:
                os.environ.pop("FLASK_ENV", None)

    def test_cryptographer_logs_warning_in_development_without_key(
        self, mock_config, temp_data_dir, caplog
    ):
        """Le cryptographer log un warning en dev sans cle configuree."""
        from app.infrastructure.container import Container
        import os
        import logging

        # Creer la structure de repertoires
        (temp_data_dir / "data").mkdir(parents=True, exist_ok=True)
        (temp_data_dir / "knowledge").mkdir(parents=True, exist_ok=True)

        # Sauvegarder l'environnement original
        original_key = os.environ.pop("AGENTYS_ENCRYPTION_KEY", None)
        original_env = os.environ.pop("AGENTYS_ENV", None)

        try:
            with caplog.at_level(logging.WARNING):
                container = Container(config=mock_config)
                container.get_cryptographer()

            # Verifier le warning de securite
            assert any(
                "SECURITY WARNING" in record.message
                for record in caplog.records
            )
        finally:
            # Restaurer l'environnement
            if original_key is not None:
                os.environ["AGENTYS_ENCRYPTION_KEY"] = original_key
            if original_env is not None:
                os.environ["AGENTYS_ENV"] = original_env


# ============================================================================
# TESTS - MARKETPLACE STORE FACTORIES
# ============================================================================

class TestMarketplaceStoreFactories:
    """Tests des factories de stores marketplace."""

    def test_get_marketplace_agent_store(self, container):
        """Crée un MarketplaceAgentStore."""
        from app.domain.ports import MarketplaceAgentPort

        store = container.get_marketplace_agent_store()
        assert isinstance(store, MarketplaceAgentPort)

    def test_get_agent_pack_store(self, container):
        """Crée un AgentPackStore."""
        from app.domain.ports import AgentPackPort

        store = container.get_agent_pack_store()
        assert isinstance(store, AgentPackPort)

    def test_get_agent_installation_store(self, container):
        """Crée un AgentInstallationStore."""
        from app.domain.ports import AgentInstallationPort

        store = container.get_agent_installation_store()
        assert isinstance(store, AgentInstallationPort)

    def test_get_agent_review_store(self, container):
        """Crée un AgentReviewStore."""
        from app.domain.ports import AgentReviewPort

        store = container.get_agent_review_store()
        assert isinstance(store, AgentReviewPort)

    def test_get_publisher_store(self, container):
        """Crée un PublisherStore."""
        from app.domain.ports import PublisherPort

        store = container.get_publisher_store()
        assert isinstance(store, PublisherPort)

    def test_marketplace_stores_are_singletons(self, container):
        """Tous les stores marketplace sont des singletons."""
        store1 = container.get_marketplace_agent_store()
        store2 = container.get_marketplace_agent_store()
        assert store1 is store2


# ============================================================================
# TESTS - FINE-TUNING STORE FACTORIES
# ============================================================================

class TestFineTuningStoreFactories:
    """Tests des factories de stores fine-tuning."""

    def test_get_user_correction_store(self, container):
        """Crée un UserCorrectionStore."""
        from app.domain.ports import UserCorrectionPort

        store = container.get_user_correction_store()
        assert isinstance(store, UserCorrectionPort)

    def test_get_user_feedback_store(self, container):
        """Crée un UserFeedbackStore."""
        from app.domain.ports import UserFeedbackPort

        store = container.get_user_feedback_store()
        assert isinstance(store, UserFeedbackPort)

    def test_get_correction_pattern_store(self, container):
        """Crée un CorrectionPatternStore."""
        from app.domain.ports import CorrectionPatternPort

        store = container.get_correction_pattern_store()
        assert isinstance(store, CorrectionPatternPort)

    def test_get_improvement_model_store(self, container):
        """Crée un ImprovementModelStore."""
        from app.domain.ports import ImprovementModelPort

        store = container.get_improvement_model_store()
        assert isinstance(store, ImprovementModelPort)

    def test_get_fine_tuning_session_store(self, container):
        """Crée un FineTuningSessionStore."""
        from app.domain.ports import FineTuningSessionPort

        store = container.get_fine_tuning_session_store()
        assert isinstance(store, FineTuningSessionPort)

    def test_get_fine_tuning_analyzer(self, container):
        """Crée un FineTuningAnalyzer."""
        from app.domain.ports import FineTuningAnalyzerPort

        analyzer = container.get_fine_tuning_analyzer()
        assert isinstance(analyzer, FineTuningAnalyzerPort)


# ============================================================================
# TESTS - MOBILE COMPANION STORE FACTORIES
# ============================================================================

class TestMobileCompanionStoreFactories:
    """Tests des factories de stores mobile companion."""

    def test_get_mobile_session_store(self, container):
        """Crée un MobileSessionStore."""
        from app.domain.ports import MobileSessionPort

        store = container.get_mobile_session_store()
        assert isinstance(store, MobileSessionPort)

    def test_get_mobile_sync_store(self, container):
        """Crée un MobileSyncStore."""
        from app.domain.ports import MobileSyncPort

        store = container.get_mobile_sync_store()
        assert isinstance(store, MobileSyncPort)

    def test_get_mobile_draft_action_store(self, container):
        """Crée un MobileDraftActionStore."""
        from app.domain.ports import MobileDraftActionPort

        store = container.get_mobile_draft_action_store()
        assert isinstance(store, MobileDraftActionPort)

    def test_get_mobile_analytics_store(self, container):
        """Crée un MobileAnalyticsStore."""
        from app.domain.ports import MobileAnalyticsPort

        store = container.get_mobile_analytics_store()
        assert isinstance(store, MobileAnalyticsPort)

    def test_get_mobile_preferences_store(self, container):
        """Crée un MobilePreferencesStore."""
        from app.domain.ports import MobileUserPreferencesPort

        store = container.get_mobile_preferences_store()
        assert isinstance(store, MobileUserPreferencesPort)

    def test_get_mobile_config_store(self, container):
        """Crée un MobileConfigStore."""
        from app.domain.ports import MobileAppConfigPort

        store = container.get_mobile_config_store()
        assert isinstance(store, MobileAppConfigPort)

    def test_mobile_stores_are_singletons(self, container):
        """Tous les stores mobile sont des singletons."""
        store1 = container.get_mobile_session_store()
        store2 = container.get_mobile_session_store()
        assert store1 is store2


# ============================================================================
# TESTS - WIZARD USE CASE FACTORIES
# ============================================================================

class TestWizardUseCaseFactories:
    """Tests des factories de use cases wizard."""

    def test_get_save_wizard_config_use_case(self, container):
        """Crée un SaveWizardConfigUseCase."""
        from app.application import SaveWizardConfigUseCase

        use_case = container.get_save_wizard_config_use_case()
        assert isinstance(use_case, SaveWizardConfigUseCase)

    def test_get_load_wizard_config_use_case(self, container):
        """Crée un LoadWizardConfigUseCase."""
        from app.application import LoadWizardConfigUseCase

        use_case = container.get_load_wizard_config_use_case()
        assert isinstance(use_case, LoadWizardConfigUseCase)

    def test_get_create_wizard_config_use_case(self, container):
        """Crée un CreateWizardConfigUseCase."""
        from app.application import CreateWizardConfigUseCase

        use_case = container.get_create_wizard_config_use_case()
        assert isinstance(use_case, CreateWizardConfigUseCase)

    def test_get_toggle_agent_use_case(self, container):
        """Crée un ToggleAgentUseCase."""
        from app.application import ToggleAgentUseCase

        use_case = container.get_toggle_agent_use_case()
        assert isinstance(use_case, ToggleAgentUseCase)


# ============================================================================
# TESTS - MARKETPLACE USE CASE FACTORIES
# ============================================================================

class TestMarketplaceUseCaseFactories:
    """Tests des factories de use cases marketplace."""

    def test_get_register_publisher_use_case(self, container):
        """Crée un RegisterPublisherUseCase."""
        from app.application import RegisterPublisherUseCase

        use_case = container.get_register_publisher_use_case()
        assert isinstance(use_case, RegisterPublisherUseCase)

    def test_get_search_agents_use_case(self, container):
        """Crée un SearchAgentsUseCase."""
        from app.application import SearchAgentsUseCase

        use_case = container.get_search_agents_use_case()
        assert isinstance(use_case, SearchAgentsUseCase)

    def test_get_install_agent_use_case(self, container):
        """Crée un InstallAgentUseCase."""
        from app.application import InstallAgentUseCase

        use_case = container.get_install_agent_use_case()
        assert isinstance(use_case, InstallAgentUseCase)


# ============================================================================
# TESTS - FINE-TUNING USE CASE FACTORIES
# ============================================================================

class TestFineTuningUseCaseFactories:
    """Tests des factories de use cases fine-tuning."""

    def test_get_record_correction_use_case(self, container):
        """Crée un RecordCorrectionUseCase."""
        from app.application import RecordCorrectionUseCase

        use_case = container.get_record_correction_use_case()
        assert isinstance(use_case, RecordCorrectionUseCase)

    def test_get_extract_patterns_use_case(self, container):
        """Crée un ExtractPatternsUseCase."""
        from app.application import ExtractPatternsUseCase

        use_case = container.get_extract_patterns_use_case()
        assert isinstance(use_case, ExtractPatternsUseCase)

    def test_get_fine_tuning_stats_use_case(self, container):
        """Crée un GetFineTuningStatsUseCase."""
        from app.application import GetFineTuningStatsUseCase

        use_case = container.get_fine_tuning_stats_use_case()
        assert isinstance(use_case, GetFineTuningStatsUseCase)


# ============================================================================
# TESTS - MOBILE COMPANION USE CASE FACTORIES
# ============================================================================

class TestMobileCompanionUseCaseFactories:
    """Tests des factories de use cases mobile companion."""

    def test_get_start_mobile_session_use_case(self, container):
        """Crée un StartMobileSessionUseCase."""
        from app.application import StartMobileSessionUseCase

        use_case = container.get_start_mobile_session_use_case()
        assert isinstance(use_case, StartMobileSessionUseCase)

    def test_get_sync_mobile_data_use_case(self, container):
        """Crée un SyncMobileDataUseCase."""
        from app.application import SyncMobileDataUseCase

        use_case = container.get_sync_mobile_data_use_case()
        assert isinstance(use_case, SyncMobileDataUseCase)

    def test_get_mobile_companion_service(self, container):
        """Crée un MobileCompanionService."""
        from app.application import MobileCompanionService

        service = container.get_mobile_companion_service()
        assert isinstance(service, MobileCompanionService)


# ============================================================================
# TESTS - SINGLETON PATTERN
# ============================================================================

class TestSingletonPattern:
    """Tests du pattern singleton global."""

    def test_get_container_returns_singleton(self):
        """get_container() retourne le même container."""
        from app.infrastructure.container import get_container, reset_container

        reset_container()
        container1 = get_container()
        container2 = get_container()
        assert container1 is container2
        reset_container()

    def test_reset_container_clears_singleton(self):
        """reset_container() efface le singleton."""
        from app.infrastructure.container import get_container, reset_container

        container1 = get_container()
        reset_container()
        container2 = get_container()
        assert container1 is not container2
        reset_container()


# ============================================================================
# TESTS - DATA DIRECTORY
# ============================================================================

class TestDataDirectory:
    """Tests de la gestion du répertoire de données."""

    def test_data_dir_property(self, container, temp_data_dir):
        """data_dir retourne le bon chemin."""
        expected = temp_data_dir / "data"
        assert container.data_dir == expected

    def test_stores_create_directories(self, container, temp_data_dir):
        """Les stores créent leurs répertoires."""
        # Accéder aux stores pour déclencher la création des répertoires
        container.get_marketplace_agent_store()
        container.get_mobile_session_store()

        assert (temp_data_dir / "data" / "marketplace").exists()
        assert (temp_data_dir / "data" / "mobile").exists()
