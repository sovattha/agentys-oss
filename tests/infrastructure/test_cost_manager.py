# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests complets pour le module app/infrastructure/cost_manager.py.

Couvre:
- AlertLevel enum
- CostAlert et UsageRecord dataclasses
- CostManager.calculate_cost() pour différents modèles
- CostManager.record_usage() avec breakdown
- CostManager.can_proceed() et budget enforcement
- CostManager.get_remaining_budget() et get_usage_percentage()
- CostManager.get_breakdown_by_agent() et get_breakdown_by_model()
- CostManager.get_daily_trend()
- CostManager.compare_models()
- CostManager.get_stats() et get_current_month_stats()
- Génération d'alertes (warning 80%, critical 95%)
- Reset mensuel
- Cas limites (budget 0, pas de records, division par zéro)
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from dataclasses import fields

from app.infrastructure.cost_manager import (
    AlertLevel,
    CostAlert,
    UsageRecord,
    CostManager,
    BudgetExceededError,
)


class TestAlertLevel:
    """Tests pour l'enum AlertLevel."""

    def test_alert_level_values(self):
        """Vérifie que tous les niveaux d'alerte ont les bonnes valeurs."""
        assert AlertLevel.INFO.value == "info"
        assert AlertLevel.WARNING.value == "warning"
        assert AlertLevel.CRITICAL.value == "critical"

    def test_alert_level_enum_members(self):
        """Vérifie que AlertLevel contient les 3 niveaux attendus."""
        levels = list(AlertLevel)
        assert len(levels) == 3
        assert AlertLevel.INFO in levels
        assert AlertLevel.WARNING in levels
        assert AlertLevel.CRITICAL in levels


class TestCostAlert:
    """Tests pour la dataclass CostAlert."""

    def test_cost_alert_creation(self):
        """Vérifie la création basique d'une alerte."""
        alert = CostAlert(
            level=AlertLevel.WARNING,
            message="Test warning",
            current_cost=80.0,
            threshold=100.0,
        )
        assert alert.level == AlertLevel.WARNING
        assert alert.message == "Test warning"
        assert alert.current_cost == 80.0
        assert alert.threshold == 100.0
        assert isinstance(alert.timestamp, datetime)

    def test_cost_alert_with_custom_timestamp(self):
        """Vérifie que le timestamp personnalisé est respecté."""
        custom_time = datetime(2026, 1, 15, 10, 30, 0)
        alert = CostAlert(
            level=AlertLevel.CRITICAL,
            message="Critical alert",
            current_cost=150.0,
            threshold=200.0,
            timestamp=custom_time,
        )
        assert alert.timestamp == custom_time

    def test_cost_alert_default_timestamp(self):
        """Vérifie que le timestamp par défaut est défini."""
        before = datetime.now()
        alert = CostAlert(
            level=AlertLevel.INFO,
            message="Info",
            current_cost=10.0,
            threshold=100.0,
        )
        after = datetime.now()
        assert before <= alert.timestamp <= after

    def test_cost_alert_fields(self):
        """Vérifie que la dataclass a tous les champs attendus."""
        field_names = {f.name for f in fields(CostAlert)}
        assert field_names == {"level", "message", "current_cost", "threshold", "timestamp"}


class TestUsageRecord:
    """Tests pour la dataclass UsageRecord."""

    def test_usage_record_creation(self):
        """Vérifie la création basique d'un enregistrement."""
        record = UsageRecord(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.05,
            agent_name="DrafterAgent",
        )
        assert record.model == "claude-3-5-sonnet-20241022"
        assert record.input_tokens == 1000
        assert record.output_tokens == 500
        assert record.cost_usd == 0.05
        assert record.agent_name == "DrafterAgent"
        assert isinstance(record.timestamp, datetime)

    def test_usage_record_default_agent_name(self):
        """Vérifie que le nom d'agent par défaut est 'unknown'."""
        record = UsageRecord(
            model="claude-3-5-haiku-20241022",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
        )
        assert record.agent_name == "unknown"

    def test_usage_record_default_timestamp(self):
        """Vérifie que le timestamp est défini par défaut."""
        before = datetime.now()
        record = UsageRecord(
            model="gpt-4o",
            input_tokens=500,
            output_tokens=250,
            cost_usd=0.02,
        )
        after = datetime.now()
        assert before <= record.timestamp <= after

    def test_usage_record_fields(self):
        """Vérifie que la dataclass a tous les champs attendus."""
        field_names = {f.name for f in fields(UsageRecord)}
        assert field_names == {
            "model",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "agent_name",
            "account_id",
            "user_id",
            "feature",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "timestamp",
        }


