# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter de classification d'emails basé sur LLM.

Implémente ClassifierPort en utilisant un LLM pour classifier les emails.

Clean Architecture:
- Propage les erreurs LLM (LLMError et sous-classes) vers les Use Cases
- Ne masque que les erreurs de parsing JSON locales
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.domain.entities import Email, Classification, EmailCategory, TokenUsage
from app.domain.exceptions import LLMError
from app.domain.ports import ClassifierPort, LLMPort

logger = logging.getLogger(__name__)

CLASSIFIER_PROMPT = """Classifier emails. Output JSON DIRECT. Zéro raisonnement, zéro <thinking>, zéro paraphrase.

Catégories : URGENT | IMPORTANT | NORMAL | NEWSLETTER | PROMO | CC_ONLY | SPAM

Règles rapides :
- User en CC (pas destinataire) → CC_ONLY
- "unsubscribe" / liste diffusion → NEWSLETTER ou PROMO
- Mot-clé urgence explicite → URGENT
- Demande client / business → IMPORTANT
- Sinon → NORMAL

Format strict (rien avant/après) :
{"category":"NORMAL","confidence":0.85,"reason":"5 mots max"}"""


@dataclass
class LLMClassifierAdapter(ClassifierPort):
    """
    Adapter de classification utilisant un LLM.

    Cet adapter utilise un modèle de langage pour classifier les emails
    en catégories prédéfinies avec un score de confiance.
    """
    llm: LLMPort
    max_tokens: int = 60  # Output JSON court uniquement
    token_usage: Optional[TokenUsage] = field(default=None, repr=False)

    def classify(self, email: Email, is_cc: bool = False) -> Classification:
        """
        Classifie un email dans une catégorie.

        Args:
            email: L'email à classifier.
            is_cc: True si l'utilisateur est en copie.

        Returns:
            Classification avec catégorie, confiance et raison.
        """
        # Construire le contexte
        context = self._build_context(email, is_cc)

        try:
            response = self.llm.complete(
                system=CLASSIFIER_PROMPT,
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
            # vers les Use Cases pour qu'ils puissent réagir
            raise
        except Exception as e:
            # Autres erreurs (parsing, etc.) → fallback
            logger.warning(f"Classification failed: {e}")
            return Classification.default()

    def _build_context(self, email: Email, is_cc: bool) -> str:
        """Construit le contexte pour le LLM."""
        parts = []

        if is_cc:
            parts.append("[L'utilisateur est en COPIE]")

        parts.append(f"Expéditeur: {email.sender}")
        parts.append(f"Sujet: {email.subject}")
        parts.append(f"Corps: {email.body[:2000]}")  # Limite le contenu

        return "\n\n".join(parts)

    def _parse_response(self, content: str) -> Classification:
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

            category_str = data.get("category", "NORMAL").upper()
            try:
                category = EmailCategory(category_str)
            except ValueError:
                category = EmailCategory.NORMAL

            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            reason = str(data.get("reason", ""))

            return Classification(
                category=category,
                confidence=confidence,
                reason=reason
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse classification response: {e}")
            return Classification.default()
