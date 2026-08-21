# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Test E2E : archivage d'un email via POST /api/emails/<id>/archive.

Reproduit le bug : après archivage, le dossier SQLite de l'email doit
passer de "inbox" à "archived" — et non être supprimé.

pytest tests/test_api_archive_e2e.py -v
"""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_db_ctx(repo):
    """Retourne un context manager mock pour get_db_session."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestArchiveE2E:
    """Test E2E du flux d'archivage."""

    @pytest.fixture(autouse=True)
    def _stub_account_resolution(self):
        """The archive handler's 404-guard (audit Cluster E, 2026-05-11)
        calls ``_resolve_account_id_cached`` + ``_email_exists_in_cache``
        before the archive flow these tests exercise. The tests pre-date
        that guard and only patched ``get_db_session`` — so the real
        ``_resolve_account_id_cached`` resolved through the mocked session
        and returned a ``MagicMock``, blowing up at ``_aid_for_check > 0``.
        Stub both so the handler reaches the archive logic under test.
        """
        with (
            patch(
                "app.api.routes_emails._resolve_account_id_cached",
                return_value=1,
            ),
            patch(
                "app.api.routes_emails._email_exists_in_cache",
                return_value=True,
            ),
        ):
            yield

    def test_archive_moves_email_to_archived_folder_in_sqlite(self, client):
        """
        BUG REPRODUIT : après archivage, update_folder_by_email_id("archived") doit
        être appelé (pas delete_by_email_id).

        Avant le fix : delete_by_email_id supprimait l'email de SQLite → absent de archives.
        Après le fix : update_folder_by_email_id déplace l'email → présent dans archives.
        """
        email_id = "msg123"
        repo = MagicMock()
        repo.update_folder_by_email_id = MagicMock(return_value=True)
        repo.delete_by_email_id = MagicMock(return_value=True)

        provider = MagicMock()
        provider.archive_email = MagicMock(return_value=True)

        pd_store = MagicMock()
        pd_store.get_by_email_id = MagicMock(return_value=None)

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_emails._invalidate_folder_cache"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx(repo)),
            patch("app.api.routes_helpers.EmailRepository", return_value=repo),
            patch("app.api.routes_helpers._get_container") as mock_container,
        ):
            mock_container.return_value.get_pending_draft_store.return_value = pd_store

            resp = client.post(f"/api/emails/{email_id}/archive", json={"sender": "test@example.com"})

        assert resp.status_code == 200, f"Archivage échoué: {resp.get_json()}"
        assert resp.get_json()["success"] is True

        # Vérifier que provider.archive_email a été appelé
        provider.archive_email.assert_called_once_with(email_id)

        # ASSERTION CENTRALE : update_folder_by_email_id("archived") doit être appelé
        assert repo.update_folder_by_email_id.called, (
            "BUG: update_folder_by_email_id n'a pas été appelé. "
            "L'email a été supprimé au lieu d'être déplacé dans 'archived'."
        )
        calls_with_archived = [
            c for c in repo.update_folder_by_email_id.call_args_list
            if "archived" in c.args
        ]
        assert calls_with_archived, (
            f"update_folder_by_email_id appelé mais sans 'archived'. "
            f"Appels: {repo.update_folder_by_email_id.call_args_list}"
        )

    def test_archive_does_not_delete_email_from_sqlite(self, client):
        """delete_by_email_id ne doit PAS être appelé lors d'un archivage réussi."""
        email_id = "msg456"
        repo = MagicMock()
        repo.update_folder_by_email_id = MagicMock(return_value=True)
        repo.delete_by_email_id = MagicMock(return_value=True)

        provider = MagicMock()
        provider.archive_email = MagicMock(return_value=True)

        pd_store = MagicMock()
        pd_store.get_by_email_id = MagicMock(return_value=None)

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_emails._invalidate_folder_cache"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx(repo)),
            patch("app.api.routes_helpers.EmailRepository", return_value=repo),
            patch("app.api.routes_helpers._get_container") as mock_container,
        ):
            mock_container.return_value.get_pending_draft_store.return_value = pd_store
            resp = client.post(f"/api/emails/{email_id}/archive", json={})

        assert resp.status_code == 200
        repo.delete_by_email_id.assert_not_called()

    def test_archive_sent_email_is_noop_for_provider(self, client):
        """Les emails sent: ne doivent pas appeler provider.archive_email."""
        email_id = "sent:msg789"
        repo = MagicMock()
        repo.update_folder_by_email_id = MagicMock(return_value=True)
        repo.delete_by_email_id = MagicMock(return_value=True)

        provider = MagicMock()
        provider.archive_email = MagicMock(return_value=True)

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_emails._invalidate_folder_cache"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx(repo)),
            patch("app.api.routes_helpers.EmailRepository", return_value=repo),
            patch("app.api.routes_helpers._get_container"),
        ):
            resp = client.post(f"/api/emails/{email_id}/archive", json={})

        assert resp.status_code == 200
        provider.archive_email.assert_not_called()

    def test_multiple_archives_all_appear_in_archived_folder(self, client):
        """
        BUG REPRODUIT : seul le premier email archivé apparaissait dans Archives.

        Cause : le cache IndexedDB frontend n'était pas invalidé après archivage,
        et sur le backend, les appels successifs devaient tous mettre à jour SQLite.

        Ce test vérifie que chaque archive appelle update_folder_by_email_id("archived").
        """
        email_ids = ["13984", "13981", "13982", "13951", "13963"]

        for email_id in email_ids:
            repo = MagicMock()
            repo.update_folder_by_email_id = MagicMock(return_value=True)
            repo.delete_by_email_id = MagicMock(return_value=True)

            provider = MagicMock()
            provider.archive_email = MagicMock(return_value=True)

            pd_store = MagicMock()
            pd_store.get_by_email_id = MagicMock(return_value=None)

            with (
                patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
                patch("app.api.routes_emails._invalidate_folder_cache"),
                patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx(repo)),
                patch("app.api.routes_helpers.EmailRepository", return_value=repo),
                patch("app.api.routes_helpers._get_container") as mock_container,
            ):
                mock_container.return_value.get_pending_draft_store.return_value = pd_store
                resp = client.post(f"/api/emails/{email_id}/archive", json={})

            assert resp.status_code == 200, f"Archive {email_id} a échoué: {resp.get_json()}"

            # Chaque archive doit mettre à jour SQLite vers "archived"
            assert repo.update_folder_by_email_id.called, (
                f"BUG: email {email_id} — update_folder_by_email_id non appelé"
            )
            found = any(
                "archived" in c.args
                for c in repo.update_folder_by_email_id.call_args_list
            )
            assert found, (
                f"BUG: email {email_id} — update_folder_by_email_id sans 'archived'. "
                f"Appels: {repo.update_folder_by_email_id.call_args_list}"
            )
            # delete_by_email_id ne doit JAMAIS être appelé pour un archivage
            repo.delete_by_email_id.assert_not_called()

    def test_archive_provider_failure_returns_200_async(self, client):
        """Archive returns 200 immediately — provider.archive_email runs in background thread."""
        email_id = "msgFail"
        repo = MagicMock()
        provider = MagicMock()
        provider.archive_email = MagicMock(return_value=False)

        with (
            patch("app.api.routes_emails._get_authenticated_provider", return_value=provider),
            patch("app.api.routes_emails._invalidate_folder_cache"),
            patch("app.api.routes_helpers.get_db_session", return_value=_mock_db_ctx(repo)),
            patch("app.api.routes_helpers.EmailRepository", return_value=repo),
            patch("app.api.routes_helpers._get_container"),
        ):
            resp = client.post(f"/api/emails/{email_id}/archive", json={})

        # Archive is now async (background thread) — endpoint always returns 200
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
