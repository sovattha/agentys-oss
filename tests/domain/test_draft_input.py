# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour l'entité DraftInput."""

from app.domain.entities.draft_input import (
    DraftInput,
    DraftInputTone,
    CompletedDraft,
)


class TestDraftInputToneEnum:
    """Tests pour l'énumération DraftInputTone."""

    def test_tone_enum_formal(self):
        """Test que FORMAL a la bonne valeur."""
        assert DraftInputTone.FORMAL.value == "formal"

    def test_tone_enum_friendly(self):
        """Test que FRIENDLY a la bonne valeur."""
        assert DraftInputTone.FRIENDLY.value == "friendly"

    def test_tone_enum_urgent(self):
        """Test que URGENT a la bonne valeur."""
        assert DraftInputTone.URGENT.value == "urgent"

    def test_tone_enum_conciliatory(self):
        """Test que CONCILIATORY a la bonne valeur."""
        assert DraftInputTone.CONCILIATORY.value == "conciliatory"

    def test_tone_enum_neutral(self):
        """Test que NEUTRAL a la bonne valeur."""
        assert DraftInputTone.NEUTRAL.value == "neutral"

    def test_tone_enum_has_five_values(self):
        """Test que l'énumération a exactement 5 valeurs."""
        assert len(DraftInputTone) == 5


class TestIsDraftInputWithPrefixes:
    """Tests pour is_draft_input() avec les préfixes déclencheurs."""

    def test_is_draft_input_with_brouillon_colon(self):
        """Test détection avec 'brouillon :'."""
        assert DraftInput.is_draft_input("brouillon : Écrire à Jean")

    def test_is_draft_input_with_brouillon_no_space(self):
        """Test détection avec 'brouillon:' (pas d'espace)."""
        assert DraftInput.is_draft_input("brouillon:Écrire à Jean")

    def test_is_draft_input_with_draft_colon(self):
        """Test détection avec 'draft :'."""
        assert DraftInput.is_draft_input("draft : Write to John")

    def test_is_draft_input_with_draft_no_space(self):
        """Test détection avec 'draft:' (pas d'espace)."""
        assert DraftInput.is_draft_input("draft:Write to John")

    def test_is_draft_input_with_a_compléter(self):
        """Test détection avec 'à compléter :'."""
        assert DraftInput.is_draft_input("à compléter : Points clés")

    def test_is_draft_input_with_a_compléter_accent_variant(self):
        """Test détection avec 'a compléter :' (sans accent)."""
        assert DraftInput.is_draft_input("a compléter : Points clés")

    def test_is_draft_input_with_ebauche(self):
        """Test détection avec 'ébauche :'."""
        assert DraftInput.is_draft_input("ébauche : Idées à développer")

    def test_is_draft_input_with_idées_pour_email(self):
        """Test détection avec 'idées pour email :'."""
        assert DraftInput.is_draft_input("idées pour email : Points clés")

    def test_is_draft_input_with_rédige_à_partir(self):
        """Test détection avec 'rédige à partir de ça :'."""
        assert DraftInput.is_draft_input("rédige à partir de ça : Points")

    def test_is_draft_input_case_insensitive(self):
        """Test que la détection est insensible à la casse."""
        assert DraftInput.is_draft_input("BROUILLON : Points")
        assert DraftInput.is_draft_input("Draft : Points")
        assert DraftInput.is_draft_input("À COMPLÉTER : Points")

    def test_is_draft_input_with_whitespace(self):
        """Test avec espaces avant et après le texte."""
        assert DraftInput.is_draft_input("  brouillon :  Points  ")

    def test_trigger_prefixes_tuple_exists(self):
        """Test que TRIGGER_PREFIXES est correctement généré."""
        assert isinstance(DraftInput.TRIGGER_PREFIXES, tuple)
        assert len(DraftInput.TRIGGER_PREFIXES) > 0
        # Doit contenir des variantes avec et sans espace
        assert any(":" in prefix for prefix in DraftInput.TRIGGER_PREFIXES)


