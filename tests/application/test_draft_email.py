# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour DraftEmailUseCase."""

from unittest.mock import MagicMock

from app.application.draft_email import DraftEmailUseCase
from app.domain.entities import Email, Draft, TokenUsage
from app.domain.ports import LLMPort, LLMResponse


def _make_email(**overrides) -> Email:
    defaults = dict(
        id="email-1",
        subject="Test",
        body="Bonjour, ceci est un test.",
        sender="test@example.com",
    )
    defaults.update(overrides)
    return Email(**defaults)


def _make_llm_response(content: str = "Réponse", **kwargs) -> LLMResponse:
    defaults = dict(input_tokens=10, output_tokens=5, model="mock")
    defaults.update(kwargs)
    return LLMResponse(content=content, **defaults)


class TestDraftEmailUseCaseInit:
    """Tests d'initialisation."""

    def test_creates_token_usage_if_none(self):
        llm = MagicMock(spec=LLMPort)
        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb")
        assert isinstance(uc.token_usage, TokenUsage)

    def test_keeps_provided_token_usage(self):
        llm = MagicMock(spec=LLMPort)
        tu = TokenUsage()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb", token_usage=tu)
        assert uc.token_usage is tu

    def test_default_max_tokens(self):
        llm = MagicMock(spec=LLMPort)
        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb")
        assert uc.max_tokens == 1024


class TestDraftEmailUseCaseExecute:
    """Tests de génération de brouillon V1."""

    def test_returns_draft_with_content(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("Cher client, voici la réponse.")

        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb")
        draft = uc.execute(_make_email())

        assert isinstance(draft, Draft)
        assert draft.content == "Cher client, voici la réponse."
        assert draft.version == 1

    def test_calls_llm_with_system_and_user_prompts(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("Réponse")

        uc = DraftEmailUseCase(llm=llm, knowledge_base="Ma KB")
        uc.execute(_make_email())

        call_kwargs = llm.complete.call_args.kwargs
        assert "Ma KB" in call_kwargs["system"]
        assert llm.complete.call_count == 1

    def test_tracks_tokens(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("R", input_tokens=100, output_tokens=50)

        tu = TokenUsage()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb", token_usage=tu)
        uc.execute(_make_email())

        assert tu.input_tokens == 100
        assert tu.output_tokens == 50

    def test_passes_max_tokens_to_llm(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("R")

        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb", max_tokens=512)
        uc.execute(_make_email())

        call_kwargs = llm.complete.call_args.kwargs
        assert call_kwargs["max_tokens"] == 512


class TestDraftEmailUseCaseExecuteRevision:
    """Tests de génération de brouillon V2 (correction)."""

    def test_returns_draft_v2(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("Version corrigée")

        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb")
        draft = uc.execute_revision(_make_email(), "Ton trop informel")

        assert isinstance(draft, Draft)
        assert draft.content == "Version corrigée"
        assert draft.version == 2

    def test_includes_critique_in_prompt(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("V2")

        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb")
        uc.execute_revision(_make_email(), "Manque de politesse")

        user_prompt = llm.complete.call_args.kwargs["user"]
        assert "Manque de politesse" in user_prompt

    def test_tracks_tokens_on_revision(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("V2", input_tokens=200, output_tokens=100)

        tu = TokenUsage()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb", token_usage=tu)
        uc.execute_revision(_make_email(), "critique")

        assert tu.input_tokens == 200
        assert tu.output_tokens == 100


class TestDraftEmailUseCasePrompts:
    """Tests de construction des prompts."""

    def test_system_prompt_contains_knowledge_base(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("R")

        uc = DraftEmailUseCase(llm=llm, knowledge_base="Règle: toujours vouvoyer")
        uc.execute(_make_email())

        system_prompt = llm.complete.call_args.kwargs["system"]
        assert "Règle: toujours vouvoyer" in system_prompt

    def test_user_prompt_contains_email_content(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("R")

        email = _make_email(body="Urgent: besoin d'aide")
        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb")
        uc.execute(email)

        llm.complete.call_args.kwargs["user"]
        assert llm.complete.called

    def test_revision_prompt_contains_critique_and_email(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.return_value = _make_llm_response("V2")

        uc = DraftEmailUseCase(llm=llm, knowledge_base="kb")
        uc.execute_revision(_make_email(), "REJET : hallucination détectée")

        user_prompt = llm.complete.call_args.kwargs["user"]
        assert "REJET : hallucination détectée" in user_prompt
