# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Fixtures pytest partagées pour les tests Agentys.
"""

import os
from unittest.mock import MagicMock


def pytest_configure(config):
    """Configure les variables d'environnement avant la collecte des tests."""
    if "ANTHROPIC_API_KEY" not in os.environ:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-mock-key-for-testing"

    # Disable all notifications during tests to prevent real desktop/push notifications
    os.environ["NOTIFICATIONS_ENABLED"] = "false"
    os.environ["NOTIFICATIONS_SOUND"] = "false"
    os.environ["PUSH_NOTIFICATIONS_ENABLED"] = "false"


import pytest
from datetime import datetime
from typing import List, Optional

from app.interfaces.email_provider import EmailProvider, StandardEmail
from app.domain.ports.llm_port import LLMPort, LLMResponse


# ============================================================================
# FIXTURES - MOCK LLM (autouse=True)
# ============================================================================

@pytest.fixture
def mock_llm():
    """LLM mocké pour les tests."""
    mock = MagicMock(spec=LLMPort)
    mock.name = "mock-llm"
    mock.model = "mock-model"
    mock.complete.return_value = LLMResponse(
        content="Réponse mockée",
        input_tokens=10,
        output_tokens=5,
        model="mock-model"
    )
    mock.is_available.return_value = True
    return mock


@pytest.fixture(autouse=True)
def mock_container_llm(mock_llm):
    """
    Mock global du LLM dans le Container.

    IMPORTANT: Ce fixture s'applique automatiquement à TOUS les tests
    grâce à autouse=True. Il prévient l'import réel du module anthropic
    en injectant un mock AVANT le lazy-loading du LLM.

    Reset aussi les module-level singletons qui survivent à reset_container() :
    - app.infrastructure.pending_draft_store._pending_draft_store

    Pollution observée : si un test injecte un MagicMock dans le store via
    `Container.get_pending_draft_store().add(mock_draft)`, le module-level
    singleton garde la référence après le test → le test suivant qui touche
    /api/pending-drafts/* via le client Flask déclenche un crash JSON
    serialize sur le Mock résiduel ('Object of type Mock is not JSON
    serializable'), ce qui pollue le state Flask et fait échouer des tests
    qui accèdent au même blueprint plus tard. Cas reproduit :
    test_no_auto_send_safety::test_validate_endpoint_requires_explicit_call
    pollue test_api_drafts_complete::test_complete_draft_get_method_not_allowed.
    """
    from app.infrastructure.container import get_container, reset_container

    reset_container()
    container = get_container()
    container._llm = mock_llm

    yield mock_llm

    reset_container()

    # Reset module-level singletons that survive Container reset.
    try:
        import app.infrastructure.pending_draft_store as _pds_mod
        _pds_mod._pending_draft_store = None
    except Exception:
        # Best effort: ne jamais bloquer le teardown sur un import edge case.
        pass

    # Reset module-level account_id cache : peut contenir des MagicMock
    # laissés par un test qui patche `_resolve_account_id_for_user` avec
    # `return_value=Mock`. Un test suivant qui hit `get_draft` fait
    # `if account_id <= 0` → TypeError sur Mock.
    try:
        import app.api.routes_helpers as _rh_mod
        if hasattr(_rh_mod, "_account_id_cache"):
            _rh_mod._account_id_cache.clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def clear_legacy_module_cache():
    """
    Vide le cache LegacyModuleLoader entre les tests.

    IMPORTANT: Le cache singleton peut causer des interférences entre tests
    si les mocks ne sont pas correctement nettoyés.
    """
    from app.api.routes import LegacyModuleLoader

    LegacyModuleLoader.clear_cache()
    yield
    LegacyModuleLoader.clear_cache()


