# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Action queue service for offline operations.

Manages queuing and processing of email actions that occur while offline.
Actions are stored in the database and processed in FIFO order when
connectivity is restored.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.db.models import ActionStatus, ActionType, PendingAction

logger = logging.getLogger(__name__)


@dataclass
class QueueResult:
    """Result of queuing an action."""

    success: bool
    action_id: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class ProcessResult:
    """Result of processing queued actions."""

    total: int = 0
    completed: int = 0
    failed: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class ActionQueue:
    """
    Service for managing offline action queue.

    Queues actions when offline and processes them when connectivity
    is restored. Actions are processed in FIFO order.

    Usage:
        queue = ActionQueue()
        queue.queue_action(account_id=1, action_type=ActionType.MARK_READ, email_id="abc123")
        # Later, when online:
        results = queue.process_queue(account_id=1, executor=my_executor)
    """

    def __init__(
        self,
        max_retry_attempts: int = 3,
        on_action_queued: Optional[Callable[[PendingAction], None]] = None,
        on_action_processed: Optional[Callable[[PendingAction, bool], None]] = None,
        on_action_permanently_failed: Optional[Callable[[PendingAction], None]] = None,
    ):
        """
        Initialize the action queue.

        Args:
            max_retry_attempts: Maximum retries for failed actions.
            on_action_queued: Callback when action is queued.
            on_action_processed: Callback when action is processed (success/fail).
            on_action_permanently_failed: Callback quand `retry_count` atteint
                `max_retry_attempts` après un nouvel échec — permet au caller
                de wire un `socketio.emit('action_failed_permanently', …)` pour
                sortir l'UI de l'illusion « action réussie ». Silent-failure fix
                pour l'issue #319.
        """
        self.max_retry_attempts = max_retry_attempts
        self._on_action_queued = on_action_queued
        self._on_action_processed = on_action_processed
        self._on_action_permanently_failed = on_action_permanently_failed

    def queue_action(
        self,
        account_id: int,
        action_type: ActionType,
        email_id: str,
        payload: Optional[Dict[str, Any]] = None,
        session: Optional[Session] = None,
    ) -> QueueResult:
        """
        Add an action to the queue.

        Args:
            account_id: Account the action belongs to.
            action_type: Type of action (mark_read, etc.).
            email_id: Provider's email ID.
            payload: Additional data for the action.
            session: Optional database session (creates one if not provided).

        Returns:
            QueueResult with success status and action ID.
        """
        try:
            should_commit = session is None
            if session is None:
                session = get_db_session().__enter__()

            action = PendingAction(
                account_id=account_id,
                action_type=action_type.value
                if isinstance(action_type, ActionType)
                else action_type,
                email_id=email_id,
                payload=json.dumps(payload) if payload else None,
                status=ActionStatus.PENDING.value,
            )

            session.add(action)

            if should_commit:
                session.commit()

            logger.info(
                f"Queued action: {action_type} for email {email_id} (account {account_id})"
            )

            if self._on_action_queued:
                try:
                    self._on_action_queued(action)
                except Exception as e:
                    logger.error(f"Error in on_action_queued callback: {e}")

            return QueueResult(success=True, action_id=action.id)

        except Exception as e:
            logger.error(f"Failed to queue action: {e}")
            return QueueResult(success=False, error_message=str(e))

    def get_pending_count(
        self, account_id: Optional[int] = None, session: Optional[Session] = None
    ) -> int:
        """
        Get count of pending actions.

        Args:
            account_id: Filter by account (None for all accounts).
            session: Optional database session.

        Returns:
            Number of pending actions.
        """
        should_close = session is None
        if session is None:
            session = get_db_session().__enter__()

        try:
            query = session.query(PendingAction).filter(
                PendingAction.status == ActionStatus.PENDING.value
            )

            if account_id is not None:
                query = query.filter(PendingAction.account_id == account_id)

            return query.count()
        finally:
            if should_close:
                session.close()

    def get_pending_actions(
        self, account_id: int, session: Optional[Session] = None, limit: int = 100
    ) -> List[PendingAction]:
        """
        Get pending actions for an account.

        Args:
            account_id: Account to get actions for.
            session: Optional database session.
            limit: Maximum actions to return.

        Returns:
            List of PendingAction objects in FIFO order.
        """
        should_close = session is None
        if session is None:
            session = get_db_session().__enter__()

        try:
            return (
                session.query(PendingAction)
                .filter(
                    PendingAction.account_id == account_id,
                    PendingAction.status == ActionStatus.PENDING.value,
                )
                .order_by(PendingAction.created_at.asc())
                .limit(limit)
                .all()
            )
        finally:
            if should_close:
                session.close()

    def process_queue(
        self,
        account_id: int,
        executor: Callable[[PendingAction], bool],
        session: Optional[Session] = None,
    ) -> ProcessResult:
        """
        Process all pending actions for an account.

        Args:
            account_id: Account to process actions for.
            executor: Function that executes an action, returns True on success.
            session: Optional database session.

        Returns:
            ProcessResult with counts of completed/failed actions.
        """
        should_close = session is None
        if session is None:
            session = get_db_session().__enter__()

        result = ProcessResult()

        try:
            actions = (
                session.query(PendingAction)
                .filter(
                    PendingAction.account_id == account_id,
                    PendingAction.status.in_(
                        [ActionStatus.PENDING.value, ActionStatus.FAILED.value]
                    ),
                    PendingAction.retry_count < self.max_retry_attempts,
                )
                .order_by(PendingAction.created_at.asc())
                .all()
            )

            result.total = len(actions)

            for action in actions:
                success = self._process_action(action, executor, session)
                if success:
                    result.completed += 1
                else:
                    result.failed += 1
                    if action.error_message:
                        result.errors.append(
                            f"Action {action.id}: {action.error_message}"
                        )

            session.commit()

            logger.info(
                f"Processed {result.total} actions for account {account_id}: "
                f"{result.completed} completed, {result.failed} failed"
            )

            return result

        except Exception as e:
            logger.error(f"Error processing queue for account {account_id}: {e}")
            result.errors.append(str(e))
            return result
        finally:
            if should_close:
                session.close()

    def _process_action(
        self, action: PendingAction, executor: Callable[[PendingAction], bool], session: Session
    ) -> bool:
        """
        Process a single action.

        Args:
            action: The action to process.
            executor: Function that executes the action.
            session: Database session.

        Returns:
            True if successful, False otherwise.
        """
        action.status = ActionStatus.PROCESSING.value
        session.flush()

        try:
            success = executor(action)

            if success:
                action.status = ActionStatus.COMPLETED.value
                action.processed_at = datetime.now(timezone.utc)
                action.error_message = None
            else:
                action.status = ActionStatus.FAILED.value
                action.retry_count += 1
                action.error_message = "Executor returned False"
                self._notify_if_permanently_failed(action)

            if self._on_action_processed:
                try:
                    self._on_action_processed(action, success)
                except Exception as e:
                    logger.error(f"Error in on_action_processed callback: {e}")

            return success

        except Exception as e:
            action.status = ActionStatus.FAILED.value
            action.retry_count += 1
            action.error_message = str(e)
            logger.error(f"Error processing action {action.id}: {e}")
            self._notify_if_permanently_failed(action)

            if self._on_action_processed:
                try:
                    self._on_action_processed(action, False)
                except Exception as callback_error:
                    logger.error(f"Error in on_action_processed callback: {callback_error}")

            return False

    def _notify_if_permanently_failed(self, action: PendingAction) -> None:
        """Fire `on_action_permanently_failed` si `retry_count` vient d'atteindre
        le plafond `max_retry_attempts` (silent-failure fix, issue #319).

        Le callback reste optionnel ; les erreurs du callback sont loguées
        sans remonter pour ne pas casser la boucle de traitement.
        """
        if self._on_action_permanently_failed is None:
            return
        if action.retry_count < self.max_retry_attempts:
            return
        try:
            logger.error(
                "Action %s permanently failed after %d retries (type=%s email=%s)",
                getattr(action, "id", "?"),
                action.retry_count,
                getattr(action, "action_type", "?"),
                getattr(action, "email_id", "?"),
            )
            self._on_action_permanently_failed(action)
        except Exception as callback_err:
            logger.error(f"Error in on_action_permanently_failed callback: {callback_err}")

    def cancel_action(
        self,
        action_id: int,
        account_id: Optional[int] = None,
        session: Optional[Session] = None,
    ) -> bool:
        """
        Cancel a pending action.

        Args:
            action_id: ID of the action to cancel.
            account_id: When provided, only cancels if the action belongs to
                this account (defense-in-depth against IDOR via guessed
                action_id). Audit 2026-04-25.
            session: Optional database session.

        Returns:
            True if cancelled, False if not found, already processed, or
            owned by a different account.
        """
        should_close = session is None
        if session is None:
            session = get_db_session().__enter__()

        try:
            query = session.query(PendingAction).filter(
                PendingAction.id == action_id,
                PendingAction.status == ActionStatus.PENDING.value,
            )
            if account_id is not None:
                query = query.filter(PendingAction.account_id == account_id)
            action = query.first()

            if action:
                action.status = ActionStatus.CANCELLED.value
                if should_close:
                    session.commit()
                logger.info(f"Cancelled action {action_id}")
                return True

            return False

        finally:
            if should_close:
                session.close()

    def clear_completed(
        self, account_id: Optional[int] = None, session: Optional[Session] = None
    ) -> int:
        """
        Remove completed actions from the queue.

        Args:
            account_id: Filter by account (None for all).
            session: Optional database session.

        Returns:
            Number of actions deleted.
        """
        should_close = session is None
        if session is None:
            session = get_db_session().__enter__()

        try:
            query = session.query(PendingAction).filter(
                PendingAction.status == ActionStatus.COMPLETED.value
            )

            if account_id is not None:
                query = query.filter(PendingAction.account_id == account_id)

            count = query.delete(synchronize_session=False)

            if should_close:
                session.commit()

            logger.info(f"Cleared {count} completed actions")
            return count

        finally:
            if should_close:
                session.close()


