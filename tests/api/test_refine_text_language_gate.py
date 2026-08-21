# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression test for the Ctrl+G language-anchor guard in /api/refine-text.

Audit 2026-05-20 — the round-4 (2026-05-19) change runs `langdetect` over the
user's notes so a genuinely English/Spanish note no longer gets forced back to
French. But `langdetect` is a coin-flip on short / abbreviation-heavy notes: a
5-word French note ("rdv demain 14h confirmer agenda") returns "en", which then
flipped the WHOLE draft (greeting, closing, body) to English — user report.

Guard: only trust a switch AWAY from the user's primary language when the note
has at least `_MIN_WORDS_FOR_NONPRIMARY_LANG` words; below that, keep the
primary. The detector is mocked here so the assertions test the GUARD logic
deterministically rather than langdetect's randomness (the end-to-end check
against the real detector lives in test_refine_text_contact_db_fallback.py).
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


def _mock_container(body: str = "Bonjour,\n\nOk pour demain.\n\nÀ bientôt,") -> MagicMock:
    r = MagicMock()
    r.content = body
    c = MagicMock()
    c.llm_drafting.complete.return_value = r
    c.llm_drafting_smart.complete.return_value = r
    c.get_writing_style_profile.return_value = None
    return c


def _system_text(complete_mock: MagicMock) -> str:
    """Flatten the `system=` arg (a list of SystemSegment) to one string."""
    assert complete_mock.called, "llm_drafting.complete was never invoked"
    _, kwargs = complete_mock.call_args
    sys = kwargs.get("system", "")
    if isinstance(sys, (list, tuple)):
        return "\n".join(getattr(s, "text", str(s)) for s in sys)
    return str(sys)


def _post(client, text: str, detected: str, primary: str):
    """POST a refine with the detector forced to `detected` and the account's
    primary language forced to `primary` (drafter label, e.g. 'FRENCH')."""
    c = _mock_container()
    with patch("app.api.routes_helpers._get_container", return_value=c), \
         patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
         patch("app.application.detect_language.DetectLanguage.run", return_value=detected), \
         patch("app.prompts.load_primary_language_for_account", return_value=primary):
        resp = client.post(
            "/api/refine-text",
            json={"text": text, "instruction": "Rédige un email complet"},
            headers=_auth_headers(),
        )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return _system_text(c.llm_drafting.complete)


def _post_with_target(client, text: str, detected: str, primary: str, target: str):
    c = _mock_container()
    with patch("app.api.routes_helpers._get_container", return_value=c), \
         patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
         patch("app.application.detect_language.DetectLanguage.run", return_value=detected), \
         patch("app.prompts.load_primary_language_for_account", return_value=primary):
        resp = client.post(
            "/api/refine-text",
            json={
                "text": text,
                "instruction": "Rédige un email complet",
                "target_language": target,
            },
            headers=_auth_headers(),
        )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return _system_text(c.llm_drafting.complete)


def _post_instruction(
    client, text: str, instruction: str, detected: str, primary: str,
    target: str | None = None,
):
    """Like _post but with a caller-supplied free-text instruction (and an
    optional target_language thread hint)."""
    c = _mock_container()
    body: dict = {"text": text, "instruction": instruction}
    if target is not None:
        body["target_language"] = target
    with patch("app.api.routes_helpers._get_container", return_value=c), \
         patch("app.api.routes_drafts._rh._resolve_account_id_for_user", return_value=42), \
         patch("app.application.detect_language.DetectLanguage.run", return_value=detected), \
         patch("app.prompts.load_primary_language_for_account", return_value=primary):
        resp = client.post(
            "/api/refine-text", json=body, headers=_auth_headers(),
        )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return _system_text(c.llm_drafting.complete)


class TestLanguageGate:
    def test_short_french_note_misdetected_as_english_stays_french(self, client):
        """The exact reported case: 5-word FR note, detector flips to 'en'.
        The guard must keep French (< 8 words → low confidence)."""
        sys = _post(client, "rdv demain 14h confirmer agenda",
                    detected="en", primary="FRENCH")
        assert "entièrement en français" in sys, (
            f"short FR note was not anchored to French:\n{sys[-600:]}"
        )
        assert "entire email in English" not in sys

    def test_long_english_note_still_switches_to_english(self, client):
        """The guard must NOT over-correct: a clearly-English note with enough
        words keeps the round-4 behaviour (switch to English)."""
        sys = _post(
            client,
            "please confirm whether tomorrow afternoon still works for our "
            "quarterly budget review call",  # 12 words ≥ threshold
            detected="en", primary="FRENCH",
        )
        assert "entire email in English" in sys, (
            f"long EN note was wrongly forced to French:\n{sys[-600:]}"
        )
        assert "entièrement en français" not in sys

    def test_guard_uses_account_primary_not_hardcoded_french(self, client):
        """Symmetry: an English-primary user's short note misdetected as 'fr'
        must stay English — the guard keys on the user's primary language,
        not a hard-coded French default."""
        sys = _post(client, "call me back asap please",  # 5 words < threshold
                    detected="fr", primary="ENGLISH")
        assert "entire email in English" in sys, (
            f"EN-primary user's short note was not anchored to English:\n{sys[-600:]}"
        )
        assert "entièrement en français" not in sys

    def test_switch_to_primary_is_always_kept(self, client):
        """When the detection AGREES with the primary language, the word-count
        floor is irrelevant — a short note in the primary language is fine."""
        sys = _post(client, "ok pour demain", detected="fr", primary="FRENCH")
        assert "entièrement en français" in sys

    def test_explicit_target_language_overrides_long_source_language(self, client):
        sys = _post_with_target(
            client,
            "please confirm whether tomorrow afternoon still works for our "
            "quarterly budget review call",
            detected="en",
            primary="FRENCH",
            target="fr",
        )
        assert "entièrement en français" in sys
        assert "entire email in English" not in sys


