# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases de l'edition temps reel des brouillons.

Ces tests couvrent les cas limites non testes:
- Valeurs null/vides
- Erreurs et exceptions
- Formats invalides
- Cas de bord

Architecture Clean:
- Domain: Entities edge cases
- Application: Use Cases edge cases
- Infrastructure: Store edge cases
- API: Endpoint edge cases
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock
from pathlib import Path
import tempfile


# =============================================================================
# TESTS EDGE CASES - ENTITES DU DOMAINE
# =============================================================================


class TestTextDiffEdgeCases:
    """Tests pour les edge cases de TextDiff."""

    def test_textdiff_with_empty_original(self):
        """TextDiff avec texte original vide (insertion pure)."""
        from app.domain.entities.realtime_edit import TextDiff

        diff = TextDiff(start=0, end=0, original="", replacement="Hello")

        assert diff.is_insertion is True
        assert diff.is_deletion is False

    def test_textdiff_with_empty_replacement(self):
        """TextDiff avec remplacement vide (suppression pure)."""
        from app.domain.entities.realtime_edit import TextDiff

        diff = TextDiff(start=0, end=5, original="Hello", replacement="")

        assert diff.is_insertion is False
        assert diff.is_deletion is True

    def test_textdiff_with_both_empty(self):
        """TextDiff avec les deux textes vides."""
        from app.domain.entities.realtime_edit import TextDiff

        diff = TextDiff(start=0, end=0, original="", replacement="")

        assert diff.is_insertion is False
        assert diff.is_deletion is False

    def test_textdiff_with_negative_positions(self):
        """TextDiff avec positions negatives."""
        from app.domain.entities.realtime_edit import TextDiff

        diff = TextDiff(start=-1, end=-1, original="test", replacement="test2")

        # Le code doit accepter ces valeurs (la validation est ailleurs)
        assert diff.start == -1
        assert diff.end == -1


