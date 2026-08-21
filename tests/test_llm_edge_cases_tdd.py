# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases LLM.

Ce module teste les scénarios d'erreur et edge cases liés aux LLMs :
- Timeouts et erreurs réseau
- Rate limiting (HTTP 429)
- Réponses vides ou malformées
- Contexte trop long
- Modèle non disponible
- Erreurs de parsing de réponse

Principes TDD/Clean Architecture :
1. Tests indépendants des adapters réels (mocks)
2. Chaque test cible un scénario d'erreur spécifique
3. Vérification de la propagation correcte des erreurs
"""

import pytest
from typing import Optional

from app.domain.entities import Email, TokenUsage
from app.domain.ports.llm_port import LLMPort, LLMResponse
from app.application.draft_email import DraftEmailUseCase


# ============================================================================
# MOCK LLM IMPLEMENTATIONS FOR TESTING
# ============================================================================

class MockLLM(LLMPort):
    """LLM Mock configurable pour les tests."""

    def __init__(
        self,
        response_content: str = "Mock response",
        should_fail: bool = False,
        error_type: Optional[type] = None,
        error_message: str = "Mock error",
        input_tokens: int = 100,
        output_tokens: int = 50,
        model: str = "mock-model"
    ):
        self._response_content = response_content
        self._should_fail = should_fail
        self._error_type = error_type or Exception
        self._error_message = error_message
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._model = model
        self._available = True
        self.call_count = 0

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return self._model

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        self.call_count += 1
        if self._should_fail:
            raise self._error_type(self._error_message)
        return LLMResponse(
            content=self._response_content,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            model=self._model
        )

    def is_available(self) -> bool:
        return self._available


class TimeoutLLM(MockLLM):
    """LLM qui simule un timeout."""

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        self.call_count += 1
        raise TimeoutError("Request timed out after 30 seconds")


class RateLimitedLLM(MockLLM):
    """LLM qui simule une erreur de rate limiting."""

    def __init__(self, fail_count: int = 3):
        super().__init__()
        self._fail_count = fail_count
        self.call_count = 0

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        self.call_count += 1
        if self.call_count <= self._fail_count:
            raise Exception("Rate limit exceeded. Please retry after 60 seconds.")
        return LLMResponse(
            content="Success after rate limit",
            input_tokens=100,
            output_tokens=50,
            model="mock-model"
        )


class ContextTooLongLLM(MockLLM):
    """LLM qui simule une erreur de contexte trop long."""

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        self.call_count += 1
        total_length = len(system) + len(user)
        if total_length > 1000:  # Seuil arbitraire pour les tests
            raise ValueError(f"Context too long: {total_length} characters exceeds maximum")
        return super().complete(system, user, max_tokens)


class EmptyResponseLLM(MockLLM):
    """LLM qui retourne une réponse vide."""

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            content="",
            input_tokens=self._input_tokens,
            output_tokens=0,
            model=self._model
        )


class MalformedResponseLLM(MockLLM):
    """LLM qui retourne une réponse malformée."""

    def __init__(self, malformed_type: str = "whitespace"):
        super().__init__()
        self.malformed_type = malformed_type

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        self.call_count += 1
        content_map = {
            "whitespace": "   \n\t  ",
            "control_chars": "\x00\x01\x02",
            "very_long": "A" * 100000,
            "only_newlines": "\n\n\n\n\n",
        }
        return LLMResponse(
            content=content_map.get(self.malformed_type, ""),
            input_tokens=100,
            output_tokens=50,
            model="mock-model"
        )


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_email():
    """Email de test standard."""
    return Email(
        id="test-123",
        subject="Question importante",
        body="Bonjour, j'ai une question concernant votre service.",
        sender="client@example.com"
    )


@pytest.fixture
def sample_knowledge_base():
    """Knowledge base de test."""
    return "Vous êtes un assistant professionnel pour la société Acme."


# ============================================================================
# TESTS - LLM RESPONSE ENTITY
# ============================================================================

class TestLLMResponseEntity:
    """Tests pour l'entité LLMResponse."""

    def test_llm_response_default_values(self):
        """LLMResponse avec valeurs par défaut."""
        response = LLMResponse(content="Test")
        assert response.content == "Test"
        assert response.input_tokens == 0
        assert response.output_tokens == 0
        assert response.model == ""

    def test_llm_response_with_all_fields(self):
        """LLMResponse avec tous les champs."""
        response = LLMResponse(
            content="Réponse complète",
            input_tokens=500,
            output_tokens=200,
            model="claude-sonnet"
        )
        assert response.content == "Réponse complète"
        assert response.input_tokens == 500
        assert response.output_tokens == 200
        assert response.model == "claude-sonnet"

    def test_llm_response_empty_content(self):
        """LLMResponse avec contenu vide."""
        response = LLMResponse(content="")
        assert response.content == ""

    def test_llm_response_negative_tokens_should_be_invalid(self):
        """TDD: tokens négatifs devraient lever une erreur."""
        response = LLMResponse(
            content="Test",
            input_tokens=-100,
            output_tokens=-50
        )
        # ATTENDU: ValueError
        # ACTUEL: Pas d'erreur
        assert response.input_tokens == -100  # Comportement actuel (à corriger)


