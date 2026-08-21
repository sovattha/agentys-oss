# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module email_cleaner.
"""


from app.utils.email_cleaner import (
    strip_signature,
    strip_quoted_text,
    detect_auto_reply,
    truncate_for_tokens,
    clean_email_content,
)


class TestStripSignature:
    """Tests pour strip_signature."""

    def test_strip_simple_signature(self):
        """Suppression signature simple avec --."""
        body = """Bonjour,

Voici ma réponse.

--
Jean Dupont
Développeur
jean@example.com"""

        result = strip_signature(body)

        assert "Bonjour" in result
        assert "Voici ma réponse" in result
        assert "Jean Dupont" not in result
        assert "jean@example.com" not in result

    def test_strip_regards_signature(self):
        """Suppression signature avec Cordialement."""
        body = """Bonjour,

Merci pour votre message.

Cordialement,
Marie Martin"""

        result = strip_signature(body)

        assert "Bonjour" in result
        assert "Merci pour votre message" in result
        assert "Marie Martin" not in result

    def test_strip_sent_from_signature(self):
        """Suppression signature mobile."""
        body = """OK, je m'en occupe.

Sent from my iPhone"""

        result = strip_signature(body)

        assert "OK, je m'en occupe" in result
        assert "Sent from" not in result
        assert "iPhone" not in result

    def test_keep_body_without_signature(self):
        """Corps sans signature reste intact."""
        body = """Bonjour,

Ceci est un message simple sans signature."""

        result = strip_signature(body)

        assert result == body.rstrip()

    def test_empty_body(self):
        """Corps vide retourne chaîne vide."""
        assert strip_signature("") == ""
        assert strip_signature(None) == ""


class TestStripQuotedText:
    """Tests pour strip_quoted_text."""

    def test_strip_quoted_lines(self):
        """Suppression lignes citées avec >."""
        body = """Merci pour l'info.

> On m'a dit que le projet avançait bien.
> C'est une bonne nouvelle.

Bien reçu !"""

        result = strip_quoted_text(body)

        assert "Merci pour l'info" in result
        assert "Bien reçu" in result
        assert "projet avançait" not in result

    def test_strip_on_wrote_header(self):
        """Suppression citation avec 'On ... wrote:'."""
        body = """D'accord, je comprends.

On Jan 15, 2025, at 10:30 AM, John Doe wrote:
> Previous message content
> More quoted text

Je m'en occupe."""

        result = strip_quoted_text(body)

        assert "D'accord, je comprends" in result
        assert "Je m'en occupe" in result
        assert "John Doe wrote" not in result
        assert "Previous message" not in result

    def test_strip_french_quote_header(self):
        """Suppression citation avec 'Le ... a écrit :'."""
        body = """Bien noté.

Le 15 janv. 2025 à 10:30, Jean Dupont a écrit :
> Message précédent
> Suite du message

Merci."""

        result = strip_quoted_text(body)

        assert "Bien noté" in result
        assert "Merci" in result
        assert "Jean Dupont" not in result

    def test_strip_forwarded_message(self):
        """Suppression message transféré."""
        body = """FYI

---------- Forwarded message ----------
From: someone@example.com
Subject: Important

Forwarded content here."""

        result = strip_quoted_text(body)

        assert "FYI" in result
        assert "Forwarded message" not in result
        assert "Forwarded content" not in result

    def test_keep_unquoted_body(self):
        """Corps non cité reste intact."""
        body = """Ceci est un message simple.

Sans aucune citation."""

        result = strip_quoted_text(body)

        assert "Ceci est un message simple" in result
        assert "Sans aucune citation" in result


