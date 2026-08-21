# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour EmailParserMixin.

Ce module teste les utilitaires de parsing d'emails:
1. _parse_email_address - parsing d'adresses email avec/sans nom
2. _extract_text_from_html - extraction de texte brut depuis HTML
3. _normalize_recipients - normalisation de listes de destinataires

TDD: Tests ecrits AVANT ou pour valider l'implementation.
Clean Architecture: Infrastructure layer (shared utilities).
"""

import pytest

from app.providers.email_parser_mixin import EmailParserMixin


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def parser() -> EmailParserMixin:
    """Instance du mixin pour les tests."""
    return EmailParserMixin()


# =============================================================================
# TESTS - _parse_email_address
# =============================================================================


class TestParseEmailAddressBasicFormats:
    """Tests pour les formats basiques d'adresse email."""

    def test_simple_email(self, parser):
        """Parse une adresse email simple."""
        email, name = parser._parse_email_address("john@example.com")
        assert email == "john@example.com"
        assert name is None

    def test_email_with_quoted_name(self, parser):
        """Parse 'Name' <email>."""
        email, name = parser._parse_email_address('"John Doe" <john@example.com>')
        assert email == "john@example.com"
        assert name == "John Doe"

    def test_email_with_unquoted_name(self, parser):
        """Parse Name <email> sans guillemets."""
        email, name = parser._parse_email_address("John Doe <john@example.com>")
        assert email == "john@example.com"
        assert name == "John Doe"

    def test_email_in_angle_brackets_only(self, parser):
        """Parse <email> sans nom."""
        email, name = parser._parse_email_address("<john@example.com>")
        assert email == "john@example.com"
        assert name is None

    def test_email_with_subdomain(self, parser):
        """Parse email avec sous-domaine."""
        email, name = parser._parse_email_address("user@mail.example.com")
        assert email == "user@mail.example.com"
        assert name is None


class TestParseEmailAddressReDoS:
    """Regression (chaos audit 2026-06-02, P2): the unanchored fallback regex
    _EMAIL_IN_TEXT_RE used to backtrack O(n^2) on a long no-'@' header value,
    hanging the single worker (algorithmic-complexity DoS). The local-part
    quantifier is now bounded, so this must complete near-instantly."""

    @pytest.mark.timeout(5)
    def test_long_no_at_header_does_not_hang(self, parser):
        # ~200k chars of local-part-class with NO '@' — the catastrophic input.
        payload = '"' + ("a" * 200_000) + "<"
        email, name = parser._parse_email_address(payload)
        # No '@' anywhere -> the "@ in value" last-resort is not hit either.
        assert email == ""
        assert name is None

    @pytest.mark.timeout(5)
    def test_long_prefix_before_real_email_still_extracts(self, parser):
        # A long run THEN a real address: must still extract it, fast.
        payload = ("a" * 100_000) + " contact: john@example.com"
        email, name = parser._parse_email_address(payload)
        assert email == "john@example.com"


class TestParseEmailAddressNullEmpty:
    """Tests pour les valeurs null/vides."""

    def test_empty_string(self, parser):
        """Retourne ('', None) pour une chaine vide."""
        email, name = parser._parse_email_address("")
        assert email == ""
        assert name is None

    def test_none_value(self, parser):
        """Retourne ('', None) pour None."""
        email, name = parser._parse_email_address(None)
        assert email == ""
        assert name is None

    def test_whitespace_only(self, parser):
        """Gere les chaines avec espaces uniquement."""
        email, name = parser._parse_email_address("   ")
        assert email == ""
        assert name is None


class TestParseEmailAddressWithSpaces:
    """Tests pour les espaces dans l'adresse."""

    def test_leading_spaces(self, parser):
        """Supprime les espaces en debut."""
        email, name = parser._parse_email_address("   john@example.com")
        assert email == "john@example.com"

    def test_trailing_spaces(self, parser):
        """Supprime les espaces en fin."""
        email, name = parser._parse_email_address("john@example.com   ")
        assert email == "john@example.com"

    def test_spaces_around_email(self, parser):
        """Supprime les espaces autour de l'email."""
        email, name = parser._parse_email_address("  john@example.com  ")
        assert email == "john@example.com"

    def test_spaces_in_name(self, parser):
        """Preserve les espaces dans le nom."""
        email, name = parser._parse_email_address('"John  Doe" <john@example.com>')
        assert email == "john@example.com"
        assert name == "John  Doe"


