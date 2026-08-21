"""
SQLAlchemy declarative base and common model mixins.
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Declarative base class for all models.

    All models should inherit from this class.
    """

    pass


class TimestampMixin:
    """
    Mixin that adds created_at and updated_at timestamp columns.

    Use this for models that need to track creation and modification times.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