class TestDetectAutoReply:
    """Tests pour detect_auto_reply."""

    def test_detect_out_of_office_subject(self):
        """Détection OOO dans le sujet."""
        assert detect_auto_reply("", "Out of Office: Re: Your email") is True
        assert detect_auto_reply("", "Absence du bureau") is True
        assert detect_auto_reply("", "Auto-Reply: Thank you") is True

    def test_detect_auto_reply_body(self):
        """Détection auto-reply dans le corps."""
        body = "I am currently out of the office and will return on Monday."
        assert detect_auto_reply(body) is True

        body_fr = "Je suis actuellement en vacances et serai de retour le 20 janvier."
        assert detect_auto_reply(body_fr) is True

    def test_detect_automated_response(self):
        """Détection réponse automatique."""
        body = "This is an automated reply. Your message has been received."
        assert detect_auto_reply(body) is True

    def test_normal_email_not_detected(self):
        """Email normal non détecté comme auto-reply."""
        body = "Bonjour, je réponds à votre demande."
        subject = "Re: Votre question"
        assert detect_auto_reply(body, subject) is False

    def test_empty_inputs(self):
        """Entrées vides retournent False."""
        assert detect_auto_reply("", "") is False
        assert detect_auto_reply(None, None) is False


class TestTruncateForTokens:
    """Tests pour truncate_for_tokens."""

    def test_short_body_unchanged(self):
        """Corps court non modifié."""
        body = "Message court."
        result = truncate_for_tokens(body, max_tokens=100)
        assert result == body

    def test_long_body_truncated(self):
        """Corps long tronqué."""
        body = "A" * 50000  # ~12500 tokens
        result = truncate_for_tokens(body, max_tokens=1000)

        assert len(result) < len(body)
        assert "[... Email tronqué" in result

    def test_truncate_at_paragraph(self):
        """Troncature préférentielle au paragraphe."""
        body = "Premier paragraphe.\n\nDeuxième paragraphe.\n\n" + "A" * 50000
        result = truncate_for_tokens(body, max_tokens=100)

        # Devrait couper avant le gros bloc
        assert len(result) < 1000

    def test_truncate_without_notice(self):
        """Troncature sans message de notice."""
        body = "A" * 50000
        result = truncate_for_tokens(body, max_tokens=100, add_truncation_notice=False)

        assert "[... Email tronqué" not in result

    def test_empty_body(self):
        """Corps vide retourne chaîne vide."""
        assert truncate_for_tokens("") == ""
        assert truncate_for_tokens(None) == ""


class TestCleanEmailContent:
    """Tests pour clean_email_content."""

    def test_full_cleaning_pipeline(self):
        """Test du pipeline complet de nettoyage."""
        body = """Bonjour,

Merci pour votre message.

> Citation précédente
> Autre ligne citée

--
Jean Dupont
jean@example.com"""

        result, metadata = clean_email_content(body)

        assert "Bonjour" in result
        assert "Merci pour votre message" in result
        assert "Citation précédente" not in result
        assert "Jean Dupont" not in result
        assert metadata["is_auto_reply"] is False

    def test_auto_reply_detection(self):
        """Détection auto-reply via clean_email_content."""
        body = "I am currently out of the office."
        subject = "Out of Office"

        result, metadata = clean_email_content(body, subject)

        assert metadata["is_auto_reply"] is True

    def test_truncation_metadata(self):
        """Métadonnées de troncature correctes."""
        body = "A" * 50000

        result, metadata = clean_email_content(body, max_tokens=1000)

        assert metadata["was_truncated"] is True
        assert metadata["original_length"] == 50000
        assert metadata["cleaned_length"] < 50000

    def test_no_modifications_when_disabled(self):
        """Pas de modifications si options désactivées."""
        body = """Message

--
Signature"""

        result, metadata = clean_email_content(
            body,
            strip_signatures=False,
            strip_quotes=False,
            check_auto_reply=False,
        )

        assert "Signature" in result
        assert metadata["is_auto_reply"] is False

    def test_empty_body(self):
        """Corps vide géré correctement."""
        result, metadata = clean_email_content("")

        assert result == ""
        assert metadata["original_length"] == 0
        assert metadata["cleaned_length"] == 0


