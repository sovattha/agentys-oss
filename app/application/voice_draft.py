# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Générer un brouillon vocal à partir d'une transcription.
"""

import uuid
from dataclasses import dataclass

from app.agents import DrafterAgent


@dataclass
class VoiceDraftResult:
    """Résultat de la génération de brouillon vocal."""
    draft_id: str
    email_id: str
    content: str
    status: str


@dataclass
class VoiceDraftUseCase:
    """
    Génère un brouillon de réponse à partir d'une transcription vocale.

    Délègue au DrafterAgent avec la transcription comme instructions.
    """
    account_id: int
    knowledge_base: str

    def execute(self, email_id: str, email_content: str, transcription: str) -> VoiceDraftResult:
        """
        Génère un brouillon à partir d'une transcription vocale.

        Args:
            email_id: ID de l'email auquel répondre.
            email_content: Contenu de l'email original.
            transcription: Transcription vocale de l'utilisateur (instructions).

        Returns:
            VoiceDraftResult avec le brouillon généré.
        """
        drafter = DrafterAgent(
            account_id=self.account_id,
            knowledge_base=self.knowledge_base,
        )

        draft_content = drafter.draft(
            email_content=email_content,
            instructions=transcription,
        )

        return VoiceDraftResult(
            draft_id=str(uuid.uuid4()),
            email_id=email_id,
            content=draft_content,
            status="generated",
        )