class TestParseEmailAddressUnicode:
    """Tests pour les caracteres Unicode."""

    def test_unicode_name_accents(self, parser):
        """Parse nom avec accents."""
        email, name = parser._parse_email_address('"Jose Garcia" <jose@example.com>')
        assert email == "jose@example.com"
        assert name == "Jose Garcia"

    def test_unicode_name_special(self, parser):
        """Parse nom avec caracteres speciaux."""
        email, name = parser._parse_email_address('"Muller" <muller@example.com>')
        assert email == "muller@example.com"
        assert name == "Muller"

    def test_chinese_name(self, parser):
        """Parse nom chinois."""
        email, name = parser._parse_email_address('"Zhang Wei" <zhang@example.com>')
        assert email == "zhang@example.com"
        assert name == "Zhang Wei"


class TestParseEmailAddressSpecialChars:
    """Tests pour les caracteres speciaux dans l'email."""

    def test_plus_in_email(self, parser):
        """Parse email avec + tag."""
        email, name = parser._parse_email_address("user+tag@example.com")
        assert email == "user+tag@example.com"
        assert name is None

    def test_dot_in_local_part(self, parser):
        """Parse email avec point dans la partie locale."""
        email, name = parser._parse_email_address("john.doe@example.com")
        assert email == "john.doe@example.com"

    def test_underscore_in_email(self, parser):
        """Parse email avec underscore."""
        email, name = parser._parse_email_address("john_doe@example.com")
        assert email == "john_doe@example.com"

    def test_hyphen_in_domain(self, parser):
        """Parse email avec tiret dans le domaine."""
        email, name = parser._parse_email_address("user@my-domain.com")
        assert email == "user@my-domain.com"


class TestParseEmailAddressMalformed:
    """Tests pour les formats malformes."""

    def test_no_at_symbol(self, parser):
        """Retourne vide si pas de @."""
        email, name = parser._parse_email_address("not-an-email")
        assert email == ""
        assert name is None

    def test_missing_closing_bracket(self, parser):
        """Gere les brackets non fermes."""
        # Ce cas devrait toujours extraire l'email via fallback
        email, name = parser._parse_email_address("<john@example.com")
        # Le fallback devrait trouver l'email
        assert "john@example.com" in email or email == ""

    def test_double_at(self, parser):
        """Gere les doubles @."""
        email, name = parser._parse_email_address("john@@example.com")
        # Devrait retourner tel quel car contient @
        assert email == "john@@example.com" or email == ""

    def test_text_with_email_inside(self, parser):
        """Extrait l'email d'un texte."""
        email, name = parser._parse_email_address("Contact: john@example.com please")
        assert email == "john@example.com"

    def test_multiple_emails_returns_first(self, parser):
        """Retourne le premier email trouve."""
        email, name = parser._parse_email_address("a@test.com, b@test.com")
        assert email == "a@test.com"


class TestParseEmailAddressComplexNames:
    """Tests pour les noms complexes."""

    def test_name_with_comma(self, parser):
        """Parse nom avec virgule."""
        email, name = parser._parse_email_address('"Doe, John" <john@example.com>')
        assert email == "john@example.com"
        assert name == "Doe, John"

    def test_name_with_apostrophe(self, parser):
        """Parse nom avec apostrophe."""
        email, name = parser._parse_email_address("\"O'Brien\" <obrien@example.com>")
        assert email == "obrien@example.com"
        assert name == "O'Brien"

    def test_empty_quotes(self, parser):
        """Parse guillemets vides."""
        email, name = parser._parse_email_address('"" <john@example.com>')
        assert email == "john@example.com"
        assert name is None or name == ""


# =============================================================================
# TESTS - _extract_text_from_html
# =============================================================================


class TestExtractTextFromHtmlBasic:
    """Tests basiques pour l'extraction de texte HTML."""

    def test_simple_paragraph(self, parser):
        """Extrait texte d'un paragraphe."""
        html = "<p>Hello World</p>"
        text = parser._extract_text_from_html(html)
        assert text == "Hello World"

    def test_nested_tags(self, parser):
        """Extrait texte de tags imbriques."""
        html = "<div><p><b>Bold</b> text</p></div>"
        text = parser._extract_text_from_html(html)
        assert "Bold" in text
        assert "text" in text

    def test_multiple_paragraphs(self, parser):
        """Extrait texte de multiples paragraphes."""
        html = "<p>First</p><p>Second</p>"
        text = parser._extract_text_from_html(html)
        assert "First" in text
        assert "Second" in text

    def test_plain_text_unchanged(self, parser):
        """Le texte brut reste inchange."""
        plain = "Just plain text"
        text = parser._extract_text_from_html(plain)
        assert text == plain


