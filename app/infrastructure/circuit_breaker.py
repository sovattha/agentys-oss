# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Module Circuit Breaker pour la gestion des APIs externes.

Le circuit breaker protège l'application contre les cascades d'échecs
en coupant temporairement les appels vers un service défaillant.

États:
- CLOSED: Fonctionnement normal, les appels passent
- OPEN: Circuit ouvert, les appels sont rejetés immédiatement
- HALF_OPEN: Test de récupération, quelques appels autorisés
"""

import time
import logging
import threading
from enum import Enum
from typing import Callable, Any, Optional, Dict
from functools import wraps
from dataclasses import dataclass
from datetime import datetime

from app.config import DEFAULT_CIRCUIT_BREAKER_CONFIG

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """États possibles du circuit breaker."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Levée quand le circuit est ouvert et rejette les appels."""

    def __init__(self, service_name: str, remaining_time: float):
        self.service_name = service_name
        self.remaining_time = remaining_time
        super().__init__(
            f"Circuit ouvert pour '{service_name}'. "
            f"Réessayer dans {remaining_time:.1f}s"
        )


@dataclass
class CircuitBreakerStats:
    """Statistiques du circuit breaker."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    current_state: CircuitState = CircuitState.CLOSED
    state_changes: int = 0


class CircuitBreaker:
    """
    Implémentation du pattern Circuit Breaker.

    Le circuit breaker surveille les appels vers un service externe
    et coupe le circuit si trop d'échecs se produisent.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: Optional[int] = None,
        recovery_timeout: Optional[int] = None,
        half_open_max_calls: Optional[int] = None,
        excluded_exceptions: tuple = (),
    ):
        """
        Initialise le circuit breaker.

        Args:
            name: Nom du service protégé (pour les logs).
            failure_threshold: Nombre d'échecs avant ouverture.
            recovery_timeout: Temps en secondes avant test de récupération.
            half_open_max_calls: Appels autorisés en half-open.
            excluded_exceptions: Exceptions qui ne comptent pas comme échec.
        """
        config = DEFAULT_CIRCUIT_BREAKER_CONFIG

        self.name = name
        self.failure_threshold = failure_threshold or config.failure_threshold
        self.recovery_timeout = recovery_timeout or config.recovery_timeout
        self.half_open_max_calls = half_open_max_calls or config.half_open_max_calls
        self.excluded_exceptions = excluded_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time = 0.0
        self._lock = threading.RLock()

        # Stats
        self._stats = CircuitBreakerStats()

    @property
    def state(self) -> CircuitState:
        """Retourne l'état actuel du circuit."""
        with self._lock:
            # Vérifier si on doit passer de OPEN à HALF_OPEN
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._transition_to(CircuitState.HALF_OPEN)
            return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        """Retourne les statistiques du circuit."""
        with self._lock:
            self._stats.current_state = self._state
            return self._stats

    def _transition_to(self, new_state: CircuitState) -> None:
        """Change l'état du circuit."""
        old_state = self._state
        self._state = new_state
        self._stats.state_changes += 1

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0

        logger.info(
            f"Circuit '{self.name}': {old_state.value} -> {new_state.value}"
        )

    def _handle_success(self) -> None:
        """Gère un appel réussi."""
        with self._lock:
            self._stats.successful_calls += 1
            self._stats.last_success_time = datetime.now()

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                # Si assez de succès en half-open, fermer le circuit
                if self._success_count >= self.half_open_max_calls:
                    self._failure_count = 0
                    self._transition_to(CircuitState.CLOSED)
            else:
                # En CLOSED, réinitialiser les échecs
                self._failure_count = 0

    def _handle_failure(self, exception: Exception) -> None:
        """Gère un appel échoué."""
        with self._lock:
            # Ignorer certaines exceptions
            if isinstance(exception, self.excluded_exceptions):
                return

            self._stats.failed_calls += 1
            self._stats.last_failure_time = datetime.now()
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Échec en half-open -> retour à open
                self._transition_to(CircuitState.OPEN)
            elif self._failure_count >= self.failure_threshold:
                # Seuil atteint -> ouvrir le circuit
                self._transition_to(CircuitState.OPEN)
                logger.warning(
                    f"[WARN] Circuit '{self.name}' ouvert après {self._failure_count} échecs"
                )

    def _can_execute(self) -> bool:
        """Vérifie si un appel peut être exécuté."""
        state = self.state  # Déclenche la vérification de transition

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            remaining = self.recovery_timeout - (time.time() - self._last_failure_time)
            if remaining > 0:
                self._stats.rejected_calls += 1
                raise CircuitOpenError(self.name, remaining)
            return False

        if state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                self._stats.rejected_calls += 1
                raise CircuitOpenError(self.name, 0)

        return False

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Exécute une fonction avec protection circuit breaker.

        Args:
            func: Fonction à exécuter.
            *args: Arguments positionnels.
            **kwargs: Arguments nommés.

        Returns:
            Résultat de la fonction.

        Raises:
            CircuitOpenError: Si le circuit est ouvert.
            Exception: L'exception originale si l'appel échoue.
        """
        self._stats.total_calls += 1
        self._can_execute()

        try:
            result = func(*args, **kwargs)
            self._handle_success()
            return result
        except Exception as e:
            self._handle_failure(e)
            raise

    def reset(self) -> None:
        """Réinitialise le circuit breaker."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            logger.info(f"[RESET] Circuit '{self.name}' réinitialisé")


# Registry global des circuit breakers
_circuit_breakers: Dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_circuit_breaker(name: str, **kwargs) -> CircuitBreaker:
    """
    Obtient ou crée un circuit breaker par nom.

    Args:
        name: Nom du service.
        **kwargs: Paramètres de configuration.

    Returns:
        L'instance du circuit breaker.
    """
    with _registry_lock:
        if name not in _circuit_breakers:
            _circuit_breakers[name] = CircuitBreaker(name, **kwargs)
        return _circuit_breakers[name]


def circuit_breaker(
    name: str,
    failure_threshold: Optional[int] = None,
    recovery_timeout: Optional[int] = None,
    excluded_exceptions: tuple = (),
):
    """
    Décorateur pour protéger une fonction avec un circuit breaker.

    Args:
        name: Nom du service.
        failure_threshold: Seuil d'échecs.
        recovery_timeout: Timeout de récupération.
        excluded_exceptions: Exceptions à ignorer.

    Example:
        @circuit_breaker("gmail_api")
        def fetch_emails():
            return gmail.users().messages().list().execute()
    """
    def decorator(func: Callable) -> Callable:
        cb = get_circuit_breaker(
            name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            excluded_exceptions=excluded_exceptions,
        )

        @wraps(func)
        def wrapper(*args, **kwargs):
            return cb.call(func, *args, **kwargs)

        # Exposer le circuit breaker pour les tests
        wrapper.circuit_breaker = cb
        return wrapper

    return decorator


def get_all_circuit_breakers() -> Dict[str, CircuitBreaker]:
    """Retourne tous les circuit breakers enregistrés."""
    with _registry_lock:
        return dict(_circuit_breakers)


def reset_all_circuit_breakers() -> None:
    """Réinitialise tous les circuit breakers."""
    with _registry_lock:
        for cb in _circuit_breakers.values():
            cb.reset()
