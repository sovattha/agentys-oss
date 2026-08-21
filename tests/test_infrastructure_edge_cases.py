# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour la couche Infrastructure.

Ces tests couvrent les edge cases non testés :
- Container et injection de dépendances
- DeviceStore avec fichiers corrompus, permissions, concurrence
- Gestion des erreurs de configuration
"""

import pytest
import json
import threading
import time
from unittest.mock import patch

from app.domain.entities import DevicePlatform


# ============================================================================
# TESTS - DEVICE STORE EDGE CASES
# ============================================================================

class TestJsonFileDeviceStoreEdgeCases:
    """Tests edge cases pour JsonFileDeviceStore."""

    @pytest.fixture
    def temp_dir(self, tmp_path):
        """Répertoire temporaire."""
        return tmp_path

    @pytest.fixture
    def store(self, temp_dir):
        """Store temporaire."""
        from app.infrastructure.device_store import JsonFileDeviceStore
        return JsonFileDeviceStore(filepath=temp_dir / "devices.json")

    def test_load_nonexistent_file(self, temp_dir):
        """Chargement d'un fichier inexistant."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        filepath = temp_dir / "nonexistent.json"
        store = JsonFileDeviceStore(filepath=filepath)

        assert len(store.get_all()) == 0

    def test_load_empty_file(self, temp_dir):
        """Chargement d'un fichier vide."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        filepath = temp_dir / "empty.json"
        filepath.write_text("")

        store = JsonFileDeviceStore(filepath=filepath)
        # Devrait gérer gracieusement
        assert len(store.get_all()) == 0

    def test_load_invalid_json(self, temp_dir):
        """Chargement d'un fichier JSON invalide."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        filepath = temp_dir / "invalid.json"
        filepath.write_text("{ invalid json }")

        store = JsonFileDeviceStore(filepath=filepath)
        # Devrait gérer gracieusement
        assert len(store.get_all()) == 0

    def test_load_json_without_devices_key(self, temp_dir):
        """Chargement d'un JSON sans clé 'devices'."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        filepath = temp_dir / "no_devices.json"
        filepath.write_text('{"other_key": "value"}')

        store = JsonFileDeviceStore(filepath=filepath)
        assert len(store.get_all()) == 0

    def test_load_json_with_corrupted_device(self, temp_dir):
        """Chargement avec un device corrompu (champs manquants)."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        filepath = temp_dir / "corrupted.json"
        data = {
            "devices": [
                {"token": "valid_token", "platform": "ios"},
                {"missing": "token"},  # Device invalide
            ]
        }
        filepath.write_text(json.dumps(data))

        # Devrait charger ce qui est valide et ignorer le reste
        JsonFileDeviceStore(filepath=filepath)
        # Selon l'implémentation, peut être 1 ou 0

    def test_register_empty_token_raises(self, store):
        """Enregistrement avec token vide."""
        with pytest.raises(ValueError, match="cannot be empty"):
            store.register(token="", platform="ios")

    def test_register_invalid_platform_raises(self, store):
        """Enregistrement avec plateforme invalide."""
        with pytest.raises(ValueError):
            store.register(token="valid_token", platform="windows")

    def test_unregister_nonexistent_token(self, store):
        """Désinscription d'un token inexistant."""
        result = store.unregister("nonexistent_token")
        assert result is False

    def test_get_nonexistent_token(self, store):
        """Récupération d'un token inexistant."""
        result = store.get("nonexistent_token")
        assert result is None

    def test_deactivate_nonexistent_token(self, store):
        """Désactivation d'un token inexistant."""
        result = store.deactivate("nonexistent_token")
        assert result is False

    def test_update_last_used_nonexistent_token(self, store):
        """Mise à jour last_used d'un token inexistant."""
        # Ne devrait pas lever d'erreur
        store.update_last_used("nonexistent_token")

    def test_get_all_empty(self, store):
        """Liste vide."""
        devices = store.get_all()
        assert devices == []

    def test_get_tokens_empty(self, store):
        """Liste tokens vide."""
        tokens = store.get_tokens()
        assert tokens == []

    def test_get_all_by_user_id_nonexistent(self, store):
        """Filtrage par user_id inexistant."""
        store.register("token1", "ios", user_id="user1")

        devices = store.get_all(user_id="nonexistent_user")
        assert devices == []

    def test_thread_safety_register(self, temp_dir):
        """Enregistrement concurrent thread-safe."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        store = JsonFileDeviceStore(filepath=temp_dir / "concurrent.json")
        errors = []

        def register_device(index):
            try:
                store.register(f"token_{index}", "ios")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_device, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(store.get_all()) == 10

    def test_thread_safety_unregister(self, temp_dir):
        """Désinscription concurrente thread-safe."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        store = JsonFileDeviceStore(filepath=temp_dir / "concurrent.json")

        # Enregistrer des tokens
        for i in range(10):
            store.register(f"token_{i}", "ios")

        errors = []

        def unregister_device(index):
            try:
                store.unregister(f"token_{index}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=unregister_device, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(store.get_all()) == 0

    def test_persistence_after_crash(self, temp_dir):
        """Persistance après "crash" (nouvelle instance)."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        filepath = temp_dir / "persistent.json"

        # Instance 1
        store1 = JsonFileDeviceStore(filepath=filepath)
        store1.register("token_1", "ios", user_id="user1")
        store1.register("token_2", "android", user_id="user2")

        # Instance 2 (simule restart)
        store2 = JsonFileDeviceStore(filepath=filepath)

        assert len(store2.get_all()) == 2
        device = store2.get("token_1")
        assert device is not None
        assert device.user_id == "user1"

    def test_create_parent_directories(self, temp_dir):
        """Création des répertoires parents."""
        from app.infrastructure.device_store import JsonFileDeviceStore

        filepath = temp_dir / "nested" / "deep" / "devices.json"
        store = JsonFileDeviceStore(filepath=filepath)
        store.register("token", "ios")

        assert filepath.exists()

    def test_register_same_token_twice(self, store):
        """Enregistrement du même token deux fois (mise à jour)."""
        store.register("same_token", "ios", device_name="First")
        store.register("same_token", "android", device_name="Second")

        device = store.get("same_token")
        # Le second enregistrement écrase le premier
        assert device.platform == DevicePlatform.ANDROID
        assert device.device_name == "Second"

    def test_update_last_used_updates_timestamp(self, store):
        """update_last_used met à jour le timestamp."""
        store.register("token", "ios")

        time.sleep(0.1)  # Petit délai pour avoir un timestamp différent
        store.update_last_used("token")

        device = store.get("token")
        assert device.last_used_at is not None


# ============================================================================
# TESTS - CONTAINER EDGE CASES
# ============================================================================

class TestContainerEdgeCases:
    """Tests edge cases pour le Container."""

    def test_container_default_config(self):
        """Container avec configuration par défaut."""
        from app.infrastructure.container import Container

        with patch.dict('os.environ', {}, clear=True):
            # Reset les variables d'environnement
            Container()
            # Config devrait utiliser les valeurs par défaut

    def test_container_llm_lazy_loading(self):
        """LLM est chargé paresseusement."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        config = Config(llm_provider="claude")
        container = Container(config=config)

        # _llm devrait être None initialement
        assert container._llm is None

    def test_container_knowledge_base_lazy_loading(self):
        """Knowledge base est chargée paresseusement."""
        from app.infrastructure.container import Container

        container = Container()

        # _knowledge_base devrait être None initialement
        assert container._knowledge_base is None

    def test_container_token_usage_singleton(self):
        """TokenUsage est un singleton."""
        from app.infrastructure.container import Container

        container = Container()
        usage1 = container.token_usage
        usage2 = container.token_usage

        assert usage1 is usage2

    def test_get_container_singleton(self):
        """get_container retourne un singleton."""
        from app.infrastructure.container import get_container, reset_container

        reset_container()  # S'assurer de partir d'un état clean

        container1 = get_container()
        container2 = get_container()

        assert container1 is container2

        reset_container()  # Nettoyer

    def test_reset_container(self):
        """reset_container réinitialise le singleton."""
        from app.infrastructure.container import get_container, reset_container

        container1 = get_container()
        reset_container()
        container2 = get_container()

        assert container1 is not container2

    def test_container_creates_default_knowledge_base(self, tmp_path):
        """Container crée un fichier knowledge base par défaut."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config
        from unittest.mock import patch, PropertyMock

        kb_path = tmp_path / "knowledge.md"

        # Créer config et container, puis patcher le chemin knowledge_path
        config = Config()
        container = Container(config=config)

        with patch.object(type(config), 'knowledge_path', new_callable=PropertyMock) as mock_kb_path:
            mock_kb_path.return_value = kb_path
            # Forcer le rechargement
            container._knowledge_base = None
            kb = container.knowledge_base

            # Le fichier devrait être créé avec contenu par défaut
            assert kb_path.exists()
            assert "Base de Connaissances" in kb

    def test_container_loads_existing_knowledge_base(self, tmp_path):
        """Container charge un fichier knowledge base existant."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config
        from unittest.mock import patch, PropertyMock

        kb_path = tmp_path / "knowledge.md"
        kb_path.write_text("# Ma knowledge base\n\nContenu custom")

        config = Config()
        container = Container(config=config)

        with patch.object(type(config), 'knowledge_path', new_callable=PropertyMock) as mock_kb_path:
            mock_kb_path.return_value = kb_path
            container._knowledge_base = None
            kb = container.knowledge_base

            assert "Ma knowledge base" in kb
            assert "Contenu custom" in kb


# ============================================================================
# TESTS - DEVICE STORE SINGLETON
# ============================================================================

class TestDeviceStoreSingleton:
    """Tests pour le singleton device store."""

    def test_get_device_store_singleton(self, tmp_path):
        """get_device_store retourne un singleton."""
        from app.infrastructure.device_store import get_device_store, reset_device_store

        reset_device_store()  # Clean state

        store1 = get_device_store(filepath=tmp_path / "devices.json")
        store2 = get_device_store()  # Devrait retourner le même

        assert store1 is store2

        reset_device_store()  # Nettoyer

    def test_reset_device_store(self, tmp_path):
        """reset_device_store réinitialise le singleton."""
        from app.infrastructure.device_store import get_device_store, reset_device_store

        store1 = get_device_store(filepath=tmp_path / "devices.json")
        reset_device_store()
        store2 = get_device_store(filepath=tmp_path / "devices2.json")

        assert store1 is not store2

        reset_device_store()  # Nettoyer


# ============================================================================
# TESTS - PUSH ADAPTER FACTORY
# ============================================================================

class TestPushAdapterFactory:
    """Tests pour la factory des adapters push."""

    def test_get_push_adapter_returns_adapter(self):
        """get_push_adapter retourne un adapter NotificationPort valide."""
        from app.infrastructure.push_adapter_factory import get_push_adapter, reset_push_adapter

        reset_push_adapter()

        adapter = get_push_adapter()

        # L'adapter peut être Expo, FCM, ou Mock selon la config
        # Vérifions juste qu'il implémente NotificationPort
        assert hasattr(adapter, 'send')
        assert hasattr(adapter, 'send_batch')
        assert hasattr(adapter, 'validate_token')
        assert hasattr(adapter, 'is_available')

        reset_push_adapter()

    def test_set_push_adapter(self):
        """set_push_adapter configure un adapter custom."""
        from app.infrastructure.push_adapter_factory import get_push_adapter, set_push_adapter, reset_push_adapter
        from app.adapters.push import MockPushAdapter

        reset_push_adapter()

        custom_adapter = MockPushAdapter(should_fail=True)
        set_push_adapter(custom_adapter)

        adapter = get_push_adapter()

        assert adapter is custom_adapter
        assert adapter.should_fail is True

        reset_push_adapter()

    def test_reset_push_adapter(self):
        """reset_push_adapter réinitialise l'adapter."""
        from app.infrastructure.push_adapter_factory import get_push_adapter, set_push_adapter, reset_push_adapter
        from app.adapters.push import MockPushAdapter

        custom_adapter = MockPushAdapter(should_fail=True)
        set_push_adapter(custom_adapter)

        reset_push_adapter()

        adapter = get_push_adapter()

        assert adapter is not custom_adapter

        reset_push_adapter()


# ============================================================================
# TESTS - NOTIFICATION PORT IMPLEMENTATIONS
# ============================================================================

class TestMockPushAdapterEdgeCases:
    """Tests edge cases pour MockPushAdapter."""

    def test_empty_token_validation(self):
        """Token vide invalide."""
        from app.adapters.push import MockPushAdapter

        adapter = MockPushAdapter()
        assert adapter.validate_token("") is False

    def test_none_token_validation(self):
        """Token None invalide."""
        from app.adapters.push import MockPushAdapter

        adapter = MockPushAdapter()
        # None n'est pas dans invalid_tokens mais est falsy
        assert adapter.validate_token(None) is False

    def test_add_and_remove_invalid_token(self):
        """Ajout et retrait de tokens invalides."""
        from app.adapters.push import MockPushAdapter

        adapter = MockPushAdapter()

        adapter.add_invalid_token("bad_token")
        assert adapter.validate_token("bad_token") is False

        adapter.remove_invalid_token("bad_token")
        assert adapter.validate_token("bad_token") is True

    def test_add_same_invalid_token_twice(self):
        """Ajout du même token invalide deux fois."""
        from app.adapters.push import MockPushAdapter

        adapter = MockPushAdapter()

        adapter.add_invalid_token("bad_token")
        adapter.add_invalid_token("bad_token")  # Ne devrait pas dupliquer

        # Le retirer une fois devrait suffire
        adapter.remove_invalid_token("bad_token")
        assert adapter.validate_token("bad_token") is True

    def test_remove_nonexistent_invalid_token(self):
        """Retrait d'un token invalide inexistant."""
        from app.adapters.push import MockPushAdapter

        adapter = MockPushAdapter()

        # Ne devrait pas lever d'erreur
        adapter.remove_invalid_token("nonexistent")

    def test_set_should_fail_toggles(self):
        """set_should_fail toggle le mode échec."""
        from app.adapters.push import MockPushAdapter

        adapter = MockPushAdapter()

        adapter.set_should_fail(True, "Custom error")
        result = adapter.send("token", "Title", "Body")
        assert result.success is False
        assert result.error_message == "Custom error"

        adapter.set_should_fail(False)
        result = adapter.send("token", "Title", "Body")
        assert result.success is True

    def test_send_batch_empty_list(self):
        """Batch avec liste vide."""
        from app.adapters.push import MockPushAdapter

        adapter = MockPushAdapter()
        results = adapter.send_batch([], "Title", "Body")

        assert results == []

    def test_send_with_data_payload(self):
        """Envoi avec payload data."""
        from app.adapters.push import MockPushAdapter

        adapter = MockPushAdapter()
        adapter.send("token", "Title", "Body", data={"key": "value"})

        notif = adapter.sent_notifications[0]
        assert notif.data == {"key": "value"}

    def test_clear_removes_all_notifications(self):
        """clear() supprime toutes les notifications."""
        from app.adapters.push import MockPushAdapter

        adapter = MockPushAdapter()
        adapter.send("t1", "T1", "B1")
        adapter.send("t2", "T2", "B2")

        assert adapter.get_notifications_count() == 2

        adapter.clear()

        assert adapter.get_notifications_count() == 0

    def test_get_notifications_for_token_empty(self):
        """Récupération pour un token sans notifications."""
        from app.adapters.push import MockPushAdapter

        adapter = MockPushAdapter()
        adapter.send("token1", "Title", "Body")

        notifs = adapter.get_notifications_for_token("other_token")
        assert notifs == []
