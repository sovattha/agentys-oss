# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Nettoyage de texte pour synthèse vocale (TTS).

Transforme un email nettoyé (post clean_email_content) en texte
prononçable naturellement par un moteur TTS.
"""

import re

# URLs → "lien"
_RE_URL = re.compile(r'https?://\S+', re.IGNORECASE)

# Adresses email → "adresse email de [nom]"
_RE_EMAIL = re.compile(r'(\b[\w.+-]+)@[\w.-]+\.\w{2,}\b')

# Bullets/listes → phrases
_RE_BULLET = re.compile(r'^\s*[-•*]\s+', re.MULTILINE)
_RE_NUMBERED = re.compile(r'^\s*\d+[.)]\s+', re.MULTILINE)

# Whitespace excessif
_RE_MULTI_NEWLINE = re.compile(r'\n{3,}')
_RE_MULTI_SPACE = re.compile(r'[ \t]{2,}')

# Abréviations courantes (français + anglais)
_ABBREVIATIONS = [
    (re.compile(r'\betc\.', re.IGNORECASE), 'et cetera'),
    (re.compile(r'\bcf\.', re.IGNORECASE), 'confer'),
    (re.compile(r'\bex\.(?=\s|$)', re.IGNORECASE), 'exemple'),
    (re.compile(r'\bvs\.', re.IGNORECASE), 'versus'),
    (re.compile(r'\bM\.(?=\s)'), 'Monsieur'),
    (re.compile(r'\bMme\.', re.IGNORECASE), 'Madame'),
    (re.compile(r'\bDr\.', re.IGNORECASE), 'Docteur'),
    (re.compile(r'\be\.g\.', re.IGNORECASE), 'par exemple'),
    (re.compile(r'\bi\.e\.', re.IGNORECASE), "c'est-à-dire"),
    (re.compile(r'\basap\b', re.IGNORECASE), 'dès que possible'),
    (re.compile(r'\bFYI\b', re.IGNORECASE), 'pour information'),
    (re.compile(r'\bRDV\b'), 'rendez-vous'),
]


def clean_for_tts(text: str) -> str:
    """
    Transforme un texte email nettoyé en texte prononçable par TTS.

    À appliquer après clean_email_content(). Transformations :
    - URLs → "lien"
    - Adresses email → "adresse email de [nom local]"
    - Bullets/listes → phrases fluides
    - Abréviations → forme longue
    - Whitespace excessif → espace simple

    Args:
        text: Texte email nettoyé.

    Returns:
        Texte optimisé pour la synthèse vocale.
    """
    if not text:
        return ""

    result = text

    # URLs → "lien"
    result = _RE_URL.sub('lien', result)

    # Adresses email → "adresse email de [local part]"
    result = _RE_EMAIL.sub(r'adresse email de \1', result)

    # Abréviations → forme longue
    for pattern, replacement in _ABBREVIATIONS:
        result = pattern.sub(replacement, result)

    # Bullets → phrases (retirer les marqueurs)
    result = _RE_BULLET.sub('', result)
    result = _RE_NUMBERED.sub('', result)

    # Nettoyer le whitespace
    result = _RE_MULTI_NEWLINE.sub('\n\n', result)
    result = _RE_MULTI_SPACE.sub(' ', result)
    result = result.strip()

    return result