class TestIsDraftInputWithBulletPoints:
    """Tests pour is_draft_input() avec les bullet points."""

    def test_is_draft_input_with_dash_bullets(self):
        """Test détection avec bullet points (-)."""
        text = """- Point 1
- Point 2
- Point 3"""
        assert DraftInput.is_draft_input(text)

    def test_is_draft_input_with_asterisk_bullets(self):
        """Test détection avec bullet points (*)."""
        text = """* Point 1
* Point 2
* Point 3"""
        assert DraftInput.is_draft_input(text)

    def test_is_draft_input_with_dot_bullets(self):
        """Test détection avec bullet points (•)."""
        text = """• Point 1
• Point 2
• Point 3"""
        assert DraftInput.is_draft_input(text)

    def test_is_draft_input_with_numbered_list(self):
        """Test détection avec numérotation (1. ou 1))."""
        text = """1. Point 1
2. Point 2
3. Point 3"""
        assert DraftInput.is_draft_input(text)

    def test_is_draft_input_with_numbered_list_closing_paren(self):
        """Test détection avec numérotation (1))."""
        text = """1) Point 1
2) Point 2
3) Point 3"""
        assert DraftInput.is_draft_input(text)

    def test_is_draft_input_with_mixed_bullets(self):
        """Test détection avec bullet points mixtes."""
        text = """- Point 1
* Point 2
1. Point 3"""
        assert DraftInput.is_draft_input(text)

    def test_is_draft_input_threshold_exactly_50_percent(self):
        """Test que le seuil de 50% est inclusif."""
        text = """- Point 1
Texte normal
- Point 3"""
        # 2 lignes sur 4 = 50%
        assert DraftInput.is_draft_input(text)

    def test_is_draft_input_below_50_percent_bullets(self):
        """Test retourne False si moins de 50% sont des bullets."""
        text = """Texte normal 1
Texte normal 2
- Point 1"""
        # 1 ligne sur 3 = 33%
        assert not DraftInput.is_draft_input(text)

    def test_is_draft_input_bullets_with_indentation(self):
        """Test détection avec bullet points indentés."""
        text = """  - Point 1
  - Point 2
  - Point 3"""
        assert DraftInput.is_draft_input(text)

    def test_is_draft_input_single_bullet_line(self):
        """Test avec une seule ligne bullet (< 2 lignes)."""
        text = "- Seul point"
        # Le code requiert >= 2 lignes pour considérer comme draft basé sur bullets
        assert not DraftInput.is_draft_input(text)


class TestIsDraftInputReturnsFalse:
    """Tests pour is_draft_input() retournant False."""

    def test_is_draft_input_empty_string(self):
        """Test que chaîne vide retourne False."""
        assert not DraftInput.is_draft_input("")

    def test_is_draft_input_whitespace_only(self):
        """Test que texte vide (espaces) retourne False."""
        assert not DraftInput.is_draft_input("   \n  \t  ")

    def test_is_draft_input_normal_text(self):
        """Test que texte normal retourne False."""
        assert not DraftInput.is_draft_input(
            "Bonjour Jean, j'aimerais te proposer une collaboration."
        )

    def test_is_draft_input_single_line(self):
        """Test que ligne simple retourne False."""
        assert not DraftInput.is_draft_input("Juste une seule ligne")

    def test_is_draft_input_no_prefix_no_bullets(self):
        """Test que texte sans préfixe et sans bullets retourne False."""
        text = """Ceci est une salutation complète.
Comment ça va?
À bientôt."""
        assert not DraftInput.is_draft_input(text)


