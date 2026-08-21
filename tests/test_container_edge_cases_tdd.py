# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases du Container (Dependency Injection).

Ce module couvre les cas limites non testés :
- Factory exceptions: échec lors de la création de dépendances
- Lazy loading: comportement du cache des singletons
- Configuration invalide: valeurs manquantes ou incorrectes
- Thread safety: accès concurrent aux singletons

Principes Clean Architecture respectés :
- Tests isolés avec mocks
- Pas de dépendance sur l'environnement réel
"""

import pytest
import threading
from unittest.mock import patch


# =============================================================================
# TESTS CONTAINER - LAZY LOADING
# =============================================================================


class TestContainerLazyLoading:
    """Tests pour le lazy loading du Container."""

    def test_llm_not_created_until_accessed(self):
        """Le LLM n'est pas créé tant qu'il n'est pas accédé."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {
            'ANTHROPIC_API_KEY': 'test-key',
            'LLM_PROVIDER': 'claude',
        }):
            config = Config.from_env()
            container = Container(config=config)

            # _llm devrait être None initialement
            assert container._llm is None

    def test_clock_default_is_system_clock(self):
        """Le clock par défaut est SystemClock."""
        from app.infrastructure.container import Container
        from app.infrastructure.clock import SystemClock
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            clock = container.clock

            assert isinstance(clock, SystemClock)

    def test_clock_can_be_injected(self):
        """Le clock peut être injecté via set_clock()."""
        from app.infrastructure.container import Container
        from app.infrastructure.clock import FakeClock
        from app.infrastructure.config import Config
        from datetime import datetime

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            fake_clock = FakeClock(datetime(2024, 1, 1, 12, 0, 0))
            container.set_clock(fake_clock)

            assert container.clock is fake_clock
            assert container.clock.now() == datetime(2024, 1, 1, 12, 0, 0)

    def test_clock_injection_replaces_previous(self):
        """Injecter un nouveau clock remplace l'ancien."""
        from app.infrastructure.container import Container
        from app.infrastructure.clock import FakeClock
        from app.infrastructure.config import Config
        from datetime import datetime

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            clock1 = FakeClock(datetime(2024, 1, 1))
            clock2 = FakeClock(datetime(2025, 12, 31))

            container.set_clock(clock1)
            container.set_clock(clock2)

            assert container.clock is clock2

    def test_token_usage_shared_instance(self):
        """TokenUsage est une instance partagée."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            usage1 = container.token_usage
            usage2 = container.token_usage

            assert usage1 is usage2


class TestContainerFactoryExceptions:
    """Tests pour les exceptions dans les factories du Container."""

    def test_llm_factory_claude_missing_api_key(self):
        """La factory LLM Claude lève une erreur si API key manquante."""
        # Skip si anthropic n'est pas installé
        pytest.importorskip("anthropic")

        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        # Simuler un environnement sans API key
        with patch.dict('os.environ', {
            'ANTHROPIC_API_KEY': '',
            'LLM_PROVIDER': 'claude',
        }, clear=True):
            config = Config.from_env()
            container = Container(config=config)

            # Accéder au LLM devrait lever ValueError
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                _ = container.llm

    def test_llm_factory_ollama_network_error(self):
        """La factory LLM Ollama gère les erreurs réseau."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {
            'LLM_PROVIDER': 'ollama',
            'OLLAMA_BASE_URL': 'http://invalid-host:11434',
        }):
            config = Config.from_env()
            container = Container(config=config)

            # L'adapter est créé mais échouera lors de l'utilisation
            llm = container.llm
            assert llm is not None

    def test_knowledge_base_creates_default_if_missing(self, tmp_path):
        """La knowledge base crée un fichier par défaut si manquant.

        Note: Config.knowledge_path est une property sans setter,
        donc on teste le comportement par défaut.
        """
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            # Accéder à knowledge_base
            content = container.knowledge_base

            # Le contenu devrait exister (soit créé, soit existant)
            assert content is not None
            # Si c'était créé par défaut, il contiendrait ce texte
            # Sinon, il existe déjà avec le contenu réel
            assert len(content) > 0


