# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Base repository with common CRUD operations.
"""

from typing import Generic, TypeVar, Type, Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models.base import Base

# Type variable for model classes
T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """
    Base repository providing common CRUD operations.

    Generic type T should be a SQLAlchemy model class.

    Attributes:
        model: The SQLAlchemy model class this repository manages.
        session: The SQLAlchemy session for database operations.
    """

    model: Type[T]

    def __init__(self, session: Session):
        """
        Initialize the repository with a session.

        Args:
            session: SQLAlchemy session for database operations.
        """
        self.session = session

    def get(self, id: int) -> Optional[T]:
        """
        Get a single entity by ID.

        Args:
            id: Primary key ID of the entity.

        Returns:
            The entity if found, None otherwise.
        """
        return self.session.get(self.model, id)

    def get_all(self, limit: int = 100, offset: int = 0) -> Sequence[T]:
        """
        Get all entities with pagination.

        Args:
            limit: Maximum number of results to return.
            offset: Number of results to skip.

        Returns:
            List of entities.
        """
        stmt = select(self.model).limit(limit).offset(offset)
        return self.session.scalars(stmt).all()

    def count(self) -> int:
        """
        Count total number of entities.

        Returns:
            Total count of entities.
        """
        stmt = select(func.count(self.model.id))
        return self.session.scalar(stmt) or 0

    def create(self, entity: T) -> T:
        """
        Create a new entity.

        Args:
            entity: The entity to create.

        Returns:
            The created entity with ID populated.
        """
        self.session.add(entity)
        self.session.flush()
        return entity

    def create_all(self, entities: Sequence[T]) -> Sequence[T]:
        """
        Create multiple entities in bulk.

        Args:
            entities: List of entities to create.

        Returns:
            List of created entities with IDs populated.
        """
        self.session.add_all(entities)
        self.session.flush()
        return entities

    def update(self, entity: T) -> T:
        """
        Update an existing entity.

        Args:
            entity: The entity to update (must have ID).

        Returns:
            The updated entity.
        """
        self.session.merge(entity)
        self.session.flush()
        return entity

    def delete(self, entity: T) -> None:
        """
        Delete an entity.

        Args:
            entity: The entity to delete.
        """
        self.session.delete(entity)
        self.session.flush()

    def delete_by_id(self, id: int) -> bool:
        """
        Delete an entity by ID.

        Args:
            id: Primary key ID of the entity to delete.

        Returns:
            True if entity was deleted, False if not found.
        """
        entity = self.get(id)
        if entity:
            self.delete(entity)
            return True
        return False

    def exists(self, id: int) -> bool:
        """
        Check if an entity exists by ID.

        Args:
            id: Primary key ID to check.

        Returns:
            True if entity exists, False otherwise.
        """
        stmt = select(func.count(self.model.id)).where(self.model.id == id)
        return (self.session.scalar(stmt) or 0) > 0
