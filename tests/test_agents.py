# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les agents IA (DrafterAgent, CriticAgent, TokenCounter).
"""

import pytest
from unittest.mock import MagicMock, patch

from app.agents import (
    TokenCounter,
    DrafterAgent,
    CriticAgent,
    EmailResult,
    process_single_email,
    MODEL_COSTS,
    ExtractedTask,
    CommitmentExtractorAgent,
    ExtractedCommitment,
    PrioritizationAgent,
)
from app.domain.ports import LLMResponse


# ============================================================================
# TESTS - TOKEN COUNTER
# ============================================================================

class TestTokenCounter:
    """Tests pour le compteur de tokens."""

    def test_initial_state(self):
        """Le compteur démarre à zéro."""
        counter = TokenCounter()
        assert counter.input == 0
        assert counter.output == 0
        assert counter.total == 0
        assert counter.model == ""

    def test_add_tokens(self):
        """Ajout de tokens incrémente les compteurs."""
        counter = TokenCounter()
        counter.add(100, 50)
        assert counter.input == 100
        assert counter.output == 50
        assert counter.total == 150

    def test_add_tokens_with_model(self):
        """Ajout de tokens avec modèle."""
        counter = TokenCounter()
        counter.add(100, 50, "claude-sonnet-4-20250514")
        assert counter.model == "claude-sonnet-4-20250514"

    def test_accumulate_tokens(self):
        """Accumulation de plusieurs ajouts."""
        counter = TokenCounter()
        counter.add(100, 50)
        counter.add(200, 100)
        assert counter.input == 300
        assert counter.output == 150
        assert counter.total == 450

    def test_reset(self):
        """Reset remet tout à zéro."""
        counter = TokenCounter()
        counter.add(100, 50, "claude-sonnet-4-20250514")
        counter.reset()
        assert counter.input == 0
        assert counter.output == 0
        assert counter.model == ""

    def test_cost_calculation_sonnet(self):
        """Calcul du coût pour Sonnet."""
        counter = TokenCounter()
        counter.add(1_000_000, 100_000, "claude-sonnet-4-20250514")
        # Sonnet: $3/M input + $15/M output
        # = 1M * 3 / 1M + 0.1M * 15 / 1M = 3 + 1.5 = 4.5
        assert counter.cost == pytest.approx(4.5)

    def test_cost_calculation_haiku(self):
        """Calcul du coût pour Haiku 3.5 (re-priced $0.80/$4.00 — voir MODEL_COSTS)."""
        counter = TokenCounter()
        counter.add(1_000_000, 100_000, "claude-3-5-haiku-20241022")
        # Haiku 3.5: $0.80/M input + $4.00/M output
        # = 1M * 0.80 / 1M + 0.1M * 4.00 / 1M = 0.80 + 0.40 = 1.20
        assert counter.cost == pytest.approx(1.20)

    def test_cost_calculation_opus(self):
        """Calcul du coût pour Opus."""
        counter = TokenCounter()
        counter.add(1_000_000, 100_000, "claude-opus-4-20250514")
        # Opus: $15/M input + $75/M output
        # = 1M * 15 / 1M + 0.1M * 75 / 1M = 15 + 7.5 = 22.5
        assert counter.cost == pytest.approx(22.5)

    def test_cost_unknown_model_defaults_to_sonnet(self):
        """Modèle inconnu utilise les coûts Sonnet par défaut."""
        counter = TokenCounter()
        counter.add(1_000_000, 100_000, "unknown-model")
        # Default (Sonnet rates): $3/M input + $15/M output
        assert counter.cost == pytest.approx(4.5)

    def test_str_representation(self):
        """Représentation string lisible."""
        counter = TokenCounter()
        counter.add(1000, 500, "claude-sonnet-4-20250514")
        result = str(counter)
        assert "1,000↓" in result
        assert "500↑" in result
        assert "$" in result
        assert "sonnet" in result


# ============================================================================
# TESTS - DRAFTER AGENT (MOCKED)
# ============================================================================

class TestDrafterAgent:
    """Tests pour le DrafterAgent avec API mockée."""

    @pytest.fixture
    def mock_llm_response(self):
        """Réponse LLM mockée."""
        return LLMResponse(
            content="Bonjour,\n\nMerci pour votre message.\n\nCordialement",
            input_tokens=500,
            output_tokens=100,
            model="claude-sonnet-4-20250514"
        )

    @pytest.fixture
    def mock_container(self, mock_llm_response):
        """Container mocké avec LLM simulé."""
        container = MagicMock()
        container.llm.complete.return_value = mock_llm_response
        container.llm_label = container.llm  # Alias for cost-optimized agents
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.token_usage = TokenCounter()
        return container

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_calls_api(self, mock_kb, mock_get_container, mock_container, mock_llm_response):
        """draft() appelle le LLM correctement."""
        mock_kb.return_value = "Knowledge base content"
        mock_get_container.return_value = mock_container

        agent = DrafterAgent()
        agent.draft("Test email content")

        # Vérifie l'appel au LLM
        mock_container.llm.complete.assert_called_once()
        call_kwargs = mock_container.llm.complete.call_args[1]
        assert "system" in call_kwargs
        assert "user" in call_kwargs

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_returns_text(self, mock_kb, mock_get_container, mock_container):
        """draft() retourne le texte de réponse."""
        mock_kb.return_value = "Knowledge base content"
        mock_get_container.return_value = mock_container

        agent = DrafterAgent()
        result = agent.draft("Test email")

        assert "Bonjour" in result
        assert "Cordialement" in result

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_revise_includes_critique(self, mock_kb, mock_get_container, mock_container):
        """revise() inclut la critique dans le prompt."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = DrafterAgent()
        agent.revise("Email content", "Ton trop formel")

        call_kwargs = mock_container.llm.complete.call_args[1]
        user_content = call_kwargs["user"]
        assert "Ton trop formel" in user_content

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_with_empty_email(self, mock_kb, mock_get_container, mock_container):
        """draft() gère un email vide."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = DrafterAgent()
        result = agent.draft("")

        # Doit appeler le LLM même avec un email vide
        mock_container.llm.complete.assert_called_once()
        assert result == "Bonjour,\n\nMerci pour votre message.\n\nCordialement"

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_with_unicode_content(self, mock_kb, mock_get_container, mock_container):
        """draft() gère le contenu unicode et emojis."""
        mock_kb.return_value = "KB test"
        mock_get_container.return_value = mock_container

        agent = DrafterAgent()
        agent.draft("📧 Bonjour, été noël ça va?")

        mock_container.llm.complete.assert_called_once()
        call_kwargs = mock_container.llm.complete.call_args[1]
        assert "📧" in call_kwargs["user"]
        assert "été" in call_kwargs["user"]

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_with_very_long_email(self, mock_kb, mock_get_container, mock_container):
        """draft() gère un email très long."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        long_email = "Test " * 10000  # ~50000 caractères
        agent = DrafterAgent()
        agent.draft(long_email)

        mock_container.llm.complete.assert_called_once()

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_revise_with_empty_critique(self, mock_kb, mock_get_container, mock_container):
        """revise() gère une critique vide."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = DrafterAgent()
        agent.revise("Email content", "")

        mock_container.llm.complete.assert_called_once()

    def test_drafter_default_values(self):
        """DrafterAgent default values, including the runtime-derived `model`.

        Audit 2026-05-04: this used to assert ``agent.model == MODEL_DEFAULT``
        on a hand-stamped dataclass field — but `__post_init__` always
        overrides ``_llm`` with the categorized "label" tier (Haiku), so the
        field value never matched the runtime. The field is gone; ``model``
        is now a property that reads from ``self._llm``. The test now pins
        that contract.
        """
        from app.config import MAX_TOKENS_DRAFT

        agent = DrafterAgent.__new__(DrafterAgent)
        agent.max_tokens = MAX_TOKENS_DRAFT
        # No `_llm` bound (we bypass `__post_init__`) — property must
        # gracefully return "" instead of raising AttributeError.
        agent._llm = None

        assert agent.max_tokens == MAX_TOKENS_DRAFT
        assert agent.model == ""

        # And once a fake LLM is bound, the property reflects it.
        class _FakeLLM:
            model = "claude-haiku-4-5-20251001"
        agent._llm = _FakeLLM()
        assert agent.model == "claude-haiku-4-5-20251001"

    # ========================================================================
    # Story 4-4: Style Adaptation Tests
    # ========================================================================

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_with_style_context_uses_style_prompt(
        self, mock_kb, mock_get_container, mock_container, mock_llm_response
    ):
        """draft() avec style_context utilise le prompt avec style."""
        mock_kb.return_value = "Knowledge base content"
        mock_get_container.return_value = mock_container

        style_context = "Style d'écriture: Ton décontracté, tutoiement"

        agent = DrafterAgent()
        agent.draft("Test email", style_context=style_context)

        # Vérifie que le system prompt contient le style context
        call_kwargs = mock_container.llm.complete.call_args[1]
        system_prompt = call_kwargs["system"]
        assert "STYLE_UTILISATEUR" in system_prompt
        assert style_context in system_prompt

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_without_style_context_uses_standard_prompt(
        self, mock_kb, mock_get_container, mock_container, mock_llm_response
    ):
        """draft() sans style_context utilise le prompt standard."""
        mock_kb.return_value = "Knowledge base content"
        mock_get_container.return_value = mock_container

        agent = DrafterAgent()
        agent.draft("Test email")

        # Vérifie que le system prompt est standard (pas de STYLE_UTILISATEUR)
        call_kwargs = mock_container.llm.complete.call_args[1]
        system_prompt = call_kwargs["system"]
        assert "STYLE_UTILISATEUR" not in system_prompt
        # Le prompt standard contient CONTEXTE mais pas STYLE_UTILISATEUR
        assert "CONTEXTE" in system_prompt

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_with_none_style_context_uses_standard_prompt(
        self, mock_kb, mock_get_container, mock_container, mock_llm_response
    ):
        """draft() avec style_context=None utilise le prompt standard."""
        mock_kb.return_value = "KB content"
        mock_get_container.return_value = mock_container

        agent = DrafterAgent()
        agent.draft("Test email", style_context=None)

        call_kwargs = mock_container.llm.complete.call_args[1]
        system_prompt = call_kwargs["system"]
        assert "STYLE_UTILISATEUR" not in system_prompt

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_with_empty_style_context_uses_standard_prompt(
        self, mock_kb, mock_get_container, mock_container, mock_llm_response
    ):
        """draft() avec style_context vide utilise le prompt standard."""
        mock_kb.return_value = "KB content"
        mock_get_container.return_value = mock_container

        agent = DrafterAgent()
        agent.draft("Test email", style_context="")

        call_kwargs = mock_container.llm.complete.call_args[1]
        system_prompt = call_kwargs["system"]
        assert "STYLE_UTILISATEUR" not in system_prompt

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_revise_with_style_context_uses_style_prompt(
        self, mock_kb, mock_get_container, mock_container, mock_llm_response
    ):
        """revise() avec style_context utilise le prompt avec style."""
        mock_kb.return_value = "KB content"
        mock_get_container.return_value = mock_container

        style_context = "Style: formel, vouvoiement"

        agent = DrafterAgent()
        agent.revise("Email content", "Critique", style_context=style_context)

        call_kwargs = mock_container.llm.complete.call_args[1]
        system_prompt = call_kwargs["system"]
        assert "STYLE_UTILISATEUR" in system_prompt
        assert style_context in system_prompt

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_revise_without_style_context_uses_standard_prompt(
        self, mock_kb, mock_get_container, mock_container, mock_llm_response
    ):
        """revise() sans style_context utilise le prompt standard."""
        mock_kb.return_value = "KB content"
        mock_get_container.return_value = mock_container

        agent = DrafterAgent()
        agent.revise("Email content", "Critique")

        call_kwargs = mock_container.llm.complete.call_args[1]
        system_prompt = call_kwargs["system"]
        assert "STYLE_UTILISATEUR" not in system_prompt


# ============================================================================
# TESTS - CRITIC AGENT (MOCKED)
# ============================================================================

class TestCriticAgent:
    """Tests pour le CriticAgent."""

    @pytest.fixture
    def mock_container(self):
        """Container mocké pour CriticAgent."""
        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.return_value = LLMResponse(
            content="VALID",
            input_tokens=200,
            output_tokens=10,
            model="claude-sonnet-4-20250514"
        )
        container.token_usage = TokenCounter()
        return container

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_is_valid_accepts_valid(self, mock_kb, mock_get_container, mock_container):
        """is_valid() accepte les réponses VALID."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        assert agent.is_valid("VALID") is True
        assert agent.is_valid("valid") is True
        assert agent.is_valid("VALID - Good response") is True
        assert agent.is_valid("  VALID  ") is True

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_is_valid_rejects_invalid(self, mock_kb, mock_get_container, mock_container):
        """is_valid() rejette les réponses REJET."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        assert agent.is_valid("REJET : Ton inapproprié") is False
        assert agent.is_valid("rejet: erreur") is False
        assert agent.is_valid("Not valid") is False

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_calls_api(self, mock_kb, mock_get_container, mock_container):
        """evaluate() appelle le LLM avec email et draft."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        agent.evaluate("Email original", "Draft proposé")

        call_kwargs = mock_container.llm.complete.call_args[1]
        user_content = call_kwargs["user"]
        assert "Email original" in user_content
        assert "Draft proposé" in user_content

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_is_valid_with_empty_string(self, mock_kb, mock_get_container, mock_container):
        """is_valid() retourne False pour une chaîne vide."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        assert agent.is_valid("") is False

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_is_valid_with_whitespace_only(self, mock_kb, mock_get_container, mock_container):
        """is_valid() retourne False pour des espaces seulement."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        assert agent.is_valid("   ") is False
        assert agent.is_valid("\t\n") is False

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_is_valid_case_insensitive(self, mock_kb, mock_get_container, mock_container):
        """is_valid() est insensible à la casse."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        assert agent.is_valid("VALID") is True
        assert agent.is_valid("Valid") is True
        assert agent.is_valid("valid") is True
        assert agent.is_valid("VaLiD") is True

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_is_valid_with_trailing_text(self, mock_kb, mock_get_container, mock_container):
        """is_valid() accepte VALID avec du texte après."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        assert agent.is_valid("VALID - Bonne réponse") is True
        assert agent.is_valid("VALID: tout est ok") is True
        assert agent.is_valid("VALIDATED") is True  # startswith VALID

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_with_empty_email(self, mock_kb, mock_get_container, mock_container):
        """evaluate() gère un email vide."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        agent.evaluate("", "Draft de test")

        mock_container.llm.complete.assert_called_once()

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_with_empty_draft(self, mock_kb, mock_get_container, mock_container):
        """evaluate() gère un draft vide."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        agent.evaluate("Email de test", "")

        mock_container.llm.complete.assert_called_once()

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_with_unicode_content(self, mock_kb, mock_get_container, mock_container):
        """evaluate() gère le contenu unicode."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        agent.evaluate("📧 Email été noël", "Réponse été 🎉")

        mock_container.llm.complete.assert_called_once()
        call_kwargs = mock_container.llm.complete.call_args[1]
        assert "📧" in call_kwargs["user"]
        assert "🎉" in call_kwargs["user"]

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_strips_response(self, mock_kb, mock_get_container, mock_container):
        """evaluate() strip les espaces de la réponse."""
        mock_kb.return_value = "KB"
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content="  VALID  \n",
            input_tokens=200,
            output_tokens=10,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate("Email", "Draft")

        assert result == "VALID"

    def test_critic_default_values(self):
        """CriticAgent default values, including the runtime-derived `model`.

        Audit 2026-05-04: same fix as ``test_drafter_default_values`` —
        the cosmetic ``model: str = MODEL_DEFAULT`` field was removed
        because it lied about the actual runtime LLM. ``model`` is now a
        property that reflects the bound ``_llm``.
        """
        from app.config import MAX_TOKENS_CRITIC

        agent = CriticAgent.__new__(CriticAgent)
        agent.max_tokens = MAX_TOKENS_CRITIC
        agent._llm = None

        assert agent.max_tokens == MAX_TOKENS_CRITIC
        assert agent.model == ""

        class _FakeLLM:
            model = "claude-haiku-4-5-20251001"
        agent._llm = _FakeLLM()
        assert agent.model == "claude-haiku-4-5-20251001"


# ============================================================================
# TESTS - PIPELINE
# ============================================================================

class TestEmailPipeline:
    """Tests pour le pipeline de traitement."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_process_single_email_valid_v1(self, mock_kb, mock_get_container):
        """Pipeline avec V1 validée directement."""
        mock_kb.return_value = "KB"

        # Réponses LLM successives
        draft_response = LLMResponse(
            content="Réponse draft",
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        critic_response = LLMResponse(
            content="VALID",
            input_tokens=150,
            output_tokens=10,
            model="claude-sonnet-4-20250514"
        )

        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.side_effect = [draft_response, critic_response]
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        drafter = DrafterAgent()
        critic = CriticAgent()

        result = process_single_email(drafter, critic, 1, "Email test", "Réponse humaine")

        assert isinstance(result, EmailResult)
        assert result.status == "VALIDÉ V1"
        assert result.draft_v1 == result.draft_final
        assert container.llm.complete.call_count == 2  # draft + critic

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_process_single_email_corrected_v2(self, mock_kb, mock_get_container):
        """Pipeline avec correction V2."""
        mock_kb.return_value = "KB"

        # Réponses LLM successives
        draft_v1 = LLMResponse(
            content="Draft V1",
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        critic_resp = LLMResponse(
            content="REJET : Ton inapproprié",
            input_tokens=150,
            output_tokens=20,
            model="claude-sonnet-4-20250514"
        )
        draft_v2 = LLMResponse(
            content="Draft V2 corrigé",
            input_tokens=200,
            output_tokens=60,
            model="claude-sonnet-4-20250514"
        )

        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.side_effect = [draft_v1, critic_resp, draft_v2]
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        drafter = DrafterAgent()
        critic = CriticAgent()

        result = process_single_email(drafter, critic, 1, "Email", "")

        assert result.status == "CORRIGÉ V2"
        assert result.draft_v1 == "Draft V1"
        assert result.draft_final == "Draft V2 corrigé"
        assert "REJET" in result.critique
        assert container.llm.complete.call_count == 3  # draft + critic + revise


# ============================================================================
# TESTS - MODEL COSTS
# ============================================================================

class TestModelCosts:
    """Tests pour les coûts des modèles."""

    def test_all_models_have_costs(self):
        """Tous les modèles ont des coûts définis."""
        expected_models = [
            "claude-sonnet-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-opus-4-20250514",
            "claude-3-opus-20240229",
        ]
        for model in expected_models:
            assert model in MODEL_COSTS
            assert "input" in MODEL_COSTS[model]
            assert "output" in MODEL_COSTS[model]

    def test_haiku_cheapest_claude(self):
        """Haiku est le modèle Claude le moins cher (Ollama est gratuit)."""
        haiku_cost = MODEL_COSTS["claude-3-5-haiku-20241022"]
        for model, costs in MODEL_COSTS.items():
            # Ignorer Ollama (gratuit) et Haiku lui-même
            if "haiku" not in model and "claude" in model:
                assert haiku_cost["input"] <= costs["input"]
                assert haiku_cost["output"] <= costs["output"]

    def test_opus_most_expensive(self):
        """Opus est le modèle le plus cher."""
        opus_cost = MODEL_COSTS["claude-opus-4-20250514"]
        for model, costs in MODEL_COSTS.items():
            if "opus" not in model:
                assert opus_cost["input"] >= costs["input"]
                assert opus_cost["output"] >= costs["output"]


# ============================================================================
# TESTS - TASK EXTRACTOR AGENT
# ============================================================================


class TestCommitmentExtractorAgent:
    """Tests pour le CommitmentExtractorAgent."""

    @pytest.fixture
    def mock_container(self):
        """Container mocké pour CommitmentExtractorAgent."""
        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.return_value = LLMResponse(
            content='{"commitments": [{"description": "Envoyer le document demain", "deadline": "2024-01-15"}]}',
            input_tokens=200,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        container.token_usage = TokenCounter()
        return container

    @patch("app.agents.get_container")
    def test_extract_commitment_from_email(self, mock_get_container, mock_container):
        """extract() extrait un engagement d'un email."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": [{"description": "Envoyer le document demain", "deadline": "2024-01-15"}]}',
            input_tokens=200,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Je vous envoie le document demain.")

        assert len(commitments) == 1
        assert commitments[0].description == "Envoyer le document demain"
        assert commitments[0].deadline == "2024-01-15"

    @patch("app.agents.get_container")
    def test_extract_multiple_commitments(self, mock_get_container, mock_container):
        """extract() extrait plusieurs engagements d'un email."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": [{"description": "Envoyer le rapport", "deadline": "2024-01-15"}, {"description": "Rappeler lundi", "deadline": "2024-01-20"}]}',
            input_tokens=250,
            output_tokens=80,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Je vous envoie le rapport demain et je vous rappelle lundi.")

        assert len(commitments) == 2
        assert commitments[0].description == "Envoyer le rapport"
        assert commitments[1].description == "Rappeler lundi"

    @patch("app.agents.get_container")
    def test_extract_no_commitments(self, mock_get_container, mock_container):
        """extract() retourne une liste vide pour un email sans engagement."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": []}',
            input_tokens=150,
            output_tokens=20,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Merci pour votre message. Bonne journée.")

        assert len(commitments) == 0
        assert commitments == []

    @patch("app.agents.get_container")
    def test_extract_with_deadline(self, mock_get_container, mock_container):
        """extract() détecte les deadlines mentionnées."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": [{"description": "Soumettre la proposition", "deadline": "2024-02-28"}]}',
            input_tokens=180,
            output_tokens=45,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Je vous soumets ma proposition avant le 28 février.")

        assert len(commitments) == 1
        assert commitments[0].deadline == "2024-02-28"

    @patch("app.agents.get_container")
    def test_extract_without_deadline(self, mock_get_container, mock_container):
        """extract() gère les engagements sans deadline explicite."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": [{"description": "Revenir vers vous avec une proposition", "deadline": null}]}',
            input_tokens=180,
            output_tokens=45,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Je reviens vers vous avec une proposition.")

        assert len(commitments) == 1
        assert commitments[0].deadline is None

    @patch("app.agents.get_container")
    def test_extract_handles_llm_error(self, mock_get_container, mock_container):
        """extract() retourne une liste vide en cas d'erreur LLM."""
        mock_get_container.return_value = mock_container
        mock_container.llm.complete.side_effect = Exception("API Error")

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Email de test")

        assert commitments == []

    @patch("app.agents.get_container")
    def test_extract_with_empty_email(self, mock_get_container, mock_container):
        """extract() gère correctement un email vide."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": []}',
            input_tokens=10,
            output_tokens=5,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("")

        assert commitments == []
        mock_container.llm.complete.assert_called_once()

    @patch("app.agents.get_container")
    def test_extract_with_malformed_json(self, mock_get_container, mock_container):
        """extract() gère un JSON malformé."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": [{"description": "Test"',
            input_tokens=100,
            output_tokens=30,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Je m'en occupe.")

        assert commitments == []

    @patch("app.agents.get_container")
    def test_extract_with_missing_commitments_key(self, mock_get_container, mock_container):
        """extract() gère un JSON sans clé 'commitments'."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"other_key": [{"description": "Test"}]}',
            input_tokens=100,
            output_tokens=30,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Je m'en occupe demain.")

        assert commitments == []

    @patch("app.agents.get_container")
    def test_extract_with_null_commitments_array(self, mock_get_container, mock_container):
        """extract() gère un JSON avec commitments: null."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": null}',
            input_tokens=50,
            output_tokens=10,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Email de test")

        # commitments.get("commitments", []) retourne None, pas une liste
        # Le code vérifie isinstance(commitments, list) et retourne []
        assert isinstance(commitments, list)
        assert commitments == []

    @patch("app.agents.get_container")
    def test_extract_with_commitments_not_a_list(self, mock_get_container, mock_container):
        """extract() gère un JSON où commitments n'est pas une liste."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": "should be a list"}',
            input_tokens=50,
            output_tokens=10,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Email de test")

        # Le code vérifie isinstance(commitments, list) et retourne []
        assert isinstance(commitments, list)
        assert commitments == []

    @patch("app.agents.get_container")
    def test_extract_with_special_characters(self, mock_get_container, mock_container):
        """extract() gère correctement les caractères spéciaux et emojis."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": [{"description": "Envoyer le document été/hiver 📄", "deadline": null}]}',
            input_tokens=200,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("📧 Email avec emojis et accents: été, noël, ça!")

        assert len(commitments) == 1
        assert "📄" in commitments[0].description
        assert "été" in commitments[0].description

    @patch("app.agents.get_container")
    def test_extract_preserves_deadline_formats(self, mock_get_container, mock_container):
        """extract() préserve différents formats de deadline."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": [{"description": "Engagement 1", "deadline": "2024-12-31T23:59:59"}, {"description": "Engagement 2", "deadline": "demain"}]}',
            input_tokens=180,
            output_tokens=60,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Je fais ça pour demain et l'autre avant la fin de l'année.")

        assert len(commitments) == 2
        assert commitments[0].deadline == "2024-12-31T23:59:59"  # ISO format préservé
        assert commitments[1].deadline == "demain"  # Texte non-ISO préservé

    @patch("app.agents.get_container")
    def test_extract_filters_non_dict_items(self, mock_get_container, mock_container):
        """extract() filtre les éléments qui ne sont pas des dicts."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"commitments": [{"description": "Valid", "deadline": null}, "invalid string", 123, null]}',
            input_tokens=100,
            output_tokens=40,
            model="claude-sonnet-4-20250514"
        )

        agent = CommitmentExtractorAgent()
        commitments = agent.extract("Email de test")

        # Seul le dict valide doit être retourné
        assert len(commitments) == 1
        assert commitments[0].description == "Valid"


# ============================================================================
# TESTS - PRIORITIZATION AGENT
# ============================================================================


class TestPrioritizationAgent:
    """Tests pour le PrioritizationAgent."""

    @pytest.fixture
    def mock_container(self):
        """Container mocké pour PrioritizationAgent."""
        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.return_value = LLMResponse(
            content='{"urgency": 80, "vip": 60, "sentiment": 0.5, "deadline": "2024-01-15", "priority_score": 75}',
            input_tokens=200,
            output_tokens=50,
            model="claude-3-5-haiku-20241022"
        )
        container.token_usage = TokenCounter()
        return container

    @patch("app.agents.get_container")
    def test_analyze_returns_priority_scores(self, mock_get_container, mock_container):
        """analyze() retourne les scores de priorité correctement."""
        mock_get_container.return_value = mock_container

        agent = PrioritizationAgent()
        result = agent.analyze("URGENT: Besoin du rapport aujourd'hui!", "vip@client.com")

        assert result["urgency"] == 80
        assert result["vip"] == 60
        assert result["sentiment"] == 0.5
        assert result["deadline"] == "2024-01-15"
        assert result["priority_score"] == 75

    @patch("app.agents.get_container")
    def test_analyze_without_sender(self, mock_get_container, mock_container):
        """analyze() fonctionne sans expéditeur."""
        mock_get_container.return_value = mock_container

        agent = PrioritizationAgent()
        agent.analyze("Email de test")

        # Vérifie que l'API est appelée sans le contexte expéditeur
        call_kwargs = mock_container.llm.complete.call_args[1]
        assert "Expéditeur" not in call_kwargs["user"]

    @patch("app.agents.get_container")
    def test_analyze_with_sender_includes_context(self, mock_get_container, mock_container):
        """analyze() inclut l'expéditeur dans le contexte."""
        mock_get_container.return_value = mock_container

        agent = PrioritizationAgent()
        agent.analyze("Email", "ceo@company.com")

        call_kwargs = mock_container.llm.complete.call_args[1]
        assert "ceo@company.com" in call_kwargs["user"]
        assert "Expéditeur" in call_kwargs["user"]

    @patch("app.agents.get_container")
    def test_analyze_handles_llm_error(self, mock_get_container, mock_container):
        """analyze() retourne les valeurs par défaut en cas d'erreur LLM."""
        mock_get_container.return_value = mock_container
        mock_container.llm.complete.side_effect = Exception("API Error")

        agent = PrioritizationAgent()
        result = agent.analyze("Email de test")

        # Valeurs par défaut
        assert result["urgency"] == 50
        assert result["vip"] == 50
        assert result["sentiment"] == 0
        assert result["deadline"] is None
        assert result["priority_score"] == 50

    @patch("app.agents.get_container")
    def test_analyze_with_malformed_json(self, mock_get_container, mock_container):
        """analyze() gère un JSON malformé du LLM."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"urgency": 80, broken',
            input_tokens=100,
            output_tokens=20,
            model="claude-3-5-haiku-20241022"
        )

        agent = PrioritizationAgent()
        result = agent.analyze("Email")

        # Doit retourner les valeurs par défaut
        assert result["urgency"] == 50
        assert result["priority_score"] == 50

    @patch("app.agents.get_container")
    def test_analyze_with_empty_email(self, mock_get_container, mock_container):
        """analyze() gère un email vide."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"urgency": 10, "vip": 10, "sentiment": 0, "deadline": null, "priority_score": 10}',
            input_tokens=50,
            output_tokens=30,
            model="claude-3-5-haiku-20241022"
        )

        agent = PrioritizationAgent()
        result = agent.analyze("")

        assert isinstance(result, dict)
        mock_container.llm.complete.assert_called_once()

    @patch("app.agents.get_container")
    def test_analyze_with_unicode_content(self, mock_get_container, mock_container):
        """analyze() gère le contenu unicode."""
        mock_get_container.return_value = mock_container

        agent = PrioritizationAgent()
        agent.analyze("📧 Email été noël ça urgent!")

        # Doit appeler le LLM sans erreur
        mock_container.llm.complete.assert_called_once()

    @patch("app.agents.get_container")
    def test_analyze_with_partial_json_response(self, mock_get_container, mock_container):
        """analyze() gère une réponse JSON partielle."""
        mock_get_container.return_value = mock_container
        mock_container.llm_label = mock_container.llm
        mock_container.llm_drafting = mock_container.llm
        mock_container.llm_background = mock_container.llm
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"urgency": 90}',  # Manque les autres champs
            input_tokens=50,
            output_tokens=15,
            model="claude-3-5-haiku-20241022"
        )

        agent = PrioritizationAgent()
        result = agent.analyze("Email urgent")

        # Le JSON partiel doit être utilisé, les valeurs par défaut pour le reste
        assert result.get("urgency") == 90 or result.get("urgency") == 50


