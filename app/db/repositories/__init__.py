"""
Agentys Database Repositories.

Repository pattern implementation for data access abstraction.
"""

from app.db.repositories.base import BaseRepository
from app.db.repositories.account_repository import AccountRepository
from app.db.repositories.contact_repository import ContactRepository
from app.db.repositories.draft_repository import DraftRepository
from app.db.repositories.email_repository import EmailRepository
from app.db.repositories.onboarding_repository import OnboardingRepository
from app.db.repositories.relationship_repository import RelationshipRepository

__all__ = [
    "BaseRepository",
    "AccountRepository",
    "ContactRepository",
    "DraftRepository",
    "EmailRepository",
    "OnboardingRepository",
    "RelationshipRepository",
]
