# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour l'isolation multi-utilisateur.

Vérifie que User B ne peut pas voir/modifier les comptes de User A.
Couvre : modèle Account.user_id, AccountManager per-user current,
routes.py fallback supprimé, accounts.py ownership checks + filtrage.

pytest tests/test_multi_user_isolation.py -v
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from app.api.app import create_app
from app.multi_accounts import (
    AccountConfig,
    AccountManager,
    AccountStatus,
    ProviderType,
    switch_account,
)
from app.db.models.account import Account


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


@pytest.fixture
def account_manager(tmp_path):
    """AccountManager avec fichier temporaire."""
    filepath = tmp_path / "accounts.json"
    return AccountManager(filepath=filepath)


def _make_jwt_client(app, user_id, email):
    """Crée un client de test qui simule un JWT valide."""
    client = app.test_client()
    # Patch g.auth_user pour simuler un JWT valide
    original_get = client.get
    original_post = client.post
    original_patch = client.patch
    original_delete = client.delete

    class JWTClient:
        """Wrapper qui injecte g.auth_user dans chaque requête."""
        def __init__(self):
            self._app = app
            self._user_id = user_id
            self._email = email

        def _inject_auth(self, method, *args, **kwargs):
            with self._app.test_request_context():
                from flask import g
                g.auth_user = {"id": self._user_id, "email": self._email}
            return method(*args, **kwargs)

        def get(self, *args, **kwargs):
            return original_get(*args, **kwargs)

        def post(self, *args, **kwargs):
            return original_post(*args, **kwargs)

        def patch(self, *args, **kwargs):
            return original_patch(*args, **kwargs)

        def delete(self, *args, **kwargs):
            return original_delete(*args, **kwargs)

    return JWTClient()


@pytest.fixture
def mock_account_manager():
    """Mock du gestionnaire de comptes."""
    with patch("app.api.accounts.get_account_manager") as mock:
        manager = MagicMock()
        manager.get_current_for_user.return_value = None
        manager.accounts = {}
        manager.stats = {}
        mock.return_value = manager
        yield manager


# ============================================================================
# 1. ACCOUNT MODEL — user_id COLUMN
# ============================================================================


class TestAccountModelUserId:
    """Tests pour le champ user_id sur le modèle Account."""

    def test_account_user_id_default_none(self):
        """user_id est None par défaut (backward compat Tauri)."""
        account = Account(
            email="test@example.com",
            provider="gmail",
        )
        assert account.user_id is None

    def test_account_user_id_set(self):
        """user_id peut être défini."""
        account = Account(
            email="test@example.com",
            provider="gmail",
            user_id=42,
        )
        assert account.user_id == 42

    def test_account_to_dict_includes_user_id(self):
        """to_dict() inclut user_id."""
        account = Account(
            email="test@example.com",
            provider="gmail",
            user_id=7,
        )
        data = account.to_dict()
        assert "user_id" in data
        assert data["user_id"] == 7

    def test_account_to_dict_user_id_none(self):
        """to_dict() retourne None pour les comptes legacy."""
        account = Account(
            email="test@example.com",
            provider="gmail",
        )
        data = account.to_dict()
        assert data["user_id"] is None


# ============================================================================
# 2. ACCOUNT CONFIG — user_id FIELD
# ============================================================================


class TestAccountConfigUserId:
    """Tests pour user_id sur AccountConfig (dataclass JSON)."""

    def test_default_user_id_none(self):
        """user_id est None par défaut."""
        config = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="gmail"
        )
        assert config.user_id is None

    def test_user_id_set(self):
        """user_id peut être passé à la construction."""
        config = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="gmail",
            user_id=42,
        )
        assert config.user_id == 42

    def test_user_id_in_add_account(self, account_manager):
        """add_account() propage user_id."""
        account = account_manager.add_account(
            "Work", "work@ex.com", ProviderType.GMAIL, user_id=99,
        )
        assert account.user_id == 99


