# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour la détection d'un action abandonné après `max_retry_attempts` épuisé
(silent-failure fix, issue #319).

L'action queue loguait `error` sur un échec d'action et incrémentait simplement
`retry_count`. Quand `retry_count >= max_retry_attempts`, l'action restait
`status='failed'` en DB mais aucune notification n'était émise — le frontend
optimiste affichait « archivé » pour un email qui était toujours dans Gmail.

Ce test valide l'ajout du callback `on_action_permanently_failed`, invoqué
exactement quand une action atteint le plafond de retries.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock


from app.services.action_queue import ActionQueue


def _make_action(action_id: int, retry_count: int) -> SimpleNamespace:
    """Fabrique un objet 'action-like' qui accepte les assignments attendus par _process_action."""
    return SimpleNamespace(
        id=action_id,
        retry_count=retry_count,
        status="pending",
        error_message=None,
        processed_at=None,
        action_type="mark_read",
        email_id="email_abc",
    )


class TestActionPermanentFailureCallback:
    """Issue #319 : quand `retry_count` atteint `max_retry_attempts` après un
    nouvel échec, le callback `on_action_permanently_failed` doit être invoqué
    avec l'action — permet au caller de wire un `socketio.emit()` visible côté UI.
    """

    def test_callback_invoked_when_max_retries_reached(self):
        """RED gate : après l'échec qui fait passer retry_count de 1 → 2 avec
        max_retry_attempts=2, le callback doit être appelé exactement une fois.
        """
        perm_failed: list = []
        queue = ActionQueue(
            max_retry_attempts=2,
            on_action_permanently_failed=lambda a: perm_failed.append(a),
        )
        action = _make_action(action_id=42, retry_count=1)  # après +1 → 2 == max
        session = MagicMock()

        def executor_fails(_a):
            return False

        queue._process_action(action, executor_fails, session)

        assert action.retry_count == 2, "Le retry_count doit avoir été incrémenté"
        assert len(perm_failed) == 1, (
            "on_action_permanently_failed doit être appelé quand retry_count atteint le plafond"
        )
        assert perm_failed[0] is action

    def test_callback_not_invoked_before_max_retries(self):
        """Contre-test : avec 2 retries restants, le callback ne se déclenche pas."""
        perm_failed: list = []
        queue = ActionQueue(
            max_retry_attempts=3,
            on_action_permanently_failed=lambda a: perm_failed.append(a),
        )
        action = _make_action(action_id=99, retry_count=0)  # après +1 → 1 < 3
        session = MagicMock()

        queue._process_action(action, lambda a: False, session)

        assert action.retry_count == 1
        assert perm_failed == []

    def test_callback_invoked_on_executor_exception_when_max_reached(self):
        """Même comportement quand l'executor lève une exception (pas juste False)."""
        perm_failed: list = []
        queue = ActionQueue(
            max_retry_attempts=2,
            on_action_permanently_failed=lambda a: perm_failed.append(a),
        )
        action = _make_action(action_id=7, retry_count=1)
        session = MagicMock()

        def executor_raises(_a):
            raise RuntimeError("Gmail API 503")

        result = queue._process_action(action, executor_raises, session)

        assert result is False
        assert action.retry_count == 2
        assert len(perm_failed) == 1
        assert "Gmail API 503" in (action.error_message or "")

    def test_no_callback_when_constructor_arg_omitted(self):
        """Retro-compat : si on ne passe pas le callback, aucun crash."""
        queue = ActionQueue(max_retry_attempts=1)
        action = _make_action(action_id=1, retry_count=0)
        session = MagicMock()
        # Ne doit pas raise
        queue._process_action(action, lambda a: False, session)
        assert action.retry_count == 1
