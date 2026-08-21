# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port pour le tracker d'emails traites.

Ce port herite du port generique ItemTrackerPort.
Conserve pour compatibilite avec le code existant.

Clean Architecture:
- Couche Domain (Ports)
- Alias semantique pour ItemTrackerPort
"""

from app.domain.ports.item_tracker_port import ItemTrackerPort


class ProcessedEmailsTrackerPort(ItemTrackerPort):
    """
    Port pour le suivi des emails traites.

    Herite de ItemTrackerPort sans modifications.
    Cet alias semantique permet un code plus expressif:
    - ProcessedEmailsTrackerPort pour tracker les emails
    - ProcessedDraftsTrackerPort pour tracker les brouillons

    Note:
        Les methodes is_processed, mark_processed, count,
        get_all_ids et clear sont heritees de ItemTrackerPort.
    """
    pass