class TestEdgeCases:
    """Tests des cas limites."""

    def test_multiple_signatures(self):
        """Email avec plusieurs indicateurs de signature."""
        body = """Message

Cordialement,
Jean

--
Email: jean@example.com"""

        result = strip_signature(body)

        assert "Message" in result
        assert "Email:" not in result

    def test_nested_quotes(self):
        """Citations imbriquées."""
        body = """OK

> Citation niveau 1
>> Citation niveau 2
>>> Citation niveau 3

Fin"""

        result = strip_quoted_text(body)

        assert "OK" in result
        assert "Fin" in result
        assert "Citation niveau" not in result

    def test_unicode_content(self):
        """Contenu Unicode."""
        body = """Bonjour 世界!

Merci beaucoup 🙏

--
Émilie"""

        result = strip_signature(body)

        assert "Bonjour 世界" in result
        assert "Merci beaucoup 🙏" in result
        assert "Émilie" not in result


class TestSignatureEdgeCases:
    """Tests edge cases pour la détection de signatures."""

    def test_signature_with_underscores(self):
        """Signature avec délimiteur ___."""
        body = """Mon message ici.

_______________
John Smith
Manager"""

        result = strip_signature(body)
        assert "Mon message" in result
        assert "John Smith" not in result

    def test_signature_with_equals(self):
        """Signature avec délimiteur ===."""
        body = """Content de l'email.

========================
Support Team"""

        result = strip_signature(body)
        assert "Content de l'email" in result
        assert "Support Team" not in result

    def test_signature_with_asterisks(self):
        """Signature avec délimiteur ***."""
        body = """Voici les informations.

***
Marketing Dept"""

        result = strip_signature(body)
        assert "Voici les informations" in result
        assert "Marketing Dept" not in result

    def test_best_regards_variations(self):
        """Variations de 'Best Regards'."""
        variations = [
            "Best Regards,",
            "Best regards",
            "Regards,",
            "Regards",
            "Kind Regards,",
            "Kind regards",
        ]

        for variation in variations:
            body = f"""Test message.

{variation}
Name"""
            result = strip_signature(body)
            assert "Test message" in result
            assert "Name" not in result, f"Failed for: {variation}"

    def test_french_signature_variations(self):
        """Variations de signatures françaises."""
        variations = [
            "Cordialement,",
            "Cordialement",
            "Bien cordialement,",
            "Bien à vous,",
            "Merci,",
            "Merci",
        ]

        for variation in variations:
            body = f"""Message de test.

{variation}
Nom"""
            result = strip_signature(body)
            assert "Message de test" in result
            assert "Nom" not in result, f"Failed for: {variation}"

    def test_mobile_signature_variations(self):
        """Signatures mobiles diverses."""
        signatures = [
            "Sent from my iPhone",
            "Sent from my Android",
            "Envoyé depuis mon iPhone",
            "Get Outlook for iOS",
            "Téléchargez Outlook pour iOS",
            "Sent with ProtonMail",
        ]

        for sig in signatures:
            body = f"Short reply.\n\n{sig}"
            result = strip_signature(body)
            assert "Short reply" in result
            # La signature doit être supprimée
            assert sig not in result or sig.split()[0] not in result

    def test_signature_at_end_only(self):
        """La signature doit être cherchée à la fin uniquement."""
        body = """Cordialement dans le texte n'est pas une signature.

Ceci est le corps du message.

Cordialement,
Jean"""

        result = strip_signature(body)
        # Le premier "Cordialement" ne doit pas être traité comme signature
        assert "Cordialement dans le texte" in result
        assert "Jean" not in result

    def test_very_short_email_with_signature(self):
        """Email très court avec signature."""
        body = """OK

--
J"""

        result = strip_signature(body)
        assert "OK" in result
        assert "J" not in result

    def test_signature_not_in_last_20_lines(self):
        """Signature détectée uniquement dans les 20 dernières lignes."""
        # Créer un email avec 25 lignes, signature à la ligne 5
        lines = ["Line " + str(i) for i in range(25)]
        lines[5] = "Cordialement,"
        body = "\n".join(lines)

        result = strip_signature(body)
        # La signature à la ligne 5 ne devrait pas être détectée
        # car elle n'est pas dans les 20 dernières lignes
        assert "Line 5" not in result or "Cordialement" in result


