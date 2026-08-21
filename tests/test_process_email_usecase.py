# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour le use case ProcessEmailUseCase."""

from unittest.mock import MagicMock

from app.domain.entities import Email, ProcessingResult, DraftStatus, TokenUsage
from app.domain.ports import LLMPort, LLMResponse
from app.application.process_email import ProcessEmailUseCase


# --- Helpers ---

def _make_email(**overrides) -> Email:
    defaults = dict(
        id="email-pipeline-001",
        subject="Réclamation client",
        body="Je suis insatisfait du service reçu.",
        sender="client@example.com",
    )
    defaults.update(overrides)
    return Email(**defaults)


def _make_llm_response(content: str, **kw) -> LLMResponse:
    defaults = dict(content=content, input_tokens=100, output_tokens=50, model="claude-sonnet-4-20250514")
    defaults.update(kw)
    return LLMResponse(**defaults)


# --- Pipeline complet : Draft V1 → Critique → (V2 si rejet) ---

class TestProcessEmailPipelineValid:
    """Tests pour le pipeline quand le brouillon V1 est validé."""

    def test_pipeline_valid_v1_returns_validated_status(self):
        """Si le critic valide, status = VALIDATED_V1."""
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("Cher client, nous sommes désolés..."),  # Draft V1
            _make_llm_response("VALID"),  # Critique
        ]
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="KB")

        result = uc.execute(_make_email())

        assert isinstance(result, ProcessingResult)
        assert result.status == DraftStatus.VALIDATED_V1
        assert result.draft_final.content == "Cher client, nous sommes désolés..."
        assert result.critique.is_valid is True

    def test_pipeline_valid_v1_no_revision_call(self):
        """Si V1 validé, le LLM est appelé exactement 2 fois (draft + critique)."""
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("Draft V1"),
            _make_llm_response("VALID"),
        ]
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="KB")

        uc.execute(_make_email())

        assert llm.complete.call_count == 2

    def test_pipeline_valid_v1_draft_final_equals_v1(self):
        """Si V1 validé, draft_final == draft_v1."""
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("Contenu V1"),
            _make_llm_response("VALID"),
        ]
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="KB")

        result = uc.execute(_make_email())

        assert result.draft_final is result.draft_v1
        assert result.was_corrected is False


class TestProcessEmailPipelineRejected:
    """Tests pour le pipeline quand le brouillon V1 est rejeté."""

    def test_pipeline_rejected_produces_v2(self):
        """Si le critic rejette, status = CORRECTED_V2 et draft V2."""
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("Draft V1 imparfait"),
            _make_llm_response("REJET : Ton trop formel."),
            _make_llm_response("Draft V2 amélioré"),
        ]
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="KB")

        result = uc.execute(_make_email())

        assert result.status == DraftStatus.CORRECTED_V2
        assert result.draft_final.content == "Draft V2 amélioré"
        assert result.draft_final.version == 2
        assert result.was_corrected is True

    def test_pipeline_rejected_calls_llm_three_times(self):
        """Si rejeté, 3 appels LLM: draft V1, critique, revision."""
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1"),
            _make_llm_response("REJET : Manque de détails."),
            _make_llm_response("V2"),
        ]
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="KB")

        uc.execute(_make_email())

        assert llm.complete.call_count == 3

    def test_pipeline_rejected_preserves_critique_reason(self):
        """Le résultat contient la raison du rejet."""
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1"),
            _make_llm_response("REJET : Hallucination détectée."),
            _make_llm_response("V2"),
        ]
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="KB")

        result = uc.execute(_make_email())

        assert result.critique.is_valid is False
        assert "Hallucination" in result.critique.reason


class TestProcessEmailTokenTracking:
    """Tests pour le suivi des tokens dans le pipeline."""

    def test_pipeline_accumulates_tokens_across_steps(self):
        """Les tokens sont cumulés entre draft, critique et éventuelle révision."""
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1", input_tokens=100, output_tokens=50),
            _make_llm_response("VALID", input_tokens=80, output_tokens=10),
        ]
        token_usage = TokenUsage()
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="KB", token_usage=token_usage)

        uc.execute(_make_email())

        assert token_usage.input_tokens == 180
        assert token_usage.output_tokens == 60

    def test_pipeline_rejected_accumulates_all_three_steps(self):
        """Avec rejet, les 3 étapes sont comptées."""
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1", input_tokens=100, output_tokens=50),
            _make_llm_response("REJET : Issue", input_tokens=80, output_tokens=20),
            _make_llm_response("V2", input_tokens=120, output_tokens=60),
        ]
        token_usage = TokenUsage()
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="KB", token_usage=token_usage)

        uc.execute(_make_email())

        assert token_usage.input_tokens == 300
        assert token_usage.output_tokens == 130

    def test_pipeline_creates_default_token_usage(self):
        """Si token_usage=None, un TokenUsage par défaut est créé."""
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1"),
            _make_llm_response("VALID"),
        ]
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="KB", token_usage=None)

        assert isinstance(uc.token_usage, TokenUsage)

    def test_pipeline_email_id_in_result(self):
        """Le résultat contient l'id de l'email traité."""
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = [
            _make_llm_response("V1"),
            _make_llm_response("VALID"),
        ]
        uc = ProcessEmailUseCase(llm=llm, knowledge_base="KB")

        result = uc.execute(_make_email(id="unique-id-42"))

        assert result.email_id == "unique-id-42"
