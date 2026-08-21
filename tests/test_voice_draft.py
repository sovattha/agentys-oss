# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.application.voice_draft."""

from unittest.mock import patch, MagicMock
from app.application.voice_draft import VoiceDraftUseCase, VoiceDraftResult


class TestVoiceDraftUseCase:
    @patch("app.application.voice_draft.DrafterAgent")
    def test_execute_returns_voice_draft_result(self, mock_drafter_cls):
        mock_drafter = MagicMock()
        mock_drafter.draft.return_value = "Bonjour, merci pour votre email."
        mock_drafter_cls.return_value = mock_drafter

        use_case = VoiceDraftUseCase(account_id=1, knowledge_base="kb")
        result = use_case.execute(
            email_id="msg-123",
            email_content="Contenu original",
            transcription="Dis-lui que je suis d'accord",
        )

        assert isinstance(result, VoiceDraftResult)
        assert result.email_id == "msg-123"
        assert result.content == "Bonjour, merci pour votre email."
        assert result.status == "generated"
        assert result.draft_id  # UUID non vide

    @patch("app.application.voice_draft.DrafterAgent")
    def test_execute_passes_transcription_as_instructions(self, mock_drafter_cls):
        mock_drafter = MagicMock()
        mock_drafter.draft.return_value = "Réponse"
        mock_drafter_cls.return_value = mock_drafter

        use_case = VoiceDraftUseCase(account_id=1, knowledge_base="kb")
        use_case.execute(
            email_id="msg-456",
            email_content="Contenu",
            transcription="Confirme le rendez-vous",
        )

        mock_drafter.draft.assert_called_once_with(
            email_content="Contenu",
            instructions="Confirme le rendez-vous",
        )

    @patch("app.application.voice_draft.DrafterAgent")
    def test_execute_creates_drafter_with_account(self, mock_drafter_cls):
        mock_drafter = MagicMock()
        mock_drafter.draft.return_value = "Réponse"
        mock_drafter_cls.return_value = mock_drafter

        use_case = VoiceDraftUseCase(account_id=42, knowledge_base="ma base")
        use_case.execute("id", "contenu", "transcription")

        mock_drafter_cls.assert_called_once_with(
            account_id=42,
            knowledge_base="ma base",
        )

    @patch("app.application.voice_draft.DrafterAgent")
    def test_execute_generates_unique_draft_ids(self, mock_drafter_cls):
        mock_drafter = MagicMock()
        mock_drafter.draft.return_value = "Réponse"
        mock_drafter_cls.return_value = mock_drafter

        use_case = VoiceDraftUseCase(account_id=1, knowledge_base="kb")
        r1 = use_case.execute("id1", "c", "t")
        r2 = use_case.execute("id2", "c", "t")

        assert r1.draft_id != r2.draft_id
