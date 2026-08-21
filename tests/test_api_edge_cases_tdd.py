# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases de l'API REST.

Ces tests couvrent les cas limites non testés :
- Validation des entrées
- Formats JSON invalides
- Valeurs aux limites
- Codes d'erreur HTTP

Approche TDD : Tests écrits d'abord, code corrigé si nécessaire.
Clean Architecture : Tests d'intégration de la couche API.
"""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _mock_jwt_for_mobile_routes():
    """Mock _authenticated_user_id (audit P0-001 2026-04-28).

    Sur self-hosted runner Hetzner, le user gh-runner n'a pas de
    multi_accounts.json, donc _resolve_account_id_for_user retourne -1
    et require_user_id renvoie 401 → tests qui valident un 400 cassent.

    Mock global pour TOUS les tests du fichier afin de couvrir les 3
    classes de tests (Mobile, PushNotifications, ErrorResponseFormat).
    """
    with patch("app.api.mobile._authenticated_user_id", return_value="test@example.com"):
        yield


# ============================================================================
# TESTS - Mobile API - Edge Cases
# ============================================================================

class TestMobileAPIEdgeCases:
    """Tests edge cases pour l'API Mobile."""

    @pytest.fixture
    def client(self):
        """Crée un client de test Flask avec auth JWT mockée.

        Audit P0-001 (2026-04-28) a ajouté require_user_id qui exige un
        JWT authentifié et retourne 401 sinon. Les tests d'edge cases
        valident le code 400 sur input invalide → on doit d'abord passer
        l'auth gate. On mock _authenticated_user_id pour retourner un
        email stable, ce qui simule un JWT valide.
        """
        from app.api.app import create_app
        app = create_app({"TESTING": True})
        with patch("app.api.mobile._authenticated_user_id", return_value="test@example.com"):
            with app.test_client() as test_client:
                yield test_client

    @pytest.fixture(autouse=True)
    def reset_stores(self):
        """Réinitialise les stores avant chaque test."""
        from app.infrastructure.mobile_companion_store import reset_mobile_stores
        from app.infrastructure.container import reset_container
        reset_mobile_stores()
        reset_container()
        yield
        reset_mobile_stores()
        reset_container()

    # ---- Session Endpoints ----

    def test_start_session_empty_body(self, client):
        """Test démarrage de session avec body vide."""
        response = client.post(
            "/api/mobile/session/start",
            data="",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_start_session_invalid_json(self, client):
        """Test démarrage de session avec JSON invalide."""
        response = client.post(
            "/api/mobile/session/start",
            data="not valid json",
            content_type="application/json",
        )
        assert response.status_code == 400

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id vient du JWT, payload ignoré ; les tests qui valident un 400 sur input invalide retournent désormais 503/401/200 selon le path. À refactorer en tests d'intégration avec mock service.")
    def test_start_session_null_user_id(self, client):
        """Test démarrage de session avec user_id null."""
        response = client.post(
            "/api/mobile/session/start",
            json={"user_id": None},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "user_id" in data.get("error", "").lower()

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id vient du JWT, payload ignoré ; les tests qui valident un 400 sur input invalide retournent désormais 503/401/200 selon le path. À refactorer en tests d'intégration avec mock service.")
    def test_start_session_empty_string_user_id(self, client):
        """Test démarrage de session avec user_id vide."""
        response = client.post(
            "/api/mobile/session/start",
            json={"user_id": ""},
            content_type="application/json",
        )
        assert response.status_code == 400

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id du payload ignoré, JWT seul fait foi → session créée 201 quel que soit le payload.")
    def test_start_session_whitespace_user_id(self, client):
        """Test démarrage de session avec user_id espaces."""
        response = client.post(
            "/api/mobile/session/start",
            json={"user_id": "   "},
            content_type="application/json",
        )
        assert response.status_code in [400, 500, 503]

    def test_end_session_missing_session_id(self, client):
        """Test fin de session sans session_id."""
        response = client.post(
            "/api/mobile/session/end",
            json={"user_id": "user_123"},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "session_id" in data.get("error", "").lower()

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id vient du JWT, payload ignoré ; les tests qui valident un 400 sur input invalide retournent désormais 503/401/200 selon le path. À refactorer en tests d'intégration avec mock service.")
    def test_end_session_missing_user_id(self, client):
        """Test fin de session sans user_id."""
        response = client.post(
            "/api/mobile/session/end",
            json={"session_id": "session_123"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_touch_session_missing_session_id(self, client):
        """Test touch sans session_id."""
        response = client.post(
            "/api/mobile/session/touch",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_touch_session_nonexistent(self, client):
        """Test touch de session inexistante."""
        response = client.post(
            "/api/mobile/session/touch",
            json={"session_id": "nonexistent"},
            content_type="application/json",
        )
        assert response.status_code == 404

    # ---- Sync Endpoint ----

    def test_sync_missing_device_token(self, client):
        """Test sync sans device_token."""
        response = client.post(
            "/api/mobile/sync",
            json={"user_id": "user_123"},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "device_token" in data.get("error", "").lower()

    def test_sync_invalid_since_format(self, client):
        """Test sync avec format de date invalide."""
        response = client.post(
            "/api/mobile/sync",
            json={
                "user_id": "user_123",
                "device_token": "token",
                "since": "not-a-date",
            },
            content_type="application/json",
        )
        # Le format invalide devrait être ignoré ou retourner 200
        # car parse_datetime retourne None pour les formats invalides
        assert response.status_code in [200, 400]

    def test_sync_negative_limit(self, client):
        """Test sync avec limit négatif."""
        response = client.post(
            "/api/mobile/sync",
            json={
                "user_id": "user_123",
                "device_token": "token",
                "limit": -10,
            },
            content_type="application/json",
        )
        # Comportement dépend de l'implémentation
        assert response.status_code in [200, 400]

    def test_sync_zero_limit(self, client):
        """Test sync avec limit à zéro."""
        response = client.post(
            "/api/mobile/sync",
            json={
                "user_id": "user_123",
                "device_token": "token",
                "limit": 0,
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        response.get_json()
        # Devrait retourner une liste vide ou utiliser une valeur par défaut

    def test_sync_very_large_limit(self, client):
        """Test sync avec limit très grand."""
        response = client.post(
            "/api/mobile/sync",
            json={
                "user_id": "user_123",
                "device_token": "token",
                "limit": 1000000,
            },
            content_type="application/json",
        )
        assert response.status_code == 200

    # ---- Drafts Endpoints ----

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id vient du JWT, payload ignoré ; les tests qui valident un 400 sur input invalide retournent désormais 503/401/200 selon le path. À refactorer en tests d'intégration avec mock service.")
    def test_list_drafts_missing_user_id(self, client):
        """Test liste brouillons sans user_id."""
        response = client.get("/api/mobile/drafts")
        # Le décorateur require_user_id devrait retourner 400
        # 415 si le décorateur vérifie aussi le Content-Type
        assert response.status_code in [400, 415, 500]

    def test_list_drafts_negative_limit(self, client):
        """Test liste brouillons avec limit négatif."""
        response = client.get("/api/mobile/drafts?user_id=user_123&limit=-5")
        # Flask convertit en int, valeur négative acceptable ou ignorée
        assert response.status_code == 200

    def test_get_draft_nonexistent(self, client):
        """Test récupération brouillon inexistant."""
        response = client.get("/api/mobile/drafts/nonexistent?user_id=user_123")
        assert response.status_code == 404
        data = response.get_json()
        assert "not found" in data.get("error", "").lower()

    # ---- Actions Endpoints ----

    def test_action_missing_draft_id(self, client):
        """Test action sans draft_id."""
        response = client.post(
            "/api/mobile/actions",
            json={
                "action": "approved",
                "user_id": "user_123",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_action_missing_action(self, client):
        """Test action sans type d'action."""
        response = client.post(
            "/api/mobile/actions",
            json={
                "draft_id": "d1",
                "user_id": "user_123",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_action_invalid_action_type(self, client):
        """Test action avec type invalide."""
        response = client.post(
            "/api/mobile/actions",
            json={
                "draft_id": "d1",
                "action": "invalid_action",
                "user_id": "user_123",
            },
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "invalid action" in data.get("error", "").lower()

    def test_action_edit_without_body(self, client):
        """Test édition sans corps."""
        response = client.post(
            "/api/mobile/actions",
            json={
                "draft_id": "d1",
                "action": "edited",
                "user_id": "user_123",
            },
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "edited_body" in data.get("error", "").lower()

    def test_action_edit_with_empty_body(self, client):
        """Test édition avec corps vide."""
        response = client.post(
            "/api/mobile/actions",
            json={
                "draft_id": "d1",
                "action": "edited",
                "user_id": "user_123",
                "edited_body": "",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_batch_actions_empty_list(self, client):
        """Test batch actions avec liste vide."""
        response = client.post(
            "/api/mobile/actions/batch",
            json={
                "user_id": "user_123",
                "actions": [],
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id vient du JWT, payload ignoré ; les tests qui valident un 400 sur input invalide retournent désormais 503/401/200 selon le path. À refactorer en tests d'intégration avec mock service.")
    def test_batch_actions_missing_user_id(self, client):
        """Test batch actions sans user_id."""
        response = client.post(
            "/api/mobile/actions/batch",
            json={
                "actions": [{"draft_id": "d1", "action": "approved"}],
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_batch_actions_invalid_action_ignored(self, client):
        """Test batch actions avec action invalide (ignorée)."""
        response = client.post(
            "/api/mobile/actions/batch",
            json={
                "user_id": "user_123",
                "actions": [
                    {"draft_id": "d1", "action": "invalid"},
                    {"draft_id": "d2", "action": "approved"},
                ],
            },
            content_type="application/json",
        )
        # L'action invalide devrait être ignorée
        assert response.status_code == 200
        data = response.get_json()
        # Seule l'action valide devrait être comptée
        assert data.get("total", 0) <= 2

    def test_mark_draft_read_missing_user_id(self, client):
        """Test marquer lu sans user_id."""
        response = client.post(
            "/api/mobile/drafts/d1/read",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 400

    # ---- Analytics Endpoints ----

    def test_analytics_invalid_event_type(self, client):
        """Test analytics avec event_type invalide."""
        response = client.post(
            "/api/mobile/analytics",
            json={
                "event_type": "invalid.event.type",
                "user_id": "user_123",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_analytics_missing_event_type(self, client):
        """Test analytics sans event_type."""
        response = client.post(
            "/api/mobile/analytics",
            json={
                "user_id": "user_123",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_analytics_batch_with_invalid_events(self, client):
        """Test analytics batch avec événements invalides."""
        response = client.post(
            "/api/mobile/analytics",
            json={
                "events": [
                    {"event_type": "app.open", "user_id": "user_123"},
                    {"event_type": "invalid", "user_id": "user_123"},
                    {"event_type": "draft.view", "user_id": "user_123"},
                ],
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        # Les événements invalides devraient être ignorés
        assert data.get("tracked", 0) == 2

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id vient du JWT, payload ignoré ; les tests qui valident un 400 sur input invalide retournent désormais 503/401/200 selon le path. À refactorer en tests d'intégration avec mock service.")
    def test_stats_missing_user_id(self, client):
        """Test stats sans user_id."""
        response = client.get("/api/mobile/stats")
        # Le décorateur require_user_id devrait retourner 400
        # 415 possible si vérifie Content-Type
        assert response.status_code in [400, 415, 500]

    def test_stats_invalid_days(self, client):
        """Test stats avec days invalide."""
        response = client.get("/api/mobile/stats?user_id=user_123&days=abc")
        # Flask type=int devrait gérer l'erreur
        assert response.status_code in [200, 400]

    def test_stats_negative_days(self, client):
        """Test stats avec days négatif."""
        response = client.get("/api/mobile/stats?user_id=user_123&days=-7")
        assert response.status_code == 200

    # ---- Preferences Endpoints ----

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id vient du JWT, payload ignoré ; les tests qui valident un 400 sur input invalide retournent désormais 503/401/200 selon le path. À refactorer en tests d'intégration avec mock service.")
    def test_preferences_missing_user_id(self, client):
        """Test préférences sans user_id."""
        response = client.get("/api/mobile/preferences")
        # Le décorateur require_user_id devrait retourner 400
        # 415 possible si vérifie Content-Type
        assert response.status_code in [400, 415, 500]

    def test_update_preferences_no_fields(self, client):
        """Test mise à jour préférences sans champs."""
        response = client.put(
            "/api/mobile/preferences",
            json={"user_id": "user_123"},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "no fields" in data.get("error", "").lower()

    def test_update_preferences_invalid_threshold(self, client):
        """Test mise à jour préférences avec seuil invalide."""
        # D'abord créer les préférences
        client.get("/api/mobile/preferences?user_id=user_123")

        response = client.put(
            "/api/mobile/preferences",
            json={
                "user_id": "user_123",
                "auto_approve_threshold": 150,
            },
            content_type="application/json",
        )
        # Devrait échouer à cause du seuil invalide
        # Mais le store pourrait ne pas valider
        assert response.status_code in [200, 400]

    def test_update_preferences_invalid_notification_pref(self, client):
        """Test mise à jour préférences avec notification invalide."""
        # La valeur invalide peut causer une exception lors de la conversion enum
        # Le test vérifie juste que l'API ne plante pas de manière inattendue
        response = client.put(
            "/api/mobile/preferences",
            json={
                "user_id": "user_123",
                "notification_preference": "invalid_pref",
            },
            content_type="application/json",
        )
        # 200 si la valeur est acceptée telle quelle
        # 400/500 si validation échoue
        # 404 si l'utilisateur n'existe pas
        assert response.status_code in [200, 400, 404, 500]

    # ---- Config Endpoints ----

    def test_config_with_invalid_version(self, client):
        """Test config avec version invalide."""
        # Une version avec lettres cause une ValueError lors de int()
        # Le service devrait capturer cette erreur ou la propager
        response = client.get("/api/mobile/config?app_version=1.0.0")
        # Avec une version valide, devrait retourner 200
        assert response.status_code == 200

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id vient du JWT, payload ignoré ; les tests qui valident un 400 sur input invalide retournent désormais 503/401/200 selon le path. À refactorer en tests d'intégration avec mock service.")
    def test_maintenance_mode_missing_enabled(self, client):
        """Test mode maintenance sans enabled."""
        response = client.put(
            "/api/mobile/config/maintenance",
            json={"message": "Update in progress"},
            content_type="application/json",
        )
        assert response.status_code == 400

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id vient du JWT, payload ignoré ; les tests qui valident un 400 sur input invalide retournent désormais 503/401/200 selon le path. À refactorer en tests d'intégration avec mock service.")
    def test_feature_flag_missing_enabled(self, client):
        """Test feature flag sans enabled."""
        response = client.put(
            "/api/mobile/config/feature/dark_mode",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 400


# ============================================================================
# TESTS - Push Notifications API - Edge Cases
# ============================================================================

_PUSH_ADMIN_HEADERS = {"Authorization": "Bearer admin-stub"}


class TestPushNotificationsAPIEdgeCases:
    """Tests edge cases pour l'API Push Notifications."""

    @pytest.fixture
    def client(self):
        """Crée un client de test Flask."""
        pytest.importorskip("flask_cors", reason="flask_cors required for API tests")
        from app.api.app import create_app
        app = create_app({"TESTING": True})
        with app.test_client() as client:
            yield client

    @pytest.fixture(autouse=True)
    def _stub_admin_for_push_admin_routes(self, monkeypatch):
        """C-3 (issue #523): certaines routes push sont admin-only depuis 2026-05-05.
        On stub _decode_jwt + _is_admin pour que les tests edge case (qui
        exercent la validation 400) passent toujours."""
        fake_payload = {"sub": "1", "email": "admin@test.com"}
        monkeypatch.setattr("app.api.auth._decode_jwt", lambda token: fake_payload)
        monkeypatch.setattr("app.api.admin._is_admin", lambda email: True)
        yield

    # ---- Devices Endpoints ----

    def test_register_device_missing_token(self, client):
        """Test enregistrement device sans token."""
        response = client.post(
            "/push/devices",
            json={"platform": "ios"},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "token" in data.get("error", "").lower()

    def test_register_device_missing_platform(self, client):
        """Test enregistrement device sans platform."""
        response = client.post(
            "/push/devices",
            json={"token": "test_token"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_register_device_invalid_platform(self, client):
        """Test enregistrement device avec platform invalide."""
        response = client.post(
            "/push/devices",
            json={
                "token": "test_token",
                "platform": "windows",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_register_device_uppercase_platform(self, client):
        """Test enregistrement device avec platform en majuscules."""
        response = client.post(
            "/push/devices",
            json={
                "token": "test_token",
                "platform": "IOS",
            },
            content_type="application/json",
        )
        # Devrait être rejeté car platform doit être lowercase
        assert response.status_code == 400

    def test_unregister_device_not_found(self, client):
        """Test désinscription device inexistant."""
        response = client.delete("/push/devices/nonexistent_token")
        assert response.status_code == 404

    # ---- Send Notification Endpoints ----

    def test_send_missing_token(self, client):
        """Test envoi sans token."""
        response = client.post(
            "/push/send",
            json={
                "title": "Test",
                "body": "Body",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_send_missing_title(self, client):
        """Test envoi sans titre."""
        response = client.post(
            "/push/send",
            json={
                "token": "test_token",
                "body": "Body",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_send_missing_body(self, client):
        """Test envoi sans corps."""
        response = client.post(
            "/push/send",
            json={
                "token": "test_token",
                "title": "Title",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_send_empty_tokens_list(self, client):
        """Test envoi avec liste de tokens vide."""
        response = client.post(
            "/push/send",
            json={
                "tokens": [],
                "title": "Test",
                "body": "Body",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_send_invalid_category(self, client):
        """Test envoi avec catégorie invalide."""
        from unittest.mock import patch
        from app.domain.ports.notification_port import PushNotificationResult

        with patch("app.api.push_notifications._get_push_notification_service") as mock_service:
            mock_result = PushNotificationResult(success=True, message_id="msg_123")
            mock_service.return_value.send_to_token.return_value = mock_result

            response = client.post(
                "/push/send",
                json={
                    "token": "test_token",
                    "title": "Test",
                    "body": "Body",
                    "category": "invalid_category",
                },
                content_type="application/json",
            )
            # parse_category retourne INFO pour les catégories invalides
            assert response.status_code == 200

    def test_send_invalid_priority(self, client):
        """Test envoi avec priorité invalide."""
        from unittest.mock import patch
        from app.domain.ports.notification_port import PushNotificationResult

        with patch("app.api.push_notifications._get_push_notification_service") as mock_service:
            mock_result = PushNotificationResult(success=True, message_id="msg_123")
            mock_service.return_value.send_to_token.return_value = mock_result

            response = client.post(
                "/push/send",
                json={
                    "token": "test_token",
                    "title": "Test",
                    "body": "Body",
                    "priority": "ultra_high",
                },
                content_type="application/json",
            )
            # La priorité invalide est acceptée (pas de validation)
            assert response.status_code == 200

    # ---- Broadcast Endpoint ----

    def test_broadcast_missing_title(self, client):
        """Test broadcast sans titre."""
        response = client.post(
            "/push/broadcast",
            json={"body": "Body"},
            content_type="application/json",
            headers=_PUSH_ADMIN_HEADERS,
        )
        assert response.status_code == 400

    def test_broadcast_missing_body(self, client):
        """Test broadcast sans corps."""
        response = client.post(
            "/push/broadcast",
            json={"title": "Title"},
            content_type="application/json",
            headers=_PUSH_ADMIN_HEADERS,
        )
        assert response.status_code == 400

    def test_broadcast_no_devices(self, client):
        """Test broadcast sans devices enregistrés."""
        with patch("app.api.push_notifications._get_push_notification_service") as mock_service:
            mock_service.return_value.broadcast.return_value = []

            response = client.post(
                "/push/broadcast",
                json={
                    "title": "Test",
                    "body": "Body",
                },
                content_type="application/json",
                headers=_PUSH_ADMIN_HEADERS,
            )
            assert response.status_code == 200
            data = response.get_json()
            assert data.get("sent", 0) == 0

    # ---- History Endpoint ----

    def test_history_invalid_limit(self, client):
        """Test historique avec limit invalide."""
        # /push/history is @require_admin (enumeration guard); send the stubbed
        # admin Bearer so we exercise limit validation, not the auth gate.
        response = client.get("/push/history?limit=abc", headers=_PUSH_ADMIN_HEADERS)
        # Flask type=int devrait gérer
        assert response.status_code in [200, 400]

    def test_history_negative_limit(self, client):
        """Test historique avec limit négatif."""
        with patch("app.api.push_notifications._get_push_notification_service") as mock_service:
            mock_service.return_value.get_records.return_value = []

            response = client.get("/push/history?limit=-10", headers=_PUSH_ADMIN_HEADERS)
            # Comportement dépend de l'implémentation
            assert response.status_code == 200


# ============================================================================
# TESTS - API Helpers - Edge Cases
# ============================================================================

class TestAPIHelpersEdgeCases:
    """Tests edge cases pour les helpers API."""

    def test_require_json_decorator_no_content_type(self):
        """Test décorateur require_json sans Content-Type."""
        from app.api.app import create_app
        app = create_app({"TESTING": True})

        with app.test_client() as client:
            response = client.post(
                "/api/mobile/session/start",
                data='{"user_id": "test"}',
            )
            # Sans Content-Type: application/json, le comportement varie
            # Flask peut quand même parser le JSON ou rejeter
            assert response.status_code in [400, 415, 201, 500]

    def test_require_json_decorator_wrong_content_type(self):
        """Test décorateur require_json avec mauvais Content-Type."""
        from app.api.app import create_app
        app = create_app({"TESTING": True})

        with app.test_client() as client:
            response = client.post(
                "/api/mobile/session/start",
                data='{"user_id": "test"}',
                content_type="text/plain",
            )
            # Avec mauvais Content-Type, le comportement varie
            assert response.status_code in [400, 415, 500]

    def test_parse_datetime_iso_formats(self):
        """Test parse_datetime avec différents formats ISO."""
        from app.api.mobile import parse_datetime

        # Format standard
        assert parse_datetime("2024-01-15T10:30:00") is not None

        # Format avec Z
        result = parse_datetime("2024-01-15T10:30:00Z")
        assert result is not None

        # Format avec timezone offset
        result = parse_datetime("2024-01-15T10:30:00+00:00")
        assert result is not None

        # Format invalide
        assert parse_datetime("not-a-date") is None

        # None
        assert parse_datetime(None) is None

        # Vide
        assert parse_datetime("") is None

    def test_parse_action_all_values(self):
        """Test parse_action avec toutes les valeurs."""
        from app.api.mobile import parse_action
        from app.domain.entities.mobile_companion import MobileDraftAction

        assert parse_action("pending") == MobileDraftAction.PENDING
        assert parse_action("approved") == MobileDraftAction.APPROVED
        assert parse_action("rejected") == MobileDraftAction.REJECTED
        assert parse_action("edited") == MobileDraftAction.EDITED
        assert parse_action("sent") == MobileDraftAction.SENT

        assert parse_action("invalid") is None
        assert parse_action("APPROVED") is None  # Case sensitive

    def test_parse_event_type_all_values(self):
        """Test parse_event_type avec toutes les valeurs."""
        from app.api.mobile import parse_event_type
        from app.domain.entities.mobile_companion import MobileEventType

        assert parse_event_type("app.open") == MobileEventType.APP_OPEN
        assert parse_event_type("draft.view") == MobileEventType.DRAFT_VIEW
        assert parse_event_type("sync.complete") == MobileEventType.SYNC_COMPLETE

        assert parse_event_type("invalid.event") is None


# ============================================================================
# TESTS - Error Response Format
# ============================================================================

class TestErrorResponseFormat:
    """Tests pour vérifier le format des réponses d'erreur."""

    @pytest.fixture
    def client(self):
        """Crée un client de test Flask."""
        from app.api.app import create_app
        app = create_app({"TESTING": True})
        with app.test_client() as client:
            yield client

    def test_error_response_has_error_field(self, client):
        """Test que les erreurs ont un champ 'error'."""
        response = client.post(
            "/api/mobile/session/start",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_error_response_is_json(self, client):
        """Test que les erreurs sont en JSON."""
        response = client.post(
            "/api/mobile/session/start",
            json={},
            content_type="application/json",
        )
        assert response.content_type == "application/json"

    @pytest.mark.skip(reason="Obsolète post audit P0-001 (2026-04-28) : user_id du payload ignoré, le JWT mocké suffit. Le test n'a plus de sens (pas de validation 400 possible).")
    def test_validation_error_message_descriptive(self, client):
        """Test que les messages d'erreur sont descriptifs."""
        response = client.post(
            "/api/mobile/session/start",
            json={"device_token": "token"},  # Missing user_id
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        error_msg = data.get("error", "").lower()
        # Le message devrait mentionner le champ manquant
        assert "user_id" in error_msg or "required" in error_msg
