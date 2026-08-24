# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Calcule un indice d'activité du thread pour guider greetings/clôtures (#189).

Si un thread est actif (3+ messages dans les 2 heures), ré-insérer un
« Bonjour Jean » à chaque réponse est contre-nature. Ce helper extrait un
signal compact que le DrafterAgent peut utiliser pour décider d'inclure ou
d'omettre la salutation.

Input : conversation_history (liste d'emails récents, déjà filtrée par thread).
Output : bloc texte court injectable dans le system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

# Seuils exposés pour tests.
ACTIVE_THREAD_MIN_MESSAGES = 3
ACTIVE_THREAD_MAX_GAP_MINUTES = 120  # 2h


@dataclass(frozen=True)
class ThreadActivity:
    """Snapshot immuable de l'activité d'un thread."""
    depth: int
    last_gap_minutes: Optional[float]  # None si < 2 messages ou dates manquantes.
    is_active: bool

    def recommend_skip_greeting(self) -> bool:
        """True si le contexte suggère d'omettre la salutation formelle.

        Actif (≥3 messages, gap ≤ 120min) → skip pour éviter la répétition.
        Faible profondeur ou gap long → garder la salutation.
        """
        return self.is_active

    def to_prompt_block(self) -> str:
        """Rend un bloc XML-style injectable dans le system prompt.

        Retourne chaîne vide si la profondeur est insuffisante pour que le
        signal ait du sens (< 2 messages) : on évite de polluer le prompt.
        """
        if self.depth < 2:
            return ""
        gap_str = (
            f"{self.last_gap_minutes:.0f}min"
            if self.last_gap_minutes is not None
            else "n/a"
        )
        skip = "true" if self.recommend_skip_greeting() else "false"
        return (
            "<ACTIVITE_THREAD>\n"
            f"profondeur={self.depth} | gap_dernier_message={gap_str} | "
            f"thread_actif={str(self.is_active).lower()}\n"
            f"RECOMMANDATION : omettre_salutation={skip}\n"
            "Si omettre_salutation=true, réponds DIRECTEMENT sans "
            "« Bonjour/Salut {prénom} » — le thread est actif et la salutation "
            "serait répétitive. Si false, inclure la salutation habituelle.\n"
            "</ACTIVITE_THREAD>"
        )


def _parse_date(raw: object) -> Optional[datetime]:
    """Parse tolérant les formats ISO utilisés dans le projet."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str) or not raw.strip():
        return None
    # Tolérance : 'Z' en suffixe, format ISO.
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def analyze(conversation_history: list[dict] | None) -> ThreadActivity:
    """Calcule l'activité du thread à partir de l'historique fourni."""
    if not conversation_history:
        return ThreadActivity(depth=0, last_gap_minutes=None, is_active=False)

    depth = len(conversation_history)
    if depth < 2:
        return ThreadActivity(depth=depth, last_gap_minutes=None, is_active=False)

    # Trier par date ascendante pour calculer le gap entre les 2 derniers.
    dated = [
        (email, _parse_date(email.get("date") or email.get("received_at")))
        for email in conversation_history
    ]
    dated_valid = [(e, d) for e, d in dated if d is not None]
    dated_valid.sort(key=lambda x: x[1])  # type: ignore[arg-type,return-value]

    if len(dated_valid) < 2:
        # Profondeur suffisante mais dates manquantes : on ne peut pas juger.
        return ThreadActivity(depth=depth, last_gap_minutes=None, is_active=False)

    last_gap_seconds = (dated_valid[-1][1] - dated_valid[-2][1]).total_seconds()  # type: ignore[operator]
    last_gap_minutes = abs(last_gap_seconds) / 60.0
    is_active = (
        depth >= ACTIVE_THREAD_MIN_MESSAGES
        and last_gap_minutes <= ACTIVE_THREAD_MAX_GAP_MINUTES
    )
    return ThreadActivity(
        depth=depth,
        last_gap_minutes=last_gap_minutes,
        is_active=is_active,
    )


def build_thread_activity_block(conversation_history: list[dict] | None) -> str:
    """Shortcut : analyze + to_prompt_block."""
    return analyze(conversation_history).to_prompt_block()
