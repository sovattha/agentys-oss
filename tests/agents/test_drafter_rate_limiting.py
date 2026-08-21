"""Tests pour le rate limiting du DrafterAgent.

TDD Tests - Story 5-1 Task 5
"""

import pytest
from unittest.mock import MagicMock, patch

from app.domain.entities.draft_generation import (
    DraftStatus,
    DraftRequest,
    DraftResult,
)
from app.domain.exceptions import LLMRateLimitError


@pytest.fixture
def mock_llm():
    """Mock LLM pour tests."""
    mock = MagicMock()
    mock.name = "claude"
    mock.model = "claude-sonnet-4-20250514"

    mock_response = MagicMock()
    mock_response.content = "Thank you for your message."
    mock_response.input_tokens = 500
    mock_response.output_tokens = 50
    mock_response.model = "claude-sonnet-4-20250514"

    mock.complete.return_value = mock_response
    return mock


@pytest.fixture
def sample_request():
    """Requête minimale pour tests."""
    return DraftRequest(
        email_content="Hi, how are you?",
    )


class TestDrafterAgentRateLimiting:
    """Tests pour la gestion du rate limiting."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_drafter_has_max_retries_attribute(
        self, mock_kb, mock_get_container, mock_llm
    ):
        """Vérifie que DrafterAgent a un attribut max_retries."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        assert hasattr(agent, "max_retries")
        assert agent.max_retries == 3

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_with_retry_success_first_attempt(
        self, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie le succès au premier essai."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        result = agent.draft_with_retry(sample_request)

        assert isinstance(result, DraftResult)
        assert result.status == DraftStatus.COMPLETED
        assert mock_llm.complete.call_count == 1

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    @patch("time.sleep")
    def test_draft_with_retry_retries_on_rate_limit(
        self, mock_sleep, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie le retry après un rate limit."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        # Premier appel: rate limit, deuxième: succès
        mock_response = MagicMock()
        mock_response.content = "Success after retry"
        mock_response.input_tokens = 500
        mock_response.output_tokens = 50
        mock_response.model = "claude-sonnet-4-20250514"

        mock_llm.complete.side_effect = [
            LLMRateLimitError(provider="claude"),
            mock_response,
        ]

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        result = agent.draft_with_retry(sample_request)

        assert result.status == DraftStatus.COMPLETED
        assert result.content == "Success after retry"
        assert mock_llm.complete.call_count == 2
        mock_sleep.assert_called_once()  # Backoff appelé une fois

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    @patch("time.sleep")
    def test_draft_with_retry_exponential_backoff(
        self, mock_sleep, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie le backoff exponentiel."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        # Trois rate limits puis succès
        mock_response = MagicMock()
        mock_response.content = "Success"
        mock_response.input_tokens = 500
        mock_response.output_tokens = 50
        mock_response.model = "claude-sonnet-4-20250514"

        mock_llm.complete.side_effect = [
            LLMRateLimitError(provider="claude"),
            LLMRateLimitError(provider="claude"),
            mock_response,
        ]

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        result = agent.draft_with_retry(sample_request)

        assert result.status == DraftStatus.COMPLETED
        # Backoff: 0.5 * 2^0 = 0.5, puis 0.5 * 2^1 = 1.0
        assert mock_sleep.call_count == 2
        # Vérifie l'ordre croissant des backoffs
        calls = mock_sleep.call_args_list
        assert calls[0][0][0] < calls[1][0][0]

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    @patch("time.sleep")
    def test_draft_with_retry_max_retries_exceeded(
        self, mock_sleep, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie le comportement après max_retries dépassé."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        # Tous les appels échouent
        mock_llm.complete.side_effect = LLMRateLimitError(provider="claude")

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        agent.max_retries = 3
        result = agent.draft_with_retry(sample_request)

        assert result.status == DraftStatus.RATE_LIMITED
        assert result.was_rate_limited() is True
        assert mock_llm.complete.call_count == 3

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    @patch("time.sleep")
    def test_draft_with_retry_tracks_retry_count(
        self, mock_sleep, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie que le retry_count est enregistré."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        # Deux rate limits puis succès
        mock_response = MagicMock()
        mock_response.content = "Success"
        mock_response.input_tokens = 500
        mock_response.output_tokens = 50
        mock_response.model = "claude-sonnet-4-20250514"

        mock_llm.complete.side_effect = [
            LLMRateLimitError(provider="claude"),
            LLMRateLimitError(provider="claude"),
            mock_response,
        ]

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        result = agent.draft_with_retry(sample_request)

        assert result.retry_count == 2  # 2 retries avant succès

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    @patch("time.sleep")
    def test_draft_with_retry_uses_retry_after_header(
        self, mock_sleep, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie l'utilisation du header retry-after."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        # Rate limit avec retry_after
        mock_response = MagicMock()
        mock_response.content = "Success"
        mock_response.input_tokens = 500
        mock_response.output_tokens = 50
        mock_response.model = "claude-sonnet-4-20250514"

        mock_llm.complete.side_effect = [
            LLMRateLimitError(provider="claude", retry_after=5),
            mock_response,
        ]

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        agent.draft_with_retry(sample_request)

        # Le backoff doit utiliser retry_after (5) au lieu du calcul exponentiel
        mock_sleep.assert_called_once_with(5)

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_with_retry_handles_other_exceptions(
        self, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie que les autres exceptions remontent."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        # Exception non rate-limit
        mock_llm.complete.side_effect = ValueError("Some other error")

        from app.agents import DrafterAgent

        agent = DrafterAgent()

        with pytest.raises(ValueError, match="Some other error"):
            agent.draft_with_retry(sample_request)


class TestDrafterAgentStreamWithRetry:
    """Tests pour le streaming avec retry."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    @patch("time.sleep")
    def test_draft_stream_with_retry_on_rate_limit(
        self, mock_sleep, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie le retry du streaming après rate limit."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        from app.domain.ports.llm_port import LLMStreamChunk

        # Premier appel échoue, deuxième réussit
        def stream_success():
            yield LLMStreamChunk(
                text="Hello",
                input_tokens=100,
                output_tokens_so_far=1,
                is_final=False,
                model="claude",
            )
            yield LLMStreamChunk(
                text="",
                input_tokens=100,
                output_tokens_so_far=1,
                is_final=True,
                model="claude",
            )

        call_count = [0]

        def stream_with_retry(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise LLMRateLimitError(provider="claude")
            return stream_success()

        mock_llm.stream.side_effect = stream_with_retry

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        chunks = list(agent.draft_stream_with_retry(sample_request))

        assert len(chunks) > 0
        assert mock_llm.stream.call_count == 2
        mock_sleep.assert_called_once()
