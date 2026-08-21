# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests edge cases pour les Ports (Interfaces) du domaine.

Ces tests vérifient:
- Les dataclasses de réponse (LLMResponse)
- Les contrats des ports abstraits
- Les implémentations mock des ports
"""

import pytest
from abc import ABC
from typing import List

from app.domain.entities import Email
from app.domain.ports import (
    LLMPort,
    LLMResponse,
    EmailPort,
    NotificationPort,
    NotificationPlatform,
    NotificationPriority,
    PushNotificationResult,
    DeviceStorePort,
    WizardConfigPort,
)


# ============================================================================
# TESTS - LLMResponse EDGE CASES
# ============================================================================

class TestLLMResponseDataclass:
    """Tests edge cases pour LLMResponse."""

    def test_default_values(self):
        """Valeurs par défaut."""
        response = LLMResponse(content="Test")

        assert response.content == "Test"
        assert response.input_tokens == 0
        assert response.output_tokens == 0
        assert response.model == ""

    def test_negative_tokens(self):
        """Tokens négatifs (edge case malformé)."""
        response = LLMResponse(
            content="Test",
            input_tokens=-100,
            output_tokens=-50,
            model="test"
        )
        # Pas de validation, donc accepté
        assert response.input_tokens == -100
        assert response.output_tokens == -50

    def test_zero_tokens(self):
        """Tokens à zéro."""
        response = LLMResponse(
            content="",
            input_tokens=0,
            output_tokens=0,
            model=""
        )
        assert response.input_tokens == 0
        assert response.output_tokens == 0

    def test_very_large_tokens(self):
        """Très grands nombres de tokens."""
        response = LLMResponse(
            content="Test",
            input_tokens=10_000_000_000,
            output_tokens=5_000_000_000,
            model="test"
        )
        assert response.input_tokens == 10_000_000_000
        assert response.output_tokens == 5_000_000_000

    def test_unicode_content(self):
        """Contenu avec unicode complexe."""
        unicode_content = "🎉 Résumé: 中文 日本語 العربية עברית\nEmoji: 👨‍👩‍👧‍👦"
        response = LLMResponse(
            content=unicode_content,
            input_tokens=100,
            output_tokens=50,
            model="test"
        )
        assert response.content == unicode_content

    def test_special_characters(self):
        """Caractères spéciaux et d'échappement."""
        special_content = "<script>alert('xss')</script>\n\t\r"
        response = LLMResponse(
            content=special_content,
            input_tokens=10,
            output_tokens=10,
            model="test"
        )
        assert "<script>" in response.content
        assert "\t" in response.content

    def test_very_long_content(self):
        """Contenu très long."""
        long_content = "A" * 1_000_000  # 1M caractères
        response = LLMResponse(
            content=long_content,
            input_tokens=500000,
            output_tokens=500000,
            model="test"
        )
        assert len(response.content) == 1_000_000

    def test_empty_content_with_tokens(self):
        """Contenu vide mais avec tokens (réponse tronquée)."""
        response = LLMResponse(
            content="",
            input_tokens=1000,
            output_tokens=0,
            model="claude-sonnet-4-20250514"
        )
        assert response.content == ""
        assert response.input_tokens == 1000

    def test_multiline_content(self):
        """Contenu multi-lignes."""
        multiline = "Line 1\nLine 2\r\nLine 3\rLine 4"
        response = LLMResponse(content=multiline, input_tokens=10, output_tokens=10, model="")
        assert "Line 1" in response.content
        assert "Line 4" in response.content

    def test_model_name_with_special_chars(self):
        """Nom de modèle avec caractères spéciaux."""
        response = LLMResponse(
            content="Test",
            input_tokens=10,
            output_tokens=10,
            model="claude-3.5-sonnet@20240620:v2"
        )
        assert response.model == "claude-3.5-sonnet@20240620:v2"


# ============================================================================
# TESTS - PushNotificationResult EDGE CASES
# ============================================================================

class TestPushNotificationResultDataclass:
    """Tests edge cases pour PushNotificationResult."""

    def test_success_result(self):
        """Résultat de succès."""
        result = PushNotificationResult(
            success=True,
            message_id="msg-123"
        )
        assert result.success is True
        assert result.message_id == "msg-123"
        assert result.error_code is None
        assert result.error_message is None

    def test_failure_result(self):
        """Résultat d'échec."""
        result = PushNotificationResult(
            success=False,
            error_code="INVALID_TOKEN",
            error_message="Token expired or invalid"
        )
        assert result.success is False
        assert result.error_code == "INVALID_TOKEN"
        assert result.error_message == "Token expired or invalid"

    def test_success_without_message_id(self):
        """Succès sans message_id (edge case)."""
        result = PushNotificationResult(success=True)
        assert result.success is True
        assert result.message_id is None

    def test_failure_without_error_details(self):
        """Échec sans détails d'erreur."""
        result = PushNotificationResult(success=False)
        assert result.success is False
        assert result.error_code is None
        assert result.error_message is None

    def test_contradictory_state(self):
        """État contradictoire (success=True avec error_code)."""
        result = PushNotificationResult(
            success=True,
            error_code="PARTIAL_FAILURE",
            message_id="msg-456"
        )
        # Pas de validation, donc accepté
        assert result.success is True
        assert result.error_code == "PARTIAL_FAILURE"

    def test_unicode_error_message(self):
        """Message d'erreur avec unicode."""
        result = PushNotificationResult(
            success=False,
            error_message="Échec: token invalide 🚫 日本語エラー"
        )
        assert "🚫" in result.error_message
        assert "日本語" in result.error_message


