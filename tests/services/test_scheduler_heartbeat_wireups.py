# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Phase B wire-up tests — issue #577 item 4.

The heartbeat helper itself is covered by ``test_scheduler_heartbeat.py``.
This file verifies that the 4 Phase B schedulers actually *call* it from
their tick body — without that wire-up the helper has nothing to detect.

Each scheduler is exercised for a single tick with its real loop body
short-circuited. We assert ``record_heartbeat`` is called at least once
with the expected name. The scheduler's own logic (recap rules, batch
submission, etc.) is out of scope here — it has its own test files.
"""

from __future__ import annotations

import threading
from unittest.mock import patch


def _heartbeat_calls(mock_record, name: str) -> list:
    """Return every call to record_heartbeat for ``name``."""
    return [
        call
        for call in mock_record.call_args_list
        if call.args and call.args[0] == name
    ]


class TestRecapSchedulerHeartbeat:
    def test_tick_records_ok_heartbeat(self):
        """A single tick of RecapScheduler should stamp recap_scheduler=ok."""
        from app.services.recap_scheduler import RecapScheduler

        sched = RecapScheduler()

        with patch(
            "app.services.scheduler_heartbeat.record_heartbeat"
        ) as mock_record, patch.object(
            sched, "_check_and_trigger"
        ) as mock_check:
            # Stop the loop right after the first iteration.
            def _stop_after_one_check():
                sched._stop_event.set()

            mock_check.side_effect = _stop_after_one_check
            # Skip the 60s initial wait.
            sched._stop_event = threading.Event()
            with patch.object(sched._stop_event, "wait", return_value=False):
                # Manually drive _run — the inner ``wait`` is patched so
                # the initial-delay branch falls through and the loop
                # body runs once before stop_event.is_set() ends it.
                sched._run()

        calls = _heartbeat_calls(mock_record, "recap_scheduler")
        assert len(calls) >= 1
        assert calls[0].kwargs["status"] == "ok"
        assert calls[0].kwargs["expected_interval_seconds"] > 0

    def test_exception_in_tick_records_error_heartbeat(self):
        """When _check_and_trigger raises, the scheduler should stamp
        a second heartbeat with status=error so the sentinel can surface
        the degraded state separately from a flat-out dead thread."""
        from app.services.recap_scheduler import RecapScheduler

        sched = RecapScheduler()

        with patch(
            "app.services.scheduler_heartbeat.record_heartbeat"
        ) as mock_record, patch.object(
            sched, "_check_and_trigger"
        ) as mock_check:
            mock_check.side_effect = RuntimeError("boom")
            sched._stop_event = threading.Event()
            # Let one tick run, then stop. The first wait() is the
            # 60s initial-delay guard; the second is the inter-tick
            # sleep. Set stop on the second call.
            wait_calls = {"n": 0}

            def _wait(timeout=None):
                wait_calls["n"] += 1
                if wait_calls["n"] >= 2:
                    sched._stop_event.set()
                return False

            with patch.object(sched._stop_event, "wait", side_effect=_wait):
                sched._run()

        statuses = [
            c.kwargs.get("status")
            for c in _heartbeat_calls(mock_record, "recap_scheduler")
        ]
        assert "ok" in statuses
        assert "error" in statuses


class TestBulkJobsSchedulerHeartbeat:
    def test_tick_records_ok_heartbeat(self):
        from app.services.bulk_jobs.scheduler import AutoDeletionScheduler

        sched = AutoDeletionScheduler()

        with patch(
            "app.services.scheduler_heartbeat.record_heartbeat"
        ) as mock_record, patch.object(
            sched, "_maybe_fire"
        ) as mock_fire:
            def _stop_after_one_fire():
                sched._stop.set()

            mock_fire.side_effect = _stop_after_one_fire
            sched._stop = threading.Event()
            with patch.object(sched._stop, "wait", return_value=False):
                sched._run()

        calls = _heartbeat_calls(mock_record, "bulk_jobs_scheduler")
        assert len(calls) >= 1
        assert calls[0].kwargs["status"] == "ok"

    def test_exception_in_tick_records_error_heartbeat(self):
        from app.services.bulk_jobs.scheduler import AutoDeletionScheduler

        sched = AutoDeletionScheduler()

        with patch(
            "app.services.scheduler_heartbeat.record_heartbeat"
        ) as mock_record, patch.object(
            sched, "_maybe_fire"
        ) as mock_fire:
            mock_fire.side_effect = RuntimeError("boom")
            sched._stop = threading.Event()
            wait_calls = {"n": 0}

            def _wait(timeout=None):
                wait_calls["n"] += 1
                if wait_calls["n"] >= 2:
                    sched._stop.set()
                return False

            with patch.object(sched._stop, "wait", side_effect=_wait):
                sched._run()

        statuses = [
            c.kwargs.get("status")
            for c in _heartbeat_calls(mock_record, "bulk_jobs_scheduler")
        ]
        assert "ok" in statuses
        assert "error" in statuses


class TestBatchWorkerHeartbeat:
    def test_tick_records_ok_heartbeat(self):
        from app.batch_queue import BatchWorker

        worker = BatchWorker()

        with patch(
            "app.services.scheduler_heartbeat.record_heartbeat"
        ) as mock_record, patch.object(
            worker, "_tick"
        ) as mock_tick:
            def _stop_after_one_tick():
                worker._stop_event.set()

            mock_tick.side_effect = _stop_after_one_tick
            worker._stop_event = threading.Event()
            with patch.object(worker._stop_event, "wait", return_value=False):
                worker._run_loop()

        calls = _heartbeat_calls(mock_record, "batch_worker")
        assert len(calls) >= 1
        assert calls[0].kwargs["status"] == "ok"

    def test_exception_in_tick_records_error_heartbeat(self):
        from app.batch_queue import BatchWorker

        worker = BatchWorker()

        with patch(
            "app.services.scheduler_heartbeat.record_heartbeat"
        ) as mock_record, patch.object(
            worker, "_tick"
        ) as mock_tick:
            mock_tick.side_effect = RuntimeError("boom")
            worker._stop_event = threading.Event()
            # The batch worker waits AFTER tick (success) and AFTER the
            # backoff sleep (failure). On exception the loop returns to
            # ``continue`` and re-enters; we stop on the second wait().
            wait_calls = {"n": 0}

            def _wait(timeout=None):
                wait_calls["n"] += 1
                if wait_calls["n"] >= 2:
                    worker._stop_event.set()
                    return True  # break out via wait==True path
                return False

            with patch.object(worker._stop_event, "wait", side_effect=_wait):
                worker._run_loop()

        statuses = [
            c.kwargs.get("status")
            for c in _heartbeat_calls(mock_record, "batch_worker")
        ]
        assert "ok" in statuses
        assert "error" in statuses


class TestLearningRefreshSchedulerHeartbeat:
    """LearningRefreshScheduler is Timer-based (no while loop). The
    heartbeat lives in the per-fire callback, so we drive it directly
    instead of going through threading.
    """

    def test_check_records_ok_heartbeat(self):
        from app.learning_refresh import (
            LearningRefreshCoordinator,
            LearningRefreshScheduler,
        )

        coord = LearningRefreshCoordinator()
        sched = LearningRefreshScheduler(coord)
        # Prevent recursive timer scheduling — _check_and_refresh's
        # ``finally`` block would otherwise spawn a real Timer.
        sched._running = False

        with patch(
            "app.services.scheduler_heartbeat.record_heartbeat"
        ) as mock_record, patch.object(
            coord, "check_deep_refresh_due", return_value=False
        ):
            sched._check_and_refresh()

        calls = _heartbeat_calls(mock_record, "learning_refresh_scheduler")
        assert len(calls) >= 1
        assert calls[0].kwargs["status"] == "ok"

    def test_exception_records_error_heartbeat(self):
        from app.learning_refresh import (
            LearningRefreshCoordinator,
            LearningRefreshScheduler,
        )

        coord = LearningRefreshCoordinator()
        sched = LearningRefreshScheduler(coord)
        sched._running = False

        with patch(
            "app.services.scheduler_heartbeat.record_heartbeat"
        ) as mock_record, patch.object(
            coord, "check_deep_refresh_due", side_effect=RuntimeError("boom")
        ):
            # Must not raise — the scheduler swallows exceptions so the
            # next Timer fire still happens.
            sched._check_and_refresh()

        statuses = [
            c.kwargs.get("status")
            for c in _heartbeat_calls(
                mock_record, "learning_refresh_scheduler"
            )
        ]
        assert "ok" in statuses
        assert "error" in statuses
