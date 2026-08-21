# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Cases pour la Marketplace d'agents IA.

Ces use cases gèrent la publication, l'installation, la recherche
et l'évaluation des agents sur la marketplace.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import re

from app.domain.entities.marketplace import (
    MarketplaceAgent,
    AgentPack,
    AgentInstallation,
    AgentReview,
    Publisher,
    AgentCategory,
    AgentPricingModel,
    AgentStatus,
    InstallationStatus,
    AgentPricing,
    AgentCapabilitySpec,
    MarketplaceSearchQuery,
    MarketplaceSearchResult,
)
from app.domain.ports.marketplace_port import (
    MarketplaceAgentPort,
    AgentPackPort,
    AgentInstallationPort,
    AgentReviewPort,
    PublisherPort,
)


# =============================================================================
# PUBLISHER USE CASES
# =============================================================================

@dataclass
class RegisterPublisherUseCase:
    """Enregistre un nouvel éditeur sur la marketplace."""
    publisher_port: PublisherPort

    def execute(
        self,
        name: str,
        email: str,
        description: str = "",
        website: str = ""
    ) -> Publisher:
        """
        Enregistre un nouvel éditeur.

        Args:
            name: Nom de l'éditeur.
            email: Email de contact.
            description: Description de l'éditeur.
            website: Site web de l'éditeur.

        Returns:
            L'éditeur créé.

        Raises:
            ValueError: Si email déjà utilisé ou données invalides.
        """
        self._validate(name, email)

        # Vérifier unicité email
        existing = self.publisher_port.get_by_email(email)
        if existing:
            raise ValueError(f"Un éditeur avec l'email {email} existe déjà")

        publisher = Publisher(
            name=name,
            email=email,
            description=description,
            website=website,
        )

        return self.publisher_port.save(publisher)

    def _validate(self, name: str, email: str) -> None:
        """Valide les données de l'éditeur."""
        if not name or not name.strip():
            raise ValueError("Le nom est requis")
        if not email or not email.strip():
            raise ValueError("L'email est requis")
        if "@" not in email:
            raise ValueError("Format d'email invalide")


@dataclass
class GetPublisherUseCase:
    """Récupère un éditeur."""
    publisher_port: PublisherPort

    def execute(self, publisher_id: str) -> Optional[Publisher]:
        """
        Récupère un éditeur par son ID.

        Args:
            publisher_id: ID de l'éditeur.

        Returns:
            L'éditeur ou None.
        """
        return self.publisher_port.get_by_id(publisher_id)


# =============================================================================
# AGENT PUBLICATION USE CASES
# =============================================================================

@dataclass
class PublishAgentUseCase:
    """Publie un nouvel agent sur la marketplace."""
    agent_port: MarketplaceAgentPort
    publisher_port: PublisherPort

    def execute(
        self,
        publisher_id: str,
        name: str,
        description: str,
        category: AgentCategory,
        system_prompt: str,
        capabilities: List[Dict[str, Any]],
        pricing: Optional[AgentPricing] = None,
        tags: Optional[List[str]] = None,
        long_description: str = "",
        knowledge_base_template: str = "",
    ) -> MarketplaceAgent:
        """
        Publie un nouvel agent sur la marketplace.

        Args:
            publisher_id: ID de l'éditeur.
            name: Nom de l'agent.
            description: Description courte.
            category: Catégorie de l'agent.
            system_prompt: Prompt système de l'agent.
            capabilities: Liste des capacités.
            pricing: Configuration de tarification.
            tags: Tags de l'agent.
            long_description: Description longue.
            knowledge_base_template: Template de knowledge base.

        Returns:
            L'agent créé (en statut DRAFT).

        Raises:
            ValueError: Si l'éditeur n'existe pas ou données invalides.
        """
        # Vérifier l'éditeur
        publisher = self.publisher_port.get_by_id(publisher_id)
        if not publisher:
            raise ValueError(f"Éditeur {publisher_id} non trouvé")

        self._validate(name, description, system_prompt)

        # Convertir les capabilities
        caps = [
            AgentCapabilitySpec(
                name=c.get("name", ""),
                description=c.get("description", ""),
                keywords=c.get("keywords", []),
                priority=c.get("priority", 0)
            )
            for c in capabilities
        ]

        agent = MarketplaceAgent(
            name=name,
            slug=self._generate_slug(name),
            description=description,
            long_description=long_description,
            category=category,
            tags=tags or [],
            system_prompt=system_prompt,
            capabilities=caps,
            knowledge_base_template=knowledge_base_template,
            publisher_id=publisher_id,
            pricing=pricing or AgentPricing(),
            status=AgentStatus.DRAFT,
        )

        saved_agent = self.agent_port.save(agent)

        # Mettre à jour le compteur de l'éditeur
        publisher.agent_count += 1
        self.publisher_port.update(publisher)

        return saved_agent

    def _validate(self, name: str, description: str, system_prompt: str) -> None:
        """Valide les données de l'agent."""
        if not name or not name.strip():
            raise ValueError("Le nom est requis")
        if len(name) < 3:
            raise ValueError("Le nom doit faire au moins 3 caractères")
        if not description or not description.strip():
            raise ValueError("La description est requise")
        if len(description) < 10:
            raise ValueError("La description doit faire au moins 10 caractères")
        if not system_prompt or not system_prompt.strip():
            raise ValueError("Le prompt système est requis")

    def _generate_slug(self, name: str) -> str:
        """Génère un slug unique."""
        slug = name.lower()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        return slug


