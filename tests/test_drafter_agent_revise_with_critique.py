# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour DrafterAgent.revise_with_critique().

Story 5-3: Draft Regeneration Loop - Task 2
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from app.agents import DrafterAgent
from app.domain.entities.draft_generation import (
    DraftRequest,
    DraftResult,
    DraftTone,
    DraftStatus,
)
from app.domain.entities.critique import (
    CritiqueDecision,
    CritiqueScores,
    CritiqueResult,
    CritiqueStatus,
)


# ============================================================================
# FIXTURES
# ============================================================================


@dataclass
class MockLLMResponse:
    """Mock d'une réponse LLM."""
    content: str
    input_tokens: int = 100
    output_tokens: int = 50
    model: str = "claude-3-5-sonnet-20241022"


@pytest.fixture
def mock_llm():
    """Mock du port LLM."""
    mock = MagicMock()
    mock.complete.return_value = MockLLMResponse(
        content="Bonjour,\n\nMerci pour votre email. Je vous réponds dès que possible.\n\nCordialement,\nJean"
    )
    return mock


@pytest.fixture
def drafter_agent(mock_llm):
    """DrafterAgent avec LLM mocké."""
    with patch("app.agents.get_container") as mock_container:
        mock_container.return_value.llm = mock_llm
        mock_container.return_value.llm_label = mock_llm
        agent = DrafterAgent()
        agent._llm = mock_llm
        return agent


@pytest.fixture
def sample_draft_request():
    """DraftRequest de test."""
    return DraftRequest(
        email_content="Bonjour, pouvez-vous me donner les tarifs de vos services?",
    )


@pytest.fixture
def sample_draft_request_with_context():
    """DraftRequest avec contexte complet."""
    from app.domain.entities.context_analysis import (
        ContextAnalysisResult,
    )
    from app.domain.entities.relationship_type import RelationshipType

    context_result = MagicMock(spec=ContextAnalysisResult)
    context_result.contact_context = "Client fidèle depuis 2 ans"
    context_result.relationship_type = RelationshipType.CLIENT
    context_result.style_hints = ["formel", "détaillé"]

    return DraftRequest(
        email_content="Bonjour, pouvez-vous me donner les tarifs de vos services?",
        context_result=context_result,
        style_context="Utiliser le vouvoiement",
        instructions="Proposer un rendez-vous",
    )


@pytest.fixture
def sample_critique_reject():
    """CritiqueResult avec décision REJECT."""
    return CritiqueResult(
        decision=CritiqueDecision.REJECT,
        scores=CritiqueScores(
            coherence=60,
            tone=75,
            completeness=45,
            errors=80,
            conciseness=70,
            over_commitment=85,
            emotional_intelligence=65,
        ),
        suggestions=[
            "Répondre à la question sur les tarifs",
            "Ajouter une formule de politesse d'ouverture",
            "Proposer un suivi personnalisé",
        ],
        explanation="Le brouillon ne répond pas à la demande de tarifs et manque de complétude.",
        status=CritiqueStatus.COMPLETED,
        evaluation_time_ms=150,
        draft_content="Bonjour,\n\nMerci pour votre message.\n\nCordialement",
    )


@pytest.fixture
def sample_critique_valid():
    """CritiqueResult avec décision VALID."""
    return CritiqueResult(
        decision=CritiqueDecision.VALID,
        scores=CritiqueScores(
            coherence=90,
            tone=85,
            completeness=88,
            errors=92,
            conciseness=88,
            over_commitment=90,
            emotional_intelligence=85,
        ),
        suggestions=[],
        explanation="Le brouillon est de bonne qualité.",
        status=CritiqueStatus.COMPLETED,
        evaluation_time_ms=100,
        draft_content="Bonjour,\n\nVoici nos tarifs...",
    )


# ============================================================================
# TESTS REVISE_WITH_CRITIQUE - BASIC FUNCTIONALITY
# ============================================================================