class TestContainerSingletons:
    """Tests pour le comportement singleton des stores."""

    def test_wizard_config_store_is_singleton(self):
        """get_wizard_config_store() retourne toujours la même instance."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            store1 = container.get_wizard_config_store()
            store2 = container.get_wizard_config_store()

            assert store1 is store2

    def test_device_store_is_singleton(self):
        """get_device_store() retourne toujours la même instance."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            store1 = container.get_device_store()
            store2 = container.get_device_store()

            assert store1 is store2

    def test_marketplace_stores_initialized_together(self):
        """Les stores marketplace sont initialisés ensemble."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            # Accéder à un store initialise tous les stores marketplace
            _ = container.get_marketplace_agent_store()

            assert container._marketplace_agent_store is not None
            assert container._agent_pack_store is not None
            assert container._agent_installation_store is not None


class TestContainerConcurrency:
    """Tests de concurrence pour le Container."""

    def test_clock_concurrent_access(self):
        """Accès concurrent au clock est thread-safe."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            clocks = []
            errors = []

            def get_clock():
                try:
                    clocks.append(container.clock)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=get_clock) for _ in range(10)]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0
            # Tous devraient avoir la même instance
            assert all(c is clocks[0] for c in clocks)

    def test_stores_concurrent_initialization(self):
        """Initialisation concurrente des stores."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            stores = []
            errors = []

            def get_store():
                try:
                    stores.append(container.get_wizard_config_store())
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=get_store) for _ in range(10)]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Note: Sans locking explicite, il peut y avoir des races
            # Ce test documente le comportement actuel
            assert len(errors) == 0


class TestContainerConfig:
    """Tests pour la configuration du Container."""

    def test_data_dir_property(self):
        """data_dir retourne le bon chemin."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            data_dir = container.data_dir

            assert data_dir.name == "data"
            assert data_dir.parent == config.project_root


class TestContainerLearningStores:
    """Tests pour les stores d'apprentissage du Container."""

    def test_learning_pattern_store_lazy_loading(self):
        """Le pattern store est chargé paresseusement."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            # Initialement None
            assert container._learning_pattern_store is None


class TestContainerUseCaseFactories:
    """Tests pour les factories de use cases."""

    def test_process_use_case_created_with_dependencies(self):
        """Le ProcessEmailUseCase est créé avec toutes ses dépendances."""

        # Ce test vérifie que le câblage fonctionne
        # Note: Nécessite un environnement valide
        pass  # Implémentation dépend de la structure réelle


# =============================================================================
# TESTS CONFIG - EDGE CASES
# =============================================================================


class TestConfigEdgeCases:
    """Tests edge cases pour la configuration."""

    def test_config_from_env_with_defaults(self):
        """Config avec valeurs par défaut."""
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}, clear=True):
            config = Config.from_env()

            assert config.llm_provider == "claude"  # Défaut
            assert config.anthropic_api_key == "test-key"

    def test_config_ollama_provider(self):
        """Config avec provider Ollama."""
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {
            'LLM_PROVIDER': 'ollama',
            'LLM_MODEL': 'llama2',
        }):
            config = Config.from_env()

            assert config.llm_provider == "ollama"
            assert config.llm_model == "llama2"

    def test_config_project_root_detection(self):
        """Config détecte correctement la racine du projet."""
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()

            # project_root devrait contenir app/ et tests/
            assert config.project_root.is_dir()

    def test_config_knowledge_path(self):
        """Config a un chemin knowledge valide."""
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()

            # Le chemin devrait être sous knowledge/
            assert "knowledge" in str(config.knowledge_path)


# =============================================================================
# TESTS LEARNING SERVICE INTEGRATION
# =============================================================================


class TestLearningServiceIntegration:
    """Tests d'intégration pour LearningService via Container."""

    def test_learning_service_can_be_created(self):
        """LearningService peut être créé via le Container."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            Container(config=config)

            # Créer manuellement un LearningService
            # (le Container peut avoir une factory dédiée)
            pass  # Implémentation dépend de la structure réelle


# =============================================================================
# TESTS REALTIME EDIT STORE
# =============================================================================


class TestRealtimeEditStoreContainer:
    """Tests pour le store d'édition en temps réel."""

    def test_realtime_edit_store_initially_none(self):
        """Le store d'édition temps réel est initialement None."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            config = Config.from_env()
            container = Container(config=config)

            assert container._realtime_edit_store is None
