# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour l'édition temps réel des brouillons.

Cette fonctionnalité permet à un agent IA de corriger/améliorer le texte
d'un utilisateur en temps réel pendant qu'il écrit un nouveau courriel.

Les modifications se font "devant ses yeux" comme dans Gmail, sans devoir
quitter la zone de texte.

Architecture Clean:
- Domain: Entités (EditSession, TextChange, SuggestionResult)
- Application: Use Cases (StartEditSession, ProcessTextChange, ApplySuggestion)
- Adapters: WebSocket, REST
- Infrastructure: Container integration
"""

import pytest
from datetime import datetime
from unittest.mock import Mock

# =============================================================================
# TESTS POUR LES ENTITÉS DU DOMAINE
# =============================================================================


class TestEditSessionEntity:
    """Tests pour l'entité EditSession."""

    def test_create_session_with_id(self):
        """Une session d'édition doit avoir un ID unique."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123")

        assert session.session_id is not None
        assert len(session.session_id) > 0
        assert session.user_id == "user-123"

    def test_create_session_has_timestamp(self):
        """Une session doit avoir un timestamp de création."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123")

        assert session.created_at is not None
        assert isinstance(session.created_at, datetime)

    def test_session_starts_active(self):
        """Une nouvelle session doit être active."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123")

        assert session.is_active is True

    def test_session_can_be_closed(self):
        """Une session peut être fermée."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123")
        session.close()

        assert session.is_active is False
        assert session.closed_at is not None

    def test_session_tracks_current_text(self):
        """Une session suit le texte courant."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123", initial_text="Hello")

        assert session.current_text == "Hello"

    def test_session_updates_text(self):
        """Le texte peut être mis à jour."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123", initial_text="Hello")
        session.update_text("Hello World")

        assert session.current_text == "Hello World"

    def test_session_tracks_last_activity(self):
        """La session suit la dernière activité."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123")
        original_time = session.last_activity_at

        session.update_text("New text")

        assert session.last_activity_at >= original_time


class TestTextChangeEntity:
    """Tests pour l'entité TextChange."""

    def test_create_text_change_from_typing(self):
        """Création d'un changement de texte depuis la frappe."""
        from app.domain.entities.realtime_edit import TextChange, ChangeType

        change = TextChange.from_typing(
            old_text="Hello",
            new_text="Hello World",
            cursor_position=11,
        )

        assert change.old_text == "Hello"
        assert change.new_text == "Hello World"
        assert change.cursor_position == 11
        assert change.change_type == ChangeType.INSERT

    def test_detect_insert_change_type(self):
        """Détecte le type INSERT quand du texte est ajouté."""
        from app.domain.entities.realtime_edit import TextChange, ChangeType

        change = TextChange.from_typing(
            old_text="Hello",
            new_text="Hello World",
            cursor_position=11,
        )

        assert change.change_type == ChangeType.INSERT

    def test_detect_delete_change_type(self):
        """Détecte le type DELETE quand du texte est supprimé."""
        from app.domain.entities.realtime_edit import TextChange, ChangeType

        change = TextChange.from_typing(
            old_text="Hello World",
            new_text="Hello",
            cursor_position=5,
        )

        assert change.change_type == ChangeType.DELETE

    def test_detect_replace_change_type(self):
        """Détecte le type REPLACE quand du texte est remplacé."""
        from app.domain.entities.realtime_edit import TextChange, ChangeType

        change = TextChange.from_typing(
            old_text="Hello World",
            new_text="Hello Planet",
            cursor_position=12,
        )

        assert change.change_type == ChangeType.REPLACE

    def test_change_has_timestamp(self):
        """Un changement a un timestamp."""
        from app.domain.entities.realtime_edit import TextChange

        change = TextChange.from_typing(
            old_text="Hello",
            new_text="Hello World",
            cursor_position=11,
        )

        assert change.timestamp is not None
        assert isinstance(change.timestamp, datetime)


