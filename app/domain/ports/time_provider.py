# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port TimeProvider - Abstraction du temps système.

Ce port définit l'interface pour obtenir l'heure courante.
Il permet de découpler le domaine du temps système réel,
facilitant les tests déterministes.

Principe Clean Architecture:
- Les entités du domaine ne doivent pas dépendre de datetime.now()
- L'injection de dépendance permet de substituer l'implémentation
- Le domaine ne connaît que l'interface, pas les implémentations concrètes

Usage (dans un use case):
    @dataclass
    class MyUseCase:
        clock: TimeProvider

        def execute(self) -> Entity:
            entity = Entity(created_at=self.clock.now())
            return entity
"""

from abc import ABC, abstractmethod
from datetime import datetime


class TimeProvider(ABC):
    """
    Interface abstraite pour obtenir l'heure courante.

    Cette abstraction permet:
    - Tests déterministes (temps contrôlé via implémentation test)
    - Respect de la Dependency Inversion Principle
    - Isolation du domaine des dépendances système
    """

    @abstractmethod
    def now(self) -> datetime:
        """
        Retourne l'heure courante.

        Returns:
            datetime: L'heure courante selon l'implémentation.
        """
        pass