@dataclass
class SubmitAgentForReviewUseCase:
    """Soumet un agent pour révision avant publication."""
    agent_port: MarketplaceAgentPort

    def execute(self, agent_id: str, publisher_id: str) -> MarketplaceAgent:
        """
        Soumet un agent pour révision.

        Args:
            agent_id: ID de l'agent.
            publisher_id: ID de l'éditeur (pour vérification).

        Returns:
            L'agent mis à jour.

        Raises:
            ValueError: Si l'agent n'existe pas ou n'appartient pas à l'éditeur.
            ValueError: Si l'agent n'est pas en statut DRAFT.
        """
        agent = self.agent_port.get_by_id(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} non trouvé")

        if agent.publisher_id != publisher_id:
            raise ValueError("Cet agent ne vous appartient pas")

        if agent.status != AgentStatus.DRAFT:
            raise ValueError(f"L'agent doit être en statut DRAFT, statut actuel: {agent.status.value}")

        agent.status = AgentStatus.PENDING_REVIEW
        agent.updated_at = datetime.now()

        return self.agent_port.update(agent)


@dataclass
class ApproveAgentUseCase:
    """Approuve un agent soumis pour publication."""
    agent_port: MarketplaceAgentPort

    def execute(self, agent_id: str) -> MarketplaceAgent:
        """
        Approuve et publie un agent.

        Args:
            agent_id: ID de l'agent.

        Returns:
            L'agent publié.

        Raises:
            ValueError: Si l'agent n'existe pas ou n'est pas en PENDING_REVIEW.
        """
        agent = self.agent_port.get_by_id(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} non trouvé")

        if agent.status != AgentStatus.PENDING_REVIEW:
            raise ValueError(f"L'agent doit être en PENDING_REVIEW, statut actuel: {agent.status.value}")

        agent.status = AgentStatus.PUBLISHED
        agent.published_at = datetime.now()
        agent.updated_at = datetime.now()

        return self.agent_port.update(agent)


@dataclass
class UpdateAgentUseCase:
    """Met à jour un agent existant."""
    agent_port: MarketplaceAgentPort

    def execute(
        self,
        agent_id: str,
        publisher_id: str,
        **updates
    ) -> MarketplaceAgent:
        """
        Met à jour un agent.

        Args:
            agent_id: ID de l'agent.
            publisher_id: ID de l'éditeur (pour vérification).
            **updates: Champs à mettre à jour.

        Returns:
            L'agent mis à jour.

        Raises:
            ValueError: Si l'agent n'existe pas ou n'appartient pas à l'éditeur.
        """
        agent = self.agent_port.get_by_id(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} non trouvé")

        if agent.publisher_id != publisher_id:
            raise ValueError("Cet agent ne vous appartient pas")

        # Champs modifiables
        allowed_fields = {
            "name", "description", "long_description", "tags",
            "system_prompt", "knowledge_base_template", "tone", "language"
        }

        for field, value in updates.items():
            if field in allowed_fields and hasattr(agent, field):
                setattr(agent, field, value)

        # Regénérer le slug si le nom change
        if "name" in updates:
            agent.slug = re.sub(r'[^a-z0-9]+', '-', updates["name"].lower()).strip('-')

        # Incrémenter la version si publié
        if agent.status == AgentStatus.PUBLISHED:
            parts = agent.version.split('.')
            parts[-1] = str(int(parts[-1]) + 1)
            agent.version = '.'.join(parts)

        agent.updated_at = datetime.now()

        return self.agent_port.update(agent)