class TestEditSessionEdgeCases:
    """Tests edge cases pour EditSession."""

    def test_create_session_with_empty_user_id(self):
        """Creation avec user_id vide."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="")

        assert session.user_id == ""
        assert session.is_active is True

    def test_create_session_with_whitespace_user_id(self):
        """Creation avec user_id contenant que des espaces."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="   ")

        assert session.user_id == "   "

    def test_update_text_with_none_raises_error(self):
        """update_text avec None devrait lever une erreur."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123")

        with pytest.raises(TypeError):
            session.update_text(None)

    def test_session_version_increments(self):
        """La version s'incremente a chaque update."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123")
        initial_version = session.version

        session.update_text("text1")
        assert session.version == initial_version + 1

        session.update_text("text2")
        assert session.version == initial_version + 2

    def test_close_already_closed_session(self):
        """Fermer une session deja fermee."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123")
        session.close()
        first_closed_at = session.closed_at

        # Fermer a nouveau
        session.close()

        # La date devrait etre mise a jour
        assert session.closed_at >= first_closed_at
        assert session.is_active is False

    def test_is_expired_with_zero_timeout(self):
        """is_expired avec timeout de 0 minutes."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123")

        # Avec timeout 0, toute session active devrait expirer immediatement
        assert session.is_expired(timeout_minutes=0) is True

    def test_is_expired_with_negative_timeout(self):
        """is_expired avec timeout negatif."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123")

        # Avec timeout negatif, devrait toujours etre expire
        assert session.is_expired(timeout_minutes=-1) is True

    def test_has_conflict_with_empty_base_text(self):
        """has_conflict avec base_text vide."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123", initial_text="Hello")

        # base_text vide ne devrait pas etre un conflit
        assert session.has_conflict(base_text="") is False

    def test_has_conflict_with_same_text(self):
        """has_conflict quand les textes sont identiques."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123", initial_text="Hello")

        assert session.has_conflict(base_text="Hello") is False

    def test_needs_processing_after_mark_processed(self):
        """needs_processing apres mark_processed."""
        from app.domain.entities.realtime_edit import EditSession

        session = EditSession.create(user_id="user-123", initial_text="Hello")
        session.mark_processed()

        assert session.needs_processing is False

        # Modifier le texte
        session.update_text("Hello World")
        assert session.needs_processing is True


class TestTextChangeEdgeCases:
    """Tests edge cases pour TextChange."""

    def test_from_typing_with_identical_texts(self):
        """from_typing avec textes identiques."""
        from app.domain.entities.realtime_edit import TextChange, ChangeType

        change = TextChange.from_typing(
            old_text="Hello",
            new_text="Hello",
            cursor_position=5,
        )

        # Meme texte = REPLACE car ni INSERT ni DELETE
        assert change.change_type == ChangeType.REPLACE

    def test_from_typing_with_empty_texts(self):
        """from_typing avec textes vides."""
        from app.domain.entities.realtime_edit import TextChange, ChangeType

        change = TextChange.from_typing(
            old_text="",
            new_text="",
            cursor_position=0,
        )

        assert change.change_type == ChangeType.REPLACE
        assert change.old_text == ""
        assert change.new_text == ""

    def test_from_typing_with_negative_cursor(self):
        """from_typing avec position curseur negative."""
        from app.domain.entities.realtime_edit import TextChange

        change = TextChange.from_typing(
            old_text="Hello",
            new_text="Hello World",
            cursor_position=-1,
        )

        # Devrait accepter (validation ailleurs)
        assert change.cursor_position == -1

    def test_from_typing_with_unicode(self):
        """from_typing avec caracteres unicode."""
        from app.domain.entities.realtime_edit import TextChange, ChangeType

        change = TextChange.from_typing(
            old_text="Bonjour",
            new_text="Bonjour le monde",
            cursor_position=10,
        )

        assert change.change_type == ChangeType.INSERT

    def test_detect_change_type_prefix_mismatch(self):
        """Detection de type quand les prefixes ne correspondent pas."""
        from app.domain.entities.realtime_edit import TextChange, ChangeType

        change = TextChange.from_typing(
            old_text="Hello",
            new_text="Goodbye",
            cursor_position=7,
        )

        assert change.change_type == ChangeType.REPLACE


class TestEditTriggerEdgeCases:
    """Tests edge cases pour EditTrigger."""

    def test_from_string_with_empty_string(self):
        """from_string avec chaine vide."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger.from_string("")

        assert trigger.trigger_type == TriggerType.NONE
        assert trigger.should_process is False

    def test_from_string_with_whitespace(self):
        """from_string avec espaces."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger.from_string("  blur  ")

        # Devrait echouer car pas de strip
        assert trigger.trigger_type == TriggerType.NONE

    def test_from_string_with_special_chars(self):
        """from_string avec caracteres speciaux."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger.from_string("blur!")

        assert trigger.trigger_type == TriggerType.NONE

    def test_pause_duration_negative(self):
        """pause_duration_ms negatif."""
        from app.domain.entities.realtime_edit import EditTrigger, TriggerType

        trigger = EditTrigger(
            trigger_type=TriggerType.TYPING_PAUSE,
            pause_duration_ms=-100,
        )

        # Devrait accepter (validation business ailleurs)
        assert trigger.pause_duration_ms == -100


class TestSuggestionEdgeCases:
    """Tests edge cases pour Suggestion."""

    def test_suggestion_confidence_zero(self):
        """Suggestion avec confidence a 0."""
        from app.domain.entities.realtime_edit import Suggestion

        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.0,
        )

        assert suggestion.confidence == 0.0

    def test_suggestion_confidence_above_one(self):
        """Suggestion avec confidence > 1."""
        from app.domain.entities.realtime_edit import Suggestion

        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=1.5,
        )

        # Devrait accepter (validation business ailleurs)
        assert suggestion.confidence == 1.5

    def test_suggestion_confidence_negative(self):
        """Suggestion avec confidence negative."""
        from app.domain.entities.realtime_edit import Suggestion

        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=-0.5,
        )

        assert suggestion.confidence == -0.5

    def test_get_diffs_with_identical_texts(self):
        """get_diffs avec textes identiques."""
        from app.domain.entities.realtime_edit import Suggestion

        suggestion = Suggestion(
            original_text="Hello World",
            suggested_text="Hello World",
            confidence=0.9,
        )

        diffs = suggestion.get_diffs()

        assert len(diffs) == 0

    def test_get_diffs_with_empty_original(self):
        """get_diffs avec original vide."""
        from app.domain.entities.realtime_edit import Suggestion

        suggestion = Suggestion(
            original_text="",
            suggested_text="Hello",
            confidence=0.9,
        )

        diffs = suggestion.get_diffs()

        assert len(diffs) >= 1
        assert any(d.is_insertion for d in diffs)

    def test_get_diffs_with_empty_suggested(self):
        """get_diffs avec suggested vide."""
        from app.domain.entities.realtime_edit import Suggestion

        suggestion = Suggestion(
            original_text="Hello",
            suggested_text="",
            confidence=0.9,
        )

        diffs = suggestion.get_diffs()

        assert len(diffs) >= 1
        assert any(d.is_deletion for d in diffs)

    def test_accept_already_accepted(self):
        """accept sur suggestion deja acceptee."""
        from app.domain.entities.realtime_edit import Suggestion, SuggestionStatus

        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9,
        )

        suggestion.accept()
        suggestion.accept()  # Double accept

        assert suggestion.status == SuggestionStatus.ACCEPTED

    def test_reject_then_accept(self):
        """reject puis accept."""
        from app.domain.entities.realtime_edit import Suggestion, SuggestionStatus

        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9,
        )

        suggestion.reject()
        suggestion.accept()

        assert suggestion.status == SuggestionStatus.ACCEPTED


