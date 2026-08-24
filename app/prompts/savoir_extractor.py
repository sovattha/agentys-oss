# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Parser de la section ## Savoir de la KB (Phase 2b).

Extrait UNIQUEMENT la section `## Savoir` de `memoire.md` pour injection
en mode compose. Les sections Profil/Format/Règles ne sont pas injectées
parce qu'elles font doublon avec WritingStyleProfile (data-driven, plus fiable).

Voir `docs/draft-pipeline-phases.md` pour le rationale complet.
"""

from __future__ import annotations

import re

# Marker d'absence de savoir — généré par build_knowledge_markdown quand FAQ
# vide. Si on tombe sur ça, retour vide (n'a aucune valeur d'injection).
_EMPTY_MARKER = "_aucun savoir enregistré._"


_HOSTILE_TAG_RE = re.compile(
    r"</?\s*(draft|context|rules|system)\b[^>]*>",
    re.IGNORECASE,
)


def _neutralize_xml_tags(text: str) -> str:
    """Neutralise les balises XML pouvant être confondues avec les délimiteurs
    du DraftService (`<context>`, `<draft>`, `<rules>`, `<system>`).

    Defense-in-depth : la KB est rédigée par l'utilisateur dans `memoire.md`
    et pourrait contenir (volontairement ou non) ces tokens. Sans neutralisation,
    un attaquant qui controlerait la KB pourrait fermer notre `<context>` et
    injecter de fausses instructions au LLM.

    Stratégie : regex insensible à la casse pour attraper toutes les variantes
    (`<draft>`, `<DRAFT>`, `<Draft>`, `<draft />`, `<draft attr="x">`, `</draft>`,
    `< draft >` avec espaces). Remplace par entités HTML pour préserver la
    lisibilité humaine tout en cassant la fenêtre XML.
    """
    if not text:
        return ""
    return _HOSTILE_TAG_RE.sub(
        lambda m: f"&lt;{m.group(0)[1:-1]}&gt;",
        text,
    )


def extract_savoir_section(kb_md: str | None) -> str:
    """Extrait la section ## Savoir de `kb_md` (memoire.md content).

    Args:
        kb_md : contenu markdown brut de la KB (typiquement
                `app/prompts.load_knowledge_base()`). Peut être None ou vide.

    Returns:
        - Bloc markdown de la section ## Savoir si présent et non vide,
          avec les balises hostiles neutralisées.
        - Empty string si :
          * kb_md est None / vide
          * Pas de section ## Savoir
          * Section présente mais ne contient que `_Aucun savoir enregistré._`
          * Section présente mais ne contient que des espaces

    Convention : si plusieurs `## Savoir` apparaissent (KB malformée), on
    retient le premier — éviter la complexité d'un merge ambigu.
    """
    if not kb_md or not kb_md.strip():
        return ""

    # Match `## Savoir` jusqu'au prochain `## ` (titre h2) ou fin de fichier.
    # Multiline + DOTALL pour capturer le contenu interne.
    pattern = re.compile(
        r"(?P<header>^##\s+Savoir\s*$)"
        r"(?P<body>.*?)"
        r"(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(kb_md)
    if not match:
        return ""

    body = match.group("body").strip()

    # Section vide ou marker explicite "_Aucun savoir enregistré._"
    if not body or body.strip().lower() == _EMPTY_MARKER:
        return ""

    # Neutraliser les balises XML hostiles dans le body
    safe_body = _neutralize_xml_tags(body)

    # Reconstituer la section avec son header
    return f"## Savoir\n\n{safe_body.strip()}\n"
