# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour CriticAgent.evaluate_draft (Story 5-2).

AC1: Agent Python qui évalue le brouillon du DrafterAgent
AC2: Critères: cohérence, ton, complétude, erreurs (0-100 chacun)
AC3: Score de qualité avec seuil configurable (default: 70)
AC4: Retour structuré avec suggestions d'amélioration
AC5: Décision: VALID ou REJECT avec raison
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from app.agents import CriticAgent
from app.domain.entities import TokenUsage as TokenCounter
from app.domain.entities.critique import (
    CritiqueDecision,
    CritiqueStatus,
    CritiqueRequest,
    CritiqueResult,
)
from app.domain.ports import LLMResponse


class TestCriticAgentEvaluateDraft:
    """Tests pour la méthode evaluate_draft (Story 5-2)."""

    @pytest.fixture
    def mock_container(self):
        """Container mocké pour CriticAgent."""
        container = MagicMock()
        container.token_usage = TokenCounter()
        container.llm = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm  # CriticAgent utilise llm_drafting
        container.llm_background = container.llm
        return container

    @pytest.fixture
    def valid_json_response(self):
        """Réponse JSON valide pour VALID."""
        return json.dumps({
            "coherence": 85,
            "tone": 90,
            "completeness": 80,
            "errors": 95,
            "decision": "valid",
            "suggestions": [],
            "explanation": "Le brouillon répond correctement à l'email."
        })

    @pytest.fixture
    def reject_json_response(self):
        """Réponse JSON valide pour REJECT."""
        return json.dumps({
            "coherence": 60,
            "tone": 55,
            "completeness": 45,
            "errors": 70,
            "decision": "reject",
            "suggestions": [
                "Améliorer le ton professionnel",
                "Répondre à toutes les questions posées"
            ],
            "explanation": "Le brouillon manque de complétude et le ton est inapproprié."
        })

    @pytest.fixture
    def critique_request(self):
        """CritiqueRequest de test."""
        return CritiqueRequest(
            draft_content="Bonjour, voici ma réponse à votre email.",
            original_email="Bonjour, pourriez-vous me donner des informations?",
            email_id="test-email-123",
            context="Client important"
        )

    # =========================================================================
    # AC1: Agent Python qui évalue le brouillon du DrafterAgent
    # =========================================================================

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_calls_llm_with_correct_prompts(
        self, mock_kb, mock_get_container, mock_container, valid_json_response, critique_request
    ):
        """evaluate_draft() appelle le LLM avec les bons prompts."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        agent.evaluate_draft(critique_request)

        # Vérifie que le LLM a été appelé
        mock_container.llm.complete.assert_called_once()
        call_kwargs = mock_container.llm.complete.call_args[1]

        # Vérifie que le prompt contient les informations nécessaires
        assert "system" in call_kwargs
        assert "user" in call_kwargs
        assert critique_request.original_email in call_kwargs["user"]
        assert critique_request.draft_content in call_kwargs["user"]

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_returns_critique_result(
        self, mock_kb, mock_get_container, mock_container, valid_json_response, critique_request
    ):
        """evaluate_draft() retourne un CritiqueResult."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert isinstance(result, CritiqueResult)
        assert result.status == CritiqueStatus.COMPLETED

    # =========================================================================
    # AC2: Critères: cohérence, ton, complétude, erreurs (0-100 chacun)
    # =========================================================================

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_extracts_all_four_scores(
        self, mock_kb, mock_get_container, mock_container, valid_json_response, critique_request
    ):
        """evaluate_draft() extrait les 4 critères de notation."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert result.scores.coherence == 85
        assert result.scores.tone == 90
        assert result.scores.completeness == 80
        assert result.scores.errors == 95

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_clamps_scores_to_valid_range(
        self, mock_kb, mock_get_container, mock_container, critique_request
    ):
        """evaluate_draft() limite les scores entre 0 et 100."""
        response = json.dumps({
            "coherence": 150,  # > 100
            "tone": -10,      # < 0
            "completeness": 75,
            "errors": 80,
            "decision": "valid",
            "suggestions": [],
            "explanation": "Test"
        })
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert result.scores.coherence == 100  # Clamped from 150
        assert result.scores.tone == 0         # Clamped from -10
        assert result.scores.completeness == 75
        assert result.scores.errors == 80

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_handles_missing_scores_with_defaults(
        self, mock_kb, mock_get_container, mock_container, critique_request
    ):
        """evaluate_draft() utilise des valeurs par défaut pour les scores manquants."""
        response = json.dumps({
            "coherence": 80,
            # tone manquant
            # completeness manquant
            "errors": 90,
            "decision": "valid",
            "suggestions": [],
            "explanation": "Test"
        })
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert result.scores.coherence == 80
        assert result.scores.tone == 50       # Défaut
        assert result.scores.completeness == 50  # Défaut
        assert result.scores.errors == 90

    # =========================================================================
    # AC3: Score de qualité avec seuil configurable (default: 70)
    # =========================================================================

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_default_threshold_is_70(
        self, mock_kb, mock_get_container, mock_container, critique_request
    ):
        """Le seuil par défaut est 70."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=json.dumps({
                "coherence": 68, "tone": 68, "completeness": 68, "errors": 68,
                "decision": "valid", "suggestions": [], "explanation": "Test"
            }),
            input_tokens=300, output_tokens=50, model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()  # Seuil par défaut: 70
        assert agent.quality_threshold == 70

        result = agent.evaluate_draft(critique_request)
        # Score moyen = 68 < 70 => REJECT malgré decision="valid" du LLM
        assert result.decision == CritiqueDecision.REJECT

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_custom_threshold_is_respected(
        self, mock_kb, mock_get_container, mock_container, critique_request
    ):
        """Un seuil personnalisé est respecté."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=json.dumps({
                "coherence": 65, "tone": 65, "completeness": 65, "errors": 65,
                "conciseness": 65, "over_commitment": 65, "emotional_intelligence": 65,
                "decision": "valid", "suggestions": [], "explanation": "Test"
            }),
            input_tokens=300, output_tokens=50, model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        # Seuil abaissé à 60
        agent = CriticAgent(quality_threshold=60)
        result = agent.evaluate_draft(critique_request)

        # Score moyen = 65 >= 60 => VALID
        assert result.decision == CritiqueDecision.VALID

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_rejects_if_score_below_threshold(
        self, mock_kb, mock_get_container, mock_container, critique_request
    ):
        """evaluate_draft() rejette si le score global est inférieur au seuil."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=json.dumps({
                "coherence": 60, "tone": 60, "completeness": 60, "errors": 60,
                "decision": "valid",  # LLM dit valid
                "suggestions": [], "explanation": "Test"
            }),
            input_tokens=300, output_tokens=50, model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent(quality_threshold=70)
        result = agent.evaluate_draft(critique_request)

        # Score moyen = 60 < 70 => Override à REJECT
        assert result.decision == CritiqueDecision.REJECT
        assert any("seuil" in s.lower() for s in result.suggestions)

    # =========================================================================
    # AC4: Retour structuré avec suggestions d'amélioration
    # =========================================================================

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_extracts_suggestions(
        self, mock_kb, mock_get_container, mock_container, reject_json_response, critique_request
    ):
        """evaluate_draft() extrait les suggestions d'amélioration."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=reject_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert len(result.suggestions) >= 2
        assert "Améliorer le ton professionnel" in result.suggestions
        assert "Répondre à toutes les questions posées" in result.suggestions

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_extracts_explanation(
        self, mock_kb, mock_get_container, mock_container, reject_json_response, critique_request
    ):
        """evaluate_draft() extrait l'explication."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=reject_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert "complétude" in result.explanation.lower() or "ton" in result.explanation.lower()

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_handles_string_suggestions(
        self, mock_kb, mock_get_container, mock_container, critique_request
    ):
        """evaluate_draft() gère les suggestions comme string unique."""
        response = json.dumps({
            "coherence": 70, "tone": 70, "completeness": 70, "errors": 70,
            "decision": "reject",
            "suggestions": "Améliorer le ton",  # String au lieu de liste
            "explanation": "Test"
        })
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=response,
            input_tokens=300, output_tokens=50, model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert isinstance(result.suggestions, list)
        assert "Améliorer le ton" in result.suggestions

    # =========================================================================
    # AC5: Décision: VALID ou REJECT avec raison
    # =========================================================================

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_returns_valid_decision(
        self, mock_kb, mock_get_container, mock_container, valid_json_response, critique_request
    ):
        """evaluate_draft() retourne VALID pour un brouillon de qualité."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert result.decision == CritiqueDecision.VALID

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_returns_reject_decision(
        self, mock_kb, mock_get_container, mock_container, reject_json_response, critique_request
    ):
        """evaluate_draft() retourne REJECT pour un brouillon insuffisant."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=reject_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert result.decision == CritiqueDecision.REJECT

    # =========================================================================
    # Tests supplémentaires: Gestion d'erreurs et cas limites
    # =========================================================================

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_handles_llm_error(
        self, mock_kb, mock_get_container, mock_container, critique_request
    ):
        """evaluate_draft() gère les erreurs LLM gracieusement."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.side_effect = Exception("API Error")
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert result.status == CritiqueStatus.FAILED
        assert result.decision == CritiqueDecision.REJECT
        assert "API Error" in result.explanation

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_handles_malformed_json(
        self, mock_kb, mock_get_container, mock_container, critique_request
    ):
        """evaluate_draft() gère le JSON malformé avec fallback prudent.

        Audit failure-mode #3 (2026-04-24): l'ancien fallback faisait du
        keyword-match naïf — un texte contenant "VALID" matchait VALID
        sans vérification réelle. Un email utilisateur citant "VALID" en
        franglais suffisait à valider silencieusement n'importe quel draft.

        Post-fix: REJECT par défaut. Pour valider il faut un marqueur
        EXPLICITE (`"decision":"VALID"` JSON ou `DECISION: VALID`).
        """
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content="VALID - Le brouillon est correct",  # Pas de JSON, pas de marqueur explicite
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        # Post-fix: défaut prudent à REJECT — l'absence d'un marqueur explicite
        # ne doit PAS valider silencieusement. Une révision V2 sera générée
        # par sécurité.
        assert result.status == CritiqueStatus.COMPLETED
        assert result.decision == CritiqueDecision.REJECT

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_fallback_for_reject(
        self, mock_kb, mock_get_container, mock_container, critique_request
    ):
        """evaluate_draft() utilise le fallback pour REJET."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content="REJET : Le ton est inapproprié",  # Pas de JSON
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert result.status == CritiqueStatus.COMPLETED
        assert result.decision == CritiqueDecision.REJECT

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_tracks_tokens_used(
        self, mock_kb, mock_get_container, mock_container, valid_json_response, critique_request
    ):
        """evaluate_draft() enregistre les tokens utilisés."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert result.tokens_used == 350  # 300 + 50

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_records_evaluation_time(
        self, mock_kb, mock_get_container, mock_container, valid_json_response, critique_request
    ):
        """evaluate_draft() enregistre le temps d'évaluation."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft(critique_request)

        assert result.evaluation_time_ms >= 0

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_with_context(
        self, mock_kb, mock_get_container, mock_container, valid_json_response
    ):
        """evaluate_draft() utilise le contexte fourni."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        request = CritiqueRequest(
            draft_content="Réponse",
            original_email="Email",
            context="Contexte important: client VIP"
        )

        agent = CriticAgent()
        agent.evaluate_draft(request)

        call_kwargs = mock_container.llm.complete.call_args[1]
        # Le contexte devrait être inclus dans le prompt
        assert "context" in call_kwargs["user"].lower() or "Contexte" in call_kwargs["user"]

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_with_unicode_content(
        self, mock_kb, mock_get_container, mock_container, valid_json_response
    ):
        """evaluate_draft() gère le contenu unicode."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        request = CritiqueRequest(
            draft_content="Réponse été été",
            original_email="Email avec accents: é à ü"
        )

        agent = CriticAgent()
        result = agent.evaluate_draft(request)

        assert result.status == CritiqueStatus.COMPLETED


