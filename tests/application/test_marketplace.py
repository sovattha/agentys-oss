# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour les use cases de la Marketplace d'agents IA.

Couvre:
- RegisterPublisherUseCase : Enregistrement des éditeurs
- GetPublisherUseCase : Récupération des éditeurs
- PublishAgentUseCase : Publication d'agents
- SubmitAgentForReviewUseCase : Soumission en révision
- ApproveAgentUseCase : Approbation et publication
- UpdateAgentUseCase : Mise à jour d'agents
- SearchAgentsUseCase : Recherche d'agents
- GetAgentDetailsUseCase : Détails complets d'un agent
- ListFeaturedAgentsUseCase : Listing des agents phares
- ListAgentsByCategoryUseCase : Listing par catégorie
- InstallAgentUseCase : Installation d'agents
- UninstallAgentUseCase : Désinstallation
- ListInstalledAgentsUseCase : Listing des installations
- RecordAgentUsageUseCase : Enregistrement d'usage
- SubmitReviewUseCase : Soumission d'avis
- RespondToReviewUseCase : Réponse aux avis
- ListAgentReviewsUseCase : Listing des avis
- CreateAgentPackUseCase : Création de packs
- InstallPackUseCase : Installation de packs
"""

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timedelta

from app.application.marketplace import (
    RegisterPublisherUseCase,
    GetPublisherUseCase,
    PublishAgentUseCase,
    SubmitAgentForReviewUseCase,
    ApproveAgentUseCase,
    UpdateAgentUseCase,
    SearchAgentsUseCase,
    GetAgentDetailsUseCase,
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
from app.domain.entities.marketplace import (
    Publisher,
    MarketplaceAgent,
    AgentPack,
    AgentInstallation,
    AgentReview,
    AgentCategory,
    AgentStatus,
    InstallationStatus,
    AgentPricing,
    AgentPricingModel,
    MarketplaceSearchQuery,
    MarketplaceSearchResult,
)


# =============================================================================
# PUBLISHER USE CASES TESTS
# =============================================================================

class TestRegisterPublisherUseCase:
    """Tests pour RegisterPublisherUseCase."""

    def test_register_publisher_success(self):
        """L'enregistrement d'un éditeur valide réussit."""
        publisher_port = MagicMock()
        publisher_port.get_by_email.return_value = None

        expected_publisher = Publisher(
            id="pub-123",
            name="Test Publisher",
            email="test@example.com",
            description="A test publisher"
        )
        publisher_port.save.return_value = expected_publisher

        use_case = RegisterPublisherUseCase(publisher_port)
        result = use_case.execute(
            name="Test Publisher",
            email="test@example.com",
            description="A test publisher"
        )

        assert result.id == "pub-123"
        assert result.name == "Test Publisher"
        assert result.email == "test@example.com"
        publisher_port.get_by_email.assert_called_once_with("test@example.com")
        publisher_port.save.assert_called_once()

    def test_register_publisher_with_website(self):
        """L'enregistrement d'un éditeur avec site web réussit."""
        publisher_port = MagicMock()
        publisher_port.get_by_email.return_value = None

        expected_publisher = Publisher(
            id="pub-456",
            name="Professional Publisher",
            email="pro@example.com",
            website="https://example.com",
            description="Professional publisher"
        )
        publisher_port.save.return_value = expected_publisher

        use_case = RegisterPublisherUseCase(publisher_port)
        result = use_case.execute(
            name="Professional Publisher",
            email="pro@example.com",
            website="https://example.com",
            description="Professional publisher"
        )

        assert result.website == "https://example.com"

    def test_register_publisher_duplicate_email_raises_error(self):
        """L'enregistrement avec un email déjà utilisé échoue."""
        publisher_port = MagicMock()
        existing_publisher = Publisher(
            id="pub-existing",
            name="Existing",
            email="test@example.com"
        )
        publisher_port.get_by_email.return_value = existing_publisher

        use_case = RegisterPublisherUseCase(publisher_port)

        with pytest.raises(ValueError, match="Un éditeur avec l'email"):
            use_case.execute(
                name="New Publisher",
                email="test@example.com"
            )

    def test_register_publisher_empty_name_raises_error(self):
        """L'enregistrement sans nom échoue."""
        publisher_port = MagicMock()
        use_case = RegisterPublisherUseCase(publisher_port)

        with pytest.raises(ValueError, match="Le nom est requis"):
            use_case.execute(name="", email="test@example.com")

    def test_register_publisher_empty_email_raises_error(self):
        """L'enregistrement sans email échoue."""
        publisher_port = MagicMock()
        use_case = RegisterPublisherUseCase(publisher_port)

        with pytest.raises(ValueError, match="L'email est requis"):
            use_case.execute(name="Test", email="")

    def test_register_publisher_invalid_email_raises_error(self):
        """L'enregistrement avec email invalide échoue."""
        publisher_port = MagicMock()
        use_case = RegisterPublisherUseCase(publisher_port)

        with pytest.raises(ValueError, match="Format d'email invalide"):
            use_case.execute(name="Test", email="not-an-email")

    def test_register_publisher_whitespace_name_raises_error(self):
        """L'enregistrement avec nom vide (espaces) échoue."""
        publisher_port = MagicMock()
        use_case = RegisterPublisherUseCase(publisher_port)

        with pytest.raises(ValueError, match="Le nom est requis"):
            use_case.execute(name="   ", email="test@example.com")


class TestGetPublisherUseCase:
    """Tests pour GetPublisherUseCase."""

    def test_get_publisher_by_id_success(self):
        """La récupération d'un éditeur existant réussit."""
        publisher_port = MagicMock()
        expected_publisher = Publisher(
            id="pub-123",
            name="Test Publisher",
            email="test@example.com"
        )
        publisher_port.get_by_id.return_value = expected_publisher

        use_case = GetPublisherUseCase(publisher_port)
        result = use_case.execute("pub-123")

        assert result.id == "pub-123"
        assert result.name == "Test Publisher"
        publisher_port.get_by_id.assert_called_once_with("pub-123")

    def test_get_publisher_not_found(self):
        """La récupération d'un éditeur inexistant retourne None."""
        publisher_port = MagicMock()
        publisher_port.get_by_id.return_value = None

        use_case = GetPublisherUseCase(publisher_port)
        result = use_case.execute("non-existent-id")

        assert result is None

    def test_get_publisher_multiple_calls(self):
        """Plusieurs appels pour différents éditeurs fonctionnent."""
        publisher_port = MagicMock()
        pub1 = Publisher(id="pub-1", name="Publisher 1", email="pub1@example.com")
        pub2 = Publisher(id="pub-2", name="Publisher 2", email="pub2@example.com")

        publisher_port.get_by_id.side_effect = [pub1, pub2, None]

        use_case = GetPublisherUseCase(publisher_port)

        result1 = use_case.execute("pub-1")
        result2 = use_case.execute("pub-2")
        result3 = use_case.execute("non-existent")

        assert result1.id == "pub-1"
        assert result2.id == "pub-2"
        assert result3 is None
        assert publisher_port.get_by_id.call_count == 3


