# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for the background email sync service.

Tests cover:
- SyncService lifecycle (start, stop, trigger)
- Retry decorator with exponential backoff
- Sync callbacks for WebSocket events
- SyncResult and SyncStatus dataclasses
- Account sync logic
"""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.db.models.email import Email
from app.db.repositories import EmailRepository
from app.services.sync_service import (
    SyncResult,
    SyncService,
    SyncStatus,
    _SYNC_BODY_PREFETCH_LIMIT,
    _get_account_setting,
    _set_account_setting,
    _warm_detail_cache_from_sync,
    get_sync_service,
    init_sync_service,
    with_retry,
)


# ==============================================================================
# Detail-cache warming (cold-account body-latency fix, #6)
# ==============================================================================


class TestWarmDetailCacheFromSync:
    """`_warm_detail_cache_from_sync` reuses bodies the sync already fetched so
    the first email open is instant instead of a redundant, Graph-throttled
    on-demand re-fetch (metadata-only mode discards bodies after sync)."""

    def _email(self, **kw):
        from types import SimpleNamespace
        base = dict(
            id="e1", sender="a@x.com", sender_name="A", subject="S",
            body="hello world", body_html="<p>hello world</p>",
            received_at=None, is_read=False, has_attachments=False,
            cc=[], conversation_id=None,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_warms_html_and_text_bodies_and_skips_unservable(self):
        account = MagicMock()
        account.id = 42
        emails = [
            self._email(id="html1", body_html="<p>hi</p>", body="hi"),
            self._email(id="text1", body_html=None, body="just plain text"),   # wrapped
            self._email(id="att1", has_attachments=True),                      # skipped
            self._email(id="cid1", body_html='<img src="cid:abc">', body=""),  # skipped
            self._email(id="empty1", body_html=None, body=""),                 # skipped
        ]
        with patch("app.api.routes_helpers._set_cached_email_detail") as mock_set:
            warmed = _warm_detail_cache_from_sync(emails, account)

        cached_ids = {c.args[0] for c in mock_set.call_args_list}
        assert warmed == 2
        assert cached_ids == {"html1", "text1"}
        # account-scoped so bodies never leak across accounts
        assert all(c.kwargs["account_id"] == 42 for c in mock_set.call_args_list)
        # text-only body wrapped to HTML so it satisfies get_email's body_ready gate
        text_payload = next(c.args[1] for c in mock_set.call_args_list if c.args[0] == "text1")
        assert text_payload["body_html"].startswith("<div") and "just plain text" in text_payload["body_html"]

    def test_newest_inserted_last_for_eviction_durability(self):
        # Provider returns newest-first; warming inserts oldest-first so the
        # newest mail sits at the MRU end and survives eviction longest.
        account = MagicMock()
        account.id = 1
        emails = [self._email(id="newest"), self._email(id="middle"), self._email(id="oldest")]
        with patch("app.api.routes_helpers._set_cached_email_detail") as mock_set:
            _warm_detail_cache_from_sync(emails, account)
        assert [c.args[0] for c in mock_set.call_args_list] == ["oldest", "middle", "newest"]

    def test_bounded_to_prefetch_limit(self):
        account = MagicMock()
        account.id = 1
        emails = [self._email(id=f"e{i}") for i in range(_SYNC_BODY_PREFETCH_LIMIT + 25)]
        with patch("app.api.routes_helpers._set_cached_email_detail"):
            warmed = _warm_detail_cache_from_sync(emails, account)
        assert warmed == _SYNC_BODY_PREFETCH_LIMIT


# ==============================================================================
# Account settings helpers
# ==============================================================================


class TestAccountSettings:
    """Round-trip helpers for the settings_json marker field."""

    def test_get_setting_default_when_json_empty(self):
        acc = MagicMock()
        acc.settings_json = None
        assert _get_account_setting(acc, "k", default="fallback") == "fallback"

    def test_get_setting_default_when_key_missing(self):
        acc = MagicMock()
        acc.settings_json = '{"other": 1}'
        assert _get_account_setting(acc, "archive_backfilled_at") is None

    def test_get_setting_returns_value(self):
        acc = MagicMock()
        acc.settings_json = '{"archive_backfilled_at": "2026-04-23T07:00:00"}'
        assert _get_account_setting(acc, "archive_backfilled_at") == "2026-04-23T07:00:00"

    def test_set_setting_on_empty_json(self):
        acc = MagicMock()
        acc.settings_json = None
        _set_account_setting(acc, "archive_backfilled_at", "2026-04-23T07:00:00")
        import json
        data = json.loads(acc.settings_json)
        assert data == {"archive_backfilled_at": "2026-04-23T07:00:00"}

    def test_set_setting_preserves_other_keys(self):
        acc = MagicMock()
        acc.settings_json = '{"existing": "keep"}'
        _set_account_setting(acc, "archive_backfilled_at", "2026-04-23T07:00:00")
        import json
        data = json.loads(acc.settings_json)
        assert data["existing"] == "keep"
        assert data["archive_backfilled_at"] == "2026-04-23T07:00:00"

    def test_set_setting_recovers_from_corrupt_json(self):
        """Bad settings_json should not block the write — we overwrite."""
        acc = MagicMock()
        acc.settings_json = "not-json-{{{"
        _set_account_setting(acc, "archive_backfilled_at", "2026-04-23T07:00:00")
        import json
        data = json.loads(acc.settings_json)
        assert data == {"archive_backfilled_at": "2026-04-23T07:00:00"}


# ==============================================================================
# SyncResult Tests
# ==============================================================================


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_sync_result_success(self):
        """Test creating a successful sync result."""
        result = SyncResult(
            account_id=1,
            account_email="test@example.com",
            success=True,
            new_emails_count=5,
            duration_ms=100,
        )

        assert result.account_id == 1
        assert result.account_email == "test@example.com"
        assert result.success is True
        assert result.new_emails_count == 5
        assert result.error_message is None
        assert result.duration_ms == 100

    def test_sync_result_failure(self):
        """Test creating a failed sync result."""
        result = SyncResult(
            account_id=2,
            account_email="fail@example.com",
            success=False,
            error_message="Authentication failed",
            duration_ms=50,
        )

        assert result.account_id == 2
        assert result.success is False
        assert result.error_message == "Authentication failed"
        assert result.new_emails_count == 0

    def test_sync_result_defaults(self):
        """Test SyncResult default values."""
        result = SyncResult(
            account_id=1,
            account_email="test@example.com",
            success=True,
        )

        assert result.new_emails_count == 0
        assert result.error_message is None
        assert result.duration_ms == 0


# ==============================================================================
# SyncStatus Tests
# ==============================================================================


class TestSyncStatus:
    """Tests for SyncStatus dataclass."""

    def test_sync_status_defaults(self):
        """Test SyncStatus default values."""
        status = SyncStatus()

        assert status.is_running is False
        assert status.is_syncing is False
        assert status.last_sync_at is None
        assert status.next_sync_at is None
        assert status.sync_interval_seconds == 120
        assert status.last_results == []

    def test_sync_status_custom_interval(self):
        """Test SyncStatus with custom interval."""
        status = SyncStatus(sync_interval_seconds=60)
        assert status.sync_interval_seconds == 60

    def test_sync_status_with_results(self):
        """Test SyncStatus with sync results."""
        results = [
            SyncResult(account_id=1, account_email="a@test.com", success=True),
            SyncResult(account_id=2, account_email="b@test.com", success=False),
        ]
        status = SyncStatus(last_results=results)

        assert len(status.last_results) == 2
        assert status.last_results[0].success is True
        assert status.last_results[1].success is False


# ==============================================================================
# with_retry Decorator Tests
# ==============================================================================


class TestWithRetryDecorator:
    """Tests for the with_retry decorator."""

    def test_retry_success_first_attempt(self):
        """Test function succeeds on first attempt."""
        call_count = 0

        @with_retry(max_attempts=3)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()

        assert result == "success"
        assert call_count == 1

    def test_retry_success_after_failures(self):
        """Test function succeeds after initial failures."""
        call_count = 0

        @with_retry(max_attempts=3, base_delay=0.01)
        def eventually_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary failure")
            return "success"

        result = eventually_succeeds()

        assert result == "success"
        assert call_count == 3

    def test_retry_all_attempts_fail(self):
        """Test function raises after all attempts fail."""
        call_count = 0

        @with_retry(max_attempts=3, base_delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        with pytest.raises(ValueError, match="Always fails"):
            always_fails()

        assert call_count == 3

    def test_retry_specific_exceptions(self):
        """Test retry only catches specified exceptions."""
        call_count = 0

        @with_retry(max_attempts=3, base_delay=0.01, exceptions=(ConnectionError,))
        def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retried")

        with pytest.raises(ValueError, match="Not retried"):
            raises_value_error()

        assert call_count == 1  # Should not retry ValueError

    def test_retry_exponential_backoff(self):
        """Test exponential backoff delays."""
        start_time = time.time()

        @with_retry(max_attempts=3, base_delay=0.1, exponential_base=2.0)
        def always_fails():
            raise Exception("Fail")

        with pytest.raises(Exception):
            always_fails()

        elapsed = time.time() - start_time
        # Expected delays: 0.1 (first), 0.2 (second) = 0.3 total
        # Allow some tolerance
        assert elapsed >= 0.25
        assert elapsed < 1.0


# ==============================================================================
# SyncService Lifecycle Tests
# ==============================================================================


class TestSyncServiceLifecycle:
    """Tests for SyncService start/stop lifecycle."""

    def test_service_initialization(self):
        """Test SyncService initializes with correct defaults."""
        service = SyncService()

        assert service.sync_interval == 120
        assert service.is_running is False
        assert service.is_syncing is False

    def test_service_custom_interval(self):
        """Test SyncService with custom interval."""
        service = SyncService(sync_interval=60)
        assert service.sync_interval == 60

    @patch("app.services.sync_service.get_db_session")
    def test_service_start_stop(self, mock_db_session):
        """Test starting and stopping the service."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_db_session.return_value = mock_session

        # Mock AccountRepository to return no accounts
        with patch("app.services.sync_service.AccountRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_active_accounts.return_value = []
            mock_repo_class.return_value = mock_repo

            service = SyncService(sync_interval=1)

            assert service.is_running is False

            service.start()
            assert service.is_running is True

            # Give the thread a moment to start
            time.sleep(0.1)

            service.stop(timeout=2.0)
            assert service.is_running is False

    def test_service_start_already_running(self):
        """Test starting an already running service logs warning."""
        service = SyncService()
        service._status.is_running = True

        # Should return without error
        service.start()

        # Still running
        assert service.is_running is True

    def test_service_stop_not_running(self):
        """Test stopping a non-running service is a no-op."""
        service = SyncService()
        assert service.is_running is False

        # Should return without error
        service.stop()

        assert service.is_running is False


# ==============================================================================
# SyncService Trigger Tests
# ==============================================================================


class TestSyncServiceTrigger:
    """Tests for manual sync trigger."""

    def test_trigger_sync_when_not_syncing(self):
        """Test triggering sync when not already syncing."""
        service = SyncService()
        service._status.is_running = True

        # Mock the perform_sync method to avoid actual sync
        with patch.object(service, "_perform_sync"):
            result = service.trigger_sync()

        assert result is True

    def test_trigger_sync_when_already_syncing(self):
        """Test triggering sync when already syncing returns False."""
        service = SyncService()
        service._is_syncing = True

        result = service.trigger_sync()

        assert result is False

    def test_trigger_sync_recovers_stale_sync_flag(self):
        """A stale in-progress flag must not block new sync triggers forever."""
        service = SyncService()
        service._is_syncing = True
        service._status.is_syncing = True
        service._sync_started_at_monotonic = (
            time.monotonic() - service._STALE_SYNC_SECONDS - 1
        )

        with patch.object(service, "_perform_sync"):
            result = service.trigger_sync()

        assert result is True

    def test_trigger_account_sync_targets_one_account(self):
        """Gmail push should be able to sync only the account that changed."""
        service = SyncService()

        with patch.object(service, "_perform_sync") as perform_sync, patch(
            "app.services.sync_service.threading.Thread"
        ) as thread_cls:
            thread_instance = thread_cls.return_value
            result = service.trigger_account_sync(42)

        assert result is True
        thread_cls.assert_called_once()
        thread_kwargs = thread_cls.call_args.kwargs["kwargs"]
        assert thread_kwargs["only_account_ids"] == [42]
        assert "claimed_account_sync_generation" in thread_kwargs
        thread_instance.start.assert_called_once()
        perform_sync.assert_not_called()

    def test_trigger_account_sync_queues_when_busy(self):
        """A second Gmail push for the same account should be deduped."""
        service = SyncService()
        service._active_account_sync_generations[42] = 1
        service._active_account_sync_started_at[42] = time.monotonic()
        service._is_syncing = True

        with patch("app.services.sync_service.threading.Thread") as thread_cls:
            result = service.trigger_account_sync(42)

        assert result is True
        assert service._pending_account_sync_ids == {42}
        thread_cls.assert_not_called()

    def test_trigger_account_sync_starts_when_other_account_is_busy(self):
        """A noisy account must not block a scoped sync for another account."""
        service = SyncService()
        service._active_account_sync_generations[10] = 1
        service._active_account_sync_started_at[10] = time.monotonic()
        service._is_syncing = True

        with patch("app.services.sync_service.threading.Thread") as thread_cls:
            thread_instance = thread_cls.return_value
            result = service.trigger_account_sync(42)

        assert result is True
        thread_cls.assert_called_once()
        thread_kwargs = thread_cls.call_args.kwargs["kwargs"]
        assert thread_kwargs["only_account_ids"] == [42]
        assert "claimed_account_sync_generation" in thread_kwargs
        thread_instance.start.assert_called_once()
        assert service._pending_account_sync_ids == set()

    def test_trigger_account_sync_caps_burst_concurrency(self):
        """A provider burst must not create one worker thread per account."""
        service = SyncService(max_concurrent_account_syncs=2)

        with patch("app.services.sync_service.threading.Thread") as thread_cls:
            for account_id in range(1, 1001):
                assert service.trigger_account_sync(account_id) is True

        started_account_ids = [
            call.kwargs["kwargs"]["only_account_ids"][0]
            for call in thread_cls.call_args_list
        ]
        assert started_account_ids == [1, 2]
        assert set(service._active_account_sync_generations) == {1, 2}
        assert len(service._pending_account_sync_ids) == 998
        assert 1000 in service._pending_account_sync_ids

    def test_trigger_account_sync_queues_when_full_sync_is_busy(self):
        """A scoped push waits behind a full sync, but is not dropped."""
        service = SyncService()
        service._active_full_sync_generation = 1
        service._sync_started_at_monotonic = time.monotonic()
        service._is_syncing = True

        with patch("app.services.sync_service.threading.Thread") as thread_cls:
            result = service.trigger_account_sync(42)

        assert result is True
        assert service._pending_account_sync_ids == {42}
        thread_cls.assert_not_called()

    @patch("app.services.sync_service.get_db_session")
    def test_perform_sync_replays_pending_account_syncs(self, mock_db_session):
        """Pending scoped syncs are replayed after the active sync finishes."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_db_session.return_value = mock_session

        service = SyncService()
        service._pending_account_sync_ids.update({6, 4})

        with patch("app.services.sync_service.AccountRepository") as repo_cls, patch(
            "app.services.sync_service.threading.Thread"
        ) as thread_cls:
            repo_cls.return_value.get_active_accounts.return_value = []
            thread_instance = thread_cls.return_value
            service._perform_sync()

        assert thread_cls.call_count == 2
        started_account_ids = {
            call.kwargs["kwargs"]["only_account_ids"][0]
            for call in thread_cls.call_args_list
        }
        assert started_account_ids == {4, 6}
        assert thread_instance.start.call_count == 2
        assert service._pending_account_sync_ids == set()

    @patch("app.services.sync_service.get_db_session")
    def test_perform_sync_claims_requested_pending_account_ids(
        self, mock_db_session
    ):
        """A queued scoped sync removes the account ids it is about to process."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_db_session.return_value = mock_session

        service = SyncService()
        service._pending_account_sync_ids.update({4, 6, 8})

        with patch("app.services.sync_service.AccountRepository") as repo_cls, patch(
            "app.services.sync_service.threading.Thread"
        ) as thread_cls:
            repo_cls.return_value.get_active_accounts.return_value = []
            service._perform_sync(only_account_ids=[4, 6])

        assert service._pending_account_sync_ids == set()
        thread_cls.assert_called_once()
        assert thread_cls.call_args.kwargs["kwargs"]["only_account_ids"] == [8]

    @patch("app.services.sync_service.get_db_session")
    def test_perform_sync_drains_pending_only_to_free_capacity(
        self, mock_db_session
    ):
        """Finishing one scoped worker should release one queued account, not all."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_db_session.return_value = mock_session

        service = SyncService(max_concurrent_account_syncs=2)
        service._active_account_sync_generations.update({1: 1, 2: 2})
        now = time.monotonic()
        service._active_account_sync_started_at.update({1: now, 2: now})
        service._pending_account_sync_ids.update({3, 4, 5})
        service._is_syncing = True

        with patch("app.services.sync_service.AccountRepository") as repo_cls, patch(
            "app.services.sync_service.threading.Thread"
        ) as thread_cls:
            repo_cls.return_value.get_active_accounts.return_value = []
            service._perform_sync(
                only_account_ids=[1],
                claimed_account_sync_generation=1,
            )

        assert set(service._active_account_sync_generations) == {2, 3}
        assert service._pending_account_sync_ids == {4, 5}
        thread_cls.assert_called_once()
        assert thread_cls.call_args.kwargs["kwargs"]["only_account_ids"] == [3]

    @patch("app.services.sync_service.get_db_session")
    def test_perform_sync_claims_only_accounts_not_already_syncing(
        self, mock_db_session
    ):
        """Queued batches should run free accounts instead of waiting globally."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_db_session.return_value = mock_session

        busy_account = MagicMock()
        busy_account.id = 10
        busy_account.email = "busy@example.test"
        free_account = MagicMock()
        free_account.id = 4
        free_account.email = "free@example.test"

        service = SyncService()
        service._active_account_sync_generations[10] = 1
        service._active_account_sync_started_at[10] = time.monotonic()
        service._is_syncing = True

        with patch("app.services.sync_service.AccountRepository") as repo_cls, patch(
            "app.services.sync_service.threading.Thread"
        ) as thread_cls, patch.object(
            service,
            "_sync_account_isolated",
            return_value=SyncResult(
                account_id=4,
                account_email="free@example.test",
                success=True,
            ),
        ) as sync_account:
            repo_cls.return_value.get_active_accounts.return_value = [
                busy_account,
                free_account,
            ]
            service._perform_sync(only_account_ids=[4, 10])

        sync_account.assert_called_once_with(free_account)
        assert service._pending_account_sync_ids == {10}
        thread_cls.assert_not_called()
        assert service._active_account_sync_generations == {10: 1}

    def test_status_clears_stale_sync_flag(self):
        """Status reads should not expose an indefinitely stale syncing state."""
        service = SyncService()
        service._is_syncing = True
        service._status.is_syncing = True
        service._sync_started_at_monotonic = (
            time.monotonic() - service._STALE_SYNC_SECONDS - 1
        )

        status = service.status

        assert status.is_syncing is False
        assert service._is_syncing is False

    def test_status_clears_stale_account_sync_flag(self):
        """A stale scoped sync should not block future pushes for that account."""
        service = SyncService()
        service._active_account_sync_generations[42] = 1
        service._active_account_sync_started_at[42] = (
            time.monotonic() - service._STALE_SYNC_SECONDS - 1
        )
        service._is_syncing = True
        service._status.is_syncing = True

        status = service.status

        assert status.is_syncing is False
        assert service._is_syncing is False
        assert service._active_account_sync_generations == {}


# ==============================================================================
# SyncService Callbacks Tests
# ==============================================================================


class TestSyncServiceCallbacks:
    """Tests for sync service callback invocation."""

    @patch("app.services.sync_service.get_db_session")
    def test_on_sync_started_callback(self, mock_db_session):
        """Test on_sync_started callback is invoked."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_db_session.return_value = mock_session

        started_accounts = []

        def on_started(account_ids):
            started_accounts.extend(account_ids)

        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "test@example.com"
        mock_account.provider = "gmail"

        with patch("app.services.sync_service.AccountRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_active_accounts.return_value = [mock_account]
            mock_repo_class.return_value = mock_repo

            with patch.object(
                SyncService, "_sync_account", return_value=SyncResult(
                    account_id=1, account_email="test@example.com", success=True
                )
            ):
                service = SyncService(on_sync_started=on_started)
                service._perform_sync()

        assert started_accounts == [1]

    @patch("app.services.sync_service.get_db_session")
    def test_on_sync_complete_callback(self, mock_db_session):
        """Test on_sync_complete callback is invoked with results."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_db_session.return_value = mock_session

        complete_results = []
        complete_duration = []

        def on_complete(results, duration_ms):
            complete_results.extend(results)
            complete_duration.append(duration_ms)

        with patch("app.services.sync_service.AccountRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_active_accounts.return_value = []
            mock_repo_class.return_value = mock_repo

            service = SyncService(on_sync_complete=on_complete)
            service._perform_sync()

        # Should have been called with empty results
        assert complete_results == []
        assert len(complete_duration) == 1
        assert complete_duration[0] >= 0

    @patch("app.services.sync_service.get_db_session")
    def test_callback_error_does_not_break_sync(self, mock_db_session):
        """Test that callback errors don't break the sync process."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_db_session.return_value = mock_session

        def broken_callback(*args, **kwargs):
            raise RuntimeError("Callback error")

        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "test@example.com"

        with patch("app.services.sync_service.AccountRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_active_accounts.return_value = [mock_account]
            mock_repo_class.return_value = mock_repo

            with patch.object(
                SyncService, "_sync_account", return_value=SyncResult(
                    account_id=1, account_email="test@example.com", success=True
                )
            ):
                service = SyncService(
                    on_sync_started=broken_callback,
                    on_sync_progress=broken_callback,
                    on_sync_complete=broken_callback,
                )

                # Should not raise
                service._perform_sync()

        # Verify status was still updated
        assert service._status.last_sync_at is not None


# ==============================================================================
# SyncService Account Sync Tests
# ==============================================================================


class TestSyncServiceAccountSync:
    """Tests for individual account sync logic."""

    def test_sync_account_no_adapter(self):
        """Test sync_account returns error when no adapter available."""
        service = SyncService()

        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "test@example.com"
        mock_account.provider = "unknown_provider"

        with patch.object(service, "_get_adapter_for_account", return_value=None):
            result = service._sync_account(MagicMock(), mock_account)

        assert result.success is False
        assert "No adapter" in result.error_message

    def test_sync_account_auth_failure(self):
        """Test sync_account returns error when authentication fails."""
        service = SyncService()

        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "test@example.com"
        mock_account.provider = "gmail"

        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = False

        with patch.object(service, "_get_adapter_for_account", return_value=mock_adapter):
            result = service._sync_account(MagicMock(), mock_account)

        assert result.success is False
        assert "Authentication failed" in result.error_message

    def test_sync_account_success(self):
        """Test successful account sync."""
        service = SyncService()

        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "test@example.com"
        mock_account.provider = "gmail"
        mock_account.last_sync_at = None

        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = True

        mock_session = MagicMock()

        with patch.object(service, "_get_adapter_for_account", return_value=mock_adapter):
            with patch.object(service, "_fetch_emails_with_retry", return_value=[]):
                with patch.object(service, "_store_emails", return_value=0):
                    with patch("app.services.sync_service.AccountRepository"):
                        result = service._sync_account(mock_session, mock_account)

        assert result.success is True
        assert result.account_id == 1
        assert result.account_email == "test@example.com"

    def test_sync_account_with_new_emails(self):
        """Test account sync with new emails."""
        service = SyncService()

        new_email_received = []

        def on_new_email(email_data):
            new_email_received.append(email_data)

        service._on_new_email = on_new_email

        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "test@example.com"
        mock_account.provider = "gmail"
        mock_account.last_sync_at = None

        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = True
        # Explicit empty SENT pull: this test exercises the inbox-side count.
        # Without this stub, the new `_delta_pull_sent` belt-and-braces SENT
        # fetch (added 2026-05-04) would call the auto-spec'd MagicMock and
        # inflate `new_emails_count` by the mocked `_store_emails` return.
        mock_adapter.get_sent_emails.return_value = []

        mock_email = MagicMock()
        mock_email.id = "email123"

        mock_session = MagicMock()

        with patch.object(service, "_get_adapter_for_account", return_value=mock_adapter):
            with patch.object(service, "_fetch_emails_with_retry", return_value=[mock_email]):
                with patch.object(service, "_store_emails", return_value=1):
                    with patch("app.services.sync_service.AccountRepository"):
                        result = service._sync_account(mock_session, mock_account)

        assert result.success is True
        assert result.new_emails_count == 1

    # ── Audit 2026-06-11 B-01 ────────────────────────────────────────────
    # Sur échec de `_store_emails` en delta sync, l'ancien rattrapage P0-A1
    # persistait le history_id via update_sync_time() qui bump AUSSI
    # last_sync_at → le fallback timestamp lisait « maintenant » et ne
    # re-fetchait jamais le batch perdu ; si le fallback échouait aussi, le
    # checkpoint avancé sautait définitivement ces emails.

    def _b01_account(self):
        account = MagicMock()
        account.id = 1
        account.email = "test@example.com"
        account.provider = "gmail"
        account.last_history_id = "100"
        account.last_sync_at = datetime(2026, 6, 11, 8, 0, 0)
        return account

    def _b01_adapter(self):
        adapter = MagicMock()
        adapter.authenticate.return_value = True
        adapter.get_history_changes.return_value = {
            "new_history_id": "200",
            "added": [MagicMock()],
            "deleted": [],
            "label_changes": [],
        }
        adapter.get_current_history_id.return_value = "250"
        adapter.get_sent_emails.return_value = []
        return adapter

    @staticmethod
    def _b01_repo_stub(account, calls):
        """Émule le VRAI effet de bord d'update_sync_time (bump last_sync_at)."""

        class RepoStub:
            def __init__(self, session):
                self.session = session

            def update_sync_time(self, account_id, history_id=None):
                calls.append((account_id, history_id))
                account.last_sync_at = datetime.utcnow()
                if history_id is not None:
                    account.last_history_id = history_id
                return True

        return RepoStub

    def test_delta_store_failure_fallback_uses_pre_delta_since(self):
        """Le fallback timestamp doit re-fetcher depuis AVANT le delta raté."""
        service = SyncService()
        account = self._b01_account()
        original_since = account.last_sync_at
        adapter = self._b01_adapter()
        update_calls: list = []
        captured_since: list = []

        def fetch_spy(adapter_arg, since):
            captured_since.append(since)
            return []

        # 1er _store_emails (delta) échoue, 2e (fallback) réussit.
        store_results = iter([Exception("database is locked"), 0])

        def store_side_effect(*args, **kwargs):
            result = next(store_results)
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(service, "_get_adapter_for_account", return_value=adapter), \
             patch.object(service, "_maybe_archive_backfill"), \
             patch.object(service, "_maybe_inbox_backfill"), \
             patch.object(service, "_maybe_sent_backfill"), \
             patch.object(service, "_fetch_emails_with_retry", side_effect=fetch_spy), \
             patch.object(service, "_store_emails", side_effect=store_side_effect), \
             patch("app.services.sync_service.AccountRepository",
                   self._b01_repo_stub(account, update_calls)):
            result = service._sync_account(MagicMock(), account)

        assert result.success is True
        # Le fallback fetch part du last_sync_at PRÉ-delta, pas de « maintenant ».
        assert captured_since == [original_since]
        # Un seul persist, en FIN de fallback réussi, avec le history_id frais —
        # pas de persist prématuré du history_id delta ("200") dans le except.
        assert update_calls == [(1, "250")]

    def test_poisoned_delta_schedules_inbox_backfill(self):
        """A poisoned (id-only) Outlook checkpoint must clear inbox_backfilled_at
        so the next tick re-fetches metadata and heals the blank rows, then
        re-initialise a fresh checkpoint via the timestamp fallback."""
        import json as _json
        from app.services.sync_service import _get_account_setting

        service = SyncService()
        account = self._b01_account()
        account.provider = "outlook"
        # The inbox backfill already ran once (marker set).
        account.settings_json = _json.dumps({"inbox_backfilled_at": "2026-06-23T00:00:00"})

        adapter = self._b01_adapter()
        adapter.get_history_changes.return_value = {
            "new_history_id": None,  # forces fallback + re-init
            "added": [],
            "deleted": [],
            "label_changes": [],
            "poisoned": True,
        }
        update_calls: list = []

        with patch.object(service, "_get_adapter_for_account", return_value=adapter), \
             patch.object(service, "_maybe_archive_backfill"), \
             patch.object(service, "_maybe_inbox_backfill"), \
             patch.object(service, "_maybe_sent_backfill"), \
             patch.object(service, "_fetch_emails_with_retry", return_value=[]), \
             patch.object(service, "_store_emails", return_value=0), \
             patch("app.services.sync_service.AccountRepository",
                   self._b01_repo_stub(account, update_calls)):
            result = service._sync_account(MagicMock(), account)

        assert result.success is True
        # Marker cleared → _maybe_inbox_backfill re-runs next tick to heal blanks.
        assert _get_account_setting(account, "inbox_backfilled_at") is None
        # A fresh, healthy checkpoint was persisted via the fallback.
        assert update_calls == [(1, "250")]

    def test_delta_and_fallback_both_fail_checkpoint_not_advanced(self):
        """Si delta ET fallback échouent, ne rien persister (re-fetch au prochain tick)."""
        service = SyncService()
        account = self._b01_account()
        original_since = account.last_sync_at
        adapter = self._b01_adapter()
        update_calls: list = []

        with patch.object(service, "_get_adapter_for_account", return_value=adapter), \
             patch.object(service, "_maybe_archive_backfill"), \
             patch.object(service, "_maybe_inbox_backfill"), \
             patch.object(service, "_maybe_sent_backfill"), \
             patch.object(service, "_fetch_emails_with_retry", return_value=[MagicMock()]), \
             patch.object(service, "_store_emails",
                          side_effect=Exception("database is locked")), \
             patch("app.services.sync_service.AccountRepository",
                   self._b01_repo_stub(account, update_calls)):
            result = service._sync_account(MagicMock(), account)

        assert result.success is False
        # Aucun checkpoint avancé : ni history_id, ni last_sync_at.
        assert update_calls == []
        assert account.last_history_id == "100"
        assert account.last_sync_at == original_since

    def test_sync_account_closes_db_transactions_before_provider_io(self):
        """Provider calls must not run while a SQLAlchemy transaction is open."""
        service = SyncService()

        class TxSession:
            def __init__(self):
                self._in_transaction = True
                self.events = []

            def in_transaction(self):
                return self._in_transaction

            def commit(self):
                self.events.append("commit")
                self._in_transaction = False

            def rollback(self):
                self.events.append("rollback")
                self._in_transaction = False

            def open_transaction(self, event):
                assert not self._in_transaction
                self.events.append(event)
                self._in_transaction = True

        class Adapter:
            provider_name = "gmail"

            def __init__(self, session):
                self.session = session

            def authenticate(self):
                assert not self.session.in_transaction()
                self.session.events.append("authenticate")
                return True

            def get_sent_emails(self, limit, since=None):
                assert not self.session.in_transaction()
                self.session.events.append("get_sent_emails")
                return []

            def disconnect(self):
                assert not self.session.in_transaction()
                self.session.events.append("disconnect")

        class FakeAccountRepository:
            def __init__(self, session):
                self.session = session

            def update_sync_time(self, account_id, history_id=None):
                self.session.open_transaction("update_sync_time")
                return True

        session = TxSession()
        adapter = Adapter(session)
        account = MagicMock()
        account.id = 1
        account.email = "test@example.com"
        account.provider = "gmail"
        account.last_sync_at = None
        account.last_history_id = None

        def backfill(session_arg, _adapter, _account):
            session_arg.open_transaction("backfill")
            return 0

        def fetch(_adapter, since):
            assert since is None
            assert not session.in_transaction()
            session.events.append("fetch_messages")
            return []

        with patch.object(service, "_get_adapter_for_account", return_value=adapter), \
             patch.object(service, "_maybe_archive_backfill", side_effect=backfill), \
             patch.object(service, "_maybe_inbox_backfill", side_effect=backfill), \
             patch.object(service, "_maybe_sent_backfill", side_effect=backfill), \
             patch.object(service, "_fetch_emails_with_retry", side_effect=fetch), \
             patch("app.services.sync_service.AccountRepository", FakeAccountRepository):
            result = service._sync_account(session, account)

        assert result.success is True
        assert session.in_transaction() is False
        assert session.events == [
            "commit",
            "authenticate",
            "backfill",
            "commit",
            "backfill",
            "commit",
            "backfill",
            "commit",
            "fetch_messages",
            "get_sent_emails",
            "update_sync_time",
            "commit",
            "disconnect",
        ]


# ==============================================================================
# Global Service Functions Tests
# ==============================================================================


class TestGlobalServiceFunctions:
    """Tests for global service management functions."""

    def test_init_sync_service(self):
        """Test initializing the global sync service."""
        service = init_sync_service(sync_interval=60)

        assert service is not None
        assert service.sync_interval == 60

    def test_get_sync_service_after_init(self):
        """Test getting the global sync service after initialization."""
        init_sync_service(sync_interval=90)
        service = get_sync_service()

        assert service is not None
        assert service.sync_interval == 90

    def test_init_sync_service_replaces_existing(self):
        """Test that re-initializing replaces the existing service."""
        init_sync_service(sync_interval=60)
        service2 = init_sync_service(sync_interval=120)

        current = get_sync_service()

        assert current is service2
        assert current.sync_interval == 120


# ==============================================================================
# SyncService Store Emails Tests
# ==============================================================================


class TestSyncServiceStoreEmails:
    """Tests for storing synced emails in database."""

    def test_store_emails_empty_list(self):
        """Test storing empty list returns 0."""
        service = SyncService()

        mock_session = MagicMock()
        mock_account = MagicMock()

        count = service._store_emails(mock_session, mock_account, [])

        assert count == 0

    def test_store_emails_skip_existing(self):
        """Test that existing emails are skipped."""
        service = SyncService()

        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1

        mock_email = MagicMock()
        mock_email.id = "existing123"
        mock_email.sender = "sender@test.com"
        mock_email.attachments = []
        mock_email.has_attachments = False

        with patch("app.services.sync_service.EmailRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_by_email_id.return_value = MagicMock()  # Email exists
            mock_repo_class.return_value = mock_repo

            with patch("app.services.sync_service.ContactRepository"):
                count = service._store_emails(mock_session, mock_account, [mock_email])

        assert count == 0

    def test_store_emails_heals_blank_existing_row(self):
        """A row stored blank by the legacy poisoned Outlook delta checkpoint is
        repaired when a richer re-fetch re-encounters the same email_id."""
        from types import SimpleNamespace

        service = SyncService()
        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "me@test.com"

        # The blank row left behind by an id-only delta insert: empty headers,
        # plus the bogus sync-time date / NULL thread / is_read=False defaults.
        bogus_insert_date = datetime(2026, 6, 23, 14, 4, tzinfo=timezone.utc)
        existing = SimpleNamespace(
            subject="", sender="", sender_name="", recipients="", cc="",
            date=bogus_insert_date, thread_id=None, is_read=False,
            body_text="body", body_html="<p>body</p>", snippet="x",
            raw_headers="{}", is_sent=False, deadline_at=None,
        )

        real_received = datetime(2026, 6, 20, 9, 30, tzinfo=timezone.utc)
        std = MagicMock()
        std.id = "blank123"
        std.subject = "Real Subject"
        std.sender = "alice@test.com"
        std.sender_name = "Alice"
        std.to = ["me@test.com"]
        std.cc = ["bob@test.com"]
        std.received_at = real_received
        std.conversation_id = "conv-real"
        std.is_read = True
        std.body = ""
        std.body_html = None
        std.preview = ""
        std.attachments = []
        std.has_attachments = False

        with patch("app.services.sync_service.EmailRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_by_email_id.return_value = existing
            mock_repo_class.return_value = mock_repo
            with patch("app.services.sync_service.ContactRepository"):
                count = service._store_emails(mock_session, mock_account, [std])

        assert count == 0  # existing row → not a fresh insert
        assert existing.subject == "Real Subject"
        assert existing.sender == "alice@test.com"
        assert existing.sender_name == "Alice"
        assert existing.recipients == "me@test.com"
        assert existing.cc == "bob@test.com"
        # Structural fields healed too (correct ordering + threading + read-state).
        assert existing.date == real_received
        assert existing.thread_id == "conv-real"
        assert existing.is_read is True

    def test_store_emails_does_not_clobber_good_row_with_blank(self):
        """Inverse guard: an id-only delta re-pass (blank std) must NEVER wipe a
        row that already has subject/sender."""
        from types import SimpleNamespace

        service = SyncService()
        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "me@test.com"

        good_date = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
        existing = SimpleNamespace(
            subject="Good Subject", sender="alice@test.com", sender_name="Alice",
            recipients="me@test.com", cc="", date=good_date, thread_id="conv-good",
            is_read=True, body_text="body", body_html="<p>b</p>",
            snippet="x", raw_headers="{}", is_sent=False, deadline_at=None,
        )

        std = MagicMock()
        std.id = "blank123"
        std.subject = ""        # id-only delta → no metadata
        std.sender = ""
        std.sender_name = None
        std.to = []
        std.cc = []
        std.received_at = None
        std.conversation_id = None
        std.is_read = False
        std.body = ""
        std.body_html = None
        std.preview = ""
        std.attachments = []
        std.has_attachments = False

        with patch("app.services.sync_service.EmailRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_by_email_id.return_value = existing
            mock_repo_class.return_value = mock_repo
            with patch("app.services.sync_service.ContactRepository"):
                service._store_emails(mock_session, mock_account, [std])

        # Nothing touched — not even is_read (which lives behind the blank gate).
        assert existing.subject == "Good Subject"
        assert existing.sender == "alice@test.com"
        assert existing.date == good_date
        assert existing.thread_id == "conv-good"
        assert existing.is_read is True

    def test_store_emails_new_email(self):
        """Test storing a new email."""
        service = SyncService()

        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1

        mock_email = MagicMock()
        mock_email.id = "new123"
        mock_email.conversation_id = "conv123"
        mock_email.subject = "Test Subject"
        mock_email.sender = "sender@test.com"
        mock_email.sender_name = "Sender"
        mock_email.to = ["recipient@test.com"]
        mock_email.cc = []
        mock_email.received_at = datetime.now(timezone.utc)
        mock_email.body = "Test body"
        mock_email.body_html = "<p>Test body</p>"
        mock_email.preview = "Test..."
        mock_email.is_read = False
        mock_email.attachments = []
        mock_email.has_attachments = False

        with patch("app.services.sync_service.EmailRepository") as mock_email_repo_class:
            mock_email_repo = MagicMock()
            mock_email_repo.get_by_email_id.return_value = None  # Email doesn't exist
            mock_email_repo_class.return_value = mock_email_repo

            with patch("app.services.sync_service.ContactRepository") as mock_contact_repo_class:
                mock_contact_repo = MagicMock()
                mock_contact = MagicMock()
                mock_contact.id = 1
                mock_contact_repo.get_or_create.return_value = (mock_contact, True)
                mock_contact_repo_class.return_value = mock_contact_repo

                count = service._store_emails(mock_session, mock_account, [mock_email])

        assert count == 1
        mock_session.add.assert_called_once()
        mock_contact_repo.increment_email_count.assert_called_once()

    def test_store_emails_metadata_only_does_not_persist_body(self, monkeypatch):
        """Default cloud sync stores headers/state, not raw email content."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        service = SyncService()

        mock_session = MagicMock()
        mock_account = MagicMock(id=1, email="me@example.com")

        mock_email = MagicMock()
        mock_email.id = "private123"
        mock_email.conversation_id = "conv123"
        mock_email.subject = "Private subject"
        mock_email.sender = "sender@test.com"
        mock_email.sender_name = "Sender"
        mock_email.to = ["me@example.com"]
        mock_email.cc = []
        mock_email.received_at = datetime.now(timezone.utc)
        mock_email.body = "Raw body that must not be stored"
        mock_email.body_html = "<p>Raw body that must not be stored</p>"
        mock_email.preview = "Sensitive preview"
        mock_email.is_read = False
        mock_email.attachments = []
        mock_email.has_attachments = False

        created_emails = []
        mock_session.add.side_effect = created_emails.append

        with patch("app.services.sync_service.EmailRepository") as mock_email_repo_class:
            mock_email_repo_class.return_value.get_by_email_id.return_value = None
            with patch("app.services.sync_service.ContactRepository") as mock_contact_repo_class:
                mock_contact_repo_class.return_value.get_or_create.return_value = (
                    MagicMock(id=1),
                    True,
                )

                count = service._store_emails(mock_session, mock_account, [mock_email])

        assert count == 1
        assert len(created_emails) == 1
        assert created_emails[0].body_text is None
        assert created_emails[0].body_html is None
        assert created_emails[0].snippet is None

    def test_store_emails_legacy_full_cache_persists_body(self, monkeypatch):
        """Legacy mode stays explicit for local/dev migration compatibility."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        service = SyncService()

        mock_session = MagicMock()
        mock_account = MagicMock(id=1, email="me@example.com")

        mock_email = MagicMock()
        mock_email.id = "legacy123"
        mock_email.conversation_id = "conv123"
        mock_email.subject = "Legacy subject"
        mock_email.sender = "sender@test.com"
        mock_email.sender_name = "Sender"
        mock_email.to = ["me@example.com"]
        mock_email.cc = []
        mock_email.received_at = datetime.now(timezone.utc)
        mock_email.body = "Legacy body"
        mock_email.body_html = "<p>Legacy body</p>"
        mock_email.preview = "Legacy preview"
        mock_email.is_read = False
        mock_email.attachments = []
        mock_email.has_attachments = False

        created_emails = []
        mock_session.add.side_effect = created_emails.append

        with patch("app.services.sync_service.EmailRepository") as mock_email_repo_class:
            mock_email_repo_class.return_value.get_by_email_id.return_value = None
            with patch("app.services.sync_service.ContactRepository") as mock_contact_repo_class:
                mock_contact_repo_class.return_value.get_or_create.return_value = (
                    MagicMock(id=1),
                    True,
                )

                count = service._store_emails(mock_session, mock_account, [mock_email])

        assert count == 1
        assert len(created_emails) == 1
        assert created_emails[0].body_text == "Legacy body"
        assert created_emails[0].body_html == "<p>Legacy body</p>"
        assert created_emails[0].snippet == "Legacy preview"

    def test_store_emails_sets_folder_inbox_for_non_sent(self):
        """Fix #77: inbox emails must be stored with folder='inbox' (not NULL).

        Emails stored with folder=NULL are treated as inbox by the DB query
        (folder == 'inbox' OR folder IS NULL). If Outlook later moves an email
        to JunkEmail, the app wouldn't know — it would still appear in inbox.
        Explicit folder='inbox' allows downstream cleanup to correct the folder.
        """
        service = SyncService()

        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1

        mock_email = MagicMock()
        mock_email.id = "inbox123"
        mock_email.conversation_id = "conv123"
        mock_email.subject = "Inbox email"
        mock_email.sender = "sender@example.com"
        mock_email.sender_name = "Sender"
        mock_email.to = ["me@example.com"]
        mock_email.cc = []
        mock_email.received_at = datetime.now(timezone.utc)
        mock_email.body = "Body"
        mock_email.body_html = None
        mock_email.preview = "Body..."
        mock_email.is_read = False
        mock_email.attachments = []
        mock_email.has_attachments = False

        created_emails = []

        def capture_add(email_obj):
            created_emails.append(email_obj)

        mock_session.add.side_effect = capture_add

        with patch("app.services.sync_service.EmailRepository") as mock_email_repo_class:
            mock_email_repo = MagicMock()
            mock_email_repo.get_by_email_id.return_value = None
            mock_email_repo_class.return_value = mock_email_repo

            with patch("app.services.sync_service.ContactRepository") as mock_contact_repo_class:
                mock_contact_repo = MagicMock()
                mock_contact_obj = MagicMock()
                mock_contact_obj.id = 1
                mock_contact_repo.get_or_create.return_value = (mock_contact_obj, True)
                mock_contact_repo_class.return_value = mock_contact_repo

                service._store_emails(mock_session, mock_account, [mock_email])

        assert len(created_emails) == 1
        assert created_emails[0].folder == "inbox", (
            "Inbox emails must have folder='inbox' so Outlook spam moved after sync "
            "can be corrected by the prefetch cleanup (fix #77)"
        )

    def test_store_emails_sent_keeps_null_folder(self):
        """Sent emails stored via _store_emails(is_sent=True) keep folder=None.

        Sent emails are queried via is_sent=True, not by folder, so their folder
        value doesn't matter for correctness. We avoid setting folder='sent' here
        to keep the minimal change needed for fix #77.
        """
        service = SyncService()

        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1
        # Required for the sender-vs-account guard added 2026-05-05 — sender matches
        # account.email so the row is genuinely sent and the flag survives.
        mock_account.email = "me@example.com"

        mock_email = MagicMock()
        mock_email.id = "sent123"
        mock_email.conversation_id = "conv456"
        mock_email.subject = "Sent email"
        mock_email.sender = "me@example.com"
        mock_email.sender_name = "Me"
        mock_email.to = ["them@example.com"]
        mock_email.cc = []
        mock_email.received_at = datetime.now(timezone.utc)
        mock_email.body = "Sent body"
        mock_email.body_html = None
        mock_email.preview = "Sent..."
        mock_email.is_read = True
        mock_email.attachments = []
        mock_email.has_attachments = False

        created_emails = []

        def capture_add(email_obj):
            created_emails.append(email_obj)

        mock_session.add.side_effect = capture_add

        with patch("app.services.sync_service.EmailRepository") as mock_email_repo_class:
            mock_email_repo = MagicMock()
            mock_email_repo.get_by_email_id.return_value = None
            mock_email_repo_class.return_value = mock_email_repo

            with patch("app.services.sync_service.ContactRepository") as mock_contact_repo_class:
                mock_contact_repo = MagicMock()
                mock_contact_obj = MagicMock()
                mock_contact_obj.id = 1
                mock_contact_repo.get_or_create.return_value = (mock_contact_obj, True)
                mock_contact_repo_class.return_value = mock_contact_repo

                service._store_emails(mock_session, mock_account, [mock_email], is_sent=True)

        assert len(created_emails) == 1
        assert created_emails[0].folder is None, (
            "Sent emails should keep folder=None (queried via is_sent=True)"
        )

    def test_store_emails_folder_override_tags_archived(self):
        """folder_override='archived' stamps archived rows so the onboarding
        loader can opt them in via include_archived without polluting the
        inbox list view.
        """
        service = SyncService()

        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "me@example.com"

        mock_email = MagicMock()
        mock_email.id = "arch_1"
        mock_email.conversation_id = "c"
        mock_email.subject = "archived"
        mock_email.sender = "karine@example.com"
        mock_email.sender_name = "Karine"
        mock_email.to = ["me@example.com"]
        mock_email.cc = []
        mock_email.received_at = datetime.now(timezone.utc)
        mock_email.body = "b"
        mock_email.body_html = None
        mock_email.preview = "p"
        mock_email.is_read = True
        mock_email.attachments = []
        mock_email.has_attachments = False

        created_emails = []
        mock_session.add.side_effect = lambda obj: created_emails.append(obj)

        with patch("app.services.sync_service.EmailRepository") as mock_email_repo_class:
            mock_email_repo_class.return_value.get_by_email_id.return_value = None
            with patch("app.services.sync_service.ContactRepository") as mock_contact_repo_class:
                mock_contact_repo_class.return_value.get_or_create.return_value = (MagicMock(id=1), True)
                service._store_emails(
                    mock_session, mock_account, [mock_email],
                    is_sent=False, folder_override="archived",
                )

        assert len(created_emails) == 1
        assert created_emails[0].folder == "archived", (
            "archive-backfill rows must carry folder='archived' so "
            "include_archived queries pick them up"
        )

    def test_store_emails_sent_bumps_recipients_not_sender(self):
        """Sent emails: bump sent_count for each recipient in To+CC, never the sender.

        This is the karine@gmail.com fix — before, sync only tracked the sender
        field, which for sent emails is the user's own address. Recipients of
        sent emails (people we reach out to via Gmail/Outlook/IMAP directly)
        would never have sent_count bumped, so the bidirectional filter excluded
        them even when the back-and-forth was real.
        """
        service = SyncService()

        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "me@example.com"

        mock_email = MagicMock()
        mock_email.id = "sent999"
        mock_email.conversation_id = "conv-k"
        mock_email.subject = "Re: hello"
        mock_email.sender = "me@example.com"  # user's own email
        mock_email.sender_name = "Me"
        mock_email.to = ["karine.morel@gmail.com", "Karine <karine.morel@gmail.com>"]  # dedup test
        mock_email.cc = ["cc1@example.com"]
        mock_email.received_at = datetime.now(timezone.utc)
        mock_email.body = "body"
        mock_email.body_html = None
        mock_email.preview = "body..."
        mock_email.is_read = True
        mock_email.attachments = []
        mock_email.has_attachments = False

        with patch("app.services.sync_service.EmailRepository") as mock_email_repo_class:
            mock_email_repo_class.return_value.get_by_email_id.return_value = None

            with patch("app.services.sync_service.ContactRepository") as mock_contact_repo_class:
                mock_contact_repo = MagicMock()
                mock_contact_repo.get_or_create.side_effect = lambda email, account_id, name=None: (
                    MagicMock(id=hash(email) & 0xFFFFFFFF), True
                )
                mock_contact_repo_class.return_value = mock_contact_repo

                service._store_emails(mock_session, mock_account, [mock_email], is_sent=True)

        # Sender (user's own email) must NOT be turned into a contact
        addrs_called = [
            call.kwargs.get("email") for call in mock_contact_repo.get_or_create.call_args_list
        ]
        assert "me@example.com" not in addrs_called, "sender (user's own email) must not become a contact"
        assert "karine.morel@gmail.com" in addrs_called, "To recipient must be tracked"
        assert "cc1@example.com" in addrs_called, "CC recipient must be tracked"
        # "Karine <karine.morel@gmail.com>" and "karine.morel@gmail.com" must dedup
        assert addrs_called.count("karine.morel@gmail.com") == 1, (
            "duplicate recipient entries must be deduplicated within the same email"
        )

        # Each tracked recipient gets increment_email_count(is_sent=True)
        for call in mock_contact_repo.increment_email_count.call_args_list:
            assert call.kwargs.get("is_sent") is True, (
                "recipients of sent emails must be incremented with is_sent=True"
            )


# ==============================================================================
# SyncService Concurrency Tests
# ==============================================================================


class TestSyncServiceConcurrency:
    """Tests for sync service thread safety."""

    def test_sync_lock_prevents_concurrent_sync(self):
        """Test that sync lock prevents concurrent syncs."""
        service = SyncService()

        # Simulate sync in progress. We must RELEASE `_sync_lock` before
        # calling `trigger_sync()` because the lock is a plain
        # `threading.Lock` (non-reentrant) — holding it across the call
        # deadlocks the same thread when `trigger_sync()` re-acquires it.
        with service._sync_lock:
            service._is_syncing = True

        # Another trigger should return False because `_is_syncing` is still
        # set (no one cleared it).
        result = service.trigger_sync()
        assert result is False

    @patch("app.services.sync_service.get_db_session")
    def test_sync_status_updated_atomically(self, mock_db_session):
        """Test sync status is updated correctly during sync."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_db_session.return_value = mock_session

        with patch("app.services.sync_service.AccountRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_active_accounts.return_value = []
            mock_repo_class.return_value = mock_repo

            service = SyncService()

            assert service._status.is_syncing is False

            service._perform_sync()

            # After sync, is_syncing should be False
            assert service._status.is_syncing is False
            assert service._status.last_sync_at is not None


# ==============================================================================
# Additional Coverage Tests
# ==============================================================================


class TestSyncServiceStopTimeout:
    """Tests for stop timeout scenarios."""

    def test_stop_thread_not_stopping_gracefully(self):
        """Test stop logs warning when thread does not stop gracefully."""
        service = SyncService()

        # Create a mock thread that is always alive
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        mock_thread.join = MagicMock()

        service._sync_thread = mock_thread
        service._status.is_running = True

        with patch("app.services.sync_service.logger") as mock_logger:
            service.stop(timeout=0.1)

            # Should log warning about ungraceful stop
            mock_logger.warning.assert_called_with("Sync thread did not stop gracefully")

        assert service.is_running is False


class TestSyncServicePerformSyncSkipWhenSyncing:
    """Tests for _perform_sync when already syncing."""

    def test_perform_sync_early_return_when_already_syncing(self):
        """Test _perform_sync returns early if already syncing."""
        service = SyncService()

        # Acquire lock and set syncing flag
        service._is_syncing = True

        # Track if get_db_session is called (it shouldn't be)
        with patch("app.services.sync_service.get_db_session") as mock_db:
            service._perform_sync()

            # Should not call database if already syncing
            mock_db.assert_not_called()


class TestSyncServicePerformSyncException:
    """Tests for _perform_sync exception handling."""

    @patch("app.services.sync_service.get_db_session")
    def test_perform_sync_handles_exception(self, mock_db_session):
        """Test _perform_sync handles exceptions gracefully."""
        mock_db_session.side_effect = RuntimeError("Database connection failed")

        service = SyncService()

        with patch("app.services.sync_service.logger") as mock_logger:
            service._perform_sync()

            # Should log error
            mock_logger.error.assert_called()

        # Status should still be updated
        assert service._status.is_syncing is False
        assert service._is_syncing is False


class TestSyncAccountExceptionWithCallback:
    """Tests for _sync_account exception handling with callback."""

    def test_sync_account_exception_triggers_error_callback(self):
        """Test _sync_account calls on_sync_error callback on exception."""
        error_received = []

        def on_error(account_id, error_msg):
            error_received.append((account_id, error_msg))

        service = SyncService(on_sync_error=on_error)

        mock_account = MagicMock()
        mock_account.id = 42
        mock_account.email = "test@example.com"
        mock_account.provider = "gmail"
        mock_account.last_history_id = None  # Skip delta sync path

        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = True

        with patch.object(service, "_get_adapter_for_account", return_value=mock_adapter):
            with patch.object(
                service, "_fetch_emails_with_retry", side_effect=Exception("Network error")
            ):
                result = service._sync_account(MagicMock(), mock_account)

        assert result.success is False
        assert "Network error" in result.error_message
        assert len(error_received) == 1
        assert error_received[0][0] == 42
        assert "Network error" in error_received[0][1]

    def test_sync_account_exception_callback_error_handled(self):
        """Test _sync_account handles callback error gracefully."""
        def broken_callback(account_id, error_msg):
            raise RuntimeError("Callback failed")

        service = SyncService(on_sync_error=broken_callback)

        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "test@example.com"
        mock_account.provider = "gmail"
        mock_account.last_history_id = None  # Skip delta sync path

        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = True

        with patch.object(service, "_get_adapter_for_account", return_value=mock_adapter):
            with patch.object(
                service, "_fetch_emails_with_retry", side_effect=Exception("Fetch failed")
            ):
                with patch("app.services.sync_service.logger") as mock_logger:
                    result = service._sync_account(MagicMock(), mock_account)

                    # Should log callback error
                    mock_logger.error.assert_called()

        # Should still return error result
        assert result.success is False

    def test_sync_account_auth_expired_does_not_emit_generic_error_callback(self):
        """Auth-expired provider failures should not surface as generic sync errors."""
        error_received = []

        def on_error(account_id, error_msg):
            error_received.append((account_id, error_msg))

        service = SyncService(on_sync_error=on_error)

        mock_account = MagicMock()
        mock_account.id = 42
        mock_account.email = "test@example.com"
        mock_account.provider = "gmail"
        mock_account.last_history_id = None

        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = True

        refresh_error = RuntimeError("invalid_grant: Token has been expired or revoked.")

        with patch.object(service, "_get_adapter_for_account", return_value=mock_adapter):
            with patch.object(service, "_fetch_emails_with_retry", side_effect=refresh_error):
                with patch("app.services.sync_service.logger") as mock_logger:
                    result = service._sync_account(MagicMock(), mock_account)

        assert result.success is False
        assert "invalid_grant" in result.error_message
        assert error_received == []
        mock_logger.error.assert_not_called()
        mock_logger.warning.assert_any_call(
            "Sync skipped for %s: account needs reauth (%s)",
            "test@example.com",
            refresh_error,
        )


class TestGetAdapterForAccount:
    """Tests for _get_adapter_for_account."""

    def test_get_adapter_success(self):
        """Test _get_adapter_for_account returns adapter on success."""
        service = SyncService()

        mock_account = MagicMock()
        mock_account.provider = "gmail"
        mock_account.refresh_token = "refresh_token"
        mock_account.access_token = "access_token"

        mock_adapter = MagicMock()

        with patch("app.providers.factory.get_email_provider", return_value=mock_adapter):
            adapter = service._get_adapter_for_account(mock_account)

        assert adapter is mock_adapter

    def test_get_adapter_exception_returns_none(self):
        """Test _get_adapter_for_account returns None on exception."""
        service = SyncService()

        mock_account = MagicMock()
        mock_account.provider = "invalid_provider"
        mock_account.refresh_token = None
        mock_account.access_token = None

        with patch(
            "app.providers.factory.get_email_provider",
            side_effect=ValueError("Unknown provider")
        ):
            with patch("app.services.sync_service.logger") as mock_logger:
                adapter = service._get_adapter_for_account(mock_account)

                # Provider config issues should be visible without looking like server faults.
                mock_logger.warning.assert_called()

        assert adapter is None


class TestFetchEmailsWithRetry:
    """Tests for _fetch_emails_with_retry delta sync logic."""

    def test_fetch_emails_delta_sync_with_fetch_messages_since(self):
        """Test delta sync using fetch_messages_since."""
        service = SyncService()

        mock_adapter = MagicMock()
        mock_adapter.fetch_messages_since = MagicMock(return_value=["email1", "email2"])

        since = datetime.now(timezone.utc)

        result = service._fetch_emails_with_retry(mock_adapter, since)

        mock_adapter.fetch_messages_since.assert_called_once_with(since, limit=200)
        assert result == ["email1", "email2"]

    def test_fetch_emails_delta_sync_fallback_to_get_messages(self):
        """Test delta sync falls back to get_messages when fetch_messages_since unavailable."""
        service = SyncService()

        mock_adapter = MagicMock(spec=["get_messages", "provider_name"])
        mock_adapter.provider_name = "legacy_provider"
        mock_adapter.get_messages = MagicMock(return_value=["email1"])

        since = datetime.now(timezone.utc)

        with patch("app.services.sync_service.logger") as mock_logger:
            result = service._fetch_emails_with_retry(mock_adapter, since)

            # Should log warning about fallback
            mock_logger.warning.assert_called()

        mock_adapter.get_messages.assert_called_once_with(limit=200)
        assert result == ["email1"]

    def test_fetch_emails_initial_sync(self):
        """Test initial sync (since=None) uses get_messages with initial_sync_limit."""
        service = SyncService()

        mock_adapter = MagicMock()
        mock_adapter.get_messages = MagicMock(return_value=["email1", "email2", "email3"])

        result = service._fetch_emails_with_retry(mock_adapter, None)

        from app.config import DEFAULT_CACHE_CONFIG
        mock_adapter.get_messages.assert_called_once_with(limit=DEFAULT_CACHE_CONFIG.initial_sync_limit)
        assert result == ["email1", "email2", "email3"]


class TestStoreEmailsWithNewEmailCallback:
    """Tests for _store_emails with on_new_email callback."""

    def test_store_emails_triggers_new_email_callback(self):
        """Test storing new email triggers on_new_email callback."""
        received_emails = []

        def on_new_email(email_data):
            received_emails.append(email_data)

        service = SyncService(on_new_email=on_new_email)

        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 10

        mock_email = MagicMock()
        mock_email.id = "email_123"
        mock_email.conversation_id = "conv_456"
        mock_email.subject = "Test Subject"
        mock_email.sender = "sender@example.com"
        mock_email.sender_name = "Sender Name"
        mock_email.to = ["recipient@example.com"]
        mock_email.cc = []
        mock_email.received_at = datetime.now(timezone.utc)
        mock_email.body = "Test body"
        mock_email.body_html = "<p>Test</p>"
        mock_email.preview = "Test..."
        mock_email.is_read = False
        mock_email.attachments = []
        mock_email.has_attachments = False

        with patch("app.services.sync_service.EmailRepository") as mock_email_repo_class:
            mock_email_repo = MagicMock()
            mock_email_repo.get_by_email_id.return_value = None
            mock_email_repo_class.return_value = mock_email_repo

            with patch("app.services.sync_service.ContactRepository") as mock_contact_repo_class:
                mock_contact_repo = MagicMock()
                mock_contact = MagicMock()
                mock_contact.id = 1
                mock_contact_repo.get_or_create.return_value = (mock_contact, True)
                mock_contact_repo_class.return_value = mock_contact_repo

                count = service._store_emails(mock_session, mock_account, [mock_email])

        assert count == 1
        assert len(received_emails) == 1
        assert received_emails[0]["email_id"] == "email_123"
        assert received_emails[0]["account_id"] == 10
        assert received_emails[0]["sender"] == "sender@example.com"
        assert received_emails[0]["subject"] == "Test Subject"

    def test_store_emails_callback_error_handled(self):
        """Test _store_emails handles callback error gracefully."""
        def broken_callback(email_data):
            raise RuntimeError("Callback error")

        service = SyncService(on_new_email=broken_callback)

        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1

        mock_email = MagicMock()
        mock_email.id = "email_123"
        mock_email.conversation_id = "conv_456"
        mock_email.subject = "Test"
        mock_email.sender = "sender@example.com"
        mock_email.sender_name = "Sender"
        mock_email.to = []
        mock_email.cc = []
        mock_email.received_at = datetime.now(timezone.utc)
        mock_email.body = "Body"
        mock_email.body_html = None
        mock_email.preview = "..."
        mock_email.is_read = False
        mock_email.attachments = []
        mock_email.has_attachments = False

        with patch("app.services.sync_service.EmailRepository") as mock_email_repo_class:
            mock_email_repo = MagicMock()
            mock_email_repo.get_by_email_id.return_value = None
            mock_email_repo_class.return_value = mock_email_repo

            with patch("app.services.sync_service.ContactRepository") as mock_contact_repo_class:
                mock_contact_repo = MagicMock()
                mock_contact = MagicMock()
                mock_contact.id = 1
                mock_contact_repo.get_or_create.return_value = (mock_contact, True)
                mock_contact_repo_class.return_value = mock_contact_repo

                with patch("app.services.sync_service.logger") as mock_logger:
                    count = service._store_emails(mock_session, mock_account, [mock_email])

                    # Should log callback error
                    mock_logger.error.assert_called()

        # Should still count the email
        assert count == 1


class TestEnforceCacheLimits:
    """Tests for _enforce_cache_limits."""

    def test_enforce_cache_limits_logs_cleanup(self):
        """Test _enforce_cache_limits logs when emails are deleted."""
        service = SyncService()

        mock_session = MagicMock()
        account_ids = [1, 2]

        mock_result = MagicMock()
        mock_result.account_id = 1
        mock_result.emails_deleted = 10

        mock_cache_manager = MagicMock()
        mock_cache_manager.cache_limit = 1000
        mock_cache_manager.enforce_limit_all_accounts.return_value = [mock_result]

        with patch("app.services.sync_service.get_cache_manager", return_value=mock_cache_manager):
            with patch("app.services.sync_service.logger") as mock_logger:
                service._enforce_cache_limits(mock_session, account_ids)

                # Should log cleanup info
                mock_logger.info.assert_called()
                log_message = mock_logger.info.call_args[0][0]
                assert "deleted 10 oldest emails" in log_message

    def test_enforce_cache_limits_no_cleanup_no_log(self):
        """Test _enforce_cache_limits doesn't log when no emails deleted."""
        service = SyncService()

        mock_session = MagicMock()
        account_ids = [1]

        mock_result = MagicMock()
        mock_result.account_id = 1
        mock_result.emails_deleted = 0

        mock_cache_manager = MagicMock()
        mock_cache_manager.enforce_limit_all_accounts.return_value = [mock_result]

        with patch("app.services.sync_service.get_cache_manager", return_value=mock_cache_manager):
            with patch("app.services.sync_service.logger") as mock_logger:
                service._enforce_cache_limits(mock_session, account_ids)

                # Should not log anything (no cleanup occurred)
                mock_logger.info.assert_not_called()


class TestSyncLoopBehavior:
    """Tests for the _sync_loop behavior."""

    @patch("app.services.sync_service.get_db_session")
    def test_sync_loop_updates_next_sync_at(self, mock_db_session):
        """Test _sync_loop updates next_sync_at status."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_db_session.return_value = mock_session

        with patch("app.services.sync_service.AccountRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_active_accounts.return_value = []
            mock_repo_class.return_value = mock_repo

            service = SyncService(sync_interval=0.1)

            # Start the service
            service.start()

            # Wait for initial sync and one loop iteration
            time.sleep(0.3)

            # Stop the service
            service.stop(timeout=1.0)

        # next_sync_at should have been set
        assert service._status.next_sync_at is not None


class TestStoreEmailsWithNullValues:
    """Tests for _store_emails with null/empty values."""

    def test_store_emails_with_no_sender(self):
        """Test storing email with no sender doesn't update contact."""
        service = SyncService()

        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.id = 1

        mock_email = MagicMock()
        mock_email.id = "email_123"
        mock_email.conversation_id = "conv_456"
        mock_email.subject = "Test"
        mock_email.sender = None  # No sender
        mock_email.sender_name = None
        mock_email.to = []
        mock_email.cc = None
        mock_email.received_at = None
        mock_email.body = "Body"
        mock_email.body_html = None
        mock_email.preview = None
        mock_email.is_read = True
        mock_email.attachments = []
        mock_email.has_attachments = False

        with patch("app.services.sync_service.EmailRepository") as mock_email_repo_class:
            mock_email_repo = MagicMock()
            mock_email_repo.get_by_email_id.return_value = None
            mock_email_repo_class.return_value = mock_email_repo

            with patch("app.services.sync_service.ContactRepository") as mock_contact_repo_class:
                mock_contact_repo = MagicMock()
                mock_contact = MagicMock()
                mock_contact.id = 1
                mock_contact_repo.get_or_create.return_value = (mock_contact, True)
                mock_contact_repo_class.return_value = mock_contact_repo

                count = service._store_emails(mock_session, mock_account, [mock_email])

        assert count == 1
        # Contact should not be updated since no sender
        mock_contact_repo.increment_email_count.assert_not_called()


class TestInboxBackfill:
    """`_maybe_inbox_backfill` repairs accounts whose delta checkpoint
    missed a chunk of pre-install inbox history — the karine@ case where
    a real incoming email sits in Gmail but never lands in the DB, keeping
    received_count at 0 and hiding the contact from the bidirectional list."""

    def _account(self, settings_json=None):
        acc = MagicMock()
        acc.id = 42
        acc.email = "me@example.com"
        acc.settings_json = settings_json
        return acc

    def test_skips_when_marker_present(self):
        service = SyncService()
        acc = self._account('{"inbox_backfilled_at": "2026-04-24T00:00:00"}')
        adapter = MagicMock()
        with patch("app.services.sync_service.time.sleep"):
            stored = service._maybe_inbox_backfill(MagicMock(), adapter, acc)
        assert stored == 0
        adapter.get_inbox_backfill.assert_not_called()

    def test_skips_when_adapter_lacks_method(self):
        service = SyncService()
        acc = self._account()
        # Adapter without get_inbox_backfill (e.g. IMAP)
        adapter = object()
        stored = service._maybe_inbox_backfill(MagicMock(), adapter, acc)
        assert stored == 0

    def test_stores_fetched_messages_and_stamps_marker(self):
        service = SyncService()
        acc = self._account()
        adapter = MagicMock()
        fake_msgs = [MagicMock(), MagicMock()]
        adapter.get_inbox_backfill.return_value = fake_msgs

        with patch("app.services.sync_service.time.sleep"), \
             patch.object(service, "_store_emails", return_value=2) as mock_store:
            stored = service._maybe_inbox_backfill(MagicMock(), adapter, acc)

        assert stored == 2
        adapter.get_inbox_backfill.assert_called_once_with(limit=1000)
        _, kwargs = mock_store.call_args
        assert kwargs["is_sent"] is False
        assert kwargs["folder_override"] == "inbox"
        assert _get_account_setting(acc, "inbox_backfilled_at") is not None

    def test_fetch_failure_leaves_marker_unset_for_retry(self):
        service = SyncService()
        acc = self._account()
        adapter = MagicMock()
        adapter.get_inbox_backfill.side_effect = RuntimeError("rate limit")
        with patch("app.services.sync_service.time.sleep"):
            stored = service._maybe_inbox_backfill(MagicMock(), adapter, acc)
        assert stored == 0
        assert _get_account_setting(acc, "inbox_backfilled_at") is None

    def test_store_failure_leaves_marker_unset_for_retry(self):
        service = SyncService()
        acc = self._account()
        adapter = MagicMock()
        adapter.get_inbox_backfill.return_value = [MagicMock()]
        with patch("app.services.sync_service.time.sleep"), \
             patch.object(service, "_store_emails", side_effect=RuntimeError("db locked")):
            stored = service._maybe_inbox_backfill(MagicMock(), adapter, acc)
        assert stored == 0
        assert _get_account_setting(acc, "inbox_backfilled_at") is None


class TestSentBackfill:
    """`_maybe_sent_backfill` repairs accounts whose pre-install Sent history
    never reached the local Email table. Without it, every recipient the user
    replied to via Gmail Web / mobile / IMAP before installing Agentys stays at
    `sent_count = 0` and disappears from the bidirectional contacts list — the
    `aubert@creation.example` regression documented in lessons.md
    (2026-05-04).

    Mirror of TestInboxBackfill: same idempotence contract, same failure-leaves-
    marker-unset semantics. The two diverge only in which adapter method is
    called and which `is_sent` / `folder_override` is forwarded to
    `_store_emails`.
    """

    def _account(self, settings_json=None):
        acc = MagicMock()
        acc.id = 42
        acc.email = "me@example.com"
        acc.settings_json = settings_json
        return acc

    def test_skips_when_marker_present(self):
        service = SyncService()
        acc = self._account('{"sent_backfilled_at": "2026-05-04T00:00:00"}')
        adapter = MagicMock()
        with patch("app.services.sync_service.time.sleep"):
            stored = service._maybe_sent_backfill(MagicMock(), adapter, acc)
        assert stored == 0
        adapter.get_sent_backfill.assert_not_called()

    def test_skips_when_adapter_lacks_method(self):
        service = SyncService()
        acc = self._account()
        # Adapter without get_sent_backfill (e.g. legacy IMAP / Outlook pre-impl)
        adapter = object()
        stored = service._maybe_sent_backfill(MagicMock(), adapter, acc)
        assert stored == 0

    def test_stores_fetched_messages_with_sent_flag_and_stamps_marker(self):
        service = SyncService()
        acc = self._account()
        adapter = MagicMock()
        fake_msgs = [MagicMock(), MagicMock()]
        adapter.get_sent_backfill.return_value = fake_msgs

        with patch("app.services.sync_service.time.sleep"), \
             patch.object(service, "_store_emails", return_value=2) as mock_store:
            stored = service._maybe_sent_backfill(MagicMock(), adapter, acc)

        assert stored == 2
        adapter.get_sent_backfill.assert_called_once_with(limit=1000)
        _, kwargs = mock_store.call_args
        assert kwargs["is_sent"] is True, (
            "sent backfill must mark rows as is_sent=True so the contact bump "
            "lands on each recipient (To+CC), not the user's own address"
        )
        assert kwargs["folder_override"] == "sent"
        assert _get_account_setting(acc, "sent_backfilled_at") is not None

    def test_fetch_failure_leaves_marker_unset_for_retry(self):
        service = SyncService()
        acc = self._account()
        adapter = MagicMock()
        adapter.get_sent_backfill.side_effect = RuntimeError("rate limit")
        with patch("app.services.sync_service.time.sleep"):
            stored = service._maybe_sent_backfill(MagicMock(), adapter, acc)
        assert stored == 0
        assert _get_account_setting(acc, "sent_backfilled_at") is None

    def test_store_failure_leaves_marker_unset_for_retry(self):
        service = SyncService()
        acc = self._account()
        adapter = MagicMock()
        adapter.get_sent_backfill.return_value = [MagicMock()]
        with patch("app.services.sync_service.time.sleep"), \
             patch.object(service, "_store_emails", side_effect=RuntimeError("db locked")):
            stored = service._maybe_sent_backfill(MagicMock(), adapter, acc)
        assert stored == 0
        assert _get_account_setting(acc, "sent_backfilled_at") is None

    def test_skips_while_provider_low_priority_backoff_active(self):
        service = SyncService()
        acc = self._account()

        class Adapter:
            def __init__(self):
                self.get_sent_backfill = MagicMock()

            def low_priority_quota_retry_after_seconds(self):
                return 42

        adapter = Adapter()
        stored = service._maybe_sent_backfill(MagicMock(), adapter, acc)

        assert stored == 0
        adapter.get_sent_backfill.assert_not_called()
        assert _get_account_setting(acc, "sent_backfilled_at") is None

    def test_partial_quota_backfill_stores_but_leaves_marker_unset(self):
        service = SyncService()
        acc = self._account()
        fake_msgs = [MagicMock()]

        class Adapter:
            def __init__(self):
                self.retry_after = 0

            def low_priority_quota_retry_after_seconds(self):
                return self.retry_after

            def get_sent_backfill(self, limit):
                self.retry_after = 60
                return fake_msgs

        adapter = Adapter()
        with patch("app.services.sync_service.time.sleep"), \
             patch.object(service, "_store_emails", return_value=1):
            stored = service._maybe_sent_backfill(MagicMock(), adapter, acc)

        assert stored == 1
        assert _get_account_setting(acc, "sent_backfilled_at") is None


class TestDeltaPullSent:
    """`_delta_pull_sent` is the per-tick belt-and-braces SENT pull added to
    the Gmail historyId branch — Gmail's history API does not reliably surface
    every SENT label addition, so we explicitly fetch a small recent SENT
    sample periodically. Idempotent via `_store_emails`'s `get_by_email_id`
    dedup.
    """

    def _account(self):
        acc = MagicMock()
        acc.id = 42
        acc.email = "me@example.com"
        return acc

    def test_returns_zero_when_adapter_lacks_method(self):
        service = SyncService()
        acc = self._account()
        # Plain object → no get_sent_emails
        adapter = object()
        assert service._delta_pull_sent(MagicMock(), acc, adapter) == 0

    def test_skips_while_provider_low_priority_backoff_active(self):
        service = SyncService()
        acc = self._account()

        class Adapter:
            def __init__(self):
                self.get_sent_emails = MagicMock()

            def low_priority_quota_retry_after_seconds(self):
                return 37

        adapter = Adapter()
        count = service._delta_pull_sent(MagicMock(), acc, adapter)

        assert count == 0
        adapter.get_sent_emails.assert_not_called()
        assert _get_account_setting(acc, "sent_delta_pulled_at") is None

    def test_returns_zero_when_no_sent_messages(self):
        service = SyncService()
        acc = self._account()
        adapter = MagicMock()
        adapter.get_sent_emails.return_value = []
        with patch.object(service, "_store_emails") as mock_store:
            count = service._delta_pull_sent(MagicMock(), acc, adapter)
        assert count == 0
        mock_store.assert_not_called()
        adapter.get_sent_emails.assert_called_once_with(limit=25)
        assert _get_account_setting(acc, "sent_delta_pulled_at") is not None

    def test_skips_when_recently_checked(self):
        service = SyncService()
        acc = self._account()
        _set_account_setting(
            acc,
            "sent_delta_pulled_at",
            datetime.now(timezone.utc).isoformat(),
        )
        adapter = MagicMock()

        count = service._delta_pull_sent(MagicMock(), acc, adapter)

        assert count == 0
        adapter.get_sent_emails.assert_not_called()

    def test_stores_with_sent_flag_and_folder_override(self):
        service = SyncService()
        acc = self._account()
        adapter = MagicMock()
        fake = [MagicMock(), MagicMock()]
        adapter.get_sent_emails.return_value = fake

        with patch.object(service, "_store_emails", return_value=2) as mock_store:
            count = service._delta_pull_sent(MagicMock(), acc, adapter)

        assert count == 2
        adapter.get_sent_emails.assert_called_once_with(limit=25)
        _, kwargs = mock_store.call_args
        assert kwargs["is_sent"] is True
        assert kwargs["folder_override"] == "sent"

    def test_quota_backoff_after_delta_pull_does_not_mark_fresh(self):
        service = SyncService()
        acc = self._account()
        fake = [MagicMock()]

        class Adapter:
            def __init__(self):
                self.retry_after = 0

            def low_priority_quota_retry_after_seconds(self):
                return self.retry_after

            def get_sent_emails(self, limit):
                self.retry_after = 45
                return fake

        adapter = Adapter()
        with patch.object(service, "_store_emails", return_value=1):
            count = service._delta_pull_sent(MagicMock(), acc, adapter)

        assert count == 1
        assert _get_account_setting(acc, "sent_delta_pulled_at") is None


class TestStoreEmailsSenderGuard:
    """Defense-in-depth: when a caller passes ``is_sent=True`` (e.g.
    ``_delta_pull_sent`` after a Gmail SENT-label query, or
    ``_maybe_sent_backfill`` after a paginated SENT pull), the resulting Email
    row is queried as Sent forever after — `get_sent_emails` filters by
    ``is_sent == True`` and the inbox query explicitly excludes those rows.

    Provider folder/label queries can leak received messages into the SENT
    bucket in practice:
    - Gmail: SMTP relays / mailing-list bounces / BCC-self rules can attach
      the SENT label to messages that arrived via INBOX.
    - IMAP: server-side rules (Outlook desktop "Save replies in same folder",
      shared mailboxes, BCC-to-self) can move/copy received messages into
      the user's Sent folder.
    - Outlook: `mail_folders/sentitems` is determined by the Exchange store,
      which is influenced by client-side rules.

    The leak symptom Carol's friend reported (2026-05-05): she sent an email
    to Rachel via Agentys, Rachel replied, and Rachel's reply showed up in
    the Sent tab instead of the Inbox tab. Behaviorally this happens any
    time a received email transits a code path that forces ``is_sent=True``
    without checking the sender.

    Source of truth for "sent": *the user actually sent this message*.
    Authoritative signal: ``email.sender == account.email``. The provider
    folder/label is a hint; the sender header is the contract. So when the
    two disagree, trust the sender — store the row as received (is_sent=False,
    folder='inbox') and let it appear in the inbox where the user expects it.
    """

    def _make_account(self, email: str = "carol@gmail.com"):
        acc = MagicMock()
        acc.id = 7
        acc.email = email
        return acc

    def _make_email(self, *, msg_id: str, sender: str, to: list[str]):
        e = MagicMock()
        e.id = msg_id
        e.conversation_id = "T123"  # same thread as Carol's prior message
        e.subject = "Re: lunch?"
        e.sender = sender
        e.sender_name = sender.split("@")[0]
        e.to = to
        e.cc = []
        e.received_at = datetime.now(timezone.utc)
        e.body = "Sounds good!"
        e.body_html = None
        e.preview = "Sounds good!"
        e.is_read = False
        e.attachments = []
        e.has_attachments = False
        return e

    def test_received_email_with_is_sent_true_is_downgraded(self):
        """Carol sent to Rachel; Rachel replied. If `_delta_pull_sent` (or any
        SENT-folder-scoped fetch) hands Rachel's reply to ``_store_emails`` with
        ``is_sent=True``, the resulting row must NOT be flagged sent.

        Pre-fix this test fails: the row is created with ``is_sent=True`` and
        ``folder='sent'``, hiding Rachel's reply from Carol's inbox.
        """
        service = SyncService()
        account = self._make_account(email="carol@gmail.com")

        # Rachel's reply: sender=rachel, recipient=carol. Caller misclaims is_sent=True
        # (e.g. provider returned this row from a SENT-label query that picked it
        # up via SMTP-relay label propagation, IMAP shared-mailbox rules, etc.)
        rachel_reply = self._make_email(
            msg_id="rachel-reply-id",
            sender="rachel@example.com",
            to=["carol@gmail.com"],
        )

        created = []
        mock_session = MagicMock()
        mock_session.add.side_effect = lambda obj: created.append(obj)

        with patch("app.services.sync_service.EmailRepository") as repo_cls:
            repo_cls.return_value.get_by_email_id.return_value = None
            with patch("app.services.sync_service.ContactRepository") as contact_cls:
                contact_cls.return_value.get_or_create.return_value = (
                    MagicMock(id=99), True,
                )
                service._store_emails(
                    mock_session, account, [rachel_reply],
                    is_sent=True, folder_override="sent",
                )

        assert len(created) == 1
        row = created[0]
        assert row.is_sent is False, (
            "received email (sender != account.email) must NOT be stored as sent "
            "even when the caller forced is_sent=True — provider folder/label "
            "leaks would otherwise hide the reply from the inbox view"
        )
        assert row.folder == "inbox", (
            "downgraded received email must land in the inbox folder so the user "
            "actually sees it where they expect"
        )

    def test_genuine_sent_email_keeps_sent_flag(self):
        """The guard only rewrites mismatches — when sender == account.email
        the email is genuinely sent and the flag must survive untouched.
        """
        service = SyncService()
        account = self._make_account(email="carol@gmail.com")

        carol_sent = self._make_email(
            msg_id="carol-sent-id",
            sender="carol@gmail.com",
            to=["rachel@example.com"],
        )

        created = []
        mock_session = MagicMock()
        mock_session.add.side_effect = lambda obj: created.append(obj)

        with patch("app.services.sync_service.EmailRepository") as repo_cls:
            repo_cls.return_value.get_by_email_id.return_value = None
            with patch("app.services.sync_service.ContactRepository") as contact_cls:
                contact_cls.return_value.get_or_create.return_value = (
                    MagicMock(id=99), True,
                )
                service._store_emails(
                    mock_session, account, [carol_sent],
                    is_sent=True, folder_override="sent",
                )

        assert len(created) == 1
        row = created[0]
        assert row.is_sent is True
        assert row.folder == "sent"

    def test_sender_normalization_handles_display_name_form(self):
        """Provider mappers sometimes leave the sender as ``"Name <addr>"``
        rather than the bare address. The guard must extract the address
        before comparing — otherwise every genuine sent email with a display
        name would be incorrectly downgraded.
        """
        service = SyncService()
        account = self._make_account(email="carol@gmail.com")

        carol_sent = self._make_email(
            msg_id="carol-sent-with-name",
            sender="Carol <carol@gmail.com>",
            to=["rachel@example.com"],
        )

        created = []
        mock_session = MagicMock()
        mock_session.add.side_effect = lambda obj: created.append(obj)

        with patch("app.services.sync_service.EmailRepository") as repo_cls:
            repo_cls.return_value.get_by_email_id.return_value = None
            with patch("app.services.sync_service.ContactRepository") as contact_cls:
                contact_cls.return_value.get_or_create.return_value = (
                    MagicMock(id=99), True,
                )
                service._store_emails(
                    mock_session, account, [carol_sent],
                    is_sent=True, folder_override="sent",
                )

        assert created[0].is_sent is True

    def test_received_email_with_is_sent_false_passes_through(self):
        """Sanity: the guard only fires when is_sent=True is being claimed.
        Normal inbox path (is_sent defaults to False) is unaffected.
        """
        service = SyncService()
        account = self._make_account(email="carol@gmail.com")

        rachel_reply = self._make_email(
            msg_id="rachel-reply-inbox",
            sender="rachel@example.com",
            to=["carol@gmail.com"],
        )

        created = []
        mock_session = MagicMock()
        mock_session.add.side_effect = lambda obj: created.append(obj)

        with patch("app.services.sync_service.EmailRepository") as repo_cls:
            repo_cls.return_value.get_by_email_id.return_value = None
            with patch("app.services.sync_service.ContactRepository") as contact_cls:
                contact_cls.return_value.get_or_create.return_value = (
                    MagicMock(id=99), True,
                )
                service._store_emails(mock_session, account, [rachel_reply])

        assert created[0].is_sent is False
        assert created[0].folder == "inbox"

    def test_downgraded_email_bumps_received_count_not_sent(self):
        """When the guard rewrites is_sent=True → False, contact bookkeeping
        must follow: bump the SENDER's received_count (the inbox path), not
        the recipients' sent_count (the sent path). Otherwise the contact
        list ends up with phantom outgoing-only relationships.
        """
        service = SyncService()
        account = self._make_account(email="carol@gmail.com")

        rachel_reply = self._make_email(
            msg_id="rachel-bookkeeping",
            sender="rachel@example.com",
            to=["carol@gmail.com"],
        )

        mock_session = MagicMock()

        with patch("app.services.sync_service.EmailRepository") as repo_cls:
            repo_cls.return_value.get_by_email_id.return_value = None
            with patch("app.services.sync_service.ContactRepository") as contact_cls:
                contact_repo = MagicMock()
                contact_repo.get_or_create.return_value = (MagicMock(id=99), True)
                contact_cls.return_value = contact_repo

                service._store_emails(
                    mock_session, account, [rachel_reply],
                    is_sent=True, folder_override="sent",
                )

        # The sender (Rachel) must be tracked, not the recipient (Carol)
        addrs_created = [
            c.kwargs.get("email") for c in contact_repo.get_or_create.call_args_list
        ]
        assert "rachel@example.com" in addrs_created, (
            "downgraded received email must register Rachel as a contact "
            "(she's the actual sender once the guard reclassifies)"
        )
        assert "carol@gmail.com" not in addrs_created, (
            "user's own email must never become a contact"
        )

        # increment_email_count must be called with is_sent=False (received)
        for call in contact_repo.increment_email_count.call_args_list:
            assert call.kwargs.get("is_sent") is False, (
                "downgraded email contact bump must use is_sent=False to bump "
                "received_count, not sent_count"
            )


class TestStoreEmailsSenderGuardE2E:
    """End-to-end verification with a real SQLite session.

    The unit tests above rely on MagicMocks for the repositories — they verify
    the guard's branching, but they don't exercise the actual SQL queries
    that determine whether the user sees the email in Inbox or Sent. This
    class hits the real ``EmailRepository`` against an in-memory SQLite to
    prove the bug really is fixed at the user-visible layer:

    - ``get_sent_emails(account_id)`` (Sent tab): must NOT return Rachel's reply
    - ``get_by_account(account_id)``  (Inbox tab): MUST return Rachel's reply

    The fixtures ``session`` and ``sample_account`` are exposed globally via
    ``conftest.py`` -> ``pytest_plugins = ["tests.db._fixtures"]``.
    """

    def _std_email(self, *, msg_id: str, sender: str, to: list[str], thread_id: str = "T123"):
        e = MagicMock()
        e.id = msg_id
        e.conversation_id = thread_id
        e.subject = "Re: lunch?"
        e.sender = sender
        e.sender_name = sender.split("@")[0].title()
        e.to = to
        e.cc = []
        e.received_at = datetime.now(timezone.utc)
        e.body = "Sounds good!"
        e.body_html = None
        e.preview = "Sounds good!"
        e.is_read = False
        e.attachments = []
        e.has_attachments = False
        return e

    def test_carol_rachel_endtoend_inbox_sent_separation(self, session, sample_account):
        """The full Carol/Rachel scenario, queried via the same SQL paths the
        backend uses to populate the Sent and Inbox tabs.

        Setup: account is ``test@example.com`` (the fixture default). We feed
        ``_store_emails`` two messages with ``is_sent=True`` (as if the
        provider's SENT-bucket query handed them both to ``_delta_pull_sent``):
        - Carol's actual sent message — sender matches the account
        - Rachel's reply — sender does NOT match the account (this is the leak)

        Pre-fix behaviour: both rows land with ``is_sent=True`` and Rachel's
        reply disappears from the Inbox.

        Post-fix behaviour: the sender guard downgrades Rachel's reply to
        ``is_sent=False, folder='inbox'``, so it shows up where the user
        expects it.
        """
        # sample_account.email == "test@example.com" — Carol is "test"
        carol_email = sample_account.email

        carol_sent = self._std_email(
            msg_id="carol-real-gmail-id",
            sender=carol_email,                   # Carol sent it
            to=["rachel@example.com"],
        )
        rachel_reply = self._std_email(
            msg_id="rachel-real-gmail-id",
            sender="rachel@example.com",          # Rachel sent it
            to=[carol_email],
        )

        service = SyncService()
        # Both rows arrive via the SENT-bucket path with is_sent=True forced —
        # exactly what _delta_pull_sent / _maybe_sent_backfill do per tick.
        stored = service._store_emails(
            session, sample_account, [carol_sent, rachel_reply],
            is_sent=True, folder_override="sent",
        )
        session.commit()

        assert stored == 2, "both rows must persist (the guard reclassifies, doesn't drop)"

        # Now query through the EXACT repositories that serve the API endpoints.
        repo = EmailRepository(session)

        sent_rows = list(repo.get_sent_emails(account_id=sample_account.id))
        sent_ids = {r.email_id for r in sent_rows}
        inbox_rows = list(repo.get_by_account(account_id=sample_account.id))
        inbox_ids = {r.email_id for r in inbox_rows}

        assert "carol-real-gmail-id" in sent_ids, (
            "Carol's real sent email must surface in the Sent tab"
        )
        assert "rachel-real-gmail-id" not in sent_ids, (
            "REGRESSION: Rachel's reply must NOT appear in the Sent tab — "
            "this is exactly the bug Carol's friend reported"
        )

        assert "rachel-real-gmail-id" in inbox_ids, (
            "Rachel's reply must surface in the Inbox tab where the user expects it"
        )
        assert "carol-real-gmail-id" not in inbox_ids, (
            "Carol's own sent email must NOT bleed into the Inbox tab"
        )

        # Spot-check the row attributes set by the guard
        rachel_row = next(r for r in inbox_rows if r.email_id == "rachel-real-gmail-id")
        assert rachel_row.is_sent is False
        assert rachel_row.folder == "inbox"
        assert rachel_row.sender == "rachel@example.com"

        carol_row = next(r for r in sent_rows if r.email_id == "carol-real-gmail-id")
        assert carol_row.is_sent is True
        assert carol_row.folder == "sent"

    def test_purely_received_via_delta_history_lands_in_inbox(self, session, sample_account):
        """Sanity: the normal delta-history path (Rachel's reply arriving with
        the inbox-default ``is_sent=False``) still works. The guard is only
        about catching mis-claimed ``is_sent=True``.
        """
        rachel_reply = self._std_email(
            msg_id="rachel-via-history",
            sender="rachel@example.com",
            to=[sample_account.email],
        )

        service = SyncService()
        service._store_emails(session, sample_account, [rachel_reply])
        session.commit()

        repo = EmailRepository(session)
        inbox_rows = list(repo.get_by_account(account_id=sample_account.id))
        sent_rows = list(repo.get_sent_emails(account_id=sample_account.id))

        assert {r.email_id for r in inbox_rows} == {"rachel-via-history"}
        assert sent_rows == []


class TestDeltaLabelReadStatusSync:
    """Gmail history label changes must keep the local unread state fresh."""

    def _seed_email(self, session, sample_account, *, email_id: str, is_read: bool):
        row = Email(
            email_id=email_id,
            account_id=sample_account.id,
            thread_id=f"thread-{email_id}",
            subject="Label sync regression",
            sender="sender@example.com",
            sender_name="Sender",
            recipients=sample_account.email,
            date=datetime.now(timezone.utc),
            body_text="Hello",
            snippet="Hello",
            is_read=is_read,
            is_sent=False,
            folder="inbox",
        )
        session.add(row)
        session.commit()
        return row

    def _run_delta_sync(self, session, sample_account, label_change):
        sample_account.last_history_id = "hist-old"
        sample_account.last_sync_at = datetime.now(timezone.utc)
        session.flush()

        adapter = MagicMock()
        adapter.authenticate.return_value = True
        adapter.get_history_changes.return_value = {
            "added": [],
            "deleted": [],
            "label_changes": [label_change],
            "new_history_id": "hist-new",
        }

        service = SyncService()
        with (
            patch.object(service, "_get_adapter_for_account", return_value=adapter),
            patch.object(service, "_maybe_archive_backfill", return_value=None),
            patch.object(service, "_maybe_inbox_backfill", return_value=None),
            patch.object(service, "_maybe_sent_backfill", return_value=None),
            patch.object(service, "_delta_pull_sent", return_value=0),
        ):
            result = service._sync_account(session, sample_account)

        assert result.success is True
        assert sample_account.last_history_id == "hist-new"

    def test_removed_unread_label_marks_existing_gmail_email_read(
        self, session, sample_account,
    ):
        row = self._seed_email(
            session, sample_account,
            email_id="gmail-read-marker",
            is_read=False,
        )

        # GmailAdapter historically emitted "id", not "message_id". This is
        # the delta event produced when the user reads the email in Gmail.
        self._run_delta_sync(
            session, sample_account,
            {"id": "gmail-read-marker", "removed": ["UNREAD"]},
        )

        session.expire(row)
        assert row.is_read is True

    def test_added_unread_label_marks_existing_gmail_email_unread(
        self, session, sample_account,
    ):
        row = self._seed_email(
            session, sample_account,
            email_id="gmail-unread-marker",
            is_read=True,
        )

        self._run_delta_sync(
            session, sample_account,
            {"message_id": "gmail-unread-marker", "added": ["UNREAD"]},
        )

        session.expire(row)
        assert row.is_read is False


class TestStoreEmailsAutoReplyDispatch:
    """GH#622 — ``_store_emails`` must fire the OOO auto-reply for newly
    stored inbox emails when the caller passes ``auto_reply_adapter``.

    The auto-reply service was previously only reachable from the legacy
    ``daemon.process_email`` path. Gmail OAuth users route through
    ``sync_service._store_emails`` and never received an auto-reply.
    These tests pin the new wiring so a future refactor can't silently
    regress it again.
    """

    def _setup_email(self) -> MagicMock:
        email = MagicMock()
        email.id = "incoming-1"
        email.conversation_id = "conv-1"
        email.subject = "Quick question"
        email.sender = "external@example.com"
        email.sender_name = "External"
        email.to = ["me@example.com"]
        email.cc = []
        email.received_at = datetime.now(timezone.utc)
        email.body = "Hello, can you confirm?"
        email.body_html = None
        email.preview = "Hello..."
        email.is_read = False
        email.attachments = []
        email.has_attachments = False
        return email

    def _patch_repos(self):
        """Returns context managers for the repo mocks used by every test
        in this class. Returns (email_repo_patch, contact_repo_patch).
        """
        email_repo = MagicMock()
        email_repo.get_by_email_id.return_value = None
        contact = MagicMock()
        contact.id = 1
        contact_repo = MagicMock()
        contact_repo.get_or_create.return_value = (contact, True)
        return email_repo, contact_repo

    def test_fires_auto_reply_when_adapter_passed(self):
        """The contract: pass adapter → service is invoked for the new email.

        Audit F-06 (2026-05-16): dispatch is now deferred to the
        after_commit hook (jobs queued on ``session.info["_deferred_auto_replies"]``).
        The test simulates the commit by draining the list manually.
        """
        from app.services import auto_reply as auto_reply_mod

        auto_reply_mod.reset_replied_senders()

        service = SyncService()
        session = MagicMock()
        session.info = {}  # real dict so setdefault/append works
        account = MagicMock()
        account.id = 42
        account.email = "me@example.com"

        email = self._setup_email()
        email_repo, contact_repo = self._patch_repos()

        adapter = MagicMock()

        with patch(
            "app.services.sync_service.EmailRepository", return_value=email_repo
        ), patch(
            "app.services.sync_service.ContactRepository", return_value=contact_repo
        ), patch(
            "app.services.auto_reply.send_auto_reply_if_needed",
            return_value=True,
        ) as mock_send:
            service._store_emails(
                session, account, [email], auto_reply_adapter=adapter
            )
            # Simulate after_commit: drain the deferred dispatches
            for job in session.info.get("_deferred_auto_replies", []):
                job()

        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        assert kwargs["provider"] is adapter
        assert kwargs["account_id"] == 42
        assert kwargs["email"] is email
        assert kwargs["is_auto_reply"] is False

    def test_skips_auto_reply_when_no_adapter(self):
        """The contract: no adapter → no auto-reply dispatch (backfill path)."""
        service = SyncService()
        session = MagicMock()
        account = MagicMock()
        account.id = 42
        account.email = "me@example.com"

        email = self._setup_email()
        email_repo, contact_repo = self._patch_repos()

        with patch(
            "app.services.sync_service.EmailRepository", return_value=email_repo
        ), patch(
            "app.services.sync_service.ContactRepository", return_value=contact_repo
        ), patch(
            "app.services.auto_reply.send_auto_reply_if_needed"
        ) as mock_send:
            service._store_emails(session, account, [email])

        mock_send.assert_not_called()

    def test_does_not_fire_for_sent_emails(self):
        """Even with adapter, an outgoing email must never trigger auto-reply."""
        service = SyncService()
        session = MagicMock()
        account = MagicMock()
        account.id = 42
        account.email = "me@example.com"

        sent_email = self._setup_email()
        # Sender matches the account → passes the sender-vs-account guard
        # and stays is_sent=True.
        sent_email.sender = "me@example.com"
        sent_email.to = ["recipient@example.com"]

        email_repo, contact_repo = self._patch_repos()
        adapter = MagicMock()

        with patch(
            "app.services.sync_service.EmailRepository", return_value=email_repo
        ), patch(
            "app.services.sync_service.ContactRepository", return_value=contact_repo
        ), patch(
            "app.services.auto_reply.send_auto_reply_if_needed"
        ) as mock_send:
            service._store_emails(
                session, account, [sent_email],
                is_sent=True, folder_override="sent",
                auto_reply_adapter=adapter,
            )

        mock_send.assert_not_called()

    def test_skips_auto_reply_for_existing_email(self):
        """If the email already exists, we don't re-fire the auto-reply on
        every delta tick (the row hits the ``if existing: continue`` branch
        before the dispatch).
        """
        service = SyncService()
        session = MagicMock()
        account = MagicMock()
        account.id = 42
        account.email = "me@example.com"

        email = self._setup_email()
        email_repo = MagicMock()
        email_repo.get_by_email_id.return_value = MagicMock()  # already stored
        contact = MagicMock()
        contact.id = 1
        contact_repo = MagicMock()
        contact_repo.get_or_create.return_value = (contact, True)

        adapter = MagicMock()
        with patch(
            "app.services.sync_service.EmailRepository", return_value=email_repo
        ), patch(
            "app.services.sync_service.ContactRepository", return_value=contact_repo
        ), patch(
            "app.services.auto_reply.send_auto_reply_if_needed"
        ) as mock_send:
            service._store_emails(
                session, account, [email], auto_reply_adapter=adapter
            )

        mock_send.assert_not_called()

    def test_detects_auto_reply_body_and_forwards_flag(self):
        """An incoming OOO email must reach the service with
        ``is_auto_reply=True`` so the service can short-circuit and avoid
        the auto-reply loop. We verify the cleaner-derived flag is forwarded.
        """
        service = SyncService()
        session = MagicMock()
        session.info = {}  # F-06: deferred dispatch container
        account = MagicMock()
        account.id = 42
        account.email = "me@example.com"

        email = self._setup_email()
        email.body = "I am currently out of the office and will return on Monday."

        email_repo, contact_repo = self._patch_repos()
        adapter = MagicMock()

        with patch(
            "app.services.sync_service.EmailRepository", return_value=email_repo
        ), patch(
            "app.services.sync_service.ContactRepository", return_value=contact_repo
        ), patch(
            "app.services.auto_reply.send_auto_reply_if_needed"
        ) as mock_send:
            service._store_emails(
                session, account, [email], auto_reply_adapter=adapter
            )
            # F-06: simulate after_commit
            for job in session.info.get("_deferred_auto_replies", []):
                job()

        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["is_auto_reply"] is True

    def test_auto_reply_exception_does_not_block_sync(self):
        """A provider hiccup inside the auto-reply must not abort
        ``_store_emails`` — sync continuity is more important than a
        single missed OOO reply.
        """
        service = SyncService()
        session = MagicMock()
        account = MagicMock()
        account.id = 42
        account.email = "me@example.com"

        email = self._setup_email()
        email_repo, contact_repo = self._patch_repos()

        adapter = MagicMock()

        with patch(
            "app.services.sync_service.EmailRepository", return_value=email_repo
        ), patch(
            "app.services.sync_service.ContactRepository", return_value=contact_repo
        ), patch(
            "app.services.auto_reply.send_auto_reply_if_needed",
            side_effect=RuntimeError("provider down"),
        ):
            # Must not raise — the email row is still inserted.
            count = service._store_emails(
                session, account, [email], auto_reply_adapter=adapter
            )

        assert count == 1

    def test_own_emails_uses_unscoped_active_accounts(self):
        """Cross-account skip must use ``get_active_accounts()`` (un-scoped),
        NOT ``get_active_accounts_for_user(account.user_id)``.

        Why: in a Tauri install each OAuth flow mints a distinct ``user_id``,
        so 7 accounts owned by 1 human have 7 different user_ids. Scoping
        by ``account.user_id`` returns only this one account → the
        cross-account loop guard collapses to a self-send guard → Hotmail
        auto-replies to Gmail (and vice-versa) even though both inboxes
        are in the same Agentys install. Verified live in prod on
        2026-05-12 at 12:09:20.
        """
        service = SyncService()
        session = MagicMock()
        session.info = {}  # F-06: deferred dispatch container
        account = MagicMock()
        account.id = 42
        account.email = "gmail@example.com"
        account.user_id = 11111  # arbitrary — must NOT be used for scoping

        email = self._setup_email()
        email_repo, contact_repo = self._patch_repos()
        adapter = MagicMock()

        # AccountRepository mock: track which method was called and
        # return both Gmail + Hotmail when get_active_accounts() is hit.
        repo_instance = MagicMock()
        repo_instance.get_active_accounts.return_value = [
            MagicMock(email="gmail@example.com"),
            MagicMock(email="hotmail@example.com"),
        ]
        # Scoped variant — if the code ever calls this, the assertion
        # below catches it. We make it return only the current account
        # (mirroring the bug behaviour) so a regression would silently
        # narrow the set.
        repo_instance.get_active_accounts_for_user.return_value = [
            MagicMock(email="gmail@example.com"),
        ]

        captured_own_emails: list = []

        def _capture(**kwargs):
            captured_own_emails.append(kwargs.get("own_account_emails"))
            return False

        with patch(
            "app.services.sync_service.EmailRepository", return_value=email_repo
        ), patch(
            "app.services.sync_service.ContactRepository", return_value=contact_repo
        ), patch(
            "app.services.sync_service.AccountRepository", return_value=repo_instance
        ), patch(
            "app.services.auto_reply.send_auto_reply_if_needed",
            side_effect=_capture,
        ):
            service._store_emails(
                session, account, [email], auto_reply_adapter=adapter
            )
            # F-06: drain the deferred dispatch (after_commit hook)
            for job in session.info.get("_deferred_auto_replies", []):
                job()

        # Contract:
        # 1. The un-scoped method was called.
        repo_instance.get_active_accounts.assert_called_once()
        # 2. The scoped variant was NOT — even though account.user_id is set.
        repo_instance.get_active_accounts_for_user.assert_not_called()
        # 3. The full set (both inboxes) reached the service.
        assert captured_own_emails and captured_own_emails[0] == {
            "gmail@example.com",
            "hotmail@example.com",
        }
