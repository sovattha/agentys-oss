# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Domain Layer - Coeur métier de l'application.

Cette couche contient :
- entities/ : Objets métier purs (Email, Draft, TokenUsage)
- ports/ : Interfaces (contrats) que les adapters doivent implémenter

Règle : Cette couche ne dépend d'AUCUNE bibliothèque externe.
"""
