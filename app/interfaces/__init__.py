# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Interfaces abstraites pour Agentys.

Ce module définit les contrats que doivent respecter les implémentations concrètes.
"""

from app.interfaces.email_provider import EmailProvider, StandardEmail

__all__ = ["EmailProvider", "StandardEmail"]
