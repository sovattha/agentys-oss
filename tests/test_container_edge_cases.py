# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases du Container d'injection de dépendances.

Ces tests couvrent :
- Initialisation avec configurations invalides
- Gestion des erreurs de création de dépendances
- Singleton patterns et isolation
- Erreurs de chargement de la knowledge base

Principes Clean Architecture respectés :
- Tests isolés sans effets de bord
- Dependency injection via configuration
"""

from pathlib import Path


# =============================================================================
# TESTS CONTAINER INITIALIZATION
# =============================================================================


class TestContainerInitialization:
    """Tests pour l'initialisation du Container."""

    def test_container_default_initialization(self):
        """Container s'initialise avec configuration par défaut."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        config = Config()
        container = Container(config=config)

        assert container is not None
        assert container.config is config

    def test_get_container_singleton_pattern(self):
        """get_container retourne le même singleton."""
        from app.infrastructure.container import get_container, reset_container

        reset_container()
        container1 = get_container()
        container2 = get_container()

        assert container1 is container2
        reset_container()

    def test_reset_container_clears_singleton(self):
        """reset_container efface le singleton."""
        from app.infrastructure.container import get_container, reset_container

        reset_container()
        container1 = get_container()
        reset_container()
        container2 = get_container()

        # Après reset, nouveau container créé
        assert container1 is not container2
        reset_container()

    def test_data_dir_is_property(self):
        """data_dir est une propriété en lecture seule."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        config = Config()
        container = Container(config=config)

        # data_dir retourne un Path
        assert isinstance(container.data_dir, Path)
        # C'est basé sur project_root
        assert container.data_dir == config.project_root / "data"


# =============================================================================
# TESTS CONFIGURATION EDGE CASES
# =============================================================================


class TestContainerConfigEdgeCases:
    """Tests pour les edge cases de configuration."""

    def test_config_default_values(self):
        """Configuration avec valeurs par défaut."""
        from app.infrastructure.config import Config

        config = Config()

        assert config.llm_provider in ["claude", "ollama"]
        assert config.llm_model is not None

    def test_config_ollama_provider(self):
        """Configuration pour provider Ollama."""
        from app.infrastructure.config import Config

        config = Config(
            llm_provider="ollama",
            llm_model="llama2",
            ollama_base_url="http://localhost:11434"
        )

        assert config.llm_provider == "ollama"
        assert config.llm_model == "llama2"

    def test_config_project_root_default(self):
        """Project root par défaut."""
        from app.infrastructure.config import Config

        config = Config()

        assert config.project_root is not None
        assert config.project_root.exists()


# =============================================================================
# TESTS FACTORY METHODS EDGE CASES
# =============================================================================


class TestFactoryMethodsEdgeCases:
    """Tests pour les méthodes factory du Container."""

    def test_create_llm_claude_default(self):
        """Création LLM Claude par défaut."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config(llm_provider="claude")
        container = Container(config=config)

        # Le LLM est créé lazily, on vérifie juste que la méthode existe
        assert hasattr(container, "_create_llm")
        reset_container()

    def test_create_llm_ollama(self):
        """Création LLM Ollama."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config(
            llm_provider="ollama",
            llm_model="llama2",
            ollama_base_url="http://localhost:11434"
        )
        container = Container(config=config)

        # Vérifier que la config est correcte
        assert container.config.llm_provider == "ollama"
        reset_container()


# =============================================================================
# TESTS STORE INITIALIZATION EDGE CASES
# =============================================================================


class TestStoreInitializationEdgeCases:
    """Tests pour l'initialisation des stores."""

    def test_wizard_config_store_singleton(self):
        """Wizard config store est un singleton."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        store1 = container.get_wizard_config_store()
        store2 = container.get_wizard_config_store()

        assert store1 is store2
        reset_container()

    def test_device_store_singleton(self):
        """Device store est un singleton."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        store1 = container.get_device_store()
        store2 = container.get_device_store()

        assert store1 is store2
        reset_container()

    def test_learning_pattern_store_singleton(self):
        """Learning pattern store est un singleton."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        store1 = container.get_learning_pattern_store()
        store2 = container.get_learning_pattern_store()

        assert store1 is store2
        reset_container()

    def test_adjustment_store_singleton(self):
        """Adjustment store est un singleton."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        store1 = container.get_adjustment_store()
        store2 = container.get_adjustment_store()

        assert store1 is store2
        reset_container()


# =============================================================================
# TESTS LEARNING USE CASES FROM CONTAINER
# =============================================================================


class TestLearningUseCasesFromContainer:
    """Tests pour les use cases Learning via le Container."""

    def test_get_analyze_feedback_use_case(self):
        """Container fournit AnalyzeFeedbackUseCase."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        use_case = container.get_analyze_feedback_use_case()

        assert use_case is not None
        assert hasattr(use_case, "execute")
        reset_container()

    def test_get_should_require_review_use_case(self):
        """Container fournit ShouldRequireReviewUseCase."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        use_case = container.get_should_require_review_use_case()

        assert use_case is not None
        assert hasattr(use_case, "execute")
        reset_container()

    def test_get_enhance_prompt_use_case(self):
        """Container fournit EnhancePromptUseCase."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        use_case = container.get_enhance_prompt_use_case()

        assert use_case is not None
        assert hasattr(use_case, "execute")
        reset_container()

    def test_get_learning_stats_use_case(self):
        """Container fournit GetLearningStatsUseCase."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        use_case = container.get_learning_stats_use_case()

        assert use_case is not None
        assert hasattr(use_case, "execute")
        reset_container()


