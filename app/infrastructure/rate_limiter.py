# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Module de gestion des rate limits pour les APIs externes.

Fournit:
- Rate limiting par fenêtre glissante
- Support pour tokens/minute et requêtes/minute
- Intégration avec les headers de réponse API
"""

import time
import threading
import logging
from typing import Optional, Dict, Callable
from collections import deque
from functools import wraps
from dataclasses import dataclass

from app.config import DEFAULT_RATE_LIMIT_CONFIG

logger = logging.getLogger(__name__)


class RateLimitExceededError(Exception):
    """Levée quand le rate limit est dépassé."""

    def __init__(self, limiter_name: str, wait_time: float):
        self.limiter_name = limiter_name
        self.wait_time = wait_time
        super().__init__(
            f"Rate limit dépassé pour '{limiter_name}'. "
            f"Attendre {wait_time:.1f}s"
        )


@dataclass
class RateLimitStats:
    """Statistiques du rate limiter."""
    total_requests: int = 0
    allowed_requests: int = 0
    rejected_requests: int = 0
    total_wait_time: float = 0.0
    current_rate: float = 0.0


class SlidingWindowRateLimiter:
    """
    Rate limiter utilisant une fenêtre glissante.

    Plus précis que le token bucket pour des limites exactes.
    """

    def __init__(
        self,
        name: str,
        max_requests: int,
        window_seconds: float,
        blocking: bool = True,
    ):
        """
        Initialise le rate limiter.

        Args:
            name: Nom du limiter (pour les logs).
            max_requests: Nombre maximum de requêtes dans la fenêtre.
            window_seconds: Durée de la fenêtre en secondes.
            blocking: Si True, attend au lieu de rejeter.
        """
        self.name = name
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.blocking = blocking

        self._timestamps: deque = deque()
        self._lock = threading.Lock()
        self._stats = RateLimitStats()

    def _cleanup_old_requests(self, now: float) -> None:
        """Supprime les requêtes hors de la fenêtre.

        window_seconds=0 → fenêtre de durée nulle, rien n'expire (cas edge).
        Sans ce guard, cutoff=now fait pop de tous les timestamps car
        `ts < now` est vrai pour toute requête antérieure.
        """
        if self.window_seconds <= 0:
            return
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def _get_wait_time(self, now: float) -> float:
        """Calcule le temps d'attente nécessaire."""
        if len(self._timestamps) < self.max_requests:
            return 0.0

        # Si la queue est vide (cas max_requests <= 0), retourner window_seconds
        if not self._timestamps:
            return self.window_seconds if self.window_seconds > 0 else 0.0

        oldest = self._timestamps[0]
        wait = (oldest + self.window_seconds) - now
        return max(0.0, wait)

    def acquire(self, count: int = 1) -> bool:
        """
        Tente d'acquérir un slot pour une requête.

        Args:
            count: Nombre de slots à acquérir.

        Returns:
            True si acquis, False si rejeté.

        Raises:
            RateLimitExceededError: Si blocking=False et limite atteinte.
        """
        with self._lock:
            now = time.time()
            self._cleanup_old_requests(now)
            self._stats.total_requests += count

            # Vérifier si on a de la place
            if len(self._timestamps) + count <= self.max_requests:
                for _ in range(count):
                    self._timestamps.append(now)
                self._stats.allowed_requests += count
                self._update_current_rate()
                return True

            # Rate limit atteint
            wait_time = self._get_wait_time(now)

            if self.blocking and wait_time > 0:
                logger.debug(f"⏳ Rate limit '{self.name}': attente {wait_time:.1f}s")
                self._stats.total_wait_time += wait_time
                time.sleep(wait_time)

                # Réessayer après l'attente
                now = time.time()
                self._cleanup_old_requests(now)

                if len(self._timestamps) + count <= self.max_requests:
                    for _ in range(count):
                        self._timestamps.append(now)
                    self._stats.allowed_requests += count
                    self._update_current_rate()
                    return True

            self._stats.rejected_requests += count

            if not self.blocking:
                raise RateLimitExceededError(self.name, wait_time)

            return False

    def _update_current_rate(self) -> None:
        """Met à jour le taux de requêtes actuel."""
        if self.window_seconds > 0:
            self._stats.current_rate = len(self._timestamps) / self.window_seconds

    @property
    def stats(self) -> RateLimitStats:
        """Retourne les statistiques."""
        with self._lock:
            return self._stats

    def reset(self) -> None:
        """Réinitialise le rate limiter."""
        with self._lock:
            self._timestamps.clear()
            logger.debug(f"[RESET] Rate limiter '{self.name}' réinitialisé")