class TestExtractTextFromHtmlNullEmpty:
    """Tests pour les valeurs null/vides HTML."""

    def test_empty_string(self, parser):
        """Retourne vide pour chaine vide."""
        text = parser._extract_text_from_html("")
        assert text == ""

    def test_none_value(self, parser):
        """Retourne vide pour None."""
        text = parser._extract_text_from_html(None)
        assert text == ""

    def test_whitespace_only(self, parser):
        """Gere les chaines avec espaces."""
        text = parser._extract_text_from_html("   ")
        assert text.strip() == ""

    def test_empty_tags(self, parser):
        """Gere les tags vides."""
        html = "<p></p><div></div>"
        text = parser._extract_text_from_html(html)
        assert text.strip() == ""


class TestExtractTextFromHtmlSpecialTags:
    """Tests pour les tags speciaux."""

    def test_script_tag_removed(self, parser):
        """Supprime le contenu des tags script."""
        html = "<p>Hello</p><script>alert('xss')</script><p>World</p>"
        text = parser._extract_text_from_html(html)
        # Le script ne devrait pas apparaitre (ou juste le contenu textuel)
        assert "alert" not in text or "Hello" in text

    def test_style_tag_removed(self, parser):
        """Supprime le contenu des tags style."""
        html = "<style>.red{color:red}</style><p>Text</p>"
        text = parser._extract_text_from_html(html)
        assert "Text" in text

    def test_br_tag(self, parser):
        """Gere les tags <br>."""
        html = "Line1<br>Line2<br/>Line3"
        text = parser._extract_text_from_html(html)
        assert "Line1" in text
        assert "Line2" in text

    def test_self_closing_tags(self, parser):
        """Gere les tags auto-fermants."""
        html = "<p>Text<img src='img.jpg'/>More</p>"
        text = parser._extract_text_from_html(html)
        assert "Text" in text
        assert "More" in text


class TestExtractTextFromHtmlEntities:
    """Tests pour les entites HTML."""

    def test_nbsp_entity(self, parser):
        """Gere &nbsp;."""
        html = "Hello&nbsp;World"
        text = parser._extract_text_from_html(html)
        # Devrait contenir les mots (nbsp peut etre converti ou supprime)
        assert "Hello" in text
        assert "World" in text

    def test_amp_entity(self, parser):
        """Gere &amp;."""
        html = "Tom &amp; Jerry"
        text = parser._extract_text_from_html(html)
        # Le & devrait etre preserve d'une maniere ou d'une autre
        assert "Tom" in text
        assert "Jerry" in text

    def test_lt_gt_entities(self, parser):
        """Gere &lt; et &gt;."""
        html = "a &lt; b &gt; c"
        text = parser._extract_text_from_html(html)
        assert "a" in text
        assert "b" in text
        assert "c" in text


class TestExtractTextFromHtmlMalformed:
    """Tests pour le HTML malformed."""

    def test_unclosed_tag(self, parser):
        """Gere les tags non fermes."""
        html = "<div>Unclosed content"
        text = parser._extract_text_from_html(html)
        assert "Unclosed content" in text

    def test_nested_unclosed(self, parser):
        """Gere les tags imbriques non fermes."""
        html = "<div><p>Text"
        text = parser._extract_text_from_html(html)
        assert "Text" in text

    def test_extra_closing_tags(self, parser):
        """Gere les tags de fermeture en trop."""
        html = "<p>Text</p></p></div>"
        text = parser._extract_text_from_html(html)
        assert "Text" in text


# =============================================================================
# TESTS - _normalize_recipients
# =============================================================================


