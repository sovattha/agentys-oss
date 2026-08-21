# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases non couverts.

Ce fichier suit les principes de Clean Architecture:
- Entities: Tests de validation des entités (StandardEmail)
- Use Cases: Tests des règles métier (agents, pipeline)
- Interface Adapters: Tests des providers et factory
- Frameworks: Tests d'intégration daemon

Edge cases couverts:
1. apply_label() - méthode non testée
2. Validation email (NULL, formats invalides, Unicode)
3. Gestion erreurs (ConnectionError, TimeoutError, credentials)
4. Agents (JSON malformé, réponses vides, token overflow)
5. Factory (configuration partielle, providers invalides)
"""

import pytest
from datetime import datetime
from typing import List, Optional
from unittest.mock import MagicMock, patch

from app.interfaces.email_provider import EmailProvider, StandardEmail
from app.domain.ports import LLMResponse


# ============================================================================
# FIXTURES COMMUNES
# ============================================================================

@pytest.fixture
def minimal_email():
    """Email avec le minimum de champs requis."""
    return StandardEmail(id="min-001", sender="test@example.com")


@pytest.fixture
def email_with_nulls():
    """Email avec des champs optionnels à None/vides."""
    return StandardEmail(
        id="null-001",
        sender="",
        sender_name=None,
        to=[],
        cc=[],
        subject="",
        body="",
        body_html=None,
        received_at=None,
        is_read=False,
        has_attachments=False,
        conversation_id=None,
        provider_source="test"
    )


@pytest.fixture
def unicode_email():
    """Email avec caractères Unicode spéciaux."""
    return StandardEmail(
        id="unicode-001",
        sender="émile.dupont@société.fr",
        sender_name="Émile Dupont 你好",
        to=["réponse@société.fr"],
        cc=["café@thé.com"],
        subject="日本語 Subject 한국어 🎉",
        body="Contenu avec émojis 🚀 et caractères spéciaux: ñ, ü, ø, ∑",
        provider_source="test"
    )


# ============================================================================
# TESTS - STANDARD EMAIL ENTITY VALIDATION (Clean Architecture: Entities)
# ============================================================================

class TestStandardEmailValidation:
    """Tests de validation pour l'entité StandardEmail."""

    def test_email_with_empty_sender(self, email_with_nulls):
        """Email avec sender vide."""
        assert email_with_nulls.sender == ""
        # sender_display doit retourner sender si sender_name est None
        assert email_with_nulls.sender_display == ""

    def test_email_with_none_sender_name(self, minimal_email):
        """sender_display retourne sender si sender_name est None."""
        assert minimal_email.sender_name is None
        assert minimal_email.sender_display == "test@example.com"

    def test_email_preview_empty_body(self, email_with_nulls):
        """preview retourne chaîne vide si body est vide."""
        assert email_with_nulls.preview == ""

    def test_email_preview_short_body(self):
        """preview retourne le body complet si < 100 chars."""
        email = StandardEmail(
            id="short-001",
            sender="test@test.com",
            body="Short body content"
        )
        assert email.preview == "Short body content"
        assert "..." not in email.preview

    def test_email_preview_long_body(self):
        """preview tronque et ajoute ... si > 100 chars."""
        long_body = "x" * 150
        email = StandardEmail(
            id="long-001",
            sender="test@test.com",
            body=long_body
        )
        assert len(email.preview) == 103  # 100 chars + "..."
        assert email.preview.endswith("...")

    def test_email_str_representation(self, minimal_email):
        """__str__ retourne un format lisible."""
        result = str(minimal_email)
        assert "test@example.com" in result
        assert "[test]" in result or "test" in result.lower()

    def test_email_with_unicode_characters(self, unicode_email):
        """Email avec caractères Unicode fonctionne correctement."""
        assert "émile" in unicode_email.sender
        assert "你好" in unicode_email.sender_name
        assert "🎉" in unicode_email.subject
        assert "🚀" in unicode_email.body

    def test_email_with_special_email_formats(self):
        """Emails avec formats spéciaux."""
        # Email avec + (alias)
        email_plus = StandardEmail(
            id="plus-001",
            sender="user+alias@example.com"
        )
        assert email_plus.sender == "user+alias@example.com"

        # Email avec sous-domaine
        email_subdomain = StandardEmail(
            id="sub-001",
            sender="user@sub.domain.example.com"
        )
        assert "sub.domain" in email_subdomain.sender

    def test_email_with_very_long_subject(self):
        """Email avec sujet très long (> 998 chars, limite RFC 5321)."""
        long_subject = "S" * 1000
        email = StandardEmail(
            id="long-subj-001",
            sender="test@test.com",
            subject=long_subject
        )
        assert len(email.subject) == 1000

    def test_email_with_html_in_subject(self):
        """Email avec HTML potentiellement dangereux dans le sujet."""
        xss_subject = '<script>alert("XSS")</script>Important'
        email = StandardEmail(
            id="xss-001",
            sender="test@test.com",
            subject=xss_subject
        )
        # Le sujet doit être stocké tel quel (échappement fait ailleurs)
        assert "<script>" in email.subject


