# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Comprehensive unit tests for DraftQualityTracker.

Tests cover:
- DB initialization and table creation
- record_send and retrieval
- record_feature with valid and invalid features
- record_interaction
- get_top_contacts with various data
- get_contact_avg_length
- get_contact_cc_patterns
- get_ignored_senders
- get_contact_edit_stats
- get_stats
- get_activity and time-saving calculations
- Edge cases: empty DB, no matching data, etc.
"""

# CRITICAL: Set environment variables BEFORE any imports
import os
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
os.environ.setdefault("LLM_PROVIDER", "ollama")

# Now safe to import test libraries and the module
import pytest
from datetime import datetime, timedelta

from app import draft_quality_tracker as draft_quality_tracker_module
from app.draft_quality_tracker import DraftQualityTracker


@pytest.fixture
def tracker(tmp_path):
    """Create a fresh DraftQualityTracker instance with temp database."""
    db_path = str(tmp_path / "test_draft_quality.db")
    tracker_instance = DraftQualityTracker(db_path=db_path)
    yield tracker_instance
    # Cleanup is automatic via tmp_path


@pytest.fixture
def tracker_with_data(tracker):
    """Populate tracker with sample data."""
    # Record some send events
    tracker.record_send("email1", "alice@example.com", "reply", "simple", sent_unmodified=True, edit_ratio=0.0, account_id="user1")
    tracker.record_send("email2", "alice@example.com", "reply", "standard", sent_unmodified=False, edit_ratio=0.15, account_id="user1")
    tracker.record_send("email3", "bob@example.com", "followup", "complex", sent_unmodified=True, edit_ratio=0.0, account_id="user1")
    tracker.record_send("email4", "bob@example.com", "reply", "simple", sent_unmodified=False, edit_ratio=0.25, account_id="user2")
    tracker.record_send("email5", "charlie@example.com", "reply", "standard", sent_unmodified=True, edit_ratio=0.0)

    # Record feature events
    tracker.record_feature("compose_ai", 2)
    tracker.record_feature("attachment_reminder", 1)
    # `deep_focus` was retired in 69bdc1c0 — use deep_work_min instead.
    tracker.record_feature("deep_work_min", 3)

    # Record interactions
    tracker.record_interaction("email1", "alice@example.com", "reply", time_spent_sec=120, sent_length=250, cc_added="", account_id="user1")
    tracker.record_interaction("email2", "alice@example.com", "reply", time_spent_sec=180, sent_length=350, cc_added="manager@example.com", account_id="user1")
    tracker.record_interaction("email3", "bob@example.com", "reply", time_spent_sec=150, sent_length=200, cc_added="", account_id="user1")
    tracker.record_interaction("email4", "bob@example.com", "ignored", time_spent_sec=0, account_id="user2")
    tracker.record_interaction("email5", "charlie@example.com", "reply", time_spent_sec=90, sent_length=180, cc_added="cc@example.com")

    return tracker


# ==================== DB Initialization Tests ====================

class TestDBInitialization:
    """Test database initialization and table creation."""

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_db_creation(self):
        """Test that database file is created."""
        import tempfile
        import shutil
        tmp_dir = tempfile.mkdtemp()
        try:
            db_path = os.path.join(tmp_dir, "test.db")
            DraftQualityTracker(db_path=db_path)
            assert os.path.exists(db_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_default_db_path_uses_agentys_data_dir(self, monkeypatch, tmp_path):
        """Railway sets AGENTYS_DATA_DIR without AGENTYS_DB_PATH."""
        monkeypatch.delenv("AGENTYS_DB_PATH", raising=False)
        monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))

        expected = str(tmp_path / "draft_quality.db")
        assert draft_quality_tracker_module._default_db_path() == expected

        tracker = DraftQualityTracker()
        assert tracker._db_path == expected
        assert os.path.exists(expected)

    def test_default_db_path_prefers_agentys_db_path(self, monkeypatch, tmp_path):
        """AGENTYS_DB_PATH remains the primary source when provided."""
        monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "agentys.db"))
        monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path / "data"))

        assert draft_quality_tracker_module._default_db_path() == str(tmp_path / "draft_quality.db")

    def test_send_events_table_creation(self, tracker):
        """Test that send_events table is created."""
        with tracker._get_conn() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='send_events'"
            )
            assert cursor.fetchone() is not None

    def test_feature_events_table_creation(self, tracker):
        """Test that feature_events table is created."""
        with tracker._get_conn() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='feature_events'"
            )
            assert cursor.fetchone() is not None

    def test_email_interactions_table_creation(self, tracker):
        """Test that email_interactions table is created."""
        with tracker._get_conn() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='email_interactions'"
            )
            assert cursor.fetchone() is not None

    def test_send_events_indexes(self, tracker):
        """Test that indexes are created on send_events."""
        with tracker._get_conn() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_send_events_date'"
            )
            assert cursor.fetchone() is not None

    def test_feature_events_indexes(self, tracker):
        """Test that indexes are created on feature_events."""
        with tracker._get_conn() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_feature_events_date'"
            )
            assert cursor.fetchone() is not None
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_feature_events_account_date'"
            )
            assert cursor.fetchone() is not None

    def test_email_interactions_indexes(self, tracker):
        """Test that indexes are created on email_interactions."""
        with tracker._get_conn() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_email_interactions_contact'"
            )
            assert cursor.fetchone() is not None

    def test_account_id_column_added(self, tracker):
        """Test that account_id column exists (via migration)."""
        with tracker._get_conn() as conn:
            cursor = conn.execute("PRAGMA table_info(send_events)")
            columns = [row[1] for row in cursor.fetchall()]
            assert "account_id" in columns
            cursor = conn.execute("PRAGMA table_info(feature_events)")
            columns = [row[1] for row in cursor.fetchall()]
            assert "account_id" in columns

    def test_send_events_table_structure(self, tracker):
        """Test send_events table has all required columns."""
        with tracker._get_conn() as conn:
            cursor = conn.execute("PRAGMA table_info(send_events)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            required = ["email_id", "contact", "intent", "tier", "sent_unmodified", "edit_ratio", "account_id"]
            for col in required:
                assert col in columns, f"Column {col} missing from send_events"


# ==================== record_send Tests ====================

class TestRecordSend:
    """Test record_send method."""

    def test_record_send_simple(self, tracker):
        """Test basic send recording."""
        tracker.record_send("email1", "alice@example.com", "reply", "simple", sent_unmodified=True, edit_ratio=0.0)

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM send_events WHERE email_id='email1'").fetchone()
            assert row is not None
            assert row["contact"] == "alice@example.com"
            assert row["sent_unmodified"] == 1

    def test_record_send_unmodified_false(self, tracker):
        """Test that sent_unmodified=False converts to 0."""
        tracker.record_send("email2", "bob@example.com", "reply", "standard", sent_unmodified=False, edit_ratio=0.25)

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM send_events WHERE email_id='email2'").fetchone()
            assert row["sent_unmodified"] == 0
            assert row["edit_ratio"] == 0.25

    def test_record_send_with_account_id(self, tracker):
        """Test recording send with account_id."""
        tracker.record_send("email3", "charlie@example.com", "reply", "complex", sent_unmodified=True, account_id="user1")

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM send_events WHERE email_id='email3'").fetchone()
            assert row["account_id"] == "user1"

    def test_record_send_defaults(self, tracker):
        """Test that defaults are applied."""
        tracker.record_send("email4")

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM send_events WHERE email_id='email4'").fetchone()
            assert row["contact"] == ""
            assert row["intent"] == ""
            assert row["tier"] == ""
            assert row["sent_unmodified"] == 0
            assert row["edit_ratio"] == 0.0

    def test_record_send_edit_ratio(self, tracker):
        """Test various edit_ratio values."""
        tracker.record_send("email5", "test@example.com", edit_ratio=0.5)

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM send_events WHERE email_id='email5'").fetchone()
            assert row["edit_ratio"] == 0.5

    def test_record_send_multiple(self, tracker):
        """Test recording multiple sends."""
        for i in range(5):
            tracker.record_send(f"email{i}", f"contact{i}@example.com")

        with tracker._get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM send_events").fetchone()["cnt"]
            assert count == 5

    def test_record_send_timestamp(self, tracker):
        """Test that created_at is set automatically."""
        tracker.record_send("email6", "test@example.com")

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT created_at FROM send_events WHERE email_id='email6'").fetchone()
            assert row["created_at"] is not None


# ==================== record_feature Tests ====================

class TestRecordFeature:
    """Test record_feature method."""

    def test_record_valid_feature(self, tracker):
        """Test recording a valid feature."""
        tracker.record_feature("compose_ai", 1)

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM feature_events WHERE feature='compose_ai'").fetchone()
            assert row is not None
            assert row["count"] == 1

    def test_record_feature_count(self, tracker):
        """Test recording feature with count > 1."""
        # `deep_focus` was renamed to `deep_work_min` in 69bdc1c0 (Sprint
        # mode removal). Pick any still-valid _TIME_SAVED key for the
        # count-aggregation assertion.
        tracker.record_feature("deep_work_min", 5)

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM feature_events WHERE feature='deep_work_min'").fetchone()
            assert row["count"] == 5

    def test_record_feature_with_account_id(self, tracker):
        """Test recording a feature scoped to an account."""
        tracker.record_feature("compose_ai", 1, account_id="user1")

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM feature_events WHERE feature='compose_ai'").fetchone()
            assert row["account_id"] == "user1"

    def test_record_feature_invalid(self, tracker):
        """Test that invalid features are rejected."""
        # Record invalid feature
        tracker.record_feature("invalid_feature", 1)

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM feature_events WHERE feature='invalid_feature'").fetchone()
            assert row is None  # Should not be recorded

    def test_record_all_valid_features(self, tracker):
        """Test recording all valid features from _TIME_SAVED dict."""
        valid_features = tracker._TIME_SAVED.keys()

        for feature in valid_features:
            tracker.record_feature(feature, 1)

        with tracker._get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM feature_events").fetchone()["cnt"]
            assert count == len(valid_features)

    def test_record_feature_default_count(self, tracker):
        """Test that default count is 1."""
        tracker.record_feature("attachment_reminder")

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM feature_events WHERE feature='attachment_reminder'").fetchone()
            assert row["count"] == 1

    def test_record_feature_multiple_same(self, tracker):
        """Test recording same feature multiple times creates multiple rows."""
        tracker.record_feature("shortcut", 1)
        tracker.record_feature("shortcut", 1)

        with tracker._get_conn() as conn:
            rows = conn.execute("SELECT * FROM feature_events WHERE feature='shortcut'").fetchall()
            assert len(rows) == 2


# ==================== record_interaction Tests ====================

class TestRecordInteraction:
    """Test record_interaction method."""

    def test_record_interaction_reply(self, tracker):
        """Test recording a reply interaction."""
        tracker.record_interaction("email1", "alice@example.com", "reply", time_spent_sec=120, sent_length=250)

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM email_interactions WHERE email_id='email1'").fetchone()
            assert row is not None
            assert row["action"] == "reply"
            assert row["time_spent_sec"] == 120
            assert row["sent_length"] == 250

    def test_record_interaction_ignored(self, tracker):
        """Test recording an ignored interaction."""
        tracker.record_interaction("email2", "bob@example.com", "ignored")

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM email_interactions WHERE email_id='email2'").fetchone()
            assert row["action"] == "ignored"

    def test_record_interaction_with_cc(self, tracker):
        """Test recording interaction with CC address."""
        tracker.record_interaction("email3", "charlie@example.com", "reply", cc_added="manager@example.com")

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM email_interactions WHERE email_id='email3'").fetchone()
            assert row["cc_added"] == "manager@example.com"

    def test_record_interaction_with_account_id(self, tracker):
        """Test recording interaction with account_id."""
        tracker.record_interaction("email4", "dave@example.com", "reply", account_id="user1")

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM email_interactions WHERE email_id='email4'").fetchone()
            assert row["account_id"] == "user1"

    def test_record_interaction_defaults(self, tracker):
        """Test interaction defaults."""
        tracker.record_interaction("email5", "eve@example.com", "reply")

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM email_interactions WHERE email_id='email5'").fetchone()
            assert row["time_spent_sec"] == 0
            assert row["sent_length"] == 0
            assert row["cc_added"] == ""
            assert row["metadata"] == "{}"

    def test_record_interaction_with_metadata(self, tracker):
        """Test recording interaction with metadata."""
        tracker.record_interaction("email6", "frank@example.com", "reply", metadata='{"source": "api"}')

        with tracker._get_conn() as conn:
            row = conn.execute("SELECT * FROM email_interactions WHERE email_id='email6'").fetchone()
            assert row["metadata"] == '{"source": "api"}'

    def test_record_multiple_interactions(self, tracker):
        """Test recording multiple interactions."""
        for i in range(5):
            tracker.record_interaction(f"email{i}", f"contact{i}@example.com", "reply")

        with tracker._get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM email_interactions").fetchone()["cnt"]
            assert count == 5


# ==================== get_top_contacts Tests ====================

class TestGetTopContacts:
    """Test get_top_contacts method."""

    def test_get_top_contacts_empty(self, tracker):
        """Test get_top_contacts on empty database."""
        result = tracker.get_top_contacts()
        assert result == []

    def test_get_top_contacts_single(self, tracker_with_data):
        """Test getting top contacts with populated data."""
        result = tracker_with_data.get_top_contacts(limit=10)
        assert len(result) > 0
        assert "contact" in result[0]
        assert "total" in result[0]
        assert "unmodified" in result[0]
        assert "avg_edit_ratio" in result[0]

    def test_get_top_contacts_sorted_by_volume(self, tracker_with_data):
        """Test that contacts are sorted by send volume."""
        result = tracker_with_data.get_top_contacts(limit=10)

        for i in range(len(result) - 1):
            assert result[i]["total"] >= result[i + 1]["total"]

    def test_get_top_contacts_limit(self, tracker_with_data):
        """Test limit parameter."""
        result = tracker_with_data.get_top_contacts(limit=2)
        assert len(result) <= 2

    def test_get_top_contacts_excludes_empty_contact(self, tracker):
        """Test that empty contact strings are excluded."""
        tracker.record_send("email1", "", "reply", "simple")
        tracker.record_send("email2", "", "reply", "simple")
        tracker.record_send("email3", "alice@example.com", "reply", "simple")

        result = tracker.get_top_contacts()

        for contact in result:
            assert contact["contact"] != ""

    def test_get_top_contacts_by_account(self, tracker_with_data):
        """Test filtering by account_id."""
        result = tracker_with_data.get_top_contacts(account_id="user1")

        # All results should be from user1's data
        assert len(result) > 0

    def test_get_top_contacts_days_filter(self, tracker):
        """Test days parameter filters old data."""
        # Record an old send
        tracker.record_send("old_email", "old@example.com", "reply", "simple")

        # Mock old timestamp by inserting directly
        with tracker._get_conn() as conn:
            old_date = (datetime.now() - timedelta(days=100)).isoformat()
            conn.execute(
                "UPDATE send_events SET created_at = ? WHERE email_id = 'old_email'",
                (old_date,)
            )

        # Query with 30-day window should not include old email
        result = tracker.get_top_contacts(days=30)
        contacts = [c["contact"] for c in result]
        assert "old@example.com" not in contacts

    def test_get_top_contacts_unmodified_count(self, tracker_with_data):
        """Test that unmodified counts are accurate."""
        result = tracker_with_data.get_top_contacts()

        for contact in result:
            assert contact["unmodified"] <= contact["total"]

    def test_get_top_contacts_avg_edit_ratio(self, tracker_with_data):
        """Test that avg_edit_ratio is calculated."""
        result = tracker_with_data.get_top_contacts()

        for contact in result:
            assert 0 <= contact["avg_edit_ratio"] <= 1


# ==================== get_contact_avg_length Tests ====================

class TestGetContactAvgLength:
    """Test get_contact_avg_length method."""

    def test_get_contact_avg_length_empty(self, tracker):
        """Test on contact with no interactions."""
        result = tracker.get_contact_avg_length("nonexistent@example.com")
        assert result is None

    def test_get_contact_avg_length_single(self, tracker):
        """Test with single reply (should return None, needs >= 2)."""
        tracker.record_interaction("email1", "alice@example.com", "reply", sent_length=250)
        result = tracker.get_contact_avg_length("alice@example.com")
        assert result is None  # Needs at least 2 replies

    def test_get_contact_avg_length_multiple(self, tracker):
        """Test with multiple replies."""
        tracker.record_interaction("email1", "bob@example.com", "reply", sent_length=200)
        tracker.record_interaction("email2", "bob@example.com", "reply", sent_length=300)
        tracker.record_interaction("email3", "bob@example.com", "reply", sent_length=400)

        result = tracker.get_contact_avg_length("bob@example.com")
        assert result is not None
        assert result == 300  # Average of 200, 300, 400

    def test_get_contact_avg_length_ignores_non_replies(self, tracker):
        """Test that non-reply actions are ignored."""
        tracker.record_interaction("email1", "charlie@example.com", "reply", sent_length=200)
        tracker.record_interaction("email2", "charlie@example.com", "ignored", sent_length=500)
        tracker.record_interaction("email3", "charlie@example.com", "reply", sent_length=300)

        result = tracker.get_contact_avg_length("charlie@example.com")
        assert result == 250  # Average of 200, 300 (ignoring the ignored one)

    def test_get_contact_avg_length_ignores_zero_length(self, tracker):
        """Test that zero length interactions are ignored."""
        tracker.record_interaction("email1", "dave@example.com", "reply", sent_length=200)
        tracker.record_interaction("email2", "dave@example.com", "reply", sent_length=0)
        tracker.record_interaction("email3", "dave@example.com", "reply", sent_length=400)

        result = tracker.get_contact_avg_length("dave@example.com")
        assert result == 300  # Average of 200, 400 (ignoring 0)

    def test_get_contact_avg_length_days_filter(self, tracker):
        """Test days parameter filters old data."""
        tracker.record_interaction("email1", "eve@example.com", "reply", sent_length=200)
        tracker.record_interaction("email2a", "eve@example.com", "reply", sent_length=200)

        # Insert old interaction
        with tracker._get_conn() as conn:
            old_date = (datetime.now() - timedelta(days=100)).isoformat()
            conn.execute(
                """INSERT INTO email_interactions
                   (email_id, contact, action, sent_length, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                ("email2b", "eve@example.com", "reply", 5000, old_date)
            )

        # Query recent only - should only count the 2 recent ones (both 200)
        result = tracker.get_contact_avg_length("eve@example.com", days=30)
        assert result == 200  # Only the 2 recent ones