class TestEditTriggerEntity:
    """Tests pour les conditions de déclenchement de l'édition."""

    def test_trigger_on_blur(self):
        """Déclenche l'édition quand le curseur quitte la zone."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger(trigger_type=TriggerType.BLUR)

        assert trigger.should_process is True
        assert trigger.trigger_type == TriggerType.BLUR

    def test_trigger_on_pause(self):
        """Déclenche l'édition après une pause de frappe."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger(
            trigger_type=TriggerType.TYPING_PAUSE,
            pause_duration_ms=1500,
        )

        assert trigger.should_process is True
        assert trigger.pause_duration_ms == 1500

    def test_trigger_on_sentence_end(self):
        """Déclenche l'édition à la fin d'une phrase."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger(trigger_type=TriggerType.SENTENCE_END)

        assert trigger.should_process is True
        assert trigger.trigger_type == TriggerType.SENTENCE_END

    def test_trigger_on_manual_request(self):
        """Déclenche l'édition sur demande explicite."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger(trigger_type=TriggerType.MANUAL)

        assert trigger.should_process is True
        assert trigger.trigger_type == TriggerType.MANUAL

    def test_no_trigger_while_typing(self):
        """Pas de déclenchement pendant la frappe active."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger(trigger_type=TriggerType.NONE)

        assert trigger.should_process is False

    def test_from_string_blur(self):
        """Crée un trigger BLUR depuis une chaîne."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger.from_string("blur")

        assert trigger.trigger_type == TriggerType.BLUR
        assert trigger.should_process is True

    def test_from_string_typing_pause(self):
        """Crée un trigger TYPING_PAUSE depuis une chaîne."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger.from_string("typing_pause")

        assert trigger.trigger_type == TriggerType.TYPING_PAUSE

    def test_from_string_case_insensitive(self):
        """La conversion est insensible à la casse."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger.from_string("BLUR")

        assert trigger.trigger_type == TriggerType.BLUR

    def test_from_string_unknown_defaults_to_none(self):
        """Une chaîne inconnue donne un trigger NONE."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger.from_string("unknown")

        assert trigger.trigger_type == TriggerType.NONE
        assert trigger.should_process is False


class TestSuggestionEntity:
    """Tests pour l'entité Suggestion (correction IA)."""

    def test_create_suggestion_with_text(self):
        """Une suggestion contient le texte corrigé."""
        from app.domain.entities.realtime_edit import Suggestion

        suggestion = Suggestion(
            original_text="je veut manger",
            suggested_text="Je veux manger",
            confidence=0.95,
        )

        assert suggestion.original_text == "je veut manger"
        assert suggestion.suggested_text == "Je veux manger"
        assert suggestion.confidence == 0.95

    def test_suggestion_has_explanation(self):
        """Une suggestion peut avoir une explication."""
        from app.domain.entities.realtime_edit import Suggestion

        suggestion = Suggestion(
            original_text="je veut",
            suggested_text="Je veux",
            confidence=0.95,
            explanation="Correction orthographique: 'veut' → 'veux'",
        )

        assert suggestion.explanation is not None
        assert "orthographique" in suggestion.explanation

    def test_suggestion_highlights_changes(self):
        """Une suggestion identifie les zones modifiées."""
        from app.domain.entities.realtime_edit import Suggestion

        suggestion = Suggestion(
            original_text="je veut manger",
            suggested_text="Je veux manger",
            confidence=0.95,
        )

        diffs = suggestion.get_diffs()

        # On vérifie qu'il y a au moins une différence
        assert len(diffs) >= 1
        # Vérifie que les diffs contiennent les changements
        # Note: difflib peut grouper les changements différemment
        all_originals = " ".join(d.original for d in diffs)
        all_replacements = " ".join(d.replacement for d in diffs)
        assert "je" in all_originals or "veut" in all_originals
        assert "Je" in all_replacements or "veux" in all_replacements

    def test_suggestion_types(self):
        """Une suggestion a un ou plusieurs types."""
        from app.domain.entities.realtime_edit import (
            Suggestion,
            SuggestionType,
        )

        suggestion = Suggestion(
            original_text="je veut",
            suggested_text="Je veux",
            confidence=0.95,
            suggestion_types=[SuggestionType.GRAMMAR, SuggestionType.CAPITALIZATION],
        )

        assert SuggestionType.GRAMMAR in suggestion.suggestion_types
        assert SuggestionType.CAPITALIZATION in suggestion.suggestion_types

    def test_suggestion_status_pending(self):
        """Une nouvelle suggestion est en attente."""
        from app.domain.entities.realtime_edit import Suggestion, SuggestionStatus

        suggestion = Suggestion(
            original_text="je veut",
            suggested_text="Je veux",
            confidence=0.95,
        )

        assert suggestion.status == SuggestionStatus.PENDING

    def test_suggestion_can_be_accepted(self):
        """Une suggestion peut être acceptée."""
        from app.domain.entities.realtime_edit import Suggestion, SuggestionStatus

        suggestion = Suggestion(
            original_text="je veut",
            suggested_text="Je veux",
            confidence=0.95,
        )

        suggestion.accept()

        assert suggestion.status == SuggestionStatus.ACCEPTED

    def test_suggestion_can_be_rejected(self):
        """Une suggestion peut être rejetée."""
        from app.domain.entities.realtime_edit import Suggestion, SuggestionStatus

        suggestion = Suggestion(
            original_text="je veut",
            suggested_text="Je veux",
            confidence=0.95,
        )

        suggestion.reject()

        assert suggestion.status == SuggestionStatus.REJECTED