# ============================================================================
# 3. PER-USER CURRENT ACCOUNT
# ============================================================================


class TestPerUserCurrent:
    """Tests pour _current_per_user dans AccountManager."""

    def test_current_account_id_legacy_none(self, account_manager):
        """current_account_id est None au départ (legacy property)."""
        assert account_manager.current_account_id is None

    def test_current_account_id_legacy_setter(self, account_manager):
        """Le setter legacy mappe sur user_id=None."""
        account_manager.current_account_id = "acc1"
        assert account_manager.current_account_id == "acc1"
        assert account_manager.get_current_for_user(None) == "acc1"

    def test_current_account_id_legacy_clear(self, account_manager):
        """Setter None supprime l'entrée."""
        account_manager.current_account_id = "acc1"
        account_manager.current_account_id = None
        assert account_manager.current_account_id is None

    def test_get_set_current_for_user(self, account_manager):
        """get/set current_for_user fonctionne par user_id."""
        account_manager.set_current_for_user("acc_a", user_id=1)
        account_manager.set_current_for_user("acc_b", user_id=2)

        assert account_manager.get_current_for_user(1) == "acc_a"
        assert account_manager.get_current_for_user(2) == "acc_b"
        assert account_manager.get_current_for_user(999) is None

    def test_switch_to_with_user_id(self, account_manager):
        """switch_to() scope le current_account_id au user."""
        acc1 = account_manager.add_account("A", "a@ex.com", ProviderType.GMAIL)
        acc2 = account_manager.add_account("B", "b@ex.com", ProviderType.GMAIL)

        account_manager.switch_to(acc1.id, user_id=1)
        account_manager.switch_to(acc2.id, user_id=2)

        assert account_manager.get_current_for_user(1) == acc1.id
        assert account_manager.get_current_for_user(2) == acc2.id

    def test_switch_account_wrapper_forwards_user_id(self, account_manager):
        """switch_account() expose le même scoping user_id que AccountManager."""
        acc = account_manager.add_account("A", "a@ex.com", ProviderType.GMAIL)

        with patch("app.multi_accounts._account_manager", account_manager):
            context = switch_account(acc.id, user_id=42)

        assert context is not None
        assert account_manager.get_current_for_user(42) == acc.id

    def test_switch_to_without_user_id_legacy(self, account_manager):
        """switch_to() sans user_id utilise None (Tauri mode)."""
        acc = account_manager.add_account("A", "a@ex.com", ProviderType.GMAIL)
        account_manager.switch_to(acc.id)

        assert account_manager.current_account_id == acc.id
        assert account_manager.get_current_for_user(None) == acc.id

    def test_switch_deactivates_same_user_only(self, account_manager):
        """switch_to() ne désactive que les comptes du même user."""
        acc_u1 = account_manager.add_account(
            "U1", "u1@ex.com", ProviderType.GMAIL, user_id=1,
        )
        acc_u2 = account_manager.add_account(
            "U2", "u2@ex.com", ProviderType.GMAIL, user_id=2,
        )

        # User 1 active son compte
        account_manager.switch_to(acc_u1.id, user_id=1)
        # User 2 active son compte — ne doit PAS désactiver celui de user 1
        account_manager.switch_to(acc_u2.id, user_id=2)

        assert acc_u1.status == AccountStatus.ACTIVE.value
        assert acc_u2.status == AccountStatus.ACTIVE.value

    def test_switch_deactivates_other_accounts_same_user(self, account_manager):
        """switch_to() désactive les autres comptes du même user."""
        acc_a = account_manager.add_account(
            "A", "a@ex.com", ProviderType.GMAIL, user_id=1,
        )
        acc_b = account_manager.add_account(
            "B", "b@ex.com", ProviderType.GMAIL, user_id=1,
        )

        account_manager.switch_to(acc_a.id, user_id=1)
        assert acc_a.status == AccountStatus.ACTIVE.value

        account_manager.switch_to(acc_b.id, user_id=1)
        assert acc_a.status == AccountStatus.INACTIVE.value
        assert acc_b.status == AccountStatus.ACTIVE.value

    def test_remove_account_clears_all_per_user(self, account_manager):
        """remove_account() nettoie _current_per_user pour tous les users."""
        acc = account_manager.add_account("A", "a@ex.com", ProviderType.GMAIL)
        account_manager.set_current_for_user(acc.id, user_id=1)
        account_manager.set_current_for_user(acc.id, user_id=2)

        account_manager.remove_account(acc.id)

        assert account_manager.get_current_for_user(1) is None
        assert account_manager.get_current_for_user(2) is None