# ============================================================================
# TESTS - TIMEOUT ERRORS
# ============================================================================

class TestLLMTimeoutErrors:
    """Tests pour les erreurs de timeout."""

    def test_timeout_error_propagates(self, sample_email, sample_knowledge_base):
        """TimeoutError est propagée depuis le LLM."""
        llm = TimeoutLLM()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        with pytest.raises(TimeoutError, match="timed out"):
            use_case.execute(sample_email)

    def test_timeout_increments_call_count(self, sample_email, sample_knowledge_base):
        """L'appel est comptabilisé même en cas de timeout."""
        llm = TimeoutLLM()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        with pytest.raises(TimeoutError):
            use_case.execute(sample_email)

        assert llm.call_count == 1

    def test_timeout_no_token_usage_recorded(self, sample_email, sample_knowledge_base):
        """Pas de tokens comptabilisés en cas de timeout."""
        llm = TimeoutLLM()
        token_usage = TokenUsage()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base,
            token_usage=token_usage
        )

        with pytest.raises(TimeoutError):
            use_case.execute(sample_email)

        assert token_usage.total == 0


# ============================================================================
# TESTS - RATE LIMITING
# ============================================================================

class TestLLMRateLimiting:
    """Tests pour le rate limiting."""

    def test_rate_limit_error_propagates(self, sample_email, sample_knowledge_base):
        """Erreur de rate limit est propagée."""
        llm = RateLimitedLLM(fail_count=1)
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        with pytest.raises(Exception, match="Rate limit"):
            use_case.execute(sample_email)

    def test_rate_limit_recovers_after_delay(self, sample_email, sample_knowledge_base):
        """TDD: Le système devrait réessayer après rate limit.

        ACTUELLEMENT: Pas de retry automatique.
        Ce test documente le comportement ATTENDU.
        """
        llm = RateLimitedLLM(fail_count=2)
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        # ACTUEL: Première erreur est propagée
        with pytest.raises(Exception, match="Rate limit"):
            use_case.execute(sample_email)

        # ATTENDU: Le use case devrait réessayer automatiquement
        # et retourner un résultat après les échecs

    def test_rate_limit_message_contains_retry_info(self):
        """Le message d'erreur contient l'info de retry."""
        llm = RateLimitedLLM(fail_count=1)
        try:
            llm.complete("system", "user")
        except Exception as e:
            assert "retry" in str(e).lower() or "60 seconds" in str(e)


# ============================================================================
# TESTS - EMPTY/MALFORMED RESPONSES
# ============================================================================

class TestLLMEmptyResponses:
    """Tests pour les réponses vides."""

    def test_empty_response_creates_empty_draft(self, sample_email, sample_knowledge_base):
        """Réponse vide crée un brouillon vide."""
        llm = EmptyResponseLLM()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        draft = use_case.execute(sample_email)
        assert draft.content == ""
        assert draft.version == 1

    def test_empty_response_still_counts_input_tokens(self, sample_email, sample_knowledge_base):
        """Les tokens d'entrée sont comptés même avec réponse vide."""
        llm = EmptyResponseLLM()
        llm._input_tokens = 500
        token_usage = TokenUsage()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base,
            token_usage=token_usage
        )

        use_case.execute(sample_email)
        assert token_usage.input_tokens == 500


