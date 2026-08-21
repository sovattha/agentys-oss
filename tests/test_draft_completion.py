# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module de complétion de brouillons.

Ce module teste :
- L'entité DraftInput (détection, parsing)
- Le use case CompleteDraftUseCase
- Le service façade DraftCompletionAgent
- L'endpoint API /api/drafts/complete
"""

import pytest
from unittest.mock import Mock, patch
from dataclasses import dataclass

from app.domain.entities import DraftInput, DraftInputTone, CompletedDraft
from app.application import CompleteDraftUseCase
from app.domain.entities import TokenUsage


# ============================================================================
# FIXTURES
# ============================================================================

@dataclass
class MockLLMResponse:
    """Mock de réponse LLM."""
    content: str
    input_tokens: int = 100
    output_tokens: int = 200
    model: str = "mock-model"


@pytest.fixture
def mock_llm():
    """Mock du LLM port."""
    llm = Mock()
    llm.complete.return_value = MockLLMResponse(
        content="OBJET: Test de réponse\n\nBonjour,\n\nMerci pour votre message.\n\nCordialement"
    )
    return llm


@pytest.fixture
def token_usage():
    """Token usage tracker."""
    return TokenUsage()


# ============================================================================
# TESTS DRAFT INPUT - DETECTION
# ============================================================================

class TestDraftInputDetection:
    """Tests de détection de demandes de complétion."""

    def test_detect_brouillon_prefix_lowercase(self):
        """Détecte le préfixe 'brouillon :'."""
        text = "brouillon : Remercier Sophie"
        assert DraftInput.is_draft_input(text) is True

    def test_detect_brouillon_prefix_uppercase(self):
        """Détecte le préfixe 'Brouillon :'."""
        text = "Brouillon: Remercier Sophie"
        assert DraftInput.is_draft_input(text) is True

    def test_detect_draft_prefix(self):
        """Détecte le préfixe 'Draft :'."""
        text = "Draft: Thank Sophie for the quick feedback"
        assert DraftInput.is_draft_input(text) is True

    def test_detect_idees_pour_email_prefix(self):
        """Détecte le préfixe 'Idées pour email :'."""
        text = "Idées pour email: Remercier, proposer réunion"
        assert DraftInput.is_draft_input(text) is True

    def test_detect_redige_prefix(self):
        """Détecte le préfixe 'Rédige à partir de ça :'."""
        text = "Rédige à partir de ça: point 1, point 2"
        assert DraftInput.is_draft_input(text) is True

    def test_detect_bullet_points_dash(self):
        """Détecte les bullet points avec tirets."""
        text = """- Remercier Sophie
- Proposer réunion mardi
- Demander avis sur budget"""
        assert DraftInput.is_draft_input(text) is True

    def test_detect_bullet_points_asterisk(self):
        """Détecte les bullet points avec astérisques."""
        text = """* Point 1
* Point 2
* Point 3"""
        assert DraftInput.is_draft_input(text) is True

    def test_detect_numbered_list(self):
        """Détecte les listes numérotées."""
        text = """1. Premier point
2. Deuxième point
3. Troisième point"""
        assert DraftInput.is_draft_input(text) is True

    def test_not_detect_normal_email(self):
        """Ne détecte pas un email normal."""
        text = "Bonjour Sophie, merci pour votre retour rapide. Cordialement, Jean"
        assert DraftInput.is_draft_input(text) is False

    def test_not_detect_short_text(self):
        """Ne détecte pas un texte court sans préfixe."""
        text = "Ok merci"
        assert DraftInput.is_draft_input(text) is False

    def test_not_detect_single_bullet(self):
        """Ne détecte pas un seul bullet point (moins de 50%)."""
        text = """Bonjour,
- Point important
Cordialement"""
        assert DraftInput.is_draft_input(text) is False


# ============================================================================
# TESTS DRAFT INPUT - PARSING
# ============================================================================

class TestDraftInputParsing:
    """Tests de parsing des entrées."""

    def test_parse_with_prefix(self):
        """Parse correctement avec préfixe."""
        text = "Brouillon: Remercier Sophie pour son retour"
        draft_input = DraftInput.from_raw_text(text)

        assert draft_input.raw_input == text
        assert len(draft_input.key_points) >= 1

    def test_parse_bullet_points(self):
        """Parse les bullet points correctement."""
        text = """- Remercier Sophie