@pytest.fixture(autouse=True)
def isolate_token_usage_writer(monkeypatch, request):
    """Prevent async token-usage rows from leaking across tests.

    Most tests only need to verify that LLM usage is queued. Starting the
    daemon writer inside tests is unsafe because retry tests patch
    app.agents._time.sleep, which mutates the shared time module and can make
    the writer loop spin against the same mock.
    """
    import queue

    import app.infrastructure.token_usage_writer as writer

    allow_writer_thread = request.node.nodeid.endswith(
        "tests/audit_fixes/test_q_08_token_usage_persistence.py::test_writer_async_flush_lifecycle"
    )

    def _reset_writer() -> None:
        writer._stop_event.set()
        thread = writer._writer_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        if thread is None or not thread.is_alive():
            writer._writer_thread = None
        while True:
            try:
                writer._queue.get_nowait()
            except queue.Empty:
                break
        writer._stop_event.clear()

    _reset_writer()
    if not allow_writer_thread:
        monkeypatch.setattr(writer, "_ensure_writer_started", lambda: None)

    yield
    _reset_writer()


@pytest.fixture(autouse=True)
def isolate_contact_style_store(tmp_path_factory, monkeypatch):
    """Isolate the SQLite contact-style store per test (PR6 follow-up).

    Without this fixture, the production ``SqliteContactStyleStore``
    consumed by ``WritingStyleProfile.contact_profiles`` reads/writes the
    user's real ``~/.agentys/data/agentys.db`` from every test, causing
    cross-test pollution and on-disk side effects.

    We patch the module-level ``get_db_session`` AND reset the Container
    singleton, then force a fresh store instance through the Container so
    its ``__init__`` runs under the patched session and creates the
    ``contact_styles`` schema in the per-test SQLite engine.
    """
    from contextlib import contextmanager
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path_factory.mktemp("contact_styles") / "test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _isolated_session():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(
        "app.infrastructure.contact_style_store_sqlite.get_db_session",
        _isolated_session,
    )
    # Force the Container to rebuild the store against the patched session.
    # We pre-instantiate it here so the schema is bootstrapped synchronously
    # under our patched ``get_db_session`` — relying on lazy reconstruction
    # leaves a window where another fixture may have already grabbed the
    # production-DB store first.
    try:
        from app.infrastructure.contact_style_store_sqlite import (
            SqliteContactStyleStore,
        )
        from app.infrastructure.container import get_container

        c = get_container()
        c._contact_style_store = SqliteContactStyleStore()
    except Exception:
        # Container or DB engine not configured for this test — fine, the
        # ``_ContactProfilesView`` falls back to its in-memory mode.
        pass
    yield


# ============================================================================
# FIXTURES - MOCK NOTIFICATIONS (autouse=True)
# ============================================================================

@pytest.fixture(autouse=True)
def mock_notifications(monkeypatch):
    """
    Mock global des notifications - désactive toutes les notifications pendant les tests.

    Ce fixture s'applique automatiquement à TOUS les tests grâce à autouse=True.
    Il empêche l'envoi de vraies notifications desktop et push pendant les tests.

    Three-layer protection:
    1. Environment variables (set in pytest_configure) disable notifications
    2. Mock the notification manager singleton and its methods
    3. Mock subprocess.run to block osascript/notify-send/powershell calls
    """
    import subprocess
    from app.infrastructure.notifications import NotificationManager

    mock_manager = MagicMock(spec=NotificationManager)
    mock_manager.config = MagicMock()
    mock_manager.config.enabled = False  # Explicitly disable
    mock_manager.config.push_enabled = False

    # Configure all notification methods to return True (no-op)
    notification_methods = [
        'send', 'draft_created', 'draft_failed', 'followup_created',
        'learning_complete', 'health_check_failed', 'rate_limit_warning',
        'budget_warning', 'error', 'info', 'vip_email_received'
    ]
    for method_name in notification_methods:
        getattr(mock_manager, method_name).return_value = True

    monkeypatch.setattr(
        "app.infrastructure.notifications._notification_manager",
        None
    )
    monkeypatch.setattr(
        "app.infrastructure.notifications.get_notification_manager",
        lambda: mock_manager
    )
    monkeypatch.setattr(
        "app.infrastructure.notifications.notify",
        mock_manager
    )

    # Safety net: Mock subprocess.run to intercept notification commands
    # This catches any notifications that slip through the manager mock
    _original_subprocess_run = subprocess.run

    def _mock_subprocess_run(cmd, *args, **kwargs):
        """Block notification commands, allow others through."""
        cmd_str = cmd if isinstance(cmd, str) else " ".join(str(c) for c in cmd)
        # Block macOS osascript notifications
        if "osascript" in cmd_str and "display notification" in cmd_str:
            return MagicMock(returncode=0)
        # Block Linux notify-send
        if "notify-send" in cmd_str:
            return MagicMock(returncode=0)
        # Block Windows PowerShell toast notifications
        if "powershell" in cmd_str and "ToastNotification" in cmd_str:
            return MagicMock(returncode=0)
        # Allow all other subprocess calls
        return _original_subprocess_run(cmd, *args, **kwargs)

    monkeypatch.setattr("subprocess.run", _mock_subprocess_run)
    monkeypatch.setattr(
        "app.infrastructure.notifications.subprocess.run",
        _mock_subprocess_run
    )

    return mock_manager


