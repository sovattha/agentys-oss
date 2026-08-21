# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for the 2026-06-02 Outlook custom-domain (M365) fixes.

Covers the fixes derived from the custom-domain readiness audit:

  #4  signature sync no-op       — OutlookAdapter must be built via account_id
  #5  freebusy 20-cap chunking   — weak adapter must chunk getSchedule + keep status
  #6  MailboxSettings.Read scope — present in backend + frontend scope sets
  #7  teamsForBusiness + retry   — provider requested, retried without it on 400
  #9  classification-header backfill — Outlook gains fetch_classification_headers_batch
  #12 allowlist tid verification — id_token signature verified when allowlist active

All Graph calls are mocked — no real credentials or network required.
"""
from __future__ import annotations

import types
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


class _FakeResp:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._data = data if data is not None else {}
        self.text = text

    def json(self):
        return self._data


# ---------------------------------------------------------------------------
# #4 — signature sync no-op fix (construct via account_id, not access_token)
# ---------------------------------------------------------------------------

def test_signature_fix_account_id_path_constructs(monkeypatch):
    """The OAuth callback must build OutlookAdapter(account_id=...).

    The pre-fix call ``OutlookAdapter(access_token=..., refresh_token=...)`` passed
    kwargs the constructor does not accept (swallowed by **kwargs); with no AZURE_*
    env (the normal web deployment) it raised ValueError -> the signature import was
    a silent no-op. Document both: the old shape raises, the fixed shape does not.
    """
    from app.providers.outlook_adapter import OutlookAdapter

    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.delenv("MICROSOFT_CLIENT_ID", raising=False)

    # Old (broken) shape: tokens ignored, no account_id, no AZURE env -> raises.
    with pytest.raises(ValueError):
        OutlookAdapter(access_token="tok", refresh_token="ref")

    # Fixed shape: account_id path skips Azure-AD validation, ready to load
    # server-stored tokens.
    adapter = OutlookAdapter(account_id="abc123")
    assert adapter.account_id == "abc123"
    assert adapter.client_secret is None or isinstance(adapter.client_secret, str)


def test_oauth_callback_uses_account_id_for_signature():
    """Guard the actual call site so a revert to the broken kwargs is caught."""
    src = (REPO_ROOT / "app" / "api" / "oauth.py").read_text(encoding="utf-8")
    assert "outlook_provider = OutlookAdapter(account_id=account_id)" in src
    assert "OutlookAdapter(\n                    access_token=" not in src


# ---------------------------------------------------------------------------
# #5 — weak adapter getSchedule must chunk to 20 and preserve status
# ---------------------------------------------------------------------------

def test_weak_freebusy_chunks_over_20(monkeypatch):
    import app.providers.outlook_calendar_adapter as mod

    adapter = mod.OutlookCalendarAdapter(account_id="x")
    adapter._authenticated = True
    monkeypatch.setattr(adapter, "_get_access_token", lambda: "tok")

    posted: list[list[str]] = []

    def fake_get(url, headers=None, timeout=None, **kw):
        return _FakeResp(data={"mail": "me@corp.com"})

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        scheds = json["schedules"]
        posted.append(scheds)
        return _FakeResp(data={"value": [
            {
                "scheduleId": s,
                "scheduleItems": [{
                    "status": "busy",
                    "start": {"dateTime": "2026-06-02T10:00:00"},
                    "end": {"dateTime": "2026-06-02T11:00:00"},
                }],
            }
            for s in scheds
        ]})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod.requests, "post", fake_post)

    attendees = [f"a{i}@corp.com" for i in range(25)]
    result = adapter.get_freebusy(attendees, datetime(2026, 6, 2, 9), datetime(2026, 6, 2, 18))

    # 25 attendees + 1 self = 26 schedules -> 2 chunks (20 + 6), none over the cap.
    assert len(posted) == 2
    assert all(len(chunk) <= 20 for chunk in posted)
    # All 26 calendars merged across chunks (the pre-fix single call silently
    # truncated to an empty/partial response -> "everyone is free").
    assert len(result["calendars"]) == 26
    # Outlook showAs status is preserved for the scheduling grid.
    assert result["calendars"]["me@corp.com"][0]["status"] == "busy"


# ---------------------------------------------------------------------------
# #6 — MailboxSettings.Read scope present (backend + frontend)
# ---------------------------------------------------------------------------

def test_mailboxsettings_scope_in_backend_user_scopes():
    from app.providers.outlook_adapter import OutlookAdapter
    assert "https://graph.microsoft.com/MailboxSettings.Read" in OutlookAdapter.USER_SCOPES


def test_mailboxsettings_scope_in_refresh_and_frontend():
    oauth_src = (REPO_ROOT / "app" / "api" / "oauth.py").read_text(encoding="utf-8")
    # backend refresh re-requests the full scope set
    assert oauth_src.count("https://graph.microsoft.com/MailboxSettings.Read") >= 1
    ts_src = (REPO_ROOT / "agentys-app" / "src" / "services" / "oauth.ts").read_text(encoding="utf-8")
    assert "https://graph.microsoft.com/MailboxSettings.Read" in ts_src


# ---------------------------------------------------------------------------
# #7 — teamsForBusiness requested, retried WITHOUT provider on HTTP 400
# ---------------------------------------------------------------------------

def _make_conf_event():
    return types.SimpleNamespace(
        title="Sync call",
        start_time=datetime(2026, 6, 2, 10, 0, 0),
        end_time=datetime(2026, 6, 2, 10, 30, 0),
        conference=True,
    )


def test_teams_for_business_requested_and_succeeds(monkeypatch):
    import app.providers.outlook_calendar as mod

    adapter = mod.OutlookCalendarAdapter(account_id="x")
    monkeypatch.setattr(adapter, "_ensure_authenticated", lambda: None)
    monkeypatch.setattr(adapter, "_get_headers", lambda: {})

    bodies: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        bodies.append(json)
        return _FakeResp(data={"id": "evt1", "onlineMeeting": {"joinUrl": "https://teams.example/x"}})

    monkeypatch.setattr(mod.requests, "post", fake_post)

    result = adapter.create_event(_make_conf_event())
    assert result["event_id"] == "evt1"
    assert result["meet_link"] == "https://teams.example/x"
    # Work/school accounts: one POST, teamsForBusiness requested explicitly.
    assert len(bodies) == 1
    assert bodies[0].get("onlineMeetingProvider") == "teamsForBusiness"


def test_teams_for_business_retries_without_provider_on_400(monkeypatch):
    import app.providers.outlook_calendar as mod

    adapter = mod.OutlookCalendarAdapter(account_id="x")
    monkeypatch.setattr(adapter, "_ensure_authenticated", lambda: None)
    monkeypatch.setattr(adapter, "_get_headers", lambda: {})

    bodies: list[dict] = []
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        bodies.append(dict(json))
        calls["n"] += 1
        if calls["n"] == 1:
            # Personal Microsoft accounts reject teamsForBusiness with 400.
            return _FakeResp(status_code=400, text="invalid onlineMeetingProvider")
        return _FakeResp(data={"id": "evt2", "onlineMeeting": {"joinUrl": "https://teams.example/y"}})

    monkeypatch.setattr(mod.requests, "post", fake_post)

    result = adapter.create_event(_make_conf_event())
    assert result is not None and result["event_id"] == "evt2"
    assert len(bodies) == 2
    assert bodies[0].get("onlineMeetingProvider") == "teamsForBusiness"
    # Retry drops the provider so the create still succeeds.
    assert "onlineMeetingProvider" not in bodies[1]


# ---------------------------------------------------------------------------
# #9 — Outlook fetch_classification_headers_batch
# ---------------------------------------------------------------------------

def test_outlook_fetch_classification_headers_batch(monkeypatch):
    import app.providers.outlook_adapter as mod

    adapter = mod.OutlookAdapter(account_id="x")
    adapter.user_id = "me@corp.com"
    adapter._access_token = "tok"
    monkeypatch.setattr(adapter, "_ensure_authenticated", lambda: None)

    def fake_graph_request(method, url, headers=None, timeout=None, **kw):
        if "id1" in url:
            return _FakeResp(data={"internetMessageHeaders": [
                {"name": "List-Unsubscribe", "value": "<mailto:x@y>"},
                {"name": "Precedence", "value": "bulk"},
                {"name": "Subject", "value": "ignored — not a classification header"},
            ]})
        # id2 has no relevant headers
        return _FakeResp(data={"internetMessageHeaders": [
            {"name": "X-Random", "value": "nope"},
        ]})

    monkeypatch.setattr(mod, "_graph_request_with_retry", fake_graph_request)

    out = adapter.fetch_classification_headers_batch(["id1", "id2"])
    assert out == {"id1": {"list-unsubscribe": "<mailto:x@y>", "precedence": "bulk"}}
    # The labels.py backfill checks for this method via hasattr -> must exist now.
    assert hasattr(adapter, "fetch_classification_headers_batch")


def test_outlook_classification_headers_match_gmail_set():
    """Header set must stay in sync with the Gmail adapter's backfill set."""
    from app.providers.outlook_adapter import OutlookAdapter
    from app.providers.gmail_adapter import GmailAdapter
    assert set(OutlookAdapter._CLASSIFICATION_HEADER_NAMES_FOR_BACKFILL) == set(
        GmailAdapter._CLASSIFICATION_HEADER_NAMES_FOR_BACKFILL
    )