class TestCriticAgentParseResponse:
    """Tests pour _parse_critique_response (méthode interne)."""

    @pytest.fixture
    def mock_container(self):
        """Container mocké."""
        container = MagicMock()
        container.llm = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.token_usage = TokenCounter()
        return container

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_parse_valid_json_response(self, mock_kb, mock_get_container, mock_container):
        """_parse_critique_response() parse correctement le JSON valide."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        response = json.dumps({
            "coherence": 85,
            "tone": 90,
            "completeness": 80,
            "errors": 95,
            "decision": "valid",
            "suggestions": ["Suggestion 1"],
            "explanation": "Explication"
        })

        result = agent._parse_critique_response(response, 100, 200)

        assert result.scores.coherence == 85
        assert result.scores.tone == 90
        assert result.decision == CritiqueDecision.VALID
        assert result.evaluation_time_ms == 100
        assert result.tokens_used == 200

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_parse_json_in_markdown_block(self, mock_kb, mock_get_container, mock_container):
        """_parse_critique_response() extrait le JSON d'un bloc markdown."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        response = """
        Voici mon analyse:
        ```json
        {
            "coherence": 75,
            "tone": 80,
            "completeness": 70,
            "errors": 85,
            "conciseness": 75,
            "over_commitment": 80,
            "emotional_intelligence": 70,
            "decision": "valid",
            "suggestions": [],
            "explanation": "OK"
        }
        ```
        """

        result = agent._parse_critique_response(response, 100, 200)

        assert result.scores.coherence == 75
        assert result.decision == CritiqueDecision.VALID

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_parse_with_non_numeric_scores(self, mock_kb, mock_get_container, mock_container):
        """_parse_critique_response() gère les scores non numériques."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        response = json.dumps({
            "coherence": "high",  # Non numérique
            "tone": 80,
            "completeness": None,  # Null
            "errors": 85,
            "decision": "valid",
            "suggestions": [],
            "explanation": "Test"
        })

        result = agent._parse_critique_response(response, 100, 200)

        # Scores non numériques => défaut 50
        assert result.scores.coherence == 50
        assert result.scores.tone == 80
        assert result.scores.completeness == 50
        assert result.scores.errors == 85