# ============================================================================
# TESTS - NotificationPriority ENUM
# ============================================================================

class TestNotificationPriorityEnum:
    """Tests edge cases pour NotificationPriority."""

    def test_all_priorities_exist(self):
        """Toutes les priorités existent."""
        assert NotificationPriority.LOW.value == "low"
        assert NotificationPriority.NORMAL.value == "normal"
        assert NotificationPriority.HIGH.value == "high"

    def test_priority_from_value(self):
        """Création depuis valeur string."""
        assert NotificationPriority("low") == NotificationPriority.LOW
        assert NotificationPriority("normal") == NotificationPriority.NORMAL
        assert NotificationPriority("high") == NotificationPriority.HIGH

    def test_invalid_priority_raises(self):
        """Priorité invalide lève une erreur."""
        with pytest.raises(ValueError):
            NotificationPriority("urgent")

        with pytest.raises(ValueError):
            NotificationPriority("NORMAL")  # Case sensitive

    def test_comparison(self):
        """Comparaison de priorités."""
        assert NotificationPriority.LOW != NotificationPriority.HIGH
        assert NotificationPriority.NORMAL == NotificationPriority.NORMAL


# ============================================================================
# TESTS - NotificationPlatform ENUM
# ============================================================================

class TestNotificationPlatformEnum:
    """Tests edge cases pour NotificationPlatform."""

    def test_all_platforms_exist(self):
        """Toutes les plateformes existent."""
        assert NotificationPlatform.IOS.value == "ios"
        assert NotificationPlatform.ANDROID.value == "android"
        assert NotificationPlatform.WEB.value == "web"

    def test_platform_from_value(self):
        """Création depuis valeur string."""
        assert NotificationPlatform("ios") == NotificationPlatform.IOS
        assert NotificationPlatform("android") == NotificationPlatform.ANDROID
        assert NotificationPlatform("web") == NotificationPlatform.WEB

    def test_invalid_platform_raises(self):
        """Plateforme invalide lève une erreur."""
        with pytest.raises(ValueError):
            NotificationPlatform("apns")

        with pytest.raises(ValueError):
            NotificationPlatform("")


# ============================================================================
# TESTS - MOCK LLM PORT IMPLEMENTATION
# ============================================================================

class MockLLMAdapter(LLMPort):
    """Implémentation mock de LLMPort pour tests."""

    def __init__(self, response_content: str = "Mock response"):
        self._response_content = response_content
        self._model = "mock-model"
        self._should_fail = False
        self._failure_error = None

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return self._model

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        if self._should_fail:
            raise self._failure_error or Exception("Mock failure")

        return LLMResponse(
            content=self._response_content,
            input_tokens=len(system) + len(user),
            output_tokens=len(self._response_content),
            model=self._model
        )

    def set_should_fail(self, should_fail: bool, error: Exception = None):
        self._should_fail = should_fail
        self._failure_error = error


class TestMockLLMAdapter:
    """Tests pour l'implémentation mock de LLMPort."""

    def test_basic_complete(self):
        """Complétion basique."""
        adapter = MockLLMAdapter(response_content="Test response")
        response = adapter.complete(
            system="System prompt",
            user="User message"
        )

        assert response.content == "Test response"
        assert response.model == "mock-model"
        assert adapter.name == "mock"

    def test_token_counting(self):
        """Comptage des tokens basé sur la longueur."""
        adapter = MockLLMAdapter(response_content="Short")
        response = adapter.complete(
            system="A" * 100,  # 100 chars
            user="B" * 50     # 50 chars
        )

        assert response.input_tokens == 150  # system + user
        assert response.output_tokens == 5   # len("Short")

    def test_failure_mode(self):
        """Mode échec."""
        adapter = MockLLMAdapter()
        adapter.set_should_fail(True, ValueError("API Error"))

        with pytest.raises(ValueError, match="API Error"):
            adapter.complete(system="", user="")

    def test_is_available_default(self):
        """is_available par défaut."""
        adapter = MockLLMAdapter()
        assert adapter.is_available() is True

    def test_empty_prompts(self):
        """Prompts vides."""
        adapter = MockLLMAdapter(response_content="Response")
        response = adapter.complete(system="", user="")

        assert response.content == "Response"
        assert response.input_tokens == 0

    def test_unicode_prompts(self):
        """Prompts avec unicode."""
        adapter = MockLLMAdapter(response_content="Réponse 🎉")
        response = adapter.complete(
            system="Système: réponds en français",
            user="Question: 日本語で答えて"
        )

        assert "Réponse" in response.content
        assert "🎉" in response.content


