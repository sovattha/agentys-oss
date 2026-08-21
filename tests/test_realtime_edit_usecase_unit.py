# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour les use cases realtime_edit."""

from unittest.mock import MagicMock
from app.application.realtime_edit import (
    StartEditSessionUseCase,
    ProcessTextChangeUseCase,
    GetSuggestionUseCase,
    ApplySuggestionUseCase,
    CloseEditSessionUseCase,
    GetEditSessionUseCase,
    CleanupExpiredSessionsUseCase,
)
from app.domain.entities.realtime_edit import (
    EditSession,
    TextChange,
    ChangeType,
    EditTrigger,
    TriggerType,
    Suggestion,
    SuggestionStatus,
)


class TestStartEditSessionUseCase:
    """Tests pour StartEditSessionUseCase."""

    def test_execute_creates_session(self):
        store = MagicMock()
        uc = StartEditSessionUseCase(session_store=store)

        session = uc.execute(user_id="user1", initial_text="Hello")

        assert session.user_id == "user1"
        assert session.current_text == "Hello"
        assert session.is_active is True
        store.save.assert_called_once_with(session)

    def test_execute_empty_text(self):
        store = MagicMock()
        uc = StartEditSessionUseCase(session_store=store)

        session = uc.execute(user_id="user1")

        assert session.current_text == ""
        store.save.assert_called_once()


class TestProcessTextChangeUseCase:
    """Tests pour ProcessTextChangeUseCase."""

    def test_execute_updates_text(self):
        session = EditSession.create(user_id="user1", initial_text="hello")
        store = MagicMock()
        store.get.return_value = session
        uc = ProcessTextChangeUseCase(session_store=store)
        change = TextChange(
            old_text="hello", new_text="hello world",
            cursor_position=11, change_type=ChangeType.INSERT,
        )

        result = uc.execute(session_id=session.session_id, change=change)

        assert result.current_text == "hello world"
        store.save.assert_called_once()

    def test_execute_session_not_found(self):
        store = MagicMock()
        store.get.return_value = None
        uc = ProcessTextChangeUseCase(session_store=store)
        change = TextChange(
            old_text="", new_text="x",
            cursor_position=1, change_type=ChangeType.INSERT,
        )

        result = uc.execute(session_id="nonexistent", change=change)

        assert result is None

    def test_execute_inactive_session(self):
        session = EditSession.create(user_id="user1")
        session.close()
        store = MagicMock()
        store.get.return_value = session
        uc = ProcessTextChangeUseCase(session_store=store)
        change = TextChange(
            old_text="", new_text="x",
            cursor_position=1, change_type=ChangeType.INSERT,
        )

        result = uc.execute(session_id=session.session_id, change=change)

        assert result is None


class TestGetSuggestionUseCase:
    """Tests pour GetSuggestionUseCase."""

    def _make_session_store(self, session=None):
        store = MagicMock()
        store.get.return_value = session
        return store

    def _make_llm(self, response_content="corrected text"):
        llm = MagicMock()
        response = MagicMock()
        response.content = response_content
        llm.complete.return_value = response
        return llm

    def test_execute_no_trigger(self):
        store = self._make_session_store()
        llm = self._make_llm()
        uc = GetSuggestionUseCase(session_store=store, llm=llm)
        trigger = EditTrigger(trigger_type=TriggerType.NONE)

        result = uc.execute(session_id="s1", trigger=trigger)

        assert result is None

    def test_execute_session_not_found(self):
        store = self._make_session_store(session=None)
        llm = self._make_llm()
        uc = GetSuggestionUseCase(session_store=store, llm=llm)
        trigger = EditTrigger(trigger_type=TriggerType.MANUAL)

        result = uc.execute(session_id="nonexistent", trigger=trigger)

        assert result is None

    def test_execute_inactive_session(self):
        session = EditSession.create(user_id="user1", initial_text="hello")
        session.close()
        store = self._make_session_store(session=session)
        llm = self._make_llm()
        uc = GetSuggestionUseCase(session_store=store, llm=llm)
        trigger = EditTrigger(trigger_type=TriggerType.MANUAL)

        result = uc.execute(session_id=session.session_id, trigger=trigger)

        assert result is None

    def test_execute_empty_text(self):
        session = EditSession.create(user_id="user1", initial_text="   ")
        store = self._make_session_store(session=session)
        llm = self._make_llm()
        uc = GetSuggestionUseCase(session_store=store, llm=llm)
        trigger = EditTrigger(trigger_type=TriggerType.MANUAL)

        result = uc.execute(session_id=session.session_id, trigger=trigger)

        assert result is None

    def test_execute_with_correction(self):
        session = EditSession.create(user_id="user1", initial_text="helo wrold")
        store = self._make_session_store(session=session)
        llm = self._make_llm(response_content="hello world")
        uc = GetSuggestionUseCase(session_store=store, llm=llm)
        trigger = EditTrigger(trigger_type=TriggerType.MANUAL)

        result = uc.execute(session_id=session.session_id, trigger=trigger)

        assert result is not None
        assert result.suggested_full_text == "hello world"
        assert result.has_changes is True
        assert len(result.suggestions) == 1
        store.save.assert_called()

    def test_execute_no_changes_needed(self):
        session = EditSession.create(user_id="user1", initial_text="hello world")
        store = self._make_session_store(session=session)
        llm = self._make_llm(response_content="hello world")
        uc = GetSuggestionUseCase(session_store=store, llm=llm)
        trigger = EditTrigger(trigger_type=TriggerType.MANUAL)

        result = uc.execute(session_id=session.session_id, trigger=trigger)

        assert result is not None
        assert result.has_changes is False
        assert result.suggestions == []

    def test_execute_llm_exception_returns_none(self):
        session = EditSession.create(user_id="user1", initial_text="hello")
        store = self._make_session_store(session=session)
        llm = MagicMock()
        llm.complete.side_effect = Exception("LLM error")
        uc = GetSuggestionUseCase(session_store=store, llm=llm)
        trigger = EditTrigger(trigger_type=TriggerType.MANUAL)

        result = uc.execute(session_id=session.session_id, trigger=trigger)

        assert result is None

    def test_execute_truncates_long_text(self):
        long_text = "x" * 6000
        session = EditSession.create(user_id="user1", initial_text=long_text)
        store = self._make_session_store(session=session)
        llm = self._make_llm(response_content="truncated")
        uc = GetSuggestionUseCase(session_store=store, llm=llm, max_text_length=100)
        trigger = EditTrigger(trigger_type=TriggerType.MANUAL)

        result = uc.execute(session_id=session.session_id, trigger=trigger)

        assert result is not None
        # LLM was called with truncated text
        call_args = llm.complete.call_args
        assert len(call_args.kwargs["user"]) <= 100


