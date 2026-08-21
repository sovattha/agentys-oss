# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Entité DraftInput pour la complétion de brouillons."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
import re


class DraftInputTone(Enum):
    """Ton souhaité pour le courriel."""
    FORMAL = "formal"
    FRIENDLY = "friendly"
    URGENT = "urgent"
    CONCILIATORY = "conciliatory"
    NEUTRAL = "neutral"


@dataclass
class DraftInput:
    """
    Représente les idées brèves fournies par l'utilisateur
    pour générer un courriel complet.

    L'utilisateur fournit des bullet points ou idées courtes,
    et l'IA les transforme en email professionnel.
    """
    raw_input: str
    recipient: Optional[str] = None
    subject_hint: Optional[str] = None
    tone: DraftInputTone = DraftInputTone.NEUTRAL
    key_points: List[str] = field(default_factory=list)

    # Base des préfixes (les variantes avec/sans espace après ":" sont générées)
    _TRIGGER_BASE = (
        "à compléter",
        "a compléter",  # variante sans accent
        "brouillon",
        "draft",
        "ébauche",
        "idées pour email",
        "rédige à partir de ça",
    )

    # Préfixes qui déclenchent le mode complétion
    # Génération des variantes avec/sans espace après ":"
    TRIGGER_PREFIXES = tuple(
        variant
        for base in _TRIGGER_BASE
        for variant in (f"{base} :", f"{base}:")
    )

    @classmethod
    def is_draft_input(cls, text: str) -> bool:
        """
        Détecte si le texte est une demande de complétion de brouillon.

        Critères :
        - Commence par un préfixe connu (Brouillon:, Draft:, etc.)
        - Contient principalement des bullet points
        - Contient des phrases courtes sans salutation complète

        Args:
            text: Le texte à analyser.

        Returns:
            True si c'est une demande de complétion.
        """
        if not text:
            return False

        text_lower = text.lower().strip()

        # Vérifier les préfixes explicites
        for prefix in cls.TRIGGER_PREFIXES:
            if text_lower.startswith(prefix):
                return True

        # Détecter les bullet points (-, *, •, numérotation)
        lines = text.strip().split('\n')
        bullet_pattern = re.compile(r'^[\s]*[-*•]|\d+[.)]')
        bullet_count = sum(1 for line in lines if bullet_pattern.match(line.strip()))

        # Si plus de 50% des lignes sont des bullet points
        if len(lines) >= 2 and bullet_count / len(lines) >= 0.5:
            return True

        return False

    @classmethod
    def from_raw_text(cls, text: str) -> "DraftInput":
        """
        Parse le texte brut pour extraire les informations structurées.

        Args:
            text: Le texte brut de l'utilisateur.

        Returns:
            Un objet DraftInput structuré.
        """
        if not text:
            return cls(
                raw_input=text or "",
                recipient=None,
                subject_hint=None,
                tone=DraftInputTone.NEUTRAL,
                key_points=[],
            )

        # Nettoyer les préfixes
        cleaned_text = text
        text_lower = text.lower().strip()

        for prefix in cls.TRIGGER_PREFIXES:
            if text_lower.startswith(prefix):
                cleaned_text = text[len(prefix):].strip()
                break

        # Extraire les informations
        recipient = cls._extract_recipient(cleaned_text)
        tone = cls._extract_tone(cleaned_text)
        key_points = cls._extract_key_points(cleaned_text)
        subject_hint = cls._extract_subject(cleaned_text, key_points)

        return cls(
            raw_input=text,
            recipient=recipient,
            subject_hint=subject_hint,
            tone=tone,
            key_points=key_points,
        )

    @staticmethod
    def _extract_recipient(text: str) -> Optional[str]:
        """Extrait le destinataire du texte."""
        patterns = [
            r'(?:à|pour|to)\s+([A-ZÀ-Ÿa-zà-ÿ]+(?:\s+[A-ZÀ-Ÿa-zà-ÿ]+)?)',
            r"(?:l'équipe|l'equipe)\s+([A-Za-z]+)",
            r'(?:le client|la cliente)\s*([A-Za-z]*)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                recipient = match.group(1).strip()
                if recipient and len(recipient) > 1:
                    return recipient

        return None

    @staticmethod
    def _extract_tone(text: str) -> DraftInputTone:
        """Détecte le ton souhaité depuis le texte."""
        text_lower = text.lower()

        tone_keywords = {
            DraftInputTone.FORMAL: ['formel', 'formal', 'professionnel', 'sérieux'],
            DraftInputTone.FRIENDLY: ['amical', 'friendly', 'sympathique', 'décontracté'],
            DraftInputTone.URGENT: ['urgent', 'asap', 'rapidement', 'prioritaire'],
            DraftInputTone.CONCILIATORY: ['conciliant', 'excuse', 'désolé', 'pardon'],
        }

        for tone, keywords in tone_keywords.items():
            if any(kw in text_lower for kw in keywords):
                return tone

        return DraftInputTone.NEUTRAL

    @staticmethod
    def _extract_key_points(text: str) -> List[str]:
        """Extrait les points clés sous forme de liste."""
        lines = text.strip().split('\n')
        key_points = []

        bullet_pattern = re.compile(r'^[\s]*[-*•]\s*|^\s*\d+[.)]\s*')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Nettoyer les bullets
            cleaned = bullet_pattern.sub('', line).strip()
            if cleaned and len(cleaned) > 3:
                key_points.append(cleaned)

        return key_points

    @staticmethod
    def _extract_subject(text: str, key_points: List[str]) -> Optional[str]:
        """Tente de déduire le sujet principal."""
        # Chercher des patterns explicites
        patterns = [
            r'(?:sujet|objet|subject)\s*:\s*(.+?)(?:\n|$)',
            r'(?:concernant|about)\s+(.+?)(?:\n|$)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        # Sinon, utiliser le premier point clé comme indice
        if key_points:
            first_point = key_points[0]
            if len(first_point) < 100:
                return first_point

        return None

    @property
    def has_enough_context(self) -> bool:
        """Vérifie si on a assez de contexte pour générer un email."""
        return len(self.key_points) >= 1


@dataclass
class CompletedDraft:
    """Représente un brouillon complété par l'IA."""
    subject: str
    body: str
    recipient: Optional[str] = None
    tone_used: DraftInputTone = DraftInputTone.NEUTRAL

    def __str__(self) -> str:
        """Retourne le brouillon formaté."""
        output = []
        if self.subject:
            output.append(f"Objet : {self.subject}")
        output.append("")
        output.append(self.body)
        return "\n".join(output)

    @property
    def formatted_output(self) -> str:
        """Retourne le brouillon avec séparateurs."""
        lines = ["---", str(self), "---"]
        lines.append("")
        lines.append(
            "Voici le courriel rédigé à partir de tes idées. "
            "Tu peux le modifier ou me demander des ajustements "
            "(ton, longueur, ajout/suppression de points, etc.). "
            "Prêt à envoyer ?"
        )
        return "\n".join(lines)
