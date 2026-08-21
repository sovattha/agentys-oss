# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Implémentation du stockage de la marketplace.

Ce module fournit les adapters de persistance pour la marketplace d'agents.
Utilise le stockage JSON pour la simplicité et la portabilité.
"""

import json
import logging
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.domain.entities.marketplace import (
    MarketplaceAgent,
    AgentPack,
    AgentInstallation,
    AgentReview,
    Publisher,
    AgentCategory,
    AgentStatus,
    InstallationStatus,
    AgentPricing,
    AgentPricingModel,
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

logger = logging.getLogger(__name__)


def _datetime_to_str(obj: Any) -> Any:
    """Convertit les datetime en strings pour JSON."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _datetime_to_str(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_datetime_to_str(item) for item in obj]
    elif hasattr(obj, 'value'):  # Enums
        return obj.value
    return obj


def _str_to_datetime(s: str) -> Optional[datetime]:
    """Convertit une string ISO en datetime."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


class JsonMarketplaceAgentStore(MarketplaceAgentPort):
    """
    Stockage des agents marketplace dans un fichier JSON.
    Thread-safe avec verrouillage.
    """

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self._agents: Dict[str, MarketplaceAgent] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Charge les agents depuis le fichier."""
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding='utf-8'))
                for agent_data in data.get("agents", []):
                    agent = self._dict_to_agent(agent_data)
                    self._agents[agent.id] = agent
                logger.info(f"Loaded {len(self._agents)} marketplace agents")
            except Exception as e:
                logger.error(f"Error loading marketplace agents: {e}")

    def _save(self) -> None:
        """Sauvegarde les agents."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "agents": [self._agent_to_dict(a) for a in self._agents.values()],
            "updated_at": datetime.now().isoformat()
        }
        self.filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding='utf-8'
        )

    def _agent_to_dict(self, agent: MarketplaceAgent) -> Dict[str, Any]:
        """Convertit un agent en dictionnaire."""
        d = asdict(agent)
        d = _datetime_to_str(d)
        d['category'] = agent.category.value
        d['status'] = agent.status.value
        d['pricing']['model'] = agent.pricing.model.value
        return d

    def _dict_to_agent(self, d: Dict[str, Any]) -> MarketplaceAgent:
        """Convertit un dictionnaire en agent."""
        # Convertir les enums
        d['category'] = AgentCategory(d.get('category', 'custom'))
        d['status'] = AgentStatus(d.get('status', 'draft'))

        # Convertir le pricing
        pricing_data = d.get('pricing', {})
        d['pricing'] = AgentPricing(
            model=AgentPricingModel(pricing_data.get('model', 'free')),
            price_cents=pricing_data.get('price_cents', 0),
            currency=pricing_data.get('currency', 'EUR'),
            billing_period_days=pricing_data.get('billing_period_days', 30),
            usage_price_per_call_cents=pricing_data.get('usage_price_per_call_cents', 0),
            trial_days=pricing_data.get('trial_days', 0),
        )

        # Convertir les capabilities
        caps = []
        for cap_data in d.get('capabilities', []):
            caps.append(AgentCapabilitySpec(
                name=cap_data.get('name', ''),
                description=cap_data.get('description', ''),
                keywords=cap_data.get('keywords', []),
                priority=cap_data.get('priority', 0),
            ))
        d['capabilities'] = caps

        # Convertir les dates
        d['created_at'] = _str_to_datetime(d.get('created_at')) or datetime.now()
        d['updated_at'] = _str_to_datetime(d.get('updated_at')) or datetime.now()
        d['published_at'] = _str_to_datetime(d.get('published_at'))

        return MarketplaceAgent(**d)

    def save(self, agent: MarketplaceAgent) -> MarketplaceAgent:
        with self._lock:
            self._agents[agent.id] = agent
            self._save()
            return agent

    def get_by_id(self, agent_id: str) -> Optional[MarketplaceAgent]:
        with self._lock:
            return self._agents.get(agent_id)

    def get_by_slug(self, slug: str) -> Optional[MarketplaceAgent]:
        with self._lock:
            for agent in self._agents.values():
                if agent.slug == slug:
                    return agent
            return None

    def list_all(
        self,
        status: Optional[AgentStatus] = None,
        category: Optional[AgentCategory] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[MarketplaceAgent]:
        with self._lock:
            agents = list(self._agents.values())

            if status:
                agents = [a for a in agents if a.status == status]
            if category:
                agents = [a for a in agents if a.category == category]

            # Trier par popularité (download_count)
            agents.sort(key=lambda a: a.download_count, reverse=True)

            return agents[offset:offset + limit]

    def search(self, query: MarketplaceSearchQuery) -> MarketplaceSearchResult:
        with self._lock:
            agents = [a for a in self._agents.values() if a.status == AgentStatus.PUBLISHED]

            # Filtres
            if query.category:
                agents = [a for a in agents if a.category == query.category]

            if query.tags:
                agents = [a for a in agents if any(t in a.tags for t in query.tags)]

            if query.pricing_models:
                agents = [a for a in agents if a.pricing.model in query.pricing_models]

            if query.min_rating > 0:
                agents = [a for a in agents if a.average_rating >= query.min_rating]

            if query.verified_only:
                # Filtre sur éditeur vérifié - à implémenter
                pass

            # Recherche textuelle
            if query.query:
                q = query.query.lower()
                agents = [
                    a for a in agents
                    if q in a.name.lower()
                    or q in a.description.lower()
                    or any(q in t.lower() for t in a.tags)
                ]

            # Tri
            if query.sort_by == "rating":
                agents.sort(key=lambda a: a.average_rating, reverse=True)
            elif query.sort_by == "newest":
                agents.sort(key=lambda a: a.created_at, reverse=True)
            elif query.sort_by == "price":
                agents.sort(key=lambda a: a.pricing.price_cents)
            else:  # popularity
                agents.sort(key=lambda a: a.download_count, reverse=True)

            total = len(agents)
            start = (query.page - 1) * query.per_page
            end = start + query.per_page

            return MarketplaceSearchResult(
                agents=agents[start:end],
                total_count=total,
                page=query.page,
                per_page=query.per_page,
                total_pages=(total + query.per_page - 1) // query.per_page
            )

    def update(self, agent: MarketplaceAgent) -> MarketplaceAgent:
        with self._lock:
            if agent.id not in self._agents:
                raise ValueError(f"Agent {agent.id} non trouvé")
            self._agents[agent.id] = agent
            self._save()
            return agent

    def delete(self, agent_id: str) -> bool:
        with self._lock:
            if agent_id in self._agents:
                del self._agents[agent_id]
                self._save()
                return True
            return False

    def get_by_publisher(
        self,
        publisher_id: str,
        status: Optional[AgentStatus] = None
    ) -> List[MarketplaceAgent]:
        with self._lock:
            agents = [a for a in self._agents.values() if a.publisher_id == publisher_id]
            if status:
                agents = [a for a in agents if a.status == status]
            return agents

    def increment_download_count(self, agent_id: str) -> None:
        with self._lock:
            if agent_id in self._agents:
                self._agents[agent_id].download_count += 1
                self._save()


class JsonAgentPackStore(AgentPackPort):
    """Stockage des packs d'agents dans un fichier JSON."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self._packs: Dict[str, AgentPack] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding='utf-8'))
                for pack_data in data.get("packs", []):
                    pack = self._dict_to_pack(pack_data)
                    self._packs[pack.id] = pack
            except Exception as e:
                logger.error(f"Error loading packs: {e}")

    def _save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "packs": [self._pack_to_dict(p) for p in self._packs.values()],
            "updated_at": datetime.now().isoformat()
        }
        self.filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding='utf-8'
        )

    def _pack_to_dict(self, pack: AgentPack) -> Dict[str, Any]:
        d = asdict(pack)
        d = _datetime_to_str(d)
        d['status'] = pack.status.value
        d['pricing']['model'] = pack.pricing.model.value
        return d

    def _dict_to_pack(self, d: Dict[str, Any]) -> AgentPack:
        d['status'] = AgentStatus(d.get('status', 'draft'))
        pricing_data = d.get('pricing', {})
        d['pricing'] = AgentPricing(
            model=AgentPricingModel(pricing_data.get('model', 'free')),
            price_cents=pricing_data.get('price_cents', 0),
            currency=pricing_data.get('currency', 'EUR'),
        )
        d['created_at'] = _str_to_datetime(d.get('created_at')) or datetime.now()
        d['updated_at'] = _str_to_datetime(d.get('updated_at')) or datetime.now()
        return AgentPack(**d)

    def save(self, pack: AgentPack) -> AgentPack:
        with self._lock:
            self._packs[pack.id] = pack
            self._save()
            return pack

    def get_by_id(self, pack_id: str) -> Optional[AgentPack]:
        with self._lock:
            return self._packs.get(pack_id)

    def list_all(self, limit: int = 100, offset: int = 0) -> List[AgentPack]:
        with self._lock:
            packs = list(self._packs.values())
            return packs[offset:offset + limit]

    def delete(self, pack_id: str) -> bool:
        with self._lock:
            if pack_id in self._packs:
                del self._packs[pack_id]
                self._save()
                return True
            return False


