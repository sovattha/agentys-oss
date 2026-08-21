# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use cases pour l'app mobile companion.

Ce module contient la logique métier pour :
- Gestion des sessions mobiles
- Synchronisation des brouillons
- Actions sur les brouillons (approve/reject/edit)
- Analytics mobiles
- Préférences utilisateur
- Configuration de l'app

Règle Clean Architecture : Ces use cases dépendent uniquement du domaine.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any

from app.domain.entities.mobile_companion import (
    MobileSession,
    MobileSyncState,
    MobileAnalyticsEvent,
    MobileDraft,
    MobileUserPreferences,
    MobileAppConfig,
    MobileSyncResponse,
    MobileDraftActionRequest,
    MobileStats,
    MobileEventType,
    MobileDraftAction,
)
from app.domain.ports.mobile_companion_port import (
    MobileSessionPort,
    MobileSyncPort,
    MobileDraftActionPort,
    MobileAnalyticsPort,
    MobileUserPreferencesPort,
    MobileAppConfigPort,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Session Use Cases
# ============================================================================

@dataclass
class StartSessionResult:
    """Résultat du démarrage d'une session."""
    success: bool
    session: Optional[MobileSession] = None
    app_config: Optional[MobileAppConfig] = None
    preferences: Optional[MobileUserPreferences] = None
    error_message: Optional[str] = None


@dataclass
class StartMobileSessionUseCase:
    """
    Use case pour démarrer une session mobile.

    Crée une nouvelle session et retourne la configuration initiale.
    """
    session_port: MobileSessionPort
    config_port: MobileAppConfigPort
    preferences_port: MobileUserPreferencesPort

    def execute(
        self,
        user_id: str,
        device_token: Optional[str] = None,
        app_version: Optional[str] = None,
        os_version: Optional[str] = None,
        device_model: Optional[str] = None,
    ) -> StartSessionResult:
        """
        Démarre une nouvelle session mobile.

        Args:
            user_id: Identifiant de l'utilisateur.
            device_token: Token push du device.
            app_version: Version de l'app.
            os_version: Version de l'OS.
            device_model: Modèle du device.

        Returns:
            Résultat avec session et configuration.
        """
        try:
            # Vérifier la version de l'app
            config = self.config_port.get()
            if app_version and not config.is_version_supported(app_version):
                return StartSessionResult(
                    success=False,
                    app_config=config,
                    error_message=f"App version {app_version} is not supported. Minimum required: {config.min_version}",
                )

            # Vérifier le mode maintenance
            if config.maintenance_mode:
                return StartSessionResult(
                    success=False,
                    app_config=config,
                    error_message=config.maintenance_message or "App is currently in maintenance mode",
                )

            # Créer la session
            session = self.session_port.create(
                user_id=user_id,
                device_token=device_token,
                app_version=app_version,
                os_version=os_version,
                device_model=device_model,
            )

            # Récupérer les préférences
            preferences = self.preferences_port.get(user_id)
            if not preferences:
                # Créer des préférences par défaut
                preferences = MobileUserPreferences(user_id=user_id)
                self.preferences_port.save(preferences)

            logger.info(f"Mobile session started: {session.session_id} for user {user_id}")

            return StartSessionResult(
                success=True,
                session=session,
                app_config=config,
                preferences=preferences,
            )

        except Exception as e:
            logger.error(f"Failed to start mobile session: {e}")
            return StartSessionResult(
                success=False,
                error_message=str(e),
            )


@dataclass
class EndMobileSessionUseCase:
    """Use case pour terminer une session mobile."""
    session_port: MobileSessionPort
    analytics_port: MobileAnalyticsPort

    def execute(self, session_id: str, user_id: str) -> bool:
        """
        Termine une session mobile.

        Args:
            session_id: Identifiant de la session.
            user_id: Identifiant de l'utilisateur.

        Returns:
            True si terminée avec succès.
        """
        try:
            # Terminer la session
            success = self.session_port.end(session_id)

            if success:
                # Enregistrer l'événement analytics
                event = MobileAnalyticsEvent(
                    event_type=MobileEventType.APP_CLOSE,
                    user_id=user_id,
                    session_id=session_id,
                )
                self.analytics_port.track_event(event)

                logger.info(f"Mobile session ended: {session_id}")

            return success

        except Exception as e:
            logger.error(f"Failed to end mobile session: {e}")
            return False


@dataclass
class TouchSessionUseCase:
    """Use case pour maintenir une session active."""
    session_port: MobileSessionPort

    def execute(self, session_id: str) -> bool:
        """Met à jour l'activité de la session."""
        return self.session_port.touch(session_id)


# ============================================================================
# Sync Use Cases
# ============================================================================

@dataclass
class SyncMobileDataUseCase:
    """
    Use case pour synchroniser les données mobiles.

    Récupère les brouillons modifiés depuis la dernière sync.
    """
    sync_port: MobileSyncPort
    analytics_port: MobileAnalyticsPort

    def execute(
        self,
        user_id: str,
        device_token: str,
        since: Optional[datetime] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> MobileSyncResponse:
        """
        Synchronise les brouillons avec le mobile.

        Args:
            user_id: Identifiant de l'utilisateur.
            device_token: Token du device.
            since: Date depuis laquelle synchroniser.
            limit: Nombre maximum de brouillons.
            cursor: Curseur de pagination.

        Returns:
            Réponse de synchronisation.
        """
        try:
            # Récupérer ou créer l'état de sync
            sync_state = self.sync_port.get_sync_state(user_id, device_token)
            if not sync_state:
                sync_state = MobileSyncState(user_id=user_id, device_token=device_token)

            # Marquer le début de la sync
            sync_state.mark_syncing()

            # Enregistrer l'événement
            self.analytics_port.track_event(MobileAnalyticsEvent(
                event_type=MobileEventType.SYNC_START,
                user_id=user_id,
                properties={"since": since.isoformat() if since else None},
            ))

            # Récupérer les brouillons
            drafts, next_cursor, has_more = self.sync_port.get_drafts_since(
                user_id=user_id,
                since=since or sync_state.last_sync_at,
                limit=limit,
                cursor=cursor,
            )

            # Mettre à jour l'état de sync
            sync_state.mark_success(len(drafts))
            self.sync_port.update_sync_state(sync_state)

            # Enregistrer le succès
            self.analytics_port.track_event(MobileAnalyticsEvent(
                event_type=MobileEventType.SYNC_COMPLETE,
                user_id=user_id,
                properties={"drafts_count": len(drafts)},
            ))

            logger.info(f"Synced {len(drafts)} drafts for user {user_id}")

            return MobileSyncResponse(
                success=True,
                drafts=drafts,
                sync_state=sync_state,
                has_more=has_more,
                next_cursor=next_cursor,
            )

        except Exception as e:
            logger.error(f"Sync failed for user {user_id}: {e}")

            # Enregistrer l'échec
            if sync_state:
                sync_state.mark_failed(str(e))
                self.sync_port.update_sync_state(sync_state)

            self.analytics_port.track_event(MobileAnalyticsEvent(
                event_type=MobileEventType.SYNC_ERROR,
                user_id=user_id,
                properties={"error": str(e)},
            ))

            return MobileSyncResponse(
                success=False,
                sync_state=sync_state,
                error_message=str(e),
            )


@dataclass
class GetDraftDetailsUseCase:
    """Use case pour récupérer les détails d'un brouillon."""
    sync_port: MobileSyncPort
    analytics_port: MobileAnalyticsPort

    def execute(self, draft_id: str, user_id: str) -> Optional[MobileDraft]:
        """
        Récupère les détails complets d'un brouillon.

        Args:
            draft_id: Identifiant du brouillon.
            user_id: Identifiant de l'utilisateur.

        Returns:
            Brouillon ou None si non trouvé.
        """
        draft = self.sync_port.get_draft(draft_id, user_id)

        if draft:
            # Enregistrer la vue
            self.analytics_port.track_event(MobileAnalyticsEvent(
                event_type=MobileEventType.DRAFT_VIEW,
                user_id=user_id,
                properties={"draft_id": draft_id},
            ))

        return draft


@dataclass
class GetPendingDraftsUseCase:
    """Use case pour récupérer les brouillons en attente."""
    sync_port: MobileSyncPort

    def execute(self, user_id: str, limit: int = 50) -> List[MobileDraft]:
        """
        Récupère les brouillons en attente d'action.

        Args:
            user_id: Identifiant de l'utilisateur.
            limit: Nombre maximum.

        Returns:
            Liste des brouillons en attente.
        """
        return self.sync_port.get_pending_drafts(user_id, limit)


# ============================================================================
# Draft Action Use Cases
# ============================================================================

def get_event_type_for_action(action: MobileDraftAction) -> MobileEventType:
    """
    Convertit une action de brouillon en type d'événement analytics.

    Args:
        action: L'action effectuée sur le brouillon.

    Returns:
        Le type d'événement correspondant.
    """
    mapping = {
        MobileDraftAction.APPROVED: MobileEventType.DRAFT_APPROVE,
        MobileDraftAction.REJECTED: MobileEventType.DRAFT_REJECT,
        MobileDraftAction.EDITED: MobileEventType.DRAFT_EDIT,
        MobileDraftAction.SENT: MobileEventType.DRAFT_SEND,
    }
    return mapping.get(action, MobileEventType.DRAFT_VIEW)


@dataclass
class DraftActionResult:
    """Résultat d'une action sur un brouillon."""
    success: bool
    draft: Optional[MobileDraft] = None
    error_message: Optional[str] = None


@dataclass
class ApplyDraftActionUseCase:
    """
    Use case pour appliquer une action sur un brouillon.

    Supporte: approve, reject, edit, send.
    """
    action_port: MobileDraftActionPort
    sync_port: MobileSyncPort
    analytics_port: MobileAnalyticsPort

    def execute(self, request: MobileDraftActionRequest) -> DraftActionResult:
        """
        Applique une action sur un brouillon.

        Args:
            request: Requête d'action.

        Returns:
            Résultat de l'action.
        """
        try:
            # Appliquer l'action
            success = self.action_port.apply_action(request)

            if not success:
                return DraftActionResult(
                    success=False,
                    error_message="Failed to apply action",
                )

            # Récupérer le brouillon mis à jour
            draft = self.sync_port.get_draft(request.draft_id, request.user_id)

            # Enregistrer l'événement analytics
            event_type = get_event_type_for_action(request.action)
            self.analytics_port.track_event(MobileAnalyticsEvent(
                event_type=event_type,
                user_id=request.user_id,
                properties={
                    "draft_id": request.draft_id,
                    "action": request.action.value,
                    "offline": request.offline_timestamp is not None,
                },
            ))

            logger.info(f"Action {request.action.value} applied to draft {request.draft_id}")

            return DraftActionResult(
                success=True,
                draft=draft,
            )

        except Exception as e:
            logger.error(f"Failed to apply action: {e}")
            return DraftActionResult(
                success=False,
                error_message=str(e),
            )


@dataclass
class BatchActionsResult:
    """Résultat d'actions en batch."""
    success: bool
    results: Dict[str, bool] = field(default_factory=dict)
    error_count: int = 0


@dataclass
class ApplyBatchActionsUseCase:
    """Use case pour appliquer plusieurs actions en batch."""
    action_port: MobileDraftActionPort
    analytics_port: MobileAnalyticsPort

    def execute(
        self,
        requests: List[MobileDraftActionRequest],
        user_id: str,
    ) -> BatchActionsResult:
        """
        Applique plusieurs actions en batch.

        Args:
            requests: Liste des requêtes d'action.
            user_id: Identifiant de l'utilisateur.

        Returns:
            Résultat du batch.
        """
        try:
            results = self.action_port.apply_batch_actions(requests)

            error_count = sum(1 for success in results.values() if not success)

            # Enregistrer les événements
            for request in requests:
                if results.get(request.draft_id, False):
                    event_type = get_event_type_for_action(request.action)
                    self.analytics_port.track_event(MobileAnalyticsEvent(
                        event_type=event_type,
                        user_id=user_id,
                        properties={
                            "draft_id": request.draft_id,
                            "action": request.action.value,
                            "batch": True,
                        },
                    ))

            logger.info(f"Batch actions completed: {len(requests) - error_count}/{len(requests)} succeeded")

            return BatchActionsResult(
                success=error_count == 0,
                results=results,
                error_count=error_count,
            )

        except Exception as e:
            logger.error(f"Batch actions failed: {e}")
            return BatchActionsResult(
                success=False,
                error_count=len(requests),
            )


@dataclass
class MarkDraftReadUseCase:
    """Use case pour marquer un brouillon comme lu."""
    action_port: MobileDraftActionPort

    def execute(self, draft_id: str, user_id: str) -> bool:
        """Marque un brouillon comme lu."""
        return self.action_port.mark_read(draft_id, user_id)


# ============================================================================
# Analytics Use Cases
# ============================================================================

@dataclass
class TrackMobileEventUseCase:
    """Use case pour enregistrer un événement analytics."""
    analytics_port: MobileAnalyticsPort

    def execute(self, event: MobileAnalyticsEvent) -> bool:
        """Enregistre un événement analytics."""
        return self.analytics_port.track_event(event)

    def execute_batch(self, events: List[MobileAnalyticsEvent]) -> int:
        """Enregistre plusieurs événements."""
        return self.analytics_port.track_batch(events)


@dataclass
class GetMobileStatsUseCase:
    """Use case pour récupérer les statistiques mobiles."""
    analytics_port: MobileAnalyticsPort

    def execute(self, user_id: str, days: int = 7) -> MobileStats:
        """Récupère les statistiques pour le dashboard mobile."""
        return self.analytics_port.get_stats(user_id, days)


# ============================================================================
# Preferences Use Cases
# ============================================================================

@dataclass
class GetPreferencesUseCase:
    """Use case pour récupérer les préférences utilisateur."""
    preferences_port: MobileUserPreferencesPort

    def execute(self, user_id: str) -> MobileUserPreferences:
        """
        Récupère les préférences d'un utilisateur.

        Crée des préférences par défaut si non existantes.
        """
        preferences = self.preferences_port.get(user_id)
        if not preferences:
            preferences = MobileUserPreferences(user_id=user_id)
            self.preferences_port.save(preferences)
        return preferences


@dataclass
class UpdatePreferencesUseCase:
    """Use case pour mettre à jour les préférences."""
    preferences_port: MobileUserPreferencesPort
    analytics_port: MobileAnalyticsPort

    def execute(
        self,
        user_id: str,
        updates: Dict[str, Any],
    ) -> Optional[MobileUserPreferences]:
        """
        Met à jour les préférences d'un utilisateur.

        Args:
            user_id: Identifiant de l'utilisateur.
            updates: Champs à mettre à jour.

        Returns:
            Préférences mises à jour ou None.
        """
        preferences = self.preferences_port.update(user_id, updates)

        if preferences:
            # Enregistrer l'événement
            self.analytics_port.track_event(MobileAnalyticsEvent(
                event_type=MobileEventType.SETTINGS_CHANGE,
                user_id=user_id,
                properties={"changed_fields": list(updates.keys())},
            ))

        return preferences


# ============================================================================
# App Config Use Cases
# ============================================================================

@dataclass
class GetAppConfigUseCase:
    """Use case pour récupérer la configuration de l'app."""
    config_port: MobileAppConfigPort

    def execute(self, app_version: Optional[str] = None) -> Dict[str, Any]:
        """
        Récupère la configuration de l'app.

        Args:
            app_version: Version de l'app pour vérification.

        Returns:
            Configuration avec informations de version.
        """
        config = self.config_port.get()

        response = config.to_dict()

        if app_version:
            response["version_supported"] = config.is_version_supported(app_version)
            response["update_available"] = config.needs_update(app_version)

        return response


@dataclass
class UpdateAppConfigUseCase:
    """Use case pour mettre à jour la configuration (admin)."""
    config_port: MobileAppConfigPort

    def set_maintenance_mode(
        self,
        enabled: bool,
        message: Optional[str] = None,
    ) -> bool:
        """Active/désactive le mode maintenance."""
        return self.config_port.set_maintenance_mode(enabled, message)

    def update_feature_flag(self, flag_name: str, enabled: bool) -> bool:
        """Met à jour un feature flag."""
        return self.config_port.update_feature_flag(flag_name, enabled)

    def update_versions(
        self,
        min_version: Optional[str] = None,
        latest_version: Optional[str] = None,
        force_update: Optional[bool] = None,
    ) -> MobileAppConfig:
        """Met à jour les versions de l'app."""
        return self.config_port.update_versions(min_version, latest_version, force_update)


# ============================================================================
# Service Layer
# ============================================================================

class MobileCompanionService:
    """
    Service de haut niveau pour l'app mobile companion.

    Combine tous les use cases pour fournir une API unifiée.
    """

    def __init__(
        self,
        session_port: MobileSessionPort,
        sync_port: MobileSyncPort,
        action_port: MobileDraftActionPort,
        analytics_port: MobileAnalyticsPort,
        preferences_port: MobileUserPreferencesPort,
        config_port: MobileAppConfigPort,
    ):
        """Initialise le service avec tous les ports."""
        self._session_port = session_port
        self._sync_port = sync_port
        self._action_port = action_port
        self._analytics_port = analytics_port
        self._preferences_port = preferences_port
        self._config_port = config_port

        # Initialiser les use cases
        self._start_session_uc = StartMobileSessionUseCase(
            session_port=session_port,
            config_port=config_port,
            preferences_port=preferences_port,
        )
        self._end_session_uc = EndMobileSessionUseCase(
            session_port=session_port,
            analytics_port=analytics_port,
        )
        self._sync_uc = SyncMobileDataUseCase(
            sync_port=sync_port,
            analytics_port=analytics_port,
        )
        self._get_draft_uc = GetDraftDetailsUseCase(
            sync_port=sync_port,
            analytics_port=analytics_port,
        )
        self._action_uc = ApplyDraftActionUseCase(
            action_port=action_port,
            sync_port=sync_port,
            analytics_port=analytics_port,
        )
        self._stats_uc = GetMobileStatsUseCase(
            analytics_port=analytics_port,
        )
        self._preferences_uc = GetPreferencesUseCase(
            preferences_port=preferences_port,
        )
        self._update_preferences_uc = UpdatePreferencesUseCase(
            preferences_port=preferences_port,
            analytics_port=analytics_port,
        )

    def start_session(
        self,
        user_id: str,
        device_token: Optional[str] = None,
        app_version: Optional[str] = None,
        os_version: Optional[str] = None,
        device_model: Optional[str] = None,
    ) -> StartSessionResult:
        """Démarre une session mobile."""
        return self._start_session_uc.execute(
            user_id=user_id,
            device_token=device_token,
            app_version=app_version,
            os_version=os_version,
            device_model=device_model,
        )

    def end_session(self, session_id: str, user_id: str) -> bool:
        """Termine une session mobile."""
        return self._end_session_uc.execute(session_id, user_id)

    def sync_data(
        self,
        user_id: str,
        device_token: str,
        since: Optional[datetime] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> MobileSyncResponse:
        """Synchronise les données."""
        return self._sync_uc.execute(
            user_id=user_id,
            device_token=device_token,
            since=since,
            limit=limit,
            cursor=cursor,
        )

    def get_draft(self, draft_id: str, user_id: str) -> Optional[MobileDraft]:
        """Récupère les détails d'un brouillon."""
        return self._get_draft_uc.execute(draft_id, user_id)

    def get_pending_drafts(self, user_id: str, limit: int = 50) -> List[MobileDraft]:
        """Récupère les brouillons en attente."""
        return self._sync_port.get_pending_drafts(user_id, limit)

    def apply_action(self, request: MobileDraftActionRequest) -> DraftActionResult:
        """Applique une action sur un brouillon."""
        return self._action_uc.execute(request)

    def get_stats(self, user_id: str, days: int = 7) -> MobileStats:
        """Récupère les statistiques."""
        return self._stats_uc.execute(user_id, days)

    def get_preferences(self, user_id: str) -> MobileUserPreferences:
        """Récupère les préférences."""
        return self._preferences_uc.execute(user_id)

    def update_preferences(
        self,
        user_id: str,
        updates: Dict[str, Any],
    ) -> Optional[MobileUserPreferences]:
        """Met à jour les préférences."""
        return self._update_preferences_uc.execute(user_id, updates)

    def get_app_config(self, app_version: Optional[str] = None) -> Dict[str, Any]:
        """Récupère la configuration de l'app."""
        config = self._config_port.get()
        response = config.to_dict()
        if app_version:
            response["version_supported"] = config.is_version_supported(app_version)
            response["update_available"] = config.needs_update(app_version)
        return response

    def track_event(self, event: MobileAnalyticsEvent) -> bool:
        """Enregistre un événement analytics."""
        return self._analytics_port.track_event(event)

    def track_batch_events(self, events: List[MobileAnalyticsEvent]) -> int:
        """Enregistre plusieurs événements analytics."""
        return self._analytics_port.track_batch(events)

    def touch_session(self, session_id: str) -> bool:
        """Maintient une session active (heartbeat)."""
        return self._session_port.touch(session_id)

    def apply_batch_actions(
        self,
        requests: List[MobileDraftActionRequest],
        user_id: str,
    ) -> BatchActionsResult:
        """Applique plusieurs actions en batch."""
        batch_uc = ApplyBatchActionsUseCase(
            action_port=self._action_port,
            analytics_port=self._analytics_port,
        )
        return batch_uc.execute(requests, user_id)

    def mark_draft_read(self, draft_id: str, user_id: str) -> bool:
        """Marque un brouillon comme lu."""
        return self._action_port.mark_read(draft_id, user_id)

    def set_maintenance_mode(self, enabled: bool, message: Optional[str] = None) -> bool:
        """Active/désactive le mode maintenance."""
        return self._config_port.set_maintenance_mode(enabled, message)

    def update_versions(
        self,
        min_version: Optional[str] = None,
        latest_version: Optional[str] = None,
        force_update: Optional[bool] = None,
    ) -> MobileAppConfig:
        """Met à jour les versions de l'app."""
        return self._config_port.update_versions(min_version, latest_version, force_update)

    def update_feature_flag(self, flag_name: str, enabled: bool) -> bool:
        """Met à jour un feature flag."""
        return self._config_port.update_feature_flag(flag_name, enabled)


# NOTE: Factory functions supprimées pour respecter la Clean Architecture.
# Les factories sont maintenant dans app/infrastructure/container.py
# Utiliser: get_container().get_mobile_companion_service()
