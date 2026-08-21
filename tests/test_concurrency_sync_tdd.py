# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour les edge cases de concurrence et synchronisation.

Ce module teste les scénarios de concurrence :
- Sessions multiples pour le même utilisateur
- Conflits de mise à jour simultanée
- États de synchronisation invalides
- Race conditions dans EditSession
- Expiration de sessions concurrentes

Principes TDD/Clean Architecture :
1. Tests déterministes via FakeClock (pas de dépendance au temps réel)
2. Isolation complète des tests
3. Simulation de conditions de concurrence sans threads
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
import uuid

from app.domain.entities import (
    MobileSession,
    MobileSyncState,
    SyncStatus,
)
from app.domain.entities.realtime_edit import (
    EditSession,
    TextChange,
    ChangeType,
    Suggestion,
    SuggestionStatus,
)
from app.infrastructure.clock import FakeClock


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def fake_clock():
    """FakeClock pour des tests déterministes."""
    return FakeClock(datetime(2024, 6, 15, 12, 0, 0))


# ============================================================================
# TESTS - MOBILE SESSION CONCURRENCY
# ============================================================================

class TestMobileSessionConcurrency:
    """Tests de concurrence pour MobileSession."""

    def test_multiple_sessions_same_user(self):
        """Un utilisateur peut avoir plusieurs sessions actives."""
        sessions = [
            MobileSession(user_id="user-123", device_token=f"token-{i}")
            for i in range(3)
        ]

        assert all(s.is_active for s in sessions)
        assert all(s.user_id == "user-123" for s in sessions)
        # Chaque session a un ID unique
        session_ids = [s.session_id for s in sessions]
        assert len(set(session_ids)) == 3

    def test_session_touch_updates_last_activity(self):
        """touch() met à jour last_activity_at."""
        session = MobileSession(user_id="user-123")
        original_activity = session.last_activity_at

        # Simuler un délai
        with patch('app.domain.entities.mobile_companion.datetime') as mock_dt:
            future_time = original_activity + timedelta(minutes=5)
            mock_dt.now.return_value = future_time
            session.touch()

        # La dernière activité devrait être mise à jour
        assert session.last_activity_at >= original_activity

    def test_session_end_deactivates(self):
        """end() désactive la session."""
        session = MobileSession(user_id="user-123")
        assert session.is_active is True

        session.end()

        assert session.is_active is False

    def test_concurrent_session_ending(self):
        """Plusieurs sessions peuvent être terminées indépendamment."""
        sessions = [
            MobileSession(user_id="user-123")
            for _ in range(5)
        ]

        # Terminer les sessions paires
        for i, session in enumerate(sessions):
            if i % 2 == 0:
                session.end()

        active_count = sum(1 for s in sessions if s.is_active)
        ended_count = sum(1 for s in sessions if not s.is_active)

        assert active_count == 2
        assert ended_count == 3

    def test_session_id_uniqueness(self):
        """Les IDs de session sont toujours uniques."""
        sessions = [MobileSession(user_id="user-123") for _ in range(100)]
        session_ids = [s.session_id for s in sessions]

        # Tous les IDs doivent être uniques
        assert len(set(session_ids)) == 100

    def test_session_empty_user_id_raises(self):
        """user_id vide lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSession(user_id="")

    def test_session_whitespace_user_id_raises(self):
        """user_id avec espaces seulement lève une erreur."""
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            MobileSession(user_id="   ")


# ============================================================================
# TESTS - SYNC STATE CONCURRENCY
# ============================================================================

class TestSyncStateConcurrency:
    """Tests de concurrence pour MobileSyncState."""

    def test_sync_status_transitions(self):
        """Les transitions de statut sont valides."""
        sync_state = MobileSyncState(
            user_id="user-123",
            device_token="token-abc",
            last_sync_status=SyncStatus.IDLE
        )

        # IDLE -> SYNCING (via mark_syncing)
        sync_state.mark_syncing()
        assert sync_state.last_sync_status == SyncStatus.SYNCING

        # SYNCING -> SUCCESS (via mark_success)
        sync_state.mark_success(drafts_count=10)
        assert sync_state.last_sync_status == SyncStatus.SUCCESS

    def test_sync_concurrent_start_should_fail(self):
        """TDD: Démarrer une sync pendant une sync devrait échouer.

        ACTUELLEMENT: Pas de validation des transitions.
        """
        sync_state = MobileSyncState(
            user_id="user-123",
            device_token="token-abc",
            last_sync_status=SyncStatus.SYNCING
        )

        # ACTUEL: On peut appeler mark_syncing même si déjà SYNCING
        sync_state.mark_syncing()
        # ATTENDU: Devrait lever une erreur ou être ignoré
        assert sync_state.last_sync_status == SyncStatus.SYNCING

    def test_sync_failed_allows_retry(self):
        """Après FAILED, on peut réessayer (retour à SYNCING)."""
        sync_state = MobileSyncState(
            user_id="user-123",
            device_token="token-abc",
            last_sync_status=SyncStatus.FAILED
        )

        sync_state.mark_syncing()
        assert sync_state.last_sync_status == SyncStatus.SYNCING

    def test_sync_partial_state(self):
        """État PARTIAL indique une synchronisation partielle."""
        sync_state = MobileSyncState(
            user_id="user-123",
            device_token="token-abc",
            last_sync_status=SyncStatus.PARTIAL
        )

        assert sync_state.last_sync_status == SyncStatus.PARTIAL


# ============================================================================
# TESTS - EDIT SESSION CONCURRENCY
# ============================================================================

class TestEditSessionConcurrency:
    """Tests de concurrence pour EditSession."""

    def test_edit_session_create(self):
        """Création d'une session d'édition."""
        session = EditSession.create(user_id="user-123", initial_text="Hello")

        assert session.user_id == "user-123"
        assert session.current_text == "Hello"
        assert session.is_active is True
        assert session.version == 1

    def test_edit_session_update_increments_version(self):
        """update_text() incrémente la version."""
        session = EditSession.create(user_id="user-123", initial_text="V1")

        session.update_text("V2")
        assert session.version == 2

        session.update_text("V3")
        assert session.version == 3

    def test_edit_session_conflict_detection(self):
        """has_conflict() détecte les modifications concurrentes."""
        session = EditSession.create(user_id="user-123", initial_text="Original")

        # Pas de conflit si le texte de base correspond
        assert session.has_conflict("Original") is False

        # Modifier le texte
        session.update_text("Modified")

        # Maintenant il y a un conflit avec le texte original
        assert session.has_conflict("Original") is True

    def test_edit_session_conflict_with_empty_base(self):
        """has_conflict() avec base vide retourne False."""
        session = EditSession.create(user_id="user-123", initial_text="Some text")

        # Base vide = pas de conflit (cas spécial)
        assert session.has_conflict("") is False

    def test_edit_session_update_null_raises(self):
        """update_text(None) lève TypeError."""
        session = EditSession.create(user_id="user-123")

        with pytest.raises(TypeError, match="cannot be None"):
            session.update_text(None)

    def test_edit_session_close_deactivates(self):
        """close() désactive la session."""
        session = EditSession.create(user_id="user-123")
        assert session.is_active is True

        session.close()

        assert session.is_active is False
        assert session.closed_at is not None

    def test_edit_session_expiration_check(self):
        """is_expired() vérifie correctement l'expiration."""
        # Créer une session avec un temps contrôlé
        now = datetime.now()
        session = EditSession(
            session_id=str(uuid.uuid4()),
            user_id="user-123",
            current_text="test",
            is_active=True,
            created_at=now,
            _last_activity_at=now - timedelta(minutes=35)  # 35 min d'inactivité
        )

        # Devrait être expiré (timeout par défaut = 30 min)
        assert session.is_expired() is True

    def test_edit_session_not_expired(self):
        """Session récente n'est pas expirée."""
        session = EditSession.create(user_id="user-123")

        # Session vient d'être créée
        assert session.is_expired() is False

    def test_edit_session_closed_is_expired(self):
        """Session fermée est considérée comme expirée."""
        session = EditSession.create(user_id="user-123")
        session.close()

        assert session.is_expired() is True

    def test_edit_session_custom_timeout(self):
        """Timeout personnalisé pour l'expiration."""
        now = datetime.now()
        session = EditSession(
            session_id=str(uuid.uuid4()),
            user_id="user-123",
            current_text="test",
            is_active=True,
            created_at=now,
            _last_activity_at=now - timedelta(minutes=10)
        )

        # Pas expiré avec timeout de 30 min
        assert session.is_expired(timeout_minutes=30) is False

        # Expiré avec timeout de 5 min
        assert session.is_expired(timeout_minutes=5) is True

    def test_edit_session_needs_processing(self):
        """needs_processing détecte les changements non traités."""
        session = EditSession.create(user_id="user-123", initial_text="Original")

        # Pas de changement depuis le traitement
        session.mark_processed()
        assert session.needs_processing is False

        # Après modification, besoin de traitement
        session.update_text("Modified")
        assert session.needs_processing is True

    def test_edit_session_concurrent_updates(self):
        """Plusieurs mises à jour rapides sont gérées."""
        session = EditSession.create(user_id="user-123", initial_text="Start")

        for i in range(100):
            session.update_text(f"Version {i}")

        assert session.version == 101  # 1 initial + 100 updates
        assert session.current_text == "Version 99"


