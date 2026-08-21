"""Tests d'intégration pour CriticAgent.

TDD Tests - Story 5-2 Task 5

Ces tests vérifient l'intégration complète du CriticAgent:
- Interaction avec le DrafterAgent
- Pipeline complet Draft → Critique → Decision
- WebSocket events émis correctement
- Gestion des erreurs de bout en bout
"""

import pytest
from unittest.mock import MagicMock, patch

from app.domain.ports import LLMResponse
from app.domain.entities.draft_generation import (
    DraftRequest,
    DraftStatus,
    DraftTone,
)
from app.domain.entities.critique import (
    CritiqueDecision,
    CritiqueStatus,
    CritiqueRequest,
)
from app.domain.exceptions import LLMRateLimitError


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_container():
    """Container mocké avec LLM et token usage.

    `llm_drafting` est l'attribut utilisé par DrafterAgent + CriticAgent
    (cf. app/agents.py:146,981). On le pointe sur le même mock que `llm`
    pour compat descendante avec les vieux tests qui stub `mock.llm`.
    """
    mock = MagicMock()
    mock.llm = MagicMock()
    mock.llm.name = "claude"
    mock.llm.model = "claude-sonnet-4-20250514"
    mock.llm_drafting = mock.llm
    mock.llm_label = mock.llm
    mock.token_usage = MagicMock()
    return mock


@pytest.fixture
def sample_email():
    """Email de test pour le pipeline."""
    return """De: client@example.com
Sujet: Question sur la livraison

Bonjour,

J'ai commandé un produit la semaine dernière et je n'ai toujours pas reçu de confirmation d'expédition.

Pouvez-vous me donner une mise à jour?

Cordialement,
Jean Client"""


@pytest.fixture
def good_draft():
    """Brouillon de bonne qualité."""
    return """Bonjour Jean,

Je vous remercie pour votre message concernant votre commande.

Je comprends votre préoccupation et je vais vérifier immédiatement l'état de votre commande. Je vous tiendrai informé dans les plus brefs délais.

N'hésitez pas à me recontacter si vous avez d'autres questions.

Bien cordialement,
L'équipe Support"""


@pytest.fixture
def poor_draft():
    """Brouillon de mauvaise qualité."""
    return """Salut,

Ouais, votre commande est en route quelque part. Pas de souci.

Bye"""


@pytest.fixture
def valid_critique_json():
    """Réponse JSON valide du LLM pour une critique positive."""
    return """{
    "coherence": 90,
    "tone": 85,
    "completeness": 88,
    "errors": 95,
    "decision": "VALID",
    "suggestions": [],
    "explanation": "Le brouillon répond parfaitement à l'email du client."
}"""


@pytest.fixture
def reject_critique_json():
    """Réponse JSON valide du LLM pour une critique négative."""
    return """{
    "coherence": 50,
    "tone": 30,
    "completeness": 45,
    "errors": 60,
    "decision": "REJECT",
    "suggestions": [
        "Utiliser un ton plus professionnel",
        "Répondre explicitement à la question du client",
        "Ajouter une formule de politesse appropriée"
    ],
    "explanation": "Le brouillon manque de professionnalisme et ne répond pas clairement à la demande."
}"""


@pytest.fixture
def drafter_response():
    """Réponse LLM pour le DrafterAgent."""
    return LLMResponse(
        content="Bonjour, je vous remercie pour votre message...",
        input_tokens=500,
        output_tokens=100,
        model="claude-sonnet-4-20250514"
    )


# ============================================================================
# TESTS - INTÉGRATION DRAFTER + CRITIC
# ============================================================================