class TestSuggestionResultEdgeCases:
    """Tests edge cases pour SuggestionResult."""

    def test_has_changes_with_none_suggested(self):
        """has_changes quand suggested_full_text est None."""
        from app.domain.entities.realtime_edit import SuggestionResult

        result = SuggestionResult(
            session_id="session-123",
            original_full_text="Hello",
            suggested_full_text=None,
            suggestions=[],
        )

        assert result.has_changes is False

    def test_has_changes_with_identical_texts(self):
        """has_changes quand les textes sont identiques."""
        from app.domain.entities.realtime_edit import SuggestionResult

        result = SuggestionResult(
            session_id="session-123",
            original_full_text="Hello",
            suggested_full_text="Hello",
            suggestions=[],
        )

        assert result.has_changes is False

    def test_empty_suggestions_list(self):
        """SuggestionResult avec liste de suggestions vide."""
        from app.domain.entities.realtime_edit import SuggestionResult

        result = SuggestionResult(
            session_id="session-123",
            original_full_text="Hello",
            suggested_full_text="Hello World",
            suggestions=[],
        )

        assert len(result.suggestions) == 0
        assert result.has_changes is True


# =============================================================================
# TESTS EDGE CASES - USE CASES (APPLICATION)
# =============================================================================


class TestStartEditSessionUseCaseEdgeCases:
    """Tests edge cases pour StartEditSessionUseCase."""

    def test_execute_with_empty_user_id(self):
        """execute avec user_id vide."""
        from app.application.realtime_edit import StartEditSessionUseCase

        mock_store = Mock()
        mock_store.save = Mock()

        use_case = StartEditSessionUseCase(session_store=mock_store)
        session = use_case.execute(user_id="")

        assert session.user_id == ""
        mock_store.save.assert_called_once()

    def test_execute_with_very_long_initial_text(self):
        """execute avec texte initial tres long."""
        from app.application.realtime_edit import StartEditSessionUseCase

        mock_store = Mock()
        mock_store.save = Mock()

        long_text = "a" * 100000  # 100k caracteres

        use_case = StartEditSessionUseCase(session_store=mock_store)
        session = use_case.execute(user_id="user-123", initial_text=long_text)

        assert len(session.current_text) == 100000

    def test_execute_store_raises_exception(self):
        """execute quand le store leve une exception."""
        from app.application.realtime_edit import StartEditSessionUseCase

        mock_store = Mock()
        mock_store.save = Mock(side_effect=IOError("Disk full"))

        use_case = StartEditSessionUseCase(session_store=mock_store)

        with pytest.raises(IOError):
            use_case.execute(user_id="user-123")


class TestProcessTextChangeUseCaseEdgeCases:
    """Tests edge cases pour ProcessTextChangeUseCase."""

    def test_execute_with_inactive_session(self):
        """execute avec session inactive."""
        from app.application.realtime_edit import ProcessTextChangeUseCase
        from app.domain.entities.realtime_edit import EditSession, TextChange

        mock_store = Mock()
        session = EditSession.create(user_id="user-123")
        session.close()  # Rendre inactive
        mock_store.get = Mock(return_value=session)

        change = TextChange.from_typing(
            old_text="",
            new_text="Hello",
            cursor_position=5,
        )

        use_case = ProcessTextChangeUseCase(session_store=mock_store)
        result = use_case.execute(session_id=session.session_id, change=change)

        assert result is None

    def test_execute_with_empty_session_id(self):
        """execute avec session_id vide."""
        from app.application.realtime_edit import ProcessTextChangeUseCase
        from app.domain.entities.realtime_edit import TextChange

        mock_store = Mock()
        mock_store.get = Mock(return_value=None)

        change = TextChange.from_typing(
            old_text="",
            new_text="Hello",
            cursor_position=5,
        )

        use_case = ProcessTextChangeUseCase(session_store=mock_store)
        result = use_case.execute(session_id="", change=change)

        assert result is None