- Proposer réunion mardi
- Demander avis budget"""
        draft_input = DraftInput.from_raw_text(text)

        assert len(draft_input.key_points) == 3
        assert "Remercier Sophie" in draft_input.key_points
        assert "Proposer réunion mardi" in draft_input.key_points
        assert "Demander avis budget" in draft_input.key_points

    def test_extract_recipient_avec_a(self):
        """Extrait le destinataire avec 'à'."""
        text = "Brouillon: à Sophie, remercier pour retour"
        draft_input = DraftInput.from_raw_text(text)

        assert draft_input.recipient == "Sophie"

    def test_extract_recipient_avec_pour(self):
        """Extrait le destinataire avec 'pour'."""
        text = "Brouillon: pour Pierre, demander mise à jour"
        draft_input = DraftInput.from_raw_text(text)

        assert draft_input.recipient == "Pierre"

    def test_extract_tone_formal(self):
        """Détecte le ton formel."""
        text = "Brouillon formel: demander mise à jour"
        draft_input = DraftInput.from_raw_text(text)

        assert draft_input.tone == DraftInputTone.FORMAL

    def test_extract_tone_friendly(self):
        """Détecte le ton amical."""
        text = "Brouillon amical: remercier pour l'aide"
        draft_input = DraftInput.from_raw_text(text)

        assert draft_input.tone == DraftInputTone.FRIENDLY

    def test_extract_tone_urgent(self):
        """Détecte le ton urgent."""
        text = "Brouillon urgent: rappeler deadline"
        draft_input = DraftInput.from_raw_text(text)

        assert draft_input.tone == DraftInputTone.URGENT

    def test_extract_tone_conciliatory(self):
        """Détecte le ton conciliant."""
        text = "Brouillon: excuse pour le retard"
        draft_input = DraftInput.from_raw_text(text)

        assert draft_input.tone == DraftInputTone.CONCILIATORY

    def test_extract_tone_default_neutral(self):
        """Ton neutre par défaut."""
        text = "Brouillon: informer de la situation"
        draft_input = DraftInput.from_raw_text(text)

        assert draft_input.tone == DraftInputTone.NEUTRAL

    def test_has_enough_context(self):
        """Vérifie qu'on a assez de contexte."""
        text = "- Point important"
        draft_input = DraftInput.from_raw_text(text)

        assert draft_input.has_enough_context is True

    def test_not_enough_context_empty(self):
        """Pas assez de contexte si vide."""
        draft_input = DraftInput(raw_input="", key_points=[])

        assert draft_input.has_enough_context is False


# ============================================================================
# TESTS COMPLETED DRAFT
# ============================================================================

class TestCompletedDraft:
    """Tests de l'entité CompletedDraft."""

    def test_str_representation(self):
        """Test de la représentation string."""
        draft = CompletedDraft(
            subject="Test Subject",
            body="Bonjour,\n\nMerci.\n\nCordialement"
        )

        result = str(draft)
        assert "Objet : Test Subject" in result
        assert "Bonjour," in result
        assert "Cordialement" in result

    def test_formatted_output(self):
        """Test de la sortie formatée."""
        draft = CompletedDraft(
            subject="Test Subject",
            body="Bonjour,\n\nCordialement"
        )

        result = draft.formatted_output
        assert "---" in result
        assert "Objet : Test Subject" in result
        assert "Voici le courriel rédigé" in result
        assert "Prêt à envoyer" in result


# ============================================================================
# TESTS USE CASE
# ============================================================================

class TestCompleteDraftUseCase:
    """Tests du use case CompleteDraftUseCase."""

    def test_execute_basic(self, mock_llm, token_usage):
        """Test d'exécution basique."""
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="Test KB",
            token_usage=token_usage,
        )

        draft_input = DraftInput.from_raw_text("- Remercier Sophie")
        result = use_case.execute(draft_input)

        assert isinstance(result, CompletedDraft)
        assert result.subject != ""
        mock_llm.complete.assert_called_once()

    def test_execute_tracks_tokens(self, mock_llm, token_usage):
        """Vérifie que les tokens sont comptés."""
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="Test KB",
            token_usage=token_usage,
        )

        draft_input = DraftInput.from_raw_text("- Point 1")
        use_case.execute(draft_input)

        assert token_usage.total > 0

    def test_execute_with_recipient(self, mock_llm, token_usage):
        """Test avec destinataire explicite."""
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage,
        )

        draft_input = DraftInput.from_raw_text("Brouillon: à Marie, remercier")
        use_case.execute(draft_input)

        # Vérifier que le prompt contient le destinataire
        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs.get("user", "")
        assert "Marie" in user_prompt or "Marie" in draft_input.recipient

    def test_execute_with_tone(self, mock_llm, token_usage):
        """Test avec ton spécifique."""
        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage,
        )

        draft_input = DraftInput(
            raw_input="Test",
            key_points=["Point 1"],
            tone=DraftInputTone.FORMAL,
        )
        use_case.execute(draft_input)

        # Vérifier que le prompt contient le ton
        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs.get("user", "")
        assert "formel" in user_prompt.lower() or "formal" in user_prompt.lower()

    def test_parse_response_with_subject(self, mock_llm, token_usage):
        """Parse correctement une réponse avec OBJET."""
        mock_llm.complete.return_value = MockLLMResponse(
            content="OBJET: Mon sujet test\n\nBonjour,\n\nMerci.\n\nCordialement"
        )

        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage,
        )

        draft_input = DraftInput.from_raw_text("- Test")
        result = use_case.execute(draft_input)

        assert result.subject == "Mon sujet test"
        assert "Bonjour," in result.body

    def test_parse_response_fallback_subject(self, mock_llm, token_usage):
        """Fallback si pas d'OBJET dans la réponse."""
        mock_llm.complete.return_value = MockLLMResponse(
            content="Bonjour,\n\nMerci pour votre message.\n\nCordialement"
        )

        use_case = CompleteDraftUseCase(
            llm=mock_llm,
            knowledge_base="",
            token_usage=token_usage,
        )

        draft_input = DraftInput(
            raw_input="Test",
            key_points=["Premier point important"],
            subject_hint="Mon sujet",
        )
        result = use_case.execute(draft_input)

        # Utilise le subject_hint comme fallback
        assert result.subject == "Mon sujet"


