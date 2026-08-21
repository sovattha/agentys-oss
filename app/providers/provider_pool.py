# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Connection pool for email providers.

Maintains a pool of authenticated provider connections to avoid
re-authentication overhead on each API request.

Usage:
    pool = ProviderPool.get_instance()
    provider = pool.get_or_create("account_1", lambda: create_gmail_provider())
"""

import logging
import socket
import threading
import time
from typing import Callable, Dict, Optional, Tuple

from app.interfaces.email_provider import EmailProvider

logger = logging.getLogger(__name__)


class ProviderPool:
    """
    Thread-safe pool of authenticated email providers.

    Maintains provider connections keyed by account_id, with automatic
    cleanup of idle connections and health checking.

    Attributes:
        max_idle_seconds: Maximum time a provider can be idle before eviction.
        check_health: If True, verify connection health before returning.
    """

    _instance: Optional["ProviderPool"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        max_idle_seconds: int = 300,
        check_health: bool = True,
    ):
        """
        Initialize the provider pool.

        Args:
            max_idle_seconds: Max idle time before connection cleanup (default 5 min).
                Aligné sur le TTL cache inbox (300s) pour éviter les reconnexions inutiles.
            check_health: Whether to check connection health before returning.
        """
        self._pool: Dict[str, Tuple[EmailProvider, float]] = {}  # account_id -> (provider, last_used)
        self._lock = threading.RLock()
        self._creation_locks: Dict[str, threading.Lock] = {}  # per-account creation locks
        self._creation_meta_lock = threading.Lock()  # protects _creation_locks dict
        self.max_idle_seconds = max_idle_seconds
        self.check_health = check_health

    @classmethod
    def get_instance(cls, **kwargs) -> "ProviderPool":
        """
        Get the singleton ProviderPool instance.

        Thread-safe lazy initialization.

        Args:
            **kwargs: Arguments passed to constructor on first creation.

        Returns:
            The global ProviderPool instance.
        """
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """
        Reset the singleton instance (useful for testing).
        """
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.clear()
                cls._instance = None

    def get_or_create(
        self,
        account_id: str,
        factory_fn: Callable[[], EmailProvider],
    ) -> EmailProvider:
        """
        Get an existing provider or create a new one.

        If a healthy provider exists in the pool for this account, returns it.
        Otherwise, creates a new provider using factory_fn, authenticates it,
        and adds it to the pool.

        Note: Health check is performed outside the lock to avoid blocking
        other pool operations during network calls.

        Args:
            account_id: Unique identifier for the account.
            factory_fn: Callable that creates a new provider instance.

        Returns:
            Authenticated EmailProvider ready for use.

        Raises:
            Exception: If provider creation or authentication fails.
        """
        # Step 1: Quick check under lock - get cached provider if exists
        cached_provider = None
        with self._lock:
            if account_id in self._pool:
                provider, _ = self._pool[account_id]
                # Optimistically update timestamp
                self._pool[account_id] = (provider, time.time())
                cached_provider = provider

        # Step 2: Health check OUTSIDE lock (avoids blocking on network)
        # Skip expensive IMAP health check if provider was used < 30s ago
        # (connections rarely go stale in 30s, and SELECT INBOX is costly)
        if cached_provider is not None:
            with self._lock:
                _, last_used = self._pool.get(account_id, (None, 0))
            recently_used = (time.time() - last_used) < 30.0
            if recently_used or self._is_healthy(cached_provider):
                logger.debug(f"Pool hit for account {account_id}")
                return cached_provider
            else:
                # Unhealthy - remove from pool
                with self._lock:
                    if account_id in self._pool:
                        logger.info(f"Removing unhealthy provider for account {account_id}")
                        del self._pool[account_id]

        # Step 3: Serialize creation per account — prevents multiple threads from
        # creating concurrent httplib2/IMAP connections (causes segfault on Windows)
        with self._creation_meta_lock:
            if account_id not in self._creation_locks:
                self._creation_locks[account_id] = threading.Lock()
            creation_lock = self._creation_locks[account_id]

        with creation_lock:
            # Re-check pool after acquiring lock (another thread may have created it)
            with self._lock:
                if account_id in self._pool:
                    provider, _ = self._pool[account_id]
                    self._pool[account_id] = (provider, time.time())
                    return provider

            logger.info(f"Creating new provider for account {account_id}")
            provider = factory_fn()

            if not provider.authenticate():
                raise Exception(f"Authentication failed for account {account_id}")

            with self._lock:
                self._pool[account_id] = (provider, time.time())

            return provider

    # Maximum time (seconds) for the IMAP health-check SELECT to complete.
    # Prevents the request thread from blocking indefinitely on a stale socket.
    _HEALTH_CHECK_TIMEOUT = 5

    def _is_healthy(self, provider: EmailProvider) -> bool:
        """
        Check if a provider connection is still healthy.

        For IMAP providers, performs a SELECT INBOX to verify the connection
        is synchronized (NOOP alone doesn't detect buffer desync issues).
        A 5-second socket timeout is applied to prevent blocking indefinitely.
        For API-based providers (Gmail, Outlook), always returns True
        as they handle re-auth internally.

        Args:
            provider: The provider to check.

        Returns:
            True if connection is healthy, False otherwise.
        """
        if not self.check_health:
            return True

        try:
            # Check for IMAP-style connection
            if hasattr(provider, '_connection') and provider._connection is not None:
                # Acquire the adapter's connection lock non-blockingly to avoid racing
                # with threads currently doing IMAP operations (would cause SSL internal error).
                conn_lock = getattr(provider, '_connection_lock', None)
                if conn_lock is not None and not conn_lock.acquire(blocking=False):
                    # Another thread is actively using this connection — skip health check,
                    # assume healthy to avoid the SSL race.
                    return True

                try:
                    conn = provider._connection
                    if conn is None:
                        return False

                    # Apply a socket timeout so the health check cannot block indefinitely
                    old_timeout = None
                    sock = None
                    if hasattr(conn, 'socket'):
                        try:
                            sock = conn.socket()
                            old_timeout = sock.gettimeout()
                            sock.settimeout(self._HEALTH_CHECK_TIMEOUT)
                        except Exception:
                            old_timeout = None
                            sock = None

                    try:
                        # SELECT INBOX detects buffer desync (NOOP doesn't)
                        # If there's corrupted data in buffer, SELECT will fail
                        folder = getattr(provider, 'folder', 'INBOX')
                        status, data = conn.select(folder)
                        if status != 'OK':
                            logger.warning(f"IMAP health check failed: SELECT returned {status}")
                            return False
                        return True
                    except (socket.timeout, TimeoutError, OSError) as e:
                        logger.warning(
                            f"[TIMEOUT] IMAP health check timed out after {self._HEALTH_CHECK_TIMEOUT}s: {e}"
                        )
                        return False
                    finally:
                        # Restore original socket timeout (reuse stored sock reference)
                        if old_timeout is not None and sock is not None:
                            try:
                                sock.settimeout(old_timeout)
                            except Exception:
                                pass
                finally:
                    if conn_lock is not None:
                        conn_lock.release()

            # API-based providers (Gmail, Outlook) handle reconnection internally
            return True

        except Exception as e:
            logger.warning(f"Provider health check failed: {e}")
            return False

    def remove(self, account_id: str) -> bool:
        """
        Remove a provider from the pool.

        Args:
            account_id: Account ID to remove.

        Returns:
            True if provider was removed, False if not found.
        """
        with self._lock:
            if account_id in self._pool:
                del self._pool[account_id]
                logger.info(f"Removed provider for account {account_id}")
                return True
            return False

    def clear(self) -> int:
        """
        Clear all providers from the pool.

        Returns:
            Number of providers cleared.
        """
        with self._lock:
            count = len(self._pool)
            self._pool.clear()
            logger.info(f"Cleared {count} providers from pool")
            return count

    def cleanup_idle(self) -> int:
        """
        Remove providers that have been idle too long.

        Should be called periodically (e.g., every 60 seconds).

        Returns:
            Number of providers removed.
        """
        now = time.time()
        removed = 0

        with self._lock:
            pool_size = len(self._pool)
            expired = [
                account_id
                for account_id, (_, last_used) in self._pool.items()
                if (now - last_used) > self.max_idle_seconds
            ]

            for account_id in expired:
                del self._pool[account_id]
                removed += 1

        if removed > 0:
            logger.info(f"Cleaned up {removed} idle providers")
        else:
            # S-13 fix: log even when nothing was removed so an operator
            # debugging "why is the pool growing forever" can see the
            # cleanup loop is firing. Was previously silent → looked dead.
            logger.debug(
                "Provider pool cleanup ran (pool_size=%d, max_idle=%ss, removed=0)",
                pool_size, self.max_idle_seconds,
            )

        return removed

    @property
    def size(self) -> int:
        """Current number of providers in the pool."""
        with self._lock:
            return len(self._pool)

    def stats(self) -> dict:
        """
        Get pool statistics.

        Returns:
            Dict with pool size, account IDs, and idle times.
        """
        now = time.time()
        with self._lock:
            return {
                "size": len(self._pool),
                "accounts": list(self._pool.keys()),
                "idle_times": {
                    account_id: round(now - last_used, 1)
                    for account_id, (_, last_used) in self._pool.items()
                },
                "max_idle_seconds": self.max_idle_seconds,
            }


# ============================================================================
# CLEANUP SCHEDULER
# ============================================================================

_cleanup_thread: Optional[threading.Thread] = None
_cleanup_stop_event: Optional[threading.Event] = None


def start_cleanup_scheduler(interval_seconds: int = 60) -> None:
    """
    Start a background thread that periodically cleans up idle connections.

    Should be called once at application startup.

    Args:
        interval_seconds: How often to run cleanup (default 60 seconds).
    """
    global _cleanup_thread, _cleanup_stop_event

    if _cleanup_thread is not None and _cleanup_thread.is_alive():
        logger.warning("Cleanup scheduler already running")
        return

    _cleanup_stop_event = threading.Event()

    def cleanup_loop():
        logger.info(f"Provider pool cleanup scheduler started (interval={interval_seconds}s)")
        while not _cleanup_stop_event.is_set():
            _cleanup_stop_event.wait(interval_seconds)
            if not _cleanup_stop_event.is_set():
                try:
                    pool = ProviderPool.get_instance()
                    pool.cleanup_idle()
                except Exception as e:
                    logger.error(f"Cleanup scheduler error: {e}")
        logger.info("Provider pool cleanup scheduler stopped")

    _cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True, name="ProviderPoolCleanup")
    _cleanup_thread.start()


def stop_cleanup_scheduler() -> None:
    """
    Stop the cleanup scheduler thread.

    Should be called at application shutdown.
    """
    global _cleanup_thread, _cleanup_stop_event

    if _cleanup_stop_event is not None:
        _cleanup_stop_event.set()

    if _cleanup_thread is not None:
        _cleanup_thread.join(timeout=5)
        _cleanup_thread = None

    _cleanup_stop_event = None
    logger.info("Cleanup scheduler shutdown complete")
