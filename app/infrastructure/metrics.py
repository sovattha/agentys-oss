# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Métriques Prometheus pour Agentys.

Expose des métriques au format Prometheus pour le monitoring :
- Emails traités (total, par catégorie)
- Temps de traitement
- Coûts API
- Erreurs

Usage:
    from app.infrastructure.metrics import metrics, start_metrics_server

    # Incrémenter un compteur
    metrics.emails_processed.labels(category="URGENT", status="V1").inc()

    # Enregistrer un temps
    with metrics.processing_time.labels(agent="drafter").time():
        # ... traitement ...

    # Démarrer le serveur de métriques
    start_metrics_server(port=9090)
"""

import os
import time
from typing import Optional, Any
from dataclasses import dataclass
from contextlib import contextmanager

# prometheus_client est optionnel
try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        Summary,
        Info,
        start_http_server,
        REGISTRY,
        CollectorRegistry,
        generate_latest,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

    # Stubs pour quand prometheus n'est pas disponible
    class _StubLabeled:
        """Stub pour les métriques avec labels."""
        def inc(self, amount: float = 1) -> None: pass
        def dec(self, amount: float = 1) -> None: pass
        def set(self, value: float) -> None: pass
        def observe(self, value: float) -> None: pass
        @contextmanager
        def time(self):
            yield

    class _StubMetric:
        """Stub pour une métrique sans labels."""
        def labels(self, **kwargs) -> _StubLabeled:
            return _StubLabeled()
        def inc(self, amount: float = 1) -> None: pass
        def dec(self, amount: float = 1) -> None: pass
        def set(self, value: float) -> None: pass
        def observe(self, value: float) -> None: pass
        def info(self, val: dict) -> None: pass
        @contextmanager
        def time(self):
            yield

    class Counter(_StubMetric):  # type: ignore
        def __init__(self, *args, **kwargs): pass

    class Gauge(_StubMetric):  # type: ignore
        def __init__(self, *args, **kwargs): pass

    class Histogram(_StubMetric):  # type: ignore
        def __init__(self, *args, **kwargs): pass

    class Summary(_StubMetric):  # type: ignore
        def __init__(self, *args, **kwargs): pass

    class Info(_StubMetric):  # type: ignore
        def __init__(self, *args, **kwargs): pass

    class CollectorRegistry:  # type: ignore
        pass

    REGISTRY = CollectorRegistry()

    def start_http_server(port: int) -> None:  # type: ignore
        pass

    def generate_latest(registry: Any) -> bytes:  # type: ignore
        return b"# prometheus_client not installed\n"

from app.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

METRICS_PORT = int(os.getenv("METRICS_PORT", "9090"))
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"


# ============================================================================
# MÉTRIQUES
# ============================================================================

@dataclass
class AgentysMetrics:
    """
    Collection de métriques Prometheus pour Agentys.

    Organise toutes les métriques en un seul endroit pour faciliter
    leur utilisation dans le code.
    """

    def __init__(self, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or REGISTRY
        self._setup_metrics()

    def _setup_metrics(self) -> None:
        """Configure toutes les métriques."""

        # ====== COMPTEURS ======

        # Emails traités
        self.emails_processed = Counter(
            "agentys_emails_processed_total",
            "Total number of emails processed",
            labelnames=["category", "status"],
            registry=self.registry,
        )

        # Brouillons créés
        self.drafts_created = Counter(
            "agentys_drafts_created_total",
            "Total number of drafts created",
            labelnames=["version", "provider"],
            registry=self.registry,
        )

        # Appels API LLM
        self.llm_requests = Counter(
            "agentys_llm_requests_total",
            "Total number of LLM API requests",
            labelnames=["model", "agent"],
            registry=self.registry,
        )

        # Erreurs
        self.errors = Counter(
            "agentys_errors_total",
            "Total number of errors",
            labelnames=["type", "component"],
            registry=self.registry,
        )

        # Follow-ups
        self.followups_sent = Counter(
            "agentys_followups_sent_total",
            "Total number of follow-up emails sent",
            registry=self.registry,
        )

        # ====== JAUGES ======

        # Emails en attente
        self.emails_pending = Gauge(
            "agentys_emails_pending",
            "Number of emails waiting to be processed",
            registry=self.registry,
        )

        # Budget restant
        self.budget_remaining = Gauge(
            "agentys_budget_remaining_usd",
            "Remaining monthly budget in USD",
            registry=self.registry,
        )

        # Coût du mois
        self.monthly_cost = Gauge(
            "agentys_monthly_cost_usd",
            "Current month cost in USD",
            registry=self.registry,
        )

        # Circuit breakers
        self.circuit_breaker_state = Gauge(
            "agentys_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=half-open, 2=open)",
            labelnames=["name"],
            registry=self.registry,
        )

        # Daemon status
        self.daemon_running = Gauge(
            "agentys_daemon_running",
            "Whether the daemon is running (1=yes, 0=no)",
            registry=self.registry,
        )

        # ====== HISTOGRAMMES ======

        # Temps de traitement email
        self.processing_time = Histogram(
            "agentys_processing_duration_seconds",
            "Time spent processing an email",
            labelnames=["agent"],
            buckets=[0.5, 1, 2, 5, 10, 30, 60, 120],
            registry=self.registry,
        )

        # Tokens utilisés par requête
        self.tokens_per_request = Histogram(
            "agentys_tokens_per_request",
            "Number of tokens used per LLM request",
            labelnames=["model", "type"],  # type = input/output
            buckets=[100, 500, 1000, 2000, 5000, 10000, 20000],
            registry=self.registry,
        )

        # ====== SUMMARY ======

        # Latence API email
        self.email_api_latency = Summary(
            "agentys_email_api_latency_seconds",
            "Latency of email provider API calls",
            labelnames=["provider", "operation"],
            registry=self.registry,
        )

        # ====== INFO ======

        # Version et config
        self.info = Info(
            "agentys",
            "Agentys application information",
            registry=self.registry,
        )
        self.info.info({
            "version": "1.0.0",
            "environment": os.getenv("ENVIRONMENT", "development"),
        })

    # ====== HELPERS ======

    def record_email_processed(
        self,
        category: str,
        status: str,
        processing_time: float
    ) -> None:
        """Enregistre le traitement d'un email."""
        self.emails_processed.labels(category=category, status=status).inc()
        self.processing_time.labels(agent="pipeline").observe(processing_time)

    def record_llm_call(
        self,
        model: str,
        agent: str,
        input_tokens: int,
        output_tokens: int,
        duration: float
    ) -> None:
        """Enregistre un appel LLM."""
        self.llm_requests.labels(model=model, agent=agent).inc()
        self.tokens_per_request.labels(model=model, type="input").observe(input_tokens)
        self.tokens_per_request.labels(model=model, type="output").observe(output_tokens)
        self.processing_time.labels(agent=agent).observe(duration)

    def record_error(self, error_type: str, component: str) -> None:
        """Enregistre une erreur."""
        self.errors.labels(type=error_type, component=component).inc()

    def update_budget(self, spent: float, remaining: float) -> None:
        """Met à jour les métriques de budget."""
        self.monthly_cost.set(spent)
        self.budget_remaining.set(remaining)