class TestCalculateCost:
    """Tests pour CostManager.calculate_cost()."""

    def test_calculate_cost_known_model(self):
        """Teste le calcul de coût pour un modèle connu."""
        manager = CostManager()

        # claude-3-5-sonnet: input=3.00, output=15.00 par 1M tokens
        cost = manager.calculate_cost("claude-3-5-sonnet-20241022", 1_000_000, 1_000_000)
        expected = 3.00 + 15.00  # $18.00
        assert cost == pytest.approx(expected, rel=1e-5)

    def test_calculate_cost_opus(self):
        """Teste le coût pour Claude Opus (plus cher)."""
        manager = CostManager()

        # claude-opus-4: input=15.00, output=75.00
        cost = manager.calculate_cost("claude-opus-4-20250514", 1_000_000, 1_000_000)
        expected = 15.00 + 75.00  # $90.00
        assert cost == pytest.approx(expected, rel=1e-5)

    def test_calculate_cost_haiku(self):
        """Teste le coût pour Claude Haiku (moins cher)."""
        manager = CostManager()

        # claude-3-5-haiku: input=0.80, output=4.00
        cost = manager.calculate_cost("claude-3-5-haiku-20241022", 1_000_000, 1_000_000)
        expected = 0.80 + 4.00  # $4.80
        assert cost == pytest.approx(expected, rel=1e-5)

    def test_calculate_cost_haiku_45(self):
        """Teste le coût courant de Claude Haiku 4.5."""
        manager = CostManager()

        cost = manager.calculate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        expected = 1.00 + 5.00  # $6.00
        assert cost == pytest.approx(expected, rel=1e-5)

    def test_calculate_cost_partial_tokens(self):
        """Teste le calcul avec des fractions de 1M tokens."""
        manager = CostManager()

        # 500k input + 250k output avec claude-3-5-sonnet
        cost = manager.calculate_cost("claude-3-5-sonnet-20241022", 500_000, 250_000)
        expected = (500_000 / 1_000_000 * 3.00) + (250_000 / 1_000_000 * 15.00)
        assert cost == pytest.approx(expected, rel=1e-5)

    def test_calculate_cost_ollama_free(self):
        """Vérifie que les modèles Ollama sont gratuits."""
        manager = CostManager()

        for model in ["llama3", "llama3.2", "mistral", "mixtral", "codellama"]:
            cost = manager.calculate_cost(model, 1_000_000, 1_000_000)
            assert cost == 0.0

    def test_calculate_cost_unknown_model_uses_default(self):
        """Teste que les modèles inconnus utilisent le pricing par défaut."""
        manager = CostManager()

        cost = manager.calculate_cost("unknown-model-xyz", 1_000_000, 1_000_000)
        # default: input=5.00, output=15.00
        expected = 5.00 + 15.00  # $20.00
        assert cost == pytest.approx(expected, rel=1e-5)

    def test_calculate_cost_zero_tokens(self):
        """Teste le calcul avec 0 tokens."""
        manager = CostManager()
        cost = manager.calculate_cost("claude-3-5-sonnet-20241022", 0, 0)
        assert cost == 0.0

    def test_calculate_cost_comparison_models(self):
        """Compare les coûts entre différents modèles."""
        manager = CostManager()

        opus_cost = manager.calculate_cost("claude-opus-4-20250514", 1_000_000, 1_000_000)
        sonnet_cost = manager.calculate_cost("claude-3-5-sonnet-20241022", 1_000_000, 1_000_000)
        haiku_cost = manager.calculate_cost("claude-3-5-haiku-20241022", 1_000_000, 1_000_000)

        # Opus > Sonnet > Haiku
        assert opus_cost > sonnet_cost > haiku_cost


class TestRecordUsage:
    """Tests pour CostManager.record_usage()."""

    def test_record_usage_basic(self):
        """Teste l'enregistrement basique d'une utilisation."""
        manager = CostManager(monthly_budget=1000.0)

        record = manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
            agent_name="DrafterAgent",
        )

        assert isinstance(record, UsageRecord)
        assert record.model == "claude-3-5-sonnet-20241022"
        assert record.agent_name == "DrafterAgent"
        assert record.cost_usd > 0
        assert len(manager._usage_records) == 1

    def test_record_usage_updates_current_month_cost(self):
        """Vérifie que le coût mensuel est accumulé."""
        manager = CostManager(monthly_budget=1000.0)
        initial_cost = manager._current_month_cost

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="DrafterAgent",
        )

        assert manager._current_month_cost > initial_cost

    def test_record_usage_updates_breakdown_by_agent(self):
        """Vérifie que le breakdown par agent est mis à jour."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
            agent_name="DrafterAgent",
        )

        assert "DrafterAgent" in manager._cost_by_agent
        assert manager._cost_by_agent["DrafterAgent"] > 0

    def test_record_usage_updates_breakdown_by_model(self):
        """Vérifie que le breakdown par modèle est mis à jour."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
            agent_name="DrafterAgent",
        )

        assert "claude-3-5-sonnet-20241022" in manager._cost_by_model
        assert manager._cost_by_model["claude-3-5-sonnet-20241022"] > 0

    def test_record_usage_multiple_records(self):
        """Teste l'accumulation de plusieurs enregistrements."""
        manager = CostManager(monthly_budget=1000.0)

        for i in range(5):
            manager.record_usage(
                model="claude-3-5-sonnet-20241022",
                input_tokens=1000,
                output_tokens=500,
                agent_name=f"Agent{i}",
            )

        assert len(manager._usage_records) == 5

    def test_record_usage_triggers_alerts(self):
        """Vérifie que les alertes sont déclenchées lors de l'enregistrement."""
        alert_callback = MagicMock()
        manager = CostManager(monthly_budget=100.0, on_alert=alert_callback)

        # Ajouter une utilisation importante pour dépasser le seuil de warning (80%)
        manager.record_usage(
            model="claude-opus-4-20250514",
            input_tokens=5_000_000,  # Coûteux
            output_tokens=5_000_000,
            agent_name="DrafterAgent",
        )

        # Vérifier qu'une alerte a été créée
        assert len(manager._alerts) > 0
        assert alert_callback.called


