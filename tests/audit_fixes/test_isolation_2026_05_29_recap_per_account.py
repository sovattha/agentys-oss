# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 — monthly recap mixed ALL tenants' metrics.

Bug: ``RecapTracker`` (reply-times / inbox-zero / active-days) and
``DraftQualityTracker.get_month_activity`` (tiers / drafts / features) were
process-global. Tenant A's monthly recap reported tenant B's behaviour.

Fix: both accept an ``account_id``. With it, data is isolated per tenant;
without it (``None`` = Tauri desktop / dashboard) the legacy global behaviour
is preserved byte-for-byte.

Run: pytest tests/audit_fixes/test_isolation_2026_05_29_recap_per_account.py -v
"""

from __future__ import annotations

from datetime import datetime, date, timezone

import pytest


# --------------------------------------------------------------------------- #
# RecapTracker — per-account isolation
# --------------------------------------------------------------------------- #

@pytest.fixture
def tracker(tmp_path):
    from app.services.recap_tracker import RecapTracker
    return RecapTracker(tracking_file=tmp_path / "recap" / "daily_tracking.json")


def _rt(received_hours_ago_iso, mins, account_id, tracker):
    received = "2026-05-24T08:00:00+00:00"
    validated = datetime(2026, 5, 24, 8, mins, 0, tzinfo=timezone.utc)
    tracker.record_reply_time(received, validated_at=validated, account_id=account_id)


def test_reply_times_isolated_between_accounts(tracker):
    """A records a 10-min reply, B records 45-min. Each only sees their own."""
    _rt(None, 10, account_id=1, tracker=tracker)
    _rt(None, 45, account_id=2, tracker=tracker)
    month = date.today().strftime("%Y-%m")

    a = tracker.get_month_data(month, account_id=1)
    b = tracker.get_month_data(month, account_id=2)
    assert a["reply_times"] == [10.0]
    assert b["reply_times"] == [45.0]
    # No cross-contamination
    assert 45.0 not in a["reply_times"]
    assert 10.0 not in b["reply_times"]


def test_inbox_zero_and_activity_isolated(tracker):
    tracker.record_inbox_zero(account_id=1)
    tracker.record_activity(account_id=1)
    month = date.today().strftime("%Y-%m")
    # Account 2 has recorded nothing → empty
    b = tracker.get_month_data(month, account_id=2)
    assert b["inbox_zero_dates"] == []
    assert b["active_dates"] == []
    a = tracker.get_month_data(month, account_id=1)
    assert len(a["inbox_zero_dates"]) == 1
    assert len(a["active_dates"]) == 1


def test_account_none_is_flat_backcompat(tracker):
    """account_id=None preserves the legacy flat top-level structure."""
    _rt(None, 12, account_id=None, tracker=tracker)
    raw = tracker.get_all_data()  # None → flat dict, legacy shape
    assert "reply_times_minutes" in raw
    assert "accounts" not in raw  # nothing namespaced when only None used
    month = date.today().strftime("%Y-%m")
    assert tracker.get_month_data(month)["reply_times"] == [12.0]
    # A scoped account does NOT see the None/legacy bucket
    assert tracker.get_month_data(month, account_id=5)["reply_times"] == []


# --------------------------------------------------------------------------- #
# DraftQualityTracker — per-account month activity
# --------------------------------------------------------------------------- #

@pytest.fixture
def quality(tmp_path):
    from app.draft_quality_tracker import DraftQualityTracker
    return DraftQualityTracker(db_path=str(tmp_path / "quality.db"))


def test_month_activity_scopes_send_events(quality):
    """Sends tagged account '1' vs '2' must not bleed into each other's recap."""
    month = date.today().strftime("%Y-%m")
    quality.record_send("e1", tier="simple", account_id="1")
    quality.record_send("e2", tier="complex", account_id="1")
    quality.record_send("e3", tier="standard", account_id="2")

    a = quality.get_month_activity(month, account_id="1")
    b = quality.get_month_activity(month, account_id="2")
    assert a["drafts"] == 2
    assert b["drafts"] == 1
    assert a["tiers"]["complex"] == 1
    assert b["tiers"]["complex"] == 0
    assert b["tiers"]["standard"] == 1


def test_month_activity_skips_global_feature_events_when_scoped(quality):
    """Legacy feature_events without account_id must be excluded when scoped."""
    month = date.today().strftime("%Y-%m")
    quality.record_feature("compose_ai", count=5)  # global, unattributable
    quality.record_send("e1", tier="simple", account_id="9")

    scoped = quality.get_month_activity(month, account_id="9")
    # compose_ai is a feature event with no owner → 0 under a scoped recap
    assert scoped.get("features", {}).get("compose_ai", 0) == 0

    # Unscoped dashboard path still sees the global feature counts
    unscoped = quality.get_month_activity(month, account_id=None)
    assert unscoped["features"]["compose_ai"] == 5


def test_month_activity_includes_owned_feature_events_only(quality):
    """New feature events carry account_id and must stay tenant-scoped."""
    month = date.today().strftime("%Y-%m")
    quality.record_feature("compose_ai", count=2, account_id="9")
    quality.record_feature("compose_ai", count=3, account_id="10")
    quality.record_feature("refine_ai", count=1, account_id="9")

    a = quality.get_month_activity(month, account_id="9")
    b = quality.get_month_activity(month, account_id="10")

    assert a["features"]["compose_ai"] == 2
    assert a["features"]["refine_ai"] == 1
    assert b["features"]["compose_ai"] == 3
    assert b["features"]["refine_ai"] == 0
    assert quality.get_month_activity(month)["features"]["compose_ai"] == 5


def test_legacy_blank_account_rows_visible_to_all(quality):
    """Pre-isolation sends (account_id='') stay counted per the F-02 contract."""
    month = date.today().strftime("%Y-%m")
    quality.record_send("legacy", tier="simple", account_id="")
    scoped = quality.get_month_activity(month, account_id="123")
    assert scoped["drafts"] == 1  # legacy '' row included


def test_get_activity_scopes_live_indicator(quality):
    """The live week/today indicator (/stats/activity) must not sum other
    tenants' sends. account_id=None stays global (Tauri desktop)."""
    quality.record_send("e1", tier="simple", account_id="1")
    quality.record_send("e2", tier="complex", account_id="1")
    quality.record_send("e3", tier="standard", account_id="2")

    a = quality.get_activity(account_id="1")
    b = quality.get_activity(account_id="2")
    assert a["week"]["drafts"] == 2
    assert b["week"]["drafts"] == 1
    # Unscoped (desktop single-user) sees all three.
    assert quality.get_activity()["week"]["drafts"] == 3


# --------------------------------------------------------------------------- #
# recap_service best records — per account
# --------------------------------------------------------------------------- #

def test_best_records_isolated_per_account(tmp_path, monkeypatch):
    import app.services.recap_service as rs
    monkeypatch.setattr(rs, "_BEST_RECORDS_FILE", tmp_path / "best_records.json")

    rs._save_best_records({"inbox_zero_days": 9}, account_id=1)
    rs._save_best_records({"inbox_zero_days": 2}, account_id=2)

    assert rs._load_best_records(account_id=1) == {"inbox_zero_days": 9}
    assert rs._load_best_records(account_id=2) == {"inbox_zero_days": 2}
    # Account 3 has no record → empty, NOT account 1's 9-day streak
    assert rs._load_best_records(account_id=3) == {}
