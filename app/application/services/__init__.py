# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Services de la couche application — orchestrent les use cases.

Cette couche dépend uniquement du domaine (entities + ports) et des DTOs
de l'application. Les implémentations concrètes (LLM, DB, etc.) sont
injectées par l'extérieur (typiquement résolues depuis le Container côté
API endpoints, pas importées ici).
"""
