# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for app/api/marketplace.py API endpoints.

Coverage: Target 100% for all marketplace API routes.
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

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
)
from app.infrastructure.marketplace_store import (
    get_marketplace_stores,
    reset_marketplace_stores,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_publisher():
    """Sample publisher for tests."""
    return Publisher(
        id="pub-123",
        name="Test Publisher",
        email="publisher@test.com",
        description="A test publisher",
        website="https://test.com",
        verified=True,
        agent_count=5,
        total_downloads=1000,
        average_rating=4.5,
    )


@pytest.fixture
def sample_agent():
    """Sample agent for tests."""
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
        active_installations=50,
        average_rating=4.5,
        review_count=20,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        published_at=datetime(2026, 1, 2, 12, 0, 0),
    )


@pytest.fixture
def sample_installation():
    """Sample installation for tests."""
    return AgentInstallation(
        id="inst-123",
        agent_id="agent-123",
        organization_id="org-456",
        status=InstallationStatus.ACTIVE,
        installed_version="1.0.0",
        usage_count=50,
        installed_at=datetime(2026, 1, 1, 12, 0, 0),
        last_used_at=datetime(2026, 1, 15, 12, 0, 0),
        expires_at=datetime(2027, 1, 1, 12, 0, 0),
    )


@pytest.fixture
def sample_review():
    """Sample review for tests."""
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
        created_at=datetime(2026, 1, 10, 12, 0, 0),
        publisher_response="Thank you!",
        publisher_response_at=datetime(2026, 1, 11, 12, 0, 0),
    )


@pytest.fixture
def sample_pack():
    """Sample pack for tests."""
    return AgentPack(
        id="pack-123",
        name="Support Pack",
        slug="support-pack",
        description="A pack of support agents",
        agent_ids=["agent-1", "agent-2"],
        publisher_id="pub-123",
        status=AgentStatus.PUBLISHED,
        discount_percent=10,
    )


@pytest.fixture
def client(temp_data_dir):
    """Flask test client.

    F-02 (audit issue #209, 2026-04-29): `approve_agent` is now under
    `@require_admin`. The fixture patches `ADMIN_EMAILS` to include the
    test admin so that `_admin_auth_headers()` JWTs are accepted.
    """
    from app.api.app import create_app
    from app.api import admin as _admin_module

    reset_marketplace_stores()

    # Patch ADMIN_EMAILS at the module level (frozen at import time
    # otherwise) so the admin JWT we mint below is recognised.
    original_admins = _admin_module.ADMIN_EMAILS.copy()
    _admin_module.ADMIN_EMAILS.add("admin@test.com")

    try:
        with patch('app.api.marketplace.get_marketplace_stores') as mock_get_stores:
            mock_get_stores.return_value = get_marketplace_stores(temp_data_dir)
            app = create_app({"TESTING": True})
            with app.test_client() as client:
                yield client
    finally:
        _admin_module.ADMIN_EMAILS.clear()
        _admin_module.ADMIN_EMAILS.update(original_admins)


