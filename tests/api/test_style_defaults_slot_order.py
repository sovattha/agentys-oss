# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression (audit 2026-06-02): editing the FORMAL default greeting/closing
must NOT corrupt the CASUAL slot.

`PATCH /writing-style/defaults` stores greetings/closings POSITIONALLY:
slot [0] = formal, slot [1] = casual (the convention every consumer assumes —
see smart_routing._compute_greeting_hint). The formal handler used to do
`insert(0, value)` (MRU prepend), which shifted the previous formal value down
into slot [1], overwriting the user's real casual greeting/closing and pushing
it to slot [2] where no consumer reads it. The fix makes the formal handler a
positional set of slot [0].
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask


@pytest.fixture
def client():
    from app.api.routes_helpers import api_bp

    app = Flask(__name__)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.config["TESTING"] = True
    return app.test_client()


def _wire(monkeypatch, profile):
    from app.api import routes_learning as rl

    monkeypatch.setattr(rl._rh, "_resolve_account_id_cached", lambda: 42)
    store = MagicMock()
    store.load.return_value = profile
    container = MagicMock()
    container.get_writing_style_store.return_value = store
    monkeypatch.setattr(rl._rh, "_get_container", lambda: container)
    return store


def _profile(greetings, closings):
    from app.domain.entities.writing_style import WritingStyleProfile

    p = WritingStyleProfile.create_empty(42)
    p.preferred_greetings = list(greetings)
    p.preferred_closings = list(closings)
    return p


def test_editing_formal_greeting_keeps_casual_slot(client, monkeypatch):
    p = _profile(
        ["Bonjour Madame {last_name},", "Salut {first_name},"],
        ["Cordialement,", "A+,"],
    )
    store = _wire(monkeypatch, p)

    resp = client.patch(
        "/api/writing-style/defaults",
        json={"preferred_greeting": "Bonjour {first_name},"},
    )

    assert resp.status_code == 200
    g = resp.get_json()["defaults"]["preferred_greetings"]
    assert g[0] == "Bonjour {first_name},"   # formal slot updated
    assert g[1] == "Salut {first_name},"     # casual slot MUST be untouched (the bug)
    store.save.assert_called()


def test_editing_formal_closing_keeps_casual_slot(client, monkeypatch):
    p = _profile(["Bonjour,", "Salut,"], ["Cordialement,", "A+,"])
    _wire(monkeypatch, p)

    resp = client.patch(
        "/api/writing-style/defaults",
        json={"preferred_closing": "Bien à vous,"},
    )

    assert resp.status_code == 200
    c = resp.get_json()["defaults"]["preferred_closings"]
    assert c[0] == "Bien à vous,"   # formal slot updated
    assert c[1] == "A+,"            # casual slot untouched


def test_casual_edit_only_touches_slot_one(client, monkeypatch):
    p = _profile(["Bonjour,", "Salut,"], ["Cordialement,", "A+,"])
    _wire(monkeypatch, p)

    resp = client.patch(
        "/api/writing-style/defaults",
        json={"preferred_greeting_casual": "Coucou,"},
    )

    assert resp.status_code == 200
    g = resp.get_json()["defaults"]["preferred_greetings"]
    assert g[0] == "Bonjour,"   # formal untouched
    assert g[1] == "Coucou,"


def test_formal_edit_into_empty_profile_creates_slot_zero(client, monkeypatch):
    p = _profile([], [])
    _wire(monkeypatch, p)

    resp = client.patch(
        "/api/writing-style/defaults",
        json={"preferred_greeting": "Bonjour,"},
    )

    assert resp.status_code == 200
    assert resp.get_json()["defaults"]["preferred_greetings"] == ["Bonjour,"]