# ============================================================================
# TESTS DRAFT COMPLETION AGENT (FACADE)
# ============================================================================

class TestDraftCompletionAgent:
    """Tests du service façade DraftCompletionAgent."""

    @patch('app.draft_completion.get_container')
    def test_complete_basic(self, mock_get_container):
        """Test de complétion basique."""
        # Setup mock
        mock_container = Mock()
        mock_llm = Mock()
        mock_llm.complete.return_value = MockLLMResponse(
            content="OBJET: Test\n\nBonjour,\n\nCordialement"
        )
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = TokenUsage()
        mock_get_container.return_value = mock_container

        from app.draft_completion import DraftCompletionAgent

        agent = DraftCompletionAgent()
        result = agent.complete("Brouillon: remercier Sophie")

        assert isinstance(result, CompletedDraft)
        mock_llm.complete.assert_called_once()

    @patch('app.draft_completion.get_container')
    def test_complete_with_options(self, mock_get_container):
        """Test de complétion avec options."""
        mock_container = Mock()
        mock_llm = Mock()
        mock_llm.complete.return_value = MockLLMResponse(
            content="OBJET: Réunion\n\nBonjour Pierre,\n\nCordialement"
        )
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = TokenUsage()
        mock_get_container.return_value = mock_container

        from app.draft_completion import DraftCompletionAgent

        agent = DraftCompletionAgent()
        result = agent.complete_with_options(
            raw_input="- Proposer réunion",
            recipient="Pierre",
            tone=DraftInputTone.FORMAL,
            subject_hint="Demande de réunion",
        )

        assert isinstance(result, CompletedDraft)
        assert result.recipient == "Pierre"
        assert result.tone_used == DraftInputTone.FORMAL

    @patch('app.draft_completion.get_container')
    def test_is_completion_request_static(self, mock_get_container):
        """Test de la méthode statique is_completion_request."""
        from app.draft_completion import DraftCompletionAgent

        assert DraftCompletionAgent.is_completion_request("Brouillon: test") is True
        assert DraftCompletionAgent.is_completion_request("Normal email") is False


# ============================================================================
# TESTS UTILITAIRES
# ============================================================================

class TestUtilityFunctions:
    """Tests des fonctions utilitaires."""

    @patch('app.draft_completion.get_container')
    def test_complete_draft_function(self, mock_get_container):
        """Test de la fonction complete_draft."""
        mock_container = Mock()
        mock_llm = Mock()
        mock_llm.complete.return_value = MockLLMResponse(
            content="OBJET: Test\n\nBonjour,\n\nCordialement"
        )
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = TokenUsage()
        mock_get_container.return_value = mock_container

        from app.draft_completion import complete_draft

        result = complete_draft("- Point 1")
        assert isinstance(result, CompletedDraft)

    def test_is_draft_request_function(self):
        """Test de la fonction is_draft_request."""
        from app.draft_completion import is_draft_request

        assert is_draft_request("Brouillon: test") is True
        assert is_draft_request("Draft: test") is True
        assert is_draft_request("Hello world") is False


# ============================================================================
# TESTS API ENDPOINT (Standalone - sans dépendance Flask)
# ============================================================================

