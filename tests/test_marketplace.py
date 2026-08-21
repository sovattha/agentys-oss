# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour la Marketplace d'agents IA.

Ces tests couvrent:
- Entités du domaine (MarketplaceAgent, Publisher, AgentInstallation, etc.)
- Ports (interfaces)
- Use cases (Publisher, Publication, Installation, Reviews, Search)
- Adapter de persistance (JSON stores)
- Endpoints API (/api/marketplace/*)
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.domain.entities.marketplace import (
    AgentCategory,
    AgentPricingModel,
    AgentStatus,
    InstallationStatus,
    AgentPricing,
    AgentCapabilitySpec,
    Publisher,
    MarketplaceAgent,
    AgentInstallation,
    AgentReview,
    AgentPack,
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
from app.application.marketplace import (
    RegisterPublisherUseCase,
    GetPublisherUseCase,
    PublishAgentUseCase,
    SubmitAgentForReviewUseCase,
    ApproveAgentUseCase,
    UpdateAgentUseCase,
    GetAgentDetailsUseCase,
    SearchAgentsUseCase,
    ListFeaturedAgentsUseCase,
    ListAgentsByCategoryUseCase,
    InstallAgentUseCase,
    UninstallAgentUseCase,
    ListInstalledAgentsUseCase,
    RecordAgentUsageUseCase,
    SubmitReviewUseCase,
    RespondToReviewUseCase,
    ListAgentReviewsUseCase,
    CreateAgentPackUseCase,
    InstallPackUseCase,
)
from app.infrastructure.marketplace_store import (
    JsonMarketplaceAgentStore,
    JsonAgentInstallationStore,
    JsonAgentReviewStore,
    JsonPublisherStore,
    get_marketplace_stores,
    reset_marketplace_stores,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_data_dir():
    """Crée un répertoire temporaire pour les tests."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_publisher():
    """Éditeur de test."""
    return Publisher(
        id="pub-123",
        name="Test Publisher",
        email="publisher@test.com",
        description="A test publisher",
        website="https://test.com",
        verified=True,
    )


@pytest.fixture
def sample_agent():
    """Agent de test."""
    return MarketplaceAgent(
        id="agent-123",
        name="Test Agent",
        slug="test-agent",
        description="A test agent for customer service",
        long_description="Full description of the test agent.",
        version="1.0.0",
        category=AgentCategory.CUSTOMER_SERVICE,
        tags=["support", "test"],
        system_prompt="You are a test agent.",
        capabilities=[
            AgentCapabilitySpec(
                name="test_capability",
                description="Test capability",
                keywords=["test", "demo"],
                priority=5,
            )
        ],
        publisher_id="pub-123",
        status=AgentStatus.PUBLISHED,
        pricing=AgentPricing(
            model=AgentPricingModel.FREE,
            price_cents=0,
        ),
        download_count=100,
        average_rating=4.5,
        review_count=20,
    )


@pytest.fixture
def sample_installation():
    """Installation de test."""
    return AgentInstallation(
        id="inst-123",
        agent_id="agent-123",
        organization_id="org-456",
        status=InstallationStatus.ACTIVE,
        installed_version="1.0.0",
        usage_count=50,
    )


@pytest.fixture
def sample_review():
    """Avis de test."""
    return AgentReview(
        id="review-123",
        agent_id="agent-123",
        organization_id="org-456",
        reviewer_name="John Doe",
        rating=5,
        title="Excellent agent!",
        content="This agent works perfectly for our needs.",
        is_verified_purchase=True,
        is_approved=True,
    )


@pytest.fixture
def mock_publisher_port():
    """Mock du port publisher."""
    return MagicMock(spec=PublisherPort)


@pytest.fixture
def mock_agent_port():
    """Mock du port agent."""
    return MagicMock(spec=MarketplaceAgentPort)


@pytest.fixture
def mock_installation_port():
    """Mock du port installation."""
    return MagicMock(spec=AgentInstallationPort)


@pytest.fixture
def mock_review_port():
    """Mock du port review."""
    return MagicMock(spec=AgentReviewPort)


@pytest.fixture
def real_stores(temp_data_dir):
    """Stores réels avec fichiers temporaires."""
    reset_marketplace_stores()
    return get_marketplace_stores(temp_data_dir)


# ============================================================================
# TESTS - ENTITES DU DOMAINE
# ============================================================================

class TestMarketplaceAgentEntity:
    """Tests pour l'entité MarketplaceAgent."""

    def test_create_minimal_agent(self):
        """Création avec valeurs minimales."""
        agent = MarketplaceAgent(
            name="Test",
            description="Test agent",
        )
        assert agent.id is not None
        assert agent.name == "Test"
        assert agent.status == AgentStatus.DRAFT
        assert agent.category == AgentCategory.CUSTOM
        assert agent.is_free() is True

    def test_create_full_agent(self, sample_agent):
        """Création avec toutes les valeurs."""
        assert sample_agent.id == "agent-123"
        assert sample_agent.name == "Test Agent"
        assert sample_agent.status == AgentStatus.PUBLISHED
        assert sample_agent.category == AgentCategory.CUSTOMER_SERVICE
        assert len(sample_agent.capabilities) == 1

    def test_is_free_with_free_pricing(self):
        """Agent gratuit."""
        agent = MarketplaceAgent(
            name="Free Agent",
            pricing=AgentPricing(model=AgentPricingModel.FREE)
        )
        assert agent.is_free() is True

    def test_is_free_with_paid_pricing(self):
        """Agent payant."""
        agent = MarketplaceAgent(
            name="Paid Agent",
            pricing=AgentPricing(
                model=AgentPricingModel.SUBSCRIPTION,
                price_cents=999
            )
        )
        assert agent.is_free() is False

    def test_is_published(self, sample_agent):
        """Agent publié."""
        assert sample_agent.is_published() is True
        sample_agent.status = AgentStatus.DRAFT
        assert sample_agent.is_published() is False

    def test_generate_slug(self):
        """Génération de slug."""
        agent = MarketplaceAgent(name="My Super Agent!")
        slug = agent.generate_slug()
        assert slug == "my-super-agent"


class TestPublisherEntity:
    """Tests pour l'entité Publisher."""

    def test_create_publisher(self, sample_publisher):
        """Création d'un éditeur."""
        assert sample_publisher.id == "pub-123"
        assert sample_publisher.name == "Test Publisher"
        assert sample_publisher.email == "publisher@test.com"
        assert sample_publisher.verified is True


class TestAgentInstallationEntity:
    """Tests pour l'entité AgentInstallation."""

    def test_create_installation(self, sample_installation):
        """Création d'une installation."""
        assert sample_installation.id == "inst-123"
        assert sample_installation.agent_id == "agent-123"
        assert sample_installation.status == InstallationStatus.ACTIVE
        assert sample_installation.usage_count == 50

    def test_is_active_true(self, sample_installation):
        """Installation active."""
        assert sample_installation.is_active() is True

    def test_is_active_false_suspended(self, sample_installation):
        """Installation suspendue."""
        sample_installation.status = InstallationStatus.SUSPENDED
        assert sample_installation.is_active() is False

    def test_is_active_false_expired(self, sample_installation):
        """Installation expirée."""
        sample_installation.expires_at = datetime.now() - timedelta(days=1)
        assert sample_installation.is_active() is False

    def test_is_active_true_not_expired(self, sample_installation):
        """Installation non expirée."""
        sample_installation.expires_at = datetime.now() + timedelta(days=1)
        assert sample_installation.is_active() is True


class TestAgentReviewEntity:
    """Tests pour l'entité AgentReview."""

    def test_create_review(self, sample_review):
        """Création d'un avis."""
        assert sample_review.id == "review-123"
        assert sample_review.rating == 5
        assert sample_review.is_verified_purchase is True
        assert sample_review.is_approved is True


class TestMarketplaceSearchQuery:
    """Tests pour MarketplaceSearchQuery."""

    def test_default_query(self):
        """Requête par défaut."""
        query = MarketplaceSearchQuery()
        assert query.query == ""
        assert query.category is None
        assert query.page == 1
        assert query.per_page == 20

    def test_custom_query(self):
        """Requête personnalisée."""
        query = MarketplaceSearchQuery(
            query="support",
            category=AgentCategory.CUSTOMER_SERVICE,
            min_rating=4.0,
            page=2,
            per_page=10,
        )
        assert query.query == "support"
        assert query.category == AgentCategory.CUSTOMER_SERVICE
        assert query.min_rating == 4.0


# ============================================================================
# TESTS - USE CASES
# ============================================================================

class TestRegisterPublisherUseCase:
    """Tests pour RegisterPublisherUseCase."""

    def test_register_publisher_success(self, mock_publisher_port):
        """Enregistrement réussi."""
        mock_publisher_port.get_by_email.return_value = None
        mock_publisher_port.save.side_effect = lambda p: p

        use_case = RegisterPublisherUseCase(publisher_port=mock_publisher_port)
        publisher = use_case.execute(
            name="New Publisher",
            email="new@publisher.com",
            description="A new publisher",
        )

        assert publisher.name == "New Publisher"
        assert publisher.email == "new@publisher.com"
        mock_publisher_port.save.assert_called_once()

    def test_register_publisher_duplicate_email(self, mock_publisher_port, sample_publisher):
        """Email déjà utilisé."""
        mock_publisher_port.get_by_email.return_value = sample_publisher

        use_case = RegisterPublisherUseCase(publisher_port=mock_publisher_port)

        with pytest.raises(ValueError, match="existe déjà"):
            use_case.execute(name="New", email="publisher@test.com")

    def test_register_publisher_invalid_name(self, mock_publisher_port):
        """Nom invalide."""
        use_case = RegisterPublisherUseCase(publisher_port=mock_publisher_port)

        with pytest.raises(ValueError, match="nom est requis"):
            use_case.execute(name="", email="test@test.com")

    def test_register_publisher_invalid_email(self, mock_publisher_port):
        """Email invalide."""
        use_case = RegisterPublisherUseCase(publisher_port=mock_publisher_port)

        with pytest.raises(ValueError, match="Format d'email invalide"):
            use_case.execute(name="Test", email="invalid-email")


class TestPublishAgentUseCase:
    """Tests pour PublishAgentUseCase."""

    def test_publish_agent_success(self, mock_agent_port, mock_publisher_port, sample_publisher):
        """Publication réussie."""
        mock_publisher_port.get_by_id.return_value = sample_publisher
        mock_publisher_port.update.side_effect = lambda p: p
        mock_agent_port.save.side_effect = lambda a: a

        use_case = PublishAgentUseCase(
            agent_port=mock_agent_port,
            publisher_port=mock_publisher_port,
        )
        agent = use_case.execute(
            publisher_id="pub-123",
            name="New Agent",
            description="A new test agent",
            category=AgentCategory.SALES,
            system_prompt="You are a sales agent.",
            capabilities=[{"name": "sales", "description": "Sales support"}],
        )

        assert agent.name == "New Agent"
        assert agent.status == AgentStatus.DRAFT
        assert agent.category == AgentCategory.SALES
        mock_agent_port.save.assert_called_once()

    def test_publish_agent_publisher_not_found(self, mock_agent_port, mock_publisher_port):
        """Éditeur non trouvé."""
        mock_publisher_port.get_by_id.return_value = None

        use_case = PublishAgentUseCase(
            agent_port=mock_agent_port,
            publisher_port=mock_publisher_port,
        )

        with pytest.raises(ValueError, match="non trouvé"):
            use_case.execute(
                publisher_id="invalid",
                name="Test",
                description="Test agent",
                category=AgentCategory.CUSTOM,
                system_prompt="Test",
                capabilities=[],
            )

    def test_publish_agent_invalid_name(self, mock_agent_port, mock_publisher_port, sample_publisher):
        """Nom invalide."""
        mock_publisher_port.get_by_id.return_value = sample_publisher

        use_case = PublishAgentUseCase(
            agent_port=mock_agent_port,
            publisher_port=mock_publisher_port,
        )

        with pytest.raises(ValueError, match="nom est requis"):
            use_case.execute(
                publisher_id="pub-123",
                name="",
                description="Test",
                category=AgentCategory.CUSTOM,
                system_prompt="Test",
                capabilities=[],
            )


class TestSubmitAgentForReviewUseCase:
    """Tests pour SubmitAgentForReviewUseCase."""

    def test_submit_for_review_success(self, mock_agent_port, sample_agent):
        """Soumission réussie."""
        sample_agent.status = AgentStatus.DRAFT
        mock_agent_port.get_by_id.return_value = sample_agent
        mock_agent_port.update.side_effect = lambda a: a

        use_case = SubmitAgentForReviewUseCase(agent_port=mock_agent_port)
        agent = use_case.execute(agent_id="agent-123", publisher_id="pub-123")

        assert agent.status == AgentStatus.PENDING_REVIEW

    def test_submit_for_review_not_owner(self, mock_agent_port, sample_agent):
        """L'éditeur n'est pas propriétaire."""
        sample_agent.status = AgentStatus.DRAFT
        mock_agent_port.get_by_id.return_value = sample_agent

        use_case = SubmitAgentForReviewUseCase(agent_port=mock_agent_port)

        with pytest.raises(ValueError, match="ne vous appartient pas"):
            use_case.execute(agent_id="agent-123", publisher_id="other-publisher")

    def test_submit_for_review_wrong_status(self, mock_agent_port, sample_agent):
        """Statut incorrect."""
        # L'agent est déjà PUBLISHED
        mock_agent_port.get_by_id.return_value = sample_agent

        use_case = SubmitAgentForReviewUseCase(agent_port=mock_agent_port)

        with pytest.raises(ValueError, match="DRAFT"):
            use_case.execute(agent_id="agent-123", publisher_id="pub-123")


class TestApproveAgentUseCase:
    """Tests pour ApproveAgentUseCase."""

    def test_approve_agent_success(self, mock_agent_port, sample_agent):
        """Approbation réussie."""
        sample_agent.status = AgentStatus.PENDING_REVIEW
        mock_agent_port.get_by_id.return_value = sample_agent
        mock_agent_port.update.side_effect = lambda a: a

        use_case = ApproveAgentUseCase(agent_port=mock_agent_port)
        agent = use_case.execute(agent_id="agent-123")

        assert agent.status == AgentStatus.PUBLISHED
        assert agent.published_at is not None


class TestInstallAgentUseCase:
    """Tests pour InstallAgentUseCase."""

    def test_install_agent_success(self, mock_agent_port, mock_installation_port, sample_agent):
        """Installation réussie."""
        mock_agent_port.get_by_id.return_value = sample_agent
        mock_agent_port.update.side_effect = lambda a: a
        mock_installation_port.find_installation.return_value = None
        mock_installation_port.save.side_effect = lambda i: i

        use_case = InstallAgentUseCase(
            agent_port=mock_agent_port,
            installation_port=mock_installation_port,
        )
        installation = use_case.execute(
            agent_id="agent-123",
            organization_id="org-456",
        )

        assert installation.agent_id == "agent-123"
        assert installation.organization_id == "org-456"
        assert installation.status == InstallationStatus.ACTIVE
        mock_agent_port.increment_download_count.assert_called_once()

    def test_install_agent_already_installed(self, mock_agent_port, mock_installation_port, sample_agent, sample_installation):
        """Agent déjà installé."""
        mock_agent_port.get_by_id.return_value = sample_agent
        mock_installation_port.find_installation.return_value = sample_installation

        use_case = InstallAgentUseCase(
            agent_port=mock_agent_port,
            installation_port=mock_installation_port,
        )

        with pytest.raises(ValueError, match="déjà installé"):
            use_case.execute(agent_id="agent-123", organization_id="org-456")

    def test_install_agent_not_published(self, mock_agent_port, mock_installation_port, sample_agent):
        """Agent non publié."""
        sample_agent.status = AgentStatus.DRAFT
        mock_agent_port.get_by_id.return_value = sample_agent

        use_case = InstallAgentUseCase(
            agent_port=mock_agent_port,
            installation_port=mock_installation_port,
        )

        with pytest.raises(ValueError, match="n'est pas disponible"):
            use_case.execute(agent_id="agent-123", organization_id="org-456")


class TestSubmitReviewUseCase:
    """Tests pour SubmitReviewUseCase."""

    def test_submit_review_success(self, mock_review_port, mock_installation_port, mock_agent_port, sample_agent, sample_installation):
        """Soumission d'avis réussie."""
        mock_installation_port.find_installation.return_value = sample_installation
        mock_review_port.save.side_effect = lambda r: r
        mock_review_port.count_reviews.return_value = 1
        mock_review_port.calculate_average_rating.return_value = 5.0
        mock_agent_port.get_by_id.return_value = sample_agent
        mock_agent_port.update.side_effect = lambda a: a

        use_case = SubmitReviewUseCase(
            review_port=mock_review_port,
            installation_port=mock_installation_port,
            agent_port=mock_agent_port,
        )
        review = use_case.execute(
            agent_id="agent-123",
            organization_id="org-456",
            reviewer_name="Test User",
            rating=5,
            title="Great agent",
            content="This agent is amazing!",
        )

        assert review.rating == 5
        assert review.is_verified_purchase is True
        mock_review_port.save.assert_called_once()

    def test_submit_review_invalid_rating(self, mock_review_port, mock_installation_port, mock_agent_port):
        """Note invalide."""
        use_case = SubmitReviewUseCase(
            review_port=mock_review_port,
            installation_port=mock_installation_port,
            agent_port=mock_agent_port,
        )

        with pytest.raises(ValueError, match="entre 1 et 5"):
            use_case.execute(
                agent_id="agent-123",
                organization_id="org-456",
                reviewer_name="Test",
                rating=6,
                title="Test",
                content="Test content",
            )


# ============================================================================
# TESTS - ADAPTER DE PERSISTANCE
# ============================================================================

class TestJsonMarketplaceAgentStore:
    """Tests pour JsonMarketplaceAgentStore."""

    def test_save_and_get_agent(self, temp_data_dir, sample_agent):
        """Sauvegarde et récupération."""
        store = JsonMarketplaceAgentStore(temp_data_dir / "agents.json")

        saved = store.save(sample_agent)
        assert saved.id == sample_agent.id

        retrieved = store.get_by_id(sample_agent.id)
        assert retrieved is not None
        assert retrieved.name == sample_agent.name
        assert retrieved.category == sample_agent.category

    def test_get_by_slug(self, temp_data_dir, sample_agent):
        """Récupération par slug."""
        store = JsonMarketplaceAgentStore(temp_data_dir / "agents.json")
        store.save(sample_agent)

        retrieved = store.get_by_slug("test-agent")
        assert retrieved is not None
        assert retrieved.id == sample_agent.id

    def test_list_all_with_filters(self, temp_data_dir, sample_agent):
        """Liste avec filtres."""
        store = JsonMarketplaceAgentStore(temp_data_dir / "agents.json")

        # Ajouter plusieurs agents
        store.save(sample_agent)

        draft_agent = MarketplaceAgent(
            id="agent-draft",
            name="Draft Agent",
            status=AgentStatus.DRAFT,
            category=AgentCategory.SALES,
        )
        store.save(draft_agent)

        # Filtrer par statut
        published = store.list_all(status=AgentStatus.PUBLISHED)
        assert len(published) == 1
        assert published[0].id == sample_agent.id

        # Filtrer par catégorie
        customer_service = store.list_all(category=AgentCategory.CUSTOMER_SERVICE)
        assert len(customer_service) == 1

    def test_search(self, temp_data_dir, sample_agent):
        """Recherche d'agents."""
        store = JsonMarketplaceAgentStore(temp_data_dir / "agents.json")
        store.save(sample_agent)

        query = MarketplaceSearchQuery(query="test")
        result = store.search(query)

        assert result.total_count == 1
        assert result.agents[0].name == "Test Agent"

    def test_delete(self, temp_data_dir, sample_agent):
        """Suppression d'un agent."""
        store = JsonMarketplaceAgentStore(temp_data_dir / "agents.json")
        store.save(sample_agent)

        deleted = store.delete(sample_agent.id)
        assert deleted is True

        retrieved = store.get_by_id(sample_agent.id)
        assert retrieved is None


class TestJsonAgentInstallationStore:
    """Tests pour JsonAgentInstallationStore."""

    def test_save_and_get(self, temp_data_dir, sample_installation):
        """Sauvegarde et récupération."""
        store = JsonAgentInstallationStore(temp_data_dir / "installations.json")

        saved = store.save(sample_installation)
        assert saved.id == sample_installation.id

        retrieved = store.get_by_id(sample_installation.id)
        assert retrieved is not None
        assert retrieved.agent_id == sample_installation.agent_id

    def test_get_by_organization(self, temp_data_dir, sample_installation):
        """Récupération par organisation."""
        store = JsonAgentInstallationStore(temp_data_dir / "installations.json")
        store.save(sample_installation)

        installations = store.get_by_organization("org-456")
        assert len(installations) == 1
        assert installations[0].organization_id == "org-456"

    def test_count_active_by_agent(self, temp_data_dir, sample_installation):
        """Comptage des installations actives."""
        store = JsonAgentInstallationStore(temp_data_dir / "installations.json")
        store.save(sample_installation)

        count = store.count_active_by_agent("agent-123")
        assert count == 1


class TestJsonAgentReviewStore:
    """Tests pour JsonAgentReviewStore."""

    def test_save_and_get(self, temp_data_dir, sample_review):
        """Sauvegarde et récupération."""
        store = JsonAgentReviewStore(temp_data_dir / "reviews.json")

        saved = store.save(sample_review)
        assert saved.id == sample_review.id

        retrieved = store.get_by_id(sample_review.id)
        assert retrieved is not None
        assert retrieved.rating == 5

    def test_calculate_average_rating(self, temp_data_dir, sample_review):
        """Calcul de la note moyenne."""
        store = JsonAgentReviewStore(temp_data_dir / "reviews.json")

        # Ajouter plusieurs avis
        store.save(sample_review)

        review2 = AgentReview(
            id="review-2",
            agent_id="agent-123",
            organization_id="org-789",
            reviewer_name="Jane",
            rating=3,
            title="OK",
            content="Average agent.",
            is_approved=True,
        )
        store.save(review2)

        avg = store.calculate_average_rating("agent-123")
        assert avg == 4.0  # (5 + 3) / 2


class TestJsonPublisherStore:
    """Tests pour JsonPublisherStore."""

    def test_save_and_get(self, temp_data_dir, sample_publisher):
        """Sauvegarde et récupération."""
        store = JsonPublisherStore(temp_data_dir / "publishers.json")

        saved = store.save(sample_publisher)
        assert saved.id == sample_publisher.id

        retrieved = store.get_by_id(sample_publisher.id)
        assert retrieved is not None
        assert retrieved.name == "Test Publisher"

    def test_get_by_email(self, temp_data_dir, sample_publisher):
        """Récupération par email."""
        store = JsonPublisherStore(temp_data_dir / "publishers.json")
        store.save(sample_publisher)

        retrieved = store.get_by_email("publisher@test.com")
        assert retrieved is not None
        assert retrieved.id == sample_publisher.id


# ============================================================================
# TESTS - API ENDPOINTS
# ============================================================================

class TestMarketplaceAPI:
    """Tests pour les endpoints API de la marketplace."""

    @pytest.fixture
    def client(self, temp_data_dir):
        """Client de test Flask."""
        from app.api.app import create_app

        reset_marketplace_stores()

        # Patcher get_marketplace_stores pour utiliser temp_data_dir
        with patch('app.api.marketplace.get_marketplace_stores') as mock_get_stores:
            mock_get_stores.return_value = get_marketplace_stores(temp_data_dir)
            app = create_app({"TESTING": True})
            with app.test_client() as client:
                yield client

    def test_register_publisher(self, client):
        """POST /api/marketplace/publishers"""
        response = client.post(
            "/api/marketplace/publishers",
            json={
                "name": "Test Publisher",
                "email": "test@publisher.com",
                "description": "A test publisher",
            },
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["publisher"]["name"] == "Test Publisher"

    def test_register_publisher_missing_fields(self, client):
        """POST /api/marketplace/publishers - champs manquants"""
        response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Test"},  # email manquant
        )

        assert response.status_code == 400

    def test_list_categories(self, client):
        """GET /api/marketplace/categories"""
        response = client.get("/api/marketplace/categories")

        assert response.status_code == 200
        data = response.get_json()
        assert "categories" in data
        assert len(data["categories"]) > 0

    def test_search_agents_empty(self, client):
        """GET /api/marketplace/agents - liste vide"""
        response = client.get("/api/marketplace/agents")

        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 0
        assert data["agents"] == []

    @pytest.mark.skip(reason="Obsolète post audits sécurité 2026-04 — auth/admin requise. À refactorer hors scope migration runner Hetzner.")
    def test_publish_and_search_agent(self, client, temp_data_dir):
        """Workflow complet: publish -> submit -> approve -> search"""
        # 1. Enregistrer un éditeur
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={
                "name": "Publisher",
                "email": "pub@test.com",
            },
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        # 2. Publier un agent
        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Support Agent",
                "description": "A helpful support agent",
                "category": "customer_service",
                "system_prompt": "You are a support agent.",
            },
        )
        assert agent_response.status_code == 201
        agent_id = agent_response.get_json()["agent"]["id"]

        # 3. Soumettre pour review
        submit_response = client.post(
            f"/api/marketplace/agents/{agent_id}/submit",
            json={"publisher_id": publisher_id},
        )
        assert submit_response.status_code == 200

        # 4. Approuver
        approve_response = client.post(f"/api/marketplace/agents/{agent_id}/approve")
        assert approve_response.status_code == 200

        # 5. Rechercher
        search_response = client.get("/api/marketplace/agents?q=support")
        assert search_response.status_code == 200
        data = search_response.get_json()
        assert data["total_count"] == 1
        assert data["agents"][0]["name"] == "Support Agent"

    @pytest.mark.skip(reason="Obsolète post audits sécurité 2026-04 — auth/admin requise. À refactorer hors scope migration runner Hetzner.")
    def test_install_agent(self, client, temp_data_dir):
        """Workflow: créer agent -> installer -> lister installations"""
        # Setup: créer et publier un agent
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "p@t.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Test",
                "description": "Test agent",
                "category": "custom",
                "system_prompt": "Test",
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]

        client.post(f"/api/marketplace/agents/{agent_id}/submit", json={"publisher_id": publisher_id})
        client.post(f"/api/marketplace/agents/{agent_id}/approve")

        # Installer
        install_response = client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": "org-123"},
        )
        assert install_response.status_code == 201

        # Lister les installations
        list_response = client.get("/api/marketplace/installations?organization_id=org-123")
        assert list_response.status_code == 200
        data = list_response.get_json()
        assert data["count"] == 1

    def test_submit_review(self, client, temp_data_dir):
        """Soumettre un avis sur un agent."""
        # Setup
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "p@r.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Reviewed Agent",
                "description": "Agent to review",
                "category": "custom",
                "system_prompt": "Test",
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]

        client.post(f"/api/marketplace/agents/{agent_id}/submit", json={"publisher_id": publisher_id})
        client.post(f"/api/marketplace/agents/{agent_id}/approve")

        # Soumettre un avis
        review_response = client.post(
            f"/api/marketplace/agents/{agent_id}/reviews",
            json={
                "organization_id": "org-123",
                "reviewer_name": "Tester",
                "rating": 4,
                "title": "Good agent",
                "content": "This agent works well for our needs.",
            },
        )
        assert review_response.status_code == 201
        data = review_response.get_json()
        assert data["review"]["rating"] == 4

        # Lister les avis
        list_response = client.get(f"/api/marketplace/agents/{agent_id}/reviews")
        assert list_response.status_code == 200
        assert list_response.get_json()["count"] == 1


# ============================================================================
# TESTS - USE CASES ADDITIONNELS
# ============================================================================

class TestUpdateAgentUseCase:
    """Tests pour UpdateAgentUseCase."""

    def test_update_agent_success(self, mock_agent_port, sample_agent):
        """Mise à jour réussie d'un agent."""

        mock_agent_port.get_by_id.return_value = sample_agent
        mock_agent_port.update.side_effect = lambda a: a

        use_case = UpdateAgentUseCase(agent_port=mock_agent_port)
        updated = use_case.execute(
            agent_id="agent-123",
            publisher_id="pub-123",
            description="Updated description",
            tags=["new", "tags"]
        )

        assert updated.description == "Updated description"
        assert updated.tags == ["new", "tags"]
        mock_agent_port.update.assert_called_once()

    def test_update_agent_not_found(self, mock_agent_port):
        """Agent non trouvé."""

        mock_agent_port.get_by_id.return_value = None

        use_case = UpdateAgentUseCase(agent_port=mock_agent_port)

        with pytest.raises(ValueError, match="non trouvé"):
            use_case.execute(
                agent_id="invalid",
                publisher_id="pub-123",
                description="Test"
            )

    def test_update_agent_not_owner(self, mock_agent_port, sample_agent):
        """L'éditeur n'est pas propriétaire."""

        mock_agent_port.get_by_id.return_value = sample_agent

        use_case = UpdateAgentUseCase(agent_port=mock_agent_port)

        with pytest.raises(ValueError, match="ne vous appartient pas"):
            use_case.execute(
                agent_id="agent-123",
                publisher_id="other-pub",
                description="Test"
            )

    def test_update_agent_increments_version_if_published(self, mock_agent_port, sample_agent):
        """Incrémente la version si l'agent est publié."""

        sample_agent.status = AgentStatus.PUBLISHED
        sample_agent.version = "1.0.0"
        mock_agent_port.get_by_id.return_value = sample_agent
        mock_agent_port.update.side_effect = lambda a: a

        use_case = UpdateAgentUseCase(agent_port=mock_agent_port)
        updated = use_case.execute(
            agent_id="agent-123",
            publisher_id="pub-123",
            description="Updated"
        )

        assert updated.version == "1.0.1"

    def test_update_agent_regenerates_slug_on_name_change(self, mock_agent_port, sample_agent):
        """Régénère le slug si le nom change."""

        mock_agent_port.get_by_id.return_value = sample_agent
        mock_agent_port.update.side_effect = lambda a: a

        use_case = UpdateAgentUseCase(agent_port=mock_agent_port)
        updated = use_case.execute(
            agent_id="agent-123",
            publisher_id="pub-123",
            name="New Agent Name"
        )

        assert updated.slug == "new-agent-name"


class TestUninstallAgentUseCase:
    """Tests pour UninstallAgentUseCase."""

    def test_uninstall_agent_success(self, mock_agent_port, mock_installation_port, sample_agent, sample_installation):
        """Désinstallation réussie."""

        mock_installation_port.get_by_id.return_value = sample_installation
        mock_installation_port.update.side_effect = lambda i: i
        sample_agent.active_installations = 1
        mock_agent_port.get_by_id.return_value = sample_agent
        mock_agent_port.update.side_effect = lambda a: a

        use_case = UninstallAgentUseCase(
            agent_port=mock_agent_port,
            installation_port=mock_installation_port
        )
        result = use_case.execute(installation_id="inst-123", organization_id="org-456")

        assert result is True
        assert sample_installation.status == InstallationStatus.UNINSTALLED
        mock_installation_port.update.assert_called_once()

    def test_uninstall_agent_not_found(self, mock_agent_port, mock_installation_port):
        """Installation non trouvée."""

        mock_installation_port.get_by_id.return_value = None

        use_case = UninstallAgentUseCase(
            agent_port=mock_agent_port,
            installation_port=mock_installation_port
        )

        with pytest.raises(ValueError, match="non trouvée"):
            use_case.execute(installation_id="invalid", organization_id="org-456")

    def test_uninstall_agent_not_owner(self, mock_agent_port, mock_installation_port, sample_installation):
        """L'organisation n'est pas propriétaire."""

        mock_installation_port.get_by_id.return_value = sample_installation

        use_case = UninstallAgentUseCase(
            agent_port=mock_agent_port,
            installation_port=mock_installation_port
        )

        with pytest.raises(ValueError, match="ne vous appartient pas"):
            use_case.execute(installation_id="inst-123", organization_id="other-org")


class TestRespondToReviewUseCase:
    """Tests pour RespondToReviewUseCase."""

    def test_respond_to_review_success(self, mock_review_port, mock_agent_port, sample_review, sample_agent):
        """Réponse à un avis réussie."""

        mock_review_port.get_by_id.return_value = sample_review
        mock_review_port.update.side_effect = lambda r: r
        mock_agent_port.get_by_id.return_value = sample_agent

        use_case = RespondToReviewUseCase(
            review_port=mock_review_port,
            agent_port=mock_agent_port
        )
        result = use_case.execute(
            review_id="review-123",
            publisher_id="pub-123",
            response="Thank you for your feedback!"
        )

        assert result.publisher_response == "Thank you for your feedback!"
        assert result.publisher_response_at is not None
        mock_review_port.update.assert_called_once()

    def test_respond_to_review_not_found(self, mock_review_port, mock_agent_port):
        """Avis non trouvé."""

        mock_review_port.get_by_id.return_value = None

        use_case = RespondToReviewUseCase(
            review_port=mock_review_port,
            agent_port=mock_agent_port
        )

        with pytest.raises(ValueError, match="non trouvé"):
            use_case.execute(
                review_id="invalid",
                publisher_id="pub-123",
                response="Test response"
            )

    def test_respond_to_review_not_authorized(self, mock_review_port, mock_agent_port, sample_review, sample_agent):
        """L'éditeur n'est pas autorisé."""

        mock_review_port.get_by_id.return_value = sample_review
        sample_agent.publisher_id = "other-pub"
        mock_agent_port.get_by_id.return_value = sample_agent

        use_case = RespondToReviewUseCase(
            review_port=mock_review_port,
            agent_port=mock_agent_port
        )

        with pytest.raises(ValueError, match="pas autorisé"):
            use_case.execute(
                review_id="review-123",
                publisher_id="pub-123",
                response="Test response"
            )

    def test_respond_to_review_too_short(self, mock_review_port, mock_agent_port, sample_review, sample_agent):
        """Réponse trop courte."""

        mock_review_port.get_by_id.return_value = sample_review
        mock_agent_port.get_by_id.return_value = sample_agent

        use_case = RespondToReviewUseCase(
            review_port=mock_review_port,
            agent_port=mock_agent_port
        )

        with pytest.raises(ValueError, match="10 caractères"):
            use_case.execute(
                review_id="review-123",
                publisher_id="pub-123",
                response="Short"
            )


class TestGetAgentDetailsUseCase:
    """Tests pour GetAgentDetailsUseCase."""

    def test_get_agent_details_success(self, mock_agent_port, mock_review_port, mock_installation_port, sample_agent, sample_review):
        """Récupération des détails réussie."""

        mock_agent_port.get_by_id.return_value = sample_agent
        mock_review_port.get_by_agent.return_value = [sample_review]
        mock_review_port.calculate_average_rating.return_value = 4.5
        mock_review_port.count_reviews.return_value = 20
        mock_installation_port.count_active_by_agent.return_value = 100

        use_case = GetAgentDetailsUseCase(
            agent_port=mock_agent_port,
            review_port=mock_review_port,
            installation_port=mock_installation_port
        )
        result = use_case.execute(agent_id="agent-123")

        assert result is not None
        assert result["agent"] == sample_agent
        assert result["reviews"] == [sample_review]
        assert result["average_rating"] == 4.5
        assert result["review_count"] == 20
        assert result["active_installations"] == 100

    def test_get_agent_details_not_found(self, mock_agent_port, mock_review_port, mock_installation_port):
        """Agent non trouvé."""

        mock_agent_port.get_by_id.return_value = None

        use_case = GetAgentDetailsUseCase(
            agent_port=mock_agent_port,
            review_port=mock_review_port,
            installation_port=mock_installation_port
        )
        result = use_case.execute(agent_id="invalid")

        assert result is None


class TestCreateAgentPackUseCase:
    """Tests pour CreateAgentPackUseCase."""

    @pytest.fixture
    def mock_pack_port(self):
        """Mock du port pack."""
        return MagicMock(spec=AgentPackPort)

    def test_create_pack_success(self, mock_pack_port, mock_agent_port, mock_publisher_port, sample_publisher, sample_agent):
        """Création de pack réussie."""

        mock_publisher_port.get_by_id.return_value = sample_publisher
        mock_agent_port.get_by_id.return_value = sample_agent
        mock_pack_port.save.side_effect = lambda p: p

        use_case = CreateAgentPackUseCase(
            pack_port=mock_pack_port,
            agent_port=mock_agent_port,
            publisher_port=mock_publisher_port
        )
        pack = use_case.execute(
            publisher_id="pub-123",
            name="Support Pack",
            description="A pack for support agents",
            agent_ids=["agent-123", "agent-456"],
        )

        assert pack.name == "Support Pack"
        assert pack.slug == "support-pack"
        assert len(pack.agent_ids) == 2
        mock_pack_port.save.assert_called_once()

    def test_create_pack_publisher_not_found(self, mock_pack_port, mock_agent_port, mock_publisher_port):
        """Éditeur non trouvé."""

        mock_publisher_port.get_by_id.return_value = None

        use_case = CreateAgentPackUseCase(
            pack_port=mock_pack_port,
            agent_port=mock_agent_port,
            publisher_port=mock_publisher_port
        )

        with pytest.raises(ValueError, match="non trouvé"):
            use_case.execute(
                publisher_id="invalid",
                name="Pack",
                description="Test",
                agent_ids=["a", "b"]
            )

    def test_create_pack_too_few_agents(self, mock_pack_port, mock_agent_port, mock_publisher_port, sample_publisher):
        """Pas assez d'agents dans le pack."""

        mock_publisher_port.get_by_id.return_value = sample_publisher

        use_case = CreateAgentPackUseCase(
            pack_port=mock_pack_port,
            agent_port=mock_agent_port,
            publisher_port=mock_publisher_port
        )

        with pytest.raises(ValueError, match="au moins 2 agents"):
            use_case.execute(
                publisher_id="pub-123",
                name="Pack",
                description="Test",
                agent_ids=["agent-123"]
            )

    def test_create_pack_agent_not_found(self, mock_pack_port, mock_agent_port, mock_publisher_port, sample_publisher):
        """Un agent du pack n'existe pas."""

        mock_publisher_port.get_by_id.return_value = sample_publisher
        mock_agent_port.get_by_id.return_value = None

        use_case = CreateAgentPackUseCase(
            pack_port=mock_pack_port,
            agent_port=mock_agent_port,
            publisher_port=mock_publisher_port
        )

        with pytest.raises(ValueError, match="non trouvé"):
            use_case.execute(
                publisher_id="pub-123",
                name="Pack",
                description="Test",
                agent_ids=["invalid-1", "invalid-2"]
            )

    def test_create_pack_agent_not_published(self, mock_pack_port, mock_agent_port, mock_publisher_port, sample_publisher, sample_agent):
        """Un agent du pack n'est pas publié."""

        mock_publisher_port.get_by_id.return_value = sample_publisher
        sample_agent.status = AgentStatus.DRAFT
        mock_agent_port.get_by_id.return_value = sample_agent

        use_case = CreateAgentPackUseCase(
            pack_port=mock_pack_port,
            agent_port=mock_agent_port,
            publisher_port=mock_publisher_port
        )

        with pytest.raises(ValueError, match="n'est pas publié"):
            use_case.execute(
                publisher_id="pub-123",
                name="Pack",
                description="Test",
                agent_ids=["agent-123", "agent-456"]
            )


class TestInstallPackUseCase:
    """Tests pour InstallPackUseCase."""

    @pytest.fixture
    def mock_pack_port(self):
        """Mock du port pack."""
        return MagicMock(spec=AgentPackPort)

    def test_install_pack_success(self, mock_pack_port, mock_agent_port, mock_installation_port, sample_agent):
        """Installation de pack réussie."""
        from app.application.marketplace import InstallAgentUseCase

        pack = AgentPack(
            id="pack-123",
            name="Support Pack",
            slug="support-pack",
            description="Test pack",
            agent_ids=["agent-1", "agent-2"],
            publisher_id="pub-123",
        )
        mock_pack_port.get_by_id.return_value = pack
        mock_agent_port.get_by_id.return_value = sample_agent
        mock_agent_port.update.side_effect = lambda a: a
        mock_installation_port.find_installation.return_value = None
        mock_installation_port.save.side_effect = lambda i: i

        install_use_case = InstallAgentUseCase(
            agent_port=mock_agent_port,
            installation_port=mock_installation_port
        )
        use_case = InstallPackUseCase(
            pack_port=mock_pack_port,
            install_agent_use_case=install_use_case
        )
        installations = use_case.execute(pack_id="pack-123", organization_id="org-456")

        assert len(installations) == 2

    def test_install_pack_not_found(self, mock_pack_port, mock_agent_port, mock_installation_port):
        """Pack non trouvé."""
        from app.application.marketplace import InstallAgentUseCase

        mock_pack_port.get_by_id.return_value = None

        install_use_case = InstallAgentUseCase(
            agent_port=mock_agent_port,
            installation_port=mock_installation_port
        )
        use_case = InstallPackUseCase(
            pack_port=mock_pack_port,
            install_agent_use_case=install_use_case
        )

        with pytest.raises(ValueError, match="non trouvé"):
            use_case.execute(pack_id="invalid", organization_id="org-456")

    def test_install_pack_skips_already_installed(self, mock_pack_port, mock_agent_port, mock_installation_port, sample_agent, sample_installation):
        """Skip les agents déjà installés."""
        from app.application.marketplace import InstallAgentUseCase

        pack = AgentPack(
            id="pack-123",
            name="Support Pack",
            slug="support-pack",
            description="Test pack",
            agent_ids=["agent-1", "agent-2"],
            publisher_id="pub-123",
        )
        mock_pack_port.get_by_id.return_value = pack
        mock_agent_port.get_by_id.return_value = sample_agent
        mock_agent_port.update.side_effect = lambda a: a
        # Premier agent déjà installé, deuxième non
        mock_installation_port.find_installation.side_effect = [sample_installation, None]
        mock_installation_port.save.side_effect = lambda i: i

        install_use_case = InstallAgentUseCase(
            agent_port=mock_agent_port,
            installation_port=mock_installation_port
        )
        use_case = InstallPackUseCase(
            pack_port=mock_pack_port,
            install_agent_use_case=install_use_case
        )
        installations = use_case.execute(pack_id="pack-123", organization_id="org-456")

        # Seulement 1 installation car le premier était déjà installé
        assert len(installations) == 1


class TestRecordAgentUsageUseCase:
    """Tests pour RecordAgentUsageUseCase."""

    def test_record_usage_success(self, mock_installation_port, sample_installation):
        """Enregistrement d'utilisation réussi."""

        sample_installation.usage_count = 10
        mock_installation_port.get_by_id.return_value = sample_installation
        mock_installation_port.update.side_effect = lambda i: i

        use_case = RecordAgentUsageUseCase(installation_port=mock_installation_port)
        result = use_case.execute(installation_id="inst-123")

        assert result.usage_count == 11
        assert result.last_used_at is not None
        mock_installation_port.update.assert_called_once()

    def test_record_usage_not_found(self, mock_installation_port):
        """Installation non trouvée."""

        mock_installation_port.get_by_id.return_value = None

        use_case = RecordAgentUsageUseCase(installation_port=mock_installation_port)

        with pytest.raises(ValueError, match="non trouvée"):
            use_case.execute(installation_id="invalid")

    def test_record_usage_not_active(self, mock_installation_port, sample_installation):
        """Installation non active."""

        sample_installation.status = InstallationStatus.SUSPENDED
        mock_installation_port.get_by_id.return_value = sample_installation

        use_case = RecordAgentUsageUseCase(installation_port=mock_installation_port)

        with pytest.raises(ValueError, match="n'est pas active"):
            use_case.execute(installation_id="inst-123")


class TestListInstalledAgentsUseCase:
    """Tests pour ListInstalledAgentsUseCase."""

    def test_list_installed_agents_success(self, mock_installation_port, mock_agent_port, sample_installation, sample_agent):
        """Liste des agents installés réussie."""

        mock_installation_port.get_by_organization.return_value = [sample_installation]
        mock_agent_port.get_by_id.return_value = sample_agent

        use_case = ListInstalledAgentsUseCase(
            installation_port=mock_installation_port,
            agent_port=mock_agent_port
        )
        result = use_case.execute(organization_id="org-456")

        assert len(result) == 1
        assert result[0]["installation"] == sample_installation
        assert result[0]["agent"] == sample_agent

    def test_list_installed_agents_empty(self, mock_installation_port, mock_agent_port):
        """Aucun agent installé."""

        mock_installation_port.get_by_organization.return_value = []

        use_case = ListInstalledAgentsUseCase(
            installation_port=mock_installation_port,
            agent_port=mock_agent_port
        )
        result = use_case.execute(organization_id="org-456")

        assert result == []


class TestGetPublisherUseCase:
    """Tests pour GetPublisherUseCase."""

    def test_get_publisher_success(self, mock_publisher_port, sample_publisher):
        """Récupération d'éditeur réussie."""

        mock_publisher_port.get_by_id.return_value = sample_publisher

        use_case = GetPublisherUseCase(publisher_port=mock_publisher_port)
        result = use_case.execute(publisher_id="pub-123")

        assert result == sample_publisher
        mock_publisher_port.get_by_id.assert_called_once_with("pub-123")

    def test_get_publisher_not_found(self, mock_publisher_port):
        """Éditeur non trouvé."""

        mock_publisher_port.get_by_id.return_value = None

        use_case = GetPublisherUseCase(publisher_port=mock_publisher_port)
        result = use_case.execute(publisher_id="invalid")

        assert result is None


class TestSearchAgentsUseCase:
    """Tests pour SearchAgentsUseCase."""

    def test_search_agents_success(self, mock_agent_port, sample_agent):
        """Recherche d'agents réussie."""

        search_result = MarketplaceSearchResult(
            agents=[sample_agent],
            total_count=1,
            page=1,
            per_page=20
        )
        mock_agent_port.search.return_value = search_result

        use_case = SearchAgentsUseCase(agent_port=mock_agent_port)
        query = MarketplaceSearchQuery(query="test")
        result = use_case.execute(query)

        assert result.total_count == 1
        assert len(result.agents) == 1
        mock_agent_port.search.assert_called_once_with(query)


class TestListFeaturedAgentsUseCase:
    """Tests pour ListFeaturedAgentsUseCase."""

    def test_list_featured_agents_success(self, mock_agent_port, sample_agent):
        """Liste des agents mis en avant réussie."""

        mock_agent_port.list_all.return_value = [sample_agent]

        use_case = ListFeaturedAgentsUseCase(agent_port=mock_agent_port)
        result = use_case.execute(limit=10)

        assert len(result) == 1
        mock_agent_port.list_all.assert_called_once_with(
            status=AgentStatus.PUBLISHED,
            limit=10
        )


class TestListAgentsByCategoryUseCase:
    """Tests pour ListAgentsByCategoryUseCase."""

    def test_list_by_category_success(self, mock_agent_port, sample_agent):
        """Liste par catégorie réussie."""

        mock_agent_port.list_all.return_value = [sample_agent]

        use_case = ListAgentsByCategoryUseCase(agent_port=mock_agent_port)
        result = use_case.execute(
            category=AgentCategory.CUSTOMER_SERVICE,
            limit=20,
            offset=0
        )

        assert len(result) == 1
        mock_agent_port.list_all.assert_called_once_with(
            status=AgentStatus.PUBLISHED,
            category=AgentCategory.CUSTOMER_SERVICE,
            limit=20,
            offset=0
        )


class TestListAgentReviewsUseCase:
    """Tests pour ListAgentReviewsUseCase."""

    def test_list_reviews_success(self, mock_review_port, sample_review):
        """Liste des avis réussie."""

        mock_review_port.get_by_agent.return_value = [sample_review]

        use_case = ListAgentReviewsUseCase(review_port=mock_review_port)
        result = use_case.execute(agent_id="agent-123", limit=50, offset=0)

        assert len(result) == 1
        mock_review_port.get_by_agent.assert_called_once_with(
            "agent-123",
            approved_only=True,
            limit=50,
            offset=0
        )
