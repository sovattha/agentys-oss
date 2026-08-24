# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests unitaires pour app.draft_quality_tracker."""


import pytest

from app.draft_quality_tracker import DraftQualityTracker


@pytest.fixture
def tracker(tmp_path):
    """Crée un DraftQualityTracker avec une DB temporaire."""
    db_path = str(tmp_path / "test_quality.db")
    return DraftQualityTracker(db_path=db_path)


# ── record_send ──────────────────────────────────────────────────────────────


class TestRecordSend:
    def test_record_send_basic(self, tracker):
        tracker.record_send(email_id="e1", contact="alice@test.com", tier="simple")
        stats = tracker.get_stats(days=1)
        assert stats["total_sent"] == 1

    def test_record_send_unmodified(self, tracker):
        tracker.record_send(email_id="e1", sent_unmodified=True)
        stats = tracker.get_stats(days=1)
        assert stats["sent_unmodified"] == 1
        assert stats["unmodified_rate"] == 100.0

    def test_record_send_with_edit_ratio(self, tracker):
        tracker.record_send(email_id="e1", edit_ratio=0.3)
        stats = tracker.get_stats(days=1)
        assert stats["avg_edit_ratio"] == 0.3

    def test_record_send_multiple(self, tracker):
        tracker.record_send(email_id="e1", sent_unmodified=True)
        tracker.record_send(email_id="e2", sent_unmodified=False)
        tracker.record_send(email_id="e3", sent_unmodified=True)
        stats = tracker.get_stats(days=1)
        assert stats["total_sent"] == 3
        assert stats["sent_unmodified"] == 2
        assert stats["unmodified_rate"] == pytest.approx(66.7, abs=0.1)


# ── record_feature ───────────────────────────────────────────────────────────


class TestRecordFeature:
    def test_record_known_feature(self, tracker):
        tracker.record_feature("compose_ai")
        # Should not raise
        activity = tracker.get_activity()
        assert activity["week"]["features"]["compose_ai"] >= 0

    def test_record_unknown_feature_ignored(self, tracker):
        # Should log warning but not crash
        tracker.record_feature("nonexistent_feature")


# ── record_interaction ───────────────────────────────────────────────────────


class TestRecordInteraction:
    def test_record_interaction_basic(self, tracker):
        tracker.record_interaction(
            email_id="e1",
            contact="bob@test.com",
            action="reply",
            time_spent_sec=30.0,
            sent_length=150,
        )
        avg = tracker.get_contact_avg_length("bob@test.com")
        # Need at least 2 interactions for avg
        assert avg is None

    def test_record_interaction_avg_length_with_enough_data(self, tracker):
        tracker.record_interaction("e1", "bob@test.com", "reply", sent_length=100)
        tracker.record_interaction("e2", "bob@test.com", "reply", sent_length=200)
        avg = tracker.get_contact_avg_length("bob@test.com")
        assert avg == 150


# ── get_top_contacts ─────────────────────────────────────────────────────────


class TestGetTopContacts:
    def test_empty_returns_empty(self, tracker):
        assert tracker.get_top_contacts() == []

    def test_returns_contacts_sorted_by_volume(self, tracker):
        for i in range(5):
            tracker.record_send(email_id=f"e{i}", contact="frequent@test.com")
        for i in range(2):
            tracker.record_send(email_id=f"r{i}", contact="rare@test.com")

        contacts = tracker.get_top_contacts()
        assert len(contacts) == 2
        assert contacts[0]["contact"] == "frequent@test.com"
        assert contacts[0]["total"] == 5
        assert contacts[1]["total"] == 2


# ── get_contact_cc_patterns ──────────────────────────────────────────────────


class TestContactCcPatterns:
    def test_empty_returns_empty(self, tracker):
        assert tracker.get_contact_cc_patterns("unknown@test.com") == []

    def test_returns_frequent_cc(self, tracker):
        for _ in range(3):
            tracker.record_interaction(
                "e1", "boss@co.com", "reply", cc_added="assistant@co.com"
            )
        patterns = tracker.get_contact_cc_patterns("boss@co.com")
        assert "assistant@co.com" in patterns


# ── get_ignored_senders ──────────────────────────────────────────────────────


class TestGetIgnoredSenders:
    def test_empty_returns_empty(self, tracker):
        assert tracker.get_ignored_senders() == []

    def test_returns_ignored_senders(self, tracker):
        for i in range(3):
            tracker.record_interaction(f"e{i}", "spam@test.com", "ignored")

        ignored = tracker.get_ignored_senders(min_ignored=2)
        assert len(ignored) == 1
        assert ignored[0]["contact"] == "spam@test.com"
        assert ignored[0]["count"] == 3


# ── get_contact_edit_stats ───────────────────────────────────────────────────


