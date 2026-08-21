# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Daemon automatique pour le traitement des emails.

Ce service tourne en continu et :
1. Surveille les nouveaux emails non lus
2. Génère automatiquement des brouillons de réponse via IA
3. Crée les brouillons dans la boîte mail de l'utilisateur

L'utilisateur retrouve ses brouillons "magiquement" prêts à envoyer.

Architecture:
    - EmailDaemon: Orchestrateur principal (polling, lifecycle)
    - ProcessedEmailsTracker: Persistance des emails traités
    - Use Cases: Logique métier déléguée au Container
"""

import logging
import os
import queue
import signal
import sys
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from queue import Empty
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from app.domain.entities.anonymization import AnonymizedResult

# =============================================================================
# IMPORTS - Configuration & Domain
# =============================================================================
from app.config import (
    DEFAULT_DAEMON_CONFIG,
    EMAIL_PROVIDER_TYPE,
    MAX_EMAIL_TOKENS,
    validate_config,
)
from app.domain.services.learning_service import LearningService
from app.domain.services.phishing_detector import PhishingDetector

# =============================================================================
# IMPORTS - Infrastructure (via injection ou singletons nécessaires)
# =============================================================================
from app.infrastructure.audit import AuditEventType, audit_logger
from app.infrastructure.circuit_breaker import CircuitOpenError
from app.infrastructure.container import get_container
from app.infrastructure.database import TaskRepository
from app.infrastructure.errors import format_error, wrap_exception
from app.infrastructure.notifications import get_notification_manager

# =============================================================================
# IMPORTS - Interfaces & Adapters
# =============================================================================
from app.interfaces.email_provider import EmailProvider, StandardEmail, InsufficientScopeError
from app.providers.factory import get_email_provider
from app.utils.email_cleaner import clean_email_content

# =============================================================================
# IMPORTS - Domain Ports (Clean Architecture)
# =============================================================================
from app.domain.ports import (
    ProcessedEmailsTrackerPort,
    ProcessedDraftsTrackerPort,
    DraftHistoryPort,
)
from app.application.commitment_tracking import CommitmentTrackingUseCase
from app.application.progress_notification_service import ProgressNotificationService

# =============================================================================
# IMPORTS - Legacy (facades pour backward compatibility)
# =============================================================================
from app.agents import (
    CommitmentExtractorAgent,
    CriticAgent,
    CryptographerAgent,
    DrafterAgent,
    PrioritizationAgent,
    SensitiveDataDetectorAgent,
    token_counter,
)
from app.draft_completion import DraftCompletionAgent
from app.draft_correction import DraftCorrectionManager, get_correction_manager

from app.message_router import (
    IncomingMessage,
    MessageChannel,
    MessageRouter,
    RoutingContext,
    get_message_router,
)
from app.routing import route_email, RoutingAction

# =============================================================================
# SINGLETONS & CONSTANTES
# =============================================================================

# Notification manager (singleton)
notify = get_notification_manager()

# ============================================================================
# CONFIGURATION DU DAEMON (depuis config centralisée)
# ============================================================================

# Utiliser la config centralisée
POLL_INTERVAL = DEFAULT_DAEMON_CONFIG.poll_interval
SKIP_LOW_PRIORITY = DEFAULT_DAEMON_CONFIG.skip_low_priority
LEARNING_ANALYSIS_INTERVAL = DEFAULT_DAEMON_CONFIG.learning_interval
MAX_EMAILS_PER_POLL = DEFAULT_DAEMON_CONFIG.max_emails_per_poll
CLEANUP_LOOP_INTERVAL = 50  # ~4h with 5min polling (newsletters, trash, spam, drafts)

# Logging (sera remplacé par setup_logging si utilisé)
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# Shared executor for parallel classify+prioritize — 4 workers handles up to
# 4 concurrent emails without thread-creation overhead per call.
_CLASSIFY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agentys-classify")


# ============================================================================
# RESULT TYPES (Clean Architecture - évite les tuples anonymes)
# ============================================================================


@dataclass(frozen=True)
class CleaningResult:
    """Résultat du nettoyage d'un email."""

    email: StandardEmail
    metadata: dict
    should_skip: bool
    skip_reason: Optional[str] = None


@dataclass(frozen=True)
class ClassificationResult:
    """Résultat de la classification et priorisation.

    `extracted_tasks` is populated when the unified analyzer path produces
    them in the same call (saves a downstream LLM call); empty when the
    legacy 2-call path is used (TaskExtractor runs separately later).
    """

    category: str
    priority_score: int
    should_skip: bool
    skip_reason: Optional[str] = None
    extracted_tasks: tuple = ()  # tuple[ExtractedTask, ...] — frozen-friendly


@dataclass(frozen=True)
class DraftGenerationResult:
    """Résultat de la génération du brouillon."""

    draft_v1: str
    critique: str
    final_draft: str
    status: str  # "V1" ou "V2"


@dataclass(frozen=True)
class DraftCreationContext:
    """
    Contexte pour la création d'un brouillon.

    Refactoring: Long Parameter List (Fowler)
    - Avant: 8 paramètres primitifs dans _create_and_save_draft
    - Après: 1 objet contexte regroupant les données liées
    """

    email: StandardEmail
    draft_v1: str
    critique: str
    final_draft: str
    status: str
    category: str
    priority_score: int
    processing_time_ms: int
    encrypted_token: Optional[str] = None


# ============================================================================
# API MODE - Types d'événements et émetteur
# ============================================================================


class DaemonEventType(Enum):
    """Types d'événements émis par le daemon en mode API."""

    EMAIL_RECEIVED = "email_received"
    PROCESSING_STARTED = "processing_started"
    DRAFT_READY = "draft_ready"
    PROCESSING_FAILED = "processing_failed"
    EMAIL_SKIPPED = "email_skipped"


@dataclass
class DaemonEvent:
    """
    Événement émis par le daemon en mode API.

    Permet à l'app Tauri de recevoir les notifications
    et d'afficher les brouillons pour validation.
    """

    event_type: DaemonEventType
    email_id: str
    timestamp: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(order=True)
class EmailQueueItem:
    """
    Item de la queue de traitement des emails.

    Ordonnancement:
    - Priorité haute (90+) traité en premier
    - À priorité égale, FIFO (premier arrivé, premier servi)

    La comparaison utilise un tuple inversé (-priority, added_at)
    pour que PriorityQueue traite d'abord les hautes priorités.
    """

    # Champs de tri (ordre important pour dataclass(order=True))
    sort_key: tuple = field(init=False, repr=False)
    # Données
    email: StandardEmail = field(compare=False)
    priority: int = field(default=50, compare=False)
    retry_count: int = field(default=0, compare=False)
    added_at: float = field(default_factory=time.time, compare=False)

    def __post_init__(self):
        self.sort_key = (-self.priority, self.added_at)