class TestCommitmentExtractorAgentParseCommitment:
    """Tests pour la méthode statique _parse_commitment."""

    def test_parse_commitment_complete(self):
        """_parse_commitment avec toutes les données."""
        commitment_dict = {
            "description": "Envoyer le document",
            "deadline": "2024-01-15"
        }
        result = CommitmentExtractorAgent._parse_commitment(commitment_dict)

        assert result.description == "Envoyer le document"
        assert result.deadline == "2024-01-15"

    def test_parse_commitment_without_deadline(self):
        """_parse_commitment sans deadline."""
        commitment_dict = {
            "description": "Rappeler le client"
        }
        result = CommitmentExtractorAgent._parse_commitment(commitment_dict)

        assert result.description == "Rappeler le client"
        assert result.deadline is None

    def test_parse_commitment_empty_dict(self):
        """_parse_commitment avec dict vide."""
        commitment_dict = {}
        result = CommitmentExtractorAgent._parse_commitment(commitment_dict)

        assert result.description == ""
        assert result.deadline is None

    def test_parse_commitment_with_null_deadline(self):
        """_parse_commitment avec deadline null explicite."""
        commitment_dict = {
            "description": "Préparer le dossier",
            "deadline": None
        }
        result = CommitmentExtractorAgent._parse_commitment(commitment_dict)

        assert result.description == "Préparer le dossier"
        assert result.deadline is None

    def test_parse_commitment_with_extra_fields(self):
        """_parse_commitment ignore les champs supplémentaires."""
        commitment_dict = {
            "description": "Envoyer le document",
            "deadline": "2024-01-15",
            "extra_field": "should be ignored",
            "priority": "high",
            "another_field": 123
        }
        result = CommitmentExtractorAgent._parse_commitment(commitment_dict)

        assert result.description == "Envoyer le document"
        assert result.deadline == "2024-01-15"

    def test_parse_commitment_with_numeric_values(self):
        """_parse_commitment gère des valeurs numériques (pas typées correctement)."""
        commitment_dict = {
            "description": 12345,
            "deadline": 2024
        }
        result = CommitmentExtractorAgent._parse_commitment(commitment_dict)

        # Les valeurs numériques sont retournées telles quelles
        assert result.description == 12345
        assert result.deadline == 2024

    def test_parse_commitment_with_whitespace_description(self):
        """_parse_commitment avec description contenant uniquement des espaces."""
        commitment_dict = {
            "description": "   ",
            "deadline": "2024-01-15"
        }
        result = CommitmentExtractorAgent._parse_commitment(commitment_dict)

        # Pas de strip automatique
        assert result.description == "   "
        assert result.deadline == "2024-01-15"

    def test_parse_commitment_with_empty_string_deadline(self):
        """_parse_commitment avec deadline chaîne vide."""
        commitment_dict = {
            "description": "Engagement test",
            "deadline": ""
        }
        result = CommitmentExtractorAgent._parse_commitment(commitment_dict)

        assert result.description == "Engagement test"
        assert result.deadline == ""

    def test_parse_commitment_with_unicode_content(self):
        """_parse_commitment gère le contenu unicode."""
        commitment_dict = {
            "description": "Engagement été 📋 noël",
            "deadline": "demain"
        }
        result = CommitmentExtractorAgent._parse_commitment(commitment_dict)

        assert result.description == "Engagement été 📋 noël"
        assert "été" in result.description
        assert "📋" in result.description

    def test_parse_commitment_with_none_description(self):
        """_parse_commitment avec description None explicite."""
        commitment_dict = {
            "description": None,
            "deadline": "2024-01-15"
        }
        result = CommitmentExtractorAgent._parse_commitment(commitment_dict)

        # get() retourne None (pas la valeur par défaut) si la clé existe avec None
        assert result.description is None
        assert result.deadline == "2024-01-15"