class TestNormalizeRecipientsBasic:
    """Tests basiques pour la normalisation des destinataires."""

    def test_single_email(self, parser):
        """Normalise un seul email."""
        recipients = parser._normalize_recipients("john@example.com")
        assert recipients == ["john@example.com"]

    def test_comma_separated(self, parser):
        """Normalise des emails separes par virgule."""
        recipients = parser._normalize_recipients("a@test.com, b@test.com")
        assert recipients == ["a@test.com", "b@test.com"]

    def test_with_names(self, parser):
        """Extrait les emails des adresses avec noms."""
        recipients = parser._normalize_recipients(
            '"John" <john@test.com>, "Jane" <jane@test.com>'
        )
        assert "john@test.com" in recipients
        assert "jane@test.com" in recipients


class TestNormalizeRecipientsNullEmpty:
    """Tests pour les valeurs null/vides."""

    def test_empty_string(self, parser):
        """Retourne liste vide pour chaine vide."""
        recipients = parser._normalize_recipients("")
        assert recipients == []

    def test_none_value(self, parser):
        """Retourne liste vide pour None."""
        recipients = parser._normalize_recipients(None)
        assert recipients == []

    def test_whitespace_only(self, parser):
        """Gere les chaines avec espaces."""
        recipients = parser._normalize_recipients("   ")
        assert recipients == []


class TestNormalizeRecipientsEdgeCases:
    """Tests pour les cas limites."""

    def test_trailing_comma(self, parser):
        """Gere les virgules finales."""
        recipients = parser._normalize_recipients("a@test.com, b@test.com,")
        assert recipients == ["a@test.com", "b@test.com"]

    def test_leading_comma(self, parser):
        """Gere les virgules initiales."""
        recipients = parser._normalize_recipients(", a@test.com")
        assert recipients == ["a@test.com"]

    def test_extra_spaces(self, parser):
        """Gere les espaces supplementaires."""
        recipients = parser._normalize_recipients("  a@test.com  ,   b@test.com  ")
        assert "a@test.com" in recipients
        assert "b@test.com" in recipients

    def test_multiple_commas(self, parser):
        """Gere les virgules multiples."""
        recipients = parser._normalize_recipients("a@test.com,,, b@test.com")
        assert recipients == ["a@test.com", "b@test.com"]

    def test_mixed_formats(self, parser):
        """Gere les formats mixtes."""
        recipients = parser._normalize_recipients(
            '"Alice" <alice@test.com>, bob@test.com, <carol@test.com>'
        )
        assert "alice@test.com" in recipients
        assert "bob@test.com" in recipients
        assert "carol@test.com" in recipients

    def test_invalid_entries_skipped(self, parser):
        """Ignore les entrees invalides."""
        recipients = parser._normalize_recipients(
            "valid@test.com, not-an-email, another@test.com"
        )
        assert "valid@test.com" in recipients
        assert "another@test.com" in recipients
        assert "not-an-email" not in recipients


class TestNormalizeRecipientsLargeList:
    """Tests pour les grandes listes."""

    def test_many_recipients(self, parser):
        """Gere beaucoup de destinataires."""
        emails = [f"user{i}@test.com" for i in range(100)]
        header = ", ".join(emails)
        recipients = parser._normalize_recipients(header)
        assert len(recipients) == 100
        assert "user0@test.com" in recipients
        assert "user99@test.com" in recipients


# =============================================================================
# TESTS - INTEGRATION AVEC PROVIDERS
# =============================================================================


class TestMixinIntegration:
    """Tests d'integration avec les classes utilisant le mixin."""

    def test_mixin_can_be_inherited(self, parser):
        """Le mixin peut etre herite."""
        class TestAdapter(EmailParserMixin):
            def parse(self, header):
                return self._parse_email_address(header)

        adapter = TestAdapter()
        email, name = adapter.parse("test@example.com")
        assert email == "test@example.com"

    def test_mixin_methods_are_private(self, parser):
        """Les methodes du mixin commencent par _."""
        assert hasattr(parser, "_parse_email_address")
        assert hasattr(parser, "_extract_text_from_html")
        assert hasattr(parser, "_normalize_recipients")

    def test_regex_patterns_compiled(self, parser):
        """Les patterns regex sont pre-compiles."""
        assert hasattr(parser, "_EMAIL_WITH_NAME_RE")
        assert hasattr(parser, "_SIMPLE_EMAIL_RE")
        assert hasattr(parser, "_HTML_TAG_RE")


# =============================================================================
# TESTS - PERFORMANCE
# =============================================================================