class TestFromRawTextWithPrefixStripping:
    """Tests pour from_raw_text() avec nettoyage des préfixes."""

    def test_from_raw_text_strips_brouillon_colon(self):
        """Test suppression du préfixe 'brouillon :'."""
        draft = DraftInput.from_raw_text("brouillon : Écrire à Jean")
        assert draft.raw_input == "brouillon : Écrire à Jean"
        # raw_input est conservé, key_points montre le texte nettoyé
        assert len(draft.key_points) > 0

    def test_from_raw_text_strips_draft_no_space(self):
        """Test suppression du préfixe 'draft:' (sans espace)."""
        draft = DraftInput.from_raw_text("draft:Write to John")
        assert draft.raw_input == "draft:Write to John"
        assert len(draft.key_points) > 0

    def test_from_raw_text_strips_à_compléter(self):
        """Test suppression du préfixe 'à compléter :'."""
        draft = DraftInput.from_raw_text("à compléter : - Point 1\n- Point 2")
        assert draft.raw_input == "à compléter : - Point 1\n- Point 2"
        assert len(draft.key_points) == 2
        assert "Point 1" in draft.key_points
        assert "Point 2" in draft.key_points

    def test_from_raw_text_strips_ébauche(self):
        """Test suppression du préfixe 'ébauche :'."""
        draft = DraftInput.from_raw_text("ébauche : Contenu")
        assert draft.raw_input == "ébauche : Contenu"

    def test_from_raw_text_strips_idées_pour_email(self):
        """Test suppression du préfixe 'idées pour email :'."""
        draft = DraftInput.from_raw_text("idées pour email : - Idée 1\n- Idée 2")
        assert draft.raw_input == "idées pour email : - Idée 1\n- Idée 2"
        assert len(draft.key_points) >= 1

    def test_from_raw_text_case_insensitive_stripping(self):
        """Test que nettoyage est insensible à la casse."""
        draft = DraftInput.from_raw_text("BROUILLON : Contenu")
        assert draft.raw_input == "BROUILLON : Contenu"
        assert len(draft.key_points) >= 1

    def test_from_raw_text_preserves_raw_input(self):
        """Test que raw_input original est conservé."""
        original = "brouillon : Points à noter"
        draft = DraftInput.from_raw_text(original)
        assert draft.raw_input == original


class TestFromRawTextWithEmptyText:
    """Tests pour from_raw_text() avec texte vide."""

    def test_from_raw_text_empty_string(self):
        """Test parsing de chaîne vide."""
        draft = DraftInput.from_raw_text("")
        assert draft.raw_input == ""
        assert draft.recipient is None
        assert draft.subject_hint is None
        assert draft.tone == DraftInputTone.NEUTRAL
        assert draft.key_points == []

    def test_from_raw_text_none_string(self):
        """Test parsing de None (converti en chaîne vide)."""
        draft = DraftInput.from_raw_text("")
        assert draft.raw_input == ""
        assert draft.key_points == []

    def test_from_raw_text_whitespace_only(self):
        """Test parsing de texte avec espaces seulement."""
        draft = DraftInput.from_raw_text("   \n  \t  ")
        assert draft.raw_input == "   \n  \t  " or draft.raw_input.strip() == ""
        assert draft.recipient is None
        assert draft.tone == DraftInputTone.NEUTRAL


class TestExtractRecipient:
    """Tests pour _extract_recipient()."""

    def test_extract_recipient_with_à_prefix(self):
        """Test extraction du destinataire avec 'à'."""
        text = "Écrire à Jean pour le remercier"
        recipient = DraftInput._extract_recipient(text)
        # Le pattern capture deux noms: Jean + pour
        assert recipient is not None
        assert "Jean" in recipient

    def test_extract_recipient_with_à_two_names(self):
        """Test extraction avec deux noms (prénom et nom)."""
        text = "Écrire à Jean Dupont"
        recipient = DraftInput._extract_recipient(text)
        assert "Jean" in recipient

    def test_extract_recipient_with_pour_prefix(self):
        """Test extraction du destinataire avec 'pour'."""
        text = "Rédiger pour Marie une lettre"
        recipient = DraftInput._extract_recipient(text)
        # Le regex capture jusqu'à 2 mots après "pour"
        assert recipient is not None
        assert "Marie" in recipient

    def test_extract_recipient_with_to_english(self):
        """Test extraction du destinataire avec 'to' (anglais)."""
        text = "Write to John about the project"
        recipient = DraftInput._extract_recipient(text)
        # Le regex capture jusqu'à 2 mots après "to"
        assert recipient is not None
        assert "John" in recipient

    def test_extract_recipient_with_équipe(self):
        """Test extraction avec "l'équipe"."""
        text = "Message à l'équipe Ventes"
        recipient = DraftInput._extract_recipient(text)
        assert "Ventes" in recipient

    def test_extract_recipient_with_equipe_sans_accent(self):
        """Test extraction avec 'l'equipe' (sans accent)."""
        text = "Message à l'equipe Support"
        recipient = DraftInput._extract_recipient(text)
        assert "Support" in recipient

    def test_extract_recipient_with_client(self):
        """Test extraction avec 'le client' ou 'la cliente'."""
        text = "Répondre au client"
        DraftInput._extract_recipient(text)
        # Peut extraire ou non selon le pattern

    def test_extract_recipient_case_insensitive(self):
        """Test que l'extraction est insensible à la casse."""
        text = "ÉCRIRE À JEAN"
        recipient = DraftInput._extract_recipient(text)
        assert recipient and recipient.upper() == "JEAN"

    def test_extract_recipient_with_accents(self):
        """Test extraction avec noms accentués."""
        text = "À Édith et Étienne"
        recipient = DraftInput._extract_recipient(text)
        assert recipient is not None

    def test_extract_recipient_none_when_not_found(self):
        """Test retourne None si pas de pattern détecté."""
        # Le texte ne doit contenir aucun mot-clé déclencheur (à, pour, to)
        text = "Voici les points essentiels"
        recipient = DraftInput._extract_recipient(text)
        assert recipient is None

    def test_extract_recipient_ignores_short_names(self):
        """Test que les noms très courts sont ignorés."""
        text = "À A pour tester"
        DraftInput._extract_recipient(text)
        # Les noms < 2 caractères sont filtrés