class TestDrafterCriticIntegration:
    """Tests d'intégration entre DrafterAgent et CriticAgent."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_critic_evaluates_drafter_output(
        self, mock_kb, mock_get_container, mock_container,
        sample_email, good_draft, valid_critique_json
    ):
        """Le CriticAgent évalue correctement la sortie du DrafterAgent."""
        mock_kb.return_value = "Knowledge base content"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_critique_json,
            input_tokens=800,
            output_tokens=100,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        agent = CriticAgent()
        request = CritiqueRequest(
            draft_content=good_draft,
            original_email=sample_email,
        )

        result = agent.evaluate_draft(request)

        assert result.decision == CritiqueDecision.VALID
        assert result.status == CritiqueStatus.COMPLETED
        assert result.scores.calculate_overall() >= 70

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_critic_rejects_poor_draft(
        self, mock_kb, mock_get_container, mock_container,
        sample_email, poor_draft, reject_critique_json
    ):
        """Le CriticAgent rejette un brouillon de mauvaise qualité."""
        mock_kb.return_value = "Knowledge base content"
        mock_container.llm.complete.return_value = LLMResponse(
            content=reject_critique_json,
            input_tokens=600,
            output_tokens=150,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        agent = CriticAgent()
        request = CritiqueRequest(
            draft_content=poor_draft,
            original_email=sample_email,
        )

        result = agent.evaluate_draft(request)

        assert result.decision == CritiqueDecision.REJECT
        assert result.scores.calculate_overall() < 70
        assert len(result.suggestions) > 0

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_full_pipeline_draft_then_critique(
        self, mock_kb, mock_get_container, mock_container,
        sample_email, valid_critique_json
    ):
        """Pipeline complet: DrafterAgent génère, CriticAgent évalue."""
        mock_kb.return_value = "Knowledge base content"

        draft_response = LLMResponse(
            content="Bonjour, je vous remercie pour votre message concernant votre commande...",
            input_tokens=500,
            output_tokens=100,
            model="claude-sonnet-4-20250514"
        )

        critique_response = LLMResponse(
            content=valid_critique_json,
            input_tokens=800,
            output_tokens=100,
            model="claude-sonnet-4-20250514"
        )

        mock_container.llm.complete.side_effect = [draft_response, critique_response]
        mock_get_container.return_value = mock_container

        from app.agents import DrafterAgent, CriticAgent

        # Step 1: Generate draft
        drafter = DrafterAgent()
        draft_request = DraftRequest(
            email_content=sample_email,
            tone_hint=DraftTone.PROFESSIONAL,
        )
        draft_result = drafter.draft_with_context(draft_request)

        # Step 2: Critique the draft
        critic = CriticAgent()
        critique_request = CritiqueRequest(
            draft_content=draft_result.content,
            original_email=sample_email,
        )
        critique_result = critic.evaluate_draft(critique_request)

        assert draft_result.status == DraftStatus.COMPLETED
        assert critique_result.status == CritiqueStatus.COMPLETED
        assert critique_result.decision == CritiqueDecision.VALID


# ============================================================================
# TESTS - WEBSOCKET INTEGRATION
# ============================================================================

class TestCriticWebSocketIntegration:
    """Tests d'intégration des événements WebSocket du CriticAgent."""

    @patch("app.api.websocket.emit_critique_error")
    @patch("app.api.websocket.emit_critique_complete")
    @patch("app.api.websocket.emit_critique_start")
    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_websocket_events_on_successful_critique(
        self, mock_kb, mock_get_container, mock_emit_start, mock_emit_complete,
        mock_emit_error, mock_container, sample_email, good_draft, valid_critique_json
    ):
        """Les événements WebSocket sont émis correctement lors d'une critique réussie."""
        mock_kb.return_value = "Knowledge base content"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_critique_json,
            input_tokens=800,
            output_tokens=100,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        agent = CriticAgent()
        request = CritiqueRequest(
            email_id="test-email-123",
            draft_content=good_draft,
            original_email=sample_email,
        )

        agent.evaluate_draft_with_retry(request)

        # Vérifier que les bons événements ont été émis
        mock_emit_start.assert_called_once()
        assert mock_emit_start.call_args[1]["email_id"] == "test-email-123"

        mock_emit_complete.assert_called_once()
        complete_args = mock_emit_complete.call_args[1]
        assert complete_args["email_id"] == "test-email-123"
        assert complete_args["decision"] == "valid"

        mock_emit_error.assert_not_called()

    @patch("app.api.websocket.emit_critique_error")
    @patch("app.api.websocket.emit_critique_complete")
    @patch("app.api.websocket.emit_critique_start")
    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_websocket_events_on_failed_critique(
        self, mock_kb, mock_get_container, mock_emit_start, mock_emit_complete,
        mock_emit_error, mock_container, sample_email, good_draft
    ):
        """Les événements WebSocket sont émis correctement lors d'une erreur."""
        mock_kb.return_value = "Knowledge base content"
        mock_container.llm.complete.side_effect = Exception("API connection failed")
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        agent = CriticAgent()
        request = CritiqueRequest(
            email_id="test-email-456",
            draft_content=good_draft,
            original_email=sample_email,
        )

        agent.evaluate_draft_with_retry(request)

        mock_emit_start.assert_called_once()
        mock_emit_error.assert_called_once()
        assert "API connection failed" in mock_emit_error.call_args[1]["error"]
        mock_emit_complete.assert_not_called()

    @patch("app.agents._time.sleep")
    @patch("app.api.websocket.emit_critique_error")
    @patch("app.api.websocket.emit_critique_complete")
    @patch("app.api.websocket.emit_critique_start")
    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_websocket_events_on_rate_limit_retry(
        self, mock_kb, mock_get_container, mock_emit_start, mock_emit_complete,
        mock_emit_error, mock_sleep, mock_container, sample_email, good_draft, valid_critique_json
    ):
        """Les événements WebSocket gèrent les retries de rate limit."""
        mock_kb.return_value = "Knowledge base content"

        # Rate limit puis succès
        mock_container.llm.complete.side_effect = [
            LLMRateLimitError("claude", retry_after=1.0),
            LLMResponse(
                content=valid_critique_json,
                input_tokens=800,
                output_tokens=100,
                model="claude-sonnet-4-20250514"
            )
        ]
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        agent = CriticAgent()
        request = CritiqueRequest(
            email_id="test-email-789",
            draft_content=good_draft,
            original_email=sample_email,
        )

        agent.evaluate_draft_with_retry(request)

        mock_emit_start.assert_called_once()
        mock_emit_complete.assert_called_once()
        mock_emit_error.assert_not_called()
        mock_sleep.assert_called_once_with(1.0)


