"""Regression tests for the 2026-04-27 audit fix batch.

Covers:
- R-001 emit_draft_error accepts account_id and routes via emit_to_account
- R-002 emit_critique_* accept account_id; CritiqueRequest carries the field
- R-003 _refresh_tokens_server emits token_expired on any permanent OAuth failure
- R-010 _pending_events GC sweeps stale rooms
- FI-001 faq_agent_logs.account_id is Integer + FK + CASCADE
- FI-002 sync UNIQUE collision uses SAVEPOINT (per-row rollback)
- P-002 _get_pending_draft_email_ids caps fetch at 400 (not 2000)

Each test is meant to FAIL if the corresponding fix is reverted.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# R-001 / R-002 — WebSocket emit helpers accept account_id
# ---------------------------------------------------------------------------

def test_r001_emit_draft_error_routes_via_account_id():
    """emit_draft_error with account_id must call emit_to_account, not the
    legacy _resolve_ws_room fallback (which silently drops from BG threads)."""
    from app.api import websocket as ws

    with patch.object(ws, "emit_to_account", return_value=True) as m_eta, \
         patch.object(ws, "_resolve_ws_room", return_value=None) as m_legacy:
        ws.emit_draft_error(
            email_id="msg123",
            error="LLM timeout",
            retry_count=2,
            account_id=42,
        )
        m_eta.assert_called_once()
        args, _ = m_eta.call_args
        assert args[0] == "draft_error"
        assert args[1]["email_id"] == "msg123"
        assert args[1]["error"] == "LLM timeout"
        assert args[1]["retry_count"] == 2
        assert args[2] == 42
        # Legacy resolver MUST NOT be touched when account_id is provided.
        m_legacy.assert_not_called()


def test_r001_emit_draft_error_falls_back_without_account_id():
    """Without account_id, emit_draft_error keeps the legacy request-context
    behavior (so existing in-request callers don't regress)."""
    from app.api import websocket as ws

    with patch.object(ws, "emit_to_account") as m_eta, \
         patch.object(ws, "_resolve_ws_room", return_value=None) as m_legacy, \
         patch.object(ws, "get_socketio", return_value=MagicMock()):
        ws.emit_draft_error(email_id="msg1", error="oops")
        m_eta.assert_not_called()
        m_legacy.assert_called_once()


def test_r002_emit_critique_error_routes_via_account_id():
    from app.api import websocket as ws

    with patch.object(ws, "emit_to_account", return_value=True) as m_eta, \
         patch.object(ws, "_resolve_ws_room", return_value=None) as m_legacy:
        ws.emit_critique_error(
            email_id="msg9",
            error="critic timeout",
            account_id=7,
        )
        m_eta.assert_called_once()
        args, _ = m_eta.call_args
        assert args[0] == "critique_error"
        assert args[2] == 7
        m_legacy.assert_not_called()


def test_r002_emit_critique_complete_routes_via_account_id():
    from app.api import websocket as ws

    with patch.object(ws, "emit_to_account", return_value=True) as m_eta, \
         patch.object(ws, "_resolve_ws_room", return_value=None) as m_legacy:
        ws.emit_critique_complete(
            email_id="msg9",
            decision="VALID",
            overall_score=85,
            scores={"coherence": 90, "tone": 85, "completeness": 80, "errors": 90},
            suggestions=[],
            explanation="ok",
            evaluation_time_ms=100,
            tokens_used=200,
            account_id=11,
        )
        m_eta.assert_called_once()
        args, _ = m_eta.call_args
        assert args[0] == "critique_complete"
        assert args[2] == 11
        m_legacy.assert_not_called()


def test_r002_critique_request_has_account_id_field():
    """CritiqueRequest must carry account_id so the agent can forward it."""
    from app.domain.entities.critique import CritiqueRequest

    req = CritiqueRequest(
        draft_content="hello",
        original_email="hi",
        email_id="m1",
        account_id=99,
    )
    assert req.account_id == 99


# ---------------------------------------------------------------------------
# R-010 — WebSocket pending events GC
# ---------------------------------------------------------------------------

def test_r010_gc_drops_stale_rooms():
    """A room whose last event is older than 2× TTL is evicted by the GC."""
    from collections import deque

    from app.api import websocket as ws

    # Inject one fresh + one stale entry directly.
    now = time.time()
    stale_ts = now - (3 * ws._BUFFER_TTL_SECONDS)
    fresh_ts = now - 1

    ws._pending_events.clear()
    ws._pending_events["alice@example.com"] = deque(
        [(stale_ts, "draft_complete", {"email_id": "m1"})], maxlen=50
    )
    ws._pending_events["bob@example.com"] = deque(
        [(fresh_ts, "draft_complete", {"email_id": "m2"})], maxlen=50
    )

    evicted = ws._gc_pending_events_locked(now)
    assert evicted == 1
    assert "alice@example.com" not in ws._pending_events
    assert "bob@example.com" in ws._pending_events

    ws._pending_events.clear()


def test_r010_gc_runs_opportunistically_from_buffer_path():
    """Every _GC_INTERVAL seconds, the GC must fire from _buffer_event_if_needed."""
    from app.api import websocket as ws

    ws._pending_events.clear()
    # Seed a stale room.
    from collections import deque
    ws._pending_events["stale@example.com"] = deque(
        [(0.0, "draft_complete", {})], maxlen=50
    )
    # Reset the GC clock so the next call triggers the sweep.
    ws._last_gc_at = 0.0

    ws._buffer_event_if_needed("active@example.com", "draft_complete", {"email_id": "m1"})

    assert "stale@example.com" not in ws._pending_events
    assert "active@example.com" in ws._pending_events

    ws._pending_events.clear()


# ---------------------------------------------------------------------------
# FI-002 — sync UNIQUE collision uses SAVEPOINT
# ---------------------------------------------------------------------------

def test_fi002_unique_collision_does_not_lose_prior_inserts():
    """When the N-th email collides on UNIQUE, the N-1 earlier inserts must
    survive (savepoint rollback only). Before the fix, session.rollback()
    discarded the whole batch."""
    import inspect
    from app.services import sync_service

    src = inspect.getsource(sync_service.SyncService._store_emails)
    # Positive marker: the new SAVEPOINT pattern.
    assert "begin_nested()" in src, "FI-002 reverted: session.begin_nested() missing"
    # Negative marker: the old batch-killing call must be gone from the loop.
    # We can't easily isolate the loop body without tokenizing, but we can
    # at least assert that no `session.rollback()` is paired with the
    # UNIQUE-collision log line on the same except branch.
    assert "session.rollback()" not in src.split("UNIQUE collision", 1)[0].rsplit("except Exception", 1)[-1], \
        "FI-002 reverted: session.rollback() reappeared in UNIQUE-collision except branch"


# ---------------------------------------------------------------------------
# R-003 — OAuth refresh emits token_expired on permanent failures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status_code, error_code, should_emit",
    [
        # Permanent — must emit
        (400, "invalid_grant", True),
        (400, "invalid_client", True),
        (401, "unauthorized_client", True),
        (403, "access_denied", True),
        (400, "AADSTS50173", True),
        # Transient — must NOT emit (still retry)
        (502, "bad_gateway", False),
        (503, "service_unavailable", False),
        (500, "internal_error", False),
    ],
)
def test_r003_oauth_refresh_emits_on_permanent_failures(status_code, error_code, should_emit):
    """Any 4xx OR a known permanent code must emit token_expired."""
    from app.api import oauth as oauth_mod

    fake_response = MagicMock()
    fake_response.ok = False
    fake_response.status_code = status_code
    fake_response.json.return_value = {
        "error": error_code,
        "error_description": "test",
    }
    fake_response.text = "{}"

    with patch.object(oauth_mod, "get_tokens_server", return_value={
            "refresh_token": "rt",
            "email": "u@example.com",
            "provider": "gmail",
        }), \
        patch.object(oauth_mod.requests, "post", return_value=fake_response), \
        patch("app.api.websocket.emit_token_expired") as m_emit:
        result = oauth_mod._refresh_tokens_server(account_id="acct-1")
        assert result is None
        if should_emit:
            m_emit.assert_called_once()
            args, _ = m_emit.call_args
            assert args[0] == "acct-1"  # account_id
            assert args[2] == "gmail"   # provider
        else:
            m_emit.assert_not_called()


