# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Lecture de fichiers texte tolérante aux fichiers hérités cp1252.

Le commit d'hygiène d'encodage (2026-05-14) a forcé ``encoding="utf-8"`` sur
toutes les lectures de fichiers de ``app/``. Mais les fichiers de données déjà
présents sur disque ont été écrits par le code antérieur via
``Path.write_text()`` sans ``encoding=`` — donc en cp1252 sur Windows
(l'environnement de dev principal). ``read_text(encoding="utf-8")`` lève alors
``UnicodeDecodeError`` sur le premier octet accentué, et plusieurs appelants
traitent cette exception comme « fichier corrompu » : ils réinitialisent aux
valeurs par défaut ou vident l'état en mémoire, puis ré-enregistrent — ce qui
DÉTRUIT silencieusement les données de l'utilisateur (audit 2026-05-14, F-01).

``read_text_legacy_safe`` lit en UTF-8 et, en cas d'``UnicodeDecodeError``,
retombe sur cp1252 (le codec qui a effectivement produit le fichier). Il
signale ce repli pour que l'appelant ré-enregistre le fichier en UTF-8 et le
répare une bonne fois pour toutes.
"""
from __future__ import annotations

from pathlib import Path


def read_text_legacy_safe(path: Path) -> tuple[str, bool]:
    """Lit un fichier texte en UTF-8, en tolérant les fichiers hérités cp1252.

    Args:
        path: Chemin du fichier à lire.

    Returns:
        ``(texte, recovered)``. ``recovered`` vaut ``True`` quand le fichier
        n'était pas de l'UTF-8 valide et a dû être décodé via le codec hérité
        cp1252 — l'appelant DOIT alors le ré-enregistrer en UTF-8 pour le
        réparer. Un fichier déjà propre renvoie toujours ``recovered=False``,
        donc la réparation est idempotente.

    Raises:
        Toute erreur d'E/S (fichier absent, permission refusée) se propage
        normalement. Seul ``UnicodeDecodeError`` déclenche le repli cp1252 ;
        si ce repli échoue lui aussi (octets qui ne sont pas du cp1252 valide,
        donc vraie corruption binaire), l'``UnicodeDecodeError`` se propage à
        l'appelant, qui applique alors sa propre logique « fichier corrompu ».
    """
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        # Fichier hérité : le code pré-hygiène écrivait via Path.write_text()
        # sans encoding=, donc cp1252 sur Windows. cp1252 décode fidèlement
        # tout ce qu'un encodeur cp1252 a produit → contenu original intact.
        return raw.decode("cp1252"), True
