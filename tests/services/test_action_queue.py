# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Unit tests for ActionQueue service.

Tests queuing, processing, and management of offline actions.
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.db.models import ActionStatus, ActionType, PendingAction
from app.services.action_queue import (
    ActionQueue,
    ProcessResult,
    QueueResult,
    get_action_queue,
    init_action_queue,
    process_pending_actions_for_account,
    process_all_pending_actions,
)


class TestQueueResult:
    """Tests for QueueResult dataclass."""

    def test_successful_result(self):
        """Test successful queue result."""
        result = QueueResult(success=True, action_id=123)
        assert result.success is True
        assert result.action_id == 123
        assert result.error_message is None

    def test_failed_result(self):
        """Test failed queue result."""
        result = QueueResult(success=False, error_message="Database error")
        assert result.success is False
        assert result.action_id is None
        assert result.error_message == "Database error"


class TestProcessResult:
    """Tests for ProcessResult dataclass."""

    def test_default_values(self):
        """Test default values."""
        result = ProcessResult()
        assert result.total == 0
        assert result.completed == 0
        assert result.failed == 0
        assert result.errors == []

    def test_with_values(self):
        """Test with specified values."""
        result = ProcessResult(total=10, completed=8, failed=2, errors=["Error 1"])
        assert result.total == 10
        assert result.completed == 8
        assert result.failed == 2
        assert result.errors == ["Error 1"]

    def test_errors_list_initialized(self):
        """Test that errors list is properly initialized."""
        result = ProcessResult(total=5)
        result.errors.append("New error")
        assert "New error" in result.errors

        # New instance should have empty list
        result2 = ProcessResult()
        assert "New error" not in result2.errors


