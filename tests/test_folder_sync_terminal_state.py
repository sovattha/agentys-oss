# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Bug "les onglets Corbeille/Indésirables ne s'ouvrent pas" (rapport Karine, 2026-06-09).

Un cache SQLite vide pour un dossier secondaire (trash/spam/archived) était
indiscernable d'un dossier jamais synchronisé : GET /api/emails répondait
`sync_in_progress: true` à CHAQUE requête, et le frontend rejouait son
escalier de retries (~72 s de skeleton) à chaque ouverture de l'onglet —
indéfiniment quand le refresh échouait en silence (compte OAuth introuvable,
auth provider KO) ou quand le dossier était réellement vide
(`_refresh_folder_cache_bg` ne persistait rien pour 0 emails).

Fix : chaque refresh terminé enregistre son issue par (account_id, folder)
via `record_folder_sync_outcome`. La route répond alors un état terminal :
- issue ok    → `{count: 0, source: "cache"}` (dossier vide, pas de skeleton)
- issue échec → `+ sync_failed: true` (le FE affiche l'erreur + Réessayer)
- pas d'issue → comportement existant (`sync_in_progress: true`)
`force_refresh=true` efface l'issue mémorisée pour que le bouton Réessayer
reflète la NOUVELLE tentative.

pytest tests/test_folder_sync_terminal_state.py -v
"""
import pytest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from app.api import routes_helpers as rh


ACCOUNT_ID = 7


@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _clean_outcomes():
    """Chaque test part d'un store d'issues vierge."""
    with rh._folder_sync_outcome_lock:
        rh._folder_sync_outcomes.clear()
    yield
    with rh._folder_sync_outcome_lock:
        rh._folder_sync_outcomes.clear()


def _mock_db_ctx():
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _list_patches(stack: ExitStack) -> MagicMock:
    """Patches minimum pour traverser list_emails jusqu'à la branche dossier
    secondaire avec un cache SQLite vide. Retourne le mock _start_background_sync."""
    current = MagicMock()
    current.email = "karine@example.com"
    current.id = "oauthhash123"
    stack.enter_context(patch(
        "app.api.routes_emails._get_current_account_for_user", return_value=current,
    ))
    stack.enter_context(patch(
        "app.api.routes_helpers._resolve_account_id_for_email", return_value=ACCOUNT_ID,
    ))
    stack.enter_context(patch(
        "app.api.routes_emails._get_cached_email_response", return_value=None,
    ))
    stack.enter_context(patch(
        "app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx(),
    ))
    repo = MagicMock()
    repo.get_by_folder = MagicMock(return_value=[])
    repo.count_by_account = MagicMock(return_value=0)
    stack.enter_context(patch(
        "app.api.routes_helpers.EmailRepository", return_value=repo,
    ))
    return stack.enter_context(patch(
        "app.api.routes_emails._start_background_sync",
    ))


# ---------------------------------------------------------------------------
# Route /api/emails — état terminal pour cache vide
# ---------------------------------------------------------------------------


class TestEmptySecondaryFolderTerminalState:

    def test_no_outcome_keeps_syncing_response(self, client):
        """Sans issue connue (premier chargement), le contrat existant est
        préservé : sync_in_progress=true + enqueue d'un job provider."""
        with ExitStack() as stack:
            bg = _list_patches(stack)
            resp = client.get("/api/emails?folder=spam")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["sync_in_progress"] is True
        assert data["source"] == "syncing"
        assert bg.called

    def test_successful_empty_sync_returns_terminal_empty(self, client):
        """Dossier réellement vide : après un refresh OK, la réponse est
        terminale (pas de sync_in_progress) — le FE affiche 'dossier vide'
        immédiatement au lieu de ~72 s de skeleton."""
        rh.record_folder_sync_outcome(ACCOUNT_ID, "spam", ok=True)
        with ExitStack() as stack:
            bg = _list_patches(stack)
            resp = client.get("/api/emails?folder=spam")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["count"] == 0
        assert data["emails"] == []
        assert data["source"] == "cache"
        assert not data.get("sync_in_progress")
        assert "sync_failed" not in data
        # Stale-while-revalidate : un refresh debounced reste enchaîné
        assert bg.called

    def test_failed_sync_returns_sync_failed_flag(self, client):
        """Refresh en échec persistant (cas Karine probable) : la réponse
        porte sync_failed=true pour que le FE montre l'erreur + Réessayer au
        lieu d'un skeleton infini ou d'un faux dossier vide."""
        rh.record_folder_sync_outcome(ACCOUNT_ID, "trash", ok=False)
        with ExitStack() as stack:
            _list_patches(stack)
            resp = client.get("/api/emails?folder=trash")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["count"] == 0
        assert data["sync_failed"] is True
        assert not data.get("sync_in_progress")

    def test_outcome_is_scoped_per_account_and_folder(self, client):
        """L'issue d'un autre compte ou d'un autre dossier ne fuit pas."""
        rh.record_folder_sync_outcome(ACCOUNT_ID + 1, "spam", ok=True)   # autre compte
        rh.record_folder_sync_outcome(ACCOUNT_ID, "trash", ok=True)      # autre dossier
        with ExitStack() as stack:
            _list_patches(stack)
            resp = client.get("/api/emails?folder=spam")
        data = resp.get_json()
        assert data["sync_in_progress"] is True  # spam de CE compte reste inconnu

    def test_force_refresh_clears_recorded_outcome(self, client):
        """Le bouton Réessayer (force_refresh) efface l'issue mémorisée : la
        réponse redevient 'syncing' le temps que la NOUVELLE tentative
        aboutisse, au lieu de rejouer l'ancien échec."""
        rh.record_folder_sync_outcome(ACCOUNT_ID, "trash", ok=False)
        with ExitStack() as stack:
            _list_patches(stack)
            resp = client.get("/api/emails?folder=trash&force_refresh=true")
        data = resp.get_json()
        assert resp.status_code == 200
        assert rh.get_folder_sync_outcome(ACCOUNT_ID, "trash") is None
        assert data["sync_in_progress"] is True
        assert "sync_failed" not in data


# ---------------------------------------------------------------------------
# record/get/clear — garde-fous
# ---------------------------------------------------------------------------


class TestOutcomeStoreGuards:

    def test_sentinel_account_is_never_recorded(self):
        rh.record_folder_sync_outcome(-1, "spam", ok=True)
        rh.record_folder_sync_outcome(0, "spam", ok=True)
        assert rh.get_folder_sync_outcome(-1, "spam") is None
        assert rh.get_folder_sync_outcome(0, "spam") is None

    def test_unknown_folder_is_never_recorded(self):
        rh.record_folder_sync_outcome(ACCOUNT_ID, "inbox", ok=True)
        assert rh.get_folder_sync_outcome(ACCOUNT_ID, "inbox") is None

    def test_clear_removes_outcome(self):
        rh.record_folder_sync_outcome(ACCOUNT_ID, "spam", ok=False)
        rh.clear_folder_sync_outcome(ACCOUNT_ID, "spam")
        assert rh.get_folder_sync_outcome(ACCOUNT_ID, "spam") is None


# ---------------------------------------------------------------------------
# _refresh_folder_cache_bg — enregistrement des issues
# ---------------------------------------------------------------------------


class TestRefreshFolderCacheOutcomeRecording:

    def test_provider_returning_zero_emails_records_success(self):
        """LE cas déterministe du bug : dossier vide côté provider →
        l'issue ok doit être mémorisée même si rien n'est persisté."""
        provider = MagicMock()
        provider.authenticate.return_value = True
        provider.get_message_headers.return_value = []
        with patch("app.providers.factory.get_pooled_provider", return_value=provider):
            persisted = rh._refresh_folder_cache_bg("spam", ACCOUNT_ID, "oauthhash123")
        assert persisted == 0
        outcome = rh.get_folder_sync_outcome(ACCOUNT_ID, "spam")
        assert outcome is not None and outcome["ok"] is True

    def test_missing_oauth_account_records_failure(self):
        with patch("app.providers.factory.get_pooled_provider") as factory:
            persisted = rh._refresh_folder_cache_bg("trash", ACCOUNT_ID, "")
        assert persisted == 0
        assert not factory.called
        outcome = rh.get_folder_sync_outcome(ACCOUNT_ID, "trash")
        assert outcome is not None and outcome["ok"] is False

    def test_auth_failure_records_failure(self):
        provider = MagicMock()
        provider.authenticate.return_value = False
        with patch("app.providers.factory.get_pooled_provider", return_value=provider):
            rh._refresh_folder_cache_bg("spam", ACCOUNT_ID, "oauthhash123")
        outcome = rh.get_folder_sync_outcome(ACCOUNT_ID, "spam")
        assert outcome is not None and outcome["ok"] is False

    def test_provider_exception_records_failure(self):
        with patch(
            "app.providers.factory.get_pooled_provider",
            side_effect=RuntimeError("Graph indisponible"),
        ):
            rh._refresh_folder_cache_bg("archived", ACCOUNT_ID, "oauthhash123")
        outcome = rh.get_folder_sync_outcome(ACCOUNT_ID, "archived")
        assert outcome is not None and outcome["ok"] is False

    def test_successful_sync_with_emails_records_success(self):
        provider = MagicMock()
        provider.authenticate.return_value = True

        class FakeEmail:
            id = "msg-1"
            subject = "Sujet"
            sender = "a@b.c"
            sender_name = "A"
            received_at = None
            conversation_id = None
            to = []
            body = None
            body_html = None
            is_read = True
            is_starred = False

        provider.get_message_headers.return_value = [FakeEmail()]
        with (
            patch("app.providers.factory.get_pooled_provider", return_value=provider),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx()),
            patch("app.api.routes_helpers.EmailRepository"),
        ):
            persisted = rh._refresh_folder_cache_bg("trash", ACCOUNT_ID, "oauthhash123")
        assert persisted == 1
        outcome = rh.get_folder_sync_outcome(ACCOUNT_ID, "trash")
        assert outcome is not None and outcome["ok"] is True
