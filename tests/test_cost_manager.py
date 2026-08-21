# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module de gestion des coûts.

Couvre:
- Calcul des coûts par modèle
- Budget et alertes
- Breakdown par agent/modèle
- Enforcement des limites
"""

import pytest
from datetime import datetime

from app.infrastructure.cost_manager import (
    CostManager,
    AlertLevel,
    BudgetExceededError,
)


class TestCostCalculation:
    """Tests pour le calcul des coûts."""

    def test_calculate_cost_claude_opus(self):
        """Calcul correct pour Claude Opus."""
        manager = CostManager()

        # 1000 tokens input, 500 tokens output
        cost = manager.calculate_cost("claude-opus-4-20250514", 1000, 500)

        # Input: 1000/1M * 15 = 0.015
        # Output: 500/1M * 75 = 0.0375
        expected = 0.015 + 0.0375
        assert cost == pytest.approx(expected, abs=0.0001)

    def test_calculate_cost_claude_haiku(self):
        """Calcul correct pour Claude Haiku."""
        manager = CostManager()

        cost = manager.calculate_cost("claude-3-haiku-20240307", 10000, 5000)

        # Input: 10000/1M * 0.25 = 0.0025
        # Output: 5000/1M * 1.25 = 0.00625
        expected = 0.0025 + 0.00625
        assert cost == pytest.approx(expected, abs=0.0001)

    def test_calculate_cost_ollama_free(self):
        """Les modèles Ollama sont gratuits."""
        manager = CostManager()

        cost = manager.calculate_cost("llama3", 100000, 50000)

        assert cost == 0.0

    def test_calculate_cost_unknown_model(self):
        """Les modèles inconnus utilisent les prix par défaut."""
        manager = CostManager()

        cost = manager.calculate_cost("unknown-model", 1000, 500)

        # Utilise default pricing
        expected = (1000 / 1_000_000 * 5.00) + (500 / 1_000_000 * 15.00)
        assert cost == pytest.approx(expected, abs=0.0001)


class TestUsageRecording:
    """Tests pour l'enregistrement des utilisations."""

    def test_record_usage(self):
        """record_usage enregistre correctement."""
        manager = CostManager()

        record = manager.record_usage(
            model="claude-3-haiku-20240307",
            input_tokens=1000,
            output_tokens=500,
            agent_name="DrafterAgent",
        )

        assert record.model == "claude-3-haiku-20240307"
        assert record.input_tokens == 1000
        assert record.output_tokens == 500
        assert record.agent_name == "DrafterAgent"
        assert record.cost_usd > 0

    def test_record_usage_accumulates_cost(self):
        """Les coûts s'accumulent."""
        manager = CostManager()

        manager.record_usage("claude-3-haiku-20240307", 1000, 500, "Agent1")
        manager.record_usage("claude-3-haiku-20240307", 1000, 500, "Agent2")

        stats = manager.get_stats()
        assert stats["total_requests"] == 2
        assert stats["current_month_cost"] > 0


class TestBudgetManagement:
    """Tests pour la gestion du budget."""

    def test_no_budget_always_can_proceed(self):
        """Sans budget, can_proceed retourne toujours True."""
        manager = CostManager(monthly_budget=None)

        assert manager.can_proceed(100000) is True

    def test_budget_can_proceed_under_limit(self):
        """Sous le budget, can_proceed retourne True."""
        manager = CostManager(monthly_budget=100.0, enforce_budget=True)

        assert manager.can_proceed(1000) is True

    def test_budget_cannot_proceed_over_limit(self):
        """Au-delà du budget avec enforce, can_proceed retourne False."""
        manager = CostManager(monthly_budget=0.01, enforce_budget=True)

        # Enregistrer une utilisation qui dépasse
        manager.record_usage("claude-opus-4-20250514", 100000, 50000)

        assert manager.can_proceed(1000) is False

    def test_budget_not_enforced_always_proceeds(self):
        """Sans enforce, can_proceed retourne toujours True."""
        manager = CostManager(monthly_budget=0.01, enforce_budget=False)

        manager.record_usage("claude-opus-4-20250514", 100000, 50000)

        assert manager.can_proceed(1000) is True

    def test_remaining_budget(self):
        """remaining_budget calcule correctement."""
        manager = CostManager(monthly_budget=10.0)

        manager.record_usage("claude-3-haiku-20240307", 1000000, 500000)

        remaining = manager.get_remaining_budget()
        assert remaining < 10.0
        assert remaining > 0

    def test_usage_percentage(self):
        """usage_percentage calcule correctement."""
        manager = CostManager(monthly_budget=10.0)
        manager._current_month_cost = 5.0

        percentage = manager.get_usage_percentage()

        assert percentage == 50.0