# =============================================================================
# AGENT PUBLICATION USE CASES TESTS
# =============================================================================

class TestPublishAgentUseCase:
    """Tests pour PublishAgentUseCase."""

    def test_publish_agent_success(self):
        """La publication d'un agent valide réussit."""
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(
            id="pub-123",
            name="Test Publisher",
            email="test@example.com"
        )
        publisher_port.get_by_id.return_value = publisher

        saved_agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            slug="test-agent",
            description="A test agent",
            system_prompt="You are a test agent",
            publisher_id="pub-123",
            status=AgentStatus.DRAFT
        )
        agent_port.save.return_value = saved_agent

        use_case = PublishAgentUseCase(agent_port, publisher_port)
        result = use_case.execute(
            publisher_id="pub-123",
            name="Test Agent",
            description="A test agent",
            category=AgentCategory.CUSTOM,
            system_prompt="You are a test agent",
            capabilities=[]
        )

        assert result.id == "agent-123"
        assert result.status == AgentStatus.DRAFT
        assert result.slug == "test-agent"
        agent_port.save.assert_called_once()
        publisher_port.update.assert_called_once()

    def test_publish_agent_with_full_data(self):
        """La publication avec tous les champs optionnels réussit."""
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(id="pub-123", name="Test", email="test@example.com")
        publisher_port.get_by_id.return_value = publisher

        saved_agent = MarketplaceAgent(
            id="agent-456",
            name="Full Agent",
            description="Full description",
            category=AgentCategory.SALES
        )
        agent_port.save.return_value = saved_agent

        use_case = PublishAgentUseCase(agent_port, publisher_port)
        result = use_case.execute(
            publisher_id="pub-123",
            name="Full Agent",
            description="Full description",
            category=AgentCategory.SALES,
            system_prompt="Prompt",
            capabilities=[{"name": "cap1", "description": "desc1"}],
            tags=["tag1", "tag2"],
            long_description="Long description",
            knowledge_base_template="KB template",
            pricing=AgentPricing(model=AgentPricingModel.SUBSCRIPTION)
        )

        assert result.id == "agent-456"

    def test_publish_agent_nonexistent_publisher_raises_error(self):
        """La publication avec un éditeur inexistant échoue."""
        agent_port = MagicMock()
        publisher_port = MagicMock()
        publisher_port.get_by_id.return_value = None

        use_case = PublishAgentUseCase(agent_port, publisher_port)

        with pytest.raises(ValueError, match="Éditeur .* non trouvé"):
            use_case.execute(
                publisher_id="non-existent",
                name="Test",
                description="Test description",
                category=AgentCategory.CUSTOM,
                system_prompt="Prompt",
                capabilities=[]
            )

    def test_publish_agent_short_name_raises_error(self):
        """La publication avec un nom trop court échoue."""
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(id="pub-123", name="Test", email="test@example.com")
        publisher_port.get_by_id.return_value = publisher

        use_case = PublishAgentUseCase(agent_port, publisher_port)

        with pytest.raises(ValueError, match="Le nom doit faire au moins 3 caractères"):
            use_case.execute(
                publisher_id="pub-123",
                name="AB",
                description="Valid description",
                category=AgentCategory.CUSTOM,
                system_prompt="Prompt",
                capabilities=[]
            )

    def test_publish_agent_short_description_raises_error(self):
        """La publication avec description trop courte échoue."""
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(id="pub-123", name="Test", email="test@example.com")
        publisher_port.get_by_id.return_value = publisher

        use_case = PublishAgentUseCase(agent_port, publisher_port)

        with pytest.raises(ValueError, match="La description doit faire au moins 10 caractères"):
            use_case.execute(
                publisher_id="pub-123",
                name="Valid Name",
                description="Short",
                category=AgentCategory.CUSTOM,
                system_prompt="Prompt",
                capabilities=[]
            )

    def test_publish_agent_empty_system_prompt_raises_error(self):
        """La publication sans prompt système échoue."""
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(id="pub-123", name="Test", email="test@example.com")
        publisher_port.get_by_id.return_value = publisher

        use_case = PublishAgentUseCase(agent_port, publisher_port)

        with pytest.raises(ValueError, match="Le prompt système est requis"):
            use_case.execute(
                publisher_id="pub-123",
                name="Valid Name",
                description="Valid description",
                category=AgentCategory.CUSTOM,
                system_prompt="",
                capabilities=[]
            )

    def test_publish_agent_slug_generation(self):
        """Le slug est généré correctement à partir du nom."""
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(id="pub-123", name="Test", email="test@example.com")
        publisher_port.get_by_id.return_value = publisher

        saved_agent = MarketplaceAgent(
            id="agent-789",
            name="My Awesome Agent!!!",
            slug="my-awesome-agent",
            description="Test description",
            system_prompt="Prompt",
            publisher_id="pub-123",
            status=AgentStatus.DRAFT
        )
        agent_port.save.return_value = saved_agent

        use_case = PublishAgentUseCase(agent_port, publisher_port)
        use_case.execute(
            publisher_id="pub-123",
            name="My Awesome Agent!!!",
            description="Test description",
            category=AgentCategory.CUSTOM,
            system_prompt="Prompt",
            capabilities=[]
        )

        # Verify the saved agent has correct slug
        saved_call = agent_port.save.call_args[0][0]
        assert saved_call.slug == "my-awesome-agent"

    def test_publish_agent_increments_publisher_count(self):
        """La publication incrémente le compteur d'agents de l'éditeur."""
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(
            id="pub-123",
            name="Test",
            email="test@example.com",
            agent_count=5
        )
        publisher_port.get_by_id.return_value = publisher

        saved_agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            slug="test-agent",
            description="Test description",
            system_prompt="Prompt",
            publisher_id="pub-123",
            status=AgentStatus.DRAFT
        )
        agent_port.save.return_value = saved_agent

        use_case = PublishAgentUseCase(agent_port, publisher_port)
        use_case.execute(
            publisher_id="pub-123",
            name="Test Agent",
            description="Test description",
            category=AgentCategory.CUSTOM,
            system_prompt="Prompt",
            capabilities=[]
        )

        # Verify publisher was updated with incremented count
        updated_publisher = publisher_port.update.call_args[0][0]
        assert updated_publisher.agent_count == 6


