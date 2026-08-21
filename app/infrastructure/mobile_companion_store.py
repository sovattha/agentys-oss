# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Implémentation du stockage pour l'app mobile companion.

Ce module fournit les adapters de persistance pour :
- Sessions mobiles
- État de synchronisation
- Actions sur les brouillons
- Analytics mobiles
- Préférences utilisateur
- Configuration de l'app

Utilise des fichiers JSON pour la persistance avec verrouillage thread-safe.
"""

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from app.domain.entities.mobile_companion import (
    MobileSession,
    MobileSyncState,
    MobileAnalyticsEvent,
    MobileDraft,
    MobileUserPreferences,
    MobileAppConfig,
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
# Session Store
# ============================================================================

class JsonFileMobileSessionStore(MobileSessionPort):
    """
    Stockage persistant des sessions mobiles dans un fichier JSON.

    Thread-safe avec verrouillage pour les accès concurrents.
    """

    def __init__(self, filepath: Path):
        """Initialise le store."""
        self.filepath = filepath
        self._sessions: Dict[str, MobileSession] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Charge les sessions depuis le fichier."""
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                for session_data in data.get("sessions", []):
                    session = MobileSession.from_dict(session_data)
                    self._sessions[session.session_id] = session
                logger.debug(f"Loaded {len(self._sessions)} mobile sessions")
            except Exception as e:
                logger.error(f"Error loading mobile sessions: {e}")

    def _save(self) -> None:
        """Sauvegarde les sessions."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "sessions": [s.to_dict() for s in self._sessions.values()],
            "updated_at": datetime.now().isoformat(),
        }
        self.filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def create(
        self,
        user_id: str,
        device_token: Optional[str] = None,
        app_version: Optional[str] = None,
        os_version: Optional[str] = None,
        device_model: Optional[str] = None,
    ) -> MobileSession:
        """Crée une nouvelle session mobile."""
        with self._lock:
            session = MobileSession(
                user_id=user_id,
                device_token=device_token,
                app_version=app_version,
                os_version=os_version,
                device_model=device_model,
            )
            self._sessions[session.session_id] = session
            self._save()
            logger.info(f"Mobile session created: {session.session_id}")
            return session

    def get(self, session_id: str) -> Optional[MobileSession]:
        """Récupère une session par son ID."""
        return self._sessions.get(session_id)

    def get_active_by_user(self, user_id: str) -> List[MobileSession]:
        """Récupère les sessions actives d'un utilisateur."""
        return [
            s for s in self._sessions.values()
            if s.user_id == user_id and s.is_active
        ]

    def touch(self, session_id: str) -> bool:
        """Met à jour l'activité d'une session."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].touch()
                self._save()
                return True
            return False

    def end(self, session_id: str) -> bool:
        """Termine une session."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].end()
                self._save()
                logger.info(f"Mobile session ended: {session_id}")
                return True
            return False

    def end_all_for_user(self, user_id: str) -> int:
        """Termine toutes les sessions d'un utilisateur."""
        with self._lock:
            count = 0
            for session in self._sessions.values():
                if session.user_id == user_id and session.is_active:
                    session.end()
                    count += 1
            if count > 0:
                self._save()
            return count

    def cleanup_inactive(self, inactive_minutes: int = 30) -> int:
        """Nettoie les sessions inactives."""
        with self._lock:
            threshold = datetime.now() - timedelta(minutes=inactive_minutes)
            to_remove = []
            for session_id, session in self._sessions.items():
                if session.is_active and session.last_activity_at < threshold:
                    session.end()
                    to_remove.append(session_id)
            if to_remove:
                self._save()
                logger.info(f"Cleaned up {len(to_remove)} inactive sessions")
            return len(to_remove)


# ============================================================================
# Sync Store
# ============================================================================

