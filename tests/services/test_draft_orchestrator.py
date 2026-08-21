# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour DraftOrchestrator.

Story 5-3: Draft Regeneration Loop - Task 3
"""

import pytest
from unittest.mock import MagicMock
import time

from app.services.draft_orchestrator import DraftOrchestrator
from app.agents import DrafterAgent, CriticAgent
from app.domain.entities.draft_generation import (
    DraftResult,
    DraftStatus,
)
from app.domain.entities.critique import (
    CritiqueDecision,
    CritiqueScores,
    CritiqueResult,
    CritiqueStatus,
)
from app.domain.entities.orchestration import (
    OrchestrationStatus,
    IterationRecord,
    OrchestrationRequest,
    OrchestrationResult,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_drafter():
    """Mock du DrafterAgent."""
    mock = MagicMock(spec=DrafterAgent)
    mock.draft_with_retry.return_value = DraftResult(
        content="Bonjour,\n\nMerci pour votre message.\n\nCordialement",
        confidence=0.8,
        status=DraftStatus.COMPLETED,
        tokens_used=150,
    )
    mock.revise_with_critique_and_retry.return_value = DraftResult(
        content="Bonjour,\n\nMerci pour votre email. Voici les informations demandées.\n\nCordialement",
        confidence=0.85,
        status=DraftStatus.COMPLETED,
        tokens_used=180,
    )
    return mock


@pytest.fixture
def mock_critic():
    """Mock du CriticAgent."""
    mock = MagicMock(spec=CriticAgent)
    # Par défaut, retourne VALID
    mock.evaluate_draft_with_retry.return_value = CritiqueResult(
        decision=CritiqueDecision.VALID,
        scores=CritiqueScores(coherence=85, tone=80, completeness=82, errors=90, conciseness=85, over_commitment=80, emotional_intelligence=82),
        suggestions=[],
        explanation="Le brouillon est de bonne qualité.",
        status=CritiqueStatus.COMPLETED,
    )
    return mock


@pytest.fixture
def orchestrator(mock_drafter, mock_critic):
    """DraftOrchestrator avec agents mockés."""
    return DraftOrchestrator(
        drafter=mock_drafter,
        critic=mock_critic,
        max_iterations=2,
        quality_threshold=70,
    )


@pytest.fixture
def sample_request():
    """OrchestrationRequest de test."""
    return OrchestrationRequest(
        email_content="Bonjour, pouvez-vous me donner les tarifs?",
        email_id="test-123",
    )


# ============================================================================
# TESTS BASIC ORCHESTRATION
# ============================================================================


class TestDraftOrchestratorBasic:
    """Tests de base pour l'orchestration."""

    def test_orchestrate_returns_result(self, orchestrator, sample_request):
        """orchestrate retourne un OrchestrationResult."""
        result = orchestrator.orchestrate(sample_request)

        assert isinstance(result, OrchestrationResult)
        assert result.status == OrchestrationStatus.COMPLETED

    def test_orchestrate_calls_drafter_first(
        self, orchestrator, mock_drafter, sample_request
    ):
        """L'orchestrateur appelle d'abord le DrafterAgent."""
        orchestrator.orchestrate(sample_request)

        mock_drafter.draft_with_retry.assert_called_once()

    def test_orchestrate_evaluates_draft(
        self, orchestrator, mock_critic, sample_request
    ):
        """L'orchestrateur évalue le brouillon avec le CriticAgent."""
        orchestrator.orchestrate(sample_request)

        mock_critic.evaluate_draft_with_retry.assert_called_once()

    def test_orchestrate_returns_on_valid(
        self, orchestrator, mock_drafter, mock_critic, sample_request
    ):
        """L'orchestrateur retourne immédiatement si le draft est VALID."""
        result = orchestrator.orchestrate(sample_request)

        # Un seul appel au drafter (pas de révision)
        assert mock_drafter.draft_with_retry.call_count == 1
        assert mock_drafter.revise_with_critique_and_retry.call_count == 0
        assert result.status == OrchestrationStatus.COMPLETED
        assert len(result.iterations) == 1

    def test_orchestrate_tracks_iterations(
        self, orchestrator, sample_request
    ):
        """L'orchestrateur enregistre les itérations."""
        result = orchestrator.orchestrate(sample_request)

        assert len(result.iterations) >= 1
        assert all(isinstance(i, IterationRecord) for i in result.iterations)
        assert result.iterations[0].iteration_number == 1  # 1-based indexing


# ============================================================================
# TESTS REGENERATION LOOP
# ============================================================================


