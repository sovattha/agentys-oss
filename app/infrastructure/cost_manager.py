# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Module de gestion des coûts pour Agentys.

Fournit:
- Budget mensuel avec alertes
- Enforcement de limite de coûts
- Breakdown des coûts par agent/modèle
- Comparaison de coûts entre modèles
- Historique des tendances
"""

import logging
import os
import sys
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from enum import Enum

from app.config import get_env_float, get_env_bool

logger = logging.getLogger(__name__)


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or any("pytest" in arg for arg in sys.argv)


def _default_persist_usage() -> bool:
    raw = os.environ.get("COST_PERSIST_USAGE")
    if raw is not None:
        return raw.lower() in ("1", "true", "yes", "on")
    return not _running_under_pytest()


_usage_account_id: ContextVar[Optional[int]] = ContextVar("usage_account_id", default=None)
_usage_user_id: ContextVar[Optional[int]] = ContextVar("usage_user_id", default=None)
_usage_feature: ContextVar[str] = ContextVar("usage_feature", default="unknown")


def set_usage_context(
    *,
    account_id: Optional[int] = None,
    user_id: Optional[int] = None,
    feature: str = "unknown",
):
    """Définit le contexte d'attribution tokens pour la requête courante.

    Retourne les tokens ContextVar pour permettre un reset fiable dans un
    `finally` sans partager d'état entre threads/requêtes.
    """
    return (
        _usage_account_id.set(account_id),
        _usage_user_id.set(user_id),
        _usage_feature.set(feature or "unknown"),
    )


def reset_usage_context(tokens) -> None:
    """Réinitialise le contexte d'attribution tokens."""
    if not tokens:
        return
    account_token, user_token, feature_token = tokens
    _usage_account_id.reset(account_token)
    _usage_user_id.reset(user_token)
    _usage_feature.reset(feature_token)


def _resolve_request_usage_context() -> tuple[Optional[int], Optional[int]]:
    """Best-effort account/user attribution from the active Flask request."""
    try:
        from flask import has_request_context

        if not has_request_context():
            return None, None

        from app.api._auth_helpers import get_auth_user_id
        from app.api.routes_helpers import _resolve_account_id_cached

        account_id = _resolve_account_id_cached()
        if account_id == -1:
            account_id = None
        return account_id, get_auth_user_id()
    except Exception:
        return None, None


def _infer_feature_from_request() -> str:
    """Infère une feature coarse depuis la route active, sans contenu métier."""
    try:
        from flask import has_request_context, request

        if not has_request_context():
            return "unknown"
        path = (request.path or "").lower()
        if "onboarding" in path:
            return "onboarding"
        if "classif" in path or "labels" in path:
            return "classify"
        if "refine" in path:
            return "refine"
        if "compose" in path:
            return "compose"
        if "draft" in path or "preview" in path or "generate" in path or "process" in path:
            return "drafting"
        return "unknown"
    except Exception:
        return "unknown"


def get_usage_context() -> tuple[Optional[int], Optional[int], str]:
    """Retourne le contexte d'attribution courant account/user/feature.

    Utilisé par les sondes non-LLM (HTTP/API) pour partager la même logique que
    les coûts tokens. Best-effort : en tâche background sans contexte Flask ou
    ContextVar explicite, les IDs restent `None`.
    """
    account_id = _usage_account_id.get()
    user_id = _usage_user_id.get()
    if account_id is None or user_id is None:
        request_account_id, request_user_id = _resolve_request_usage_context()
        if account_id is None:
            account_id = request_account_id
        if user_id is None:
            user_id = request_user_id
    feature = _usage_feature.get() or "unknown"
    if feature == "unknown":
        feature = _infer_feature_from_request()
    return account_id, user_id, feature or "unknown"


# Prix par 1M de tokens (mise à jour 2025-2026)
# Source de vérité pour les prix — app/domain/entities/token_usage.py doit rester synchronisé
# Note: anciens IDs conservés pour les usages historiques loggés avant la migration.
MODEL_PRICING = {
    # Claude models (prix 2025-2026)
    "claude-opus-4-7": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    # Anciens IDs (rétrocompat données historiques)
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    # Ollama (local - gratuit)
    "llama3": {"input": 0.0, "output": 0.0},
    "llama3.2": {"input": 0.0, "output": 0.0},
    "mistral": {"input": 0.0, "output": 0.0},
    "mixtral": {"input": 0.0, "output": 0.0},
    "codellama": {"input": 0.0, "output": 0.0},
    # OpenAI (pour comparaison)
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    # Default for unknown models
    "default": {"input": 5.00, "output": 15.00},
}


