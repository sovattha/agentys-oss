# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour app.application.make_speakable."""

from app.application.make_speakable import MakeSpeakableUseCase, SpeakableResult

_KNOWN_INTROS = ["écrit", "vient d'arriver", "te contacte", "tu as un message", "tu as un mail", "message de", "email de"]


def _has_natural_intro(text: str, name: str) -> bool:
    """Vérifie que le texte contient le nom ET une formulation naturelle connue."""
    lower = text.lower()
    return name.lower() in lower and any(kw in lower for kw in _KNOWN_INTROS)


def _intro_omits_subject(text: str, subject: str) -> bool:
    """Le sujet ne doit JAMAIS apparaître dans l'intro vocale."""
    if not subject:
        return True
    # On vérifie que l'intro ne contient pas le sujet avant le corps
    lower = text.lower()
    return f"sujet : {subject.lower()}" not in lower and f"au sujet de {subject.lower()}" not in lower


class TestMakeSpeakableUseCase:
    def test_execute_returns_speakable_result(self):
        use_case = MakeSpeakableUseCase()
        result = use_case.execute(
            email_id="msg-123",
            body="Bonjour, voici le lien https://example.com",
            subject="Test",
            sender_name="Jean Dupont",
        )
        assert isinstance(result, SpeakableResult)
        assert result.email_id == "msg-123"
        assert result.subject == "Test"
        assert result.sender_name == "Jean Dupont"
        assert "lien" in result.speakable_text
        assert "https://" not in result.speakable_text
        # Intro naturelle : contient le nom et une formulation connue
        assert _has_natural_intro(result.speakable_text, "Jean Dupont")

    def test_execute_empty_body(self):
        use_case = MakeSpeakableUseCase()
        result = use_case.execute(
            email_id="msg-456",
            body="",
            subject="Vide",
            sender_name="Alice",
        )
        assert "alice" in result.speakable_text.lower()
        assert "Le message est vide" in result.speakable_text

    def test_execute_preserves_metadata(self):
        use_case = MakeSpeakableUseCase()
        result = use_case.execute(
            email_id="abc-789",
            body="Un simple message texte.",
            subject="Sujet important",
            sender_name="Bob Martin",
        )
        assert result.email_id == "abc-789"
        assert result.subject == "Sujet important"
        assert result.sender_name == "Bob Martin"
        assert "simple message" in result.speakable_text
        assert _has_natural_intro(result.speakable_text, "Bob Martin")

    def test_execute_cleans_email_content(self):
        """Vérifie que clean_email_content est appliqué (signatures supprimées)."""
        body_with_signature = "Bonjour,\n\nMerci pour votre email.\n\n--\nJean Dupont\nDirecteur"
        use_case = MakeSpeakableUseCase()
        result = use_case.execute(
            email_id="sig-test",
            body=body_with_signature,
            subject="Test signature",
            sender_name="Jean",
        )
        # La signature devrait être supprimée par clean_email_content
        assert "Directeur" not in result.speakable_text
        assert "Merci pour votre email" in result.speakable_text

    def test_natural_intro_no_subject(self):
        """Sujet vide → intro contient le nom sans sujet."""
        use_case = MakeSpeakableUseCase()
        result = use_case.execute(
            email_id="no-subj",
            body="Salut, ça va ?",
            subject="",
            sender_name="Marie",
        )
        assert "marie" in result.speakable_text.lower()
        assert any(kw in result.speakable_text.lower() for kw in _KNOWN_INTROS)

    def test_natural_intro_generic_subject(self):
        """Sujets génériques (Re:, Fwd:) → traités comme vides."""
        use_case = MakeSpeakableUseCase()
        for subj in ["Re:", "Fwd:", "(pas de sujet)", "no subject"]:
            result = use_case.execute(
                email_id="gen-subj",
                body="Contenu test.",
                subject=subj,
                sender_name="Paul",
            )
            assert "paul" in result.speakable_text.lower()
            assert any(kw in result.speakable_text.lower() for kw in _KNOWN_INTROS)

    def test_natural_intro_no_sender(self):
        """Pas d'expéditeur → intro anonyme, sans sujet."""
        use_case = MakeSpeakableUseCase()
        result = use_case.execute(
            email_id="no-sender",
            body="Hello",
            subject="Offre",
            sender_name="",
        )
        assert result.speakable_text.startswith("Nouveau message.")
        assert "Offre" not in result.speakable_text.split(". ", 1)[0]

    def test_intro_never_announces_subject(self):
        """Le sujet doit être affiché à l'écran, jamais lu avant le corps."""
        use_case = MakeSpeakableUseCase()
        for subj in ["Facture 2024", "Réunion budget", "Question urgente"]:
            result = use_case.execute(
                email_id="subj-test",
                body="Contenu du message ici.",
                subject=subj,
                sender_name="Marie",
            )
            assert _intro_omits_subject(result.speakable_text, subj), \
                f"Sujet '{subj}' ne doit pas apparaître dans l'intro: {result.speakable_text!r}"

    def test_conversational_flag_fallback_without_api_key(self):
        """Avec conversational=True mais sans clé API → fallback template silencieux."""
        import os
        orig = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            use_case = MakeSpeakableUseCase()
            result = use_case.execute(
                email_id="conv-test",
                body="Réunion demain 14h.",
                subject="Réunion",
                sender_name="Alex",
                conversational=True,
            )
            # Doit fallback vers le template sans erreur
            assert isinstance(result, SpeakableResult)
            assert "alex" in result.speakable_text.lower()
        finally:
            if orig is not None:
                os.environ["ANTHROPIC_API_KEY"] = orig


class TestMakeSpeakableLang:
    """La langue du registre parlé suit le DEVICE (i18n mobile), pas le
    contenu de l'email. Défaut fr (back-compat), en/es supportés, langue
    inconnue → fr."""

    def test_default_lang_is_french(self):
        result = MakeSpeakableUseCase().execute(
            email_id="l1", body="Contenu.", subject="S", sender_name="Marie",
        )
        assert any(kw in result.speakable_text.lower() for kw in _KNOWN_INTROS)

    def test_english_intro(self):
        result = MakeSpeakableUseCase().execute(
            email_id="l2", body="Some content.", subject="S",
            sender_name="Marie", lang="en",
        )
        lower = result.speakable_text.lower()
        assert "marie" in lower
        assert any(kw in lower for kw in ["wrote to you", "message from", "reaching out", "new email from"])

    def test_spanish_intro(self):
        result = MakeSpeakableUseCase().execute(
            email_id="l3", body="Contenido.", subject="S",
            sender_name="Marie", lang="es",
        )
        lower = result.speakable_text.lower()
        assert any(kw in lower for kw in ["te escribe", "mensaje de", "te contacta", "un correo de"])

    def test_unknown_lang_falls_back_to_french(self):
        result = MakeSpeakableUseCase().execute(
            email_id="l4", body="Inhalt.", subject="S",
            sender_name="Hans", lang="de",
        )
        assert any(kw in result.speakable_text.lower() for kw in _KNOWN_INTROS)

    def test_empty_body_localized(self):
        result = MakeSpeakableUseCase().execute(
            email_id="l5", body="", subject="S",
            sender_name="Marie", lang="en",
        )
        assert "The message is empty." in result.speakable_text

    def test_no_sender_localized(self):
        result = MakeSpeakableUseCase().execute(
            email_id="l6", body="Hello", subject="S",
            sender_name="", lang="es",
        )
        assert result.speakable_text.startswith("Mensaje nuevo.")
