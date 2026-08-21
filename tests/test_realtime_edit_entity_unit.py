# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour les entités realtime_edit."""

import pytest
from datetime import datetime
from app.domain.entities.realtime_edit import (
    ChangeType,
    TriggerType,
    SuggestionStatus,
    TextDiff,
    TextChange,
    EditTrigger,
    Suggestion,
    SuggestionResult,
    EditSession,
)


class TestTextDiff:
    """Tests pour TextDiff."""

    def test_is_insertion(self):
        diff = TextDiff(start=0, end=0, original="", replacement="hello")
        assert diff.is_insertion is True
        assert diff.is_deletion is False

    def test_is_deletion(self):
        diff = TextDiff(start=0, end=5, original="hello", replacement="")
        assert diff.is_deletion is True
        assert diff.is_insertion is False

    def test_is_replacement(self):
        diff = TextDiff(start=0, end=5, original="hello", replacement="world")
        assert diff.is_insertion is False
        assert diff.is_deletion is False

    def test_empty_diff(self):
        diff = TextDiff(start=0, end=0, original="", replacement="")
        assert diff.is_insertion is False
        assert diff.is_deletion is False


class TestTextChange:
    """Tests pour TextChange."""

    def test_from_typing_insert(self):
        change = TextChange.from_typing("hello", "hello world", cursor_position=11)
        assert change.change_type == ChangeType.INSERT
        assert change.new_text == "hello world"

    def test_from_typing_delete(self):
        change = TextChange.from_typing("hello world", "hello", cursor_position=5)
        assert change.change_type == ChangeType.DELETE

    def test_from_typing_replace(self):
        change = TextChange.from_typing("hello", "world", cursor_position=5)
        assert change.change_type == ChangeType.REPLACE

    def test_detect_change_type_insert(self):
        assert TextChange._detect_change_type("abc", "abcd") == ChangeType.INSERT

    def test_detect_change_type_delete(self):
        assert TextChange._detect_change_type("abcd", "abc") == ChangeType.DELETE

    def test_detect_change_type_replace(self):
        assert TextChange._detect_change_type("abc", "xyz") == ChangeType.REPLACE

    def test_timestamp_auto_set(self):
        change = TextChange.from_typing("a", "ab", 2)
        assert isinstance(change.timestamp, datetime)


class TestEditTrigger:
    """Tests pour EditTrigger."""

    def test_should_process_blur(self):
        trigger = EditTrigger(trigger_type=TriggerType.BLUR)
        assert trigger.should_process is True

    def test_should_process_none(self):
        trigger = EditTrigger(trigger_type=TriggerType.NONE)
        assert trigger.should_process is False

    def test_should_process_manual(self):
        trigger = EditTrigger(trigger_type=TriggerType.MANUAL)
        assert trigger.should_process is True

    def test_should_process_typing_pause(self):
        trigger = EditTrigger(trigger_type=TriggerType.TYPING_PAUSE)
        assert trigger.should_process is True

    def test_from_string_blur(self):
        trigger = EditTrigger.from_string("blur")
        assert trigger.trigger_type == TriggerType.BLUR

    def test_from_string_manual(self):
        trigger = EditTrigger.from_string("manual")
        assert trigger.trigger_type == TriggerType.MANUAL

    def test_from_string_typing_pause(self):
        trigger = EditTrigger.from_string("typing_pause")
        assert trigger.trigger_type == TriggerType.TYPING_PAUSE

    def test_from_string_sentence_end(self):
        trigger = EditTrigger.from_string("sentence_end")
        assert trigger.trigger_type == TriggerType.SENTENCE_END

    def test_from_string_none(self):
        trigger = EditTrigger.from_string("none")
        assert trigger.trigger_type == TriggerType.NONE

    def test_from_string_unknown_defaults_to_none(self):
        trigger = EditTrigger.from_string("unknown_trigger")
        assert trigger.trigger_type == TriggerType.NONE

    def test_from_string_case_insensitive(self):
        trigger = EditTrigger.from_string("BLUR")
        assert trigger.trigger_type == TriggerType.BLUR