# ============================================================================
# FIXTURES - STANDARD EMAIL
# ============================================================================

@pytest.fixture
def sample_email() -> StandardEmail:
    """Email de test standard."""
    return StandardEmail(
        id="msg-123",
        sender="client@example.com",
        sender_name="Jean Client",
        to=["support@example.com"],
        cc=[],
        subject="Question sur votre service",
        body="Bonjour, j'ai une question sur votre service. Merci.",
        body_html=None,
        received_at=datetime(2025, 1, 15, 10, 30, 0),
        is_read=False,
        has_attachments=False,
        conversation_id="conv-456",
        provider_source="test"
    )


@pytest.fixture
def sample_emails() -> List[StandardEmail]:
    """Liste d'emails de test."""
    return [
        StandardEmail(
            id="msg-001",
            sender="alice@example.com",
            sender_name="Alice",
            subject="Demande d'information",
            body="Bonjour, je souhaite...",
            provider_source="test"
        ),
        StandardEmail(
            id="msg-002",
            sender="bob@example.com",
            sender_name="Bob",
            subject="Problème de connexion",
            body="J'ai un souci avec mon compte...",
            provider_source="test"
        ),
        StandardEmail(
            id="msg-003",
            sender="charlie@example.com",
            sender_name="Charlie",
            subject="Merci !",
            body="Je voulais vous remercier...",
            provider_source="test"
        ),
    ]


# ============================================================================
# FIXTURES - MOCK PROVIDER
# ============================================================================

