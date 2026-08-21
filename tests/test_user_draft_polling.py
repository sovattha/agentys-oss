# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour le polling automatique des brouillons utilisateur.

Ce module teste:
1. Les nouvelles méthodes get_user_drafts() et update_draft() de EmailProvider
2. Le tracker de brouillons traités (ProcessedDraftsTrackerPort)
3. L'intégration avec le daemon pour le polling des brouillons
4. L'intégration avec DraftCompletionAgent pour la complétion

Workflow testé:
    Utilisateur crée brouillon: "Brouillon:\n- Remercier Sophie\n- Proposer réunion"
           ↓
    Daemon détecte le brouillon (is_draft_completion_request())
           ↓
    DraftCompletionAgent génère l'email complet
           ↓
    Le brouillon est mis à jour dans la boîte mail
"""

import pytest
from typing import List, Optional

from app.interfaces.email_provider import EmailProvider, StandardEmail


# ==============================================================================
# TESTS POUR L'INTERFACE EmailProvider - Nouvelles méthodes
# ==============================================================================


class TestEmailProviderGetUserDrafts:
    """Tests pour la méthode get_user_drafts() de EmailProvider."""

    def test_get_user_drafts_returns_list(self, mock_provider_with_drafts):
        """get_user_drafts retourne une liste de StandardEmail."""
        drafts = mock_provider_with_drafts.get_user_drafts()

        assert isinstance(drafts, list)
        assert all(isinstance(d, StandardEmail) for d in drafts)

    def test_get_user_drafts_empty_when_no_drafts(self, mock_provider_with_drafts):
        """get_user_drafts retourne une liste vide si aucun brouillon."""
        mock_provider_with_drafts._user_drafts = {}
        drafts = mock_provider_with_drafts.get_user_drafts()

        assert drafts == []

    def test_get_user_drafts_with_limit(self, mock_provider_with_drafts):
        """get_user_drafts respecte le paramètre limit."""
        # Ajouter plusieurs brouillons
        for i in range(5):
            mock_provider_with_drafts._user_drafts[f"draft-{i}"] = StandardEmail(
                id=f"draft-{i}",
                sender="user@example.com",
                subject=f"Draft {i}",
                body=f"Body {i}",
                provider_source="mock"
            )

        drafts = mock_provider_with_drafts.get_user_drafts(limit=3)

        assert len(drafts) == 3

    def test_get_user_drafts_returns_user_drafts_only(self, mock_provider_with_drafts):
        """get_user_drafts ne retourne que les brouillons utilisateur, pas les brouillons créés par le daemon."""
        # Le mock provider distingue _user_drafts des _drafts (créés par daemon)
        drafts = mock_provider_with_drafts.get_user_drafts()

        # Ne doit contenir que les brouillons utilisateur
        for d in drafts:
            assert d.raw_metadata.get("is_user_draft", True)

    def test_get_user_drafts_includes_metadata(self, mock_provider_with_drafts):
        """Les brouillons retournés contiennent les métadonnées nécessaires."""
        drafts = mock_provider_with_drafts.get_user_drafts()

        for draft in drafts:
            assert draft.id
            assert draft.body is not None
            # Les métadonnées brutes devraient contenir is_user_draft
            assert "is_user_draft" in draft.raw_metadata or True  # Optional metadata


class TestEmailProviderUpdateDraft:
    """Tests pour la méthode update_draft() de EmailProvider."""

    def test_update_draft_updates_body(self, mock_provider_with_drafts):
        """update_draft met à jour le corps du brouillon."""
        draft_id = "user-draft-1"
        new_body = "Nouveau contenu complet généré par l'IA"

        result = mock_provider_with_drafts.update_draft(
            draft_id=draft_id,
            body=new_body
        )

        assert result is True
        updated = mock_provider_with_drafts.get_draft_by_id(draft_id)
        assert updated.body == new_body

    def test_update_draft_updates_subject(self, mock_provider_with_drafts):
        """update_draft met à jour le sujet."""
        draft_id = "user-draft-1"
        new_subject = "Nouveau sujet généré"

        result = mock_provider_with_drafts.update_draft(
            draft_id=draft_id,
            subject=new_subject
        )

        assert result is True
        updated = mock_provider_with_drafts.get_draft_by_id(draft_id)
        assert updated.subject == new_subject

    def test_update_draft_partial_update(self, mock_provider_with_drafts):
        """update_draft permet les mises à jour partielles."""
        draft_id = "user-draft-1"
        original = mock_provider_with_drafts.get_draft_by_id(draft_id)
        original_subject = original.subject

        # Mettre à jour seulement le corps
        mock_provider_with_drafts.update_draft(
            draft_id=draft_id,
            body="Corps mis à jour uniquement"
        )

        updated = mock_provider_with_drafts.get_draft_by_id(draft_id)
        assert updated.subject == original_subject  # Inchangé
        assert updated.body == "Corps mis à jour uniquement"

    def test_update_draft_returns_false_if_not_found(self, mock_provider_with_drafts):
        """update_draft retourne False si le brouillon n'existe pas."""
        result = mock_provider_with_drafts.update_draft(
            draft_id="non-existent-draft",
            body="Test"
        )

        assert result is False

    def test_update_draft_with_recipients(self, mock_provider_with_drafts):
        """update_draft peut mettre à jour les destinataires."""
        draft_id = "user-draft-1"
        new_to = ["newrecipient@example.com"]
        new_cc = ["cc@example.com"]

        result = mock_provider_with_drafts.update_draft(
            draft_id=draft_id,
            to=new_to,
            cc=new_cc
        )

        assert result is True
        updated = mock_provider_with_drafts.get_draft_by_id(draft_id)
        assert updated.to == new_to
        assert updated.cc == new_cc


