# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port for per-contact style profile storage (PR6 follow-up).

Splits the per-contact dimension out of the JSON-serialized
``WritingStyleProfile`` into its own structured store. Today the contact
profiles live as a ``Dict[str, Any]`` field on the user-level profile JSON
file (``data/learning/style_profile_<account_id>.json``) — that has two
known issues :

1. **Concurrent-write corruption** — onboarding runs 4 agents in parallel
   (``ThreadPoolExecutor(max_workers=4)``) and each agent's completion can
   trigger a ``WritingStyleProfile`` save. Without a global lock around
   ``write_text`` (currently ``_FILE_LOCK`` in ``writing_style_store.py``),
   two simultaneous writes interleave on Windows and leave trailing garbage,
   forcing JSONDecodeError on the next load.
2. **Read-amplification** — every draft request loads the full profile JSON
   (account-wide metrics, preferred greetings, signature, all contacts)
   just to look up one contact's nickname. With ~200 contacts per account
   this becomes meaningful disk I/O per request.

This port + its SQLite adapter address both : per-row primary key
``(account_id, email)`` removes the need for a global lock, and lookup
is O(1) regardless of contact count.

PR6 status (deferred runtime adoption) :
    The port and adapter ship as additive infrastructure. The runtime path
    still uses ``WritingStyleProfile.contact_profiles`` as the source of
    truth — flipping is the senior dev's call once the migration script
    is reviewed and an integration test covers the JSON↔SQLite copy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities.writing_style import ContactStyleProfile


class ContactStyleStorePort(ABC):
    """Per-contact style profile CRUD.

    All methods are scoped by ``account_id`` so a multi-account install
    never leaks contacts across users.
    """

    @abstractmethod
    def get(self, account_id: int, email: str) -> Optional[ContactStyleProfile]:
        """Fetch a contact's style profile, or ``None`` if absent.

        ``email`` is matched case-insensitively (the row stores the
        lower-cased form to match the JSON dict-key convention).
        """

    @abstractmethod
    def upsert(self, account_id: int, profile: ContactStyleProfile) -> bool:
        """Insert-or-update a contact's profile.

        Returns ``True`` on success. Implementations MUST be safe under
        concurrent writes — that's the entire point of this port.
        """

    @abstractmethod
    def delete(self, account_id: int, email: str) -> bool:
        """Remove a contact's profile. Returns ``False`` if it didn't exist."""

    @abstractmethod
    def list_for_account(self, account_id: int) -> List[ContactStyleProfile]:
        """Return every contact profile for ``account_id``.

        Used by the Training UI to render the contact list, and by the
        migration script to bulk-copy from the JSON dict to SQLite.
        """

    @abstractmethod
    def count_for_account(self, account_id: int) -> int:
        """Cheap O(1) count for stats / stats endpoints."""

    @abstractmethod
    def replace_account(
        self, account_id: int, profiles: List[ContactStyleProfile]
    ) -> int:
        """Replace all contact profiles for ``account_id`` atomically.

        Used by the JSON→SQLite migration : load the dict, build the
        list, hand it here. Returns the number of rows inserted.
        Operates inside a single transaction so a partial failure leaves
        the previous state intact.
        """