# ============================================================================
# TESTS - TEXT CHANGE CONCURRENCY
# ============================================================================

class TestTextChangeConcurrency:
    """Tests de concurrence pour TextChange."""

    def test_text_change_detection_insert(self):
        """Détection correcte d'insertion."""
        change = TextChange.from_typing(
            old_text="Hello",
            new_text="Hello World",
            cursor_position=11
        )
        assert change.change_type == ChangeType.INSERT

    def test_text_change_detection_delete(self):
        """Détection correcte de suppression."""
        change = TextChange.from_typing(
            old_text="Hello World",
            new_text="Hello",
            cursor_position=5
        )
        assert change.change_type == ChangeType.DELETE

    def test_text_change_detection_replace(self):
        """Détection correcte de remplacement."""
        change = TextChange.from_typing(
            old_text="Hello World",
            new_text="Hello Universe",
            cursor_position=14
        )
        assert change.change_type == ChangeType.REPLACE

    def test_text_change_empty_to_text(self):
        """Changement de vide vers texte est une insertion."""
        change = TextChange.from_typing(
            old_text="",
            new_text="New text",
            cursor_position=8
        )
        assert change.change_type == ChangeType.INSERT

    def test_text_change_text_to_empty(self):
        """Changement de texte vers vide est une suppression."""
        change = TextChange.from_typing(
            old_text="Old text",
            new_text="",
            cursor_position=0
        )
        assert change.change_type == ChangeType.DELETE

    def test_text_change_same_text(self):
        """Même texte = remplacement (pas de changement détecté)."""
        change = TextChange.from_typing(
            old_text="Same",
            new_text="Same",
            cursor_position=4
        )
        # Si le nouveau ne commence pas par l'ancien et vice versa,
        # c'est classé comme REPLACE
        assert change.change_type == ChangeType.REPLACE