class TestContactEditStats:
    def test_no_data_returns_none(self, tracker):
        assert tracker.get_contact_edit_stats("unknown@test.com") is None

    def test_returns_stats(self, tracker):
        tracker.record_send("e1", contact="alice@test.com", edit_ratio=0.2)
        tracker.record_send("e2", contact="alice@test.com", edit_ratio=0.4)
        stats = tracker.get_contact_edit_stats("alice@test.com")
        assert stats is not None
        assert stats["count"] == 2
        assert stats["avg_edit_ratio"] == pytest.approx(0.3, abs=0.01)


# ── get_stats ────────────────────────────────────────────────────────────────


class TestGetStats:
    def test_empty_stats(self, tracker):
        stats = tracker.get_stats()
        assert stats["total_sent"] == 0
        assert stats["unmodified_rate"] == 0
        assert stats["by_intent"] == {}
        assert stats["by_tier"] == {}
        assert stats["daily"] == []

    def test_by_intent(self, tracker):
        tracker.record_send("e1", intent="reply", sent_unmodified=True)
        tracker.record_send("e2", intent="reply", sent_unmodified=False)
        tracker.record_send("e3", intent="forward")
        stats = tracker.get_stats(days=1)
        assert "reply" in stats["by_intent"]
        assert stats["by_intent"]["reply"]["total"] == 2
        assert stats["by_intent"]["reply"]["unmodified"] == 1

    def test_by_tier(self, tracker):
        tracker.record_send("e1", tier="simple", sent_unmodified=True)
        tracker.record_send("e2", tier="complex")
        stats = tracker.get_stats(days=1)
        assert "simple" in stats["by_tier"]
        assert "complex" in stats["by_tier"]

    def test_daily_trend(self, tracker):
        tracker.record_send("e1")
        stats = tracker.get_stats(days=1)
        assert len(stats["daily"]) >= 1


# ── get_activity ─────────────────────────────────────────────────────────────


class TestGetActivity:
    def test_empty_activity(self, tracker):
        activity = tracker.get_activity()
        assert "week" in activity
        assert "today" in activity
        assert activity["week"]["drafts"] == 0
        assert activity["today"]["time_saved_min"] == 0

    def test_activity_counts_drafts(self, tracker):
        tracker.record_send("e1", tier="simple")
        tracker.record_send("e2", tier="standard")
        activity = tracker.get_activity()
        assert activity["today"]["drafts"] == 2
        assert activity["today"]["tiers"]["simple"] == 1
        assert activity["today"]["tiers"]["standard"] == 1

    def test_activity_time_saved(self, tracker):
        tracker.record_send("e1", tier="simple")  # 1.2 min
        tracker.record_send("e2", tier="complex")  # 6 min
        # auto-label / auto-archive events are recorded independently from sends
        tracker.record_feature("auto_label", count=5)  # 5 * 0.25 = 1.25 min
        tracker.record_feature("auto_archive_action", count=3)  # 3 * 0.17 = 0.51 min
        activity = tracker.get_activity()
        time_saved = activity["today"]["time_saved_min"]
        # drafts (1.2 + 6) + label (1.25) + archive (0.51) ≈ 8.96 min
        assert time_saved > 8
        # archives/labels must come from feature events, not from draft count
        assert activity["today"]["labels"] == 5
        assert activity["today"]["archives"] == 3


# ── get_month_activity ───────────────────────────────────────────────────────


class TestGetMonthActivity:
    def test_month_activity_empty(self, tracker):
        result = tracker.get_month_activity("2025-01")
        assert result["drafts"] == 0

    def test_month_activity_december_boundary(self, tracker):
        # December should go to next year January
        result = tracker.get_month_activity("2025-12")
        assert result["drafts"] == 0


# ── _empty_activity ──────────────────────────────────────────────────────────


class TestEmptyActivity:
    def test_structure(self):
        empty = DraftQualityTracker._empty_activity()
        assert empty["drafts"] == 0
        assert empty["time_saved_min"] == 0
        assert "tiers" in empty
        assert "features" in empty
        assert "time_breakdown" in empty


# ── _TIME_SAVED ──────────────────────────────────────────────────────────────


class TestTimeSaved:
    def test_all_time_saved_values_are_numeric(self):
        for feature, value in DraftQualityTracker._TIME_SAVED.items():
            assert isinstance(value, (int, float)), f"{feature} has non-numeric value"

    def test_known_features_present(self):
        # Sprint (Deep Focus) mode was retired in 69bdc1c0 and the
        # `deep_focus` aggregate split into deep_work_min (concentration
        # duration, tracked but worth 0) and deep_work_emails (interruption
        # save per blocked notification).
        expected = {"simple", "standard", "complex", "followup", "archive", "label",
                    "compose_ai", "refine_ai", "auto_reply", "attachment_reminder",
                    "deep_work_min", "deep_work_emails", "shortcut", "smart_schedule"}
        assert expected.issubset(set(DraftQualityTracker._TIME_SAVED.keys()))
