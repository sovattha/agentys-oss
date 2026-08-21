# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le use case AnalyzeContactHistory.

pytest tests/application/test_analyze_contact_history.py -v
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock

# Skip tests if pytest-asyncio is not installed
pytest_asyncio = pytest.importorskip("pytest_asyncio")

from app.application.analyze_contact_history import AnalyzeContactHistoryUseCase
from app.domain.entities import ContactContext, DominantTone, TopicInfo
from app.domain.ports import ContactAnalyzerPort
from app.db.models.email import Email


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_email_repository():
    """Mock du repository email."""
    return Mock()


@pytest.fixture
def mock_contact_analyzer():
    """Mock de l'analyzer de contact."""
    analyzer = Mock(spec=ContactAnalyzerPort)
    # Configure analyze as AsyncMock
    analyzer.analyze = AsyncMock()
    return analyzer


@pytest.fixture
def sample_emails():
    """Liste d'emails de test."""
    emails = []
    for i in range(5):
        email = Mock(spec=Email)
        email.id = f"email-{i}"
        email.sender = "john@example.com"
        email.recipients = "user@agentys.com"
        email.cc = None
        email.subject = f"Email {i}"
        email.body_text = f"Body of email {i}"
        email.snippet = f"Snippet {i}"
        email.date = datetime(2026, 1, 15 + i)
        emails.append(email)
    return emails


@pytest.fixture
def sample_contact_context():
    """ContactContext de test."""
    return ContactContext(
        contact_email="john@example.com",
        account_id=1,
        email_count=5,
        dominant_tone=DominantTone.PROFESSIONAL,
        tone_confidence=0.85,
        recurring_topics=[
            TopicInfo(topic="Project updates", frequency=3),
            TopicInfo(topic="Meeting scheduling", frequency=2),
        ],
        relationship_strength=60,
        first_interaction=datetime(2026, 1, 15),
        last_interaction=datetime(2026, 1, 19),
        analysis_duration_ms=1500,
        is_complete=True,
    )


# ============================================================================
# USE CASE TESTS
# ============================================================================


class TestAnalyzeContactHistoryUseCase:
    """Tests pour AnalyzeContactHistoryUseCase."""

    @pytest.mark.asyncio
    async def test_execute_with_valid_contact(
        self,
        mock_email_repository,
        mock_contact_analyzer,
        sample_emails,
        sample_contact_context,
    ):
        """Test d'analyse avec un contact valide ayant des emails."""
        # Setup
        mock_email_repository.get_with_contact.return_value = sample_emails
        mock_contact_analyzer.analyze.return_value = sample_contact_context

        use_case = AnalyzeContactHistoryUseCase(
            email_repository=mock_email_repository,
            contact_analyzer=mock_contact_analyzer,
        )

        # Execute
        result = await use_case.execute(
            contact_email="john@example.com",
            account_id=1,
            limit=20,
        )

        # Verify
        assert result.contact_email == "john@example.com"
        assert result.account_id == 1
        assert result.email_count == 5
        assert result.dominant_tone == DominantTone.PROFESSIONAL
        assert result.tone_confidence == 0.85
        assert len(result.recurring_topics) == 2
        assert result.relationship_strength == 60
        assert result.is_complete is True

        # Verify repository was called
        mock_email_repository.get_with_contact.assert_called_once_with(
            contact_email="john@example.com",
            account_id=1,
            limit=20,
        )

        # Verify analyzer was called
        mock_contact_analyzer.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_no_emails(
        self,
        mock_email_repository,
        mock_contact_analyzer,
    ):
        """Test avec un contact n'ayant aucun email."""
        # Setup
        mock_email_repository.get_with_contact.return_value = []

        use_case = AnalyzeContactHistoryUseCase(
            email_repository=mock_email_repository,
            contact_analyzer=mock_contact_analyzer,
        )

        # Execute
        result = await use_case.execute(
            contact_email="unknown@example.com",
            account_id=1,
        )

        # Verify - should return incomplete context
        assert result.contact_email == "unknown@example.com"
        assert result.account_id == 1
        assert result.email_count == 0
        assert result.is_complete is False

        # Analyzer should NOT be called if no emails
        mock_contact_analyzer.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_with_empty_email_raises_error(
        self,
        mock_email_repository,
        mock_contact_analyzer,
    ):
        """Test avec un email vide lève une erreur."""
        use_case = AnalyzeContactHistoryUseCase(
            email_repository=mock_email_repository,
            contact_analyzer=mock_contact_analyzer,
        )

        with pytest.raises(ValueError, match="cannot be empty"):
            await use_case.execute(
                contact_email="",
                account_id=1,
            )

    @pytest.mark.asyncio
    async def test_execute_with_invalid_email_format_raises_error(
        self,
        mock_email_repository,
        mock_contact_analyzer,
    ):
        """Test avec un email invalide lève une erreur."""
        use_case = AnalyzeContactHistoryUseCase(
            email_repository=mock_email_repository,
            contact_analyzer=mock_contact_analyzer,
        )

        with pytest.raises(ValueError, match="must be a valid email"):
            await use_case.execute(
                contact_email="not-an-email",
                account_id=1,
            )

    @pytest.mark.asyncio
    async def test_execute_with_invalid_limit_raises_error(
        self,
        mock_email_repository,
        mock_contact_analyzer,
    ):
        """Test avec une limite invalide lève une erreur."""
        use_case = AnalyzeContactHistoryUseCase(
            email_repository=mock_email_repository,
            contact_analyzer=mock_contact_analyzer,
        )

        with pytest.raises(ValueError, match="limit must be positive"):
            await use_case.execute(
                contact_email="john@example.com",
                account_id=1,
                limit=0,
            )

    @pytest.mark.asyncio
    async def test_execute_with_invalid_timeout_raises_error(
        self,
        mock_email_repository,
        mock_contact_analyzer,
    ):
        """Test avec un timeout invalide lève une erreur."""
        use_case = AnalyzeContactHistoryUseCase(
            email_repository=mock_email_repository,
            contact_analyzer=mock_contact_analyzer,
        )

        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            await use_case.execute(
                contact_email="john@example.com",
                account_id=1,
                timeout_seconds=-1,
            )