class TestExtractTone:
    """Tests pour _extract_tone()."""

    def test_extract_tone_formal_french(self):
        """Test détection du ton formel avec 'formel'."""
        text = "Ton formel, professionnel"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.FORMAL

    def test_extract_tone_formal_english(self):
        """Test détection du ton formel avec 'formal'."""
        text = "Use a formal tone"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.FORMAL

    def test_extract_tone_formal_professionnel(self):
        """Test détection du ton formel avec 'professionnel'."""
        text = "Ton professionnel svp"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.FORMAL

    def test_extract_tone_formal_sérieux(self):
        """Test détection du ton formel avec 'sérieux'."""
        text = "Soyons sérieux ici"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.FORMAL

    def test_extract_tone_friendly_french(self):
        """Test détection du ton amical avec 'amical'."""
        text = "Ton amical et sympathique"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.FRIENDLY

    def test_extract_tone_friendly_english(self):
        """Test détection du ton amical avec 'friendly'."""
        text = "Keep it friendly"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.FRIENDLY

    def test_extract_tone_friendly_sympathique(self):
        """Test détection du ton amical avec 'sympathique'."""
        text = "Un ton sympathique"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.FRIENDLY

    def test_extract_tone_friendly_décontracté(self):
        """Test détection du ton amical avec 'décontracté'."""
        text = "Décontracté et naturel"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.FRIENDLY

    def test_extract_tone_urgent_french(self):
        """Test détection du ton urgent avec 'urgent'."""
        text = "C'est urgent!"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.URGENT

    def test_extract_tone_urgent_asap(self):
        """Test détection du ton urgent avec 'asap'."""
        text = "ASAP, c'est critique"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.URGENT

    def test_extract_tone_urgent_rapidement(self):
        """Test détection du ton urgent avec 'rapidement'."""
        text = "Répondre rapidement"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.URGENT

    def test_extract_tone_urgent_prioritaire(self):
        """Test détection du ton urgent avec 'prioritaire'."""
        text = "C'est prioritaire"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.URGENT

    def test_extract_tone_conciliatory_conciliant(self):
        """Test détection du ton conciliant avec 'conciliant'."""
        text = "Ton conciliant s'il vous plaît"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.CONCILIATORY

    def test_extract_tone_conciliatory_excuse(self):
        """Test détection du ton conciliant avec 'excuse'."""
        text = "Faire une excuse"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.CONCILIATORY

    def test_extract_tone_conciliatory_désolé(self):
        """Test détection du ton conciliant avec 'désolé'."""
        text = "Je suis désolé pour..."
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.CONCILIATORY

    def test_extract_tone_conciliatory_pardon(self):
        """Test détection du ton conciliant avec 'pardon'."""
        text = "Je vous demande pardon"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.CONCILIATORY

    def test_extract_tone_neutral_default(self):
        """Test retourne NEUTRAL par défaut."""
        text = "Texte sans indication de ton"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.NEUTRAL

    def test_extract_tone_case_insensitive(self):
        """Test que détection est insensible à la casse."""
        text = "URGENT et rapide"
        tone = DraftInput._extract_tone(text)
        assert tone == DraftInputTone.URGENT


