# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests pour DrafterAgent.draft_stream.

TDD Tests - Story 5-1 Task 3
"""

import pytest
from unittest.mock import MagicMock, patch

from app.domain.entities.draft_generation import (
    DraftRequest,
    StreamingDraftChunk,
)
from app.domain.entities.context_analysis import (
    ContextAnalysisResult,
    RelationshipType,
)
from app.domain.ports.llm_port import LLMStreamChunk


@pytest.fixture
def mock_stream_generator():
    """Générateur de mock stream chunks."""
    def _generator():
        chunks = [
            LLMStreamChunk(text="Thank ", input_tokens=500, output_tokens_so_far=1, is_final=False, model="claude"),
            LLMStreamChunk(text="you ", input_tokens=500, output_tokens_so_far=2, is_final=False, model="claude"),
            LLMStreamChunk(text="for ", input_tokens=500, output_tokens_so_far=3, is_final=False, model="claude"),
            LLMStreamChunk(text="your ", input_tokens=500, output_tokens_so_far=4, is_final=False, model="claude"),
            LLMStreamChunk(text="message.", input_tokens=500, output_tokens_so_far=5, is_final=False, model="claude"),
            LLMStreamChunk(text="", input_tokens=500, output_tokens_so_far=5, is_final=True, model="claude"),
        ]
        for chunk in chunks:
            yield chunk
    return _generator


@pytest.fixture
def mock_llm(mock_stream_generator):
    """Mock LLM pour tests sans appel API réel."""
    mock = MagicMock()
    mock.name = "claude"
    mock.model = "claude-sonnet-4-20250514"

    # Mock complete pour les autres tests
    mock_response = MagicMock()
    mock_response.content = "Thank you for your message."
    mock_response.input_tokens = 500
    mock_response.output_tokens = 50
    mock_response.model = "claude-sonnet-4-20250514"
    mock.complete.return_value = mock_response

    # Mock stream
    mock.stream.return_value = mock_stream_generator()

    return mock


@pytest.fixture
def sample_request():
    """Requête minimale pour tests."""
    return DraftRequest(
        email_content="Hi, how are you?",
    )


@pytest.fixture
def sample_request_with_context():
    """Requête avec contexte pour tests."""
    context = ContextAnalysisResult(
        contact_context="Professional colleague",
        style_hints=["formal", "concise"],
        relationship_type=RelationshipType.COLLEAGUE,
        confidence=0.85,
    )
    return DraftRequest(
        email_content="Meeting request",
        context_result=context,
        instructions="Be professional",
    )


class TestDrafterAgentStream:
    """Tests pour DrafterAgent.draft_stream."""

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_stream_yields_chunks(
        self, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """draft_stream() génère des StreamingDraftChunk."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        chunks = list(agent.draft_stream(sample_request))

        assert len(chunks) > 0
        assert all(isinstance(c, StreamingDraftChunk) for c in chunks)

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_stream_accumulates_text(
        self, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie que le texte s'accumule correctement."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        chunks = list(agent.draft_stream(sample_request))

        # Le dernier chunk non-final doit avoir le texte complet accumulé
        final_chunk = [c for c in chunks if c.is_final][-1]
        assert "Thank you for your message" in final_chunk.accumulated_text

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_stream_final_chunk_is_marked(
        self, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie que le dernier chunk est marqué is_final=True."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        chunks = list(agent.draft_stream(sample_request))

        final_chunks = [c for c in chunks if c.is_final]
        assert len(final_chunks) == 1
        assert final_chunks[0].progress_percent == 100.0

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_stream_progress_increases(
        self, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie que le progress_percent augmente."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        chunks = list(agent.draft_stream(sample_request))

        # Le progress doit augmenter ou rester constant
        prev_progress = 0.0
        for chunk in chunks:
            assert chunk.progress_percent >= prev_progress
            prev_progress = chunk.progress_percent

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_stream_chunk_index_increments(
        self, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie que chunk_index s'incrémente."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        chunks = list(agent.draft_stream(sample_request))

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_stream_with_context(
        self, mock_kb, mock_get_container, mock_llm, sample_request_with_context
    ):
        """Vérifie le streaming avec contexte."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        chunks = list(agent.draft_stream(sample_request_with_context))

        assert len(chunks) > 0
        # Le contexte devrait être utilisé dans le prompt
        mock_llm.stream.assert_called_once()
        call_kwargs = mock_llm.stream.call_args[1]
        assert "system" in call_kwargs

    @patch("app.agents.get_container")
    @patch("app.agents.load_knowledge_base")
    def test_draft_stream_tracks_tokens(
        self, mock_kb, mock_get_container, mock_llm, sample_request
    ):
        """Vérifie que les tokens sont suivis."""
        mock_kb.return_value = "Knowledge base content"
        mock_container = MagicMock()
        mock_container.llm = mock_llm
        mock_container.llm_drafting = mock_llm
        mock_container.llm_label = mock_llm
        mock_container.token_usage = MagicMock()
        mock_get_container.return_value = mock_container

        from app.agents import DrafterAgent

        agent = DrafterAgent()
        chunks = list(agent.draft_stream(sample_request))

        final_chunk = [c for c in chunks if c.is_final][-1]
        assert final_chunk.tokens_so_far > 0