# ==================== get_contact_cc_patterns Tests ====================

class TestGetContactCcPatterns:
    """Test get_contact_cc_patterns method."""

    def test_get_contact_cc_patterns_empty(self, tracker):
        """Test on contact with no CC patterns."""
        result = tracker.get_contact_cc_patterns("nonexistent@example.com")
        assert result == []

    def test_get_contact_cc_patterns_single(self, tracker):
        """Test with single CC (should return empty, needs >= 2)."""
        tracker.record_interaction("email1", "alice@example.com", "reply", cc_added="manager@example.com")
        result = tracker.get_contact_cc_patterns("alice@example.com")
        assert result == []  # Needs at least 2 occurrences

    def test_get_contact_cc_patterns_multiple(self, tracker):
        """Test with multiple CC patterns."""
        tracker.record_interaction("email1", "bob@example.com", "reply", cc_added="manager@example.com")
        tracker.record_interaction("email2", "bob@example.com", "reply", cc_added="manager@example.com")
        tracker.record_interaction("email3", "bob@example.com", "reply", cc_added="lead@example.com")
        tracker.record_interaction("email4", "bob@example.com", "reply", cc_added="lead@example.com")

        result = tracker.get_contact_cc_patterns("bob@example.com")
        assert len(result) > 0
        assert "manager@example.com" in result
        assert "lead@example.com" in result

    def test_get_contact_cc_patterns_sorted(self, tracker):
        """Test that CC patterns are sorted by frequency."""
        # Add more frequent first CC
        for _ in range(5):
            tracker.record_interaction("email_x", "charlie@example.com", "reply", cc_added="frequent@example.com")

        # Add less frequent CC
        for _ in range(2):
            tracker.record_interaction("email_y", "charlie@example.com", "reply", cc_added="less_frequent@example.com")

        result = tracker.get_contact_cc_patterns("charlie@example.com")

        if len(result) >= 2:
            # More frequent should come first
            assert result[0] == "frequent@example.com"

    def test_get_contact_cc_patterns_limit(self, tracker):
        """Test that result is limited to 5."""
        # Add 10 different CC patterns
        for i in range(2, 12):
            for _ in range(2):
                tracker.record_interaction(f"email_{i}_{_}", "dave@example.com", "reply", cc_added=f"cc{i}@example.com")

        result = tracker.get_contact_cc_patterns("dave@example.com")
        assert len(result) <= 5

    def test_get_contact_cc_patterns_ignores_empty(self, tracker):
        """Test that empty CC strings are ignored."""
        tracker.record_interaction("email1", "eve@example.com", "reply", cc_added="")
        tracker.record_interaction("email2", "eve@example.com", "reply", cc_added="")
        tracker.record_interaction("email3", "eve@example.com", "reply", cc_added="manager@example.com")
        tracker.record_interaction("email4", "eve@example.com", "reply", cc_added="manager@example.com")

        result = tracker.get_contact_cc_patterns("eve@example.com")
        assert "" not in result