class TestCanProceed:
    """Tests pour CostManager.can_proceed()."""

    def test_can_proceed_no_budget(self):
        """Vérifie que can_proceed retourne True sans budget."""
        manager = CostManager(monthly_budget=None)
        assert manager.can_proceed(estimated_tokens=10000) is True

    def test_can_proceed_not_enforced(self):
        """Vérifie que can_proceed retourne True si l'enforcement n'est pas activé."""
        manager = CostManager(monthly_budget=100.0, enforce_budget=False)
        assert manager.can_proceed(estimated_tokens=10000) is True

    def test_can_proceed_within_budget(self):
        """Vérifie que can_proceed retourne True si on est dans le budget."""
        manager = CostManager(monthly_budget=1000.0, enforce_budget=True)
        manager._current_month_cost = 100.0

        assert manager.can_proceed(estimated_tokens=1000) is True

    def test_can_proceed_exceeds_budget(self):
        """Vérifie que can_proceed retourne False si on dépasserait le budget."""
        manager = CostManager(monthly_budget=100.0, enforce_budget=True)
        manager._current_month_cost = 99.99

        # Avec une estimation de tokens élevée, le coût estimé dépasse le budget restant
        assert manager.can_proceed(estimated_tokens=10000000) is False

    def test_can_proceed_at_budget_limit(self):
        """Vérifie le comportement à la limite du budget."""
        manager = CostManager(monthly_budget=100.0, enforce_budget=True)
        manager._current_month_cost = 100.0

        # À la limite avec estimation nulle
        assert manager.can_proceed(estimated_tokens=0) is True


class TestGetRemainingBudget:
    """Tests pour CostManager.get_remaining_budget()."""

    def test_get_remaining_budget_no_budget(self):
        """Vérifie que get_remaining_budget retourne None sans budget."""
        manager = CostManager(monthly_budget=None)
        assert manager.get_remaining_budget() is None

    def test_get_remaining_budget_full(self):
        """Vérifie le budget restant sans aucun coût."""
        manager = CostManager(monthly_budget=1000.0)
        manager._current_month_cost = 0.0

        assert manager.get_remaining_budget() == 1000.0

    def test_get_remaining_budget_partial(self):
        """Vérifie le budget restant avec coûts partiels."""
        manager = CostManager(monthly_budget=1000.0)
        manager._current_month_cost = 250.0

        assert manager.get_remaining_budget() == 750.0

    def test_get_remaining_budget_exceeded(self):
        """Vérifie que le budget restant ne peut pas être négatif."""
        manager = CostManager(monthly_budget=100.0)
        manager._current_month_cost = 150.0

        assert manager.get_remaining_budget() == 0.0

    def test_get_remaining_budget_zero(self):
        """Vérifie le budget restant quand tout est utilisé."""
        manager = CostManager(monthly_budget=100.0)
        manager._current_month_cost = 100.0

        assert manager.get_remaining_budget() == 0.0


class TestGetUsagePercentage:
    """Tests pour CostManager.get_usage_percentage()."""

    def test_get_usage_percentage_no_budget(self):
        """Vérifie que get_usage_percentage retourne 0% sans budget."""
        manager = CostManager(monthly_budget=None)
        assert manager.get_usage_percentage() == 0.0

    def test_get_usage_percentage_empty(self):
        """Vérifie le pourcentage avec aucun coût."""
        manager = CostManager(monthly_budget=1000.0)
        manager._current_month_cost = 0.0

        assert manager.get_usage_percentage() == 0.0

    def test_get_usage_percentage_half(self):
        """Vérifie le pourcentage à 50%."""
        manager = CostManager(monthly_budget=1000.0)
        manager._current_month_cost = 500.0

        assert manager.get_usage_percentage() == pytest.approx(50.0, rel=1e-5)

    def test_get_usage_percentage_warning(self):
        """Vérifie le pourcentage au seuil de warning (80%)."""
        manager = CostManager(monthly_budget=1000.0)
        manager._current_month_cost = 800.0

        assert manager.get_usage_percentage() == pytest.approx(80.0, rel=1e-5)

    def test_get_usage_percentage_critical(self):
        """Vérifie le pourcentage au seuil de critical (95%)."""
        manager = CostManager(monthly_budget=1000.0)
        manager._current_month_cost = 950.0

        assert manager.get_usage_percentage() == pytest.approx(95.0, rel=1e-5)

    def test_get_usage_percentage_over_100(self):
        """Vérifie le pourcentage quand on dépasse le budget."""
        manager = CostManager(monthly_budget=100.0)
        manager._current_month_cost = 150.0

        assert manager.get_usage_percentage() == pytest.approx(150.0, rel=1e-5)


