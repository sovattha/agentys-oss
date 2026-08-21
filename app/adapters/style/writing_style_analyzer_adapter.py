# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter pour l'analyse du style d'écriture via Claude API.

Cet adapter utilise Claude pour analyser les emails envoyés par l'utilisateur
et en extraire son style d'écriture personnel.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

from app.db.models.email import Email
from app.domain.entities.writing_style import FormalityLevel, WritingStyleProfile
from app.domain.ports.llm_port import LLMPort
from app.domain.ports.writing_style_port import WritingStyleAnalyzerPort

logger = logging.getLogger(__name__)

# System prompt for writing style analysis
STYLE_ANALYSIS_SYSTEM_PROMPT = """You are an expert at analyzing personal writing styles in emails.
Your task is to analyze a collection of emails written by a user and extract their writing characteristics.

IMPORTANT: You MUST respond ONLY with valid JSON. No explanations, no markdown formatting.

JSON Schema:
{
  "formality_level": "formal" | "casual" | "mixed",
  "common_words": ["word1", "word2", ...],
  "preferred_greetings": ["greeting1", "greeting2", ...],
  "preferred_closings": ["closing1", "closing2", ...],
  "typical_signature": "string or null",
  "avg_sentence_length": number
}

Definitions:
- formality_level:
  - formal: Uses "vous", complete formal phrases, no contractions
  - casual: Uses "tu", contractions, informal expressions
  - mixed: Adapts based on context

- common_words: Frequently used words/expressions that characterize this person's style (max 20)
- preferred_greetings: Opening phrases like "Bonjour", "Salut", "Cher/Chère" (max 5)
- preferred_closings: Closing phrases like "Cordialement", "À bientôt", "Bien à vous" (max 5)
- typical_signature: If the user has a consistent signature pattern
- avg_sentence_length: Average number of words per sentence

FORBIDDEN: never output "Unknown", "Inconnu", "None", "null", "N/A", "undefined" or a
descriptive placeholder (e.g. "Unknown (forwarded content)") in preferred_greetings /
preferred_closings. If the emails contain no usable greeting/closing (forwards, empty
bodies), return an empty array [].

Focus on patterns that are CONSISTENT across multiple emails."""

SINGLE_EMAIL_ANALYSIS_PROMPT = """Analyze this single email for writing style characteristics.
Extract ONLY the elements present in this specific email.

IMPORTANT: Respond ONLY with valid JSON.

JSON Schema:
{
  "common_words": ["word1", "word2", ...],
  "greetings": ["greeting found"],
  "closings": ["closing found"],
  "sentence_length": number,
  "email_length": number
}

Extract only what's actually present - empty arrays are fine if not found."""


