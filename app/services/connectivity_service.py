# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Connectivity service for network status detection.

Monitors network connectivity and notifies when status changes.
Used to enable/disable online-only features and trigger queue processing.
"""

import logging
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class ConnectivityStatus:
    """Current connectivity status."""

    is_online: bool = True
    last_check_at: Optional[datetime] = None
    last_online_at: Optional[datetime] = None
    last_offline_at: Optional[datetime] = None
    check_interval_seconds: int = 30
    consecutive_failures: int = 0


class ConnectivityService:
    """
    Service for monitoring network connectivity.

    Runs periodic checks to detect when the application goes online/offline.
    Notifies registered callbacks when connectivity status changes.

    Usage:
        connectivity = ConnectivityService(check_interval=30)
        connectivity.on_status_change(lambda online: print(f"Online: {online}"))
        connectivity.start()
    """

    def __init__(
        self,
        check_interval: int = 30,
        health_endpoint: str = "http://localhost:5050/api/health",
        failure_threshold: int = 2,
        on_online: Optional[Callable[[], None]] = None,
        on_offline: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize the connectivity service.

        Args:
            check_interval: Seconds between connectivity checks (default 30).
            health_endpoint: URL to check for connectivity.
            failure_threshold: Consecutive failures before marking offline.
            on_online: Callback when connectivity is restored.
            on_offline: Callback when connectivity is lost.
        """
        self.check_interval = check_interval
        self.health_endpoint = health_endpoint
        self.failure_threshold = failure_threshold

        self._status = ConnectivityStatus(check_interval_seconds=check_interval)
        self._callbacks: List[Callable[[bool], None]] = []
        self._stop_flag = threading.Event()
        self._check_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Register initial callbacks
        if on_online:
            self._on_online = on_online
        else:
            self._on_online = None

        if on_offline:
            self._on_offline = on_offline
        else:
            self._on_offline = None

    @property
    def is_online(self) -> bool:
        """Check if currently online."""
        return self._status.is_online

    @property
    def status(self) -> ConnectivityStatus:
        """Get current connectivity status."""
        return self._status

    def on_status_change(self, callback: Callable[[bool], None]) -> None:
        """
        Register a callback for connectivity changes.

        Args:
            callback: Function to call with boolean (True = online).
        """
        with self._lock:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[bool], None]) -> None:
        """
        Remove a previously registered callback.

        Args:
            callback: The callback to remove.
        """
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def start(self) -> None:
        """Start the background connectivity check thread."""
        if self._check_thread and self._check_thread.is_alive():
            logger.warning("Connectivity service already running")
            return

        self._stop_flag.clear()
        self._check_thread = threading.Thread(
            target=self._check_loop, daemon=True, name="ConnectivityCheckThread"
        )
        self._check_thread.start()
        logger.info(f"Connectivity service started (interval: {self.check_interval}s)")

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the connectivity check thread.

        Args:
            timeout: Maximum time to wait for thread to finish.
        """
        logger.info("Stopping connectivity service...")
        self._stop_flag.set()

        if self._check_thread and self._check_thread.is_alive():
            self._check_thread.join(timeout=timeout)
            if self._check_thread.is_alive():
                logger.warning("Connectivity thread did not stop gracefully")

        logger.info("Connectivity service stopped")

    def check_now(self) -> bool:
        """
        Perform an immediate connectivity check.

        Returns:
            True if online, False if offline.
        """
        return self._perform_check()

    def _check_loop(self) -> None:
        """Main loop for periodic connectivity checks."""
        # Initial check
        self._perform_check()

        while not self._stop_flag.is_set():
            if self._stop_flag.wait(timeout=self.check_interval):
                break
            self._perform_check()

    def _perform_check(self) -> bool:
        """
        Perform a single connectivity check.

        Returns:
            True if online, False if offline.
        """
        now = datetime.now(timezone.utc)
        self._status.last_check_at = now

        is_connected = self._check_connectivity()

        if is_connected:
            self._status.consecutive_failures = 0
            was_offline = not self._status.is_online

            if was_offline:
                # Transitioning from offline to online
                self._status.is_online = True
                self._status.last_online_at = now
                logger.info("Connectivity restored")
                self._notify_change(True)
        else:
            self._status.consecutive_failures += 1

            if (
                self._status.is_online
                and self._status.consecutive_failures >= self.failure_threshold
            ):
                # Transitioning from online to offline
                self._status.is_online = False
                self._status.last_offline_at = now
                logger.warning(
                    f"Connectivity lost after {self._status.consecutive_failures} failures"
                )
                self._notify_change(False)

        return self._status.is_online

    def _check_connectivity(self) -> bool:
        """
        Check if we can reach the network.

        Tries the health endpoint first, then falls back to a TCP connect.

        Returns:
            True if connected, False otherwise.
        """
        # First try the backend health endpoint
        try:
            response = requests.get(self.health_endpoint, timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            pass

        # Audit MED-6 (2026-04-25): TCP connect to 1.1.1.1:53 plutôt que
        # gethostbyname() qui peut hang ≥ 10 s sur un /etc/resolv.conf
        # cassé (resolver timeout système). 3 s explicite côté socket.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(3)
            sock.connect(("1.1.1.1", 53))
            return True
        except (OSError, socket.timeout):
            return False
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _notify_change(self, is_online: bool) -> None:
        """
        Notify all registered callbacks of connectivity change.

        Args:
            is_online: New connectivity status.
        """
        # Call specific callbacks first
        if is_online and self._on_online:
            try:
                self._on_online()
            except Exception as e:
                logger.error(f"Error in on_online callback: {e}")

        if not is_online and self._on_offline:
            try:
                self._on_offline()
            except Exception as e:
                logger.error(f"Error in on_offline callback: {e}")

        # Call general callbacks
        with self._lock:
            for callback in self._callbacks:
                try:
                    callback(is_online)
                except Exception as e:
                    logger.error(f"Error in connectivity callback: {e}")


# Global connectivity service instance
_connectivity_service: Optional[ConnectivityService] = None


def get_connectivity_service() -> Optional[ConnectivityService]:
    """Get the global connectivity service instance."""
    return _connectivity_service


def init_connectivity_service(
    check_interval: int = 30, **kwargs
) -> ConnectivityService:
    """
    Initialize the global connectivity service.

    Args:
        check_interval: Seconds between connectivity checks.
        **kwargs: Additional arguments for ConnectivityService.

    Returns:
        The initialized ConnectivityService instance.
    """
    global _connectivity_service

    if _connectivity_service is not None:
        logger.warning(
            "Connectivity service already initialized, stopping existing instance"
        )
        _connectivity_service.stop()

    _connectivity_service = ConnectivityService(check_interval=check_interval, **kwargs)
    return _connectivity_service
