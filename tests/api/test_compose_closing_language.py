# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Compose: a French closing must not leak into an English draft (2026-06-23).

User report: an English email ("Hi Matt," / "Looking forward to meeting you
tomorrow afternoon.") was signed "Merci,". Two root causes:

1. "merci" — the single most common French sign-off — was missing from the
   closing-detection tables, so it was never recognised as French and never
   translated.
2. Compose had no deterministic fallback when the LLM ignored the prompt's
   LANGUAGE OVERRIDE. `_apply_compose_body_cleanup` now detects the body
   language and rewrites a trailing closing that is in the wrong language.
"""
from __future__ import annotations

from unittest.mock import patch

from app.prompts.identity import (
    _is_french_closing,
    _translate_closing_to_english,
    _translate_closing_to_french,
    normalize_closing_to_language,
)


class TestClosingTables:
    def test_merci_recognised_as_french(self):
        assert _is_french_closing("Merci")
        assert _is_french_closing("Merci beaucoup")

    def test_merci_translates_to_english(self):
        assert _translate_closing_to_english("Merci") == "Thanks"
        assert _translate_closing_to_english("Merci beaucoup") == "Thank you"

    def test_english_closings_translate_to_french(self):
        assert _translate_closing_to_french("Best") == "Cordialement"
        assert _translate_closing_to_french("Cheers") == "À bientôt"
        assert _translate_closing_to_french("Thanks") == "Merci"
        assert _translate_closing_to_french("Best regards") == "Cordialement"


class TestNormalizeClosingToLanguage:
    def test_french_closing_in_english_body_is_translated(self):
        """The exact reported bug."""
        body = "Hi Matt,\n\nLooking forward to meeting you tomorrow afternoon.\n\nMerci,"
        out = normalize_closing_to_language(body, "en")
        assert out.endswith("Thanks,")
        assert "Merci" not in out
        # The body above the closing is untouched.
        assert "Looking forward to meeting you tomorrow afternoon." in out

    def test_cordialement_in_english_body(self):
        body = "Hi,\n\nThe report is attached.\n\nCordialement,"
        out = normalize_closing_to_language(body, "en")
        assert out.endswith("Best regards,")

    def test_english_closing_in_french_body_is_translated(self):
        body = "Bonjour Matt,\n\nAu plaisir de te voir demain.\n\nBest,"
        out = normalize_closing_to_language(body, "fr")
        assert out.endswith("Cordialement,")

    def test_matching_language_left_unchanged(self):
        en = "Hi Matt,\n\nSee you soon.\n\nThanks,"
        assert normalize_closing_to_language(en, "en") == en
        fr = "Bonjour,\n\nÀ demain.\n\nMerci,"
        assert normalize_closing_to_language(fr, "fr") == fr

    def test_long_trailing_sentence_not_touched(self):
        # Last line is a sentence (not a sign-off) that merely starts with a
        # closing word — the <=4-word guard must leave it alone.
        body = "Hi,\n\nMerci de bien vouloir confirmer votre présence avant demain."
        assert normalize_closing_to_language(body, "en") == body

    def test_unsupported_language_is_noop(self):
        body = "Hola,\n\nNos vemos.\n\nMerci,"
        assert normalize_closing_to_language(body, "es") == body

    def test_empty_body_safe(self):
        assert normalize_closing_to_language("", "en") == ""
        assert normalize_closing_to_language(None, "en") is None


class TestComposeCleanupIntegration:
    def test_reported_bug_english_email_signed_merci(self):
        from app.api.routes_misc import _apply_compose_body_cleanup
        body = "Hi Matt,\n\nLooking forward to meeting you tomorrow afternoon.\n\nMerci,"
        # Pin the language so the test never depends on langdetect's installation
        # or its behaviour on short text — the wiring (detect → normalize) is
        # what's under test here.
        with patch("app.application.detect_language.DetectLanguage.run", return_value="en"):
            out = _apply_compose_body_cleanup(body, typical_signature=None)
        assert out.endswith("Thanks,")
        assert "Merci" not in out

    def test_english_body_with_english_closing_untouched(self):
        from app.api.routes_misc import _apply_compose_body_cleanup
        body = "Hi Matt,\n\nLooking forward to meeting you tomorrow afternoon.\n\nThanks,"
        with patch("app.application.detect_language.DetectLanguage.run", return_value="en"):
            out = _apply_compose_body_cleanup(body, typical_signature=None)
        assert out.endswith("Thanks,")


class TestReplyDriftClosing:
    """The reply pipeline shares the leak: _detect_language_drift skips short
    lines, so a one-word wrong-language sign-off must be normalized too."""

    def test_french_closing_in_english_reply_is_fixed(self):
        from app.smart_routing import _detect_language_drift
        draft = "Hi Matt,\n\nThat works for me, see you then.\n\nMerci,"
        out = _detect_language_drift(draft, "ENGLISH")
        assert out.endswith("Thanks,")
        assert "Merci" not in out

    def test_english_closing_in_french_reply_is_fixed(self):
        from app.smart_routing import _detect_language_drift
        draft = "Bonjour Matt,\n\nC'est parfait, à demain alors.\n\nBest,"
        out = _detect_language_drift(draft, "FRENCH")
        assert out.endswith("Cordialement,")

    def test_correct_language_reply_untouched(self):
        from app.smart_routing import _detect_language_drift
        draft = "Hi Matt,\n\nThat works for me, see you then.\n\nThanks,"
        assert _detect_language_drift(draft, "ENGLISH").endswith("Thanks,")