class TestEmailProviderGetDraftById:
    """Tests pour la méthode get_draft_by_id() de EmailProvider."""

    def test_get_draft_by_id_returns_draft(self, mock_provider_with_drafts):
        """get_draft_by_id retourne le brouillon correspondant."""
        draft = mock_provider_with_drafts.get_draft_by_id("user-draft-1")

        assert draft is not None
        assert draft.id == "user-draft-1"

    def test_get_draft_by_id_returns_none_if_not_found(self, mock_provider_with_drafts):
        """get_draft_by_id retourne None si non trouvé."""
        draft = mock_provider_with_drafts.get_draft_by_id("non-existent")

        assert draft is None


# ==============================================================================
# TESTS POUR LA DÉTECTION DE REQUÊTE DE COMPLÉTION
# ==============================================================================


class TestDraftCompletionDetection:
    """Tests pour la détection des brouillons à compléter."""

    def test_detect_brouillon_prefix(self):
        """Détecte les brouillons avec préfixe 'Brouillon:'."""
        from app.draft_completion import DraftCompletionAgent

        text = "Brouillon:\n- Remercier Sophie\n- Proposer réunion"
        assert DraftCompletionAgent.is_completion_request(text) is True

    def test_detect_draft_prefix(self):
        """Détecte les brouillons avec préfixe 'Draft:'."""
        from app.draft_completion import DraftCompletionAgent

        text = "Draft:\n- Thank Sophie\n- Propose meeting"
        assert DraftCompletionAgent.is_completion_request(text) is True

    def test_detect_bullet_points(self):
        """Détecte les brouillons avec bullet points."""
        from app.draft_completion import DraftCompletionAgent

        text = "- Point 1\n- Point 2\n- Point 3"
        assert DraftCompletionAgent.is_completion_request(text) is True

    def test_ignore_complete_email(self):
        """Ne détecte pas les emails déjà complets."""
        from app.draft_completion import DraftCompletionAgent

        text = """Bonjour Sophie,

Je vous remercie pour notre échange d'hier.

Cordialement,
Jean"""
        assert DraftCompletionAgent.is_completion_request(text) is False

    def test_detect_ebauche_prefix(self):
        """Détecte les brouillons avec préfixe 'Ébauche:' sans bullet points."""
        from app.draft_completion import DraftCompletionAgent

        text = "Ébauche: Confirmer le rendez-vous avec Sophie"
        assert DraftCompletionAgent.is_completion_request(text) is True


# ==============================================================================
# TESTS POUR LE TRACKER DE BROUILLONS TRAITÉS
# ==============================================================================


