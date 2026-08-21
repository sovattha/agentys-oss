# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Providers concrets pour Agentys.

Ce module contient les implémentations des interfaces abstraites.
"""

from app.providers.factory import get_email_provider

__all__ = ["get_email_provider"]