class TestSuggestionResultEntity:
    """Tests pour l'entité SuggestionResult (résultat global)."""

    def test_result_contains_suggestions(self):
        """Un résultat contient les suggestions."""
        from app.domain.entities.realtime_edit import Suggestion, SuggestionResult

        suggestion = Suggestion(
            original_text="je veut",
            suggested_text="Je veux",
            confidence=0.95,
        )

        result = SuggestionResult(
            session_id="session-123",
            original_full_text="je veut manger",
            suggestions=[suggestion],
        )

        assert len(result.suggestions) == 1
        assert result.suggestions[0].suggested_text == "Je veux"

    def test_result_has_final_text(self):
        """Un résultat a le texte final suggéré."""
        from app.domain.entities.realtime_edit import SuggestionResult

        result = SuggestionResult(
            session_id="session-123",
            original_full_text="je veut manger",
            suggested_full_text="Je veux manger",
            suggestions=[],
        )

        assert result.suggested_full_text == "Je veux manger"

    def test_result_tracks_processing_time(self):
        """Un résultat suit le temps de traitement."""
        from app.domain.entities.realtime_edit import SuggestionResult

        result = SuggestionResult(
            session_id="session-123",
            original_full_text="test",
            processing_time_ms=150,
            suggestions=[],
        )

        assert result.processing_time_ms == 150


# =============================================================================
# TESTS POUR LES PORTS (INTERFACES)
# =============================================================================


class TestRealTimeEditPort:
    """Tests pour le port RealTimeEditPort."""

    def test_port_has_start_session_method(self):
        """Le port a une méthode start_session."""
        from app.domain.ports.realtime_edit_port import RealTimeEditPort

        assert hasattr(RealTimeEditPort, "start_session")

    def test_port_has_process_change_method(self):
        """Le port a une méthode process_change."""
        from app.domain.ports.realtime_edit_port import RealTimeEditPort

        assert hasattr(RealTimeEditPort, "process_change")

    def test_port_has_get_suggestion_method(self):
        """Le port a une méthode get_suggestion."""
        from app.domain.ports.realtime_edit_port import RealTimeEditPort

        assert hasattr(RealTimeEditPort, "get_suggestion")

    def test_port_has_close_session_method(self):
        """Le port a une méthode close_session."""
        from app.domain.ports.realtime_edit_port import RealTimeEditPort

        assert hasattr(RealTimeEditPort, "close_session")