class TestSuggestion:
    """Tests pour Suggestion."""

    def test_create_suggestion(self):
        s = Suggestion(original_text="helo", suggested_text="hello", confidence=0.9)
        assert s.original_text == "helo"
        assert s.suggested_text == "hello"
        assert s.status == SuggestionStatus.PENDING

    def test_accept(self):
        s = Suggestion(original_text="a", suggested_text="b", confidence=0.8)
        s.accept()
        assert s.status == SuggestionStatus.ACCEPTED

    def test_reject(self):
        s = Suggestion(original_text="a", suggested_text="b", confidence=0.8)
        s.reject()
        assert s.status == SuggestionStatus.REJECTED

    def test_get_diffs_replace(self):
        s = Suggestion(original_text="hello wrold", suggested_text="hello world", confidence=0.9)
        diffs = s.get_diffs()
        assert len(diffs) > 0

    def test_get_diffs_identical(self):
        s = Suggestion(original_text="hello world", suggested_text="hello world", confidence=0.9)
        diffs = s.get_diffs()
        assert len(diffs) == 0

    def test_get_diffs_insertion(self):
        s = Suggestion(original_text="hello", suggested_text="hello world", confidence=0.9)
        diffs = s.get_diffs()
        assert len(diffs) == 1
        assert diffs[0].is_insertion

    def test_get_diffs_deletion(self):
        s = Suggestion(original_text="hello cruel world", suggested_text="hello world", confidence=0.9)
        diffs = s.get_diffs()
        assert len(diffs) > 0

    def test_suggestion_id_unique(self):
        s1 = Suggestion(original_text="a", suggested_text="b", confidence=0.5)
        s2 = Suggestion(original_text="a", suggested_text="b", confidence=0.5)
        assert s1.suggestion_id != s2.suggestion_id

    def test_default_suggestion_types_empty(self):
        s = Suggestion(original_text="a", suggested_text="b", confidence=0.5)
        assert s.suggestion_types == []


class TestSuggestionResult:
    """Tests pour SuggestionResult."""

    def test_has_changes_true(self):
        result = SuggestionResult(
            session_id="s1",
            original_full_text="hello",
            suggested_full_text="hello world",
        )
        assert result.has_changes is True

    def test_has_changes_false_same_text(self):
        result = SuggestionResult(
            session_id="s1",
            original_full_text="hello",
            suggested_full_text="hello",
        )
        assert result.has_changes is False

    def test_has_changes_false_none(self):
        result = SuggestionResult(
            session_id="s1",
            original_full_text="hello",
        )
        assert result.has_changes is False

    def test_default_values(self):
        result = SuggestionResult(session_id="s1", original_full_text="test")
        assert result.suggestions == []
        assert result.processing_time_ms == 0


class TestEditSession:
    """Tests pour EditSession."""

    def test_create_session(self):
        session = EditSession.create(user_id="user1", initial_text="hello")
        assert session.user_id == "user1"
        assert session.current_text == "hello"
        assert session.is_active is True
        assert session.version == 1

    def test_create_session_empty_text(self):
        session = EditSession.create(user_id="user1")
        assert session.current_text == ""

    def test_update_text(self):
        session = EditSession.create(user_id="user1", initial_text="hello")
        session.update_text("hello world")
        assert session.current_text == "hello world"
        assert session.version == 2

    def test_update_text_none_raises(self):
        session = EditSession.create(user_id="user1")
        with pytest.raises(TypeError):
            session.update_text(None)

    def test_close_session(self):
        session = EditSession.create(user_id="user1")
        session.close()
        assert session.is_active is False
        assert session.closed_at is not None

    def test_is_expired_closed_session(self):
        session = EditSession.create(user_id="user1")
        session.close()
        assert session.is_expired() is True

    def test_is_expired_recent_session(self):
        session = EditSession.create(user_id="user1")
        assert session.is_expired(timeout_minutes=30) is False

    def test_has_conflict_different_text(self):
        session = EditSession.create(user_id="user1", initial_text="hello")
        assert session.has_conflict("world") is True

    def test_has_conflict_same_text(self):
        session = EditSession.create(user_id="user1", initial_text="hello")
        assert session.has_conflict("hello") is False

    def test_has_conflict_empty_base(self):
        session = EditSession.create(user_id="user1", initial_text="hello")
        assert session.has_conflict("") is False

    def test_mark_processed_and_needs_processing(self):
        session = EditSession.create(user_id="user1", initial_text="hello")
        assert session.needs_processing is True
        session.mark_processed()
        assert session.needs_processing is False

    def test_needs_processing_after_update(self):
        session = EditSession.create(user_id="user1", initial_text="hello")
        session.mark_processed()
        session.update_text("hello world")
        assert session.needs_processing is True

    def test_session_id_unique(self):
        s1 = EditSession.create(user_id="user1")
        s2 = EditSession.create(user_id="user1")
        assert s1.session_id != s2.session_id

    def test_last_activity_at_updated_on_text_change(self):
        session = EditSession.create(user_id="user1")
        initial_activity = session.last_activity_at
        import time
        time.sleep(0.01)
        session.update_text("new text")
        assert session.last_activity_at >= initial_activity

    def test_version_increments_on_each_update(self):
        session = EditSession.create(user_id="user1")
        session.update_text("v2")
        session.update_text("v3")
        session.update_text("v4")
        assert session.version == 4