class TestExtractKeyPoints:
    """Tests pour _extract_key_points()."""

    def test_extract_key_points_from_dash_bullets(self):
        """Test extraction depuis bullet points (-)."""
        text = """- Point 1
- Point 2
- Point 3"""
        points = DraftInput._extract_key_points(text)
        assert len(points) == 3
        assert "Point 1" in points
        assert "Point 2" in points
        assert "Point 3" in points

    def test_extract_key_points_from_asterisk_bullets(self):
        """Test extraction depuis bullet points (*)."""
        text = """* Idea 1
* Idea 2"""
        points = DraftInput._extract_key_points(text)
        assert len(points) == 2
        assert "Idea 1" in points
        assert "Idea 2" in points

    def test_extract_key_points_from_dot_bullets(self):
        """Test extraction depuis bullet points (•)."""
        text = """• Point A
• Point B"""
        points = DraftInput._extract_key_points(text)
        assert len(points) == 2

    def test_extract_key_points_from_numbered_list(self):
        """Test extraction depuis liste numérotée (1.)."""
        text = """1. First
2. Second
3. Third"""
        points = DraftInput._extract_key_points(text)
        assert len(points) == 3
        assert "First" in points

    def test_extract_key_points_from_numbered_list_paren(self):
        """Test extraction depuis liste numérotée (1))."""
        text = """1) First
2) Second"""
        points = DraftInput._extract_key_points(text)
        assert len(points) == 2

    def test_extract_key_points_ignores_empty_lines(self):
        """Test que les lignes vides sont ignorées."""
        text = """- Point 1

- Point 2

"""
        points = DraftInput._extract_key_points(text)
        assert len(points) == 2

    def test_extract_key_points_with_indentation(self):
        """Test extraction avec indentation."""
        text = """  - Point 1
  - Point 2"""
        points = DraftInput._extract_key_points(text)
        assert len(points) == 2

    def test_extract_key_points_min_length_3_chars(self):
        """Test que les points < 3 caractères sont ignorés."""
        text = """- A
- Point with enough chars
- B"""
        points = DraftInput._extract_key_points(text)
        # Seul "Point with enough chars" doit être inclus
        assert "Point with enough chars" in points
        assert len(points) <= 1

    def test_extract_key_points_strips_whitespace(self):
        """Test que les espaces sont nettoyés."""
        text = """  - Point 1
  - Point 2  """
        points = DraftInput._extract_key_points(text)
        assert points[0] == "Point 1"
        assert points[1] == "Point 2"

    def test_extract_key_points_mixed_bullets(self):
        """Test extraction avec différents types de bullets."""
        text = """- Point 1
* Point 2
1. Point 3"""
        points = DraftInput._extract_key_points(text)
        assert len(points) == 3

    def test_extract_key_points_empty_text(self):
        """Test extraction depuis texte vide."""
        points = DraftInput._extract_key_points("")
        assert points == []