class TestEditSessionStorePort:
    """Tests pour le port de persistance des sessions."""

    def test_port_has_save_method(self):
        """Le port a une méthode save."""
        from app.domain.ports.realtime_edit_port import EditSessionStorePort

        assert hasattr(EditSessionStorePort, "save")

    def test_port_has_get_method(self):
        """Le port a une méthode get."""
        from app.domain.ports.realtime_edit_port import EditSessionStorePort

        assert hasattr(EditSessionStorePort, "get")

    def test_port_has_delete_method(self):
        """Le port a une méthode delete."""
        from app.domain.ports.realtime_edit_port import EditSessionStorePort

        assert hasattr(EditSessionStorePort, "delete")


# =============================================================================
# TESTS POUR LES USE CASES
# =============================================================================


class TestStartEditSessionUseCase:
    """Tests pour le use case StartEditSession."""

    def test_creates_new_session(self):
        """Crée une nouvelle session d'édition."""
        from app.application.realtime_edit import StartEditSessionUseCase
        from app.domain.entities.realtime_edit import EditSession

        mock_store = Mock()
        mock_store.save = Mock()

        use_case = StartEditSessionUseCase(session_store=mock_store)
        session = use_case.execute(user_id="user-123")

        assert isinstance(session, EditSession)
        assert session.user_id == "user-123"
        assert session.is_active is True
        mock_store.save.assert_called_once()

    def test_creates_session_with_initial_text(self):
        """Crée une session avec texte initial."""
        from app.application.realtime_edit import StartEditSessionUseCase

        mock_store = Mock()
        mock_store.save = Mock()

        use_case = StartEditSessionUseCase(session_store=mock_store)
        session = use_case.execute(
            user_id="user-123",
            initial_text="Hello",
        )

        assert session.current_text == "Hello"


class TestProcessTextChangeUseCase:
    """Tests pour le use case ProcessTextChange."""

    def test_updates_session_text(self):
        """Met à jour le texte de la session."""
        from app.application.realtime_edit import ProcessTextChangeUseCase
        from app.domain.entities.realtime_edit import EditSession, TextChange

        mock_store = Mock()
        session = EditSession.create(user_id="user-123", initial_text="Hello")
        mock_store.get = Mock(return_value=session)
        mock_store.save = Mock()

        change = TextChange.from_typing(
            old_text="Hello",
            new_text="Hello World",
            cursor_position=11,
        )

        use_case = ProcessTextChangeUseCase(session_store=mock_store)
        updated_session = use_case.execute(
            session_id=session.session_id,
            change=change,
        )

        assert updated_session.current_text == "Hello World"
        mock_store.save.assert_called_once()

    def test_returns_none_if_session_not_found(self):
        """Retourne None si la session n'existe pas."""
        from app.application.realtime_edit import ProcessTextChangeUseCase
        from app.domain.entities.realtime_edit import TextChange

        mock_store = Mock()
        mock_store.get = Mock(return_value=None)

        change = TextChange.from_typing(
            old_text="Hello",
            new_text="Hello World",
            cursor_position=11,
        )

        use_case = ProcessTextChangeUseCase(session_store=mock_store)
        result = use_case.execute(
            session_id="nonexistent",
            change=change,
        )

        assert result is None