# ============================================================================
# 4. PERSISTENCE — SAVE/LOAD current_per_user
# ============================================================================


class TestPerUserPersistence:
    """Tests pour la sérialisation de current_per_user."""

    def test_save_load_per_user(self, tmp_path):
        """current_per_user persiste correctement."""
        filepath = tmp_path / "accounts.json"
        mgr1 = AccountManager(filepath=filepath)
        acc = mgr1.add_account("A", "a@ex.com", ProviderType.GMAIL)
        mgr1.set_current_for_user(acc.id, user_id=1)
        mgr1.set_current_for_user(acc.id, user_id=None)
        mgr1._save()

        # Reload
        mgr2 = AccountManager(filepath=filepath)
        assert mgr2.get_current_for_user(1) == acc.id
        assert mgr2.get_current_for_user(None) == acc.id

    def test_load_legacy_format(self, tmp_path):
        """Charge un fichier sans current_per_user (backward compat)."""
        filepath = tmp_path / "accounts.json"
        # Écrire un fichier legacy avec current_account_id seulement
        legacy_data = {
            "accounts": [],
            "stats": [],
            "current_account_id": "legacy-acc",
            "updated_at": "2024-01-01T00:00:00",
        }
        filepath.write_text(json.dumps(legacy_data))

        mgr = AccountManager(filepath=filepath)
        # Legacy current_account_id → mappé sur user_id=None
        assert mgr.current_account_id == "legacy-acc"
        assert mgr.get_current_for_user(None) == "legacy-acc"
        # Pas de mapping pour d'autres users
        assert mgr.get_current_for_user(1) is None

    def test_load_migrates_stale_user_ids_to_canonical_email_hash(self, tmp_path):
        """Prod had old 5-digit user_ids in email_accounts.json."""
        from app.account_identity import user_id_from_email

        filepath = tmp_path / "accounts.json"
        email = "nathanroy@gmail.com"
        account_id = "f9057edfed0d4574"
        old_user_id = 32691
        canonical_user_id = user_id_from_email(email)
        filepath.write_text(json.dumps({
            "accounts": [{
                "id": account_id,
                "name": "Nat",
                "email": email,
                "provider": ProviderType.GMAIL.value,
                "user_id": old_user_id,
            }],
            "stats": [],
            "current_per_user": {str(old_user_id): account_id},
            "current_account_id": account_id,
            "updated_at": "2026-05-13T00:00:00",
        }))

        mgr = AccountManager(filepath=filepath)

        assert mgr.get_account(account_id).user_id == canonical_user_id
        assert mgr.get_current_for_user(canonical_user_id) == account_id
        persisted = json.loads(filepath.read_text())
        assert persisted["accounts"][0]["user_id"] == canonical_user_id
        assert persisted["current_per_user"][str(canonical_user_id)] == account_id

    def test_save_includes_legacy_field(self, tmp_path):
        """_save() inclut toujours current_account_id pour backward compat."""
        filepath = tmp_path / "accounts.json"
        mgr = AccountManager(filepath=filepath)
        acc = mgr.add_account("A", "a@ex.com", ProviderType.GMAIL)
        mgr.current_account_id = acc.id
        mgr._save()

        data = json.loads(filepath.read_text())
        assert "current_account_id" in data
        assert data["current_account_id"] == acc.id
        assert "current_per_user" in data


