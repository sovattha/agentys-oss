# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Service façade pour l'adaptation de style d'écriture.

Story 4-4: Style Adaptation Engine
Orchestre l'adaptation de style dans la génération de brouillons.
"""

from typing import Optional

from app.config import STYLE_ADAPTATION_ENABLED, STYLE_SIMILARITY_THRESHOLD
from app.domain.entities.style_similarity import StyleSimilarityScore


class StyleAdaptationService:
    """
    Service façade pour l'adaptation de style d'écriture.

    Orchestre l'utilisation du profil de style de l'utilisateur
    dans la génération de brouillons et le calcul de similarité.

    Attributes:
        writing_style_service: Service pour récupérer les profils de style.
        similarity_analyzer: Analyseur de similarité de style.
        drafter_agent: Agent de rédaction de brouillons.
    """

    def __init__(
        self,
        writing_style_service,
        similarity_analyzer,
        drafter_agent,
    ):
        """
        Initialise le service.

        Args:
            writing_style_service: Service pour récupérer les profils de style.
            similarity_analyzer: Analyseur de similarité de style.
            drafter_agent: Agent de rédaction de brouillons.
        """
        self._writing_style_service = writing_style_service
        self._similarity_analyzer = similarity_analyzer
        self._drafter_agent = drafter_agent

    def get_style_context(self, account_id: int) -> Optional[str]:
        """
        Récupère le contexte de style pour un compte.

        Args:
            account_id: ID du compte email.

        Returns:
            Le contexte de style formaté pour le prompt, ou None si:
            - L'adaptation de style est désactivée globalement
            - Aucun profil n'existe pour ce compte
        """
        # Vérifier si l'adaptation est activée
        if not STYLE_ADAPTATION_ENABLED:
            return None

        return self._writing_style_service.get_prompt_context(account_id)

    def draft_with_style(
        self,
        account_id: int,
        email_content: str,
        use_style: bool = True,
    ) -> str:
        """
        Génère un brouillon avec adaptation de style optionnelle.

        Args:
            account_id: ID du compte email.
            email_content: Contenu de l'email à répondre.
            use_style: Si True, utilise l'adaptation de style.
                       Si False, génère un brouillon standard.

        Returns:
            Le brouillon généré.
        """
        style_context = None

        if use_style:
            style_context = self.get_style_context(account_id)

        return self._drafter_agent.draft(email_content, style_context=style_context)

    def calculate_similarity(
        self, account_id: int, draft: str
    ) -> StyleSimilarityScore:
        """
        Calcule le score de similarité entre un brouillon et le profil de style.

        Args:
            account_id: ID du compte email.
            draft: Le brouillon à analyser.

        Returns:
            StyleSimilarityScore avec le résultat de l'analyse.
            Retourne un score par défaut si aucun profil n'existe.
        """
        profile = self._writing_style_service.get_profile(account_id)

        if profile is None:
            return StyleSimilarityScore.create_default()

        return self._similarity_analyzer.analyze(draft, profile)

    def is_style_acceptable(
        self,
        account_id: int,
        draft: str,
        threshold: Optional[float] = None,
    ) -> bool:
        """
        Vérifie si le brouillon correspond suffisamment au style de l'utilisateur.

        Args:
            account_id: ID du compte email.
            draft: Le brouillon à vérifier.
            threshold: Seuil de similarité (0-100). Utilise la config par défaut si None.

        Returns:
            True si le score de similarité est >= seuil.
        """
        if threshold is None:
            threshold = STYLE_SIMILARITY_THRESHOLD

        score = self.calculate_similarity(account_id, draft)
        return score.is_acceptable(threshold)
