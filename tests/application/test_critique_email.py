# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.application.critique_email."""

from unittest.mock import MagicMock

from app.domain.entities import Email, Draft, Critique, TokenUsage
from app.application.critique_email import CritiqueEmailUseCase


def _make_email(**overrides) -> Email:
    defaults = dict(id="e1", subject="Réunion", body="Bonjour, ...", sender="a@b.com")
    defaults.update(overrides)
    return Email(**defaults)


def _make_draft(content: str = "Merci pour votre email.", version: int = 1) -> Draft:
    return Draft(content=content, version=version)


def _make_llm_response(content: str = "VALID", input_tokens: int = 50, output_tokens: int = 10):
    resp = MagicMock()
    resp.content = content
    resp.input_tokens = input_tokens
    resp.output_tokens = output_tokens
    resp.model = "claude-sonnet-4-20250514"
    return resp


class TestCritiqueEmailUseCase:
    def test_valid_critique(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _make_llm_response("VALID")

        use_case = CritiqueEmailUseCase(llm=mock_llm, knowledge_base="Soyez poli")
        result = use_case.execute(_make_email(), _make_draft())

        assert result.is_valid is True
        assert result.reason is None
        mock_llm.complete.assert_called_once()

    def test_rejected_critique(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _make_llm_response(
            "REJET : Le ton est trop familier"
        )

        use_case = CritiqueEmailUseCase(llm=mock_llm, knowledge_base="Vouvoyer")
        result = use_case.execute(_make_email(), _make_draft())

        assert result.is_valid is False
        assert "familier" in result.reason

    def test_token_usage_is_tracked(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _make_llm_response(
            "VALID", input_tokens=100, output_tokens=20
        )

        mock_token_usage = MagicMock(spec=TokenUsage)
        use_case = CritiqueEmailUseCase(
            llm=mock_llm, knowledge_base="", token_usage=mock_token_usage
        )
        use_case.execute(_make_email(), _make_draft())

        mock_token_usage.add.assert_called_once_with(100, 20, "claude-sonnet-4-20250514")

    def test_default_token_usage_created(self):
        mock_llm = MagicMock()
        use_case = CritiqueEmailUseCase(llm=mock_llm, knowledge_base="")
        assert use_case.token_usage is not None
        assert isinstance(use_case.token_usage, TokenUsage)

    def test_system_prompt_contains_knowledge_base(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _make_llm_response("VALID")

        use_case = CritiqueEmailUseCase(llm=mock_llm, knowledge_base="Toujours vouvoyer")
        use_case.execute(_make_email(), _make_draft())

        call_args = mock_llm.complete.call_args
        system_prompt = call_args.kwargs.get("system") or call_args[1].get("system") or call_args[0][0]
        assert "Toujours vouvoyer" in system_prompt

    def test_user_prompt_contains_email_and_draft(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _make_llm_response("VALID")

        email = _make_email(body="Contenu de l'email original")
        draft = _make_draft(content="Ma réponse au brouillon")

        use_case = CritiqueEmailUseCase(llm=mock_llm, knowledge_base="")
        use_case.execute(email, draft)

        call_args = mock_llm.complete.call_args
        user_prompt = call_args.kwargs.get("user") or call_args[1].get("user")
        assert "Ma réponse au brouillon" in user_prompt

    def test_max_tokens_passed_to_llm(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _make_llm_response("VALID")

        use_case = CritiqueEmailUseCase(
            llm=mock_llm, knowledge_base="", max_tokens=512
        )
        use_case.execute(_make_email(), _make_draft())

        call_args = mock_llm.complete.call_args
        assert call_args.kwargs.get("max_tokens") == 512


# ── Critique.from_response (entité pure) ────────────────────────────────────

class TestCritiqueFromResponse:
    def test_valid_response(self):
        c = Critique.from_response("VALID")
        assert c.is_valid is True
        assert c.reason is None

    def test_valid_with_extra_text(self):
        c = Critique.from_response("VALID - good job")
        assert c.is_valid is True

    def test_valid_case_insensitive(self):
        c = Critique.from_response("valid")
        assert c.is_valid is True

    def test_rejection(self):
        c = Critique.from_response("REJET : Trop informel")
        assert c.is_valid is False
        assert "Trop informel" in c.reason

    def test_whitespace_trimmed(self):
        c = Critique.from_response("  VALID  ")
        assert c.is_valid is True

    def test_str(self):
        c = Critique(raw_response="VALID", is_valid=True)
        assert str(c) == "VALID"
