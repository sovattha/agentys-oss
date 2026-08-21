# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Module de retry avec backoff exponentiel.

Fournit des décorateurs et utilitaires pour gérer les erreurs
transitoires des APIs externes (LLM, Email providers).
"""

import functools
import logging
import time
from typing import Callable, Optional, Tuple, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryExhaustedError(Exception):
    """Exception levée quand toutes les tentatives ont échoué."""

    def __init__(self, message: str, last_exception: Optional[Exception] = None):
        super().__init__(message)
        self.last_exception = last_exception


def with_retry(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
) -> Callable:
    """
    Décorateur pour ajouter retry avec backoff exponentiel.

    Args:
        max_attempts: Nombre maximum de tentatives (défaut: 3).
        backoff_factor: Facteur multiplicatif entre tentatives (défaut: 2.0).
        initial_delay: Délai initial en secondes (défaut: 1.0).
        max_delay: Délai maximum entre tentatives (défaut: 60.0).
        retryable_exceptions: Tuple d'exceptions à retry (défaut: toutes).
        on_retry: Callback optionnel appelé avant chaque retry.

    Returns:
        Décorateur de fonction.

    Example:
        @with_retry(max_attempts=3, retryable_exceptions=(TimeoutError, ConnectionError))
        def call_api():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            delay = initial_delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(
                            f"[Retry] {func.__name__} échec après {max_attempts} tentatives: {e}"
                        )
                        raise RetryExhaustedError(
                            f"Échec après {max_attempts} tentatives: {e}",
                            last_exception=e,
                        ) from e

                    logger.warning(
                        f"[Retry] {func.__name__} tentative {attempt}/{max_attempts} "
                        f"échouée: {e}. Retry dans {delay:.1f}s..."
                    )

                    if on_retry:
                        on_retry(e, attempt)

                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            # Ne devrait jamais arriver
            raise RetryExhaustedError(
                "Retry épuisé sans exception", last_exception=last_exception
            )

        return wrapper

    return decorator


def retry_call(
    func: Callable[..., T],
    args: tuple = (),
    kwargs: Optional[dict] = None,
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
) -> T:
    """
    Appelle une fonction avec retry (version impérative).

    Args:
        func: Fonction à appeler.
        args: Arguments positionnels.
        kwargs: Arguments nommés.
        max_attempts: Nombre maximum de tentatives.
        backoff_factor: Facteur multiplicatif entre tentatives.
        initial_delay: Délai initial en secondes.
        max_delay: Délai maximum entre tentatives.
        retryable_exceptions: Tuple d'exceptions à retry.

    Returns:
        Résultat de la fonction.

    Raises:
        RetryExhaustedError: Si toutes les tentatives échouent.
    """
    if kwargs is None:
        kwargs = {}

    @with_retry(
        max_attempts=max_attempts,
        backoff_factor=backoff_factor,
        initial_delay=initial_delay,
        max_delay=max_delay,
        retryable_exceptions=retryable_exceptions,
    )
    def _wrapped():
        return func(*args, **kwargs)

    return _wrapped()


# Exceptions communes à retry pour les APIs externes (LLM, Email, etc.)
API_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
)

# Alias pour rétrocompatibilité - utiliser API_RETRYABLE_EXCEPTIONS directement
LLM_RETRYABLE_EXCEPTIONS = API_RETRYABLE_EXCEPTIONS


def is_rate_limit_error(exception: Exception) -> bool:
    """
    Vérifie si une exception est une erreur de rate limit.

    Args:
        exception: Exception à vérifier.

    Returns:
        True si c'est une erreur de rate limit.
    """
    error_msg = str(exception).lower()
    rate_limit_indicators = [
        "rate limit",
        "rate_limit",
        "too many requests",
        "429",
        "quota exceeded",
        "overloaded",
    ]
    return any(indicator in error_msg for indicator in rate_limit_indicators)


def get_retry_delay_from_error(exception: Exception, default: float = 30.0) -> float:
    """
    Extrait le délai de retry suggéré depuis une erreur de rate limit.

    Args:
        exception: Exception à analyser.
        default: Délai par défaut si non spécifié.

    Returns:
        Délai en secondes.
    """
    error_msg = str(exception)

    # Chercher "retry after X seconds" ou similaire
    import re

    # Pattern: "retry after 30 seconds", "retry in 30s", etc.
    match = re.search(r"retry\s+(?:after\s+)?(\d+)\s*(?:seconds?|s\b)", error_msg, re.IGNORECASE)
    if match:
        return float(match.group(1))

    return default
