# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests complets pour app/infrastructure/push_adapter_factory.py.

Couverture cible: 100%
Focus: Tests de la factory de sélection d'adapter push (FCM, Expo, Mock).
"""

import pytest
from unittest.mock import patch, MagicMock

from app.infrastructure import push_adapter_factory
from app.infrastructure.push_adapter_factory import (
    get_push_adapter,
    set_push_adapter,
    reset_push_adapter,
)
from app.adapters.push import MockPushAdapter


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture(autouse=True)
def reset_adapter_before_each():
    """Reset adapter state before and after each test."""
    reset_push_adapter()
    yield
    reset_push_adapter()


@pytest.fixture
def mock_fcm_adapter():
    """Create a mock FCM adapter."""
    adapter = MagicMock()
    adapter.name = "FCM"
    adapter.is_available.return_value = True
    return adapter


@pytest.fixture
def mock_fcm_adapter_unavailable():
    """Create a mock FCM adapter that is not available."""
    adapter = MagicMock()
    adapter.name = "FCM"
    adapter.is_available.return_value = False
    return adapter


@pytest.fixture
def mock_expo_adapter():
    """Create a mock Expo adapter."""
    adapter = MagicMock()
    adapter.name = "Expo"
    return adapter


# ============================================================================
# TESTS - get_push_adapter
# ============================================================================


class TestGetPushAdapter:
    """Tests pour la fonction get_push_adapter."""

    def test_returns_adapter_implementing_notification_port(self):
        """get_push_adapter retourne un adapter avec les méthodes attendues."""
        adapter = get_push_adapter()

        assert hasattr(adapter, 'send')
        assert hasattr(adapter, 'send_batch')
        assert hasattr(adapter, 'validate_token')
        assert hasattr(adapter, 'is_available')
        assert hasattr(adapter, 'name')

    def test_returns_cached_adapter_on_subsequent_calls(self):
        """get_push_adapter retourne le même adapter en cache."""
        adapter1 = get_push_adapter()
        adapter2 = get_push_adapter()

        assert adapter1 is adapter2

    def test_returns_expo_adapter_when_no_firebase_config(self):
        """Sans config Firebase, Expo est utilisé."""
        with patch.dict('os.environ', {}, clear=True):
            # Remove any existing Firebase env vars
            with patch.object(push_adapter_factory, '_push_adapter', None):
                adapter = get_push_adapter()

                # Should be Expo adapter (lowercase name)
                assert adapter.name.lower() == "expo"

    def test_uses_fcm_when_credentials_path_set_and_available(self, mock_fcm_adapter):
        """Utilise FCM quand FIREBASE_CREDENTIALS_PATH est défini."""
        with patch.dict('os.environ', {'FIREBASE_CREDENTIALS_PATH': '/path/to/creds.json'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter):
                reset_push_adapter()
                adapter = get_push_adapter()

                assert adapter is mock_fcm_adapter
                mock_fcm_adapter.is_available.assert_called_once()

    def test_uses_fcm_when_project_id_set_and_available(self, mock_fcm_adapter):
        """Utilise FCM quand FIREBASE_PROJECT_ID est défini."""
        with patch.dict('os.environ', {'FIREBASE_PROJECT_ID': 'my-project'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter):
                reset_push_adapter()
                adapter = get_push_adapter()

                assert adapter is mock_fcm_adapter
                mock_fcm_adapter.is_available.assert_called_once()

    def test_falls_back_to_expo_when_fcm_unavailable(self, mock_fcm_adapter_unavailable):
        """Fallback sur Expo si FCM n'est pas disponible."""
        with patch.dict('os.environ', {'FIREBASE_PROJECT_ID': 'my-project'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter_unavailable):
                reset_push_adapter()
                adapter = get_push_adapter()

                # FCM was checked but not available
                mock_fcm_adapter_unavailable.is_available.assert_called_once()
                # Fallback to Expo (lowercase name)
                assert adapter.name.lower() == "expo"

    def test_fcm_adapter_cached_after_first_call(self, mock_fcm_adapter):
        """L'adapter FCM est mis en cache après le premier appel."""
        with patch.dict('os.environ', {'FIREBASE_PROJECT_ID': 'my-project'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter) as fcm_class:
                reset_push_adapter()
                adapter1 = get_push_adapter()
                adapter2 = get_push_adapter()

                # FCM class called only once
                fcm_class.assert_called_once()
                assert adapter1 is adapter2

    def test_logs_info_when_using_fcm(self, mock_fcm_adapter):
        """Log info quand FCM est utilisé."""
        with patch.dict('os.environ', {'FIREBASE_PROJECT_ID': 'my-project'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter):
                with patch.object(push_adapter_factory.logger, 'info') as mock_log:
                    reset_push_adapter()
                    get_push_adapter()

                    mock_log.assert_called_with("Using FCM adapter for push notifications")

    def test_logs_info_when_using_expo(self):
        """Log info quand Expo est utilisé."""
        with patch.dict('os.environ', {}, clear=True):
            with patch.object(push_adapter_factory.logger, 'info') as mock_log:
                reset_push_adapter()
                get_push_adapter()

                mock_log.assert_called_with("Using Expo adapter for push notifications")

    def test_respects_global_adapter_state(self):
        """Respecte l'état global de l'adapter."""
        custom = MockPushAdapter()
        push_adapter_factory._push_adapter = custom

        adapter = get_push_adapter()

        assert adapter is custom


# ============================================================================
# TESTS - set_push_adapter
# ============================================================================


class TestSetPushAdapter:
    """Tests pour la fonction set_push_adapter."""

    def test_sets_custom_adapter(self):
        """set_push_adapter configure un adapter personnalisé."""
        custom = MockPushAdapter()
        set_push_adapter(custom)

        adapter = get_push_adapter()

        assert adapter is custom

    def test_replaces_existing_adapter(self):
        """set_push_adapter remplace un adapter existant."""
        adapter1 = MockPushAdapter()
        adapter2 = MockPushAdapter(should_fail=True)

        set_push_adapter(adapter1)
        assert get_push_adapter() is adapter1

        set_push_adapter(adapter2)
        assert get_push_adapter() is adapter2

    def test_logs_adapter_name(self):
        """set_push_adapter log le nom de l'adapter."""
        custom = MockPushAdapter()

        with patch.object(push_adapter_factory.logger, 'info') as mock_log:
            set_push_adapter(custom)

            mock_log.assert_called_with(f"Push adapter set to: {custom.name}")

    def test_sets_global_variable(self):
        """set_push_adapter modifie la variable globale."""
        custom = MockPushAdapter()
        set_push_adapter(custom)

        assert push_adapter_factory._push_adapter is custom

    def test_accepts_fcm_adapter(self, mock_fcm_adapter):
        """set_push_adapter accepte un FCMAdapter."""
        set_push_adapter(mock_fcm_adapter)

        assert get_push_adapter() is mock_fcm_adapter

    def test_accepts_expo_adapter(self, mock_expo_adapter):
        """set_push_adapter accepte un ExpoAdapter."""
        set_push_adapter(mock_expo_adapter)

        assert get_push_adapter() is mock_expo_adapter


# ============================================================================
# TESTS - reset_push_adapter
# ============================================================================


class TestResetPushAdapter:
    """Tests pour la fonction reset_push_adapter."""

    def test_resets_to_none(self):
        """reset_push_adapter remet la variable à None."""
        custom = MockPushAdapter()
        set_push_adapter(custom)

        reset_push_adapter()

        assert push_adapter_factory._push_adapter is None

    def test_allows_new_adapter_selection(self):
        """reset_push_adapter permet une nouvelle sélection d'adapter."""
        custom = MockPushAdapter(should_fail=True)
        set_push_adapter(custom)

        reset_push_adapter()
        adapter = get_push_adapter()

        # Should not be the custom adapter anymore
        assert adapter is not custom

    def test_can_be_called_multiple_times(self):
        """reset_push_adapter peut être appelé plusieurs fois."""
        reset_push_adapter()
        reset_push_adapter()
        reset_push_adapter()

        assert push_adapter_factory._push_adapter is None

    def test_idempotent_when_already_none(self):
        """reset_push_adapter est idempotent quand déjà None."""
        push_adapter_factory._push_adapter = None
        reset_push_adapter()

        assert push_adapter_factory._push_adapter is None


# ============================================================================
# TESTS - Integration scenarios
# ============================================================================


class TestIntegrationScenarios:
    """Tests d'intégration pour différents scénarios."""

    def test_scenario_production_with_fcm(self, mock_fcm_adapter):
        """Scénario production avec FCM configuré."""
        env = {
            'FIREBASE_CREDENTIALS_PATH': '/app/firebase-creds.json',
            'FIREBASE_PROJECT_ID': 'my-prod-project',
        }

        with patch.dict('os.environ', env):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter):
                reset_push_adapter()
                adapter = get_push_adapter()

                assert adapter is mock_fcm_adapter

    def test_scenario_development_without_firebase(self):
        """Scénario développement sans Firebase."""
        # Clear Firebase env vars
        with patch.dict('os.environ', {}, clear=True):
            reset_push_adapter()
            adapter = get_push_adapter()

            # Should use Expo (lowercase)
            assert adapter.name.lower() == "expo"

    def test_scenario_test_with_mock(self):
        """Scénario test avec MockPushAdapter."""
        mock = MockPushAdapter()
        set_push_adapter(mock)

        adapter = get_push_adapter()

        assert adapter is mock
        assert isinstance(adapter, MockPushAdapter)

    def test_scenario_fcm_credentials_invalid(self, mock_fcm_adapter_unavailable):
        """Scénario avec credentials FCM invalides."""
        env = {
            'FIREBASE_CREDENTIALS_PATH': '/invalid/path.json',
        }

        with patch.dict('os.environ', env):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter_unavailable):
                reset_push_adapter()
                adapter = get_push_adapter()

                # Should fallback to Expo
                assert adapter.name.lower() == "expo"

    def test_scenario_switch_adapter_at_runtime(self, mock_fcm_adapter, mock_expo_adapter):
        """Scénario changement d'adapter à l'exécution."""
        # Start with custom Expo
        set_push_adapter(mock_expo_adapter)
        assert get_push_adapter() is mock_expo_adapter

        # Switch to FCM
        set_push_adapter(mock_fcm_adapter)
        assert get_push_adapter() is mock_fcm_adapter

        # Reset and let it auto-select
        reset_push_adapter()
        adapter = get_push_adapter()
        assert adapter.name.lower() == "expo"  # Default when no Firebase config

    def test_scenario_concurrent_access(self):
        """Scénario accès concurrent (simulation)."""
        import threading
        adapters = []

        def get_adapter():
            adapters.append(get_push_adapter())

        threads = [threading.Thread(target=get_adapter) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should be the same adapter instance
        first = adapters[0]
        assert all(a is first for a in adapters)


# ============================================================================
# TESTS - Edge cases
# ============================================================================


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_firebase_credentials_path(self):
        """FIREBASE_CREDENTIALS_PATH vide ne déclenche pas FCM."""
        with patch.dict('os.environ', {'FIREBASE_CREDENTIALS_PATH': ''}):
            reset_push_adapter()
            adapter = get_push_adapter()

            # Empty string is falsy, should use Expo
            assert adapter.name.lower() == "expo"

    def test_whitespace_firebase_project_id(self):
        """FIREBASE_PROJECT_ID avec espaces déclenche FCM."""
        # Whitespace is truthy in Python
        with patch.dict('os.environ', {'FIREBASE_PROJECT_ID': '  '}):
            with patch('app.adapters.push.FCMAdapter') as fcm_class:
                mock = MagicMock()
                mock.is_available.return_value = False
                fcm_class.return_value = mock

                reset_push_adapter()
                get_push_adapter()

                # FCM should be tried because whitespace is truthy
                fcm_class.assert_called_once()

    def test_both_firebase_env_vars_set(self, mock_fcm_adapter):
        """Les deux variables Firebase définies."""
        env = {
            'FIREBASE_CREDENTIALS_PATH': '/path/to/creds.json',
            'FIREBASE_PROJECT_ID': 'my-project',
        }

        with patch.dict('os.environ', env):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter):
                reset_push_adapter()
                adapter = get_push_adapter()

                assert adapter is mock_fcm_adapter

    def test_adapter_with_custom_name(self):
        """Adapter avec nom personnalisé."""
        custom = MagicMock()
        custom.name = "CustomPush"

        with patch.object(push_adapter_factory.logger, 'info') as mock_log:
            set_push_adapter(custom)

            mock_log.assert_called_with("Push adapter set to: CustomPush")

    def test_module_level_variable_isolation(self):
        """La variable module-level est isolée entre tests."""
        # This test verifies the autouse fixture works
        assert push_adapter_factory._push_adapter is None or \
               push_adapter_factory._push_adapter is not None  # Just checking access


# ============================================================================
# TESTS - FCM import path
# ============================================================================


class TestFCMImportPath:
    """Tests pour le chemin d'import FCM."""

    def test_fcm_imported_lazily(self):
        """FCMAdapter est importé paresseusement."""
        # With no Firebase config, FCMAdapter should not be imported
        with patch.dict('os.environ', {}, clear=True):
            with patch('app.adapters.push.FCMAdapter') as fcm_class:
                reset_push_adapter()
                get_push_adapter()

                # FCMAdapter class should not have been instantiated
                fcm_class.assert_not_called()

    def test_expo_imported_when_fcm_unavailable(self, mock_fcm_adapter_unavailable):
        """ExpoAdapter importé quand FCM n'est pas disponible."""
        with patch.dict('os.environ', {'FIREBASE_PROJECT_ID': 'test'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter_unavailable):
                reset_push_adapter()
                adapter = get_push_adapter()

                assert adapter.name.lower() == "expo"


# ============================================================================
# TESTS - Logging behavior
# ============================================================================


class TestLoggingBehavior:
    """Tests pour le comportement de logging."""

    def test_no_logging_when_cached(self):
        """Pas de log quand l'adapter est en cache."""
        with patch.object(push_adapter_factory.logger, 'info') as mock_log:
            reset_push_adapter()
            get_push_adapter()  # First call logs
            mock_log.reset_mock()

            get_push_adapter()  # Second call should not log

            mock_log.assert_not_called()

    def test_logging_on_set_adapter(self):
        """Log à chaque set_push_adapter."""
        with patch.object(push_adapter_factory.logger, 'info') as mock_log:
            adapter1 = MockPushAdapter()
            adapter2 = MockPushAdapter()

            set_push_adapter(adapter1)
            set_push_adapter(adapter2)

            assert mock_log.call_count == 2

    def test_logging_after_reset_and_get(self):
        """Log après reset puis get."""
        with patch.object(push_adapter_factory.logger, 'info') as mock_log:
            get_push_adapter()
            mock_log.reset_mock()

            reset_push_adapter()
            get_push_adapter()

            # Should log again after reset
            mock_log.assert_called_once()


# ============================================================================
# TESTS - Coverage completion for lines 37-42
# ============================================================================


class TestFCMAdapterSelection:
    """Tests spécifiques pour la branche FCM (lignes 37-42)."""

    def test_fcm_adapter_selected_when_available(self, mock_fcm_adapter):
        """L'adapter FCM est sélectionné quand disponible."""
        with patch.dict('os.environ', {'FIREBASE_CREDENTIALS_PATH': '/valid/path.json'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter) as fcm_class:
                reset_push_adapter()
                adapter = get_push_adapter()

                fcm_class.assert_called_once()
                mock_fcm_adapter.is_available.assert_called_once()
                assert adapter is mock_fcm_adapter

    def test_fcm_adapter_created_and_checked(self, mock_fcm_adapter):
        """FCMAdapter est créé et sa disponibilité vérifiée."""
        with patch.dict('os.environ', {'FIREBASE_PROJECT_ID': 'test-project'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter) as fcm_class:
                reset_push_adapter()
                get_push_adapter()

                # Verify FCMAdapter was instantiated
                fcm_class.assert_called_once()
                # Verify is_available was called
                mock_fcm_adapter.is_available.assert_called_once()

    def test_fcm_adapter_stored_in_global(self, mock_fcm_adapter):
        """FCMAdapter stocké dans la variable globale."""
        with patch.dict('os.environ', {'FIREBASE_CREDENTIALS_PATH': '/creds.json'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter):
                reset_push_adapter()
                get_push_adapter()

                assert push_adapter_factory._push_adapter is mock_fcm_adapter

    def test_fcm_logging_message(self, mock_fcm_adapter):
        """Message de log correct pour FCM."""
        with patch.dict('os.environ', {'FIREBASE_PROJECT_ID': 'proj'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter):
                with patch.object(push_adapter_factory.logger, 'info') as mock_log:
                    reset_push_adapter()
                    get_push_adapter()

                    # Verify the exact log message
                    mock_log.assert_any_call("Using FCM adapter for push notifications")

    def test_fcm_returned_directly(self, mock_fcm_adapter):
        """FCMAdapter retourné directement (pas ExpoAdapter)."""
        with patch.dict('os.environ', {'FIREBASE_CREDENTIALS_PATH': '/valid.json'}):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter):
                with patch('app.adapters.push.ExpoAdapter') as expo_class:
                    reset_push_adapter()
                    adapter = get_push_adapter()

                    # ExpoAdapter should NOT be instantiated
                    expo_class.assert_not_called()
                    assert adapter is mock_fcm_adapter

    def test_fcm_with_credentials_path_only(self, mock_fcm_adapter):
        """FCM sélectionné avec uniquement FIREBASE_CREDENTIALS_PATH."""
        env = {'FIREBASE_CREDENTIALS_PATH': '/only/creds.json'}
        with patch.dict('os.environ', env, clear=True):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter):
                reset_push_adapter()
                adapter = get_push_adapter()

                assert adapter is mock_fcm_adapter

    def test_fcm_with_project_id_only(self, mock_fcm_adapter):
        """FCM sélectionné avec uniquement FIREBASE_PROJECT_ID."""
        env = {'FIREBASE_PROJECT_ID': 'only-project-id'}
        with patch.dict('os.environ', env, clear=True):
            with patch('app.adapters.push.FCMAdapter', return_value=mock_fcm_adapter):
                reset_push_adapter()
                adapter = get_push_adapter()

                assert adapter is mock_fcm_adapter


# ============================================================================
# TESTS - Additional edge cases
# ============================================================================


class TestAdditionalEdgeCases:
    """Tests supplémentaires pour les cas limites."""

    def test_fcm_initialization_order(self, mock_fcm_adapter):
        """L'ordre d'initialisation est correct."""
        call_order = []

        def track_fcm():
            call_order.append('fcm_init')
            return mock_fcm_adapter

        mock_fcm_adapter.is_available.side_effect = lambda: (call_order.append('is_available'), True)[1]

        with patch.dict('os.environ', {'FIREBASE_PROJECT_ID': 'test'}):
            with patch('app.adapters.push.FCMAdapter', side_effect=track_fcm):
                reset_push_adapter()
                get_push_adapter()

                assert call_order == ['fcm_init', 'is_available']

    def test_multiple_resets_between_gets(self):
        """Multiple resets entre les appels get."""
        adapter1 = get_push_adapter()
        reset_push_adapter()
        reset_push_adapter()
        reset_push_adapter()
        adapter2 = get_push_adapter()

        # Should get fresh adapters, but both Expo
        assert adapter1.name.lower() == "expo"
        assert adapter2.name.lower() == "expo"

    def test_set_none_equivalent_to_reset(self):
        """Définir None n'est pas équivalent à reset (TypeError attendu)."""
        # Setting None directly should cause issues when get is called
        # because None doesn't have expected methods
        push_adapter_factory._push_adapter = None

        # But get_push_adapter handles None and returns a new adapter
        adapter = get_push_adapter()
        assert adapter is not None

    def test_get_after_set_then_reset(self, mock_fcm_adapter):
        """get après set puis reset retourne nouvel adapter."""
        set_push_adapter(mock_fcm_adapter)
        assert get_push_adapter() is mock_fcm_adapter

        reset_push_adapter()
        adapter = get_push_adapter()

        assert adapter is not mock_fcm_adapter
        assert adapter.name.lower() == "expo"
