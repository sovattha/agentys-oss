# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Onboarding analysis agents — aligned 1:1 with the 4 training pillars.

- ProfileAgent: user identity (Pillar 1 — Profil)
- StyleAgent: writing style rules and patterns (Pillar 2 — Style d'écriture)
- KnowledgeAgent: contacts, FAQ, language variants (Pillar 3 — Savoir)
- LabelAgent: auto-label rules and categories (Pillar 4 — Auto-Label)
"""

from app.onboarding.agents.profile_agent import ProfileAgent
from app.onboarding.agents.knowledge_agent import KnowledgeAgent
from app.onboarding.agents.style_agent import StyleAgent
from app.onboarding.agents.label_agent import LabelAgent

__all__ = ["ProfileAgent", "StyleAgent", "KnowledgeAgent", "LabelAgent"]