class JsonAgentInstallationStore(AgentInstallationPort):
    """Stockage des installations d'agents dans un fichier JSON."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self._installations: Dict[str, AgentInstallation] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding='utf-8'))
                for inst_data in data.get("installations", []):
                    inst = self._dict_to_installation(inst_data)
                    self._installations[inst.id] = inst
            except Exception as e:
                logger.error(f"Error loading installations: {e}")

    def _save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "installations": [self._installation_to_dict(i) for i in self._installations.values()],
            "updated_at": datetime.now().isoformat()
        }
        self.filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding='utf-8'
        )

    def _installation_to_dict(self, inst: AgentInstallation) -> Dict[str, Any]:
        d = asdict(inst)
        d = _datetime_to_str(d)
        d['status'] = inst.status.value
        return d

    def _dict_to_installation(self, d: Dict[str, Any]) -> AgentInstallation:
        d['status'] = InstallationStatus(d.get('status', 'active'))
        d['installed_at'] = _str_to_datetime(d.get('installed_at')) or datetime.now()
        d['expires_at'] = _str_to_datetime(d.get('expires_at'))
        d['last_used_at'] = _str_to_datetime(d.get('last_used_at'))
        return AgentInstallation(**d)

    def save(self, installation: AgentInstallation) -> AgentInstallation:
        with self._lock:
            self._installations[installation.id] = installation
            self._save()
            return installation

    def get_by_id(self, installation_id: str) -> Optional[AgentInstallation]:
        with self._lock:
            return self._installations.get(installation_id)

    def get_by_organization(
        self,
        organization_id: str,
        active_only: bool = True
    ) -> List[AgentInstallation]:
        with self._lock:
            insts = [i for i in self._installations.values() if i.organization_id == organization_id]
            if active_only:
                insts = [i for i in insts if i.is_active()]
            return insts

    def get_by_agent(self, agent_id: str) -> List[AgentInstallation]:
        with self._lock:
            return [i for i in self._installations.values() if i.agent_id == agent_id]

    def find_installation(
        self,
        agent_id: str,
        organization_id: str
    ) -> Optional[AgentInstallation]:
        with self._lock:
            for inst in self._installations.values():
                if inst.agent_id == agent_id and inst.organization_id == organization_id:
                    return inst
            return None

    def update(self, installation: AgentInstallation) -> AgentInstallation:
        with self._lock:
            if installation.id not in self._installations:
                raise ValueError(f"Installation {installation.id} non trouvée")
            self._installations[installation.id] = installation
            self._save()
            return installation

    def delete(self, installation_id: str) -> bool:
        with self._lock:
            if installation_id in self._installations:
                del self._installations[installation_id]
                self._save()
                return True
            return False

    def count_active_by_agent(self, agent_id: str) -> int:
        with self._lock:
            return sum(
                1 for i in self._installations.values()
                if i.agent_id == agent_id and i.is_active()
            )


class JsonAgentReviewStore(AgentReviewPort):
    """Stockage des avis dans un fichier JSON."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self._reviews: Dict[str, AgentReview] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding='utf-8'))
                for review_data in data.get("reviews", []):
                    review = self._dict_to_review(review_data)
                    self._reviews[review.id] = review
            except Exception as e:
                logger.error(f"Error loading reviews: {e}")

    def _save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "reviews": [self._review_to_dict(r) for r in self._reviews.values()],
            "updated_at": datetime.now().isoformat()
        }
        self.filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding='utf-8'
        )

    def _review_to_dict(self, review: AgentReview) -> Dict[str, Any]:
        d = asdict(review)
        return _datetime_to_str(d)

    def _dict_to_review(self, d: Dict[str, Any]) -> AgentReview:
        d['created_at'] = _str_to_datetime(d.get('created_at')) or datetime.now()
        d['updated_at'] = _str_to_datetime(d.get('updated_at')) or datetime.now()
        d['publisher_response_at'] = _str_to_datetime(d.get('publisher_response_at'))
        return AgentReview(**d)

    def save(self, review: AgentReview) -> AgentReview:
        with self._lock:
            self._reviews[review.id] = review
            self._save()
            return review

    def get_by_id(self, review_id: str) -> Optional[AgentReview]:
        with self._lock:
            return self._reviews.get(review_id)

    def get_by_agent(
        self,
        agent_id: str,
        approved_only: bool = True,
        limit: int = 50,
        offset: int = 0
    ) -> List[AgentReview]:
        with self._lock:
            reviews = [r for r in self._reviews.values() if r.agent_id == agent_id]
            if approved_only:
                reviews = [r for r in reviews if r.is_approved]
            reviews.sort(key=lambda r: r.created_at, reverse=True)
            return reviews[offset:offset + limit]

    def update(self, review: AgentReview) -> AgentReview:
        with self._lock:
            if review.id not in self._reviews:
                raise ValueError(f"Review {review.id} non trouvée")
            self._reviews[review.id] = review
            self._save()
            return review

    def delete(self, review_id: str) -> bool:
        with self._lock:
            if review_id in self._reviews:
                del self._reviews[review_id]
                self._save()
                return True
            return False

    def calculate_average_rating(self, agent_id: str) -> float:
        with self._lock:
            reviews = [r for r in self._reviews.values() if r.agent_id == agent_id and r.is_approved]
            if not reviews:
                return 0.0
            return sum(r.rating for r in reviews) / len(reviews)

    def count_reviews(self, agent_id: str, approved_only: bool = True) -> int:
        with self._lock:
            reviews = [r for r in self._reviews.values() if r.agent_id == agent_id]
            if approved_only:
                reviews = [r for r in reviews if r.is_approved]
            return len(reviews)