# ============================================================================
# CONTACT CONTEXT ENTITY TESTS
# ============================================================================


class TestContactContextEntity:
    """Tests pour l'entité ContactContext."""

    def test_create_incomplete_context(self):
        """Test de création d'un contexte incomplet."""
        context = ContactContext.create_incomplete(
            contact_email="john@example.com",
            account_id=1,
            email_count=0,
            analysis_duration_ms=100,
        )

        assert context.contact_email == "john@example.com"
        assert context.account_id == 1
        assert context.email_count == 0
        assert context.is_complete is False
        assert context.dominant_tone == DominantTone.PROFESSIONAL  # Default
        assert context.tone_confidence == 0.0
        assert context.recurring_topics == []
        assert context.relationship_strength == 0

    def test_dominant_tone_enum_values(self):
        """Test des valeurs de l'enum DominantTone."""
        assert DominantTone.FORMAL.value == "formal"
        assert DominantTone.FRIENDLY.value == "friendly"
        assert DominantTone.PROFESSIONAL.value == "professional"
        assert DominantTone.CASUAL.value == "casual"

    def test_topic_info_creation(self):
        """Test de création d'un TopicInfo."""
        topic = TopicInfo(
            topic="Project planning",
            frequency=5,
            last_mentioned=datetime(2026, 1, 19),
        )

        assert topic.topic == "Project planning"
        assert topic.frequency == 5
        assert topic.last_mentioned == datetime(2026, 1, 19)


# ============================================================================
# ADAPTER TESTS (with mocked LLM)
# ============================================================================