class TestAlertGeneration:
    """Tests pour la génération d'alertes."""

    def test_no_alert_without_budget(self):
        """Vérifie qu'aucune alerte n'est générée sans budget."""
        manager = CostManager(monthly_budget=None)

        manager.record_usage(
            model="claude-opus-4-20250514",
            input_tokens=10_000_000,
            output_tokens=10_000_000,
            agent_name="DrafterAgent",
        )

        assert len(manager._alerts) == 0

    def test_warning_alert_at_80_percent(self):
        """Vérifie qu'une alerte WARNING est générée à 80%."""
        manager = CostManager(
            monthly_budget=100.0,
            warning_threshold=0.8,
            critical_threshold=0.95,
        )

        # Enregistrer une utilisation menant à ~80% du budget
        manager._current_month_cost = 79.9
        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=100_000,  # Petite utilisation pour atteindre exactement 80%
            output_tokens=100_000,
            agent_name="DrafterAgent",
        )

        # Chercher l'alerte WARNING
        warning_alerts = [a for a in manager._alerts if a.level == AlertLevel.WARNING]
        assert len(warning_alerts) >= 1

    def test_critical_alert_at_95_percent(self):
        """Vérifie qu'une alerte CRITICAL est générée à 95%."""
        manager = CostManager(
            monthly_budget=100.0,
            warning_threshold=0.8,
            critical_threshold=0.95,
        )

        # Atteindre ~95% du budget
        manager._current_month_cost = 94.9
        manager.record_usage(
            model="claude-opus-4-20250514",
            input_tokens=100_000,
            output_tokens=100_000,
            agent_name="DrafterAgent",
        )

        # Chercher l'alerte CRITICAL
        critical_alerts = [a for a in manager._alerts if a.level == AlertLevel.CRITICAL]
        assert len(critical_alerts) >= 1

    def test_no_duplicate_alerts(self):
        """Vérifie qu'aucune alerte dupliquée du même niveau n'est créée."""
        manager = CostManager(
            monthly_budget=100.0,
            warning_threshold=0.8,
            critical_threshold=0.95,
        )

        # Atteindre le seuil de warning
        manager._current_month_cost = 80.0
        manager.record_usage(
            model="claude-3-5-haiku-20241022",
            input_tokens=10_000,
            output_tokens=10_000,
            agent_name="Agent1",
        )

        len(manager._alerts)

        # Enregistrer une autre utilisation (ne devrait pas créer de nouvelle alerte)
        manager.record_usage(
            model="claude-3-5-haiku-20241022",
            input_tokens=10_000,
            output_tokens=10_000,
            agent_name="Agent2",
        )

        len(manager._alerts)

        # Pas de nouvelle alerte du même niveau
        warning_alerts = [a for a in manager._alerts if a.level == AlertLevel.WARNING]
        assert len(warning_alerts) == 1

    def test_alert_callback_called(self):
        """Vérifie que le callback d'alerte est appelé."""
        alert_callback = MagicMock()
        manager = CostManager(
            monthly_budget=100.0,
            warning_threshold=0.8,
            on_alert=alert_callback,
        )

        manager._current_month_cost = 79.0
        manager.record_usage(
            model="claude-opus-4-20250514",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="DrafterAgent",
        )

        # Vérifier que le callback a été appelé au moins une fois
        assert alert_callback.call_count >= 1

        # Vérifier que l'argument est une CostAlert
        if alert_callback.call_count > 0:
            call_args = alert_callback.call_args
            assert isinstance(call_args[0][0], CostAlert)