def _admin_auth_headers() -> dict:
    """Mint a JWT for admin@test.com and wrap as Authorization header.

    F-02 (audit issue #209): used by tests that exercise endpoints now
    behind `@require_admin` (approve_agent, wizard config save/delete,
    wizard import/export, mobile config admin). The corresponding
    `client` fixture must add this email to `app.api.admin.ADMIN_EMAILS`.
    """
    import time
    import jwt as _pyjwt
    from app.api.auth import JWT_SECRET, JWT_ALGORITHM

    token = _pyjwt.encode(
        {
            "sub": "99999",
            "email": "admin@test.com",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# TESTS - REQUIRE_JSON DECORATOR
# ============================================================================

class TestRequireJsonDecorator:
    """Tests for require_json decorator."""

    def test_require_json_empty_dict(self, client):
        """POST with empty JSON dict should return 400 'JSON body required'."""
        response = client.post(
            "/api/marketplace/publishers",
            json={},
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "JSON body required"

    def test_require_json_no_content_type(self, client):
        """POST without a JSON content type returns a consistent 400 'JSON body
        required' (audit 2026-05-19 STAB-02). Previously this surfaced werkzeug's
        incidental 415 because `request.get_json()` raised before the decorator
        could return its intended 400; with silent=True the decorator now owns
        the response for every missing/malformed-body case."""
        response = client.post(
            "/api/marketplace/publishers",
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "JSON body required"

    def test_require_json_array_body_rejected(self, client):
        """A JSON array body (valid JSON, wrong shape) is rejected with 400
        instead of passing the truthiness check and blowing up on data.get()."""
        response = client.post(
            "/api/marketplace/publishers",
            json=["not", "an", "object"],
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "JSON body required"


# ============================================================================
# TESTS - PUBLISHERS ENDPOINTS
# ============================================================================

class TestPublishersAPI:
    """Tests for /api/marketplace/publishers endpoints."""

    def test_register_publisher_success(self, client):
        """POST /api/marketplace/publishers - success."""
        response = client.post(
            "/api/marketplace/publishers",
            json={
                "name": "My Publisher",
                "email": "pub@test.com",
                "description": "Test desc",
                "website": "https://example.com",
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["publisher"]["name"] == "My Publisher"
        assert data["publisher"]["email"] == "pub@test.com"
        assert data["publisher"]["verified"] is False

    def test_register_publisher_missing_name(self, client):
        """POST /api/marketplace/publishers - missing name."""
        response = client.post(
            "/api/marketplace/publishers",
            json={"email": "test@test.com"},
        )
        assert response.status_code == 400

    def test_register_publisher_invalid_email(self, client):
        """POST /api/marketplace/publishers - invalid email."""
        response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Test", "email": "invalid-email"},
        )
        assert response.status_code == 400

    def test_register_publisher_duplicate_email(self, client):
        """POST /api/marketplace/publishers - duplicate email."""
        # Register first publisher
        client.post(
            "/api/marketplace/publishers",
            json={"name": "First", "email": "dup@test.com"},
        )
        # Try to register with same email
        response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Second", "email": "dup@test.com"},
        )
        assert response.status_code == 400

    def test_get_publisher_success(self, client):
        """GET /api/marketplace/publishers/<id> - success."""
        # Create a publisher first
        create_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Get Test", "email": "get@test.com", "description": "A test description", "website": "https://test.com"},
        )
        publisher_id = create_response.get_json()["publisher"]["id"]

        # Get the publisher
        response = client.get(f"/api/marketplace/publishers/{publisher_id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == publisher_id
        assert data["name"] == "Get Test"
        assert data["description"] == "A test description"
        assert data["website"] == "https://test.com"
        assert "verified" in data
        assert "agent_count" in data
        assert "total_downloads" in data
        assert "average_rating" in data

    def test_get_publisher_not_found(self, client):
        """GET /api/marketplace/publishers/<id> - not found."""
        response = client.get("/api/marketplace/publishers/invalid-id")
        assert response.status_code == 404
        assert response.get_json()["error"] == "Publisher not found"


# ============================================================================
# TESTS - SEARCH AGENTS ENDPOINTS
# ============================================================================

class TestSearchAgentsAPI:
    """Tests for search and list agents endpoints."""

    def _setup_published_agent(self, client):
        """Helper to create and publish an agent."""
        # Create publisher
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "p@t.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        # Create agent
        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Search Test Agent",
                "description": "Agent for testing search",
                "category": "customer_service",
                "system_prompt": "You are a test agent.",
                "tags": ["support", "test"],
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]

        # Submit and approve
        client.post(f"/api/marketplace/agents/{agent_id}/submit", json={"publisher_id": publisher_id})
        client.post(f"/api/marketplace/agents/{agent_id}/approve", headers=_admin_auth_headers())

        return publisher_id, agent_id

    def test_search_agents_empty(self, client):
        """GET /api/marketplace/agents - empty list."""
        response = client.get("/api/marketplace/agents")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 0
        assert data["agents"] == []
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert data["total_pages"] == 0

    def test_search_agents_with_query(self, client):
        """GET /api/marketplace/agents?q=search - text search."""
        self._setup_published_agent(client)

        response = client.get("/api/marketplace/agents?q=search")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 1
        assert data["agents"][0]["name"] == "Search Test Agent"

    def test_search_agents_with_category_filter(self, client):
        """GET /api/marketplace/agents?category=customer_service."""
        self._setup_published_agent(client)

        response = client.get("/api/marketplace/agents?category=customer_service")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 1

    def test_search_agents_with_invalid_category(self, client):
        """GET /api/marketplace/agents?category=invalid - ignores invalid."""
        self._setup_published_agent(client)

        # Invalid category should be ignored
        response = client.get("/api/marketplace/agents?category=invalid_cat")
        assert response.status_code == 200

    def test_search_agents_with_pricing_filter(self, client):
        """GET /api/marketplace/agents?pricing=free."""
        self._setup_published_agent(client)

        response = client.get("/api/marketplace/agents?pricing=free")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_count"] == 1

    def test_search_agents_with_invalid_pricing(self, client):
        """GET /api/marketplace/agents?pricing=invalid - ignores invalid."""
        self._setup_published_agent(client)

        response = client.get("/api/marketplace/agents?pricing=invalid_pricing")
        assert response.status_code == 200

    def test_search_agents_with_min_rating(self, client):
        """GET /api/marketplace/agents?min_rating=3.0."""
        self._setup_published_agent(client)

        response = client.get("/api/marketplace/agents?min_rating=3.0")
        assert response.status_code == 200

    def test_search_agents_with_pagination(self, client):
        """GET /api/marketplace/agents?page=2&per_page=5."""
        response = client.get("/api/marketplace/agents?page=2&per_page=5")
        assert response.status_code == 200
        data = response.get_json()
        assert data["page"] == 2
        assert data["per_page"] == 5

    def test_search_agents_with_sort(self, client):
        """GET /api/marketplace/agents?sort=newest."""
        response = client.get("/api/marketplace/agents?sort=newest")
        assert response.status_code == 200

    def test_list_featured_agents(self, client):
        """GET /api/marketplace/agents/featured."""
        self._setup_published_agent(client)

        response = client.get("/api/marketplace/agents/featured")
        assert response.status_code == 200
        data = response.get_json()
        assert "count" in data
        assert "agents" in data
        assert data["count"] >= 0

    def test_list_featured_agents_with_limit(self, client):
        """GET /api/marketplace/agents/featured?limit=5."""
        response = client.get("/api/marketplace/agents/featured?limit=5")
        assert response.status_code == 200

    def test_list_agents_by_category(self, client):
        """GET /api/marketplace/agents/categories/<category>."""
        self._setup_published_agent(client)

        response = client.get("/api/marketplace/agents/categories/customer_service")
        assert response.status_code == 200
        data = response.get_json()
        assert data["category"] == "customer_service"
        assert "count" in data
        assert "agents" in data

    def test_list_agents_by_invalid_category(self, client):
        """GET /api/marketplace/agents/categories/<invalid> - 400."""
        response = client.get("/api/marketplace/agents/categories/invalid_category")
        assert response.status_code == 400
        assert "Invalid category" in response.get_json()["error"]

    def test_list_agents_by_category_with_pagination(self, client):
        """GET /api/marketplace/agents/categories/<category>?limit=10&offset=5."""
        response = client.get("/api/marketplace/agents/categories/customer_service?limit=10&offset=5")
        assert response.status_code == 200


# ============================================================================
# TESTS - AGENT DETAILS ENDPOINT
# ============================================================================

class TestAgentDetailsAPI:
    """Tests for get agent details endpoint."""

    def _setup_published_agent(self, client):
        """Helper to create and publish an agent."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "details@t.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Details Test Agent",
                "description": "Agent for testing details",
                "category": "sales",
                "system_prompt": "You are a test agent.",
                "capabilities": [
                    {"name": "cap1", "description": "Cap 1 desc", "keywords": ["a", "b"]},
                ],
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]

        client.post(f"/api/marketplace/agents/{agent_id}/submit", json={"publisher_id": publisher_id})
        client.post(f"/api/marketplace/agents/{agent_id}/approve", headers=_admin_auth_headers())

        return publisher_id, agent_id

    def test_get_agent_details_success(self, client):
        """GET /api/marketplace/agents/<id> - success."""
        publisher_id, agent_id = self._setup_published_agent(client)

        response = client.get(f"/api/marketplace/agents/{agent_id}")
        assert response.status_code == 200
        data = response.get_json()
        assert "agent" in data
        assert data["agent"]["id"] == agent_id
        assert data["agent"]["name"] == "Details Test Agent"
        assert "system_prompt" in data
        assert "capabilities" in data
        assert len(data["capabilities"]) == 1
        assert data["capabilities"][0]["name"] == "cap1"
        assert "reviews" in data
        assert "active_installations" in data
        assert "average_rating" in data
        assert "review_count" in data

    def test_get_agent_details_not_found(self, client):
        """GET /api/marketplace/agents/<invalid> - 404."""
        response = client.get("/api/marketplace/agents/invalid-agent-id")
        assert response.status_code == 404
        assert response.get_json()["error"] == "Agent not found"


# ============================================================================
# TESTS - PUBLISH AGENT ENDPOINT
# ============================================================================

class TestPublishAgentAPI:
    """Tests for publish agent endpoint."""

    def test_publish_agent_success(self, client):
        """POST /api/marketplace/agents - success."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "pub@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "New Agent",
                "description": "New agent desc",
                "category": "custom",
                "system_prompt": "You are an agent.",
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["agent"]["name"] == "New Agent"
        assert data["agent"]["status"] == "draft"
        assert "DRAFT" in data["message"]

    def test_publish_agent_with_capabilities(self, client):
        """POST /api/marketplace/agents - with capabilities."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "cap@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Cap Agent",
                "description": "Agent with caps",
                "category": "sales",
                "system_prompt": "You are an agent.",
                "capabilities": [
                    {"name": "sell", "description": "Can sell", "keywords": ["sale"]},
                ],
                "tags": ["sales", "crm"],
                "long_description": "A longer description.",
                "knowledge_base_template": "KB template here",
            },
        )
        assert response.status_code == 201

    def test_publish_agent_with_pricing_free(self, client):
        """POST /api/marketplace/agents - with free pricing."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "free@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Free Agent",
                "description": "Free agent",
                "category": "custom",
                "system_prompt": "You are an agent.",
                "pricing": {
                    "model": "free",
                    "price_cents": 0,
                    "currency": "EUR",
                    "trial_days": 0,
                },
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["agent"]["pricing"]["model"] == "free"
        assert data["agent"]["pricing"]["price_cents"] == 0

    def test_publish_agent_with_pricing_subscription(self, client):
        """POST /api/marketplace/agents - with subscription pricing."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "sub@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Paid Agent",
                "description": "Paid agent",
                "category": "custom",
                "system_prompt": "You are an agent.",
                "pricing": {
                    "model": "subscription",
                    "price_cents": 999,
                    "currency": "USD",
                    "trial_days": 14,
                },
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["agent"]["pricing"]["model"] == "subscription"
        assert data["agent"]["pricing"]["price_cents"] == 999
        assert data["agent"]["pricing"]["trial_days"] == 14

    def test_publish_agent_invalid_category(self, client):
        """POST /api/marketplace/agents - invalid category."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "invcat@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Bad Cat Agent",
                "description": "A test agent for the marketplace",
                "category": "invalid_category_xyz",
                "system_prompt": "You are an agent.",
            },
        )
        assert response.status_code == 400
        assert "Invalid category" in response.get_json()["error"]

    def test_publish_agent_invalid_pricing_model(self, client):
        """POST /api/marketplace/agents - invalid pricing model."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "invprice@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Bad Price Agent",
                "description": "A test agent for the marketplace",
                "category": "custom",
                "system_prompt": "You are an agent.",
                "pricing": {
                    "model": "invalid_model",
                    "price_cents": 100,
                },
            },
        )
        assert response.status_code == 400
        assert "Invalid pricing" in response.get_json()["error"]

    def test_publish_agent_publisher_not_found(self, client):
        """POST /api/marketplace/agents - publisher not found."""
        response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": "invalid-publisher-id",
                "name": "Agent",
                "description": "A test agent for the marketplace",
                "category": "custom",
                "system_prompt": "You are an agent.",
            },
        )
        assert response.status_code == 400

    def test_publish_agent_missing_name(self, client):
        """POST /api/marketplace/agents - missing name."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "noname@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "",
                "description": "A test agent for the marketplace",
                "category": "custom",
                "system_prompt": "You are an agent.",
            },
        )
        assert response.status_code == 400


