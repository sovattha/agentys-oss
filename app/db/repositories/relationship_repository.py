# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Repository for managing relationship type overrides.
"""

from typing import Optional, Sequence, Type

from sqlalchemy import select

from app.db.models.relationship_override import RelationshipOverride
from app.db.repositories.base import BaseRepository


class RelationshipRepository(BaseRepository[RelationshipOverride]):
    """
    Repository for RelationshipOverride entities.

    Provides CRUD operations plus specialized queries for
    managing user overrides of relationship type detection.
    """

    model: Type[RelationshipOverride] = RelationshipOverride

    def get_override(
        self, account_id: int, contact_email: str
    ) -> Optional[RelationshipOverride]:
        """
        Get the relationship override for a specific account and contact.

        Args:
            account_id: The user's account ID.
            contact_email: Email address of the contact.

        Returns:
            The override if exists, None otherwise.
        """
        stmt = select(RelationshipOverride).where(
            RelationshipOverride.account_id == account_id,
            RelationshipOverride.contact_email == contact_email,
        )
        return self.session.scalar(stmt)

    def save_override(
        self,
        account_id: int,
        contact_email: str,
        relationship_type: str,
    ) -> RelationshipOverride:
        """
        Create or update a relationship override.

        If an override already exists for the account/contact combination,
        it will be updated. Otherwise, a new override is created.

        Args:
            account_id: The user's account ID.
            contact_email: Email address of the contact.
            relationship_type: The relationship type to set.

        Returns:
            The created or updated override.
        """
        existing = self.get_override(account_id, contact_email)

        if existing:
            existing.relationship_type = relationship_type
            with self.session.begin_nested():
                self.session.flush()
            return existing
        else:
            override = RelationshipOverride(
                account_id=account_id,
                contact_email=contact_email,
                relationship_type=relationship_type,
            )
            return self.create(override)

    def delete_override(self, account_id: int, contact_email: str) -> bool:
        """
        Delete a relationship override.

        Args:
            account_id: The user's account ID.
            contact_email: Email address of the contact.

        Returns:
            True if deleted, False if not found.
        """
        override = self.get_override(account_id, contact_email)
        if override:
            self.delete(override)
            return True
        return False

    def get_overrides_for_account(
        self, account_id: int
    ) -> Sequence[RelationshipOverride]:
        """
        Get all relationship overrides for an account.

        Args:
            account_id: The user's account ID.

        Returns:
            List of all overrides for the account.
        """
        stmt = (
            select(RelationshipOverride)
            .where(RelationshipOverride.account_id == account_id)
            .order_by(RelationshipOverride.updated_at.desc())
        )
        return self.session.scalars(stmt).all()

    def get_override_history(
        self, account_id: int, contact_email: str
    ) -> Optional[RelationshipOverride]:
        """
        Get the override with history metadata.

        For now this returns the same as get_override.
        Future enhancement could include audit log.

        Args:
            account_id: The user's account ID.
            contact_email: Email address of the contact.

        Returns:
            The override if exists, None otherwise.
        """
        return self.get_override(account_id, contact_email)