class TestBreakdownByAgent:
    """Tests pour CostManager.get_breakdown_by_agent()."""

    def test_breakdown_by_agent_empty(self):
        """Vérifie le breakdown vide."""
        manager = CostManager(monthly_budget=1000.0)
        breakdown = manager.get_breakdown_by_agent()

        assert breakdown == {}

    def test_breakdown_by_agent_single_agent(self):
        """Vérifie le breakdown avec un seul agent."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="DrafterAgent",
        )

        breakdown = manager.get_breakdown_by_agent()

        assert "DrafterAgent" in breakdown
        assert breakdown["DrafterAgent"]["cost_usd"] > 0
        assert breakdown["DrafterAgent"]["percentage"] == pytest.approx(100.0, rel=1e-5)
        assert breakdown["DrafterAgent"]["request_count"] == 1

    def test_breakdown_by_agent_multiple_agents(self):
        """Vérifie le breakdown avec plusieurs agents."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="DrafterAgent",
        )

        manager.record_usage(
            model="claude-3-5-haiku-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="CriticAgent",
        )

        breakdown = manager.get_breakdown_by_agent()

        assert len(breakdown) == 2
        assert "DrafterAgent" in breakdown
        assert "CriticAgent" in breakdown
        assert breakdown["DrafterAgent"]["percentage"] + breakdown["CriticAgent"]["percentage"] == pytest.approx(100.0, rel=1e-3)

    def test_breakdown_by_agent_includes_token_count(self):
        """Vérifie que le breakdown inclut le compte de tokens."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=5000,
            output_tokens=3000,
            agent_name="TestAgent",
        )

        breakdown = manager.get_breakdown_by_agent()

        assert breakdown["TestAgent"]["total_tokens"] == 8000

    def test_breakdown_by_agent_division_by_zero_protection(self):
        """Vérifie que le breakdown gère la division par zéro."""
        manager = CostManager(monthly_budget=1000.0)
        manager._current_month_cost = 0.0

        breakdown = manager.get_breakdown_by_agent()

        # Ne devrait pas lever d'exception
        assert breakdown == {}


class TestBreakdownByModel:
    """Tests pour CostManager.get_breakdown_by_model()."""

    def test_breakdown_by_model_empty(self):
        """Vérifie le breakdown vide."""
        manager = CostManager(monthly_budget=1000.0)
        breakdown = manager.get_breakdown_by_model()

        assert breakdown == {}

    def test_breakdown_by_model_single_model(self):
        """Vérifie le breakdown avec un seul modèle."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="DrafterAgent",
        )

        breakdown = manager.get_breakdown_by_model()

        assert "claude-3-5-sonnet-20241022" in breakdown
        assert breakdown["claude-3-5-sonnet-20241022"]["cost_usd"] > 0
        assert breakdown["claude-3-5-sonnet-20241022"]["percentage"] == pytest.approx(100.0, rel=1e-5)
        assert breakdown["claude-3-5-sonnet-20241022"]["request_count"] == 1

    def test_breakdown_by_model_multiple_models(self):
        """Vérifie le breakdown avec plusieurs modèles."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="Agent1",
        )

        manager.record_usage(
            model="claude-3-5-haiku-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="Agent2",
        )

        breakdown = manager.get_breakdown_by_model()

        assert len(breakdown) == 2
        assert "claude-3-5-sonnet-20241022" in breakdown
        assert "claude-3-5-haiku-20241022" in breakdown

    def test_breakdown_by_model_avg_cost_per_request(self):
        """Vérifie le calcul du coût moyen par requête."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="Agent1",
        )

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="Agent2",
        )

        breakdown = manager.get_breakdown_by_model()

        total_cost = breakdown["claude-3-5-sonnet-20241022"]["cost_usd"]
        avg_cost = breakdown["claude-3-5-sonnet-20241022"]["avg_cost_per_request"]

        assert avg_cost == pytest.approx(total_cost / 2, rel=1e-5)