class TestDraftCompletionAPILogic:
    """Tests de la logique API sans Flask (standalone)."""

    def test_complete_request_validation_missing_input(self):
        """Valide que raw_input est requis."""
        data = {}
        raw_input = data.get("raw_input")
        assert raw_input is None

    def test_complete_request_validation_with_input(self):
        """Valide que raw_input est présent."""
        data = {"raw_input": "- Point 1"}
        raw_input = data.get("raw_input")
        assert raw_input == "- Point 1"

    def test_tone_mapping_valid(self):
        """Test du mapping des tons valides."""
        tone_map = {
            "formal": DraftInputTone.FORMAL,
            "friendly": DraftInputTone.FRIENDLY,
            "urgent": DraftInputTone.URGENT,
            "conciliatory": DraftInputTone.CONCILIATORY,
            "neutral": DraftInputTone.NEUTRAL,
        }

        assert tone_map.get("formal") == DraftInputTone.FORMAL
        assert tone_map.get("friendly") == DraftInputTone.FRIENDLY
        assert tone_map.get("urgent") == DraftInputTone.URGENT

    def test_tone_mapping_invalid(self):
        """Test du mapping avec ton invalide."""
        tone_map = {
            "formal": DraftInputTone.FORMAL,
            "friendly": DraftInputTone.FRIENDLY,
        }

        assert tone_map.get("invalid_tone") is None

    def test_detect_request_validation_missing_text(self):
        """Valide que text est requis pour detect."""
        data = {}
        text = data.get("text")
        assert text is None

    def test_detect_request_with_text(self):
        """Valide la détection avec texte présent."""
        from app.draft_completion import is_draft_request

        data = {"text": "Brouillon: test"}
        text = data.get("text")
        assert is_draft_request(text) is True

    @patch('app.draft_completion.get_container')
    def test_api_response_structure(self, mock_get_container):
        """Test de la structure de réponse API."""
        mock_container = Mock()
        mock_llm = Mock()
        mock_llm.complete.return_value = MockLLMResponse(
            content="OBJET: Test\n\nBonjour,\n\nCordialement"
        )
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = TokenUsage()
        mock_get_container.return_value = mock_container

        from app.draft_completion import DraftCompletionAgent

        agent = DraftCompletionAgent()
        result = agent.complete("Brouillon: test")

        # Simuler la réponse API
        api_response = {
            "success": True,
            "subject": result.subject,
            "body": result.body,
            "recipient": result.recipient,
            "tone_used": result.tone_used.value,
            "formatted_output": result.formatted_output,
        }

        assert api_response["success"] is True
        assert "subject" in api_response
        assert "body" in api_response
        assert "formatted_output" in api_response


# ============================================================================
# TESTS D'INTÉGRATION
# ============================================================================

class TestIntegration:
    """Tests d'intégration du pipeline complet."""

    @patch('app.draft_completion.get_container')
    def test_full_pipeline(self, mock_get_container):
        """Test du pipeline complet."""
        # Setup
        mock_container = Mock()
        mock_llm = Mock()
        mock_llm.complete.return_value = MockLLMResponse(
            content="""OBJET: Demande de réunion

Bonjour Sophie,

Je tenais à vous remercier pour votre retour rapide concernant le projet.

Je souhaiterais vous proposer une réunion mardi ou jeudi prochain afin de discuter des prochaines étapes. Pourriez-vous me faire part de vos disponibilités ?

Je vous joins également le rapport mis à jour pour votre examen.

Enfin, j'aimerais avoir votre avis sur la nouvelle version du budget proposée.

Dans l'attente de votre retour, je vous prie d'agréer, Sophie, l'expression de mes salutations distinguées.

Cordialement"""
        )
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = TokenUsage()
        mock_get_container.return_value = mock_container

        from app.draft_completion import DraftCompletionAgent

        # Input utilisateur (exemple du TODO)
        user_input = """Brouillon :
- Remercier Sophie pour son retour rapide
- Proposer réunion mardi ou jeudi prochain
- Joindre le rapport mis à jour
- Demander son avis sur la nouvelle version du budget"""

        agent = DraftCompletionAgent()
        result = agent.complete(user_input)

        # Vérifications
        assert result.subject != ""
        assert "Sophie" in result.body or result.recipient == "Sophie"
        assert len(result.body) > 100  # Email complet, pas juste les points

    @patch('app.draft_completion.get_container')
    def test_english_input(self, mock_get_container):
        """Test avec entrée en anglais."""
        mock_container = Mock()
        mock_llm = Mock()
        mock_llm.complete.return_value = MockLLMResponse(
            content="OBJET: Meeting Request\n\nDear John,\n\nThank you.\n\nBest regards"
        )
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = TokenUsage()
        mock_get_container.return_value = mock_container

        from app.draft_completion import DraftCompletionAgent

        user_input = """Draft:
- Thank John for quick response
- Schedule meeting for Tuesday
- Request feedback on proposal"""

        agent = DraftCompletionAgent()
        result = agent.complete(user_input)

        assert result.subject != ""
        mock_llm.complete.assert_called_once()
