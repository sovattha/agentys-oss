"""Tests unitaires pour app.batch_queue — BatchQueue et is_batch_window."""

import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.batch_queue import (
    BatchQueue,
    is_batch_window,
    touch_user_activity,
    get_last_user_activity,
)


# ── is_batch_window ──────────────────────────────────────────────────────────


class TestIsBatchWindow:
    """Tests pour la logique de fenêtre batch (off-hours)."""

    def _make_settings(self, **overrides):
        defaults = {
            "batch_enabled": True,
            "batch_active_hours_start": "07:00",
            "batch_active_hours_end": "20:00",
            "batch_weekend_all_day": True,
            "batch_activity_timeout_min": 15,
        }
        defaults.update(overrides)
        return defaults

    @patch("app.batch_queue.get_last_user_activity", return_value=0.0)
    def test_weekday_during_active_hours(self, _activity):
        """Mardi 10h → heures actives → pas de batch."""
        now = datetime(2024, 1, 9, 10, 0)  # Tuesday 10:00
        with patch("app.api.settings.load_settings", return_value=self._make_settings()):
            result = is_batch_window(now=now)
        assert result is False

    @patch("app.batch_queue.get_last_user_activity", return_value=0.0)
    def test_weekday_outside_active_hours(self, _activity):
        """Mardi 23h → hors heures actives → batch."""
        now = datetime(2024, 1, 9, 23, 0)  # Tuesday 23:00
        with patch("app.api.settings.load_settings", return_value=self._make_settings()):
            result = is_batch_window(now=now)
        assert result is True

    @patch("app.batch_queue.get_last_user_activity", return_value=0.0)
    def test_weekend_batch_all_day(self, _activity):
        """Samedi 14h avec batch_weekend_all_day → batch."""
        now = datetime(2024, 1, 13, 14, 0)  # Saturday 14:00
        with patch("app.api.settings.load_settings", return_value=self._make_settings()):
            result = is_batch_window(now=now)
        assert result is True

    @patch("app.batch_queue.get_last_user_activity", return_value=0.0)
    def test_batch_disabled(self, _activity):
        """Batch désactivé dans settings → jamais batch."""
        settings = self._make_settings(batch_enabled=False)
        with patch("app.api.settings.load_settings", return_value=settings):
            result = is_batch_window(now=datetime(2024, 1, 13, 23, 0))
        assert result is False

    @patch("app.batch_queue.get_last_user_activity")
    def test_user_active_override(self, mock_activity):
        """Utilisateur actif récemment → pas de batch même en off-hours."""
        mock_activity.return_value = time.time() - 60  # Active 1 min ago
        with patch("app.api.settings.load_settings", return_value=self._make_settings()):
            result = is_batch_window(now=datetime(2024, 1, 9, 23, 0))
        assert result is False

    @patch("app.batch_queue.get_last_user_activity", return_value=0.0)
    def test_settings_from_ui(self, _activity):
        """Settings chargés depuis l'UI (load_settings)."""
        settings = self._make_settings(
            batch_active_hours_start="09:00",
            batch_active_hours_end="18:00",
            batch_weekend_all_day=False,
        )
        with patch("app.api.settings.load_settings", return_value=settings):
            # Saturday 14h but weekend batch disabled
            result = is_batch_window(now=datetime(2024, 1, 13, 14, 0))
        # Not weekend batch, 14:00 is within 09:00-18:00, so not batch
        assert result is False


# ── touch_user_activity / get_last_user_activity ─────────────────────────────


class TestUserActivity:
    def test_touch_and_get(self):
        before = time.time()
        touch_user_activity()
        after = time.time()
        last = get_last_user_activity()
        assert before <= last <= after


# ── BatchQueue ───────────────────────────────────────────────────────────────


