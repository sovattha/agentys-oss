# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter for detecting relationship types using LLM analysis.
"""

import json
import logging
from typing import Optional, Sequence

from app.domain.entities.relationship_type import (
    RelationshipType,
    CommunicationFrequency,
    RelationshipDetection,
)
from app.domain.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)


RELATIONSHIP_DETECTION_SYSTEM_PROMPT = """You are an email relationship analyzer. Your task is to determine the type of relationship between the email user and a contact based on their email history.

Analyze the email exchanges and determine:
1. The relationship type: one of "colleague", "client", "friend", "manager", "vendor", or "unknown"
2. Your confidence in this assessment (0.0 to 1.0)
3. The communication frequency: "daily", "weekly", "monthly", or "sporadic"
4. Typical communication hours (list of hours 0-23)
5. Brief reasoning for your classification

IMPORTANT: Respond ONLY with valid JSON in this exact format:
{
    "relationship_type": "colleague|client|friend|manager|vendor|unknown",
    "confidence": 0.85,
    "communication_frequency": "daily|weekly|monthly|sporadic",
    "typical_hours": [9, 10, 11, 14, 15, 16],
    "reasoning": "Brief explanation of classification"
}

Indicators for each relationship type:
- COLLEAGUE: Work discussions, shared projects, company-internal topics, professional but familiar tone
- CLIENT: Business inquiries, service requests, formal professional tone, external company domain
- FRIEND: Personal topics, casual language, emotional content, non-work hours
- MANAGER: Task assignments, approvals, performance discussions, hierarchical language
- VENDOR: Sales pitches, product info, invoices, external business services
- UNKNOWN: Insufficient data or ambiguous signals"""


class RelationshipDetectorAdapter:
    """
    Adapter that uses LLM to detect relationship types from email history.

    Analyzes email content, tone, frequency, and timing to classify
    the relationship between the user and a contact.

    Attributes:
        _llm: LLM port for making inference calls.
    """

    def __init__(self, llm: LLMPort):
        """
        Initialize the adapter.

        Args:
            llm: LLM port for making calls (e.g., ClaudeAdapter).
        """
        self._llm = llm

    def detect(
        self,
        account_id: int,
        contact_email: str,
        emails: Sequence,
    ) -> Optional[RelationshipDetection]:
        """
        Detect the relationship type for a contact.

        Args:
            account_id: The user's account ID.
            contact_email: Email address of the contact.
            emails: Sequence of emails to analyze.

        Returns:
            RelationshipDetection with classification, or None if no emails.
        """
        if not emails:
            return None

        user_prompt = self._build_user_prompt(contact_email, emails)

        try:
            response = self._llm.complete(
                system=RELATIONSHIP_DETECTION_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=512,
            )

            if not response or not response.content:
                logger.warning(
                    f"LLM returned no response for relationship detection of {contact_email}"
                )
                return self._create_unknown_detection(account_id, contact_email)

            # Parse JSON response
            result = self._parse_response(response.content)

            if result is None:
                return self._create_unknown_detection(account_id, contact_email)

            return self._build_detection(account_id, contact_email, result)

        except Exception as e:
            logger.error(f"Relationship detection error for {contact_email}: {e}")
            return self._create_unknown_detection(account_id, contact_email)

    def _build_user_prompt(self, contact_email: str, emails: Sequence) -> str:
        """
        Build the user prompt with email data.

        Args:
            contact_email: Email of the contact.
            emails: List of emails to analyze.

        Returns:
            Formatted prompt for LLM.
        """
        lines = [
            f"Analyze the relationship with contact: {contact_email}",
            f"Total emails to analyze: {len(emails)}",
            "",
            "--- EMAIL HISTORY ---",
        ]

        for i, email in enumerate(emails[:20], 1):  # Limit to 20 emails
            direction = "FROM" if getattr(email, "sender", "") == contact_email else "TO"
            date_str = (
                email.date.strftime("%Y-%m-%d %H:%M")
                if getattr(email, "date", None)
                else "unknown"
            )
            subject = getattr(email, "subject", None) or "(no subject)"

            # Get body, truncate if too long
            body = getattr(email, "body_text", None) or getattr(email, "snippet", "") or ""
            if len(body) > 500:
                body = body[:500] + "..."

            lines.append(f"\n[Email {i}] {direction} {contact_email} on {date_str}")
            lines.append(f"Subject: {subject}")
            if body:
                lines.append(f"Content: {body}")

        lines.append("\n--- END OF HISTORY ---")
        lines.append("\nAnalyze and respond with JSON only.")

        return "\n".join(lines)

    def _parse_response(self, content: str) -> Optional[dict]:
        """
        Parse the LLM response as JSON.

        Args:
            content: Raw response content.

        Returns:
            Parsed dictionary or None on error.
        """
        try:
            # Handle markdown code blocks
            content = content.strip()
            if content.startswith("```"):
                # Extract content between code blocks
                parts = content.split("```")
                if len(parts) >= 2:
                    content = parts[1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.strip()

            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse relationship detection response: {e}")
            logger.debug(f"Response content: {content}")
            return None

    def _build_detection(
        self,
        account_id: int,
        contact_email: str,
        result: dict,
    ) -> RelationshipDetection:
        """
        Build RelationshipDetection from parsed LLM result.

        Args:
            account_id: The user's account ID.
            contact_email: Email of the contact.
            result: Parsed JSON result from LLM.

        Returns:
            RelationshipDetection with classification.
        """
        # Parse relationship type
        type_str = result.get("relationship_type", "unknown").lower()
        try:
            relationship_type = RelationshipType(type_str)
        except ValueError:
            relationship_type = RelationshipType.UNKNOWN

        # Parse confidence
        confidence = result.get("confidence", 0.5)
        confidence = max(0.0, min(1.0, float(confidence)))

        # Parse frequency
        freq_str = result.get("communication_frequency", "sporadic").lower()
        try:
            frequency = CommunicationFrequency(freq_str)
        except ValueError:
            frequency = CommunicationFrequency.SPORADIC

        # Parse typical hours
        typical_hours = result.get("typical_hours", [])
        if isinstance(typical_hours, list):
            typical_hours = [
                h for h in typical_hours
                if isinstance(h, int) and 0 <= h <= 23
            ]
        else:
            typical_hours = []

        return RelationshipDetection(
            contact_email=contact_email,
            account_id=account_id,
            relationship_type=relationship_type,
            confidence=confidence,
            communication_frequency=frequency,
            typical_hours=typical_hours,
            is_user_override=False,
        )

    def _create_unknown_detection(
        self,
        account_id: int,
        contact_email: str,
    ) -> RelationshipDetection:
        """
        Create a detection with UNKNOWN type.

        Args:
            account_id: The user's account ID.
            contact_email: Email of the contact.

        Returns:
            RelationshipDetection with UNKNOWN type.
        """
        return RelationshipDetection(
            contact_email=contact_email,
            account_id=account_id,
            relationship_type=RelationshipType.UNKNOWN,
            confidence=0.0,
            communication_frequency=CommunicationFrequency.SPORADIC,
            is_user_override=False,
        )

    def is_available(self) -> bool:
        """Check if the LLM is available."""
        return self._llm.is_available()