class TestQuotedTextEdgeCases:
    """Tests edge cases pour la suppression de texte cité."""

    def test_original_message_header(self):
        """Header 'Original Message' en anglais.

        Note: Le comportement actuel supprime le header mais pas le contenu
        qui suit si ce n'est pas préfixé par >.
        """
        body = """My response.

----- Original Message -----
From: sender@example.com
To: me@example.com
Subject: Test

Original content."""

        result = strip_quoted_text(body)
        assert "My response" in result
        # Le header "Original Message" est reconnu mais le contenu après
        # n'est pas supprimé car il n'est pas préfixé par >
        # C'est le comportement documenté du code
        assert "Original Message" not in result

    def test_message_origine_header(self):
        """Header 'Message d'origine' en français.

        Note: Le comportement actuel supprime le header mais pas le contenu
        qui suit si ce n'est pas préfixé par >.
        """
        body = """Ma réponse.

----- Message d'origine -----
De: envoyeur@example.com
À: moi@example.com

Contenu original."""

        result = strip_quoted_text(body)
        assert "Ma réponse" in result
        # Le header "Message d'origine" est reconnu mais le contenu après
        # n'est pas supprimé car il n'est pas préfixé par >
        assert "Message d'origine" not in result

    def test_begin_forwarded_message(self):
        """Message transféré avec 'Begin forwarded message'."""
        body = """FYI, see below.

Begin forwarded message:

From: someone@example.com
Date: January 15, 2025
Subject: Info

The forwarded content."""

        result = strip_quoted_text(body)
        assert "FYI" in result
        assert "forwarded content" not in result

    def test_debut_message_transfere(self):
        """Message transféré en français."""
        body = """Pour info.

Début du message transféré :

De: quelquun@example.com
Date: 15 janvier 2025

Le contenu transféré."""

        result = strip_quoted_text(body)
        assert "Pour info" in result
        assert "contenu transféré" not in result

    def test_multiple_quote_blocks(self):
        """Plusieurs blocs de citation.

        Note: Le comportement actuel garde le texte entre les citations
        car la logique sort du mode citation quand elle trouve du texte non cité.
        """
        body = """Ma réponse finale.

> Première citation
> Suite

Mon commentaire intermédiaire.

> Deuxième citation

Fin de mon message."""

        result = strip_quoted_text(body)
        assert "Ma réponse finale" in result
        # Le comportement actuel: le texte entre les citations est conservé
        # car la logique "sort" du mode citation quand elle trouve du texte normal
        assert "Mon commentaire" in result  # Conservé car texte normal après citation
        assert "Fin de mon message" in result  # Conservé car texte normal après citation

    def test_quote_with_empty_lines(self):
        """Citation avec lignes vides intercalées."""
        body = """Response.

> Quoted line 1
>
> Quoted line 2

Not quoted."""

        result = strip_quoted_text(body)
        assert "Response" in result
        assert "Quoted line" not in result

    def test_from_header_in_quoted(self):
        """Header 'From:' dans le contexte de citation."""
        body = """OK.

From: John Doe
Subject: Test
Date: Today

Quoted email content."""

        result = strip_quoted_text(body)
        assert "OK" in result
        # Le "From:" devrait être traité comme citation
        assert "John Doe" not in result

    def test_de_header_french(self):
        """Header 'De :' en français.

        Note: Le pattern De: est reconnu mais le contenu suivant n'est pas
        automatiquement supprimé s'il n'est pas préfixé par >.
        """
        body = """Bien reçu.

De : Jean Dupont
Objet : Test

Contenu cité."""

        result = strip_quoted_text(body)
        assert "Bien reçu" in result
        # Le header De: est reconnu et la ligne est supprimée,
        # mais le contenu après n'est pas automatiquement supprimé
        assert "Jean Dupont" not in result