# ==================== get_ignored_senders Tests ====================

class TestGetIgnoredSenders:
    """Test get_ignored_senders method."""

    def test_get_ignored_senders_empty(self, tracker):
        """Test on empty database."""
        result = tracker.get_ignored_senders()
        assert result == []

    def test_get_ignored_senders_below_threshold(self, tracker):
        """Test that senders below min_ignored are excluded."""
        tracker.record_interaction("email1", "alice@example.com", "ignored")
        result = tracker.get_ignored_senders(min_ignored=2)
        assert result == []

    def test_get_ignored_senders_above_threshold(self, tracker):
        """Test senders at or above min_ignored."""
        for i in range(3):
            tracker.record_interaction(f"email{i}", "bob@example.com", "ignored")

        result = tracker.get_ignored_senders(min_ignored=2)
        assert len(result) == 1
        assert result[0]["contact"] == "bob@example.com"
        assert result[0]["count"] == 3

    def test_get_ignored_senders_multiple(self, tracker):
        """Test with multiple ignored senders."""
        for i in range(2):
            tracker.record_interaction(f"email_a{i}", "alice@example.com", "ignored")
        for i in range(3):
            tracker.record_interaction(f"email_b{i}", "bob@example.com", "ignored")

        result = tracker.get_ignored_senders(min_ignored=2)
        assert len(result) == 2

    def test_get_ignored_senders_sorted(self, tracker):
        """Test that results are sorted by count descending."""
        for i in range(2):
            tracker.record_interaction(f"email_a{i}", "alice@example.com", "ignored")
        for i in range(5):
            tracker.record_interaction(f"email_b{i}", "bob@example.com", "ignored")

        result = tracker.get_ignored_senders(min_ignored=2)

        assert result[0]["count"] >= result[1]["count"]

    def test_get_ignored_senders_ignores_non_ignored(self, tracker):
        """Test that non-ignored actions are not counted."""
        for i in range(5):
            tracker.record_interaction(f"email{i}", "charlie@example.com", "reply")

        result = tracker.get_ignored_senders(min_ignored=2)
        contacts = [r["contact"] for r in result]
        assert "charlie@example.com" not in contacts

    def test_get_ignored_senders_days_filter(self, tracker):
        """Test days parameter filters old data."""
        for i in range(3):
            tracker.record_interaction(f"email{i}", "dave@example.com", "ignored")

        # Update one to be old
        with tracker._get_conn() as conn:
            old_date = (datetime.now() - timedelta(days=30)).isoformat()
            conn.execute(
                "UPDATE email_interactions SET created_at = ? WHERE email_id = 'email0'",
                (old_date,)
            )

        result = tracker.get_ignored_senders(days=14, min_ignored=2)
        # Should have fewer than 3 if one is outside the window
        senders = [r for r in result if r["contact"] == "dave@example.com"]
        if senders:
            assert senders[0]["count"] < 3


