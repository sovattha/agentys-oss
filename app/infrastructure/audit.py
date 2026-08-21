# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Module d'audit pour tracer les actions du système.

Fournit un log d'audit structuré pour:
- Création de brouillons
- Appels LLM
- Actions utilisateur
- Événements système
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from enum import Enum

from app.config import DATA_DIR
from app.infrastructure.text_io import read_text_legacy_safe

logger = logging.getLogger(__name__)

# Fichier d'audit
AUDIT_LOG_FILE = DATA_DIR / "audit.json"
AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


class AuditEventType(Enum):
    """Types d'événements d'audit."""
    DRAFT_CREATED = "draft_created"
    DRAFT_COMPLETED = "draft_completed"  # Complétion automatique d'un brouillon utilisateur
    DRAFT_FAILED = "draft_failed"
    EMAIL_PROCESSED = "email_processed"
    EMAIL_SKIPPED = "email_skipped"
    LLM_CALL = "llm_call"
    LLM_ERROR = "llm_error"
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    DAEMON_START = "daemon_start"
    DAEMON_STOP = "daemon_stop"
    LEARNING_ANALYSIS = "learning_analysis"
    FOLLOWUP_SENT = "followup_sent"
    CONFIG_CHANGE = "config_change"


@dataclass
class AuditEvent:
    """Événement d'audit."""
    timestamp: str
    event_type: str
    success: bool
    details: Dict[str, Any]
    user: Optional[str] = None
    email_id: Optional[str] = None
    draft_id: Optional[str] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'événement en dictionnaire."""
        return {k: v for k, v in asdict(self).items() if v is not None}


