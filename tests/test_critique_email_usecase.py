# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour le use case CritiqueEmailUseCase."""

from unittest.mock import MagicMock

from app.domain.entities import Email, Draft, Critique, TokenUsage
from app.domain.ports import LLMPort, LLMResponse
from app.application.critique_email import CritiqueEmailUseCase


# --- Helpers ---

def _make_email(**overrides) -> Email:
    defaults = dict(
        id="email-001",
        subject="Question sur le produit",
        body="Bonjour, quel est le prix du plan Pro ?",
        sender="prospect@example.com",
    )
    defaults.update(overrides)
    return Email(**defaults)


def _make_draft(content: str = "Bonjour, le plan Pro coûte 49€/mois.", version: int = 1) -> Draft:
    return Draft(content=content, version=version)


def _make_llm_response(content: str, **kw) -> LLMResponse:
    defaults = dict(content=content, input_tokens=80, output_tokens=20, model="claude-sonnet-4-20250514")
    defaults.update(kw)
    return LLMResponse(**defaults)


def _make_mock_llm(response: LLMResponse = None) -> MagicMock:
    mock = MagicMock(spec=LLMPort)
    mock.complete.return_value = response or _make_llm_response("VALID")
    return mock


# --- Tests execute() ---

class TestCritiqueEmailUseCaseExecute:
    """Tests pour l'évaluation de brouillons."""

    def test_execute_returns_valid_critique(self):
        """execute() retourne une Critique VALID quand le LLM valide."""
        llm = _make_mock_llm(_make_llm_response("VALID"))
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="KB")

        critique = uc.execute(_make_email(), _make_draft())

        assert isinstance(critique, Critique)
        assert critique.is_valid is True
        assert critique.reason is None

    def test_execute_returns_rejected_critique(self):
        """execute() retourne une Critique avec rejet quand le LLM rejette."""
        llm = _make_mock_llm(_make_llm_response("REJET : Le ton est trop familier."))
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="KB")

        critique = uc.execute(_make_email(), _make_draft())

        assert critique.is_valid is False
        assert "familier" in critique.reason.lower()

    def test_execute_calls_llm_with_email_and_draft(self):
        """execute() envoie l'email et le brouillon au LLM."""
        llm = _make_mock_llm()
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="KB")
        email = _make_email(body="Corps de l'email")
        draft = _make_draft("Réponse proposée")

        uc.execute(email, draft)

        user_prompt = llm.complete.call_args[1].get("user") or llm.complete.call_args[0][1]
        assert "Corps de l'email" in user_prompt
        assert "Réponse proposée" in user_prompt

    def test_execute_tracks_token_usage(self):
        """execute() incrémente le token_usage."""
        llm = _make_mock_llm(_make_llm_response("VALID", input_tokens=150, output_tokens=30))
        token_usage = TokenUsage()
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="KB", token_usage=token_usage)

        uc.execute(_make_email(), _make_draft())

        assert token_usage.input_tokens == 150
        assert token_usage.output_tokens == 30

    def test_execute_creates_default_token_usage(self):
        """__post_init__ crée un TokenUsage si None."""
        llm = _make_mock_llm()
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="KB", token_usage=None)

        assert isinstance(uc.token_usage, TokenUsage)
        assert uc.token_usage.total == 0

    def test_execute_uses_max_tokens(self):
        """execute() passe max_tokens au LLM."""
        llm = _make_mock_llm()
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="KB", max_tokens=128)

        uc.execute(_make_email(), _make_draft())

        call_args = llm.complete.call_args
        # max_tokens should be 128
        assert 128 in call_args.args or call_args.kwargs.get("max_tokens") == 128

    def test_execute_valid_with_extra_whitespace(self):
        """VALID avec espaces est quand même considéré valid."""
        llm = _make_mock_llm(_make_llm_response("  VALID  "))
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="KB")

        critique = uc.execute(_make_email(), _make_draft())

        assert critique.is_valid is True

    def test_execute_valid_case_insensitive(self):
        """'Valid' ou 'valid' est accepté."""
        llm = _make_mock_llm(_make_llm_response("Valid"))
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="KB")

        critique = uc.execute(_make_email(), _make_draft())

        assert critique.is_valid is True


# --- Tests prompts ---

class TestCritiqueEmailPrompts:
    """Tests pour la construction des prompts de critique."""

    def test_system_prompt_contains_evaluation_criteria(self):
        """Le prompt système contient les critères d'évaluation."""
        llm = _make_mock_llm()
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="Contexte métier")

        prompt = uc._build_system_prompt()

        assert "VALID" in prompt
        assert "REJET" in prompt
        assert "Contexte métier" in prompt

    def test_user_prompt_contains_email_and_draft(self):
        """Le prompt utilisateur contient l'email original et la réponse."""
        llm = _make_mock_llm()
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="KB")
        email = _make_email(body="Question importante")
        draft = _make_draft("Ma réponse détaillée")

        prompt = uc._build_user_prompt(email, draft)

        assert "Question importante" in prompt
        assert "Ma réponse détaillée" in prompt
        assert "VERDICT" in prompt

    def test_system_prompt_contains_knowledge_base(self):
        """Le prompt système inclut la knowledge base."""
        llm = _make_mock_llm()
        uc = CritiqueEmailUseCase(llm=llm, knowledge_base="Ne jamais promettre de remise.")

        prompt = uc._build_system_prompt()

        assert "Ne jamais promettre de remise." in prompt