class TestReviseWithCritiqueBasic:
    """Tests de base pour revise_with_critique."""

    def test_revise_with_critique_returns_draft_result(
        self, drafter_agent, sample_draft_request, sample_critique_reject
    ):
        """revise_with_critique retourne un DraftResult."""
        result = drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )

        assert isinstance(result, DraftResult)
        assert result.content != ""
        assert result.status == DraftStatus.COMPLETED

    def test_revise_with_critique_calls_llm(
        self, drafter_agent, mock_llm, sample_draft_request, sample_critique_reject
    ):
        """revise_with_critique appelle le LLM avec les bons paramètres."""
        drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )

        mock_llm.complete.assert_called_once()
        call_args = mock_llm.complete.call_args

        # Vérifier que le system et user prompt sont passés
        assert "system" in call_args.kwargs
        assert "user" in call_args.kwargs
        assert "max_tokens" in call_args.kwargs

    def test_revise_with_critique_includes_scores_in_prompt(
        self, drafter_agent, mock_llm, sample_draft_request, sample_critique_reject
    ):
        """Le prompt de révision inclut les scores du Critic."""
        drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )

        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs["user"]

        # Vérifier que les scores sont inclus
        assert "60/100" in user_prompt  # coherence
        assert "75/100" in user_prompt  # tone
        assert "45/100" in user_prompt  # completeness
        assert "80/100" in user_prompt  # errors

    def test_revise_with_critique_includes_suggestions_in_prompt(
        self, drafter_agent, mock_llm, sample_draft_request, sample_critique_reject
    ):
        """Le prompt de révision inclut les suggestions du Critic."""
        drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )

        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs["user"]

        # Vérifier que les suggestions sont incluses
        assert "tarifs" in user_prompt.lower()
        assert "formule de politesse" in user_prompt.lower() or "Ajouter" in user_prompt

    def test_revise_with_critique_includes_previous_draft(
        self, drafter_agent, mock_llm, sample_draft_request, sample_critique_reject
    ):
        """Le prompt de révision inclut le brouillon précédent."""
        drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )

        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs["user"]

        # Vérifier que le brouillon précédent est inclus
        assert "Bonjour," in user_prompt
        assert "Cordialement" in user_prompt


# ============================================================================
# TESTS REVISE_WITH_CRITIQUE - AVEC CONTEXTE
# ============================================================================


class TestReviseWithCritiqueWithContext:
    """Tests avec contexte de relation et style."""

    def test_revise_with_context_uses_context_info(
        self, drafter_agent, mock_llm, sample_draft_request_with_context, sample_critique_reject
    ):
        """Le prompt inclut les informations de contexte."""
        drafter_agent.revise_with_critique(
            sample_draft_request_with_context, sample_critique_reject
        )

        call_args = mock_llm.complete.call_args
        system_prompt = call_args.kwargs["system"]

        # Vérifier que le contexte relationnel est inclus
        assert "Client fidèle" in system_prompt or "client" in system_prompt.lower()

    def test_revise_with_context_sets_context_used_true(
        self, drafter_agent, sample_draft_request_with_context, sample_critique_reject
    ):
        """context_used est True quand context_result est fourni."""
        result = drafter_agent.revise_with_critique(
            sample_draft_request_with_context, sample_critique_reject
        )

        assert result.context_used is True

    def test_revise_without_context_sets_context_used_false(
        self, drafter_agent, sample_draft_request, sample_critique_reject
    ):
        """context_used est False quand context_result n'est pas fourni."""
        result = drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )

        assert result.context_used is False

    def test_revise_with_context_has_higher_confidence(
        self, drafter_agent, sample_draft_request, sample_draft_request_with_context, sample_critique_reject
    ):
        """La confiance est plus élevée avec contexte."""
        result_no_context = drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )
        result_with_context = drafter_agent.revise_with_critique(
            sample_draft_request_with_context, sample_critique_reject
        )

        assert result_with_context.confidence > result_no_context.confidence

    def test_revise_includes_instructions_in_prompt(
        self, drafter_agent, mock_llm, sample_draft_request_with_context, sample_critique_reject
    ):
        """Les instructions supplémentaires sont incluses dans le prompt."""
        drafter_agent.revise_with_critique(
            sample_draft_request_with_context, sample_critique_reject
        )

        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs["user"]

        # Vérifier que les instructions sont incluses
        assert "Proposer un rendez-vous" in user_prompt