class TestContactHistoryAdapter:
    """Tests pour le ContactHistoryAdapter avec LLM mocké."""

    @pytest.fixture
    def mock_llm(self):
        """Mock du LLM."""
        llm = Mock()
        llm.is_available.return_value = True
        return llm

    @pytest.fixture
    def mock_llm_response(self):
        """Mock d'une réponse LLM valide."""
        response = Mock()
        response.content = """{
            "dominant_tone": "professional",
            "tone_confidence": 0.85,
            "recurring_topics": [
                {"topic": "Project updates", "frequency": 3},
                {"topic": "Budget review", "frequency": 2}
            ],
            "relationship_strength": 65
        }"""
        return response

    @pytest.mark.asyncio
    async def test_adapter_parses_llm_response(
        self,
        mock_llm,
        mock_llm_response,
        sample_emails,
    ):
        """Test que l'adapter parse correctement la réponse LLM."""
        from app.adapters.analysis import ContactHistoryAdapter

        mock_llm.complete.return_value = mock_llm_response

        adapter = ContactHistoryAdapter(llm=mock_llm)
        result = await adapter.analyze(
            contact_email="john@example.com",
            account_id=1,
            emails=sample_emails,
        )

        assert result.dominant_tone == DominantTone.PROFESSIONAL
        assert result.tone_confidence == 0.85
        assert len(result.recurring_topics) == 2
        assert result.recurring_topics[0].topic == "Project updates"
        assert result.recurring_topics[0].frequency == 3
        assert result.relationship_strength == 65
        assert result.is_complete is True

    @pytest.mark.asyncio
    async def test_adapter_handles_empty_emails(
        self,
        mock_llm,
    ):
        """Test que l'adapter gère une liste vide d'emails."""
        from app.adapters.analysis import ContactHistoryAdapter

        adapter = ContactHistoryAdapter(llm=mock_llm)
        result = await adapter.analyze(
            contact_email="john@example.com",
            account_id=1,
            emails=[],
        )

        assert result.email_count == 0
        assert result.is_complete is False
        # LLM should not be called for empty emails
        mock_llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_adapter_handles_invalid_email(
        self,
        mock_llm,
    ):
        """Test que l'adapter rejette un email invalide."""
        from app.adapters.analysis import ContactHistoryAdapter

        adapter = ContactHistoryAdapter(llm=mock_llm)

        with pytest.raises(ValueError, match="Invalid contact_email"):
            await adapter.analyze(
                contact_email="not-valid",
                account_id=1,
                emails=[],
            )

    @pytest.mark.asyncio
    async def test_adapter_handles_llm_error(
        self,
        mock_llm,
        sample_emails,
    ):
        """Test que l'adapter gère les erreurs LLM gracieusement."""
        from app.adapters.analysis import ContactHistoryAdapter

        mock_llm.complete.return_value = None

        adapter = ContactHistoryAdapter(llm=mock_llm)
        result = await adapter.analyze(
            contact_email="john@example.com",
            account_id=1,
            emails=sample_emails,
        )

        # Should return incomplete context on LLM error
        assert result.is_complete is False

    @pytest.mark.asyncio
    async def test_adapter_handles_invalid_json(
        self,
        mock_llm,
        sample_emails,
    ):
        """Test que l'adapter gère le JSON invalide."""
        from app.adapters.analysis import ContactHistoryAdapter

        response = Mock()
        response.content = "This is not JSON"
        mock_llm.complete.return_value = response

        adapter = ContactHistoryAdapter(llm=mock_llm)
        result = await adapter.analyze(
            contact_email="john@example.com",
            account_id=1,
            emails=sample_emails,
        )

        # Should return incomplete context on parse error
        assert result.is_complete is False

    @pytest.mark.asyncio
    async def test_adapter_handles_markdown_json(
        self,
        mock_llm,
        sample_emails,
    ):
        """Test que l'adapter gère le JSON dans un bloc markdown."""
        from app.adapters.analysis import ContactHistoryAdapter

        response = Mock()
        response.content = """```json
{
    "dominant_tone": "friendly",
    "tone_confidence": 0.9,
    "recurring_topics": [],
    "relationship_strength": 80
}
```"""
        mock_llm.complete.return_value = response

        adapter = ContactHistoryAdapter(llm=mock_llm)
        result = await adapter.analyze(
            contact_email="john@example.com",
            account_id=1,
            emails=sample_emails,
        )

        assert result.dominant_tone == DominantTone.FRIENDLY
        assert result.tone_confidence == 0.9
        assert result.relationship_strength == 80
        assert result.is_complete is True

    def test_adapter_is_available(self, mock_llm):
        """Test de la méthode is_available."""
        from app.adapters.analysis import ContactHistoryAdapter

        mock_llm.is_available.return_value = True
        adapter = ContactHistoryAdapter(llm=mock_llm)

        assert adapter.is_available() is True

        mock_llm.is_available.return_value = False
        assert adapter.is_available() is False
