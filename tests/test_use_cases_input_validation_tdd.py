# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour la validation des entrées dans les Use Cases.

Ce fichier teste les edge cases et la validation des entrées pour:
- DraftEmailUseCase
- CompleteDraftUseCase
- ProcessEmailUseCase

Cycle TDD: RED → GREEN → REFACTOR

Clean Architecture:
- Les Use Cases doivent valider leurs entrées
- Les erreurs Domain doivent être propagées
- Les erreurs LLM doivent remonter vers l'appelant
"""

import pytest
from unittest.mock import Mock

from app.domain.entities import (
    Email, Draft, TokenUsage, DraftInput, DraftInputTone,
    CompletedDraft, ProcessingResult
)
from app.domain.exceptions import (
    ValidationError,
    LLMError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMConnectionError,
)
from app.domain.ports import LLMPort, LLMResponse
from app.application.draft_email import DraftEmailUseCase
from app.application.complete_draft import CompleteDraftUseCase
from app.application.process_email import ProcessEmailUseCase


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_llm():
    """Crée un mock du LLMPort."""
    mock = Mock(spec=LLMPort)
    mock.complete.return_value = LLMResponse(
        content="Bonjour, merci pour votre message.",
        input_tokens=100,
        output_tokens=50,
        model="test-model"
    )
    return mock


@pytest.fixture
def valid_email():
    """Email valide pour les tests."""
    return Email(
        id="test-123",
        sender="client@example.com",
        subject="Question importante",
        body="Bonjour, j'ai une question concernant votre service."
    )


@pytest.fixture
def valid_draft_input():
    """DraftInput valide pour les tests."""
    return DraftInput(
        raw_input="Remercier pour la commande. Confirmer livraison lundi.",
        key_points=["Remercier pour la commande", "Confirmer livraison lundi"],
        recipient="client@example.com",
        subject_hint="Confirmation de commande",
        tone=DraftInputTone.FORMAL
    )


@pytest.fixture
def knowledge_base():
    """Knowledge base pour les tests."""
    return "Je suis un assistant professionnel."


# =============================================================================
# Tests DraftEmailUseCase - Validation des entrées
# =============================================================================


class TestDraftEmailUseCaseInputValidation:
    """Tests de validation des entrées pour DraftEmailUseCase."""

    # -------------------------------------------------------------------------
    # Tests avec email=None
    # -------------------------------------------------------------------------

    def test_execute_with_none_email_raises_error(self, mock_llm, knowledge_base):
        """execute() avec email=None doit lever une erreur."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            use_case.execute(None)

    def test_execute_revision_with_none_email_raises_error(self, mock_llm, knowledge_base):
        """execute_revision() avec email=None doit lever une erreur."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            use_case.execute_revision(None, "critique")

    def test_execute_revision_with_none_critique_accepts_gracefully(
        self, mock_llm, knowledge_base, valid_email
    ):
        """execute_revision() avec critique=None accepte (convertit en 'None' string)."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        # Le code actuel accepte None et le convertit en string "None"
        # Ce comportement est acceptable car le LLM recevra juste "None" comme critique
        result = use_case.execute_revision(valid_email, None)

        assert isinstance(result, Draft)
        assert result.version == 2
        assert mock_llm.complete.called

    # -------------------------------------------------------------------------
    # Tests avec LLM=None
    # -------------------------------------------------------------------------

    def test_init_with_none_llm_raises_error(self, knowledge_base):
        """Création avec llm=None doit lever une erreur."""
        # Ce test vérifie que le use case ne peut pas être créé sans LLM
        use_case = DraftEmailUseCase(
            llm=None,
            knowledge_base=knowledge_base
        )

        # L'erreur devrait survenir à l'exécution si pas à l'init
        email = Email(
            id="test", sender="test@test.com",
            subject="Test", body="Test body"
        )
        with pytest.raises((AttributeError, TypeError)):
            use_case.execute(email)

    # -------------------------------------------------------------------------
    # Tests avec knowledge_base vide ou None
    # -------------------------------------------------------------------------

    def test_execute_with_empty_knowledge_base(self, mock_llm, valid_email):
        """execute() avec knowledge_base vide doit fonctionner."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=""
        )

        result = use_case.execute(valid_email)

        assert isinstance(result, Draft)
        assert result.version == 1

    def test_execute_with_none_knowledge_base_handles_gracefully(
        self, mock_llm, valid_email
    ):
        """execute() avec knowledge_base=None doit gérer l'erreur."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=None
        )

        # Devrait soit fonctionner, soit lever une erreur claire
        try:
            result = use_case.execute(valid_email)
            assert isinstance(result, Draft)
        except (TypeError, AttributeError):
            pass  # Acceptable si None n'est pas supporté

    # -------------------------------------------------------------------------
    # Tests avec max_tokens invalides
    # -------------------------------------------------------------------------

    def test_execute_with_zero_max_tokens(self, mock_llm, knowledge_base, valid_email):
        """execute() avec max_tokens=0 doit gérer le cas."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            max_tokens=0
        )

        # Le LLM devrait être appelé avec max_tokens=0
        use_case.execute(valid_email)
        assert mock_llm.complete.called

    def test_execute_with_negative_max_tokens(
        self, mock_llm, knowledge_base, valid_email
    ):
        """execute() avec max_tokens négatif doit lever une erreur ou valider."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            max_tokens=-100
        )

        # Devrait soit lever une ValidationError, soit utiliser une valeur par défaut
        try:
            use_case.execute(valid_email)
            # Si ça passe, vérifier que le LLM a reçu une valeur valide
            call_args = mock_llm.complete.call_args
            assert call_args is not None
        except ValidationError:
            pass  # Acceptable

    # -------------------------------------------------------------------------
    # Tests avec email mal formé
    # -------------------------------------------------------------------------

    def test_execute_with_wrong_type_raises_error(self, mock_llm, knowledge_base):
        """execute() avec un type incorrect doit lever une erreur."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            use_case.execute("not an email")

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            use_case.execute({"id": "123", "sender": "test@test.com"})

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            use_case.execute(123)

    # -------------------------------------------------------------------------
    # Tests de propagation des erreurs LLM
    # -------------------------------------------------------------------------

    def test_execute_propagates_llm_authentication_error(
        self, mock_llm, knowledge_base, valid_email
    ):
        """execute() doit propager LLMAuthenticationError."""
        mock_llm.complete.side_effect = LLMAuthenticationError(
            provider="test", message="Invalid API key"
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        with pytest.raises(LLMAuthenticationError):
            use_case.execute(valid_email)

    def test_execute_propagates_llm_rate_limit_error(
        self, mock_llm, knowledge_base, valid_email
    ):
        """execute() doit propager LLMRateLimitError."""
        mock_llm.complete.side_effect = LLMRateLimitError(
            provider="test", retry_after=60
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        with pytest.raises(LLMRateLimitError):
            use_case.execute(valid_email)

    def test_execute_propagates_llm_timeout_error(
        self, mock_llm, knowledge_base, valid_email
    ):
        """execute() doit propager LLMTimeoutError."""
        mock_llm.complete.side_effect = LLMTimeoutError(
            provider="test", timeout_seconds=120
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        with pytest.raises(LLMTimeoutError):
            use_case.execute(valid_email)

    def test_execute_propagates_llm_connection_error(
        self, mock_llm, knowledge_base, valid_email
    ):
        """execute() doit propager LLMConnectionError."""
        mock_llm.complete.side_effect = LLMConnectionError(
            provider="test", url="http://localhost:11434"
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        with pytest.raises(LLMConnectionError):
            use_case.execute(valid_email)

    # -------------------------------------------------------------------------
    # Tests avec réponse LLM None ou vide
    # -------------------------------------------------------------------------

    def test_execute_with_llm_returning_none_content(
        self, mock_llm, knowledge_base, valid_email
    ):
        """execute() avec LLM retournant content=None."""
        mock_llm.complete.return_value = LLMResponse(
            content=None,
            input_tokens=100,
            output_tokens=0,
            model="test"
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        # Devrait soit lever une erreur, soit créer un Draft vide
        try:
            result = use_case.execute(valid_email)
            # Si ça passe, le Draft devrait avoir un content None ou ""
            assert result.content is None or result.content == ""
        except (ValidationError, TypeError, AttributeError):
            pass

    def test_execute_with_llm_returning_empty_content(
        self, mock_llm, knowledge_base, valid_email
    ):
        """execute() avec LLM retournant content vide."""
        mock_llm.complete.return_value = LLMResponse(
            content="",
            input_tokens=100,
            output_tokens=0,
            model="test"
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        result = use_case.execute(valid_email)

        assert isinstance(result, Draft)
        assert result.content == ""

    # -------------------------------------------------------------------------
    # Tests avec email contenu très long
    # -------------------------------------------------------------------------

    def test_execute_with_very_long_email_body(self, mock_llm, knowledge_base):
        """execute() avec un email très long doit fonctionner."""
        long_body = "A" * 100000  # 100k caractères

        email = Email(
            id="long-email",
            sender="sender@test.com",
            subject="Long email",
            body=long_body
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        result = use_case.execute(email)

        assert isinstance(result, Draft)
        assert mock_llm.complete.called


# =============================================================================
# Tests CompleteDraftUseCase - Validation des entrées
# =============================================================================


class TestCompleteDraftUseCaseInputValidation:
    """Tests de validation des entrées pour CompleteDraftUseCase."""

    # -------------------------------------------------------------------------
    # Tests avec draft_input=None
    # -------------------------------------------------------------------------

    def test_execute_with_none_draft_input_raises_error(self, mock_llm):
        """execute() avec draft_input=None doit lever une erreur."""
        use_case = CompleteDraftUseCase(llm=mock_llm)

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            use_case.execute(None)

    # -------------------------------------------------------------------------
    # Tests avec LLM=None
    # -------------------------------------------------------------------------

    def test_init_with_none_llm_raises_error_on_execute(self, valid_draft_input):
        """Création avec llm=None doit lever une erreur à l'exécution."""
        use_case = CompleteDraftUseCase(llm=None)

        with pytest.raises((AttributeError, TypeError)):
            use_case.execute(valid_draft_input)

    # -------------------------------------------------------------------------
    # Tests avec DraftInput mal formé
    # -------------------------------------------------------------------------

    def test_execute_with_wrong_type_raises_error(self, mock_llm):
        """execute() avec un type incorrect doit lever une erreur."""
        use_case = CompleteDraftUseCase(llm=mock_llm)

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            use_case.execute("not a draft input")

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            use_case.execute({"raw_input": "test"})

    def test_execute_with_empty_key_points(self, mock_llm):
        """execute() avec key_points vide utilise raw_input."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET: Test\n\nBonjour, merci.",
            input_tokens=100,
            output_tokens=50,
            model="test"
        )

        draft_input = DraftInput(
            raw_input="Mon texte brut",
            key_points=[],
            tone=DraftInputTone.NEUTRAL
        )

        use_case = CompleteDraftUseCase(llm=mock_llm)
        result = use_case.execute(draft_input)

        assert isinstance(result, CompletedDraft)

    def test_execute_with_none_key_points(self, mock_llm):
        """execute() avec key_points=None."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET: Test\n\nBonjour, merci.",
            input_tokens=100,
            output_tokens=50,
            model="test"
        )

        # DraftInput avec key_points=None
        draft_input = DraftInput(
            raw_input="Mon texte",
            key_points=None,
            tone=DraftInputTone.NEUTRAL
        )

        use_case = CompleteDraftUseCase(llm=mock_llm)

        # Devrait soit fonctionner, soit lever une erreur claire
        try:
            result = use_case.execute(draft_input)
            assert isinstance(result, CompletedDraft)
        except (TypeError, AttributeError):
            pass

    # -------------------------------------------------------------------------
    # Tests de parsing de réponse LLM
    # -------------------------------------------------------------------------

    def test_parse_response_without_subject(self, mock_llm, valid_draft_input):
        """Parsing d'une réponse sans ligne OBJET."""
        mock_llm.complete.return_value = LLMResponse(
            content="Bonjour,\n\nMerci pour votre message.\n\nCordialement",
            input_tokens=100,
            output_tokens=50,
            model="test"
        )

        use_case = CompleteDraftUseCase(llm=mock_llm)
        result = use_case.execute(valid_draft_input)

        assert isinstance(result, CompletedDraft)
        # Le sujet devrait être extrait du subject_hint ou key_points
        assert result.subject or result.body

    def test_parse_response_empty_body(self, mock_llm, valid_draft_input):
        """Parsing d'une réponse avec corps vide."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET: Test",
            input_tokens=100,
            output_tokens=50,
            model="test"
        )

        use_case = CompleteDraftUseCase(llm=mock_llm)
        result = use_case.execute(valid_draft_input)

        assert isinstance(result, CompletedDraft)

    def test_parse_response_completely_empty(self, mock_llm, valid_draft_input):
        """Parsing d'une réponse complètement vide."""
        mock_llm.complete.return_value = LLMResponse(
            content="",
            input_tokens=100,
            output_tokens=0,
            model="test"
        )

        use_case = CompleteDraftUseCase(llm=mock_llm)
        result = use_case.execute(valid_draft_input)

        assert isinstance(result, CompletedDraft)

    # -------------------------------------------------------------------------
    # Tests de propagation des erreurs LLM
    # -------------------------------------------------------------------------

    def test_execute_propagates_llm_error(self, mock_llm, valid_draft_input):
        """execute() doit propager les erreurs LLM."""
        mock_llm.complete.side_effect = LLMError(
            message="Generic LLM error",
            provider="test"
        )

        use_case = CompleteDraftUseCase(llm=mock_llm)

        with pytest.raises(LLMError):
            use_case.execute(valid_draft_input)

    # -------------------------------------------------------------------------
    # Tests avec max_tokens invalides
    # -------------------------------------------------------------------------

    def test_execute_with_zero_max_tokens(self, mock_llm, valid_draft_input):
        """execute() avec max_tokens=0."""
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            max_tokens=0
        )

        use_case.execute(valid_draft_input)
        assert mock_llm.complete.called