class TestGetDailyTrend:
    """Tests pour CostManager.get_daily_trend()."""

    def test_get_daily_trend_empty(self):
        """Vérifie le trend vide."""
        manager = CostManager(monthly_budget=1000.0)
        trend = manager.get_daily_trend(days=30)

        assert trend == []

    def test_get_daily_trend_single_day(self):
        """Vérifie le trend avec un seul jour."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="Agent1",
        )

        trend = manager.get_daily_trend(days=30)

        assert len(trend) == 1
        assert "date" in trend[0]
        assert "cost_usd" in trend[0]
        assert trend[0]["cost_usd"] > 0

    def test_get_daily_trend_multiple_days(self):
        """Vérifie le trend avec plusieurs jours."""
        manager = CostManager(monthly_budget=1000.0)

        # Enregistrer pour aujourd'hui
        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="Agent1",
        )

        # Simuler une utilisation hier
        yesterday = datetime.now() - timedelta(days=1)
        record = UsageRecord(
            model="claude-3-5-haiku-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cost_usd=6.0,
            agent_name="Agent2",
            timestamp=yesterday,
        )
        manager._usage_records.append(record)
        manager._current_month_cost += record.cost_usd

        trend = manager.get_daily_trend(days=30)

        assert len(trend) == 2
        # Vérifier que c'est trié
        assert trend[0]["date"] <= trend[1]["date"]

    def test_get_daily_trend_respects_days_limit(self):
        """Vérifie que le trend respecte la limite de jours."""
        manager = CostManager(monthly_budget=1000.0)

        # Ajouter des records de 40 jours en arrière
        for i in range(40):
            old_date = datetime.now() - timedelta(days=i)
            record = UsageRecord(
                model="claude-3-5-haiku-20241022",
                input_tokens=10_000,
                output_tokens=10_000,
                cost_usd=0.001,
                agent_name="Agent",
                timestamp=old_date,
            )
            manager._usage_records.append(record)

        trend = manager.get_daily_trend(days=30)

        # Seulement 30 jours
        assert len(trend) <= 30

    def test_get_daily_trend_sorted(self):
        """Vérifie que le trend est trié chronologiquement."""
        manager = CostManager(monthly_budget=1000.0)

        # Ajouter dans le désordre
        for i in [10, 5, 15, 0, 20]:
            old_date = datetime.now() - timedelta(days=i)
            record = UsageRecord(
                model="claude-3-5-haiku-20241022",
                input_tokens=10_000,
                output_tokens=10_000,
                cost_usd=0.001,
                agent_name="Agent",
                timestamp=old_date,
            )
            manager._usage_records.append(record)

        trend = manager.get_daily_trend(days=30)
        dates = [item["date"] for item in trend]

        assert dates == sorted(dates)


class TestCompareModels:
    """Tests pour CostManager.compare_models()."""

    def test_compare_models_returns_dict(self):
        """Vérifie que compare_models retourne un dictionnaire."""
        manager = CostManager()
        comparison = manager.compare_models(1_000_000, 1_000_000)

        assert isinstance(comparison, dict)

    def test_compare_models_excludes_default(self):
        """Vérifie que le modèle 'default' n'est pas inclus."""
        manager = CostManager()
        comparison = manager.compare_models(1_000_000, 1_000_000)

        assert "default" not in comparison

    def test_compare_models_includes_known_models(self):
        """Vérifie que les modèles connus sont inclus."""
        manager = CostManager()
        comparison = manager.compare_models(1_000_000, 1_000_000)

        assert "claude-3-5-sonnet-20241022" in comparison
        assert "claude-3-5-haiku-20241022" in comparison
        assert "claude-opus-4-20250514" in comparison

    def test_compare_models_correct_relative_costs(self):
        """Vérifie que les coûts relatifs sont corrects."""
        manager = CostManager()
        comparison = manager.compare_models(1_000_000, 1_000_000)

        opus_cost = comparison["claude-opus-4-20250514"]
        sonnet_cost = comparison["claude-3-5-sonnet-20241022"]
        haiku_cost = comparison["claude-3-5-haiku-20241022"]

        # Opus > Sonnet > Haiku
        assert opus_cost > sonnet_cost > haiku_cost

    def test_compare_models_ollama_free(self):
        """Vérifie que les modèles Ollama sont gratuits dans la comparaison."""
        manager = CostManager()
        comparison = manager.compare_models(1_000_000, 1_000_000)

        for model in ["llama3", "llama3.2", "mistral"]:
            assert comparison[model] == 0.0


class TestGetStats:
    """Tests pour CostManager.get_stats()."""

    def test_get_stats_empty(self):
        """Vérifie les stats sans utilisation."""
        manager = CostManager(monthly_budget=1000.0)
        stats = manager.get_stats()

        assert stats["current_month_cost"] == 0.0
        assert stats["monthly_budget"] == 1000.0
        assert stats["total_requests"] == 0
        assert stats["total_tokens"] == 0

    def test_get_stats_includes_required_fields(self):
        """Vérifie que les stats incluent tous les champs requis."""
        manager = CostManager(monthly_budget=1000.0)
        stats = manager.get_stats()

        required_fields = [
            "current_month_cost",
            "monthly_budget",
            "remaining_budget",
            "usage_percentage",
            "enforce_budget",
            "total_requests",
            "total_tokens",
            "avg_cost_per_request",
            "alerts_count",
            "by_agent",
            "by_model",
        ]

        for field in required_fields:
            assert field in stats

    def test_get_stats_with_usage(self):
        """Vérifie les stats avec utilisation."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="DrafterAgent",
        )

        stats = manager.get_stats()

        assert stats["current_month_cost"] > 0
        assert stats["total_requests"] == 1
        assert stats["total_tokens"] > 0
        assert stats["avg_cost_per_request"] > 0

    def test_get_stats_breakdown_included(self):
        """Vérifie que les breakdowns sont inclus."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="TestAgent",
        )

        stats = manager.get_stats()

        assert "TestAgent" in stats["by_agent"]
        assert "claude-3-5-sonnet-20241022" in stats["by_model"]


