# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Service for detecting and managing relationship types with contacts.
"""

import logging
from typing import Dict, List, Optional, Sequence, Union

from app.db.repositories.relationship_repository import RelationshipRepository
from app.db.models.relationship_override import RelationshipOverride
from app.domain.entities.relationship_type import (
    RelationshipType,
    CommunicationFrequency,
    RelationshipDetection,
)

logger = logging.getLogger(__name__)


class RelationshipDetectionService:
    """
    Service for detecting and managing relationship types.

    Combines automatic detection via LLM with user overrides.
    User overrides always take precedence over automatic detection.

    Attributes:
        _repository: Repository for storing/retrieving user overrides.
        _detector: Adapter for automatic relationship detection.
    """

    def __init__(
        self,
        repository: Optional[RelationshipRepository] = None,
        detector=None,
    ):
        """
        Initialize the service.

        Args:
            repository: Repository for relationship overrides.
            detector: Adapter for automatic detection (optional).
        """
        self._repository = repository
        self._detector = detector

    def get_relationship(
        self,
        account_id: int,
        contact_email: str,
    ) -> RelationshipDetection:
        """
        Get the relationship type for a contact.

        First checks for user override, then falls back to automatic detection.

        Args:
            account_id: The user's account ID.
            contact_email: Email address of the contact.

        Returns:
            RelationshipDetection with the relationship info.
        """
        # Check for user override first
        if self._repository:
            override = self._repository.get_override(account_id, contact_email)
            if override:
                return self._create_detection_from_override(
                    override, account_id, contact_email
                )

        # Fall back to automatic detection
        if self._detector:
            detection = self._detector.detect(account_id, contact_email)
            if detection:
                return detection

        # Return unknown if no detection available
        return RelationshipDetection(
            contact_email=contact_email,
            account_id=account_id,
            relationship_type=RelationshipType.UNKNOWN,
            confidence=0.0,
            communication_frequency=CommunicationFrequency.SPORADIC,
        )

    def set_relationship_override(
        self,
        account_id: int,
        contact_email: str,
        relationship_type: Union[RelationshipType, str],
    ) -> RelationshipDetection:
        """
        Set a manual override for a contact's relationship type.

        Args:
            account_id: The user's account ID.
            contact_email: Email address of the contact.
            relationship_type: The relationship type to set.

        Returns:
            RelationshipDetection with the override info.
        """
        # Convert string to enum if needed
        if isinstance(relationship_type, str):
            relationship_type = RelationshipType(relationship_type)

        if not self._repository:
            raise ValueError("Repository not configured")

        override = self._repository.save_override(
            account_id=account_id,
            contact_email=contact_email,
            relationship_type=relationship_type.value,
        )

        return self._create_detection_from_override(
            override, account_id, contact_email
        )

    def delete_relationship_override(
        self,
        account_id: int,
        contact_email: str,
    ) -> bool:
        """
        Delete a relationship override.

        Args:
            account_id: The user's account ID.
            contact_email: Email address of the contact.

        Returns:
            True if deleted, False if not found.
        """
        if not self._repository:
            return False

        return self._repository.delete_override(account_id, contact_email)

    def get_all_overrides(
        self,
        account_id: int,
    ) -> Sequence[RelationshipOverride]:
        """
        Get all relationship overrides for an account.

        Args:
            account_id: The user's account ID.

        Returns:
            List of all overrides for the account.
        """
        if not self._repository:
            return []

        return self._repository.get_overrides_for_account(account_id)

    def batch_get_relationships(
        self,
        account_id: int,
        contact_emails: List[str],
    ) -> Dict[str, RelationshipDetection]:
        """
        Get relationships for multiple contacts at once.

        Args:
            account_id: The user's account ID.
            contact_emails: List of contact email addresses.

        Returns:
            Dictionary mapping email to RelationshipDetection.
        """
        results = {}
        for email in contact_emails:
            results[email] = self.get_relationship(account_id, email)
        return results

    def _create_detection_from_override(
        self,
        override: RelationshipOverride,
        account_id: int,
        contact_email: str,
    ) -> RelationshipDetection:
        """
        Create a RelationshipDetection from a user override.

        Args:
            override: The database override record.
            account_id: The user's account ID.
            contact_email: Email address of the contact.

        Returns:
            RelationshipDetection marked as user override.
        """
        return RelationshipDetection(
            contact_email=contact_email,
            account_id=account_id,
            relationship_type=RelationshipType(override.relationship_type),
            confidence=1.0,  # User overrides have full confidence
            communication_frequency=CommunicationFrequency.SPORADIC,  # Unknown for overrides
            is_user_override=True,
        )