# ---------------------------------------------------------------------------
# #12 — tenant allowlist gates on a SIGNATURE-VERIFIED tid
# ---------------------------------------------------------------------------

def test_allowlist_empty_skips_signature_verification(monkeypatch):
    import app.api.oauth as oauth

    monkeypatch.setattr(oauth, "_MICROSOFT_TENANT_ALLOWLIST", frozenset())
    monkeypatch.setattr(oauth, "_decode_id_token_claims",
                        lambda _t: {"tid": "T1", "oid": "o1", "email": "a@corp.com"})

    def _boom(_t):
        raise AssertionError("verification must NOT run when allowlist is empty")
    monkeypatch.setattr(oauth, "_verify_microsoft_id_token", _boom)

    ok, reason = oauth._validate_outlook_identity(
        {"id_token": "header.body.sig"}, {"mail": "a@corp.com", "id": "u1"}
    )
    assert ok is True


def test_allowlist_active_accepts_verified_tid(monkeypatch):
    import app.api.oauth as oauth

    monkeypatch.setattr(oauth, "_MICROSOFT_TENANT_ALLOWLIST", frozenset({"T1"}))
    monkeypatch.setattr(oauth, "_decode_id_token_claims",
                        lambda _t: {"tid": "spoofed", "oid": "o1", "email": "a@corp.com"})
    # Verified token carries the real (allowlisted) tid.
    monkeypatch.setattr(oauth, "_verify_microsoft_id_token", lambda _t: {"tid": "T1"})

    ok, reason = oauth._validate_outlook_identity(
        {"id_token": "header.body.sig"}, {"mail": "a@corp.com", "id": "u1"}
    )
    assert ok is True


