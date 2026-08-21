# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'isolation multi-utilisateur dans les routes calendrier.

Vérifie que les endpoints calendrier (calendar_routes.py, calendar.py)
ne retournent que les données du user authentifié, et refusent l'accès
aux comptes d'un autre user.

Pattern suivi : tests/test_multi_user_isolation.py

pytest tests/test_calendar_user_isolation.py -v
"""

import pytest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.app import create_app
from app.multi_accounts import AccountConfig


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def app():
    """Crée une instance de l'application Flask pour les tests."""
    app = create_app({"TESTING": True})
    return app


@pytest.fixture
def client(app):
    """Client de test sans JWT (mode Tauri desktop)."""
    return app.test_client()


def _make_account(account_id: str, email: str, user_id=None, provider="gmail"):
    """Crée un AccountConfig pour les tests."""
    return AccountConfig(
        id=account_id,
        name=f"Test {email}",
        email=email,
        provider=provider,
        user_id=user_id,
    )


@contextmanager
def _patch_calendar_handler_globals(client, **values):
    """Patch les globals du handler Flask réellement enregistré.

    En full-suite, des imports/reloads de Flask peuvent rendre un patch string
    sur ``app.api.calendar`` trop fragile. Les assertions ici concernent les
    handlers HTTP, donc on patch la fonction que Flask va appeler.
    """
    endpoint_globals = {
        "calendar.list_followups": client.application.view_functions[
            "calendar.list_followups"
        ].__globals__,
        "calendar.update_followup": client.application.view_functions[
            "calendar.update_followup"
        ].__globals__,
        "calendar.delete_followup": client.application.view_functions[
            "calendar.delete_followup"
        ].__globals__,
        "calendar.list_suggestions": client.application.view_functions[
            "calendar.list_suggestions"
        ].__globals__,
        "calendar.accept_suggestion": client.application.view_functions[
            "calendar.accept_suggestion"
        ].__globals__,
        "calendar.reject_suggestion": client.application.view_functions[
            "calendar.reject_suggestion"
        ].__globals__,
    }
    globals_by_id = {id(globals_dict): globals_dict for globals_dict in endpoint_globals.values()}
    missing = object()
    originals = []
    for globals_dict in globals_by_id.values():
        for name, value in values.items():
            originals.append((globals_dict, name, globals_dict.get(name, missing)))
            globals_dict[name] = value
    try:
        yield
    finally:
        for globals_dict, name, original in reversed(originals):
            if original is missing:
                globals_dict.pop(name, None)
            else:
                globals_dict[name] = original


# ============================================================================
# 1. _get_active_account_id — calendar_routes.py
# ============================================================================


class TestGetActiveAccountId:
    """Tests pour _get_active_account_id() dans calendar_routes.py."""

    def test_returns_current_user_account(self, app):
        """Doit retourner le compte du user courant, pas le global."""
        user_a_account = _make_account("acc-a", "a@test.com", user_id=1)
        _make_account("acc-b", "b@test.com", user_id=2)

        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 1, "email": "a@test.com"}

            with patch("app.api.calendar_routes.get_account_manager") as mock_mgr:
                manager = MagicMock()
                # get_current_for_user(1) should return user A's account
                manager.get_current_for_user.return_value = "acc-a"
                manager.get_account.return_value = user_a_account
                mock_mgr.return_value = manager

                from app.api.calendar_routes import _get_active_account_id
                result = _get_active_account_id()

                assert result == "acc-a"
                manager.get_current_for_user.assert_called()

    def test_fallback_filters_by_ownership(self, app):
        """Le fallback get_all_accounts doit filtrer par ownership."""
        user_a_account = _make_account("acc-a", "a@test.com", user_id=1)
        user_b_account = _make_account("acc-b", "b@test.com", user_id=2)

        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 1, "email": "a@test.com"}

            with patch("app.api.calendar_routes.get_account_manager") as mock_mgr:
                manager = MagicMock()
                manager.get_current_for_user.return_value = None
                manager.get_account.return_value = None
                # User B's account is FIRST — without ownership filtering,
                # the code would return acc-b (wrong user)
                manager.get_all_accounts.return_value = [user_b_account, user_a_account]
                mock_mgr.return_value = manager

                with patch("app.api.calendar_routes.supports_calendar", return_value=True):
                    from app.api.calendar_routes import _get_active_account_id
                    result = _get_active_account_id()

                    # Should return user A's account, NOT user B's
                    assert result == "acc-a"

    def test_fallback_resolves_jwt_db_account_to_oauth_hash(self, app):
        """Sans current AccountManager, le JWT peut résoudre le compte DB actif."""
        db_account = SimpleNamespace(
            id=4,
            email="a@test.com",
            provider="gmail",
            is_active=True,
            user_id=1,
        )
        oauth_account = _make_account("hash-a", "a@test.com", user_id=1)

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeRepo:
            def __init__(self, session):
                self.session = session

            def get_by_email(self, email):
                return db_account if email == "a@test.com" else None

            def get(self, account_id):
                return db_account if account_id == 4 else None

        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 1, "email": "a@test.com"}

            with patch("app.api.routes_helpers.get_db_session", return_value=FakeSession()), \
                 patch("app.db.repositories.account_repository.AccountRepository", FakeRepo), \
                 patch("app.api.calendar_routes.get_account_manager") as mock_mgr:
                manager = MagicMock()
                manager.get_current_for_user.return_value = None
                manager.get_account.return_value = None
                manager.get_all_accounts.return_value = []
                manager.get_account_by_email.return_value = oauth_account
                mock_mgr.return_value = manager

                from app.api.calendar_routes import _get_active_account_id
                result = _get_active_account_id()

                assert result == "hash-a"


