# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour POST /api/emails/compose - Compose new email with AI assistance.

Story 5-4: Compose New Email
pytest tests/test_api_compose_email.py -v
"""

from dataclasses import dataclass, field
from enum import Enum
from unittest.mock import MagicMock

import pytest




def _auth_headers(email: str = "test@agentys.app", sub: str = "12345") -> dict:
    """Mint a JWT Bearer header.

    /api/refine-text and /api/emails/compose are @require_auth gated
    (audit-2026-05-11). Tests hitting these endpoints must include a token.
    """
    import time as _time
    import jwt as _pyjwt
    from app.api.auth import JWT_ALGORITHM, JWT_SECRET
    token = _pyjwt.encode(
        {
            "sub": sub,
            "email": email,
            "iat": int(_time.time()),
            "exp": int(_time.time()) + 3600,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}

class MockOrchestrationStatus(Enum):
    """Mock OrchestrationStatus."""
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class MockDraftResult:
    """DraftResult mock pour les tests."""

    content: str = "Generated email content"
    confidence: float = 0.85
    status: str = "completed"

    def to_dict(self):
        return {
            "content": self.content,
            "confidence": self.confidence,
            "status": self.status,
        }


@dataclass
class MockOrchestrationResult:
    """OrchestrationResult mock pour les tests."""

    final_draft: MockDraftResult = field(default_factory=MockDraftResult)
    status: MockOrchestrationStatus = MockOrchestrationStatus.COMPLETED
    total_duration_ms: int = 1500
    error_message: str = None

    def is_successful(self):
        return self.status == MockOrchestrationStatus.COMPLETED and self.final_draft is not None

    def get_iteration_count(self):
        return 1

    def get_best_score(self):
        return 85

    def was_validated(self):
        return True

    def to_dict(self):
        return {
            "status": self.status.value,
            "total_duration_ms": self.total_duration_ms,
        }


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
def mock_container_llm_label():
    """Ensure container.llm_label returns a mock LLM.

    The compose endpoint calls container.llm_label (not container.llm),
    so the global mock_container_llm autouse fixture from conftest.py
    does not cover this code path.
    """
    from app.infrastructure.container import get_container
    from app.domain.ports.llm_port import LLMResponse

    container = get_container()
    mock_llm = MagicMock()
    mock_llm.complete.return_value = LLMResponse(
        content="Generated email content",
        input_tokens=10,
        output_tokens=20,
        model="mock-haiku",
    )
    # Route /emails/compose utilise container.llm_drafting (cf routes_misc.py:490),
    # pas llm_label. On stub les deux pour compat descendante si le code rechange.
    container._llm_label = mock_llm
    container._llm_drafting = mock_llm
    yield mock_llm
    container._llm_label = None
    container._llm_drafting = None


@pytest.fixture
def mock_orchestrator():
    """Mock DraftOrchestrator."""
    mock_result = MockOrchestrationResult()

    orchestrator = MagicMock()
    orchestrator.orchestrate.return_value = mock_result
    return orchestrator


class TestComposeEmailEndpoint:
    """Tests pour POST /api/emails/compose."""

    def test_compose_without_history(self, client):
        """Test composition sans historique de contact."""
        response = client.post(
            "/api/emails/compose",
            json={
                "to": "new@example.com",
                "subject": "Hello",
                "instructions": "Write a friendly greeting",
                "use_history": False,
            },
            headers=_auth_headers(),
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "final_draft" in data

    def test_compose_with_history(self, client):
        """Test composition avec historique existant."""
        response = client.post(
            "/api/emails/compose",
            json={
                "to": "known@example.com",
                "subject": "Follow-up",
                "instructions": "Reference our previous discussion",
                "use_history": True,
            },
            headers=_auth_headers(),
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

    def test_compose_invalid_email_format(self, client):
        """Test avec format email invalide."""
        response = client.post(
            "/api/emails/compose",
            json={
                "to": "invalid-email",
                "subject": "Test",
                "instructions": "Write something",
            },
            headers=_auth_headers(),
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_compose_missing_subject(self, client):
        """Test avec sujet manquant."""
        response = client.post(
            "/api/emails/compose",
            json={
                "to": "test@example.com",
                "instructions": "Write something",
            },
            headers=_auth_headers(),
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_compose_missing_to(self, client):
        """Test avec destinataire manquant."""
        response = client.post(
            "/api/emails/compose",
            json={
                "subject": "Test",
                "instructions": "Write something",
            },
            headers=_auth_headers(),
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_compose_empty_instructions_allowed(self, client):
        """Test avec instructions vides (autorisé)."""
        response = client.post(
            "/api/emails/compose",
            json={
                "to": "test@example.com",
                "subject": "Quick hello",
                "instructions": "",
            },
            headers=_auth_headers(),
        )

        assert response.status_code == 200

    def test_compose_returns_final_draft(self, client):
        """Test que la réponse inclut le brouillon généré."""
        response = client.post(
            "/api/emails/compose",
            json={
                "to": "test@example.com",
                "subject": "Test Subject",
                "instructions": "Write a professional email",
            },
            headers=_auth_headers(),
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "final_draft" in data
        assert "content" in data["final_draft"]

    def test_compose_llm_failure(self, client, mock_container_llm_label):
        """Test gestion d'échec de la génération LLM."""
        mock_container_llm_label.complete.side_effect = Exception("Generation failed")

        response = client.post(
            "/api/emails/compose",
            json={
                "to": "test@example.com",
                "subject": "Test",
                "instructions": "Write something",
            },
            headers=_auth_headers(),
        )

        assert response.status_code == 500
        data = response.get_json()
        assert "error" in data
