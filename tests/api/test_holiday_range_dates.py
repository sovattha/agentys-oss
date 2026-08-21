# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression (chaos audit 2026-06-02, timezone lens).

The /public-holidays visible-range filter took ``start_dt.date()`` / ``end_dt.date()``
in UTC. The FE sends local-midnight bounds as Z-suffixed UTC (``toISOString``),
so for east-of-UTC users those land at e.g. 22:00 the PREVIOUS UTC day — the
half-open window then shifted back a day and a holiday on the LAST visible grid
day was dropped. `_holiday_range_dates` normalizes to the requested tz's date.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.api.calendar_routes import _holiday_range_dates


def test_east_of_utc_keeps_local_calendar_day():
    # Paris (UTC+2) week of 2026-06-07: local midnight -> 2026-06-06T22:00Z;
    # periodEnd (+7d) -> 2026-06-13T22:00Z.
    start_dt = datetime(2026, 6, 6, 22, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 6, 13, 22, 0, tzinfo=timezone.utc)
    start_date, end_date = _holiday_range_dates(start_dt, end_dt, "Europe/Paris")
    # Window must be [2026-06-07, 2026-06-14) so a holiday on the last visible
    # grid day (Sat 2026-06-13) is INCLUDED, and 2026-06-06 is excluded.
    assert start_date == date(2026, 6, 7)
    assert end_date == date(2026, 6, 14)


def test_west_of_utc_unaffected():
    # Montreal (UTC-4): local midnight 2026-06-07 -> 2026-06-07T04:00Z; the date
    # is already correct (no day shift west of UTC).
    start_dt = datetime(2026, 6, 7, 4, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 6, 14, 4, 0, tzinfo=timezone.utc)
    start_date, end_date = _holiday_range_dates(start_dt, end_dt, "America/Montreal")
    assert start_date == date(2026, 6, 7)
    assert end_date == date(2026, 6, 14)


def test_no_or_invalid_tz_falls_back_to_utc_date():
    start_dt = datetime(2026, 6, 6, 22, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 6, 13, 22, 0, tzinfo=timezone.utc)
    for tz in (None, "", "Not/AZone"):
        start_date, end_date = _holiday_range_dates(start_dt, end_dt, tz)
        assert start_date == date(2026, 6, 6)
        assert end_date == date(2026, 6, 13)
