# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression test for the contacts-DB fallback in /api/refine-text.

When the NewMessageModal does not supply ``sender_name`` (typical for a
direct-typed recipient that bypassed contact autocomplete) AND the user has
no per-contact override for that recipient in their WritingStyleProfile,
the route must still produce a `mandatory_opening` greeting instead of
letting the LLM fall back to the email-username heuristic
(observed regression 2026-05-19: drafts to `cours.universite@…`
opened with "Hi Crypto," instead of "Bonjour Alexandre,").

The third fallback (contact_nickname → sender_name_hint → contacts.name)
queries the contacts table for the resolved account_id and uses the stored
display name's first token.
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


def _mock_container_with_haiku(refined_text: str) -> MagicMock:
    r = MagicMock()
    r.content = refined_text
    c = MagicMock()
    c.llm_drafting.complete.return_value = r
    c.llm_drafting_smart.complete.return_value = r
    # No writing-style profile: forces the route past the contact_nickname
    # branch and into the sender_name_hint / contacts-DB fallback chain.
    c.get_writing_style_profile.return_value = None
    return c


def _captured_user_prompt(complete_mock: MagicMock) -> str:
    """Pluck the user-prompt arg out of `llm.complete(system=…, user=…)`."""
    assert complete_mock.called, "llm_drafting.complete was never invoked"
    _, kwargs = complete_mock.call_args
    return kwargs.get("user", "")


class TestContactsDBFallbackFirstName:
    """Third-fallback: contact_nickname=None, sender_name_hint='', contacts.name set."""

    def test_uses_contacts_db_display_name_when_client_omits_sender_name(self, client):
        from app.db.models.contact import Contact

        fake_contact = Contact(
            id=99,
            account_id=42,
            email="alexandre.simon@hotmail.com",
            name="Alexandre Simon",
        )
        repo_instance = MagicMock()
        repo_instance.get_by_email.return_value = fake_contact

        c = _mock_container_with_haiku("Bonjour Alexandre,\n\nOK pour demain. Merci,")
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
             patch("app.db.repositories.contact_repository.ContactRepository",
                   return_value=repo_instance), \
             patch("app.db.database.get_db_session") as mock_sess:
            mock_sess.return_value.__enter__.return_value = MagicMock()
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "rdv demain 14h confirmer agenda",
                    "instruction": "Rédige un email complet",
                    "to": "alexandre.simon@hotmail.com",
                    # NOTE: sender_name intentionally omitted — this is the
                    # exact frontend payload that triggered the regression.
                },
                headers=_auth_headers(),
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        prompt = _captured_user_prompt(c.llm_drafting.complete)
        # The contacts-DB fallback should have produced
        # mandatory_opening = "Bonjour Alexandre,", which appears in the
        # user-prompt REMINDER tail emitted at routes_drafts.py:1553.
        assert "Bonjour Alexandre," in prompt, (
            "Expected contacts-DB fallback to inject 'Bonjour Alexandre,' "
            f"into the LLM prompt, got:\n{prompt[-500:]}"
        )
        # First-name-only: never ship the full "Simon" to avoid awkward
        # "Bonjour Alexandre Simon," in casual French registers.
        assert "Bonjour Alexandre Simon," not in prompt
        repo_instance.get_by_email.assert_called_once_with(
            "alexandre.simon@hotmail.com", 42
        )

    def test_silently_no_ops_when_contact_not_in_db(self, client):
        """No contact row → mandatory_opening stays None; route still succeeds."""
        repo_instance = MagicMock()
        repo_instance.get_by_email.return_value = None

        c = _mock_container_with_haiku("Bonjour,\n\nOK. Merci,")
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
             patch("app.db.repositories.contact_repository.ContactRepository",
                   return_value=repo_instance), \
             patch("app.db.database.get_db_session") as mock_sess:
            mock_sess.return_value.__enter__.return_value = MagicMock()
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "rdv demain",
                    "instruction": "Rédige un email",
                    "to": "unknown@example.com",
                },
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        prompt = _captured_user_prompt(c.llm_drafting.complete)
        # No mandatory-opening REMINDER tail — the LLM is free to infer
        # a generic greeting (the username-heuristic is still the LLM's
        # own behavior at this point; the fallback only fires when we
        # have a real name to inject).
        assert "MANDATORY OPENING LINE" not in prompt
        assert "REMINDER: start the refined email with exactly" not in prompt

    def test_client_sender_name_still_wins_over_db_lookup(self, client):
        """When the frontend DOES pass sender_name, the second-priority branch
        takes effect — we never reach the contacts-DB lookup."""
        repo_instance = MagicMock()
        repo_instance.get_by_email.return_value = MagicMock(name="should_not_be_called")

        c = _mock_container_with_haiku("Bonjour Bob,\n\nOK. Merci,")
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
             patch("app.db.repositories.contact_repository.ContactRepository",
                   return_value=repo_instance), \
             patch("app.db.database.get_db_session"):
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "rdv demain",
                    "instruction": "Rédige un email",
                    "to": "bob@example.com",
                    "sender_name": "Bob Roberts",
                },
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        prompt = _captured_user_prompt(c.llm_drafting.complete)
        assert "Bonjour Bob," in prompt
        # The DB lookup should be skipped entirely when sender_name_hint
        # already produced a mandatory_opening.
        repo_instance.get_by_email.assert_not_called()
