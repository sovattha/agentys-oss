# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Détecter la langue d'un texte.
"""


class DetectLanguage:
    """
    Détecte la langue d'un texte parmi les langues supportées.

    Langues supportées : fr, en, es.
    Fallback : 'fr' si la détection échoue ou si la langue n'est pas supportée.
    """

    SUPPORTED = {'fr', 'en', 'es'}

    def run(self, text: str) -> str:
        """
        Détecte la langue d'un texte.

        Args:
            text: Texte à analyser (les 500 premiers caractères suffisent).

        Returns:
            Code langue ISO 639-1 ('fr', 'en', 'es') ou 'fr' par défaut.
        """
        if not text or not text.strip():
            return 'fr'

        try:
            from langdetect import detect  # type: ignore
            lang = detect(text[:500])
            return lang if lang in self.SUPPORTED else 'fr'
        except Exception:
            return 'fr'