class TestGetSuggestionUseCase:
    """Tests pour le use case GetSuggestion."""

    def test_returns_suggestion_for_text(self):
        """Retourne une suggestion pour le texte."""
        from app.application.realtime_edit import GetSuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            EditTrigger,
            TriggerType,
            SuggestionResult,
        )
        from app.domain.ports.llm_port import LLMResponse

        mock_store = Mock()
        session = EditSession.create(
            user_id="user-123",
            initial_text="je veut manger",
        )
        mock_store.get = Mock(return_value=session)

        mock_llm = Mock()
        mock_llm.complete = Mock(
            return_value=LLMResponse(
                content="Je veux manger",
                input_tokens=10,
                output_tokens=5,
            )
        )

        trigger = EditTrigger(trigger_type=TriggerType.BLUR)

        use_case = GetSuggestionUseCase(
            session_store=mock_store,
            llm=mock_llm,
        )
        result = use_case.execute(
            session_id=session.session_id,
            trigger=trigger,
        )

        assert result is not None
        assert isinstance(result, SuggestionResult)
        assert result.suggested_full_text == "Je veux manger"

    def test_no_suggestion_if_trigger_inactive(self):
        """Pas de suggestion si le trigger n'est pas actif."""
        from app.application.realtime_edit import GetSuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            EditTrigger,
            TriggerType,
        )

        mock_store = Mock()
        session = EditSession.create(
            user_id="user-123",
            initial_text="je veut manger",
        )
        mock_store.get = Mock(return_value=session)

        mock_llm = Mock()

        trigger = EditTrigger(trigger_type=TriggerType.NONE)

        use_case = GetSuggestionUseCase(
            session_store=mock_store,
            llm=mock_llm,
        )
        result = use_case.execute(
            session_id=session.session_id,
            trigger=trigger,
        )

        assert result is None
        mock_llm.complete.assert_not_called()

    def test_no_suggestion_if_text_unchanged(self):
        """Pas de suggestion si le texte n'a pas changé."""
        from app.application.realtime_edit import GetSuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            EditTrigger,
            TriggerType,
        )
        from app.domain.ports.llm_port import LLMResponse

        mock_store = Mock()
        session = EditSession.create(
            user_id="user-123",
            initial_text="Je veux manger",  # Texte déjà correct
        )
        mock_store.get = Mock(return_value=session)

        mock_llm = Mock()
        # LLM retourne le même texte
        mock_llm.complete = Mock(
            return_value=LLMResponse(
                content="Je veux manger",
                input_tokens=10,
                output_tokens=5,
            )
        )

        trigger = EditTrigger(trigger_type=TriggerType.BLUR)

        use_case = GetSuggestionUseCase(
            session_store=mock_store,
            llm=mock_llm,
        )
        result = use_case.execute(
            session_id=session.session_id,
            trigger=trigger,
        )

        assert result is not None
        # Pas de suggestions car le texte est identique
        assert len(result.suggestions) == 0


class TestApplySuggestionUseCase:
    """Tests pour le use case ApplySuggestion."""

    def test_applies_accepted_suggestion(self):
        """Applique une suggestion acceptée."""
        from app.application.realtime_edit import ApplySuggestionUseCase
        from app.domain.entities.realtime_edit import EditSession, Suggestion

        mock_store = Mock()
        session = EditSession.create(
            user_id="user-123",
            initial_text="je veut manger",
        )
        mock_store.get = Mock(return_value=session)
        mock_store.save = Mock()

        suggestion = Suggestion(
            original_text="je veut",
            suggested_text="Je veux",
            confidence=0.95,
        )

        use_case = ApplySuggestionUseCase(session_store=mock_store)
        updated_session = use_case.execute(
            session_id=session.session_id,
            suggestion=suggestion,
            accept=True,
        )

        assert "Je veux" in updated_session.current_text
        mock_store.save.assert_called_once()

    def test_rejects_suggestion_without_change(self):
        """Rejette une suggestion sans modifier le texte."""
        from app.application.realtime_edit import ApplySuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            Suggestion,
            SuggestionStatus,
        )

        mock_store = Mock()
        session = EditSession.create(
            user_id="user-123",
            initial_text="je veut manger",
        )
        mock_store.get = Mock(return_value=session)
        mock_store.save = Mock()

        suggestion = Suggestion(
            original_text="je veut",
            suggested_text="Je veux",
            confidence=0.95,
        )

        use_case = ApplySuggestionUseCase(session_store=mock_store)
        updated_session = use_case.execute(
            session_id=session.session_id,
            suggestion=suggestion,
            accept=False,
        )

        # Le texte reste inchangé
        assert updated_session.current_text == "je veut manger"
        assert suggestion.status == SuggestionStatus.REJECTED


