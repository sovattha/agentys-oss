# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for `_tokenize_greeting` — conservative greeting template tokenizer.

The function replaces the recipient's first name with ``{first_name}`` in a
greeting, but only when the name appears immediately after a known greeting
anchor (Bonjour, Salut, Hi, Dear, …). The conservative rule prevents false
positives on short nicknames (Al, Eva, Sam).
"""

from app.prompts.identity import _tokenize_greeting


class TestTokenizeGreetingHappyPath:
    """Nickname is anchored right after a known greeting word."""

    def test_bonjour_fr(self):
        assert _tokenize_greeting("Bonjour Alexandra,", "Alexandra") == "Bonjour {first_name},"

    def test_salut_casual(self):
        assert _tokenize_greeting("Salut Alice,", "Alice") == "Salut {first_name},"

    def test_hi_en(self):
        assert _tokenize_greeting("Hi Sarah,", "Sarah") == "Hi {first_name},"

    def test_hello_no_trailing_punct(self):
        assert _tokenize_greeting("Hello Alice", "Alice") == "Hello {first_name}"

    def test_hey_with_bang(self):
        assert _tokenize_greeting("Hey Sam!", "Sam") == "Hey {first_name}!"

    def test_dear_formal(self):
        assert _tokenize_greeting("Dear Paul,", "Paul") == "Dear {first_name},"

    def test_coucou_fr_casual(self):
        assert _tokenize_greeting("Coucou Ben !", "Ben") == "Coucou {first_name} !"

    def test_cher_fr_formal(self):
        assert _tokenize_greeting("Cher Paul,", "Paul") == "Cher {first_name},"

    def test_chere_accented(self):
        assert _tokenize_greeting("Chère Marie,", "Marie") == "Chère {first_name},"


class TestTokenizeGreetingCase:
    """Case handling: anchor case-insensitive, original case preserved."""

    def test_lowercase_anchor_preserved(self):
        assert _tokenize_greeting("bonjour alexandra,", "Alexandra") == "bonjour {first_name},"

    def test_uppercase_anchor_preserved(self):
        assert _tokenize_greeting("BONJOUR Alexandra,", "Alexandra") == "BONJOUR {first_name},"

    def test_nickname_case_insensitive(self):
        # Stored nickname ("Alexandra") matches lowercase in text
        assert _tokenize_greeting("Bonjour alexandra,", "Alexandra") == "Bonjour {first_name},"


class TestTokenizeGreetingNoop:
    """Inputs where no tokenization must happen."""

    def test_empty_nickname(self):
        assert _tokenize_greeting("Bonjour Alexandra,", "") == "Bonjour Alexandra,"

    def test_empty_text(self):
        assert _tokenize_greeting("", "Alexandra") == ""

    def test_title_between_anchor_and_name(self):
        # "Maître" is not an anchor, so "Dupont" stays literal
        assert _tokenize_greeting("Bonjour Maître Dupont,", "Robert") == "Bonjour Maître Dupont,"

    def test_nickname_not_directly_after_anchor(self):
        # Comma + toi between anchor and nickname → no match
        assert _tokenize_greeting("Coucou toi, Alex!", "Alex") == "Coucou toi, Alex!"

    def test_different_name_in_greeting(self):
        assert _tokenize_greeting("Bonjour Alice,", "Alexandra") == "Bonjour Alice,"

    def test_bonsoir_not_in_anchor_list(self):
        # Conservative: deliberately excluded to keep the list short
        assert _tokenize_greeting("Bonsoir Alexandra,", "Alexandra") == "Bonsoir Alexandra,"

    def test_nickname_in_middle_not_after_anchor(self):
        # Only the token immediately after the anchor is tokenized
        assert _tokenize_greeting("Bonjour Alice et Bob,", "Bob") == "Bonjour Alice et Bob,"


class TestTokenizeGreetingSafety:
    """Guards against false positives and double-tokenization."""

    def test_short_nickname_whole_word_only(self):
        # "Al" must not match inside "Alice"
        assert _tokenize_greeting("Bonjour Alice,", "Al") == "Bonjour Alice,"

    def test_short_nickname_whole_word_match(self):
        # But "Al" matches exact "Al"
        assert _tokenize_greeting("Bonjour Al,", "Al") == "Bonjour {first_name},"

    def test_idempotent_first_name_token(self):
        assert _tokenize_greeting("Bonjour {first_name},", "Alexandra") == "Bonjour {first_name},"

    def test_idempotent_last_name_token(self):
        assert _tokenize_greeting("Bonjour {last_name},", "Alexandra") == "Bonjour {last_name},"

    def test_idempotent_civility_token(self):
        assert _tokenize_greeting("{civility} Dupont,", "Alexandra") == "{civility} Dupont,"

    def test_accented_nickname(self):
        assert _tokenize_greeting("Bonjour Léa,", "Léa") == "Bonjour {first_name},"
