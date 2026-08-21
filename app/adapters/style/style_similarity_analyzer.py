# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Analyseur de similarité de style d'écriture.

Story 4-4: Style Adaptation Engine
Compare un brouillon généré avec le profil de style de l'utilisateur
pour calculer un score de similarité.
"""

import re
from typing import List, Optional

from app.domain.entities.style_similarity import StyleSimilarityScore
from app.domain.entities.writing_style import FormalityLevel, WritingStyleProfile


class StyleSimilarityAnalyzer:
    """
    Analyseur de similarité entre un brouillon et un profil de style.

    Compare les caractéristiques du brouillon (salutations, clôtures,
    formalité, vocabulaire) avec les préférences du profil utilisateur.
    """

    # Indicateurs de vouvoiement (formel)
    FORMAL_INDICATORS = {
        "vous", "votre", "vos", "veuillez", "madame", "monsieur",
        "respectueusement", "cordialement", "sincères", "agréer",
    }

    # Indicateurs de tutoiement (décontracté)
    CASUAL_INDICATORS = {
        "tu", "ton", "ta", "tes", "toi", "salut", "coucou", "bises",
        "bisous", "cool", "sympa", "super", "génial",
    }

    def analyze(
        self, draft: str, profile: WritingStyleProfile
    ) -> StyleSimilarityScore:
        """
        Analyse un brouillon par rapport au profil de style.

        Args:
            draft: Le brouillon d'email à analyser.
            profile: Le profil de style de l'utilisateur.

        Returns:
            StyleSimilarityScore avec le résultat de l'analyse.
        """
        if not draft:
            return StyleSimilarityScore(
                overall_score=0.0,
                greeting_match=False,
                closing_match=False,
                formality_match=False,
                vocabulary_overlap=0.0,
                analysis_details={
                    "detected_greeting": None,
                    "detected_closing": None,
                    "detected_formality": None,
                    "reason": "Empty draft",
                },
            )

        # Analyser chaque critère
        detected_greeting = self._detect_greeting(draft, profile.preferred_greetings)
        greeting_match = detected_greeting is not None

        detected_closing = self._detect_closing(draft, profile.preferred_closings)
        closing_match = detected_closing is not None

        detected_formality = self._detect_formality(draft)
        formality_match = self._check_formality_match(
            detected_formality, profile.formality_level
        )

        vocabulary_overlap = self._calculate_vocabulary_overlap(
            draft, profile.common_words
        )

        # Calculer le score global
        overall_score = self._calculate_overall_score(
            greeting_match=greeting_match,
            closing_match=closing_match,
            formality_match=formality_match,
            vocabulary_overlap=vocabulary_overlap,
        )

        return StyleSimilarityScore(
            overall_score=overall_score,
            greeting_match=greeting_match,
            closing_match=closing_match,
            formality_match=formality_match,
            vocabulary_overlap=vocabulary_overlap,
            analysis_details={
                "detected_greeting": detected_greeting,
                "detected_closing": detected_closing,
                "detected_formality": detected_formality,
            },
        )

    def _detect_greeting(
        self, draft: str, preferred_greetings: List[str]
    ) -> Optional[str]:
        """
        Détecte une salutation préférée dans le brouillon.

        Args:
            draft: Le brouillon à analyser.
            preferred_greetings: Liste des salutations préférées.

        Returns:
            La salutation détectée ou None.
        """
        if not preferred_greetings:
            return None

        draft_lower = draft.lower()
        # Chercher dans les premières lignes (salutation typiquement au début)
        first_lines = draft_lower[:200]

        for greeting in preferred_greetings:
            if greeting.lower() in first_lines:
                return greeting

        return None

    def _detect_closing(
        self, draft: str, preferred_closings: List[str]
    ) -> Optional[str]:
        """
        Détecte une formule de clôture préférée dans le brouillon.

        Args:
            draft: Le brouillon à analyser.
            preferred_closings: Liste des clôtures préférées.

        Returns:
            La clôture détectée ou None.
        """
        if not preferred_closings:
            return None

        draft_lower = draft.lower()
        # Chercher dans les dernières lignes (clôture typiquement à la fin)
        last_lines = draft_lower[-300:]

        for closing in preferred_closings:
            if closing.lower() in last_lines:
                return closing

        return None

    def _detect_formality(self, draft: str) -> Optional[str]:
        """
        Détecte le niveau de formalité du brouillon.

        Args:
            draft: Le brouillon à analyser.

        Returns:
            "formal", "casual" ou "mixed".
        """
        words = set(re.findall(r"\b\w+\b", draft.lower()))

        formal_count = len(words & self.FORMAL_INDICATORS)
        casual_count = len(words & self.CASUAL_INDICATORS)

        if formal_count > casual_count:
            return "formal"
        elif casual_count > formal_count:
            return "casual"
        elif formal_count > 0 and casual_count > 0:
            return "mixed"
        else:
            return "mixed"  # Default si aucun indicateur

    def _check_formality_match(
        self, detected: Optional[str], expected: FormalityLevel
    ) -> bool:
        """
        Vérifie si la formalité détectée correspond au profil.

        Args:
            detected: Formalité détectée ("formal", "casual", "mixed").
            expected: Niveau de formalité attendu du profil.

        Returns:
            True si correspondance.
        """
        if detected is None:
            return False

        if expected == FormalityLevel.FORMAL:
            return detected == "formal"
        elif expected == FormalityLevel.CASUAL:
            return detected == "casual"
        else:  # MIXED
            return True  # Mixed accepte tout

    def _calculate_vocabulary_overlap(
        self, draft: str, common_words: List[str]
    ) -> float:
        """
        Calcule le chevauchement de vocabulaire.

        Args:
            draft: Le brouillon à analyser.
            common_words: Mots caractéristiques du profil.

        Returns:
            Ratio de mots communs (0.0 à 1.0).
        """
        if not common_words:
            return 0.0

        draft_words = set(re.findall(r"\b\w+\b", draft.lower()))
        common_words_lower = {w.lower() for w in common_words}

        matches = draft_words & common_words_lower

        if not common_words_lower:
            return 0.0

        return len(matches) / len(common_words_lower)

    def _calculate_overall_score(
        self,
        greeting_match: bool,
        closing_match: bool,
        formality_match: bool,
        vocabulary_overlap: float,
    ) -> float:
        """
        Calcule le score global de similarité.

        Pondération:
        - Salutation: 25%
        - Clôture: 25%
        - Formalité: 30%
        - Vocabulaire: 20%

        Args:
            greeting_match: Match de salutation.
            closing_match: Match de clôture.
            formality_match: Match de formalité.
            vocabulary_overlap: Ratio de vocabulaire (0-1).

        Returns:
            Score global (0-100).
        """
        score = 0.0

        # Salutation: 25 points
        if greeting_match:
            score += 25.0

        # Clôture: 25 points
        if closing_match:
            score += 25.0

        # Formalité: 30 points
        if formality_match:
            score += 30.0

        # Vocabulaire: 20 points (proportionnel à l'overlap)
        score += vocabulary_overlap * 20.0

        return min(100.0, max(0.0, score))
