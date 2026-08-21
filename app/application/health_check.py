# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Health Check des services.

Vérifie l'état de santé des composants du système (email provider, LLM)
sans exposer les détails d'implémentation à la couche API.
"""

from dataclasses import dataclass
from typing import Callable

from app.domain.ports import LLMPort, EmailPort


@dataclass
class HealthStatus:
    """Résultat d'un health check."""
    healthy: bool
    message: str = ""


@dataclass
class SystemHealthStatus:
    """État de santé global du système."""
    email_provider: HealthStatus
    llm: HealthStatus

    @property
    def overall_healthy(self) -> bool:
        """Retourne True si tous les composants sont sains."""
        return self.email_provider.healthy and self.llm.healthy

    @property
    def status(self) -> str:
        """Retourne le statut global."""
        return "healthy" if self.overall_healthy else "degraded"


class HealthCheckUseCase:
    """
    Use case pour vérifier la santé des services.

    Respecte la Clean Architecture en utilisant les ports
    plutôt que les implémentations concrètes.
    """

    def __init__(
        self,
        email_provider_factory: Callable[[], EmailPort],
        llm_factory: Callable[[], LLMPort],
    ):
        """
        Initialise le health check.

        Args:
            email_provider_factory: Factory pour créer un email provider.
            llm_factory: Factory pour créer un LLM port.
        """
        self._email_provider_factory = email_provider_factory
        self._llm_factory = llm_factory

    def check_email_provider(self) -> HealthStatus:
        """Vérifie la santé du provider email."""
        try:
            provider = self._email_provider_factory()
            is_healthy = provider.authenticate()
            return HealthStatus(
                healthy=is_healthy,
                message="" if is_healthy else "Authentication failed"
            )
        except Exception as e:
            return HealthStatus(healthy=False, message=str(e))

    def check_llm(self) -> HealthStatus:
        """Vérifie la santé du LLM via un test simple."""
        try:
            llm = self._llm_factory()
            response = llm.complete(
                system="You are a test assistant.",
                user="Reply with OK",
                max_tokens=10
            )
            is_healthy = bool(response and response.content)
            return HealthStatus(
                healthy=is_healthy,
                message="" if is_healthy else "Empty response"
            )
        except Exception as e:
            return HealthStatus(healthy=False, message=str(e))

    def execute(self) -> SystemHealthStatus:
        """
        Exécute tous les health checks.

        Returns:
            État de santé global du système.
        """
        return SystemHealthStatus(
            email_provider=self.check_email_provider(),
            llm=self.check_llm(),
        )