# ==================== get_contact_edit_stats Tests ====================

class TestGetContactEditStats:
    """Test get_contact_edit_stats method."""

    def test_get_contact_edit_stats_empty(self, tracker):
        """Test on contact with no sends."""
        result = tracker.get_contact_edit_stats("nonexistent@example.com")
        assert result is None

    def test_get_contact_edit_stats_single(self, tracker):
        """Test with single send."""
        tracker.record_send("email1", "alice@example.com", edit_ratio=0.25)
        result = tracker.get_contact_edit_stats("alice@example.com")
        assert result is not None
        assert result["count"] == 1
        assert result["avg_edit_ratio"] == 0.25

    def test_get_contact_edit_stats_multiple(self, tracker):
        """Test with multiple sends."""
        tracker.record_send("email1", "bob@example.com", edit_ratio=0.0)
        tracker.record_send("email2", "bob@example.com", edit_ratio=0.25)
        tracker.record_send("email3", "bob@example.com", edit_ratio=0.5)

        result = tracker.get_contact_edit_stats("bob@example.com")
        assert result["count"] == 3
        assert result["avg_edit_ratio"] == pytest.approx(0.25)

    def test_get_contact_edit_stats_days_filter(self, tracker):
        """Test days parameter."""
        tracker.record_send("email1", "charlie@example.com", edit_ratio=0.1)

        # Insert old send
        with tracker._get_conn() as conn:
            old_date = (datetime.now() - timedelta(days=50)).isoformat()
            conn.execute(
                """INSERT INTO send_events
                   (email_id, contact, edit_ratio, created_at)
                   VALUES (?, ?, ?, ?)""",
                ("email_old", "charlie@example.com", 0.9, old_date)
            )

        result = tracker.get_contact_edit_stats("charlie@example.com", days=30)
        assert result["count"] == 1  # Only recent one
        assert result["avg_edit_ratio"] == 0.1