class TestAlerts:
    """Tests pour le système d'alertes."""

    def test_warning_alert_triggered(self):
        """Alerte warning déclenchée à 80%."""
        alerts_received = []
        manager = CostManager(
            monthly_budget=10.0,
            warning_threshold=0.8,
            on_alert=lambda a: alerts_received.append(a),
        )

        # Simuler 85% du budget
        manager._current_month_cost = 8.5
        manager._check_alerts()

        assert len(alerts_received) == 1
        assert alerts_received[0].level == AlertLevel.WARNING

    def test_critical_alert_triggered(self):
        """Alerte critical déclenchée à 95%."""
        alerts_received = []
        manager = CostManager(
            monthly_budget=10.0,
            critical_threshold=0.95,
            on_alert=lambda a: alerts_received.append(a),
        )

        # Simuler 98% du budget
        manager._current_month_cost = 9.8
        manager._check_alerts()

        assert len(alerts_received) == 1
        assert alerts_received[0].level == AlertLevel.CRITICAL

    def test_no_duplicate_alerts(self):
        """Pas d'alertes dupliquées du même niveau."""
        alerts_received = []
        manager = CostManager(
            monthly_budget=10.0,
            on_alert=lambda a: alerts_received.append(a),
        )

        manager._current_month_cost = 8.5
        manager._check_alerts()
        manager._check_alerts()
        manager._check_alerts()

        # Une seule alerte
        assert len(alerts_received) == 1


class TestBreakdown:
    """Tests pour le breakdown des coûts."""

    def test_breakdown_by_agent(self):
        """Breakdown par agent correct."""
        manager = CostManager()

        manager.record_usage("claude-3-haiku-20240307", 1000, 500, "DrafterAgent")
        manager.record_usage("claude-3-haiku-20240307", 2000, 1000, "DrafterAgent")
        manager.record_usage("claude-3-haiku-20240307", 1000, 500, "CriticAgent")

        breakdown = manager.get_breakdown_by_agent()

        assert "DrafterAgent" in breakdown
        assert "CriticAgent" in breakdown
        assert breakdown["DrafterAgent"]["request_count"] == 2
        assert breakdown["CriticAgent"]["request_count"] == 1

    def test_breakdown_by_model(self):
        """Breakdown par modèle correct."""
        manager = CostManager()

        manager.record_usage("claude-3-haiku-20240307", 1000, 500)
        manager.record_usage("claude-opus-4-20250514", 1000, 500)

        breakdown = manager.get_breakdown_by_model()

        assert "claude-3-haiku-20240307" in breakdown
        assert "claude-opus-4-20250514" in breakdown


class TestModelComparison:
    """Tests pour la comparaison de modèles."""

    def test_compare_models(self):
        """compare_models retourne tous les modèles."""
        manager = CostManager()

        comparison = manager.compare_models(10000, 5000)

        assert "claude-opus-4-20250514" in comparison
        assert "claude-3-haiku-20240307" in comparison
        assert "llama3" in comparison

        # Haiku devrait être moins cher qu'Opus
        assert comparison["claude-3-haiku-20240307"] < comparison["claude-opus-4-20250514"]

        # Ollama devrait être gratuit
        assert comparison["llama3"] == 0.0


class TestDailyTrend:
    """Tests pour la tendance quotidienne."""

    def test_daily_trend(self):
        """daily_trend retourne les données par jour."""
        manager = CostManager()

        # Ajouter des enregistrements
        manager.record_usage("claude-3-haiku-20240307", 1000, 500)

        trend = manager.get_daily_trend(days=7)

        assert len(trend) >= 1
        assert "date" in trend[0]
        assert "cost_usd" in trend[0]


class TestMonthlyReset:
    """Tests pour le reset mensuel."""

    def test_monthly_reset(self):
        """Le reset mensuel fonctionne."""
        manager = CostManager()

        manager.record_usage("claude-3-haiku-20240307", 1000, 500)
        assert manager._current_month_cost > 0

        # Simuler changement de mois
        manager._last_reset_month = datetime.now().month - 1
        manager._check_monthly_reset()

        assert manager._current_month_cost == 0
        assert len(manager._usage_records) == 0


class TestStats:
    """Tests pour les statistiques globales."""

    def test_get_stats(self):
        """get_stats retourne toutes les métriques."""
        manager = CostManager(monthly_budget=100.0)

        manager.record_usage("claude-3-haiku-20240307", 1000, 500, "DrafterAgent")
        manager.record_usage("claude-3-haiku-20240307", 2000, 1000, "CriticAgent")

        stats = manager.get_stats()

        assert "current_month_cost" in stats
        assert "monthly_budget" in stats
        assert "remaining_budget" in stats
        assert "usage_percentage" in stats
        assert "total_requests" in stats
        assert "total_tokens" in stats
        assert "by_agent" in stats
        assert "by_model" in stats

        assert stats["total_requests"] == 2
        assert stats["monthly_budget"] == 100.0


class TestBudgetExceededError:
    """Tests pour BudgetExceededError."""

    def test_error_message(self):
        """Le message d'erreur est correct."""
        error = BudgetExceededError(current_cost=15.0, budget=10.0)

        assert "15.00" in str(error)
        assert "10.00" in str(error)
        assert "150" in str(error)  # 150%