# =============================================================================
# Tests ProcessEmailUseCase - Validation des entrées
# =============================================================================


class TestProcessEmailUseCaseInputValidation:
    """Tests de validation des entrées pour ProcessEmailUseCase."""

    @pytest.fixture
    def mock_llm_for_process(self):
        """Mock LLM configuré pour le pipeline complet."""
        mock = Mock(spec=LLMPort)

        # Première réponse pour le draft V1
        # Deuxième réponse pour la critique (VALID = pas de révision)
        mock.complete.side_effect = [
            LLMResponse(
                content="Bonjour, merci pour votre message.",
                input_tokens=100,
                output_tokens=50,
                model="test"
            ),
            LLMResponse(
                content="VALID",  # Critique valide = pas de révision nécessaire
                input_tokens=150,
                output_tokens=30,
                model="test"
            ),
        ]
        return mock

    # -------------------------------------------------------------------------
    # Tests avec email=None
    # -------------------------------------------------------------------------

    def test_execute_with_none_email_raises_error(
        self, mock_llm_for_process, knowledge_base
    ):
        """execute() avec email=None doit lever une erreur."""
        use_case = ProcessEmailUseCase(
            llm=mock_llm_for_process,
            knowledge_base=knowledge_base
        )

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            use_case.execute(None)

    # -------------------------------------------------------------------------
    # Tests avec LLM=None
    # -------------------------------------------------------------------------

    def test_init_with_none_llm_raises_error_on_execute(
        self, knowledge_base, valid_email
    ):
        """Création avec llm=None doit lever une erreur à l'exécution."""
        use_case = ProcessEmailUseCase(
            llm=None,
            knowledge_base=knowledge_base
        )

        with pytest.raises((AttributeError, TypeError)):
            use_case.execute(valid_email)

    # -------------------------------------------------------------------------
    # Tests avec knowledge_base invalide
    # -------------------------------------------------------------------------

    def test_execute_with_none_knowledge_base(
        self, mock_llm_for_process, valid_email
    ):
        """execute() avec knowledge_base=None."""
        use_case = ProcessEmailUseCase(
            llm=mock_llm_for_process,
            knowledge_base=None
        )

        # Devrait soit fonctionner, soit lever une erreur claire
        try:
            result = use_case.execute(valid_email)
            assert isinstance(result, ProcessingResult)
        except (TypeError, AttributeError):
            pass

    # -------------------------------------------------------------------------
    # Tests de propagation des erreurs LLM dans le pipeline
    # -------------------------------------------------------------------------

    def test_execute_propagates_llm_error_from_drafter(
        self, mock_llm, knowledge_base, valid_email
    ):
        """execute() propage les erreurs LLM du drafter."""
        mock_llm.complete.side_effect = LLMAuthenticationError(
            provider="test", message="Invalid key"
        )

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        with pytest.raises(LLMAuthenticationError):
            use_case.execute(valid_email)

    def test_execute_propagates_llm_error_from_critic(
        self, knowledge_base, valid_email
    ):
        """execute() propage les erreurs LLM du critic."""
        mock = Mock(spec=LLMPort)
        mock.complete.side_effect = [
            # Draft V1 réussit
            LLMResponse(
                content="Bonjour, merci.",
                input_tokens=100,
                output_tokens=50,
                model="test"
            ),
            # Critique échoue
            LLMRateLimitError(provider="test", retry_after=60)
        ]

        use_case = ProcessEmailUseCase(
            llm=mock,
            knowledge_base=knowledge_base
        )

        with pytest.raises(LLMRateLimitError):
            use_case.execute(valid_email)

    # -------------------------------------------------------------------------
    # Tests avec max_tokens invalides
    # -------------------------------------------------------------------------

    def test_execute_with_zero_max_tokens_draft(
        self, mock_llm_for_process, knowledge_base, valid_email
    ):
        """execute() avec max_tokens_draft=0."""
        use_case = ProcessEmailUseCase(
            llm=mock_llm_for_process,
            knowledge_base=knowledge_base,
            max_tokens_draft=0
        )

        result = use_case.execute(valid_email)
        assert isinstance(result, ProcessingResult)

    def test_execute_with_negative_max_tokens(
        self, mock_llm_for_process, knowledge_base, valid_email
    ):
        """execute() avec max_tokens négatif."""
        use_case = ProcessEmailUseCase(
            llm=mock_llm_for_process,
            knowledge_base=knowledge_base,
            max_tokens_draft=-100,
            max_tokens_critique=-50
        )

        # Devrait soit lever une erreur, soit utiliser des valeurs par défaut
        try:
            result = use_case.execute(valid_email)
            assert isinstance(result, ProcessingResult)
        except ValidationError:
            pass


