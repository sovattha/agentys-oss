# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour les fonctions utilitaires de recap_service."""

from app.services.recap_service import _prev_month, _month_label, _build_comparison, MONTH_NAMES_EN


class TestPrevMonth:
    """Tests pour _prev_month."""

    def test_middle_of_year(self):
        assert _prev_month("2026-06") == "2026-05"

    def test_january_wraps_to_december(self):
        assert _prev_month("2026-01") == "2025-12"

    def test_february(self):
        assert _prev_month("2026-02") == "2026-01"

    def test_december(self):
        assert _prev_month("2026-12") == "2026-11"

    def test_march(self):
        assert _prev_month("2026-03") == "2026-02"


class TestMonthLabel:
    """Tests pour _month_label."""

    def test_january(self):
        assert _month_label("2026-01") == "JANUARY 2026"

    def test_december(self):
        assert _month_label("2026-12") == "DECEMBER 2026"

    def test_june(self):
        assert _month_label("2026-06") == "JUNE 2026"

    def test_february(self):
        assert _month_label("2025-02") == "FEBRUARY 2025"


class TestMonthNamesEn:
    """Tests pour la constante MONTH_NAMES_EN."""

    def test_twelve_months(self):
        assert len(MONTH_NAMES_EN) == 12

    def test_first_month(self):
        assert MONTH_NAMES_EN[0] == "January"

    def test_last_month(self):
        assert MONTH_NAMES_EN[11] == "December"


class TestBuildComparison:
    """Tests pour _build_comparison."""

    def test_improving(self):
        result = _build_comparison(10.0, 5.0, "2026-01", "2026-02")
        assert result["type"] == "improving"
        assert result["delta_hours"] == 5.0
        assert "de plus" in result["message"]

    def test_declining(self):
        result = _build_comparison(3.0, 8.0, "2026-01", "2026-02")
        assert result["type"] == "declining"
        assert result["delta_hours"] == -5.0
        assert "de moins" in result["message"]

    def test_same(self):
        result = _build_comparison(5.0, 5.0, "2026-01", "2026-02")
        assert result["type"] == "same"
        assert result["delta_hours"] == 0.0
        assert "Stable" in result["message"]

    def test_empty(self):
        result = _build_comparison(0, 0, "2026-01", "2026-02")
        assert result["type"] == "empty"

    def test_same_with_small_delta(self):
        result = _build_comparison(5.3, 5.0, "2026-01", "2026-02")
        assert result["type"] == "same"

    def test_improving_threshold(self):
        result = _build_comparison(5.5, 5.0, "2026-01", "2026-02")
        assert result["type"] == "same"

    def test_improving_above_threshold(self):
        result = _build_comparison(5.6, 5.0, "2026-01", "2026-02")
        assert result["type"] == "improving"
