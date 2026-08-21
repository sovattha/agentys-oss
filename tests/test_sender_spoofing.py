"""Tests for sender display-name spoof detection.

Audit 2026-05-18: an inbox carried a row labelled
``"Хfinity Billpay"`` (Cyrillic Х + invisible variation selectors) with no
warning. detect_sender_spoofing now returns ``(cleaned, True)`` for that
shape and ``(name, False)`` for legitimate names.
"""

import os
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

from app.utils.sender_spoofing import detect_sender_spoofing, strip_invisible


class TestStripInvisible:
    def test_drops_variation_selectors(self) -> None:
        # \U000E0100 is VARIATION SELECTOR-17 — frequently abused.
        s = "X\U000E0100finity"
        assert strip_invisible(s) == "Xfinity"

    def test_drops_zero_width_joiner(self) -> None:
        s = "Pay‍Pal"  # ZWJ between Pay and Pal
        assert strip_invisible(s) == "PayPal"

    def test_drops_word_joiner(self) -> None:
        s = "Spotify⁠Music"
        assert strip_invisible(s) == "SpotifyMusic"

    def test_leaves_normal_text_alone(self) -> None:
        assert strip_invisible("Alice & Bob") == "Alice & Bob"

    def test_handles_empty(self) -> None:
        assert strip_invisible("") == ""
        assert strip_invisible(None) is None  # type: ignore[arg-type]


class TestDetectSenderSpoofing:
    def test_flags_invisible_chars(self) -> None:
        cleaned, spoofed = detect_sender_spoofing("Pay‍Pal")
        assert cleaned == "PayPal"
        assert spoofed is True

    def test_flags_mixed_latin_cyrillic(self) -> None:
        # Capital Х is U+0425 CYRILLIC, not Latin.
        cleaned, spoofed = detect_sender_spoofing("Хfinity Billpay")
        assert cleaned == "Хfinity Billpay"  # script mix only, no invisibles
        assert spoofed is True

    def test_flags_repro_case_combined(self) -> None:
        # The exact pattern from the audit screenshot: Cyrillic + variation
        # selectors interleaved.
        raw = "Х\U000E0100f\U000E0100i\U000E0100n\U000E0100i\U000E0100ty"
        cleaned, spoofed = detect_sender_spoofing(raw)
        assert cleaned == "Хfinity"
        assert spoofed is True

    def test_clean_french_name_is_not_spoofed(self) -> None:
        cleaned, spoofed = detect_sender_spoofing("François Müller")
        assert cleaned == "François Müller"
        assert spoofed is False

    def test_clean_ascii_is_not_spoofed(self) -> None:
        cleaned, spoofed = detect_sender_spoofing("savagecrypto22")
        assert cleaned == "savagecrypto22"
        assert spoofed is False

    def test_fully_cyrillic_name_is_not_spoofed(self) -> None:
        # Legitimate Russian display name — no Latin mixed in.
        cleaned, spoofed = detect_sender_spoofing("Андрей Иванов")
        assert spoofed is False

    def test_fully_greek_name_is_not_spoofed(self) -> None:
        cleaned, spoofed = detect_sender_spoofing("Γιάννης Παπαδόπουλος")
        assert spoofed is False

    def test_none_and_empty(self) -> None:
        assert detect_sender_spoofing("") == ("", False)
        assert detect_sender_spoofing(None) == ("", False)

    def test_emoji_in_name_is_not_spoofed(self) -> None:
        # Emoji are not letters, so they don't trigger mixed-script.
        cleaned, spoofed = detect_sender_spoofing("Acme 🎁 Team")
        assert spoofed is False