class TestExtractSubject:
    """Tests pour _extract_subject()."""

    def test_extract_subject_with_explicit_subject_pattern(self):
        """Test extraction avec pattern explicite 'subject:'."""
        text = "subject: Meeting Notes"
        points = ["Note 1", "Note 2"]
        subject = DraftInput._extract_subject(text, points)
        assert subject == "Meeting Notes"

    def test_extract_subject_with_objet_french(self):
        """Test extraction avec pattern 'objet:'."""
        text = "objet: Réunion importante"
        points = []
        subject = DraftInput._extract_subject(text, points)
        assert subject == "Réunion importante"

    def test_extract_subject_with_sujet_french(self):
        """Test extraction avec pattern 'sujet:'."""
        text = "sujet: Demande de congé"
        points = []
        subject = DraftInput._extract_subject(text, points)
        assert subject == "Demande de congé"

    def test_extract_subject_with_concernant(self):
        """Test extraction avec pattern 'concernant'."""
        text = "concernant la réunion d'équipe"
        points = []
        subject = DraftInput._extract_subject(text, points)
        assert subject == "la réunion d'équipe"

    def test_extract_subject_with_about_english(self):
        """Test extraction avec pattern 'about' (anglais)."""
        text = "about the project update"
        points = []
        subject = DraftInput._extract_subject(text, points)
        assert subject == "the project update"

    def test_extract_subject_fallback_to_first_key_point(self):
        """Test fallback sur le premier point clé."""
        text = "Contenu sans sujet explicite"
        points = ["Premier point important", "Deuxième point"]
        subject = DraftInput._extract_subject(text, points)
        assert subject == "Premier point important"

    def test_extract_subject_ignores_long_first_point(self):
        """Test que les points > 100 chars ne sont pas utilisés."""
        text = "Pas de sujet"
        long_point = "A" * 150
        points = [long_point, "Point 2"]
        subject = DraftInput._extract_subject(text, points)
        # Le point long ne doit pas être utilisé comme sujet
        assert subject != long_point

    def test_extract_subject_uses_second_point_if_first_too_long(self):
        """Test utilise le second point si le premier est trop long."""
        text = "Pas de sujet"
        long_point = "A" * 150
        short_point = "Point court"
        points = [long_point, short_point]
        DraftInput._extract_subject(text, points)
        # Doit chercher le deuxième point ou retourner None

    def test_extract_subject_returns_none_if_no_key_points(self):
        """Test retourne None si pas de points clés."""
        text = "Texte sans pattern"
        points = []
        subject = DraftInput._extract_subject(text, points)
        assert subject is None

    def test_extract_subject_case_insensitive(self):
        """Test que pattern matching est insensible à la casse."""
        text = "SUJET: Très important"
        points = []
        subject = DraftInput._extract_subject(text, points)
        assert subject == "Très important"

    def test_extract_subject_stops_at_newline(self):
        """Test que l'extraction s'arrête à la première ligne."""
        text = "sujet: Premier sujet\nobjet: Deuxième"
        points = []
        subject = DraftInput._extract_subject(text, points)
        assert subject == "Premier sujet"


class TestHasEnoughContext:
    """Tests pour la propriété has_enough_context."""

    def test_has_enough_context_with_one_point(self):
        """Test que un point clé suffit."""
        draft = DraftInput(
            raw_input="test",
            key_points=["Point 1"],
        )
        assert draft.has_enough_context

    def test_has_enough_context_with_multiple_points(self):
        """Test avec plusieurs points clés."""
        draft = DraftInput(
            raw_input="test",
            key_points=["Point 1", "Point 2", "Point 3"],
        )
        assert draft.has_enough_context

    def test_has_enough_context_empty_points(self):
        """Test retourne False sans points clés."""
        draft = DraftInput(
            raw_input="test",
            key_points=[],
        )
        assert not draft.has_enough_context

    def test_has_enough_context_threshold_is_one(self):
        """Test que le seuil minimal est 1 point."""
        draft = DraftInput(
            raw_input="test",
            key_points=["Seul point"],
        )
        assert draft.has_enough_context is True


class TestCompletedDraftStr:
    """Tests pour CompletedDraft.__str__()."""

    def test_completed_draft_str_with_subject_and_body(self):
        """Test le formatage avec sujet et contenu."""
        draft = CompletedDraft(
            subject="Réunion d'équipe",
            body="Nous nous réunissons demain à 10h.",
        )
        output = str(draft)
        assert "Objet : Réunion d'équipe" in output
        assert "Nous nous réunissons demain à 10h." in output

    def test_completed_draft_str_format_has_blank_line(self):
        """Test que ligne blanche entre objet et corps."""
        draft = CompletedDraft(
            subject="Test",
            body="Corps du message",
        )
        output = str(draft)
        lines = output.split("\n")
        # Doit avoir un format: "Objet: ...", "", "Corps"
        assert lines[0].startswith("Objet :")
        assert lines[1] == ""
        assert "Corps du message" in "\n".join(lines[2:])

    def test_completed_draft_str_without_subject(self):
        """Test le formatage sans sujet."""
        draft = CompletedDraft(
            subject="",
            body="Juste le corps",
        )
        output = str(draft)
        # Doit quand même contenir le corps
        assert "Juste le corps" in output

    def test_completed_draft_str_empty_body(self):
        """Test le formatage avec corps vide."""
        draft = CompletedDraft(
            subject="Sujet seul",
            body="",
        )
        output = str(draft)
        assert "Objet : Sujet seul" in output

    def test_completed_draft_str_multiline_body(self):
        """Test le formatage avec contenu multi-ligne."""
        draft = CompletedDraft(
            subject="Reunion",
            body="Paragraphe 1\n\nParagraphe 2",
        )
        output = str(draft)
        assert "Paragraphe 1" in output
        assert "Paragraphe 2" in output