class AuditLogger:
    """
    Logger d'audit pour tracer les actions du système.

    Thread-safe et persiste les événements sur disque.
    """

    def __init__(self, filepath: Path = AUDIT_LOG_FILE, max_events: int = 10000):
        """
        Initialise le logger d'audit.

        Args:
            filepath: Chemin du fichier d'audit.
            max_events: Nombre maximum d'événements à conserver.
        """
        self.filepath = filepath
        self.max_events = max_events
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        """Charge les événements depuis le fichier."""
        if not self.filepath.exists():
            return
        try:
            raw, recovered = read_text_legacy_safe(self.filepath)
            data = json.loads(raw)
            self._events = data.get("events", [])
            logger.debug(f"📋 {len(self._events)} événements d'audit chargés")
        except Exception as e:
            # Vrai fichier corrompu : comportement historique conservé. Un
            # fichier simplement écrit en cp1252 par l'ancien code est récupéré
            # par read_text_legacy_safe et ne tombe PAS ici (audit 2026-05-14 F-01).
            logger.warning(f"Impossible de charger l'audit: {e}")
            self._events = []
            return
        if recovered:
            # Fichier hérité cp1252 — ré-enregistré en UTF-8 pour ne pas perdre
            # l'historique au prochain _save().
            logger.warning(
                f"Audit log was legacy cp1252, re-saving as UTF-8: {self.filepath}"
            )
            self._save()

    def _save(self) -> None:
        """Sauvegarde les événements sur disque."""
        try:
            # Garder seulement les derniers événements
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events:]

            data = {
                "last_updated": datetime.now().isoformat(),
                "event_count": len(self._events),
                "events": self._events,
            }
            self.filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Impossible de sauvegarder l'audit: {e}")

    def log(
        self,
        event_type: AuditEventType,
        success: bool = True,
        details: Optional[Dict[str, Any]] = None,
        user: Optional[str] = None,
        email_id: Optional[str] = None,
        draft_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
    ) -> AuditEvent:
        """
        Enregistre un événement d'audit.

        Args:
            event_type: Type d'événement.
            success: Si l'action a réussi.
            details: Détails supplémentaires.
            user: Utilisateur concerné.
            email_id: ID de l'email concerné.
            draft_id: ID du brouillon créé.
            duration_ms: Durée de l'opération en ms.
            error: Message d'erreur si échec.

        Returns:
            L'événement créé.
        """
        event = AuditEvent(
            timestamp=datetime.now().isoformat(),
            event_type=event_type.value,
            success=success,
            details=details or {},
            user=user,
            email_id=email_id,
            draft_id=draft_id,
            duration_ms=duration_ms,
            error=error,
        )

        with self._lock:
            self._events.append(event.to_dict())
            self._save()

        # Log aussi dans le logger standard
        log_msg = f"[AUDIT] {event_type.value}: "
        if email_id:
            log_msg += f"email={email_id[:8]}... "
        if draft_id:
            log_msg += f"draft={draft_id[:8]}... "
        if duration_ms:
            log_msg += f"({duration_ms}ms)"

        if success:
            logger.debug(log_msg)
        else:
            logger.warning(f"{log_msg} FAILED: {error}")

        return event

    def log_draft_created(
        self,
        email_id: str,
        draft_id: str,
        recipient: str,
        subject: str,
        duration_ms: int,
        status: str,
        priority_score: int = 50,
        category: str = "NORMAL",
    ) -> AuditEvent:
        """Raccourci pour logger la création d'un brouillon."""
        return self.log(
            event_type=AuditEventType.DRAFT_CREATED,
            success=True,
            email_id=email_id,
            draft_id=draft_id,
            duration_ms=duration_ms,
            details={
                "recipient": recipient,
                "subject": subject[:50],
                "status": status,
                "priority_score": priority_score,
                "category": category,
            },
        )

    def log_draft_failed(
        self,
        email_id: str,
        recipient: str,
        error: str,
        duration_ms: Optional[int] = None,
    ) -> AuditEvent:
        """Raccourci pour logger l'échec de création d'un brouillon."""
        return self.log(
            event_type=AuditEventType.DRAFT_FAILED,
            success=False,
            email_id=email_id,
            duration_ms=duration_ms,
            error=error,
            details={
                "recipient": recipient,
            },
        )

    def log_email_skipped(
        self,
        email_id: str,
        reason: str,
        category: Optional[str] = None,
    ) -> AuditEvent:
        """Raccourci pour logger un email ignoré."""
        return self.log(
            event_type=AuditEventType.EMAIL_SKIPPED,
            success=True,
            email_id=email_id,
            details={
                "reason": reason,
                "category": category,
            },
        )

    def get_events(
        self,
        event_type: Optional[AuditEventType] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Récupère les événements d'audit.

        Args:
            event_type: Filtrer par type.
            since: Filtrer depuis cette date.
            limit: Nombre maximum d'événements.

        Returns:
            Liste des événements.
        """
        with self._lock:
            events = self._events.copy()

        # Filtrer par type
        if event_type:
            events = [e for e in events if e.get("event_type") == event_type.value]

        # Filtrer par date
        if since:
            since_str = since.isoformat()
            events = [e for e in events if e.get("timestamp", "") >= since_str]

        # Limiter et retourner les plus récents
        return events[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques d'audit."""
        with self._lock:
            events = self._events.copy()

        # Compter par type
        by_type = {}
        success_count = 0
        failure_count = 0

        for event in events:
            event_type = event.get("event_type", "unknown")
            by_type[event_type] = by_type.get(event_type, 0) + 1

            if event.get("success"):
                success_count += 1
            else:
                failure_count += 1

        return {
            "total_events": len(events),
            "success_count": success_count,
            "failure_count": failure_count,
            "by_type": by_type,
            "first_event": events[0]["timestamp"] if events else None,
            "last_event": events[-1]["timestamp"] if events else None,
        }

    def clear(self) -> None:
        """Efface tous les événements."""
        with self._lock:
            self._events = []
            self._save()


# Instance globale
audit_logger = AuditLogger()


# Fonctions utilitaires
def log_draft_created(*args, **kwargs) -> AuditEvent:
    """Raccourci pour audit_logger.log_draft_created."""
    return audit_logger.log_draft_created(*args, **kwargs)


def log_draft_failed(*args, **kwargs) -> AuditEvent:
    """Raccourci pour audit_logger.log_draft_failed."""
    return audit_logger.log_draft_failed(*args, **kwargs)


def log_email_skipped(*args, **kwargs) -> AuditEvent:
    """Raccourci pour audit_logger.log_email_skipped."""
    return audit_logger.log_email_skipped(*args, **kwargs)