class TestGetSuggestionUseCaseEdgeCases:
    """Tests edge cases pour GetSuggestionUseCase."""

    def test_execute_with_inactive_session(self):
        """execute avec session inactive."""
        from app.application.realtime_edit import GetSuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            EditTrigger,
            TriggerType,
        )

        mock_store = Mock()
        session = EditSession.create(user_id="user-123", initial_text="Hello")
        session.close()
        mock_store.get = Mock(return_value=session)

        mock_llm = Mock()
        trigger = EditTrigger(trigger_type=TriggerType.BLUR)

        use_case = GetSuggestionUseCase(session_store=mock_store, llm=mock_llm)
        result = use_case.execute(session_id=session.session_id, trigger=trigger)

        assert result is None
        mock_llm.complete.assert_not_called()

    def test_execute_llm_raises_exception(self):
        """execute quand le LLM leve une exception."""
        from app.application.realtime_edit import GetSuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            EditTrigger,
            TriggerType,
        )

        mock_store = Mock()
        session = EditSession.create(user_id="user-123", initial_text="Hello")
        mock_store.get = Mock(return_value=session)
        mock_store.save = Mock()

        mock_llm = Mock()
        mock_llm.complete = Mock(side_effect=Exception("API Error"))

        trigger = EditTrigger(trigger_type=TriggerType.BLUR)

        use_case = GetSuggestionUseCase(session_store=mock_store, llm=mock_llm)
        result = use_case.execute(session_id=session.session_id, trigger=trigger)

        # Devrait retourner None sans propager l'exception
        assert result is None

    def test_execute_with_whitespace_only_text(self):
        """execute avec texte contenant que des espaces."""
        from app.application.realtime_edit import GetSuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            EditTrigger,
            TriggerType,
        )

        mock_store = Mock()
        session = EditSession.create(user_id="user-123", initial_text="   ")
        mock_store.get = Mock(return_value=session)

        mock_llm = Mock()
        trigger = EditTrigger(trigger_type=TriggerType.BLUR)

        use_case = GetSuggestionUseCase(session_store=mock_store, llm=mock_llm)
        result = use_case.execute(session_id=session.session_id, trigger=trigger)

        # Texte vide apres strip -> pas de suggestion
        assert result is None
        mock_llm.complete.assert_not_called()

    def test_execute_llm_returns_empty_content(self):
        """execute quand le LLM retourne un contenu vide."""
        from app.application.realtime_edit import GetSuggestionUseCase
        from app.domain.entities.realtime_edit import (
            EditSession,
            EditTrigger,
            TriggerType,
        )
        from app.domain.ports.llm_port import LLMResponse

        mock_store = Mock()
        session = EditSession.create(user_id="user-123", initial_text="Hello")
        mock_store.get = Mock(return_value=session)
        mock_store.save = Mock()

        mock_llm = Mock()
        mock_llm.complete = Mock(
            return_value=LLMResponse(content="", input_tokens=10, output_tokens=0)
        )

        trigger = EditTrigger(trigger_type=TriggerType.BLUR)

        use_case = GetSuggestionUseCase(session_store=mock_store, llm=mock_llm)
        result = use_case.execute(session_id=session.session_id, trigger=trigger)

        # Devrait retourner un resultat avec suggested_text vide
        assert result is not None
        assert result.suggested_full_text == ""


class TestApplySuggestionUseCaseEdgeCases:
    """Tests edge cases pour ApplySuggestionUseCase."""

    def test_execute_original_not_in_session(self):
        """execute quand le texte original n'est pas dans la session."""
        from app.application.realtime_edit import ApplySuggestionUseCase
        from app.domain.entities.realtime_edit import EditSession, Suggestion

        mock_store = Mock()
        session = EditSession.create(user_id="user-123", initial_text="Bonjour")
        mock_store.get = Mock(return_value=session)
        mock_store.save = Mock()

        suggestion = Suggestion(
            original_text="Hello",  # N'existe pas dans la session
            suggested_text="Hi",
            confidence=0.9,
        )

        use_case = ApplySuggestionUseCase(session_store=mock_store)
        result = use_case.execute(
            session_id=session.session_id,
            suggestion=suggestion,
            accept=True,
        )

        # Le texte ne devrait pas changer (replace ne trouve rien)
        assert result.current_text == "Bonjour"

    def test_execute_with_partial_match(self):
        """execute avec correspondance partielle du texte."""
        from app.application.realtime_edit import ApplySuggestionUseCase
        from app.domain.entities.realtime_edit import EditSession, Suggestion

        mock_store = Mock()
        session = EditSession.create(
            user_id="user-123", initial_text="Hello Hello World"
        )
        mock_store.get = Mock(return_value=session)
        mock_store.save = Mock()

        suggestion = Suggestion(
            original_text="Hello",
            suggested_text="Hi",
            confidence=0.9,
        )

        use_case = ApplySuggestionUseCase(session_store=mock_store)
        result = use_case.execute(
            session_id=session.session_id,
            suggestion=suggestion,
            accept=True,
        )

        # replace() remplace TOUTES les occurrences
        assert result.current_text == "Hi Hi World"


