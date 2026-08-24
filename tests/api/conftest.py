# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fixtures partagées pour les tests de l'API (tests/api/).

Ré-exporte la fixture ``admin_client`` depuis ``tests.audit_fixes._admin_helpers``
pour que les tests de ce dossier la consomment en paramètre sans import direct
(évite le faux-positif F811 « redéfinition » sur le pattern fixture pytest).
"""
from tests.audit_fixes._admin_helpers import admin_client  # noqa: F401 — fixture pytest ré-exportée