class TestTranslateInstruction:
    """Audit 2026-06-17 — the reported "AI instructions don't work" case: a
    French draft with the free-text instruction « traduit en anglais » never
    switched language because `detected_lang` is keyed on the DRAFT body (FR),
    not on the instruction, and the LANGUAGE HARD CONSTRAINT then forbade the
    switch. An explicit language-change instruction must now win over both the
    detected source language and the thread target_language hint."""

    def test_french_draft_translate_to_english_switches_to_english(self, client):
        """The exact screenshot case: FR draft + « traduit en anglais »."""
        sys = _post_instruction(
            client,
            "Salut Nathan, Ça te va demain ? Merci,",
            "traduit en anglais",
            detected="fr", primary="FRENCH",
        )
        assert "entire email in English" in sys, (
            f"FR draft was not switched to English by the translate "
            f"instruction:\n{sys[-700:]}"
        )
        assert "entièrement en français" not in sys

    def test_english_draft_translate_to_french_switches_to_french(self, client):
        """Symmetric: EN draft + « mets ça en français »."""
        sys = _post_instruction(
            client,
            "Hi Alex, does tomorrow afternoon still work? Thanks,",
            "mets ça en français",
            detected="en", primary="ENGLISH",
        )
        assert "entièrement en français" in sys, (
            f"EN draft was not switched to French:\n{sys[-700:]}"
        )
        assert "entire email in English" not in sys

    def test_translate_to_spanish(self, client):
        sys = _post_instruction(
            client,
            "Salut Nathan, Ça te va demain ? Merci,",
            "traduis en espagnol",
            detected="fr", primary="FRENCH",
        )
        assert "en español" in sys
        assert "entièrement en français" not in sys

    def test_english_keyword_instruction(self, client):
        """A non-French wording of the same intent ("translate to English")."""
        sys = _post_instruction(
            client,
            "Salut Nathan, Ça te va demain ? Merci,",
            "translate this to English",
            detected="fr", primary="FRENCH",
        )
        assert "entire email in English" in sys
        assert "entièrement en français" not in sys

    def test_translate_instruction_beats_thread_target_hint(self, client):
        """Precedence: the explicit instruction wins over a target_language
        thread hint that points the other way."""
        sys = _post_instruction(
            client,
            "Salut Nathan, Ça te va demain ? Merci,",
            "traduit en anglais",
            detected="fr", primary="FRENCH",
            target="fr",  # thread hint reinforcing French — must NOT win
        )
        assert "entire email in English" in sys
        assert "entièrement en français" not in sys

    def test_non_language_instruction_keeps_source_language(self, client):
        """Negative: a shorten/rewrite instruction with no language named must
        NOT trigger any switch — the anchor guard stays intact."""
        sys = _post_instruction(
            client,
            "Salut Nathan, Ça te va demain ? Merci,",
            "raccourcis ce message",
            detected="fr", primary="FRENCH",
        )
        assert "entièrement en français" in sys
        assert "entire email in English" not in sys


class TestDetectRequestedTargetLanguage:
    """Unit tests for the pure target-language extractor."""

    @pytest.mark.parametrize(
        "instruction,expected",
        [
            ("traduit en anglais", "en"),
            ("Traduis en anglais s'il te plaît", "en"),
            ("translate to English", "en"),
            ("translate this into english", "en"),
            ("mets ça en français", "fr"),
            ("rewrite in French", "fr"),
            ("traduis en espagnol", "es"),
            ("traducir al español", "es"),
            ("écris l'email en anglais", "en"),
            # No language named → None
            ("raccourcis ce message", None),
            ("rends le plus formel", None),
            ("corrige les fautes", None),
            ("", None),
            # Language mentioned but not as a translation/direction target
            ("parle de mon voyage en Angleterre", None),
            # Unsupported target language → None (pre-existing limitation)
            ("traduit en allemand", None),
        ],
    )
    def test_extracts_target_language(self, instruction, expected):
        from app.api.routes_drafts import _detect_requested_target_language
        assert _detect_requested_target_language(instruction) == expected
