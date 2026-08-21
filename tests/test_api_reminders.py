# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les endpoints /api/reminders (GET, POST, DELETE)
et le service ReminderService (unit tests sans Flask).

Pattern identique à test_api_followups.py :
- Flask app via create_app(config={"TESTING": True})
- Services mockés via unittest.mock.patch
"""

import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")

TEST_ACCOUNT_ID = 1


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def app():
    """Application Flask de test."""
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Client de test Flask."""
    return app.test_client()


@pytest.fixture(autouse=True)
def account_scope():
    """Stabilise le scope compte attendu par les routes reminders."""
    with patch(
        "app.api.routes_helpers._resolve_account_id_for_user",
        return_value=TEST_ACCOUNT_ID,
    ):
        yield


# ============================================================================
# HELPERS
# ============================================================================


def _make_reminder(
    reminder_id: str = "reminder-abc",
    email_id: str = "email-123",
    subject: str = "Rappel test",
    reminder_date: str | None = None,
    notified: bool = False,
    account_id: int | None = TEST_ACCOUNT_ID,
) -> dict:
    if reminder_date is None:
        reminder_date = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    return {
        "id": reminder_id,
        "email_id": email_id,
        "subject": subject,
        "reminder_date": reminder_date,
        "notified": notified,
        "account_id": account_id,
    }