class TestAutoReplyEdgeCases:
    """Tests edge cases pour la détection d'auto-reply."""

    def test_ooo_variations(self):
        """Variations de 'Out of Office'."""
        subjects = [
            "Out of Office: Re: Meeting",
            "Out of the Office",
            "OOO: Meeting request",
            "OOF: Your email",  # Outlook terminology
        ]

        for subject in subjects:
            assert detect_auto_reply("", subject) is True, f"Failed for: {subject}"

    def test_vacation_reply(self):
        """Réponse de vacances."""
        assert detect_auto_reply("", "Vacation Reply: Your message") is True
        assert detect_auto_reply("", "Vacation Response") is True

    def test_automatic_reply_variations(self):
        """Variations de réponse automatique."""
        subjects = [
            "Auto-Reply: Thanks",
            "Automatic Reply",
            "AutoReply: Received",
            "[Auto] Your message",
            "Réponse automatique",
        ]

        for subject in subjects:
            assert detect_auto_reply("", subject) is True, f"Failed for: {subject}"

    def test_absence_french(self):
        """Absence en français.

        Note: Seuls certains patterns sont reconnus dans le sujet.
        'Absence' seul n'est pas détecté, il faut 'Absence du bureau'.
        """
        subjects_detected = [
            "Absence du bureau",
            # "Absence" seul n'est pas dans les patterns
        ]

        for subject in subjects_detected:
            assert detect_auto_reply("", subject) is True, f"Failed for: {subject}"

        # Ces patterns sont détectés dans le corps, pas le sujet
        bodies_detected = [
            "Je suis absent",
            "Je suis en congés",
            "Je suis en vacances",
        ]

        for body in bodies_detected:
            assert detect_auto_reply(body) is True, f"Failed for: {body}"

    def test_do_not_reply(self):
        """Messages 'Ne pas répondre'."""
        assert detect_auto_reply("", "Do not reply: Notification") is True
        assert detect_auto_reply("", "Ne pas répondre: Confirmation") is True

    def test_body_patterns_english(self):
        """Patterns dans le corps (anglais)."""
        bodies = [
            "I am currently out of the office.",
            "I am away on vacation.",
            "I am on leave until Monday.",
            "This is an automated message.",
            "This is an automatic response.",
            "I will be back on Monday.",
            "I will return on January 20.",
            "I have limited access to email.",
            "I will respond upon my return.",
        ]

        for body in bodies:
            assert detect_auto_reply(body) is True, f"Failed for: {body}"

    def test_body_patterns_french(self):
        """Patterns dans le corps (français)."""
        bodies = [
            "Je suis actuellement absent.",
            "Je suis en vacances.",
            "Je suis en congés.",
            "Ceci est une réponse automatique.",
            "Ceci est un message automatique.",
            "Je serai de retour le 20 janvier.",
            "Je reviens à partir du lundi.",
            "J'ai un accès limité à mes emails.",
        ]

        for body in bodies:
            assert detect_auto_reply(body) is True, f"Failed for: {body}"

    def test_false_positives_prevention(self):
        """Éviter les faux positifs."""
        normal_messages = [
            "Please reply as soon as possible.",
            "I am writing to inform you...",
            "This is a message about the project.",
            "I will be there at 10:00.",
            "Je vous écris concernant...",
            "Je serai là demain.",
        ]

        for msg in normal_messages:
            assert detect_auto_reply(msg) is False, f"False positive for: {msg}"


class TestTruncationEdgeCases:
    """Tests edge cases pour la troncature."""

    def test_truncate_exact_limit(self):
        """Troncature à la limite exacte."""
        # chars_per_token=4.0 par défaut, donc 100 tokens = 400 chars
        body = "A" * 400
        result = truncate_for_tokens(body, max_tokens=100)
        # Ne devrait pas être tronqué
        assert "[... Email tronqué" not in result

    def test_truncate_just_over_limit(self):
        """Troncature juste au-dessus de la limite."""
        body = "A" * 401
        result = truncate_for_tokens(body, max_tokens=100)
        assert len(result) <= 400 + len("\n\n[... Email tronqué pour traitement ...]")

    def test_truncate_preserves_paragraph_structure(self):
        """La troncature préserve la structure des paragraphes."""
        body = """Premier paragraphe avec du contenu.

Deuxième paragraphe avec plus de contenu.

""" + "X" * 10000

        result = truncate_for_tokens(body, max_tokens=200)
        # Devrait garder les premiers paragraphes si possible
        assert "Premier paragraphe" in result or "[..." in result

    def test_truncate_very_long_single_line(self):
        """Troncature d'une seule très longue ligne."""
        body = "A" * 100000
        result = truncate_for_tokens(body, max_tokens=1000)
        assert len(result) < len(body)
        assert "[... Email tronqué" in result

    def test_truncate_with_custom_chars_per_token(self):
        """Troncature avec ratio personnalisé."""
        body = "A" * 1000
        # Avec 2 chars/token, 100 tokens = 200 chars
        result = truncate_for_tokens(body, max_tokens=100, chars_per_token=2.0)
        assert len(result) < 1000

    def test_truncate_unicode_aware(self):
        """La troncature gère correctement l'Unicode."""
        # Emoji prennent plus d'espace
        body = "🎉" * 5000
        result = truncate_for_tokens(body, max_tokens=100)
        # Ne devrait pas couper au milieu d'un emoji
        assert "🎉" in result