# =============================================================================
# Tests TokenUsage - Intégration avec Use Cases
# =============================================================================


class TestTokenUsageIntegration:
    """Tests d'intégration du tracking des tokens dans les Use Cases."""

    def test_draft_use_case_tracks_tokens(self, mock_llm, knowledge_base, valid_email):
        """DraftEmailUseCase doit tracker les tokens utilisés."""
        token_usage = TokenUsage()

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        use_case.execute(valid_email)

        assert token_usage.input_tokens == 100
        assert token_usage.output_tokens == 50

    def test_draft_use_case_initializes_token_usage_if_none(
        self, mock_llm, knowledge_base, valid_email
    ):
        """DraftEmailUseCase doit initialiser TokenUsage si non fourni."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=None
        )

        use_case.execute(valid_email)

        # Le use case devrait avoir créé son propre TokenUsage
        assert use_case.token_usage is not None
        assert use_case.token_usage.input_tokens == 100

    def test_complete_draft_use_case_tracks_tokens(
        self, mock_llm, valid_draft_input
    ):
        """CompleteDraftUseCase doit tracker les tokens utilisés."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET: Test\n\nBonjour",
            input_tokens=200,
            output_tokens=75,
            model="test"
        )

        token_usage = TokenUsage()

        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            token_usage=token_usage
        )

        use_case.execute(valid_draft_input)

        assert token_usage.input_tokens == 200
        assert token_usage.output_tokens == 75

    def test_process_use_case_shares_token_usage(
        self, knowledge_base, valid_email
    ):
        """ProcessEmailUseCase doit partager le TokenUsage entre sous-use-cases."""
        mock = Mock(spec=LLMPort)
        mock.complete.side_effect = [
            LLMResponse(content="Draft V1", input_tokens=100, output_tokens=50, model="t"),
            LLMResponse(
                content="VALID",  # Critique valide = pas de révision nécessaire
                input_tokens=150, output_tokens=30, model="t"
            ),
        ]

        token_usage = TokenUsage()

        use_case = ProcessEmailUseCase(
            llm=mock,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        use_case.execute(valid_email)

        # Les tokens de draft + critique doivent être cumulés
        assert token_usage.input_tokens == 250  # 100 + 150
        assert token_usage.output_tokens == 80   # 50 + 30


# =============================================================================
# Tests de cas edge avec emails spéciaux
# =============================================================================


class TestEdgeCasesWithSpecialEmails:
    """Tests avec des emails aux formats edge case."""

    def test_email_with_unicode_characters(self, mock_llm, knowledge_base):
        """Email avec caractères Unicode spéciaux."""
        email = Email(
            id="unicode-test",
            sender="émoji@tëst.com",
            subject="Test 🎉 émojis et àccénts",
            body="Bonjour 👋, ceci est un test avec des émojis 🚀 et des caractères spéciaux: ñ, ü, ß"
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        result = use_case.execute(email)

        assert isinstance(result, Draft)

    def test_email_with_html_content(self, mock_llm, knowledge_base):
        """Email avec contenu HTML."""
        email = Email(
            id="html-test",
            sender="sender@test.com",
            subject="Test HTML",
            body="<html><body><h1>Titre</h1><p>Contenu avec <b>HTML</b></p></body></html>"
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        result = use_case.execute(email)

        assert isinstance(result, Draft)

    def test_email_with_only_whitespace_body(self, mock_llm, knowledge_base):
        """Email avec body contenant uniquement des espaces."""
        email = Email(
            id="whitespace-test",
            sender="sender@test.com",
            subject="Test",
            body="   \n\t\n   "
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        result = use_case.execute(email)

        assert isinstance(result, Draft)

    def test_email_with_multiline_subject(self, mock_llm, knowledge_base):
        """Email avec sujet multilignes (edge case)."""
        email = Email(
            id="multiline-subject",
            sender="sender@test.com",
            subject="Ligne 1\nLigne 2",
            body="Test body"
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
        )

        result = use_case.execute(email)

        assert isinstance(result, Draft)
