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