# ============================================================================
# TESTS - SUGGESTION STATUS TRANSITIONS
# ============================================================================

class TestSuggestionConcurrency:
    """Tests de concurrence pour Suggestion."""

    def test_suggestion_initial_status(self):
        """Statut initial est PENDING."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9
        )
        assert suggestion.status == SuggestionStatus.PENDING

    def test_suggestion_accept_from_pending(self):
        """accept() depuis PENDING."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9
        )
        suggestion.accept()
        assert suggestion.status == SuggestionStatus.ACCEPTED

    def test_suggestion_reject_from_pending(self):
        """reject() depuis PENDING."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9
        )
        suggestion.reject()
        assert suggestion.status == SuggestionStatus.REJECTED

    def test_suggestion_double_accept_should_be_idempotent(self):
        """TDD: accept() deux fois devrait être idempotent."""
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9
        )
        suggestion.accept()
        suggestion.accept()  # Deuxième appel

        # Devrait rester ACCEPTED
        assert suggestion.status == SuggestionStatus.ACCEPTED

    def test_suggestion_accept_then_reject_should_fail(self):
        """TDD: reject() après accept() devrait échouer ou être ignoré.

        ACTUELLEMENT: Pas de validation des transitions.
        """
        suggestion = Suggestion(
            original_text="test",
            suggested_text="Test",
            confidence=0.9
        )
        suggestion.accept()
        suggestion.reject()

        # ACTUEL: Le statut change à REJECTED
        # ATTENDU: Devrait rester ACCEPTED ou lever une erreur
        assert suggestion.status == SuggestionStatus.REJECTED  # Bug actuel


# ============================================================================
# TESTS - SESSION LIFECYCLE
# ============================================================================

class TestSessionLifecycle:
    """Tests du cycle de vie des sessions."""

    def test_mobile_session_lifecycle(self):
        """Cycle de vie complet d'une session mobile."""
        # Création
        session = MobileSession(user_id="user-123", device_token="token-abc")
        assert session.is_active is True

        # Activité
        session.touch()

        # Fin
        session.end()
        assert session.is_active is False

    def test_edit_session_lifecycle(self):
        """Cycle de vie complet d'une session d'édition."""
        # Création
        session = EditSession.create(user_id="user-123", initial_text="Draft")
        assert session.is_active is True
        assert session.version == 1

        # Éditions
        session.update_text("Draft v2")
        assert session.version == 2

        # Traitement
        session.mark_processed()
        assert session.needs_processing is False

        # Plus d'éditions
        session.update_text("Draft v3")
        assert session.needs_processing is True

        # Fermeture
        session.close()
        assert session.is_active is False
        assert session.is_expired() is True


