from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from flask import Flask, jsonify
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.privacy import privacy_bp
from app.db.models import Account, Base, Draft, Email, LegalConsent


def test_delete_account_data_requires_confirmation():
    app = Flask(__name__)
    app.register_blueprint(privacy_bp)
    client = app.test_client()

    response = client.delete("/accounts/abc/data", json={})

    assert response.status_code == 400
    assert response.get_json()["code"] == "CONFIRMATION_REQUIRED"


def test_delete_account_data_delegates_to_account_delete(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(privacy_bp)
    client = app.test_client()

    def _fake_delete(account_id: str):
        return jsonify({"success": True, "account_id": account_id})

    monkeypatch.setattr("app.api.accounts.delete_account", _fake_delete)

    response = client.delete("/accounts/abc/data", json={"confirm": "DELETE"})

    assert response.status_code == 200
    assert response.get_json() == {"success": True, "account_id": "abc"}


def test_record_legal_consent_requires_explicit_acceptance():
    app = Flask(__name__)
    app.register_blueprint(privacy_bp)
    client = app.test_client()

    response = client.post("/consents", json={"provider": "gmail", "accepted": False})

    assert response.status_code == 400
    assert response.get_json()["code"] == "CONSENT_REQUIRED"


def test_record_legal_consent_persists_ip_user_agent_and_versions(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    @contextmanager
    def fake_db_session():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr("app.api.privacy.get_db_session", fake_db_session)

    app = Flask(__name__)
    app.register_blueprint(privacy_bp)
    client = app.test_client()

    response = client.post(
        "/consents",
        json={
            "accepted": True,
            "provider": "gmail",
            "terms_version": "terms-v1",
            "privacy_version": "privacy-v1",
        },
        headers={
            "User-Agent": "Agentys Test Browser",
            "X-Forwarded-For": "203.0.113.42, 10.0.0.1",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["success"] is True

    with Session() as session:
        rows = session.query(LegalConsent).all()
        assert len(rows) == 1
        consent = rows[0]
        assert consent.id == payload["consent_id"]
        assert consent.provider == "gmail"
        assert consent.terms_version == "terms-v1"
        assert consent.privacy_version == "privacy-v1"
        assert consent.ip_address == "203.0.113.42"
        assert consent.user_agent == "Agentys Test Browser"


def test_export_account_data_omits_content_and_tokens(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session.begin() as session:
        account = Account(
            id=1,
            email="owner@example.com",
            provider="gmail",
            display_name="Owner",
            access_token=None,
            refresh_token=None,
        )
        email = Email(
            id=10,
            email_id="msg-1",
            thread_id="thread-1",
            account_id=1,
            subject="Exportable subject",
            sender="sender@example.com",
            recipients="owner@example.com",
            date=datetime(2026, 5, 16, tzinfo=timezone.utc),
            body_text="secret body",
            body_html="<p>secret body</p>",
            snippet="secret snippet",
            raw_headers='{"authorization":"secret"}',
        )
        draft = Draft(
            id=20,
            account_id=1,
            original_email_id=10,
            subject="Draft subject",
            body_text="draft body",
            body_html="<p>draft body</p>",
            generation_prompt="free-form prompt",
            user_edits="free-form edit",
            feedback_notes="free-form feedback",
            tokens_used=12,
        )
        session.add_all([account, email, draft])

    @contextmanager
    def fake_db_session():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("app.api.privacy.get_db_session", fake_db_session)
    monkeypatch.setattr("app.api.onboarding._resolve_db_account_id", lambda _account_id: 1)

    app = Flask(__name__)
    app.register_blueprint(privacy_bp)
    client = app.test_client()

    response = client.get("/accounts/hash-id/data")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["account_id"] == "hash-id"
    assert payload["tables"]["emails"][0]["subject"] == "Exportable subject"
    assert payload["tables"]["drafts"][0]["tokens_used"] == 12

    exported = str(payload)
    assert "secret body" not in exported
    assert "secret snippet" not in exported
    assert "free-form prompt" not in exported
    assert "free-form edit" not in exported
    assert "free-form feedback" not in exported
    assert "authorization" not in exported