# ============================================================================
# TESTS - APPLY_LABEL (Non testé - Interface Adapters)
# ============================================================================

class MockEmailProviderWithLabel(EmailProvider):
    """Mock provider avec implémentation de apply_label."""

    def __init__(self):
        self._emails = {}
        self._labels = {}  # {email_id: [labels]}
        self._authenticated = False

    @property
    def provider_name(self) -> str:
        return "mock_with_label"

    def authenticate(self) -> bool:
        self._authenticated = True
        return True

    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        return []

    def get_message_by_id(self, message_id: str) -> Optional[StandardEmail]:
        return self._emails.get(message_id)

    def create_draft(self, to, subject, body, reply_to_id=None, cc=None, is_html=False):
        return "draft-001"

    def send_draft(self, draft_id: str) -> bool:
        return True

    def mark_as_read(self, message_id: str) -> bool:
        return True

    def mark_as_unread(self, message_id: str) -> bool:
        return True

    def apply_label(self, message_id: str, label: str) -> bool:
        """Implémentation de apply_label pour les tests."""
        if not message_id or not label:
            return False
        if message_id not in self._labels:
            self._labels[message_id] = []
        self._labels[message_id].append(label)
        return True

    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        return []

    def get_draft_by_id(self, draft_id: str) -> Optional[StandardEmail]:
        return None

    def update_draft(
        self,
        draft_id: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        is_html: bool = False
    ) -> bool:
        return True


class TestApplyLabel:
    """Tests pour la méthode apply_label (non testée auparavant)."""

    @pytest.fixture
    def provider_with_label(self):
        """Provider avec support des labels."""
        return MockEmailProviderWithLabel()

    def test_apply_label_default_returns_false(self, mock_provider):
        """La méthode par défaut retourne False."""
        # mock_provider vient de conftest.py
        result = mock_provider.apply_label("msg-001", "URGENT")
        assert result is False

    def test_apply_label_success(self, provider_with_label):
        """apply_label réussit avec des paramètres valides."""
        result = provider_with_label.apply_label("msg-001", "URGENT")
        assert result is True
        assert "URGENT" in provider_with_label._labels["msg-001"]

    def test_apply_label_multiple(self, provider_with_label):
        """Plusieurs labels peuvent être appliqués au même email."""
        provider_with_label.apply_label("msg-001", "URGENT")
        provider_with_label.apply_label("msg-001", "VIP")
        provider_with_label.apply_label("msg-001", "IMPORTANT")

        assert len(provider_with_label._labels["msg-001"]) == 3
        assert "URGENT" in provider_with_label._labels["msg-001"]
        assert "VIP" in provider_with_label._labels["msg-001"]

    def test_apply_label_empty_message_id(self, provider_with_label):
        """apply_label avec message_id vide retourne False."""
        result = provider_with_label.apply_label("", "URGENT")
        assert result is False

    def test_apply_label_empty_label(self, provider_with_label):
        """apply_label avec label vide retourne False."""
        result = provider_with_label.apply_label("msg-001", "")
        assert result is False

    def test_apply_label_none_values(self, provider_with_label):
        """apply_label avec None retourne False."""
        result = provider_with_label.apply_label(None, "URGENT")
        assert result is False

        result = provider_with_label.apply_label("msg-001", None)
        assert result is False

    def test_apply_label_special_characters(self, provider_with_label):
        """apply_label avec caractères spéciaux dans le label."""
        result = provider_with_label.apply_label("msg-001", "🏷️ URGENT")
        assert result is True

        result = provider_with_label.apply_label("msg-001", "Priority/High")
        assert result is True

    def test_apply_label_unicode(self, provider_with_label):
        """apply_label avec label Unicode."""
        result = provider_with_label.apply_label("msg-001", "重要")
        assert result is True
        assert "重要" in provider_with_label._labels["msg-001"]


