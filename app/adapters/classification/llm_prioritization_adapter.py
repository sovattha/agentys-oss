# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter de priorisation d'emails basé sur LLM.

Implémente PrioritizationPort en utilisant un LLM pour analyser la priorité.

Clean Architecture:
- Propage les erreurs LLM (LLMError et sous-classes) vers les Use Cases
- Ne masque que les erreurs de parsing JSON locales
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.domain.entities import Email, Priority, TokenUsage
from app.domain.exceptions import LLMError
from app.domain.ports import PrioritizationPort, LLMPort

logger = logging.getLogger(__name__)

PRIORITIZATION_PROMPT = """Agent priorisation emails. Output JSON DIRECT, zéro raisonnement, zéro <thinking>, zéro explication.

Scoring :
- urgency (0-100) : mots-clés urgent/ASAP/deadline/aujourd'hui/demain
- vip (0-100) : importance expéditeur (domaine, titre signature)
- sentiment (-1..1) : -1 négatif, 0 neutre, 1 positif
- deadline : ISO YYYY-MM-DD ou null

Format strict (rien autour) :
{"urgency":50,"vip":30,"sentiment":0,"deadline":null,"priority_score":40}

priority_score = urgency*0.4 + vip*0.3 + (sentiment+1)*15"""


@dataclass
class LLMPrioritizationAdapter(PrioritizationPort):
    """
    Adapter de priorisation utilisant un LLM.

    Cet adapter utilise un modèle de langage pour analyser la priorité
    des emails avec des scores d'urgence, VIP et sentiment.
    """
    llm: LLMPort
    max_tokens: int = 80  # Output JSON court uniquement
    token_usage: Optional[TokenUsage] = field(default=None, repr=False)

    def analyze(self, email: Email) -> Priority:
        """
        Analyse la priorité d'un email.

        Args:
            email: L'email à analyser.

        Returns:
            Priority avec les scores de priorité.
        """
        context = self._build_context(email)

        try:
            response = self.llm.complete(
                system=PRIORITIZATION_PROMPT,
                user=context,
                max_tokens=self.max_tokens
            )

            # Tracker les tokens si disponible
            if self.token_usage:
                self.token_usage.add(
                    response.input_tokens,
                    response.output_tokens,
                    response.model
                )

            return self._parse_response(response.content)

        except LLMError:
            # Propager les erreurs LLM (auth, rate limit, timeout, etc.)
            raise
        except Exception as e:
            logger.warning(f"Prioritization failed: {e}")
            return Priority.default()

    def _build_context(self, email: Email) -> str:
        """Construit le contexte pour le LLM."""
        parts = [
            f"Expéditeur: {email.sender}",
            f"Sujet: {email.subject}",
            f"Corps: {email.body[:2000]}"  # Limite le contenu
        ]
        return "\n\n".join(parts)

    def _parse_response(self, content: str) -> Priority:
        """Parse la réponse JSON du LLM."""
        try:
            # Nettoyer le contenu (enlever markdown si présent)
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            data = json.loads(content)

            # Extraire et valider les valeurs
            urgency = int(data.get("urgency", 50))
            urgency = max(0, min(100, urgency))

            vip = int(data.get("vip", 50))
            vip = max(0, min(100, vip))

            sentiment = float(data.get("sentiment", 0))
            sentiment = max(-1.0, min(1.0, sentiment))

            deadline = data.get("deadline")
            if deadline is not None:
                deadline = str(deadline)

            # Calculer le score de priorité si non fourni
            priority_score = data.get("priority_score")
            if priority_score is not None:
                priority_score = int(priority_score)
                priority_score = max(0, min(100, priority_score))
                return Priority(
                    urgency=urgency,
                    vip=vip,
                    sentiment=sentiment,
                    deadline=deadline,
                    priority_score=priority_score
                )
            else:
                # Utiliser la méthode from_components pour calculer
                return Priority.from_components(
                    urgency=urgency,
                    vip=vip,
                    sentiment=sentiment,
                    deadline=deadline
                )

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"Failed to parse prioritization response: {e}")
            return Priority.default()