# ---------------------------------------------------------------------------
# FI-001 — faq_agent_logs.account_id is Integer + FK + CASCADE
# ---------------------------------------------------------------------------

def test_fi001_faq_log_account_id_is_integer_with_fk_cascade():
    """The model must declare account_id as Integer, with a FK to accounts.id
    and ondelete=CASCADE."""
    from sqlalchemy import Integer

    from app.db.models.faq_agent_log import FaqAgentLog

    col = FaqAgentLog.__table__.columns["account_id"]
    assert isinstance(col.type, Integer), \
        f"FI-001 reverted: account_id type is {col.type!r}, expected Integer"

    fks = list(col.foreign_keys)
    assert len(fks) == 1, "FI-001 reverted: missing FK on account_id"
    fk = fks[0]
    assert fk.column.table.name == "accounts"
    assert fk.column.name == "id"
    assert fk.ondelete == "CASCADE", \
        f"FI-001 reverted: ondelete is {fk.ondelete!r}, expected CASCADE"


def test_fi001_log_action_coerces_str_account_id_defensively():
    """Legacy callers pass account_id as str; _log_faq_action must coerce."""
    from app.db import database as db_mod
    from app import faq_agent

    captured_log = {}

    class _FakeSession:
        def add(self, obj):
            captured_log["account_id"] = obj.account_id
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    with patch.object(db_mod, "get_db_session", return_value=_FakeSession()):
        faq_agent._log_faq_action(
            account_id="42",  # str, like legacy callers
            email_id="m1",
            action="auto_sent",
            confidence=80.0,
            entry_id=None,
            entry_title=None,
        )
    assert captured_log == {"account_id": 42}


def test_fi001_log_action_skips_non_numeric_account_id():
    """Non-numeric account_id must be skipped (no exception, no insert)."""
    from app.db import database as db_mod
    from app import faq_agent

    inserted = []

    class _FakeSession:
        def add(self, obj):
            inserted.append(obj)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    with patch.object(db_mod, "get_db_session", return_value=_FakeSession()):
        faq_agent._log_faq_action(
            account_id="not-an-int",
            email_id="m1",
            action="skipped",
            confidence=0.0,
            entry_id=None,
            entry_title=None,
        )
    assert inserted == []


# ---------------------------------------------------------------------------
# P-002 — draft fetch cap
# ---------------------------------------------------------------------------

def test_p002_get_pending_draft_email_ids_caps_at_400():
    """The hot-path fetch must request at most 400 drafts (not 2000)."""
    import inspect
    from app.api import routes_emails

    src = inspect.getsource(routes_emails._get_pending_draft_email_ids)
    # Positive: 400 cap is present.
    assert "_FETCH_CAP = 400" in src or "limit=400" in src, \
        "P-002 reverted: 400 cap missing from _get_pending_draft_email_ids"
    # Negative: legacy 2000 hardcode is gone.
    assert "limit=2000" not in src, \
        "P-002 reverted: limit=2000 reappeared in _get_pending_draft_email_ids"