# ============================================================================
# TESTS REVISE_WITH_CRITIQUE - METRICS
# ============================================================================


class TestReviseWithCritiqueMetrics:
    """Tests des métriques générées."""

    def test_revise_tracks_generation_time(
        self, drafter_agent, sample_draft_request, sample_critique_reject
    ):
        """Le temps de génération est suivi."""
        result = drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )

        # Avec un mock, le temps peut être 0ms car très rapide
        # On vérifie juste que le champ existe et est >= 0
        assert result.generation_time_ms >= 0

    def test_revise_tracks_tokens_used(
        self, drafter_agent, sample_draft_request, sample_critique_reject
    ):
        """Les tokens utilisés sont suivis."""
        result = drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )

        # input_tokens (100) + output_tokens (50) = 150
        assert result.tokens_used == 150

    def test_revise_sets_status_completed(
        self, drafter_agent, sample_draft_request, sample_critique_reject
    ):
        """Le statut est COMPLETED après révision réussie."""
        result = drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )

        assert result.status == DraftStatus.COMPLETED

    def test_revise_sets_default_tone_professional(
        self, drafter_agent, sample_draft_request, sample_critique_reject
    ):
        """Le ton par défaut est PROFESSIONAL."""
        result = drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_reject
        )

        assert result.tone_detected == DraftTone.PROFESSIONAL


# ============================================================================
# TESTS REVISE_WITH_CRITIQUE - EDGE CASES
# ============================================================================


class TestReviseWithCritiqueEdgeCases:
    """Tests des cas limites."""

    def test_revise_with_empty_suggestions(
        self, drafter_agent, sample_draft_request, sample_critique_valid
    ):
        """Révision fonctionne avec des suggestions vides."""
        result = drafter_agent.revise_with_critique(
            sample_draft_request, sample_critique_valid
        )

        assert isinstance(result, DraftResult)
        assert result.status == DraftStatus.COMPLETED

    def test_revise_with_low_scores(
        self, drafter_agent, mock_llm, sample_draft_request
    ):
        """Révision fonctionne avec des scores très bas."""
        critique = CritiqueResult(
            decision=CritiqueDecision.REJECT,
            scores=CritiqueScores(
                coherence=20,
                tone=30,
                completeness=15,
                errors=25,
                conciseness=30,
                over_commitment=20,
                emotional_intelligence=25,
            ),
            suggestions=["Tout est à refaire"],
            explanation="Brouillon de très mauvaise qualité.",
            status=CritiqueStatus.COMPLETED,
            evaluation_time_ms=100,
            draft_content="Test",
        )

        result = drafter_agent.revise_with_critique(sample_draft_request, critique)

        assert result.status == DraftStatus.COMPLETED

        # Vérifier que les feedbacks CRITIQUE sont dans le prompt
        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs["user"]
        assert "CRITIQUE" in user_prompt

    def test_revise_with_none_draft_content(
        self, drafter_agent, sample_draft_request
    ):
        """Révision fonctionne quand draft_content est None dans la critique."""
        critique = CritiqueResult(
            decision=CritiqueDecision.REJECT,
            scores=CritiqueScores(
                coherence=60,
                tone=70,
                completeness=55,
                errors=75,
                conciseness=65,
                over_commitment=70,
                emotional_intelligence=60,
            ),
            suggestions=["Améliorer la complétude"],
            explanation="Brouillon incomplet.",
            status=CritiqueStatus.COMPLETED,
            evaluation_time_ms=100,
            draft_content=None,  # Pas de contenu
        )

        result = drafter_agent.revise_with_critique(sample_draft_request, critique)

        assert result.status == DraftStatus.COMPLETED


