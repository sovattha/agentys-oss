# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter de stockage pour les sessions d'édition temps réel.

Implémente le port EditSessionStorePort avec persistance JSON.
"""

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional, List, Dict, Any

from app.domain.entities.realtime_edit import EditSession
from app.domain.ports.realtime_edit_port import EditSessionStorePort


class JsonEditSessionStore(EditSessionStorePort):
    """
    Implémentation JSON du store de sessions d'édition.

    Thread-safe avec verrouillage pour accès concurrent.
    """

    def __init__(self, filepath: Path):
        """
        Initialise le store.

        Args:
            filepath: Chemin vers le fichier JSON de stockage.
        """
        self._filepath = filepath
        self._lock = Lock()
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Crée le fichier s'il n'existe pas."""
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self._filepath.exists():
            self._filepath.write_text("{}", encoding="utf-8")

    def _load_data(self) -> Dict[str, Any]:
        """Charge les données depuis le fichier."""
        try:
            content = self._filepath.read_text(encoding="utf-8")
            return json.loads(content) if content.strip() else {}
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_data(self, data: Dict[str, Any]) -> None:
        """Sauvegarde les données dans le fichier."""
        self._filepath.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def _session_to_dict(self, session: EditSession) -> Dict[str, Any]:
        """Convertit une session en dictionnaire pour JSON."""
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "current_text": session.current_text,
            "is_active": session.is_active,
            "created_at": session.created_at.isoformat(),
            "closed_at": session.closed_at.isoformat() if session.closed_at else None,
            "last_activity_at": session._last_activity_at.isoformat(),
            "last_processed_text": session._last_processed_text,
            "version": session.version,
        }

    def _dict_to_session(self, data: Dict[str, Any]) -> EditSession:
        """Convertit un dictionnaire en session."""
        session = EditSession(
            session_id=data["session_id"],
            user_id=data["user_id"],
            current_text=data["current_text"],
            is_active=data["is_active"],
            created_at=datetime.fromisoformat(data["created_at"]),
            closed_at=(
                datetime.fromisoformat(data["closed_at"])
                if data.get("closed_at")
                else None
            ),
            version=data.get("version", 1),
        )
        session._last_activity_at = datetime.fromisoformat(
            data.get("last_activity_at", data["created_at"])
        )
        session._last_processed_text = data.get("last_processed_text", "")
        return session

    def save(self, session: EditSession) -> None:
        """
        Sauvegarde une session d'édition.

        Args:
            session: La session à sauvegarder.
        """
        with self._lock:
            data = self._load_data()
            data[session.session_id] = self._session_to_dict(session)
            self._save_data(data)

    def get(self, session_id: str) -> Optional[EditSession]:
        """
        Récupère une session par son ID.

        Args:
            session_id: L'identifiant de la session.

        Returns:
            La session si trouvée, None sinon.
        """
        with self._lock:
            data = self._load_data()
            session_data = data.get(session_id)

            if session_data is None:
                return None

            return self._dict_to_session(session_data)

    def delete(self, session_id: str) -> bool:
        """
        Supprime une session.

        Args:
            session_id: L'identifiant de la session.

        Returns:
            True si supprimée, False si non trouvée.
        """
        with self._lock:
            data = self._load_data()

            if session_id not in data:
                return False

            del data[session_id]
            self._save_data(data)
            return True

    def get_by_user(self, user_id: str) -> List[EditSession]:
        """
        Récupère toutes les sessions actives d'un utilisateur.

        Args:
            user_id: L'identifiant de l'utilisateur.

        Returns:
            Liste des sessions actives.
        """
        with self._lock:
            data = self._load_data()
            sessions = []

            for session_data in data.values():
                if session_data["user_id"] == user_id and session_data["is_active"]:
                    sessions.append(self._dict_to_session(session_data))

            return sessions

    def cleanup_expired(self, timeout_minutes: int = 30) -> int:
        """
        Nettoie les sessions expirées.

        Args:
            timeout_minutes: Durée d'inactivité avant expiration.

        Returns:
            Nombre de sessions supprimées.
        """
        with self._lock:
            data = self._load_data()
            expired_ids = []

            for session_id, session_data in data.items():
                session = self._dict_to_session(session_data)
                if session.is_expired(timeout_minutes):
                    expired_ids.append(session_id)

            for session_id in expired_ids:
                del data[session_id]

            if expired_ids:
                self._save_data(data)

            return len(expired_ids)

    def get_all_active(self) -> List[EditSession]:
        """
        Récupère toutes les sessions actives.

        Returns:
            Liste de toutes les sessions actives.
        """
        with self._lock:
            data = self._load_data()
            sessions = []

            for session_data in data.values():
                if session_data["is_active"]:
                    sessions.append(self._dict_to_session(session_data))

            return sessions


class InMemoryEditSessionStore(EditSessionStorePort):
    """
    Implémentation en mémoire pour les tests.

    Plus rapide que JSON, pas de persistance.
    """

    def __init__(self):
        self._sessions: Dict[str, EditSession] = {}
        self._lock = Lock()

    def save(self, session: EditSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> Optional[EditSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def get_by_user(self, user_id: str) -> List[EditSession]:
        with self._lock:
            return [
                s for s in self._sessions.values()
                if s.user_id == user_id and s.is_active
            ]

    def cleanup_expired(self, timeout_minutes: int = 30) -> int:
        with self._lock:
            expired = [
                sid for sid, s in self._sessions.items()
                if s.is_expired(timeout_minutes)
            ]
            for sid in expired:
                del self._sessions[sid]
            return len(expired)

    def clear(self) -> None:
        """Vide le store (utile pour les tests)."""
        with self._lock:
            self._sessions.clear()
