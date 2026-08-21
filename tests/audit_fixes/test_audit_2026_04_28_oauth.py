"""P1-009 — _refresh_tokens_server treats 408/425/429 as transient.

Regression: a single 429 from Google/Microsoft used to emit token_expired and
force the user to re-auth. After the fix, transient 4xx must not emit and
must keep the refresh_token intact.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _fake_token_data():
    return {
        "provider": "gmail",
        "refresh_token": "rt-abc",
        "email": "user@example.com",
    }


def _make_response(status: int, body: dict | None = None, headers: dict | None = None):
    r = MagicMock()
    r.ok = 200 <= status < 300
    r.status_code = status
    r.json.return_value = body or {"error": "rate_limited", "error_description": "slow down"}
    r.text = "irrelevant"
    r.headers = headers or {}
    return r


@pytest.mark.parametrize("status", [408, 425, 429])
def test_p1009_transient_4xx_does_not_emit_token_expired(status):
    from app.api import oauth

    resp = _make_response(status, headers={"Retry-After": "30"})
    with patch.object(oauth, "get_tokens_server", return_value=_fake_token_data()), \
         patch.object(oauth, "requests") as m_req, \
         patch("app.api.websocket.emit_token_expired") as m_emit:
        m_req.post.return_value = resp
        result = oauth._refresh_tokens_server("acc-1")
        assert result is None
        m_emit.assert_not_called()


def test_p1009_invalid_grant_400_still_emits_token_expired():
    """Positive control: real permanent failure must still emit the signal."""
    from app.api import oauth

    resp = _make_response(400, body={"error": "invalid_grant", "error_description": "expired"})
    with patch.object(oauth, "get_tokens_server", return_value=_fake_token_data()), \
         patch.object(oauth, "requests") as m_req, \
         patch("app.api.websocket.emit_token_expired") as m_emit:
        m_req.post.return_value = resp
        result = oauth._refresh_tokens_server("acc-1")
        assert result is None
        m_emit.assert_called_once()


def test_p1009_429_with_invalid_grant_body_still_emits():
    """Body-level permanent code overrides transient HTTP status."""
    from app.api import oauth

    resp = _make_response(429, body={"error": "invalid_grant", "error_description": "x"})
    with patch.object(oauth, "get_tokens_server", return_value=_fake_token_data()), \
         patch.object(oauth, "requests") as m_req, \
         patch("app.api.websocket.emit_token_expired") as m_emit:
        m_req.post.return_value = resp
        result = oauth._refresh_tokens_server("acc-1")
        assert result is None
        m_emit.assert_called_once()
