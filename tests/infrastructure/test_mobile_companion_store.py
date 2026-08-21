# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour app/infrastructure/mobile_companion_store.py

Ce module teste les stores de persistance pour l'app mobile companion :
- JsonFileMobileSessionStore
- JsonFileMobileSyncStore
- JsonFileMobileDraftActionStore
- JsonFileMobileAnalyticsStore
- JsonFileMobilePreferencesStore
- JsonFileMobileAppConfigStore
- Factory functions et singletons
"""

import json
import pytest
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.infrastructure.mobile_companion_store import (
    JsonFileMobileSessionStore,
    JsonFileMobileSyncStore,
    JsonFileMobileDraftActionStore,
    JsonFileMobileAnalyticsStore,
    JsonFileMobilePreferencesStore,
    JsonFileMobileAppConfigStore,
    get_mobile_session_store,
    get_mobile_sync_store,
    get_mobile_action_store,
    get_mobile_analytics_store,
    get_mobile_preferences_store,
    get_mobile_config_store,
    reset_mobile_stores,
)
from app.domain.entities.mobile_companion import (
    MobileSyncState,
    MobileAnalyticsEvent,
    MobileDraft,
    MobileUserPreferences,
    MobileAppConfig,
    MobileDraftActionRequest,
    MobileEventType,
    MobileDraftAction,
    NotificationPreference,
    SyncFrequency,
)


class TestJsonFileMobileSessionStore:
    """Tests pour JsonFileMobileSessionStore."""

    @pytest.fixture
    def temp_file(self, tmp_path):
        """Crée un fichier temporaire pour les tests."""
        return tmp_path / "sessions.json"

    @pytest.fixture
    def store(self, temp_file):
        """Crée un store pour les tests."""
        return JsonFileMobileSessionStore(temp_file)

    def test_init_creates_empty_store(self, store):
        assert store._sessions == {}

    def test_init_loads_existing_sessions(self, temp_file):
        session_data = {
            "sessions": [
                {
                    "session_id": "sess-123",
                    "user_id": "user-1",
                    "device_token": "token-abc",
                    "started_at": "2024-01-15T10:00:00",
                    "last_activity_at": "2024-01-15T10:30:00",
                    "app_version": "1.0.0",
                    "os_version": "iOS 17",
                    "device_model": "iPhone 15",
                    "is_active": True,
                }
            ],
            "updated_at": "2024-01-15T10:30:00",
        }
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(json.dumps(session_data))
        store = JsonFileMobileSessionStore(temp_file)
        assert "sess-123" in store._sessions
        assert store._sessions["sess-123"].user_id == "user-1"

    def test_init_handles_corrupted_file(self, temp_file):
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text("invalid json {{{")
        store = JsonFileMobileSessionStore(temp_file)
        assert store._sessions == {}

    def test_create_session(self, store):
        session = store.create(
            user_id="user-1",
            device_token="token-abc",
            app_version="1.0.0",
            os_version="iOS 17",
            device_model="iPhone 15",
        )
        assert session.user_id == "user-1"
        assert session.device_token == "token-abc"
        assert session.app_version == "1.0.0"
        assert session.os_version == "iOS 17"
        assert session.device_model == "iPhone 15"
        assert session.is_active
        assert session.session_id in store._sessions

    def test_create_session_without_optional_fields(self, store):
        session = store.create(user_id="user-1")
        assert session.user_id == "user-1"
        assert session.device_token is None
        assert session.app_version is None

    def test_get_session(self, store):
        session = store.create(user_id="user-1")
        retrieved = store.get(session.session_id)
        assert retrieved == session

    def test_get_session_not_found(self, store):
        result = store.get("nonexistent-id")
        assert result is None

    def test_get_active_by_user(self, store):
        store.create(user_id="user-1")
        store.create(user_id="user-1")
        store.create(user_id="user-2")
        active = store.get_active_by_user("user-1")
        assert len(active) == 2
        assert all(s.user_id == "user-1" for s in active)

    def test_get_active_by_user_excludes_inactive(self, store):
        s1 = store.create(user_id="user-1")
        s2 = store.create(user_id="user-1")
        store.end(s2.session_id)
        active = store.get_active_by_user("user-1")
        assert len(active) == 1
        assert active[0].session_id == s1.session_id

    def test_touch_updates_activity(self, store):
        session = store.create(user_id="user-1")
        original_activity = session.last_activity_at
        time.sleep(0.01)
        result = store.touch(session.session_id)
        assert result is True
        assert store._sessions[session.session_id].last_activity_at > original_activity

    def test_touch_nonexistent_session(self, store):
        result = store.touch("nonexistent-id")
        assert result is False

    def test_end_session(self, store):
        session = store.create(user_id="user-1")
        result = store.end(session.session_id)
        assert result is True
        assert not store._sessions[session.session_id].is_active

    def test_end_nonexistent_session(self, store):
        result = store.end("nonexistent-id")
        assert result is False

    def test_end_all_for_user(self, store):
        store.create(user_id="user-1")
        store.create(user_id="user-1")
        store.create(user_id="user-2")
        count = store.end_all_for_user("user-1")
        assert count == 2
        active = store.get_active_by_user("user-1")
        assert len(active) == 0

    def test_end_all_for_user_returns_zero_if_none_active(self, store):
        s1 = store.create(user_id="user-1")
        store.end(s1.session_id)
        count = store.end_all_for_user("user-1")
        assert count == 0

    def test_cleanup_inactive(self, store, temp_file):
        session_data = {
            "sessions": [
                {
                    "session_id": "sess-old",
                    "user_id": "user-1",
                    "started_at": "2024-01-15T10:00:00",
                    "last_activity_at": (datetime.now() - timedelta(hours=2)).isoformat(),
                    "is_active": True,
                }
            ],
            "updated_at": "2024-01-15T10:30:00",
        }
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(json.dumps(session_data))
        store = JsonFileMobileSessionStore(temp_file)
        store.create(user_id="user-2")
        count = store.cleanup_inactive(inactive_minutes=30)
        assert count == 1
        assert not store._sessions["sess-old"].is_active

    def test_cleanup_inactive_no_old_sessions(self, store):
        store.create(user_id="user-1")
        count = store.cleanup_inactive(inactive_minutes=30)
        assert count == 0

    def test_thread_safety(self, store):
        results = []

        def create_session(idx):
            session = store.create(user_id=f"user-{idx}")
            results.append(session.session_id)

        threads = [threading.Thread(target=create_session, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        assert len(store._sessions) == 10


class TestJsonFileMobileSyncStore:
    """Tests pour JsonFileMobileSyncStore."""

    @pytest.fixture
    def temp_file(self, tmp_path):
        return tmp_path / "sync.json"

    @pytest.fixture
    def store(self, temp_file):
        return JsonFileMobileSyncStore(temp_file)

    def test_init_creates_empty_store(self, store):
        assert store._sync_states == {}
        assert store._drafts == {}

    def test_init_loads_existing_data(self, temp_file):
        data = {
            "sync_states": [
                {
                    "user_id": "user-1",
                    "device_token": "token-abc",
                    "last_sync_at": "2024-01-15T10:00:00",
                    "last_sync_status": "success",
                    "drafts_synced_count": 5,
                    "pending_actions_count": 0,
                    "sync_version": 1,
                }
            ],
            "drafts": [
                {
                    "draft_id": "draft-1",
                    "subject": "Test Subject",
                    "recipient": "test@example.com",
                    "body_full": "Test body",
                    "status": "pending",
                    "action": "pending",
                    "priority_score": 50,
                    "category": "NORMAL",
                    "created_at": "2024-01-15T10:00:00",
                    "updated_at": "2024-01-15T10:00:00",
                    "is_read": False,
                }
            ],
            "updated_at": "2024-01-15T10:30:00",
        }
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(json.dumps(data))
        store = JsonFileMobileSyncStore(temp_file)
        assert "user-1:token-abc" in store._sync_states
        assert "draft-1" in store._drafts

    def test_init_handles_corrupted_file(self, temp_file):
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text("invalid json")
        store = JsonFileMobileSyncStore(temp_file)
        assert store._sync_states == {}
        assert store._drafts == {}

    def test_get_sync_state(self, store):
        sync_state = MobileSyncState(user_id="user-1", device_token="token-abc")
        store.update_sync_state(sync_state)
        result = store.get_sync_state("user-1", "token-abc")
        assert result is not None
        assert result.user_id == "user-1"

    def test_get_sync_state_not_found(self, store):
        result = store.get_sync_state("user-1", "token-abc")
        assert result is None

    def test_update_sync_state(self, store):
        sync_state = MobileSyncState(user_id="user-1", device_token="token-abc")
        result = store.update_sync_state(sync_state)
        assert result.user_id == "user-1"
        assert "user-1:token-abc" in store._sync_states

    def test_get_drafts_since_returns_all(self, store):
        for i in range(5):
            draft = MobileDraft(
                draft_id=f"draft-{i}",
                subject=f"Subject {i}",
                recipient=f"test{i}@example.com",
                body_full=f"Body {i}",
            )
            store.add_draft(draft)
        drafts, cursor, has_more = store.get_drafts_since("user-1")
        assert len(drafts) == 5
        assert cursor is None
        assert not has_more

    def test_get_drafts_since_with_date_filter(self, store, temp_file):
        old_data = {
            "sync_states": [],
            "drafts": [
                {
                    "draft_id": "draft-old",
                    "subject": "Old",
                    "recipient": "test@example.com",
                    "body_full": "Old body",
                    "status": "pending",
                    "action": "pending",
                    "priority_score": 50,
                    "category": "NORMAL",
                    "created_at": "2024-01-01T10:00:00",
                    "updated_at": "2024-01-01T10:00:00",
                    "is_read": False,
                }
            ],
            "updated_at": "2024-01-15T10:30:00",
        }
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(json.dumps(old_data))
        store = JsonFileMobileSyncStore(temp_file)
        new_draft = MobileDraft(
            draft_id="draft-new",
            subject="New",
            recipient="test@example.com",
            body_full="New body",
        )
        store.add_draft(new_draft)
        since = datetime.now() - timedelta(hours=1)
        drafts, _, _ = store.get_drafts_since("user-1", since=since)
        assert len(drafts) == 1
        assert drafts[0].draft_id == "draft-new"

    def test_get_drafts_since_with_pagination(self, store):
        for i in range(15):
            draft = MobileDraft(
                draft_id=f"draft-{i:02d}",
                subject=f"Subject {i}",
                recipient=f"test{i}@example.com",
                body_full=f"Body {i}",
            )
            store.add_draft(draft)
        drafts, cursor, has_more = store.get_drafts_since("user-1", limit=10)
        assert len(drafts) == 10
        assert has_more is True
        assert cursor is not None

    def test_get_drafts_since_with_cursor(self, store):
        for i in range(10):
            draft = MobileDraft(
                draft_id=f"draft-{i:02d}",
                subject=f"Subject {i}",
                recipient=f"test{i}@example.com",
                body_full=f"Body {i}",
            )
            store.add_draft(draft)
        drafts_page1, cursor, _ = store.get_drafts_since("user-1", limit=5)
        drafts_page2, _, _ = store.get_drafts_since("user-1", limit=5, cursor=cursor)
        all_ids = [d.draft_id for d in drafts_page1 + drafts_page2]
        assert len(all_ids) == 10
        assert len(set(all_ids)) == 10

    def test_get_drafts_since_with_invalid_cursor(self, store):
        draft = MobileDraft(
            draft_id="draft-1",
            subject="Test",
            recipient="test@example.com",
            body_full="Body",
        )
        store.add_draft(draft)
        drafts, _, _ = store.get_drafts_since("user-1", cursor="invalid-cursor")
        assert len(drafts) == 1

    def test_get_draft(self, store):
        draft = MobileDraft(
            draft_id="draft-1",
            subject="Test",
            recipient="test@example.com",
            body_full="Body",
        )
        store.add_draft(draft)
        result = store.get_draft("draft-1", "user-1")
        assert result is not None
        assert result.draft_id == "draft-1"

    def test_get_draft_not_found(self, store):
        result = store.get_draft("nonexistent", "user-1")
        assert result is None

    def test_get_pending_drafts(self, store):
        pending = MobileDraft(
            draft_id="draft-pending",
            subject="Pending",
            recipient="test@example.com",
            body_full="Body",
            action=MobileDraftAction.PENDING,
            priority_score=80,
        )
        approved = MobileDraft(
            draft_id="draft-approved",
            subject="Approved",
            recipient="test@example.com",
            body_full="Body",
            action=MobileDraftAction.APPROVED,
        )
        store.add_draft(pending)
        store.add_draft(approved)
        results = store.get_pending_drafts("user-1")
        assert len(results) == 1
        assert results[0].draft_id == "draft-pending"

    def test_get_pending_drafts_sorted_by_priority(self, store):
        for i, score in enumerate([50, 90, 70]):
            draft = MobileDraft(
                draft_id=f"draft-{i}",
                subject=f"Subject {i}",
                recipient="test@example.com",
                body_full="Body",
                action=MobileDraftAction.PENDING,
                priority_score=score,
            )
            store.add_draft(draft)
        results = store.get_pending_drafts("user-1")
        assert results[0].priority_score == 90
        assert results[1].priority_score == 70
        assert results[2].priority_score == 50

    def test_add_draft(self, store):
        draft = MobileDraft(
            draft_id="draft-1",
            subject="Test",
            recipient="test@example.com",
            body_full="Body",
        )
        result = store.add_draft(draft)
        assert result.draft_id == "draft-1"
        assert "draft-1" in store._drafts

    def test_update_draft(self, store):
        draft = MobileDraft(
            draft_id="draft-1",
            subject="Original",
            recipient="test@example.com",
            body_full="Original body",
        )
        store.add_draft(draft)
        draft.subject = "Updated"
        result = store.update_draft(draft)
        assert result.subject == "Updated"
        assert store._drafts["draft-1"].subject == "Updated"


class TestJsonFileMobileDraftActionStore:
    """Tests pour JsonFileMobileDraftActionStore."""

    @pytest.fixture
    def temp_path(self, tmp_path):
        return tmp_path

    @pytest.fixture
    def sync_store(self, temp_path):
        return JsonFileMobileSyncStore(temp_path / "sync.json")

    @pytest.fixture
    def store(self, temp_path, sync_store):
        return JsonFileMobileDraftActionStore(temp_path / "actions.json", sync_store)

    @pytest.fixture
    def sample_draft(self, sync_store):
        draft = MobileDraft(
            draft_id="draft-1",
            subject="Test",
            recipient="test@example.com",
            body_full="Test body content",
        )
        sync_store.add_draft(draft)
        return draft

    def test_init_creates_empty_history(self, store):
        assert store._action_history == []

    def test_init_loads_existing_history(self, temp_path, sync_store):
        data = {
            "actions": [
                {
                    "draft_id": "draft-1",
                    "user_id": "user-1",
                    "action": "approved",
                    "device_token": "token-abc",
                    "timestamp": "2024-01-15T10:00:00",
                }
            ],
            "updated_at": "2024-01-15T10:30:00",
        }
        filepath = temp_path / "actions.json"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(data))
        store = JsonFileMobileDraftActionStore(filepath, sync_store)
        assert len(store._action_history) == 1

    def test_init_handles_corrupted_file(self, temp_path, sync_store):
        filepath = temp_path / "actions.json"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text("invalid json")
        store = JsonFileMobileDraftActionStore(filepath, sync_store)
        assert store._action_history == []

    def test_apply_action_approve(self, store, sample_draft, sync_store):
        request = MobileDraftActionRequest(
            draft_id="draft-1",
            action=MobileDraftAction.APPROVED,
            user_id="user-1",
            device_token="token-abc",
        )
        result = store.apply_action(request)
        assert result is True
        draft = sync_store.get_draft("draft-1", "user-1")
        assert draft.action == MobileDraftAction.APPROVED

    def test_apply_action_reject(self, store, sample_draft, sync_store):
        request = MobileDraftActionRequest(
            draft_id="draft-1",
            action=MobileDraftAction.REJECTED,
            user_id="user-1",
        )
        result = store.apply_action(request)
        assert result is True
        draft = sync_store.get_draft("draft-1", "user-1")
        assert draft.action == MobileDraftAction.REJECTED

    def test_apply_action_edit(self, store, sample_draft, sync_store):
        request = MobileDraftActionRequest(
            draft_id="draft-1",
            action=MobileDraftAction.EDITED,
            user_id="user-1",
            edited_body="New edited content",
        )
        result = store.apply_action(request)
        assert result is True
        draft = sync_store.get_draft("draft-1", "user-1")
        assert draft.action == MobileDraftAction.EDITED
        assert draft.body_full == "New edited content"

    def test_apply_action_sent(self, store, sample_draft, sync_store):
        request = MobileDraftActionRequest(
            draft_id="draft-1",
            action=MobileDraftAction.SENT,
            user_id="user-1",
        )
        result = store.apply_action(request)
        assert result is True
        draft = sync_store.get_draft("draft-1", "user-1")
        assert draft.action == MobileDraftAction.SENT

    def test_apply_action_draft_not_found(self, store):
        request = MobileDraftActionRequest(
            draft_id="nonexistent",
            action=MobileDraftAction.APPROVED,
            user_id="user-1",
        )
        result = store.apply_action(request)
        assert result is False

    def test_apply_action_with_offline_timestamp(self, store, sample_draft):
        offline_time = datetime.now() - timedelta(hours=1)
        request = MobileDraftActionRequest(
            draft_id="draft-1",
            action=MobileDraftAction.APPROVED,
            user_id="user-1",
            offline_timestamp=offline_time,
        )
        result = store.apply_action(request)
        assert result is True
        assert len(store._action_history) == 1
        assert store._action_history[0]["offline_timestamp"] == offline_time.isoformat()

    def test_apply_batch_actions(self, store, sync_store):
        for i in range(3):
            draft = MobileDraft(
                draft_id=f"draft-{i}",
                subject=f"Subject {i}",
                recipient="test@example.com",
                body_full="Body",
            )
            sync_store.add_draft(draft)
        requests = [
            MobileDraftActionRequest(
                draft_id=f"draft-{i}",
                action=MobileDraftAction.APPROVED,
                user_id="user-1",
            )
            for i in range(3)
        ]
        results = store.apply_batch_actions(requests)
        assert all(results.values())
        assert len(results) == 3

    def test_mark_read(self, store, sample_draft, sync_store):
        result = store.mark_read("draft-1", "user-1")
        assert result is True
        draft = sync_store.get_draft("draft-1", "user-1")
        assert draft.is_read is True

    def test_mark_read_draft_not_found(self, store):
        result = store.mark_read("nonexistent", "user-1")
        assert result is False

    def test_get_action_history(self, store, sample_draft):
        for action in [MobileDraftAction.APPROVED, MobileDraftAction.SENT]:
            request = MobileDraftActionRequest(
                draft_id="draft-1",
                action=action,
                user_id="user-1",
            )
            store.apply_action(request)
        history = store.get_action_history("user-1")
        assert len(history) == 2

    def test_get_action_history_filter_by_draft(self, store, sync_store):
        for i in range(2):
            draft = MobileDraft(
                draft_id=f"draft-{i}",
                subject=f"Subject {i}",
                recipient="test@example.com",
                body_full="Body",
            )
            sync_store.add_draft(draft)
            request = MobileDraftActionRequest(
                draft_id=f"draft-{i}",
                action=MobileDraftAction.APPROVED,
                user_id="user-1",
            )
            store.apply_action(request)
        history = store.get_action_history("user-1", draft_id="draft-0")
        assert len(history) == 1
        assert history[0]["draft_id"] == "draft-0"

    def test_get_action_history_with_limit(self, store, sync_store):
        draft = MobileDraft(
            draft_id="draft-1",
            subject="Test",
            recipient="test@example.com",
            body_full="Body",
        )
        sync_store.add_draft(draft)
        for _ in range(10):
            request = MobileDraftActionRequest(
                draft_id="draft-1",
                action=MobileDraftAction.APPROVED,
                user_id="user-1",
            )
            store.apply_action(request)
        history = store.get_action_history("user-1", limit=5)
        assert len(history) == 5


class TestJsonFileMobileAnalyticsStore:
    """Tests pour JsonFileMobileAnalyticsStore."""

    @pytest.fixture
    def temp_file(self, tmp_path):
        return tmp_path / "analytics.json"

    @pytest.fixture
    def store(self, temp_file):
        return JsonFileMobileAnalyticsStore(temp_file)

    def test_init_creates_empty_store(self, store):
        assert store._events == []

    def test_init_loads_existing_events(self, temp_file):
        data = {
            "events": [
                {
                    "event_id": "evt-1",
                    "event_type": "app.open",
                    "user_id": "user-1",
                    "timestamp": "2024-01-15T10:00:00",
                    "properties": {},
                    "device_info": {},
                }
            ],
            "updated_at": "2024-01-15T10:30:00",
        }
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(json.dumps(data))
        store = JsonFileMobileAnalyticsStore(temp_file)
        assert len(store._events) == 1

    def test_init_handles_corrupted_file(self, temp_file):
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text("invalid json")
        store = JsonFileMobileAnalyticsStore(temp_file)
        assert store._events == []

    def test_track_event(self, store):
        event = MobileAnalyticsEvent(
            event_type=MobileEventType.APP_OPEN,
            user_id="user-1",
            session_id="sess-1",
        )
        result = store.track_event(event)
        assert result is True
        assert len(store._events) == 1

    def test_track_batch(self, store):
        events = [
            MobileAnalyticsEvent(
                event_type=MobileEventType.APP_OPEN,
                user_id="user-1",
            ),
            MobileAnalyticsEvent(
                event_type=MobileEventType.DRAFT_VIEW,
                user_id="user-1",
            ),
        ]
        count = store.track_batch(events)
        assert count == 2
        assert len(store._events) == 2

    def test_get_events(self, store):
        for event_type in [MobileEventType.APP_OPEN, MobileEventType.DRAFT_VIEW]:
            event = MobileAnalyticsEvent(
                event_type=event_type,
                user_id="user-1",
            )
            store.track_event(event)
        events = store.get_events("user-1")
        assert len(events) == 2

    def test_get_events_filter_by_type(self, store):
        for event_type in [MobileEventType.APP_OPEN, MobileEventType.DRAFT_VIEW]:
            event = MobileAnalyticsEvent(
                event_type=event_type,
                user_id="user-1",
            )
            store.track_event(event)
        events = store.get_events("user-1", event_type="draft.view")
        assert len(events) == 1
        assert events[0].event_type == MobileEventType.DRAFT_VIEW

    def test_get_events_filter_by_date(self, store, temp_file):
        old_data = {
            "events": [
                {
                    "event_id": "evt-old",
                    "event_type": "app.open",
                    "user_id": "user-1",
                    "timestamp": "2024-01-01T10:00:00",
                    "properties": {},
                    "device_info": {},
                }
            ],
            "updated_at": "2024-01-15T10:30:00",
        }
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(json.dumps(old_data))
        store = JsonFileMobileAnalyticsStore(temp_file)
        new_event = MobileAnalyticsEvent(
            event_type=MobileEventType.DRAFT_VIEW,
            user_id="user-1",
        )
        store.track_event(new_event)
        since = datetime.now() - timedelta(hours=1)
        events = store.get_events("user-1", since=since)
        assert len(events) == 1
        assert events[0].event_type == MobileEventType.DRAFT_VIEW

    def test_get_events_with_limit(self, store):
        for i in range(10):
            event = MobileAnalyticsEvent(
                event_type=MobileEventType.APP_OPEN,
                user_id="user-1",
            )
            store.track_event(event)
        events = store.get_events("user-1", limit=5)
        assert len(events) == 5

    def test_get_stats(self, store):
        today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        for event_type in [
            MobileEventType.DRAFT_VIEW,
            MobileEventType.DRAFT_APPROVE,
            MobileEventType.DRAFT_APPROVE,
            MobileEventType.DRAFT_REJECT,
        ]:
            event = MobileAnalyticsEvent(
                event_type=event_type,
                user_id="user-1",
                timestamp=today,
            )
            store._events.append(event)
        stats = store.get_stats("user-1")
        assert stats.user_id == "user-1"
        assert stats.approved_today == 2
        assert stats.rejected_today == 1
        assert stats.ai_accuracy_percentage > 0

    def test_get_stats_no_actions(self, store):
        stats = store.get_stats("user-1")
        assert stats.approved_today == 0
        assert stats.rejected_today == 0
        assert stats.ai_accuracy_percentage == 0.0

    def test_cleanup_old_events(self, store, temp_file):
        old_data = {
            "events": [
                {
                    "event_id": "evt-old",
                    "event_type": "app.open",
                    "user_id": "user-1",
                    "timestamp": "2024-01-01T10:00:00",
                    "properties": {},
                    "device_info": {},
                }
            ],
            "updated_at": "2024-01-15T10:30:00",
        }
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(json.dumps(old_data))
        store = JsonFileMobileAnalyticsStore(temp_file)
        new_event = MobileAnalyticsEvent(
            event_type=MobileEventType.APP_OPEN,
            user_id="user-1",
        )
        store.track_event(new_event)
        count = store.cleanup_old_events(days=30)
        assert count == 1
        assert len(store._events) == 1

    def test_cleanup_old_events_nothing_to_clean(self, store):
        event = MobileAnalyticsEvent(
            event_type=MobileEventType.APP_OPEN,
            user_id="user-1",
        )
        store.track_event(event)
        count = store.cleanup_old_events(days=30)
        assert count == 0


class TestJsonFileMobilePreferencesStore:
    """Tests pour JsonFileMobilePreferencesStore."""

    @pytest.fixture
    def temp_file(self, tmp_path):
        return tmp_path / "preferences.json"

    @pytest.fixture
    def store(self, temp_file):
        return JsonFileMobilePreferencesStore(temp_file)

    def test_init_creates_empty_store(self, store):
        assert store._preferences == {}

    def test_init_loads_existing_preferences(self, temp_file):
        data = {
            "preferences": [
                {
                    "user_id": "user-1",
                    "notification_preference": "all",
                    "sync_frequency": "5min",
                    "auto_approve_threshold": 0,
                    "dark_mode": True,
                    "language": "en",
                    "biometric_enabled": False,
                    "offline_mode": True,
                    "updated_at": "2024-01-15T10:00:00",
                }
            ],
            "updated_at": "2024-01-15T10:30:00",
        }
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(json.dumps(data))
        store = JsonFileMobilePreferencesStore(temp_file)
        assert "user-1" in store._preferences

    def test_init_handles_corrupted_file(self, temp_file):
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text("invalid json")
        store = JsonFileMobilePreferencesStore(temp_file)
        assert store._preferences == {}

    def test_get_preferences(self, store):
        prefs = MobileUserPreferences(user_id="user-1", dark_mode=True)
        store.save(prefs)
        result = store.get("user-1")
        assert result is not None
        assert result.dark_mode is True

    def test_get_preferences_not_found(self, store):
        result = store.get("nonexistent")
        assert result is None

    def test_save_preferences(self, store):
        prefs = MobileUserPreferences(
            user_id="user-1",
            notification_preference=NotificationPreference.IMPORTANT_ONLY,
            sync_frequency=SyncFrequency.EVERY_15_MIN,
            dark_mode=True,
        )
        result = store.save(prefs)
        assert result.user_id == "user-1"
        assert "user-1" in store._preferences

    def test_update_preferences(self, store):
        prefs = MobileUserPreferences(user_id="user-1", dark_mode=False)
        store.save(prefs)
        result = store.update("user-1", {"dark_mode": True, "language": "en"})
        assert result is not None
        assert result.dark_mode is True
        assert result.language == "en"

    def test_update_preferences_with_enum_strings(self, store):
        prefs = MobileUserPreferences(user_id="user-1")
        store.save(prefs)
        result = store.update(
            "user-1",
            {
                "notification_preference": "important_only",
                "sync_frequency": "15min",
            },
        )
        assert result is not None
        assert result.notification_preference == NotificationPreference.IMPORTANT_ONLY
        assert result.sync_frequency == SyncFrequency.EVERY_15_MIN

    def test_update_preferences_user_not_found(self, store):
        result = store.update("nonexistent", {"dark_mode": True})
        assert result is None

    def test_delete_preferences(self, store):
        prefs = MobileUserPreferences(user_id="user-1")
        store.save(prefs)
        result = store.delete("user-1")
        assert result is True
        assert "user-1" not in store._preferences

    def test_delete_preferences_not_found(self, store):
        result = store.delete("nonexistent")
        assert result is False


class TestJsonFileMobileAppConfigStore:
    """Tests pour JsonFileMobileAppConfigStore."""

    @pytest.fixture
    def temp_file(self, tmp_path):
        return tmp_path / "config.json"

    @pytest.fixture
    def store(self, temp_file):
        return JsonFileMobileAppConfigStore(temp_file)

    def test_init_creates_default_config(self, store):
        assert store._config is not None
        assert store._config.min_version == "1.0.0"

    def test_init_loads_existing_config(self, temp_file):
        data = {
            "config": {
                "min_version": "2.0.0",
                "latest_version": "2.1.0",
                "force_update": True,
                "maintenance_mode": False,
                "feature_flags": {"dark_mode": True},
                "api_endpoints": {},
                "sync_config": {},
                "updated_at": "2024-01-15T10:00:00",
            },
            "updated_at": "2024-01-15T10:30:00",
        }
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(json.dumps(data))
        store = JsonFileMobileAppConfigStore(temp_file)
        assert store._config.min_version == "2.0.0"
        assert store._config.force_update is True

    def test_init_handles_corrupted_file(self, temp_file):
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text("invalid json")
        store = JsonFileMobileAppConfigStore(temp_file)
        assert store._config.min_version == "1.0.0"

    def test_get_config(self, store):
        config = store.get()
        assert config is not None
        assert config.min_version == "1.0.0"

    def test_update_config(self, store):
        new_config = MobileAppConfig(
            min_version="2.0.0",
            latest_version="2.1.0",
        )
        result = store.update(new_config)
        assert result.min_version == "2.0.0"
        assert store._config.min_version == "2.0.0"

    def test_update_feature_flag(self, store):
        result = store.update_feature_flag("new_feature", True)
        assert result is True
        assert store._config.feature_flags["new_feature"] is True

    def test_update_feature_flag_disable(self, store):
        store.update_feature_flag("dark_mode", False)
        assert store._config.feature_flags["dark_mode"] is False

    def test_set_maintenance_mode(self, store):
        result = store.set_maintenance_mode(True, "System update in progress")
        assert result is True
        assert store._config.maintenance_mode is True
        assert store._config.maintenance_message == "System update in progress"

    def test_set_maintenance_mode_off(self, store):
        store.set_maintenance_mode(True, "Maintenance")
        result = store.set_maintenance_mode(False)
        assert result is True
        assert store._config.maintenance_mode is False

    def test_update_versions_all(self, store):
        result = store.update_versions(
            min_version="2.0.0",
            latest_version="2.1.0",
            force_update=True,
        )
        assert result.min_version == "2.0.0"
        assert result.latest_version == "2.1.0"
        assert result.force_update is True

    def test_update_versions_partial(self, store):
        result = store.update_versions(latest_version="1.1.0")
        assert result.min_version == "1.0.0"
        assert result.latest_version == "1.1.0"


class TestFactoryFunctions:
    """Tests pour les factory functions et singletons."""

    def setup_method(self):
        reset_mobile_stores()

    def teardown_method(self):
        reset_mobile_stores()

    def test_get_mobile_session_store_creates_singleton(self, tmp_path):
        filepath = tmp_path / "sessions.json"
        store1 = get_mobile_session_store(filepath)
        store2 = get_mobile_session_store(filepath)
        assert store1 is store2

    def test_get_mobile_session_store_uses_default_path(self):
        with patch("app.config.PROJECT_ROOT", Path("/tmp/test")):
            reset_mobile_stores()
            store = get_mobile_session_store()
            assert store is not None

    def test_get_mobile_sync_store_creates_singleton(self, tmp_path):
        filepath = tmp_path / "sync.json"
        store1 = get_mobile_sync_store(filepath)
        store2 = get_mobile_sync_store(filepath)
        assert store1 is store2

    def test_get_mobile_action_store_creates_singleton(self, tmp_path):
        reset_mobile_stores()
        sync_path = tmp_path / "sync.json"
        action_path = tmp_path / "actions.json"
        get_mobile_sync_store(sync_path)
        store1 = get_mobile_action_store(action_path)
        store2 = get_mobile_action_store(action_path)
        assert store1 is store2

    def test_get_mobile_analytics_store_creates_singleton(self, tmp_path):
        filepath = tmp_path / "analytics.json"
        store1 = get_mobile_analytics_store(filepath)
        store2 = get_mobile_analytics_store(filepath)
        assert store1 is store2

    def test_get_mobile_preferences_store_creates_singleton(self, tmp_path):
        filepath = tmp_path / "preferences.json"
        store1 = get_mobile_preferences_store(filepath)
        store2 = get_mobile_preferences_store(filepath)
        assert store1 is store2

    def test_get_mobile_config_store_creates_singleton(self, tmp_path):
        filepath = tmp_path / "config.json"
        store1 = get_mobile_config_store(filepath)
        store2 = get_mobile_config_store(filepath)
        assert store1 is store2

    def test_reset_mobile_stores(self, tmp_path):
        filepath = tmp_path / "sessions.json"
        store1 = get_mobile_session_store(filepath)
        reset_mobile_stores()
        store2 = get_mobile_session_store(filepath)
        assert store1 is not store2


class TestEdgeCases:
    """Tests pour les cas limites et scénarios edge."""

    @pytest.fixture
    def temp_path(self, tmp_path):
        return tmp_path

    def test_session_store_handles_concurrent_writes(self, temp_path):
        store = JsonFileMobileSessionStore(temp_path / "sessions.json")
        errors = []

        def create_and_modify(idx):
            try:
                session = store.create(user_id=f"user-{idx}")
                store.touch(session.session_id)
                store.end(session.session_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_and_modify, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_analytics_store_limits_saved_events(self, temp_path):
        store = JsonFileMobileAnalyticsStore(temp_path / "analytics.json")
        for i in range(10005):
            event = MobileAnalyticsEvent(
                event_type=MobileEventType.APP_OPEN,
                user_id="user-1",
            )
            store._events.append(event)
        store._save()
        data = json.loads((temp_path / "analytics.json").read_text())
        assert len(data["events"]) == 10000

    def test_action_store_limits_saved_history(self, temp_path):
        sync_store = JsonFileMobileSyncStore(temp_path / "sync.json")
        draft = MobileDraft(
            draft_id="draft-1",
            subject="Test",
            recipient="test@example.com",
            body_full="Body",
        )
        sync_store.add_draft(draft)
        store = JsonFileMobileDraftActionStore(temp_path / "actions.json", sync_store)
        for _ in range(1005):
            store._action_history.append({
                "draft_id": "draft-1",
                "user_id": "user-1",
                "action": "approved",
                "timestamp": datetime.now().isoformat(),
            })
        store._save()
        data = json.loads((temp_path / "actions.json").read_text())
        assert len(data["actions"]) == 1000

    def test_sync_store_with_optional_drafts_filepath(self, temp_path):
        store = JsonFileMobileSyncStore(
            temp_path / "sync.json",
            drafts_filepath=temp_path / "drafts.json",
        )
        assert store.drafts_filepath == temp_path / "drafts.json"

    def test_preferences_update_ignores_unknown_fields(self, temp_path):
        store = JsonFileMobilePreferencesStore(temp_path / "preferences.json")
        prefs = MobileUserPreferences(user_id="user-1")
        store.save(prefs)
        result = store.update("user-1", {"unknown_field": "value", "dark_mode": True})
        assert result is not None
        assert result.dark_mode is True
        assert not hasattr(result, "unknown_field")

    def test_config_store_preserves_custom_feature_flags(self, temp_path):
        store = JsonFileMobileAppConfigStore(temp_path / "config.json")
        store.update_feature_flag("custom_flag", True)
        store.update_feature_flag("another_flag", False)
        config = store.get()
        assert config.feature_flags["custom_flag"] is True
        assert config.feature_flags["another_flag"] is False