class EmailQueue:
    """
    Queue thread-safe pour le traitement des emails avec priorité.

    Caractéristiques:
    - Priorité: emails urgents/VIP traités en premier
    - Thread-safe: supporte producteurs/consommateurs concurrents
    - Retry: emails échoués remis en queue avec backoff
    - Stats: métriques de la queue disponibles
    """

    def __init__(self, max_size: int = 100, max_retries: int = 3):
        self.max_size = max_size
        self.max_retries = max_retries
        self._queue: queue.PriorityQueue[EmailQueueItem] = queue.PriorityQueue(
            maxsize=max_size
        )
        self._lock = threading.Lock()

    def enqueue(
        self,
        email: StandardEmail,
        priority: int = 50,
        timeout: Optional[float] = None,
    ) -> None:
        """Ajoute un email à la queue avec une priorité."""
        item = EmailQueueItem(email=email, priority=priority)
        try:
            self._queue.put(item, block=True, timeout=timeout)
        except queue.Full as e:
            raise Exception(f"Queue pleine (max={self.max_size})") from e

    def dequeue(self, timeout: Optional[float] = None) -> EmailQueueItem:
        """Retire et retourne l'email avec la plus haute priorité."""
        try:
            return self._queue.get(block=True, timeout=timeout)
        except queue.Empty:
            raise Empty("Queue vide")

    def requeue(self, item: EmailQueueItem) -> bool:
        """Remet un email dans la queue après échec (avec priorité réduite)."""
        item.retry_count += 1
        if item.retry_count > self.max_retries:
            return False

        # Réduire la priorité de 10 par retry pour éviter starvation
        new_priority = max(0, item.priority - 10)
        item.priority = new_priority
        item.sort_key = (-new_priority, item.added_at)

        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            return False

    def peek(self) -> Optional[EmailQueueItem]:
        """Retourne le prochain item sans le retirer (non thread-safe pour usage interne)."""
        with self._lock:
            if self._queue.empty():
                return None
            # On doit sortir puis remettre - pas idéal mais PriorityQueue n'a pas de peek
            try:
                item = self._queue.get_nowait()
                self._queue.put_nowait(item)
                return item
            except (queue.Empty, queue.Full):
                return None

    def clear(self) -> None:
        """Vide la queue."""
        with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

    def is_empty(self) -> bool:
        return self._queue.empty()

    def __len__(self) -> int:
        return self._queue.qsize()

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de la queue."""
        size = self._queue.qsize()
        return {
            "size": size,
            "max_size": self.max_size,
            "utilization": round(size / self.max_size, 2) if self.max_size > 0 else 0,
        }


class EventEmitter(ABC):
    """Interface pour l'émission d'événements."""

    @abstractmethod
    def emit(self, event: DaemonEvent) -> None:
        """Émet un événement."""
        pass


class InMemoryEventEmitter(EventEmitter):
    """
    Émetteur d'événements en mémoire (pour tests et usage simple).

    Peut appeler un callback optionnel lors de l'émission.
    """

    def __init__(self, callback: Optional[Callable[[DaemonEvent], None]] = None):
        self.events: List[DaemonEvent] = []
        self._callback = callback

    def emit(self, event: DaemonEvent) -> None:
        self.events.append(event)
        if self._callback:
            self._callback(event)


# ============================================================================
# DAEMON PRINCIPAL
# ============================================================================


@dataclass
class EmailDaemon:
    """
    Daemon automatique de traitement des emails.

    Surveille la boîte mail et génère des brouillons de réponse
    automatiquement pour chaque nouvel email.

    Clean Architecture:
    - Utilise les ports du Container pour les dépendances
    - Les agents restent en façade pour la génération LLM
    - Les trackers utilisent les ports injectés
    """

    provider: EmailProvider = field(default=None)
    drafter: DrafterAgent = field(default=None)
    # Legacy DI slots — the auto-draft / per-email analysis pipeline that
    # consumed `critic` / `prioritizer` / `classifier` / `task_extractor` was
    # removed (2026-05-15). Kept as constructor slots so existing test fixtures
    # wiring them still build EmailDaemon; they are NOT auto-instantiated and
    # never read at runtime. Safe to drop once those fixtures stop wiring them.
    critic: CriticAgent = field(default=None)
    prioritizer: PrioritizationAgent = field(default=None)
    classifier: Optional[Any] = field(default=None)
    task_extractor: Optional[Any] = field(default=None)
    tracker: ProcessedEmailsTrackerPort = field(default=None)  # Via Container (Clean Architecture)
    processed_drafts_tracker: ProcessedDraftsTrackerPort = field(default=None)  # Via Container (Clean Architecture)
    learning_manager: LearningService = field(default=None)  # Via Container (Clean Architecture)
    draft_history: DraftHistoryPort = field(default=None)  # Via Container (Clean Architecture)
    message_router: MessageRouter = field(default=None)  # Router multi-canal
    draft_completion_agent: DraftCompletionAgent = field(default=None)  # Pour compléter les brouillons utilisateur
    task_repository: TaskRepository = field(default=None)  # Persistance des tâches extraites
    phishing_detector: PhishingDetector = field(default=None)  # Détection de phishing
    commitment_extractor: CommitmentExtractorAgent = field(default=None)  # Extracteur d'engagements
    commitment_use_case: CommitmentTrackingUseCase = field(default=None)  # Suivi des engagements (Clean Architecture)
    sensitive_data_detector: SensitiveDataDetectorAgent = field(default=None)  # Détection de données sensibles
    cryptographer: "CryptographerAgent" = field(default=None)  # Anonymisation des données sensibles
    correction_manager: DraftCorrectionManager = field(default=None)  # Apprentissage des corrections utilisateur
    progress_notifier: ProgressNotificationService = field(default=None)  # Notifications de progression
    poll_interval: int = POLL_INTERVAL
    skip_low_priority: bool = field(default=False)  # Skip newsletters, promos, etc.
    use_smart_routing: bool = field(default=True)  # Utiliser le router intelligent
    # account_id (hash string from AccountManager) of the account this daemon
    # serves. Set by the orchestrator that spawns one daemon per active
    # account. When None we fall back to AccountManager.get_current_account()
    # — that's a process singleton and on a multi-user deploy returns
    # whoever activated last, so all callers should aim to set this
    # explicitly (cf. 2026-04-25 isolation audit C-4).
    account_id: Optional[str] = field(default=None)
    _running: bool = field(default=False, repr=False)
    _emails_processed_count: int = field(default=0, repr=False)  # Pour trigger learning
    # Audit P1-1 (mother-of-all 2026-04-25): structure étendue pour permettre
    # l'éviction TTL. Avant : `dict[str, int]` (email_id → nb d'échecs) qui
    # accumulait sans jamais être nettoyé. Après : `dict[str, tuple[int, float]]`
    # (email_id → (nb_failures, last_attempt_unix_ts)) — l'éviction lit le ts
    # pour drop les entrées >7j (cf. _evict_failed_draft_counts ci-dessous).
    # Le code est currently dead (return en haut de _requeue_*), mais on
    # défense-in-depth pour le jour où l'auto-draft sera réactivé.
    _failed_draft_counts: dict = field(default_factory=dict, repr=False)  # email_id → (count, last_attempt_ts)
    _stop_event: threading.Event = field(default=None, repr=False)  # Pour arrêt interruptible
    # Mode API: émet des événements au lieu de créer les brouillons directement
    api_mode: bool = field(default=False)
    event_emitter: Optional["EventEmitter"] = field(default=None)
    # Queue de traitement pour gestion propre des emails en attente
    email_queue: Optional["EmailQueue"] = field(default=None)

    def __post_init__(self):
        # Récupérer le Container pour l'injection de dépendances
        container = get_container()

        # Initialiser l'événement d'arrêt (pour sleep interruptible)
        if self._stop_event is None:
            self._stop_event = threading.Event()

        # Initialiser le provider si non fourni
        if self.provider is None:
            self.provider = get_email_provider()

        # Initialiser le drafter (façade LLM encore utilisée par le healthcheck
        # de démarrage). critic / prioritizer / unified_analyzer ne sont plus
        # consommés par le daemon — voir les « Legacy DI slots » plus haut.
        if self.drafter is None:
            self.drafter = DrafterAgent()

        # Initialiser le tracker via Container (Clean Architecture)
        if self.tracker is None:
            self.tracker = container.get_processed_emails_tracker()

        # Initialiser le tracker de brouillons via Container (Clean Architecture)
        if self.processed_drafts_tracker is None:
            self.processed_drafts_tracker = container.get_processed_drafts_tracker()

        # Initialiser l'agent de complétion de brouillons
        if self.draft_completion_agent is None:
            self.draft_completion_agent = DraftCompletionAgent()

        # Initialiser le repository des tâches extraites
        if self.task_repository is None:
            self.task_repository = TaskRepository()

        # Initialiser le learning service via Container (Clean Architecture)
        if self.learning_manager is None:
            self.learning_manager = container.get_learning_service()

        # Initialiser l'historique des brouillons via Container (Clean Architecture)
        if self.draft_history is None:
            self.draft_history = container.get_draft_history()

        # Initialiser le message router
        if self.message_router is None:
            self.message_router = get_message_router()

        # Initialiser le détecteur de phishing
        if self.phishing_detector is None:
            self.phishing_detector = PhishingDetector()

        # Initialiser l'extracteur d'engagements
        if self.commitment_extractor is None:
            self.commitment_extractor = CommitmentExtractorAgent()

        # Initialiser le use case d'engagements via Container (Clean Architecture)
        if self.commitment_use_case is None:
            tracker = container.get_commitment_tracker()
            self.commitment_use_case = CommitmentTrackingUseCase(tracker=tracker)

        # Initialiser le détecteur de données sensibles
        if self.sensitive_data_detector is None:
            self.sensitive_data_detector = SensitiveDataDetectorAgent()

        # Initialiser le gestionnaire de corrections utilisateur (Singleton)
        if self.correction_manager is None:
            self.correction_manager = get_correction_manager()

        # Initialiser l'agent cryptographe pour l'anonymisation
        if self.cryptographer is None:
            self.cryptographer = CryptographerAgent()

        # Initialiser le service de notifications de progression
        if self.progress_notifier is None:
            self.progress_notifier = ProgressNotificationService(
                learning_service=self.learning_manager,
            )

        # Set pour tracker les expéditeurs ayant déjà reçu une réponse automatique
        self._auto_replied_senders: set = set()

    def _email_to_incoming_message(self, email: StandardEmail) -> IncomingMessage:
        """
        Convertit un StandardEmail en IncomingMessage pour le router.

        Args:
            email: L'email standard à convertir.

        Returns:
            IncomingMessage prêt pour le routage.
        """
        return IncomingMessage(
            channel=MessageChannel.EMAIL,
            content=email.body,
            sender_id=email.sender,
            sender_name=email.sender_name,
            conversation_id=email.conversation_id,
            subject=email.subject,
            cc=email.cc if email.cc else [],
            metadata={
                "email_id": email.id,
                "has_attachments": email.has_attachments,
                "provider": email.provider_source,
            }
        )

    def get_routing_info(self, email: StandardEmail) -> RoutingContext:
        """
        Obtient les informations de routage pour un email.

        Args:
            email: L'email à analyser.

        Returns:
            RoutingContext avec la décision de routage.
        """
        message = self._email_to_incoming_message(email)
        return self.message_router.route(message)

    def health_check(self) -> dict:
        """
        Vérifie la santé des composants critiques au démarrage.

        Returns:
            dict avec état de chaque composant:
            - email_provider: bool
            - llm: bool
            - overall: bool
        """
        results = {
            "email_provider": False,
            "llm": False,
            "overall": False,
        }

        # Test 1: Email Provider
        try:
            logger.info("Vérification email provider...")
            if self.provider.authenticate():
                results["email_provider"] = True
                logger.info("  [OK] Email provider OK")
            else:
                logger.error("  [ERROR] Email provider: échec authentification")
        except Exception as e:
            logger.error(f"  [ERROR] Email provider: {e}")

        # Test 2: LLM (appel minimal)
        try:
            logger.info("Vérification LLM...")
            # Test avec un prompt minimal
            test_response = self.drafter.draft("Test: Répondre OK si fonctionnel.")
            if test_response and len(test_response) > 0:
                results["llm"] = True
                logger.info("  [OK] LLM OK")
            else:
                logger.error("  [ERROR] LLM: réponse vide")
        except Exception as e:
            logger.error(f"  [ERROR] LLM: {e}")

        # Résultat global
        results["overall"] = results["email_provider"] and results["llm"]

        if results["overall"]:
            logger.info("[OK] Health check: tous les composants OK")
        else:
            logger.warning("[WARN] Health check: certains composants en échec")

        return results

    def _format_email_for_agent(self, email: StandardEmail) -> str:
        """Formate un email pour le passer aux agents."""
        parts = []

        if email.sender_name:
            parts.append(f"De: {email.sender_name} <{email.sender}>")
        else:
            parts.append(f"De: {email.sender}")

        parts.append(f"Sujet: {email.subject or ''}")
        parts.append("")
        parts.append(email.body or "")

        return "\n".join(parts)

    def _generate_reply_subject(self, original_subject: str) -> str:
        """Génère le sujet de la réponse."""
        if not original_subject:
            return "Re: (sans sujet)"
        if original_subject.lower().startswith("re:"):
            return original_subject
        return f"Re: {original_subject}"

    def _clean_and_validate_email(self, email: StandardEmail) -> CleaningResult:
        """
        Nettoie et valide un email avant traitement.

        Args:
            email: L'email brut à nettoyer.

        Returns:
            CleaningResult avec l'email nettoyé ou une indication de skip.
        """
        cleaned_body, clean_meta = clean_email_content(
            body=email.body,
            subject=email.subject,
            max_tokens=MAX_EMAIL_TOKENS,
        )

        # Skip les emails envoyés par l'utilisateur lui-même (déjà répondu)
        try:
            from app.db.database import get_db_session
            from app.db.repositories import AccountRepository
            with get_db_session() as _sess:
                _accts = AccountRepository(_sess).get_active_accounts()
                if _accts:
                    _own_email = (_accts[0].email or "").lower().strip()
                    _sender = (email.sender or "").lower().strip()
                    if _own_email and _sender == _own_email:
                        logger.info("  [SKIP] Ignoré (email envoyé par l'utilisateur)")
                        audit_logger.log_email_skipped(email.id, "self-sent")
                        return CleaningResult(
                            email=email,
                            metadata=clean_meta,
                            should_skip=True,
                            skip_reason="self-sent",
                        )
        except Exception:
            logger.debug("Failed to detect self-sent email", exc_info=True)

        # Skip les expéditeurs bloqués. self.account_id wins over the
        # process-global current account so the blocklist applied is the
        # one of THIS daemon's account, not whoever activated last on
        # the API (cf. C-4).
        try:
            from app.multi_accounts import get_account_manager
            _mgr = get_account_manager()
            _current = (
                _mgr.accounts.get(self.account_id)
                if self.account_id
                else _mgr.get_current_account()
            )
            if _current and not _mgr.is_sender_allowed(_current.id, email.sender or ""):
                logger.info("  [SKIP] Ignoré (expéditeur bloqué)")
                audit_logger.log_email_skipped(email.id, "blocked_sender")
                return CleaningResult(
                    email=email,
                    metadata=clean_meta,
                    should_skip=True,
                    skip_reason="blocked_sender",
                )
        except Exception:
            # B-06 (audit 2026-06-11): a broken blocklist store silently
            # disables the filter for every email — must be visible in prod.
            logger.warning("Failed to check blocked sender", exc_info=True)

        # Skip les expéditeurs/domaines appris comme spam (auto-move vers spam).
        # Same scoping rule as the blocked-sender path above (cf. C-4).
        try:
            from app.multi_accounts import get_account_manager as _get_mgr, AccountManager
            _spam_mgr = _get_mgr()
            _spam_current = (
                _spam_mgr.accounts.get(self.account_id)
                if self.account_id
                else _spam_mgr.get_current_account()
            )
            if _spam_current:
                _sender_email = AccountManager._extract_email(email.sender or "")
                _is_spam = False
                # Check sender list
                if _spam_current.spammed_senders and _sender_email in {s.lower() for s in _spam_current.spammed_senders}:
                    _is_spam = True
                # Check domain list
                if not _is_spam and _spam_current.spammed_domains and "@" in _sender_email:
                    _sender_domain = _sender_email.split("@")[1].lower()
                    if _sender_domain in {d.lower() for d in _spam_current.spammed_domains}:
                        _is_spam = True
                if _is_spam:
                    logger.info("  [SKIP] Ignoré (expéditeur/domaine appris comme spam)")
                    audit_logger.log_email_skipped(email.id, "spammed_sender")
                    # Auto-déplacer vers le dossier spam
                    try:
                        if hasattr(self.provider, "move_to_spam"):
                            self.provider.move_to_spam(email.id)
                            logger.info(f"  [AUTO-SPAM] Email déplacé vers spam : {email.id[:20]}...")
                    except Exception:
                        # B-06 (audit 2026-06-11): the email stays in the inbox
                        # despite the learned-spam verdict — warn, don't whisper.
                        logger.warning("Failed to auto-move to spam", exc_info=True)
                    return CleaningResult(
                        email=email,
                        metadata=clean_meta,
                        should_skip=True,
                        skip_reason="spammed_sender",
                    )
        except Exception:
            logger.debug("Failed to check spammed sender", exc_info=True)

        # Skip les auto-replies
        if clean_meta["is_auto_reply"]:
            logger.info("  [SKIP] Ignoré (auto-reply détecté)")
            audit_logger.log_email_skipped(email.id, "auto-reply")
            return CleaningResult(
                email=email,
                metadata=clean_meta,
                should_skip=True,
                skip_reason="auto-reply",
            )

        if clean_meta["was_truncated"]:
            logger.debug(
                f"  [TRIM] Email tronqué"
                f"({clean_meta['original_length']} → {clean_meta['cleaned_length']} chars)"
            )

        # Créer une copie avec le body nettoyé
        cleaned_email = StandardEmail(
            id=email.id,
            sender=email.sender,
            sender_name=email.sender_name,
            to=email.to,
            cc=email.cc,
            subject=email.subject,
            body=cleaned_body,
            body_html=email.body_html,
            received_at=email.received_at,
            is_read=email.is_read,
            has_attachments=email.has_attachments,
            conversation_id=email.conversation_id,
            provider_source=email.provider_source,
            raw_metadata=email.raw_metadata,
        )

        return CleaningResult(
            email=cleaned_email,
            metadata=clean_meta,
            should_skip=False,
        )

    def _detect_phishing(self, email: StandardEmail) -> bool:
        """
        Détecte si un email est du phishing.

        Args:
            email: L'email à analyser.

        Returns:
            True si l'email est du phishing (doit être skippé), False sinon.
        """
        result = self.phishing_detector.analyze_email(
            subject=email.subject,
            body=email.body
        )

        if result.is_phishing:
            logger.warning(f"  [WARN] PHISHING DÉTECTÉ (score: {result.risk_score})")
            logger.warning(f"      {result.analysis_summary}")
            self.provider.apply_label(email.id, "PHISHING")
            try:
                if self.provider.move_to_spam(email.id):
                    logger.info("  [EMAIL] Email déplacé vers spam")
                else:
                    logger.warning("  [WARN] Échec déplacement spam (provider ne supporte pas)")
            except Exception as e:
                logger.warning(f"  [WARN] Erreur déplacement spam: {e}")
            audit_logger.log_email_skipped(email.id, "phishing", "PHISHING")
            return True

        if result.risk_score > 0:
            logger.debug(f"  Analyse phishing: score={result.risk_score} (OK)")

        return False

    def _anonymize_sensitive_data(
        self, draft_content: str, recipient: str
    ) -> Optional["AnonymizedResult"]:
        """
        Anonymise les données sensibles dans le brouillon.

        Args:
            draft_content: Le contenu du brouillon à analyser.
            recipient: L'adresse email du destinataire.

        Returns:
            AnonymizedResult si anonymisation effectuée, None sinon.
        """
        result = self.cryptographer.anonymize(draft_content, recipient)

        if result.has_redactions:
            logger.warning(
                f"  [WARN] DONNÉES SENSIBLES ANONYMISÉES ({result.items_anonymized} éléments)"
            )
            return result

        logger.debug("  [OK] Pas de données sensibles détectées")
        return None


    def _check_vip_and_notify(self, email: StandardEmail) -> None:
        """Vérifie si l'expéditeur est VIP et envoie une notification."""
        routing_result = route_email(
            sender=email.sender,
            subject=email.subject,
            body=email.body or "",
        )
        if routing_result.action == RoutingAction.VIP_NOTIFY:
            vip_name = routing_result.rule.name if routing_result.rule else None
            notify.vip_email_received(
                sender=email.sender,
                subject=email.subject,
                vip_name=vip_name,
                email_id=email.id,
            )
            logger.info(f"  VIP détecté: {email.sender}")

    def _auto_label_email(self, email: StandardEmail) -> None:
        """
        Assigne automatiquement des labels à un email.

        Utilise LabelEmailUseCase pour classifier l'email en:
        - Action, Waiting, FYI, Noise, ou labels personnalisés

        When SMART_ROUTING_ENABLED, uses combined Haiku call for STANDARD-eligible
        emails to classify AND draft in one LLM call, saving 1 API call.

        After classification, applies all existing user rules (VIP, custom labels)
        so custom labels are always applied to new emails.

        Args:
            email: L'email à labelliser.
        """
        try:
            container = get_container()
            label_store = container.get_label_store(account_id=getattr(getattr(self, 'account', None), 'id', None))

            # Vérifier si déjà assigné
            existing = label_store.get_assignment(email.id)
            if existing:
                logger.debug(f"  Labels existants: {existing.labels}")
                return

            # Phishing pre-check — runs BEFORE any LLM call. Pure rule-based,
            # zero LLM cost, but mandatory: a phishing email shouldn't be
            # classified as Action/FYI/Normal. Detected emails get the
            # PHISHING label and move to spam, then the function returns
            # early so the LLM-based label use case is never invoked.
            #
            # Audit context (2026-05-05): pre-fix this check lived in
            # `process_email` step 3, which was unreachable when auto-draft
            # was off (the default). Lifting it here means phishing
            # detection runs on every newly-arriving email, every time,
            # regardless of any draft toggle.
            try:
                if self._detect_phishing(email):
                    return  # phishing handled by _detect_phishing (label + spam move)
            except Exception:
                # Phishing detector is rule-based but malformed input
                # (None subject, etc.) shouldn't break labeling.
                logger.exception("[WARN] Phishing pre-check raised — falling through to LLM labeling")

            # L4 (2026-05-05) — tiny-email bypass.
            # An email body of <50 chars is almost always an acknowledgment
            # ("OK", "Merci", "À demain", "Bien reçu") that doesn't warrant
            # an LLM call to classify+draft. We assign the NORMAL label
            # heuristically and skip the LLM. The user can still trigger a
            # draft on-demand via SmartRouter.route() if they want one.
            #
            # Net effect: ~15% of inbound (typical ack volume) skips the
            # ~$0.003 classify_and_draft call → ~$0.045/user/month savings.
            # Subject-only emails (no body) are also caught here.
            try:
                _body_for_size = (email.body or "").strip()
                if len(_body_for_size) < 50:
                    from app.domain.entities.email_labels import LabelAssignment
                    _tiny_assignment = LabelAssignment(
                        email_id=email.id,
                        labels=["FYI"],
                        confidences={"FYI": 0.85},
                        assigned_by="tiny_email_bypass",
                    )
                    label_store.save_assignment(_tiny_assignment)
                    logger.info(
                        "  [TINY_BYPASS] Email body <50 chars → FYI label "
                        "(skipped classify_and_draft, saved ~$0.003)"
                    )
                    return
            except Exception:
                logger.exception("[WARN] Tiny-email bypass raised — falling through to LLM labeling")

            # Resolve user email early — needed for FAQ agent + CC detection
            _user_email = ""
            try:
                from app.db.database import get_db_session
                from app.db.repositories import AccountRepository
                with get_db_session() as _sess:
                    _accts = AccountRepository(_sess).get_active_accounts()
                    if _accts:
                        _user_email = _accts[0].email or ""
            except Exception:
                logger.exception("[WARN] Failed to resolve user email for label assignment")

            # Fallback: standard LabelEmailUseCase
            from app.domain.entities import Email as DomainEmail

            domain_email = DomainEmail(
                id=email.id,
                sender=email.sender,
                subject=email.subject,
                body=email.body or "",
                recipients=getattr(email, 'to', []) or [],
                cc=getattr(email, 'cc', []) or [],
                received_at=email.received_at,
            )

            label_use_case = container.get_label_email_use_case(
                user_email=_user_email,
                account_id=getattr(getattr(self, 'account', None), 'id', None),
            )

            # Compute contact-floor flag: if user has emailed this sender before,
            # never auto-classify as Noise (see routes_helpers.sender_is_real_contact).
            _raw_meta = getattr(email, 'raw_metadata', None) or {}
            if not isinstance(_raw_meta, dict):
                _raw_meta = {}
            # Hydrate classification_headers from the persisted raw_headers
            # JSON column when the email already lives in the DB. Without this
            # the labelizer's RFC noise rules (List-Unsubscribe → Noise @ 0.95)
            # never fire on stored emails.
            if "classification_headers" not in _raw_meta:
                _stored_headers = getattr(email, 'raw_headers', None)
                if _stored_headers:
                    try:
                        import json as _json_dmn
                        _parsed_headers = _json_dmn.loads(_stored_headers)
                        if isinstance(_parsed_headers, dict) and _parsed_headers:
                            _raw_meta = {**_raw_meta, "classification_headers": _parsed_headers}
                    except (ValueError, TypeError):
                        pass
            try:
                from app.api.routes_helpers import sender_is_real_contact
                _raw_meta = {
                    **_raw_meta,
                    "sender_is_real_contact": sender_is_real_contact(
                        getattr(email, 'account_id', None), email.sender
                    ),
                }
            except Exception:
                pass

            assignment = label_use_case.execute(domain_email, raw_metadata=_raw_meta)

            label_store.save_assignment(assignment)
            logger.info(f"  [LABEL] Labels assignés: {assignment.labels}")

            # Record sender reputation for future classification
            if assignment.default_label:
                try:
                    from app.infrastructure.sender_reputation_store import get_reputation_store
                    get_reputation_store().record_classification(
                        sender=email.sender,
                        label=assignment.default_label,
                        source="auto",
                    )
                except Exception:
                    pass

            # Apply custom rules (VIP, etc.) after standard classification
            self._apply_custom_rules_to_email(email, label_store)

        except Exception as e:
            logger.warning(f"  [WARN] Erreur auto-labeling: {e}")

    def _apply_custom_rules_to_email(self, email: StandardEmail, label_store) -> None:
        """Apply all existing user rules (VIP, custom labels) to a newly classified email."""
        try:
            from app.domain.entities.email_labels import DEFAULT_LABEL_NAMES

            assignment = label_store.get_assignment(email.id)
            if not assignment:
                return

            all_rules = label_store.get_rules()
            email_data = {
                "sender": (email.sender or "").lower(),
                "subject": (email.subject or "").lower(),
                "body": (email.body or "").lower()[:2000],
                "recipients": [],
                "is_cc": False,
            }

            changed = False
            for rule in all_rules:
                if rule.label_name not in assignment.labels and rule.matches(email_data):
                    if rule.label_name in DEFAULT_LABEL_NAMES:
                        # Don't override the default label already set by LLM/combined
                        pass
                    else:
                        assignment.add_custom_label(
                            rule.label_name, rule.confidence,
                            f"Rule: {rule.condition_type} = '{rule.condition_value}'")
                        changed = True

            if changed:
                assignment._rebuild_labels()
                label_store.save_assignment(assignment)
                custom_added = [lbl for lbl in assignment.labels if lbl not in DEFAULT_LABEL_NAMES]
                logger.info(f"  [LABEL] Custom labels ajoutés par règles: {custom_added}")

        except Exception as e:
            logger.warning(f"  [WARN] Erreur application règles custom: {e}")

    def _has_action_label(self, email: StandardEmail) -> bool:
        """Vérifie si l'email a le label Action (seul label déclenchant un draft auto)."""
        try:
            container = get_container()
            label_store = container.get_label_store(account_id=getattr(getattr(self, 'account', None), 'id', None))
            assignment = label_store.get_assignment(email.id)
            if assignment and "Action" in assignment.labels:
                return True
        except Exception as e:
            logger.warning(f"  [WARN] Erreur vérification label Action: {e}")
        return False

    def _has_noise_or_fyi_label(self, email: StandardEmail) -> bool:
        """Vérifie si l'email a le label Noise ou FYI (pas de draft pour ces labels)."""
        try:
            container = get_container()
            label_store = container.get_label_store(account_id=getattr(getattr(self, 'account', None), 'id', None))
            assignment = label_store.get_assignment(email.id)
            if assignment:
                labels = set(assignment.labels)
                if "Noise" in labels or "FYI" in labels:
                    return True
        except Exception as e:
            logger.warning(f"  [WARN] Erreur vérification label Noise/FYI: {e}")
        return False

    # Patterns de senders automatiques — O(1) lookup, partagés avec routes.py
    _NOREPLY_PATTERNS: frozenset = frozenset([
        "noreply@", "no-reply@", "no_reply@", "no.reply@",
        "donotreply@", "do-not-reply@", "nepasrepondre@",
        "mailer-daemon@", "postmaster@", "bounce@", "bounces@",
        "notifications@", "notification@", "notification-",
        "newsletter@", "newsletters@",
        "updates@", "update@", "digest@", "news@", "announce@",
        "marketing@", "promo@", "promotions@", "campaigns@",
        "billing@", "receipts@", "receipt@", "invoice@", "invoice+",
        "alert@", "alerts@", "automated@", "auto@", "auto-reply@",
        "calendar-notification@", "calendar-server@",
        "feedback@", "survey@", "monitoring@",
        "feeds@", "feed@", "subscriptions@", "onboarding@",
        "hello@notify.", "info@notify.",
        "bot@", "system@",
    ])

    _NOISE_DOMAINS: frozenset = frozenset([
        "substack.com", "mail.instagram.com", "mail.facebook.com",
        "facebookmail.com", "e.linkedin.com", "linkedin.com",
        "email.twitter.com", "postmaster.twitter.com",
        "accounts.google.com", "googleusercontent.com",
        "youtube.com", "tiktok.com", "pinterest.com",
        "medium.com", "ghost.io", "mailchimp.com",
        "sendgrid.net", "amazonses.com", "mandrillapp.com",
        "mailgun.org", "sparkpostmail.com",
        "shopify.com", "squarespace.com",
        # Services dev/infra
        "md.getsentry.com", "notify.railway.app", "resend.dev",
        "email.claude.com", "amazonaws.com",
        # Services financiers/notifications
        "stripe.com", "revolut.com",
        # Services divers
        "github.com", "gitlab.com", "bitbucket.org",
        "slack.com", "trello.com", "asana.com", "notion.so",
        "chess.com",
        # Crypto
        "bitcoin.com", "binance.com", "coinbase.com", "kraken.com",
        "crypto.com", "bybit.com", "okx.com",
        # E-commerce
        "amazon.com", "amazon.ca", "amazon.fr",
        # Wellness / AI community
        "apolloneuro.com",
        "cerebralvalley.ai", "cerebralvalley.com", "thecerebralvalley.com",
    ])

    def _is_notification_sender(self, email: StandardEmail) -> bool:
        """Détecte les senders de notification automatique par pattern matching."""
        sender = (email.sender or "").lower().strip()
        if not sender:
            return False
        # Check noreply-style prefixes
        if any(sender.startswith(p) for p in self._NOREPLY_PATTERNS):
            return True
        # Check known noise domains (exact match + subdomain suffix matching)
        if "@" in sender:
            domain = sender.split("@", 1)[1]
            if domain in self._NOISE_DOMAINS:
                return True
            # Suffix match: news.bitcoin.com → endswith .bitcoin.com
            for nd in self._NOISE_DOMAINS:
                if domain.endswith("." + nd):
                    return True
        return False

    def _force_noise_label(self, email: StandardEmail) -> None:
        """Force le label Noise sur un email (bypass LLM)."""
        try:
            container = get_container()
            label_store = container.get_label_store(account_id=getattr(getattr(self, 'account', None), 'id', None))
            existing = label_store.get_assignment(email.id)
            if existing:
                return  # Déjà labellisé
            from app.domain.entities.email_labels import LabelAssignment
            assignment = LabelAssignment(
                email_id=email.id,
                labels=["Noise"],
                confidences={"Noise": 1.0},
                assigned_by="pattern_detector",
            )
            label_store.save_assignment(assignment)
            logger.info(f"  [LABEL] Force Noise: {email.sender}")
        except Exception as e:
            logger.warning(f"  [WARN] Erreur force Noise label: {e}")


    @staticmethod
    def _get_reply_subject(subject: str) -> str:
        """Ajoute le préfixe Re: au sujet si nécessaire."""
        if not subject:
            return "Re: (sans sujet)"
        if subject.lower().startswith("re:"):
            return subject
        return f"Re: {subject}"

    def _handle_auto_reply(self, email: StandardEmail, is_auto_reply: bool) -> bool:
        """
        Envoie une réponse automatique d'absence si activé et dans la période.

        Délègue à ``app.services.auto_reply`` pour partager la logique avec
        le path Gmail OAuth (``sync_service._store_emails``) — sans cette
        extraction, GH#622 : aucun auto-reply pour les comptes OAuth.
        """
        from app.services.auto_reply import send_auto_reply_if_needed

        account_obj = getattr(self, "account", None)
        account_id = getattr(account_obj, "id", None)
        account_email = getattr(account_obj, "email", None)

        # F-06: pass every connected account's address so the auto-reply
        # skips cross-account loops (Gmail → Hotmail → Gmail when both are
        # in Agentys with OOO on). sync_service._store_emails already does
        # this; the daemon path was missed and still looped. Falls back to
        # the single account_email if the lookup fails.
        own_emails = None
        try:
            from app.db.database import get_db_session
            from app.db.repositories import AccountRepository
            with get_db_session() as _sess:
                _accts = AccountRepository(_sess).get_active_accounts()
                own_emails = {a.email for a in _accts if a.email}
        except Exception as _own_err:
            logger.debug(f"own_account_emails lookup failed: {_own_err}")
            own_emails = {account_email} if account_email else None

        sent = send_auto_reply_if_needed(
            provider=self.provider,
            account_id=account_id,
            email=email,
            is_auto_reply=is_auto_reply,
            account_email=account_email,
            own_account_emails=own_emails,
        )
        if sent:
            # Keep the legacy in-memory set in sync so tests that inspect
            # ``daemon._auto_replied_senders`` still observe the dedupe.
            sender = (email.sender or "").lower().strip()
            if sender:
                self._auto_replied_senders.add(sender)
        return sent


    def process_email(self, email: StandardEmail) -> bool:
        """Traite un email entrant : nettoyage + auto-label (qui inclut phishing).

        Pipeline (post-2026-05-05 — auto-draft retiré) :
            1. Nettoyer + valider (skip si auto-reply / spam évident)
            2. Réponse automatique d'absence si applicable
            3. VIP check (notification éventuelle)
            4. Filet déterministe pour les notifications auto (force Noise)
            5. Auto-label — qui exécute en interne :
                 - phishing pre-check (rule-based, fail-closed sur erreur)
                 - puis LabelEmailUseCase (Haiku via classify_and_draft)
                 - et applique les règles VIP / labels personnalisés

        Auto-draft a été supprimé du pipeline de polling (2026-05-05). Les
        brouillons sont désormais produits exclusivement :
          - de manière opportuniste pendant l'auto-label via
            `SmartRouter.classify_and_draft` (1 appel Haiku combiné)
          - sur demande de l'utilisateur via les routes REST/WS
            (`SmartRouter.route` / `route_streaming`)

        Args:
            email: L'email à traiter (provider-native shape).

        Returns:
            True si le traitement a abouti (ou a été skippé proprement),
            False uniquement sur erreur permanente non-récupérable.
        """
        import time as time_module

        start_time = time_module.time()

        try:
            logger.info(f"Traitement: {email.subject[:50]}...")

            # Étape 1 — Nettoyer et valider
            cleaning_result = self._clean_and_validate_email(email)
            if cleaning_result.should_skip:
                return True
            cleaned_email = cleaning_result.email

            # Étape 1.5 — Réponse automatique (absence)
            self._handle_auto_reply(
                cleaned_email,
                is_auto_reply=cleaning_result.metadata.get("is_auto_reply", False),
            )

            # Étape 2 — VIP check (notification éventuelle)
            self._check_vip_and_notify(cleaned_email)

            # Étape 3 — Filet déterministe : sender de notification automatique
            if self._is_notification_sender(cleaned_email):
                logger.info("  [SKIP] Sender notification automatique détecté → force label Noise")
                self._force_noise_label(cleaned_email)
                return True

            # Étape 4 — Auto-labeling (inclut le phishing pre-check + LLM label)
            self._auto_label_email(cleaned_email)

            # Étape 5 — Auto-trigger Quick Steps (best-effort, never blocks)
            self._run_quick_step_auto_triggers(cleaned_email)

            self._emails_processed_count += 1
            if self.progress_notifier:
                self.progress_notifier.check_and_notify(self._emails_processed_count)
            return True

        except Exception as e:
            processing_time_ms = self._calculate_processing_time(start_time, time_module)
            self._handle_processing_error(email, e, processing_time_ms)

            # Erreurs permanentes (billing, auth) : marquer comme traité pour éviter boucle infinie
            from app.domain.exceptions import LLMBillingError, LLMAuthenticationError
            if isinstance(e, (LLMBillingError, LLMAuthenticationError)):
                logger.warning(f"  [STOP] Erreur permanente LLM pour {email.id} — pas de requeue")
                self.tracker.mark_processed(email.id)

            return False

    def _log_routing_info(self, email: StandardEmail) -> None:
        """Log les informations de routage intelligent si activé."""
        if not self.use_smart_routing:
            return

        routing_context = self.get_routing_info(email)
        target_agent_id = self.message_router.get_final_agent_id(routing_context)

        if routing_context.routing_decision:
            logger.debug(
                f"  Routing: {target_agent_id} "
                f"(catégorie: {routing_context.routing_decision.category.value}, "
                f"confiance: {routing_context.routing_decision.confidence:.0%})"
            )
            if (
                routing_context.supervision_result
                and not routing_context.supervision_result.approved
            ):
                logger.debug("  [WARN] Routing corrigé par Supervisor")

    def _calculate_processing_time(self, start_time: float, time_module) -> Optional[int]:
        """Calcule le temps de traitement en ms."""
        try:
            return int((time_module.time() - start_time) * 1000)
        except Exception:
            logger.debug("Failed to calculate processing time", exc_info=True)
            return None


    def _run_quick_step_auto_triggers(self, email: StandardEmail) -> None:
        """Fire any Quick Steps whose auto-trigger conditions match this email.

        Resolves the integer DB account_id from the daemon's string hash so the
        quicksteps store can look up the right account. Fully wrapped — any error
        is logged and swallowed so it never interrupts the main processing pipeline.

        We resolve the SQLAlchemy Email row by email_id BEFORE evaluating triggers
        so condition evaluators that read columns stamped by ingest-time scanners
        (``deadline_at`` from ``deadline_extractor``, ``emoji_marker_json`` from
        the ``mark_with_emoji`` action, ``attachments_meta``, etc.) see the
        full row. Passing the provider's StandardEmail directly would shadow
        those columns as ``None`` and rules like ``has_deadline_detected=true``
        would silently never match.
        """
        try:
            from app.quicksteps.auto_trigger import run_auto_triggers
            from app.api.routes_helpers import _resolve_account_id_for_email
            from app.multi_accounts import get_account_manager
            from app.db.repositories.email_repository import EmailRepository
            from app.db.database import get_db_session

            account_email: str = ""
            if self.account_id:
                try:
                    acct = get_account_manager().get_account(self.account_id)
                    account_email = acct.email if acct else ""
                except Exception:
                    pass
            if not account_email:
                logger.warning("quick step auto-trigger skipped: account %s not in AccountManager", self.account_id)
                return

            int_account_id = _resolve_account_id_for_email(account_email)
            email_for_eval: object = email
            try:
                with get_db_session() as session:
                    row = EmailRepository(session).get_by_email_id(
                        email.id, account_id=int_account_id,
                    )
                    if row is not None:
                        # Detach so the object can outlive the session block;
                        # the run_auto_triggers spawns threads in some paths.
                        session.expunge(row)
                        email_for_eval = row
            except Exception as fetch_err:  # noqa: BLE001
                logger.debug("quick step auto-trigger: SQL fetch failed (%s), falling back to provider object", fetch_err)

            run_auto_triggers(int_account_id, email.id, email_for_eval)
        except Exception as exc:
            # Audit e2e 2026-06-10 B-03 : à DEBUG, une panne totale des règles
            # auto (resolver/import) était invisible — même promotion que le
            # chemin scheduler (quicksteps_scheduler.py F-02 2026-05-17).
            logger.warning("quick step auto-trigger suppressed: %s", exc)

    def _handle_processing_error(
        self, email: StandardEmail, error: Exception, processing_time_ms: Optional[int]
    ) -> None:
        """Gère une erreur de traitement d'email."""
        import traceback as _tb
        from app.domain.exceptions import LLMBillingError, LLMAuthenticationError

        wrapped_error = wrap_exception(error)
        error_msg = format_error(
            wrapped_error, include_resolution=False, include_traceback=True
        )
        logger.error(f"  [ERROR] Erreur traitement:\n{error_msg}\n{_tb.format_exc()}")
        audit_logger.log_draft_failed(
            email_id=email.id,
            recipient=email.sender,
            error=str(wrapped_error),
            duration_ms=processing_time_ms,
        )

        # Émettre un message d'erreur clair vers le frontend via WebSocket
        # Audit R-001 (2026-04-27): pass account_id so the error reaches the
        # correct user when the daemon emits from a BG thread.
        _aid = getattr(self, "account_id", None)
        if isinstance(error, LLMBillingError):
            user_msg = "Crédits IA épuisés. Veuillez vérifier votre abonnement."
            notify.error(user_msg)
            try:
                from app.api.websocket import emit_draft_error
                emit_draft_error(email_id=email.id, error=user_msg, retry_count=-1, account_id=_aid)
            except Exception:
                logger.debug("Failed to emit billing error via WebSocket", exc_info=True)
        elif isinstance(error, LLMAuthenticationError):
            user_msg = "Clé API IA invalide. Veuillez vérifier la configuration."
            notify.error(user_msg)
            try:
                from app.api.websocket import emit_draft_error
                emit_draft_error(email_id=email.id, error=user_msg, retry_count=-1, account_id=_aid)
            except Exception:
                logger.debug("Failed to emit auth error via WebSocket", exc_info=True)
        else:
            notify.error(f"Erreur: {wrapped_error.message[:50]}")


    def _prioritize_emails(self, emails: List[StandardEmail]) -> List[StandardEmail]:
        """
        Trie les emails du plus récent au plus ancien (``received_at`` décroissant).

        Audit 2026-06-02 (P1 coût) : cette méthode appelait auparavant
        ``self.prioritizer.analyze`` — un appel Haiku — PAR email, juste pour
        produire une clé de tri. Or ``poll_and_process`` distribue ensuite la
        liste à un ``ThreadPoolExecutor`` consommé via ``as_completed`` : l'ordre
        d'entrée n'a donc aucun effet observable (les workers terminent dans un
        ordre non déterministe et chaque effet de bord par email est
        indépendant de l'ordre). On supprime l'appel LLM (jusqu'à ~50
        round-trips séquentiels par cycle de polling, plus la latence avant le
        premier label) et on trie via un signal gratuit.

        NB : ``self.prioritizer`` n'est plus consommé ici. Si un consommateur
        du ``priority_score`` réapparaît un jour, le recâbler via le port
        analyzer du Container (``get_email_analyzer`` — 1 appel Haiku fusionné)
        plutôt que de ressusciter l'appel legacy par email.

        Args:
            emails: Liste d'emails à prioriser.

        Returns:
            Les emails triés du plus récent au plus ancien.
        """
        if len(emails) <= 1:
            return emails

        def _recency_key(email: StandardEmail) -> float:
            # Clé de tri gratuite (accès attribut, zéro appel LLM). ``received_at``
            # peut être None selon le provider, et mélanger naïf/aware ou des
            # dates pré-epoch ferait crasher ``sorted`` (OSError sur Windows) —
            # ce qui propagerait jusqu'au handler de poll_and_process. On retombe
            # donc sur 0.0 (= le plus ancien) en cas de None / valeur exotique.
            received = email.received_at
            if received is None:
                return 0.0
            if isinstance(received, str):
                try:
                    return datetime.fromisoformat(
                        received.replace("Z", "+00:00")
                    ).timestamp()
                except ValueError:
                    return 0.0
            try:
                return received.timestamp()
            except (AttributeError, OverflowError, OSError, ValueError):
                return 0.0

        return sorted(emails, key=_recency_key, reverse=True)

    def _evict_failed_draft_counts(self, ttl_days: int = 7) -> int:
        """Drop les entrées de ``_failed_draft_counts`` plus vieilles que ``ttl_days``.

        Audit P1-1 : sans cette éviction, le dict accumule une entrée par
        email-en-échec et grossit sans limite (proportionnel au nombre d'emails
        traités sur la durée de vie du process). Sur Hetzner où le daemon tourne
        des semaines, ça finit par peser sur la heap. L'auto-draft qui invoquait
        cette éviction a été retiré ; la méthode reste couverte par des tests
        dédiés et prête à être recâblée si le retry de brouillons réapparaît.

        Retourne le nombre d'entrées évincées.
        """
        import time as _t
        cutoff = _t.time() - (ttl_days * 86400)
        to_drop = [
            eid for eid, val in self._failed_draft_counts.items()
            if isinstance(val, tuple) and len(val) >= 2 and val[1] < cutoff
        ]
        for eid in to_drop:
            self._failed_draft_counts.pop(eid, None)
        return len(to_drop)

    def poll_and_process(self) -> int:
        """
        Récupère les nouveaux emails et les traite par ordre de priorité.

        Returns:
            Le nombre d'emails traités.
        """
        try:
            # Process all recent emails (not just unread) to generate AI drafts
            all_emails = self.provider.get_messages(limit=50, unread_only=False)
            if not all_emails:
                return 0

            new_emails = [
                email for email in all_emails
                if not self.tracker.is_processed(email.id)
            ]
            if not new_emails:
                return 0

            logger.info(f"[EMAIL] {len(new_emails)} nouveau(x) email(s) à traiter")

            new_emails = self._prioritize_emails(new_emails)

            MAX_PARALLEL_EMAILS = 3
            processed_count = 0

            def _process_one(email):
                success = self.process_email(email)
                self.tracker.mark_processed(email.id)
                return success

            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_EMAILS) as executor:
                futures = {executor.submit(_process_one, email): email for email in new_emails}
                for future in as_completed(futures):
                    try:
                        if future.result():
                            processed_count += 1
                    except Exception as e:
                        email = futures[future]
                        logger.error(f"Erreur parallèle {(email.subject or '')[:40]}: {e}")

            return processed_count

        except Exception as e:
            logger.error(f"Erreur polling: {e}")
            return 0


    def _validate_startup_config(self) -> bool:
        """
        Valide la configuration au démarrage.

        Returns:
            True si la configuration est valide, False sinon.
        """
        logger.info("[CHECK] Validation de la configuration...")
        errors = validate_config()
        if errors:
            for error in errors:
                logger.error(f"  [FAIL] {error}")
            logger.error("[FAIL] Configuration invalide. Arrêt.")
            return False
        logger.info("  [OK] Configuration valide")
        return True

    def _setup_signal_handlers(self) -> None:
        """Configure les handlers de signaux pour arrêt propre."""
        def signal_handler(sig, frame):
            logger.info("\n[STOP] Arrêt du daemon...")
            self._running = False
            self._stop_event.set()
            signal.signal(signal.SIGINT, lambda s, f: sys.exit(1))

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def _perform_startup_checks(self, skip_health_check: bool) -> bool:
        """
        Exécute les vérifications de démarrage.

        Args:
            skip_health_check: Si True, effectue uniquement l'authentification.

        Returns:
            True si les vérifications passent, False sinon.
        """
        if not skip_health_check:
            logger.info("[CHECK] Exécution du health check...")
            health = self.health_check()
            if not health["overall"]:
                logger.error("[FAIL] Health check échoué. Arrêt.")
                audit_logger.log(AuditEventType.DAEMON_START, success=False, error="Health check failed")
                failed_components = [k for k, v in health.items() if k != "overall" and not v]
                for comp in failed_components:
                    notify.health_check_failed(comp)
                return False
        else:
            logger.info("[AUTH] Authentification...")
            if not self.provider.authenticate():
                logger.error("[FAIL] Échec authentification. Arrêt.")
                audit_logger.log(AuditEventType.DAEMON_START, success=False, error="Auth failed")
                return False
        return True

    def _log_startup(self) -> None:
        """Log le démarrage réussi du daemon."""
        audit_logger.log(
            AuditEventType.DAEMON_START,
            success=True,
            details={
                "poll_interval": self.poll_interval,
                "skip_low_priority": self.skip_low_priority,
                "provider": EMAIL_PROVIDER_TYPE,
            }
        )
        logger.info(f"[OK] Daemon démarré (polling toutes les {self.poll_interval}s)")
        logger.info(f"[STATS] {self.tracker.count()} emails déjà traités")
        logger.info("-" * 50)

    def _reconnect_provider(self) -> bool:
        """Reconnect IMAP provider for a fresh connection each cycle."""
        # Disconnect previous connection if still open
        if self.provider and hasattr(self.provider, 'disconnect'):
            try:
                self.provider.disconnect()
            except Exception:
                logger.debug("Failed to disconnect provider before reconnect", exc_info=True)

        try:
            self.provider = get_email_provider()
            if self.provider.authenticate():
                return True
            logger.warning("Daemon: provider re-authentication failed")
            return False
        except Exception as e:
            logger.error(f"Daemon: provider reconnect error: {e}")
            return False

    def _disconnect_provider(self) -> None:
        """Disconnect IMAP provider to free the connection slot."""
        if self.provider and hasattr(self.provider, 'disconnect'):
            try:
                self.provider.disconnect()
            except Exception:
                logger.debug("Failed to disconnect provider", exc_info=True)

    def _ensure_provider_alive(self) -> bool:
        """Vérifie que le provider IMAP est connecté et vivant via NOOP."""
        if not self.provider:
            return False
        try:
            if hasattr(self.provider, '_connection') and self.provider._connection:
                status, _ = self.provider._connection.noop()
                return status == "OK"
            # Non-IMAP providers (e.g. Gmail API) — assume alive
            if hasattr(self.provider, 'authenticate'):
                return True
            return False
        except Exception:
            logger.debug("Provider alive check failed", exc_info=True)
            return False

    def _run_main_loop(self) -> None:
        """Exécute la boucle principale du daemon."""
        loop_count = 0

        try:
            while self._running:
                try:
                    # Keepalive: reuse connection, reconnect only if NOOP fails
                    if not self._ensure_provider_alive():
                        if not self._reconnect_provider():
                            if self._stop_event.wait(timeout=30):
                                break
                            continue

                    processed = self.poll_and_process()
                    if processed > 0:
                        logger.info(f"[STATS] {processed} email(s) traité(s) {token_counter}")
                        logger.info("-" * 50)

                    drafts_completed = self.poll_user_drafts()
                    if drafts_completed > 0:
                        logger.info(f"[DRAFT] {drafts_completed} brouillon(s) complété(s)")
                        logger.info("-" * 50)

                    loop_count += 1

                    if self._emails_processed_count > 0 and self._emails_processed_count % LEARNING_ANALYSIS_INTERVAL == 0:
                        self.run_learning_analysis()

                    # Auto-cleanup tasks (every CLEANUP_LOOP_INTERVAL loops ≈ ~4h with 5min interval)
                    if loop_count % CLEANUP_LOOP_INTERVAL == 0:
                        self._auto_empty_trash()
                        self._auto_empty_spam()
                        self._auto_delete_old_noise()

                    if self._stop_event.wait(timeout=self.poll_interval):
                        break

                except KeyboardInterrupt:
                    break
                except CircuitOpenError as e:
                    self._disconnect_provider()
                    logger.warning(f"[WARN] Circuit ouvert: {e}")
                    if self._stop_event.wait(timeout=min(e.remaining_time, 30)):
                        break
                except Exception as e:
                    self._disconnect_provider()
                    logger.error(f"Erreur dans la boucle principale: {e}")
                    if self._stop_event.wait(timeout=10):
                        break
        except KeyboardInterrupt:
            pass
        finally:
            self._disconnect_provider()

    def start(self, skip_health_check: bool = False, skip_config_validation: bool = False) -> None:
        """
        Démarre le daemon en boucle infinie.

        Args:
            skip_health_check: Si True, ne pas exécuter le health check au démarrage.
            skip_config_validation: Si True, ne pas valider la configuration.
        """
        self._running = True
        self._stop_event.clear()

        if not skip_config_validation and not self._validate_startup_config():
            return

        self._setup_signal_handlers()

        if not self._perform_startup_checks(skip_health_check):
            return

        self._log_startup()
        self._run_main_loop()

        audit_logger.log(AuditEventType.DAEMON_STOP, success=True)
        logger.info("[OK] Daemon arrêté proprement")
    def stop(self) -> None:
        """Arrête le daemon proprement."""
        logger.info("[STOP] Demande d'arrêt...")
        self._running = False
        self._stop_event.set()

    def poll_user_drafts(self) -> int:
        """
        Récupère les brouillons utilisateur et complète ceux qui sont des demandes.

        Workflow:
        1. Récupérer les brouillons de l'utilisateur
        2. Filtrer ceux déjà traités
        3. Détecter les demandes de complétion (préfixe "Brouillon:", bullet points, etc.)
        4. Compléter via DraftCompletionAgent
        5. Mettre à jour le brouillon original
        6. Marquer comme traité

        Returns:
            Le nombre de brouillons complétés.
        """
        try:
            logger.debug("[DRAFT] Polling des brouillons utilisateur...")

            # Récupérer les brouillons utilisateur
            user_drafts = self.provider.get_user_drafts(limit=50)

            if not user_drafts:
                logger.debug("[DRAFT] Aucun brouillon trouvé")
                return 0

            # Filtrer les brouillons déjà traités
            new_drafts = []
            for draft in user_drafts:
                if self.processed_drafts_tracker.is_processed(draft.id):
                    logger.debug(f"[DRAFT] Brouillon déjà traité: {draft.id[:20]}...")
                else:
                    new_drafts.append(draft)

            if not new_drafts:
                logger.debug("[DRAFT] Aucun nouveau brouillon à traiter")
                return 0

            logger.debug(f"[DRAFT] {len(new_drafts)} brouillon(s) utilisateur à analyser")

            completed_count = 0
            for draft in new_drafts:
                try:
                    # Vérifier si c'est une demande de complétion
                    draft_text = draft.body or ""
                    logger.debug(
                        "[DRAFT] Analyse brouillon: subject_len=%s, body_len=%s",
                        len(draft.subject or ""),
                        len(draft_text),
                    )

                    if not self.draft_completion_agent.is_completion_request(draft_text):
                        # Pas une demande de complétion, marquer comme traité et passer
                        logger.debug("[DRAFT] Pas une demande de complétion, ignoré")
                        self.processed_drafts_tracker.mark_processed(draft.id)
                        continue

                    logger.info(
                        "[DRAFT] Complétion brouillon: draft_id=%s, subject_len=%s",
                        draft.id,
                        len(draft.subject or ""),
                    )

                    # Compléter le brouillon
                    recipient = draft.to[0] if draft.to else None
                    completed = self.draft_completion_agent.complete_with_options(
                        raw_input=draft_text,
                        recipient=recipient,
                        subject_hint=draft.subject,
                    )

                    # Mettre à jour le brouillon dans la boîte mail
                    new_subject = completed.subject or draft.subject
                    new_body = completed.body

                    success = self.provider.update_draft(
                        draft_id=draft.id,
                        subject=new_subject,
                        body=new_body,
                    )

                    if success:
                        logger.info(f"  [OK] Brouillon complété: {new_subject[:50]}...")
                        completed_count += 1

                        # Log d'audit
                        audit_logger.log(
                            AuditEventType.DRAFT_COMPLETED,
                            success=True,
                            details={
                                "draft_id": draft.id,
                                "original_length": len(draft_text),
                                "completed_length": len(new_body),
                                "subject": new_subject,
                            }
                        )

                        # Notification desktop
                        notify.draft_created(
                            recipient or "destinataire",
                            new_subject,
                            priority=50,
                        )

                        # Extraire et sauvegarder les engagements du brouillon complété.
                        # Inlined 2026-05-15 — the prior `_extract_commitments_from_draft`
                        # helper was deleted with the auto-draft graveyard but this caller
                        # was missed. Own try/except so a commitment-extraction failure
                        # doesn't trigger the misleading "Erreur complétion" log below.
                        try:
                            extracted = self.commitment_extractor.extract(new_body)
                            if extracted:
                                logger.info(f"  [NOTE] {len(extracted)} engagement(s) détecté(s)")
                                self.commitment_use_case.track_from_extracted(extracted, draft.id)
                        except Exception as _commit_err:
                            logger.warning(f"  [WARN] Extraction engagements échouée: {_commit_err}")
                    else:
                        logger.warning(f"  [WARN] Échec mise à jour brouillon: {draft.id}")

                    # Marquer comme traité (même en cas d'échec pour éviter les boucles)
                    self.processed_drafts_tracker.mark_processed(draft.id)

                except Exception as e:
                    logger.error(f"  [FAIL] Erreur complétion brouillon {draft.id}: {e}")
                    # Marquer comme traité pour éviter les boucles infinies
                    self.processed_drafts_tracker.mark_processed(draft.id)

            return completed_count

        except Exception as e:
            logger.error(f"Erreur polling brouillons: {e}")
            return 0

    def run_learning_analysis(self) -> None:
        """
        Exécute l'analyse learning pour améliorer les prompts.

        Appelé périodiquement après un certain nombre d'emails traités.
        """
        try:
            logger.info("[LEARN] Analyse learning en cours...")

            # Analyser les feedbacks
            insights = self.learning_manager.analyze_feedback()
            logger.debug(f"  [STATS] Feedback analysés: {insights.get('total_with_feedback', 0)}")

            # Extraire de nouveaux patterns si on a assez de données
            if insights.get("total_with_feedback", 0) >= 10:
                patterns = self.learning_manager.extract_patterns_from_feedback()
                if patterns:
                    logger.info(f"  [INFO] {len(patterns)} nouveaux patterns extraits")

                # Générer des ajustements si nécessaire
                adjustment = self.learning_manager.generate_prompt_adjustment()
                if adjustment:
                    logger.info(f"  [INFO] Nouvel ajustement: {adjustment.adjustment[:50]}...")

            # Afficher les stats
            stats = self.learning_manager.get_stats()
            logger.info(f"  [STATS] Stats: {stats.get('patterns_count', 0)} patterns, "
                       f"{stats.get('active_adjustments', 0)} ajustements actifs")

        except Exception as e:
            logger.error(f"Erreur analyse learning: {e}")

    def _auto_empty_trash(self) -> None:
        """
        Supprime définitivement les emails de la corbeille de plus de 30 jours
        si le paramètre auto_empty_trash_30d est activé.
        """
        # Scope manquant détecté lors d'un cycle précédent → échec permanent,
        # ne pas relancer 200 appels API voués au 403 à chaque cycle.
        if getattr(self, '_purge_scope_missing', False):
            return
        try:
            from app.api.settings import load_settings
            _aid = getattr(getattr(self, 'account', None), 'id', None)
            settings = load_settings(account_id=_aid)
            if not settings.get("auto_empty_trash_30d", False):
                return

            # Resolve trash folder name for this provider
            _trash_folder = None
            if hasattr(self.provider, 'resolve_folder_name'):
                _trash_folder = self.provider.resolve_folder_name("trash")
            if not _trash_folder:
                _pname = getattr(self.provider, 'PROVIDER_NAME', '')
                if _pname == 'outlook':
                    _trash_folder = "deleteditems"
                elif _pname == 'gmail':
                    _trash_folder = "[Gmail]/Trash"
                else:
                    _trash_folder = "Deleted Items"

            if hasattr(self.provider, 'get_messages'):
                try:
                    emails = self.provider.get_messages(limit=200, label_ids=[_trash_folder])
                except TypeError:
                    try:
                        emails = self.provider.get_messages(limit=200, folder=_trash_folder)
                    except TypeError:
                        emails = []
            else:
                return

            if not emails:
                return

            from datetime import timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)

            deleted = 0
            for email_obj in emails:
                try:
                    received = email_obj.received_at
                    if not received:
                        continue
                    if hasattr(received, 'tzinfo') and received.tzinfo is None:
                        received = received.replace(tzinfo=timezone.utc)
                    if received > cutoff:
                        continue
                    if hasattr(self.provider, "permanently_delete"):
                        if self.provider.permanently_delete(email_obj.id):
                            deleted += 1
                except InsufficientScopeError:
                    # Permanent : le token n'aura jamais le scope tant que
                    # l'app ne le demande pas. Désactiver la purge pour ce
                    # compte (sinon : 200 appels API en échec par cycle —
                    # la tempête de 2 107 erreurs de l'audit 2026-06-09).
                    # Gmail purge nativement la corbeille après 30 jours,
                    # donc la promesse « 30 jours » reste tenue.
                    self._purge_scope_missing = True
                    logger.warning(
                        "Auto-purge désactivée pour ce compte : le token Gmail "
                        "n'a pas le scope complet https://mail.google.com/ "
                        "(messages.delete impossible). Gmail purge nativement "
                        "corbeille/spam après 30 jours."
                    )
                    return
                except Exception as e:
                    logger.debug(f"Failed to auto-delete trash item {email_obj.id}: {e}")
                    continue

            if deleted > 0:
                logger.info(f"Auto-emptied {deleted} trash item(s) older than 30 days")
        except Exception as e:
            # Audit Cluster D (2026-05-17) B-06: this outer handler catches
            # load_settings/provider-auth/DB-locked errors. At .debug a
            # transient failure silently disabled the feature with no signal
            # in INFO logs. Per-item failures stay at .debug (the loop
            # continues), but a whole-batch crash should be visible to ops.
            logger.warning(f"Auto-empty trash error: {e}", exc_info=True)

    def _auto_empty_spam(self) -> None:
        """
        Supprime définitivement les emails indésirables de plus de 30 jours
        si le paramètre auto_empty_spam_30d est activé.
        """
        # Voir _auto_empty_trash — même flag, même raison.
        if getattr(self, '_purge_scope_missing', False):
            return
        try:
            from app.api.settings import load_settings
            _aid = getattr(getattr(self, 'account', None), 'id', None)
            settings = load_settings(account_id=_aid)
            if not settings.get("auto_empty_spam_30d", False):
                return

            # Resolve spam folder name for this provider
            _spam_folder = None
            if hasattr(self.provider, 'resolve_folder_name'):
                _spam_folder = self.provider.resolve_folder_name("spam")
            if not _spam_folder:
                _pname = getattr(self.provider, 'PROVIDER_NAME', '')
                if _pname == 'outlook':
                    _spam_folder = "junkemail"
                elif _pname == 'gmail':
                    _spam_folder = "[Gmail]/Spam"
                else:
                    _spam_folder = "Junk"

            if hasattr(self.provider, 'get_messages'):
                try:
                    emails = self.provider.get_messages(limit=200, label_ids=[_spam_folder])
                except TypeError:
                    try:
                        emails = self.provider.get_messages(limit=200, folder=_spam_folder)
                    except TypeError:
                        emails = []
            else:
                return

            if not emails:
                return

            from datetime import timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)

            deleted = 0
            for email_obj in emails:
                try:
                    received = email_obj.received_at
                    if not received:
                        continue
                    if hasattr(received, 'tzinfo') and received.tzinfo is None:
                        received = received.replace(tzinfo=timezone.utc)
                    if received > cutoff:
                        continue
                    if hasattr(self.provider, "permanently_delete"):
                        if self.provider.permanently_delete(email_obj.id):
                            deleted += 1
                except InsufficientScopeError:
                    # Voir _auto_empty_trash — échec permanent, on coupe.
                    self._purge_scope_missing = True
                    logger.warning(
                        "Auto-purge spam désactivée pour ce compte : scope "
                        "complet https://mail.google.com/ manquant "
                        "(messages.delete impossible)."
                    )
                    return
                except Exception as e:
                    logger.debug(f"Failed to auto-delete spam item {email_obj.id}: {e}")
                    continue

            if deleted > 0:
                logger.info(f"Auto-emptied {deleted} spam item(s) older than 30 days")
        except Exception as e:
            # Audit Cluster D (2026-05-17) B-06: see _auto_empty_trash —
            # elevated to .warning so transient feature stoppages surface
            # in INFO logs instead of vanishing into .debug noise.
            logger.warning(f"Auto-empty spam error: {e}", exc_info=True)

    def _auto_delete_old_noise(self) -> None:
        """
        Déplace automatiquement les emails Noise lus de plus de 30 jours
        vers la corbeille si le paramètre auto_delete_noise_30d est activé.
        """
        try:
            from app.api.settings import load_settings
            _aid = getattr(getattr(self, 'account', None), 'id', None)
            settings = load_settings(account_id=_aid)
            if not settings.get("auto_delete_noise_30d", False):
                return

            from app.infrastructure.container import get_container
            container = get_container()
            label_store = container.get_label_store(account_id=_aid)
            noise_ids = set(label_store.get_emails_by_label("Noise"))
            if not noise_ids:
                return

            # Get account info for provider
            from app.multi_accounts import get_all_accounts
            accounts = get_all_accounts()
            if not accounts:
                return

            from datetime import timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            trashed = 0

            for acct in accounts:
                try:
                    acct_id = acct.get("id") or acct.get("account_id")
                    if not acct_id:
                        continue

                    from app.db.database import get_db_session
                    from app.db.email_repository import EmailRepository
                    with get_db_session() as session:
                        repo = EmailRepository(session)
                        db_emails = list(repo.get_by_account(
                            account_id=acct_id,
                            limit=500,
                            email_ids=noise_ids,
                            skip_folder_filter=True,
                        ))

                    if not db_emails:
                        continue

                    ids_to_trash = []
                    for em in db_emails:
                        if not em.is_read:
                            continue
                        email_date = em.date
                        if email_date and email_date.tzinfo is None:
                            email_date = email_date.replace(tzinfo=timezone.utc)
                        if email_date and email_date < cutoff:
                            ids_to_trash.append(em.email_id)

                    if not ids_to_trash:
                        continue

                    # Move to trash via provider.delete_email (trash, not permanent)
                    provider = self.provider
                    if hasattr(provider, "delete_email"):
                        for eid in ids_to_trash:
                            try:
                                if provider.delete_email(eid):
                                    trashed += 1
                            except Exception:
                                continue
                except Exception as e:
                    logger.debug(f"Auto-trash noise for account {acct}: {e}")
                    continue

            if trashed > 0:
                logger.info(f"Auto-trashed {trashed} noise email(s) older than 30 days")
        except Exception as e:
            # Audit Cluster D (2026-05-17) B-06: see _auto_empty_trash —
            # elevated to .warning so transient feature stoppages surface
            # in INFO logs instead of vanishing into .debug noise.
            logger.warning(f"Auto-trash old noise error: {e}", exc_info=True)

    def run_once(self) -> int:
        """
        Exécute un seul cycle de polling (utile pour les tests).

        Returns:
            Le nombre d'emails traités.
        """
        logger.info("[AUTH] Authentification...")
        if not self.provider.authenticate():
            logger.error("[FAIL] Échec authentification.")
            return 0

        return self.poll_and_process()


# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

def main():
    """Point d'entrée principal du daemon."""
    print("""
+---------------------------------------------------------------+
|                    Agentys Email Daemon                       |
|                        Mode "Zero UI"                         |
+---------------------------------------------------------------+
    """)

    # Vérifier la configuration
    provider_type = os.getenv("EMAIL_PROVIDER_TYPE", "OUTLOOK")
    print(f"[Email] Provider: {provider_type}")
    print(f"[Timer] Intervalle: {POLL_INTERVAL}s")
    print("[Priority] Priorisation: Activee")
    print("[Classify] Classification: Activee")
    if SKIP_LOW_PRIORITY:
        print("[Skip] Auto-skip: Newsletters, Promos, Spam")
    print()

    # Créer et démarrer le daemon
    daemon = EmailDaemon(skip_low_priority=SKIP_LOW_PRIORITY)
    daemon.start()


if __name__ == "__main__":
    main()
