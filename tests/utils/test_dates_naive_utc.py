# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression — « pourquoi 14:47 dans la liste et 18:47 dans le fil ? » (2026-06-09).

Les writers du cache email stockaient des datetimes provider AWARE (offset
-04:00 du header Date Gmail) dans la colonne naïve ``Email.date`` : SQLite perd
l'offset, ``_to_iso_utc`` re-étiquette l'heure murale locale en ``Z``, et le
frontend décale l'affichage de -4 h dans la liste pendant que le détail (re-servi
du provider avec son vrai offset) affiche l'heure juste.

pytest tests/utils/test_dates_naive_utc.py -v
"""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from app.utils.dates import cached_date_needs_heal, to_naive_utc, utc_now_naive


KARINE_HEADER = "Mon, 09 Jun 2026 18:47:53 -0400"  # le header Date réel du bug
TRUE_UTC = datetime(2026, 6, 9, 22, 47, 53)


class TestToNaiveUtc:
    def test_gmail_date_header_becomes_true_utc(self):
        aware = parsedate_to_datetime(KARINE_HEADER)
        normalized = to_naive_utc(aware)
        assert normalized == TRUE_UTC
        assert normalized.tzinfo is None

    def test_naive_datetime_passes_through_unchanged(self):
        naive = datetime(2026, 6, 9, 22, 47, 53)
        assert to_naive_utc(naive) is naive

    def test_iso_string_with_z_suffix(self):
        assert to_naive_utc("2026-06-09T22:47:53Z") == TRUE_UTC

    def test_iso_string_with_offset(self):
        assert to_naive_utc("2026-06-09T18:47:53-04:00") == TRUE_UTC

    def test_naive_iso_string_assumed_utc(self):
        assert to_naive_utc("2026-06-09T22:47:53") == TRUE_UTC

    def test_garbage_and_none_return_none(self):
        assert to_naive_utc("Mon, 09 Jun") is None
        assert to_naive_utc("") is None
        assert to_naive_utc(None) is None
        assert to_naive_utc(12345) is None  # type: ignore[arg-type]

    def test_serialization_roundtrip_preserves_instant(self):
        """Le contrat de bout en bout : header Date → colonne → _to_iso_utc
        doit redonner le MÊME instant, pas l'heure murale re-étiquetée."""
        from app.api.routes_helpers import _to_iso_utc

        normalized = to_naive_utc(parsedate_to_datetime(KARINE_HEADER))
        assert _to_iso_utc(normalized) == "2026-06-09T22:47:53Z"


class TestUtcNowNaive:
    def test_is_naive_and_close_to_utc(self):
        now = utc_now_naive()
        assert now.tzinfo is None
        delta = abs((now - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds())
        assert delta < 5


class TestCachedDateNeedsHeal:
    def test_timezone_shift_triggers_heal(self):
        wall_local = datetime(2026, 6, 9, 18, 47, 53)  # ligne pré-fix (heure murale)
        assert cached_date_needs_heal(wall_local, TRUE_UTC) is True

    def test_small_drift_is_left_alone(self):
        assert cached_date_needs_heal(TRUE_UTC, TRUE_UTC + timedelta(seconds=30)) is False

    def test_missing_values_never_heal(self):
        assert cached_date_needs_heal(None, TRUE_UTC) is False
        assert cached_date_needs_heal(TRUE_UTC, None) is False