# ============================================================================
# TESTS REVISE_WITH_CRITIQUE_AND_RETRY
# ============================================================================


class TestReviseWithCritiqueAndRetry:
    """Tests pour revise_with_critique_and_retry avec rate limiting."""

    def test_retry_on_rate_limit(
        self, drafter_agent, mock_llm, sample_draft_request, sample_critique_reject
    ):
        """Retry automatique en cas de rate limit."""
        from app.domain.exceptions import LLMRateLimitError

        # Première tentative échoue, deuxième réussit
        mock_llm.complete.side_effect = [
            LLMRateLimitError("Rate limited", retry_after=0.1),
            MockLLMResponse(content="Brouillon révisé"),
        ]

        result = drafter_agent.revise_with_critique_and_retry(
            sample_draft_request, sample_critique_reject
        )

        assert result.status == DraftStatus.COMPLETED
        assert mock_llm.complete.call_count == 2

    def test_returns_rate_limited_after_max_retries(
        self, drafter_agent, mock_llm, sample_draft_request, sample_critique_reject
    ):
        """Retourne RATE_LIMITED après épuisement des retries."""
        from app.domain.exceptions import LLMRateLimitError

        mock_llm.complete.side_effect = LLMRateLimitError("Rate limited", retry_after=0.01)

        result = drafter_agent.revise_with_critique_and_retry(
            sample_draft_request, sample_critique_reject
        )

        assert result.status == DraftStatus.RATE_LIMITED
        assert result.retry_count == drafter_agent.max_retries

    def test_uses_retry_after_header(
        self, drafter_agent, mock_llm, sample_draft_request, sample_critique_reject
    ):
        """Utilise retry_after du header si disponible."""
        from app.domain.exceptions import LLMRateLimitError
        import time

        mock_llm.complete.side_effect = [
            LLMRateLimitError("Rate limited", retry_after=0.05),
            MockLLMResponse(content="Succès"),
        ]

        start = time.time()
        drafter_agent.revise_with_critique_and_retry(
            sample_draft_request, sample_critique_reject
        )
        elapsed = time.time() - start

        # Devrait avoir attendu au moins 0.05 secondes
        assert elapsed >= 0.04  # Marge pour l'exécution

    def test_exponential_backoff_without_retry_after(
        self, drafter_agent, mock_llm, sample_draft_request, sample_critique_reject
    ):
        """Utilise exponential backoff si pas de retry_after."""
        from app.domain.exceptions import LLMRateLimitError
        import time

        mock_llm.complete.side_effect = [
            LLMRateLimitError("Rate limited", retry_after=None),
            MockLLMResponse(content="Succès"),
        ]

        start = time.time()
        drafter_agent.revise_with_critique_and_retry(
            sample_draft_request, sample_critique_reject
        )
        elapsed = time.time() - start

        # Backoff initial = 0.5 * (2^0) = 0.5s
        # Mais on accepte une marge car le test peut être lent
        assert elapsed >= 0.4


# ============================================================================
# TESTS PROMPT GENERATION
# ============================================================================


