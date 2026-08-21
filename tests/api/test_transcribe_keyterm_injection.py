# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests vérifiant que ``_call_deepgram`` injecte bien le param ``keyterm``."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.api import routes_misc
from app.api.routes_misc import _call_deepgram


def _mk_response(transcript: str = "ok"):
    """Forge une réponse Deepgram minimale."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "results": {
            "channels": [{"alternatives": [{"transcript": transcript}]}]
        }
    }
    return resp


def _install_session_mock(monkeypatch_target):
    """Replace the cached Deepgram session with a MagicMock and return it.

    Production code calls ``_dg_session.post(...)`` (cached session, intro'd
    in commit a3c0e067). Patching ``requests.post`` no longer intercepts —
    we have to swap the cached session itself.
    """
    session = MagicMock()
    session.post.return_value = _mk_response("hi")
    monkeypatch_target.setattr(routes_misc, "_dg_session", session)
    return session


class TestKeytermInjection:
    def test_keyterm_param_present_when_provided(self, monkeypatch):
        session = _install_session_mock(monkeypatch)
        _call_deepgram(
            "fake-key", b"audio", "audio/webm",
            language="fr",
            keyterms=["Agentys", "Nat"],
        )
        assert session.post.called
        params = session.post.call_args.kwargs["params"]
        assert params["keyterm"] == ["Agentys", "Nat"]

    def test_keyterm_param_absent_when_empty(self, monkeypatch):
        session = _install_session_mock(monkeypatch)
        _call_deepgram("fake-key", b"audio", "audio/webm", language="fr", keyterms=[])
        params = session.post.call_args.kwargs["params"]
        assert "keyterm" not in params

    def test_keyterm_param_absent_when_none(self, monkeypatch):
        session = _install_session_mock(monkeypatch)
        _call_deepgram("fake-key", b"audio", "audio/webm", language="fr")
        params = session.post.call_args.kwargs["params"]
        assert "keyterm" not in params

    def test_other_params_untouched(self, monkeypatch):
        """Sanity — keyterm injection doesn't break the existing params shape."""
        session = _install_session_mock(monkeypatch)
        _call_deepgram(
            "fake-key", b"audio", "audio/webm",
            language="fr",
            keyterms=["Atlas"],
        )
        params = session.post.call_args.kwargs["params"]
        assert params["model"]
        assert params["smart_format"] == "true"
        assert params["punctuate"] == "true"
        assert params["language"] == "fr"
