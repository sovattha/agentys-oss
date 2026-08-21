# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter pour l'analyse du contexte de contact via Claude API.

Cet adapter utilise Claude pour analyser l'historique des échanges
avec un contact et en extraire le ton, les sujets récurrents, etc.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional, Sequence

from app.db.models.email import Email
from app.domain.entities import ContactContext, DominantTone, TopicInfo
from app.domain.ports import ContactAnalyzerPort, LLMPort

logger = logging.getLogger(__name__)

# System prompt for contact analysis
ANALYSIS_SYSTEM_PROMPT = """You are an expert at analyzing email communication patterns.
Your task is to analyze a conversation history between two parties and extract:
1. The dominant tone of the relationship (formal, friendly, professional, casual)
2. Recurring topics/themes in their conversations
3. The strength of their professional relationship (0-100 scale)

IMPORTANT: You MUST respond ONLY with valid JSON. No explanations, no markdown formatting.

JSON Schema:
{
  "dominant_tone": "formal" | "friendly" | "professional" | "casual",
  "tone_confidence": 0.0 to 1.0,
  "recurring_topics": [
    {"topic": "string", "frequency": number}
  ],
  "relationship_strength": 0 to 100
}

Tone definitions:
- formal: Very structured, polite, follows strict business etiquette
- friendly: Warm, personal, uses informal language
- professional: Business-appropriate but not stiff, balanced
- casual: Relaxed, informal, like talking to a friend

relationship_strength:
- 0-25: New or distant contact
- 26-50: Occasional professional interaction
- 51-75: Regular working relationship
- 76-100: Close professional or personal relationship"""