# ============================================================================
# TESTS - ERROR HANDLING (Interface Adapters)
# ============================================================================

class TestProviderErrorHandling:
    """Tests de gestion des erreurs pour les providers."""

    @pytest.fixture
    def failing_provider(self):
        """Provider qui lève des exceptions."""
        provider = MagicMock(spec=EmailProvider)
        provider.provider_name = "failing_mock"
        return provider

    def test_authenticate_connection_error(self, failing_provider):
        """authenticate() gère les erreurs de connexion."""
        failing_provider.authenticate.side_effect = ConnectionError("Network unreachable")

        with pytest.raises(ConnectionError) as exc_info:
            failing_provider.authenticate()

        assert "Network unreachable" in str(exc_info.value)

    def test_authenticate_timeout_error(self, failing_provider):
        """authenticate() gère les timeouts."""
        failing_provider.authenticate.side_effect = TimeoutError("Connection timed out")

        with pytest.raises(TimeoutError):
            failing_provider.authenticate()

    def test_get_unread_connection_error(self, failing_provider):
        """get_unread_messages() gère les erreurs de connexion."""
        failing_provider.get_unread_messages.side_effect = ConnectionError("Lost connection")

        with pytest.raises(ConnectionError):
            failing_provider.get_unread_messages()

    def test_create_draft_api_error(self, failing_provider):
        """create_draft() gère les erreurs API."""
        failing_provider.create_draft.side_effect = Exception("API Error 500")

        with pytest.raises(Exception) as exc_info:
            failing_provider.create_draft(
                to=["test@test.com"],
                subject="Test",
                body="Body"
            )

        assert "API Error" in str(exc_info.value)

    def test_send_draft_returns_false_on_error(self, mock_provider):
        """send_draft() retourne False pour un draft inexistant."""
        result = mock_provider.send_draft("nonexistent-draft-id")
        assert result is False

    def test_mark_as_read_returns_false_on_error(self, mock_provider):
        """mark_as_read() retourne False pour un message inexistant."""
        result = mock_provider.mark_as_read("nonexistent-message-id")
        assert result is False


# ============================================================================
# TESTS - FACTORY EDGE CASES (Interface Adapters)
# ============================================================================

