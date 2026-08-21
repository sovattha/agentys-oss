# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.utils.tts_cleaner."""

from app.utils.tts_cleaner import clean_for_tts


class TestCleanForTts:
    def test_empty_string(self):
        assert clean_for_tts("") == ""

    def test_none_input(self):
        assert clean_for_tts(None) == ""

    def test_plain_text_unchanged(self):
        text = "Bonjour, merci pour votre message."
        assert clean_for_tts(text) == text

    def test_url_replaced(self):
        text = "Voir https://example.com/page pour plus de détails."
        result = clean_for_tts(text)
        assert "https://" not in result
        assert "lien" in result

    def test_multiple_urls(self):
        text = "Voir https://a.com et http://b.com"
        result = clean_for_tts(text)
        assert result.count("lien") == 2

    def test_email_address_replaced(self):
        text = "Contactez jean.dupont@example.com"
        result = clean_for_tts(text)
        assert "adresse email de jean.dupont" in result
        assert "@" not in result

    def test_bullets_removed(self):
        text = "Points importants :\n- Premier point\n- Deuxième point"
        result = clean_for_tts(text)
        assert "- " not in result
        assert "Premier point" in result

    def test_numbered_list_removed(self):
        text = "1. Premier\n2. Deuxième\n3. Troisième"
        result = clean_for_tts(text)
        assert "1." not in result
        assert "Premier" in result

    def test_abbreviation_etc(self):
        text = "Documents, factures, etc."
        result = clean_for_tts(text)
        assert "et cetera" in result

    def test_abbreviation_cf(self):
        text = "cf. le document annexe"
        result = clean_for_tts(text)
        assert "confer" in result

    def test_abbreviation_asap(self):
        text = "Merci de répondre ASAP"
        result = clean_for_tts(text)
        assert "dès que possible" in result

    def test_abbreviation_fyi(self):
        text = "FYI, la réunion est reportée"
        result = clean_for_tts(text)
        assert "pour information" in result

    def test_excessive_whitespace(self):
        text = "Premier paragraphe.\n\n\n\n\nDeuxième paragraphe."
        result = clean_for_tts(text)
        assert "\n\n\n" not in result
        assert "Premier paragraphe." in result

    def test_multiple_spaces(self):
        text = "Mot    avec    espaces"
        result = clean_for_tts(text)
        assert "  " not in result

    def test_combined_transformations(self):
        text = (
            "Bonjour M. Dupont,\n\n"
            "- Voir https://docs.example.com/report\n"
            "- Contacter jean@test.com ASAP\n\n"
            "Merci, etc."
        )
        result = clean_for_tts(text)
        assert "Monsieur" in result
        assert "lien" in result
        assert "adresse email de jean" in result
        assert "dès que possible" in result
        assert "et cetera" in result
        assert "- " not in result