# =============================================================================
# SEARCH USE CASES
# =============================================================================

@dataclass
class SearchAgentsUseCase:
    """Recherche des agents sur la marketplace."""
    agent_port: MarketplaceAgentPort

    def execute(self, query: MarketplaceSearchQuery) -> MarketplaceSearchResult:
        """
        Recherche des agents.

        Args:
            query: Critères de recherche.

        Returns:
            Résultats de la recherche.
        """
        return self.agent_port.search(query)


@dataclass
class GetAgentDetailsUseCase:
    """Récupère les détails d'un agent."""
    agent_port: MarketplaceAgentPort
    review_port: AgentReviewPort
    installation_port: AgentInstallationPort

    def execute(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les détails complets d'un agent.

        Args:
            agent_id: ID de l'agent.

        Returns:
            Détails de l'agent avec avis et stats, ou None.
        """
        agent = self.agent_port.get_by_id(agent_id)
        if not agent:
            return None

        reviews = self.review_port.get_by_agent(agent_id, approved_only=True, limit=10)
        active_installations = self.installation_port.count_active_by_agent(agent_id)

        return {
            "agent": agent,
            "reviews": reviews,
            "active_installations": active_installations,
            "average_rating": self.review_port.calculate_average_rating(agent_id),
            "review_count": self.review_port.count_reviews(agent_id),
        }


@dataclass
class ListFeaturedAgentsUseCase:
    """Liste les agents mis en avant."""
    agent_port: MarketplaceAgentPort

    def execute(self, limit: int = 10) -> List[MarketplaceAgent]:
        """
        Liste les agents populaires/mis en avant.

        Args:
            limit: Nombre maximum d'agents.

        Returns:
            Liste des agents mis en avant.
        """
        return self.agent_port.list_all(
            status=AgentStatus.PUBLISHED,
            limit=limit
        )


@dataclass
class ListAgentsByCategoryUseCase:
    """Liste les agents par catégorie."""
    agent_port: MarketplaceAgentPort

    def execute(
        self,
        category: AgentCategory,
        limit: int = 20,
        offset: int = 0
    ) -> List[MarketplaceAgent]:
        """
        Liste les agents d'une catégorie.

        Args:
            category: Catégorie à filtrer.
            limit: Nombre maximum d'agents.
            offset: Offset pour pagination.

        Returns:
            Liste des agents.
        """
        return self.agent_port.list_all(
            status=AgentStatus.PUBLISHED,
            category=category,
            limit=limit,
            offset=offset
        )


# =============================================================================
# INSTALLATION USE CASES
# =============================================================================

@dataclass
class InstallAgentUseCase:
    """Installe un agent pour une organisation."""
    agent_port: MarketplaceAgentPort
    installation_port: AgentInstallationPort

    def execute(
        self,
        agent_id: str,
        organization_id: str,
        custom_settings: Optional[Dict[str, Any]] = None
    ) -> AgentInstallation:
        """
        Installe un agent pour une organisation.

        Args:
            agent_id: ID de l'agent à installer.
            organization_id: ID de l'organisation.
            custom_settings: Paramètres personnalisés.

        Returns:
            L'installation créée.

        Raises:
            ValueError: Si l'agent n'existe pas ou n'est pas publié.
            ValueError: Si déjà installé.
        """
        agent = self.agent_port.get_by_id(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} non trouvé")

        if agent.status != AgentStatus.PUBLISHED:
            raise ValueError("Cet agent n'est pas disponible à l'installation")

        # Vérifier si déjà installé
        existing = self.installation_port.find_installation(agent_id, organization_id)
        if existing and existing.is_active():
            raise ValueError("Cet agent est déjà installé")

        # Calculer la date d'expiration si applicable
        expires_at = None
        if agent.pricing.model == AgentPricingModel.SUBSCRIPTION:
            expires_at = datetime.now() + timedelta(days=agent.pricing.billing_period_days)
        elif agent.pricing.trial_days > 0:
            expires_at = datetime.now() + timedelta(days=agent.pricing.trial_days)

        installation = AgentInstallation(
            agent_id=agent_id,
            organization_id=organization_id,
            installed_version=agent.version,
            custom_settings=custom_settings or {},
            expires_at=expires_at,
        )

        saved_installation = self.installation_port.save(installation)

        # Mettre à jour les statistiques de l'agent
        self.agent_port.increment_download_count(agent_id)
        agent.active_installations += 1
        self.agent_port.update(agent)

        return saved_installation


@dataclass
class UninstallAgentUseCase:
    """Désinstalle un agent."""
    agent_port: MarketplaceAgentPort
    installation_port: AgentInstallationPort

    def execute(self, installation_id: str, organization_id: str) -> bool:
        """
        Désinstalle un agent.

        Args:
            installation_id: ID de l'installation.
            organization_id: ID de l'organisation (pour vérification).

        Returns:
            True si désinstallé.

        Raises:
            ValueError: Si l'installation n'existe pas ou n'appartient pas à l'organisation.
        """
        installation = self.installation_port.get_by_id(installation_id)
        if not installation:
            raise ValueError(f"Installation {installation_id} non trouvée")

        if installation.organization_id != organization_id:
            raise ValueError("Cette installation ne vous appartient pas")

        installation.status = InstallationStatus.UNINSTALLED
        self.installation_port.update(installation)

        # Mettre à jour les stats de l'agent
        agent = self.agent_port.get_by_id(installation.agent_id)
        if agent and agent.active_installations > 0:
            agent.active_installations -= 1
            self.agent_port.update(agent)

        return True


@dataclass
class ListInstalledAgentsUseCase:
    """Liste les agents installés par une organisation."""
    installation_port: AgentInstallationPort
    agent_port: MarketplaceAgentPort

    def execute(self, organization_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Liste les agents installés.

        Args:
            organization_id: ID de l'organisation.
            active_only: Ne retourner que les installations actives.

        Returns:
            Liste des installations avec détails des agents.
        """
        installations = self.installation_port.get_by_organization(
            organization_id,
            active_only=active_only
        )

        result = []
        for installation in installations:
            agent = self.agent_port.get_by_id(installation.agent_id)
            result.append({
                "installation": installation,
                "agent": agent,
            })

        return result


@dataclass
class RecordAgentUsageUseCase:
    """Enregistre l'utilisation d'un agent installé."""
    installation_port: AgentInstallationPort

    def execute(self, installation_id: str) -> AgentInstallation:
        """
        Enregistre une utilisation.

        Args:
            installation_id: ID de l'installation.

        Returns:
            Installation mise à jour.

        Raises:
            ValueError: Si l'installation n'existe pas ou n'est pas active.
        """
        installation = self.installation_port.get_by_id(installation_id)
        if not installation:
            raise ValueError(f"Installation {installation_id} non trouvée")

        if not installation.is_active():
            raise ValueError("Cette installation n'est pas active")

        installation.usage_count += 1
        installation.last_used_at = datetime.now()

        return self.installation_port.update(installation)


# =============================================================================
# REVIEW USE CASES
# =============================================================================

@dataclass
class SubmitReviewUseCase:
    """Soumet un avis sur un agent."""
    review_port: AgentReviewPort
    installation_port: AgentInstallationPort
    agent_port: MarketplaceAgentPort

    def execute(
        self,
        agent_id: str,
        organization_id: str,
        reviewer_name: str,
        rating: int,
        title: str,
        content: str
    ) -> AgentReview:
        """
        Soumet un avis sur un agent.

        Args:
            agent_id: ID de l'agent.
            organization_id: ID de l'organisation.
            reviewer_name: Nom de l'évaluateur.
            rating: Note (1-5).
            title: Titre de l'avis.
            content: Contenu de l'avis.

        Returns:
            L'avis créé.

        Raises:
            ValueError: Si l'organisation n'a pas installé l'agent.
            ValueError: Si rating invalide.
        """
        if rating < 1 or rating > 5:
            raise ValueError("La note doit être entre 1 et 5")

        if not title or len(title) < 3:
            raise ValueError("Le titre doit faire au moins 3 caractères")

        if not content or len(content) < 10:
            raise ValueError("Le contenu doit faire au moins 10 caractères")

        # Vérifier que l'organisation a installé l'agent
        installation = self.installation_port.find_installation(agent_id, organization_id)
        is_verified = installation is not None

        review = AgentReview(
            agent_id=agent_id,
            organization_id=organization_id,
            reviewer_name=reviewer_name,
            rating=rating,
            title=title,
            content=content,
            is_verified_purchase=is_verified,
            is_approved=True,  # Auto-approve pour simplifier
        )

        saved_review = self.review_port.save(review)

        # Mettre à jour les statistiques de l'agent
        agent = self.agent_port.get_by_id(agent_id)
        if agent:
            agent.review_count = self.review_port.count_reviews(agent_id)
            agent.average_rating = self.review_port.calculate_average_rating(agent_id)
            self.agent_port.update(agent)

        return saved_review


@dataclass
class RespondToReviewUseCase:
    """Permet à l'éditeur de répondre à un avis."""
    review_port: AgentReviewPort
    agent_port: MarketplaceAgentPort

    def execute(
        self,
        review_id: str,
        publisher_id: str,
        response: str
    ) -> AgentReview:
        """
        Répond à un avis.

        Args:
            review_id: ID de l'avis.
            publisher_id: ID de l'éditeur (pour vérification).
            response: Réponse de l'éditeur.

        Returns:
            L'avis mis à jour.

        Raises:
            ValueError: Si l'avis n'existe pas ou l'éditeur n'est pas autorisé.
        """
        review = self.review_port.get_by_id(review_id)
        if not review:
            raise ValueError(f"Avis {review_id} non trouvé")

        # Vérifier que l'éditeur possède l'agent
        agent = self.agent_port.get_by_id(review.agent_id)
        if not agent or agent.publisher_id != publisher_id:
            raise ValueError("Vous n'êtes pas autorisé à répondre à cet avis")

        if not response or len(response) < 10:
            raise ValueError("La réponse doit faire au moins 10 caractères")

        review.publisher_response = response
        review.publisher_response_at = datetime.now()

        return self.review_port.update(review)


@dataclass
class ListAgentReviewsUseCase:
    """Liste les avis d'un agent."""
    review_port: AgentReviewPort

    def execute(
        self,
        agent_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[AgentReview]:
        """
        Liste les avis d'un agent.

        Args:
            agent_id: ID de l'agent.
            limit: Nombre maximum d'avis.
            offset: Offset pour pagination.

        Returns:
            Liste des avis.
        """
        return self.review_port.get_by_agent(
            agent_id,
            approved_only=True,
            limit=limit,
            offset=offset
        )


# =============================================================================
# PACK USE CASES
# =============================================================================

@dataclass
class CreateAgentPackUseCase:
    """Crée un pack d'agents."""
    pack_port: AgentPackPort
    agent_port: MarketplaceAgentPort
    publisher_port: PublisherPort

    def execute(
        self,
        publisher_id: str,
        name: str,
        description: str,
        agent_ids: List[str],
        pricing: Optional[AgentPricing] = None,
        discount_percent: int = 0
    ) -> AgentPack:
        """
        Crée un pack d'agents.

        Args:
            publisher_id: ID de l'éditeur.
            name: Nom du pack.
            description: Description du pack.
            agent_ids: IDs des agents à inclure.
            pricing: Configuration de tarification.
            discount_percent: Réduction en %.

        Returns:
            Le pack créé.

        Raises:
            ValueError: Si l'éditeur n'existe pas ou agents invalides.
        """
        publisher = self.publisher_port.get_by_id(publisher_id)
        if not publisher:
            raise ValueError(f"Éditeur {publisher_id} non trouvé")

        if len(agent_ids) < 2:
            raise ValueError("Un pack doit contenir au moins 2 agents")

        # Vérifier que tous les agents existent et sont publiés
        for agent_id in agent_ids:
            agent = self.agent_port.get_by_id(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} non trouvé")
            if agent.status != AgentStatus.PUBLISHED:
                raise ValueError(f"Agent {agent_id} n'est pas publié")

        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

        pack = AgentPack(
            name=name,
            slug=slug,
            description=description,
            agent_ids=agent_ids,
            publisher_id=publisher_id,
            pricing=pricing or AgentPricing(),
            discount_percent=discount_percent,
            status=AgentStatus.DRAFT,
        )

        return self.pack_port.save(pack)


@dataclass
class InstallPackUseCase:
    """Installe tous les agents d'un pack."""
    pack_port: AgentPackPort
    install_agent_use_case: InstallAgentUseCase

    def execute(
        self,
        pack_id: str,
        organization_id: str
    ) -> List[AgentInstallation]:
        """
        Installe tous les agents d'un pack.

        Args:
            pack_id: ID du pack.
            organization_id: ID de l'organisation.

        Returns:
            Liste des installations créées.

        Raises:
            ValueError: Si le pack n'existe pas.
        """
        pack = self.pack_port.get_by_id(pack_id)
        if not pack:
            raise ValueError(f"Pack {pack_id} non trouvé")

        installations = []
        for agent_id in pack.agent_ids:
            try:
                installation = self.install_agent_use_case.execute(
                    agent_id=agent_id,
                    organization_id=organization_id
                )
                installations.append(installation)
            except ValueError:
                # Agent déjà installé, on continue
                pass

        return installations