class TestCloseEditSessionUseCaseEdgeCases:
    """Tests edge cases pour CloseEditSessionUseCase."""

    def test_execute_already_closed_session(self):
        """execute sur session deja fermee."""
        from app.application.realtime_edit import CloseEditSessionUseCase
        from app.domain.entities.realtime_edit import EditSession

        mock_store = Mock()
        session = EditSession.create(user_id="user-123")
        session.close()
        mock_store.get = Mock(return_value=session)
        mock_store.save = Mock()

        use_case = CloseEditSessionUseCase(session_store=mock_store)
        result = use_case.execute(session_id=session.session_id)

        assert result.is_active is False
        mock_store.save.assert_called_once()


class TestCleanupExpiredSessionsUseCaseEdgeCases:
    """Tests edge cases pour CleanupExpiredSessionsUseCase."""

    def test_execute_with_no_expired_sessions(self):
        """execute sans sessions expirees."""
        from app.application.realtime_edit import CleanupExpiredSessionsUseCase

        mock_store = Mock()
        mock_store.cleanup_expired = Mock(return_value=0)

        use_case = CleanupExpiredSessionsUseCase(session_store=mock_store)
        count = use_case.execute()

        assert count == 0

    def test_execute_with_custom_timeout(self):
        """execute avec timeout personnalise."""
        from app.application.realtime_edit import CleanupExpiredSessionsUseCase

        mock_store = Mock()
        mock_store.cleanup_expired = Mock(return_value=5)

        use_case = CleanupExpiredSessionsUseCase(
            session_store=mock_store, timeout_minutes=60
        )
        count = use_case.execute()

        mock_store.cleanup_expired.assert_called_with(60)
        assert count == 5


# =============================================================================
# TESTS EDGE CASES - INFRASTRUCTURE (STORE)
# =============================================================================