class TestFactoryEdgeCases:
    """Tests edge cases pour la factory de providers."""

    def test_unknown_provider_raises_error(self):
        """Provider inconnu lève ProviderConfigurationError."""
        from app.providers.factory import get_email_provider, ProviderConfigurationError

        with pytest.raises(ProviderConfigurationError) as exc_info:
            get_email_provider("UNKNOWN_PROVIDER")

        assert "Provider inconnu" in str(exc_info.value)
        assert "UNKNOWN_PROVIDER" in str(exc_info.value)

    def test_provider_type_case_insensitive(self):
        """Le type de provider est insensible à la casse."""
        from app.providers.factory import get_email_provider, ProviderConfigurationError

        # Test avec mocks pour éviter les dépendances externes (azure, google, etc.)
        with patch("app.providers.factory._create_outlook_provider") as mock_create:
            mock_create.side_effect = ProviderConfigurationError("Test config error")

            # Ces appels doivent tous atteindre _create_outlook_provider
            # car le type est normalisé en majuscules
            with pytest.raises(ProviderConfigurationError):
                get_email_provider("outlook")  # minuscule

            with pytest.raises(ProviderConfigurationError):
                get_email_provider("OUTLOOK")  # majuscule

            with pytest.raises(ProviderConfigurationError):
                get_email_provider("Outlook")  # mixte

            # Vérifier que le mock a été appelé 3 fois
            assert mock_create.call_count == 3

    def test_provider_type_with_whitespace(self):
        """Le type de provider gère les espaces."""
        from app.providers.factory import get_email_provider, ProviderConfigurationError

        with patch("app.providers.factory._create_outlook_provider") as mock_create:
            mock_create.side_effect = ProviderConfigurationError("Test config error")

            with pytest.raises(ProviderConfigurationError):
                get_email_provider("  OUTLOOK  ")

    def test_empty_provider_type_uses_env_or_default(self):
        """Provider vide utilise ENV ou défaut."""
        from app.providers.factory import get_email_provider, ProviderConfigurationError
        import os

        # Avec None et ENV=GMAIL, doit appeler _create_gmail_provider
        with patch.dict(os.environ, {'EMAIL_PROVIDER_TYPE': 'GMAIL'}):
            with patch("app.providers.factory._create_gmail_provider") as mock_gmail:
                mock_gmail.side_effect = ProviderConfigurationError("Gmail not configured")

                with pytest.raises(ProviderConfigurationError):
                    get_email_provider(None)

                mock_gmail.assert_called_once()

    def test_validate_provider_config_returns_dict(self):
        """validate_provider_config retourne un dict de statuts."""
        from app.providers.factory import validate_provider_config

        result = validate_provider_config("OUTLOOK")

        assert isinstance(result, dict)
        assert "AZURE_TENANT_ID" in result
        assert "AZURE_CLIENT_ID" in result

    def test_validate_unknown_provider_returns_empty(self):
        """validate_provider_config retourne dict vide pour provider inconnu."""
        from app.providers.factory import validate_provider_config

        result = validate_provider_config("UNKNOWN")
        assert result == {}

    def test_list_available_providers(self):
        """list_available_providers retourne tous les providers."""
        from app.providers.factory import list_available_providers

        providers = list_available_providers()

        assert "OUTLOOK" in providers
        assert "GMAIL" in providers
        assert "IMAP" in providers
        assert "SMTP" in providers
        assert "IMAP_SMTP" in providers


# ============================================================================
# TESTS - AGENT JSON PARSING (Use Cases)
# ============================================================================

class TestAgentJsonParsing:
    """Tests pour le parsing JSON dans les agents."""

    @pytest.fixture
    def mock_container(self):
        """Container mocké pour les agents."""
        from app.agents import TokenCounter
        container = MagicMock()
        container.llm = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.token_usage = TokenCounter()
        return container

    @patch("app.agents.get_container")
    def test_prioritization_agent_malformed_json(self, mock_get_container, mock_container):
        """PrioritizationAgent gère le JSON malformé."""
        from app.agents import PrioritizationAgent

        # LLM retourne du JSON invalide
        mock_container.llm.complete.return_value = LLMResponse(
            content="This is not valid JSON {broken",
            input_tokens=100,
            output_tokens=50,
            model="test"
        )
        mock_get_container.return_value = mock_container

        agent = PrioritizationAgent()
        result = agent.analyze("Test email content")

        # Doit retourner les valeurs par défaut
        assert result["urgency"] == 50
        assert result["vip"] == 50
        assert result["sentiment"] == 0
        assert result["priority_score"] == 50

    @patch("app.agents.get_container")
    def test_prioritization_agent_empty_response(self, mock_get_container, mock_container):
        """PrioritizationAgent gère une réponse vide."""
        mock_container.llm.complete.return_value = LLMResponse(
            content="",
            input_tokens=100,
            output_tokens=0,
            model="test"
        )
        mock_get_container.return_value = mock_container

        from app.agents import PrioritizationAgent
        agent = PrioritizationAgent()
        result = agent.analyze("Test")

        assert result["priority_score"] == 50