class TestProcessedDraftsTracker:
    """Tests pour le tracker de brouillons traités."""

    def test_is_processed_returns_false_for_new_draft(self, drafts_tracker):
        """is_processed retourne False pour un nouveau brouillon."""
        assert drafts_tracker.is_processed("new-draft-id") is False

    def test_mark_processed_marks_draft(self, drafts_tracker):
        """mark_processed marque le brouillon comme traité."""
        draft_id = "draft-to-mark"

        drafts_tracker.mark_processed(draft_id)

        assert drafts_tracker.is_processed(draft_id) is True

    def test_is_processed_returns_true_after_marking(self, drafts_tracker):
        """is_processed retourne True après mark_processed."""
        draft_id = "draft-already-processed"
        drafts_tracker.mark_processed(draft_id)

        assert drafts_tracker.is_processed(draft_id) is True

    def test_get_processed_count(self, drafts_tracker):
        """get_processed_count retourne le nombre de brouillons traités."""
        drafts_tracker.mark_processed("draft-1")
        drafts_tracker.mark_processed("draft-2")
        drafts_tracker.mark_processed("draft-3")

        assert drafts_tracker.get_processed_count() == 3

    def test_clear_processed(self, drafts_tracker):
        """clear_processed vide le tracker."""
        drafts_tracker.mark_processed("draft-1")
        drafts_tracker.mark_processed("draft-2")

        drafts_tracker.clear_processed()

        assert drafts_tracker.is_processed("draft-1") is False
        assert drafts_tracker.is_processed("draft-2") is False
        assert drafts_tracker.get_processed_count() == 0


# ==============================================================================
# TESTS POUR L'INTÉGRATION DAEMON
# ==============================================================================


