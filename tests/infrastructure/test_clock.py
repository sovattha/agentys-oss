# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.infrastructure.clock."""

from datetime import datetime, timedelta
from app.infrastructure.clock import SystemClock, FakeClock, get_clock


# ============================================================================
# SystemClock
# ============================================================================

class TestSystemClock:
    def test_now_returns_datetime(self):
        clock = SystemClock()
        result = clock.now()
        assert isinstance(result, datetime)

    def test_now_is_recent(self):
        clock = SystemClock()
        before = datetime.now()
        result = clock.now()
        after = datetime.now()
        assert before <= result <= after

    def test_str(self):
        clock = SystemClock()
        s = str(clock)
        assert s.startswith("SystemClock(")

    def test_repr(self):
        clock = SystemClock()
        r = repr(clock)
        assert r.startswith("SystemClock(current=")


# ============================================================================
# FakeClock
# ============================================================================

class TestFakeClock:
    def test_returns_initial_time(self):
        t = datetime(2026, 1, 1, 12, 0, 0)
        clock = FakeClock(t)
        assert clock.now() == t

    def test_default_initial_time_is_now(self):
        before = datetime.now()
        clock = FakeClock()
        after = datetime.now()
        assert before <= clock.now() <= after

    def test_set_time(self):
        clock = FakeClock(datetime(2026, 1, 1))
        new_time = datetime(2026, 6, 15, 14, 30)
        clock.set_time(new_time)
        assert clock.now() == new_time

    def test_advance_by_hours(self):
        t = datetime(2026, 1, 1, 10, 0)
        clock = FakeClock(t)
        clock.advance_by(hours=2)
        assert clock.now() == datetime(2026, 1, 1, 12, 0)

    def test_advance_by_days(self):
        t = datetime(2026, 1, 1)
        clock = FakeClock(t)
        clock.advance_by(days=5)
        assert clock.now() == datetime(2026, 1, 6)

    def test_advance_by_minutes_and_seconds(self):
        t = datetime(2026, 1, 1, 10, 0, 0)
        clock = FakeClock(t)
        clock.advance_by(minutes=30, seconds=15)
        assert clock.now() == datetime(2026, 1, 1, 10, 30, 15)

    def test_advance_by_milliseconds(self):
        t = datetime(2026, 1, 1, 10, 0, 0)
        clock = FakeClock(t)
        clock.advance_by(milliseconds=500)
        expected = t + timedelta(milliseconds=500)
        assert clock.now() == expected

    def test_advance_by_delta(self):
        t = datetime(2026, 1, 1)
        clock = FakeClock(t)
        clock.advance_by_delta(timedelta(days=3, hours=6))
        assert clock.now() == datetime(2026, 1, 4, 6, 0)

    def test_reset(self):
        t = datetime(2026, 1, 1)
        clock = FakeClock(t)
        clock.advance_by(days=10)
        clock.reset()
        assert clock.now() == t

    def test_elapsed(self):
        t = datetime(2026, 1, 1)
        clock = FakeClock(t)
        clock.advance_by(hours=3)
        assert clock.elapsed() == timedelta(hours=3)

    def test_elapsed_zero_at_start(self):
        clock = FakeClock(datetime(2026, 1, 1))
        assert clock.elapsed() == timedelta(0)

    def test_str(self):
        t = datetime(2026, 3, 15, 14, 30, 0)
        clock = FakeClock(t)
        assert str(clock) == "FakeClock(2026-03-15 14:30:00)"

    def test_repr(self):
        t = datetime(2026, 3, 15, 14, 30, 0)
        clock = FakeClock(t)
        r = repr(clock)
        assert "current=" in r
        assert "initial=" in r

    def test_multiple_advances_accumulate(self):
        t = datetime(2026, 1, 1, 0, 0, 0)
        clock = FakeClock(t)
        clock.advance_by(hours=1)
        clock.advance_by(hours=2)
        clock.advance_by(minutes=30)
        assert clock.now() == datetime(2026, 1, 1, 3, 30, 0)


# ============================================================================
# get_clock factory
# ============================================================================

class TestGetClock:
    def test_returns_system_clock_by_default(self):
        clock = get_clock()
        assert isinstance(clock, SystemClock)

    def test_returns_fake_clock(self):
        clock = get_clock(use_fake=True)
        assert isinstance(clock, FakeClock)

    def test_fake_clock_with_initial_time(self):
        t = datetime(2026, 6, 1)
        clock = get_clock(use_fake=True, initial_time=t)
        assert isinstance(clock, FakeClock)
        assert clock.now() == t

    def test_system_clock_ignores_initial_time(self):
        clock = get_clock(use_fake=False, initial_time=datetime(2020, 1, 1))
        assert isinstance(clock, SystemClock)
