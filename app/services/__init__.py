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
Services module for Agentys.

Contains background services like email sync, cache management,
connectivity monitoring, offline action queue, and search.
"""

from app.services.action_queue import (
    ActionQueue,
    get_action_queue,
    process_all_pending_actions,
    process_pending_actions_for_account,
)
from app.services.cache_manager import EmailCacheManager, get_cache_manager
from app.services.connectivity_service import ConnectivityService, get_connectivity_service
from app.services.search_service import SearchService, get_search_service
from app.services.sync_service import SyncService, get_sync_service
from app.services.relationship_detection_service import RelationshipDetectionService
from app.services.draft_orchestrator import DraftOrchestrator

__all__ = [
    "ActionQueue",
    "ConnectivityService",
    "DraftOrchestrator",
    "EmailCacheManager",
    "SearchService",
    "SyncService",
    "get_action_queue",
    "get_cache_manager",
    "get_connectivity_service",
    "get_search_service",
    "get_sync_service",
    "process_all_pending_actions",
    "process_pending_actions_for_account",
    "RelationshipDetectionService",
]