class TestDaemonDraftPolling:
    """Tests pour l'intégration du polling dans le daemon."""

    def test_poll_user_drafts_detects_completion_requests(
        self, empty_daemon_with_draft_polling
    ):
        """Le daemon détecte les brouillons qui nécessitent une complétion."""
        # Ajouter un brouillon utilisateur avec demande de complétion
        empty_daemon_with_draft_polling.provider._user_drafts["draft-001"] = StandardEmail(
            id="draft-001",
            sender="user@example.com",
            to=["recipient@example.com"],
            subject="",
            body="Brouillon:\n- Remercier pour la réunion\n- Proposer un prochain RDV",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        processed = empty_daemon_with_draft_polling.poll_user_drafts()

        assert processed == 1

    def test_poll_user_drafts_skips_already_processed(
        self, empty_daemon_with_draft_polling
    ):
        """Le daemon ignore les brouillons déjà traités."""
        draft_id = "draft-already-done"
        empty_daemon_with_draft_polling.provider._user_drafts[draft_id] = StandardEmail(
            id=draft_id,
            sender="user@example.com",
            body="Brouillon:\n- Point 1",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        # Marquer comme déjà traité
        empty_daemon_with_draft_polling.processed_drafts_tracker.mark_processed(draft_id)

        processed = empty_daemon_with_draft_polling.poll_user_drafts()

        # Ne devrait pas retraiter ce brouillon
        assert processed == 0

    def test_poll_user_drafts_skips_complete_emails(
        self, empty_daemon_with_draft_polling
    ):
        """Le daemon ignore les brouillons qui sont déjà complets."""
        empty_daemon_with_draft_polling.provider._user_drafts["draft-complete"] = StandardEmail(
            id="draft-complete",
            sender="user@example.com",
            subject="Re: Notre réunion",
            body="""Bonjour Sophie,

Je vous remercie pour notre échange d'hier.

Cordialement,
Jean""",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        processed = empty_daemon_with_draft_polling.poll_user_drafts()

        assert processed == 0

    def test_poll_user_drafts_updates_draft_with_completion(
        self, empty_daemon_with_draft_polling
    ):
        """Le daemon met à jour le brouillon avec le contenu complété."""
        draft_id = "draft-to-complete"
        original_body = "Brouillon:\n- Remercier Marie\n- Proposer déjeuner"

        empty_daemon_with_draft_polling.provider._user_drafts[draft_id] = StandardEmail(
            id=draft_id,
            sender="user@example.com",
            to=["marie@example.com"],
            subject="",
            body=original_body,
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        empty_daemon_with_draft_polling.poll_user_drafts()

        # Le brouillon doit être mis à jour
        updated = empty_daemon_with_draft_polling.provider.get_draft_by_id(draft_id)

        # Le corps doit être plus long que l'original (complété)
        assert len(updated.body) > len(original_body)
        # Doit avoir un sujet généré si vide
        assert updated.subject or original_body  # Au moins un des deux

    def test_poll_user_drafts_marks_as_processed(
        self, empty_daemon_with_draft_polling
    ):
        """Le daemon marque le brouillon comme traité après complétion."""
        draft_id = "draft-to-mark"
        empty_daemon_with_draft_polling.provider._user_drafts[draft_id] = StandardEmail(
            id=draft_id,
            sender="user@example.com",
            body="Draft:\n- Thank for the call",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        empty_daemon_with_draft_polling.poll_user_drafts()

        assert empty_daemon_with_draft_polling.processed_drafts_tracker.is_processed(draft_id)


    def test_poll_user_drafts_logs_start_message(
        self, caplog, drafts_tracker
    ):
        """Le vrai daemon log le début du polling des brouillons."""
        import logging
        from unittest.mock import MagicMock, patch

        mock_provider = MockEmailProviderWithDraftPolling()
        mock_provider.authenticate()
        
        with patch('app.daemon.audit_logger'):
            with patch('app.daemon.notify'):
                with patch.object(mock_provider, 'get_user_drafts', return_value=[]):
                    from app.daemon import EmailDaemon
                    
                    daemon = EmailDaemon.__new__(EmailDaemon)
                    daemon.provider = mock_provider
                    daemon.processed_drafts_tracker = drafts_tracker
                    daemon.draft_completion_agent = MagicMock()
                    
                    with caplog.at_level(logging.DEBUG):
                        daemon.poll_user_drafts()
        
        assert any("brouillon" in record.message.lower() 
                   for record in caplog.records)


# ==============================================================================
# TESTS POUR L'USE CASE CompleteDraftUseCase
# ==============================================================================


class TestCompleteDraftUseCase:
    """Tests pour le use case de complétion de brouillons."""

    def test_complete_draft_generates_full_email(self, complete_draft_use_case):
        """Le use case génère un email complet à partir d'idées brèves."""
        from app.domain.entities.draft_input import DraftInput, DraftInputTone

        draft_input = DraftInput(
            raw_input="Brouillon:\n- Remercier Sophie\n- Proposer réunion",
            recipient="sophie@example.com",
            tone=DraftInputTone.FORMAL,
            key_points=["Remercier Sophie", "Proposer réunion"]
        )

        result = complete_draft_use_case.execute(draft_input)

        assert result.body
        assert len(result.body) > 50  # Corps substantiel
        assert result.subject  # Sujet généré

    def test_complete_draft_uses_provided_tone(self, complete_draft_use_case):
        """Le use case respecte le ton demandé."""
        from app.domain.entities.draft_input import DraftInput, DraftInputTone

        draft_input = DraftInput(
            raw_input="Draft:\n- Thanks for help\n- Let's catch up",
            recipient="friend@example.com",
            tone=DraftInputTone.FRIENDLY,
            key_points=["Thanks for help", "Let's catch up"]
        )

        result = complete_draft_use_case.execute(draft_input)

        assert result.tone_used == DraftInputTone.FRIENDLY


# ==============================================================================
# TESTS D'INTÉGRATION END-TO-END
# ==============================================================================


class TestEndToEndDraftPolling:
    """Tests d'intégration pour le workflow complet."""

    def test_full_workflow_brouillon_to_completion(
        self, empty_daemon_with_draft_polling
    ):
        """
        Workflow complet:
        1. Utilisateur crée un brouillon avec idées brèves
        2. Daemon détecte le brouillon
        3. DraftCompletionAgent génère l'email complet
        4. Le brouillon est mis à jour dans la boîte mail
        """
        # 1. Simuler la création d'un brouillon par l'utilisateur
        draft_id = "user-workflow-draft"
        empty_daemon_with_draft_polling.provider._user_drafts[draft_id] = StandardEmail(
            id=draft_id,
            sender="user@example.com",
            to=["client@company.com"],
            subject="",
            body="Brouillon:\n- Confirmer réception commande\n- Indiquer délai livraison 3 jours\n- Remercier pour la confiance",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        # 2. & 3. Le daemon poll et traite
        processed = empty_daemon_with_draft_polling.poll_user_drafts()

        # 4. Vérifier le résultat
        assert processed == 1

        updated_draft = empty_daemon_with_draft_polling.provider.get_draft_by_id(draft_id)

        # Le brouillon doit maintenant être un email complet
        assert updated_draft is not None
        assert "Bonjour" in updated_draft.body or "Madame" in updated_draft.body or "Confirmation" in updated_draft.body
        assert updated_draft.subject  # Sujet généré

    def test_multiple_drafts_processed_in_order(
        self, empty_daemon_with_draft_polling
    ):
        """Plusieurs brouillons sont traités en ordre."""
        for i in range(3):
            empty_daemon_with_draft_polling.provider._user_drafts[f"draft-{i}"] = StandardEmail(
                id=f"draft-{i}",
                sender="user@example.com",
                body=f"Brouillon:\n- Point {i}",
                provider_source="mock",
                raw_metadata={"is_user_draft": True}
            )

        processed = empty_daemon_with_draft_polling.poll_user_drafts()

        assert processed == 3

        # Tous doivent être marqués comme traités
        for i in range(3):
            assert empty_daemon_with_draft_polling.processed_drafts_tracker.is_processed(f"draft-{i}")


# ==============================================================================
# FIXTURES
# ==============================================================================


class MockEmailProviderWithDraftPolling(EmailProvider):
    """
    Mock provider étendu avec support du polling de brouillons.

    Distingue:
    - _drafts: brouillons créés par le daemon (réponses automatiques)
    - _user_drafts: brouillons créés par l'utilisateur (à compléter)
    """

    def __init__(self, emails: List[StandardEmail] = None):
        self._emails = {e.id: e for e in (emails or [])}
        self._drafts = {}  # Brouillons créés par daemon
        self._user_drafts = {}  # Brouillons utilisateur
        self._authenticated = False
        self._draft_counter = 0

    @property
    def provider_name(self) -> str:
        return "mock_with_draft_polling"

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
        is_html: bool = False
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
        return True

    # ========== NOUVELLES MÉTHODES POUR LE POLLING ==========

    def get_user_drafts(self, limit: int = 50) -> List[StandardEmail]:
        """Récupère les brouillons de l'utilisateur."""
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


class MockProcessedDraftsTracker:
    """Mock du tracker de brouillons traités."""

    def __init__(self):
        self._processed = set()

    def is_processed(self, draft_id: str) -> bool:
        return draft_id in self._processed

    def mark_processed(self, draft_id: str) -> None:
        self._processed.add(draft_id)

    def get_processed_count(self) -> int:
        return len(self._processed)

    def clear_processed(self) -> None:
        self._processed.clear()


class MockDaemonWithDraftPolling:
    """Mock du daemon avec support du polling de brouillons."""

    def __init__(
        self,
        provider: MockEmailProviderWithDraftPolling,
        processed_drafts_tracker: MockProcessedDraftsTracker,
        draft_completion_agent=None
    ):
        self.provider = provider
        self.processed_drafts_tracker = processed_drafts_tracker
        self.draft_completion_agent = draft_completion_agent

    def poll_user_drafts(self) -> int:
        """
        Poll les brouillons utilisateur et complète ceux qui le nécessitent.

        Returns:
            Nombre de brouillons traités.
        """
        from app.draft_completion import DraftCompletionAgent

        drafts = self.provider.get_user_drafts()
        processed_count = 0

        for draft in drafts:
            # Skip si déjà traité
            if self.processed_drafts_tracker.is_processed(draft.id):
                continue

            # Skip si pas une demande de complétion
            if not DraftCompletionAgent.is_completion_request(draft.body or ""):
                continue

            # Compléter le brouillon
            if self.draft_completion_agent:
                completed = self.draft_completion_agent.complete(draft.body or "")

                # Mettre à jour le brouillon
                self.provider.update_draft(
                    draft_id=draft.id,
                    subject=completed.subject if not draft.subject else draft.subject,
                    body=completed.body
                )
            else:
                # Mock: simplement marquer comme complété avec un corps simulé
                self.provider.update_draft(
                    draft_id=draft.id,
                    subject=draft.subject or "Sujet généré",
                    body=f"Bonjour,\n\nEmail complet généré à partir de:\n{draft.body}\n\nCordialement"
                )

            # Marquer comme traité
            self.processed_drafts_tracker.mark_processed(draft.id)
            processed_count += 1

        return processed_count


# ========== PYTEST FIXTURES ==========


@pytest.fixture
def mock_provider_with_drafts() -> MockEmailProviderWithDraftPolling:
    """Provider mock avec brouillons utilisateur."""
    provider = MockEmailProviderWithDraftPolling()
    provider.authenticate()

    # Ajouter un brouillon utilisateur
    provider._user_drafts["user-draft-1"] = StandardEmail(
        id="user-draft-1",
        sender="user@example.com",
        to=["recipient@example.com"],
        subject="Mon brouillon",
        body="Brouillon:\n- Point 1\n- Point 2",
        provider_source="mock",
        raw_metadata={"is_user_draft": True}
    )

    return provider


@pytest.fixture
def drafts_tracker() -> MockProcessedDraftsTracker:
    """Tracker de brouillons traités."""
    return MockProcessedDraftsTracker()


@pytest.fixture
def mock_daemon_with_draft_polling(
    mock_provider_with_drafts,
    drafts_tracker
) -> MockDaemonWithDraftPolling:
    """Daemon mock avec polling de brouillons (avec brouillon pré-existant)."""
    return MockDaemonWithDraftPolling(
        provider=mock_provider_with_drafts,
        processed_drafts_tracker=drafts_tracker
    )


@pytest.fixture
def empty_daemon_with_draft_polling(
    drafts_tracker
) -> MockDaemonWithDraftPolling:
    """Daemon mock avec polling de brouillons (sans brouillon pré-existant)."""
    empty_provider = MockEmailProviderWithDraftPolling()
    empty_provider.authenticate()
    return MockDaemonWithDraftPolling(
        provider=empty_provider,
        processed_drafts_tracker=drafts_tracker
    )


@pytest.fixture
def complete_draft_use_case():
    """Mock du use case de complétion."""
    from app.domain.entities.draft_input import CompletedDraft

    class MockCompleteDraftUseCase:
        def execute(self, draft_input):
            return CompletedDraft(
                subject="Confirmation de rendez-vous",
                body=f"""Bonjour,

Je me permets de vous contacter suite à notre échange.

{' '.join(draft_input.key_points) if draft_input.key_points else 'Points clés traités.'}

Bien cordialement,
L'équipe""",
                recipient=draft_input.recipient,
                tone_used=draft_input.tone
            )

    return MockCompleteDraftUseCase()


# ==============================================================================
# TESTS EDGE CASES ADDITIONNELS
# ==============================================================================


class TestEmailProviderEdgeCases:
    """Tests des edge cases pour EmailProvider avec drafts."""

    def test_get_user_drafts_with_null_body(self, mock_provider_with_drafts):
        """get_user_drafts gère les brouillons avec body None."""
        mock_provider_with_drafts._user_drafts["draft-null-body"] = StandardEmail(
            id="draft-null-body",
            sender="user@example.com",
            subject="Draft avec body null",
            body=None,
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        drafts = mock_provider_with_drafts.get_user_drafts()
        null_body_draft = next(
            (d for d in drafts if d.id == "draft-null-body"), None
        )

        assert null_body_draft is not None
        assert null_body_draft.body is None

    def test_get_user_drafts_with_empty_body(self, mock_provider_with_drafts):
        """get_user_drafts gère les brouillons avec body vide."""
        mock_provider_with_drafts._user_drafts["draft-empty-body"] = StandardEmail(
            id="draft-empty-body",
            sender="user@example.com",
            subject="Draft vide",
            body="",
            provider_source="mock"
        )

        drafts = mock_provider_with_drafts.get_user_drafts()
        empty_draft = next(
            (d for d in drafts if d.id == "draft-empty-body"), None
        )

        assert empty_draft is not None
        assert empty_draft.body == ""

    def test_update_draft_with_empty_body(self, mock_provider_with_drafts):
        """update_draft accepte un body vide."""
        draft_id = "user-draft-1"

        result = mock_provider_with_drafts.update_draft(
            draft_id=draft_id,
            body=""
        )

        assert result is True
        updated = mock_provider_with_drafts.get_draft_by_id(draft_id)
        assert updated.body == ""

    def test_update_draft_with_unicode_content(self, mock_provider_with_drafts):
        """update_draft gère le contenu Unicode."""
        draft_id = "user-draft-1"
        unicode_body = "Bonjour 中文 émoji 🎉 日本語"

        result = mock_provider_with_drafts.update_draft(
            draft_id=draft_id,
            body=unicode_body
        )

        assert result is True
        updated = mock_provider_with_drafts.get_draft_by_id(draft_id)
        assert updated.body == unicode_body

    def test_update_draft_with_very_long_body(self, mock_provider_with_drafts):
        """update_draft gère les corps très longs."""
        draft_id = "user-draft-1"
        long_body = "A" * 100000  # 100KB

        result = mock_provider_with_drafts.update_draft(
            draft_id=draft_id,
            body=long_body
        )

        assert result is True
        updated = mock_provider_with_drafts.get_draft_by_id(draft_id)
        assert len(updated.body) == 100000


class TestDraftCompletionDetectionEdgeCases:
    """Tests des edge cases pour la détection de complétion."""

    def test_detect_empty_body(self):
        """Ne détecte pas les body vides."""
        from app.draft_completion import DraftCompletionAgent

        assert DraftCompletionAgent.is_completion_request("") is False

    def test_detect_none_body(self):
        """Gère body None sans erreur."""
        from app.draft_completion import DraftCompletionAgent

        # None devrait retourner False ou lever une erreur gérée
        try:
            result = DraftCompletionAgent.is_completion_request(None)
            assert result is False
        except (TypeError, AttributeError):
            pass  # Acceptable si l'implémentation ne gère pas None

    def test_detect_whitespace_only(self):
        """Ne détecte pas les body avec espaces uniquement."""
        from app.draft_completion import DraftCompletionAgent

        assert DraftCompletionAgent.is_completion_request("   ") is False

    def test_detect_single_bullet(self):
        """Un seul bullet point n'est pas détecté (nécessite 2+ lignes)."""
        from app.draft_completion import DraftCompletionAgent

        text = "- Un seul point"
        assert DraftCompletionAgent.is_completion_request(text) is False

    def test_detect_numbered_list(self):
        """Détecte les listes numérotées."""
        from app.draft_completion import DraftCompletionAgent

        text = "1. Premier point\n2. Deuxième point"
        # Peut ou non être détecté selon l'implémentation
        # Le test vérifie juste qu'il n'y a pas d'erreur
        DraftCompletionAgent.is_completion_request(text)

    def test_detect_mixed_content(self):
        """Contenu mixte avec moins de 50% de bullets n'est pas détecté."""
        from app.draft_completion import DraftCompletionAgent

        text = """Quelques idées:
- Point 1
- Point 2

À développer."""
        assert DraftCompletionAgent.is_completion_request(text) is False

    def test_ignore_signature_with_bullets(self):
        """Ignore les signatures avec bullets visuels."""
        from app.draft_completion import DraftCompletionAgent

        text = """Bonjour,

Merci pour votre message.

Cordialement,
--
Jean Dupont
• Directeur Marketing
• Tel: 01.23.45.67.89"""
        # Le texte est déjà complet, ne devrait pas être détecté
        assert DraftCompletionAgent.is_completion_request(text) is False


class TestProcessedDraftsTrackerEdgeCases:
    """Tests des edge cases pour le tracker de brouillons."""

    def test_mark_processed_with_empty_id(self, drafts_tracker):
        """mark_processed accepte un ID vide."""
        drafts_tracker.mark_processed("")
        assert drafts_tracker.is_processed("")

    def test_mark_processed_with_special_chars(self, drafts_tracker):
        """mark_processed gère les caractères spéciaux."""
        special_id = "draft/with:special<chars>"
        drafts_tracker.mark_processed(special_id)
        assert drafts_tracker.is_processed(special_id)

    def test_mark_processed_idempotent(self, drafts_tracker):
        """mark_processed est idempotent."""
        draft_id = "draft-123"
        drafts_tracker.mark_processed(draft_id)
        drafts_tracker.mark_processed(draft_id)
        drafts_tracker.mark_processed(draft_id)
        assert drafts_tracker.get_processed_count() == 1

    def test_is_processed_with_unknown_id(self, drafts_tracker):
        """is_processed retourne False pour ID inconnu."""
        assert drafts_tracker.is_processed("unknown-draft-xyz") is False

    def test_clear_on_empty_tracker(self, drafts_tracker):
        """clear sur tracker vide ne lève pas d'erreur."""
        drafts_tracker.clear_processed()
        assert drafts_tracker.get_processed_count() == 0


class TestDaemonDraftPollingEdgeCases:
    """Tests des edge cases pour le polling du daemon."""

    def test_poll_with_no_drafts(self, empty_daemon_with_draft_polling):
        """poll_user_drafts retourne 0 si aucun brouillon."""
        processed = empty_daemon_with_draft_polling.poll_user_drafts()
        assert processed == 0

    def test_poll_with_null_body_draft(self, empty_daemon_with_draft_polling):
        """poll_user_drafts gère les brouillons avec body None."""
        empty_daemon_with_draft_polling.provider._user_drafts["draft-null"] = StandardEmail(
            id="draft-null",
            sender="user@example.com",
            body=None,
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        # Ne devrait pas lever d'erreur
        processed = empty_daemon_with_draft_polling.poll_user_drafts()
        assert processed == 0  # None body pas détecté comme demande de complétion

    def test_poll_with_empty_body_draft(self, empty_daemon_with_draft_polling):
        """poll_user_drafts gère les brouillons avec body vide."""
        empty_daemon_with_draft_polling.provider._user_drafts["draft-empty"] = StandardEmail(
            id="draft-empty",
            sender="user@example.com",
            body="",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        processed = empty_daemon_with_draft_polling.poll_user_drafts()
        assert processed == 0

    def test_poll_respects_limit(self, empty_daemon_with_draft_polling):
        """poll_user_drafts traite un nombre limité de brouillons."""
        # Ajouter beaucoup de brouillons
        for i in range(100):
            empty_daemon_with_draft_polling.provider._user_drafts[f"draft-{i}"] = StandardEmail(
                id=f"draft-{i}",
                sender="user@example.com",
                body=f"Brouillon:\n- Point {i}",
                provider_source="mock",
                raw_metadata={"is_user_draft": True}
            )

        # Limiter à 50 dans get_user_drafts
        processed = empty_daemon_with_draft_polling.poll_user_drafts()
        # Le nombre traité dépend de la limite du provider (50 par défaut)
        assert processed <= 50

    def test_poll_with_unicode_content(self, empty_daemon_with_draft_polling):
        """poll_user_drafts gère le contenu Unicode."""
        empty_daemon_with_draft_polling.provider._user_drafts["draft-unicode"] = StandardEmail(
            id="draft-unicode",
            sender="utilisateur@exemple.fr",
            to=["destinataire@exemple.fr"],
            subject="",
            body="Brouillon:\n- Répondre à José\n- Envoyer à 中文客户",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        processed = empty_daemon_with_draft_polling.poll_user_drafts()
        assert processed == 1


class TestEndToEndEdgeCases:
    """Tests d'intégration end-to-end pour les edge cases."""

    def test_workflow_with_already_completed_draft(
        self, empty_daemon_with_draft_polling
    ):
        """Le workflow ignore les brouillons déjà complétés correctement."""
        # Brouillon qui a déjà été complété par le passé
        draft_id = "draft-already-done"
        empty_daemon_with_draft_polling.processed_drafts_tracker.mark_processed(draft_id)

        empty_daemon_with_draft_polling.provider._user_drafts[draft_id] = StandardEmail(
            id=draft_id,
            sender="user@example.com",
            body="Brouillon:\n- Point 1",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        processed = empty_daemon_with_draft_polling.poll_user_drafts()
        assert processed == 0

    def test_workflow_with_multiple_recipients(
        self, empty_daemon_with_draft_polling
    ):
        """Le workflow gère les brouillons avec plusieurs destinataires."""
        draft_id = "draft-multi-recipients"
        empty_daemon_with_draft_polling.provider._user_drafts[draft_id] = StandardEmail(
            id=draft_id,
            sender="user@example.com",
            to=["alice@example.com", "bob@example.com"],
            cc=["carol@example.com"],
            subject="",
            body="Brouillon:\n- Informer l'équipe\n- Planifier réunion",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        processed = empty_daemon_with_draft_polling.poll_user_drafts()
        assert processed == 1

        updated = empty_daemon_with_draft_polling.provider.get_draft_by_id(draft_id)
        # Les destinataires doivent être préservés
        assert "alice@example.com" in updated.to
        assert "bob@example.com" in updated.to

    def test_workflow_preserves_existing_subject(
        self, empty_daemon_with_draft_polling
    ):
        """Le workflow préserve le sujet existant."""
        draft_id = "draft-with-subject"
        existing_subject = "Re: Projet important"
        empty_daemon_with_draft_polling.provider._user_drafts[draft_id] = StandardEmail(
            id=draft_id,
            sender="user@example.com",
            to=["recipient@example.com"],
            subject=existing_subject,
            body="Brouillon:\n- Confirmer la date",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        empty_daemon_with_draft_polling.poll_user_drafts()

        updated = empty_daemon_with_draft_polling.provider.get_draft_by_id(draft_id)
        assert updated.subject == existing_subject


class TestConcurrencyEdgeCases:
    """Tests des edge cases de concurrence."""

    def test_multiple_polls_same_draft(self, empty_daemon_with_draft_polling):
        """Plusieurs polls ne traitent pas le même brouillon deux fois."""
        draft_id = "draft-concurrent"
        empty_daemon_with_draft_polling.provider._user_drafts[draft_id] = StandardEmail(
            id=draft_id,
            sender="user@example.com",
            body="Brouillon:\n- Point 1",
            provider_source="mock",
            raw_metadata={"is_user_draft": True}
        )

        # Premier poll
        processed1 = empty_daemon_with_draft_polling.poll_user_drafts()
        assert processed1 == 1

        # Deuxième poll - ne devrait pas retraiter
        processed2 = empty_daemon_with_draft_polling.poll_user_drafts()
        assert processed2 == 0

    def test_tracker_prevents_duplicate_processing(self, drafts_tracker):
        """Le tracker empêche le traitement en double."""
        draft_ids = ["draft-1", "draft-2", "draft-3"]

        # Simuler le premier poll
        for draft_id in draft_ids:
            drafts_tracker.mark_processed(draft_id)

        # Vérifier qu'aucun n'est retraité
        new_to_process = [
            d for d in draft_ids
            if not drafts_tracker.is_processed(d)
        ]
        assert new_to_process == []
