# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Ports (interfaces) pour l'app mobile companion.

Ce module définit les contrats que les adapters doivent implémenter
pour la fonctionnalité mobile companion.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Dict, Any

from app.domain.entities.mobile_companion import (
    MobileSession,
    MobileSyncState,
    MobileAnalyticsEvent,
    MobileDraft,
    MobileUserPreferences,
    MobileAppConfig,
    MobileDraftActionRequest,
    MobileStats,
)


class MobileSessionPort(ABC):
    """
    Interface abstraite pour la gestion des sessions mobiles.

    Tout adapter de persistance de sessions doit implémenter cette interface.
    """

    @abstractmethod
    def create(
        self,
        user_id: str,
        device_token: Optional[str] = None,
        app_version: Optional[str] = None,
        os_version: Optional[str] = None,
        device_model: Optional[str] = None,
    ) -> MobileSession:
        """
        Crée une nouvelle session mobile.

        Args:
            user_id: Identifiant de l'utilisateur.
            device_token: Token push du device.
            app_version: Version de l'app.
            os_version: Version de l'OS.
            device_model: Modèle du device.

        Returns:
            MobileSession créée.
        """
        pass

    @abstractmethod
    def get(self, session_id: str) -> Optional[MobileSession]:
        """
        Récupère une session par son ID.

        Args:
            session_id: Identifiant de la session.

        Returns:
            MobileSession ou None si non trouvée.
        """
        pass

    @abstractmethod
    def get_active_by_user(self, user_id: str) -> List[MobileSession]:
        """
        Récupère les sessions actives d'un utilisateur.

        Args:
            user_id: Identifiant de l'utilisateur.

        Returns:
            Liste des sessions actives.
        """
        pass

    @abstractmethod
    def touch(self, session_id: str) -> bool:
        """
        Met à jour l'activité d'une session.

        Args:
            session_id: Identifiant de la session.

        Returns:
            True si mise à jour réussie.
        """
        pass

    @abstractmethod
    def end(self, session_id: str) -> bool:
        """
        Termine une session.

        Args:
            session_id: Identifiant de la session.

        Returns:
            True si terminée avec succès.
        """
        pass

    @abstractmethod
    def end_all_for_user(self, user_id: str) -> int:
        """
        Termine toutes les sessions d'un utilisateur.

        Args:
            user_id: Identifiant de l'utilisateur.

        Returns:
            Nombre de sessions terminées.
        """
        pass

    @abstractmethod
    def cleanup_inactive(self, inactive_minutes: int = 30) -> int:
        """
        Nettoie les sessions inactives.

        Args:
            inactive_minutes: Durée d'inactivité avant nettoyage.

        Returns:
            Nombre de sessions nettoyées.
        """
        pass