class AlertLevel(Enum):
    """Niveau d'alerte pour les coûts."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class CostAlert:
    """Alerte de coût."""
    level: AlertLevel
    message: str
    current_cost: float
    threshold: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class UsageRecord:
    """Enregistrement d'utilisation."""
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    agent_name: str = "unknown"
    account_id: Optional[int] = None
    user_id: Optional[int] = None
    feature: str = "unknown"
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


class CostManager:
    """
    Gestionnaire de coûts pour le suivi et le contrôle des dépenses API.

    Fonctionnalités:
    - Calcul des coûts par modèle
    - Budget mensuel avec alertes
    - Enforcement optionnel des limites
    - Breakdown par agent
    """

    def __init__(
        self,
        monthly_budget: Optional[float] = None,
        enforce_budget: Optional[bool] = None,
        warning_threshold: float = 0.8,
        critical_threshold: float = 0.95,
        on_alert: Optional[Callable[[CostAlert], None]] = None,
        persist_usage: Optional[bool] = None,
    ):
        """
        Initialise le gestionnaire de coûts.

        Args:
            monthly_budget: Budget mensuel en USD (None = illimité)
            enforce_budget: Si True, bloque les requêtes au-delà du budget
            warning_threshold: Seuil d'alerte warning (0.8 = 80%)
            critical_threshold: Seuil d'alerte critical (0.95 = 95%)
            on_alert: Callback appelé lors d'une alerte
        """
        self.monthly_budget = monthly_budget or get_env_float("COST_MONTHLY_BUDGET", None)
        self.enforce_budget = enforce_budget if enforce_budget is not None else get_env_bool("COST_ENFORCE_BUDGET", False)
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.on_alert = on_alert
        self.persist_usage = (
            persist_usage
            if persist_usage is not None
            else _default_persist_usage()
        )

        # État interne
        self._current_month_cost = 0.0
        self._usage_records: List[UsageRecord] = []
        self._alerts: List[CostAlert] = []
        self._cost_by_agent: Dict[str, float] = {}
        self._cost_by_model: Dict[str, float] = {}
        self._last_reset_month: int = datetime.now().month

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """
        Calcule le coût pour une utilisation donnée.

        Args:
            model: Nom du modèle utilisé
            input_tokens: Nombre de tokens en entrée
            output_tokens: Nombre de tokens en sortie

        Returns:
            Coût en USD
        """
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])

        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]

        return input_cost + output_cost

    def calculate_cost_with_cache(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> float:
        """Calcule le coût en tenant compte du prompt caching Anthropic.

        Anthropic facture les cache writes à 1.25x le prix input, et les cache
        reads à 0.10x. Pour les modèles non-Anthropic, les compteurs cache sont
        normalement à zéro ; garder le calcul ici évite de perdre la visibilité
        cache hit demandée par #551.
        """
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        billable_input = (
            input_tokens
            + cache_creation_input_tokens * 1.25
            + cache_read_input_tokens * 0.10
        )
        input_cost = (billable_input / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent_name: str = "unknown",
        account_id: Optional[int] = None,
        user_id: Optional[int] = None,
        feature: Optional[str] = None,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        persist: bool = True,
    ) -> UsageRecord:
        """
        Enregistre une utilisation et vérifie les alertes.

        Args:
            model: Nom du modèle
            input_tokens: Tokens en entrée
            output_tokens: Tokens en sortie
            agent_name: Nom de l'agent (DrafterAgent, CriticAgent, etc.)

        Returns:
            L'enregistrement d'utilisation
        """
        # Auto-reset mensuel
        self._check_monthly_reset()

        context_account_id = _usage_account_id.get()
        context_user_id = _usage_user_id.get()
        if account_id is None:
            account_id = context_account_id
        if user_id is None:
            user_id = context_user_id
        if account_id is None or user_id is None:
            request_account_id, request_user_id = _resolve_request_usage_context()
            if account_id is None:
                account_id = request_account_id
            if user_id is None:
                user_id = request_user_id
        feature = feature or _usage_feature.get() or "unknown"
        if feature == "unknown":
            feature = _infer_feature_from_request()
        cost = self.calculate_cost_with_cache(
            model,
            input_tokens,
            output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        )

        record = UsageRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            agent_name=agent_name,
            account_id=account_id,
            user_id=user_id,
            feature=feature,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        )

        self._usage_records.append(record)
        self._current_month_cost += cost

        # Mise à jour breakdown
        self._cost_by_agent[agent_name] = self._cost_by_agent.get(agent_name, 0.0) + cost
        self._cost_by_model[model] = self._cost_by_model.get(model, 0.0) + cost

        # Vérifier les alertes
        self._check_alerts()
        if persist:
            self._persist_usage_record(record)
            self._report_billable_overage(record)

        logger.debug(
            f"Cost recorded: model={model}, tokens={input_tokens}+{output_tokens}, "
            f"cost=${cost:.4f}, agent={agent_name}"
        )

        return record

    def _report_billable_overage(self, record: UsageRecord) -> None:
        """Report billable overage without ever breaking the LLM response path."""
        try:
            from app.billing.usage_metering import report_llm_overage_if_needed

            report_llm_overage_if_needed(record)
        except Exception as exc:  # pragma: no cover — billing telemetry best-effort
            logger.error("[COST] LLM overage billing report skipped: %s", exc)

    def _persist_usage_record(self, record: UsageRecord) -> None:
        """Écrit le record dans SQLite sans jamais casser l'appel LLM."""
        if not self.persist_usage:
            return
        try:
            from app.infrastructure.database import db

            db.execute(
                """
                INSERT INTO token_usage_log (
                    account_id, user_id, agent, agent_name, feature, model,
                    input_tokens, output_tokens,
                    cache_creation_input_tokens, cache_read_input_tokens,
                    cost_usd, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.account_id,
                    record.user_id,
                    record.agent_name,
                    record.agent_name,
                    record.feature,
                    record.model,
                    record.input_tokens,
                    record.output_tokens,
                    record.cache_creation_input_tokens,
                    record.cache_read_input_tokens,
                    record.cost_usd,
                    record.timestamp.isoformat(),
                ),
            )
            db.commit()
        except Exception as exc:  # pragma: no cover — telemetry non-bloquante
            logger.debug("[COST] token_usage_log write skipped: %s", exc)

    def can_proceed(self, estimated_tokens: int = 5000) -> bool:
        """
        Vérifie si une nouvelle requête peut être effectuée.

        Args:
            estimated_tokens: Estimation des tokens pour la requête

        Returns:
            True si la requête peut être effectuée
        """
        if not self.monthly_budget:
            return True

        if not self.enforce_budget:
            return True

        # Estimer le coût (utilise le modèle par défaut)
        estimated_cost = self.calculate_cost("default", estimated_tokens, estimated_tokens // 2)

        return (self._current_month_cost + estimated_cost) <= self.monthly_budget

    def get_remaining_budget(self) -> Optional[float]:
        """Retourne le budget restant pour le mois."""
        if not self.monthly_budget:
            return None
        return max(0, self.monthly_budget - self._current_month_cost)

    def get_usage_percentage(self) -> float:
        """Retourne le pourcentage du budget utilisé."""
        if not self.monthly_budget:
            return 0.0
        return (self._current_month_cost / self.monthly_budget) * 100

    def get_breakdown_by_agent(self) -> Dict[str, Dict[str, Any]]:
        """
        Retourne le breakdown des coûts par agent.

        Returns:
            Dict avec pour chaque agent: cost, percentage, token_count
        """
        total = self._current_month_cost or 1  # Éviter division par zéro

        result = {}
        for agent, cost in self._cost_by_agent.items():
            agent_records = [r for r in self._usage_records if r.agent_name == agent]
            result[agent] = {
                "cost_usd": cost,
                "percentage": (cost / total) * 100,
                "request_count": len(agent_records),
                "total_tokens": sum(r.input_tokens + r.output_tokens for r in agent_records),
            }

        return result

    def get_breakdown_by_model(self) -> Dict[str, Dict[str, Any]]:
        """
        Retourne le breakdown des coûts par modèle.

        Returns:
            Dict avec pour chaque modèle: cost, percentage, request_count
        """
        total = self._current_month_cost or 1

        result = {}
        for model, cost in self._cost_by_model.items():
            model_records = [r for r in self._usage_records if r.model == model]
            result[model] = {
                "cost_usd": cost,
                "percentage": (cost / total) * 100,
                "request_count": len(model_records),
                "avg_cost_per_request": cost / len(model_records) if model_records else 0,
            }

        return result

    def get_daily_trend(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Retourne la tendance des coûts par jour.

        Args:
            days: Nombre de jours à inclure

        Returns:
            Liste des coûts par jour
        """
        # Strict ``>`` keeps exactly ``days`` distinct calendar days
        # (including today). Using ``>=`` with ``days`` produced ``days + 1``
        # entries for callers that populate one record per day because it
        # included the boundary day on both ends.
        cutoff = datetime.now() - timedelta(days=days)

        # Regrouper par jour
        daily_costs: Dict[str, float] = {}
        for record in self._usage_records:
            if record.timestamp > cutoff:
                day = record.timestamp.strftime("%Y-%m-%d")
                daily_costs[day] = daily_costs.get(day, 0.0) + record.cost_usd

        # Convertir en liste triée
        return [
            {"date": day, "cost_usd": cost}
            for day, cost in sorted(daily_costs.items())
        ]

    def compare_models(self, input_tokens: int, output_tokens: int) -> Dict[str, float]:
        """
        Compare les coûts entre différents modèles pour une utilisation donnée.

        Args:
            input_tokens: Tokens en entrée
            output_tokens: Tokens en sortie

        Returns:
            Dict des coûts par modèle
        """
        return {
            model: self.calculate_cost(model, input_tokens, output_tokens)
            for model in MODEL_PRICING.keys()
            if model != "default"
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques complètes.

        Returns:
            Dict avec toutes les métriques
        """
        return {
            "current_month_cost": self._current_month_cost,
            "monthly_budget": self.monthly_budget,
            "remaining_budget": self.get_remaining_budget(),
            "usage_percentage": self.get_usage_percentage(),
            "enforce_budget": self.enforce_budget,
            "total_requests": len(self._usage_records),
            "total_tokens": sum(r.input_tokens + r.output_tokens for r in self._usage_records),
            "avg_cost_per_request": (
                self._current_month_cost / len(self._usage_records)
                if self._usage_records else 0
            ),
            "alerts_count": len(self._alerts),
            "by_agent": self.get_breakdown_by_agent(),
            "by_model": self.get_breakdown_by_model(),
        }

    def get_current_month_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du mois en cours.

        Returns:
            Dict avec les métriques du mois
        """
        return {
            "cost_usd": self._current_month_cost,
            "budget": self.monthly_budget,
            "remaining": self.get_remaining_budget(),
            "usage_percentage": self.get_usage_percentage(),
            "request_count": len(self._usage_records),
            "total_tokens": sum(r.input_tokens + r.output_tokens for r in self._usage_records),
        }

    def get_daily_costs(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Alias pour get_daily_trend pour compatibilité API.

        Args:
            days: Nombre de jours à inclure

        Returns:
            Liste des coûts par jour
        """
        return self.get_daily_trend(days=days)

    @property
    def alert_threshold(self) -> float:
        """Retourne le seuil d'alerte warning."""
        return self.warning_threshold

    def _check_monthly_reset(self) -> None:
        """Vérifie et effectue le reset mensuel si nécessaire."""
        current_month = datetime.now().month
        if current_month != self._last_reset_month:
            logger.info(
                f"Monthly cost reset: ${self._current_month_cost:.2f} "
                f"(month {self._last_reset_month} → {current_month})"
            )
            self._current_month_cost = 0.0
            self._usage_records = []
            self._cost_by_agent = {}
            self._cost_by_model = {}
            self._alerts = []
            self._last_reset_month = current_month

    def _check_alerts(self) -> None:
        """Vérifie et génère les alertes si nécessaire."""
        if not self.monthly_budget:
            return

        percentage = self._current_month_cost / self.monthly_budget

        # Critical alert
        if percentage >= self.critical_threshold:
            self._create_alert(
                AlertLevel.CRITICAL,
                f"Budget critique! {percentage*100:.1f}% utilisé "
                f"(${self._current_month_cost:.2f}/${self.monthly_budget:.2f})",
            )
        # Warning alert
        elif percentage >= self.warning_threshold:
            self._create_alert(
                AlertLevel.WARNING,
                f"Budget warning: {percentage*100:.1f}% utilisé "
                f"(${self._current_month_cost:.2f}/${self.monthly_budget:.2f})",
            )

    def _create_alert(self, level: AlertLevel, message: str) -> None:
        """Crée une alerte si elle n'existe pas déjà pour ce niveau."""
        # Éviter les alertes dupliquées du même niveau
        existing = [a for a in self._alerts if a.level == level]
        if existing:
            return

        alert = CostAlert(
            level=level,
            message=message,
            current_cost=self._current_month_cost,
            threshold=self.monthly_budget * (
                self.critical_threshold if level == AlertLevel.CRITICAL
                else self.warning_threshold
            ),
        )

        self._alerts.append(alert)
        logger.warning(f"Cost alert [{level.value}]: {message}")

        if self.on_alert:
            self.on_alert(alert)


class BudgetExceededError(Exception):
    """Exception levée quand le budget est dépassé."""

    def __init__(self, current_cost: float, budget: float):
        self.current_cost = current_cost
        self.budget = budget
        super().__init__(
            f"Budget exceeded: ${current_cost:.2f} / ${budget:.2f} "
            f"({(current_cost/budget)*100:.1f}%)"
        )


# Instance globale
cost_manager = CostManager()


def get_cost_manager() -> CostManager:
    """Retourne l'instance globale du gestionnaire de coûts."""
    return cost_manager