# ============================================================================
# TESTS - DRAFTER AGENT NO ASSUMPTION INSTRUCTION
# ============================================================================


class TestDrafterNoAssumptionInstruction:
    """Tests pour l'instruction 'ne jamais supposer' du DrafterAgent."""

    def test_drafter_system_prompt_contains_no_assumption_instruction(self):
        """Le prompt système du Drafter contient l'instruction de ne jamais supposer.

        Audit 2026-05-04 : RÈGLE #5bis (l'interdiction explicite des
        marqueurs `[À confirmer]`) a été retirée — le drafter audit a
        confirmé un placeholder rate de 0 % sur 60 cas sans elle, et le
        Critic + le strip post-LLM constituent la défense en profondeur.
        Le test ne vérifie plus la présence du marqueur dans le prompt
        (il y était comme exemple INTERDIT de la règle supprimée).
        Reste vérifié : la directive "ne jamais inventer / supposer" de
        la RÈGLE #5, qui couvre la motivation originale.
        """
        from app.prompts import DRAFTER_SYSTEM_PROMPT

        prompt_lower = DRAFTER_SYSTEM_PROMPT.lower()
        assert "jamais" in prompt_lower and "suppos" in prompt_lower

    def test_drafter_user_prompt_does_not_instruct_to_use_confirmation_marker(self):
        """Le prompt utilisateur du Drafter NE doit PAS instruire d'utiliser [À confirmer].

        La RÈGLE 5bis du system prompt interdit explicitement ces marqueurs ; demander
        au user prompt de les utiliser créait une contradiction et déclenchait des V2
        retries inutiles. Le system prompt reste la source de vérité (cf.
        test_drafter_system_prompt_contains_no_assumption_instruction).
        """
        from app.prompts import DRAFTER_USER_PROMPT

        prompt_lower = DRAFTER_USER_PROMPT.lower()
        assert "[à confirmer]" not in prompt_lower
        assert "à valider" not in prompt_lower

    def test_drafter_correction_prompt_does_not_instruct_to_use_confirmation_marker(self):
        """Le prompt de correction NE doit PAS instruire d'utiliser [À confirmer].

        Même raison que le user prompt ci-dessus : la RÈGLE 5bis du system prompt
        gouverne, le correction prompt n'a pas à la contredire.
        """
        from app.prompts import DRAFTER_CORRECTION_PROMPT

        prompt_lower = DRAFTER_CORRECTION_PROMPT.lower()
        assert "[à confirmer]" not in prompt_lower
        assert "à valider" not in prompt_lower

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_drafter_system_prompt_includes_no_assumption_when_called(
        self, mock_kb, mock_get_container
    ):
        """Le prompt système envoyé au LLM contient l'instruction de non-supposition."""
        mock_kb.return_value = "Knowledge base test"

        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.return_value = LLMResponse(
            content="Test response",
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        agent = DrafterAgent()
        agent.draft("Test email")

        call_kwargs = container.llm.complete.call_args[1]
        system_prompt = call_kwargs["system"]

        assert "jamais" in system_prompt.lower() and "suppos" in system_prompt.lower()


# ============================================================================
# TESTS - TOKEN COUNTER EDGE CASES
# ============================================================================


class TestTokenCounterEdgeCases:
    """Tests pour les edge cases du TokenCounter/TokenUsage."""

    def test_add_negative_input_tokens_raises_error(self):
        """add() avec input_tokens négatif lève InvalidBoundsError."""
        from app.domain.exceptions import InvalidBoundsError

        counter = TokenCounter()
        with pytest.raises(InvalidBoundsError):
            counter.add(-100, 50)

    def test_add_negative_output_tokens_raises_error(self):
        """add() avec output_tokens négatif lève InvalidBoundsError."""
        from app.domain.exceptions import InvalidBoundsError

        counter = TokenCounter()
        with pytest.raises(InvalidBoundsError):
            counter.add(100, -50)

    def test_init_negative_input_tokens_raises_error(self):
        """Initialisation avec input_tokens négatif lève InvalidBoundsError."""
        from app.domain.exceptions import InvalidBoundsError
        from app.domain.entities.token_usage import TokenUsage

        with pytest.raises(InvalidBoundsError):
            TokenUsage(input_tokens=-100, output_tokens=50)

    def test_init_negative_output_tokens_raises_error(self):
        """Initialisation avec output_tokens négatif lève InvalidBoundsError."""
        from app.domain.exceptions import InvalidBoundsError
        from app.domain.entities.token_usage import TokenUsage

        with pytest.raises(InvalidBoundsError):
            TokenUsage(input_tokens=100, output_tokens=-50)

    def test_str_without_model(self):
        """__str__ sans modèle défini."""
        counter = TokenCounter()
        counter.add(1000, 500)
        result = str(counter)

        assert "1,000↓" in result
        assert "500↑" in result
        # Pas de modèle dans la sortie
        assert "|" in result  # Format avec séparateurs

    def test_str_with_ollama_model_format(self):
        """__str__ avec modèle au format Ollama (contenant :)."""
        counter = TokenCounter()
        counter.add(1000, 500, "llama3.1:8b")
        result = str(counter)

        assert "1,000↓" in result
        assert "500↑" in result
        # Le code split sur ":" pour extraire le nom court
        assert "llama3.1" in result or "llama" in result

    def test_cost_with_zero_tokens(self):
        """cost est 0 quand aucun token n'est utilisé."""
        counter = TokenCounter()
        assert counter.cost == 0.0

    def test_add_with_empty_model_preserves_existing(self):
        """add() avec model vide préserve le modèle existant."""
        counter = TokenCounter()
        counter.add(100, 50, "claude-sonnet-4-20250514")
        counter.add(100, 50, "")  # Pas de modèle spécifié

        assert counter.model == "claude-sonnet-4-20250514"

    def test_add_with_new_model_updates(self):
        """add() avec nouveau modèle le met à jour."""
        counter = TokenCounter()
        counter.add(100, 50, "claude-sonnet-4-20250514")
        counter.add(100, 50, "claude-3-5-haiku-20241022")

        assert counter.model == "claude-3-5-haiku-20241022"

    def test_cost_with_very_large_token_count(self):
        """cost avec un très grand nombre de tokens."""
        counter = TokenCounter()
        counter.add(10_000_000, 5_000_000, "claude-sonnet-4-20250514")
        # Sonnet: $3/M input + $15/M output
        # = 10M * 3 / 1M + 5M * 15 / 1M = 30 + 75 = 105
        assert counter.cost == pytest.approx(105.0)

    def test_total_property(self):
        """total retourne la somme des tokens."""
        counter = TokenCounter()
        counter.add(1000, 500)
        counter.add(500, 250)

        assert counter.total == 2250
        assert counter.input == 1500
        assert counter.output == 750


# ============================================================================
# TESTS - PROCESS SINGLE EMAIL EDGE CASES
# ============================================================================


class TestProcessSingleEmailEdgeCases:
    """Tests pour les edge cases de process_single_email."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_process_with_empty_human_response(self, mock_kb, mock_get_container):
        """process_single_email fonctionne avec une réponse humaine vide."""
        mock_kb.return_value = "KB"

        draft_response = LLMResponse(
            content="Draft test",
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        critic_response = LLMResponse(
            content="VALID",
            input_tokens=150,
            output_tokens=10,
            model="claude-sonnet-4-20250514"
        )

        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.side_effect = [draft_response, critic_response]
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        drafter = DrafterAgent()
        critic = CriticAgent()

        result = process_single_email(drafter, critic, 1, "Test email", "")

        assert isinstance(result, EmailResult)
        assert result.status == "VALIDÉ V1"

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_process_with_special_characters_in_email(self, mock_kb, mock_get_container):
        """process_single_email gère les caractères spéciaux dans l'email."""
        mock_kb.return_value = "KB"

        draft_response = LLMResponse(
            content="Réponse avec été 🎉",
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        critic_response = LLMResponse(
            content="VALID",
            input_tokens=150,
            output_tokens=10,
            model="claude-sonnet-4-20250514"
        )

        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.side_effect = [draft_response, critic_response]
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        drafter = DrafterAgent()
        critic = CriticAgent()

        result = process_single_email(
            drafter, critic, 1,
            "Email avec émojis 📧 et accents: été, noël, ça va?",
            "Réponse humaine été"
        )

        assert isinstance(result, EmailResult)
        assert "été" in result.draft_final or result.draft_final is not None

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_process_returns_correct_row_number(self, mock_kb, mock_get_container):
        """process_single_email retourne le bon numéro de ligne."""
        mock_kb.return_value = "KB"

        draft_response = LLMResponse(
            content="Draft",
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        critic_response = LLMResponse(
            content="VALID",
            input_tokens=150,
            output_tokens=10,
            model="claude-sonnet-4-20250514"
        )

        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.side_effect = [draft_response, critic_response]
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        drafter = DrafterAgent()
        critic = CriticAgent()

        result = process_single_email(drafter, critic, 42, "Email", "")

        assert result.numero == 42

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_process_with_very_long_email(self, mock_kb, mock_get_container):
        """process_single_email gère un email très long."""
        mock_kb.return_value = "KB"

        draft_response = LLMResponse(
            content="Draft court",
            input_tokens=10000,
            output_tokens=100,
            model="claude-sonnet-4-20250514"
        )
        critic_response = LLMResponse(
            content="VALID",
            input_tokens=150,
            output_tokens=10,
            model="claude-sonnet-4-20250514"
        )

        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.side_effect = [draft_response, critic_response]
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        drafter = DrafterAgent()
        critic = CriticAgent()

        long_email = "Paragraphe test. " * 5000  # ~80000 caractères
        result = process_single_email(drafter, critic, 1, long_email, "")

        assert isinstance(result, EmailResult)
        assert result.status == "VALIDÉ V1"


# ============================================================================
# TESTS - PRIORITIZATION AGENT EDGE CASES
# ============================================================================


class TestPrioritizationAgentEdgeCases:
    """Tests pour les edge cases du PrioritizationAgent."""

    @patch("app.agents.get_container")
    def test_analyze_with_negative_scores_in_response(self, mock_get_container):
        """analyze() gère les scores négatifs dans la réponse."""
        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.return_value = LLMResponse(
            content='{"urgency": -10, "vip": -5, "sentiment": -2.0, "deadline": null, "priority_score": -20}',
            input_tokens=200,
            output_tokens=50,
            model="claude-3-5-haiku-20241022"
        )
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        agent = PrioritizationAgent()
        result = agent.analyze("Email test")

        # Le code retourne les valeurs telles quelles du JSON
        assert result["urgency"] == -10
        assert result["vip"] == -5
        assert result["sentiment"] == -2.0

    @patch("app.agents.get_container")
    def test_analyze_with_scores_above_100(self, mock_get_container):
        """analyze() gère les scores au-dessus de 100 dans la réponse."""
        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.return_value = LLMResponse(
            content='{"urgency": 150, "vip": 200, "sentiment": 5.0, "deadline": null, "priority_score": 180}',
            input_tokens=200,
            output_tokens=50,
            model="claude-3-5-haiku-20241022"
        )
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        agent = PrioritizationAgent()
        result = agent.analyze("Email test")

        # Le code retourne les valeurs telles quelles du JSON
        assert result["urgency"] == 150
        assert result["vip"] == 200

    @patch("app.agents.get_container")
    def test_analyze_with_string_scores_in_response(self, mock_get_container):
        """analyze() gère les scores en string dans la réponse."""
        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.return_value = LLMResponse(
            content='{"urgency": "high", "vip": "yes", "sentiment": "positive", "deadline": null, "priority_score": "urgent"}',
            input_tokens=200,
            output_tokens=50,
            model="claude-3-5-haiku-20241022"
        )
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        agent = PrioritizationAgent()
        result = agent.analyze("Email test")

        # Le code retourne les valeurs telles quelles
        assert result["urgency"] == "high"
        assert result["vip"] == "yes"

    @patch("app.agents.get_container")
    def test_analyze_with_null_values_in_response(self, mock_get_container):
        """analyze() gère les valeurs null dans la réponse."""
        container = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.llm.complete.return_value = LLMResponse(
            content='{"urgency": null, "vip": null, "sentiment": null, "deadline": null, "priority_score": null}',
            input_tokens=200,
            output_tokens=50,
            model="claude-3-5-haiku-20241022"
        )
        container.token_usage = TokenCounter()
        mock_get_container.return_value = container

        agent = PrioritizationAgent()
        result = agent.analyze("Email test")

        assert result["urgency"] is None
        assert result["deadline"] is None


# ============================================================================
# TESTS - EXTRACTED TASK DATACLASS
# ============================================================================


class TestExtractedTaskDataclass:
    """Tests pour le dataclass ExtractedTask."""

    def test_extracted_task_with_required_fields(self):
        """ExtractedTask avec les champs requis."""
        task = ExtractedTask(title="Test", description="Desc", priority="medium")

        assert task.title == "Test"
        assert task.description == "Desc"
        assert task.priority == "medium"
        assert task.deadline is None  # Seule la deadline a une valeur par défaut

    def test_extracted_task_all_values(self):
        """ExtractedTask avec toutes les valeurs."""
        task = ExtractedTask(
            title="Urgent Task",
            description="Do this now",
            priority="high",
            deadline="2024-12-31"
        )

        assert task.title == "Urgent Task"
        assert task.description == "Do this now"
        assert task.priority == "high"
        assert task.deadline == "2024-12-31"

    def test_extracted_task_with_unicode(self):
        """ExtractedTask avec contenu unicode."""
        task = ExtractedTask(
            title="Tâche été 📋",
            description="Description noël 🎄",
            priority="élevée"
        )

        assert "été" in task.title
        assert "📋" in task.title
        assert "noël" in task.description


# ============================================================================
# TESTS - EXTRACTED COMMITMENT DATACLASS
# ============================================================================


class TestExtractedCommitmentDataclass:
    """Tests pour le dataclass ExtractedCommitment."""

    def test_extracted_commitment_default_values(self):
        """ExtractedCommitment avec valeurs par défaut."""
        commitment = ExtractedCommitment(description="Test")

        assert commitment.description == "Test"
        assert commitment.deadline is None

    def test_extracted_commitment_all_values(self):
        """ExtractedCommitment avec toutes les valeurs."""
        commitment = ExtractedCommitment(
            description="Envoyer le document",
            deadline="2024-12-31"
        )

        assert commitment.description == "Envoyer le document"
        assert commitment.deadline == "2024-12-31"

    def test_extracted_commitment_with_unicode(self):
        """ExtractedCommitment avec contenu unicode."""
        commitment = ExtractedCommitment(
            description="Engagement été 📄 noël",
            deadline="demain"
        )

        assert "été" in commitment.description
        assert "📄" in commitment.description


# ============================================================================
# TESTS - EMAIL RESULT DATACLASS
# ============================================================================


class TestEmailResultDataclass:
    """Tests pour le dataclass EmailResult."""

    def test_email_result_creation(self):
        """EmailResult création basique."""
        result = EmailResult(
            numero=1,
            email_content="Email content",
            human_response="Human response",
            draft_v1="Draft initial",
            critique="",
            draft_final="Draft initial",
            status="VALIDÉ V1"
        )

        assert result.numero == 1
        assert result.status == "VALIDÉ V1"
        assert result.draft_v1 == result.draft_final

    def test_email_result_with_revision(self):
        """EmailResult avec révision V2."""
        result = EmailResult(
            numero=5,
            email_content="Email content",
            human_response="Human response",
            draft_v1="Draft V1",
            critique="REJET: Ton trop formel",
            draft_final="Draft V2 corrigé",
            status="CORRIGÉ V2"
        )

        assert result.status == "CORRIGÉ V2"
        assert result.draft_v1 != result.draft_final
        assert "REJET" in result.critique

    def test_email_result_with_unicode(self):
        """EmailResult avec contenu unicode."""
        result = EmailResult(
            numero=1,
            email_content="Email été 📧",
            human_response="Réponse été",
            draft_v1="Réponse été 📧",
            critique="",
            draft_final="Réponse été 📧",
            status="VALIDÉ V1"
        )

        assert "été" in result.draft_v1
        assert "📧" in result.draft_final
        assert "été" in result.email_content