# ==================== get_stats Tests ====================

class TestGetStats:
    """Test get_stats method."""

    def test_get_stats_empty(self, tracker):
        """Test stats on empty database."""
        result = tracker.get_stats()
        assert result["total_sent"] == 0
        assert result["sent_unmodified"] == 0
        assert result["unmodified_rate"] == 0
        assert result["avg_edit_ratio"] == 0

    def test_get_stats_basic(self, tracker_with_data):
        """Test basic stats calculation."""
        result = tracker_with_data.get_stats()
        assert result["total_sent"] > 0
        assert "by_intent" in result
        assert "by_tier" in result
        assert "daily" in result

    def test_get_stats_unmodified_rate(self, tracker):
        """Test unmodified rate calculation."""
        tracker.record_send("email1", "alice@example.com", sent_unmodified=True)
        tracker.record_send("email2", "bob@example.com", sent_unmodified=False)
        tracker.record_send("email3", "charlie@example.com", sent_unmodified=True)

        result = tracker.get_stats()
        # 2 out of 3 unmodified = 66.7%
        assert result["unmodified_rate"] == pytest.approx(66.7, rel=0.1)

    def test_get_stats_by_intent(self, tracker_with_data):
        """Test by_intent breakdown."""
        result = tracker_with_data.get_stats()
        assert "by_intent" in result
        assert isinstance(result["by_intent"], dict)

    def test_get_stats_by_tier(self, tracker_with_data):
        """Test by_tier breakdown."""
        result = tracker_with_data.get_stats()
        assert "by_tier" in result
        assert isinstance(result["by_tier"], dict)

    def test_get_stats_daily_breakdown(self, tracker_with_data):
        """Test daily breakdown."""
        result = tracker_with_data.get_stats()
        assert "daily" in result
        assert isinstance(result["daily"], list)

    def test_get_stats_days_filter(self, tracker):
        """Test days parameter."""
        tracker.record_send("email1", "alice@example.com")

        # Insert old send
        with tracker._get_conn() as conn:
            old_date = (datetime.now() - timedelta(days=20)).isoformat()
            conn.execute(
                "INSERT INTO send_events (email_id, created_at) VALUES (?, ?)",
                ("email_old", old_date)
            )

        recent = tracker.get_stats(days=7)
        older = tracker.get_stats(days=30)

        assert recent["total_sent"] <= older["total_sent"]