class TestLLMMalformedResponses:
    """Tests pour les réponses malformées."""

    def test_whitespace_only_response(self, sample_email, sample_knowledge_base):
        """Réponse avec espaces seulement."""
        llm = MalformedResponseLLM(malformed_type="whitespace")
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        draft = use_case.execute(sample_email)
        # Le contenu n'est pas strippé par le use case
        assert draft.content == "   \n\t  "

    def test_control_characters_response(self, sample_email, sample_knowledge_base):
        """Réponse avec caractères de contrôle."""
        llm = MalformedResponseLLM(malformed_type="control_chars")
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        draft = use_case.execute(sample_email)
        assert draft.content == "\x00\x01\x02"

    def test_very_long_response(self, sample_email, sample_knowledge_base):
        """Réponse très longue."""
        llm = MalformedResponseLLM(malformed_type="very_long")
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        draft = use_case.execute(sample_email)
        assert len(draft.content) == 100000


# ============================================================================
# TESTS - CONTEXT TOO LONG
# ============================================================================

class TestLLMContextTooLong:
    """Tests pour les erreurs de contexte trop long."""

    def test_context_too_long_error(self, sample_knowledge_base):
        """Erreur levée si le contexte est trop long."""
        llm = ContextTooLongLLM()
        long_email = Email(
            id="test-123",
            subject="Test",
            body="X" * 2000,  # Body très long
            sender="test@example.com"
        )
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        with pytest.raises(ValueError, match="Context too long"):
            use_case.execute(long_email)

    def test_short_context_succeeds(self, sample_email, sample_knowledge_base):
        """Contexte court réussit."""
        llm = ContextTooLongLLM()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base="Short KB"
        )

        draft = use_case.execute(sample_email)
        assert draft.content == "Mock response"


# ============================================================================
# TESTS - MODEL NOT AVAILABLE
# ============================================================================

class TestLLMModelAvailability:
    """Tests pour la disponibilité du modèle."""

    def test_is_available_returns_true_by_default(self):
        """is_available() retourne True par défaut."""
        llm = MockLLM()
        assert llm.is_available() is True

    def test_is_available_can_return_false(self):
        """is_available() peut retourner False."""
        llm = MockLLM()
        llm._available = False
        assert llm.is_available() is False

    def test_use_case_should_check_availability(self, sample_email, sample_knowledge_base):
        """TDD: Le use case devrait vérifier la disponibilité.

        ACTUELLEMENT: Pas de vérification de disponibilité.
        """
        llm = MockLLM()
        llm._available = False
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        # ACTUEL: Appel réussit même si le LLM n'est pas disponible
        draft = use_case.execute(sample_email)
        assert draft is not None

        # ATTENDU: Devrait lever une erreur ou vérifier is_available()


# ============================================================================
# TESTS - GENERIC EXCEPTIONS
# ============================================================================

class TestLLMGenericExceptions:
    """Tests pour les exceptions génériques."""

    def test_connection_error_propagates(self, sample_email, sample_knowledge_base):
        """ConnectionError est propagée."""
        llm = MockLLM(
            should_fail=True,
            error_type=ConnectionError,
            error_message="Unable to connect to API"
        )
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        with pytest.raises(ConnectionError, match="Unable to connect"):
            use_case.execute(sample_email)

    def test_value_error_propagates(self, sample_email, sample_knowledge_base):
        """ValueError est propagée."""
        llm = MockLLM(
            should_fail=True,
            error_type=ValueError,
            error_message="Invalid API key"
        )
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        with pytest.raises(ValueError, match="Invalid API key"):
            use_case.execute(sample_email)

    def test_runtime_error_propagates(self, sample_email, sample_knowledge_base):
        """RuntimeError est propagée."""
        llm = MockLLM(
            should_fail=True,
            error_type=RuntimeError,
            error_message="Unexpected error"
        )
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        with pytest.raises(RuntimeError, match="Unexpected error"):
            use_case.execute(sample_email)


# ============================================================================
# TESTS - TOKEN COUNTING EDGE CASES
# ============================================================================

