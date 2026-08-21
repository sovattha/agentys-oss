# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour le use case CompleteDraftUseCase."""

from unittest.mock import MagicMock

from app.domain.entities import DraftInput, DraftInputTone, CompletedDraft, TokenUsage
from app.domain.ports import LLMPort, LLMResponse
from app.application.complete_draft import CompleteDraftUseCase


# --- Helpers ---

def _make_draft_input(**overrides) -> DraftInput:
    defaults = dict(
        raw_input="- Confirmer le RDV\n- Envoyer le devis\n- Remercier pour la confiance",
        key_points=["Confirmer le RDV", "Envoyer le devis", "Remercier pour la confiance"],
        tone=DraftInputTone.FORMAL,
        recipient="Jean Dupont",
        subject_hint="Confirmation de rendez-vous",
    )
    defaults.update(overrides)
    return DraftInput(**defaults)


def _make_llm_response(content: str = None, **kw) -> LLMResponse:
    if content is None:
        content = (
            "OBJET: Confirmation de rendez-vous\n\n"
            "Monsieur Dupont,\n\n"
            "Je vous écris pour confirmer notre rendez-vous.\n\n"
            "Cordialement"
        )
    defaults = dict(content=content, input_tokens=150, output_tokens=80, model="claude-sonnet-4-20250514")
    defaults.update(kw)
    return LLMResponse(**defaults)


def _make_mock_llm(response: LLMResponse = None) -> MagicMock:
    mock = MagicMock(spec=LLMPort)
    mock.complete.return_value = response or _make_llm_response()
    return mock


# --- Tests execute() ---

class TestCompleteDraftUseCaseExecute:
    """Tests pour la complétion de brouillon."""

    def test_execute_returns_completed_draft(self):
        """execute() retourne un CompletedDraft."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)

        result = uc.execute(_make_draft_input())

        assert isinstance(result, CompletedDraft)

    def test_execute_extracts_subject_from_response(self):
        """Le sujet est extrait de la ligne OBJET: dans la réponse."""
        llm = _make_mock_llm(_make_llm_response(
            "OBJET: Mon sujet extrait\n\nCorps du message."
        ))
        uc = CompleteDraftUseCase(llm=llm)

        result = uc.execute(_make_draft_input())

        assert result.subject == "Mon sujet extrait"

    def test_execute_extracts_body_from_response(self):
        """Le corps est extrait après la ligne OBJET:."""
        llm = _make_mock_llm(_make_llm_response(
            "OBJET: Sujet\n\nBonjour,\n\nVoici le contenu.\n\nCordialement"
        ))
        uc = CompleteDraftUseCase(llm=llm)

        result = uc.execute(_make_draft_input())

        assert "Bonjour" in result.body
        assert "Cordialement" in result.body

    def test_execute_uses_subject_hint_as_fallback(self):
        """Si pas d'OBJET: dans la réponse, utilise subject_hint."""
        llm = _make_mock_llm(_make_llm_response(
            "Bonjour,\n\nVoici un email sans ligne OBJET."
        ))
        uc = CompleteDraftUseCase(llm=llm)

        result = uc.execute(_make_draft_input(subject_hint="Mon sujet hint"))

        assert result.subject == "Mon sujet hint"

    def test_execute_uses_first_key_point_as_subject_fallback(self):
        """Si pas d'OBJET: ni subject_hint, utilise le premier key_point."""
        llm = _make_mock_llm(_make_llm_response(
            "Bonjour,\n\nJuste un message sans objet."
        ))
        uc = CompleteDraftUseCase(llm=llm)

        result = uc.execute(_make_draft_input(
            subject_hint=None,
            key_points=["Premier point important"]
        ))

        assert result.subject == "Premier point important"

    def test_execute_tracks_token_usage(self):
        """execute() incrémente le token_usage."""
        llm = _make_mock_llm(_make_llm_response(input_tokens=200, output_tokens=100))
        token_usage = TokenUsage()
        uc = CompleteDraftUseCase(llm=llm, token_usage=token_usage)

        uc.execute(_make_draft_input())

        assert token_usage.input_tokens == 200
        assert token_usage.output_tokens == 100

    def test_execute_creates_default_token_usage(self):
        """Si token_usage=None, un TokenUsage est créé."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm, token_usage=None)

        assert isinstance(uc.token_usage, TokenUsage)

    def test_execute_preserves_recipient_and_tone(self):
        """Le résultat conserve recipient et tone de l'input."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)

        result = uc.execute(_make_draft_input(
            recipient="Marie Martin",
            tone=DraftInputTone.FRIENDLY,
        ))

        assert result.recipient == "Marie Martin"
        assert result.tone_used == DraftInputTone.FRIENDLY