# ==================== get_activity Tests ====================

class TestGetActivity:
    """Test get_activity and activity-related methods."""

    def test_get_activity_empty(self, tracker):
        """Test activity on empty database."""
        result = tracker.get_activity()
        assert "week" in result
        assert "today" in result
        assert result["week"]["drafts"] == 0
        assert result["today"]["drafts"] == 0

    def test_get_activity_structure(self, tracker_with_data):
        """Test activity result structure."""
        result = tracker_with_data.get_activity()

        for period in ["week", "today"]:
            activity = result[period]
            assert "drafts" in activity
            assert "tiers" in activity
            assert "features" in activity
            assert "time_saved_min" in activity
            assert "time_breakdown" in activity

    def test_get_activity_time_saved_simple(self, tracker):
        """Test time saved calculation for simple tier."""
        tracker.record_send("email1", "alice@example.com", tier="simple")
        result = tracker.get_activity()

        # Simple tier = 1.2 min
        assert result["today"]["time_saved_min"] > 0

    def test_get_activity_time_saved_features(self, tracker):
        """Test time saved calculation includes features."""
        tracker.record_send("email1", "alice@example.com", tier="simple")
        tracker.record_feature("compose_ai", 1)

        result = tracker.get_activity()

        # Should include both draft time and feature time
        assert result["today"]["time_saved_min"] > tracker._TIME_SAVED["simple"]

    def test_get_month_activity_valid_month(self, tracker):
        """Test get_month_activity with valid month."""
        tracker.record_send("email1", "alice@example.com")

        month_str = datetime.now().strftime("%Y-%m")
        result = tracker.get_month_activity(month_str)

        assert result["drafts"] >= 0
        assert "time_saved_min" in result

    def test_empty_activity_structure(self):
        """Test _empty_activity static method."""
        result = DraftQualityTracker._empty_activity()

        assert result["drafts"] == 0
        assert result["tiers"]["simple"] == 0
        assert result["archives"] == 0
        assert "time_saved_min" in result