class TestSubmitAgentForReviewUseCase:
    """Tests pour SubmitAgentForReviewUseCase."""

    def test_submit_agent_for_review_success(self):
        """La soumission d'un agent en révision réussit."""
        agent_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            status=AgentStatus.DRAFT,
            publisher_id="pub-123"
        )

        updated_agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            status=AgentStatus.PENDING_REVIEW,
            publisher_id="pub-123"
        )

        agent_port.get_by_id.return_value = agent
        agent_port.update.return_value = updated_agent

        use_case = SubmitAgentForReviewUseCase(agent_port)
        result = use_case.execute("agent-123", "pub-123")

        assert result.status == AgentStatus.PENDING_REVIEW
        agent_port.update.assert_called_once()

    def test_submit_nonexistent_agent_raises_error(self):
        """La soumission d'un agent inexistant échoue."""
        agent_port = MagicMock()
        agent_port.get_by_id.return_value = None

        use_case = SubmitAgentForReviewUseCase(agent_port)

        with pytest.raises(ValueError, match="Agent .* non trouvé"):
            use_case.execute("non-existent", "pub-123")

    def test_submit_agent_not_owned_raises_error(self):
        """La soumission d'un agent non propriétaire échoue."""
        agent_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test",
            status=AgentStatus.DRAFT,
            publisher_id="pub-123"
        )
        agent_port.get_by_id.return_value = agent

        use_case = SubmitAgentForReviewUseCase(agent_port)

        with pytest.raises(ValueError, match="ne vous appartient pas"):
            use_case.execute("agent-123", "pub-different")

    def test_submit_agent_not_draft_raises_error(self):
        """La soumission d'un agent non-DRAFT échoue."""
        agent_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test",
            status=AgentStatus.PUBLISHED,
            publisher_id="pub-123"
        )
        agent_port.get_by_id.return_value = agent

        use_case = SubmitAgentForReviewUseCase(agent_port)

        with pytest.raises(ValueError, match="L'agent doit être en statut DRAFT"):
            use_case.execute("agent-123", "pub-123")


class TestApproveAgentUseCase:
    """Tests pour ApproveAgentUseCase."""

    def test_approve_agent_success(self):
        """L'approbation d'un agent réussit."""
        agent_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            status=AgentStatus.PENDING_REVIEW,
            publisher_id="pub-123"
        )

        updated_agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            status=AgentStatus.PUBLISHED,
            publisher_id="pub-123",
            published_at=datetime.now()
        )

        agent_port.get_by_id.return_value = agent
        agent_port.update.return_value = updated_agent

        use_case = ApproveAgentUseCase(agent_port)
        result = use_case.execute("agent-123")

        assert result.status == AgentStatus.PUBLISHED
        assert result.published_at is not None
        agent_port.update.assert_called_once()

    def test_approve_nonexistent_agent_raises_error(self):
        """L'approbation d'un agent inexistant échoue."""
        agent_port = MagicMock()
        agent_port.get_by_id.return_value = None

        use_case = ApproveAgentUseCase(agent_port)

        with pytest.raises(ValueError, match="Agent .* non trouvé"):
            use_case.execute("non-existent")

    def test_approve_agent_not_pending_raises_error(self):
        """L'approbation d'un agent non-PENDING_REVIEW échoue."""
        agent_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test",
            status=AgentStatus.DRAFT,
            publisher_id="pub-123"
        )
        agent_port.get_by_id.return_value = agent

        use_case = ApproveAgentUseCase(agent_port)

        with pytest.raises(ValueError, match="L'agent doit être en PENDING_REVIEW"):
            use_case.execute("agent-123")


class TestUpdateAgentUseCase:
    """Tests pour UpdateAgentUseCase."""

    def test_update_agent_description_success(self):
        """La mise à jour de la description réussit."""
        agent_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            description="Old description",
            status=AgentStatus.DRAFT,
            publisher_id="pub-123"
        )

        updated_agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            description="New description",
            status=AgentStatus.DRAFT,
            publisher_id="pub-123"
        )

        agent_port.get_by_id.return_value = agent
        agent_port.update.return_value = updated_agent

        use_case = UpdateAgentUseCase(agent_port)
        result = use_case.execute(
            "agent-123",
            "pub-123",
            description="New description"
        )

        assert result.description == "New description"

    def test_update_agent_name_regenerates_slug(self):
        """La mise à jour du nom régénère le slug."""
        agent_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Old Name",
            slug="old-name",
            status=AgentStatus.DRAFT,
            publisher_id="pub-123"
        )

        agent_port.get_by_id.return_value = agent
        agent_port.update.return_value = agent

        use_case = UpdateAgentUseCase(agent_port)
        use_case.execute(
            "agent-123",
            "pub-123",
            name="New Name"
        )

        # Verify the call updated the agent with new name
        updated_agent = agent_port.update.call_args[0][0]
        assert updated_agent.slug == "new-name"

    def test_update_agent_increments_version_when_published(self):
        """La mise à jour d'un agent publié incrémente la version."""
        agent_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            version="1.2.3",
            status=AgentStatus.PUBLISHED,
            publisher_id="pub-123"
        )

        agent_port.get_by_id.return_value = agent
        agent_port.update.return_value = agent

        use_case = UpdateAgentUseCase(agent_port)
        use_case.execute(
            "agent-123",
            "pub-123",
            description="Updated description"
        )

        updated_agent = agent_port.update.call_args[0][0]
        assert updated_agent.version == "1.2.4"

    def test_update_nonexistent_agent_raises_error(self):
        """La mise à jour d'un agent inexistant échoue."""
        agent_port = MagicMock()
        agent_port.get_by_id.return_value = None

        use_case = UpdateAgentUseCase(agent_port)

        with pytest.raises(ValueError, match="Agent .* non trouvé"):
            use_case.execute("non-existent", "pub-123", description="Test")

    def test_update_agent_not_owned_raises_error(self):
        """La mise à jour d'un agent non propriétaire échoue."""
        agent_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test",
            status=AgentStatus.DRAFT,
            publisher_id="pub-123"
        )
        agent_port.get_by_id.return_value = agent

        use_case = UpdateAgentUseCase(agent_port)

        with pytest.raises(ValueError, match="ne vous appartient pas"):
            use_case.execute("agent-123", "pub-different", description="Test")

    def test_update_agent_allows_only_permitted_fields(self):
        """Seuls les champs autorisés peuvent être mis à jour."""
        agent_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test",
            status=AgentStatus.DRAFT,
            publisher_id="pub-123",
            active_installations=0
        )

        agent_port.get_by_id.return_value = agent
        agent_port.update.return_value = agent

        use_case = UpdateAgentUseCase(agent_port)
        # Try to update a non-allowed field
        use_case.execute(
            "agent-123",
            "pub-123",
            active_installations=999  # Not in allowed_fields
        )

        updated_agent = agent_port.update.call_args[0][0]
        # active_installations should not be changed
        assert updated_agent.active_installations == 0


