# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Service for aggregating context transparency data.

Provides users visibility into what context the AI used to generate drafts.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List

from app.domain.entities.context_transparency import (
    AnalyzedEmailSummary,
    StyleProfileSummary,
    RelationshipSummary,
    ContextTransparencyData,
)
from app.domain.entities.writing_style import WritingStyleProfile

logger = logging.getLogger(__name__)


class ContextTransparencyService:
    """
    Service for aggregating and providing context transparency data.

    Combines data from multiple services to show users what context
    was used by the AI to generate email drafts.

    Attributes:
        _relationship_service: Service for relationship detection.
        _style_service: Service for writing style profiles.
        _contact_context_provider: Provider for contact context and analyzed emails.
    """

    # Approximate tokens per character (rough estimate for GPT-style models)
    TOKENS_PER_CHAR = 0.25

    def __init__(
        self,
        relationship_service=None,
        style_service=None,
        contact_context_provider=None,
    ):
        """
        Initialize the service.

        Args:
            relationship_service: Service for relationship detection.
            style_service: Service for writing style profiles.
            contact_context_provider: Provider for contact context data.
        """
        self._relationship_service = relationship_service
        self._style_service = style_service
        self._contact_context_provider = contact_context_provider

    def get_transparency_data(
        self,
        session_id: str,
        account_id: int,
        contact_email: str,
    ) -> ContextTransparencyData:
        """
        Get aggregated context transparency data.

        Collects data from relationship service, style service, and
        contact context provider to build a complete transparency view.

        Args:
            session_id: The draft generation session ID.
            account_id: The user's account ID.
            contact_email: Email address of the contact.

        Returns:
            ContextTransparencyData with all aggregated context info.
        """
        logger.debug(
            f"Getting transparency data for session={session_id}, "
            f"account={account_id}, contact={contact_email}"
        )

        # Aggregate relationship data
        relationship_summary = None
        if self._relationship_service:
            try:
                detection = self._relationship_service.get_relationship(
                    account_id=account_id,
                    contact_email=contact_email,
                )
                relationship_summary = self._build_relationship_summary(detection)
            except Exception as e:
                logger.warning(f"Failed to get relationship data: {e}")

        # Aggregate style profile data
        style_profile_summary = None
        if self._style_service:
            try:
                profile = self._style_service.get_profile(account_id)
                if profile:
                    style_profile_summary = self._build_style_profile_summary(profile)
            except Exception as e:
                logger.warning(f"Failed to get style profile: {e}")

        # Aggregate analyzed emails
        analyzed_emails: List[AnalyzedEmailSummary] = []
        if self._contact_context_provider:
            try:
                raw_emails = self._contact_context_provider.get_analyzed_emails(
                    account_id=account_id,
                    contact_email=contact_email,
                )
                for raw_email in raw_emails:
                    analyzed_emails.append(self._build_email_summary(raw_email))
            except Exception as e:
                logger.warning(f"Failed to get analyzed emails: {e}")

        # Build the transparency data
        data = ContextTransparencyData(
            session_id=session_id,
            contact_email=contact_email,
            analyzed_emails=analyzed_emails,
            style_profile=style_profile_summary,
            relationship=relationship_summary,
            analysis_timestamp=datetime.utcnow(),
            total_context_tokens=0,  # Will be calculated
        )

        # Calculate token count
        data.total_context_tokens = self._estimate_token_count(data)

        return data

    def _build_relationship_summary(self, detection) -> RelationshipSummary:
        """
        Build a RelationshipSummary from a RelationshipDetection.

        Args:
            detection: RelationshipDetection from the relationship service.

        Returns:
            RelationshipSummary with simplified data.
        """
        return RelationshipSummary(
            relationship_type=detection.relationship_type.value,
            confidence=detection.confidence,
            communication_frequency=detection.communication_frequency.value,
        )

    def _build_style_profile_summary(
        self, profile: WritingStyleProfile
    ) -> StyleProfileSummary:
        """
        Build a StyleProfileSummary from a WritingStyleProfile.

        Args:
            profile: WritingStyleProfile from the style service.

        Returns:
            StyleProfileSummary with relevant data.
        """
        # Calculate confidence based on email count
        # More emails analyzed = higher confidence
        confidence = min(profile.email_count / 10.0, 1.0)

        return StyleProfileSummary(
            formality_level=profile.formality_level.value,
            characteristic_phrases=profile.common_words[:10],  # Top 10 phrases
            greeting_style=profile.preferred_greetings[0] if profile.preferred_greetings else "",
            closing_style=profile.preferred_closings[0] if profile.preferred_closings else "",
            confidence=confidence,
        )

    def _build_email_summary(self, raw_data: Dict[str, Any]) -> AnalyzedEmailSummary:
        """
        Build an AnalyzedEmailSummary from raw email data.

        Args:
            raw_data: Dictionary with email data.

        Returns:
            AnalyzedEmailSummary entity.
        """
        return AnalyzedEmailSummary(
            email_id=raw_data.get("email_id", ""),
            subject=raw_data.get("subject", ""),
            sender=raw_data.get("sender", ""),
            date=raw_data.get("date", datetime.utcnow()),
            relevant_excerpts=raw_data.get("relevant_excerpts", []),
            relevance_score=raw_data.get("relevance_score", 0.0),
        )

    def _estimate_token_count(self, data: ContextTransparencyData) -> int:
        """
        Estimate the token count for the context data.

        Uses a simple character-based estimation.

        Args:
            data: The context transparency data.

        Returns:
            Estimated token count.
        """
        total_chars = 0

        # Count session and contact info
        total_chars += len(data.session_id)
        total_chars += len(data.contact_email)

        # Count analyzed emails
        for email in data.analyzed_emails:
            total_chars += len(email.subject)
            total_chars += len(email.sender)
            for excerpt in email.relevant_excerpts:
                total_chars += len(excerpt)

        # Count style profile
        if data.style_profile:
            total_chars += len(data.style_profile.formality_level)
            total_chars += len(data.style_profile.greeting_style)
            total_chars += len(data.style_profile.closing_style)
            for phrase in data.style_profile.characteristic_phrases:
                total_chars += len(phrase)

        # Count relationship
        if data.relationship:
            total_chars += len(data.relationship.relationship_type)
            total_chars += len(data.relationship.communication_frequency)

        return int(total_chars * self.TOKENS_PER_CHAR)