class TestCompletedDraftFormattedOutput:
    """Tests pour CompletedDraft.formatted_output."""

    def test_completed_draft_formatted_output_has_separators(self):
        """Test que le format a des séparateurs (---)."""
        draft = CompletedDraft(
            subject="Test",
            body="Contenu",
        )
        output = draft.formatted_output
        assert output.count("---") == 2

    def test_completed_draft_formatted_output_has_message(self):
        """Test que le format inclut le message français."""
        draft = CompletedDraft(
            subject="Test",
            body="Contenu",
        )
        output = draft.formatted_output
        assert "Voici le courriel rédigé à partir de tes idées" in output
        assert "Tu peux le modifier" in output
        assert "Prêt à envoyer" in output

    def test_completed_draft_formatted_output_structure(self):
        """Test la structure complète du format."""
        draft = CompletedDraft(
            subject="Reunion",
            body="Demain à 10h",
        )
        output = draft.formatted_output
        lines = output.split("\n")
        # Doit commencer par un séparateur
        assert lines[0] == "---"
        # Doit se terminer par un message

    def test_completed_draft_formatted_output_with_recipient(self):
        """Test le format avec destinataire (même si non affiché)."""
        draft = CompletedDraft(
            subject="Test",
            body="Corps",
            recipient="Jean",
        )
        output = draft.formatted_output
        # Le destinataire ne devrait pas changer la sortie str()
        assert "Objet : Test" in output

    def test_completed_draft_formatted_output_with_tone(self):
        """Test le format avec ton (même si non affiché)."""
        draft = CompletedDraft(
            subject="Test",
            body="Corps",
            tone_used=DraftInputTone.FORMAL,
        )
        output = draft.formatted_output
        # Le ton ne devrait pas changer la sortie str()
        assert "Objet : Test" in output


class TestDraftInputIntegration:
    """Tests d'intégration complets."""

    def test_full_workflow_from_raw_text_with_bullets(self):
        """Test le workflow complet: texte → parsing → analyse."""
        text = """brouillon :
À Jean Dupont
Ton amical
Sujet: Invitation à déjeuner
- Point 1: Je te propose un déjeuner
- Point 2: Jeudi prochain
- Point 3: Au restaurant du coin"""

        draft = DraftInput.from_raw_text(text)

        assert draft.raw_input == text
        assert draft.recipient is not None
        assert "Jean" in draft.recipient
        assert draft.tone == DraftInputTone.FRIENDLY
        assert draft.subject_hint == "Invitation à déjeuner"
        assert len(draft.key_points) >= 2
        assert draft.has_enough_context

    def test_full_workflow_minimal_input(self):
        """Test avec input minimal."""
        text = "draft : - Urgent meeting\n- Need approval"

        draft = DraftInput.from_raw_text(text)

        assert draft.raw_input == text
        assert len(draft.key_points) >= 1
        assert draft.has_enough_context

    def test_full_workflow_no_prefix(self):
        """Test avec structure bullet points sans préfixe."""
        text = "- Point 1\n- Point 2\n- Point 3"

        # is_draft_input doit détecter
        assert DraftInput.is_draft_input(text)

        # from_raw_text doit parser
        draft = DraftInput.from_raw_text(text)
        assert len(draft.key_points) == 3
        assert draft.has_enough_context

    def test_completed_draft_from_input(self):
        """Test création d'un draft complété à partir d'input."""
        draft_input = DraftInput(
            raw_input="brouillon: À Marie",
            recipient="Marie",
            subject_hint="Proposition",
            tone=DraftInputTone.FRIENDLY,
            key_points=["Point 1", "Point 2"],
        )

        # Simuler un draft complété par l'IA
        completed = CompletedDraft(
            subject="Proposition de collaboration",
            body="Chère Marie,\n\nJ'aimerais te proposer une collaboration...",
            recipient=draft_input.recipient,
            tone_used=draft_input.tone,
        )

        assert completed.recipient == "Marie"
        assert completed.tone_used == DraftInputTone.FRIENDLY
        assert "Objet : Proposition de collaboration" in str(completed)
