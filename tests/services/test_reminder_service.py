# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour le module reminder_service."""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import app.services.reminder_service as reminder_service
from app.services.reminder_service import (
    add_reminder,
    get_all_pending,
    dismiss_reminder,
    check_and_notify,
    _mark_notified,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def tmp_reminders_file(tmp_path):
    """Redirige le fichier de persistance vers un fichier temporaire."""
    file = tmp_path / "reminders.json"
    original = reminder_service._REMINDERS_FILE
    reminder_service._REMINDERS_FILE = file
    yield file
    reminder_service._REMINDERS_FILE = original


@pytest.fixture(autouse=True)
def clean_file(tmp_reminders_file):
    """S'assure qu'on part d'un état propre."""
    if tmp_reminders_file.exists():
        tmp_reminders_file.unlink()
    yield


# ============================================================================
# TESTS — add_reminder
# ============================================================================

class TestAddReminder:
    def test_creates_reminder_and_returns_id(self, tmp_reminders_file):
        rid = add_reminder("email_1", "Test Subject", "2026-04-01T10:00:00Z")
        assert rid is not None
        assert len(rid) == 36  # UUID format

    def test_reminder_persisted_to_file(self, tmp_reminders_file):
        add_reminder("email_1", "Test", "2026-04-01T10:00:00Z")
        data = json.loads(tmp_reminders_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["email_id"] == "email_1"
        assert data[0]["notified"] is False

    def test_replaces_existing_reminder_for_same_email(self, tmp_reminders_file):
        rid1 = add_reminder("email_1", "First", "2026-04-01T10:00:00Z")
        rid2 = add_reminder("email_1", "Second", "2026-05-01T10:00:00Z")
        assert rid1 != rid2
        data = json.loads(tmp_reminders_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["subject"] == "Second"

    def test_different_types_on_same_email_coexist(self, tmp_reminders_file):
        # Regression guard (adversarial review F1): a "deadline" reminder
        # (create_reminder Quick Step) must NOT clobber a manual "snooze" on
        # the same email — distinct intents keyed on the same provider id.
        add_reminder("email_1", "Snooze", "2026-04-01T10:00:00Z", reminder_type="snooze")
        add_reminder("email_1", "Deadline", "2026-05-01T10:00:00Z", reminder_type="deadline")
        data = json.loads(tmp_reminders_file.read_text(encoding="utf-8"))
        types = sorted(r["type"] for r in data if r["email_id"] == "email_1")
        assert types == ["deadline", "snooze"]

    def test_same_type_same_email_still_replaces(self, tmp_reminders_file):
        # The type-scoped dedup must still collapse repeats of the SAME type
        # (re-snooze, or a Quick Step re-firing) to one entry.
        add_reminder("email_1", "First", "2026-04-01T10:00:00Z", reminder_type="deadline")
        add_reminder("email_1", "Second", "2026-05-01T10:00:00Z", reminder_type="deadline")
        data = json.loads(tmp_reminders_file.read_text(encoding="utf-8"))
        same = [r for r in data if r["email_id"] == "email_1"]
        assert len(same) == 1
        assert same[0]["subject"] == "Second"

    def test_multiple_emails_coexist(self, tmp_reminders_file):
        add_reminder("email_1", "First", "2026-04-01T10:00:00Z")
        add_reminder("email_2", "Second", "2026-04-02T10:00:00Z")
        data = json.loads(tmp_reminders_file.read_text(encoding="utf-8"))
        assert len(data) == 2


# ============================================================================
# TESTS — get_all_pending
# ============================================================================

class TestGetAllPending:
    def test_empty_when_no_reminders(self, tmp_reminders_file):
        assert get_all_pending() == []

    def test_returns_only_non_notified(self, tmp_reminders_file):
        add_reminder("e1", "Sub1", "2026-04-01T10:00:00Z")
        rid = add_reminder("e2", "Sub2", "2026-04-02T10:00:00Z")
        _mark_notified(rid)
        pending = get_all_pending()
        assert len(pending) == 1
        assert pending[0]["email_id"] == "e1"


# ============================================================================
# TESTS — dismiss_reminder
# ============================================================================

class TestDismissReminder:
    def test_removes_reminder_by_id(self, tmp_reminders_file):
        rid = add_reminder("e1", "Subject", "2026-04-01T10:00:00Z")
        dismiss_reminder(rid)
        assert get_all_pending() == []

    def test_dismiss_nonexistent_id_no_error(self, tmp_reminders_file):
        add_reminder("e1", "Subject", "2026-04-01T10:00:00Z")
        dismiss_reminder("nonexistent-id")
        assert len(get_all_pending()) == 1

    def test_dismiss_only_target(self, tmp_reminders_file):
        rid1 = add_reminder("e1", "Sub1", "2026-04-01T10:00:00Z")
        add_reminder("e2", "Sub2", "2026-04-02T10:00:00Z")
        dismiss_reminder(rid1)
        pending = get_all_pending()
        assert len(pending) == 1
        assert pending[0]["email_id"] == "e2"


# ============================================================================
# TESTS — _mark_notified
# ============================================================================

class TestMarkNotified:
    def test_marks_reminder_as_notified(self, tmp_reminders_file):
        rid = add_reminder("e1", "Subject", "2026-04-01T10:00:00Z")
        _mark_notified(rid)
        data = json.loads(tmp_reminders_file.read_text(encoding="utf-8"))
        assert data[0]["notified"] is True

    def test_mark_nonexistent_id(self, tmp_reminders_file):
        add_reminder("e1", "Subject", "2026-04-01T10:00:00Z")
        _mark_notified("nonexistent")
        data = json.loads(tmp_reminders_file.read_text(encoding="utf-8"))
        assert data[0]["notified"] is False


# ============================================================================
# TESTS — check_and_notify
# ============================================================================

class TestCheckAndNotify:
    @patch("app.services.reminder_service._mark_notified")
    @patch("app.infrastructure.notifications.notify")
    def test_notifies_due_reminders(self, mock_notify, mock_mark, tmp_reminders_file):
        # Créer un rappel échu (dans le passé)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        rid = add_reminder("e1", "Overdue Subject", past)

        mock_notify_obj = MagicMock()
        mock_notify.send = mock_notify_obj

        check_and_notify()
        mock_mark.assert_called_once_with(rid)

    @patch("app.services.reminder_service._mark_notified")
    def test_does_not_notify_future_reminders(self, mock_mark, tmp_reminders_file):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        add_reminder("e1", "Future Subject", future)
        check_and_notify()
        mock_mark.assert_not_called()

    @patch("app.services.reminder_service._mark_notified")
    def test_does_not_notify_already_notified(self, mock_mark, tmp_reminders_file):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        rid = add_reminder("e1", "Subject", past)
        _mark_notified(rid)
        check_and_notify()
        mock_mark.assert_not_called()


# ============================================================================
# TESTS — Persistance edge cases
# ============================================================================

class TestPersistenceEdgeCases:
    def test_corrupted_json_returns_empty(self, tmp_reminders_file):
        tmp_reminders_file.write_text("not valid json", encoding="utf-8")
        assert get_all_pending() == []

    def test_missing_file_returns_empty(self, tmp_reminders_file):
        if tmp_reminders_file.exists():
            tmp_reminders_file.unlink()
        assert get_all_pending() == []

    def test_creates_parent_directory(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "reminders.json"
        original = reminder_service._REMINDERS_FILE
        reminder_service._REMINDERS_FILE = nested
        try:
            add_reminder("e1", "Subject", "2026-04-01T10:00:00Z")
            assert nested.exists()
        finally:
            reminder_service._REMINDERS_FILE = original


class TestPersistenceDurability:
    """Audit 2026-05-19 CONC-DATA-01: atomic write + corrupt-file quarantine
    so a crash mid-write can't silently wipe every reminder."""

    def test_corrupt_file_is_quarantined_not_silently_wiped(self, tmp_reminders_file):
        tmp_reminders_file.write_text("{ broken json", encoding="utf-8")
        assert get_all_pending() == []
        # The live file is moved out of the way (not left to fail every boot)…
        assert not tmp_reminders_file.exists()
        # …and the bad bytes survive in a quarantine file for forensics.
        quarantines = list(tmp_reminders_file.parent.glob("reminders.json.corrupt-*"))
        assert len(quarantines) == 1
        assert "broken json" in quarantines[0].read_text(encoding="utf-8")

    def test_write_leaves_no_temp_file_and_valid_json(self, tmp_reminders_file):
        add_reminder("e1", "Subject", "2026-04-01T10:00:00Z")
        leftovers = list(tmp_reminders_file.parent.glob("reminders.json.tmp.*"))
        assert leftovers == []
        # Round-trips as valid JSON.
        json.loads(tmp_reminders_file.read_text(encoding="utf-8"))

    def test_failed_write_does_not_truncate_existing_file(self, tmp_reminders_file):
        """The whole point of tmp+os.replace: a failure during the new write
        must leave the PREVIOUS good file completely intact."""
        add_reminder("e1", "Original", "2026-04-01T10:00:00Z")
        before = tmp_reminders_file.read_text(encoding="utf-8")
        with patch(
            "app.services.reminder_service.json.dump",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(OSError):
                reminder_service._write([{"clobbered": True}])
        # Original is byte-for-byte intact; no temp turd left behind.
        assert tmp_reminders_file.read_text(encoding="utf-8") == before
        assert list(tmp_reminders_file.parent.glob("reminders.json.tmp.*")) == []


# ============================================================================
# TESTS — _read() parsed-snapshot cache (perf)
# ============================================================================

class TestReadCache:
    """The drafts UI polls /api/pending-drafts (+ /snoozed) constantly and each
    poll calls _read(). These tests pin the (mtime_ns, size)-keyed cache that
    stops _read() from re-parsing the whole file when it hasn't changed, while
    still reflecting every real write and external change."""

    def _reset_cache(self):
        reminder_service._read_cache_sig = None
        reminder_service._read_cache_data = []

    def test_unchanged_file_is_parsed_only_once(self, tmp_reminders_file):
        tmp_reminders_file.write_text(
            json.dumps([{"id": "r1", "email_id": "e1", "notified": False}]),
            encoding="utf-8",
        )
        self._reset_cache()
        with patch(
            "app.services.reminder_service.json.loads", wraps=json.loads
        ) as spy:
            first = reminder_service._read()
            second = reminder_service._read()
            third = reminder_service._read()
        assert spy.call_count == 1  # parsed once, then served from the cache
        assert first == second == third
        assert first[0]["email_id"] == "e1"

    def test_write_invalidates_cache(self, tmp_reminders_file):
        tmp_reminders_file.write_text(json.dumps([]), encoding="utf-8")
        self._reset_cache()
        assert reminder_service._read() == []
        reminder_service._write(
            [{"id": "r2", "email_id": "e2", "notified": False}]
        )
        # Next read must reflect the write, not the stale empty snapshot.
        rows = reminder_service._read()
        assert [r["email_id"] for r in rows] == ["e2"]

    def test_external_change_detected_via_size(self, tmp_reminders_file):
        tmp_reminders_file.write_text(
            json.dumps([{"id": "a", "email_id": "e1"}]), encoding="utf-8"
        )
        self._reset_cache()
        assert len(reminder_service._read()) == 1
        # Out-of-process rewrite with different content/size: even on a coarse
        # mtime filesystem the size delta busts the cached signature.
        tmp_reminders_file.write_text(
            json.dumps(
                [{"id": "a", "email_id": "e1"}, {"id": "b", "email_id": "e2"}]
            ),
            encoding="utf-8",
        )
        assert len(reminder_service._read()) == 2

    def test_returned_list_is_an_independent_copy(self, tmp_reminders_file):
        tmp_reminders_file.write_text(
            json.dumps([{"id": "a", "email_id": "e1", "notified": False}]),
            encoding="utf-8",
        )
        self._reset_cache()
        rows = reminder_service._read()
        # Callers mutate the returned list in place (add_reminder appends,
        # check_and_notify flips fields). That must not corrupt the cache.
        rows.append({"id": "injected"})
        rows[0]["notified"] = True
        again = reminder_service._read()
        assert len(again) == 1
        assert again[0]["notified"] is False

    def test_missing_file_returns_empty_and_resets_cache(self, tmp_reminders_file):
        tmp_reminders_file.write_text(
            json.dumps([{"id": "a", "email_id": "e1"}]), encoding="utf-8"
        )
        self._reset_cache()
        assert len(reminder_service._read()) == 1
        tmp_reminders_file.unlink()
        assert reminder_service._read() == []
        assert reminder_service._read_cache_sig is None

    def test_corrupt_file_quarantined_and_cache_reset(self, tmp_reminders_file):
        tmp_reminders_file.write_text(
            json.dumps([{"id": "a", "email_id": "e1"}]), encoding="utf-8"
        )
        self._reset_cache()
        assert len(reminder_service._read()) == 1
        # Corrupt with a different size so the signature changes and we re-parse.
        tmp_reminders_file.write_text("xxxxxx not valid json", encoding="utf-8")
        assert reminder_service._read() == []
        assert reminder_service._read_cache_sig is None
        # CONC-DATA-01 quarantine behavior must remain intact.
        assert list(tmp_reminders_file.parent.glob("reminders.json.corrupt-*"))