class JsonPublisherStore(PublisherPort):
    """Stockage des éditeurs dans un fichier JSON."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self._publishers: Dict[str, Publisher] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding='utf-8'))
                for pub_data in data.get("publishers", []):
                    pub = self._dict_to_publisher(pub_data)
                    self._publishers[pub.id] = pub
            except Exception as e:
                logger.error(f"Error loading publishers: {e}")

    def _save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "publishers": [self._publisher_to_dict(p) for p in self._publishers.values()],
            "updated_at": datetime.now().isoformat()
        }
        self.filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding='utf-8'
        )

    def _publisher_to_dict(self, pub: Publisher) -> Dict[str, Any]:
        d = asdict(pub)
        return _datetime_to_str(d)

    def _dict_to_publisher(self, d: Dict[str, Any]) -> Publisher:
        d['created_at'] = _str_to_datetime(d.get('created_at')) or datetime.now()
        return Publisher(**d)

    def save(self, publisher: Publisher) -> Publisher:
        with self._lock:
            self._publishers[publisher.id] = publisher
            self._save()
            return publisher

    def get_by_id(self, publisher_id: str) -> Optional[Publisher]:
        with self._lock:
            return self._publishers.get(publisher_id)

    def list_all(
        self,
        verified_only: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> List[Publisher]:
        with self._lock:
            pubs = list(self._publishers.values())
            if verified_only:
                pubs = [p for p in pubs if p.verified]
            return pubs[offset:offset + limit]

    def update(self, publisher: Publisher) -> Publisher:
        with self._lock:
            if publisher.id not in self._publishers:
                raise ValueError(f"Publisher {publisher.id} non trouvé")
            self._publishers[publisher.id] = publisher
            self._save()
            return publisher

    def delete(self, publisher_id: str) -> bool:
        with self._lock:
            if publisher_id in self._publishers:
                del self._publishers[publisher_id]
                self._save()
                return True
            return False

    def get_by_email(self, email: str) -> Optional[Publisher]:
        with self._lock:
            for pub in self._publishers.values():
                if pub.email == email:
                    return pub
            return None


# =============================================================================
# SINGLETONS ET FACTORY
# =============================================================================

_agent_store: Optional[JsonMarketplaceAgentStore] = None
_pack_store: Optional[JsonAgentPackStore] = None
_installation_store: Optional[JsonAgentInstallationStore] = None
_review_store: Optional[JsonAgentReviewStore] = None
_publisher_store: Optional[JsonPublisherStore] = None


def get_marketplace_stores(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Retourne tous les stores de la marketplace (singletons).

    Args:
        data_dir: Répertoire de données optionnel.

    Returns:
        Dictionnaire avec tous les stores.
    """
    global _agent_store, _pack_store, _installation_store, _review_store, _publisher_store

    if data_dir is None:
        from app.config import PROJECT_ROOT
        data_dir = PROJECT_ROOT / "data" / "marketplace"

    data_dir.mkdir(parents=True, exist_ok=True)

    if _agent_store is None:
        _agent_store = JsonMarketplaceAgentStore(data_dir / "agents.json")
    if _pack_store is None:
        _pack_store = JsonAgentPackStore(data_dir / "packs.json")
    if _installation_store is None:
        _installation_store = JsonAgentInstallationStore(data_dir / "installations.json")
    if _review_store is None:
        _review_store = JsonAgentReviewStore(data_dir / "reviews.json")
    if _publisher_store is None:
        _publisher_store = JsonPublisherStore(data_dir / "publishers.json")

    return {
        "agent_store": _agent_store,
        "pack_store": _pack_store,
        "installation_store": _installation_store,
        "review_store": _review_store,
        "publisher_store": _publisher_store,
    }


def reset_marketplace_stores() -> None:
    """Réinitialise tous les singletons (utile pour les tests)."""
    global _agent_store, _pack_store, _installation_store, _review_store, _publisher_store
    _agent_store = None
    _pack_store = None
    _installation_store = None
    _review_store = None
    _publisher_store = None
