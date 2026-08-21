# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.infrastructure.rate_limiter."""

import pytest
import time
from app.infrastructure.rate_limiter import (
    RateLimitExceededError,
    RateLimitStats,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
)


# ============================================================================
# RateLimitExceededError
# ============================================================================

class TestRateLimitExceededError:
    def test_error_attributes(self):
        err = RateLimitExceededError("test_limiter", 5.0)
        assert err.limiter_name == "test_limiter"
        assert err.wait_time == 5.0

    def test_error_message(self):
        err = RateLimitExceededError("api", 2.5)
        assert "api" in str(err)
        assert "2.5" in str(err)

    def test_inherits_from_exception(self):
        err = RateLimitExceededError("test", 1.0)
        assert isinstance(err, Exception)


# ============================================================================
# RateLimitStats
# ============================================================================

class TestRateLimitStats:
    def test_default_values(self):
        stats = RateLimitStats()
        assert stats.total_requests == 0
        assert stats.allowed_requests == 0
        assert stats.rejected_requests == 0
        assert stats.total_wait_time == 0.0
        assert stats.current_rate == 0.0


# ============================================================================
# SlidingWindowRateLimiter
# ============================================================================

class TestSlidingWindowRateLimiter:
    def test_acquire_within_limit(self):
        limiter = SlidingWindowRateLimiter("test", max_requests=5, window_seconds=60, blocking=False)
        assert limiter.acquire() is True
        assert limiter.stats.allowed_requests == 1

    def test_acquire_multiple_within_limit(self):
        limiter = SlidingWindowRateLimiter("test", max_requests=3, window_seconds=60, blocking=False)
        for _ in range(3):
            assert limiter.acquire() is True
        assert limiter.stats.allowed_requests == 3

    def test_acquire_exceeds_limit_non_blocking_raises(self):
        limiter = SlidingWindowRateLimiter("test", max_requests=2, window_seconds=60, blocking=False)
        limiter.acquire()
        limiter.acquire()
        with pytest.raises(RateLimitExceededError) as exc_info:
            limiter.acquire()
        assert exc_info.value.limiter_name == "test"

    def test_acquire_count_parameter(self):
        limiter = SlidingWindowRateLimiter("test", max_requests=5, window_seconds=60, blocking=False)
        assert limiter.acquire(count=3) is True
        assert limiter.stats.allowed_requests == 3

    def test_acquire_count_exceeds_raises(self):
        limiter = SlidingWindowRateLimiter("test", max_requests=2, window_seconds=60, blocking=False)
        with pytest.raises(RateLimitExceededError):
            limiter.acquire(count=3)

    def test_reset_clears_state(self):
        limiter = SlidingWindowRateLimiter("test", max_requests=2, window_seconds=60, blocking=False)
        limiter.acquire()
        limiter.acquire()
        limiter.reset()
        # After reset, should be able to acquire again
        assert limiter.acquire() is True

    def test_stats_tracking(self):
        limiter = SlidingWindowRateLimiter("test", max_requests=2, window_seconds=60, blocking=False)
        limiter.acquire()
        limiter.acquire()
        try:
            limiter.acquire()
        except RateLimitExceededError:
            pass
        stats = limiter.stats
        assert stats.total_requests == 3
        assert stats.allowed_requests == 2
        assert stats.rejected_requests == 1

    def test_window_expiry(self):
        """Requests should expire after window_seconds."""
        limiter = SlidingWindowRateLimiter("test", max_requests=1, window_seconds=0.1, blocking=False)
        limiter.acquire()
        time.sleep(0.15)
        # After window expires, should be able to acquire
        assert limiter.acquire() is True

    def test_name_stored(self):
        limiter = SlidingWindowRateLimiter("my_limiter", max_requests=10, window_seconds=60)
        assert limiter.name == "my_limiter"


# ============================================================================
# TokenBucketRateLimiter
# ============================================================================

class TestTokenBucketRateLimiter:
    def test_acquire_within_capacity(self):
        limiter = TokenBucketRateLimiter("test", tokens_per_second=10, max_tokens=5, blocking=False)
        assert limiter.acquire() is True

    def test_acquire_drains_tokens(self):
        limiter = TokenBucketRateLimiter("test", tokens_per_second=0.01, max_tokens=2, blocking=False)
        assert limiter.acquire() is True
        assert limiter.acquire() is True
        with pytest.raises(RateLimitExceededError):
            limiter.acquire()

    def test_acquire_multiple_tokens(self):
        limiter = TokenBucketRateLimiter("test", tokens_per_second=0.01, max_tokens=5, blocking=False)
        assert limiter.acquire(tokens=3) is True
        with pytest.raises(RateLimitExceededError):
            limiter.acquire(tokens=3)

    def test_refill_over_time(self):
        limiter = TokenBucketRateLimiter("test", tokens_per_second=100, max_tokens=5, blocking=False)
        # Drain all tokens
        limiter.acquire(tokens=5)
        # Wait a bit for refill
        time.sleep(0.1)
        # Should have refilled some tokens
        assert limiter.acquire() is True

    def test_reset(self):
        limiter = TokenBucketRateLimiter("test", tokens_per_second=0, max_tokens=3, blocking=False)
        limiter.acquire(tokens=3)
        limiter.reset()
        assert limiter.acquire(tokens=3) is True

    def test_stats(self):
        limiter = TokenBucketRateLimiter("test", tokens_per_second=0.01, max_tokens=1, blocking=False)
        limiter.acquire()
        try:
            limiter.acquire()
        except RateLimitExceededError:
            pass
        stats = limiter.stats
        assert stats.total_requests == 2
        assert stats.allowed_requests == 1
        assert stats.rejected_requests == 1

    def test_non_blocking_error_has_wait_time(self):
        limiter = TokenBucketRateLimiter("test", tokens_per_second=1, max_tokens=1, blocking=False)
        limiter.acquire()
        with pytest.raises(RateLimitExceededError) as exc_info:
            limiter.acquire()
        assert exc_info.value.wait_time > 0
