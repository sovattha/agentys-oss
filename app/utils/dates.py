# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Normalisation des datetimes provider vers la convention « colonne = UTC naïf ».

Bug 2026-06-09 (« pourquoi 14:47 dans la liste et 18:47 dans le fil ? ») : les
colonnes ``DateTime`` (sans timezone) du cache email perdent l'offset au
round-trip SQLite/SQLAlchemy. Un ``parsedate_to_datetime`` Gmail (aware,
``-04:00``) stocké tel quel ressort comme datetime naïf portant l'heure MURALE
locale, que ``_to_iso_utc`` re-étiquette ensuite ``Z`` — l'heure locale est
mensongèrement déclarée UTC et le frontend la « convertit » une seconde fois
(-4 h). Le repository ``bulk_create`` normalisait déjà (« Normalize to UTC
before storing — SQLite loses timezone info ») mais quatre autres writers non.

Tout writer de ``Email.date`` (et de toute colonne DateTime naïve) DOIT passer
par :func:`to_naive_utc` / :func:`utc_now_naive`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union


def to_naive_utc(value: Union[datetime, str, None]) -> Optional[datetime]:
    """Convertit une date provider (aware/naïve/ISO-string) en datetime UTC NAÏF.

    - datetime aware → converti en UTC puis tzinfo retiré ;
    - datetime naïf → renvoyé tel quel (convention : déjà UTC) ;
    - str ISO 8601 (suffixe ``Z`` ou offset accepté) → parsé puis normalisé ;
    - None / non parsable → None (le caller choisit son fallback,
      typiquement :func:`utc_now_naive`).
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def utc_now_naive() -> datetime:
    """« Maintenant » en UTC naïf — le seul fallback valide pour ``Email.date``.

    ``datetime.now()`` (heure murale locale) stocké dans une colonne supposée
    UTC produit exactement le décalage d'affichage de ce bug.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def cached_date_needs_heal(
    existing: Optional[datetime],
    incoming: Optional[datetime],
    tolerance_seconds: float = 60.0,
) -> bool:
    """True si la date cachée diverge assez de la date provider pour être réécrite.

    Sert au chemin « doublon » de la sync inbox : les lignes écrites avant la
    normalisation portent l'heure murale locale (décalage = offset du fuseau,
    p.ex. 4 h) et ne se répareraient jamais autrement. La tolérance évite de
    réécrire la ligne à chaque sync pour une dérive d'horloge anodine.
    Les deux datetimes doivent être naïfs-UTC (passer ``incoming`` par
    :func:`to_naive_utc` d'abord).
    """
    if existing is None or incoming is None:
        return False
    return abs((existing - incoming).total_seconds()) > tolerance_seconds
