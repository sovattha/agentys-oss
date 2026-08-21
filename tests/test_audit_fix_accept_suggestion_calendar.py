# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix: accept_suggestion truthful calendar sync status.

Pré-fix, ``POST /api/calendar/suggestions/<id>/accept`` ignorait la valeur de
retour de ``_sync_followup_to_calendar`` et renvoyait toujours
``success: true`` / ``calendar_event_id: None`` même quand
``adapter.create_event`` échouait silencieusement (try/except qui avalait
l'erreur). Le frontend croyait l'événement créé alors qu'il ne l'était pas.

Le fix :
- ``_sync_followup_to_calendar`` retourne désormais l'``event_id`` (ou None)
- ``accept_suggestion`` expose ``calendar_synced: bool`` + le vrai
  ``calendar_event_id`` dans le JSON (statut 200 inchangé).

Pattern suivi : tests/test_calendar_user_isolation.py

pytest tests/test_audit_fix_accept_suggestion_calendar.py -v
"""

import uuid
from datetime import datetime, timezone

import pytest
from unittest.mock import MagicMock, patch

from app.api.app import create_app


@pytest.fixture
def app():
    """Crée une instance de l'application Flask pour les tests."""
    return create_app({"TESTING": True})


@pytest.fixture
def client(app):
    """Client de test sans JWT (mode Tauri desktop)."""
    return app.test_client()


@pytest.fixture(autouse=True)
def calendar_db(monkeypatch, tmp_path):
    """Tables ``followups`` + ``calendar_suggestions`` SQLite mémoire
    (migrations 041/042), imports legacy neutralisés. La DB est fraîche par
    test — plus d'état module-level à isoler entre tests du shard CI."""
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.services.calendar_suggestion_store as sugg_store
    import app.services.followup_store as fu_store
    from app.db.models import Base

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)

    @contextmanager
    def _cm():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr("app.db.database.get_db_session", _cm)
    monkeypatch.setattr(fu_store, "FOLLOWUPS_FILE", str(tmp_path / "followups.json"))
    monkeypatch.setattr(fu_store, "_legacy_import_done", False)
    monkeypatch.setattr(
        sugg_store, "SUGGESTIONS_FILE", str(tmp_path / "calendar_suggestions.json")
    )
    monkeypatch.setattr(sugg_store, "_legacy_import_done", False)
    yield _cm
    engine.dispose()


def _seed_suggestion():
    """Insère une suggestion pending isolée (table 042) et renvoie son id."""
    from app.services import calendar_suggestion_store

    suggestion_id = f"test-{uuid.uuid4()}"
    calendar_suggestion_store.save_record(suggestion_id, {
        "email_id": "e1",
        "account_id": "acc-a",
        "description": "Relancer le client",
        "deadline": None,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "email_subject": "Projet X",
        "email_sender": "client@test.com",
        "draft_body_preview": "",
    })
    return suggestion_id


def _accept(client, suggestion_id, create_event_return):
    """Drive la route accept avec un adapter dont create_event renvoie la valeur
    fournie (None = échec silencieux, str = succès)."""
    adapter = MagicMock()
    adapter.create_event.return_value = create_event_return

    from app.api import calendar as calendar_module

    # Ownership ouvert (mode Tauri) + pas d'écriture disque globale.
    with patch.object(calendar_module, "_validate_account_ownership", return_value="acc-a"), \
         patch.object(calendar_module, "_get_calendar_adapter", return_value=adapter):
        # Le harness HTTP + état module-level de calendar diverge entre local et
        # CI Linux (voir tests/test_calendar_user_isolation.py). Appeler la vue
        # directement garde le test centré sur le contrat calendar_synced.
        with client.application.test_request_context(
            f"/api/calendar/suggestions/{suggestion_id}/accept",
            method="POST",
            json={"sync_to_calendar": True},
        ):
            resp = calendar_module.accept_suggestion(suggestion_id)
    return resp


def test_accept_suggestion_calendar_synced_false_when_create_event_fails(client):
    """create_event renvoie None (échec silencieux) → calendar_synced=False,
    calendar_event_id=None, mais statut 200 préservé (callers non cassés)."""
    suggestion_id = _seed_suggestion()
    resp = _accept(client, suggestion_id, create_event_return=None)

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["calendar_synced"] is False
    assert data["calendar_event_id"] is None


def test_accept_suggestion_calendar_synced_true_on_success(client):
    """create_event renvoie un id → calendar_synced=True + le vrai event_id."""
    suggestion_id = _seed_suggestion()
    resp = _accept(client, suggestion_id, create_event_return="cal-event-123")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["calendar_synced"] is True
    assert data["calendar_event_id"] == "cal-event-123"


def test_sync_followup_helper_returns_event_id(app):
    """Régression directe sur le helper : il doit RETOURNER l'event_id au lieu
    de l'avaler. None quand create_event échoue, l'id quand il réussit."""
    from app.api import calendar as calendar_module

    followup = {"due_date": "2026-01-01T10:00:00+00:00", "title": "t"}

    ok_adapter = MagicMock()
    ok_adapter.create_event.return_value = "evt-9"
    fail_adapter = MagicMock()
    fail_adapter.create_event.return_value = None

    with patch.object(calendar_module, "_get_calendar_adapter", return_value=ok_adapter):
        assert calendar_module._sync_followup_to_calendar("f1", followup, "acc-a") == "evt-9"
    with patch.object(calendar_module, "_get_calendar_adapter", return_value=fail_adapter):
        assert calendar_module._sync_followup_to_calendar("f2", followup, "acc-a") is None
