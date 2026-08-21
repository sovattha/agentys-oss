#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Daily check: how many days until the Azure App Registration "Agentys"
Client Secret expires?

Issue #577 item 2. Without this monitoring, the next outage is "100% green
up to D-day, then 100% red, no warning, user finds out by phone." The
secret expires on 2026-09-10 (cf. memory/outlook-oauth-setup.md). Run this
in the nightly workflow; an exit code != 0 triggers the paired
oauth-expiry-alert job which opens a deduped auto-sentinelle issue.

Source of truth for the expiry date — env var first, hardcoded default
fallback. The default exists so a forgotten env var on a fresh runner
doesn't silently disable the safety net; update it AND the env var when
the secret is rotated.

Exit codes:
    0  OK             secret expires in > 30 days
    1  WARN           secret expires in <= 30 days but not yet expired
    2  CRITICAL       secret already expired

Phase B (refresh-token age across accounts) is deliberately out of scope:
it requires production DB access from the runner, which the nightly
workflow does not currently have. Track in a follow-up run if we wire
that up.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date as _date

# Source-of-truth fallback. Keep in sync with Azure Portal and rotate
# at the same time as MICROSOFT_CLIENT_SECRET / the Railway env var.
_DEFAULT_EXPIRY_DATE = _date(2026, 9, 10)
_ENV_VAR_NAME = "MICROSOFT_CLIENT_SECRET_EXPIRY_DATE"
_WARN_THRESHOLD_DAYS = 30


def resolve_expiry_date() -> _date:
    """Return the configured expiry date.

    Reads ``MICROSOFT_CLIENT_SECRET_EXPIRY_DATE`` (ISO ``YYYY-MM-DD``).
    Falls back to the hardcoded default on missing or malformed values
    so a bad env var doesn't silently disable the cron — better a
    slightly-stale check than no check at all.
    """
    raw = os.environ.get(_ENV_VAR_NAME, "").strip()
    if not raw:
        return _DEFAULT_EXPIRY_DATE
    try:
        return _date.fromisoformat(raw)
    except ValueError:
        print(
            f"[oauth-expiry] WARNING: {_ENV_VAR_NAME}={raw!r} is not a valid "
            f"ISO date — falling back to hardcoded default "
            f"{_DEFAULT_EXPIRY_DATE.isoformat()}",
            file=sys.stderr,
        )
        return _DEFAULT_EXPIRY_DATE


def classify_expiry(days_remaining: int) -> int:
    """Pure function: ``days_remaining`` -> exit code.

    Boundary: ``days_remaining == 30`` returns 1 (warn) — we want to
    surface the warning *at* the 30-day mark, not the day after.
    """
    if days_remaining < 0:
        return 2
    if days_remaining <= _WARN_THRESHOLD_DAYS:
        return 1
    return 0


def _format_summary(expiry: _date, today: _date, days_remaining: int) -> str:
    if days_remaining < 0:
        status = f"CRITICAL — secret EXPIRED {-days_remaining} day(s) ago"
    elif days_remaining <= _WARN_THRESHOLD_DAYS:
        status = f"WARN — secret expires in {days_remaining} day(s)"
    else:
        status = f"OK — secret expires in {days_remaining} day(s)"
    return (
        f"[oauth-expiry] today={today.isoformat()} "
        f"expiry={expiry.isoformat()} {status}"
    )


def main(argv: list[str] | None = None) -> int:
    """Main entry. ``argv`` defaults to sys.argv[1:] in production; tests
    pass an explicit list (typically empty) so pytest's own argv does
    not bleed into argparse and crash the cron simulation.
    """
    parser = argparse.ArgumentParser(
        description="Check Azure Client Secret expiry vs today; exit 0/1/2."
    )
    parser.parse_args(argv if argv is not None else sys.argv[1:])

    expiry = resolve_expiry_date()
    today = _date.today()
    days_remaining = (expiry - today).days
    print(_format_summary(expiry, today, days_remaining))
    return classify_expiry(days_remaining)


if __name__ == "__main__":
    sys.exit(main())