# =============================================================================
# SEARCH AND LISTING USE CASES TESTS
# =============================================================================

class TestSearchAgentsUseCase:
    """Tests pour SearchAgentsUseCase."""

    def test_search_agents_success(self):
        """La recherche d'agents réussit."""
        agent_port = MagicMock()

        query = MarketplaceSearchQuery(
            query="email",
            category=AgentCategory.CUSTOMER_SERVICE
        )

        agents = [
            MarketplaceAgent(id="1", name="Email Handler", status=AgentStatus.PUBLISHED),
            MarketplaceAgent(id="2", name="Email Analyst", status=AgentStatus.PUBLISHED)
        ]

        result = MarketplaceSearchResult(agents=agents, total_count=2)
        agent_port.search.return_value = result

        use_case = SearchAgentsUseCase(agent_port)
        result = use_case.execute(query)

        assert len(result.agents) == 2
        assert result.total_count == 2
        agent_port.search.assert_called_once_with(query)

    def test_search_agents_empty_result(self):
        """Une recherche sans résultats retourne une liste vide."""
        agent_port = MagicMock()

        query = MarketplaceSearchQuery(query="nonexistent")
        result = MarketplaceSearchResult(agents=[], total_count=0)
        agent_port.search.return_value = result

        use_case = SearchAgentsUseCase(agent_port)
        result = use_case.execute(query)

        assert len(result.agents) == 0
        assert result.total_count == 0


class TestGetAgentDetailsUseCase:
    """Tests pour GetAgentDetailsUseCase."""

    def test_get_agent_details_success(self):
        """Récupérer les détails d'un agent réussit."""
        agent_port = MagicMock()
        review_port = MagicMock()
        installation_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            status=AgentStatus.PUBLISHED
        )

        reviews = [
            AgentReview(id="r1", agent_id="agent-123", rating=5, title="Great!"),
            AgentReview(id="r2", agent_id="agent-123", rating=4, title="Good")
        ]

        agent_port.get_by_id.return_value = agent
        review_port.get_by_agent.return_value = reviews
        installation_port.count_active_by_agent.return_value = 42
        review_port.calculate_average_rating.return_value = 4.5
        review_port.count_reviews.return_value = 2

        use_case = GetAgentDetailsUseCase(agent_port, review_port, installation_port)
        result = use_case.execute("agent-123")

        assert result is not None
        assert result["agent"].id == "agent-123"
        assert len(result["reviews"]) == 2
        assert result["active_installations"] == 42
        assert result["average_rating"] == 4.5
        assert result["review_count"] == 2

    def test_get_agent_details_nonexistent_returns_none(self):
        """Récupérer les détails d'un agent inexistant retourne None."""
        agent_port = MagicMock()
        review_port = MagicMock()
        installation_port = MagicMock()

        agent_port.get_by_id.return_value = None

        use_case = GetAgentDetailsUseCase(agent_port, review_port, installation_port)
        result = use_case.execute("non-existent")

        assert result is None


class TestListFeaturedAgentsUseCase:
    """Tests pour ListFeaturedAgentsUseCase."""

    def test_list_featured_agents_success(self):
        """Le listing des agents phares réussit."""
        agent_port = MagicMock()

        featured = [
            MarketplaceAgent(id="1", name="Popular Agent 1", status=AgentStatus.PUBLISHED),
            MarketplaceAgent(id="2", name="Popular Agent 2", status=AgentStatus.PUBLISHED)
        ]

        agent_port.list_all.return_value = featured

        use_case = ListFeaturedAgentsUseCase(agent_port)
        result = use_case.execute(limit=10)

        assert len(result) == 2
        agent_port.list_all.assert_called_once()
        call_args = agent_port.list_all.call_args
        assert call_args[1]["status"] == AgentStatus.PUBLISHED

    def test_list_featured_agents_respects_limit(self):
        """Le listing respecte la limite."""
        agent_port = MagicMock()
        agent_port.list_all.return_value = []

        use_case = ListFeaturedAgentsUseCase(agent_port)
        use_case.execute(limit=25)

        call_args = agent_port.list_all.call_args
        assert call_args[1]["limit"] == 25


class TestListAgentsByCategoryUseCase:
    """Tests pour ListAgentsByCategoryUseCase."""

    def test_list_agents_by_category_success(self):
        """Le listing par catégorie réussit."""
        agent_port = MagicMock()

        agents = [
            MarketplaceAgent(
                id="1",
                name="Sales Agent 1",
                category=AgentCategory.SALES,
                status=AgentStatus.PUBLISHED
            ),
            MarketplaceAgent(
                id="2",
                name="Sales Agent 2",
                category=AgentCategory.SALES,
                status=AgentStatus.PUBLISHED
            )
        ]

        agent_port.list_all.return_value = agents

        use_case = ListAgentsByCategoryUseCase(agent_port)
        result = use_case.execute(category=AgentCategory.SALES, limit=20, offset=0)

        assert len(result) == 2
        agent_port.list_all.assert_called_once()
        call_args = agent_port.list_all.call_args
        assert call_args[1]["category"] == AgentCategory.SALES
        assert call_args[1]["status"] == AgentStatus.PUBLISHED

    def test_list_agents_by_category_with_pagination(self):
        """Le listing par catégorie supporte la pagination."""
        agent_port = MagicMock()
        agent_port.list_all.return_value = []

        use_case = ListAgentsByCategoryUseCase(agent_port)
        use_case.execute(
            category=AgentCategory.MARKETING,
            limit=50,
            offset=100
        )

        call_args = agent_port.list_all.call_args
        assert call_args[1]["limit"] == 50
        assert call_args[1]["offset"] == 100


# =============================================================================
# INSTALLATION USE CASES TESTS
# =============================================================================

