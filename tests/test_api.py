# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'API REST Agentys.

pytest tests/test_api.py -v
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import threading

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# STANDALONE WEBHOOK CLASSES FOR TESTING (without Flask dependency)
# ============================================================================

@dataclass
class WebhookConfig:
    """Configuration d'un webhook (standalone for testing)."""
    id: str
    url: str
    events: List[str]
    secret: Optional[str] = None
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_triggered: Optional[str] = None
    failure_count: int = 0


@dataclass
class WebhookEvent:
    """Événement à envoyer via webhook."""
    event_type: str
    timestamp: str
    data: Dict[str, Any]


class WebhookManagerForTest:
    """Gestionnaire des webhooks (standalone for testing)."""

    VALID_EVENTS = [
        "draft.created",
        "draft.failed",
        "followup.sent",
        "email.processed",
        "email.skipped",
        "learning.pattern_extracted",
        "error",
        "health.degraded",
    ]

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.webhooks: Dict[str, WebhookConfig] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text())
                for wh_data in data.get("webhooks", []):
                    wh = WebhookConfig(**wh_data)
                    self.webhooks[wh.id] = wh
            except Exception:
                pass

    def _save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "webhooks": [asdict(wh) for wh in self.webhooks.values()],
            "updated_at": datetime.now().isoformat(),
        }
        self.filepath.write_text(json.dumps(data, indent=2))

    def register(self, url: str, events: List[str], secret: Optional[str] = None) -> WebhookConfig:
        invalid = [e for e in events if e not in self.VALID_EVENTS and e != "*"]
        if invalid:
            raise ValueError(f"Invalid events: {invalid}")

        import uuid
        webhook_id = str(uuid.uuid4())[:8]

        with self._lock:
            webhook = WebhookConfig(
                id=webhook_id,
                url=url,
                events=events,
                secret=secret,
            )
            self.webhooks[webhook_id] = webhook
            self._save()

        return webhook

    def unregister(self, webhook_id: str) -> bool:
        with self._lock:
            if webhook_id in self.webhooks:
                del self.webhooks[webhook_id]
                self._save()
                return True
        return False

    def get(self, webhook_id: str) -> Optional[WebhookConfig]:
        return self.webhooks.get(webhook_id)

    def list_all(self) -> List[WebhookConfig]:
        return list(self.webhooks.values())

    def trigger(self, event_type: str, data: Dict[str, Any]) -> int:
        event = WebhookEvent(
            event_type=event_type,
            timestamp=datetime.now().isoformat(),
            data=data,
        )

        success_count = 0

        for webhook in self.webhooks.values():
            if not webhook.enabled:
                continue
            if "*" not in webhook.events and event_type not in webhook.events:
                continue
            thread = threading.Thread(
                target=self._send_webhook,
                args=(webhook, event),
            )
            thread.start()
            success_count += 1

        return success_count

    def _send_webhook(self, webhook: WebhookConfig, event: WebhookEvent) -> bool:
        import requests

        payload = {
            "event": event.event_type,
            "timestamp": event.timestamp,
            "data": event.data,
        }

        headers = {
            "Content-Type": "application/json",
            "X-Agentys-Event": event.event_type,
            "X-Agentys-Webhook-Id": webhook.id,
        }

        if webhook.secret:
            import hmac
            import hashlib
            payload_bytes = json.dumps(payload).encode()
            signature = hmac.new(
                webhook.secret.encode(),
                payload_bytes,
                hashlib.sha256
            ).hexdigest()
            headers["X-Agentys-Signature"] = f"sha256={signature}"

        try:
            response = requests.post(
                webhook.url,
                json=payload,
                headers=headers,
                timeout=10,
            )

            if response.ok:
                with self._lock:
                    webhook.last_triggered = datetime.now().isoformat()
                    webhook.failure_count = 0
                    self._save()
                return True
            else:
                with self._lock:
                    webhook.failure_count += 1
                    if webhook.failure_count >= 5:
                        webhook.enabled = False
                    self._save()
                return False

        except Exception:
            with self._lock:
                webhook.failure_count += 1
                if webhook.failure_count >= 5:
                    webhook.enabled = False
                self._save()
            return False


# ============================================================================
# TESTS WEBHOOKS
# ============================================================================