class TestCloseEditSessionUseCase:
    """Tests pour le use case CloseEditSession."""

    def test_closes_active_session(self):
        """Ferme une session active."""
        from app.application.realtime_edit import CloseEditSessionUseCase
        from app.domain.entities.realtime_edit import EditSession

        mock_store = Mock()
        session = EditSession.create(user_id="user-123")
        mock_store.get = Mock(return_value=session)
        mock_store.save = Mock()

        use_case = CloseEditSessionUseCase(session_store=mock_store)
        closed_session = use_case.execute(session_id=session.session_id)

        assert closed_session.is_active is False
        assert closed_session.closed_at is not None
        mock_store.save.assert_called_once()


class TestGetEditSessionUseCase:
    """Tests pour le use case GetEditSession."""

    def test_returns_session_if_found(self):
        """Retourne une session si elle existe."""
        from app.application.realtime_edit import GetEditSessionUseCase
        from app.domain.entities.realtime_edit import EditSession

        mock_store = Mock()
        session = EditSession.create(user_id="user-123", initial_text="Hello")
        mock_store.get = Mock(return_value=session)

        use_case = GetEditSessionUseCase(session_store=mock_store)
        result = use_case.execute(session_id=session.session_id)

        assert result is not None
        assert result.session_id == session.session_id
        assert result.current_text == "Hello"

    def test_returns_none_if_not_found(self):
        """Retourne None si la session n'existe pas."""
        from app.application.realtime_edit import GetEditSessionUseCase

        mock_store = Mock()
        mock_store.get = Mock(return_value=None)

        use_case = GetEditSessionUseCase(session_store=mock_store)
        result = use_case.execute(session_id="nonexistent")

        assert result is None


# =============================================================================
# TESTS POUR L'INTÉGRATION AVEC LE CONTAINER
# =============================================================================


class TestContainerIntegration:
    """Tests pour l'intégration au Container DI."""

    def test_container_has_realtime_edit_store(self):
        """Le container expose le store d'édition temps réel."""
        from app.infrastructure.container import get_container, reset_container

        reset_container()
        container = get_container()

        store = container.get_realtime_edit_store()

        assert store is not None
        from app.domain.ports.realtime_edit_port import EditSessionStorePort
        assert isinstance(store, EditSessionStorePort)

    def test_container_has_start_session_use_case(self):
        """Le container expose le use case StartEditSession."""
        from app.infrastructure.container import get_container, reset_container

        reset_container()
        container = get_container()

        use_case = container.get_start_edit_session_use_case()

        assert use_case is not None
        from app.application.realtime_edit import StartEditSessionUseCase
        assert isinstance(use_case, StartEditSessionUseCase)

    def test_container_has_get_suggestion_use_case(self):
        """Le container expose le use case GetSuggestion (avec mock LLM)."""
        from app.infrastructure.container import get_container, reset_container

        reset_container()
        container = get_container()

        # Injecter un mock LLM pour éviter les erreurs d'import anthropic
        mock_llm = Mock()
        mock_llm.name = "mock"
        mock_llm.model = "mock-model"
        container._llm = mock_llm

        use_case = container.get_suggestion_use_case()

        assert use_case is not None
        from app.application.realtime_edit import GetSuggestionUseCase
        assert isinstance(use_case, GetSuggestionUseCase)

    def test_container_has_get_edit_session_use_case(self):
        """Le container expose le use case GetEditSession."""
        from app.infrastructure.container import get_container, reset_container

        reset_container()
        container = get_container()

        use_case = container.get_edit_session_use_case()

        assert use_case is not None
        from app.application.realtime_edit import GetEditSessionUseCase
        assert isinstance(use_case, GetEditSessionUseCase)


# =============================================================================
# TESTS POUR L'API REST/WEBSOCKET
# =============================================================================


