"""Sent-email detail must not 404 when the provider can't serve the id.

Bug (2026-06-11, app.agentys.io): clicking a Sent row showed
« Error: Email not found ». Root cause: replies insert a synthetic
``reply-<ts>`` placeholder row for immediate Sent visibility; on
deployments without email-content persistence ``dedupe_sent_by_content``
can never reconcile it with the real provider message, and the detail
route's sent branch had no SQLite fallback — provider miss + cold list
cache → hard 404.

These tests pin the fixed contract:
- provider miss + SQLite row → 200 served from SQLite (was: 404)
- synthetic ``reply-<ts>`` ids must NOT claim ``body_fetch_pending``
  (no provider counterpart — the frontend would poll forever)
- provider miss + no SQLite row → still 404 (regression guard)
- gmail_adapter denies ``reply-<ts>`` outright (no wasted Gmail call)
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def app():
    from app.api.app import create_app

    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _db_row(email_id="reply-1718000000", body_text=None, snippet=None):
    """A no-body SQLite Email row, as produced by the reply-time sent-cache
    insert when should_persist_email_content() is off."""
    return SimpleNamespace(
        email_id=email_id,
        thread_id="thread-abc",
        subject="Re: Question",
        sender="me@example.com",
        sender_name="",
        recipients="alexandra@example.com",
        cc=None,
        bcc=None,
        date=None,
        body_text=body_text,
        body_html=None,
        snippet=snippet,
        is_read=True,
        is_starred=False,
        attachments_meta=None,
    )


@contextmanager
def _sent_detail_harness(db_row, provider_email=None):
    """Force the detail route down the sent branch: caches cold, provider
    misses, SQLite returns `db_row` (or None)."""
    provider = Mock()
    provider.get_message_by_id.return_value = provider_email

    fake_repo = Mock()
    fake_repo.get_by_email_id.return_value = db_row
    fake_repo.exists_by_email_id.return_value = db_row is not None

    @contextmanager
    def fake_session():
        yield Mock()

    with patch("app.api.routes_emails._get_cached_email_detail", return_value=None), \
         patch("app.api.routes_emails._find_email_in_list_cache", return_value=None), \
         patch("app.api.routes_emails._find_sent_email_in_list_cache", return_value=None), \
         patch("app.api.routes_emails._get_pending_draft_email_ids", return_value=set()), \
         patch("app.api.routes_emails._fetch_body_html_background") as bg_fetch, \
         patch("app.api.routes_helpers.get_db_session", fake_session), \
         patch("app.api.routes_helpers.EmailRepository", return_value=fake_repo), \
         patch("app.api.routes_emails._get_authenticated_provider", return_value=provider):
        yield SimpleNamespace(provider=provider, repo=fake_repo, bg_fetch=bg_fetch)


class TestSentDetailSqliteFallback:
    def test_synthetic_reply_id_served_from_sqlite_not_404(self, client):
        """The exact prod repro: sent:reply-<ts>, provider miss, no-body row."""
        with _sent_detail_harness(_db_row("reply-1718000000")):
            resp = client.get("/api/emails/sent:reply-1718000000")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data["subject"] == "Re: Question"
        assert data["to"] == ["alexandra@example.com"]
        # No provider counterpart: must not tell the frontend a body is coming.
        assert data.get("body_fetch_pending") is False

    def test_real_sent_id_provider_miss_keeps_body_fetch_pending(self, client):
        """A real Gmail id that transiently misses still serves headers, but
        keeps the body fetch pending so the background refresh can land."""
        with _sent_detail_harness(_db_row("1a2b3c4d5e6f7a8b")):
            resp = client.get("/api/emails/sent:1a2b3c4d5e6f7a8b")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json().get("body_fetch_pending") is True

    def test_sent_id_without_sqlite_row_still_404(self, client):
        with _sent_detail_harness(None):
            resp = client.get("/api/emails/sent:19eb000000000000")

        assert resp.status_code == 404

    def test_sqlite_row_with_body_serves_body(self, client):
        """Content-persisting deployments serve the stored body text."""
        row = _db_row("reply-1718000001", body_text="Salut Alexandra, Merci beaucoup!")
        with _sent_detail_harness(row):
            resp = client.get("/api/emails/sent:reply-1718000001")

        assert resp.status_code == 200
        assert "Salut Alexandra" in (resp.get_json().get("body") or "")


class TestGmailSyntheticIdDenylist:
    @pytest.mark.parametrize("bad_id", [
        "reply-1718000000",
        "email-42",
        "draft-abc123",
        "test-email-id",
        "PYTHON-FLASK-B7",
    ])
    def test_synthetic_ids_denied(self, bad_id):
        from app.providers.gmail_adapter import _is_gmail_message_id

        assert _is_gmail_message_id(bad_id) is False

    @pytest.mark.parametrize("real_id", [
        "1a2b3c4d5e6f7a8b",          # Gmail-shaped opaque hex id
        "reply-not-numeric",          # only the numeric placeholder form is ours
        "CAOU+8LMfxVoUiHV@mail.com",  # RFC-2822-ish opaque id
    ])
    def test_real_ids_allowed(self, real_id):
        from app.providers.gmail_adapter import _is_gmail_message_id

        assert _is_gmail_message_id(real_id) is True