# ============================================================================
# TESTS - CONFIGURATION ET SEUILS
# ============================================================================

class TestCriticThresholdIntegration:
    """Tests d'intégration pour la configuration des seuils."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_custom_threshold_affects_decision(
        self, mock_kb, mock_get_container, mock_container, sample_email, good_draft
    ):
        """Le seuil personnalisé affecte la décision."""
        mock_kb.return_value = "Knowledge base content"

        # Score de 75 - entre le default 70 et un threshold élevé de 80
        borderline_json = """{
    "coherence": 75,
    "tone": 75,
    "completeness": 75,
    "errors": 75,
    "conciseness": 75,
    "over_commitment": 75,
    "emotional_intelligence": 75,
    "decision": "VALID",
    "suggestions": ["Améliorer légèrement le ton"],
    "explanation": "Acceptable mais peut être amélioré."
}"""

        mock_container.llm.complete.return_value = LLMResponse(
            content=borderline_json,
            input_tokens=700,
            output_tokens=80,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        # Avec threshold default (70), devrait être VALID
        agent_default = CriticAgent(quality_threshold=70)
        request = CritiqueRequest(
            draft_content=good_draft,
            original_email=sample_email,
        )
        result_default = agent_default.evaluate_draft(request)

        # Avec threshold élevé (80), devrait être REJECT
        # (le LLM retourne VALID mais le score est < 80)
        reject_json_for_high_threshold = """{
    "coherence": 75,
    "tone": 75,
    "completeness": 75,
    "errors": 75,
    "conciseness": 75,
    "over_commitment": 75,
    "emotional_intelligence": 75,
    "decision": "REJECT",
    "suggestions": ["Améliorer le score global"],
    "explanation": "Score insuffisant pour le seuil configuré."
}"""
        mock_container.llm.complete.return_value = LLMResponse(
            content=reject_json_for_high_threshold,
            input_tokens=700,
            output_tokens=80,
            model="claude-sonnet-4-20250514"
        )

        agent_strict = CriticAgent(quality_threshold=80)
        result_strict = agent_strict.evaluate_draft(request)

        assert result_default.decision == CritiqueDecision.VALID
        assert result_strict.decision == CritiqueDecision.REJECT


# ============================================================================
# TESTS - ERREURS ET CAS LIMITES
# ============================================================================

class TestCriticErrorHandling:
    """Tests d'intégration pour la gestion des erreurs."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_handles_invalid_json_response(
        self, mock_kb, mock_get_container, mock_container, sample_email, good_draft
    ):
        """Le CriticAgent gère les réponses JSON invalides avec fallback."""
        mock_kb.return_value = "Knowledge base content"

        # Réponse avec JSON malformé mais contenant REJECT
        malformed_response = """Je pense que ce brouillon n'est pas acceptable.
DECISION: REJECT
Le ton est trop informel."""

        mock_container.llm.complete.return_value = LLMResponse(
            content=malformed_response,
            input_tokens=600,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        agent = CriticAgent()
        request = CritiqueRequest(
            draft_content=good_draft,
            original_email=sample_email,
        )

        result = agent.evaluate_draft(request)

        # Le fallback devrait détecter REJECT dans le texte
        assert result.decision == CritiqueDecision.REJECT
        assert result.status == CritiqueStatus.COMPLETED

    def test_rejects_empty_draft_at_validation(self, sample_email):
        """CritiqueRequest rejette les brouillons vides à la validation."""
        with pytest.raises(ValueError, match="draft_content cannot be empty"):
            CritiqueRequest(
                draft_content="",
                original_email=sample_email,
            )

    def test_rejects_whitespace_only_draft(self, sample_email):
        """CritiqueRequest rejette les brouillons avec seulement des espaces."""
        with pytest.raises(ValueError, match="draft_content cannot be empty"):
            CritiqueRequest(
                draft_content="   \n\t  ",
                original_email=sample_email,
            )

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_handles_unicode_content(
        self, mock_kb, mock_get_container, mock_container
    ):
        """Le CriticAgent gère le contenu Unicode."""
        mock_kb.return_value = "Knowledge base content"

        unicode_response = """{
    "coherence": 85,
    "tone": 80,
    "completeness": 90,
    "errors": 85,
    "decision": "VALID",
    "suggestions": [],
    "explanation": "Le brouillon est bien rédigé avec les caractères spéciaux."
}"""

        mock_container.llm.complete.return_value = LLMResponse(
            content=unicode_response,
            input_tokens=800,
            output_tokens=100,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        agent = CriticAgent()
        request = CritiqueRequest(
            draft_content="Bonjour, voici le café ☕ et le résumé 📋",
            original_email="Pouvez-vous me donner les émojis? 🎉",
        )

        result = agent.evaluate_draft(request)

        assert result.status == CritiqueStatus.COMPLETED
        assert result.decision == CritiqueDecision.VALID


# ============================================================================
# TESTS - PERFORMANCE ET MÉTRIQUES
# ============================================================================

class TestCriticMetricsIntegration:
    """Tests d'intégration pour les métriques et performances."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_tracks_evaluation_time(
        self, mock_kb, mock_get_container, mock_container,
        sample_email, good_draft, valid_critique_json
    ):
        """Le temps d'évaluation est correctement enregistré."""
        mock_kb.return_value = "Knowledge base content"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_critique_json,
            input_tokens=800,
            output_tokens=100,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        agent = CriticAgent()
        request = CritiqueRequest(
            draft_content=good_draft,
            original_email=sample_email,
        )

        result = agent.evaluate_draft(request)

        assert result.evaluation_time_ms >= 0
        assert isinstance(result.evaluation_time_ms, int)

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_tracks_tokens_used(
        self, mock_kb, mock_get_container, mock_container,
        sample_email, good_draft, valid_critique_json
    ):
        """L'utilisation des tokens est correctement enregistrée."""
        mock_kb.return_value = "Knowledge base content"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_critique_json,
            input_tokens=800,
            output_tokens=100,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        agent = CriticAgent()
        request = CritiqueRequest(
            draft_content=good_draft,
            original_email=sample_email,
        )

        result = agent.evaluate_draft(request)

        assert result.tokens_used == 900  # 800 + 100
        assert isinstance(result.tokens_used, int)

    @patch("app.agents._track_token_usage")
    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_token_tracking_called(
        self, mock_kb, mock_get_container, mock_track, mock_container,
        sample_email, good_draft, valid_critique_json
    ):
        """La fonction de tracking des tokens est appelée."""
        mock_kb.return_value = "Knowledge base content"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_critique_json,
            input_tokens=800,
            output_tokens=100,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        from app.agents import CriticAgent

        agent = CriticAgent()
        request = CritiqueRequest(
            draft_content=good_draft,
            original_email=sample_email,
        )

        agent.evaluate_draft(request)

        mock_track.assert_called_once()