class TestGetCurrentMonthStats:
    """Tests pour CostManager.get_current_month_stats()."""

    def test_get_current_month_stats_empty(self):
        """Vérifie les stats du mois vide."""
        manager = CostManager(monthly_budget=1000.0)
        stats = manager.get_current_month_stats()

        assert stats["cost_usd"] == 0.0
        assert stats["budget"] == 1000.0
        assert stats["usage_percentage"] == 0.0

    def test_get_current_month_stats_includes_required_fields(self):
        """Vérifie que les stats du mois incluent tous les champs."""
        manager = CostManager(monthly_budget=1000.0)
        stats = manager.get_current_month_stats()

        required_fields = [
            "cost_usd",
            "budget",
            "remaining",
            "usage_percentage",
            "request_count",
            "total_tokens",
        ]

        for field in required_fields:
            assert field in stats

    def test_get_current_month_stats_with_usage(self):
        """Vérifie les stats du mois avec utilisation."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="TestAgent",
        )

        stats = manager.get_current_month_stats()

        assert stats["cost_usd"] > 0
        assert stats["request_count"] == 1
        assert stats["total_tokens"] > 0


class TestMonthlyReset:
    """Tests pour la logique de reset mensuel."""

    @patch("app.infrastructure.cost_manager.datetime")
    def test_monthly_reset_on_month_change(self, mock_datetime):
        """Vérifie que le reset mensuel fonctionne lors du changement de mois."""
        # Simuler janvier
        mock_datetime.now.return_value = datetime(2026, 1, 15, 10, 0, 0)
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        manager = CostManager(monthly_budget=1000.0)
        manager._last_reset_month = 1

        # Enregistrer une utilisation
        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="TestAgent",
        )

        assert len(manager._usage_records) == 1
        assert manager._current_month_cost > 0

        # Simuler février
        mock_datetime.now.return_value = datetime(2026, 2, 15, 10, 0, 0)

        # Enregistrer une autre utilisation (qui déclenche le reset)
        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="TestAgent",
        )

        # Le reset devrait avoir vidé les anciens records
        assert manager._last_reset_month == 2
        assert len(manager._usage_records) == 1

    def test_monthly_reset_clears_state(self):
        """Vérifie que le reset mensuel efface tout l'état."""
        manager = CostManager(monthly_budget=1000.0)
        manager._last_reset_month = 1
        manager._current_month_cost = 100.0
        manager._cost_by_agent = {"Agent1": 50.0}
        manager._cost_by_model = {"Model1": 100.0}
        manager._alerts = [
            CostAlert(
                level=AlertLevel.WARNING,
                message="Test",
                current_cost=100.0,
                threshold=800.0,
            )
        ]
        manager._usage_records = [
            UsageRecord(
                model="test",
                input_tokens=100,
                output_tokens=100,
                cost_usd=0.01,
            )
        ]

        # Forcer le reset
        manager._check_monthly_reset()
        # Changer le mois fictif
        manager._last_reset_month = 1

        # Manuellement changer la date de check
        with patch("app.infrastructure.cost_manager.datetime") as mock_dt:
            mock_dt.now.return_value.month = 2
            manager._check_monthly_reset()

        # Vérifier que l'état a été réinitialisé
        assert manager._current_month_cost == 0.0
        assert manager._cost_by_agent == {}
        assert manager._cost_by_model == {}
        assert manager._alerts == []
        assert manager._usage_records == []

    def test_no_reset_same_month(self):
        """Vérifie qu'aucun reset n'a lieu le même mois."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="Agent1",
        )

        cost_before = manager._current_month_cost

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            agent_name="Agent2",
        )

        # Le coût devrait avoir augmenté, pas réinitialisé
        assert manager._current_month_cost > cost_before


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_zero_budget(self):
        """Teste le comportement avec un budget de 0 (falsy → considéré illimité)."""
        manager = CostManager(monthly_budget=0.0)

        record = manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
            agent_name="TestAgent",
        )

        assert record is not None
        assert manager._current_month_cost > 0
        # 0.0 is falsy → monthly_budget is None-like → get_usage_percentage returns 0.0
        assert manager.get_usage_percentage() == 0.0

    def test_very_small_budget(self):
        """Teste avec un très petit budget."""
        manager = CostManager(monthly_budget=0.01)

        manager.record_usage(
            model="claude-3-5-haiku-20241022",
            input_tokens=1000,
            output_tokens=500,
            agent_name="TestAgent",
        )

        assert manager.get_remaining_budget() >= 0.0

    def test_very_large_budget(self):
        """Teste avec un très grand budget."""
        manager = CostManager(monthly_budget=1_000_000.0)

        manager.record_usage(
            model="claude-opus-4-20250514",
            input_tokens=100_000_000,
            output_tokens=100_000_000,
            agent_name="TestAgent",
        )

        assert manager.get_usage_percentage() < 100.0

    def test_zero_tokens(self):
        """Teste l'enregistrement avec 0 tokens."""
        manager = CostManager(monthly_budget=1000.0)

        record = manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=0,
            output_tokens=0,
            agent_name="TestAgent",
        )

        assert record.cost_usd == 0.0

    def test_very_large_token_count(self):
        """Teste avec un très grand nombre de tokens."""
        manager = CostManager(monthly_budget=1_000_000.0)

        record = manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000_000,
            output_tokens=1_000_000_000,
            agent_name="TestAgent",
        )

        assert record.cost_usd > 0

    def test_empty_agent_name(self):
        """Teste avec un nom d'agent vide."""
        manager = CostManager(monthly_budget=1000.0)

        record = manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
            agent_name="",
        )

        assert record.agent_name == ""
        assert "" in manager._cost_by_agent

    def test_division_by_zero_protection(self):
        """Teste la protection contre la division par zéro."""
        manager = CostManager(monthly_budget=1000.0)
        manager._current_month_cost = 0.0

        # Ces appels ne devraient pas lever d'exception
        assert manager.get_usage_percentage() == 0.0
        breakdown_agent = manager.get_breakdown_by_agent()
        breakdown_model = manager.get_breakdown_by_model()

        assert breakdown_agent == {}
        assert breakdown_model == {}


