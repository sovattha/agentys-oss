# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Daemon thread that flips zombie onboardings to ``failed``.

Companion to ``OnboardingManager.cleanup_stale_onboardings`` — calls it on a
fixed cadence so a row stuck in ``waiting_for_sync`` / ``running`` never
outlives its dead worker thread by more than ``check_interval`` seconds.

Designed to live alongside the other process-lifetime schedulers wired in
``run_api.py`` (sync, recap, scheduled-email, gmail-watch). Same shape:
``start()`` spawns a daemon thread, ``stop()`` joins with timeout.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60
INITIAL_DELAY_SECONDS = 30


class OnboardingWatchdog:
    def __init__(
        self,
        *,
        manager_factory: Optional[Callable[[], object]] = None,
        check_interval: int = CHECK_INTERVAL_SECONDS,
        initial_delay: int = INITIAL_DELAY_SECONDS,
        stale_seconds: float = 600.0,
        grace_seconds: float = 60.0,
    ):
        """
        Args:
            manager_factory: zero-arg callable returning an OnboardingManager
                with a ``cleanup_stale_onboardings`` method. Injected so tests
                can pass a stub. Defaults to the lazy ``_get_manager()`` from
                the API layer (resolved at start time to avoid import cycles).
            check_interval: seconds between watchdog ticks.
            initial_delay: grace period after process start before the first
                tick. Lets the boot-time ``recover_orphaned_waiting`` settle.
            stale_seconds: see ``cleanup_stale_onboardings``.
            grace_seconds: see ``cleanup_stale_onboardings``.
        """
        self._manager_factory = manager_factory
        self._check_interval = check_interval
        self._initial_delay = initial_delay
        self._stale_seconds = stale_seconds
        self._grace_seconds = grace_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _resolve_manager(self):
        if self._manager_factory is not None:
            return self._manager_factory()
        # Default: the API-layer factory. Imported lazily so this module can
        # be imported standalone (tests, scripts) without dragging Flask.
        from app.api.onboarding import _get_manager
        return _get_manager()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="OnboardingWatchdog",
        )
        self._thread.start()
        logger.info(
            "OnboardingWatchdog started (poll=%ss, stale=%.0fs, grace=%.0fs)",
            self._check_interval, self._stale_seconds, self._grace_seconds,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("OnboardingWatchdog stopped")

    def _run(self) -> None:
        # Initial delay: recover_orphaned_waiting() runs at boot and may have
        # just flipped a batch of rows. Don't tick on top of that.
        if self._stop_event.wait(self._initial_delay):
            return
        while not self._stop_event.is_set():
            try:
                manager = self._resolve_manager()
                flipped = manager.cleanup_stale_onboardings(
                    stale_seconds=self._stale_seconds,
                    grace_seconds=self._grace_seconds,
                )
                if flipped:
                    logger.warning(
                        "OnboardingWatchdog: flipped %d stale onboarding(s) to failed: %s",
                        len(flipped), flipped,
                    )
            except Exception:
                # Never let a tick failure kill the watchdog. The next tick
                # will retry; meanwhile the periodic logger output makes the
                # incident visible.
                logger.exception("OnboardingWatchdog tick failed")
            if self._stop_event.wait(self._check_interval):
                return