# ============================================================================
# TESTS - UPDATE AGENT ENDPOINT
# ============================================================================

class TestUpdateAgentAPI:
    """Tests for update agent endpoint."""

    def _setup_agent(self, client):
        """Helper to create an agent."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "upd@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Update Test Agent",
                "description": "Original desc",
                "category": "custom",
                "system_prompt": "Original prompt",
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]
        return publisher_id, agent_id

    def test_update_agent_success(self, client):
        """PATCH /api/marketplace/agents/<id> - success."""
        publisher_id, agent_id = self._setup_agent(client)

        response = client.patch(
            f"/api/marketplace/agents/{agent_id}",
            json={
                "publisher_id": publisher_id,
                "description": "Updated description",
                "tags": ["new", "tags"],
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["agent"]["description"] == "Updated description"
        assert data["agent"]["tags"] == ["new", "tags"]

    def test_update_agent_missing_publisher_id(self, client):
        """PATCH /api/marketplace/agents/<id> - missing publisher_id."""
        publisher_id, agent_id = self._setup_agent(client)

        response = client.patch(
            f"/api/marketplace/agents/{agent_id}",
            json={"description": "Updated"},
        )
        assert response.status_code == 400
        assert "publisher_id is required" in response.get_json()["error"]

    def test_update_agent_not_found(self, client):
        """PATCH /api/marketplace/agents/<id> - not found."""
        response = client.patch(
            "/api/marketplace/agents/invalid-id",
            json={"publisher_id": "pub-123", "description": "Updated"},
        )
        assert response.status_code == 400

    def test_update_agent_not_owner(self, client):
        """PATCH /api/marketplace/agents/<id> - not owner."""
        publisher_id, agent_id = self._setup_agent(client)

        response = client.patch(
            f"/api/marketplace/agents/{agent_id}",
            json={"publisher_id": "other-publisher", "description": "Updated"},
        )
        assert response.status_code == 400


# ============================================================================
# TESTS - SUBMIT FOR REVIEW ENDPOINT
# ============================================================================

class TestSubmitForReviewAPI:
    """Tests for submit agent for review endpoint."""

    def _setup_agent(self, client):
        """Helper to create an agent."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "submit@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Submit Test Agent",
                "description": "A test agent for the marketplace",
                "category": "custom",
                "system_prompt": "You are an agent.",
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]
        return publisher_id, agent_id

    def test_submit_for_review_success(self, client):
        """POST /api/marketplace/agents/<id>/submit - success."""
        publisher_id, agent_id = self._setup_agent(client)

        response = client.post(
            f"/api/marketplace/agents/{agent_id}/submit",
            json={"publisher_id": publisher_id},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["agent"]["status"] == "pending_review"
        assert "submitted for review" in data["message"]

    def test_submit_for_review_missing_publisher_id(self, client):
        """POST /api/marketplace/agents/<id>/submit - missing publisher_id."""
        publisher_id, agent_id = self._setup_agent(client)

        response = client.post(
            f"/api/marketplace/agents/{agent_id}/submit",
            json={"other_field": "value"},  # Non-empty but without publisher_id
        )
        assert response.status_code == 400
        assert "publisher_id is required" in response.get_json()["error"]

    def test_submit_for_review_not_owner(self, client):
        """POST /api/marketplace/agents/<id>/submit - not owner."""
        publisher_id, agent_id = self._setup_agent(client)

        response = client.post(
            f"/api/marketplace/agents/{agent_id}/submit",
            json={"publisher_id": "other-pub"},
        )
        assert response.status_code == 400

    def test_submit_for_review_wrong_status(self, client):
        """POST /api/marketplace/agents/<id>/submit - already published."""
        publisher_id, agent_id = self._setup_agent(client)

        # Submit and approve
        client.post(f"/api/marketplace/agents/{agent_id}/submit", json={"publisher_id": publisher_id})
        client.post(f"/api/marketplace/agents/{agent_id}/approve", headers=_admin_auth_headers())

        # Try to submit again
        response = client.post(
            f"/api/marketplace/agents/{agent_id}/submit",
            json={"publisher_id": publisher_id},
        )
        assert response.status_code == 400


# ============================================================================
# TESTS - APPROVE AGENT ENDPOINT
# ============================================================================

class TestApproveAgentAPI:
    """Tests for approve agent endpoint."""

    def _setup_pending_agent(self, client):
        """Helper to create an agent pending review."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "approve@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Approve Test Agent",
                "description": "A test agent for the marketplace",
                "category": "custom",
                "system_prompt": "You are an agent.",
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]

        # Submit for review
        client.post(f"/api/marketplace/agents/{agent_id}/submit", json={"publisher_id": publisher_id})
        return publisher_id, agent_id

    def test_approve_agent_success(self, client):
        """POST /api/marketplace/agents/<id>/approve - success."""
        publisher_id, agent_id = self._setup_pending_agent(client)

        response = client.post(f"/api/marketplace/agents/{agent_id}/approve", headers=_admin_auth_headers())  # F-02
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["agent"]["status"] == "published"
        assert "approved and published" in data["message"]

    def test_approve_agent_not_found(self, client):
        """POST /api/marketplace/agents/<id>/approve - not found."""
        response = client.post("/api/marketplace/agents/invalid-id/approve", headers=_admin_auth_headers())  # F-02
        assert response.status_code == 400

    def test_approve_agent_wrong_status(self, client):
        """POST /api/marketplace/agents/<id>/approve - not pending."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "wrongstatus@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Draft Agent",
                "description": "A test agent for the marketplace",
                "category": "custom",
                "system_prompt": "You are an agent.",
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]

        # Try to approve without submitting
        response = client.post(f"/api/marketplace/agents/{agent_id}/approve", headers=_admin_auth_headers())  # F-02
        assert response.status_code == 400