@pytest.fixture
def queue(tmp_path):
    """Crée un BatchQueue avec une DB temporaire et connexion isolée."""
    import app.batch_queue as bq
    # Clear thread-local connection to ensure isolation
    if hasattr(bq._local, "batch_conn"):
        try:
            bq._local.batch_conn.close()
        except Exception:
            pass
        bq._local.batch_conn = None
    db_path = str(tmp_path / "test_batch.db")
    return BatchQueue(db_path=db_path)


class TestBatchQueueEnqueue:
    def test_enqueue_returns_id(self, queue):
        item_id = queue.enqueue(
            email_id="e1",
            tier="standard",
            model="claude-3-haiku",
            system_prompt="You are helpful",
            user_prompt="Reply to this",
        )
        assert item_id is not None
        assert len(item_id) == 36  # UUID format

    def test_enqueue_with_metadata(self, queue):
        queue.enqueue(
            email_id="e1",
            tier="complex",
            model="claude-3-sonnet",
            system_prompt="sys",
            user_prompt="usr",
            metadata={"sender": "alice@test.com", "subject": "Hello"},
        )
        item = queue.get_by_email_id("e1")
        assert item is not None
        assert item["email_id"] == "e1"

    def test_enqueue_custom_tokens_and_temp(self, queue):
        queue.enqueue(
            email_id="e1",
            tier="simple",
            model="haiku",
            system_prompt="s",
            user_prompt="u",
            max_tokens=1024,
            temperature=0.7,
        )
        pending = queue.get_pending()
        assert len(pending) == 1
        assert pending[0]["max_tokens"] == 1024
        assert pending[0]["temperature"] == 0.7


class TestBatchQueueGetPending:
    def test_get_pending_empty(self, queue):
        assert queue.get_pending() == []

    def test_get_pending_returns_pending_only(self, queue):
        queue.enqueue("e1", "t", "m", "s", "u")
        queue.enqueue("e2", "t", "m", "s", "u")
        pending = queue.get_pending()
        assert len(pending) == 2

    def test_get_pending_respects_limit(self, queue):
        for i in range(10):
            queue.enqueue(f"e{i}", "t", "m", "s", "u")
        pending = queue.get_pending(limit=3)
        assert len(pending) == 3

    def test_get_pending_ordered_by_created_at(self, queue):
        queue.enqueue("first", "t", "m", "s", "u")
        queue.enqueue("second", "t", "m", "s", "u")
        pending = queue.get_pending()
        assert pending[0]["email_id"] == "first"


class TestBatchQueueMarkSubmitted:
    def test_mark_submitted(self, queue):
        id1 = queue.enqueue("e1", "t", "m", "s", "u")
        id2 = queue.enqueue("e2", "t", "m", "s", "u")
        queue.mark_submitted([id1, id2], "batch-123")

        # Should no longer be pending
        pending = queue.get_pending()
        assert len(pending) == 0

        # Should have active batch
        batches = queue.get_active_batches()
        assert len(batches) == 1
        assert batches[0]["batch_id"] == "batch-123"
        assert batches[0]["request_count"] == 2


class TestBatchQueueMarkCompleted:
    def test_mark_completed(self, queue):
        item_id = queue.enqueue("e1", "t", "m", "s", "u")
        queue.mark_completed(item_id, "Draft text here", input_tokens=100, output_tokens=50)

        # No longer pending
        assert queue.pending_count() == 0

        # Check by email
        item = queue.get_by_email_id("e1")
        assert item is None  # Not pending/submitted anymore


class TestBatchQueueMarkFailed:
    def test_mark_failed(self, queue):
        item_id = queue.enqueue("e1", "t", "m", "s", "u")
        queue.mark_failed(item_id, "API error")
        assert queue.pending_count() == 0


class TestBatchQueueGetByEmailId:
    def test_get_existing(self, queue):
        queue.enqueue("e1", "t", "m", "s", "u")
        item = queue.get_by_email_id("e1")
        assert item is not None
        assert item["email_id"] == "e1"

    def test_get_nonexistent(self, queue):
        assert queue.get_by_email_id("nonexistent") is None

    def test_completed_not_returned(self, queue):
        item_id = queue.enqueue("e1", "t", "m", "s", "u")
        queue.mark_completed(item_id, "done")
        assert queue.get_by_email_id("e1") is None


