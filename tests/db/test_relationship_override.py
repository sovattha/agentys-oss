# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for RelationshipOverride model and repository.
"""

import pytest
from datetime import datetime

from app.db.models import Account
from app.db.models.relationship_override import RelationshipOverride
from app.domain.entities.relationship_type import RelationshipType


@pytest.fixture(autouse=True)
def _seed_accounts(session):
    """Pre-populate accounts required by FK constraints on relationship_overrides."""
    for acct_id, email in [(1, "account1@test.com"), (2, "account2@test.com")]:
        existing = session.get(Account, acct_id)
        if not existing:
            session.add(Account(id=acct_id, email=email, provider="gmail"))
    session.commit()


class TestRelationshipOverrideModel:
    """Tests for RelationshipOverride SQLAlchemy model."""

    def test_create_relationship_override(self, session):
        """Test creating a RelationshipOverride record."""
        override = RelationshipOverride(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.CLIENT.value,
        )
        session.add(override)
        session.commit()

        assert override.id is not None
        assert override.account_id == 1
        assert override.contact_email == "john@example.com"
        assert override.relationship_type == "client"
        assert isinstance(override.created_at, datetime)
        assert isinstance(override.updated_at, datetime)

    def test_update_relationship_override(self, session):
        """Test updating relationship type."""
        override = RelationshipOverride(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.COLLEAGUE.value,
        )
        session.add(override)
        session.commit()

        original_created_at = override.created_at

        # Update
        override.relationship_type = RelationshipType.CLIENT.value
        session.commit()

        assert override.relationship_type == "client"
        assert override.created_at == original_created_at
        # updated_at should be updated (may be same if within same second)

    def test_unique_constraint_account_contact(self, session):
        """Test unique constraint on (account_id, contact_email)."""
        override1 = RelationshipOverride(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.CLIENT.value,
        )
        session.add(override1)
        session.commit()

        # Try to add duplicate
        override2 = RelationshipOverride(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.COLLEAGUE.value,
        )
        session.add(override2)

        with pytest.raises(Exception):  # IntegrityError
            session.commit()

    def test_different_accounts_same_contact(self, session):
        """Test that different accounts can have same contact."""
        override1 = RelationshipOverride(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.CLIENT.value,
        )
        override2 = RelationshipOverride(
            account_id=2,
            contact_email="john@example.com",
            relationship_type=RelationshipType.COLLEAGUE.value,
        )
        session.add(override1)
        session.add(override2)
        session.commit()

        assert override1.id != override2.id

    def test_query_by_account_id(self, session):
        """Test querying by account_id."""
        for i in range(3):
            override = RelationshipOverride(
                account_id=1,
                contact_email=f"contact{i}@example.com",
                relationship_type=RelationshipType.CLIENT.value,
            )
            session.add(override)
        session.commit()

        results = session.query(RelationshipOverride).filter_by(account_id=1).all()
        assert len(results) == 3


class TestRelationshipRepository:
    """Tests for RelationshipRepository."""

    def test_get_override_not_found(self, session):
        """Test get_override returns None when not found."""
        from app.db.repositories.relationship_repository import RelationshipRepository

        repo = RelationshipRepository(session)
        result = repo.get_override(account_id=1, contact_email="nonexistent@example.com")
        assert result is None

    def test_get_override_found(self, session):
        """Test get_override returns override when found."""
        from app.db.repositories.relationship_repository import RelationshipRepository

        # Create override
        override = RelationshipOverride(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.CLIENT.value,
        )
        session.add(override)
        session.commit()

        repo = RelationshipRepository(session)
        result = repo.get_override(account_id=1, contact_email="john@example.com")

        assert result is not None
        assert result.relationship_type == "client"

    def test_save_override_creates_new(self, session):
        """Test save_override creates new when not exists."""
        from app.db.repositories.relationship_repository import RelationshipRepository

        repo = RelationshipRepository(session)
        result = repo.save_override(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.CLIENT.value,
        )
        session.commit()

        assert result.id is not None
        assert result.relationship_type == "client"

    def test_save_override_updates_existing(self, session):
        """Test save_override updates when exists."""
        from app.db.repositories.relationship_repository import RelationshipRepository

        # Create initial
        override = RelationshipOverride(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.COLLEAGUE.value,
        )
        session.add(override)
        session.commit()
        original_id = override.id

        # Update via repository
        repo = RelationshipRepository(session)
        result = repo.save_override(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.CLIENT.value,
        )
        session.commit()

        assert result.id == original_id
        assert result.relationship_type == "client"

    def test_delete_override(self, session):
        """Test delete_override removes override."""
        from app.db.repositories.relationship_repository import RelationshipRepository

        # Create override
        override = RelationshipOverride(
            account_id=1,
            contact_email="john@example.com",
            relationship_type=RelationshipType.CLIENT.value,
        )
        session.add(override)
        session.commit()

        repo = RelationshipRepository(session)
        deleted = repo.delete_override(account_id=1, contact_email="john@example.com")
        session.commit()

        assert deleted is True
        assert repo.get_override(account_id=1, contact_email="john@example.com") is None

    def test_delete_override_not_found(self, session):
        """Test delete_override returns False when not found."""
        from app.db.repositories.relationship_repository import RelationshipRepository

        repo = RelationshipRepository(session)
        deleted = repo.delete_override(account_id=1, contact_email="nonexistent@example.com")

        assert deleted is False

    def test_get_overrides_for_account(self, session):
        """Test get_overrides_for_account returns all for account."""
        from app.db.repositories.relationship_repository import RelationshipRepository

        # Create multiple overrides for account 1
        for i in range(3):
            override = RelationshipOverride(
                account_id=1,
                contact_email=f"contact{i}@example.com",
                relationship_type=RelationshipType.CLIENT.value,
            )
            session.add(override)

        # Create one for account 2
        override_other = RelationshipOverride(
            account_id=2,
            contact_email="other@example.com",
            relationship_type=RelationshipType.COLLEAGUE.value,
        )
        session.add(override_other)
        session.commit()

        repo = RelationshipRepository(session)
        results = repo.get_overrides_for_account(account_id=1)

        assert len(results) == 3
        for r in results:
            assert r.account_id == 1
