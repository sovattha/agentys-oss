# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Monitoring et détection des échecs background pour Agentys.

Ce module permet de :
- Détecter les échecs silencieux en arrière-plan
- Monitorer l'état de santé des différents composants
- Alerter en cas de problèmes détectés
- Collecter des métriques de santé

Usage:
    from app.infrastructure.monitoring import HealthMonitor, get_health_monitor

    monitor = get_health_monitor()
    monitor.register_component("daemon", check_daemon_health)
    monitor.start()

    # Plus tard
    status = monitor.get_status()
    if not status.healthy:
        print(f"Problèmes détectés: {status.issues}")
"""

import time
import threading
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any
from enum import Enum
from collections import deque


# ============================================================================
# MODÈLES
# ============================================================================

class HealthStatus(Enum):
    """Statut de santé d'un composant."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class FailureType(Enum):
    """Types d'échecs détectés."""
    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    THRESHOLD_EXCEEDED = "threshold_exceeded"
    SILENT_FAILURE = "silent_failure"
    CONNECTIVITY = "connectivity"
    RATE_LIMIT = "rate_limit"


@dataclass
class HealthCheck:
    """Résultat d'un health check."""
    component: str
    status: HealthStatus
    message: str = ""
    timestamp: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class FailureEvent:
    """Événement d'échec détecté."""
    component: str
    failure_type: FailureType
    message: str
    timestamp: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolution_timestamp: Optional[str] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class MonitoringStatus:
    """Statut global du monitoring."""
    healthy: bool
    status: HealthStatus
    components: Dict[str, HealthCheck]
    issues: List[str]
    last_check: str
    uptime_seconds: float


# ============================================================================
# HEALTH MONITOR
# ============================================================================