def test_allowlist_active_rejects_unverifiable_token(monkeypatch):
    import app.api.oauth as oauth

    monkeypatch.setattr(oauth, "_MICROSOFT_TENANT_ALLOWLIST", frozenset({"T1"}))
    monkeypatch.setattr(oauth, "_decode_id_token_claims",
                        lambda _t: {"tid": "T1", "oid": "o1"})

    def _bad_sig(_t):
        raise ValueError("signature mismatch")
    monkeypatch.setattr(oauth, "_verify_microsoft_id_token", _bad_sig)

    ok, reason = oauth._validate_outlook_identity(
        {"id_token": "header.body.sig"}, {"mail": "a@corp.com", "id": "u1"}
    )
    assert ok is False
    assert "signature" in reason.lower()


def test_allowlist_active_rejects_verified_tid_outside_allowlist(monkeypatch):
    import app.api.oauth as oauth

    monkeypatch.setattr(oauth, "_MICROSOFT_TENANT_ALLOWLIST", frozenset({"T1"}))
    monkeypatch.setattr(oauth, "_decode_id_token_claims",
                        lambda _t: {"tid": "T2", "oid": "o1"})
    monkeypatch.setattr(oauth, "_verify_microsoft_id_token", lambda _t: {"tid": "T2"})

    ok, reason = oauth._validate_outlook_identity(
        {"id_token": "header.body.sig"}, {"mail": "a@corp.com", "id": "u1"}
    )
    assert ok is False
    assert "non autorisé" in reason.lower()