# ============================================================================
# 5. ROUTES — FALLBACK SUPPRIMÉ
# ============================================================================


class TestResolveAccountIdFallback:
    """Tests pour _resolve_account_id_for_user() sans fallback dangereux."""

    def test_returns_sentinel_when_email_not_in_db(self, app):
        """Retourne -1 (sentinel) si l'email JWT n'a pas de compte DB (pas fallback à 1)."""
        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 999, "email": "unknown@example.com"}

            from app.api.routes import _resolve_account_id_for_user, _account_id_cache, _NO_ACCOUNT_SENTINEL
            _account_id_cache.clear()

            mock_repo = MagicMock()
            mock_repo.get_by_email.return_value = None

            with patch("app.api.routes_helpers.get_db_session") as mock_session:
                mock_sess = MagicMock()
                mock_session.return_value.__enter__ = MagicMock(return_value=mock_sess)
                mock_session.return_value.__exit__ = MagicMock(return_value=False)

                with patch("app.db.repositories.account_repository.AccountRepository", return_value=mock_repo):
                    result = _resolve_account_id_for_user()
                    assert result == _NO_ACCOUNT_SENTINEL  # -1, PAS 1 !
                    assert result != 1  # Never fallback to account_id=1

    def test_returns_account_id_when_found(self, app):
        """Retourne l'ID du compte trouvé en DB."""
        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 1, "email": "known@example.com"}

            from app.api.routes import _resolve_account_id_for_user, _account_id_cache
            _account_id_cache.clear()

            mock_db_account = MagicMock()
            mock_db_account.id = 42
            mock_repo = MagicMock()
            mock_repo.get_by_email.return_value = mock_db_account

            with patch("app.api.routes_helpers.get_db_session") as mock_session:
                mock_sess = MagicMock()
                mock_session.return_value.__enter__ = MagicMock(return_value=mock_sess)
                mock_session.return_value.__exit__ = MagicMock(return_value=False)

                with patch("app.db.repositories.account_repository.AccountRepository", return_value=mock_repo):
                    result = _resolve_account_id_for_user()
                    assert result == 42

    def test_sentinel_never_matches_real_accounts(self):
        """Le sentinel -1 ne peut jamais matcher un vrai account_id en DB."""
        from app.api.routes import _NO_ACCOUNT_SENTINEL
        assert _NO_ACCOUNT_SENTINEL == -1
        assert _NO_ACCOUNT_SENTINEL < 0  # DB IDs are always > 0


class TestGetCurrentAccountForUser:
    """Tests pour _get_current_account_for_user()."""

    def test_returns_none_for_unknown_jwt_email(self, app):
        """JWT avec email inconnu → None (pas fallback sur un autre user)."""
        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 999, "email": "stranger@example.com"}

            from app.api.routes import _get_current_account_for_user
            with patch("app.multi_accounts.get_account_manager") as mock_mgr:
                mock_mgr.return_value.get_account_by_email.return_value = None

                result = _get_current_account_for_user()
                assert result is None

    def test_returns_account_for_known_jwt_email(self, app):
        """JWT avec email connu → retourne le bon compte."""
        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 1, "email": "user@example.com"}

            from app.api.routes import _get_current_account_for_user
            expected = AccountConfig(
                id="acc1", name="Test", email="user@example.com", provider="gmail"
            )
            with patch("app.multi_accounts.get_account_manager") as mock_mgr:
                mock_mgr.return_value.get_account_by_email.return_value = expected

                result = _get_current_account_for_user()
                assert result == expected

    def test_tauri_mode_fallback_to_global(self, app):
        """Sans JWT (Tauri) → fallback sur get_current_account()."""
        with app.test_request_context(
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        ):
            from flask import g
            g.auth_user = None

            from app.api.routes import _get_current_account_for_user
            expected = AccountConfig(
                id="tauri-acc", name="Tauri", email="tauri@local.com", provider="gmail"
            )
            with patch("app.multi_accounts.get_current_account", return_value=expected):
                result = _get_current_account_for_user()
                assert result == expected


