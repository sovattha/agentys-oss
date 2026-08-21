# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapters pour les modules legacy.

Ces adapters wrappent les modules legacy existants
et implementent les ports de la Clean Architecture.

Architecture:
- JsonFileStore: Classe de base pour la persistance JSON (fichier unique)
- MultiFileJsonStore: Classe de base pour multi-fichiers JSON
- *Adapter: Implementations des ports du domaine
"""

from .json_file_store import JsonFileStore, MultiFileJsonStore
from .draft_history_adapter import LegacyDraftHistoryAdapter
from .analytics_adapter import LegacyAnalyticsAdapter
from .token_counter_adapter import LegacyTokenCounterAdapter
from .processed_emails_adapter import (
    JsonProcessedEmailsTracker,
    InMemoryProcessedEmailsTracker,
)
from .commitment_adapter import CommitmentAdapter
from .communication_channel_adapter import CommunicationChannelAdapter
from .cryptographer_adapter import FernetCryptographerAdapter

__all__ = [
    # Base classes
    "JsonFileStore",
    "MultiFileJsonStore",
    # Adapters
    "LegacyDraftHistoryAdapter",
    "LegacyAnalyticsAdapter",
    "LegacyTokenCounterAdapter",
    "JsonProcessedEmailsTracker",
    "InMemoryProcessedEmailsTracker",
    "CommitmentAdapter",
    "CommunicationChannelAdapter",
    "FernetCryptographerAdapter",
]
