# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression (chaos audit 2026-06-02, timezone lens).

`extract_deadline` resolved RELATIVE / end-of-period tokens ("today" /
"tomorrow" / "demain" / EOD…) against the UTC wall-clock, so the resulting
deadline landed on the WRONG calendar day for non-UTC users (a west-of-UTC user
in the evening got "today" = tomorrow; every east-of-UTC user had EOD roll into
the next local day). It now anchors those tokens to the user's local day.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.quicksteps.deadline_extractor import extract_deadline


class TestRelativeTokensResolveInUserTimezone:
    def test_today_west_of_utc_uses_local_day(self):
        # LA user (UTC-7 PDT) at 21:00 local on 2026-06-01 == 04:00Z on 06-02.
        now_utc = datetime(2026, 6, 2, 4, 0, tzinfo=timezone.utc)
        dl = extract_deadline(
            body="please respond by today",
            now=now_utc,
            user_timezone="America/Los_Angeles",
        )
        assert dl is not None
        # "today" for the LA user is June 1 LOCAL — not June 2 (the UTC day).
        assert dl.astimezone(ZoneInfo("America/Los_Angeles")).date() == date(2026, 6, 1)

    def test_tomorrow_east_of_utc_uses_local_day(self):
        # Paris user (UTC+2 CEST) at 10:00 local on 2026-06-01 == 08:00Z.
        now_utc = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
        dl = extract_deadline(
            body="reply by tomorrow",
            now=now_utc,
            user_timezone="Europe/Paris",
        )
        assert dl is not None
        # tomorrow == June 2 local (the UTC-wall-clock bug produced June 3).
        assert dl.astimezone(ZoneInfo("Europe/Paris")).date() == date(2026, 6, 2)

    def test_no_timezone_preserves_utc_behaviour(self):
        # Backward-compatible: with no tz, resolve against UTC end-of-day as before.
        now_utc = datetime(2026, 6, 2, 4, 0, tzinfo=timezone.utc)
        dl = extract_deadline(body="please respond by today", now=now_utc)
        assert dl is not None
        assert dl.astimezone(timezone.utc).date() == date(2026, 6, 2)
        assert dl.hour == 23 and dl.minute == 59

    def test_absolute_date_unaffected_by_timezone(self):
        # An explicit date is parsed as-is; the tz only governs relative tokens.
        now_utc = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
        dl = extract_deadline(
            body="payment due 15 juin 2026",
            now=now_utc,
            user_timezone="America/Los_Angeles",
        )
        assert dl is not None
        assert dl.astimezone(timezone.utc).date() == date(2026, 6, 15)
