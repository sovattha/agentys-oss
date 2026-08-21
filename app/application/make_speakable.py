# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Case : Convertir un email en texte prononçable (TTS).
"""

import logging
import random
from dataclasses import dataclass

from app.utils.email_cleaner import clean_email_content
from app.utils.tts_cleaner import clean_for_tts

_logger = logging.getLogger(__name__)

# Langues supportées par le registre conversationnel. La langue vient du
# device mobile (i18n.language), pas du contenu de l'email — l'utilisateur
# veut entendre SON registre, même pour un email reçu dans une autre langue.
_SUPPORTED_LANGS = {"fr", "en", "es"}

_INTRO_TEMPLATES = {
    "fr": [
        lambda name: f"{name} t'écrit.",
        lambda name: f"Tu as un message de {name}.",
        lambda name: f"{name} te contacte.",
        lambda name: f"Un email de {name} vient d'arriver.",
    ],
    "en": [
        lambda name: f"{name} wrote to you.",
        lambda name: f"You've got a message from {name}.",
        lambda name: f"{name} is reaching out.",
        lambda name: f"New email from {name}.",
    ],
    "es": [
        lambda name: f"{name} te escribe.",
        lambda name: f"Tienes un mensaje de {name}.",
        lambda name: f"{name} te contacta.",
        lambda name: f"Acaba de llegar un correo de {name}.",
    ],
}

_EMPTY_BODY = {
    "fr": "Le message est vide.",
    "en": "The message is empty.",
    "es": "El mensaje está vacío.",
}

_NO_SENDER_INTRO = {
    "fr": "Nouveau message.",
    "en": "New message.",
    "es": "Mensaje nuevo.",
}

_HAIKU_RULES = (
    "SUPPRIME ABSOLUMENT (ne les lis jamais) :\n"
    "- Salutations d'ouverture : Bonjour, Cher X, Hello, Bonsoir, Madame/Monsieur\n"
    "- Formules de clôture : Cordialement, Bien à vous/toi, Best regards, Kind regards, "
    "Salutations, Amicalement, À bientôt, Merci d'avance, En vous remerciant, "
    "Looking forward, Warm regards, Bisous, Bien cordialement\n"
    "- Signatures : nom, prénom, titre, poste, entreprise, numéro de téléphone, adresse\n"
    "- Disclaimers légaux, mentions de confidentialité\n"
    "- Lignes vides répétées\n"
    "Conserve TOUTES les infos importantes : dates, montants, questions posées, "
    "actions demandées, liens importants (remplace-les par 'un lien'). "
    "Registre parlé : phrases courtes, pas de tournures écrites. "
    "Maximum 90 mots. N'invente jamais d'informations absentes de l'email."
)

_HAIKU_SYSTEM_BY_LANG = {
    "fr": (
        "Tu es un assistant vocal qui lit des emails à voix haute à leur propriétaire "
        "(en voiture ou en déplacement). Reformule l'email en texte parlé naturel et fluide "
        "en FRANÇAIS, en tutoyant — même si l'email est dans une autre langue. Commence "
        "directement par le contenu sans jamais dire 'Voici l'email' ou 'Je te lis'.\n"
        + _HAIKU_RULES
    ),
    "en": (
        "You are a voice assistant reading emails aloud to their owner (driving or on "
        "the move). Rewrite the email as natural, flowing SPOKEN ENGLISH — even if the "
        "email is in another language. Start directly with the content; never say "
        "'Here is the email' or 'Let me read'.\n"
        + _HAIKU_RULES
    ),
    "es": (
        "Eres un asistente de voz que lee correos en voz alta a su propietario "
        "(conduciendo o en movimiento). Reformula el correo en ESPAÑOL hablado, natural y "
        "fluido, tuteando — aunque el correo esté en otro idioma. Empieza directamente por "
        "el contenido; nunca digas 'Aquí está el correo'.\n"
        + _HAIKU_RULES
    ),
}


@dataclass
class SpeakableResult:
    """Résultat de la conversion TTS."""
    email_id: str
    subject: str
    sender_name: str
    speakable_text: str


@dataclass
class MakeSpeakableUseCase:
    """
    Convertit le contenu d'un email en texte optimisé pour la synthèse vocale.

    Pipeline (conversational=True)  : Haiku script → fallback template si erreur
    Pipeline (conversational=False) : clean_email_content() → intro template → clean_for_tts()
    """

    def execute(
        self,
        email_id: str,
        body: str,
        subject: str,
        sender_name: str,
        conversational: bool = False,
        lang: str = "fr",
    ) -> SpeakableResult:
        if lang not in _SUPPORTED_LANGS:
            lang = "fr"
        cleaned, _metadata = clean_email_content(body, subject)
        speakable_body = clean_for_tts(cleaned)

        if conversational and speakable_body:
            haiku_script = self._build_haiku_script(sender_name, subject, speakable_body, lang)
            if haiku_script:
                # On préfixe TOUJOURS par l'intro naturelle (« Marie t'écrit… »)
                # — Haiku est instruit de commencer direct par le contenu, donc
                # sans ce préfixe l'utilisateur ne sait pas de qui vient l'email.
                intro = self._build_natural_intro(sender_name, subject, lang)
                full_text = f"{intro} {haiku_script}" if intro else haiku_script
                return SpeakableResult(
                    email_id=email_id,
                    subject=subject,
                    sender_name=sender_name,
                    speakable_text=full_text,
                )

        intro = self._build_natural_intro(sender_name, subject, lang)
        full_text = f"{intro} {speakable_body}" if speakable_body else f"{intro} {_EMPTY_BODY[lang]}"

        return SpeakableResult(
            email_id=email_id,
            subject=subject,
            sender_name=sender_name,
            speakable_text=full_text,
        )

    @staticmethod
    def _build_haiku_script(sender_name: str, subject: str, body: str, lang: str = "fr") -> str | None:
        """Génère un script conversationnel via Haiku. Retourne None si indisponible."""
        import os
        if not os.getenv("ANTHROPIC_API_KEY"):
            return None
        try:
            from app.adapters.llm.claude_adapter import ClaudeAdapter
            from app.config import CLAUDE_MODEL_LABEL
            adapter = ClaudeAdapter(model=CLAUDE_MODEL_LABEL)
            name = sender_name.strip() if sender_name else "quelqu'un"
            subj = subject.strip() if subject else "(sans sujet)"
            user_prompt = (
                f"Email de {name} — Sujet : {subj}\n\n{body[:1500]}"
            )
            response = adapter.complete(
                system=_HAIKU_SYSTEM_BY_LANG.get(lang, _HAIKU_SYSTEM_BY_LANG["fr"]),
                user=user_prompt,
                max_tokens=180,
            )
            script = response.content.strip() if response and response.content else ""
            if len(script) > 30:
                return script
            return None
        except Exception as exc:
            _logger.debug("Haiku speakable fallback: %s", exc)
            return None

    @staticmethod
    def _build_natural_intro(sender_name: str, subject: str, lang: str = "fr") -> str:
        """Construit une introduction naturelle avec variation. Le sujet est
        volontairement omis : il est affiché à l'écran et l'utilisateur ne veut
        pas l'entendre avant le corps."""
        if lang not in _SUPPORTED_LANGS:
            lang = "fr"
        name = sender_name.strip() if sender_name else ""
        if name:
            return random.choice(_INTRO_TEMPLATES[lang])(name)
        return _NO_SENDER_INTRO[lang]
