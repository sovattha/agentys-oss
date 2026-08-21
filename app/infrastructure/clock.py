# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Implémentations du TimeProvider - Adapters pour le temps.

Ce module fournit deux implémentations du TimeProvider:
- SystemClock: Utilise datetime.now() (production)
- FakeClock: Temps contrôlé manuellement (tests)

Exemple d'utilisation:
    # Production
    from app.infrastructure.clock import SystemClock
    clock = SystemClock()
    print(clock.now())  # Heure système réelle

    # Tests
    from app.infrastructure.clock import FakeClock
    clock = FakeClock(datetime(2024, 1, 1, 12, 0, 0))
    print(clock.now())  # 2024-01-01 12:00:00
    clock.advance_by(hours=2)
    print(clock.now())  # 2024-01-01 14:00:00
"""

from datetime import datetime, timedelta
from typing import Optional

from app.domain.ports.time_provider import TimeProvider


class SystemClock(TimeProvider):
    """
    Implémentation production du TimeProvider.

    Utilise datetime.now() pour retourner l'heure système réelle.
    Compatible avec freezegun pour les tests d'intégration.
    """

    def now(self) -> datetime:
        """Retourne l'heure système courante."""
        return datetime.now()

    def __str__(self) -> str:
        return f"SystemClock({self.now().strftime('%Y-%m-%d %H:%M:%S')})"

    def __repr__(self) -> str:
        return f"SystemClock(current={self.now().isoformat()})"


class FakeClock(TimeProvider):
    """
    Implémentation test du TimeProvider.

    Permet de contrôler manuellement le temps pour des tests déterministes.
    Fonctionnalités:
    - Temps fixe ou ajustable
    - Avancement manuel (advance_by)
    - Reset à l'heure initiale
    - Calcul du temps écoulé
    """

    def __init__(self, initial_time: Optional[datetime] = None):
        """
        Initialise le FakeClock.

        Args:
            initial_time: Heure initiale. Si None, utilise datetime.now().
        """
        self._initial_time = initial_time or datetime.now()
        self._current_time = self._initial_time

    def now(self) -> datetime:
        """Retourne l'heure courante simulée."""
        return self._current_time

    def set_time(self, new_time: datetime) -> None:
        """
        Définit une nouvelle heure courante.

        Args:
            new_time: Nouvelle heure à utiliser.
        """
        self._current_time = new_time

    def advance_by(
        self,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        milliseconds: int = 0,
    ) -> None:
        """
        Avance l'heure courante.

        Args:
            days: Nombre de jours à ajouter.
            hours: Nombre d'heures à ajouter.
            minutes: Nombre de minutes à ajouter.
            seconds: Nombre de secondes à ajouter.
            milliseconds: Nombre de millisecondes à ajouter.
        """
        delta = timedelta(
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            milliseconds=milliseconds,
        )
        self._current_time += delta

    def advance_by_delta(self, delta: timedelta) -> None:
        """
        Avance l'heure courante d'un timedelta.

        Args:
            delta: Durée à ajouter.
        """
        self._current_time += delta

    def reset(self) -> None:
        """Remet l'heure à la valeur initiale."""
        self._current_time = self._initial_time

    def elapsed(self) -> timedelta:
        """
        Retourne le temps écoulé depuis l'heure initiale.

        Returns:
            timedelta: Durée écoulée.
        """
        return self._current_time - self._initial_time

    def __str__(self) -> str:
        return f"FakeClock({self._current_time.strftime('%Y-%m-%d %H:%M:%S')})"

    def __repr__(self) -> str:
        return f"FakeClock(current={self._current_time.isoformat()}, initial={self._initial_time.isoformat()})"


# Factory function pour faciliter l'utilisation
def get_clock(use_fake: bool = False, initial_time: Optional[datetime] = None) -> TimeProvider:
    """
    Factory pour obtenir un clock.

    Args:
        use_fake: Si True, retourne un FakeClock. Sinon, SystemClock.
        initial_time: Heure initiale pour FakeClock (ignoré pour SystemClock).

    Returns:
        TimeProvider: Instance de clock appropriée.
    """
    if use_fake:
        return FakeClock(initial_time)
    return SystemClock()
