# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression test for the typical_signature account-fallback in /api/refine-text.

Audit 2026-05-19, T31.1 finding: the LLM occasionally violates the "NO
SIGNATURE BLOCK" rule (routes_drafts.py:1496) and appends the user's name
after the closing line — "Alexandre Simon," in T31.1. The post-LLM
defense `_strip_trailing_signature(body, typical_signature)` was supposed
to remove it but its token-matching branch is gated behind a populated
`typical_signature` field. For users without a writing-style profile (new
accounts, profile-load exceptions silently swallowed at the try/except),
`typical_signature` was `None` and the leaked name passed through —
visible as a doublon next to the signature widget below.

Fix: when the profile lacks `typical_signature`, hydrate it from the
account's `signature_text` (or `display_name` as a last resort) so the
stripper always has tokens to match.
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


def _auth_headers(email: str = "test@agentys.app", sub: str = "12345") -> dict:
    token = _pyjwt.encode(
        {"sub": sub, "email": email, "iat": int(time.time()), "exp": int(time.time()) + 3600},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


# The exact T31.1 LLM output: French body ending with a leaked name line.
# The stripper should remove the trailing name when typical_signature is
# hydrated from the account, leaving only "Cordialement," as the closing.
LLM_BODY_WITH_NAME_LEAK = (
    "Bonjour Alexandre,\n\n"
    "Je confirme que je suis disponible demain à 14h pour l'appel Q4. "
    "Je prépare les slides en ce moment.\n\n"
    "Cordialement,\n\n"
    "Alexandre Simon,"
)


def _mock_container_returning(body: str) -> MagicMock:
    r = MagicMock()
    r.content = body
    c = MagicMock()
    c.llm_drafting.complete.return_value = r
    c.llm_drafting_smart.complete.return_value = r
    # Profile has NO typical_signature — this is the regression condition.
    profile = MagicMock()
    profile.typical_signature = None
    profile.contact_profiles = {}
    c.get_writing_style_profile.return_value = profile
    return c


class TestSignatureAccountFallback:
    def test_account_signature_text_strips_leaked_name(self, client):
        """When typical_signature is None but the account has a signature_text
        containing the user's name, the leaked trailing name line is stripped."""
        c = _mock_container_returning(LLM_BODY_WITH_NAME_LEAK)
        fake_account = MagicMock()
        fake_account.signature_text = "Alexandre Simon\nCo-fondateur d'Agentys"
        fake_account.display_name = "Alexandre Simon"
        repo_instance = MagicMock()
        repo_instance.get.return_value = fake_account

        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
             patch("app.db.repositories.account_repository.AccountRepository",
                   return_value=repo_instance), \
             patch("app.db.database.get_db_session") as mock_sess:
            mock_sess.return_value.__enter__.return_value = MagicMock()
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "rdv demain 14h Q4",
                    "instruction": "Rédige un email complet",
                },
                headers=_auth_headers(),
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        refined = resp.get_json()["refined_text"]
        # The trailing "Alexandre Simon," must be gone.
        assert not refined.rstrip().endswith("Alexandre Simon,"), (
            f"Expected name leak to be stripped, got body ending: {refined[-200:]!r}"
        )
        # The body should still end at the closing word.
        assert "Cordialement," in refined
        # The actual hydrate call was made.
        repo_instance.get.assert_called_once_with(42)

    def test_falls_back_to_display_name_when_signature_text_empty(self, client):
        c = _mock_container_returning(LLM_BODY_WITH_NAME_LEAK)
        fake_account = MagicMock()
        fake_account.signature_text = None
        fake_account.display_name = "Alexandre Simon"
        repo_instance = MagicMock()
        repo_instance.get.return_value = fake_account

        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
             patch("app.db.repositories.account_repository.AccountRepository",
                   return_value=repo_instance), \
             patch("app.db.database.get_db_session") as mock_sess:
            mock_sess.return_value.__enter__.return_value = MagicMock()
            resp = client.post(
                "/api/refine-text",
                json={"text": "rdv demain 14h", "instruction": "Rédige un email"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        refined = resp.get_json()["refined_text"]
        assert not refined.rstrip().endswith("Alexandre Simon,")
        repo_instance.get.assert_called_once_with(42)

    def test_no_fallback_when_profile_already_has_typical_signature(self, client):
        """If the writing-style profile already supplies typical_signature, we
        must NOT make a second DB round-trip — the fallback only runs when the
        profile's field is empty."""
        c = MagicMock()
        c.llm_drafting.complete.return_value = MagicMock(content="ok")
        c.llm_drafting_smart.complete.return_value = MagicMock(content="ok")
        profile = MagicMock()
        profile.typical_signature = "Alexandre Simon, Co-fondateur"
        profile.contact_profiles = {}
        c.get_writing_style_profile.return_value = profile

        repo_instance = MagicMock()
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
             patch("app.db.repositories.account_repository.AccountRepository",
                   return_value=repo_instance), \
             patch("app.db.database.get_db_session"):
            resp = client.post(
                "/api/refine-text",
                json={"text": "rdv demain", "instruction": "Rédige un email"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        # Account repository should NOT have been queried — the profile already
        # had typical_signature and the fallback is conditional.
        repo_instance.get.assert_not_called()

    def test_no_fallback_when_account_id_unresolved(self, client):
        """No account context (legacy / unauthed-Tauri) → skip the DB lookup
        rather than crash."""
        c = _mock_container_returning(LLM_BODY_WITH_NAME_LEAK)
        repo_instance = MagicMock()

        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=0), \
             patch("app.db.repositories.account_repository.AccountRepository",
                   return_value=repo_instance), \
             patch("app.db.database.get_db_session"):
            resp = client.post(
                "/api/refine-text",
                json={"text": "rdv demain", "instruction": "Rédige un email"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        repo_instance.get.assert_not_called()