# Global action queue instance
_action_queue: Optional[ActionQueue] = None


def get_action_queue() -> ActionQueue:
    """Get the global action queue instance."""
    global _action_queue
    if _action_queue is None:
        _action_queue = ActionQueue()
    return _action_queue


def init_action_queue(**kwargs) -> ActionQueue:
    """
    Initialize the global action queue.

    Args:
        **kwargs: Arguments for ActionQueue.

    Returns:
        The initialized ActionQueue instance.
    """
    global _action_queue
    _action_queue = ActionQueue(**kwargs)
    return _action_queue


def process_pending_actions_for_account(
    account_id: int,
    provider,
) -> ProcessResult:
    """
    Process all pending actions for a specific account.

    This function is called when connectivity is restored to execute
    all queued actions.

    Args:
        account_id: The database account ID.
        provider: The authenticated email provider instance.

    Returns:
        ProcessResult with counts of completed/failed actions.
    """
    from app.db.models import ActionType

    def execute_action(action: PendingAction) -> bool:
        """Execute a single pending action."""
        action_type = action.action_type
        email_id = action.email_id
        payload = json.loads(action.payload) if action.payload else {}

        try:
            if action_type == ActionType.MARK_READ.value:
                return provider.mark_as_read(email_id)
            elif action_type == ActionType.MARK_UNREAD.value:
                return provider.mark_as_unread(email_id)
            elif action_type == ActionType.MARK_STARRED.value:
                return provider.star_email(email_id)
            elif action_type == ActionType.MARK_UNSTARRED.value:
                return provider.unstar_email(email_id)
            elif action_type == ActionType.DELETE.value:
                return provider.delete_email(email_id)
            elif action_type == ActionType.ARCHIVE.value:
                return provider.archive_email(email_id)
            elif action_type == ActionType.MOVE_TO_FOLDER.value:
                folder = payload.get("folder")
                if folder:
                    return provider.move_to_folder(email_id, folder)
                else:
                    logger.error(f"Missing folder in payload for action {action.id}")
                    return False
            else:
                logger.error(f"Unknown action type: {action_type}")
                return False
        except Exception as e:
            logger.error(f"Error executing action {action.id}: {e}")
            return False

    action_queue = get_action_queue()
    return action_queue.process_queue(
        account_id=account_id,
        executor=execute_action,
    )