# ============================================================================
# TESTS - AGENT EMPTY/NULL RESPONSES (Use Cases)
# ============================================================================

class TestAgentEmptyResponses:
    """Tests pour les réponses vides/nulles des agents."""

    @pytest.fixture
    def mock_container_empty(self):
        """Container qui retourne des réponses vides."""
        from app.agents import TokenCounter
        container = MagicMock()
        container.llm = MagicMock()
        container.llm.complete.return_value = LLMResponse(
            content="",
            input_tokens=0,
            output_tokens=0,
            model="test"
        )
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.token_usage = TokenCounter()
        return container

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_drafter_empty_response(self, mock_kb, mock_get_container, mock_container_empty):
        """DrafterAgent avec réponse vide."""
        from app.agents import DrafterAgent

        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container_empty

        agent = DrafterAgent()
        result = agent.draft("Test email")

        assert result == ""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_critic_empty_response(self, mock_kb, mock_get_container, mock_container_empty):
        """CriticAgent avec réponse vide."""
        from app.agents import CriticAgent

        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container_empty

        agent = CriticAgent()
        result = agent.evaluate("Email", "Draft")

        assert result == ""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_critic_is_valid_empty_string(self, mock_kb, mock_get_container, mock_container_empty):
        """is_valid retourne False pour chaîne vide."""
        from app.agents import CriticAgent

        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container_empty

        agent = CriticAgent()

        assert agent.is_valid("") is False
        assert agent.is_valid("   ") is False

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_critic_is_valid_whitespace_only(self, mock_kb, mock_get_container, mock_container_empty):
        """is_valid gère les espaces blancs."""
        from app.agents import CriticAgent

        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container_empty

        agent = CriticAgent()

        assert agent.is_valid("\n\t  \n") is False


# ============================================================================
# TESTS - TOKEN COUNTER EDGE CASES (Use Cases)
# ============================================================================

class TestTokenCounterEdgeCases:
    """Tests edge cases pour TokenCounter."""

    def test_token_counter_negative_values(self):
        """TokenCounter avec valeurs négatives lève InvalidBoundsError."""
        from app.agents import TokenCounter
        from app.domain.exceptions import InvalidBoundsError

        counter = TokenCounter()
        with pytest.raises(InvalidBoundsError):
            counter.add(-100, -50)

    def test_token_counter_very_large_values(self):
        """TokenCounter avec très grandes valeurs."""
        from app.agents import TokenCounter

        counter = TokenCounter()
        counter.add(1_000_000_000, 500_000_000, "claude-sonnet-4-20250514")

        assert counter.total == 1_500_000_000
        # Le coût doit être calculable
        assert counter.cost > 0

    def test_token_counter_zero_values(self):
        """TokenCounter avec valeurs nulles."""
        from app.agents import TokenCounter

        counter = TokenCounter()
        counter.add(0, 0, "claude-sonnet-4-20250514")

        assert counter.total == 0
        assert counter.cost == 0

    def test_token_counter_model_empty_string(self):
        """TokenCounter avec modèle chaîne vide."""
        from app.agents import TokenCounter

        counter = TokenCounter()
        counter.add(100, 50, "")

        # Modèle vide accepté
        assert counter.model == ""

    def test_token_counter_str_zero_values(self):
        """__str__ avec valeurs nulles."""
        from app.agents import TokenCounter

        counter = TokenCounter()
        result = str(counter)

        assert "0" in result


# ============================================================================
# TESTS - EMAIL PIPELINE EDGE CASES (Use Cases)
# ============================================================================