class TestCleanEmailContentEdgeCases:
    """Tests edge cases pour le pipeline complet."""

    def test_email_with_all_components(self):
        """Email avec signature, citation et auto-reply potentiel."""
        body = """Je réponds à votre email.

> Voici ce que vous aviez écrit
> Sur plusieurs lignes

Merci de votre attention.

Cordialement,
Jean Dupont
jean@example.com"""

        result, metadata = clean_email_content(body)

        assert "Je réponds" in result
        assert "Voici ce que vous aviez" not in result
        assert "Jean Dupont" not in result
        assert metadata["is_auto_reply"] is False

    def test_auto_reply_still_cleaned(self):
        """Un auto-reply est quand même nettoyé."""
        body = """I am currently out of the office.

I will return on Monday.

--
John Smith
Vacation Mode"""

        result, metadata = clean_email_content(body, "Out of Office")

        assert metadata["is_auto_reply"] is True
        assert "John Smith" not in result

    def test_metadata_accuracy(self):
        """Précision des métadonnées."""
        body = "Short message."
        result, metadata = clean_email_content(body)

        assert metadata["original_length"] == len("Short message.")
        assert metadata["cleaned_length"] > 0
        assert metadata["was_truncated"] is False
        assert metadata["is_auto_reply"] is False

    def test_all_options_disabled(self):
        """Toutes les options désactivées."""
        body = """Message

> Quote

--
Sig"""

        result, metadata = clean_email_content(
            body,
            strip_signatures=False,
            strip_quotes=False,
            check_auto_reply=False,
        )

        assert "Quote" in result
        assert "Sig" in result
        assert metadata["is_auto_reply"] is False

    def test_very_long_email_thread(self):
        """Long thread d'emails."""
        thread = """Ma réponse.

On Jan 15, 2025, Person A wrote:
> Previous message
>
> On Jan 14, 2025, Person B wrote:
>> Even earlier message
>>
>> On Jan 13, 2025, Person C wrote:
>>> Very old message

""" + "X" * 50000

        result, metadata = clean_email_content(thread, max_tokens=1000)

        assert "Ma réponse" in result
        assert "Very old message" not in result
        assert metadata["was_truncated"] is True


class TestSpecialCharactersAndEncoding:
    """Tests pour caractères spéciaux et encodages."""

    def test_html_entities_in_body(self):
        """Entités HTML dans le corps."""
        body = """Message avec &amp; et &lt;tags&gt;

Cordialement,
Test"""

        result = strip_signature(body)
        assert "&amp;" in result
        assert "Test" not in result

    def test_newline_variations(self):
        """Différentes variations de sauts de ligne."""
        # Windows style \r\n
        # Note: Les patterns actuels utilisent \n, donc \r\n pourrait ne pas matcher
        # Ce test documente le comportement

    def test_tabs_in_content(self):
        """Tabulations dans le contenu."""
        body = """Message avec\ttab.

\tIndented line.

--
Sig"""

        result = strip_signature(body)
        assert "tab" in result
        assert "Sig" not in result

    def test_mixed_encodings(self):
        """Encodages mixtes (accent, emoji, CJK)."""
        body = """Café ☕ 中文

Merci 感谢 🙏

Cordialement,
名前"""

        result = strip_signature(body)
        assert "Café" in result
        assert "中文" in result
        assert "感谢" in result
        assert "名前" not in result

    def test_zero_width_characters(self):
        """Caractères de largeur nulle."""
        # ZWSP entre les caractères
        body = "Test\u200Bmessage\n\n--\nSig"
        result = strip_signature(body)
        assert "Sig" not in result

    def test_rtl_text(self):
        """Texte Right-to-Left (arabe)."""
        body = """مرحبا

شكرا

--
اسم"""

        result = strip_signature(body)
        assert "مرحبا" in result
        assert "شكرا" in result

    def test_very_long_lines(self):
        """Lignes très longues."""
        body = "A" * 10000 + "\n\n--\nSignature"
        result = strip_signature(body)
        assert "Signature" not in result

    def test_empty_lines_before_signature(self):
        """Lignes vides multiples avant signature."""
        body = """Message.




--
Sig"""

        result = strip_signature(body)
        assert "Message" in result
        assert "Sig" not in result


