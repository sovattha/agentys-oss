# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour le use case DraftEmailUseCase."""

from unittest.mock import MagicMock

from app.domain.entities import Email, Draft, TokenUsage
from app.domain.ports import LLMPort, LLMResponse
from app.application.draft_email import DraftEmailUseCase


# --- Fixtures ---

def _make_email(**overrides) -> Email:
    defaults = dict(
        id="email-001",
        subject="Demande de devis",
        body="Bonjour, je souhaite un devis pour 100 licences.",
        sender="client@example.com",
    )
    defaults.update(overrides)
    return Email(**defaults)


def _make_llm_response(content: str = "Bonjour, voici le devis.", **kw) -> LLMResponse:
    defaults = dict(content=content, input_tokens=100, output_tokens=50, model="claude-sonnet-4-20250514")
    defaults.update(kw)
    return LLMResponse(**defaults)


def _make_mock_llm(response: LLMResponse = None) -> MagicMock:
    mock = MagicMock(spec=LLMPort)
    mock.complete.return_value = response or _make_llm_response()
    return mock


# --- DraftEmailUseCase.execute ---

class TestDraftEmailUseCaseExecute:
    """Tests pour la génération de brouillon V1."""

    def test_execute_returns_draft_v1(self):
        """execute() retourne un Draft avec version=1."""
        llm = _make_mock_llm()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="Nous sommes une ESN.")
        email = _make_email()

        draft = uc.execute(email)

        assert isinstance(draft, Draft)
        assert draft.version == 1
        assert draft.content == "Bonjour, voici le devis."

    def test_execute_calls_llm_complete_with_correct_params(self):
        """execute() appelle llm.complete avec system, user, max_tokens."""
        llm = _make_mock_llm()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB", max_tokens=512)
        email = _make_email()

        uc.execute(email)

        llm.complete.assert_called_once()
        call_kwargs = llm.complete.call_args
        assert call_kwargs.kwargs.get("max_tokens") == 512 or call_kwargs[1].get("max_tokens") == 512 or \
            (len(call_kwargs.args) >= 3 and call_kwargs.args[2] == 512)

    def test_execute_system_prompt_contains_knowledge_base(self):
        """Le prompt système inclut la knowledge base."""
        llm = _make_mock_llm()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="Règle: toujours vouvoyer.")

        uc.execute(_make_email())

        system_prompt = llm.complete.call_args[1].get("system") or llm.complete.call_args[0][0]
        assert "Règle: toujours vouvoyer." in system_prompt

    def test_execute_user_prompt_contains_email_content(self):
        """Le prompt utilisateur contient le contenu de l'email."""
        llm = _make_mock_llm()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB")
        email = _make_email(body="Détail important du message")

        uc.execute(email)

        user_prompt = llm.complete.call_args[1].get("user") or llm.complete.call_args[0][1]
        assert "Détail important du message" in user_prompt

    def test_execute_tracks_token_usage(self):
        """execute() incrémente le token_usage partagé."""
        llm = _make_mock_llm(_make_llm_response(input_tokens=200, output_tokens=80))
        token_usage = TokenUsage()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB", token_usage=token_usage)

        uc.execute(_make_email())

        assert token_usage.input_tokens == 200
        assert token_usage.output_tokens == 80

    def test_execute_creates_default_token_usage_if_none(self):
        """Si token_usage=None, __post_init__ crée un TokenUsage vide."""
        llm = _make_mock_llm()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB", token_usage=None)

        assert uc.token_usage is not None
        assert isinstance(uc.token_usage, TokenUsage)

    def test_execute_accumulates_tokens_across_calls(self):
        """Les tokens sont cumulés entre plusieurs appels."""
        llm = _make_mock_llm(_make_llm_response(input_tokens=100, output_tokens=50))
        token_usage = TokenUsage()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB", token_usage=token_usage)

        uc.execute(_make_email())
        uc.execute(_make_email(id="email-002"))

        assert token_usage.input_tokens == 200
        assert token_usage.output_tokens == 100


# --- DraftEmailUseCase.execute_revision ---

class TestDraftEmailUseCaseRevision:
    """Tests pour la génération de brouillon V2 (correction)."""

    def test_execute_revision_returns_draft_v2(self):
        """execute_revision() retourne un Draft avec version=2."""
        llm = _make_mock_llm(_make_llm_response("Version corrigée du brouillon."))
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB")
        email = _make_email()

        draft = uc.execute_revision(email, critique="Ton trop familier.")

        assert isinstance(draft, Draft)
        assert draft.version == 2
        assert draft.content == "Version corrigée du brouillon."

    def test_execute_revision_prompt_contains_critique(self):
        """Le prompt de révision inclut la critique."""
        llm = _make_mock_llm()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB")

        uc.execute_revision(_make_email(), critique="Manque de politesse")

        user_prompt = llm.complete.call_args[1].get("user") or llm.complete.call_args[0][1]
        assert "Manque de politesse" in user_prompt

    def test_execute_revision_prompt_contains_original_email(self):
        """Le prompt de révision inclut l'email original."""
        llm = _make_mock_llm()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB")
        email = _make_email(body="Contenu original important")

        uc.execute_revision(email, critique="Critique")

        user_prompt = llm.complete.call_args[1].get("user") or llm.complete.call_args[0][1]
        assert "Contenu original important" in user_prompt

    def test_execute_revision_tracks_token_usage(self):
        """execute_revision() incrémente le token_usage."""
        llm = _make_mock_llm(_make_llm_response(input_tokens=300, output_tokens=120))
        token_usage = TokenUsage()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB", token_usage=token_usage)

        uc.execute_revision(_make_email(), critique="Critique")

        assert token_usage.input_tokens == 300
        assert token_usage.output_tokens == 120


# --- Prompts internes ---

class TestDraftEmailPrompts:
    """Tests pour la construction des prompts."""

    def test_system_prompt_contains_instructions(self):
        """Le prompt système contient les instructions de rédaction."""
        llm = _make_mock_llm()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="")

        prompt = uc._build_system_prompt()

        assert "concis" in prompt.lower() or "professionnel" in prompt.lower()
        assert "langue" in prompt.lower()

    def test_user_prompt_formatted_correctly(self):
        """Le prompt utilisateur contient l'email formaté."""
        llm = _make_mock_llm()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB")
        email = _make_email(sender="test@acme.com", subject="Sujet test")

        prompt = uc._build_user_prompt(email)

        assert "test@acme.com" in prompt
        assert "Sujet test" in prompt

    def test_revision_prompt_structured(self):
        """Le prompt de révision a la structure CRITIQUE + EMAIL."""
        llm = _make_mock_llm()
        uc = DraftEmailUseCase(llm=llm, knowledge_base="KB")
        email = _make_email()

        prompt = uc._build_revision_prompt(email, "Ton inadapté")

        assert "CRITIQUE" in prompt.upper()
        assert "Ton inadapté" in prompt