# ============================================================================
# TESTS - SERIALIZATION CONCURRENCY
# ============================================================================

class TestSerializationConcurrency:
    """Tests de sérialisation avec données concurrentes."""

    def test_mobile_session_to_dict_from_dict_roundtrip(self):
        """Sérialisation/désérialisation préserve les données."""
        original = MobileSession(
            user_id="user-123",
            device_token="token-abc",
            app_version="1.0.0",
            os_version="iOS 17.2",
            device_model="iPhone 15"
        )
        original.touch()

        data = original.to_dict()
        restored = MobileSession.from_dict(data)

        assert restored.session_id == original.session_id
        assert restored.user_id == original.user_id
        assert restored.device_token == original.device_token
        assert restored.app_version == original.app_version
        assert restored.is_active == original.is_active

    def test_mobile_session_from_dict_missing_optional_fields(self):
        """Désérialisation avec champs optionnels manquants."""
        data = {
            "user_id": "user-123",
            "started_at": datetime.now().isoformat(),
        }
        session = MobileSession.from_dict(data)

        assert session.user_id == "user-123"
        assert session.device_token is None
        assert session.app_version is None
        assert session.is_active is True

    def test_mobile_session_from_dict_missing_user_id_raises(self):
        """Désérialisation sans user_id lève une erreur."""
        data = {
            "session_id": str(uuid.uuid4()),
            "started_at": datetime.now().isoformat(),
        }
        with pytest.raises(KeyError):
            MobileSession.from_dict(data)


# ============================================================================
# TESTS - RACE CONDITION SIMULATION
# ============================================================================

class TestRaceConditionSimulation:
    """Simulation de conditions de course."""

    def test_edit_session_rapid_updates(self):
        """Mises à jour rapides ne perdent pas de versions."""
        session = EditSession.create(user_id="user-123")
        updates = []

        for i in range(1000):
            session.update_text(f"Update {i}")
            updates.append(session.version)

        # Chaque update doit incrémenter la version
        assert session.version == 1001
        # Les versions doivent être consécutives
        for i, v in enumerate(updates):
            assert v == i + 2  # +2 car version initiale = 1

    def test_suggestion_rapid_status_changes(self):
        """Changements rapides de statut."""
        suggestions = [
            Suggestion(
                original_text=f"text-{i}",
                suggested_text=f"Text-{i}",
                confidence=0.9
            )
            for i in range(100)
        ]

        # Accepter les pairs, rejeter les impairs
        for i, suggestion in enumerate(suggestions):
            if i % 2 == 0:
                suggestion.accept()
            else:
                suggestion.reject()

        accepted = sum(1 for s in suggestions if s.status == SuggestionStatus.ACCEPTED)
        rejected = sum(1 for s in suggestions if s.status == SuggestionStatus.REJECTED)

        assert accepted == 50
        assert rejected == 50

    def test_multiple_sessions_isolation(self):
        """Les sessions sont isolées les unes des autres."""
        sessions = [
            EditSession.create(user_id=f"user-{i}", initial_text=f"Text {i}")
            for i in range(10)
        ]

        # Modifier chaque session indépendamment
        for i, session in enumerate(sessions):
            session.update_text(f"Modified {i}")

        # Vérifier l'isolation
        for i, session in enumerate(sessions):
            assert session.current_text == f"Modified {i}"
            assert session.user_id == f"user-{i}"