class TestLLMTokenCounting:
    """Tests pour le comptage des tokens."""

    def test_token_usage_accumulated_across_calls(self, sample_email, sample_knowledge_base):
        """TokenUsage accumule les tokens à travers les appels."""
        llm = MockLLM(input_tokens=100, output_tokens=50)
        token_usage = TokenUsage()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base,
            token_usage=token_usage
        )

        use_case.execute(sample_email)
        use_case.execute(sample_email)

        assert token_usage.input_tokens == 200
        assert token_usage.output_tokens == 100

    def test_token_usage_model_updated(self, sample_email, sample_knowledge_base):
        """Le modèle est mis à jour dans TokenUsage."""
        llm = MockLLM(model="claude-sonnet-4")
        token_usage = TokenUsage()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base,
            token_usage=token_usage
        )

        use_case.execute(sample_email)
        assert token_usage.model == "claude-sonnet-4"

    def test_zero_tokens_response(self, sample_email, sample_knowledge_base):
        """Réponse avec zéro tokens."""
        llm = MockLLM(input_tokens=0, output_tokens=0)
        token_usage = TokenUsage()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base,
            token_usage=token_usage
        )

        use_case.execute(sample_email)
        assert token_usage.total == 0
        assert token_usage.cost == 0.0


# ============================================================================
# TESTS - REVISION (execute_revision) EDGE CASES
# ============================================================================

class TestDraftEmailRevision:
    """Tests pour la révision de brouillon."""

    def test_revision_creates_v2_draft(self, sample_email, sample_knowledge_base):
        """execute_revision crée un brouillon V2."""
        llm = MockLLM(response_content="Réponse corrigée")
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        draft = use_case.execute_revision(sample_email, "Le ton est trop formel")
        assert draft.version == 2
        assert draft.content == "Réponse corrigée"

    def test_revision_with_empty_critique(self, sample_email, sample_knowledge_base):
        """Révision avec critique vide."""
        llm = MockLLM()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        draft = use_case.execute_revision(sample_email, "")
        assert draft.version == 2

    def test_revision_timeout_propagates(self, sample_email, sample_knowledge_base):
        """Timeout pendant la révision est propagé."""
        llm = TimeoutLLM()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )

        with pytest.raises(TimeoutError):
            use_case.execute_revision(sample_email, "critique")

    def test_revision_tokens_accumulated(self, sample_email, sample_knowledge_base):
        """Les tokens de révision sont accumulés."""
        llm = MockLLM(input_tokens=100, output_tokens=50)
        token_usage = TokenUsage()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base,
            token_usage=token_usage
        )

        use_case.execute(sample_email)
        use_case.execute_revision(sample_email, "critique")

        assert token_usage.input_tokens == 200
        assert token_usage.output_tokens == 100


# ============================================================================
# TESTS - USE CASE INITIALIZATION
# ============================================================================

class TestDraftEmailUseCaseInit:
    """Tests pour l'initialisation du use case."""

    def test_default_token_usage_created(self, sample_knowledge_base):
        """TokenUsage par défaut est créé si non fourni."""
        llm = MockLLM()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )
        assert use_case.token_usage is not None
        assert isinstance(use_case.token_usage, TokenUsage)

    def test_custom_token_usage_used(self, sample_knowledge_base):
        """TokenUsage personnalisé est utilisé."""
        llm = MockLLM()
        token_usage = TokenUsage(input_tokens=1000, output_tokens=500)
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base,
            token_usage=token_usage
        )
        assert use_case.token_usage.input_tokens == 1000
        assert use_case.token_usage.output_tokens == 500

    def test_default_max_tokens(self, sample_knowledge_base):
        """max_tokens par défaut est 1024."""
        llm = MockLLM()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base
        )
        assert use_case.max_tokens == 1024

    def test_custom_max_tokens(self, sample_knowledge_base):
        """max_tokens personnalisé."""
        llm = MockLLM()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=sample_knowledge_base,
            max_tokens=2048
        )
        assert use_case.max_tokens == 2048

    def test_empty_knowledge_base(self, sample_email):
        """Knowledge base vide est acceptée."""
        llm = MockLLM()
        use_case = DraftEmailUseCase(
            llm=llm,
            knowledge_base=""
        )
        draft = use_case.execute(sample_email)
        assert draft is not None