# ============================================================================
# 2. _resolve_account_id — calendar_routes.py
# ============================================================================


class TestResolveAccountId:
    """Tests pour _resolve_account_id() dans calendar_routes.py."""

    def test_numeric_db_account_id_resolves_to_owned_oauth_hash(self, app):
        """Un ID DB numérique venant du frontend doit mapper vers l'ID OAuth."""
        db_account = SimpleNamespace(
            id=4,
            email="a@test.com",
            provider="gmail",
            user_id=1,
        )
        oauth_account = _make_account("hash-a", "a@test.com", user_id=1)

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeRepo:
            def __init__(self, session):
                self.session = session

            def get(self, account_id):
                return db_account if account_id == 4 else None

        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 1, "email": "a@test.com"}

            with patch("app.api.routes_helpers.get_db_session", return_value=FakeSession()), \
                 patch("app.db.repositories.account_repository.AccountRepository", FakeRepo), \
                 patch("app.api.calendar_routes.get_account_manager") as mock_mgr:
                manager = MagicMock()
                manager.get_current_for_user.return_value = None
                manager.get_account_by_email.return_value = oauth_account
                mock_mgr.return_value = manager

                from app.api.calendar_routes import _resolve_account_id
                result = _resolve_account_id("4")

                assert result == "hash-a"

    def test_rejects_other_users_account(self, app):
        """Doit refuser un account_id explicite qui ne lui appartient pas."""
        other_account = _make_account("acc-b", "b@test.com", user_id=2)

        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 1, "email": "a@test.com"}

            with patch("app.api.calendar_routes.get_account_manager") as mock_mgr:
                manager = MagicMock()
                manager.get_account.return_value = other_account
                mock_mgr.return_value = manager

                from app.api.calendar_routes import _resolve_account_id
                result = _resolve_account_id("acc-b")

                # Should return None (rejected), not "acc-b"
                assert result is None

    def test_numeric_stale_account_id_does_not_fallback_to_active_account(self, app):
        """Un ID DB numérique explicite mais stale doit rester rejeté.

        Pré-fix, ``account_id=13`` tombait sur le compte actif et retournait
        200, ce qui masquait les onglets frontend qui envoyaient un ancien ID.
        """
        with app.test_request_context():
            from app.api.calendar_routes import _resolve_account_id

            with patch("app.api.calendar_routes._resolve_numeric_db_account_id", return_value=None) as resolve_numeric, \
                 patch("app.api.calendar_routes._get_active_account_id", return_value="hash-active") as get_active:
                result = _resolve_account_id("13")

                assert result is None
                resolve_numeric.assert_called_once_with("13")
                get_active.assert_not_called()


# ============================================================================
# 2bis. Regression: F-01 (2026-05-17 deep-audit) — /api/calendar/events must
# route the raw account_id through _resolve_account_id (validates ownership),
# not the previous `_raw_aid or _active_aid` short-circuit which let any
# authenticated user read any other user's calendar with one HTTP call.
# ============================================================================