class MobileSyncPort(ABC):
    """
    Interface abstraite pour la synchronisation mobile.

    Gère l'état de synchronisation et les données à synchroniser.
    """

    @abstractmethod
    def get_sync_state(self, user_id: str, device_token: str) -> Optional[MobileSyncState]:
        """
        Récupère l'état de synchronisation.

        Args:
            user_id: Identifiant de l'utilisateur.
            device_token: Token du device.

        Returns:
            État de sync ou None si non trouvé.
        """
        pass

    @abstractmethod
    def update_sync_state(self, sync_state: MobileSyncState) -> MobileSyncState:
        """
        Met à jour l'état de synchronisation.

        Args:
            sync_state: Nouvel état de sync.

        Returns:
            État mis à jour.
        """
        pass

    @abstractmethod
    def get_drafts_since(
        self,
        user_id: str,
        since: Optional[datetime] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> tuple[List[MobileDraft], Optional[str], bool]:
        """
        Récupère les brouillons depuis une date.

        Args:
            user_id: Identifiant de l'utilisateur.
            since: Date depuis laquelle récupérer.
            limit: Nombre maximum de résultats.
            cursor: Curseur de pagination.

        Returns:
            Tuple (brouillons, next_cursor, has_more).
        """
        pass

    @abstractmethod
    def get_draft(self, draft_id: str, user_id: str) -> Optional[MobileDraft]:
        """
        Récupère un brouillon spécifique.

        Args:
            draft_id: Identifiant du brouillon.
            user_id: Identifiant de l'utilisateur.

        Returns:
            MobileDraft ou None si non trouvé.
        """
        pass

    @abstractmethod
    def get_pending_drafts(self, user_id: str, limit: int = 50) -> List[MobileDraft]:
        """
        Récupère les brouillons en attente d'action.

        Args:
            user_id: Identifiant de l'utilisateur.
            limit: Nombre maximum de résultats.

        Returns:
            Liste des brouillons en attente.
        """
        pass


class MobileDraftActionPort(ABC):
    """
    Interface abstraite pour les actions sur les brouillons mobiles.
    """

    @abstractmethod
    def apply_action(self, request: MobileDraftActionRequest) -> bool:
        """
        Applique une action sur un brouillon.

        Args:
            request: Requête d'action.

        Returns:
            True si l'action a été appliquée.
        """
        pass

    @abstractmethod
    def apply_batch_actions(self, requests: List[MobileDraftActionRequest]) -> Dict[str, bool]:
        """
        Applique plusieurs actions en batch.

        Args:
            requests: Liste des requêtes d'action.

        Returns:
            Dictionnaire {draft_id: success}.
        """
        pass

    @abstractmethod
    def mark_read(self, draft_id: str, user_id: str) -> bool:
        """
        Marque un brouillon comme lu.

        Args:
            draft_id: Identifiant du brouillon.
            user_id: Identifiant de l'utilisateur.

        Returns:
            True si marqué avec succès.
        """
        pass

    @abstractmethod
    def get_action_history(
        self,
        user_id: str,
        draft_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Récupère l'historique des actions.

        Args:
            user_id: Identifiant de l'utilisateur.
            draft_id: Filtrer par brouillon (optionnel).
            limit: Nombre maximum de résultats.

        Returns:
            Liste des actions.
        """
        pass


class MobileAnalyticsPort(ABC):
    """
    Interface abstraite pour les analytics mobiles.
    """

    @abstractmethod
    def track_event(self, event: MobileAnalyticsEvent) -> bool:
        """
        Enregistre un événement analytics.

        Args:
            event: Événement à enregistrer.

        Returns:
            True si enregistré avec succès.
        """
        pass

    @abstractmethod
    def track_batch(self, events: List[MobileAnalyticsEvent]) -> int:
        """
        Enregistre plusieurs événements en batch.

        Args:
            events: Liste des événements.

        Returns:
            Nombre d'événements enregistrés.
        """
        pass

    @abstractmethod
    def get_events(
        self,
        user_id: str,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[MobileAnalyticsEvent]:
        """
        Récupère les événements analytics.

        Args:
            user_id: Identifiant de l'utilisateur.
            event_type: Type d'événement à filtrer.
            since: Depuis quand.
            limit: Nombre maximum.

        Returns:
            Liste des événements.
        """
        pass

    @abstractmethod
    def get_stats(self, user_id: str, days: int = 7) -> MobileStats:
        """
        Récupère les statistiques pour le dashboard.

        Args:
            user_id: Identifiant de l'utilisateur.
            days: Nombre de jours pour les stats.

        Returns:
            Statistiques mobile.
        """
        pass

    @abstractmethod
    def cleanup_old_events(self, days: int = 90) -> int:
        """
        Nettoie les anciens événements.

        Args:
            days: Âge maximum en jours.

        Returns:
            Nombre d'événements supprimés.
        """
        pass


class MobileUserPreferencesPort(ABC):
    """
    Interface abstraite pour les préférences utilisateur mobiles.
    """

    @abstractmethod
    def get(self, user_id: str) -> Optional[MobileUserPreferences]:
        """
        Récupère les préférences d'un utilisateur.

        Args:
            user_id: Identifiant de l'utilisateur.

        Returns:
            Préférences ou None si non trouvées.
        """
        pass

    @abstractmethod
    def save(self, preferences: MobileUserPreferences) -> MobileUserPreferences:
        """
        Enregistre les préférences.

        Args:
            preferences: Préférences à sauvegarder.

        Returns:
            Préférences sauvegardées.
        """
        pass

    @abstractmethod
    def update(
        self,
        user_id: str,
        updates: Dict[str, Any],
    ) -> Optional[MobileUserPreferences]:
        """
        Met à jour partiellement les préférences.

        Args:
            user_id: Identifiant de l'utilisateur.
            updates: Champs à mettre à jour.

        Returns:
            Préférences mises à jour ou None.
        """
        pass

    @abstractmethod
    def delete(self, user_id: str) -> bool:
        """
        Supprime les préférences d'un utilisateur.

        Args:
            user_id: Identifiant de l'utilisateur.

        Returns:
            True si supprimées.
        """
        pass


class MobileAppConfigPort(ABC):
    """
    Interface abstraite pour la configuration de l'app mobile.
    """

    @abstractmethod
    def get(self) -> MobileAppConfig:
        """
        Récupère la configuration de l'app.

        Returns:
            Configuration de l'app.
        """
        pass

    @abstractmethod
    def update(self, config: MobileAppConfig) -> MobileAppConfig:
        """
        Met à jour la configuration.

        Args:
            config: Nouvelle configuration.

        Returns:
            Configuration mise à jour.
        """
        pass

    @abstractmethod
    def update_feature_flag(self, flag_name: str, enabled: bool) -> bool:
        """
        Met à jour un feature flag.

        Args:
            flag_name: Nom du flag.
            enabled: Activé ou non.

        Returns:
            True si mis à jour.
        """
        pass

    @abstractmethod
    def set_maintenance_mode(self, enabled: bool, message: Optional[str] = None) -> bool:
        """
        Active/désactive le mode maintenance.

        Args:
            enabled: Mode maintenance activé.
            message: Message de maintenance.

        Returns:
            True si mis à jour.
        """
        pass

    @abstractmethod
    def update_versions(
        self,
        min_version: Optional[str] = None,
        latest_version: Optional[str] = None,
        force_update: Optional[bool] = None,
    ) -> MobileAppConfig:
        """
        Met à jour les versions de l'app.

        Args:
            min_version: Version minimale.
            latest_version: Dernière version.
            force_update: Forcer la mise à jour.

        Returns:
            Configuration mise à jour.
        """
        pass
