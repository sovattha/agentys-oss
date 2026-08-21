# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour ProcessEmailUseCase."""

from unittest.mock import MagicMock

from app.application.process_email import ProcessEmailUseCase
from app.domain.entities import Email, DraftStatus, TokenUsage
from app.domain.ports import LLMPort, LLMResponse


def _make_email(**overrides) -> Email:
    defaults = dict(
        id="email-1",
        subject="Demande info",
        body="Bonjour, je voudrais des informations.",
        sender="client@example.com",
    )
    defaults.update(overrides)
    return Email(**defaults)


def _make_llm_response(content: str = "Réponse", input_tokens: int = 10, output_tokens: int = 5) -> LLMResponse:
    return LLMResponse(content=content, input_tokens=input_tokens, output_tokens=output_tokens, model="mock")


class TestProcessEmailUseCaseInit:
    """Tests d'initialisation du use case."""

    def test_creates_token_usage_if_none(self):
        llm = MagicMock(spec=LLMPort)
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb")
        assert uc.token_usage is not None
        assert isinstance(uc.token_usage, TokenUsage)

    def test_keeps_provided_token_usage(self):
        llm = MagicMock(spec=LLMPort)
        tu = TokenUsage()
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb", token_usage=tu)
        assert uc.token_usage is tu

    def test_default_max_tokens(self):
        llm = MagicMock(spec=LLMPort)
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb")
        assert uc.max_tokens_draft == 1024
        assert uc.max_tokens_critique == 256


class TestProcessEmailUseCaseExecuteValidV1:
    """Tests du pipeline quand le brouillon V1 est validé."""

    def test_returns_validated_v1_when_critique_is_valid(self):
        llm = MagicMock(spec=LLMPort)
        # Premier appel: draft V1, deuxième appel: critique VALID
        llm.complete.side_effect = [
            _make_llm_response("Brouillon V1"),
            _make_llm_response("VALID"),
        ]

        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb")
        result = uc.execute(_make_email())

        assert result.status == DraftStatus.VALIDATED_V1
        assert result.draft_v1.content == "Brouillon V1"
        assert result.draft_final.content == "Brouillon V1"
        assert result.critique.is_valid is True
        assert result.draft_final is result.draft_v1

    def test_llm_called_twice_for_valid_v1(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("Brouillon V1"),
            _make_llm_response("VALID"),
        ]

        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb")
        uc.execute(_make_email())

        assert llm.complete.call_count == 2


class TestProcessEmailUseCaseExecuteCorrectedV2:
    """Tests du pipeline quand le brouillon V1 est rejeté."""

    def test_returns_corrected_v2_when_critique_rejects(self):
        llm = MagicMock(spec=LLMPort)
        # Appels: draft V1, critique REJET, draft V2
        llm.complete.side_effect = [
            _make_llm_response("Brouillon V1"),
            _make_llm_response("REJET : Ton trop informel"),
            _make_llm_response("Brouillon V2 corrigé"),
        ]

        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb")
        result = uc.execute(_make_email())

        assert result.status == DraftStatus.CORRECTED_V2
        assert result.draft_v1.content == "Brouillon V1"
        assert result.draft_final.content == "Brouillon V2 corrigé"
        assert result.critique.is_valid is False
        assert result.critique.reason == "REJET : Ton trop informel"

    def test_llm_called_three_times_for_rejection(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1"),
            _make_llm_response("REJET : problème"),
            _make_llm_response("V2"),
        ]

        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb")
        uc.execute(_make_email())

        assert llm.complete.call_count == 3


class TestProcessEmailUseCaseTokenTracking:
    """Tests du suivi des tokens."""

    def test_tokens_accumulated_across_valid_pipeline(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1", input_tokens=100, output_tokens=50),
            _make_llm_response("VALID", input_tokens=80, output_tokens=10),
        ]

        tu = TokenUsage()
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb", token_usage=tu)
        uc.execute(_make_email())

        assert tu.input_tokens == 180
        assert tu.output_tokens == 60

    def test_tokens_accumulated_across_rejection_pipeline(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1", input_tokens=100, output_tokens=50),
            _make_llm_response("REJET : x", input_tokens=80, output_tokens=10),
            _make_llm_response("V2", input_tokens=120, output_tokens=60),
        ]

        tu = TokenUsage()
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb", token_usage=tu)
        uc.execute(_make_email())

        assert tu.input_tokens == 300
        assert tu.output_tokens == 120


class TestProcessEmailUseCaseResult:
    """Tests sur le ProcessingResult."""

    def test_was_corrected_false_when_v1_valid(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1"),
            _make_llm_response("VALID"),
        ]

        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb")
        result = uc.execute(_make_email())
        assert result.was_corrected is False

    def test_was_corrected_true_when_rejected(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1"),
            _make_llm_response("REJET : x"),
            _make_llm_response("V2"),
        ]

        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb")
        result = uc.execute(_make_email())
        assert result.was_corrected is True

    def test_email_id_preserved_in_result(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1"),
            _make_llm_response("VALID"),
        ]

        uc = ProcessEmailUseCase(llm=llm, knowledge_base="kb")
        result = uc.execute(_make_email(id="my-email-42"))
        assert result.email_id == "my-email-42"