class TestBudgetExceededError:
    """Tests pour l'exception BudgetExceededError."""

    def test_budget_exceeded_error_creation(self):
        """Vérifie la création de l'exception."""
        error = BudgetExceededError(150.0, 100.0)

        assert error.current_cost == 150.0
        assert error.budget == 100.0

    def test_budget_exceeded_error_message(self):
        """Vérifie le message d'exception."""
        error = BudgetExceededError(150.0, 100.0)
        message = str(error)

        assert "150.00" in message
        assert "100.00" in message
        assert "150.0" in message  # Pourcentage


class TestIntegration:
    """Tests d'intégration complètes."""

    def test_full_workflow(self):
        """Teste un workflow complet d'utilisation."""
        alert_callback = MagicMock()
        manager = CostManager(
            monthly_budget=100.0,
            enforce_budget=True,
            warning_threshold=0.8,
            critical_threshold=0.95,
            on_alert=alert_callback,
        )

        # Vérifier que la procédure est possible au début
        assert manager.can_proceed(estimated_tokens=1000) is True

        # Enregistrer plusieurs utilisations
        for i in range(5):
            manager.record_usage(
                model="claude-3-5-haiku-20241022",
                input_tokens=100_000,
                output_tokens=50_000,
                agent_name=f"Agent{i}",
            )

        # Vérifier les stats
        stats = manager.get_stats()
        assert stats["total_requests"] == 5
        assert stats["current_month_cost"] > 0

        # Vérifier les breakdowns
        breakdown_agent = manager.get_breakdown_by_agent()
        assert len(breakdown_agent) == 5

        breakdown_model = manager.get_breakdown_by_model()
        assert "claude-3-5-haiku-20241022" in breakdown_model

        # Vérifier que les alertes ont été créées (si le seuil a été atteint)
        if manager.get_usage_percentage() >= 80:
            assert len(manager._alerts) > 0

    def test_model_comparison_workflow(self):
        """Teste le workflow de comparaison de modèles."""
        manager = CostManager(monthly_budget=1000.0)

        # Utiliser plusieurs modèles
        models = [
            "claude-opus-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
        ]

        for model in models:
            manager.record_usage(
                model=model,
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                agent_name=f"Agent-{model}",
            )

        # Obtenir la comparaison
        comparison = manager.compare_models(1_000_000, 1_000_000)

        # Vérifier que les coûts sont dans le bon ordre
        opus = comparison["claude-opus-4-20250514"]
        sonnet = comparison["claude-3-5-sonnet-20241022"]
        haiku = comparison["claude-3-5-haiku-20241022"]

        assert opus > sonnet > haiku


class TestPropertyAndMethods:
    """Tests pour les propriétés et méthodes supplémentaires."""

    def test_alert_threshold_property(self):
        """Vérifie la propriété alert_threshold."""
        manager = CostManager(warning_threshold=0.75)
        assert manager.alert_threshold == 0.75

    def test_get_daily_costs_alias(self):
        """Vérifie que get_daily_costs est un alias pour get_daily_trend."""
        manager = CostManager(monthly_budget=1000.0)

        manager.record_usage(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
            agent_name="TestAgent",
        )

        daily_trend = manager.get_daily_trend(days=30)
        daily_costs = manager.get_daily_costs(days=30)

        assert daily_trend == daily_costs

    def test_constructor_with_env_fallback(self):
        """Vérifie que le constructeur utilise les env fallbacks."""
        # Sans passer de paramètres, devrait utiliser les defaults
        manager = CostManager()

        # Vérifier que les defaults sont appliqués
        assert manager.warning_threshold == 0.8
        assert manager.critical_threshold == 0.95
        assert manager.enforce_budget is False

    def test_custom_thresholds(self):
        """Teste les seuils d'alerte personnalisés."""
        manager = CostManager(
            monthly_budget=100.0,
            warning_threshold=0.5,  # Plus bas que la valeur par défaut
            critical_threshold=0.9,
        )

        assert manager.warning_threshold == 0.5
        assert manager.critical_threshold == 0.9