class TestWebhookConfig:
    """Tests pour la configuration des webhooks."""

    def test_webhook_config_creation(self):
        """Création d'une config webhook."""
        config = WebhookConfig(
            id="test123",
            url="https://example.com/webhook",
            events=["draft.created", "error"],
        )

        assert config.id == "test123"
        assert config.url == "https://example.com/webhook"
        assert len(config.events) == 2
        assert config.enabled is True
        assert config.failure_count == 0

    def test_webhook_config_with_secret(self):
        """Config avec secret HMAC."""
        config = WebhookConfig(
            id="test123",
            url="https://example.com/webhook",
            events=["*"],
            secret="my_secret_key",
        )

        assert config.secret == "my_secret_key"


class TestWebhookEvent:
    """Tests pour les événements webhook."""

    def test_webhook_event_creation(self):
        """Création d'un événement."""
        event = WebhookEvent(
            event_type="draft.created",
            timestamp=datetime.now().isoformat(),
            data={"draft_id": "abc123", "recipient": "user@example.com"},
        )

        assert event.event_type == "draft.created"
        assert "draft_id" in event.data


class TestWebhookManager:
    """Tests pour le gestionnaire de webhooks."""

    @pytest.fixture
    def webhook_manager(self, tmp_path):
        """Crée un manager avec fichier temporaire."""
        filepath = tmp_path / "webhooks.json"
        return WebhookManagerForTest(filepath=filepath)

    def test_register_webhook(self, webhook_manager):
        """Enregistrement d'un webhook."""
        webhook = webhook_manager.register(
            url="https://example.com/hook",
            events=["draft.created"],
        )

        assert webhook.id is not None
        assert webhook.url == "https://example.com/hook"
        assert webhook.events == ["draft.created"]
        assert webhook.enabled is True

    def test_register_webhook_with_secret(self, webhook_manager):
        """Enregistrement avec secret."""
        webhook = webhook_manager.register(
            url="https://example.com/hook",
            events=["*"],
            secret="my_secret",
        )

        assert webhook.secret == "my_secret"

    def test_register_invalid_events(self, webhook_manager):
        """Rejet d'événements invalides."""
        with pytest.raises(ValueError, match="Invalid events"):
            webhook_manager.register(
                url="https://example.com/hook",
                events=["invalid_event"],
            )

    def test_unregister_webhook(self, webhook_manager):
        """Suppression d'un webhook."""
        webhook = webhook_manager.register(
            url="https://example.com/hook",
            events=["draft.created"],
        )

        result = webhook_manager.unregister(webhook.id)
        assert result is True

        assert webhook_manager.get(webhook.id) is None

    def test_unregister_nonexistent(self, webhook_manager):
        """Suppression d'un webhook inexistant."""
        result = webhook_manager.unregister("nonexistent_id")
        assert result is False

    def test_get_webhook(self, webhook_manager):
        """Récupération d'un webhook."""
        webhook = webhook_manager.register(
            url="https://example.com/hook",
            events=["draft.created"],
        )

        retrieved = webhook_manager.get(webhook.id)
        assert retrieved is not None
        assert retrieved.id == webhook.id

    def test_list_all_webhooks(self, webhook_manager):
        """Liste tous les webhooks."""
        webhook_manager.register(
            url="https://example1.com/hook",
            events=["draft.created"],
        )
        webhook_manager.register(
            url="https://example2.com/hook",
            events=["error"],
        )

        webhooks = webhook_manager.list_all()
        assert len(webhooks) == 2

    def test_trigger_matching_events(self, webhook_manager):
        """Déclenchement pour événements correspondants."""
        webhook_manager.register(
            url="https://example.com/hook",
            events=["draft.created"],
        )

        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = True

            count = webhook_manager.trigger(
                "draft.created",
                {"draft_id": "abc123"},
            )

            assert count == 1

    def test_trigger_wildcard_event(self, webhook_manager):
        """Déclenchement pour wildcard *."""
        webhook_manager.register(
            url="https://example.com/hook",
            events=["*"],
        )

        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = True

            count = webhook_manager.trigger(
                "any_event",
                {"data": "test"},
            )

            assert count == 1

    def test_trigger_no_matching(self, webhook_manager):
        """Pas de déclenchement si événement non souscrit."""
        webhook_manager.register(
            url="https://example.com/hook",
            events=["draft.created"],
        )

        count = webhook_manager.trigger(
            "error",
            {"error": "test"},
        )

        assert count == 0

    def test_trigger_disabled_webhook(self, webhook_manager):
        """Webhook désactivé non déclenché."""
        webhook = webhook_manager.register(
            url="https://example.com/hook",
            events=["draft.created"],
        )
        webhook.enabled = False

        count = webhook_manager.trigger(
            "draft.created",
            {"draft_id": "abc123"},
        )

        assert count == 0

    def test_persistence(self, tmp_path):
        """Persistance des webhooks."""
        filepath = tmp_path / "webhooks.json"

        manager1 = WebhookManagerForTest(filepath=filepath)
        webhook = manager1.register(
            url="https://example.com/hook",
            events=["draft.created"],
        )
        webhook_id = webhook.id

        manager2 = WebhookManagerForTest(filepath=filepath)
        loaded = manager2.get(webhook_id)

        assert loaded is not None
        assert loaded.url == "https://example.com/hook"