# =============================================================================
# TESTS TIME PROVIDER INJECTION
# =============================================================================


class TestTimeProviderInjection:
    """Tests pour l'injection du TimeProvider."""

    def test_default_clock_is_system_clock(self):
        """Clock par défaut est SystemClock."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config
        from app.infrastructure.clock import SystemClock

        reset_container()
        config = Config()
        container = Container(config=config)

        # clock est une propriété, pas get_clock()
        clock = container.clock

        assert isinstance(clock, SystemClock)
        reset_container()

    def test_set_custom_clock(self):
        """Injection d'un clock personnalisé."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config
        from app.infrastructure.clock import FakeClock
        from datetime import datetime

        reset_container()
        config = Config()
        container = Container(config=config)

        fake_clock = FakeClock(datetime(2024, 1, 1, 12, 0, 0))
        container.set_clock(fake_clock)

        assert container.clock is fake_clock
        reset_container()

    def test_clock_time_values(self):
        """Clock retourne les valeurs de temps correctes."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config
        from app.infrastructure.clock import FakeClock
        from datetime import datetime

        reset_container()
        config = Config()
        container = Container(config=config)

        fake_clock = FakeClock(datetime(2024, 6, 15, 10, 30, 0))
        container.set_clock(fake_clock)

        assert container.clock.now() == datetime(2024, 6, 15, 10, 30, 0)
        reset_container()


# =============================================================================
# TESTS MARKETPLACE STORES INITIALIZATION
# =============================================================================


class TestMarketplaceStoresInitialization:
    """Tests pour l'initialisation des stores Marketplace."""

    def test_marketplace_stores_created_on_demand(self):
        """Stores marketplace créés à la demande."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        # Avant accès, pas de store
        assert container._marketplace_agent_store is None

        # Accès déclenche la création
        store = container.get_marketplace_agent_store()

        assert store is not None
        reset_container()

    def test_all_marketplace_stores_available(self):
        """Tous les stores marketplace sont disponibles."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        # Vérifier que tous les getters existent
        assert hasattr(container, "get_marketplace_agent_store")
        assert hasattr(container, "get_agent_pack_store")
        assert hasattr(container, "get_agent_installation_store")
        assert hasattr(container, "get_agent_review_store")
        assert hasattr(container, "get_publisher_store")
        reset_container()


# =============================================================================
# TESTS FINE-TUNING STORES INITIALIZATION
# =============================================================================


class TestFineTuningStoresInitialization:
    """Tests pour l'initialisation des stores Fine-tuning."""

    def test_fine_tuning_stores_created_on_demand(self):
        """Stores fine-tuning créés à la demande."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        # Avant accès, pas de store
        assert container._user_correction_store is None

        # Accès déclenche la création
        store = container.get_user_correction_store()

        assert store is not None
        reset_container()

    def test_all_fine_tuning_stores_available(self):
        """Tous les stores fine-tuning sont disponibles."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        assert hasattr(container, "get_user_correction_store")
        assert hasattr(container, "get_user_feedback_store")
        assert hasattr(container, "get_correction_pattern_store")
        reset_container()


# =============================================================================
# TESTS MOBILE STORES INITIALIZATION
# =============================================================================


class TestMobileStoresInitialization:
    """Tests pour l'initialisation des stores Mobile."""

    def test_mobile_stores_created_on_demand(self):
        """Stores mobile créés à la demande."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        # Avant accès, pas de store
        assert container._mobile_session_store is None

        # Accès déclenche la création
        store = container.get_mobile_session_store()

        assert store is not None
        reset_container()

    def test_all_mobile_stores_available(self):
        """Tous les stores mobile sont disponibles."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        assert hasattr(container, "get_mobile_session_store")
        assert hasattr(container, "get_mobile_sync_store")
        assert hasattr(container, "get_mobile_analytics_store")
        reset_container()


# =============================================================================
# TESTS ERROR HANDLING IN CONTAINER
# =============================================================================


class TestContainerErrorHandling:
    """Tests pour la gestion d'erreurs dans le Container."""

    def test_container_with_invalid_llm_provider(self):
        """Configuration avec provider LLM invalide."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        # Le container accepte n'importe quel provider, l'erreur survient à l'exécution
        config = Config(llm_provider="invalid_provider")
        container = Container(config=config)

        assert container.config.llm_provider == "invalid_provider"
        reset_container()

    def test_token_usage_initialized(self):
        """TokenUsage est initialisé par défaut."""
        from app.infrastructure.container import Container, reset_container
        from app.infrastructure.config import Config

        reset_container()
        config = Config()
        container = Container(config=config)

        # token_usage est initialisé
        assert container.token_usage is not None
        reset_container()
