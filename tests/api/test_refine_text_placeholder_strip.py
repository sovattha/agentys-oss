# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""/api/refine-text anti-templating (audit fix 2026-06-02).

Previously only the SURGICAL path rejected leaked template placeholders
({name}, [Name], ${var}). The normal Ctrl+G / expand-notes path had no
protection, so a draft could ship "Bonjour {prénom}," verbatim. The fix:
 - surgical  -> hard 422 reject (precise-edit contract, unchanged);
 - non-surgical -> STRIP only the NEW tokens (diffed vs input so user-authored
   brackets survive), keeping a usable draft.
"""
import os
import time
from unittest.mock import MagicMock, patch

import jwt as _pyjwt
import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

from app.api.auth import JWT_ALGORITHM, JWT_SECRET


@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _auth_headers() -> dict:
    token = _pyjwt.encode(
        {"sub": "12345", "email": "test@agentys.app",
         "iat": int(time.time()), "exp": int(time.time()) + 3600},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _mock_container(refined_text: str) -> MagicMock:
    r = MagicMock()
    r.content = refined_text
    c = MagicMock()
    c.llm_drafting.complete.return_value = r
    c.llm_drafting_smart.complete.return_value = r
    c.get_writing_style_profile.return_value = None
    return c


def _post(client, body: dict):
    with patch("app.api.routes_helpers._get_container", return_value=_post.container), \
         patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42):
        return client.post("/api/refine-text", json=body, headers=_auth_headers())


class TestNonSurgicalStrip:
    def test_strips_leaked_greeting_placeholder(self, client):
        _post.container = _mock_container(
            "Bonjour {prénom},\n\nJe confirme ma présence demain.\n\nCordialement,"
        )
        resp = _post(client, {"text": "confirme demain", "instruction": "Rédige"})
        assert resp.status_code == 200
        refined = resp.get_json()["refined_text"]
        assert "{prénom}" not in refined
        # bare-token removal artefact "Bonjour ," is tidied to "Bonjour,"
        assert "Bonjour ," not in refined

    def test_strips_multiple_placeholder_kinds(self, client):
        _post.container = _mock_container(
            "Hi [Name],\n\nYour code is ${code} and %ref%.\n\nBest,"
        )
        resp = _post(client, {"text": "send code", "instruction": "Rewrite"})
        assert resp.status_code == 200
        refined = resp.get_json()["refined_text"]
        assert "[Name]" not in refined
        assert "${code}" not in refined
        assert "%ref%" not in refined

    def test_preserves_user_authored_brackets(self, client):
        # [ProjectX] is present in the INPUT, so it is not a NEW placeholder and
        # must survive (no false-positive strip of legitimate user content).
        _post.container = _mock_container(
            "Bonjour,\n\nPoint sur [ProjectX] demain.\n\nCordialement,"
        )
        resp = _post(client, {
            "text": "point sur [ProjectX] demain",
            "instruction": "Corrige les fautes",
        })
        assert resp.status_code == 200
        refined = resp.get_json()["refined_text"]
        assert "[ProjectX]" in refined


class TestSurgicalStillRejects:
    def test_surgical_rejects_leaked_placeholder(self, client):
        _post.container = _mock_container("Bonjour {first_name}, à 21h.")
        resp = _post(client, {
            "text": "Bonjour Alexandre, à 20h.",
            "instruction": "remplace 20h par 21h",
            "surgical": True,
        })
        assert resp.status_code == 422
        assert resp.get_json().get("code") == "surgical_template_leak"