# ============================================================================
# 6. ACCOUNTS API — OWNERSHIP CHECKS
# ============================================================================


class TestOwnershipChecks:
    """Tests pour les ownership checks dans accounts.py."""

    def test_check_account_ownership_no_auth(self):
        """Sans JWT (Tauri) → toujours autorisé."""
        from app.api.accounts import _check_account_ownership
        account = AccountConfig(
            id="acc1", name="T", email="t@e.com", provider="gmail", user_id=42,
        )
        assert _check_account_ownership(account, None) is True

    def test_check_account_ownership_legacy_account(self):
        """Compte legacy (user_id=None) → refusé pour un user JWT (isolation stricte)."""
        from app.api.accounts import _check_account_ownership
        account = AccountConfig(
            id="acc1", name="T", email="t@e.com", provider="gmail", user_id=None,
        )
        assert _check_account_ownership(account, 42) is False

    def test_check_account_ownership_match(self):
        """user_id matche → autorisé."""
        from app.api.accounts import _check_account_ownership
        account = AccountConfig(
            id="acc1", name="T", email="t@e.com", provider="gmail", user_id=42,
        )
        assert _check_account_ownership(account, 42) is True

    def test_check_account_ownership_mismatch(self):
        """user_id ne matche pas → refusé."""
        from app.api.accounts import _check_account_ownership
        account = AccountConfig(
            id="acc1", name="T", email="t@e.com", provider="gmail", user_id=42,
        )
        assert _check_account_ownership(account, 999) is False


class TestGetAuthUserId:
    """Tests pour _get_auth_user_id()."""

    def test_no_auth_user(self, app):
        """Sans JWT → None."""
        with app.test_request_context():
            from flask import g
            g.auth_user = None
            from app.api.accounts import _get_auth_user_id
            assert _get_auth_user_id() is None

    def test_auth_user_with_int_id(self, app):
        """JWT avec id entier."""
        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": 42, "email": "u@e.com"}
            from app.api.accounts import _get_auth_user_id
            assert _get_auth_user_id() == 42

    def test_auth_user_with_string_id(self, app):
        """JWT avec id string (converti en int)."""
        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": "123", "email": "u@e.com"}
            from app.api.accounts import _get_auth_user_id
            assert _get_auth_user_id() == 123

    def test_auth_user_with_non_numeric_id(self, app):
        """JWT avec id non-numérique → None."""
        with app.test_request_context():
            from flask import g
            g.auth_user = {"id": "not-a-number", "email": "u@e.com"}
            from app.api.accounts import _get_auth_user_id
            assert _get_auth_user_id() is None


# ============================================================================
# 7. ACCOUNTS API — LIST FILTERED BY USER
# ============================================================================