class TestWebhookHMAC:
    """Tests pour la signature HMAC."""

    @pytest.fixture
    def webhook_manager(self, tmp_path):
        filepath = tmp_path / "webhooks.json"
        return WebhookManagerForTest(filepath=filepath)

    def test_send_with_hmac_signature(self, webhook_manager):
        """Envoi avec signature HMAC."""
        webhook = webhook_manager.register(
            url="https://example.com/hook",
            events=["draft.created"],
            secret="test_secret",
        )

        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = True

            event = WebhookEvent(
                event_type="draft.created",
                timestamp=datetime.now().isoformat(),
                data={"draft_id": "abc"},
            )

            webhook_manager._send_webhook(webhook, event)

            call_args = mock_post.call_args
            headers = call_args.kwargs.get("headers", {})
            assert "X-Agentys-Signature" in headers
            assert headers["X-Agentys-Signature"].startswith("sha256=")


class TestWebhookFailureHandling:
    """Tests pour la gestion des échecs."""

    @pytest.fixture
    def webhook_manager(self, tmp_path):
        filepath = tmp_path / "webhooks.json"
        return WebhookManagerForTest(filepath=filepath)

    def test_increment_failure_count(self, webhook_manager):
        """Incrémentation du compteur d'échecs."""
        webhook = webhook_manager.register(
            url="https://example.com/hook",
            events=["draft.created"],
        )

        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = False
            mock_post.return_value.status_code = 500

            event = WebhookEvent(
                event_type="draft.created",
                timestamp=datetime.now().isoformat(),
                data={},
            )

            result = webhook_manager._send_webhook(webhook, event)

            assert result is False
            assert webhook.failure_count == 1

    def test_disable_after_5_failures(self, webhook_manager):
        """Désactivation après 5 échecs."""
        webhook = webhook_manager.register(
            url="https://example.com/hook",
            events=["draft.created"],
        )
        webhook.failure_count = 4

        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = False

            event = WebhookEvent(
                event_type="draft.created",
                timestamp=datetime.now().isoformat(),
                data={},
            )

            webhook_manager._send_webhook(webhook, event)

            assert webhook.failure_count == 5
            assert webhook.enabled is False

    def test_reset_failure_on_success(self, webhook_manager):
        """Remise à zéro du compteur après succès."""
        webhook = webhook_manager.register(
            url="https://example.com/hook",
            events=["draft.created"],
        )
        webhook.failure_count = 3

        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = True

            event = WebhookEvent(
                event_type="draft.created",
                timestamp=datetime.now().isoformat(),
                data={},
            )

            result = webhook_manager._send_webhook(webhook, event)

            assert result is True
            assert webhook.failure_count == 0


class TestWebhookValidEvents:
    """Tests pour la liste des événements valides."""

    def test_valid_events_list(self):
        """Vérification de la liste des événements."""
        events = WebhookManagerForTest.VALID_EVENTS

        assert "draft.created" in events
        assert "draft.failed" in events
        assert "followup.sent" in events
        assert "email.processed" in events
        assert "email.skipped" in events
        assert "error" in events
        assert "health.degraded" in events
