# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Smart Meeting Scheduler.

Finds available time slots for multiple attendees by querying
provider FreeBusy APIs and scanning for free windows.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)


def find_available_slots(
    freebusy_data: dict,
    start: datetime,
    end: datetime,
    duration_minutes: int = 60,
    work_hours_only: bool = True,
    work_start: int = 8,
    work_end: int = 17,
    lunch_start: int = 12,
    lunch_end: int = 13,
    max_slots: int = 5,
    tz_offset_minutes: int = 0,
    extra_busy: Optional[List[dict]] = None,
) -> List[dict]:
    """
    Find available meeting slots for all attendees.

    Args:
        freebusy_data: Result from CalendarPort.get_freebusy()
            Format: { "calendars": { email: [{ start, end }] } }
        start: Start of search window.
        end: End of search window.
        duration_minutes: Required meeting duration in minutes.
        work_hours_only: If True, only suggest slots within work hours.
        work_start: Work hours start (0-23), in user's LOCAL time.
        work_end: Work hours end (0-23), in user's LOCAL time.
        lunch_start: Lunch break start hour (0-23), in user's LOCAL time. -1 to disable.
        lunch_end: Lunch break end hour (0-23), in user's LOCAL time.
        max_slots: Maximum number of slots to return.
        tz_offset_minutes: Timezone offset from JS getTimezoneOffset()
            (positive = west of UTC, e.g. 300 for UTC-5).
        extra_busy: Additional busy blocks (e.g. local Deep Work)
            as list of { start: ISO string, end: ISO string }.

    Returns:
        List of { start: ISO string, end: ISO string } dicts.
    """
    tz_delta = timedelta(minutes=-tz_offset_minutes)

    # Merge all busy blocks into a single sorted list
    all_busy: List[tuple[datetime, datetime]] = []
    calendars = freebusy_data.get("calendars", {})
    logger.info(f"[SmartScheduler] FreeBusy calendars: {len(calendars)}")
    for email, blocks in calendars.items():
        logger.info(f"[SmartScheduler]   {email}: {len(blocks)} busy blocks")
        for block in blocks:
            try:
                b_start = _parse_dt(block["start"])
                b_end = _parse_dt(block["end"])
                all_busy.append((b_start, b_end))
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping invalid busy block: {e}")

    # Inject extra busy blocks (local Deep Work / calendar events from frontend)
    freebusy_count = len(all_busy)
    if extra_busy:
        logger.info(f"[SmartScheduler] Extra busy blocks from frontend: {len(extra_busy)}")
        for block in extra_busy:
            try:
                b_start = _parse_dt(block["start"])
                b_end = _parse_dt(block["end"])
                all_busy.append((b_start, b_end))
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping invalid extra busy block: {e}")
    else:
        logger.info("[SmartScheduler] No extra busy blocks from frontend")

    logger.info(f"[SmartScheduler] Total busy blocks: {len(all_busy)} (freebusy={freebusy_count}, extra={len(all_busy) - freebusy_count})")

    # Sort by start time and merge overlapping
    all_busy.sort(key=lambda x: x[0])
    merged: List[tuple[datetime, datetime]] = []
    for b_start, b_end in all_busy:
        if merged and b_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b_end))
        else:
            merged.append((b_start, b_end))

    logger.info(f"[SmartScheduler] Merged busy blocks: {len(merged)}")

    # Scan for available slots in 30-minute increments (clean :00 / :30 slots)
    duration = timedelta(minutes=duration_minutes)
    slots: List[dict] = []
    current = _snap_to_half_hour(start)

    while current + duration <= end and len(slots) < max_slots:
        slot_end = current + duration

        # Check work hours constraint (in user's local time)
        if work_hours_only:
            local_current = current + tz_delta
            local_slot_end = slot_end + tz_delta

            if local_current.weekday() >= 5:  # Skip weekends
                current = _next_workday_local(local_current, work_start, tz_delta)
                continue
            if local_current.hour < work_start:
                # Advance to work_start in local time, convert back to UTC
                local_start = local_current.replace(hour=work_start, minute=0, second=0)
                current = local_start - tz_delta
                continue
            if local_slot_end.hour > work_end or (local_slot_end.hour == work_end and local_slot_end.minute > 0):
                # Move to next day's work start in local time
                local_next = local_current + timedelta(days=1)
                local_next = local_next.replace(hour=work_start, minute=0, second=0)
                current = local_next - tz_delta
                continue

            # Skip lunch break
            if lunch_start >= 0 and lunch_end > lunch_start:
                local_start_min = local_current.hour * 60 + local_current.minute
                local_end_min = local_slot_end.hour * 60 + local_slot_end.minute
                lunch_start_min = lunch_start * 60
                lunch_end_min = lunch_end * 60
                # Slot overlaps with lunch if it starts before lunch ends and ends after lunch starts
                if local_start_min < lunch_end_min and local_end_min > lunch_start_min:
                    # Skip to lunch end
                    local_after_lunch = local_current.replace(hour=lunch_end, minute=0, second=0)
                    current = local_after_lunch - tz_delta
                    continue

        # Check if slot conflicts with any busy block
        is_free = True
        for b_start, b_end in merged:
            if current < b_end and slot_end > b_start:
                # Conflict — skip past this busy block
                current = b_end
                is_free = False
                break

        if is_free:
            slots.append({
                "start": current.isoformat(),
                "end": slot_end.isoformat(),
            })
            # Move past this slot to find next available
            current = slot_end
        else:
            # current was already advanced past the busy block
            # Snap to next 30-min boundary (:00 or :30)
            current = _snap_to_half_hour(current)

    return slots


def _snap_to_half_hour(dt: datetime) -> datetime:
    """Snap datetime forward to the next :00 or :30 boundary."""
    minute = dt.minute
    if minute == 0 or minute == 30:
        return dt.replace(second=0, microsecond=0)
    if minute < 30:
        return dt.replace(minute=30, second=0, microsecond=0)
    # minute > 30: advance to next hour
    return (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def _parse_dt(value: str) -> datetime:
    """Parse ISO datetime string."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _next_workday(dt: datetime, work_start: int) -> datetime:
    """Advance to the next workday at work_start hour."""
    next_day = dt + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.replace(hour=work_start, minute=0, second=0, microsecond=0)


def _next_workday_local(local_dt: datetime, work_start: int, tz_delta: timedelta) -> datetime:
    """Advance to the next workday at work_start in local time, return UTC."""
    next_day = local_dt + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    local_start = next_day.replace(hour=work_start, minute=0, second=0, microsecond=0)
    return local_start - tz_delta