# ==================== Edge Cases and Special Scenarios ====================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_null_contact_handling(self, tracker):
        """Test handling of None/empty contact values."""
        tracker.record_send("email1", None, "reply", "simple")
        result = tracker.get_top_contacts()

        # Empty/None contacts should be filtered
        for contact in result:
            assert contact["contact"] != ""

    def test_concurrent_access_safety(self, tmp_path):
        """Test that concurrent access doesn't cause issues."""
        db_path = str(tmp_path / "concurrent.db")
        tracker1 = DraftQualityTracker(db_path=db_path)
        tracker2 = DraftQualityTracker(db_path=db_path)

        tracker1.record_send("email1", "alice@example.com")
        tracker2.record_send("email2", "bob@example.com")

        result = tracker1.get_top_contacts()
        assert len(result) >= 2

    def test_very_large_edit_ratio(self, tracker):
        """Test handling of edge case edit ratios."""
        tracker.record_send("email1", "alice@example.com", edit_ratio=1.0)
        result = tracker.get_contact_edit_stats("alice@example.com")
        assert result["avg_edit_ratio"] == 1.0

    def test_very_small_edit_ratio(self, tracker):
        """Test handling of very small edit ratios."""
        tracker.record_send("email1", "alice@example.com", edit_ratio=0.001)
        result = tracker.get_contact_edit_stats("alice@example.com")
        assert result["avg_edit_ratio"] == pytest.approx(0.001)

    def test_special_characters_in_contact(self, tracker):
        """Test handling of special characters in contact."""
        special_contact = "user+tag@example.com"
        tracker.record_send("email1", special_contact)
        tracker.record_interaction("email1", special_contact, "reply", sent_length=100)

        result = tracker.get_top_contacts()
        contacts = [c["contact"] for c in result]
        assert special_contact in contacts

    def test_very_long_contact_string(self, tracker):
        """Test handling of very long contact strings."""
        long_contact = "a" * 500 + "@example.com"
        tracker.record_send("email1", long_contact)

        result = tracker.get_top_contacts()
        assert len(result) > 0

    def test_unicode_in_contact(self, tracker):
        """Test handling of unicode in contact."""
        unicode_contact = "josé.garcía@example.com"
        tracker.record_send("email1", unicode_contact)

        result = tracker.get_top_contacts()
        contacts = [c["contact"] for c in result]
        assert unicode_contact in contacts

    def test_negative_values(self, tracker):
        """Test handling of invalid negative values (should still store)."""
        tracker.record_send("email1", "alice@example.com", edit_ratio=-0.1)
        result = tracker.get_contact_edit_stats("alice@example.com")
        assert result["avg_edit_ratio"] == -0.1

    def test_zero_sent_length(self, tracker):
        """Test handling of zero sent length."""
        tracker.record_interaction("email1", "alice@example.com", "reply", sent_length=0)
        tracker.record_interaction("email2", "alice@example.com", "reply", sent_length=100)
        tracker.record_interaction("email3", "alice@example.com", "reply", sent_length=100)

        result = tracker.get_contact_avg_length("alice@example.com")
        assert result == 100  # Should exclude zero, average of 100, 100


