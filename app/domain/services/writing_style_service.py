# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Service façade pour le système d'apprentissage du style d'écriture.

Ce service combine l'analyse LLM et le stockage local pour
gérer les profils de style d'écriture des utilisateurs.
"""

import logging
from typing import Dict, Any, List, Optional, Sequence

from app.db.models.email import Email
from app.domain.entities.writing_style import WritingStyleProfile
from app.domain.ports.writing_style_port import WritingStyleAnalyzerPort, WritingStyleStorePort

logger = logging.getLogger(__name__)


class WritingStyleService:
    """
    Service façade pour la gestion du style d'écriture.

    Combine l'analyse LLM et le stockage local pour:
    - Analyser les emails envoyés et extraire le style
    - Stocker le profil localement (NFR47)
    - Mettre à jour le profil de façon incrémentale

    Usage:
        container = get_container()
        service = container.get_writing_style_service()
        profile = await service.analyze_and_store(account_id, emails)
    """

    # Nombre minimum d'emails pour une analyse initiale
    MIN_EMAILS_FOR_ANALYSIS = 3

    def __init__(
        self,
        analyzer: WritingStyleAnalyzerPort,
        store: WritingStyleStorePort,
    ):
        """
        Initialise le service.

        Args:
            analyzer: Port d'analyse du style (LLM).
            store: Port de stockage local.
        """
        self._analyzer = analyzer
        self._store = store

    async def analyze_and_store(
        self,
        account_id: int,
        emails: Sequence[Email],
        timeout_seconds: int = 30,
    ) -> WritingStyleProfile:
        """
        Analyse les emails et stocke le profil.

        Cette méthode effectue une analyse complète des emails
        et persiste le résultat localement.

        Args:
            account_id: ID du compte email.
            emails: Séquence d'emails envoyés à analyser.
            timeout_seconds: Timeout en secondes.

        Returns:
            WritingStyleProfile avec les caractéristiques extraites.
        """
        logger.info(f"Starting style analysis for account {account_id} with {len(emails)} emails")

        # Analyser les emails
        profile = await self._analyzer.analyze(
            account_id=account_id,
            emails=emails,
            timeout_seconds=timeout_seconds,
        )

        # Sauvegarder le profil
        if profile.email_count > 0:
            success = self._store.save(profile)
            if success:
                logger.info(f"Style profile saved for account {account_id}")
            else:
                logger.warning(f"Failed to save style profile for account {account_id}")

        return profile

    async def update_with_sent_email(
        self,
        account_id: int,
        email: Email,
    ) -> WritingStyleProfile:
        """
        Met à jour le profil après l'envoi d'un email.

        Effectue une mise à jour incrémentale sans re-analyser
        tous les emails précédents.

        Args:
            account_id: ID du compte email.
            email: L'email qui vient d'être envoyé.

        Returns:
            Profil mis à jour.
        """
        logger.debug(f"Updating style profile for account {account_id} with new email")

        # Charger le profil existant ou en créer un nouveau
        profile = self._store.load(account_id)
        if profile is None:
            profile = WritingStyleProfile.create_empty(account_id)

        # Analyser le nouvel email
        features = await self._analyzer.analyze_single(email)

        # Mettre à jour le profil
        profile.merge_with_new_email(
            new_words=features.get("common_words", []),
            new_greetings=features.get("greetings", []),
            new_closings=features.get("closings", []),
            new_email_length=features.get("email_length", 0),
            new_sentence_length=features.get("sentence_length", 0.0),
        )

        # Sauvegarder
        self._store.save(profile)

        return profile

    def get_profile(self, account_id: int) -> Optional[WritingStyleProfile]:
        """
        Récupère le profil de style pour un compte.

        Args:
            account_id: ID du compte.

        Returns:
            Profil ou None si non trouvé.
        """
        return self._store.load(account_id)

    def get_or_create_profile(self, account_id: int) -> WritingStyleProfile:
        """
        Récupère ou crée un profil vide.

        Args:
            account_id: ID du compte.

        Returns:
            Profil existant ou nouveau profil vide.
        """
        profile = self._store.load(account_id)
        if profile is None:
            profile = WritingStyleProfile.create_empty(account_id)
            self._store.save(profile)
        return profile

    def get_prompt_context(self, account_id: int, recipient_email: Optional[str] = None) -> str:
        """
        Génère le contexte de style pour un prompt.

        Alias de :meth:`get_observed_style_block` conservé pour compat avec les
        callsites qui n'ont pas encore été migrés (notamment
        :class:`StyleAdaptationService`). Délègue à la même implémentation
        unifiée — métriques continues + few-shot anonymisé + per-contact hint.

        Args:
            account_id: ID du compte.
            recipient_email: Email du destinataire pour adaptation par contact.

        Returns:
            Texte décrivant le style pour inclusion dans un prompt.
            Chaîne vide si pas assez de données.
        """
        profile = self._store.load(account_id)
        if profile is None or not profile.is_sufficient():
            return ""
        from app.prompts.style_guidance import build_style_guidance_from_profile
        return build_style_guidance_from_profile(
            profile, language="fr", recipient_email=recipient_email
        )

    def get_observed_style_block(
        self,
        account_id: int,
        language: str = "fr",
        recipient_email: Optional[str] = None,
    ) -> str:
        """
        Génère le bloc de style observé (issue #187) : métriques + few-shot
        + (PR3) hint per-contact si ``recipient_email`` est fourni et match.

        Remplace les anciens labels slider (ton=formel, emotion=chaleureux)
        par une description factuelle du style réel de l'utilisateur.

        Args:
            account_id: ID du compte.
            language: Code locale ("fr" | "en") pour les labels narratifs
                — évite le mélange de langues dans le prompt (F16).
            recipient_email: PR3 — opt-in adaptation par contact. Si fourni
                et matche un ``ContactStyleProfile`` dans le profile, le bloc
                inclut une section per-contact (nickname / formalité / greeting
                / closing / langue / variante régionale) en bout de chaîne.

        Returns:
            Bloc narratif + <STYLE_EXAMPLES>...</STYLE_EXAMPLES> + (option)
            hint per-contact, ou chaîne vide si rien à émettre.
        """
        # Import tardif pour éviter les cycles domain → prompts
        from app.prompts.style_guidance import build_style_guidance_from_profile

        profile = self._store.load(account_id)
        return build_style_guidance_from_profile(
            profile, language=language, recipient_email=recipient_email
        )

    def has_sufficient_data(self, account_id: int) -> bool:
        """
        Vérifie si le profil a assez de données.

        Args:
            account_id: ID du compte.

        Returns:
            True si au moins MIN_EMAILS_FOR_ANALYSIS emails analysés.
        """
        profile = self._store.load(account_id)
        if profile is None:
            return False
        return profile.is_sufficient(self.MIN_EMAILS_FOR_ANALYSIS)

    def delete_profile(self, account_id: int) -> bool:
        """
        Supprime le profil d'un compte.

        Args:
            account_id: ID du compte.

        Returns:
            True si supprimé avec succès.
        """
        return self._store.delete(account_id)

    def list_profiles(self) -> List[int]:
        """
        Liste tous les comptes ayant un profil.

        Returns:
            Liste des IDs de comptes.
        """
        return self._store.list_all()

    def get_stats(self, account_id: int) -> Dict[str, Any]:
        """
        Récupère les statistiques du profil.

        Args:
            account_id: ID du compte.

        Returns:
            Dictionnaire avec les statistiques ou stats vides.
        """
        profile = self._store.load(account_id)
        if profile is None:
            return {
                "exists": False,
                "email_count": 0,
                "is_sufficient": False,
            }

        return {
            "exists": True,
            "email_count": profile.email_count,
            "is_sufficient": profile.is_sufficient(),
            "formality_level": profile.formality_level.value,
            "avg_sentence_length": profile.avg_sentence_length,
            "avg_email_length": profile.avg_email_length,
            "analysis_duration_ms": profile.analysis_duration_ms,
            "analyzed_at": profile.analyzed_at.isoformat(),
            "common_words_count": len(profile.common_words),
            "greetings_count": len(profile.preferred_greetings),
            "closings_count": len(profile.preferred_closings),
            # PR4 follow-up — `humor_level`, `bullet_list_ratio`,
            # `rejected_drafts_count`, `rejection_rate` removed from the
            # entity. Their slots in the stats dict are gone too — any
            # consumer expecting them would be reading dead data anyway.
            "emoji_frequency": profile.emoji_frequency,
            "contact_profiles_count": len(profile.contact_profiles),
        }