def process_all_pending_actions(user_id: int | None = None) -> Dict[int, ProcessResult]:
    """
    Process pending actions for all accounts owned by ``user_id``.

    This function is called when connectivity is restored to execute
    all queued actions across all accounts.

    Args:
        user_id: If set, restricts processing to accounts owned by this
            user (``Account.user_id == user_id``). ``None`` keeps the
            legacy unrestricted iteration — required for loopback Tauri
            (single-user host) and any caller that has already validated
            ownership upstream. Audit H-5 (issue #531): the API route
            always passes the JWT caller's id ; ``None`` is reserved for
            loopback / internal callers.

    Returns:
        Dictionary mapping account_id to ProcessResult.
    """
    from app.db.database import get_db_session
    from app.db.models import Account
    from app.db.repositories import AccountRepository

    results: Dict[int, ProcessResult] = {}

    try:
        with get_db_session() as session:
            AccountRepository(session)
            query = session.query(Account)
            if user_id is not None:
                query = query.filter(Account.user_id == user_id)
            accounts = query.all()

            for account in accounts:
                # Check if account has pending actions
                action_queue = get_action_queue()
                pending_count = action_queue.get_pending_count(account_id=account.id)

                if pending_count == 0:
                    continue

                # Get provider for this account
                try:
                    from app.providers.factory import get_provider_for_account
                    provider = get_provider_for_account(account)
                    if provider and provider.authenticate():
                        result = process_pending_actions_for_account(account.id, provider)
                        results[account.id] = result

                        logger.info(
                            f"Processed {result.total} pending actions for account {account.email}: "
                            f"{result.completed} completed, {result.failed} failed"
                        )
                    else:
                        logger.warning(f"Could not authenticate provider for account {account.email}")
                except Exception as e:
                    logger.error(f"Error processing pending actions for account {account.email}: {e}")

    except Exception as e:
        logger.error(f"Error processing all pending actions: {e}")

    return results