# ============================================================================
# TESTS - MOCK EMAIL PORT IMPLEMENTATION
# ============================================================================

class MockEmailAdapter(EmailPort):
    """Implémentation mock de EmailPort pour tests."""

    def __init__(self):
        self._authenticated = False
        self._emails: List[Email] = []
        self._drafts = {}
        self._should_fail = False

    @property
    def name(self) -> str:
        return "mock"

    def authenticate(self) -> bool:
        if self._should_fail:
            return False
        self._authenticated = True
        return True

    def get_unread_emails(self, limit: int = 10) -> List[Email]:
        if not self._authenticated:
            return []
        return self._emails[:limit]

    def create_draft(self, email: Email, reply_content: str) -> str:
        if not self._authenticated:
            return None
        draft_id = f"draft-{email.id}"
        self._drafts[draft_id] = reply_content
        return draft_id

    def mark_as_read(self, email_id: str) -> bool:
        if not self._authenticated:
            return False
        return True

    # Helpers pour tests
    def add_email(self, email: Email):
        self._emails.append(email)

    def set_should_fail(self, should_fail: bool):
        self._should_fail = should_fail


class TestMockEmailAdapter:
    """Tests pour l'implémentation mock de EmailPort."""

    @pytest.fixture
    def adapter(self):
        return MockEmailAdapter()

    @pytest.fixture
    def sample_email(self):
        return Email(
            id="test-123",
            subject="Test Subject",
            body="Test Body",
            sender="sender@test.com",
            recipients=["recipient@test.com"]
        )

    def test_authenticate_success(self, adapter):
        """Authentification réussie."""
        assert adapter.authenticate() is True
        assert adapter._authenticated is True

    def test_authenticate_failure(self, adapter):
        """Authentification échouée."""
        adapter.set_should_fail(True)
        assert adapter.authenticate() is False
        assert adapter._authenticated is False

    def test_get_unread_emails_not_authenticated(self, adapter, sample_email):
        """Récupération sans authentification."""
        adapter.add_email(sample_email)

        # Sans authentification
        emails = adapter.get_unread_emails()
        assert emails == []

    def test_get_unread_emails_authenticated(self, adapter, sample_email):
        """Récupération avec authentification."""
        adapter.authenticate()
        adapter.add_email(sample_email)

        emails = adapter.get_unread_emails()
        assert len(emails) == 1
        assert emails[0].id == "test-123"

    def test_get_unread_emails_with_limit(self, adapter):
        """Récupération avec limite."""
        adapter.authenticate()

        for i in range(10):
            adapter.add_email(Email(
                id=f"email-{i}",
                subject=f"Subject {i}",
                body=f"Body {i}",
                sender="sender@test.com"
            ))

        emails = adapter.get_unread_emails(limit=5)
        assert len(emails) == 5
        assert emails[0].id == "email-0"

    def test_create_draft(self, adapter, sample_email):
        """Création de brouillon."""
        adapter.authenticate()

        draft_id = adapter.create_draft(sample_email, "Reply content")

        assert draft_id == "draft-test-123"
        assert "draft-test-123" in adapter._drafts

    def test_create_draft_not_authenticated(self, adapter, sample_email):
        """Création de brouillon sans authentification."""
        draft_id = adapter.create_draft(sample_email, "Reply content")
        assert draft_id is None

    def test_mark_as_read(self, adapter, sample_email):
        """Marquer comme lu."""
        adapter.authenticate()
        adapter.add_email(sample_email)

        result = adapter.mark_as_read("test-123")
        assert result is True

    def test_mark_as_read_not_authenticated(self, adapter):
        """Marquer comme lu sans authentification."""
        result = adapter.mark_as_read("test-123")
        assert result is False

    def test_name_property(self, adapter):
        """Propriété name."""
        assert adapter.name == "mock"

    def test_is_available_default(self, adapter):
        """is_available par défaut."""
        assert adapter.is_available() is True


# ============================================================================
# TESTS - PORT INTERFACE COMPLIANCE
# ============================================================================

class TestPortInterfaceCompliance:
    """Tests de conformité des interfaces de port."""

    def test_llm_port_is_abstract(self):
        """LLMPort est une classe abstraite."""
        assert issubclass(LLMPort, ABC)

    def test_email_port_is_abstract(self):
        """EmailPort est une classe abstraite."""
        assert issubclass(EmailPort, ABC)

    def test_notification_port_is_abstract(self):
        """NotificationPort est une classe abstraite."""
        assert issubclass(NotificationPort, ABC)

    def test_device_store_port_is_abstract(self):
        """DeviceStorePort est une classe abstraite."""
        assert issubclass(DeviceStorePort, ABC)

    def test_wizard_config_port_is_abstract(self):
        """WizardConfigPort est une classe abstraite."""
        assert issubclass(WizardConfigPort, ABC)

    def test_cannot_instantiate_llm_port(self):
        """Impossible d'instancier LLMPort directement."""
        with pytest.raises(TypeError):
            LLMPort()

    def test_cannot_instantiate_email_port(self):
        """Impossible d'instancier EmailPort directement."""
        with pytest.raises(TypeError):
            EmailPort()