class MockEmailProvider(EmailProvider):
    """
    Implémentation mock de EmailProvider pour les tests.

    Stocke les emails en mémoire et simule les opérations.
    """

    def __init__(self, emails: List[StandardEmail] = None):
        self._emails = {e.id: e for e in (emails or [])}
        self._drafts = {}
        self._user_drafts = {}  # Brouillons utilisateur (pour polling)
        self._authenticated = False
        self._draft_counter = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    def authenticate(self) -> bool:
        self._authenticated = True
        return True

    def get_unread_messages(self, limit: int = 10) -> List[StandardEmail]:
        unread = [e for e in self._emails.values() if not e.is_read]
        return unread[:limit]

    def get_message_by_id(self, message_id: str) -> Optional[StandardEmail]:
        return self._emails.get(message_id)

    def create_draft(
        self,
        to: List[str],
        subject: str,
        body: str,
        reply_to_id: Optional[str] = None,
        cc: Optional[List[str]] = None,
        is_html: bool = False,
        attachments: Optional[list] = None,
        bcc: Optional[List[str]] = None,
        from_name: Optional[str] = None
    ) -> Optional[str]:
        self._draft_counter += 1
        draft_id = f"draft-{self._draft_counter}"
        self._drafts[draft_id] = {
            "to": to,
            "subject": subject,
            "body": body,
            "reply_to_id": reply_to_id,
            "cc": cc,
            "is_html": is_html
        }
        return draft_id

    def send_draft(self, draft_id: str) -> bool:
        if draft_id in self._drafts:
            del self._drafts[draft_id]
            return True
        return False

    def mark_as_read(self, message_id: str) -> bool:
        if message_id in self._emails:
            # Créer une copie avec is_read=True
            email = self._emails[message_id]
            self._emails[message_id] = StandardEmail(
                id=email.id,
                sender=email.sender,
                sender_name=email.sender_name,
                to=email.to,
                cc=email.cc,
                subject=email.subject,
                body=email.body,
                is_read=True,
                provider_source=email.provider_source
            )
            return True
        return False

    def mark_as_unread(self, message_id: str) -> bool:
        if message_id in self._emails:
            email = self._emails[message_id]
            self._emails[message_id] = StandardEmail(
                id=email.id,
                sender=email.sender,
                sender_name=email.sender_name,
                to=email.to,
                cc=email.cc,
                subject=email.subject,
                body=email.body,
                is_read=False,
                provider_source=email.provider_source
            )
            return True
        return False

    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        """Récupère les brouillons utilisateur."""
        drafts = list(self._user_drafts.values())
        return drafts[:limit]

    def get_draft_by_id(self, draft_id: str) -> Optional[StandardEmail]:
        """Récupère un brouillon par ID."""
        return self._user_drafts.get(draft_id)

    def update_draft(
        self,
        draft_id: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        is_html: bool = False
    ) -> bool:
        """Met à jour un brouillon existant."""
        if draft_id not in self._user_drafts:
            return False

        current = self._user_drafts[draft_id]
        self._user_drafts[draft_id] = StandardEmail(
            id=current.id,
            sender=current.sender,
            sender_name=current.sender_name,
            to=to if to is not None else current.to,
            cc=cc if cc is not None else current.cc,
            subject=subject if subject is not None else current.subject,
            body=body if body is not None else current.body,
            body_html=current.body_html if not is_html else body,
            received_at=current.received_at,
            is_read=current.is_read,
            has_attachments=current.has_attachments,
            conversation_id=current.conversation_id,
            provider_source=current.provider_source,
            raw_metadata=current.raw_metadata
        )
        return True


@pytest.fixture
def mock_provider(sample_emails) -> MockEmailProvider:
    """Provider mock avec des emails de test."""
    return MockEmailProvider(emails=sample_emails)


@pytest.fixture
def empty_provider() -> MockEmailProvider:
    """Provider mock sans emails."""
    return MockEmailProvider()


# ============================================================================
# FIXTURES - MOCKED DAEMON FACTORY
# ============================================================================

