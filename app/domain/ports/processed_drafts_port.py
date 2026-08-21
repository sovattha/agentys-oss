# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port pour le tracker de brouillons traites.

Ce port herite du port generique ItemTrackerPort.
Conserve pour compatibilite avec le code existant.

Clean Architecture:
- Couche Domain (Ports)
- Alias semantique pour ItemTrackerPort
"""

from app.domain.ports.item_tracker_port import ItemTrackerPort


class ProcessedDraftsTrackerPort(ItemTrackerPort):
    """
    Port pour le suivi des brouillons utilisateur traites.

    Herite de ItemTrackerPort sans modifications.
    Ce port est specifique aux brouillons utilisateur
    qui sont completes automatiquement par le daemon.

    Note:
        Les methodes is_processed, mark_processed, count,
        get_all_ids et clear sont heritees de ItemTrackerPort.
    """
    pass