class TestListAccountsFiltered:
    """Tests pour le filtrage de list_accounts() par user_id."""

    def test_list_no_jwt_returns_all(self, client, mock_account_manager):
        """Sans JWT → tous les comptes (mode Tauri)."""
        acc1 = AccountConfig(
            id="a1", name="A", email="a@e.com", provider="gmail", user_id=1,
        )
        acc2 = AccountConfig(
            id="a2", name="B", email="b@e.com", provider="gmail", user_id=2,
        )
        mock_account_manager.get_all_accounts.return_value = [acc1, acc2]

        response = client.get("/api/accounts")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 2

    def test_list_jwt_filters_by_user(self, app, mock_account_manager):
        """Avec JWT → seuls les comptes du user (isolation stricte, pas de legacy)."""
        acc_mine = AccountConfig(
            id="mine", name="Mine", email="me@e.com", provider="gmail", user_id=42,
        )
        acc_other = AccountConfig(
            id="other", name="Other", email="other@e.com", provider="gmail", user_id=99,
        )
        acc_legacy = AccountConfig(
            id="legacy", name="Legacy", email="old@e.com", provider="gmail", user_id=None,
        )
        mock_account_manager.get_all_accounts.return_value = [acc_mine, acc_other, acc_legacy]

        with patch("app.api.accounts._get_auth_user_id", return_value=42):
            with patch("app.api.accounts._get_auth_email", return_value="me@e.com"):
                # _is_loopback is called twice: first by auth guard (must return True
                # to let the request through without JWT), then by list_accounts
                # (must return False so multi-user filtering is applied).
                with patch("app.api.auth._is_loopback", side_effect=[True, False]):
                    with app.test_client() as c:
                        response = c.get("/api/accounts")
                        assert response.status_code == 200
                        data = response.get_json()
                        # Seul acc_mine visible (acc_other=autre user, acc_legacy=pas d'email match)
                        emails = [a["email"] for a in data["accounts"]]
                        assert "me@e.com" in emails
                        assert "old@e.com" not in emails
                        assert "other@e.com" not in emails


# ============================================================================
# 8. ACCOUNTS API — CRUD OWNERSHIP ENFORCEMENT
# ============================================================================


