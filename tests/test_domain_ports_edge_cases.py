# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests edge cases pour les Ports du domaine.

Ces tests vérifient:
- LLMResponse avec valeurs nulles/négatives/extrêmes
- LLMPort interface compliance
- EmailPort interface compliance
- NotificationPort interface compliance
"""

import pytest

from app.domain.ports import (
    LLMPort,
    LLMResponse,
    EmailPort,
    NotificationPort,
    NotificationPriority,
    PushNotificationResult,
    DeviceStorePort,
)


# ============================================================================
# TESTS - LLM RESPONSE EDGE CASES
# ============================================================================

class TestLLMResponseEdgeCases:
    """Tests edge cases pour LLMResponse."""

    def test_llm_response_minimal(self):
        """LLMResponse avec valeurs minimales."""
        response = LLMResponse(content="Test")
        assert response.content == "Test"
        assert response.input_tokens == 0
        assert response.output_tokens == 0
        assert response.model == ""

    def test_llm_response_empty_content(self):
        """LLMResponse avec contenu vide."""
        response = LLMResponse(content="")
        assert response.content == ""

    def test_llm_response_negative_tokens(self):
        """LLMResponse avec tokens négatifs (edge case non validé)."""
        response = LLMResponse(
            content="Test",
            input_tokens=-100,
            output_tokens=-50
        )
        assert response.input_tokens == -100
        assert response.output_tokens == -50

    def test_llm_response_zero_tokens(self):
        """LLMResponse avec zéro tokens."""
        response = LLMResponse(
            content="Test",
            input_tokens=0,
            output_tokens=0
        )
        assert response.input_tokens == 0
        assert response.output_tokens == 0

    def test_llm_response_large_tokens(self):
        """LLMResponse avec grands nombres de tokens."""
        response = LLMResponse(
            content="Test",
            input_tokens=1_000_000_000,
            output_tokens=500_000_000
        )
        assert response.input_tokens == 1_000_000_000
        assert response.output_tokens == 500_000_000

    def test_llm_response_unicode_content(self):
        """LLMResponse avec contenu unicode."""
        unicode_content = "日本語 🎉 émojis Überlegung"
        response = LLMResponse(content=unicode_content)
        assert response.content == unicode_content

    def test_llm_response_multiline_content(self):
        """LLMResponse avec contenu multi-lignes."""
        multiline = "Line 1\nLine 2\n\nLine 4 après saut\n\ttab"
        response = LLMResponse(content=multiline)
        assert "\n" in response.content
        assert "\t" in response.content

    def test_llm_response_whitespace_content(self):
        """LLMResponse avec uniquement espaces."""
        response = LLMResponse(content="   \n\t  ")
        assert response.content == "   \n\t  "

    def test_llm_response_special_chars(self):
        """LLMResponse avec caractères spéciaux."""
        special = '<script>alert("xss")</script>\x00\x01\x02'
        response = LLMResponse(content=special)
        assert response.content == special

    def test_llm_response_model_with_version(self):
        """LLMResponse avec modèle versionné."""
        response = LLMResponse(
            content="Test",
            model="claude-sonnet-4-20250514"
        )
        assert "sonnet" in response.model
        assert "20250514" in response.model

    def test_llm_response_model_ollama_format(self):
        """LLMResponse avec format modèle Ollama."""
        response = LLMResponse(
            content="Test",
            model="llama3.3:70b-instruct-q4_K_M"
        )
        assert "llama" in response.model
        assert ":" in response.model

    def test_llm_response_very_long_content(self):
        """LLMResponse avec contenu très long."""
        long_content = "A" * 1_000_000  # 1M caractères
        response = LLMResponse(content=long_content)
        assert len(response.content) == 1_000_000

    def test_llm_response_is_dataclass(self):
        """LLMResponse est un dataclass."""
        response = LLMResponse(content="Test")

        # Devrait avoir __dataclass_fields__
        assert hasattr(response, '__dataclass_fields__')
        assert 'content' in response.__dataclass_fields__
        assert 'input_tokens' in response.__dataclass_fields__
        assert 'output_tokens' in response.__dataclass_fields__
        assert 'model' in response.__dataclass_fields__


# ============================================================================
# TESTS - PUSH NOTIFICATION RESULT EDGE CASES
# ============================================================================

class TestPushNotificationResultEdgeCases:
    """Tests edge cases pour PushNotificationResult."""

    def test_push_result_success_minimal(self):
        """PushNotificationResult succès minimal."""
        result = PushNotificationResult(success=True)
        assert result.success is True
        assert result.message_id is None
        assert result.error_code is None
        assert result.error_message is None

    def test_push_result_success_with_message_id(self):
        """PushNotificationResult succès avec message_id."""
        result = PushNotificationResult(
            success=True,
            message_id="msg-12345-abcde"
        )
        assert result.message_id == "msg-12345-abcde"

    def test_push_result_failure_with_error(self):
        """PushNotificationResult échec avec erreur."""
        result = PushNotificationResult(
            success=False,
            error_code="INVALID_TOKEN",
            error_message="Device token is not registered"
        )
        assert result.success is False
        assert result.error_code == "INVALID_TOKEN"
        assert "not registered" in result.error_message

    def test_push_result_failure_without_error_code(self):
        """PushNotificationResult échec sans code erreur."""
        result = PushNotificationResult(
            success=False,
            error_message="Unknown error occurred"
        )
        assert result.error_code is None
        assert result.error_message is not None

    def test_push_result_success_false_with_message_id(self):
        """PushNotificationResult incohérent (échec avec message_id)."""
        result = PushNotificationResult(
            success=False,
            message_id="msg-123",
            error_message="Partial failure"
        )
        # Autorisé car pas de validation
        assert result.success is False
        assert result.message_id == "msg-123"

    def test_push_result_unicode_error_message(self):
        """PushNotificationResult avec message d'erreur unicode."""
        result = PushNotificationResult(
            success=False,
            error_message="Erreur: Token invalide 日本語"
        )
        assert "日本語" in result.error_message