# ==================== Singleton and Instance Tests ====================

class TestTrackerInstance:
    """Test DraftQualityTracker instance management."""

    def test_multiple_tracker_instances_same_db(self, tmp_path):
        """Test that multiple instances can share same DB."""
        db_path = str(tmp_path / "shared.db")
        tracker1 = DraftQualityTracker(db_path=db_path)
        tracker2 = DraftQualityTracker(db_path=db_path)

        tracker1.record_send("email1", "alice@example.com")

        result = tracker2.get_top_contacts()
        assert len(result) > 0
        assert result[0]["contact"] == "alice@example.com"

    def test_tracker_db_path_override(self, tmp_path):
        """Test that custom db_path is respected."""
        db_path = str(tmp_path / "custom.db")
        tracker = DraftQualityTracker(db_path=db_path)

        assert tracker._db_path == db_path
        assert os.path.exists(db_path)


# ==================== Data Consistency Tests ====================

class TestDataConsistency:
    """Test data consistency and integrity."""

    def test_sum_consistency(self, tracker_with_data):
        """Test that aggregate sums are consistent."""
        result = tracker_with_data.get_stats()

        total = result["total_sent"]
        unmodified = result["sent_unmodified"]

        assert unmodified <= total

    def test_rate_calculation_consistency(self, tracker):
        """Test rate calculations are logically consistent."""
        tracker.record_send("email1", "alice@example.com", sent_unmodified=True)
        tracker.record_send("email2", "alice@example.com", sent_unmodified=True)
        tracker.record_send("email3", "alice@example.com", sent_unmodified=False)

        result = tracker.get_stats()

        # 2 out of 3 = ~66.7%
        assert 66 < result["unmodified_rate"] < 67

    def test_contact_data_isolation(self, tracker):
        """Test that contact data is properly isolated."""
        tracker.record_send("email1", "alice@example.com", edit_ratio=0.2)
        tracker.record_send("email2", "bob@example.com", edit_ratio=0.8)

        alice_stats = tracker.get_contact_edit_stats("alice@example.com")
        bob_stats = tracker.get_contact_edit_stats("bob@example.com")

        assert alice_stats["avg_edit_ratio"] == 0.2
        assert bob_stats["avg_edit_ratio"] == 0.8


# ==================== Database Persistence Tests ====================

class TestDatabasePersistence:
    """Test that data persists across connections."""

    def test_data_persists_across_connections(self, tmp_path):
        """Test that recorded data survives connection closure."""
        db_path = str(tmp_path / "persist.db")

        # First connection
        tracker1 = DraftQualityTracker(db_path=db_path)
        tracker1.record_send("email1", "alice@example.com")

        # Second connection
        tracker2 = DraftQualityTracker(db_path=db_path)
        result = tracker2.get_top_contacts()

        assert len(result) == 1
        assert result[0]["contact"] == "alice@example.com"

    def test_feature_data_persists(self, tmp_path):
        """Test that feature data persists."""
        db_path = str(tmp_path / "feature_persist.db")

        tracker1 = DraftQualityTracker(db_path=db_path)
        tracker1.record_feature("compose_ai", 5)

        tracker2 = DraftQualityTracker(db_path=db_path)
        with tracker2._get_conn() as conn:
            row = conn.execute("SELECT SUM(count) as total FROM feature_events WHERE feature='compose_ai'").fetchone()
            assert row["total"] == 5