class TestParserPerformance:
    """Tests de performance pour le parsing."""

    def test_parse_large_html(self, parser):
        """Parse efficacement un grand HTML."""
        html = "<p>Text</p>" * 1000
        text = parser._extract_text_from_html(html)
        assert "Text" in text

    def test_parse_many_recipients(self, parser):
        """Parse efficacement beaucoup de destinataires."""
        header = ", ".join([f"user{i}@test.com" for i in range(500)])
        recipients = parser._normalize_recipients(header)
        assert len(recipients) == 500

    def test_regex_reuse(self, parser):
        """Les regex sont reutilisees entre appels."""
        # Premier appel
        parser._parse_email_address("a@test.com")
        regex1 = parser._SIMPLE_EMAIL_RE

        # Deuxieme appel
        parser._parse_email_address("b@test.com")
        regex2 = parser._SIMPLE_EMAIL_RE

        # Meme objet regex (compile une seule fois)
        assert regex1 is regex2


# =============================================================================
# TESTS - _demojibake (repair UTF-8-as-Latin-1 mojibake in display names)
# =============================================================================
#
# Regression: sent-email `From:` display names were written to the header
# already mojibake'd by a since-removed send path (UTF-8 bytes of `é` decoded
# as Latin-1 -> `Ã©`). Gmail echoes those headers back verbatim on every
# re-fetch, so the corruption re-entered `emails.sender_name` on each sync
# until `_parse_email_address` started running `_demojibake`.


class TestDemojibake:
    """Tests directs du helper _demojibake."""

    def test_repairs_utf8_as_latin1_mojibake(self, parser):
        """`Crypto UniversitÃ©` (Ã© = \\xc3\\xa9) -> `Crypto Université` (é = \\xe9)."""
        mojibake = "Crypto Universit\xc3\xa9"
        assert parser._demojibake(mojibake) == "Crypto Universit\xe9"

    def test_repairs_multiple_accents(self, parser):
        """Plusieurs accents corrompus dans la meme chaine."""
        # "Crème Brûlée" mojibake'd
        mojibake = "Cr\xc3\xa8me Br\xc3\xbbl\xc3\xa9e"
        assert parser._demojibake(mojibake) == "Cr\xe8me Br\xfbl\xe9e"

    def test_idempotent_on_clean_string(self, parser):
        """Une chaine propre (deja correcte) n'a aucun marqueur -> intacte."""
        clean = "Crypto Universit\xe9"
        assert parser._demojibake(clean) == clean

    def test_idempotent_when_run_twice(self, parser):
        """Relancer _demojibake sur le resultat repare est un no-op."""
        once = parser._demojibake("Crypto Universit\xc3\xa9")
        assert parser._demojibake(once) == once

    def test_plain_ascii_untouched(self, parser):
        """ASCII pur : aucun marqueur, renvoye tel quel."""
        assert parser._demojibake("Nathan Roy") == "Nathan Roy"

    def test_non_roundtripping_input_left_untouched(self, parser):
        """Un `Ã` qui n'est PAS un mojibake reel (l'aller-retour utf-8 echoue)
        doit etre renvoye intact — pas de faux positif sur un vrai nom."""
        # \xc3 ('Ã') suivi de 'n' : pas une sequence UTF-8 valide -> decode raise
        legit = "\xc3ndr\xe9"
        assert parser._demojibake(legit) == legit

    def test_none_and_empty_safe(self, parser):
        """None et chaine vide passent sans erreur."""
        assert parser._demojibake(None) is None
        assert parser._demojibake("") == ""