# ============================================================================
# TESTS - NOTIFICATION PRIORITY ENUM
# ============================================================================

class TestNotificationPriorityEdgeCases:
    """Tests edge cases pour NotificationPriority."""

    def test_all_priorities_exist(self):
        """Toutes les priorités existent."""
        assert NotificationPriority.LOW
        assert NotificationPriority.NORMAL
        assert NotificationPriority.HIGH

    def test_priority_values(self):
        """Valeurs des priorités."""
        assert NotificationPriority.LOW.value == "low"
        assert NotificationPriority.NORMAL.value == "normal"
        assert NotificationPriority.HIGH.value == "high"

    def test_priority_from_string(self):
        """Création depuis string."""
        assert NotificationPriority("low") == NotificationPriority.LOW
        assert NotificationPriority("normal") == NotificationPriority.NORMAL
        assert NotificationPriority("high") == NotificationPriority.HIGH

    def test_priority_invalid_string_raises(self):
        """String invalide lève erreur."""
        with pytest.raises(ValueError):
            NotificationPriority("urgent")

        with pytest.raises(ValueError):
            NotificationPriority("NORMAL")  # Case sensitive

    def test_priority_comparison(self):
        """Comparaison de priorités."""
        assert NotificationPriority.LOW != NotificationPriority.HIGH
        assert NotificationPriority.NORMAL == NotificationPriority.NORMAL


# ============================================================================
# TESTS - LLM PORT ABSTRACT CLASS
# ============================================================================

class TestLLMPortAbstract:
    """Tests pour vérifier que LLMPort est une interface abstraite."""

    def test_llm_port_cannot_instantiate(self):
        """LLMPort ne peut pas être instanciée directement."""
        with pytest.raises(TypeError):
            LLMPort()

    def test_llm_port_requires_name_property(self):
        """LLMPort requiert la propriété name."""
        class IncompleteAdapter(LLMPort):
            @property
            def model(self) -> str:
                return "test"

            def complete(self, system, user, max_tokens=1024):
                return LLMResponse(content="test")

        with pytest.raises(TypeError):
            IncompleteAdapter()

    def test_llm_port_requires_model_property(self):
        """LLMPort requiert la propriété model."""
        class IncompleteAdapter(LLMPort):
            @property
            def name(self) -> str:
                return "test"

            def complete(self, system, user, max_tokens=1024):
                return LLMResponse(content="test")

        with pytest.raises(TypeError):
            IncompleteAdapter()

    def test_llm_port_requires_complete_method(self):
        """LLMPort requiert la méthode complete."""
        class IncompleteAdapter(LLMPort):
            @property
            def name(self) -> str:
                return "test"

            @property
            def model(self) -> str:
                return "test"

        with pytest.raises(TypeError):
            IncompleteAdapter()

    def test_llm_port_complete_implementation(self):
        """LLMPort implémentation complète."""
        class CompleteAdapter(LLMPort):
            @property
            def name(self) -> str:
                return "test-adapter"

            @property
            def model(self) -> str:
                return "test-model"

            def complete(self, system, user, max_tokens=1024):
                return LLMResponse(
                    content="Generated content",
                    input_tokens=100,
                    output_tokens=50,
                    model=self.model
                )

        adapter = CompleteAdapter()
        assert adapter.name == "test-adapter"
        assert adapter.model == "test-model"

        response = adapter.complete("System", "User")
        assert isinstance(response, LLMResponse)

    def test_llm_port_is_available_default(self):
        """is_available a une implémentation par défaut."""
        class MinimalAdapter(LLMPort):
            @property
            def name(self) -> str:
                return "test"

            @property
            def model(self) -> str:
                return "test"

            def complete(self, system, user, max_tokens=1024):
                return LLMResponse(content="test")

        adapter = MinimalAdapter()
        # Doit retourner True par défaut
        assert adapter.is_available() is True


# ============================================================================
# TESTS - EMAIL PORT ABSTRACT CLASS
# ============================================================================

class TestEmailPortAbstract:
    """Tests pour vérifier que EmailPort est une interface abstraite."""

    def test_email_port_cannot_instantiate(self):
        """EmailPort ne peut pas être instanciée directement."""
        with pytest.raises(TypeError):
            EmailPort()


# ============================================================================
# TESTS - NOTIFICATION PORT ABSTRACT CLASS
# ============================================================================

class TestNotificationPortAbstract:
    """Tests pour vérifier que NotificationPort est une interface abstraite."""

    def test_notification_port_cannot_instantiate(self):
        """NotificationPort ne peut pas être instanciée directement."""
        with pytest.raises(TypeError):
            NotificationPort()


# ============================================================================
# TESTS - DEVICE STORE PORT ABSTRACT CLASS
# ============================================================================

class TestDeviceStorePortAbstract:
    """Tests pour vérifier que DeviceStorePort est une interface abstraite."""

    def test_device_store_port_cannot_instantiate(self):
        """DeviceStorePort ne peut pas être instanciée directement."""
        with pytest.raises(TypeError):
            DeviceStorePort()
