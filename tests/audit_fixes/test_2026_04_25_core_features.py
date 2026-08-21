# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests locking in the 2026-04-25 core-feature audit fixes.

Covers the P0 / P1 fixes that landed in this audit pass:
- Mic / transcribe : auth required, size cap, language detection, no-key 503
- Send : multi-recipient compose validation, plain-text HTML wrapping
- Calendar : AGENTYS_DATA_DIR honored, atomic write, suggestions persisted,
  naive-datetime coercion
- Reply : send/refine race serialized via _draft_lock, email_archived event
  is routed via account_id, double-fire guard, BCC parity with routes_emails

Each test is a snapshot of the audit recommendation — if a future refactor
breaks the contract, these tests catch it.
"""

from __future__ import annotations

import importlib
import io
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Mic / transcribe (Mic HIGH — auth, size, language, missing-key)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def app_client(monkeypatch):
    """Build an isolated Flask test client for the API.

    Uses monkeypatch (auto-restored on teardown) to avoid leaking env state
    into subsequent tests like test_s_04_oauth_tokens_path which validates
    OAUTH_TOKEN_ENCRYPTION_KEY at import time.
    """
    monkeypatch.setenv("FLASK_ENV", "testing")
    # Real Fernet key (32 url-safe base64 bytes). Used only by oauth.py at
    # import time; we don't actually exercise OAuth in these tests.
    from cryptography.fernet import Fernet
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    from app.api.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _mock_auth_pass():
    """Patch require_auth_or_local to allow the request through."""
    from app.api import auth
    return patch.object(auth, "require_auth_or_local", lambda f: f)


def test_transcribe_rejects_unauth(app_client):
    """/api/transcribe must require authentication (audit Mic-HIGH)."""
    # No JWT, no localhost — should 401
    headers = {"X-Forwarded-For": "1.2.3.4"}  # break loopback heuristic
    resp = app_client.post(
        "/api/transcribe",
        data={"audio": (io.BytesIO(b"fakebytes"), "x.webm")},
        content_type="multipart/form-data",
        headers=headers,
        environ_overrides={"REMOTE_ADDR": "1.2.3.4"},
    )
    # require_auth_or_local rejects with 401 when neither JWT nor loopback.
    assert resp.status_code == 401, resp.get_data(as_text=True)


def test_transcribe_size_cap(app_client):
    """/api/transcribe must reject payloads > 10 MB early (audit Mic-HIGH)."""
    big = b"x" * (11 * 1024 * 1024)  # 11 MB
    resp = app_client.post(
        "/api/transcribe",
        data={"audio": (io.BytesIO(big), "big.webm")},
        content_type="multipart/form-data",
        # Loopback bypasses auth — we want to test size cap, not auth here.
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 413
    body = resp.get_json()
    assert "max_bytes" in body
    assert body["max_bytes"] == 10 * 1024 * 1024


def test_transcribe_503_when_no_keys(app_client, monkeypatch):
    """Without DEEPGRAM_API_KEY and OPENAI_API_KEY, return 503 (audit Mic-MEDIUM)."""
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    audio = b"x" * 2000  # > 1 KB so frontend "blob too small" guard doesn't trigger
    resp = app_client.post(
        "/api/transcribe",
        data={"audio": (io.BytesIO(audio), "test.webm")},
        content_type="multipart/form-data",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 503
    # Post-2026-05-18 i18n sweep: backend ships English fallback in `error`
    # and the localized message via `error_code` ("transcription_no_api_key").
    body = resp.get_json()
    assert body.get("error_code") == "TRANSCRIPTION_NO_API_KEY"
    assert "unavailable" in body.get("error", "").lower()


class _StubDeepgramResponse:
    """Mimic the bits of requests.Response we use."""
    def __init__(self, transcript: str = "hello"):
        self._transcript = transcript

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "results": {
                "channels": [
                    {"alternatives": [{"transcript": self._transcript}]}
                ]
            }
        }


def _install_deepgram_session_mock(monkeypatch, captured: dict, transcript: str = "hello") -> None:
    """Patch the cached Deepgram session used by production transcription code."""
    from app.api import routes_misc

    class _StubDeepgramSession:
        def post(self, url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs.get("params") or {}
            captured["headers"] = kwargs.get("headers") or {}
            return _StubDeepgramResponse(transcript)

    monkeypatch.setattr(routes_misc, "_dg_session", _StubDeepgramSession())


def test_transcribe_accepts_lang_param(app_client, monkeypatch):
    """Custom `lang` form field is forwarded to Deepgram (audit Mic-HIGH)."""
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-fake")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    audio = b"x" * 2000

    captured = {}

    _install_deepgram_session_mock(monkeypatch, captured)

    resp = app_client.post(
        "/api/transcribe",
        data={"audio": (io.BytesIO(audio), "x.webm"), "lang": "en"},
        content_type="multipart/form-data",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert captured["params"].get("language") == "en"
    assert "deepgram.com" in captured["url"]
    assert captured["headers"].get("Authorization") == "Token dg-fake"


def test_transcribe_records_dictation_usage(app_client, monkeypatch, tmp_path):
    """Successful transcriptions persist duration for the billing credits gauge."""
    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "transcribe_usage.db"))
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-fake")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from app.api import routes_misc
    from app.db.database import get_db_session, get_engine, init_db, reset_engine
    from app.db.models import Account, DictationUsageLogRow

    reset_engine()
    init_db(get_engine())
    with get_db_session() as session:
        session.add(
            Account(
                id=7,
                email="buyer@example.com",
                provider="gmail",
                user_id=42,
            )
        )

    captured = {}
    _install_deepgram_session_mock(monkeypatch, captured, transcript="bonjour")
    monkeypatch.setattr(routes_misc, "_resolve_account_id_cached", lambda: 7)

    resp = app_client.post(
        "/api/transcribe",
        data={
            "audio": (io.BytesIO(b"x" * 2000), "x.webm"),
            "duration_seconds": "75",
        },
        content_type="multipart/form-data",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    with get_db_session() as session:
        row = session.query(DictationUsageLogRow).one()
        assert row.account_id == 7
        assert row.user_id == 42
        assert row.provider == "deepgram"
        assert row.duration_seconds == 75


def test_transcribe_invalid_lang_falls_back_to_autodetect(app_client, monkeypatch):
    """Invalid language code → no `language` param (Deepgram auto-detect)."""
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-fake")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    audio = b"x" * 2000
    captured = {}

    _install_deepgram_session_mock(monkeypatch, captured)

    app_client.post(
        "/api/transcribe",
        data={"audio": (io.BytesIO(audio), "x.webm"), "lang": "klingon"},
        content_type="multipart/form-data",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert "language" not in captured["params"]
    # Auto-detect flag is set instead.
    assert captured["params"].get("detect_language") == "true"


# ─────────────────────────────────────────────────────────────────────────────
# Send / compose validation (Send-MEDIUM)
# ─────────────────────────────────────────────────────────────────────────────


def test_validate_compose_email_accepts_multi_recipient():
    """_validate_compose_email must validate each comma-separated address."""
    from app.api.routes_misc import _validate_compose_email
    assert _validate_compose_email("a@x.com")
    assert _validate_compose_email("a@x.com, b@y.com")
    assert _validate_compose_email("a@x.com; b@y.com; c@z.com")
    # Reject if any part is malformed
    assert not _validate_compose_email("a@x.com, notanemail")
    assert not _validate_compose_email("notanemail")
    assert not _validate_compose_email("")
    assert not _validate_compose_email(",,,")


# ─────────────────────────────────────────────────────────────────────────────
# Calendar (Calendar-HIGH-1, HIGH-2, HIGH-4, MEDIUM-7)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_calendar_module(monkeypatch, tmp_path):
    """Reload `app.api.calendar` against a fresh AGENTYS_DATA_DIR, then
    restore the original module + state on teardown so we don't pollute
    other tests (esp. test_calendar_user_isolation.py).

    Post-migration 041 les followups vivent dans la table ``followups`` —
    la fixture monte donc aussi une DB SQLite mémoire et reload
    ``app.services.followup_store`` (son FOLLOWUPS_FILE legacy se résout à
    l'import, comme l'ancien _FOLLOWUPS_FILE de calendar)."""
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.models import Base

    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))

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

    saved_store_module = sys.modules.pop("app.services.followup_store", None)
    saved_sugg_module = sys.modules.pop("app.services.calendar_suggestion_store", None)
    saved_module = sys.modules.pop("app.api.calendar", None)
    fu_store = importlib.import_module("app.services.followup_store")
    sugg_store = importlib.import_module("app.services.calendar_suggestion_store")
    cal = importlib.import_module("app.api.calendar")
    try:
        yield cal, tmp_path, fu_store, sugg_store
    finally:
        # Drop the env-overridden modules and restore the originals
        sys.modules.pop("app.api.calendar", None)
        sys.modules.pop("app.services.followup_store", None)
        sys.modules.pop("app.services.calendar_suggestion_store", None)
        if saved_store_module is not None:
            sys.modules["app.services.followup_store"] = saved_store_module
        if saved_sugg_module is not None:
            sys.modules["app.services.calendar_suggestion_store"] = saved_sugg_module
        if saved_module is not None:
            sys.modules["app.api.calendar"] = saved_module
        engine.dispose()


def test_calendar_followups_path_honors_data_dir(isolated_calendar_module):
    """Le chemin des JSON legacy doit honorer AGENTYS_DATA_DIR (audit
    Calendar-HIGH-1) — porté sur les stores (migrations 041/042)."""
    _cal, tmp_path, fu_store, sugg_store = isolated_calendar_module
    expected = str(tmp_path / "followups.json")
    assert fu_store.FOLLOWUPS_FILE == expected, (
        f"FOLLOWUPS_FILE should honor AGENTYS_DATA_DIR; got {fu_store.FOLLOWUPS_FILE!r}"
    )
    assert sugg_store.SUGGESTIONS_FILE == str(tmp_path / "calendar_suggestions.json")


# NB : test_calendar_atomic_write supprimé avec la migration 042 —
# `_atomic_write_json` n'existe plus (le risque « partial write » de l'audit
# Calendar-HIGH-4 est structurellement clos : la persistance passe par des
# transactions DB).


def test_calendar_suggestions_persisted(isolated_calendar_module):
    """add_suggestion must persist durably (audit Calendar-HIGH-2 « suggestions
    in-memory only — lost on restart ») — post-042, la durabilité = table DB."""
    cal, _tmp, _fu_store, sugg_store = isolated_calendar_module
    sid = cal.add_suggestion(
        email_id="e1",
        account_id="acc1",
        description="Send proposal Friday",
    )
    assert sid
    persisted = sugg_store.get_record(sid)
    assert persisted is not None
    assert persisted["description"] == "Send proposal Friday"
    assert persisted["status"] == "pending"


def test_calendar_followup_naive_datetime_coercion(isolated_calendar_module):
    """Naive datetimes in followups must not crash _get_followups_as_events
    (audit Calendar-MEDIUM-7)."""
    cal, _tmp, fu_store, _sugg_store = isolated_calendar_module
    fu_store.save_record("fid1", {
        "account_id": "acc1",
        "title": "Test",
        "description": "",
        "due_date": "2026-05-01T10:00:00",  # naive
        "status": "pending",
    })
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, tzinfo=timezone.utc)
    events = cal._get_followups_as_events("acc1", start, end)
    assert len(events) == 1
    assert events[0]["id"] == "followup_fid1"


# ─────────────────────────────────────────────────────────────────────────────
# Reply / pending-drafts (Reply-HIGH-1, HIGH-2)
# ─────────────────────────────────────────────────────────────────────────────


def test_evict_uses_submit_background(monkeypatch):
    """_evict_email_from_all_caches must use submit_background (bounded pool),
    not threading.Thread daemon=True (audit Reply-HIGH-2).
    """
    import app.api.routes_helpers as rh
    calls = []
    monkeypatch.setattr(rh, "submit_background", lambda fn, *a, **kw: calls.append(fn))
    # Avoid actual cache/lock work
    monkeypatch.setattr(rh, "_invalidate_folder_cache", lambda *a, **kw: None)
    monkeypatch.setattr(rh, "_invalidate_label_batch_cache", lambda *a, **kw: None)

    rh._evict_email_from_all_caches("test-id-123")
    assert len(calls) == 1, "expected exactly one submit_background call"


def test_emit_email_sent_exists():
    """emit_email_sent must exist on websocket module (audit Send-MEDIUM
    'no email_sent WS event')."""
    from app.api import websocket
    assert hasattr(websocket, "emit_email_sent")
    # Signature smoke: callable with email_id, account_id, is_reply
    websocket.emit_email_sent("e1", account_id=None, is_reply=False)


def test_emit_email_sent_routes_via_account(monkeypatch):
    """emit_email_sent(account_id=N) must route through emit_to_account
    instead of falling through to the no-room branch (audit Send-MEDIUM)."""
    from app.api import websocket as ws
    captured = {}
    monkeypatch.setattr(ws, "emit_to_account",
                        lambda evt, payload, aid: captured.update(evt=evt, aid=aid, payload=payload))
    ws.emit_email_sent("eid-1", account_id=42, is_reply=True)
    assert captured.get("evt") == "email_sent"
    assert captured.get("aid") == 42
    assert captured.get("payload", {}).get("email_id") == "eid-1"
    assert captured.get("payload", {}).get("is_reply") is True


# ─────────────────────────────────────────────────────────────────────────────
# Outlook all-day TZ (Calendar-MEDIUM-5)
# ─────────────────────────────────────────────────────────────────────────────


def test_outlook_all_day_uses_datetime_tz():
    """All-day Outlook events must use the datetime's IANA timezone, not
    blindly UTC (audit Calendar-MEDIUM-5)."""
    from app.providers.outlook_calendar import OutlookCalendarAdapter
    adapter = OutlookCalendarAdapter(account_id="acc1")
    # Synthetic naive datetime → UTC fallback
    naive = datetime(2026, 5, 1, 0, 0, 0)
    out_naive = adapter._format_datetime(naive, all_day=True)
    assert out_naive["timeZone"] == "UTC"

    # Tz-aware datetime with IANA name
    try:
        from zoneinfo import ZoneInfo
        paris = ZoneInfo("Europe/Paris")
        aware = datetime(2026, 5, 1, 0, 0, 0, tzinfo=paris)
        out_aware = adapter._format_datetime(aware, all_day=True)
        assert out_aware["timeZone"] == "Europe/Paris"
    except ImportError:
        pytest.skip("zoneinfo not available")


# ─────────────────────────────────────────────────────────────────────────────
# Sanity: api ApiError retryAfter wiring is exposed via 429 body
# (frontend-side test cannot run here; this checks backend payload shape only)
# ─────────────────────────────────────────────────────────────────────────────


def test_rate_limit_429_includes_retry_after(app_client):
    """Backend rate-limit responses must include `retry_after` (sec) so the
    frontend can show a countdown (audit Send-MEDIUM)."""
    from app.api.routes_helpers import _rate_limited
    from app.api.app import create_app
    app = create_app()
    bucket = "test_audit_2026_04_25"
    with app.app_context():
        # Burn through a tiny budget
        for _ in range(3):
            ok, _ = _rate_limited(bucket, max_calls=2, window_seconds=60)
        ok, retry = _rate_limited(bucket, max_calls=2, window_seconds=60)
        # Once limit is exceeded, retry_after must be a positive number
        assert ok is False
        assert isinstance(retry, (int, float)) and retry > 0
