# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Classification heuristique des éditions utilisateur sur un draft (#196).

Le Drafter IA produit un brouillon. L'utilisateur l'édite avant de l'envoyer.
Ce service compare ``initial`` vs ``final`` et classifie la nature du changement
pour alimenter le feedback loop d'apprentissage.

Implémentation heuristique volontairement : pas d'appel LLM pour rester
gratuit et synchrone. Un classifieur LLM peut être branché plus tard derrière
la même interface si on veut de la nuance.
"""

from __future__ import annotations

import re
from typing import Optional

from app.domain.entities.draft_edit_event import EditCategory, EditEvent


# Marqueurs de formalité — heuristiques simples, lang FR/EN.
_FORMAL_MARKERS = {
    "vous",
    "cordialement",
    "bien à vous",
    "bien cordialement",
    "sincèrement",
    "sincerely",
    "regards",
    "best regards",
    "yours truly",
}

_CASUAL_MARKERS = {
    "salut",
    "coucou",
    "yo",
    "hey",
    "ciao",
    "à +",
    "a+",
    "cheers",
    "thx",
    "thanks",
    "bises",
    "bisous",
}

# Bloc de signature typique : ≥ 3 lignes courtes avec email ou tél en dernière.
_EMAIL_OR_PHONE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|\+?\d[\d\s.-]{6,}")

# Seuils exposés pour tests et tuning.
TONE_SHIFT_MIN_HITS = 2
LENGTH_ADJ_MIN_DELTA = 0.20  # 20% d'écart de longueur déclenche length_adjustment.
CONTENT_ADDITION_MIN_NEW_SENTENCES = 2
STRUCTURE_MIN_PARA_DELTA = 2


def _count_markers(text: str, markers: set[str]) -> int:
    lower = text.lower()
    return sum(1 for m in markers if m in lower)


def _sentence_count(text: str) -> int:
    parts = re.split(r"[.!?]+", text)
    return sum(1 for p in parts if len(p.strip()) >= 3)


def _paragraph_count(text: str) -> int:
    return sum(1 for p in re.split(r"\n\s*\n", text.strip()) if p.strip())


def _has_signature_block(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    # Heuristique : au moins un email/téléphone dans les 4 dernières lignes.
    tail = "\n".join(lines[-4:])
    return bool(_EMAIL_OR_PHONE.search(tail))


def _tone_delta(initial: str, final: str) -> Optional[EditCategory]:
    """Detect a directional tone shift between initial and final."""
    formal_initial = _count_markers(initial, _FORMAL_MARKERS)
    casual_initial = _count_markers(initial, _CASUAL_MARKERS)
    formal_final = _count_markers(final, _FORMAL_MARKERS)
    casual_final = _count_markers(final, _CASUAL_MARKERS)

    formal_delta = formal_final - formal_initial
    casual_delta = casual_final - casual_initial

    # Mouvement significatif dans une direction opposée.
    if formal_delta >= TONE_SHIFT_MIN_HITS and casual_delta <= 0:
        return EditCategory.TONE_SHIFT
    if casual_delta >= TONE_SHIFT_MIN_HITS and formal_delta <= 0:
        return EditCategory.TONE_SHIFT
    return None


def classify_edit(initial: str, final: str) -> EditCategory:
    """Classe l'édition selon l'ordre de priorité documenté dans EditCategory."""
    if initial == final:
        return EditCategory.OTHER  # No-op, appelant peut filtrer en amont.

    # 1. Signature added or replaced ? (stronger signal than length)
    if _has_signature_block(final) and not _has_signature_block(initial):
        return EditCategory.SIGNATURE_OVERRIDE

    # 2. Content addition — nouvelles phrases apportant de l'info.
    initial_sentences = _sentence_count(initial)
    final_sentences = _sentence_count(final)
    sentence_delta = final_sentences - initial_sentences
    if sentence_delta >= CONTENT_ADDITION_MIN_NEW_SENTENCES:
        return EditCategory.CONTENT_ADDITION

    # 3. Length adjustment — écart relatif significatif (raccourci ou allongé).
    initial_len = max(len(initial), 1)
    length_delta = abs(len(final) - len(initial)) / initial_len
    if length_delta >= LENGTH_ADJ_MIN_DELTA:
        return EditCategory.LENGTH_ADJUSTMENT

    # 4. Tone shift — marqueurs de formalité.
    tone = _tone_delta(initial, final)
    if tone is not None:
        return tone

    # 5. Structure change — paragraphes ajoutés ou retirés.
    para_delta = abs(_paragraph_count(final) - _paragraph_count(initial))
    if para_delta >= STRUCTURE_MIN_PARA_DELTA:
        return EditCategory.STRUCTURE_CHANGE

    # 6. Petites corrections cosmétiques — moins de 5% de changement.
    if length_delta < 0.05:
        return EditCategory.MINOR_TYPO_FIX

    return EditCategory.OTHER


def build_event(
    *,
    draft_id: str,
    account_id: int,
    initial: str,
    final: str,
    intent: Optional[str] = None,
    recipient_email: Optional[str] = None,
    original_email_id: Optional[int] = None,
) -> EditEvent:
    """Classifie l'édition et emballe dans un ``EditEvent`` prêt à persister."""
    category = classify_edit(initial, final)
    initial_len = len(initial)
    final_len = len(final)
    magnitude = abs(final_len - initial_len) / max(initial_len, 1)
    return EditEvent(
        draft_id=draft_id,
        account_id=account_id,
        category=category,
        magnitude=magnitude,
        initial_length=initial_len,
        final_length=final_len,
        intent=intent,
        recipient_email=recipient_email,
        original_email_id=original_email_id,
    )