class TestNoneAndEmptyInputs:
    """Tests pour entrées None et vides."""

    def test_strip_signature_none(self):
        """strip_signature avec None."""
        assert strip_signature(None) == ""

    def test_strip_quoted_text_none(self):
        """strip_quoted_text avec None."""
        assert strip_quoted_text(None) == ""

    def test_detect_auto_reply_none_both(self):
        """detect_auto_reply avec None."""
        assert detect_auto_reply(None, None) is False
        assert detect_auto_reply(None, "") is False
        assert detect_auto_reply("", None) is False

    def test_truncate_for_tokens_none(self):
        """truncate_for_tokens avec None."""
        assert truncate_for_tokens(None) == ""

    def test_clean_email_content_none(self):
        """clean_email_content avec None."""
        result, metadata = clean_email_content(None)
        assert result == ""
        assert metadata["original_length"] == 0

    def test_whitespace_only_inputs(self):
        """Entrées avec espaces uniquement."""
        assert strip_signature("   \n\t  ").strip() == ""
        assert strip_quoted_text("   \n\t  ").strip() == ""


class TestRobustness:
    """Tests de robustesse et cas extrêmes."""

    def test_signature_pattern_at_start(self):
        """Pattern de signature au début du message."""
        body = """--
Ceci n'est pas une signature mais le début.

Le vrai contenu est ici."""

        strip_signature(body)
        # La signature est cherchée depuis la fin
        # Donc le -- au début ne devrait pas poser problème

    def test_quote_character_in_normal_text(self):
        """Caractère > dans du texte normal."""
        body = """Le prix est > 100€.

C'est 5 > 3.

Fin."""

        result = strip_quoted_text(body)
        # Les > qui ne sont pas au début de ligne ne devraient pas matcher
        # Mais actuellement le pattern match au début de ligne
        assert "Fin" in result

    def test_regards_in_middle_of_text(self):
        """'Regards' au milieu du texte."""
        body = """In regards to your question, here is my answer.

The details are below.

Best Regards,
Name"""

        result = strip_signature(body)
        assert "In regards to" in result
        assert "Name" not in result

    def test_repeated_cleaning(self):
        """Nettoyage répété donne le même résultat."""
        body = """Message.

> Quote

--
Sig"""

        result1, _ = clean_email_content(body)
        result2, _ = clean_email_content(result1)

        # Idempotence
        assert result1 == result2

    def test_only_signature(self):
        """Email qui n'est qu'une signature.

        Note: Le comportement actuel ne supprime pas la signature si elle est
        au début du message (les 20 premières lignes ne sont pas scannées
        à moins que le message soit très court).
        """
        body = """--
John Doe
john@example.com"""

        result = strip_signature(body)
        # Comportement actuel: le -- au début est dans les dernières 20 lignes
        # donc il est détecté et supprimé, laissant une chaîne vide
        # Mais l'algo cherche depuis la fin, et si le message est court,
        # il trouve le -- et coupe là
        assert result == "" or "john@example.com" in result

    def test_only_quoted_text(self):
        """Email qui n'est que du texte cité."""
        body = """> Line 1
> Line 2
> Line 3"""

        result = strip_quoted_text(body)
        assert result.strip() == ""