def _future_iso(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ============================================================================
# TESTS — GET /api/reminders
# ============================================================================


class TestListReminders:
    """Tests pour GET /api/reminders."""

    @patch("app.services.reminder_service._read")
    def test_returns_200_with_reminders_key(self, mock_read, client):
        """GET /api/reminders retourne 200 avec la clé 'reminders'."""
        mock_read.return_value = [_make_reminder()]

        response = client.get("/api/reminders")

        assert response.status_code == 200
        data = response.get_json()
        assert "reminders" in data
        assert isinstance(data["reminders"], list)

    @patch("app.services.reminder_service._read")
    def test_returns_empty_list_when_no_reminders(self, mock_read, client):
        """GET retourne {"reminders": []} quand aucun rappel n'existe."""
        mock_read.return_value = []

        response = client.get("/api/reminders")

        assert response.status_code == 200
        assert response.get_json()["reminders"] == []

    @patch("app.services.reminder_service._read")
    def test_reminder_contains_expected_fields(self, mock_read, client):
        """Chaque rappel expose les champs id, email_id, subject, reminder_date, notified."""
        reminder = _make_reminder(
            reminder_id="r-field-check",
            email_id="e-42",
            subject="Vérification des champs",
            notified=False,
        )
        mock_read.return_value = [reminder]

        response = client.get("/api/reminders")

        r = response.get_json()["reminders"][0]
        assert r["id"] == "r-field-check"
        assert r["email_id"] == "e-42"
        assert r["subject"] == "Vérification des champs"
        assert "reminder_date" in r
        assert r["notified"] is False


# ============================================================================
# TESTS — POST /api/reminders
# ============================================================================


class TestCreateReminder:
    """Tests pour POST /api/reminders."""

    @patch("app.services.reminder_service.add_reminder")
    def test_success_returns_201_with_id_and_success(self, mock_add, client):
        """POST valide → 201 + {"id": "...", "success": true}."""
        mock_add.return_value = "generated-uuid-1"

        response = client.post(
            "/api/reminders",
            json={
                "email_id": "email-001",
                "subject": "Relance client",
                "reminder_date": _future_iso(),
            },
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["id"] == "generated-uuid-1"
        assert data["success"] is True

    def test_missing_email_id_returns_400(self, client):
        """POST sans email_id → 400 avec message d'erreur."""
        response = client.post(
            "/api/reminders",
            json={"subject": "Sans email_id", "reminder_date": _future_iso()},
        )

        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_missing_reminder_date_returns_400(self, client):
        """POST sans reminder_date → 400."""
        response = client.post(
            "/api/reminders",
            json={"email_id": "email-002", "subject": "Sans date"},
        )

        assert response.status_code == 400

    def test_empty_body_returns_400(self, client):
        """POST avec corps vide → 400."""
        response = client.post(
            "/api/reminders",
            data="",
            content_type="application/json",
        )

        assert response.status_code == 400

    @patch("app.services.reminder_service.add_reminder")
    def test_subject_optional_empty_string_accepted(self, mock_add, client):
        """subject est optionnel : POST sans subject → 201, add_reminder appelé avec subject=''."""
        mock_add.return_value = "uuid-no-subject"

        response = client.post(
            "/api/reminders",
            json={"email_id": "email-003", "reminder_date": _future_iso()},
        )

        assert response.status_code == 201
        mock_add.assert_called_once()
        _email_id, subject_arg, _date = mock_add.call_args[0]
        assert subject_arg == ""

    @patch("app.services.reminder_service.add_reminder")
    def test_duplicate_email_id_both_calls_reach_service(self, mock_add, client):
        """POST avec même email_id → add_reminder appelé deux fois (dédup dans le service)."""
        mock_add.side_effect = ["id-first", "id-second"]

        client.post(
            "/api/reminders",
            json={"email_id": "dup-email", "subject": "Premier", "reminder_date": _future_iso(48)},
        )
        response = client.post(
            "/api/reminders",
            json={"email_id": "dup-email", "subject": "Mis à jour", "reminder_date": _future_iso(72)},
        )

        assert response.status_code == 201
        assert mock_add.call_count == 2


# ============================================================================
# TESTS — DELETE /api/reminders/<id>
# ============================================================================


class TestDeleteReminder:
    """Tests pour DELETE /api/reminders/<reminder_id>."""

    @patch("app.services.reminder_service.dismiss_reminder")
    def test_delete_returns_200_success(self, mock_dismiss, client):
        """DELETE /api/reminders/<id> → 200 + {"success": true}."""
        response = client.delete("/api/reminders/reminder-to-delete")

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        mock_dismiss.assert_called_once_with("reminder-to-delete", account_id=TEST_ACCOUNT_ID)

    @patch("app.services.reminder_service.dismiss_reminder")
    def test_delete_unknown_id_is_idempotent(self, mock_dismiss, client):
        """DELETE avec ID inexistant → 200 (dismiss_reminder est idempotent)."""
        response = client.delete("/api/reminders/id-qui-nexiste-pas")

        assert response.status_code == 200
        assert response.get_json()["success"] is True


# ============================================================================
# TESTS — ReminderService (unit, sans Flask)
# ============================================================================


class TestReminderService:
    """Tests unitaires du service reminder (sans Flask ni I/O réelle)."""

    def test_add_reminder_returns_valid_uuid(self, tmp_path, monkeypatch):
        """add_reminder() retourne un UUID valide."""
        import app.services.reminder_service as svc

        monkeypatch.setattr(svc, "_REMINDERS_FILE", tmp_path / "reminders.json")

        result = svc.add_reminder("email-x", "Sujet X", _future_iso())

        # Lève ValueError si ce n'est pas un UUID valide
        uuid.UUID(result)

    def test_get_all_pending_excludes_notified(self, tmp_path, monkeypatch):
        """get_all_pending() n'inclut pas les rappels notified=True."""
        import app.services.reminder_service as svc

        reminders_file = tmp_path / "reminders.json"
        reminders_file.write_text(
            json.dumps([
                _make_reminder("r-pending", notified=False),
                _make_reminder("r-done", email_id="email-done", notified=True),
            ]),
            encoding="utf-8",
        )
        monkeypatch.setattr(svc, "_REMINDERS_FILE", reminders_file)

        pending = svc.get_all_pending()

        assert len(pending) == 1
        assert pending[0]["id"] == "r-pending"
        assert all(not r["notified"] for r in pending)

    def test_dismiss_reminder_removes_only_target(self, tmp_path, monkeypatch):
        """dismiss_reminder() supprime uniquement l'ID ciblé."""
        import app.services.reminder_service as svc

        reminders_file = tmp_path / "reminders.json"
        reminders_file.write_text(
            json.dumps([
                _make_reminder("r-keep", email_id="email-keep"),
                _make_reminder("r-delete", email_id="email-delete"),
            ]),
            encoding="utf-8",
        )
        monkeypatch.setattr(svc, "_REMINDERS_FILE", reminders_file)

        svc.dismiss_reminder("r-delete")

        remaining = json.loads(reminders_file.read_text(encoding="utf-8"))
        assert len(remaining) == 1
        assert remaining[0]["id"] == "r-keep"

    @patch("app.services.reminder_service._mark_notified")
    def test_check_and_notify_marks_only_due_reminders(self, mock_mark_notified, tmp_path, monkeypatch):
        """check_and_notify() appelle _mark_notified uniquement pour les rappels échus."""
        import app.services.reminder_service as svc

        reminders_file = tmp_path / "reminders.json"
        reminders_file.write_text(
            json.dumps([
                _make_reminder("r-due", reminder_date=_past_iso(2), notified=False),
                _make_reminder("r-future", email_id="email-future", reminder_date=_future_iso(24), notified=False),
            ]),
            encoding="utf-8",
        )
        monkeypatch.setattr(svc, "_REMINDERS_FILE", reminders_file)

        svc.check_and_notify()

        # Seul le rappel échu doit être notifié
        mock_mark_notified.assert_called_once_with("r-due")