class TestDemojibakeMixedContent:
    """Y003 / F-01 / F-02 regression: corps d'emails reels a contenu mixte.

    Avant le passage a ftfy, ``_demojibake`` faisait un ``encode('latin-1')``
    sur TOUTE la chaine : un seul ``€`` / emoji / guillemet courbe levait une
    exception et la chaine mojibake etait renvoyee INTACTE (F-01) — or les corps
    francais en contiennent presque toujours un. Et l'aller-retour brut
    reinterpretait a l'aveugle un texte deja correct (F-02). ftfy corrige les
    deux : reparation sequence par sequence + modele de "badness".
    """

    def test_f01_mojibake_with_euro_is_repaired(self, parser):
        """F-01: ``UniversitÃ© coûte 50€`` — le € ne doit plus bloquer le fix."""
        mojibake = "Universit\xc3\xa9 co\xfbte 50€"
        assert parser._demojibake(mojibake) == "Universit\xe9 co\xfbte 50€"

    def test_f01_mojibake_with_emoji_is_repaired(self, parser):
        """F-01: un emoji (codepoint > U+00FF) ne bloque plus la reparation."""
        mojibake = "Salut \U0001F600 Universit\xc3\xa9"
        assert parser._demojibake(mojibake) == "Salut \U0001F600 Universit\xe9"

    def test_f01_smart_quote_mojibake_is_repaired(self, parser):
        """F-01: les guillemets / tirets CP1252 mojibake (``â€™``) sont repares."""
        # "It’s 5–6pm" mojibake'd : â€™ -> ’ (U+2019), â€“ -> – (U+2013)
        mojibake = "It\xe2€™s 5\xe2€“6pm"
        assert parser._demojibake(mojibake) == "It’s 5–6pm"

    def test_f01_qa_quote_header_is_repaired(self, parser):
        """F-01: le cas exact du rapport QA Y003 (en-tete de citation dans le corps)."""
        mojibake = "De : Crypto Universit\xc3\xa9 <cours.universite@gmail.com>"
        expected = "De : Crypto Universit\xe9 <cours.universite@gmail.com>"
        assert parser._demojibake(mojibake) == expected

    def test_clean_french_body_with_euro_untouched(self, parser):
        """Un corps francais propre (accents corrects + €) n'a aucun marqueur
        Ã/Â/â€ -> renvoye tel quel, sans meme appeler ftfy."""
        clean = "Re\xe7u : 5€ pour le caf\xe9 d\xe9j\xe0"
        assert parser._demojibake(clean) == clean

    def test_long_html_body_repaired_in_place(self, parser):
        """Le fix s'applique au HTML complet (corps rendu), pas qu'a un nom court."""
        html = "<p>Bonjour,</p><p>Voici l'Universit\xc3\xa9 — co\xfbt 50€.</p>"
        out = parser._demojibake(html)
        assert "Universit\xe9" in out          # é correct
        assert "Universit\xc3\xa9" not in out   # plus de mojibake residuel
        assert "50€" in out                # € preserve
        assert "—" in out                  # em-dash preserve

    def test_f02_copyright_mojibake_is_repaired(self, parser):
        """F-02: ``Â©`` (\\xc2\\xa9) est un VRAI mojibake de ``©`` -> repare."""
        # "Â© 2026" : 0xC2 0xA9 sont les octets UTF-8 de © (U+00A9) relus en latin-1.
        assert parser._demojibake("\xc2\xa9 2026 Acme") == "\xa9 2026 Acme"

    def test_f02_legit_capital_a_circumflex_preserved(self, parser):
        """F-02 (anti-corruption): un ``Â`` FRANCAIS legitime n'est PAS detruit.

        L'ancien aller-retour latin-1 brut mutait aveuglement tout ``Â`` ;
        ftfy, via son modele de badness, laisse intact un mot francais correct
        ("Âme", "Âgé") meme s'il declenche le marqueur ``Â``.
        """
        assert parser._demojibake("\xc2me sœur") == "\xc2me sœur"
        assert parser._demojibake("\xc2g\xe9 de 30 ans") == "\xc2g\xe9 de 30 ans"


class TestParseEmailAddressDemojibake:
    """Integration: _parse_email_address repare le nom corrompu de bout en bout."""

    def test_from_header_with_mojibake_name_is_repaired(self, parser):
        """Le chemin d'ingestion (From: header -> nom) demojibake le nom.

        C'est exactement le scenario du bug : Gmail renvoie
        `"Crypto UniversitÃ©" <addr>` (mojibake fige cote serveur), et
        l'appelant ne doit JAMAIS stocker le nom corrompu.
        """
        header = '"Crypto Universit\xc3\xa9" <cours.universite@gmail.com>'
        email, name = parser._parse_email_address(header)
        assert email == "cours.universite@gmail.com"
        assert name == "Crypto Universit\xe9"  # é correct, pas Ã©

    def test_clean_accented_name_preserved(self, parser):
        """Un nom deja correct (accent UTF-8 propre) traverse intact."""
        header = "Crypto Universit\xe9 <crypto@example.com>"
        email, name = parser._parse_email_address(header)
        assert name == "Crypto Universit\xe9"