class TestJsonEditSessionStoreEdgeCases:
    """Tests edge cases pour JsonEditSessionStore."""

    def test_init_creates_parent_directories(self):
        """init cree les repertoires parents."""
        from app.infrastructure.realtime_edit_store import JsonEditSessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "subdir" / "nested" / "sessions.json"

            JsonEditSessionStore(filepath)

            assert filepath.exists()

    def test_load_corrupted_json(self):
        """Chargement d'un fichier JSON corrompu."""
        from app.infrastructure.realtime_edit_store import JsonEditSessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "sessions.json"
            filepath.write_text("{ invalid json }", encoding="utf-8")

            store = JsonEditSessionStore(filepath)

            # get() devrait retourner None, pas lever d'exception
            result = store.get("nonexistent")
            assert result is None

    def test_load_empty_file(self):
        """Chargement d'un fichier vide."""
        from app.infrastructure.realtime_edit_store import JsonEditSessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "sessions.json"
            filepath.write_text("", encoding="utf-8")

            store = JsonEditSessionStore(filepath)

            result = store.get("nonexistent")
            assert result is None

    def test_save_and_retrieve_session(self):
        """Sauvegarde et recuperation d'une session."""
        from app.infrastructure.realtime_edit_store import JsonEditSessionStore
        from app.domain.entities.realtime_edit import EditSession

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "sessions.json"
            store = JsonEditSessionStore(filepath)

            session = EditSession.create(user_id="user-123", initial_text="Hello")
            store.save(session)

            retrieved = store.get(session.session_id)

            assert retrieved is not None
            assert retrieved.session_id == session.session_id
            assert retrieved.current_text == "Hello"

    def test_delete_nonexistent_session(self):
        """Suppression d'une session inexistante."""
        from app.infrastructure.realtime_edit_store import JsonEditSessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "sessions.json"
            store = JsonEditSessionStore(filepath)

            result = store.delete("nonexistent-id")

            assert result is False

    def test_get_by_user_no_sessions(self):
        """get_by_user sans sessions pour l'utilisateur."""
        from app.infrastructure.realtime_edit_store import JsonEditSessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "sessions.json"
            store = JsonEditSessionStore(filepath)

            sessions = store.get_by_user("nonexistent-user")

            assert sessions == []

    def test_get_by_user_filters_inactive(self):
        """get_by_user filtre les sessions inactives."""
        from app.infrastructure.realtime_edit_store import JsonEditSessionStore
        from app.domain.entities.realtime_edit import EditSession

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "sessions.json"
            store = JsonEditSessionStore(filepath)

            # Creer une session active et une inactive
            active_session = EditSession.create(user_id="user-123")
            inactive_session = EditSession.create(user_id="user-123")
            inactive_session.close()

            store.save(active_session)
            store.save(inactive_session)

            sessions = store.get_by_user("user-123")

            assert len(sessions) == 1
            assert sessions[0].is_active is True

    def test_cleanup_expired_no_expired(self):
        """cleanup_expired sans sessions expirees."""
        from app.infrastructure.realtime_edit_store import JsonEditSessionStore
        from app.domain.entities.realtime_edit import EditSession

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "sessions.json"
            store = JsonEditSessionStore(filepath)

            session = EditSession.create(user_id="user-123")
            store.save(session)

            count = store.cleanup_expired(timeout_minutes=30)

            assert count == 0
            assert store.get(session.session_id) is not None

    def test_get_all_active(self):
        """get_all_active retourne uniquement les sessions actives."""
        from app.infrastructure.realtime_edit_store import JsonEditSessionStore
        from app.domain.entities.realtime_edit import EditSession

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "sessions.json"
            store = JsonEditSessionStore(filepath)

            session1 = EditSession.create(user_id="user-1")
            session2 = EditSession.create(user_id="user-2")
            session3 = EditSession.create(user_id="user-3")
            session3.close()

            store.save(session1)
            store.save(session2)
            store.save(session3)

            active = store.get_all_active()

            assert len(active) == 2


class TestInMemoryEditSessionStoreEdgeCases:
    """Tests edge cases pour InMemoryEditSessionStore."""

    def test_clear_removes_all_sessions(self):
        """clear supprime toutes les sessions."""
        from app.infrastructure.realtime_edit_store import InMemoryEditSessionStore
        from app.domain.entities.realtime_edit import EditSession

        store = InMemoryEditSessionStore()

        session1 = EditSession.create(user_id="user-1")
        session2 = EditSession.create(user_id="user-2")

        store.save(session1)
        store.save(session2)

        store.clear()

        assert store.get(session1.session_id) is None
        assert store.get(session2.session_id) is None

    def test_concurrent_access(self):
        """Acces concurrent au store."""
        from app.infrastructure.realtime_edit_store import InMemoryEditSessionStore
        from app.domain.entities.realtime_edit import EditSession
        import threading

        store = InMemoryEditSessionStore()
        sessions_created = []
        errors = []

        def create_sessions(user_id: str, count: int):
            try:
                for i in range(count):
                    session = EditSession.create(user_id=f"{user_id}-{i}")
                    store.save(session)
                    sessions_created.append(session.session_id)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=create_sessions, args=(f"user-{i}", 10))
            for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(sessions_created) == 50


# =============================================================================
# TESTS EDGE CASES - API REST
# =============================================================================