class TestInstallAgentUseCase:
    """Tests pour InstallAgentUseCase."""

    def test_install_agent_success(self):
        """L'installation d'un agent réussit."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            version="1.0.0",
            status=AgentStatus.PUBLISHED,
            active_installations=0,
            pricing=AgentPricing(model=AgentPricingModel.FREE)
        )

        installation = AgentInstallation(
            id="install-123",
            agent_id="agent-123",
            organization_id="org-123",
            installed_version="1.0.0",
            status=InstallationStatus.ACTIVE
        )

        agent_port.get_by_id.return_value = agent
        installation_port.find_installation.return_value = None
        installation_port.save.return_value = installation

        use_case = InstallAgentUseCase(agent_port, installation_port)
        result = use_case.execute("agent-123", "org-123")

        assert result.id == "install-123"
        assert result.status == InstallationStatus.ACTIVE
        installation_port.save.assert_called_once()
        agent_port.increment_download_count.assert_called_once_with("agent-123")

    def test_install_agent_with_subscription_expires(self):
        """L'installation d'un agent d'abonnement fixe une date d'expiration."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Subscription Agent",
            version="1.0.0",
            status=AgentStatus.PUBLISHED,
            active_installations=0,
            pricing=AgentPricing(
                model=AgentPricingModel.SUBSCRIPTION,
                billing_period_days=30
            )
        )

        installation = AgentInstallation(
            id="install-123",
            agent_id="agent-123",
            organization_id="org-123",
            installed_version="1.0.0",
            status=InstallationStatus.ACTIVE,
            expires_at=datetime.now() + timedelta(days=30)
        )

        agent_port.get_by_id.return_value = agent
        installation_port.find_installation.return_value = None
        installation_port.save.return_value = installation

        use_case = InstallAgentUseCase(agent_port, installation_port)
        result = use_case.execute("agent-123", "org-123")

        assert result.expires_at is not None

    def test_install_agent_with_trial_expires(self):
        """L'installation avec trial fixe une date d'expiration."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Trial Agent",
            version="1.0.0",
            status=AgentStatus.PUBLISHED,
            active_installations=0,
            pricing=AgentPricing(model=AgentPricingModel.FREE, trial_days=14)
        )

        installation = AgentInstallation(
            id="install-123",
            agent_id="agent-123",
            organization_id="org-123",
            expires_at=datetime.now() + timedelta(days=14)
        )

        agent_port.get_by_id.return_value = agent
        installation_port.find_installation.return_value = None
        installation_port.save.return_value = installation

        use_case = InstallAgentUseCase(agent_port, installation_port)
        result = use_case.execute("agent-123", "org-123")

        assert result.expires_at is not None

    def test_install_nonexistent_agent_raises_error(self):
        """L'installation d'un agent inexistant échoue."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        agent_port.get_by_id.return_value = None

        use_case = InstallAgentUseCase(agent_port, installation_port)

        with pytest.raises(ValueError, match="Agent .* non trouvé"):
            use_case.execute("non-existent", "org-123")

    def test_install_unpublished_agent_raises_error(self):
        """L'installation d'un agent non publié échoue."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Draft Agent",
            status=AgentStatus.DRAFT
        )
        agent_port.get_by_id.return_value = agent

        use_case = InstallAgentUseCase(agent_port, installation_port)

        with pytest.raises(ValueError, match="n'est pas disponible à l'installation"):
            use_case.execute("agent-123", "org-123")

    def test_install_already_installed_agent_raises_error(self):
        """L'installation d'un agent déjà installé échoue."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            status=AgentStatus.PUBLISHED,
            pricing=AgentPricing(model=AgentPricingModel.FREE)
        )

        existing_installation = AgentInstallation(
            id="install-existing",
            agent_id="agent-123",
            organization_id="org-123",
            status=InstallationStatus.ACTIVE
        )

        agent_port.get_by_id.return_value = agent
        installation_port.find_installation.return_value = existing_installation

        use_case = InstallAgentUseCase(agent_port, installation_port)

        with pytest.raises(ValueError, match="déjà installé"):
            use_case.execute("agent-123", "org-123")

    def test_install_agent_with_custom_settings(self):
        """L'installation avec paramètres personnalisés réussit."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        agent = MarketplaceAgent(
            id="agent-123",
            name="Configurable Agent",
            version="1.0.0",
            status=AgentStatus.PUBLISHED,
            active_installations=0,
            pricing=AgentPricing(model=AgentPricingModel.FREE)
        )

        custom_settings = {"tone": "friendly", "language": "en"}

        installation = AgentInstallation(
            id="install-123",
            agent_id="agent-123",
            organization_id="org-123",
            custom_settings=custom_settings,
            status=InstallationStatus.ACTIVE
        )

        agent_port.get_by_id.return_value = agent
        installation_port.find_installation.return_value = None
        installation_port.save.return_value = installation

        use_case = InstallAgentUseCase(agent_port, installation_port)
        use_case.execute(
            "agent-123",
            "org-123",
            custom_settings=custom_settings
        )

        # Verify custom settings were saved
        saved_installation = installation_port.save.call_args[0][0]
        assert saved_installation.custom_settings == custom_settings


class TestUninstallAgentUseCase:
    """Tests pour UninstallAgentUseCase."""

    def test_uninstall_agent_success(self):
        """La désinstallation d'un agent réussit."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        installation = AgentInstallation(
            id="install-123",
            agent_id="agent-123",
            organization_id="org-123",
            status=InstallationStatus.ACTIVE
        )

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            active_installations=5
        )

        installation_port.get_by_id.return_value = installation
        agent_port.get_by_id.return_value = agent

        use_case = UninstallAgentUseCase(agent_port, installation_port)
        result = use_case.execute("install-123", "org-123")

        assert result is True
        installation_port.update.assert_called_once()
        updated_installation = installation_port.update.call_args[0][0]
        assert updated_installation.status == InstallationStatus.UNINSTALLED

    def test_uninstall_nonexistent_installation_raises_error(self):
        """La désinstallation d'une installation inexistante échoue."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        installation_port.get_by_id.return_value = None

        use_case = UninstallAgentUseCase(agent_port, installation_port)

        with pytest.raises(ValueError, match="Installation .* non trouvée"):
            use_case.execute("non-existent", "org-123")

    def test_uninstall_installation_not_owned_raises_error(self):
        """La désinstallation d'une installation non propriétaire échoue."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        installation = AgentInstallation(
            id="install-123",
            agent_id="agent-123",
            organization_id="org-123"
        )

        installation_port.get_by_id.return_value = installation

        use_case = UninstallAgentUseCase(agent_port, installation_port)

        with pytest.raises(ValueError, match="ne vous appartient pas"):
            use_case.execute("install-123", "org-different")

    def test_uninstall_agent_decrements_count(self):
        """La désinstallation décrémente le compteur d'installations actives."""
        agent_port = MagicMock()
        installation_port = MagicMock()

        installation = AgentInstallation(
            id="install-123",
            agent_id="agent-123",
            organization_id="org-123",
            status=InstallationStatus.ACTIVE
        )

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            active_installations=5
        )

        installation_port.get_by_id.return_value = installation
        agent_port.get_by_id.return_value = agent

        use_case = UninstallAgentUseCase(agent_port, installation_port)
        use_case.execute("install-123", "org-123")

        updated_agent = agent_port.update.call_args[0][0]
        assert updated_agent.active_installations == 4