def create_mocked_daemon(
    mock_provider=None,
    mock_agents=None,
    mock_container=None,
    poll_interval=60,
    skip_low_priority=False,
    use_smart_routing=False,
):
    """
    Crée un EmailDaemon avec toutes les dépendances mockées.

    Cette factory centrale unifie la création de daemons mockés pour les tests.
    Elle évite la duplication de code dans les fichiers de test.

    Args:
        mock_provider: Provider email mocké (ou None pour défaut)
        mock_agents: Dict avec agents mockés {"drafter", "critic", "prioritizer", "classifier"}
        mock_container: Container mocké (ou None pour défaut)
        poll_interval: Intervalle de polling en secondes
        skip_low_priority: Skip des emails basse priorité
        use_smart_routing: Utilisation du routage intelligent

    Returns:
        EmailDaemon: Instance mockée prête pour les tests
    """
    import threading
    from app.daemon import EmailDaemon
    from app.domain.entities.anonymized_result import AnonymizedResult

    # Créer le daemon sans initialisation automatique
    daemon = EmailDaemon.__new__(EmailDaemon)

    # Provider mock
    if mock_provider is None:
        mock_provider = MagicMock(spec=EmailProvider)
        mock_provider.provider_name = "mock"
        mock_provider.authenticate.return_value = True
        mock_provider.get_unread_messages.return_value = []
        mock_provider.get_user_drafts.return_value = []
        mock_provider.create_draft.return_value = "draft-001"
        mock_provider.update_draft.return_value = True
        mock_provider.mark_as_read.return_value = True
        mock_provider.apply_label.return_value = True

    daemon.provider = mock_provider

    # Agents mock
    if mock_agents is None:
        mock_agents = {
            "drafter": MagicMock(),
            "critic": MagicMock(),
            "prioritizer": MagicMock(),
            "classifier": MagicMock(),
        }
        mock_agents["drafter"].draft.return_value = "Draft response"
        mock_agents["drafter"].revise.return_value = "Revised response"
        mock_agents["critic"].evaluate.return_value = "VALID"
        mock_agents["critic"].is_valid.return_value = True
        mock_agents["prioritizer"].analyze.return_value = {"priority_score": 50}
        mock_agents["classifier"].classify.return_value = {"category": "NORMAL"}
        mock_agents["classifier"].should_skip.return_value = False

    daemon.drafter = mock_agents["drafter"]
    daemon.critic = mock_agents["critic"]
    daemon.prioritizer = mock_agents["prioritizer"]
    daemon.classifier = mock_agents["classifier"]

    # Container dependencies
    if mock_container is None:
        mock_container = MagicMock()
        mock_container.get_processed_emails_tracker.return_value = MagicMock()
        mock_container.get_learning_service.return_value = MagicMock()
        mock_container.get_draft_history.return_value = MagicMock()

    daemon.tracker = mock_container.get_processed_emails_tracker()
    daemon.tracker.is_processed.return_value = False
    daemon.tracker.mark_processed.return_value = None
    daemon.tracker.count.return_value = 0

    # Processed drafts tracker mock
    daemon.processed_drafts_tracker = MagicMock()
    daemon.processed_drafts_tracker.is_processed.return_value = False
    daemon.processed_drafts_tracker.mark_processed.return_value = None

    # Draft completion agent mock
    daemon.draft_completion_agent = MagicMock()
    daemon.draft_completion_agent.is_completion_request.return_value = False

    daemon.learning_manager = mock_container.get_learning_service()
    daemon.learning_manager.should_require_review.return_value = False
    daemon.learning_manager.analyze_feedback.return_value = {}
    daemon.learning_manager.get_stats.return_value = {}

    daemon.draft_history = mock_container.get_draft_history()

    # Message router
    daemon.message_router = MagicMock()

    # Phishing detector
    from app.domain.services import PhishingDetector
    daemon.phishing_detector = PhishingDetector()

    # Correction manager mocké
    daemon.correction_manager = MagicMock()
    daemon.correction_manager.apply_learned_corrections.return_value = ("Draft response", [])
    daemon.correction_manager.detect_user_modification.return_value = False

    # Task extractor mock
    daemon.task_extractor = MagicMock()
    daemon.task_extractor.extract.return_value = []
    daemon.task_extractor.extract_tasks.return_value = []
    daemon.task_repository = MagicMock()

    # Commitment extractor mock
    daemon.commitment_extractor = MagicMock()
    daemon.commitment_extractor.extract.return_value = []
    daemon.commitment_extractor.extract_commitments.return_value = []
    daemon.commitment_repository = MagicMock()
    daemon.commitment_use_case = MagicMock()

    # Sensitive data detector mock
    daemon.sensitive_data_detector = MagicMock()
    daemon.sensitive_data_detector.detect.return_value = MagicMock(
        is_sensitive=False, confidence=0.0, detected_items=[]
    )

    # Cryptographer mock (pour anonymisation)
    daemon.cryptographer = MagicMock()
    mock_detection = MagicMock(is_sensitive=False)
    daemon.cryptographer.anonymize.return_value = AnonymizedResult.empty(
        original_content="", detection=mock_detection
    )

    # Configuration
    daemon.poll_interval = poll_interval
    daemon.skip_low_priority = skip_low_priority
    daemon.use_smart_routing = use_smart_routing
    daemon._running = False
    daemon._emails_processed_count = 0
    daemon._stop_event = threading.Event()
    daemon._failed_draft_counts = {}
    daemon._auto_replied_senders = set()
    daemon.api_mode = False
    daemon.event_emitter = None
    daemon.email_queue = None
    daemon.progress_notifier = None

    return daemon


@pytest.fixture
def mocked_daemon():
    """Fixture pytest pour obtenir un daemon mocké."""
    return create_mocked_daemon()
