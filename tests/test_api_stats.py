# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'endpoint GET /api/stats.

Ces tests vérifient:
- Réponse nominale avec toutes les composantes
- Format JSON correct avec les clés attendues
- Gestion des dépendances via Container DI
- Edge cases (composants vides, valeurs nulles)
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

# Skip all tests if flask_cors is not available
pytest.importorskip("flask_cors")


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def app():
    """Application Flask de test."""
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Client de test Flask."""
    return app.test_client()


@pytest.fixture(autouse=True)
def _mock_stats_account_id():
    """Route /api/stats scope les drafts via _resolve_account_id_for_user()
    (routes_health.py:426). Sans compte actif en CI, all_drafts = []. Mock
    pour que les tests voient leurs drafts injectés."""
    with patch("app.api.routes_health._rh._resolve_account_id_for_user",
               return_value=1):
        yield


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _create_mock_draft(
    timestamp: str = "2025-01-02T10:00:00",
    status: str = "SENT",
    category: str = "SUPPORT",
) -> Mock:
    """Create a mock draft with configurable attributes."""
    mock_draft = Mock()
    mock_draft.timestamp = timestamp
    mock_draft.status = status
    mock_draft.category = category
    return mock_draft


def _create_mock_container(
    drafts: list = None,
    learning_stats: dict = None,
    token_total: int = 1000,
    token_model: str = "claude-3-5-sonnet",
    token_history: list = None,
    learning_stats_as_dict: bool = False,
) -> Mock:
    """Create a mock container with all required dependencies.

    Args:
        learning_stats_as_dict: If True, return learning_stats as raw dict
            instead of wrapping in SimpleNamespace. Used to test the else
            branch of hasattr(__dict__) check.
    """
    mock_container = Mock()

    # Draft history mock
    mock_draft_history = Mock()
    mock_draft_history.get_all.return_value = drafts or []
    mock_draft_history.get_all_for_account.return_value = drafts or []
    mock_container.get_draft_history.return_value = mock_draft_history

    # Token counter mock
    mock_token_counter = Mock()
    mock_token_counter.get_total.return_value = token_total
    mock_token_counter.get_model.return_value = token_model
    mock_token_counter.get_breakdown.return_value = {}
    mock_token_counter.get_history.return_value = token_history or []
    mock_container.get_token_counter.return_value = mock_token_counter

    # Learning service mock
    mock_learning_service = Mock()
    stats_data = learning_stats or {"total_feedback": 0, "patterns_learned": 0}
    if learning_stats_as_dict:
        mock_learning_service.get_stats.return_value = stats_data
    else:
        from types import SimpleNamespace
        mock_learning_service.get_stats.return_value = SimpleNamespace(**stats_data)
    mock_container.get_learning_service.return_value = mock_learning_service

    return mock_container


def _create_mock_cost_manager(cost_stats: dict = None) -> Mock:
    """Create a mock cost manager."""
    mock_cost_manager = Mock()
    mock_cost_manager.get_current_month_stats.return_value = cost_stats or {
        "total_cost": 0.0,
        "total_requests": 0,
    }
    return mock_cost_manager


# ============================================================================
# TESTS - STATS ENDPOINT
# ============================================================================


class TestStatsEndpoint:
    """Tests pour GET /api/stats."""

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_returns_200_with_valid_json(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats endpoint retourne 200 avec JSON valide."""
        mock_get_container.return_value = _create_mock_container()
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")

        assert response.status_code == 200
        assert response.content_type == "application/json"
        data = response.get_json()
        assert data is not None

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_contains_all_required_keys(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats contient toutes les clés requises."""
        mock_get_container.return_value = _create_mock_container()
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        required_keys = ["drafts", "learning", "costs", "tokens", "timestamp"]
        for key in required_keys:
            assert key in data, f"Clé manquante: {key}"

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_drafts_structure(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats drafts a la structure attendue."""
        drafts = [
            _create_mock_draft(
                timestamp=datetime.now().strftime("%Y-%m-%d") + "T10:00:00",
                status="SENT",
                category="SUPPORT",
            ),
            _create_mock_draft(
                timestamp="2025-01-01T10:00:00",
                status="PENDING",
                category="SALES",
            ),
        ]
        mock_get_container.return_value = _create_mock_container(drafts=drafts)
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert "drafts" in data
        draft_stats = data["drafts"]
        assert "total" in draft_stats
        assert "today" in draft_stats
        assert "by_status" in draft_stats
        assert "by_category" in draft_stats
        assert draft_stats["total"] == 2
        assert draft_stats["by_status"]["SENT"] == 1
        assert draft_stats["by_status"]["PENDING"] == 1
        assert draft_stats["by_category"]["SUPPORT"] == 1
        assert draft_stats["by_category"]["SALES"] == 1

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_tokens_structure(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats tokens a la structure attendue."""
        mock_get_container.return_value = _create_mock_container(
            token_total=5000,
            token_model="claude-3-5-sonnet",
            token_history=[{"timestamp": "2025-01-02", "tokens": 1000}],
        )
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert "tokens" in data
        token_stats = data["tokens"]
        assert "total_tokens" in token_stats
        assert "model" in token_stats
        assert "breakdown" in token_stats
        assert token_stats["total_tokens"] == 5000
        assert token_stats["model"] == "claude-3-5-sonnet"

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_with_empty_data(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats gère correctement les données vides."""
        mock_get_container.return_value = _create_mock_container(
            drafts=[],
            learning_stats={},
            token_total=0,
            token_history=[],
        )
        mock_get_cost_manager.return_value = _create_mock_cost_manager(
            cost_stats={"total_cost": 0.0, "total_requests": 0}
        )

        response = client.get("/api/stats")
        data = response.get_json()

        assert response.status_code == 200
        assert data["drafts"]["total"] == 0
        assert data["drafts"]["today"] == 0
        assert data["tokens"]["total_tokens"] == 0

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_timestamp_format(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats timestamp est au format ISO."""
        mock_get_container.return_value = _create_mock_container()
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert "timestamp" in data
        timestamp = data["timestamp"]
        # Verify ISO format by parsing
        try:
            datetime.fromisoformat(timestamp)
        except ValueError:
            pytest.fail(f"Timestamp '{timestamp}' n'est pas au format ISO")

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_costs_included(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats inclut les statistiques de coûts."""
        cost_stats = {
            "total_cost": 12.50,
            "total_requests": 250,
            "average_cost_per_request": 0.05,
        }
        mock_get_container.return_value = _create_mock_container()
        mock_get_cost_manager.return_value = _create_mock_cost_manager(
            cost_stats=cost_stats
        )

        response = client.get("/api/stats")
        data = response.get_json()

        assert "costs" in data
        assert data["costs"]["total_cost"] == 12.50
        assert data["costs"]["total_requests"] == 250

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_learning_included(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats inclut les statistiques d'apprentissage."""
        learning_stats = {
            "total_feedback": 50,
            "patterns_learned": 15,
            "accuracy": 0.85,
        }
        mock_get_container.return_value = _create_mock_container(
            learning_stats=learning_stats
        )
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert "learning" in data
        assert data["learning"]["total_feedback"] == 50
        assert data["learning"]["patterns_learned"] == 15


# ============================================================================
# TESTS - STATS ENDPOINT EDGE CASES
# ============================================================================


class TestStatsEndpointEdgeCases:
    """Tests edge cases pour GET /api/stats."""

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_drafts_with_null_status_and_category(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats gère les drafts avec status/category None (fallback UNKNOWN)."""
        # Draft avec status et category None
        mock_draft = Mock()
        mock_draft.timestamp = "2025-01-02T10:00:00"
        mock_draft.status = None
        mock_draft.category = None

        mock_get_container.return_value = _create_mock_container(drafts=[mock_draft])
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert response.status_code == 200
        assert data["drafts"]["total"] == 1
        assert "UNKNOWN" in data["drafts"]["by_status"]
        assert data["drafts"]["by_status"]["UNKNOWN"] == 1
        assert "UNKNOWN" in data["drafts"]["by_category"]
        assert data["drafts"]["by_category"]["UNKNOWN"] == 1

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_with_learning_stats_as_dict(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats gère learning_stats retourné comme dict (sans __dict__)."""
        learning_stats = {"total_feedback": 25, "patterns_learned": 5}
        mock_get_container.return_value = _create_mock_container(
            learning_stats=learning_stats,
            learning_stats_as_dict=True,
            token_total=0,
            token_model="test-model",
        )
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert response.status_code == 200
        assert "learning" in data
        # Le dict est retourné tel quel (branche else du hasattr)
        assert data["learning"]["total_feedback"] == 25
        assert data["learning"]["patterns_learned"] == 5

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_with_large_number_of_drafts(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats gère correctement un grand nombre de drafts."""
        # Créer 1000 drafts avec différents status/categories
        drafts = []
        statuses = ["SENT", "PENDING", "DRAFT", "FAILED"]
        categories = ["SUPPORT", "SALES", "BILLING", "TECHNICAL"]
        today = datetime.now().strftime("%Y-%m-%d")

        for i in range(1000):
            mock_draft = Mock()
            # 200 drafts aujourd'hui (indices 0-199)
            if i < 200:
                mock_draft.timestamp = f"{today}T{10 + (i % 12):02d}:00:00"
            else:
                mock_draft.timestamp = "2024-12-01T10:00:00"
            mock_draft.status = statuses[i % len(statuses)]
            mock_draft.category = categories[i % len(categories)]
            drafts.append(mock_draft)

        mock_get_container.return_value = _create_mock_container(drafts=drafts)
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert response.status_code == 200
        assert data["drafts"]["total"] == 1000
        assert data["drafts"]["today"] == 200
        # Vérifier répartition équitable des status (250 chaque)
        for status in statuses:
            assert data["drafts"]["by_status"][status] == 250
        # Vérifier répartition équitable des categories (250 chaque)
        for category in categories:
            assert data["drafts"]["by_category"][category] == 250

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_container_raises_exception(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats propage l'exception si get_container échoue."""
        mock_get_container.side_effect = RuntimeError("Container initialization failed")

        # En mode TESTING, Flask propage les exceptions
        response = client.get("/api/stats")
        assert response.status_code == 500

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_cost_manager_raises_exception(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats propage l'exception si get_cost_manager échoue."""
        mock_get_container.return_value = _create_mock_container()
        mock_get_cost_manager.side_effect = RuntimeError("Cost manager unavailable")

        # En mode TESTING, Flask propage les exceptions
        response = client.get("/api/stats")
        assert response.status_code == 500

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_draft_history_raises_exception(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats propage l'exception si draft_history.get_all_for_account() échoue."""
        mock_container = Mock()
        mock_draft_history = Mock()
        mock_draft_history.get_all.side_effect = Exception("Database connection failed")
        mock_draft_history.get_all_for_account.side_effect = Exception("Database connection failed")
        mock_container.get_draft_history.return_value = mock_draft_history

        mock_get_container.return_value = mock_container
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        # En mode TESTING, Flask propage les exceptions
        response = client.get("/api/stats")
        assert response.status_code == 500

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_with_zero_tokens(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats gère correctement zero tokens."""
        mock_get_container.return_value = _create_mock_container(
            token_total=0,
            token_model="",
            token_history=[],
        )
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert response.status_code == 200
        assert data["tokens"]["total_tokens"] == 0
        assert data["tokens"]["model"] == ""
        assert data["tokens"]["breakdown"] == []

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_with_max_token_history(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats limite l'historique des tokens à 10 entrées."""
        # L'endpoint appelle get_history(10) donc on vérifie que le mock respecte cela
        token_history = [
            {"timestamp": f"2025-01-{i:02d}", "tokens": i * 100}
            for i in range(1, 11)  # 10 entries
        ]
        mock_get_container.return_value = _create_mock_container(
            token_history=token_history
        )
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert response.status_code == 200
        assert len(data["tokens"]["breakdown"]) == 10

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_with_negative_costs(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats retourne des coûts négatifs (crédits/remboursements)."""
        cost_stats = {
            "total_cost": -5.00,
            "total_requests": 100,
            "credits_applied": 10.00,
        }
        mock_get_container.return_value = _create_mock_container()
        mock_get_cost_manager.return_value = _create_mock_cost_manager(
            cost_stats=cost_stats
        )

        response = client.get("/api/stats")
        data = response.get_json()

        assert response.status_code == 200
        assert data["costs"]["total_cost"] == -5.00

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_drafts_all_same_status(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats gère correctement tous les drafts avec le même status."""
        drafts = [
            _create_mock_draft(status="SENT", category="SUPPORT")
            for _ in range(5)
        ]
        mock_get_container.return_value = _create_mock_container(drafts=drafts)
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert response.status_code == 200
        assert data["drafts"]["by_status"] == {"SENT": 5}
        assert data["drafts"]["by_category"] == {"SUPPORT": 5}

    @patch("app.infrastructure.cost_manager.get_cost_manager")
    @patch("app.api.routes_helpers.get_container")
    def test_stats_with_very_long_model_name(
        self, mock_get_container, mock_get_cost_manager, client
    ):
        """Stats gère correctement un nom de modèle très long."""
        long_model_name = "claude-3-5-sonnet-20241022-with-extended-context-window-v2"
        mock_get_container.return_value = _create_mock_container(
            token_model=long_model_name
        )
        mock_get_cost_manager.return_value = _create_mock_cost_manager()

        response = client.get("/api/stats")
        data = response.get_json()

        assert response.status_code == 200
        assert data["tokens"]["model"] == long_model_name