# ============================================================================
# TESTS - INSTALLATIONS ENDPOINTS
# ============================================================================

class TestInstallationsAPI:
    """Tests for installations endpoints."""

    def _setup_published_agent(self, client, email_suffix="inst"):
        """Helper to create and publish an agent."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": f"{email_suffix}@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Install Test Agent",
                "description": "A test agent for the marketplace",
                "category": "custom",
                "system_prompt": "You are an agent.",
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]

        client.post(f"/api/marketplace/agents/{agent_id}/submit", json={"publisher_id": publisher_id})
        client.post(f"/api/marketplace/agents/{agent_id}/approve", headers=_admin_auth_headers())
        return publisher_id, agent_id

    def test_list_installations_success(self, client):
        """GET /api/marketplace/installations - success."""
        publisher_id, agent_id = self._setup_published_agent(client, "list")

        # Install the agent
        client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": "org-123"},
        )

        response = client.get("/api/marketplace/installations?organization_id=org-123")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        assert len(data["installations"]) == 1
        assert "agent" in data["installations"][0]

    def test_list_installations_missing_org_id(self, client):
        """GET /api/marketplace/installations - missing organization_id."""
        response = client.get("/api/marketplace/installations")
        assert response.status_code == 400
        assert "organization_id is required" in response.get_json()["error"]

    def test_list_installations_active_only_true(self, client):
        """GET /api/marketplace/installations?active_only=true."""
        publisher_id, agent_id = self._setup_published_agent(client, "active")
        client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": "org-active"},
        )

        response = client.get("/api/marketplace/installations?organization_id=org-active&active_only=true")
        assert response.status_code == 200

    def test_list_installations_active_only_false(self, client):
        """GET /api/marketplace/installations?active_only=false."""
        publisher_id, agent_id = self._setup_published_agent(client, "inactive")
        client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": "org-inactive"},
        )

        response = client.get("/api/marketplace/installations?organization_id=org-inactive&active_only=false")
        assert response.status_code == 200

    def test_install_agent_success(self, client):
        """POST /api/marketplace/agents/<id>/install - success."""
        publisher_id, agent_id = self._setup_published_agent(client, "install")

        response = client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": "org-install"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["installation"]["agent_id"] == agent_id
        assert data["installation"]["organization_id"] == "org-install"
        assert "installed successfully" in data["message"]

    def test_install_agent_with_custom_settings(self, client):
        """POST /api/marketplace/agents/<id>/install - with custom_settings."""
        publisher_id, agent_id = self._setup_published_agent(client, "settings")

        response = client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={
                "organization_id": "org-settings",
                "custom_settings": {"key": "value"},
            },
        )
        assert response.status_code == 201

    def test_install_agent_missing_org_id(self, client):
        """POST /api/marketplace/agents/<id>/install - missing organization_id."""
        publisher_id, agent_id = self._setup_published_agent(client, "noorg")

        response = client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"some_field": "value"},  # Non-empty but without organization_id
        )
        assert response.status_code == 400
        assert "organization_id is required" in response.get_json()["error"]

    def test_install_agent_already_installed(self, client):
        """POST /api/marketplace/agents/<id>/install - already installed."""
        publisher_id, agent_id = self._setup_published_agent(client, "double")

        # Install once
        client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": "org-double"},
        )

        # Try to install again
        response = client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": "org-double"},
        )
        assert response.status_code == 400

    def test_install_agent_not_published(self, client):
        """POST /api/marketplace/agents/<id>/install - agent not published."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "draft@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Draft Agent",
                "description": "A test agent for the marketplace",
                "category": "custom",
                "system_prompt": "You are an agent.",
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]

        # Don't submit/approve - try to install draft
        response = client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": "org-draft"},
        )
        assert response.status_code == 400

    def test_uninstall_agent_success(self, client):
        """DELETE /api/marketplace/installations/<id> - success."""
        publisher_id, agent_id = self._setup_published_agent(client, "uninstall")

        # Install first
        install_response = client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": "org-uninstall"},
        )
        installation_id = install_response.get_json()["installation"]["id"]

        # Uninstall
        response = client.delete(f"/api/marketplace/installations/{installation_id}?organization_id=org-uninstall")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "uninstalled successfully" in data["message"]

    def test_uninstall_agent_missing_org_id(self, client):
        """DELETE /api/marketplace/installations/<id> - missing organization_id."""
        response = client.delete("/api/marketplace/installations/inst-123")
        assert response.status_code == 400
        assert "organization_id is required" in response.get_json()["error"]

    def test_uninstall_agent_not_found(self, client):
        """DELETE /api/marketplace/installations/<id> - not found."""
        response = client.delete("/api/marketplace/installations/invalid-id?organization_id=org-123")
        assert response.status_code == 400

    def test_uninstall_agent_not_owner(self, client):
        """DELETE /api/marketplace/installations/<id> - not owner."""
        publisher_id, agent_id = self._setup_published_agent(client, "notowner")

        install_response = client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": "org-owner"},
        )
        installation_id = install_response.get_json()["installation"]["id"]

        # Try to uninstall with different org
        response = client.delete(f"/api/marketplace/installations/{installation_id}?organization_id=other-org")
        assert response.status_code == 400