class TestRealTimeEditAPI:
    """Tests pour l'API de l'édition temps réel."""

    @pytest.fixture
    def client(self):
        """Client de test Flask avec mock LLM."""
        from app.api.app import create_app
        from app.infrastructure.container import get_container, reset_container
        from app.domain.ports.llm_port import LLMResponse

        reset_container()
        container = get_container()

        # Injecter un mock LLM
        mock_llm = Mock()
        mock_llm.name = "mock"
        mock_llm.model = "mock-model"
        mock_llm.complete = Mock(
            return_value=LLMResponse(
                content="Je veux manger",
                input_tokens=10,
                output_tokens=5,
            )
        )
        container._llm = mock_llm

        app = create_app({"TESTING": True})
        return app.test_client()

    def test_start_session_endpoint(self, client):
        """POST /api/realtime-edit/sessions démarre une session."""
        response = client.post(
            "/api/realtime-edit/sessions",
            json={"user_id": "user-123"},
        )

        assert response.status_code == 201
        data = response.get_json()
        assert "session_id" in data
        assert data["is_active"] is True

    def test_update_text_endpoint(self, client):
        """PUT /api/realtime-edit/sessions/<id>/text met à jour le texte."""
        # D'abord créer une session
        create_response = client.post(
            "/api/realtime-edit/sessions",
            json={"user_id": "user-123"},
        )
        session_id = create_response.get_json()["session_id"]

        # Puis mettre à jour le texte
        response = client.put(
            f"/api/realtime-edit/sessions/{session_id}/text",
            json={
                "old_text": "",
                "new_text": "Hello World",
                "cursor_position": 11,
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["current_text"] == "Hello World"

    def test_get_suggestion_endpoint(self, client):
        """POST /api/realtime-edit/sessions/<id>/suggest obtient une suggestion."""
        # Créer une session avec texte
        create_response = client.post(
            "/api/realtime-edit/sessions",
            json={
                "user_id": "user-123",
                "initial_text": "je veut manger",
            },
        )
        session_id = create_response.get_json()["session_id"]

        # Demander une suggestion
        response = client.post(
            f"/api/realtime-edit/sessions/{session_id}/suggest",
            json={"trigger": "blur"},
        )

        assert response.status_code == 200
        data = response.get_json()
        # Peut avoir suggested_full_text ou message si pas de changement
        assert "suggested_full_text" in data or "message" in data

    def test_apply_suggestion_endpoint(self, client):
        """POST /api/realtime-edit/sessions/<id>/apply applique une suggestion."""
        # Créer une session
        create_response = client.post(
            "/api/realtime-edit/sessions",
            json={
                "user_id": "user-123",
                "initial_text": "je veut manger",
            },
        )
        session_id = create_response.get_json()["session_id"]

        # Appliquer une suggestion directement (sans passer par suggest)
        response = client.post(
            f"/api/realtime-edit/sessions/{session_id}/apply",
            json={
                "original_text": "je veut",
                "suggested_text": "Je veux",
                "accept": True,
            },
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["applied"] is True
        # Le texte devrait contenir "Je veux"
        assert "Je veux" in data["current_text"]

    def test_close_session_endpoint(self, client):
        """DELETE /api/realtime-edit/sessions/<id> ferme la session."""
        # Créer une session
        create_response = client.post(
            "/api/realtime-edit/sessions",
            json={"user_id": "user-123"},
        )
        session_id = create_response.get_json()["session_id"]

        # Fermer la session
        response = client.delete(f"/api/realtime-edit/sessions/{session_id}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["is_active"] is False


# =============================================================================
# TESTS EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_text_no_suggestion(self):
        """Pas de suggestion pour un texte vide."""
        from app.application.realtime_edit import GetSuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            EditTrigger,
            TriggerType,
        )

        mock_store = Mock()
        session = EditSession.create(user_id="user-123", initial_text="")
        mock_store.get = Mock(return_value=session)

        mock_llm = Mock()

        trigger = EditTrigger(trigger_type=TriggerType.BLUR)

        use_case = GetSuggestionUseCase(
            session_store=mock_store,
            llm=mock_llm,
        )
        result = use_case.execute(
            session_id=session.session_id,
            trigger=trigger,
        )

        assert result is None
        mock_llm.complete.assert_not_called()

    def test_very_long_text_truncated(self):
        """Un texte très long est tronqué pour le LLM."""
        from app.application.realtime_edit import GetSuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            EditTrigger,
            TriggerType,
        )
        from app.domain.ports.llm_port import LLMResponse

        mock_store = Mock()
        long_text = "a" * 10000  # 10k caractères
        session = EditSession.create(user_id="user-123", initial_text=long_text)
        mock_store.get = Mock(return_value=session)

        mock_llm = Mock()
        mock_llm.complete = Mock(
            return_value=LLMResponse(
                content=long_text[:5000],
                input_tokens=1000,
                output_tokens=500,
            )
        )

        trigger = EditTrigger(trigger_type=TriggerType.BLUR)

        use_case = GetSuggestionUseCase(
            session_store=mock_store,
            llm=mock_llm,
            max_text_length=5000,
        )
        use_case.execute(
            session_id=session.session_id,
            trigger=trigger,
        )

        # Le LLM devrait être appelé avec un texte tronqué
        mock_llm.complete.assert_called_once()
        call_args = mock_llm.complete.call_args
        assert len(call_args[1]["user"]) <= 5500  # Marge pour le prompt

    def test_session_timeout(self):
        """Une session expirée ne devrait pas être utilisable."""
        from app.domain.entities.realtime_edit import EditSession
        from datetime import timedelta

        session = EditSession.create(user_id="user-123")

        # Simuler une session expirée (plus de 30 min d'inactivité)
        session._last_activity_at = session.created_at - timedelta(minutes=31)

        assert session.is_expired(timeout_minutes=30) is True

    def test_concurrent_updates_handled(self):
        """Les mises à jour concurrentes sont gérées."""
        from app.domain.entities.realtime_edit import EditSession, TextChange

        session = EditSession.create(user_id="user-123", initial_text="Hello")

        # Simuler deux changements concurrents
        change1 = TextChange.from_typing(
            old_text="Hello",
            new_text="Hello World",
            cursor_position=11,
        )
        TextChange.from_typing(
            old_text="Hello",
            new_text="Hello!",
            cursor_position=6,
        )

        # Appliquer le premier changement
        session.update_text(change1.new_text)

        # Le second changement devrait détecter le conflit
        assert session.has_conflict(base_text="Hello") is True

    def test_special_characters_preserved(self):
        """Les caractères spéciaux sont préservés."""
        from app.domain.entities.realtime_edit import EditSession

        special_text = "Bonjour 😀 → test «guillemets» €100"
        session = EditSession.create(
            user_id="user-123",
            initial_text=special_text,
        )

        assert session.current_text == special_text


# =============================================================================
# TESTS DE PERFORMANCE
# =============================================================================


class TestPerformance:
    """Tests de performance."""

    def test_suggestion_within_timeout(self):
        """La suggestion doit être générée dans le temps imparti."""
        import time
        from app.application.realtime_edit import GetSuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            EditTrigger,
            TriggerType,
        )
        from app.domain.ports.llm_port import LLMResponse

        mock_store = Mock()
        session = EditSession.create(
            user_id="user-123",
            initial_text="je veut manger",
        )
        mock_store.get = Mock(return_value=session)

        mock_llm = Mock()
        mock_llm.complete = Mock(
            return_value=LLMResponse(
                content="Je veux manger",
                input_tokens=10,
                output_tokens=5,
            )
        )

        trigger = EditTrigger(trigger_type=TriggerType.BLUR)

        use_case = GetSuggestionUseCase(
            session_store=mock_store,
            llm=mock_llm,
        )

        start = time.time()
        result = use_case.execute(
            session_id=session.session_id,
            trigger=trigger,
        )
        elapsed = (time.time() - start) * 1000  # en ms

        # La suggestion devrait prendre moins de 100ms (hors appel LLM mocké)
        assert elapsed < 100
        assert result is not None