class TestGetEventsOwnershipGuard:
    """Regression for the F-01 cross-tenant calendar exfil."""

    def test_get_events_routes_account_id_through_resolver(self, app, client):
        """``get_events`` must use ``_resolve_account_id`` (ownership-validated)
        not the bypass ``_raw_aid or _active_aid`` it had pre-F-01.

        When ``_resolve_account_id`` returns None (ownership rejected), the
        route MUST short-circuit to the 400 "No OAuth account found" branch
        instead of reaching ``create_calendar_provider`` with the rejected id.
        """
        resolve_calls: list[str | None] = []

        def fake_resolve(raw_id):
            resolve_calls.append(raw_id)
            return None  # ownership rejected

        provider_calls: list[str] = []

        def fake_provider(account_id):
            provider_calls.append(account_id)
            return MagicMock()

        with patch("app.api.calendar_routes._resolve_account_id", side_effect=fake_resolve), \
             patch("app.api.calendar_routes.create_calendar_provider", side_effect=fake_provider):
            resp = client.get("/api/calendar/events?account_id=acc-b")

        # The resolver MUST have been called with the raw query-arg id.
        assert resolve_calls == ["acc-b"], (
            "get_events must hand the raw account_id to _resolve_account_id; "
            "F-01 regression — the previous code bypassed the validator."
        )
        # When the resolver returns None we must hit the 400 branch and
        # NEVER call create_calendar_provider with the rejected id.
        assert resp.status_code == 400
        assert provider_calls == [], (
            "create_calendar_provider was called despite ownership rejection — "
            "F-01 regression — get_events leaked the rejected account_id "
            "downstream to the provider factory."
        )


# ============================================================================
# 3. _get_current_account_id — calendar.py
# ============================================================================


class TestGetCurrentAccountIdCalendar:
    """Tests pour _get_current_account_id() dans calendar.py."""

    def test_returns_user_account(self, app):
        """Doit retourner le compte du user courant via get_current_for_user."""
        user_account = _make_account("acc-a", "a@test.com", user_id=1)

        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 1, "email": "a@test.com"}

            with patch("app.api.calendar.get_account_manager") as mock_mgr:
                manager = MagicMock()
                manager.get_current_for_user.return_value = "acc-a"
                manager.get_account.return_value = user_account
                mock_mgr.return_value = manager

                from app.api.calendar import _get_current_account_id
                result = _get_current_account_id()

                assert result == "acc-a"
                manager.get_current_for_user.assert_called()


# ============================================================================
# 4. Followups — isolation par user
# ============================================================================


class _FakeFollowupStore:
    """Double du store DB (migration 041) au contrat records utilisé par les
    routes — garde ces tests d'isolation unitaires (pas de DB)."""

    def __init__(self, records: dict):
        self._records = dict(records)

    def records_for_account(self, account_id):
        return [
            (fid, rec) for fid, rec in self._records.items()
            if rec.get("account_id") == account_id
        ]

    def all_records(self):
        return list(self._records.items())

    def get_record(self, followup_id):
        return self._records.get(followup_id)

    def save_record(self, followup_id, record):
        self._records[followup_id] = record

    def delete_record(self, followup_id):
        return self._records.pop(followup_id, None) is not None

    def wake_snoozed(self, now=None):
        return 0


class TestFollowupIsolation:
    """Tests pour l'isolation des followups entre users."""

    def test_list_followups_only_shows_own(self, app, client):
        """list_followups ne doit retourner que les followups du user courant."""
        manager = MagicMock()
        acc_a = _make_account("acc-a", "a@test.com", user_id=1)
        acc_b = _make_account("acc-b", "b@test.com", user_id=2)
        manager.get_account.side_effect = lambda aid: acc_a if aid == "acc-a" else acc_b

        with _patch_calendar_handler_globals(
            client,
            _get_current_account_id=lambda: "acc-a",
            _wake_snoozed_followups=lambda: None,
            _fu_store=_FakeFollowupStore({
                "f1": {"account_id": "acc-a", "status": "pending", "due_date": "2026-01-01"},
                "f2": {"account_id": "acc-b", "status": "pending", "due_date": "2026-01-02"},
            }),
            get_auth_user_id=lambda: 1,
            get_account_manager=lambda: manager,
        ):
            resp = client.get("/api/calendar/followups")
            data = resp.get_json()

        followup_ids = [f["id"] for f in data.get("followups", [])]
        assert "f1" in followup_ids
        assert "f2" not in followup_ids

    def test_update_followup_rejects_other_user(self, app, client):
        """PATCH followup doit refuser si le followup appartient à un autre user."""
        manager = MagicMock()
        acc_b = _make_account("acc-b", "b@test.com", user_id=2)
        manager.get_account.return_value = acc_b

        with _patch_calendar_handler_globals(
            client,
            _fu_store=_FakeFollowupStore({
                "f1": {"account_id": "acc-b", "status": "pending", "due_date": "2026-01-01"},
            }),
            get_auth_user_id=lambda: 1,
            get_account_manager=lambda: manager,
        ):
            resp = client.patch(
                "/api/calendar/followups/f1",
                json={"action": "complete"},
                content_type="application/json",
            )
        assert resp.status_code == 403

    def test_delete_followup_rejects_other_user(self, app, client):
        """DELETE followup doit refuser si le followup appartient à un autre user."""
        manager = MagicMock()
        acc_b = _make_account("acc-b", "b@test.com", user_id=2)
        manager.get_account.return_value = acc_b

        with _patch_calendar_handler_globals(
            client,
            _fu_store=_FakeFollowupStore({
                "f1": {"account_id": "acc-b", "status": "pending", "due_date": "2026-01-01"},
            }),
            get_auth_user_id=lambda: 1,
            get_account_manager=lambda: manager,
        ):
            resp = client.delete("/api/calendar/followups/f1")
        assert resp.status_code == 403