class JsonFileMobileSyncStore(MobileSyncPort):
    """
    Stockage pour la synchronisation mobile.

    Gère l'état de sync et fournit les brouillons à synchroniser.
    """

    def __init__(self, filepath: Path, drafts_filepath: Optional[Path] = None):
        """
        Initialise le store.

        Args:
            filepath: Chemin pour le fichier d'état de sync.
            drafts_filepath: Chemin pour les brouillons (optionnel).
        """
        self.filepath = filepath
        self.drafts_filepath = drafts_filepath
        self._sync_states: Dict[str, MobileSyncState] = {}
        self._drafts: Dict[str, MobileDraft] = {}  # draft_id -> MobileDraft
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Charge les états de sync et brouillons."""
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                for state_data in data.get("sync_states", []):
                    state = MobileSyncState.from_dict(state_data)
                    key = f"{state.user_id}:{state.device_token}"
                    self._sync_states[key] = state
                for draft_data in data.get("drafts", []):
                    draft = MobileDraft.from_dict(draft_data)
                    self._drafts[draft.draft_id] = draft
                logger.debug(f"Loaded {len(self._sync_states)} sync states and {len(self._drafts)} drafts")
            except Exception as e:
                logger.error(f"Error loading mobile sync data: {e}")

    def _save(self) -> None:
        """Sauvegarde les données."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "sync_states": [s.to_dict() for s in self._sync_states.values()],
            "drafts": [d.to_dict() for d in self._drafts.values()],
            "updated_at": datetime.now().isoformat(),
        }
        self.filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_sync_state(self, user_id: str, device_token: str) -> Optional[MobileSyncState]:
        """Récupère l'état de synchronisation."""
        key = f"{user_id}:{device_token}"
        return self._sync_states.get(key)

    def update_sync_state(self, sync_state: MobileSyncState) -> MobileSyncState:
        """Met à jour l'état de synchronisation."""
        with self._lock:
            key = f"{sync_state.user_id}:{sync_state.device_token}"
            self._sync_states[key] = sync_state
            self._save()
            return sync_state

    def get_drafts_since(
        self,
        user_id: str,
        since: Optional[datetime] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Tuple[List[MobileDraft], Optional[str], bool]:
        """Récupère les brouillons depuis une date."""
        # Filtrer et trier les brouillons
        drafts = sorted(
            self._drafts.values(),
            key=lambda d: d.created_at,
            reverse=True,
        )

        # Appliquer le filtre de date
        if since:
            drafts = [d for d in drafts if d.updated_at >= since]

        # Appliquer la pagination avec curseur
        if cursor:
            try:
                cursor_idx = next(
                    i for i, d in enumerate(drafts)
                    if d.draft_id == cursor
                )
                drafts = drafts[cursor_idx + 1:]
            except StopIteration:
                pass

        # Appliquer la limite
        has_more = len(drafts) > limit
        drafts = drafts[:limit]

        # Calculer le next_cursor
        next_cursor = drafts[-1].draft_id if has_more and drafts else None

        return drafts, next_cursor, has_more

    @staticmethod
    def _draft_belongs_to(draft: MobileDraft, user_id: str) -> bool:
        """Audit P0-001 (2026-04-28): owner check.

        ``MobileDraft`` does not currently carry a ``user_id`` field at
        the entity level (single-tenant legacy design). When such a field
        is added (or attached at runtime by add_draft), this helper
        enforces ownership; otherwise it falls back to "no owner = no
        filter" so legacy single-tenant deployments keep working. Caller
        identity ALSO comes from the JWT-level guard in ``app/api/mobile.py``
        so even without per-row ownership a remote attacker can no
        longer pass an arbitrary ``user_id`` query parameter.
        """
        owner = getattr(draft, "user_id", None)
        if not owner:
            return True
        return str(owner) == str(user_id)

    def get_draft(self, draft_id: str, user_id: str) -> Optional[MobileDraft]:
        """Récupère un brouillon spécifique.

        Audit P0-001 (2026-04-28): when the draft has an explicit owner
        (``user_id`` attribute) it MUST match the caller — otherwise one
        tenant could fetch another's draft using only the draft_id.
        """
        draft = self._drafts.get(draft_id)
        if draft is None:
            return None
        if user_id and not self._draft_belongs_to(draft, user_id):
            return None
        return draft

    def get_pending_drafts(self, user_id: str, limit: int = 50) -> List[MobileDraft]:
        """Récupère les brouillons en attente d'action.

        Audit P0-001 (2026-04-28): filter by owner when the entity carries
        a ``user_id`` attribute.
        """
        pending = [
            d for d in self._drafts.values()
            if d.action == MobileDraftAction.PENDING
            and (not user_id or self._draft_belongs_to(d, user_id))
        ]
        # Trier par priorité décroissante puis par date
        pending.sort(key=lambda d: (-d.priority_score, d.created_at))
        return pending[:limit]

    # Méthodes pour ajouter/modifier les brouillons (utilisées par les tests)
    def add_draft(self, draft: MobileDraft) -> MobileDraft:
        """Ajoute un brouillon."""
        with self._lock:
            self._drafts[draft.draft_id] = draft
            self._save()
            return draft

    def update_draft(self, draft: MobileDraft) -> MobileDraft:
        """Met à jour un brouillon."""
        with self._lock:
            self._drafts[draft.draft_id] = draft
            self._save()
            return draft


# ============================================================================
# Action Store
# ============================================================================

class JsonFileMobileDraftActionStore(MobileDraftActionPort):
    """
    Gère les actions sur les brouillons depuis l'app mobile.
    """

    def __init__(self, filepath: Path, sync_store: JsonFileMobileSyncStore):
        """
        Initialise le store.

        Args:
            filepath: Chemin pour l'historique des actions.
            sync_store: Référence au sync store pour accéder aux brouillons.
        """
        self.filepath = filepath
        self._sync_store = sync_store
        self._action_history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Charge l'historique des actions."""
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                self._action_history = data.get("actions", [])
                logger.debug(f"Loaded {len(self._action_history)} action records")
            except Exception as e:
                logger.error(f"Error loading action history: {e}")

    def _save(self) -> None:
        """Sauvegarde l'historique."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "actions": self._action_history[-1000:],  # Garder les 1000 dernières
            "updated_at": datetime.now().isoformat(),
        }
        self.filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def apply_action(self, request: MobileDraftActionRequest) -> bool:
        """Applique une action sur un brouillon."""
        with self._lock:
            draft = self._sync_store.get_draft(request.draft_id, request.user_id)
            if not draft:
                return False

            # Appliquer l'action
            if request.action == MobileDraftAction.APPROVED:
                draft.approve()
            elif request.action == MobileDraftAction.REJECTED:
                draft.reject()
            elif request.action == MobileDraftAction.EDITED:
                if request.edited_body:
                    draft.edit(request.edited_body)
            elif request.action == MobileDraftAction.SENT:
                draft.action = MobileDraftAction.SENT
                draft.updated_at = datetime.now()

            # Mettre à jour le brouillon
            self._sync_store.update_draft(draft)

            # Enregistrer l'action
            self._action_history.append({
                "draft_id": request.draft_id,
                "user_id": request.user_id,
                "action": request.action.value,
                "device_token": request.device_token,
                "timestamp": datetime.now().isoformat(),
                "offline_timestamp": request.offline_timestamp.isoformat() if request.offline_timestamp else None,
            })
            self._save()

            logger.info(f"Action {request.action.value} applied to draft {request.draft_id}")
            return True

    def apply_batch_actions(self, requests: List[MobileDraftActionRequest]) -> Dict[str, bool]:
        """Applique plusieurs actions en batch."""
        results = {}
        for request in requests:
            results[request.draft_id] = self.apply_action(request)
        return results

    def mark_read(self, draft_id: str, user_id: str) -> bool:
        """Marque un brouillon comme lu."""
        with self._lock:
            draft = self._sync_store.get_draft(draft_id, user_id)
            if draft:
                draft.mark_read()
                self._sync_store.update_draft(draft)
                return True
            return False

    def get_action_history(
        self,
        user_id: str,
        draft_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Récupère l'historique des actions."""
        history = [
            a for a in self._action_history
            if a.get("user_id") == user_id
        ]
        if draft_id:
            history = [a for a in history if a.get("draft_id") == draft_id]
        return history[-limit:]


# ============================================================================
# Analytics Store
# ============================================================================

class JsonFileMobileAnalyticsStore(MobileAnalyticsPort):
    """
    Stockage des événements analytics mobiles.
    """

    def __init__(self, filepath: Path):
        """Initialise le store."""
        self.filepath = filepath
        self._events: List[MobileAnalyticsEvent] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Charge les événements."""
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                for event_data in data.get("events", []):
                    event = MobileAnalyticsEvent.from_dict(event_data)
                    self._events.append(event)
                logger.debug(f"Loaded {len(self._events)} analytics events")
            except Exception as e:
                logger.error(f"Error loading analytics events: {e}")

    def _save(self) -> None:
        """Sauvegarde les événements."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "events": [e.to_dict() for e in self._events[-10000:]],  # Garder les 10000 derniers
            "updated_at": datetime.now().isoformat(),
        }
        self.filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def track_event(self, event: MobileAnalyticsEvent) -> bool:
        """Enregistre un événement analytics."""
        with self._lock:
            self._events.append(event)
            self._save()
            return True

    def track_batch(self, events: List[MobileAnalyticsEvent]) -> int:
        """Enregistre plusieurs événements."""
        with self._lock:
            self._events.extend(events)
            self._save()
            return len(events)

    def get_events(
        self,
        user_id: str,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[MobileAnalyticsEvent]:
        """Récupère les événements analytics."""
        events = [e for e in self._events if e.user_id == user_id]

        if event_type:
            events = [e for e in events if e.event_type.value == event_type]

        if since:
            events = [e for e in events if e.timestamp >= since]

        # Trier par date décroissante
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def get_stats(self, user_id: str, days: int = 7) -> MobileStats:
        """Récupère les statistiques pour le dashboard mobile."""
        now = datetime.now()
        period_start = now - timedelta(days=days)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Filtrer les événements de la période
        events = [
            e for e in self._events
            if e.user_id == user_id and e.timestamp >= period_start
        ]

        # Compter les actions
        today_events = [e for e in events if e.timestamp >= today_start]

        approved_today = sum(
            1 for e in today_events
            if e.event_type == MobileEventType.DRAFT_APPROVE
        )
        rejected_today = sum(
            1 for e in today_events
            if e.event_type == MobileEventType.DRAFT_REJECT
        )

        # Calculer les métriques
        total_drafts = sum(
            1 for e in events
            if e.event_type == MobileEventType.DRAFT_VIEW
        )
        pending_drafts = 0  # À calculer depuis le sync store

        # Temps moyen de réponse (mock)
        avg_response_time = 120.0  # 2 minutes en moyenne

        # Précision IA (basée sur ratio approve/reject)
        total_actions = approved_today + rejected_today
        ai_accuracy = (approved_today / total_actions * 100) if total_actions > 0 else 0.0

        # Temps économisé (estimation: 3 min par brouillon approuvé)
        time_saved = approved_today * 3

        return MobileStats(
            user_id=user_id,
            total_drafts=total_drafts,
            pending_drafts=pending_drafts,
            approved_today=approved_today,
            rejected_today=rejected_today,
            avg_response_time_seconds=avg_response_time,
            ai_accuracy_percentage=ai_accuracy,
            time_saved_minutes=time_saved,
            period_start=period_start,
            period_end=now,
        )

    def cleanup_old_events(self, days: int = 90) -> int:
        """Nettoie les anciens événements."""
        with self._lock:
            threshold = datetime.now() - timedelta(days=days)
            original_count = len(self._events)
            self._events = [e for e in self._events if e.timestamp >= threshold]
            removed = original_count - len(self._events)
            if removed > 0:
                self._save()
                logger.info(f"Cleaned up {removed} old analytics events")
            return removed


# ============================================================================
# Preferences Store
# ============================================================================

class JsonFileMobilePreferencesStore(MobileUserPreferencesPort):
    """
    Stockage des préférences utilisateur mobiles.
    """

    def __init__(self, filepath: Path):
        """Initialise le store."""
        self.filepath = filepath
        self._preferences: Dict[str, MobileUserPreferences] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Charge les préférences."""
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                for pref_data in data.get("preferences", []):
                    pref = MobileUserPreferences.from_dict(pref_data)
                    self._preferences[pref.user_id] = pref
                logger.debug(f"Loaded {len(self._preferences)} user preferences")
            except Exception as e:
                logger.error(f"Error loading preferences: {e}")

    def _save(self) -> None:
        """Sauvegarde les préférences."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "preferences": [p.to_dict() for p in self._preferences.values()],
            "updated_at": datetime.now().isoformat(),
        }
        self.filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get(self, user_id: str) -> Optional[MobileUserPreferences]:
        """Récupère les préférences d'un utilisateur."""
        return self._preferences.get(user_id)

    def save(self, preferences: MobileUserPreferences) -> MobileUserPreferences:
        """Enregistre les préférences."""
        with self._lock:
            self._preferences[preferences.user_id] = preferences
            self._save()
            return preferences

    def update(
        self,
        user_id: str,
        updates: Dict[str, Any],
    ) -> Optional[MobileUserPreferences]:
        """Met à jour partiellement les préférences."""
        from app.domain.entities.mobile_companion import NotificationPreference, SyncFrequency

        with self._lock:
            pref = self._preferences.get(user_id)
            if not pref:
                return None

            # Appliquer les mises à jour avec conversion des enums
            for key, value in updates.items():
                if hasattr(pref, key):
                    # Convertir les chaînes en enums pour les champs appropriés
                    if key == "notification_preference" and isinstance(value, str):
                        value = NotificationPreference(value)
                    elif key == "sync_frequency" and isinstance(value, str):
                        value = SyncFrequency(value)
                    setattr(pref, key, value)

            pref.updated_at = datetime.now()
            self._preferences[user_id] = pref
            self._save()
            return pref

    def delete(self, user_id: str) -> bool:
        """Supprime les préférences d'un utilisateur."""
        with self._lock:
            if user_id in self._preferences:
                del self._preferences[user_id]
                self._save()
                return True
            return False