# ============================================================================
# TESTS - USAGE RECORDING ENDPOINT
# ============================================================================

class TestRecordUsageAPI:
    """Tests for record usage endpoint."""

    def _setup_installed_agent(self, client, email_suffix="usage"):
        """Helper to create, publish, and install an agent."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": f"{email_suffix}@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Usage Test Agent",
                "description": "A test agent for the marketplace",
                "category": "custom",
                "system_prompt": "You are an agent.",
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]

        client.post(f"/api/marketplace/agents/{agent_id}/submit", json={"publisher_id": publisher_id})
        client.post(f"/api/marketplace/agents/{agent_id}/approve", headers=_admin_auth_headers())

        install_response = client.post(
            f"/api/marketplace/agents/{agent_id}/install",
            json={"organization_id": f"org-{email_suffix}"},
        )
        installation_id = install_response.get_json()["installation"]["id"]

        return publisher_id, agent_id, installation_id

    def test_record_usage_success(self, client):
        """POST /api/marketplace/installations/<id>/usage - success."""
        publisher_id, agent_id, installation_id = self._setup_installed_agent(client, "rec")

        response = client.post(f"/api/marketplace/installations/{installation_id}/usage")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["usage_count"] == 1

    def test_record_usage_multiple_times(self, client):
        """POST /api/marketplace/installations/<id>/usage - multiple."""
        publisher_id, agent_id, installation_id = self._setup_installed_agent(client, "multi")

        # Record 3 times
        for _ in range(3):
            client.post(f"/api/marketplace/installations/{installation_id}/usage")

        response = client.post(f"/api/marketplace/installations/{installation_id}/usage")
        assert response.status_code == 200
        assert response.get_json()["usage_count"] == 4

    def test_record_usage_not_found(self, client):
        """POST /api/marketplace/installations/<id>/usage - not found."""
        response = client.post("/api/marketplace/installations/invalid-id/usage")
        assert response.status_code == 400


# ============================================================================
# TESTS - REVIEWS ENDPOINTS
# ============================================================================

class TestReviewsAPI:
    """Tests for reviews endpoints."""

    def _setup_installed_agent(self, client, email_suffix="review"):
        """Helper to create, publish, and install an agent."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": f"{email_suffix}@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_response = client.post(
            "/api/marketplace/agents",
            json={
                "publisher_id": publisher_id,
                "name": "Review Test Agent",
                "description": "A test agent for the marketplace",
                "category": "custom",
                "system_prompt": "You are an agent.",
            },
        )
        agent_id = agent_response.get_json()["agent"]["id"]

        client.post(f"/api/marketplace/agents/{agent_id}/submit", json={"publisher_id": publisher_id})
        client.post(f"/api/marketplace/agents/{agent_id}/approve", headers=_admin_auth_headers())

        return publisher_id, agent_id

    def test_list_reviews_empty(self, client):
        """GET /api/marketplace/agents/<id>/reviews - empty."""
        publisher_id, agent_id = self._setup_installed_agent(client, "listr")

        response = client.get(f"/api/marketplace/agents/{agent_id}/reviews")
        assert response.status_code == 200
        data = response.get_json()
        assert data["agent_id"] == agent_id
        assert data["count"] == 0
        assert data["reviews"] == []

    def test_list_reviews_with_data(self, client):
        """GET /api/marketplace/agents/<id>/reviews - with reviews."""
        publisher_id, agent_id = self._setup_installed_agent(client, "listreview")

        # Submit a review (install is not verified)
        client.post(
            f"/api/marketplace/agents/{agent_id}/reviews",
            json={
                "organization_id": "org-review",
                "reviewer_name": "Tester",
                "rating": 4,
                "title": "Good",
                "content": "This is a good agent for testing purposes.",
            },
        )

        response = client.get(f"/api/marketplace/agents/{agent_id}/reviews")
        assert response.status_code == 200

    def test_list_reviews_with_pagination(self, client):
        """GET /api/marketplace/agents/<id>/reviews?limit=5&offset=0."""
        publisher_id, agent_id = self._setup_installed_agent(client, "pag")

        response = client.get(f"/api/marketplace/agents/{agent_id}/reviews?limit=5&offset=0")
        assert response.status_code == 200

    def test_submit_review_success(self, client):
        """POST /api/marketplace/agents/<id>/reviews - success."""
        publisher_id, agent_id = self._setup_installed_agent(client, "submitr")

        response = client.post(
            f"/api/marketplace/agents/{agent_id}/reviews",
            json={
                "organization_id": "org-submitr",
                "reviewer_name": "Reviewer",
                "rating": 5,
                "title": "Amazing!",
                "content": "This agent is absolutely amazing for our team.",
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["review"]["rating"] == 5
        assert data["review"]["title"] == "Amazing!"

    def test_submit_review_invalid_rating_too_low(self, client):
        """POST /api/marketplace/agents/<id>/reviews - rating too low."""
        publisher_id, agent_id = self._setup_installed_agent(client, "lowrat")

        response = client.post(
            f"/api/marketplace/agents/{agent_id}/reviews",
            json={
                "organization_id": "org-lowrat",
                "reviewer_name": "Reviewer",
                "rating": 0,
                "title": "Bad",
                "content": "Rating is too low, should be between 1 and 5.",
            },
        )
        assert response.status_code == 400

    def test_submit_review_invalid_rating_too_high(self, client):
        """POST /api/marketplace/agents/<id>/reviews - rating too high."""
        publisher_id, agent_id = self._setup_installed_agent(client, "highrat")

        response = client.post(
            f"/api/marketplace/agents/{agent_id}/reviews",
            json={
                "organization_id": "org-highrat",
                "reviewer_name": "Reviewer",
                "rating": 6,
                "title": "Great",
                "content": "Rating is too high, should be between 1 and 5.",
            },
        )
        assert response.status_code == 400

    def test_respond_to_review_success(self, client):
        """POST /api/marketplace/reviews/<id>/respond - success."""
        publisher_id, agent_id = self._setup_installed_agent(client, "respond")

        # Submit a review
        review_response = client.post(
            f"/api/marketplace/agents/{agent_id}/reviews",
            json={
                "organization_id": "org-respond",
                "reviewer_name": "Reviewer",
                "rating": 4,
                "title": "Good agent",
                "content": "This is a good agent for our needs.",
            },
        )
        review_id = review_response.get_json()["review"]["id"]

        # Respond to the review
        response = client.post(
            f"/api/marketplace/reviews/{review_id}/respond",
            json={
                "publisher_id": publisher_id,
                "response": "Thank you so much for your kind feedback!",
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["review"]["publisher_response"] == "Thank you so much for your kind feedback!"
        assert data["review"]["publisher_response_at"] is not None

    def test_respond_to_review_not_found(self, client):
        """POST /api/marketplace/reviews/<id>/respond - not found."""
        response = client.post(
            "/api/marketplace/reviews/invalid-review-id/respond",
            json={
                "publisher_id": "pub-123",
                "response": "Thank you for your feedback!",
            },
        )
        assert response.status_code == 400

    def test_respond_to_review_not_authorized(self, client):
        """POST /api/marketplace/reviews/<id>/respond - not authorized."""
        publisher_id, agent_id = self._setup_installed_agent(client, "notauth")

        # Submit a review
        review_response = client.post(
            f"/api/marketplace/agents/{agent_id}/reviews",
            json={
                "organization_id": "org-notauth",
                "reviewer_name": "Reviewer",
                "rating": 3,
                "title": "OK agent",
                "content": "This agent is okay but could be better.",
            },
        )
        review_id = review_response.get_json()["review"]["id"]

        # Try to respond with wrong publisher
        response = client.post(
            f"/api/marketplace/reviews/{review_id}/respond",
            json={
                "publisher_id": "other-publisher",
                "response": "This response should fail.",
            },
        )
        assert response.status_code == 400

    def test_respond_to_review_too_short(self, client):
        """POST /api/marketplace/reviews/<id>/respond - response too short."""
        publisher_id, agent_id = self._setup_installed_agent(client, "short")

        # Submit a review
        review_response = client.post(
            f"/api/marketplace/agents/{agent_id}/reviews",
            json={
                "organization_id": "org-short",
                "reviewer_name": "Reviewer",
                "rating": 2,
                "title": "Not great",
                "content": "This agent does not meet our expectations.",
            },
        )
        review_id = review_response.get_json()["review"]["id"]

        # Try to respond with too short response
        response = client.post(
            f"/api/marketplace/reviews/{review_id}/respond",
            json={
                "publisher_id": publisher_id,
                "response": "Thx",
            },
        )
        assert response.status_code == 400


# ============================================================================
# TESTS - PACKS ENDPOINTS
# ============================================================================

class TestPacksAPI:
    """Tests for packs endpoints."""

    def _setup_published_agents(self, client, count=2, email_suffix="pack"):
        """Helper to create multiple published agents."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": f"{email_suffix}@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        agent_ids = []
        for i in range(count):
            agent_response = client.post(
                "/api/marketplace/agents",
                json={
                    "publisher_id": publisher_id,
                    "name": f"Pack Agent {i}",
                    "description": f"This is agent number {i} in the pack",
                    "category": "custom",
                    "system_prompt": f"You are agent {i}.",
                },
            )
            agent_id = agent_response.get_json()["agent"]["id"]
            client.post(f"/api/marketplace/agents/{agent_id}/submit", json={"publisher_id": publisher_id})
            client.post(f"/api/marketplace/agents/{agent_id}/approve", headers=_admin_auth_headers())
            agent_ids.append(agent_id)

        return publisher_id, agent_ids

    def test_list_packs_empty(self, client):
        """GET /api/marketplace/packs - empty."""
        response = client.get("/api/marketplace/packs")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 0
        assert data["packs"] == []

    def test_list_packs_with_data(self, client):
        """GET /api/marketplace/packs - with packs."""
        publisher_id, agent_ids = self._setup_published_agents(client, 2, "listpack")

        # Create a pack
        client.post(
            "/api/marketplace/packs",
            json={
                "publisher_id": publisher_id,
                "name": "My Pack",
                "description": "A pack of agents",
                "agent_ids": agent_ids,
                "discount_percent": 15,
            },
        )

        response = client.get("/api/marketplace/packs")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        assert data["packs"][0]["name"] == "My Pack"
        assert data["packs"][0]["agent_count"] == 2
        assert data["packs"][0]["discount_percent"] == 15

    def test_create_pack_success(self, client):
        """POST /api/marketplace/packs - success."""
        publisher_id, agent_ids = self._setup_published_agents(client, 2, "createpack")

        response = client.post(
            "/api/marketplace/packs",
            json={
                "publisher_id": publisher_id,
                "name": "New Pack",
                "description": "A new pack of agents",
                "agent_ids": agent_ids,
                "discount_percent": 10,
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["pack"]["name"] == "New Pack"
        assert data["pack"]["agent_count"] == 2

    def test_create_pack_too_few_agents(self, client):
        """POST /api/marketplace/packs - too few agents."""
        publisher_id, agent_ids = self._setup_published_agents(client, 1, "fewagents")

        response = client.post(
            "/api/marketplace/packs",
            json={
                "publisher_id": publisher_id,
                "name": "Small Pack",
                "description": "This description is long enough to be valid",
                "agent_ids": agent_ids,
            },
        )
        assert response.status_code == 400

    def test_create_pack_publisher_not_found(self, client):
        """POST /api/marketplace/packs - publisher not found."""
        response = client.post(
            "/api/marketplace/packs",
            json={
                "publisher_id": "invalid-publisher",
                "name": "Pack",
                "description": "A pack of useful agents",
                "agent_ids": ["a", "b"],
            },
        )
        assert response.status_code == 400

    def test_create_pack_agent_not_found(self, client):
        """POST /api/marketplace/packs - agent not found."""
        pub_response = client.post(
            "/api/marketplace/publishers",
            json={"name": "Pub", "email": "agentnotfound@agent.com"},
        )
        publisher_id = pub_response.get_json()["publisher"]["id"]

        response = client.post(
            "/api/marketplace/packs",
            json={
                "publisher_id": publisher_id,
                "name": "Pack",
                "description": "A pack of useful agents",
                "agent_ids": ["invalid-1", "invalid-2"],
            },
        )
        assert response.status_code == 400

    def test_install_pack_success(self, client):
        """POST /api/marketplace/packs/<id>/install - success."""
        publisher_id, agent_ids = self._setup_published_agents(client, 2, "installpack")

        # Create a pack
        pack_response = client.post(
            "/api/marketplace/packs",
            json={
                "publisher_id": publisher_id,
                "name": "Install Pack",
                "description": "Pack to install",
                "agent_ids": agent_ids,
            },
        )
        pack_id = pack_response.get_json()["pack"]["id"]

        # Install the pack
        response = client.post(
            f"/api/marketplace/packs/{pack_id}/install",
            json={"organization_id": "org-installpack"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["installed_count"] == 2
        assert len(data["installations"]) == 2

    def test_install_pack_missing_org_id(self, client):
        """POST /api/marketplace/packs/<id>/install - missing organization_id."""
        publisher_id, agent_ids = self._setup_published_agents(client, 2, "noorgpack")

        pack_response = client.post(
            "/api/marketplace/packs",
            json={
                "publisher_id": publisher_id,
                "name": "No Org Pack",
                "description": "A collection of agents",
                "agent_ids": agent_ids,
            },
        )
        pack_id = pack_response.get_json()["pack"]["id"]

        response = client.post(
            f"/api/marketplace/packs/{pack_id}/install",
            json={"some_field": "value"},  # Non-empty but without organization_id
        )
        assert response.status_code == 400
        assert "organization_id is required" in response.get_json()["error"]

    def test_install_pack_not_found(self, client):
        """POST /api/marketplace/packs/<id>/install - pack not found."""
        response = client.post(
            "/api/marketplace/packs/invalid-pack-id/install",
            json={"organization_id": "org-notfound"},
        )
        assert response.status_code == 400


# ============================================================================
# TESTS - CATEGORIES ENDPOINT
# ============================================================================

class TestCategoriesAPI:
    """Tests for categories endpoint."""

    def test_list_categories(self, client):
        """GET /api/marketplace/categories."""
        response = client.get("/api/marketplace/categories")
        assert response.status_code == 200
        data = response.get_json()
        assert "count" in data
        assert "categories" in data
        assert data["count"] > 0
        # Check structure
        for cat in data["categories"]:
            assert "id" in cat
            assert "name" in cat


# ============================================================================
# TESTS - SERIALIZERS
# ============================================================================

class TestSerializers:
    """Tests for serializer helper functions."""

    def test_serialize_agent_with_all_fields(self, client, sample_agent):
        """Test serialize_agent with all fields populated."""
        from app.api.marketplace import serialize_agent

        result = serialize_agent(sample_agent)

        assert result["id"] == "agent-123"
        assert result["name"] == "Test Agent"
        assert result["slug"] == "test-agent"
        assert result["description"] == "A test agent for customer service"
        assert result["long_description"] == "Full description of the test agent."
        assert result["version"] == "1.0.0"
        assert result["category"] == "customer_service"
        assert result["tags"] == ["support", "test"]
        assert result["status"] == "published"
        assert result["pricing"]["model"] == "free"
        assert result["pricing"]["price_cents"] == 0
        assert result["pricing"]["currency"] == "EUR"
        assert result["pricing"]["trial_days"] == 0
        assert result["download_count"] == 100
        assert result["active_installations"] == 50
        assert result["average_rating"] == 4.5
        assert result["review_count"] == 20
        assert result["publisher_id"] == "pub-123"
        assert result["created_at"] is not None
        assert result["published_at"] is not None

    def test_serialize_agent_with_none_dates(self):
        """Test serialize_agent with None dates."""
        from app.api.marketplace import serialize_agent

        agent = MarketplaceAgent(
            id="agent-none",
            name="None Dates Agent",
            description="Agent without dates",
            created_at=None,
            published_at=None,
        )

        result = serialize_agent(agent)

        assert result["created_at"] is None
        assert result["published_at"] is None

    def test_serialize_review_with_all_fields(self, sample_review):
        """Test serialize_review with all fields populated."""
        from app.api.marketplace import serialize_review

        result = serialize_review(sample_review)

        assert result["id"] == "review-123"
        assert result["agent_id"] == "agent-123"
        assert result["reviewer_name"] == "John Doe"
        assert result["rating"] == 5
        assert result["title"] == "Excellent agent!"
        assert result["content"] == "This agent works perfectly for our needs."
        assert result["is_verified_purchase"] is True
        assert result["publisher_response"] == "Thank you!"
        assert result["publisher_response_at"] is not None
        assert result["created_at"] is not None

    def test_serialize_review_with_none_dates(self):
        """Test serialize_review with None dates."""
        from app.api.marketplace import serialize_review

        review = AgentReview(
            id="review-none",
            agent_id="agent-123",
            organization_id="org-456",
            reviewer_name="Tester",
            rating=3,
            title="OK",
            content="It's okay.",
            created_at=None,
            publisher_response_at=None,
        )

        result = serialize_review(review)

        assert result["created_at"] is None
        assert result["publisher_response_at"] is None

    def test_serialize_installation_without_agent(self, sample_installation):
        """Test serialize_installation without agent."""
        from app.api.marketplace import serialize_installation

        result = serialize_installation(sample_installation)

        assert result["id"] == "inst-123"
        assert result["agent_id"] == "agent-123"
        assert result["organization_id"] == "org-456"
        assert result["status"] == "active"
        assert result["installed_version"] == "1.0.0"
        assert result["usage_count"] == 50
        assert result["installed_at"] is not None
        assert result["last_used_at"] is not None
        assert result["expires_at"] is not None
        assert "agent" not in result

    def test_serialize_installation_with_agent(self, sample_installation, sample_agent):
        """Test serialize_installation with agent."""
        from app.api.marketplace import serialize_installation

        result = serialize_installation(sample_installation, sample_agent)

        assert "agent" in result
        assert result["agent"]["id"] == "agent-123"
        assert result["agent"]["name"] == "Test Agent"

    def test_serialize_installation_with_none_dates(self):
        """Test serialize_installation with None dates."""
        from app.api.marketplace import serialize_installation

        installation = AgentInstallation(
            id="inst-none",
            agent_id="agent-123",
            organization_id="org-456",
            installed_at=None,
            last_used_at=None,
            expires_at=None,
        )

        result = serialize_installation(installation)

        assert result["installed_at"] is None
        assert result["last_used_at"] is None
        assert result["expires_at"] is None