class WritingStyleAnalyzerAdapter(WritingStyleAnalyzerPort):
    """
    Adapter utilisant Claude API pour l'analyse du style d'écriture.

    Attributes:
        llm: Port LLM pour les appels à Claude.
    """

    MIN_EMAIL_LENGTH = 50  # Minimum characters for a valid email

    def __init__(self, llm: LLMPort):
        """
        Initialise l'adapter.

        Args:
            llm: Port LLM configuré (ex: ClaudeAdapter).
        """
        self._llm = llm

    async def analyze(
        self,
        account_id: int,
        emails: Sequence[Email],
        timeout_seconds: int = 30,
    ) -> WritingStyleProfile:
        """
        Analyse une collection d'emails pour extraire le style d'écriture.

        Args:
            account_id: ID du compte email de l'utilisateur.
            emails: Séquence d'emails envoyés à analyser.
            timeout_seconds: Timeout en secondes (défaut: 30).

        Returns:
            WritingStyleProfile avec les caractéristiques extraites.
        """
        start_time = time.time()

        # Filter valid emails
        valid_emails = [
            e for e in emails
            if e.body_text and len(e.body_text) >= self.MIN_EMAIL_LENGTH
        ]

        if not valid_emails:
            logger.warning(f"No valid emails to analyze for account {account_id}")
            return WritingStyleProfile.create_empty(account_id)

        # Build prompt
        user_prompt = self._build_user_prompt(valid_emails)

        try:
            result = await asyncio.wait_for(
                self._call_llm(user_prompt, STYLE_ANALYSIS_SYSTEM_PROMPT),
                timeout=timeout_seconds,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            if result is None:
                logger.warning(f"LLM returned no result for account {account_id}")
                return WritingStyleProfile.create_empty(account_id)

            # Calculate average email length
            avg_length = sum(len(e.body_text or "") for e in valid_emails) // len(valid_emails)

            return self._build_profile(
                account_id=account_id,
                email_count=len(valid_emails),
                avg_email_length=avg_length,
                llm_result=result,
                analysis_duration_ms=elapsed_ms,
            )

        except asyncio.TimeoutError:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.warning(f"Style analysis timeout after {elapsed_ms}ms for account {account_id}")
            return WritingStyleProfile.create_empty(account_id)

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Style analysis error: {e}")
            return WritingStyleProfile.create_empty(account_id)

    async def analyze_single(self, email: Email) -> Dict[str, Any]:
        """
        Analyse un seul email pour extraction incrémentale.

        Args:
            email: L'email envoyé à analyser.

        Returns:
            Dictionnaire avec les caractéristiques extraites.
        """
        if not email.body_text or len(email.body_text) < self.MIN_EMAIL_LENGTH:
            return {
                "common_words": [],
                "greetings": [],
                "closings": [],
                "sentence_length": 0.0,
                "email_length": len(email.body_text or ""),
            }

        user_prompt = f"""Analyze this email:

Subject: {email.subject or '(no subject)'}
Content:
{email.body_text[:1000]}

Extract the writing characteristics."""

        try:
            result = await asyncio.wait_for(
                self._call_llm(user_prompt, SINGLE_EMAIL_ANALYSIS_PROMPT),
                timeout=10,
            )

            if result is None:
                return self._extract_basic_features(email)

            return {
                "common_words": result.get("common_words", [])[:10],
                "greetings": result.get("greetings", []),
                "closings": result.get("closings", []),
                "sentence_length": float(result.get("sentence_length", 0)),
                "email_length": int(result.get("email_length", len(email.body_text or ""))),
            }

        except Exception as e:
            logger.warning(f"Single email analysis failed: {e}")
            return self._extract_basic_features(email)

    def _extract_basic_features(self, email: Email) -> Dict[str, Any]:
        """
        Extraction basique sans LLM (fallback).

        Args:
            email: L'email à analyser.

        Returns:
            Caractéristiques de base extraites.
        """
        body = email.body_text or ""
        lines = body.strip().split("\n")

        # Basic greeting detection
        greetings = []
        if lines:
            first_line = lines[0].strip().lower()
            for greeting in ["bonjour", "salut", "hello", "hi", "cher", "chère"]:
                if first_line.startswith(greeting):
                    greetings.append(lines[0].strip())
                    break

        # Basic closing detection
        closings = []
        if len(lines) > 1:
            last_lines = " ".join(lines[-3:]).lower()
            for closing in ["cordialement", "bien à vous", "à bientôt", "merci", "cdlt"]:
                if closing in last_lines:
                    closings.append(closing.capitalize())
                    break

        # Calculate sentence length
        sentences = re.split(r'[.!?]+', body)
        sentences = [s for s in sentences if s.strip()]
        avg_sentence = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)

        return {
            "common_words": [],
            "greetings": greetings,
            "closings": closings,
            "sentence_length": avg_sentence,
            "email_length": len(body),
        }

    def _build_user_prompt(self, emails: Sequence[Email]) -> str:
        """
        Construit le prompt utilisateur avec les emails à analyser.

        Args:
            emails: Liste des emails.

        Returns:
            Prompt formaté pour Claude.
        """
        lines = [
            f"Analyze the writing style from {len(emails)} emails written by this user.",
            "",
            "--- SENT EMAILS ---",
        ]

        for i, email in enumerate(emails[:10], 1):  # Limit to 10 emails
            subject = email.subject or "(no subject)"
            date_str = email.date.strftime("%Y-%m-%d") if email.date else "unknown"

            # Truncate body for context window efficiency
            body = email.body_text or ""
            if len(body) > 800:
                body = body[:800] + "..."

            lines.append(f"\n[Email {i}] Sent on {date_str}")
            lines.append(f"Subject: {subject}")
            lines.append(f"Content:\n{body}")

        lines.append("\n--- END OF EMAILS ---")
        lines.append("\nAnalyze the consistent writing patterns and respond with JSON only.")

        return "\n".join(lines)

    async def _call_llm(self, user_prompt: str, system_prompt: str) -> Optional[Dict[str, Any]]:
        """
        Appelle le LLM et parse la réponse JSON.

        Args:
            user_prompt: Prompt utilisateur.
            system_prompt: Prompt système.

        Returns:
            Dictionnaire avec le résultat ou None.
        """
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._llm.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=1024,
            ),
        )

        if not response or not response.content:
            return None

        try:
            content = response.content.strip()
            # Handle potential markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response content: {response.content}")
            return None

    def _build_profile(
        self,
        account_id: int,
        email_count: int,
        avg_email_length: int,
        llm_result: Dict[str, Any],
        analysis_duration_ms: int,
    ) -> WritingStyleProfile:
        """
        Construit le WritingStyleProfile à partir du résultat LLM.

        Args:
            account_id: ID du compte.
            email_count: Nombre d'emails analysés.
            avg_email_length: Longueur moyenne des emails.
            llm_result: Résultat JSON du LLM.
            analysis_duration_ms: Durée de l'analyse.

        Returns:
            WritingStyleProfile complet.
        """
        # Extract formality level
        formality_str = llm_result.get("formality_level", "mixed")
        try:
            formality = FormalityLevel(formality_str.lower())
        except ValueError:
            formality = FormalityLevel.MIXED

        # Extract common words (max 20)
        common_words = llm_result.get("common_words", [])
        if isinstance(common_words, list):
            common_words = [str(w) for w in common_words[:20]]
        else:
            common_words = []

        # Extract greetings (max 5)
        greetings = llm_result.get("preferred_greetings", [])
        if isinstance(greetings, list):
            from app.prompts.identity import is_placeholder_style_value
            greetings = [
                str(g)
                for g in greetings
                if g and not is_placeholder_style_value(g)
            ][:5]
        else:
            greetings = []

        # Extract closings (max 5)
        closings = llm_result.get("preferred_closings", [])
        if isinstance(closings, list):
            from app.prompts.identity import is_placeholder_style_value
            closings = [
                str(c)
                for c in closings
                if c and not is_placeholder_style_value(c)
            ][:5]
        else:
            closings = []

        # Drop LLM "no signal" placeholders ("Unknown", "Unknown (forwarded
        # content)", "Salut Unknown") so the DEFAULT style never STORES them and
        # later leaks into a draft (the user-reported bad greeting/closing,
        # 2026-06-01). Belt-and-suspenders with the consumer-side guard in
        # identity._compute_greeting_hint / _compute_closing_hint.
        from app.prompts.identity import is_placeholder_style_value
        greetings = [g for g in greetings if not is_placeholder_style_value(g)]
        closings = [c for c in closings if not is_placeholder_style_value(c)]

        # Extract signature
        signature = llm_result.get("typical_signature")
        if signature and not isinstance(signature, str):
            signature = None

        # Extract sentence length
        avg_sentence_length = llm_result.get("avg_sentence_length", 15.0)
        try:
            avg_sentence_length = float(avg_sentence_length)
        except (TypeError, ValueError):
            avg_sentence_length = 15.0

        # PR4 follow-up — `uses_contractions` and `uses_emojis` no longer
        # extracted (the LLM prompt was paying for fields that were never
        # consumed in any draft prompt after the PR3 unification).
        return WritingStyleProfile(
            account_id=account_id,
            analyzed_at=datetime.utcnow(),
            email_count=email_count,
            common_words=common_words,
            avg_sentence_length=avg_sentence_length,
            formality_level=formality,
            preferred_greetings=greetings,
            preferred_closings=closings,
            typical_signature=signature,
            avg_email_length=avg_email_length,
            analysis_duration_ms=analysis_duration_ms,
        )

    def is_available(self) -> bool:
        """Vérifie si le LLM est disponible."""
        return self._llm.is_available()