class TestApplySuggestionUseCase:
    """Tests pour ApplySuggestionUseCase."""

    def test_accept_suggestion(self):
        session = EditSession.create(user_id="user1", initial_text="helo world")
        store = MagicMock()
        store.get.return_value = session
        uc = ApplySuggestionUseCase(session_store=store)
        suggestion = Suggestion(
            original_text="helo",
            suggested_text="hello",
            confidence=0.9,
        )

        result = uc.execute(
            session_id=session.session_id,
            suggestion=suggestion,
            accept=True,
        )

        assert result is not None
        assert "hello world" in result.current_text
        assert suggestion.status == SuggestionStatus.ACCEPTED
        store.save.assert_called_once()

    def test_reject_suggestion(self):
        session = EditSession.create(user_id="user1", initial_text="helo world")
        store = MagicMock()
        store.get.return_value = session
        uc = ApplySuggestionUseCase(session_store=store)
        suggestion = Suggestion(
            original_text="helo",
            suggested_text="hello",
            confidence=0.9,
        )

        result = uc.execute(
            session_id=session.session_id,
            suggestion=suggestion,
            accept=False,
        )

        assert result is not None
        assert result.current_text == "helo world"
        assert suggestion.status == SuggestionStatus.REJECTED

    def test_session_not_found(self):
        store = MagicMock()
        store.get.return_value = None
        uc = ApplySuggestionUseCase(session_store=store)
        suggestion = Suggestion(original_text="a", suggested_text="b", confidence=0.5)

        result = uc.execute(session_id="nonexistent", suggestion=suggestion, accept=True)

        assert result is None


class TestCloseEditSessionUseCase:
    """Tests pour CloseEditSessionUseCase."""

    def test_close_session(self):
        session = EditSession.create(user_id="user1")
        store = MagicMock()
        store.get.return_value = session
        uc = CloseEditSessionUseCase(session_store=store)

        result = uc.execute(session_id=session.session_id)

        assert result is not None
        assert result.is_active is False
        store.save.assert_called_once()

    def test_close_nonexistent_session(self):
        store = MagicMock()
        store.get.return_value = None
        uc = CloseEditSessionUseCase(session_store=store)

        result = uc.execute(session_id="nonexistent")

        assert result is None


class TestGetEditSessionUseCase:
    """Tests pour GetEditSessionUseCase."""

    def test_get_existing_session(self):
        session = EditSession.create(user_id="user1")
        store = MagicMock()
        store.get.return_value = session
        uc = GetEditSessionUseCase(session_store=store)

        result = uc.execute(session_id=session.session_id)

        assert result == session

    def test_get_nonexistent_session(self):
        store = MagicMock()
        store.get.return_value = None
        uc = GetEditSessionUseCase(session_store=store)

        result = uc.execute(session_id="nonexistent")

        assert result is None


class TestCleanupExpiredSessionsUseCase:
    """Tests pour CleanupExpiredSessionsUseCase."""

    def test_cleanup(self):
        store = MagicMock()
        store.cleanup_expired.return_value = 5
        uc = CleanupExpiredSessionsUseCase(session_store=store, timeout_minutes=60)

        result = uc.execute()

        assert result == 5
        store.cleanup_expired.assert_called_once_with(60)

    def test_cleanup_default_timeout(self):
        store = MagicMock()
        store.cleanup_expired.return_value = 0
        uc = CleanupExpiredSessionsUseCase(session_store=store)

        uc.execute()

        store.cleanup_expired.assert_called_once_with(30)