class TestEmailPipelineEdgeCases:
    """Tests edge cases pour le pipeline de traitement."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_process_empty_email_content(self, mock_kb, mock_get_container):
        """Pipeline avec contenu email vide."""
        from app.agents import DrafterAgent, CriticAgent, process_single_email, TokenCounter

        mock_kb.return_value = "KB"

        container = MagicMock()
        container.token_usage = TokenCounter()
        container.llm.complete.return_value = LLMResponse(
            content="VALID",
            input_tokens=10,
            output_tokens=5,
            model="test"
        )
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        mock_get_container.return_value = container

        drafter = DrafterAgent()
        critic = CriticAgent()

        result = process_single_email(drafter, critic, 1, "", "")

        assert result is not None
        assert result.email_content == ""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_process_unicode_email_content(self, mock_kb, mock_get_container):
        """Pipeline avec contenu Unicode."""
        from app.agents import DrafterAgent, CriticAgent, process_single_email, TokenCounter

        mock_kb.return_value = "KB"

        container = MagicMock()
        container.token_usage = TokenCounter()
        container.llm.complete.side_effect = [
            LLMResponse(content="Réponse 日本語", input_tokens=100, output_tokens=50, model="test"),
            LLMResponse(content="VALID", input_tokens=100, output_tokens=10, model="test")
        ]
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        mock_get_container.return_value = container

        drafter = DrafterAgent()
        critic = CriticAgent()

        result = process_single_email(
            drafter, critic, 1,
            "Contenu avec 你好 émojis 🎉",
            ""
        )

        assert "日本語" in result.draft_final


# ============================================================================
# TESTS - PROCESSED EMAILS TRACKER (Infrastructure)
# ============================================================================

class TestProcessedEmailsTrackerEdgeCases:
    """Tests edge cases pour JsonProcessedEmailsTracker (Clean Architecture adapter)."""

    def test_tracker_empty_file(self, tmp_path):
        """Tracker avec fichier vide."""
        from app.infrastructure.adapters.processed_emails_adapter import JsonProcessedEmailsTracker

        filepath = tmp_path / "empty.json"
        filepath.write_text("")

        # Doit gérer le fichier vide sans crash
        tracker = JsonProcessedEmailsTracker(filepath=filepath)
        assert tracker.count() == 0

    def test_tracker_invalid_json(self, tmp_path):
        """Tracker avec JSON invalide."""
        from app.infrastructure.adapters.processed_emails_adapter import JsonProcessedEmailsTracker

        filepath = tmp_path / "invalid.json"
        filepath.write_text("not valid json {")

        # Doit gérer le JSON invalide sans crash
        tracker = JsonProcessedEmailsTracker(filepath=filepath)
        assert tracker.count() == 0

    def test_tracker_missing_processed_ids_key(self, tmp_path):
        """Tracker avec JSON valide mais sans clé processed_ids."""
        from app.infrastructure.adapters.processed_emails_adapter import JsonProcessedEmailsTracker

        filepath = tmp_path / "missing_key.json"
        filepath.write_text('{"other_key": "value"}')

        tracker = JsonProcessedEmailsTracker(filepath=filepath)
        assert tracker.count() == 0

    def test_tracker_is_processed_empty_id(self, tmp_path):
        """is_processed avec ID vide."""
        from app.infrastructure.adapters.processed_emails_adapter import JsonProcessedEmailsTracker

        filepath = tmp_path / "test.json"
        tracker = JsonProcessedEmailsTracker(filepath=filepath)

        # ID vide n'est pas dans les traités
        assert tracker.is_processed("") is False

    def test_tracker_mark_processed_multiple_times(self, tmp_path):
        """Marquer le même email plusieurs fois ne duplique pas."""
        from app.infrastructure.adapters.processed_emails_adapter import JsonProcessedEmailsTracker

        filepath = tmp_path / "test.json"
        tracker = JsonProcessedEmailsTracker(filepath=filepath)

        tracker.mark_processed("email-001")
        tracker.mark_processed("email-001")
        tracker.mark_processed("email-001")

        assert tracker.count() == 1

    def test_tracker_persistence(self, tmp_path):
        """Les données persistent après rechargement."""
        from app.infrastructure.adapters.processed_emails_adapter import JsonProcessedEmailsTracker

        filepath = tmp_path / "persist.json"

        # Premier tracker
        tracker1 = JsonProcessedEmailsTracker(filepath=filepath)
        tracker1.mark_processed("email-001")
        tracker1.mark_processed("email-002")

        # Nouveau tracker charge les données
        tracker2 = JsonProcessedEmailsTracker(filepath=filepath)
        assert tracker2.count() == 2
        assert tracker2.is_processed("email-001")
        assert tracker2.is_processed("email-002")


# ============================================================================
# TESTS - DAEMON RESULT TYPES (Clean Architecture: Use Case DTOs)
# ============================================================================

class TestDaemonResultTypes:
    """Tests pour les types de résultats du daemon."""

    def test_cleaning_result_immutable(self):
        """CleaningResult est immutable (frozen dataclass)."""
        from app.daemon import CleaningResult

        result = CleaningResult(
            email=StandardEmail(id="test", sender="test@test.com"),
            metadata={"key": "value"},
            should_skip=False
        )

        with pytest.raises(AttributeError):
            result.should_skip = True

    def test_classification_result_with_skip_reason(self):
        """ClassificationResult avec raison de skip."""
        from app.daemon import ClassificationResult

        result = ClassificationResult(
            category="SPAM",
            priority_score=0,
            should_skip=True,
            skip_reason="low_priority:SPAM"
        )

        assert result.should_skip is True
        assert "SPAM" in result.skip_reason

    def test_draft_generation_result(self):
        """DraftGenerationResult contient toutes les versions."""
        from app.daemon import DraftGenerationResult

        result = DraftGenerationResult(
            draft_v1="Version 1",
            critique="REJET: Ton incorrect",
            final_draft="Version 2 corrigée",
            status="V2"
        )

        assert result.draft_v1 != result.final_draft
        assert result.status == "V2"


# ============================================================================
# TESTS - EMAIL DAEMON EDGE CASES (Infrastructure / Framework)
# ============================================================================

class TestEmailDaemonEdgeCases:
    """Tests edge cases pour EmailDaemon."""

    @pytest.fixture
    def mock_daemon_dependencies(self):
        """Dépendances mockées pour le daemon."""
        from tests.conftest import MockEmailProvider

        provider = MockEmailProvider()
        drafter = MagicMock()
        drafter.draft.return_value = "Draft response"
        drafter.revise.return_value = "Revised response"

        critic = MagicMock()
        critic.evaluate.return_value = "VALID"
        critic.is_valid.return_value = True

        return {
            "provider": provider,
            "drafter": drafter,
            "critic": critic,
        }

    def test_daemon_format_email_empty_sender_name(self):
        """_format_email_for_agent avec sender_name vide."""
        from app.daemon import EmailDaemon

        email = StandardEmail(
            id="test-001",
            sender="test@example.com",
            sender_name=None,
            subject="Test Subject",
            body="Test body"
        )

        with patch("app.daemon.get_email_provider"):
            with patch("app.daemon.get_container"):
                daemon = EmailDaemon.__new__(EmailDaemon)
                daemon.provider = MagicMock()

                result = daemon._format_email_for_agent(email)

                assert "test@example.com" in result
                assert "Test Subject" in result

    def test_daemon_generate_reply_subject_already_re(self):
        """_generate_reply_subject ne double pas le Re:."""
        from app.daemon import EmailDaemon

        with patch("app.daemon.get_email_provider"):
            with patch("app.daemon.get_container"):
                daemon = EmailDaemon.__new__(EmailDaemon)

                result = daemon._generate_reply_subject("Re: Original Subject")
                assert result == "Re: Original Subject"

                result = daemon._generate_reply_subject("RE: Original Subject")
                assert result == "RE: Original Subject"

    def test_daemon_generate_reply_subject_adds_re(self):
        """_generate_reply_subject ajoute Re: si absent."""
        from app.daemon import EmailDaemon

        with patch("app.daemon.get_email_provider"):
            with patch("app.daemon.get_container"):
                daemon = EmailDaemon.__new__(EmailDaemon)

                result = daemon._generate_reply_subject("Original Subject")
                assert result == "Re: Original Subject"


# ============================================================================
# TESTS - SEND EMAIL CONVENIENCE METHOD (Interface Adapters)
# ============================================================================

class TestSendEmailConvenience:
    """Tests pour la méthode send_email (combine create + send)."""

    def test_send_email_success(self, mock_provider):
        """send_email réussit quand create_draft et send_draft réussissent."""
        result = mock_provider.send_email(
            to=["recipient@example.com"],
            subject="Test Subject",
            body="Test body content"
        )

        assert result is True

    def test_send_email_with_all_options(self, mock_provider):
        """send_email avec toutes les options."""
        result = mock_provider.send_email(
            to=["main@example.com", "other@example.com"],
            subject="Test",
            body="Body",
            reply_to_id="original-msg-123",
            cc=["cc1@example.com", "cc2@example.com"],
            is_html=True
        )

        assert result is True

    def test_send_email_create_draft_fails(self):
        """send_email retourne False si create_draft échoue."""
        from tests.conftest import MockEmailProvider

        class FailingCreateDraftProvider(MockEmailProvider):
            def create_draft(self, *args, **kwargs):
                return None

        provider = FailingCreateDraftProvider()
        result = provider.send_email(
            to=["test@test.com"],
            subject="Test",
            body="Body"
        )

        assert result is False

    def test_send_email_send_draft_fails(self):
        """send_email retourne False si send_draft échoue."""
        from tests.conftest import MockEmailProvider

        class FailingSendDraftProvider(MockEmailProvider):
            def send_draft(self, draft_id):
                return False

        provider = FailingSendDraftProvider()
        result = provider.send_email(
            to=["test@test.com"],
            subject="Test",
            body="Body"
        )

        assert result is False


# ============================================================================
# TESTS - STANDARD EMAIL DATACLASS EDGE CASES (Entities)
# ============================================================================

class TestStandardEmailDataclass:
    """Tests pour les comportements du dataclass StandardEmail."""

    def test_email_equality(self):
        """Deux emails avec mêmes valeurs sont égaux."""
        email1 = StandardEmail(id="same-id", sender="same@test.com")
        email2 = StandardEmail(id="same-id", sender="same@test.com")

        assert email1 == email2

    def test_email_inequality_different_id(self):
        """Emails avec IDs différents ne sont pas égaux."""
        email1 = StandardEmail(id="id-1", sender="same@test.com")
        email2 = StandardEmail(id="id-2", sender="same@test.com")

        assert email1 != email2

    def test_email_default_values(self):
        """Vérifier les valeurs par défaut."""
        email = StandardEmail(id="test", sender="test@test.com")

        assert email.sender_name is None
        assert email.to == []
        assert email.cc == []
        assert email.subject == ""
        assert email.body == ""
        assert email.body_html is None
        assert email.received_at is None
        assert email.is_read is False
        assert email.has_attachments is False
        assert email.conversation_id is None
        assert email.provider_source == "unknown"
        assert email.raw_metadata == {}

    def test_email_raw_metadata_isolation(self):
        """raw_metadata est isolé entre instances."""
        email1 = StandardEmail(id="1", sender="a@a.com")
        email2 = StandardEmail(id="2", sender="b@b.com")

        email1.raw_metadata["key"] = "value"

        assert "key" not in email2.raw_metadata

    def test_email_with_datetime(self):
        """Email avec datetime valide."""
        now = datetime.now()
        email = StandardEmail(
            id="test",
            sender="test@test.com",
            received_at=now
        )

        assert email.received_at == now