class TestListInstalledAgentsUseCase:
    """Tests pour ListInstalledAgentsUseCase."""

    def test_list_installed_agents_success(self):
        """Le listing des agents installés réussit."""
        installation_port = MagicMock()
        agent_port = MagicMock()

        installations = [
            AgentInstallation(id="i1", agent_id="a1", organization_id="org-123"),
            AgentInstallation(id="i2", agent_id="a2", organization_id="org-123")
        ]

        agents = [
            MarketplaceAgent(id="a1", name="Agent 1"),
            MarketplaceAgent(id="a2", name="Agent 2")
        ]

        installation_port.get_by_organization.return_value = installations
        agent_port.get_by_id.side_effect = agents

        use_case = ListInstalledAgentsUseCase(installation_port, agent_port)
        result = use_case.execute("org-123", active_only=True)

        assert len(result) == 2
        assert result[0]["agent"].id == "a1"
        assert result[1]["agent"].id == "a2"

    def test_list_installed_agents_respects_active_only(self):
        """Le listing respecte le filtre active_only."""
        installation_port = MagicMock()
        agent_port = MagicMock()

        installation_port.get_by_organization.return_value = []

        use_case = ListInstalledAgentsUseCase(installation_port, agent_port)
        use_case.execute("org-123", active_only=False)

        call_args = installation_port.get_by_organization.call_args
        assert call_args[1]["active_only"] is False


class TestRecordAgentUsageUseCase:
    """Tests pour RecordAgentUsageUseCase."""

    def test_record_usage_success(self):
        """L'enregistrement d'usage réussit."""
        installation_port = MagicMock()

        installation = AgentInstallation(
            id="install-123",
            agent_id="agent-123",
            organization_id="org-123",
            usage_count=5,
            status=InstallationStatus.ACTIVE
        )

        updated_installation = AgentInstallation(
            id="install-123",
            agent_id="agent-123",
            organization_id="org-123",
            usage_count=6,
            status=InstallationStatus.ACTIVE,
            last_used_at=datetime.now()
        )

        installation_port.get_by_id.return_value = installation
        installation_port.update.return_value = updated_installation

        use_case = RecordAgentUsageUseCase(installation_port)
        result = use_case.execute("install-123")

        assert result.usage_count == 6
        assert result.last_used_at is not None

    def test_record_usage_nonexistent_installation_raises_error(self):
        """L'enregistrement sur une installation inexistante échoue."""
        installation_port = MagicMock()
        installation_port.get_by_id.return_value = None

        use_case = RecordAgentUsageUseCase(installation_port)

        with pytest.raises(ValueError, match="Installation .* non trouvée"):
            use_case.execute("non-existent")

    def test_record_usage_inactive_installation_raises_error(self):
        """L'enregistrement sur une installation inactive échoue."""
        installation_port = MagicMock()

        installation = AgentInstallation(
            id="install-123",
            status=InstallationStatus.EXPIRED
        )

        installation_port.get_by_id.return_value = installation

        use_case = RecordAgentUsageUseCase(installation_port)

        with pytest.raises(ValueError, match="n'est pas active"):
            use_case.execute("install-123")


# =============================================================================
# REVIEW USE CASES TESTS
# =============================================================================

class TestSubmitReviewUseCase:
    """Tests pour SubmitReviewUseCase."""

    def test_submit_review_success(self):
        """La soumission d'un avis réussit."""
        review_port = MagicMock()
        installation_port = MagicMock()
        agent_port = MagicMock()

        installation = AgentInstallation(
            id="install-123",
            agent_id="agent-123",
            organization_id="org-123"
        )

        agent = MarketplaceAgent(id="agent-123", name="Test Agent")

        review = AgentReview(
            id="review-123",
            agent_id="agent-123",
            organization_id="org-123",
            reviewer_name="John Doe",
            rating=5,
            title="Great Agent!",
            content="This agent is amazing and works perfectly.",
            is_verified_purchase=True,
            is_approved=True
        )

        installation_port.find_installation.return_value = installation
        review_port.save.return_value = review
        agent_port.get_by_id.return_value = agent
        review_port.count_reviews.return_value = 1
        review_port.calculate_average_rating.return_value = 5.0

        use_case = SubmitReviewUseCase(review_port, installation_port, agent_port)
        result = use_case.execute(
            agent_id="agent-123",
            organization_id="org-123",
            reviewer_name="John Doe",
            rating=5,
            title="Great Agent!",
            content="This agent is amazing and works perfectly."
        )

        assert result.id == "review-123"
        assert result.is_verified_purchase is True

    def test_submit_review_invalid_rating_raises_error(self):
        """La soumission avec rating invalide échoue."""
        review_port = MagicMock()
        installation_port = MagicMock()
        agent_port = MagicMock()

        use_case = SubmitReviewUseCase(review_port, installation_port, agent_port)

        with pytest.raises(ValueError, match="La note doit être entre 1 et 5"):
            use_case.execute(
                agent_id="agent-123",
                organization_id="org-123",
                reviewer_name="John",
                rating=6,
                title="Good",
                content="This is a valid content."
            )

    def test_submit_review_short_title_raises_error(self):
        """La soumission avec titre trop court échoue."""
        review_port = MagicMock()
        installation_port = MagicMock()
        agent_port = MagicMock()

        use_case = SubmitReviewUseCase(review_port, installation_port, agent_port)

        with pytest.raises(ValueError, match="Le titre doit faire au moins 3 caractères"):
            use_case.execute(
                agent_id="agent-123",
                organization_id="org-123",
                reviewer_name="John",
                rating=5,
                title="Go",
                content="This is a valid content."
            )

    def test_submit_review_short_content_raises_error(self):
        """La soumission avec contenu trop court échoue."""
        review_port = MagicMock()
        installation_port = MagicMock()
        agent_port = MagicMock()

        use_case = SubmitReviewUseCase(review_port, installation_port, agent_port)

        with pytest.raises(ValueError, match="Le contenu doit faire au moins 10 caractères"):
            use_case.execute(
                agent_id="agent-123",
                organization_id="org-123",
                reviewer_name="John",
                rating=5,
                title="Good",
                content="Short"
            )

    def test_submit_review_without_installation_not_verified(self):
        """Un avis sans installation n'est pas marqué comme achat vérifié."""
        review_port = MagicMock()
        installation_port = MagicMock()
        agent_port = MagicMock()

        agent = MarketplaceAgent(id="agent-123", name="Test Agent")

        review = AgentReview(
            id="review-123",
            agent_id="agent-123",
            organization_id="org-123",
            rating=3,
            title="Decent",
            content="It's okay but not perfect.",
            is_verified_purchase=False,
            is_approved=True
        )

        installation_port.find_installation.return_value = None
        review_port.save.return_value = review
        agent_port.get_by_id.return_value = agent
        review_port.count_reviews.return_value = 1
        review_port.calculate_average_rating.return_value = 3.0

        use_case = SubmitReviewUseCase(review_port, installation_port, agent_port)
        result = use_case.execute(
            agent_id="agent-123",
            organization_id="org-123",
            reviewer_name="Jane",
            rating=3,
            title="Decent",
            content="It's okay but not perfect."
        )

        assert result.is_verified_purchase is False


