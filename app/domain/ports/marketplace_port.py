# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port MarketplacePort - Interface pour la persistance de la marketplace.

Ce port définit les contrats que tout adapter de stockage de la marketplace
doit implémenter (fichier JSON, base de données SQLite, API externe, etc.).
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities.marketplace import (
    MarketplaceAgent,
    AgentPack,
    AgentInstallation,
    AgentReview,
    Publisher,
    MarketplaceSearchQuery,
    MarketplaceSearchResult,
    AgentCategory,
    AgentStatus,
)


class MarketplaceAgentPort(ABC):
    """
    Interface abstraite pour le stockage des agents de la marketplace.
    """

    @abstractmethod
    def save(self, agent: MarketplaceAgent) -> MarketplaceAgent:
        """
        Sauvegarde un agent sur la marketplace.

        Args:
            agent: Agent à sauvegarder.

        Returns:
            L'agent sauvegardé avec son ID.

        Raises:
            ValueError: Si les données sont invalides.
            IOError: Si la sauvegarde échoue.
        """
        pass

    @abstractmethod
    def get_by_id(self, agent_id: str) -> Optional[MarketplaceAgent]:
        """
        Récupère un agent par son ID.

        Args:
            agent_id: ID de l'agent.

        Returns:
            L'agent ou None si non trouvé.
        """
        pass

    @abstractmethod
    def get_by_slug(self, slug: str) -> Optional[MarketplaceAgent]:
        """
        Récupère un agent par son slug.

        Args:
            slug: Slug de l'agent.

        Returns:
            L'agent ou None si non trouvé.
        """
        pass

    @abstractmethod
    def list_all(
        self,
        status: Optional[AgentStatus] = None,
        category: Optional[AgentCategory] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[MarketplaceAgent]:
        """
        Liste tous les agents avec filtres optionnels.

        Args:
            status: Filtrer par statut.
            category: Filtrer par catégorie.
            limit: Nombre maximum d'agents à retourner.
            offset: Offset pour la pagination.

        Returns:
            Liste des agents.
        """
        pass

    @abstractmethod
    def search(self, query: MarketplaceSearchQuery) -> MarketplaceSearchResult:
        """
        Recherche des agents selon des critères.

        Args:
            query: Critères de recherche.

        Returns:
            Résultats de la recherche.
        """
        pass

    @abstractmethod
    def update(self, agent: MarketplaceAgent) -> MarketplaceAgent:
        """
        Met à jour un agent existant.

        Args:
            agent: Agent à mettre à jour.

        Returns:
            L'agent mis à jour.

        Raises:
            ValueError: Si l'agent n'existe pas.
        """
        pass

    @abstractmethod
    def delete(self, agent_id: str) -> bool:
        """
        Supprime un agent.

        Args:
            agent_id: ID de l'agent à supprimer.

        Returns:
            True si supprimé, False si non trouvé.
        """
        pass

    @abstractmethod
    def get_by_publisher(
        self,
        publisher_id: str,
        status: Optional[AgentStatus] = None
    ) -> List[MarketplaceAgent]:
        """
        Récupère les agents d'un éditeur.

        Args:
            publisher_id: ID de l'éditeur.
            status: Filtrer par statut.

        Returns:
            Liste des agents de l'éditeur.
        """
        pass

    @abstractmethod
    def increment_download_count(self, agent_id: str) -> None:
        """
        Incrémente le compteur de téléchargements.

        Args:
            agent_id: ID de l'agent.
        """
        pass


class AgentPackPort(ABC):
    """
    Interface abstraite pour le stockage des packs d'agents.
    """

    @abstractmethod
    def save(self, pack: AgentPack) -> AgentPack:
        """Sauvegarde un pack."""
        pass

    @abstractmethod
    def get_by_id(self, pack_id: str) -> Optional[AgentPack]:
        """Récupère un pack par son ID."""
        pass

    @abstractmethod
    def list_all(self, limit: int = 100, offset: int = 0) -> List[AgentPack]:
        """Liste tous les packs."""
        pass

    @abstractmethod
    def delete(self, pack_id: str) -> bool:
        """Supprime un pack."""
        pass


class AgentInstallationPort(ABC):
    """
    Interface abstraite pour le stockage des installations d'agents.
    """

    @abstractmethod
    def save(self, installation: AgentInstallation) -> AgentInstallation:
        """
        Enregistre une installation.

        Args:
            installation: Installation à enregistrer.

        Returns:
            L'installation enregistrée.
        """
        pass

    @abstractmethod
    def get_by_id(self, installation_id: str) -> Optional[AgentInstallation]:
        """Récupère une installation par son ID."""
        pass

    @abstractmethod
    def get_by_organization(
        self,
        organization_id: str,
        active_only: bool = True
    ) -> List[AgentInstallation]:
        """
        Récupère les installations d'une organisation.

        Args:
            organization_id: ID de l'organisation.
            active_only: Ne retourner que les installations actives.

        Returns:
            Liste des installations.
        """
        pass

    @abstractmethod
    def get_by_agent(self, agent_id: str) -> List[AgentInstallation]:
        """
        Récupère toutes les installations d'un agent.

        Args:
            agent_id: ID de l'agent.

        Returns:
            Liste des installations.
        """
        pass

    @abstractmethod
    def find_installation(
        self,
        agent_id: str,
        organization_id: str
    ) -> Optional[AgentInstallation]:
        """
        Trouve une installation spécifique.

        Args:
            agent_id: ID de l'agent.
            organization_id: ID de l'organisation.

        Returns:
            L'installation ou None.
        """
        pass

    @abstractmethod
    def update(self, installation: AgentInstallation) -> AgentInstallation:
        """Met à jour une installation."""
        pass

    @abstractmethod
    def delete(self, installation_id: str) -> bool:
        """Supprime une installation."""
        pass

    @abstractmethod
    def count_active_by_agent(self, agent_id: str) -> int:
        """
        Compte le nombre d'installations actives d'un agent.

        Args:
            agent_id: ID de l'agent.

        Returns:
            Nombre d'installations actives.
        """
        pass


class AgentReviewPort(ABC):
    """
    Interface abstraite pour le stockage des avis.
    """

    @abstractmethod
    def save(self, review: AgentReview) -> AgentReview:
        """Sauvegarde un avis."""
        pass

    @abstractmethod
    def get_by_id(self, review_id: str) -> Optional[AgentReview]:
        """Récupère un avis par son ID."""
        pass

    @abstractmethod
    def get_by_agent(
        self,
        agent_id: str,
        approved_only: bool = True,
        limit: int = 50,
        offset: int = 0
    ) -> List[AgentReview]:
        """
        Récupère les avis d'un agent.

        Args:
            agent_id: ID de l'agent.
            approved_only: Ne retourner que les avis approuvés.
            limit: Nombre maximum d'avis.
            offset: Offset pour pagination.

        Returns:
            Liste des avis.
        """
        pass

    @abstractmethod
    def update(self, review: AgentReview) -> AgentReview:
        """Met à jour un avis."""
        pass

    @abstractmethod
    def delete(self, review_id: str) -> bool:
        """Supprime un avis."""
        pass

    @abstractmethod
    def calculate_average_rating(self, agent_id: str) -> float:
        """
        Calcule la note moyenne d'un agent.

        Args:
            agent_id: ID de l'agent.

        Returns:
            Note moyenne (0.0 si aucun avis).
        """
        pass

    @abstractmethod
    def count_reviews(self, agent_id: str, approved_only: bool = True) -> int:
        """
        Compte le nombre d'avis d'un agent.

        Args:
            agent_id: ID de l'agent.
            approved_only: Ne compter que les avis approuvés.

        Returns:
            Nombre d'avis.
        """
        pass


class PublisherPort(ABC):
    """
    Interface abstraite pour le stockage des éditeurs.
    """

    @abstractmethod
    def save(self, publisher: Publisher) -> Publisher:
        """Sauvegarde un éditeur."""
        pass

    @abstractmethod
    def get_by_id(self, publisher_id: str) -> Optional[Publisher]:
        """Récupère un éditeur par son ID."""
        pass

    @abstractmethod
    def list_all(
        self,
        verified_only: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> List[Publisher]:
        """Liste tous les éditeurs."""
        pass

    @abstractmethod
    def update(self, publisher: Publisher) -> Publisher:
        """Met à jour un éditeur."""
        pass

    @abstractmethod
    def delete(self, publisher_id: str) -> bool:
        """Supprime un éditeur."""
        pass

    @abstractmethod
    def get_by_email(self, email: str) -> Optional[Publisher]:
        """Récupère un éditeur par son email."""
        pass
