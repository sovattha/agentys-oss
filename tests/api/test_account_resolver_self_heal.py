# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression tests — onglets Corbeille/Spam morts quand la ligne `accounts` DB manque
(rapport Karine, 2026-06-09).

Etat pathologique reproduit : le compte OAuth existe et fonctionne (AccountManager /
email_accounts.json + tokens valides) mais la ligne `accounts` SQLite/PG est absente
(DB recréée après corruption, `db_sync_failed` au callback OAuth, désync
accounts.json↔DB). Tous les resolvers renvoyaient alors le sentinel -1 :

  - GET /api/emails?folder=trash|spam lisait SQLite avec account_id=-1 (0 lignes),
    enfilait un sync job condamné (résolution OAuth impossible pour -1) et répondait
    `sync_in_progress: true` à l'infini — le frontend affichait ~72 s de skeleton
    puis un faux état vide, à chaque visite. La sync d'arrière-plan récupérait bien
    les emails du provider puis les JETAIT ("invalid account_id=-1 — aborting
    SQLite writes").
  - L'inbox survivait via le cache mémoire clé par hash OAuth, d'où le symptôme
    asymétrique « seuls Corbeille/Spam ne s'ouvrent pas ».

Fix : _resolve_account_id_for_email s'auto-guérit en recréant la ligne DB manquante
depuis la config AccountManager (même insert que le callback OAuth), et le chemin
DB-miss de /api/emails ne prétend plus `sync_in_progress` quand aucun sync n'est
possible (account_id <= 0) ni n'enfile de job condamné.

pytest tests/api/test_account_resolver_self_heal.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


KARINE = "karine.morel@gmail.com"


def _fresh_temp_db(tmp_path, monkeypatch, name: str):
    """Point the engine at an empty temp SQLite DB (no accounts row)."""
    from app.db.database import init_db, reset_engine

    db_path = tmp_path / name
    monkeypatch.setenv("AGENTYS_DB_PATH", str(db_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_engine()
    init_db()
    return db_path


def _clear_resolver_state():
    """Drop the resolver's positive cache AND the heal cooldown between tests."""
    from app.api import routes_helpers as rh

    rh._invalidate_account_id_cache()
    rh._heal_attempts.clear()


@pytest.fixture(autouse=True)
def _engine_cleanup():
    yield
    from app.db.database import reset_engine

    reset_engine()
    _clear_resolver_state()


def _manager_with(email: str | None, **cfg_attrs):
    """Fake AccountManager: knows `email` (or nothing when email is None)."""
    manager = MagicMock()
    if email is None:
        manager.get_account_by_email.return_value = None
    else:
        cfg = MagicMock()
        cfg.email = email
        cfg.provider = cfg_attrs.get("provider", "gmail")
        cfg.name = cfg_attrs.get("name", "Karine")
        cfg.user_id = cfg_attrs.get("user_id", 777)
        manager.get_account_by_email.return_value = cfg
    return manager


def test_resolver_heals_missing_db_account_from_manager(tmp_path, monkeypatch):
    """Ligne DB absente + compte connu du AccountManager → la ligne est recréée
    et le resolver renvoie son id (pas le sentinel -1)."""
    from app.api import routes_helpers as rh
    from app.db.database import get_db_session
    from app.db.repositories.account_repository import AccountRepository

    _fresh_temp_db(tmp_path, monkeypatch, "heal_ok.db")
    _clear_resolver_state()

    with patch("app.multi_accounts.get_account_manager", return_value=_manager_with(KARINE)):
        resolved = rh._resolve_account_id_for_email(KARINE)

    assert resolved > 0, f"resolver returned sentinel {resolved} instead of healing"

    with get_db_session() as session:
        row = AccountRepository(session).get_by_email(KARINE)
        assert row is not None
        assert row.id == resolved
        assert row.is_active is True
        assert row.provider == "gmail"
        assert row.user_id == 777


def test_resolver_returns_sentinel_when_manager_unknown(tmp_path, monkeypatch):
    """Email inconnu du AccountManager (ex: JWT pré-OAuth) → sentinel -1, AUCUNE
    ligne créée (pas de minting de comptes pour des identités arbitraires)."""
    from app.api import routes_helpers as rh
    from app.db.database import get_db_session
    from app.db.repositories.account_repository import AccountRepository

    _fresh_temp_db(tmp_path, monkeypatch, "heal_unknown.db")
    _clear_resolver_state()

    with patch("app.multi_accounts.get_account_manager", return_value=_manager_with(None)):
        resolved = rh._resolve_account_id_for_email("stranger@example.com")

    assert resolved == rh._NO_ACCOUNT_SENTINEL
    with get_db_session() as session:
        assert AccountRepository(session).get_by_email("stranger@example.com") is None


def test_heal_is_idempotent_when_row_already_exists(tmp_path, monkeypatch):
    """Si la ligne existe déjà (course avec le callback OAuth), le heal renvoie
    l'id existant sans tenter un doublon."""
    from app.api import routes_helpers as rh
    from app.db.database import get_db_session
    from app.db.models.account import Account

    _fresh_temp_db(tmp_path, monkeypatch, "heal_race.db")
    _clear_resolver_state()

    with get_db_session() as session:
        session.add(Account(email=KARINE, provider="gmail", user_id=777))
        session.commit()

    with patch("app.multi_accounts.get_account_manager", return_value=_manager_with(KARINE)):
        first = rh._resolve_account_id_for_email(KARINE)
        healed_again = rh._heal_missing_db_account(KARINE)

    assert first > 0
    assert healed_again == first


def test_heal_failure_is_cooled_down(tmp_path, monkeypatch):
    """Un heal qui échoue (ex: INSERT refusé) ne doit pas marteler la DB à chaque
    requête : la 2e tentative dans la fenêtre de cooldown est un no-op."""
    from app.api import routes_helpers as rh

    _fresh_temp_db(tmp_path, monkeypatch, "heal_cooldown.db")
    _clear_resolver_state()

    manager = _manager_with(KARINE)
    with patch("app.multi_accounts.get_account_manager", return_value=manager):
        with patch.object(rh, "get_db_session", side_effect=RuntimeError("insert refused")):
            assert rh._heal_missing_db_account(KARINE) is None
        # Within cooldown: no second manager lookup / insert attempt
        calls_before = manager.get_account_by_email.call_count
        assert rh._heal_missing_db_account(KARINE) is None
        assert manager.get_account_by_email.call_count == calls_before


def test_heal_suppressed_during_account_deletion(tmp_path, monkeypatch):
    """Pendant la suppression d'un compte (ligne DB effacée AVANT l'entrée
    manager), le heal est bloqué par _suppress_account_heal — sinon un poll
    /api/emails concurrent ressusciterait la ligne en compte fantôme. La
    reconnexion OAuth (_invalidate_account_id_cache) lève le blocage."""
    from app.api import routes_helpers as rh
    from app.db.database import get_db_session
    from app.db.repositories.account_repository import AccountRepository

    _fresh_temp_db(tmp_path, monkeypatch, "heal_suppressed.db")
    _clear_resolver_state()

    with patch("app.multi_accounts.get_account_manager", return_value=_manager_with(KARINE)):
        rh._suppress_account_heal(KARINE)
        resolved = rh._resolve_account_id_for_email(KARINE)
        assert resolved == rh._NO_ACCOUNT_SENTINEL
        with get_db_session() as session:
            assert AccountRepository(session).get_by_email(KARINE) is None, (
                "heal resurrected the account row mid-deletion"
            )

        # OAuth re-connect lifts the suppression
        rh._invalidate_account_id_cache(KARINE)
        resolved_after = rh._resolve_account_id_for_email(KARINE)
        assert resolved_after > 0


def test_emails_endpoint_no_fake_syncing_when_account_unresolvable(tmp_path, monkeypatch):
    """GET /api/emails?folder=trash avec compte OAuth présent mais irrésoluble en DB
    (heal impossible) : la réponse ne doit PAS prétendre `sync_in_progress` (le
    frontend bouclait 72 s de skeleton dessus) et aucun sync job ne doit être enfilé
    pour le sentinel -1."""
    from app.api.app import create_app

    _fresh_temp_db(tmp_path, monkeypatch, "endpoint_honesty.db")
    _clear_resolver_state()

    app = create_app(config={"TESTING": True})
    client = app.test_client()

    current = MagicMock()
    current.email = "ghost@example.com"
    current.id = "hash-ghost"

    enqueued: list[dict] = []

    def _record_enqueue(**kwargs):
        enqueued.append(kwargs)
        return MagicMock()

    with patch("app.api.routes_emails._get_current_account_for_user", return_value=current), \
         patch("app.multi_accounts.get_account_manager", return_value=_manager_with(None)), \
         patch("app.services.sync_jobs.enqueue_sync_job", side_effect=_record_enqueue):
        resp = client.get("/api/emails?limit=10&offset=0&filter=all&folder=trash")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["emails"] == []
    assert data.get("sync_in_progress") in (False, None), (
        "endpoint still pretends a sync is running for an unresolvable account"
    )
    assert enqueued == [], f"doomed sync job enqueued for sentinel account: {enqueued}"