class TestCrudOwnershipEnforcement:
    """Tests pour les ownership checks sur GET/PATCH/DELETE/ACTIVATE."""

    def test_get_account_owned_by_other_returns_404(self, client, mock_account_manager):
        """GET /accounts/<id> d'un compte d'un autre user → 404."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="gmail", user_id=99,
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.stats = {}

        with patch("app.api.accounts._get_auth_user_id", return_value=42):
            with patch("app.api.accounts._check_account_ownership", return_value=False):
                response = client.get("/api/accounts/acc1")
                assert response.status_code == 404

    def test_get_account_owned_by_self(self, client, mock_account_manager):
        """GET /accounts/<id> de son propre compte → 200."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="gmail", user_id=42,
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.get_current_for_user.return_value = "acc1"
        mock_account_manager.stats = {}

        with patch("app.api.accounts._get_auth_user_id", return_value=42):
            with patch("app.api.accounts._check_account_ownership", return_value=True):
                response = client.get("/api/accounts/acc1")
                assert response.status_code == 200

    def test_update_account_owned_by_other_returns_404(self, client, mock_account_manager):
        """PATCH /accounts/<id> d'un compte d'un autre user → 404."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="gmail", user_id=99,
        )
        mock_account_manager.get_account.return_value = account

        with patch("app.api.accounts._get_auth_user_id", return_value=42):
            with patch("app.api.accounts._check_account_ownership", return_value=False):
                response = client.patch(
                    "/api/accounts/acc1",
                    data=json.dumps({"name": "Hacked"}),
                    content_type="application/json",
                )
                assert response.status_code == 404

    def test_delete_account_owned_by_other_returns_404(self, client, mock_account_manager):
        """DELETE /accounts/<id> d'un compte d'un autre user → 404."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="gmail", user_id=99,
        )
        mock_account_manager.get_account.return_value = account

        with patch("app.api.accounts._get_auth_user_id", return_value=42):
            with patch("app.api.accounts._check_account_ownership", return_value=False):
                # _is_loopback must return True for auth guard (pass request through),
                # then False inside delete_account (so ownership check runs).
                with patch("app.api.auth._is_loopback", side_effect=[True, False]):
                    response = client.delete("/api/accounts/acc1")
                    assert response.status_code == 404

    def test_activate_account_owned_by_other_returns_404(self, client, mock_account_manager):
        """POST /accounts/<id>/activate d'un compte d'un autre user → 404."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="gmail", user_id=99,
        )
        mock_account_manager.get_account.return_value = account

        with patch("app.api.accounts._get_auth_user_id", return_value=42):
            with patch("app.api.accounts._check_account_ownership", return_value=False):
                response = client.post("/api/accounts/acc1/activate")
                assert response.status_code == 404


# ============================================================================
# 9. CREATE ACCOUNT — user_id PROPAGATION
# ============================================================================


class TestCreateAccountUserId:
    """Tests pour la propagation de user_id à la création."""

    def test_create_account_passes_user_id(self, client, mock_account_manager):
        """POST /accounts propage user_id du JWT à add_account()."""
        new_account = AccountConfig(
            id="new1", name="New", email="new@e.com", provider="imap_smtp",
            user_id=42,
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        with patch("app.api.accounts._get_auth_user_id", return_value=42):
            with patch("app.api.accounts._ensure_db_account") as mock_ensure:
                response = client.post(
                    "/api/accounts",
                    data=json.dumps({
                        "name": "New",
                        "email": "new@e.com",
                        "provider": "imap_smtp",
                    }),
                    content_type="application/json",
                )

                assert response.status_code == 201
                # Vérifie que user_id=42 a été passé à add_account
                call_kwargs = mock_account_manager.add_account.call_args
                assert call_kwargs.kwargs.get("user_id") == 42
                # Vérifie que user_id=42 a été passé à _ensure_db_account
                mock_ensure.assert_called_once()
                assert mock_ensure.call_args.kwargs.get("user_id") == 42

    def test_create_account_no_jwt_user_id_none(self, client, mock_account_manager):
        """POST /accounts sans JWT → user_id=None (Tauri mode)."""
        new_account = AccountConfig(
            id="new1", name="New", email="new@e.com", provider="imap_smtp",
        )
        mock_account_manager.get_account_by_email.return_value = None
        mock_account_manager.add_account.return_value = new_account

        with patch("app.api.accounts._get_auth_user_id", return_value=None):
            with patch("app.api.accounts._ensure_db_account"):
                response = client.post(
                    "/api/accounts",
                    data=json.dumps({
                        "name": "New",
                        "email": "new@e.com",
                        "provider": "imap_smtp",
                    }),
                    content_type="application/json",
                )

                assert response.status_code == 201
                call_kwargs = mock_account_manager.add_account.call_args
                assert call_kwargs.kwargs.get("user_id") is None


# ============================================================================
# 10. ENSURE DB ACCOUNT — user_id PROPAGATION
# ============================================================================


class TestEnsureDbAccountUserId:
    """Tests pour _ensure_db_account() avec user_id."""

    @pytest.fixture
    def _db_session(self, tmp_path):
        """Session SQLite en mémoire avec schéma complet."""
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from app.db.models import Base

        engine = create_engine("sqlite:///:memory:", echo=False)
        event.listen(engine, "connect", lambda c, _: c.cursor().execute("PRAGMA foreign_keys = ON").close())
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()

    def test_creates_account_with_user_id(self, app, _db_session):
        """Crée un Account DB avec user_id."""
        from contextlib import contextmanager

        @contextmanager
        def fake_db_session():
            yield _db_session

        with app.app_context():
            from app.api.accounts import _ensure_db_account
            with patch("app.db.database.get_db_session", fake_db_session):
                _ensure_db_account("u@e.com", "gmail", "User", user_id=42)

            account = _db_session.query(Account).filter_by(email="u@e.com").first()
            assert account is not None
            assert account.user_id == 42

    def test_backfills_user_id_on_existing(self, app, _db_session):
        """Backfill user_id sur un compte existant sans user_id."""
        from contextlib import contextmanager

        # Pré-créer un compte sans user_id
        existing = Account(email="u@e.com", provider="gmail", display_name="Old")
        _db_session.add(existing)
        _db_session.commit()
        assert existing.user_id is None

        @contextmanager
        def fake_db_session():
            yield _db_session

        with app.app_context():
            from app.api.accounts import _ensure_db_account
            with patch("app.db.database.get_db_session", fake_db_session):
                _ensure_db_account("u@e.com", "gmail", "User", user_id=42)

            _db_session.refresh(existing)
            assert existing.user_id == 42


# ============================================================================
# 11. DB MODEL — user_id PERSISTS IN SQLITE
# ============================================================================


class TestAccountUserIdPersistence:
    """Tests pour la persistance de user_id en SQLite."""

    @pytest.fixture
    def db_session(self, tmp_path):
        """Session SQLite en mémoire pour tests."""
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from app.db.models import Base

        engine = create_engine("sqlite:///:memory:", echo=False)
        event.listen(engine, "connect", lambda conn, _: conn.cursor().execute("PRAGMA foreign_keys = ON").close())
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()

    def test_user_id_stored_and_retrieved(self, db_session):
        """user_id est stocké et récupéré correctement."""
        account = Account(
            email="test@example.com",
            provider="gmail",
            user_id=42,
        )
        db_session.add(account)
        db_session.commit()

        retrieved = db_session.query(Account).filter_by(email="test@example.com").first()
        assert retrieved.user_id == 42

    def test_user_id_nullable(self, db_session):
        """user_id peut être None (comptes legacy)."""
        account = Account(
            email="legacy@example.com",
            provider="gmail",
        )
        db_session.add(account)
        db_session.commit()

        retrieved = db_session.query(Account).filter_by(email="legacy@example.com").first()
        assert retrieved.user_id is None

    def test_multiple_accounts_different_users(self, db_session):
        """Plusieurs comptes avec différents user_id."""
        for i in range(3):
            db_session.add(Account(
                email=f"user{i}@example.com",
                provider="gmail",
                user_id=i + 1,
            ))
        db_session.commit()

        user2_accounts = db_session.query(Account).filter_by(user_id=2).all()
        assert len(user2_accounts) == 1
        assert user2_accounts[0].email == "user1@example.com"


# ============================================================================
# 12. ACTIVATE — user_id PASSED TO switch_to
# ============================================================================


class TestActivatePassesUserId:
    """Tests pour activate_account() qui passe user_id à switch_to()."""

    def test_activate_passes_user_id_to_switch(self, client, mock_account_manager):
        """POST /accounts/<id>/activate passe user_id à switch_to()."""
        account = AccountConfig(
            id="acc1", name="Test", email="t@e.com", provider="gmail", user_id=42,
        )
        mock_account_manager.get_account.return_value = account
        mock_account_manager.switch_to.return_value = MagicMock()  # AccountContext

        with patch("app.api.accounts._get_auth_user_id", return_value=42):
            with patch("app.api.accounts._check_account_ownership", return_value=True):
                # _is_loopback must return True for auth guard (1st call),
                # then False inside activate_account (2nd call) so effective_user_id = auth_user_id
                with patch("app.api.auth._is_loopback", side_effect=[True, False]):
                    # Mock les imports dans activate_account
                    with patch("app.api.accounts.get_db_session"):
                        with patch("app.api.accounts.AccountRepository"):
                            with patch("app.api.accounts._ensure_db_account"):
                                # Mock le cache clear
                                with patch("app.api.routes._email_cache", {}), \
                                     patch("app.api.routes._email_detail_cache", {}):
                                    response = client.post("/api/accounts/acc1/activate")

                    assert response.status_code == 200
                    # `allow_first_time_bind=False` ajouté au call site (audit
                    # multi-tenant 2026-04-29) — un nouvel onboarding ne doit
                    # pas pouvoir lier un compte à un user_id inattendu via une
                    # POST /activate.
                    mock_account_manager.switch_to.assert_called_once_with(
                        "acc1", user_id=42, allow_first_time_bind=False,
                    )