# ============================================================================
# App Config Store
# ============================================================================

class JsonFileMobileAppConfigStore(MobileAppConfigPort):
    """
    Stockage de la configuration de l'app mobile.
    """

    def __init__(self, filepath: Path):
        """Initialise le store."""
        self.filepath = filepath
        self._config: MobileAppConfig = MobileAppConfig()
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Charge la configuration."""
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                if "config" in data:
                    self._config = MobileAppConfig.from_dict(data["config"])
                logger.debug("Loaded mobile app config")
            except Exception as e:
                logger.error(f"Error loading app config: {e}")

    def _save(self) -> None:
        """Sauvegarde la configuration."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "config": self._config.to_dict(),
            "updated_at": datetime.now().isoformat(),
        }
        self.filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get(self) -> MobileAppConfig:
        """Récupère la configuration de l'app."""
        return self._config

    def update(self, config: MobileAppConfig) -> MobileAppConfig:
        """Met à jour la configuration."""
        with self._lock:
            self._config = config
            self._config.updated_at = datetime.now()
            self._save()
            return self._config

    def update_feature_flag(self, flag_name: str, enabled: bool) -> bool:
        """Met à jour un feature flag."""
        with self._lock:
            self._config.feature_flags[flag_name] = enabled
            self._config.updated_at = datetime.now()
            self._save()
            return True

    def set_maintenance_mode(self, enabled: bool, message: Optional[str] = None) -> bool:
        """Active/désactive le mode maintenance."""
        with self._lock:
            self._config.maintenance_mode = enabled
            self._config.maintenance_message = message
            self._config.updated_at = datetime.now()
            self._save()
            return True

    def update_versions(
        self,
        min_version: Optional[str] = None,
        latest_version: Optional[str] = None,
        force_update: Optional[bool] = None,
    ) -> MobileAppConfig:
        """Met à jour les versions de l'app."""
        with self._lock:
            if min_version is not None:
                self._config.min_version = min_version
            if latest_version is not None:
                self._config.latest_version = latest_version
            if force_update is not None:
                self._config.force_update = force_update
            self._config.updated_at = datetime.now()
            self._save()
            return self._config