class TestRespondToReviewUseCase:
    """Tests pour RespondToReviewUseCase."""

    def test_respond_to_review_success(self):
        """La réponse à un avis réussit."""
        review_port = MagicMock()
        agent_port = MagicMock()

        review = AgentReview(
            id="review-123",
            agent_id="agent-123",
            rating=4,
            title="Good"
        )

        agent = MarketplaceAgent(
            id="agent-123",
            name="Test Agent",
            publisher_id="pub-123"
        )

        updated_review = AgentReview(
            id="review-123",
            agent_id="agent-123",
            rating=4,
            title="Good",
            publisher_response="Thank you for your feedback!",
            publisher_response_at=datetime.now()
        )

        review_port.get_by_id.return_value = review
        agent_port.get_by_id.return_value = agent
        review_port.update.return_value = updated_review

        use_case = RespondToReviewUseCase(review_port, agent_port)
        result = use_case.execute(
            review_id="review-123",
            publisher_id="pub-123",
            response="Thank you for your feedback!"
        )

        assert result.publisher_response == "Thank you for your feedback!"
        assert result.publisher_response_at is not None

    def test_respond_to_review_nonexistent_raises_error(self):
        """La réponse à un avis inexistant échoue."""
        review_port = MagicMock()
        agent_port = MagicMock()

        review_port.get_by_id.return_value = None

        use_case = RespondToReviewUseCase(review_port, agent_port)

        with pytest.raises(ValueError, match="Avis .* non trouvé"):
            use_case.execute("non-existent", "pub-123", "Response")

    def test_respond_to_review_unauthorized_raises_error(self):
        """La réponse sans être propriétaire de l'agent échoue."""
        review_port = MagicMock()
        agent_port = MagicMock()

        review = AgentReview(
            id="review-123",
            agent_id="agent-123",
            rating=4,
            title="Good"
        )

        agent = MarketplaceAgent(
            id="agent-123",
            publisher_id="pub-different"
        )

        review_port.get_by_id.return_value = review
        agent_port.get_by_id.return_value = agent

        use_case = RespondToReviewUseCase(review_port, agent_port)

        with pytest.raises(ValueError, match="n'êtes pas autorisé"):
            use_case.execute("review-123", "pub-123", "Response")

    def test_respond_to_review_short_response_raises_error(self):
        """La réponse trop courte échoue."""
        review_port = MagicMock()
        agent_port = MagicMock()

        review = AgentReview(id="review-123", agent_id="agent-123")
        agent = MarketplaceAgent(id="agent-123", publisher_id="pub-123")

        review_port.get_by_id.return_value = review
        agent_port.get_by_id.return_value = agent

        use_case = RespondToReviewUseCase(review_port, agent_port)

        with pytest.raises(ValueError, match="La réponse doit faire au moins 10 caractères"):
            use_case.execute("review-123", "pub-123", "Short")


class TestListAgentReviewsUseCase:
    """Tests pour ListAgentReviewsUseCase."""

    def test_list_agent_reviews_success(self):
        """Le listing des avis d'un agent réussit."""
        review_port = MagicMock()

        reviews = [
            AgentReview(id="r1", agent_id="agent-123", rating=5),
            AgentReview(id="r2", agent_id="agent-123", rating=4),
            AgentReview(id="r3", agent_id="agent-123", rating=5)
        ]

        review_port.get_by_agent.return_value = reviews

        use_case = ListAgentReviewsUseCase(review_port)
        result = use_case.execute("agent-123", limit=50, offset=0)

        assert len(result) == 3
        review_port.get_by_agent.assert_called_once()
        call_args = review_port.get_by_agent.call_args
        assert call_args[1]["approved_only"] is True

    def test_list_agent_reviews_with_pagination(self):
        """Le listing des avis supporte la pagination."""
        review_port = MagicMock()
        review_port.get_by_agent.return_value = []

        use_case = ListAgentReviewsUseCase(review_port)
        use_case.execute("agent-123", limit=25, offset=50)

        call_args = review_port.get_by_agent.call_args
        assert call_args[1]["limit"] == 25
        assert call_args[1]["offset"] == 50


# =============================================================================
# PACK USE CASES TESTS
# =============================================================================