class TestRealTimeEditAPIEdgeCases:
    """Tests edge cases pour l'API REST."""

    @pytest.fixture
    def client(self):
        """Client de test Flask."""
        from app.api.app import create_app
        from app.infrastructure.container import get_container, reset_container
        from app.domain.ports.llm_port import LLMResponse

        reset_container()
        container = get_container()

        mock_llm = Mock()
        mock_llm.name = "mock"
        mock_llm.model = "mock-model"
        mock_llm.complete = Mock(
            return_value=LLMResponse(
                content="Corrected text",
                input_tokens=10,
                output_tokens=5,
            )
        )
        container._llm = mock_llm

        app = create_app({"TESTING": True})
        return app.test_client()

    def test_start_session_missing_user_id(self, client):
        """POST /sessions sans user_id dans le body.

        Audit 2026-04-25 (HIGH-Backend-1) : l'API ignore le user_id du body
        et bind la session à l'identité JWT (ou loopback Tauri en dev). Donc
        un body vide sur loopback produit une session valide (201) ;
        un body vide sans JWT/loopback produit 401.
        """
        response = client.post(
            "/api/realtime-edit/sessions",
            json={},
        )

        # En tests Flask, request.remote_addr=='127.0.0.1' → loopback Tauri →
        # session créée sous l'identité "loopback:tauri".
        assert response.status_code == 201
        data = response.get_json()
        assert data["user_id"] == "loopback:tauri"

    def test_start_session_empty_user_id(self, client):
        """POST /sessions avec user_id vide dans le body.

        Même remarque que test_start_session_missing_user_id : le body est
        ignoré, l'identité provient du JWT / loopback.
        """
        response = client.post(
            "/api/realtime-edit/sessions",
            json={"user_id": ""},
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["user_id"] == "loopback:tauri"

    def test_start_session_invalid_json(self, client):
        """POST /sessions avec JSON invalide."""
        response = client.post(
            "/api/realtime-edit/sessions",
            data="not json",
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_text_missing_new_text(self, client):
        """PUT /sessions/<id>/text sans new_text."""
        # Creer une session d'abord
        create_response = client.post(
            "/api/realtime-edit/sessions",
            json={"user_id": "user-123"},
        )
        session_id = create_response.get_json()["session_id"]

        response = client.put(
            f"/api/realtime-edit/sessions/{session_id}/text",
            json={"old_text": ""},
        )

        assert response.status_code == 400
        assert "new_text" in response.get_json()["error"]

    def test_update_text_nonexistent_session(self, client):
        """PUT /sessions/<id>/text avec session inexistante."""
        response = client.put(
            "/api/realtime-edit/sessions/nonexistent-id/text",
            json={"old_text": "", "new_text": "Hello"},
        )

        assert response.status_code == 404

    def test_get_suggestion_nonexistent_session(self, client):
        """POST /sessions/<id>/suggest avec session inexistante.

        Audit 2026-04-25 (HIGH-Backend-1) : l'API renvoie 404 pour une
        session inconnue (et pour une session d'un autre utilisateur, même
        envelope pour ne pas leak l'existence). Pas de fallback "no
        suggestion" en 200.
        """
        response = client.post(
            "/api/realtime-edit/sessions/nonexistent-id/suggest",
            json={"trigger": "blur"},
        )

        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data

    def test_apply_suggestion_missing_texts(self, client):
        """POST /sessions/<id>/apply sans textes."""
        create_response = client.post(
            "/api/realtime-edit/sessions",
            json={"user_id": "user-123"},
        )
        session_id = create_response.get_json()["session_id"]

        response = client.post(
            f"/api/realtime-edit/sessions/{session_id}/apply",
            json={"accept": True},
        )

        assert response.status_code == 400

    def test_apply_suggestion_empty_texts(self, client):
        """POST /sessions/<id>/apply avec textes vides."""
        create_response = client.post(
            "/api/realtime-edit/sessions",
            json={"user_id": "user-123"},
        )
        session_id = create_response.get_json()["session_id"]

        response = client.post(
            f"/api/realtime-edit/sessions/{session_id}/apply",
            json={
                "original_text": "",
                "suggested_text": "",
                "accept": True,
            },
        )

        assert response.status_code == 400

    def test_close_nonexistent_session(self, client):
        """DELETE /sessions/<id> avec session inexistante."""
        response = client.delete("/api/realtime-edit/sessions/nonexistent-id")

        assert response.status_code == 404

    def test_get_nonexistent_session(self, client):
        """GET /sessions/<id> avec session inexistante."""
        response = client.get("/api/realtime-edit/sessions/nonexistent-id")

        assert response.status_code == 404

    def test_suggest_with_invalid_trigger(self, client):
        """POST /sessions/<id>/suggest avec trigger invalide."""
        create_response = client.post(
            "/api/realtime-edit/sessions",
            json={"user_id": "user-123", "initial_text": "Hello"},
        )
        session_id = create_response.get_json()["session_id"]

        response = client.post(
            f"/api/realtime-edit/sessions/{session_id}/suggest",
            json={"trigger": "invalid_trigger"},
        )

        # Trigger invalide = NONE = pas de suggestion
        assert response.status_code == 200
        data = response.get_json()
        assert "message" in data or data.get("suggested_full_text") is None

    def test_suggest_with_empty_trigger(self, client):
        """POST /sessions/<id>/suggest avec trigger vide."""
        create_response = client.post(
            "/api/realtime-edit/sessions",
            json={"user_id": "user-123", "initial_text": "Hello"},
        )
        session_id = create_response.get_json()["session_id"]

        response = client.post(
            f"/api/realtime-edit/sessions/{session_id}/suggest",
            json={"trigger": ""},
        )

        assert response.status_code == 200

    def test_full_workflow(self, client):
        """Test du workflow complet."""
        # 1. Creer session
        create_response = client.post(
            "/api/realtime-edit/sessions",
            json={"user_id": "user-123"},
        )
        assert create_response.status_code == 201
        session_id = create_response.get_json()["session_id"]

        # 2. Mettre a jour le texte
        update_response = client.put(
            f"/api/realtime-edit/sessions/{session_id}/text",
            json={
                "old_text": "",
                "new_text": "je veut manger",
                "cursor_position": 14,
            },
        )
        assert update_response.status_code == 200

        # 3. Obtenir une suggestion
        suggest_response = client.post(
            f"/api/realtime-edit/sessions/{session_id}/suggest",
            json={"trigger": "blur"},
        )
        assert suggest_response.status_code == 200

        # 4. Appliquer la suggestion
        apply_response = client.post(
            f"/api/realtime-edit/sessions/{session_id}/apply",
            json={
                "original_text": "je veut",
                "suggested_text": "Je veux",
                "accept": True,
            },
        )
        assert apply_response.status_code == 200

        # 5. Verifier l'etat
        get_response = client.get(f"/api/realtime-edit/sessions/{session_id}")
        assert get_response.status_code == 200

        # 6. Fermer la session
        close_response = client.delete(f"/api/realtime-edit/sessions/{session_id}")
        assert close_response.status_code == 200
        assert close_response.get_json()["is_active"] is False


# =============================================================================
# TESTS EDGE CASES - VALIDATION
# =============================================================================


class TestValidationEdgeCases:
    """Tests pour les validations de donnees."""

    def test_session_id_format_uuid(self):
        """Le session_id doit etre un UUID valide."""
        from app.domain.entities.realtime_edit import EditSession
        import uuid

        session = EditSession.create(user_id="user-123")

        # Verifier que c'est un UUID valide
        try:
            uuid.UUID(session.session_id)
            is_valid_uuid = True
        except ValueError:
            is_valid_uuid = False

        assert is_valid_uuid is True

    def test_suggestion_id_format_uuid(self):
        """Le suggestion_id doit etre un UUID valide."""
        from app.domain.entities.realtime_edit import Suggestion
        import uuid

        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9,
        )

        try:
            uuid.UUID(suggestion.suggestion_id)
            is_valid_uuid = True
        except ValueError:
            is_valid_uuid = False

        assert is_valid_uuid is True

    def test_timestamps_are_datetime(self):
        """Les timestamps doivent etre des datetime."""
        from app.domain.entities.realtime_edit import EditSession, Suggestion

        session = EditSession.create(user_id="user-123")
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9,
        )

        assert isinstance(session.created_at, datetime)
        assert isinstance(suggestion.created_at, datetime)