class TestBatchQueueGetStaleItems:
    def test_no_stale_items(self, queue):
        assert queue.get_stale_items() == []

    def test_stale_items_detected(self, queue):
        item_id = queue.enqueue("e1", "t", "m", "s", "u")
        queue.mark_submitted([item_id], "b1")

        # Manually backdate submitted_at
        conn = queue._get_conn()
        old_time = (datetime.now() - timedelta(minutes=60)).isoformat()
        conn.execute(
            "UPDATE batch_queue SET submitted_at = ? WHERE id = ?",
            (old_time, item_id),
        )
        conn.commit()

        stale = queue.get_stale_items(timeout_minutes=30)
        assert len(stale) == 1


class TestBatchQueuePendingCount:
    def test_zero_when_empty(self, queue):
        assert queue.pending_count() == 0

    def test_counts_pending(self, queue):
        queue.enqueue("e1", "t", "m", "s", "u")
        queue.enqueue("e2", "t", "m", "s", "u")
        assert queue.pending_count() == 2


class TestBatchQueueGetOldestPendingAge:
    def test_zero_when_empty(self, queue):
        assert queue.get_oldest_pending_age_sec() == 0.0

    def test_returns_positive_age(self, queue):
        queue.enqueue("e1", "t", "m", "s", "u")
        age = queue.get_oldest_pending_age_sec()
        assert age >= 0


class TestBatchQueueGetItemsForBatch:
    def test_returns_batch_items(self, queue):
        id1 = queue.enqueue("e1", "t", "m", "s", "u")
        id2 = queue.enqueue("e2", "t", "m", "s", "u")
        queue.mark_submitted([id1, id2], "b1")

        items = queue.get_items_for_batch("b1")
        assert len(items) == 2

    def test_empty_for_unknown_batch(self, queue):
        assert queue.get_items_for_batch("unknown") == []


class TestBatchQueueMarkBatchEnded:
    def test_mark_batch_ended(self, queue):
        id1 = queue.enqueue("e1", "t", "m", "s", "u")
        queue.mark_submitted([id1], "b1")
        queue.mark_batch_ended("b1")

        active = queue.get_active_batches()
        assert len(active) == 0


class TestBatchQueueCleanupOld:
    def test_cleanup_removes_old_completed(self, queue):
        item_id = queue.enqueue("e1", "t", "m", "s", "u")
        queue.mark_completed(item_id, "done")

        # Backdate
        conn = queue._get_conn()
        old_time = (datetime.now() - timedelta(days=10)).isoformat()
        conn.execute(
            "UPDATE batch_queue SET completed_at = ? WHERE id = ?",
            (old_time, item_id),
        )
        conn.commit()

        queue.cleanup_old(days=7)
        # Item should be removed
        items = conn.execute("SELECT COUNT(*) as cnt FROM batch_queue").fetchone()
        assert items["cnt"] == 0

    def test_cleanup_keeps_recent(self, queue):
        item_id = queue.enqueue("e1", "t", "m", "s", "u")
        queue.mark_completed(item_id, "done")
        queue.cleanup_old(days=7)
        # Still within 7 days, should remain
        conn = queue._get_conn()
        items = conn.execute("SELECT COUNT(*) as cnt FROM batch_queue").fetchone()
        assert items["cnt"] == 1


class TestBatchQueuePrivacyDelete:
    def test_delete_by_account_removes_only_matching_rows(self, queue):
        queue.enqueue("e1", "t", "m", "secret sys", "secret user", account_id="1")
        queue.enqueue("e2", "t", "m", "other sys", "other user", account_id="2")

        assert queue.delete_by_account(1) == 1

        assert queue.get_by_email_id("e1", account_id="1") is None
        assert queue.get_by_email_id("e2", account_id="2") is not None