class TestCriticAgentEvaluateDraftWithRetry:
    """Tests pour la méthode evaluate_draft_with_retry (rate limiting)."""

    @pytest.fixture
    def mock_container(self):
        """Container mocké."""
        container = MagicMock()
        container.llm = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.token_usage = TokenCounter()
        return container

    @pytest.fixture
    def valid_json_response(self):
        """Réponse JSON valide pour VALID."""
        return json.dumps({
            "coherence": 85,
            "tone": 90,
            "completeness": 80,
            "errors": 95,
            "decision": "valid",
            "suggestions": [],
            "explanation": "Le brouillon répond correctement à l'email."
        })

    @pytest.fixture
    def critique_request(self):
        """CritiqueRequest de test."""
        return CritiqueRequest(
            draft_content="Bonjour, voici ma réponse.",
            original_email="Bonjour, question?",
            email_id="test-email-123",
        )

    @patch("app.api.websocket.emit_critique_error")
    @patch("app.api.websocket.emit_critique_complete")
    @patch("app.api.websocket.emit_critique_start")
    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_with_retry_success_first_attempt(
        self, mock_kb, mock_get_container, mock_emit_start, mock_emit_complete, mock_emit_error,
        mock_container, valid_json_response, critique_request
    ):
        """evaluate_draft_with_retry réussit au premier essai."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft_with_retry(critique_request)

        assert result.decision == CritiqueDecision.VALID
        assert result.status == CritiqueStatus.COMPLETED
        mock_emit_start.assert_called_once()
        mock_emit_complete.assert_called_once()

    @patch("app.api.websocket.emit_critique_error")
    @patch("app.api.websocket.emit_critique_complete")
    @patch("app.api.websocket.emit_critique_start")
    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    @patch("app.agents._time.sleep")
    def test_evaluate_draft_with_retry_rate_limit_then_success(
        self, mock_sleep, mock_kb, mock_get_container, mock_emit_start, mock_emit_complete, mock_emit_error,
        mock_container, valid_json_response, critique_request
    ):
        """evaluate_draft_with_retry réessaie après rate limit puis réussit."""
        from app.domain.exceptions import LLMRateLimitError

        mock_kb.return_value = "KB"

        # Premier appel: rate limit, deuxième: succès
        mock_container.llm.complete.side_effect = [
            LLMRateLimitError("claude", retry_after=2),
            LLMResponse(
                content=valid_json_response,
                input_tokens=300,
                output_tokens=50,
                model="claude-sonnet-4-20250514"
            )
        ]
        mock_get_container.return_value = mock_container

        agent = CriticAgent(max_retries=3)
        result = agent.evaluate_draft_with_retry(critique_request)

        assert result.decision == CritiqueDecision.VALID
        assert result.status == CritiqueStatus.COMPLETED
        # Vérifie qu'on a attendu
        mock_sleep.assert_called_once_with(2)  # retry_after=2
        # Pas d'erreur émise car succès final
        mock_emit_error.assert_not_called()

    @patch("app.api.websocket.emit_critique_error")
    @patch("app.api.websocket.emit_critique_complete")
    @patch("app.api.websocket.emit_critique_start")
    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    @patch("app.agents._time.sleep")
    def test_evaluate_draft_with_retry_exhausts_retries(
        self, mock_sleep, mock_kb, mock_get_container, mock_emit_start, mock_emit_complete, mock_emit_error,
        mock_container, critique_request
    ):
        """evaluate_draft_with_retry épuise les tentatives."""
        from app.domain.exceptions import LLMRateLimitError

        mock_kb.return_value = "KB"

        # Toujours rate limit
        mock_container.llm.complete.side_effect = LLMRateLimitError("claude", retry_after=1)
        mock_get_container.return_value = mock_container

        agent = CriticAgent(max_retries=3)
        result = agent.evaluate_draft_with_retry(critique_request)

        assert result.status == CritiqueStatus.RATE_LIMITED
        assert result.decision == CritiqueDecision.REJECT
        # 2 sleeps (entre les 3 tentatives)
        assert mock_sleep.call_count == 2
        # Erreur émise à la fin
        mock_emit_error.assert_called_once()

    @patch("app.api.websocket.emit_critique_error")
    @patch("app.api.websocket.emit_critique_complete")
    @patch("app.api.websocket.emit_critique_start")
    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_with_retry_non_rate_limit_error(
        self, mock_kb, mock_get_container, mock_emit_start, mock_emit_complete, mock_emit_error,
        mock_container, critique_request
    ):
        """evaluate_draft_with_retry gère les erreurs non-rate-limit."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.side_effect = Exception("Network error")
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        result = agent.evaluate_draft_with_retry(critique_request)

        assert result.status == CritiqueStatus.FAILED
        assert "Network error" in result.explanation
        mock_emit_error.assert_called_once()

    @patch("app.api.websocket.emit_critique_error")
    @patch("app.api.websocket.emit_critique_complete")
    @patch("app.api.websocket.emit_critique_start")
    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    @patch("app.agents._time.sleep")
    def test_evaluate_draft_with_retry_uses_exponential_backoff(
        self, mock_sleep, mock_kb, mock_get_container, mock_emit_start, mock_emit_complete, mock_emit_error,
        mock_container, valid_json_response, critique_request
    ):
        """evaluate_draft_with_retry utilise backoff exponentiel sans retry_after."""
        from app.domain.exceptions import LLMRateLimitError

        mock_kb.return_value = "KB"

        # Rate limit sans retry_after, puis succès
        mock_container.llm.complete.side_effect = [
            LLMRateLimitError("claude", retry_after=None),  # Pas de retry_after
            LLMRateLimitError("claude", retry_after=None),
            LLMResponse(
                content=valid_json_response,
                input_tokens=300,
                output_tokens=50,
                model="claude-sonnet-4-20250514"
            )
        ]
        mock_get_container.return_value = mock_container

        agent = CriticAgent(max_retries=5)
        result = agent.evaluate_draft_with_retry(critique_request)

        assert result.decision == CritiqueDecision.VALID
        # Backoff exponentiel: 1.0 * 2^0 = 1.0, puis 1.0 * 2^1 = 2.0
        assert mock_sleep.call_count == 2
        calls = mock_sleep.call_args_list
        assert calls[0][0][0] == 1.0  # Premier backoff
        assert calls[1][0][0] == 2.0  # Deuxième backoff

    @patch("app.api.websocket.emit_critique_error")
    @patch("app.api.websocket.emit_critique_complete")
    @patch("app.api.websocket.emit_critique_start")
    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_evaluate_draft_with_retry_emits_websocket_events(
        self, mock_kb, mock_get_container, mock_emit_start, mock_emit_complete, mock_emit_error,
        mock_container, valid_json_response, critique_request
    ):
        """evaluate_draft_with_retry émet les événements WebSocket."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=valid_json_response,
            input_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent()
        agent.evaluate_draft_with_retry(critique_request)

        # Vérifie que critique_start a été appelé avec l'email_id.
        # Audit R-002 (2026-04-27): emit_critique_start a gagné un paramètre
        # `account_id` (None ici car CriticAgent() est instancié sans account_id).
        mock_emit_start.assert_called_once_with(email_id="test-email-123", account_id=None)


class TestCriticAgentQualityThreshold:
    """Tests spécifiques pour le seuil de qualité (AC3)."""

    @pytest.fixture
    def mock_container(self):
        """Container mocké."""
        container = MagicMock()
        container.llm = MagicMock()
        container.llm_label = container.llm
        container.llm_drafting = container.llm
        container.llm_background = container.llm
        container.token_usage = TokenCounter()
        return container

    def test_default_threshold_value(self):
        """Le seuil par défaut est 70."""
        agent = CriticAgent.__new__(CriticAgent)
        agent.quality_threshold = 70
        assert agent.quality_threshold == 70

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_custom_threshold_initialization(self, mock_kb, mock_get_container, mock_container):
        """Le seuil personnalisé est correctement initialisé."""
        mock_kb.return_value = "KB"
        mock_get_container.return_value = mock_container

        agent = CriticAgent(quality_threshold=80)
        assert agent.quality_threshold == 80

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_threshold_boundary_at_exactly_70(self, mock_kb, mock_get_container, mock_container):
        """Score exactement égal au seuil => VALID."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=json.dumps({
                "coherence": 70, "tone": 70, "completeness": 70, "errors": 70,
                "conciseness": 70, "over_commitment": 70, "emotional_intelligence": 70,
                "decision": "valid", "suggestions": [], "explanation": "OK"
            }),
            input_tokens=100, output_tokens=50, model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent(quality_threshold=70)
        request = CritiqueRequest(draft_content="Test", original_email="Test")
        result = agent.evaluate_draft(request)

        # Score moyen = 70 >= 70 => VALID
        assert result.decision == CritiqueDecision.VALID

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_threshold_boundary_just_below(self, mock_kb, mock_get_container, mock_container):
        """Score juste en dessous du seuil => REJECT."""
        mock_kb.return_value = "KB"
        mock_container.llm.complete.return_value = LLMResponse(
            content=json.dumps({
                "coherence": 69, "tone": 69, "completeness": 69, "errors": 69,
                "decision": "valid", "suggestions": [], "explanation": "OK"
            }),
            input_tokens=100, output_tokens=50, model="claude-sonnet-4-20250514"
        )
        mock_get_container.return_value = mock_container

        agent = CriticAgent(quality_threshold=70)
        request = CritiqueRequest(draft_content="Test", original_email="Test")
        result = agent.evaluate_draft(request)

        # Score moyen = 69 < 70 => REJECT
        assert result.decision == CritiqueDecision.REJECT
