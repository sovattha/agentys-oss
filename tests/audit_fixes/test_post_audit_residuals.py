# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Post-audit residuals — 4 regression tests requested by the user during the
2026-04-26 ultrathink pass:

1. email_archived WS event must include account_id (S-07 fix)
2. Calendar followups must recover gracefully from JSON corruption
3. Outlook all-day events must NOT shift TZ (Calendar-MEDIUM-5)
4. Multi-account cache isolation: same email_id in account A vs B
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ------------------------------------------------------------------ #
# 1. email_archived WS event scoped to account_id
# ------------------------------------------------------------------ #


class TestEmailArchivedAccountScoping:
    """Background threads emitting `email_archived` MUST pass account_id so
    `emit_to_account` can route to the per-account WS room. Pre-fix, missing
    account_id caused `_resolve_ws_room()` to return None (no Flask request
    context in the bg thread) and the event was silently dropped."""

    def test_emit_with_account_id_routes_to_emit_to_account(self):
        from app.api import websocket as ws_mod

        with patch.object(ws_mod, "emit_to_account") as mock_emit_to_acc, \
             patch.object(ws_mod, "get_socketio") as mock_socketio:
            ws_mod.emit_email_archived("email-42", account_id=7)

        mock_emit_to_acc.assert_called_once_with(
            "email_archived", {"email_id": "email-42"}, 7
        )
        mock_socketio.assert_not_called()  # we used the per-account path, not broadcast

    def test_emit_without_account_id_skips_when_no_room(self):
        """ISO-06 / S-01: bg thread without request context → no broadcast."""
        from app.api import websocket as ws_mod

        with patch.object(ws_mod, "_resolve_ws_room", return_value=None), \
             patch.object(ws_mod, "get_socketio") as mock_socketio:
            sio = MagicMock()
            mock_socketio.return_value = sio
            ws_mod.emit_email_archived("email-42", account_id=None)

        # Must NOT have broadcast
        sio.emit.assert_not_called()

    def test_emit_with_zero_account_id_falls_through_to_legacy_path(self):
        """account_id=0 is invalid (no real account uses 0). Should NOT
        invoke emit_to_account; falls through to the room-resolve path."""
        from app.api import websocket as ws_mod

        with patch.object(ws_mod, "emit_to_account") as mock_emit_to_acc, \
             patch.object(ws_mod, "_resolve_ws_room", return_value=None):
            ws_mod.emit_email_archived("email-42", account_id=0)

        mock_emit_to_acc.assert_not_called()


# ------------------------------------------------------------------ #
# 2. Calendar followups corruption recovery
# ------------------------------------------------------------------ #


class TestCalendarFollowupsCorruption:
    """Un followups.json corrompu ne doit pas crasher ni bloquer les boots.

    Post-migration 041 le comportement vit dans
    ``app.services.followup_store.ensure_legacy_import`` : JSON corrompu →
    quarantaine ``.corrupt-<ts>`` + store vide ; fichier absent → store vide.
    """

    @staticmethod
    def _store_db(monkeypatch, tmp_path):
        from contextlib import contextmanager

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        import app.services.followup_store as fu_store
        from app.db.models import Base

        engine = create_engine(
            "sqlite://", poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False)

        @contextmanager
        def _cm():
            s = SessionLocal()
            try:
                yield s
            finally:
                s.close()

        monkeypatch.setattr("app.db.database.get_db_session", _cm)
        monkeypatch.setattr(fu_store, "FOLLOWUPS_FILE", str(tmp_path / "followups.json"))
        monkeypatch.setattr(fu_store, "_legacy_import_done", False)
        return fu_store

    def test_corrupt_json_resets_to_empty_dict(self, tmp_path, monkeypatch):
        fu_store = self._store_db(monkeypatch, tmp_path)
        (tmp_path / "followups.json").write_text("{not valid json{{{", encoding="utf-8")

        assert fu_store.all_records() == []  # pas de raise, store vide
        # Quarantaine (audit 2026-05-11 P1) : le fichier corrompu est déplacé
        assert not (tmp_path / "followups.json").exists()
        assert list(tmp_path.glob("followups.json.corrupt-*"))

# NB : test_atomic_write_uses_temp_then_rename supprimé avec les migrations
# 041/042 — `_atomic_write_json` n'existe plus dans calendar.py (le risque
# « partial write » de Calendar-HIGH-4 est structurellement clos : followups
# et suggestions persistent via des transactions DB).

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        """No file → fresh start, store vide, no crash."""
        fu_store = self._store_db(monkeypatch, tmp_path)
        assert fu_store.all_records() == []


# ------------------------------------------------------------------ #
# 3. Outlook all-day TZ regression
# ------------------------------------------------------------------ #


