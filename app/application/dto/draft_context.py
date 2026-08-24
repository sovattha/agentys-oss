# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DraftContext — input normalisé du DraftService (Phase 2 du pipeline unifié).

Contrat partagé entre les deux flows :
- reply : `email_in` est un mapping de l'email original (sender, body, subject, id, thread_id, …)
- compose : `email_in` est None ; (recipient_email, subject, instructions) suffisent

Frozen au niveau dataclass — mais shallow uniquement : les Mapping et tuple
internes restent eux-mêmes muables (un appelant peut muter `email_in["body"]`).
Convention : ne PAS muter ce qu'on a passé au service. Le DTO est en lecture
seule du point de vue du service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class DraftContext:
    """Input du DraftService.generate() — un seul format pour reply et compose.

    Champs obligatoires :
        recipient_email : destinataire principal (premier `to:`)
        subject : sujet de l'email à composer ou auquel on répond (Re: ...)
        instructions : consigne libre de l'utilisateur (« Propose 3 options »)
        knowledge_base : KB textuelle injectée dans le prompt Drafter
        user_email : email de l'expéditeur (utilisé pour few-shot, signature)

    Champs optionnels :
        email_in : Mapping représentant l'email original (mode reply). Clés
                   typiques : sender, body, subject, id, thread_id, attachments.
                   None en mode compose.
        cc : destinataires en copie (tuple immuable)
        bcc : destinataires en copie cachée (tuple immuable)
        compose_id : id de session WebSocket pour le streaming (mode compose
                     uniquement — émission `draft_chunk` events)
        conversation_history : tuple de mappings {sender, body, ...}
                               utilisé pour le contexte multi-tour
        style_profile : profil de style sérialisé en string (cf.
                        WritingStyleProfile.to_prompt_context)
        account_id : id DB du compte (résolution KB DB-first, contact summary)
        tier_hint : tier suggéré par le routeur amont (SIMPLE/STANDARD/COMPLEX)
                    — le DraftService peut overrider après analyse
        language : locale forcée du brouillon ('fr', 'en', …) — None = auto-détect
    """
    recipient_email: str
    subject: str
    instructions: str
    knowledge_base: str
    user_email: str
    email_in: Optional[Mapping[str, Any]] = None
    cc: tuple[str, ...] = field(default_factory=tuple)
    bcc: tuple[str, ...] = field(default_factory=tuple)
    compose_id: Optional[str] = None
    conversation_history: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    style_profile: Optional[str] = None
    account_id: Optional[int] = None
    tier_hint: Optional[str] = None
    language: Optional[str] = None