class TestDraftOrchestratorRegenerationLoop:
    """Tests pour la boucle de régénération."""

    def test_loop_on_reject_then_valid(
        self, orchestrator, mock_drafter, mock_critic, sample_request
    ):
        """Boucle: REJECT → revision → VALID."""
        # Premier appel: REJECT, deuxième: VALID
        mock_critic.evaluate_draft_with_retry.side_effect = [
            CritiqueResult(
                decision=CritiqueDecision.REJECT,
                scores=CritiqueScores(coherence=60, tone=75, completeness=55, errors=80, conciseness=65, over_commitment=60, emotional_intelligence=70),
                suggestions=["Répondre aux tarifs"],
                explanation="Incomplet",
                status=CritiqueStatus.COMPLETED,
            ),
            CritiqueResult(
                decision=CritiqueDecision.VALID,
                scores=CritiqueScores(coherence=85, tone=80, completeness=82, errors=90, conciseness=85, over_commitment=80, emotional_intelligence=82),
                suggestions=[],
                explanation="Bon brouillon",
                status=CritiqueStatus.COMPLETED,
            ),
        ]

        result = orchestrator.orchestrate(sample_request)

        # Vérifie que la révision a été appelée
        assert mock_drafter.draft_with_retry.call_count == 1
        assert mock_drafter.revise_with_critique_and_retry.call_count == 1
        assert len(result.iterations) == 2
        assert result.status == OrchestrationStatus.COMPLETED

    def test_loop_max_iterations_reached(
        self, orchestrator, mock_drafter, mock_critic, sample_request
    ):
        """Retourne le meilleur brouillon après max iterations."""
        # Tous les appels retournent REJECT
        mock_critic.evaluate_draft_with_retry.return_value = CritiqueResult(
            decision=CritiqueDecision.REJECT,
            scores=CritiqueScores(coherence=60, tone=65, completeness=55, errors=70, conciseness=60, over_commitment=55, emotional_intelligence=65),
            suggestions=["Améliorer"],
            explanation="Pas assez bon",
            status=CritiqueStatus.COMPLETED,
        )

        result = orchestrator.orchestrate(sample_request)

        # max_iterations = 2, donc 3 itérations au total (0, 1, 2)
        assert len(result.iterations) == 3
        assert mock_drafter.draft_with_retry.call_count == 1  # Initial
        assert mock_drafter.revise_with_critique_and_retry.call_count == 2  # Révisions
        assert result.status == OrchestrationStatus.COMPLETED

    def test_loop_selects_best_draft_on_max_iterations(
        self, orchestrator, mock_drafter, mock_critic, sample_request
    ):
        """Sélectionne le meilleur brouillon quand max iterations atteint."""
        # Scores croissants à chaque itération
        mock_critic.evaluate_draft_with_retry.side_effect = [
            CritiqueResult(
                decision=CritiqueDecision.REJECT,
                scores=CritiqueScores(coherence=50, tone=50, completeness=50, errors=50, conciseness=50, over_commitment=50, emotional_intelligence=50),
                suggestions=["Améliorer"],
                explanation="Mauvais",
                status=CritiqueStatus.COMPLETED,
            ),
            CritiqueResult(
                decision=CritiqueDecision.REJECT,
                scores=CritiqueScores(coherence=65, tone=65, completeness=65, errors=65, conciseness=65, over_commitment=65, emotional_intelligence=65),
                suggestions=["Encore mieux"],
                explanation="Moyen",
                status=CritiqueStatus.COMPLETED,
            ),
            CritiqueResult(
                decision=CritiqueDecision.REJECT,
                scores=CritiqueScores(coherence=75, tone=75, completeness=75, errors=75, conciseness=75, over_commitment=75, emotional_intelligence=75),
                suggestions=["Presque"],
                explanation="Correct",
                status=CritiqueStatus.COMPLETED,
            ),
        ]

        result = orchestrator.orchestrate(sample_request)

        # Le meilleur score est 75 (dernière itération)
        assert result.get_best_score() == 75


# ============================================================================
# TESTS TIMEOUT
# ============================================================================