class TestCreateAgentPackUseCase:
    """Tests pour CreateAgentPackUseCase."""

    def test_create_pack_success(self):
        """La création d'un pack réussit."""
        pack_port = MagicMock()
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(id="pub-123", name="Test Publisher", email="test@example.com")
        publisher_port.get_by_id.return_value = publisher

        agent1 = MarketplaceAgent(id="a1", name="Agent 1", status=AgentStatus.PUBLISHED)
        agent2 = MarketplaceAgent(id="a2", name="Agent 2", status=AgentStatus.PUBLISHED)
        agent_port.get_by_id.side_effect = [agent1, agent2]

        pack = AgentPack(
            id="pack-123",
            name="Test Pack",
            slug="test-pack",
            description="A test pack",
            agent_ids=["a1", "a2"],
            publisher_id="pub-123",
            status=AgentStatus.DRAFT
        )
        pack_port.save.return_value = pack

        use_case = CreateAgentPackUseCase(pack_port, agent_port, publisher_port)
        result = use_case.execute(
            publisher_id="pub-123",
            name="Test Pack",
            description="A test pack",
            agent_ids=["a1", "a2"]
        )

        assert result.id == "pack-123"
        assert result.status == AgentStatus.DRAFT
        assert len(result.agent_ids) == 2

    def test_create_pack_nonexistent_publisher_raises_error(self):
        """La création avec éditeur inexistant échoue."""
        pack_port = MagicMock()
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher_port.get_by_id.return_value = None

        use_case = CreateAgentPackUseCase(pack_port, agent_port, publisher_port)

        with pytest.raises(ValueError, match="Éditeur .* non trouvé"):
            use_case.execute(
                publisher_id="non-existent",
                name="Test Pack",
                description="Test",
                agent_ids=["a1", "a2"]
            )

    def test_create_pack_less_than_two_agents_raises_error(self):
        """La création avec moins de 2 agents échoue."""
        pack_port = MagicMock()
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(id="pub-123", name="Test", email="test@example.com")
        publisher_port.get_by_id.return_value = publisher

        use_case = CreateAgentPackUseCase(pack_port, agent_port, publisher_port)

        with pytest.raises(ValueError, match="Un pack doit contenir au moins 2 agents"):
            use_case.execute(
                publisher_id="pub-123",
                name="Test Pack",
                description="Test",
                agent_ids=["a1"]
            )

    def test_create_pack_nonexistent_agent_raises_error(self):
        """La création avec agent inexistant échoue."""
        pack_port = MagicMock()
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(id="pub-123", name="Test", email="test@example.com")
        publisher_port.get_by_id.return_value = publisher

        agent_port.get_by_id.return_value = None

        use_case = CreateAgentPackUseCase(pack_port, agent_port, publisher_port)

        with pytest.raises(ValueError, match="Agent .* non trouvé"):
            use_case.execute(
                publisher_id="pub-123",
                name="Test Pack",
                description="Test",
                agent_ids=["non-existent", "a2"]
            )

    def test_create_pack_unpublished_agent_raises_error(self):
        """La création avec agent non publié échoue."""
        pack_port = MagicMock()
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(id="pub-123", name="Test", email="test@example.com")
        publisher_port.get_by_id.return_value = publisher

        agent = MarketplaceAgent(id="a1", name="Draft Agent", status=AgentStatus.DRAFT)
        agent_port.get_by_id.return_value = agent

        use_case = CreateAgentPackUseCase(pack_port, agent_port, publisher_port)

        with pytest.raises(ValueError, match="n'est pas publié"):
            use_case.execute(
                publisher_id="pub-123",
                name="Test Pack",
                description="Test",
                agent_ids=["a1", "a2"]
            )

    def test_create_pack_slug_generation(self):
        """Le slug du pack est généré correctement."""
        pack_port = MagicMock()
        agent_port = MagicMock()
        publisher_port = MagicMock()

        publisher = Publisher(id="pub-123", name="Test", email="test@example.com")
        publisher_port.get_by_id.return_value = publisher

        agent1 = MarketplaceAgent(id="a1", status=AgentStatus.PUBLISHED)
        agent2 = MarketplaceAgent(id="a2", status=AgentStatus.PUBLISHED)
        agent_port.get_by_id.side_effect = [agent1, agent2]

        pack_port.save.return_value = AgentPack(
            id="pack-123",
            name="My Awesome Pack!!!",
            slug="my-awesome-pack",
            agent_ids=["a1", "a2"]
        )

        use_case = CreateAgentPackUseCase(pack_port, agent_port, publisher_port)
        use_case.execute(
            publisher_id="pub-123",
            name="My Awesome Pack!!!",
            description="Test",
            agent_ids=["a1", "a2"]
        )

        saved_pack = pack_port.save.call_args[0][0]
        assert saved_pack.slug == "my-awesome-pack"


class TestInstallPackUseCase:
    """Tests pour InstallPackUseCase."""

    def test_install_pack_success(self):
        """L'installation d'un pack réussit."""
        pack_port = MagicMock()
        install_agent_use_case = MagicMock()

        pack = AgentPack(
            id="pack-123",
            name="Test Pack",
            agent_ids=["a1", "a2"],
            status=AgentStatus.PUBLISHED
        )
        pack_port.get_by_id.return_value = pack

        inst1 = AgentInstallation(id="i1", agent_id="a1")
        inst2 = AgentInstallation(id="i2", agent_id="a2")
        install_agent_use_case.execute.side_effect = [inst1, inst2]

        use_case = InstallPackUseCase(pack_port, install_agent_use_case)
        result = use_case.execute("pack-123", "org-123")

        assert len(result) == 2
        assert install_agent_use_case.execute.call_count == 2

    def test_install_pack_nonexistent_raises_error(self):
        """L'installation d'un pack inexistant échoue."""
        pack_port = MagicMock()
        install_agent_use_case = MagicMock()

        pack_port.get_by_id.return_value = None

        use_case = InstallPackUseCase(pack_port, install_agent_use_case)

        with pytest.raises(ValueError, match="Pack .* non trouvé"):
            use_case.execute("non-existent", "org-123")

    def test_install_pack_skips_already_installed_agents(self):
        """L'installation du pack saute les agents déjà installés."""
        pack_port = MagicMock()
        install_agent_use_case = MagicMock()

        pack = AgentPack(
            id="pack-123",
            name="Test Pack",
            agent_ids=["a1", "a2"],
            status=AgentStatus.PUBLISHED
        )
        pack_port.get_by_id.return_value = pack

        inst1 = AgentInstallation(id="i1", agent_id="a1")
        # a2 is already installed, raises ValueError
        install_agent_use_case.execute.side_effect = [
            inst1,
            ValueError("Cet agent est déjà installé")
        ]

        use_case = InstallPackUseCase(pack_port, install_agent_use_case)
        result = use_case.execute("pack-123", "org-123")

        # Should still have 1 installation despite error for a2
        assert len(result) == 1
        assert result[0].agent_id == "a1"

    def test_install_pack_continues_on_errors(self):
        """L'installation continue même si un agent échoue."""
        pack_port = MagicMock()
        install_agent_use_case = MagicMock()

        pack = AgentPack(
            id="pack-123",
            name="Test Pack",
            agent_ids=["a1", "a2", "a3"],
            status=AgentStatus.PUBLISHED
        )
        pack_port.get_by_id.return_value = pack

        inst1 = AgentInstallation(id="i1", agent_id="a1")
        inst3 = AgentInstallation(id="i3", agent_id="a3")
        # a2 fails, but others should succeed
        install_agent_use_case.execute.side_effect = [
            inst1,
            ValueError("Error"),
            inst3
        ]

        use_case = InstallPackUseCase(pack_port, install_agent_use_case)
        result = use_case.execute("pack-123", "org-123")

        assert len(result) == 2
        assert result[0].agent_id == "a1"
        assert result[1].agent_id == "a3"
