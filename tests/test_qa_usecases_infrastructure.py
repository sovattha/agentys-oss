# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests QA - Use Cases et Infrastructure Edge Cases.

Ce module teste les edge cases critiques des use cases et de l'infrastructure :
1. DraftEmailUseCase - Génération de brouillons
2. CritiqueEmailUseCase - Évaluation des brouillons
3. ProcessEmailUseCase - Pipeline complet
4. CompleteDraftUseCase - Complétion de brouillons
5. Container - Injection de dépendances
6. LLM Adapters - Edge cases de connexion

pytest tests/test_qa_usecases_infrastructure.py -v
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.domain.entities import (
    Email,
    Draft,
    DraftStatus,
    TokenUsage,
    DraftInput,
    DraftInputTone,
)
from app.domain.ports import LLMPort, LLMResponse

from app.application import (
    DraftEmailUseCase,
    CritiqueEmailUseCase,
    ProcessEmailUseCase,
    CompleteDraftUseCase,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_llm():
    """LLM mocké."""
    mock = MagicMock(spec=LLMPort)
    mock.name = "mock-llm"
    mock.model = "mock-model"
    mock.complete.return_value = LLMResponse(
        content="Test response",
        input_tokens=100,
        output_tokens=50,
        model="mock-model"
    )
    return mock


@pytest.fixture
def token_usage():
    """Token usage tracker."""
    return TokenUsage()


@pytest.fixture
def sample_email():
    """Email de test."""
    return Email(
        id="test-123",
        subject="Question importante",
        body="Bonjour, j'ai une question concernant votre service.",
        sender="client@example.com"
    )


@pytest.fixture
def knowledge_base():
    """Knowledge base de test."""
    return """
    Règles de réponse :
    - Toujours être poli et professionnel
    - Répondre dans la langue de l'email
    - Ne pas promettre ce qu'on ne peut pas tenir
    """


# ============================================================================
# TESTS - DRAFT EMAIL USE CASE
# ============================================================================

class TestDraftEmailUseCaseEdgeCases:
    """Edge cases pour DraftEmailUseCase."""

    def test_execute_with_empty_knowledge_base(self, mock_llm, sample_email, token_usage):
        """Exécution avec knowledge base vide."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage
        )

        draft = use_case.execute(sample_email)

        assert draft is not None
        assert draft.version == 1
        # Le prompt système devrait quand même être construit
        call_args = mock_llm.complete.call_args
        assert call_args is not None

    def test_execute_with_unicode_knowledge_base(self, mock_llm, sample_email, token_usage):
        """Exécution avec knowledge base unicode."""
        unicode_kb = "Règles 日本語 العربية 中文 émojis 🎉"
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=unicode_kb,
            token_usage=token_usage
        )

        draft = use_case.execute(sample_email)

        assert draft is not None
        call_args = mock_llm.complete.call_args
        assert unicode_kb in call_args.kwargs.get("system", "")

    def test_execute_with_very_long_email(self, mock_llm, token_usage, knowledge_base):
        """Exécution avec email très long."""
        long_body = "A" * 100000
        email = Email(
            id="long-1",
            subject="Long Email",
            body=long_body,
            sender="test@test.com"
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        draft = use_case.execute(email)

        assert draft is not None
        # Le prompt devrait contenir le body complet
        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs.get("user", "")
        assert long_body in user_prompt

    def test_execute_revision_with_empty_critique(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Révision avec critique vide."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        draft = use_case.execute_revision(sample_email, critique="")

        assert draft is not None
        assert draft.version == 2

    def test_execute_tracks_token_usage(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Vérifie que l'usage de tokens est tracké."""
        mock_llm.complete.return_value = LLMResponse(
            content="Response",
            input_tokens=150,
            output_tokens=75,
            model="test-model"
        )

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        use_case.execute(sample_email)

        assert token_usage.input_tokens == 150
        assert token_usage.output_tokens == 75
        assert token_usage.model == "test-model"

    def test_execute_with_llm_exception(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Exécution quand le LLM lève une exception."""
        mock_llm.complete.side_effect = ConnectionError("API unreachable")

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        with pytest.raises(ConnectionError, match="API unreachable"):
            use_case.execute(sample_email)

    def test_execute_with_timeout_error(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Exécution avec timeout."""
        mock_llm.complete.side_effect = TimeoutError("Request timed out")

        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        with pytest.raises(TimeoutError):
            use_case.execute(sample_email)

    def test_execute_without_token_usage(self, mock_llm, sample_email, knowledge_base):
        """Exécution sans token_usage fourni (création automatique)."""
        use_case = DraftEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base
            # token_usage non fourni
        )

        draft = use_case.execute(sample_email)

        assert draft is not None
        # token_usage devrait avoir été créé automatiquement
        assert use_case.token_usage is not None


# ============================================================================
# TESTS - CRITIQUE EMAIL USE CASE
# ============================================================================

class TestCritiqueEmailUseCaseEdgeCases:
    """Edge cases pour CritiqueEmailUseCase."""

    def test_execute_returns_valid_critique(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Exécution avec réponse VALID."""
        mock_llm.complete.return_value = LLMResponse(
            content="VALID",
            input_tokens=100,
            output_tokens=5,
            model="test"
        )

        use_case = CritiqueEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        draft = Draft(content="Test draft", version=1)
        critique = use_case.execute(sample_email, draft)

        assert critique.is_valid is True
        assert critique.raw_response == "VALID"

    def test_execute_returns_rejet_critique(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Exécution avec réponse REJET."""
        mock_llm.complete.return_value = LLMResponse(
            content="REJET : Ton trop informel pour un client professionnel",
            input_tokens=100,
            output_tokens=20,
            model="test"
        )

        use_case = CritiqueEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        draft = Draft(content="Salut, ça va?", version=1)
        critique = use_case.execute(sample_email, draft)

        assert critique.is_valid is False
        assert "Ton trop informel" in critique.reason

    def test_execute_with_empty_draft(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Exécution avec draft vide."""
        use_case = CritiqueEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        draft = Draft(content="", version=1)
        critique = use_case.execute(sample_email, draft)

        # Ne devrait pas crasher
        assert critique is not None

    def test_execute_with_multiline_response(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Exécution avec réponse multi-lignes."""
        mock_llm.complete.return_value = LLMResponse(
            content="""VALID

Cette réponse est excellente car :
- Elle est professionnelle
- Elle respecte le ton
- Elle répond à la question""",
            input_tokens=100,
            output_tokens=30,
            model="test"
        )

        use_case = CritiqueEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        draft = Draft(content="Good draft", version=1)
        critique = use_case.execute(sample_email, draft)

        assert critique.is_valid is True


# ============================================================================
# TESTS - PROCESS EMAIL USE CASE
# ============================================================================

class TestProcessEmailUseCaseEdgeCases:
    """Edge cases pour ProcessEmailUseCase."""

    def test_execute_validated_v1(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Exécution avec validation V1 directe."""
        # Première réponse : draft V1
        # Deuxième réponse : VALID
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft V1 content", input_tokens=100, output_tokens=50, model="test"),
            LLMResponse(content="VALID", input_tokens=50, output_tokens=5, model="test"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        result = use_case.execute(sample_email)

        assert result.status == DraftStatus.VALIDATED_V1
        assert result.draft_v1.content == "Draft V1 content"
        assert result.draft_final.content == "Draft V1 content"
        assert result.was_corrected is False

    def test_execute_corrected_v2(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Exécution avec correction V2."""
        # Première réponse : draft V1
        # Deuxième réponse : REJET
        # Troisième réponse : draft V2
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft V1 bad", input_tokens=100, output_tokens=50, model="test"),
            LLMResponse(content="REJET : Trop formel", input_tokens=50, output_tokens=10, model="test"),
            LLMResponse(content="Draft V2 good", input_tokens=150, output_tokens=60, model="test"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        result = use_case.execute(sample_email)

        assert result.status == DraftStatus.CORRECTED_V2
        assert result.draft_v1.content == "Draft V1 bad"
        assert result.draft_final.content == "Draft V2 good"
        assert result.was_corrected is True

    def test_execute_accumulates_tokens(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Vérifie que les tokens sont accumulés correctement."""
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft V1", input_tokens=100, output_tokens=50, model="test"),
            LLMResponse(content="REJET", input_tokens=80, output_tokens=10, model="test"),
            LLMResponse(content="Draft V2", input_tokens=120, output_tokens=60, model="test"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        use_case.execute(sample_email)

        # Total : 100+80+120 = 300 input, 50+10+60 = 120 output
        assert token_usage.input_tokens == 300
        assert token_usage.output_tokens == 120

    def test_execute_with_llm_failure_on_critique(self, mock_llm, sample_email, token_usage, knowledge_base):
        """Échec du LLM lors de la critique."""
        mock_llm.complete.side_effect = [
            LLMResponse(content="Draft V1", input_tokens=100, output_tokens=50, model="test"),
            Exception("LLM error during critique"),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        with pytest.raises(Exception, match="LLM error"):
            use_case.execute(sample_email)

    def test_execute_with_empty_email_fields(self, mock_llm, token_usage, knowledge_base):
        """Email avec id/sender vides lève EmptyValueError."""
        from app.domain.exceptions import EmptyValueError

        with pytest.raises(EmptyValueError):
            Email(
                id="",
                subject="",
                body="",
                sender=""
            )


# ============================================================================
# TESTS - COMPLETE DRAFT USE CASE
# ============================================================================

class TestCompleteDraftUseCaseEdgeCases:
    """Edge cases pour CompleteDraftUseCase."""

    def test_execute_parses_objet_correctly(self, mock_llm, token_usage):
        """Parse correctement OBJET: dans la réponse."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET: Demande de rendez-vous\n\nBonjour,\n\nJe souhaite...",
            input_tokens=100,
            output_tokens=30,
            model="test"
        )

        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage
        )

        draft_input = DraftInput(
            raw_input="- Demander rdv",
            key_points=["Demander rendez-vous"]
        )

        result = use_case.execute(draft_input)

        assert "rendez-vous" in result.subject.lower()
        assert "Bonjour" in result.body

    def test_execute_without_objet_uses_fallback(self, mock_llm, token_usage):
        """Sans OBJET:, utilise le premier key_point."""
        mock_llm.complete.return_value = LLMResponse(
            content="Bonjour,\n\nJe souhaite vous rencontrer.\n\nCordialement",
            input_tokens=100,
            output_tokens=20,
            model="test"
        )

        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage
        )

        draft_input = DraftInput(
            raw_input="- Premier point important",
            key_points=["Premier point important"]
        )

        result = use_case.execute(draft_input)

        assert result.subject == "Premier point important"

    def test_execute_with_empty_key_points(self, mock_llm, token_usage):
        """Exécution avec key_points vide."""
        mock_llm.complete.return_value = LLMResponse(
            content="Response without structure",
            input_tokens=50,
            output_tokens=10,
            model="test"
        )

        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage
        )

        draft_input = DraftInput(
            raw_input="Just some raw text",
            key_points=[]
        )

        result = use_case.execute(draft_input)

        # Fallback to empty subject ou raw_input
        assert result is not None

    def test_execute_with_recipient_in_input(self, mock_llm, token_usage):
        """Exécution avec destinataire spécifié."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET: Test\n\nBody",
            input_tokens=100,
            output_tokens=20,
            model="test"
        )

        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage
        )

        draft_input = DraftInput(
            raw_input="Test",
            key_points=["Test point"],
            recipient="Jean-Pierre"
        )

        use_case.execute(draft_input)

        # Vérifie que le prompt inclut le destinataire
        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs.get("user", "")
        assert "Jean-Pierre" in user_prompt

    def test_execute_preserves_tone(self, mock_llm, token_usage):
        """Le ton est transmis au prompt."""
        mock_llm.complete.return_value = LLMResponse(
            content="OBJET: Test\n\nBody",
            input_tokens=100,
            output_tokens=20,
            model="test"
        )

        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage
        )

        draft_input = DraftInput(
            raw_input="Test",
            key_points=["Test point"],
            tone=DraftInputTone.URGENT
        )

        result = use_case.execute(draft_input)

        # Vérifie que le ton urgent est transmis
        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs.get("user", "")
        assert "urgent" in user_prompt.lower() or result.tone_used == DraftInputTone.URGENT


# ============================================================================
# TESTS - LLM ADAPTER FACTORY
# ============================================================================

class TestLLMAdapterFactory:
    """Tests pour la factory d'adapters LLM."""

    def test_get_llm_adapter_claude(self):
        """Factory retourne ClaudeAdapter pour 'claude'."""
        from app.adapters.llm import get_llm_adapter

        # Mock le module anthropic car il peut ne pas être installé
        with patch.dict('os.environ', {'LLM_PROVIDER': 'claude', 'ANTHROPIC_API_KEY': 'test-key'}):
            try:
                adapter = get_llm_adapter("claude")
                assert adapter is not None
                assert adapter.name == "claude"
            except ModuleNotFoundError:
                # Le module anthropic n'est pas installé, c'est acceptable
                pytest.skip("anthropic module not installed")

    def test_get_llm_adapter_ollama(self):
        """Factory retourne OllamaAdapter pour 'ollama'."""
        from app.adapters.llm import get_llm_adapter

        adapter = get_llm_adapter("ollama")

        assert adapter is not None
        assert adapter.name == "ollama"

    def test_get_llm_adapter_invalid_raises(self):
        """Factory lève une erreur pour provider invalide."""
        from app.adapters.llm import get_llm_adapter

        with pytest.raises(ValueError, match="non supporté"):
            get_llm_adapter("gpt-4")

    def test_get_llm_adapter_default_from_env(self):
        """Factory utilise la variable d'environnement par défaut."""
        from app.adapters.llm import get_llm_adapter

        with patch.dict('os.environ', {'LLM_PROVIDER': 'ollama'}):
            adapter = get_llm_adapter()

        assert adapter.name == "ollama"


# ============================================================================
# TESTS - CONTAINER EDGE CASES
# ============================================================================

class TestContainerEdgeCases:
    """Edge cases pour le Container DI."""

    @pytest.fixture
    def temp_data_dir(self):
        """Crée un répertoire temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_container_lazy_loading_llm(self, temp_data_dir):
        """LLM est chargé en lazy loading."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        config = Config(
            project_root=temp_data_dir,
            llm_provider="ollama"
        )

        container = Container(config=config)

        # Au départ, _llm est None
        assert container._llm is None

    def test_container_singleton_token_usage(self, temp_data_dir):
        """TokenUsage est un singleton dans le container."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        config = Config(
            project_root=temp_data_dir,
            llm_provider="ollama"
        )

        container = Container(config=config)

        # Accès multiples retournent le même objet
        usage1 = container._token_usage
        usage2 = container._token_usage

        assert usage1 is usage2

    def test_container_with_missing_knowledge_file(self, temp_data_dir):
        """Container gère l'absence du fichier knowledge."""
        from app.infrastructure.container import Container
        from app.infrastructure.config import Config

        # Créer la structure mais PAS le fichier memoire.md
        (temp_data_dir / "knowledge").mkdir(parents=True, exist_ok=True)

        config = Config(project_root=temp_data_dir, llm_provider="ollama")
        container = Container(config=config)

        # Devrait gérer gracieusement l'absence du fichier
        assert container._knowledge_base is None


# ============================================================================
# TESTS - CONFIG EDGE CASES ADDITIONNELS
# ============================================================================

class TestConfigAdditionalEdgeCases:
    """Edge cases additionnels pour Config."""

    def test_config_validate_with_empty_string_api_key(self):
        """Validation avec API key chaîne vide."""
        from app.infrastructure.config import Config

        config = Config(
            llm_provider="claude",
            anthropic_api_key=""
        )

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            config.validate()

    def test_config_validate_with_whitespace_api_key(self):
        """Validation avec API key espaces."""
        from app.infrastructure.config import Config

        config = Config(
            llm_provider="claude",
            anthropic_api_key="   "
        )

        # Whitespace-only n'est pas None et n'est pas empty
        # Donc devrait passer la validation
        config.validate()  # Ne devrait pas lever d'erreur

    def test_config_paths_are_pathlib(self):
        """Les chemins sont des objets Path."""
        from app.infrastructure.config import Config

        config = Config()

        assert isinstance(config.project_root, Path)
        assert isinstance(config.knowledge_path, Path)
        assert isinstance(config.data_inputs_path, Path)
        assert isinstance(config.data_outputs_path, Path)


# ============================================================================
# TESTS - DRAFT ENTITY EDGE CASES
# ============================================================================

class TestDraftEntityEdgeCases:
    """Edge cases pour Draft entity."""

    def test_draft_str_returns_content(self):
        """__str__ retourne le contenu."""
        draft = Draft(content="Test content", version=1)
        assert str(draft) == "Test content"

    def test_draft_with_empty_content(self):
        """Draft avec contenu vide."""
        draft = Draft(content="", version=1)
        assert draft.content == ""
        assert str(draft) == ""

    def test_draft_with_version_zero(self):
        """Draft avec version 0 lève InvalidBoundsError."""
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            Draft(content="Content", version=0)

    def test_draft_with_negative_version(self):
        """Draft avec version négative lève InvalidBoundsError."""
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            Draft(content="Content", version=-1)


# ============================================================================
# TESTS - CROSS-LAYER INTEGRATION
# ============================================================================

class TestCrossLayerIntegration:
    """Tests d'intégration cross-layer."""

    def test_full_pipeline_with_mock_llm(self, mock_llm, token_usage, sample_email, knowledge_base):
        """Pipeline complet avec LLM mocké."""
        mock_llm.complete.side_effect = [
            LLMResponse(
                content="Bonjour,\n\nMerci pour votre message.\n\nCordialement",
                input_tokens=100,
                output_tokens=30,
                model="test"
            ),
            LLMResponse(
                content="VALID - Réponse professionnelle et appropriée",
                input_tokens=80,
                output_tokens=10,
                model="test"
            ),
        ]

        use_case = ProcessEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage
        )

        result = use_case.execute(sample_email)

        assert result.email_id == sample_email.id
        assert result.status == DraftStatus.VALIDATED_V1
        assert "Bonjour" in result.draft_final.content
        assert token_usage.total > 0

    def test_draft_completion_with_parsing(self, mock_llm, token_usage):
        """Complétion de draft avec parsing correct."""
        mock_llm.complete.return_value = LLMResponse(
            content="""OBJET : Demande de réunion

Bonjour Jean,

Suite à notre conversation téléphonique, je vous propose
une réunion mardi prochain à 14h.

Merci de me confirmer votre disponibilité.

Cordialement""",
            input_tokens=100,
            output_tokens=50,
            model="test"
        )

        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage
        )

        draft_input = DraftInput(
            raw_input="- proposer réunion mardi 14h",
            key_points=["proposer réunion mardi 14h"],
            recipient="Jean",
            tone=DraftInputTone.FORMAL
        )

        result = use_case.execute(draft_input)

        assert "réunion" in result.subject.lower()
        assert "Jean" in result.body or result.recipient == "Jean"
        assert "14h" in result.body
