from __future__ import annotations

import os
import threading
import time


class RateGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._configured_rate = 0.0
        self._tokens = 0.0
        self._updated_at = time.monotonic()

    def allow(self) -> bool:
        rate_per_minute = float(os.getenv("LOAD_TARGET_DRAFTS_PER_MINUTE", "0") or "0")
        if rate_per_minute <= 0:
            return True

        burst = float(os.getenv("LOAD_DRAFT_RATE_BURST", "0") or "0")
        if burst <= 0:
            burst = max(1.0, min(rate_per_minute / 6.0, 50.0))

        now = time.monotonic()
        with self._lock:
            if rate_per_minute != self._configured_rate:
                self._configured_rate = rate_per_minute
                self._tokens = burst
                self._updated_at = now

            elapsed = max(0.0, now - self._updated_at)
            self._updated_at = now
            self._tokens = min(burst, self._tokens + elapsed * (rate_per_minute / 60.0))
            if self._tokens < 1.0:
                return False
            self._tokens -= 1.0
            return True
