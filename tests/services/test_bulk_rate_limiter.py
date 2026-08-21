# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""L1 unit tests for the bulk-job TokenBucket.

Pure-function-ish — no DB, no threads beyond the bucket itself. Goal is
to nail the rate-math edges that codex tends to flag: refill window,
penalty interaction, capacity cap.

The bucket uses `time.monotonic()` internally; we don't try to freeze
it, we just measure observed throughput across short windows. To keep
the suite fast (<1s total), the rate values used here are intentionally
high — production uses 30/s for Gmail.
"""
from __future__ import annotations

import threading
import time

import pytest

from app.services.bulk_jobs.rate_limiter import (
    PROVIDER_RATE_LIMITS,
    TokenBucket,
    make_bucket_for,
)


# ── Construction guard rails ───────────────────────────────────────────
def test_constructor_rejects_zero_rate() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate_per_sec=0, capacity=1)


def test_constructor_rejects_zero_capacity() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate_per_sec=1.0, capacity=0)


def test_acquire_rejects_more_than_capacity() -> None:
    bucket = TokenBucket(rate_per_sec=10, capacity=5, name="t")
    with pytest.raises(ValueError):
        bucket.acquire(tokens=10)


# ── Burst tolerance and steady state ───────────────────────────────────
def test_initial_burst_drains_capacity_immediately() -> None:
    """A fresh bucket should hand out `capacity` tokens with zero wait."""
    bucket = TokenBucket(rate_per_sec=50, capacity=5, name="t")
    start = time.monotonic()
    for _ in range(5):
        assert bucket.acquire() is True
    elapsed = time.monotonic() - start
    assert elapsed < 0.05, f"initial burst took {elapsed*1000:.1f} ms"


def test_steady_state_throughput_matches_rate() -> None:
    """Over a window large enough to hide jitter, observed rate ≈ configured rate."""
    rate = 100.0
    bucket = TokenBucket(rate_per_sec=rate, capacity=10, name="t")
    # Drain the initial burst so the rest is rate-limited.
    for _ in range(10):
        bucket.acquire()
    n = 30
    start = time.monotonic()
    for _ in range(n):
        bucket.acquire()
    elapsed = time.monotonic() - start
    observed = n / elapsed
    # Allow ±50 % slack: the kernel's polling granularity (50 ms) and
    # CI noise can both push the observed rate around. We're guarding
    # against gross errors (10× too fast or 10× too slow), not building
    # a precision benchmark.
    assert observed <= rate * 1.5, f"observed {observed:.1f}/s exceeds {rate}/s"
    assert observed >= rate * 0.5, f"observed {observed:.1f}/s far below {rate}/s"


# ── penalize() semantics ───────────────────────────────────────────────
def test_penalize_blocks_acquire_until_window_passes() -> None:
    """A penalty drains the bucket and freezes refill for `seconds`."""
    bucket = TokenBucket(rate_per_sec=1000, capacity=10, name="t")
    bucket.penalize(0.2)
    # Right after penalize, no tokens should be available.
    start = time.monotonic()
    assert bucket.acquire(timeout=2.0) is True
    waited = time.monotonic() - start
    assert waited >= 0.18, f"acquire returned in {waited*1000:.1f} ms — penalty not honored"


def test_penalize_extends_existing_penalty_only_if_longer() -> None:
    """Two penalties in a row keep the longer deadline (idempotent)."""
    bucket = TokenBucket(rate_per_sec=1000, capacity=10, name="t")
    bucket.penalize(0.5)
    deadline_after_first = bucket.snapshot()["penalty_remaining_s"]
    bucket.penalize(0.05)  # shorter — must NOT shorten the active pause
    deadline_after_second = bucket.snapshot()["penalty_remaining_s"]
    # Allow a few-ms tick between the two snapshots.
    assert deadline_after_second >= deadline_after_first - 0.05


def test_acquire_timeout_returns_false() -> None:
    """If the timeout expires before tokens arrive, acquire returns False."""
    bucket = TokenBucket(rate_per_sec=1.0, capacity=1, name="t")
    bucket.acquire()  # drain
    assert bucket.acquire(timeout=0.1) is False


# ── snapshot() ──────────────────────────────────────────────────────────
def test_snapshot_returns_diagnostic_dict() -> None:
    bucket = TokenBucket(rate_per_sec=10.0, capacity=20, name="probe")
    snap = bucket.snapshot()
    assert snap["name"] == "probe"
    assert snap["rate_per_sec"] == 10.0
    assert snap["capacity"] == 20
    assert 0 <= snap["tokens_available"] <= 20
    assert snap["penalty_remaining_s"] == 0.0


# ── make_bucket_for() ──────────────────────────────────────────────────
def test_make_bucket_for_known_providers() -> None:
    for kind in ("gmail", "outlook", "imap"):
        bucket = make_bucket_for(kind, account_label="42")
        snap = bucket.snapshot()
        assert snap["rate_per_sec"] == PROVIDER_RATE_LIMITS[kind][0]
        assert snap["capacity"] == PROVIDER_RATE_LIMITS[kind][1]
        assert "42" in snap["name"]


def test_make_bucket_for_unknown_falls_back_to_imap_profile() -> None:
    """Unknown providers must NOT crash — they get the conservative profile."""
    bucket = make_bucket_for("nonexistent_provider")
    snap = bucket.snapshot()
    assert snap["rate_per_sec"] == PROVIDER_RATE_LIMITS["imap"][0]
    assert snap["capacity"] == PROVIDER_RATE_LIMITS["imap"][1]


# ── thread-safety smoke ────────────────────────────────────────────────
def test_concurrent_acquires_never_exceed_rate() -> None:
    """Eight threads pounding on the bucket can't exceed its quota."""
    rate = 200.0
    bucket = TokenBucket(rate_per_sec=rate, capacity=10, name="t")

    counter = [0]
    counter_lock = threading.Lock()
    stop = threading.Event()

    def worker() -> None:
        while not stop.is_set():
            if bucket.acquire(timeout=0.1):
                with counter_lock:
                    counter[0] += 1

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
    for t in threads:
        t.start()
    time.sleep(0.5)
    stop.set()
    for t in threads:
        t.join(timeout=1.0)

    # Rate × duration + initial capacity, with 60 % headroom for jitter.
    upper_bound = int(rate * 0.5 + 10) * 16 // 10
    assert counter[0] <= upper_bound, (
        f"threads acquired {counter[0]} tokens in 0.5s, expected ≤ {upper_bound}"
    )