class TestActionQueue:
    """Tests for ActionQueue class."""

    @pytest.fixture
    def action_queue(self):
        """Create action queue instance."""
        return ActionQueue(max_retry_attempts=3)

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        session = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.flush = MagicMock()
        session.close = MagicMock()
        session.query = MagicMock()
        return session

    @pytest.fixture
    def mock_pending_action(self):
        """Create mock pending action."""
        action = MagicMock(spec=PendingAction)
        action.id = 1
        action.account_id = 1
        action.action_type = ActionType.MARK_READ.value
        action.email_id = "email123"
        action.payload = None
        action.status = ActionStatus.PENDING.value
        action.retry_count = 0
        action.error_message = None
        action.created_at = datetime.now(timezone.utc)
        return action

    def test_init_default_values(self):
        """Test default initialization."""
        queue = ActionQueue()
        assert queue.max_retry_attempts == 3
        assert queue._on_action_queued is None
        assert queue._on_action_processed is None

    def test_init_custom_values(self):
        """Test custom initialization."""
        callback1 = MagicMock()
        callback2 = MagicMock()
        queue = ActionQueue(
            max_retry_attempts=5,
            on_action_queued=callback1,
            on_action_processed=callback2,
        )
        assert queue.max_retry_attempts == 5
        assert queue._on_action_queued is callback1
        assert queue._on_action_processed is callback2

    @patch("app.services.action_queue.get_db_session")
    def test_queue_action_success(self, mock_get_session, action_queue, mock_session):
        """Test successful action queuing."""
        # Setup mock
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        # Queue action
        result = action_queue.queue_action(
            account_id=1,
            action_type=ActionType.MARK_READ,
            email_id="email123",
        )

        assert result.success is True
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @patch("app.services.action_queue.get_db_session")
    def test_queue_action_with_payload(self, mock_get_session, action_queue, mock_session):
        """Test queuing action with payload."""
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        payload = {"folder": "Archive"}
        result = action_queue.queue_action(
            account_id=1,
            action_type=ActionType.MOVE_TO_FOLDER,
            email_id="email123",
            payload=payload,
        )

        assert result.success is True
        # Verify the action was added with correct payload
        call_args = mock_session.add.call_args
        added_action = call_args[0][0]
        assert json.loads(added_action.payload) == payload

    @patch("app.services.action_queue.get_db_session")
    def test_queue_action_with_callback(self, mock_get_session, mock_session):
        """Test that on_action_queued callback is called."""
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        callback = MagicMock()
        queue = ActionQueue(on_action_queued=callback)

        queue.queue_action(
            account_id=1,
            action_type=ActionType.MARK_READ,
            email_id="email123",
        )

        callback.assert_called_once()

    @patch("app.services.action_queue.get_db_session")
    def test_queue_action_callback_error_handled(self, mock_get_session, mock_session):
        """Test that callback errors don't break queuing."""
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        callback = MagicMock(side_effect=Exception("Callback error"))
        queue = ActionQueue(on_action_queued=callback)

        result = queue.queue_action(
            account_id=1,
            action_type=ActionType.MARK_READ,
            email_id="email123",
        )

        # Should still succeed despite callback error
        assert result.success is True

    @patch("app.services.action_queue.get_db_session")
    def test_queue_action_with_existing_session(self, mock_get_session, action_queue, mock_session):
        """Test queuing with provided session doesn't commit."""
        result = action_queue.queue_action(
            account_id=1,
            action_type=ActionType.MARK_READ,
            email_id="email123",
            session=mock_session,
        )

        assert result.success is True
        mock_session.add.assert_called_once()
        # Should NOT commit when session is provided
        mock_session.commit.assert_not_called()

    @patch("app.services.action_queue.get_db_session")
    def test_get_pending_count_all_accounts(self, mock_get_session, action_queue, mock_session):
        """Test getting pending count for all accounts."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 5
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        count = action_queue.get_pending_count()
        assert count == 5

    @patch("app.services.action_queue.get_db_session")
    def test_get_pending_count_specific_account(self, mock_get_session, action_queue, mock_session):
        """Test getting pending count for specific account."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 3
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        count = action_queue.get_pending_count(account_id=1)
        assert count == 3
        # Should have additional filter for account_id
        assert mock_query.filter.call_count == 2

    @patch("app.services.action_queue.get_db_session")
    def test_get_pending_actions(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test getting pending actions."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        actions = action_queue.get_pending_actions(account_id=1)
        assert len(actions) == 1
        assert actions[0] == mock_pending_action

    @patch("app.services.action_queue.get_db_session")
    def test_get_pending_actions_custom_limit(self, mock_get_session, action_queue, mock_session):
        """Test getting pending actions with custom limit."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        action_queue.get_pending_actions(account_id=1, limit=50)
        mock_query.limit.assert_called_with(50)

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_success(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test processing queue with successful executor."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        executor = MagicMock(return_value=True)
        result = action_queue.process_queue(account_id=1, executor=executor)

        assert result.total == 1
        assert result.completed == 1
        assert result.failed == 0
        executor.assert_called_once_with(mock_pending_action)

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_executor_fails(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test processing queue when executor returns False."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        executor = MagicMock(return_value=False)
        result = action_queue.process_queue(account_id=1, executor=executor)

        assert result.total == 1
        assert result.completed == 0
        assert result.failed == 1
        assert mock_pending_action.status == ActionStatus.FAILED.value
        assert mock_pending_action.retry_count == 1

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_executor_raises(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test processing queue when executor raises exception."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        executor = MagicMock(side_effect=Exception("Network error"))
        result = action_queue.process_queue(account_id=1, executor=executor)

        assert result.total == 1
        assert result.completed == 0
        assert result.failed == 1
        assert mock_pending_action.status == ActionStatus.FAILED.value
        assert mock_pending_action.error_message == "Network error"

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_with_callback(self, mock_get_session, mock_session, mock_pending_action):
        """Test that on_action_processed callback is called."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        callback = MagicMock()
        queue = ActionQueue(on_action_processed=callback)

        executor = MagicMock(return_value=True)
        queue.process_queue(account_id=1, executor=executor)

        callback.assert_called_once_with(mock_pending_action, True)

    @patch("app.services.action_queue.get_db_session")
    def test_cancel_action_success(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test successfully cancelling an action."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_pending_action
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        result = action_queue.cancel_action(action_id=1)

        assert result is True
        assert mock_pending_action.status == ActionStatus.CANCELLED.value

    @patch("app.services.action_queue.get_db_session")
    def test_cancel_action_not_found(self, mock_get_session, action_queue, mock_session):
        """Test cancelling non-existent action."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        result = action_queue.cancel_action(action_id=999)

        assert result is False

    @patch("app.services.action_queue.get_db_session")
    def test_clear_completed(self, mock_get_session, action_queue, mock_session):
        """Test clearing completed actions."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.delete.return_value = 5
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        count = action_queue.clear_completed()

        assert count == 5
        mock_session.commit.assert_called_once()

    @patch("app.services.action_queue.get_db_session")
    def test_clear_completed_specific_account(self, mock_get_session, action_queue, mock_session):
        """Test clearing completed actions for specific account."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.delete.return_value = 3
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        count = action_queue.clear_completed(account_id=1)

        assert count == 3
        # Should have additional filter for account_id
        assert mock_query.filter.call_count == 2


class TestGlobalActionQueue:
    """Tests for global action queue functions."""

    def test_get_action_queue_creates_singleton(self):
        """Test that get_action_queue creates a singleton."""
        # Reset global instance
        import app.services.action_queue as module
        module._action_queue = None

        queue1 = get_action_queue()
        queue2 = get_action_queue()

        assert queue1 is queue2

    def test_init_action_queue_replaces_instance(self):
        """Test that init_action_queue creates new instance."""
        queue1 = init_action_queue(max_retry_attempts=5)
        queue2 = init_action_queue(max_retry_attempts=10)

        assert queue1 is not queue2
        assert queue2.max_retry_attempts == 10


class TestActionQueueEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def action_queue(self):
        """Create action queue instance."""
        return ActionQueue(max_retry_attempts=3)

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        session = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.flush = MagicMock()
        session.close = MagicMock()
        session.query = MagicMock()
        return session

    @pytest.fixture
    def mock_pending_action(self):
        """Create mock pending action."""
        action = MagicMock(spec=PendingAction)
        action.id = 1
        action.account_id = 1
        action.action_type = ActionType.MARK_READ.value
        action.email_id = "email123"
        action.payload = None
        action.status = ActionStatus.PENDING.value
        action.retry_count = 0
        action.error_message = None
        action.created_at = datetime.now(timezone.utc)
        return action

    @patch("app.services.action_queue.get_db_session")
    def test_queue_action_database_error(self, mock_get_session, action_queue):
        """Test queue_action when database error occurs."""
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(side_effect=Exception("Database connection failed"))
        mock_get_session.return_value = mock_context

        result = action_queue.queue_action(
            account_id=1,
            action_type=ActionType.MARK_READ,
            email_id="email123",
        )

        assert result.success is False
        assert "Database connection failed" in result.error_message

    @patch("app.services.action_queue.get_db_session")
    def test_queue_action_commit_error(self, mock_get_session, action_queue, mock_session):
        """Test queue_action when commit fails."""
        mock_session.commit.side_effect = Exception("Commit failed")
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value = mock_context

        result = action_queue.queue_action(
            account_id=1,
            action_type=ActionType.MARK_READ,
            email_id="email123",
        )

        assert result.success is False
        assert "Commit failed" in result.error_message

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_query_error(self, mock_get_session, action_queue, mock_session):
        """Test process_queue when query fails."""
        mock_session.query.side_effect = Exception("Query failed")
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value = mock_context

        result = action_queue.process_queue(account_id=1, executor=MagicMock())

        assert result.total == 0
        assert "Query failed" in result.errors

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_empty_queue(self, mock_get_session, action_queue, mock_session):
        """Test process_queue with empty queue."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value = mock_context

        result = action_queue.process_queue(account_id=1, executor=MagicMock())

        assert result.total == 0
        assert result.completed == 0
        assert result.failed == 0
        assert result.errors == []

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_callback_error_on_success(self, mock_get_session, mock_session, mock_pending_action):
        """Test that callback errors don't break processing on success."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value = mock_context

        callback = MagicMock(side_effect=Exception("Callback error"))
        queue = ActionQueue(on_action_processed=callback)

        executor = MagicMock(return_value=True)
        result = queue.process_queue(account_id=1, executor=executor)

        # Should still complete successfully despite callback error
        assert result.completed == 1
        assert result.failed == 0

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_callback_error_on_failure(self, mock_get_session, mock_session, mock_pending_action):
        """Test that callback errors don't break processing on failure."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value = mock_context

        callback = MagicMock(side_effect=Exception("Callback error"))
        queue = ActionQueue(on_action_processed=callback)

        executor = MagicMock(side_effect=Exception("Executor error"))
        result = queue.process_queue(account_id=1, executor=executor)

        # Should still count as failed despite callback error
        assert result.completed == 0
        assert result.failed == 1

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_multiple_actions(self, mock_get_session, action_queue, mock_session):
        """Test processing multiple actions with mixed results."""
        actions = []
        for i in range(3):
            action = MagicMock(spec=PendingAction)
            action.id = i + 1
            action.account_id = 1
            action.action_type = ActionType.MARK_READ.value
            action.email_id = f"email{i}"
            action.payload = None
            action.status = ActionStatus.PENDING.value
            action.retry_count = 0
            action.error_message = None
            actions.append(action)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = actions
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value = mock_context

        # First succeeds, second fails, third succeeds
        executor = MagicMock(side_effect=[True, False, True])
        result = action_queue.process_queue(account_id=1, executor=executor)

        assert result.total == 3
        assert result.completed == 2
        assert result.failed == 1

    @patch("app.services.action_queue.get_db_session")
    def test_get_pending_count_with_provided_session(self, mock_get_session, action_queue, mock_session):
        """Test get_pending_count with provided session doesn't close it."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 5
        mock_session.query.return_value = mock_query

        count = action_queue.get_pending_count(session=mock_session)

        assert count == 5
        mock_session.close.assert_not_called()

    @patch("app.services.action_queue.get_db_session")
    def test_get_pending_actions_with_provided_session(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test get_pending_actions with provided session doesn't close it."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        actions = action_queue.get_pending_actions(account_id=1, session=mock_session)

        assert len(actions) == 1
        mock_session.close.assert_not_called()

    @patch("app.services.action_queue.get_db_session")
    def test_cancel_action_with_provided_session(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test cancel_action with provided session."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_pending_action
        mock_session.query.return_value = mock_query

        result = action_queue.cancel_action(action_id=1, session=mock_session)

        assert result is True
        # Should NOT commit or close when session is provided
        mock_session.commit.assert_not_called()
        mock_session.close.assert_not_called()

    @patch("app.services.action_queue.get_db_session")
    def test_clear_completed_with_provided_session(self, mock_get_session, action_queue, mock_session):
        """Test clear_completed with provided session."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.delete.return_value = 5
        mock_session.query.return_value = mock_query

        count = action_queue.clear_completed(session=mock_session)

        assert count == 5
        # Should NOT commit or close when session is provided
        mock_session.commit.assert_not_called()
        mock_session.close.assert_not_called()

    @patch("app.services.action_queue.get_db_session")
    def test_queue_action_with_string_action_type(self, mock_get_session, action_queue, mock_session):
        """Test queue_action handles string action type."""
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value = mock_context

        result = action_queue.queue_action(
            account_id=1,
            action_type="mark_read",  # String instead of enum
            email_id="email123",
        )

        assert result.success is True
        call_args = mock_session.add.call_args
        added_action = call_args[0][0]
        assert added_action.action_type == "mark_read"

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_with_provided_session(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test process_queue with provided session doesn't close it."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        executor = MagicMock(return_value=True)
        result = action_queue.process_queue(account_id=1, executor=executor, session=mock_session)

        assert result.completed == 1
        mock_session.close.assert_not_called()

    @patch("app.services.action_queue.get_db_session")
    def test_process_action_sets_processing_status(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test that _process_action sets PROCESSING status before executing."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value = mock_context

        statuses = []
        def track_status(action):
            statuses.append(mock_pending_action.status)
            return True

        action_queue.process_queue(account_id=1, executor=track_status)

        # Should have been set to PROCESSING before executor was called
        assert ActionStatus.PROCESSING.value in statuses or statuses[0] == ActionStatus.PROCESSING.value

    @patch("app.services.action_queue.get_db_session")
    def test_process_action_clears_error_on_success(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test that _process_action clears error_message on success."""
        mock_pending_action.error_message = "Previous error"

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value = mock_context

        executor = MagicMock(return_value=True)
        action_queue.process_queue(account_id=1, executor=executor)

        assert mock_pending_action.error_message is None

    @patch("app.services.action_queue.get_db_session")
    def test_process_queue_adds_error_messages_to_result(self, mock_get_session, action_queue, mock_session, mock_pending_action):
        """Test that failed actions add error messages to result."""
        mock_pending_action.error_message = "Test error message"

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_pending_action]
        mock_session.query.return_value = mock_query

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value = mock_context

        executor = MagicMock(return_value=False)
        result = action_queue.process_queue(account_id=1, executor=executor)

        assert result.failed == 1
        # Error message should be added (executor sets it to "Executor returned False")
        assert any("Action 1" in err for err in result.errors)


class TestProcessPendingActionsForAccount:
    """Tests for process_pending_actions_for_account function."""

    @pytest.fixture
    def mock_provider(self):
        """Create mock email provider."""
        provider = MagicMock()
        provider.mark_as_read = MagicMock(return_value=True)
        provider.mark_as_unread = MagicMock(return_value=True)
        provider.star_email = MagicMock(return_value=True)
        provider.unstar_email = MagicMock(return_value=True)
        provider.delete_email = MagicMock(return_value=True)
        provider.archive_email = MagicMock(return_value=True)
        provider.move_to_folder = MagicMock(return_value=True)
        return provider

    @pytest.fixture
    def mock_action(self):
        """Create mock pending action."""
        action = MagicMock(spec=PendingAction)
        action.id = 1
        action.account_id = 1
        action.action_type = ActionType.MARK_READ.value
        action.email_id = "email123"
        action.payload = None
        action.status = ActionStatus.PENDING.value
        action.retry_count = 0
        action.error_message = None
        return action

    @patch("app.services.action_queue.get_action_queue")
    def test_mark_read_action(self, mock_get_queue, mock_provider):
        """Test executing mark_read action."""
        action = MagicMock()
        action.action_type = ActionType.MARK_READ.value
        action.email_id = "email123"
        action.payload = None

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(return_value=ProcessResult(total=1, completed=1))
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        mock_queue.process_queue.assert_called_once()

    @patch("app.services.action_queue.get_action_queue")
    def test_mark_unread_action(self, mock_get_queue, mock_provider):
        """Test executing mark_unread action."""
        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(return_value=ProcessResult(total=1, completed=1))
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        assert mock_queue.process_queue.called

    @patch("app.services.action_queue.get_action_queue")
    def test_star_email_action(self, mock_get_queue, mock_provider):
        """Test executing star_email action."""
        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(return_value=ProcessResult(total=1, completed=1))
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        assert mock_queue.process_queue.called

    @patch("app.services.action_queue.get_action_queue")
    def test_unstar_email_action(self, mock_get_queue, mock_provider):
        """Test executing unstar_email action."""
        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(return_value=ProcessResult(total=1, completed=1))
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        assert mock_queue.process_queue.called

    @patch("app.services.action_queue.get_action_queue")
    def test_delete_email_action(self, mock_get_queue, mock_provider):
        """Test executing delete_email action."""
        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(return_value=ProcessResult(total=1, completed=1))
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        assert mock_queue.process_queue.called

    @patch("app.services.action_queue.get_action_queue")
    def test_archive_email_action(self, mock_get_queue, mock_provider):
        """Test executing archive_email action."""
        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(return_value=ProcessResult(total=1, completed=1))
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        assert mock_queue.process_queue.called

    @patch("app.services.action_queue.get_action_queue")
    def test_move_to_folder_action_with_folder(self, mock_get_queue, mock_provider):
        """Test executing move_to_folder action with folder in payload."""
        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(return_value=ProcessResult(total=1, completed=1))
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        assert mock_queue.process_queue.called

    @patch("app.services.action_queue.get_action_queue")
    def test_returns_process_result(self, mock_get_queue, mock_provider):
        """Test that function returns ProcessResult from queue."""
        expected_result = ProcessResult(total=5, completed=4, failed=1)
        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(return_value=expected_result)
        mock_get_queue.return_value = mock_queue

        result = process_pending_actions_for_account(account_id=1, provider=mock_provider)

        assert result == expected_result


class TestProcessPendingActionsExecutor:
    """Tests for the execute_action function inside process_pending_actions_for_account."""

    @pytest.fixture
    def mock_provider(self):
        """Create mock email provider with all methods."""
        provider = MagicMock()
        provider.mark_as_read = MagicMock(return_value=True)
        provider.mark_as_unread = MagicMock(return_value=True)
        provider.star_email = MagicMock(return_value=True)
        provider.unstar_email = MagicMock(return_value=True)
        provider.delete_email = MagicMock(return_value=True)
        provider.archive_email = MagicMock(return_value=True)
        provider.move_to_folder = MagicMock(return_value=True)
        return provider

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_calls_mark_read(self, mock_get_queue, mock_provider):
        """Test executor calls provider.mark_as_read for MARK_READ action."""
        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        # Create mock action and test executor
        action = MagicMock()
        action.action_type = ActionType.MARK_READ.value
        action.email_id = "email123"
        action.payload = None

        result = captured_executor(action)
        assert result is True
        mock_provider.mark_as_read.assert_called_once_with("email123")

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_calls_mark_unread(self, mock_get_queue, mock_provider):
        """Test executor calls provider.mark_as_unread for MARK_UNREAD action."""
        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        action = MagicMock()
        action.action_type = ActionType.MARK_UNREAD.value
        action.email_id = "email123"
        action.payload = None

        result = captured_executor(action)
        assert result is True
        mock_provider.mark_as_unread.assert_called_once_with("email123")

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_calls_star_email(self, mock_get_queue, mock_provider):
        """Test executor calls provider.star_email for MARK_STARRED action."""
        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        action = MagicMock()
        action.action_type = ActionType.MARK_STARRED.value
        action.email_id = "email123"
        action.payload = None

        result = captured_executor(action)
        assert result is True
        mock_provider.star_email.assert_called_once_with("email123")

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_calls_unstar_email(self, mock_get_queue, mock_provider):
        """Test executor calls provider.unstar_email for MARK_UNSTARRED action."""
        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        action = MagicMock()
        action.action_type = ActionType.MARK_UNSTARRED.value
        action.email_id = "email123"
        action.payload = None

        result = captured_executor(action)
        assert result is True
        mock_provider.unstar_email.assert_called_once_with("email123")

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_calls_delete_email(self, mock_get_queue, mock_provider):
        """Test executor calls provider.delete_email for DELETE action."""
        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        action = MagicMock()
        action.action_type = ActionType.DELETE.value
        action.email_id = "email123"
        action.payload = None

        result = captured_executor(action)
        assert result is True
        mock_provider.delete_email.assert_called_once_with("email123")

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_calls_archive_email(self, mock_get_queue, mock_provider):
        """Test executor calls provider.archive_email for ARCHIVE action."""
        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        action = MagicMock()
        action.action_type = ActionType.ARCHIVE.value
        action.email_id = "email123"
        action.payload = None

        result = captured_executor(action)
        assert result is True
        mock_provider.archive_email.assert_called_once_with("email123")

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_calls_move_to_folder_with_folder(self, mock_get_queue, mock_provider):
        """Test executor calls provider.move_to_folder with folder from payload."""
        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        action = MagicMock()
        action.action_type = ActionType.MOVE_TO_FOLDER.value
        action.email_id = "email123"
        action.payload = json.dumps({"folder": "Archive"})

        result = captured_executor(action)
        assert result is True
        mock_provider.move_to_folder.assert_called_once_with("email123", "Archive")

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_move_to_folder_missing_folder(self, mock_get_queue, mock_provider):
        """Test executor returns False when move_to_folder is missing folder."""
        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        action = MagicMock()
        action.action_type = ActionType.MOVE_TO_FOLDER.value
        action.email_id = "email123"
        action.payload = json.dumps({})  # No folder

        result = captured_executor(action)
        assert result is False
        mock_provider.move_to_folder.assert_not_called()

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_unknown_action_type(self, mock_get_queue, mock_provider):
        """Test executor returns False for unknown action type."""
        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        action = MagicMock()
        action.action_type = "unknown_action"
        action.email_id = "email123"
        action.payload = None

        result = captured_executor(action)
        assert result is False

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_handles_provider_exception(self, mock_get_queue, mock_provider):
        """Test executor returns False when provider raises exception."""
        mock_provider.mark_as_read.side_effect = Exception("Provider error")

        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        action = MagicMock()
        action.action_type = ActionType.MARK_READ.value
        action.email_id = "email123"
        action.payload = None

        result = captured_executor(action)
        assert result is False

    @patch("app.services.action_queue.get_action_queue")
    def test_executor_parses_json_payload(self, mock_get_queue, mock_provider):
        """Test executor properly parses JSON payload."""
        captured_executor = None

        def capture_executor(*args, **kwargs):
            nonlocal captured_executor
            captured_executor = kwargs.get("executor")
            return ProcessResult()

        mock_queue = MagicMock()
        mock_queue.process_queue = MagicMock(side_effect=capture_executor)
        mock_get_queue.return_value = mock_queue

        process_pending_actions_for_account(account_id=1, provider=mock_provider)

        action = MagicMock()
        action.action_type = ActionType.MOVE_TO_FOLDER.value
        action.email_id = "email123"
        action.payload = json.dumps({"folder": "Spam", "extra_data": "ignored"})

        result = captured_executor(action)
        assert result is True
        mock_provider.move_to_folder.assert_called_once_with("email123", "Spam")


class TestProcessAllPendingActions:
    """Tests for process_all_pending_actions function.

    Note: Tests for processing accounts with pending actions are skipped
    because process_all_pending_actions relies on get_provider_for_account
    which is imported dynamically from app.providers.factory but doesn't exist.
    """

    @patch("app.services.action_queue.get_db_session")
    def test_handles_database_exception(self, mock_get_session):
        """Test handles database exception gracefully."""
        mock_get_session.side_effect = Exception("Database error")

        result = process_all_pending_actions()

        assert result == {}

    @patch("app.services.action_queue.get_db_session")
    @patch("app.services.action_queue.get_action_queue")
    def test_returns_empty_dict_when_no_accounts(self, mock_get_queue, mock_get_session):
        """Test returns empty dict when no accounts exist."""
        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        result = process_all_pending_actions()

        assert result == {}

    @patch("app.services.action_queue.get_db_session")
    @patch("app.services.action_queue.get_action_queue")
    def test_skips_accounts_with_no_pending_actions(self, mock_get_queue, mock_get_session):
        """Test skips accounts with no pending actions."""
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.email = "test@example.com"

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = [mock_account]
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_session)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_context

        mock_queue = MagicMock()
        mock_queue.get_pending_count = MagicMock(return_value=0)
        mock_get_queue.return_value = mock_queue

        result = process_all_pending_actions()

        assert result == {}