class TestOutlookAllDayTimezone:
    """Calendar-MEDIUM-5: all-day events must keep the IANA TZ name so Microsoft
    Graph doesn't shift them by ±1 day for users west of UTC."""

    def test_all_day_event_preserves_iana_tz(self):
        """Europe/Paris midnight all-day → must NOT be sent as UTC."""
        from app.providers.outlook_calendar import OutlookCalendarAdapter

        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            pytest.skip("zoneinfo not available")

        adapter = OutlookCalendarAdapter.__new__(OutlookCalendarAdapter)
        paris = datetime(2026, 6, 15, 0, 0, tzinfo=ZoneInfo("Europe/Paris"))
        result = adapter._format_datetime(paris, all_day=True)
        assert result["timeZone"] == "Europe/Paris"
        # Must be midnight on the correct day, not a UTC-shifted version.
        assert result["dateTime"].startswith("2026-06-15T00:00:00")

    def test_all_day_with_naive_datetime_falls_back_to_utc(self):
        """Naive datetimes (no tz) must default to UTC for all-day events."""
        from app.providers.outlook_calendar import OutlookCalendarAdapter

        adapter = OutlookCalendarAdapter.__new__(OutlookCalendarAdapter)
        naive = datetime(2026, 6, 15, 0, 0)
        result = adapter._format_datetime(naive, all_day=True)
        assert result["timeZone"] == "UTC"

    def test_timed_event_keeps_iana_tz(self):
        """Non-all-day events also use the IANA tz name so DST transitions
        don't shift the wall clock time."""
        from app.providers.outlook_calendar import OutlookCalendarAdapter

        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            pytest.skip("zoneinfo not available")

        adapter = OutlookCalendarAdapter.__new__(OutlookCalendarAdapter)
        ny = datetime(2026, 6, 15, 14, 30, tzinfo=ZoneInfo("America/New_York"))
        result = adapter._format_datetime(ny, all_day=False)
        assert result["timeZone"] == "America/New_York"
        assert result["dateTime"].startswith("2026-06-15T14:30:00")


# ------------------------------------------------------------------ #
# 4. Multi-account cache isolation (same email_id in two accounts)
# ------------------------------------------------------------------ #


class TestLabelsCachePerAccount:
    """C-1 audit: `_labels_cache` is keyed by account_id. The same key (None)
    must NOT leak between accounts when both call _get_labels_cached with
    different ids."""

    def test_two_accounts_get_distinct_cache_entries(self):
        from app.api import labels as labels_mod

        # Reset the cache.
        labels_mod._labels_cache.clear()

        # Build a fake container.get_label_store(account_id=...) that returns
        # a different fake store per account so the cache is the only thing
        # that could mix them.
        class _FakeStore:
            def __init__(self, label_set):
                self._labels = label_set

            def get_labels(self):
                return self._labels

        store_a = _FakeStore(["label-A"])
        store_b = _FakeStore(["label-B"])

        def fake_get_store(account_id=None):
            if account_id == 1:
                return store_a
            if account_id == 2:
                return store_b
            return _FakeStore(["legacy"])

        with patch.object(labels_mod, "get_container") as mock_container:
            container = MagicMock()
            container.get_label_store.side_effect = fake_get_store
            mock_container.return_value = container

            r1 = labels_mod._get_labels_cached(account_id=1)
            r2 = labels_mod._get_labels_cached(account_id=2)
            r1_again = labels_mod._get_labels_cached(account_id=1)

        assert r1 == ["label-A"]
        assert r2 == ["label-B"]
        # Same account → cache hit, identical reference.
        assert r1 is r1_again
        # Cache has independent entries.
        assert 1 in labels_mod._labels_cache
        assert 2 in labels_mod._labels_cache
        assert labels_mod._labels_cache[1][0] != labels_mod._labels_cache[2][0]

    def test_invalidate_one_account_does_not_clear_others(self):
        from app.api import labels as labels_mod
        import time

        labels_mod._labels_cache.clear()
        now = time.monotonic()
        labels_mod._labels_cache[1] = (["A"], now)
        labels_mod._labels_cache[2] = (["B"], now)

        labels_mod._invalidate_labels_cache(account_id=1)

        assert 1 not in labels_mod._labels_cache
        assert 2 in labels_mod._labels_cache  # NOT cleared

    def test_invalidate_all_when_account_id_none(self):
        """The legacy invalidate-all behaviour (mutations) must clear the
        whole cache so no account sees stale data."""
        from app.api import labels as labels_mod
        import time

        labels_mod._labels_cache.clear()
        now = time.monotonic()
        labels_mod._labels_cache[1] = (["A"], now)
        labels_mod._labels_cache[2] = (["B"], now)

        labels_mod._invalidate_labels_cache(account_id=None)

        assert labels_mod._labels_cache == {}