# --- Tests prompts ---

class TestCompleteDraftPrompts:
    """Tests pour la construction des prompts."""

    def test_system_prompt_contains_base_prompt(self):
        """Le prompt système contient le prompt de base."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)

        prompt = uc._build_system_prompt()

        assert "courriel" in prompt.lower() or "email" in prompt.lower()
        assert "OBJET:" in prompt

    def test_system_prompt_includes_knowledge_base(self):
        """Le prompt système inclut la KB si fournie."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm, knowledge_base="Nous vendons du SaaS.")

        prompt = uc._build_system_prompt()

        assert "Nous vendons du SaaS." in prompt

    def test_system_prompt_without_knowledge_base(self):
        """Le prompt système sans KB ne contient pas CONTEXTE ENTREPRISE."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm, knowledge_base="")

        prompt = uc._build_system_prompt()

        assert "CONTEXTE ENTREPRISE" not in prompt

    def test_user_prompt_contains_key_points(self):
        """Le prompt utilisateur contient les key_points."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)

        prompt = uc._build_user_prompt(_make_draft_input(
            key_points=["Point A", "Point B"]
        ))

        assert "Point A" in prompt
        assert "Point B" in prompt

    def test_user_prompt_uses_raw_input_if_no_key_points(self):
        """Si pas de key_points, utilise raw_input."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)

        prompt = uc._build_user_prompt(_make_draft_input(
            key_points=[],
            raw_input="Texte brut de l'utilisateur"
        ))

        assert "Texte brut de l'utilisateur" in prompt

    def test_user_prompt_includes_recipient(self):
        """Le prompt inclut le destinataire si fourni."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)

        prompt = uc._build_user_prompt(_make_draft_input(recipient="Client VIP"))

        assert "Client VIP" in prompt

    def test_user_prompt_includes_tone(self):
        """Le prompt inclut le ton souhaité."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)

        prompt = uc._build_user_prompt(_make_draft_input(tone=DraftInputTone.URGENT))

        assert "urgent" in prompt.lower()


# --- Tests _parse_response ---

class TestCompleteDraftParseResponse:
    """Tests pour le parsing de la réponse LLM."""

    def test_parse_with_objet_prefix(self):
        """Parse correctement avec OBJET: en début de ligne."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)
        draft_input = _make_draft_input()

        result = uc._parse_response(
            "OBJET: Sujet test\n\nCorps du message ici.",
            draft_input
        )

        assert result.subject == "Sujet test"
        assert "Corps du message" in result.body

    def test_parse_with_objet_space_prefix(self):
        """Parse correctement avec 'OBJET :' (espace avant les deux-points)."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)
        draft_input = _make_draft_input()

        result = uc._parse_response(
            "Objet : Mon sujet\n\nMon corps.",
            draft_input
        )

        assert result.subject == "Mon sujet"

    def test_parse_without_objet_line(self):
        """Sans OBJET:, le fallback subject_hint est utilisé."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)
        draft_input = _make_draft_input(subject_hint="Fallback sujet")

        result = uc._parse_response("Juste du texte brut.", draft_input)

        assert result.subject == "Fallback sujet"

    def test_parse_empty_body_uses_full_response(self):
        """Si le body est vide après parsing, utilise la réponse complète."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)
        draft_input = _make_draft_input()

        result = uc._parse_response("OBJET: Sujet\n", draft_input)

        # Le body ne devrait pas être vide — fallback au contenu complet
        assert len(result.body) > 0

    def test_parse_truncates_long_first_key_point_for_subject(self):
        """Un key_point > 50 chars est tronqué pour le sujet."""
        llm = _make_mock_llm()
        uc = CompleteDraftUseCase(llm=llm)
        long_point = "A" * 60
        draft_input = _make_draft_input(subject_hint=None, key_points=[long_point])

        result = uc._parse_response("Juste du texte.", draft_input)

        assert len(result.subject) == 53  # 50 + "..."
        assert result.subject.endswith("...")