class TestDrafterRevisionPrompt:
    """Tests pour get_drafter_revision_with_critique_prompt."""

    def test_prompt_includes_all_scores(self):
        """Le prompt inclut tous les scores."""
        from app.prompts import get_drafter_revision_with_critique_prompt

        prompt = get_drafter_revision_with_critique_prompt(
            email_content="Test email",
            previous_draft="Previous draft",
            coherence=80,
            tone=70,
            completeness=60,
            errors=90,
            decision="REJECT",
            suggestions=["Améliorer"],
            explanation="À améliorer",
        )

        assert "80/100" in prompt
        assert "70/100" in prompt
        assert "60/100" in prompt
        assert "90/100" in prompt

    def test_prompt_includes_feedback_for_low_scores(self):
        """Le prompt inclut des feedbacks pour les scores bas."""
        from app.prompts import get_drafter_revision_with_critique_prompt

        prompt = get_drafter_revision_with_critique_prompt(
            email_content="Test email",
            previous_draft="Previous draft",
            coherence=40,  # Très bas
            tone=65,       # Moyen
            completeness=80,  # OK
            errors=90,     # OK
            decision="REJECT",
            suggestions=["Améliorer"],
            explanation="À améliorer",
        )

        assert "CRITIQUE" in prompt  # Pour score < 50
        assert "à améliorer" in prompt  # Pour score < 70

    def test_prompt_calculates_overall_score(self):
        """Le prompt calcule le score global."""
        from app.prompts import get_drafter_revision_with_critique_prompt

        prompt = get_drafter_revision_with_critique_prompt(
            email_content="Test email",
            previous_draft="Previous draft",
            coherence=80,
            tone=70,
            completeness=60,
            errors=90,
            decision="REJECT",
            suggestions=["Améliorer"],
            explanation="À améliorer",
            conciseness=75,
            over_commitment=75,
            emotional_intelligence=75,
        )

        # Score global = (80 + 70 + 60 + 90 + 75 + 75 + 75) // 7 = 75
        assert "75/100" in prompt

    def test_prompt_formats_suggestions_list(self):
        """Le prompt formate la liste des suggestions."""
        from app.prompts import get_drafter_revision_with_critique_prompt

        prompt = get_drafter_revision_with_critique_prompt(
            email_content="Test email",
            previous_draft="Previous draft",
            coherence=70,
            tone=70,
            completeness=70,
            errors=70,
            decision="REJECT",
            suggestions=["Suggestion 1", "Suggestion 2", "Suggestion 3"],
            explanation="À améliorer",
        )

        assert "- Suggestion 1" in prompt
        assert "- Suggestion 2" in prompt
        assert "- Suggestion 3" in prompt

    def test_prompt_handles_empty_suggestions(self):
        """Le prompt gère les suggestions vides."""
        from app.prompts import get_drafter_revision_with_critique_prompt

        prompt = get_drafter_revision_with_critique_prompt(
            email_content="Test email",
            previous_draft="Previous draft",
            coherence=90,
            tone=90,
            completeness=90,
            errors=90,
            decision="VALID",
            suggestions=[],
            explanation="Tout est bon",
        )

        assert "Aucune suggestion spécifique" in prompt

    def test_prompt_includes_instructions_when_provided(self):
        """Le prompt inclut les instructions quand fournies."""
        from app.prompts import get_drafter_revision_with_critique_prompt

        prompt = get_drafter_revision_with_critique_prompt(
            email_content="Test email",
            previous_draft="Previous draft",
            coherence=70,
            tone=70,
            completeness=70,
            errors=70,
            decision="REJECT",
            suggestions=["Améliorer"],
            explanation="À améliorer",
            instructions="Utiliser un ton formel",
        )

        assert "Utiliser un ton formel" in prompt
        assert "INSTRUCTIONS DE L'UTILISATEUR" in prompt

    def test_prompt_excludes_instructions_section_when_none(self):
        """Le prompt exclut la section instructions quand None."""
        from app.prompts import get_drafter_revision_with_critique_prompt

        prompt = get_drafter_revision_with_critique_prompt(
            email_content="Test email",
            previous_draft="Previous draft",
            coherence=70,
            tone=70,
            completeness=70,
            errors=70,
            decision="REJECT",
            suggestions=["Améliorer"],
            explanation="À améliorer",
            instructions=None,
        )

        assert "INSTRUCTIONS DE L'UTILISATEUR" not in prompt