class HealthMonitor:
    """
    Moniteur de santé pour détecter les échecs background silencieux.

    Features:
    - Health checks périodiques sur les composants
    - Détection des échecs silencieux (pas d'activité)
    - Alertes configurables
    - Historique des échecs
    """

    def __init__(
        self,
        check_interval: float = 60.0,
        failure_threshold: int = 3,
        alert_callback: Optional[Callable[[FailureEvent], None]] = None
    ):
        """
        Initialise le moniteur de santé.

        Args:
            check_interval: Intervalle entre les checks (secondes)
            failure_threshold: Nombre d'échecs avant alerte
            alert_callback: Fonction appelée lors d'une alerte
        """
        self.check_interval = check_interval
        self.failure_threshold = failure_threshold
        self.alert_callback = alert_callback

        self._components: Dict[str, Callable[[], HealthCheck]] = {}
        self._heartbeats: Dict[str, datetime] = {}
        self._failure_counts: Dict[str, int] = {}
        self._failure_history: deque = deque(maxlen=1000)
        self._last_checks: Dict[str, HealthCheck] = {}

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        self._start_time = datetime.now()

        self.logger = logging.getLogger(__name__)

    def register_component(
        self,
        name: str,
        check_func: Callable[[], HealthCheck],
        heartbeat_timeout: Optional[float] = None
    ) -> None:
        """
        Enregistre un composant à surveiller.

        Args:
            name: Nom du composant
            check_func: Fonction de health check
            heartbeat_timeout: Timeout pour heartbeat (optionnel)
        """
        with self._lock:
            self._components[name] = check_func
            self._failure_counts[name] = 0
            if heartbeat_timeout:
                self._heartbeats[name] = datetime.now()

        self.logger.info(f"Composant enregistré pour monitoring: {name}")

    def unregister_component(self, name: str) -> None:
        """Désenregistre un composant."""
        with self._lock:
            self._components.pop(name, None)
            self._heartbeats.pop(name, None)
            self._failure_counts.pop(name, None)

    def heartbeat(self, component: str) -> None:
        """
        Enregistre un heartbeat pour un composant.

        À appeler régulièrement par les composants pour signaler qu'ils sont actifs.

        Args:
            component: Nom du composant
        """
        with self._lock:
            self._heartbeats[component] = datetime.now()
            # Reset failure count on heartbeat
            self._failure_counts[component] = 0

    def record_failure(
        self,
        component: str,
        failure_type: FailureType,
        message: str,
        details: Optional[Dict] = None
    ) -> None:
        """
        Enregistre un échec pour un composant.

        Args:
            component: Nom du composant
            failure_type: Type d'échec
            message: Message d'erreur
            details: Détails supplémentaires
        """
        with self._lock:
            self._failure_counts[component] = self._failure_counts.get(component, 0) + 1

            event = FailureEvent(
                component=component,
                failure_type=failure_type,
                message=message,
                details=details or {}
            )
            self._failure_history.append(event)

            # Alerte si seuil atteint
            if self._failure_counts[component] >= self.failure_threshold:
                self._trigger_alert(event)

        self.logger.warning(f"Échec enregistré pour {component}: {message}")

    def record_success(self, component: str) -> None:
        """
        Enregistre un succès pour un composant.

        Reset le compteur d'échecs.

        Args:
            component: Nom du composant
        """
        with self._lock:
            self._failure_counts[component] = 0
            self._heartbeats[component] = datetime.now()

    def get_status(self) -> MonitoringStatus:
        """
        Retourne le statut global du monitoring.

        Returns:
            MonitoringStatus avec l'état de tous les composants
        """
        with self._lock:
            components = {}
            issues = []
            overall_status = HealthStatus.HEALTHY

            for name, check_func in self._components.items():
                try:
                    check = check_func()
                    components[name] = check
                    self._last_checks[name] = check

                    if check.status == HealthStatus.UNHEALTHY:
                        issues.append(f"{name}: {check.message}")
                        overall_status = HealthStatus.UNHEALTHY
                    elif check.status == HealthStatus.DEGRADED and overall_status == HealthStatus.HEALTHY:
                        overall_status = HealthStatus.DEGRADED

                except Exception as e:
                    check = HealthCheck(
                        component=name,
                        status=HealthStatus.UNKNOWN,
                        message=f"Check failed: {e}"
                    )
                    components[name] = check
                    issues.append(f"{name}: check failed - {e}")

            # Vérifier les heartbeats
            heartbeat_issues = self._check_heartbeats()
            issues.extend(heartbeat_issues)
            if heartbeat_issues:
                overall_status = HealthStatus.UNHEALTHY

            uptime = (datetime.now() - self._start_time).total_seconds()

            return MonitoringStatus(
                healthy=overall_status == HealthStatus.HEALTHY,
                status=overall_status,
                components=components,
                issues=issues,
                last_check=datetime.now().isoformat(),
                uptime_seconds=uptime
            )

    def get_failure_history(self, component: Optional[str] = None, limit: int = 100) -> List[FailureEvent]:
        """
        Retourne l'historique des échecs.

        Args:
            component: Filtrer par composant (optionnel)
            limit: Nombre maximum d'événements

        Returns:
            Liste des événements d'échec
        """
        with self._lock:
            history = list(self._failure_history)
            if component:
                history = [e for e in history if e.component == component]
            return history[-limit:]

    def get_component_stats(self, component: str) -> Dict[str, Any]:
        """
        Retourne les statistiques d'un composant.

        Args:
            component: Nom du composant

        Returns:
            Dictionnaire de statistiques
        """
        with self._lock:
            failures = [e for e in self._failure_history if e.component == component]
            last_check = self._last_checks.get(component)
            last_heartbeat = self._heartbeats.get(component)

            return {
                "component": component,
                "failure_count": self._failure_counts.get(component, 0),
                "total_failures": len(failures),
                "last_check": last_check.timestamp if last_check else None,
                "last_status": last_check.status.value if last_check else "unknown",
                "last_heartbeat": last_heartbeat.isoformat() if last_heartbeat else None,
                "registered": component in self._components,
            }

    def start(self) -> None:
        """Démarre le monitoring en background."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

        self.logger.info("Monitoring démarré")

    def stop(self) -> None:
        """Arrête le monitoring."""
        self._running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        self.logger.info("Monitoring arrêté")

    def _monitor_loop(self) -> None:
        """Boucle principale de monitoring."""
        while self._running:
            try:
                self._run_checks()
            except Exception as e:
                self.logger.error(f"Erreur dans la boucle de monitoring: {e}")

            # Attendre le prochain cycle
            self._stop_event.wait(self.check_interval)

    def _run_checks(self) -> None:
        """Exécute tous les health checks."""
        with self._lock:
            for name, check_func in self._components.items():
                try:
                    check = check_func()
                    self._last_checks[name] = check

                    if check.status == HealthStatus.UNHEALTHY:
                        self.record_failure(
                            name,
                            FailureType.THRESHOLD_EXCEEDED,
                            check.message,
                            check.details
                        )
                    else:
                        self.record_success(name)

                except Exception as e:
                    self.record_failure(
                        name,
                        FailureType.EXCEPTION,
                        str(e)
                    )

            # Vérifier les heartbeats
            self._check_heartbeats()

    def _check_heartbeats(self) -> List[str]:
        """Vérifie les heartbeats et retourne les problèmes."""
        issues = []
        now = datetime.now()
        timeout = timedelta(seconds=self.check_interval * 3)

        for component, last_heartbeat in self._heartbeats.items():
            if now - last_heartbeat > timeout:
                issue = f"{component}: pas de heartbeat depuis {(now - last_heartbeat).seconds}s"
                issues.append(issue)

                self.record_failure(
                    component,
                    FailureType.SILENT_FAILURE,
                    issue
                )

        return issues

    def _trigger_alert(self, event: FailureEvent) -> None:
        """Déclenche une alerte."""
        self.logger.error(f"ALERTE: {event.component} - {event.message}")

        if self.alert_callback:
            try:
                self.alert_callback(event)
            except Exception as e:
                self.logger.error(f"Erreur dans le callback d'alerte: {e}")


# ============================================================================
# HEALTH CHECKS PRÉDÉFINIS
# ============================================================================

def check_disk_space(
    path: str = "/",
    warning_threshold: float = 80.0,
    critical_threshold: float = 95.0
) -> Callable[[], HealthCheck]:
    """
    Crée une fonction de check d'espace disque.

    Args:
        path: Chemin à vérifier
        warning_threshold: Seuil d'avertissement (%)
        critical_threshold: Seuil critique (%)

    Returns:
        Fonction de health check
    """
    def check() -> HealthCheck:
        try:
            import shutil
            total, used, free = shutil.disk_usage(path)
            usage_percent = (used / total) * 100

            if usage_percent >= critical_threshold:
                status = HealthStatus.UNHEALTHY
                message = f"Espace disque critique: {usage_percent:.1f}%"
            elif usage_percent >= warning_threshold:
                status = HealthStatus.DEGRADED
                message = f"Espace disque faible: {usage_percent:.1f}%"
            else:
                status = HealthStatus.HEALTHY
                message = f"Espace disque OK: {usage_percent:.1f}%"

            return HealthCheck(
                component="disk_space",
                status=status,
                message=message,
                details={
                    "total_gb": round(total / (1024**3), 2),
                    "used_gb": round(used / (1024**3), 2),
                    "free_gb": round(free / (1024**3), 2),
                    "usage_percent": round(usage_percent, 1),
                }
            )
        except Exception as e:
            return HealthCheck(
                component="disk_space",
                status=HealthStatus.UNKNOWN,
                message=str(e)
            )

    return check


def check_memory_usage(
    warning_threshold: float = 80.0,
    critical_threshold: float = 95.0
) -> Callable[[], HealthCheck]:
    """
    Crée une fonction de check mémoire.

    Args:
        warning_threshold: Seuil d'avertissement (%)
        critical_threshold: Seuil critique (%)

    Returns:
        Fonction de health check
    """
    def check() -> HealthCheck:
        try:
            import psutil
            memory = psutil.virtual_memory()
            usage_percent = memory.percent

            if usage_percent >= critical_threshold:
                status = HealthStatus.UNHEALTHY
                message = f"Mémoire critique: {usage_percent:.1f}%"
            elif usage_percent >= warning_threshold:
                status = HealthStatus.DEGRADED
                message = f"Mémoire faible: {usage_percent:.1f}%"
            else:
                status = HealthStatus.HEALTHY
                message = f"Mémoire OK: {usage_percent:.1f}%"

            return HealthCheck(
                component="memory",
                status=status,
                message=message,
                details={
                    "total_gb": round(memory.total / (1024**3), 2),
                    "used_gb": round(memory.used / (1024**3), 2),
                    "available_gb": round(memory.available / (1024**3), 2),
                    "usage_percent": round(usage_percent, 1),
                }
            )
        except ImportError:
            return HealthCheck(
                component="memory",
                status=HealthStatus.UNKNOWN,
                message="psutil non disponible"
            )
        except Exception as e:
            return HealthCheck(
                component="memory",
                status=HealthStatus.UNKNOWN,
                message=str(e)
            )

    return check


def check_api_connectivity(
    url: str,
    timeout: float = 5.0,
    component_name: str = "api"
) -> Callable[[], HealthCheck]:
    """
    Crée une fonction de check de connectivité API.

    Args:
        url: URL à tester
        timeout: Timeout en secondes
        component_name: Nom du composant

    Returns:
        Fonction de health check
    """
    def check() -> HealthCheck:
        try:
            import urllib.request
            import urllib.error

            start = time.time()
            request = urllib.request.Request(url, method='HEAD')
            urllib.request.urlopen(request, timeout=timeout)
            latency = (time.time() - start) * 1000

            return HealthCheck(
                component=component_name,
                status=HealthStatus.HEALTHY,
                message=f"API accessible (latence: {latency:.0f}ms)",
                details={"latency_ms": round(latency), "url": url}
            )
        except urllib.error.URLError as e:
            return HealthCheck(
                component=component_name,
                status=HealthStatus.UNHEALTHY,
                message=f"API inaccessible: {e.reason}",
                details={"url": url}
            )
        except Exception as e:
            return HealthCheck(
                component=component_name,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                details={"url": url}
            )

    return check


# ============================================================================
# SINGLETON
# ============================================================================

_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Retourne l'instance singleton du moniteur de santé."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor


def setup_default_monitoring(alert_callback: Optional[Callable] = None) -> HealthMonitor:
    """
    Configure le monitoring avec les checks par défaut.

    Args:
        alert_callback: Callback pour les alertes

    Returns:
        Instance configurée du moniteur
    """
    monitor = get_health_monitor()
    monitor.alert_callback = alert_callback

    # Enregistrer les checks par défaut
    monitor.register_component("disk_space", check_disk_space())

    # Memory check (si psutil disponible)
    import importlib.util
    if importlib.util.find_spec("psutil") is not None:
        monitor.register_component("memory", check_memory_usage())

    return monitor