# ============================================================================
# SERVEUR DE MÉTRIQUES
# ============================================================================

_metrics_server_started = False
_metrics: Optional[AgentysMetrics] = None


def get_metrics() -> AgentysMetrics:
    """Retourne l'instance singleton des métriques."""
    global _metrics
    if _metrics is None:
        _metrics = AgentysMetrics()
    return _metrics


def start_metrics_server(port: int = METRICS_PORT) -> bool:
    """
    Démarre le serveur HTTP de métriques Prometheus.

    Args:
        port: Port sur lequel exposer les métriques

    Returns:
        True si démarré avec succès, False sinon
    """
    global _metrics_server_started

    if not PROMETHEUS_AVAILABLE:
        logger.warning(
            "prometheus_client package not installed - metrics disabled. "
            "Install with: pip install prometheus-client"
        )
        return False

    if not METRICS_ENABLED:
        logger.info("Prometheus metrics disabled")
        return False

    if _metrics_server_started:
        logger.warning("Metrics server already started")
        return True

    try:
        start_http_server(port)
        _metrics_server_started = True
        logger.info(f"Prometheus metrics available at http://localhost:{port}/metrics")
        return True
    except Exception as e:
        logger.error(f"Failed to start metrics server: {e}")
        return False


def get_metrics_text() -> str:
    """Retourne les métriques au format texte Prometheus."""
    return generate_latest(REGISTRY).decode("utf-8")


# ============================================================================
# DÉCORATEURS
# ============================================================================

def timed(metric_name: str = "processing", agent: str = "unknown"):
    """
    Décorateur pour mesurer le temps d'exécution d'une fonction.

    Usage:
        @timed(agent="drafter")
        def generate_draft(...):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            metrics = get_metrics()
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                metrics.processing_time.labels(agent=agent).observe(duration)
        return wrapper
    return decorator


def count_errors(component: str):
    """
    Décorateur pour compter les erreurs d'une fonction.

    Usage:
        @count_errors(component="email_provider")
        def fetch_emails():
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            metrics = get_metrics()
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_type = type(e).__name__
                metrics.record_error(error_type, component)
                raise
        return wrapper
    return decorator


# ============================================================================
# FLASK ENDPOINT
# ============================================================================

def create_metrics_blueprint():
    """
    Crée un blueprint Flask pour exposer les métriques.

    Usage:
        from app.infrastructure.metrics import create_metrics_blueprint
        app.register_blueprint(create_metrics_blueprint(), url_prefix="/")
    """
    from flask import Blueprint, Response

    metrics_bp = Blueprint("metrics", __name__)

    @metrics_bp.route("/metrics")
    def metrics_endpoint():
        return Response(get_metrics_text(), mimetype="text/plain")

    return metrics_bp
