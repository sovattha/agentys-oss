# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression test for the final blank-line collapse pass in /api/refine-text.

Audit 2026-05-19 round-2 (R1 + R2): the post-LLM pipeline runs several
``_strip_*`` / ``_enforce_*`` passes in sequence. Each one removes or
inserts lines without normalizing the surrounding blank-line density.
Without a final collapse, the response carries ``\\n\\n\\n\\n\\n`` (4–5
consecutive newlines) between greeting/body/closing, and the ProseMirror
editor renders these as visible empty paragraphs the user must delete
before sending.

Fix added a single line at the end of the route:

    refined = re.sub(r"\\n{3,}", "\\n\\n", refined).strip()
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


class TestFinalBlankLineCollapse:
    def test_collapses_quadruple_newlines_to_double(self, client):
        """LLM returns a body with 4-newline gaps (caused by signature
        post-strip leaving blank lines). The final collapse must reduce
        them to single \\n\\n paragraph breaks."""
        c = _mock_container(
            "Bonjour Alexandre,\n\n\n\n"
            "Je confirme ma disponibilité demain à 14h.\n\n\n\n"
            "Cordialement,"
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42):
            resp = client.post(
                "/api/refine-text",
                json={"text": "dispo demain 14h", "instruction": "Rédige"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        refined = resp.get_json()["refined_text"]
        # No run of 3+ newlines should survive.
        assert "\n\n\n" not in refined, (
            f"Expected blank-line collapse, found triple+ newlines in: {refined!r}"
        )

    def test_collapses_quintuple_newlines_too(self, client):
        """The R1 + R2 prod responses had \\n\\n\\n\\n\\n (5 newlines).
        Verify the collapse catches that extreme case as well."""
        c = _mock_container(
            "Bonjour Alexandre,\n\n\n\n\n"
            "Je confirme ma disponibilité demain à 14h.\n\n\n\n\n"
            "Cordialement,"
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42):
            resp = client.post(
                "/api/refine-text",
                json={"text": "dispo demain 14h", "instruction": "Rédige"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        refined = resp.get_json()["refined_text"]
        assert "\n\n\n" not in refined
        # The paragraph break between greeting and body is exactly \n\n.
        assert "Bonjour Alexandre,\n\nJe confirme" in refined

    def test_preserves_intentional_paragraph_breaks(self, client):
        """A well-formed body with 2-newline paragraph breaks must come back
        unchanged — the collapse should be idempotent, not destructive."""
        c = _mock_container(
            "Bonjour,\n\n"
            "Premier paragraphe.\n\n"
            "Deuxième paragraphe.\n\n"
            "Cordialement,"
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42):
            resp = client.post(
                "/api/refine-text",
                json={"text": "deux idées", "instruction": "Rédige"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        refined = resp.get_json()["refined_text"]
        assert refined.count("\n\n") >= 3  # three paragraph breaks survive
        assert "Premier paragraphe.\n\nDeuxième paragraphe." in refined