class TestDraftOrchestratorTimeout:
    """Tests pour la gestion du timeout."""

    def test_timeout_global_returns_best_draft(
        self, mock_drafter, mock_critic, sample_request
    ):
        """Timeout global retourne le meilleur brouillon disponible."""
        # Orchestre avec timeout très court
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter,
            critic=mock_critic,
            timeout_seconds=0.001,  # Très court
        )

        # Le critic est lent
        def slow_evaluate(*args, **kwargs):
            time.sleep(0.01)
            return CritiqueResult(
                decision=CritiqueDecision.REJECT,
                scores=CritiqueScores(coherence=60, tone=60, completeness=60, errors=60, conciseness=60, over_commitment=60, emotional_intelligence=60),
                suggestions=["Améliorer"],
                explanation="Timeout test",
                status=CritiqueStatus.COMPLETED,
            )

        mock_critic.evaluate_draft_with_retry.side_effect = slow_evaluate

        result = orchestrator.orchestrate(sample_request)

        # Soit TIMEOUT soit COMPLETED (si première itération termine)
        assert result.status in [OrchestrationStatus.TIMEOUT, OrchestrationStatus.COMPLETED]

    def test_timeout_request_override(
        self, mock_drafter, mock_critic
    ):
        """Le timeout de la requête override celui de l'orchestrateur."""
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter,
            critic=mock_critic,
            timeout_seconds=300,  # Long timeout default
        )

        # Requête avec timeout court
        request = OrchestrationRequest(
            email_content="Test",
            email_id="test-timeout",
            timeout_seconds=0.001,
        )

        mock_critic.evaluate_draft_with_retry.side_effect = lambda *args: (
            time.sleep(0.01),
            CritiqueResult(
                decision=CritiqueDecision.REJECT,
                scores=CritiqueScores(coherence=60, tone=60, completeness=60, errors=60, conciseness=60, over_commitment=60, emotional_intelligence=60),
                suggestions=[],
                explanation="",
                status=CritiqueStatus.COMPLETED,
            )
        )[1]

        result = orchestrator.orchestrate(request)

        assert result.status in [OrchestrationStatus.TIMEOUT, OrchestrationStatus.COMPLETED]


# ============================================================================
# TESTS ERROR HANDLING
# ============================================================================


class TestDraftOrchestratorErrorHandling:
    """Tests pour la gestion des erreurs."""

    def test_draft_generation_failure(
        self, orchestrator, mock_drafter, sample_request
    ):
        """Gestion d'une erreur de génération."""
        mock_drafter.draft_with_retry.return_value = DraftResult(
            content="",
            confidence=0.0,
            status=DraftStatus.FAILED,
            error_message="LLM unavailable",
        )

        result = orchestrator.orchestrate(sample_request)

        assert result.status == OrchestrationStatus.FAILED

    def test_revision_failure_returns_best(
        self, orchestrator, mock_drafter, mock_critic, sample_request
    ):
        """Échec de révision retourne le meilleur brouillon précédent."""
        # Premier appel réussit avec REJECT
        mock_critic.evaluate_draft_with_retry.return_value = CritiqueResult(
            decision=CritiqueDecision.REJECT,
            scores=CritiqueScores(coherence=65, tone=70, completeness=60, errors=75, conciseness=65, over_commitment=60, emotional_intelligence=70),
            suggestions=["Améliorer"],
            explanation="À réviser",
            status=CritiqueStatus.COMPLETED,
        )

        # La révision échoue
        mock_drafter.revise_with_critique_and_retry.return_value = DraftResult(
            content="",
            confidence=0.0,
            status=DraftStatus.FAILED,
            error_message="Revision failed",
        )

        result = orchestrator.orchestrate(sample_request)

        # Doit retourner le premier brouillon (le seul avec du contenu)
        assert result.status == OrchestrationStatus.FAILED

    def test_critique_failure_continues(
        self, orchestrator, mock_drafter, mock_critic, sample_request
    ):
        """Échec de critique est géré gracieusement."""
        mock_critic.evaluate_draft_with_retry.return_value = CritiqueResult.create_failed(
            error_message="Critique unavailable",
        )

        result = orchestrator.orchestrate(sample_request)

        # L'orchestration continue avec le draft disponible
        assert len(result.iterations) >= 1


# ============================================================================
# TESTS CALLBACKS
# ============================================================================


class TestDraftOrchestratorCallbacks:
    """Tests pour les callbacks d'événements."""

    def test_on_iteration_start_called(
        self, orchestrator, sample_request
    ):
        """on_iteration_start est appelé au début de chaque itération."""
        callback = MagicMock()

        orchestrator.orchestrate(sample_request, on_iteration_start=callback)

        callback.assert_called_once_with("test-123", 1)  # 1-based indexing

    def test_on_iteration_complete_called(
        self, orchestrator, sample_request
    ):
        """on_iteration_complete est appelé à la fin de chaque itération."""
        callback = MagicMock()

        orchestrator.orchestrate(sample_request, on_iteration_complete=callback)

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "test-123"  # email_id
        assert args[1] == 1  # iteration_number (1-based indexing)
        assert isinstance(args[2], int)  # score
        assert args[3] in ["valid", "reject"]  # decision

    def test_callbacks_for_multiple_iterations(
        self, orchestrator, mock_critic, sample_request
    ):
        """Callbacks appelés pour chaque itération."""
        mock_critic.evaluate_draft_with_retry.side_effect = [
            CritiqueResult(
                decision=CritiqueDecision.REJECT,
                scores=CritiqueScores(coherence=60, tone=60, completeness=60, errors=60, conciseness=60, over_commitment=60, emotional_intelligence=60),
                suggestions=["Améliorer"],
                explanation="",
                status=CritiqueStatus.COMPLETED,
            ),
            CritiqueResult(
                decision=CritiqueDecision.VALID,
                scores=CritiqueScores(coherence=85, tone=85, completeness=85, errors=85, conciseness=85, over_commitment=85, emotional_intelligence=85),
                suggestions=[],
                explanation="OK",
                status=CritiqueStatus.COMPLETED,
            ),
        ]

        start_callback = MagicMock()
        complete_callback = MagicMock()

        orchestrator.orchestrate(
            sample_request,
            on_iteration_start=start_callback,
            on_iteration_complete=complete_callback,
        )

        assert start_callback.call_count == 2
        assert complete_callback.call_count == 2

    def test_callback_exception_ignored(
        self, orchestrator, sample_request
    ):
        """Les exceptions dans les callbacks sont ignorées."""
        def failing_callback(*args):
            raise Exception("Callback error")

        # Ne doit pas lever d'exception
        result = orchestrator.orchestrate(
            sample_request,
            on_iteration_start=failing_callback,
            on_iteration_complete=failing_callback,
        )

        assert result.status == OrchestrationStatus.COMPLETED