class ContactHistoryAdapter(ContactAnalyzerPort):
    """
    Adapter utilisant Claude API pour l'analyse du contexte de contact.

    Attributes:
        llm: Port LLM pour les appels à Claude.
    """

    def __init__(self, llm: LLMPort):
        """
        Initialise l'adapter.

        Args:
            llm: Port LLM configuré (ex: ClaudeAdapter).
        """
        self._llm = llm

    async def analyze(
        self,
        contact_email: str,
        account_id: int,
        emails: Sequence[Email],
        timeout_seconds: int = 30,
    ) -> ContactContext:
        """
        Analyse l'historique des échanges avec un contact via Claude API.

        Args:
            contact_email: Adresse email du contact.
            account_id: ID du compte email.
            emails: Séquence d'emails à analyser.
            timeout_seconds: Timeout en secondes.

        Returns:
            ContactContext avec le résultat de l'analyse.
        """
        start_time = time.time()

        # Validation
        if not contact_email or "@" not in contact_email:
            raise ValueError("Invalid contact_email")

        email_count = len(emails)
        if email_count == 0:
            return ContactContext.create_incomplete(
                contact_email=contact_email,
                account_id=account_id,
                email_count=0,
                analysis_duration_ms=0,
            )

        # Extract date range
        dates = [e.date for e in emails if e.date]
        first_interaction = min(dates) if dates else None
        last_interaction = max(dates) if dates else None

        # Prepare email summaries for analysis
        user_prompt = self._build_user_prompt(contact_email, emails)

        try:
            # Run LLM call with timeout
            result = await asyncio.wait_for(
                self._call_llm(user_prompt),
                timeout=timeout_seconds,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            if result is None:
                logger.warning(f"LLM returned no result for {contact_email}")
                return ContactContext.create_incomplete(
                    contact_email=contact_email,
                    account_id=account_id,
                    email_count=email_count,
                    analysis_duration_ms=elapsed_ms,
                )

            # Parse and build ContactContext
            return self._build_context(
                contact_email=contact_email,
                account_id=account_id,
                email_count=email_count,
                llm_result=result,
                first_interaction=first_interaction,
                last_interaction=last_interaction,
                analysis_duration_ms=elapsed_ms,
            )

        except asyncio.TimeoutError:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.warning(
                f"Contact analysis timeout after {elapsed_ms}ms for {contact_email}"
            )
            return ContactContext.create_incomplete(
                contact_email=contact_email,
                account_id=account_id,
                email_count=email_count,
                analysis_duration_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Contact analysis error: {e}")
            return ContactContext.create_incomplete(
                contact_email=contact_email,
                account_id=account_id,
                email_count=email_count,
                analysis_duration_ms=elapsed_ms,
            )

    def _build_user_prompt(self, contact_email: str, emails: Sequence[Email]) -> str:
        """
        Construit le prompt utilisateur avec les emails à analyser.

        Args:
            contact_email: Email du contact.
            emails: Liste des emails.

        Returns:
            Prompt formaté pour Claude.
        """
        lines = [
            f"Analyze the following email conversation history with {contact_email}.",
            f"Total emails: {len(emails)}",
            "",
            "--- EMAIL HISTORY ---",
        ]

        for i, email in enumerate(emails, 1):
            direction = "FROM" if email.sender == contact_email else "TO"
            date_str = email.date.strftime("%Y-%m-%d") if email.date else "unknown"
            subject = email.subject or "(no subject)"

            # Truncate body for context window efficiency
            body = email.body_text or email.snippet or ""
            if len(body) > 500:
                body = body[:500] + "..."

            lines.append(f"\n[Email {i}] {direction} {contact_email} on {date_str}")
            lines.append(f"Subject: {subject}")
            lines.append(f"Content: {body}")

        lines.append("\n--- END OF HISTORY ---")
        lines.append("\nAnalyze and respond with JSON only.")

        return "\n".join(lines)

    async def _call_llm(self, user_prompt: str) -> Optional[dict]:
        """
        Appelle le LLM et parse la réponse JSON.

        Args:
            user_prompt: Prompt à envoyer.

        Returns:
            Dictionnaire avec le résultat ou None.
        """
        # Run in executor since LLM.complete is synchronous
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._llm.complete(
                system=ANALYSIS_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=1024,
            ),
        )

        if not response or not response.content:
            return None

        # Parse JSON response
        try:
            # Handle potential markdown code blocks
            content = response.content.strip()
            if content.startswith("```"):
                # Extract content between code blocks
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response content: {response.content}")
            return None

    def _build_context(
        self,
        contact_email: str,
        account_id: int,
        email_count: int,
        llm_result: dict,
        first_interaction: Optional[datetime],
        last_interaction: Optional[datetime],
        analysis_duration_ms: int,
    ) -> ContactContext:
        """
        Construit le ContactContext à partir du résultat LLM.

        Args:
            contact_email: Email du contact.
            account_id: ID du compte.
            email_count: Nombre d'emails analysés.
            llm_result: Résultat JSON du LLM.
            first_interaction: Date du premier échange.
            last_interaction: Date du dernier échange.
            analysis_duration_ms: Durée de l'analyse.

        Returns:
            ContactContext complet.
        """
        # Extract tone
        tone_str = llm_result.get("dominant_tone", "professional")
        try:
            dominant_tone = DominantTone(tone_str.lower())
        except ValueError:
            dominant_tone = DominantTone.PROFESSIONAL

        # Extract confidence
        tone_confidence = llm_result.get("tone_confidence", 0.5)
        tone_confidence = max(0.0, min(1.0, float(tone_confidence)))

        # Extract topics
        topics_raw = llm_result.get("recurring_topics", [])
        recurring_topics = []
        for topic_data in topics_raw[:5]:  # Limit to 5 topics max
            if isinstance(topic_data, dict) and "topic" in topic_data:
                try:
                    topic_info = TopicInfo(
                        topic=str(topic_data["topic"]),
                        frequency=int(topic_data.get("frequency", 1)),
                    )
                    recurring_topics.append(topic_info)
                except (ValueError, TypeError):
                    continue

        # Extract relationship strength
        relationship_strength = llm_result.get("relationship_strength", 50)
        relationship_strength = max(0, min(100, int(relationship_strength)))

        return ContactContext(
            contact_email=contact_email,
            account_id=account_id,
            email_count=email_count,
            dominant_tone=dominant_tone,
            tone_confidence=tone_confidence,
            recurring_topics=recurring_topics,
            relationship_strength=relationship_strength,
            first_interaction=first_interaction,
            last_interaction=last_interaction,
            analysis_duration_ms=analysis_duration_ms,
            is_complete=True,
        )

    def is_available(self) -> bool:
        """Vérifie si le LLM est disponible."""
        return self._llm.is_available()
