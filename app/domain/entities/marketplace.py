# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités du domaine pour la Marketplace d'agents IA.

Ces entités représentent les concepts métier de la marketplace :
- MarketplaceAgent : Un agent publié sur la marketplace
- AgentPack : Un pack d'agents groupés
- AgentInstallation : Une installation d'agent par une organisation
- AgentReview : Un avis sur un agent
- Publisher : Un éditeur/vendeur d'agents
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
import uuid


class AgentCategory(Enum):
    """Catégories d'agents disponibles sur la marketplace."""
    CUSTOMER_SERVICE = "customer_service"
    SALES = "sales"
    MARKETING = "marketing"
    HR = "hr"
    LEGAL = "legal"
    FINANCIAL = "financial"
    TECHNICAL = "technical"
    MEDICAL = "medical"
    CUSTOM = "custom"


class AgentPricingModel(Enum):
    """Modèles de tarification des agents."""
    FREE = "free"
    ONE_TIME = "one_time"
    SUBSCRIPTION = "subscription"
    USAGE_BASED = "usage_based"


class AgentStatus(Enum):
    """Statut d'un agent sur la marketplace."""
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class InstallationStatus(Enum):
    """Statut d'une installation d'agent."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    UNINSTALLED = "uninstalled"


@dataclass
class AgentPricing:
    """Configuration de tarification d'un agent."""
    model: AgentPricingModel = AgentPricingModel.FREE
    price_cents: int = 0  # Prix en centimes
    currency: str = "EUR"
    billing_period_days: int = 30  # Pour les abonnements
    usage_price_per_call_cents: int = 0  # Pour usage-based
    trial_days: int = 0


@dataclass
class AgentCapabilitySpec:
    """Spécification d'une capacité d'agent."""
    name: str
    description: str
    keywords: List[str] = field(default_factory=list)
    priority: int = 0


@dataclass
class Publisher:
    """Éditeur/vendeur d'agents sur la marketplace."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    website: str = ""
    email: str = ""
    verified: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    agent_count: int = 0
    total_downloads: int = 0
    average_rating: float = 0.0


@dataclass
class MarketplaceAgent:
    """
    Agent publié sur la marketplace.

    Représente un agent IA que les entreprises peuvent installer
    et utiliser dans leur instance Agentys.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Métadonnées
    name: str = ""
    slug: str = ""  # URL-friendly identifier
    description: str = ""
    long_description: str = ""
    version: str = "1.0.0"

    # Classification
    category: AgentCategory = AgentCategory.CUSTOM
    tags: List[str] = field(default_factory=list)

    # Configuration de l'agent
    system_prompt: str = ""
    capabilities: List[AgentCapabilitySpec] = field(default_factory=list)
    knowledge_base_template: str = ""
    tone: str = "professional"
    language: str = "auto"

    # Publication
    publisher_id: str = ""
    status: AgentStatus = AgentStatus.DRAFT

    # Tarification
    pricing: AgentPricing = field(default_factory=AgentPricing)

    # Statistiques
    download_count: int = 0
    active_installations: int = 0
    average_rating: float = 0.0
    review_count: int = 0

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    published_at: Optional[datetime] = None

    # Métadonnées additionnelles
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_free(self) -> bool:
        """Vérifie si l'agent est gratuit."""
        return self.pricing.model == AgentPricingModel.FREE

    def is_published(self) -> bool:
        """Vérifie si l'agent est publié."""
        return self.status == AgentStatus.PUBLISHED

    def generate_slug(self) -> str:
        """Génère un slug à partir du nom."""
        import re
        slug = self.name.lower()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        return slug


@dataclass
class AgentPack:
    """
    Pack d'agents groupés pour un cas d'usage spécifique.

    Exemple : "Pack E-commerce" contenant Refund Handler,
    Sales Qualifier et Feedback Analyst.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    slug: str = ""
    description: str = ""

    # Agents inclus
    agent_ids: List[str] = field(default_factory=list)

    # Publication
    publisher_id: str = ""
    status: AgentStatus = AgentStatus.DRAFT

    # Tarification (peut offrir une réduction vs agents séparés)
    pricing: AgentPricing = field(default_factory=AgentPricing)
    discount_percent: int = 0  # Réduction par rapport aux agents séparés

    # Statistiques
    download_count: int = 0
    average_rating: float = 0.0

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class AgentInstallation:
    """
    Installation d'un agent par une organisation.

    Trace l'installation, la configuration et l'usage d'un agent
    de la marketplace par une entreprise.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Références
    agent_id: str = ""
    organization_id: str = ""

    # Statut
    status: InstallationStatus = InstallationStatus.ACTIVE

    # Version installée
    installed_version: str = "1.0.0"

    # Configuration personnalisée
    custom_knowledge_base: str = ""
    custom_settings: Dict[str, Any] = field(default_factory=dict)

    # Statistiques d'usage
    usage_count: int = 0
    last_used_at: Optional[datetime] = None

    # Timestamps
    installed_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None

    def is_active(self) -> bool:
        """Vérifie si l'installation est active."""
        if self.status != InstallationStatus.ACTIVE:
            return False
        if self.expires_at and datetime.now() > self.expires_at:
            return False
        return True


@dataclass
class AgentReview:
    """
    Avis sur un agent de la marketplace.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Références
    agent_id: str = ""
    organization_id: str = ""
    reviewer_name: str = ""

    # Contenu
    rating: int = 5  # 1-5 étoiles
    title: str = ""
    content: str = ""

    # Réponse de l'éditeur
    publisher_response: str = ""
    publisher_response_at: Optional[datetime] = None

    # Modération
    is_verified_purchase: bool = False
    is_approved: bool = False

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class MarketplaceSearchQuery:
    """Requête de recherche sur la marketplace."""
    query: str = ""
    category: Optional[AgentCategory] = None
    tags: List[str] = field(default_factory=list)
    pricing_models: List[AgentPricingModel] = field(default_factory=list)
    min_rating: float = 0.0
    verified_only: bool = False
    sort_by: str = "popularity"  # popularity, rating, newest, price
    page: int = 1
    per_page: int = 20


@dataclass
class MarketplaceSearchResult:
    """Résultat de recherche sur la marketplace."""
    agents: List[MarketplaceAgent] = field(default_factory=list)
    total_count: int = 0
    page: int = 1
    per_page: int = 20
    total_pages: int = 0