# =============================================================================
# TESTS EDGE CASES - PERFORMANCES
# =============================================================================


class TestPerformanceEdgeCases:
    """Tests de performance pour les edge cases."""

    def test_many_sessions_cleanup(self):
        """Cleanup avec beaucoup de sessions."""
        from app.infrastructure.realtime_edit_store import InMemoryEditSessionStore
        from app.domain.entities.realtime_edit import EditSession

        store = InMemoryEditSessionStore()

        # Creer 1000 sessions dont 500 expirees
        for i in range(1000):
            session = EditSession.create(user_id=f"user-{i}")
            if i < 500:
                # Simuler une session expiree
                session._last_activity_at = datetime.now() - timedelta(hours=1)
            store.save(session)

        count = store.cleanup_expired(timeout_minutes=30)

        assert count == 500

    def test_large_text_handling(self):
        """Gestion de textes tres longs."""
        from app.domain.entities.realtime_edit import EditSession, Suggestion

        large_text = "a" * 1000000  # 1MB de texte

        session = EditSession.create(user_id="user-123", initial_text=large_text)
        assert len(session.current_text) == 1000000

        suggestion = Suggestion(
            original_text=large_text,
            suggested_text=large_text.upper(),
            confidence=0.9,
        )

        # get_diffs sur un gros texte
        diffs = suggestion.get_diffs()
        assert len(diffs) >= 1
