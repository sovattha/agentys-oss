"""Thread-safe token bucket for per-provider rate limiting.

Used by the bulk-job worker to keep our request rate under the published
provider quotas (Gmail ~250 quota units/user/sec, Microsoft Graph ~10k
req/10min, IMAP per-host idiosyncrasies). Each `_AccountQueue` owns one
`TokenBucket` instance; the worker calls `acquire()` immediately before
every provider call.

Design:
- `time.monotonic()` for elapsed-time math (immune to wall-clock jumps).
- A single `threading.Lock` — fine because contention is tiny: one
  acquire per provider call (~50 ms apart at most).
- `penalize(seconds)` drains the bucket and freezes refill until the
  pause expires. Called when an adapter raises a 429 with `Retry-After`.
- Capacity > rate so we tolerate small idle gaps without losing
  throughput on resume.

Returns `bool` from `acquire()` so callers can implement timeout-based
shutdown (e.g. drain on `Ctrl-C`).
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class TokenBucket:
    """Continuous-refill token bucket.

    Args:
        rate_per_sec: Tokens added per second (provider's safe ops/sec).
        capacity: Max tokens that can accumulate during idle periods.
            Use ~2× `rate_per_sec` for short-burst tolerance.
        name: Optional identifier surfaced in log lines.
    """

    __slots__ = (
        "_rate",
        "_capacity",
        "_tokens",
        "_last_refill",
        "_penalty_until",
        "_lock",
        "_name",
    )

    def __init__(
        self,
        rate_per_sec: float,
        capacity: int,
        *,
        name: str = "",
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError(f"rate_per_sec must be > 0, got {rate_per_sec}")
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        self._rate = float(rate_per_sec)
        self._capacity = int(capacity)
        # Start full so the first burst doesn't have to warm up.
        self._tokens: float = float(capacity)
        self._last_refill = time.monotonic()
        # `_penalty_until` is the monotonic timestamp before which refill
        # is paused. 0.0 means no active penalty.
        self._penalty_until: float = 0.0
        self._lock = threading.Lock()
        self._name = name or f"bucket@{rate_per_sec:.0f}/s"

    # ── internal helpers ────────────────────────────────────────────────
    def _refill_locked(self) -> None:
        now = time.monotonic()
        if self._penalty_until and now < self._penalty_until:
            # No refill while penalized; just bump the clock.
            self._last_refill = now
            return
        # First tick after a penalty expired: don't claim refill for the
        # frozen window (would dump a sudden burst the moment we resume).
        if self._penalty_until and now >= self._penalty_until:
            self._last_refill = max(self._last_refill, self._penalty_until)
            self._penalty_until = 0.0

        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        added = elapsed * self._rate
        if added > 0:
            self._tokens = min(self._capacity, self._tokens + added)
            self._last_refill = now

    # ── public API ──────────────────────────────────────────────────────
    def acquire(self, tokens: int = 1, timeout: float | None = None) -> bool:
        """Block until `tokens` are available or timeout expires.

        Returns True on success, False if the timeout elapsed first.
        Polls in 50 ms increments to keep wakeup latency tight without
        churning CPU.
        """
        if tokens <= 0:
            raise ValueError(f"tokens must be > 0, got {tokens}")
        if tokens > self._capacity:
            raise ValueError(
                f"tokens={tokens} exceeds bucket capacity={self._capacity}"
            )

        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                # How long until we have enough tokens (assuming no penalty)?
                deficit = tokens - self._tokens
                wait_for = deficit / self._rate
                if self._penalty_until:
                    wait_for = max(
                        wait_for, self._penalty_until - time.monotonic()
                    )

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait_for = min(wait_for, remaining)

            # Cap polling granularity at 50 ms so penalty expiry / shutdown
            # signals are honored quickly.
            time.sleep(min(0.05, max(wait_for, 0.005)))

    def penalize(self, seconds: float) -> None:
        """Drain the bucket and freeze refill for `seconds`.

        Idempotent: if an existing penalty already extends past the new
        deadline, the longer pause wins.
        """
        if seconds <= 0:
            return
        with self._lock:
            now = time.monotonic()
            new_until = now + seconds
            if new_until > self._penalty_until:
                self._penalty_until = new_until
            self._tokens = 0.0
            self._last_refill = now
        logger.info(
            "[bulk-rate] %s penalized for %.1fs (Retry-After honored)",
            self._name,
            seconds,
        )

    def snapshot(self) -> dict:
        """Cheap diagnostic snapshot (used by /api/bulk-jobs/_metrics)."""
        with self._lock:
            self._refill_locked()
            now = time.monotonic()
            penalty_remaining = max(0.0, self._penalty_until - now) if self._penalty_until else 0.0
            return {
                "name": self._name,
                "rate_per_sec": self._rate,
                "capacity": self._capacity,
                "tokens_available": round(self._tokens, 3),
                "penalty_remaining_s": round(penalty_remaining, 3),
            }


# ── Default per-provider configuration ────────────────────────────────
#
# These numbers are deliberately conservative. Hard provider ceilings
# are higher (Gmail allows ~50 modify ops/s before throttle, Outlook
# ~10) but a quiet headroom protects us against:
# - other code paths in Agentys also hitting the API (sync, classify…)
# - multiple bulk jobs queued for the same account
# - unexpected per-tenant quota reductions
#
# Tune via env vars only if you have telemetry showing under-utilization.
PROVIDER_RATE_LIMITS: dict[str, tuple[float, int]] = {
    # provider_kind → (rate_per_sec, capacity)
    "gmail": (30.0, 60),
    "outlook": (8.0, 16),
    "imap": (2.0, 4),
}


def make_bucket_for(provider_kind: str, account_label: str = "") -> TokenBucket:
    """Build a TokenBucket configured for `provider_kind`.

    Unknown providers get the most conservative IMAP profile rather than
    crashing — better to throttle aggressively than to discover a typo
    in production by hammering an unknown adapter.
    """
    rate, capacity = PROVIDER_RATE_LIMITS.get(
        provider_kind.lower(), PROVIDER_RATE_LIMITS["imap"]
    )
    name = f"{provider_kind}:{account_label}" if account_label else provider_kind
    return TokenBucket(rate, capacity, name=name)