# ============================================================================
# 5. Suggestions — isolation par user
# ============================================================================


class _FakeSuggestionStore:
    """Double du store DB des suggestions (migration 042) — contrat records."""

    def __init__(self, records: dict):
        self._records = dict(records)

    def all_records(self):
        return list(self._records.items())

    def get_record(self, suggestion_id):
        return self._records.get(suggestion_id)

    def save_record(self, suggestion_id, record):
        self._records[suggestion_id] = record


class TestSuggestionIsolation:
    """Tests pour l'isolation des suggestions entre users."""

    def test_list_suggestions_filters_by_ownership(self, app, client):
        """list_suggestions ne doit retourner que les suggestions du user courant."""
        manager = MagicMock()
        acc_a = _make_account("acc-a", "a@test.com", user_id=1)
        acc_b = _make_account("acc-b", "b@test.com", user_id=2)
        manager.get_account.side_effect = lambda aid: acc_a if aid == "acc-a" else acc_b

        with _patch_calendar_handler_globals(
            client,
            _sugg_store=_FakeSuggestionStore({
                "s1": {"account_id": "acc-a", "status": "pending", "created_at": "2026-01-01", "email_id": "e1"},
                "s2": {"account_id": "acc-b", "status": "pending", "created_at": "2026-01-02", "email_id": "e2"},
            }),
            get_auth_user_id=lambda: 1,
            get_account_manager=lambda: manager,
        ):
            resp = client.get("/api/calendar/suggestions")
            data = resp.get_json()

        suggestion_ids = [s["id"] for s in data.get("suggestions", [])]
        assert "s1" in suggestion_ids
        assert "s2" not in suggestion_ids

    def test_accept_suggestion_rejects_other_user(self, app, client):
        """accept_suggestion doit refuser si la suggestion appartient à un autre user."""
        manager = MagicMock()
        acc_b = _make_account("acc-b", "b@test.com", user_id=2)
        manager.get_account.return_value = acc_b

        with _patch_calendar_handler_globals(
            client,
            _sugg_store=_FakeSuggestionStore({
                "s1": {"account_id": "acc-b", "status": "pending", "created_at": "2026-01-01"},
            }),
            get_auth_user_id=lambda: 1,
            get_account_manager=lambda: manager,
        ):
            resp = client.post("/api/calendar/suggestions/s1/accept", json={})
        assert resp.status_code == 403

    def test_reject_suggestion_rejects_other_user(self, app, client):
        """reject_suggestion doit refuser si la suggestion appartient à un autre user."""
        manager = MagicMock()
        acc_b = _make_account("acc-b", "b@test.com", user_id=2)
        manager.get_account.return_value = acc_b

        with _patch_calendar_handler_globals(
            client,
            _sugg_store=_FakeSuggestionStore({
                "s1": {"account_id": "acc-b", "status": "pending", "created_at": "2026-01-01"},
            }),
            get_auth_user_id=lambda: 1,
            get_account_manager=lambda: manager,
        ):
            resp = client.post("/api/calendar/suggestions/s1/reject", json={})
        assert resp.status_code == 403


# ============================================================================
# 6. Mode Tauri — aucune restriction
# ============================================================================


class TestTauriModeNoRestriction:
    """Mode Tauri (loopback, user_id=None) doit fonctionner normalement."""

    def test_get_active_account_id_tauri(self, app):
        """En mode Tauri (pas de JWT), l'accès est libre."""
        account = _make_account("acc-a", "a@test.com", user_id=None)

        with app.test_request_context():
            # No g.auth_user set (Tauri mode)
            with patch("app.api.calendar_routes.get_account_manager") as mock_mgr:
                manager = MagicMock()
                manager.get_current_for_user.return_value = "acc-a"
                manager.get_account.return_value = account
                mock_mgr.return_value = manager

                with patch("app.api.calendar_routes.supports_calendar", return_value=True):
                    from app.api.calendar_routes import _get_active_account_id
                    result = _get_active_account_id()

                    assert result == "acc-a"