# ============================================================================
# Factory Functions (Singletons)
# ============================================================================

_session_store: Optional[JsonFileMobileSessionStore] = None
_sync_store: Optional[JsonFileMobileSyncStore] = None
_action_store: Optional[JsonFileMobileDraftActionStore] = None
_analytics_store: Optional[JsonFileMobileAnalyticsStore] = None
_preferences_store: Optional[JsonFileMobilePreferencesStore] = None
_config_store: Optional[JsonFileMobileAppConfigStore] = None


def get_mobile_session_store(filepath: Optional[Path] = None) -> JsonFileMobileSessionStore:
    """Retourne le singleton du session store."""
    global _session_store
    if _session_store is None:
        if filepath is None:
            from app.config import PROJECT_ROOT
            filepath = PROJECT_ROOT / "data" / "mobile" / "sessions.json"
        _session_store = JsonFileMobileSessionStore(filepath)
    return _session_store


def get_mobile_sync_store(filepath: Optional[Path] = None) -> JsonFileMobileSyncStore:
    """Retourne le singleton du sync store."""
    global _sync_store
    if _sync_store is None:
        if filepath is None:
            from app.config import PROJECT_ROOT
            filepath = PROJECT_ROOT / "data" / "mobile" / "sync.json"
        _sync_store = JsonFileMobileSyncStore(filepath)
    return _sync_store