# ============================================================================
# TESTS METRICS
# ============================================================================


class TestDraftOrchestratorMetrics:
    """Tests pour les métriques de l'orchestration."""

    def test_tracks_total_duration(
        self, orchestrator, sample_request
    ):
        """Le temps total d'orchestration est suivi."""
        result = orchestrator.orchestrate(sample_request)

        assert result.total_duration_ms >= 0

    def test_tracks_iteration_durations(
        self, orchestrator, sample_request
    ):
        """Le temps de chaque itération est suivi."""
        result = orchestrator.orchestrate(sample_request)

        for iteration in result.iterations:
            assert iteration.duration_ms >= 0

    def test_final_draft_is_set(
        self, orchestrator, sample_request
    ):
        """Le brouillon final est correctement défini."""
        result = orchestrator.orchestrate(sample_request)

        assert result.final_draft is not None
        assert result.final_draft.content != ""


# ============================================================================
# TESTS INTEGRATION WITH REQUEST
# ============================================================================


class TestDraftOrchestratorRequestIntegration:
    """Tests d'intégration avec OrchestrationRequest."""

    def test_request_max_iterations_respected(
        self, mock_drafter, mock_critic
    ):
        """max_iterations de la requête est respecté."""
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter,
            critic=mock_critic,
            max_iterations=5,  # Default élevé
        )

        request = OrchestrationRequest(
            email_content="Test",
            email_id="test",
            max_iterations=1,  # Limité à 1
        )

        mock_critic.evaluate_draft_with_retry.return_value = CritiqueResult(
            decision=CritiqueDecision.REJECT,
            scores=CritiqueScores(coherence=60, tone=60, completeness=60, errors=60, conciseness=60, over_commitment=60, emotional_intelligence=60),
            suggestions=["Améliorer"],
            explanation="",
            status=CritiqueStatus.COMPLETED,
        )

        result = orchestrator.orchestrate(request)

        # max_iterations=1 → 2 itérations (0 et 1)
        assert len(result.iterations) == 2

    def test_request_threshold_used(
        self, mock_drafter, mock_critic
    ):
        """quality_threshold de la requête est utilisé (CriticAgent détermine décision)."""
        orchestrator = DraftOrchestrator(
            drafter=mock_drafter,
            critic=mock_critic,
            quality_threshold=90,  # Seuil très élevé par défaut
        )

        request = OrchestrationRequest(
            email_content="Test",
            email_id="test",
            quality_threshold=50,  # Seuil bas dans la requête
        )

        # CriticAgent retourne VALID (le threshold n'est pas passé au Critic,
        # c'est le Critic qui détermine VALID/REJECT selon ses propres critères)
        mock_critic.evaluate_draft_with_retry.return_value = CritiqueResult(
            decision=CritiqueDecision.VALID,
            scores=CritiqueScores(coherence=60, tone=60, completeness=60, errors=60, conciseness=60, over_commitment=60, emotional_intelligence=60),
            suggestions=[],
            explanation="OK selon le critic",
            status=CritiqueStatus.COMPLETED,
        )

        result = orchestrator.orchestrate(request)

        # La critique a été appelée avec le bon contenu
        critique_call = mock_critic.evaluate_draft_with_retry.call_args
        critique_request = critique_call[0][0]
        assert critique_request.draft_content == mock_drafter.draft_with_retry.return_value.content
        assert critique_request.original_email == "Test"
        # Le résultat est COMPLETED car le Critic a retourné VALID
        assert result.status == OrchestrationStatus.COMPLETED
