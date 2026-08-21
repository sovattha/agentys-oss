# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression test for per-PERSON contact overrides on the LIVE generation path.

The "write from my notes" Generate flow hits ``POST /api/refine-text`` (not
``/api/emails/compose``). refine-text held a THIRD copy of the per-contact
override extraction that (a) looked the recipient up by EXACT email — so an
override stored on a contact's work address never reached a draft to their
gmail — and (b) built the opening with inline logic that produced the
double-comma "Bonjour, Nat," for a bare "Bonjour," greeting.

This drives the route with a profile where the override lives only on the
work work address and the gmail address is empty, and asserts the prompt
sent to the drafter carries the clean shared opening "Bonjour Nat,".
"""

import os
import time
from unittest.mock import MagicMock, patch

import jwt as _pyjwt
import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

from app.api.auth import JWT_ALGORITHM, JWT_SECRET

_WORK = "nathan.roy@corp.example"
_GMAIL = "nathanroy@gmail.com"


@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _auth_headers(email: str = "test@agentys.app", sub: str = "12345") -> dict:
    token = _pyjwt.encode(
        {"sub": sub, "email": email, "iat": int(time.time()), "exp": int(time.time()) + 3600},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _flatten_complete_call(args, kwargs) -> str:
    """Flatten a captured llm.complete(system=[...], user=...) call to text."""
    parts = []
    sys = kwargs.get("system") if kwargs else None
    if isinstance(sys, list):
        parts += [getattr(s, "text", str(s)) for s in sys]
    elif sys is not None:
        parts.append(str(sys))
    u = kwargs.get("user") if kwargs else None
    if u:
        parts.append(str(u))
    parts += [str(a) for a in (args or [])]
    return "\n".join(parts)


class TestRefineTextPerContactSiblingOverride:
    def _container(self):
        captured = []

        def complete(*args, **kwargs):
            captured.append((args, kwargs))
            return MagicMock(content="Bonjour Nat,\n\nUn petit mot.\n\nA+")

        c = MagicMock()
        c.llm_drafting.complete.side_effect = complete
        c.llm_drafting_smart.complete.side_effect = complete
        profile = MagicMock()
        profile.typical_signature = "Alexandre Simon"
        profile.preferred_closings = []
        profile.contact_profiles = {
            _WORK: {
                "email": _WORK, "nickname": "Nat",
                "preferred_greeting": "Bonjour,", "preferred_closing": "A+",
                "formality_override": "casual",
            },
            _GMAIL: {
                "email": _GMAIL, "nickname": None, "preferred_greeting": None,
                "preferred_closing": None, "formality_override": None,
            },
        }
        c.get_writing_style_profile.return_value = profile
        return c, captured

    def test_gmail_recipient_inherits_work_opening_in_prompt(self, client):
        c, captured = self._container()
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user",
                   return_value=13):
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "demande-lui quand il est dispo pour une rencontre",
                    "instruction": "Rédige un email complet",
                    "to": _GMAIL,
                },
                headers=_auth_headers(),
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert captured, "the drafter LLM was never called"
        prompts = "\n".join(_flatten_complete_call(a, k) for a, k in captured)
        # The work sibling's nickname (Nat) + bare "Bonjour," greeting must
        # resolve to the clean shared opening — not the recipient's bare first
        # name, and not the old inline double-comma form.
        assert "Bonjour Nat," in prompts
        assert "Bonjour, Nat," not in prompts
        assert "Bonjour Nathan," not in prompts