def get_mobile_action_store(filepath: Optional[Path] = None) -> JsonFileMobileDraftActionStore:
    """Retourne le singleton de l'action store."""
    global _action_store
    if _action_store is None:
        if filepath is None:
            from app.config import PROJECT_ROOT
            filepath = PROJECT_ROOT / "data" / "mobile" / "actions.json"
        _action_store = JsonFileMobileDraftActionStore(filepath, get_mobile_sync_store())
    return _action_store


def get_mobile_analytics_store(filepath: Optional[Path] = None) -> JsonFileMobileAnalyticsStore:
    """Retourne le singleton de l'analytics store."""
    global _analytics_store
    if _analytics_store is None:
        if filepath is None:
            from app.config import PROJECT_ROOT
            filepath = PROJECT_ROOT / "data" / "mobile" / "analytics.json"
        _analytics_store = JsonFileMobileAnalyticsStore(filepath)
    return _analytics_store


def get_mobile_preferences_store(filepath: Optional[Path] = None) -> JsonFileMobilePreferencesStore:
    """Retourne le singleton du preferences store."""
    global _preferences_store
    if _preferences_store is None:
        if filepath is None:
            from app.config import PROJECT_ROOT
            filepath = PROJECT_ROOT / "data" / "mobile" / "preferences.json"
        _preferences_store = JsonFileMobilePreferencesStore(filepath)
    return _preferences_store


def get_mobile_config_store(filepath: Optional[Path] = None) -> JsonFileMobileAppConfigStore:
    """Retourne le singleton du config store."""
    global _config_store
    if _config_store is None:
        if filepath is None:
            from app.config import PROJECT_ROOT
            filepath = PROJECT_ROOT / "data" / "mobile" / "config.json"
        _config_store = JsonFileMobileAppConfigStore(filepath)
    return _config_store


def reset_mobile_stores() -> None:
    """Réinitialise tous les singletons (utile pour les tests)."""
    global _session_store, _sync_store, _action_store
    global _analytics_store, _preferences_store, _config_store
    _session_store = None
    _sync_store = None
    _action_store = None
    _analytics_store = None
    _preferences_store = None
    _config_store = None