class TokenBucketRateLimiter:
    """
    Rate limiter utilisant l'algorithme Token Bucket.

    Permet des bursts tout en maintenant un taux moyen.
    """

    def __init__(
        self,
        name: str,
        tokens_per_second: float,
        max_tokens: int,
        blocking: bool = True,
    ):
        """
        Initialise le rate limiter.

        Args:
            name: Nom du limiter.
            tokens_per_second: Taux de remplissage.
            max_tokens: Capacité maximum du bucket.
            blocking: Si True, attend au lieu de rejeter.
        """
        self.name = name
        self.tokens_per_second = tokens_per_second
        self.max_tokens = max_tokens
        self.blocking = blocking

        self._tokens = float(max_tokens)
        self._last_update = time.time()
        self._lock = threading.Lock()
        self._stats = RateLimitStats()

    def _refill(self) -> None:
        """Remplit le bucket avec les tokens accumulés."""
        now = time.time()
        elapsed = now - self._last_update
        self._tokens = min(
            self.max_tokens,
            self._tokens + elapsed * self.tokens_per_second
        )
        self._last_update = now

    def acquire(self, tokens: int = 1) -> bool:
        """
        Tente d'acquérir des tokens.

        Args:
            tokens: Nombre de tokens à acquérir.

        Returns:
            True si acquis.

        Raises:
            RateLimitExceededError: Si blocking=False et pas assez de tokens.
        """
        with self._lock:
            self._refill()
            self._stats.total_requests += 1

            if self._tokens >= tokens:
                self._tokens -= tokens
                self._stats.allowed_requests += 1
                return True

            # Pas assez de tokens
            if self.blocking:
                wait_time = (tokens - self._tokens) / self.tokens_per_second
                logger.debug(f"⏳ Token bucket '{self.name}': attente {wait_time:.1f}s")
                self._stats.total_wait_time += wait_time
                time.sleep(wait_time)

                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    self._stats.allowed_requests += 1
                    return True

            self._stats.rejected_requests += 1

            if not self.blocking:
                wait_time = (tokens - self._tokens) / self.tokens_per_second
                raise RateLimitExceededError(self.name, wait_time)

            return False

    @property
    def stats(self) -> RateLimitStats:
        """Retourne les statistiques."""
        with self._lock:
            self._stats.current_rate = self._tokens / self.max_tokens
            return self._stats

    def reset(self) -> None:
        """Réinitialise le bucket."""
        with self._lock:
            self._tokens = float(self.max_tokens)
            self._last_update = time.time()


# Registry global des rate limiters
_rate_limiters: Dict[str, SlidingWindowRateLimiter] = {}
_registry_lock = threading.Lock()


def get_rate_limiter(
    name: str,
    max_requests: Optional[int] = None,
    window_seconds: Optional[float] = None,
    **kwargs
) -> SlidingWindowRateLimiter:
    """
    Obtient ou crée un rate limiter par nom.

    Args:
        name: Nom du service.
        max_requests: Limite de requêtes.
        window_seconds: Durée de la fenêtre.
        **kwargs: Paramètres supplémentaires.

    Returns:
        L'instance du rate limiter.
    """
    with _registry_lock:
        if name not in _rate_limiters:
            # Utiliser les valeurs par défaut selon le nom
            if max_requests is None or window_seconds is None:
                config = DEFAULT_RATE_LIMIT_CONFIG
                if "claude" in name.lower():
                    max_requests = max_requests or config.claude_requests_per_minute
                    window_seconds = window_seconds or 60.0
                elif "gmail" in name.lower():
                    max_requests = max_requests or config.gmail_requests_per_second
                    window_seconds = window_seconds or 1.0
                elif "outlook" in name.lower():
                    max_requests = max_requests or config.outlook_requests_per_minute
                    window_seconds = window_seconds or 60.0
                else:
                    max_requests = max_requests or 100
                    window_seconds = window_seconds or 60.0

            _rate_limiters[name] = SlidingWindowRateLimiter(
                name=name,
                max_requests=max_requests,
                window_seconds=window_seconds,
                **kwargs
            )
        return _rate_limiters[name]


def rate_limit(
    name: str,
    max_requests: Optional[int] = None,
    window_seconds: Optional[float] = None,
    tokens: int = 1,
):
    """
    Décorateur pour appliquer un rate limit à une fonction.

    Args:
        name: Nom du rate limiter.
        max_requests: Limite de requêtes.
        window_seconds: Durée de la fenêtre.
        tokens: Nombre de tokens par appel.

    Example:
        @rate_limit("gmail_api", max_requests=10, window_seconds=1)
        def fetch_emails():
            return gmail.users().messages().list().execute()
    """
    def decorator(func: Callable) -> Callable:
        limiter = get_rate_limiter(name, max_requests, window_seconds)

        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter.acquire(tokens)
            return func(*args, **kwargs)

        wrapper.rate_limiter = limiter
        return wrapper

    return decorator


def get_all_rate_limiters() -> Dict[str, SlidingWindowRateLimiter]:
    """Retourne tous les rate limiters enregistrés."""
    with _registry_lock:
        return dict(_rate_limiters)


def reset_all_rate_limiters() -> None:
    """Réinitialise tous les rate limiters."""
    with _registry_lock:
        for limiter in _rate_limiters.values():
            limiter.reset()
