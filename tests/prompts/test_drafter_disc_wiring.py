# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Test d'intégration — vérifie que DrafterAgent consomme bien RecipientProfile.

Lesson 2026-04-17 : phase 2 (persistence DB) shippée sans wiring du read path
côté Drafter. Ce test prouve bout-en-bout que le profil arrive dans le system
prompt. Si un futur refactor casse le wiring, ce test échoue immédiatement.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.agents import DrafterAgent
from app.domain.entities.draft_generation import DraftRequest
from app.domain.entities.recipient_profile import (
    DISCScores,
    DISCType,
    RecipientProfile,
)


@pytest.fixture
def reliable_profile():
    return RecipientProfile(
        email="bob@example.com",
        disc=DISCType.CONSCIENTIOUSNESS,
        disc_scores=DISCScores(0.2, 0.2, 0.2, 0.6),
        confidence=0.8,
        sample_size=20,
    )


def _build_mock_llm_response():
    resp = MagicMock()
    resp.content = '{"draft": "Merci, je regarde ça.", "classification": "Action", "priority": 50}'
    resp.input_tokens = 100
    resp.output_tokens = 20
    return resp


class TestDISCReadPathWired:
    """Les 3 sites get_drafter_system_prompt_with_context_split doivent recevoir recipient_profile."""

    def test_resolve_recipient_profile_returns_profile_when_persisted(self, reliable_profile):
        """Helper _resolve_recipient_profile renvoie le profil via le repository."""
        agent = DrafterAgent(account_id=1, knowledge_base="kb")
        request = DraftRequest(
            email_content="Merci, quelle est la deadline ?",
            recipient_email="bob@example.com",
            account_id=1,
        )

        with patch("app.db.repositories.recipient_profile_repository.RecipientProfileRepository") as repo_cls:
            repo_instance = MagicMock()
            repo_instance.get.return_value = reliable_profile
            repo_cls.return_value = repo_instance
            with patch("app.db.database.get_db_session") as gds:
                gds.return_value.__enter__.return_value = MagicMock()
                gds.return_value.__exit__.return_value = False
                result = agent._resolve_recipient_profile(request)

        assert result is reliable_profile
        repo_instance.get.assert_called_once_with(1, "bob@example.com")

    def test_resolve_returns_none_when_no_account_id(self):
        agent = DrafterAgent(account_id=None, knowledge_base="kb")
        request = DraftRequest(
            email_content="hello",
            recipient_email="bob@example.com",
            account_id=None,
        )
        with patch("app.multi_accounts.get_current_account", return_value=None):
            assert agent._resolve_recipient_profile(request) is None

    def test_resolve_extracts_recipient_from_conversation_history(self, reliable_profile):
        """Quand request.recipient_email est vide, fallback sur conversation_history."""
        agent = DrafterAgent(account_id=1, knowledge_base="kb")
        request = DraftRequest(
            email_content="hello",
            recipient_email=None,
            account_id=1,
            user_email="me@example.com",
            conversation_history=[
                {"sender": "me@example.com", "body": "..."},
                {"sender": "bob@example.com", "body": "..."},
            ],
        )
        with patch("app.db.repositories.recipient_profile_repository.RecipientProfileRepository") as repo_cls:
            repo_instance = MagicMock()
            repo_instance.get.return_value = reliable_profile
            repo_cls.return_value = repo_instance
            with patch("app.db.database.get_db_session") as gds:
                gds.return_value.__enter__.return_value = MagicMock()
                gds.return_value.__exit__.return_value = False
                result = agent._resolve_recipient_profile(request)
        assert result is reliable_profile
        repo_instance.get.assert_called_once_with(1, "bob@example.com")

    def test_profile_reaches_system_prompt_in_draft_with_context(self, reliable_profile):
        """draft_with_context doit injecter <PROFIL_DESTINATAIRE> dans le system prompt."""
        agent = DrafterAgent(account_id=1, knowledge_base="kb_stub")
        agent._llm = MagicMock()
        agent._llm.complete.return_value = _build_mock_llm_response()

        request = DraftRequest(
            email_content="Quelle est la deadline ?",
            recipient_email="bob@example.com",
            account_id=1,
        )

        with patch.object(agent, "_resolve_recipient_profile", return_value=reliable_profile), \
             patch("app.agents.get_drafter_system_prompt_with_context_split", wraps=lambda **kw: (f"STUB_PROMPT {kw.get('recipient_profile')}", "")) as spy, \
             patch("app.agents._track_token_usage"):
            agent.draft_with_context(request)

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        assert "recipient_profile" in kwargs, "recipient_profile doit être passé explicitement"
        assert kwargs["recipient_profile"] is reliable_profile
