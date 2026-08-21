# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""F-02 (audit 2026-05-11) — bulk_jobs worker must rollback optimistic state.

The clean-inbox HTTP path commits `Email.folder='archived'` to SQLite at
request time for every raw_id BEFORE the worker confirms with the
provider. When the worker later hits a per-item provider failure
(throttle, revoked token, transient 5xx after retry exhaustion), the
old code marked the item failed in the queue but never touched the
Email.folder row — so the email vanished from the user's inbox view
(SQLite said archived) while still living on the provider's INBOX.

The fix: the worker now reverts SQLite folder + emits
`emit_email_updated(archive_failed=True)` on per-item permanent
failure, so the frontend can un-strip the optimistic removal.

Single-email archive_email (issue #325) was fixed previously; this is
the bulk path equivalent.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch



def _make_item(job_type: str, msg_id: str = "abc123", account_id: int = 1):
    """Lightweight ClaimedItem stand-in — only the fields the rollback uses."""
    item = MagicMock()
    item.item_id = "item-1"
    item.job_id = "job-1"
    item.account_id = account_id
    item.job_type = job_type
    item.provider_msg_id = msg_id
    item.attempts = 0
    item.params = {}
    return item


class TestF02OptimisticRollback:
    """Direct unit tests of `_rollback_optimistic_state` — the helper the
    worker calls on per-item failure for destructive ops with optimistic
    SQLite updates."""

    def test_archive_failure_reverts_folder_to_inbox(self):
        from app.services.bulk_jobs import worker as w
        from app.db.models.bulk_job import JOB_TYPE_ARCHIVE

        item = _make_item(JOB_TYPE_ARCHIVE, msg_id="mail-abc")
        fake_repo = MagicMock()
        fake_session = MagicMock()

        with patch.object(
            w, "EmailRepository", return_value=fake_repo, create=True
        ) if False else patch(
            "app.db.repositories.email_repository.EmailRepository",
            return_value=fake_repo,
        ), patch(
            "app.api.websocket.emit_email_updated", create=True
        ) as mock_emit:
            w._rollback_optimistic_state(fake_session, item, reason="429 throttled")

        # 1. Folder reverted in SQLite.
        fake_repo.update_folder_by_email_id.assert_called_once_with(
            "mail-abc", "inbox", account_id=1,
        )
        # 2. Frontend notified so it un-strips the row.
        mock_emit.assert_called_once()
        emit_args, emit_kwargs = mock_emit.call_args
        assert emit_args[0] == "mail-abc"
        payload = emit_args[1]
        assert payload.get("archive_failed") is True
        assert payload.get("error") == "429 throttled"
        assert emit_kwargs.get("account_id") == 1

    def test_trash_failure_reverts_and_emits_trash_failed(self):
        from app.services.bulk_jobs import worker as w
        from app.db.models.bulk_job import JOB_TYPE_MOVE_TO_TRASH

        item = _make_item(JOB_TYPE_MOVE_TO_TRASH, msg_id="mail-xyz")
        fake_repo = MagicMock()
        fake_session = MagicMock()

        with patch(
            "app.db.repositories.email_repository.EmailRepository",
            return_value=fake_repo,
        ), patch("app.api.websocket.emit_email_updated", create=True) as mock_emit:
            w._rollback_optimistic_state(fake_session, item, reason="500 server error")

        fake_repo.update_folder_by_email_id.assert_called_once_with(
            "mail-xyz", "inbox", account_id=1,
        )
        mock_emit.assert_called_once()
        payload = mock_emit.call_args.args[1]
        assert payload.get("trash_failed") is True

    def test_mark_read_failure_is_no_op(self):
        """JOB_TYPE_MARK_READ does not optimistically commit folder
        changes — the helper must be a pure no-op for it."""
        from app.services.bulk_jobs import worker as w
        from app.db.models.bulk_job import JOB_TYPE_MARK_READ

        item = _make_item(JOB_TYPE_MARK_READ, msg_id="mail-read")
        fake_repo = MagicMock()
        fake_session = MagicMock()

        with patch(
            "app.db.repositories.email_repository.EmailRepository",
            return_value=fake_repo,
        ), patch("app.api.websocket.emit_email_updated", create=True) as mock_emit:
            w._rollback_optimistic_state(fake_session, item, reason="whatever")

        fake_repo.update_folder_by_email_id.assert_not_called()
        mock_emit.assert_not_called()

    def test_emit_failure_does_not_break_rollback(self):
        """If emit_email_updated raises (e.g. WS layer down), the SQLite
        revert must still happen and the helper must not propagate."""
        from app.services.bulk_jobs import worker as w
        from app.db.models.bulk_job import JOB_TYPE_ARCHIVE

        item = _make_item(JOB_TYPE_ARCHIVE, msg_id="mail-emit-broke")
        fake_repo = MagicMock()
        fake_session = MagicMock()

        with patch(
            "app.db.repositories.email_repository.EmailRepository",
            return_value=fake_repo,
        ), patch(
            "app.api.websocket.emit_email_updated",
            side_effect=RuntimeError("WS down"),
            create=True,
        ):
            # Should not raise.
            w._rollback_optimistic_state(fake_session, item, reason="x")

        # SQLite revert still happened.
        fake_repo.update_folder_by_email_id.assert_called_once()


class TestF02WorkerWiring:
    """Source-level guard: confirm the worker actually calls the rollback
    helper from the per-item failure paths. If a future refactor drops
    the call, the rollback hook becomes dead code and the bug returns.

    The full integration path (claim → execute → fail → rollback) is too
    coupled to the dispatcher loop to mock cheaply; this guard catches the
    regression that matters: a future commit removing the helper call.
    """

    def test_worker_invokes_rollback_on_permanent_failure(self):
        import inspect
        from app.services.bulk_jobs import worker as w

        src = inspect.getsource(w._AccountQueue._process_claimed)
        assert "_rollback_optimistic_state" in src, (
            "_process_claimed no longer calls _rollback_optimistic_state — "
            "the F-02 rollback hook is dead code. Restore the call before "
            "mark_item_failed in the auth_failed and permanent-failure paths."
        )

    def test_auth_failure_rolls_back_current_and_pending_items(self):
        from app.services.bulk_jobs import worker as w
        from app.db.models.bulk_job import JOB_TYPE_MOVE_TO_TRASH

        item = _make_item(JOB_TYPE_MOVE_TO_TRASH, msg_id="mail-current")
        fake_repo = MagicMock()
        fake_repo.list_items.return_value = [
            {
                "id": 2,
                "provider_msg_id": "mail-pending",
                "attempts": 0,
            }
        ]
        fake_session = MagicMock()
        fake_bucket = MagicMock()
        fake_bucket.acquire.return_value = True
        queue = w._AccountQueue(account_id=1, worker=MagicMock())
        queue._ensure_provider = MagicMock(return_value=object())
        queue._ensure_bucket = MagicMock(return_value=fake_bucket)
        queue._maybe_finalize = MagicMock()

        with patch.object(
            w,
            "_execute_op",
            return_value=w._OpOutcome(
                succeeded=False,
                auth_failed=True,
                error="invalid_grant",
            ),
        ), patch.object(w, "_rollback_optimistic_state") as mock_rollback:
            queue._process_claimed(fake_repo, fake_session, item)

        rolled_back_ids = [
            call.args[1].provider_msg_id for call in mock_rollback.call_args_list
        ]
        assert rolled_back_ids == ["mail-current", "mail-pending"]
        fake_repo.fail_remaining_pending.assert_called_once_with("job-1", "auth failed")

    def test_missing_provider_rolls_back_current_and_pending_items(self):
        from app.services.bulk_jobs import worker as w
        from app.db.models.bulk_job import JOB_TYPE_MOVE_TO_TRASH

        item = _make_item(JOB_TYPE_MOVE_TO_TRASH, msg_id="mail-current")
        fake_repo = MagicMock()
        fake_repo.list_items.return_value = [
            {
                "id": 2,
                "provider_msg_id": "mail-pending",
                "attempts": 0,
            }
        ]
        fake_session = MagicMock()
        queue = w._AccountQueue(account_id=1, worker=MagicMock())
        queue._ensure_provider = MagicMock(return_value=None)
        queue._maybe_finalize = MagicMock()

        with patch.object(w, "_rollback_optimistic_state") as mock_rollback:
            queue._process_claimed(fake_repo, fake_session, item)

        rolled_back_ids = [
            call.args[1].provider_msg_id for call in mock_rollback.call_args_list
        ]
        assert rolled_back_ids == ["mail-current", "mail-pending"]
        fake_repo.fail_remaining_pending.assert_called_once_with(
            "job-1", "no authenticated provider"
        )
