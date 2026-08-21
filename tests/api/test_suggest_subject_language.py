# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression test for /api/compose/suggest-subject language coherence.

Audit 2026-05-19, T31.1 finding: when a Ctrl+G-generated body opens with an
English greeting ("Hi Crypto,") but the actual content is French, the
subject generator was reading the salutation as a language signal and
producing English subjects alongside French bodies — a per-thread language
mismatch visible in the recipient's inbox preview.

The fix detects the body's language on the post-greeting content and
hard-codes the target language into the LLM system prompt.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")


@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _make_llm(subject_out: str = "Sujet test") -> MagicMock:
    r = MagicMock()
    r.content = subject_out
    c = MagicMock()
    c.llm_drafting.complete.return_value = r
    return c


def _system_prompt_arg(complete_mock: MagicMock) -> str:
    """Pluck the system prompt out of the LLM call."""
    assert complete_mock.called
    _, kwargs = complete_mock.call_args
    return kwargs.get("system", "")


class TestSubjectLanguageConstraint:
    def test_french_body_with_english_greeting_forces_french_subject(self, client):
        """The exact T31.1 regression body — should still detect FR and
        constrain the subject to French in the LLM prompt."""
        c = _make_llm("Confirmation appel Q4 demain")
        body = (
            "Hi Crypto,\n\n"
            "Je confirme que je suis disponible demain à 14h pour l'appel Q4. "
            "Je prépare les slides en ce moment.\n\n"
            "Alexandre Simon,"
        )
        with patch("app.api.routes_helpers._get_container", return_value=c):
            resp = client.post(
                "/api/compose/suggest-subject",
                json={"body": body},
            )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        system_prompt = _system_prompt_arg(c.llm_drafting.complete)
        # The LANGUE OBLIGATOIRE directive must name FRENCH explicitly so
        # the LLM can't fall back to the salutation-language heuristic.
        assert "LANGUE OBLIGATOIRE" in system_prompt
        assert "FRENCH" in system_prompt
        assert "ENGLISH" not in system_prompt

    def test_english_body_forces_english_subject(self, client):
        c = _make_llm("Q4 call tomorrow")
        body = (
            "Hi Marc,\n\n"
            "Confirming I'm available tomorrow at 2 pm for the Q4 call. "
            "I'm prepping the slides now.\n\n"
            "Cheers,"
        )
        with patch("app.api.routes_helpers._get_container", return_value=c):
            resp = client.post(
                "/api/compose/suggest-subject",
                json={"body": body},
            )
        assert resp.status_code == 200
        system_prompt = _system_prompt_arg(c.llm_drafting.complete)
        assert "LANGUE OBLIGATOIRE" in system_prompt
        assert "ENGLISH" in system_prompt
        assert "FRENCH" not in system_prompt

    def test_french_body_with_loanwords_stays_french(self, client):
        """Body with FR content but EN technical loanwords (brief, deadline,
        slides, Q4) must still detect FR — those tokens shouldn't tip the
        scale to English."""
        c = _make_llm("Brief équipe vendredi")
        body = (
            "Bonjour,\n\n"
            "Je prépare le brief pour l'équipe avec les slides et le "
            "deadline pour vendredi. Q4 est notre priorité.\n\n"
            "Merci,"
        )
        with patch("app.api.routes_helpers._get_container", return_value=c):
            resp = client.post(
                "/api/compose/suggest-subject",
                json={"body": body},
            )
        assert resp.status_code == 200
        system_prompt = _system_prompt_arg(c.llm_drafting.complete)
        assert "LANGUE OBLIGATOIRE" in system_prompt
        assert "FRENCH" in system_prompt

    def test_empty_body_returns_400_without_calling_llm(self, client):
        c = _make_llm("ignored")
        with patch("app.api.routes_helpers._get_container", return_value=c):
            resp = client.post(
                "/api/compose/suggest-subject",
                json={"body": ""},
            )
        assert resp.status_code == 400
        c.llm_drafting.complete.assert_not_called()
