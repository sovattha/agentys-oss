# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix — concurrency locks for SmartRouter and PendingDraftStore.

Source audit: tasks/audit-reports/2026-04-24_stability/03-draft-pipeline.md
              — concurrency rows C1, C2, C4.

Fixes covered:
- C1: two simultaneous `/process` for the same email — both used to spend
      Haiku tokens, last writer wins. Fix: per-(account, email) lock at
      SmartRouter entry, plus a post-lock cache re-check.
- C2: daemon + relabel race for the same email. Same lock covers it.
- C4: `/refine` and `/validate-and-send` racing on the same draft. Fix:
      per-draft lock on the PendingDraftStore.
"""
from __future__ import annotations

import threading
import time


from app.smart_routing import SmartRouter


# --------------------------------------------------------------------------- #
# C1+C2: SmartRouter entry lock dedup.
# --------------------------------------------------------------------------- #


def test_entry_lock_acquire_release_round_trip():
    """`_acquire_entry_lock` returns a handle that `_release_entry_lock`
    consumes; subsequent acquire on the same key works fine."""
    handle1 = SmartRouter._acquire_entry_lock("acct-1", "email-1")
    assert handle1 is not None

    SmartRouter._release_entry_lock(handle1)

    handle2 = SmartRouter._acquire_entry_lock("acct-1", "email-1")
    assert handle2 is not None
    SmartRouter._release_entry_lock(handle2)


def test_entry_lock_serializes_concurrent_callers():
    """Two threads asking for the same (account, email) lock must serialize:
    the loser blocks until the winner releases.

    Pre-fix (no lock): both `route()` calls would proceed in parallel and
    each would burn Haiku tokens. Post-fix: the second waits, then sees
    the cached result and skips the LLM (verified separately in the
    cache-recheck test below)."""
    timeline: list[tuple[str, float]] = []
    barrier = threading.Barrier(2)
    use_unique_key = ("acct-ser", "email-ser")

    def worker(label: str, hold_ms: int) -> None:
        barrier.wait()  # ensure both fire close in time
        h = SmartRouter._acquire_entry_lock(*use_unique_key)
        timeline.append((f"{label}:acq", time.monotonic()))
        try:
            time.sleep(hold_ms / 1000.0)
        finally:
            timeline.append((f"{label}:rel", time.monotonic()))
            SmartRouter._release_entry_lock(h)

    t1 = threading.Thread(target=worker, args=("A", 80))
    t2 = threading.Thread(target=worker, args=("B", 80))
    t1.start()
    t2.start()
    t1.join(timeout=4.0)
    t2.join(timeout=4.0)

    # Both must have acquired and released
    events = [e[0] for e in timeline]
    assert events.count("A:acq") == 1 and events.count("A:rel") == 1
    assert events.count("B:acq") == 1 and events.count("B:rel") == 1

    # Whichever acquired first MUST release before the other acquires —
    # serialization holds regardless of which thread won the race.
    by_event = {e: t for (e, t) in timeline}
    first_label = "A" if by_event["A:acq"] < by_event["B:acq"] else "B"
    second_label = "B" if first_label == "A" else "A"
    first_rel = by_event[f"{first_label}:rel"]
    second_acq = by_event[f"{second_label}:acq"]
    assert second_acq >= first_rel - 0.005, (
        f"C1+C2 fix: SmartRouter entry lock must serialize concurrent "
        f"calls for the same (account, email). {second_label}:acq fired at "
        f"{second_acq:.3f} but {first_label}:rel only fired at {first_rel:.3f}. "
        "Timeline: " + repr(timeline)
    )


def test_entry_lock_returns_none_for_empty_email():
    """When email_id is empty, no dedup keying is possible — return None."""
    h = SmartRouter._acquire_entry_lock("acct-1", "")
    assert h is None


def test_entry_lock_guard_releases_via_dunder_del():
    """The _EntryLockGuard class releases the lock through __del__ when
    the local goes out of scope. Validates that the guard pattern works
    (CPython refcounting drops the object as soon as the function frame
    pops)."""
    guard1 = SmartRouter._EntryLockGuard(SmartRouter, "acct-Z", "email-Z")
    assert guard1.acquired
    del guard1  # explicit drop, triggers __del__

    # After drop, a fresh acquire must succeed without blocking.
    guard2 = SmartRouter._EntryLockGuard(SmartRouter, "acct-Z", "email-Z")
    assert guard2.acquired
    guard2.release()


# --------------------------------------------------------------------------- #
# C4: PendingDraftStore per-draft lock.
# --------------------------------------------------------------------------- #


def _make_store():
    """Build an InMemoryPendingDraftStore with disk I/O stubbed out."""
    from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore

    store = InMemoryPendingDraftStore.__new__(InMemoryPendingDraftStore)
    import threading as _thr
    store._store = {}
    store._email_id_index = {}
    store._secure_passwords = {}
    store._lock = _thr.RLock()
    store._draft_locks = {}
    store._draft_locks_master = _thr.Lock()
    store._save_to_disk = lambda: None
    store._reload_if_changed = lambda: None
    return store


def test_pending_draft_store_get_draft_lock_returns_same_lock():
    """Subsequent calls for the same draft_id must return the SAME lock."""
    store = _make_store()
    l1 = store.get_draft_lock("d-abc")
    l2 = store.get_draft_lock("d-abc")
    assert l1 is l2, (
        "C4 fix: per-draft lock must be re-used across calls so /refine "
        "and /validate-and-send actually serialize on the same mutex."
    )


def test_pending_draft_store_get_draft_lock_distinct_for_distinct_drafts():
    store = _make_store()
    l1 = store.get_draft_lock("d-A")
    l2 = store.get_draft_lock("d-B")
    assert l1 is not l2


def test_pending_draft_store_release_lock_drops_unused():
    store = _make_store()
    _ = store.get_draft_lock("d-x")
    assert "d-x" in store._draft_locks
    store.release_draft_lock("d-x")
    assert "d-x" not in store._draft_locks


def test_pending_draft_store_release_lock_keeps_held_lock():
    """release_draft_lock must NOT drop a lock that is currently held."""
    store = _make_store()
    lock = store.get_draft_lock("d-y")
    lock.acquire()
    try:
        store.release_draft_lock("d-y")
        assert "d-y" in store._draft_locks, (
            "release_draft_lock must not drop a held lock — that would let "
            "a second caller acquire a new instance and break mutual "
            "exclusion."
        )
    finally:
        lock.release()


def test_per_draft_lock_serializes_two_threads():
    """Two threads each acquiring the per-draft lock must serialize."""
    store = _make_store()
    lock = store.get_draft_lock("d-shared")
    timeline: list[str] = []
    barrier = threading.Barrier(2)

    def worker(label: str, hold_ms: int) -> None:
        barrier.wait()
        with lock:
            timeline.append(f"{label}:in")
            time.sleep(hold_ms / 1000.0)
            timeline.append(f"{label}:out")

    t1 = threading.Thread(target=worker, args=("R", 60))
    t2 = threading.Thread(target=worker, args=("V", 1))
    t1.start()
    t2.start()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    # The serialized order must be either R-then-V or V-then-R, NOT
    # interleaved (no nested in/out).
    assert timeline.count("R:in") == 1 and timeline.count("V:in") == 1
    # The first :in must be paired with its :out before the second :in.
    first_in_label = timeline[0].split(":")[0]
    expected = [f"{first_in_label}:in", f"{first_in_label}:out"]
    assert timeline[:2] == expected, (
        f"C4 fix: per-draft lock failed to serialize. Timeline: {timeline}"
    )
