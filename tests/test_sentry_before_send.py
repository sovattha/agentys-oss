"""Tests for the Sentry `before_send` noise filter in app.api.app.

Note: `_sentry_before_send` short-circuits to `None` whenever pytest is detected,
so every test here must patch `_is_testing = False` and strip "pytest" from argv
to exercise the real filter logic.
"""

from __future__ import annotations

import pytest

from app.api import app as app_module


@pytest.fixture
def active_filter(monkeypatch):
    """Force the filter to behave as it would in production (non-test process)."""
    monkeypatch.setattr(app_module, "_is_testing", False)
    monkeypatch.setattr(app_module._sys, "argv", ["run_api.py"])
    return app_module._sentry_before_send


def _make_event(exc_type: str, exc_value: str) -> dict:
    return {
        "exception": {"values": [{"type": exc_type, "value": exc_value}]},
    }


def test_drops_session_is_disconnected_from_engineio(active_filter):
    """Stale socket.io session id should be filtered out — benign race on reconnect."""
    event = _make_event("KeyError", "'Session is disconnected'")
    assert active_filter(event, None) is None


def test_drops_write_before_start_response(active_filter):
    event = _make_event("AssertionError", "write() before start_response")
    assert active_filter(event, None) is None


def test_drops_windows_connection_aborted(active_filter):
    event = _make_event("ConnectionAbortedError", "WinError 10053")
    assert active_filter(event, None) is None


def test_drops_imap_auth_required(active_filter):
    event = _make_event("RuntimeError", "Authentification IMAP requise")
    assert active_filter(event, None) is None


def test_keeps_unrelated_errors(active_filter):
    """A real bug must NOT be filtered out."""
    event = _make_event("ValueError", "unexpected value in production code")
    assert active_filter(event, None) is event


def test_keeps_key_error_with_different_message(active_filter):
    """Other KeyErrors (real bugs) must pass through."""
    event = _make_event("KeyError", "'missing_config_key'")
    assert active_filter(event, None) is event


def test_redacts_structured_email_content_fields(active_filter):
    """Sentry extras/breadcrumbs can carry structured payloads outside logentry."""
    raw_body = "Bonjour Alice, le contrat secret ACME est prêt pour demain"
    event = {
        "extra": {
            "body_text": raw_body,
            "safe_counter": 3,
        },
        "breadcrumbs": {
            "values": [
                {"message": f"Persisted body_html='{raw_body}'"},
            ]
        },
    }

    filtered = active_filter(event, None)

    assert filtered is event
    assert raw_body not in str(filtered)
    assert "[EMAIL_CONTENT_REDACTED]" in str(filtered)
