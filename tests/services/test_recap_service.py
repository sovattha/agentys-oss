# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.services.recap_service — fonctions pures."""

import pytest
from unittest.mock import patch, MagicMock

from app.services.recap_service import (
    _prev_month,
    _month_label,
    _build_comparison,
    MONTH_NAMES_EN,
)


# ── _prev_month ─────────────────────────────────────────────────────────────

class TestPrevMonth:
    def test_standard_month(self):
        assert _prev_month("2026-03") == "2026-02"

    def test_january_wraps_to_december(self):
        assert _prev_month("2026-01") == "2025-12"

    def test_february(self):
        assert _prev_month("2026-02") == "2026-01"

    def test_december(self):
        assert _prev_month("2026-12") == "2026-11"

    def test_preserves_format(self):
        result = _prev_month("2026-05")
        assert result == "2026-04"
        # Doit être zero-padded
        result2 = _prev_month("2026-02")
        assert result2 == "2026-01"


# ── _month_label ─────────────────────────────────────────────────────────────

class TestMonthLabel:
    def test_january(self):
        assert _month_label("2026-01") == "JANUARY 2026"

    def test_december(self):
        assert _month_label("2026-12") == "DECEMBER 2026"

    def test_february(self):
        assert _month_label("2025-02") == "FEBRUARY 2025"

    def test_all_months_valid(self):
        for i in range(1, 13):
            month_str = f"2026-{i:02d}"
            label = _month_label(month_str)
            assert MONTH_NAMES_EN[i - 1].upper() in label
            assert "2026" in label


# ── _build_comparison ────────────────────────────────────────────────────────

class TestBuildComparison:
    @patch("app.services.recap_tracker.get_recap_tracker")
    def test_first_month_no_history(self, mock_tracker):
        tracker = MagicMock()
        tracker.get_all_data.return_value = {"active_dates": []}
        mock_tracker.return_value = tracker

        result = _build_comparison(5.0, 0, "2026-01", "2026-02")
        assert result["type"] == "first_month"
        assert result["delta_hours"] == 0

    @patch("app.services.recap_tracker.get_recap_tracker")
    def test_improving(self, mock_tracker):
        tracker = MagicMock()
        tracker.get_all_data.return_value = {"active_dates": ["2026-01-15"]}
        mock_tracker.return_value = tracker

        result = _build_comparison(10.0, 5.0, "2025-12", "2026-01")
        assert result["type"] == "improving"
        assert result["delta_hours"] == 5.0
        assert "décembre 2025" in result["message"]

    def test_declining(self):
        result = _build_comparison(3.0, 8.0, "2025-12", "2026-01")
        assert result["type"] == "declining"
        assert result["delta_hours"] == -5.0

    def test_same(self):
        result = _build_comparison(5.0, 5.2, "2025-12", "2026-01")
        assert result["type"] == "same"
        assert result["delta_hours"] == pytest.approx(-0.2, abs=0.01)

    def test_improving_threshold(self):
        """delta > 0.5 => improving."""
        result = _build_comparison(5.6, 5.0, "2025-12", "2026-01")
        assert result["type"] == "improving"

    def test_declining_threshold(self):
        """delta < -0.5 => declining."""
        result = _build_comparison(4.4, 5.0, "2025-12", "2026-01")
        assert result["type"] == "declining"

    def test_same_threshold_boundary(self):
        """delta = -0.5 => same (not declining, needs < -0.5)."""
        result = _build_comparison(4.5, 5.0, "2025-12", "2026-01")
        assert result["type"] == "same"

    def test_empty_when_both_months_have_no_signal(self):
        result = _build_comparison(0, 0, "2025-12", "2026-01")
        assert result["type"] == "empty"
