# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DTOs partagés entre la couche application et l'extérieur.

Les DTOs ici sont des structures de transport — pas d'entités du domaine.
Ils sont utilisés notamment par DraftService (Phase 2 du pipeline unifié)
pour normaliser les inputs (DraftContext) et outputs (DraftServiceResult)
des paths reply et compose.
"""
